"""Multi-link fiscal and instrumentation cascades, and the order in which
competing refusals are reported.

Two families of behaviour live here. The first drives a single write and then
walks the chain of consequences it causes: posting a leak credit moves the
ledger, the ledger moves the balance, the balance moves the credit standing and
the credit standing restores service; recording a fast bench result restates the
meter, the meter restates its latest live read, that read restates the bill and
the bill arms the rebill interlock. The second family aims one request that
breaks two rules at once and checks which refusal the service reports.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CSR_HEADERS,
    SUPERVISOR_ALT_HEADERS,
    SUPERVISOR_HEADERS,
    TECHNICIAN_HEADERS,
    ApiErrorId,
    assertions,
    fixtures,
    make_csr_headers,
    make_supervisor_headers,
)
from test_helpers.factories import bill_payload, leak_adjustment_payload

# ---------------------------------------------------------------------------
# Chain builders
# ---------------------------------------------------------------------------


def _submitted_credit_on_held_account(api, payment_cents, target_gallons=12000):
    """A submitted leak credit on an account whose shutoff is stopped by the hold.

    The three history periods bill 4000 gallons each and the target period bills
    ``target_gallons``; an ad-hoc payment then leaves the account above the
    past-due threshold so a shutoff can be scheduled and the investigation can
    hold it. The determination is recorded by ``csr-1`` so that ``sup-1`` may
    approve.
    """
    ctx = fixtures.baselined_bill(api, target_gallons=target_gallons)
    fixtures.record_account_payment(api, ctx["account_id"], payment_cents, CSR_HEADERS)
    get_success_data(api.schedule_shutoff(ctx["account_id"], SUPERVISOR_HEADERS))

    investigation = fixtures.open_investigation(api, ctx["bill_id"], CSR_HEADERS)
    fixtures.request_evidence(api, investigation["id"], CSR_HEADERS)
    proof = fixtures.submit_repair_proof(
        api, investigation["id"], "SERVICE_LINE", CSR_HEADERS
    )
    fixtures.verify_repair_proof(api, proof["id"], CSR_HEADERS)
    investigation = fixtures.determine(
        api, investigation["id"], "CUSTOMER_SIDE_LEAK", CSR_HEADERS
    )
    adjustment = fixtures.draft_adjustment(
        api,
        investigation["id"],
        ctx["bill_id"],
        "SERVICE_LINE",
        investigation["version"],
        CSR_HEADERS,
    )
    fixtures.submit_adjustment(api, adjustment["id"], CSR_HEADERS)

    ctx["investigation_id"] = investigation["id"]
    ctx["adjustment_id"] = adjustment["id"]
    return ctx


def _bench_pending_on_held_account(api):
    """A UTILITY-funded bench test pending on the meter of a held account."""
    ctx = fixtures.baselined_bill(api, target_gallons=41000)
    get_success_data(api.schedule_shutoff(ctx["account_id"], SUPERVISOR_HEADERS))
    investigation = fixtures.open_investigation(api, ctx["bill_id"], CSR_HEADERS)
    fixtures.request_evidence(api, investigation["id"], CSR_HEADERS)
    request = fixtures.request_meter_test(
        api,
        investigation["id"],
        ctx["meter_id"],
        "BENCH",
        "UTILITY",
        CSR_HEADERS,
    )
    ctx["investigation_id"] = investigation["id"]
    ctx["test_request_id"] = request["id"]
    return ctx


def _readings(api, meter_id, **filters):
    rows, _meta = validate_paginated(
        api.list_meter_readings(
            TECHNICIAN_HEADERS, {"meter_id": meter_id, "limit": 100, **filters}
        )
    )
    return rows


def _two_account_estate(api):
    """Two accounts, one of which owns both a master meter and a submeter."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    period = fixtures.create_billing_period(api)
    account_x = fixtures.create_account(api, schedule["id"])
    account_y = fixtures.create_account(api, schedule["id"])
    master_x = fixtures.create_master_meter(
        api, account_x["id"], initial_register_value=600000
    )
    submeter_x = fixtures.create_submeter(api, account_x["id"], master_x["id"])
    master_y = fixtures.create_master_meter(
        api, account_y["id"], initial_register_value=700000
    )
    fixtures.post_reading(api, master_x["id"], "2026-06-30", 600000)
    fixtures.post_reading(api, master_x["id"], "2026-07-31", 604000)
    fixtures.post_reading(api, submeter_x["id"], "2026-06-30", 0)
    fixtures.post_reading(api, submeter_x["id"], "2026-07-31", 1000)
    fixtures.post_reading(api, master_y["id"], "2026-06-30", 700000)
    fixtures.post_reading(api, master_y["id"], "2026-07-31", 704000)
    return {
        "period_id": period["id"],
        "account_x_id": account_x["id"],
        "account_y_id": account_y["id"],
        "master_x_id": master_x["id"],
        "submeter_x_id": submeter_x["id"],
        "master_y_id": master_y["id"],
    }


