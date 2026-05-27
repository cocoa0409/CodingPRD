"""Business-logic services: state transitions, cascades, ledger entries.

The functions here are imported by `app.py` route handlers. They expect all
preconditions to already be checked (the route handler is the one running
the §1.4 validation ladder); their job is to commit side effects atomically
and bump versions / timestamps consistently across the cascade fan-out.
"""
import uuid

from db import store
from calculations import (
    parse_iso_to_dt, no_show_fee_amount, lightning_lane_addon_fee,
)


def gen_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Server logical-clock instant (PRD §2.5). All timestamps trace to this
    so a clock-set advance produces deterministic chronological ordering."""
    return store.current_utc


def common_create(obj: dict, with_version: bool = True) -> dict:
    """Stamp id, created_at, updated_at, version on a fresh resource."""
    if "id" not in obj:
        obj["id"] = gen_id()
    n = now_iso()
    obj["created_at"] = n
    obj["updated_at"] = n
    if with_version:
        obj["version"] = 1
    return obj


def bump_version(obj: dict):
    """Increment version and refresh updated_at — the unified cascade book-
    keeping per PRD §2.6."""
    obj["version"] = int(obj.get("version", 1)) + 1
    obj["updated_at"] = now_iso()


# =============================================================
# Credit ledger helpers
# =============================================================

def append_ledger_entry(*, dining_plan_id: str, reservation_id: str,
                       entry_type: str, credits_delta: int):
    """Append-only CreditLedgerEntry write. PRD §2.4: only id, created_at,
    plus the entity's own posted_at — no updated_at, no version."""
    n = now_iso()
    entry = {
        "id": gen_id(),
        "dining_plan_id": dining_plan_id,
        "reservation_id": reservation_id,
        "entry_type": entry_type,
        "credits_delta": int(credits_delta),
        "posted_at": n,
        "created_at": n,
    }
    store.credit_ledger_entries[entry["id"]] = entry
    return entry


# =============================================================
# Reservation cascades
# =============================================================

def find_allergy_meal_for_reservation(reservation_id: str):
    for m in store.allergy_meals.values():
        if m["reservation_id"] == reservation_id:
            return m
    return None


def find_lightning_lane_addon_for_reservation(reservation_id: str):
    for a in store.lightning_lane_addons.values():
        if a["reservation_id"] == reservation_id:
            return a
    return None


def release_credit_hold(reservation: dict):
    """Release a reservation's held credits back to its plan (CONFIRMED ->
    CANCELLED side effect; also no-show release). Appends RELEASE ledger
    entry. Plan-row version is bumped per §2.6."""
    if int(reservation.get("credits_held", 0)) <= 0:
        return
    plan = store.dining_plans.get(reservation["dining_plan_id"])
    held = int(reservation["credits_held"])
    if plan is not None:
        plan["table_service_credits_held"] = int(plan["table_service_credits_held"]) - held
        bump_version(plan)
    append_ledger_entry(
        dining_plan_id=reservation["dining_plan_id"],
        reservation_id=reservation["id"],
        entry_type="RELEASE",
        credits_delta=-held,
    )
    reservation["credits_held"] = 0


def cascade_cancel_addon_for_reservation(reservation_id: str):
    """When a Reservation is cancelled (direct cancel, park-session cascade,
    or any future revert), any attached LL add-on in REQUESTED or ALLOCATED
    flips to CANCELLED with its own updated_at / version bump."""
    a = find_lightning_lane_addon_for_reservation(reservation_id)
    if a is not None and a["status"] in ("REQUESTED", "ALLOCATED"):
        a["status"] = "CANCELLED"
        bump_version(a)


def cascade_decline_allergy_for_no_show(reservation_id: str):
    """No-show side effect: any AllergyMeal in REQUESTED or ACKNOWLEDGED gets
    DECLINED with declined_reason='RESERVATION_NO_SHOW'."""
    m = find_allergy_meal_for_reservation(reservation_id)
    if m is not None and m["status"] in ("REQUESTED", "ACKNOWLEDGED"):
        m["status"] = "DECLINED"
        m["declined_reason"] = "RESERVATION_NO_SHOW"
        bump_version(m)


