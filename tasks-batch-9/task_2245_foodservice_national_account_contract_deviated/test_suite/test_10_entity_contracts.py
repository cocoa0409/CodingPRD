"""The declared shape of the entities themselves: what a create returns, which
defaults fill the omitted keys, which fields the server mints or computes, and
how reads, filters and foreign keys behave.
"""
from test_helpers import (
    AUG_05,
    AUG_06,
    api_client,
    assert_common_fields,
    assert_contract,
    assert_contract_tier,
    assert_order_line,
    assert_pct,
    assert_product,
    bootstrap_partners,
    build_priced_world,
    build_signed_contract,
    contract_payload,
    contract_tier_payload,
    create_contract_draft,
    create_distribution_center,
    create_manufacturer,
    create_operator,
    create_order_line,
    create_product,
    dc_coverage_payload,
    invoice_order_line,
    is_valid_uuid,
    open_rebate_period,
    order_line_payload,
    product_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ACCOUNTANT, ADMIN, ANALYST, NAM, add_coverage, add_tier

UNKNOWN_CONTRACT_ID = "11111111-1111-1111-1111-111111111111"
UNKNOWN_ORDER_LINE_ID = "22222222-2222-2222-2222-222222222222"
UNKNOWN_DEVIATION_ID = "33333333-3333-3333-3333-333333333333"
UNKNOWN_PRODUCT_ID = "44444444-4444-4444-4444-444444444444"
UNKNOWN_REBATE_PERIOD_ID = "55555555-5555-5555-5555-555555555555"
UNKNOWN_PARENT_CONTRACT_ID = "66666666-6666-6666-6666-666666666666"
UNKNOWN_DC_ID = "77777777-7777-7777-7777-777777777777"

BOISE_DC = {
    "dc_code": "DC-BOI",
    "name": "Boise DC",
    "in_market_state_codes": ["ID"],
    "out_of_market_fee_per_case_cents": 300,
}


class TestContractCreation:
    def test_a_new_contract_is_returned_whole_with_every_counter_at_zero(self):
        """PRD §3.2: "A new contract lands in `DRAFT` with `compliance_posture`
        `OPEN`, `deviation_breach_count` 0, `rebate_payable_cents` 0 and
        `rebate_settled_total_cents` 0, and with `amends_contract_id`,
        `signed_at` and `signed_by_user_id` all null."

        Design: Corner/Entities/contract_creation_returns_all_declared_fields
        """
        operator = create_operator()
        manufacturer = create_manufacturer()

        contract = validate_success(
            api_client.create_contract(
                contract_payload(operator["id"], manufacturer["id"]), NAM
            ),
            201,
        )

        assert_contract(contract)
        assert contract["status"] == "DRAFT"
        assert contract["operator_id"] == operator["id"]
        assert contract["rebate_funding_manufacturer_id"] == manufacturer["id"]
        assert contract["contract_code"] == "HLG-2026"
        assert contract["amends_contract_id"] is None
        assert contract["compliance_posture"] == "OPEN"
        assert contract["deviation_breach_count"] == 0
        assert contract["rebate_payable_cents"] == 0
        assert contract["rebate_settled_total_cents"] == 0
        assert contract["signed_at"] is None
        assert contract["signed_by_user_id"] is None


class TestDeclaredDefaults:
    def test_every_omitted_optional_key_lands_on_its_declared_default(self):
        """PRD §3.2: "Four optional terms may be set at creation and otherwise
        take their defaults: `notice_period_days`, at least 1 and defaulting to
        30, the advance notice the operator is owed for a major cost change;
        `contracted_purchase_pct_target`, between 0.00 and 100.00 inclusive with
        two decimals and defaulting to 85.00, the contracted-item purchase share
        the operator commits to; `compliance_basis`, either `DOLLAR_WEIGHTED`
        (the default) or `CASE_WEIGHTED`, selecting which variant of the
        compliance percentage the contract is measured on; and
        `allow_out_of_market`, defaulting to false, which decides whether
        out-of-market coverage may be mapped at all."

        Design: Corner/Entities/omitted_optional_inputs_take_declared_defaults
        """
        operator = create_operator()
        manufacturer = create_manufacturer()

        product = validate_success(
            api_client.create_product(product_payload(manufacturer["id"]), ADMIN), 201
        )
        contract = validate_success(
            api_client.create_contract(
                contract_payload(operator["id"], manufacturer["id"]), NAM
            ),
            201,
        )
        tier = validate_success(
            api_client.create_contract_tier(
                contract_tier_payload(contract["id"]), NAM
            ),
            201,
        )

        assert contract["notice_period_days"] == 30
        assert_pct(
            contract["contracted_purchase_pct_target"],
            85.00,
            "contracted_purchase_pct_target",
        )
        assert contract["compliance_basis"] == "DOLLAR_WEIGHTED"
        assert contract["allow_out_of_market"] is False

        assert product["stock_status"] == "IN_STOCK"
        assert product["is_market_indexed"] is False
        assert product["substitution_group_code"] is None
        assert product["cost_effective_at"] is None

        assert manufacturer["bill_back_terms_days"] == 45
        assert manufacturer["status"] == "ACTIVE"

        # A tier with no explicit band ceiling is unbounded above and counts.
        assert tier["counts_as_contracted"] is True
        assert tier["max_case_volume"] is None


class TestServerMintedSystemFields:
    def test_version_starts_at_one_and_the_first_action_makes_it_two(self):
        """PRD §2.4: "`version` is an integer that starts at 1 on creation and
        increases by exactly 1 on every mutation of that row; `updated_at` is
        refreshed on the same mutation."

        Design: Corner/Entities/system_fields_are_server_minted_and_version_starts_at_one
        """
        world = bootstrap_partners()
        create_product(world["manufacturer_id"])
        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )
        add_tier(contract["id"])
        add_coverage(contract["id"], world["dc_id"])

        assert_common_fields(contract, "contract")
        assert is_valid_uuid(contract["id"])
        assert contract["version"] == 1

        submitted = validate_success(
            api_client.submit_contract_for_signature(contract["id"], NAM)
        )

        assert submitted["status"] == "PENDING_SIGNATURE"
        assert submitted["version"] == 2
        assert_common_fields(submitted, "contract after submit")
        # The client never supplied any of the four; they are all server-minted.
        assert submitted["id"] == contract["id"]
        assert submitted["created_at"] == contract["created_at"]


