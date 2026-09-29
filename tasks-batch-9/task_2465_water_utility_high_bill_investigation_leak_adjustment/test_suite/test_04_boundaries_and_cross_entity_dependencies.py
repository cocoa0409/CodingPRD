"""Threshold precision and cross-entity gating in the high-bill workflow.

Two concerns share this module. The first is the exact edge of three published
thresholds: the anomaly screen's inclusive 2.000 ratio carried to three decimal
places, the bench verdict's strict 101.50 accuracy bound carried to two decimal
places, and the past-due comparison's strict 5,000-cent bound carried to a
single cent. The second is the way one entity's state decides what may happen
on another: a meter test request gating a meter-error determination, an open
investigation barring a shutoff execution, and a posted leak credit moving the
figure an instalment plan is allowed to finance.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    CSR_HEADERS,
    SUPERVISOR_HEADERS,
    TECHNICIAN_HEADERS,
    ApiErrorId,
    assertions,
    constants,
    factories as f,
    fixtures,
)

TOLERANCE = 1e-9


def _num(value):
    """Read a numeric response field as a float whatever its JSON encoding."""
    assert value is not None, "expected a numeric field, got null"
    return float(value)


# ---------------------------------------------------------------------------
# Fixture builders shared by the tests below
# ---------------------------------------------------------------------------
def _anomaly_boundary_calendar(api):
    """Two candidate bills straddling the anomaly ratio on one 4000-gal baseline.

    Three settled SUMMER history bills of 4000 gallons each pin the baseline at
    4000. A fifth SUMMER period carries the second candidate so that both
    candidates can be generated against that same baseline, and the earlier
    candidate is deliberately left in ``DRAFT`` so it cannot join the pool.
    """
    ctx = fixtures.metered_account(api)
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    august = fixtures.create_billing_period(
        api,
        period_code="2026-08",
        start_date="2026-08-01",
        end_date="2026-08-31",
        season="SUMMER",
        rebilling_deadline_date="2027-02-28",
    )
    meter_id = ctx["meter_id"]
    register = constants.INITIAL_REGISTER_VALUE
    fixtures.post_reading(api, meter_id, constants.HISTORY_READ_DATES[0], register)
    for index, period_id in enumerate(ctx["calendar"]["history_ids"]):
        register += constants.HISTORY_CONSUMPTION_GALLONS
        fixtures.post_reading(
            api, meter_id, constants.HISTORY_READ_DATES[index + 1], register
        )
        fixtures.generate_and_issue_bill(api, ctx["account_id"], period_id, meter_id)

    fixtures.post_reading(api, meter_id, "2026-07-31", register + 7996)
    fixtures.post_reading(api, meter_id, "2026-08-31", register + 7996 + 8000)

    below = fixtures.generate_bill(
        api, ctx["account_id"], ctx["calendar"]["target_id"], meter_id
    )
    at_threshold = fixtures.generate_bill(
        api, ctx["account_id"], august["id"], meter_id
    )
    ctx.update(
        {
            "below_bill": below,
            "below_bill_id": below["id"],
            "at_bill": at_threshold,
            "at_bill_id": at_threshold["id"],
        }
    )
    return ctx


def _single_bill_past_due_account(api):
    """One 4000-gallon issued bill of 5210 cents, with a shutoff scheduled.

    The balance sits just above the past-due threshold, so the account is
    delinquent and a supervisor can arm the ten-day notice.
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    period = fixtures.create_billing_period(api, **constants.STANDARD_PERIODS[0])
    account = fixtures.create_account(api, schedule["id"])
    meter = fixtures.create_master_meter(
        api, account["id"], initial_register_value=constants.INITIAL_REGISTER_VALUE
    )
    fixtures.post_reading(
        api, meter["id"], "2025-05-31", constants.INITIAL_REGISTER_VALUE
    )
    fixtures.post_reading(
        api, meter["id"], "2025-06-30", constants.INITIAL_REGISTER_VALUE + 4000
    )
    bill = fixtures.generate_and_issue_bill(
        api, account["id"], period["id"], meter["id"]
    )
    account = validate_success(api.schedule_shutoff(account["id"], SUPERVISOR_HEADERS))
    return {
        "account_id": account["id"],
        "account": account,
        "bill_id": bill["id"],
        "meter_id": meter["id"],
    }


