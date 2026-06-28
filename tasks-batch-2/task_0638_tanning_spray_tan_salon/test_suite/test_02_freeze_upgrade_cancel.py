"""Freeze proration, upgrade proration, OCC, and freeze/cancel compensation.

Covers queue-B calculation, cross_cutting (OCC), and consistency_model corner
instances plus the compensating_invariant difficulty instance for the freeze
credit ledger reversal.
"""
from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    TEST_USERS,
    make_member_headers,
)
from test_helpers import fixtures as fx

BILLING = TEST_USERS["billing_system_headers"]
SALON_MANAGER = TEST_USERS["salon_manager_headers"]


def test_freeze_proration_credit_exact_value(api):
    """PRD §3.8: "The daily rate in cents is the plan's `monthly_fee_cents` divided
    by 30, rounded half up to whole cents. The elapsed whole days are the floor of
    the current logical instant minus `cycle_anchor_at`, expressed in days ...
    then clamped to lie between 0 and 30. The unused days are 30 minus the clamped
    elapsed days. The freeze proration credit is the daily rate multiplied by the
    unused days, an exact integer number of cents, and this exact amount is what is
    added both to the member's `account_credit_cents` and to the salon ledger's
    `deferred_revenue_cents`."

    Design: Corner/calculations/freeze_proration_credit_correct_value
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Prorate Member")
    fx.set_clock("2026-06-11T00:00:00Z")
    resp = api.freeze_member(
        member["id"], {"expected_member_version": member["version"]},
        make_member_headers(member["id"]),
    )
    data = validate_success(resp)
    # daily = round_half_up(6000/30)=200; elapsed=10 -> unused=20 -> 200*20=4000
    assert data["account_credit_cents"] == 4000, (
        f"expected 4000 freeze credit, got {data['account_credit_cents']}"
    )
    assert data["status"] == "FROZEN"


def test_freeze_credit_visible_in_same_response(api):
    """PRD §3.3: "On freeze, `frozen_at` is set to the current logical instant, a
    freeze proration credit (computed in Section 3.8) is added to the member's
    `account_credit_cents`, the same credit amount is added to the salon ledger's
    `deferred_revenue_cents`, and `Member.version` is incremented by one."

    Design: Corner/consistency_model/freeze_credit_visible_in_same_response
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Immediate Member")
    fx.set_clock("2026-06-11T00:00:00Z")
    resp = api.freeze_member(
        member["id"], {"expected_member_version": member["version"]},
        make_member_headers(member["id"]),
    )
    data = validate_success(resp)
    assert data["account_credit_cents"] == 4000
    assert data["status"] == "FROZEN"


def test_upgrade_proration_charge_sets_new_plan(api):
    """PRD §3.8: "The upgrade charge in cents is the difference of the two daily
    rates (new daily minus old daily) multiplied by the remaining days, an exact
    integer of cents, billed as the `UPGRADE` payment."
    PRD §3.3: "when the charge result is `SUCCEEDED`, the member's `plan_id` is set
    to `new_plan_id`."

    Design: Corner/calculations/upgrade_proration_charge_correct
    """
    basic, premium, member = fx.setup_member_for_upgrade(
        basic_fee=3000, premium_fee=8000,
        anchor="2026-06-01T00:00:00Z", upgrade_at="2026-06-11T00:00:00Z",
        pin_outcome="SUCCEEDED",
    )
    resp = api.upgrade_member(
        member["id"],
        {"new_plan_id": premium["id"], "expected_member_version": member["version"]},
        make_member_headers(member["id"]),
    )
    data = validate_success(resp, expected_status=200)
    assert data["plan_id"] == premium["id"], (
        f"plan_id must become the PREMIUM plan, got {data['plan_id']}"
    )


