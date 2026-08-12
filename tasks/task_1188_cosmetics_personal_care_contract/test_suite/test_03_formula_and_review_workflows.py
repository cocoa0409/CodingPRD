"""Formula lifecycle, regulatory review loops, and the compliance hold cascade."""
from test_helpers import (
    ApiErrorId,
    approve_review,
    assert_formula,
    assert_order,
    assert_review,
    assert_run,
    claim_review,
    create_active_formula,
    create_component,
    create_customer,
    create_formula,
    create_revision,
    get_success_data,
    make_customer_rep_headers,
    open_review,
    request_changes,
    resume_order,
    submit_formula,
    resubmit_review,
    scheduled_run_ctx,
    validate_error,
    validate_success,
)


class TestReviewLoopCycle:
    def test_formula_review_cycle_full_loop(self, api, formulation_chemist_headers):
        """PRD §3.3: "The review loop closes when the chemist resubmits the
        formula to `IN_REVIEW` and then resubmits the `CHANGES_REQUESTED` review
        itself, returning the review to `SUBMITTED`; resubmission is refused
        while the referenced formula has not yet returned to `IN_REVIEW`."
        PRD §3.3: "approval of an `INCI_LIST`-scope review moves a formula
        standing `IN_REVIEW` to `APPROVED`".

        Design: Difficulty/non_linear_state_machine/formula_review_cycle
        """
        customer = create_customer()
        component = create_component()
        formula = create_formula(customer["id"], component_id=component["id"])
        submit_formula(formula["id"])
        review = open_review(formula["id"], "INCI_LIST")
        claim_review(review["id"])
        request_changes(review["id"], comment="INCI names incomplete")

        # Resubmitting the review while the formula is still CHANGES_REQUESTED is refused.
        resp = api.resubmit_review(review["id"], formulation_chemist_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        # Resubmit the formula first, then the review; claim + approve cycle again.
        resubmitted_formula = submit_formula(formula["id"])
        assert resubmitted_formula["status"] == "IN_REVIEW"
        cycled_review = resubmit_review(review["id"])
        assert cycled_review["status"] == "SUBMITTED"
        claim_review(review["id"])
        approve_review(review["id"])

        final_formula = validate_success(api.get_formula(formula["id"], formulation_chemist_headers), 200)
        assert_formula(final_formula)
        assert final_formula["status"] == "APPROVED"

    def test_request_changes_records_comment_and_holds_formula(self, api, formulation_chemist_headers,
                                                               regulatory_affairs_headers):
        """PRD §3.3: "Requesting changes moves the review to `CHANGES_REQUESTED`
        and records the reviewer's `comment`."
        PRD §3.3: "The formula — whether it stood `IN_REVIEW` or `ACTIVE`, the
        latter being the post-market re-audit path — moves to
        `CHANGES_REQUESTED`, and the hold cascade fires".

        Design: Difficulty/non_linear_state_machine/formula_review_cycle
        """
        customer = create_customer()
        component = create_component()
        formula = create_formula(customer["id"], component_id=component["id"])
        submit_formula(formula["id"])
        review = open_review(formula["id"], "INCI_LIST")
        claim_review(review["id"])

        updated = request_changes(review["id"], comment="INCI names incomplete")
        assert_review(updated)
        assert updated["status"] == "CHANGES_REQUESTED"
        assert updated["comment"] == "INCI names incomplete"

        fetched_formula = validate_success(api.get_formula(formula["id"], formulation_chemist_headers), 200)
        assert fetched_formula["status"] == "CHANGES_REQUESTED"


class TestReviewUniqueness:
    def test_review_already_open_same_scope(self, api, formulation_chemist_headers):
        """PRD §3.3: "Only one open review — one standing `SUBMITTED`,
        `UNDER_REVIEW`, or `CHANGES_REQUESTED` — may exist per formula per scope;
        opening a duplicate is rejected with `ERR_REVIEW_ALREADY_OPEN`
        (HTTP 409)."

        Design: Corner/validations/review_already_open_same_scope
        """
        customer = create_customer()
        component = create_component()
        formula = create_formula(customer["id"], component_id=component["id"])
        submit_formula(formula["id"])
        open_review(formula["id"], "INCI_LIST")

        resp = api.create_review(formula["id"], {"review_scope": "INCI_LIST"}, formulation_chemist_headers)
        validate_error(resp, ApiErrorId.ERR_REVIEW_ALREADY_OPEN, 409)

        label_review = validate_success(
            api.create_review(formula["id"], {"review_scope": "LABEL_ARTWORK"}, formulation_chemist_headers), 201)
        assert_review(label_review)
        assert label_review["status"] == "SUBMITTED"
        assert label_review["review_scope"] == "LABEL_ARTWORK"


class TestFormulaRetirement:
    def test_formula_retire_terminal_lockdown_and_order_cascade(self, api, plant_director_headers,
                                                                formulation_chemist_headers,
                                                                production_planner_headers):
        """PRD §3.3: "a `PlantDirector` retires an `ACTIVE` formula, moving it to
        its terminal state `RETIRED`, incrementing `version`, and cancelling
        every `DRAFT` production order that still references it, with the full
        cancellation cascade of §3.5."
        PRD §2.9: "Every stateful resource moves only along the transitions
        declared for its lifecycle in §3; terminal states reject every further
        transition."

        Design: Corner/state_machines/formula_retire_terminal_lockdown_and_order_cascade
        """
        customer = create_customer()
        component = create_component()
        formula = create_active_formula(customer["id"], component_id=component["id"])
        order = get_success_data(api.create_order(
            {"formula_id": formula["id"], "requested_units": 1000},
            make_customer_rep_headers(customer["id"])))

        retired = validate_success(api.retire_formula(formula["id"], plant_director_headers), 200)
        assert_formula(retired)
        assert retired["status"] == "RETIRED"

        resp = api.submit_formula(formula["id"], formulation_chemist_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        fetched_order = validate_success(api.get_order(order["id"], production_planner_headers), 200)
        assert_order(fetched_order)
        assert fetched_order["status"] == "CANCELLED", "retire must cascade CANCELLED to DRAFT orders"


class TestRevisionOcc:
    def test_stale_formula_version_on_revision_returns_412(self, api, formulation_chemist_headers):
        """PRD §2.7: "Creating a revision of a formula
        (`POST /cosmfg/formulas/{id}/revisions`) requires the non-optional input
        `expected_formula_version`, carrying the `version` of the parent formula
        as the client last observed it."
        PRD §2.7: "if the supplied value does not match the formula's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "The child is created in `DRAFT` with `version_seq` equal to
        the parent's `version_seq` plus one".

        Design: Corner/errors/stale_formula_version_on_revision_returns_412
        """
        customer = create_customer()
        component = create_component()
        formula = create_active_formula(customer["id"], component_id=component["id"])
        observed_version = validate_success(api.get_formula(formula["id"], formulation_chemist_headers), 200)["version"]

        child = create_revision(formula["id"], observed_version, name="F v2")
        assert_formula(child)
        assert child["version_seq"] == 2
        assert child["status"] == "DRAFT"

        resp = api.create_revision(formula["id"], {"expected_formula_version": observed_version, "name": "F v3"},
                                   formulation_chemist_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


class TestComplianceHoldCascade:
    def test_review_changes_cascade_depth3(self, api, production_planner_headers,
                                           formulation_chemist_headers):
        """PRD §3.3: "The formula — whether it stood `IN_REVIEW` or `ACTIVE`, the
        latter being the post-market re-audit path — moves to
        `CHANGES_REQUESTED`, and the hold cascade fires: every production order
        referencing the formula and standing in `CONFIRMED`, `IN_PRODUCTION`, or
        `FILLING` moves to `ON_HOLD` with its `hold_return_status` set to the
        status it just vacated, and every `SCHEDULED` filling run of each such
        order moves to `ABORTED`, releasing its line window."

        Design: Difficulty/transitive_cascade/review_changes_cascade_depth3
        """
        ctx = scheduled_run_ctx()
        formula_id = ctx["formula"]["id"]
        order_id = ctx["order"]["id"]
        run_id = ctx["run"]["id"]

        # Post-market re-audit: a second INCI_LIST review on the ACTIVE formula.
        reaudit = open_review(formula_id, "INCI_LIST")
        claim_review(reaudit["id"])
        request_changes(reaudit["id"], comment="re-audit finding")

        fetched_formula = validate_success(api.get_formula(formula_id, formulation_chemist_headers), 200)
        assert fetched_formula["status"] == "CHANGES_REQUESTED"

        fetched_order = validate_success(api.get_order(order_id, production_planner_headers), 200)
        assert_order(fetched_order)
        assert fetched_order["status"] == "ON_HOLD"
        assert fetched_order["hold_return_status"] == "CONFIRMED"

        fetched_run = validate_success(api.get_run(run_id, production_planner_headers), 200)
        assert_run(fetched_run)
        assert fetched_run["status"] == "ABORTED"

    def test_held_order_resume_restores_status(self, api, production_planner_headers,
                                               formulation_chemist_headers):
        """PRD §3.3: "A `ProductionPlanner` resumes an `ON_HOLD` order, and the
        order returns to whatever `hold_return_status` recorded — `CONFIRMED`,
        `IN_PRODUCTION`, or `FILLING` — with `hold_return_status` cleared on
        success."
        PRD §3.3: "Resumption requires the referenced formula to stand in
        `IN_REVIEW`, `APPROVED`, or `ACTIVE`; if it does not, the request is
        rejected with `ERR_FORMULA_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/transitive_cascade/review_changes_cascade_depth3
        """
        ctx = scheduled_run_ctx()
        formula_id = ctx["formula"]["id"]
        order_id = ctx["order"]["id"]

        reaudit = open_review(formula_id, "INCI_LIST")
        claim_review(reaudit["id"])
        request_changes(reaudit["id"], comment="re-audit finding")

        held = validate_success(api.get_order(order_id, production_planner_headers), 200)
        assert held["status"] == "ON_HOLD"
        assert held["hold_return_status"] == "CONFIRMED"

        # Formula recovers to IN_REVIEW, which satisfies the resume gate.
        submit_formula(formula_id)
        resumed = resume_order(order_id)
        assert_order(resumed)
        assert resumed["status"] == "CONFIRMED"
        assert resumed["hold_return_status"] is None
