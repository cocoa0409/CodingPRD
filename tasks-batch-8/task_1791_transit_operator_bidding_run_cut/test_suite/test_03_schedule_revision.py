"""Mid-pick service change: the PICKING -> RUNS_CUT cycle and its cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    adjudicate,
    award_run_to_operator,
    create_operator,
    create_picking_period,
    create_run_piece,
    get_period,
    get_run,
    list_bids,
    schedule_revision_payload,
    submit_bid,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

SO = TEST_USERS["scheduling_officer_headers"]


def _new_run_spec(run_number="R3", service_date="2026-09-09"):
    return {
        "run_number": run_number,
        "service_date": service_date,
        "pieces": [create_run_piece(300, 700, 400)],
    }


class TestPickingToRunsCutCycle:
    def _setup_picking_with_award_and_posted(self, api):
        """PICKING period: op1 awarded R1; R2 still POSTED."""
        period, runs = create_picking_period(
            [{"run_number": "R1", "service_date": "2026-09-07"},
             {"run_number": "R2", "service_date": "2026-09-08"}]
        )
        op1 = create_operator(employee_number="E1", full_name="Op One", hire_date="2000-01-01")
        award_run_to_operator(period["id"], op1["id"], runs[0]["id"])
        return period, runs, op1

    def test_revision_cycles_period_back_to_runs_cut(self, api):
        """PRD §3.6: "The revision increments the period's `schedule_revision`
        by one"
        PRD §3.6: "The pick then restarts on the augmented pool:
        `picked_through_rank` resets to 0, the period returns from `PICKING` to
        `RUNS_CUT`, and bid awards made before the revision stay awarded."

        Design: Difficulty/non_linear_state_machine/signup_period_picking_to_runs_cut_cycle
        """
        period, runs, op1 = self._setup_picking_with_award_and_posted(api)
        assert get_period(period["id"])["status"] == "PICKING"
        resp = api.create_schedule_revision(
            period["id"], schedule_revision_payload([_new_run_spec("R3")]), SO
        )
        validate_success(resp, expected_status=201)
        after = get_period(period["id"])
        assert after["status"] == "RUNS_CUT"
        assert after["schedule_revision"] == 2
        assert after["picked_through_rank"] == 0

    def test_revision_preserves_awards_and_withdraws_stale_posted(self, api):
        """PRD §3.6: "every run of the prior revision still `POSTED` moves to
        `WITHDRAWN`, and every `SUBMITTED` bid entry referencing a withdrawn
        run moves to `WITHDRAWN` with it, while runs already `AWARDED` are left
        untouched."

        Design: Difficulty/non_linear_state_machine/signup_period_picking_to_runs_cut_cycle
        """
        period, runs, op1 = self._setup_picking_with_award_and_posted(api)
        resp = api.create_schedule_revision(
            period["id"], schedule_revision_payload([_new_run_spec("R3")]), SO
        )
        validate_success(resp, expected_status=201)
        assert get_run(runs[0]["id"])["status"] == "AWARDED"  # survives revision
        assert get_run(runs[1]["id"])["status"] == "WITHDRAWN"  # stale POSTED


class TestScheduleRevisionBidCascade:
    def _setup_picking_with_bid_on_second_run(self, api):
        """PICKING period, no awards yet; operator holds one SUBMITTED bid on
        the second run."""
        period, runs = create_picking_period(
            [{"run_number": "R1", "service_date": "2026-09-07"},
             {"run_number": "R2", "service_date": "2026-09-08"}]
        )
        operator = create_operator(employee_number="E1", full_name="Op One", hire_date="2000-01-01")
        bid = submit_bid(period["id"], operator["id"], runs[1]["id"], preference_rank=1)
        return period, runs, operator, bid

    def test_revision_withdraws_bids_on_withdrawn_runs(self, api):
        """PRD §3.6: "every run of the prior revision still `POSTED` moves to
        `WITHDRAWN`, and every `SUBMITTED` bid entry referencing a withdrawn
        run moves to `WITHDRAWN` with it, while runs already `AWARDED` are left
        untouched."

        Design: Difficulty/transitive_cascade/schedule_revision_two_hop_bid_cascade
        """
        period, runs, operator, bid = self._setup_picking_with_bid_on_second_run(api)
        resp = api.create_schedule_revision(
            period["id"], schedule_revision_payload([_new_run_spec("R9")]), SO
        )
        validate_success(resp, expected_status=201)
        assert get_run(runs[1]["id"])["status"] == "WITHDRAWN"
        bids = list_bids(period["id"], operator_id=operator["id"])
        by_id = {b["id"]: b for b in bids}
        assert by_id[bid["id"]]["status"] == "WITHDRAWN"

    def test_revision_cascade_leaves_bid_on_surviving_pool_consistent(self, api):
        """PRD §3.6: "every run of the prior revision still `POSTED` moves to
        `WITHDRAWN`, and every `SUBMITTED` bid entry referencing a withdrawn
        run moves to `WITHDRAWN` with it, while runs already `AWARDED` are left
        untouched."
        PRD §3.6: "The `new_runs` are then cut under the new revision —
        subject to the same piece-geometry rules as initial creation (§3.2) —
        validated by the spread rule so that each new run lands in `VALIDATED`
        or `WITHDRAWN`, and every `VALIDATED` new run is posted immediately."

        Design: Difficulty/transitive_cascade/schedule_revision_two_hop_bid_cascade
        """
        period, runs, operator, bid = self._setup_picking_with_bid_on_second_run(api)
        resp = api.create_schedule_revision(
            period["id"], schedule_revision_payload([_new_run_spec("R9")]), SO
        )
        validate_success(resp, expected_status=201)
        # Both prior POSTED runs withdraw; the only bid (on R2) withdraws.
        assert get_run(runs[0]["id"])["status"] == "WITHDRAWN"
        assert get_run(runs[1]["id"])["status"] == "WITHDRAWN"
        bids = list_bids(period["id"], operator_id=operator["id"])
        assert all(b["status"] == "WITHDRAWN" for b in bids)
        # The new run is posted immediately under the new revision.
        from test_helpers import api_client
        from test_helpers import get_success_data
        new_runs = get_success_data(
            api_client.list_runs(period["id"], SO, params={"schedule_revision": 2})
        )
        assert len(new_runs) == 1
        assert new_runs[0]["run_number"] == "R9"
        assert new_runs[0]["status"] == "POSTED"
