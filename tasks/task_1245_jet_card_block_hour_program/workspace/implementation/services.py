"""Business logic: lifecycle helpers, calculations, cascades, sweeps.

Implements SCAFFOLD.yaml section 1.3 (calculations) and the state-machine
side effects from section 1.2, with PRD.md prose as the tie-breaker.
"""

from decimal import Decimal

from store import db
from util import (
    D, add_months, category_rank, distance_nm, fmt_ts, new_uuid,
    round_hours, round_money,
)


# ---------------------------------------------------------------------------
# Generic resource helpers
# ---------------------------------------------------------------------------

def touch(resource):
    """Mutation bookkeeping: refresh updated_at and increment version by 1."""
    resource["updated_at"] = db.now()
    resource["version"] += 1


def new_common():
    ts = db.now()
    return {
        "id": new_uuid(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def insert_ledger_entry(card_id, entry_kind, hours_delta, trip_id=None, note=None,
                        effective_at=None):
    entry = {
        "id": new_uuid(),
        "created_at": db.now(),
        "_seq": db.next_seq(),
        "card_id": card_id,
        "entry_kind": entry_kind,
        "hours_delta": round_hours(hours_delta),
        "effective_at": effective_at if effective_at is not None else db.now(),
        "trip_id": trip_id,
        "note": note,
    }
    db.ledger[entry["id"]] = entry
    return entry


def card_ledger_entries(card_id):
    return [e for e in db.ledger.values() if e["card_id"] == card_id]


def chrono_hours_remaining(card):
    """Chronological variant: sum of deltas with effective_at <= now."""
    now = db.now()
    total = Decimal("0")
    for e in card_ledger_entries(card["id"]):
        if e["effective_at"] <= now:
            total += e["hours_delta"]
    return round_hours(total)


def forward_hours_remaining(card):
    """Forward-looking variant: entries with effective_at <= min(now, expires_at)."""
    now = db.now()
    cap = now
    if card.get("expires_at") is not None and card["expires_at"] < cap:
        cap = card["expires_at"]
    total = Decimal("0")
    for e in card_ledger_entries(card["id"]):
        if e["effective_at"] <= cap:
            total += e["hours_delta"]
    return round_hours(total)


def card_trips(card_id):
    return [t for t in db.trips.values() if t["card_id"] == card_id]


def trip_legs(trip_id):
    return sorted(
        (lg for lg in db.legs.values() if lg["trip_id"] == trip_id),
        key=lambda lg: lg["leg_seq"])


def card_escrow(card_id):
    for e in db.escrow_accounts.values():
        if e["card_id"] == card_id:
            return e
    return None


def trip_invoice(trip_id):
    for inv in db.invoices.values():
        if inv["trip_id"] == trip_id:
            return inv
    return None


# ---------------------------------------------------------------------------
# Trip quoting (calc: quoted_hours_estimate)
# ---------------------------------------------------------------------------

def compute_quoted_hours(program, trip_kind, dep_icao, arr_icao):
    dist = distance_nm(dep_icao, arr_icao)
    per_leg = round_hours(D(dist) / D(400) + D(program["taxi_minutes_per_leg"]) / D(60))
    floor_h = round_hours(D(program["min_billable_minutes_per_leg"]) / D(60))
    per_leg = max(per_leg, floor_h)
    if trip_kind == "ROUND_TRIP":
        return round_hours(per_leg * 2)
    return per_leg


def is_peak_departure(program_id, departure_dt):
    for w in db.peak_windows.values():
        if w["program_id"] != program_id:
            continue
        if w["window_start_utc"] <= departure_dt < w["window_end_utc"]:
            return True
    return False


def blackout_intersects(program_id, category, departure_dt):
    for w in db.blackout_windows.values():
        if w["program_id"] != program_id:
            continue
        if w["applies_to_category"] != category:
            continue
        if w["window_start_utc"] <= departure_dt < w["window_end_utc"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Card lifecycle
# ---------------------------------------------------------------------------

def activate_card(card, program):
    now = db.now()
    card["card_status"] = "ACTIVE"
    card["purchased_at"] = now
    card["expires_at"] = add_months(now, program["expiry_months"])
    card["hours_remaining"] = D(card["hours_total"])
    card["hours_consumed"] = Decimal("0")
    card["hours_expired"] = Decimal("0")
    card["peak_hours_used"] = Decimal("0")
    insert_ledger_entry(card["id"], "PURCHASE_GRANT", D(card["hours_total"]))
    escrow = new_common()
    escrow.update({
        "card_id": card["id"],
        "principal_cents": program["purchase_price_cents"],
        "available_cents": program["purchase_price_cents"],
        "released_cents": 0,
        "forfeited_cents": 0,
    })
    db.escrow_accounts[escrow["id"]] = escrow
    card["escrow_balance_cents"] = escrow["available_cents"]
    touch(card)


# ---------------------------------------------------------------------------
# Dispatch / completion
# ---------------------------------------------------------------------------

def leg_swap_multiplier(program, trip, dispatched_category):
    requested = trip["requested_category"]
    if dispatched_category == requested:
        return Decimal("1.0")
    if category_rank(dispatched_category) < category_rank(requested):
        return D(program["swap_ratio_to_lower"])
    return D(program["swap_ratio_to_higher"])


def create_trip_legs(trip):
    """One leg for ONE_WAY, two legs for ROUND_TRIP, all PLANNED."""
    legs = []
    leg1 = new_common()
    leg1.update({
        "trip_id": trip["id"],
        "leg_seq": 1,
        "departure_icao": trip["departure_icao"],
        "arrival_icao": trip["arrival_icao"],
        "scheduled_departure_utc": trip["requested_departure_utc"],
        "actual_block_minutes": None,
        "billable_minutes": None,
        "billable_hours": None,
        "swap_multiplier": None,
        "debited_hours": None,
        "leg_status": "PLANNED",
    })
    db.legs[leg1["id"]] = leg1
    legs.append(leg1)
    if trip["trip_kind"] == "ROUND_TRIP":
        leg2 = new_common()
        leg2.update({
            "trip_id": trip["id"],
            "leg_seq": 2,
            "departure_icao": trip["arrival_icao"],
            "arrival_icao": trip["departure_icao"],
            "scheduled_departure_utc": trip["requested_return_utc"],
            "actual_block_minutes": None,
            "billable_minutes": None,
            "billable_hours": None,
            "swap_multiplier": None,
            "debited_hours": None,
            "leg_status": "PLANNED",
        })
        db.legs[leg2["id"]] = leg2
        legs.append(leg2)
    return legs


def compute_leg_billing(program, trip, leg, dispatched_category):
    """calc billable_hours_per_leg + debited_hours_per_leg."""
    raw_minutes = leg["actual_block_minutes"] + program["taxi_minutes_per_leg"]
    billable_minutes = max(raw_minutes, program["min_billable_minutes_per_leg"])
    billable_hours = round_hours(D(billable_minutes) / D(60))
    swap_multiplier = leg_swap_multiplier(program, trip, dispatched_category)
    debited_hours = round_hours(billable_hours * swap_multiplier)
    leg["billable_minutes"] = billable_minutes
    leg["billable_hours"] = billable_hours
    leg["swap_multiplier"] = swap_multiplier
    leg["debited_hours"] = debited_hours
    return debited_hours


def create_invoice(program, trip, final_hours):
    """calc invoice_total: subtotal, peak surcharge, round-trip discount."""
    implied_rate = D(program["purchase_price_cents"]) / D(program["hours_purchased"])
    subtotal = round_money(final_hours * implied_rate)
    if trip["is_peak_period"]:
        surcharge = round_money(D(subtotal) * D(program["peak_surcharge_pct"]))
    else:
        surcharge = 0
    if trip["trip_kind"] == "ROUND_TRIP":
        discount = round_money(
            D(subtotal + surcharge) * D(program["round_trip_discount_pct"]))
    else:
        discount = 0
    total = subtotal + surcharge - discount

    inv = new_common()
    inv.update({
        "trip_id": trip["id"],
        "invoice_status": "DRAFT",
        "subtotal_cents": subtotal,
        "peak_surcharge_cents": surcharge,
        "round_trip_discount_cents": discount,
        "total_cents": total,
        "issued_at": None,
    })
    db.invoices[inv["id"]] = inv
    # The completion cascade immediately issues the invoice (DRAFT -> ISSUED).
    inv["invoice_status"] = "ISSUED"
    inv["issued_at"] = db.now()
    touch(inv)
    return inv


def complete_trip(program, trip, card):
    """Run the full completion cascade. Assumes actual_block_minutes are set."""
    aircraft = db.aircraft.get(trip["dispatched_aircraft_id"])
    dispatched_category = aircraft["category"] if aircraft else trip["requested_category"]

    legs = trip_legs(trip["id"])
    final_hours = Decimal("0")
    for leg in legs:
        final_hours += compute_leg_billing(program, trip, leg, dispatched_category)
    final_hours = round_hours(final_hours)
    trip["final_hours"] = final_hours

    # Hour debit
    insert_ledger_entry(card["id"], "TRIP_DEBIT", -final_hours, trip_id=trip["id"])
    card["hours_consumed"] = round_hours(card["hours_consumed"] + final_hours)
    card["hours_remaining"] = round_hours(card["hours_remaining"] - final_hours)
    if trip["is_peak_period"]:
        card["peak_hours_used"] = round_hours(card["peak_hours_used"] + final_hours)

    # Escrow release (calc escrow_release_on_completion)
    escrow = card_escrow(card["id"])
    if escrow is not None:
        release = round_money(
            (final_hours / D(card["hours_total"])) * D(escrow["principal_cents"]))
        escrow["available_cents"] -= release
        escrow["released_cents"] += release
        card["escrow_balance_cents"] = escrow["available_cents"]
        touch(escrow)

    # Cleanup: aircraft back to AVAILABLE, legs FLOWN, invoice issued.
    if aircraft is not None:
        aircraft["aircraft_status"] = "AVAILABLE"
        touch(aircraft)
    for leg in legs:
        leg["leg_status"] = "FLOWN"
        touch(leg)
    create_invoice(program, trip, final_hours)

    trip["trip_status"] = "COMPLETED"
    touch(trip)
    touch(card)


# ---------------------------------------------------------------------------
# Expiration sweep (POST /ops/run)
# ---------------------------------------------------------------------------

def run_expiration_sweep():
    now = db.now()
    expired_ids = []
    closed_ids = []
    for card in sorted(db.cards.values(), key=lambda c: (c["created_at"], c["_seq"])):
        if card["card_status"] != "ACTIVE":
            continue
        if card["expires_at"] is None or now < card["expires_at"]:
            continue
        remaining = card["hours_remaining"]
        if remaining > 0:
            # EXPIRED: expiration debit + escrow forfeiture are inseparable.
            # The debit takes effect at expires_at (the moment hours lapse), so
            # the forward-looking projection forecasts the post-expiry floor.
            insert_ledger_entry(card["id"], "EXPIRATION_DEBIT", -remaining,
                                effective_at=card["expires_at"])
            card["hours_expired"] = round_hours(card["hours_expired"] + remaining)
            card["hours_remaining"] = Decimal("0")
            escrow = card_escrow(card["id"])
            if escrow is not None:
                escrow["forfeited_cents"] += escrow["available_cents"]
                escrow["available_cents"] = 0
                card["escrow_balance_cents"] = 0
                touch(escrow)
            card["card_status"] = "EXPIRED"
            expired_ids.append(card["id"])
        else:
            card["card_status"] = "CLOSED"
            closed_ids.append(card["id"])
        touch(card)
    return expired_ids, closed_ids
