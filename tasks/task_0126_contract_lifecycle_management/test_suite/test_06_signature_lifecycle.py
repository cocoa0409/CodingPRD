"""The signature fork/join: two parallel signature requests, the contract going live
only when BOTH reach SIGNED.

Tests here translate queue A (Difficulty) rule non_linear_state_machine, instance
signature_request_branching_fork_join.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    fixtures as FX,
)

MGR = FX.MGR
SIGNER_INT = FX.SIGNER_INT
SIGNER_CP = FX.SIGNER_CP


@pytest.fixture
def api():
    return api_client


def test_first_signature_does_not_activate_contract(api):
    """PRD §3.5: "Signature is a fork-join: the contract goes live only when every
    one of its signature requests has reached SIGNED."

    Design: Difficulty/non_linear_state_machine/signature_request_branching_fork_join
    """
    setup = FX.setup_out_for_signature(api, FX.simple_clause_defs(), FX.simple_clauses_spec())
    srs = setup["signature_requests"]
    validate_success(api.sign_signature_request(srs[0]["id"], SIGNER_INT), 200)
    contract = FX.get_contract(api, setup["contract"]["id"])
    assert contract["status"] == "OUT_FOR_SIGNATURE", \
        f"with one of two signatures the join must NOT fire, got {contract['status']}"


def test_final_signature_joins_to_active(api):
    """PRD §3.5: "On that final signature, the join fires and the contract moves from
    OUT_FOR_SIGNATURE to ACTIVE: its effective_date is set to the current clock time,
    its expiry_date is projected from that date, a renewal alert is scheduled".

    Design: Difficulty/non_linear_state_machine/signature_request_branching_fork_join
    """
    setup = FX.setup_out_for_signature(api, FX.simple_clause_defs(), FX.simple_clauses_spec())
    srs = setup["signature_requests"]
    validate_success(api.sign_signature_request(srs[0]["id"], SIGNER_INT), 200)
    validate_success(api.sign_signature_request(srs[1]["id"], SIGNER_CP), 200)
    contract = FX.get_contract(api, setup["contract"]["id"])
    assert contract["status"] == "ACTIVE", \
        f"both signatures must join the contract to ACTIVE, got {contract['status']}"


def test_both_signature_requests_reach_signed(api):
    """PRD §3.5: "signing sets signed_at to the current clock time, moves the request
    from SENT to SIGNED, and increments its version."

    Design: Difficulty/non_linear_state_machine/signature_request_branching_fork_join
    """
    setup = FX.setup_out_for_signature(api, FX.simple_clause_defs(), FX.simple_clauses_spec())
    srs = setup["signature_requests"]
    validate_success(api.sign_signature_request(srs[0]["id"], SIGNER_INT), 200)
    validate_success(api.sign_signature_request(srs[1]["id"], SIGNER_CP), 200)
    final = FX.get_success_data(api.list_signature_requests(setup["contract"]["id"], MGR))
    statuses = {s["status"] for s in final}
    assert statuses == {"SIGNED"}, \
        f"all signature requests must be SIGNED after the join, got statuses {statuses}"
