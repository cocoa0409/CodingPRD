"""Optimistic concurrency, incident workflow, ticket states, listings, clock.

Covers PRD §2.6 (the four OCC-guarded operations), §2.3 (pagination), §2.5
(logical clock default), §3.6 (ticket state rule), §3.7 (incident review
workflow), and the settlement state errors of §3.8.
"""
from test_helpers import (
    TEST_USERS,
    create_weight_ticket_payload,
    make_compliance_headers,
    make_driver_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId as E
from test_helpers.fixtures import (
    allocate_all,
    create_driver,
    create_load,
    create_shipper,
    create_trailer,
    dispute,
    get_load,
    plan_load,
    report_incident,
    set_clock,
    setup_assigned_load,
    setup_delivered_load,
    setup_in_transit_load,
    start_review,
)

ADMIN = TEST_USERS["admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CO2 = make_compliance_headers("co-2")
CONSIGNEE = TEST_USERS["consignee_headers"]


class TestOccAllocation:
    def test_occ_allocation_stale_load_version(self, api):
        """PRD §2.6: "Creating a compartment allocation against a load requires
        `expected_load_version` matching the load's current `version`. After a
        reopen-plan or another allocation, a client allocating against a stale
        plan is rejected."
        PRD §2.6: "if that value does not match the parent entity's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_allocation_stale_load_version
        """
        shipper = create_shipper()
        tt = create_trailer()
        comp_id = tt["compartments"][0]["id"]
        load = create_load(shipper["id"])
        stale_version = load["version"]

        # first allocation advances the load version
        validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": comp_id, "head_count": 10,
                 "avg_weight_lb": 1000,
                 "expected_load_version": stale_version},
                DISP), 201)

        # replaying the stale version is rejected
        resp = api.create_allocation(
            load["id"],
            {"trailer_compartment_id": comp_id, "head_count": 5,
             "avg_weight_lb": 1000, "expected_load_version": stale_version},
            DISP)
        validate_error(resp, E.ERR_STALE_VERSION)

        # retrying with the fresh version succeeds
        fresh = get_load(load["id"])
        validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": comp_id, "head_count": 5,
                 "avg_weight_lb": 1000,
                 "expected_load_version": fresh["version"]},
                DISP), 201)
        assert get_load(load["id"])["allocated_head_count"] == 15


class TestOccAssignDriver:
    def test_occ_assign_driver_stale_version(self, api):
        """PRD §2.6: "Assigning a driver to a load requires
        `expected_driver_version` matching the driver's current `version`; the
        assignment decision was made on a snapshot of the driver's hours and
        standing, and new duty events or another assignment recorded in between
        advance that version."

        Design: Corner/complexity_layers/occ_assign_driver_stale_version
        """
        # build a PAPERWORK_VERIFIED load, then bump the driver version with a
        # duty event after the caller captured the driver's version
        from test_helpers.fixtures import setup_verified_load
        ctx = setup_verified_load()
        driver = create_driver()
        snapshot = driver["version"]
        # a duty event recorded in between advances the driver version
        from test_helpers.fixtures import append_duty_event
        append_duty_event(driver["id"], "DUTY_ON", "2026-08-01T06:00:00Z")

        resp = api.assign_driver(
            ctx["load"]["id"],
            {"driver_id": driver["id"], "expected_driver_version": snapshot},
            DISP)
        validate_error(resp, E.ERR_STALE_VERSION)

        load = get_load(ctx["load"]["id"])
        assert load["status"] == "PAPERWORK_VERIFIED"
        assert load["driver_id"] is None


class TestOccCounter:
    def test_occ_counter_stale_settlement_version(self, api):
        """PRD §2.6: "Countering a settlement requires
        `expected_settlement_version` matching the settlement's current
        `version`; because a fresh counter legitimately supersedes a prior one,
        the stale writer must re-read before countering."
        PRD §3.8: "The counter request carries `counter_weight_lb` and
        `expected_settlement_version`; the version must match the settlement's
        current `version` or the counter is rejected with `ERR_STALE_VERSION`
        (HTTP 412), forcing the dispatcher to re-read before overwriting."

        Design: Corner/complexity_layers/occ_counter_stale_settlement_version
        """
        ctx = setup_delivered_load(net_lb=38800)
        s_id = ctx["settlement"]["id"]

        set_clock("2026-08-03T10:00:00Z")
        dispute(s_id, 37000)
        stale = validate_success(api.get_settlement(s_id, ADMIN))["version"]

        # first counter advances the settlement version
        countered = validate_success(
            api.counter_settlement(
                s_id, {"counter_weight_lb": 38500,
                       "expected_settlement_version": stale},
                DISP), 200)
        assert countered["status"] == "COUNTERED"

        # replaying the pre-counter version is stale
        resp = api.counter_settlement(
            s_id, {"counter_weight_lb": 38600,
                   "expected_settlement_version": stale},
            DISP)
        validate_error(resp, E.ERR_STALE_VERSION)

        s = validate_success(api.get_settlement(s_id, ADMIN))
        assert s["counter_weight_lb"] == 38500
        assert s["status"] == "COUNTERED"


