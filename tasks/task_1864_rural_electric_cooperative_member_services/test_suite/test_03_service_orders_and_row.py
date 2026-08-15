"""Service orders, aid-to-construction, right-of-way workflows (PRD §3.2, §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_row_agreement_payload,
    create_service_order_payload,
    get_success_data,
    make_member_headers,
    setup_cooperative,
    setup_energized_location,
    setup_member,
    validate_error,
    validate_paginated,
    validate_success,
)

REP = TEST_USERS["rep"]
FIELD = TEST_USERS["field_ops"]
LEGAL = TEST_USERS["legal_counsel"]


def _api():
    from test_helpers import api_client
    return api_client


class TestAidToConstruction:
    def test_atc_multifactor_overhead_threshold(self, api):
        """PRD §3.2: "the base cost is 1,200 cents per foot of `distance_ft`,
        plus a flat 150,000-cent charge when a road bore is required" and "The
        cooperative grants the first 250 feet free — an allowance of 250 times
        the per-foot rate, 300,000 cents, is subtracted from the base, and the
        contribution is the excess, never below zero. When that excess exceeds
        200,000 cents, a nonlinear overhead of ten percent of the portion above
        200,000 cents is added."

        Design: Difficulty/combinatorial_formula/atc_multifactor_overhead_threshold
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        order = get_success_data(api.create_service_order(
            create_service_order_payload(
                service_location_id=location["id"],
                distance_ft=400, requires_road_bore=True),
            REP), 201)
        estimated = validate_success(api.estimate_service_order(order["id"], FIELD), 200)
        # base = 400*1200 + 150000 = 630000; excess over 300000 allowance = 330000;
        # overhead = 10% of (330000 - 200000) = 13000; total = 343000.
        assert estimated["aid_to_construction_cents"] == 343000

    def test_atc_temporary_floor_and_free_allowance(self, api):
        """PRD §3.2: "for a `TEMPORARY` order the base is raised to a floor of
        50,000 cents if it would otherwise fall below that. The cooperative
        grants the first 250 feet free — an allowance of 250 times the per-foot
        rate, 300,000 cents, is subtracted from the base, and the contribution
        is the excess, never below zero."

        Design: Difficulty/combinatorial_formula/atc_multifactor_overhead_threshold
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        # TEMPORARY at 100 ft: base would be 120000, floored at 50000; still
        # below the 300000 allowance, so the contribution is zero.
        order = get_success_data(api.create_service_order(
            create_service_order_payload(
                service_location_id=location["id"], order_type="TEMPORARY",
                distance_ft=100, requires_road_bore=False),
            REP), 201)
        estimated = validate_success(api.estimate_service_order(order["id"], FIELD), 200)
        assert estimated["aid_to_construction_cents"] == 0

    def test_invoice_atc_zero_rejected(self, api):
        """PRD §3.2: "An order with a positive `aid_to_construction_cents` is
        invoiced to the member, moving `ESTIMATED → ATC_INVOICED`; attempting
        that step on a zero-contribution order is rejected with
        `ERR_ATC_ZERO_NOT_INVOICABLE`."

        Design: Corner/state_machines/invoice_atc_zero_rejected
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        order = get_success_data(api.create_service_order(
            create_service_order_payload(
                service_location_id=location["id"], distance_ft=100,
                requires_road_bore=False),
            REP), 201)
        estimated = validate_success(api.estimate_service_order(order["id"], FIELD), 200)
        # 100 ft * 1200 = 120000 < 300000 free allowance -> zero contribution
        assert estimated["aid_to_construction_cents"] == 0
        resp = api.invoice_atc(order["id"], REP)
        validate_error(resp, ApiErrorId.ERR_ATC_ZERO_NOT_INVOICABLE)