def _investigation_then_scheduled_shutoff(api):
    """A delinquent account whose hold was already outstanding when scheduled.

    The 12000-gallon disputed bill leaves the balance at 30887 cents, the
    investigation is opened first so the hold count is already 1, and the clock
    is then moved past the notice date.
    """
    ctx = fixtures.baselined_bill(api, target_gallons=12000)
    investigation = fixtures.open_investigation(api, ctx["bill_id"], CSR_HEADERS)
    account = validate_success(
        api.schedule_shutoff(ctx["account_id"], SUPERVISOR_HEADERS)
    )
    fixtures.set_clock(api, "2026-08-12T00:00:00Z")
    ctx.update(
        {
            "investigation": investigation,
            "investigation_id": investigation["id"],
            "account": account,
        }
    )
    return ctx


# ===========================================================================
# The anomaly screen's inclusive 2.000 ratio, carried to three decimals
# ===========================================================================
def test_consumption_rounding_to_a_ratio_of_one_point_nine_nine_nine_is_not_flagged(api):
    """PRD §3.2: "Otherwise `anomaly_ratio` is `consumption_gallons` divided by `seasonal_baseline_gallons`, rounded half up to three decimal places, and `anomaly_flag` is true when that rounded ratio is greater than or equal to 2.000."

    PRD §3.2: "The boundary is included: a bill running at exactly twice its baseline is flagged, while a ratio that rounds to 1.999 is not."

    Design: Difficulty/boundary_precision_check/boundary_anomaly_ratio_inclusive_at_two_point_zero_three_decimals
    """
    ctx = _anomaly_boundary_calendar(api)

    bill = fixtures.fetch_bill(api, ctx["below_bill_id"])
    water, sewer, total = constants.PINNED_CHARGES[("SUMMER", 7996)]
    assertions.assert_fields(
        bill,
        consumption_gallons=7996,
        seasonal_baseline_gallons=4000,
        baseline_sample_count=3,
        anomaly_flag=False,
        billing_status="DRAFT",
    )
    assert _num(bill["anomaly_ratio"]) == pytest.approx(1.999, abs=TOLERANCE)
    assertions.assert_bill_charges(
        bill,
        water_charge_cents=water,
        sewer_charge_cents=sewer,
        total_charge_cents=total,
    )


def test_consumption_at_exactly_twice_the_baseline_is_flagged_as_an_anomaly(api):
    """PRD §3.2: "Otherwise `anomaly_ratio` is `consumption_gallons` divided by `seasonal_baseline_gallons`, rounded half up to three decimal places, and `anomaly_flag` is true when that rounded ratio is greater than or equal to 2.000."

    PRD §3.2: "The boundary is included: a bill running at exactly twice its baseline is flagged, while a ratio that rounds to 1.999 is not."

    Design: Difficulty/boundary_precision_check/boundary_anomaly_ratio_inclusive_at_two_point_zero_three_decimals
    """
    ctx = _anomaly_boundary_calendar(api)

    bill = fixtures.fetch_bill(api, ctx["at_bill_id"])
    water, sewer, total = constants.PINNED_CHARGES[("SUMMER", 8000)]
    assertions.assert_fields(
        bill,
        consumption_gallons=8000,
        seasonal_baseline_gallons=4000,
        baseline_sample_count=3,
        anomaly_flag=True,
        billing_status="DRAFT",
    )
    assert _num(bill["anomaly_ratio"]) == pytest.approx(2.000, abs=TOLERANCE)
    assertions.assert_bill_charges(
        bill,
        water_charge_cents=water,
        sewer_charge_cents=sewer,
        total_charge_cents=total,
    )


