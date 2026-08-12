"""Inquiries: cyclic review queue, challenged-score branches, filing window
boundaries, resolution consistency, pass-discipline cascades, and the
provisional-vs-final dual computation."""
from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    fmt_ts,
    get_success_data,
    make_coach_headers,
    make_judge_panel_chief_headers,
    parse_ts,
    resolve_inquiry,
    set_clock,
    setup_filed_inquiry,
    setup_inquiry_under_review,
    setup_published_score,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["meet_director_headers"]
REFEREE = TEST_USERS["meet_referee_headers"]


class TestProvisionalVsFinalDualVariant:
    def test_publish_variant_computes_provisional_from_raw_inputs(self, api):
        """PRD §3.6: "Publication stamps `published_at`, computes the score's
        `provisional_total` as the difficulty score plus the execution score minus the
        neutral deduction — rounded half-up to three decimal places and floored at 0.000 —
        and pushes the result to the live scoring display."

        Design: Difficulty/dual_variant_calc/score_provisional_vs_final_after_upheld_inquiry
        """
        ctx = setup_published_score(difficulty=5.2, execution=8.85, neutral_deduction=0.1)
        score = ctx["score"]
        assert score["score_state"] == "PUBLISHED"
        # Publish-time variant: 5.2 + 8.85 - 0.1 = 13.950 from the raw inputs.
        assert score["provisional_total"] == pytest.approx(13.95, abs=0.001)

    def test_upheld_inquiry_variant_recomputes_total_with_deltas(self, api, meet_director_headers):
        """PRD §3.6: "An `UPHELD` resolution folds the deltas into the score: the adjusted
        difficulty (the original `difficulty_score` plus `d_score_delta`), the adjusted
        execution (`execution_score` plus `e_score_delta`), and the adjusted deduction
        (`neutral_deduction` plus `deduction_delta`) are summed — difficulty plus execution
        minus deduction — and the provisional total is recomputed from those adjusted
        components with rounding applied after the summation, half-up to three decimals and
        floored at zero; the score's `final_total` is then this recomputed provisional
        total."

        Design: Difficulty/dual_variant_calc/score_provisional_vs_final_after_upheld_inquiry
        """
        ctx = setup_inquiry_under_review(difficulty=5.2, execution=8.85, neutral_deduction=0.1)
        publish_variant = ctx["score"]["provisional_total"]
        assert publish_variant == pytest.approx(13.95, abs=0.001)
        res = resolve_inquiry(ctx["inquiry"]["id"], "D_RAISED", d_score_delta=0.3,
                              e_score_delta=0.15, deduction_delta=-0.1,
                              resolution_reason="missed DV")
        inquiry = validate_success(res)
        assert inquiry["inquiry_state"] == "UPHELD"
        score = get_success_data(api.get_score(ctx["score"]["id"], meet_director_headers))
        assert score["score_state"] == "INQUIRY_RESOLVED"
        # Post-inquiry variant: (5.2+0.3) + (8.85+0.15) - (0.1-0.1) = 14.500.
        assert score["provisional_total"] == pytest.approx(14.5, abs=0.001)
        assert score["final_total"] == pytest.approx(14.5, abs=0.001)
        assert score["provisional_total"] != pytest.approx(publish_variant, abs=0.001), (
            "the two computation variants must diverge by exactly the applied deltas")


