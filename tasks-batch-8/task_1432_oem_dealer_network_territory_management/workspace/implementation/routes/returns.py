"""PartsReturn endpoints: draft (credit preview), submit (stocking + allowance
gates, credit recomputed at submit date), decide, reverse."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_RETURN_YEAR_MISMATCH,
    ERR_DEALER_NOT_FOUND,
    ERR_RETURN_NOT_FOUND,
    ERR_DEALER_IDENTITY_MISMATCH,
    ERR_RETURN_INVALID_STATE,
    ERR_STOCKING_NONCOMPLIANT,
    ERR_ALLOWANCE_EXCEEDED,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import (
    allowance_total_cents,
    allowance_used_cents,
    return_credit_cents,
)
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("parts_returns", __name__)


def get_return_or_404(return_id: str) -> dict:
    ret = db.parts_returns.get(return_id)
    if ret is None:
        raise_err(ERR_RETURN_NOT_FOUND, "Parts return id does not exist")
    return ret


def _validate_lines(body: dict) -> list:
    lines = require_field(body, "lines")
    if not isinstance(lines, list):
        raise_err(ERR_INVALID_REQUEST, "lines must be an array")
    for line in lines:
        if not isinstance(line, dict):
            raise_err(ERR_INVALID_REQUEST, "each line must be an object")
        part_number = line.get("part_number")
        if not isinstance(part_number, str) or part_number == "":
            raise_err(ERR_INVALID_REQUEST, "line.part_number must be a non-empty string")
        quantity = line.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise_err(ERR_INVALID_REQUEST, "line.quantity must be an integer > 0")
        unit_credit = line.get("unit_credit_cents")
        if isinstance(unit_credit, bool) or not isinstance(unit_credit, int) or unit_credit <= 0:
            raise_err(ERR_INVALID_REQUEST, "line.unit_credit_cents must be an integer > 0")
    return lines


@bp.route("/parts-returns", methods=["POST"])
@require_roles("DealerUser")
def create_return(_user_id: str, _role: str):
    body = get_json_body()
    dealer_id = require_string(body, "dealer_id")
    return_year = require_int(body, "return_year")
    lines = _validate_lines(body)
    # Priority 3 input format: return_year must equal the current clock year.
    if return_year != db.clock_date().year:
        raise_err(ERR_RETURN_YEAR_MISMATCH, "return_year != current clock year")

    # Priority 4 existence.
    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        raise_err(ERR_DEALER_NOT_FOUND, "Dealer id does not exist")

    # Priority 5 ownership.
    if dealer_id != _user_id:
        raise_err(ERR_DEALER_IDENTITY_MISMATCH, "DealerUser body dealer_id != X-User-ID")

    # Credit preview against the current logical date.
    credit, restock = return_credit_cents(lines, return_year, db.clock_date())
    ret = {
        "dealer_id": dealer_id,
        "return_year": return_year,
        "lines": [
            {
                "part_number": line["part_number"],
                "quantity": line["quantity"],
                "unit_credit_cents": line["unit_credit_cents"],
            }
            for line in lines
        ],
        "restock_pct_applied": restock,
        "credit_cents": credit,
        "status": "DRAFT",
    }
    db.stamp_new(ret)
    db.parts_returns[ret["id"]] = ret
    return success_object(serialize(ret), 201)


@bp.route("/parts-returns", methods=["GET"])
@require_roles("Any")
def list_returns(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.parts_returns.values()))
    items = apply_filters(items, ["dealer_id", "return_year", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/parts-returns/<return_id>", methods=["GET"])
@require_roles("Any")
def get_return(return_id: str, _user_id: str, _role: str):
    ret = get_return_or_404(return_id)
    return success_object(serialize(ret))


@bp.route("/parts-returns/<return_id>/submit", methods=["POST"])
@require_roles("DealerUser")
def submit_return(return_id: str, _user_id: str, _role: str):
    ret = get_return_or_404(return_id)

    # Priority 5 ownership (before state per PRD 2.8 ordering).
    if ret["dealer_id"] != _user_id:
        raise_err(ERR_DEALER_IDENTITY_MISMATCH, "Submitting DealerUser is not the return's dealer")

    # Priority 6 state.
    if ret["status"] != "DRAFT":
        raise_err(ERR_RETURN_INVALID_STATE, "submit requires return DRAFT")

    dealer = db.dealers.get(ret["dealer_id"])
    if dealer is None:
        raise_err(ERR_DEALER_NOT_FOUND, "Dealer id does not exist")

    # Recompute credit authoritatively against the submit date.
    credit, restock = return_credit_cents(ret["lines"], ret["return_year"], db.clock_date())

    # Priority 8: stocking compliance gate.
    if not dealer["stock_compliant"]:
        raise_err(ERR_STOCKING_NONCOMPLIANT, "Return submit requires Dealer.stock_compliant == true")

    # Priority 11 fiscal: annual allowance check (equality allowed).
    allowance_total = allowance_total_cents(dealer)
    used = allowance_used_cents(ret["dealer_id"], ret["return_year"])
    if used + credit > allowance_total:
        raise_err(ERR_ALLOWANCE_EXCEEDED, "allowance_used + credit_cents > allowance_total")

    ret["credit_cents"] = credit
    ret["restock_pct_applied"] = restock
    ret["status"] = "SUBMITTED"
    db.touch(ret)
    return success_object(serialize(ret))


@bp.route("/parts-returns/<return_id>/decide", methods=["POST"])
@require_roles("OemSalesOps")
def decide_return(return_id: str, _user_id: str, _role: str):
    body = get_json_body()
    decision = require_enum(body, "decision", {"CREDIT", "REJECT"})
    ret = get_return_or_404(return_id)
    if ret["status"] != "SUBMITTED":
        raise_err(ERR_RETURN_INVALID_STATE, "decide requires return SUBMITTED")
    ret["status"] = "CREDITED" if decision == "CREDIT" else "REJECTED"
    db.touch(ret)
    return success_object(serialize(ret))


@bp.route("/parts-returns/<return_id>/reverse", methods=["POST"])
@require_roles("OemAuditor")
def reverse_return(return_id: str, _user_id: str, _role: str):
    ret = get_return_or_404(return_id)
    if ret["status"] != "CREDITED":
        raise_err(ERR_RETURN_INVALID_STATE, "reverse requires return CREDITED")
    # REVERSED returns drop out of allowance_used_cents (compensating release).
    ret["status"] = "REVERSED"
    db.touch(ret)
    return success_object(serialize(ret))
