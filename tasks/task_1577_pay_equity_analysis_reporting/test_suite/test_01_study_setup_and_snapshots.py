"""Study creation defaults, snapshot intake, listing, and headcount conservation
(PRD §2.9, §2.10, §3.1)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_snapshots,
    advance_study,
    api_client,
    assign_snapshot,
    create_group,
    create_snapshot_payload,
    create_study,
    create_study_payload,
    get_group,
    get_study,
    member_spec,
    unassign_snapshot,
    validate_error,
    validate_paginated,
    validate_success,
)

PEOPLE_OPS = TEST_USERS["people_ops_admin_headers"]


class TestStudyCreation:
    def test_study_create_applies_defaults(self, api, comp_analyst_headers):
        """PRD §3.1: "`significance_threshold` is the p-value ceiling for statistical significance and defaults to 0.05; `actionable_gap_pct` is the minimum adjusted gap percent for actionability and defaults to 2.0; `min_group_size` is the membership floor a comparator group must reach before it can lock and defaults to 30; `monitor_cadence_days` is the cadence between monitoring windows, defaults to 180, and serves as the informational baseline when a cycle's `due_date` is chosen."
        PRD §3.1: "A new study begins in `DRAFT` with `review_rounds` at zero and an empty `privileged_model_run_ids` list."

        Design: Corner/entities/study_create_applies_defaults
        """
        study = validate_success(
            api.create_study(
                create_study_payload(
                    name="Dflt",
                    analysis_period_start="2025-01-01",
                    analysis_period_end="2025-12-31",
                    protected_classes=["GENDER"],
                ),
                comp_analyst_headers,
            ),
            201,
        )
        assert study["status"] == "DRAFT"
        assert isinstance(study["version"], int)
        assert study["significance_threshold"] == pytest.approx(0.05, abs=1e-9)
        assert study["actionable_gap_pct"] == pytest.approx(2.0, abs=1e-9)
        assert study["min_group_size"] == 30
        assert study["monitor_cadence_days"] == 180
        assert study["review_rounds"] == 0
        assert study["privileged_model_run_ids"] == []

    def test_study_create_missing_required_name_rejected(self, api, comp_analyst_headers):
        """PRD §3.1: "An `analysis_period_end` earlier than `analysis_period_start`, a missing required field, an invalid enum value, or a malformed date is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/study_create_missing_required_name_rejected
        """
        res = api.create_study(
            {
                "analysis_period_start": "2025-01-01",
                "analysis_period_end": "2025-12-31",
                "protected_classes": ["GENDER"],
            },
            comp_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        # No study persisted: the list stays empty.
        data, meta = validate_paginated(api.list_studies(comp_analyst_headers))
        assert meta["total_count"] == 0
        assert data == []

    def test_study_create_invalid_period_rejected(self, api, comp_analyst_headers):
        """PRD §3.1: "An `analysis_period_end` earlier than `analysis_period_start`, a missing required field, an invalid enum value, or a malformed date is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/study_create_invalid_period_rejected
        """
        res = api.create_study(
            create_study_payload(
                name="BadPeriod",
                analysis_period_start="2025-12-31",
                analysis_period_end="2025-01-01",
                protected_classes=["GENDER"],
            ),
            comp_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_study_get_unknown_id_returns_not_found(self, api, comp_analyst_headers):
        """PRD §2.8: "Third, every identifier in the path and every foreign-key identifier in the request body is resolved left to right, and the first one that does not reference an existing resource yields `ERR_NOT_FOUND`."

        Design: Corner/entities/study_get_unknown_id_returns_not_found
        """
        res = api.get_study(
            "11111111-2222-4333-8444-555555555555", comp_analyst_headers
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_study_list_filter_by_status(self, api, comp_analyst_headers):
        """PRD §3.1: "The studies collection supports an optional `status` query filter alongside pagination."

        Design: Corner/entities/study_list_filter_by_status
        """
        validate_success(
            api.create_study(
                create_study_payload(
                    name="F1",
                    analysis_period_start="2024-01-01",
                    analysis_period_end="2024-12-31",
                ),
                comp_analyst_headers,
            ),
            201,
        )
        validate_success(
            api.create_study(
                create_study_payload(
                    name="F2",
                    analysis_period_start="2025-01-01",
                    analysis_period_end="2025-12-31",
                ),
                comp_analyst_headers,
            ),
            201,
        )
        drafts, meta_drafts = validate_paginated(
            api.list_studies(comp_analyst_headers, {"status": "DRAFT"})
        )
        assert len(drafts) == 2
        assert all(s["status"] == "DRAFT" for s in drafts)
        closed, meta_closed = validate_paginated(
            api.list_studies(comp_analyst_headers, {"status": "CLOSED"})
        )
        assert closed == []
        assert meta_closed["total_count"] == 0


class TestStudyPeriodOverlap:
    def test_shared_boundary_date_conflicts(self, api, comp_analyst_headers):
        """PRD §2.9: "Two studies may not hold overlapping analysis periods, and because the intervals are closed, two periods that share even a single boundary date conflict. A conflicting study creation is rejected with `ERR_STUDY_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/study_period_closed_interval_boundary_conflicts
        """
        validate_success(
            api.create_study(
                create_study_payload(
                    name="StudyL1",
                    analysis_period_start="2025-01-01",
                    analysis_period_end="2025-12-31",
                ),
                comp_analyst_headers,
            ),
            201,
        )
        res = api.create_study(
            create_study_payload(
                name="StudyL2",
                analysis_period_start="2025-12-31",
                analysis_period_end="2026-06-30",
            ),
            comp_analyst_headers,
        )
        # 2025-12-31 belongs to both CLOSED periods.
        validate_error(res, ApiErrorId.ERR_STUDY_PERIOD_OVERLAP)

    def test_next_day_period_accepted(self, api, comp_analyst_headers):
        """PRD §2.9: "Two studies may not hold overlapping analysis periods, and because the intervals are closed, two periods that share even a single boundary date conflict. A conflicting study creation is rejected with `ERR_STUDY_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/study_period_closed_interval_boundary_conflicts
        """
        validate_success(
            api.create_study(
                create_study_payload(
                    name="StudyL1",
                    analysis_period_start="2025-01-01",
                    analysis_period_end="2025-12-31",
                ),
                comp_analyst_headers,
            ),
            201,
        )
        # 2026-01-01 is the first day wholly outside the occupied CLOSED period.
        study = validate_success(
            api.create_study(
                create_study_payload(
                    name="StudyL3",
                    analysis_period_start="2026-01-01",
                    analysis_period_end="2026-12-31",
                ),
                comp_analyst_headers,
            ),
            201,
        )
        assert study["status"] == "DRAFT"


class TestSnapshotIntake:
    def test_snapshot_computed_fields_input_ignored(
        self, api, comp_analyst_headers, people_ops_admin_headers
    ):
        """PRD §3.1: "The `annualized_base_cents` is the FTE-normalized annual base: `base_salary_cents` divided by `fte_factor`, rounded half-up to a whole cent."
        PRD §3.1: "The `tenure_years` is the number of days between the snapshot's `hire_date` and the parent study's `analysis_period_end`, divided by 365.25 and rounded half-up to two decimal places."

        Design: Corner/entities/snapshot_computed_fields_input_ignored
        """
        study = validate_success(
            api.create_study(
                create_study_payload(
                    name="StudyX",
                    analysis_period_start="2025-01-01",
                    analysis_period_end="2025-12-31",
                ),
                comp_analyst_headers,
            ),
            201,
        )
        payload = create_snapshot_payload(
            study["id"],
            employee_ref="X1",
            fte_factor=0.5,
            base_salary_cents=6000000,
            hire_date="2021-01-01",
        )
        # A client-sent value for the derived field must not override the
        # server computation (the server derives it from the inputs above).
        payload["annualized_base_cents"] = 1
        snap = validate_success(
            api.create_snapshot(payload, people_ops_admin_headers), 201
        )
        assert snap["annualized_base_cents"] == 12000000
        assert snap["tenure_years"] == pytest.approx(5.0, abs=1e-9)

    def test_snapshot_duplicate_employee_ref_rejected(
        self, api, comp_analyst_headers, people_ops_admin_headers
    ):
        """PRD §3.1: "Each snapshot names its parent `study_id` — immutable after creation — and an `employee_ref` that is unique within the study; a repeated `employee_ref` in the same study is rejected with `ERR_DUPLICATE_EMPLOYEE_REF`."

        Design: Corner/entities/snapshot_duplicate_employee_ref_rejected
        """
        x1 = validate_success(
            api.create_study(
                create_study_payload(
                    name="X1",
                    analysis_period_start="2024-01-01",
                    analysis_period_end="2024-12-31",
                ),
                comp_analyst_headers,
            ),
            201,
        )
        x2 = validate_success(
            api.create_study(
                create_study_payload(
                    name="X2",
                    analysis_period_start="2025-01-01",
                    analysis_period_end="2025-12-31",
                ),
                comp_analyst_headers,
            ),
            201,
        )
        validate_success(
            api.create_snapshot(
                create_snapshot_payload(x1["id"], employee_ref="DUP1"),
                people_ops_admin_headers,
            ),
            201,
        )
        # Same ref in the SAME study conflicts.
        res = api.create_snapshot(
            create_snapshot_payload(
                x1["id"], employee_ref="DUP1", gender_class="FEMALE",
                ethnicity_class="ASIAN", age_band="FORTY_PLUS", job_level=4,
                base_salary_cents=9000000, hire_date="2019-01-01",
            ),
            people_ops_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_REF)
        # Uniqueness is per-study: the same ref in a DIFFERENT study is fine.
        ok = validate_success(
            api.create_snapshot(
                create_snapshot_payload(
                    x2["id"], employee_ref="DUP1", gender_class="FEMALE",
                    ethnicity_class="ASIAN", age_band="FORTY_PLUS", job_level=4,
                    base_salary_cents=9000000, hire_date="2019-01-01",
                ),
                people_ops_admin_headers,
            ),
            201,
        )
        assert ok["employee_ref"] == "DUP1"
        assert ok["study_id"] == x2["id"]

    def test_snapshot_create_with_unknown_study_returns_not_found(
        self, api, people_ops_admin_headers
    ):
        """PRD §2.8: "Third, every identifier in the path and every foreign-key identifier in the request body is resolved left to right, and the first one that does not reference an existing resource yields `ERR_NOT_FOUND`."

        Design: Corner/validations/snapshot_create_with_unknown_study_returns_not_found
        """
        res = api.create_snapshot(
            create_snapshot_payload(
                "11111111-2222-4333-8444-555555555555", employee_ref="ORPH"
            ),
            people_ops_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_snapshot_create_after_advance_locked(self, api):
        """PRD §3.1: "Creating a snapshot — or patching a snapshot's compensation fields, namely `base_salary_cents`, `bonus_cents`, `fte_factor`, or `job_level` — is rejected with `ERR_SNAPSHOT_LOCKED` whenever the parent study is no longer in `DRAFT`."

        Design: Corner/state_machines/snapshot_create_after_advance_locked
        """
        study = create_study(
            name="SL", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=2,
        )
        members = add_snapshots(
            study["id"],
            [
                member_spec("SLM1", "MALE", 10000000),
                member_spec("SLF1", "FEMALE", 9000000),
            ],
        )
        group = create_group(study["id"], name="GSL")
        for m in members:
            assign_snapshot(m["id"], group["id"])
        advance_study(study["id"])
        res = api_client.create_snapshot(
            create_snapshot_payload(
                study["id"], employee_ref="SLLATE", base_salary_cents=8000000,
                hire_date="2021-01-01",
            ),
            PEOPLE_OPS,
        )
        validate_error(res, ApiErrorId.ERR_SNAPSHOT_LOCKED)

    def test_immediate_read_after_write_consistency(
        self, api, comp_analyst_headers, people_ops_admin_headers
    ):
        """PRD §2.10: "Several resources expose derived aggregates that the server maintains automatically, atomically within the request that triggers the change."
        PRD §3.1: "A permitted patch to `base_salary_cents` or `fte_factor` recomputes `annualized_base_cents` from the new values."
        PRD §2.5: "**`version` (integer):** A system-managed integer that increments with every modification to the resource."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        study = validate_success(
            api.create_study(
                create_study_payload(
                    name="IC",
                    analysis_period_start="2025-01-01",
                    analysis_period_end="2025-12-31",
                ),
                comp_analyst_headers,
            ),
            201,
        )
        snap = validate_success(
            api.create_snapshot(
                create_snapshot_payload(study["id"], employee_ref="IC1"),
                people_ops_admin_headers,
            ),
            201,
        )
        # The POST is visible in the parent's computed aggregate on the very next GET.
        study_after = validate_success(
            api.get_study(study["id"], comp_analyst_headers)
        )
        assert study_after["snapshot_count"] == 1
        # PATCH recomputes the derived field in-request and increments version.
        patched = validate_success(
            api.patch_snapshot(
                snap["id"], {"base_salary_cents": 10500000}, people_ops_admin_headers
            )
        )
        assert patched["annualized_base_cents"] == 10500000
        assert patched["version"] > snap["version"]
        # Read-back returns the patched value.
        reread = validate_success(
            api.get_snapshot(snap["id"], comp_analyst_headers)
        )
        assert reread["base_salary_cents"] == 10500000


