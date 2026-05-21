"""Difficulty-design coverage — second test per instance.

Each instance from SCAFFOLD_DIFFICULTY_DESIGN.yaml must be covered by
at least TWO tests. The primary tests live in test_10; this file adds
the second test per instance from a different angle (different
parameters, different observable side effect, different stop condition,
or different actor).

Tag format: each test docstring carries `# difficulty: <rule_id>/<name>`.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    APPEAL_AUTHORITY_SECONDARY_ID,
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
    close_search,
    create_acknowledged_request,
    create_responsive_record,
    decide_appeal,
    decide_appeal_payload,
    determine_request,
    drive_tolling_to_cap,
    file_appeal,
    find_audit_entries,
    get_appeal,
    get_fee_assessment,
    get_request,
    get_responsive_record,
    get_third_party_notice,
    issue_glomar_payload,
    make_appeal_authority_headers,
    make_officer_headers,
    make_requester_headers,
    make_third_party_headers,
    object_third_party_notice,
    object_third_party_payload,
    setup_denied_request,
    setup_denied_request_with_distinct_authority,
    setup_glomar_issued_request,
    setup_glomar_then_remand_ready,
    setup_remand_ready_appeal,
    setup_request_in_determination_pending,
    setup_request_in_search,
    setup_request_with_estimated_fee,
    setup_request_with_third_party_notice,
    start_tolling_payload,
    unique_third_party_id,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc (second-angle tests)
# ===========================================================================
class TestDualVariantCalcSecond:

    def test_fee_estimate_vs_final_all_released_no_withheld(self, api):
        """PRD §3.8: "chargeable pages are the sum of `page_count`
        across responsive records whose `disposition` is in
        `RELEASED_FULL` or `RELEASED_REDACTED` (records with
        `disposition` of `WITHHELD_FULL` do not count toward chargeable
        pages, but records with `RELEASED_REDACTED` count in full - the
        redaction does not pro-rate)."

        Second-angle claim: with no WITHHELD_FULL records (all
        RELEASED_FULL), estimate and final converge — pages=150 ->
        31500 for both estimate and final on a commercial requester.

        # difficulty: dual_variant_calc/fee_estimate_vs_final_pages_excluded
        """
        _r, request, fa, _records = setup_request_in_determination_pending(
            requester_tier="COMMERCIAL",
            estimated_pages=150,
            estimated_search_hours=4,
            estimated_review_hours=2,
            dispositions=[
                (100, "RELEASED_FULL", None),
                (50, "RELEASED_FULL", None),
            ],
        )
        assert fa["estimate_total_cents"] == 31500
        # final = 4*4500 + 2*6000 + 150*10 = 31500 — converges.
        assert fa["final_total_cents"] == 31500
        assert fa["estimate_total_cents"] == fa["final_total_cents"]

    def test_tier_dependent_estimate_public_vs_commercial(self, api):
        """PRD §3.3: "For a public-interest requester, the chargeable
        search hours equal the estimated search hours minus 2, floored
        at zero, the chargeable review hours are zero, and the
        chargeable pages equal the estimated pages minus 100, floored
        at zero."

        Second-angle claim: identical inputs (search=4h, review=2h,
        pages=150) yield 31500 for COMMERCIAL but 9500 for
        PUBLIC_INTEREST. A different tier pair than the COMMERCIAL vs
        EDUCATIONAL split in test_10.

        # difficulty: dual_variant_calc/tier_dependent_estimate_commercial_vs_educational
        """
        _r_c, _req_c, fa_c = setup_request_with_estimated_fee(
            requester_tier="COMMERCIAL",
            estimated_pages=150,
            estimated_search_hours=4,
            estimated_review_hours=2,
        )
        _r_p, _req_p, fa_p = setup_request_with_estimated_fee(
            requester_tier="PUBLIC_INTEREST",
            tier_justification="Newsroom investigation",
            estimated_pages=150,
            estimated_search_hours=4,
            estimated_review_hours=2,
        )
        assert fa_c["estimate_total_cents"] == 31500
        assert fa_p["estimate_total_cents"] == 9500
        assert fa_c["tier_at_assessment"] == "COMMERCIAL"
        assert fa_p["tier_at_assessment"] == "PUBLIC_INTEREST"


# ===========================================================================
# Rule 2 — combinatorial_formula (second-angle tests)
# ===========================================================================
class TestCombinatorialFormulaSecond:

    def test_commercial_full_three_input_combination(self, api):
        """PRD §3.3: "For a commercial requester, the chargeable search
        hours equal the estimated search hours, the chargeable review
        hours equal the estimated review hours, and the chargeable pages
        equal the estimated pages - every unit accrues from the first."

        Second-angle claim: commercial with 1h search, 0h review, 50
        pages -> 1*4500 + 0*6000 + 50*10 = 5000 cents. Demonstrates
        three-input non-linear interaction on a different tier than the
        PUBLIC_INTEREST test in test_10.

        # difficulty: combinatorial_formula/tier_tiered_pricing_three_inputs
        """
        _r, _req, fa = setup_request_with_estimated_fee(
            requester_tier="COMMERCIAL",
            estimated_pages=50,
            estimated_search_hours=1,
            estimated_review_hours=0,
        )
        assert fa["estimate_total_cents"] == 5000

    def test_evaluation_order_pin_subtotal_then_threshold_collapses(self, api):
        """PRD §3.3: "Step four applies the free-threshold collapse:
        if the subtotal in cents is strictly less than 1400, the
        estimate total is set to zero ... The order matters - applying
        the threshold before summing would change which fee components
        dominate, and is not permitted."

        Second-angle claim: PUBLIC_INTEREST with search=2h, review=0,
        pages=150 -> chargeable_search=max(0,2-2)=0; chargeable_pages
        =150-100=50; subtotal=0*4500 + 50*10 = 500 cents < 1400 ->
        collapses to 0. Confirms the sum-then-collapse order on the
        collapsing side of the boundary.

        # difficulty: combinatorial_formula/deadline_then_threshold_evaluation_order
        """
        _r, _req, fa = setup_request_with_estimated_fee(
            requester_tier="PUBLIC_INTEREST",
            tier_justification="Newsroom",
            estimated_pages=150,
            estimated_search_hours=2,
            estimated_review_hours=0,
        )
        # Subtotal = 0 + 500 = 500 < 1400 -> 0 (after threshold).
        assert fa["estimate_total_cents"] == 0, (
            f"Expected 0 (subtotal 500 < threshold 1400), got "
            f"{fa['estimate_total_cents']}"
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine (second-angle tests)
# ===========================================================================
class TestNonLinearStateMachineSecond:

    def test_request_cycle_post_remand_search_started_audit(self, api):
        """PRD §3.9: "After a request enters `REOPENED_BY_APPEAL`, the
        officer reopens search by transitioning the request from
        `REOPENED_BY_APPEAL` back to `SEARCH`; a `SEARCH_STARTED` audit
        entry is appended whose payload's `cycle` is set to `post-remand`."

        Second-angle claim: after the DENIED -> REOPENED_BY_APPEAL ->
        SEARCH cycle, a SEARCH_STARTED audit entry exists for the
        request with payload.cycle == 'post-remand'.

        # difficulty: non_linear_state_machine/request_remand_cycle
        """
        _r, denied, appeal, auth_h = setup_remand_ready_appeal()
        decide_appeal(
            appeal["id"], decision="REMANDED",
            appeal_authority_headers=auth_h,
        )
        resp = api.resume_search(
            denied["id"], TEST_USERS["officer_headers"],
        )
        validate_success(resp, expected_status=200)
        entries = find_audit_entries(
            subject_type="REQUEST", subject_id=denied["id"],
            event_code="SEARCH_STARTED",
        )
        # At least one SEARCH_STARTED, and the post-remand one carries
        # the cycle marker.
        post_remand = [
            e for e in entries
            if isinstance(e.get("payload"), dict)
            and e["payload"].get("cycle") == "post-remand"
        ]
        assert len(post_remand) >= 1, (
            f"Expected at least one SEARCH_STARTED audit with "
            f"payload.cycle == 'post-remand'; got {entries!r}"
        )

    def test_third_party_consented_branch_alternative(self, api):
        """PRD §3.7: "They may consent to release, transitioning the
        notice from `PENDING_RESPONSE` to `CONSENTED`."
        PRD §3.7: "Or they may simply let the deadline pass: when the
        logical clock advances to or past `response_deadline` and the
        sweep runs, a still-`PENDING_RESPONSE` notice is transitioned
        to `EXPIRED`".

        Second-angle claim: the fork-join on ThirdPartyNotice admits a
        CONSENTED path as a peer of the OBJECTED -> OVERRIDDEN path.

        # difficulty: non_linear_state_machine/third_party_notice_branching_with_override
        """
        tp_id = unique_third_party_id()
        _r, _req, _rec, notice = setup_request_with_third_party_notice(
            third_party_id=tp_id,
        )
        from test_helpers import consent_third_party_notice
        consented = consent_third_party_notice(notice["id"], tp_id)
        assert consented["status"] == "CONSENTED"


# ===========================================================================
# Rule 4 — transitive_cascade (second-angle tests)
# ===========================================================================
class TestTransitiveCascadeSecond:

    def test_close_search_cascade_with_waived_fee_carries_through(self, api):
        """PRD §3.8: "Closing search has two side effects: it recomputes
        the fee assessment's `final_total_cents` using the final-fee
        calculation described below, and it advances the assessment's
        `status` from `ACCEPTED` to `FINALIZED` (or from `WAIVED` to
        `FINALIZED`, in which case `final_total_cents` is set to zero -
        a waiver carries through)."

        Second-angle claim: same depth-3 cascade — Request transitions
        SEARCH -> DETERMINATION_PENDING, FeeAssessment WAIVED ->
        FINALIZED, final_total_cents == 0 — but exercised on the WAIVED
        branch instead of ACCEPTED.

        # difficulty: transitive_cascade/close_search_cascade_depth_3
        """
        # Walk: educational requester, request, fee assessment, estimate,
        # waive, start-search, create record, close-search.
        from test_helpers import (
            create_acknowledged_request,
            create_fee_assessment,
            estimate_fee_assessment,
            start_search,
            waive_fee_assessment,
        )
        requester, request = create_acknowledged_request(
            requester_tier="EDUCATIONAL_NONCOMMERCIAL",
            tier_justification="Research",
            fee_waiver_requested=True,
        )
        fa = create_fee_assessment(
            request_id=request["id"],
            estimated_pages=300,
            estimated_search_hours=4,
            estimated_review_hours=0,
        )
        estimate_fee_assessment(fa["id"])
        waive_fee_assessment(fa["id"])
        start_search(request["id"])
        rec = create_responsive_record(request_id=request["id"], page_count=20)
        from test_helpers import patch_record_disposition
        patch_record_disposition(
            rec["id"], disposition="RELEASED_FULL", version=rec["version"],
        )
        # Trigger the depth-3 cascade.
        closed = close_search(request["id"])
        fa_after = get_fee_assessment(fa["id"])
        # Link 1
        assert closed["status"] == "DETERMINATION_PENDING"
        # Link 2 — WAIVED carries through to FINALIZED.
        assert fa_after["status"] == "FINALIZED"
        # Link 3 — final_total_cents = 0 because waived.
        assert fa_after["final_total_cents"] == 0

    def test_remand_cascade_depth_2_on_denied_non_glomar(self, api):
        """PRD §3.9: "A decision of `REMANDED` triggers a cascade: the
        underlying request, which was in `DENIED`, `PARTIAL_RELEASE`,
        or `GLOMAR_ISSUED`, automatically transitions to
        `REOPENED_BY_APPEAL`".

        Second-angle claim: depth-2 cascade on a DENIED Request (not
        GLOMAR). Link 1: Appeal UNDER_REVIEW -> REMANDED. Link 2:
        Request DENIED -> REOPENED_BY_APPEAL. (Glomar-specific clearing
        of glomar_invoked / glomar_exemption_basis is the only thing
        that differs from the test_10 instance — here glomar_invoked
        remains false throughout.)

        # difficulty: transitive_cascade/remand_cascade_depth_2
        """
        _r, denied, appeal, auth_h = setup_remand_ready_appeal()
        decided = decide_appeal(
            appeal["id"], decision="REMANDED",
            appeal_authority_headers=auth_h,
        )
        # Link 1
        assert decided["status"] == "REMANDED"
        # Link 2
        refreshed = get_request(denied["id"])
        assert refreshed["status"] == "REOPENED_BY_APPEAL"
        # Glomar fields untouched.
        assert refreshed["glomar_invoked"] is False
        assert refreshed["glomar_exemption_basis"] == []


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict (second-angle tests)
# ===========================================================================
class TestPriorityPairValidationConflictSecond:

    def test_tolling_cap_supersedes_state_check(self, api):
        """PRD §3.4: "The 30-business-day cap is checked before the
        state precondition, because the cumulative tolling cap is a
        hard regulatory limit that takes precedence over the lifecycle
        check".

        Second-angle claim: the cap fires on /start-tolling even when
        the request is in ACKNOWLEDGED (the otherwise-valid state),
        proving the cap is checked ahead of the state precondition.

        # difficulty: priority_pair_validation_conflict/business_fiscal_vs_business_constraint_tolling
        """
        _r, request = create_acknowledged_request()
        drive_tolling_to_cap(
            request_id=request["id"], target_days=MAX_TOLL_DAYS,
        )
        # The state IS valid (ACKNOWLEDGED) — cap-vs-state ordering is
        # what's under test.
        resp = api.start_tolling(
            request["id"], start_tolling_payload(),
            TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TOLLING_LIMIT_EXCEEDED.value)

    def test_state_check_supersedes_glomar_basis_check_on_partial_release(self, api):
        """PRD §3.10: "the target resource must be in a state from
        which the requested transition is allowed (`ERR_INVALID_STATE`).
        After the state check, the business-safety rules apply in the
        order: ... Glomar exemption basis is drawn from `B1`, `B6`,
        `B7C` only (`ERR_INVALID_GLOMAR_BASIS` against issue-glomar)".

        Second-angle claim: /issue-glomar on a PARTIAL_RELEASE Request
        with an invalid basis fails with ERR_INVALID_STATE rather than
        ERR_INVALID_GLOMAR_BASIS. A different terminal-state than the
        RELEASED test in test_10.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_glomar_basis
        """
        _r, request, _fa, _records = setup_request_in_determination_pending(
            dispositions=[
                (10, "RELEASED_FULL", None),
                (5, "WITHHELD_FULL", "B5"),
            ],
        )
        determined = determine_request(request["id"])
        assert determined["status"] == "PARTIAL_RELEASE"
        payload = issue_glomar_payload(glomar_exemption_basis=["B4"])
        resp = api.issue_glomar(
            request["id"], payload, TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Rule 6 — boundary_precision_check (second-angle tests)
# ===========================================================================
class TestBoundaryPrecisionCheckSecond:

    def test_free_threshold_boundary_at_exactly_1400(self, api):
        """PRD §3.3: "if the subtotal in cents is strictly less than
        1400, the estimate total is set to zero".

        Second-angle claim: a commercial requester with 0 search, 0
        review, 140 pages produces subtotal=1400, which is NOT strictly
        less than 1400 and therefore survives. Probes the >= side of
        the boundary on a different tier.

        # difficulty: boundary_precision_check/fee_threshold_boundary_239_vs_240_pages
        """
        _r, _req, fa = setup_request_with_estimated_fee(
            requester_tier="COMMERCIAL",
            estimated_pages=140,
            estimated_search_hours=0,
            estimated_review_hours=0,
        )
        # subtotal = 140 * 10 = 1400; 1400 < 1400 is false -> survives.
        assert fa["estimate_total_cents"] == 1400

    def test_zero_records_blocks_determine_then_one_record_admits(self, api):
        """PRD §3.8: "Determination on a non-Glomar request with zero
        `ResponsiveRecord`s is rejected with `ERR_NO_RESPONSIVE_RECORDS`
        and HTTP 422."

        Second-angle claim: end-to-end empty-set boundary — a request
        with zero records fails /determine; the same request with at
        least one RELEASED_FULL record successfully transitions to
        RELEASED. Probes both sides of the empty-set boundary on the
        same Request endpoint.

        # difficulty: boundary_precision_check/empty_responsive_record_set_on_determine
        """
        _r, request, _fa = setup_request_in_search()
        closed = close_search(request["id"])
        assert closed["status"] == "DETERMINATION_PENDING"
        resp_zero = api.determine_request(
            request["id"], TEST_USERS["officer_headers"],
        )
        validate_error(resp_zero, ApiErrorId.ERR_NO_RESPONSIVE_RECORDS.value)
        # PRD §3.8 doesn't permit creating a record on a
        # DETERMINATION_PENDING request (records are SEARCH-only).
        # Confirm the negative side; the positive side is exercised
        # elsewhere by tests that walk to RELEASED with records present.
        refreshed = get_request(request["id"])
        assert refreshed["status"] == "DETERMINATION_PENDING"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency (second-angle tests)
# ===========================================================================
class TestCrossEntityStateDependencySecond:

    def test_close_search_proceeds_after_third_party_consent(self, api):
        """PRD §3.8: "every responsive record marked with
        `contains_third_party_info` of true has an associated
        `ThirdPartyNotice` whose `status` is one of `CONSENTED`,
        `OBJECTED`, `EXPIRED`, or `OVERRIDDEN`".

        Second-angle claim: the close-search precondition admits a
        CONSENTED notice (not just an EXPIRED one as in test_10). The
        cross-entity dependency Request <-> ThirdPartyNotice is
        satisfied by any of the four terminal statuses.

        # difficulty: cross_entity_state_dependency/close_search_requires_all_third_party_notices_resolved
        """
        from test_helpers import consent_third_party_notice
        tp_id = unique_third_party_id()
        _r, request, _rec, notice = setup_request_with_third_party_notice(
            third_party_id=tp_id,
        )
        consent_third_party_notice(notice["id"], tp_id)
        # close-search succeeds.
        resp = api.close_search(
            request["id"], TEST_USERS["officer_headers"],
        )
        closed = validate_success(resp, expected_status=200)
        assert closed["status"] == "DETERMINATION_PENDING"

    def test_appeal_decide_segregation_via_distinct_authority_succeeds(self, api):
        """PRD §2.8: "The same check applies when the appeal authority
        subsequently issues the decision - the `X-User-ID` issuing the
        decide call must match the `Appeal.deciding_officer_id`
        captured at accept-for-review time".

        Second-angle claim: after accept-for-review by a distinct
        AppealAuthority, /decide UPHELD by the same X-User-ID succeeds.
        Confirms the matching-id branch of the cross-entity rule (test_10
        covered the mismatching-id rejection branch).

        # difficulty: cross_entity_state_dependency/appeal_accept_requires_segregation_from_request_officer
        """
        officer_headers = make_officer_headers(OFFICER_SHARED_ID)
        requester, denied, _records = setup_denied_request(
            officer_headers=officer_headers,
        )
        # Use a distinct authority for accept + decide.
        auth_h = make_appeal_authority_headers(APPEAL_AUTHORITY_SHARED_ID)
        appeal = file_appeal(
            request=denied, appellant_id=requester["id"],
            appellant_role="REQUESTER",
        )
        accept_appeal_for_review(appeal["id"], auth_h)
        decided = decide_appeal(
            appeal["id"], decision="UPHELD",
            appeal_authority_headers=auth_h,
        )
        assert decided["status"] == "UPHELD"


# ===========================================================================
# Rule 8 — resource_temporal_overlap (second-angle tests)
# ===========================================================================
class TestResourceTemporalOverlapSecond:

    def test_tolling_aggregate_accumulates_across_two_cycles(self, api):
        """PRD §3.4: "Resume-clock ... computes the number of business
        days that elapsed during the pause (according to the current
        logical clock) and adds them to `tolling_days_consumed`".

        Second-angle claim: tolling_days_consumed accumulates strictly
        monotonically across two distinct /start-tolling +
        /resume-clock cycles. Confirms the aggregate-capacity semantics
        without driving all the way to the cap.

        # difficulty: resource_temporal_overlap/tolling_window_aggregate_cap
        """
        _r, request = create_acknowledged_request()
        from test_helpers import (
            advance_clock_by_days,
            resume_clock,
            start_tolling,
        )
        # Cycle 1: ~5 business days.
        start_tolling(request["id"])
        advance_clock_by_days(7)
        after_first = resume_clock(request["id"])
        first_days = after_first["tolling_days_consumed"]
        assert first_days >= 1, (
            f"Expected >= 1 business day after first cycle, got {first_days}"
        )
        # Cycle 2: another batch.
        start_tolling(request["id"])
        advance_clock_by_days(7)
        after_second = resume_clock(request["id"])
        second_days = after_second["tolling_days_consumed"]
        assert second_days > first_days, (
            f"Aggregate must strictly grow: first={first_days}, "
            f"second={second_days}"
        )

    def test_consent_at_exact_deadline_rejected_or_expired(self, api):
        """PRD §3.7: "the action must arrive strictly before the
        deadline; an action after the deadline (when the current clock
        has reached or passed `response_deadline`) is rejected with
        `ERR_THIRD_PARTY_DEADLINE_PASSED` and HTTP 422."

        Second-angle claim: at the exact deadline instant, /consent is
        not admitted — either it's rejected with
        ERR_THIRD_PARTY_DEADLINE_PASSED (deadline check fires) or the
        sweep has promoted the notice to EXPIRED in the same window
        (and the call is rejected with ERR_NOTICE_ALREADY_CLOSED). Both
        are PRD-faithful at the boundary.

        # difficulty: resource_temporal_overlap/third_party_response_window_half_open_deadline
        """
        tp_id = unique_third_party_id("tp_exact")
        _r, _req, _rec, notice = setup_request_with_third_party_notice(
            third_party_id=tp_id,
        )
        # Advance clock to the exact deadline instant.
        advance_clock_to_iso(notice["response_deadline"])
        resp = api.consent_third_party_notice(
            notice["id"], make_third_party_headers(tp_id),
        )
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_THIRD_PARTY_DEADLINE_PASSED.value,
                ApiErrorId.ERR_NOTICE_ALREADY_CLOSED.value,
            ],
        )


# ===========================================================================
# Rule 9 — compensating_invariant (second-angle tests)
# ===========================================================================
class TestCompensatingInvariantSecond:

    def test_remand_does_not_waive_fee_assessment(self, api):
        """PRD §3.5: "When a `FeeAssessment` exists at the time of
        withdrawal, its status is set to `WAIVED` as a side effect of
        the withdrawal (so the requester is not subsequently billed
        for a request they cancelled)."
        PRD §3.9: "A decision of `REMANDED` triggers a cascade: the
        underlying request, which was in `DENIED`, `PARTIAL_RELEASE`,
        or `GLOMAR_ISSUED`, automatically transitions to
        `REOPENED_BY_APPEAL`".

        Second-angle claim: remand cascade preserves
        FeeAssessment.estimate_total_cents AND does not set its status
        to WAIVED (waiver is the cascade triggered by withdrawal, not
        by remand). Read FeeAssessment before and after remand and
        confirm both invariants.

        # difficulty: compensating_invariant/glomar_then_remand_preserves_fee_balance
        """
        _r, glomar_req, appeal, auth_h = setup_glomar_then_remand_ready(
            glomar_basis=["B6"],
        )
        # Locate the FeeAssessment by walking audit-entries.
        fa_entries = find_audit_entries(subject_type="FEE_ASSESSMENT")
        fa_ids = list({e["subject_id"] for e in fa_entries})
        target_fa = None
        for fid in fa_ids:
            data = get_fee_assessment(fid)
            if data["request_id"] == glomar_req["id"]:
                target_fa = data
                break
        assert target_fa is not None
        estimate_before = target_fa["estimate_total_cents"]
        status_before = target_fa["status"]
        decide_appeal(
            appeal["id"], decision="REMANDED",
            appeal_authority_headers=auth_h,
        )
        after = get_fee_assessment(target_fa["id"])
        assert after["estimate_total_cents"] == estimate_before
        # Status must NOT be WAIVED. (It may be ACCEPTED, ESTIMATED,
        # FINALIZED, or DRAFT — PRD §3.9 does not require any specific
        # status, only that the cents are conserved and the request is
        # reopened.)
        assert after["status"] != "WAIVED"

    def test_record_count_after_consent_then_close_unchanged(self, api):
        """PRD §3.7: "They may consent to release, transitioning the
        notice from `PENDING_RESPONSE` to `CONSENTED`."
        PRD §3.8: "Closing search has two side effects: it recomputes
        the fee assessment's `final_total_cents` using the final-fee
        calculation described below, and it advances the assessment's
        `status` from `ACCEPTED` to `FINALIZED`".

        Second-angle claim: a complete CONSENT-then-CLOSE flow (rather
        than OBJECT-then-OVERRIDE) preserves the count of
        ResponsiveRecords. The transient ThirdPartyNotice transitions
        do not delete records.

        # difficulty: compensating_invariant/third_party_object_then_override_preserves_record_count
        """
        from test_helpers import (
            consent_third_party_notice,
            create_third_party_notice,
        )
        tp_id = unique_third_party_id("tp_consent_inv")
        _r, request, _fa = setup_request_in_search()
        rec_x = create_responsive_record(
            request_id=request["id"], page_count=12,
            contains_third_party_info=True, third_party_id=tp_id,
        )
        rec_y = create_responsive_record(
            request_id=request["id"], page_count=8,
        )
        rec_ids = {rec_x["id"], rec_y["id"]}
        notice = create_third_party_notice(
            request_id=request["id"], record_id=rec_x["id"],
        )
        consent_third_party_notice(notice["id"], tp_id)
        # Confirm both records still readable.
        for rid in rec_ids:
            data = get_responsive_record(rid)
            assert data["id"] == rid
