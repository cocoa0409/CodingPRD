"""Party and Property registration (PRD §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_party,
    assert_property,
    party_payload,
    property_payload,
    validate_error,
    validate_success,
    with_idempotency,
)


# ===========================================================================
# Party CRUD — PRD §3.1
# ===========================================================================
class TestPartyCreation:

    @pytest.mark.parametrize(
        "party_kind",
        ["BUYER", "SELLER", "LENDER", "QUALIFIED_INTERMEDIARY"],
    )
    def test_create_party_each_kind(
        self, api, escrow_officer_headers, party_kind,
    ):
        """PRD §3.1: "a party_kind drawn from the closed set BUYER,
        SELLER, LENDER, or QUALIFIED_INTERMEDIARY".

        Claim: creating a party with each allowed party_kind succeeds
        and returns 201 with the kind echoed back.
        """
        headers = with_idempotency(escrow_officer_headers)
        payload = party_payload(party_kind=party_kind)
        resp = api.create_party(payload, headers)
        data = validate_success(resp, expected_status=201)
        assert_party(data)
        assert data["party_kind"] == party_kind
        assert data["full_name"] == payload["full_name"]
        assert data["contact_email"] == payload["contact_email"]

    def test_read_party_succeeds(self, api, escrow_officer_headers):
        """PRD §3.1: parties are pre-registered; reading returns the
        party (PRD §4 lists GET /parties/{partyId})."""
        headers = with_idempotency(escrow_officer_headers)
        create = api.create_party(party_payload(party_kind="BUYER"), headers)
        created = validate_success(create, expected_status=201)
        get = api.get_party(created["id"], escrow_officer_headers)
        fetched = validate_success(get)
        assert fetched["id"] == created["id"]
        assert fetched["party_kind"] == "BUYER"

    def test_read_nonexistent_party_returns_404(
        self, api, escrow_officer_headers,
    ):
        """PRD §2.8: "existence of every entity referenced by a path
        parameter or body foreign key, evaluated left-to-right against
        the URL (ERR_NOT_FOUND)".

        Claim: GET /parties/{unknown} yields ERR_NOT_FOUND.
        """
        resp = api.get_party(NON_EXISTENT_UUID, escrow_officer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# Property CRUD — PRD §3.1
# ===========================================================================
class TestPropertyCreation:

    def test_create_property_minimum(self, api, escrow_officer_headers):
        """PRD §3.1: "Properties are likewise pre-registered with a
        street_address, a county-assessor parcel_id, the annual HOA
        dues on hoa_annual_dues (defaulting to zero when the parcel has
        no association), and the annual property tax on tax_annual
        (also defaulting to zero)".

        Claim: creating a property succeeds; HOA and tax defaults work.
        """
        headers = with_idempotency(escrow_officer_headers)
        payload = property_payload(
            hoa_annual_dues=0, tax_annual=0,
        )
        resp = api.create_property(payload, headers)
        data = validate_success(resp, expected_status=201)
        assert_property(data)
        assert data["hoa_annual_dues"] == 0
        assert data["tax_annual"] == 0

    def test_create_property_with_dues_and_tax(
        self, api, escrow_officer_headers,
    ):
        """PRD §3.1: "the latter two are not merely descriptive — they
        are the proration inputs the system later consumes when it
        computes the Closing Disclosure's seller credits."

        Claim: hoa_annual_dues and tax_annual are persisted as supplied.
        """
        headers = with_idempotency(escrow_officer_headers)
        payload = property_payload(hoa_annual_dues=789.0, tax_annual=1234.0)
        resp = api.create_property(payload, headers)
        data = validate_success(resp, expected_status=201)
        assert data["hoa_annual_dues"] == pytest.approx(789.0)
        assert data["tax_annual"] == pytest.approx(1234.0)

    def test_read_nonexistent_property_returns_404(
        self, api, escrow_officer_headers,
    ):
        """PRD §2.8: existence check yields ERR_NOT_FOUND."""
        resp = api.get_property(NON_EXISTENT_UUID, escrow_officer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
