"""Contractor prequalification (PRD 3.6): register, submit, decide, suspend."""

from datetime import timedelta

from flask import Blueprint, request

import db
from clock import CLOCK
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import calc, core

bp = Blueprint("contractors", __name__)

_SUBMITTABLE = ("DRAFT", "CONDITIONAL", "SUSPENDED", "EXPIRED")


@bp.route("/safety/contractor-orgs", methods=["POST"])
def create_contractor():
    auth(["ContractorRep", "EHSAdmin"])
    body = core.body_json()
    name = core.req_str(body, "name")
    contact_email = core.req_str(body, "contact_email")
    emr = core.req_num(body, "emr", minimum=0)
    trir = core.req_num(body, "trir", minimum=0)
    audit_pct = core.req_num(body, "safety_audit_pct", minimum=0)
    if audit_pct > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "safety_audit_pct must be between 0 and 100")
    expires = core.req_date(body, "insurance_cert_expires_on")
    c = core.stamp_new({
        "id": core.new_id(),
        "name": name,
        "contact_email": contact_email,
        "emr": emr,
        "trir": trir,
        "safety_audit_pct": audit_pct,
        "insurance_cert_expires_on": expires.isoformat(),
        "prequal_score": None,
        "computed_decision": None,
        "status": "DRAFT",
        "prequal_valid_until": None,
        "suspension_reason": None,
        "suspension_claim_id": None,
    })
    db.DB["contractors"][c["id"]] = c
    return ok(core.contractor_view(c), 201)


@bp.route("/safety/contractor-orgs", methods=["GET"])
def list_contractors():
    auth(ALL_ROLES)
    status = request.args.get("status")
    claim_id = request.args.get("suspension_claim_id")
    items = list(db.DB["contractors"].values())
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if claim_id is not None:
        items = [c for c in items if c["suspension_claim_id"] == claim_id]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.contractor_view(c) for c in page], total, limit, offset)


@bp.route("/safety/contractor-orgs/<cid>", methods=["GET"])
def get_contractor(cid):
    auth(ALL_ROLES)
    c = core.get_or_404("contractors", cid, "ContractorOrg")
    return ok(core.contractor_view(c))


@bp.route("/safety/contractor-orgs/<cid>/submit", methods=["POST"])
def submit_contractor(cid):
    user_id, _ = auth(["ContractorRep"])
    c = core.get_or_404("contractors", cid, "ContractorOrg")
    body = core.body_json()
    # Entity-backed ownership: the rep may submit only its own organization.
    if user_id != c["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A ContractorRep may submit only its own organization")

    updates = {}
    if "emr" in body and body["emr"] is not None:
        updates["emr"] = core.req_num(body, "emr", minimum=0)
    if "trir" in body and body["trir"] is not None:
        updates["trir"] = core.req_num(body, "trir", minimum=0)
    if "safety_audit_pct" in body and body["safety_audit_pct"] is not None:
        v = core.req_num(body, "safety_audit_pct", minimum=0)
        if v > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "safety_audit_pct must be between 0 and 100")
        updates["safety_audit_pct"] = v
    if "insurance_cert_expires_on" in body \
            and body["insurance_cert_expires_on"] is not None:
        updates["insurance_cert_expires_on"] = core.req_date(
            body, "insurance_cert_expires_on").isoformat()

    if c["status"] not in _SUBMITTABLE:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT, CONDITIONAL, SUSPENDED, or EXPIRED "
                       "organization can be submitted")
    if c["status"] == "CONDITIONAL":
        changed = any(updates.get(k) != c[k] for k in
                      ("emr", "trir", "safety_audit_pct", "insurance_cert_expires_on")
                      if k in updates)
        if not changed:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Remediation resubmission must change at least one metric")

    for k, v in updates.items():
        c[k] = v
    # The certificate — after applying any update in this call — must not be
    # expired as of the logical today.
    from clock import parse_date
    expires_on = parse_date(c["insurance_cert_expires_on"])
    if expires_on < CLOCK.today():
        raise ApiError("ERR_INSURANCE_CERT_EXPIRED", 422,
                       "Insurance certificate expires before the logical today")

    score, decision = calc.prequal_score(
        c["emr"], c["trir"], c["safety_audit_pct"], expires_on, CLOCK.today())
    c["prequal_score"] = score
    c["computed_decision"] = decision
    c["status"] = "UNDER_REVIEW"
    core.touch(c)
    return ok(core.contractor_view(c))


@bp.route("/safety/contractor-orgs/<cid>/decide", methods=["POST"])
def decide_contractor(cid):
    auth(["SafetyManager"])
    c = core.get_or_404("contractors", cid, "ContractorOrg")
    body = core.body_json()
    decision = core.req_enum(body, "decision", ("APPROVE", "CONDITIONAL", "REJECT"))
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CONTRACTOR_NOT_UNDER_REVIEW", 409,
                       "decide requires the organization to be UNDER_REVIEW")
    # Posture gate precedes the score-contradiction check (validations 8 < 9).
    if decision == "APPROVE":
        active = next((p for p in db.DB["programs"].values()
                       if p["status"] == "ACTIVE"), None)
        if active is not None and active["posture"] == "RESTRICTED":
            raise ApiError("ERR_PROGRAM_RESTRICTED", 422,
                           "The ACTIVE program's RESTRICTED posture blocks approval")
    if decision != c["computed_decision"]:
        raise ApiError("ERR_DECISION_CONTRADICTS_SCORE", 422,
                       "decision must equal the computed band from prequal_score")

    if decision == "APPROVE":
        c["status"] = "APPROVED"
        c["prequal_valid_until"] = CLOCK.now() + timedelta(days=365)
    elif decision == "CONDITIONAL":
        c["status"] = "CONDITIONAL"
    else:
        c["status"] = "REJECTED"
    core.touch(c)
    return ok(core.contractor_view(c))


@bp.route("/safety/contractor-orgs/<cid>/suspend", methods=["POST"])
def suspend_contractor(cid):
    auth(["SafetyManager", "EHSAdmin"])
    c = core.get_or_404("contractors", cid, "ContractorOrg")
    body = core.body_json()
    reason = core.req_str(body, "suspension_reason")
    claim_id = core.opt_str(body, "suspension_claim_id", default=None)
    if claim_id is not None:
        # PRD 3.6 pins ERR_INVALID_REQUEST for a claim reference that does not
        # resolve or names another contractor's claim.
        claim = db.DB["claims"].get(claim_id)
        if claim is None or claim["contractor_org_id"] != c["id"]:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "suspension_claim_id must reference an existing claim "
                           "involving this contractor")
    if c["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an APPROVED organization can be suspended")
    c["status"] = "SUSPENDED"
    c["suspension_reason"] = reason
    c["suspension_claim_id"] = claim_id
    core.touch(c)
    return ok(core.contractor_view(c))
