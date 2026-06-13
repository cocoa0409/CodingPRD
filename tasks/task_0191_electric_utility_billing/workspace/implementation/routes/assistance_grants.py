"""AssistanceGrant endpoints: pledge, cancel, reads (PRD §3.8)."""
from flask import Blueprint, request

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles, require_owner
from response import success
from services import serializers as ser
from services.common import (
    check_enum,
    get_json_body,
    paginate,
    parse_pagination,
    require_fields,
    require_int,
)

bp = Blueprint("assistance_grants", __name__)

READ_ROLES = {"BillingOperator", "AssistanceCaseworker", "Customer"}
PROGRAMS = {"LIHEAP", "EMERGENCY_CRISIS"}


@bp.route("/assistance-grants", methods=["POST"])
def create_grant():
    _, role = authenticate()
    require_roles(role, {"AssistanceCaseworker"})
    body = get_json_body()
    require_fields(body, ["account_id", "pledged_cents"])
    account_id = body["account_id"]
    pledged = require_int(body, "pledged_cents")
    program = body.get("program", "LIHEAP")
    if program is None:
        program = "LIHEAP"
    check_enum(program, PROGRAMS, "program")

    if db.accounts.get(account_id) is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced account does not exist.")

    if pledged <= 0:
        raise err("ERR_VALIDATION_RANGE", "pledged_cents must be > 0.")

    rec = base_record()
    rec.update({
        "account_id": account_id,
        "program": program,
        "status": "PLEDGED",
        "pledged_cents": pledged,
        "remaining_cents": pledged,
    })
    db.assistance_grants[rec["id"]] = rec
    return success(ser.assistance_grant(rec), status=201)


@bp.route("/assistance-grants/<grant_id>/cancel", methods=["POST"])
def cancel_grant(grant_id):
    _, role = authenticate()
    require_roles(role, {"AssistanceCaseworker"})
    grant = db.assistance_grants.get(grant_id)
    if grant is None:
        raise err("ERR_NOT_FOUND", "Assistance grant not found.")
    if grant["status"] != "PLEDGED":
        raise err("ERR_INVALID_STATE", "Only a PLEDGED grant can be cancelled.")
    grant["status"] = "CANCELLED"
    touch(grant)
    return success(ser.assistance_grant(grant), status=200)


@bp.route("/assistance-grants/<grant_id>", methods=["GET"])
def get_grant(grant_id):
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    grant = db.assistance_grants.get(grant_id)
    if grant is None:
        raise err("ERR_NOT_FOUND", "Assistance grant not found.")
    require_owner(role, user_id, grant["account_id"])
    return success(ser.assistance_grant(grant), status=200)


@bp.route("/assistance-grants", methods=["GET"])
def list_grants():
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = list(db.assistance_grants.values())
    if role == "Customer":
        items = [g for g in items if g["account_id"] == user_id]
    if account_id is not None:
        items = [g for g in items if g["account_id"] == account_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    page, pagination = paginate(items)
    return success(
        [ser.assistance_grant(g) for g in page], status=200, pagination=pagination
    )
