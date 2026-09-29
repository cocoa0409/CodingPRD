"""The thirteen declared calculations of PRD §2.6 / §3, implemented with exact
decimal arithmetic."""

from decimal import Decimal

import config
import db
import util


# ---------------------------------------------------------------------------
# 1. water_quality_status
# ---------------------------------------------------------------------------
def recompute_water_status(block):
    rows = db.water_tests_of_block(block["id"])
    window = rows[-config.WATER_SAMPLE_WINDOW :]
    n = len(window)
    if n == 0:
        block["water_sample_count"] = 0
        block["water_geomean_mpn"] = None
        block["water_status"] = "NO_SAMPLES"
        block["last_sample_date"] = None
        block["_last_sample_date"] = None
        return block["water_status"]

    newest = window[-1]
    geomean = util.geomean1([r["generic_ecoli_mpn"] for r in window])
    block["water_sample_count"] = n
    block["water_geomean_mpn"] = geomean
    block["last_sample_date"] = newest["sample_date"]
    block["_last_sample_date"] = newest["_sample_date"]

    if newest["generic_ecoli_mpn"] > config.SINGLE_SAMPLE_MAX_MPN:
        status = "FAILED"
    elif n < config.MIN_SAMPLES_FOR_COMPLIANT:
        status = "PROVISIONAL"
    elif geomean <= config.GEOMEAN_LIMIT_MPN:
        status = "COMPLIANT"
    else:
        status = "NON_COMPLIANT"
    block["water_status"] = status
    return status


# ---------------------------------------------------------------------------
# 2. block_food_safety_posture
# ---------------------------------------------------------------------------
def recompute_posture(block):
    if block["manual_quarantine_active"]:
        block["food_safety_posture"] = "QUARANTINED"
    elif block["water_status"] in ("PROVISIONAL", "COMPLIANT"):
        block["food_safety_posture"] = "CLEARED"
    else:
        block["food_safety_posture"] = "RESTRICTED"
    return block["food_safety_posture"]


# ---------------------------------------------------------------------------
# 3. window_crew_requirement
# ---------------------------------------------------------------------------
def staffing_estimate(window, block):
    variety = block["variety"]
    base = config.VARIETY_PICK_RATE[variety]
    target = config.BRIX_TARGET[variety]
    multiplier = (
        config.RIPE_MULTIPLIER
        if util.dec(window["forecast_brix"]) >= target
        else Decimal("1.00")
    )
    rate = util.q2(base * multiplier)
    capacity = rate * util.dec(window["window_hours"])
    if capacity <= 0:
        required = config.CREW_CAP + 1
    else:
        required = max(
            config.MIN_PICKER_FLOOR,
            util.iceil(util.dec(window["planned_volume_lbs"]) / capacity),
        )
    return rate, required


def apply_staffing_estimate(window, block):
    rate, required = staffing_estimate(window, block)
    window["effective_pick_rate_lbs_per_hour"] = rate
    window["required_picker_count"] = required
    return rate, required


# ---------------------------------------------------------------------------
# 4. session_pay_per_session
# ---------------------------------------------------------------------------
def price_session(session, window, crew):
    filled = int(session["clamshells_filled"])
    culled = int(session["culled_clamshells"])

    # step 1: quality grading
    if filled == 0:
        cull_rate = util.q4(0)
    else:
        cull_rate = util.q4(util.dec(culled) / util.dec(filled))
    session["cull_rate"] = cull_rate
    session["quality_flag"] = (
        "MEETS_STANDARD" if cull_rate <= config.MAX_CULL_RATE else "BELOW_STANDARD"
    )

    # step 2: the effective piece rate
    window_rate = int(window["piece_rate_cents_per_clamshell"])
    if session["quality_flag"] == "MEETS_STANDARD":
        effective = window_rate
    else:
        effective = util.q0(
            util.dec(window_rate) * (Decimal("1") - config.QUALITY_DERATE_PCT)
        )
    session["effective_piece_rate_cents"] = effective

    # step 3: piece earnings — culls are never paid
    saleable = filled - culled
    piece = effective * saleable
    session["piece_cents"] = piece

    # step 4: the per-session minimum-wage guarantee
    floor_cents = util.q0(
        util.dec(session["hours_worked"]) * config.MIN_WAGE_CENTS_PER_HOUR
    )
    makeup = max(0, floor_cents - piece)
    gross = piece + makeup
    session["guarantee_floor_cents"] = floor_cents
    session["makeup_cents"] = makeup
    session["gross_cents"] = gross

    # step 5: housing deduction, capped against the made-whole gross (FLOOR)
    if crew["labor_program"] == "H2A" and crew.get("housing_unit_code") is not None:
        deduction = min(
            config.HOUSING_DAILY_DEDUCTION_CENTS,
            util.ifloor(util.dec(gross) * config.DEDUCTION_GROSS_CAP_PCT),
        )
    else:
        deduction = 0
    session["housing_deduction_cents"] = deduction
    session["net_cents"] = gross - deduction
    return session


