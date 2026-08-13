"""Formula registration, the label-claim review loop, and its cascades."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories,
    create_customer, create_formula, submit_label, quote_run, confirm_run,
    make_product_developer_headers, make_label_reviewer_headers,
    DEV_USER, REV_USER,
)

PM = TEST_USERS["plant_manager_headers"]
FIN = TEST_USERS["finance_clerk_headers"]
DEV = TEST_USERS["product_developer_headers"]
REV = TEST_USERS["label_reviewer_headers"]
PLAN = TEST_USERS["production_planner_headers"]


class TestFormulaCreateDefaults:
    def test_formula_born_draft_with_label_version_zero(self, api):
        """PRD §3.2: "A new formula is born `DRAFT` with `label_version` at zero."

        Design: Corner/entities/formula_create_defaults
        """
        customer = create_customer(approve=False)
        formula = get_success_data(api.create_formula(
            factories.create_formula_payload(
                customer["id"], formula_code="FC-1", name="Corner Cola",
                target_brix=11.0, brix_tolerance=0.2, container_fill_ml=355,
                concentrate_brix=60.0, allergen_group="SULFITE",
                shelf_life_days=60, claims=["NO_ADDED_SUGAR"]),
            DEV))
        assert formula["status"] == "DRAFT"
        assert formula["label_version"] == 0
        assert formula["allergen_group"] == "SULFITE"

    def test_formula_create_returns_201_with_uuid(self, api):
        """PRD §3.2: "A new formula is born `DRAFT` with `label_version` at zero."
        and PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/formula_create_defaults
        """
        from test_helpers import is_valid_uuid
        customer = create_customer(approve=False)
        resp = api.create_formula(
            factories.create_formula_payload(customer["id"]), DEV)
        formula = validate_success(resp, 201)
        assert is_valid_uuid(formula["id"])
        assert formula["status"] == "DRAFT"


class TestFormulaRetire:
    def test_retire_blocked_by_open_run(self, api):
        """PRD §3.2: "Retirement moves a formula terminally to `RETIRED`; it is
        permitted only from `DRAFT` or `APPROVED`, and only while no production
        run of the formula occupies `QUOTED`, `CONFIRMED`, `SCHEDULED`,
        `IN_PRODUCTION`, `BLOCKED_SUPPLY`, or `BLOCKED_LABEL`; violations draw
        `ERR_FORMULA_STATE_INVALID`."

        Design: Corner/state_machines/formula_retire_blocked_by_open_run
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        run = quote_run(customer["id"], formula["id"])
        resp = api.retire_formula(formula["id"], DEV)
        validate_error(resp, ApiErrorId.ERR_FORMULA_STATE_INVALID)
        get_success_data(api.cancel_run(run["id"], PLAN))
        retired = get_success_data(api.retire_formula(formula["id"], DEV))
        assert retired["status"] == "RETIRED"

    def test_retired_formula_is_terminal(self, api):
        """PRD §3.2: "Retirement moves a formula terminally to `RETIRED`; it is
        permitted only from `DRAFT` or `APPROVED`" and "Submitting a formula for
        label review moves it into `LABEL_REVIEW` from `DRAFT`,
        `REVISION_REQUIRED`, `APPROVED`, or even from `LABEL_REVIEW` itself; any
        other source state draws `ERR_FORMULA_STATE_INVALID`."

        Design: Corner/state_machines/formula_retired_terminal_lockdown
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False)
        retired = get_success_data(api.retire_formula(formula["id"], DEV))
        assert retired["status"] == "RETIRED"
        # second retire rejected
        resp = api.retire_formula(formula["id"], DEV)
        validate_error(resp, ApiErrorId.ERR_FORMULA_STATE_INVALID)
        # submit with the CURRENT version: OCC passes, the state gate fires
        resp = api.submit_label_review(
            formula["id"], {"expected_formula_version": retired["version"]}, DEV)
        validate_error(resp, ApiErrorId.ERR_FORMULA_STATE_INVALID)


class TestLabelReviewSupersede:
    def test_resubmit_supersedes_pending_review(self, api):
        """PRD §3.2: "Each accepted submission creates a fresh `LabelClaimReview`
        standing in `PENDING`, freezes the formula's current `claims` into the
        review's `claims_snapshot`, stamps `submitted_by_user_id` with the caller,
        flips any still-`PENDING` earlier review of the same formula to
        `SUPERSEDED`, and advances the formula's `version` by one"

        Design: Corner/state_machines/label_review_supersede_and_decided_lockdown
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False)
        review1 = submit_label(formula["id"])
        assert review1["status"] == "PENDING"
        review2 = submit_label(formula["id"])
        review1_after = get_success_data(api.get_label_review(review1["id"], PM))
        assert review1_after["status"] == "SUPERSEDED"
        # a SUPERSEDED review can no longer be decided
        resp = api.approve_label_review(review1["id"], REV)
        validate_error(resp, ApiErrorId.ERR_REVIEW_STATE_INVALID)

    def test_decided_review_is_terminal(self, api):
        """PRD §3.2: "The review must still stand in `PENDING`, else
        `ERR_REVIEW_STATE_INVALID`, and an approval only lands when the decided
        review is the formula's current pending review."

        Design: Corner/state_machines/label_review_supersede_and_decided_lockdown
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False)
        review = submit_label(formula["id"])
        approved = get_success_data(api.approve_label_review(review["id"], REV))
        assert approved["status"] == "APPROVED"
        resp = api.approve_label_review(review["id"], REV)
        validate_error(resp, ApiErrorId.ERR_REVIEW_STATE_INVALID)
        resp = api.reject_label_review(review["id"], {"review_note": "too late"}, REV)
        validate_error(resp, ApiErrorId.ERR_REVIEW_STATE_INVALID)


class TestLabelSod:
    def test_submitter_cannot_approve_own_review(self, api):
        """PRD §3.2: "Decisions belong to a `LabelComplianceReviewer`, and the
        review loop is segregated: the deciding reviewer's `X-User-ID` must differ
        from the formula's `submitted_by_user_id`, else the decision is refused
        with `ERR_SOD_LABEL_SELF_REVIEW`."

        Design: Corner/rbac/sod_label_self_review
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False)
        review = submit_label(formula["id"])  # submitted by DEV_USER
        resp = api.approve_label_review(
            review["id"], make_label_reviewer_headers(DEV_USER))
        validate_error(resp, ApiErrorId.ERR_SOD_LABEL_SELF_REVIEW)
        # the review is untouched by the refused decision
        review_mid = get_success_data(api.get_label_review(review["id"], PM))
        assert review_mid["status"] == "PENDING"

    def test_distinct_reviewer_approves_and_bumps_label_version(self, api):
        """PRD §3.2: "Approval moves the review to `APPROVED`, records the decider
        in `reviewer_user_id`, returns the formula to `APPROVED`, increments
        `label_version` by exactly one"

        Design: Corner/rbac/sod_label_self_review
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False)
        review = submit_label(formula["id"])
        assert review["claims_snapshot"] == formula["claims"]
        approved = get_success_data(api.approve_label_review(review["id"], REV))
        assert approved["status"] == "APPROVED"
        assert approved["reviewer_user_id"] == REV_USER
        formula_after = get_success_data(api.get_formula(formula["id"], PM))
        assert formula_after["status"] == "APPROVED"
        assert formula_after["label_version"] == 1  # 0 at birth + 1 per approval
        assert formula_after["submitted_by_user_id"] == DEV_USER


class TestLabelReviewOcc:
    def test_stale_expected_version_rejected(self, api):
        """PRD §2.7: "If the supplied value does not equal the parent entity's
        current `version` — because a prior successful write has legitimately
        advanced it since the client last read the resource — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and no part of the write is
        applied."

        Design: Corner/cross_cutting_layers/occ_submit_label_review_stale
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False)
        v0 = formula["version"]
        submit_label(formula["id"])  # bumps version by one
        resp = api.submit_label_review(
            formula["id"], {"expected_formula_version": v0}, DEV)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

    def test_current_version_submit_succeeds_and_supersedes(self, api):
        """PRD §3.2: "flips any still-`PENDING` earlier review of the same formula
        to `SUPERSEDED`, and advances the formula's `version` by one — which is
        precisely why a second submission bearing the previously observed version
        reads as stale."

        Design: Corner/cross_cutting_layers/occ_submit_label_review_stale
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False)
        v0 = formula["version"]
        review1 = submit_label(formula["id"])
        v1 = get_success_data(api.get_formula(formula["id"], PM))["version"]
        assert v1 == v0 + 1
        review2 = get_success_data(api.submit_label_review(
            formula["id"], {"expected_formula_version": v1}, DEV))
        assert review2["status"] == "PENDING"
        assert get_success_data(api.get_label_review(review1["id"], PM))["status"] == "SUPERSEDED"
        v2 = get_success_data(api.get_formula(formula["id"], PM))["version"]
        assert v2 == v1 + 1


class TestOccBeatsStateCheck:
    def test_stale_submit_on_retired_formula_is_412(self, api):
        """PRD §2.6: "Every request is validated against a fixed pipeline of check
        categories, evaluated in the order below; when several checks would fail,
        the earliest category's error is the one returned." (optimistic
        concurrency, category 4, precedes state-machine admissibility, category 5.)

        Design: Corner/validations/occ_stale_version_beats_state_check
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False)
        retired = get_success_data(api.retire_formula(formula["id"], DEV))
        # stale version: OCC fires before the RETIRED state gate
        resp = api.submit_label_review(
            formula["id"], {"expected_formula_version": retired["version"] - 1}, DEV)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

    def test_current_version_submit_on_retired_formula_is_409(self, api):
        """PRD §3.2: "Submitting a formula for label review moves it into
        `LABEL_REVIEW` from `DRAFT`, `REVISION_REQUIRED`, `APPROVED`, or even from
        `LABEL_REVIEW` itself; any other source state draws
        `ERR_FORMULA_STATE_INVALID`."

        Design: Corner/validations/occ_stale_version_beats_state_check
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False)
        retired = get_success_data(api.retire_formula(formula["id"], DEV))
        resp = api.submit_label_review(
            formula["id"], {"expected_formula_version": retired["version"]}, DEV)
        validate_error(resp, ApiErrorId.ERR_FORMULA_STATE_INVALID)
        assert resp.status_code == 409


class TestLabelReviewCycle:
    def test_rejection_does_not_bump_label_version(self, api):
        """PRD §3.2: "Rejection — which may carry an optional `review_note` —
        moves the review to `REJECTED`, drops the formula to `REVISION_REQUIRED`"
        (label_version increments only on approval: "increments `label_version` by
        exactly one" is stated of approval).

        Design: Difficulty/non_linear_state_machine/formula_label_review_cycle_version_bumps
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False)
        review = submit_label(formula["id"])
        rejected = get_success_data(api.reject_label_review(
            review["id"], {"review_note": "claim unsubstantiated"}, REV))
        assert rejected["status"] == "REJECTED"
        formula_after = get_success_data(api.get_formula(formula["id"], PM))
        assert formula_after["status"] == "REVISION_REQUIRED"
        assert formula_after["label_version"] == 0

    def test_full_cycle_bumps_label_version_per_approval(self, api):
        """PRD §3.2: "Approval moves the review to `APPROVED`, records the decider
        in `reviewer_user_id`, returns the formula to `APPROVED`, increments
        `label_version` by exactly one" and "Submitting a formula for label review
        moves it into `LABEL_REVIEW` from `DRAFT`, `REVISION_REQUIRED`,
        `APPROVED`, or even from `LABEL_REVIEW` itself"

        Design: Difficulty/non_linear_state_machine/formula_label_review_cycle_version_bumps
        """
        customer = create_customer(approve=False)
        formula = create_formula(customer["id"], approve=False)
        # DRAFT -> LABEL_REVIEW -> REVISION_REQUIRED
        review1 = submit_label(formula["id"])
        get_success_data(api.reject_label_review(review1["id"], {"review_note": "nope"}, REV))
        # REVISION_REQUIRED -> LABEL_REVIEW -> APPROVED (label_version 0 -> 1)
        review2 = submit_label(formula["id"])
        get_success_data(api.approve_label_review(review2["id"], REV))
        formula_mid = get_success_data(api.get_formula(formula["id"], PM))
        assert formula_mid["status"] == "APPROVED"
        assert formula_mid["label_version"] == 1
        # APPROVED -> LABEL_REVIEW -> APPROVED (label_version 1 -> 2)
        review3 = submit_label(formula["id"])
        approved3 = get_success_data(api.approve_label_review(
            review3["id"], make_label_reviewer_headers("rev-2")))
        assert approved3["status"] == "APPROVED"
        formula_end = get_success_data(api.get_formula(formula["id"], PM))
        assert formula_end["status"] == "APPROVED"
        assert formula_end["label_version"] == 2


