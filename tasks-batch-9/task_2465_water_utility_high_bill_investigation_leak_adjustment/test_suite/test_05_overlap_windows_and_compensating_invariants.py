"""Reserved intervals and the quantities that must survive being undone.

Two resources in this service hand out intervals under opposite conventions:
the utility's billing calendar reserves whole days closed-closed, while a
physical meter is reserved for field testing over a half-open instant window
that additionally carries a trailing post-test quarantine.

Alongside those, three quantities have to balance after a movement is undone or
restated: the account receivable in cents after a posted leak credit is
reversed, the metered gallons on a register after a meter-error correction is
rebilled, and the meter-test deposit escrow held per test request.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    CSR_HEADERS,
    SUPERVISOR_HEADERS,
    TECHNICIAN_HEADERS,
    assertions,
    factories,
    fixtures,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of its fractional-second width."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _seed_june_period(api) -> dict:
    """One SUMMER period spanning 2025-06-01 through 2025-06-30, and nothing else."""
    fixtures.set_clock(api)
    return fixtures.create_billing_period(
        api,
        period_code="2025-06",
        start_date="2025-06-01",
        end_date="2025-06-30",
        season="SUMMER",
        rebilling_deadline_date="2026-12-31",
    )


def _period_attempt(api, period_code: str, start_date: str, end_date: str, season="SUMMER"):
    """Attempt one billing-period creation and hand back the raw response."""
    return api.create_billing_period(
        factories.billing_period_payload(
            period_code=period_code,
            start_date=start_date,
            end_date=end_date,
            season=season,
            rebilling_deadline_date="2026-12-31",
        ),
        ADMIN_HEADERS,
    )


# ===========================================================================
# The billing calendar: closed-closed day intervals
# ===========================================================================
def test_new_period_sharing_only_the_existing_end_date_is_refused(api):
    """PRD §2.10: "A new period is refused with `ERR_BILLING_PERIOD_OVERLAP` when the closed-closed interval from its `start_date` through its `end_date` intersects the closed-closed interval of any existing period — sharing a single endpoint date already counts as an intersection."

    Design: Difficulty/resource_temporal_overlap/resource_overlap_billing_calendar_closed_closed_shared_endpoint_date_conflicts
    """
    existing = _seed_june_period(api)

    response = _period_attempt(api, "2025-06B", "2025-06-30", "2025-07-15")
    validate_error(response, "ERR_BILLING_PERIOD_OVERLAP", 409)

    rows, meta = validate_paginated(api.list_billing_periods(ADMIN_HEADERS, {"limit": 100}))
    assertions.assert_pagination_meta(meta, total_count=1)
    assertions.assert_listing_ids(rows, [existing["id"]])
    unchanged = validate_success(api.get_billing_period(existing["id"], ADMIN_HEADERS))
    assertions.assert_fields(
        unchanged, start_date="2025-06-01", end_date="2025-06-30", status="OPEN"
    )


def test_new_period_sharing_only_the_existing_start_date_is_refused(api):
    """PRD §2.10: "A new period is refused with `ERR_BILLING_PERIOD_OVERLAP` when the closed-closed interval from its `start_date` through its `end_date` intersects the closed-closed interval of any existing period — sharing a single endpoint date already counts as an intersection."

    Design: Difficulty/resource_temporal_overlap/resource_overlap_billing_calendar_closed_closed_shared_endpoint_date_conflicts
    """
    existing = _seed_june_period(api)

    response = _period_attempt(api, "2025-06C", "2025-05-15", "2025-06-01")
    validate_error(response, "ERR_BILLING_PERIOD_OVERLAP", 409)

    _rows, meta = validate_paginated(api.list_billing_periods(ADMIN_HEADERS, {"limit": 100}))
    assertions.assert_pagination_meta(meta, total_count=1)
    unchanged = validate_success(api.get_billing_period(existing["id"], ADMIN_HEADERS))
    assertions.assert_fields(unchanged, start_date="2025-06-01", end_date="2025-06-30")


def test_new_period_fully_contained_in_an_existing_period_is_refused(api):
    """PRD §2.10: "A new period is refused with `ERR_BILLING_PERIOD_OVERLAP` when the closed-closed interval from its `start_date` through its `end_date` intersects the closed-closed interval of any existing period — sharing a single endpoint date already counts as an intersection."

    Design: Difficulty/resource_temporal_overlap/resource_overlap_billing_calendar_closed_closed_shared_endpoint_date_conflicts
    """
    existing = _seed_june_period(api)

    response = _period_attempt(api, "2025-06D", "2025-06-10", "2025-06-20")
    validate_error(response, "ERR_BILLING_PERIOD_OVERLAP", 409)

    _rows, meta = validate_paginated(api.list_billing_periods(ADMIN_HEADERS, {"limit": 100}))
    assertions.assert_pagination_meta(meta, total_count=1)
    unchanged = validate_success(api.get_billing_period(existing["id"], ADMIN_HEADERS))
    assertions.assert_fields(unchanged, start_date="2025-06-01", end_date="2025-06-30")


def test_periods_abutting_the_calendar_without_sharing_a_day_are_accepted(api):
    """PRD §2.10: "A new period is refused with `ERR_BILLING_PERIOD_OVERLAP` when the closed-closed interval from its `start_date` through its `end_date` intersects the closed-closed interval of any existing period — sharing a single endpoint date already counts as an intersection."

    PRD §2.10: "A `BillingPeriod` advances through exactly two transitions, both driven by a `SystemAdmin`, and its `status` starts at `OPEN`."

    Design: Difficulty/resource_temporal_overlap/resource_overlap_billing_calendar_closed_closed_shared_endpoint_date_conflicts
    """
    existing = _seed_june_period(api)

    for code, start, end in (
        ("2025-06B", "2025-06-30", "2025-07-15"),
        ("2025-06C", "2025-05-15", "2025-06-01"),
        ("2025-06D", "2025-06-10", "2025-06-20"),
    ):
        validate_error(
            _period_attempt(api, code, start, end), "ERR_BILLING_PERIOD_OVERLAP", 409
        )

    forward = validate_success(
        _period_attempt(api, "2025-07", "2025-07-01", "2025-07-31"), 201
    )
    backward = validate_success(
        _period_attempt(api, "2025-05", "2025-05-01", "2025-05-31", season="WINTER"), 201
    )
    assertions.assert_fields(forward, status="OPEN", start_date="2025-07-01")
    assertions.assert_fields(backward, status="OPEN", end_date="2025-05-31")

    rows, meta = validate_paginated(api.list_billing_periods(ADMIN_HEADERS, {"limit": 100}))
    assertions.assert_pagination_meta(meta, total_count=3)
    assert sorted(assertions.ids_of(rows)) == sorted(
        [existing["id"], forward["id"], backward["id"]]
    )
    unchanged = validate_success(api.get_billing_period(existing["id"], ADMIN_HEADERS))
    assertions.assert_fields(unchanged, start_date="2025-06-01", end_date="2025-06-30")


# ===========================================================================
# The meter test bench: half-open instant windows plus a quarantine buffer
# ===========================================================================
def _field_test_requests(api, count: int) -> dict:
    """An investigation awaiting evidence plus ``count`` utility-funded FIELD requests."""
    ctx = fixtures.investigation_case(api)
    ctx["requests"] = [
        fixtures.request_meter_test(
            api,
            ctx["investigation_id"],
            ctx["meter_id"],
            "FIELD",
            "UTILITY",
            ctx["rep_headers"],
        )
        for _ in range(count)
    ]
    ctx["request_ids"] = [request["id"] for request in ctx["requests"]]
    return ctx


def test_field_test_windows_touching_at_one_endpoint_both_reserve_the_meter(api):
    """PRD §3.4: "Because both intervals are half-open, two windows that merely touch at an endpoint — one ending exactly where the next begins — do not conflict."

    PRD §3.4: "Successful scheduling records `window_start` and `window_end` and moves the request to `FIELD_TEST_SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/resource_overlap_meter_test_window_half_open_touching_allowed_plus_quarantine_buffer
    """
    ctx = _field_test_requests(api, 2)

    first = fixtures.schedule_field_test(
        api, ctx["request_ids"][0], "2026-08-03T08:00:00Z", "2026-08-03T12:00:00Z"
    )
    second = fixtures.schedule_field_test(
        api, ctx["request_ids"][1], "2026-08-03T12:00:00Z", "2026-08-03T16:00:00Z"
    )

    assert first["status"] == "FIELD_TEST_SCHEDULED"
    assert second["status"] == "FIELD_TEST_SCHEDULED"
    assert _instant(first["window_start"]) == _instant("2026-08-03T08:00:00Z")
    assert _instant(first["window_end"]) == _instant("2026-08-03T12:00:00Z")
    assert _instant(second["window_start"]) == _instant("2026-08-03T12:00:00Z")
    assert _instant(second["window_end"]) == _instant("2026-08-03T16:00:00Z")


def test_field_test_window_straddling_a_live_reservation_is_refused(api):
    """PRD §3.4: "Two live reservations on the same meter may not overlap: the requested interval must not intersect the half-open interval of any other test request on that same meter sitting in `FIELD_TEST_SCHEDULED` or `BENCH_TEST_PENDING`, else `ERR_METER_TEST_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/resource_overlap_meter_test_window_half_open_touching_allowed_plus_quarantine_buffer
    """
    ctx = _field_test_requests(api, 2)
    fixtures.schedule_field_test(
        api, ctx["request_ids"][0], "2026-08-03T08:00:00Z", "2026-08-03T12:00:00Z"
    )

    response = api.schedule_field_test(
        ctx["request_ids"][1],
        factories.field_test_window_payload("2026-08-03T10:00:00Z", "2026-08-03T14:00:00Z"),
        TECHNICIAN_HEADERS,
    )
    validate_error(response, "ERR_METER_TEST_WINDOW_CONFLICT", 409)

    refused = validate_success(
        api.get_meter_test_request(ctx["request_ids"][1], TECHNICIAN_HEADERS)
    )
    assertions.assert_fields(refused, status="REQUESTED")
    assertions.assert_null_fields(refused, "window_start", "window_end")


def test_field_test_window_inside_the_post_test_quarantine_is_refused(api):
    """PRD §3.4: "A meter also needs to settle after being handled: whenever `last_test_completed_at` is not null, `window_start` must be at or after that instant plus a forty-eight-hour (two full day) quarantine, else `ERR_METER_TEST_QUARANTINE`."

    PRD §3.4: "`PASS` closes the request at `CLOSED_PASS`, sets the meter's `accuracy_status` to `VERIFIED_ACCURATE` and its `last_test_completed_at` to `tested_at`, forfeits the deposit — no refund entry is written and `deposit_refunded` stays false, because the customer's suspicion was unfounded — and advances the investigation from `EVIDENCE_REQUESTED` to `EVIDENCE_UNDER_REVIEW`."

    Design: Difficulty/resource_temporal_overlap/resource_overlap_meter_test_window_half_open_touching_allowed_plus_quarantine_buffer
    """
    ctx = _field_test_requests(api, 2)
    fixtures.schedule_field_test(
        api, ctx["request_ids"][0], "2026-08-03T08:00:00Z", "2026-08-03T12:00:00Z"
    )
    closed = fixtures.record_field_result(
        api, ctx["request_ids"][0], "PASS", "2026-08-03T09:00:00Z"
    )
    assertions.assert_fields(
        closed, status="CLOSED_PASS", field_result="PASS", deposit_refunded=False
    )

    meter = fixtures.fetch_meter(api, ctx["meter_id"])
    assertions.assert_fields(meter, accuracy_status="VERIFIED_ACCURATE")
    assert _instant(meter["last_test_completed_at"]) == _instant("2026-08-03T09:00:00Z")
    investigation = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(investigation, status="EVIDENCE_UNDER_REVIEW")

    # 2026-08-04T09:00Z is 24 hours after the completed test and overlaps no
    # other reservation, so only the trailing buffer can refuse it.
    response = api.schedule_field_test(
        ctx["request_ids"][1],
        factories.field_test_window_payload("2026-08-04T09:00:00Z", "2026-08-04T13:00:00Z"),
        TECHNICIAN_HEADERS,
    )
    validate_error(response, "ERR_METER_TEST_QUARANTINE", 409)

    refused = validate_success(
        api.get_meter_test_request(ctx["request_ids"][1], TECHNICIAN_HEADERS)
    )
    assertions.assert_fields(refused, status="REQUESTED")
    assertions.assert_null_fields(refused, "window_start", "window_end")


def test_field_test_window_at_exactly_forty_eight_hours_after_a_test_is_accepted(api):
    """PRD §3.4: "A meter also needs to settle after being handled: whenever `last_test_completed_at` is not null, `window_start` must be at or after that instant plus a forty-eight-hour (two full day) quarantine, else `ERR_METER_TEST_QUARANTINE`."

    PRD §3.4: "Because both intervals are half-open, two windows that merely touch at an endpoint — one ending exactly where the next begins — do not conflict."

    Design: Difficulty/resource_temporal_overlap/resource_overlap_meter_test_window_half_open_touching_allowed_plus_quarantine_buffer
    """
    ctx = _field_test_requests(api, 3)
    fixtures.schedule_field_test(
        api, ctx["request_ids"][0], "2026-08-03T08:00:00Z", "2026-08-03T12:00:00Z"
    )
    fixtures.schedule_field_test(
        api, ctx["request_ids"][1], "2026-08-03T12:00:00Z", "2026-08-03T16:00:00Z"
    )
    fixtures.record_field_result(
        api, ctx["request_ids"][0], "PASS", "2026-08-03T09:00:00Z"
    )

    accepted = fixtures.schedule_field_test(
        api, ctx["request_ids"][2], "2026-08-05T09:00:00Z", "2026-08-05T13:00:00Z"
    )
    assertions.assert_fields(accepted, status="FIELD_TEST_SCHEDULED")
    assert _instant(accepted["window_start"]) == _instant("2026-08-05T09:00:00Z")

    # The buffer reaches back to the completed test only; a window already
    # reserved before it keeps its reservation.
    untouched = validate_success(
        api.get_meter_test_request(ctx["request_ids"][1], TECHNICIAN_HEADERS)
    )
    assertions.assert_fields(untouched, status="FIELD_TEST_SCHEDULED")
    assert _instant(untouched["window_start"]) == _instant("2026-08-03T12:00:00Z")
    assert _instant(untouched["window_end"]) == _instant("2026-08-03T16:00:00Z")


# ===========================================================================
# The receivable in cents, restored by a compensating reversal
# ===========================================================================
def test_reversing_a_posted_leak_credit_restores_the_receivable_to_the_cent(api):
    """PRD §3.7: "`balance_cents`, `credit_status` and `service_status` are then recomputed in that order, and the invariant is exact: after a reversal the account's `balance_cents` equals its value immediately before the approval that it undoes."

    PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."

    Design: Difficulty/compensating_invariant/compensating_invariant_receivable_balance_restored_after_adjustment_reversal
    """
    ctx = fixtures.pending_adjustment_case(api)

    before = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(before, balance_cents=60569, credit_status="PAST_DUE")

    approved = fixtures.approve_adjustment(api, ctx["adjustment_id"], SUPERVISOR_HEADERS)
    assertions.assert_credit_breakdown(
        approved,
        capped_credit_cents=26963,
        admin_fee_charged_cents=0,
        net_credit_cents=26963,
    )
    mid = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(mid, balance_cents=33606)

    fixtures.reverse_adjustment(api, ctx["adjustment_id"], SUPERVISOR_HEADERS)

    after = fixtures.fetch_account(api, ctx["account_id"])
    assert after["balance_cents"] == before["balance_cents"], (
        "the reversal must restore the pre-approval receivable to the cent"
    )
    assertions.assert_account_state(after, balance_cents=60569)
    assertions.assert_balance_is_ledger_sum(
        after, assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    )


def test_reversal_writes_one_compensating_entry_and_deletes_nothing(api):
    """PRD §3.7: "Exactly one compensating entry is written: a `REVERSAL` with `source_kind` `LEAK_ADJUSTMENT_REVERSAL` whose `amount_cents` is the positive `capped_credit_cents` minus `admin_fee_charged_cents` — a single movement that undoes both the credit and the fee."

    PRD §2.4: "Ledger entries are append-only: once written they are never updated and never deleted, so they carry only `id` and `created_at`."

    Design: Difficulty/compensating_invariant/compensating_invariant_receivable_balance_restored_after_adjustment_reversal
    """
    ctx = fixtures.pending_adjustment_case(api)
    fixtures.approve_adjustment(api, ctx["adjustment_id"], SUPERVISOR_HEADERS)

    after_approval = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assert len(after_approval) == 5, (
        "four bill charges plus the single credit leg the approval wrote"
    )

    fixtures.reverse_adjustment(api, ctx["adjustment_id"], SUPERVISOR_HEADERS)

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assert len(entries) == 6, "the reversal appends one row rather than removing any"
    assertions.assert_single_entry(
        entries,
        "LEAK_ADJUSTMENT_REVERSAL",
        entry_type="REVERSAL",
        amount_cents=26963,
    )
    assertions.assert_single_entry(
        entries,
        "LEAK_ADJUSTMENT_CREDIT",
        entry_type="CREDIT",
        amount_cents=-26963,
    )
    assert len(assertions.entries_of_kind(entries, "BILL_CHARGE")) == 4
    assert sum(entry["amount_cents"] for entry in entries) == 60569
    assertions.assert_no_entry_of_kind(entries, "LEAK_ADJUSTMENT_ADMIN_FEE")


def test_reversal_walks_the_bill_and_investigation_back_to_pre_approval_states(api):
    """PRD §3.7: "The bill returns from `ADJUSTED` to `ISSUED` with `adjusted_total_cents` recomputed back to `total_charge_cents`; the investigation returns from `RESOLVED` to `DETERMINED`, `shutoff_hold_active` becomes true again and the account's `open_investigation_hold_count` increases by one — a reversal genuinely re-opens the dispute and re-arms the shutoff protection."

    Design: Difficulty/compensating_invariant/compensating_invariant_receivable_balance_restored_after_adjustment_reversal
    """
    ctx = fixtures.pending_adjustment_case(api)
    bill_before = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_bill_charges(
        bill_before, total_charge_cents=44939, adjusted_total_cents=44939
    )
    assertions.assert_fields(bill_before, billing_status="UNDER_INVESTIGATION")

    fixtures.approve_adjustment(api, ctx["adjustment_id"], SUPERVISOR_HEADERS)
    bill_mid = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(bill_mid, billing_status="ADJUSTED")
    assertions.assert_bill_charges(bill_mid, adjusted_total_cents=17976)
    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]), status="RESOLVED"
    )

    reversed_adjustment = fixtures.reverse_adjustment(
        api, ctx["adjustment_id"], SUPERVISOR_HEADERS
    )

    assertions.assert_fields(reversed_adjustment, status="REVERSED")
    bill_after = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(bill_after, billing_status="ISSUED")
    assertions.assert_bill_charges(
        bill_after, total_charge_cents=44939, adjusted_total_cents=44939
    )
    investigation_after = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(
        investigation_after, status="DETERMINED", shutoff_hold_active=True
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]),
        open_investigation_hold_count=1,
        credit_status="PAST_DUE",
    )


# ===========================================================================
# Metered gallons on the register, conserved across correction and rebill
# ===========================================================================
def _account_bills(api, ctx) -> list:
    """Every bill on the fixture's account and meter, oldest first."""
    rows, _meta = validate_paginated(
        api.list_bills(
            SUPERVISOR_HEADERS,
            {"account_id": ctx["account_id"], "meter_id": ctx["meter_id"], "limit": 100},
        )
    )
    return rows


