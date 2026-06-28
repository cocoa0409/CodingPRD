"""Pricing engine (PRD §3.6; SCAFFOLD §1.3 enrollment_drop_in_price,
camp_block_quote, membership_cycle_unused_credit) and member progress score."""
from decimal import Decimal, ROUND_HALF_UP

from db import db

MULTI_WEEK_THRESHOLD = 2
MULTI_WEEK_DISCOUNT_PCT = Decimal("0.10")
SIBLING_DISCOUNT_PCT = Decimal("0.15")

W_BELT = Decimal("0.5")
W_BADGE = Decimal("0.3")
W_ATTEND = Decimal("0.2")


def round_half_up(value):
    """Round a Decimal to whole cents/units, ties going up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def discounted_price(program, session, sibling_index):
    """Steps 1-3 of the drop-in pricing engine: base -> multi-week -> sibling.

    Returns the rounded 'discounted' amount in integer cents (before wallet).
    """
    base = Decimal(program["drop_in_fee_cents"])

    # Step 2 — multi-week multiplier (CAMP only), round per-line.
    if session["format"] == "CAMP" and session["week_count"] >= MULTI_WEEK_THRESHOLD:
        week_factor = Decimal(session["week_count"]) * (Decimal(1) - MULTI_WEEK_DISCOUNT_PCT)
    else:
        week_factor = Decimal(session["week_count"])
    gross = round_half_up(base * week_factor)

    # Step 3 — sibling discount on rounded gross.
    if sibling_index >= 2:
        discounted = round_half_up(Decimal(gross) * (Decimal(1) - SIBLING_DISCOUNT_PCT))
    else:
        discounted = gross
    return discounted


def compute_drop_in(program, session, guardian, sibling_index):
    """Full four-step engine including wallet application + debit.

    Mutates guardian wallet. Returns (price_cents, wallet_applied_cents).
    """
    discounted = discounted_price(program, session, sibling_index)
    wallet = guardian["wallet_credit_cents"]
    wallet_applied = min(wallet, discounted)
    price = discounted - wallet_applied
    guardian["wallet_credit_cents"] = wallet - wallet_applied
    return price, wallet_applied


def camp_block_quote(program, session, members):
    """Round-per-seat-then-sum. sibling_index assigned 1..N in member order.
    Wallet NOT applied (preview only)."""
    per_seat = []
    total = 0
    for i, member in enumerate(members):
        sibling_index = i + 1
        price = discounted_price(program, session, sibling_index)
        per_seat.append({
            "member_id": member["id"],
            "sibling_index": sibling_index,
            "price_cents": price,
        })
        total += price
    return total, per_seat


def membership_cycle_credit(membership):
    """Prorated unused-session credit at cycle rollover. Returns integer cents."""
    included = membership["included_sessions_per_cycle"]
    used = membership["sessions_used_this_cycle"]
    unused = max(0, included - used)
    per_session_value = Decimal(membership["monthly_fee_cents"]) / Decimal(max(1, included))
    credit = round_half_up(Decimal(unused) * per_session_value)
    return credit


def member_progress(member):
    """Compute member_progress_score plus breakdown (PRD §3.7)."""
    belt = db.belt_levels[member["current_belt_level_id"]]
    program_id = member["program_id"]
    total_belts = sum(1 for b in db.belt_levels.values() if b["program_id"] == program_id)
    total_belts = max(1, total_belts)

    belt_factor = Decimal(belt["rank"]) / Decimal(total_belts)

    required = belt["required_badge_count"]
    badge_divisor = max(1, required)
    badge_ratio = Decimal(member["active_badge_count"]) / Decimal(badge_divisor)
    badge_factor = min(Decimal(1), badge_ratio)

    attended = 0
    no_show = 0
    for e in db.enrollments.values():
        if e["member_id"] == member["id"]:
            if e["attendance_status"] == "ATTENDED":
                attended += 1
            elif e["attendance_status"] == "NO_SHOW":
                no_show += 1
    denom = attended + no_show
    if denom == 0:
        attend_factor = Decimal(0)
    else:
        attend_factor = Decimal(attended) / Decimal(denom)

    raw = belt_factor * W_BELT + badge_factor * W_BADGE + attend_factor * W_ATTEND
    score = round_half_up(raw * Decimal(100))
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return {
        "progress_score": score,
        "belt_rank": belt["rank"],
        "total_belts": total_belts,
        "active_badge_count": member["active_badge_count"],
        "required_badge_count": required,
        "attended_sessions": attended,
        "no_show_sessions": no_show,
    }
