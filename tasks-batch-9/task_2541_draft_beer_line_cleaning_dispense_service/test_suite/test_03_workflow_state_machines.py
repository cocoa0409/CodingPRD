"""Workflows that revisit a state they have already been in, carrying new figures."""

from test_helpers import (
    ApiErrorId,
    ComplaintStatus,
    FindingCode,
    SettlementState,
    VerificationStatus,
    assert_instant,
    assert_liters,
    assert_program_ledger,
    fixtures,
    validate_error,
)
from test_helpers.test_users import AUDITOR_HEADERS, SECOND_AUDITOR_HEADERS


def _never_cleaned_line_complaint(api):
    """A line plumbed at the epoch, complained about ten days later, never cleaned."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(api, venue_name="Loop Lounge")
    fixtures.set_clock(api, "2026-08-11T00:00:00Z")
    complaint = fixtures.file_complaint(
        api, venue["account"]["id"], venue["lines"][0]["id"], "SLOW_POUR"
    )
    return venue, complaint


def test_diagnosis_and_parts_waiting_alternate_until_the_third_round_burns_the_cap(api):
    """PRD §3.8: "From `DIAGNOSING`, needing parts moves it `DIAGNOSING → AWAITING_PARTS`.
    From `AWAITING_PARTS`, finding the root cause moves it back
    `AWAITING_PARTS → DIAGNOSING`."
    PRD §3.8: "At most three rounds may ever be logged on one complaint — the
    `diagnostic_round` count must be below three, else `ERR_DIAGNOSTIC_ROUNDS_EXHAUSTED`, and
    the fourth round is refused with the instruction implicit that the complaint must now be
    closed one way or the other."

    Design: Difficulty/non_linear_state_machine/complaint_alternates_diagnosing_and_awaiting_parts_until_round_cap_then_reopens
    """
    venue, complaint = _never_cleaned_line_complaint(api)
    assert complaint["days_at_risk"] == 10
    assert_liters(complaint["provisional_yield_loss_liters"], 18.00)
    assert complaint["provisional_yield_loss_cents"] == 8640

    first = fixtures.run_diagnostic_round(
        api, complaint["id"], outcome="ROOT_CAUSE_FOUND", finding_code=FindingCode.LINE_SOIL
    )
    assert first["status"] == ComplaintStatus.DIAGNOSING
    assert first["diagnostic_round"] == 1
    assert first["last_finding_code"] == FindingCode.LINE_SOIL

    second = fixtures.run_diagnostic_round(
        api, complaint["id"], outcome="PARTS_REQUIRED", finding_code=FindingCode.FAUCET_WEAR
    )
    assert second["status"] == ComplaintStatus.AWAITING_PARTS
    assert second["diagnostic_round"] == 2

    third = fixtures.run_diagnostic_round(
        api, complaint["id"], outcome="ROOT_CAUSE_FOUND", finding_code=FindingCode.FAUCET_WEAR
    )
    assert third["status"] == ComplaintStatus.DIAGNOSING, (
        "the third round walks back out of parts-waiting into diagnosis"
    )
    assert third["diagnostic_round"] == 3

    refused = api.record_diagnostic_round(
        complaint["id"],
        {"outcome": "ROOT_CAUSE_FOUND", "finding_code": FindingCode.GAS_IMBALANCE},
        AUDITOR_HEADERS,
    )
    validate_error(refused, ApiErrorId.DIAGNOSTIC_ROUNDS_EXHAUSTED, 422)

    after = fixtures.read_complaint(api, complaint["id"])
    assert after["diagnostic_round"] == 3, "the refused round burns nothing"
    assert after["status"] == ComplaintStatus.DIAGNOSING
    assert after["last_finding_code"] == FindingCode.FAUCET_WEAR, (
        "the refused round must not overwrite the standing theory"
    )


def test_reopening_re_arms_the_round_counter_without_re_snapshotting_intake(api):
    """PRD §3.8: "Reopening raises `reopen_count` by 1, resets `diagnostic_round` to 0
    so a fresh set of three rounds becomes available, and clears `resolved_at`,
    `closed_by_user_id`, `measured_waste_liters`, `settled_yield_loss_liters` and
    `settled_yield_loss_cents` back to null."
    PRD §3.8: "What survives the loop is the intake snapshot: `reported_at`,
    `days_at_risk` and both provisional figures are never recomputed, so the estimate a
    reopened complaint carries is still the one struck the day it was first filed."

    Design: Difficulty/non_linear_state_machine/complaint_alternates_diagnosing_and_awaiting_parts_until_round_cap_then_reopens
    """
    venue, complaint = _never_cleaned_line_complaint(api)
    fixtures.run_diagnostic_round(
        api, complaint["id"], outcome="ROOT_CAUSE_FOUND", finding_code=FindingCode.LINE_SOIL
    )
    fixtures.run_diagnostic_round(
        api, complaint["id"], outcome="PARTS_REQUIRED", finding_code=FindingCode.FAUCET_WEAR
    )
    fixtures.run_diagnostic_round(
        api, complaint["id"], outcome="ROOT_CAUSE_FOUND", finding_code=FindingCode.FAUCET_WEAR
    )

    fixtures.set_clock(api, "2026-08-12T00:00:00Z")
    closed = fixtures.close_complaint(
        api,
        complaint["id"],
        disposition="RESOLVED",
        measured_waste_liters=4.0,
        headers=SECOND_AUDITOR_HEADERS,
    )
    assert_liters(closed["settled_yield_loss_liters"], 5.00)
    assert closed["settled_yield_loss_cents"] == 2400

    reopened = fixtures.reopen_complaint(
        api,
        complaint["id"],
        venue["account"]["id"],
        reopen_reason="Foam returned within a day of the repair.",
    )

    assert reopened["status"] == ComplaintStatus.OPEN
    assert reopened["reopen_count"] == 1
    assert reopened["diagnostic_round"] == 0, "a fresh set of three rounds is available"
    assert reopened["settled_yield_loss_liters"] is None
    assert reopened["settled_yield_loss_cents"] is None
    assert reopened["measured_waste_liters"] is None
    assert reopened["resolved_at"] is None
    assert reopened["days_at_risk"] == 10, "the exposure window is not re-measured"
    assert reopened["provisional_yield_loss_cents"] == 8640
    account = fixtures.read_account(api, venue["account"]["id"])
    assert account["open_complaint_count"] == 1, "a reopened complaint counts as open again"


def _funded_visit_ready_to_sign(api):
    """A three-line job on a brewer-funded contract, closed out and awaiting sign-off."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    program = fixtures.create_brewer_program(
        api,
        brewer_name="Northside Brewing",
        funded_scope="CLEANING_AND_PARTS",
        co_pay_bps=2000,
        funding_cap_cents=50000,
    )
    ground = fixtures.setup_three_line_visit_with_work(
        api, venue_name="Dispute Depot", brewer_program_id=program["id"]
    )
    ground["program"] = program
    assert ground["visit"]["provisional_charge_cents"] == 24474
    fixtures.set_clock(api, "2026-08-05T12:00:00Z")
    return ground


