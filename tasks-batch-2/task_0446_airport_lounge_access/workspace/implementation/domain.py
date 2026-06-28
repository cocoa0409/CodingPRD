"""Core domain logic: derived counters, calculations, state transitions, cascades.

All structural names and rules read from SCAFFOLD §1.1-§1.4 and PRD §3.
"""
from decimal import Decimal, ROUND_HALF_UP

import clock
from db import db, touch

# --- Constants (SCAFFOLD §1.3 calculations.constants; PRD §3 narrative) ------
HOLD_TTL_MINUTES = 30
DAY_PASS_TTL_HOURS = 24
NO_SHOW_SUSPEND_THRESHOLD = 3
MEMBER_FEE_DISCOUNT = Decimal("0.90")

CONSUMING_STATUSES = {"CHECKED_IN", "COMPLETED", "NO_SHOW"}

CARD_RANK = {"BASIC": 0, "SILVER": 1, "GOLD": 2}


# =============================================================================
# Rounding (PRD §2.8 / §3.4 — round-half-up, per line)
# =============================================================================
def round_half_up_cents(cents_int, multiplier):
    """Round (cents_int * multiplier) to a whole number of cents, half-up."""
    product = Decimal(cents_int) * multiplier
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# Logical-clock helpers
# =============================================================================
def is_expired(iso_instant):
    """True iff the given ISO instant is at or before the logical clock
    (valid_until <= now means expired)."""
    if iso_instant is None:
        return False
    return clock.parse_iso(iso_instant) <= clock.now()


# =============================================================================
# Lookups
# =============================================================================
def get_plan(plan_id):
    return db.membership_plans.items.get(plan_id)


def get_lounge(lounge_id):
    return db.lounges.items.get(lounge_id)


def get_member(member_id):
    return db.members.items.get(member_id)


def get_card(card_id):
    return db.eligibility_cards.items.get(card_id)


def get_visit(visit_id):
    return db.visits.items.get(visit_id)


def get_day_pass(dp_id):
    return db.day_passes.items.get(dp_id)


def get_settlement(settlement_id):
    return db.settlements.items.get(settlement_id)


def active_card_for_member(member_id):
    for card in db.eligibility_cards.items.values():
        if card["member_id"] == member_id and card.get("active"):
            return card
    return None


# =============================================================================
# Derived-counter recomputation (PRD §2.5, §3.9; SCAFFOLD calc 5 & 6)
# =============================================================================
def recompute_lounge_occupancy(lounge):
    """Recompute current_occupancy & held_occupancy from this lounge's visits,
    then recompute the OPEN/OVERFLOW status line (CLOSED is sticky until reopen).
    Bumps version/updated_at when any of those fields actually change."""
    lid = lounge["id"]
    current = 0
    held = 0
    for v in db.visits.items.values():
        if v["lounge_id"] != lid:
            continue
        if v["status"] == "CHECKED_IN":
            current += v["occupant_count"]
        elif v["status"] == "HELD":
            held += v["occupant_count"]

    changed = (
        lounge["current_occupancy"] != current
        or lounge["held_occupancy"] != held
    )
    lounge["current_occupancy"] = current
    lounge["held_occupancy"] = held

    # Recompute OPEN <-> OVERFLOW status line (CLOSED unaffected here).
    status_changed = _recompute_overflow_status(lounge)
    if changed or status_changed:
        touch(lounge)
    return lounge


def _recompute_overflow_status(lounge):
    """Recompute OPEN/OVERFLOW from the occupancy line. Returns True if status
    flipped. CLOSED is left untouched (only reopen leaves CLOSED)."""
    if lounge["status"] == "CLOSED":
        return False
    line = lounge["current_occupancy"] + lounge["held_occupancy"]
    new_status = "OVERFLOW" if line >= lounge["capacity"] else "OPEN"
    if lounge["status"] != new_status:
        lounge["status"] = new_status
        return True
    return False