class TestInquiryReviewLoop:
    def test_return_to_queue_loops_back_to_filed(self, api, meet_referee_headers):
        """PRD §3.6: "At the inquiry desk the `MeetReferee` begins review — `FILED` →
        `UNDER_REVIEW` — and may return the inquiry to the queue — `UNDER_REVIEW` → `FILED`
        — as long as no resolution has been written yet, a deliberate loop that lets the
        referee defer without deciding."
        PRD §2.6: "`version` (integer): a system-managed integer that increments by one with
        every modification to the resource, including cascading side effects."

        Design: Difficulty/non_linear_state_machine/inquiry_cyclic_return_to_queue
        """
        ctx = setup_filed_inquiry()
        inquiry = ctx["inquiry"]
        created_version = inquiry["version"]
        for _ in range(2):
            under_review = validate_success(api.begin_review(inquiry["id"], meet_referee_headers))
            assert under_review["inquiry_state"] == "UNDER_REVIEW"
            back = validate_success(api.return_to_queue(inquiry["id"], meet_referee_headers))
            assert back["inquiry_state"] == "FILED"
        final = get_success_data(api.get_inquiry(inquiry["id"], meet_referee_headers))
        assert final["inquiry_state"] == "FILED"
        assert final["version"] == created_version + 4, (
            f"two begin-review/return-to-queue loops must add exactly 4 to the version: "
            f"{created_version} -> {final['version']}")

    def test_inquiry_still_resolvable_after_deferral_loop(self, api, meet_director_headers):
        """PRD §3.6: "At the inquiry desk the `MeetReferee` begins review — `FILED` →
        `UNDER_REVIEW` — and may return the inquiry to the queue — `UNDER_REVIEW` → `FILED`
        — as long as no resolution has been written yet, a deliberate loop that lets the
        referee defer without deciding."
        PRD §3.6: "An `UPHELD` resolution folds the deltas into the score ..."

        Design: Difficulty/non_linear_state_machine/inquiry_cyclic_return_to_queue
        """
        ctx = setup_filed_inquiry()
        inquiry = ctx["inquiry"]
        validate_success(api.begin_review(inquiry["id"], REFEREE))
        validate_success(api.return_to_queue(inquiry["id"], REFEREE))
        validate_success(api.begin_review(inquiry["id"], REFEREE))
        resolved = validate_success(
            resolve_inquiry(inquiry["id"], "D_RAISED", d_score_delta=0.2))
        assert resolved["inquiry_state"] == "UPHELD", (
            "a deferred inquiry must remain resolvable after the review loop")
        score = get_success_data(api.get_score(ctx["score"]["id"], meet_director_headers))
        assert score["score_state"] == "INQUIRY_RESOLVED"


class TestPublicationInquiryBranches:
    def test_withdrawn_inquiry_returns_score_to_published_unchanged(
            self, api, meet_director_headers):
        """PRD §3.6: "The filing coach — and only that coach — may withdraw a still-`FILED`
        inquiry, moving it `FILED` → `WITHDRAWN`."
        PRD §3.6: "Both exits record `resolved_at` on the inquiry and return the score from
        `UNDER_INQUIRY` to `PUBLISHED`, its `final_total` still equal to `provisional_total`,
        where the ordinary expiry path to `FINAL` resumes."

        Design: Difficulty/non_linear_state_machine/score_parallel_publication_and_inquiry_dimensions
        """
        ctx = setup_filed_inquiry(difficulty=5.0, execution=8.0, neutral_deduction=0.0)
        assert ctx["score"]["provisional_total"] == pytest.approx(13.0, abs=0.001)
        withdrawn = validate_success(api.withdraw_inquiry(
            ctx["inquiry"]["id"], make_coach_headers(ctx["coach"]["id"])))
        assert withdrawn["inquiry_state"] == "WITHDRAWN"
        assert withdrawn.get("resolved_at"), "withdrawal must record resolved_at"
        score = get_success_data(api.get_score(ctx["score"]["id"], meet_director_headers))
        assert score["score_state"] == "PUBLISHED", (
            "withdrawal must return the score to its pre-inquiry state")
        assert score["final_total"] == pytest.approx(13.0, abs=0.001)
        assert score["provisional_total"] == pytest.approx(13.0, abs=0.001)

    def test_upheld_inquiry_keeps_applied_deltas(self, api, meet_director_headers):
        """PRD §3.6: "An `UPHELD` resolution folds the deltas into the score: the adjusted
        difficulty (the original `difficulty_score` plus `d_score_delta`), the adjusted
        execution (`execution_score` plus `e_score_delta`), and the adjusted deduction
        (`neutral_deduction` plus `deduction_delta`) are summed — difficulty plus execution
        minus deduction — and the provisional total is recomputed from those adjusted
        components with rounding applied after the summation, half-up to three decimals and
        floored at zero; the score's `final_total` is then this recomputed provisional
        total."

        Design: Difficulty/non_linear_state_machine/score_parallel_publication_and_inquiry_dimensions
        """
        ctx = setup_inquiry_under_review(difficulty=5.0, execution=8.0, neutral_deduction=0.0)
        resolved = validate_success(
            resolve_inquiry(ctx["inquiry"]["id"], "D_RAISED", d_score_delta=0.2))
        assert resolved["inquiry_state"] == "UPHELD"
        score = get_success_data(api.get_score(ctx["score"]["id"], meet_director_headers))
        assert score["score_state"] == "INQUIRY_RESOLVED"
        # Same initial inputs as the withdrawn branch (13.000), but the upheld
        # branch keeps the delta: (5.0+0.2) + 8.0 - 0.0 = 13.200.
        assert score["provisional_total"] == pytest.approx(13.2, abs=0.001)
        assert score["final_total"] == pytest.approx(13.2, abs=0.001)


