"""Endowment fund and append-only ledger endpoints."""
from decimal import Decimal

from flask import Blueprint, g, request

import db
import utils
from errors import ApiError
from middleware import ANY_ROLE, body, parse_pagination, require_roles
from response import ok, ok_list
from services import domain

bp = Blueprint("endowment", __name__)

PURPOSES = {"MONITORING", "ENFORCEMENT", "GENERAL_STEWARDSHIP"}


def get_fund_or_404(fund_id):
    f = db.endowment_funds.get(fund_id)
    if f is None:
        raise ApiError("ERR_ENDOWMENT_FUND_NOT_FOUND", "EndowmentFund id does not exist.", 404)
    return f


def _require_active(f):
    if f["status"] != "ACTIVE":
        raise ApiError("ERR_FUND_NOT_ACTIVE", "Fund mutation requires an ACTIVE fund.", 409)


@bp.route("/stewardship/endowment-funds", methods=["POST"])
@require_roles("TrustAdmin")
def create_fund():
    b = body()
    easement_id = b.get("easement_id")
    if easement_id is not None and easement_id not in db.easements:
        raise ApiError("ERR_EASEMENT_NOT_FOUND", "Easement id does not exist.", 404)
    # Uniqueness (priority 8): one fund per easement ever.
    if easement_id is not None and any(
        f["easement_id"] == easement_id for f in db.endowment_funds.values()
    ):
        raise ApiError("ERR_FUND_ALREADY_EXISTS", "Second EndowmentFund for the same easement.", 409)
    rate = b.get("spending_rate_bps")
    floor = b.get("principal_floor_cents")
    if (
        easement_id is None
        or not utils.is_int(rate)
        or rate < 100
        or rate > 800
        or not utils.is_int(floor)
        or floor < 0
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "easement_id, spending_rate_bps (100..800) and principal_floor_cents (>= 0) are required.",
            400,
        )
    now = utils.now_iso()
    f = {
        "id": utils.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "easement_id": easement_id,
        "spending_rate_bps": rate,
        "principal_floor_cents": floor,
        "status": "INITIALIZING",
        "market_value_cents": 0,
        "units_outstanding": Decimal("0.0000"),
        "_unit_value_cents": Decimal("100.0000"),  # anchor; exposed as null while units == 0
        "fiscal_year": 1,
        "prior_year_close_mv_cents": 0,
        "carryover_allowance_cents": 0,
    }
    db.endowment_funds[f["id"]] = f
    return ok(domain.fund_json(f), 201)


