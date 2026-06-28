"""Foundation-referral eligibility, validation-ordering existence precedence, the
backup-requires-sump constraint, RBAC exclusivity, authentication, and job listing /
pagination.

Covers Difficulty queue: priority_pair_validation_conflict (existence before referral
eligibility on send).
Covers Corner queue: referral send non-severe, backup-requires-sump on quote create,
estimator-cannot-accept-quote RBAC, missing-headers unauthenticated, list-jobs pagination
envelope, list-jobs pagination limit out of bounds.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_quote_payload, create_foundation_referral_payload,
    create_homeowner, create_job, create_finalized_inspection, create_sent_quote,
    make_homeowner_headers,
    TEST_USERS, MISSING_UUID,
)

EST = TEST_USERS["estimator_headers"]
INS = TEST_USERS["inspector_headers"]


class TestReferralEligibility:
    def test_send_non_severe_referral_returns_not_eligible(self, api):
        """PRD §3.3: "Sending a referral moves it from `DRAFT` to `SENT`, but only when the
        referenced inspection is `FINALIZED` with a severity of exactly `SEVERE`. A send
        against an inspection that is not finalized-and-severe is rejected with
        `ERR_REFERRAL_NOT_ELIGIBLE` (HTTP 422)".

        Design: Corner/validations/referral_send_non_severe_returns_not_eligible
        """
        # moisture 40 (<60, +0) + 2 structural (min(2,4)*2=4) => score 4 => MODERATE (not SEVERE).
        ho = create_homeowner(credit_band="PRIME")
        job = create_job(ho["id"], footprint_sqft=900, structure_type="COMBINED")
        insp = create_finalized_inspection(job["id"], moisture_pct=40,
                                           structural_findings_count=2)
        assert insp["severity"] == "MODERATE"
        referral = get_success_data(api.create_foundation_referral(
            job["id"], create_foundation_referral_payload(insp["id"], "SolidGround"), INS))
        res = api.send_foundation_referral(referral["id"], INS)
        validate_error(res, "ERR_REFERRAL_NOT_ELIGIBLE", expected_status=422)
        ref_after = validate_success(api.get_foundation_referral(referral["id"], INS), 200)
        assert ref_after["status"] == "DRAFT"

    def test_send_nonexistent_referral_returns_not_found(self, api):
        """PRD §2.6: "The system resolves these identifiers left to right and rejects the
        request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
        correspond to an existing resource."
        PRD §2.7: "Then path-resource existence is verified left to right, yielding
        `ERR_NOT_FOUND`. ... Only after all of those does the system evaluate ... the
        domain-specific business rules".

        Design: Difficulty/priority_pair_validation_conflict/existence_before_referral_eligibility_on_send
        """
        # No referral with this id exists; existence (P3) outranks the eligibility check (P10).
        res = api.send_foundation_referral(MISSING_UUID, INS)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)


class TestBackupRequiresSump:
    def test_backup_without_sump_on_create_rejected(self, api):
        """PRD §3.4: "setting `includes_battery_backup` to true requires `includes_sump` to
        also be true on the same quote, both at quote creation and at quote revision. A
        battery-backup flag without a sump on the same quote is rejected with
        `ERR_BACKUP_REQUIRES_SUMP` (HTTP 422)."

        Design: Corner/validations/backup_requires_sump_on_quote_create
        """
        ho = create_homeowner(credit_band="PRIME")
        job = create_job(ho["id"], footprint_sqft=600, structure_type="BASEMENT")
        res = api.create_quote(job["id"], create_quote_payload(
            includes_battery_backup=True, includes_sump=False), EST)
        validate_error(res, "ERR_BACKUP_REQUIRES_SUMP", expected_status=422)


class TestRbacAndAuth:
    def test_estimator_cannot_accept_quote(self, api):
        """PRD §2.1: "When the headers are present but the declared role is not permitted to
        invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §3.5: "The `Homeowner` accepts a sent quote to turn the deal into a sale."

        Design: Corner/rbac/estimator_cannot_accept_quote
        """
        ho = create_homeowner(credit_band="PRIME")
        job = create_job(ho["id"], footprint_sqft=600, structure_type="BASEMENT")
        create_finalized_inspection(job["id"], moisture_pct=65, structural_findings_count=0)
        quote = create_sent_quote(job["id"], includes_sump=True)
        res = api.accept_quote(quote["id"], {"expected_quote_version": quote["version"]}, EST)
        validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)

    def test_missing_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying
        the acting user, and `X-User-Role`, declaring the capacity in which they act. A
        request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_headers_returns_unauthenticated
        """
        res = api.get_job(MISSING_UUID, {"Content-Type": "application/json"})
        validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


class TestJobListing:
    def test_list_jobs_pagination_envelope(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
        `has_more` inside the envelope's `meta` object."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        Design: Corner/endpoints/list_jobs_pagination_envelope
        """
        ho = create_homeowner(credit_band="PRIME")
        create_job(ho["id"], footprint_sqft=700, structure_type="CRAWLSPACE")
        create_job(ho["id"], footprint_sqft=800, structure_type="BASEMENT")
        data, meta = validate_paginated(
            api.list_jobs(EST, params={"homeowner_id": ho["id"], "limit": 10, "offset": 0}))
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

    def test_list_jobs_limit_over_max_rejected(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
        to 10 when omitted, must be at least 1, and may not exceed 100. ... A `limit` or
        `offset` outside those bounds is rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

        Design: Corner/endpoints/list_jobs_pagination_limit_out_of_bounds
        """
        ho = create_homeowner(credit_band="PRIME")
        create_job(ho["id"], footprint_sqft=600, structure_type="BASEMENT")
        res = api.list_jobs(EST, params={"limit": 101})
        validate_error(res, "ERR_PAGINATION_INVALID", expected_status=400)
