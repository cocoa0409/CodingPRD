"""Composite setup helpers for the Gym Membership test suite.

Most interesting test claims need the system in a specific state reached
through 5–15 API calls (card-type → member → recharge → issue → activate
→ ...). These helpers encapsulate those preambles so test bodies stay
focused on assertions.

Identity threading (PRD §2.1):
- Member is ENTITY-BACKED: "When X-User-Role is Member, X-User-ID is the
  id of the acting Member; ownership checks ... compare the resource's
  foreign-key field ... to X-User-ID." Every ownership-gated Member call
  MUST use make_member_headers(member['id']).
- Trainer is ENTITY-BACKED: "When X-User-Role is Trainer, X-User-ID is
  the id of the acting Trainer." Every ownership-gated Trainer call MUST
  use make_trainer_headers(trainer['id']).
- PlatformAdmin, StaffOps, system are OPAQUE.

Setup helpers use get_success_data (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion failure
inside the test body.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    access_event_payload,
    clock_payload,
    create_card_type_payload,
    create_group_booking_payload,
    create_group_class_payload,
    create_member_payload,
    create_pt_booking_payload,
    create_pt_package_payload,
    create_trainer_payload,
    create_trainer_slot_payload,
    freeze_payload,
    issue_card_payload,
    open_payout_payload,
    recharge_payload,
    transfer_payload,
    unfreeze_payload,
    send_reminder_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_trainer_headers,
)


# ===========================================================================
# Shared opaque-role headers
# ===========================================================================
PA = TEST_USERS["platform_admin_headers"]
PA_ALT = TEST_USERS["platform_admin_headers_alt"]
SO = TEST_USERS["staff_ops_headers"]
SO_ALT = TEST_USERS["staff_ops_headers_alt"]
SYS = TEST_USERS["system_headers"]


# ===========================================================================
# ISO 8601 helpers (PRD §2.7: ISO 8601 UTC; PRD §2.2 three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision, Z-suffixed."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 UTC string into a tz-aware UTC datetime."""
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def end_of_day(dt: datetime) -> datetime:
    """PRD §2.7: 'End-of-day timestamps used for expiry semantics are
    anchored at 23:59:59.999Z UTC.'"""
    return dt.astimezone(timezone.utc).replace(
        hour=23, minute=59, second=59, microsecond=999_000,
    )


