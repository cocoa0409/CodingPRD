"""Close-search, determination branches, final-fee cascade — PRD §3.8."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_search,
    create_exemption_claim,
    create_responsive_record,
    determine_request,
    get_fee_assessment,
    patch_record_disposition,
    setup_request_in_search,
    setup_request_in_determination_pending,
    validate_error,
    validate_success,
)


# ===========================================================================
# Close-search and final-fee cascade — PRD §3.8
# ===========================================================================
class TestCloseSearch:

    def test_close_search_with_no_third_party_records_succeeds(self, api):
        """PRD §3.8: "The officer closes the search by transitioning the
        request from `SEARCH` to `DETERMINATION_PENDING`."

        Claim: /close-search on a SEARCH request with no third-party
        records transitions to DETERMINATION_PENDING.
        """
        _r, request, _fa = setup_request_in_search()
        # Create a non-third-party record so determination can later
        # proceed; close-search itself doesn't require records.
        rec = create_responsive_record(
            request_id=request["id"], page_count=10,
        )
        patch_record_disposition(
            rec["id"], disposition="RELEASED_FULL", version=rec["version"],
        )
        closed = close_search(request["id"])
        assert closed["status"] == "DETERMINATION_PENDING"

    def test_close_search_cascades_final_total_cents_excluding_withheld(self, api):
        """PRD §3.8: "it recomputes the fee assessment's
        `final_total_cents` using the final-fee calculation described
        below, and it advances the assessment's `status` from `ACCEPTED`
        to `FINALIZED`".
        PRD §3.8: "chargeable pages are the sum of `page_count` across
        responsive records whose `disposition` is in `RELEASED_FULL` or
        `RELEASED_REDACTED` (records with `disposition` of `WITHHELD_FULL`
        do not count toward chargeable pages, but records with
        `RELEASED_REDACTED` count in full - the redaction does not
        pro-rate)."

        Claim: after /close-search on a commercial request with
        records (100 RELEASED_FULL + 30 RELEASED_REDACTED + 20
        WITHHELD_FULL), search=4h review=2h, FeeAssessment.status =
        FINALIZED and final_total_cents == 4*4500 + 2*6000 + 130*10 = 31300.
        """
        _r, request, fa, _records = setup_request_in_determination_pending(
            requester_tier="COMMERCIAL",
            estimated_pages=150,
            estimated_search_hours=4,
            estimated_review_hours=2,
            dispositions=[
                (100, "RELEASED_FULL", None),
                (30, "RELEASED_REDACTED", "B5"),
                (20, "WITHHELD_FULL", "B5"),
            ],
        )
        assert request["status"] == "DETERMINATION_PENDING"
        assert fa["status"] == "FINALIZED"
        assert fa["final_total_cents"] == 31300, (
            f"Expected 31300, got {fa['final_total_cents']}"
        )


# ===========================================================================
# Determination branches — PRD §3.8
# ===========================================================================
class TestDetermination:

    def test_determine_to_released_when_all_full(self, api):
        """PRD §3.8: "When every responsive record has `disposition` of
        `RELEASED_FULL`, the request transitions from
        `DETERMINATION_PENDING` to `RELEASED`".

        Claim: /determine with all RELEASED_FULL records transitions to
        RELEASED.
        """
        _r, request, _fa, _records = setup_request_in_determination_pending(
            dispositions=[(20, "RELEASED_FULL", None)],
        )
        determined = determine_request(request["id"])
        assert determined["status"] == "RELEASED"
        assert determined["determination_at"] is not None

    def test_determine_to_partial_release_with_mix(self, api):
        """PRD §3.8: "When at least one responsive record has
        `disposition` in the set `RELEASED_FULL` or `RELEASED_REDACTED`
        and at least one other record has `disposition` in the set
        `RELEASED_REDACTED` or `WITHHELD_FULL` (so the determination is
        a mix of released and withheld material), the request transitions
        from `DETERMINATION_PENDING` to `PARTIAL_RELEASE`".

        Claim: /determine with a RELEASED_FULL + RELEASED_REDACTED +
        WITHHELD_FULL mix transitions to PARTIAL_RELEASE.
        """
        _r, request, _fa, _records = setup_request_in_determination_pending(
            dispositions=[
                (10, "RELEASED_FULL", None),
                (5, "RELEASED_REDACTED", "B5"),
                (3, "WITHHELD_FULL", "B5"),
            ],
        )
        determined = determine_request(request["id"])
        assert determined["status"] == "PARTIAL_RELEASE"

    def test_determine_to_denied_when_all_withheld(self, api):
        """PRD §3.8: "When every responsive record has `disposition` of
        `WITHHELD_FULL` and at least one `ExemptionClaim` exists for
        each such record, the request transitions from
        `DETERMINATION_PENDING` to `DENIED`".

        Claim: /determine with all WITHHELD_FULL records + B5 exemptions
        transitions to DENIED.
        """
        _r, request, _fa, _records = setup_request_in_determination_pending(
            dispositions=[(7, "WITHHELD_FULL", "B5")],
        )
        determined = determine_request(request["id"])
        assert determined["status"] == "DENIED"

    def test_determine_with_no_records_rejected_err_no_responsive_records(self, api):
        """PRD §3.8: "Determination on a non-Glomar request with zero
        `ResponsiveRecord`s is rejected with `ERR_NO_RESPONSIVE_RECORDS`
        and HTTP 422."

        Claim: a request walked into DETERMINATION_PENDING with zero
        ResponsiveRecords (achievable via close-search after a search
        with no third-party records) fails /determine with
        ERR_NO_RESPONSIVE_RECORDS.
        """
        _r, request, _fa = setup_request_in_search()
        closed = close_search(request["id"])
        assert closed["status"] == "DETERMINATION_PENDING"
        resp = api.determine_request(
            request["id"], TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_RESPONSIVE_RECORDS.value)
        # After error, the request must still be DETERMINATION_PENDING.
        from test_helpers import get_request
        assert get_request(request["id"])["status"] == "DETERMINATION_PENDING"

    def test_determine_on_search_state_rejected(self, api):
        """PRD §3.8: "Beyond the determination branch, the close-search
        and determine actions also enforce procedural ordering. Close-search
        requires the request to be in `SEARCH`; determine requires it to be
        in `DETERMINATION_PENDING`; an action invoked against the wrong
        state is rejected with `ERR_INVALID_STATE` and HTTP 409."

        Claim: /determine while the request is still in SEARCH fails
        with ERR_INVALID_STATE.
        """
        _r, request, _fa = setup_request_in_search()
        resp = api.determine_request(
            request["id"], TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_close_search_on_acknowledged_state_rejected(self, api):
        """PRD §3.8: "Close-search requires the request to be in
        `SEARCH`; ... an action invoked against the wrong state is
        rejected with `ERR_INVALID_STATE` and HTTP 409."

        Claim: /close-search on an ACKNOWLEDGED request fails with
        ERR_INVALID_STATE.
        """
        from test_helpers import create_acknowledged_request
        _r, request = create_acknowledged_request()
        resp = api.close_search(
            request["id"], TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
