"""Registering a hull model and a tool, reading them back, and the two envelopes.

Every test here exercises the plainest shape of the API: a creation whose
derived ledger is seeded at insertion, a single-row read that echoes what was
stored, a well-formed identifier that resolves to nothing, and the two envelope
shapes PRD.md section 2.2 declares.
"""

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT_UTC,
    assert_common_fields,
    assert_instant_equals,
    assert_money_equals,
    assert_warranty_reserve_conserved,
    dec,
    get_success_data,
    mold_payload,
    product_model_payload,
    retire_mold_payload,
    set_clock,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    warehouse_payload,
)

UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"

# The 24 client-supplied fields PRD.md section 2.8 declares on ProductModel,
# spelled out here rather than taken from a factory so the echo assertions read
# against a literal body.
CANOE_MODEL_BODY = {
    "model_code": "PM-CD-CREATE",
    "hull_type": "CANOE",
    "size_class": "TANDEM",
    "resin_grade": "HDPE_XL",
    "master_color_code": "GRANITE",
    "max_color_delta_e": 1.5,
    "required_additive_package_code": "UV12",
    "max_regrind_pct": 30.0,
    "min_melt_index_g10min": 2.5,
    "max_melt_index_g10min": 6.0,
    "nominal_charge_kg": 30.0,
    "charge_tolerance_pct": 5.0,
    "min_cooling_minutes": 30,
    "target_wall_thickness_mm": 7.0,
    "wall_thickness_min_mm": 5.0,
    "wall_cv_max_pct": 12.0,
    "impact_test_min_joules": 110.0,
    "gross_cube_m3": 3.5,
    "nest_factor": 0.6,
    "unit_weight_kg": 41.0,
    "msrp_cents": 265000,
    "warranty_basis": "FLAT_SCHEDULE",
    "initial_warranty_reserve_cents": 400000,
    "seasonal_family": "PADDLE",
}


class TestProductModelRegistration:
    """POST /product-models opens the model's warranty ledger at creation."""

    def test_create_returns_201_and_seeds_the_warranty_ledger(
        self, api, admin_headers
    ):
        """A registered model seeds its two derived money fields.

        PRD.md section 3.1: "Registering a hull model establishes its process
        envelope and, at the same instant, opens its warranty ledger:
        `warranty_reserve_cents` is set to the supplied
        `initial_warranty_reserve_cents` and `warranty_paid_cents` to 0, and
        `version` starts at 1."

        PRD.md section 2.10: "A hull model holds a two-bucket ledger in which
        `warranty_reserve_cents` plus `warranty_paid_cents` always equals the
        immutable `initial_warranty_reserve_cents`; approving a claim moves the
        net payout from reserve to paid, and voiding an approval moves the
        identical integer back."

        PRD.md section 2.4: "`id` is a server-generated opaque string
        identifier, unique across its collection and never derived from
        business data."

        Design: Corner/entities/ent_create_product_model_returns_201_with_warranty_ledger_seeded
        """
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)

        created = validate_success(
            api.create_product_model(dict(CANOE_MODEL_BODY), admin_headers),
            expected_status=201,
        )

        assert_common_fields(created, "ProductModel")
        assert created["id"], "the server must mint a non-empty identifier"
        assert created["id"] not in CANOE_MODEL_BODY.values()
        assert created["model_code"] == "PM-CD-CREATE"
        assert created["hull_type"] == "CANOE"
        assert created["size_class"] == "TANDEM"
        assert created["resin_grade"] == "HDPE_XL"
        assert created["master_color_code"] == "GRANITE"
        assert dec(created["nominal_charge_kg"]) == dec("30.000")
        assert dec(created["charge_tolerance_pct"]) == dec("5.00")
        assert dec(created["gross_cube_m3"]) == dec("3.5000")
        assert dec(created["nest_factor"]) == dec("0.6000")
        assert created["warranty_basis"] == "FLAT_SCHEDULE"
        assert_money_equals(
            created["initial_warranty_reserve_cents"], 400000, "initial reserve"
        )
        assert_money_equals(
            created["warranty_reserve_cents"], 400000, "warranty_reserve_cents"
        )
        assert_money_equals(created["warranty_paid_cents"], 0, "warranty_paid_cents")
        assert_warranty_reserve_conserved(created)
        assert created["version"] == 1
        assert_instant_equals(created["created_at"], CLOCK_DEFAULT_UTC, "created_at")
        assert_instant_equals(created["updated_at"], CLOCK_DEFAULT_UTC, "updated_at")

    def test_single_read_returns_the_same_values_as_the_create_body(
        self, api, admin_headers
    ):
        """The single-model read exposes the live ledger the create seeded.

        PRD.md section 3.1: "Models are listed with optional `hull_type`,
        `size_class`, `resin_grade`, `warranty_basis` and `seasonal_family`
        filters, and a single-model read exposes the live
        `warranty_reserve_cents` and `warranty_paid_cents`."

        Design: Corner/entities/ent_create_product_model_returns_201_with_warranty_ledger_seeded
        """
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        body = dict(CANOE_MODEL_BODY, model_code="PM-CD-CREATE-READ")
        created = get_success_data(api.create_product_model(body, admin_headers))

        fetched = validate_success(
            api.get_product_model(created["id"], admin_headers)
        )

        for field in sorted(created):
            assert fetched.get(field) == created[field], (
                f"ProductModel.{field}: the single read returned "
                f"{fetched.get(field)!r} where the create returned "
                f"{created[field]!r}"
            )


