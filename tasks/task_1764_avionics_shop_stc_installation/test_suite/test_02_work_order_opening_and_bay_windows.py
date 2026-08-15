"""Work-order opening: initial state, bay-window reservation, and aircraft gating."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_work_order,
    create_aircraft,
    create_customer,
    create_equipment_order_payload,
    create_work_order,
    get_aircraft,
    setup_draft_work_order,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]


class TestWorkOrderInitialState:
    def test_work_order_starts_in_draft_with_zeroed_counters(self, api):
        """PRD §3.1: "The new work order starts in `DRAFT` with its derived counters at zero — `parts_pending_count`, `tasks_unverified_count`, `total_actual_labor_hours`, and `total_billed_labor_cents` — with `overage_acknowledged` false, and with `inducted_at`, `completed_at`, and `quoted_total_cents` still null."
        PRD §3.1: "Creation flips the aircraft from `AVAILABLE` to `IN_SHOP` automatically."

        Design: Corner/state_machines/work_order_initial_state_draft
        """
        customer = create_customer(name="Init Ian", contact_email="i@x.com")
        aircraft = create_aircraft(customer["id"], tail_number="N650IN")
        work_order = create_work_order(aircraft["id"])
        assert_work_order(work_order)
        assert work_order["status"] == "DRAFT"
        assert work_order["parts_pending_count"] == 0
        assert work_order["tasks_unverified_count"] == 0
        assert work_order["total_actual_labor_hours"] == 0
        assert work_order["total_billed_labor_cents"] == 0
        assert work_order["inducted_at"] is None
        assert work_order["completed_at"] is None
        assert work_order["quoted_total_cents"] is None
        assert work_order["overage_acknowledged"] is False
        assert get_aircraft(aircraft["id"])["status"] == "IN_SHOP", (
            "opening a work order flips its aircraft AVAILABLE -> IN_SHOP")


class TestWorkOrderWindowValidation:
    def test_work_order_create_with_empty_window_rejected(self, api):
        """PRD §3.1: "a bay reservation made of `bay_code`, `bay_window_start`, and `bay_window_end`, with the end required to be later than the start (`ERR_VALIDATION`)"
        PRD §2.9: "an aircraft reads `IN_SHOP` while any non-terminal work order references it and `AVAILABLE` otherwise."

        Design: Corner/entities/work_order_create_invalid_window_rejected
        """
        customer = create_customer(name="Win Wendy", contact_email="w@x.com")
        aircraft = create_aircraft(customer["id"], tail_number="N620WN")
        response = api.create_work_order(
            {
                "aircraft_id": aircraft["id"],
                "scope_description": "bad window",
                "estimated_downtime_days": 10,
                "quoted_labor_hours": 5,
                "bay_code": "BAY-1",
                "bay_window_start": "2026-08-20T00:00:00Z",
                "bay_window_end": "2026-08-20T00:00:00Z",
            },
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION)
        assert get_aircraft(aircraft["id"])["status"] == "AVAILABLE", (
            "rejected creation persists no work order, so the aircraft stays AVAILABLE")


class TestManualOrderRequiresApproval:
    def test_equipment_create_before_approval_rejected(self, api):
        """PRD §3.3: "Manual lines are accepted only while the work order is `APPROVED` or `PARTS_PENDING`; any other state draws `ERR_WORK_ORDER_NOT_APPROVED`."

        Design: Corner/endpoints/equipment_create_before_approval_rejected
        """
        bundle = setup_draft_work_order(customer_name="Early Ed",
                                        customer_email="e2@x.com",
                                        with_design=False)
        response = api.create_equipment_order(
            create_equipment_order_payload(bundle["work_order"]["id"]), MANAGER)
        validate_error(response, ApiErrorId.ERR_WORK_ORDER_NOT_APPROVED)
        reread = validate_success(api.get_work_order(bundle["work_order"]["id"], MANAGER))
        assert reread["status"] == "DRAFT"
        assert reread["parts_pending_count"] == 0, (
            "rejected manual line must not persist an order")


class TestAircraftBusyGate:
    def test_second_work_order_on_busy_aircraft_rejected(self, api):
        """PRD §3.1: "Only one open work order per aircraft is tolerated — the aircraft must be `AVAILABLE` at creation, otherwise the open fails with `ERR_AIRCRAFT_BUSY`"

        Design: Difficulty/cross_entity_state_dependency/work_order_create_requires_available_aircraft
        """
        customer = create_customer(name="Busy Owner", contact_email="busy@x.com")
        busy = create_aircraft(customer["id"], tail_number="N400CA")
        create_work_order(busy["id"], scope_description="first job")
        response = api.create_work_order(
            {
                "aircraft_id": busy["id"],
                "scope_description": "second job",
                "estimated_downtime_days": 5,
                "quoted_labor_hours": 2,
                "bay_code": "BAY-2",
                "bay_window_start": "2026-08-01T00:00:00Z",
                "bay_window_end": "2026-08-10T00:00:00Z",
            },
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_AIRCRAFT_BUSY)
        assert get_aircraft(busy["id"])["status"] == "IN_SHOP"

    def test_available_aircraft_accepts_work_order(self, api):
        """PRD §3.1: "Only one open work order per aircraft is tolerated — the aircraft must be `AVAILABLE` at creation, otherwise the open fails with `ERR_AIRCRAFT_BUSY`"
        PRD §2.9: "an aircraft reads `IN_SHOP` while any non-terminal work order references it and `AVAILABLE` otherwise. Opening a work order flips its aircraft from `AVAILABLE` to `IN_SHOP`; completing or cancelling that work order flips it back."

        Design: Difficulty/cross_entity_state_dependency/work_order_create_requires_available_aircraft
        """
        customer = create_customer(name="Busy Owner", contact_email="busy@x.com")
        busy = create_aircraft(customer["id"], tail_number="N400CA")
        free = create_aircraft(customer["id"], tail_number="N401CB",
                               baseline_empty_weight_lb=1700.0)
        create_work_order(busy["id"], scope_description="first job")
        opened = validate_success(api.create_work_order(
            {
                "aircraft_id": free["id"],
                "scope_description": "other aircraft job",
                "estimated_downtime_days": 5,
                "quoted_labor_hours": 2,
                "bay_code": "BAY-2",
                "bay_window_start": "2026-08-01T00:00:00Z",
                "bay_window_end": "2026-08-10T00:00:00Z",
            },
            MANAGER,
        ), 201)
        assert opened["status"] == "DRAFT"
        assert get_aircraft(free["id"])["status"] == "IN_SHOP", (
            "the newly opened work order flips the available aircraft to IN_SHOP")


class TestBayWindowHalfOpen:
    def test_adjacent_bay_window_accepted(self, api):
        """PRD §2.6: "Two scheduling disciplines run across the whole system, and both are enforced as half-open intervals: a window includes its start instant and excludes its end instant, so two windows that merely touch — one ending at exactly the instant the other begins — do not overlap."

        Design: Difficulty/resource_temporal_overlap/bay_window_half_open_adjacency
        """
        customer = create_customer(name="Bay Owner", contact_email="bay@x.com",
                                   customer_kind="FLEET_OPERATOR")
        aircraft_a = create_aircraft(customer["id"], tail_number="N500BA")
        aircraft_b = create_aircraft(customer["id"], tail_number="N501BB",
                                     baseline_empty_weight_lb=1700.0)
        create_work_order(aircraft_a["id"], scope_description="bay holder",
                          estimated_downtime_days=15, quoted_labor_hours=20,
                          bay_code="BAY-1",
                          bay_window_start="2026-08-01T00:00:00Z",
                          bay_window_end="2026-08-20T00:00:00Z")
        adjacent = validate_success(api.create_work_order(
            {
                "aircraft_id": aircraft_b["id"],
                "scope_description": "adjacent booking",
                "estimated_downtime_days": 10,
                "quoted_labor_hours": 10,
                "bay_code": "BAY-1",
                "bay_window_start": "2026-08-20T00:00:00Z",
                "bay_window_end": "2026-09-01T00:00:00Z",
            },
            MANAGER,
        ), 201)
        assert adjacent["status"] == "DRAFT", (
            "a window starting exactly at the prior window's end merely touches it "
            "and must be accepted")

    def test_overlapping_bay_window_rejected(self, api):
        """PRD §2.6: "Opening a work order conflicts with another non-terminal work order on the same bay when the new window starts before the existing window ends and ends after the existing window starts; such a conflict is rejected with `ERR_BAY_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/bay_window_half_open_adjacency
        """
        customer = create_customer(name="Bay Owner", contact_email="bay@x.com",
                                   customer_kind="FLEET_OPERATOR")
        aircraft_a = create_aircraft(customer["id"], tail_number="N500BA")
        aircraft_c = create_aircraft(customer["id"], tail_number="N502BC",
                                     baseline_empty_weight_lb=1900.0)
        create_work_order(aircraft_a["id"], scope_description="bay holder",
                          estimated_downtime_days=15, quoted_labor_hours=20,
                          bay_code="BAY-1",
                          bay_window_start="2026-08-01T00:00:00Z",
                          bay_window_end="2026-08-20T00:00:00Z")
        response = api.create_work_order(
            {
                "aircraft_id": aircraft_c["id"],
                "scope_description": "overlapping booking",
                "estimated_downtime_days": 10,
                "quoted_labor_hours": 10,
                "bay_code": "BAY-1",
                "bay_window_start": "2026-08-19T00:00:00Z",
                "bay_window_end": "2026-09-01T00:00:00Z",
            },
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_BAY_WINDOW_CONFLICT)
        assert get_aircraft(aircraft_c["id"])["status"] == "AVAILABLE", (
            "rejected creation persists no work order, so the aircraft stays AVAILABLE")
