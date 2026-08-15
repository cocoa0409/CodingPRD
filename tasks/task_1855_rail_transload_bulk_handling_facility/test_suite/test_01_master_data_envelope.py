"""Master data creation defaults, shape validation, 404s, system-field
handling, response envelope, and list pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_charge_entry,
    assert_customer,
    assert_equipment,
    assert_facility,
    assert_inventory_lot,
    assert_invoice,
    assert_product,
    assert_railcar,
    assert_track,
    create_customer_payload,
    create_equipment_payload,
    create_facility_payload,
    create_incident_payload,
    create_invoice_payload,
    create_lot_payload,
    create_product_payload,
    create_railcar_payload,
    create_spot_order_payload,
    create_track_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_customer_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    BILLING,
    OPERATOR,
    SAFETY,
    YARD,
    create_customer,
    create_facility,
    create_lot,
    create_product,
    create_railcar,
    create_track,
    set_clock,
)

NULL_UUID = NON_EXISTENT_UUID


class TestFacilityDefaults:
    def test_facility_create_defaults_patch_and_get(self, api):
        """PRD §2.6: "`free_demurrage_hours` (default 48, must be greater than
        0), `sit_free_days` (default 2, must be at least 0),
        `switch_buffer_minutes` (default 30, must be greater than 0),
        `free_switches_per_period` (default 0, must be at least 0), and
        `contamination_policy` (default `STRICT_MATRIX`, alternatively
        `WEIGHTED_SCORE`). When a facility is created its `safety_posture`
        starts at `NORMAL` and its `open_incident_count` at 0."
        PRD §2.4: "an integer `version` that increments by one on every
        mutation of that resource, including mutations caused by cascades from
        operations on other resources."

        Design: Corner/entities/facility_create_patch_get_defaults
        """
        fac = validate_success(
            api.create_facility(create_facility_payload(name="FT-E1"), ADMIN), 201
        )
        assert_facility(fac)
        assert fac["safety_posture"] == "NORMAL"
        assert fac["open_incident_count"] == 0
        assert fac["free_demurrage_hours"] == 48
        assert fac["sit_free_days"] == 2
        assert fac["switch_buffer_minutes"] == 30
        assert fac["contamination_policy"] == "STRICT_MATRIX"
        assert fac["version"] == 1

        patched = validate_success(
            api.patch_facility(
                fac["id"],
                {"free_demurrage_hours": 24,
                 "contamination_policy": "WEIGHTED_SCORE"},
                ADMIN,
            )
        )
        assert patched["free_demurrage_hours"] == 24
        assert patched["contamination_policy"] == "WEIGHTED_SCORE"
        assert patched["version"] == 2, "PATCH bumps version by exactly one"

        fetched = validate_success(api.get_facility(fac["id"], ADMIN))
        assert fetched["id"] == fac["id"]
        assert fetched["open_incident_count"] == 0


class TestMasterData:
    def test_master_data_create_and_get(self, api):
        """PRD §3.1: "The customer also carries a `credit_standing` (default
        `GOOD_STANDING`, escalating through `CREDIT_WATCH` to `CREDIT_HOLD`), a
        `demurrage_basis` (default `CONSTRUCTIVE`, alternatively `ACTUAL`) that
        selects when the demurrage clock starts, and a `sit_day_basis` (default
        `CALENDAR`, alternatively `BUSINESS`) that selects how
        storage-in-transit days are counted."
        PRD §3.1: "A `Track` is created with a `name` and a `spot_capacity`
        (strictly positive), starting `ACTIVE` with `derail_protection`
        `DISENGAGED` and zero `occupied_spots` and `reserved_spots`."
        PRD §3.1: "`Equipment` — a conveyor, pump, or hose (`equipment_type` of
        `CONVEYOR`, `PUMP`, or `HOSE`) — starts `AVAILABLE` with
        `last_product_id` null."
        PRD §3.2: "an optional `sit_free_days` override may be supplied, and
        otherwise the lot's `sit_free_days` is stamped from the facility's
        `sit_free_days` at creation. The lot's `sit_day_basis` is stamped from
        the customer's `sit_day_basis` at creation, and `sit_start_timestamp`
        is set to the current logical clock — that is the SIT custody start. A
        new lot is `ACTIVE` with `quantity_received_tons`,
        `quantity_shipped_tons`, and `quantity_rejected_tons` all at zero"
        PRD §3.8: "the invoice starts `DRAFT` with `charge_count` 0 and
        `total_cents` 0."

        Design: Corner/entities/master_data_create_and_get
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-E2")

        cust = validate_success(
            api.create_customer(
                create_customer_payload(name="ACME", allocated_car_spots=4), ADMIN
            ),
            201,
        )
        assert_customer(cust)
        assert cust["credit_standing"] == "GOOD_STANDING"
        assert cust["demurrage_basis"] == "CONSTRUCTIVE"
        assert cust["sit_day_basis"] == "CALENDAR"

        prod = validate_success(
            api.create_product(create_product_payload(name="Salt"), ADMIN), 201
        )
        assert_product(prod)

        trk = validate_success(
            api.create_track(create_track_payload(name="T1", spot_capacity=3), ADMIN),
            201,
        )
        assert_track(trk)
        assert trk["status"] == "ACTIVE"
        assert trk["derail_protection"] == "DISENGAGED"
        assert trk["occupied_spots"] == 0
        assert trk["reserved_spots"] == 0

        eq = validate_success(
            api.create_equipment(
                create_equipment_payload(name="PUMP-1", equipment_type="PUMP"), ADMIN
            ),
            201,
        )
        assert_equipment(eq)
        assert eq["status"] == "AVAILABLE"
        assert eq["last_product_id"] is None

        lot = validate_success(
            api.create_lot(
                create_lot_payload(
                    customer_id=cust["id"], product_id=prod["id"],
                    sit_daily_rate_cents=5000,
                ),
                ADMIN,
            ),
            201,
        )
        assert_inventory_lot(lot)
        assert lot["status"] == "ACTIVE"
        assert lot["sit_free_days"] == 2, "stamped from the facility default"
        assert lot["sit_day_basis"] == "CALENDAR", "stamped from the customer"
        assert lot["sit_start_timestamp"][:19] == "2026-08-03T00:00:00"
        assert lot["quantity_received_tons"] == 0
        assert lot["quantity_shipped_tons"] == 0
        assert lot["quantity_on_hand_tons"] == 0

        inv = validate_success(
            api.create_invoice(create_invoice_payload(customer_id=cust["id"]), BILLING),
            201,
        )
        assert_invoice(inv)
        assert inv["status"] == "DRAFT"
        assert inv["total_cents"] == 0
        assert inv["charge_count"] == 0

        rep = make_customer_rep_headers(cust["id"])
        assert validate_success(api.get_customer(cust["id"], BILLING))["name"] == "ACME"
        assert validate_success(api.get_product(prod["id"], YARD))["name"] == "Salt"
        assert validate_success(api.get_track(trk["id"], SAFETY))["spot_capacity"] == 3
        assert validate_success(api.get_equipment(eq["id"], OPERATOR))["name"] == "PUMP-1"
        assert validate_success(api.get_lot(lot["id"], rep))["quantity_on_hand_tons"] == 0
        assert validate_success(api.get_invoice(inv["id"], rep))["status"] == "DRAFT"


