"""ReserveFund singleton: read + OCC-guarded manual adjustments (PRD 2.8, 3.9)."""
from flask import Blueprint

import store
from domain import update_reserve, view
from envelope import success
from errors import ApiError
from security import ALL_ROLES, require_roles
from validate import get_body, validate_body

bp = Blueprint("reserve", __name__)

DIRECTIONS = ("CONTRIBUTION", "WITHDRAWAL")


@bp.get("/giving/reserve-fund")
@require_roles(*ALL_ROLES)
def get_reserve_fund():
    return success(view(store.reserve_fund), 200)


@bp.post("/giving/reserve-fund/adjustments")
@require_roles("ComplianceOfficer")
def reserve_adjustment():
    body = get_body()
    validate_body(
        body,
        {
            "direction": ("str", True, DIRECTIONS),
            "amount_cents": ("int", True, None),
            "expected_reserve_fund_version": ("int", True, None),
        },
    )
    fund = store.reserve_fund
    # OCC guard (§2.9)
    if body["expected_reserve_fund_version"] != fund["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale reserve fund version")
    if body["direction"] == "WITHDRAWAL" and body["amount_cents"] > fund["balance_cents"]:
        raise ApiError(
            "ERR_INSUFFICIENT_RESERVE_BALANCE",
            422,
            "Withdrawal exceeds the reserve balance",
        )
    delta = body["amount_cents"]
    if body["direction"] == "WITHDRAWAL":
        delta = -delta
    update_reserve(new_balance=fund["balance_cents"] + delta)
    return success(view(fund), 200)