class TestIncidentWorkflow:
    def test_report_incident_on_assigned_load_rejected(self, api):
        """PRD §3.7: "The referenced load must exist (`ERR_LOAD_NOT_FOUND`) and
        must be in `IN_TRANSIT`, `WEATHER_HOLD`, `REST_UNLOAD`, `ARRIVED`, or
        `DELIVERED` (`ERR_LOAD_NOT_REPORTABLE`, HTTP 409); `occurred_at` must
        not be in the future (`ERR_EVENT_IN_FUTURE`)."

        Design: Corner/validations/report_incident_on_assigned_load_rejected
        """
        ctx = setup_assigned_load()
        resp = api.create_incident(
            {"load_id": ctx["load"]["id"], "incident_type": "INJURY",
             "severity": "MINOR", "head_count_affected": 1,
             "occurred_at": "2026-08-01T08:00:00Z"},
            make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, E.ERR_LOAD_NOT_REPORTABLE)

    def test_incident_close_from_reported_rejected(self, api):
        """PRD §3.7: "Closing moves `UNDER_REVIEW → CLOSED` (any other state
        fails with `ERR_INCIDENT_NOT_UNDER_REVIEW`) and accepts an optional
        `fine_waived` flag defaulting to false."

        Design: Corner/state_machines/incident_close_from_reported_rejected
        """
        ctx = setup_in_transit_load()
        set_clock("2026-08-02T09:30:00Z")
        incident = report_incident(ctx["load"]["id"], ctx["driver"]["id"],
                                   incident_type="INJURY", severity="MINOR",
                                   head_count_affected=1,
                                   occurred_at="2026-08-02T09:00:00Z")
        assert incident["status"] == "REPORTED"

        resp = api.close_incident(incident["id"], {}, CO2)
        validate_error(resp, E.ERR_INCIDENT_NOT_UNDER_REVIEW)

        inc = validate_success(api.get_incident(incident["id"], ADMIN))
        assert inc["status"] == "REPORTED"

    def test_start_review_twice_rejected(self, api):
        """PRD §3.7: "Starting review moves `REPORTED → UNDER_REVIEW` (any
        other state fails with `ERR_INCIDENT_NOT_REPORTED`, HTTP 409) and
        increments the incident `version`."

        Design: Corner/errors/start_review_twice_rejected
        """
        ctx = setup_in_transit_load()
        set_clock("2026-08-02T09:30:00Z")
        incident = report_incident(ctx["load"]["id"], ctx["driver"]["id"],
                                   incident_type="DOWNER", severity="MAJOR",
                                   head_count_affected=2,
                                   occurred_at="2026-08-02T09:00:00Z")
        start_review(incident["id"])

        resp = api.start_incident_review(incident["id"], CO2)
        validate_error(resp, E.ERR_INCIDENT_NOT_REPORTED)


class TestTicketStates:
    def test_delivery_ticket_before_arrival_rejected(self, api):
        """PRD §3.6: "The checks run in order: body shape, then load existence,
        then the state rule — an `ORIGIN` ticket is accepted only while the
        load is in `DRAFT`, `PLANNED`, `PAPERWORK_VERIFIED`, `ASSIGNED`, or
        `IN_TRANSIT`, and a `DELIVERY` ticket only while the load is `ARRIVED`
        or while it is `DELIVERED` with its settlement still `PENDING`; any
        other combination is rejected with `ERR_TICKET_STATE_FORBIDDEN`
        (HTTP 409)."

        Design: Corner/errors/delivery_ticket_before_arrival_rejected
        """
        ctx = setup_in_transit_load()
        resp = api.create_weight_ticket(
            ctx["load"]["id"],
            create_weight_ticket_payload(ticket_type="DELIVERY", gross_lb=46000,
                                         tare_lb=6000,
                                         weighed_at="2026-08-02T09:00:00Z"),
            CONSIGNEE)
        validate_error(resp, E.ERR_TICKET_STATE_FORBIDDEN)

    def test_deliver_without_delivery_ticket_rejected(self, api):
        """PRD §3.6: "The load must be `ARRIVED` (`ERR_LOAD_NOT_ARRIVED`,
        HTTP 409) and at least one `DELIVERY` ticket must exist
        (`ERR_NO_DELIVERY_TICKET`, HTTP 422)."

        Design: Corner/validations/deliver_without_delivery_ticket_rejected
        """
        from test_helpers.fixtures import setup_arrived_load
        ctx = setup_arrived_load()
        resp = api.deliver(ctx["load"]["id"], CONSIGNEE)
        validate_error(resp, E.ERR_NO_DELIVERY_TICKET)
        assert get_load(ctx["load"]["id"])["status"] == "ARRIVED"


