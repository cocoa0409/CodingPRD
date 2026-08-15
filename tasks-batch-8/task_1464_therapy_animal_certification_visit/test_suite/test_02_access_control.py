"""Access control: role authorization, ownership, pipeline ordering, SoD."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    complete_visit_ok,
    create_active_evaluator,
    create_active_handler,
    create_applicant_handler,
    create_forming_team,
    file_incident_ok,
    register_animal,
    request_evaluation,
    schedule_evaluation_ok,
    schedule_visit_ok,
    set_clock,
    setup_certified_team_at_facility,
    triage_incident_ok,
    make_evaluator_headers,
    make_facility_coordinator_headers,
    make_handler_headers,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_2 = TEST_USERS["compliance_officer_2_headers"]


class TestRoleAuthorization:
    def test_handler_cannot_approve_handler(self):
        """PRD §2.1: "A request whose role is not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.1: "A `ProgramAdmin` reviews the application: approval moves the handler `APPLICANT → ACTIVE`, and rejection — a call that carries a `reason` — moves it to the terminal `REJECTED` state; either action on a handler no longer in `APPLICANT` fails with `ERR_HANDLER_NOT_APPLICANT`."

        Design: Corner/rbac/handler_cannot_approve_handler
        """
        handler = create_applicant_handler(full_name="H RB1")
        resp = api_client.approve_handler(handler["id"], make_handler_headers(handler["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_role_check_precedes_existence(self):
        """PRD §2.7: "Every request is evaluated against a fixed pipeline of check categories, in the order below, and the first category that fails determines the rejection. The ordering is load-bearing: an authentication failure masks everything downstream; a stale-version rejection surfaces before any state-machine precondition is examined; a segregation-of-duties violation is reported only after every other check has passed."
        PRD §2.7: "2. **Role authorization.** The role appears in the endpoint's authorized list — otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). Applies to all endpoints."

        Design: Corner/validations/role_check_precedes_existence
        """
        handler = create_active_handler(full_name="H PR")
        resp = api_client.update_facility(
            NON_EXISTENT_UUID, {"max_visit_minutes": 45}, make_handler_headers(handler["id"])
        )
        # Role authorization (category 2) fires before path existence (category 4).
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestOwnership:
    def test_evaluator_cannot_score_unassigned_evaluation(self):
        """PRD §3.2: "Scoring belongs to the assigned `Evaluator` and only after the session has concluded: the evaluation must be `SCHEDULED` (otherwise `ERR_EVALUATION_NOT_SCHEDULED`), the acting evaluator must be the one named in `evaluator_id` (otherwise `ERR_OWNERSHIP_MISMATCH`), and the current time must be at or past `scheduled_end` (otherwise `ERR_EVALUATION_NOT_CONCLUDED`)."

        Design: Corner/rbac/evaluator_cannot_score_unassigned_evaluation
        """
        handler = create_active_handler(full_name="H RB2")
        animal = register_animal(handler["id"], name="D")
        team = create_forming_team(handler["id"], animal["id"], "TRB2")
        evaluation = request_evaluation(handler["id"], team["id"])
        ev1 = create_active_evaluator(full_name="Ev One", specializations=["DOG"])
        ev2 = create_active_evaluator(full_name="Ev Two", specializations=["DOG"])
        schedule_evaluation_ok(evaluation["id"], ev1["id"])
        set_clock("2026-08-02T11:00:00Z")
        resp = api_client.score_evaluation(
            evaluation["id"], {"aptitude_score": 90, "obedience_score": 90},
            make_evaluator_headers(ev2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    def test_facility_coordinator_cannot_verify_other_facility(self):
        """PRD §2.1: "`FacilityCoordinator` is the facility-side counterpart: when `X-User-Role` is `FacilityCoordinator`, `X-User-ID` is the `id` of the coordinator's Facility record, and ownership checks on visit requests, orientation records, agreements, and visits compare the target resource's `facility_id` to `X-User-ID`."
        PRD §3.8: "The coordinator of the visit's facility verifies a completed visit (`ERR_VISIT_NOT_COMPLETED` otherwise) still `UNVERIFIED` (`ERR_VISIT_ALREADY_RESOLVED` otherwise), with the usual facility ownership check: `verified_at` is stamped, and the credit is reconciled in two postings — a `REVERSAL` row negating the provisional amount, then a `FINAL` row computed as the smallest of the visit's `actual_minutes`, its scheduled minutes, and the effective cap in minutes, divided by fifteen, rounded half-up to the nearest whole unit, and multiplied by fifteen."

        Design: Corner/rbac/facility_coordinator_cannot_verify_other_facility
        """
        ctx = setup_certified_team_at_facility()
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z")
        complete_visit_ok(visit["id"], ctx["handler"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z")
        # A second facility whose coordinator does not own the visit's facility.
        other = validate_success(api_client.create_facility(
            {
                "name": "Fac F2", "facility_type": "SCHOOL", "region_code": "WA",
                "max_visit_minutes": 60, "allowed_species": ["DOG"],
                "min_liability_coverage_cents": 100_000_000,
                "max_overlapping_teams": 2, "visits_per_week_cap": 5,
            }, ADMIN,
        ), 201)
        resp = api_client.verify_visit(
            visit["id"], make_facility_coordinator_headers(other["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    def test_ownership_mismatch_on_checkin_returns_403(self):
        """PRD §3.7: "Check-in belongs to the handler who owns the visit's team (otherwise `ERR_OWNERSHIP_MISMATCH`) and requires the visit still `SCHEDULED` (otherwise `ERR_VISIT_NOT_SCHEDULED`)."
        PRD §2.1: "Wherever an entity-backed actor touches a resource it does not own, the rejection is `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/validations/ownership_mismatch_on_checkin_returns_403
        """
        ctx = setup_certified_team_at_facility()
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        other_handler = create_active_handler(full_name="H O2")
        set_clock("2026-08-03T10:00:00Z")
        resp = api_client.check_in_visit(visit["id"], make_handler_headers(other_handler["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


class TestSegregationOfDuties:
    def test_sod_triager_cannot_resolve(self):
        """PRD §3.9: "A `ComplianceOfficer` resolves from `UNDER_REVIEW` or `ESCALATED` (otherwise `ERR_INCIDENT_NOT_RESOLVABLE`), and the resolving officer's `X-User-ID` must differ from the recorded `triaged_by` — a self-resolution fails with `ERR_SOD_VIOLATION`, the final check of the pipeline."

        Design: Corner/rbac/sod_triager_cannot_resolve
        """
        ctx = setup_certified_team_at_facility()
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z")
        complete_visit_ok(visit["id"], ctx["handler"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z")
        incident = file_incident_ok(
            visit["id"], make_facility_coordinator_headers(ctx["facility"]["id"]),
            severity="LOW", category="PROTOCOL_BREACH",
            description="handler skipped sign-in sheet",
        )
        triage_incident_ok(incident["id"], COMPLIANCE)

        resp = api_client.resolve_incident(incident["id"], {"resolution_code": "NO_ACTION"}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        resolved = validate_success(
            api_client.resolve_incident(incident["id"], {"resolution_code": "NO_ACTION"}, COMPLIANCE_2)
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_code"] == "NO_ACTION"
