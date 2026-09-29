"""Re-entrant order review and the two independently advancing agency axes."""

from test_helpers import (
    AgreementStatus,
    ApiErrorId,
    COMPLIANCE_REVIEWER_ID,
    EligibilityPosture,
    FormulaVariant,
    OrderStatus,
    SECOND_COMPLIANCE_REVIEWER_ID,
    TrainingStatus,
    assert_agency_axes,
    assert_instant,
    assert_pounds,
    fixtures as fx,
    make_compliance_reviewer_headers,
    make_second_compliance_reviewer_headers,
    validate_error,
)

PEACH_CODE = "CANNED_PEACHES"


def _order_awaiting_first_review(api):
    """One 10-case peach line, submitted once inside an open window."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area One", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency One",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    agency = fx.make_agency_eligible(api, agency["id"])
    peaches = fx.create_canned_peaches(api, entitlement_value_cents_per_case=1800)
    warehouse = fx.create_warehouse(api, name="WH North")
    fx.create_posted_lot(
        api,
        peaches["id"],
        warehouse["id"],
        federal_lot_code="FL-P-001",
        cases_received=100,
        pack_date="2026-05-01",
        best_by_date="2028-05-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27REV",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[PEACH_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    fx.add_line(api, order["id"], agency["id"], peaches["id"], 10)
    fx.submit_order(api, order["id"], agency["id"])
    return {
        "agency": agency,
        "cycle": cycle,
        "commodity": peaches,
        "order": order,
    }


def _resubmitted_after_revision(api):
    """The same order returned by rev-1, extended by a second line and resubmitted."""
    env = _order_awaiting_first_review(api)
    fx.return_for_revision(api, env["order"]["id"], make_compliance_reviewer_headers())
    fx.add_line(
        api, env["order"]["id"], env["agency"]["id"], env["commodity"]["id"], 5
    )
    fx.submit_order(api, env["order"]["id"], env["agency"]["id"])
    return env


def test_01_a_returned_order_re_enters_draft_and_records_the_returning_reviewer(api):
    """PRD §3.6: "The return increases `revision_count` by one, writes the acting
    reviewer's `X-User-ID` into `last_returned_by_user_id`, and increments the
    order's `version`."

    Design: Difficulty/non_linear_state_machine/order_revision_loop_returns_to_draft_then_blocks_returning_reviewer
    """
    env = _order_awaiting_first_review(api)

    order = fx.return_for_revision(
        api, env["order"]["id"], make_compliance_reviewer_headers()
    )

    assert order["status"] == OrderStatus.DRAFT, (
        f"a returned order must sit in DRAFT but got {order['status']}"
    )
    assert order["revision_count"] == 1, (
        f"revision_count expected 1 but got {order['revision_count']}"
    )
    assert order["last_returned_by_user_id"] == COMPLIANCE_REVIEWER_ID, (
        "last_returned_by_user_id expected "
        f"{COMPLIANCE_REVIEWER_ID} but got {order['last_returned_by_user_id']}"
    )


def test_02_the_returning_reviewer_cannot_approve_the_resubmission(api):
    """PRD §3.6: "A reviewer attempting to approve the very resubmission they
    themselves sent back is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/non_linear_state_machine/order_revision_loop_returns_to_draft_then_blocks_returning_reviewer
    """
    env = _resubmitted_after_revision(api)

    response = api.approve_order(
        env["order"]["id"], headers=make_compliance_reviewer_headers(), payload={}
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    order = fx.read_order(api, env["order"]["id"])
    assert order["status"] == OrderStatus.SUBMITTED, (
        f"the refused order must stay SUBMITTED but got {order['status']}"
    )
    assert order["approved_by_user_id"] is None, (
        f"approved_by_user_id must stay null but got {order['approved_by_user_id']}"
    )


def test_03_a_different_reviewer_approves_the_second_pass_over_both_lines(api):
    """PRD §3.6: "When a reviewer approves an order, either the order has never been
    returned — `revision_count` is 0 — or the acting `X-User-ID` must differ from
    `last_returned_by_user_id`." PRD §3.6: "The order's `total_pounds` is the sum of
    the per-line rounded `line_pounds` values, and its `total_pallets` is the sum of
    the per-line ceilinged `line_pallets` values."

    Design: Difficulty/non_linear_state_machine/order_revision_loop_returns_to_draft_then_blocks_returning_reviewer
    """
    env = _resubmitted_after_revision(api)

    order = fx.approve_order(
        api, env["order"]["id"], make_second_compliance_reviewer_headers()
    )

    assert order["status"] == OrderStatus.APPROVED, (
        f"status expected APPROVED but got {order['status']}"
    )
    assert order["revision_count"] == 1, (
        f"revision_count expected 1 but got {order['revision_count']}"
    )
    assert order["last_returned_by_user_id"] == COMPLIANCE_REVIEWER_ID, (
        "last_returned_by_user_id expected "
        f"{COMPLIANCE_REVIEWER_ID} but got {order['last_returned_by_user_id']}"
    )
    assert order["approved_by_user_id"] == SECOND_COMPLIANCE_REVIEWER_ID, (
        "approved_by_user_id expected "
        f"{SECOND_COMPLIANCE_REVIEWER_ID} but got {order['approved_by_user_id']}"
    )
    assert order["line_count"] == 2, f"line_count expected 2 but got {order['line_count']}"
    assert order["total_cases_requested"] == 15, (
        f"total_cases_requested expected 15 but got {order['total_cases_requested']}"
    )
    assert order["total_cases_approved"] == 15, (
        f"total_cases_approved expected 15 but got {order['total_cases_approved']}"
    )
    assert_pounds(order["total_pounds"], 365.63, "total_pounds")
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_committed"] == 15, (
        f"cases_committed expected 15 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_remaining"] == 986, (
        f"cases_remaining expected 986 but got {allocation['cases_remaining']}"
    )


def _agency_with_long_agreement(api):
    """Training expiring 2027-07-01 under an agreement that runs to 2028-06-30."""
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area One", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency One",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.record_training(api, agency["id"], completed_at="2026-07-01T00:00:00Z")
    fx.renew_agreement(api, agency["id"], "2026-07-01", "2028-06-30")
    return {"area": area, "agency": fx.read_agency(api, agency["id"])}


def test_04_both_axes_start_green_and_the_join_reads_eligible(api):
    """PRD §3.2: "If `agreement_status` is `ACTIVE` and `training_status` is
    `CURRENT`, the posture is `ELIGIBLE`." PRD §3.2: "Recording a training writes
    `last_training_completed_at` from `completed_at` and sets `training_expires_at`
    to one year — 365 days — after that instant, then recomputes the posture."

    Design: Difficulty/non_linear_state_machine/agency_agreement_and_training_axes_advance_independently
    """
    env = _agency_with_long_agreement(api)

    agency = env["agency"]

    assert_agency_axes(
        agency,
        AgreementStatus.ACTIVE,
        TrainingStatus.CURRENT,
        EligibilityPosture.ELIGIBLE,
    )
    assert_instant(
        agency["training_expires_at"], "2027-07-01T00:00:00Z", "training_expires_at"
    )
    assert agency["renewal_count"] == 1, (
        f"renewal_count expected 1 but got {agency['renewal_count']}"
    )


def test_05_the_training_axis_lapses_alone_and_drops_the_posture_to_probation(api):
    """PRD §3.2: "A training in `CURRENT` moves to `LAPSED` once the current instant
    reaches `training_expires_at`." PRD §3.2: "If `agreement_status` is `ACTIVE` and
    `training_status` is `LAPSED`, the posture is `PROBATION`."

    Design: Difficulty/non_linear_state_machine/agency_agreement_and_training_axes_advance_independently
    """
    env = _agency_with_long_agreement(api)
    fx.set_clock(api, "2027-07-01T00:00:00Z")

    fx.run_compliance_sweep(api)

    agency = fx.read_agency(api, env["agency"]["id"])
    assert_agency_axes(
        agency,
        AgreementStatus.ACTIVE,
        TrainingStatus.LAPSED,
        EligibilityPosture.PROBATION,
    )
    area = fx.read_service_area(api, env["area"]["id"])
    assert area["eligible_agency_count"] == 0, (
        f"eligible_agency_count expected 0 but got {area['eligible_agency_count']}"
    )


def test_06_a_refresher_training_restores_eligibility_without_touching_the_agreement(api):
    """PRD §3.2: "`LAPSED → CURRENT` is re-training after expiry. It requires
    `completed_at` at or before the current instant, refreshes both timestamps, and
    recomputes the posture — an agency whose agreement is still `ACTIVE` moves from
    `PROBATION` back to `ELIGIBLE` in the same write." PRD §3.2: "Immediately after
    any posture write, the `eligible_agency_count` of that agency's service area is
    recomputed as the number of agencies in that area whose posture is `ELIGIBLE`."

    Design: Difficulty/non_linear_state_machine/agency_agreement_and_training_axes_advance_independently
    """
    env = _agency_with_long_agreement(api)
    fx.set_clock(api, "2027-07-01T00:00:00Z")
    fx.run_compliance_sweep(api)

    fx.record_training(
        api, env["agency"]["id"], completed_at="2027-07-01T00:00:00Z", attendee_count=6
    )

    agency = fx.read_agency(api, env["agency"]["id"])
    assert_agency_axes(
        agency,
        AgreementStatus.ACTIVE,
        TrainingStatus.CURRENT,
        EligibilityPosture.ELIGIBLE,
    )
    assert_instant(
        agency["training_expires_at"], "2028-06-30T00:00:00Z", "training_expires_at"
    )
    assert agency["renewal_count"] == 1, (
        f"renewal_count must stay 1 but got {agency['renewal_count']}"
    )
    area = fx.read_service_area(api, env["area"]["id"])
    assert area["eligible_agency_count"] == 1, (
        f"eligible_agency_count expected 1 but got {area['eligible_agency_count']}"
    )
