"""Hedge position business logic."""
import store
import clock
from util import new_record, bump, month_first_day
from errors import raise_err, ERR_HEDGE_NOT_OPEN, ERR_INVALID_REQUEST, \
    ERR_STALE_VERSION, ERR_LOT_NOT_FOUND
from . import lot_service
from . import calculations


def create_hedge(lot, contract_month, side, quantity_contracts,
                 entry_price_cents_per_cwt, expected_lot_version):
    """Create a hedge position for a lot (OCC-guarded)."""
    lot_service.check_lot_open(lot)

    # OCC check
    if expected_lot_version is not None and expected_lot_version != lot["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_lot_version (%d) does not match lot's current version (%d)"
                  % (expected_lot_version, lot["version"]))

    # Hedge coverage check
    calculations.check_hedge_coverage(lot, quantity_contracts)

    rec = new_record()
    rec.update({
        "lot_id": lot["id"],
        "contract_month": contract_month,
        "side": side,
        "quantity_contracts": quantity_contracts,
        "entry_price_cents_per_cwt": entry_price_cents_per_cwt,
        "exit_price_cents_per_cwt": None,
        "realized_pnl_cents": None,
        "status": "OPEN",
    })
    store.hedge_positions[rec["id"]] = rec

    lot_service.bump_lot(lot)
    return rec


def offset_hedge(hedge, exit_price_cents_per_cwt, offset_date):
    """Offset (close) an OPEN hedge and realize P&L."""
    if hedge["status"] != "OPEN":
        raise_err(ERR_HEDGE_NOT_OPEN,
                  "Hedge %s is not OPEN (status=%s)" % (hedge["id"], hedge["status"]))

    # Validate offset_date not in future
    if offset_date > clock.today():
        raise_err(ERR_INVALID_REQUEST,
                  "offset_date must not be in the future")

    lot = store.lots.get(hedge["lot_id"])
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND, "Lot not found: %s" % hedge["lot_id"])

    # Compute P&L
    realized_pnl = calculations.compute_hedge_pnl(hedge, exit_price_cents_per_cwt)

    hedge["exit_price_cents_per_cwt"] = exit_price_cents_per_cwt
    hedge["realized_pnl_cents"] = realized_pnl
    hedge["status"] = "OFFSET"
    bump(hedge)

    lot["total_hedge_pnl_cents"] += realized_pnl
    lot_service.bump_lot(lot)

    return hedge


def expire_hedges_for_clock_advance():
    """Expire OPEN hedges whose contract month has begun."""
    current_date = clock.today()
    for hedge in store.hedge_positions.values():
        if hedge["status"] == "OPEN":
            contract_first = month_first_day(hedge["contract_month"])
            if contract_first <= current_date:
                hedge["exit_price_cents_per_cwt"] = hedge["entry_price_cents_per_cwt"]
                hedge["realized_pnl_cents"] = 0
                hedge["status"] = "EXPIRED"
                bump(hedge)
                # Note: lot P&L unchanged for expired hedges