def test_a_dispute_reverses_the_settlement_it_is_lodged_against(api):
    """PRD §3.7: "The visit's `settlement_state` becomes `REVERSED` and its
    `settled_charge_cents`, `brewer_funded_cents`, `account_due_cents` and
    `cleaning_subtotal_cents` are all reset to 0."
    PRD §3.7: "The visit's `settlement_state` becomes `REVERSED` and its
    `settled_charge_cents`, `brewer_funded_cents`, `account_due_cents` and
    `cleaning_subtotal_cents` are all reset to 0."

    Design: Difficulty/non_linear_state_machine/verification_signs_disputes_and_resigns_at_a_different_amount
    """
    ground = _funded_visit_ready_to_sign(api)

    signed = fixtures.sign_visit(api, ground["visit"]["id"], ground["account"]["id"])
    assert signed["verification_status"] == VerificationStatus.SIGNED
    assert signed["settlement_state"] == SettlementState.SETTLED
    assert signed["cleaning_subtotal_cents"] == 9186
    assert signed["settled_charge_cents"] == 19881
    assert signed["brewer_funded_cents"] == 9904, (
        f"7348 of cleaning plus 2556 of parts is 9904, got {signed['brewer_funded_cents']}"
    )
    assert signed["account_due_cents"] == 9977
    assert_program_ledger(
        fixtures.read_program(api, ground["program"]["id"]), 9904, 40096, "ACTIVE"
    )

    fixtures.set_clock(api, "2026-08-06T12:00:00Z")
    disputed = fixtures.dispute_visit(
        api,
        ground["visit"]["id"],
        ground["account"]["id"],
        dispute_reason="Line 2 was never actually recirculated.",
    )

    assert disputed["verification_status"] == VerificationStatus.DISPUTED
    assert disputed["settlement_state"] == SettlementState.REVERSED
    assert disputed["settled_charge_cents"] == 0
    assert disputed["brewer_funded_cents"] == 0
    assert disputed["account_due_cents"] == 0
    assert disputed["cleaning_subtotal_cents"] == 0
    assert disputed["provisional_charge_cents"] == 24474, (
        "the provisional figure is frozen and survives the reversal"
    )
    assert_program_ledger(
        fixtures.read_program(api, ground["program"]["id"]), 0, 50000, "ACTIVE"
    )


