"""Contract endpoints: booking, price-fixes (OCC), short-close, cancel (PRD §3.1-3.3)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_CREDIT_LIMIT_EXCEEDED, ERR_INVALID_DELIVERY_WINDOW, ERR_INVALID_FIX_QUANTITY,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_OVER_FIX,
    ERR_STALE_VERSION, err,
)
from middleware import (
    COMMON_SYS, D, base_fields, check_unknown_fields, get_json_body,
    is_number, occ_value, paginate, pub, require_fields, require_role,
    sort_created, touch, v_enum, v_int, v_iso, v_num, v_string,
)
from response import success_list, success_object
from services import (
    provisional_exposure_after_fix, recompute_contract_pricing,
    recompute_counterparty_exposure,
)

bp = Blueprint("contracts", __name__)

CONTRACT_INPUTS = {
    "contract_ref", "pricing_mode", "coffee_grade", "total_lbs",
    "fixed_price_usd_per_lb", "differential_usd_per_lb",
    "delivery_window_start", "delivery_window_end",
}
CONTRACT_SYS = {
    "counterparty_id", "pricing_status", "fulfillment_status",
    "fixed_lbs_accum", "weighted_avg_fixed_futures_usd", "received_lbs_accum",
    "priced_notional_usd", "unpriced_lbs",
} | COMMON_SYS

PRICING_MODES = {"DIFFERENTIAL_PTBF", "FIXED_OUTRIGHT"}
COFFEE_GRADES = {"SHB", "HG", "NY2_3", "ROBUSTA_GRADE1"}
READ_ROLES = ("Trader", "RiskManager", "LogisticsCoordinator")


def get_contract_or_404(contract_id):
    c = DB.contracts.get(contract_id)
    if c is None:
        raise err(ERR_NOT_FOUND, "Contract id does not exist")
    return c


def _check_contract_occ(body, contract):
    """Priority-7 OCC guard: expected_contract_version vs current version.

    Absent field defers to the structural required-field check (400);
    present-but-mismatched (or non-integer) -> ERR_STALE_VERSION (412).
    """
    present, val = occ_value(body, "expected_contract_version")
    if present and val != contract["version"]:
        raise err(ERR_STALE_VERSION, "expected_contract_version does not match current contract version")
    return present


@bp.post("/roastery/counterparties/<counterparty_id>/contracts")
def create_contract(counterparty_id):
    require_role("Trader")
    cp = DB.counterparties.get(counterparty_id)
    if cp is None:
        raise err(ERR_NOT_FOUND, "Counterparty id does not exist")
    body = get_json_body()
    check_unknown_fields(body, CONTRACT_INPUTS | CONTRACT_SYS)

    # Priority 20: delivery-window sanity (only evaluable when both parse).
    from clock import parse_iso
    ws_raw = body.get("delivery_window_start")
    we_raw = body.get("delivery_window_end")
    if isinstance(ws_raw, str) and isinstance(we_raw, str):
        try:
            ws, we = parse_iso(ws_raw), parse_iso(we_raw)
            if we <= ws:
                raise err(ERR_INVALID_DELIVERY_WINDOW,
                          "delivery_window_end must be strictly after delivery_window_start")
        except ValueError:
            pass  # unparseable -> structural 400 below

    # Structural validation (priorities 22/23).
    require_fields(body, ["contract_ref", "pricing_mode", "coffee_grade", "total_lbs",
                          "delivery_window_start", "delivery_window_end"])
    ref = v_string(body, "contract_ref")
    mode = v_enum(body, "pricing_mode", PRICING_MODES)
    grade = v_enum(body, "coffee_grade", COFFEE_GRADES)
    total = v_int(body, "total_lbs", gt=0)
    ws = v_iso(body, "delivery_window_start")
    we = v_iso(body, "delivery_window_end")
    if mode == "FIXED_OUTRIGHT":
        fixed_price = v_num(body, "fixed_price_usd_per_lb")
        if body.get("differential_usd_per_lb") is not None:
            raise err(ERR_INVALID_REQUEST,
                      "differential_usd_per_lb must be null for FIXED_OUTRIGHT")
        differential = None
    else:
        differential = v_num(body, "differential_usd_per_lb")
        if body.get("fixed_price_usd_per_lb") is not None:
            raise err(ERR_INVALID_REQUEST,
                      "fixed_price_usd_per_lb must be null for DIFFERENTIAL_PTBF")
        fixed_price = None

    c = base_fields()
    c.update({
        "counterparty_id": counterparty_id,
        "contract_ref": ref,
        "pricing_mode": mode,
        "coffee_grade": grade,
        "total_lbs": total,
        "fixed_price_usd_per_lb": fixed_price,
        "differential_usd_per_lb": differential,
        "delivery_window_start": _norm_iso(ws),
        "delivery_window_end": _norm_iso(we),
        "pricing_status": "UNFIXED" if mode == "DIFFERENTIAL_PTBF" else "NOT_APPLICABLE",
        "fulfillment_status": "OPEN",
        "fixed_lbs_accum": 0,
        "weighted_avg_fixed_futures_usd": None,
        "received_lbs_accum": 0,
        "priced_notional_usd": 0.0,
        "unpriced_lbs": total,
    })
    recompute_contract_pricing(c)  # FIXED_OUTRIGHT initializes its pricing fields
    DB.contracts[c["id"]] = c
    recompute_counterparty_exposure(cp)
    return success_object(pub(c), status=201)


def _norm_iso(s):
    from clock import fmt_iso, parse_iso
    return fmt_iso(parse_iso(s))


@bp.get("/roastery/contracts/<contract_id>")
def get_contract(contract_id):
    require_role(*READ_ROLES)
    return success_object(pub(get_contract_or_404(contract_id)))


@bp.get("/roastery/contracts")
def list_contracts():
    require_role(*READ_ROLES)
    items = sort_created(DB.contracts.values())
    cp_id = request.args.get("counterparty_id")
    ps = request.args.get("pricing_status")
    fs = request.args.get("fulfillment_status")
    if cp_id is not None:
        items = [c for c in items if c["counterparty_id"] == cp_id]
    if ps is not None:
        items = [c for c in items if c["pricing_status"] == ps]
    if fs is not None:
        items = [c for c in items if c["fulfillment_status"] == fs]
    page, limit, offset, total = paginate(items)
    return success_list([pub(c) for c in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Price-fix events (PRD §3.2)
# ---------------------------------------------------------------------------

PRICE_FIX_ALLOWED = {
    "fix_lbs", "futures_price_usd_per_lb", "expected_contract_version",
    "contract_id", "fixed_at", "fixed_by_trader_id",
} | COMMON_SYS


@bp.post("/roastery/contracts/<contract_id>/price-fixes")
def create_price_fix(contract_id):
    user_id, _ = require_role("Trader")
    contract = get_contract_or_404(contract_id)
    body = get_json_body()

    # Priority 6: state preconditions.
    if contract["pricing_mode"] != "DIFFERENTIAL_PTBF":
        raise err(ERR_INVALID_STATE, "Price-fix requires a DIFFERENTIAL_PTBF contract")
    if contract["fulfillment_status"] not in ("OPEN", "PARTIALLY_RECEIVED", "FULLY_RECEIVED"):
        raise err(ERR_INVALID_STATE,
                  "Price-fix not permitted once the contract is SHORT_CLOSED or CANCELLED")
    if contract["pricing_status"] == "FULLY_FIXED":
        # FULLY_FIXED is terminal for the pricing dimension.
        raise err(ERR_INVALID_STATE, "Contract is already FULLY_FIXED")

    # Priority 7: OCC.
    _check_contract_occ(body, contract)

    fix_lbs_raw = body.get("fix_lbs")
    price_raw = body.get("futures_price_usd_per_lb")
    fix_numeric = is_number(fix_lbs_raw) and is_number(price_raw)

    cp = DB.counterparties.get(contract["counterparty_id"])

    # Priority 12: credit gate (provisional exposure after this fix).
    if fix_numeric and cp is not None:
        projected = provisional_exposure_after_fix(
            cp, contract, int(fix_lbs_raw), price_raw)
        if D(projected) > D(cp["credit_limit_usd"]):
            raise err(ERR_CREDIT_LIMIT_EXCEEDED,
                      "Price-fix would push counterparty provisional open exposure above credit_limit_usd")

    # Priority 13: over-fix cap.
    if is_number(fix_lbs_raw):
        if contract["fixed_lbs_accum"] + int(fix_lbs_raw) > contract["total_lbs"]:
            raise err(ERR_OVER_FIX,
                      "Cumulative fix_lbs would exceed contract total_lbs")

    # Priorities 22/23: structural.
    check_unknown_fields(body, PRICE_FIX_ALLOWED)
    require_fields(body, ["fix_lbs", "futures_price_usd_per_lb", "expected_contract_version"])
    fix_lbs = v_int(body, "fix_lbs")
    price = v_num(body, "futures_price_usd_per_lb")
    v_int(body, "expected_contract_version")

    # Priority 26: fix quantity sanity.
    if fix_lbs <= 0 or not (price > 0):
        raise err(ERR_INVALID_FIX_QUANTITY,
                  "fix_lbs and futures_price_usd_per_lb must be strictly positive")

    from clock import now_iso
    from middleware import new_id, q5
    ts = now_iso()
    event = {
        "id": new_id(),
        "created_at": ts,
        "_seq": DB.next_seq(),
        "contract_id": contract["id"],
        "fix_lbs": fix_lbs,
        "futures_price_usd_per_lb": q5(price),
        "fixed_at": ts,
        "fixed_by_trader_id": user_id,
    }
    DB.price_fixes[event["id"]] = event

    contract["fixed_lbs_accum"] += fix_lbs
    recompute_contract_pricing(contract)
    if contract["fixed_lbs_accum"] == contract["total_lbs"]:
        contract["pricing_status"] = "FULLY_FIXED"
    else:
        contract["pricing_status"] = "PARTIALLY_FIXED"
    touch(contract)

    # FULLY_FIXED auto-lift cascade: every APPROVED hedge lifts at the
    # contract's final weighted-average futures level.
    if contract["pricing_status"] == "FULLY_FIXED":
        from services import hedge_realized_pnl
        for h in DB.futures_hedges.values():
            if h["contract_id"] == contract["id"] and h["hedge_status"] == "APPROVED":
                h["exit_price_usd_per_lb"] = contract["weighted_avg_fixed_futures_usd"]
                h["realized_pnl_usd"] = hedge_realized_pnl(h)
                h["hedge_status"] = "LIFTED"
                touch(h)

    if cp is not None:
        recompute_counterparty_exposure(cp)
    return success_object(pub(event), status=201)


@bp.get("/roastery/contracts/<contract_id>/price-fixes")
def list_price_fixes(contract_id):
    require_role("Trader", "RiskManager")
    get_contract_or_404(contract_id)
    items = sort_created(
        [e for e in DB.price_fixes.values() if e["contract_id"] == contract_id])
    page, limit, offset, total = paginate(items)
    return success_list([pub(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Short-close / cancel (PRD §3.3)
# ---------------------------------------------------------------------------

SHORT_CLOSE_ALLOWED = {"expected_contract_version"} | CONTRACT_SYS


@bp.post("/roastery/contracts/<contract_id>/short-close")
def short_close_contract(contract_id):
    require_role("Trader")
    contract = get_contract_or_404(contract_id)
    body = get_json_body()

    # Priority 6: state preconditions.
    if contract["fulfillment_status"] != "PARTIALLY_RECEIVED":
        raise err(ERR_INVALID_STATE, "Short-close requires fulfillment_status PARTIALLY_RECEIVED")
    if not (contract["received_lbs_accum"] < contract["total_lbs"]):
        raise err(ERR_INVALID_STATE, "Short-close requires received_lbs_accum < total_lbs")
    pending = any(
        s["contract_id"] == contract["id"]
        and s["transit_status"] in ("BOOKED", "IN_TRANSIT", "ARRIVED")
        for s in DB.shipments.values()
    )
    if pending:
        raise err(ERR_INVALID_STATE,
                  "Short-close blocked while shipments are still BOOKED, IN_TRANSIT, or ARRIVED")

    # Priority 7: OCC.
    _check_contract_occ(body, contract)

    check_unknown_fields(body, SHORT_CLOSE_ALLOWED)
    require_fields(body, ["expected_contract_version"])
    v_int(body, "expected_contract_version")

    contract["fulfillment_status"] = "SHORT_CLOSED"
    contract["unpriced_lbs"] = 0
    touch(contract)

    for h in DB.futures_hedges.values():
        if h["contract_id"] == contract["id"] and h["hedge_status"] in ("WORKING", "APPROVED"):
            h["hedge_status"] = "CANCELLED"
            touch(h)

    cp = DB.counterparties.get(contract["counterparty_id"])
    if cp is not None:
        recompute_counterparty_exposure(cp)
    return success_object(pub(contract))


CANCEL_ALLOWED = CONTRACT_SYS


@bp.post("/roastery/contracts/<contract_id>/cancel")
def cancel_contract(contract_id):
    require_role("Trader")
    contract = get_contract_or_404(contract_id)
    body = get_json_body()
    check_unknown_fields(body, CANCEL_ALLOWED)

    if contract["fulfillment_status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Cancel requires fulfillment_status OPEN")
    if any(s["contract_id"] == contract["id"] for s in DB.shipments.values()):
        raise err(ERR_INVALID_STATE, "Cancel blocked: shipments exist for this contract")
    if any(e["contract_id"] == contract["id"] for e in DB.price_fixes.values()):
        raise err(ERR_INVALID_STATE, "Cancel blocked: price-fix events exist for this contract")
    if any(
        h["contract_id"] == contract["id"] and h["hedge_status"] in ("WORKING", "APPROVED")
        for h in DB.futures_hedges.values()
    ):
        raise err(ERR_INVALID_STATE, "Cancel blocked: live futures hedges exist for this contract")

    contract["fulfillment_status"] = "CANCELLED"
    contract["unpriced_lbs"] = 0
    touch(contract)

    cp = DB.counterparties.get(contract["counterparty_id"])
    if cp is not None:
        recompute_counterparty_exposure(cp)
    return success_object(pub(contract))
