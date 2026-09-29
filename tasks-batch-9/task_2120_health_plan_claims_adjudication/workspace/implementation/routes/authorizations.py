"""Prior authorizations (PRD 3.3)."""

from flask import Blueprint, request

from auth import ALL_OPERATORS, endpoint
from envelope import created, ok
from errors import ApiError
from routes.common import filter_equals, render_list, resolve
from serializers import dump
from store import db
from validators import body, check_interval, read_date, read_int, read_string, require_fields

bp = Blueprint("authorizations", __name__)


@bp.post("/adjudication/authorizations")
@endpoint(["UtilizationReviewer"])
def issue_authorization():
    payload = body()
    if payload.get("member_id") is not None:
        resolve("members", payload["member_id"], "ERR_MEMBER_NOT_FOUND")
    if payload.get("provider_id") is not None:
        resolve("providers", payload["provider_id"], "ERR_PROVIDER_NOT_FOUND")
    require_fields(
        payload,
        ["member_id", "provider_id", "procedure_code", "authorized_units", "valid_from", "valid_to"],
    )
    valid_from = read_date(payload, "valid_from", required=True)
    valid_to = read_date(payload, "valid_to", required=True)
    check_interval("valid_to", valid_from, valid_to)
    row = {
        "member_id": read_string(payload, "member_id", required=True),
        "provider_id": read_string(payload, "provider_id", required=True),
        "procedure_code": read_string(payload, "procedure_code", required=True),
        "authorized_units": read_int(payload, "authorized_units", minimum=1, required=True),
        "units_consumed": 0,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "status": "ACTIVE",
    }
    return created(dump("authorization", db.insert("authorizations", row)))


@bp.get("/adjudication/authorizations/<authorization_id>")
@endpoint(ALL_OPERATORS)
def get_authorization(authorization_id):
    row = resolve("authorizations", authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")
    return ok(dump("authorization", row))


@bp.get("/adjudication/authorizations")
@endpoint(ALL_OPERATORS)
def list_authorizations():
    rows = db.values("authorizations")
    rows = filter_equals(rows, "member_id", request.args.get("member_id"))
    rows = filter_equals(rows, "provider_id", request.args.get("provider_id"))
    rows = filter_equals(rows, "procedure_code", request.args.get("procedure_code"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    return render_list("authorization", rows)


@bp.post("/adjudication/authorizations/<authorization_id>/revoke")
@endpoint(["UtilizationReviewer"])
def revoke_authorization(authorization_id):
    row = resolve("authorizations", authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")
    if row["status"] not in ("ACTIVE", "PARTIALLY_CONSUMED"):
        raise ApiError("ERR_AUTHORIZATION_NOT_REVOCABLE")
    # Revocation does not release units already consumed.
    row["status"] = "REVOKED"
    db.touch(row)
    return ok(dump("authorization", row))
