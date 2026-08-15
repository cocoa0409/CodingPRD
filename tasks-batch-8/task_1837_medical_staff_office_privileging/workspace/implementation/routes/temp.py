from datetime import timedelta

from flask import Blueprint

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import (check_dt_order, get_body, paginate, parse_dt,
                  require_enum, require_fields)

bp = Blueprint("temp", __name__)

COORD = "MedicalStaffCoordinator"
CHAIR = "CredentialsCommitteeChair"

TEMP_KINDS = ("TEMPORARY", "EMERGENCY", "DISASTER")
WINDOW_CAPS = {
    "EMERGENCY": timedelta(hours=24),
    "DISASTER": timedelta(hours=72),
    "TEMPORARY": timedelta(days=120),
}


def _get_temp(tid):
    rec = db.temps.get(tid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND,
                         "TemporaryPrivilege not found")
    return rec


@bp.route("/mso/temporary-privileges", methods=["POST"])
@require_roles(COORD)
def create_temp():
    body = get_body()
    # Rung 3: existence.
    member_id = body.get("member_id")
    if member_id is not None and member_id not in db.members:
        errors.raise_err(errors.ERR_NOT_FOUND, "MedicalStaffMember not found")
    sponsor_id = body.get("sponsor_member_id")
    if sponsor_id is not None and sponsor_id not in db.members:
        errors.raise_err(errors.ERR_NOT_FOUND, "MedicalStaffMember not found")
    # Rung 10: self-sponsorship is incoherent.
    if member_id is not None and sponsor_id is not None \
            and member_id == sponsor_id:
        errors.raise_err(errors.ERR_SELF_SPONSOR,
                         "sponsor_member_id must differ from member_id")
    # Rung 11: input shape.
    require_fields(body, ["member_id", "sponsor_member_id", "temp_kind",
                          "privilege_line", "window_start", "window_end"])
    kind = require_enum(body, "temp_kind", TEMP_KINDS)
    if not isinstance(body["privilege_line"], str) \
            or not body["privilege_line"]:
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "privilege_line must be a non-empty string")
    check_dt_order(body["window_start"], body["window_end"],
                   "window_start", "window_end")
    if kind == "DISASTER" and not body.get("disaster_declaration_ref"):
        errors.raise_err(errors.ERR_DISASTER_REF_REQUIRED,
                         "disaster_declaration_ref is required for DISASTER")
    rec = services.base_record()
    rec.update({
        "member_id": member_id,
        "sponsor_member_id": sponsor_id,
        "temp_kind": kind,
        "privilege_line": body["privilege_line"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "temp_status": "PENDING_SPONSOR",
        "disaster_declaration_ref": body.get("disaster_declaration_ref"),
    })
    db.temps[rec["id"]] = rec
    return ok_object(serializers.temp(rec), 201)


@bp.route("/mso/temporary-privileges", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_temps():
    items, limit, offset, total = paginate(
        db.temps.values(), serializers.temp,
        ["member_id", "sponsor_member_id", "temp_status", "temp_kind"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/temporary-privileges/<tid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_temp(tid):
    return ok_object(serializers.temp(_get_temp(tid)))


@bp.route("/mso/temporary-privileges/<tid>/activate", methods=["POST"])
@require_roles(CHAIR)
def activate_temp(tid):
    get_body()
    temp = _get_temp(tid)
    # Rung 5: state.
    if temp["temp_status"] != "PENDING_SPONSOR":
        errors.raise_err(errors.ERR_TEMP_NOT_PENDING,
                         "Temporary privilege is not PENDING_SPONSOR")
    # Rung 7: safety gates — sponsor qualification, recipient eligibility.
    sponsor = db.members.get(temp["sponsor_member_id"])
    if sponsor is None or sponsor["membership_status"] != "ACTIVE" \
            or sponsor["privilege_posture"] != "FULL":
        errors.raise_err(errors.ERR_SPONSOR_NOT_QUALIFIED,
                         "Sponsor must be ACTIVE with FULL privilege_posture")
    recipient = db.members.get(temp["member_id"])
    if recipient is None or recipient["membership_status"] not in (
            "APPLICANT", "ACTIVE"):
        errors.raise_err(errors.ERR_MEMBER_NOT_ELIGIBLE,
                         "Recipient membership_status must be APPLICANT or "
                         "ACTIVE")
    # Rung 8: temporal — kind cap, then buffered overlap.
    start = parse_dt(temp["window_start"])
    end = parse_dt(temp["window_end"])
    if end - start > WINDOW_CAPS[temp["temp_kind"]]:
        errors.raise_err(errors.ERR_TEMP_WINDOW_TOO_LONG,
                         "Window exceeds the cap for its kind")
    day = timedelta(days=1)
    for other in db.temps.values():
        if (other["id"] == temp["id"]
                or other["member_id"] != temp["member_id"]
                or other["temp_status"] != "ACTIVE"):
            continue
        buffered_start = parse_dt(other["window_start"]) - day
        buffered_end = parse_dt(other["window_end"]) + day
        if start <= buffered_end and buffered_start <= end:
            errors.raise_err(errors.ERR_TEMP_OVERLAP,
                             "Window overlaps an existing ACTIVE temporary "
                             "privilege (1-day buffered)")
    if temp["temp_kind"] == "DISASTER" \
            and not temp.get("disaster_declaration_ref"):
        errors.raise_err(errors.ERR_DISASTER_REF_REQUIRED,
                         "disaster_declaration_ref is required for DISASTER")
    temp["temp_status"] = "ACTIVE"
    services.touch(temp)
    services.recompute_member_derived(recipient)
    return ok_object(serializers.temp(temp))


@bp.route("/mso/temporary-privileges/<tid>/terminate", methods=["POST"])
@require_roles(CHAIR)
def terminate_temp(tid):
    get_body()
    temp = _get_temp(tid)
    if temp["temp_status"] != "ACTIVE":
        errors.raise_err(errors.ERR_TEMP_NOT_ACTIVE,
                         "Temporary privilege is not ACTIVE")
    temp["temp_status"] = "TERMINATED_EARLY"
    services.touch(temp)
    member = db.members.get(temp["member_id"])
    if member is not None:
        services.recompute_member_derived(member)
    return ok_object(serializers.temp(temp))
