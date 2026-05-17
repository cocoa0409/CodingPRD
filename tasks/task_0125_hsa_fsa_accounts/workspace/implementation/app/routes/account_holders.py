"""Account-holder endpoints."""
from __future__ import annotations

from flask import Blueprint, g, jsonify

from ..auth import require_auth
from ..errors import ApiError
from ..helpers import (
    get_json_body, parse_iso_field, require_enum, require_fields, require_string,
    serialize_account_holder,
)
from ..responses import build_success_envelope
from ..store import store


bp = Blueprint("account_holders", __name__)


TAX_FILING_STATUSES = {"SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD"}


@bp.route("/account-holders", methods=["POST"])
@require_auth(["PlanAdministrator"])
def create_account_holder():
    body = get_json_body(allow_empty=False)
    require_fields(body, ["full_name", "ssn_last4", "tax_filing_status", "birth_date"])

    full_name = require_string(body["full_name"], "full_name")
    ssn = body["ssn_last4"]
    if not isinstance(ssn, str) or len(ssn) != 4 or not ssn.isdigit():
        raise ApiError("ERR_BAD_REQUEST", "ssn_last4 must be exactly 4 numeric digits.")
    tax_filing_status = require_enum(body["tax_filing_status"], TAX_FILING_STATUSES, "tax_filing_status")
    birth_date = parse_iso_field(body["birth_date"], "birth_date")

    with store.lock:
        now = store.clock.now()
        row = {
            "id": store.new_id(),
            "_seq": store.next_seq(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "full_name": full_name,
            "ssn_last4": ssn,
            "tax_filing_status": tax_filing_status,
            "birth_date": birth_date,
        }
        store.account_holders[row["id"]] = row

    return jsonify(build_success_envelope(serialize_account_holder(row))), 201


@bp.route("/account-holders/<account_holder_id>", methods=["GET"])
@require_auth(["PlanAdministrator", "AccountHolder", "Auditor"])
def get_account_holder(account_holder_id: str):
    row = store.account_holders.get(account_holder_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "Account holder not found.")
    # AccountHolder may only view themselves.
    if g.role == "AccountHolder" and g.user_id != row["id"]:
        raise ApiError("ERR_NOT_FOUND", "Account holder not found.")
    return jsonify(build_success_envelope(serialize_account_holder(row))), 200
