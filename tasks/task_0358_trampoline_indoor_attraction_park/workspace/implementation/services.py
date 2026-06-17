"""Domain services: seat accounting, pricing, membership tiers, time gates.

Every rule here traces to PRD §3 and the SCAFFOLD §1.3 calculation table.
"""
from datetime import timedelta

from common import round_half_up, touch
from db import db
from errors import err

# Catalogue constants (SCAFFOLD §1.3)
ADDON_PRICES = {
    "ARM_SLEEVES": 800,
    "LOCKER": 500,
    "FAST_PASS": 1500,
    "PHOTO_PKG": 2500,
}

TIER_TABLE = {
    "BRONZE": {"monthly_fee_cents": 2900, "discount_pct": 0.10, "included_visits": 2},
    "SILVER": {"monthly_fee_cents": 4900, "discount_pct": 0.15, "included_visits": 4},
    "GOLD": {"monthly_fee_cents": 7900, "discount_pct": 0.25, "included_visits": 8},
}

WAIVER_VALIDITY_DAYS = 365
CHECKIN_LEAD_MINUTES = 30


# ---------------------------------------------------------------------------
# Park clock
# ---------------------------------------------------------------------------
def park_clock(park):
    """The park's current logical clock (PRD §2.9). Falls back to created time."""
    return park["_clock_dt"]


# ---------------------------------------------------------------------------
# Slot seat accounting (SCAFFOLD §1.3 slot_seat_accounting, PRD §3.2)
# ---------------------------------------------------------------------------
def recompute_slot(slot):
    """Recompute seats_taken and derived status from current facts (closed wins)."""
    seats = 0
    for jp in db.jump_passes.values():
        if jp["slot_id"] == slot["id"] and jp["admission_status"] in ("RESERVED", "CHECKED_IN"):
            seats += 1
    for pb in db.party_bookings.values():
        if pb["slot_id"] == slot["id"] and pb["booking_status"] in (
            "DEPOSIT_HELD",
            "CONFIRMED",
            "CHECKED_IN",
        ):
            seats += pb["guest_count"]
    slot["seats_taken"] = seats
    if slot["closed"]:
        slot["status"] = "CLOSED"
    elif seats >= slot["jump_capacity"]:
        slot["status"] = "FULL"
    else:
        slot["status"] = "OPEN"


def bump_slot_version(slot):
    """A seat consume/release mutates the slot: touch + version increment."""
    touch(slot)


# ---------------------------------------------------------------------------
# Membership helpers (PRD §3.7, SCAFFOLD §1.3 membership_pricing)
# ---------------------------------------------------------------------------
def membership_for(member_id):
    """Most recent (highest created) membership for a member id, or None."""
    found = [m for m in db.memberships.values() if m["member_id"] == member_id]
    if not found:
        return None
    found.sort(key=lambda m: (m["_created_dt"], m["id"]))
    return found[-1]


# ---------------------------------------------------------------------------
# Pass pricing (PRD §3.5, SCAFFOLD §1.3 pass_pricing)
# ---------------------------------------------------------------------------
def compute_pass_price(park, slot, channel, sock_count, membership):
    """Return (base_charge_cents, consumes_inclusion) under the pinned order."""
    socks_subtotal = park["grip_sock_price_cents"] * sock_count
    surcharge = park["walkin_surcharge_cents"] if channel == "WALKIN" else 0
    discountable = slot["base_price_cents"] + surcharge

    if membership and membership["status"] == "ACTIVE" and membership["included_visits_remaining"] > 0:
        # inclusion path: base+surcharge waived, only socks billed
        return socks_subtotal, True
    if membership and membership["status"] == "ACTIVE":
        # discount path: % off discountable, socks at full
        pct = TIER_TABLE[membership["tier"]]["discount_pct"]
        discount = round_half_up(discountable * pct)
        return (discountable - discount) + socks_subtotal, False
    return discountable + socks_subtotal, False


# ---------------------------------------------------------------------------
# Add-on totals
# ---------------------------------------------------------------------------
def addon_total_for_pass(pass_id):
    return sum(
        a["line_total_cents"] for a in db.add_ons.values() if a["jump_pass_id"] == pass_id
    )


# ---------------------------------------------------------------------------
# Cancellation refund (PRD §3.6, SCAFFOLD §1.3 cancellation_refund)
# ---------------------------------------------------------------------------
def apply_cancellation_refund(park, slot, jp):
    """Mutate jp's payment fields per the refund tier. Caller has confirmed PAID."""
    clock = park_clock(park)
    delta = slot["_starts_dt"] - clock
    minutes_before = int(delta.total_seconds() // 60)
    socks_and_addons = (
        park["grip_sock_price_cents"] * jp["sock_count"] + addon_total_for_pass(jp["id"])
    )
    if minutes_before >= park["cancellation_cutoff_minutes"]:
        refund = jp["amount_paid_cents"]
        new_status = "REFUNDED"
    else:
        refund = min(jp["amount_paid_cents"], socks_and_addons)
        new_status = "PARTIALLY_REFUNDED" if refund < jp["amount_paid_cents"] else "REFUNDED"
    jp["amount_refunded_cents"] += refund
    jp["amount_paid_cents"] -= refund
    jp["payment_status"] = new_status


# ---------------------------------------------------------------------------
# Party pricing (PRD §3.8, SCAFFOLD §1.3 party_pricing)
# ---------------------------------------------------------------------------
def compute_party_total(package, guest_count, membership):
    per_guest_subtotal = package["per_guest_cents"] * guest_count
    if membership and membership["status"] == "ACTIVE":
        pct = TIER_TABLE[membership["tier"]]["discount_pct"]
        guest_discount = round_half_up(per_guest_subtotal * pct)
        per_guest_subtotal = per_guest_subtotal - guest_discount
    return package["base_room_fee_cents"] + per_guest_subtotal


# ---------------------------------------------------------------------------
# Waiver validity (PRD §3.4, SCAFFOLD §1.3 waiver_expiry)
# ---------------------------------------------------------------------------
def waiver_valid(park, waiver):
    if waiver["status"] != "SIGNED":
        return False
    return park_clock(park) < waiver["_expires_dt"]


def covering_waiver_exists(park, participant):
    """A valid waiver covering the participant; for a minor it must be signed by
    the participant's guardian (PRD §3.4)."""
    for w in db.waivers.values():
        if w["participant_id"] != participant["id"]:
            continue
        if not waiver_valid(park, w):
            continue
        if participant["is_minor"]:
            if w["signed_by_participant_id"] == participant["guardian_participant_id"]:
                return True
        else:
            return True
    return False


# ---------------------------------------------------------------------------
# Check-in window (PRD §3.6)
# ---------------------------------------------------------------------------
def within_checkin_window(park, slot):
    clock = park_clock(park)
    start = slot["_starts_dt"] - timedelta(minutes=CHECKIN_LEAD_MINUTES)
    end = slot["_ends_dt"]
    return start <= clock < end


# ---------------------------------------------------------------------------
# Existence lookups (left-to-right, ERR_NOT_FOUND, PRD §2.5)
# ---------------------------------------------------------------------------
def get_or_404(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist.")
    return rec