class TestInquiryWindowBoundary:
    def test_filing_at_exact_boundary_allowed(self, api, meet_director_headers):
        """PRD §3.6: "Filing is permitted only while the score is `PUBLISHED`, only while
        the logical clock has not passed `published_at` plus the meet's
        `inquiry_window_minutes` — filing at exactly that boundary instant is allowed,
        filing after it is rejected with `ERR_INQUIRY_WINDOW_EXPIRED` (HTTP 422) ..."

        Design: Difficulty/boundary_precision_check/inquiry_window_exactly_at_deadline
        """
        ctx = setup_published_score()
        published_at = parse_ts(ctx["score"]["published_at"])
        boundary = published_at + timedelta(minutes=ctx["meet"]["inquiry_window_minutes"])
        set_clock(fmt_ts(boundary))
        inquiry = validate_success(api.file_inquiry(
            ctx["score"]["id"], {"filed_by_coach_id": ctx["coach"]["id"]},
            make_coach_headers(ctx["coach"]["id"])), 201)
        assert inquiry["inquiry_state"] == "FILED"
        score = get_success_data(api.get_score(ctx["score"]["id"], meet_director_headers))
        assert score["score_state"] == "UNDER_INQUIRY"

    def test_filing_after_boundary_rejected(self, api):
        """PRD §3.6: "Filing is permitted only while the score is `PUBLISHED`, only while
        the logical clock has not passed `published_at` plus the meet's
        `inquiry_window_minutes` — filing at exactly that boundary instant is allowed,
        filing after it is rejected with `ERR_INQUIRY_WINDOW_EXPIRED` (HTTP 422) ..."
        (One second past the boundary the score may already have finalized itself per the
        §3.6 quiet path, so the rejection surfaces either as the named window error or as
        the state gate.)

        Design: Difficulty/boundary_precision_check/inquiry_window_exactly_at_deadline
        """
        ctx = setup_published_score()
        published_at = parse_ts(ctx["score"]["published_at"])
        past = published_at + timedelta(minutes=ctx["meet"]["inquiry_window_minutes"],
                                        seconds=1)
        set_clock(fmt_ts(past))
        res = api.file_inquiry(ctx["score"]["id"],
                               {"filed_by_coach_id": ctx["coach"]["id"]},
                               make_coach_headers(ctx["coach"]["id"]))
        validate_error_is_one_of(
            res, [ApiErrorId.ERR_INQUIRY_WINDOW_EXPIRED, ApiErrorId.ERR_INVALID_STATE])


