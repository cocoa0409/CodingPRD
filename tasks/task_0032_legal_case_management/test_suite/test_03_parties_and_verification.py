"""Party creation, multi-role binding, and identity verification.

PRD §3.2.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    add_verified_party,
    api_client,
    assert_party,
    create_party_payload,
    setup_partner_and_active_case,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Multi-role binding (PRD §3.2)
# ---------------------------------------------------------------------------
def test_create_party_default_unverified(api):
    """PRD §3.2: 'A newly created party always has identity_verified
    equal to false.'
    """
    partner, partner_headers, case = setup_partner_and_active_case()
    payload = create_party_payload(party_role="PLAINTIFF")
    res = api.create_party(case["id"], payload, partner_headers)
    party = validate_success(res, 201)
    assert_party(party)
    assert party["identity_verified"] is False


def test_party_default_access_level_standard(api):
    """PRD §3.2: 'The access_level defaults to STANDARD and may be
    STANDARD, RESTRICTED, or NONE, controlling what case data the party
    itself may read.'
    """
    partner, partner_headers, case = setup_partner_and_active_case()
    payload = create_party_payload(party_role="PLAINTIFF")
    payload.pop("access_level", None)
    party = validate_success(
        api.create_party(case["id"], payload, partner_headers), 201
    )
    assert party["access_level"] == "STANDARD"


def test_verify_identity_flips_flag(api):
    """PRD §3.2: 'An intake clerk or partner verifies a party's identity
    in a separate operation that flips identity_verified to true.'
    """
    partner, partner_headers, case = setup_partner_and_active_case()
    payload = create_party_payload(party_role="WITNESS")
    party = validate_success(
        api.create_party(case["id"], payload, partner_headers), 201
    )
    assert party["identity_verified"] is False
    verified = validate_success(
        api.verify_party_identity(party["id"], partner_headers), 200
    )
    assert verified["identity_verified"] is True


# ---------------------------------------------------------------------------
# Phone validation (PRD §3.2)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("phone", ["12345", "123456"])  # < 7 chars
def test_contact_phone_too_short_rejected(api, phone):
    """PRD §3.2: 'contact_phone must be between 7 and 20 characters
    inclusive.'

    Phones below 7 characters violate that length constraint, which
    PRD §5 surfaces via ERR_VALIDATION_FAILED for generic length
    violations.
    """
    partner, partner_headers, case = setup_partner_and_active_case()
    payload = create_party_payload(
        party_role="WITNESS", contact_phone=phone,
    )
    res = api.create_party(case["id"], payload, partner_headers)
    validate_error(res, "ERR_VALIDATION_FAILED", expected_status=422)


def test_contact_phone_too_long_rejected(api):
    """PRD §3.2: 'contact_phone must be between 7 and 20 characters
    inclusive.'
    """
    partner, partner_headers, case = setup_partner_and_active_case()
    payload = create_party_payload(
        party_role="WITNESS", contact_phone="1" * 21,
    )
    res = api.create_party(case["id"], payload, partner_headers)
    validate_error(res, "ERR_VALIDATION_FAILED", expected_status=422)