class TestSettlementStateErrors:
    def test_dispute_twice_rejected(self, api):
        """PRD §3.8: "When the consignee disagrees with the delivered weight, a
        `ConsigneeAgent` disputes the settlement, moving `PENDING → DISPUTED`
        (any other state fails with `ERR_SETTLEMENT_NOT_PENDING`, HTTP 409)."

        Design: Corner/errors/dispute_twice_rejected
        """
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]
        set_clock("2026-08-03T10:00:00Z")
        dispute(s_id, 39000)

        resp = api.dispute_settlement(s_id, {"disputed_weight_lb": 38500},
                                      CONSIGNEE)
        validate_error(resp, E.ERR_SETTLEMENT_NOT_PENDING)

        s = validate_success(api.get_settlement(s_id, ADMIN))
        assert s["disputed_weight_lb"] == 39000

    def test_counter_without_dispute_rejected(self, api):
        """PRD §3.8: "Countering — a `Dispatcher` action — moves `DISPUTED →
        COUNTERED`; countering is also legal from `COUNTERED`, where the new
        counter supersedes the previous one (from any state other than
        `DISPUTED` or `COUNTERED` the attempt fails with
        `ERR_SETTLEMENT_NOT_DISPUTED`)."

        Design: Corner/errors/counter_without_dispute_rejected
        """
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]
        s = validate_success(api.get_settlement(s_id, ADMIN))
        assert s["status"] == "PENDING"

        resp = api.counter_settlement(
            s_id, {"counter_weight_lb": 39000,
                   "expected_settlement_version": s["version"]},
            DISP)
        validate_error(resp, E.ERR_SETTLEMENT_NOT_DISPUTED)

    def test_accept_counter_without_counter_rejected(self, api):
        """PRD §3.8: "Accepting the counter — also a `ConsigneeAgent` action —
        moves `COUNTERED → RESOLVED` (any other state fails with
        `ERR_SETTLEMENT_NOT_COUNTERED`): `dispute_adjustment_cents` is set to
        the shrink penalty as computed at delivery on the delivered-weight
        basis minus the shrink penalty recomputed on the countered-weight
        basis, `effective_delivered_weight_lb` becomes `counter_weight_lb`, the
        shrink fields and `final_amount_cents` are recomputed, and the
        settlement `version` increments."

        Design: Corner/errors/accept_counter_without_counter_rejected
        """
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]
        set_clock("2026-08-03T10:00:00Z")
        dispute(s_id, 39000)

        resp = api.accept_counter(s_id, CONSIGNEE)
        validate_error(resp, E.ERR_SETTLEMENT_NOT_COUNTERED)

    def test_pay_twice_rejected(self, api):
        """PRD §3.8: "It is permitted from `PENDING` or `RESOLVED`; from
        `PRELIMINARY` or from an already `PAID` settlement the attempt fails
        with `ERR_SETTLEMENT_NOT_PAYABLE` (HTTP 409), and from `DISPUTED` or
        `COUNTERED` it fails with `ERR_UNRESOLVED_DISPUTE` (HTTP 422)."
        PRD §3.8: "A successful payment sets `paid_at` to now and increments
        the settlement `version`."

        Design: Corner/errors/pay_twice_rejected
        """
        from test_helpers import assert_ts_eq
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]
        # dispute -> accept-original -> RESOLVED -> pay (no waiting requirement)
        set_clock("2026-08-03T10:00:00Z")
        dispute(s_id, 39000)
        validate_success(api.accept_original(s_id, CONSIGNEE), 200)
        paid = validate_success(api.pay_settlement(s_id, ADMIN), 200)
        assert paid["status"] == "PAID"
        assert_ts_eq(paid["paid_at"], "2026-08-03T10:00:00Z", "paid_at")

        resp = api.pay_settlement(s_id, ADMIN)
        validate_error(resp, E.ERR_SETTLEMENT_NOT_PAYABLE)

        s = validate_success(api.get_settlement(s_id, ADMIN))
        assert s["status"] == "PAID"
        assert_ts_eq(s["paid_at"], "2026-08-03T10:00:00Z",
                     "paid_at unchanged by rejected second pay")


