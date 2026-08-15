"""MinorWorkPermit endpoints."""
from flask import Blueprint, request

import db
from errors import (err_invalid_request, err_invalid_state, err_not_found,
                    err_ref_not_found)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from util import (check_datetime, check_int, check_string, filter_status,
                  get_payload, logical_now, new_record, paginate, parse_dt,
                  serialize, touch)

S = db.STORE
bp = Blueprint("permits", __name__)

READ_ROLES = ("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Guardian")


def _get_permit(pid):
    p = domain.find("permits", pid)
    if p is None:
        raise err_not_found("MinorWorkPermit not found")
    return p


@bp.post("/casting/permits")
def create_permit():
    require_roles("ProductionCoordinator")
    body = get_payload()
    # Body FK existence
    talent = None
    if body.get("talent_id") is not None:
        talent = domain.find("talents", body.get("talent_id"))
        if talent is None:
            raise err_ref_not_found("talent_id does not reference a Talent")
    production = None
    if body.get("production_id") is not None:
        production = domain.find("productions", body.get("production_id"))
        if production is None:
            raise err_ref_not_found("production_id does not reference a Production")
    guardian = None
    if body.get("guardian_user_id") is not None:
        guardian = domain.find("guardians", body.get("guardian_user_id"))
        if guardian is None:
            raise err_ref_not_found("guardian_user_id does not reference a Guardian")
    # Field validation
    check_string(body, "talent_id")
    check_string(body, "production_id")
    check_string(body, "permit_number")
    issued = check_datetime(body, "issued_at")
    valid_until = check_datetime(body, "valid_until")
    if not valid_until > issued:
        raise err_invalid_request("valid_until must be strictly after issued_at")
    school_cap = check_int(body, "max_daily_hours_school_day", required=False,
                           default=5, min_v=1, max_v=8)
    non_school_cap = check_int(body, "max_daily_hours_non_school_day", required=False,
                               default=8, min_v=1, max_v=10)
    check_string(body, "guardian_user_id")
    # permit_number unique per (talent_id, production_id)
    for p in S["permits"].values():
        if p["talent_id"] == talent["id"] and p["production_id"] == production["id"] \
                and p["permit_number"] == body["permit_number"]:
            raise err_invalid_request("permit_number must be unique per (talent_id, production_id)")
    rec = new_record({
        "talent_id": talent["id"],
        "production_id": production["id"],
        "permit_number": body["permit_number"],
        "issued_at": issued,
        "valid_until": valid_until,
        "max_daily_hours_school_day": school_cap,
        "max_daily_hours_non_school_day": non_school_cap,
        "guardian_user_id": guardian["id"],
        "status": "PENDING_VERIFICATION",
    })
    S["permits"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/casting/permits")
def list_permits():
    require_roles(*READ_ROLES)
    records = filter_status(S["permits"].values())
    for param in ("talent_id", "production_id", "guardian_user_id"):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r.get(param) == v]
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/casting/permits/<pid>")
def get_permit(pid):
    require_roles(*READ_ROLES)
    return success_object(serialize(_get_permit(pid)))


@bp.get("/casting/talents/<tid>/permits")
def list_talent_permits(tid):
    require_roles(*READ_ROLES)
    if domain.find("talents", tid) is None:
        raise err_not_found("Talent not found")
    records = filter_status(domain.children("permits", "talent_id", tid))
    prod = request.args.get("production_id")
    if prod is not None:
        records = [r for r in records if r.get("production_id") == prod]
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/casting/permits/<pid>/verify")
def verify_permit(pid):
    require_roles("ProductionCoordinator")
    p = _get_permit(pid)
    if p["status"] != "PENDING_VERIFICATION":
        raise err_invalid_state("Only a PENDING_VERIFICATION permit can be verified")
    if not logical_now() < p["valid_until"]:
        raise err_invalid_state("Permit validity has already lapsed")
    p["status"] = "VERIFIED"
    touch(p)
    return success_object(serialize(p))


@bp.post("/casting/permits/<pid>/revoke")
def revoke_permit(pid):
    require_roles("ProductionCoordinator")
    p = _get_permit(pid)
    if p["status"] != "VERIFIED":
        raise err_invalid_state("Only a VERIFIED permit can be revoked")
    p["status"] = "REVOKED"
    touch(p)
    for b in S["bookings"].values():
        if b.get("work_permit_id") != pid:
            continue
        if b["status"] not in ("PENDING", "CONFIRMED"):
            continue
        domain.cancel_booking_record(b, "PERMIT_REVOKED",
                                     compute_penalty=(b["status"] == "CONFIRMED"))
    return success_object(serialize(p))
