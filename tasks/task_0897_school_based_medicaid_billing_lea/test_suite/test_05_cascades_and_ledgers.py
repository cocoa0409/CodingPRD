"""Cascading state propagation (student withdraw, authorization discontinue) and
the two conservation ledgers (money and units) under compensating voids.
"""
from test_helpers import (
    TEST_USERS, get_success_data, validate_success,
    setup_billing_context, create_verified_log, create_documented_log,
    setup_claim_with_verified_log, submit_claim, approve_claim, void_claim,
    api_client,
)

MC = TEST_USERS["medicaid_coordinator_headers"]
BC = TEST_USERS["billing_coordinator_headers"]


# --- transitive_cascade / student_withdraw_depth3_cascade --------------------
def _withdrawn_student_with_verified_log():
    ctx = setup_billing_context()
    log = create_verified_log(ctx["authorization"]["id"], ctx["provider"]["id"],
                              ctx["student"]["id"], delivered_minutes=40)
    ctx["log"] = log
    ctx["student"] = get_success_data(api_client.withdraw_student(ctx["student"]["id"], MC))
    return ctx


def test_withdraw_discontinues_student_and_authorization(api):
    """PRD §3.9: "A MedicaidCoordinator withdraws an active student, moving the
    student from ACTIVE to the terminal WITHDRAWN. As a first cascade hop, every
    IEPAuthorization of that student whose status is ACTIVE is discontinued,
    moving from ACTIVE to DISCONTINUED."

    Design: Difficulty/transitive_cascade/student_withdraw_depth3_cascade
    """
    ctx = _withdrawn_student_with_verified_log()
    assert ctx["student"]["status"] == "WITHDRAWN"
    assert get_success_data(api.get_authorization(ctx["authorization"]["id"], MC))["status"] == "DISCONTINUED"


def test_withdraw_voids_verified_log_and_reverses_unit_ledger(api):
    """PRD §3.9: "every service log referencing that authorization whose status is
    LOGGED, DOCUMENTED, or VERIFIED is voided, moving to the terminal VOID. That
    void is the third hop and carries the ledger consequence: a voided log that
    had been VERIFIED decreases the student's verified_service_units by its
    delivered_units, exactly as a direct void would."

    Design: Difficulty/transitive_cascade/student_withdraw_depth3_cascade
    """
    ctx = _withdrawn_student_with_verified_log()
    assert get_success_data(api.get_service_log(ctx["log"]["id"], MC))["status"] == "VOID"
    assert get_success_data(api.get_student(ctx["student"]["id"], MC))["verified_service_units"] == 0


# --- transitive_cascade / authorization_discontinue_depth2_cascade -----------
def _discontinued_auth_with_documented_log():
    ctx = setup_billing_context()
    log = create_documented_log(ctx["authorization"]["id"], ctx["provider"]["id"], ctx["student"]["id"])
    ctx["log"] = log
    ctx["authorization"] = get_success_data(
        api_client.discontinue_authorization(ctx["authorization"]["id"], MC))
    return ctx


def test_discontinue_voids_documented_log(api):
    """PRD §3.9: "Discontinuing an authorization — whether reached through this
    withdrawal cascade or invoked directly on an active authorization — is itself
    the second hop: every service log referencing that authorization whose status
    is LOGGED, DOCUMENTED, or VERIFIED is voided, moving to the terminal VOID."

    Design: Difficulty/transitive_cascade/authorization_discontinue_depth2_cascade
    """
    ctx = _discontinued_auth_with_documented_log()
    assert ctx["authorization"]["status"] == "DISCONTINUED"
    assert get_success_data(api.get_service_log(ctx["log"]["id"], MC))["status"] == "VOID"


def test_discontinue_of_documented_log_leaves_unit_ledger_at_zero(api):
    """PRD §3.9: "Logs already attached to claims (those in CLAIMED, PAID, or
    DENIED) are not swept up by this cascade; only the non-terminal, not-yet-billed
    logs are voided."

    Design: Difficulty/transitive_cascade/authorization_discontinue_depth2_cascade
    """
    ctx = _discontinued_auth_with_documented_log()
    # The log never reached VERIFIED, so the unit ledger was never advanced.
    assert get_success_data(api.get_student(ctx["student"]["id"], MC))["verified_service_units"] == 0
    assert get_success_data(api.get_service_log(ctx["log"]["id"], MC))["status"] == "VOID"


# --- compensating_invariant / interim_paid_ledger_conserved_on_void ----------
def _paid_then_voided_claim():
    ctx = setup_claim_with_verified_log()
    submit_claim(ctx["claim"]["id"])
    approve_claim(ctx["claim"]["id"])
    ctx["claim"] = void_claim(ctx["claim"]["id"])
    return ctx


def test_void_paid_claim_zeroes_claim_interim_payment(api):
    """PRD §3.6: "Voiding a PAID claim additionally recoups money: the student's
    interim_paid_cents ledger is decreased by the claim's interim_payment_cents,
    each attached log moves from PAID back to VERIFIED and is detached, and
    total_charge_cents, interim_payment_cents, and attached_log_count are all
    zeroed."

    Design: Difficulty/compensating_invariant/interim_paid_ledger_conserved_on_void
    """
    ctx = _paid_then_voided_claim()
    assert ctx["claim"]["status"] == "VOID"
    assert ctx["claim"]["interim_payment_cents"] == 0


def test_void_paid_claim_restores_student_money_ledger_and_log(api):
    """PRD §3.6: "Voiding a PAID claim additionally recoups money: the student's
    interim_paid_cents ledger is decreased by the claim's interim_payment_cents,
    each attached log moves from PAID back to VERIFIED and is detached".

    Design: Difficulty/compensating_invariant/interim_paid_ledger_conserved_on_void
    """
    ctx = _paid_then_voided_claim()
    assert get_success_data(api.get_student(ctx["student"]["id"], MC))["interim_paid_cents"] == 0
    assert get_success_data(api.get_service_log(ctx["log"]["id"], MC))["status"] == "VERIFIED"


# --- compensating_invariant / verified_units_conserved_on_void ---------------
def _verified_then_voided_log():
    ctx = setup_billing_context()
    log = create_verified_log(ctx["authorization"]["id"], ctx["provider"]["id"],
                              ctx["student"]["id"], delivered_minutes=40)
    ctx["log"] = log
    ctx["voided_log"] = get_success_data(api_client.void_service_log(log["id"], BC))
    return ctx


def test_void_verified_log_moves_to_void(api):
    """PRD §3.4: "A verified log that has not yet been attached to a claim (its
    claim_id is still null) may be voided by a coordinator, moving it to the
    terminal VOID state".

    Design: Difficulty/compensating_invariant/verified_units_conserved_on_void
    """
    ctx = _verified_then_voided_log()
    assert ctx["voided_log"]["status"] == "VOID"


def test_void_verified_log_reverses_unit_ledger(api):
    """PRD §3.4: "because that log had contributed to the ledger, voiding it
    decreases the student's verified_service_units by its delivered_units,
    reversing the earlier increase."

    Design: Difficulty/compensating_invariant/verified_units_conserved_on_void
    """
    ctx = _verified_then_voided_log()
    assert get_success_data(api.get_student(ctx["student"]["id"], MC))["verified_service_units"] == 0