# ===========================================================================
# Approving a leak credit: ledger, balance, credit standing, service
# ===========================================================================


def test_posting_a_leak_credit_writes_both_entries_and_replays_the_balance(api):
    """PRD §3.7: "The pinned sequence is: ledger inserts, then adjustment status, then bill, then investigation, then balance, then credit status, then service status."

    PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."

    Design: Difficulty/transitive_cascade/transitive_cascade_approve_adjustment_ledger_to_balance_to_credit_to_service
    """
    ctx = _submitted_credit_on_held_account(api, payment_cents=21000)
    before = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        before,
        balance_cents=9887,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_HELD",
    )
    assert before["shutoff_scheduled_for"] is not None

    posted = validate_success(
        api.approve_leak_adjustment(ctx["adjustment_id"], SUPERVISOR_HEADERS)
    )
    assertions.assert_fields(
        posted, status="POSTED", approved_by_user_id="sup-1", capped_credit_cents=9154
    )
    assert posted["admin_fee_charged_cents"] == 1500

    entries = assertions.ledger_entries(api, ctx["account_id"], SUPERVISOR_HEADERS)
    assertions.assert_single_entry(
        entries, "LEAK_ADJUSTMENT_CREDIT", amount_cents=-9154, entry_type="CREDIT"
    )
    assertions.assert_single_entry(
        entries, "LEAK_ADJUSTMENT_ADMIN_FEE", amount_cents=1500, entry_type="CHARGE"
    )

    after = fixtures.fetch_account(api, ctx["account_id"])
    assert after["balance_cents"] == 2233
    assertions.assert_balance_is_ledger_sum(after, entries)


def test_posting_a_leak_credit_clears_past_due_and_restores_service(api):
    """PRD §2.9: "It is evaluated as a strict precedence chain in which the first matching clause wins: if any arrangement on the account is `DEFAULTED`, the status is `ARRANGEMENT_DEFAULTED`; otherwise if any arrangement on the account is `ACTIVE`, the status is `IN_ARRANGEMENT`; otherwise if `balance_cents` is strictly greater than 5,000 cents (fifty dollars), the status is `PAST_DUE`; otherwise it is `CURRENT`."

    PRD §3.8: "And whenever `credit_status` becomes `CURRENT` or `IN_ARRANGEMENT`, the account returns to `ACTIVE` from `SHUTOFF_HELD`, from `SHUTOFF_SCHEDULED`, or from `SHUTOFF_EXECUTED` — in the last case service is restored — and `shutoff_scheduled_for` is set to null."

    Design: Difficulty/transitive_cascade/transitive_cascade_approve_adjustment_ledger_to_balance_to_credit_to_service
    """
    ctx = _submitted_credit_on_held_account(api, payment_cents=21000)
    before = fixtures.fetch_account(api, ctx["account_id"])
    assert before["service_status"] == "SHUTOFF_HELD"
    assert before["shutoff_scheduled_for"].startswith("2026-08-11")

    validate_success(
        api.approve_leak_adjustment(ctx["adjustment_id"], SUPERVISOR_HEADERS)
    )

    after = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        after,
        balance_cents=2233,
        credit_status="CURRENT",
        service_status="ACTIVE",
        open_investigation_hold_count=0,
    )
    assert after["shutoff_scheduled_for"] is None

    investigation = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(
        investigation, status="RESOLVED", shutoff_hold_active=False
    )
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(
        bill, billing_status="ADJUSTED", adjusted_total_cents=7603
    )