@bp.route("/stewardship/endowment-funds", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_funds():
    filters = {}
    for key in ("easement_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    rows = [r for r in db.endowment_funds.values() if all(r.get(k) == v for k, v in filters.items())]
    limit, offset = parse_pagination()
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return ok_list([domain.fund_json(r) for r in rows[offset : offset + limit]], limit, offset, total)


@bp.route("/stewardship/endowment-funds/<endowmentFundId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_fund(endowmentFundId):
    return ok(domain.fund_json(get_fund_or_404(endowmentFundId)))


@bp.route("/stewardship/endowment-funds/<endowmentFundId>/contributions", methods=["POST"])
@require_roles("TrustAdmin")
def post_contribution(endowmentFundId):
    f = get_fund_or_404(endowmentFundId)
    b = body()
    amount = b.get("amount_cents")
    if not utils.is_int(amount) or amount <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be a positive integer.", 400)
    txn = domain.post_ledger(f, "CONTRIBUTION", amount)
    if f["status"] == "INITIALIZING":
        f["status"] = "ACTIVE"
    domain.bump(f)
    return ok(domain.txn_json(txn), 201)


@bp.route("/stewardship/endowment-funds/<endowmentFundId>/returns", methods=["POST"])
@require_roles("TrustAdmin")
def post_return(endowmentFundId):
    f = get_fund_or_404(endowmentFundId)
    _require_active(f)
    b = body()
    amount = b.get("amount_cents")
    if not utils.is_int(amount):
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be an integer.", 400)
    txn = domain.post_ledger(f, "INVESTMENT_RETURN", amount)
    domain.bump(f)
    return ok(domain.txn_json(txn), 201)


@bp.route("/stewardship/endowment-funds/<endowmentFundId>/draws", methods=["POST"])
@require_roles("StewardshipCoordinator", "TrustBoardReviewer")
def post_draw(endowmentFundId):
    f = get_fund_or_404(endowmentFundId)
    _require_active(f)
    b = body()
    expected = b.get("expected_fund_version")
    # OCC (priority 6): compare when present and well-typed.
    if utils.is_int(expected) and expected != f["version"]:
        raise ApiError("ERR_STALE_FUND_VERSION", "expected_fund_version does not match the fund version.", 412)
    amount = b.get("amount_cents")
    purpose = b.get("purpose")
    if not utils.is_int(amount) or amount <= 0 or purpose not in PURPOSES or not utils.is_int(expected):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "A positive integer amount_cents, a valid purpose and expected_fund_version are required.",
            400,
        )
    # Waterfall allocation (SCAFFOLD calculations.waterfall_draw_allocation, pinned).
    d = amount
    mv = f["market_value_cents"]
    b1_remaining = max(0, domain.policy_draw_allowance(f) - domain.provisional_draws_ytd(f))
    b2_remaining = max(0, mv - f["principal_floor_cents"])
    from_policy = min(d, b1_remaining)
    rem1 = d - from_policy
    from_excess = min(rem1, b2_remaining - from_policy)
    rem2 = rem1 - from_excess
    if rem2 > 0 and g.user_role != "TrustBoardReviewer":
        raise ApiError(
            "ERR_PRINCIPAL_INVASION_REQUIRES_BOARD",
            "The draw would dip below the principal floor and the caller is not a TrustBoardReviewer.",
            402,
        )
    if rem2 > 0:
        if d > mv:
            raise ApiError(
                "ERR_DRAW_EXCEEDS_AUTHORITY", "The draw exceeds the fund's market value.", 402
            )
        from_principal = rem2
    else:
        from_principal = 0
    txn = domain.post_ledger(
        f, "DRAW", -d, purpose=purpose, buckets=(from_policy, from_excess, from_principal)
    )
    domain.bump(f)
    return ok(domain.txn_json(txn), 201)


@bp.route("/stewardship/endowment-funds/<endowmentFundId>/close-year", methods=["POST"])
@require_roles("TrustBoardReviewer")
def close_year(endowmentFundId):
    f = get_fund_or_404(endowmentFundId)
    _require_active(f)
    # Pinned evaluation order (SCAFFOLD calculations.carryover_allowance, mode c).
    policy_y = domain.policy_amount_for(f["prior_year_close_mv_cents"], f["spending_rate_bps"])
    underused = max(0, policy_y + f["carryover_allowance_cents"] - domain.provisional_draws_ytd(f))
    new_carryover = min(underused, policy_y)  # capped by the CLOSED year's policy amount
    f["carryover_allowance_cents"] = new_carryover
    f["prior_year_close_mv_cents"] = f["market_value_cents"]
    f["fiscal_year"] += 1  # resets provisional_draws_ytd (derived per fiscal year)
    domain.bump(f)
    return ok(domain.fund_json(f))


@bp.route("/stewardship/endowment-funds/<endowmentFundId>/transactions", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_transactions(endowmentFundId):
    get_fund_or_404(endowmentFundId)
    txn_type = request.args.get("txn_type")
    rows = [t for t in db.endowment_transactions.values() if t["fund_id"] == endowmentFundId]
    if txn_type is not None:
        rows = [t for t in rows if t["txn_type"] == txn_type]
    limit, offset = parse_pagination()
    rows.sort(key=lambda t: (t["posted_on"], t["created_at"]))  # posting order
    total = len(rows)
    return ok_list([domain.txn_json(t) for t in rows[offset : offset + limit]], limit, offset, total)