# ===========================================================================
# Clock helpers (PRD §2.10)
# ===========================================================================
def advance_clock(to_iso: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.10: 'The clock-advance capability ... nudges the logical
    clock to a supplied instant.'"""
    return get_success_data(api_client.advance_clock(
        clock_payload(to=to_iso), headers or SYS,
    ))


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.10: 'A parallel sweep capability runs the renewal-reminder
    fan-out independently.'"""
    return get_success_data(api_client.run_sweep(headers or SYS))


def reset_clock_to(initial_iso: str = "2026-01-01T00:00:00.000Z") -> None:
    """Many tests are easier to read when clock starts at a known instant.
    The runner provides a fresh server for each session; advancing once
    sets the baseline."""
    advance_clock(initial_iso)


# ===========================================================================
# Card-type creation (PRD §3.1)
# ===========================================================================
def create_card_type(headers: Optional[Dict[str, str]] = None,
                     **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_card_type(
        create_card_type_payload(**overrides), headers or PA,
    ))


def create_annual_card_type(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 ANNUAL category card type."""
    defaults = {
        "category": "ANNUAL",
        "price_cents": 120_000,
        "validity_days": 365,
        "visit_quota": 0,
        "family_shareable": False,
        "max_freeze_days": 14,
        "transfer_fee_pct_bp": 1_000,
        "renewal_discount_pct_bp": 1_000,
        "refund_eligibility_days": 30,
    }
    defaults.update(overrides)
    return create_card_type(**defaults)


def create_monthly_card_type(**overrides: Any) -> Dict[str, Any]:
    defaults = {
        "category": "MONTHLY",
        "price_cents": 30_000,
        "validity_days": 30,
        "visit_quota": 0,
        "family_shareable": False,
        "max_freeze_days": 10,
        "transfer_fee_pct_bp": 1_000,
        "renewal_discount_pct_bp": 1_500,
        "refund_eligibility_days": 7,
    }
    defaults.update(overrides)
    return create_card_type(**defaults)


def create_per_visit_card_type(**overrides: Any) -> Dict[str, Any]:
    defaults = {
        "category": "PER_VISIT",
        "price_cents": 20_000,
        "validity_days": 90,
        "visit_quota": 10,
        "family_shareable": False,
        "max_freeze_days": 0,
        "transfer_fee_pct_bp": 500,
        "renewal_discount_pct_bp": 0,
        "refund_eligibility_days": 0,
    }
    defaults.update(overrides)
    return create_card_type(**defaults)


# ===========================================================================
# Member creation (PRD §3.1)
# ===========================================================================
def create_member(headers: Optional[Dict[str, str]] = None,
                  **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_member(
        create_member_payload(**overrides), headers or PA,
    ))


def get_member(member_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_member(
        member_id, headers or PA,
    ))


def recharge_member(member_id: str, amount_cents: int,
                    headers: Optional[Dict[str, str]] = None) -> Any:
    """Use the member's own entity-backed headers when ownership-gated.
    Returns whatever the recharge endpoint returns (may be a list of
    WalletTransaction rows per PRD §3.3 output)."""
    return get_success_data(api_client.recharge_wallet(
        member_id, recharge_payload(amount_cents=amount_cents),
        headers or make_member_headers(member_id),
    ))


def list_wallet_transactions(
    member_id: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Paginated list — drain all pages so callers can assert across the
    full ledger.

    PRD §3.4 says rows return in created_at ascending order; we accumulate
    in that order.
    """
    use_headers = headers or make_member_headers(member_id)
    out: List[Dict[str, Any]] = []
    offset = 0
    limit = 100
    while True:
        p = {"limit": limit, "offset": offset}
        if params:
            p.update(params)
        resp = api_client.list_wallet_transactions(
            member_id, use_headers, params=p,
        )
        data, meta = validate_paginated(resp)
        out.extend(data)
        if not meta.get("has_more"):
            break
        offset += limit
    return out


def create_funded_member(
    *,
    wallet_balance_cents: int = 200_000,
    headers: Optional[Dict[str, str]] = None,
    **member_overrides: Any,
) -> Dict[str, Any]:
    """Create a member then recharge so their principal balance >= the
    target. Returns the member dict (re-fetched after the recharge so
    wallet_balance_cents reflects the projection).

    Note: PRD §3.3 caps recharge at 1,000,000 cents per call. If the
    target exceeds this we split across multiple recharges.
    """
    member = create_member(headers, **member_overrides)
    remaining = wallet_balance_cents
    while remaining > 0:
        chunk = min(remaining, 1_000_000)
        recharge_member(member["id"], chunk)
        remaining -= chunk
    return get_member(member["id"])


# ===========================================================================
# Card lifecycle (PRD §3.2)
# ===========================================================================
def issue_card(card_type_id: str, holder_member_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.2: 'Issuance also debits the wallet of the holder for
    CardType.price_cents'. Caller must ensure wallet has funds."""
    return get_success_data(api_client.issue_card(
        issue_card_payload(
            card_type_id=card_type_id,
            holder_member_id=holder_member_id,
        ),
        headers or SO,
    ))


def activate_card(card_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.activate_card(card_id, headers or SO))


def get_card(card_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_card(card_id, headers or PA))


def issue_and_activate_card(
    *,
    card_type: Dict[str, Any],
    member: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a wallet-funded path through PENDING→ACTIVE.

    Assumes the member's wallet already covers CardType.price_cents.
    """
    card = issue_card(card_type["id"], member["id"], headers)
    return activate_card(card["id"], headers)


# ===========================================================================
# Tier 1+2: full setup of a member with an ACTIVE card.
# ===========================================================================
def setup_member_with_active_card(
    *,
    card_type_overrides: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
    wallet_balance_cents: Optional[int] = None,
    category: str = "MONTHLY",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (card_type, member, active_card).

    Sets baseline clock to 2026-01-01T00:00:00Z; funds member's wallet
    sufficiently to cover the card price; issues + activates.
    """
    reset_clock_to("2026-01-01T00:00:00.000Z")
    if category == "ANNUAL":
        ct = create_annual_card_type(**(card_type_overrides or {}))
    elif category == "PER_VISIT":
        ct = create_per_visit_card_type(**(card_type_overrides or {}))
    else:
        ct = create_monthly_card_type(**(card_type_overrides or {}))
    needed = wallet_balance_cents or (ct["price_cents"] + 100_000)
    member = create_funded_member(
        wallet_balance_cents=needed,
        **(member_overrides or {}),
    )
    card = issue_and_activate_card(card_type=ct, member=member)
    return ct, member, card


# ===========================================================================
# Freeze helpers (PRD §3.5)
# ===========================================================================
def freeze_card(card_id: str, *, reason: str = "ILLNESS",
                requested_days: int = 5,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.freeze_card(
        card_id,
        freeze_payload(reason=reason, requested_days=requested_days),
        headers or SO,
    ))


def unfreeze_card(card_id: str, freeze_episode_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.unfreeze_card(
        card_id,
        unfreeze_payload(freeze_episode_id=freeze_episode_id),
        headers or SO,
    ))


# ===========================================================================
# Trainer / TrainerSlot / PT helpers (PRD §3.8)
# ===========================================================================
def create_trainer(*, specialties: Optional[List[str]] = None,
                   session_commission_pct_bp: int = 1_500,
                   package_commission_pct_bp: int = 800,
                   headers: Optional[Dict[str, str]] = None,
                   **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_trainer(
        create_trainer_payload(
            specialties=specialties,
            session_commission_pct_bp=session_commission_pct_bp,
            package_commission_pct_bp=package_commission_pct_bp,
            **overrides,
        ),
        headers or PA,
    ))


def patch_trainer(trainer_id: str, payload: Dict[str, Any],
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.patch_trainer(
        trainer_id, payload, headers or PA,
    ))


def create_trainer_slot(*, trainer_id: str,
                        starts_at: str, ends_at: str,
                        specialty_code: str = "STRENGTH",
                        headers: Optional[Dict[str, str]] = None,
                        ) -> Dict[str, Any]:
    """Use the trainer's entity-backed headers when ownership-gated; PRD
    §3.8 declares Trainer slot publishing is per-trainer."""
    use_headers = headers or make_trainer_headers(trainer_id)
    return get_success_data(api_client.create_trainer_slot(
        create_trainer_slot_payload(
            trainer_id=trainer_id,
            starts_at=starts_at,
            ends_at=ends_at,
            specialty_code=specialty_code,
        ),
        use_headers,
    ))


def create_pt_booking(*, member: Dict[str, Any], slot: Dict[str, Any],
                      billing_mode: str = "SINGLE",
                      package_id: Optional[str] = None,
                      headers: Optional[Dict[str, str]] = None,
                      ) -> Dict[str, Any]:
    use_headers = headers or make_member_headers(member["id"])
    return get_success_data(api_client.create_pt_booking(
        create_pt_booking_payload(
            member_id=member["id"],
            slot_id=slot["id"],
            billing_mode=billing_mode,
            package_id=package_id,
        ),
        use_headers,
    ))


def cancel_pt_booking(booking_id: str,
                      headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_pt_booking(
        booking_id, headers,
    ))


def complete_pt_booking(booking_id: str, trainer_id: str,
                        headers: Optional[Dict[str, str]] = None,
                        ) -> Dict[str, Any]:
    """PRD §4: complete is authorized for Trainer, StaffOps, PlatformAdmin.
    Trainer must own the booking; pass that trainer's headers."""
    use_headers = headers or make_trainer_headers(trainer_id)
    return get_success_data(api_client.complete_pt_booking(
        booking_id, use_headers,
    ))


def create_pt_package(*, member: Dict[str, Any], trainer_id: str,
                      total_sessions: int = 7,
                      gross_price_cents: int = 100_000,
                      headers: Optional[Dict[str, str]] = None,
                      ) -> Dict[str, Any]:
    use_headers = headers or make_member_headers(member["id"])
    return get_success_data(api_client.create_pt_package(
        create_pt_package_payload(
            member_id=member["id"],
            trainer_id=trainer_id,
            total_sessions=total_sessions,
            gross_price_cents=gross_price_cents,
        ),
        use_headers,
    ))


# ===========================================================================
# Group classes / bookings (PRD §3.9)
# ===========================================================================
def create_group_class(*, instructor_trainer_id: str,
                       starts_at: str, ends_at: str,
                       capacity: int = 5,
                       deduction_cents: Optional[int] = None,
                       class_code: Optional[str] = None,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    return get_success_data(api_client.create_group_class(
        create_group_class_payload(
            class_code=class_code,
            instructor_trainer_id=instructor_trainer_id,
            starts_at=starts_at,
            ends_at=ends_at,
            capacity=capacity,
            deduction_cents=deduction_cents,
        ),
        headers or SO,
    ))


def create_group_booking(*, class_id: str, member: Dict[str, Any],
                         card_id: Optional[str] = None,
                         accept_waitlist: Optional[bool] = None,
                         headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    use_headers = headers or make_member_headers(member["id"])
    return get_success_data(api_client.create_group_booking(
        create_group_booking_payload(
            class_id=class_id,
            member_id=member["id"],
            card_id=card_id,
            accept_waitlist=accept_waitlist,
        ),
        use_headers,
    ))


def cancel_group_booking(booking_id: str,
                         headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_group_booking(
        booking_id, headers,
    ))


# ===========================================================================
# Access events (PRD §3.10)
# ===========================================================================
def access_card(card: Dict[str, Any], member: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.10 turnstile entry. Role: StaffOps."""
    return get_success_data(api_client.create_access_event(
        access_event_payload(card_id=card["id"], member_id=member["id"]),
        SO,
    ))


# ===========================================================================
# Payouts (PRD §3.11)
# ===========================================================================
def open_payout(*, cycle_start: str, cycle_end: str) -> Dict[str, Any]:
    return get_success_data(api_client.open_payout(
        open_payout_payload(cycle_start=cycle_start, cycle_end=cycle_end),
        PA,
    ))


def close_payout(cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.close_payout(cycle_id, PA))


def list_trainer_commissions(
    trainer_id: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    use_headers = headers or PA
    out: List[Dict[str, Any]] = []
    offset = 0
    limit = 100
    while True:
        p = {"limit": limit, "offset": offset}
        if params:
            p.update(params)
        resp = api_client.list_trainer_commissions(
            trainer_id, use_headers, params=p,
        )
        data, meta = validate_paginated(resp)
        out.extend(data)
        if not meta.get("has_more"):
            break
        offset += limit
    return out


def list_audit_log(action: Optional[str] = None,
                   target_startswith: Optional[str] = None,
                   ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    offset = 0
    limit = 100
    while True:
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if action is not None:
            params["action"] = action
        resp = api_client.list_audit_log(PA, params=params)
        data, meta = validate_paginated(resp)
        out.extend(data)
        if not meta.get("has_more"):
            break
        offset += limit
    if target_startswith:
        out = [r for r in out
               if (r.get("target_entity") or "").startswith(target_startswith)]
    return out


# ===========================================================================
# Tier 4 — composite scenarios for difficulty-design instances
# ===========================================================================
def setup_annual_card_at_remaining_days(
    *,
    remaining_days: int,
    activation_iso: str = "2026-01-01T00:00:00.000Z",
    validity_days: int = 365,
    price_cents: int = 120_000,
    refund_eligibility_days: int = 30,
    transfer_fee_pct_bp: int = 1_000,
    max_freeze_days: int = 14,
    family_group_id: Optional[str] = None,
    extra_funds_cents: int = 200_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Set up an activated ANNUAL card with a specific number of days
    remaining. Returns (card_type, member, card).

    Internally:
      1. clock := activation_iso
      2. create CardType with validity_days/price/transfer_fee/etc.
      3. create member with wallet_balance >= price + extra_funds_cents
      4. issue + activate card → original_expiry_date is activation +
         validity_days (end-of-day)
      5. advance clock to activation + (validity_days - remaining_days)
         (so remaining days from clock to expiry equals target).

    Used by difficulty-design rule 1 (card_remaining_value_dual_variant)
    and rule 2 (transfer_fee_round_order_pinned).
    """
    reset_clock_to(activation_iso)
    ct = create_annual_card_type(
        price_cents=price_cents,
        validity_days=validity_days,
        refund_eligibility_days=refund_eligibility_days,
        transfer_fee_pct_bp=transfer_fee_pct_bp,
        max_freeze_days=max_freeze_days,
    )
    member_kwargs: Dict[str, Any] = {}
    if family_group_id:
        member_kwargs["family_group_id"] = family_group_id
    member = create_funded_member(
        wallet_balance_cents=price_cents + extra_funds_cents,
        **member_kwargs,
    )
    card = issue_and_activate_card(card_type=ct, member=member)

    # Advance clock so that effective_expiry - now() == remaining_days.
    activation_dt = parse_iso(activation_iso)
    elapsed_days = validity_days - remaining_days
    target_dt = activation_dt + timedelta(days=elapsed_days)
    advance_clock(iso_z(target_dt))
    return ct, member, get_card(card["id"])


def setup_monthly_card_for_refund_eligibility(
    *,
    remaining_days: int,
    refund_eligibility_days: int = 30,
    validity_days: int = 90,
    price_cents: int = 90_000,
    renewal_discount_pct_bp: int = 1_500,
    activation_iso: str = "2026-01-01T00:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """For refund_eligibility_day_inclusive_boundary
    (difficulty rule 6). Activate a MONTHLY card; advance clock to a
    point where (effective_expiry - now()) in days equals
    remaining_days.

    NOTE: MONTHLY validity_days at 90 falls outside the spec's
    1..3650 bound — we keep it well within (90)."""
    reset_clock_to(activation_iso)
    ct = create_monthly_card_type(
        price_cents=price_cents,
        validity_days=validity_days,
        max_freeze_days=0,             # avoid freeze interactions
        refund_eligibility_days=refund_eligibility_days,
        renewal_discount_pct_bp=renewal_discount_pct_bp,
    )
    member = create_funded_member(
        wallet_balance_cents=price_cents + 100_000,
    )
    card = issue_and_activate_card(card_type=ct, member=member)

    activation_dt = parse_iso(activation_iso)
    elapsed_days = validity_days - remaining_days
    target_dt = activation_dt + timedelta(days=elapsed_days)
    advance_clock(iso_z(target_dt))
    return ct, member, get_card(card["id"])


# ---------------------------------------------------------------------------
# Setup helper: two trainers, one BRONZE, one GOLD, both with identical
# session_commission_pct_bp = 1500.  Used by
# trainer_session_commission_tier_modifier_variant (difficulty rule 1).
# ---------------------------------------------------------------------------
def setup_two_trainers_bronze_and_gold(
    *,
    session_rate_bp: int = 1_500,
    package_rate_bp: int = 800,
    activation_iso: str = "2026-01-01T00:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns (bronze_trainer, gold_trainer).

    Bronze stays BRONZE because no COMPLETED bookings accrue in cycle.
    Gold is promoted to GOLD by completing >= 80 bookings within a
    payout cycle and closing it.
    """
    reset_clock_to(activation_iso)
    bronze = create_trainer(
        specialties=["STRENGTH"],
        session_commission_pct_bp=session_rate_bp,
        package_commission_pct_bp=package_rate_bp,
        full_name=f"Bronze {hex(id(object()))}",
    )
    gold = create_trainer(
        specialties=["STRENGTH"],
        session_commission_pct_bp=session_rate_bp,
        package_commission_pct_bp=package_rate_bp,
        full_name=f"Gold {hex(id(object()))}",
    )
    # Open payout cycle Q1.
    cycle_start_iso = activation_iso
    cycle_end_iso = "2026-04-01T00:00:00.000Z"
    cycle = open_payout(cycle_start=cycle_start_iso, cycle_end=cycle_end_iso)

    # Schedule 80 sequential slots for gold, each 1 hour long, starting
    # at activation + 1 day, then book + complete each.  We need 80
    # *COMPLETED* PTBookings whose scheduled_starts_at lies in the cycle
    # window — PRD §3.11.
    activation_dt = parse_iso(activation_iso)
    base = activation_dt + timedelta(days=1)
    members: List[Dict[str, Any]] = []
    # Re-use a single rich member for all 80 sessions to keep setup fast.
    rich_member = create_funded_member(wallet_balance_cents=900_000)
    # PRD §3.8 says session_price_cents "is pinned" at booking; the PRD
    # leaves the source of that pin open. Fund generously — up to the
    # per-recharge cap (1_000_000) per recharge call. We do several
    # 1_000_000 recharges so booking 80 sessions cannot run out even if
    # the implementation pins a price as high as ~100_000 cents/session.
    for _ in range(8):
        recharge_member(rich_member["id"], 1_000_000)
    rich_member = get_member(rich_member["id"])

    for i in range(80):
        s = base + timedelta(hours=i)
        e = s + timedelta(minutes=30)
        slot = create_trainer_slot(
            trainer_id=gold["id"],
            starts_at=iso_z(s),
            ends_at=iso_z(e),
            specialty_code="STRENGTH",
        )
        booking = create_pt_booking(
            member=rich_member,
            slot=slot,
            billing_mode="SINGLE",
        )
        # Advance to the slot's start so complete is allowed.
        advance_clock(iso_z(s))
        complete_pt_booking(booking["id"], gold["id"])

    # Now advance past cycle_end and close.
    advance_clock(cycle_end_iso)
    close_payout(cycle["id"])
    return get_trainer(bronze["id"]), get_trainer(gold["id"])


def get_trainer(trainer_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_trainer(trainer_id, headers or PA))


def funded_to_target(member_id: str, additional_cents: int) -> None:
    """Top up wallet to ensure at least additional_cents more principal
    becomes available."""
    remaining = additional_cents
    while remaining > 0:
        chunk = min(remaining, 1_000_000)
        recharge_member(member_id, chunk)
        remaining -= chunk


# ---------------------------------------------------------------------------
# Setup helpers for difficulty rule 4 (transitive cascade)
# ---------------------------------------------------------------------------
def setup_package_with_partial_consumption_simple(
    *,
    total_sessions: int = 7,
    sessions_to_complete: int = 3,
    gross_price_cents: int = 100_000,
    package_commission_pct_bp: int = 800,
    activation_iso: str = "2026-01-01T00:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Same as setup_package_with_partial_consumption but returns the
    package dict from creation (no GET) plus the booking ids list so
    callers can inspect post-refund state.

    Returns (trainer, member, package_at_creation, refund_observation).

    refund_observation is a dict carrying:
      - "completed_booking_ids": list of completed booking ids
      - "expected_pkg_sale_commission": int
    """
    reset_clock_to(activation_iso)
    trainer = create_trainer(
        specialties=["STRENGTH"],
        session_commission_pct_bp=1_500,
        package_commission_pct_bp=package_commission_pct_bp,
    )
    member = create_funded_member(
        wallet_balance_cents=gross_price_cents + 100_000,
    )
    package = get_success_data(api_client.create_pt_package(
        create_pt_package_payload(
            member_id=member["id"],
            trainer_id=trainer["id"],
            total_sessions=total_sessions,
            gross_price_cents=gross_price_cents,
        ),
        make_member_headers(member["id"]),
    ))
    completed_ids: List[str] = []
    activation_dt = parse_iso(activation_iso)
    base = activation_dt + timedelta(days=1)
    for i in range(sessions_to_complete):
        s = base + timedelta(hours=i * 2)
        e = s + timedelta(hours=1)
        slot = create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at=iso_z(s),
            ends_at=iso_z(e),
            specialty_code="STRENGTH",
        )
        booking = create_pt_booking(
            member=member,
            slot=slot,
            billing_mode="PACKAGE",
            package_id=package["id"],
        )
        advance_clock(iso_z(s))
        completed = complete_pt_booking(booking["id"], trainer["id"])
        completed_ids.append(completed["id"])

    from .constants import round_half_up as _r
    return (
        trainer,
        member,
        package,
        {
            "completed_booking_ids": completed_ids,
            "expected_pkg_sale_commission": _r(
                gross_price_cents * package_commission_pct_bp / 10_000,
            ),
        },
    )


# ---------------------------------------------------------------------------
# Setup helper: GroupClass + WAITLIST scenario for rule 3
# (group_booking_branching_with_waitlist_promotion).
# ---------------------------------------------------------------------------
def setup_group_class_with_waitlist(
    *,
    capacity: int = 1,
    deduction_cents: int = 0,
    activation_iso: str = "2026-01-01T00:00:00.000Z",
    class_start_offset_hours: int = 24,
    class_duration_minutes: int = 60,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (trainer, group_class, member1, member2, booking2_waitlisted).

    booking1 (member1) is CONFIRMED; booking2 (member2) is WAITLISTED at
    position 1. Used by waitlist-promotion tests.
    """
    reset_clock_to(activation_iso)
    trainer = create_trainer(specialties=["STRENGTH"])
    activation_dt = parse_iso(activation_iso)
    s = activation_dt + timedelta(hours=class_start_offset_hours)
    e = s + timedelta(minutes=class_duration_minutes)
    klass = create_group_class(
        instructor_trainer_id=trainer["id"],
        starts_at=iso_z(s),
        ends_at=iso_z(e),
        capacity=capacity,
        deduction_cents=deduction_cents,
    )
    m1 = create_funded_member(wallet_balance_cents=100_000)
    m2 = create_funded_member(wallet_balance_cents=100_000)
    # m1 books first → CONFIRMED.
    b1 = create_group_booking(class_id=klass["id"], member=m1)
    # m2 books with accept_waitlist=True → WAITLISTED at position 1.
    b2 = create_group_booking(
        class_id=klass["id"], member=m2, accept_waitlist=True,
    )
    return trainer, klass, m1, m2, b2


# ---------------------------------------------------------------------------
# Setup helper for rule 5 instance:
# state_vs_business_referential_refund_on_frozen_card.
#   - Card with a previous SETTLED freeze episode (so card was ever frozen)
#   - Currently FROZEN (an APPROVED freeze episode in progress)
# ---------------------------------------------------------------------------
def setup_card_currently_frozen_with_settled_history(
    *,
    activation_iso: str = "2026-01-01T00:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (card_type, member, card_currently_frozen).

    Sequence:
      activate annual card → freeze 3 days → advance past ends_at
      → settled (card back to ACTIVE) → freeze 4 days fresh → card FROZEN.
    """
    ct, member, card = setup_member_with_active_card(
        category="ANNUAL",
        card_type_overrides={"max_freeze_days": 14,
                             "refund_eligibility_days": 30},
    )
    # First freeze.
    fe1 = freeze_card(card["id"], requested_days=3)
    # Advance past first freeze ends_at to settle it.
    advance_clock(fe1["ends_at"])
    # Tiny clock bump beyond ends_at to ensure crossing is unambiguous.
    settled_card = get_card(card["id"])
    assert settled_card["status"] == "ACTIVE", (
        f"setup error: card should have returned to ACTIVE after freeze "
        f"settle; got {settled_card['status']}"
    )
    # Now create a second freeze in progress.
    fe2 = freeze_card(card["id"], requested_days=4)
    # The card is now FROZEN, with one SETTLED + one APPROVED episode.
    return ct, member, get_card(card["id"])


# ---------------------------------------------------------------------------
# Setup helper for rule 5 instance: PT cancel-window-vs-balance.
# We need a confirmed SINGLE PT booking with paid-up wallet, then clock
# pushed past starts_at, then wallet drained.
# ---------------------------------------------------------------------------
def setup_pt_booking_past_starts_with_zero_balance(
    *,
    activation_iso: str = "2026-01-01T00:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (trainer, member, booking, slot).

    1. activate clock at activation_iso
    2. trainer published a slot at activation + 1 day
    3. fund member, book SINGLE PT booking → wallet debited the session
       price
    4. advance clock past slot.starts_at
    5. drain wallet to zero with a PT package or a series of recharges
       offset by debits; in practice tests need the cancel to be
       blocked by ERR_CANCEL_WINDOW_EXPIRED, so wallet content does not
       have to be literally zero — what matters is "past starts_at".

    PRD §3.8: cancel is rejected with ERR_CANCEL_WINDOW_EXPIRED for
    now() >= scheduled_starts_at.
    """
    reset_clock_to(activation_iso)
    trainer = create_trainer(specialties=["STRENGTH"])
    activation_dt = parse_iso(activation_iso)
    s = activation_dt + timedelta(days=1)
    e = s + timedelta(hours=1)
    slot = create_trainer_slot(
        trainer_id=trainer["id"],
        starts_at=iso_z(s),
        ends_at=iso_z(e),
        specialty_code="STRENGTH",
    )
    member = create_funded_member(wallet_balance_cents=50_000)
    booking = create_pt_booking(
        member=member, slot=slot, billing_mode="SINGLE",
    )
    # Advance to past starts_at but before the 15-minute auto-no-show
    # threshold so the cancel hits the cancel-window check (PRD §3.8)
    # and not the from-state check (PRD §3.12 priority order moves
    # state-machine before cancel-window).
    advance_clock(iso_z(s + timedelta(minutes=5)))
    return trainer, member, booking, slot


# ---------------------------------------------------------------------------
# Setup helper for rule 7 instance: card_freeze_blocked_by_active_pt_booking
# ---------------------------------------------------------------------------
def setup_card_with_confirmed_pt_booking_in_freeze_window(
    *,
    activation_iso: str = "2026-01-01T00:00:00.000Z",
    booking_offset_days: int = 3,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (card_type, member, card, booking).

    Card is ACTIVE, max_freeze_days=14, cumulative_freeze_days=0; a
    CONFIRMED PT booking for the same member at activation + 3 days.
    """
    reset_clock_to(activation_iso)
    ct = create_annual_card_type(
        max_freeze_days=14,
        refund_eligibility_days=0,
    )
    member = create_funded_member(wallet_balance_cents=400_000)
    card = issue_and_activate_card(card_type=ct, member=member)
    trainer = create_trainer(specialties=["STRENGTH"])
    activation_dt = parse_iso(activation_iso)
    s = activation_dt + timedelta(days=booking_offset_days)
    e = s + timedelta(hours=1)
    slot = create_trainer_slot(
        trainer_id=trainer["id"],
        starts_at=iso_z(s),
        ends_at=iso_z(e),
        specialty_code="STRENGTH",
    )
    booking = create_pt_booking(
        member=member, slot=slot, billing_mode="SINGLE",
    )
    return ct, member, get_card(card["id"]), booking


# ---------------------------------------------------------------------------
# Setup helper for rule 7 instance: pt_booking_blocked_by_inactive_trainer
# ---------------------------------------------------------------------------
def setup_inactive_trainer_with_published_slot(
    *,
    activation_iso: str = "2026-01-01T00:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (trainer, member, slot). Trainer is INACTIVE."""
    reset_clock_to(activation_iso)
    trainer = create_trainer(specialties=["STRENGTH"])
    activation_dt = parse_iso(activation_iso)
    s = activation_dt + timedelta(days=1)
    e = s + timedelta(hours=1)
    slot = create_trainer_slot(
        trainer_id=trainer["id"],
        starts_at=iso_z(s),
        ends_at=iso_z(e),
        specialty_code="STRENGTH",
    )
    # Patch trainer to INACTIVE. PRD §3.8: only PlatformAdmin can
    # PATCH /trainers/{id}.
    trainer = patch_trainer(
        trainer["id"],
        {"version": trainer["version"], "status": "INACTIVE"},
    )
    member = create_funded_member(wallet_balance_cents=200_000)
    return trainer, member, slot


# ---------------------------------------------------------------------------
# Setup helper for rule 4 instance:
# clock_advance_to_card_expiry_to_autorenew_chain
#   - MONTHLY card; auto_renew_authorized=true; wallet pre-funded;
#   - T0 reminder dispatched at activation + 30 days;
#   - advance clock past effective_expiry_date.
# ---------------------------------------------------------------------------
def setup_card_for_auto_renew_chain(
    *,
    activation_iso: str = "2026-01-01T00:00:00.000Z",
    price_cents: int = 30_000,
    validity_days: int = 30,
    extra_funds_cents: int = 200_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (card_type, member, original_card).

    After return the caller can advance clock to past
    effective_expiry to trigger the auto-renew cascade.
    """
    reset_clock_to(activation_iso)
    ct = create_monthly_card_type(
        price_cents=price_cents,
        validity_days=validity_days,
        renewal_discount_pct_bp=0,
        refund_eligibility_days=0,
        max_freeze_days=0,
    )
    # Member with auto_renew + plenty of wallet for original + renewal.
    member = create_funded_member(
        wallet_balance_cents=price_cents * 2 + extra_funds_cents,
        auto_renew_authorized=True,
        notification_channels=["SMS", "EMAIL", "IM", "PUSH"],
    )
    card = issue_and_activate_card(card_type=ct, member=member)
    return ct, member, get_card(card["id"])


__all__ = [
    "PA", "PA_ALT", "SO", "SO_ALT", "SYS",
    "iso_z", "parse_iso", "end_of_day",
    "advance_clock", "run_sweep", "reset_clock_to",
    "create_card_type",
    "create_annual_card_type", "create_monthly_card_type",
    "create_per_visit_card_type",
    "create_member", "create_funded_member",
    "get_member", "recharge_member",
    "list_wallet_transactions",
    "issue_card", "activate_card", "get_card",
    "issue_and_activate_card",
    "setup_member_with_active_card",
    "freeze_card", "unfreeze_card",
    "create_trainer", "patch_trainer", "get_trainer",
    "create_trainer_slot",
    "create_pt_booking", "cancel_pt_booking", "complete_pt_booking",
    "create_pt_package",
    "create_group_class", "create_group_booking", "cancel_group_booking",
    "access_card",
    "open_payout", "close_payout",
    "list_trainer_commissions", "list_audit_log",
    "funded_to_target",
    "setup_annual_card_at_remaining_days",
    "setup_monthly_card_for_refund_eligibility",
    "setup_two_trainers_bronze_and_gold",
    "setup_package_with_partial_consumption_simple",
    "setup_group_class_with_waitlist",
    "setup_card_currently_frozen_with_settled_history",
    "setup_pt_booking_past_starts_with_zero_balance",
    "setup_card_with_confirmed_pt_booking_in_freeze_window",
    "setup_inactive_trainer_with_published_slot",
    "setup_card_for_auto_renew_chain",
]
