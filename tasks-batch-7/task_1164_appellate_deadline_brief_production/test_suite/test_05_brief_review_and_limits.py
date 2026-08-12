"""Brief drafting/review cycle, dual-variant length limits, segregation of duties."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_brief,
    attorney_headers,
    setup_briefing_case,
    create_brief, submit_brief, approve_brief,
    walk_brief_to_ready,
    PARALEGAL,
)


class TestCyclicReviewLoop:
    def test_brief_survives_two_full_review_cycles_then_ready(self, api):
        """PRD §3.5: "Alternatively the reviewer — again, someone other than the
        author — may return the brief for revision, moving it from `IN_REVIEW`
        back to `DRAFT`; this cycle between `DRAFT` and `IN_REVIEW` may repeat as
        many times as needed."

        Design: Difficulty/non_linear_state_machine/brief_cyclic_review_loop
        """
        ctx = setup_briefing_case(court_overrides={"code": "CYC-CT"})
        author, reviewer = ctx["attorney"], ctx["reviewer"]
        brief = create_brief(ctx, "OPENING")

        for cycle in range(2):
            submitted = validate_success(
                api.submit_review(brief["id"], attorney_headers(author)), 200
            )
            assert submitted["status"] == "IN_REVIEW", f"cycle {cycle}: submit must move to IN_REVIEW"
            returned = validate_success(
                api.return_draft(brief["id"], attorney_headers(reviewer)), 200
            )
            assert returned["status"] == "DRAFT", f"cycle {cycle}: return must move back to DRAFT"

        validate_success(api.submit_review(brief["id"], attorney_headers(author)), 200)
        approved = validate_success(
            api.approve_brief(brief["id"], attorney_headers(reviewer)), 200
        )
        assert approved["status"] == "READY", (
            f"brief must reach READY after repeated DRAFT/IN_REVIEW cycles, got {approved['status']}"
        )

    def test_returned_brief_is_editable_again_in_draft(self, api):
        """PRD §3.5: "While a brief is in `DRAFT` or `IN_REVIEW`, its author may
        update `page_count` and `word_count`, which recomputes `over_limit` and
        increments the brief's `version`; edits in any other state are rejected
        with `ERR_INVALID_STATE`."
        PRD §3.5: "Alternatively the reviewer — again, someone other than the
        author — may return the brief for revision, moving it from `IN_REVIEW`
        back to `DRAFT`; this cycle between `DRAFT` and `IN_REVIEW` may repeat as
        many times as needed."

        Design: Difficulty/non_linear_state_machine/brief_cyclic_review_loop
        """
        ctx = setup_briefing_case(court_overrides={"code": "CYC2"})
        author, reviewer = ctx["attorney"], ctx["reviewer"]
        brief = create_brief(ctx, "OPENING", word_count=1000)
        submit_brief(brief, author)
        returned = validate_success(
            api.return_draft(brief["id"], attorney_headers(reviewer)), 200
        )
        assert returned["status"] == "DRAFT"
        version_after_return = returned["version"]

        edited = validate_success(
            api.update_brief(brief["id"], {"word_count": 2000}, attorney_headers(author)), 200
        )
        assert edited["word_count"] == 2000
        assert edited["version"] == version_after_return + 1, (
            "editing the returned draft must increment the brief's version by exactly 1"
        )
        resubmitted = validate_success(
            api.submit_review(brief["id"], attorney_headers(author)), 200
        )
        assert resubmitted["status"] == "IN_REVIEW"


class TestDualVariantLengthLimit:
    def test_page_limit_variant_marks_same_input_over_limit(self, api):
        """PRD §3.5: "When the court's `uses_word_count` flag is set, the
        applicable limit is `max_words_reply` for a `REPLY` brief and
        `max_words_opening` for every other type, and the measured length is the
        brief's `word_count`; when the flag is unset, the limit is
        `max_pages_reply` for a `REPLY` and `max_pages_opening` otherwise,
        measured against `page_count`."
        PRD §3.5: "Because the two variants measure different quantities against
        different limits, the same draft can be over-limit under one variant and
        compliant under the other; the court's flag decides which reading
        governs."

        Design: Difficulty/dual_variant_calc/brief_limit_word_vs_page_variant_same_input
        """
        ctx = setup_briefing_case(court_overrides={
            "code": "PAGE-CT", "jurisdiction_type": "STATE",
            "uses_word_count": False,
            "max_words_opening": 0, "max_pages_opening": 40,
            "max_words_reply": 0, "max_pages_reply": 20,
        })
        brief = create_brief(ctx, "OPENING", page_count=50, word_count=15000)
        assert_brief(brief)
        assert brief["over_limit"] is True, (
            "page court (max 40 pages) must flag a 50-page brief over-limit"
        )

    def test_word_limit_variant_marks_same_input_compliant(self, api):
        """PRD §3.5: "When the court's `uses_word_count` flag is set, the
        applicable limit is `max_words_reply` for a `REPLY` brief and
        `max_words_opening` for every other type, and the measured length is the
        brief's `word_count`; when the flag is unset, the limit is
        `max_pages_reply` for a `REPLY` and `max_pages_opening` otherwise,
        measured against `page_count`."
        PRD §3.5: "Because the two variants measure different quantities against
        different limits, the same draft can be over-limit under one variant and
        compliant under the other; the court's flag decides which reading
        governs."

        Design: Difficulty/dual_variant_calc/brief_limit_word_vs_page_variant_same_input
        """
        ctx = setup_briefing_case(court_overrides={
            "code": "WORD-CT", "jurisdiction_type": "STATE",
            "uses_word_count": True,
            "max_words_opening": 16000, "max_pages_opening": 0,
            "max_words_reply": 8000, "max_pages_reply": 0,
        })
        brief = create_brief(ctx, "OPENING", page_count=50, word_count=15000)
        assert_brief(brief)
        assert brief["over_limit"] is False, (
            "word court (max 16000 words) must not flag a 15000-word brief"
        )


class TestBoundaryPrecision:
    def test_word_count_exactly_at_limit_is_compliant(self, api):
        """PRD §3.5: "The brief's `over_limit` flag is set only when the measured
        length strictly exceeds the applicable limit — a brief sitting exactly
        at the limit is compliant."
        PRD §2.7: "Brief-length compliance uses strict integer comparison: a
        brief is over its limit only when its measured length strictly exceeds
        the limit, so a brief sitting exactly at the limit is compliant."

        Design: Difficulty/boundary_precision_check/brief_word_count_at_exact_limit
        """
        ctx = setup_briefing_case(court_overrides={
            "code": "BP1", "uses_word_count": True, "max_words_opening": 14000,
        })
        brief = create_brief(ctx, "OPENING", page_count=5, word_count=14000)
        assert brief["over_limit"] is False, (
            "word_count exactly equal to the limit must be compliant (strict >)"
        )

    def test_word_count_one_above_limit_is_over_limit(self, api):
        """PRD §3.5: "The brief's `over_limit` flag is set only when the measured
        length strictly exceeds the applicable limit — a brief sitting exactly
        at the limit is compliant."
        PRD §2.7: "Brief-length compliance uses strict integer comparison: a
        brief is over its limit only when its measured length strictly exceeds
        the limit, so a brief sitting exactly at the limit is compliant."

        Design: Difficulty/boundary_precision_check/brief_word_count_at_exact_limit
        """
        ctx = setup_briefing_case(court_overrides={
            "code": "BP1B", "uses_word_count": True, "max_words_opening": 14000,
        })
        brief = create_brief(ctx, "RESPONSE", page_count=5, word_count=14001)
        assert brief["over_limit"] is True, (
            "word_count one above the limit must cross the threshold"
        )


class TestSubmitReviewStateGate:
    def test_submit_review_from_in_review_returns_invalid_state(self, api):
        """PRD §2.9: "5. **State validity** — the target resource is in a state
        from which the requested transition exists (for example, a brief may be
        submitted for review only while `DRAFT`); otherwise `ERR_INVALID_STATE`
        (HTTP 409). Applies to every state-transition endpoint."

        Design: Corner/state_machines/brief_submit_review_from_non_draft_returns_invalid_state
        """
        ctx = setup_briefing_case(court_overrides={"code": "SM1"})
        brief = create_brief(ctx, "OPENING")
        submit_brief(brief, ctx["attorney"])

        res = api.submit_review(brief["id"], attorney_headers(ctx["attorney"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        after = validate_success(
            api.get_brief(brief["id"], attorney_headers(ctx["attorney"])), 200
        )
        assert after["status"] == "IN_REVIEW", "a rejected re-submit must leave the brief IN_REVIEW"


class TestSegregationOfDuties:
    def test_author_cannot_approve_own_brief(self, api):
        """PRD §3.5: "Approval must come from a different attorney: if the
        approving request's `X-User-ID` equals `author_attorney_id`, the attempt
        fails with `ERR_SELF_APPROVAL_FORBIDDEN`."

        Design: Corner/errors/err_self_approval_forbidden_on_brief_approve
        """
        ctx = setup_briefing_case(court_overrides={"code": "E3"})
        brief = create_brief(ctx, "OPENING")
        submit_brief(brief, ctx["attorney"])

        res = api.approve_brief(brief["id"], attorney_headers(ctx["attorney"]))
        validate_error(res, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN.value, expected_status=403)

    def test_state_gate_fires_before_segregation_when_author_approves_draft(self, api):
        """PRD §2.9: "Requests are validated in a fixed priority order, and when
        several rules could fail on the same request the earliest rule's error is
        the one returned."
        PRD §2.9: "5. **State validity** — the target resource is in a state from
        which the requested transition exists (for example, a brief may be
        submitted for review only while `DRAFT`); otherwise `ERR_INVALID_STATE`
        (HTTP 409). Applies to every state-transition endpoint."
        PRD §2.9: "6. **Segregation of duties** — on brief approval and on
        return-to-draft, the reviewing attorney must differ from the drafting
        attorney; otherwise `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_self_approval
        """
        ctx = setup_briefing_case(court_overrides={"code": "PV1"})
        brief = create_brief(ctx, "OPENING")  # stays DRAFT; never submitted

        res = api.approve_brief(brief["id"], attorney_headers(ctx["attorney"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        err = res.json()["data"]["error_id"]
        assert err != ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN.value, (
            "priority-5 state check must surface before the priority-6 segregation check"
        )

    def test_state_gate_fires_before_segregation_when_reviewer_approves_draft(self, api):
        """PRD §2.9: "Requests are validated in a fixed priority order, and when
        several rules could fail on the same request the earliest rule's error is
        the one returned."
        PRD §2.9: "5. **State validity** — the target resource is in a state from
        which the requested transition exists (for example, a brief may be
        submitted for review only while `DRAFT`); otherwise `ERR_INVALID_STATE`
        (HTTP 409). Applies to every state-transition endpoint."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_self_approval
        """
        ctx = setup_briefing_case(court_overrides={"code": "PV1R"})
        brief = create_brief(ctx, "OPENING")  # stays DRAFT

        res = api.approve_brief(brief["id"], attorney_headers(ctx["reviewer"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


class TestRoleGatesOnReview:
    def test_paralegal_cannot_approve_brief(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted to
        invoke the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "`ParalegalStaff` — support staff who manage transcript
        orders, citations, and filings but can never approve or e-file a brief."

        Design: Corner/validations/paralegal_cannot_approve_brief
        """
        ctx = setup_briefing_case(court_overrides={"code": "V1"})
        brief = create_brief(ctx, "OPENING")
        submit_brief(brief, ctx["attorney"])

        res = api.approve_brief(brief["id"], PARALEGAL)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)