def test_the_draft_candidate_bill_never_enters_the_later_baseline_pool(api):
    """PRD §3.2: "Bills in `DRAFT`, `UNDER_INVESTIGATION`, `REBILL_PENDING` or `REBILLED` never qualify, and neither do anomaly-flagged or estimated bills — the baseline must be built from settled, actually-read, ordinary periods."

    PRD §3.2: "A newly generated bill sits in `DRAFT` with `rebill_of_bill_id` null and writes nothing to the ledger."

    Design: Difficulty/boundary_precision_check/boundary_anomaly_ratio_inclusive_at_two_point_zero_three_decimals
    """
    ctx = _anomaly_boundary_calendar(api)

    below = fixtures.fetch_bill(api, ctx["below_bill_id"])
    at_threshold = fixtures.fetch_bill(api, ctx["at_bill_id"])
    assertions.assert_fields(below, billing_status="DRAFT")
    # The 7996-gallon candidate is still DRAFT, so the later baseline stays at
    # the mean of the three settled 4000-gallon periods rather than rising.
    assertions.assert_fields(
        at_threshold, seasonal_baseline_gallons=4000, baseline_sample_count=3
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(account, balance_cents=3 * 5210)
    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assert len(entries) == 3, f"only the three issued bills reach the ledger: {entries}"
    assertions.assert_balance_is_ledger_sum(account, entries)


# ===========================================================================
# The bench verdict's strict 101.50 bound, carried to two decimals
# ===========================================================================
def test_bench_accuracy_just_below_the_fast_bound_closes_the_request_as_a_pass(api):
    """PRD §3.4: "`bench_result` classifies the already-rounded `accuracy_pct` with two strict comparisons: it is `FAST` when `accuracy_pct` is strictly greater than 101.50, `SLOW` when `accuracy_pct` is strictly less than 98.50, and `PASS` when it lies at or between those two bounds."

    PRD §3.4: "In all cases the meter's `correction_factor` is one hundred divided by `accuracy_pct`, rounded half up to six decimal places."

    Design: Difficulty/boundary_precision_check/boundary_bench_accuracy_strict_greater_than_fast_threshold_101_50
    """
    ctx = fixtures.bench_closed_case(
        api, 101.49, 101.49, 101.49, requested_by_kind="UTILITY"
    )

    request = ctx["test_request"]
    assertions.assert_fields(
        request,
        accuracy_method="AWWA_WEIGHTED",
        bench_result="PASS",
        status="CLOSED_PASS",
    )
    assert _num(request["accuracy_pct"]) == pytest.approx(101.49, abs=TOLERANCE)

    meter = fixtures.fetch_meter(api, ctx["meter_id"])
    assertions.assert_fields(meter, accuracy_status="VERIFIED_ACCURATE")
    assert _num(meter["correction_factor"]) == pytest.approx(0.985319, abs=TOLERANCE)


def test_bench_accuracy_exactly_on_the_fast_bound_closes_the_request_as_a_pass(api):
    """PRD §3.4: "A composite landing on exactly 101.50 is therefore a pass, not a fast meter."

    PRD §3.4: "A meter of 2.0 inches or smaller is graded `AWWA_WEIGHTED`, where `accuracy_pct` is `low_flow_pct` multiplied by fifteen hundredths, plus `mid_flow_pct` multiplied by seventy hundredths, plus `high_flow_pct` multiplied by fifteen hundredths, rounded half up to two decimal places — a weighting that deliberately dominates the composite with mid-flow behaviour."

    Design: Difficulty/boundary_precision_check/boundary_bench_accuracy_strict_greater_than_fast_threshold_101_50
    """
    ctx = fixtures.bench_closed_case(
        api, 101.50, 101.50, 101.50, requested_by_kind="UTILITY"
    )

    request = ctx["test_request"]
    assertions.assert_fields(
        request,
        accuracy_method="AWWA_WEIGHTED",
        bench_result="PASS",
        status="CLOSED_PASS",
    )
    assert _num(request["accuracy_pct"]) == pytest.approx(101.50, abs=TOLERANCE)

    meter = fixtures.fetch_meter(api, ctx["meter_id"])
    assertions.assert_fields(meter, accuracy_status="VERIFIED_ACCURATE")
    assert _num(meter["correction_factor"]) == pytest.approx(0.985222, abs=TOLERANCE)

    # A pass restates nothing: the latest live read stands and the bill keeps
    # the consumption it was generated with.
    target_read = validate_success(
        api.get_meter_reading(ctx["target_read_id"], TECHNICIAN_HEADERS)
    )
    assert target_read["superseded_by_reading_id"] is None
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(
        bill, billing_status="UNDER_INVESTIGATION", consumption_gallons=41000
    )


def test_bench_accuracy_one_hundredth_above_the_fast_bound_closes_fast_and_restates(api):
    """PRD §3.4: "`bench_result` classifies the already-rounded `accuracy_pct` with two strict comparisons: it is `FAST` when `accuracy_pct` is strictly greater than 101.50, `SLOW` when `accuracy_pct` is strictly less than 98.50, and `PASS` when it lies at or between those two bounds."

    PRD §3.4: "**Link three**, caused by link two: the bill whose period contains the corrected `read_date` recomputes `consumption_gallons` and every charge field and moves to `REBILL_PENDING`."

    Design: Difficulty/boundary_precision_check/boundary_bench_accuracy_strict_greater_than_fast_threshold_101_50
    """
    ctx = fixtures.bench_closed_case(
        api, 101.51, 101.51, 101.51, requested_by_kind="UTILITY"
    )

    request = ctx["test_request"]
    assertions.assert_fields(
        request,
        accuracy_method="AWWA_WEIGHTED",
        bench_result="FAST",
        status="CLOSED_FAST",
    )
    assert _num(request["accuracy_pct"]) == pytest.approx(101.51, abs=TOLERANCE)

    meter = fixtures.fetch_meter(api, ctx["meter_id"])
    assertions.assert_fields(meter, accuracy_status="FAILED_FAST")
    assert _num(meter["correction_factor"]) == pytest.approx(0.985125, abs=TOLERANCE)

    # One hundredth of a percentage point is the difference between no cascade
    # and the full correction cascade.
    target_read = validate_success(
        api.get_meter_reading(ctx["target_read_id"], TECHNICIAN_HEADERS)
    )
    assert target_read["superseded_by_reading_id"] is not None

    live = fixtures.live_readings(api, ctx["meter_id"])
    corrected = [row for row in live if row["read_type"] == "CORRECTED"]
    assert len(corrected) == 1, f"expected exactly one corrected live read: {live}"
    assertions.assert_fields(
        corrected[0],
        read_date="2026-07-31",
        reading_value=112000 + 40390,
        consumption_since_prior_gallons=40390,
    )

    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(
        bill, billing_status="REBILL_PENDING", consumption_gallons=40390
    )


# ===========================================================================
# The past-due comparison's strict 5,000-cent bound, at single-cent granularity
# ===========================================================================
def test_balance_one_cent_above_the_threshold_stays_past_due_and_scheduled(api):
    """PRD §2.9: "It is evaluated as a strict precedence chain in which the first matching clause wins: if any arrangement on the account is `DEFAULTED`, the status is `ARRANGEMENT_DEFAULTED`; otherwise if any arrangement on the account is `ACTIVE`, the status is `IN_ARRANGEMENT`; otherwise if `balance_cents` is strictly greater than 5,000 cents (fifty dollars), the status is `PAST_DUE`; otherwise it is `CURRENT`."

    Design: Difficulty/boundary_precision_check/boundary_past_due_balance_strict_greater_than_five_thousand_cents
    """
    ctx = _single_bill_past_due_account(api)
    assertions.assert_account_state(
        ctx["account"],
        balance_cents=5210,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_SCHEDULED",
    )
    assert ctx["account"]["shutoff_scheduled_for"] is not None

    fixtures.record_account_payment(api, ctx["account_id"], 209)

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account,
        balance_cents=5001,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_SCHEDULED",
    )
    assert account["shutoff_scheduled_for"] is not None