def test_a_credit_too_small_to_clear_the_arrears_leaves_the_shutoff_notice_standing(api):
    """PRD §3.7: "**Link four**, caused by link three: when `credit_status` has become `CURRENT` or `IN_ARRANGEMENT`, `service_status` moves from `SHUTOFF_HELD`, `SHUTOFF_SCHEDULED` or `SHUTOFF_EXECUTED` to `ACTIVE` and `shutoff_scheduled_for` is set to null."

    PRD §3.8: "When that sum returns to zero while `credit_status` is still `PAST_DUE` or `ARRANGEMENT_DEFAULTED`, the account moves back from `SHUTOFF_HELD` to `SHUTOFF_SCHEDULED` with `shutoff_scheduled_for` again unchanged."

    Design: Difficulty/transitive_cascade/transitive_cascade_approve_adjustment_ledger_to_balance_to_credit_to_service
    """
    ctx = _submitted_credit_on_held_account(api, payment_cents=5000)
    before = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        before,
        balance_cents=25887,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_HELD",
    )
    notice = before["shutoff_scheduled_for"]

    validate_success(
        api.approve_leak_adjustment(ctx["adjustment_id"], SUPERVISOR_HEADERS)
    )

    # The two fiscal links still fire on the identical credit figures.
    entries = assertions.ledger_entries(api, ctx["account_id"], SUPERVISOR_HEADERS)
    assertions.assert_single_entry(entries, "LEAK_ADJUSTMENT_CREDIT", amount_cents=-9154)
    assertions.assert_single_entry(
        entries, "LEAK_ADJUSTMENT_ADMIN_FEE", amount_cents=1500
    )

    after = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        after,
        balance_cents=18233,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_SCHEDULED",
        open_investigation_hold_count=0,
    )
    assert after["shutoff_scheduled_for"] == notice


# ===========================================================================
# A fast bench result: meter, read, bill, rebill interlock
# ===========================================================================