class TestInvalidRequests:
    def test_create_rejected_invalid_request_family(self, api):
        """PRD §2.9: "4. Envelope and shape — required fields present, types
        valid, enum members valid, numeric ranges valid (strictly positive
        where required), and `window_end` strictly after `window_start`
        (`ERR_INVALID_REQUEST`, 400)."
        PRD §3.1: a track's `spot_capacity` is "strictly positive"; PRD §3.3:
        `quantity_loaded_tons` "strictly positive, three-decimal precision";
        PRD §3.2: a lot carries "a `sit_daily_rate_cents` (strictly positive,
        integer cents per day)"; PRD §3.8: "`period_end` (inclusive, and at
        least `period_start`)".

        Design: Corner/entities/entity_create_rejected_invalid_request
        """
        fac = create_facility(name="FT-E3")
        cust = create_customer(name="ACME", allocated_car_spots=4)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=2)
        car = create_railcar(cust["id"], prod["id"], lot["id"], car_number="95001")

        cases = [
            # missing required name
            api.create_customer({"allocated_car_spots": 4}, ADMIN),
            # invalid enum member for hazard_class
            api.create_product(
                create_product_payload(name="X", hazard_class="RADIOACTIVE"), ADMIN
            ),
            # non-positive spot_capacity
            api.create_track({"name": "T2", "spot_capacity": 0}, ADMIN),
            # invalid enum member for equipment_type
            api.create_equipment({"name": "Z", "equipment_type": "CRANE"}, ADMIN),
            # non-positive quantity_loaded_tons
            api.create_railcar(
                create_railcar_payload(
                    customer_id=cust["id"], product_id=prod["id"],
                    lot_id=lot["id"], car_number="95002", quantity_loaded_tons=0,
                ),
                YARD,
            ),
            # missing required sit_daily_rate_cents
            api.create_lot(
                {"customer_id": cust["id"], "product_id": prod["id"]}, ADMIN
            ),
            # window_end not strictly after window_start
            api.create_spot_order(
                car["id"],
                create_spot_order_payload(
                    expected_railcar_version=car["version"],
                    track_id=trk["id"],
                    spot_number=1,
                    window_start="2026-08-03T05:00:00Z",
                    window_end="2026-08-03T01:00:00Z",
                ),
                YARD,
            ),
            # period_end before period_start
            api.create_invoice(
                create_invoice_payload(
                    customer_id=cust["id"],
                    period_start="2026-08-31T00:00:00Z",
                    period_end="2026-08-01T00:00:00Z",
                ),
                BILLING,
            ),
            # invalid enum member for severity
            api.create_incident(
                create_incident_payload(severity="CATASTROPHIC"), SAFETY
            ),
            # missing required to_iso8601
            api._request("POST", "/_clock/set_current_utc", {}, ADMIN),
        ]
        for resp in cases:
            validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        # The rejected calls created nothing: only the setup car exists.
        cars, cars_meta = validate_paginated(api.list_railcars(YARD))
        assert cars_meta["total_count"] == 1 and cars[0]["id"] == car["id"]
        _invs, inv_meta = validate_paginated(api.list_invoices(BILLING))
        assert inv_meta["total_count"] == 0