def _live_gallons_total(bills: list) -> int:
    """Sum consumption over the bills that still count against the register."""
    return sum(
        bill["consumption_gallons"]
        for bill in bills
        if bill["billing_status"] not in ("DRAFT", "REBILLED")
    )


def _greatest_live_reading(api, meter_id: str) -> int:
    return max(row["reading_value"] for row in fixtures.live_readings(api, meter_id))


def test_meter_error_correction_and_rebill_conserve_metered_gallons(api):
    """PRD §3.4: "This keeps the register monotonic and conserves every gallon already billed in earlier periods: the sum of `consumption_gallons` over every bill on the meter that is neither `DRAFT` nor `REBILLED` always equals the greatest live `reading_value` on the meter minus the meter's `initial_register_value`."

    Design: Difficulty/compensating_invariant/compensating_invariant_metered_gallons_conserved_across_correction_and_rebill
    """
    ctx = fixtures.bench_pending_case(api, requested_by_kind="UTILITY")

    before_bills = _account_bills(api, ctx)
    assert _greatest_live_reading(api, ctx["meter_id"]) - 100000 == 53000
    assert _live_gallons_total(before_bills) == 53000

    fixtures.record_bench_result(
        api, ctx["test_request_id"], 95.20, 103.40, 102.10, tested_at="2026-08-03T09:00:00Z"
    )
    validate_success(api.rebill_bill(ctx["bill_id"], SUPERVISOR_HEADERS))

    corrected_travel = _greatest_live_reading(api, ctx["meter_id"]) - 100000
    assert corrected_travel == 52204, "152204 - 100000 after the corrected read"
    after_bills = _account_bills(api, ctx)
    assert _live_gallons_total(after_bills) == 52204
    assert _live_gallons_total(after_bills) == corrected_travel, (
        "no gallon is created or destroyed by the correction"
    )


