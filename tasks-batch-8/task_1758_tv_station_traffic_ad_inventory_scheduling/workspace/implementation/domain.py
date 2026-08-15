"""Business logic: state machines, calculations, and cascades.

Every rule below traces to SCAFFOLD §1.2/§1.3 and PRD §3; where the two
disagree, the PRD prose wins.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from helpers import created_key, fail, new_record, touch
from store import db

# ---------------------------------------------------------------------------
# Enum domains (SCAFFOLD §1.1)
# ---------------------------------------------------------------------------

PRODUCT_CATEGORIES = {
    "AUTOMOTIVE", "RETAIL", "RESTAURANT", "PHARMA", "FINANCE", "POLITICAL", "OTHER",
}
DAYPART_CODES = {
    "EARLY_MORNING", "DAYTIME", "EARLY_NEWS", "PRIME", "LATE_NEWS",
    "LATE_FRINGE", "OVERNIGHT",
}
SPOT_LENGTHS = {15, 30, 60, 120}
PREEMPT_REASONS = {"POLITICAL_PRIORITY", "OVERSOLD", "NEWS_OVERRIDE"}

# Calculation constants (SCAFFOLD §1.3)
MIN_SEPARATION_POSITIONS = 1
LATE_PENALTY_PCT = Decimal("0.25")
EARLY_PENALTY_PCT = Decimal("0.0")
SPOT_WEIGHT = 1000


# ---------------------------------------------------------------------------
# Graph lookups
# ---------------------------------------------------------------------------

def lines_of_order(order_id):
    return [l for l in db.order_lines.values() if l["order_id"] == order_id]


def spots_of_line(line_id):
    return [s for s in db.spots.values() if s["order_line_id"] == line_id]


def spots_of_order(order_id):
    line_ids = {l["id"] for l in lines_of_order(order_id)}
    return [s for s in db.spots.values() if s["order_line_id"] in line_ids]


def line_of_spot(spot):
    return db.order_lines[spot["order_line_id"]]


def order_of_spot(spot):
    return db.orders[line_of_spot(spot)["order_id"]]


def advertiser_of_spot(spot):
    return db.advertisers[order_of_spot(spot)["advertiser_id"]]


def active_lines(order):
    return [l for l in lines_of_order(order["id"]) if l["status"] == "ACTIVE"]


def recompute_budget(order):
    """gross_budget_cents = sum over non-cancelled lines of
    gross_rate_cents * spots_per_week * weeks_requested (PRD §3.4)."""
    order["gross_budget_cents"] = sum(
        l["gross_rate_cents"] * l["spots_per_week"] * l["weeks_requested"]
        for l in lines_of_order(order["id"])
        if l["status"] != "CANCELLED"
    )


def week_span(week):
    start = date.fromisoformat(week["week_start_date"])
    return start, start + timedelta(days=6)


def date_in_week(week, date_str):
    start, end = week_span(week)
    d = date.fromisoformat(date_str)
    return start <= d <= end


def covering_log_finalized(date_str):
    """True when a FINALIZED or RECONCILED LogDay covers this air date."""
    return any(
        ld["log_date"] == date_str and ld["status"] in ("FINALIZED", "RECONCILED")
        for ld in db.log_days.values()
    )


def spot_class_for_advertiser(advertiser):
    """Fixed at spot creation: POLITICAL when the advertiser's product
    category is POLITICAL, else COMMERCIAL (PRD §3.4)."""
    return "POLITICAL" if advertiser["product_category"] == "POLITICAL" else "COMMERCIAL"


def bucket_for(spot):
    return (
        "booked_political_seconds"
        if spot["spot_class"] == "POLITICAL"
        else "booked_commercial_seconds"
    )


# ---------------------------------------------------------------------------
# Order pipeline (PRD §3.4, SCAFFOLD §1.2 Order machine)
# ---------------------------------------------------------------------------

def spawn_spots(order):
    """Approval side effect: weeks_requested * spots_per_week PENDING_PLACEMENT
    spots per ACTIVE line, spot_class fixed from the advertiser category."""
    advertiser = db.advertisers[order["advertiser_id"]]
    spot_class = spot_class_for_advertiser(advertiser)
    for line in active_lines(order):
        for _ in range(line["weeks_requested"] * line["spots_per_week"]):
            spot = new_record()
            spot.update(
                {
                    "order_line_id": line["id"],
                    "avail_unit_id": None,
                    "copy_instruction_id": None,
                    "spot_class": spot_class,
                    "scheduled_air_date": None,
                    "status": "PENDING_PLACEMENT",
                    "preempt_reason": "NONE",
                    "make_good_of_spot_id": None,
                }
            )
            db.spots[spot["id"]] = spot


def cancel_spot_tree(spot):
    """Cancel one spot, releasing held seconds when it is SCHEDULED on a log
    date not covered by a FINALIZED/RECONCILED log day. SCHEDULED spots locked
    into finalized logs are left untouched (PRD §3.4)."""
    if spot["status"] in ("PENDING_PLACEMENT", "PREEMPTED", "MAKE_GOOD_OFFERED"):
        spot["status"] = "CANCELLED"
        touch(spot)
    elif spot["status"] == "SCHEDULED":
        if not covering_log_finalized(spot["scheduled_air_date"]):
            line = line_of_spot(spot)
            unit = db.avail_units[spot["avail_unit_id"]]
            unit[bucket_for(spot)] -= line["spot_length_seconds"]
            touch(unit)
            spot["status"] = "CANCELLED"
            touch(spot)
        # else: locked into a FINALIZED/RECONCILED log — untouched


def teardown_order_spots(order):
    for spot in sorted(spots_of_order(order["id"]), key=created_key):
        cancel_spot_tree(spot)


def order_has_aired_spot(order):
    return any(s["status"] == "AIRED" for s in spots_of_order(order["id"]))


def run_completion_sweep():
    """System sweep (PRD §3.4): APPROVED orders whose flight_end_date is
    strictly before the logical clock date and whose spots are all terminal
    (AIRED or CANCELLED) transition to COMPLETED."""
    clock_date = db.now.date().isoformat()
    for order in sorted(db.orders.values(), key=created_key):
        if order["status"] != "APPROVED":
            continue
        if not order["flight_end_date"] < clock_date:
            continue
        spots = spots_of_order(order["id"])
        if all(s["status"] in ("AIRED", "CANCELLED") for s in spots):
            order["status"] = "COMPLETED"
            touch(order)


# ---------------------------------------------------------------------------
# Credit ledger (discrepancy credits, PRD §3.6/§3.8)
# ---------------------------------------------------------------------------

def post_discrepancy_credit(order_id, spot, penalty_pct):
    """credit_cents = floor(base * (1 + penalty_pct)) — multiply first, floor
    once, no per-step rounding (PRD §2.7/§3.8)."""
    line = line_of_spot(spot)
    base = Decimal(line["gross_rate_cents"])
    credit = int((base * (Decimal(1) + penalty_pct)).to_integral_value(rounding=ROUND_FLOOR))
    db.credit_entries.append(
        {
            "id": db.next_seq(),
            "order_id": order_id,
            "spot_id": spot["id"],
            "credit_cents": credit,
            "penalty_pct": str(penalty_pct),
        }
    )
    return credit


def order_discrepancy_credits(order_id):
    return sum(e["credit_cents"] for e in db.credit_entries if e["order_id"] == order_id)


# ---------------------------------------------------------------------------
# Placement gates (PRD §3.5, SCAFFOLD §1.3 avail_headroom_check /
# commercial_separation_check)
# ---------------------------------------------------------------------------

def headroom_check(spot, unit):
    """Raises ERR_POLITICAL_RESERVE / ERR_AVAIL_OVERFLOW as classified by
    PRD §3.5. Capacity boundaries are inclusive in both branches."""
    line = line_of_spot(spot)
    d = line["spot_length_seconds"]
    if spot["spot_class"] == "POLITICAL":
        # Political spots may use ANY free second (reserved or shared).
        headroom = (
            unit["total_seconds"]
            - unit["booked_political_seconds"]
            - unit["booked_commercial_seconds"]
        )
        if d > headroom:
            fail(
                "ERR_AVAIL_OVERFLOW",
                "avail headroom exceeded: %ss requested, %ss free" % (d, headroom),
            )
    else:
        # COMMERCIAL spots are fenced out of the political reserve; political
        # spill beyond the reserve leaves commercial capacity intact.
        commercial_capacity = unit["total_seconds"] - unit["reserved_political_seconds"]
        if unit["booked_commercial_seconds"] + d > commercial_capacity:
            if unit["booked_commercial_seconds"] + d <= unit["total_seconds"]:
                fail(
                    "ERR_POLITICAL_RESERVE",
                    "commercial placement would consume reserved political seconds",
                )
            fail(
                "ERR_AVAIL_OVERFLOW",
                "avail headroom exceeded: commercial capacity %ss" % commercial_capacity,
            )


def separation_check(spot, unit):
    """Two same-product-category spots may not air adjacently in one break:
    at least MIN_SEPARATION_POSITIONS distinct other spots must stand between
    them. Occupants are the unit's SCHEDULED spots sorted by created_at ASC;
    the candidate is evaluated as if appended at the last position."""
    occupants = sorted(
        (
            s
            for s in db.spots.values()
            if s["avail_unit_id"] == unit["id"] and s["status"] == "SCHEDULED"
        ),
        key=created_key,
    )
    candidate_category = advertiser_of_spot(spot)["product_category"]
    candidate_position = len(occupants) + 1
    for index, occupant in enumerate(occupants, start=1):
        if advertiser_of_spot(occupant)["product_category"] != candidate_category:
            continue
        if abs(index - candidate_position) <= MIN_SEPARATION_POSITIONS:
            fail(
                "ERR_SEPARATION_VIOLATION",
                "same product_category spots would sit within %d positions"
                % MIN_SEPARATION_POSITIONS,
            )


# ---------------------------------------------------------------------------
# Copy rotation (PRD §3.7, SCAFFOLD §1.3 copy_rotation_select)
# ---------------------------------------------------------------------------

def eligible_copy(advertiser_id, length_seconds):
    return [
        c
        for c in db.copy_instructions.values()
        if c["advertiser_id"] == advertiser_id
        and c["status"] == "RECEIVED"
        and c["length_seconds"] == length_seconds
    ]


def times_used(copy_id):
    """Spots of any status whose copy_instruction_id references this copy."""
    return sum(
        1 for s in db.spots.values() if s["copy_instruction_id"] == copy_id
    )


def usage_snapshot():
    """Times-used per copy frozen at the start of a finalize run: the count
    covers only assignments made before the run began, so every spot in one
    run scores candidates against the same history (PRD §3.7)."""
    return {c["id"]: times_used(c["id"]) for c in db.copy_instructions.values()}


def copy_rotation_select(candidates, snapshot):
    """Deterministic weighted round-robin: lowest times_used/rotation_weight
    wins; scores compared exactly as rationals by cross-multiplication; ties
    break to the earliest-created candidate."""
    best = None
    best_used = best_weight = None
    for cand in sorted(candidates, key=created_key):
        used = snapshot[cand["id"]]
        weight = cand["rotation_weight"]
        if best is None or used * best_weight < best_used * weight:
            best, best_used, best_weight = cand, used, weight
    return best


# ---------------------------------------------------------------------------
# Post-buy report (PRD §3.8, SCAFFOLD §1.3 audience_delivery_shortfall /
# post_buy_credit_value)
# ---------------------------------------------------------------------------

def _latest_entry_by_spot():
    latest = {}
    for entry in sorted(db.as_run_entries.values(), key=lambda e: e["_seq"]):
        latest[entry["spot_id"]] = entry
    return latest


def _q3(value):
    """Deficit per spot kept to three decimal places (PRD §2.7)."""
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _line_deficit_strict(line, aired, entries):
    """Per-spot-strict: over-delivery on one spot never offsets another."""
    g = Decimal(str(line["guaranteed_rating"]))
    total = Decimal(0)
    for spot in aired:
        actual = Decimal(str(entries[spot["id"]]["actual_rating"]))
        deficit = g - actual
        if deficit > 0:
            total += _q3(deficit)
    return total


def _line_deficit_week_averaged(line, aired, entries):
    """Week-averaged: ratings averaged across the line's aired spots inside
    ONE AvailWeek before comparing to the guarantee; over-delivery offsets
    within the same week, never across weeks."""
    g = Decimal(str(line["guaranteed_rating"]))
    by_week = {}
    for spot in aired:
        unit = db.avail_units[spot["avail_unit_id"]]
        by_week.setdefault(unit["avail_week_id"], []).append(spot)
    total = Decimal(0)
    for week_id, spots in by_week.items():
        n = len(spots)
        sum_actual = sum(
            (Decimal(str(entries[s["id"]]["actual_rating"])) for s in spots),
            Decimal(0),
        )
        # max(0, g - avg) * n computed exactly as max(0, g*n - sum_actual)
        deficit = g * n - sum_actual
        if deficit > 0:
            total += _q3(deficit)
    return total


def compute_post_buy(order, method_variant):
    """Order-level credit waterfall in pinned order: discrepancy bucket first,
    per-line audience-shortfall bucket second; floor applied per line, never
    on the order total (PRD §3.8)."""
    entries = _latest_entry_by_spot()
    discrepancy = order_discrepancy_credits(order["id"])
    line_reports = []
    shortfall_total = 0
    for line in sorted(lines_of_order(order["id"]), key=created_key):
        g = Decimal(str(line["guaranteed_rating"]))
        aired = sorted(
            (
                s
                for s in spots_of_line(line["id"])
                if s["status"] == "AIRED" and s["id"] in entries
            ),
            key=created_key,
        )
        if g > 0 and aired:
            if method_variant == "week_averaged":
                deficit_total = _line_deficit_week_averaged(line, aired, entries)
            else:
                deficit_total = _line_deficit_strict(line, aired, entries)
        else:
            deficit_total = Decimal(0)
        adu_owed = int(
            (deficit_total * len(aired)).to_integral_value(rounding=ROUND_CEILING)
        )
        if g > 0:
            cpp = Decimal(line["gross_rate_cents"]) / g
            line_shortfall = int(
                (deficit_total * cpp).to_integral_value(rounding=ROUND_FLOOR)
            )
            cpp_cents = float(cpp)
        else:
            line_shortfall = 0
            cpp_cents = None
        shortfall_total += line_shortfall
        actuals = [
            float(Decimal(str(entries[s["id"]]["actual_rating"]))) for s in aired
        ]
        line_reports.append(
            {
                "order_line_id": line["id"],
                "status": line["status"],
                "guaranteed_rating": line["guaranteed_rating"],
                "aired_spot_count": len(aired),
                "average_actual_rating": (
                    round(sum(actuals) / len(actuals), 3) if actuals else None
                ),
                "post_buy_deficit_points": float(deficit_total),
                "adu_owed": adu_owed,
                "cpp_cents": cpp_cents,
                "shortfall_credit_cents": line_shortfall,
            }
        )
    return {
        "order_id": order["id"],
        "method_variant": method_variant,
        "lines": line_reports,
        "discrepancy_credit_cents": discrepancy,
        "shortfall_credit_cents": shortfall_total,
        "order_credit_cents": discrepancy + shortfall_total,
    }