def test_balance_landing_exactly_on_the_threshold_becomes_current_and_active(api):
    """PRD §2.9: "Because clause two outranks clause three, an account with an `ACTIVE` arrangement is never `PAST_DUE` no matter how large its balance grows, and a balance of exactly 5,000 cents with no arrangement is `CURRENT` because the comparison excludes the boundary."

    PRD §3.8: "And whenever `credit_status` becomes `CURRENT` or `IN_ARRANGEMENT`, the account returns to `ACTIVE` from `SHUTOFF_HELD`, from `SHUTOFF_SCHEDULED`, or from `SHUTOFF_EXECUTED` — in the last case service is restored — and `shutoff_scheduled_for` is set to null."

    Design: Difficulty/boundary_precision_check/boundary_past_due_balance_strict_greater_than_five_thousand_cents
    """
    ctx = _single_bill_past_due_account(api)
    fixtures.record_account_payment(api, ctx["account_id"], 209)

    fixtures.record_account_payment(api, ctx["account_id"], 1)

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account,
        balance_cents=5000,
        credit_status="CURRENT",
        service_status="ACTIVE",
    )
    assert account["shutoff_scheduled_for"] is None


def test_balance_one_cent_below_the_threshold_remains_current_and_active(api):
    """PRD §2.9: "It is evaluated as a strict precedence chain in which the first matching clause wins: if any arrangement on the account is `DEFAULTED`, the status is `ARRANGEMENT_DEFAULTED`; otherwise if any arrangement on the account is `ACTIVE`, the status is `IN_ARRANGEMENT`; otherwise if `balance_cents` is strictly greater than 5,000 cents (fifty dollars), the status is `PAST_DUE`; otherwise it is `CURRENT`."

    PRD §3.8: "An ad-hoc account payment supplies an `amount_cents` that must be strictly positive, else `ERR_PAYMENT_AMOUNT_INVALID`, plus an optional `memo`; it writes a `PAYMENT` entry with `source_kind` `CUSTOMER_PAYMENT` for the negative amount, with `bill_id` and `source_id` both null and `effective_at` taken from the logical clock, and then recomputes `balance_cents`, `credit_status` and `service_status` in that order."

    Design: Difficulty/boundary_precision_check/boundary_past_due_balance_strict_greater_than_five_thousand_cents
    """
    ctx = _single_bill_past_due_account(api)
    for amount in (209, 1, 1):
        fixtures.record_account_payment(api, ctx["account_id"], amount)

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account,
        balance_cents=4999,
        credit_status="CURRENT",
        service_status="ACTIVE",
    )

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assert len(entries) == 4, f"one charge plus three payments expected: {entries}"
    assertions.assert_balance_is_ledger_sum(account, entries)
    payments = assertions.entries_of_kind(entries, "CUSTOMER_PAYMENT")
    assert len(payments) == 3, f"expected three customer payments: {payments}"
    for entry in payments:
        assertions.assert_fields(entry, entry_type="PAYMENT")
        assert entry["amount_cents"] < 0, f"a payment is negative: {entry}"
        assertions.assert_append_only_shape(entry)


