"""Vessel registration, shift windows, and gang order placement basics."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_gang_order,
    assert_vessel_call,
    berth_vessel,
    create_gang_order_payload,
    create_vessel,
    create_vessel_call_payload,
    get_gang,
    open_shift,
    place_gang,
    create_shift,
    setup_vessel_with_open_shift,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVesselCreation:

    def test_vessel_create_applies_system_defaults(self, api, admin_headers):
        """PRD §3.1: "A new vessel call is born in `SCHEDULED` status with `work_posture` `NORMAL` and both `actual_moves` and `actual_tons` at zero."

        Design: Corner/entities/vessel_create_applies_system_defaults
        """
        resp = api.create_vessel_call(
            create_vessel_call_payload(
                vessel_name="MV Defaults", voyage_number="D-001",
                planned_moves=10, planned_tons=5, contracted_mph_target=20.0,
                credit_limit_cents=1_000_000),
            admin_headers)
        data = validate_success(resp, 201)
        assert_vessel_call(data)
        assert data["status"] == "SCHEDULED"
        assert data["work_posture"] == "NORMAL"
        assert data["actual_moves"] == 0
        assert data["actual_tons"] == 0

    def test_vessel_create_zero_cargo_plan_returns_400(self, api, admin_headers):
        """PRD §3.1: "The cargo plan may be container-only, breakbulk-only, or mixed, but it may not be empty: a call registered with zero planned moves and zero planned tons is rejected with `ERR_CARGO_PLAN_REQUIRED` (400), while either quantity being positive satisfies the rule (neither may be negative)."

        Design: Corner/entities/vessel_create_zero_cargo_plan_returns_400
        """
        resp = api.create_vessel_call(
            create_vessel_call_payload(
                vessel_name="MV Empty", voyage_number="D-002",
                planned_moves=0, planned_tons=0),
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_CARGO_PLAN_REQUIRED)

        # Either quantity positive satisfies the rule.
        ok_moves = api.create_vessel_call(
            create_vessel_call_payload(voyage_number="D-002A",
                                       planned_moves=1, planned_tons=0),
            admin_headers)
        validate_success(ok_moves, 201)
        ok_tons = api.create_vessel_call(
            create_vessel_call_payload(voyage_number="D-002B",
                                       planned_moves=0, planned_tons=1),
            admin_headers)
        validate_success(ok_tons, 201)


class TestShiftWindowValidation:

    def test_shift_window_end_not_after_start_returns_400(self, api, superintendent_headers):
        """PRD §3.1: "The end must be later than the start and the duration no more than 960 minutes; a window failing either condition is rejected with `ERR_SHIFT_WINDOW_INVALID` (400)."

        Design: Corner/entities/shift_window_end_not_after_start_returns_400
        """
        vessel = create_vessel(vessel_name="MV ShiftVal", voyage_number="D-003")
        berth_vessel(vessel["id"])

        zero_length = api.create_shift_window(
            {"vessel_call_id": vessel["id"], "shift_date": "2026-08-10",
             "period": "DAY", "start_utc": "2026-08-10T08:00:00Z",
             "end_utc": "2026-08-10T08:00:00Z"},
            superintendent_headers)
        validate_error(zero_length, ApiErrorId.ERR_SHIFT_WINDOW_INVALID)

        # 08:00 -> next-day 00:01 is 961 minutes, one over the 960-minute cap.
        too_long = api.create_shift_window(
            {"vessel_call_id": vessel["id"], "shift_date": "2026-08-10",
             "period": "DAY", "start_utc": "2026-08-10T08:00:00Z",
             "end_utc": "2026-08-11T00:01:00Z"},
            superintendent_headers)
        validate_error(too_long, ApiErrorId.ERR_SHIFT_WINDOW_INVALID)


class TestWorkerRegistration:

    def test_worker_duplicate_registration_returns_409(self, api, admin_headers):
        """PRD §3.3: "Workers enter the system when a `StevedoreAdmin` registers them with a `full_name`, a `registration_number` that is unique across all workers (a duplicate is rejected with `ERR_DUPLICATE_REGISTRATION`, 409), a `classification` from the five dispatch classes, a `registered_on` date that anchors seniority, and a `base_hourly_rate_cents` greater than zero."

        Design: Corner/entities/worker_duplicate_registration_returns_409
        """
        first = api.create_worker(
            {"full_name": "W One", "registration_number": "R001",
             "classification": "HOLDMAN", "registered_on": "2010-01-01",
             "base_hourly_rate_cents": 4000},
            admin_headers)
        validate_success(first, 201)

        # A different classification does not rescue the duplicate number.
        dup = api.create_worker(
            {"full_name": "W Other", "registration_number": "R001",
             "classification": "DRIVER", "registered_on": "2020-01-01",
             "base_hourly_rate_cents": 3800},
            admin_headers)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_REGISTRATION)


class TestGangOrderReadAndSchema:

    def test_gang_order_get_with_unknown_id_returns_404(self, api, superintendent_headers):
        """PRD §2.4: "Every identifier appearing in a path, and every foreign key appearing in a request body, is validated to reference an existing resource; an unresolvable reference is rejected with `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/gang_order_get_with_unknown_id_returns_404
        """
        resp = api.get_gang_order(NON_EXISTENT_UUID, superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_gang_order_create_missing_required_field_returns_400(self, api, superintendent_headers):
        """PRD §2.5: "Required fields are present, enum values are in range, and numeric ranges hold. The generic failure is `ERR_VALIDATION` (400)"
        PRD §3.2: "The order names its `shift_window_id`, a `gang_type` of `CRANE_GANG`, `HOLD_GANG`, `LASHING_GANG`, `DRIVING_GANG`, or `GENERAL`, a `required_classification` of `CRANE_OPERATOR`, `HOLDMAN`, `LASHER`, `DRIVER`, or `CLERK` that defines dispatch eligibility, a `required_headcount` of at least one, a `required_equipment_type` of `SHIP_CRANE`, `RTG`, `FORKLIFT`, or `TRACTOR`, and a `required_equipment_count` of zero or more units of that type that must be covered before work may start."

        Design: Corner/entities/gang_order_create_missing_required_field_returns_400
        """
        _vessel, shift = setup_vessel_with_open_shift(
            vessel_overrides={"vessel_name": "MV Req", "voyage_number": "D-004"})
        payload = create_gang_order_payload(shift["id"])
        del payload["required_headcount"]
        resp = api.create_gang_order(payload, superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestVesselListPagination:

    def test_vessel_list_pagination_envelope(self, api, admin_headers, billing_headers):
        """PRD §2.3: "List endpoints are paginated through two query parameters: `limit`, the maximum number of items returned, defaults to 10 and accepts values from a minimum of 1 to a maximum of 100; `offset`, the number of items skipped, defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/vessel_list_pagination_envelope
        """
        for i in (1, 2, 3):
            create_vessel(vessel_name=f"MV P{i}", voyage_number=f"PG-{i}")

        page1_resp = api.list_vessel_calls(billing_headers,
                                           params={"limit": 2, "offset": 0})
        page1, meta1 = validate_paginated(page1_resp)
        assert page1_resp.json()["response_type"] == "array"
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2_resp = api.list_vessel_calls(billing_headers,
                                           params={"limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(page2_resp)
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        # created_at ascending order across pages
        names = [v["vessel_name"] for v in page1 + page2]
        assert names == ["MV P1", "MV P2", "MV P3"]


class TestGangOrderCreateShiftGate:

    def test_gang_order_create_against_planned_shift_rejected(self, api, superintendent_headers):
        """PRD §3.2: "A `StevedoreSuperintendent` places one against a shift that is currently `OPEN_FOR_ORDERS`; placing against a shift in any other state is rejected with `ERR_SHIFT_NOT_OPEN_FOR_ORDERS` (409)."

        Design: Difficulty/cross_entity_state_dependency/gang_order_create_requires_open_shift
        """
        vessel = create_vessel(vessel_name="MV XDep1", voyage_number="X-301")
        berth_vessel(vessel["id"])
        shift = create_shift(vessel["id"])  # remains PLANNED

        resp = api.create_gang_order(
            create_gang_order_payload(shift["id"], required_headcount=1),
            superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_OPEN_FOR_ORDERS)

    def test_gang_order_create_succeeds_once_shift_opened(self, api, superintendent_headers):
        """PRD §3.2: "A `StevedoreSuperintendent` places one against a shift that is currently `OPEN_FOR_ORDERS`; placing against a shift in any other state is rejected with `ERR_SHIFT_NOT_OPEN_FOR_ORDERS` (409)."
        PRD §3.2: "A new order is born `PLACED` with `filled_headcount` and `offered_count` at zero, `assigned_equipment_ok` false, and `suspension_count` at zero."

        Design: Difficulty/cross_entity_state_dependency/gang_order_create_requires_open_shift
        """
        vessel = create_vessel(vessel_name="MV XDep1B", voyage_number="X-301B")
        berth_vessel(vessel["id"])
        shift = create_shift(vessel["id"])

        blocked = api.create_gang_order(
            create_gang_order_payload(shift["id"]), superintendent_headers)
        validate_error(blocked, ApiErrorId.ERR_SHIFT_NOT_OPEN_FOR_ORDERS)

        open_shift(shift["id"])
        created = api.create_gang_order(
            create_gang_order_payload(shift["id"]), superintendent_headers)
        data = validate_success(created, 201)
        assert_gang_order(data)
        assert data["status"] == "PLACED"
        assert data["filled_headcount"] == 0
        assert data["offered_count"] == 0
        assert data["assigned_equipment_ok"] is False


class TestGangOrderInvalidTransitions:

    def test_gang_complete_from_placed_returns_invalid_state(self, api, foreman_headers):
        """PRD §3.5: "Completing the gang is the foreman's final act on the order, from `WORKING` to `COMPLETED`."
        PRD §2.5: "The target entity's current state permits the requested operation. The generic failure is `ERR_INVALID_STATE` (409)"

        Design: Corner/state_machines/gang_complete_from_placed_returns_invalid_state
        """
        ns = setup_vessel_with_open_shift(
            vessel_overrides={"vessel_name": "MV BadTrans", "voyage_number": "S-101"})
        gang = place_gang(ns[1]["id"])
        resp = api.complete_gang_order(gang["id"], foreman_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_gang(gang["id"])["status"] == "PLACED"

    def test_cancelled_gang_is_terminal_returns_invalid_state(self, api, superintendent_headers):
        """PRD §3.2: "Cancellation is the superintendent's prerogative from any non-terminal state and always releases the order's holdings."
        PRD §2.5: "The target entity's current state permits the requested operation. The generic failure is `ERR_INVALID_STATE` (409)"

        Design: Corner/state_machines/cancelled_gang_is_terminal_returns_invalid_state
        """
        ns = setup_vessel_with_open_shift(
            vessel_overrides={"vessel_name": "MV Term", "voyage_number": "S-102"})
        gang = place_gang(ns[1]["id"])
        first = api.cancel_gang_order(gang["id"], superintendent_headers)
        assert validate_success(first)["status"] == "CANCELLED"

        second = api.cancel_gang_order(gang["id"], superintendent_headers)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)
        assert get_gang(gang["id"])["status"] == "CANCELLED"


class TestGangOrderListFilter:

    def test_gang_orders_filtered_list_by_shift_window(self, api, dispatcher_headers):
        """PRD §2.3: "List endpoints accept optional equality filters corresponding to their resource's foreign keys and lifecycle state: `status`, `vessel_call_id`, `shift_window_id`, `gang_order_id`, `worker_id`, `classification`, `equipment_type`, and `equipment_unit_id`, each applicable to the list endpoints whose resource carries that field, alongside `limit` and `offset`."
        PRD §2.3: "Every list endpoint returns items ordered by `created_at` ascending."

        Design: Corner/endpoints/gang_orders_filtered_list_by_shift_window
        """
        vessel = create_vessel(vessel_name="MV Filter", voyage_number="E-402")
        berth_vessel(vessel["id"])
        s1 = create_shift(vessel["id"], start_utc="2026-08-10T08:00:00Z",
                          end_utc="2026-08-10T16:00:00Z")
        s2 = create_shift(vessel["id"], period="NIGHT",
                          start_utc="2026-08-10T18:00:00Z",
                          end_utc="2026-08-11T02:00:00Z")
        open_shift(s1["id"])
        open_shift(s2["id"])
        g1 = place_gang(s1["id"], required_headcount=1)
        g2 = place_gang(s1["id"], gang_type="LASHING_GANG",
                        required_classification="LASHER", required_headcount=2,
                        required_equipment_type="FORKLIFT",
                        required_equipment_count=1)
        g3 = place_gang(s2["id"], required_headcount=3)

        resp1 = api.list_gang_orders(dispatcher_headers,
                                     params={"shift_window_id": s1["id"]})
        data1, meta1 = validate_paginated(resp1)
        assert meta1["total_count"] == 2
        assert [g["id"] for g in data1] == [g1["id"], g2["id"]]

        resp2 = api.list_gang_orders(dispatcher_headers,
                                     params={"shift_window_id": s2["id"]})
        data2, meta2 = validate_paginated(resp2)
        assert meta2["total_count"] == 1
        assert [g["id"] for g in data2] == [g3["id"]]
