"""Activation gate: dual-basis credential readiness, packet-state dependency, contract gate."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_credential_item_payload,
)
from test_helpers.fixtures import (
    provision, get_assignment_data, get_packet_data, submit_packet, review_packet,
)

RECRUITER = TEST_USERS["recruiter_headers"]
CS1 = TEST_USERS["credentialing_specialist_headers"]


# --- Difficulty: packet readiness diverges between start-date and full-term basis ---
def test_packet_clears_under_start_date_basis(api):
    """PRD §3.4: "The count of satisfied required types out of five, multiplied by 100
    and divided by 5 and rounded half up, is the readiness score. Under the start-date
    basis, the basis date is the assignment's start_date: this yields
    readiness_score_start_basis and, as five minus the satisfied count,
    blocking_item_count_start_basis."
    PRD §3.4: "the start-date basis gates packet clearance"

    Design: Difficulty/dual_variant_calc/packet_readiness_start_date_basis_vs_full_term_basis_diverges
    """
    ctx = provision(api, add_items=True, verify_items=True,
                    item_expiries={"BLS_CERT": "2026-07-15"},
                    packet_stage="cleared", contract_stage="executed")
    pkt = get_packet_data(api, ctx.pkt_id)
    assert pkt["readiness_score_start_basis"] == 100 and pkt["blocking_item_count_start_basis"] == 0
    assert pkt["status"] == "CLEARED"


def test_activation_rejected_under_full_term_basis(api):
    """PRD §3.4: "Under the full-term basis, the basis date is the assignment's end_date:
    this yields readiness_score_full_term_basis and blocking_item_count_full_term_basis.
    Because a document may be valid on the start date but expire before the end date, the
    full-term basis can score strictly lower than the start-date basis on the identical
    packet — ... the stricter full-term basis gates activation."
    PRD §3.5: "Activation further requires that the credential packet's status is CLEARED
    and its blocking_item_count_full_term_basis is 0 under the stricter full-term basis,
    else ERR_PACKET_NOT_CLEARED"

    Design: Difficulty/dual_variant_calc/packet_readiness_start_date_basis_vs_full_term_basis_diverges
    """
    ctx = provision(api, add_items=True, verify_items=True,
                    item_expiries={"BLS_CERT": "2026-07-15"},
                    packet_stage="cleared", contract_stage="executed")
    pkt = get_packet_data(api, ctx.pkt_id)
    assert pkt["readiness_score_full_term_basis"] == 80 and pkt["blocking_item_count_full_term_basis"] == 1
    validate_error(api.activate_assignment(ctx.asg_id, RECRUITER), ApiErrorId.ERR_PACKET_NOT_CLEARED.value)
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["staffing_status"] == "PENDING_START" and asg["compliance_status"] == "CLEARED"


# --- Difficulty: activation gated by the SEPARATE credential-packet row's state ---
def test_activation_rejected_while_packet_under_review(api):
    """PRD §3.5: "Activation further requires that the credential packet's status is
    CLEARED and its blocking_item_count_full_term_basis is 0 under the stricter full-term
    basis, else ERR_PACKET_NOT_CLEARED"

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_gated_by_credential_packet_state
    """
    ctx = provision(api, clock="2026-06-14", contract_stage="executed")  # PENDING_START, packet DRAFT
    bls = validate_success(api.create_credential_item(
        ctx.pkt_id, create_credential_item_payload("BLS_CERT"), CS1), 201)
    validate_success(api.transition_credential_item(bls["id"], "VERIFIED", CS1), 200)
    submit_packet(api, ctx.pkt_id, CS1)
    review_packet(api, ctx.pkt_id)
    validate_error(api.activate_assignment(ctx.asg_id, RECRUITER), ApiErrorId.ERR_PACKET_NOT_CLEARED.value)


def test_activation_rejection_under_review_leaves_states_untouched(api):
    """PRD §3.5: "On success the assignment's staffing_status becomes ACTIVE ...; the
    compliance_status dimension is untouched." — a rejected activation performs none of
    these side effects.
    PRD §3.4: "A required type is satisfied on a given basis date when at least one item
    of that type on the packet is VERIFIED ..." (only one of five required types present
    -> blocking_item_count_start_basis is 4).

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_gated_by_credential_packet_state
    """
    ctx = provision(api, clock="2026-06-14", contract_stage="executed")
    bls = validate_success(api.create_credential_item(
        ctx.pkt_id, create_credential_item_payload("BLS_CERT"), CS1), 201)
    validate_success(api.transition_credential_item(bls["id"], "VERIFIED", CS1), 200)
    submit_packet(api, ctx.pkt_id, CS1)
    review_packet(api, ctx.pkt_id)
    validate_error(api.activate_assignment(ctx.asg_id, RECRUITER), ApiErrorId.ERR_PACKET_NOT_CLEARED.value)
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["staffing_status"] == "PENDING_START" and asg["compliance_status"] == "PENDING_CREDENTIALS"
    pkt = get_packet_data(api, ctx.pkt_id)
    assert pkt["status"] == "UNDER_REVIEW" and pkt["blocking_item_count_start_basis"] == 4


def test_activate_rejected_when_contract_not_executed(api):
    """PRD §3.5: "A DRAFT assignment survives that state gate but is then stopped by the
    contract gate: activation requires the linked contract's status to be FULLY_EXECUTED,
    and a DRAFT assignment (whose contract is not executed) is rejected with
    ERR_CONTRACT_NOT_EXECUTED — this is exactly how that error becomes reachable."

    Design: Corner/errors/corner_activate_rejected_when_contract_not_executed
    """
    ctx = provision(api, add_items=True, verify_items=True,
                    packet_stage="cleared", contract_stage="sent")  # DRAFT staffing, packet CLEARED
    before = get_assignment_data(api, ctx.asg_id)
    assert before["compliance_status"] == "CLEARED" and before["staffing_status"] == "DRAFT"
    validate_error(api.activate_assignment(ctx.asg_id, RECRUITER), ApiErrorId.ERR_CONTRACT_NOT_EXECUTED.value)
    after = get_assignment_data(api, ctx.asg_id)
    assert after["staffing_status"] == "DRAFT"
    data, _ = validate_paginated_contract(api, ctx.asg_id)
    assert data["status"] == "SENT_FOR_SIGNATURE"


def validate_paginated_contract(api, asg_id):
    from test_helpers import validate_paginated
    data, meta = validate_paginated(api.list_assignment_contracts(asg_id, RECRUITER))
    return data[0], meta
