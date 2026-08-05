"""Award selection, customer decision branch, and manager approval gates.

Queue A: the customer-decision branch, the state-beats-referential precedence
pair, the empty-shortlist boundary, and the supplier-active approval gate.
Queue B: award selection ranking, referential mismatch, approval-limit ceiling.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_agent_headers, ops_headers,
)
import test_helpers.fixtures as fx
import test_helpers.factories as fac


# ===========================================================================
# Difficulty: non_linear_state_machine / contract_branch_customer_reject
# ===========================================================================

def test_customer_reject_voids_quote_and_reverts_rfp(api):
    """PRD §3.3: "Rejecting advances it PENDING_CUSTOMER → REJECTED and unwinds
    the award: the winning quote reverts AWARDED → VOID and its RFP reverts
    AWARDED → BEST_AND_FINAL, making the solicitation re-openable for a fresh award."

    Design: Difficulty/non_linear_state_machine/contract_branch_customer_reject
    """
    ctx = fx.setup_contract_pending_customer(api)
    contract = get_success_data(api.customer_decision(
        ctx["contract"]["id"], {"decision": "REJECT"}, ctx["customer_headers"]))
    assert contract["status"] == "REJECTED"

    quote = get_success_data(api.get_quote(ctx["quote"]["id"], ctx["agent_headers"]))
    rfp = get_success_data(api.get_rfp(ctx["rfp"]["id"], ctx["agent_headers"]))
    assert quote["status"] == "VOID", f"winning quote should be VOID, got {quote['status']}"
    assert rfp["status"] == "BEST_AND_FINAL", f"rfp should revert, got {rfp['status']}"


def test_customer_accept_advances_to_pending_approval(api):
    """PRD §3.3: "Accepting advances the contract PENDING_CUSTOMER → PENDING_APPROVAL
    (the acting customer must own the contract's account, else ERR_FORBIDDEN)."

    Design: Difficulty/non_linear_state_machine/contract_branch_customer_reject
    """
    ctx = fx.setup_contract_pending_customer(api)
    contract = get_success_data(api.customer_decision(
        ctx["contract"]["id"], {"decision": "ACCEPT"}, ctx["customer_headers"]))
    assert contract["status"] == "PENDING_APPROVAL"


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / award_state_beats_referential_mismatch
# ===========================================================================

def _cancelled_rfp_with_second_account(api):
    ctx = fx.setup_open_rfp_with_shortlisted_quote(api)
    ctx["account2"] = fx.new_account(api, ctx["customer"]["id"], ctx["agent"]["id"])
    get_success_data(api.transition_rfp(ctx["rfp"]["id"], {"action": "CANCEL"}, ctx["agent_headers"]))
    return ctx


def test_award_on_cancelled_rfp_with_mismatch_reports_invalid_state(api):
    """PRD §2.6: "State. For a transition endpoint, the target resource must
    currently be in a state from which the requested transition is defined, else
    ERR_INVALID_STATE (HTTP 409)." precedes "Referential coherence ... else
    ERR_REFERENTIAL_MISMATCH (HTTP 409)." and the first failing check wins.

    Design: Difficulty/priority_pair_validation_conflict/award_state_beats_referential_mismatch
    """
    ctx = _cancelled_rfp_with_second_account(api)
    payload = fac.award_contract_payload(ctx["rfp"]["id"], ctx["account2"]["id"])
    resp = api.award_contract(payload, ctx["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_rfp(ctx["rfp"]["id"], ctx["agent_headers"]))
    assert after["status"] == "CANCELLED"


def test_award_on_cancelled_rfp_with_correct_account_still_invalid_state(api):
    """PRD §2.6: "State. For a transition endpoint, the target resource must
    currently be in a state from which the requested transition is defined, else
    ERR_INVALID_STATE (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/award_state_beats_referential_mismatch
    """
    ctx = _cancelled_rfp_with_second_account(api)
    payload = fac.award_contract_payload(ctx["rfp"]["id"], ctx["account"]["id"])  # matching account
    resp = api.award_contract(payload, ctx["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty: boundary_precision_check / award_rejects_empty_shortlisted_set
# ===========================================================================

def _rfp_open_with_submitted_only(api):
    ctx = fx.setup_verified_account(api)
    ctx["supplier"] = fx.new_supplier(api)
    ctx["supplier_headers"] = fx.make_supplier_headers(ctx["supplier"]["id"])
    rfp = get_success_data(api.create_rfp(
        fac.create_rfp_payload(ctx["account"]["id"], ctx["agent"]["id"]), ctx["agent_headers"]))
    get_success_data(api.transition_rfp(rfp["id"], {"action": "OPEN"}, ctx["agent_headers"]))
    v = fx.rfp_version(api, rfp["id"], ctx["agent_headers"])
    quote = get_success_data(api.create_quote(
        fac.create_quote_payload(rfp["id"], ctx["supplier"]["id"], v), ctx["supplier_headers"]))
    ctx["rfp"] = rfp
    ctx["quote"] = quote
    return ctx


def test_award_empty_shortlisted_set_rejected(api):
    """PRD §3.3: "The candidate set is every quote on that RFP currently in
    SHORTLISTED; if that set is empty the award fails with ERR_NO_ELIGIBLE_QUOTES."

    Design: Difficulty/boundary_precision_check/award_rejects_empty_shortlisted_set
    """
    ctx = _rfp_open_with_submitted_only(api)  # one SUBMITTED, zero SHORTLISTED
    resp = api.award_contract(
        fac.award_contract_payload(ctx["rfp"]["id"], ctx["account"]["id"]), ctx["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_QUOTES.value)
    quote = get_success_data(api.get_quote(ctx["quote"]["id"], ctx["agent_headers"]))
    assert quote["status"] == "SUBMITTED"


def test_award_with_one_shortlisted_quote_succeeds(api):
    """PRD §3.3: "The candidate set is every quote on that RFP currently in
    SHORTLISTED; if that set is empty the award fails with ERR_NO_ELIGIBLE_QUOTES."

    Design: Difficulty/boundary_precision_check/award_rejects_empty_shortlisted_set
    """
    ctx = _rfp_open_with_submitted_only(api)
    get_success_data(api.shortlist_quote(ctx["quote"]["id"], ctx["agent_headers"]))  # now non-empty
    contract = get_success_data(api.award_contract(
        fac.award_contract_payload(ctx["rfp"]["id"], ctx["account"]["id"]), ctx["agent_headers"]))
    assert contract["status"] == "PENDING_CUSTOMER"
    quote = get_success_data(api.get_quote(ctx["quote"]["id"], ctx["agent_headers"]))
    assert quote["status"] == "AWARDED"


# ===========================================================================
# Difficulty: cross_entity_state_dependency / contract_approve_requires_supplier_active
# ===========================================================================

def test_approve_rejected_when_supplier_suspended(api):
    """PRD §3.3: "The winning quote's supplier must currently be ACTIVE (else
    ERR_SUPPLIER_NOT_ACTIVE)".

    Design: Difficulty/cross_entity_state_dependency/contract_approve_requires_supplier_active
    """
    ctx = fx.setup_contract_pending_approval(api, with_manager=True)
    get_success_data(api.set_supplier_status(ctx["supplier"]["id"], {"status": "SUSPENDED"}, ops_headers()))

    resp = api.approve_contract(ctx["contract"]["id"], ctx["mgr1_headers"])
    validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_ACTIVE.value)
    after = get_success_data(api.get_contract(ctx["contract"]["id"], ctx["agent_headers"]))
    assert after["status"] == "PENDING_APPROVAL"


def test_approve_succeeds_when_supplier_active(api):
    """PRD §3.3: "A manager then approves an accepted contract, advancing it
    PENDING_APPROVAL → APPROVED, subject to three fiscal and dependency checks.
    The winning quote's supplier must currently be ACTIVE (else
    ERR_SUPPLIER_NOT_ACTIVE)".

    Design: Difficulty/cross_entity_state_dependency/contract_approve_requires_supplier_active
    """
    ctx = fx.setup_contract_pending_approval(api, with_manager=True)
    contract = get_success_data(api.approve_contract(ctx["contract"]["id"], ctx["mgr1_headers"]))
    assert contract["status"] == "APPROVED"


# ===========================================================================
# Corner: award selection, referential mismatch, approval-limit ceiling
# ===========================================================================

def test_award_selects_lowest_all_in_rate(api):
    """PRD §3.3: "Among candidates the server computes each quote's all-in rate as
    its rate_mills_per_kwh plus its broker_adder_mills, and picks the lowest
    all-in rate."

    Design: Corner/calculations/award_selects_lowest_all_in_rate
    """
    ctx = fx.setup_verified_account(api)
    hdr = ctx["agent_headers"]
    supA = fx.new_supplier(api, name="PowerCo")
    supB = fx.new_supplier(api, name="GridCo")
    rfp = get_success_data(api.create_rfp(fac.create_rfp_payload(ctx["account"]["id"], ctx["agent"]["id"]), hdr))
    get_success_data(api.transition_rfp(rfp["id"], {"action": "OPEN"}, hdr))

    v1 = fx.rfp_version(api, rfp["id"], hdr)
    qA = get_success_data(api.create_quote(
        fac.create_quote_payload(rfp["id"], supA["id"], v1, rate_mills_per_kwh=60, broker_adder_mills=5),
        fx.make_supplier_headers(supA["id"])))  # all-in 65
    v2 = fx.rfp_version(api, rfp["id"], hdr)
    qB = get_success_data(api.create_quote(
        fac.create_quote_payload(rfp["id"], supB["id"], v2, rate_mills_per_kwh=58, broker_adder_mills=4),
        fx.make_supplier_headers(supB["id"])))  # all-in 62 (lower)
    get_success_data(api.shortlist_quote(qA["id"], hdr))
    get_success_data(api.shortlist_quote(qB["id"], hdr))

    contract = get_success_data(api.award_contract(
        fac.award_contract_payload(rfp["id"], ctx["account"]["id"]), hdr))
    assert contract["quote_id"] == qB["id"]
    assert contract["rate_mills_per_kwh"] == 58
    assert contract["broker_adder_mills"] == 4
    winner = get_success_data(api.get_quote(qB["id"], hdr))
    assert winner["status"] == "AWARDED"


def test_award_account_mismatch_referential(api):
    """PRD §3.3: "The award also checks referential coherence: the selected
    quote's RFP must belong to the named account, else ERR_REFERENTIAL_MISMATCH."

    Design: Corner/validations/award_account_mismatch_referential
    """
    ctx = fx.setup_open_rfp_with_shortlisted_quote(api)  # rfp OPEN (state OK) on ctx.account
    account2 = fx.new_account(api, ctx["customer"]["id"], ctx["agent"]["id"])
    resp = api.award_contract(
        fac.award_contract_payload(ctx["rfp"]["id"], account2["id"]), ctx["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_REFERENTIAL_MISMATCH.value)
    after = get_success_data(api.get_rfp(ctx["rfp"]["id"], ctx["agent_headers"]))
    assert after["status"] == "OPEN"


def test_approve_over_manager_limit_rejected(api):
    """PRD §3.3: "the estimated gross commission the deal would generate ... must
    not exceed the acting manager's own approval_limit_cents (else
    ERR_APPROVAL_LIMIT_EXCEEDED)."

    Design: Corner/validations/approve_over_manager_limit_rejected
    """
    ctx = fx.setup_contract_pending_approval(api, with_manager=True, manager_limit=20000)
    # est 60000 * adder 5 / 10 = 30000 gross > 20000 limit
    resp = api.approve_contract(ctx["contract"]["id"], ctx["mgr1_headers"])
    validate_error(resp, ApiErrorId.ERR_APPROVAL_LIMIT_EXCEEDED.value)
    after = get_success_data(api.get_contract(ctx["contract"]["id"], ctx["agent_headers"]))
    assert after["status"] == "PENDING_APPROVAL"
