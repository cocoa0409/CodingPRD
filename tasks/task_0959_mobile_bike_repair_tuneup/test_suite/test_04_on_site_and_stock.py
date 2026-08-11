"""On-site work events, the parts-wait loop, and the truck-stock ledger."""
from test_helpers import (
    ApiErrorId,
    assert_truck_stock_item,
    complete_request,
    get_request,
    get_route_stop,
    hold_parts,
    make_mechanic_headers,
    make_part,
    make_van,
    make_zone,
    receive_stock,
    release_part,
    reserve_part,
    resume_service,
    return_stock,
    setup_in_service_request,
    setup_quoted_request,
    validate_error,
    validate_paginated,
    validate_success,
    DISPATCH,
)


class TestEventStateGuards:
    def test_start_service_from_quoted_rejected(self, api, dispatcher_headers):
        """PRD §3.7: "Starting service moves `ON_SITE` to `IN_SERVICE`" and "any
        event fired from a state that does not support it draws
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/start_service_from_quoted_rejected
        """
        ctx = setup_quoted_request()
        resp = api.service_request_event(ctx["request"]["id"], {"event_type": "START_SERVICE"}, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_request(ctx["request"]["id"])["work_status"] == "QUOTED", (
            "rejected START_SERVICE must leave the request QUOTED")

    def test_stop_done_requires_completed_request(self, api, dispatcher_headers):
        """PRD §3.7: "Only after the request reaches `COMPLETED` may its stop be
        marked `DONE`"

        Design: Corner/state_machines/stop_done_requires_completed_request
        """
        ctx = setup_in_service_request()
        resp = api.route_stop_event(ctx["stop"]["id"], {"event_type": "DONE"},
                                    make_mechanic_headers(ctx["mechanic"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_route_stop(ctx["stop"]["id"])["status"] == "ARRIVED", (
            "rejected DONE must leave the stop ARRIVED")


class TestPartsHoldCycle:
    def test_hold_resume_cycle_runs_twice(self, api, dispatcher_headers):
        """PRD §3.7: "Starting service moves `ON_SITE` to `IN_SERVICE`; holding for
        parts moves `IN_SERVICE` to `ON_HOLD_PARTS`; resuming moves back, and this
        parts-wait loop is an unrestricted cycle that may repeat as often as
        supply dictates."

        Design: Difficulty/non_linear_state_machine/service_request_parallel_dims_and_parts_hold_cycle
        """
        ctx = setup_in_service_request()
        req_id, mech_id = ctx["request"]["id"], ctx["mechanic"]["id"]

        r1 = hold_parts(req_id, mech_id)
        assert r1["work_status"] == "ON_HOLD_PARTS", f"expected ON_HOLD_PARTS, got {r1['work_status']}"
        r2 = resume_service(req_id, mech_id)
        assert r2["work_status"] == "IN_SERVICE", f"expected IN_SERVICE, got {r2['work_status']}"
        r3 = hold_parts(req_id, mech_id)
        assert r3["work_status"] == "ON_HOLD_PARTS", f"expected ON_HOLD_PARTS, got {r3['work_status']}"
        r4 = resume_service(req_id, mech_id)
        assert r4["work_status"] == "IN_SERVICE", f"expected IN_SERVICE, got {r4['work_status']}"

    def test_billing_dimension_untouched_by_work_cycle(self, api, dispatcher_headers):
        """PRD §3.4: "A new request starts with `work_status` `QUOTED` and
        `billing_status` `ESTIMATED` — two independent dimensions that evolve
        separately from then on"
        PRD §3.7: "The parallel billing dimension is untouched by all of this: a
        request may sit at `COMPLETED` while its `billing_status` is still
        `ESTIMATED`."

        Design: Difficulty/non_linear_state_machine/service_request_parallel_dims_and_parts_hold_cycle
        """
        ctx = setup_in_service_request()
        req_id, mech_id = ctx["request"]["id"], ctx["mechanic"]["id"]

        for action in (hold_parts, resume_service, hold_parts, resume_service):
            data = action(req_id, mech_id)
            assert data["billing_status"] == "ESTIMATED", (
                f"billing_status must stay ESTIMATED through work events, got {data['billing_status']}")

        done = complete_request(req_id, mech_id, 40)
        assert done["work_status"] == "COMPLETED"
        assert done["billing_status"] == "ESTIMATED", (
            "COMPLETED work must not move the parallel billing dimension")


class TestStockReserveBoundary:
    def _setup_stocked_in_service(self, receive_qty=3):
        return setup_in_service_request(parts=[{
            "sku": "A1", "name": "Chain", "unit_price_cents": 1200,
            "warranty_days": 90, "receive": receive_qty,
        }])

    def test_reserve_exactly_available_succeeds(self, api, dispatcher_headers):
        """PRD §3.2: "Three sufficiency guards protect the ledger — a reservation
        may not exceed `on_hand` minus `reserved`, a consumption may not exceed
        `reserved`, and a return may not exceed `on_hand` — and any violation is
        rejected with `ERR_STOCK_INSUFFICIENT` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/stock_reserve_exact_on_hand_boundary
        """
        ctx = self._setup_stocked_in_service(receive_qty=3)
        item = reserve_part(ctx["request"]["id"], ctx["parts"]["A1"]["id"], 3, ctx["mechanic"]["id"])
        assert_truck_stock_item(item)
        # Reserving exactly on_hand - reserved == 3 is legal and leaves zero headroom.
        assert item["on_hand"] == 3, f"on_hand must stay 3, got {item['on_hand']}"
        assert item["reserved"] == 3, f"reserved must become 3, got {item['reserved']}"

    def test_reserve_one_past_available_rejected(self, api, dispatcher_headers):
        """PRD §3.2: "Three sufficiency guards protect the ledger — a reservation
        may not exceed `on_hand` minus `reserved`, a consumption may not exceed
        `reserved`, and a return may not exceed `on_hand` — and any violation is
        rejected with `ERR_STOCK_INSUFFICIENT` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/stock_reserve_exact_on_hand_boundary
        """
        ctx = self._setup_stocked_in_service(receive_qty=3)
        reserve_part(ctx["request"]["id"], ctx["parts"]["A1"]["id"], 3, ctx["mechanic"]["id"])
        resp = api.create_part_usage(ctx["request"]["id"], {
            "part_id": ctx["parts"]["A1"]["id"], "quantity": 1, "action": "RESERVE",
        }, make_mechanic_headers(ctx["mechanic"]["id"]))
        validate_error(resp, ApiErrorId.ERR_STOCK_INSUFFICIENT)


class TestStockConservation:
    def _setup_five_units_in_service(self):
        return setup_in_service_request(parts=[{
            "sku": "A1", "name": "Chain", "unit_price_cents": 1200,
            "warranty_days": 90, "receive": 5,
        }])

    def test_reserve_raises_reserved_not_on_hand(self, api, dispatcher_headers):
        """PRD §3.7: "A reservation — permitted from `DISPATCHED`, `ON_SITE`,
        `IN_SERVICE`, or `ON_HOLD_PARTS` — raises `reserved` and appends a
        `RESERVE` movement."

        Design: Difficulty/compensating_invariant/stock_reserve_release_conserves_units
        """
        ctx = self._setup_five_units_in_service()
        item = reserve_part(ctx["request"]["id"], ctx["parts"]["A1"]["id"], 2, ctx["mechanic"]["id"])
        assert item["on_hand"] == 5, f"reservation must not move on_hand, got {item['on_hand']}"
        assert item["reserved"] == 2, f"reserved must become 2, got {item['reserved']}"

    def test_reserve_then_release_conserves_counters(self, api, dispatcher_headers):
        """PRD §3.2: "The ledger obeys a compensating invariant: a reservation
        followed by a release of the same quantity leaves both counters exactly as
        they were."
        PRD §3.2: "`on_hand` is the sum of `quantity_delta` over receiving and
        returning movements minus the quantities consumed, and `reserved` is the
        reserved quantities minus the released and consumed quantities."

        Design: Difficulty/compensating_invariant/stock_reserve_release_conserves_units
        """
        ctx = self._setup_five_units_in_service()
        req_id, part_id, mech_id = ctx["request"]["id"], ctx["parts"]["A1"]["id"], ctx["mechanic"]["id"]
        reserve_part(req_id, part_id, 2, mech_id)
        item = release_part(req_id, part_id, 2, mech_id)
        assert item["on_hand"] == 5 and item["reserved"] == 0, (
            f"reserve+release must restore on_hand 5 / reserved 0, got "
            f"{item['on_hand']}/{item['reserved']}")

        movements, _ = validate_paginated(api.list_stock_movements(
            DISPATCH, params={"van_id": ctx["van"]["id"], "part_id": part_id}))
        reasons = [m["reason"] for m in movements]
        assert reasons == ["RECEIVE", "RESERVE", "RELEASE"], (
            f"movement log must replay RECEIVE, RESERVE, RELEASE in order, got {reasons}")
        received = sum(m["quantity_delta"] for m in movements if m["reason"] == "RECEIVE")
        returned = sum(-m["quantity_delta"] for m in movements if m["reason"] == "RETURN_TO_WAREHOUSE")
        consumed = sum(1 for m in movements if m["reason"] == "CONSUME")
        assert received - returned - consumed == item["on_hand"] == 5


class TestVanStockRead:
    def test_van_stock_computed_read_after_movements(self, api, dispatcher_headers):
        """PRD §3.2: "Reading the view back: `on_hand` is the sum of
        `quantity_delta` over receiving and returning movements minus the
        quantities consumed, and `reserved` is the reserved quantities minus the
        released and consumed quantities."

        Design: Corner/endpoints/van_stock_computed_read_after_movements
        """
        zone = make_zone(2500)
        van = make_van(zone["id"])
        part = make_part(sku="A1", name="Chain", unit_price_cents=1200, warranty_days=90)
        receive_stock(van["id"], part["id"], 10)
        return_stock(van["id"], part["id"], 3)

        data, _ = validate_paginated(api.list_van_stock(van["id"], dispatcher_headers))
        assert len(data) == 1
        assert_truck_stock_item(data[0])
        assert data[0]["on_hand"] == 7, f"10 received - 3 returned must give on_hand 7, got {data[0]['on_hand']}"
        assert data[0]["reserved"] == 0
