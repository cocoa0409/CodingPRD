"""Event creation defaults, temporal creation rules, lifecycle spine, and cascades."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    approve_order,
    begin_ready_event,
    create_event,
    create_manifest,
    create_meal_plan,
    create_order,
    create_sponsorship,
    create_vehicle,
    commit_sponsorship,
    get_assignment,
    get_event,
    get_manifest,
    get_meal_plan,
    get_order,
    get_project,
    get_registration,
    get_sponsorship,
    lock_event_registration,
    order_meal_plan,
    setup_matched_scenario,
    setup_ready_event,
    submit_order,
    validate_error,
    validate_success,
)


class TestEventCreationDefaults:
    def test_event_create_applies_defaults(self, api, cem_headers):
        """PRD §3.2: "A new event opens in `PLANNING` status with `readiness_posture` `BLOCKED` (it has no matched projects yet), both spend positions at zero, all headcounts at zero, `total_scheduled_hours` and `total_verified_hours` at zero, a null `source_event_id`, `repeat_booking_bonus` false, and a null `avg_feedback_rating` until the first survey arrives."
        PRD §3.2: "a total `budget_cents` that may not be negative, and optionally the `waiver_document_version`, which defaults to 1 and must be at least 1."

        Design: Corner/entities/event_create_applies_defaults
        """
        resp = api.create_service_event(
            {
                "name": "Day 1",
                "event_start_at": "2026-08-20T09:00:00Z",
                "event_end_at": "2026-08-20T15:00:00Z",
                "budget_cents": 500000,
            },
            cem_headers,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "PLANNING"
        assert data["readiness_posture"] == "BLOCKED"
        assert data["waiver_document_version"] == 1
        assert data["projected_spend_cents"] == 0
        assert data["committed_spend_cents"] == 0
        assert data["available_budget_cents"] == 500000
        assert data["confirmed_headcount"] == 0
        assert data["registered_headcount"] == 0
        assert data["checked_in_headcount"] == 0
        assert data["repeat_booking_bonus"] is False
        assert data["source_event_id"] is None
        assert data["version"] == 1


class TestEventCreationTemporalRules:
    def test_event_create_start_too_soon_rejected(self, api, cem_headers):
        """PRD §3.2: "The start must be at least 24 hours after the current logical clock, and the end must be strictly after the start; either violation is rejected with `ERR_EVENT_IN_PAST` (HTTP 422)."
        PRD §2.5: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and before any explicit set call it continues to read that default; it never falls back to wall-clock time."

        Design: Corner/validations/event_create_start_too_soon_rejected
        """
        # 12h ahead of the 2026-08-01T00:00:00Z default clock: inside the 24h lead time
        resp = api.create_service_event(
            {
                "name": "Too Soon",
                "event_start_at": "2026-08-01T12:00:00Z",
                "event_end_at": "2026-08-01T18:00:00Z",
                "budget_cents": 100,
            },
            cem_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_IN_PAST)

        # Exactly now + 24h: "at least 24 hours after" is inclusive of the boundary
        resp_ok = api.create_service_event(
            {
                "name": "Just In Time",
                "event_start_at": "2026-08-02T00:00:00Z",
                "event_end_at": "2026-08-02T06:00:00Z",
                "budget_cents": 100,
            },
            cem_headers,
        )
        data = validate_success(resp_ok, 201)
        assert data["event_start_at"] == "2026-08-02T00:00:00Z"


class TestEventNotFound:
    def test_event_not_found_returns_404(self, api, any_headers):
        """PRD §2.10: "For requests that address nested resources — creating a meal plan under an event path is the one nested creation in the system — the system validates path identifiers in a strict left-to-right order and rejects immediately with the 404 error corresponding to the first identifier that does not resolve."

        Design: Corner/entities/event_not_found_returns_404
        """
        resp = api.get_service_event(NON_EXISTENT_UUID, any_headers)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)


class TestCancelledEventTerminalLockdown:
    def test_cancelled_event_terminal_lockdown(self, api, cem_headers):
        """PRD §3.7: "Each of these actions is legal only from its named from-state — anything else is `ERR_INVALID_EVENT_TRANSITION` — and each increments the event's `version` by exactly 1."
        PRD §3.7: "`CLOSED` and `CANCELLED` are the event's terminal states."

        Design: Corner/state_machines/cancelled_event_terminal_lockdown
        """
        event = create_event(name="Day 4", budget_cents=500000)
        cancelled = validate_success(api.cancel_event(event["id"], cem_headers), 200)
        assert cancelled["status"] == "CANCELLED"

        for action in (
            api.open_registration,
            api.begin_event,
            api.complete_event,
            api.close_event,
            api.cancel_event,
        ):
            resp = action(event["id"], cem_headers)
            validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_TRANSITION)

        assert get_event(event["id"])["status"] == "CANCELLED"


class TestBeginPostureGate:
    def test_begin_blocked_when_posture_not_ready(self, api, cem_headers):
        """PRD §3.7: "Beginning the day is the posture-gated step: beyond being `REGISTRATION_LOCKED`, the event's `readiness_posture` must be `READY` at that instant, otherwise the begin is rejected with `ERR_EVENT_NOT_READY`."
        PRD §2.7: "In every other configuration the posture is `PARTIAL`."

        Design: Corner/state_machines/begin_blocked_when_posture_not_ready
        """
        # One MATCHED project (never locked) leaves posture at PARTIAL
        sc = setup_matched_scenario(event_name="Day 8", budget_cents=500000)
        event_id = sc["event"]["id"]
        lock_event_registration(event_id)

        posture = get_event(event_id)["readiness_posture"]
        assert posture == "PARTIAL", f"expected PARTIAL, got {posture}"

        resp = api.begin_event(event_id, cem_headers)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_READY)
        assert get_event(event_id)["status"] == "REGISTRATION_LOCKED"


class TestEventCompleteCascade:
    def test_event_complete_cascades_project_and_meal(self, api, cem_headers):
        """PRD §3.7: "Along with the version increment and a full recompute of headcounts, spend, and posture, completing the event moves every registration still in `CONFIRMED` to `NO_SHOW` (the volunteers who never checked in; their `transport_manifest_id` is cleared), every `LOCKED` project of the event to `COMPLETED`, every manifest in `BOOKED` or `CONFIRMED` to `COMPLETED`, and every meal plan in `ORDERED` to `FULFILLED`."

        Design: Corner/state_machines/event_complete_cascades_project_and_meal
        """
        # wants_meal=True creates meal demand, so an ORDERED plan is needed for READY
        sc = setup_ready_event(event_name="Day 9", budget_cents=500000, wants_meal=True)
        event_id = sc["event"]["id"]
        plan = create_meal_plan(event_id, vendor_name="FreshCo", per_person_cost_cents=1200)
        ordered = order_meal_plan(plan["id"])
        assert ordered["status"] == "ORDERED"

        begin_ready_event(event_id)
        completed = validate_success(api.complete_event(event_id, cem_headers), 200)
        assert completed["status"] == "COMPLETED"
        assert get_project(sc["project"]["id"])["status"] == "COMPLETED"
        assert get_meal_plan(plan["id"])["status"] == "FULFILLED"


class TestEventCancelCompensationCascade:
    def test_event_cancel_full_compensation_cascade(self, api, cem_headers):
        """PRD §3.7: "Cancellation is the full compensating unwind, available from `PLANNING`, `REGISTRATION_OPEN`, or `REGISTRATION_LOCKED` (else `ERR_INVALID_EVENT_TRANSITION`), with each child cascade applied in ascending `created_at` order (§2.10): the event's registrations in `REGISTERED` or `CONFIRMED` move to `CANCELLED` with `transport_manifest_id` cleared; its procurement orders in `DRAFT`, `SUBMITTED`, or `APPROVED` move to `CANCELLED` as a budget reversal while `RECEIVED` orders are untouched; its manifests in `BOOKED` or `CONFIRMED` move to `CANCELLED`; its meal plans in `DRAFT` or `ORDERED` move to `CANCELLED`; its sponsorships in `PLEDGED` or `COMMITTED` move to `WITHDRAWN`; its projects in `MATCHED` or `LOCKED` return to `VETTED` with `event_id` cleared to null, releasing them back to the sourcing pool, and each such project's `ACTIVE` supervision assignments move to `WITHDRAWN`; and the event's `version` increments by 1."

        Design: Corner/cross_cutting_layers/event_cancel_full_compensation_cascade
        """
        # READY event: confirmed volunteer who wants a meal, lead, LOCKED project
        sc = setup_ready_event(event_name="Day 51", budget_cents=500000, wants_meal=True)
        event_id = sc["event"]["id"]
        project_id = sc["project"]["id"]
        received_order = sc["order"]  # 1088, sunk cost
        # An APPROVED (not received) order: round_half_up(1 x 100 x 1.0875) = 109
        approved_order = create_order(
            event_id, project_id, lines=[{"item_name": "Cones", "quantity": 1, "unit_cost_cents": 100}]
        )
        submit_order(approved_order["id"])
        approve_order(approved_order["id"])
        vehicle = create_vehicle()
        manifest = create_manifest(event_id, vehicle["id"])
        plan = create_meal_plan(event_id, vendor_name="FreshCo", per_person_cost_cents=1000)
        order_meal_plan(plan["id"])
        sponsorship = create_sponsorship(event_id)
        commit_sponsorship(sponsorship["id"])

        cancelled = validate_success(api.cancel_event(event_id, cem_headers), 200)
        assert cancelled["status"] == "CANCELLED"

        assert get_registration(sc["registrations"][0]["id"])["rsvp_status"] == "CANCELLED"
        assert get_assignment(sc["assignment"]["id"])["status"] == "WITHDRAWN"
        assert get_order(approved_order["id"])["status"] == "CANCELLED"
        assert get_order(received_order["id"])["status"] == "RECEIVED"
        assert get_manifest(manifest["id"])["status"] == "CANCELLED"
        assert get_meal_plan(plan["id"])["status"] == "CANCELLED"
        assert get_sponsorship(sponsorship["id"])["status"] == "WITHDRAWN"

        project = get_project(project_id)
        assert project["status"] == "VETTED"
        assert project["event_id"] is None

        # Only the RECEIVED sunk-cost order (1088) remains in the projected position
        event = get_event(event_id)
        assert event["projected_spend_cents"] == 1088


class TestRescheduleOcc:
    def test_reschedule_stale_version_rejected_and_fresh_accepted(self, api, cem_headers):
        """PRD §3.2: "A successful reschedule increments the event's `version` by 1."
        PRD §2.9: "In both cases, when `expected_event_version` does not match the event's current `version`, the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/reschedule_stale_version_rejected_and_fresh_accepted
        """
        event = create_event(name="Day 50", budget_cents=500000)
        observed_version = get_event(event["id"])["version"]

        ok = api.reschedule_event(
            event["id"],
            {
                "event_start_at": "2026-08-25T09:00:00Z",
                "event_end_at": "2026-08-25T15:00:00Z",
                "expected_event_version": observed_version,
            },
            cem_headers,
        )
        data = validate_success(ok, 200)
        assert data["event_start_at"] == "2026-08-25T09:00:00Z"
        assert data["version"] == observed_version + 1

        # Replaying the stale observed version is rejected; the window is unchanged
        stale = api.reschedule_event(
            event["id"],
            {
                "event_start_at": "2026-08-26T09:00:00Z",
                "event_end_at": "2026-08-26T15:00:00Z",
                "expected_event_version": observed_version,
            },
            cem_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_EVENT_VERSION)
        assert get_event(event["id"])["event_start_at"] == "2026-08-25T09:00:00Z"