class TestEnergizeAndScheduleGates:
    def test_energize_requires_row_recorded(self, api):
        """PRD §3.2: "Energizing from `PENDING_CONSTRUCTION` requires both a
        `ServiceOrder` for the location in `CONSTRUCTED` status
        (`ERR_SERVICE_NOT_CONSTRUCTED` otherwise) and a right-of-way agreement
        in `RECORDED` status (`ERR_ROW_NOT_RECORDED` otherwise)" and §3.3:
        "scheduling construction accepts either `RECORDED` or `CONDEMNATION` as
        sufficient land rights, while energizing a new location insists on
        `RECORDED`."

        Design: Difficulty/cross_entity_state_dependency/energize_requires_row_recorded
        """
        setup_cooperative()
        # Control location: ROW via consent + record.
        member, loc1, order1, row1 = setup_energized_location(address="1")
        assert loc1["status"] == "ENERGIZED"
        # Second location: ROW driven to CONDEMNATION — good enough to schedule
        # construction, but not to energize.
        loc2 = get_success_data(api.create_service_location(
            {"member_id": member["id"], "address": "2", "rate_class": "RESIDENTIAL"}, REP), 201)
        order2 = get_success_data(api.create_service_order(
            create_service_order_payload(
                service_location_id=loc2["id"], distance_ft=100, requires_road_bore=False),
            REP), 201)
        order2 = get_success_data(api.estimate_service_order(order2["id"], FIELD), 200)
        row2 = get_success_data(api.create_row_agreement(
            create_row_agreement_payload(service_location_id=loc2["id"]), FIELD), 201)
        member_headers = make_member_headers(member["id"])
        row2 = get_success_data(api.contest_row(row2["id"], member_headers), 200)
        row2 = get_success_data(api.condemn_row(row2["id"], LEGAL), 200)
        assert row2["status"] == "CONDEMNATION"
        order2 = get_success_data(api.mark_order_paid(order2["id"], REP), 200)
        order2 = get_success_data(api.schedule_service_order(order2["id"], FIELD), 200)
        order2 = get_success_data(api.construct_service_order(order2["id"], FIELD), 200)
        assert order2["status"] == "CONSTRUCTED"
        resp = api.energize_location(loc2["id"], FIELD)
        validate_error(resp, ApiErrorId.ERR_ROW_NOT_RECORDED)

    def test_energize_with_recorded_row_succeeds_and_completes_order(self, api):
        """PRD §3.2: "Energizing from `PENDING_CONSTRUCTION` requires both a
        `ServiceOrder` for the location in `CONSTRUCTED` status ... and a
        right-of-way agreement in `RECORDED` status ...; success stamps
        `energized_at` and completes the order as described above" — "The
        order's final step is not taken on the order itself — energizing the
        service location cascades the order from `CONSTRUCTED` to `ENERGIZED`."

        Design: Difficulty/cross_entity_state_dependency/energize_requires_row_recorded
        """
        setup_cooperative()
        member, location, order, row = setup_energized_location(address="1")
        assert location["status"] == "ENERGIZED"
        assert location.get("energized_at")
        assert row["status"] == "RECORDED"
        order_after = get_success_data(api.get_service_order(order["id"], FIELD), 200)
        assert order_after["status"] == "ENERGIZED"

    def test_energize_without_constructed_order_rejected(self, api):
        """PRD §3.2: "Energizing from `PENDING_CONSTRUCTION` requires both a
        `ServiceOrder` for the location in `CONSTRUCTED` status
        (`ERR_SERVICE_NOT_CONSTRUCTED` otherwise)".

        Design: Corner/state_machines/energize_without_constructed_order_rejected
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        order = get_success_data(api.create_service_order(
            create_service_order_payload(
                service_location_id=location["id"], distance_ft=100,
                requires_road_bore=False),
            REP), 201)
        order = get_success_data(api.estimate_service_order(order["id"], FIELD), 200)
        row = get_success_data(api.create_row_agreement(
            create_row_agreement_payload(service_location_id=location["id"]), FIELD), 201)
        row = get_success_data(api.consent_row(row["id"], make_member_headers(member["id"])), 200)
        row = get_success_data(api.record_row(row["id"], FIELD), 200)
        assert row["status"] == "RECORDED"
        # Order is only ESTIMATED — not CONSTRUCTED.
        resp = api.energize_location(location["id"], FIELD)
        validate_error(resp, ApiErrorId.ERR_SERVICE_NOT_CONSTRUCTED)

    def test_schedule_requires_recorded_row(self, api):
        """PRD §3.2: "Scheduling construction (`PAID → SCHEDULED`) is gated on
        land rights: the location's right-of-way agreement must be `RECORDED` or
        in `CONDEMNATION`, else `ERR_ROW_NOT_RECORDED`."

        Design: Corner/state_machines/schedule_requires_recorded_row
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        order = get_success_data(api.create_service_order(
            create_service_order_payload(
                service_location_id=location["id"], distance_ft=100,
                requires_road_bore=False),
            REP), 201)
        order = get_success_data(api.estimate_service_order(order["id"], FIELD), 200)
        row = get_success_data(api.create_row_agreement(
            create_row_agreement_payload(service_location_id=location["id"]), FIELD), 201)
        row = get_success_data(api.consent_row(row["id"], make_member_headers(member["id"])), 200)
        assert row["status"] == "MEMBER_CONSENTED"
        order = get_success_data(api.mark_order_paid(order["id"], REP), 200)
        resp = api.schedule_service_order(order["id"], FIELD)
        validate_error(resp, ApiErrorId.ERR_ROW_NOT_RECORDED)