# ===========================================================================
# A meter-error determination waits on the meter test request
# ===========================================================================
def test_meter_error_determination_refused_while_the_bench_test_is_still_pending(api):
    """PRD §3.6: "Two of those values carry an evidentiary precondition: `CUSTOMER_SIDE_LEAK` and `UTILITY_SIDE_LEAK` each require at least one repair proof on the investigation to be `VERIFIED`, and `METER_ERROR` requires at least one meter test request on the investigation to sit in `CLOSED_FAST` or `CLOSED_SLOW`."

    PRD §2.7: "The subject entity must sit in a state from which the requested transition exists, and every cross-entity state precondition of that transition must hold → `ERR_INVALID_STATE_TRANSITION` (409) on every action operation."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_investigation_meter_error_determination_gated_by_test_closure
    """
    ctx = fixtures.bench_pending_case(api, requested_by_kind="UTILITY")
    request = validate_success(
        api.get_meter_test_request(ctx["test_request_id"], CSR_HEADERS)
    )
    assertions.assert_fields(request, status="BENCH_TEST_PENDING")

    response = api.determine_investigation(
        ctx["investigation_id"],
        f.determination_payload("METER_ERROR"),
        CSR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    investigation = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(
        investigation,
        status="EVIDENCE_REQUESTED",
        leak_determination="UNDETERMINED",
    )


def test_closing_the_bench_test_slow_unblocks_the_meter_error_determination(api):
    """PRD §3.4: "All three set the meter's `accuracy_pct` and `last_test_completed_at`, and all three advance the investigation from `EVIDENCE_REQUESTED` to `EVIDENCE_UNDER_REVIEW`."

    PRD §3.6: "Two of those values carry an evidentiary precondition: `CUSTOMER_SIDE_LEAK` and `UTILITY_SIDE_LEAK` each require at least one repair proof on the investigation to be `VERIFIED`, and `METER_ERROR` requires at least one meter test request on the investigation to sit in `CLOSED_FAST` or `CLOSED_SLOW`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_investigation_meter_error_determination_gated_by_test_closure
    """
    ctx = fixtures.bench_pending_case(api, requested_by_kind="UTILITY")
    validate_error(
        api.determine_investigation(
            ctx["investigation_id"],
            f.determination_payload("METER_ERROR"),
            CSR_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    # A write aimed only at the meter test request, with no call whatsoever
    # against the investigation.
    request = fixtures.record_bench_result(
        api, ctx["test_request_id"], 97.00, 98.20, 98.40, tested_at="2026-08-03T09:00:00Z"
    )
    assertions.assert_fields(request, bench_result="SLOW", status="CLOSED_SLOW")
    assert _num(request["accuracy_pct"]) == pytest.approx(98.05, abs=TOLERANCE)

    meter = fixtures.fetch_meter(api, ctx["meter_id"])
    assertions.assert_fields(meter, accuracy_status="FAILED_SLOW")
    assert _num(meter["correction_factor"]) == pytest.approx(1.019888, abs=TOLERANCE)

    moved = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(moved, status="EVIDENCE_UNDER_REVIEW")

    determined = fixtures.determine(
        api, ctx["investigation_id"], "METER_ERROR", CSR_HEADERS
    )
    assertions.assert_fields(
        determined, status="DETERMINED", leak_determination="METER_ERROR"
    )


def test_slow_bench_result_restates_nothing_on_the_disputed_bill(api):
    """PRD §3.4: "Critically, **no** `CORRECTED` read is created and **no** bill enters `REBILL_PENDING`: a slow meter under-billed the customer, and the utility does not back-bill for water it failed to measure."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_investigation_meter_error_determination_gated_by_test_closure
    """
    ctx = fixtures.bench_pending_case(api, requested_by_kind="UTILITY")
    fixtures.record_bench_result(
        api, ctx["test_request_id"], 97.00, 98.20, 98.40, tested_at="2026-08-03T09:00:00Z"
    )

    target_read = validate_success(
        api.get_meter_reading(ctx["target_read_id"], TECHNICIAN_HEADERS)
    )
    assert target_read["superseded_by_reading_id"] is None

    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(
        bill, billing_status="UNDER_INVESTIGATION", consumption_gallons=41000
    )


def test_meter_error_credit_is_drafted_with_no_repair_proof_in_existence(api):
    """PRD §3.6: "Unless the determination is `METER_ERROR`, at least one repair proof on the investigation must be `VERIFIED`, else `ERR_REPAIR_PROOF_REQUIRED`; and unless the determination is `METER_ERROR`, the supplied `leak_type` must equal the `leak_type` of at least one such `VERIFIED` proof, else `ERR_LEAK_TYPE_MISMATCH`."

    PRD §3.6: "Buried leaks — `SERVICE_LINE` and `UNDERGROUND` — take `BASELINE_REBILL`, where the whole excess is forgiven and the bill is simply rewritten to the baseline: `water_credit_cents` is `water_charge_cents` minus the water charge that consumption of exactly `seasonal_baseline_gallons` in that same `season` would have produced, again with any negative result treated as zero."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_investigation_meter_error_determination_gated_by_test_closure
    """
    ctx = fixtures.bench_pending_case(api, requested_by_kind="UTILITY")
    fixtures.record_bench_result(
        api, ctx["test_request_id"], 97.00, 98.20, 98.40, tested_at="2026-08-03T09:00:00Z"
    )
    investigation = fixtures.determine(
        api, ctx["investigation_id"], "METER_ERROR", CSR_HEADERS
    )

    adjustment = fixtures.draft_adjustment(
        api,
        ctx["investigation_id"],
        ctx["bill_id"],
        "SERVICE_LINE",
        investigation["version"],
        CSR_HEADERS,
    )
    assertions.assert_credit_breakdown(
        adjustment,
        status="DRAFT",
        variant_applied="BASELINE_REBILL",
        net_credit_cents=26963,
    )

    _rows, meta = validate_paginated(
        api.list_repair_proofs(
            CSR_HEADERS, {"investigation_id": ctx["investigation_id"], "limit": 100}
        )
    )
    assertions.assert_pagination_meta(meta, total_count=0)


# ===========================================================================
# A shutoff execution waits on the investigation hold
# ===========================================================================
def test_shutoff_schedules_into_scheduled_even_with_a_hold_already_outstanding(api):
    """PRD §3.8: "Note carefully that the account lands in `SHUTOFF_SCHEDULED` even when `open_investigation_hold_count` plus `open_rebill_count` is already positive: `SHUTOFF_HELD` is reached only by the system transition that fires when that sum moves from zero to a positive number, so a shutoff scheduled while a hold is already outstanding simply sits in `SHUTOFF_SCHEDULED` and is stopped later, at execution time."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_execute_shutoff_blocked_while_investigation_hold_outstanding
    """
    ctx = _investigation_then_scheduled_shutoff(api)

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account,
        balance_cents=30887,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_SCHEDULED",
        open_investigation_hold_count=1,
        open_rebill_count=0,
    )
    assert account["shutoff_scheduled_for"] is not None

    investigation = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(investigation, shutoff_hold_active=True)


def test_execute_shutoff_refused_while_the_investigation_hold_is_outstanding(api):
    """PRD §3.8: "Both `open_investigation_hold_count` and `open_rebill_count` must be zero, else `ERR_SHUTOFF_HOLD_ACTIVE` — no household loses water while the utility is still deciding whether the bill was right."

    PRD §3.8: "The current logical-clock instant must be at or after `shutoff_scheduled_for`, else `ERR_SHUTOFF_NOTICE_NOT_ELAPSED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_execute_shutoff_blocked_while_investigation_hold_outstanding
    """
    ctx = _investigation_then_scheduled_shutoff(api)
    scheduled_for = fixtures.fetch_account(api, ctx["account_id"])["shutoff_scheduled_for"]

    response = api.execute_shutoff(ctx["account_id"], SUPERVISOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_SHUTOFF_HOLD_ACTIVE.value, 409)

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account,
        service_status="SHUTOFF_SCHEDULED",
        open_investigation_hold_count=1,
    )
    assert account["shutoff_scheduled_for"] == scheduled_for


def test_closing_the_investigation_releases_the_hold_and_the_shutoff_executes(api):
    """PRD §3.3: "That drops `shutoff_hold_active` to false, decrements the account's `open_investigation_hold_count` — which may return `service_status` from `SHUTOFF_HELD` to `SHUTOFF_SCHEDULED`, or all the way to `ACTIVE` — and settles the bill from `UNDER_INVESTIGATION` to the terminal `UPHELD_AS_BILLED`, where `adjusted_total_cents` stays equal to `total_charge_cents` and no ledger entry whatsoever is written."

    PRD §3.8: "Execution moves `service_status` to `SHUTOFF_EXECUTED` and clears `shutoff_scheduled_for` to null."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_execute_shutoff_blocked_while_investigation_hold_outstanding
    """
    ctx = _investigation_then_scheduled_shutoff(api)
    validate_error(
        api.execute_shutoff(ctx["account_id"], SUPERVISOR_HEADERS),
        ApiErrorId.ERR_SHUTOFF_HOLD_ACTIVE.value,
        409,
    )

    # A write aimed only at the investigation drops the hold count to zero.
    closed = validate_success(
        api.close_investigation_no_adjustment(
            ctx["investigation_id"], CSR_HEADERS, f.close_no_adjustment_payload()
        )
    )
    assertions.assert_fields(
        closed, status="CLOSED_NO_ADJUSTMENT", shutoff_hold_active=False
    )
    released = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        released,
        open_investigation_hold_count=0,
        service_status="SHUTOFF_SCHEDULED",
        credit_status="PAST_DUE",
    )
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(bill, billing_status="UPHELD_AS_BILLED")
    assertions.assert_bill_charges(bill, adjusted_total_cents=15257)

    account = validate_success(api.execute_shutoff(ctx["account_id"], SUPERVISOR_HEADERS))
    assertions.assert_account_state(
        account, service_status="SHUTOFF_EXECUTED", balance_cents=30887
    )
    assert account["shutoff_scheduled_for"] is None


