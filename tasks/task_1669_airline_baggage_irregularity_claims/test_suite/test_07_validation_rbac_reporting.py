"""Validation cascade, RBAC, uniqueness guards, immediate consistency, and the
station irregularity summary (PRD §2.1, §2.7, §2.10, §3.2, §3.3, §3.5, §3.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    CLOCK_EPOCH, CLOCK_PLUS_504H,
    create_station_payload, create_carrier_payload, create_courier_service_payload,
    create_passenger_payload, create_bag_tag_payload, create_report_payload,
    create_tracing_event_payload, create_dispatch_payload,
    create_station, create_carrier, create_passenger, create_bag_tag, create_report,
    create_courier_service, set_clock, setup_bag_and_report,
    setup_found_pending_delivery, setup_closed_report,
    create_expense_claim, make_receipt,
    TEST_USERS, make_passenger_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]
PASSENGER = TEST_USERS["passenger_headers"]


class TestAuthAndRbac:

    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Failure to provide valid, well-formed headers will result in
        an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error (HTTP 400)."

        Design: Corner/errors/missing_auth_headers_rejected
        """
        set_clock(CLOCK_EPOCH)
        station = create_station()
        resp = api.get_station(station["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       400)

    def test_passenger_cannot_create_dispatch(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside the caller's designated role is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /baggage/dispatches is authorized for BaggageServiceAgent only.

        Design: Corner/rbac/passenger_cannot_create_dispatch
        """
        set_clock(CLOCK_EPOCH)
        create_station()
        resp = api.create_dispatch(
            create_dispatch_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            make_passenger_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

    def test_agent_cannot_adjudicate_claim(self, api):
        """PRD §2.1: "an attempt to perform an action outside the caller's
        designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.6: "Adjudication belongs to the `ClaimsAdjuster`"

        Design: Corner/rbac/agent_cannot_adjudicate_claim
        """
        ctx = setup_bag_and_report(report_type="DELAYED")
        claim = create_expense_claim(ctx["report"]["id"], ctx["passenger"]["id"],
                                     [make_receipt("2026-08-02", 4000, "USD",
                                                   "meals")])
        resp = api.adjudicate_expense_claim(claim["id"], {"decision": "APPROVE"},
                                            AGENT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
        current = get_success_data(api.get_expense_claim(claim["id"], ADJUSTER))
        assert current["status"] == "SUBMITTED"

    def test_adjuster_cannot_create_courier_service(self, api):
        """PRD §2.1: "A `SystemAdmin` is the back-office administrator who owns
        configuration entities — stations, carriers, courier services, and repair
        vendors — and exclusively controls the logical clock."
        PRD §2.1: "an attempt to perform an action outside the caller's designated
        role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/adjuster_cannot_create_courier_service
        """
        set_clock(CLOCK_EPOCH)
        station = create_station()
        resp = api.create_courier_service(
            create_courier_service_payload([station["id"]]), ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

    def test_passenger_can_read_own_report(self, api):
        """PRD §2.1: "When `X-User-Role` is `Passenger`, `X-User-ID` is the `id` of
        the acting Passenger; ownership checks on any resource that references a
        Passenger compare the resource's `passenger_id` foreign-key field to
        `X-User-ID`."
        PRD §4: GET /baggage/reports/{id} is authorized for all roles.

        Design: Corner/rbac/passenger_can_read_own_report
        """
        ctx = setup_bag_and_report(is_international=False, weight_kg=20,
                                   report_type="DELAYED")
        resp = api.get_report(ctx["report"]["id"],
                              make_passenger_headers(ctx["passenger"]["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "TRACING"
        assert data["effective_cap_cents"] == 50000


class TestUniquenessAndCrossEntityGuards:

    def test_duplicate_tag_number_rejected(self, api):
        """PRD §3.2: "Tag numbers are unique across all bag tags — a duplicate is
        rejected with `ERR_DUPLICATE_TAG_NUMBER`"

        Design: Corner/validations/duplicate_tag_number_rejected
        """
        set_clock(CLOCK_EPOCH)
        carrier = create_carrier()
        passenger = create_passenger()
        payload1 = create_bag_tag_payload(passenger["id"], [carrier["id"]],
                                          weight_kg=20)
        get_success_data(api.create_bag_tag(payload1, AGENT))
        payload2 = create_bag_tag_payload(passenger["id"], [carrier["id"]],
                                          weight_kg=15,
                                          tag_number=payload1["tag_number"])
        resp = api.create_bag_tag(payload2, AGENT)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAG_NUMBER, 409)

    def test_declared_value_over_max_rejected(self, api):
        """PRD §3.2: "A passenger may declare excess value at check-in through
        `declared_value_cents`, which defaults to zero and may not exceed 500000
        cents; a declared value above that ceiling is rejected with
        `ERR_DECLARED_VALUE_EXCEEDS_MAX` (HTTP 422)."

        Design: Corner/validations/declared_value_over_max_rejected
        """
        set_clock(CLOCK_EPOCH)
        carrier = create_carrier()
        passenger = create_passenger()
        payload = create_bag_tag_payload(passenger["id"], [carrier["id"]],
                                         declared_value_cents=500001)
        resp = api.create_bag_tag(payload, AGENT)
        validate_error(resp, ApiErrorId.ERR_DECLARED_VALUE_EXCEEDS_MAX, 422)

    def test_duplicate_report_reference_rejected(self, api):
        """PRD §3.3: "supplying a `report_reference` (the WorldTracer file
        reference, such as JFKAA00001, unique across all reports and guarded by
        `ERR_DUPLICATE_REPORT_REFERENCE`)"

        Design: Corner/validations/report_reference_unique_rejected
        """
        set_clock(CLOCK_EPOCH)
        station = create_station()
        carrier = create_carrier()
        passenger = create_passenger()
        bag1 = create_bag_tag(passenger["id"], [carrier["id"]])
        bag2 = create_bag_tag(passenger["id"], [carrier["id"]])
        p1 = create_report_payload(passenger["id"], bag1["id"], station["id"],
                                   type="DELAYED")
        get_success_data(api.create_report(p1, AGENT))
        p2 = create_report_payload(passenger["id"], bag2["id"], station["id"],
                                   type="DELAYED",
                                   report_reference=p1["report_reference"])
        resp = api.create_report(p2, AGENT)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT_REFERENCE, 409)

    def test_bag_already_reported_rejected(self, api):
        """PRD §3.3: "a bag tag may have at most one report that is not yet
        `CLOSED`, so filing a second open report against the same tag is rejected
        with `ERR_BAG_ALREADY_REPORTED`."

        Design: Corner/validations/bag_already_reported_rejected
        """
        ctx = setup_bag_and_report(report_type="DELAYED")
        resp = api.create_report(
            create_report_payload(ctx["passenger"]["id"], ctx["bag"]["id"],
                                  ctx["station"]["id"], type="DAMAGED"), AGENT)
        validate_error(resp, ApiErrorId.ERR_BAG_ALREADY_REPORTED, 409)

    def test_bag_passenger_mismatch_rejected(self, api):
        """PRD §3.3: "The report's `passenger_id` must equal the referenced bag
        tag's `passenger_id` — a mismatch is rejected with
        `ERR_BAG_PASSENGER_MISMATCH`"

        Design: Corner/validations/bag_passenger_mismatch_rejected
        """
        set_clock(CLOCK_EPOCH)
        station = create_station()
        carrier = create_carrier()
        pax_a = create_passenger(full_name="Pat Flyer", email="pat@x.com")
        pax_b = create_passenger(full_name="Sam Other", email="sam@x.com")
        bag = create_bag_tag(pax_a["id"], [carrier["id"]])
        resp = api.create_report(
            create_report_payload(pax_b["id"], bag["id"], station["id"],
                                  type="DELAYED"), AGENT)
        validate_error(resp, ApiErrorId.ERR_BAG_PASSENGER_MISMATCH, 409)


class TestValidationOrdering:

    def test_existence_beats_state(self, api):
        """PRD §2.10: "Every request is screened against an ordered validation
        cascade, and the first failing check determines the rejection. The order is
        fixed:" with existence (item 5, `ERR_NOT_FOUND`) before state (item 6).
        PRD §2.7: "the system validates each identifier in sequential, left-to-right
        order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not correspond to an existing resource."

        Design: Corner/validations/existence_beats_state_priority_ordering
        """
        set_clock(CLOCK_EPOCH)
        station = create_station()
        resp = api.offer_settlement(
            NON_EXISTENT_UUID,
            {"root_cause": "MISCONNECT", "root_cause_station_id": station["id"]},
            ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_zone_referential_beats_window_temporal(self, api):
        """PRD §2.10: "Every request is screened against an ordered validation
        cascade, and the first failing check determines the rejection." Item 7 lists
        `ERR_COURIER_ZONE_MISMATCH` (cross-entity referential) and item 8 lists
        `ERR_DISPATCH_WINDOW_CONFLICT` (temporal).
        PRD §3.5: "The chosen courier must actually serve the report's filing
        station — the report's `station_id` must appear in the courier's
        `serves_station_ids` — failing which the request is rejected with
        `ERR_COURIER_ZONE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_zone_referential_beats_window_temporal
        """
        set_clock(CLOCK_EPOCH)
        stn_jfk = get_success_data(api.create_station(
            create_station_payload(station_code="JFK", name="New York JFK",
                                   bags_handled_total=1000000), ADMIN))
        stn_lax = get_success_data(api.create_station(
            create_station_payload(station_code="LAX", name="Los Angeles",
                                   bags_handled_total=800000), ADMIN))
        carrier = create_carrier()
        # Courier serves LAX only.
        courier = create_courier_service([stn_lax["id"]], turnaround_buffer_minutes=60)
        passenger = create_passenger()

        bag_a = create_bag_tag(passenger["id"], [carrier["id"]])
        rpt_a = create_report(passenger["id"], bag_a["id"], stn_lax["id"],
                              report_type="DELAYED")
        bag_b = create_bag_tag(passenger["id"], [carrier["id"]])
        rpt_b = create_report(passenger["id"], bag_b["id"], stn_jfk["id"],
                              report_type="DELAYED")
        for rpt, stn in ((rpt_a, stn_lax), (rpt_b, stn_jfk)):
            get_success_data(api.record_tracing_event(
                rpt["id"],
                create_tracing_event_payload(carrier["id"], stn["id"], "LOCATED"),
                AGENT))
        # Existing dispatch on the courier at LAX: [10:00, 12:00].
        get_success_data(api.create_dispatch(
            create_dispatch_payload(rpt_a["id"], courier["id"],
                                    pickup_at="2026-08-02T10:00:00Z"), AGENT))
        # B violates the zone (courier does not serve JFK) AND overlaps A's window.
        resp = api.create_dispatch(
            create_dispatch_payload(rpt_b["id"], courier["id"],
                                    pickup_at="2026-08-02T11:00:00Z"), AGENT)
        err = validate_error(resp, ApiErrorId.ERR_COURIER_ZONE_MISMATCH, 409)
        assert err["error_id"] == "ERR_COURIER_ZONE_MISMATCH"
        assert err["error_id"] != "ERR_DISPATCH_WINDOW_CONFLICT"

    def test_zone_mismatch_alone_rejected(self, api):
        """PRD §3.5: "The chosen courier must actually serve the report's filing
        station — the report's `station_id` must appear in the courier's
        `serves_station_ids` — failing which the request is rejected with
        `ERR_COURIER_ZONE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_zone_referential_beats_window_temporal
        """
        set_clock(CLOCK_EPOCH)
        stn_jfk = get_success_data(api.create_station(
            create_station_payload(station_code="JFK", name="New York JFK",
                                   bags_handled_total=1000000), ADMIN))
        stn_lax = get_success_data(api.create_station(
            create_station_payload(station_code="LAX", name="Los Angeles",
                                   bags_handled_total=800000), ADMIN))
        carrier = create_carrier()
        courier = create_courier_service([stn_lax["id"]])
        passenger = create_passenger()
        bag = create_bag_tag(passenger["id"], [carrier["id"]])
        rpt = create_report(passenger["id"], bag["id"], stn_jfk["id"],
                            report_type="DELAYED")
        get_success_data(api.record_tracing_event(
            rpt["id"],
            create_tracing_event_payload(carrier["id"], stn_jfk["id"], "LOCATED"),
            AGENT))
        # No other dispatch on the courier: only the zone rule can fire.
        resp = api.create_dispatch(
            create_dispatch_payload(rpt["id"], courier["id"],
                                    pickup_at="2026-08-02T10:00:00Z"), AGENT)
        validate_error(resp, ApiErrorId.ERR_COURIER_ZONE_MISMATCH, 409)


class TestImmediateConsistency:

    def test_create_response_reflects_computed_state(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.3: "Creation also fixes the report's liability posture, computed once
        and stored."
        PRD §3.3: "A `DELAYED` report moves from `OPEN` to `TRACING`"

        Design: Corner/consistency_model/create_response_reflects_computed_state_immediately
        """
        set_clock(CLOCK_EPOCH)
        station = create_station()
        carrier = create_carrier()
        passenger = create_passenger()
        bag = create_bag_tag(passenger["id"], [carrier["id"]], weight_kg=20)
        resp = api.create_report(
            create_report_payload(passenger["id"], bag["id"], station["id"],
                                  type="DELAYED"), AGENT)
        data = validate_success(resp, 201)
        assert data["status"] == "TRACING"
        assert data["effective_cap_cents"] == 50000
        assert data["liability_regime"] == "DOMESTIC"
        assert data["version"] == 1


class TestStationSummary:

    def test_summary_after_full_lifecycle_closure(self, api):
        """PRD §3.9: "For the addressed station the summary reports its
        `station_id`, the live `open_report_count` of reports filed there that have
        not reached `CLOSED`, the `mishandled_report_count` of closed reports whose
        root cause was attributed to the station, and the `recovered_bag_count` of
        `LOCATED` tracing events recorded at the station. A `by_root_cause`
        breakdown groups those closed, attributed reports by their `root_cause`,
        omitting any cause whose count is zero. The headline figure,
        `mishandled_rate_per_1000`, is zero when the station's `bags_handled_total`
        is zero, and is otherwise one thousand times the `mishandled_report_count`
        divided by `bags_handled_total`, rounded half up to exactly two decimal
        places."

        Design: Corner/endpoints/station_summary_computed_read
        """
        ctx = setup_closed_report(contents_loss_cents=100000, is_international=True,
                                  root_cause="MISCONNECT", bags_handled_total=100000)
        assert ctx["report"]["status"] == "CLOSED"
        resp = api.get_station_irregularity_summary(ctx["station"]["id"], ADJUSTER)
        summary = validate_success(resp, 200)
        assert summary["open_report_count"] == 0
        assert summary["mishandled_report_count"] == 1
        assert summary["by_root_cause"] == {"MISCONNECT": 1}
        assert summary["recovered_bag_count"] == 0
        # 1000 * 1 / 100000 = 0.01 (rounded half up to exactly two decimals).
        assert summary["mishandled_rate_per_1000"] == 0.01


class TestTracingEventListing:

    def test_events_reverse_reachable_by_report(self, api):
        """PRD §3.4: "a `BaggageServiceAgent` records each WorldTracer message
        against the report as a **Tracing Event**"
        PRD §2.3: "Unless otherwise specified, all list endpoints return resources
        sorted by their creation timestamp in ascending order."
        PRD §4: GET /baggage/tracing-events lists tracing events with filters.

        Design: Corner/endpoints/tracing_events_reverse_reachable_by_report
        """
        set_clock(CLOCK_EPOCH)
        station = create_station()
        carrier = create_carrier()
        passenger = create_passenger()
        bag_a = create_bag_tag(passenger["id"], [carrier["id"]])
        bag_b = create_bag_tag(passenger["id"], [carrier["id"]])
        rpt_a = create_report(passenger["id"], bag_a["id"], station["id"],
                              report_type="DELAYED")
        rpt_b = create_report(passenger["id"], bag_b["id"], station["id"],
                              report_type="DELAYED")
        get_success_data(api.record_tracing_event(
            rpt_a["id"],
            create_tracing_event_payload(carrier["id"], station["id"], "FORWARDED"),
            AGENT))
        # Advance the logical clock so the second event's created_at is strictly
        # later: §2.3 pins ascending created_at order but is silent on ties.
        set_clock("2026-08-01T00:00:01Z")
        get_success_data(api.record_tracing_event(
            rpt_a["id"],
            create_tracing_event_payload(carrier["id"], station["id"], "LOCATED"),
            AGENT))
        get_success_data(api.record_tracing_event(
            rpt_b["id"],
            create_tracing_event_payload(carrier["id"], station["id"], "FORWARDED"),
            AGENT))

        events, meta = validate_paginated(
            api.list_tracing_events(AGENT, params={"report_id": rpt_a["id"]}))
        assert len(events) == 2
        assert all(e["report_id"] == rpt_a["id"] for e in events)
        assert [e["event_type"] for e in events] == ["FORWARDED", "LOCATED"]
