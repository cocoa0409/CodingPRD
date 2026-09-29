"""Paging and filtering the two reference-data collections.

PRD.md section 2.3 gives every collection read the same two query parameters
and the same four `meta` fields, so the mould list and the hull-model list are
paged here against a known row count and then narrowed by the filters each
endpoint declares.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT_UTC,
    DEFAULT_PAGE_LIMIT,
    assert_pagination_meta,
    get_success_data,
    mold_payload,
    product_model_payload,
    set_clock,
    validate_error,
    validate_paginated,
)

KAYAK_MID = dict(
    model_code="PM-CD-KM",
    hull_type="KAYAK",
    size_class="MID",
    resin_grade="HDPE_LINEAR",
    seasonal_family="PADDLE",
    warranty_basis="PRO_RATA_AGE",
    nominal_charge_kg=12.0,
)
KAYAK_COMPACT = dict(
    model_code="PM-CD-K2",
    hull_type="KAYAK",
    size_class="COMPACT",
    resin_grade="HDPE_LINEAR",
    seasonal_family="PADDLE",
    warranty_basis="FLAT_SCHEDULE",
    nominal_charge_kg=9.0,
    min_cooling_minutes=25,
    target_wall_thickness_mm=5.0,
    wall_thickness_min_mm=4.0,
    impact_test_min_joules=80.0,
    gross_cube_m3=1.5,
    unit_weight_kg=18.0,
    msrp_cents=120000,
    initial_warranty_reserve_cents=300000,
)
CANOE_TANDEM = dict(
    model_code="PM-CD-T3",
    hull_type="CANOE",
    size_class="TANDEM",
    resin_grade="MDPE",
    seasonal_family="DECK",
    warranty_basis="FLAT_SCHEDULE",
    master_color_code="GRAPHITE",
    max_color_delta_e=2.0,
    required_additive_package_code="UV20",
    max_regrind_pct=20.0,
    min_melt_index_g10min=3.0,
    max_melt_index_g10min=7.0,
    nominal_charge_kg=30.0,
    charge_tolerance_pct=4.0,
    min_cooling_minutes=45,
    target_wall_thickness_mm=8.0,
    wall_thickness_min_mm=6.5,
    wall_cv_max_pct=10.0,
    impact_test_min_joules=140.0,
    gross_cube_m3=6.0,
    nest_factor=0.7,
    unit_weight_kg=90.0,
    msrp_cents=640000,
    initial_warranty_reserve_cents=900000,
)


def _p3_three_models(api, admin_headers):
    """Create the three hull models both list groups below page over."""
    set_clock(CLOCK_DEFAULT_UTC, admin_headers)
    rows = []
    for overrides in (KAYAK_MID, KAYAK_COMPACT, CANOE_TANDEM):
        rows.append(
            get_success_data(
                api.create_product_model(
                    product_model_payload(**overrides), admin_headers
                )
            )
        )
    return rows


class TestMoldListPagination:
    """GET /molds pages and filters three tools across two hull models."""

    @staticmethod
    def _three_molds(api, admin_headers):
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        model_a = get_success_data(
            api.create_product_model(
                product_model_payload(
                    model_code="PM-CD-LIST-A",
                    hull_type="KAYAK",
                    size_class="MID",
                    nominal_charge_kg=24.0,
                ),
                admin_headers,
            )
        )
        model_b = get_success_data(
            api.create_product_model(
                product_model_payload(
                    model_code="PM-CD-LIST-B",
                    hull_type="CANOE",
                    size_class="TANDEM",
                    resin_grade="MDPE",
                    master_color_code="GRANITE",
                    nominal_charge_kg=30.0,
                    target_wall_thickness_mm=7.0,
                    wall_thickness_min_mm=5.0,
                    impact_test_min_joules=110.0,
                    gross_cube_m3=3.5,
                    nest_factor=0.6,
                    unit_weight_kg=41.0,
                    msrp_cents=265000,
                    warranty_basis="FLAT_SCHEDULE",
                    initial_warranty_reserve_cents=400000,
                ),
                admin_headers,
            )
        )
        molds = [
            get_success_data(
                api.create_mold(
                    mold_payload(
                        model_a["id"],
                        mold_code="MLD-CD-L1",
                        size_class="MID",
                        cavity_count=1,
                        nominal_charge_kg=24.0,
                    ),
                    admin_headers,
                )
            ),
            get_success_data(
                api.create_mold(
                    mold_payload(
                        model_a["id"],
                        mold_code="MLD-CD-L2",
                        size_class="MID",
                        cavity_count=2,
                        nominal_charge_kg=48.0,
                    ),
                    admin_headers,
                )
            ),
            get_success_data(
                api.create_mold(
                    mold_payload(
                        model_b["id"],
                        mold_code="MLD-CD-L3",
                        size_class="TANDEM",
                        cavity_count=1,
                        nominal_charge_kg=30.0,
                    ),
                    admin_headers,
                )
            ),
        ]
        return model_a, model_b, molds

    def test_two_page_window_reports_total_count_and_has_more(
        self, api, admin_headers
    ):
        """Three tools split across two pages of two, with no row repeated.

        PRD.md section 2.3: "List responses populate `limit`, `offset`,
        `total_count` and `has_more` in the `meta` object."

        PRD.md section 2.3: "`total_count` is the number of rows matching the
        filters before pagination is applied, and `has_more` is true exactly
        when `offset` plus the number of returned rows is strictly less than
        `total_count`."

        Design: Corner/entities/ent_list_molds_pagination_total_count_and_has_more
        """
        _model_a, _model_b, molds = self._three_molds(api, admin_headers)
        expected_ids = {mold["id"] for mold in molds}

        page_one_response = api.list_molds({"limit": 2, "offset": 0}, admin_headers)
        assert page_one_response.json()["response_type"] == "array"
        page_one, meta_one = validate_paginated(page_one_response)
        assert len(page_one) == 2
        assert_pagination_meta(meta_one, 3, 2, 0)
        assert meta_one["has_more"] is True

        page_two, meta_two = validate_paginated(
            api.list_molds({"limit": 2, "offset": 2}, admin_headers)
        )
        assert len(page_two) == 1
        assert_pagination_meta(meta_two, 3, 2, 2)
        assert meta_two["has_more"] is False

        seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
        assert len(seen) == len(set(seen)), (
            f"the two pages must not repeat a row; got {seen}"
        )
        assert set(seen) == expected_ids

    def test_unparameterised_list_uses_the_declared_default_limit(
        self, api, admin_headers
    ):
        """An omitted `limit` falls back to 10, not to "every row".

        PRD.md section 2.3: "`limit` bounds the page size; it defaults to 10,
        must be at least 1 and at most 100, and a value outside that range is
        rejected with `ERR_VALIDATION` (HTTP 422)."

        PRD.md section 2.3: "`offset` is the zero-based index of the first row
        returned; it defaults to 0 and must not be negative."

        Design: Corner/entities/ent_list_molds_pagination_total_count_and_has_more
        """
        _model_a, _model_b, molds = self._three_molds(api, admin_headers)

        rows, meta = validate_paginated(api.list_molds(None, admin_headers))

        assert len(rows) == 3
        assert_pagination_meta(meta, 3, DEFAULT_PAGE_LIMIT, 0)
        assert meta["limit"] == 10
        assert meta["has_more"] is False
        assert {row["id"] for row in rows} == {mold["id"] for mold in molds}

    def test_product_model_filter_narrows_total_count_to_the_matched_set(
        self, api, admin_headers
    ):
        """`total_count` counts the filtered set rather than the whole table.

        PRD.md section 3.1: "Tools are listed with optional `product_model_id`,
        `replaces_mold_id`, `status` and `size_class` filters, so the
        replacement chain is traversable in both directions."

        PRD.md section 2.3: "Filter parameters on list endpoints are exact-match
        and are combined with logical AND."

        Design: Corner/entities/ent_list_molds_pagination_total_count_and_has_more
        """
        _model_a, model_b, molds = self._three_molds(api, admin_headers)

        rows, meta = validate_paginated(
            api.list_molds({"product_model_id": model_b["id"]}, admin_headers)
        )

        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["id"] == molds[2]["id"]

    def test_limit_below_the_declared_floor_is_refused(self, api, admin_headers):
        """`limit=0` is outside the declared 1..100 band.

        PRD.md section 2.3: "`limit` bounds the page size; it defaults to 10,
        must be at least 1 and at most 100, and a value outside that range is
        rejected with `ERR_VALIDATION` (HTTP 422)."

        Design: Corner/entities/ent_list_molds_pagination_total_count_and_has_more
        """
        self._three_molds(api, admin_headers)

        refused = api.list_molds({"limit": 0}, admin_headers)

        validate_error(refused, ApiErrorId.VALIDATION, 422)


class TestProductModelListPagination:
    """GET /product-models over exactly three rows."""

    def test_offset_window_walks_the_three_rows(self, api, admin_headers):
        """limit=2 with offset 0 then 2 covers every row exactly once.

        PRD.md section 2.3: "`total_count` is the number of rows matching the
        filters before pagination is applied, and `has_more` is true exactly
        when `offset` plus the number of returned rows is strictly less than
        `total_count`."

        PRD.md section 2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/endpoints/ep_product_model_list_pagination_defaults_and_offset_window
        """
        models = _p3_three_models(api, admin_headers)

        first_response = api.list_product_models(
            {"limit": 2, "offset": 0}, admin_headers
        )
        assert first_response.status_code == 200
        assert first_response.json()["response_type"] == "array"
        first, first_meta = validate_paginated(first_response)
        assert len(first) == 2
        assert_pagination_meta(first_meta, 3, 2, 0)
        assert first_meta["has_more"] is True

        second, second_meta = validate_paginated(
            api.list_product_models({"limit": 2, "offset": 2}, admin_headers)
        )
        assert len(second) == 1
        assert_pagination_meta(second_meta, 3, 2, 2)
        assert second_meta["has_more"] is False

        walked = [row["id"] for row in first] + [row["id"] for row in second]
        assert len(walked) == len(set(walked))
        assert set(walked) == {model["id"] for model in models}

    def test_omitted_limit_defaults_to_ten(self, api, admin_headers):
        """With no query parameters the page reports limit 10 and offset 0.

        PRD.md section 2.3: "`limit` bounds the page size; it defaults to 10,
        must be at least 1 and at most 100, and a value outside that range is
        rejected with `ERR_VALIDATION` (HTTP 422)."

        Design: Corner/endpoints/ep_product_model_list_pagination_defaults_and_offset_window
        """
        models = _p3_three_models(api, admin_headers)

        rows, meta = validate_paginated(api.list_product_models(None, admin_headers))

        assert_pagination_meta(meta, 3, DEFAULT_PAGE_LIMIT, 0)
        assert meta["limit"] == 10
        assert meta["has_more"] is False
        assert len(rows) == 3
        assert {row["id"] for row in rows} == {model["id"] for model in models}

    @pytest.mark.parametrize("limit", [0, 101])
    def test_limit_outside_the_declared_band_is_refused(
        self, api, admin_headers, limit
    ):
        """A limit under 1 or over 100 is refused rather than clamped.

        PRD.md section 2.3: "`limit` bounds the page size; it defaults to 10,
        must be at least 1 and at most 100, and a value outside that range is
        rejected with `ERR_VALIDATION` (HTTP 422)."

        Design: Corner/endpoints/ep_product_model_list_pagination_defaults_and_offset_window
        """
        _p3_three_models(api, admin_headers)

        refused = api.list_product_models({"limit": limit}, admin_headers)

        validate_error(refused, ApiErrorId.VALIDATION, 422)


class TestProductModelListFilters:
    """The declared model filters compose with logical AND."""

    def test_two_filters_are_anded_not_ored(self, api, admin_headers):
        """Each filter narrows, and the pair narrows further than either alone.

        PRD.md section 2.3: "Filter parameters on list endpoints are exact-match
        and are combined with logical AND."

        PRD.md section 3.1: "Models are listed with optional `hull_type`,
        `size_class`, `resin_grade`, `warranty_basis` and `seasonal_family`
        filters, and a single-model read exposes the live
        `warranty_reserve_cents` and `warranty_paid_cents`."

        Design: Corner/endpoints/ep_product_model_list_filters_compose_and_can_narrow_to_zero_rows
        """
        kayak_mid, kayak_compact, canoe_tandem = _p3_three_models(api, admin_headers)

        kayaks, kayak_meta = validate_paginated(
            api.list_product_models({"hull_type": "KAYAK"}, admin_headers)
        )
        assert kayak_meta["total_count"] == 2
        assert {row["id"] for row in kayaks} == {
            kayak_mid["id"],
            kayak_compact["id"],
        }

        compacts, compact_meta = validate_paginated(
            api.list_product_models({"size_class": "COMPACT"}, admin_headers)
        )
        assert compact_meta["total_count"] == 1
        assert compacts[0]["id"] == kayak_compact["id"]

        both, both_meta = validate_paginated(
            api.list_product_models(
                {"hull_type": "KAYAK", "size_class": "COMPACT"}, admin_headers
            )
        )
        assert both_meta["total_count"] == 1
        assert len(both) == 1
        assert both[0]["id"] == kayak_compact["id"]

        pair, pair_meta = validate_paginated(
            api.list_product_models(
                {"warranty_basis": "FLAT_SCHEDULE", "seasonal_family": "PADDLE"},
                admin_headers,
            )
        )
        assert pair_meta["total_count"] == 1
        assert pair[0]["id"] == kayak_compact["id"]

        grade, grade_meta = validate_paginated(
            api.list_product_models({"resin_grade": "MDPE"}, admin_headers)
        )
        assert grade_meta["total_count"] == 1
        assert grade[0]["id"] == canoe_tandem["id"]

    def test_jointly_empty_filter_pair_returns_an_empty_page(
        self, api, admin_headers
    ):
        """Two individually satisfiable filters that no row satisfies together
        give an empty page, not a 404.

        PRD.md section 2.3: "Each filter is optional; supplying an unrecognised
        value for an enum-typed filter is rejected with
        `ERR_INVALID_ENUM_VALUE` (HTTP 422), and supplying an identifier that
        matches no row is not an error — it simply yields an empty page with
        `total_count` zero."

        Design: Corner/endpoints/ep_product_model_list_filters_compose_and_can_narrow_to_zero_rows
        """
        _p3_three_models(api, admin_headers)

        response = api.list_product_models(
            {"hull_type": "KAYAK", "size_class": "TANDEM"}, admin_headers
        )

        assert response.status_code == 200
        assert response.json()["response_type"] == "array"
        rows, meta = validate_paginated(response)
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
