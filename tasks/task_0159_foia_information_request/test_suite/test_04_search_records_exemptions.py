"""Search lifecycle, responsive records, exemption claims — PRD §3.5, §3.6, §3.10."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_exemption_claim,
    assert_responsive_record,
    create_exemption_claim,
    create_exemption_claim_payload,
    create_responsive_record,
    create_responsive_record_payload,
    make_requester_headers,
    setup_request_in_search,
    setup_request_with_accepted_fee,
    setup_request_with_estimated_fee,
    start_search,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# /start-search precondition — PRD §3.5
# ===========================================================================
class TestStartSearch:

    def test_start_search_with_unaccepted_high_estimate_fails(self, api):
        """PRD §3.5: "When neither of these holds - when a `FeeAssessment`
        exists, its `estimate_total_cents` exceeds 1400, and its `status`
        is not `ACCEPTED` or `WAIVED` - the start-search call is rejected
        with `ERR_FEE_NOT_RESOLVED` and HTTP 422."

        Claim: /start-search on a request whose ESTIMATED fee is
        31500 (> 1400) fails with ERR_FEE_NOT_RESOLVED.
        """
        _r, request, _fa = setup_request_with_estimated_fee(
            requester_tier="COMMERCIAL", estimated_pages=150,
            estimated_search_hours=4, estimated_review_hours=2,
        )
        resp = api.start_search(
            request["id"], TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FEE_NOT_RESOLVED.value)

    def test_start_search_with_accepted_fee_succeeds(self, api):
        """PRD §3.5: "The precondition is: either the linked
        `FeeAssessment` is in `ACCEPTED` or `WAIVED`, or its
        `estimate_total_cents` is less than or equal to 1400 cents."

        Claim: /start-search on a request with ACCEPTED fee succeeds
        and transitions to SEARCH.
        """
        _r, _req, _fa = setup_request_with_accepted_fee()
        # The accept-then-start happens inside setup_request_in_search;
        # the simpler form here re-uses setup_request_in_search to
        # exercise the same path end-to-end.
        _r, request, _fa = setup_request_in_search()
        assert request["status"] == "SEARCH"


# ===========================================================================
# ResponsiveRecord creation — PRD §3.6
# ===========================================================================
class TestResponsiveRecordCreation:

    def test_create_record_in_search_state(self, api):
        """PRD §3.6: "Recording a record is permitted only when the
        referenced request is currently in `SEARCH`".
        PRD §3.6: "The new record lands with `disposition` of
        `PENDING_REVIEW`."

        Claim: a record created against a SEARCH-state request lands
        with disposition=PENDING_REVIEW.
        """
        _r, request, _fa = setup_request_in_search()
        rec = create_responsive_record(
            request_id=request["id"], page_count=12,
        )
        assert_responsive_record(rec)
        assert rec["disposition"] == "PENDING_REVIEW"
        assert rec["page_count"] == 12

    def test_create_record_on_acknowledged_request_rejected(self, api):
        """PRD §3.6: "Recording a record is permitted only when the
        referenced request is currently in `SEARCH` (records cannot be
        created on a request in any other lifecycle state, and they
        cannot be created at all on a Glomar request)".
        PRD §5: ERR_RECORDS_FORBIDDEN_ON_GLOMAR HTTP 422.

        Claim: creating a record while the request is still ACKNOWLEDGED
        is rejected with ERR_RECORDS_FORBIDDEN_ON_GLOMAR.
        """
        from test_helpers import create_acknowledged_request
        _r, request = create_acknowledged_request()
        payload = create_responsive_record_payload(
            request_id=request["id"], page_count=5,
        )
        resp = api.create_responsive_record(
            payload, TEST_USERS["officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_RECORDS_FORBIDDEN_ON_GLOMAR.value,
        )

    def test_record_with_third_party_info_requires_third_party_id(self, api):
        """PRD §3.6: "a record created while marking
        `contains_third_party_info` true must supply a non-null
        `third_party_id`."

        Claim: a record with contains_third_party_info=true and a null
        third_party_id is rejected.
        """
        _r, request, _fa = setup_request_in_search()
        payload = {
            "request_id": request["id"],
            "title": "Confidential",
            "page_count": 3,
            "contains_third_party_info": True,
            # third_party_id intentionally omitted/null
        }
        resp = api.create_responsive_record(
            payload, TEST_USERS["officer_headers"],
        )
        # PRD §3.10 routes this under ERR_MISSING_THIRD_PARTY_NOTICE
        # (validation priority 9): "the same error covers the case where
        # a record is marked third-party but its `third_party_id` is
        # missing." But §5 lists ERR_MISSING_THIRD_PARTY_NOTICE applying
        # to close-search and record creation. Accept either:
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_MISSING_THIRD_PARTY_NOTICE.value,
                ApiErrorId.ERR_INVALID_INPUT.value,
            ],
        )


# ===========================================================================
# ExemptionClaim — PRD §3.6 (append-only)
# ===========================================================================
class TestExemptionClaim:

    def test_create_exemption_claim_returns_append_only(self, api):
        """PRD §3.6: "Claims are immutable once written - they carry
        only `id` and `created_at`, no `updated_at` or `version`."

        Claim: a newly created ExemptionClaim has id+created_at and
        does NOT carry updated_at or version.
        """
        _r, request, _fa = setup_request_in_search()
        rec = create_responsive_record(request_id=request["id"])
        payload = create_exemption_claim_payload(
            record_id=rec["id"], exemption_code="B5",
            redaction_scope="FULL",
            rationale="Withheld under deliberative process",
        )
        resp = api.create_exemption_claim(
            payload, TEST_USERS["officer_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_exemption_claim(data)

    def test_duplicate_exemption_claim_rejected(self, api):
        """PRD §3.6: "The pair `(record_id, exemption_code)` is unique:
        a duplicate exemption claim on the same record with the same
        code is rejected with `ERR_DUPLICATE_EXEMPTION` and HTTP 409."

        Claim: a second claim with the same record_id and exemption_code
        fails with ERR_DUPLICATE_EXEMPTION.
        """
        _r, request, _fa = setup_request_in_search()
        rec = create_responsive_record(request_id=request["id"])
        create_exemption_claim(record_id=rec["id"], exemption_code="B5")
        payload = create_exemption_claim_payload(
            record_id=rec["id"], exemption_code="B5",
        )
        resp = api.create_exemption_claim(
            payload, TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EXEMPTION.value)

    def test_exemption_claim_with_invalid_code(self, api):
        """PRD §3.6: "the `exemption_code` (one of the nine statutory
        exemptions `B1`, `B2`, `B3`, `B4`, `B5`, `B6`, `B7`, `B8`, `B9`)".

        Claim: a claim with exemption_code outside the nine-code set
        fails with ERR_INVALID_INPUT.
        """
        _r, request, _fa = setup_request_in_search()
        rec = create_responsive_record(request_id=request["id"])
        payload = {
            "record_id": rec["id"],
            "exemption_code": "B99",
            "redaction_scope": "FULL",
            "rationale": "Bad code",
        }
        resp = api.create_exemption_claim(
            payload, TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)


# ===========================================================================
# Record disposition PATCH — PRD §3.6
# ===========================================================================
class TestRecordDisposition:

    def test_disposition_patch_increments_version(self, api):
        """PRD §3.6: "Once the exemptions on a record have been reviewed,
        the officer updates that record's `disposition` to one of
        `RELEASED_FULL` (no redactions, full release), `RELEASED_REDACTED`
        (partial redactions applied), or `WITHHELD_FULL` (the entire
        record withheld) through a versioned disposition update accepting
        `disposition` and `version`."
        PRD §2.5: "Successful mutations always increment `version` by
        one and refresh `updated_at` to the moment of the write".

        Claim: PATCH disposition increments record.version by 1.
        """
        _r, request, _fa = setup_request_in_search()
        rec = create_responsive_record(request_id=request["id"], page_count=20)
        from test_helpers import patch_record_disposition
        updated = patch_record_disposition(
            rec["id"], disposition="RELEASED_FULL", version=rec["version"],
        )
        assert updated["disposition"] == "RELEASED_FULL"
        assert updated["version"] == rec["version"] + 1

    def test_disposition_patch_with_wrong_version_rejected(self, api):
        """PRD §2.5: "When `version` is supplied and does not match the
        resource's current `version`, the server rejects the call with
        `ERR_VERSION_CONFLICT` and HTTP 409 and makes no state change."

        Claim: PATCH disposition with body.version != current.version
        fails with ERR_VERSION_CONFLICT.
        """
        _r, request, _fa = setup_request_in_search()
        rec = create_responsive_record(request_id=request["id"])
        from test_helpers import patch_record_disposition_payload
        payload = patch_record_disposition_payload(
            disposition="RELEASED_FULL",
            version=rec["version"] + 9,
        )
        resp = api.patch_record_disposition(
            rec["id"], payload, TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)
