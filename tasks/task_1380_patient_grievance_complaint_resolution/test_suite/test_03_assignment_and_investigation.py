"""Assignment (explicit, selector, supersede, release), investigation
lifecycle, evidence floor, notes immutability, and interview booking rules."""
from test_helpers import (
    add_note,
    ApiErrorId,
    assert_investigation_note,
    assign_investigator,
    classify_case,
    create_case,
    create_interview_booking_payload,
    create_interview_room_payload,
    create_staff,
    create_unit,
    get_case,
    get_case_version,
    get_staff,
    get_success_data,
    make_director_headers,
    make_investigator_headers,
    open_investigation,
    set_clock,
    setup_assigned_case,
    setup_classified_case,
    setup_open_investigation,
    submit_findings,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


class TestInvestigationRequiresActivePrimary:
    def _setup_assigned_without_primary(self, api):
        """Case ASSIGNED holding only a SUPPORTING assignment (no PRIMARY)."""
        base = setup_classified_case(decision="GRIEVANCE", unit_name="Ortho",
                                     unit_category="SURGICAL",
                                     patient_ref="P-9002", channel="EMAIL",
                                     description="Post-op instructions unclear",
                                     grievance_category="COMMUNICATION")
        inv1 = create_staff("Ivy One", ["INVESTIGATOR"])
        inv2 = create_staff("Ivy Two", ["INVESTIGATOR"])
        director = create_staff("Dana Director", ["DIRECTOR"])
        assign_investigator(base.case["id"], director["id"], inv1["id"],
                            assignment_role="SUPPORTING")
        return base, inv1, inv2, director

    def test_open_investigation_without_active_primary_rejected(self, api):
        """PRD §3.3: "A `DepartmentInvestigator` opens it while the case is
        `ASSIGNED` (`ERR_CASE_INVALID_STATE` otherwise), and opening requires
        an `ACTIVE` `PRIMARY` assignment on the case — without one the request
        fails with `ERR_NO_ACTIVE_PRIMARY_ASSIGNMENT`."

        Design: Difficulty/cross_entity_state_dependency/investigation_requires_active_primary_assignment
        """
        base, inv1, _inv2, _director = self._setup_assigned_without_primary(api)
        assert get_case(base.case["id"])["lifecycle_status"] == "ASSIGNED"
        resp = api.create_investigation(base.case["id"],
                                        make_investigator_headers(inv1["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PRIMARY_ASSIGNMENT)

    def test_open_investigation_succeeds_once_primary_exists(self, api):
        """PRD §3.3: "A `DepartmentInvestigator` opens it while the case is
        `ASSIGNED` (`ERR_CASE_INVALID_STATE` otherwise), and opening requires
        an `ACTIVE` `PRIMARY` assignment on the case — without one the request
        fails with `ERR_NO_ACTIVE_PRIMARY_ASSIGNMENT`." and "The investigation
        begins `OPEN` and the case moves `ASSIGNED` → `UNDER_INVESTIGATION`."

        Design: Difficulty/cross_entity_state_dependency/investigation_requires_active_primary_assignment
        """
        base, _inv1, inv2, director = self._setup_assigned_without_primary(api)
        assign_investigator(base.case["id"], director["id"], inv2["id"],
                            assignment_role="PRIMARY")
        investigation = open_investigation(base.case["id"], inv2["id"])
        assert investigation["status"] == "OPEN"
        assert get_case(base.case["id"])["lifecycle_status"] == "UNDER_INVESTIGATION"


class TestAssignmentConstraints:
    def test_explicit_investigator_at_capacity_rejected(self, api):
        """PRD §3.3: "A named investigator must hold the `INVESTIGATOR`
        capability, must not be on leave (`ERR_ADVOCATE_ON_LEAVE`), and must
        have `open_assignment_count` below their `max_concurrent_assignments`
        (`ERR_INVESTIGATOR_AT_CAPACITY`)"

        Design: Corner/validations/explicit_investigator_at_capacity_rejected
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("Renal", "INPATIENT")
        inv = create_staff("Ivy Investigator", ["INVESTIGATOR"],
                           max_concurrent_assignments=1)
        director = create_staff("Dana Director", ["DIRECTOR"])
        case_a = create_case(unit["id"], patient_ref="P-0315",
                             received_at="2026-08-03T09:00:00.000Z",
                             description="Case A", grievance_category="OTHER")
        classify_case(case_a["id"], "GRIEVANCE")
        assign_investigator(case_a["id"], director["id"], inv["id"])

        case_b = create_case(unit["id"], patient_ref="P-0316", channel="EMAIL",
                             received_at="2026-08-03T09:00:00.000Z",
                             description="Case B", grievance_category="OTHER")
        classify_case(case_b["id"], "GRIEVANCE")
        resp = api.create_assignment(
            case_b["id"],
            {"investigator_id": inv["id"],
             "expected_case_version": get_case_version(case_b["id"])},
            make_director_headers(director["id"]))
        validate_error(resp, ApiErrorId.ERR_INVESTIGATOR_AT_CAPACITY)

    def test_duplicate_active_assignment_same_investigator_rejected(self, api):
        """PRD §3.3: "naming an investigator who already holds an `ACTIVE`
        assignment on the same case is rejected with
        `ERR_DUPLICATE_ACTIVE_ASSIGNMENT`."

        Design: Corner/validations/duplicate_active_assignment_same_investigator_rejected
        """
        base = setup_assigned_case(decision="GRIEVANCE", unit_name="Renal",
                                   unit_category="INPATIENT", patient_ref="P-0317",
                                   description="Case", grievance_category="OTHER")
        resp = api.create_assignment(
            base.case["id"],
            {"investigator_id": base.inv["id"],
             "expected_case_version": get_case_version(base.case["id"])},
            make_director_headers(base.director["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_ASSIGNMENT)


class TestAutoAssignmentSelector:
    def test_auto_assign_empty_pool_rejected(self, api):
        """PRD §3.3: "An empty pool rejects the request with
        `ERR_NO_ELIGIBLE_INVESTIGATOR` and the case remains `CLASSIFIED`."

        Design: Corner/validations/auto_assign_empty_pool_rejected
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED", "EMERGENCY")
        director = create_staff("Dana Director", ["DIRECTOR"])
        case = create_case(unit["id"], patient_ref="P-0323",
                           received_at="2026-08-03T09:00:00.000Z",
                           description="Concern", grievance_category="OTHER")
        classify_case(case["id"], "GRIEVANCE")
        resp = api.create_assignment(
            case["id"],
            {"expected_case_version": get_case_version(case["id"])},
            make_director_headers(director["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_INVESTIGATOR)
        assert get_case(case["id"])["lifecycle_status"] == "CLASSIFIED"

    def test_auto_assign_selector_ranking_and_exclusion(self, api):
        """PRD §3.3: "Eligibility requires the `INVESTIGATOR` capability,
        `on_leave` false, and assignment headroom; the eligible pool is ranked
        by `open_assignment_count` ascending, ties break by staff `created_at`
        ascending — earliest registered first, and the staff `id` is never used
        as a tiebreaker."

        Design: Corner/validations/auto_assign_selector_ranking_and_exclusion
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("Renal", "INPATIENT")
        inv_a = create_staff("Ivy A", ["INVESTIGATOR"])
        inv_b = create_staff("Ivy B", ["INVESTIGATOR"])
        inv_c = create_staff("Ivy C", ["INVESTIGATOR"], max_concurrent_assignments=5)
        get_success_data(api.patch_staff(inv_c["id"], {"on_leave": True}, ADMIN))
        director = create_staff("Dana Director", ["DIRECTOR"])

        case_a = create_case(unit["id"], patient_ref="P-0324",
                             received_at="2026-08-03T09:00:00.000Z",
                             description="Case one", grievance_category="OTHER")
        classify_case(case_a["id"], "GRIEVANCE")
        case_b = create_case(unit["id"], patient_ref="P-0325", channel="EMAIL",
                             received_at="2026-08-03T09:00:00.000Z",
                             description="Case two", grievance_category="OTHER")
        classify_case(case_b["id"], "GRIEVANCE")

        pick1 = validate_success(api.create_assignment(
            case_a["id"],
            {"expected_case_version": get_case_version(case_a["id"])},
            make_director_headers(director["id"])), expected_status=201)
        assert pick1["investigator_id"] == inv_a["id"], (
            "tie at zero open assignments resolves to earliest registered staff")

        pick2 = validate_success(api.create_assignment(
            case_b["id"],
            {"expected_case_version": get_case_version(case_b["id"])},
            make_director_headers(director["id"])), expected_status=201)
        assert pick2["investigator_id"] == inv_b["id"], (
            "0 open beats 1 open; the on-leave investigator is never eligible")


class TestAssignReleaseSupersedeInvariant:
    def _setup_two_cases_one_investigator(self, api):
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("Renal", "INPATIENT")
        inv1 = create_staff("Ivy One", ["INVESTIGATOR"])
        inv2 = create_staff("Ivy Two", ["INVESTIGATOR"])
        director = create_staff("Dana Director", ["DIRECTOR"])
        case_a = create_case(unit["id"], patient_ref="P-9301",
                             received_at="2026-08-03T09:00:00.000Z",
                             description="Dialysis scheduling A",
                             grievance_category="ACCESS_DELAY")
        classify_case(case_a["id"], "GRIEVANCE")
        assignment_a = assign_investigator(case_a["id"], director["id"], inv1["id"])
        case_b = create_case(unit["id"], patient_ref="P-9302", channel="EMAIL",
                             received_at="2026-08-03T09:00:00.000Z",
                             description="Dialysis scheduling B",
                             grievance_category="ACCESS_DELAY")
        classify_case(case_b["id"], "GRIEVANCE")
        assign_investigator(case_b["id"], director["id"], inv1["id"])
        return unit, inv1, inv2, director, case_a, case_b, assignment_a

    def test_release_then_supersede_conserves_open_assignment_count(self, api):
        """PRD §3.3: "A successful creation produces an `ACTIVE` assignment,
        raises the investigator's `open_assignment_count` by one" and
        "Supersede semantics govern primacy: when a new `PRIMARY` assignment
        arrives while an `ACTIVE` `PRIMARY` already exists on the case, the
        prior assignment is released — status `RELEASED`, `released_at` stamped
        with the current clock — and the previous investigator's
        `open_assignment_count` falls by one." and "The director may also
        release any `ACTIVE` assignment explicitly (optionally noting a
        `release_reason`); releasing anything not `ACTIVE` is rejected with
        `ERR_ASSIGNMENT_INVALID_STATE`, and a release stamps `released_at` and
        decrements the investigator's count."

        Design: Difficulty/compensating_invariant/assign_release_supersede_conserves_open_count
        """
        _unit, inv1, inv2, director, case_a, case_b, assignment_a = (
            self._setup_two_cases_one_investigator(api))
        mid = get_staff(inv1["id"])
        assert mid["open_assignment_count"] == 2, (
            "two ACTIVE assignments on the investigator")

        released = validate_success(api.release_assignment(
            assignment_a["id"], {"release_reason": "Workload rebalance"},
            make_director_headers(director["id"])))
        assert released["status"] == "RELEASED"

        # New PRIMARY on case B supersedes the previous ACTIVE PRIMARY.
        validate_success(api.create_assignment(
            case_b["id"],
            {"investigator_id": inv2["id"], "assignment_role": "PRIMARY",
             "expected_case_version": get_case_version(case_b["id"])},
            make_director_headers(director["id"])), expected_status=201)

        assert get_staff(inv1["id"])["open_assignment_count"] == 0, (
            "release (-1) then supersede (-1) returns the counter to zero")
        assert get_staff(inv2["id"])["open_assignment_count"] == 1

    def test_counter_equals_active_assignment_rows_exactly(self, api):
        """PRD §3.1: "a derived `open_assignment_count` of that person's
        currently `ACTIVE` assignments". PRD §3.3: "Supersede semantics govern
        primacy: when a new `PRIMARY` assignment arrives while an `ACTIVE`
        `PRIMARY` already exists on the case, the prior assignment is released
        — status `RELEASED`, `released_at` stamped with the current clock — and
        the previous investigator's `open_assignment_count` falls by one."

        Design: Difficulty/compensating_invariant/assign_release_supersede_conserves_open_count
        """
        _unit, inv1, inv2, director, case_a, case_b, assignment_a = (
            self._setup_two_cases_one_investigator(api))
        get_success_data(api.release_assignment(
            assignment_a["id"], {"release_reason": "Workload rebalance"},
            make_director_headers(director["id"])))
        get_success_data(api.create_assignment(
            case_b["id"],
            {"investigator_id": inv2["id"], "assignment_role": "PRIMARY",
             "expected_case_version": get_case_version(case_b["id"])},
            make_director_headers(director["id"])))

        active_rows, _ = validate_paginated(api.list_assignments(
            make_director_headers(director["id"]),
            params={"investigator_id": inv1["id"], "status": "ACTIVE"}))
        assert active_rows == [], (
            "counter must equal count(ACTIVE assignments) exactly — no drift "
            "from the release+supersede pair")
        assert get_staff(inv1["id"])["open_assignment_count"] == 0


class TestOccOnAssignment:
    def test_occ_stale_assignment_version_rejected(self, api):
        """PRD §2.7: "If the case's current `version` differs — because another
        writer has advanced it since the caller last read the case — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_assignment_version_rejected
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED", "EMERGENCY")
        inv1 = create_staff("Ivy One", ["INVESTIGATOR"])
        inv2 = create_staff("Ivy Two", ["INVESTIGATOR"])
        director = create_staff("Dana Director", ["DIRECTOR"])
        case = create_case(unit["id"], patient_ref="P-0602",
                           received_at="2026-08-03T09:00:00.000Z",
                           description="Concern", grievance_category="OTHER")
        classify_case(case["id"], "GRIEVANCE")
        stale_version = get_case_version(case["id"])

        first = api.create_assignment(
            case["id"], {"investigator_id": inv1["id"],
                         "expected_case_version": stale_version},
            make_director_headers(director["id"]))
        validate_success(first, expected_status=201)

        second = api.create_assignment(
            case["id"], {"investigator_id": inv2["id"],
                         "expected_case_version": stale_version},
            make_director_headers(director["id"]))
        validate_error(second, ApiErrorId.ERR_STALE_VERSION)

        active, _ = validate_paginated(api.list_assignments(
            make_director_headers(director["id"]),
            params={"case_id": case["id"], "status": "ACTIVE"}))
        assert len(active) == 1
        assert active[0]["investigator_id"] == inv1["id"], (
            "the stale write must not have superseded the live PRIMARY")


class TestEvidenceAndNotes:
    def test_submit_findings_evidence_boundary(self, api):
        """PRD §3.3: "Submission requires the investigation to be `OPEN`
        (`ERR_INVESTIGATION_INVALID_STATE` otherwise) and an evidence floor of
        at least two notes in total with at least one `INTERVIEW` note among
        them — anything thinner is rejected with
        `ERR_INSUFFICIENT_INVESTIGATION_EVIDENCE`."

        Design: Corner/validations/submit_findings_evidence_boundary
        """
        base = setup_open_investigation(unit_name="ED", unit_category="EMERGENCY",
                                        patient_ref="P-0322", description="Concern",
                                        grievance_category="OTHER")
        add_note(base.investigation["id"], base.inv["id"], "INTERVIEW",
                 "Only interview so far")
        resp = api.submit_findings(
            base.investigation["id"],
            {"care_concern_flag": False, "findings_summary": "Too early"},
            make_investigator_headers(base.inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVESTIGATION_EVIDENCE)

        add_note(base.investigation["id"], base.inv["id"], "DOCUMENT_REVIEW",
                 "Second note completes evidence")
        accepted = submit_findings(base.investigation["id"], base.inv["id"],
                                   findings_summary="Now sufficient")
        assert accepted["status"] == "FINDINGS_SUBMITTED", (
            "boundary: exactly 2 total notes with 1 INTERVIEW passes")

    def test_accept_findings_from_open_rejected(self, api):
        """PRD §3.3: "Both doors require `FINDINGS_SUBMITTED`; any other
        investigation state meets `ERR_INVESTIGATION_INVALID_STATE`."

        Design: Corner/state_machines/accept_findings_from_open_rejected
        """
        base = setup_open_investigation(unit_name="Ortho", unit_category="SURGICAL",
                                        patient_ref="P-0102", description="Concern",
                                        grievance_category="CARE_QUALITY")
        resp = api.accept_findings(base.investigation["id"],
                                   make_director_headers(base.director["id"]))
        validate_error(resp, ApiErrorId.ERR_INVESTIGATION_INVALID_STATE)

    def test_investigation_note_is_immutable(self, api):
        """PRD §2.5: "Three resources are deliberately lighter immutable
        records: a `ClassificationDecision`, an `InvestigationNote`, and a
        `HolidayObservance` carry only `id` and `created_at`. Neither
        `updated_at` nor `version` exists on them."

        Design: Corner/entities/investigation_note_is_immutable
        """
        base = setup_open_investigation(unit_name="Ortho", unit_category="SURGICAL",
                                        patient_ref="P-0005",
                                        description="Surgical site concern",
                                        grievance_category="CARE_QUALITY")
        note = add_note(base.investigation["id"], base.inv["id"], "INTERVIEW",
                        "Patient interview transcript summary")
        assert_investigation_note(note)

        fetched = get_success_data(api.get_note(
            note["id"], make_investigator_headers(base.inv["id"])))
        assert_investigation_note(fetched)
        assert fetched["body"] == "Patient interview transcript summary"
        assert fetched["note_type"] == "INTERVIEW"
        assert fetched["id"] == note["id"]


class TestInterviewBooking:
    def _setup_open_investigation_with_room(self, api):
        set_clock("2026-08-03T08:00:00.000Z")
        unit = create_unit("Neuro", "INPATIENT")
        inv1 = create_staff("Ivy One", ["INVESTIGATOR"])
        inv2 = create_staff("Ivy Two", ["INVESTIGATOR"])
        director = create_staff("Dana Director", ["DIRECTOR"])
        room = get_success_data(api.create_interview_room(
            create_interview_room_payload(name="Room 101", location="Tower 3F"),
            ADMIN))
        case = create_case(unit["id"], patient_ref="P-9101",
                           received_at="2026-08-03T07:00:00.000Z",
                           description="MRI scheduling concern",
                           grievance_category="ACCESS_DELAY")
        classify_case(case["id"], "GRIEVANCE")
        assign_investigator(case["id"], director["id"], inv1["id"])
        investigation = open_investigation(case["id"], inv1["id"])
        return unit, inv1, inv2, director, room, case, investigation

    def test_booking_by_non_assigned_investigator_identity_mismatch(self, api):
        """PRD §3.3: "the server records `booked_by_id` from the caller, and a
        caller who is not the case's `ACTIVE` `PRIMARY` investigator is
        rejected with `ERR_IDENTITY_MISMATCH`."

        Design: Corner/validations/booking_by_non_assigned_investigator_identity_mismatch
        """
        (_unit, _inv1, inv2, _director, room, _case, investigation) = (
            self._setup_open_investigation_with_room(api))
        resp = api.create_interview_booking(
            create_interview_booking_payload(
                investigation_id=investigation["id"], room_id=room["id"],
                start_at="2026-08-04T10:00:00.000Z", end_at="2026-08-04T11:00:00.000Z"),
            make_investigator_headers(inv2["id"]))
        validate_error(resp, ApiErrorId.ERR_IDENTITY_MISMATCH)

    def test_booking_buffer_gap_below_900_seconds_rejected(self, api):
        """PRD §3.3: "Bookings on the same room must respect a fifteen-minute
        turnover: the new booking must end no later than nine hundred seconds
        before an existing `BOOKED` booking starts, or start no earlier than
        nine hundred seconds after that booking ends. A gap of exactly nine
        hundred seconds on a side is allowed; eight hundred ninety-nine
        seconds, or any overlap, is rejected with
        `ERR_BOOKING_BUFFER_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/interview_booking_buffer_gap_boundary
        """
        (_unit, inv1, _inv2, _director, room, _case, investigation) = (
            self._setup_open_investigation_with_room(api))
        first = api.create_interview_booking(
            create_interview_booking_payload(
                investigation_id=investigation["id"], room_id=room["id"],
                start_at="2026-08-04T10:00:00.000Z", end_at="2026-08-04T11:00:00.000Z"),
            make_investigator_headers(inv1["id"]))
        validate_success(first, expected_status=201)

        resp = api.create_interview_booking(
            create_interview_booking_payload(
                investigation_id=investigation["id"], room_id=room["id"],
                start_at="2026-08-04T11:10:00.000Z", end_at="2026-08-04T12:00:00.000Z"),
            make_investigator_headers(inv1["id"]))
        validate_error(resp, ApiErrorId.ERR_BOOKING_BUFFER_VIOLATION)

    def test_booking_buffer_gap_exactly_900_seconds_allowed(self, api):
        """PRD §3.3: "A gap of exactly nine hundred seconds on a side is
        allowed; eight hundred ninety-nine seconds, or any overlap, is rejected
        with `ERR_BOOKING_BUFFER_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/interview_booking_buffer_gap_boundary
        """
        (_unit, inv1, _inv2, _director, room, _case, investigation) = (
            self._setup_open_investigation_with_room(api))
        validate_success(api.create_interview_booking(
            create_interview_booking_payload(
                investigation_id=investigation["id"], room_id=room["id"],
                start_at="2026-08-04T10:00:00.000Z", end_at="2026-08-04T11:00:00.000Z"),
            make_investigator_headers(inv1["id"])), expected_status=201)

        boundary = api.create_interview_booking(
            create_interview_booking_payload(
                investigation_id=investigation["id"], room_id=room["id"],
                start_at="2026-08-04T11:15:00.000Z", end_at="2026-08-04T12:00:00.000Z"),
            make_investigator_headers(inv1["id"]))
        booking = validate_success(boundary, expected_status=201)
        assert booking["status"] == "BOOKED", (
            "a gap of exactly 900 seconds satisfies the inclusive buffer boundary")