class TestListings:
    def test_list_loads_pagination_envelope(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies how many items to skip
        and defaults to 0."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/endpoints/list_loads_pagination_envelope
        """
        shipper = create_shipper()
        for species, weight, day in (("CATTLE", 10000, "02"),
                                     ("SWINE", 5000, "03"),
                                     ("SHEEP", 3000, "04")):
            create_load(shipper["id"], species=species,
                        declared_head_count=10, declared_weight_lb=weight,
                        planned_duration_hours=5, loaded_miles=100,
                        planned_departure_at=f"2026-08-{day}T08:00:00Z")

        page1, meta1 = validate_paginated(
            api.list_loads(ADMIN, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_loads(ADMIN, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        body = api.list_loads(ADMIN, params={"limit": 2, "offset": 0}).json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_get_load_settlement_returns_empty_array_before_depart(self, api):
        """PRD §3.6: "Reading a load's settlement returns an array of zero or
        one element, and the settlement list can be filtered by `status`."
        PRD §3.6: "The settlement is created at departure in `PRELIMINARY`, one
        per load — its `load_id` is unique."

        Design: Corner/endpoints/get_load_settlement_returns_empty_array_before_depart
        """
        shipper = create_shipper()
        load = create_load(shipper["id"])
        rows = validate_success(api.get_load_settlement(load["id"], ADMIN))
        assert isinstance(rows, list)
        assert len(rows) == 0

    def test_list_loads_filter_by_status(self, api):
        """PRD §3.3: "A load list may be filtered by `status`, `shipper_id`,
        `driver_id`, `trailer_id`, or `backhaul_of_load_id`."

        Design: Corner/complexity_layers/list_loads_filter_by_status
        """
        shipper = create_shipper()
        tt = create_trailer()
        # one DRAFT load and one fully allocated + finalized (PLANNED) load
        create_load(shipper["id"], declared_head_count=10,
                    declared_weight_lb=10000, planned_duration_hours=5,
                    loaded_miles=100)
        planned = create_load(
            shipper["id"], declared_head_count=10, declared_weight_lb=10000,
            planned_duration_hours=5, loaded_miles=100,
            planned_departure_at="2026-08-03T08:00:00Z", destination="C")
        allocate_all(planned, [tt["compartments"][0]["id"]])
        plan_load(planned["id"])

        planned_rows, planned_meta = validate_paginated(
            api.list_loads(ADMIN, params={"status": "PLANNED"}))
        assert len(planned_rows) == 1
        assert planned_rows[0]["id"] == planned["id"]
        assert planned_meta["total_count"] == 1

        draft_rows, draft_meta = validate_paginated(
            api.list_loads(ADMIN, params={"status": "DRAFT"}))
        assert len(draft_rows) == 1
        assert draft_meta["total_count"] == 1

        all_rows, all_meta = validate_paginated(api.list_loads(ADMIN))
        assert all_meta["total_count"] == 2


class TestLogicalClockDefault:
    def test_clock_default_proven_by_future_event_rejection(self, api):
        """PRD §2.5: "Every occurrence of "now" in this document refers to the
        server's logical clock, never to wall-clock time. At server startup the
        logical clock reads exactly `2026-08-01T00:00:00Z`; until it is
        explicitly set, the clock continues to report this default and never
        falls back to wall-clock time."
        PRD §3.1: "First, `occurred_at` must not be later than the current
        logical time, or the append fails with `ERR_EVENT_IN_FUTURE`
        (HTTP 422)."

        Design: Corner/endpoints/clock_default_proven_by_future_event_rejection
        """
        # no set_current_utc call: the clock must read 2026-08-01T00:00:00Z
        driver = create_driver()
        validate_success(
            api.create_duty_event(
                driver["id"],
                {"event_type": "DUTY_ON",
                 "occurred_at": "2026-08-01T00:00:00Z"},
                ADMIN), 201)
        resp = api.create_duty_event(
            driver["id"],
            {"event_type": "DUTY_ON",
             "occurred_at": "2026-08-01T00:00:01Z"},
            ADMIN)
        validate_error(resp, E.ERR_EVENT_IN_FUTURE)
