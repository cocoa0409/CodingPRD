"""Composite setup helpers for the Tanning & Spray-Tan Salon API.

Every test runs against a freshly-launched, empty server, so each fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls use
the lenient get_success_data() validator so a setup failure surfaces clearly.

Identity threading: after a member is created, any ownership-gated call (freeze,
unfreeze, upgrade, cancel, booking, retail order placed as Member) uses
make_member_headers(member["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_member_headers,
)
from .factories import (
    create_membership_plan_payload,
    create_member_payload,
    create_equipment_payload,
    create_spray_room_payload,
    create_product_payload,
    create_consent_payload,
    create_session_payload,
    create_retail_order_payload,
)

SALON_MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_system_headers"]


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Set the logical clock (BillingSystem)."""
    return get_success_data(api_client.set_clock(to_iso8601, BILLING))


def create_plan(**overrides) -> dict:
    """Create a MembershipPlan (SalonManager)."""
    return get_success_data(
        api_client.create_membership_plan(create_membership_plan_payload(**overrides), SALON_MANAGER)
    )


def create_equipment(**overrides) -> dict:
    """Create an Equipment unit (SalonManager)."""
    return get_success_data(
        api_client.create_equipment(create_equipment_payload(**overrides), SALON_MANAGER)
    )


def create_spray_room(**overrides) -> dict:
    """Create a SprayRoom (SalonManager)."""
    return get_success_data(
        api_client.create_spray_room(create_spray_room_payload(**overrides), SALON_MANAGER)
    )


def create_product(**overrides) -> dict:
    """Create a Product (SalonManager)."""
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), SALON_MANAGER)
    )


def register_member(plan_id: str, **overrides) -> dict:
    """Register a PENDING member (FrontDeskStaff)."""
    payload = create_member_payload(plan_id=plan_id, **overrides)
    return get_success_data(api_client.create_member(payload, FRONT_DESK))


def create_active_member(plan_id: str, **overrides) -> dict:
    """Register a member, charge first dues SUCCEEDED, and activate.

    Returns the activated Member resource (status ACTIVE). cycle_anchor_at is the
    logical clock at activation, so callers that need a known anchor should set the
    clock before calling this helper.
    """
    member = register_member(plan_id, **overrides)
    mid = member["id"]
    get_success_data(
        api_client.charge_first_dues({"member_id": mid, "outcome": "SUCCEEDED"}, BILLING)
    )
    activated = get_success_data(api_client.activate_member(mid, BILLING))
    return activated


# ---------------------------------------------------------------------------
# Tier 1/2: common active-member-with-resource scenarios
# ---------------------------------------------------------------------------
def setup_active_member_with_equipment(plan_overrides=None, member_overrides=None,
                                       equip_overrides=None, clock=None):
    """Active member + one Equipment unit. Returns (plan, member, equipment).

    plan defaults to UNLIMITED 6000 weekly_uv_session_cap=0; equipment defaults to
    max_exposure_seconds=600 turnaround_seconds=600.
    """
    plan = create_plan(**(plan_overrides or {}))
    equip_kwargs = {"max_exposure_seconds": 600, "turnaround_seconds": 600}
    equip_kwargs.update(equip_overrides or {})
    equipment = create_equipment(**equip_kwargs)
    if clock:
        set_clock(clock)
    member = create_active_member(plan["id"], **(member_overrides or {}))
    return plan, member, equipment


def setup_active_member_with_spray_room(plan_overrides=None, member_overrides=None,
                                        room_overrides=None, clock=None):
    """Active member + one SprayRoom. Returns (plan, member, room)."""
    plan_kwargs = {"includes_spray": True}
    plan_kwargs.update(plan_overrides or {})
    plan = create_plan(**plan_kwargs)
    room = create_spray_room(**(room_overrides or {}))
    if clock:
        set_clock(clock)
    member = create_active_member(plan["id"], **(member_overrides or {}))
    return plan, member, room