class TestLabelRejectCascade:
    def _approved_formula_with_confirmed_run(self):
        customer = create_customer()
        formula = create_formula(customer["id"])
        run = quote_run(customer["id"], formula["id"])
        run = confirm_run(run["id"])
        return customer, formula, run

    def test_reject_demotes_confirmed_runs(self, api):
        """PRD §3.2: "Rejection — which may carry an optional `review_note` —
        moves the review to `REJECTED`, drops the formula to `REVISION_REQUIRED`,
        and cascades every `CONFIRMED` run of the formula into `BLOCKED_LABEL`
        (§2.10)."

        Design: Difficulty/transitive_cascade/label_reject_cascade_demotes_confirmed_runs
        """
        customer, formula, run = self._approved_formula_with_confirmed_run()
        # re-submitting an APPROVED formula does not yet demote the CONFIRMED run
        review2 = submit_label(formula["id"])
        assert get_success_data(api.get_production_run(run["id"], PM))["production_status"] == "CONFIRMED"
        rejected = get_success_data(api.reject_label_review(
            review2["id"], {"review_note": "vitamin claim unsubstantiated"},
            make_label_reviewer_headers("rev-2")))
        assert rejected["status"] == "REJECTED"
        run_mid = get_success_data(api.get_production_run(run["id"], PM))
        assert run_mid["production_status"] == "BLOCKED_LABEL"
        formula_mid = get_success_data(api.get_formula(formula["id"], PM))
        assert formula_mid["status"] == "REVISION_REQUIRED"

    def test_approve_restores_blocked_label_runs(self, api):
        """PRD §3.2: "Approval moves the review to `APPROVED`, records the decider
        in `reviewer_user_id`, returns the formula to `APPROVED`, increments
        `label_version` by exactly one, and automatically restores every
        production run of that formula sitting in `BLOCKED_LABEL` back to
        `CONFIRMED`."

        Design: Difficulty/transitive_cascade/label_reject_cascade_demotes_confirmed_runs
        """
        customer, formula, run = self._approved_formula_with_confirmed_run()
        review2 = submit_label(formula["id"])
        get_success_data(api.reject_label_review(
            review2["id"], {"review_note": "claim"}, make_label_reviewer_headers("rev-2")))
        assert get_success_data(api.get_production_run(run["id"], PM))["production_status"] == "BLOCKED_LABEL"
        review3 = submit_label(formula["id"])
        get_success_data(api.approve_label_review(review3["id"], REV))
        run_end = get_success_data(api.get_production_run(run["id"], PM))
        assert run_end["production_status"] == "CONFIRMED"