class TestComputedPricingFields:
    def test_a_client_supplied_list_price_is_refused_and_the_server_computes_it(self):
        """PRD §2.8: "Body parsing, declared types, enum membership, range
        constraints, and rejection of unknown fields — `ERR_INVALID_REQUEST`
        (400)."

        Design: Corner/Entities/order_line_pricing_fields_are_computed_not_accepted
        """
        world = build_priced_world()

        dictated = api_client.create_order_line(
            order_line_payload(
                world["contract_id"],
                world["product_id"],
                world["dc_id"],
                10,
                list_unit_price_cents=1,
            ),
            world["buyer"],
        )
        validate_error(dictated, "ERR_INVALID_REQUEST", 400)

        line = create_order_line(
            world["contract_id"],
            world["product_id"],
            world["dc_id"],
            world["operator_id"],
            10,
        )

        assert_order_line(line)
        # 4200 * 1.125 = 4725, never the 1 the client tried to dictate.
        assert line["list_unit_price_cents"] == 4725
        assert line["cost_basis_snapshot_cents"] == 4200
        assert line["extended_price_cents"] == 47250
        assert line["is_contracted_item"] is True
        assert line["order_date"].startswith("2026-08-05T00:00:00")
        assert line["pricing_status"] == "DRAFT_PRICED"


class TestRequiredInputs:
    def test_omitting_a_required_input_writes_nothing_at_all(self):
        """PRD §3.2: "A `NationalAccountManager` opens a contract for an operator
        by supplying `operator_id`, a globally unique `contract_code`, the
        `rebate_funding_manufacturer_id` that will fund the manufacturer share of
        the operator's rebate, and the term bounds `effective_from` and
        `effective_to`."

        Design: Corner/Entities/missing_required_inputs_are_rejected_before_any_write
        """
        world = bootstrap_partners()
        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )

        without_code = api_client.create_contract(
            contract_payload(
                world["operator_id"], world["manufacturer_id"], contract_code=None
            ),
            NAM,
        )
        validate_error(without_code, "ERR_INVALID_REQUEST", 400)

        without_band_floor = api_client.create_contract_tier(
            contract_tier_payload(contract["id"], min_case_volume=None), NAM
        )
        validate_error(without_band_floor, "ERR_INVALID_REQUEST", 400)

        _, contract_meta = validate_paginated(
            api_client.list_contracts(NAM, {"operator_id": world["operator_id"]})
        )
        assert contract_meta["total_count"] == 1

        tier_rows, tier_meta = validate_paginated(
            api_client.list_contract_tiers(NAM, {"contract_id": contract["id"]})
        )
        assert tier_meta["total_count"] == 0
        assert tier_rows == []


