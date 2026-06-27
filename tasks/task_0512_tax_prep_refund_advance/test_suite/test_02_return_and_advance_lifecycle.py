"""Non-linear lifecycles: the e-file reject/correction cycle on TaxReturn and the
approve/deny fork on RefundAdvance.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_return_prepared, create_client, create_return, create_refund_advance,
    api_client, TEST_USERS,
)

BO = TEST_USERS["bank_officer_headers"]


# ─── Queue A: non_linear_state_machine / tax_return_reject_correction_cycle ─

def test_reject_then_correct_then_accept_cycle(api):
    """PRD §3.5: "When ack_status is REJECTED, a reject_code must be supplied,
    else ERR_REJECT_CODE_REQUIRED; the return moves to EFILED_REJECTED, the
    latest TRANSMITTED submission's ack_status becomes REJECTED with the supplied
    reject_code stored on it, and the return's reject_count is incremented by
    one."
    PRD §3.5: "A TaxPreparer moves it from EFILED_REJECTED back to PREPARED,
    provided the return's reject_count is at most 3"

    Design: Difficulty/non_linear_state_machine/tax_return_reject_correction_cycle
    """
    ctx = setup_return_prepared(return_overrides={"complexity_band": "SIMPLE"})
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]

    validate_success(api.efile_return(rid, ph), 200)
    rejected = validate_success(api.efile_ack_return(
        rid, {"ack_status": "REJECTED", "reject_code": "R0000-901"}, ph), 200)
    assert rejected["status"] == "EFILED_REJECTED"
    assert rejected["reject_count"] == 1, f"reject_count should be 1, got {rejected['reject_count']}"

    looped = validate_success(api.transition_return(rid, {"to": "PREPARED"}, ph), 200)
    assert looped["status"] == "PREPARED", "loop-back to PREPARED should succeed"

    validate_success(api.efile_return(rid, ph), 200)
    accepted = validate_success(api.efile_ack_return(rid, {"ack_status": "ACCEPTED"}, ph), 200)
    assert accepted["status"] == "EFILED_ACCEPTED"
    assert accepted["reject_count"] == 1, "reject_count is unchanged by an ACCEPTED ack"


def test_reject_count_increments_each_rejection(api):
    """PRD §3.5: "the return moves to EFILED_REJECTED, the latest TRANSMITTED
    submission's ack_status becomes REJECTED with the supplied reject_code stored
    on it, and the return's reject_count is incremented by one."

    Design: Difficulty/non_linear_state_machine/tax_return_reject_correction_cycle
    """
    ctx = setup_return_prepared(return_overrides={"complexity_band": "SIMPLE"})
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]

    validate_success(api.efile_return(rid, ph), 200)
    r1 = validate_success(api.efile_ack_return(
        rid, {"ack_status": "REJECTED", "reject_code": "R1"}, ph), 200)
    assert r1["reject_count"] == 1
    validate_success(api.transition_return(rid, {"to": "PREPARED"}, ph), 200)
    validate_success(api.efile_return(rid, ph), 200)
    r2 = validate_success(api.efile_ack_return(
        rid, {"ack_status": "REJECTED", "reject_code": "R2"}, ph), 200)
    assert r2["reject_count"] == 2, f"reject_count should be 2 after second rejection, got {r2['reject_count']}"
    assert r2["status"] == "EFILED_REJECTED"


# ─── Queue A: non_linear_state_machine / refund_advance_approve_or_deny_branch

def _bank_office_with_two_returns():
    office = validate_success(api_client.create_office(
        {"name": "Branch Office", "efin": "555666", "state_code": "WA",
         "bank_product_enabled": True}, TEST_USERS["office_manager_headers"]), 201)
    client = create_client(office["id"], full_name="Br Bea", ssn_last4="9999", risk_band="LOW")
    ret_a = create_return(office["id"], client["id"], tax_year=2025, expected_refund_cents=500000)
    ret_b = create_return(office["id"], client["id"], tax_year=2024,
                          expected_refund_cents=500000, return_kind="PRIOR_YEAR")
    return ret_a, ret_b


def test_advance_underwrite_approve_branch(api):
    """PRD §3.8: "An approval moves it from REQUESTED to APPROVED, but only when
    the linked return's office has bank_product_enabled true ... and the maximum
    eligible advance for the linked return and client is greater than zero"
    PRD §3.8: "On an approval, approved_cents is set to the smaller of
    requested_cents and that maximum eligible."

    Design: Difficulty/non_linear_state_machine/refund_advance_approve_or_deny_branch
    """
    ret_a, _ = _bank_office_with_two_returns()
    adv = create_refund_advance(ret_a["id"], 100000)
    approved = validate_success(api.underwrite_refund_advance(
        adv["id"], {"decision": "APPROVE"}, BO), 200)
    # tier(500000)=150000; round(500000*0.75)=375000; min=150000; min(100000,150000)=100000.
    assert approved["status"] == "APPROVED"
    assert approved["approved_cents"] == 100000, f"expected 100000, got {approved['approved_cents']}"


def test_advance_underwrite_deny_branch(api):
    """PRD §3.8: "A denial moves the advance from REQUESTED to DENIED and sets
    approved_cents to zero."

    Design: Difficulty/non_linear_state_machine/refund_advance_approve_or_deny_branch
    """
    _, ret_b = _bank_office_with_two_returns()
    adv = create_refund_advance(ret_b["id"], 100000)
    denied = validate_success(api.underwrite_refund_advance(
        adv["id"], {"decision": "DENY"}, BO), 200)
    assert denied["status"] == "DENIED"
    assert denied["approved_cents"] == 0, f"DENY sets approved_cents to 0, got {denied['approved_cents']}"