# ---------------------------------------------------------------------------
# 5. payroll_period_averaged_settlement
# ---------------------------------------------------------------------------
def settle_period(run, sessions, crew):
    period_hours = util.q2(sum((util.dec(s["hours_worked"]) for s in sessions), util.ZERO))
    period_piece = sum(int(s["piece_cents"]) for s in sessions)

    period_floor = util.q0(period_hours * config.MIN_WAGE_CENTS_PER_HOUR)
    period_makeup = max(0, period_floor - period_piece)
    settled_gross = period_piece + period_makeup

    if crew["labor_program"] == "H2A" and crew.get("housing_unit_code") is not None:
        housing_sessions = len(sessions)
    else:
        housing_sessions = 0
    period_deduction = min(
        config.HOUSING_DAILY_DEDUCTION_CENTS * housing_sessions,
        util.ifloor(util.dec(settled_gross) * config.DEDUCTION_GROSS_CAP_PCT),
    )
    settled_net = settled_gross - period_deduction
    net_sum = sum(int(s["net_cents"]) for s in sessions)

    run["period_hours"] = period_hours
    run["period_piece_cents"] = period_piece
    run["period_floor_cents"] = period_floor
    run["period_makeup_cents"] = period_makeup
    run["period_deduction_cents"] = period_deduction
    run["settled_gross_cents"] = settled_gross
    run["settled_net_cents"] = settled_net
    run["reconciliation_delta_cents"] = settled_net - net_sum
    return net_sum


# ---------------------------------------------------------------------------
# 6. picker_productivity
# ---------------------------------------------------------------------------
PAID_STATUSES = ("APPROVED", "SETTLED")


def recompute_picker_productivity(picker):
    paid = [
        s
        for s in db.sessions_of_picker(picker["id"])
        if s["status"] in PAID_STATUSES
    ]
    clamshells = 0
    hours = util.ZERO
    paid_lbs = util.ZERO
    for s in paid:
        saleable = int(s["clamshells_filled"]) - int(s["culled_clamshells"])
        clamshells += saleable
        hours += util.dec(s["hours_worked"])
        window = db.harvest_windows.get(s["harvest_window_id"])
        weight = (
            util.dec(window["clamshell_net_weight_lbs"]) if window else util.ZERO
        )
        paid_lbs += util.dec(saleable) * weight
    total_hours = util.q2(hours)
    picker["total_clamshells_lifetime"] = clamshells
    picker["total_hours_lifetime"] = total_hours
    if total_hours == 0:
        picker["avg_lbs_per_hour"] = util.q2(0)
    else:
        picker["avg_lbs_per_hour"] = util.q2(paid_lbs / total_hours)
    return picker


def recompute_window_harvested(window):
    total = 0
    for s in db.sessions_of_window(window["id"]):
        if s["status"] in PAID_STATUSES:
            total += int(s["clamshells_filled"])
    window["harvested_clamshells"] = total
    return total


def recompute_window_packed(window):
    total = util.ZERO
    for lot in db.lots_of_window(window["id"]):
        if lot["disposition_status"] != "REJECTED":
            total += util.dec(lot["net_packed_lbs"])
    window["packed_lbs"] = util.q2(total)
    return window["packed_lbs"]


