"""Hot work permitting: issuer gates, half-open window conflicts, validation
pipeline precedence, terminal-state lockdown, and issuer/performer RBAC."""
from test_helpers import (
    MLEAD,
    ApiErrorId,
    api_client,
    create_contractor,
    create_facility,
    create_hot_work_permit_payload,
    create_system,
    create_employee,
    make_contractor_rep_headers,
    make_operator_headers,
    qualify_contractor,
    set_clock,
    setup_issued_permit,
    setup_requested_permit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestContractorQualificationGate:

    def test_permit_issue_blocked_for_pending_contractor(self):
        """PRD section 3.7: "A `MaintenanceLead` moves a `REQUESTED` permit to
        `ISSUED` only through five gates: the contractor currently `QUALIFIED`
        (`ERR_CONTRACTOR_NOT_QUALIFIED`), the system `IN_SERVICE`
        (`ERR_SYSTEM_OUT_OF_SERVICE`), no equipment on the system standing
        `FAILED` (`ERR_EQUIPMENT_INTEGRITY_FAILED`), the facility not
        `NONCOMPLIANT` (`ERR_FACILITY_NONCOMPLIANT`), and the window-conflict
        check re-evaluated against the live permit book, since other permits
        may have appeared since the request."

        Design: Difficulty/cross_entity_state_dependency/permit_issue_requires_contractor_qualified
        """
        facility, system, contractor, permit, rep_headers = setup_requested_permit(
            qualify=False)
        assert contractor["qualification_status"] == "PENDING"
        resp = api_client.issue_permit(permit["id"], MLEAD)
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_NOT_QUALIFIED,
                       expected_status=422)

    def test_permit_issue_succeeds_after_qualify(self):
        """PRD section 3.7: "A `MaintenanceLead` moves a `REQUESTED` permit to
        `ISSUED` only through five gates: the contractor currently `QUALIFIED`
        (`ERR_CONTRACTOR_NOT_QUALIFIED`), the system `IN_SERVICE`
        (`ERR_SYSTEM_OUT_OF_SERVICE`), no equipment on the system standing
        `FAILED` (`ERR_EQUIPMENT_INTEGRITY_FAILED`), the facility not
        `NONCOMPLIANT` (`ERR_FACILITY_NONCOMPLIANT`), and the window-conflict
        check re-evaluated against the live permit book, since other permits
        may have appeared since the request."
        PRD section 3.7: "Qualification supplies a `qualified_until` timestamp
        that must lie in the future of the logical clock — a past or present
        timestamp is `ERR_INVALID_WINDOW` — and moves `PENDING` to `QUALIFIED`,
        or renews an `EXPIRED` record back to `QUALIFIED`."

        Design: Difficulty/cross_entity_state_dependency/permit_issue_requires_contractor_qualified
        """
        facility, system, contractor, permit, rep_headers = setup_requested_permit(
            qualify=False)
        # only the Contractor entity changes between the two issue attempts
        qualify_contractor(contractor["id"], "2027-06-01T00:00:00Z")
        issued = validate_success(api_client.issue_permit(permit["id"], MLEAD),
                                  expected_status=200)
        assert issued["status"] == "ISSUED"


