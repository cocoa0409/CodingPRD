"""Recurring EFT billing, suspension, ledger reads, and a booking-priority pair.

Covers queue-B validation and endpoint corner instances around the billing
dimension plus the priority_pair difficulty instance where booking eligibility
(SUSPENDED) pre-empts the dose ceiling check.
"""
from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    create_session_payload,
)
from test_helpers import fixtures as fx

BILLING = TEST_USERS["billing_system_headers"]
SALON_MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_eft_run_before_cycle_due_rejected(api):
    """PRD §3.2: "A normal due-date run also requires that the logical clock has
    reached or passed `cycle_anchor_at` plus 30 days; if the cycle is not yet due,
    the run is rejected with `ERR_CYCLE_NOT_DUE`."

    Design: Corner/validations/cycle_not_due_rejects_eft
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="NotDue Member")
    fx.set_clock("2026-06-15T00:00:00Z")
    resp = api.run_eft({"member_id": member["id"], "outcome": "SUCCEEDED"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_DUE.value, expected_status=409)
    after = validate_success(api.get_member(member["id"], FRONT_DESK))
    assert after["billing_status"] == "CURRENT"


def test_eft_success_advances_cycle_and_ledger(api):
    """PRD §3.2: "On a `SUCCEEDED` charge while `CURRENT`, the member stays
    `CURRENT`: a `Payment` of `kind` `EFT_DUES` with `outcome` `SUCCEEDED` and
    `amount_cents` equal to the plan's `monthly_fee_cents` is created,
    `cycle_anchor_at` advances by 30 days, and the ledger's `collected_dues_cents`
    rises by `monthly_fee_cents`."

    Design: Corner/endpoints/eft_success_advances_cycle_and_ledger
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="EFT Member")
    fx.set_clock("2026-07-02T00:00:00Z")
    resp = api.run_eft({"member_id": member["id"], "outcome": "SUCCEEDED"}, BILLING)
    data = validate_success(resp)
    assert data["billing_status"] == "CURRENT"
    # First dues (3000 at activation) + this run (3000) == 6000 collected.
    ledger = fx.get_ledger()
    assert ledger["collected_dues_cents"] == 6000, (
        f"expected collected_dues_cents 6000, got {ledger['collected_dues_cents']}"
    )


def test_payments_filtered_by_member_id(api):
    """PRD §3.10: "Payments are immutable records and can be listed or fetched for
    audit, filtered by `member_id` and by `retail_order_id`, which provides reverse
    reachability from a member or a retail order to its charges."

    Design: Corner/endpoints/payments_filtered_by_member_id
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    member = fx.register_member(plan["id"], full_name="Pay Member")
    api.charge_first_dues({"member_id": member["id"], "outcome": "SUCCEEDED"}, BILLING)
    resp = api.list_payments(BILLING, params={"member_id": member["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected exactly 1 payment, got {meta['total_count']}"
    assert all(p["member_id"] == member["id"] for p in data)


def test_salon_ledger_singleton_starts_at_zero(api):
    """PRD §2.10: "The ledger tracks three running totals, all in cents:
    `deferred_revenue_cents`, the outstanding freeze credits the salon owes to
    members; `collected_dues_cents`, the cumulative successfully collected EFT dues;
    and `collected_retail_cents`, the cumulative net retail revenue."

    Design: Corner/endpoints/salon_ledger_singleton_read
    """
    ledger = validate_success(api.get_salon_ledger(SALON_MANAGER))
    assert ledger["deferred_revenue_cents"] == 0
    assert ledger["collected_dues_cents"] == 0
    assert ledger["collected_retail_cents"] == 0


def test_suspended_member_cannot_book_pre_empts_dose_check(api):
    """PRD §3.4: "First comes member booking eligibility: the booking member must be
    `ACTIVE` and must not have `billing_status` of `SUSPENDED`; a suspended or
    non-active member cannot book and is rejected with `ERR_MEMBER_NOT_BOOKABLE`.
    The remaining checks apply only to UV bookings and run in this order: skin-type
    prohibition, minor consent, minor frequency, adult frequency, cool-down, dose
    ceiling, and finally the equipment slot-conflict check."

    Design: Difficulty/priority_pair_validation_conflict/not_bookable_beats_dose_limit
    """
    plan, member = fx.setup_suspended_member(monthly_fee_cents=3000, anchor="2026-06-01T00:00:00Z")
    assert member["billing_status"] == "SUSPENDED"
    equipment = fx.create_equipment(max_exposure_seconds=600, turnaround_seconds=600)
    # requested_seconds 999 would breach the dose ceiling (180) for skin IV count 0,
    # but eligibility runs first so ERR_MEMBER_NOT_BOOKABLE wins.
    payload = create_session_payload(
        member_id=member["id"], kind="UV", booking_mode="WALK_IN",
        equipment_id=equipment["id"], start_at="2026-07-09T10:00:00Z", requested_seconds=999,
    )
    resp = api.create_session(payload, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_BOOKABLE.value, expected_status=409)


def test_suspended_member_not_bookable_on_minimal_dose_too(api):
    """PRD §3.4: "First comes member booking eligibility: the booking member must be
    `ACTIVE` and must not have `billing_status` of `SUSPENDED`; a suspended or
    non-active member cannot book and is rejected with `ERR_MEMBER_NOT_BOOKABLE`."

    Design: Difficulty/priority_pair_validation_conflict/not_bookable_beats_dose_limit
    """
    plan, member = fx.setup_suspended_member(monthly_fee_cents=3000, anchor="2026-06-01T00:00:00Z")
    equipment = fx.create_equipment(max_exposure_seconds=600, turnaround_seconds=600)
    payload = create_session_payload(
        member_id=member["id"], kind="UV", booking_mode="WALK_IN",
        equipment_id=equipment["id"], start_at="2026-07-09T10:00:00Z", requested_seconds=60,
    )
    resp = api.create_session(payload, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_BOOKABLE.value, expected_status=409)
