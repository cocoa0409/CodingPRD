"""Project formation: creation defaults, MOBILIZE fiscal gates, listing envelope.

PRD §3.1 (project formation, mobilization checkpoint), §2.2/§2.3 (envelope,
pagination), §2.10 (validation precedence: state before fiscal).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_project,
    create_project_payload,
    create_project,
    invite_participation,
    commit_participation,
    lifecycle,
    create_project_with_committed_participants,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["pm_headers"]


class TestProjectDefaults:
    def test_new_project_starts_planning_clear_with_zero_counters(self, api):
        """PRD §3.1: "A new project starts in `PLANNING` status with posture
        `CLEAR`, zero `cumulative_delay_days`, zero `liquidated_damages_cents`,
        and no `latest_true_up_run_id` — that field stays null until the first
        true-up run exists."
        PRD §3.1: "An optional `contingency_days` allowance (zero or greater,
        defaulting to zero) sets the excusable-delay buffer before liquidated
        damages accrue."

        Design: Corner/entities/project_create_applies_defaults
        """
        resp = api.create_project(
            create_project_payload(
                name="Defaults",
                rule20_credit_cents=0,
                estimated_total_cost_cents=500000,
                target_cutover_on="2026-12-31T00:00:00Z",
            ),
            PM,
        )
        data = validate_success(resp, 201)
        assert_project(data)
        assert data["status"] == "PLANNING", f"expected PLANNING, got {data['status']}"
        assert data["posture"] == "CLEAR", f"expected CLEAR, got {data['posture']}"
        assert data["contingency_days"] == 0, "omitted contingency_days must default to 0"
        assert data["cumulative_delay_days"] == 0
        assert data["liquidated_damages_cents"] == 0
        assert data["latest_true_up_run_id"] is None


class TestMobilizeGates:
    def test_mobilize_requires_two_committed_participants(self, api):
        """PRD §3.1: "Mobilizing the project (`PLANNING → MOBILIZED`) is the
        first hard fiscal checkpoint, and it evaluates three gates in the
        global validation order: at least two participations must be in
        `COMMITTED` status (`ERR_MIN_PARTICIPANTS`), no two non-withdrawn
        participations may share a `sequence_order` (`ERR_DUPLICATE_SEQUENCE`),
        and the `cost_share_bp` values of the participations in `COMMITTED` or
        `MOBILIZED` must sum to exactly ten thousand (`ERR_SHARE_SUM_INVALID`)."

        Design: Corner/validations/mobilize_requires_two_committed_participants
        """
        project = create_project(
            name="V5", rule20_credit_cents=0, estimated_total_cost_cents=500000,
            target_cutover_on="2026-12-31T00:00:00Z",
        )
        p1 = invite_participation(project["id"], "U1", "ELECTRIC", 6000, 1)
        p2 = invite_participation(project["id"], "U2", "TELECOM", 4000, 2)
        commit_participation(p1["id"])

        resp = api.project_lifecycle(project["id"], {"action": "MOBILIZE"}, PM)
        validate_error(resp, ApiErrorId.ERR_MIN_PARTICIPANTS)

        commit_participation(p2["id"])
        ok = api.project_lifecycle(project["id"], {"action": "MOBILIZE"}, PM)
        data = validate_success(ok, 200)
        assert data["status"] == "MOBILIZED", (
            f"two COMMITTED participants satisfy the >= 2 gate, got {data['status']}"
        )

    def test_mobilize_rejects_share_sum_not_10000(self, api):
        """PRD §3.1: "Mobilizing the project (`PLANNING → MOBILIZED`) is the
        first hard fiscal checkpoint, and it evaluates three gates in the
        global validation order: at least two participations must be in
        `COMMITTED` status (`ERR_MIN_PARTICIPANTS`), no two non-withdrawn
        participations may share a `sequence_order` (`ERR_DUPLICATE_SEQUENCE`),
        and the `cost_share_bp` values of the participations in `COMMITTED` or
        `MOBILIZED` must sum to exactly ten thousand (`ERR_SHARE_SUM_INVALID`)."

        Design: Corner/validations/mobilize_share_sum_not_10000
        """
        project, _parts = create_project_with_committed_participants(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 6000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
            ],
            name="V6", rule20_credit_cents=0, estimated_total_cost_cents=500000,
            target_cutover_on="2026-12-31T00:00:00Z",
        )
        resp = api.project_lifecycle(project["id"], {"action": "MOBILIZE"}, PM)
        validate_error(resp, ApiErrorId.ERR_SHARE_SUM_INVALID)

    def test_mobilize_rejects_duplicate_sequence_order(self, api):
        """PRD §3.1: "Mobilizing the project (`PLANNING → MOBILIZED`) is the
        first hard fiscal checkpoint, and it evaluates three gates in the
        global validation order: at least two participations must be in
        `COMMITTED` status (`ERR_MIN_PARTICIPANTS`), no two non-withdrawn
        participations may share a `sequence_order` (`ERR_DUPLICATE_SEQUENCE`),
        and the `cost_share_bp` values of the participations in `COMMITTED` or
        `MOBILIZED` must sum to exactly ten thousand (`ERR_SHARE_SUM_INVALID`)."

        Design: Corner/validations/duplicate_sequence_order_rejected
        """
        project, _parts = create_project_with_committed_participants(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 5000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 5000, "sequence_order": 1},
            ],
            name="V7", rule20_credit_cents=0, estimated_total_cost_cents=500000,
            target_cutover_on="2026-12-31T00:00:00Z",
        )
        resp = api.project_lifecycle(project["id"], {"action": "MOBILIZE"}, PM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEQUENCE)


class TestStatePreemptsFiscalOnMobilize:
    def test_mobilize_on_cancelled_project_reports_state_not_fiscal(self, api):
        """PRD §2.10: "Only then does the server evaluate, in order: optimistic
        concurrency mismatches (`ERR_STALE_VERSION`); state-machine legality,
        including terminal-state lockdown (`ERR_INVALID_STATE`, HTTP 409);
        posture and freeze gates (`ERR_POSTURE_FROZEN`, `ERR_CHANGE_ORDER_FREEZE`);
        business safety rules such as trench geometry and outage coverage;
        referential gates such as easements and permits; temporal gates such as
        permit windows, slot windows, notification lead time, and warranty
        deadlines; capacity and constraint checks such as slot conflicts, crew
        capacity, and panel sizing; and finally the fiscal rules — share sums,
        exact payment amounts, and segregation of duties."
        Here the project is CANCELLED (terminal) and the committed bp sum is
        9000, so both checks could fire; the state rule runs first.

        Design: Difficulty/priority_pair_validation_conflict/state_preempts_fiscal_on_mobilize
        """
        project, _parts = create_project_with_committed_participants(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 6000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
            ],
            name="Prio Project", rule20_credit_cents=0, estimated_total_cost_cents=900000,
            target_cutover_on="2026-12-31T00:00:00Z",
        )
        lifecycle(project["id"], "CANCEL")
        resp = api.project_lifecycle(project["id"], {"action": "MOBILIZE"}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_share_sum_fires_when_state_is_valid(self, api):
        """PRD §3.1: "the `cost_share_bp` values of the participations in
        `COMMITTED` or `MOBILIZED` must sum to exactly ten thousand
        (`ERR_SHARE_SUM_INVALID`)."
        Companion half of the pair: with the project in a valid from-state
        (PLANNING), the fiscal gate is the one that fires for a 9000 bp sum.

        Design: Difficulty/priority_pair_validation_conflict/state_preempts_fiscal_on_mobilize
        """
        project, _parts = create_project_with_committed_participants(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 6000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
            ],
            name="Prio Project Iso", rule20_credit_cents=0, estimated_total_cost_cents=900000,
            target_cutover_on="2026-12-31T00:00:00Z",
        )
        resp = api.project_lifecycle(project["id"], {"action": "MOBILIZE"}, PM)
        validate_error(resp, ApiErrorId.ERR_SHARE_SUM_INVALID)


class TestProjectListing:
    def test_list_projects_paginates_with_envelope_fields(self, api):
        """PRD §2.3: "Paginated list responses carry four fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/list_projects_paginates_with_envelope_fields
        """
        for name in ("PgA", "PgB", "PgC"):
            create_project(
                name=name, rule20_credit_cents=0, estimated_total_cost_cents=1000,
                target_cutover_on="2026-12-31T00:00:00Z",
            )
        resp1 = api.list_projects(PM, params={"limit": 2, "offset": 0})
        page1, meta1 = validate_paginated(resp1)
        assert len(page1) == 2, f"page 1 must carry exactly 2 rows, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        assert resp1.json()["response_type"] == "array"
        assert isinstance(resp1.json()["meta"]["api_request_id"], str)

        resp2 = api.list_projects(PM, params={"limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(resp2)
        assert len(page2) == 1, f"page 2 must carry the last row only, got {len(page2)}"
        assert meta2["has_more"] is False