class TestEnumAndRangeConstraints:
    def test_out_of_enum_inverted_band_and_backwards_term_are_all_refused(self):
        """PRD §2.5: "In every one of these, the upper bound must be strictly
        after the lower bound; `effective_to` must be strictly after
        `effective_from`, `coverage_to` strictly after `coverage_from`,
        `period_end` strictly after `period_start`, `claim_period_end` strictly
        after `claim_period_start`, and `max_case_volume`, when supplied,
        strictly greater than `min_case_volume`."

        Design: Corner/Entities/enum_and_range_constraints_rejected_on_input
        """
        world = bootstrap_partners()
        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )

        bad_class = api_client.create_product(
            product_payload(
                world["manufacturer_id"],
                sku="P-BAD",
                description="Bad class",
                product_class_code="CUTLERY",
                pack_size=1,
                last_cost_cents=100,
                avg_cost_cents=100,
                replacement_cost_cents=100,
            ),
            ADMIN,
        )
        validate_error(bad_class, "ERR_INVALID_REQUEST", 400)

        # 500 is not strictly greater than 500, so the band is empty.
        empty_band = api_client.create_contract_tier(
            contract_tier_payload(
                contract["id"], min_case_volume=500, max_case_volume=500
            ),
            NAM,
        )
        validate_error(empty_band, "ERR_INVALID_REQUEST", 400)

        backwards_term = api_client.create_contract(
            contract_payload(
                world["operator_id"],
                world["manufacturer_id"],
                contract_code="HLG-BACKWARDS",
                effective_from="2027-08-01T00:00:00Z",
                effective_to="2026-07-31T23:59:59Z",
            ),
            NAM,
        )
        validate_error(backwards_term, "ERR_INVALID_REQUEST", 400)

        _, product_meta = validate_paginated(api_client.list_products(ADMIN))
        assert product_meta["total_count"] == 0

        _, tier_meta = validate_paginated(
            api_client.list_contract_tiers(NAM, {"contract_id": contract["id"]})
        )
        assert tier_meta["total_count"] == 0


class TestNotFoundCodes:
    def test_each_unknown_path_id_answers_with_its_own_not_found_code(self):
        """PRD §2.4: "Each has its own not-found code:
        `ERR_OPERATOR_NOT_FOUND`, `ERR_MANUFACTURER_NOT_FOUND`,
        `ERR_DISTRIBUTION_CENTER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_CONTRACT_TIER_NOT_FOUND`,
        `ERR_DC_COVERAGE_NOT_FOUND`, `ERR_DEVIATION_NOT_FOUND`,
        `ERR_SUBSTITUTION_RULE_NOT_FOUND`, `ERR_PRICE_CHANGE_NOTICE_NOT_FOUND`,
        `ERR_ORDER_LINE_NOT_FOUND`, `ERR_BILL_BACK_CLAIM_NOT_FOUND`,
        `ERR_BILL_BACK_REMITTANCE_NOT_FOUND`, `ERR_REBATE_PERIOD_NOT_FOUND` and
        `ERR_PRICING_DISPUTE_NOT_FOUND`, all HTTP 404."

        Design: Corner/Entities/unknown_ids_return_entity_specific_not_found_codes
        """
        create_operator()
        create_manufacturer()

        validate_error(
            api_client.get_contract(UNKNOWN_CONTRACT_ID, NAM),
            "ERR_CONTRACT_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_order_line(UNKNOWN_ORDER_LINE_ID, NAM),
            "ERR_ORDER_LINE_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_deviation_agreement(UNKNOWN_DEVIATION_ID, ANALYST),
            "ERR_DEVIATION_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_product(UNKNOWN_PRODUCT_ID, ADMIN),
            "ERR_PRODUCT_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_rebate_period(UNKNOWN_REBATE_PERIOD_ID, ACCOUNTANT),
            "ERR_REBATE_PERIOD_NOT_FOUND",
            404,
        )