# ---------------------------------------------------------------------------
# 7. lot_shelf_life (forecast and verified variants)
# ---------------------------------------------------------------------------
def shelf_life_days(lot, cool_end_instant, exit_temp):
    base = config.VARIETY_BASE_SHELF_LIFE[lot["variety"]]
    grade_derate = config.GRADE_DERATE[lot["grade"]]

    field_delay = util.dec(lot["field_delay_hours"])
    field_penalty = util.iceil(max(util.ZERO, field_delay - config.FIELD_HEAT_MAX_HOURS))

    cool_hours = util.hours_between(lot["_cool_start_at"], cool_end_instant)
    cool_penalty = util.iceil(max(util.ZERO, cool_hours - config.TARGET_COOL_HOURS))

    if exit_temp is None:
        temp_penalty = 0
    else:
        excess = max(util.ZERO, util.dec(exit_temp) - config.EXIT_TEMP_TARGET_F)
        temp_penalty = util.ifloor(excess / config.EXIT_TEMP_STEP_F)

    days = base - grade_derate - field_penalty - cool_penalty - temp_penalty
    return max(config.SHELF_LIFE_FLOOR_DAYS, days), cool_hours


# ---------------------------------------------------------------------------
# 8. lot_pack_mass_balance
# ---------------------------------------------------------------------------
def recompute_lot_balance(lot):
    allocated = util.ZERO
    for a in db.allocations_of_lot(lot["id"]):
        if a["status"] in ("RESERVED", "SHIPPED"):
            allocated += util.dec(a["allocated_lbs"])
    lot["allocated_lbs"] = util.q2(allocated)
    if lot["disposition_status"] == "REJECTED":
        lot["available_lbs"] = util.q2(0)
        return lot["available_lbs"]
    available = (
        util.dec(lot["net_packed_lbs"])
        - util.dec(lot["allocated_lbs"])
        - util.dec(lot["repack_out_lbs"])
        - util.dec(lot["cull_lbs"])
        - util.dec(lot["optical_reject_lbs"])
    )
    lot["available_lbs"] = util.q2(available)
    return lot["available_lbs"]


def traceability_code(block, pick_date_raw, pick_date, grade):
    seq = 1
    for lot in db.lots_of_block(block["id"]):
        if lot["_pick_date"] == pick_date and lot["grade"] == grade:
            seq += 1
    return "%s-%s-%s-%03d" % (
        block["name"],
        util.compact_date(pick_date),
        grade,
        seq,
    )


# ---------------------------------------------------------------------------
# 9. tunnel_occupancy — HALF-OPEN interval, back-to-back runs are legal
# ---------------------------------------------------------------------------
def tunnel_has_room(tunnel, start, end, requested_slots, exclude_lot_id=None):
    occupied = 0
    for lot in db.lots_of_tunnel(tunnel["id"]):
        if lot["id"] == exclude_lot_id:
            continue
        if lot["cold_chain_status"] != "COOLING":
            continue
        if lot.get("_cool_start_at") is None or lot.get("_planned_cool_end_at") is None:
            continue
        if lot["_cool_start_at"] < end and lot["_planned_cool_end_at"] > start:
            occupied += int(lot["pallet_slots"])
    return occupied + int(requested_slots) <= int(tunnel["slot_capacity"])


# ---------------------------------------------------------------------------
# 10. block_window_separation — the buffer makes adjacency a CONFLICT
# ---------------------------------------------------------------------------
LIVE_WINDOW_STATUSES = ("PLANNED", "CONFIRMED", "OPEN", "SUSPENDED")


def has_reentry_conflict(block_id, start, end, candidate_id=None):
    buffer = util.timedelta_hours(config.BLOCK_REENTRY_BUFFER_HOURS)
    for other in db.windows_of_block(block_id):
        if candidate_id is not None and other["id"] == candidate_id:
            continue
        if other["status"] not in LIVE_WINDOW_STATUSES:
            continue
        if start < other["_end_at"] + buffer and end + buffer > other["_start_at"]:
            return True
    return False


