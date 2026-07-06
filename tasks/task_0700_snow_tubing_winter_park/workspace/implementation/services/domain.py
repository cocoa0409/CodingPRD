"""Core domain logic: posture, park-ledger reconciliation, calculations, cascades."""
from decimal import Decimal, ROUND_HALF_UP

from services.common import touch

# ---------------------------------------------------------------------------
# Calculation constants
# ---------------------------------------------------------------------------
CHILD_CENTS = 1500
JUNIOR_CENTS = 2500
ADULT_CENTS = 3500
SENIOR_CENTS = 2000
SILVER_DISCOUNT = Decimal("0.10")
GOLD_DISCOUNT = Decimal("0.25")
RESIDENT_GOLD_DISCOUNT = Decimal("0.40")
RESIDENT_DISCOUNT = Decimal("0.05")

TIER1_PER_HEAD_CENTS = 3000
TIER2_PER_HEAD_CENTS = 2600
TIER3_PER_HEAD_CENTS = 2200
EXCLUSIVE_LANE_FLAT_CENTS = 20000
MIN_SHARED_DEPOSIT_CENTS = 8000

ADDON_FOOD_PASS_DISCOUNT = Decimal("0.15")
ADDON_RESIDENT_DRINK_DISCOUNT = Decimal("0.10")

MIN_TUBE_HEIGHT_CM = 92

PASS_DAILY_ALLOWANCE = {"SILVER": 2, "GOLD": 4, "RESIDENT_GOLD": 6}


def round_half_up(value):
    """Round a Decimal to whole cents, rounding halves up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Posture
# ---------------------------------------------------------------------------
def derive_posture(park, snow_depth_cm, wind_kph):
    """A single reading's implied posture per PRD §2.6 (evaluated in order)."""
    if snow_depth_cm < park["min_snow_depth_cm"]:
        return "CLOSED"
    if wind_kph >= park["max_safe_wind_kph"] and snow_depth_cm >= park["min_snow_depth_cm"]:
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# Park ledger reconciliation
# ---------------------------------------------------------------------------
def lanes_of_park(store, park_id):
    return [l for l in store.lanes.values() if l["park_id"] == park_id]


def open_lane_capacity_sum(store, park_id):
    return sum(
        l["rider_capacity_per_block"]
        for l in store.lanes.values()
        if l["park_id"] == park_id and l["status"] == "OPEN"
    )


def active_block_committed(store, park_id):
    """Riders committed for the active block (the block whose status == ACTIVE).

    total_capacity_remaining = sum(open lane caps) - committed riders for the active block.
    Use the ACTIVE block's committed_rider_count; if multiple ACTIVE blocks exist, sum them.
    """
    total = 0
    for tb in store.time_blocks.values():
        if tb["park_id"] == park_id and tb["status"] == "ACTIVE":
            total += tb["committed_rider_count"]
    return total


def reconcile_park(store, park):
    """Recompute open_lane_count and total_capacity_remaining; bump version if changed.

    Returns True if any derived field actually changed."""
    pid = park["id"]
    new_open = sum(1 for l in store.lanes.values() if l["park_id"] == pid and l["status"] == "OPEN")
    cap_sum = open_lane_capacity_sum(store, pid)
    committed = active_block_committed(store, pid)
    new_remaining = cap_sum - committed
    changed = (
        park["open_lane_count"] != new_open
        or park["total_capacity_remaining"] != new_remaining
    )
    park["open_lane_count"] = new_open
    park["total_capacity_remaining"] = new_remaining
    if changed:
        touch(store, park)
    return changed


def recompute_park_remaining(store, park):
    """Recompute only total_capacity_remaining (ledger sync after commit/release).
    Counts as a mutation if it changes the value."""
    pid = park["id"]
    cap_sum = open_lane_capacity_sum(store, pid)
    committed = active_block_committed(store, pid)
    new_remaining = cap_sum - committed
    if park["total_capacity_remaining"] != new_remaining:
        park["total_capacity_remaining"] = new_remaining
        touch(store, park)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_is_resident(park, patron):
    prefixes = park.get("resident_zip_prefixes") or []
    zip_code = patron.get("zip_code") or ""
    for p in prefixes:
        if isinstance(p, str) and zip_code.startswith(p):
            return True
    return False


def compute_ticket_price(rider_age_years, is_resident, season_pass):
    # (1) base by age tier
    if rider_age_years < 6:
        base = CHILD_CENTS
    elif rider_age_years < 13:
        base = JUNIOR_CENTS
    elif rider_age_years >= 65:
        base = SENIOR_CENTS
    else:
        base = ADULT_CENTS

    discount_factor = Decimal("1.0")
    pass_tier = season_pass["tier"] if season_pass else None
    # (2) pass discount
    if season_pass is not None:
        if pass_tier == "SILVER":
            discount_factor *= (Decimal("1") - SILVER_DISCOUNT)
        elif pass_tier == "GOLD":
            discount_factor *= (Decimal("1") - GOLD_DISCOUNT)
        elif pass_tier == "RESIDENT_GOLD":
            discount_factor *= (Decimal("1") - RESIDENT_GOLD_DISCOUNT)
    # (3) resident discount (stacks unless tier is RESIDENT_GOLD)
    if is_resident and pass_tier != "RESIDENT_GOLD":
        discount_factor *= (Decimal("1") - RESIDENT_DISCOUNT)
    # (4) single rounding at the end
    return round_half_up(Decimal(base) * discount_factor)