# =============================================================
# Reservation transition: CONFIRMED -> NO_SHOW (with full cascade)
# =============================================================

def commit_no_show(reservation: dict):
    """Carry out the full cascade for a CONFIRMED -> NO_SHOW transition.

    Per scaffold §1.2 (Reservation) order:
      1. Guest.no_show_strike_count += 1; suspend if >= 5
      2. Create NoShowFeeAssessment per calculation no_show_fee_amount
      3. Release plan held credits + append RELEASE CreditLedgerEntry
      4. AllergyMeal REQUESTED/ACKNOWLEDGED -> DECLINED w/
         declined_reason='RESERVATION_NO_SHOW'
      5. Reservation.credits_held := 0; no_show_assessed_at := now()
    """
    guest = store.guests.get(reservation["guest_id"])
    restaurant = store.restaurants.get(reservation["restaurant_id"])
    n = now_iso()

    # 1. Guest strike (this transition is counted)
    if guest is not None:
        guest["no_show_strike_count"] = int(guest.get("no_show_strike_count", 0)) + 1
        if guest["no_show_strike_count"] >= 5 and guest.get("status") != "SUSPENDED":
            guest["status"] = "SUSPENDED"
        bump_version(guest)
        strike_after = int(guest["no_show_strike_count"])
    else:
        strike_after = 1

    # 2. Compute and persist NoShowFeeAssessment
    fee = no_show_fee_amount(
        base_fee_cents=int(restaurant["no_show_base_fee_cents"]) if restaurant else 0,
        is_character_dining=bool(restaurant.get("is_character_dining")) if restaurant else False,
        party_size=int(reservation["party_size"]),
        strike_after=strike_after,
    )
    assessment = {
        "id": gen_id(),
        "reservation_id": reservation["id"],
        "guest_id": reservation["guest_id"],
        "base_amount_cents": fee["base_amount_cents"],
        "character_surcharge_cents": fee["character_surcharge_cents"],
        "repeat_offender_multiplier": fee["repeat_offender_multiplier"],
        "total_amount_cents": fee["total_amount_cents"],
        "assessed_at": n,
        "created_at": n,
    }
    store.no_show_fee_assessments[assessment["id"]] = assessment

    # 3. Release plan held credits (no-show releases the hold but does not debit)
    release_credit_hold(reservation)

    # 4. Allergy cascade
    cascade_decline_allergy_for_no_show(reservation["id"])

    # 5. Final reservation bookkeeping
    reservation["credits_held"] = 0
    reservation["no_show_assessed_at"] = n
    reservation["status"] = "NO_SHOW"
    bump_version(reservation)
    return assessment


# =============================================================
# Lightning Lane fee allocation
# =============================================================

def allocate_lightning_lane(addon: dict, reservation: dict, restaurant: dict):
    """Carry out the REQUESTED -> ALLOCATED transition: compute fee_cents,
    stamp allocated_at, set redemption_window_end_utc = slot_end_utc + 60min."""
    addon["fee_cents"] = lightning_lane_addon_fee(
        tier=addon["tier"],
        park_code=restaurant["park_code"],
        is_character_dining=bool(restaurant.get("is_character_dining")),
        party_size=int(reservation["party_size"]),
    )
    n = now_iso()
    addon["allocated_at"] = n
    # redemption_window_end_utc = slot_end_utc + 60 minutes
    slot_end = parse_iso_to_dt(reservation["slot_end_utc"])
    from datetime import timedelta
    end = slot_end + timedelta(minutes=60)
    addon["redemption_window_end_utc"] = end.strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{end.microsecond // 1000:03d}Z"
    addon["status"] = "ALLOCATED"
    bump_version(addon)
