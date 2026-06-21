"""Deterministic error selection when multiple checks could fire, and the two
temporal windows (timely filing, bad-debt aging).

Queue A (difficulty) instances:
  priority_pair_validation_conflict / state_beats_fiscal_overpayment_on_terminal_statement
  priority_pair_validation_conflict / state_beats_temporal_appeal_on_nonappealable_denial
  resource_temporal_overlap / timely_filing_window_closed_at_boundary
  resource_temporal_overlap / bad_debt_aging_window_not_met
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, ApiErrorId,
    create_active_policy, create_encounter, add_charge, run_eligibility,
    setup_partially_paid_statement, setup_submitted_claim, setup_coded_encounter,
    setup_denied_statement,
    submit_claim, submit_claim_payload, deny, payment_payload, set_clock,
)
from test_helpers import api_client as _api

REGISTRAR = TEST_USERS["registrar_headers"]
CODER = TEST_USERS["coder_headers"]
BILLING = TEST_USERS["billing_headers"]


# ===========================================================================
# priority_pair_validation_conflict / state_beats_fiscal_overpayment_on_terminal_statement
# ===========================================================================
def test_payment_on_paid_statement_returns_invalid_state_not_overpayment(api):
    """PRD §2.7: "Sixth, the target resource's state is checked: if the requested transition
    is not defined from the resource's current state, the request yields ERR_INVALID_STATE
    (409). Only after all six of these structural gates pass are the domain-specific business
    rules of §3 - referential, safety, temporal, fiscal, and concurrency checks - evaluated."

    A PAID (terminal) statement: a further payment both violates state and would be an
    overpayment; the state gate fires first => ERR_INVALID_STATE, not ERR_OVERPAYMENT.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_overpayment_on_terminal_statement
    """
    payer, patient, policy, encounter, coding, claim, statement = setup_partially_paid_statement(
        allowed_amount_cents=200000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    # Pay it off fully -> statement PAID (terminal).
    paid = validate_success(
        _api.post_payment(statement["id"], payment_payload(120000), BILLING),
        expected_status=201,
    )
    stmt = validate_success(api.get_statement(statement["id"], BILLING))
    assert stmt["status"] == "PAID"
    # Now a further (over)payment: state error must win.
    resp = _api.post_payment(statement["id"], payment_payload(999999), BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_overpayment_on_issued_statement_returns_overpayment(api):
    """PRD §3.10: "A payment may not exceed the statement's outstanding balance - the
    statement's amount_due_cents minus its amount_paid_cents - and an overpayment is rejected
    with ERR_OVERPAYMENT."

    On an ISSUED (non-terminal) statement the state gate passes, so the fiscal overpayment
    rule is the one that fires - the contrast that makes the terminal-state case meaningful.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_overpayment_on_terminal_statement
    """
    payer, patient, policy, encounter, coding, claim, statement = setup_partially_paid_statement(
        allowed_amount_cents=200000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    stmt = validate_success(api.get_statement(statement["id"], BILLING))
    assert stmt["status"] == "ISSUED"
    resp = _api.post_payment(statement["id"], payment_payload(130000), BILLING)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value, expected_status=422)


# ===========================================================================
# priority_pair_validation_conflict / state_beats_temporal_appeal_on_nonappealable_denial
# ===========================================================================
def test_appeal_on_coding_error_denial_past_window_returns_not_appealable(api):
    """PRD §3.9: "Appeal is defined only from DENIED status with one of those two reasons; an
    appeal attempt on a denial with any other reason is rejected with ERR_NOT_APPEALABLE.
    Appeal additionally requires that the current clock time is within the payer's
    appeal_window_days measured from the claim's submitted_at; an appeal filed after that
    window is rejected with ERR_APPEAL_WINDOW_CLOSED."

    A CODING_ERROR denial is not appealable; even past the appeal window the appealability
    gate ("additionally") fires first => ERR_NOT_APPEALABLE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_appeal_on_nonappealable_denial
    """
    set_clock("2026-03-01T00:00:00Z")
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    deny(claim["id"], "CODING_ERROR")
    set_clock("2026-06-01T00:00:00Z")  # well past appeal_window_days (30)
    resp = api.appeal_claim(claim["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_NOT_APPEALABLE.value, expected_status=409)


def test_appeal_on_not_covered_denial_past_window_returns_window_closed(api):
    """PRD §3.9: "Appeal additionally requires that the current clock time is within the
    payer's appeal_window_days measured from the claim's submitted_at; an appeal filed after
    that window is rejected with ERR_APPEAL_WINDOW_CLOSED."

    A NOT_COVERED denial IS appealable, so past the window the temporal gate is the one that
    fires - the contrast against the non-appealable case above.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_appeal_on_nonappealable_denial
    """
    set_clock("2026-03-01T00:00:00Z")
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    deny(claim["id"], "NOT_COVERED")
    set_clock("2026-06-01T00:00:00Z")  # past appeal_window_days (30)
    resp = api.appeal_claim(claim["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value, expected_status=409)


# ===========================================================================
# resource_temporal_overlap / timely_filing_window_closed_at_boundary
# ===========================================================================
def test_claim_submitted_past_timely_filing_rejected(api):
    """PRD §3.7: "the claim must be submitted within the payer's timely_filing_days measured
    from the encounter's discharge_at, and a submission later than that window is rejected with
    ERR_TIMELY_FILING_EXCEEDED."

    Discharge anchored on 2026-02-28, timely_filing_days 90, clock advanced to 2026-06-15
    (>90 days later) => submission rejected.

    Design: Difficulty/resource_temporal_overlap/timely_filing_window_closed_at_boundary
    """
    set_clock("2026-03-01T00:00:00Z")
    payer, patient, policy, encounter, coding = setup_coded_encounter(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    # discharge_at was stamped at the current clock (2026-03-01); advance well past 90 days.
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    set_clock("2026-06-15T00:00:00Z")
    resp = _api.submit_claim(
        encounter["id"], submit_claim_payload(payer["id"], enc["version"]), BILLING
    )
    validate_error(resp, ApiErrorId.ERR_TIMELY_FILING_EXCEEDED.value, expected_status=409)


def test_claim_submitted_within_timely_filing_succeeds(api):
    """PRD §3.7: "the claim must be submitted within the payer's timely_filing_days measured
    from the encounter's discharge_at".

    Submission on the same day as discharge is comfortably within the 90-day window => succeeds.

    Design: Difficulty/resource_temporal_overlap/timely_filing_window_closed_at_boundary
    """
    set_clock("2026-03-01T00:00:00Z")
    payer, patient, policy, encounter, coding = setup_coded_encounter(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    data = validate_success(
        _api.submit_claim(encounter["id"], submit_claim_payload(payer["id"], enc["version"]), BILLING),
        expected_status=201,
    )
    assert data["status"] == "SUBMITTED"


# ===========================================================================
# resource_temporal_overlap / bad_debt_aging_window_not_met
# ===========================================================================
def test_send_to_collections_before_aging_rejected(api):
    """PRD §3.11: "A BillingSpecialist may send a statement to collections, which is permitted
    from ISSUED or PARTIALLY_PAID status but only once the statement has aged sufficiently: the
    current clock time must be at least 120 days after the statement's issued_at. A
    send-to-collections attempt before that aging threshold is rejected with ERR_AGING_NOT_MET."

    Statement issued at 2026-03-10, clock only 2026-03-20 (10 days) => rejected.

    Design: Difficulty/resource_temporal_overlap/bad_debt_aging_window_not_met
    """
    set_clock("2026-03-10T00:00:00Z")
    payer, patient, policy, encounter, coding, claim, statement = setup_denied_statement(
        denial_reason="NOT_COVERED", charge_cents=300000,
        deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    set_clock("2026-03-20T00:00:00Z")
    resp = api.send_statement_to_collections(statement["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_AGING_NOT_MET.value, expected_status=409)


def test_send_to_collections_after_aging_succeeds(api):
    """PRD §3.11: "the current clock time must be at least 120 days after the statement's
    issued_at. ... On success the statement moves to IN_COLLECTIONS."

    Clock advanced well past 120 days after issue => send-to-collections succeeds.

    Design: Difficulty/resource_temporal_overlap/bad_debt_aging_window_not_met
    """
    set_clock("2026-03-10T00:00:00Z")
    payer, patient, policy, encounter, coding, claim, statement = setup_denied_statement(
        denial_reason="NOT_COVERED", charge_cents=300000,
        deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    set_clock("2026-08-01T00:00:00Z")
    data = validate_success(api.send_statement_to_collections(statement["id"], BILLING))
    assert data["status"] == "IN_COLLECTIONS", (
        f"expected IN_COLLECTIONS, got {data['status']}"
    )
