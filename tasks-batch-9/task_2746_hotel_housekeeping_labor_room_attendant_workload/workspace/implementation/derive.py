"""Derived aggregates, calculations and cascades.

PRD 2.9: derived aggregates are RECOMPUTED FROM THEIR DEFINITION on every event
that could move them, never adjusted by an incremental delta.  Each such
recomputation independently mutates the resource it lands on -- updated_at is
refreshed and version is incremented on the roster, the forecast day, the room or
the linen item, exactly as if a client had written to it.
"""

from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from errors import ApiError
from numeric import (
    LINEN_REFRESH_CREDITS,
    RECLEAN_CREDIT_FACTOR,
    RESTRICTED_DUTY_FACTOR,
    ceil_exact,
    dec0,
    dec1,
    dec2,
    dec4,
    round_half_up,
    snap_quarter_credits,
    to_frac,
    trunc_toward_zero,
)
from store import touch
from timeutil import add_days, minutes_between


# ---------------------------------------------------------------------------
# Status sets
# ---------------------------------------------------------------------------

# PRD 2.8: the counted set of a roster.  CANCELLED and DEFERRED are excluded from
# both sums; every other status is counted, including RECLEAN_REQUIRED rows that
# have already been superseded by a re-clean.
COUNTED_STATUSES = ("ASSIGNED", "IN_PROGRESS", "COMPLETED", "INSPECTED_PASS", "RECLEAN_REQUIRED")

# PRD 3.5: the performed set -- the productivity and sampling basis.
PERFORMED_STATUSES = ("COMPLETED", "INSPECTED_PASS", "RECLEAN_REQUIRED")

# PRD 2.10 / 3.4: a non-terminal assignment for the duplicate constraint.
NON_TERMINAL_ASSIGNMENT_STATUSES = ("ASSIGNED", "IN_PROGRESS", "COMPLETED")

ORDINANCE_PROFILES = ("NONE", "SQFT_CAP_2200", "CREDIT_CAP_STRICT")
SERVICE_PROGRAMS = ("DAILY", "EVERY_OTHER_DAY", "OPT_OUT")
OCCUPANCY_STATES = ("VACANT", "STAYOVER", "DUE_OUT", "ARRIVAL")
CLEANLINESS_STATUSES = (
    "CLEAN", "DIRTY", "IN_SERVICE", "INSPECTED_PASS", "RECLEAN_REQUIRED", "OUT_OF_ORDER",
)
ATTENDANT_STATUSES = ("ACTIVE", "ON_LEAVE", "TERMINATED")
SERVICE_TYPES = ("CHECKOUT", "STAYOVER", "DEEP_CLEAN", "LINEN_REFRESH")
LINEN_TYPES = ("SHEET_SET", "TOWEL_SET", "DUVET_COVER")
LOST_FOUND_CATEGORIES = ("HIGH_VALUE", "ID_DOCUMENT", "STANDARD", "PERISHABLE")
PROOF_KINDS = ("PHOTO_ID", "DESCRIPTION_MATCH", "RECEIPT")
ENROLLMENT_PROGRAMS = ("OPT_OUT", "EVERY_OTHER_DAY")

RETENTION_DAYS_BY_CATEGORY = {
    "HIGH_VALUE": 90,
    "ID_DOCUMENT": 60,
    "STANDARD": 30,
    "PERISHABLE": 0,
}

# PRD 3.4 occupancy coherence pairing.
OCCUPANCY_REQUIRED_FOR_SERVICE = {
    "CHECKOUT": "DUE_OUT",
    "STAYOVER": "STAYOVER",
    "DEEP_CLEAN": "VACANT",
}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def _find(collection, entity_id, error_id, label):
    if not isinstance(entity_id, str):
        raise ApiError(error_id, "%s not found." % label)
    row = collection.get(entity_id)
    if row is None:
        raise ApiError(error_id, "%s %s not found." % (label, entity_id))
    return row


def get_property(store, pid):
    return _find(store.properties, pid, "ERR_PROPERTY_NOT_FOUND", "Property")


def get_room_type(store, rid):
    return _find(store.room_types, rid, "ERR_ROOM_TYPE_NOT_FOUND", "Room type")