class TestMoldRegistrationRead:
    """GET /molds/{mold_id} on a tool no cycle has touched yet."""

    def test_get_mold_shows_zero_counter_available_and_null_predecessor(
        self, api, admin_headers
    ):
        """A freshly registered tool reads back with all three derived fields at
        their declared defaults.

        PRD.md section 3.1: "When it is registered, `cycles_since_service`
        starts at 0 and `status` at `AVAILABLE`."

        PRD.md section 2.8, Mold: "and the optional `replaces_mold_id` (default
        null; when present it must resolve or `ERR_MOLD_NOT_FOUND`, must have
        `status` `RETIRED` or `ERR_MOLD_NOT_AVAILABLE`, and must reference a
        tool of the same `product_model_id` — and must not be the tool itself —
        or `ERR_INVALID_MOLD_REPLACEMENT`)."

        PRD.md section 2.8, Mold: "`nominal_charge_kg` (required, greater than
        zero, three decimals, and must equal the model's `nominal_charge_kg`
        multiplied by `cavity_count` and rounded to three decimals, otherwise
        `ERR_VALIDATION`)."

        Design: Corner/entities/ent_get_mold_by_id_returns_stored_tool_with_counter_zero
        """
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        model = get_success_data(
            api.create_product_model(
                product_model_payload(
                    model_code="PM-CD-GET",
                    size_class="MID",
                    nominal_charge_kg=24.0,
                ),
                admin_headers,
            )
        )
        created = validate_success(
            api.create_mold(
                mold_payload(
                    model["id"],
                    mold_code="MLD-CD-GET",
                    size_class="MID",
                    cavity_count=1,
                    nominal_charge_kg=24.0,
                    service_interval_cycles=10,
                ),
                admin_headers,
            ),
            expected_status=201,
        )

        mold = validate_success(api.get_mold(created["id"], admin_headers))

        assert_common_fields(mold, "Mold")
        assert mold["mold_code"] == "MLD-CD-GET"
        assert mold["product_model_id"] == model["id"]
        assert mold["size_class"] == "MID"
        assert mold["cavity_count"] == 1
        assert dec(mold["nominal_charge_kg"]) == dec("24.000")
        assert mold["service_interval_cycles"] == 10
        assert mold["cycles_since_service"] == 0
        assert mold["status"] == "AVAILABLE"
        assert mold.get("replaces_mold_id") is None
        assert mold["version"] == 1


