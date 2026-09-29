"""The design revision review loop and its reach into production."""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_approved_revision,
    create_changes_requested_revision,
    create_draft_revision,
    create_product,
    freeze_design_payload,
    get_lot_data,
    get_product_data,
    get_revision_data,
    is_iso8601_timestamp,
    open_lot,
    review_design_revision_payload,
    run_campaign_to_passed,
    start_production_payload,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["design_engineer_headers"]
APPROVER = TEST_USERS["design_approver_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]


class TestReviewLoopRoundCounter:
    def test_revising_a_changes_requested_revision_increments_review_round(self):
        """PRD §3.2: "Revising increments `review_round` by one, so `review_round`
        is the count of completed review loops, and it clears
        `submitted_by_user_id` back to null so that the next submission
        re-stamps it with whoever submits."

        Design: Difficulty/non_linear_state_machine/design_revision_review_cycle_increments_review_round
        """
        product = create_product()
        revision = create_changes_requested_revision(
            product["id"], structural_margin_pct=7.25, rail_section_modulus_in3=0.310
        )
        assert revision["status"] == "CHANGES_REQUESTED"
        assert revision["review_round"] == 1

        revised = validate_success(
            api_client.revise_design_revision(revision["id"], ENGINEER)
        )

        assert revised["status"] == "DRAFT", "revise returns the revision to DRAFT"
        assert revised["review_round"] == 2, (
            f"review_round must reach 2 after one completed loop, got {revised['review_round']}"
        )
        assert revised["submitted_by_user_id"] is None, (
            "revise clears submitted_by_user_id back to null"
        )

    def test_second_review_round_approves_and_stamps_both_operator_identifiers(self):
        """PRD §3.2: "Submitting the revision for review moves it `DRAFT` →
        `UNDER_REVIEW` and stamps `submitted_by_user_id` with the submitting
        engineer's `X-User-ID`, and it also increments the revision's `version`."
        PRD §3.2: "`APPROVE` moves the revision `UNDER_REVIEW` → `APPROVED`, but
        only if `rail_section_modulus_in3` is at least 0.180 cubic inches; below
        that the approval is rejected with `ERR_DESIGN_MARGIN_INSUFFICIENT`."

        Design: Difficulty/non_linear_state_machine/design_revision_review_cycle_increments_review_round
        """
        product = create_product()
        revision = create_changes_requested_revision(
            product["id"], structural_margin_pct=7.25, rail_section_modulus_in3=0.310
        )
        validate_success(api_client.revise_design_revision(revision["id"], ENGINEER))
        validate_success(api_client.submit_design_revision(revision["id"], ENGINEER))

        approved = validate_success(
            api_client.review_design_revision(
                revision["id"], review_design_revision_payload("APPROVE"), APPROVER
            )
        )

        assert approved["status"] == "APPROVED"
        assert approved["review_round"] == 2, (
            "the completed-loop count survives the second submission and approval"
        )
        assert float(approved["structural_margin_pct"]) == 7.25
        assert float(approved["rail_section_modulus_in3"]) == 0.310
        assert approved["submitted_by_user_id"] == "eng-1", (
            "the re-submission re-stamps submitted_by_user_id"
        )
        assert approved["reviewed_by_user_id"] == "appr-1"
        assert approved["superseded_at"] is None, (
            "the newest approved revision is not itself superseded"
        )

    def test_revise_request_overwrites_only_the_supplied_engineering_values(self):
        """PRD §3.2: "Any of `structural_margin_pct`, `rail_section_modulus_in3`,
        and `joint_type` supplied with the revise request overwrite the stored
        engineering values; values not supplied are left as they were."

        Design: Difficulty/non_linear_state_machine/design_revision_review_cycle_increments_review_round
        """
        product = create_product()
        revision = create_changes_requested_revision(
            product["id"],
            joint_type="RIVETED",
            structural_margin_pct=7.25,
            rail_section_modulus_in3=0.310,
        )

        revised = validate_success(
            api_client.revise_design_revision(
                revision["id"], ENGINEER, {"structural_margin_pct": 9.50}
            )
        )

        assert float(revised["structural_margin_pct"]) == 9.50, "supplied value overwrites"
        assert float(revised["rail_section_modulus_in3"]) == 0.310, (
            "an unsupplied engineering value is left as it was"
        )
        assert revised["joint_type"] == "RIVETED", (
            "an unsupplied joint_type is left as it was"
        )
        assert revised["review_round"] == 2


class TestSupersededRevisionBlocksProduction:
    def _setup_superseded_first_revision(self):
        """First revision approved, then replaced by a second approved revision
        that names it as the superseded target; the model is frozen on the
        second."""
        product = create_product()
        first = create_approved_revision(product["id"])
        second = create_approved_revision(
            product["id"], supersedes_revision_id=first["id"]
        )
        product = get_product_data(product["id"])
        run_campaign_to_passed(product, second["id"], "DESIGN_QUALIFICATION")
        product = validate_success(
            api_client.freeze_design(
                product["id"], freeze_design_payload(second["id"]), APPROVER
            )
        )
        lot = open_lot(product, first["id"])
        return product, first, second, lot

    def test_start_production_on_a_superseded_pinned_revision_is_rejected(self):
        """PRD §3.6: "The pinned revision must be `APPROVED` and not yet
        superseded, or the request is rejected with `ERR_REVISION_NOT_APPROVED`."
        PRD §3.2: "A consequence reaches into production immediately — any lot
        still `OPEN` that pinned the now-superseded revision can no longer start
        production, because the pinned revision must be `APPROVED` with a null
        `superseded_at`, and a pinned revision that fails either half of that
        test is rejected with `ERR_REVISION_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/production_blocked_by_superseded_design_revision
        """
        product, first, second, lot = self._setup_superseded_first_revision()
        assert product["design_status"] == "DESIGN_FROZEN", (
            "the design gate is satisfied, so only the revision gate can fail"
        )

        response = api_client.start_production(
            lot["id"], start_production_payload(400), SUPERVISOR
        )
        validate_error(response, ApiErrorId.ERR_REVISION_NOT_APPROVED.value, 409)

        reread = get_lot_data(lot["id"])
        assert reread["status"] == "OPEN", "the rejected start leaves the lot OPEN"
        assert reread["produced_units"] == 0
        assert reread["units_wip"] == 0

    def test_approval_of_the_replacement_supersedes_the_named_prior_revision(self):
        """PRD §3.2: "Approval also carries one cascade: if this revision names a
        `supersedes_revision_id` and the revision so named is itself in
        `APPROVED`, that older revision moves `APPROVED` → `SUPERSEDED` and its
        `superseded_at` is stamped with the logical clock."

        Design: Difficulty/cross_entity_state_dependency/production_blocked_by_superseded_design_revision
        """
        product, first, second, lot = self._setup_superseded_first_revision()

        first_reread = get_revision_data(first["id"])
        assert first_reread["status"] == "SUPERSEDED"
        assert is_iso8601_timestamp(first_reread["superseded_at"] or ""), (
            "the superseded revision carries a stamped superseded_at"
        )

        second_reread = get_revision_data(second["id"])
        assert second_reread["status"] == "APPROVED"
        assert second_reread["superseded_at"] is None
        assert second_reread["supersedes_revision_id"] == first["id"]

        assert product["frozen_revision_id"] == second["id"], (
            "the model is frozen against the surviving approved revision"
        )

    def test_draft_revision_cannot_be_pinned_by_a_production_start(self):
        """PRD §3.6: "The pinned revision must be `APPROVED` and not yet
        superseded, or the request is rejected with `ERR_REVISION_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/production_blocked_by_superseded_design_revision
        """
        product = create_product()
        approved = create_approved_revision(product["id"])
        product = get_product_data(product["id"])
        run_campaign_to_passed(product, approved["id"], "DESIGN_QUALIFICATION")
        product = validate_success(
            api_client.freeze_design(
                product["id"], freeze_design_payload(approved["id"]), APPROVER
            )
        )
        draft = create_draft_revision(product["id"])
        lot = open_lot(product, draft["id"])

        response = api_client.start_production(
            lot["id"], start_production_payload(400), SUPERVISOR
        )
        validate_error(response, ApiErrorId.ERR_REVISION_NOT_APPROVED.value, 409)
        assert get_lot_data(lot["id"])["status"] == "OPEN"
