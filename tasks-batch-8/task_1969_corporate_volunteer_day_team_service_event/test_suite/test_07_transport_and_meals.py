"""Transport manifests (window conflicts, seats) and meal plans (totals, deadline,
vendor-day capacity, one-active-plan pipeline, OCC create)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_signed_registration,
    create_event,
    create_manifest,
    create_meal_plan,
    create_partner,
    create_project,
    create_vehicle,
    create_volunteer,
    get_event,
    get_manifest,
    get_meal_plan,
    get_registration,
    match_project,
    open_event_registration,
    order_meal_plan,
    register_volunteer,
    set_clock,
    setup_matched_scenario,
    validate_error,
    validate_success,
    vet_project,
)

LC = TEST_USERS["logistics_headers"]


class TestVehicleTurnaroundBuffer:
    def _setup_manifest(self):
        event = create_event("Day O")
        vehicle = create_vehicle("Bus-7", 40)
        m1 = create_manifest(
            event["id"],
            vehicle["id"],
            depart_at="2026-08-20T08:00:00Z",
            return_at="2026-08-20T10:00:00Z",
            cost_cents=5000,
        )
        return event, vehicle, m1

    def test_departure_exactly_at_buffer_is_legal(self, api):
        """PRD §3.6: "The same vehicle cannot be double-booked: against every existing manifest for that vehicle in `BOOKED`, `CONFIRMED`, or `COMPLETED` status, the new window must respect a 30-minute turnaround buffer, meaning there is no conflict only when the new departure is at or after the existing window's return plus 30 minutes, or the new return plus 30 minutes is at or before the existing departure. Adjacency at exactly the 30-minute buffer is legal; one minute less is a conflict, rejected with `ERR_VEHICLE_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/vehicle_turnaround_buffer_exact_30_minutes
        """
        _, vehicle, m1 = self._setup_manifest()
        # M2 departs at exactly return_at + 30 min (10:30): allowed
        resp = api.create_transport_manifest(
            {
                "event_id": get_manifest(m1["id"])["event_id"],
                "vehicle_id": vehicle["id"],
                "depart_at": "2026-08-20T10:30:00Z",
                "return_at": "2026-08-20T12:00:00Z",
                "cost_cents": 4000,
            },
            LC,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "BOOKED"

    def test_departure_one_minute_inside_buffer_conflicts(self, api):
        """PRD §3.6: "Adjacency at exactly the 30-minute buffer is legal; one minute less is a conflict, rejected with `ERR_VEHICLE_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/vehicle_turnaround_buffer_exact_30_minutes
        """
        _, vehicle, m1 = self._setup_manifest()
        resp = api.create_transport_manifest(
            {
                "event_id": get_manifest(m1["id"])["event_id"],
                "vehicle_id": vehicle["id"],
                "depart_at": "2026-08-20T10:29:00Z",
                "return_at": "2026-08-20T12:00:00Z",
                "cost_cents": 4000,
            },
            LC,
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_SCHEDULE_CONFLICT)
        # The pre-existing manifest is unaffected
        assert get_manifest(m1["id"])["status"] == "BOOKED"


class TestVendorDayCapacity:
    def _setup_three_events(self):
        """Three same-UTC-date events (2026-08-20) with 4, 2, and 1 confirmed
        meal-demanding volunteers respectively (wants_meal defaults to true)."""
        out = []
        specs = [
            ("Day P-A", "2026-08-20T09:00:00Z", "2026-08-20T12:00:00Z", 4),
            ("Day P-B", "2026-08-20T13:00:00Z", "2026-08-20T16:00:00Z", 2),
            ("Day P-C", "2026-08-20T09:00:00Z", "2026-08-20T10:00:00Z", 1),
        ]
        partner = create_partner()
        for name, start, end, count in specs:
            event = create_event(name, event_start_at=start, event_end_at=end)
            project = create_project(partner["id"], f"Proj {name}")
            vet_project(project["id"])
            match_project(project["id"], event["id"])
            open_event_registration(event["id"])
            for i in range(count):
                vol = create_volunteer(f"Vol {name}-{i}", f"v-{name}-{i}@corp.com")
                add_signed_registration(
                    event["id"], project["id"], vol, wants_meal=None, confirm=True
                )
            out.append((event, project))
        return out

    def test_vendor_pool_admits_orders_up_to_capacity(self, api):
        """PRD §3.6: "One more constraint protects the caterer: across all meal plans with the same `vendor_name` whose events share the same UTC calendar date of `event_start_at` and whose status is `ORDERED` or `FULFILLED`, the pooled `ordered_headcount` plus this plan's snapshot must not exceed the vendor's daily capacity of 6 meals, otherwise the order is rejected with `ERR_VENDOR_CAPACITY_EXCEEDED`."
        PRD §3.6: "The plan's `total_cost_cents` is the number of non-dietary diners multiplied by `per_person_cost_cents`, plus the number of dietary diners multiplied by the sum of `per_person_cost_cents` and `dietary_surcharge_cents`."

        Design: Difficulty/resource_temporal_overlap/vendor_day_aggregate_capacity_boundary
        """
        (ev_a, _), (ev_b, _), _ = self._setup_three_events()
        plan_a = create_meal_plan(ev_a["id"], vendor_name="FreshCo", per_person_cost_cents=1000)
        ordered_a = order_meal_plan(plan_a["id"])
        assert ordered_a["ordered_headcount"] == 4
        assert ordered_a["total_cost_cents"] == 4000

        plan_b = create_meal_plan(ev_b["id"], vendor_name="FreshCo", per_person_cost_cents=1000)
        ordered_b = order_meal_plan(plan_b["id"])
        # Pool 4 + 2 == 6 == capacity: allowed at equality
        assert ordered_b["ordered_headcount"] == 2
        assert ordered_b["total_cost_cents"] == 2000

    def test_vendor_pool_rejects_the_order_that_overflows(self, api):
        """PRD §3.6: "across all meal plans with the same `vendor_name` whose events share the same UTC calendar date of `event_start_at` and whose status is `ORDERED` or `FULFILLED`, the pooled `ordered_headcount` plus this plan's snapshot must not exceed the vendor's daily capacity of 6 meals, otherwise the order is rejected with `ERR_VENDOR_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/vendor_day_aggregate_capacity_boundary
        """
        (ev_a, _), (ev_b, _), (ev_c, _) = self._setup_three_events()
        order_meal_plan(
            create_meal_plan(ev_a["id"], vendor_name="FreshCo", per_person_cost_cents=1000)["id"]
        )
        order_meal_plan(
            create_meal_plan(ev_b["id"], vendor_name="FreshCo", per_person_cost_cents=1000)["id"]
        )
        # Pool is now 6; event C's snapshot of 1 would make 7 > 6
        plan_c = create_meal_plan(ev_c["id"], vendor_name="FreshCo", per_person_cost_cents=1000)
        resp = api.order_meal_plan(plan_c["id"], LC)
        validate_error(resp, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED)
        assert get_meal_plan(plan_c["id"])["status"] == "DRAFT"


class TestManifestSeats:
    def test_manifest_seat_capacity_last_seat_boundary(self, api):
        """PRD §3.6: "must have a free seat: the manifest's `assigned_seats`, the count of registrations pointing at it with `rsvp_status` `REGISTERED`, `CONFIRMED`, or `CHECKED_IN`, must be below the vehicle's `seat_capacity`, otherwise `ERR_MANIFEST_FULL`."

        Design: Corner/validations/manifest_seat_capacity_last_seat_boundary
        """
        sc = setup_matched_scenario(event_name="Day 23")
        regs = []
        for i in range(3):
            vol = create_volunteer(f"Vol {i + 1}", f"v{i + 1}@corp.com")
            regs.append(
                register_volunteer(
                    vol,
                    sc["event"]["id"],
                    sc["project"]["id"],
                    wants_meal=False,
                    wants_transport=True,
                )
            )
        vehicle = create_vehicle("Van-2", 2)
        manifest = create_manifest(
            sc["event"]["id"],
            vehicle["id"],
            depart_at="2026-08-20T08:00:00Z",
            return_at="2026-08-20T10:00:00Z",
            cost_cents=3000,
        )

        first = validate_success(
            api.assign_transport(regs[0]["id"], {"transport_manifest_id": manifest["id"]}, LC), 200
        )
        assert first["transport_manifest_id"] == manifest["id"]
        validate_success(
            api.assign_transport(regs[1]["id"], {"transport_manifest_id": manifest["id"]}, LC), 200
        )
        # The second assignment fills the last seat: 2 == seat_capacity
        assert get_manifest(manifest["id"])["assigned_seats"] == 2

        denied = api.assign_transport(
            regs[2]["id"], {"transport_manifest_id": manifest["id"]}, LC
        )
        validate_error(denied, ApiErrorId.ERR_MANIFEST_FULL)
        assert get_registration(regs[2]["id"])["transport_manifest_id"] is None

    def test_assign_transport_manifest_event_mismatch(self, api):
        """PRD §3.6: "The manifest must belong to the same event as the registration (`ERR_MANIFEST_EVENT_MISMATCH`, HTTP 422), must be in an assignable non-terminal state — `BOOKED` or `CONFIRMED`, since a `CANCELLED` or `COMPLETED` manifest rejects the assignment with `ERR_INVALID_MANIFEST_TRANSITION` — and must have a free seat: the manifest's `assigned_seats`, the count of registrations pointing at it with `rsvp_status` `REGISTERED`, `CONFIRMED`, or `CHECKED_IN`, must be below the vehicle's `seat_capacity`, otherwise `ERR_MANIFEST_FULL`."

        Design: Corner/validations/assign_transport_manifest_event_mismatch
        """
        partner = create_partner()
        proj_a = create_project(partner["id"], "P-A")
        ev_a = create_event("Day 29A")
        ev_b = create_event(
            "Day 29B", event_start_at="2026-08-21T09:00:00Z", event_end_at="2026-08-21T15:00:00Z"
        )
        vet_project(proj_a["id"])
        match_project(proj_a["id"], ev_a["id"])
        open_event_registration(ev_a["id"])
        vol = create_volunteer("Vol One", "v1@corp.com")
        reg = register_volunteer(vol, ev_a["id"], proj_a["id"], wants_transport=True)
        vehicle = create_vehicle()
        manifest_b = create_manifest(
            ev_b["id"],
            vehicle["id"],
            depart_at="2026-08-21T08:00:00Z",
            return_at="2026-08-21T10:00:00Z",
        )

        resp = api.assign_transport(reg["id"], {"transport_manifest_id": manifest_b["id"]}, LC)
        validate_error(resp, ApiErrorId.ERR_MANIFEST_EVENT_MISMATCH)
        assert get_registration(reg["id"])["transport_manifest_id"] is None


class TestManifestStateMachine:
    def test_manifest_depart_in_past_rejected(self, api):
        """PRD §3.6: "The `depart_at` must be strictly after the current logical clock (`ERR_MANIFEST_IN_PAST`, HTTP 422), and `return_at` must be strictly after `depart_at` (`ERR_VALIDATION`)."

        Design: Corner/validations/manifest_depart_in_past_rejected
        """
        event = create_event("Day 19")
        vehicle = create_vehicle()
        resp = api.create_transport_manifest(
            {
                "event_id": event["id"],
                "vehicle_id": vehicle["id"],
                "depart_at": "2026-07-31T08:00:00Z",
                "return_at": "2026-07-31T10:00:00Z",
                "cost_cents": 5000,
            },
            LC,
        )
        validate_error(resp, ApiErrorId.ERR_MANIFEST_IN_PAST)

    def test_manifest_double_confirm_rejected(self, api):
        """PRD §3.6: "Confirmation moves it `BOOKED` → `CONFIRMED`, promoting the cost into committed spend; cancelling from `BOOKED` or `CONFIRMED` moves it to `CANCELLED`, clears `transport_manifest_id` on every registration pointing at it, frees the vehicle window, and reverses the spend — other from-states fail as `ERR_INVALID_MANIFEST_TRANSITION`."

        Design: Corner/errors/manifest_double_confirm_rejected
        """
        event = create_event("Day 37")
        vehicle = create_vehicle()
        manifest = create_manifest(event["id"], vehicle["id"])
        validate_success(api.confirm_manifest(manifest["id"], LC), 200)

        resp = api.confirm_manifest(manifest["id"], LC)
        validate_error(resp, ApiErrorId.ERR_INVALID_MANIFEST_TRANSITION)


class TestMealPlanTotals:
    def test_meal_total_with_dietary_surcharge_split(self, api):
        """PRD §3.6: "At that moment the server snapshots the eligible diners: `ordered_headcount` counts the event's registrations with `rsvp_status` `CONFIRMED` or `CHECKED_IN` and `wants_meal` true, and `dietary_headcount` counts the subset carrying at least one dietary tag."
        PRD §3.6: "The plan's `total_cost_cents` is the number of non-dietary diners multiplied by `per_person_cost_cents`, plus the number of dietary diners multiplied by the sum of `per_person_cost_cents` and `dietary_surcharge_cents`."
        PRD §3.6: "Placing the order freezes the numbers."

        Design: Corner/calculations/meal_total_with_dietary_surcharge_split
        """
        sc = setup_matched_scenario(event_name="Day 11")
        vol1 = create_volunteer("Vol 1", "v1@corp.com", dietary_tags=["VEGAN"])
        vol2 = create_volunteer("Vol 2", "v2@corp.com")
        vol3 = create_volunteer("Vol 3", "v3@corp.com")
        for vol in (vol1, vol2, vol3):
            add_signed_registration(
                sc["event"]["id"], sc["project"]["id"], vol, wants_meal=None, confirm=True
            )
        plan = create_meal_plan(
            sc["event"]["id"],
            vendor_name="FreshCo",
            per_person_cost_cents=1200,
            dietary_surcharge_cents=300,
        )
        ordered = order_meal_plan(plan["id"])
        assert ordered["ordered_headcount"] == 3
        assert ordered["dietary_headcount"] == 1
        # 2 x 1200 + 1 x (1200 + 300) = 3900
        assert ordered["total_cost_cents"] == 3900

        # The snapshot is frozen: a later confirm does not move the ordered numbers
        vol4 = create_volunteer("Vol 4", "v4@corp.com")
        add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol4, wants_meal=None, confirm=True
        )
        frozen = get_meal_plan(plan["id"])
        assert frozen["ordered_headcount"] == 3
        assert frozen["total_cost_cents"] == 3900


class TestMealOrderDeadline:
    def _setup_draft_plan(self):
        sc = setup_matched_scenario(event_name="Day 18")
        vol = create_volunteer("Vol One", "v1@corp.com")
        add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol, wants_meal=None, confirm=True
        )
        plan = create_meal_plan(sc["event"]["id"], vendor_name="FreshCo", per_person_cost_cents=1000)
        return sc, plan

    def test_order_at_exactly_72h_before_start_is_accepted(self, api):
        """PRD §3.6: "Ordering requires the plan to be `DRAFT` (`ERR_INVALID_MEAL_PLAN_TRANSITION` otherwise) and the current logical clock to be no later than 72 hours before the event's `event_start_at` — the caterer's lead time — failing as `ERR_MEAL_ORDER_DEADLINE_PASSED`."

        Design: Corner/validations/meal_order_deadline_exact_72h_boundary
        """
        _, plan = self._setup_draft_plan()
        # Deadline for a 2026-08-20T09:00:00Z start: 2026-08-17T09:00:00Z (inclusive)
        set_clock("2026-08-17T09:00:00Z")
        ordered = validate_success(api.order_meal_plan(plan["id"], LC), 200)
        assert ordered["status"] == "ORDERED"
        assert ordered["ordered_headcount"] == 1

    def test_order_one_second_past_the_deadline_is_rejected(self, api):
        """PRD §3.6: "Ordering requires the plan to be `DRAFT` (`ERR_INVALID_MEAL_PLAN_TRANSITION` otherwise) and the current logical clock to be no later than 72 hours before the event's `event_start_at` — the caterer's lead time — failing as `ERR_MEAL_ORDER_DEADLINE_PASSED`."

        Design: Corner/validations/meal_order_deadline_exact_72h_boundary
        """
        _, plan = self._setup_draft_plan()
        set_clock("2026-08-17T09:00:01Z")
        resp = api.order_meal_plan(plan["id"], LC)
        validate_error(resp, ApiErrorId.ERR_MEAL_ORDER_DEADLINE_PASSED)
        assert get_meal_plan(plan["id"])["status"] == "DRAFT"


class TestMealPlanPipelineRules:
    def test_meal_plan_double_order_rejected(self, api):
        """PRD §3.6: "Ordering requires the plan to be `DRAFT` (`ERR_INVALID_MEAL_PLAN_TRANSITION` otherwise) and the current logical clock to be no later than 72 hours before the event's `event_start_at` — the caterer's lead time — failing as `ERR_MEAL_ORDER_DEADLINE_PASSED`."

        Design: Corner/errors/meal_plan_double_order_rejected
        """
        sc = setup_matched_scenario(event_name="Day 38")
        vol = create_volunteer("Vol One", "v1@corp.com")
        add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol, wants_meal=None, confirm=True
        )
        plan = create_meal_plan(sc["event"]["id"], vendor_name="FreshCo", per_person_cost_cents=1000)
        order_meal_plan(plan["id"])

        resp = api.order_meal_plan(plan["id"], LC)
        validate_error(resp, ApiErrorId.ERR_INVALID_MEAL_PLAN_TRANSITION)

    def test_meal_plan_create_blocked_when_ordered_exists(self, api):
        """PRD §3.6: "Only one active meal pipeline exists per event: if a plan in `ORDERED` or `FULFILLED` status already exists for the event, creation is rejected with `ERR_ACTIVE_MEAL_PLAN_EXISTS`; if a `DRAFT` plan exists, creating the new plan supersedes it — the old draft moves to `CANCELLED` — and the creation increments the event's `version` by 1."

        Design: Corner/validations/meal_plan_create_blocked_when_ordered_exists
        """
        sc = setup_matched_scenario(event_name="Day 33")
        vol = create_volunteer("Vol One", "v1@corp.com")
        add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol, wants_meal=None, confirm=True
        )
        plan = create_meal_plan(sc["event"]["id"], vendor_name="FreshCo", per_person_cost_cents=1000)
        order_meal_plan(plan["id"])

        version = get_event(sc["event"]["id"])["version"]
        resp = api.create_meal_plan(
            sc["event"]["id"],
            {
                "vendor_name": "OtherCo",
                "per_person_cost_cents": 900,
                "expected_event_version": version,
            },
            LC,
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_MEAL_PLAN_EXISTS)
        assert get_meal_plan(plan["id"])["status"] == "ORDERED"


class TestMealPlanOcc:
    def test_meal_plan_supersede_cancels_existing_draft(self, api):
        """PRD §3.6: "Only one active meal pipeline exists per event: if a plan in `ORDERED` or `FULFILLED` status already exists for the event, creation is rejected with `ERR_ACTIVE_MEAL_PLAN_EXISTS`; if a `DRAFT` plan exists, creating the new plan supersedes it — the old draft moves to `CANCELLED` — and the creation increments the event's `version` by 1."

        Design: Corner/cross_cutting_layers/meal_plan_supersede_cancels_existing_draft
        """
        event = create_event("Day 48")
        v0 = get_event(event["id"])["version"]

        plan_a = create_meal_plan(event["id"], vendor_name="FreshCo", per_person_cost_cents=1000)
        v1 = get_event(event["id"])["version"]
        plan_b = create_meal_plan(event["id"], vendor_name="OtherCo", per_person_cost_cents=900)
        v2 = get_event(event["id"])["version"]

        # Each creation is a direct write to the event: version advances by exactly 1
        assert (v0, v1, v2) == (v0, v0 + 1, v0 + 2)
        assert get_meal_plan(plan_a["id"])["status"] == "CANCELLED"  # superseded
        assert get_meal_plan(plan_b["id"])["status"] == "DRAFT"

    def test_meal_plan_create_stale_event_version_rejected(self, api):
        """PRD §2.9: "Creating a meal plan for an event. Because creation supersedes the event's existing draft meal plan (§3.6), a writer whose last observed version is stale would silently cancel a plan it never saw; the create is therefore rejected instead."
        PRD §2.9: "In both cases, when `expected_event_version` does not match the event's current `version`, the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/meal_plan_create_stale_event_version_rejected
        """
        event = create_event("Day 49")
        stale_version = get_event(event["id"])["version"]
        plan_a = create_meal_plan(event["id"], vendor_name="FreshCo", per_person_cost_cents=1000)

        resp = api.create_meal_plan(
            event["id"],
            {
                "vendor_name": "StaleCo",
                "per_person_cost_cents": 800,
                "expected_event_version": stale_version,
            },
            LC,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_EVENT_VERSION)
        assert get_meal_plan(plan_a["id"])["status"] == "DRAFT"  # no supersede happened