# ===========================================================================
# An instalment plan tracks the adjusted total the posted credit leaves behind
# ===========================================================================
def test_arrangement_finances_the_unadjusted_total_while_the_credit_is_pending(api):
    """PRD §3.8: "And `total_amount_cents` must equal the financed bill's `adjusted_total_cents` at the time of proposal, else `ERR_ARRANGEMENT_AMOUNT_MISMATCH`, so a plan can never finance a figure the credit workflow has already superseded."

    PRD §3.8: "`installment_cents` is the financed amount divided by `installment_count`, taking the floor — the largest whole number of cents not exceeding the quotient — and it applies to every instalment from the first through the second-to-last."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_arrangement_amount_tracks_posted_adjustment_on_the_bill
    """
    ctx = fixtures.pending_adjustment_case(api)
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(ctx["adjustment"], status="PENDING_APPROVAL")
    assertions.assert_bill_charges(bill, adjusted_total_cents=44939)

    arrangement = fixtures.propose_arrangement(
        api,
        ctx["account_id"],
        ctx["bill_id"],
        44939,
        fixtures.account_version(api, ctx["account_id"]),
        installment_count=12,
        down_payment_cents=9000,
    )
    assertions.assert_fields(
        arrangement,
        status="PROPOSED",
        total_amount_cents=44939,
        installment_cents=2994,
        final_installment_cents=3005,
    )


