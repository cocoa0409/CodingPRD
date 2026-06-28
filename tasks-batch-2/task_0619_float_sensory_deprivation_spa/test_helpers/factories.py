"""Payload factories — one per entity, input fields only."""
import uuid


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ─── MembershipPlan ───────────────────────────────────────────────────────
def create_plan_payload(**overrides) -> dict:
    """Required: tier, monthly_fee_cents, included_floats_per_cycle, rollover_cap,
    retail_float_cents. Optional: member_discount_pct (default 0.0), active (default true)."""
    defaults = {
        "tier": _unique("PLAN"),
        "monthly_fee_cents": 8000,
        "included_floats_per_cycle": 4,
        "rollover_cap": 4,
        "retail_float_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


# ─── Member ───────────────────────────────────────────────────────────────
def create_member_payload(**overrides) -> dict:
    """Required: email, full_name."""
    defaults = {
        "email": f"{_unique('member')}@x.com",
        "full_name": "Test Member",
    }
    defaults.update(overrides)
    return defaults


# ─── Membership ───────────────────────────────────────────────────────────
def create_membership_payload(member_id: str, plan_id: str, **overrides) -> dict:
    """Required: member_id, plan_id."""
    defaults = {"member_id": member_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


# ─── Tank ─────────────────────────────────────────────────────────────────
def create_tank_payload(**overrides) -> dict:
    """Required: name, capacity_kind. Optional: turnover_buffer_minutes (default 30)."""
    defaults = {
        "name": _unique("Pod"),
        "capacity_kind": "SINGLE",
    }
    defaults.update(overrides)
    return defaults


# ─── SanitationCycle ──────────────────────────────────────────────────────
def create_sanitation_cycle_payload(tank_id: str, kind: str = "DEEP_CLEAN", **overrides) -> dict:
    """Required: tank_id, kind. Optional: duration_minutes, booking_id."""
    defaults = {"tank_id": tank_id, "kind": kind}
    defaults.update(overrides)
    return defaults


# ─── Attendant ────────────────────────────────────────────────────────────
def create_attendant_payload(**overrides) -> dict:
    """Required: full_name. Optional: active (default true)."""
    defaults = {"full_name": "Test Attendant"}
    defaults.update(overrides)
    return defaults


# ─── Orientation ──────────────────────────────────────────────────────────
def create_orientation_payload(member_id: str, attendant_id: str, start_utc: str,
                               end_utc: str, **overrides) -> dict:
    """Required: member_id, attendant_id, start_utc, end_utc. Optional: waiver_version
    (default 1)."""
    defaults = {
        "member_id": member_id,
        "attendant_id": attendant_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    defaults.update(overrides)
    return defaults


# ─── Booking ──────────────────────────────────────────────────────────────
def create_booking_payload(member_id: str, tank_id: str, session_minutes: int,
                          start_utc: str, pay_source: str, **overrides) -> dict:
    """Required: member_id, tank_id, session_minutes, start_utc, pay_source.
    Optional: membership_id, is_couples (default false), gift_card_id."""
    defaults = {
        "member_id": member_id,
        "tank_id": tank_id,
        "session_minutes": session_minutes,
        "start_utc": start_utc,
        "pay_source": pay_source,
    }
    defaults.update(overrides)
    return defaults


# ─── GiftCard ─────────────────────────────────────────────────────────────
def create_gift_card_payload(**overrides) -> dict:
    """Required: code, initial_balance_cents."""
    defaults = {
        "code": _unique("GC"),
        "initial_balance_cents": 10000,
    }
    defaults.update(overrides)
    return defaults
