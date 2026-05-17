"""QualifiedExpense catalog endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_auth
from ..errors import ApiError
from ..helpers import (
    get_json_body, require_enum, require_fields, require_string,
    serialize_qualified_expense, sort_key_created_then_id,
)
from ..responses import build_list_envelope, build_success_envelope, paginate, parse_pagination
from ..store import store


bp = Blueprint("qualified_expenses", __name__)


CATEGORIES = {"MEDICAL", "VISION", "DENTAL", "OTC_MEDICATION", "DEPENDENT_CARE", "NON_QUALIFIED"}
ACCOUNT_TYPES = {"HSA", "HEALTH_FSA", "DEPENDENT_CARE_FSA"}


@bp.route("/qualified-expenses", methods=["POST"])
@require_auth(["PlanAdministrator"])
def create_qualified_expense():
    body = get_json_body(allow_empty=False)
    require_fields(body, ["code", "category", "eligible_account_types", "requires_dependent"])
    code = require_string(body["code"], "code")
    category = require_enum(body["category"], CATEGORIES, "category")
    eligible = body["eligible_account_types"]
    if not isinstance(eligible, list) or not eligible:
        raise ApiError("ERR_BAD_REQUEST", "eligible_account_types must be a non-empty list.")
    for t in eligible:
        if t not in ACCOUNT_TYPES:
            raise ApiError("ERR_BAD_REQUEST", f"Invalid account_type '{t}' in eligible_account_types.")
    requires_dep = body["requires_dependent"]
    if not isinstance(requires_dep, bool):
        raise ApiError("ERR_BAD_REQUEST", "requires_dependent must be boolean.")

    with store.lock:
        if code in store.qualified_expenses_by_code:
            raise ApiError("ERR_BAD_REQUEST", "QualifiedExpense.code must be unique.")
        now = store.clock.now()
        row = {
            "id": store.new_id(),
            "_seq": store.next_seq(),
            "created_at": now,
            "code": code,
            "category": category,
            "eligible_account_types": list(eligible),
            "requires_dependent": requires_dep,
        }
        store.qualified_expenses_by_id[row["id"]] = row
        store.qualified_expenses_by_code[row["code"]] = row

    return jsonify(build_success_envelope(serialize_qualified_expense(row))), 201


@bp.route("/qualified-expenses", methods=["GET"])
@require_auth(["AccountHolder", "PlanAdministrator", "ClaimAdjudicator", "Auditor"])
def list_qualified_expenses():
    limit, offset = parse_pagination()
    f_category = request.args.get("category")
    rows = list(store.qualified_expenses_by_id.values())
    if f_category is not None:
        rows = [r for r in rows if r["category"] == f_category]
    rows.sort(key=sort_key_created_then_id)
    page, total = paginate(rows, limit, offset)
    return jsonify(build_list_envelope(
        [serialize_qualified_expense(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )), 200
