"""Terminals, shipment tender, initial GROSS rating, and shared read access."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_shipment,
    assert_terminal,
    create_shipment_payload,
    create_terminal_payload,
    get_success_data,
    make_rated_shipment,
    make_shipment,
    make_terminal,
    make_terminal_pair,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTerminals:
    def test_terminal_creation_applies_defaults_and_rejects_duplicate_code(self, api):
        """PRD §2.9: "Terminals each carry a `timezone` (an IANA timezone name,
        defaulting to `America/Chicago` when not supplied at registration) that
        governs service-standard cutoff math"
        PRD §2.10: "Closing a terminal is a one-way `ACTIVE` → `CLOSED` transition
        available to a `TerminalAdmin`."
        PRD §2.10: "A `TerminalAdmin` registers a terminal with a unique `code`
        (exactly three uppercase letters, A through Z — for example CHI), a
        human-readable `name`, the count of physical `dock_doors` at the facility
        (an integer of at least 1), and an optional `timezone`."

        Design: Corner/entities/terminal_creation_defaults_and_unique_code
        """
        resp = api.create_terminal(
            create_terminal_payload(code="CHI", name="Chicago", dock_doors=12),
            headers=TEST_USERS["terminal_admin_headers"],
        )
        terminal = validate_success(resp, expected_status=201)
        assert_terminal(terminal)
        assert terminal["timezone"] == "America/Chicago", (
            "default timezone America/Chicago must be applied when not supplied"
        )
        assert terminal["status"] == "ACTIVE"

        dup = api.create_terminal(
            create_terminal_payload(code="CHI", name="Dup", dock_doors=4),
            headers=TEST_USERS["terminal_admin_headers"],
        )
        validate_error(dup, ApiErrorId.ERR_INVALID_REQUEST)


class TestShipmentTender:
    def test_shipment_creation_mints_pro_and_system_fields(self, api):
        """PRD §3.1: "On acceptance the server mints a `pro_number` — the string
        `PRO-` followed by a zero-padded serial — and stamps `tendered_at_utc`
        from the logical clock. The new shipment is born with `rating_status`
        `UNRATED` and `handling_status` `TENDERED`"
        PRD §3.1: "`chargeable_weight_lbs` equals the declared `actual_weight_lbs`,
        `dim_weight_lbs` is 0 until a dimensioner measurement exists,
        `rated_amount_cents` is 0 until the first rating run, and
        `billed_amount_cents` stays 0 until the shipment is actually billed."

        Design: Corner/entities/shipment_creation_system_fields_and_pro_minting
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(
            origin["id"], dest["id"], nmfc_class="CLASS_70", actual_weight_lbs=450,
            length_in=48, width_in=40, height_in=48, service_standard="STANDARD",
        )
        assert_shipment(shipment)
        assert shipment["pro_number"].startswith("PRO-"), (
            "pro_number must be server-minted with the PRO- prefix"
        )
        assert shipment["rating_status"] == "UNRATED"
        assert shipment["handling_status"] == "TENDERED"
        assert shipment["rated_amount_cents"] == 0
        assert shipment["billed_amount_cents"] == 0
        assert shipment["chargeable_weight_lbs"] == 450
        assert shipment["dim_weight_lbs"] == 0
        assert shipment["osd_hold"] is False

    def test_shipment_missing_required_field_rejected(self, api):
        """PRD §3.1: "A `Dispatcher` tenders a shipment by supplying
        `origin_terminal_id` and `destination_terminal_id` (both must resolve to
        existing terminals, and the origin must not be `CLOSED`), the declared
        `nmfc_class`, the shipper-declared `actual_weight_lbs` in whole pounds,
        the declared carton dimensions `length_in`, `width_in`, and `height_in`
        in whole inches, the committed `service_standard`, and optionally a list
        of `accessorial_codes` requested at tender."
        PRD §2.8: "20. Field-level request validity — enum membership, integer
        ranges, required fields → `ERR_INVALID_REQUEST`."

        Design: Corner/entities/shipment_missing_required_field_returns_invalid_request
        """
        origin, dest = make_terminal_pair()
        payload = create_shipment_payload(origin["id"], dest["id"],
                                          nmfc_class="CLASS_70")
        del payload["actual_weight_lbs"]
        resp = api.create_shipment(payload, headers=TEST_USERS["dispatcher_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_shipment_invalid_nmfc_class_rejected(self, api):
        """PRD §3.1: "The declared NMFC class must be one of `CLASS_50`,
        `CLASS_55`, `CLASS_60`, `CLASS_65`, `CLASS_70`, `CLASS_85`, `CLASS_100`,
        or `CLASS_125`; each accessorial code must be one of `LIFTGATE`, `NOTIFY`,
        `RESIDENTIAL`, or `INSIDE`; weight and every dimension must be at least 1.
        Violations of enum membership or these ranges are rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/shipment_invalid_enum_returns_invalid_request
        """
        origin, dest = make_terminal_pair()
        payload = create_shipment_payload(origin["id"], dest["id"],
                                          nmfc_class="CLASS_999")
        resp = api.create_shipment(payload, headers=TEST_USERS["dispatcher_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_shipment_not_found(self, api):
        """PRD §2.8: "3. Path resolution — every id in the URL path is resolved
        left to right; the first unresolvable id yields `ERR_NOT_FOUND`."

        Design: Corner/entities/entity_get_not_found
        """
        resp = api.get_shipment(NON_EXISTENT_UUID,
                                headers=TEST_USERS["dispatcher_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_shipments_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10, must be at least 1,
        and may not exceed 100; a value outside that range is rejected with
        `ERR_INVALID_REQUEST`. The `offset` parameter defaults to 0 and must be a
        non-negative integer. Every list response includes the pagination fields
        `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/entities/shipments_list_pagination_envelope
        """
        origin, dest = make_terminal_pair()
        make_shipment(origin["id"], dest["id"], nmfc_class="CLASS_70",
                      actual_weight_lbs=450)
        resp = api.list_shipments(headers=TEST_USERS["dispatcher_headers"])
        body = resp.json()
        assert "api_request_id" in body["meta"], "meta.api_request_id required"
        assert "api_request_timestamp" in body["meta"], (
            "meta.api_request_timestamp required"
        )
        assert body["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0, "default offset is 0"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

    def test_logical_clock_default_and_commitment(self, api):
        """PRD §2.9: "At startup the clock reads 2026-08-01T00:00:00Z, and a
        `TerminalAdmin` may advance it to a supplied instant via a test-driving
        capability that accepts `to_iso8601` and reports back the new
        `current_utc`."
        PRD §3.1: "The committed delivery instant, `committed_delivery_utc`, is
        computed at tender as `tendered_at_utc` plus a number of terminal-local
        calendar days at the destination terminal: three days for `STANDARD`, two
        for `EXPEDITED`, one for `GUARANTEED`."

        Design: Corner/cross_cutting_layers/clock_default_is_fixed_startup_time
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(origin["id"], dest["id"], nmfc_class="CLASS_60",
                                 actual_weight_lbs=500,
                                 service_standard="GUARANTEED")
        assert shipment["tendered_at_utc"] == "2026-08-01T00:00:00Z", (
            "tender stamp must come from the default logical clock"
        )
        assert shipment["committed_delivery_utc"] == "2026-08-02T00:00:00Z", (
            "GUARANTEED commits tender + 1 terminal-local calendar day"
        )

    def test_tender_to_closed_terminal_rejected(self, api):
        """PRD §2.10: "Once a terminal is `CLOSED`, four kinds of new work against
        it are rejected with `ERR_TERMINAL_CLOSED` (HTTP 409): tendering a
        shipment whose origin is that terminal, spotting an outbound trailer at
        that terminal, opening a sortation batch at that terminal, and reserving
        a dock door belonging to that terminal."

        Design: Corner/validations/error_terminal_closed_on_shipment_tender
        """
        origin, dest = make_terminal_pair()
        validate_success(api.close_terminal(origin["id"],
                                            headers=TEST_USERS["terminal_admin_headers"]))
        resp = api.create_shipment(
            create_shipment_payload(origin["id"], dest["id"], nmfc_class="CLASS_60",
                                    actual_weight_lbs=500),
            headers=TEST_USERS["dispatcher_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TERMINAL_CLOSED)

    def test_tender_with_unknown_origin_fk_rejected(self, api):
        """PRD §2.8: "4. Body reference resolution — every foreign-key field in
        the request body (for example `origin_terminal_id`,
        `destination_terminal_id`, `route_id`, `shipment_id`, `trailer_id`,
        `scan_id`) must resolve to an existing entity, else
        `ERR_REFERENCE_NOT_FOUND`."

        Design: Corner/validations/error_body_fk_reference_not_found
        """
        dest = make_terminal(code="ATL", name="Atlanta", dock_doors=10)
        payload = create_shipment_payload(NON_EXISTENT_UUID, dest["id"],
                                          nmfc_class="CLASS_60",
                                          actual_weight_lbs=500)
        resp = api.create_shipment(payload, headers=TEST_USERS["dispatcher_headers"])
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_unauthenticated_request_beats_business_errors(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        API does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "Authentication is therefore evaluated before any other concern
        — the server never reaches path resolution, state checks, or business
        rules for an unauthenticated or unauthorized caller."

        Design: Corner/validations/priority_auth_beats_business
        """
        # No auth headers AND an empty (field-level invalid) body: auth wins.
        resp = api.create_shipment({}, headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestInitialRating:
    def test_freight_rating_class_100_constants(self, api):
        """PRD §3.2: "The **line-haul charge** is the chargeable weight divided by
        100 and multiplied by the per-class rate in cents per hundredweight,
        rounded half-up to whole cents. The per-class rates are: `CLASS_50` 1800,
        `CLASS_55` 2000, `CLASS_60` 2150, `CLASS_65` 2350, `CLASS_70` 2500,
        `CLASS_85` 2900, `CLASS_100` 3400, `CLASS_125` 4100."
        PRD §3.2: "The **fuel surcharge** is 22 percent of the rounded line-haul
        charge, itself rounded half-up to whole cents."

        Design: Corner/calculations/freight_rating_constants_applied_class_rates
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(origin["id"], dest["id"], nmfc_class="CLASS_100",
                                 actual_weight_lbs=200, length_in=36, width_in=36,
                                 height_in=36, service_standard="EXPEDITED")
        rated = validate_success(api.rate_shipment(
            shipment["id"], headers=TEST_USERS["rating_clerk_headers"]))
        # linehaul = 200/100*3400 = 6800; fuel = round_half_up(6800*0.22) = 1496
        assert rated["rated_amount_cents"] == 8296
        assert rated["rating_status"] == "RATED"
        assert rated["chargeable_weight_lbs"] == 200
        assert rated["dim_weight_lbs"] == 0

    def test_rating_rounding_order_linehaul_then_fuel(self, api):
        """PRD §3.2: "Note the rounding order is pinned: line-haul rounded first,
        fuel computed on the rounded line-haul, accessorials added last — never
        sum-then-round."
        PRD §2.5: "Where a calculation produces a fractional cent, the result is
        rounded half-up to whole cents before the next step of the calculation
        proceeds."

        Design: Difficulty/combinatorial_formula/freight_rating_nested_rounding_order
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(origin["id"], dest["id"], nmfc_class="CLASS_85",
                                 actual_weight_lbs=333, length_in=36, width_in=36,
                                 height_in=36, service_standard="STANDARD")
        rated = validate_success(api.rate_shipment(
            shipment["id"], headers=TEST_USERS["rating_clerk_headers"]))
        # linehaul = 333/100*2900 = 9657 (exact); fuel = round_half_up(9657*0.22)
        # = round_half_up(2124.54) = 2125; total 9657 + 2125 = 11782.
        assert rated["rated_amount_cents"] == 11782

    def test_rating_fuel_half_up_boundary(self, api):
        """PRD §3.2: "The **fuel surcharge** is 22 percent of the rounded
        line-haul charge, itself rounded half-up to whole cents."
        PRD §2.5: "Where a calculation produces a fractional cent, the result is
        rounded half-up to whole cents before the next step of the calculation
        proceeds."

        Design: Difficulty/combinatorial_formula/freight_rating_nested_rounding_order
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(origin["id"], dest["id"], nmfc_class="CLASS_70",
                                 actual_weight_lbs=91, length_in=36, width_in=36,
                                 height_in=36, service_standard="STANDARD")
        rated = validate_success(api.rate_shipment(
            shipment["id"], headers=TEST_USERS["rating_clerk_headers"]))
        # linehaul = 91/100*2500 = 2275 (exact); fuel = 2275*0.22 = 500.5 -> 501
        # half-up (a floor/truncation would yield 2775 instead of 2776).
        assert rated["rated_amount_cents"] == 2776

    def test_rate_already_rated_rejected(self, api):
        """PRD §3.2: "A `RatingClerk` runs the initial rating on a shipment whose
        `rating_status` is `UNRATED` and whose `handling_status` is either
        `TENDERED` or `ON_DOCK`; rating is impossible once the freight is
        manifested or further along, and impossible if either endpoint terminal
        has since gone `CLOSED` (both `origin_terminal_id` and
        `destination_terminal_id` must reference `ACTIVE` terminals at rating
        time). A state mismatch here is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/rate_already_rated_shipment_returns_invalid_state
        """
        origin, dest = make_terminal_pair()
        shipment = make_rated_shipment(origin["id"], dest["id"],
                                       nmfc_class="CLASS_70", actual_weight_lbs=450)
        # CLASS_70 450 lbs no accessorials: 11250 + round(11250*0.22)=2475 -> 13725
        assert shipment["rated_amount_cents"] == 13725
        resp = api.rate_shipment(shipment["id"],
                                 headers=TEST_USERS["rating_clerk_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_shipment(
            shipment["id"], headers=TEST_USERS["rating_clerk_headers"]))
        assert after["rated_amount_cents"] == 13725, (
            "a rejected re-rate must not move the billed basis"
        )

    def test_dispatcher_cannot_rate_shipment(self, api):
        """PRD §2.1: "A request whose role is valid but not authorized for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /ltl/shipments/{shipmentId}/rate is authorized for
        RatingClerk only.

        Design: Corner/rbac/dispatcher_cannot_rate_shipment
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(origin["id"], dest["id"], nmfc_class="CLASS_60",
                                 actual_weight_lbs=500)
        resp = api.rate_shipment(shipment["id"],
                                 headers=TEST_USERS["dispatcher_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSharedReadAccess:
    @pytest.mark.parametrize(
        "role_key",
        ["terminal_admin_headers", "dispatcher_headers", "dock_supervisor_headers",
         "rating_clerk_headers", "osd_clerk_headers"],
    )
    def test_shared_get_endpoints_allowed_for_all_roles(self, api, role_key):
        """PRD §2.1: "Read-only list and retrieval endpoints accept any of the
        five roles unless §4 says otherwise; write endpoints are restricted to
        the roles named in the endpoint table"

        Design: Corner/rbac/shared_get_endpoints_allowed_for_all_roles
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(origin["id"], dest["id"], nmfc_class="CLASS_60",
                                 actual_weight_lbs=500)
        resp = api.get_shipment(shipment["id"], headers=TEST_USERS[role_key])
        data = validate_success(resp)
        assert data["id"] == shipment["id"]
        assert data["pro_number"] == shipment["pro_number"]