# ---------------------------------------------------------------------------
# Tier 1/3: session lifecycle shortcuts
# ---------------------------------------------------------------------------
def reserve_uv_session(member_id, equipment_id, start_at, requested_seconds=120,
                       booking_mode="RESERVATION"):
    """Reserve a UV session for a member. Returns the RESERVED Session."""
    payload = create_session_payload(
        member_id=member_id, kind="UV", booking_mode=booking_mode,
        equipment_id=equipment_id, start_at=start_at, requested_seconds=requested_seconds,
    )
    return get_success_data(api_client.create_session(payload, make_member_headers(member_id)))


def reserve_spray_session(member_id, spray_room_id, start_at, requested_seconds=300,
                          booking_mode="RESERVATION"):
    """Reserve a SPRAY session for a member. Returns the RESERVED Session."""
    payload = create_session_payload(
        member_id=member_id, kind="SPRAY", booking_mode=booking_mode,
        spray_room_id=spray_room_id, start_at=start_at, requested_seconds=requested_seconds,
    )
    payload.pop("equipment_id", None)
    return get_success_data(api_client.create_session(payload, make_member_headers(member_id)))


def complete_uv_session(member_id, equipment_id, start_at, requested_seconds=120):
    """Reserve -> start -> complete a UV session. Returns the COMPLETED Session.

    The caller must have set the clock so the cool-down and slot rules pass.
    """
    session = reserve_uv_session(member_id, equipment_id, start_at, requested_seconds)
    sid = session["id"]
    get_success_data(api_client.start_session(sid, FRONT_DESK))
    return get_success_data(api_client.complete_session(sid, FRONT_DESK))


def start_uv_session(member_id, equipment_id, start_at, requested_seconds=120):
    """Reserve -> start a UV session (leaves it IN_PROGRESS). Returns the Session."""
    session = reserve_uv_session(member_id, equipment_id, start_at, requested_seconds)
    sid = session["id"]
    return get_success_data(api_client.start_session(sid, FRONT_DESK))


# ---------------------------------------------------------------------------
# Tier 1: member lifecycle shortcuts
# ---------------------------------------------------------------------------
def freeze_member(member_id, expected_version):
    """Freeze an ACTIVE member. Returns the FROZEN Member."""
    return get_success_data(
        api_client.freeze_member(
            member_id, {"expected_member_version": expected_version}, make_member_headers(member_id)
        )
    )


def unfreeze_member(member_id, expected_version):
    """Unfreeze a FROZEN member. Returns the ACTIVE Member."""
    return get_success_data(
        api_client.unfreeze_member(
            member_id, {"expected_member_version": expected_version}, make_member_headers(member_id)
        )
    )