def test_upgrade_to_lower_fee_rejected(api):
    """PRD §3.8: "An upgrade is permitted only when the new plan's
    `monthly_fee_cents` is strictly greater than the current plan's
    `monthly_fee_cents`; a lateral or lower fee is rejected with
    `ERR_NOT_AN_UPGRADE`."

    Design: Corner/calculations/upgrade_to_lower_fee_rejected
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    premium = fx.create_plan(tier_code="PREMIUM", monthly_fee_cents=8000, weekly_uv_session_cap=0)
    basic = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    member = fx.create_active_member(premium["id"], full_name="Down Member")
    resp = api.upgrade_member(
        member["id"],
        {"new_plan_id": basic["id"], "expected_member_version": member["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_AN_UPGRADE.value, expected_status=409)


def test_upgrade_stale_member_version_rejected(api):
    """PRD §2.9: "If the supplied value does not equal the member's current
    `version`, the request is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412),
    and no state change occurs."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_member_version_on_upgrade
    """
    basic = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    premium = fx.create_plan(tier_code="PREMIUM", monthly_fee_cents=8000, weekly_uv_session_cap=0)
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_active_member(basic["id"], full_name="OCC Member")
    fx.set_clock("2026-06-11T00:00:00Z")
    stale_version = member["version"]
    frozen = fx.freeze_member(member["id"], stale_version)
    fx.unfreeze_member(member["id"], frozen["version"])  # version now bumped twice
    resp = api.upgrade_member(
        member["id"],
        {"new_plan_id": premium["id"], "expected_member_version": stale_version},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_MEMBER_VERSION.value, expected_status=412)


def test_upgrade_with_current_version_succeeds(api):
    """PRD §2.9: "The freeze, unfreeze, upgrade, and cancel operations each take
    `expected_member_version` as a non-optional input. If the supplied value does
    not equal the member's current `version`, the request is rejected with
    `ERR_STALE_MEMBER_VERSION` (HTTP 412), and no state change occurs."
    PRD §3.3: "Each upgrade increments `Member.version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_upgrade_succeeds
    """
    basic, premium, member = fx.setup_member_for_upgrade(
        basic_fee=3000, premium_fee=8000,
        anchor="2026-06-01T00:00:00Z", upgrade_at="2026-06-11T00:00:00Z",
        pin_outcome="SUCCEEDED",
    )
    resp = api.upgrade_member(
        member["id"],
        {"new_plan_id": premium["id"], "expected_member_version": member["version"]},
        make_member_headers(member["id"]),
    )
    data = validate_success(resp, expected_status=200)
    assert data["plan_id"] == premium["id"]
    assert data["version"] == member["version"] + 1, (
        f"version must increment by 1, was {member['version']}, now {data['version']}"
    )


def test_freeze_then_cancel_restores_account_credit(api):
    """PRD §3.3: "If — and only if — the member is `FROZEN` at cancel time, the
    cancellation runs a compensating reversal of the freeze: the freeze proration
    credit recorded at freeze is subtracted from the member's `account_credit_cents`,
    and the same amount is subtracted from the salon ledger's `deferred_revenue_cents`,
    restoring the deferred-revenue invariant."

    Design: Difficulty/compensating_invariant/freeze_then_cancel_restores_deferred_revenue
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Conserve Member")
    fx.set_clock("2026-06-11T00:00:00Z")
    frozen = fx.freeze_member(member["id"], member["version"])
    assert frozen["account_credit_cents"] == 4000
    resp = api.cancel_member(
        member["id"], {"expected_member_version": frozen["version"]},
        make_member_headers(member["id"]),
    )
    data = validate_success(resp)
    assert data["status"] == "CANCELLED"
    assert data["account_credit_cents"] == 0, (
        f"freeze credit must be reversed to 0, got {data['account_credit_cents']}"
    )


def test_freeze_then_cancel_restores_ledger_deferred_revenue(api):
    """PRD §2.10: "the salon's `deferred_revenue_cents` rises by exactly the same
    amount that a freeze adds to a member's `account_credit_cents`, and falls by
    exactly that amount when the credit is drawn down or a cancellation reverses it."

    Design: Difficulty/compensating_invariant/freeze_then_cancel_restores_deferred_revenue
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Conserve Member 2")
    fx.set_clock("2026-06-11T00:00:00Z")
    frozen = fx.freeze_member(member["id"], member["version"])
    ledger_after_freeze = fx.get_ledger()
    assert ledger_after_freeze["deferred_revenue_cents"] == 4000
    fx.cancel_member(member["id"], frozen["version"])
    ledger_after_cancel = fx.get_ledger()
    assert ledger_after_cancel["deferred_revenue_cents"] == 0, (
        "deferred_revenue_cents must return to 0 after cancel-while-frozen, got "
        f"{ledger_after_cancel['deferred_revenue_cents']}"
    )
