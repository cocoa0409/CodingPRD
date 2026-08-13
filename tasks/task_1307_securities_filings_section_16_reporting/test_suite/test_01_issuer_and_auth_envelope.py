"""Issuer onboarding, request-envelope rules, auth context, and issuer OCC
(§2.1, §2.2, §2.4, §2.8, §2.9, §3.1)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    is_valid_uuid, NON_EXISTENT_UUID, ApiErrorId,
    assert_issuer, create_issuer_payload, create_reporting_person_payload,
    make_compliance_officer_headers,
    create_issuer, create_reporting_person,
)


class TestIssuerCreation:
    def test_create_issuer_defaults_applied(self, api):
        """PRD §3.1: "Two optional attributes complete the profile: `holiday_dates`,
        a list of exchange holiday dates as `YYYY-MM-DD` strings that the
        business-day routine skips (empty when omitted), and
        `next_earnings_filing_date`, the date of the issuer's next periodic
        earnings report, which feeds the officer/director cooling-off extension
        and may remain unset."
        PRD §2.4: "`id`: a unique server-minted identifier, formatted as a UUID
        with no type prefix." and "`created_at`: an ISO 8601 UTC timestamp with
        three fractional digits, set when the resource is created."

        Design: Corner/entities/create_issuer_defaults_applied
        """
        resp = api.create_issuer(create_issuer_payload(),
                                 make_compliance_officer_headers())
        data = validate_success(resp, 201)
        assert_issuer(data)
        assert data["holiday_dates"] == [], (
            f"Expected holiday_dates default [], got {data['holiday_dates']}")
        assert data.get("next_earnings_filing_date") is None, (
            f"Expected next_earnings_filing_date unset, "
            f"got {data.get('next_earnings_filing_date')}")
        # created_at carries three fractional digits per PRD §2.4
        created_at = data["created_at"]
        frac = created_at.split(".", 1)[1]
        assert frac[:3].isdigit() and frac[3:] == "Z", (
            f"created_at must carry three fractional digits, got {created_at}")

    def test_create_issuer_missing_required_cik_returns_invalid_request(self, api):
        """PRD §3.1: "A `ComplianceOfficer` registers each public company as an
        Issuer, supplying its legal `name`, the exchange `ticker` symbol, the
        ten-digit SEC Central Index Key `cik`, the current EDGAR confirmation
        code `edgar_ccc`, the common-share count `shares_outstanding` (which
        must be greater than zero and serves as the denominator of the basic
        ownership percentage), and the `fiscal_year_end_month` as an integer
        from 1 to 12, where 12 denotes a December 31 fiscal year end."
        PRD §2.8: "On every mutation, required fields must be present, enum
        values must be valid, dates must be well-formed, a blackout's
        `start_date` must not be later than its `end_date`, `shares` must be
        greater than zero, `shares_delta` must not be zero, and
        `price_per_share` must be present for transaction codes `P` and `S`.
        Violations yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_issuer_missing_required_cik_returns_invalid_request
        """
        payload = create_issuer_payload()
        del payload["cik"]
        resp = api.create_issuer(payload, make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_missing_person_returns_not_found(self, api):
        """PRD §2.8: "Every identifier appearing in the URL path — `issuerId`,
        `blackoutWindowId`, `personId`, `transactionId`, `filingId`, `planId`,
        `holderId`, `positionChangeId`, `sweepId`, `authorizationId` — is
        verified to exist, validated left to right; the first missing identifier
        yields `ERR_NOT_FOUND` before any body or business validation runs."

        Design: Corner/entities/get_missing_person_returns_not_found
        """
        resp = api.get_reporting_person(NON_EXISTENT_UUID,
                                        make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthContext:
    def test_auth_context_missing_headers_returns_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, declaring the
        operator's capacity. A request in which either header is missing or
        empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/rbac/auth_context_missing_headers_returns_400
        """
        resp = api.create_issuer(create_issuer_payload(), {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestIssuerOptimisticConcurrency:
    def test_put_issuer_stale_version_returns_412(self, api):
        """PRD §2.9: "Updating an issuer — `PUT /issuers/{issuerId}` — requires
        the request to carry `expected_issuer_version` equal to the issuer's
        current `version`. Issuer configuration is freely editable, so both an
        older and a newer write would legitimately succeed on product semantics;
        if the issuer's `version` has advanced since the client last observed
        it, the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.1: "The update is guarded by the issuer's expected version as
        described in §2.9 and increments the issuer's `version` by one on
        success."

        Design: Corner/validations/put_issuer_stale_version_returns_412
        """
        issuer = create_issuer()
        observed_version = issuer["version"]
        updated = get_success_data(api.update_issuer(
            issuer["id"],
            {"expected_issuer_version": observed_version,
             "shares_outstanding": 2000000},
            make_compliance_officer_headers()))
        assert updated["version"] == observed_version + 1, (
            f"Expected version to increment by one from {observed_version}, "
            f"got {updated['version']}")
        resp = api.update_issuer(
            issuer["id"],
            {"expected_issuer_version": observed_version,
             "holiday_dates": ["2026-08-10"]},
            make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