def test_identical_arrangement_amount_is_refused_once_the_credit_posts(api):
    """PRD §3.8: "And `total_amount_cents` must equal the financed bill's `adjusted_total_cents` at the time of proposal, else `ERR_ARRANGEMENT_AMOUNT_MISMATCH`, so a plan can never finance a figure the credit workflow has already superseded."

    PRD §3.7: "The bill then moves from `UNDER_INVESTIGATION` to `ADJUSTED` and its `adjusted_total_cents` is recomputed as `total_charge_cents` minus the sum of `net_credit_cents` over the `POSTED` adjustments on that bill; the investigation moves from `ADJUSTMENT_PENDING` to `RESOLVED`, `shutoff_hold_active` becomes false and the account's `open_investigation_hold_count` decreases by one."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_arrangement_amount_tracks_posted_adjustment_on_the_bill
    """
    ctx = fixtures.pending_adjustment_case(api)
    fixtures.propose_arrangement(
        api,
        ctx["account_id"],
        ctx["bill_id"],
        44939,
        fixtures.account_version(api, ctx["account_id"]),
        installment_count=12,
        down_payment_cents=9000,
    )

    # A write aimed only at the leak adjustment moves the figure the plan may
    # finance.
    posted = fixtures.approve_adjustment(
        api, ctx["adjustment_id"], SUPERVISOR_HEADERS
    )
    assertions.assert_credit_breakdown(
        posted, status="POSTED", net_credit_cents=26963
    )
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(bill, billing_status="ADJUSTED")
    assertions.assert_bill_charges(bill, adjusted_total_cents=17976)

    response = api.create_payment_arrangement(
        f.payment_arrangement_payload(
            ctx["account_id"],
            ctx["bill_id"],
            44939,
            9000,
            12,
            fixtures.account_version(api, ctx["account_id"]),
        ),
        CSR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ARRANGEMENT_AMOUNT_MISMATCH.value, 422)


