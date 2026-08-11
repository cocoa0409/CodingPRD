"""CPM forward/backward pass and critical path identification (PRD §3.3)."""
from datetime import datetime

from test_helpers import (
    create_project,
    create_draft_schedule_with_activities,
    submit_schedule,
    get_activity,
    get_schedule_version,
)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestLinearChain:
    def test_cpm_forward_pass_linear_chain(self, api):
        """PRD §3.3: "An activity's `early_start` is the largest of its candidates,
        or the version's `data_date` when it has no predecessors, and its
        `early_finish` is its `early_start` plus its `remaining_duration_days`".
        PRD §3.3: "The pass stamps `is_critical` on each activity and aggregates
        `critical_path_activity_count` and `projected_finish_date` — the maximum
        early finish over the terminal activities — onto the version."

        Design: Corner/calculations/cpm_forward_pass_linear_chain
        """
        project = create_project()
        version, ids = create_draft_schedule_with_activities(
            project["id"],
            data_date="2026-05-01T00:00:00Z",
            activity_durations=[("A", 5), ("B", 7)],
            relationships=[(0, 1, "FS", 0)],
        )
        submit_schedule(project["id"], version["id"])
        a = get_activity(project["id"], version["id"], ids[0])
        b = get_activity(project["id"], version["id"], ids[1])
        # A: ES 2026-05-01, EF +5d; B starts at A's finish, EF +7d → 2026-05-13.
        assert _parse(a["early_start"]) == _parse("2026-05-01T00:00:00Z")
        assert _parse(a["early_finish"]) == _parse("2026-05-06T00:00:00Z")
        assert _parse(b["early_start"]) == _parse("2026-05-06T00:00:00Z")
        assert _parse(b["early_finish"]) == _parse("2026-05-13T00:00:00Z")
        assert a["total_float_days"] == 0
        assert b["total_float_days"] == 0
        computed = get_schedule_version(project["id"], version["id"])
        assert _parse(computed["projected_finish_date"]) == _parse("2026-05-13T00:00:00Z")
        assert computed["critical_path_activity_count"] == 2


class TestParallelPaths:
    def test_cpm_float_on_parallel_paths(self, api):
        """PRD §3.3: "An activity's `late_finish` is the smallest of its candidates,
        or — when it has no successors — the project horizon, defined as the maximum
        `early_finish` among the terminal activities." and "Finally,
        `total_float_days` is the `late_finish` minus the `early_finish` in whole
        calendar days, and a zero float marks an activity as critical."

        Design: Corner/calculations/cpm_float_on_parallel_paths
        """
        project = create_project()
        # A(10d) and B(5d) run in parallel from the data date and converge on M(1d).
        version, ids = create_draft_schedule_with_activities(
            project["id"],
            data_date="2026-05-01T00:00:00Z",
            activity_durations=[("A", 10), ("B", 5), ("M", 1)],
            relationships=[(0, 2, "FS", 0), (1, 2, "FS", 0)],
        )
        submit_schedule(project["id"], version["id"])
        a = get_activity(project["id"], version["id"], ids[0])
        b = get_activity(project["id"], version["id"], ids[1])
        m = get_activity(project["id"], version["id"], ids[2])
        assert a["total_float_days"] == 0 and a["is_critical"] is True
        assert b["total_float_days"] == 5, (
            "B finishes 5 days before A, so B carries 5 days of total float"
        )
        assert b["is_critical"] is False
        assert m["total_float_days"] == 0 and m["is_critical"] is True
        computed = get_schedule_version(project["id"], version["id"])
        assert computed["critical_path_activity_count"] == 2


class TestTiedSuccessors:
    def test_tied_terminal_successors_all_critical(self, api):
        """PRD §3.3: "The default `LONGEST_PATH` variant — used when no external
        completion constraint exists — treats every activity whose `total_float_days`
        is zero as critical." and "Finally, `total_float_days` is the `late_finish`
        minus the `early_finish` in whole calendar days".

        Design: Difficulty/combinatorial_formula/cpm_pass_rounding_and_tie_break_mode_b
        """
        project = create_project()
        # ROOT(5d) fans out to S1(5d) and S2(5d); both successors share one EF.
        version, ids = create_draft_schedule_with_activities(
            project["id"],
            data_date="2026-05-01T00:00:00Z",
            activity_durations=[("ROOT", 5), ("S1", 5), ("S2", 5)],
            relationships=[(0, 1, "FS", 0), (0, 2, "FS", 0)],
        )
        submit_schedule(project["id"], version["id"])
        root = get_activity(project["id"], version["id"], ids[0])
        s1 = get_activity(project["id"], version["id"], ids[1])
        s2 = get_activity(project["id"], version["id"], ids[2])
        assert root["total_float_days"] == 0, "critical root"
        assert s1["total_float_days"] == 0 and s2["total_float_days"] == 0, (
            "equal-EF terminal successors both land at the horizon — no drift"
        )

    def test_tied_terminal_successors_critical_count_and_finish(self, api):
        """PRD §3.3: "The default `LONGEST_PATH` variant — used when no external
        completion constraint exists — treats every activity whose `total_float_days`
        is zero as critical." and "The pass stamps `is_critical` on each activity and
        aggregates `critical_path_activity_count` and `projected_finish_date` — the
        maximum early finish over the terminal activities — onto the version."

        Design: Difficulty/combinatorial_formula/cpm_pass_rounding_and_tie_break_mode_b
        """
        project = create_project()
        version, ids = create_draft_schedule_with_activities(
            project["id"],
            data_date="2026-05-01T00:00:00Z",
            activity_durations=[("ROOT", 5), ("S1", 5), ("S2", 5)],
            relationships=[(0, 1, "FS", 0), (0, 2, "FS", 0)],
        )
        submit_schedule(project["id"], version["id"])
        computed = get_schedule_version(project["id"], version["id"])
        # All three activities sit at zero float; both successors finish 2026-05-11.
        assert computed["critical_path_activity_count"] == 3
        assert _parse(computed["projected_finish_date"]) == _parse("2026-05-11T00:00:00Z")
        for aid in ids:
            assert get_activity(project["id"], version["id"], aid)["is_critical"] is True
