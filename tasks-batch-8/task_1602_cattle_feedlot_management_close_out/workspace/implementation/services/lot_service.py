"""Lot business logic: state transitions, version management, COG recompute."""
import store
import clock
from util import bump
from . import calculations


def bump_lot(lot):
    """Increment lot version and recompute provisional COG."""
    bump(lot)
    recompute_provisional_cog(lot)


def recompute_provisional_cog(lot):
    """Recompute lot's provisional_cog_cents_per_cwt."""
    if lot["status"] == "SETTLED":
        return
    lot["provisional_cog_cents_per_cwt"] = calculations.compute_provisional_cog(lot)


def recompute_withdrawal_clear_date(lot):
    """Recompute lot's withdrawal_clear_date as max of all HealthEvents' end dates."""
    events = [he for he in store.health_events.values() if he["lot_id"] == lot["id"]]
    if not events:
        lot["withdrawal_clear_date"] = None
    else:
        lot["withdrawal_clear_date"] = max(he["withdrawal_end_date"] for he in events)


def check_lot_open(lot):
    """Raise ERR_LOT_NOT_OPEN if lot is not OPEN."""
    from errors import raise_err, ERR_LOT_NOT_OPEN
    if lot["status"] != "OPEN":
        raise_err(ERR_LOT_NOT_OPEN, "Lot %s is not OPEN (status=%s)" % (lot["id"], lot["status"]))


def check_lot_marketed(lot):
    """Raise ERR_LOT_NOT_MARKETED if lot is not MARKETED."""
    from errors import raise_err, ERR_LOT_NOT_MARKETED
    if lot["status"] != "MARKETED":
        raise_err(ERR_LOT_NOT_MARKETED, "Lot %s is not MARKETED (status=%s)" % (lot["id"], lot["status"]))


def check_lot_closable(lot):
    """Raise ERR_LOT_NOT_CLOSABLE if lot is not SHIPPED or CLOSED_OUT."""
    from errors import raise_err, ERR_LOT_NOT_CLOSABLE
    if lot["status"] not in ("SHIPPED", "CLOSED_OUT"):
        raise_err(ERR_LOT_NOT_CLOSABLE,
                  "Lot %s is not SHIPPED or CLOSED_OUT (status=%s)" % (lot["id"], lot["status"]))


def check_lot_has_head(lot):
    """Raise ERR_LOT_HAS_NO_HEAD if head_count_current < 1."""
    from errors import raise_err, ERR_LOT_HAS_NO_HEAD
    if lot["head_count_current"] < 1:
        raise_err(ERR_LOT_HAS_NO_HEAD, "Lot %s has no head on feed" % lot["id"])


def market_lot(lot):
    """OPEN -> MARKETED."""
    check_lot_open(lot)
    check_lot_has_head(lot)
    lot["status"] = "MARKETED"
    bump_lot(lot)


def fail_sale(lot):
    """MARKETED -> OPEN (sale fell through)."""
    check_lot_marketed(lot)
    lot["status"] = "OPEN"
    bump_lot(lot)


def ship_lot(lot, ship_date, out_weight_total_lbs):
    """MARKETED -> SHIPPED with cascades."""
    from errors import raise_err, ERR_WITHDRAWAL_NOT_CLEARED, ERR_INVALID_REQUEST
    from . import pen_service

    check_lot_marketed(lot)

    # Validate ship_date range
    if ship_date < lot["arrival_date"] or ship_date > clock.today():
        raise_err(ERR_INVALID_REQUEST,
                  "ship_date must be within [arrival_date, current date]")

    # Check withdrawal cleared
    if lot["withdrawal_clear_date"] is not None:
        if ship_date < lot["withdrawal_clear_date"]:
            raise_err(ERR_WITHDRAWAL_NOT_CLEARED,
                      "Lot %s has uncleared withdrawal until %s"
                      % (lot["id"], lot["withdrawal_clear_date"].isoformat()))

    # Set ship fields
    lot["head_shipped"] = lot["head_count_current"]
    lot["out_weight_total_lbs"] = out_weight_total_lbs
    lot["_ship_date"] = ship_date  # Store for yardage calculation
    lot["status"] = "SHIPPED"

    # End all ACTIVE pen assignments
    for pa in store.pen_assignments.values():
        if pa["lot_id"] == lot["id"] and pa["status"] == "ACTIVE":
            pa["status"] = "ENDED"
            pa["end_date"] = ship_date
            bump(pa)

    # Recompute pen occupancies
    pen_service.recompute_all_pen_occupancies()

    # Close all ACTIVE ration assignments
    for ra in store.ration_assignments.values():
        if ra["lot_id"] == lot["id"] and ra["status"] == "ACTIVE":
            ra["status"] = "CLOSED"
            ra["end_date"] = ship_date
            bump(ra)

    bump_lot(lot)


def close_out_lot(lot):
    """SHIPPED -> CLOSED_OUT (triggered by CloseOut confirm)."""
    lot["status"] = "CLOSED_OUT"
    bump_lot(lot)


def settle_lot(lot):
    """CLOSED_OUT -> SETTLED (triggered by Invoice PAID)."""
    lot["status"] = "SETTLED"
    bump_lot(lot)