def recompute_lounge_settlement_balance(lounge):
    """settlement_balance_cents = sum of PAYABLE settlement amounts (calc 5)."""
    lid = lounge["id"]
    total = 0
    for s in db.settlements.items.values():
        if s["lounge_id"] == lid and s["status"] == "PAYABLE":
            total += s["amount_cents"]
    if lounge["settlement_balance_cents"] != total:
        lounge["settlement_balance_cents"] = total
        touch(lounge)
    else:
        lounge["settlement_balance_cents"] = total
    return lounge


def recompute_member_usage(member):
    """Recompute visits_used, guest_visits_used, no_show_strikes,
    wallet_balance_cents (calc 6 + wallet). Does NOT itself flip standing —
    standing transitions are handled by the no-show cascade explicitly.

    NOTE: recomputation of usage counters is a derived read and does not bump the
    member's version (only explicit transitions reinstate/roll-year do)."""
    mid = member["id"]
    year_start = clock.parse_iso(member["membership_year_start"])

    visits_used = 0
    guest_visits_used = 0
    no_show_strikes = 0
    for v in db.visits.items.values():
        if v["member_id"] != mid:
            continue
        held_at = clock.parse_iso(v["held_at"]) if v.get("held_at") else None
        if held_at is None or held_at < year_start:
            continue
        status = v["status"]
        if status in CONSUMING_STATUSES:
            if v.get("allotment_consumed"):
                visits_used += 1
            guest_visits_used += v.get("guest_allotment_consumed", 0)
        if status == "NO_SHOW" and v.get("entry_mode") != "DAY_PASS":
            no_show_strikes += 1

    member["visits_used"] = visits_used
    member["guest_visits_used"] = guest_visits_used
    member["no_show_strikes"] = no_show_strikes
    member["wallet_balance_cents"] = compute_wallet_balance(mid)
    return member


def compute_wallet_balance(member_id):
    total = 0
    for le in db.ledger_entries.items.values():
        if le["member_id"] == member_id and le["status"] == "POSTED":
            total += le["amount_cents"]
    return total


def recompute_wallet(member):
    member["wallet_balance_cents"] = compute_wallet_balance(member["id"])
    return member


# =============================================================================
# Calc 1: resolve_entry_mode (SCAFFOLD §1.3 calc 1; PRD §3.3)
# =============================================================================
def resolve_entry_mode(member, plan, day_pass_valid):
    """Returns (entry_mode, allotment_consumed)."""
    if day_pass_valid:
        return "DAY_PASS", False
    if plan["included_visits_per_year"] == -1:
        return "ALLOTMENT", True
    if member["visits_used"] < plan["included_visits_per_year"]:
        return "ALLOTMENT", True
    return "OVERAGE", False


# =============================================================================
# Calc 2: resolve_guest_funding (SCAFFOLD §1.3 calc 2; PRD §3.3)
# =============================================================================
def resolve_guest_funding(member, plan, guest_count):
    """Returns (guest_allotment_consumed, funded_by_list) walking guests in
    creation order. Reads the member's PRE-hold guest_visits_used."""
    remaining = max(
        0, plan["included_guest_visits_per_year"] - member["guest_visits_used"]
    )
    guest_allotment_consumed = min(guest_count, remaining)
    funded = []
    for i in range(guest_count):
        if i < guest_allotment_consumed:
            funded.append("GUEST_ALLOTMENT")
        else:
            funded.append("GUEST_CHARGE")
    return guest_allotment_consumed, funded