class TestPermitWindowOverlap:

    def test_permit_adjacent_windows_allowed(self):
        """PRD section 3.7: "And the window must not collide with any other
        permit on the same system standing `REQUESTED`, `ISSUED`, or
        `IN_PROGRESS`: two windows overlap when each begins before the other
        ends, while touching endpoints — one window beginning exactly as
        another ends — do not conflict; a genuine overlap is rejected with
        `ERR_PERMIT_WINDOW_CONFLICT` (409)."
        PRD section 3.7: "A clean request stands `REQUESTED`."

        Design: Difficulty/resource_temporal_overlap/permit_half_open_window_overlap
        """
        facility, system, contractor, permit1, rep_headers = setup_requested_permit(
            qualify=False, work_description="P1 08-12")
        assert permit1["status"] == "REQUESTED"
        # [12:00, 16:00) touches [08:00, 12:00) — half-open, no overlap
        resp = api_client.create_hot_work_permit(
            create_hot_work_permit_payload(
                facility["id"], system["id"], contractor["id"],
                work_description="P2 12-16 adjacent",
                valid_from="2026-09-01T12:00:00Z",
                valid_until="2026-09-01T16:00:00Z"),
            rep_headers)
        permit2 = validate_success(resp, expected_status=201)
        assert permit2["status"] == "REQUESTED"

    def test_permit_interior_overlap_rejected(self):
        """PRD section 3.7: "And the window must not collide with any other
        permit on the same system standing `REQUESTED`, `ISSUED`, or
        `IN_PROGRESS`: two windows overlap when each begins before the other
        ends, while touching endpoints — one window beginning exactly as
        another ends — do not conflict; a genuine overlap is rejected with
        `ERR_PERMIT_WINDOW_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/permit_half_open_window_overlap
        """
        facility, system, contractor, permit1, rep_headers = setup_requested_permit(
            qualify=False, work_description="P1 08-12")
        # [11:30, 13:00) intersects [08:00, 12:00) in its interior
        resp = api_client.create_hot_work_permit(
            create_hot_work_permit_payload(
                facility["id"], system["id"], contractor["id"],
                work_description="P3 11:30-13:00 overlapping",
                valid_from="2026-09-01T11:30:00Z",
                valid_until="2026-09-01T13:00:00Z"),
            rep_headers)
        validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_CONFLICT,
                       expected_status=409)