def test_meter_error_correction_reduces_only_the_period_it_covers(api):
    """PRD §3.4: "**Link two**, caused by link one: exactly one `CORRECTED` read is created, aimed at the live read with the greatest `read_date` on that meter with `created_at` descending as the tie-break — the scope of a meter-error correction is the latest live read only, never a sweep across history."

    PRD §3.5: "The superseded bill moves from `REBILL_PENDING` to the terminal `REBILLED`."

    Design: Difficulty/compensating_invariant/compensating_invariant_metered_gallons_conserved_across_correction_and_rebill
    """
    ctx = fixtures.bench_pending_case(api, requested_by_kind="UTILITY")

    fixtures.record_bench_result(
        api, ctx["test_request_id"], 95.20, 103.40, 102.10, tested_at="2026-08-03T09:00:00Z"
    )
    replacement = validate_success(api.rebill_bill(ctx["bill_id"], SUPERVISOR_HEADERS))

    for history_bill_id in ctx["history_bill_ids"]:
        history_bill = fixtures.fetch_bill(api, history_bill_id)
        assertions.assert_bill_charges(history_bill, consumption_gallons=4000)
        assertions.assert_fields(history_bill, billing_status="ISSUED")

    assertions.assert_fields(replacement, billing_status="ISSUED", rebill_of_bill_id=ctx["bill_id"])
    assertions.assert_bill_charges(
        replacement,
        consumption_gallons=40204,
        water_charge_cents=36804,
        sewer_charge_cents=7320,
        total_charge_cents=44124,
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]), billing_status="REBILLED"
    )