class TestRightOfWayCycle:
    def test_row_contest_consent_record_cycle(self, api):
        """PRD §3.3: "A contested easement is not a dead end: the member may
        later consent after all (`CONTESTED → MEMBER_CONSENTED`, again stamping
        `consented_at`)" and "`RECORDED`, `CONDEMNATION`, and `RELEASED` are
        terminal."

        Design: Difficulty/non_linear_state_machine/right_of_way_contest_consent_cycle
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        row = get_success_data(api.create_row_agreement(
            create_row_agreement_payload(service_location_id=location["id"]), FIELD), 201)
        member_headers = make_member_headers(member["id"])
        row = get_success_data(api.contest_row(row["id"], member_headers), 200)
        assert row["status"] == "CONTESTED"
        row = get_success_data(api.consent_row(row["id"], member_headers), 200)
        assert row["status"] == "MEMBER_CONSENTED"
        row = get_success_data(api.record_row(row["id"], FIELD), 200)
        assert row["status"] == "RECORDED"
        # RECORDED is terminal: a further consent is not a legitimate from-state.
        resp = api.consent_row(row["id"], member_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_row_contest_stamps_and_allows_reconsent(self, api):
        """PRD §3.3: "Alternatively the owning member may contest the request,
        moving `REQUESTED → CONTESTED`." and "the member may later consent after
        all (`CONTESTED → MEMBER_CONSENTED`, again stamping `consented_at`)".

        Design: Difficulty/non_linear_state_machine/right_of_way_contest_consent_cycle
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        row = get_success_data(api.create_row_agreement(
            create_row_agreement_payload(service_location_id=location["id"]), FIELD), 201)
        member_headers = make_member_headers(member["id"])
        contested = get_success_data(api.contest_row(row["id"], member_headers), 200)
        assert contested["status"] == "CONTESTED"
        consented = get_success_data(api.consent_row(row["id"], member_headers), 200)
        assert consented["status"] == "MEMBER_CONSENTED"
        assert consented.get("consented_at")


class TestMemberLocationSubresource:
    def test_get_member_service_locations_reverse_reachability(self, api):
        """PRD §4: "GET | `/coop/members/{id}/service-locations` | List member's
        service locations".

        Design: Corner/endpoints/get_member_service_locations_reverse_reachability
        """
        setup_cooperative()
        member_a = get_success_data(api.create_member(
            {"legal_name": "A", "member_type": "RESIDENTIAL", "district_id": 1}, REP), 201)
        member_b = get_success_data(api.create_member(
            {"legal_name": "B", "member_type": "RESIDENTIAL", "district_id": 2}, REP), 201)
        get_success_data(api.create_service_location(
            {"member_id": member_a["id"], "address": "1", "rate_class": "RESIDENTIAL"}, REP), 201)
        get_success_data(api.create_service_location(
            {"member_id": member_a["id"], "address": "2", "rate_class": "SEASONAL"}, REP), 201)
        get_success_data(api.create_service_location(
            {"member_id": member_b["id"], "address": "3", "rate_class": "RESIDENTIAL"}, REP), 201)
        data = validate_success(api.list_member_service_locations(member_a["id"], REP), 200)
        assert len(data) == 2
        assert all(loc["member_id"] == member_a["id"] for loc in data)