def compute_group_deposit(party_size, rental_type):
    if party_size <= 5:
        per_head = TIER1_PER_HEAD_CENTS
    elif party_size <= 12:
        per_head = TIER2_PER_HEAD_CENTS
    else:
        per_head = TIER3_PER_HEAD_CENTS
    seats_subtotal = per_head * party_size
    if rental_type == "EXCLUSIVE_LANE":
        return seats_subtotal + EXCLUSIVE_LANE_FLAT_CENTS
    return max(seats_subtotal, MIN_SHARED_DEPOSIT_CENTS)


def compute_addon_line_total(store, add_on_category, unit_price_cents, quantity, ticket):
    """Discount per unit, round per unit FIRST, then multiply by quantity."""
    raw_unit = Decimal(unit_price_cents)
    holder_pass = _active_pass_for_ticket_holder(store, ticket)
    if (
        holder_pass is not None
        and holder_pass["tier"] in ("GOLD", "RESIDENT_GOLD")
        and add_on_category == "FOOD"
    ):
        discounted_unit = raw_unit * (Decimal("1") - ADDON_FOOD_PASS_DISCOUNT)
    elif ticket.get("is_resident") and add_on_category == "HOT_DRINK":
        discounted_unit = raw_unit * (Decimal("1") - ADDON_RESIDENT_DRINK_DISCOUNT)
    else:
        discounted_unit = raw_unit
    unit_rounded = round_half_up(discounted_unit)
    return unit_rounded * quantity


def _active_pass_for_ticket_holder(store, ticket):
    """Find an ACTIVE season pass held by the ticket's holder (for add-on food discount).

    PRD §3.8: 'the linked ticket's holder has an ACTIVE GOLD or RESIDENT_GOLD season pass'.
    """
    holder = ticket.get("holder_patron_id")
    best = None
    for sp in store.season_passes.values():
        if sp["holder_patron_id"] == holder and sp["status"] == "ACTIVE":
            if sp["tier"] in ("GOLD", "RESIDENT_GOLD"):
                # Prefer one tied to this ticket's park if available; any active works.
                if best is None:
                    best = sp
    return best


# ---------------------------------------------------------------------------
# Refund entries
# ---------------------------------------------------------------------------
def create_refund_entry(store, ticket_id, group_reservation_id, amount_cents, reason):
    from services.common import make_record
    rec = make_record(store, "RefundEntry", {
        "ticket_id": ticket_id,
        "group_reservation_id": group_reservation_id,
        "amount_cents": amount_cents,
        "reason": reason,
    })
    store.refund_entries[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Ticket lifecycle ledger release (refund/expiry)
# ---------------------------------------------------------------------------
def release_ticket_slot(store, ticket):
    """Decrement the ticket's block committed count and recompute park remaining."""
    tb = store.time_blocks.get(ticket["time_block_id"])
    if tb is not None and tb["committed_rider_count"] > 0:
        tb["committed_rider_count"] -= 1
        touch(store, tb)
    park = store.parks.get(ticket["park_id"])
    if park is not None:
        recompute_park_remaining(store, park)


# ---------------------------------------------------------------------------
# Closure cascades
# ---------------------------------------------------------------------------
def expire_confirmed_tickets_on_lane(store, lane, weather):
    """Force every CONFIRMED ticket committed to this lane (active/scheduled block) to EXPIRED.

    A ticket is "committed to this lane" if it is CONFIRMED, in this lane's park, and its
    block is ACTIVE or SCHEDULED. Tickets are not pinned to a specific lane in the model;
    closure of a lane affects tickets in the active block of that lane's park.

    On WEATHER closures, write a RefundEntry(WEATHER_CLOSURE) per expired ticket.
    """
    park_id = lane["park_id"]
    for ticket in list(store.tickets.values()):
        if ticket["park_id"] != park_id:
            continue
        if ticket["lifecycle_state"] != "CONFIRMED":
            continue
        tb = store.time_blocks.get(ticket["time_block_id"])
        if tb is None or tb["status"] not in ("ACTIVE", "SCHEDULED"):
            continue
        ticket["lifecycle_state"] = "EXPIRED"
        touch(store, ticket)
        release_ticket_slot(store, ticket)
        if weather:
            create_refund_entry(
                store, ticket["id"], None, ticket["base_price_cents"], "WEATHER_CLOSURE"
            )


def close_lane(store, lane, closure_reason, weather, expire_tickets=True):
    """Set a lane to CLOSED with the given reason, optionally cascading ticket expiry."""
    lane["status"] = "CLOSED"
    lane["closure_reason"] = closure_reason
    touch(store, lane)
    if expire_tickets:
        expire_confirmed_tickets_on_lane(store, lane, weather)


def recompute_posture_after_weather(store, park):
    """Recompute Park.operational_posture from the latest weather reading; cascade on CLOSED.

    Caller is responsible for the +1 version bump on the weather append itself.
    """
    pid = park["id"]
    logs = [w for w in store.weather_logs.values() if w["park_id"] == pid]
    if not logs:
        return
    latest = max(logs, key=lambda w: (w["_observed_dt"], w["_seq"]))
    implied = latest["derived_posture"]
    old = park["operational_posture"]
    park["operational_posture"] = implied

    if implied == "CLOSED":
        # Cascade: every lane in {OPEN, GROOMING} -> CLOSED with WEATHER.
        for lane in list(store.lanes.values()):
            if lane["park_id"] == pid and lane["status"] in ("OPEN", "GROOMING"):
                close_lane(store, lane, "WEATHER", weather=True, expire_tickets=True)
    # Recompute aggregates over the (possibly changed) lane set.
    reconcile_park(store, park)