class TestUnknownIdentifierResolution:
    """One existence rule serves reads, action endpoints and computed reads."""

    def test_unknown_path_id_is_404_on_reads_actions_and_computed_reads(
        self, api, admin_headers, planner_headers
    ):
        """A well-formed identifier that matches no row is a 404 everywhere.

        PRD.md section 2.7: "**Existence** — path identifiers first, then body
        foreign keys, each reported with its entity-specific not-found code
        where one exists and with `ERR_RESOURCE_NOT_FOUND` otherwise."

        PRD.md section 2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error."

        Design: Corner/entities/ent_get_nonexistent_resin_lot_returns_resource_not_found
        """
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        get_success_data(
            api.create_warehouse(
                warehouse_payload(site_code="WHS-CD-404"), planner_headers
            )
        )

        lot_read = api.get_resin_lot(UNKNOWN_ID, admin_headers)
        assert lot_read.status_code == 404
        validate_error_is_one_of(
            lot_read,
            [ApiErrorId.RESIN_LOT_NOT_FOUND, ApiErrorId.RESOURCE_NOT_FOUND],
        )

        mold_read = api.get_mold(UNKNOWN_ID, admin_headers)
        assert mold_read.status_code == 404
        validate_error_is_one_of(
            mold_read, [ApiErrorId.MOLD_NOT_FOUND, ApiErrorId.RESOURCE_NOT_FOUND]
        )

        retire = api.retire_mold(
            UNKNOWN_ID, retire_mold_payload("CD-404-PROBE"), admin_headers
        )
        assert retire.status_code == 404
        validate_error_is_one_of(
            retire, [ApiErrorId.MOLD_NOT_FOUND, ApiErrorId.RESOURCE_NOT_FOUND]
        )
        listed, meta = validate_paginated(api.list_molds(None, admin_headers))
        assert all(row["id"] != UNKNOWN_ID for row in listed), (
            "a refused retire must not have created a Mold row"
        )

        summary = api.get_warehouse_footprint_summary(UNKNOWN_ID, planner_headers)
        assert summary.status_code == 404
        validate_error_is_one_of(
            summary,
            [ApiErrorId.WAREHOUSE_NOT_FOUND, ApiErrorId.RESOURCE_NOT_FOUND],
        )

        for refused in (lot_read, mold_read, retire, summary):
            body = refused.json()
            assert body["response_type"] == "error"
            assert body["data"]["error_id"]

    def test_a_real_identifier_on_the_same_computed_route_still_returns_200(
        self, api, admin_headers, planner_headers
    ):
        """The 404s above are identifier-specific, not route-wide.

        PRD.md section 4, `GET /warehouses/{warehouse_id}/footprint-summary`:
        "Computed read: per-zone committed cube, remaining cube, anchor counts
        per product model, and the site's posture, so a test can observe the
        nesting arithmetic without recomputing it."

        Design: Corner/entities/ent_get_nonexistent_resin_lot_returns_resource_not_found
        """
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        warehouse = get_success_data(
            api.create_warehouse(
                warehouse_payload(site_code="WHS-CD-404-OK"), planner_headers
            )
        )

        summary = validate_success(
            api.get_warehouse_footprint_summary(warehouse["id"], planner_headers)
        )

        assert summary["warehouse_id"] == warehouse["id"]


class TestResponseEnvelope:
    """Both halves of the section 2.2 envelope, on one resource."""

    def test_success_envelope_carries_meta_response_type_and_data(
        self, api, admin_headers
    ):
        """A 201 create answers with meta, response_type "object" and data.

        PRD.md section 2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        PRD.md section 2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        PRD.md section 2.2: "The `data` field contains the resource object or an
        array of resource objects."

        Design: Corner/endpoints/ep_response_envelope_success_and_error_shapes_on_one_resource
        """
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)

        response = api.create_product_model(
            product_model_payload(model_code="PM-CD-KM"), admin_headers
        )

        assert response.status_code == 201
        body = response.json()
        assert set(body) == {"meta", "response_type", "data"}, (
            f"the success envelope carries exactly meta, response_type and "
            f"data; got {sorted(body)}"
        )
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]
        data = validate_success(response, expected_status=201)
        assert data["model_code"] == "PM-CD-KM"
        assert data["version"] == 1
        assert_money_equals(
            data["warranty_reserve_cents"], 500000, "warranty_reserve_cents"
        )
        assert_money_equals(data["warranty_paid_cents"], 0, "warranty_paid_cents")

    def test_error_envelope_puts_error_id_inside_data(self, api, admin_headers):
        """A 404 read answers with response_type "error" and error_id in data.

        PRD.md section 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        PRD.md section 2.2: "The `message` provides a human-readable explanation
        of what went wrong."

        Design: Corner/endpoints/ep_response_envelope_success_and_error_shapes_on_one_resource
        """
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)

        response = api.get_product_model("pm-cd-does-not-exist", admin_headers)

        assert response.status_code == 404
        body = response.json()
        assert set(body) == {"meta", "response_type", "data"}, (
            f"the error envelope carries exactly meta, response_type and data; "
            f"got {sorted(body)}"
        )
        assert body["response_type"] == "error"
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip()
        validate_error_is_one_of(
            response,
            [ApiErrorId.PRODUCT_MODEL_NOT_FOUND, ApiErrorId.RESOURCE_NOT_FOUND],
        )