def test_fast_bench_result_corrects_the_latest_live_read_and_restates_its_bill(api):
    """PRD §3.4: "In all cases the meter's `correction_factor` is one hundred divided by `accuracy_pct`, rounded half up to six decimal places."

    PRD §3.4: "The new row carries the target's `meter_id` and `read_date`, a `read_type` of `CORRECTED`, a `reading_value` equal to the prior register value plus the corrected segment, `corrects_reading_id` pointing at the target, and `consumption_since_prior_gallons` equal to the corrected segment; the target's `superseded_by_reading_id` is set to the new row."

    PRD §3.5: "Entering `REBILL_PENDING` recomputes `consumption_gallons`, `water_charge_cents`, `submeter_credit_gallons`, `sewer_billable_gallons`, `sewer_charge_cents` and `total_charge_cents` from the live reads, and increments the account's `open_rebill_count`, which is what drives the `SHUTOFF_SCHEDULED` to `SHUTOFF_HELD` protection."

    Design: Difficulty/transitive_cascade/transitive_cascade_bench_fast_meter_to_reading_to_bill_to_rebill_counter
    """
    ctx = fixtures.bench_pending_case(
        api, requested_by_kind="UTILITY", target_gallons=41000
    )

    request = validate_success(
        api.record_bench_result(
            ctx["test_request_id"],
            {
                "tested_at": "2026-08-03T09:00:00Z",
                "low_flow_pct": 95.20,
                "mid_flow_pct": 103.40,
                "high_flow_pct": 102.10,
            },
            TECHNICIAN_HEADERS,
        )
    )
    assertions.assert_fields(
        request,
        accuracy_method="AWWA_WEIGHTED",
        accuracy_pct=101.98,
        bench_result="FAST",
        status="CLOSED_FAST",
        deposit_refunded=False,
    )

    meter = fixtures.fetch_meter(api, ctx["meter_id"])
    assertions.assert_fields(
        meter,
        accuracy_status="FAILED_FAST",
        accuracy_pct=101.98,
        correction_factor=0.980584,
    )
    assert meter["last_test_completed_at"].startswith("2026-08-03T09:00:00")

    corrected_rows = _readings(api, ctx["meter_id"], read_type="CORRECTED")
    assert len(corrected_rows) == 1, "exactly one CORRECTED read is created"
    corrected = corrected_rows[0]
    assertions.assert_fields(
        corrected,
        read_date="2026-07-31",
        reading_value=152204,
        corrects_reading_id=ctx["target_read_id"],
        consumption_since_prior_gallons=40204,
    )

    all_rows = _readings(api, ctx["meter_id"])
    superseded = next(row for row in all_rows if row["id"] == ctx["target_read_id"])
    assert superseded["superseded_by_reading_id"] == corrected["id"]
    earlier = next(row for row in all_rows if row["read_date"] == "2025-08-31")
    assert earlier["superseded_by_reading_id"] is None

    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_bill_charges(
        bill,
        consumption_gallons=40204,
        water_charge_cents=36804,
        sewer_charge_cents=7320,
        total_charge_cents=44124,
    )
    assert bill["billing_status"] == "REBILL_PENDING"

    for history_bill_id in ctx["history_bill_ids"]:
        history = fixtures.fetch_bill(api, history_bill_id)
        assertions.assert_fields(
            history, billing_status="ISSUED", consumption_gallons=4000
        )


def test_fast_bench_result_arms_the_rebill_counter_without_moving_any_money(api):
    """PRD §3.5: "Entering `REBILL_PENDING` recomputes `consumption_gallons`, `water_charge_cents`, `submeter_credit_gallons`, `sewer_billable_gallons`, `sewer_charge_cents` and `total_charge_cents` from the live reads, and increments the account's `open_rebill_count`, which is what drives the `SHUTOFF_SCHEDULED` to `SHUTOFF_HELD` protection."

    PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."

    Design: Difficulty/transitive_cascade/transitive_cascade_bench_fast_meter_to_reading_to_bill_to_rebill_counter
    """
    ctx = fixtures.bench_pending_case(
        api, requested_by_kind="UTILITY", target_gallons=41000
    )
    before = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        before, balance_cents=60569, open_rebill_count=0
    )

    validate_success(
        api.record_bench_result(
            ctx["test_request_id"],
            {
                "tested_at": "2026-08-03T09:00:00Z",
                "low_flow_pct": 95.20,
                "mid_flow_pct": 103.40,
                "high_flow_pct": 102.10,
            },
            TECHNICIAN_HEADERS,
        )
    )

    after = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        after, balance_cents=60569, open_rebill_count=1
    )

    entries = assertions.ledger_entries(api, ctx["account_id"], SUPERVISOR_HEADERS)
    assertions.assert_source_kinds(
        entries, ["BILL_CHARGE", "BILL_CHARGE", "BILL_CHARGE", "BILL_CHARGE"]
    )
    assertions.assert_balance_is_ledger_sum(after, entries)


