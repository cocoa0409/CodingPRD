"""Day-of-service: completion invoice variants, completion cascade,
dispatch gating of driver actions, and route close bubble-up."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_route_day,
    dispatch_route,
    find_assessment,
    get_request,
    get_request_assessments,
    get_request_items,
    get_route_day,
    get_success_data,
    make_resident_headers,
    set_clock,
    setup_completed_request,
    setup_scheduled_request,
    validate_error,
    validate_success,
)

DRIVER = TEST_USERS["driver_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]

ROUTE_DATE = "2026-08-10"
SERVICE_MORNING = "2026-08-10T07:00:00Z"


def _scheduled_fridge_oversize(api, street):
    """One APPLIANCE_WITH_REFRIGERANT oversize item, within allowance:
    4500 + 1500 = 6000, surcharge round_half_up(510.0)=510 -> 6510."""
    return setup_scheduled_request(
        street_address=street, service_zone="ZONE_NORTH",
        annual_allowance_items=4, route_date=ROUTE_DATE,
        max_load_units=40, max_stops=25,
        items=((1, "APPLIANCE_WITH_REFRIGERANT", True, True),),
    )


class TestProvisionalVsFinalInvoice:
    def test_clean_complete_final_equals_provisional(self, api):
        """PRD §3.4: "The final invoice builds on the frozen scheduled quote:
        `final_total_cents` is the request's `provisional_total_cents` plus a
        flat contamination penalty of 3000 cents for each item the driver
        flagged — the penalty carries no surcharge and no rounding, so the
        final total is always at least the provisional total."
        PRD §3.4: "**Completion** moves the stop `SCHEDULED → COMPLETED` and
        is the fiscal climax. The driver may flag specific collected items as
        having been set out with improper preparation by passing their ids in
        `improper_preparation_item_ids`."

        Design: Difficulty/dual_variant_calc/pickup_request_provisional_vs_final_invoice
        """
        hh, req, items, rd = _scheduled_fridge_oversize(api, "1 Elm St")
        set_clock(SERVICE_MORNING)
        dispatch_route(rd["id"])

        data = get_success_data(
            api.complete_pickup_request(req["id"], {}, DRIVER)
        )
        assert data["status"] == "COMPLETED"
        assert data["provisional_total_cents"] == 6510
        assert data["final_total_cents"] == 6510

    def test_contaminated_complete_adds_flat_penalty(self, api):
        """PRD §3.4: "`final_total_cents` is the request's
        `provisional_total_cents` plus a flat contamination penalty of 3000
        cents for each item the driver flagged — the penalty carries no
        surcharge and no rounding, so the final total is always at least the
        provisional total. Completion creates a `FINAL_INVOICE` FeeAssessment
        for that amount in `PENDING` status"

        Design: Difficulty/dual_variant_calc/pickup_request_provisional_vs_final_invoice
        """
        hh, req, items, rd = _scheduled_fridge_oversize(api, "2 Elm St")
        set_clock(SERVICE_MORNING)
        dispatch_route(rd["id"])

        data = get_success_data(api.complete_pickup_request(
            req["id"], {"improper_preparation_item_ids": [items[0]["id"]]}, DRIVER
        ))
        assert data["provisional_total_cents"] == 6510
        assert data["final_total_cents"] == 9510
        assert data["final_total_cents"] > data["provisional_total_cents"]

        invoice = find_assessment(
            get_request_assessments(req["id"]), "FINAL_INVOICE"
        )
        assert invoice["amount_cents"] == 9510
        assert invoice["status"] == "PENDING"


class TestCompletionCascade:
    def _setup(self, api):
        set_clock("2026-08-05T00:00:00Z")
        hh, req, items, rd = setup_scheduled_request(
            street_address="21 Spruce St", service_zone="ZONE_SOUTH",
            annual_allowance_items=4, route_date=ROUTE_DATE,
            items=(
                (1, "MATTRESS", False, True),
                (2, "APPLIANCE_NO_REFRIGERANT", False, True),
            ),
        )
        set_clock(SERVICE_MORNING)
        dispatch_route(rd["id"])
        return hh, req, items, rd

    def test_complete_waives_superseded_provisional_quote(self, api):
        """PRD §3.4: "Completion creates a `FINAL_INVOICE` FeeAssessment for
        that amount in `PENDING` status, waives the now-superseded
        `PROVISIONAL_QUOTE` assessment, assigns every collected item its
        `disposition_route` (§3.5), and bumps the request's `version`."

        Design: Difficulty/transitive_cascade/completion_cascade_depth2
        """
        hh, req, items, rd = self._setup(api)
        data = get_success_data(api.complete_pickup_request(req["id"], {}, DRIVER))
        assert data["status"] == "COMPLETED"

        assessments = get_request_assessments(req["id"])
        invoice = find_assessment(assessments, "FINAL_INVOICE")
        # mattress within allowance: 1200 + round_half_up(102.0)=102 -> 1302
        assert invoice["amount_cents"] == 1302
        assert invoice["status"] == "PENDING"
        quote = find_assessment(assessments, "PROVISIONAL_QUOTE")
        assert quote["status"] == "WAIVED"

    def test_complete_assigns_disposition_routes_by_category(self, api):
        """PRD §3.5: "At completion, every collected item receives its
        downstream destination in `disposition_route`, assigned purely by
        category: `STANDARD_FURNITURE` goes to `LANDFILL`, `MATTRESS` to
        `MATTRESS_RECYCLING`, `APPLIANCE_NO_REFRIGERANT` to `METAL_RECYCLING`,
        `APPLIANCE_WITH_REFRIGERANT` to `REFRIGERANT_RECOVERY` (refrigerant
        items always route to recovery first, regardless of oversize),
        `ELECTRONICS` to `E_WASTE`, and `TIRES` to `TIRE_RECYCLING`."

        Design: Difficulty/transitive_cascade/completion_cascade_depth2
        """
        hh, req, items, rd = self._setup(api)
        get_success_data(api.complete_pickup_request(req["id"], {}, DRIVER))

        after_items = get_request_items(req["id"], INSPECTOR)
        by_seq = {i["sequence_no"]: i for i in after_items}
        assert by_seq[1]["disposition_route"] == "MATTRESS_RECYCLING"
        assert by_seq[2]["disposition_route"] == "METAL_RECYCLING"


class TestCompletionGatedByRouteDispatched:
    def test_complete_blocked_while_route_open(self, api):
        """PRD §3.4: "A `Driver` working a dispatched route resolves each stop
        in one of three ways, all of which require the logical clock's date to
        equal the request's `scheduled_date` — off-date driver actions are
        `ERR_TEMPORAL_CONFLICT` — and all of which require the request to be
        `SCHEDULED`, anything else being `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/completion_gated_by_routeday_dispatched
        """
        set_clock("2026-08-05T00:00:00Z")
        hh, req, _, rd = setup_scheduled_request(
            street_address="61 Alder Aly", service_zone="ZONE_SOUTH",
            route_date=ROUTE_DATE,
        )
        set_clock(SERVICE_MORNING)
        # Route left OPEN (never dispatched).
        resp = api.complete_pickup_request(req["id"], {}, DRIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        assert get_request(hh["id"], req["id"])["status"] == "SCHEDULED"

    def test_refuse_blocked_while_route_open(self, api):
        """PRD §3.4: "A `Driver` working a dispatched route resolves each stop
        in one of three ways, all of which require the logical clock's date to
        equal the request's `scheduled_date` — off-date driver actions are
        `ERR_TEMPORAL_CONFLICT` — and all of which require the request to be
        `SCHEDULED`, anything else being `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/completion_gated_by_routeday_dispatched
        """
        set_clock("2026-08-05T00:00:00Z")
        hh, req, _, rd = setup_scheduled_request(
            street_address="63 Alder Aly", service_zone="ZONE_SOUTH",
            route_date=ROUTE_DATE,
        )
        set_clock(SERVICE_MORNING)
        resp = api.refuse_pickup_request(
            req["id"], {"refusal_reason_code": "BLOCKED_ACCESS"}, DRIVER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_request(hh["id"], req["id"])["status"] == "SCHEDULED"


class TestRouteCloseGate:
    def test_route_close_blocked_while_stop_scheduled(self, api):
        """PRD §3.4: "When every stop on a dispatched route has left
        `SCHEDULED` — each request sitting in `COMPLETED`, `REFUSED`,
        `MISSED`, or `CANCELLED` — the `Dispatcher` may close the route,
        moving it `DISPATCHED → CLOSED` with a version bump. The bubble-up
        gate is strict: closing while any request on the route is still
        `SCHEDULED` fails with `ERR_ROUTE_NOT_EMPTY`."

        Design: Corner/state_machines/route_close_blocked_while_stop_scheduled
        """
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_WEST", route_date=ROUTE_DATE)
        hh1, req1, _, _ = setup_scheduled_request(
            street_address="21 Close Ct", service_zone="ZONE_WEST",
            items=((1, "TIRES", False, True),), route_day=rd,
        )
        setup_scheduled_request(
            street_address="22 Close Ct", service_zone="ZONE_WEST",
            items=((1, "TIRES", False, True),), route_day=rd,
        )
        set_clock(SERVICE_MORNING)
        dispatch_route(rd["id"])
        get_success_data(api.complete_pickup_request(req1["id"], {}, DRIVER))

        resp = api.close_route_day(rd["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_EMPTY)
        assert resp.status_code == 409
        assert get_route_day(rd["id"])["status"] == "DISPATCHED"
