"""Validation precedence and cross-entity state gates on e-file, IN_PREP, and
refund-transfer disbursement.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_return_in_prep, setup_return_prepared, setup_accepted_return_with_pending_transfer,
    setup_return_in_docs_pending, api_client, TEST_USERS,
)

OM = TEST_USERS["office_manager_headers"]
BO = TEST_USERS["bank_officer_headers"]


# ─── Queue A: priority_pair_validation_conflict / state_vs_efin_suspended ──

def test_state_check_outranks_efin_suspended_on_efile(api):
    """PRD §2.5: "then, on transition, e-file, e-file-ack, underwrite, disburse,
    and cancel endpoints, that the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE, 409) ... Business rules
    specific to each workflow are evaluated only after this common precedence
    has passed."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_efin_suspended_on_efile
    """
    # Return left in IN_PREP (not PREPARED) at a SUSPENDED-EFIN office.
    ctx = setup_return_in_prep(return_overrides={"complexity_band": "SIMPLE"})
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]
    validate_success(api.set_efin_status(ctx["office"]["id"], {"efin_status": "SUSPENDED"}, OM), 200)

    res = api.efile_return(rid, ph)
    # /efile is undefined from IN_PREP; the state check (in the common precedence)
    # fires before the EFIN business-safety rule.
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_return(rid, ph), 200)
    assert after["status"] == "IN_PREP", "return must remain IN_PREP after the rejected e-file"


# Queue A instance priority_pair_validation_conflict /
# credential_safety_vs_amend_referential_on_efile is SKIPPED: the PRD does not
# commit to a definite ordering between the credential (priority 8) and
# amend-target (priority 9) business preconditions — §2.5's tiebreak references
# only its enumerated common-precedence list, not the relative order of these
# two same-category business rules. A faithful PRD-only reader could surface
# either error, so the asserted ERR_CREDENTIAL_INVALID is not uniquely derivable
# (Silence pattern: error-precedence between same-tier business rules).


# ─── Queue A: cross_entity_state_dependency / refund_transfer_disburse_requires_return_accepted

def test_disburse_requires_return_accepted(api):
    """PRD §3.7: "The linked return must be in EFILED_ACCEPTED, else
    ERR_RETURN_NOT_ACCEPTED"

    Design: Difficulty/cross_entity_state_dependency/refund_transfer_disburse_requires_return_accepted
    """
    # Build a PREPARED (not accepted) return at a bank office, with a pending RT.
    ctx = setup_return_prepared(
        bank_product_enabled=True,
        client_overrides={"risk_band": "LOW"},
        return_overrides={"complexity_band": "SIMPLE", "expected_refund_cents": 500000})
    rid = ctx["return"]["id"]
    rt = validate_success(api.create_refund_transfer({"tax_return_id": rid}, BO), 201)
    rt_v = rt["version"]

    res = api.disburse_refund_transfer(
        rt["id"], {"disbursed_refund_cents": 500000, "expected_refundtransfer_version": rt_v}, BO)
    validate_error(res, "ERR_RETURN_NOT_ACCEPTED", expected_status=409)
    rt_after = validate_success(api.get_refund_transfer(rt["id"], BO), 200)
    assert rt_after["status"] == "PENDING_FUNDING", "transfer must remain PENDING_FUNDING"
    ret_after = validate_success(api.get_return(rid, ctx["prep_headers"]), 200)
    assert ret_after["status"] == "PREPARED"


# ─── Queue A: cross_entity_state_dependency / in_prep_requires_active_credential

def test_in_prep_requires_active_credential(api):
    """PRD §3.4: "the assigned preparer's credential must be in ACTIVE status,
    else ERR_CREDENTIAL_INVALID."

    Design: Difficulty/cross_entity_state_dependency/in_prep_requires_active_credential
    """
    # Return in DOCS_PENDING with assigned preparer and received doc; revoke the
    # preparer's credential before attempting IN_PREP.
    ctx = setup_return_in_docs_pending(return_overrides={"complexity_band": "SIMPLE"})
    rid = ctx["return"]["id"]
    cred_id = ctx["credential"]["id"]
    validate_success(api.revoke_credential(cred_id, OM), 200)

    res = api.transition_return(rid, {"to": "IN_PREP"}, ctx["prep_headers"])
    validate_error(res, "ERR_CREDENTIAL_INVALID", expected_status=409)
    after = validate_success(api.get_return(rid, ctx["prep_headers"]), 200)
    assert after["status"] == "DOCS_PENDING", "return must remain DOCS_PENDING"
    cred_after = validate_success(api.get_credential(cred_id, OM), 200)
    assert cred_after["status"] == "REVOKED"
