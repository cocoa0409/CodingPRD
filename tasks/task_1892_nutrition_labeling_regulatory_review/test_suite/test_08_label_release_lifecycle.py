"""Label version lifecycle: the parallel review/release state dimensions,
review rounds, the release gate gauntlet, draft withdrawal on new drafts,
and the compensating release/withdraw invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_label,
    create_claim,
    create_label_draft,
    get_label_version,
    get_product,
    make_regulatory_reviewer_headers,
    reject_label,
    release_label,
    review_lab_analysis,
    setup_cookie_workspace,
    setup_lab_claim_workspace,
    setup_released_wafer_label,
    setup_wafer_workspace,
    submit_lab_analysis,
    submit_label,
    validate_error,
    validate_paginated,
    withdraw_label,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["label_analyst_headers"]
REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def _released_ids(product_id):
    data, _meta = validate_paginated(api_client.list_label_versions(product_id, ADMIN))
    return {lv["id"] for lv in data if lv["release_status"] == "RELEASED"}


class TestReviewStateGuards:
    def test_approve_from_draft_returns_not_in_review(self, api):
        """PRD §3.6: "Approval by a `RegulatoryReviewer` requires the label to
        be `IN_REVIEW` (`ERR_LABEL_NOT_IN_REVIEW` otherwise), requires the
        approver's `X-User-ID` to differ from `prepared_by` per the
        segregation-of-duties rule (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`),
        and requires `content_status` to be `READY`
        (`ERR_CONTENT_REVISION_REQUIRED`)."

        Design: Corner/state_machines/sm_approve_from_draft_returns_not_in_review
        """
        ws = setup_wafer_workspace()
        assert ws["label"]["review_status"] == "DRAFT"
        resp = api.approve_label(ws["label"]["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_LABEL_NOT_IN_REVIEW,
                       expected_status=409)

    def test_withdraw_from_draft_returns_invalid_state(self, api):
        """PRD §3.6: "Withdrawal is the compensating mirror: a
        `QualityManager` withdraws a label that is `RELEASED` (any other
        release status is rejected with `ERR_INVALID_STATE_TRANSITION`),
        optionally supplying a `reason`; the label moves to `WITHDRAWN`, the
        label whose `superseded_by_id` points at the withdrawn one is restored
        to `RELEASED`, and again both the product's and the label's `version`
        increment."

        Design: Corner/state_machines/sm_withdraw_from_draft_returns_invalid_state
        """
        ws = setup_wafer_workspace()
        assert ws["label"]["release_status"] == "NOT_RELEASED"
        resp = api.withdraw_label(ws["label"]["id"],
                                  ws["quality_manager_headers"],
                                  reason="too early")
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION,
                       expected_status=409)

    def test_label_draft_withdrawn_on_new_draft(self, api):
        """PRD §3.6: "Because only one draft per product and market may be in
        flight, creating the draft withdraws any existing `DRAFT` label
        version for the same product and market, moving its `review_status`
        to `WITHDRAWN`."
        PRD §3.6: "The new draft initializes with `review_status` `DRAFT`,
        `release_status` `NOT_RELEASED`, `review_round` 0, and `prepared_by`
        set to the creating analyst's `X-User-ID`; the product's `version`
        increments as part of the same write."

        Design: Corner/state_machines/sm_label_draft_withdrawn_on_new_draft
        """
        ws = setup_wafer_workspace()
        product_before = get_product(ws["product"]["id"])

        lv2 = create_label_draft(
            ws["product"]["id"], ws["racc"]["id"],
            declared_format="SIMPLIFIED",
            statement_recipe_id=ws["recipe"]["id"])

        assert get_label_version(ws["label"]["id"])["review_status"] == (
            "WITHDRAWN"
        ), "the system supersedes the older DRAFT"
        assert lv2["review_status"] == "DRAFT"
        product_after = get_product(ws["product"]["id"])
        assert product_after["version"] == product_before["version"] + 1, (
            "each label-version create advances the product's version by one"
        )


class TestReleaseGates:
    def test_format_check_failed_on_release(self, api):
        """PRD §3.6: "Release is a `QualityManager` act with a gauntlet of
        gates, evaluated in the fixed order of §2.8: the label must be
        `APPROVED` with `release_status` `NOT_RELEASED`
        (`ERR_LABEL_NOT_APPROVED`), `content_status` must be `READY`
        (`ERR_CONTENT_REVISION_REQUIRED`), every claim on the label must be
        `ELIGIBLE` or `NOT_REQUIRED` — a claim still `PENDING`, `SUSPENDED`,
        or `INELIGIBLE` blocks release with `ERR_CLAIMS_NOT_RESOLVED` — and
        the most recently created format check must be `PASS`
        (`ERR_FORMAT_CHECK_FAILED`)."
        PRD §3.6: "Format failures never touch `content_status`; they gate
        the release step instead, and a label may accumulate several format
        checks across review rounds, each retrievable through the label's
        format-check listing."

        Design: Corner/errors/err_format_check_failed_on_release
        """
        # LINEAR is not allowed on a 30 sq in package, so the auto-created
        # format check FAILs while content stays READY.
        ws = setup_wafer_workspace(
            label_overrides={"declared_format": "LINEAR"}, submit=True)
        approve_label(ws["label"]["id"])

        resp = api.release_label(
            ws["label"]["id"],
            {"expected_product_version":
                 get_product(ws["product"]["id"])["version"]},
            ws["quality_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_FORMAT_CHECK_FAILED,
                       expected_status=409)
        assert get_label_version(ws["label"]["id"])["release_status"] == (
            "NOT_RELEASED"
        )

    def test_content_revision_required_on_approve(self, api):
        """PRD §3.6: "Approval by a `RegulatoryReviewer` requires the label to
        be `IN_REVIEW` (`ERR_LABEL_NOT_IN_REVIEW` otherwise), requires the
        approver's `X-User-ID` to differ from `prepared_by` per the
        segregation-of-duties rule (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`),
        and requires `content_status` to be `READY`
        (`ERR_CONTENT_REVISION_REQUIRED`)."
        PRD §3.7: "Thereafter its health tracks its basis panel: when the
        panel goes `STALE` through either cascade of §3.2 and §3.3, an
        `ELIGIBLE` claim is suspended, and the owning label's `content_status`
        flips to `NEEDS_REVISION`."

        Design: Corner/errors/err_content_revision_required_on_approve
        """
        ws = setup_lab_claim_workspace()
        lab2 = submit_lab_analysis(
            ws["recipe"]["id"], ws["client"]["id"], lab_report_ref="LR-101",
            kcal_per_100g=351.0, fat_g_per_100g=1.5, sodium_mg_per_100g=3.6,
            carb_g_per_100g=80.1, sugar_g_per_100g=24.1)
        review_lab_analysis(lab2["id"], outcome="VALIDATED")
        assert get_label_version(ws["label"]["id"])["content_status"] == (
            "NEEDS_REVISION"
        )

        resp = api.approve_label(ws["label"]["id"],
                                 make_regulatory_reviewer_headers("reviewer-2"))
        validate_error(resp, ApiErrorId.ERR_CONTENT_REVISION_REQUIRED,
                       expected_status=409)
        assert get_label_version(ws["label"]["id"])["review_status"] == "IN_REVIEW"

    def test_label_not_approved_on_release(self, api):
        """PRD §3.6: "Release is a `QualityManager` act with a gauntlet of
        gates, evaluated in the fixed order of §2.8: the label must be
        `APPROVED` with `release_status` `NOT_RELEASED`
        (`ERR_LABEL_NOT_APPROVED`), `content_status` must be `READY`
        (`ERR_CONTENT_REVISION_REQUIRED`), every claim on the label must be
        `ELIGIBLE` or `NOT_REQUIRED` — a claim still `PENDING`, `SUSPENDED`,
        or `INELIGIBLE` blocks release with `ERR_CLAIMS_NOT_RESOLVED` — and
        the most recently created format check must be `PASS`
        (`ERR_FORMAT_CHECK_FAILED`)."

        Design: Corner/errors/err_label_not_approved_on_release
        """
        ws = setup_wafer_workspace(submit=True)
        assert ws["label"]["review_status"] == "IN_REVIEW"
        resp = api.release_label(
            ws["label"]["id"],
            {"expected_product_version":
                 get_product(ws["product"]["id"])["version"]},
            ws["quality_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_LABEL_NOT_APPROVED,
                       expected_status=409)


class TestParallelDimensionsAndRejectCycle:
    def test_reject_cycle_accumulates_review_round(self, api):
        """PRD §3.6: "On success the submission pins `panel_snapshot_id` to
        the most recently created `CURRENT` panel of the recipe with the
        matching method, advances `review_round` by one, auto-creates a format
        check, recomputes `content_status`, moves `review_status` to
        `IN_REVIEW`, and increments the label's `version`."
        PRD §3.6: "Rejection moves the label from `IN_REVIEW` back to `DRAFT`
        — the same `ERR_LABEL_NOT_IN_REVIEW` guard applies — optionally
        recording a free-text `reason`, clearing `approved_by`, and
        deliberately leaving the declared content untouched:
        `ingredient_statement_text`, `contains_text`, `declared_format`,
        `declared_type_size_in`, and the pinned `panel_snapshot_id` all
        survive rejection unchanged, so the analyst can correct and resubmit
        without re-entering the artwork facts."

        Design: Difficulty/non_linear_state_machine/label_parallel_dimensions_and_reject_cycle
        """
        ws = setup_wafer_workspace()
        label_id = ws["label"]["id"]

        submitted = submit_label(label_id)
        assert submitted["review_status"] == "IN_REVIEW"
        assert submitted["review_round"] == 1

        rejected = reject_label(label_id, reason="panel legibility")
        assert rejected["review_status"] == "DRAFT", "reject cycle leg"

        resubmitted = submit_label(label_id)
        assert resubmitted["review_status"] == "IN_REVIEW"
        assert resubmitted["review_round"] == 2, (
            "the round accumulates across the reject cycle"
        )

        approved = approve_label(label_id)
        assert approved["review_status"] == "APPROVED"

    def test_release_and_withdraw_leave_review_dimension_approved(self, api):
        """PRD §3.6: "A successful release moves `release_status` to
        `RELEASED`, flips any other `RELEASED` label version of the same
        product and market to `SUPERSEDED` while stamping its
        `superseded_by_id` with the newly released label's id, and increments
        both the product's and the label's `version`."
        PRD §3.6: "Withdrawal is the compensating mirror: a `QualityManager`
        withdraws a label that is `RELEASED` (any other release status is
        rejected with `ERR_INVALID_STATE_TRANSITION`), optionally supplying a
        `reason`; the label moves to `WITHDRAWN`, the label whose
        `superseded_by_id` points at the withdrawn one is restored to
        `RELEASED`, and again both the product's and the label's `version`
        increment."

        Design: Difficulty/non_linear_state_machine/label_parallel_dimensions_and_reject_cycle
        """
        ws = setup_released_wafer_label()
        assert ws["label"]["release_status"] == "RELEASED"
        assert ws["label"]["review_status"] == "APPROVED"

        withdrawn = withdraw_label(ws["label"]["id"], ws["client"]["id"],
                                   reason="retailer hold")
        assert withdrawn["release_status"] == "WITHDRAWN", (
            "the release dimension moves"
        )
        assert withdrawn["review_status"] == "APPROVED", (
            "the review dimension is untouched"
        )


class TestReleaseBlockedByIneligibleClaim:
    def test_release_blocked_by_ineligible_claim(self, api):
        """PRD §3.6: "Release is a `QualityManager` act with a gauntlet of
        gates, evaluated in the fixed order of §2.8: the label must be
        `APPROVED` with `release_status` `NOT_RELEASED`
        (`ERR_LABEL_NOT_APPROVED`), `content_status` must be `READY`
        (`ERR_CONTENT_REVISION_REQUIRED`), every claim on the label must be
        `ELIGIBLE` or `NOT_REQUIRED` — a claim still `PENDING`, `SUSPENDED`,
        or `INELIGIBLE` blocks release with `ERR_CLAIMS_NOT_RESOLVED` — and
        the most recently created format check must be `PASS`
        (`ERR_FORMAT_CHECK_FAILED`)."

        Design: Difficulty/cross_entity_state_dependency/release_blocked_by_ineligible_claim
        """
        ws = setup_cookie_workspace()
        claim = create_claim(ws["label"]["id"], "HIGH_FIBER")
        assert claim["status"] == "INELIGIBLE"
        submit_label(ws["label"]["id"])
        approve_label(ws["label"]["id"])

        resp = api.release_label(
            ws["label"]["id"],
            {"expected_product_version":
                 get_product(ws["product"]["id"])["version"]},
            ws["quality_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_CLAIMS_NOT_RESOLVED,
                       expected_status=409)
        assert get_label_version(ws["label"]["id"])["release_status"] == (
            "NOT_RELEASED"
        )

    def test_ineligible_claim_does_not_block_approval(self, api):
        """PRD §3.7: "That derived flag follows one rule everywhere:
        `content_status` is `NEEDS_REVISION` whenever any claim on the label
        is `SUSPENDED`, or the product's locked recipe has changed out from
        under the label's pinned basis, or the pinned panel snapshot has gone
        `STALE` — and it is `READY` when none of those hold."
        PRD §3.7: "Meeting the threshold settles the claim `ELIGIBLE`;
        missing it settles `INELIGIBLE`, with `disqualified_by` recorded as
        `NONE` when no disqualifier fired."

        Design: Difficulty/cross_entity_state_dependency/release_blocked_by_ineligible_claim
        """
        ws = setup_cookie_workspace()
        claim = create_claim(ws["label"]["id"], "HIGH_FIBER")
        assert claim["status"] == "INELIGIBLE", (
            "fiber per RACC 2.25 x 0.55 = 1.24 < 5.0"
        )
        assert claim["evaluated_value_per_racc"] == pytest.approx(1.24, abs=0.005)
        assert claim["disqualified_by"] == "NONE"

        submit_label(ws["label"]["id"])
        label = get_label_version(ws["label"]["id"])
        assert label["content_status"] == "READY", (
            "an INELIGIBLE claim does not flip content_status"
        )
        approved = approve_label(ws["label"]["id"])
        assert approved["review_status"] == "APPROVED"


class TestReleaseWithdrawInvariant:
    def test_release_supersedes_prior_release(self, api):
        """PRD §3.6: "A successful release moves `release_status` to
        `RELEASED`, flips any other `RELEASED` label version of the same
        product and market to `SUPERSEDED` while stamping its
        `superseded_by_id` with the newly released label's id, and increments
        both the product's and the label's `version`."

        Design: Difficulty/compensating_invariant/invariant_release_withdraw_conserves_released_set
        """
        ws = setup_released_wafer_label()
        lv1 = ws["label"]
        assert _released_ids(ws["product"]["id"]) == {lv1["id"]}

        lv2 = create_label_draft(ws["product"]["id"], ws["racc"]["id"],
                                 statement_recipe_id=ws["recipe"]["id"])
        submit_label(lv2["id"])
        approve_label(lv2["id"])
        release_label(ws["product"]["id"], lv2["id"], ws["client"]["id"])

        lv1_mid = get_label_version(lv1["id"])
        assert lv1_mid["release_status"] == "SUPERSEDED", (
            "the forward action displaced LV1"
        )
        assert lv1_mid["superseded_by_id"] == lv2["id"]
        assert _released_ids(ws["product"]["id"]) == {lv2["id"]}, (
            "exactly one label of the product+market is RELEASED"
        )

    def test_withdraw_restores_superseded_release(self, api):
        """PRD §3.6: "Withdrawal is the compensating mirror: a
        `QualityManager` withdraws a label that is `RELEASED` (any other
        release status is rejected with `ERR_INVALID_STATE_TRANSITION`),
        optionally supplying a `reason`; the label moves to `WITHDRAWN`, the
        label whose `superseded_by_id` points at the withdrawn one is restored
        to `RELEASED`, and again both the product's and the label's `version`
        increment."

        Design: Difficulty/compensating_invariant/invariant_release_withdraw_conserves_released_set
        """
        ws = setup_released_wafer_label()
        lv1 = ws["label"]
        lv2 = create_label_draft(ws["product"]["id"], ws["racc"]["id"],
                                 statement_recipe_id=ws["recipe"]["id"])
        submit_label(lv2["id"])
        approve_label(lv2["id"])
        release_label(ws["product"]["id"], lv2["id"], ws["client"]["id"])

        withdrawn = withdraw_label(lv2["id"], ws["client"]["id"],
                                   reason="recall hold")
        assert withdrawn["release_status"] == "WITHDRAWN", "compensating action"
        lv1_end = get_label_version(lv1["id"])
        assert lv1_end["release_status"] == "RELEASED", (
            "restored via the superseded_by_id linkage"
        )
        assert _released_ids(ws["product"]["id"]) == {lv1["id"]}, (
            "the released set is identical to the pre-release state"
        )


class TestSubmitRejectInvariant:
    def test_submit_reject_conserves_content_tuple(self, api):
        """PRD §3.6: "Rejection moves the label from `IN_REVIEW` back to
        `DRAFT` — the same `ERR_LABEL_NOT_IN_REVIEW` guard applies —
        optionally recording a free-text `reason`, clearing `approved_by`, and
        deliberately leaving the declared content untouched:
        `ingredient_statement_text`, `contains_text`, `declared_format`,
        `declared_type_size_in`, and the pinned `panel_snapshot_id` all
        survive rejection unchanged, so the analyst can correct and resubmit
        without re-entering the artwork facts."

        Design: Difficulty/compensating_invariant/invariant_submit_reject_conserves_content
        """
        ws = setup_wafer_workspace()
        label = ws["label"]
        tuple_before = (label["ingredient_statement_text"],
                        label["contains_text"], label["declared_format"],
                        label["declared_type_size_in"])

        submitted = submit_label(label["id"])
        snapshot = submitted["panel_snapshot_id"]
        assert snapshot is not None
        reject_label(label["id"], reason="needs rework")

        after = get_label_version(label["id"])
        assert (after["ingredient_statement_text"],
                after["contains_text"], after["declared_format"],
                after["declared_type_size_in"]) == tuple_before, (
            "the content tuple is conserved"
        )
        assert after["panel_snapshot_id"] == snapshot, (
            "the pinned snapshot survives the cycle unchanged"
        )
        assert after["approved_by"] is None, "approved_by is cleared by reject"
        assert after["review_status"] == "DRAFT"

    def test_review_round_drifts_only_on_submit(self, api):
        """PRD §3.6: "On success the submission pins `panel_snapshot_id` to
        the most recently created `CURRENT` panel of the recipe with the
        matching method, advances `review_round` by one, auto-creates a format
        check, recomputes `content_status`, moves `review_status` to
        `IN_REVIEW`, and increments the label's `version`."
        PRD §3.6: "The new draft initializes with `review_status` `DRAFT`,
        `release_status` `NOT_RELEASED`, `review_round` 0, and `prepared_by`
        set to the creating analyst's `X-User-ID`; the product's `version`
        increments as part of the same write."

        Design: Difficulty/compensating_invariant/invariant_submit_reject_conserves_content
        """
        ws = setup_wafer_workspace()
        assert ws["label"]["review_round"] == 0

        submitted = submit_label(ws["label"]["id"])
        assert submitted["review_round"] == 1
        reject_label(ws["label"]["id"], reason="needs rework")

        after = get_label_version(ws["label"]["id"])
        assert after["review_round"] == 1, (
            "review_round increments on submit only — the sole permitted drift"
        )
