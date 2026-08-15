"""Inspections and the deficiency correction loop: the reject-reopen cycle,
segregated verification, creation prerequisites, SubcontractorRep ownership,
the IMMINENT_DANGER freeze, and immediate read consistency (PRD §3.5, §2.8)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId, api_client,
    validate_error, validate_success,
    create_project, create_project_with_active_plan,
    create_inspection, create_completed_inspection, complete_inspection,
    create_deficiency, submit_correction, get_deficiency, get_project,
    setup_jobsite_with_issued_permit, get_permit, get_jha, set_clock,
    make_safety_manager_headers, make_safety_inspector_headers,
    make_subcontractor_rep_headers,
)

SM = make_safety_manager_headers()
INSP1 = make_safety_inspector_headers("insp-1")
INSP2 = make_safety_inspector_headers("insp-2")


def _parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp to an aware datetime for instant
    comparison. PRD §2.4/§2.12 pin per-field formats (created_at carries three
    fractional digits; due_at is second-precision), so instant equality must
    not be asserted as raw string equality."""
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    ).astimezone(timezone.utc)


def _project_with_open_deficiency(name="Site", hours=20000, severity="MINOR",
                                  sub_id=None):
    set_clock("2026-08-01T08:00:00Z")
    project = create_project(name=name, annual_hours_worked=hours)
    inspection = create_completed_inspection(project["id"], inspector_id="insp-1")
    deficiency = create_deficiency(inspection["id"], severity=severity,
                                   assigned_subcontractor_id=sub_id,
                                   creator_id="insp-1")
    return project, inspection, deficiency


class TestDeficiencyCorrectionCycle:

    def test_reject_reopen_cycle_is_traversable(self, api):
        """PRD §3.5: "On `REJECTED`, the deficiency returns to `OPEN` with
        `verified_by_user_id` reset to null and the submitted `correction_notes`
        retained"
        PRD §3.5: "Submitting a correction — open to a `SiteSuperintendent`, or to
        a `SubcontractorRep` whose `X-User-ID` equals the deficiency's
        `assigned_subcontractor_id` (a mismatch is `ERR_INSUFFICIENT_PERMISSIONS`,
        HTTP 403) — moves the deficiency from `OPEN` or `OVERDUE` to
        `CORRECTION_SUBMITTED`"

        Design: Difficulty/non_linear_state_machine/deficiency_correction_reject_reopen_cycle
        """
        project, _insp, deficiency = _project_with_open_deficiency(
            name="Lincoln Square", hours=120000
        )

        submitted = submit_correction(deficiency["id"], "cleared")
        assert submitted["status"] == "CORRECTION_SUBMITTED"

        # REJECTED cycles back to OPEN — not terminal. (MINOR due in 14 days,
        # so no overdue re-flip at the unchanged clock.)
        resp_reject = api.verify_deficiency(
            deficiency["id"], {"outcome": "REJECTED"}, INSP2
        )
        rejected = validate_success(resp_reject, 200)
        assert rejected["status"] == "OPEN", (
            f"rejection must cycle back to OPEN, got {rejected['status']}"
        )
        assert rejected["verified_by_user_id"] is None
        assert rejected["correction_notes"] == "cleared"

    def test_cycle_closes_and_decrements_open_count(self, api):
        """PRD §3.5: "On `CLOSED`, the deficiency moves to the terminal
        `VERIFIED_CLOSED` state: `verified_by_user_id` records the verifier,
        `closed_disposition` stores the request's disposition (null until this
        point), the project's `open_deficiency_count` decrements, the project's
        `version` increments, and posture is recomputed."

        Design: Difficulty/non_linear_state_machine/deficiency_correction_reject_reopen_cycle
        """
        project, _insp, deficiency = _project_with_open_deficiency(
            name="Lincoln Square 2", hours=121000
        )
        assert get_project(project["id"])["open_deficiency_count"] == 1

        submit_correction(deficiency["id"], "cleared")
        api_verify = api.verify_deficiency(
            deficiency["id"], {"outcome": "REJECTED"}, INSP2
        )
        assert validate_success(api_verify, 200)["status"] == "OPEN"

        submit_correction(deficiency["id"], "rework with photo")
        resp_close = api.verify_deficiency(
            deficiency["id"],
            {"outcome": "CLOSED", "disposition": "CONFIRMED"}, INSP2,
        )
        closed = validate_success(resp_close, 200)
        assert closed["status"] == "VERIFIED_CLOSED"
        assert closed["verified_by_user_id"] == "insp-2"
        assert closed["closed_disposition"] == "CONFIRMED"
        assert get_project(project["id"])["open_deficiency_count"] == 0


