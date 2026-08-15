"""Comparator groups: naming, membership rules, locking gates (PRD §3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_snapshot,
    add_snapshots,
    advance_study,
    api_client,
    assign_snapshot,
    create_group,
    create_group_payload,
    create_study,
    create_study_payload,
    get_group,
    lock_group,
    member_spec,
    two_eng_member_specs,
    validate_error,
    validate_success,
)

_ANALYST = TEST_USERS["comp_analyst_headers"]


def raw_lock(group_id):
    """Lock attempt that may fail — returns the raw response for error assertions."""
    return api_client.lock_group(group_id, _ANALYST)


def raw_advance(study_id):
    return api_client.advance_study(study_id, _ANALYST)


def raw_submit_review(study_id):
    return api_client.submit_legal_review(study_id, _ANALYST)


class TestGroupNaming:
    def test_group_duplicate_name_rejected(self, api, comp_analyst_headers):
        """PRD §3.2: "A group carries its parent `study_id`, a `name` that is unique within the study (a repeat is rejected with `ERR_DUPLICATE_GROUP_NAME`), and four membership criteria: `job_family`, `min_job_level`, `max_job_level` (which must be no lower than `min_job_level`, since both bounds are inclusive), and `location_code`."

        Design: Corner/entities/group_duplicate_name_rejected
        """
        y1 = validate_success(
            api.create_study(
                create_study_payload(
                    name="Y1",
                    analysis_period_start="2024-01-01",
                    analysis_period_end="2024-12-31",
                ),
                comp_analyst_headers,
            ),
            201,
        )
        y2 = validate_success(
            api.create_study(
                create_study_payload(
                    name="Y2",
                    analysis_period_start="2025-01-01",
                    analysis_period_end="2025-12-31",
                ),
                comp_analyst_headers,
            ),
            201,
        )
        validate_success(
            api.create_group(create_group_payload(y1["id"], name="ENG-5"), comp_analyst_headers),
            201,
        )
        # Same name in the SAME study conflicts.
        res = api.create_group(
            create_group_payload(
                y1["id"], name="ENG-5", min_job_level=6, max_job_level=6
            ),
            comp_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_GROUP_NAME)
        # Uniqueness is per-study: the same name in another study is allowed.
        ok = validate_success(
            api.create_group(create_group_payload(y2["id"], name="ENG-5"), comp_analyst_headers),
            201,
        )
        assert ok["name"] == "ENG-5"
        assert ok["study_id"] == y2["id"]


class TestGroupLocking:
    def test_group_lock_twice_rejected(self, api):
        """PRD §3.2: "A `CompAnalyst` locks a group only while the group is in `DRAFT` (otherwise `ERR_GROUP_INVALID_STATE`) and the parent study is in `MODELING` (otherwise `ERR_STUDY_NOT_MODELING`), and only when the group's `member_count` is at least the study's `min_group_size` — the boundary is inclusive, so a group whose membership exactly equals the floor locks successfully, and a smaller group is rejected with `ERR_GROUP_BELOW_MIN_SIZE`."

        Design: Corner/state_machines/group_lock_twice_rejected
        """
        study = create_study(
            name="G2", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=2,
        )
        members = add_snapshots(study["id"], two_eng_member_specs())
        group = create_group(study["id"], name="GG")
        for m in members:
            assign_snapshot(m["id"], group["id"])
        advance_study(study["id"])
        locked = lock_group(group["id"])
        assert locked["status"] == "LOCKED"
        # Locking an already-LOCKED group is a state violation.
        res = raw_lock(group["id"])
        validate_error(res, ApiErrorId.ERR_GROUP_INVALID_STATE)
        assert get_group(group["id"])["status"] == "LOCKED"

    def test_group_lock_below_min_size_rejected(self, api):
        """PRD §3.2: "A `CompAnalyst` locks a group only while the group is in `DRAFT` (otherwise `ERR_GROUP_INVALID_STATE`) and the parent study is in `MODELING` (otherwise `ERR_STUDY_NOT_MODELING`), and only when the group's `member_count` is at least the study's `min_group_size` — the boundary is inclusive, so a group whose membership exactly equals the floor locks successfully, and a smaller group is rejected with `ERR_GROUP_BELOW_MIN_SIZE`."

        Design: Corner/validations/group_lock_below_min_size_rejected
        """
        study = create_study(
            name="MS", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=3,
        )
        specs = [
            member_spec("MS1", "MALE", 10000000, 5),
            member_spec("MS2", "MALE", 10100000, 5),
            member_spec("MS3", "FEMALE", 9000000, 5),
            member_spec("MS4", "FEMALE", 9500000, 7),
        ]
        members = add_snapshots(study["id"], specs)
        gbig = create_group(study["id"], name="G-BIG", min_job_level=5, max_job_level=5)
        gsmall = create_group(study["id"], name="G-SMALL", min_job_level=7, max_job_level=7)
        for m in members[:3]:
            assign_snapshot(m["id"], gbig["id"])
        assign_snapshot(members[3]["id"], gsmall["id"])
        advance_study(study["id"])

        # member_count 1 < min_group_size 3 blocks the lock.
        res = raw_lock(gsmall["id"])
        validate_error(res, ApiErrorId.ERR_GROUP_BELOW_MIN_SIZE)
        # The 3-member sibling locks: member_count 3 >= 3 (inclusive boundary).
        locked = lock_group(gbig["id"])
        assert locked["status"] == "LOCKED"

    def test_lock_requires_study_modeling_rejected(self, api):
        """PRD §3.2: "A `CompAnalyst` locks a group only while the group is in `DRAFT` (otherwise `ERR_GROUP_INVALID_STATE`) and the parent study is in `MODELING` (otherwise `ERR_STUDY_NOT_MODELING`), and only when the group's `member_count` is at least the study's `min_group_size` — the boundary is inclusive, so a group whose membership exactly equals the floor locks successfully, and a smaller group is rejected with `ERR_GROUP_BELOW_MIN_SIZE`."

        Design: Difficulty/cross_entity_state_dependency/group_lock_requires_study_modeling
        """
        study = create_study(
            name="StudyJ", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=2,
        )
        members = add_snapshots(study["id"], two_eng_member_specs())
        group = create_group(study["id"], name="GJ")
        for m in members:
            assign_snapshot(m["id"], group["id"])
        # The group's own state and size are valid; only the parent study's
        # DRAFT state blocks the lock.
        assert get_group(group["id"])["member_count"] == 2
        res = raw_lock(group["id"])
        validate_error(res, ApiErrorId.ERR_STUDY_NOT_MODELING)

    def test_lock_succeeds_after_study_advances(self, api):
        """PRD §3.2: "A `CompAnalyst` locks a group only while the group is in `DRAFT` (otherwise `ERR_GROUP_INVALID_STATE`) and the parent study is in `MODELING` (otherwise `ERR_STUDY_NOT_MODELING`), and only when the group's `member_count` is at least the study's `min_group_size` — the boundary is inclusive, so a group whose membership exactly equals the floor locks successfully, and a smaller group is rejected with `ERR_GROUP_BELOW_MIN_SIZE`."
        PRD §3.2: "Advancement requires the study to be in `DRAFT` (otherwise `ERR_STUDY_INVALID_STATE`) and at least one of its comparator groups to have a `member_count` of at least the study's `min_group_size` (otherwise `ERR_NO_QUALIFYING_GROUPS`)."

        Design: Difficulty/cross_entity_state_dependency/group_lock_requires_study_modeling
        """
        study = create_study(
            name="StudyJ", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=2,
        )
        members = add_snapshots(study["id"], two_eng_member_specs())
        group = create_group(study["id"], name="GJ")
        for m in members:
            assign_snapshot(m["id"], group["id"])
        advance_study(study["id"])
        # After the study advances to MODELING, the identical lock succeeds.
        locked = lock_group(group["id"])
        assert locked["status"] == "LOCKED"


class TestMembershipAssignment:
    def test_assign_cross_study_group_rejected(self, api, people_ops_admin_headers):
        """PRD §3.2: "Assignment requires the target group to be in `DRAFT` — assigning to, or unassigning from, a `LOCKED` or `ANALYZED` group is rejected with `ERR_GROUP_INVALID_STATE` — and the group must belong to the same study as the snapshot; a cross-study reference among snapshot, group, plan, or finding is rejected with `ERR_CROSS_STUDY_REFERENCE`."

        Design: Corner/validations/assign_cross_study_group_rejected
        """
        sa = create_study(
            name="XA", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31",
        )
        sb = create_study(
            name="XB", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
        )
        snap = add_snapshot(sa["id"], member_spec("SA1", "MALE", 10000000))
        # Criteria match (same family/level/location); only the study differs.
        gb = create_group(sb["id"], name="GXB")
        res = api.patch_snapshot(
            snap["id"], {"comparator_group_id": gb["id"]}, people_ops_admin_headers
        )
        validate_error(res, ApiErrorId.ERR_CROSS_STUDY_REFERENCE)
        # The rejected assignment leaves the snapshot unassigned.
        reread = validate_success(api.get_snapshot(snap["id"], people_ops_admin_headers))
        assert reread["comparator_group_id"] is None

    def test_assign_criteria_mismatch_rejected(self, api, people_ops_admin_headers):
        """PRD §3.2: "The snapshot must also satisfy the group's membership criteria: its `job_family` and `location_code` must equal the group's, and its `job_level` must fall inside the inclusive band from `min_job_level` to `max_job_level`; otherwise the assignment is rejected with `ERR_GROUP_CRITERIA_MISMATCH`."

        Design: Corner/validations/assign_criteria_mismatch_rejected
        """
        study = create_study(
            name="CM", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
        )
        snap = add_snapshot(study["id"], member_spec("CM1", "MALE", 10000000, 6))
        group = create_group(study["id"], name="GCM", min_job_level=5, max_job_level=5)
        # Level 6 falls outside the group's inclusive [5, 5] band.
        res = api.patch_snapshot(
            snap["id"], {"comparator_group_id": group["id"]}, people_ops_admin_headers
        )
        validate_error(res, ApiErrorId.ERR_GROUP_CRITERIA_MISMATCH)

    def test_assign_to_locked_group_rejected(self, api, people_ops_admin_headers):
        """PRD §3.2: "Once locked, membership is frozen: any attempt to assign snapshots to or unassign snapshots from the group fails with `ERR_GROUP_INVALID_STATE`."

        Design: Corner/validations/assign_to_locked_group_rejected
        """
        study = create_study(
            name="AL", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=2,
        )
        specs = [
            member_spec("AL1", "MALE", 10000000),
            member_spec("AL2", "FEMALE", 9000000),
            member_spec("AL3", "FEMALE", 9500000),
        ]
        members = add_snapshots(study["id"], specs)
        group = create_group(study["id"], name="GAL")
        assign_snapshot(members[0]["id"], group["id"])
        assign_snapshot(members[1]["id"], group["id"])
        advance_study(study["id"])
        lock_group(group["id"])
        # Membership is frozen at lock: the third snapshot cannot join.
        res = api.patch_snapshot(
            members[2]["id"], {"comparator_group_id": group["id"]}, people_ops_admin_headers
        )
        validate_error(res, ApiErrorId.ERR_GROUP_INVALID_STATE)


class TestStudyAdvanceAndReviewGates:
    def test_advance_without_qualifying_group_rejected(self, api):
        """PRD §3.2: "Advancement requires the study to be in `DRAFT` (otherwise `ERR_STUDY_INVALID_STATE`) and at least one of its comparator groups to have a `member_count` of at least the study's `min_group_size` (otherwise `ERR_NO_QUALIFYING_GROUPS`)."

        Design: Corner/state_machines/advance_without_qualifying_group_rejected
        """
        study = create_study(
            name="AQ", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=2,
        )
        res = raw_advance(study["id"])
        validate_error(res, ApiErrorId.ERR_NO_QUALIFYING_GROUPS)

    def test_submit_legal_review_with_unanalyzed_group_rejected(self, api):
        """PRD §3.3: "Submission requires the study to be in `MODELING` (otherwise `ERR_STUDY_INVALID_STATE`) and requires every comparator group in `LOCKED` or `ANALYZED` status to hold at least one `FINAL` model run (otherwise `ERR_UNANALYZED_GROUPS`)."

        Design: Corner/state_machines/submit_legal_review_with_unanalyzed_group_rejected
        """
        study = create_study(
            name="UL", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=2,
        )
        members = add_snapshots(study["id"], two_eng_member_specs())
        group = create_group(study["id"], name="GUL")
        for m in members:
            assign_snapshot(m["id"], group["id"])
        advance_study(study["id"])
        lock_group(group["id"])
        # The LOCKED group holds no FINAL run, blocking legal-review submission.
        res = raw_submit_review(study["id"])
        validate_error(res, ApiErrorId.ERR_UNANALYZED_GROUPS)
