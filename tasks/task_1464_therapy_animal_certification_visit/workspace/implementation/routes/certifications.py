"""Certification endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err, err_not_found
from middleware import get_auth, require_roles
from response import success_object, success_list, paginate
from services import cascades, gates
from services.records import new_record, touch, public
from util import today, parse_date, parse_datetime
from validate import get_body, validate_body

bp = Blueprint("certifications", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]

CERT_PERIOD_DAYS = 730
LATE_RENEWAL_GRACE_DAYS = 90
RENEWAL_MIN_VERIFIED_VISITS = 6


def _get_cert(cert_id):
    c = store.certifications.get(cert_id)
    if c is None:
        raise err_not_found("certification")
    return c


@bp.post("/v1/certifications")
def create_certification():
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    body = validate_body(get_body(), {
        "team_id": ("string", True, None),
        "evaluation_id": ("string", True, None),
    })
    team = store.teams.get(body["team_id"])
    if team is None:
        raise err_not_found("team")
    evaluation = store.evaluations.get(body["evaluation_id"])
    if evaluation is None:
        raise err_not_found("evaluation")
    # State preconditions (pipeline category 7)
    if team["status"] != "FORMING":
        raise err("ERR_TEAM_NOT_FORMING", 409, "Team is not FORMING")
    if evaluation["status"] != "PASSED":
        raise err("ERR_EVALUATION_NOT_PASSED", 409, "Evaluation is not PASSED")
    if evaluation["team_id"] != team["id"]:
        raise err("ERR_EVALUATION_TEAM_MISMATCH", 409,
                  "Evaluation belongs to a different team")
    # Uniqueness (category 12)
    for c in store.certifications.values():
        if c["team_id"] == team["id"] and c["status"] in ("PROVISIONAL", "ACTIVE", "RENEWAL_DUE", "SUSPENDED"):
            raise err("ERR_ACTIVE_CERTIFICATION_EXISTS", 422,
                      "Team already has a non-terminal certification")
    rec = new_record(store.certifications, {
        "team_id": team["id"],
        "evaluation_id": evaluation["id"],
        "status": "PROVISIONAL",
        "activated_on": None,
        "expires_on": None,
        "renewal_count": 0,
        "suspension_reason": None,
        "suspension_until": None,
    })
    return success_object(public(rec), 201)


@bp.get("/v1/certifications/<cert_id>")
def get_certification(cert_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_cert(cert_id)), 200)


@bp.get("/v1/certifications")
def list_certifications():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.certifications.values())
    team_id = request.args.get("team_id")
    evaluation_id = request.args.get("evaluation_id")
    status = request.args.get("status")
    if team_id is not None:
        records = [r for r in records if r["team_id"] == team_id]
    if evaluation_id is not None:
        records = [r for r in records if r.get("evaluation_id") == evaluation_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/certifications/<cert_id>/activate")
def activate_certification(cert_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    cert = _get_cert(cert_id)
    if cert["status"] != "PROVISIONAL":
        raise err("ERR_CERT_NOT_PROVISIONAL", 409, "Certification is not PROVISIONAL")
    team = store.teams.get(cert["team_id"])
    # Safety: rabies gate against today
    gates.check_rabies(team["animal_id"], today())
    # Fiscal: program floor
    gates.check_insurance(team["handler_id"], 100000000)
    today_d = today()
    cert["status"] = "ACTIVE"
    cert["activated_on"] = today_d.isoformat()
    cert["expires_on"] = (today_d + timedelta(days=CERT_PERIOD_DAYS)).isoformat()
    touch(cert)
    cascades.activate_certification_bubble(cert)
    return success_object(public(cert), 200)


@bp.post("/v1/certifications/<cert_id>/renew")
def renew_certification(cert_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    cert = _get_cert(cert_id)
    if cert["status"] not in ("RENEWAL_DUE", "EXPIRED"):
        raise err("ERR_CERT_NOT_RENEWABLE", 409,
                  "Certification is not RENEWAL_DUE or EXPIRED")
    today_d = today()
    old_expires = parse_date(cert["expires_on"])
    team = store.teams.get(cert["team_id"])
    # Safety (category 8): rabies gate against today
    gates.check_rabies(team["animal_id"], today_d)
    # Temporal windows (category 10): late-renewal grace window
    if cert["status"] == "EXPIRED" and today_d > old_expires + timedelta(days=LATE_RENEWAL_GRACE_DAYS):
        raise err("ERR_RENEWAL_WINDOW_CLOSED", 409,
                  "The 90-day late-renewal grace window has closed")
    # Fiscal (category 11): program floor
    gates.check_insurance(team["handler_id"], 100000000)
    # Constraint (category 12): >= 6 COMPLETED+VERIFIED visits with actual_end
    # date within [activated_on, pre-renewal expires_on]
    activated_on = parse_date(cert["activated_on"])
    count = 0
    for v in store.visits.values():
        if (v["team_id"] == team["id"]
                and v["lifecycle_status"] == "COMPLETED"
                and v["verification_status"] == "VERIFIED"
                and v.get("actual_end")):
            d = parse_datetime(v["actual_end"]).date()
            if activated_on <= d <= old_expires:
                count += 1
    if count < RENEWAL_MIN_VERIFIED_VISITS:
        raise err("ERR_RENEWAL_VISIT_MINIMUM_NOT_MET", 422,
                  "Fewer than 6 COMPLETED+VERIFIED visits in the certification period")
    # Pinned order: eligibility counted above; now extend; then bump count.
    new_expires = max(today_d, old_expires) + timedelta(days=CERT_PERIOD_DAYS)
    cert["status"] = "ACTIVE"
    cert["expires_on"] = new_expires.isoformat()
    cert["renewal_count"] = cert.get("renewal_count", 0) + 1
    touch(cert)
    return success_object(public(cert), 200)


@bp.post("/v1/certifications/<cert_id>/suspend")
def suspend_certification(cert_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    cert = _get_cert(cert_id)
    body = validate_body(get_body(), {
        "reason": ("string", True, None),
        "suspension_until": ("date", False, None),
    })
    if cert["status"] not in ("ACTIVE", "RENEWAL_DUE"):
        raise err("ERR_CERT_NOT_SUSPENDABLE", 409,
                  "Certification is not ACTIVE or RENEWAL_DUE")
    cascades.suspend_certification(cert, "MANUAL", body.get("suspension_until"))
    return success_object(public(cert), 200)


@bp.post("/v1/certifications/<cert_id>/reinstate")
def reinstate_certification(cert_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    cert = _get_cert(cert_id)
    if cert["status"] != "SUSPENDED":
        raise err("ERR_CERT_NOT_SUSPENDED", 409, "Certification is not SUSPENDED")
    today_d = today()
    if cert.get("suspension_until") and today_d < parse_date(cert["suspension_until"]):
        raise err("ERR_SUSPENSION_NOT_ELAPSED", 409,
                  "suspension_until is still in the future")
    team = store.teams.get(cert["team_id"])
    # Re-gate: rabies valid today; insurance floor
    gates.check_rabies(team["animal_id"], today_d)
    gates.check_insurance(team["handler_id"], 100000000)
    cert["status"] = "ACTIVE"
    cert["suspension_reason"] = None
    cert["suspension_until"] = None
    touch(cert)
    cascades.reinstate_certification_bubble(cert)
    return success_object(public(cert), 200)


@bp.post("/v1/certifications/<cert_id>/revoke")
def revoke_certification(cert_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    cert = _get_cert(cert_id)
    validate_body(get_body(), {"reason": ("string", True, None)})
    if cert["status"] not in ("ACTIVE", "RENEWAL_DUE", "SUSPENDED"):
        raise err("ERR_CERT_NOT_REVOKABLE", 409,
                  "Certification is not ACTIVE, RENEWAL_DUE, or SUSPENDED")
    cascades.revoke_certification(cert)
    return success_object(public(cert), 200)
