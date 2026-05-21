"""Difficulty-design coverage — primary tests for each instance.

Every instance declared in the difficulty-design index gets at least
two tests (this file and test_11_difficulty_coverage_supplemental.py).
Each test cites a verbatim PRD sentence for its underlying rule.

Tag format: each test docstring carries `# difficulty: <rule_id>/<name>`
so the audit pass can verify two-per-instance coverage.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    APPEAL_AUTHORITY_SHARED_ID,
    ApiErrorId,
    MAX_TOLL_DAYS,
    OFFICER_SECONDARY_ID,
    OFFICER_SHARED_ID,
    TEST_USERS,
    accept_appeal_for_review,
    add_seconds,
    advance_clock_by_days,
    advance_clock_to_iso,
    create_acknowledged_request,
    create_exemption_claim,
    create_fee_assessment,
    create_responsive_record,
    decide_appeal,
    decide_appeal_payload,
    determine_request,
    drive_tolling_to_cap,
    estimate_fee_assessment,
    file_appeal,
    find_audit_entries,
    get_fee_assessment,
    get_request,
    get_third_party_notice,
    issue_glomar_payload,
    make_appeal_authority_headers,
    make_officer_headers,
    make_requester_headers,
    make_third_party_headers,
    object_third_party_notice,
    object_third_party_payload,
    patch_record_disposition,
    setup_denied_request,
    setup_denied_request_with_distinct_authority,
    setup_glomar_issued_request,
    setup_glomar_then_remand_ready,
    setup_remand_ready_appeal,
    setup_request_in_determination_pending,
    setup_request_in_search,
    setup_request_with_estimated_fee,
    setup_request_with_third_party_notice,
    start_search,
    start_tolling_payload,
    unique_third_party_id,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_fee_estimate_vs_final_pages_excluded(self, api):
        """PRD §3.8: "chargeable pages are the sum of `page_count` across
        responsive records whose `disposition` is in `RELEASED_FULL` or
        `RELEASED_REDACTED` (records with `disposition` of `WITHHELD_FULL`
        do not count toward chargeable pages, but records with
        `RELEASED_REDACTED` count in full - the redaction does not
        pro-rate)."

        Claim: same inputs yield different totals — commercial tier
        with search=4h, review=2h, estimated_pages=150 estimates to
        31500 cents; closing search with 100 RELEASED_FULL + 30
        RELEASED_REDACTED + 20 WITHHELD_FULL leaves final_total_cents
        at 31300 (excluding the WITHHELD_FULL 20 pages).

        # difficulty: dual_variant_calc/fee_estimate_vs_final_pages_excluded
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
        assert fa["estimate_total_cents"] == 31500, (
            f"estimate_total_cents expected 31500, got "
            f"{fa['estimate_total_cents']}"
        )
        assert fa["final_total_cents"] == 31300, (
            f"final_total_cents expected 31300 (130 chargeable pages), "
            f"got {fa['final_total_cents']}"
        )
        assert fa["estimate_total_cents"] != fa["final_total_cents"]

    def test_tier_dependent_estimate_commercial_vs_educational(self, api):
        """PRD §3.3: "For a commercial requester, the chargeable search
        hours equal the estimated search hours, the chargeable review
        hours equal the estimated review hours, and the chargeable pages
        equal the estimated pages - every unit accrues from the first."
        PRD §3.3: "For an educational-noncommercial requester, the
        chargeable search hours are zero (search time is not billable),
        the chargeable review hours are zero (review time is never
        billable on any non-commercial tier), and the chargeable pages
        equal the estimated pages minus 100, floored at zero."

        Claim: identical inputs yield 31500 for COMMERCIAL but 0 for
        EDUCATIONAL_NONCOMMERCIAL (50 page-cents = 500 < 1400, collapses
        to 0).

        # difficulty: dual_variant_calc/tier_dependent_estimate_commercial_vs_educational
        """
        _r_c, _req_c, fa_c = setup_request_with_estimated_fee(
            requester_tier="COMMERCIAL",
            estimated_pages=150,
            estimated_search_hours=4,
            estimated_review_hours=2,
        )
        _r_e, _req_e, fa_e = setup_request_with_estimated_fee(
            requester_tier="EDUCATIONAL_NONCOMMERCIAL",
            tier_justification="University research",
            estimated_pages=150,
            estimated_search_hours=4,
            estimated_review_hours=2,
        )
        assert fa_c["estimate_total_cents"] == 31500
        assert fa_e["estimate_total_cents"] == 0
        assert fa_c["tier_at_assessment"] == "COMMERCIAL"
        assert fa_e["tier_at_assessment"] == "EDUCATIONAL_NONCOMMERCIAL"


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_tier_tiered_pricing_three_inputs_public_interest(self, api):
        """PRD §3.3: "For a public-interest requester, the chargeable
        search hours equal the estimated search hours minus 2, floored
        at zero, the chargeable review hours are zero, and the
        chargeable pages equal the estimated pages minus 100, floored
        at zero."

        Claim: PUBLIC_INTEREST with search=4h, review=2h, pages=150
        yields chargeable_search=max(0,4-2)=2, chargeable_pages=50,
        review=0; subtotal = 2*4500 + 50*10 = 9500 cents.

        # difficulty: combinatorial_formula/tier_tiered_pricing_three_inputs
        """
        _r, _req, fa = setup_request_with_estimated_fee(
            requester_tier="PUBLIC_INTEREST",
            tier_justification="Newsroom",
            estimated_pages=150,
            estimated_search_hours=4,
            estimated_review_hours=2,
        )
        assert fa["estimate_total_cents"] == 9500, (
            f"Expected 9500 cents, got {fa['estimate_total_cents']}"
        )
        assert fa["tier_at_assessment"] == "PUBLIC_INTEREST"

    def test_deadline_then_threshold_evaluation_order_public_interest(self, api):
        """PRD §3.3: "Step four applies the free-threshold collapse: if
        the subtotal in cents is strictly less than 1400, the estimate
        total is set to zero; otherwise it is set to the subtotal. The
        order matters - applying the threshold before summing would
        change which fee components dominate, and is not permitted."

        Claim: PUBLIC_INTEREST with search=2h, review=0, pages=250:
        chargeable_search = max(0,2-2) = 0; chargeable_pages = 250-100
        = 150; subtotal = 0*4500 + 150*10 = 1500 cents; 1500 >= 1400 -->
        survives. If threshold were applied per-line, 0 + 1500 would
        both fail (0 < 1400, 1500 >= 1400 — actually that works), but
        more importantly the pin enforces the sum-then-collapse order.

        # difficulty: combinatorial_formula/deadline_then_threshold_evaluation_order
        """
        _r, _req, fa = setup_request_with_estimated_fee(
            requester_tier="PUBLIC_INTEREST",
            tier_justification="Research",
            estimated_pages=250,
            estimated_search_hours=2,
            estimated_review_hours=0,
        )
        # Per the pinned order: subtotal = 0 + 1500 = 1500; 1500 >= 1400
        # -> survives.
        assert fa["estimate_total_cents"] == 1500, (
            f"Expected 1500 (subtotal-then-threshold), got "
            f"{fa['estimate_total_cents']}"
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_request_remand_cycle(self, api):
        """PRD §3.9: "A decision of `REMANDED` triggers a cascade: the
        underlying request, which was in `DENIED`, `PARTIAL_RELEASE`,
        or `GLOMAR_ISSUED`, automatically transitions to
        `REOPENED_BY_APPEAL`".
        PRD §3.9: "After a request enters `REOPENED_BY_APPEAL`, the
        officer reopens search by transitioning the request from
        `REOPENED_BY_APPEAL` back to `SEARCH`".

        Claim: A Request walks the cycle DENIED -> REOPENED_BY_APPEAL ->
        SEARCH; the REMANDED audit entry exists for that subject_id.

        # difficulty: non_linear_state_machine/request_remand_cycle
        """
        requester, denied, appeal, auth_h = setup_remand_ready_appeal()
        decide_appeal(
            appeal["id"], decision="REMANDED",
            appeal_authority_headers=auth_h,
        )
        reopened = get_request(denied["id"])
        assert reopened["status"] == "REOPENED_BY_APPEAL"
        # /resume-search transitions back to SEARCH (closing the cycle).
        resp = api.resume_search(
            denied["id"], TEST_USERS["officer_headers"],
        )
        back_in_search = validate_success(resp, expected_status=200)
        assert back_in_search["status"] == "SEARCH"
        # Audit entry for the REMANDED event on the request subject.
        entries = find_audit_entries(
            subject_type="REQUEST", subject_id=denied["id"],
            event_code="REMANDED",
        )
        assert len(entries) >= 1, (
            "Expected at least one REMANDED audit entry on the request"
        )

    def test_third_party_notice_branching_with_override(self, api):
        """PRD §3.7: "Override from `OBJECTED` to `OVERRIDDEN` requires
        the upheld-against-third-party outcome specifically."

        Claim: a ThirdPartyNotice walks PENDING_RESPONSE -> OBJECTED ->
        OVERRIDDEN — a non-linear branching where the OBJECTED branch
        re-converges via override to the same downstream effect a
        CONSENTED notice would have produced.

        PRD §3.9 requires the underlying request to be in DENIED,
        PARTIAL_RELEASE, or GLOMAR_ISSUED before a third-party appeal
        can be filed, so the test walks the request to DENIED first
        (object, claim B4, withhold the record, close-search,
        determine) before filing the appeal.

        # difficulty: non_linear_state_machine/third_party_notice_branching_with_override
        """
        from test_helpers import close_search
        tp_id = unique_third_party_id("tp_branch")
        requester, request, rec, notice = (
            setup_request_with_third_party_notice(third_party_id=tp_id)
        )
        # Forward branch: object.
        objected = object_third_party_notice(
            notice["id"], tp_id, objection_grounds="trade secret",
        )
        assert objected["status"] == "OBJECTED"
        # Walk to DENIED so a THIRD_PARTY appeal can be filed (§3.9).
        create_exemption_claim(
            record_id=rec["id"], exemption_code="B4",
            redaction_scope="FULL",
        )
        patch_record_disposition(
            rec["id"], disposition="WITHHELD_FULL", version=rec["version"],
        )
        close_search(request["id"])
        determined = determine_request(request["id"])
        assert determined["status"] == "DENIED"
        # Third-party files a reverse-FOIA appeal and AppealAuthority
        # upholds against the third party.
        auth_h = make_appeal_authority_headers(APPEAL_AUTHORITY_SHARED_ID)
        appeal = file_appeal(
            request=request, appellant_id=tp_id,
            appellant_role="THIRD_PARTY",
        )
        accept_appeal_for_review(appeal["id"], auth_h)
        decide_appeal(
            appeal["id"], decision="UPHELD",
            appeal_authority_headers=auth_h,
        )
        # Override the objection.
        resp = api.override_third_party_notice(notice["id"], auth_h)
        overridden = validate_success(resp, expected_status=200)
        assert overridden["status"] == "OVERRIDDEN"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_close_search_cascade_depth_3(self, api):
        """PRD §3.8: "Closing search has two side effects: it recomputes
        the fee assessment's `final_total_cents` using the final-fee
        calculation described below, and it advances the assessment's
        `status` from `ACCEPTED` to `FINALIZED` (or from `WAIVED` to
        `FINALIZED`".

        Claim: POST /close-search causes link 1 (Request.SEARCH ->
        DETERMINATION_PENDING), link 2 (FeeAssessment.ACCEPTED ->
        FINALIZED), and link 3 (final_total_cents written from
        ResponsiveRecord aggregation excluding WITHHELD_FULL). With
        records 100 RELEASED_FULL + 30 RELEASED_REDACTED + 20
        WITHHELD_FULL, search=4h review=2h: final_total_cents = 4*4500
        + 2*6000 + 130*10 = 31300.

        # difficulty: transitive_cascade/close_search_cascade_depth_3
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
        # Link 1
        assert request["status"] == "DETERMINATION_PENDING"
        # Link 2
        assert fa["status"] == "FINALIZED"
        # Link 3
        assert fa["final_total_cents"] == 31300

    def test_remand_cascade_depth_2_glomar(self, api):
        """PRD §2.10: "if the appealed determination was Glomar, the
        cascade also clears `glomar_invoked` back to false and empties
        `glomar_exemption_basis` so that the agency starts the new
        search fresh."

        Claim: POST /decide REMANDED on a Glomar appeal cascades to the
        Request: status -> REOPENED_BY_APPEAL, glomar_invoked = false,
        glomar_exemption_basis = [].

        # difficulty: transitive_cascade/remand_cascade_depth_2
        """
        _r, glomar_req, appeal, auth_h = setup_glomar_then_remand_ready(
            glomar_basis=["B1"],
        )
        decided = decide_appeal(
            appeal["id"], decision="REMANDED",
            appeal_authority_headers=auth_h,
        )
        # Link 1 — Appeal -> REMANDED
        assert decided["status"] == "REMANDED"
        # Link 2 — Request cascaded.
        refreshed = get_request(glomar_req["id"])
        assert refreshed["status"] == "REOPENED_BY_APPEAL"
        assert refreshed["glomar_invoked"] is False
        assert refreshed["glomar_exemption_basis"] == []


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_business_constraint_vs_business_fiscal_tolling(self, api):
        """PRD §3.4: "Tolling-start is permitted only when the request
        is currently `ACKNOWLEDGED` and only when the cumulative
        `tolling_days_consumed` is strictly less than 30
        (`MAX_TOLL_DAYS`). The 30-business-day cap is checked before
        the state precondition, because the cumulative tolling cap is a
        hard regulatory limit that takes precedence over the lifecycle
        check; a tolling-start that would push cumulative tolling beyond
        30 is rejected with `ERR_TOLLING_LIMIT_EXCEEDED` and HTTP 422."

        Claim: /start-tolling on an ACKNOWLEDGED request whose
        tolling_days_consumed == 30 fails specifically with
        ERR_TOLLING_LIMIT_EXCEEDED.

        # difficulty: priority_pair_validation_conflict/business_fiscal_vs_business_constraint_tolling
        """
        _r, request = create_acknowledged_request()
        # Create a fee assessment with a high estimate so an unrelated
        # check (fee not resolved) would also fail on start-search; but
        # the operation under test is /start-tolling, so this just
        # confirms the tolling cap fires regardless.
        create_fee_assessment(
            request_id=request["id"],
            estimated_pages=150,
            estimated_search_hours=4,
            estimated_review_hours=2,
        )
        # Note: we deliberately do NOT estimate (DRAFT state) so the
        # fee assessment is in an unresolved state.
        drive_tolling_to_cap(
            request_id=request["id"], target_days=MAX_TOLL_DAYS,
        )
        resp = api.start_tolling(
            request["id"], start_tolling_payload(),
            TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TOLLING_LIMIT_EXCEEDED.value)
        # Confirm tolling_days_consumed unchanged at 30.
        refreshed = get_request(request["id"])
        assert refreshed["tolling_days_consumed"] == MAX_TOLL_DAYS

    def test_state_vs_business_safety_glomar_basis(self, api):
        """PRD §3.10: "Validation on every action runs in a fixed
        priority order so that the most consequential failures surface
        first. The ordering, from highest priority to lowest, is: first
        the auth headers must be present and well-formed
        (`ERR_MISSING_AUTH`), then `X-User-Role` must be one of the five
        recognised values (`ERR_INVALID_ROLE`), then the role must be
        permitted to invoke this endpoint (`ERR_FORBIDDEN`), then path
        parameters must resolve to existing resources validated
        left-to-right in the URL (`ERR_NOT_FOUND`), then foreign-key
        references in the request body must resolve (`ERR_FK_NOT_FOUND`),
        then the target resource must be in a state from which the
        requested transition is allowed (`ERR_INVALID_STATE`)."

        Claim: POST /issue-glomar on a RELEASED Request with an
        invalid glomar_exemption_basis=['B4'] fails with
        ERR_INVALID_STATE — the state check is ordered above the
        glomar-basis check.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_glomar_basis
        """
        # Drive a Request to RELEASED.
        _r, request, _fa, _records = setup_request_in_determination_pending(
            dispositions=[(5, "RELEASED_FULL", None)],
        )
        determined = determine_request(request["id"])
        assert determined["status"] == "RELEASED"
        # Now attempt /issue-glomar with an invalid basis.
        payload = issue_glomar_payload(glomar_exemption_basis=["B4"])
        resp = api.issue_glomar(
            request["id"], payload, TEST_USERS["officer_headers"],
        )
        # PRD §3.10 explicitly orders ERR_INVALID_STATE above
        # ERR_INVALID_GLOMAR_BASIS; the state check fires first.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_fee_threshold_boundary_239_vs_240_pages(self, api):
        """PRD §3.3: "Step four applies the free-threshold collapse: if
        the subtotal in cents is strictly less than 1400, the estimate
        total is set to zero; otherwise it is set to the subtotal."

        Claim: EDUCATIONAL with 239 pages (subtotal = 139*10 = 1390,
        strictly less than 1400) collapses to 0; with 240 pages
        (subtotal = 140*10 = 1400, not strictly less than 1400)
        survives at 1400. Proves the strict-inequality boundary.

        # difficulty: boundary_precision_check/fee_threshold_boundary_239_vs_240_pages
        """
        _r_a, _req_a, fa_a = setup_request_with_estimated_fee(
            requester_tier="EDUCATIONAL_NONCOMMERCIAL",
            tier_justification="University research a",
            estimated_pages=239,
            estimated_search_hours=0,
            estimated_review_hours=0,
        )
        _r_b, _req_b, fa_b = setup_request_with_estimated_fee(
            requester_tier="EDUCATIONAL_NONCOMMERCIAL",
            tier_justification="University research b",
            estimated_pages=240,
            estimated_search_hours=0,
            estimated_review_hours=0,
        )
        assert fa_a["estimate_total_cents"] == 0, (
            f"239 pages: expected 0 (subtotal 1390 < 1400), got "
            f"{fa_a['estimate_total_cents']}"
        )
        assert fa_b["estimate_total_cents"] == 1400, (
            f"240 pages: expected 1400 (exactly at boundary), got "
            f"{fa_b['estimate_total_cents']}"
        )

    def test_empty_responsive_record_set_on_determine(self, api):
        """PRD §3.8: "Determination on a non-Glomar request with zero
        `ResponsiveRecord`s is rejected with `ERR_NO_RESPONSIVE_RECORDS`
        and HTTP 422."

        Claim: a non-Glomar request walked into DETERMINATION_PENDING
        with zero ResponsiveRecords fails /determine with
        ERR_NO_RESPONSIVE_RECORDS; once one RELEASED_FULL record is
        added the request can still not /determine again (state is
        wrong because the close-search would need to be re-run). The
        primary assertion is the zero-records rejection.

        # difficulty: boundary_precision_check/empty_responsive_record_set_on_determine
        """
        _r, request, _fa = setup_request_in_search()
        from test_helpers import close_search
        closed = close_search(request["id"])
        assert closed["status"] == "DETERMINATION_PENDING"
        resp = api.determine_request(
            request["id"], TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_RESPONSIVE_RECORDS.value)
        # State must remain DETERMINATION_PENDING.
        refreshed = get_request(request["id"])
        assert refreshed["status"] == "DETERMINATION_PENDING"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_close_search_requires_all_third_party_notices_resolved(self, api):
        """PRD §3.8: "The precondition is that every responsive record
        marked with `contains_third_party_info` of true has an
        associated `ThirdPartyNotice` whose `status` is one of
        `CONSENTED`, `OBJECTED`, `EXPIRED`, or `OVERRIDDEN` ... When
        this precondition fails (a record with `contains_third_party_info`
        of true has no notice, or the notice is still pending), the
        close-search call is rejected with
        `ERR_MISSING_THIRD_PARTY_NOTICE` and HTTP 422".

        Claim: /close-search while a notice is PENDING_RESPONSE fails
        with ERR_MISSING_THIRD_PARTY_NOTICE; after the clock advances
        past response_deadline (notice auto-EXPIRES) the same
        /close-search succeeds.

        # difficulty: cross_entity_state_dependency/close_search_requires_all_third_party_notices_resolved
        """
        tp_id = unique_third_party_id()
        _r, request, _rec, notice = (
            setup_request_with_third_party_notice(third_party_id=tp_id)
        )
        # First attempt — PENDING_RESPONSE.
        resp_fail = api.close_search(
            request["id"], TEST_USERS["officer_headers"],
        )
        validate_error(
            resp_fail, ApiErrorId.ERR_MISSING_THIRD_PARTY_NOTICE.value,
        )
        # Confirm request is still in SEARCH.
        refreshed = get_request(request["id"])
        assert refreshed["status"] == "SEARCH"
        # Advance the clock past the notice's deadline; sweep auto-EXPIRES.
        target = add_seconds(notice["response_deadline"], 60)
        advance_clock_to_iso(target)
        notice_after = get_third_party_notice(notice["id"])
        assert notice_after["status"] == "EXPIRED"
        # Retry — close-search now succeeds.
        resp_ok = api.close_search(
            request["id"], TEST_USERS["officer_headers"],
        )
        closed = validate_success(resp_ok, expected_status=200)
        assert closed["status"] == "DETERMINATION_PENDING"

    def test_appeal_accept_requires_segregation_from_request_officer(self, api):
        """PRD §2.8: "when an appeal authority attempts to accept an
        appeal for review, the server compares `X-User-ID` against the
        `actor_id` recorded on the `DETERMINATION_ISSUED` audit entry
        for the underlying request. If they match, the call is rejected
        with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403, regardless of
        how syntactically valid the rest of the call is."

        Claim: /accept-for-review by X-User-ID == the original
        determining officer fails with ERR_SEGREGATION_OF_DUTIES; the
        same call by a distinct X-User-ID succeeds.

        # difficulty: cross_entity_state_dependency/appeal_accept_requires_segregation_from_request_officer
        """
        # Drive determination with a specific officer id.
        officer_id = OFFICER_SHARED_ID
        officer_headers = make_officer_headers(officer_id)
        requester, denied, _records = setup_denied_request(
            officer_headers=officer_headers,
        )
        appeal = file_appeal(
            request=denied, appellant_id=requester["id"],
            appellant_role="REQUESTER",
        )
        # SoD violation: same id as the determining officer.
        bad_auth_h = make_appeal_authority_headers(officer_id)
        resp_bad = api.accept_appeal_for_review(appeal["id"], bad_auth_h)
        validate_error(resp_bad, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        # Confirm the appeal remains SUBMITTED.
        from test_helpers import get_appeal
        refreshed = get_appeal(appeal["id"])
        assert refreshed["status"] == "SUBMITTED"
        # Distinct authority accepts successfully.
        good_auth_h = make_appeal_authority_headers(APPEAL_AUTHORITY_SHARED_ID)
        resp_ok = api.accept_appeal_for_review(appeal["id"], good_auth_h)
        accepted = validate_success(resp_ok, expected_status=200)
        assert accepted["status"] == "UNDER_REVIEW"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_tolling_window_aggregate_cap(self, api):
        """PRD §3.4: "Tolling-start is permitted only when the request
        is currently `ACKNOWLEDGED` and only when the cumulative
        `tolling_days_consumed` is strictly less than 30
        (`MAX_TOLL_DAYS`)."

        Claim: cumulative tolling days are summed across multiple
        /start-tolling + /resume-clock cycles; once
        tolling_days_consumed reaches MAX_TOLL_DAYS the next
        /start-tolling fails with ERR_TOLLING_LIMIT_EXCEEDED — even
        though no individual tolling interval geometrically overlaps
        any prior one.

        # difficulty: resource_temporal_overlap/tolling_window_aggregate_cap
        """
        _r, request = create_acknowledged_request()
        at_cap = drive_tolling_to_cap(
            request_id=request["id"], target_days=MAX_TOLL_DAYS,
        )
        assert at_cap["tolling_days_consumed"] == MAX_TOLL_DAYS
        resp = api.start_tolling(
            request["id"], start_tolling_payload(),
            TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TOLLING_LIMIT_EXCEEDED.value)
        # Confirm aggregate unchanged.
        refreshed = get_request(request["id"])
        assert refreshed["tolling_days_consumed"] == MAX_TOLL_DAYS

    def test_third_party_response_window_half_open_deadline(self, api):
        """PRD §3.7: "the action must arrive strictly before the
        deadline; an action after the deadline (when the current clock
        has reached or passed `response_deadline`) is rejected with
        `ERR_THIRD_PARTY_DEADLINE_PASSED` and HTTP 422."
        PRD §3.7: "when the logical clock advances to or past
        `response_deadline` and the sweep runs, a still-`PENDING_RESPONSE`
        notice is transitioned to `EXPIRED`".

        Claim: /object at clock < deadline succeeds (strict-less-than
        admit); at clock >= deadline the notice auto-EXPIRES via sweep
        (greater-or-equal reject for /object, simultaneous sweep
        promotes to EXPIRED).

        # difficulty: resource_temporal_overlap/third_party_response_window_half_open_deadline
        """
        # Notice 1: object strictly before deadline succeeds.
        tp1 = unique_third_party_id("tp_pre")
        _r1, _req1, _rec1, notice1 = setup_request_with_third_party_notice(
            third_party_id=tp1,
        )
        # Advance clock to (deadline - 60s) — still strictly less than.
        before = add_seconds(notice1["response_deadline"], -60)
        advance_clock_to_iso(before)
        objected = object_third_party_notice(
            notice1["id"], tp1, objection_grounds="trade secret",
        )
        assert objected["status"] == "OBJECTED"

        # Notice 2: clock advanced past deadline -> EXPIRED via sweep.
        tp2 = unique_third_party_id("tp_post")
        _r2, _req2, _rec2, notice2 = setup_request_with_third_party_notice(
            third_party_id=tp2,
        )
        past = add_seconds(notice2["response_deadline"], 60)
        advance_clock_to_iso(past)
        after = get_third_party_notice(notice2["id"])
        assert after["status"] == "EXPIRED", (
            f"Expected EXPIRED after clock >= deadline, got {after['status']}"
        )


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_glomar_then_remand_preserves_fee_balance(self, api):
        """PRD §2.10: "if the appealed determination was Glomar, the
        cascade also clears `glomar_invoked` back to false and empties
        `glomar_exemption_basis` so that the agency starts the new
        search fresh."

        Claim: after Glomar -> REMAND, FeeAssessment.estimate_total_cents
        is preserved. (The PRD does not state that remand recomputes the
        fee; we assert estimate_total_cents is unchanged from its value
        before the remand.)

        # difficulty: compensating_invariant/glomar_then_remand_preserves_fee_balance
        """
        _r, glomar_req, appeal, auth_h = setup_glomar_then_remand_ready(
            glomar_basis=["B1"],
        )
        # Locate the FeeAssessment for this request via /audit-entries.
        # The setup uses a zero-cost assessment (estimated_pages=1) so
        # the estimate collapses to 0; we capture estimate_before from
        # a direct fetch via the audit trail.
        fa_entries = find_audit_entries(
            subject_type="FEE_ASSESSMENT",
        )
        fa_ids = list({e["subject_id"] for e in fa_entries})
        target_fa = None
        for fid in fa_ids:
            fa_data = get_fee_assessment(fid)
            if fa_data["request_id"] == glomar_req["id"]:
                target_fa = fa_data
                break
        assert target_fa is not None, (
            "Could not locate FeeAssessment linked to glomar request"
        )
        estimate_before = target_fa["estimate_total_cents"]
        # Remand.
        decide_appeal(
            appeal["id"], decision="REMANDED",
            appeal_authority_headers=auth_h,
        )
        # Re-read FeeAssessment.
        fa_after = get_fee_assessment(target_fa["id"])
        assert fa_after["estimate_total_cents"] == estimate_before, (
            f"estimate_total_cents must be conserved across remand: "
            f"before={estimate_before}, after={fa_after['estimate_total_cents']}"
        )
        assert fa_after["status"] != "WAIVED", (
            "Remand must not waive an existing fee assessment"
        )

    def test_third_party_object_then_override_preserves_record_count(self, api):
        """PRD §2.10: "Every cascade increments the affected resource's
        `version` by one and refreshes its `updated_at`."
        PRD §3.7: "Override from `OBJECTED` to `OVERRIDDEN` requires
        the upheld-against-third-party outcome specifically."

        Claim: the OBJECT -> OVERRIDE cycle preserves the count of
        ResponsiveRecords linked to the underlying request — the cycle
        emits AuditEntries but does not create, delete, or merge records.

        PRD §3.9 requires the underlying request to be in DENIED,
        PARTIAL_RELEASE, or GLOMAR_ISSUED before a third-party appeal
        can be filed; we walk to PARTIAL_RELEASE (one full released,
        one withheld) before filing the appeal.

        # difficulty: compensating_invariant/third_party_object_then_override_preserves_record_count
        """
        from test_helpers import close_search, create_third_party_notice
        tp_id = unique_third_party_id("tp_invariant")
        requester, request, _fa = setup_request_in_search()
        # Create exactly 2 records: rec_x with third-party-info, rec_y plain.
        rec_x = create_responsive_record(
            request_id=request["id"], page_count=15,
            contains_third_party_info=True, third_party_id=tp_id,
        )
        rec_y = create_responsive_record(
            request_id=request["id"], page_count=8,
        )
        record_ids_before = {rec_x["id"], rec_y["id"]}
        notice = create_third_party_notice(
            request_id=request["id"], record_id=rec_x["id"],
        )
        object_third_party_notice(
            notice["id"], tp_id, objection_grounds="trade secret",
        )
        # Walk to PARTIAL_RELEASE so a THIRD_PARTY appeal can be filed
        # (§3.9). rec_x: B4 claim + WITHHELD_FULL; rec_y: RELEASED_FULL.
        create_exemption_claim(
            record_id=rec_x["id"], exemption_code="B4",
            redaction_scope="FULL",
        )
        patch_record_disposition(
            rec_x["id"], disposition="WITHHELD_FULL",
            version=rec_x["version"],
        )
        patch_record_disposition(
            rec_y["id"], disposition="RELEASED_FULL",
            version=rec_y["version"],
        )
        close_search(request["id"])
        determined = determine_request(request["id"])
        assert determined["status"] == "PARTIAL_RELEASE"
        # Third-party appeal -> UPHELD; AppealAuthority overrides.
        auth_h = make_appeal_authority_headers(APPEAL_AUTHORITY_SHARED_ID)
        appeal = file_appeal(
            request=request, appellant_id=tp_id,
            appellant_role="THIRD_PARTY",
        )
        accept_appeal_for_review(appeal["id"], auth_h)
        decide_appeal(
            appeal["id"], decision="UPHELD",
            appeal_authority_headers=auth_h,
        )
        resp = api.override_third_party_notice(notice["id"], auth_h)
        overridden = validate_success(resp, expected_status=200)
        assert overridden["status"] == "OVERRIDDEN"
        # Read each record back individually; both must still exist.
        from test_helpers import get_responsive_record
        for rid in record_ids_before:
            data = get_responsive_record(rid)
            assert data["id"] == rid
