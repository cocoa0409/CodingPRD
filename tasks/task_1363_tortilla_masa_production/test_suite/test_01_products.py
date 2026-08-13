"""Products: creation defaults, declared-weight rounding, catalog errors,
discontinue gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_product,
    create_line,
    create_product,
    create_product_payload,
    create_run,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
MILLER = TEST_USERS["miller_operator_headers"]


class TestProductCreation:
    def test_creation_applies_defaults_and_computed_fields(self, api):
        """PRD §3.4: "`weight_tolerance_pct` defaults to 2.0 when omitted and must
        be greater than zero." and "`shelf_life_days` is 5 when `preservative_system`
        is `NONE`, 20 when it is `PROPIONATE`, and 45 when it is `FUMARIC_ACID`."
        and "`declared_pack_net_g` is `unit_weight_g` multiplied by `count_per_pack`,
        rounded half-up to one decimal place, computed per-pack first" and "A new
        product enters in `product_status` `ACTIVE`."
        25 g x 24 -> declared_pack_net_g 600.0; NONE -> 5 days shelf life.

        Design: Corner/entities/entities_product_defaults_and_computed_fields
        """
        payload = create_product_payload(
            sku_code="E-DEF",
            diameter_in="D10",
            count_per_pack=24,
            packs_per_case=6,
            unit_weight_g=25,
            channel="FOODSERVICE",
            preservative_system="NONE",
            allergen_class="CORN_ONLY",
        )
        del payload["weight_tolerance_pct"]  # omitted -> server default applies
        product = validate_success(api.create_product(payload, PM), 201)
        assert_product(product)
        assert product["weight_tolerance_pct"] == pytest.approx(2.0), (
            "omitted weight_tolerance_pct must default to 2.0"
        )
        assert product["shelf_life_days"] == 5
        assert product["declared_pack_net_g"] == pytest.approx(600.0)
        assert product["product_status"] == "ACTIVE"
        assert isinstance(product["version"], int)

    def test_get_missing_product_returns_not_found(self, api):
        """PRD §2.9: "Existence — path ids and foreign-key references resolve
        (`ERR_NOT_FOUND`)." A well-formed but absent product id yields 404.

        Design: Corner/entities/entities_get_nonexistent_returns_not_found
        """
        validate_error(
            api.get_product(NON_EXISTENT_UUID, PM), ApiErrorId.ERR_NOT_FOUND
        )

    def test_create_rejects_undeclared_diameter_enum(self, api):
        """PRD §2.9: "Request shape and enums — required fields present, types
        correct, declared enum members only (`ERR_INVALID_REQUEST`,
        `ERR_INVALID_ENUM`, `ERR_VALIDATION` for numeric semantic ranges such as
        `delivered_cases` not exceeding `allocated_cases`, `lime_pct` inside its
        band, `cook_minutes` at least 30, `steep_target_hours` at least 8)."
        PRD §3.4 declares diameter_in members "(`D6`, `D8`, `D10`, or `D12`
        inches)" — D7 is not among them.

        Design: Corner/entities/entities_invalid_enum_rejected
        """
        validate_error(
            api.create_product(
                create_product_payload(sku_code="E-ENUM", diameter_in="D7"), PM
            ),
            ApiErrorId.ERR_INVALID_ENUM,
        )

    def test_create_missing_sku_code_rejected(self, api):
        """PRD §2.9: "Request shape and enums — required fields present, types
        correct, declared enum members only (`ERR_INVALID_REQUEST`,
        `ERR_INVALID_ENUM`, `ERR_VALIDATION` for numeric semantic ranges such as
        `delivered_cases` not exceeding `allocated_cases`, `lime_pct` inside its
        band, `cook_minutes` at least 30, `steep_target_hours` at least 8)."
        Omitting the required sku_code field fails the request-shape check.

        Design: Corner/entities/entities_product_create_missing_required_sku
        """
        payload = create_product_payload()
        del payload["sku_code"]
        validate_error(api.create_product(payload, PM), ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_sku_code_rejected(self, api):
        """PRD §3.4: "The `sku_code` must be unique; a duplicate is rejected with
        `ERR_DUPLICATE_CODE`."

        Design: Corner/entities/entities_duplicate_sku_rejected
        """
        validate_success(
            api.create_product(create_product_payload(sku_code="DUP-1"), PM), 201
        )
        validate_error(
            api.create_product(
                create_product_payload(
                    sku_code="DUP-1",
                    diameter_in="D8",
                    channel="FOODSERVICE",
                    preservative_system="NONE",
                    allergen_class="SOY_BLENDED",
                ),
                PM,
            ),
            ApiErrorId.ERR_DUPLICATE_CODE,
        )


class TestDeclaredWeightRoundingOrder:
    def test_pack_weight_rounds_half_up_per_pack_first(self, api):
        """PRD §3.4: "`declared_pack_net_g` is `unit_weight_g` multiplied by
        `count_per_pack`, rounded half-up to one decimal place, computed per-pack
        first; `declared_case_net_g` is then `declared_pack_net_g` multiplied by
        `packs_per_case`, rounded half-up to one decimal place." 29.97 g x 12 =
        359.64 -> 359.6 after per-pack-first half-up rounding.

        Design: Difficulty/combinatorial_formula/declared_weight_per_pack_rounding_order
        """
        product = validate_success(
            api.create_product(
                create_product_payload(
                    sku_code="RND-8-12",
                    diameter_in="D8",
                    count_per_pack=12,
                    packs_per_case=10,
                    unit_weight_g=29.97,
                    channel="FOODSERVICE",
                    preservative_system="FUMARIC_ACID",
                    allergen_class="CORN_ONLY",
                ),
                PM,
            ),
            201,
        )
        assert product["declared_pack_net_g"] == pytest.approx(359.6, abs=1e-9), (
            "round_half_up(29.97 x 12, 1) must be 359.6"
        )

    def test_case_weight_uses_rounded_pack_value_not_raw_product(self, api):
        """PRD §3.4: "Rounding the raw per-case product in one step is forbidden —
        the per-pack-then-per-case order is normative." and "`shelf_life_days` is
        5 when `preservative_system` is `NONE`, 20 when it is `PROPIONATE`, and 45
        when it is `FUMARIC_ACID`." 359.6 x 10 = 3596.0 (the naive one-step order
        would give 3596.4); FUMARIC_ACID -> 45 days.

        Design: Difficulty/combinatorial_formula/declared_weight_per_pack_rounding_order
        """
        product = validate_success(
            api.create_product(
                create_product_payload(
                    sku_code="RND-8-12",
                    diameter_in="D8",
                    count_per_pack=12,
                    packs_per_case=10,
                    unit_weight_g=29.97,
                    channel="FOODSERVICE",
                    preservative_system="FUMARIC_ACID",
                    allergen_class="CORN_ONLY",
                ),
                PM,
            ),
            201,
        )
        assert product["declared_case_net_g"] == pytest.approx(3596.0, abs=1e-9), (
            "declared_case_net_g must be computed from the rounded pack weight"
        )
        assert product["shelf_life_days"] == 45


class TestProductDiscontinueGates:
    def test_discontinue_blocked_by_planned_run(self, api):
        """PRD §3.4: "The product must currently be `ACTIVE` — otherwise
        `ERR_PRODUCT_DISCONTINUED` — and no production run naming this product may
        exist in `PLANNED`, `SCHEDULED`, or `IN_PROGRESS` — otherwise
        `ERR_PRODUCT_IN_USE`."

        Design: Corner/endpoints/ep_discontinue_product_in_use_rejected
        """
        product = create_product(sku_code="C-PIU")
        line = create_line(line_code="L-PIU")
        create_run(
            product["id"],
            line["id"],
            planned_cases=10,
            start_at="2026-08-02T10:00:00Z",
            end_at="2026-08-02T11:00:00Z",
        )
        validate_error(
            api.discontinue_product(product["id"], PM), ApiErrorId.ERR_PRODUCT_IN_USE
        )
        after = validate_success(api.get_product(product["id"], PM))
        assert after["product_status"] == "ACTIVE"

    def test_run_create_on_discontinued_product_rejected(self, api):
        """PRD §3.5: "The referenced product must be `ACTIVE` — a `DISCONTINUED`
        product yields `ERR_PRODUCT_DISCONTINUED`."

        Design: Corner/endpoints/ep_run_create_on_discontinued_product_rejected
        """
        product = create_product(sku_code="C-DISC")
        discontinued = validate_success(api.discontinue_product(product["id"], PM))
        assert discontinued["product_status"] == "DISCONTINUED"
        line = create_line(line_code="L-DISC")
        validate_error(
            api.create_run(
                {
                    "product_id": product["id"],
                    "line_id": line["id"],
                    "planned_cases": 10,
                    "start_at": "2026-08-02T10:00:00Z",
                    "end_at": "2026-08-02T11:00:00Z",
                    "expected_line_version": line["version"],
                },
                TEST_USERS["line_scheduler_headers"],
            ),
            ApiErrorId.ERR_PRODUCT_DISCONTINUED,
        )
