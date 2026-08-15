"""Entity intake: shippers, drivers, trailers, loads, tickets, allocations.

Covers PRD §2.1 (identity headers), §2.2 (envelopes), §2.4 (server-managed
identity fields), §2.7 (body-shape layer), §3.1 (shipper/driver creation),
§3.2 (trailer/compartment/washout creation), §3.3 (load intake, allocation
rounding), §3.4 (health-paper body shape), §3.6 (scale-ticket shape).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_health_paper_payload,
    create_load_payload,
    create_shipper_payload,
    create_trailer_payload,
    create_washout_payload,
    create_weight_ticket_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId as E
from test_helpers.fixtures import (
    create_load,
    create_shipper,
    create_trailer,
    set_clock,
)


class TestShippers:
    def test_shipper_create_applies_default_shrink_pct(self, api, admin_headers):
        """PRD §3.1: "An optional `default_shrink_allowance_pct` establishes the
        shipper's standard shrink allowance; when omitted it defaults to 2.0
        percent and applies to every load of that shipper that does not carry
        its own override."
        PRD §2.4: "`version` (integer): a system-managed counter that increments
        by exactly 1 on every mutation of the resource, including mutations
        caused by cross-entity cascades."

        Design: Corner/entities/shipper_create_applies_default_shrink_pct
        """
        shipper = validate_success(
            api.create_shipper(create_shipper_payload(), admin_headers), 201)
        assert shipper["default_shrink_allowance_pct"] == 2.0
        assert shipper["version"] == 1
        assert shipper["created_at"] is not None

        fetched = validate_success(api.get_shipper(shipper["id"], admin_headers))
        assert fetched["default_shrink_allowance_pct"] == 2.0
        assert fetched["version"] == 1
        assert fetched["created_at"] == shipper["created_at"]

    def test_shipper_create_missing_name_returns_invalid_request(
            self, api, admin_headers):
        """PRD §2.7: "Required fields are present, types and enum values are
        valid, numeric inputs are positive, and on a health certificate
        `expires_at` is strictly later than `issued_at` — otherwise
        `ERR_INVALID_REQUEST` (HTTP 400), or `ERR_INVALID_TIME_RANGE` (HTTP 400)
        for the certificate time-range case."

        Design: Corner/entities/shipper_create_missing_name_returns_invalid_request
        """
        resp = api.create_shipper({}, admin_headers)
        validate_error(resp, E.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api.list_shippers(admin_headers))
        assert len(data) == 0
        assert meta["total_count"] == 0

    def test_shipper_create_client_supplied_id_input_ignored(
            self, api, admin_headers):
        """PRD §2.4: "`id` (string): a server-minted UUID with no type prefix."
        PRD §2.4: "`version` (integer): a system-managed counter that increments
        by exactly 1 on every mutation of the resource, including mutations
        caused by cross-entity cascades."

        Design: Corner/entities/shipper_create_client_supplied_id_input_ignored
        """
        shipper = validate_success(
            api.create_shipper(
                {"id": "client-1", "version": 99, "name": "Ranchco",
                 "contact_email": "r@x.com"},
                admin_headers), 201)
        assert shipper["id"] != "client-1", (
            "Server must mint its own UUID, ignoring client-supplied id")
        assert shipper["version"] == 1


class TestDrivers:
    def test_driver_create_duplicate_license_rejected(self, api, admin_headers):
        """PRD §3.1: "The license number is unique across drivers: a duplicate
        submission is rejected with `ERR_DUPLICATE_LICENSE_NO` (HTTP 409), a
        check that runs after the request body's shape has been validated."

        Design: Corner/entities/driver_create_duplicate_license_rejected
        """
        validate_success(
            api.create_driver({"name": "Ann", "license_no": "CDL-X1"},
                              admin_headers), 201)
        resp = api.create_driver({"name": "Bob", "license_no": "CDL-X1"},
                                 admin_headers)
        validate_error(resp, E.ERR_DUPLICATE_LICENSE_NO)


class TestTrailers:
    def test_trailer_create_initializes_dirty_with_compartments(
            self, api, admin_headers):
        """PRD §3.2: "A brand-new trailer has never been washed and therefore
        starts `DIRTY`: it must be washed before its first load can depart."
        PRD §3.2: "A `CarrierAdmin` creates a trailer by supplying its fleet
        `trailer_no` — unique across the fleet — its `max_gross_weight_lb` (the
        GVWR that no single load's allocated weight may exceed), and a
        `compartments` array that atomically creates the trailer's compartments
        in the same request."
        PRD §3.2: "A trailer's compartment listing is ordered by
        `compartment_index` ascending, and the trailer list can be filtered by
        `washout_status`."

        Design: Corner/entities/trailer_create_initializes_dirty_with_compartments
        """
        trailer = validate_success(
            api.create_trailer(
                {"trailer_no": "T-C1", "max_gross_weight_lb": 50000,
                 "compartments": [
                     {"compartment_index": 2, "max_head_count": 10,
                      "max_weight_lb": 20000},
                     {"compartment_index": 1, "max_head_count": 20,
                      "max_weight_lb": 26000},
                 ]},
                admin_headers), 201)

        fetched = validate_success(api.get_trailer(trailer["id"], admin_headers))
        assert fetched["washout_status"] == "DIRTY"
        assert fetched["last_washed_at"] is None
        assert fetched["washout_valid_until"] is None

        comps, meta = validate_paginated(
            api.list_compartments(trailer["id"], admin_headers))
        assert len(comps) == 2
        assert comps[0]["compartment_index"] == 1
        assert comps[0]["max_head_count"] == 20
        for comp in comps:
            assert comp["occupied_head_count"] == 0
            assert comp["occupied_weight_lb"] == 0

    def test_washout_event_is_append_only_without_version(
            self, api, admin_headers):
        """PRD §2.4: "Three record types are immutable once written and therefore
        carry only `id` and `created_at` — both `updated_at` and `version` are
        absent from them: a `DriverDutyEvent`, a `WashoutEvent`, and a
        `WeightTicket`."

        Design: Corner/entities/washout_event_is_append_only_without_version
        """
        set_clock("2026-08-01T01:00:00Z")
        trailer = validate_success(
            api.create_trailer(create_trailer_payload(), admin_headers), 201)
        wash = validate_success(
            api.create_washout(
                trailer["id"],
                create_washout_payload(washed_at="2026-08-01T00:30:00Z",
                                       method="STEAM"),
                TEST_USERS["washout_headers"]), 201)
        assert "version" not in wash
        assert "updated_at" not in wash
        assert wash["id"]
        assert wash["created_at"]

        washes, meta = validate_paginated(
            api.list_washouts(trailer["id"], admin_headers))
        assert len(washes) == 1
        assert washes[0]["method"] == "STEAM"
        assert "version" not in washes[0]


class TestLoads:
    def test_load_created_in_draft_initial_state(self, api):
        """PRD §3.3: "A new load starts in `DRAFT` with no `driver_id`, no
        `trailer_id`, and zero `allocated_head_count` and
        `allocated_weight_lb`; the actual timestamps `departed_at`,
        `arrived_at`, and `delivered_at`, and the clocks
        `confinement_anchor_at` and `rest_unload_started_at`, are all null
        until the road events of §3.5 and §3.6 set them."

        Design: Corner/state_machines/load_created_in_draft_initial_state
        """
        shipper = create_shipper()
        load = validate_success(
            api.create_load(create_load_payload(shipper_id=shipper["id"]),
                            TEST_USERS["dispatcher_headers"]), 201)
        assert load["status"] == "DRAFT"
        assert load["allocated_head_count"] == 0
        assert load["allocated_weight_lb"] == 0
        assert load["driver_id"] is None
        assert load["trailer_id"] is None
        assert load["is_backhaul"] is False

    def test_get_load_not_found_returns_error_envelope(self, api, admin_headers):
        """PRD §2.7: "Identifiers in the URL path are validated left to right;
        the first identifier that does not resolve rejects the request with that
        resource's specific not-found error (HTTP 404): `ERR_SHIPPER_NOT_FOUND`,
        `ERR_DRIVER_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
        `ERR_COMPARTMENT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_HEALTH_PAPER_NOT_FOUND`,
        `ERR_BRAND_INSPECTION_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOLD_NOT_FOUND`."
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" carrying `data.error_id`, `data.message`, and
        `meta.api_request_id`.

        Design: Corner/entities/get_load_not_found_returns_error_envelope
        """
        resp = api.get_load(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, E.ERR_LOAD_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"]) > 0
        assert isinstance(body["meta"]["api_request_id"], str)
        assert len(body["meta"]["api_request_id"]) > 0


class TestWeightTickets:
    def test_weight_ticket_net_weight_computed(self, api, consignee_headers):
        """PRD §3.6: "A `ConsigneeAgent` or a `Driver` records one against a
        load with `ticket_type` (`ORIGIN` or `DELIVERY`), `gross_lb`, `tare_lb`,
        and `weighed_at`; the ticket's `net_weight_lb` is `gross_lb` minus
        `tare_lb`."

        Design: Corner/entities/weight_ticket_net_weight_computed
        """
        shipper = create_shipper()
        load = create_load(shipper["id"])
        ticket = validate_success(
            api.create_weight_ticket(
                load["id"],
                create_weight_ticket_payload(ticket_type="ORIGIN",
                                             gross_lb=46000, tare_lb=6000,
                                             weighed_at="2026-08-01T00:00:00Z"),
                consignee_headers), 201)
        assert ticket["net_weight_lb"] == 40000

    def test_weight_ticket_gross_not_greater_than_tare_rejected(
            self, api, consignee_headers):
        """PRD §3.6: "After the state rule, `gross_lb` must be strictly greater
        than `tare_lb` (`ERR_INVALID_TICKET_WEIGHT`, HTTP 422; `tare_lb` itself
        may be zero), and `weighed_at` must not be later than the current
        logical time (`ERR_EVENT_IN_FUTURE`)."

        Design: Corner/entities/weight_ticket_gross_not_greater_than_tare_rejected
        """
        shipper = create_shipper()
        load = create_load(shipper["id"])
        resp = api.create_weight_ticket(
            load["id"],
            create_weight_ticket_payload(ticket_type="ORIGIN", gross_lb=6000,
                                         tare_lb=6000,
                                         weighed_at="2026-08-01T00:00:00Z"),
            consignee_headers)
        validate_error(resp, E.ERR_INVALID_TICKET_WEIGHT)


class TestAllocations:
    def test_allocation_weight_rounds_per_allocation(self, api):
        """PRD §3.3: "Each allocation's `weight_lb` is its `head_count`
        multiplied by `avg_weight_lb`, rounded half up to a whole pound — this
        per-allocation rounding is pinned before any summation."
        PRD §3.3: "The load's `allocated_head_count` and `allocated_weight_lb`
        are the sums of `head_count` and `weight_lb` over its `ACTIVE`
        allocations only; `RELEASED` rows are excluded."

        Design: Corner/entities/allocation_weight_rounds_per_allocation
        """
        shipper = create_shipper()
        tt = create_trailer(compartments=[
            {"compartment_index": 1, "max_head_count": 10,
             "max_weight_lb": 50000}])
        load = create_load(shipper["id"])
        alloc = validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": tt["compartments"][0]["id"],
                 "head_count": 3, "avg_weight_lb": 333.33,
                 "expected_load_version": load["version"]},
                TEST_USERS["dispatcher_headers"]), 201)
        # round_half_up(3 * 333.33) == round_half_up(999.99) == 1000
        assert alloc["weight_lb"] == 1000

        load_after = validate_success(
            api.get_load(load["id"], TEST_USERS["dispatcher_headers"]))
        assert load_after["allocated_weight_lb"] == 1000
        assert load_after["allocated_head_count"] == 3


class TestPaperworkBodyShape:
    def test_health_paper_expiry_before_issue_returns_invalid_time_range(
            self, api, co1_headers):
        """PRD §3.4: "A certificate whose `expires_at` is not strictly later
        than its `issued_at` is rejected with `ERR_INVALID_TIME_RANGE`
        (HTTP 400) at body validation."

        Design: Corner/validations/health_paper_expiry_before_issue_returns_invalid_time_range
        """
        shipper = create_shipper()
        load = create_load(shipper["id"])
        resp = api.create_health_paper(
            load["id"],
            create_health_paper_payload(issued_at="2026-08-01T00:00:00Z",
                                        expires_at="2026-07-30T00:00:00Z"),
            co1_headers)
        validate_error(resp, E.ERR_INVALID_TIME_RANGE)

    def test_create_load_invalid_enum_species_returns_invalid_request(
            self, api, dispatcher_headers):
        """PRD §2.7: "Required fields are present, types and enum values are
        valid, numeric inputs are positive, and on a health certificate
        `expires_at` is strictly later than `issued_at` — otherwise
        `ERR_INVALID_REQUEST` (HTTP 400), or `ERR_INVALID_TIME_RANGE` (HTTP 400)
        for the certificate time-range case."
        PRD §3.3: "the hauled `species` (exactly one of `CATTLE`, `SWINE`,
        `SHEEP`, or `HORSES` per load)"

        Design: Corner/validations/create_load_invalid_enum_species_returns_invalid_request
        """
        shipper = create_shipper()
        resp = api.create_load(
            create_load_payload(shipper_id=shipper["id"], species="ELK"),
            dispatcher_headers)
        validate_error(resp, E.ERR_INVALID_REQUEST)


class TestAuthAndFkExistence:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request in which either header is missing, or in which
        the role is not one of the recognized values, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.create_shipper({"name": "Ranchco", "contact_email": "r@x.com"},
                                  headers={})
        validate_error(resp, E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_create_load_with_unknown_shipper_not_found(
            self, api, dispatcher_headers):
        """PRD §3.3: "The referenced shipper must exist
        (`ERR_SHIPPER_NOT_FOUND`), as must the backhaul target
        (`ERR_LOAD_NOT_FOUND`)."
        PRD §2.7: "Identifiers carried in the request body — `shipper_id`,
        `trailer_compartment_id`, `driver_id`, `backhaul_of_load_id`, `load_id`
        — must resolve to existing resources, again producing the referenced
        resource's specific not-found error (HTTP 404)."

        Design: Corner/validations/create_load_with_unknown_shipper_not_found
        """
        resp = api.create_load(
            create_load_payload(shipper_id=NON_EXISTENT_UUID),
            dispatcher_headers)
        validate_error(resp, E.ERR_SHIPPER_NOT_FOUND)

    def test_allocate_to_missing_compartment_not_found(
            self, api, dispatcher_headers):
        """PRD §3.3: "The checks run in a fixed order: the compartment must
        exist (`ERR_COMPARTMENT_NOT_FOUND`); the load must still be `DRAFT`
        (`ERR_LOAD_NOT_DRAFT`, HTTP 409); `expected_load_version` must match the
        load's current `version` (`ERR_STALE_VERSION`, HTTP 412); the
        compartment must not already hold an `ACTIVE` allocation of a different
        species (`ERR_SPECIES_MIX_FORBIDDEN`, HTTP 422); the compartment's head
        room must suffice — `occupied_head_count` plus the new `head_count` may
        not exceed `max_head_count`, with a placement exactly at capacity
        allowed (`ERR_COMPARTMENT_HEAD_EXCEEDED`, HTTP 422); and the
        compartment's weight room must suffice — `occupied_weight_lb` plus the
        new allocation's `weight_lb` may not exceed `max_weight_lb`
        (`ERR_COMPARTMENT_WEIGHT_EXCEEDED`, HTTP 422)."

        Design: Corner/errors/allocate_to_missing_compartment_not_found
        """
        shipper = create_shipper()
        load = create_load(shipper["id"])
        resp = api.create_allocation(
            load["id"],
            {"trailer_compartment_id": NON_EXISTENT_UUID, "head_count": 2,
             "avg_weight_lb": 500,
             "expected_load_version": load["version"]},
            dispatcher_headers)
        validate_error(resp, E.ERR_COMPARTMENT_NOT_FOUND)