def test_rebill_moves_the_receivable_by_exactly_the_reprice_of_the_same_gallons(api):
    """PRD §3.5: "Two ledger entries land: a `REVERSAL` with `source_kind` `REBILL_REVERSAL` whose `amount_cents` is the negative of the sum of the superseded bill's `BILL_CHARGE` and `REBILL_CHARGE` entries, and then — from the replacement's auto-issue — a `CHARGE` with `source_kind` `REBILL_CHARGE` for the positive `total_charge_cents` of the replacement."

    Design: Difficulty/compensating_invariant/compensating_invariant_metered_gallons_conserved_across_correction_and_rebill
    """
    ctx = fixtures.bench_pending_case(api, requested_by_kind="UTILITY")
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]), balance_cents=60569
    )

    fixtures.record_bench_result(
        api, ctx["test_request_id"], 95.20, 103.40, 102.10, tested_at="2026-08-03T09:00:00Z"
    )
    validate_success(api.rebill_bill(ctx["bill_id"], SUPERVISOR_HEADERS))

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_single_entry(
        entries, "REBILL_REVERSAL", entry_type="REVERSAL", amount_cents=-44939
    )
    assertions.assert_single_entry(
        entries, "REBILL_CHARGE", entry_type="CHARGE", amount_cents=44124
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(account, balance_cents=59754)
    assert account["balance_cents"] == 60569 - 44939 + 44124
    assertions.assert_balance_is_ledger_sum(account, entries)


def test_correction_supersedes_a_read_without_deleting_any_reading(api):
    """PRD §3.1: "Liveness is tracked by `superseded_by_reading_id`: a row whose `superseded_by_reading_id` is null is live, and posting a `CORRECTED` read sets that field on the row named by `corrects_reading_id` to the new row's identifier."

    Design: Difficulty/compensating_invariant/compensating_invariant_metered_gallons_conserved_across_correction_and_rebill
    """
    ctx = fixtures.bench_pending_case(api, requested_by_kind="UTILITY")

    fixtures.record_bench_result(
        api, ctx["test_request_id"], 95.20, 103.40, 102.10, tested_at="2026-08-03T09:00:00Z"
    )

    rows, meta = validate_paginated(
        api.list_meter_readings(
            TECHNICIAN_HEADERS, {"meter_id": ctx["meter_id"], "limit": 100}
        )
    )
    assertions.assert_pagination_meta(meta, total_count=6)
    corrected = [row for row in rows if row["read_type"] == "CORRECTED"]
    assert len(corrected) == 1, "exactly one CORRECTED read restates the latest live read"
    assertions.assert_fields(
        corrected[0],
        reading_value=152204,
        corrects_reading_id=ctx["target_read_id"],
        consumption_since_prior_gallons=40204,
    )

    superseded = validate_success(
        api.get_meter_reading(ctx["target_read_id"], TECHNICIAN_HEADERS)
    )
    assertions.assert_fields(
        superseded, reading_value=153000, superseded_by_reading_id=corrected[0]["id"]
    )


# ===========================================================================
# The meter-test deposit escrow, conserved per request
# ===========================================================================
def _two_customer_funded_bench_requests(api) -> dict:
    """One account, two master meters, and one customer-funded bench test on each.

    The second master meter carries reads but no bill, so a verdict against it
    cannot disturb any charge.
    """
    ctx = fixtures.investigation_case(api)
    second_meter = fixtures.create_master_meter(
        api, ctx["account_id"], initial_register_value=900000
    )
    fixtures.post_reading(api, second_meter["id"], "2026-06-30", 900000)
    second_read = fixtures.post_reading(api, second_meter["id"], "2026-07-31", 901000)

    forfeiting = fixtures.request_meter_test(
        api, ctx["investigation_id"], ctx["meter_id"], "BENCH", "CUSTOMER", CSR_HEADERS
    )
    refunding = fixtures.request_meter_test(
        api, ctx["investigation_id"], second_meter["id"], "BENCH", "CUSTOMER", CSR_HEADERS
    )
    ctx.update(
        {
            "second_meter_id": second_meter["id"],
            "second_read_id": second_read["id"],
            "forfeiting_request_id": forfeiting["id"],
            "refunding_request_id": refunding["id"],
        }
    )
    return ctx


def _entries_for_source(entries: list, source_id: str) -> list:
    return [entry for entry in entries if entry.get("source_id") == source_id]


def test_vindicating_bench_test_keeps_the_customer_deposit_in_escrow(api):
    """PRD §3.4: "**`PASS`** closes the request at `CLOSED_PASS`, sets the meter's `accuracy_status` to `VERIFIED_ACCURATE`, stores `accuracy_pct` and `correction_factor` on the meter, and forfeits the deposit — no refund entry, `deposit_refunded` stays false."

    PRD §3.4: "A request opens in `REQUESTED` with `deposit_refunded` false; when `deposit_cents` is greater than zero a `CHARGE` entry with `source_kind` `METER_TEST_DEPOSIT` for the positive deposit is written to the ledger and the account's `balance_cents`, `credit_status` and `service_status` are recomputed in that order."

    Design: Difficulty/compensating_invariant/compensating_invariant_meter_test_deposit_escrow_conserved_per_request
    """
    ctx = _two_customer_funded_bench_requests(api)
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]), balance_cents=66569
    )

    closed = fixtures.record_bench_result(
        api,
        ctx["forfeiting_request_id"],
        100.00,
        100.00,
        100.00,
        tested_at="2026-08-03T09:00:00Z",
    )
    assertions.assert_fields(
        closed,
        status="CLOSED_PASS",
        bench_result="PASS",
        deposit_cents=3000,
        deposit_refunded=False,
    )
    assert float(closed["accuracy_pct"]) == 100.00

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    own = _entries_for_source(entries, ctx["forfeiting_request_id"])
    assert len(own) == 1, "a forfeited deposit leaves exactly one escrow row behind"
    assertions.assert_fields(
        own[0], source_kind="METER_TEST_DEPOSIT", entry_type="CHARGE", amount_cents=3000
    )
    assert sum(entry["amount_cents"] for entry in own) == 3000
    assertions.assert_no_entry_of_kind(entries, "METER_TEST_DEPOSIT_REFUND")

    meter = fixtures.fetch_meter(api, ctx["meter_id"])
    assertions.assert_fields(meter, accuracy_status="VERIFIED_ACCURATE")
    assert float(meter["correction_factor"]) == 1.000000