def test_the_rebill_hold_keeps_service_held_after_the_investigation_closes(api):
    """PRD §3.8: "When that sum returns to zero while `credit_status` is still `PAST_DUE` or `ARRANGEMENT_DEFAULTED`, the account moves back from `SHUTOFF_HELD` to `SHUTOFF_SCHEDULED` with `shutoff_scheduled_for` again unchanged."

    PRD §2.9: "`open_investigation_hold_count` is the number of `HighBillInvestigation` rows on the account whose `shutoff_hold_active` is true, and `open_rebill_count` is the number of the account's bills sitting in `REBILL_PENDING`."

    Design: Difficulty/transitive_cascade/transitive_cascade_bench_fast_meter_to_reading_to_bill_to_rebill_counter
    """
    ctx = _bench_pending_on_held_account(api)
    before = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        before,
        balance_cents=60569,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_HELD",
        open_investigation_hold_count=1,
        open_rebill_count=0,
    )
    notice = before["shutoff_scheduled_for"]

    validate_success(
        api.record_bench_result(
            ctx["test_request_id"],
            {
                "tested_at": "2026-08-03T09:00:00Z",
                "low_flow_pct": 95.20,
                "mid_flow_pct": 103.40,
                "high_flow_pct": 102.10,
            },
            TECHNICIAN_HEADERS,
        )
    )
    assert fixtures.fetch_account(api, ctx["account_id"])["open_rebill_count"] == 1

    investigation = validate_success(
        api.close_investigation_no_adjustment(
            ctx["investigation_id"],
            CSR_HEADERS,
            {"note": "meter error, no leak credit; rebill will follow"},
        )
    )
    assertions.assert_fields(
        investigation, status="CLOSED_NO_ADJUSTMENT", shutoff_hold_active=False
    )

    after = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        after,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_HELD",
        open_investigation_hold_count=0,
        open_rebill_count=1,
    )
    assert after["shutoff_scheduled_for"] == notice


# ===========================================================================
# Competing refusals: which rule reports first
# ===========================================================================