class TestPassDisciplineCascade:
    def test_suspend_expires_filed_inquiry_and_restores_score(self, api, meet_director_headers):
        """PRD §3.3: "Suspension strips the coach's standing at the inquiry desk: every
        inquiry that coach filed that is still `FILED` is cascade-transitioned to
        `EXPIRED`."
        PRD §3.6: "Both exits record `resolved_at` on the inquiry and return the score from
        `UNDER_INQUIRY` to `PUBLISHED`, its `final_total` still equal to `provisional_total`,
        where the ordinary expiry path to `FINAL` resumes."

        Design: Difficulty/transitive_cascade/pass_suspend_cascade_to_inquiry_expiry_to_score_state
        """
        ctx = setup_filed_inquiry(difficulty=5.0, execution=8.0, neutral_deduction=0.0)
        suspended = validate_success(api.suspend_pass(
            ctx["coach_pass"]["id"], {"suspension_reason": "CONDUCT"}, meet_director_headers))
        assert suspended["pass_state"] == "FLOOR_ACCESS_SUSPENDED"
        inquiry = get_success_data(api.get_inquiry(ctx["inquiry"]["id"], meet_director_headers))
        assert inquiry["inquiry_state"] == "EXPIRED", (
            f"a FILED inquiry must be cascade-expired when the filing coach's pass is "
            f"suspended, got {inquiry['inquiry_state']}")
        score = get_success_data(api.get_score(ctx["score"]["id"], meet_director_headers))
        assert score["score_state"] == "PUBLISHED"
        assert score["final_total"] == pytest.approx(score["provisional_total"], abs=0.0001)

    def test_revoke_expires_filed_inquiry_the_same_way(self, api, meet_director_headers):
        """PRD §3.3: "Revoking a pass — permitted from `ISSUED`, `FLOOR_ACCESS_GRANTED`, or
        `FLOOR_ACCESS_SUSPENDED` — sends it to the terminal `REVOKED` state and expires the
        coach's still-`FILED` inquiries in exactly the same way."

        Design: Difficulty/transitive_cascade/pass_suspend_cascade_to_inquiry_expiry_to_score_state
        """
        ctx = setup_filed_inquiry(difficulty=5.0, execution=8.0, neutral_deduction=0.0)
        revoked = validate_success(api.revoke_pass(ctx["coach_pass"]["id"], meet_director_headers))
        assert revoked["pass_state"] == "REVOKED"
        inquiry = get_success_data(api.get_inquiry(ctx["inquiry"]["id"], meet_director_headers))
        assert inquiry["inquiry_state"] == "EXPIRED"
        score = get_success_data(api.get_score(ctx["score"]["id"], meet_director_headers))
        assert score["score_state"] == "PUBLISHED"


class TestDeductionNeutralityInvariant:
    def test_compensating_deltas_leave_total_unchanged(self, api, meet_director_headers):
        """PRD §3.6: "An `UPHELD` resolution folds the deltas into the score: the adjusted
        difficulty (the original `difficulty_score` plus `d_score_delta`), the adjusted
        execution (`execution_score` plus `e_score_delta`), and the adjusted deduction
        (`neutral_deduction` plus `deduction_delta`) are summed — difficulty plus execution
        minus deduction — and the provisional total is recomputed from those adjusted
        components with rounding applied after the summation, half-up to three decimals and
        floored at zero; the score's `final_total` is then this recomputed provisional
        total."

        Design: Difficulty/compensating_invariant/inquiry_uphold_conserves_deduction_neutrality_invariant
        """
        ctx = setup_inquiry_under_review(difficulty=5.2, execution=8.85, neutral_deduction=0.1)
        assert ctx["score"]["provisional_total"] == pytest.approx(13.95, abs=0.001)
        # Compensating deltas: +0.3 to difficulty, -0.3 from execution, deduction
        # untouched — the accounting identity D + E - ND is conserved.
        resolved = validate_success(resolve_inquiry(
            ctx["inquiry"]["id"], "D_RAISED", d_score_delta=0.3, e_score_delta=-0.3,
            deduction_delta=0.0))
        assert resolved["inquiry_state"] == "UPHELD"
        score = get_success_data(api.get_score(ctx["score"]["id"], meet_director_headers))
        assert score["provisional_total"] == pytest.approx(13.95, abs=0.001), (
            f"compensating deltas (+0.3 D, -0.3 E, 0 ND) must conserve the total, got "
            f"{score['provisional_total']}")

    def test_finalize_after_upheld_pins_recomputed_total(self, api, meet_director_headers):
        """PRD §3.6: "Either way the inquiry records `resolved_at` and the score moves
        `UNDER_INQUIRY` → `INQUIRY_RESOLVED`, from which the referee finalizes it —
        `INQUIRY_RESOLVED` → `FINAL` — provided the linked inquiry sits in `UPHELD` or
        `DENIED`; finalization stamps `finalized_at` and prompts the parent rotation's
        re-evaluation."

        Design: Difficulty/compensating_invariant/inquiry_uphold_conserves_deduction_neutrality_invariant
        """
        ctx = setup_inquiry_under_review(difficulty=5.2, execution=8.85, neutral_deduction=0.1)
        validate_success(resolve_inquiry(
            ctx["inquiry"]["id"], "D_RAISED", d_score_delta=0.3, e_score_delta=-0.3,
            deduction_delta=0.0))
        finalized = validate_success(api.finalize_score(ctx["score"]["id"], REFEREE))
        assert finalized["score_state"] == "FINAL"
        assert finalized.get("finalized_at"), "finalization must stamp finalized_at"
        assert finalized["final_total"] == pytest.approx(13.95, abs=0.001)
        assert finalized["provisional_total"] == pytest.approx(13.95, abs=0.001)


