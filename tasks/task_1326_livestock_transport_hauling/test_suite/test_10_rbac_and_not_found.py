"""Role authorization (PRD §2.1, §4) and not-found errors (PRD §2.7 layer 5).

Every denial asserts the PRD's specific error id; the authorized counterparty
cases confirm the operation succeeds for a permitted role.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_load_payload,
    create_trailer_payload,
    create_washout_payload,
    make_compliance_headers,
    make_driver_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId as E
from test_helpers.fixtures import (
    create_driver,
    create_load,
    create_shipper,
    create_trailer,
    get_settlement_of_load,
    get_trailer,
    set_clock,
    setup_in_transit_load,
)

ADMIN = TEST_USERS["admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CO1 = make_compliance_headers("co-1")
CO2 = make_compliance_headers("co-2")
CONSIGNEE = TEST_USERS["consignee_headers"]
WASHOUT = TEST_USERS["washout_headers"]


class TestRoleDenials:
    def test_dispatcher_cannot_create_trailer_forbidden(self, api):
        """PRD §2.1: "When the declared role is not permitted to invoke an
        endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/dispatcher_cannot_create_trailer_forbidden
        """
        resp = api.create_trailer(create_trailer_payload(), DISP)
        validate_error(resp, E.ERR_FORBIDDEN_ROLE)
        data, meta = validate_paginated(api.list_trailers(ADMIN))
        assert len(data) == 0

    def test_driver_cannot_finalize_plan_forbidden(self, api):
        """PRD §2.1: "When the declared role is not permitted to invoke an
        endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/driver_cannot_finalize_plan_forbidden
        """
        shipper = create_shipper()
        tt = create_trailer()
        load = create_load(shipper["id"], declared_head_count=10,
                           declared_weight_lb=10000, planned_duration_hours=5,
                           loaded_miles=100)
        validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": tt["compartments"][0]["id"],
                 "head_count": 10, "avg_weight_lb": 1000,
                 "expected_load_version": load["version"]},
                DISP), 201)
        driver = create_driver()
        resp = api.finalize_plan(load["id"], make_driver_headers(driver["id"]))
        validate_error(resp, E.ERR_FORBIDDEN_ROLE)
        load_after = validate_success(api.get_load(load["id"], ADMIN))
        assert load_after["status"] == "DRAFT"

    def test_consignee_cannot_create_load_forbidden(self, api):
        """PRD §2.1: "When the declared role is not permitted to invoke an
        endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/consignee_cannot_create_load_forbidden
        """
        shipper = create_shipper()
        resp = api.create_load(
            create_load_payload(shipper_id=shipper["id"]), CONSIGNEE)
        validate_error(resp, E.ERR_FORBIDDEN_ROLE)

    def test_compliance_officer_cannot_pay_settlement_forbidden(self, api):
        """PRD §2.1: "When the declared role is not permitted to invoke an
        endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §3.8: "Payment is the `CarrierAdmin`'s act and moves a settlement
        to `PAID`."

        Design: Corner/rbac/compliance_officer_cannot_pay_settlement_forbidden
        """
        ctx = setup_in_transit_load()
        settlement = get_settlement_of_load(ctx["load"]["id"])
        resp = api.pay_settlement(settlement["id"], CO2)
        validate_error(resp, E.ERR_FORBIDDEN_ROLE)

    def test_dispatcher_cannot_record_washout_forbidden(self, api):
        """PRD §2.1: "When the declared role is not permitted to invoke an
        endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/dispatcher_cannot_record_washout_forbidden
        """
        set_clock("2026-08-01T01:00:00Z")
        tt = create_trailer()
        resp = api.create_washout(
            tt["trailer"]["id"],
            create_washout_payload(washed_at="2026-08-01T00:30:00Z",
                                   method="STEAM"),
            DISP)
        validate_error(resp, E.ERR_FORBIDDEN_ROLE)
        assert get_trailer(tt["trailer"]["id"])["washout_status"] == "DIRTY"


class TestRoleAllowed:
    def test_washout_operator_records_washout(self, api):
        """PRD §3.2: "A `WashoutOperator` or `CarrierAdmin` records a wash with
        its `washed_at` completion timestamp — which must not be later than the
        current logical time, or the record is rejected with
        `ERR_EVENT_IN_FUTURE` — a `method` of `HIGH_PRESSURE`, `STEAM`, or
        `CHEMICAL`, and an optional `operator_note`. Recording a wash sets the
        trailer's `last_washed_at` to `washed_at`, clears `dirtied_at` to null,
        sets `washout_valid_until` to `washed_at` plus 96 hours, and recomputes
        `washout_status`."

        Design: Corner/rbac/washout_operator_records_washout
        """
        from test_helpers import assert_ts_eq
        set_clock("2026-08-01T01:00:00Z")
        tt = create_trailer()
        assert get_trailer(tt["trailer"]["id"])["washout_status"] == "DIRTY"

        validate_success(
            api.create_washout(
                tt["trailer"]["id"],
                create_washout_payload(washed_at="2026-08-01T00:30:00Z",
                                       method="CHEMICAL"),
                WASHOUT), 201)
        trailer = get_trailer(tt["trailer"]["id"])
        assert trailer["washout_status"] == "CLEAN"
        assert_ts_eq(trailer["washout_valid_until"], "2026-08-05T00:30:00Z",
                     "washout_valid_until")

    def test_any_role_can_list_loads(self, api):
        """PRD §2.1: "The recognized roles are `CarrierAdmin`, `Dispatcher`,
        `ComplianceOfficer`, `Driver`, `ConsigneeAgent`, and `WashoutOperator`;
        the wildcard `Any` used elsewhere in this document means any
        authenticated role."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/rbac/any_role_can_list_loads
        """
        shipper = create_shipper()
        create_load(shipper["id"])
        for headers in (ADMIN, DISP, CO1, WASHOUT, CONSIGNEE,
                        make_driver_headers("some-driver")):
            data, meta = validate_paginated(api.list_loads(headers))
            assert meta["total_count"] == 1
            assert isinstance(data, list)

    def test_driver_logs_own_duty_event_but_not_anothers(self, api):
        """PRD §2.1: "Ownership rule for the `Driver` role: a driver may append
        duty events only to their own record (the path driver id must equal
        `X-User-ID`), and may perform depart, arrive, rest-unload,
        resume-transit, weather-hold placement and release, and welfare-incident
        reporting only on a load whose `driver_id` equals `X-User-ID`. Any
        violation is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/driver_logs_own_duty_event_but_not_anothers
        """
        set_clock("2026-08-02T12:00:00Z")
        d1 = create_driver()
        d2 = create_driver()

        # own record: allowed
        validate_success(
            api.create_duty_event(
                d1["id"],
                {"event_type": "DUTY_ON",
                 "occurred_at": "2026-08-02T06:00:00Z"},
                make_driver_headers(d1["id"])), 201)

        # another driver's record: ownership violation
        resp = api.create_duty_event(
            d2["id"],
            {"event_type": "DUTY_ON", "occurred_at": "2026-08-02T06:00:00Z"},
            make_driver_headers(d1["id"]))
        validate_error(resp, E.ERR_OWNERSHIP_MISMATCH)


class TestNotFound:
    def test_washout_on_missing_trailer_not_found(self, api):
        """PRD §2.7: "Identifiers in the URL path are validated left to right;
        the first identifier that does not resolve rejects the request with that
        resource's specific not-found error (HTTP 404): `ERR_SHIPPER_NOT_FOUND`,
        `ERR_DRIVER_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
        `ERR_COMPARTMENT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_HEALTH_PAPER_NOT_FOUND`,
        `ERR_BRAND_INSPECTION_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOLD_NOT_FOUND`."

        Design: Corner/errors/washout_on_missing_trailer_not_found
        """
        resp = api.create_washout(
            NON_EXISTENT_UUID,
            create_washout_payload(washed_at="2026-08-01T00:00:00Z",
                                   method="STEAM"),
            WASHOUT)
        validate_error(resp, E.ERR_TRAILER_NOT_FOUND)

    def test_duty_event_on_missing_driver_not_found(self, api):
        """PRD §2.7: "Identifiers in the URL path are validated left to right;
        the first identifier that does not resolve rejects the request with that
        resource's specific not-found error (HTTP 404): `ERR_SHIPPER_NOT_FOUND`,
        `ERR_DRIVER_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
        `ERR_COMPARTMENT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_HEALTH_PAPER_NOT_FOUND`,
        `ERR_BRAND_INSPECTION_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOLD_NOT_FOUND`."

        Design: Corner/errors/duty_event_on_missing_driver_not_found
        """
        resp = api.create_duty_event(
            NON_EXISTENT_UUID,
            {"event_type": "DUTY_ON", "occurred_at": "2026-08-01T00:00:00Z"},
            ADMIN)
        validate_error(resp, E.ERR_DRIVER_NOT_FOUND)

    def test_release_missing_hold_not_found(self, api):
        """PRD §2.7: "Identifiers in the URL path are validated left to right;
        the first identifier that does not resolve rejects the request with that
        resource's specific not-found error (HTTP 404): `ERR_SHIPPER_NOT_FOUND`,
        `ERR_DRIVER_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
        `ERR_COMPARTMENT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_HEALTH_PAPER_NOT_FOUND`,
        `ERR_BRAND_INSPECTION_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOLD_NOT_FOUND`."

        Design: Corner/errors/release_missing_hold_not_found
        """
        resp = api.release_weather_hold(NON_EXISTENT_UUID, DISP)
        validate_error(resp, E.ERR_HOLD_NOT_FOUND)

    def test_verify_missing_health_paper_not_found(self, api):
        """PRD §2.7: "Identifiers in the URL path are validated left to right;
        the first identifier that does not resolve rejects the request with that
        resource's specific not-found error (HTTP 404): `ERR_SHIPPER_NOT_FOUND`,
        `ERR_DRIVER_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
        `ERR_COMPARTMENT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_HEALTH_PAPER_NOT_FOUND`,
        `ERR_BRAND_INSPECTION_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOLD_NOT_FOUND`."

        Design: Corner/errors/verify_missing_health_paper_not_found
        """
        resp = api.verify_health_paper(NON_EXISTENT_UUID, CO2)
        validate_error(resp, E.ERR_HEALTH_PAPER_NOT_FOUND)

    def test_verify_missing_brand_inspection_not_found(self, api):
        """PRD §2.7: "Identifiers in the URL path are validated left to right;
        the first identifier that does not resolve rejects the request with that
        resource's specific not-found error (HTTP 404): `ERR_SHIPPER_NOT_FOUND`,
        `ERR_DRIVER_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
        `ERR_COMPARTMENT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_HEALTH_PAPER_NOT_FOUND`,
        `ERR_BRAND_INSPECTION_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOLD_NOT_FOUND`."

        Design: Corner/errors/verify_missing_brand_inspection_not_found
        """
        resp = api.verify_brand_inspection(NON_EXISTENT_UUID, CO2)
        validate_error(resp, E.ERR_BRAND_INSPECTION_NOT_FOUND)

    def test_release_missing_allocation_not_found(self, api):
        """PRD §2.7: "Identifiers in the URL path are validated left to right;
        the first identifier that does not resolve rejects the request with that
        resource's specific not-found error (HTTP 404): `ERR_SHIPPER_NOT_FOUND`,
        `ERR_DRIVER_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
        `ERR_COMPARTMENT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_HEALTH_PAPER_NOT_FOUND`,
        `ERR_BRAND_INSPECTION_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOLD_NOT_FOUND`. A nested request
        therefore fails on the parent before the child is ever consulted."

        Design: Corner/errors/release_missing_allocation_not_found
        """
        shipper = create_shipper()
        load = create_load(shipper["id"])
        resp = api.release_allocation(
            NON_EXISTENT_UUID,
            {"expected_load_version": load["version"]},
            DISP)
        validate_error(resp, E.ERR_ALLOCATION_NOT_FOUND)

    def test_pay_missing_settlement_not_found(self, api):
        """PRD §2.7: "Identifiers in the URL path are validated left to right;
        the first identifier that does not resolve rejects the request with that
        resource's specific not-found error (HTTP 404): `ERR_SHIPPER_NOT_FOUND`,
        `ERR_DRIVER_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
        `ERR_COMPARTMENT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_HEALTH_PAPER_NOT_FOUND`,
        `ERR_BRAND_INSPECTION_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOLD_NOT_FOUND`."

        Design: Corner/errors/pay_missing_settlement_not_found
        """
        resp = api.pay_settlement(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, E.ERR_SETTLEMENT_NOT_FOUND)

    def test_close_missing_incident_not_found(self, api):
        """PRD §2.7: "Identifiers in the URL path are validated left to right;
        the first identifier that does not resolve rejects the request with that
        resource's specific not-found error (HTTP 404): `ERR_SHIPPER_NOT_FOUND`,
        `ERR_DRIVER_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
        `ERR_COMPARTMENT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_HEALTH_PAPER_NOT_FOUND`,
        `ERR_BRAND_INSPECTION_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOLD_NOT_FOUND`."

        Design: Corner/errors/close_missing_incident_not_found
        """
        resp = api.close_incident(NON_EXISTENT_UUID, {}, CO2)
        validate_error(resp, E.ERR_INCIDENT_NOT_FOUND)

    def test_create_load_backhaul_target_not_found(self, api):
        """PRD §3.3: "The referenced shipper must exist
        (`ERR_SHIPPER_NOT_FOUND`), as must the backhaul target
        (`ERR_LOAD_NOT_FOUND`)."

        Design: Corner/errors/create_load_backhaul_target_not_found
        """
        shipper = create_shipper()
        resp = api.create_load(
            create_load_payload(shipper_id=shipper["id"],
                                backhaul_of_load_id=NON_EXISTENT_UUID),
            DISP)
        validate_error(resp, E.ERR_LOAD_NOT_FOUND)
