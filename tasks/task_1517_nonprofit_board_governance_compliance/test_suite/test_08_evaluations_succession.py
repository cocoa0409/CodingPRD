"""Executive evaluations (scores, composites, SoD, OCC) and succession plans."""
import pytest

import test_helpers as th
from test_helpers import fixtures as fx

ADMIN = th.TEST_USERS["governance_admin_headers"]


class TestEvaluationLifecycle:
    def test_evaluation_return_and_resubmit_cycle(self, api):
        """PRD §3.7: "The committee may send it back to `DRAFT` for rework, after
        which the provisional composite is recomputed on the next score edit, or
        advance it to ratification."
        PRD §3.7: "The first score edit locks in its recorder as
        `recorded_by_user_id`, and every later edit while the evaluation remains in
        `DRAFT` must come from that same user, else
        `ERR_EVALUATION_RECORDER_MISMATCH`; each accepted edit replaces the sheet,
        recomputes the `provisional_composite`, and increments the evaluation's
        `version` by 1."
        PRD §3.7: "The provisional figure is the committee's working number: the
        unweighted mean of all recorded scores, rounded half-up to 2 decimal
        places."

        Design: Corner/state_machines/evaluation_return_and_resubmit_cycle
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-ER-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        evaluation = fx.setup_evaluation_in_review(np_id, chair,
                                                   th.make_scores(3), 2026)

        returned = th.validate_success(api.return_evaluation(
            evaluation["id"], chair_headers))
        assert returned["status"] == "DRAFT", "the return loop reopens the sheet"

        rescored = fx.patch_scores(evaluation["id"], chair, th.make_scores(4))
        assert rescored["provisional_composite"] == pytest.approx(4.00, abs=0.001), (
            f"unweighted mean of all 4s recomputed on the next edit, got {rescored['provisional_composite']}")

        resubmitted = th.validate_success(api.submit_evaluation_review(
            evaluation["id"], chair_headers))
        assert resubmitted["status"] == "COMMITTEE_REVIEW"

    def test_evaluation_submit_incomplete_rejected(self, api):
        """PRD §3.7: "When the sheet is complete — all five dimensions present, else
        `ERR_EVALUATION_INCOMPLETE` — the `BoardChair` submits it to committee
        review, moving the evaluation to `COMMITTEE_REVIEW`."

        Design: Corner/state_machines/evaluation_submit_incomplete_rejected
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-EI-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        evaluation = fx.create_evaluation(np_id, chair, fiscal_year=2026)
        fx.patch_scores(evaluation["id"], chair, [
            {"dimension": "LEADERSHIP", "score": 4},
            {"dimension": "FUNDRAISING", "score": 4},
            {"dimension": "FINANCIAL", "score": 4},
        ])

        resp = api.submit_evaluation_review(evaluation["id"], chair_headers)
        th.validate_error(resp, th.ApiErrorId.ERR_EVALUATION_INCOMPLETE)

        fx.patch_scores(evaluation["id"], chair, th.make_scores(4))
        submitted = th.validate_success(api.submit_evaluation_review(
            evaluation["id"], chair_headers))
        assert submitted["status"] == "COMMITTEE_REVIEW"