def test_arrangement_matching_the_posted_adjusted_total_is_accepted(api):
    """PRD §3.8: "And `total_amount_cents` must equal the financed bill's `adjusted_total_cents` at the time of proposal, else `ERR_ARRANGEMENT_AMOUNT_MISMATCH`, so a plan can never finance a figure the credit workflow has already superseded."

    PRD §3.8: "The remainder is the financed amount minus `installment_cents` multiplied by `installment_count`, and `final_installment_cents` is `installment_cents` plus that entire remainder."

    PRD §3.8: "A new plan opens in `PROPOSED` with `paid_installment_count`, `missed_payment_count` and `reinstatement_count` all zero, and any other arrangement on the same account sitting in `PROPOSED` or `ACTIVE` is moved to the terminal `CANCELLED`, which stops it counting toward the account's `credit_status` and therefore triggers a recompute."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_arrangement_amount_tracks_posted_adjustment_on_the_bill
    """
    ctx = fixtures.pending_adjustment_case(api)
    earlier = fixtures.propose_arrangement(
        api,
        ctx["account_id"],
        ctx["bill_id"],
        44939,
        fixtures.account_version(api, ctx["account_id"]),
        installment_count=12,
        down_payment_cents=9000,
    )
    fixtures.approve_adjustment(api, ctx["adjustment_id"], SUPERVISOR_HEADERS)

    arrangement = fixtures.propose_arrangement(
        api,
        ctx["account_id"],
        ctx["bill_id"],
        17976,
        fixtures.account_version(api, ctx["account_id"]),
        installment_count=6,
        down_payment_cents=4000,
    )
    assertions.assert_fields(
        arrangement,
        status="PROPOSED",
        total_amount_cents=17976,
        installment_cents=2329,
        final_installment_cents=2331,
        paid_installment_count=0,
        missed_payment_count=0,
        reinstatement_count=0,
    )
    financed = arrangement["installment_cents"] * 5 + arrangement["final_installment_cents"]
    assert financed == 17976 - 4000, f"schedule must reconcile to the financed amount: {financed}"

    superseded = fixtures.fetch_arrangement(api, earlier["id"])
    assertions.assert_fields(superseded, status="CANCELLED")

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account, balance_cents=33606, credit_status="PAST_DUE"
    )
