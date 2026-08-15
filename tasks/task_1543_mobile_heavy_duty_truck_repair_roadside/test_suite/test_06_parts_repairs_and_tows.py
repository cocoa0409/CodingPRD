"""On-site work: part usage, van-stock reorder triggers, repair completion,
and tow coordination."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    assert_part_usage,
    complete_repair,
    create_invoice_for_call,
    create_standard_rate_card,
    create_technician,
    create_tow_order_payload,
    create_vehicle,
    diagnose_call,
    drive_call_on_site,
    get_call,
    get_success_data,
    list_restock_requests_for_item,
    open_triaged_call,
    order_tow,
    post_part_usage,
    start_repair,
    stock_van,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _repair_in_progress(qty_on_hand=10, reorder_point=2, part_number="ALT-104"):
    """Business-hours call in REPAIR_IN_PROGRESS; returns ctx dict."""
    create_standard_rate_card()
    veh = create_vehicle()
    tech, tech_headers = create_technician()
    stock = stock_van(tech["id"], part_number=part_number,
                      qty_on_hand=qty_on_hand, reorder_point=reorder_point)
    call = open_triaged_call(veh["id"], severity="DRIVABLE",
                             received_at="2026-08-04T09:00:00Z")
    call, dispatch = drive_call_on_site(
        call, tech["id"], tech_headers, "2026-08-04T09:00:00Z",
        "2026-08-04T13:00:00Z", depart_at=None,
        arrive_at="2026-08-04T09:40:00Z", actual_travel_miles=20)
    diagnose_call(call["id"], tech_headers, diagnosis_summary="alternator")
    call = start_repair(call["id"], tech_headers)
    return {"veh": veh, "tech": tech, "tech_headers": tech_headers,
            "stock": stock, "call": call, "dispatch": dispatch}


class TestAutoRestockCascade:
    def test_part_usage_triggers_auto_restock_request(self, api):
        """PRD: "when `qty_on_hand` is at or below `reorder_point` and no
        restock request for the item is currently `PENDING` or `APPROVED`, the
        system opens an `AUTO_LOW_STOCK` `RestockRequest` whose
        `qty_requested` equals `reorder_point` plus 2 minus the on-hand count
        (at minimum one unit ...) and sets the item's `restock_pending`
        flag".

        Design: Difficulty/transitive_cascade/cascade_part_usage_triggers_auto_restock_request
        """
        ctx = _repair_in_progress(qty_on_hand=3, reorder_point=2)
        post_part_usage(ctx["call"]["id"], ctx["tech_headers"],
                        ctx["stock"]["id"], 1)
        item = get_success_data(
            api.get_van_stock_item(ctx["stock"]["id"], DISPATCHER))
        assert item["qty_on_hand"] == 2, "usage decrements on-hand"
        assert item["restock_pending"] is True
        requests = list_restock_requests_for_item(ctx["stock"]["id"])
        assert len(requests) == 1
        assert requests[0]["source"] == "AUTO_LOW_STOCK"
        assert requests[0]["status"] == "PENDING"
        assert requests[0]["qty_requested"] == 2, (
            "max(1, reorder_point + 2 - qty_on_hand) = max(1, 2+2-2)")

    def test_pending_restock_request_dedupes_further_usage(self, api):
        """PRD: the auto request opens only when "no restock request for the
        item is currently `PENDING` or `APPROVED`" — a second decrement while
        the first request is pending creates no duplicate.

        Design: Difficulty/transitive_cascade/cascade_part_usage_triggers_auto_restock_request
        """
        ctx = _repair_in_progress(qty_on_hand=3, reorder_point=2)
        post_part_usage(ctx["call"]["id"], ctx["tech_headers"],
                        ctx["stock"]["id"], 1)
        post_part_usage(ctx["call"]["id"], ctx["tech_headers"],
                        ctx["stock"]["id"], 1)
        item = get_success_data(
            api.get_van_stock_item(ctx["stock"]["id"], DISPATCHER))
        assert item["qty_on_hand"] == 1
        requests = list_restock_requests_for_item(ctx["stock"]["id"])
        assert len(requests) == 1, (
            "no duplicate AUTO_LOW_STOCK request while one is PENDING")


class TestPartPostReturnInvariant:
    def test_part_post_then_return_restores_van_stock(self, api):
        """PRD: "returning restores the full `qty` to the van's `qty_on_hand`
        (so post plus return leaves the count unchanged), moves the usage to
        `RETURNED`".

        Design: Difficulty/compensating_invariant/part_post_then_return_restores_van_stock_and_invoice
        """
        ctx = _repair_in_progress(qty_on_hand=10, reorder_point=2)
        usage = post_part_usage(ctx["call"]["id"], ctx["tech_headers"],
                                ctx["stock"]["id"], 4)
        assert_part_usage(usage)
        mid = get_success_data(
            api.get_van_stock_item(ctx["stock"]["id"], DISPATCHER))
        assert mid["qty_on_hand"] == 6

        returned = validate_success(api.return_part_usage(
            usage["id"], ctx["tech_headers"]))
        assert returned["status"] == "RETURNED"
        after = get_success_data(
            api.get_van_stock_item(ctx["stock"]["id"], DISPATCHER))
        assert after["qty_on_hand"] == 10, (
            "post + return conserves qty_on_hand")

    def test_returned_usage_contributes_nothing_to_the_invoice(self, api):
        """PRD: "`parts_subtotal_cents` sums `line_total_cents` over the
        call's `POSTED` customer-pay usages" — a RETURNED line is excluded,
        so the invoice shows no parts drift after post-then-return.

        Design: Difficulty/compensating_invariant/part_post_then_return_restores_van_stock_and_invoice
        """
        ctx = _repair_in_progress(qty_on_hand=10, reorder_point=2)
        usage = post_part_usage(ctx["call"]["id"], ctx["tech_headers"],
                                ctx["stock"]["id"], 4)
        validate_success(api.return_part_usage(usage["id"],
                                               ctx["tech_headers"]))
        complete_repair(ctx["call"]["id"], ctx["tech_headers"], 0.5, 90020)
        invoice = create_invoice_for_call(ctx["call"]["id"])
        assert invoice["parts_subtotal_cents"] == 0
        assert invoice["tax_cents"] == 0, (
            "tax is computed on the parts subtotal, which is zero")


class TestReorderThreshold:
    def test_reorder_threshold_exactly_at_point_vs_one_above(self, api):
        """PRD: "an on-hand count exactly at the reorder point triggers, while
        one unit above it does not."

        Design: Corner/calculations/reorder_threshold_exactly_at_point_vs_one_above
        """
        ctx = _repair_in_progress(qty_on_hand=4, reorder_point=2)
        post_part_usage(ctx["call"]["id"], ctx["tech_headers"],
                        ctx["stock"]["id"], 1)
        assert list_restock_requests_for_item(ctx["stock"]["id"]) == [], (
            "4 -> 3 lands one ABOVE reorder_point 2: no request")
        post_part_usage(ctx["call"]["id"], ctx["tech_headers"],
                        ctx["stock"]["id"], 1)
        requests = list_restock_requests_for_item(ctx["stock"]["id"])
        assert len(requests) == 1 and requests[0]["source"] == "AUTO_LOW_STOCK", (
            "3 -> 2 lands exactly AT reorder_point: <= semantics trigger")


class TestRestockFulfillment:
    def test_restock_fulfill_adds_units_and_clears_pending(self, api):
        """PRD: an OpsAdmin "fulfills it with a `fulfilled_qty` of at least
        one (which adds that many units back to `qty_on_hand`, recomputes
        `restock_pending`, and leaves the request `FULFILLED`)".

        Design: Corner/state_machines/restock_fulfill_adds_units_and_clears_pending
        """
        ctx = _repair_in_progress(qty_on_hand=3, reorder_point=2)
        post_part_usage(ctx["call"]["id"], ctx["tech_headers"],
                        ctx["stock"]["id"], 1)
        request = list_restock_requests_for_item(ctx["stock"]["id"])[0]

        approved = validate_success(
            api.approve_restock_request(request["id"], OPS))
        assert approved["status"] == "APPROVED"
        fulfilled = validate_success(api.fulfill_restock_request(
            request["id"], {"fulfilled_qty": 5}, OPS))
        assert fulfilled["status"] == "FULFILLED"

        item = get_success_data(
            api.get_van_stock_item(ctx["stock"]["id"], OPS))
        assert item["qty_on_hand"] == 7, "2 remaining after usage + 5 fulfilled"
        assert item["restock_pending"] is False, (
            "no PENDING/APPROVED request remains")


class TestPartUsageRejectionRules:
    def test_insufficient_van_stock_rejected(self, api):
        """PRD: "the requested quantity may not exceed the item's
        `qty_on_hand` (`ERR_INSUFFICIENT_VAN_STOCK` otherwise)".

        Design: Corner/errors/insufficient_van_stock_rejected
        """
        ctx = _repair_in_progress(qty_on_hand=3, reorder_point=1)
        resp = api.create_part_usage(
            ctx["call"]["id"],
            {"van_stock_item_id": ctx["stock"]["id"], "qty": 5},
            ctx["tech_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VAN_STOCK)
        item = get_success_data(
            api.get_van_stock_item(ctx["stock"]["id"], DISPATCHER))
        assert item["qty_on_hand"] == 3, "no partial decrement on rejection"

    def test_part_usage_from_another_technicians_van_rejected(self, api):
        """PRD: "The stock item must belong to the technician currently
        `ON_SITE` for the call (`ERR_PART_NOT_ON_VAN` otherwise)".

        Design: Corner/errors/part_usage_from_another_technicians_van_rejected
        """
        ctx = _repair_in_progress(qty_on_hand=3)
        spare, _sh = create_technician(full_name="Sam Spare")
        spare_stock = stock_van(spare["id"], qty_on_hand=3)
        resp = api.create_part_usage(
            ctx["call"]["id"],
            {"van_stock_item_id": spare_stock["id"], "qty": 1},
            ctx["tech_headers"])
        validate_error(resp, ApiErrorId.ERR_PART_NOT_ON_VAN)


class TestRepairCompletion:
    def test_odometer_regression_on_complete_repair(self, api):
        """PRD: "a `completion_odometer_miles` that must be at least the
        vehicle's currently recorded `odometer_miles`
        (`ERR_ODOMETER_REGRESSION` otherwise)".

        Design: Corner/validations/odometer_regression_on_complete_repair
        """
        ctx = _repair_in_progress()
        resp = api.complete_repair(
            ctx["call"]["id"],
            {"labor_hours_actual": 0.5, "completion_odometer_miles": 89500},
            ctx["tech_headers"])
        assert resp.status_code == 422
        validate_error(resp, ApiErrorId.ERR_ODOMETER_REGRESSION)
        call = get_call(ctx["call"]["id"])
        assert call["status"] == "REPAIR_IN_PROGRESS"
        veh = get_success_data(api.get_vehicle(ctx["veh"]["id"], DISPATCHER))
        assert veh["odometer_miles"] == 90000


class TestTowCoordination:
    def _tow_in_progress(self):
        """Retail call diagnosed TOW_REQUIRED with a REQUESTED tow order."""
        create_standard_rate_card()
        veh = create_vehicle()
        tech, tech_headers = create_technician()
        call = open_triaged_call(veh["id"], severity="BLOCKING",
                                 received_at="2026-08-05T07:00:00Z",
                                 symptom_description="seized",
                                 breakdown_location_text="site A")
        call, dispatch = drive_call_on_site(
            call, tech["id"], tech_headers, "2026-08-05T07:00:00Z",
            "2026-08-05T09:00:00Z", depart_at=None,
            arrive_at="2026-08-05T07:40:00Z", actual_travel_miles=20)
        diagnose_call(call["id"], tech_headers,
                      diagnosis_summary="seized engine",
                      resolution_path="TOW_REQUIRED")
        tow = order_tow(call["id"])
        return call, dispatch, tow, tech, tech_headers

    def test_tow_hook_after_delivered_rejected(self, api):
        """PRD: "The tow then proceeds through `REQUESTED` to `HOOKED` ...
        and from `HOOKED` to `DELIVERED`" — hooking a DELIVERED order is not a
        declared transition and fails `ERR_INVALID_STATE`.

        Design: Corner/state_machines/tow_hook_after_delivered_rejected
        """
        _call, _d, tow, _t, _th = self._tow_in_progress()
        get_success_data(api.hook_tow_order(tow["id"], DISPATCHER))
        delivered = get_success_data(api.deliver_tow_order(tow["id"],
                                                           DISPATCHER))
        assert delivered["status"] == "DELIVERED"
        resp = api.hook_tow_order(tow["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_tow_on_repair_path_and_start_repair_on_tow_path_rejected(
            self, api):
        """PRD: "beginning a repair requires `ON_SITE_REPAIR` and ordering a
        tow requires `TOW_REQUIRED`, and either action attempted against the
        opposite path is rejected with `ERR_RESOLUTION_PATH_CONFLICT`."

        Design: Corner/errors/tow_on_repair_path_and_start_repair_on_tow_path_rejected
        """
        create_standard_rate_card()
        veh_a = create_vehicle()
        veh_b = create_vehicle()
        tech, tech_headers = create_technician()
        spare, spare_headers = create_technician(full_name="Sam Spare")
        advance_clock("2026-08-05T07:00:00Z")

        # Call A: ON_SITE_REPAIR.
        call_a = open_triaged_call(veh_a["id"], severity="DRIVABLE",
                                   breakdown_location_text="site A")
        call_a, _da = drive_call_on_site(
            call_a, tech["id"], tech_headers, "2026-08-05T07:00:00Z",
            "2026-08-05T09:00:00Z", depart_at=None,
            arrive_at="2026-08-05T07:40:00Z", actual_travel_miles=20)
        diagnose_call(call_a["id"], tech_headers, diagnosis_summary="fuse",
                      resolution_path="ON_SITE_REPAIR")

        # Call B: TOW_REQUIRED (second technician, adjacent window).
        call_b = open_triaged_call(veh_b["id"], severity="BLOCKING",
                                   symptom_description="seized",
                                   breakdown_location_text="site B")
        call_b, _db = drive_call_on_site(
            call_b, spare["id"], spare_headers, "2026-08-05T09:00:00Z",
            "2026-08-05T11:00:00Z", depart_at="2026-08-05T09:10:00Z",
            arrive_at="2026-08-05T09:40:00Z", actual_travel_miles=25)
        diagnose_call(call_b["id"], spare_headers,
                      diagnosis_summary="seized engine",
                      resolution_path="TOW_REQUIRED")

        resp_a = api.create_tow_order(
            call_a["id"],
            create_tow_order_payload(
                tow_unit_id="TT-9",
                pickup_window_start_at="2026-08-05T12:00:00Z",
                pickup_window_end_at="2026-08-05T14:00:00Z",
                tow_fee_cents=80000),
            DISPATCHER)
        validate_error(resp_a, ApiErrorId.ERR_RESOLUTION_PATH_CONFLICT)

        resp_b = api.start_repair(call_b["id"], spare_headers)
        validate_error(resp_b, ApiErrorId.ERR_RESOLUTION_PATH_CONFLICT)
