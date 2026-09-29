"""Two state dimensions on one row, each with its own triggers and its own guards."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import INSPECTOR_HEADERS, OFFICER_HEADERS


def _submit(site_id, reference):
    return api_client.submit_esc_plan(
        site_id, factories.submit_esc_plan_payload(reference), INSPECTOR_HEADERS
    )


def _review(site_id, decision, notes=None):
    overrides = {"review_notes": notes} if notes is not None else {}
    return api_client.esc_review(
        site_id, factories.esc_review_payload(decision, **overrides), INSPECTOR_HEADERS
    )


def _stop(site_id, reason):
    return api_client.stop_work(
        site_id, factories.stop_work_payload(reason=reason), OFFICER_HEADERS
    )


def _release(site_id, note):
    return api_client.release_stop_work(
        site_id,
        factories.release_stop_work_payload(corrective_action_note=note),
        OFFICER_HEADERS,
    )


def _close(site_id, note):
    return api_client.close_construction_site(
        site_id, factories.close_site_payload(final_stabilization_note=note), INSPECTOR_HEADERS
    )


class TestPlanReviewCyclesThroughReturned:
    """Review has exactly one legal source state, and the cycle counts each pass."""

    @pytest.fixture
    def submitted_site(self, active_program):
        """SITE-B at 1.50 acres, plan SUBMITTED, field PRE_CONSTRUCTION."""
        site = fx.create_site(
            active_program["term_id"],
            site_name="SITE-B",
            operator_name="Northgate Civil",
            disturbed_acres=1.50,
        )
        return {"term_id": active_program["term_id"], "site": site}

    def test_01_review_is_refused_before_the_plan_is_submitted(self, submitted_site):
        """SUBMITTED is not ESC_REVIEW, so there is nothing to decide on.

        PRD: "Review then takes a `decision` of either `APPROVE` or `RETURN` and may
        carry `review_notes`; it is available only while `plan_status` is `ESC_REVIEW`,
        and otherwise refused with `ERR_PLAN_NOT_IN_REVIEW`, and it requires the owning
        term to be `ACTIVE`."

        Design: Corner/state_machines/plan_review_cycles_through_returned_and_only_reviews_a_plan_in_review
        """
        response = _review(submitted_site["site"]["id"], "APPROVE")

        validate_error(response, ApiErrorId.ERR_PLAN_NOT_IN_REVIEW.value, 409)

        site = fx.read_site(submitted_site["site"]["id"])
        assert site["plan_status"] == "SUBMITTED", "the refused review moved nothing"
        assert site["plan_review_round"] == 0, "no review round was counted"
        assert site["esc_plan_reference"] is None, "no reference was recorded"

    def test_02_a_return_decision_counts_a_round_and_leaves_the_field_dimension(
        self, submitted_site
    ):
        """The plan falls back to RETURNED; the field dimension does not budge.

        PRD: "Either decision increments `plan_review_round` by one. `RETURN` writes
        `RETURNED` into `plan_status` and leaves `field_status` untouched, so the
        operator can revise and resubmit."

        Design: Corner/state_machines/plan_review_cycles_through_returned_and_only_reviews_a_plan_in_review
        """
        site_id = submitted_site["site"]["id"]
        in_review = validate_success(_submit(site_id, "ESC-B-R1"))
        assert in_review["plan_status"] == "ESC_REVIEW", "submission opens the review"
        assert in_review["esc_plan_reference"] == "ESC-B-R1", "the reference is recorded"

        returned = validate_success(
            _review(site_id, "RETURN", "Silt fence detail missing")
        )

        assert returned["plan_status"] == "RETURNED", "the plan comes back"
        assert returned["plan_review_round"] == 1, "one round was counted"
        assert returned["field_status"] == "PRE_CONSTRUCTION", (
            "the field dimension is untouched by a plan decision"
        )
        assert returned["esc_plan_reference"] == "ESC-B-R1", "the reference survives"

    def test_03_review_is_refused_from_returned_as_well(self, submitted_site):
        """RETURNED offers a resubmission, not a second decision.

        PRD: "it is available only while `plan_status` is `ESC_REVIEW`, and otherwise
        refused with `ERR_PLAN_NOT_IN_REVIEW`, and it requires the owning term to be
        `ACTIVE`."

        Design: Corner/state_machines/plan_review_cycles_through_returned_and_only_reviews_a_plan_in_review
        """
        site_id = submitted_site["site"]["id"]
        validate_success(_submit(site_id, "ESC-B-R1"))
        validate_success(_review(site_id, "RETURN", "Silt fence detail missing"))

        response = _review(site_id, "APPROVE")

        validate_error(response, ApiErrorId.ERR_PLAN_NOT_IN_REVIEW.value, 409)

        site = fx.read_site(site_id)
        assert site["plan_status"] == "RETURNED", "the refused review moved nothing"
        assert site["plan_review_round"] == 1, "the round count is unchanged"

    def test_04_the_second_pass_approves_and_cascades_the_field_dimension(
        self, submitted_site
    ):
        """A resubmission reopens the review, and approval starts the disturbance.

        PRD: "The inspector submits the plan by supplying an `esc_plan_reference`, which
        moves `plan_status` from either `SUBMITTED` or `RETURNED` into `ESC_REVIEW`,
        records the reference, and leaves `field_status` untouched." And: "`APPROVE`
        writes `APPROVED` into `plan_status` and, if and only if `field_status` is still
        `PRE_CONSTRUCTION`, additionally advances `field_status` to `ACTIVE_DISTURBANCE`
        — the point at which the site becomes eligible for erosion-control
        inspections."

        Design: Corner/state_machines/plan_review_cycles_through_returned_and_only_reviews_a_plan_in_review
        """
        site_id = submitted_site["site"]["id"]
        validate_success(_submit(site_id, "ESC-B-R1"))
        validate_success(_review(site_id, "RETURN", "Silt fence detail missing"))
        validate_success(_submit(site_id, "ESC-B-R2"))

        approved = validate_success(_review(site_id, "APPROVE", "Detail added"))

        assert approved["plan_status"] == "APPROVED", "the second pass approves"
        assert approved["plan_review_round"] == 2, "both passes were counted"
        assert approved["esc_plan_reference"] == "ESC-B-R2", "the newer reference stands"
        assert approved["field_status"] == "ACTIVE_DISTURBANCE", (
            "approval from PRE_CONSTRUCTION starts the disturbance"
        )

    def test_05_a_site_below_two_acres_needs_no_permanent_control(self, submitted_site):
        """1.50 acres is under the post-construction threshold.

        PRD: "On creation the server derives `post_construction_control_required`,
        setting it true exactly when `disturbed_acres` is 2.00 or more, and initialises
        `plan_review_round` and `stop_work_count` to 0, `open_deficiency_score` to 0,
        `open_enforcement_count` to 0, and `esc_plan_reference`, `stop_work_reason` and
        `closed_at` to null."

        Design: Corner/state_machines/plan_review_cycles_through_returned_and_only_reviews_a_plan_in_review
        """
        site = fx.read_site(submitted_site["site"]["id"])

        assert site["disturbed_acres"] == pytest.approx(1.50, abs=0.01), (
            "the site is one and a half acres"
        )
        assert site["post_construction_control_required"] is False, (
            "below 2.00 acres no permanent control is required"
        )
        assert site["stop_work_count"] == 0, "no order has been issued"
        assert site["open_enforcement_count"] == 0, "no action is live"
        assert site["closed_at"] is None, "the file is open"


class TestStopWorkAndReleaseGuardTheirOwnState:
    """Two triggers on one dimension, each with its own refusal code."""

    @pytest.fixture
    def pre_construction_site(self, active_program):
        """SITE-C at 1.50 acres, plan SUBMITTED, field PRE_CONSTRUCTION."""
        site = fx.create_site(
            active_program["term_id"],
            site_name="SITE-C",
            operator_name="Northgate Civil",
            disturbed_acres=1.50,
        )
        return {"term_id": active_program["term_id"], "site": site}

    def test_06_stop_work_is_refused_before_the_disturbance_begins(
        self, pre_construction_site
    ):
        """There is no work to stop while the site is pre-construction.

        PRD: "A stop-work order attempted on a site whose `field_status` is not
        `ACTIVE_DISTURBANCE` is refused with `ERR_SITE_NOT_ACTIVE_DISTURBANCE`, and on a
        closed site with `ERR_SITE_CLOSED`."

        Design: Corner/state_machines/stop_work_and_release_each_guard_their_own_field_state
        """
        response = _stop(pre_construction_site["site"]["id"], "No perimeter control")

        validate_error(response, ApiErrorId.ERR_SITE_NOT_ACTIVE_DISTURBANCE.value, 409)

        site = fx.read_site(pre_construction_site["site"]["id"])
        assert site["stop_work_count"] == 0, "no order was counted"
        assert site["stop_work_reason"] is None, "no reason was recorded"

    def test_07_release_is_refused_from_the_same_state_with_a_different_code(
        self, pre_construction_site
    ):
        """The two guards are not interchangeable.

        PRD: "Releasing a site that is not stopped is `ERR_SITE_NOT_STOPPED`."

        Design: Corner/state_machines/stop_work_and_release_each_guard_their_own_field_state
        """
        response = _release(pre_construction_site["site"]["id"], "Nothing to release")

        validate_error(response, ApiErrorId.ERR_SITE_NOT_STOPPED.value, 409)

        site = fx.read_site(pre_construction_site["site"]["id"])
        assert site["field_status"] == "PRE_CONSTRUCTION", "the site never moved"

    def test_08_an_order_on_a_disturbed_site_records_its_reason(
        self, pre_construction_site
    ):
        """A manual order writes the reason and counts one order.

        PRD: "Stop-work authority belongs to the `EnforcementOfficer`, who supplies a
        `reason` and drives `field_status` from `ACTIVE_DISTURBANCE` to `STOP_WORK`
        while the term is `ACTIVE`, recording that reason in `stop_work_reason`,
        incrementing `stop_work_count` by one, and leaving `plan_status` untouched."

        Design: Corner/state_machines/stop_work_and_release_each_guard_their_own_field_state
        """
        site_id = pre_construction_site["site"]["id"]
        validate_success(_submit(site_id, "ESC-C"))
        validate_success(_review(site_id, "APPROVE", "Plan meets the design standard"))

        stopped = validate_success(_stop(site_id, "Sediment discharge to Mill Creek"))

        assert stopped["field_status"] == "STOP_WORK", "the order stops the work"
        assert stopped["stop_work_reason"] == "Sediment discharge to Mill Creek", (
            "the officer's reason is recorded verbatim"
        )
        assert stopped["stop_work_count"] == 1, "one order was counted"
        assert stopped["plan_status"] == "APPROVED", "the plan dimension is untouched"
        assert stopped["open_deficiency_score"] == 0, (
            "no inspection drove the score, so it stays at zero"
        )

    def test_09_a_second_order_is_refused_because_stop_work_is_not_idempotent(
        self, pre_construction_site
    ):
        """The order's own source state is consumed by the first order.

        PRD: "A stop-work order attempted on a site whose `field_status` is not
        `ACTIVE_DISTURBANCE` is refused with `ERR_SITE_NOT_ACTIVE_DISTURBANCE`, and on a
        closed site with `ERR_SITE_CLOSED`."

        Design: Corner/state_machines/stop_work_and_release_each_guard_their_own_field_state
        """
        site_id = pre_construction_site["site"]["id"]
        validate_success(_submit(site_id, "ESC-C"))
        validate_success(_review(site_id, "APPROVE", "Plan meets the design standard"))
        validate_success(_stop(site_id, "Sediment discharge to Mill Creek"))

        response = _stop(site_id, "Same violation observed again")

        validate_error(response, ApiErrorId.ERR_SITE_NOT_ACTIVE_DISTURBANCE.value, 409)

        site = fx.read_site(site_id)
        assert site["stop_work_count"] == 1, "the refused order counted nothing"
        assert site["stop_work_reason"] == "Sediment discharge to Mill Creek", (
            "the stored reason was not overwritten"
        )

    def test_10_a_manual_order_generates_no_automatic_notice(self, pre_construction_site):
        """Only the finalize cascade writes an action by itself.

        PRD: "The automatic action that the finalize cascade generates is the same
        record on a different origin: `action_type` `NOTICE_OF_VIOLATION`,
        `auto_generated` true, `source_inspection_id` set to the inspection that
        triggered it, `issued_by_user_id` recorded as the system rather than an
        operator, and `violation_days` left at its default of 0."

        Design: Corner/state_machines/stop_work_and_release_each_guard_their_own_field_state
        """
        site_id = pre_construction_site["site"]["id"]
        validate_success(_submit(site_id, "ESC-C"))
        validate_success(_review(site_id, "APPROVE", "Plan meets the design standard"))
        validate_success(_stop(site_id, "Sediment discharge to Mill Creek"))

        _, meta = validate_paginated(
            api_client.list_enforcement_actions(
                OFFICER_HEADERS, {"construction_site_id": site_id}
            )
        )
        assert meta["total_count"] == 0, (
            f"a manual order writes no enforcement action, got {meta['total_count']}"
        )

        site = fx.read_site(site_id)
        assert site["open_enforcement_count"] == 0, "no action is live against the site"


class TestReleaseNeedsBothPreconditionsAtOnce:
    """A quiet ledger and an approved plan, checked in that order."""

    @pytest.fixture
    def stopped_site_with_action(self, active_program):
        """SITE-D approved, stopped by hand, carrying one ISSUED notice."""
        site = fx.setup_stopped_site(
            active_program["term_id"],
            esc_plan_reference="ESC-D",
            site_name="SITE-D",
            operator_name="Northgate Civil",
            disturbed_acres=1.50,
        )
        action = validate_success(
            api_client.create_enforcement_action(
                factories.enforcement_action_payload(
                    "NOTICE_OF_VIOLATION",
                    violation_days=0,
                    construction_site_id=site["id"],
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        return {"term_id": active_program["term_id"], "site": site, "action": action}

    def test_11_an_open_action_blocks_the_release(self, stopped_site_with_action):
        """The ledger guard fires first, while the plan is still approved.

        PRD: "The same officer lifts the order by supplying a
        `corrective_action_note`, moving `field_status` from `STOP_WORK` back to
        `ACTIVE_DISTURBANCE`; this requires `open_enforcement_count` to be 0 (otherwise
        `ERR_SITE_HAS_OPEN_ENFORCEMENT`) and `plan_status` to be `APPROVED` (otherwise
        `ERR_ESC_PLAN_NOT_APPROVED`), and it clears `stop_work_reason` to null and
        `open_deficiency_score` to 0."

        Design: Corner/state_machines/release_needs_a_quiet_ledger_and_an_approved_plan_at_the_same_time
        """
        site = fx.read_site(stopped_site_with_action["site"]["id"])
        assert site["open_enforcement_count"] == 1, "one action is live against the site"
        assert site["plan_status"] == "APPROVED", "the plan guard is already satisfied"

        response = _release(stopped_site_with_action["site"]["id"], "Fence installed")

        validate_error(response, ApiErrorId.ERR_SITE_HAS_OPEN_ENFORCEMENT.value, 409)

        after = fx.read_site(stopped_site_with_action["site"]["id"])
        assert after["field_status"] == "STOP_WORK", "the refused release moved nothing"

    def test_12_a_resubmission_moves_the_plan_dimension_while_the_field_stays_stopped(
        self, stopped_site_with_action
    ):
        """The two dimensions really are independent of one another.

        PRD: "Each site carries **two independent state dimensions on the same row**,
        and most operations move exactly one of them."

        Design: Corner/state_machines/release_needs_a_quiet_ledger_and_an_approved_plan_at_the_same_time
        """
        site_id = stopped_site_with_action["site"]["id"]
        validate_success(
            api_client.close_enforcement_action(
                stopped_site_with_action["action"]["id"],
                factories.close_enforcement_payload(
                    compliance_note="Perimeter control verified"
                ),
                OFFICER_HEADERS,
            )
        )

        resubmitted = validate_success(_submit(site_id, "ESC-D-R2"))

        assert resubmitted["plan_status"] == "ESC_REVIEW", "the plan reopens for review"
        assert resubmitted["field_status"] == "STOP_WORK", (
            "the field dimension is untouched by a plan submission"
        )

    def test_13_a_quiet_ledger_alone_does_not_release_the_site(
        self, stopped_site_with_action
    ):
        """With the plan back in review, the second guard fires instead.

        PRD: "this requires `open_enforcement_count` to be 0 (otherwise
        `ERR_SITE_HAS_OPEN_ENFORCEMENT`) and `plan_status` to be `APPROVED` (otherwise
        `ERR_ESC_PLAN_NOT_APPROVED`), and it clears `stop_work_reason` to null and
        `open_deficiency_score` to 0."

        Design: Corner/state_machines/release_needs_a_quiet_ledger_and_an_approved_plan_at_the_same_time
        """
        site_id = stopped_site_with_action["site"]["id"]
        validate_success(
            api_client.close_enforcement_action(
                stopped_site_with_action["action"]["id"],
                factories.close_enforcement_payload(
                    compliance_note="Perimeter control verified"
                ),
                OFFICER_HEADERS,
            )
        )
        validate_success(_submit(site_id, "ESC-D-R2"))

        response = _release(site_id, "Fence installed")

        validate_error(response, ApiErrorId.ERR_ESC_PLAN_NOT_APPROVED.value, 422)

        site = fx.read_site(site_id)
        assert site["open_enforcement_count"] == 0, "the ledger guard is satisfied"
        assert site["field_status"] == "STOP_WORK", "the site is still stopped"

    def test_14_approving_a_stopped_site_does_not_restart_the_work_by_itself(
        self, stopped_site_with_action
    ):
        """The PRE_CONSTRUCTION cascade of an approval does not reach a stopped site.

        PRD: "`APPROVE` writes `APPROVED` into `plan_status` and, if and only if
        `field_status` is still `PRE_CONSTRUCTION`, additionally advances `field_status`
        to `ACTIVE_DISTURBANCE` — the point at which the site becomes eligible for
        erosion-control inspections."

        Design: Corner/state_machines/release_needs_a_quiet_ledger_and_an_approved_plan_at_the_same_time
        """
        site_id = stopped_site_with_action["site"]["id"]
        validate_success(
            api_client.close_enforcement_action(
                stopped_site_with_action["action"]["id"],
                factories.close_enforcement_payload(
                    compliance_note="Perimeter control verified"
                ),
                OFFICER_HEADERS,
            )
        )
        validate_success(_submit(site_id, "ESC-D-R2"))

        approved = validate_success(_review(site_id, "APPROVE", "Revised plan accepted"))

        assert approved["plan_status"] == "APPROVED", "the revised plan is approved"
        assert approved["field_status"] == "STOP_WORK", (
            "an approval does not lift a stop-work order"
        )

    def test_15_with_both_guards_satisfied_the_release_succeeds(
        self, stopped_site_with_action
    ):
        """The identical call clears the site and wipes the stop-work fields.

        PRD: "this requires `open_enforcement_count` to be 0 (otherwise
        `ERR_SITE_HAS_OPEN_ENFORCEMENT`) and `plan_status` to be `APPROVED` (otherwise
        `ERR_ESC_PLAN_NOT_APPROVED`), and it clears `stop_work_reason` to null and
        `open_deficiency_score` to 0."

        Design: Corner/state_machines/release_needs_a_quiet_ledger_and_an_approved_plan_at_the_same_time
        """
        site_id = stopped_site_with_action["site"]["id"]
        validate_success(
            api_client.close_enforcement_action(
                stopped_site_with_action["action"]["id"],
                factories.close_enforcement_payload(
                    compliance_note="Perimeter control verified"
                ),
                OFFICER_HEADERS,
            )
        )
        validate_success(_submit(site_id, "ESC-D-R2"))
        _release(site_id, "Fence installed")
        validate_success(_review(site_id, "APPROVE", "Revised plan accepted"))

        released = validate_success(_release(site_id, "Fence installed and inspected"))

        assert released["field_status"] == "ACTIVE_DISTURBANCE", "the work may resume"
        assert released["stop_work_reason"] is None, "the reason was cleared"
        assert released["open_deficiency_score"] == 0, "the open score was cleared"
        assert released["stop_work_count"] == 1, (
            "the historical order count is not undone by the release"
        )


class TestClosedSitesAreFrozenOnEveryDimension:
    """CLOSED outranks the plan dimension's own errors and the inspection rules."""

    @pytest.fixture
    def closed_site(self, active_program):
        """SITE-E approved, disturbed and then closed at the initial clock."""
        site = fx.setup_site_with_approved_plan(
            active_program["term_id"],
            esc_plan_reference="ESC-E",
            site_name="SITE-E",
            operator_name="Northgate Civil",
            disturbed_acres=1.50,
        )
        closed = validate_success(
            _close(site["id"], "Permanent vegetation established at 90 percent")
        )
        return {"term_id": active_program["term_id"], "site": closed}

    def test_16_closure_moves_only_the_field_dimension(self, closed_site):
        """The plan stays APPROVED and the closure instant is stamped.

        PRD: "Closing the file is the inspector's act, carrying a
        `final_stabilization_note`, and moves `field_status` from `ACTIVE_DISTURBANCE`
        to `CLOSED`." And: "Closure stamps `closed_at` from the logical clock and blocks
        any further erosion-control inspection on the site."

        Design: Corner/state_machines/closed_sites_reject_every_further_plan_field_and_inspection_operation
        """
        site = fx.read_site(closed_site["site"]["id"])

        assert site["field_status"] == "CLOSED", "the file is closed"
        assert site["closed_at"] is not None, "closure stamps its instant"
        assert site["plan_status"] == "APPROVED", "the plan dimension is untouched"

    @pytest.mark.parametrize(
        "operation",
        ["submit_esc_plan", "stop_work", "esc_inspection", "close_again"],
    )
    def test_17_every_further_operation_reports_the_closure(self, closed_site, operation):
        """One code answers for the plan track, the field track and the programme.

        PRD: "Submission is refused once the site's `field_status` is `CLOSED`, with
        `ERR_SITE_CLOSED`." And: "an erosion-control inspection additionally requires the
        subject site's `plan_status` to be `APPROVED` — otherwise
        `ERR_ESC_PLAN_NOT_APPROVED` — and its `field_status` to be `ACTIVE_DISTURBANCE`
        or `STOP_WORK`, refusing a site in `PRE_CONSTRUCTION` with
        `ERR_SITE_NOT_ACTIVE_DISTURBANCE` and a closed site with `ERR_SITE_CLOSED`."

        Design: Corner/state_machines/closed_sites_reject_every_further_plan_field_and_inspection_operation
        """
        site_id = closed_site["site"]["id"]
        calls = {
            "submit_esc_plan": lambda: _submit(site_id, "ESC-E-R2"),
            "stop_work": lambda: _stop(site_id, "Late complaint"),
            "esc_inspection": lambda: api_client.create_inspection(
                factories.esc_inspection_payload(
                    site_id, "2026-08-01", "2026-08-31", rainfall_trigger=False
                ),
                INSPECTOR_HEADERS,
            ),
            "close_again": lambda: _close(site_id, "Again"),
        }

        validate_error(calls[operation](), ApiErrorId.ERR_SITE_CLOSED.value, 409)

    def test_18_nothing_was_written_by_any_of_the_refused_operations(self, closed_site):
        """No inspection exists, and the closed row is exactly as closure left it.

        PRD: "Nothing is persisted when a request is rejected — no partial writes, no
        counter increments, no cascades."

        Design: Corner/state_machines/closed_sites_reject_every_further_plan_field_and_inspection_operation
        """
        site_id = closed_site["site"]["id"]
        _submit(site_id, "ESC-E-R2")
        _stop(site_id, "Late complaint")
        api_client.create_inspection(
            factories.esc_inspection_payload(
                site_id, "2026-08-01", "2026-08-31", rainfall_trigger=False
            ),
            INSPECTOR_HEADERS,
        )
        _close(site_id, "Again")

        _, meta = validate_paginated(
            api_client.list_inspections(INSPECTOR_HEADERS, {"construction_site_id": site_id})
        )
        assert meta["total_count"] == 0, (
            f"no inspection may exist on a closed site, got {meta['total_count']}"
        )

        site = fx.read_site(site_id)
        assert site["plan_status"] == "APPROVED", "the plan reference was not reopened"
        assert site["esc_plan_reference"] == "ESC-E", "the stored reference is unchanged"
        assert site["stop_work_count"] == 0, "no order was counted"
        assert site["field_status"] == "CLOSED", "the terminal state holds"