def test_convicting_bench_test_refunds_the_deposit_with_a_compensating_entry(api):
    """PRD §3.4: "When `deposit_cents` is greater than zero, a `CREDIT` entry with `source_kind` `METER_TEST_DEPOSIT_REFUND` for the negative deposit amount is written and `deposit_refunded` becomes true."

    PRD §2.9: "Signs are fixed at insert time and never revisited: a `CHARGE` is positive, a `CREDIT` and a `PAYMENT` (including a deposit refund) are negative, and a `REVERSAL` carries whatever sign undoes the entry it compensates."

    Design: Difficulty/compensating_invariant/compensating_invariant_meter_test_deposit_escrow_conserved_per_request
    """
    ctx = _two_customer_funded_bench_requests(api)

    closed = fixtures.record_bench_result(
        api,
        ctx["refunding_request_id"],
        97.00,
        98.20,
        98.40,
        tested_at="2026-08-03T11:00:00Z",
    )
    assertions.assert_fields(
        closed, status="CLOSED_SLOW", bench_result="SLOW", deposit_refunded=True
    )
    assert float(closed["accuracy_pct"]) == 98.05

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    own = _entries_for_source(entries, ctx["refunding_request_id"])
    assert len(own) == 2, "the refund is appended alongside the original deposit charge"
    kinds = sorted(entry["source_kind"] for entry in own)
    assert kinds == ["METER_TEST_DEPOSIT", "METER_TEST_DEPOSIT_REFUND"]
    charge = [e for e in own if e["source_kind"] == "METER_TEST_DEPOSIT"][0]
    refund = [e for e in own if e["source_kind"] == "METER_TEST_DEPOSIT_REFUND"][0]
    assertions.assert_fields(charge, entry_type="CHARGE", amount_cents=3000)
    assertions.assert_fields(refund, entry_type="CREDIT", amount_cents=-3000)
    assert sum(entry["amount_cents"] for entry in own) == 0, (
        "this request's escrow nets to exactly zero"
    )


