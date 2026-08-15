"""Serving-size determination: market rounding variants, label-mode bands,
the single-serving override, and the duplicate / market-mismatch guards."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_racc_assignment,
    create_client,
    create_label_version_payload,
    create_product,
    create_racc_assignment,
    create_racc_assignment_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["label_analyst_headers"]


def _cereal_product(client):
    return create_product(client, name="Cereal", product_category="CEREAL",
                          net_weight_g=120, total_surface_area_sq_in=50.0,
                          pdp_area_sq_in=10.0, household_unit_name="piece",
                          household_unit_weight_g=13)


class TestMarketRoundingVariants:
    def test_us_household_first_rounding(self, api):
        """PRD §3.5: "Otherwise the `US_FDA` path works household-first: the
        raw unit count is `racc_g` divided by `household_unit_weight_g` — a
        missing or zero unit weight is rejected with
        `ERR_SERVING_SIZE_UNRESOLVABLE` — and `serving_household_units` is
        that raw count rounded to the nearest half unit with halves rounding
        up (double the raw count, add one half, truncate down to a whole
        number, then halve it); `serving_size_g` is then the rounded units
        multiplied by the unit weight, rounded half-up to two decimal places."
        PRD §3.5: "Finally, `servings_per_container` for non-single-serving
        packages divides `net_weight_g` by the computed `serving_size_g` and
        rounds the count by band: below 2 it declares 1; at least 2 and at
        most 5 it rounds to the nearest half with halves up; above 5 it rounds
        to the nearest whole number with halves up."

        Design: Difficulty/dual_variant_calc/serving_rounding_us_vs_cfia
        """
        client = create_client()
        product = _cereal_product(client)
        us = create_racc_assignment(product["id"], market_code="US_FDA")
        assert_racc_assignment(us)
        assert us["racc_g"] == 40, "CEREAL reference amount"
        assert us["serving_household_units"] == pytest.approx(3.0), (
            "40 / 13 = 3.0769, nearest 0.5 unit with halves up"
        )
        assert us["serving_size_g"] == pytest.approx(39.0, abs=0.005), (
            "3.0 units x 13 g"
        )
        assert us["servings_per_container"] == pytest.approx(3.0), (
            "120 / 39.0 = 3.0769, in the [2, 5] band, nearest 0.5"
        )
        assert us["label_mode"] == "DUAL_COLUMN", "ratio 120/40 == 3.0 <= 3.0"

    def test_ca_metric_first_rounding(self, api):
        """PRD §3.5: "The `CA_CFIA` path works metric-first: `serving_size_g`
        is the reference amount rounded to the nearest 5 grams when `racc_g`
        is at least 50 grams, or to the nearest 1 gram below that, halves
        rounding up in both cases; `serving_household_units` is then derived
        as the serving size divided by `household_unit_weight_g`, rounded
        half-up to two decimal places, with the same missing-or-zero guard
        producing `ERR_SERVING_SIZE_UNRESOLVABLE`."
        PRD §2.9: "The markets diverge in three places, each detailed where it
        applies: serving-size rounding is household-measure-first under
        `US_FDA` but metric-first under `CA_CFIA`; the claim types
        `SUGAR_FREE` and `LOW_CALORIE` are unregulated in the Canadian market;
        and a variant destined for the other market may carry a localized
        allergen statement."

        Design: Difficulty/dual_variant_calc/serving_rounding_us_vs_cfia
        """
        client = create_client(home_market_code="CA_CFIA")
        product = _cereal_product(client)
        ca = create_racc_assignment(product["id"], market_code="CA_CFIA")
        assert_racc_assignment(ca)
        assert ca["racc_g"] == 40
        assert ca["serving_size_g"] == pytest.approx(40.0, abs=0.005), (
            "racc < 50 rounds to the nearest 1 g"
        )
        assert ca["serving_household_units"] == pytest.approx(3.08, abs=0.005), (
            "40 / 13 = 3.0769, rounded half-up to 2dp"
        )
        assert ca["servings_per_container"] == pytest.approx(3.0), (
            "120 / 40.0 = 3.0"
        )
        assert ca["label_mode"] == "DUAL_COLUMN"


class TestModeEvaluationOrder:
    def test_single_serving_override_replaces_racc_derivation(self, api):
        """PRD §3.5: "Second, the package ratio is computed as `net_weight_g`
        divided by `racc_g` — deliberately against the reference amount, not
        against any serving size, because the serving size is what is being
        derived. Third, the ratio selects the `label_mode`: below 2.0 the
        package is `SINGLE_SERVING`; at least 2.0 and at most 3.0 it is
        `DUAL_COLUMN`; above 3.0 it is `STANDARD`."
        PRD §3.5: "A `SINGLE_SERVING` package declares `serving_size_g` equal
        to the whole `net_weight_g`, exactly 1 `serving_household_units`, and
        1 `servings_per_container`, with no household-measure data required."

        Design: Difficulty/combinatorial_formula/serving_mode_evaluation_order
        """
        client = create_client()
        product = create_product(client, name="Cookie Single", net_weight_g=100)
        ra = create_racc_assignment(product["id"], market_code="US_FDA")
        assert ra["label_mode"] == "SINGLE_SERVING", (
            "ratio 100/55 = 1.818 < 2.0, evaluated against the RACC before "
            "any serving size exists"
        )
        assert ra["serving_size_g"] == pytest.approx(100.0), (
            "single-serving override: serving is the whole net contents"
        )
        assert ra["serving_household_units"] == pytest.approx(1)
        assert ra["servings_per_container"] == pytest.approx(1)

    def test_standard_mode_keeps_racc_derivation(self, api):
        """PRD §3.5: "Third, the ratio selects the `label_mode`: below 2.0 the
        package is `SINGLE_SERVING`; at least 2.0 and at most 3.0 it is
        `DUAL_COLUMN`; above 3.0 it is `STANDARD`."
        PRD §3.5: "Otherwise the `US_FDA` path works household-first: the raw
        unit count is `racc_g` divided by `household_unit_weight_g` — a
        missing or zero unit weight is rejected with
        `ERR_SERVING_SIZE_UNRESOLVABLE` — and `serving_household_units` is
        that raw count rounded to the nearest half unit with halves rounding
        up (double the raw count, add one half, truncate down to a whole
        number, then halve it); `serving_size_g` is then the rounded units
        multiplied by the unit weight, rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/serving_mode_evaluation_order
        """
        client = create_client()
        product = create_product(client, name="Cookie Family", net_weight_g=330)
        ra = create_racc_assignment(product["id"], market_code="US_FDA")
        assert ra["label_mode"] == "STANDARD", "ratio 330/55 = 6.0 > 3.0"
        assert ra["serving_household_units"] == pytest.approx(2.0), (
            "55 / 27.5 = 2.0 units"
        )
        assert ra["serving_size_g"] == pytest.approx(55.0, abs=0.005)
        assert ra["servings_per_container"] == pytest.approx(6.0), (
            "330 / 55.0 = 6.0, above 5 rounds to the nearest whole number"
        )


class TestDualColumnBoundary:
    def test_exact_ratio_2_is_dual_column(self, api):
        """PRD §3.5: "Third, the ratio selects the `label_mode`: below 2.0 the
        package is `SINGLE_SERVING`; at least 2.0 and at most 3.0 it is
        `DUAL_COLUMN`; above 3.0 it is `STANDARD`."
        PRD §2.5: "Format-compliance tier boundaries and serving-size package
        ratios are compared as exact decimals, without tolerance."

        Design: Difficulty/boundary_precision_check/boundary_dual_column_at_exact_200pct
        """
        client = create_client()
        product = create_product(client, name="Cookie 110", net_weight_g=110)
        ra = create_racc_assignment(product["id"], market_code="US_FDA")
        assert ra["label_mode"] == "DUAL_COLUMN", (
            "ratio exactly 2.0 satisfies 2.0 <= r <= 3.0"
        )
        assert ra["serving_size_g"] == pytest.approx(55.0, abs=0.005), (
            "55 / 27.5 = 2.0 units, x 27.5 g"
        )
        assert ra["servings_per_container"] == pytest.approx(2.0)

    def test_just_below_ratio_2_is_single_serving(self, api):
        """PRD §3.5: "Third, the ratio selects the `label_mode`: below 2.0 the
        package is `SINGLE_SERVING`; at least 2.0 and at most 3.0 it is
        `DUAL_COLUMN`; above 3.0 it is `STANDARD`."
        PRD §3.5: "A `SINGLE_SERVING` package declares `serving_size_g` equal
        to the whole `net_weight_g`, exactly 1 `serving_household_units`, and
        1 `servings_per_container`, with no household-measure data required."

        Design: Difficulty/boundary_precision_check/boundary_dual_column_at_exact_200pct
        """
        client = create_client()
        product = create_product(client, name="Cookie 109", net_weight_g=109.9)
        ra = create_racc_assignment(product["id"], market_code="US_FDA")
        assert ra["label_mode"] == "SINGLE_SERVING", "ratio 1.998 < 2.0"
        assert ra["serving_size_g"] == pytest.approx(109.9)
        assert ra["servings_per_container"] == pytest.approx(1)


class TestAssignmentGuards:
    def test_serving_unresolvable_without_unit_weight(self, api):
        """PRD §3.5: "Otherwise the `US_FDA` path works household-first: the
        raw unit count is `racc_g` divided by `household_unit_weight_g` — a
        missing or zero unit weight is rejected with
        `ERR_SERVING_SIZE_UNRESOLVABLE` — and `serving_household_units` is
        that raw count rounded to the nearest half unit with halves rounding
        up (double the raw count, add one half, truncate down to a whole
        number, then halve it); `serving_size_g` is then the rounded units
        multiplied by the unit weight, rounded half-up to two decimal places."
        PRD §3.1: "Both may be omitted at registration, but serving-size
        determination for any package that is not a single-serving package
        requires `household_unit_weight_g` to be present and positive, and the
        American panel conventionally expresses the serving in
        `household_unit_name` terms."

        Design: Corner/calculations/calc_serving_unresolvable_without_unit_weight
        """
        client = create_client()
        product = create_product(client, include_household=False)
        resp = api.create_racc_assignment(
            product["id"], create_racc_assignment_payload(market_code="US_FDA"),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_SERVING_SIZE_UNRESOLVABLE,
                       expected_status=422)

    def test_duplicate_racc_assignment_rejected(self, api):
        """PRD §3.5: "A `LabelAnalyst` requests a **RaccAssignment** for a
        product by naming the target `market_code`, and at most one assignment
        may exist per product and market — a second request for the same pair
        is rejected with `ERR_RACC_ALREADY_ASSIGNED`."

        Design: Corner/validations/val_duplicate_racc_assignment_rejected
        """
        client = create_client()
        product = create_product(client)
        create_racc_assignment(product["id"], market_code="US_FDA")
        resp = api.create_racc_assignment(
            product["id"], create_racc_assignment_payload(market_code="US_FDA"),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_RACC_ALREADY_ASSIGNED,
                       expected_status=409)

    def test_racc_market_mismatch_rejected(self, api):
        """PRD §3.6: "The pinned assignment must belong to the same product
        and target the same market, failing which creation is rejected with
        `ERR_RACC_MARKET_MISMATCH` — while an assignment id that does not
        exist at all fails earlier as `ERR_NOT_FOUND`."

        Design: Corner/validations/val_racc_market_mismatch_rejected
        """
        client = create_client()
        product = create_product(client)
        racc_ca = create_racc_assignment(product["id"], market_code="CA_CFIA")
        payload = create_label_version_payload(
            racc_ca["id"], product["version"],
            "Wafers", "Contains: None.",
            market_code="US_FDA",
        )
        resp = api.create_label_version(product["id"], payload, ANALYST)
        validate_error(resp, ApiErrorId.ERR_RACC_MARKET_MISMATCH,
                       expected_status=422)
