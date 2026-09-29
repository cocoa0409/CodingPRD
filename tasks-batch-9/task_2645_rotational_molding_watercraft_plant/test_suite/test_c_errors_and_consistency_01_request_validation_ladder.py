"""Request-level rejections: headers, identity, existence, schema and uniqueness.

Every test in this module drives a request that PRD §2.7 refuses in one of its
first three bands, before any lifecycle, safety or capacity rule can run, and
pins the exact identifier PRD.md names for that refusal. The four authentication
codes are separated by what is wrong with the same pair of headers; the
not-found codes are separated by whether PRD.md declares an entity-specific
code for the entity being addressed; the schema codes are separated by whether
the defect is an absent field, an unknown enum member or a value outside a
declared numeric bound.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    Q_CUBE,
    Q_MASS,
    assert_decimal_equals,
    assert_instant_equals,
    build_user_headers,
    create_plant_baseline,
    create_technician,
    get_success_data,
    inspect_payload,
    mold_payload,
    outfit_payload,
    product_model_payload,
    set_clock,
    setup_demolded_units,
    suspend_payload,
    technician_payload,
    trim_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    warehouse_payload,
    zone,
)

CLOCK_START = "2026-08-01T00:00:00Z"


class TestAuthenticationLadder:
    """The four header failures of PRD §2.1, separated one rung at a time."""

    def test_role_permission_is_settled_before_the_asserted_identity_is_resolved(
        self, api, admin_headers
    ):
        """PRD §2.1: "When `X-User-Role` is not one of the eight role names below
        the request is rejected with `ERR_INVALID_ROLE` (HTTP 401). When the role
        is recognised but the endpoint being called does not list it among its
        authorised roles, the request is rejected with `ERR_ROLE_NOT_PERMITTED`
        (HTTP 403)." PRD §2.1: "Four roles ... are backed by the `Technician`
        entity, so `X-User-ID` must resolve to a `Technician` row; if it does
        not, the request fails with `ERR_IDENTITY_NOT_FOUND` (HTTP 401)."
        PRD §2.1: "Asserting one shop-floor role with the identifier of a
        technician carrying a different `role_code` fails with
        `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403)." PRD §2.7 evaluates
        "header presence, role validity, endpoint permission, identity
        resolution, role/identity agreement, customer scope" in that ascending
        order and "returns on the first failure it finds", and PRD §4 rejects an
        unlisted role "before any business rule runs".

        Design: Corner/errors/err_auth_ladder_role_not_permitted_precedes_identity_and_role_code_checks
        """
        ctx = create_plant_baseline()

        # Rung 2 — MOLDING_OPERATOR is a Technician role_code, not one of the
        # eight role names, so the role itself is invalid.
        res = api.list_technicians(
            None, build_user_headers(ctx["molding_operator_id"], "MOLDING_OPERATOR")
        )
        validate_error(res, ApiErrorId.INVALID_ROLE)

        # Rung 3 beats rung 4 — POST /molds does not list MoldingOperator, so
        # the unresolvable X-User-ID is never looked up.
        molds_before = validate_paginated(api.list_molds(None, admin_headers))[1]
        res = api.create_mold(
            mold_payload(ctx["product_model_id"]),
            build_user_headers(NON_EXISTENT_UUID, "MoldingOperator"),
        )
        validate_error(res, ApiErrorId.ROLE_NOT_PERMITTED)
        molds_after = validate_paginated(api.list_molds(None, admin_headers))[1]
        assert molds_after["total_count"] == molds_before["total_count"], (
            "a request refused with ERR_ROLE_NOT_PERMITTED must not register a mould"
        )

        # Rung 4 — the same unresolvable id on an endpoint MoldingOperator may
        # call is an identity failure, not a 404.
        res = api.list_technicians(
            None, build_user_headers(NON_EXISTENT_UUID, "MoldingOperator")
        )
        validate_error(res, ApiErrorId.IDENTITY_NOT_FOUND)

        # Rung 5 — the id resolves, but to a QUALITY_INSPECTOR row.
        res = api.list_technicians(
            None, build_user_headers(ctx["quality_inspector_id"], "MoldingOperator")
        )
        validate_error(res, ApiErrorId.ROLE_IDENTITY_MISMATCH)

        # Every rung cleared: the same id under its own role name is admitted.
        res = api.list_technicians(
            None, build_user_headers(ctx["quality_inspector_id"], "QualityInspector")
        )
        validate_success(res)
        assert res.json()["response_type"] == "array"


class TestTechnicianStateAndCertification:
    """Suspension and missing certifications, each isolated to a single cause."""

    def test_suspension_and_missing_certification_each_refuse_the_shop_floor_write(
        self, api, admin_headers
    ):
        """PRD §2.1: "A suspended shop-floor technician (`status` `SUSPENDED`)
        may not act and may not be named as the subject of an operation; either
        case yields `ERR_TECHNICIAN_SUSPENDED` (HTTP 403). A technician who lacks
        the certification an operation requires is refused with
        `ERR_TECHNICIAN_NOT_CERTIFIED` (HTTP 403)." PRD §3.1: "Suspension mutates
        no cycle and no hull: it only causes that technician's *next* action to
        be refused, because every shop-floor write first checks that the acting
        technician is `ACTIVE`." PRD §3.6: outfitting "requires `build_status`
        `TRIMMED`, requires the `FIXTURE_ASSEMBLY` certification
        (`ERR_TECHNICIAN_NOT_CERTIFIED`), moves the hull to `OUTFITTED`, and
        stamps `outfitted_by_technician_id` with the acting identifier".
        PRD §3.6: inspection "requires both the `WALL_GAUGE` and `IMPACT_RIG`
        certifications".

        Design: Corner/errors/err_technician_state_suspension_outranks_the_certification_check
        """
        ctx = setup_demolded_units()
        unit_id = ctx["finished_unit_ids"][0]

        # A second assembly technician, fully certified, then suspended: the
        # only thing wrong with its request is its status.
        suspended = create_technician("ASSEMBLY_TECH")
        get_success_data(
            api.suspend_technician(
                suspended["technician_id"],
                suspend_payload("Safety stand-down"),
                admin_headers,
            )
        )
        # A third assembly technician that is ACTIVE but holds no certification:
        # the only thing wrong with its request is the missing FIXTURE_ASSEMBLY.
        uncertified = create_technician("ASSEMBLY_TECH", certifications=[])

        res = api.trim_finished_unit(unit_id, trim_payload(0.4), suspended["headers"])
        validate_error(res, ApiErrorId.TECHNICIAN_SUSPENDED)
        held = api.read_entity("get_finished_unit", unit_id, admin_headers)
        assert held["build_status"] == "DEMOLDED"

        trimmed = get_success_data(
            api.trim_finished_unit(unit_id, trim_payload(0.4), ctx["assembly_headers"])
        )
        assert trimmed["build_status"] == "TRIMMED"
        assert_decimal_equals(trimmed["trim_waste_kg"], "0.400", Q_MASS, "trim_waste_kg")

        res = api.outfit_finished_unit(
            unit_id, outfit_payload("HK-UNCERT"), uncertified["headers"]
        )
        validate_error(res, ApiErrorId.TECHNICIAN_NOT_CERTIFIED)

        res = api.outfit_finished_unit(
            unit_id, outfit_payload("HK-SUSPENDED"), suspended["headers"]
        )
        validate_error(res, ApiErrorId.TECHNICIAN_SUSPENDED)

        held = api.read_entity("get_finished_unit", unit_id, admin_headers)
        assert held["build_status"] == "TRIMMED"
        assert held["outfitted_by_technician_id"] is None
        assert held["hardware_kit_serial"] is None

        outfitted = get_success_data(
            api.outfit_finished_unit(
                unit_id, outfit_payload("HK-GOOD"), ctx["assembly_headers"]
            )
        )
        assert outfitted["build_status"] == "OUTFITTED"
        assert outfitted["outfitted_by_technician_id"] == ctx["assembly_technician_id"]

        # An inspector holding only WALL_GAUGE is short the IMPACT_RIG the
        # inspection also requires.
        half_certified = create_technician(
            "QUALITY_INSPECTOR", certifications=["WALL_GAUGE"]
        )
        res = api.inspect_finished_unit(
            unit_id, inspect_payload(), half_certified["headers"]
        )
        validate_error(res, ApiErrorId.TECHNICIAN_NOT_CERTIFIED)

        inspected = get_success_data(
            api.inspect_finished_unit(unit_id, inspect_payload(), ctx["inspector_headers"])
        )
        assert inspected["inspection_verdict"] == "PASS"
        assert inspected["inspected_by_technician_id"] == ctx["quality_inspector_id"]


class TestNotFoundCodes:
    """Entity-specific not-found codes versus the generic fallback."""

    def test_unknown_ids_report_the_entity_specific_code_where_one_is_declared(
        self, api, admin_headers, planner_headers, warranty_agent_headers
    ):
        """PRD §2.7: "**Existence** — path identifiers first, then body foreign
        keys, each reported with its entity-specific not-found code where one
        exists and with `ERR_RESOURCE_NOT_FOUND` otherwise." PRD §2.8: a mould's
        `product_model_id` is "required, must resolve or
        `ERR_PRODUCT_MODEL_NOT_FOUND`". PRD §2.7 places Existence at rung 2 and
        "Schema and type validation" at rung 3, and "returns on the first failure
        it finds". PRD §2.2: an error response carries "`response_type` `error`"
        with "`error_id`" and "`message`" inside `data`.

        Design: Corner/errors/err_404_entity_specific_code_versus_the_generic_fallback_and_its_precedence
        """
        set_clock(CLOCK_START)
        model = get_success_data(
            api.create_product_model(product_model_payload(), admin_headers)
        )

        # WarrantyClaim and ShipmentLine have no not-found code of their own in
        # the PRD §5 catalogue, so the generic fallback answers for them.
        res = api.get_warranty_claim(NON_EXISTENT_UUID, warranty_agent_headers)
        validate_error(res, ApiErrorId.RESOURCE_NOT_FOUND)
        res = api.get_shipment_line(NON_EXISTENT_UUID, planner_headers)
        validate_error(res, ApiErrorId.RESOURCE_NOT_FOUND)

        # Mold and Shipment each declare one, so the specific code answers.
        res = api.get_mold(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.MOLD_NOT_FOUND)
        res = api.get_shipment(NON_EXISTENT_UUID, planner_headers)
        validate_error(res, ApiErrorId.SHIPMENT_NOT_FOUND)

        # A body foreign key that does not resolve is reported before the
        # out-of-range cavity_count in the same body is ever judged.
        res = api.create_mold(
            mold_payload(NON_EXISTENT_UUID, cavity_count=9), admin_headers
        )
        validate_error(res, ApiErrorId.PRODUCT_MODEL_NOT_FOUND)
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_PRODUCT_MODEL_NOT_FOUND"
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"]
        assert "error" not in body, "the error identifier lives inside data, not at the top level"

        _, meta = validate_paginated(api.list_molds(None, admin_headers))
        assert meta["total_count"] == 0, "a 404 must not register the mould it named"

        # The model that does exist is still readable, so nothing was lost.
        assert api.read_entity("get_product_model", model["id"], admin_headers)["id"] == model["id"]


class TestSchemaAndRangeCodes:
    """PRD §2.4 assigns one code per kind of schema defect; each is probed alone."""

    def test_absent_field_unknown_enum_member_and_out_of_range_number_are_distinct_codes(
        self, api, admin_headers
    ):
        """PRD §2.4: "Where a field declares a decimal-place count, a supplied
        value with more precision than that is a schema failure reported as
        `ERR_VALIDATION`; where a field declares numeric bounds, a value outside
        those bounds is reported as `ERR_INVALID_QUANTITY` (HTTP 422). A field
        whose declared type does not match the supplied JSON type, a required
        field that is absent, and a timestamp or date string that does not parse
        are all `ERR_VALIDATION`. A value outside an enum's declared set is
        `ERR_INVALID_ENUM_VALUE`." PRD §2.8: a mould's `size_class` is "required,
        one of the four classes" and its `cavity_count` is a "required integer,
        1 to 4 inclusive". PRD §2.5: the clock instant "must parse as an ISO 8601
        UTC timestamp or the request fails with `ERR_VALIDATION`".

        Design: Corner/errors/err_422_schema_ladder_missing_field_then_enum_then_numeric_bound
        """
        set_clock(CLOCK_START)
        model = get_success_data(
            api.create_product_model(product_model_payload(), admin_headers)
        )

        # Each probe below carries exactly one defect, so PRD.md pins one answer.
        absent = mold_payload(model["id"])
        del absent["size_class"]
        validate_error(api.create_mold(absent, admin_headers), ApiErrorId.VALIDATION)

        validate_error(
            api.create_mold(
                mold_payload(model["id"], size_class="GIGANTIC"), admin_headers
            ),
            ApiErrorId.INVALID_ENUM_VALUE,
        )

        # cavity_count 5 breaks the 1..4 bound; nominal_charge_kg is set to the
        # model's 12.000 times 5 so the cross-field mass rule is satisfied.
        validate_error(
            api.create_mold(
                mold_payload(model["id"], cavity_count=5, nominal_charge_kg=60.0),
                admin_headers,
            ),
            ApiErrorId.INVALID_QUANTITY,
        )

        _, meta = validate_paginated(api.list_molds(None, admin_headers))
        assert meta["total_count"] == 0, "no refused create may register a mould"

        # A timestamp that does not parse is refused and leaves the clock alone.
        res = api.set_clock({"current_utc": "2026-08-01 09:00:00"}, admin_headers)
        validate_error(res, ApiErrorId.VALIDATION)
        assert_instant_equals(
            api.read_current_utc(admin_headers), CLOCK_START, "current_utc"
        )

    def test_pagination_bounds_are_schema_failures_and_the_ceiling_itself_is_accepted(
        self, api, admin_headers
    ):
        """PRD §2.3: "`limit` bounds the page size; it defaults to 10, must be at
        least 1 and at most 100, and a value outside that range is rejected with
        `ERR_VALIDATION` (HTTP 422). `offset` is the zero-based index of the
        first row returned; it defaults to 0 and must not be negative." PRD §2.3:
        "List responses populate `limit`, `offset`, `total_count` and `has_more`
        in the `meta` object ... `has_more` is true exactly when `offset` plus the
        number of returned rows is strictly less than `total_count`."

        Design: Corner/errors/err_422_schema_ladder_missing_field_then_enum_then_numeric_bound
        """
        set_clock(CLOCK_START)
        get_success_data(api.create_product_model(product_model_payload(), admin_headers))

        validate_error(
            api.list_product_models({"limit": 101}, admin_headers),
            ApiErrorId.VALIDATION,
        )
        # 0 is not a synonym for "no limit": the declared range starts at 1.
        validate_error(
            api.list_product_models({"limit": 0}, admin_headers),
            ApiErrorId.VALIDATION,
        )
        # A negative offset is out of its declared bound; PRD §2.3 calls the
        # pagination band a schema failure while PRD §2.4 assigns out-of-bound
        # numbers their own code, so either identifier honours the contract.
        validate_error_is_one_of(
            api.list_product_models({"limit": 10, "offset": -1}, admin_headers),
            [ApiErrorId.VALIDATION, ApiErrorId.INVALID_QUANTITY],
        )

        data, meta = validate_paginated(
            api.list_product_models({"limit": 100}, admin_headers)
        )
        assert len(data) == 1
        assert meta["limit"] == 100
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


class TestUniquenessCodes:
    """PRD §2.8 rejects a reused business code, including a repeat inside one array."""

    def test_duplicate_business_codes_are_refused_and_sit_below_the_range_check(
        self, api, admin_headers, planner_headers
    ):
        """PRD §2.8: a model's `model_code` is "globally unique with case-sensitive
        exact matching, duplicate rejected as `ERR_DUPLICATE_CODE`"; a
        technician's `employee_code` is "required, 3–32 characters, globally
        unique, duplicate rejected as `ERR_DUPLICATE_CODE`"; a warehouse's
        `site_code` is "globally unique, duplicate rejected as
        `ERR_DUPLICATE_CODE`" and each zone holds a `zone_code` "2–16 characters
        and unique within the site, a repeat being `ERR_DUPLICATE_CODE`".
        PRD §2.8: `restricted_threshold_pct` must be "greater than 0.00 and
        strictly less than `frozen_threshold_pct`". PRD §2.7 band 3 runs
        "required fields, JSON types, numeric bounds, enum membership,
        measurement-count minimums, date-window sanity, and business-code
        uniqueness" in that ascending order and "returns on the first failure it
        finds".

        Design: Corner/errors/err_409_duplicate_code_family_including_a_repeat_inside_one_zones_array
        """
        set_clock(CLOCK_START)
        model = get_success_data(
            api.create_product_model(
                product_model_payload(model_code="PM-DUP-1"), admin_headers
            )
        )
        get_success_data(
            api.create_technician(
                technician_payload("RESIN_TECH", employee_code="T-DUP-1"), admin_headers
            )
        )
        site = get_success_data(
            api.create_warehouse(
                warehouse_payload(site_code="WH-DUP-1"), planner_headers
            )
        )

        # A second row reusing a global business code is refused, and the
        # original row is the only one left standing.
        res = api.create_product_model(
            product_model_payload(model_code="PM-DUP-1", hull_type="CANOE"),
            admin_headers,
        )
        validate_error(res, ApiErrorId.DUPLICATE_CODE)
        assert validate_paginated(api.list_product_models(None, admin_headers))[1][
            "total_count"
        ] == 1

        # Uniqueness is on the code alone: a different role_code does not
        # release the employee_code.
        res = api.create_technician(
            technician_payload(
                "MOLDING_OPERATOR", employee_code="T-DUP-1", certifications=[]
            ),
            admin_headers,
        )
        validate_error(res, ApiErrorId.DUPLICATE_CODE)
        assert validate_paginated(api.list_technicians(None, admin_headers))[1][
            "total_count"
        ] == 1

        # A zone_code repeated inside one zones array is a duplicate with no
        # existing row to compare against.
        res = api.create_warehouse(
            warehouse_payload(
                site_code="WH-DUP-2",
                footprint_capacity_cube_m3=10.0,
                zones=[zone("Z-D", 5.0), zone("Z-D", 5.0)],
            ),
            planner_headers,
        )
        validate_error(res, ApiErrorId.DUPLICATE_CODE)

        # Both defective at once: the numeric bound is checked before the
        # business-code uniqueness that the same body also breaks.
        res = api.create_warehouse(
            warehouse_payload(
                site_code="WH-DUP-1",
                footprint_capacity_cube_m3=150.0,
                zones=[zone("Z-X", 150.0)],
                restricted_threshold_pct=120.0,
                frozen_threshold_pct=95.0,
            ),
            planner_headers,
        )
        validate_error(res, ApiErrorId.INVALID_QUANTITY)

        sites, meta = validate_paginated(api.list_warehouses(None, planner_headers))
        assert meta["total_count"] == 1
        assert sites[0]["id"] == site["id"]
        assert sites[0]["site_code"] == "WH-DUP-1"
        assert_decimal_equals(
            sites[0]["footprint_capacity_cube_m3"],
            "20.0000",
            Q_CUBE,
            "footprint_capacity_cube_m3",
        )
        assert model["model_code"] == "PM-DUP-1"