def test_re_signing_after_a_void_settles_the_same_visit_at_a_new_amount(api):
    """PRD §3.7: "A re-signature moves `DISPUTED → SIGNED` and is where the two-sided
    cycle earns its keep. The `signer_name` is overwritten, `signed_at` is stamped
    afresh — restarting the dispute window this time — and the settled variant is
    re-run with no withholding **against the current compliance picture**, so a cycle
    voided while the visit sat in dispute changes the amount owed."
    PRD §3.7: "Voided cycles are excluded from both line counts, so voiding the only
    passing cycle on a line drops that line out of the settled inclusion set entirely."

    Design: Difficulty/non_linear_state_machine/verification_signs_disputes_and_resigns_at_a_different_amount
    """
    ground = _funded_visit_ready_to_sign(api)
    fixtures.sign_visit(api, ground["visit"]["id"], ground["account"]["id"])
    fixtures.set_clock(api, "2026-08-06T12:00:00Z")
    fixtures.dispute_visit(
        api,
        ground["visit"]["id"],
        ground["account"]["id"],
        dispute_reason="Line 2 was never actually recirculated.",
    )

    voided = fixtures.void_cycle(
        api, ground["cycles"][1]["id"], "Recirculation not performed on line 2."
    )
    assert voided["record_status"] == "VOIDED"
    after_void = fixtures.read_visit(api, ground["visit"]["id"])
    assert after_void["serviced_line_count"] == 2, "the voided line leaves both line counts"

    fixtures.set_clock(api, "2026-08-07T12:00:00Z")
    resigned = fixtures.sign_visit(api, ground["visit"]["id"], ground["account"]["id"])

    assert resigned["verification_status"] == VerificationStatus.SIGNED
    assert resigned["settlement_state"] == SettlementState.SETTLED
    assert resigned["billable_line_count"] == 1, (
        f"only line 1 still holds a passing cycle, got {resigned['billable_line_count']}"
    )
    assert resigned["cleaning_subtotal_cents"] == 4593
    assert resigned["settled_charge_cents"] == 15288, (
        f"7500 base plus 4593 cleaning plus 3195 parts is 15288, got {resigned['settled_charge_cents']}"
    )
    assert resigned["brewer_funded_cents"] == 6230, (
        f"3674 of cleaning plus 2556 of parts is 6230, got {resigned['brewer_funded_cents']}"
    )
    assert resigned["account_due_cents"] == 9058
    assert resigned["provisional_charge_cents"] == 24474
    # The re-signature stamps a fresh signature instant.
    assert_instant(resigned["signed_at"], "2026-08-07T12:00:00Z", label="signed_at")
    assert_program_ledger(
        fixtures.read_program(api, ground["program"]["id"]), 6230, 43770, "ACTIVE"
    )
