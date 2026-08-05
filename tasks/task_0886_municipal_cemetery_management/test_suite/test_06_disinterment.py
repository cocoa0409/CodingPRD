"""Disinterment: settlement variants, precedence, consent gates, segregation."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_registrar_headers,
    setup_disinterment_requested, setup_disinterment_approved,
)

REG = TEST_USERS["registrar_headers"]
HEALTH = TEST_USERS["health_officer_headers"]


# ── Difficulty: dual_variant_calc / disinterment_relocation_vs_removal_settlement ──

def test_relocation_settlement_is_fifty_percent(api):
    """PRD §3.6: "For a RELOCATION, settlement_cents is that contribution multiplied
    by 50% (0.50) and rounded half-up — the care funds follow the remains to the new
    resting place."

    Design: Difficulty/dual_variant_calc/disinterment_relocation_vs_removal_settlement
    """
    r = setup_disinterment_approved(disinterment_type="RELOCATION", approver_id="dir-a")
    executed = validate_success(
        api.execute_disinterment(r["auth"]["id"], make_registrar_headers("reg-exec")), 200)
    assert executed["settlement_cents"] == 75000
    interment = validate_success(api.get_interment(r["interment"]["id"], REG), 200)
    assert interment["operational_status"] == "DISINTERRED"


def test_removal_settlement_is_twenty_five_percent(api):
    """PRD §3.6: "For a REMOVAL, it is that contribution multiplied by 25% (0.25) and
    rounded half-up — a partial refund, with the remainder retained by the fund."

    Design: Difficulty/dual_variant_calc/disinterment_relocation_vs_removal_settlement
    """
    r = setup_disinterment_approved(disinterment_type="REMOVAL", approver_id="dir-b")
    executed = validate_success(
        api.execute_disinterment(r["auth"]["id"], make_registrar_headers("reg-exec")), 200)
    assert executed["settlement_cents"] == 37500


# ── Difficulty: priority_pair_validation_conflict / disinterment_state_beats_fiscal ──

def test_execute_before_approval_reports_state_error(api):
    """PRD §2.5: "the first failing rung determines the error returned"; the ladder
    ranks "State" (rung 6) above "Fiscal gates" (rung 11). PRD §3.6: "A Registrar
    executes an APPROVED authorization, moving it to the terminal EXECUTED."

    Design: Difficulty/priority_pair_validation_conflict/disinterment_state_beats_fiscal
    """
    r = setup_disinterment_requested(disinterment_type="REMOVAL")
    res = api.execute_disinterment(r["auth"]["id"], make_registrar_headers("reg-1"))
    validate_error(res, "ERR_INVALID_STATE")


def test_execute_before_approval_not_masked_by_unpaid_invoice(api):
    """PRD §2.5: "the first failing rung determines the error returned"; with "State"
    (rung 6) ranked above "Fiscal gates" (rung 11), executing a still-REQUESTED
    authorization whose invoice is unpaid reports the state error, not
    ERR_INVOICE_UNPAID.

    Design: Difficulty/priority_pair_validation_conflict/disinterment_state_beats_fiscal
    """
    r = setup_disinterment_requested(disinterment_type="REMOVAL")
    res = api.execute_disinterment(r["auth"]["id"], make_registrar_headers("reg-1"))
    body = res.json()["data"]
    assert body["error_id"] == "ERR_INVALID_STATE"
    assert body["error_id"] != "ERR_INVOICE_UNPAID"


# ── Corner: state_machines / record_clearance_twice_already_recorded ──

def test_record_clearance_twice_already_recorded(api):
    """PRD §3.6: "a HealthOfficer records public-health clearance, setting
    health_cleared to true; this is permitted only while health_cleared is still
    false, otherwise ERR_ALREADY_RECORDED."

    Design: Corner/state_machines/record_clearance_twice_already_recorded
    """
    r = setup_disinterment_requested(disinterment_type="REMOVAL")
    validate_success(api.record_clearance(r["auth"]["id"], HEALTH), 200)
    res = api.record_clearance(r["auth"]["id"], HEALTH)
    validate_error(res, "ERR_ALREADY_RECORDED")


# ── Corner: state_machines / approve_without_consent_incomplete ──

def test_approve_without_consent_incomplete(api):
    """PRD §3.6: "Approval is the join gate: it is permitted only when both
    health_cleared and nok_consented are true, otherwise ERR_CONSENT_INCOMPLETE."

    Design: Corner/state_machines/approve_without_consent_incomplete
    """
    r = setup_disinterment_requested(disinterment_type="REMOVAL")
    validate_success(api.record_clearance(r["auth"]["id"], HEALTH), 200)
    # nok_consented is still false — join gate must reject.
    res = api.approve_disinterment(r["auth"]["id"], TEST_USERS["cemetery_director_headers"])
    validate_error(res, "ERR_CONSENT_INCOMPLETE")


# ── Corner: rbac / health_officer_cannot_approve_disinterment ──

def test_health_officer_cannot_approve_disinterment(api):
    """PRD §2.1: "When the role is recognized but is not permitted to perform the
    requested operation — or, for an entity-backed role, does not own the target
    resource — the request is rejected with ERR_FORBIDDEN." Approval is a
    CemeteryDirector operation (PRD §3.6 / §4).

    Design: Corner/rbac/health_officer_cannot_approve_disinterment
    """
    r = setup_disinterment_requested(disinterment_type="REMOVAL")
    res = api.approve_disinterment(r["auth"]["id"], HEALTH)
    validate_error(res, "ERR_FORBIDDEN")


# ── Corner: rbac / disinterment_approve_execute_same_user_segregation ──

def test_same_user_cannot_approve_and_execute(api):
    """PRD §2.8: "the later execution of that disinterment is rejected with
    ERR_SEGREGATION_OF_DUTIES if the executing Registrar's X-User-ID equals the
    recorded approved_by_user_id."

    Design: Corner/rbac/disinterment_approve_execute_same_user_segregation
    """
    r = setup_disinterment_approved(disinterment_type="REMOVAL", approver_id="user-x")
    res = api.execute_disinterment(r["auth"]["id"], make_registrar_headers("user-x"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