class TestHeadcountConservation:
    def test_assign_two_members_updates_counts(self, api):
        """PRD §2.10: "A study reports `snapshot_count` (the number of employee snapshots belonging to it), `assigned_snapshot_count` (the number of its snapshots whose `comparator_group_id` is non-null), `unresolved_finding_count` (the number of its gap findings in `FLAGGED` or `TARGETED` status), and `actionable_finding_count` (the number of its findings whose `is_actionable` is true and whose status is anything other than `DISMISSED`). A comparator group reports `member_count`, the number of snapshots currently assigned to it."

        Design: Difficulty/compensating_invariant/assign_unassign_roundtrip_conserves_headcount
        """
        study = create_study(
            name="StudyO", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=2,
        )
        specs = [
            member_spec("OM1", "MALE", 10000000),
            member_spec("OM2", "MALE", 10100000),
            member_spec("OF1", "FEMALE", 9500000),
        ]
        members = add_snapshots(study["id"], specs)
        group = create_group(study["id"], name="GO")
        baseline = get_study(study["id"])
        assert baseline["snapshot_count"] == 3
        assert baseline["assigned_snapshot_count"] == 0
        assert group["member_count"] == 0

        assign_snapshot(members[0]["id"], group["id"])
        assign_snapshot(members[1]["id"], group["id"])
        assert get_group(group["id"])["member_count"] == 2
        after = get_study(study["id"])
        # Headcount conserved: assigned + unassigned == snapshot_count == 3.
        assert after["snapshot_count"] == 3
        assert after["assigned_snapshot_count"] == 2

    def test_assign_unassign_roundtrip_returns_to_zero(self, api):
        """PRD §3.2: "Membership is managed on the snapshot side: a `PeopleOpsAdmin` assigns a snapshot to a group by patching its `comparator_group_id`, and unassigns it by sending `comparator_group_id` as null."
        PRD §2.10: "A comparator group reports `member_count`, the number of snapshots currently assigned to it."

        Design: Difficulty/compensating_invariant/assign_unassign_roundtrip_conserves_headcount
        """
        study = create_study(
            name="StudyO", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=2,
        )
        specs = [
            member_spec("OM1", "MALE", 10000000),
            member_spec("OM2", "MALE", 10100000),
            member_spec("OF1", "FEMALE", 9500000),
        ]
        members = add_snapshots(study["id"], specs)
        group = create_group(study["id"], name="GO")

        assign_snapshot(members[0]["id"], group["id"])
        assign_snapshot(members[1]["id"], group["id"])
        assert get_group(group["id"])["member_count"] == 2

        unassign_snapshot(members[0]["id"])
        unassign_snapshot(members[1]["id"])
        # The compensating pair returns every counter to exactly its baseline.
        assert get_group(group["id"])["member_count"] == 0
        final = get_study(study["id"])
        assert final["snapshot_count"] == 3
        assert final["assigned_snapshot_count"] == 0
        # The third snapshot was never assigned.
        third = validate_success(
            api_client.get_snapshot(members[2]["id"], PEOPLE_OPS)
        )
        assert third["comparator_group_id"] is None