# =============================================================================
# Calc 3: compute_member_charge (SCAFFOLD §1.3 calc 3; PRD §3.4)
# =============================================================================
def compute_member_charge(visit, plan, lounge, member, day_pass):
    """Computes member_charge_cents with per-line round-half-up, then sums.
    Returns (member_charge_cents, per_guest_charges list aligned to guests)."""
    active_card = active_card_for_member(member["id"]) if member else None
    is_gold = bool(active_card and active_card["card_status"] == "GOLD")
    disc = MEMBER_FEE_DISCOUNT if is_gold else Decimal("1")

    overage_line = 0
    if visit["entry_mode"] == "OVERAGE":
        overage_line = round_half_up_cents(plan["overage_charge_cents"], disc)

    guest_total = 0
    per_guest = []
    guests = guests_of_visit(visit["id"])
    for g in guests:
        if g["funded_by"] == "GUEST_CHARGE":
            base = plan["guest_charge_cents"] + lounge["guest_fee_cents"]
        else:  # GUEST_ALLOTMENT — only the lounge door fee applies
            base = lounge["guest_fee_cents"]
        line = round_half_up_cents(base, disc)
        per_guest.append((g, line))
        guest_total += line

    day_pass_line = 0
    if visit["entry_mode"] == "DAY_PASS" and day_pass is not None:
        day_pass_line = day_pass["price_cents"]

    total = overage_line + guest_total + day_pass_line
    return total, overage_line, per_guest, day_pass_line


def guests_of_visit(visit_id):
    """Guests of a visit in creation order."""
    result = [
        g for g in db.guests.items.values() if g["visit_id"] == visit_id
    ]
    result.sort(key=lambda g: g["_seq"])
    return result


# =============================================================================
# Ledger entry creation
# =============================================================================
def post_ledger_entry(member_id, kind, amount_cents, visit_id=None,
                      day_pass_id=None):
    from db import new_id, make_event_fields
    entry = {
        "id": new_id(),
        "member_id": member_id,
        "visit_id": visit_id,
        "day_pass_id": day_pass_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "status": "POSTED",
    }
    entry.update(make_event_fields())
    entry["_seq"] = db.ledger_entries.next_seq()
    db.ledger_entries.items[entry["id"]] = entry
    return entry


# =============================================================================
# Calc 4: compute_settlement (SCAFFOLD §1.3 calc 4; PRD §3.4)
# =============================================================================
def compute_settlement_amount(visit, lounge):
    return visit["occupant_count"] * lounge["settlement_rate_cents"]


def create_settlement(lounge_id, visit_id, amount_cents):
    from db import new_id, make_event_fields
    s = {
        "id": new_id(),
        "lounge_id": lounge_id,
        "visit_id": visit_id,
        "amount_cents": amount_cents,
        "status": "PAYABLE",
    }
    s.update(make_event_fields())
    s["_seq"] = db.settlements.next_seq()
    db.settlements.items[s["id"]] = s
    return s


# =============================================================================
# No-show / suspension cascade (PRD §3.8; SCAFFOLD Member state machine)
# =============================================================================
def apply_no_show_strike_cascade(member):
    """After a member's no_show_strikes is recomputed, if it crosses the
    threshold flip GOOD -> SUSPENDED and auto-cancel that member's other HELD
    holds (releasing held_occupancy at each lounge)."""
    if member["standing"] == "GOOD" and \
            member["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD:
        member["standing"] = "SUSPENDED"
        touch(member)
        # CASCADE: auto-cancel other HELD holds of this member.
        affected_lounges = set()
        for v in list(db.visits.items.values()):
            if v["member_id"] == member["id"] and v["status"] == "HELD":
                v["status"] = "CANCELLED"
                touch(v)
                # revert day pass if applicable
                _revert_day_pass_on_cancel(v)
                affected_lounges.add(v["lounge_id"])
        for lid in affected_lounges:
            lounge = get_lounge(lid)
            if lounge:
                recompute_lounge_occupancy(lounge)


def _revert_day_pass_on_cancel(visit):
    """When a hold that redeemed a day pass is cancelled, the held redemption
    reverts to ISSUED and redeemed_visit_id is cleared."""
    dp_id = visit.get("day_pass_id")
    if not dp_id:
        return
    dp = get_day_pass(dp_id)
    if dp and dp["status"] == "REDEEMED" and \
            dp.get("redeemed_visit_id") == visit["id"]:
        dp["status"] = "ISSUED"
        dp["redeemed_visit_id"] = None
        touch(dp)