def test_a_stale_investigation_version_outranks_the_undetermined_state_on_drafting(api):
    """PRD §2.7: "A request that breaks several rules always reports the earliest one in this ladder, which is why the ladder itself is part of the contract rather than an implementation detail."

    PRD §2.6: "If that value does not equal the investigation's current `version`, the request is rejected with `ERR_STALE_INVESTIGATION_VERSION` and HTTP 412."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_concurrency_p7_beats_state_p8_stale_investigation_version
    """
    ctx = fixtures.baselined_bill(api, target_gallons=41000)
    opened = fixtures.open_investigation(api, ctx["bill_id"], CSR_HEADERS)
    assert opened["version"] == 1
    requested = fixtures.request_evidence(api, opened["id"], CSR_HEADERS)
    assert requested["version"] == 2
    assert requested["status"] == "EVIDENCE_REQUESTED"

    response = api.create_leak_adjustment(
        leak_adjustment_payload(
            opened["id"], ctx["bill_id"], "SERVICE_LINE", opened["version"]
        ),
        CSR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_STALE_INVESTIGATION_VERSION.value, 412)

    rows, meta = validate_paginated(
        api.list_leak_adjustments(CSR_HEADERS, {"investigation_id": opened["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    investigation = fixtures.fetch_investigation(api, opened["id"])
    assertions.assert_fields(investigation, status="EVIDENCE_REQUESTED", version=2)


def test_the_current_investigation_version_reveals_the_state_refusal_on_drafting(api):
    """PRD §2.7: "The subject entity must sit in a state from which the requested transition exists, and every cross-entity state precondition of that transition must hold → `ERR_INVALID_STATE_TRANSITION` (409) on every action operation."

    PRD §3.6: "Drafting the real credit names the `investigation_id`, the `bill_id`, the `leak_type` and the `expected_investigation_version` described in Section 2.6. The investigation must be `DETERMINED`."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_concurrency_p7_beats_state_p8_stale_investigation_version
    """
    ctx = fixtures.baselined_bill(api, target_gallons=41000)
    opened = fixtures.open_investigation(api, ctx["bill_id"], CSR_HEADERS)
    requested = fixtures.request_evidence(api, opened["id"], CSR_HEADERS)
    assert requested["version"] == opened["version"] + 1

    stale = api.create_leak_adjustment(
        leak_adjustment_payload(
            opened["id"], ctx["bill_id"], "SERVICE_LINE", opened["version"]
        ),
        CSR_HEADERS,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_INVESTIGATION_VERSION.value, 412)

    fresh = api.create_leak_adjustment(
        leak_adjustment_payload(
            opened["id"], ctx["bill_id"], "SERVICE_LINE", requested["version"]
        ),
        CSR_HEADERS,
    )
    validate_error(fresh, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    _rows, meta = validate_paginated(
        api.list_leak_adjustments(CSR_HEADERS, {"investigation_id": opened["id"]})
    )
    assert meta["total_count"] == 0
    investigation = fixtures.fetch_investigation(api, opened["id"])
    assertions.assert_fields(investigation, status="EVIDENCE_REQUESTED", version=2)


def test_segregation_of_duties_outranks_the_locked_period_on_approval(api):
    """PRD §2.1: "Approving, denying or reversing a leak adjustment fails with `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID` equals the `determination_by_user_id` recorded on the parent investigation, so a single human holding both the rep and supervisor roles is still blocked."

    PRD §2.7: "A request that breaks several rules always reports the earliest one in this ladder, which is why the ladder itself is part of the contract rather than an implementation detail."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_business_safety_p9_beats_business_temporal_p10_on_approve
    """
    shared_rep = make_csr_headers("u-shared")
    ctx = fixtures.pending_adjustment_case(
        api, rep_headers=shared_rep, target_gallons=41000
    )
    locked = fixtures.lock_period(api, ctx["calendar"]["target_id"])
    assert locked["status"] == "LOCKED"
    investigation = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assert investigation["determination_by_user_id"] == "u-shared"

    response = api.approve_leak_adjustment(
        ctx["adjustment_id"], make_supervisor_headers("u-shared")
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    adjustment = fixtures.fetch_adjustment(api, ctx["adjustment_id"])
    assertions.assert_fields(adjustment, status="PENDING_APPROVAL")
    assertions.assert_null_fields(adjustment, "approved_by_user_id")

    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(
        bill, billing_status="UNDER_INVESTIGATION", adjusted_total_cents=44939
    )
    account = fixtures.fetch_account(api, ctx["account_id"])
    assert account["balance_cents"] == 60569
    entries = assertions.ledger_entries(api, ctx["account_id"], SUPERVISOR_HEADERS)
    assertions.assert_no_entry_of_kind(entries, "LEAK_ADJUSTMENT_CREDIT")
    assertions.assert_no_entry_of_kind(entries, "LEAK_ADJUSTMENT_ADMIN_FEE")


def test_the_locked_period_still_refuses_an_approval_by_an_untainted_supervisor(api):
    """PRD §2.10: "Locking a `CLOSED` period moves it to `LOCKED`, the terminal state, after which every fiscal write touching a bill of that period is refused with `ERR_BILLING_PERIOD_LOCKED`: leak-adjustment approval, leak-adjustment denial, leak-adjustment reversal, rebilling, and the posting of a `CORRECTED` meter reading."

    PRD §2.7: "A request that breaks several rules always reports the earliest one in this ladder, which is why the ladder itself is part of the contract rather than an implementation detail."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_business_safety_p9_beats_business_temporal_p10_on_approve
    """
    shared_rep = make_csr_headers("u-shared")
    ctx = fixtures.pending_adjustment_case(
        api, rep_headers=shared_rep, target_gallons=41000
    )
    fixtures.lock_period(api, ctx["calendar"]["target_id"])

    conflicted = api.approve_leak_adjustment(
        ctx["adjustment_id"], make_supervisor_headers("u-shared")
    )
    validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    untainted = api.approve_leak_adjustment(
        ctx["adjustment_id"], SUPERVISOR_ALT_HEADERS
    )
    validate_error(untainted, ApiErrorId.ERR_BILLING_PERIOD_LOCKED.value, 409)

    adjustment = fixtures.fetch_adjustment(api, ctx["adjustment_id"])
    assertions.assert_fields(adjustment, status="PENDING_APPROVAL")
    assertions.assert_null_fields(adjustment, "approved_by_user_id")
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(
        bill, billing_status="UNDER_INVESTIGATION", adjusted_total_cents=44939
    )
    account = fixtures.fetch_account(api, ctx["account_id"])
    assert account["balance_cents"] == 60569


def test_an_unbillable_submeter_outranks_the_account_mismatch_on_bill_generation(api):
    """PRD §3.1: "Only a `POTABLE_MASTER` meter may ever carry a bill; an `IRRIGATION_SUBMETER` measures outdoor water that never reaches the sewer, and a `BACKFLOW_FIRE_LINE` measures fire-protection volume that is neither sewer-discharged nor added to the master's consumption."

    PRD §2.7: "A request that breaks several rules always reports the earliest one in this ladder, which is why the ladder itself is part of the contract rather than an implementation detail."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_business_constraint_p11_beats_business_referential_p12_on_bill_create
    """
    estate = _two_account_estate(api)
    submeter = fixtures.fetch_meter(api, estate["submeter_x_id"])
    assertions.assert_fields(
        submeter,
        meter_type="IRRIGATION_SUBMETER",
        account_id=estate["account_x_id"],
    )
    assert submeter["account_id"] != estate["account_y_id"]

    response = api.create_bill(
        bill_payload(
            estate["account_y_id"], estate["period_id"], estate["submeter_x_id"]
        ),
        SUPERVISOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_METER_NOT_BILLABLE.value, 422)

    for filters in (
        {"account_id": estate["account_y_id"]},
        {"account_id": estate["account_x_id"]},
        {"meter_id": estate["submeter_x_id"]},
    ):
        _rows, meta = validate_paginated(api.list_bills(SUPERVISOR_HEADERS, filters))
        assert meta["total_count"] == 0, f"no bill should exist for {filters}"


def test_a_master_meter_on_the_wrong_account_yields_the_referential_refusal(api):
    """PRD §3.2: "The meter must belong to the named account, else `ERR_BILL_METER_ACCOUNT_MISMATCH`."

    PRD §2.7: "**Cross-row coherence**, all 422: `ERR_LEAK_TYPE_MISMATCH` and `ERR_ADJUSTMENT_BILL_MISMATCH` on leak-adjustment drafting, `ERR_TEST_METER_ACCOUNT_MISMATCH` on meter-test requesting, `ERR_ARRANGEMENT_ACCOUNT_MISMATCH` on arrangement proposal, `ERR_BILL_METER_ACCOUNT_MISMATCH` on bill generation."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_business_constraint_p11_beats_business_referential_p12_on_bill_create
    """
    estate = _two_account_estate(api)

    unbillable = api.create_bill(
        bill_payload(
            estate["account_y_id"], estate["period_id"], estate["submeter_x_id"]
        ),
        SUPERVISOR_HEADERS,
    )
    validate_error(unbillable, ApiErrorId.ERR_METER_NOT_BILLABLE.value, 422)

    mismatched = api.create_bill(
        bill_payload(
            estate["account_y_id"], estate["period_id"], estate["master_x_id"]
        ),
        SUPERVISOR_HEADERS,
    )
    validate_error(mismatched, ApiErrorId.ERR_BILL_METER_ACCOUNT_MISMATCH.value, 422)

    for filters in (
        {"account_id": estate["account_y_id"]},
        {"account_id": estate["account_x_id"]},
        {"meter_id": estate["submeter_x_id"]},
    ):
        _rows, meta = validate_paginated(api.list_bills(SUPERVISOR_HEADERS, filters))
        assert meta["total_count"] == 0, f"no bill should exist for {filters}"
