"""A brand-new row refused because the parent it points at ended the wrong way."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_field_values,
    assert_fields_null,
    assert_unchanged,
)
from test_helpers.test_users import OFFICER_HEADERS

# The mirror-image score test: NOT_REPORTABLE under DEFECT needs a defect_score
# strictly below 5, so 2 and 3 are the scores a no-action determination requires.
NOT_REPORTABLE_DETERMINATION = {
    "determination": "NOT_REPORTABLE",
    "defect_score": 2,
    "risk_score": 3,
    "determination_note": (
        "Isolated misuse pattern; no defect in the weld and no unreasonable risk "
        "shown."
    ),
}


def _no_action_evaluation(api):
    """A DEFECT evaluation reviewed and then closed at NOT_REPORTABLE."""
    return fx.determined_evaluation_env(
        api, determination=NOT_REPORTABLE_DETERMINATION
    )


def _attempt_report(api, evaluation_id):
    """Draft a statutory report against one evaluation, returning the response."""
    return api.create_section_report(
        f.section_report_payload(evaluation_id), headers=OFFICER_HEADERS
    )


class TestSectionReportAgainstNoActionDetermination:
    """The payload is perfect; only the parent evaluation's outcome forbids it."""

    def test_drafting_a_report_on_a_no_action_determination_is_refused(self, api):
        """A no-action determination cannot carry a statutory report.

        The contract states: "The referenced evaluation must be in `status`
        `REPORTABLE`; anything else draws `ERR_EVALUATION_STATE_INVALID`." The
        refusal belongs to the parent because "Cross-entity state precondition —
        the state of a *different* row that the write depends on permits the
        operation, else that other entity's state error."

        Design: Difficulty/cross_entity_state_dependency/section_report_creation_blocked_by_not_reportable_evaluation
        """
        env = _no_action_evaluation(api)
        assert_field_values(env["evaluation"], status="NOT_REPORTABLE")

        response = _attempt_report(api, env["evaluation_id"])
        validate_error(response, "ERR_EVALUATION_STATE_INVALID", 409)

        rows, meta = validate_paginated(
            api.list_section_reports(
                {"reportability_evaluation_id": env["evaluation_id"]},
                headers=OFFICER_HEADERS,
            )
        )
        assert rows == [], f"the refused draft still wrote a report row: {rows}"
        assert meta["total_count"] == 0, meta

    def test_the_refused_draft_leaves_the_evaluation_and_its_clock_untouched(self, api):
        """No reporting clock starts, and the refusal mutates nothing.

        The contract states: "A `NOT_REPORTABLE` determination does none of this:
        `report_due_at` stays null, every incident keeps its existing `status`
        and `escalation_deadline_at`, `open_escalation_count` is untouched, and
        the model's `hazard_posture` is relaxed to `MONITORED`." Lateness is
        measured against that clock, since "Lateness is measured against the
        immutable `report_due_at` of the report's evaluation, reached through
        `reportability_evaluation_id`."

        Design: Difficulty/cross_entity_state_dependency/section_report_creation_blocked_by_not_reportable_evaluation
        """
        env = _no_action_evaluation(api)
        before = fx.get_evaluation(api, env["evaluation_id"])

        response = _attempt_report(api, env["evaluation_id"])
        validate_error(response, "ERR_EVALUATION_STATE_INVALID", 409)

        after = fx.get_evaluation(api, env["evaluation_id"])
        assert_field_values(
            after,
            status="NOT_REPORTABLE",
            defect_score=2,
            risk_score=3,
            escalation_breached=False,
        )
        assert_fields_null(after, "report_due_at")
        assert after["determined_at"] is not None, after
        assert_unchanged(
            before,
            after,
            "status",
            "report_due_at",
            "determined_at",
            "updated_at",
            "version",
        )

    def test_the_cluster_and_the_model_posture_stay_where_the_no_action_branch_left_them(
        self, api
    ):
        """No incident escalates and the model is relaxed, not frozen.

        The contract states: "A `NOT_REPORTABLE` determination does none of this:
        `report_due_at` stays null, every incident keeps its existing `status`
        and `escalation_deadline_at`, `open_escalation_count` is untouched, and
        the model's `hazard_posture` is relaxed to `MONITORED`." The registry
        agrees that "A reportability determination of `NOT_REPORTABLE` sets
        `hazard_posture` to `MONITORED`."

        Design: Difficulty/cross_entity_state_dependency/section_report_creation_blocked_by_not_reportable_evaluation
        """
        env = _no_action_evaluation(api)

        response = _attempt_report(api, env["evaluation_id"])
        validate_error(response, "ERR_EVALUATION_STATE_INVALID", 409)

        for incident in env["incidents"]:
            row = fx.get_incident(api, incident["id"])
            assert_field_values(
                row, status="CLUSTERED", hazard_pattern_id=env["pattern_id"]
            )
            assert_fields_null(row, "escalation_deadline_at")

        model = fx.get_product_model(api, env["model_id"])
        assert_field_values(
            model, open_escalation_count=0, hazard_posture="MONITORED"
        )
        assert model["hazard_posture"] != "FROZEN", model