class TestEvaluationSoD:
    def test_evaluation_ratify_by_recorder_rejected(self, api):
        """PRD §3.7: "A `BoardChair` or `Treasurer` ratifies, but never the score
        recorder — the ratifier's `X-User-ID` must differ from
        `recorded_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — and the ratifier
        is recorded as `ratified_by_user_id`."
        PRD §3.7: "At ratification the `final_composite` is computed as the weighted
        sum of the five dimension scores — `LEADERSHIP` weighted 0.30, `FUNDRAISING`
        0.20, `FINANCIAL` 0.20, `PROGRAM` 0.20, and `GOVERNANCE` 0.10 — rounded
        half-up to 2 decimal places, and the `rating` band is `EXCEEDS` when the
        final composite is at least 4.25, `MEETS` when at least 3.00,
        `NEEDS_IMPROVEMENT` when at least 2.00, and `UNSATISFACTORY` below that."

        Design: Corner/state_machines/evaluation_ratify_by_recorder_rejected
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR", "TREASURER"),
                                     ein="EIN-ES-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, treasurer = sc["chair"], sc["treasurer"]
        evaluation = fx.setup_evaluation_in_review(
            np_id, chair, th.make_scores_list(5, 4, 4, 4, 4), 2026)

        resp = api.ratify_evaluation(evaluation["id"],
                                     th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        ratified = th.validate_success(api.ratify_evaluation(
            evaluation["id"], th.make_treasurer_headers(treasurer["id"])))
        assert ratified["status"] == "RATIFIED"
        assert ratified["final_composite"] == pytest.approx(4.30, abs=0.001), (
            f"5*0.30 + 4*0.20*3 + 4*0.10 == 4.30, got {ratified['final_composite']}")
        assert ratified["rating"] == "EXCEEDS", "4.30 >= 4.25 is EXCEEDS"
        assert ratified["ratified_by_user_id"] == treasurer["id"]

    def test_evaluation_second_recorder_rejected(self, api):
        """PRD §3.7: "The first score edit locks in its recorder as
        `recorded_by_user_id`, and every later edit while the evaluation remains in
        `DRAFT` must come from that same user, else
        `ERR_EVALUATION_RECORDER_MISMATCH`; each accepted edit replaces the sheet,
        recomputes the `provisional_composite`, and increments the evaluation's
        `version` by 1."

        Design: Corner/state_machines/evaluation_second_recorder_rejected
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR", "TREASURER"),
                                     ein="EIN-EM2-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, treasurer = sc["chair"], sc["treasurer"]
        evaluation = fx.create_evaluation(np_id, chair, fiscal_year=2026)
        scored = fx.patch_scores(evaluation["id"], chair, th.make_scores(3))

        resp = api.patch_scores(
            evaluation["id"],
            {"expected_evaluation_version": scored["version"],
             "scores": th.make_scores(1)},
            th.make_treasurer_headers(treasurer["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_EVALUATION_RECORDER_MISMATCH)

    def test_evaluation_scores_occ_stale_version_rejected(self, api):
        """PRD §2.6: "`PATCH /boardgov/executive-evaluations/{id}/scores` requires
        `expected_evaluation_version`, carrying the client's last observed `version`
        of the evaluation. A mismatch with the evaluation's current `version` —
        which advances on every legitimate score-sheet edit — is rejected with
        `ERR_STALE_VERSION` (HTTP 412), so a writer never edits against a stale
        baseline."
        PRD §3.7: "The provisional figure is the committee's working number: the
        unweighted mean of all recorded scores, rounded half-up to 2 decimal
        places."

        Design: Corner/cross_cutting_layers/evaluation_scores_occ_stale_version_rejected
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-OC3-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        evaluation = fx.create_evaluation(np_id, chair, fiscal_year=2026)
        v1 = evaluation["version"]

        scored = th.validate_success(api.patch_scores(
            evaluation["id"], {"expected_evaluation_version": v1,
                               "scores": th.make_scores(5)}, chair_headers))
        assert scored["provisional_composite"] == pytest.approx(5.00, abs=0.001)
        assert scored["version"] == v1 + 1

        th.validate_error(api.patch_scores(
            evaluation["id"], {"expected_evaluation_version": v1,
                               "scores": th.make_scores(1)}, chair_headers),
            th.ApiErrorId.ERR_STALE_VERSION, 412)

        after = th.validate_success(api.get_evaluation(evaluation["id"], ADMIN))
        assert after["provisional_composite"] == pytest.approx(5.00, abs=0.001), (
            "the rejected stale write must not partially mutate the sheet")

    def test_evaluation_rating_band_boundaries(self, api):
        """PRD §3.7: "At ratification the `final_composite` is computed as the
        weighted sum of the five dimension scores — `LEADERSHIP` weighted 0.30,
        `FUNDRAISING` 0.20, `FINANCIAL` 0.20, `PROGRAM` 0.20, and `GOVERNANCE` 0.10
        — rounded half-up to 2 decimal places, and the `rating` band is `EXCEEDS`
        when the final composite is at least 4.25, `MEETS` when at least 3.00,
        `NEEDS_IMPROVEMENT` when at least 2.00, and `UNSATISFACTORY` below that."

        Design: Corner/calculations/evaluation_rating_band_boundaries
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR", "TREASURER"),
                                     ein="EIN-RB-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, treasurer = sc["chair"], sc["treasurer"]
        treasurer_headers = th.make_treasurer_headers(treasurer["id"])

        cases = [
            (2026, th.make_scores(3), 3.00, "MEETS"),
            (2027, th.make_scores(2), 2.00, "NEEDS_IMPROVEMENT"),
            (2028, th.make_scores_list(2, 2, 2, 2, 1), 1.90, "UNSATISFACTORY"),
        ]
        for fiscal_year, scores, expected_final, expected_rating in cases:
            evaluation = fx.setup_evaluation_in_review(np_id, chair, scores,
                                                       fiscal_year)
            ratified = th.validate_success(api.ratify_evaluation(
                evaluation["id"], treasurer_headers))
            assert ratified["final_composite"] == pytest.approx(expected_final, abs=0.001), (
                f"FY{fiscal_year}: expected final {expected_final}, got {ratified['final_composite']}")
            assert ratified["rating"] == expected_rating, (
                f"FY{fiscal_year}: {expected_final} must band {expected_rating} (inclusive floor), got {ratified['rating']}")


class TestEvaluationVariantPair:
    """Difficulty: dual_variant_calc / evaluation_composite_unweighted_vs_weighted."""

    def test_provisional_composite_is_unweighted_mean(self, api):
        """PRD §3.7: "The provisional figure is the committee's working number: the
        unweighted mean of all recorded scores, rounded half-up to 2 decimal
        places."
        PRD §3.7: "The two variants genuinely differ on identical inputs: scores of
        5, 5, 5, 1, 1 yield a provisional composite of 3.40 but a final composite of
        3.80."

        Design: Difficulty/dual_variant_calc/evaluation_composite_unweighted_vs_weighted
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR", "TREASURER"),
                                     ein="EIN-EVAL-1")
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        evaluation = fx.create_evaluation(np_id, chair, fiscal_year=2026)
        scored = fx.patch_scores(evaluation["id"], chair,
                                 th.make_scores_list(5, 5, 5, 1, 1))
        assert scored["provisional_composite"] == pytest.approx(3.40, abs=0.001), (
            f"unweighted mean 17/5 == 3.40, got {scored['provisional_composite']}")

    def test_ratified_composite_is_weighted_and_drives_rating(self, api):
        """PRD §3.7: "At ratification the `final_composite` is computed as the
        weighted sum of the five dimension scores — `LEADERSHIP` weighted 0.30,
        `FUNDRAISING` 0.20, `FINANCIAL` 0.20, `PROGRAM` 0.20, and `GOVERNANCE` 0.10
        — rounded half-up to 2 decimal places, and the `rating` band is `EXCEEDS`
        when the final composite is at least 4.25, `MEETS` when at least 3.00,
        `NEEDS_IMPROVEMENT` when at least 2.00, and `UNSATISFACTORY` below that."
        PRD §3.7: "The two variants genuinely differ on identical inputs: scores of
        5, 5, 5, 1, 1 yield a provisional composite of 3.40 but a final composite of
        3.80."

        Design: Difficulty/dual_variant_calc/evaluation_composite_unweighted_vs_weighted
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR", "TREASURER"),
                                     ein="EIN-EVAL-2")
        np_id = sc["nonprofit"]["id"]
        chair, treasurer = sc["chair"], sc["treasurer"]
        evaluation = fx.setup_evaluation_in_review(
            np_id, chair, th.make_scores_list(5, 5, 5, 1, 1), 2026)
        ratified = th.validate_success(api.ratify_evaluation(
            evaluation["id"], th.make_treasurer_headers(treasurer["id"])))
        assert ratified["status"] == "RATIFIED"
        assert ratified["final_composite"] == pytest.approx(3.80, abs=0.001), (
            f"5*0.30 + 5*0.20 + 5*0.20 + 1*0.20 + 1*0.10 == 3.80, got {ratified['final_composite']}")
        assert ratified["rating"] == "MEETS", "3.80 in [3.00, 4.25) is MEETS"
        assert ratified["ratified_by_user_id"] == treasurer["id"], (
            "the ratifier is the treasurer, not the chair who recorded the scores")


class TestEvaluationUniqueness:
    def test_executive_evaluation_duplicate_year_rejected(self, api):
        """PRD §3.7: "Once per fiscal year the board evaluates its executive: a
        `BoardChair` opens an evaluation with `nonprofit_id`, the `fiscal_year`
        under review, and the `executive_name`; a duplicate for the same nonprofit
        and year is rejected with `ERR_DUPLICATE_EVALUATION`."

        Design: Corner/entities/executive_evaluation_duplicate_year_rejected
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-EV-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        fx.create_evaluation(np_id, chair, fiscal_year=2026)

        resp = api.create_evaluation(
            th.create_evaluation_payload(np_id, 2026, executive_name="ED"),
            th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_DUPLICATE_EVALUATION)


class TestSuccessionPlans:
    def test_succession_approve_without_designee_rejected(self, api):
        """PRD §3.7: "Approval is the gated step: the plan must be `DRAFT`, and the
        designee must be present per the target role — for `BOARD_CHAIR` or
        `TREASURER` an `interim_designee_member_id` referencing an `ACTIVE` member
        of the nonprofit, for `EXECUTIVE_DIRECTOR` a non-empty free-text
        `interim_designee_name` since non-board staff may serve as interim — and an
        absent designee is rejected with `ERR_DESIGNEE_REQUIRED` while an
        unresolvable member reference surfaces as `ERR_NOT_FOUND`."

        Design: Corner/entities/succession_approve_without_designee_rejected
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-SP-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        plan = fx.create_succession_plan(np_id, chair, target_role="BOARD_CHAIR",
                                         readiness="READY_NOW")

        resp = api.approve_plan(plan["id"], th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_DESIGNEE_REQUIRED)
        after = th.validate_success(api.get_succession_plan(plan["id"], ADMIN))
        assert after["status"] == "DRAFT"

    def test_succession_second_approval_supersedes_first(self, api):
        """PRD §3.7: "At most one plan per nonprofit and target role may stand
        approved or activated at a time: approval moves the draft to `APPROVED` and
        automatically supersedes any previously `APPROVED` plan for the same
        pairing, moving it to `SUPERSEDED`."
        PRD §3.7: "a `DRAFT` plan may be discarded to `DISCARDED`, and `SUPERSEDED`
        and `DISCARDED` are terminal."

        Design: Corner/state_machines/succession_second_approval_supersedes_first
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-SS-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        plan_a = fx.create_succession_plan(np_id, chair, readiness="READY_NOW",
                                           interim_designee_name="Interim One")
        plan_b = fx.create_succession_plan(np_id, chair, readiness="ONE_YEAR",
                                           interim_designee_name="Interim Two")

        approved_a = fx.approve_plan(plan_a["id"], chair)
        assert approved_a["status"] == "APPROVED"
        approved_b = fx.approve_plan(plan_b["id"], chair)
        assert approved_b["status"] == "APPROVED"

        plan_a_after = th.validate_success(api.get_succession_plan(plan_a["id"], ADMIN))
        assert plan_a_after["status"] == "SUPERSEDED", (
            "approving B superseded the previously APPROVED plan A")

        th.validate_error(api.activate_plan(plan_a["id"], chair_headers),
                          th.ApiErrorId.ERR_INVALID_STATE)

    def test_succession_activate_standdown_cycle(self, api):
        """PRD §3.7: "From `APPROVED` the `BoardChair` may activate the plan in an
        emergency transition to `ACTIVATED`, stand an activated plan back down to
        `APPROVED` — the activate-stand-down loop — or return the plan to `DRAFT`
        for revision; a `DRAFT` plan may be discarded to `DISCARDED`, and
        `SUPERSEDED` and `DISCARDED` are terminal."

        Design: Corner/state_machines/succession_activate_standdown_cycle
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-SD-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        plan = fx.create_succession_plan(np_id, chair, readiness="READY_NOW",
                                         interim_designee_name="Interim")
        fx.approve_plan(plan["id"], chair)

        activated = th.validate_success(api.activate_plan(plan["id"], chair_headers))
        assert activated["status"] == "ACTIVATED"
        stood_down = th.validate_success(api.stand_down_plan(plan["id"], chair_headers))
        assert stood_down["status"] == "APPROVED", (
            "the stand-down loop returns to APPROVED without superseding anything")