class TestParentResolution:
    def test_body_foreign_keys_report_the_entity_that_is_actually_missing(self):
        """PRD §2.4: "The same codes cover body foreign keys, which are resolved
        after the path parameters in the order they are declared in the
        endpoint's input list; `rebate_funding_manufacturer_id` resolves under
        `ERR_MANUFACTURER_NOT_FOUND`, and `primary_product_id` and
        `substitute_product_id` resolve under `ERR_PRODUCT_NOT_FOUND`."

        Design: Corner/Entities/child_creates_require_a_resolvable_parent_contract
        """
        operator = create_operator()
        manufacturer = create_manufacturer()
        contract = create_contract_draft(operator["id"], manufacturer["id"])

        orphan_tier = api_client.create_contract_tier(
            contract_tier_payload(UNKNOWN_PARENT_CONTRACT_ID), NAM
        )
        validate_error(orphan_tier, "ERR_CONTRACT_NOT_FOUND", 404)

        # The contract resolves here; only the distribution center does not.
        unknown_center = api_client.create_dc_coverage(
            dc_coverage_payload(contract["id"], UNKNOWN_DC_ID), NAM
        )
        validate_error(unknown_center, "ERR_DISTRIBUTION_CENTER_NOT_FOUND", 404)

        _, tier_meta = validate_paginated(
            api_client.list_contract_tiers(NAM, {"contract_id": contract["id"]})
        )
        assert tier_meta["total_count"] == 0

        _, coverage_meta = validate_paginated(
            api_client.list_dc_coverages(NAM, {"contract_id": contract["id"]})
        )
        assert coverage_meta["total_count"] == 0


class TestSingleResourceReads:
    def test_a_read_echoes_the_stored_row_without_recomputing_anything(self):
        """PRD §3.1: "Items whose cost moves with a published market index set
        `is_market_indexed` to true (it defaults to false) and must then also
        carry `index_baseline_value`, the published index value, greater than zero
        and carrying two decimals, together with `index_baseline_cost_cents`, the
        cost per case that corresponds to that index value, greater than zero."

        Design: Corner/Entities/single_reads_return_exactly_what_was_stored
        """
        operator = create_operator()
        manufacturer = create_manufacturer()
        product = create_product(
            manufacturer["id"],
            is_market_indexed=True,
            index_baseline_value=100.00,
            index_baseline_cost_cents=4200,
        )
        contract = create_contract_draft(operator["id"], manufacturer["id"])
        tier = add_tier(
            contract["id"],
            cost_basis="AVG_COST",
            markup_type="DOLLARS_PER_CASE",
            markup_value=150,
            min_case_volume=0,
            max_case_volume=500,
            counts_as_contracted=False,
        )

        read_product = validate_success(
            api_client.get_product(product["id"], ANALYST)
        )
        read_tier = validate_success(
            api_client.get_contract_tier(tier["id"], NAM)
        )

        assert_product(read_product)
        assert read_product["sku"] == "P-CHKN"
        assert read_product["last_cost_cents"] == 4200
        assert read_product["avg_cost_cents"] == 4100
        assert read_product["replacement_cost_cents"] == 4300
        assert read_product["is_market_indexed"] is True
        assert_pct(read_product["index_baseline_value"], 100.00, "index_baseline_value")
        assert read_product["index_baseline_cost_cents"] == 4200

        assert_contract_tier(read_tier)
        assert read_tier["cost_basis"] == "AVG_COST"
        assert read_tier["markup_type"] == "DOLLARS_PER_CASE"
        assert read_tier["max_case_volume"] == 500
        assert read_tier["counts_as_contracted"] is False
        assert read_tier["status"] == "ACTIVE"


def _build_two_contract_world():
    """One operator with two ACTIVE contracts: contract A holds an invoiced line
    and a draft-priced line, contract B a single invoiced line."""
    world = bootstrap_partners()
    product = create_product(world["manufacturer_id"])
    world["product_id"] = product["id"]

    for key, code in (("a", "HLG-A"), ("b", "HLG-B")):
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            contract_code=code,
        )
        open_rebate_period(signed["contract_id"])
        world[key] = signed

    set_clock(AUG_05)
    first = create_order_line(
        world["a"]["contract_id"],
        product["id"],
        world["dc_id"],
        world["operator_id"],
        10,
    )
    invoice_order_line(first["id"])

    set_clock(AUG_06)
    second = create_order_line(
        world["a"]["contract_id"],
        product["id"],
        world["dc_id"],
        world["operator_id"],
        20,
    )
    third = create_order_line(
        world["b"]["contract_id"],
        product["id"],
        world["dc_id"],
        world["operator_id"],
        30,
    )
    invoice_order_line(third["id"])

    world["a1_id"] = first["id"]
    world["a2_id"] = second["id"]
    world["b1_id"] = third["id"]
    return world