# ---------------------------------------------------------------------------
# 11. commitment exposure and settlement
# ---------------------------------------------------------------------------
def recompute_commitment_exposure(commitment):
    committed = util.ZERO
    shipped = util.ZERO
    for a in db.allocations_of_commitment(commitment["id"]):
        if a["status"] in ("RESERVED", "SHIPPED"):
            committed += util.dec(a["allocated_lbs"])
        if a["status"] == "SHIPPED":
            shipped += util.dec(a["allocated_lbs"])
    volume = util.dec(commitment["volume_commitment_lbs"])
    commitment["committed_lbs"] = util.q2(committed)
    commitment["shipped_lbs"] = util.q2(shipped)
    commitment["open_lbs"] = max(util.q2(0), util.q2(volume - committed))
    commitment["fill_pct"] = util.q4(shipped / volume) if volume > 0 else util.q4(0)
    coverage = util.q4(committed / volume) if volume > 0 else util.q4(0)
    commitment["_coverage_pct"] = coverage
    commitment["risk_flag"] = risk_flag(commitment, coverage)
    return commitment


def risk_flag(commitment, coverage):
    threshold = util.add_days(commitment["_window_end_date"], -config.RISK_LEAD_DAYS)
    if db.clock_date() > threshold and coverage < config.FILL_TARGET_PCT:
        return "AT_RISK"
    return "ON_TRACK"


def price_shipped_lines(commitment, lines):
    revenue = 0
    for line in lines:
        lot = db.fruit_lots.get(line["fruit_lot_id"])
        verified = 0
        if lot is not None and lot.get("verified_shelf_life_days") is not None:
            verified = int(lot["verified_shelf_life_days"])
        shortfall = max(0, int(commitment["shelf_life_guarantee_days"]) - verified)
        discount_pct = min(
            config.SHELF_LIFE_DISCOUNT_CAP_PCT,
            util.dec(shortfall) * config.SHELF_LIFE_DISCOUNT_PER_DAY,
        )
        gross = util.q0(
            util.dec(line["allocated_lbs"]) * util.dec(commitment["price_cents_per_lb"])
        )
        discount = util.q0(util.dec(gross) * discount_pct)
        net = gross - discount
        line["shelf_life_shortfall_days"] = shortfall
        line["line_gross_cents"] = gross
        line["line_discount_cents"] = discount
        line["line_net_cents"] = net
        revenue += net
    return revenue


def shortfall_penalty(commitment, shipped_lbs):
    volume = util.dec(commitment["volume_commitment_lbs"])
    return util.q0(
        (volume - util.dec(shipped_lbs))
        * util.dec(commitment["price_cents_per_lb"])
        * config.SHORTFALL_PENALTY_RATE
    )


# ---------------------------------------------------------------------------
# 12. crew_wage_ledger
# ---------------------------------------------------------------------------
def accrue(crew, cents):
    crew["accrued_wage_cents"] = int(crew["accrued_wage_cents"]) + int(cents)


def reverse_accrual(crew, cents):
    crew["accrued_wage_cents"] = int(crew["accrued_wage_cents"]) - int(cents)


# ---------------------------------------------------------------------------
# 13. block_traceability_summary
# ---------------------------------------------------------------------------
def traceability_summary(block):
    lots = sorted(
        db.lots_of_block(block["id"]),
        key=lambda l: (l["_pick_date"], l["created_at"], l["_seq"]),
    )
    total = util.ZERO
    shipped = util.ZERO
    held = 0
    rejected = 0
    dates = []
    for lot in lots:
        total += util.dec(lot["net_packed_lbs"])
        if lot["disposition_status"] == "DELIVERED":
            shipped += util.dec(lot["net_packed_lbs"])
        if lot["food_safety_hold"]:
            held += 1
        if lot["disposition_status"] == "REJECTED":
            rejected += 1
        dates.append(lot["pick_date"])
    return {
        "block_id": block["id"],
        "block_name": block["name"],
        "variety": block["variety"],
        "water_status": block["water_status"],
        "food_safety_posture": block["food_safety_posture"],
        "lot_count": len(lots),
        "pick_date_count": len(set(dates)),
        "total_packed_lbs": util.q2(total),
        "shipped_lbs": util.q2(shipped),
        "held_lot_count": held,
        "rejected_lot_count": rejected,
        "earliest_pick_date": lots[0]["pick_date"] if lots else None,
        "latest_pick_date": lots[-1]["pick_date"] if lots else None,
    }
