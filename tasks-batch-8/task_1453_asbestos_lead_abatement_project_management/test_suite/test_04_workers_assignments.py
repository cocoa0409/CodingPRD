"""Worker registration and read consistency, the clock-driven lapse and
recertification cycle, the stop-work cascade, and crew-assignment safety,
window, overlap, and hours rules."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_crew_assignment,
    assert_worker,
    cancel_assignment,
    create_assignment_entity,
    create_assignment_payload,
    create_project_entity,
    create_worker_entity,
    create_worker_payload,
    get_project,
    get_worker,
    list_worker_assignments,
    set_clock,
    setup_acknowledged_notification,
    setup_assessed_project,
    setup_verified_containment,
    supervisor_headers,
    validate_error,
    validate_success,
)


class TestWorkerRegistration:
    def test_worker_create_read_consistent(self):
        """PRD section 3.5: "A registered worker starts `ACTIVE` with
        `assigned_scheduled_hours` at zero."
        PRD section 1: "The design favors immediate consistency: every derived
        quantity (square footage, fees, tonnage, scheduled hours) is
        recomputed at the moment the underlying fact changes"

        Design: Corner/consistency_model/worker_create_read_consistent
        """
        created = validate_success(api_client.create_worker(
            create_worker_payload(
                full_name="Han Read", certification_level="HANDLER",
                cert_expires_at="2027-01-01T00:00:00Z",
                medical_clearance_expires_at="2027-02-01T00:00:00Z",
                respirator_fit_expires_at="2027-03-01T00:00:00Z"),
            ADMIN), expected_status=201)
        fetched = get_worker(created["id"])
        assert_worker(fetched)
        assert fetched["full_name"] == "Han Read"
        assert fetched["certification_level"] == "HANDLER"
        assert fetched["status"] == "ACTIVE"
        assert fetched["assigned_scheduled_hours"] == 0
        assert fetched["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at must be stamped from the logical clock default, "
            f"got {fetched['created_at']}"
        )


class TestAssignmentGates:
    def test_create_assignment_with_unknown_worker_404(self):
        """PRD section 2.11: "Requests that address nested resources validate
        every referenced identifier in strict left-to-right order — path
        identifiers first, then body references — and reject with the 404
        error of the **first** reference that does not resolve."
        PRD section 2.11: "body references are validated in the order
        `project_id`, `survey_id`, `worker_id`, `unit_id`, `facility_id`."

        Design: Corner/entities/create_assignment_with_unknown_worker_returns_404
        """
        project = create_project_entity(name="P-FK",
                                        base_abatement_cost_cents=1_000)
        resp = api_client.create_assignment(
            create_assignment_payload(project["id"], NON_EXISTENT_UUID,
                                      role_on_site="HANDLER"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_WORKER_NOT_FOUND)

    def test_expiry_exactly_at_start_rejected(self):
        """PRD section 3.5: "the worker must be `ACTIVE` with all three expiry
        timestamps falling strictly after `start_at` (an expiry exactly equal
        to `start_at` renders the worker unfit, `ERR_WORKER_NOT_FIT`, 422)"

        Design: Corner/calculations/assignment_expiry_exactly_at_start_rejected
        """
        ctx = setup_assessed_project(name="P-C1", base_abatement_cost_cents=1_000)
        worker = create_worker_entity(
            full_name="Han Fit", certification_level="HANDLER",
            respirator_fit_expires_at="2026-08-11T00:00:00Z")
        # start_at exactly equals the respirator fit expiry -> unfit.
        resp = api_client.create_assignment(
            create_assignment_payload(
                ctx["project"]["id"], worker["id"], role_on_site="HANDLER",
                start_at="2026-08-11T00:00:00Z", end_at="2026-08-20T00:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_WORKER_NOT_FIT)
        # One second earlier: the expiry is strictly after start_at -> fit.
        ok = api_client.create_assignment(
            create_assignment_payload(
                ctx["project"]["id"], worker["id"], role_on_site="HANDLER",
                start_at="2026-08-10T23:59:59Z", end_at="2026-08-20T00:00:00Z"),
            ADMIN)
        data = validate_success(ok, expected_status=201)
        assert_crew_assignment(data)
        assert data["status"] == "SCHEDULED"

    def test_supervisor_role_with_handler_cert_rejected(self):
        """PRD section 3.5: "a `role_on_site` of `SUPERVISOR` requires the
        worker's `certification_level` to be `SUPERVISOR`
        (`ERR_CERTIFICATION_MISMATCH`, 422)"

        Design: Corner/validations/supervisor_role_with_handler_cert_rejected
        """
        ctx = setup_assessed_project(name="P-V3", base_abatement_cost_cents=1_000)
        worker = create_worker_entity(full_name="Han One",
                                      certification_level="HANDLER")
        resp = api_client.create_assignment(
            create_assignment_payload(
                ctx["project"]["id"], worker["id"], role_on_site="SUPERVISOR",
                start_at="2026-08-11T00:00:00Z", end_at="2026-08-20T00:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_MISMATCH)

    def test_assignment_inverted_window_rejected(self):
        """PRD section 3.5: "then the window itself, where an `end_at` that is
        not strictly after `start_at` fails with `ERR_INVALID_WINDOW` (422)"

        Design: Corner/validations/assignment_inverted_window_rejected
        """
        ctx = setup_assessed_project(name="P-V4", base_abatement_cost_cents=1_000)
        worker = create_worker_entity(full_name="Han One",
                                      certification_level="HANDLER")
        resp = api_client.create_assignment(
            create_assignment_payload(
                ctx["project"]["id"], worker["id"], role_on_site="HANDLER",
                start_at="2026-08-20T00:00:00Z", end_at="2026-08-20T00:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


class TestFitnessBeatsOverlap:
    def test_expiry_before_start_masks_overlap(self):
        """PRD section 3.5: "Creation evaluates its checks in order: field
        validation first, then existence of the referenced project and worker,
        then the cross-entity project-state gate (`ERR_INVALID_STATE`), then
        two worker safety checks — the worker must be `ACTIVE` with all three
        expiry timestamps falling strictly after `start_at` (an expiry exactly
        equal to `start_at` renders the worker unfit, `ERR_WORKER_NOT_FIT`,
        422), and a `role_on_site` of `SUPERVISOR` requires the worker's
        `certification_level` to be `SUPERVISOR` (`ERR_CERTIFICATION_MISMATCH`,
        422) — then the window itself, where an `end_at` that is not strictly
        after `start_at` fails with `ERR_INVALID_WINDOW` (422), and finally
        overlap".

        Design: Difficulty/priority_pair_validation_conflict/assignment_fitness_beats_overlap
        """
        ctx = setup_assessed_project(name="P-PV2", base_abatement_cost_cents=1_000)
        worker = create_worker_entity(
            full_name="Sup Three", certification_level="SUPERVISOR",
            respirator_fit_expires_at="2026-09-01T00:00:00Z")
        create_assignment_entity(
            ctx["project"]["id"], worker["id"], role_on_site="SUPERVISOR",
            start_at="2026-08-11T00:00:00Z", end_at="2026-09-10T00:00:00Z")
        # New window overlaps the existing one AND starts after the
        # respirator fit expiry (2026-09-01): the safety check fires first.
        resp = api_client.create_assignment(
            create_assignment_payload(
                ctx["project"]["id"], worker["id"], role_on_site="SUPERVISOR",
                start_at="2026-09-05T00:00:00Z", end_at="2026-09-12T00:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_WORKER_NOT_FIT)
        assert resp.json()["data"]["error_id"] != "ERR_ASSIGNMENT_OVERLAP"

    def test_expiry_equal_start_masks_overlap(self):
        """PRD section 3.5: "the worker must be `ACTIVE` with all three expiry
        timestamps falling strictly after `start_at` (an expiry exactly equal
        to `start_at` renders the worker unfit, `ERR_WORKER_NOT_FIT`, 422)"
        PRD section 3.5: "then the window itself, where an `end_at` that is
        not strictly after `start_at` fails with `ERR_INVALID_WINDOW` (422),
        and finally overlap: the worker must have no existing `SCHEDULED`
        assignment whose `start_at` falls before the new `end_at` while the
        new `start_at` falls before that assignment's `end_at`."

        Design: Difficulty/priority_pair_validation_conflict/assignment_fitness_beats_overlap
        """
        ctx = setup_assessed_project(name="P-PV2B", base_abatement_cost_cents=1_000)
        worker = create_worker_entity(
            full_name="Sup Four", certification_level="SUPERVISOR",
            cert_expires_at="2026-09-05T00:00:00Z")
        create_assignment_entity(
            ctx["project"]["id"], worker["id"], role_on_site="SUPERVISOR",
            start_at="2026-08-11T00:00:00Z", end_at="2026-09-10T00:00:00Z")
        # cert expiry exactly equals the new start_at AND the window overlaps.
        resp = api_client.create_assignment(
            create_assignment_payload(
                ctx["project"]["id"], worker["id"], role_on_site="SUPERVISOR",
                start_at="2026-09-05T00:00:00Z", end_at="2026-09-12T00:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_WORKER_NOT_FIT)
        assert resp.json()["data"]["error_id"] != "ERR_ASSIGNMENT_OVERLAP"


class TestAssignmentOverlap:
    def test_back_to_back_assignments_allowed(self):
        """PRD section 3.5: "Because windows are half-open, back-to-back
        assignments that merely touch are allowed; a true overlap is rejected
        with `ERR_ASSIGNMENT_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/worker_assignment_half_open_back_to_back
        """
        ctx = setup_assessed_project(name="P-OV1", base_abatement_cost_cents=1_000)
        worker = create_worker_entity(full_name="Han One",
                                      certification_level="HANDLER")
        first = create_assignment_entity(
            ctx["project"]["id"], worker["id"], role_on_site="HANDLER",
            start_at="2026-08-11T00:00:00Z", end_at="2026-08-20T00:00:00Z")
        assert first["status"] == "SCHEDULED"
        # New window starts exactly at the existing window's end.
        resp = api_client.create_assignment(
            create_assignment_payload(
                ctx["project"]["id"], worker["id"], role_on_site="HANDLER",
                start_at="2026-08-20T00:00:00Z", end_at="2026-08-25T00:00:00Z"),
            ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED", \
            "back-to-back (half-open) assignments must be allowed"

    def test_interior_overlap_rejected(self):
        """PRD section 3.5: "the worker must have no existing `SCHEDULED`
        assignment whose `start_at` falls before the new `end_at` while the
        new `start_at` falls before that assignment's `end_at`."
        PRD section 3.5: "a true overlap is rejected with
        `ERR_ASSIGNMENT_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/worker_assignment_half_open_back_to_back
        """
        ctx = setup_assessed_project(name="P-OV1B", base_abatement_cost_cents=1_000)
        worker = create_worker_entity(full_name="Han One",
                                      certification_level="HANDLER")
        create_assignment_entity(
            ctx["project"]["id"], worker["id"], role_on_site="HANDLER",
            start_at="2026-08-11T00:00:00Z", end_at="2026-08-20T00:00:00Z")
        resp = api_client.create_assignment(
            create_assignment_payload(
                ctx["project"]["id"], worker["id"], role_on_site="HANDLER",
                start_at="2026-08-19T00:00:00Z", end_at="2026-08-21T00:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OVERLAP)


class TestWorkerLapseCycle:
    def test_clock_reaching_earliest_expiry_lapses_worker(self):
        """PRD section 3.5: "When the logical clock reaches the earliest of a
        worker's three expiry fields, the worker transitions from `ACTIVE` to
        `LAPSED`, and the lapse cascades in two links. Link 1: every
        `SCHEDULED` assignment of that worker transitions to `SUSPENDED`, and
        the worker's hours are recomputed with the suspended assignments
        excluded."

        Design: Difficulty/non_linear_state_machine/worker_lapse_recertify_cycle
        """
        ctx = setup_assessed_project(name="P-NSM2", base_abatement_cost_cents=1_000)
        worker = create_worker_entity(
            full_name="Sup Two", certification_level="SUPERVISOR",
            cert_expires_at="2026-08-14T00:00:00Z")
        assignment = create_assignment_entity(
            ctx["project"]["id"], worker["id"], role_on_site="SUPERVISOR",
            start_at="2026-08-11T00:00:00Z", end_at="2026-08-20T00:00:00Z")
        set_clock("2026-08-14T00:00:00Z")
        worker_after = get_worker(worker["id"])
        assert worker_after["status"] == "LAPSED", \
            "clock reaching the earliest expiry must lapse the worker"
        assignments = list_worker_assignments(worker["id"])
        mine = [a for a in assignments if a["id"] == assignment["id"]]
        assert mine and mine[0]["status"] == "SUSPENDED", \
            "link 1: the SCHEDULED assignment must suspend"

    def test_recertify_restores_worker_and_future_assignments(self):
        """PRD section 3.5: "only if, after applying the provided fields, all
        three expiries fall strictly after the current time does the worker
        return from `LAPSED` to `ACTIVE` — otherwise the request fails with
        `ERR_WORKER_NOT_FIT` (422)."
        PRD section 3.5: "On a successful recertification, every `SUSPENDED`
        assignment of the worker whose `end_at` is still in the future
        transitions back to `SCHEDULED`, and the worker's assigned hours are
        recomputed."

        Design: Difficulty/non_linear_state_machine/worker_lapse_recertify_cycle
        """
        ctx = setup_assessed_project(name="P-NSM2B", base_abatement_cost_cents=1_000)
        worker = create_worker_entity(
            full_name="Sup Two", certification_level="SUPERVISOR",
            cert_expires_at="2026-08-14T00:00:00Z")
        assignment = create_assignment_entity(
            ctx["project"]["id"], worker["id"], role_on_site="SUPERVISOR",
            start_at="2026-08-11T00:00:00Z", end_at="2026-08-20T00:00:00Z")
        set_clock("2026-08-14T00:00:00Z")
        assert get_worker(worker["id"])["status"] == "LAPSED"
        resp = api_client.recertify_worker(
            worker["id"], {"cert_expires_at": "2027-06-01T00:00:00Z"}, ADMIN)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE", \
            "all three expiries strictly future: worker returns to ACTIVE"
        assignments = list_worker_assignments(worker["id"])
        mine = [a for a in assignments if a["id"] == assignment["id"]]
        assert mine and mine[0]["status"] == "SCHEDULED", \
            "end_at 2026-08-20 is still in the future: assignment restores"


class TestLapseStopWorkCascade:
    def test_lapse_suspends_worker_and_assignment(self):
        """PRD section 3.5: "When the logical clock reaches the earliest of a
        worker's three expiry fields, the worker transitions from `ACTIVE` to
        `LAPSED`, and the lapse cascades in two links. Link 1: every
        `SCHEDULED` assignment of that worker transitions to `SUSPENDED`, and
        the worker's hours are recomputed with the suspended assignments
        excluded."

        Design: Difficulty/transitive_cascade/certificate_lapse_transitive_stop_work_chain
        """
        ctx = setup_assessed_project(name="P-TC2")
        supervisor = create_worker_entity(
            full_name="Sup Two", certification_level="SUPERVISOR",
            cert_expires_at="2026-08-14T00:00:00Z")
        setup_verified_containment(ctx["project"]["id"], supervisor["id"])
        setup_acknowledged_notification(ctx["project"]["id"])
        assignment = create_assignment_entity(
            ctx["project"]["id"], supervisor["id"], role_on_site="SUPERVISOR",
            start_at="2026-08-11T00:00:00Z", end_at="2026-08-20T00:00:00Z",
            headers=supervisor_headers(supervisor))
        set_clock("2026-08-11T00:00:00Z")
        validate_success(api_client.start_abatement(ctx["project"]["id"], ADMIN))

        set_clock("2026-08-14T00:00:00Z")
        assert get_worker(supervisor["id"])["status"] == "LAPSED", \
            "link 1 trigger: clock reached the certification expiry"
        assignments = list_worker_assignments(supervisor["id"])
        mine = [a for a in assignments if a["id"] == assignment["id"]]
        assert mine and mine[0]["status"] == "SUSPENDED", \
            "link 1: the supervisor's SCHEDULED assignment must suspend"

    def test_lapse_stop_works_project_without_coverage(self):
        """PRD section 3.5: "Link 2: for each project that had at least one
        assignment suspended by link 1, if the project is `IN_PROGRESS` and no
        remaining `SCHEDULED` `SUPERVISOR` assignment covers the current
        instant, the project itself transitions from `IN_PROGRESS` to
        `SUSPENDED`, incrementing its `version` by 1 — the site cannot
        lawfully run without supervisor coverage."

        Design: Difficulty/transitive_cascade/certificate_lapse_transitive_stop_work_chain
        """
        ctx = setup_assessed_project(name="P-TC2B")
        supervisor = create_worker_entity(
            full_name="Sup Two", certification_level="SUPERVISOR",
            cert_expires_at="2026-08-14T00:00:00Z")
        setup_verified_containment(ctx["project"]["id"], supervisor["id"])
        setup_acknowledged_notification(ctx["project"]["id"])
        create_assignment_entity(
            ctx["project"]["id"], supervisor["id"], role_on_site="SUPERVISOR",
            start_at="2026-08-11T00:00:00Z", end_at="2026-08-20T00:00:00Z",
            headers=supervisor_headers(supervisor))
        set_clock("2026-08-11T00:00:00Z")
        validate_success(api_client.start_abatement(ctx["project"]["id"], ADMIN))

        set_clock("2026-08-14T00:00:00Z")
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "SUSPENDED", (
            "link 3: with its only supervisor coverage suspended, the "
            "IN_PROGRESS project must stop-work to SUSPENDED"
        )


class TestScheduledHoursInvariant:
    def test_create_adds_scheduled_hours(self):
        """PRD section 3.5: "A created assignment is `SCHEDULED`, and its
        `scheduled_hours` — the window length in hours at 2 decimal places,
        rounded half up — feeds the worker's `assigned_scheduled_hours`, which
        is the sum of `scheduled_hours` over that worker's `SCHEDULED`
        assignments only, recomputed at 2 decimal places whenever an
        assignment is created, cancelled, suspended, restored, or completed."

        Design: Difficulty/compensating_invariant/assignment_create_cancel_conserves_scheduled_hours
        """
        ctx = setup_assessed_project(name="P-INV2", base_abatement_cost_cents=1_000)
        worker = create_worker_entity(full_name="Han One",
                                      certification_level="HANDLER")
        create_assignment_entity(
            ctx["project"]["id"], worker["id"], role_on_site="HANDLER",
            start_at="2026-08-11T00:00:00Z", end_at="2026-08-20T00:00:00Z")
        assert get_worker(worker["id"])["assigned_scheduled_hours"] == 216, \
            "9 days x 24 h = 216 scheduled hours"
        create_assignment_entity(
            ctx["project"]["id"], worker["id"], role_on_site="HANDLER",
            start_at="2026-08-21T00:00:00Z", end_at="2026-08-25T00:00:00Z")
        hours = get_worker(worker["id"])["assigned_scheduled_hours"]
        assert hours == 312, (
            f"216 + 96 (4 days) = 312 scheduled hours, got {hours}"
        )

    def test_cancel_restores_scheduled_hours(self):
        """PRD section 3.5: "Cancelling an assignment (a `ContractorAdmin` or
        `Supervisor` action) moves it from `SCHEDULED` to `CANCELLED` and
        recomputes the worker's hours."
        PRD section 3.5: "the sum of `scheduled_hours` over that worker's
        `SCHEDULED` assignments only"

        Design: Difficulty/compensating_invariant/assignment_create_cancel_conserves_scheduled_hours
        """
        ctx = setup_assessed_project(name="P-INV2B", base_abatement_cost_cents=1_000)
        worker = create_worker_entity(full_name="Han One",
                                      certification_level="HANDLER")
        first = create_assignment_entity(
            ctx["project"]["id"], worker["id"], role_on_site="HANDLER",
            start_at="2026-08-11T00:00:00Z", end_at="2026-08-20T00:00:00Z")
        second = create_assignment_entity(
            ctx["project"]["id"], worker["id"], role_on_site="HANDLER",
            start_at="2026-08-21T00:00:00Z", end_at="2026-08-25T00:00:00Z")
        assert get_worker(worker["id"])["assigned_scheduled_hours"] == 312
        cancel_assignment(second["id"])
        hours = get_worker(worker["id"])["assigned_scheduled_hours"]
        assert hours == 216, (
            f"create+cancel must conserve the aggregate: expected 216, "
            f"got {hours}"
        )
        assignments = list_worker_assignments(worker["id"])
        mine = [a for a in assignments if a["id"] == first["id"]]
        assert mine and mine[0]["status"] == "SCHEDULED", \
            "the untouched assignment must remain SCHEDULED"