class TestValidationPipelinePrecedence:

    def test_permit_issue_state_beats_safety_when_both_fail(self):
        """PRD section 2.9: "Every well-formed request is then evaluated
        against an ordered pipeline of checks, and a failure at any stage
        short-circuits every later stage, so the earliest failing check
        determines the error returned."
        PRD section 2.9: "Source-state validity fifth: the target stands in a
        state that permits the requested transition — issuance only from
        `REQUESTED`, permit closure only from `IN_PROGRESS`, investigator
        assignment only from `REPORTED` or `REOPENED`, leak confirmation only
        from `SUSPECTED`, and so on (`ERR_INVALID_STATE`, 409)."
        PRD section 2.9: "Safety and compliance gates sixth: contractor
        qualification, system in service, equipment integrity, facility
        posture, the investigator-is-not-reporter and verifier-is-not-completer
        segregations, and the drill training quorum
        (`ERR_CONTRACTOR_NOT_QUALIFIED`, `ERR_SYSTEM_OUT_OF_SERVICE`,
        `ERR_EQUIPMENT_INTEGRITY_FAILED`, `ERR_FACILITY_NONCOMPLIANT`,
        `ERR_INVESTIGATOR_IS_REPORTER`, `ERR_VERIFIER_IS_COMPLETER`,
        `ERR_DRILL_TRAINING_SHORTFALL`)."

        Design: Difficulty/priority_pair_validation_conflict/permit_issue_state_beats_safety_rejected
        """
        facility, system, contractor, permit, rep_headers = setup_requested_permit(
            qualified_until="2027-01-01T00:00:00Z")
        # both violations armed: contractor SUSPENDED, permit VOIDED
        validate_success(api_client.suspend_contractor(contractor["id"], MLEAD), 200)
        validate_success(api_client.void_permit(permit["id"], MLEAD), 200)
        resp = api_client.issue_permit(permit["id"], MLEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_permit_issue_state_leg_alone_on_voided_permit(self):
        """PRD section 2.9: "Source-state validity fifth: the target stands in
        a state that permits the requested transition — issuance only from
        `REQUESTED`, permit closure only from `IN_PROGRESS`, investigator
        assignment only from `REPORTED` or `REOPENED`, leak confirmation only
        from `SUSPECTED`, and so on (`ERR_INVALID_STATE`, 409)."
        PRD section 3.7: "A `MaintenanceLead` may void a permit that stands
        `REQUESTED` or `ISSUED`, moving it to `VOIDED`."

        Design: Difficulty/priority_pair_validation_conflict/permit_issue_state_beats_safety_rejected
        """
        facility, system, contractor, permit, rep_headers = setup_requested_permit()
        # safety gate would pass (contractor QUALIFIED); only the state leg fails
        validate_success(api_client.void_permit(permit["id"], MLEAD), 200)
        resp = api_client.issue_permit(permit["id"], MLEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestPermitCreatePrecedence:

    def test_permit_create_temporal_beats_constraint(self):
        """PRD section 2.9: "Temporal window sanity seventh: permit and drill
        windows well formed, qualification expiries in the future, permit
        starts inside the validity window (`ERR_INVALID_WINDOW`,
        `ERR_PERMIT_OUTSIDE_WINDOW`)."
        PRD section 2.9: "Resource conflicts eighth: permit window overlap on a
        shared system and the drill quiet gap (`ERR_PERMIT_WINDOW_CONFLICT`,
        `ERR_DRILL_GAP_VIOLATION`)."
        PRD section 3.7: "The window is half-open — it begins at `valid_from`
        inclusive and ends at `valid_until` exclusive — and the start must
        precede the end (`ERR_INVALID_WINDOW`)."

        Design: Difficulty/priority_pair_validation_conflict/permit_create_temporal_beats_constraint_rejected
        """
        facility, system, contractor, permit1, rep_headers = setup_requested_permit(
            qualify=False, work_description="P1 morning weld",
            valid_from="2026-09-01T08:00:00Z", valid_until="2026-09-01T17:00:00Z")
        # inverted window (12:00 >= 09:00) that also overlaps P1
        resp = api_client.create_hot_work_permit(
            create_hot_work_permit_payload(
                facility["id"], system["id"], contractor["id"],
                work_description="P2 inverted window overlapping P1",
                valid_from="2026-09-01T12:00:00Z",
                valid_until="2026-09-01T09:00:00Z"),
            rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW, expected_status=422)
        permits, meta = validate_paginated(api_client.list_hot_work_permits(
            MLEAD, params={"system_id": system["id"]}))
        assert meta["total_count"] == 1, "no second permit may be persisted"
        permit1_after = validate_success(
            api_client.get_hot_work_permit(permit1["id"], MLEAD),
            expected_status=200)
        assert permit1_after["status"] == "REQUESTED"

    def test_permit_create_inverted_window_alone(self):
        """PRD section 3.7: "The window is half-open — it begins at `valid_from`
        inclusive and ends at `valid_until` exclusive — and the start must
        precede the end (`ERR_INVALID_WINDOW`)."

        Design: Difficulty/priority_pair_validation_conflict/permit_create_temporal_beats_constraint_rejected
        """
        facility, system, contractor, permit1, rep_headers = setup_requested_permit(
            qualify=False)
        # inverted window on a different, non-overlapping day: only the
        # temporal leg can fail, and it must report ERR_INVALID_WINDOW
        resp = api_client.create_hot_work_permit(
            create_hot_work_permit_payload(
                facility["id"], system["id"], contractor["id"],
                work_description="inverted window, clear day",
                valid_from="2026-09-05T12:00:00Z",
                valid_until="2026-09-05T09:00:00Z"),
            rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW, expected_status=422)


class TestPermitLifecycleEdges:

    def test_void_closed_permit_rejected(self):
        """PRD section 3.7: "A `MaintenanceLead` may void a permit that stands
        `REQUESTED` or `ISSUED`, moving it to `VOIDED`."
        PRD section 3.7: "`CLOSED`, `VOIDED`, and `EXPIRED` are terminal."
        PRD section 2.9: "Source-state validity fifth: the target stands in a
        state that permits the requested transition — issuance only from
        `REQUESTED`, permit closure only from `IN_PROGRESS`, investigator
        assignment only from `REPORTED` or `REOPENED`, leak confirmation only
        from `SUSPECTED`, and so on (`ERR_INVALID_STATE`, 409)."

        Design: Corner/state_machines/void_closed_permit_rejected
        """
        facility, system, contractor, permit, rep_headers = setup_issued_permit()
        set_clock("2026-09-01T09:00:00Z")
        started = validate_success(api_client.start_permit(permit["id"], rep_headers),
                                   expected_status=200)
        assert started["status"] == "IN_PROGRESS"
        closed = validate_success(api_client.close_permit(permit["id"], rep_headers),
                                  expected_status=200)
        assert closed["status"] == "CLOSED"

        resp = api_client.void_permit(permit["id"], MLEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api_client.get_hot_work_permit(permit["id"], MLEAD),
                                 expected_status=200)
        assert after["status"] == "CLOSED"

    def test_permit_start_outside_window_rejected(self):
        """PRD section 3.7: "Three gates apply at the moment of starting: the
        logical clock must sit inside the window, at or after `valid_from` and
        strictly before `valid_until` (`ERR_PERMIT_OUTSIDE_WINDOW`, 409); the
        contractor must still be `QUALIFIED` (`ERR_CONTRACTOR_NOT_QUALIFIED`);
        and no equipment on the system may stand `FAILED`
        (`ERR_EQUIPMENT_INTEGRITY_FAILED`)."

        Design: Corner/validations/permit_start_outside_window_rejected
        """
        facility, system, contractor, permit, rep_headers = setup_issued_permit()
        assert permit["status"] == "ISSUED"
        # clock a week and a half before the window opens
        set_clock("2026-08-20T09:00:00Z")
        resp = api_client.start_permit(permit["id"], rep_headers)
        validate_error(resp, ApiErrorId.ERR_PERMIT_OUTSIDE_WINDOW,
                       expected_status=409)
        after = validate_success(api_client.get_hot_work_permit(permit["id"], MLEAD),
                                 expected_status=200)
        assert after["status"] == "ISSUED"

    def test_permit_cross_facility_system_rejected(self):
        """PRD section 2.10: "Facilities are hard tenancy boundaries. Whenever
        a request references a refrigeration system, that system must belong to
        the facility named on the acted resource — this holds when posting a
        charge adjustment with an optional system attribution and when
        requesting a hot work permit."
        PRD section 2.10: "Any breach of these rules is rejected with
        `ERR_CROSS_FACILITY_REFERENCE` (422)."

        Design: Corner/validations/permit_cross_facility_system_rejected
        """
        plant_a = create_facility(name="Plant A")
        plant_b = create_facility(name="Plant B")
        system_b = create_system(plant_b["id"], name="ER-B1",
                                 design_charge_lbs=3000)
        contractor = create_contractor()
        rep_headers = make_contractor_rep_headers(contractor["id"])
        resp = api_client.create_hot_work_permit(
            create_hot_work_permit_payload(
                plant_a["id"], system_b["id"], contractor["id"],
                work_description="cross-plant confusion"),
            rep_headers)
        validate_error(resp, ApiErrorId.ERR_CROSS_FACILITY_REFERENCE,
                       expected_status=422)


class TestPermitRbac:

    def test_operator_cannot_issue_permit(self):
        """PRD section 2.1: "`MaintenanceLead` is the mechanical-integrity
        lead, owning the equipment registry, the inspection program, contractor
        qualification, and the issuer side of hot work permitting — issuance
        and voiding, never performance."
        PRD section 2.1: "A request whose role is not permitted for the target
        endpoint, or that fails an entity-backed ownership check, is rejected
        with `ERR_FORBIDDEN` (403)."

        Design: Corner/rbac/operator_cannot_issue_permit
        """
        facility, system, contractor, permit, rep_headers = setup_requested_permit(
            qualify=False)
        employee = create_employee(facility["id"], "Olivia Operator")
        resp = api_client.issue_permit(permit["id"],
                                       make_operator_headers(employee["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        after = validate_success(api_client.get_hot_work_permit(permit["id"], MLEAD),
                                 expected_status=200)
        assert after["status"] == "REQUESTED"

    def test_contractor_cannot_void_permit(self):
        """PRD section 2.1: "`ContractorRep` represents a `Contractor` company,
        requesting hot work permits and starting or closing permitted work —
        the performer side of the permit segregation, never the issuer."
        PRD section 2.1: "A request whose role is not permitted for the target
        endpoint, or that fails an entity-backed ownership check, is rejected
        with `ERR_FORBIDDEN` (403)."

        Design: Corner/rbac/contractor_cannot_void_permit
        """
        facility, system, contractor, permit, rep_headers = setup_requested_permit(
            qualify=False)
        # the performing contractor cannot void even its own permit
        resp = api_client.void_permit(permit["id"], rep_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        after = validate_success(api_client.get_hot_work_permit(permit["id"], MLEAD),
                                 expected_status=200)
        assert after["status"] == "REQUESTED"
