"""Derived-field reconciliation and shared domain computations (PRD §2.10, §3).

Derived figures (salon active_occupancy_count, member loyalty_balance and
no_show_strikes, queue ticket position, salon license_status) are recomputed
from underlying records rather than stored as independent truth.
"""
import clock
from db import db

# Constants (SCAFFOLD §1.3 / PRD §3).
MAX_RECALLS = 2
SUSPEND_THRESHOLD = 2
BAN_THRESHOLD = 4
POINT_VALUE_CENTS = 5

TIER_DISCOUNT_BPS = {"BRONZE": 500, "SILVER": 1000, "GOLD": 1500}
TIER_CREDITS = {"BRONZE": 4, "SILVER": 8, "GOLD": 12}


# ---------------------------------------------------------------------------
# Salon derived fields
# ---------------------------------------------------------------------------
def compute_license_status(salon):
    """ACTIVE while clock strictly < license_expiry, else LAPSED (PRD §3.1)."""
    return "ACTIVE" if clock.now() < salon["license_expiry"] else "LAPSED"


def compute_active_occupancy(salon_id):
    """Count of chairs in OCCUPIED state right now (PRD §3.1)."""
    return sum(
        1 for c in db.chairs.values()
        if c["salon_id"] == salon_id and c["status"] == "OCCUPIED"
    )


def refresh_salon_derived(salon):
    salon["license_status"] = compute_license_status(salon)
    salon["active_occupancy_count"] = compute_active_occupancy(salon["id"])


# ---------------------------------------------------------------------------
# Member derived fields
# ---------------------------------------------------------------------------
def compute_loyalty_balance(member_id):
    """max(0, sum of signed points across the member's ledger) (PRD §3.1)."""
    total = sum(
        e["points"] for e in db.loyalty_entries.values()
        if e["member_id"] == member_id
    )
    return max(0, total)


def count_no_show_strikes(member_id):
    """Running count of the member's un-expired no-show events (PRD §3.1/§3.7).

    No expiry mechanism is defined, so every recorded NO_SHOW ticket counts.
    """
    return sum(
        1 for t in db.queue_tickets.values()
        if t["member_id"] == member_id and t["status"] == "NO_SHOW"
    )


def refresh_member_derived(member):
    member["loyalty_balance"] = compute_loyalty_balance(member["id"])
    member["no_show_strikes"] = count_no_show_strikes(member["id"])


def escalate_member_standing(member):
    """Re-evaluate standing against the two thresholds (PRD §3.7).

    BANNED is terminal; once banned the member is never un-escalated.
    """
    strikes = count_no_show_strikes(member["id"])
    member["no_show_strikes"] = strikes
    if member["status"] == "BANNED":
        return
    if strikes >= BAN_THRESHOLD:
        member["status"] = "BANNED"
    elif strikes >= SUSPEND_THRESHOLD:
        member["status"] = "SUSPENDED"
    # below SUSPEND_THRESHOLD: standing unchanged (remains ACTIVE).


# ---------------------------------------------------------------------------
# Queue position derivation (PRD §3.3 / SCAFFOLD queue_position)
# ---------------------------------------------------------------------------
def recompute_positions(salon_id):
    """1-based FIFO rank over WAITING tickets, joined_at ASC then created_at ASC.

    Tickets not WAITING get position 0. The ticket id is never used in ordering.
    """
    waiting = [
        t for t in db.queue_tickets.values()
        if t["salon_id"] == salon_id and t["status"] == "WAITING"
    ]
    waiting.sort(key=lambda t: (t["joined_at"], t["created_at"], t["_seq"]))
    for i, t in enumerate(waiting, start=1):
        t["position"] = i
    for t in db.queue_tickets.values():
        if t["salon_id"] == salon_id and t["status"] != "WAITING":
            t["position"] = 0


def refresh_ticket_position(ticket):
    """Recompute this ticket's position from the live WAITING set (PRD §3.3)."""
    recompute_positions(ticket["salon_id"])


def lowest_waiting_ticket(salon_id):
    waiting = [
        t for t in db.queue_tickets.values()
        if t["salon_id"] == salon_id and t["status"] == "WAITING"
    ]
    if not waiting:
        return None
    waiting.sort(key=lambda t: (t["joined_at"], t["created_at"], t["_seq"]))
    return waiting[0]


# ---------------------------------------------------------------------------
# Visit cost calculations (PRD §3.5 / §3.6, SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def active_lines(visit_id):
    return [
        li for li in db.line_items.values()
        if li["service_visit_id"] == visit_id and li["status"] == "ACTIVE"
    ]


def compute_estimate_total(visit):
    """Provisional list-price estimate (PRD §3.5). Plain integer-cent sum."""
    service_item = db.service_menu_items.get(visit["service_menu_item_id"])
    service_part = service_item["base_price_cents"] if service_item else 0
    addon_part = sum(
        li["line_total_cents"] for li in active_lines(visit["id"])
        if li["line_type"] == "ADDON"
    )
    retail_part = sum(
        li["line_total_cents"] for li in active_lines(visit["id"])
        if li["line_type"] == "RETAIL"
    )
    return service_part + addon_part + retail_part


def refresh_estimate(visit):
    visit["estimate_total_cents"] = compute_estimate_total(visit)
