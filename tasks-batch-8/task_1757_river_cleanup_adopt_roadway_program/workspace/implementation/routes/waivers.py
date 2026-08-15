"""VolunteerWaiver endpoints (PRD 3.4): registration with minor supervision,
revocation, listing."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_WAIVER_NOT_FOUND,
    ERR_MINOR_GUARDIAN_REQUIRED,
    ERR_SUPERVISOR_INVALID,
    ERR_WAIVER_NOT_ACTIVE,
)
from middleware import get_caller, check_role, check_ownership, COORD, LEADER
from response import success_object
from routes.helpers import list_response, agreement_chain_owner
from services.core import stamp_new, touch, public
from util import CLOCK, add_years, parse_date
from validate import (
    get_body, req_str, opt_bool, ref_id, require_resource, maybe_resource,
    parse_iso_date,
)

bp = Blueprint("waivers", __name__)

MAJORITY_AGE = 18


def _age_at(dob, on_date):
    """Whole calendar years: largest a such that dob + a years <= on_date."""
    years = on_date.year - dob.year
    if (on_date.month, on_date.day) < (dob.month, dob.day):
        years -= 1
    return years


@bp.post("/program/waivers")
def create_waiver():
    caller = get_caller()
    check_role(caller, [LEADER])
    body = get_body()
    # family 3: body references that are present must resolve
    agreement_id = ref_id(body, "agreement_id")
    agreement = maybe_resource("agreements", agreement_id, ERR_AGREEMENT_NOT_FOUND)
    supervisor_id = ref_id(body, "supervisor_waiver_id")
    supervisor = maybe_resource("waivers", supervisor_id, ERR_WAIVER_NOT_FOUND)
    # family 4: ownership through the agreement chain
    if agreement is not None:
        check_ownership(caller, agreement["group_id"])
    # family 5: shape
    if agreement_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: agreement_id")
    volunteer_full_name = req_str(body, "volunteer_full_name")
    dob = parse_iso_date(body.get("dob"), "dob")
    today = CLOCK.today()
    if not dob < today:
        raise_error(ERR_INVALID_REQUEST, "dob must be a date in the past")
    guardian_full_name = body.get("guardian_full_name")
    if guardian_full_name is not None and not isinstance(guardian_full_name, str):
        raise_error(ERR_INVALID_REQUEST, "invalid field type: guardian_full_name")
    guardian_consent = opt_bool(body, "guardian_consent", False)
    # computed: calendar age at signing; exactly 18 on signed_date is NOT a minor
    is_minor = _age_at(dob, today) < MAJORITY_AGE
    # family 7: minor-safety rules (guardian first, then supervisor)
    if is_minor:
        if not guardian_full_name or guardian_consent is not True:
            raise_error(ERR_MINOR_GUARDIAN_REQUIRED,
                        "a minor waiver requires guardian_full_name and guardian_consent true")
        if (supervisor is None or supervisor["status"] != "ACTIVE"
                or supervisor["is_minor"] or supervisor["agreement_id"] != agreement_id):
            raise_error(ERR_SUPERVISOR_INVALID,
                        "supervisor waiver must be an ACTIVE adult waiver under the same agreement")
    else:
        guardian_full_name = None
        guardian_consent = False
        supervisor_id = None
    rec = stamp_new({
        "agreement_id": agreement_id,
        "volunteer_full_name": volunteer_full_name,
        "dob": dob.isoformat(),
        "is_minor": is_minor,
        "guardian_full_name": guardian_full_name,
        "guardian_consent": guardian_consent,
        "supervisor_waiver_id": supervisor_id,
        "status": "ACTIVE",
        "signed_date": today.isoformat(),
        "expiry_date": add_years(today, 1).isoformat(),
    })
    db["waivers"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/program/waivers/<wid>")
def get_waiver(wid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("waivers", wid, ERR_WAIVER_NOT_FOUND)
    check_ownership(caller, agreement_chain_owner(rec["agreement_id"]))
    return success_object(public(rec))


@bp.get("/program/waivers")
def list_waivers():
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    filters = {
        "agreement_id": request.args.get("agreement_id"),
        "supervisor_waiver_id": request.args.get("supervisor_waiver_id"),
        "status": request.args.get("status"),
    }
    return list_response("waivers", caller, filters=filters,
                         owner_of=lambda w: agreement_chain_owner(w["agreement_id"]))


@bp.post("/program/waivers/<wid>/revoke")
def revoke_waiver(wid):
    caller = get_caller()
    check_role(caller, [LEADER])
    rec = require_resource("waivers", wid, ERR_WAIVER_NOT_FOUND)
    check_ownership(caller, agreement_chain_owner(rec["agreement_id"]))
    get_body()
    if rec["status"] != "ACTIVE":
        raise_error(ERR_WAIVER_NOT_ACTIVE, "only an ACTIVE waiver can be revoked")
    rec["status"] = "REVOKED"
    touch(rec)
    return success_object(public(rec))
