"""State-machine corner behaviors: precondition enforcement, invalid transitions,
idempotency, cross-entity cascades on decline, library-retire guards, and the
clock-driven expiry / auto-renew sweeps.

Tests here translate queue B (Corner) instances under sections `state_machines`
and `errors` (retire_contract_template_in_use).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    factories as F, fixtures as FX,
    ApiErrorId,
)

ADMIN = FX.ADMIN
LIBRARIAN = FX.LIBRARIAN
MGR = FX.MGR
SIGNER_INT = FX.SIGNER_INT
SIGNER_CP = FX.SIGNER_CP


@pytest.fixture
def api():
    return api_client


def test_submit_contract_without_version_returns_no_version(api):
    """PRD §3.2: "Submission requires that the contract already have a current
    version — if current_version_id is still null, the submit is refused with
    ERR_NO_VERSION".

    Design: Corner/state_machines/submit_contract_with_no_version_returns_no_version
    """
    org = FX.create_organization(api)
    clause = FX.create_clause(api, org["id"], clause_key="K")
    template = FX.create_contract_template(api, org["id"], [clause["id"]])
    contract = FX.create_contract(api, org["id"], template["id"])
    resp = api.submit_contract(contract["id"], F.submit_payload(contract["version"]), MGR)
    validate_error(resp, ApiErrorId.ERR_NO_VERSION.value, 409)


def test_terminate_draft_contract_returns_invalid_state(api):
    """PRD §2.5/§3.7: terminate is defined only on an ACTIVE contract ("A
    ContractManager may terminate an ACTIVE contract"); the general state guard is
    PRD §2.6-adjacent — a transition not defined from the current state.

    Design: Corner/state_machines/terminate_draft_contract_returns_invalid_state
    """
    setup = FX.setup_draft_contract_with_version(
        api, FX.simple_clauses_spec(), clause_defs=FX.simple_clause_defs()
    )
    contract = setup["contract_after"]
    resp = api.terminate_contract(contract["id"], F.occ_payload(contract["version"]), MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_sign_already_signed_request_returns_invalid_state(api):
    """PRD §3.5: "A Signer signs a request, which is permitted only while the parent
    contract is OUT_FOR_SIGNATURE (otherwise ERR_INVALID_STATE)".

    Design: Corner/state_machines/sign_already_signed_request_returns_invalid_state
    """
    setup = FX.setup_simple_active(api)
    sr0 = setup["signature_requests"][0]
    # The contract is now ACTIVE (both signed), so re-signing the first is invalid.
    resp = api.sign_signature_request(sr0["id"], SIGNER_INT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_decline_bounces_contract_to_redlining_and_voids_sibling(api):
    """PRD §3.5: "A decline moves that request from SENT to DECLINED and bubbles up
    to bounce the contract from OUT_FOR_SIGNATURE back into REDLINING; as a cascade,
    every sibling signature request still in SENT is moved to VOIDED."

    Design: Corner/state_machines/signature_decline_bounces_to_redlining_and_voids_siblings
    """
    setup = FX.setup_out_for_signature(
        api, FX.simple_clause_defs(), FX.simple_clauses_spec()
    )
    srs = setup["signature_requests"]
    sr0, sr1 = srs[0], srs[1]
    validate_success(api.decline_signature_request(sr0["id"], SIGNER_INT), 200)

    contract = FX.get_contract(api, setup["contract"]["id"])
    assert contract["status"] == "REDLINING", \
        f"contract must bounce to REDLINING on decline, got {contract['status']}"

    sibling = FX.get_success_data(api.list_signature_requests(setup["contract"]["id"], MGR))
    sib = next(s for s in sibling if s["id"] == sr1["id"])
    assert sib["status"] == "VOIDED", \
        f"sibling SENT request must be VOIDED, got {sib['status']}"


def test_retire_clause_in_use_returns_clause_in_use(api):
    """PRD §3.1: "Retiring a clause template... is permitted only when no contract in
    a working state — that is, no contract whose status is DRAFT, UNDER_REVIEW, or
    REDLINING — has a current version that still references the clause. Retiring a
    clause that is still in use that way is refused with ERR_CLAUSE_IN_USE."

    Design: Corner/state_machines/retire_clause_template_in_use_returns_clause_in_use
    """
    setup = FX.setup_draft_contract_with_version(
        api, FX.simple_clauses_spec(), clause_defs=FX.simple_clause_defs()
    )
    clause_id = setup["clauses"][0]["id"]
    resp = api.retire_clause_template(clause_id, LIBRARIAN)
    validate_error(resp, ApiErrorId.ERR_CLAUSE_IN_USE.value, 409)


def test_cancel_active_contract_returns_invalid_state(api):
    """PRD §3.2: "A contract may be cancelled by its ContractManager while it is
    DRAFT or REDLINING". Cancel from any other state is not a defined transition.

    Design: Corner/state_machines/cancel_active_contract_returns_invalid_state
    """
    setup = FX.setup_simple_active(api)
    contract = setup["contract_active"]
    resp = api.cancel_contract(contract["id"], F.occ_payload(contract["version"]), MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_expiry_sweep_lets_lapse_and_waives_obligations(api):
    """PRD §3.7: "the sweep expires it: the contract moves from ACTIVE to the
    terminal EXPIRED state, any renewal alert still SCHEDULED or DUE is moved to
    RESOLVED with resolution LET_LAPSE, every obligation still OPEN is moved to
    WAIVED because the contract is no longer active".

    Design: Corner/state_machines/expiry_lets_lapse_and_waives_obligations
    """
    setup = FX.setup_simple_active(api, auto_renew=False, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    obl = FX.get_success_data(api.create_obligation(
        contract_id, F.create_obligation_payload(contract_id, "2027-09-01T00:00:00Z"), MGR
    ))

    FX.set_clock(api, "2027-06-02T00:00:00Z")  # past expiry 2027-06-01

    contract = FX.get_contract(api, contract_id)
    assert contract["status"] == "EXPIRED", f"expected EXPIRED, got {contract['status']}"

    obls = FX.get_success_data(api.list_obligations(contract_id, MGR))
    assert obls[0]["status"] == "WAIVED", f"OPEN obligation must be WAIVED, got {obls[0]['status']}"

    alerts = FX.get_success_data(api.list_renewal_alerts(contract_id, MGR))
    assert alerts[0]["resolution"] == "LET_LAPSE", \
        f"alert resolution must be LET_LAPSE, got {alerts[0]['resolution']}"


def test_auto_renew_sweep_self_loops_active(api):
    """PRD §3.7: "When the clock advances on an ACTIVE contract whose auto_renew is
    true and which has a DUE renewal alert, the contract renews via its self-loop,
    staying ACTIVE with an extended term." And: "A renewal increments
    renewal_cycle_index by one... recomputes expiry_date as that new effective date
    plus term_months calendar months".

    Design: Corner/state_machines/auto_renew_sweep_self_loops_active
    """
    setup = FX.setup_simple_active(api, auto_renew=True, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]

    FX.set_clock(api, "2027-06-01T00:00:00Z")  # at expiry; alert is due (trigger 2027-05-02)

    contract = FX.get_contract(api, contract_id)
    assert contract["status"] == "ACTIVE", f"auto-renew must keep ACTIVE, got {contract['status']}"
    assert contract["renewal_cycle_index"] == 1, \
        f"renewal_cycle_index must be 1 after one auto-renew, got {contract['renewal_cycle_index']}"
    assert contract["expiry_date"] == "2028-06-01T00:00:00.000Z", \
        f"expiry must roll to 2028-06-01, got {contract['expiry_date']}"


def test_retire_contract_template_in_use_returns_template_in_use(api):
    """PRD §3.1: "Retiring a contract template moves it to RETIRED and increments its
    version, and is allowed only when no contract whose status is DRAFT,
    UNDER_REVIEW, or REDLINING references it; otherwise the request is refused with
    ERR_TEMPLATE_IN_USE."

    Design: Corner/errors/retire_contract_template_in_use_returns_template_in_use
    """
    org = FX.create_organization(api)
    clause = FX.create_clause(api, org["id"], clause_key="K")
    template = FX.create_contract_template(api, org["id"], [clause["id"]])
    FX.create_contract(api, org["id"], template["id"])  # DRAFT contract references it
    resp = api.retire_contract_template(template["id"], LIBRARIAN)
    validate_error(resp, ApiErrorId.ERR_TEMPLATE_IN_USE.value, 409)
