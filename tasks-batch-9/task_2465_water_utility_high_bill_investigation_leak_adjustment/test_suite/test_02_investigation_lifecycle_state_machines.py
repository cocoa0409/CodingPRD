"""Non-linear lifecycles of a high-bill dispute.

Three shapes are exercised against the running service:

* the bounded evidence loop, which re-enters ``EVIDENCE_REQUESTED`` by two
  different back-edges — a repair-proof rejection and a board remand — until
  the round ceiling refuses a further request;
* the two independent state dimensions of a service account, where the
  collections dimension and the derived credit dimension advance without being
  locked together;
* the bench-test fork, where one trigger on one source state reaches three
  terminal states whose side-effect sets are pairwise different.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLERK_HEADERS,
    CSR_HEADERS,
    SUPERVISOR_HEADERS,
    TECHNICIAN_HEADERS,
    assertions,
    constants,
    factories,
    fixtures,
)


def _num(value):
    """Read a numeric response field as a float regardless of its encoding."""
    assert value is not None, "expected a numeric field, got null"
    return float(value)


def _corrected_reads(api, meter_id):
    """List the ``CORRECTED`` reads on one meter."""
    rows, _meta = validate_paginated(
        api.list_meter_readings(
            TECHNICIAN_HEADERS,
            {"meter_id": meter_id, "read_type": "CORRECTED", "limit": 100},
        )
    )
    return rows


def _rejection_looped_case(api):
    """An investigation that has already re-entered the evidence loop once.

    Round one is opened with the investigation, a first proof is rejected which
    loops the investigation back to ``EVIDENCE_REQUESTED``, and a second proof
    is submitted so the review state is visited twice.
    """
    ctx = fixtures.investigation_case(api)
    head = ctx["rep_headers"]

    first_proof = fixtures.submit_repair_proof(
        api, ctx["investigation_id"], "SERVICE_LINE", head
    )
    ctx["first_proof"] = fixtures.reject_repair_proof(api, first_proof["id"], head)
    ctx["after_rejection"] = fixtures.fetch_investigation(api, ctx["investigation_id"])

    second_proof = fixtures.submit_repair_proof(
        api, ctx["investigation_id"], "SERVICE_LINE", head
    )
    ctx["second_proof"] = second_proof
    ctx["after_second_submission"] = fixtures.fetch_investigation(
        api, ctx["investigation_id"]
    )
    return ctx


def _remanded_case(api):
    """The looped investigation carried through a board remand back-edge.

    After the rejection loop the second proof is verified, a determination is
    recorded, the customer appeals, a clerk dockets the hearing and the board
    remands the matter.
    """
    ctx = _rejection_looped_case(api)
    head = ctx["rep_headers"]

    fixtures.verify_repair_proof(api, ctx["second_proof"]["id"], head)
    fixtures.determine(api, ctx["investigation_id"], "CUSTOMER_SIDE_LEAK", head)

    appeal = fixtures.file_appeal(
        api, ctx["investigation_id"], ctx["customer_headers"]
    )
    fixtures.schedule_hearing(api, appeal["id"], "2026-08-15", CLERK_HEADERS)
    fixtures.set_clock(api, "2026-08-15T18:00:00Z")
    ctx["appeal"] = fixtures.record_board_decision(
        api, appeal["id"], "REMAND", CLERK_HEADERS
    )
    ctx["appeal_id"] = appeal["id"]
    ctx["after_remand"] = fixtures.fetch_investigation(api, ctx["investigation_id"])
    return ctx


# ===========================================================================
# The cyclic evidence loop and its two back-edges
# ===========================================================================
def test_rejecting_a_repair_proof_reopens_the_evidence_round(api):
    """PRD §3.3: "Rejection moves the proof from `SUBMITTED` to `REJECTED` with a mandatory `rejection_reason`, and it is the rejection that makes this workflow cyclic: if `evidence_round_count` is still below three the investigation loops back from `EVIDENCE_UNDER_REVIEW` to `EVIDENCE_REQUESTED` and `evidence_round_count` increases by one; if `evidence_round_count` has already reached three the investigation instead moves to `EVIDENCE_EXHAUSTED` and the counter is deliberately left unchanged, because the loop is being closed rather than re-opened."

    PRD §3.3: "Evidence arrives in one of two forms, and either form advances the investigation from `EVIDENCE_REQUESTED` to `EVIDENCE_UNDER_REVIEW`: a repair proof is submitted, or a meter test request for this investigation reaches one of its closed states — `CLOSED_PASS`, `CLOSED_FAST` or `CLOSED_SLOW`."

    Design: Difficulty/non_linear_state_machine/non_linear_cyclic_investigation_evidence_loop_then_remand_exhausts_rounds
    """
    ctx = _rejection_looped_case(api)

    assertions.assert_fields(ctx["first_proof"], status="REJECTED")
    assertions.assert_fields(
        ctx["after_rejection"], status="EVIDENCE_REQUESTED", evidence_round_count=2
    )
    # The second submission is the second visit to the review state.
    assertions.assert_fields(
        ctx["after_second_submission"], status="EVIDENCE_UNDER_REVIEW"
    )
    assertions.assert_fields(ctx["second_proof"], status="SUBMITTED")


def test_board_remand_returns_a_determined_investigation_to_the_evidence_loop(api):
    """PRD §3.9: "`REMAND` moves the appeal to the terminal `REMANDED` and sends the matter back for more work."

    PRD §3.9: "A permitted remand moves the investigation from `APPEALED` back to `EVIDENCE_REQUESTED`, increases `remand_count` by one and `evidence_round_count` by one, and returns the bill from `UPHELD_AS_BILLED` to `UNDER_INVESTIGATION` when it had previously been upheld; a bill still sitting in `UNDER_INVESTIGATION` simply stays there."

    PRD §3.9: "Every branch stamps `hearing_officer_user_id` with the acting `X-User-ID` and records the `decision` and `decision_note`; beyond that the three branches diverge completely, and each carries its own full set of effects."

    Design: Difficulty/non_linear_state_machine/non_linear_cyclic_investigation_evidence_loop_then_remand_exhausts_rounds
    """
    ctx = _remanded_case(api)

    assertions.assert_fields(
        ctx["appeal"],
        status="REMANDED",
        decision="REMAND",
        hearing_officer_user_id=CLERK_HEADERS["X-User-ID"],
    )
    # Third visit to EVIDENCE_REQUESTED, reached backwards from APPEALED.
    assertions.assert_fields(
        ctx["after_remand"],
        status="EVIDENCE_REQUESTED",
        remand_count=1,
        evidence_round_count=constants.MAX_EVIDENCE_ROUNDS,
        leak_determination="CUSTOMER_SIDE_LEAK",
    )
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(bill, billing_status="UNDER_INVESTIGATION")


def test_fourth_evidence_request_is_refused_once_the_round_ceiling_is_reached(api):
    """PRD §3.3: "At most three evidence rounds may ever be opened on one investigation, counting the initial request, every rejection-driven re-request and the round a board remand grants; an attempt made when `evidence_round_count` has already reached three is refused with `ERR_EVIDENCE_ROUND_LIMIT`."

    PRD §3.3: "That request is available from `OPEN` and again from `EVIDENCE_REQUESTED`, it always lands the investigation in `EVIDENCE_REQUESTED`, and it increments `evidence_round_count` by one."

    Design: Difficulty/non_linear_state_machine/non_linear_cyclic_investigation_evidence_loop_then_remand_exhausts_rounds
    """
    ctx = _remanded_case(api)
    assertions.assert_fields(
        ctx["after_remand"],
        status="EVIDENCE_REQUESTED",
        evidence_round_count=constants.MAX_EVIDENCE_ROUNDS,
    )

    response = api.request_evidence(
        ctx["investigation_id"],
        CSR_HEADERS,
        factories.evidence_request_payload(note="round four would exceed the limit"),
    )
    validate_error(response, "ERR_EVIDENCE_ROUND_LIMIT")

    # The refusal is inert: the legal source state and the counter both stand.
    after = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(
        after,
        status="EVIDENCE_REQUESTED",
        evidence_round_count=constants.MAX_EVIDENCE_ROUNDS,
        remand_count=1,
    )


# ===========================================================================
# Two independent state dimensions on one service account
# ===========================================================================
def test_investigation_hold_moves_service_status_without_touching_credit_status(api):
    """PRD §3.8: "An account carries two independent state dimensions on one row, and they advance without blocking one another: a change in `credit_status` never by itself forbids a `service_status` trigger, and vice versa, although `service_status` triggers do consult `credit_status` in their preconditions."

    PRD §3.8: "When the sum of `open_investigation_hold_count` and `open_rebill_count` moves from zero to positive, an account in `SHUTOFF_SCHEDULED` moves to `SHUTOFF_HELD` with `shutoff_scheduled_for` preserved unchanged, so the notice period resumes rather than restarts when the hold lifts."

    Design: Difficulty/non_linear_state_machine/non_linear_parallel_service_and_credit_dimensions_move_independently
    """
    ctx = fixtures.shutoff_scheduled_account(api, target_gallons=12000)
    before = ctx["account"]
    assertions.assert_account_state(
        before,
        balance_cents=30887,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_SCHEDULED",
        open_investigation_hold_count=0,
    )
    scheduled_for = before["shutoff_scheduled_for"]
    assert scheduled_for is not None, "a scheduled shutoff must carry its notice instant"
    assert scheduled_for.startswith("2026-08-11"), (
        f"shutoff_scheduled_for: expected the ten-day notice date, got {scheduled_for!r}"
    )

    investigation = fixtures.open_investigation(api, ctx["bill_id"], CSR_HEADERS)
    assertions.assert_fields(
        investigation, status="OPEN", shutoff_hold_active=True
    )

    after = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        after,
        balance_cents=30887,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_HELD",
        open_investigation_hold_count=1,
    )
    assert after["shutoff_scheduled_for"] == scheduled_for, (
        "the notice instant must be preserved unchanged across the hold"
    )
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(bill, billing_status="UNDER_INVESTIGATION")


def test_partial_payment_above_the_threshold_moves_neither_state_dimension(api):
    """PRD §2.9: "It is evaluated as a strict precedence chain in which the first matching clause wins: if any arrangement on the account is `DEFAULTED`, the status is `ARRANGEMENT_DEFAULTED`; otherwise if any arrangement on the account is `ACTIVE`, the status is `IN_ARRANGEMENT`; otherwise if `balance_cents` is strictly greater than 5,000 cents (fifty dollars), the status is `PAST_DUE`; otherwise it is `CURRENT`."

    PRD §3.8: "An ad-hoc account payment supplies an `amount_cents` that must be strictly positive, else `ERR_PAYMENT_AMOUNT_INVALID`, plus an optional `memo`; it writes a `PAYMENT` entry with `source_kind` `CUSTOMER_PAYMENT` for the negative amount, with `bill_id` and `source_id` both null and `effective_at` taken from the logical clock, and then recomputes `balance_cents`, `credit_status` and `service_status` in that order."

    Design: Difficulty/non_linear_state_machine/non_linear_parallel_service_and_credit_dimensions_move_independently
    """
    ctx = fixtures.shutoff_held_account(api, target_gallons=12000)
    assertions.assert_account_state(
        ctx["account"],
        balance_cents=30887,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_HELD",
        open_investigation_hold_count=1,
    )
    scheduled_for = ctx["account"]["shutoff_scheduled_for"]

    fixtures.record_account_payment(api, ctx["account_id"], 25000)

    after = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        after,
        balance_cents=5887,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_HELD",
        open_investigation_hold_count=1,
    )
    assert after["shutoff_scheduled_for"] == scheduled_for, (
        "a payment that changes no dimension must not disturb the notice instant"
    )
    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_single_entry(
        entries, "CUSTOMER_PAYMENT", entry_type="PAYMENT", amount_cents=-25000
    )
    assertions.assert_balance_is_ledger_sum(after, entries)


def test_payment_to_the_threshold_moves_both_dimensions_while_the_hold_stands(api):
    """PRD §3.8: "And whenever `credit_status` becomes `CURRENT` or `IN_ARRANGEMENT`, the account returns to `ACTIVE` from `SHUTOFF_HELD`, from `SHUTOFF_SCHEDULED`, or from `SHUTOFF_EXECUTED` — in the last case service is restored — and `shutoff_scheduled_for` is set to null."

    PRD §2.9: "Because clause two outranks clause three, an account with an `ACTIVE` arrangement is never `PAST_DUE` no matter how large its balance grows, and a balance of exactly 5,000 cents with no arrangement is `CURRENT` because the comparison excludes the boundary."

    Design: Difficulty/non_linear_state_machine/non_linear_parallel_service_and_credit_dimensions_move_independently
    """
    ctx = fixtures.shutoff_held_account(api, target_gallons=12000)
    fixtures.record_account_payment(api, ctx["account_id"], 25000)
    fixtures.record_account_payment(api, ctx["account_id"], 887)

    after = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        after,
        balance_cents=constants.PAST_DUE_THRESHOLD_CENTS,
        credit_status="CURRENT",
        service_status="ACTIVE",
        open_investigation_hold_count=1,
    )
    assert after["shutoff_scheduled_for"] is None, (
        "returning to ACTIVE nulls the notice instant"
    )
    # The collections dimension moved while the investigation dimension did not.
    investigation = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(
        investigation, status="OPEN", shutoff_hold_active=True
    )
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(bill, billing_status="UNDER_INVESTIGATION")


# ===========================================================================
# The bench-test fork: three terminals, three different effect sets
# ===========================================================================
def test_bench_pass_forfeits_the_deposit_and_leaves_the_bill_alone(api):
    """PRD §3.4: "**`PASS`** closes the request at `CLOSED_PASS`, sets the meter's `accuracy_status` to `VERIFIED_ACCURATE`, stores `accuracy_pct` and `correction_factor` on the meter, and forfeits the deposit — no refund entry, `deposit_refunded` stays false."

    PRD §3.4: "A meter of 2.0 inches or smaller is graded `AWWA_WEIGHTED`, where `accuracy_pct` is `low_flow_pct` multiplied by fifteen hundredths, plus `mid_flow_pct` multiplied by seventy hundredths, plus `high_flow_pct` multiplied by fifteen hundredths, rounded half up to two decimal places — a weighting that deliberately dominates the composite with mid-flow behaviour."

    Design: Difficulty/non_linear_state_machine/non_linear_branching_bench_result_three_terminals_diverge
    """
    ctx = fixtures.bench_closed_case(api, 100.00, 100.00, 100.00)

    request = ctx["test_request"]
    assertions.assert_fields(
        request,
        status="CLOSED_PASS",
        bench_result="PASS",
        accuracy_method="AWWA_WEIGHTED",
        deposit_refunded=False,
    )
    assert _num(request["accuracy_pct"]) == 100.00

    meter = ctx["meter"]
    assertions.assert_fields(meter, accuracy_status="VERIFIED_ACCURATE")
    assert _num(meter["correction_factor"]) == 1.000000
    assert meter["last_test_completed_at"] is not None

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_single_entry(
        entries, "METER_TEST_DEPOSIT", entry_type="CHARGE", amount_cents=3000
    )
    assertions.assert_no_entry_of_kind(entries, "METER_TEST_DEPOSIT_REFUND")

    # A verified-accurate meter restates nothing: no correction, no rebill.
    corrected = _corrected_reads(api, ctx["meter_id"])
    assert corrected == [], "a passing bench test must create no CORRECTED read"
    assertions.assert_fields(
        ctx["bill"], billing_status="UNDER_INVESTIGATION", consumption_gallons=41000
    )
    assertions.assert_account_state(ctx["account"], open_rebill_count=0)
    investigation = fixtures.fetch_investigation(api, ctx["investigation_id"])
    assertions.assert_fields(investigation, status="EVIDENCE_UNDER_REVIEW")


def test_bench_slow_refunds_the_deposit_but_never_back_bills(api):
    """PRD §3.4: "**`SLOW`** closes the request at `CLOSED_SLOW` and sets the meter's `accuracy_status` to `FAILED_SLOW`, storing `accuracy_pct` and `correction_factor`."

    PRD §3.4: "Critically, **no** `CORRECTED` read is created and **no** bill enters `REBILL_PENDING`: a slow meter under-billed the customer, and the utility does not back-bill for water it failed to measure."

    Design: Difficulty/non_linear_state_machine/non_linear_branching_bench_result_three_terminals_diverge
    """
    ctx = fixtures.bench_closed_case(api, 97.00, 98.20, 98.40)

    request = ctx["test_request"]
    assertions.assert_fields(
        request,
        status="CLOSED_SLOW",
        bench_result="SLOW",
        accuracy_method="AWWA_WEIGHTED",
        deposit_refunded=True,
    )
    assert _num(request["accuracy_pct"]) == 98.05

    meter = ctx["meter"]
    assertions.assert_fields(meter, accuracy_status="FAILED_SLOW")
    assert _num(meter["correction_factor"]) == 1.019888

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_single_entry(
        entries, "METER_TEST_DEPOSIT", entry_type="CHARGE", amount_cents=3000
    )
    assertions.assert_single_entry(
        entries, "METER_TEST_DEPOSIT_REFUND", entry_type="CREDIT", amount_cents=-3000
    )

    corrected = _corrected_reads(api, ctx["meter_id"])
    assert corrected == [], "a slow meter is never back-billed, so no CORRECTED read"
    target_read = validate_success(
        api.get_meter_reading(ctx["target_read_id"], TECHNICIAN_HEADERS)
    )
    assert target_read["superseded_by_reading_id"] is None, (
        "the slow branch supersedes no read"
    )
    assertions.assert_fields(
        ctx["bill"], billing_status="UNDER_INVESTIGATION", consumption_gallons=41000
    )
    assertions.assert_account_state(ctx["account"], open_rebill_count=0)


def test_bench_fast_refunds_the_deposit_corrects_the_read_and_drives_a_rebill(api):
    """PRD §3.4: "**`FAST`** closes the request at `CLOSED_FAST` and refunds the deposit on the same terms as `SLOW`, but it also drives a four-link cascade, because a fast meter over-billed the customer and the record must be restated."

    PRD §3.4: "**Link three**, caused by link two: the bill whose period contains the corrected `read_date` recomputes `consumption_gallons` and every charge field and moves to `REBILL_PENDING`."

    Design: Difficulty/non_linear_state_machine/non_linear_branching_bench_result_three_terminals_diverge
    """
    ctx = fixtures.bench_closed_case(api, 95.20, 103.40, 102.10)

    request = ctx["test_request"]
    assertions.assert_fields(
        request,
        status="CLOSED_FAST",
        bench_result="FAST",
        accuracy_method="AWWA_WEIGHTED",
        deposit_refunded=True,
    )
    assert _num(request["accuracy_pct"]) == 101.98

    meter = ctx["meter"]
    assertions.assert_fields(meter, accuracy_status="FAILED_FAST")
    assert _num(meter["correction_factor"]) == 0.980584

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_single_entry(
        entries, "METER_TEST_DEPOSIT_REFUND", entry_type="CREDIT", amount_cents=-3000
    )

    corrected = _corrected_reads(api, ctx["meter_id"])
    assert len(corrected) == 1, (
        f"exactly one CORRECTED read is expected, found {len(corrected)}"
    )
    assertions.assert_fields(
        corrected[0],
        read_type="CORRECTED",
        reading_value=152204,
        corrects_reading_id=ctx["target_read_id"],
        consumption_since_prior_gallons=40204,
    )
    target_read = validate_success(
        api.get_meter_reading(ctx["target_read_id"], TECHNICIAN_HEADERS)
    )
    assert target_read["superseded_by_reading_id"] == corrected[0]["id"]

    water, sewer, total = constants.PINNED_CHARGES[("SUMMER", 40204)]
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(bill, billing_status="REBILL_PENDING")
    assertions.assert_bill_charges(
        bill,
        consumption_gallons=40204,
        water_charge_cents=water,
        sewer_charge_cents=sewer,
        total_charge_cents=total,
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]), open_rebill_count=1
    )

    # Only the corrected period's bill moved; settled history is untouched.
    for history_bill_id in ctx["history_bill_ids"]:
        assertions.assert_fields(
            fixtures.fetch_bill(api, history_bill_id), billing_status="ISSUED"
        )


def test_a_closed_bench_request_refuses_a_second_bench_result(api):
    """PRD §3.4: "The bench test supplies `tested_at` together with three registration percentages, `low_flow_pct`, `mid_flow_pct` and `high_flow_pct`, and is available only from `BENCH_TEST_PENDING`."

    PRD §2.7: "**State preconditions.** The subject entity must sit in a state from which the requested transition exists, and every cross-entity state precondition of that transition must hold → `ERR_INVALID_STATE_TRANSITION` (409) on every action operation."

    Design: Difficulty/non_linear_state_machine/non_linear_branching_bench_result_three_terminals_diverge
    """
    ctx = fixtures.bench_closed_case(api, 100.00, 100.00, 100.00)
    assertions.assert_fields(ctx["test_request"], status="CLOSED_PASS")

    response = api.record_bench_result(
        ctx["test_request_id"],
        factories.bench_result_payload(
            90.00, 90.00, 90.00, tested_at="2026-08-04T09:00:00Z"
        ),
        TECHNICIAN_HEADERS,
    )
    validate_error(response, "ERR_INVALID_STATE_TRANSITION")

    after = validate_success(
        api.get_meter_test_request(ctx["test_request_id"], SUPERVISOR_HEADERS)
    )
    assertions.assert_fields(
        after, status="CLOSED_PASS", bench_result="PASS", deposit_refunded=False
    )
    assert _num(after["accuracy_pct"]) == 100.00
    assertions.assert_fields(
        fixtures.fetch_meter(api, ctx["meter_id"]),
        accuracy_status="VERIFIED_ACCURATE",
    )
