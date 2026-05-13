"""Rights-holder lifecycle: creation, minor handling, guardian rules
(PRD §3.5, §2.10 priority 10)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_rights_holder,
    create_individual_rights_holder_payload,
    create_minor_rights_holder_payload,
    create_org_holder,
    create_rights_holder,
    create_rights_holder_payload,
    setup_minor_with_guardian,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestCreateOrganization:

    def test_create_organization_minimal(self, api, pa_headers):
        """PRD §3.5: 'A PlatformAdmin provisions every RightsHolder with
        their legal_name (1 to 200 characters), a holder_kind of either
        INDIVIDUAL or ORGANIZATION, a tax_jurisdiction (exactly two
        uppercase letters, the ISO country code that determines
        withholding), a payout_currency from the set {USD, EUR, GBP, JPY,
        CNY}, and a tokenised bank_account_token of 1 to 64 characters
        from the payment system.'

        Claim: PlatformAdmin can create an ORGANIZATION RightsHolder with
        the documented field set; response carries the assigned id.
        """
        resp = api.create_rights_holder(
            create_rights_holder_payload(holder_kind="ORGANIZATION"),
            pa_headers,
        )
        data = validate_success(resp, 201)
        assert_rights_holder(data)
        assert data["holder_kind"] == "ORGANIZATION"

    def test_organization_is_not_minor(self, api, pa_headers):
        """PRD §3.5: 'The platform computes is_minor at creation time as
        a frozen boolean: it is true if and only if the holder is an
        INDIVIDUAL and the elapsed time between date_of_birth and the
        current date is strictly less than 18 years on the date the
        record was created.'

        Claim: An ORGANIZATION RightsHolder has is_minor == false.
        """
        h = create_org_holder()
        assert h["is_minor"] is False


class TestCreateIndividual:

    def test_adult_individual_no_guardian_required(self, api, pa_headers):
        """PRD §3.5: 'For individuals, the date_of_birth must also be
        supplied as an ISO 8601 YYYY-MM-DD date.' The is_minor formula
        is_minor iff INDIVIDUAL AND age < 18 at creation; an adult
        therefore needs no guardian.

        Claim: An INDIVIDUAL with DOB > 18 years ago is created without
        guardian_holder_id and carries is_minor == false.
        """
        resp = api.create_rights_holder(
            create_individual_rights_holder_payload(
                date_of_birth="1980-01-01",
            ),
            pa_headers,
        )
        data = validate_success(resp, 201)
        assert data["holder_kind"] == "INDIVIDUAL"
        assert data["is_minor"] is False

    def test_minor_with_valid_org_guardian(self, api):
        """PRD §3.5: 'When is_minor evaluates to true at create time, a
        guardian_holder_id must be supplied and must reference an
        existing RightsHolder that is either an ORGANIZATION or an
        INDIVIDUAL whose own is_minor is false.'

        Claim: minor + ORGANIZATION guardian succeeds; is_minor == true.
        """
        minor, guardian = setup_minor_with_guardian()
        assert minor["is_minor"] is True
        assert minor["guardian_holder_id"] == guardian["id"]
        assert minor["holder_kind"] == "INDIVIDUAL"

    def test_minor_missing_guardian_rejected(self, api, pa_headers):
        """PRD §3.5 / §2.10 priority 10: 'a missing or invalid guardian
        rejects creation with ERR_MINOR_REQUIRES_GUARDIAN.'

        Claim: minor INDIVIDUAL without guardian_holder_id →
        ERR_MINOR_REQUIRES_GUARDIAN (422).
        """
        # Use a clearly-recent DOB to force is_minor=true.
        payload = create_individual_rights_holder_payload(
            date_of_birth="2018-01-01",
        )
        # No guardian_holder_id supplied.
        resp = api.create_rights_holder(payload, pa_headers)
        validate_error(resp, ApiErrorId.ERR_MINOR_REQUIRES_GUARDIAN.value, 422)

    def test_minor_with_unknown_guardian_id_rejected(self, api, pa_headers):
        """PRD §3.5: 'guardian_holder_id ... must reference an existing
        RightsHolder ...; a missing or invalid guardian rejects creation
        with ERR_MINOR_REQUIRES_GUARDIAN.' PRD §2.5 also says body FK
        guardian_holder_id resolution yields ERR_NOT_FOUND. PRD §2.10
        priority list does NOT explicitly cover guardian_holder_id under
        priorities 4–5 (path-only / share-endpoint-only), so a faithful
        reader could choose either ERR_NOT_FOUND or
        ERR_MINOR_REQUIRES_GUARDIAN.

        Claim: minor with guardian_holder_id pointing to a non-existent
        RightsHolder → one of {ERR_NOT_FOUND, ERR_MINOR_REQUIRES_GUARDIAN}.
        """
        payload = create_minor_rights_holder_payload(
            guardian_holder_id=NON_EXISTENT_UUID,
            date_of_birth="2018-01-01",
        )
        resp = api.create_rights_holder(payload, pa_headers)
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_NOT_FOUND.value,
                ApiErrorId.ERR_MINOR_REQUIRES_GUARDIAN.value,
            ],
        )

    def test_minor_with_minor_guardian_rejected(self, api, pa_headers):
        """PRD §3.5: 'guardian_holder_id ... must reference an existing
        RightsHolder that is either an ORGANIZATION or an INDIVIDUAL
        whose own is_minor is false.'

        Claim: minor whose guardian is itself a minor INDIVIDUAL →
        ERR_MINOR_REQUIRES_GUARDIAN (422).
        """
        # Build the guardian-of-minor: requires its OWN adult guardian.
        outer_guardian = create_org_holder(legal_name="Outer Org Guardian")
        guardian_minor = validate_success(api.create_rights_holder(
            create_minor_rights_holder_payload(
                guardian_holder_id=outer_guardian["id"],
                date_of_birth="2015-01-01",
            ),
            pa_headers,
        ), 201)
        # Now try to use guardian_minor (is_minor=true) as a guardian.
        resp = api.create_rights_holder(
            create_minor_rights_holder_payload(
                guardian_holder_id=guardian_minor["id"],
                date_of_birth="2018-01-01",
            ),
            pa_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MINOR_REQUIRES_GUARDIAN.value, 422)


class TestReadAndList:

    def test_get_rights_holder_returns_expected_shape(self, api, pa_headers):
        """PRD §2.4: 'every resource that this PRD treats as
        common-fields-bearing — Work, RightsHolder, AgencyBinding ...
        carries the standard four-tuple: an id ... a created_at
        timestamp ... an updated_at timestamp ... and an integer version
        that starts at 1 at creation.'

        Claim: GET /royalty/rights-holders/{id} returns id +
        created_at + updated_at + version (>= 1) and the domain fields.
        """
        h = create_rights_holder(legal_name="Read-Test Holder")
        resp = api.get_rights_holder(h["id"], pa_headers)
        data = validate_success(resp, 200)
        assert_rights_holder(data)
        assert data["version"] >= 1

    def test_list_rights_holders_paginates(self, api, pa_headers):
        """PRD §2.3: list endpoints accept limit and offset and meta
        reports total_count and has_more.

        Claim: page of holders returns a list under data and meta with
        limit/offset/total_count/has_more.
        """
        for _ in range(3):
            create_rights_holder()
        resp = api.list_rights_holders(pa_headers, params={"limit": 2})
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert meta["limit"] == 2
        assert meta["total_count"] >= 3