class TestResolutionRules:
    def test_inconsistent_resolution_rejected(self, api):
        """PRD §3.6: "Consistency is enforced before ranges: an inquiry may only resolve
        `UPHELD` when at least one of the three deltas is non-zero, and may only resolve
        `DENIED` when all three deltas are zero — an inconsistent combination is rejected
        with `ERR_INQUIRY_RESOLUTION_INCONSISTENT`."

        Design: Corner/validations/inquiry_resolution_consistency_upheld_requires_delta
        """
        ctx = setup_inquiry_under_review()
        # A change-claiming resolution with all-zero deltas is inconsistent.
        res = resolve_inquiry(ctx["inquiry"]["id"], "D_RAISED",
                              d_score_delta=0.0, e_score_delta=0.0, deduction_delta=0.0)
        validate_error(res, ApiErrorId.ERR_INQUIRY_RESOLUTION_INCONSISTENT)
        # A no-change resolution carrying a non-zero delta is equally inconsistent.
        res2 = resolve_inquiry(ctx["inquiry"]["id"], "NO_CHANGE", d_score_delta=0.1)
        validate_error(res2, ApiErrorId.ERR_INQUIRY_RESOLUTION_INCONSISTENT)

    def test_resolve_from_filed_rejected(self, api):
        """PRD §3.6: "At the inquiry desk the `MeetReferee` begins review — `FILED` →
        `UNDER_REVIEW` — ..." and resolution is defined as the `UNDER_REVIEW` →
        `UPHELD`/`DENIED` step: "Resolution is the OCC-guarded write of §2.8: the request
        must carry `expected_inquiry_version` matching the inquiry's current `version`, plus
        a `resolution` of `D_RAISED`, `D_UNCHANGED`, `E_ADJUSTED`, `DEDUCTION_REMOVED`, or
        `NO_CHANGE` ..."
        PRD §2.9: "then the entity-specific state precondition of the requested transition
        (`ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/inquiry_invalid_from_published_direct_resolve
        """
        ctx = setup_filed_inquiry()
        assert ctx["inquiry"]["inquiry_state"] == "FILED"
        res = resolve_inquiry(ctx["inquiry"]["id"], "NO_CHANGE",
                              d_score_delta=0.0, e_score_delta=0.0, deduction_delta=0.0)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        inquiry = get_success_data(api.get_inquiry(ctx["inquiry"]["id"], REFEREE))
        assert inquiry["inquiry_state"] == "FILED"

    def test_panel_chief_cannot_resolve_inquiry(self, api):
        """PRD §2.1: "Duties are deliberately segregated: a `JudgePanelChief` publishes
        scores but can never resolve inquiries on them; inquiry resolution belongs to the
        `MeetReferee` alone."
        PRD §2.1: "Once authenticated, the acting role must be permitted to invoke the
        target endpoint; otherwise the request is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/segregation_of_duties_panel_chief_cannot_resolve_inquiry
        """
        ctx = setup_inquiry_under_review()
        inquiry = get_success_data(api.get_inquiry(ctx["inquiry"]["id"], REFEREE))
        payload = {"expected_inquiry_version": inquiry["version"], "resolution": "NO_CHANGE"}
        res = api.resolve_inquiry(
            inquiry["id"], payload,
            make_judge_panel_chief_headers(ctx["chiefs"]["VAULT"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_inquiry(inquiry["id"], REFEREE))
        assert after["inquiry_state"] == "UNDER_REVIEW"
