"""Calculation engines: feed call, yardage, death loss value, COG, grid value, hedge."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date

import store
import clock
from util import dec, round_half_up_int, round_half_up_tenth, round_half_up_2dp, days_between


# ---------------------------------------------------------------------------
# Constants from scaffold
# ---------------------------------------------------------------------------
BUNK_DELTA = {0: 0.75, 1: 0.25, 2: 0.0, 3: -0.75}
MIN_QTY = 8.0
MAX_QTY = 30.0
YARDAGE_RATE = 45  # cents per head-day
CONTRACT_CWT = 400  # 40,000 lb live-cattle contract
OUT_WEIGHT_FACTOR = 1.5  # projected out-weight = avg in-weight x 1.5
ADG_LBS_PER_HEAD_DAY = 3.4

# Grid pricing constants (cents per cwt)
QP = {"PRIME": 1200, "CHOICE": 0, "SELECT": -1800, "STANDARD": -3500}
YD = {1: 400, 2: 200, 3: 0, 4: -2000, 5: -3500}


# ---------------------------------------------------------------------------
# Yardage head-days calculation
# ---------------------------------------------------------------------------
def yardage_head_days(lot, from_date, to_date):
    """Compute head-days for a lot over [from_date, to_date).

    For each PenAssignment of the lot (processed by start_date ASC, created_at ASC),
    collect boundary dates: start_date, each non-VOID DeathLoss loss_date allocated
    to it, min(end_date, to_date). Segment [d_i, d_{i+1}) contributes head_i x
    days(d_i, d_{i+1}) where head_i is the head_count after applying all death
    allocations with loss_date <= d_i.
    """
    # Get all pen assignments for this lot, sorted by start_date ASC, created_at ASC
    assignments = [pa for pa in store.pen_assignments.values() if pa["lot_id"] == lot["id"]]
    assignments.sort(key=lambda pa: (pa["start_date"], pa["created_at"]))

    total_head_days = 0

    for pa in assignments:
        # Get death losses allocated to this assignment
        losses = []
        for dl in store.death_losses.values():
            if dl["lot_id"] == lot["id"] and dl["status"] == "RECORDED":
                for alloc in dl.get("allocations", []):
                    if alloc["assignment_id"] == pa["id"]:
                        losses.append({"loss_date": dl["loss_date"], "head_count": alloc["head_count"]})
                        break

        # Build boundary dates
        boundaries = set()
        boundaries.add(pa["start_date"])
        for loss in losses:
            if from_date <= loss["loss_date"] <= to_date:
                boundaries.add(loss["loss_date"])
        # End boundary
        effective_end = pa["end_date"] if pa["end_date"] else to_date
        effective_end = min(effective_end, to_date)
        boundaries.add(effective_end)

        # Clip to [from_date, to_date)
        boundaries = sorted(b for b in boundaries if from_date <= b <= to_date)
        if not boundaries or boundaries[-1] < to_date:
            if not boundaries:
                boundaries = [from_date]
            if boundaries[-1] < to_date and pa["status"] == "ACTIVE":
                boundaries.append(min(to_date, effective_end))

        # Compute segments
        for i in range(len(boundaries) - 1):
            seg_start = boundaries[i]
            seg_end = boundaries[i + 1]
            if seg_start >= to_date or seg_end <= from_date:
                continue
            seg_start_clipped = max(seg_start, from_date)
            seg_end_clipped = min(seg_end, to_date)
            if seg_end_clipped <= seg_start_clipped:
                continue

            # Head count at segment start: the assignment's head count BEFORE
            # any death allocations (its current head_count is already reduced
            # by every non-void allocation; add them back to reconstruct the
            # original), minus allocations with loss_date <= seg_start — a death
            # reduces the count only for dates from its loss date onward.
            original_head = pa["head_count"] + sum(l["head_count"] for l in losses)
            head_at_start = original_head
            for loss in losses:
                if loss["loss_date"] <= seg_start:
                    head_at_start -= loss["head_count"]

            days = days_between(seg_start_clipped, seg_end_clipped)
            total_head_days += head_at_start * days

    return total_head_days


def yardage_cents_final(lot):
    """Final yardage: [arrival_date, ship_date)."""
    if lot["status"] not in ("SHIPPED", "CLOSED_OUT", "SETTLED"):
        return 0
    ship_date = lot.get("_ship_date")
    if ship_date is None:
        return 0
    hd = yardage_head_days(lot, lot["arrival_date"], ship_date)
    return hd * YARDAGE_RATE, hd


def yardage_cents_provisional(lot):
    """Provisional yardage: [arrival_date, current logical date)."""
    current = clock.today()
    hd = yardage_head_days(lot, lot["arrival_date"], current)
    return hd * YARDAGE_RATE, hd


# ---------------------------------------------------------------------------
# Death loss value
# ---------------------------------------------------------------------------
def compute_death_loss_value(lot, loss_date, head_count):
    """Compute loss_value_cents per calculations.death_loss_value.

    Uses lot's cost accumulators as of loss_date; head_count_current BEFORE
    applying this loss.
    """
    # in_cost_per_head = round_half_up(purchase_cost_cents / head_count_in, 1)
    in_cost_per_head = round_half_up_int(
        dec(lot["purchase_cost_cents"]) / dec(lot["head_count_in"])
    )

    # accrued_basis = total_feed_cost_cents + yardage accrued over [arrival, loss_date)
    #               + total_health_cost_cents
    yardage_hd = yardage_head_days(lot, lot["arrival_date"], loss_date)
    yardage_cents = yardage_hd * YARDAGE_RATE
    accrued_basis = (
        lot["total_feed_cost_cents"]
        + yardage_cents
        + lot["total_health_cost_cents"]
    )

    # accrued_per_head = round_half_up(accrued_basis / head_count_current_before, 1)
    head_count_current_before = lot["head_count_current"]
    if head_count_current_before <= 0:
        accrued_per_head = 0
    else:
        accrued_per_head = round_half_up_int(
            dec(accrued_basis) / dec(head_count_current_before)
        )

    # loss_value_cents = head_count x (in_cost_per_head + accrued_per_head)
    loss_value = head_count * (in_cost_per_head + accrued_per_head)
    return loss_value


# ---------------------------------------------------------------------------
# Cost of gain
# ---------------------------------------------------------------------------
def compute_provisional_cog(lot):
    """Compute provisional COG for a lot.

    Returns None when projected gain <= 0.
    """
    current = clock.today()
    arrival = lot["arrival_date"]
    days_on_feed = days_between(arrival, current)
    if days_on_feed <= 0:
        return None

    head_count_current = lot["head_count_current"]
    gain_lbs = head_count_current * days_on_feed * ADG_LBS_PER_HEAD_DAY
    if gain_lbs <= 0:
        return None

    # Cost pool
    yardage_cents, _ = yardage_cents_provisional(lot)
    total_cost = (
        lot["purchase_cost_cents"]
        + lot["total_feed_cost_cents"]
        + yardage_cents
        + lot["total_health_cost_cents"]
        + lot["total_death_loss_cents"]
    )

    # gain_cwt = gain_lbs / 100
    gain_cwt = dec(gain_lbs) / dec(100)
    cog = round_half_up_2dp(dec(total_cost) / gain_cwt)
    return cog


def compute_final_cog(lot, out_weight_total_lbs, head_shipped):
    """Compute final COG at close-out confirm.

    gain_cwt = (out_weight - in_weight x head_shipped / head_count_in) / 100
    """
    in_weight_attributable = (
        dec(lot["in_weight_total_lbs"]) * dec(head_shipped) / dec(lot["head_count_in"])
    )
    gain_lbs = dec(out_weight_total_lbs) - in_weight_attributable
    if gain_lbs <= 0:
        return None

    # Cost pool with final yardage
    yardage_cents, _ = yardage_cents_final(lot)
    total_cost = (
        lot["purchase_cost_cents"]
        + lot["total_feed_cost_cents"]
        + yardage_cents
        + lot["total_health_cost_cents"]
        + lot["total_death_loss_cents"]
    )

    gain_cwt = gain_lbs / dec(100)
    cog = round_half_up_2dp(dec(total_cost) / gain_cwt)
    return cog


# ---------------------------------------------------------------------------
# Feed call quantity
# ---------------------------------------------------------------------------
def compute_feed_call_quantity(pen, bunk_score, base_qty_lbs_per_head):
    """Compute qty_lbs_per_head for a feed call.

    First call: base_qty_lbs_per_head input required, used as qty_raw.
    Later calls: bunk_score input required, qty_raw = prev_qty + BUNK_DELTA[bunk_score].
    """
    # Get prior feed calls for this pen
    prior_calls = [fc for fc in store.feed_calls.values() if fc["pen_id"] == pen["id"]]
    prior_calls.sort(key=lambda fc: (fc["call_date"], fc["created_at"]), reverse=True)

    if not prior_calls:
        # First call
        if base_qty_lbs_per_head is None:
            from errors import raise_err, ERR_INVALID_REQUEST
            raise_err(ERR_INVALID_REQUEST,
                      "base_qty_lbs_per_head is required for the pen's first feed call")
        if bunk_score is not None:
            from errors import raise_err, ERR_INVALID_REQUEST
            raise_err(ERR_INVALID_REQUEST,
                      "bunk_score is forbidden for the pen's first feed call")
        qty_raw = base_qty_lbs_per_head
    else:
        # Subsequent call
        if bunk_score is None:
            from errors import raise_err, ERR_INVALID_REQUEST
            raise_err(ERR_INVALID_REQUEST,
                      "bunk_score is required when the pen has a prior feed call")
        if base_qty_lbs_per_head is not None:
            from errors import raise_err, ERR_INVALID_REQUEST
            raise_err(ERR_INVALID_REQUEST,
                      "base_qty_lbs_per_head is forbidden when the pen has a prior feed call")
        if bunk_score not in BUNK_DELTA:
            from errors import raise_err, ERR_INVALID_REQUEST
            raise_err(ERR_INVALID_REQUEST,
                      "bunk_score must be one of 0, 1, 2, 3")
        prev_qty = prior_calls[0]["qty_lbs_per_head"]
        qty_raw = prev_qty + BUNK_DELTA[bunk_score]

    # Clamp and round
    qty_lbs_per_head = round_half_up_tenth(min(max(qty_raw, MIN_QTY), MAX_QTY))
    return qty_lbs_per_head


def compute_feed_call_totals(pen, qty_lbs_per_head, ration):
    """Compute total_qty_lbs and total_cost_cents."""
    total_qty_lbs = round_half_up_int(
        dec(qty_lbs_per_head) * dec(pen["current_occupancy_head"])
    )
    total_cost_cents = round_half_up_int(
        dec(total_qty_lbs) / dec(2000) * dec(ration["cost_per_ton_cents"])
    )
    return total_qty_lbs, total_cost_cents


def derive_common_ration(pen):
    """Derive the common ACTIVE ration of the lots in the pen.

    Commingled lots are required to share one ration.
    Returns the ration record or None.
    """
    active_assignments = [
        pa for pa in store.pen_assignments.values()
        if pa["pen_id"] == pen["id"] and pa["status"] == "ACTIVE"
    ]
    if not active_assignments:
        return None

    # Get the lot for each assignment
    lot_ids = set(pa["lot_id"] for pa in active_assignments)

    # Get active ration assignments for these lots
    ration_ids = set()
    for lot_id in lot_ids:
        for ra in store.ration_assignments.values():
            if ra["lot_id"] == lot_id and ra["status"] == "ACTIVE":
                ration_ids.add(ra["ration_id"])

    if len(ration_ids) == 1:
        rid = ration_ids.pop()
        return store.rations.get(rid)
    return None


# ---------------------------------------------------------------------------
# Feed cost allocation (waterfall)
# ---------------------------------------------------------------------------
def allocate_feed_cost(pen, total_cost_cents):
    """Distribute total_cost_cents across pen's ACTIVE assignments proportional
    to head_count. Last assignment gets residual."""
    active_assignments = [
        pa for pa in store.pen_assignments.values()
        if pa["pen_id"] == pen["id"] and pa["status"] == "ACTIVE"
    ]
    active_assignments.sort(key=lambda pa: pa["created_at"])

    if not active_assignments:
        return

    total_head = sum(pa["head_count"] for pa in active_assignments)
    if total_head <= 0:
        return

    shares = []
    running_sum = 0

    for i, pa in enumerate(active_assignments):
        if i == len(active_assignments) - 1:
            # Last assignment gets residual
            share = total_cost_cents - running_sum
        else:
            share = round_half_up_int(
                dec(total_cost_cents) * dec(pa["head_count"]) / dec(total_head)
            )
            running_sum += share
        shares.append((pa, share))

    # Apply shares to lots
    from services import lot_service
    for pa, share in shares:
        lot = store.lots.get(pa["lot_id"])
        if lot:
            lot["total_feed_cost_cents"] += share
            lot_service.bump_lot(lot)


# ---------------------------------------------------------------------------
# Hedge coverage
# ---------------------------------------------------------------------------
def compute_marketable_cwt(lot):
    """Compute marketable hundredweight for hedge coverage."""
    if lot["head_count_in"] <= 0:
        return 0
    marketable = round_half_up_int(
        dec(lot["head_count_current"])
        * dec(lot["in_weight_total_lbs"])
        * dec(3)
        / (dec(lot["head_count_in"]) * dec(200))
    )
    return marketable


def check_hedge_coverage(lot, new_quantity_contracts):
    """Check hedge coverage rule. Raises ERR_HEDGE_OVER_COVERED if exceeded."""
    from errors import raise_err, ERR_HEDGE_OVER_COVERED

    marketable_cwt = compute_marketable_cwt(lot)

    # Sum OPEN hedge positions
    open_cwt = sum(
        h["quantity_contracts"] * CONTRACT_CWT
        for h in store.hedge_positions.values()
        if h["lot_id"] == lot["id"] and h["status"] == "OPEN"
    )

    # Add new position
    open_cwt_after = open_cwt + (new_quantity_contracts * CONTRACT_CWT)

    if open_cwt_after > marketable_cwt:
        raise_err(ERR_HEDGE_OVER_COVERED,
                  "Hedge coverage would exceed marketable cwt (%d > %d)"
                  % (open_cwt_after, marketable_cwt))


def compute_hedge_pnl(hedge, exit_price_cents_per_cwt):
    """Compute realized P&L for a hedge position."""
    entry = hedge["entry_price_cents_per_cwt"]
    qty = hedge["quantity_contracts"]

    if hedge["side"] == "SHORT":
        pnl = (entry - exit_price_cents_per_cwt) * CONTRACT_CWT * qty
    else:  # LONG
        pnl = (exit_price_cents_per_cwt - entry) * CONTRACT_CWT * qty

    return pnl


# ---------------------------------------------------------------------------
# Grid value
# ---------------------------------------------------------------------------
def compute_grid_value_per_carcass(carcass_records, grid_base_price_cents_per_cwt):
    """PER_CARCASS: round each carcass line to cents FIRST, then sum."""
    total = Decimal("0")
    for rec in carcass_records:
        hcw = dec(rec["hot_carcass_weight_lbs"])
        qp = dec(QP[rec["quality_grade"]])
        yd = dec(YD[rec["yield_grade"]])
        price = dec(grid_base_price_cents_per_cwt) + qp + yd
        value = (hcw / dec(100)) * price
        value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += value
    return float(total)


def compute_grid_value_lot_average(carcass_records, grid_base_price_cents_per_cwt):
    """LOT_AVERAGE: weight-averaged adjustments, single rounding at end."""
    total_hcw = sum(dec(rec["hot_carcass_weight_lbs"]) for rec in carcass_records)
    if total_hcw <= 0:
        return 0.0

    # Weighted average QP
    sum_qp_hcw = sum(
        dec(QP[rec["quality_grade"]]) * dec(rec["hot_carcass_weight_lbs"])
        for rec in carcass_records
    )
    avg_qp = (sum_qp_hcw / total_hcw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Weighted average YD
    sum_yd_hcw = sum(
        dec(YD[rec["yield_grade"]]) * dec(rec["hot_carcass_weight_lbs"])
        for rec in carcass_records
    )
    avg_yd = (sum_yd_hcw / total_hcw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    avg_price = dec(grid_base_price_cents_per_cwt) + avg_qp + avg_yd
    total_value = (total_hcw / dec(100)) * avg_price
    total_value = total_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(total_value)


# ---------------------------------------------------------------------------
# Invoice total
# ---------------------------------------------------------------------------
def compute_invoice_total(lot):
    """Compute invoice lines per calculations.invoice_total.

    Returns dict with all invoice fields.
    """
    feed_cents = lot["total_feed_cost_cents"]
    yardage_cents, yardage_head_days = yardage_cents_final(lot)
    health_cents = lot["total_health_cost_cents"]
    death_loss_cents = lot["total_death_loss_cents"]

    # Insurance credit: min(pending, sum of charges)
    charges_sum = feed_cents + yardage_cents + health_cents + death_loss_cents
    insurance_credit = min(lot["insurance_credit_pending_cents"], charges_sum)
    lot["insurance_credit_pending_cents"] -= insurance_credit

    total_cents = charges_sum - insurance_credit

    return {
        "feed_cents": feed_cents,
        "yardage_cents": yardage_cents,
        "yardage_head_days": yardage_head_days,
        "health_cents": health_cents,
        "death_loss_cents": death_loss_cents,
        "insurance_credit_cents": insurance_credit,
        "total_cents": total_cents,
    }