class TestNotFound:
    def test_get_unknown_id_returns_not_found(self, api):
        """PRD §2.9: "3. Existence — path ids resolve left-to-right, then body
        foreign-key ids (`railcar_id`, `lot_id`, `customer_id`, `product_id`,
        `equipment_id`, `track_id`) resolve (`ERR_NOT_FOUND`, 404)."

        Design: Corner/entities/entity_get_not_found
        """
        reads = [
            api.get_facility(NULL_UUID, ADMIN),
            api.get_customer(NULL_UUID, ADMIN),
            api.get_product(NULL_UUID, ADMIN),
            api.get_track(NULL_UUID, YARD),
            api.get_equipment(NULL_UUID, OPERATOR),
            api.get_incident(NULL_UUID, SAFETY),
            api.get_railcar(NULL_UUID, YARD),
            api.get_lot(NULL_UUID, ADMIN),
            api.get_spot_order(NULL_UUID, YARD),
            api.get_switch_order(NULL_UUID, YARD),
            api.get_transfer_order(NULL_UUID, OPERATOR),
            api.get_weight_ticket(NULL_UUID, OPERATOR),
            api.get_charge(NULL_UUID, BILLING),
            api.get_invoice(NULL_UUID, BILLING),
        ]
        for resp in reads:
            validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSystemFieldsIgnored:
    def test_system_and_computed_fields_input_ignored(self, api):
        """PRD §2.6: "The `safety_posture` is computed, never set directly"
        and "When a facility is created its `safety_posture` starts at `NORMAL`
        and its `open_incident_count` at 0."
        PRD §3.1: "A `Track` is created with a `name` and a `spot_capacity`
        (strictly positive), starting `ACTIVE` with `derail_protection`
        `DISENGAGED` and zero `occupied_spots` and `reserved_spots`."
        PRD §3.1: "Both are maintained by the system as placements are
        scheduled, executed, cancelled, superseded, and released."

        Design: Corner/entities/system_and_computed_fields_input_ignored
        """
        fac = validate_success(
            api.create_facility(
                {"name": "FT-E5", "safety_posture": "SUSPENDED",
                 "open_incident_count": 9, "version": 42},
                ADMIN,
            ),
            201,
        )
        assert fac["safety_posture"] == "NORMAL", "client-supplied posture ignored"
        assert fac["open_incident_count"] == 0
        assert fac["version"] == 1, "server mints the initial version"

        trk = validate_success(
            api.create_track(
                {"name": "T1", "spot_capacity": 2, "status": "OUT_OF_SERVICE",
                 "occupied_spots": 7, "derail_protection": "ENGAGED"},
                ADMIN,
            ),
            201,
        )
        assert trk["status"] == "ACTIVE"
        assert trk["occupied_spots"] == 0
        assert trk["derail_protection"] == "DISENGAGED"


