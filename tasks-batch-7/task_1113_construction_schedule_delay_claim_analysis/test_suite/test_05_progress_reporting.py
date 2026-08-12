"""Monthly progress reporting: update lifecycle, entry invariants, and the
approval cascade that folds actuals into the schedule (PRD §3.4)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_progress_entry_payload,
    create_progress_update,
    add_progress_entry,
    submit_progress_update,
    approve_progress_update,
    setup_accepted_update,
    get_activity,
)


def _project_with_accepted_update():
    return setup_accepted_update(
        contract_completion_date="2026-05-15T00:00:00Z",
        update_activity_durations=[("A", 10)],
        update_data_date="2026-05-08T00:00:00Z",
    )


class TestProgressUpdateLifecycle:
    def test_progress_update_initial_state_draft(self, api, contractor_headers):
        """PRD §3.4: "The `ContractorScheduler` creates one by supplying the
        `reporting_period_end` — the month-end cutoff — and an opaque
        `submitted_by_contractor_user_id`; the update begins in `DRAFT`."

        Design: Corner/state_machines/progress_update_initial_state_draft
        """
        ctx = _project_with_accepted_update()
        pid, vid = ctx["project"]["id"], ctx["update"]["id"]
        resp = api.create_progress_update(
            pid,
            vid,
            {
                "reporting_period_end": "2026-05-08T00:00:00Z",
                "submitted_by_contractor_user_id": "u1",
            },
            contractor_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"


class TestProgressEntryInvariants:
    def test_progress_entry_inconsistent_100_percent(self, api, contractor_headers):
        """PRD §3.4: "Four progress invariants are enforced when an entry is
        recorded, and a violation of any of them is rejected with
        `ERR_INVALID_PROGRESS`" — among them "`percent_complete` must be exactly 100
        if and only if `remaining_duration_days` is zero".

        Design: Corner/errors/progress_entry_inconsistent_100_percent
        """
        ctx = _project_with_accepted_update()
        pid, vid = ctx["project"]["id"], ctx["update"]["id"]
        activity_id = ctx["update_activity_ids"][0]
        pu = create_progress_update(pid, vid)
        resp = api.create_progress_entry(
            pid,
            vid,
            pu["id"],
            create_progress_entry_payload(
                activity_id,
                percent_complete=100,
                remaining_duration_days=3,  # violates the 100-iff-0 invariant
                actual_start="2026-05-01T00:00:00Z",
                actual_finish="2026-05-08T00:00:00Z",
            ),
            contractor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PROGRESS)


class TestApprovalCascade:
    def _slipping_progress_update(self):
        """Accepted UPDATE whose single activity is reported 50% done with 20 days
        remaining (original plan: 10 days) — a projected finish past the contract
        completion date."""
        ctx = _project_with_accepted_update()
        pid, vid = ctx["project"]["id"], ctx["update"]["id"]
        activity_id = ctx["update_activity_ids"][0]
        pu = create_progress_update(
            pid, vid, reporting_period_end="2026-05-08T00:00:00Z"
        )
        add_progress_entry(
            pid,
            vid,
            pu["id"],
            create_progress_entry_payload(
                activity_id,
                percent_complete=50,
                remaining_duration_days=20,
                actual_start="2026-05-01T00:00:00Z",
            ),
        )
        submit_progress_update(pid, vid, pu["id"])
        return ctx, pu["id"]

    def test_approval_writes_entry_actuals_onto_activity(self, api, pce_headers):
        """PRD §3.4: "each entry's `percent_complete`, `remaining_duration_days`,
        `actual_start`, and `actual_finish` are written onto its activity, the
        forward-and-backward pass and critical path identification are re-run on the
        parent version, and `projected_finish_date` is recomputed."

        Design: Difficulty/transitive_cascade/progress_approval_cascades_cpm_recompute_then_lda_spawn
        """
        ctx, pu_id = self._slipping_progress_update()
        pid, vid = ctx["project"]["id"], ctx["update"]["id"]
        approved = approve_progress_update(pid, vid, pu_id)
        assert approved["status"] == "APPROVED"
        activity = get_activity(pid, vid, ctx["update_activity_ids"][0])
        assert activity["percent_complete"] == 50
        assert activity["remaining_duration_days"] == 20
        assert activity["actual_start"] is not None

    def test_approval_spawns_proposed_ld_assessment_on_overrun(
        self, api, pce_headers, owner_headers
    ):
        """PRD §3.4: "If the new projected finish crosses beyond the project's
        `current_completion_date`, the system automatically creates a draft
        (`PROPOSED`) liquidated damages assessment spanning the overrun window —
        the exposure cascade of §3.8."

        Design: Difficulty/transitive_cascade/progress_approval_cascades_cpm_recompute_then_lda_spawn
        """
        ctx, pu_id = self._slipping_progress_update()
        pid, vid = ctx["project"]["id"], ctx["update"]["id"]
        # Recomputed finish: data_date 2026-05-08 + 20 remaining days = 2026-05-28,
        # beyond the current completion date 2026-05-15 → cascade must fire.
        before, _ = validate_paginated(
            api.list_ld_assessments(pid, owner_headers)
        )
        assert before == [], "no assessment may exist before the overrunning approval"
        approve_progress_update(pid, vid, pu_id)
        after, meta = validate_paginated(
            api.list_ld_assessments(pid, owner_headers)
        )
        assert meta["total_count"] == 1, "exactly one assessment must be spawned"
        assert after[0]["status"] == "PROPOSED"
