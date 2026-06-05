"""Overpayments: fraud penalty, waiver eligibility, recovery ledger, the
exact-total SATISFIED boundary, the assessed-total conservation invariant, and
the recovery OCC stale-version guard."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_overpayment, establish_overpayment, apply_recovery,
    current_overpayment_version,
    assert_overpayment, assert_overpayment_recovery, assert_overpayment_conserved,
    TEST_USERS,
)

ADJ = TEST_USERS["adjudicator_headers"]
BPO = TEST_USERS["benefit_payment_officer_headers"]


# ── Difficulty: boundary_precision_check / overpayment_satisfied_at_exact_total_not_over ──

def test_recovery_to_exact_total_satisfies(api):
    """PRD §3.8: "A recovery that brings recovered_cents to exactly
    total_assessed_cents moves the overpayment to SATISFIED — whether that
    satisfying recovery arrives from ESTABLISHED (a single recovery equal to the
    whole assessed total) or from RECOVERING."

    Design: Difficulty/boundary_precision_check/overpayment_satisfied_at_exact_total_not_over
    """
    # NONFRAUD principal 40000, total 40000. First CASH 25000 -> RECOVERING; then
    # CASH 15000 -> recovered 40000 exactly -> SATISFIED.
    scenario = make_overpayment(cause="NONFRAUD", principal_cents=40000)
    op = scenario["overpayment"]
    apply_recovery(op["id"], 25000, op["version"], recovery_method="CASH")
    v1 = current_overpayment_version(op["id"])
    apply_recovery(op["id"], 15000, v1, recovery_method="CASH")
    op_after = get_success_data(api_client.get_overpayment(op["id"], BPO))
    assert_overpayment(op_after)
    assert op_after["recovered_cents"] == 40000
    assert op_after["status"] == "SATISFIED"
    assert_overpayment_conserved(op_after)


def test_recovery_over_total_rejected(api):
    """PRD §3.8: "A recovery whose amount_cents would push recovered_cents above
    total_assessed_cents is rejected with ERR_OVER_RECOVERY — recoveries may bring
    the running total up to the assessed total exactly, but never past it."

    Design: Difficulty/boundary_precision_check/overpayment_satisfied_at_exact_total_not_over
    """
    # NONFRAUD total 40000; first CASH 25000 (RECOVERING); a 15001 recovery would
    # reach 40001 (> total) -> ERR_OVER_RECOVERY.
    scenario = make_overpayment(cause="NONFRAUD", principal_cents=40000)
    op = scenario["overpayment"]
    apply_recovery(op["id"], 25000, op["version"], recovery_method="CASH")
    v1 = current_overpayment_version(op["id"])
    res = api.create_recovery(
        op["id"],
        {"recovery_method": "CASH", "amount_cents": 15001,
         "expected_overpayment_version": v1},
        BPO)
    validate_error(res, "ERR_OVER_RECOVERY", expected_status=422)


# ── Difficulty: compensating_invariant / overpayment_offset_conserves_assessed_total ──

def test_fraud_penalty_and_two_recoveries_conserve_assessed_total(api):
    """PRD §3.8: "for a FRAUD overpayment, penalty_cents is fifteen percent of the
    principal_cents, resolved to whole cents using round-half-up ... The
    total_assessed_cents is the principal_cents plus the penalty_cents".
    PRD §3.8: "Each applied recovery adds its amount_cents to the overpayment's
    recovered_cents."

    Design: Difficulty/compensating_invariant/overpayment_offset_conserves_assessed_total
    """
    # FRAUD principal 50000 -> penalty 7500, total 57500. CASH 50000 then 7500 ->
    # recovered 57500 == total_assessed -> SATISFIED, no residual.
    scenario = make_overpayment(cause="FRAUD", principal_cents=50000)
    op = scenario["overpayment"]
    assert op["total_assessed_cents"] == 57500
    apply_recovery(op["id"], 50000, op["version"], recovery_method="CASH")
    v1 = current_overpayment_version(op["id"])
    apply_recovery(op["id"], 7500, v1, recovery_method="CASH")
    op_after = get_success_data(api_client.get_overpayment(op["id"], BPO))
    assert op_after["recovered_cents"] == 57500
    assert op_after["total_assessed_cents"] == 57500
    assert op_after["status"] == "SATISFIED"
    assert_overpayment_conserved(op_after)


def test_fraud_penalty_computed_at_establishment(api):
    """PRD §3.8: "for a FRAUD overpayment, penalty_cents is fifteen percent of the
    principal_cents, resolved to whole cents using round-half-up ... strictly
    greater than the principal for fraud".

    Design: Difficulty/compensating_invariant/overpayment_offset_conserves_assessed_total
    """
    scenario = make_overpayment(cause="FRAUD", principal_cents=50000)
    op = scenario["overpayment"]
    assert op["penalty_cents"] == 7500
    assert op["total_assessed_cents"] == 57500
    assert op["status"] == "ESTABLISHED"
    assert op["recovered_cents"] == 0


# ── Difficulty: priority_pair_validation_conflict / waiver_state_beats_waiver_fiscal_eligibility ──

def test_waive_recovering_fraud_overpayment_is_invalid_state(api):
    """PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (ERR_INVALID_STATE). Only after all of those pass does
    the system evaluate the operation-specific business rules — timeliness,
    segregation of duties, work-search sufficiency, availability, waiver
    eligibility".
    PRD §3.8: "Alternatively, an Adjudicator may waive an overpayment, moving it
    ESTABLISHED → WAIVED."

    Design: Difficulty/priority_pair_validation_conflict/waiver_state_beats_waiver_fiscal_eligibility
    """
    # FRAUD principal 50000 (total 57500), one CASH 10000 -> RECOVERING. Waive is
    # only defined from ESTABLISHED, so the state check (priority 7) pre-empts the
    # waiver-eligibility (priority 12) FRAUD gate -> ERR_INVALID_STATE.
    scenario = make_overpayment(cause="FRAUD", principal_cents=50000)
    op = scenario["overpayment"]
    apply_recovery(op["id"], 10000, op["version"], recovery_method="CASH")
    res = api.waive_overpayment(op["id"], {}, ADJ)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_waive_established_fraud_overpayment_is_waiver_not_allowed(api):
    """PRD §3.8: "Waiver is permitted only when the overpayment's cause is NONFRAUD
    and its recovered_cents is 0 — a fraud overpayment can never be waived, and one
    with any recovery already applied can no longer be waived; either condition is
    rejected with ERR_WAIVER_NOT_ALLOWED."

    Design: Difficulty/priority_pair_validation_conflict/waiver_state_beats_waiver_fiscal_eligibility
    """
    # ESTABLISHED FRAUD with nothing recovered: state check passes (ESTABLISHED is
    # the from-state for waive), so the FRAUD waiver-eligibility gate fires.
    scenario = make_overpayment(cause="FRAUD", principal_cents=50000)
    res = api.waive_overpayment(scenario["overpayment"]["id"], {}, ADJ)
    validate_error(res, "ERR_WAIVER_NOT_ALLOWED", expected_status=422)


# ── Corner: validations / nonfraud_overpayment_waiver_succeeds ──

def test_nonfraud_waiver_succeeds(api):
    """PRD §3.8: "Waiver is permitted only when the overpayment's cause is NONFRAUD
    and its recovered_cents is 0".
    PRD §3.8: "an Adjudicator may waive an overpayment, moving it
    ESTABLISHED → WAIVED."

    Design: Corner/validations/nonfraud_overpayment_waiver_succeeds
    """
    scenario = make_overpayment(cause="NONFRAUD", principal_cents=30000)
    op = get_success_data(api.waive_overpayment(scenario["overpayment"]["id"], {}, ADJ))
    assert op["status"] == "WAIVED"


# ── Corner: validations / fraud_overpayment_waiver_rejected ──

def test_fraud_waiver_rejected(api):
    """PRD §3.8: "a fraud overpayment can never be waived ... either condition is
    rejected with ERR_WAIVER_NOT_ALLOWED."

    Design: Corner/validations/fraud_overpayment_waiver_rejected
    """
    scenario = make_overpayment(cause="FRAUD", principal_cents=30000)
    res = api.waive_overpayment(scenario["overpayment"]["id"], {}, ADJ)
    validate_error(res, "ERR_WAIVER_NOT_ALLOWED", expected_status=422)


# ── Corner: cross_cutting_complexity_layers / occ_recovery_stale_overpayment_version ──

def test_recovery_with_stale_overpayment_version_rejected(api):
    """PRD §2.6: "Recording a recovery against an overpayment requires the request
    to carry expected_overpayment_version, holding the client's last observed
    version of the target Overpayment. If that value does not equal the
    overpayment's current version ... the recovery is rejected with
    ERR_STALE_OVERPAYMENT_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_recovery_stale_overpayment_version
    """
    # Capture version at create (op_v0), apply one recovery (advances version),
    # then a second recovery still carrying op_v0 is stale -> 412.
    scenario = make_overpayment(cause="NONFRAUD", principal_cents=40000)
    op = scenario["overpayment"]
    stale_version = op["version"]
    apply_recovery(op["id"], 10000, stale_version, recovery_method="CASH")
    res = api.create_recovery(
        op["id"],
        {"recovery_method": "CASH", "amount_cents": 5000,
         "expected_overpayment_version": stale_version},
        BPO)
    validate_error(res, "ERR_STALE_OVERPAYMENT_VERSION", expected_status=412)
