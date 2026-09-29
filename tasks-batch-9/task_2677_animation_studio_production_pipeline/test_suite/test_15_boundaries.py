"""Boundary checks: the escalation threshold latch and the first version index in a group."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_DELIVERABLE_VERSION_CONFLICT
from test_helpers.assertions import assert_version_label
from test_helpers.constants import (
    DELIVERABLE_DRAFT,
    DELIVERABLE_PROXY_MP4,
    DELIVERABLE_QC_FAILED,
    DELIVERABLE_SUBMITTED,
    SHOT_IN_PRODUCTION,
    TASK_RETAKE,
)
from test_helpers.test_users import PRODUCTION_MANAGER_HEADERS, SUPERVISOR_HEADERS


def _active_show(client, **overrides):
    payload = {
        "title": "Aurora Drift",
        "production_code": "AD01",
        "budget_cents": 100000000,
        "render_allowance_cents": 5000000,
        "contingency_pct": 0.10,
        "gate_types": ["SCRIPT"],
    }
    payload.update(overrides)
    return fx.active_production(client, **payload)


def _shot_with_assigned_layout(client, production_id):
    shot = fx.create_shot(
        client,
        production_id,
        shot_code="AD01_010_0010",
        sequence_code="010",
        frame_count=120,
        budget_cents=1000000,
        planned_start_at="2026-08-01T00:00:00Z",
        planned_finish_at="2026-09-30T00:00:00Z",
    )
    task = fx.task_for_stage(client, shot["id"], "LAYOUT")
    fx.assign_task(client, task["id"])
    return shot, task


def _retake_once(client, task_id):
    """Submit the task and have the supervisor send it back."""
    fx.submit_task(client, task_id)
    return validate_success(
        client.decide_stage_task(
            task_id, f.task_decision_payload("RETAKE"), SUPERVISOR_HEADERS
        )
    )


class TestEscalationThreshold:
    def test_the_second_retake_does_not_escalate_and_the_third_one_does(self, client):
        """The comparison is inclusive at three, so revision 2 reads escalated false and
        revision 3 latches the task, the shot and the show's at-risk count together.

        PRD: "The task's `revision_count` is increased by 1, and `escalated` is set to true
        when `revision_count` has reached **three or more** — the comparison is inclusive, so
        the third retake escalates the task and the second does not."
        PRD: "When `escalated` flips to true, the owning shot's `escalation_flag` becomes true
        and the production's `at_risk_shot_count` is recomputed."

        Design: Difficulty/boundary_precision_check/retake_escalation_fires_at_exactly_third_revision
        """
        production = _active_show(client)
        shot, task = _shot_with_assigned_layout(client, production["id"])

        first = _retake_once(client, task["id"])
        assert first["revision_count"] == 1
        assert first["escalated"] is False

        second = _retake_once(client, task["id"])
        assert second["revision_count"] == 2
        assert second["escalated"] is False, "threshold minus one must not escalate"
        at_two_shot = fx.read_shot(client, shot["id"])
        assert at_two_shot["escalation_flag"] is False
        assert at_two_shot["retake_count"] == 2
        assert fx.read_production(client, production["id"])["at_risk_shot_count"] == 0

        third = _retake_once(client, task["id"])
        assert third["revision_count"] == 3
        assert third["escalated"] is True, "exactly at the threshold, the comparison is >="
        assert third["status"] == TASK_RETAKE

        at_three_shot = fx.read_shot(client, shot["id"])
        assert at_three_shot["escalation_flag"] is True
        assert at_three_shot["retake_count"] == 3
        assert at_three_shot["status"] == SHOT_IN_PRODUCTION

        at_three_production = fx.read_production(client, production["id"])
        assert at_three_production["at_risk_shot_count"] == 1
        assert at_three_production["total_retake_count"] == 3

    def test_a_fourth_retake_counts_the_shot_once_and_an_approval_never_clears_it(self, client):
        """Past the threshold the latch stops moving: revision 4 leaves at_risk_shot_count at
        1 rather than double-counting the shot, and a later approval does not clear the flag.

        PRD: "Once true, `escalated` latches: a later approval never clears it, and
        `revision_count` never resets."
        PRD: "Independently of escalation, every retake recomputes the shot's `retake_count`
        as the sum of `revision_count` over its five tasks, and the production's
        `total_retake_count` as the sum of `retake_count` over its shots."

        Design: Difficulty/boundary_precision_check/retake_escalation_fires_at_exactly_third_revision
        """
        production = _active_show(client)
        shot, task = _shot_with_assigned_layout(client, production["id"])
        for _ in range(3):
            _retake_once(client, task["id"])
        assert fx.read_production(client, production["id"])["at_risk_shot_count"] == 1

        fourth = _retake_once(client, task["id"])
        assert fourth["revision_count"] == 4
        assert fourth["escalated"] is True, "already latched"

        at_four = fx.read_production(client, production["id"])
        assert at_four["at_risk_shot_count"] == 1, "the shot is counted once, not twice"
        assert at_four["total_retake_count"] == 4
        assert fx.read_shot(client, shot["id"])["retake_count"] == 4

        fx.submit_task(client, task["id"])
        approved = fx.approve_task(client, task["id"])
        assert approved["escalated"] is True, "an approval never clears the latch"
        assert approved["revision_count"] == 4
        assert fx.read_shot(client, shot["id"])["escalation_flag"] is True
        assert fx.read_production(client, production["id"])["at_risk_shot_count"] == 1


def _show_with_one_shot(client):
    production = _active_show(client, approved_color_spaces=["ACEScg", "Rec709"])
    shot = fx.create_shot(
        client,
        production["id"],
        shot_code="AD01_010_0010",
        sequence_code="010",
        frame_count=120,
        budget_cents=1000000,
        planned_start_at="2026-08-01T00:00:00Z",
        planned_finish_at="2026-09-30T00:00:00Z",
    )
    return production, shot


class TestFirstDeliverableVersion:
    def test_the_first_row_of_an_empty_group_is_v01_and_the_padding_survives_v02(self, client):
        """An empty group opens at index 1 with the exact three-character label v01, and after
        a QC failure frees the group the next row is index 2 labelled v02.

        PRD: "A new deliverable's `version_index` is one more than the number of rows already
        in its group, and **every** row counts toward that number regardless of status —
        including rows that are `SUPERSEDED` or `QC_FAILED` — so the index never decreases and
        never reuses a value."
        PRD: "`version_label` is the letter `v` followed by the index padded with leading
        zeros to at least two digits: the first deliverable of an empty group is `v01`, the
        second is `v02`, and the hundredth is `v100`."
        PRD: "`FAIL` moves it `SUBMITTED → QC_FAILED` and **requires** `qc_note` to be present
        and non-empty, otherwise `ERR_VALIDATION`; because a failed row is no longer in flight,
        the group is freed and a fresh version may be created."

        Design: Difficulty/boundary_precision_check/first_deliverable_in_empty_group_gets_v01
        """
        production, shot = _show_with_one_shot(client)

        first = fx.create_deliverable(
            client,
            production["id"],
            shot_id=shot["id"],
            deliverable_type=DELIVERABLE_PROXY_MP4,
            color_space="Rec709",
        )
        assert first["version_index"] == 1
        assert first["version_label"] == "v01", "not v1, not v0 and not v00"
        assert len(first["version_label"]) == 3
        assert first["status"] == DELIVERABLE_DRAFT
        assert first["qc_note"] is None
        assert_version_label(first["version_label"], 1)

        submitted = fx.submit_deliverable(client, first["id"])
        assert submitted["status"] == DELIVERABLE_SUBMITTED

        failed = validate_success(
            client.qc_decide_deliverable(
                first["id"],
                {"decision": "FAIL", "qc_note": "Burn-in is missing."},
                SUPERVISOR_HEADERS,
            )
        )
        assert failed["status"] == DELIVERABLE_QC_FAILED
        assert failed["qc_note"] == "Burn-in is missing."

        second = fx.create_deliverable(
            client,
            production["id"],
            shot_id=shot["id"],
            deliverable_type=DELIVERABLE_PROXY_MP4,
            color_space="Rec709",
        )
        assert second["version_index"] == 2
        assert second["version_label"] == "v02"
        assert_version_label(second["version_label"], 2)
        assert second["status"] == DELIVERABLE_DRAFT

    def test_the_group_admits_one_in_flight_row_and_a_null_shot_id_is_its_own_group(self, client):
        """A third create while v02 is still DRAFT is refused, yet the same production and type
        with no shot_id opens a separate group back at v01.

        PRD: "If any row of the target group is already in `DRAFT` or `SUBMITTED`, the create is
        refused with `ERR_DELIVERABLE_VERSION_CONFLICT`."
        PRD: "Versioning is per **group**, and the grouping key is the combination of
        `production_id`, `deliverable_type` and `shot_id`, where a null `shot_id` matches only
        other rows with a null `shot_id`."

        Design: Difficulty/boundary_precision_check/first_deliverable_in_empty_group_gets_v01
        """
        production, shot = _show_with_one_shot(client)

        first = fx.create_deliverable(
            client,
            production["id"],
            shot_id=shot["id"],
            deliverable_type=DELIVERABLE_PROXY_MP4,
            color_space="Rec709",
        )
        fx.submit_deliverable(client, first["id"])
        validate_success(
            client.qc_decide_deliverable(
                first["id"],
                {"decision": "FAIL", "qc_note": "Burn-in is missing."},
                SUPERVISOR_HEADERS,
            )
        )
        second = fx.create_deliverable(
            client,
            production["id"],
            shot_id=shot["id"],
            deliverable_type=DELIVERABLE_PROXY_MP4,
            color_space="Rec709",
        )
        assert second["status"] == DELIVERABLE_DRAFT

        current_version = fx.read_production(client, production["id"])["version"]
        validate_error(
            client.create_deliverable(
                f.deliverable_payload(
                    production["id"],
                    current_version,
                    shot_id=shot["id"],
                    deliverable_type=DELIVERABLE_PROXY_MP4,
                    color_space="Rec709",
                ),
                PRODUCTION_MANAGER_HEADERS,
            ),
            ERR_DELIVERABLE_VERSION_CONFLICT,
            409,
        )

        production_wide = fx.create_deliverable(
            client,
            production["id"],
            deliverable_type=DELIVERABLE_PROXY_MP4,
            color_space="Rec709",
        )
        assert production_wide["shot_id"] is None
        assert production_wide["version_index"] == 1, (
            "a null shot_id numbers independently of the shot-scoped group"
        )
        assert production_wide["version_label"] == "v01"
        assert fx.read_deliverable(client, second["id"])["version_index"] == 2