def cancel_member(member_id, expected_version):
    """Cancel a member. Returns the CANCELLED Member."""
    return get_success_data(
        api_client.cancel_member(
            member_id, {"expected_member_version": expected_version}, make_member_headers(member_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 4: credit / billing accumulation targeting
# ---------------------------------------------------------------------------
def setup_member_with_freeze_credit(monthly_fee_cents=6000, anchor="2026-06-01T00:00:00Z",
                                    freeze_at="2026-06-11T00:00:00Z", retail_discount_pct=None,
                                    unfreeze_after=True):
    """Active member whose account_credit_cents holds a freeze proration credit.

    Sets clock to `anchor`, activates (cycle_anchor_at = anchor), advances to
    `freeze_at`, freezes (minting credit). If unfreeze_after, immediately unfreezes
    back to ACTIVE so the member can transact. Returns (plan, member_after_op,
    credit_after_freeze) where member_after_op is FROZEN or ACTIVE accordingly.
    """
    plan_kwargs = {"monthly_fee_cents": monthly_fee_cents, "weekly_uv_session_cap": 0}
    if retail_discount_pct is not None:
        plan_kwargs["retail_discount_pct"] = retail_discount_pct
    plan = create_plan(**plan_kwargs)
    set_clock(anchor)
    activated = create_active_member(plan["id"])
    mid = activated["id"]
    set_clock(freeze_at)
    frozen = freeze_member(mid, activated["version"])
    credit_after_freeze = frozen["account_credit_cents"]
    if unfreeze_after:
        active = unfreeze_member(mid, frozen["version"])
        return plan, active, credit_after_freeze
    return plan, frozen, credit_after_freeze


def setup_suspended_member(monthly_fee_cents=3000, anchor="2026-06-01T00:00:00Z"):
    """Drive a member to billing_status SUSPENDED via grace-elapsed declined EFTs.

    anchor -> activate (cycle_anchor_at = anchor) -> advance to anchor+31d, DECLINED
    EFT (PAST_DUE) -> advance to anchor+38d (past 30+7 grace), DECLINED EFT
    (SUSPENDED). Returns (plan, member) with member.billing_status == SUSPENDED.
    """
    plan = create_plan(tier_code="BASIC", monthly_fee_cents=monthly_fee_cents,
                       weekly_uv_session_cap=0)
    set_clock(anchor)
    activated = create_active_member(plan["id"])
    mid = activated["id"]
    set_clock("2026-07-02T00:00:00Z")
    get_success_data(api_client.run_eft({"member_id": mid, "outcome": "DECLINED"}, BILLING))
    set_clock("2026-07-09T00:00:00Z")
    member = get_success_data(
        api_client.run_eft({"member_id": mid, "outcome": "DECLINED"}, BILLING)
    )
    return plan, member


def setup_member_for_upgrade(basic_fee=3000, premium_fee=8000, anchor="2026-06-01T00:00:00Z",
                             upgrade_at="2026-06-11T00:00:00Z", pin_outcome="SUCCEEDED"):
    """Active member on a BASIC plan, ready to upgrade to a PREMIUM plan.

    Returns (basic_plan, premium_plan, member). cycle_anchor_at == anchor; clock is
    left at upgrade_at; the next upgrade outcome is pinned to pin_outcome.
    """
    basic = create_plan(tier_code="BASIC", monthly_fee_cents=basic_fee, weekly_uv_session_cap=0)
    premium = create_plan(tier_code="PREMIUM", monthly_fee_cents=premium_fee, weekly_uv_session_cap=0)
    set_clock(anchor)
    member = create_active_member(basic["id"])
    if pin_outcome is not None:
        get_success_data(
            api_client.set_upgrade_outcome(
                {"member_id": member["id"], "outcome": pin_outcome}, BILLING
            )
        )
    set_clock(upgrade_at)
    return basic, premium, member


def setup_equipment_in_maintenance(start_a="2026-06-01T10:00:00Z",
                                   start_b="2026-06-02T10:00:00Z"):
    """Drive an Equipment unit to MAINTENANCE via two completed UV sessions
    (SERVICE_THRESHOLD=2). Returns (plan, member, equipment). The equipment's
    status is MAINTENANCE on return.
    """
    plan = create_plan(weekly_uv_session_cap=0)
    equipment = create_equipment(max_exposure_seconds=600, turnaround_seconds=600)
    set_clock(start_a)
    member = create_active_member(plan["id"])
    mid = member["id"]
    complete_uv_session(mid, equipment["id"], start_a)
    set_clock(start_b)
    complete_uv_session(mid, equipment["id"], start_b)
    equipment = get_success_data(api_client.get_equipment(equipment["id"], SALON_MANAGER))
    return plan, member, equipment


def add_consent(member_id, **overrides) -> dict:
    """Record a guardian consent for a (minor) member (FrontDeskStaff)."""
    return get_success_data(
        api_client.create_consent(member_id, create_consent_payload(**overrides), FRONT_DESK)
    )


def place_retail_order(member_id, lines) -> dict:
    """Place a retail order as the purchasing member. Returns the PAID order."""
    payload = create_retail_order_payload(member_id=member_id, lines=lines)
    return get_success_data(api_client.create_retail_order(payload, make_member_headers(member_id)))


def get_ledger() -> dict:
    """Read the singleton SalonLedger (SalonManager)."""
    return get_success_data(api_client.get_salon_ledger(SALON_MANAGER))