class TestDeficiencySegregationAndState:

    def test_verify_by_creator_rejected(self, api):
        """PRD §2.8: "A deficiency is logged by one `SafetyInspector` and verified
        by another: the verifying operator's `X-User-ID` must differ from the
        deficiency's `created_by_user_id`, and a match is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/validations/deficiency_verify_by_creator_rejected
        """
        _project, _insp, deficiency = _project_with_open_deficiency(
            name="Georgetown", hours=28000
        )
        submit_correction(deficiency["id"], "cord replaced")

        resp = api.verify_deficiency(
            deficiency["id"],
            {"outcome": "CLOSED", "disposition": "CONFIRMED"}, INSP1,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        assert get_deficiency(deficiency["id"])["status"] == "CORRECTION_SUBMITTED"

    def test_verify_from_open_rejected(self, api):
        """PRD §3.5: "Submitting a correction — open to a `SiteSuperintendent`,
        or to a `SubcontractorRep` whose `X-User-ID` equals the deficiency's
        `assigned_subcontractor_id` (a mismatch is `ERR_INSUFFICIENT_PERMISSIONS`,
        HTTP 403) — moves the deficiency from `OPEN` or `OVERDUE` to
        `CORRECTION_SUBMITTED` and stores the request's `correction_notes`. Any
        other source state yields `ERR_DEFICIENCY_INVALID_STATE`."
        PRD §2.9: "Fifth (priority 5): the target resource must be in the state
        the operation requires."

        Design: Corner/errors/deficiency_verify_from_open_rejected
        """
        _project, _insp, deficiency = _project_with_open_deficiency(
            name="Madison Park", hours=11000
        )
        resp = api.verify_deficiency(
            deficiency["id"],
            {"outcome": "CLOSED", "disposition": "CONFIRMED"}, INSP2,
        )
        validate_error(resp, ApiErrorId.ERR_DEFICIENCY_INVALID_STATE)

    def test_deficiency_create_requires_completed_inspection(self, api):
        """PRD §3.5: "The parent inspection must be `COMPLETED`, else
        `ERR_INSPECTION_NOT_COMPLETED`."

        Design: Corner/errors/deficiency_create_on_due_inspection_rejected
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Arbor Heights", annual_hours_worked=16000)
        inspection = create_inspection(project["id"], inspection_type="DAILY",
                                       due_date="2026-08-05T17:00:00Z")
        resp = api.create_deficiency(
            {"inspection_id": inspection["id"], "description": "premature",
             "severity": "MINOR"}, INSP1,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_COMPLETED)

    def test_submit_correction_by_other_subcontractor_forbidden(self, api):
        """PRD §2.1: "ownership checks on any resource that references a
        subcontractor — in practice, submitting a correction on a deficiency —
        compare the resource's `assigned_subcontractor_id` field to `X-User-ID`,
        and a mismatch is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/validations/submit_correction_by_other_subcontractor_forbidden
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="View Ridge", annual_hours_worked=26000)
        from test_helpers import create_subcontractor
        s1 = create_subcontractor(project["id"], company_name="One Sub",
                                  trade="plumbing")
        s2 = create_subcontractor(project["id"], company_name="Two Sub",
                                  trade="hvac")
        inspection = create_completed_inspection(project["id"])
        deficiency = create_deficiency(
            inspection["id"], "missing pipe supports", "MINOR",
            assigned_subcontractor_id=s1["id"], creator_id="insp-1",
        )

        resp = api.submit_correction(
            deficiency["id"], {"correction_notes": "not ours"},
            make_subcontractor_rep_headers(s2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestImminentDangerFreeze:

    def test_imminent_danger_deficiency_freezes_project(self, api):
        """PRD §3.5: "`IMMINENT_DANGER` is due immediately — `due_at` equals the
        creation timestamp itself, so the strictly-greater overdue rule flips it
        to `OVERDUE` on the first clock advance past creation."
        PRD §3.5: "an `IMMINENT_DANGER` deficiency therefore freezes the project
        the moment it is logged, running the permit-suspension cascade of §2.6."
        PRD §2.6: "When a project transitions into `FROZEN`, every permit of that
        project in status `ISSUED` is suspended with `suspension_reason` set to
        `POSTURE_FROZEN`, and each such suspension cascades to the permit's job
        hazard analysis per §2.7."

        Design: Corner/state_machines/imminent_danger_deficiency_freeze_cascade
        """
        setup = setup_jobsite_with_issued_permit(project_name="Northgate",
                                                 annual_hours=75000)
        project_id = setup["project"]["id"]
        inspection = create_completed_inspection(
            project_id, inspection_type="DAILY", due_date="2026-08-02T17:00:00Z",
            findings_summary="platform tie-in missing",
        )

        resp = api.create_deficiency(
            {"inspection_id": inspection["id"],
             "description": "work platform could collapse",
             "severity": "IMMINENT_DANGER"}, INSP1,
        )
        deficiency = validate_success(resp, 201)
        # The zero-day SLA makes due_at equal to the creation timestamp.
        # Compared as instants: §2.4 formats created_at with three fractional
        # digits while §2.12 defaults due_at to second precision.
        assert _parse_ts(deficiency["due_at"]) == _parse_ts(deficiency["created_at"]), (
            f"IMMINENT_DANGER due_at must equal created_at: "
            f"{deficiency['due_at']} != {deficiency['created_at']}"
        )
        assert deficiency["status"] == "OPEN"

        assert get_project(project_id)["safety_posture"] == "FROZEN"
        permit = get_permit(setup["permit"]["id"])
        assert permit["status"] == "SUSPENDED"
        assert permit["suspension_reason"] == "POSTURE_FROZEN"
        assert get_jha(setup["jha"]["id"])["status"] == "RE_REVIEW_REQUIRED"


class TestImmediateConsistency:

    def test_create_response_carries_due_at_and_count_updates(self, api):
        """PRD §3.5: "computes `due_at` from a severity service-level agreement:
        `MINOR` deficiencies are due 14 days after creation, `MAJOR` after 7 days,
        `CRITICAL` after 3 days"
        PRD §3.5: "increments the project's `open_deficiency_count`"

        Design: Corner/consistency_model/immediate_consistency_in_response_and_next_read
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Phinney", annual_hours_worked=17000)
        inspection = create_completed_inspection(
            project["id"], inspection_type="DAILY",
            due_date="2026-08-05T17:00:00Z", findings_summary="electrical",
        )

        resp = api.create_deficiency(
            {"inspection_id": inspection["id"], "description": "exposed wiring",
             "severity": "CRITICAL"}, INSP1,
        )
        deficiency = validate_success(resp, 201)
        # created_at is the logical clock 2026-08-01T08:00:00Z; CRITICAL SLA +3d.
        assert deficiency["due_at"].startswith("2026-08-04T08:00:00"), (
            f"CRITICAL due_at must be created_at + 3 days, got {deficiency['due_at']}"
        )
        assert deficiency["status"] == "OPEN"

        # The very next read already reflects the incremented counter.
        project_after = get_project(project["id"])
        assert project_after["open_deficiency_count"] == 1
