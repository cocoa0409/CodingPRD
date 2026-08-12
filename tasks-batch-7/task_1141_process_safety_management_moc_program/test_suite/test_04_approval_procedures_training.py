"""Approval gate, procedure publication, training coverage (pinned rounding)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_procedure_update_payload,
    create_pha_study_payload,
    create_training_assignment_payload,
    drive_moc_to_approval_pending,
    drive_moc_to_approved,
    get_moc,
    make_approver_headers,
    make_requester_headers,
    moc_version,
    new_personnel,
    setup_moc_with_split_training_coverage,
    setup_unit_with_study,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
MANAGER = TEST_USERS["manager_headers"]


class TestApproval:
    def test_sod_approver_is_requester_rejected(self, api):
        """PRD §3.4: "Approval requires the approver to be someone other than the
        requester (`ERR_SOD_APPROVER_IS_REQUESTER`)" — an OpsApprover whose
        X-User-ID equals the MOC's requester_id is refused.

        Design: Corner/validations/sod_approver_is_requester_rejected
        """
        unit, _ = setup_unit_with_study()
        req = new_personnel("Req", "E-REQ")
        rev = new_personnel("Rev", "E-REV", qualifications=["CHEMICAL"])
        moc = drive_moc_to_approval_pending(unit["id"], req["id"], rev["id"])

        resp = api.approve_moc(moc["id"], {}, make_approver_headers(req["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_APPROVER_IS_REQUESTER.value)
        assert get_moc(moc["id"])["status"] == "APPROVAL_PENDING"

    def test_approve_response_immediate_consistency(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.4: "on success the approver is stamped as `approver_id` (null until
        this moment) and the MOC moves to `APPROVED_IMPLEMENTATION`" and "either
        way the MOC's `version` increments" — all of it visible on the approve
        response itself, no re-read needed.

        Design: Corner/consistency_model/approve_response_immediate_consistency
        """
        unit, _ = setup_unit_with_study()
        req = new_personnel("Req", "E-REQ")
        rev = new_personnel("Rev", "E-REV", qualifications=["CHEMICAL"])
        app = new_personnel("App", "E-APP")
        moc = drive_moc_to_approval_pending(unit["id"], req["id"], rev["id"])
        version_before = moc_version(moc["id"])

        resp = api.approve_moc(moc["id"], {}, make_approver_headers(app["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED_IMPLEMENTATION"
        assert data["approver_id"] == app["id"]
        assert data["version"] == version_before + 1, (
            f"version must increment by exactly 1: {version_before} -> {data['version']}"
        )


class TestProcedurePublicationGates:
    def test_mark_implemented_without_published_procedure_rejected(self, api):
        """PRD §3.4: "at least one linked procedure update must be `PUBLISHED`
        (`ERR_PROCEDURES_NOT_PUBLISHED`)" — a DRAFT update does not satisfy the
        publication gate.

        Design: Corner/validations/mark_implemented_without_published_procedure_rejected
        """
        unit, _ = setup_unit_with_study()
        req = new_personnel("Req", "E-REQ")
        rev = new_personnel("Rev", "E-REV", qualifications=["CHEMICAL"])
        app = new_personnel("App", "E-APP")
        moc = drive_moc_to_approved(unit["id"], req["id"], rev["id"], app["id"])
        update = validate_success(
            api.create_procedure_update(moc["id"], create_procedure_update_payload(), COORD), 201)
        assert update["status"] == "DRAFT"

        resp = api.mark_implemented(moc["id"], make_requester_headers(req["id"]))
        validate_error(resp, ApiErrorId.ERR_PROCEDURES_NOT_PUBLISHED.value)
        assert get_moc(moc["id"])["status"] == "APPROVED_IMPLEMENTATION"

    def test_publish_without_assignments_rejected(self, api):
        """PRD §3.4: "at least one **TrainingAssignment** must exist for it
        (`ERR_NO_TRAINING_ASSIGNED`)" — publication with zero assignments is
        blocked and the update stays DRAFT.

        Design: Corner/validations/publish_without_assignments_rejected
        """
        unit, _ = setup_unit_with_study()
        req = new_personnel("Req", "E-REQ")
        rev = new_personnel("Rev", "E-REV", qualifications=["CHEMICAL"])
        app = new_personnel("App", "E-APP")
        moc = drive_moc_to_approved(unit["id"], req["id"], rev["id"], app["id"])
        update = validate_success(
            api.create_procedure_update(moc["id"], create_procedure_update_payload(), COORD), 201)

        resp = api.publish_procedure_update(update["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_NO_TRAINING_ASSIGNED.value)
        refreshed = validate_success(api.get_procedure_update(update["id"], MANAGER))
        assert refreshed["status"] == "DRAFT"

    def test_uniqueness_pha_study_and_training_assignment(self, api):
        """PRD §3.7: "Each unit carries at most one **PhaStudy** — a second
        creation attempt is rejected with `ERR_PHA_STUDY_EXISTS`."
        PRD §3.4: assignments "are unique per (`procedure_update_id`,
        `personnel_id`) pair (`ERR_DUPLICATE_TRAINING_ASSIGNMENT`)".

        Design: Corner/validations/uniqueness_pha_study_and_training_assignment
        """
        unit, _ = setup_unit_with_study()
        req = new_personnel("Req", "E-REQ")
        rev = new_personnel("Rev", "E-REV", qualifications=["CHEMICAL"])
        app = new_personnel("App", "E-APP")
        moc = drive_moc_to_approved(unit["id"], req["id"], rev["id"], app["id"])
        update = validate_success(
            api.create_procedure_update(moc["id"], create_procedure_update_payload(), COORD), 201)
        validate_success(api.create_training_assignment(
            update["id"], create_training_assignment_payload(req["id"]), COORD), 201)

        dup_study = api.create_pha_study(
            unit["id"], create_pha_study_payload(method="WHAT_IF", initial_validated_at="2026-05-01"),
            MANAGER)
        validate_error(dup_study, ApiErrorId.ERR_PHA_STUDY_EXISTS.value)

        dup_assignment = api.create_training_assignment(
            update["id"], create_training_assignment_payload(req["id"]), COORD)
        validate_error(dup_assignment, ApiErrorId.ERR_DUPLICATE_TRAINING_ASSIGNMENT.value)


class TestTrainingCoveragePinnedRounding:
    def test_training_coverage_pinned_per_update_rounding(self, api):
        """PRD §3.4: "for each linked update in `PUBLISHED` status, a per-update
        coverage is one hundred times the update's completed assignments divided
        by its total assignments, rounded half-up to two decimal places; the
        MOC's `training_coverage_pct` is then the arithmetic mean of those
        per-update values across all published updates, itself rounded half-up to
        two decimal places." With completions 2/3 (66.67) and 3/4 (75.00) the
        pinned order yields round2((66.67 + 75.00) / 2) = 70.84 — "aggregating all
        completions over all assignments before a single rounding produces a
        different, non-conforming number" (71.43).

        Design: Difficulty/combinatorial_formula/training_coverage_per_update_rounding_mode_b
        """
        unit, actors, moc = setup_moc_with_split_training_coverage()
        assert moc["status"] == "APPROVED_IMPLEMENTATION"
        assert moc["training_coverage_pct"] == pytest.approx(70.84, abs=0.001), (
            f"pinned per-update rounding must yield 70.84, got {moc['training_coverage_pct']}"
        )

    def test_training_coverage_gate_rejects_mark_implemented(self, api):
        """PRD §3.4: "`training_coverage_pct` must be at least the unit's
        `training_coverage_threshold_pct` (`ERR_TRAINING_COVERAGE_INSUFFICIENT`)"
        — 70.84 is below the 100.00 default threshold (PRD §3.1), so
        mark-implemented is rejected and the MOC stays APPROVED_IMPLEMENTATION.

        Design: Difficulty/combinatorial_formula/training_coverage_per_update_rounding_mode_b
        """
        unit, actors, moc = setup_moc_with_split_training_coverage()
        resp = api.mark_implemented(moc["id"], make_requester_headers(actors["req"]["id"]))
        validate_error(resp, ApiErrorId.ERR_TRAINING_COVERAGE_INSUFFICIENT.value)
        after = get_moc(moc["id"])
        assert after["status"] == "APPROVED_IMPLEMENTATION"
        assert after["training_coverage_pct"] == pytest.approx(70.84, abs=0.001)
