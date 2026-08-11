"""Repeat-offender scoring, program bands, and prevention-training cascade
(PRD §3.2, §3.4, §3.7)."""
from test_helpers import (
    ApiErrorId,
    add_evidence,
    begin_investigation,
    create_allocation,
    create_case,
    create_course,
    create_excavator,
    create_locate_ticket_payload,
    create_violation,
    evaluate_program,
    finalize_allocation,
    get_excavator,
    make_excavator_headers,
    make_investigator_headers,
    make_manager_headers,
    parse_iso,
    propose_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = make_manager_headers("mgr-1")


def _seed_violation(excavator_id: str, address: str, severity: str, occurred_at: str) -> dict:
    case = create_case(excavator_id, address, "GAS", severity, occurred_at)
    return create_violation(excavator_id, case["id"])


def _list_violations_for_case(api, case_id: str) -> list:
    resp = api.list_violation_records(MANAGER, params={"damage_case_id": case_id})
    data, _meta = validate_paginated(resp)
    return [v for v in data if v.get("damage_case_id") in (None, case_id)]


def _list_assignments_for_excavator(api, excavator_id: str) -> list:
    resp = api.list_training_assignments(MANAGER, params={"excavator_id": excavator_id})
    data, _meta = validate_paginated(resp)
    return [a for a in data if a.get("excavator_id") in (None, excavator_id)]


class TestOffenderBoundary:
    def test_offender_points_exactly_12_probation(self, api):
        """PRD §3.7: "The band mapping is inclusive at every threshold: points at or
        above 18 yield `SUSPENDED`; at or above 12 yield `PROBATION`; at or above 6
        yield `WATCH`; otherwise `GOOD_STANDING`." Three MAJOR violations give exactly
        12 points, which meets the inclusive PROBATION boundary.

        Design: Difficulty/boundary_precision_check/offender_points_exactly_12_probation_10_watch
        """
        ex_a = create_excavator(company_name="DigA", contact_email="a@x.com")
        for i in range(3):
            _seed_violation(ex_a["id"], f"{i + 1} A St", "MAJOR", f"2026-04-0{i + 1}T09:00:00Z")
        result = evaluate_program(ex_a["id"])
        assert result["offender_points"] == 12
        assert result["program_status"] == "PROBATION", (
            f"12 >= 12 must yield PROBATION, got {result['program_status']}"
        )

    def test_offender_points_10_watch(self, api):
        """PRD §3.7: "The base `points` of a violation are determined by the linked
        case's `severity`: 2 for `MINOR`, 4 for `MAJOR`, 6 for `CRITICAL`." Two MAJOR
        plus one MINOR give 10 points — below the PROBATION boundary, inside WATCH.

        Design: Difficulty/boundary_precision_check/offender_points_exactly_12_probation_10_watch
        """
        ex_b = create_excavator(company_name="DigB", contact_email="b@x.com")
        _seed_violation(ex_b["id"], "1 B St", "MAJOR", "2026-04-01T09:00:00Z")
        _seed_violation(ex_b["id"], "2 B St", "MAJOR", "2026-04-02T09:00:00Z")
        _seed_violation(ex_b["id"], "3 B St", "MINOR", "2026-04-03T09:00:00Z")
        result = evaluate_program(ex_b["id"])
        assert result["offender_points"] == 10
        assert result["program_status"] == "WATCH", (
            f"10 is >= 6 and < 12, must yield WATCH, got {result['program_status']}"
        )


class TestFinalizeViolationTrainingCascade:
    def _setup_cascade(self):
        course = create_course("P101", "PROBATION")
        excavator = create_excavator()
        _seed_violation(excavator["id"], "10 Old Rd", "MAJOR", "2026-04-01T09:00:00Z")
        _seed_violation(excavator["id"], "11 Old Rd", "MAJOR", "2026-04-02T09:00:00Z")
        # Band still GOOD_STANDING: no evaluation has run yet (PRD §3.7).
        case = create_case(excavator["id"], "12 New Rd", "ELECTRIC", "CRITICAL",
                           "2026-05-08T09:00:00Z")
        add_evidence(case["id"], captured_at="2026-05-08T10:00:00Z")
        case = begin_investigation(case["id"], "inv-1")
        shares = [{"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 10000}]
        allocation = create_allocation(case["id"], case["version"],
                                       root_cause_code="NO_TICKET", shares=shares)
        propose_allocation(allocation["id"], "inv-1")
        return course, excavator, case, allocation

    def test_finalize_creates_violation_and_applies_probation_band(self, api):
        """PRD §3.4: "if the excavator's `share_bp` is at least 5000, a `ViolationRecord`
        is created against the case's `excavator_id` with points derived from the case's
        `severity` (2 for `MINOR`, 4 for `MAJOR`, 6 for `CRITICAL`)." PRD §3.4: "The
        violation creation triggers a recompute of the excavator's repeat-offender score
        (§3.7); the new band applies immediately if it is worse than the current band,
        and entering `PROBATION` or `SUSPENDED` from a better band auto-creates one
        `TrainingAssignment` per matching course."

        Design: Difficulty/transitive_cascade/finalize_violation_probation_training_cascade
        """
        _course, excavator, case, allocation = self._setup_cascade()
        validate_success(api.finalize_fault_allocation(allocation["id"], {}, MANAGER))
        violations = _list_violations_for_case(api, case["id"])
        assert len(violations) == 1
        assert violations[0]["points"] == 6, "CRITICAL severity yields 6 base points"
        excavator_after = get_excavator(excavator["id"])
        assert excavator_after["offender_points"] == 14, (
            f"8 seed + 6 new = 14, got {excavator_after['offender_points']}"
        )
        assert excavator_after["program_status"] == "PROBATION", (
            f"14 >= 12 must apply PROBATION immediately, got {excavator_after['program_status']}"
        )

    def test_finalize_cascade_auto_creates_matching_training_assignment(self, api):
        """PRD §3.4: "entering `PROBATION` or `SUSPENDED` from a better band auto-creates
        one `TrainingAssignment` per matching course." PRD §3.7: "Each new assignment
        starts in `ASSIGNED` with `due_at` computed as ninety days after its
        `created_at` and `completed_at` null."

        Design: Difficulty/transitive_cascade/finalize_violation_probation_training_cascade
        """
        course, excavator, _case, allocation = self._setup_cascade()
        validate_success(api.finalize_fault_allocation(allocation["id"], {}, MANAGER))
        assignments = _list_assignments_for_excavator(api, excavator["id"])
        assert len(assignments) == 1, (
            f"exactly one assignment expected for the single PROBATION course, got {len(assignments)}"
        )
        assignment = assignments[0]
        assert assignment["course_id"] == course["id"]
        assert assignment["status"] == "ASSIGNED"
        delta = parse_iso(assignment["due_at"]) - parse_iso(assignment["created_at"])
        assert delta.days == 90, f"due_at must be created_at + 90 days, got {delta}"


class TestOverturnedExclusion:
    def test_offender_score_excludes_overturned_violations(self, api):
        """PRD §3.7: "The excavator's `offender_points` is the sum of these effective
        points across `ACTIVE` violations only — `OVERTURNED` rows are excluded."
        Overturning one of three MAJOR violations drops the score from 12 to 8, and the
        next evaluation bands WATCH instead of PROBATION.

        Design: Corner/calculations/offender_score_excludes_overturned_violations
        """
        excavator = create_excavator()
        _seed_violation(excavator["id"], "13 A St", "MAJOR", "2026-04-01T09:00:00Z")
        case2 = create_case(excavator["id"], "14 B St", "GAS", "MAJOR", "2026-04-02T09:00:00Z")
        v2 = create_violation(excavator["id"], case2["id"])
        _seed_violation(excavator["id"], "15 C St", "MAJOR", "2026-04-03T09:00:00Z")
        resp = api.overturn_violation(v2["id"], MANAGER)
        overturned = validate_success(resp)
        assert overturned["status"] == "OVERTURNED"
        result = evaluate_program(excavator["id"])
        assert result["offender_points"] == 8, (
            f"12 - 4 overturned = 8, got {result['offender_points']}"
        )
        assert result["program_status"] == "WATCH"


class TestProgramGates:
    def test_suspended_excavator_cannot_file_ticket(self, api):
        """PRD §3.2: "A ticket filed by a `SUSPENDED` excavator is rejected with
        `ERR_PROGRAM_SUSPENDED` (HTTP 409)." Three CRITICAL violations give 18 points,
        meeting the inclusive SUSPENDED boundary (PRD §3.7).

        Design: Corner/errors/suspended_excavator_cannot_file_ticket
        """
        excavator = create_excavator()
        _seed_violation(excavator["id"], "36 Phi St", "CRITICAL", "2026-04-01T09:00:00Z")
        _seed_violation(excavator["id"], "37 Chi St", "CRITICAL", "2026-04-02T09:00:00Z")
        _seed_violation(excavator["id"], "38 Psi St", "CRITICAL", "2026-04-03T09:00:00Z")
        result = evaluate_program(excavator["id"])
        assert result["program_status"] == "SUSPENDED", "18 >= 18 must yield SUSPENDED"
        payload = create_locate_ticket_payload(
            excavator_id=excavator["id"], dig_site_address="39 Omega St",
            work_start_at="2026-06-01T08:00:00Z", work_end_at="2026-06-01T17:00:00Z",
        )
        resp = api.create_locate_ticket(payload, make_excavator_headers(excavator["id"]))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_SUSPENDED, expected_status=409)

    def test_duplicate_course_code_rejected(self, api):
        """PRD §3.1: "`course_code` is a natural key unique across all courses, and reuse
        is rejected with `ERR_DUPLICATE_COURSE_CODE` (HTTP 409)."

        Design: Corner/errors/duplicate_course_code_rejected
        """
        create_course("P101", "PROBATION")
        resp = api.create_training_course(
            {
                "course_code": "P101", "title": "Duplicate",
                "required_for_status": "WATCH", "credit_hours": 4,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_COURSE_CODE, expected_status=409)
