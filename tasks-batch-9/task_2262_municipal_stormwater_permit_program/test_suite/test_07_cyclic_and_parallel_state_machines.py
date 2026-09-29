"""Cyclic case tracing and the two independent dimensions of a construction site."""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import IDDE_HEADERS, INSPECTOR_HEADERS, OFFICER_HEADERS


class TestCaseTracingCycle:
    """The case returns to TRACING and the revisit is not a no-op."""

    @pytest.fixture
    def reopened_case(self):
        """A case traced, identified, reopened once and identified again."""
        program = fx.setup_active_program()
        outfall = program["outfalls"]["OF-01"]
        observation, case = fx.open_case_by_screening(
            outfall["id"], "2026-08-01T08:00:00Z"
        )
        validate_success(
            api_client.start_tracing(
                case["id"], factories.start_tracing_payload("DYE_TEST"), IDDE_HEADERS
            )
        )
        validate_success(
            api_client.identify_source(
                case["id"],
                factories.identify_source_payload(
                    source_description="Floor drain cross-connection at 14 Mill Rd",
                    responsible_party="Mill Road Laundry",
                ),
                IDDE_HEADERS,
            )
        )
        validate_success(
            api_client.reopen_tracing(
                case["id"],
                factories.reopen_tracing_payload(
                    reason="Dye did not resurface at the suspected connection"
                ),
                IDDE_HEADERS,
            )
        )
        validate_success(
            api_client.identify_source(
                case["id"],
                factories.identify_source_payload(
                    source_description="Grease interceptor overflow at 22 Mill Rd",
                    responsible_party="Mill Road Diner",
                ),
                IDDE_HEADERS,
            )
        )
        return {
            "program": program,
            "term_id": program["term_id"],
            "outfall": outfall,
            "observation": observation,
            "case_id": case["id"],
        }

    def test_01_the_first_trace_counts_one_attempt(self):
        """Starting tracing records the method and counts the attempt.

        PRD: "The transition records that method on the case and increments
        `tracing_attempt_count` by one."

        Design: Difficulty/non_linear_state_machine/illicit_discharge_case_reopen_cycle_clears_source_and_counts_attempts
        """
        program = fx.setup_active_program()
        _, case = fx.open_case_by_screening(program["outfalls"]["OF-01"]["id"])
        assert case["status"] == "OPEN", "the screening cascade opens the case"
        assert case["tracing_attempt_count"] == 0, "no trace has been attempted yet"

        traced = validate_success(
            api_client.start_tracing(
                case["id"], factories.start_tracing_payload("DYE_TEST"), IDDE_HEADERS
            )
        )

        assert traced["status"] == "TRACING", "the case moves from OPEN to TRACING"
        assert traced["trace_method"] == "DYE_TEST", "the method used is recorded"
        assert traced["tracing_attempt_count"] == 1, "the first attempt is counted"
        assert traced["reopen_count"] == 0, "a first trace is not a reopen"

    def test_02_the_second_reopen_reenters_tracing_and_clears_the_source(
        self, reopened_case
    ):
        """The third visit to TRACING carries no source and counts two reopens.

        PRD: "A successful reopen clears both `source_description` and
        `responsible_party` back to null and increments both `reopen_count` and
        `tracing_attempt_count` by one."

        Design: Difficulty/non_linear_state_machine/illicit_discharge_case_reopen_cycle_clears_source_and_counts_attempts
        """
        reopened = validate_success(
            api_client.reopen_tracing(
                reopened_case["case_id"],
                factories.reopen_tracing_payload(
                    reason="Second source hypothesis also failed smoke testing"
                ),
                IDDE_HEADERS,
            )
        )

        assert reopened["status"] == "TRACING", "the case re-enters TRACING"
        assert reopened["reopen_count"] == 2, "this is the second reopen"
        assert reopened["tracing_attempt_count"] == 3, (
            "one original trace plus two reopens is three attempts"
        )
        assert reopened["source_description"] is None, (
            "a reopen clears the source narrative"
        )
        assert reopened["responsible_party"] is None, (
            "a reopen clears the responsible party"
        )

    def test_03_the_cycle_never_detaches_the_case_from_its_origin(self, reopened_case):
        """The case still points at the screening that opened it.

        PRD: "A `SUSPECT` result moves `screening_status` from either
        `NOT_SCREENED` or `CLEAR` to `SUSPECT` and additionally opens a case: the
        server creates an **illicit discharge case** in `OPEN` whose `outfall_id`
        is this outfall and whose `origin_observation_id` is the new observation,
        stamps the case's `opened_at` from the logical clock, raises the outfall's
        `open_case_count` by one, then recomputes the `ILLICIT_DISCHARGE` control
        measure's `open_case_count` and `goal_status`, the term's posture, and —
        where the posture moved and the observation falls inside a closed
        reporting window — the annual report's return to `DRAFT`."

        Design: Difficulty/non_linear_state_machine/illicit_discharge_case_reopen_cycle_clears_source_and_counts_attempts
        """
        validate_success(
            api_client.reopen_tracing(
                reopened_case["case_id"],
                factories.reopen_tracing_payload(reason="Smoke testing also failed"),
                IDDE_HEADERS,
            )
        )

        case = fx.read_case(reopened_case["case_id"])
        assert case["origin_observation_id"] == reopened_case["observation"]["id"], (
            "the case stays bound to the screening that opened it"
        )
        assert case["outfall_id"] == reopened_case["outfall"]["id"], (
            "the case stays bound to its outfall"
        )

    def test_04_the_loop_does_not_move_the_outfall_or_measure_census(self, reopened_case):
        """One open case remains one open case however many times it loops.

        PRD: "For the `ILLICIT_DISCHARGE` measure, if `open_case_count` is greater
        than three, the result is `BEHIND`." And: "If `last_progress_reported_at`
        is null and `measurable_goal_actual` is 0, the result is `PENDING`."

        Design: Difficulty/non_linear_state_machine/illicit_discharge_case_reopen_cycle_clears_source_and_counts_attempts
        """
        validate_success(
            api_client.reopen_tracing(
                reopened_case["case_id"],
                factories.reopen_tracing_payload(reason="Smoke testing also failed"),
                IDDE_HEADERS,
            )
        )

        outfall = fx.read_outfall(reopened_case["outfall"]["id"])
        assert outfall["screening_status"] == "SUSPECT", (
            "the outfall stays suspect while its case is open"
        )
        assert outfall["open_case_count"] == 1, "the loop opens no further case"

        measure = fx.read_measure(
            reopened_case["program"]["measures"]["ILLICIT_DISCHARGE"]["id"]
        )
        assert measure["open_case_count"] == 1, (
            "the measure sees the same single open case"
        )
        assert measure["goal_status"] == "PENDING", (
            "with no progress reported and one open case the measure is pending"
        )


