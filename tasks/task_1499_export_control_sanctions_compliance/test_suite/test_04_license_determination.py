"""License determination ladder, de minimis boundary, surcharge tiers, embargo/classification guards (PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_export_order,
    create_classified_product,
    create_entry,
    create_party,
    create_product,
    validate_error,
    validate_success,
)


class TestDeMinimisBoundary:
    def test_de_minimis_boundary_group_e_ten_percent(self, api, ops_headers):
        """PRD §3.4: "(6) otherwise — an EAR product with a real ECCN — the de minimis rule applies: the threshold is 10 percent for destinations in the Group E set (`CUB`, `IRN`, `PRK`, `SYR`) and 25 percent for all other destinations, and the outcome is `LICENSE_REQUIRED` only when `controlled_content_pct` is strictly greater than the threshold. A controlled-content percentage exactly equal to the threshold is `NOT_REQUIRED`."

        Design: Corner/calculations/de_minimis_boundary_group_e_ten_percent
        """
        low, _ = create_classified_product(sku="P-020", name="Chip Low",
                                           controlled_content_pct=10, unit_value_cents=100,
                                           classification_code="5A002")
        high, _ = create_classified_product(sku="P-021", name="Chip High",
                                            controlled_content_pct=11, unit_value_cents=100,
                                            classification_code="5A002")
        party = create_party(legal_name="Caspian Trade PJSC", country_code="IRN",
                             city="Tehran")

        order_low = validate_success(
            api.create_order(
                {"product_id": low["id"], "party_id": party["id"],
                 "destination_country": "IRN", "end_use": "CIVILIAN", "quantity": 1},
                ops_headers,
            ),
            201,
        )
        assert order_low["provisional_determination"] == "NOT_REQUIRED", (
            f"pct 10 == threshold 10 must be NOT_REQUIRED (strictly-greater rule), "
            f"got {order_low['provisional_determination']}"
        )

        order_high = validate_success(
            api.create_order(
                {"product_id": high["id"], "party_id": party["id"],
                 "destination_country": "IRN", "end_use": "CIVILIAN", "quantity": 1},
                ops_headers,
            ),
            201,
        )
        assert order_high["provisional_determination"] == "LICENSE_REQUIRED", (
            f"pct 11 > threshold 10 must be LICENSE_REQUIRED, "
            f"got {order_high['provisional_determination']}"
        )


class TestLadderBranches:
    def test_itar_jurisdiction_always_requires_license(self, api, ops_headers):
        """PRD §3.4: "The ladder, in strict order: (1) if the destination country matches an `ACTIVE` `EMBARGOED_COUNTRY` entry with severity `PROHIBITED`, the outcome is `PROHIBITED`; (2) else if the party's `screening_posture` is `BLOCKED`, `PROHIBITED`; (3) else if the classification's `jurisdiction` is `ITAR`, `LICENSE_REQUIRED`; (4) else if the order's `end_use` is `MILITARY`, `LICENSE_REQUIRED`; (5) else if the `classification_code` is `EAR99`, `NOT_REQUIRED`; (6) otherwise — an EAR product with a real ECCN — the de minimis rule applies: the threshold is 10 percent for destinations in the Group E set (`CUB`, `IRN`, `PRK`, `SYR`) and 25 percent for all other destinations, and the outcome is `LICENSE_REQUIRED` only when `controlled_content_pct` is strictly greater than the threshold."

        Design: Corner/calculations/itar_jurisdiction_always_requires_license
        """
        product, _ = create_classified_product(
            sku="P-022", name="Launcher Part", controlled_content_pct=0,
            unit_value_cents=5000, jurisdiction="ITAR", classification_code="XI",
            determination_basis="CJ_DETERMINATION",
        )
        party = create_party(legal_name="Royal Armouries Ltd", country_code="GBR", city="Leeds")
        order = validate_success(
            api.create_order(
                {"product_id": product["id"], "party_id": party["id"],
                 "destination_country": "GBR", "end_use": "CIVILIAN", "quantity": 1},
                ops_headers,
            ),
            201,
        )
        assert_export_order(order)
        assert order["provisional_determination"] == "LICENSE_REQUIRED", (
            f"ITAR short-circuits de minimis and end-use analysis, "
            f"got {order['provisional_determination']}"
        )

    def test_ear99_military_end_use_requires_license(self, api, ops_headers):
        """PRD §3.4: "(4) else if the order's `end_use` is `MILITARY`, `LICENSE_REQUIRED`; (5) else if the `classification_code` is `EAR99`, `NOT_REQUIRED`;"

        Design: Corner/calculations/ear99_military_end_use_requires_license
        """
        product, _ = create_classified_product(sku="P-023", name="Bolt Mil",
                                               controlled_content_pct=0, unit_value_cents=10,
                                               classification_code="EAR99")
        party = create_party(legal_name="Fort Defense LLC", country_code="POL", city="Warsaw",
                             party_type="END_USER")
        order = validate_success(
            api.create_order(
                {"product_id": product["id"], "party_id": party["id"],
                 "destination_country": "POL", "end_use": "MILITARY", "quantity": 1},
                ops_headers,
            ),
            201,
        )
        assert order["provisional_determination"] == "LICENSE_REQUIRED", (
            f"MILITARY end_use flips even EAR99 to LICENSE_REQUIRED, "
            f"got {order['provisional_determination']}"
        )


class TestSurchargeTiers:
    def test_surcharge_high_tier_at_exact_boundary(self, api, ops_headers):
        """PRD §3.4: "The compliance surcharge then applies a two-tier rate keyed **only** on `goods_value_cents`, never on the running total: 0.02 when the goods value is below 100000 cents, and 0.035 when it is 100000 cents or more — an order whose goods value lands exactly on the boundary takes the higher rate."

        Design: Corner/calculations/surcharge_high_tier_at_exact_boundary
        """
        product, _ = create_classified_product(sku="P-024", name="Press",
                                               controlled_content_pct=0, unit_value_cents=25000,
                                               classification_code="EAR99")
        party = create_party(legal_name="Vulcan Industries SA", country_code="ESP", city="Bilbao")
        order = validate_success(
            api.create_order(
                {"product_id": product["id"], "party_id": party["id"],
                 "destination_country": "ESP", "end_use": "CIVILIAN", "quantity": 4},
                ops_headers,
            ),
            201,
        )
        assert order["goods_value_cents"] == 100000
        assert order["surcharge_cents"] == 3500, (
            f"exactly 100000 takes the 0.035 tier: expected 3500, got {order['surcharge_cents']}"
        )
        assert order["total_value_cents"] == 103500

    def test_surcharge_low_tier_just_below_boundary(self, api, ops_headers):
        """PRD §3.4: "The compliance surcharge then applies a two-tier rate keyed **only** on `goods_value_cents`, never on the running total: 0.02 when the goods value is below 100000 cents, and 0.035 when it is 100000 cents or more — an order whose goods value lands exactly on the boundary takes the higher rate. The `surcharge_cents` is the goods value multiplied by the applicable tier rate, rounded to a whole cent round half up, and `total_value_cents` is the sum of `goods_value_cents` and `surcharge_cents`."

        Design: Difficulty/combinatorial_formula/surcharge_tier_keyed_on_goods_not_total
        """
        product, _ = create_classified_product(sku="P-400", name="Pump",
                                               controlled_content_pct=0, unit_value_cents=33333,
                                               classification_code="EAR99")
        party = create_party(legal_name="Harbor Retail GmbH", country_code="DEU", city="Hamburg")
        order = validate_success(
            api.create_order(
                {"product_id": product["id"], "party_id": party["id"],
                 "destination_country": "DEU", "end_use": "CIVILIAN", "quantity": 3},
                ops_headers,
            ),
            201,
        )
        assert order["goods_value_cents"] == 99999
        assert order["surcharge_cents"] == 2000, (
            f"goods 99999 < 100000 takes the 0.02 tier: round(1999.98)=2000, "
            f"got {order['surcharge_cents']}"
        )
        assert order["total_value_cents"] == 101999

    def test_tier_keyed_on_goods_even_when_total_crosses(self, api, ops_headers):
        """PRD §3.4: "The compliance surcharge then applies a two-tier rate keyed **only** on `goods_value_cents`, never on the running total: 0.02 when the goods value is below 100000 cents, and 0.035 when it is 100000 cents or more — an order whose goods value lands exactly on the boundary takes the higher rate."

        Design: Difficulty/combinatorial_formula/surcharge_tier_keyed_on_goods_not_total
        """
        product, _ = create_classified_product(sku="P-400", name="Pump",
                                               controlled_content_pct=0, unit_value_cents=33333,
                                               classification_code="EAR99")
        party = create_party(legal_name="Harbor Retail GmbH", country_code="DEU", city="Hamburg")
        order = validate_success(
            api.create_order(
                {"product_id": product["id"], "party_id": party["id"],
                 "destination_country": "DEU", "end_use": "CIVILIAN", "quantity": 3},
                ops_headers,
            ),
            201,
        )
        # goods 99999 stays under the boundary while the total (101999) crosses it;
        # the tier must still be the low one because it keys on goods alone.
        assert order["goods_value_cents"] == 99999 < 100000
        assert order["total_value_cents"] == 101999 > 100000
        assert order["surcharge_cents"] == 2000, (
            f"tier keyed on goods (0.02) not on total (which would give 3570): "
            f"got {order['surcharge_cents']}"
        )


class TestCreationGuards:
    def test_embargoed_destination_rejected_at_create(self, api, ops_headers):
        """PRD §3.4: "And when the destination country matches an `ACTIVE` `EMBARGOED_COUNTRY` list entry with severity `PROHIBITED`, the create is refused with `ERR_DESTINATION_EMBARGOED` before anything is persisted."

        Design: Corner/validations/embargoed_destination_rejected_at_create
        """
        product, _ = create_classified_product(sku="P-031", name="Pipe",
                                               controlled_content_pct=0, unit_value_cents=10,
                                               classification_code="EAR99")
        create_entry(list_source="EMBARGOED_COUNTRY", match_name="North Korea",
                     country_code="PRK", severity="PROHIBITED")
        party = create_party(legal_name="Taedong Trading", country_code="PRK",
                             city="Pyongyang")
        res = api.create_order(
            {"product_id": product["id"], "party_id": party["id"],
             "destination_country": "PRK", "end_use": "CIVILIAN", "quantity": 1},
            ops_headers,
        )
        validate_error(res, ApiErrorId.ERR_DESTINATION_EMBARGOED)

    def test_order_create_for_unclassified_product_rejected(self, api, ops_headers):
        """PRD §3.4: "The product must already be `CLASSIFIED` — that is, have an active classification — because the determination analysis requires one; otherwise the create fails with `ERR_CLASSIFICATION_REQUIRED`."

        Design: Corner/validations/order_create_for_unclassified_product_rejected
        """
        product = create_product(sku="P-049", name="Blank2", controlled_content_pct=0,
                                 unit_value_cents=10)
        party = create_party(legal_name="Bruges Trading BV", country_code="BEL", city="Bruges")
        res = api.create_order(
            {"product_id": product["id"], "party_id": party["id"],
             "destination_country": "BEL", "end_use": "CIVILIAN", "quantity": 1},
            ops_headers,
        )
        validate_error(res, ApiErrorId.ERR_CLASSIFICATION_REQUIRED)

    def test_submit_license_for_unclassified_product_rejected(self, api, analyst_headers):
        """PRD §3.5: "Submission — including resubmission from `RETURNED_FOR_INFO` — moves the application to `SUBMITTED` and anchors `applicant_user_id` to the submitting analyst; the first submission additionally requires the product to be `CLASSIFIED`, failing with `ERR_CLASSIFICATION_REQUIRED` otherwise."

        Design: Corner/validations/submit_license_for_unclassified_product_rejected
        """
        product = create_product(sku="P-048", name="Blank", controlled_content_pct=0,
                                 unit_value_cents=10)
        lic = validate_success(
            api.create_license(
                {"product_id": product["id"], "issuing_authority": "BIS",
                 "approved_value_cents": 1000, "approved_quantity": 10,
                 "valid_from": "2026-07-01", "valid_until": "2026-12-31"},
                analyst_headers,
            ),
            201,
        )
        res = api.submit_license(lic["id"], analyst_headers)
        validate_error(res, ApiErrorId.ERR_CLASSIFICATION_REQUIRED)

        after = validate_success(api.get_license(lic["id"], analyst_headers), 200)
        assert after["status"] == "DRAFT", f"license must stay DRAFT, got {after['status']}"