class TestFilteredListReads:
    def test_filters_and_the_window_agree_on_the_same_ordered_result_set(self):
        """PRD §2.3: "The `meta` block of a list response carries `limit`,
        `offset`, `total_count` (the number of rows matching the filters before
        the window is applied) and `has_more` (true when rows remain beyond the
        current window)."

        Design: Corner/Entities/filtered_list_reads_page_and_scope_correctly
        """
        world = _build_two_contract_world()
        contract_a = world["a"]["contract_id"]

        rows, meta = validate_paginated(
            api_client.list_order_lines(NAM, {"contract_id": contract_a})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {world["a1_id"], world["a2_id"]}

        invoiced, invoiced_meta = validate_paginated(
            api_client.list_order_lines(
                NAM, {"contract_id": contract_a, "pricing_status": "INVOICED"}
            )
        )
        assert invoiced_meta["total_count"] == 1
        assert invoiced[0]["id"] == world["a1_id"]

        draft, draft_meta = validate_paginated(
            api_client.list_order_lines(
                NAM, {"contract_id": contract_a, "pricing_status": "DRAFT_PRICED"}
            )
        )
        assert draft_meta["total_count"] == 1
        assert draft[0]["id"] == world["a2_id"]

        page_one, page_one_meta = validate_paginated(
            api_client.list_order_lines(
                NAM, {"contract_id": contract_a, "limit": 1, "offset": 0}
            )
        )
        page_two, page_two_meta = validate_paginated(
            api_client.list_order_lines(
                NAM, {"contract_id": contract_a, "limit": 1, "offset": 1}
            )
        )
        assert len(page_one) == 1 and len(page_two) == 1
        assert page_one_meta["limit"] == 1 and page_one_meta["offset"] == 0
        assert page_one_meta["total_count"] == 2
        assert page_one_meta["has_more"] is True
        assert page_two_meta["has_more"] is False
        # The two windows walk the set without repeating or skipping a row.
        assert {page_one[0]["id"], page_two[0]["id"]} == {
            world["a1_id"],
            world["a2_id"],
        }

        _, all_meta = validate_paginated(api_client.list_order_lines(NAM))
        assert all_meta["total_count"] == 3

        _, active_meta = validate_paginated(
            api_client.list_contracts(
                NAM, {"operator_id": world["operator_id"], "status": "ACTIVE"}
            )
        )
        assert active_meta["total_count"] == 2


class TestVersionedMutationThroughActions:
    def test_each_action_bumps_the_version_and_rewrites_nothing_else(self):
        """PRD §3.3: "The transition refreshes `updated_at` and increments the
        contract's `version` by 1, and nothing else changes."

        Design: Corner/Entities/every_entity_is_versioned_and_mutated_only_through_action_endpoints
        """
        world = bootstrap_partners()
        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )
        add_tier(contract["id"])
        add_coverage(contract["id"], world["dc_id"])
        assert contract["version"] == 1

        submitted = validate_success(
            api_client.submit_contract_for_signature(contract["id"], NAM)
        )
        assert submitted["status"] == "PENDING_SIGNATURE"
        assert submitted["version"] == 2

        returned = validate_success(
            api_client.return_contract_to_draft(contract["id"], world["buyer"])
        )
        assert returned["status"] == "DRAFT"
        assert returned["version"] == 3

        # No endpoint exists that could have rewritten the identifying code.
        assert returned["contract_code"] == "HLG-2026"
        assert returned["operator_id"] == world["operator_id"]


class TestFlatForeignKeyTopology:
    def test_an_uncovered_center_is_refused_and_a_good_line_back_fills_its_keys(self):
        """PRD §3.5: "The server looks for the single `ACTIVE` coverage row on
        this contract and this `distribution_center_id` whose closed window from
        `coverage_from` to `coverage_to` contains the line's `order_date`; if
        there is none — including the case where a contract-level cascade has
        already moved the row to `ENDED` — the request fails with
        `ERR_DC_NOT_COVERED`."

        Design: Corner/Entities/flat_topology_keeps_cross_references_consistent
        """
        world = build_priced_world()
        unmapped_dc = create_distribution_center(**BOISE_DC)

        refused = api_client.create_order_line(
            order_line_payload(
                world["contract_id"], world["product_id"], unmapped_dc["id"], 10
            ),
            world["buyer"],
        )
        validate_error(refused, "ERR_DC_NOT_COVERED", 409)

        line = create_order_line(
            world["contract_id"],
            world["product_id"],
            world["dc_id"],
            world["operator_id"],
            10,
        )

        assert line["rebate_period_id"] == world["rebate_period_id"]
        assert line["applied_tier_id"] == world["tier_ids"][0]
        assert line["deviation_agreement_id"] is None
        assert line["substitution_rule_id"] is None

        _, meta = validate_paginated(
            api_client.list_order_lines(
                NAM, {"distribution_center_id": unmapped_dc["id"]}
            )
        )
        assert meta["total_count"] == 0
