"""Case registration: conflict-of-interest, claim-amount sanity, case-number
assignment, and INTAKE → ACTIVE activation preconditions.

PRD §3.1.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    activate_case,
    add_verified_party,
    api_client,
    assert_case,
    create_case_payload,
    create_party_payload,
    make_intake_clerk_headers,
    make_junior_lawyer,
    make_partner_lawyer,
    make_partner_headers,
    register_case,
    register_lawyer,
    setup_partner_and_active_case,
    unique_hash,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Successful registration + case-number format
# ---------------------------------------------------------------------------
def test_register_case_assigns_case_number(api):
    """PRD §3.1: 'YEAR is the current UTC year, TYPE_CODE is CIV for
    CIVIL, CRM for CRIMINAL, ADM for ADMINISTRATIVE, and ARB for
    ARBITRATION, and SEQ6 is a zero-padded six-digit sequence number
    that starts at 000001 for each (YEAR, TYPE_CODE) pair and increases
    by exactly one for each subsequent registration in that pair.'
    """
    partner, partner_headers = make_partner_lawyer()
    case = register_case(
        lead_lawyer_id=partner["id"],
        actor_headers=partner_headers,
        case_type="CIVIL",
        claim_amount_cents=1_000_000,
    )
    assert_case(case)
    parts = case["case_number"].split("-")
    assert len(parts) == 3
    year, type_code, seq = parts
    assert len(year) == 4 and year.isdigit()
    assert type_code == "CIV"
    assert len(seq) == 6 and seq.isdigit()
    assert case["status"] == "INTAKE"
    assert case["posture"] == "OPEN"


@pytest.mark.parametrize("case_type,expected_code", [
    ("CIVIL", "CIV"),
    ("CRIMINAL", "CRM"),
    ("ADMINISTRATIVE", "ADM"),
    ("ARBITRATION", "ARB"),
])
def test_case_number_type_code_per_case_type(api, case_type, expected_code):
    """PRD §3.1: 'TYPE_CODE is CIV for CIVIL, CRM for CRIMINAL, ADM for
    ADMINISTRATIVE, and ARB for ARBITRATION.'
    """
    partner, partner_headers = make_partner_lawyer()
    claim = 0 if case_type in ("CRIMINAL", "ADMINISTRATIVE") else 1_000_000
    case = register_case(
        lead_lawyer_id=partner["id"],
        actor_headers=partner_headers,
        case_type=case_type,
        claim_amount_cents=claim,
    )
    assert case["case_number"].split("-")[1] == expected_code


def test_case_sequence_increments_within_same_year_type(api):
    """PRD §3.1: 'SEQ6 is a zero-padded six-digit sequence number that
    starts at 000001 for each (YEAR, TYPE_CODE) pair and increases by
    exactly one for each subsequent registration in that pair.'
    """
    partner, partner_headers = make_partner_lawyer()
    cases = [
        register_case(
            lead_lawyer_id=partner["id"],
            actor_headers=partner_headers,
            case_type="CIVIL",
            claim_amount_cents=1_000_000,
        )
        for _ in range(2)
    ]
    seq_a = int(cases[0]["case_number"].split("-")[2])
    seq_b = int(cases[1]["case_number"].split("-")[2])
    assert seq_b == seq_a + 1


# ---------------------------------------------------------------------------
# Conflict-of-interest checks (priority 5 + 6)
# ---------------------------------------------------------------------------
def test_lead_lawyer_history_against_opposing_rejected(api):
    """PRD §3.1: 'every entry there is a hash of a client the lawyer has
    previously represented — and rejects the request with
    ERR_CONFLICT_OF_INTEREST if the case'
    """
    opposing = unique_hash("opp")
    # Register a partner whose history contains exactly the opposing hash.
    bootstrap = make_partner_lawyer()[1]
    partner = register_lawyer(
        role="PARTNER",
        client_history=[opposing],
        bootstrap_partner_headers=bootstrap,
    )
    headers = make_partner_headers(partner["id"])
    payload = create_case_payload(
        lead_lawyer_id=partner["id"],
        opposing_identity_hash=opposing,
    )
    res = api.create_case(payload, headers)
    validate_error(res, "ERR_CONFLICT_OF_INTEREST", expected_status=409)


def test_client_equals_opposing_rejected(api):
    """PRD §3.1: 'Only when that check passes does the system run the
    secondary check, rejecting with the same ERR_CONFLICT_OF_INTEREST if
    client_identity_hash and opposing_identity_hash are equal.'
    """
    partner, partner_headers = make_partner_lawyer()
    same = unique_hash("identity")
    payload = create_case_payload(
        lead_lawyer_id=partner["id"],
        client_identity_hash=same,
        opposing_identity_hash=same,
    )
    res = api.create_case(payload, partner_headers)
    validate_error(res, "ERR_CONFLICT_OF_INTEREST", expected_status=409)


# ---------------------------------------------------------------------------
# Claim-amount validation (priority 21)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case_type", ["CRIMINAL", "ADMINISTRATIVE"])
def test_criminal_admin_must_have_zero_claim(api, case_type):
    """PRD §3.1: 'The claim_amount_cents must be 0 for CRIMINAL and
    ADMINISTRATIVE matters (where there is no monetary dispute) and must
    be strictly greater than 0 for CIVIL and ARBITRATION matters; a
    violation is rejected with ERR_CLAIM_AMOUNT_INVALID.'
    """
    partner, partner_headers = make_partner_lawyer()
    payload = create_case_payload(
        lead_lawyer_id=partner["id"], case_type=case_type,
        claim_amount_cents=10_000,
    )
    res = api.create_case(payload, partner_headers)
    validate_error(res, "ERR_CLAIM_AMOUNT_INVALID", expected_status=422)


@pytest.mark.parametrize("case_type", ["CIVIL", "ARBITRATION"])
def test_civil_arbitration_must_have_positive_claim(api, case_type):
    """PRD §3.1: 'must be strictly greater than 0 for CIVIL and
    ARBITRATION matters; a violation is rejected with
    ERR_CLAIM_AMOUNT_INVALID.'
    """
    partner, partner_headers = make_partner_lawyer()
    payload = create_case_payload(
        lead_lawyer_id=partner["id"], case_type=case_type,
        claim_amount_cents=0,
    )
    res = api.create_case(payload, partner_headers)
    validate_error(res, "ERR_CLAIM_AMOUNT_INVALID", expected_status=422)


# ---------------------------------------------------------------------------
# Activation preconditions (priority 7)
# ---------------------------------------------------------------------------
def test_activate_without_plaintiff_rejected(api):
    """PRD §3.1: 'Activation requires that the case has at least one
    Party whose party_role is PLAINTIFF, at least one Party whose
    party_role is DEFENDANT, ... failure to meet any precondition
    surfaces ERR_INVALID_STATE.'
    """
    partner, partner_headers = make_partner_lawyer()
    case = register_case(
        lead_lawyer_id=partner["id"], actor_headers=partner_headers,
    )
    add_verified_party(
        case_id=case["id"], party_role="DEFENDANT",
        actor_headers=partner_headers,
    )
    res = api.activate_case(case["id"], partner_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_activate_without_defendant_rejected(api):
    """PRD §3.1: 'Activation requires that the case has at least one
    Party whose party_role is PLAINTIFF, at least one Party whose
    party_role is DEFENDANT, that lead_lawyer_id still references an
    ACTIVE Lawyer'
    """
    partner, partner_headers = make_partner_lawyer()
    case = register_case(
        lead_lawyer_id=partner["id"], actor_headers=partner_headers,
    )
    add_verified_party(
        case_id=case["id"], party_role="PLAINTIFF",
        actor_headers=partner_headers,
    )
    res = api.activate_case(case["id"], partner_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_activation_succeeds_with_both_parties(api):
    """PRD §3.1: 'Activation of an INTAKE case to ACTIVE is a partner-only
    action.' Combined with the activation precondition list, the
    happy-path scenario should yield Case.status == ACTIVE.
    """
    partner, partner_headers, case = setup_partner_and_active_case()
    assert case["status"] == "ACTIVE"


def test_activate_already_active_rejected(api):
    """PRD §2.6: 'State-transition validity (priority 7,
    ERR_INVALID_STATE) is checked before any sub-resource side effects
    fire'

    Claim: activating an already-ACTIVE case → ERR_INVALID_STATE.
    """
    partner, partner_headers, case = setup_partner_and_active_case()
    res = api.activate_case(case["id"], partner_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_referenced_lead_lawyer_not_found(api):
    """PRD §2.6: 'then the existence of every foreign key in the request
    body (priority 4, ERR_REFERENCED_NOT_FOUND).'
    """
    partner, partner_headers = make_partner_lawyer()
    payload = create_case_payload(lead_lawyer_id=NON_EXISTENT_UUID)
    res = api.create_case(payload, partner_headers)
    validate_error(res, "ERR_REFERENCED_NOT_FOUND", expected_status=404)