def get_room(store, rid):
    return _find(store.rooms, rid, "ERR_ROOM_NOT_FOUND", "Room")


def get_attendant(store, aid):
    return _find(store.attendants, aid, "ERR_ATTENDANT_NOT_FOUND", "Attendant")


def get_forecast_day(store, fid):
    return _find(store.forecast_days, fid, "ERR_FORECAST_DAY_NOT_FOUND", "Forecast day")


def get_roster(store, rid):
    return _find(store.rosters, rid, "ERR_ROSTER_NOT_FOUND", "Shift roster")


def get_assignment(store, aid):
    return _find(store.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND", "Room assignment")


def get_inspection(store, iid):
    return _find(store.inspections, iid, "ERR_INSPECTION_NOT_FOUND", "Inspection")


def get_linen_item(store, lid):
    return _find(store.linen_items, lid, "ERR_LINEN_ITEM_NOT_FOUND", "Linen item")


def get_laundry_cycle(store, cid):
    return _find(store.laundry_cycles, cid, "ERR_LAUNDRY_CYCLE_NOT_FOUND", "Laundry cycle")


def get_lost_found_item(store, iid):
    return _find(store.lost_found_items, iid, "ERR_LOST_FOUND_ITEM_NOT_FOUND", "Lost and found item")


def get_enrollment(store, eid):
    return _find(store.enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND", "Service enrollment")


# ---------------------------------------------------------------------------
# Live counts (Property.total_rooms, RoomType.room_count, incentive points)
# ---------------------------------------------------------------------------

def room_types_of_property(store, property_id):
    return [t for t in store.room_types.values() if t["property_id"] == property_id]


def rooms_of_property(store, property_id):
    return [r for r in store.rooms.values() if r["property_id"] == property_id]


def property_total_rooms(store, property_id):
    """PRD 3.1: count of rooms belonging to the property, regardless of their
    cleanliness or occupancy posture."""
    return len(rooms_of_property(store, property_id))


def room_type_room_count(store, room_type_id):
    return sum(1 for r in store.rooms.values() if r["room_type_id"] == room_type_id)


def property_outstanding_incentive_points(store, property_id):
    """PRD 3.1: sum of points_accrued over ACTIVE enrollments whose room belongs
    to the property."""
    total = 0
    for enr in store.enrollments.values():
        if enr["status"] != "ACTIVE":
            continue
        room = store.rooms.get(enr["room_id"])
        if room is not None and room["property_id"] == property_id:
            total += enr["points_accrued"]
    return total


def linen_items_of_property(store, property_id):
    return [li for li in store.linen_items.values() if li["property_id"] == property_id]


def cycles_of_linen_item(store, linen_item_id):
    return [c for c in store.laundry_cycles.values() if c["linen_item_id"] == linen_item_id]


def sheet_set_item(store, property_id):
    for li in linen_items_of_property(store, property_id):
        if li["linen_type"] == "SHEET_SET":
            return li
    return None


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------

def property_of_room(store, room):
    return store.properties[room["property_id"]]


def property_of_roster(store, roster):
    day = store.forecast_days[roster["forecast_day_id"]]
    return store.properties[day["property_id"]]


def forecast_day_of_roster(store, roster):
    return store.forecast_days[roster["forecast_day_id"]]


def attendant_of_roster(store, roster):
    return store.attendants[roster["attendant_id"]]


def property_id_of_roster(store, roster):
    return store.forecast_days[roster["forecast_day_id"]]["property_id"]


def rosters_of_forecast_day(store, forecast_day_id):
    return [r for r in store.rosters.values() if r["forecast_day_id"] == forecast_day_id]


def assignments_of_roster(store, roster_id):
    return [a for a in store.assignments.values() if a["roster_id"] == roster_id]


def assignments_of_room(store, room_id):
    return [a for a in store.assignments.values() if a["room_id"] == room_id]


def inspections_of_assignment(store, assignment_id):
    return [i for i in store.inspections.values() if i["assignment_id"] == assignment_id]


def counted_assignments(store, roster_id):
    """PRD 2.8 counted set."""
    return [a for a in assignments_of_roster(store, roster_id) if a["status"] in COUNTED_STATUSES]


def performed_assignments(store, roster_id):
    """PRD 3.5 performed set."""
    return [a for a in assignments_of_roster(store, roster_id) if a["status"] in PERFORMED_STATUSES]


# ---------------------------------------------------------------------------
# Linen: par level, coverage ratio, shortage ladder (PRD 3.8)
# ---------------------------------------------------------------------------

def par_required_sets(store, property_id):
    """Sum over the property's room types of room_count * linen_sets_per_room,
    counted for every room type regardless of whether it currently has rooms."""
    total = 0
    for rt in room_types_of_property(store, property_id):
        total += room_type_room_count(store, rt["id"]) * rt["linen_sets_per_room"]
    return total


def coverage_ratio_of(on_hand_clean, par):
    if par == 0:
        return None
    return dec4(Fraction(int(on_hand_clean), int(par)))


def shortage_from_ratio(ratio):
    """Four-rung ladder, each comparison inclusive at its floor.  A null ratio --
    a property with no linen requirement at all -- reports OK."""
    if ratio is None:
        return "OK"
    if ratio >= Decimal("1.0000"):
        return "OK"
    if ratio >= Decimal("0.8500"):
        return "WATCH"
    if ratio >= Decimal("0.6000"):
        return "SHORTAGE"
    return "ESCALATED"


def recompute_linen(store, item, bump=True):
    """Recompute par_required_sets, coverage_ratio and shortage_status from their
    definitions.  While ANY laundry cycle of this line sits in LATE_ESCALATED the
    shortage status is forced to ESCALATED whatever coverage_ratio says -- the
    override is sticky and every cycle of the line is consulted regardless of age."""
    par = par_required_sets(store, item["property_id"])
    ratio = coverage_ratio_of(item["on_hand_clean"], par)
    status = shortage_from_ratio(ratio)
    for cycle in cycles_of_linen_item(store, item["id"]):
        if cycle["status"] == "LATE_ESCALATED":
            status = "ESCALATED"
            break
    item["par_required_sets"] = par
    item["coverage_ratio"] = ratio
    item["shortage_status"] = status
    if bump:
        touch(store, item)
    return item


def recompute_all_linen_of_property(store, property_id, bump=True):
    for item in linen_items_of_property(store, property_id):
        recompute_linen(store, item, bump=bump)


def property_has_linen_shortage(store, property_id):
    """PRD 3.4 gate 5: a DEEP_CLEAN may not be created while ANY linen line of the
    property reports SHORTAGE or ESCALATED."""
    for item in linen_items_of_property(store, property_id):
        if item["shortage_status"] in ("SHORTAGE", "ESCALATED"):
            return True
    return False


# ---------------------------------------------------------------------------
# Ordinance ceilings and the compliance dimension (PRD 2.8)
# ---------------------------------------------------------------------------

def effective_credit_cap(prop, attendant):
    """Property.max_daily_credits reduced by the restricted-duty factor -- three
    quarters of the property ceiling for a restricted-duty attendant -- with the
    product rounded half up to two decimals."""
    cap = prop["max_daily_credits"]
    if attendant["restricted_duty"]:
        return dec2(to_frac(cap) * to_frac(RESTRICTED_DUTY_FACTOR))
    return dec2(cap)


def effective_sqft_cap(prop):
    """Only the SQFT_CAP_2200 profile carries a square-foot ceiling; under NONE and
    CREDIT_CAP_STRICT the cap is null and no square-foot ceiling applies at all."""
    if prop["ordinance_profile"] == "SQFT_CAP_2200":
        return prop["max_daily_square_feet"]
    return None


def waiver_headroom_factor(prop):
    if prop["ordinance_profile"] == "CREDIT_CAP_STRICT":
        return Decimal("1.00")
    return Decimal("1.25")


def resolve_compliance_state(roster, credits, square_feet, credit_cap, sqft_cap, ignore_waiver=False):
    """PRD 2.8 resolution rule, evaluated in this fixed order.  Both comparisons
    are exact: equality lands on AT_LIMIT and is a permitted, workable condition;
    only strictly-greater lands on BREACH_BLOCKED."""
    sqft_ok = sqft_cap is None or square_feet <= sqft_cap
    if (
        not ignore_waiver
        and roster["waiver_state"] == "GRANTED"
        and roster["waiver_requested_credits"] is not None
        and credits <= roster["waiver_requested_credits"]
        and sqft_ok
    ):
        return "WAIVER_GRANTED"
    if credits > credit_cap:
        return "BREACH_BLOCKED"
    if sqft_cap is not None and square_feet > sqft_cap:
        return "BREACH_BLOCKED"
    if credits == credit_cap:
        return "AT_LIMIT"
    if sqft_cap is not None and square_feet == sqft_cap:
        return "AT_LIMIT"
    return "COMPLIANT"


# ---------------------------------------------------------------------------
# Inspection sampling obligation (PRD 3.6)
# ---------------------------------------------------------------------------

def sampling_rate(prop, attendant):
    """probation_sample_rate when the attendant's quality_probation flag is true,
    otherwise inspection_sample_rate."""
    if attendant["quality_probation"]:
        return prop["probation_sample_rate"]
    return prop["inspection_sample_rate"]


def required_samples_for(performed_count, rate):
    """Round the exact product UP, raise to at least one, then cap at the performed
    count.  A performed count of zero owes nothing."""
    if performed_count <= 0:
        return 0
    raw = to_frac(performed_count) * to_frac(rate)
    required = ceil_exact(raw)
    if required < 1:
        required = 1
    if required > performed_count:
        required = performed_count
    return required


# ---------------------------------------------------------------------------
# The roster aggregate recomputation (PRD 2.9)
# ---------------------------------------------------------------------------

def roster_inspections_completed(store, roster_id):
    ids = set(a["id"] for a in assignments_of_roster(store, roster_id))
    return sum(1 for i in store.inspections.values() if i["assignment_id"] in ids)


def recompute_roster(store, roster, bump=True):
    """Recompute assigned_credits, assigned_square_feet, the two ordinance ceilings,
    compliance_state, the productivity counters and the sampling obligation, all
    from their definitions.  Returns True when assigned_credits actually moved, which
    is the trigger for the forecast day's conserved total."""
    prop = property_of_roster(store, roster)
    attendant = attendant_of_roster(store, roster)
    counted = counted_assignments(store, roster["id"])

    credit_sum = Fraction(0)
    sqft_sum = 0
    for a in counted:
        credit_sum += to_frac(a["credits"])
        sqft_sum += int(a["square_feet_snapshot"])
    credits = dec2(credit_sum)

    cap = effective_credit_cap(prop, attendant)
    sqft_cap = effective_sqft_cap(prop)

    before = roster.get("assigned_credits")
    roster["assigned_credits"] = credits
    roster["assigned_square_feet"] = sqft_sum
    roster["effective_credit_cap"] = cap
    roster["effective_sqft_cap"] = sqft_cap
    roster["compliance_state"] = resolve_compliance_state(roster, credits, sqft_sum, cap, sqft_cap)

    performed = performed_assignments(store, roster["id"])
    roster["rooms_completed_gross"] = len(performed)
    roster["rooms_credited_net"] = len(set(a["room_id"] for a in performed))
    roster["required_inspection_samples"] = required_samples_for(
        len(performed), sampling_rate(prop, attendant)
    )
    roster["inspections_completed"] = roster_inspections_completed(store, roster["id"])

    if bump:
        touch(store, roster)
    return before is None or credits != before


def recompute_forecast_allocated(store, forecast_day, bump=True):
    """The conserved day quantity: the sum of ShiftRoster.assigned_credits across
    every roster of the day, recomputed rather than incremented."""
    total = Fraction(0)
    for roster in rosters_of_forecast_day(store, forecast_day["id"]):
        total += to_frac(roster["assigned_credits"])
    forecast_day["allocated_credits_total"] = dec2(total)
    if bump:
        touch(store, forecast_day)
    return forecast_day


def cascade_roster(store, roster, bump_roster=True):
    """Recompute the roster and, when its credit total moved, the parent forecast
    day's conserved total."""
    changed = recompute_roster(store, roster, bump=bump_roster)
    if changed:
        day = store.forecast_days.get(roster["forecast_day_id"])
        if day is not None:
            recompute_forecast_allocated(store, day, bump=True)
    return changed


# ---------------------------------------------------------------------------
# Forecast projection and headcount (PRD 3.2)
# ---------------------------------------------------------------------------

def projected_required_credits(store, prop, forecast_day):
    """Variant PROJECTED_INVENTORY_MIX.  Iterate the property's room types in
    ascending code order, round EACH type's raw demand half up to two decimals, and
    only then add the rounded per-type figures, rounding the sum once more."""
    total_rooms = property_total_rooms(store, prop["id"])
    if total_rooms == 0:
        return Decimal("0.00")

    checkout_rooms = forecast_day["forecast_departures"]
    stayover_rooms = forecast_day["forecast_occupied_rooms"] - forecast_day["forecast_arrivals"]
    if stayover_rooms < 0:
        stayover_rooms = 0
    deep_rooms = forecast_day["planned_deep_clean_rooms"]

    running = Decimal("0.00")
    types = sorted(room_types_of_property(store, prop["id"]), key=lambda t: t["code"])
    for rt in types:
        count = room_type_room_count(store, rt["id"])
        if count == 0:
            continue
        share = Fraction(count, total_rooms)
        raw = (
            to_frac(checkout_rooms) * share * to_frac(rt["checkout_credits"])
            + to_frac(stayover_rooms) * share * to_frac(rt["stayover_credits"])
            + to_frac(deep_rooms) * share * to_frac(rt["deep_clean_credits"])
        )
        running += dec2(raw)
    return dec2(running)


def credits_per_shift(prop):
    """standard_shift_minutes less pre_post_shift_minutes, divided by
    credit_minute_value -- an exact rational, never pre-rounded."""
    assignable_minutes = prop["standard_shift_minutes"] - prop["pre_post_shift_minutes"]
    return Fraction(assignable_minutes, prop["credit_minute_value"])


def required_attendant_headcount(prop, projected):
    """Zero when the projection is zero; otherwise the projected credits divided by
    the assignable ceiling and rounded UP, the ceiling applied to the exact quotient."""
    if to_frac(projected) == 0:
        return 0
    per_shift = credits_per_shift(prop)
    assignable = min(per_shift, to_frac(prop["max_daily_credits"]))
    if assignable <= 0:
        return 0
    return ceil_exact(to_frac(projected) / assignable)


def actual_reconciled_credits(store, forecast_day):
    """Variant ACTUAL_RECONCILED: the credits of every assignment on a roster of this
    day whose status is COMPLETED, INSPECTED_PASS or RECLEAN_REQUIRED."""
    total = Fraction(0)
    roster_ids = set(r["id"] for r in rosters_of_forecast_day(store, forecast_day["id"]))
    for a in store.assignments.values():
        if a["roster_id"] in roster_ids and a["status"] in PERFORMED_STATUSES:
            total += to_frac(a["credits"])
    return dec2(total)


def credit_variance_pct(projected, actual):
    """Signed percentage divergence; null when the projection is zero because there
    is no base to divide by."""
    if to_frac(projected) == 0:
        return None
    return dec2((to_frac(actual) - to_frac(projected)) / to_frac(projected) * 100)


# ---------------------------------------------------------------------------
# Assignment credit valuation (PRD 3.4)
# ---------------------------------------------------------------------------

def base_credits_for(room_type, service_type):
    if service_type == "CHECKOUT":
        return to_frac(room_type["checkout_credits"])
    if service_type == "STAYOVER":
        return to_frac(room_type["stayover_credits"])
    if service_type == "DEEP_CLEAN":
        return to_frac(room_type["deep_clean_credits"])
    # LINEN_REFRESH is a flat quarter credit for every room type: a linen-only
    # touch does not scale with the room.
    return to_frac(LINEN_REFRESH_CREDITS)


def programme_factor(room, service_type):
    """One half when the room is on EVERY_OTHER_DAY *and* the service is STAYOVER;
    one otherwise -- CHECKOUT and DEEP_CLEAN work is never discounted."""
    if room["service_program"] == "EVERY_OTHER_DAY" and service_type == "STAYOVER":
        return Fraction(1, 2)
    return Fraction(1)


def reclean_factor(reclean_generation):
    if reclean_generation >= 1:
        return to_frac(RECLEAN_CREDIT_FACTOR)
    return Fraction(1)


def assignment_credit_value(room, room_type, service_type, reclean_generation):
    raw = (
        base_credits_for(room_type, service_type)
        * programme_factor(room, service_type)
        * reclean_factor(reclean_generation)
    )
    return snap_quarter_credits(raw)


# ---------------------------------------------------------------------------
# Cleaning-window rules (PRD 3.5)
# ---------------------------------------------------------------------------

def room_window_overlap(store, assignment, start, end):
    """Room-level exclusivity: half-open intervals, so windows that merely touch at
    an instant do not overlap.  The peer set is the other assignments on the SAME
    room whose status is COMPLETED, INSPECTED_PASS or RECLEAN_REQUIRED."""
    for other in assignments_of_room(store, assignment["room_id"]):
        if other["id"] == assignment["id"]:
            continue
        if other["status"] not in PERFORMED_STATUSES:
            continue
        o_start = other["started_at"]
        o_end = other["completed_at"]
        if o_start is None or o_end is None:
            continue
        if o_start < end and start < o_end:
            return True
    return False


def rest_buffer_violation(store, assignment, start, end, buffer_minutes):
    """Attendant rest buffer: the windows of the other performed assignments on the
    SAME roster are treated as CLOSED intervals and must be separated from the new
    window by at least Property.rest_buffer_minutes on both sides."""
    buffer_delta = timedelta(minutes=int(buffer_minutes))
    for other in assignments_of_roster(store, assignment["roster_id"]):
        if other["id"] == assignment["id"]:
            continue
        if other["status"] not in PERFORMED_STATUSES:
            continue
        o_start = other["started_at"]
        o_end = other["completed_at"]
        if o_start is None or o_end is None:
            continue
        separated = (start - o_end) >= buffer_delta or (o_start - end) >= buffer_delta
        if not separated:
            return True
    return False


# ---------------------------------------------------------------------------
# Inspection scoring and the sample plan (PRD 3.6)
# ---------------------------------------------------------------------------

INSPECTION_WEIGHTS = (
    ("bathroom_points", Fraction(30, 100)),
    ("linen_points", Fraction(25, 100)),
    ("dust_points", Fraction(20, 100)),
    ("amenity_points", Fraction(15, 100)),
    ("floor_points", Fraction(10, 100)),
)


def inspection_score(points, threshold):
    """Weighted roll-up of the five item scores, consulting nothing but this one
    request.  critical_fail is true when either the bathroom or the linen item is 6
    or lower; the pass comparison against the threshold is inclusive."""
    weighted = Fraction(0)
    for field, weight in INSPECTION_WEIGHTS:
        weighted += to_frac(points[field]) * weight
    score_pct = dec1(weighted * 10)
    critical_fail = points["bathroom_points"] <= 6 or points["linen_points"] <= 6
    if critical_fail or score_pct < to_frac(threshold):
        result = "FAIL"
    else:
        result = "PASS"
    return score_pct, critical_fail, result


def inspection_sample_plan(store, roster):
    """The eligible pool is the roster's assignments whose status is exactly
    COMPLETED, ranked by credits descending, then the room's room_number ascending,
    then created_at ascending; the id field is never consulted."""
    prop = property_of_roster(store, roster)
    attendant = attendant_of_roster(store, roster)
    performed = performed_assignments(store, roster["id"])
    rate = sampling_rate(prop, attendant)
    required = required_samples_for(len(performed), rate)
    completed_inspections = roster_inspections_completed(store, roster["id"])
    remaining = required - completed_inspections
    if remaining < 0:
        remaining = 0

    pool = [a for a in assignments_of_roster(store, roster["id"]) if a["status"] == "COMPLETED"]

    def rank_key(a):
        room = store.rooms.get(a["room_id"])
        room_number = room["room_number"] if room is not None else ""
        return (-to_frac(a["credits"]), room_number, a["created_at"], a["_seq"])

    pool.sort(key=rank_key)
    selected = [a["id"] for a in pool[:remaining]]
    return {
        "roster_id": roster["id"],
        "completed_count": len(performed),
        "sample_rate": rate,
        "required_samples": required,
        "inspections_completed": completed_inspections,
        "remaining_samples": remaining,
        "selected_assignment_ids": selected,
    }


# ---------------------------------------------------------------------------
# Shift settlement, productivity and labour cost (PRD 3.7)
# ---------------------------------------------------------------------------

def settle_minutes(prop, worked_minutes, break_minutes):
    """Steps evaluated strictly in order: the guarantee gap, paid minutes, overtime,
    and productive minutes -- which are derived from worked_minutes, NEVER from
    paid_minutes."""
    gap = prop["min_daily_paid_minutes"] - worked_minutes
    if gap < 0:
        gap = 0
    paid_minutes = worked_minutes + gap
    overtime_minutes = paid_minutes - prop["standard_shift_minutes"]
    if overtime_minutes < 0:
        overtime_minutes = 0
    productive_minutes = worked_minutes - break_minutes
    return paid_minutes, overtime_minutes, productive_minutes


def minutes_per_room(productive_minutes, divisor):
    """Each variant is null when its own divisor is zero."""
    if divisor == 0:
        return None
    return dec2(Fraction(int(productive_minutes), int(divisor)))


def target_minutes_per_room(prop, assigned_credits, rooms_credited_net):
    if rooms_credited_net == 0:
        return None
    standard_minutes = to_frac(assigned_credits) * to_frac(prop["credit_minute_value"])
    return dec2(standard_minutes / to_frac(rooms_credited_net))


def resolve_productivity_flag(store, roster, net, target):
    """The quality guardrail OUTRANKS the minutes comparison."""
    for a in assignments_of_roster(store, roster["id"]):
        if a["status"] != "CANCELLED" and a["reclean_generation"] >= 1:
            return "QUALITY_HOLD"
    if roster["rooms_credited_net"] == 0:
        return "PENDING"
    if net is None or target is None:
        return "PENDING"
    if to_frac(net) <= to_frac(target):
        return "ON_TARGET"
    return "OVER_TARGET"


def premium_pct_for_base(base_wage_cents):
    """Tier keyed on base_wage_cents and never on the total that already contains the
    premium.  The boundaries are exact integer comparisons."""
    if base_wage_cents < 20000:
        return Fraction(0)
    if base_wage_cents < 30000:
        return Fraction(4, 100)
    return Fraction(7, 100)


def labor_cost(paid_minutes, hourly_rate_cents, overtime_minutes, compliance_state):
    base_wage_cents = dec0(Fraction(int(paid_minutes) * int(hourly_rate_cents), 60))
    if overtime_minutes > 0 or compliance_state == "WAIVER_GRANTED":
        pct = premium_pct_for_base(base_wage_cents)
        premium = dec0(to_frac(base_wage_cents) * pct)
    else:
        premium = 0
    return base_wage_cents, premium, base_wage_cents + premium


# ---------------------------------------------------------------------------
# Lost and found retention, laundry turnaround (PRD 3.8 / 3.9)
# ---------------------------------------------------------------------------

def retention_window(category, stored_at):
    days = RETENTION_DAYS_BY_CATEGORY[category]
    return days, add_days(stored_at, days)


def laundry_turnaround(dispatched_at, returned_at, sla_minutes):
    minutes = trunc_toward_zero(minutes_between(dispatched_at, returned_at))
    return minutes, minutes > sla_minutes


def skip_budget(program, nights):
    """The budget equals nights under OPT_OUT, and ceil(nights / 2) under
    EVERY_OTHER_DAY -- an alternating-day guest cannot skip every night."""
    if program == "OPT_OUT":
        return nights
    return ceil_exact(Fraction(nights, 2))


POINTS_PER_SKIP = {"OPT_OUT": 500, "EVERY_OTHER_DAY": 250}