def test_deposit_escrow_nets_per_request_across_two_customer_funded_tests(api):
    """PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."

    PRD §3.4: "**`PASS`** closes the request at `CLOSED_PASS`, sets the meter's `accuracy_status` to `VERIFIED_ACCURATE`, stores `accuracy_pct` and `correction_factor` on the meter, and forfeits the deposit — no refund entry, `deposit_refunded` stays false."

    Design: Difficulty/compensating_invariant/compensating_invariant_meter_test_deposit_escrow_conserved_per_request
    """
    ctx = _two_customer_funded_bench_requests(api)
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]), balance_cents=66569
    )

    fixtures.record_bench_result(
        api,
        ctx["forfeiting_request_id"],
        100.00,
        100.00,
        100.00,
        tested_at="2026-08-03T09:00:00Z",
    )
    fixtures.record_bench_result(
        api,
        ctx["refunding_request_id"],
        97.00,
        98.20,
        98.40,
        tested_at="2026-08-03T11:00:00Z",
    )

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    escrow_rows = assertions.entries_of_kind(
        entries, "METER_TEST_DEPOSIT"
    ) + assertions.entries_of_kind(entries, "METER_TEST_DEPOSIT_REFUND")
    assert sum(entry["amount_cents"] for entry in escrow_rows) == 3000, (
        "one deposit forfeited and one refunded leaves the escrow at exactly +3000"
    )
    assert (
        sum(
            entry["amount_cents"]
            for entry in _entries_for_source(entries, ctx["forfeiting_request_id"])
        )
        == 3000
    )
    assert (
        sum(
            entry["amount_cents"]
            for entry in _entries_for_source(entries, ctx["refunding_request_id"])
        )
        == 0
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(account, balance_cents=63569)
    assert account["balance_cents"] == 60569 + 3000
    assertions.assert_balance_is_ledger_sum(account, entries)


def test_slow_bench_verdict_refunds_without_restating_any_read_or_bill(api):
    """PRD §3.4: "Critically, **no** `CORRECTED` read is created and **no** bill enters `REBILL_PENDING`: a slow meter under-billed the customer, and the utility does not back-bill for water it failed to measure."

    PRD §3.4: "In all cases the meter's `correction_factor` is one hundred divided by `accuracy_pct`, rounded half up to six decimal places."

    Design: Difficulty/compensating_invariant/compensating_invariant_meter_test_deposit_escrow_conserved_per_request
    """
    ctx = _two_customer_funded_bench_requests(api)

    fixtures.record_bench_result(
        api,
        ctx["refunding_request_id"],
        97.00,
        98.20,
        98.40,
        tested_at="2026-08-03T11:00:00Z",
    )

    meter = fixtures.fetch_meter(api, ctx["second_meter_id"])
    assertions.assert_fields(meter, accuracy_status="FAILED_SLOW")
    assert float(meter["correction_factor"]) == 1.019888

    rows, meta = validate_paginated(
        api.list_meter_readings(
            TECHNICIAN_HEADERS, {"meter_id": ctx["second_meter_id"], "limit": 100}
        )
    )
    assertions.assert_pagination_meta(meta, total_count=2)
    assert [row["read_type"] for row in rows] == ["ACTUAL", "ACTUAL"]
    assertions.assert_null_fields(
        validate_success(api.get_meter_reading(ctx["second_read_id"], TECHNICIAN_HEADERS)),
        "superseded_by_reading_id",
    )

    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_bill_charges(bill, consumption_gallons=41000)
    assertions.assert_fields(bill, billing_status="UNDER_INVESTIGATION")