class TestCustomerPatch:
    def test_customer_patch_and_version_progression(self, api):
        """PRD §3.1: "The administrator may later update `credit_standing`,
        `demurrage_basis`, or `sit_day_basis`; each update bumps
        `Customer.version`."
        PRD §2.4: "an integer `version` that increments by one on every
        mutation of that resource".

        Design: Corner/entities/customer_patch_and_version_progression
        """
        create_facility(name="FT-E6")
        cust = create_customer(name="ACME", allocated_car_spots=4)
        assert cust["version"] == 1

        p1 = validate_success(
            api.patch_customer(cust["id"], {"credit_standing": "CREDIT_WATCH"}, ADMIN)
        )
        assert p1["version"] == 2
        assert p1["credit_standing"] == "CREDIT_WATCH"
        assert p1["demurrage_basis"] == "CONSTRUCTIVE", "unsent fields unchanged"

        p2 = validate_success(
            api.patch_customer(cust["id"], {"demurrage_basis": "ACTUAL"}, ADMIN)
        )
        assert p2["version"] == 3
        assert p2["credit_standing"] == "CREDIT_WATCH"
        assert p2["demurrage_basis"] == "ACTUAL"


class TestResponseEnvelope:
    def test_response_envelope_shape(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources." and
        "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`,
        `has_more`) are included for list endpoints."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
        unique, machine-readable string that identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape
        """
        fac = create_facility(name="FT-EP1")

        obj_resp = api.get_facility(fac["id"], ADMIN)
        body = obj_resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["id"] == fac["id"]

        data, meta = validate_paginated(api.list_railcars(ADMIN))
        assert isinstance(data, list)
        assert meta["limit"] == 10 and meta["offset"] == 0, (
            "PRD §2.3 defaults: limit 10, offset 0"
        )
        list_body = api.list_railcars(ADMIN).json()
        assert list_body["response_type"] == "array"

        err_resp = api.get_facility(NULL_UUID, ADMIN)
        assert err_resp.status_code == 404
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"].strip()


class TestRailcarPagination:
    def test_railcar_list_limit_offset_window(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`
        (default 10, minimum 1, maximum 100) and `offset` (default 0). List
        responses order by `created_at` ascending. The `meta` block of a list
        response carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/cross_cutting_layers/pagination_with_filtering
        """
        create_facility(name="FT-L3")
        cust_a = create_customer(name="A", allocated_car_spots=5)
        cust_b = create_customer(name="B", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot_a = create_lot(cust_a["id"], prod["id"])
        lot_b = create_lot(cust_b["id"], prod["id"])
        for i in range(3):
            create_railcar(
                cust_a["id"], prod["id"], lot_a["id"], car_number=f"9741{i + 1}"
            )
        create_railcar(cust_b["id"], prod["id"], lot_b["id"], car_number="97414")

        page1, meta1 = validate_paginated(api.list_railcars(YARD, params={"limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 4
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_railcars(YARD, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 2
        assert meta2["total_count"] == 4
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2
        assert {c["id"] for c in page1}.isdisjoint({c["id"] for c in page2})
