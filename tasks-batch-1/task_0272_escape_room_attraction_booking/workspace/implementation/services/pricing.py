"""Pricing & settlement calculations (PRD §3.5, §3.7, §3.8 / SCAFFOLD calcs)."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import db

BPS_DENOM = 10000


def _parse_utc(s):
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime."""
    txt = s
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _minute_of_day_utc(dt):
    return dt.hour * 60 + dt.minute


def _weekday_bit(dt):
    # bit0 = Monday ... bit6 = Sunday. Python weekday(): Monday=0..Sunday=6.
    return dt.weekday()


def _pricing_rule_for_room(room_id):
    for p in db.pricing_rules.values():
        if p["room_id"] == room_id:
            return p
    return None


def _is_peak(rule, start_utc_str):
    if rule is None:
        return False
    dt = _parse_utc(start_utc_str)
    bit = _weekday_bit(dt)
    if not (rule["peak_dow_mask"] & (1 << bit)):
        return False
    mod = _minute_of_day_utc(dt)
    return rule["peak_start_minute_of_day"] <= mod < rule["peak_end_minute_of_day"]


def _per_participant(room, rule, start_utc_str, count_for_large_group):
    """Pinned per-participant pipeline: base -> peak floor -> large-group floor."""
    per = room["base_price_cents"]
    if _is_peak(rule, start_utc_str):
        per = (per * rule["peak_multiplier_bps"]) // BPS_DENOM
    if rule is not None and count_for_large_group >= rule["large_group_threshold"]:
        per = (per * rule["large_group_multiplier_bps"]) // BPS_DENOM
    return per


def compute_quote(booking, room, slot):
    """price_quote: forward-looking, uses intended group_size."""
    rule = _pricing_rule_for_room(room["id"])
    group_size = booking["group_size"]
    per = _per_participant(room, rule, slot["start_utc"], group_size)
    line_total = per * group_size
    if booking.get("is_private"):
        line_total += room["private_surcharge_cents"]
    return line_total


def compute_settlement(booking, room, slot, settled_count):
    """price_settlement: chronological, uses checked-in count."""
    rule = _pricing_rule_for_room(room["id"])
    per = _per_participant(room, rule, slot["start_utc"], settled_count)
    line_total = per * settled_count
    if booking.get("is_private"):
        line_total += room["private_surcharge_cents"]
    return line_total


def compute_no_show_fee(quoted_charge_cents, no_show_fee_pct):
    """round_half_up(quoted * pct)."""
    amount = Decimal(str(quoted_charge_cents)) * Decimal(str(no_show_fee_pct))
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- temporal geometry helpers ---

def _slot_room_interval(slot):
    return _parse_utc(slot["start_utc"]), _parse_utc(slot["block_end_utc"])


def _slot_game_interval(slot):
    return _parse_utc(slot["start_utc"]), _parse_utc(slot["game_end_utc"])


def _overlaps(a_start, a_end, b_start, b_end):
    # Half-open intervals [start, end): overlap iff a_start < b_end and b_start < a_end.
    return a_start < b_end and b_start < a_end


def room_overlap_conflict(target_slot, room_id, exclude_slot_id=None):
    """True if target overlaps any HELD/BOOKED slot of the SAME room
    (room interval includes reset buffer)."""
    t_start, t_end = _slot_room_interval(target_slot)
    for s in db.time_slots.values():
        if s["id"] == target_slot["id"]:
            continue
        if exclude_slot_id is not None and s["id"] == exclude_slot_id:
            continue
        if s["room_id"] != room_id:
            continue
        if s["status"] not in ("HELD", "BOOKED"):
            continue
        s_start, s_end = _slot_room_interval(s)
        if _overlaps(t_start, t_end, s_start, s_end):
            return True
    return False


def gm_has_game_overlap(gm_id, target_slot, exclude_slot_id=None):
    """True if gm has any HELD/BOOKED slot of ANY room whose game window
    overlaps target's game window (buffer excluded for staff)."""
    t_start, t_end = _slot_game_interval(target_slot)
    for s in db.time_slots.values():
        if s["id"] == target_slot["id"]:
            continue
        if exclude_slot_id is not None and s["id"] == exclude_slot_id:
            continue
        if s.get("assigned_game_master_id") != gm_id:
            continue
        if s["status"] not in ("HELD", "BOOKED"):
            continue
        s_start, s_end = _slot_game_interval(s)
        if _overlaps(t_start, t_end, s_start, s_end):
            return True
    return False


def select_game_master(venue_id, target_slot, exclude_slot_id=None):
    """Candidate set: AVAILABLE gms of the venue with no overlapping game
    window. Rank by active_assignment_count ASC, tie-break created_at ASC.
    Returns the chosen gm dict or None."""
    from services.entities import gm_active_count
    candidates = []
    for g in db.game_masters.values():
        if g["venue_id"] != venue_id:
            continue
        if g["status"] != "AVAILABLE":
            continue
        if gm_has_game_overlap(g["id"], target_slot, exclude_slot_id=exclude_slot_id):
            continue
        candidates.append(g)
    if not candidates:
        return None
    candidates.sort(key=lambda g: (gm_active_count(g["id"]), g["created_at"], g["id"]))
    return candidates[0]