class TestSitePlanAndFieldDimensions:
    """Plan review cycles while the field condition is driven separately."""

    @pytest.fixture
    def resubmitted_site(self):
        """A 1.50-acre site whose plan was returned once and then approved."""
        program = fx.setup_active_program()
        site = fx.create_site(
            program["term_id"],
            site_name="SITE-C",
            operator_name="Cedar Grade Works",
            disturbed_acres=1.50,
        )
        validate_success(
            api_client.submit_esc_plan(
                site["id"], factories.submit_esc_plan_payload("ESC-C-1"), INSPECTOR_HEADERS
            )
        )
        validate_success(
            api_client.esc_review(
                site["id"],
                factories.esc_review_payload(
                    "RETURN", review_notes="Missing inlet protection detail"
                ),
                INSPECTOR_HEADERS,
            )
        )
        validate_success(
            api_client.submit_esc_plan(
                site["id"], factories.submit_esc_plan_payload("ESC-C-2"), INSPECTOR_HEADERS
            )
        )
        approved = validate_success(
            api_client.esc_review(
                site["id"],
                factories.esc_review_payload(
                    "APPROVE", review_notes="Inlet protection detail added"
                ),
                INSPECTOR_HEADERS,
            )
        )
        return {
            "program": program,
            "term_id": program["term_id"],
            "site": approved,
        }

    def test_05_a_returned_plan_leaves_the_field_dimension_where_it_was(self):
        """RETURN moves only the plan dimension.

        PRD: "`RETURN` writes `RETURNED` into `plan_status` and leaves
        `field_status` untouched, so the operator can revise and resubmit."

        Design: Difficulty/non_linear_state_machine/construction_site_plan_and_field_dimensions_advance_independently
        """
        program = fx.setup_active_program()
        site = fx.create_site(
            program["term_id"],
            site_name="SITE-C",
            operator_name="Cedar Grade Works",
            disturbed_acres=1.50,
        )
        assert site["plan_status"] == "SUBMITTED", "a new site starts at SUBMITTED"
        assert site["field_status"] == "PRE_CONSTRUCTION", (
            "a new site starts in PRE_CONSTRUCTION"
        )

        validate_success(
            api_client.submit_esc_plan(
                site["id"], factories.submit_esc_plan_payload("ESC-C-1"), INSPECTOR_HEADERS
            )
        )
        returned = validate_success(
            api_client.esc_review(
                site["id"],
                factories.esc_review_payload(
                    "RETURN", review_notes="Missing inlet protection detail"
                ),
                INSPECTOR_HEADERS,
            )
        )

        assert returned["plan_status"] == "RETURNED", "the plan dimension moved"
        assert returned["field_status"] == "PRE_CONSTRUCTION", (
            "the field dimension did not move"
        )
        assert returned["plan_review_round"] == 1, "the first review round is counted"

    def test_06_the_second_review_round_approves_and_opens_the_field(
        self, resubmitted_site
    ):
        """Approval on the second round advances the field dimension too.

        PRD: "`APPROVE` writes `APPROVED` into `plan_status` and, if and only if
        `field_status` is still `PRE_CONSTRUCTION`, additionally advances
        `field_status` to `ACTIVE_DISTURBANCE` — the point at which the site
        becomes eligible for erosion-control inspections."

        Design: Difficulty/non_linear_state_machine/construction_site_plan_and_field_dimensions_advance_independently
        """
        site = resubmitted_site["site"]

        assert site["plan_status"] == "APPROVED", "the second round approved the plan"
        assert site["plan_review_round"] == 2, "two review rounds have been counted"
        assert site["esc_plan_reference"] == "ESC-C-2", (
            "the resubmitted reference overwrote the first one"
        )
        assert site["field_status"] == "ACTIVE_DISTURBANCE", (
            "approval opened the field dimension"
        )

    def test_07_an_operator_stop_work_leaves_the_approved_plan_untouched(
        self, resubmitted_site
    ):
        """The combined state APPROVED plus STOP_WORK is reachable.

        PRD: "Stop-work authority belongs to the `EnforcementOfficer`, who
        supplies a `reason` and drives `field_status` from `ACTIVE_DISTURBANCE` to
        `STOP_WORK` while the term is `ACTIVE`, recording that reason in
        `stop_work_reason`, incrementing `stop_work_count` by one, and leaving
        `plan_status` untouched."

        Design: Difficulty/non_linear_state_machine/construction_site_plan_and_field_dimensions_advance_independently
        """
        stopped = validate_success(
            api_client.stop_work(
                resubmitted_site["site"]["id"],
                factories.stop_work_payload(
                    reason="Sediment discharge observed leaving the site"
                ),
                OFFICER_HEADERS,
            )
        )

        assert stopped["field_status"] == "STOP_WORK", "the field dimension moved"
        assert stopped["plan_status"] == "APPROVED", (
            "the plan dimension is untouched by a stop-work order"
        )
        assert stopped["plan_review_round"] == 2, "the review rounds are untouched"
        assert stopped["stop_work_count"] == 1, "the order is counted"
        assert stopped["stop_work_reason"] == "Sediment discharge observed leaving the site", (
            "the officer's reason is recorded"
        )

    def test_08_a_manual_stop_work_carries_no_score_and_no_penalty(
        self, resubmitted_site
    ):
        """An operator order is not an inspection and not an enforcement action.

        PRD: "On creation the server derives `post_construction_control_required`,
        setting it true exactly when `disturbed_acres` is 2.00 or more, and
        initialises `plan_review_round` and `stop_work_count` to 0,
        `open_deficiency_score` to 0, `open_enforcement_count` to 0, and
        `esc_plan_reference`, `stop_work_reason` and `closed_at` to null."

        Design: Difficulty/non_linear_state_machine/construction_site_plan_and_field_dimensions_advance_independently
        """
        validate_success(
            api_client.stop_work(
                resubmitted_site["site"]["id"],
                factories.stop_work_payload(
                    reason="Sediment discharge observed leaving the site"
                ),
                OFFICER_HEADERS,
            )
        )

        site = fx.read_site(resubmitted_site["site"]["id"])
        assert site["open_deficiency_score"] == 0, (
            "an operator stop-work carries no inspection score"
        )
        assert site["open_enforcement_count"] == 0, (
            "a stop-work order is not itself an enforcement action"
        )

        measure = fx.read_measure(
            resubmitted_site["program"]["measures"]["CONSTRUCTION_RUNOFF"]["id"]
        )
        assert measure["enforcement_count"] == 0, (
            "the runoff measure sees no enforcement action"
        )

        term = fx.read_term(resubmitted_site["term_id"])
        assert term["total_assessed_penalty_cents"] == 0, (
            "no money is assessed by a stop-work order"
        )
