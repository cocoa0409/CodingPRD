"""Entity contracts: creation echo, defaults, system fields, listing and the graph."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_INTAKE,
    ADMIN_REVIEW,
    AUDITOR,
    ApiErrorId,
    assert_cents,
    assert_envelope_meta,
    assert_instant,
    assert_score,
    assert_system_fields,
    make_member_headers,
)
from test_helpers.constants import (
    CLOCK_AFTER_RESPONSE_DUE,
    CLOCK_REGISTRY,
    CLOCK_STARTUP,
    SKU_CART,
    SKU_DISPENSER,
)
from test_helpers.factories import (
    CA_RULE,
    CART_LINE,
    NV_RULE,
    OMIT,
    TX_RULE,
    contract_usage_payload,
    line_item_payload,
    master_contract_payload,
    member_agency_payload,
    solicitation_payload,
    state_law_rule_payload,
    supplier_payload,
)
from test_helpers.fixtures import (
    add_line_item,
    create_member,
    determine_analysis,
    open_analysis,
    read_analysis,
    read_contract,
    read_member,
    seed_state_law_rules,
    set_clock,
    setup_active_contract,
    setup_authorised_member,
)
from test_helpers.test_users import OFFICER_AWARDER, OFFICER_CONDUCTOR

AUSTIN = dict(
    legal_name="City of Austin",
    state_code="TX",
    member_category="CITY",
    annual_spend_ceiling_cents=5000000,
    governing_body_resolution_number="RES-2026-208",
)
TRAVIS = dict(
    legal_name="Travis County",
    state_code="TX",
    member_category="COUNTY",
    annual_spend_ceiling_cents=7000000,
    governing_body_resolution_number="RES-2026-209",
)
MOP_LINE = dict(
    sku="JAN-MOP-200",
    item_description="Wet mop head, 20 ounce",
    unit_of_measure="EACH",
    base_unit_price_cents=4000,
    price_floor_cents=3000,
)


def _registry(api, rules=(TX_RULE,)):
    """The bare configuration table at the registry instant."""
    set_clock(api, CLOCK_REGISTRY)
    return seed_state_law_rules(api, rules=rules)


def _three_members(api):
    """Three unverified members created at three distinct logical instants."""
    _registry(api, rules=(TX_RULE, CA_RULE))
    austin = create_member(api, **AUSTIN)
    set_clock(api, CLOCK_AFTER_RESPONSE_DUE)
    travis = create_member(api, **TRAVIS)
    set_clock(api, CLOCK_STARTUP)
    riverside = create_member(api)
    return austin, travis, riverside


def _second_contract(api, world):
    """A second ACTIVE contract on the same award, carrying its own single line."""
    contract = validate_success(
        api.create_master_contract(
            master_contract_payload(
                world["solicitation"]["id"],
                world["supplier_a"]["id"],
                contract_number="COOP-MC-2026-002",
            ),
            OFFICER_AWARDER,
        ),
        201,
    )
    line = add_line_item(api, contract["id"], CART_LINE)
    contract = validate_success(
        api.contract_award_status(contract["id"], {"action": "EXECUTE"}, ADMIN_REVIEW)
    )
    return contract, line


class TestCreationAndReadBack:
    def test_01_a_configuration_row_echoes_every_field_it_was_given(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."

        Design: Corner/Entities/state_law_rule_creation_returns_201_and_echoes_every_declared_field
        """
        set_clock(api, CLOCK_REGISTRY)

        response = api.create_state_law_rule(state_law_rule_payload(**TX_RULE), ADMIN_INTAKE)

        created = validate_success(response, 201)
        body = response.json()
        assert body["response_type"] == "object"
        assert_envelope_meta(body)
        assert created["state_code"] == "TX"
        assert created["piggyback_doctrine"] == "STATUTORY_STRICT"
        assert created["min_notice_days"] == 14
        assert created["requires_lead_agency_in_state"] is False
        assert created["allows_nonprofit_participation"] is True
        assert created["max_contract_term_months"] == 60
        assert created["requires_local_solicitation_waiver"] is False
        assert created["reciprocity_state_codes"] == []
        read_back = validate_success(api.get_state_law_rule(created["id"], AUDITOR))
        assert read_back["id"] == created["id"]
        assert read_back["state_code"] == "TX"

    def test_02_the_contract_read_back_carries_the_award_terms_it_stored(self, api):
        """PRD §3.3: "A new contract starts in `status` `PENDING_EXECUTION` with
        `compliance_posture` `COMPLIANT`, `current_term_end` initialised to `base_term_end`,
        `renewals_used` 0, and every ledger total — `usage_chargeable_cents_total`,
        `fee_assessed_cents_total`, `fee_remitted_cents_total`, `fee_outstanding_cents` and
        `delinquent_report_count` — at 0."

        Design: Corner/Entities/master_contract_read_back_returns_the_stored_award_terms
        """
        world = setup_active_contract(api)

        response = api.get_master_contract(world["contract"]["id"], AUDITOR)

        contract = validate_success(response)
        assert response.json()["response_type"] == "object"
        assert contract["contract_number"] == "COOP-MC-2026-001"
        assert contract["status"] == "ACTIVE"
        assert contract["compliance_posture"] == "COMPLIANT"
        assert contract["admin_fee_rate_bps"] == 200
        assert_instant(contract["base_term_start"], "2026-09-01T00:00:00Z", "base_term_start")
        assert_instant(contract["base_term_end"], "2027-09-01T00:00:00Z", "base_term_end")
        assert_instant(contract["current_term_end"], "2027-09-01T00:00:00Z", "current_term_end")
        assert contract["max_renewals"] == 2
        assert contract["renewals_used"] == 0
        assert contract["nationwide_pricing_flag"] is True
        assert_cents(contract["usage_chargeable_cents_total"], 0, "usage_chargeable_cents_total")
        assert_cents(contract["fee_assessed_cents_total"], 0, "fee_assessed_cents_total")
        assert_cents(contract["fee_remitted_cents_total"], 0, "fee_remitted_cents_total")
        assert_cents(contract["fee_outstanding_cents"], 0, "fee_outstanding_cents")
        assert contract["delinquent_report_count"] == 0
        assert len(contract["discount_tiers"]) == 3
        assert len(contract["permitted_add_ons"]) == 3

    def test_03_the_member_listing_pages_filters_and_orders_by_creation(self, api):
        """PRD §2.3: "Unless a specific endpoint says otherwise, every list endpoint returns
        its rows sorted by `created_at` ascending. The `meta` object of a list response
        carries `limit`, `offset`, `total_count` and `has_more`."

        Design: Corner/Entities/member_agency_listing_paginates_filters_and_orders_by_created_at
        """
        austin, travis, riverside = _three_members(api)

        page_one, meta_one = validate_paginated(
            api.list_member_agencies(AUDITOR, {"limit": 2, "offset": 0})
        )
        page_two, meta_two = validate_paginated(
            api.list_member_agencies(AUDITOR, {"limit": 2, "offset": 2})
        )

        assert meta_one["total_count"] == 3
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["has_more"] is True
        assert [row["legal_name"] for row in page_one] == ["City of Austin", "Travis County"]
        assert_instant(page_one[0]["created_at"], CLOCK_REGISTRY, "created_at")
        assert_instant(page_one[1]["created_at"], CLOCK_AFTER_RESPONSE_DUE, "created_at")
        assert meta_two["total_count"] == 3
        assert meta_two["offset"] == 2
        assert meta_two["has_more"] is False
        assert [row["id"] for row in page_two] == [riverside["id"]]
        whole, meta_whole = validate_paginated(api.list_member_agencies(AUDITOR))
        assert meta_whole["limit"] == 10
        assert meta_whole["offset"] == 0
        assert meta_whole["total_count"] == 3
        assert meta_whole["has_more"] is False
        assert [row["id"] for row in whole] == [austin["id"], travis["id"], riverside["id"]]
        texans, meta_texans = validate_paginated(
            api.list_member_agencies(AUDITOR, {"state_code": "TX"})
        )
        assert meta_texans["total_count"] == 2
        assert all(row["state_code"] == "TX" for row in texans)
        live, meta_live = validate_paginated(
            api.list_member_agencies(AUDITOR, {"registration_status": "ACTIVE"})
        )
        assert meta_live["total_count"] == 0
        assert meta_live["has_more"] is False
        assert live == []

    def test_04_each_path_identifier_family_answers_with_its_own_code(self, api):
        """PRD §2.8: "Each entity has its own not-found code: `ERR_SOLICITATION_NOT_FOUND`,
        `ERR_SUPPLIER_NOT_FOUND`, `ERR_RESPONSE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_LINE_ITEM_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`,
        `ERR_USAGE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`,
        `ERR_COMPLAINT_NOT_FOUND` and `ERR_STATE_LAW_RULE_NOT_FOUND`, all HTTP 404."

        Design: Corner/Entities/every_path_id_family_reports_its_own_not_found_error
        """
        set_clock(api, CLOCK_REGISTRY)
        routes = [
            (api.get_solicitation, ApiErrorId.ERR_SOLICITATION_NOT_FOUND),
            (api.get_supplier, ApiErrorId.ERR_SUPPLIER_NOT_FOUND),
            (api.get_solicitation_response, ApiErrorId.ERR_RESPONSE_NOT_FOUND),
            (api.get_master_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND),
            (api.get_contract_line_item, ApiErrorId.ERR_LINE_ITEM_NOT_FOUND),
            (api.get_member_agency, ApiErrorId.ERR_MEMBER_NOT_FOUND),
            (api.get_piggyback_analysis, ApiErrorId.ERR_ANALYSIS_NOT_FOUND),
            (api.get_contract_usage, ApiErrorId.ERR_USAGE_NOT_FOUND),
            (api.get_usage_report, ApiErrorId.ERR_REPORT_NOT_FOUND),
            (api.get_contract_amendment, ApiErrorId.ERR_AMENDMENT_NOT_FOUND),
            (api.get_complaint, ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
            (api.get_state_law_rule, ApiErrorId.ERR_STATE_LAW_RULE_NOT_FOUND),
        ]

        for read, error_id in routes:
            response = read(NON_EXISTENT_UUID, ADMIN_REVIEW)

            error = validate_error(response, error_id, 404)
            assert response.json()["response_type"] == "error"
            assert error["message"]


class TestInputContract:
    def test_05_a_missing_required_field_writes_no_partial_row(self, api):
        """PRD §2.9: "Request body and query string conform to the endpoint's input schema:
        no unknown fields, no missing required fields, correct scalar types, enum values
        (including the endpoint's `action` set) inside their declared sets, `limit` within 1
        to 100, `offset` at least 0, `quantity` at least 1, `amount_cents` at least 0,
        `technical_score` within 0.00 to 100.00, `technical_weight_pct` and
        `price_weight_pct` summing to exactly 100, `base_term_start` strictly before
        `base_term_end`, `period_start` at or before `period_end`, and `discount_tiers` and
        `permitted_add_ons` well formed per their own constraints — `ERR_INVALID_REQUEST`,
        400, on every endpoint."

        Design: Corner/Entities/omitting_a_required_input_field_is_refused_before_any_row_is_written
        """
        _registry(api)

        no_weight = api.create_solicitation(
            solicitation_payload(price_weight_pct=OMIT), OFFICER_CONDUCTOR
        )
        no_home_state = api.create_supplier(supplier_payload(home_state_code=OMIT), ADMIN_INTAKE)
        no_ceiling = api.create_member_agency(
            member_agency_payload(**{**AUSTIN, "annual_spend_ceiling_cents": OMIT}), ADMIN_INTAKE
        )
        no_waiver_flag = api.create_state_law_rule(
            state_law_rule_payload(**{**NV_RULE, "requires_local_solicitation_waiver": OMIT}),
            ADMIN_INTAKE,
        )

        for response in (no_weight, no_home_state, no_ceiling, no_waiver_flag):
            validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        _, solicitations = validate_paginated(api.list_solicitations(AUDITOR))
        assert solicitations["total_count"] == 0
        _, suppliers = validate_paginated(api.list_suppliers(AUDITOR))
        assert suppliers["total_count"] == 0
        _, members = validate_paginated(api.list_member_agencies(AUDITOR))
        assert members["total_count"] == 0
        _, rules = validate_paginated(api.list_state_law_rules(AUDITOR))
        assert rules["total_count"] == 1

    def test_06_every_omitted_optional_field_lands_on_its_declared_default(self, api):
        """PRD §3.2: "A new solicitation lands in `status` `DRAFT` and `audit_package_status`
        `NOT_ASSEMBLED`, with `addenda_count` and `responsive_response_count` both 0 and
        `posted_at`, `notice_days` and `audit_completeness_pct` all null." PRD §3.4: "A new
        member starts in `registration_status` `PENDING_VERIFICATION` with
        `committed_spend_cents` 0, `docs_request_count` 0, and `verified_at` and
        `verified_by_user_id` null."

        Design: Corner/Entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
        """
        set_clock(api, CLOCK_REGISTRY)

        rule = validate_success(
            api.create_state_law_rule(
                state_law_rule_payload(**{**CA_RULE, "reciprocity_state_codes": OMIT}),
                ADMIN_INTAKE,
            ),
            201,
        )
        solicitation = validate_success(
            api.create_solicitation(
                solicitation_payload(
                    lead_agency_state_code="CA",
                    specification_document_ref=OMIT,
                    method_justification_ref=OMIT,
                ),
                OFFICER_CONDUCTOR,
            ),
            201,
        )
        member = validate_success(
            api.create_member_agency(
                member_agency_payload(**{**AUSTIN, "state_code": "CA"}), ADMIN_INTAKE
            ),
            201,
        )

        assert rule["reciprocity_state_codes"] == []
        assert solicitation["status"] == "DRAFT"
        assert solicitation["audit_package_status"] == "NOT_ASSEMBLED"
        assert solicitation["specification_document_ref"] is None
        assert solicitation["method_justification_ref"] is None
        assert solicitation["addenda_count"] == 0
        assert solicitation["responsive_response_count"] == 0
        assert solicitation["posted_at"] is None
        assert solicitation["notice_days"] is None
        assert solicitation["audit_completeness_pct"] is None
        assert member["registration_status"] == "PENDING_VERIFICATION"
        assert member["irs_determination_letter_number"] is None
        assert_cents(member["committed_spend_cents"], 0, "committed_spend_cents")
        assert member["docs_request_count"] == 0
        assert member["verified_at"] is None
        assert member["verified_by_user_id"] is None

    def test_07_notice_days_is_frozen_by_posting_and_never_supplied_by_a_client(self, api):
        """PRD §3.2: "On success it sets `posted_at` to the current logical instant, freezes
        `notice_days` as the whole number of 86,400-second days between `posted_at` and
        `response_due_at` — that is, the elapsed seconds divided by 86,400 and rounded *down*
        to a whole number — and sets `addenda_count` to 0."

        Design: Corner/Entities/notice_days_is_computed_at_post_notice_and_client_supplied_computed_fields_are_rejected
        """
        _registry(api)
        drafted = validate_success(
            api.create_solicitation(solicitation_payload(), OFFICER_CONDUCTOR), 201
        )

        posted = validate_success(
            api.solicitation_lifecycle(drafted["id"], {"action": "POST_NOTICE"}, OFFICER_CONDUCTOR)
        )

        assert posted["status"] == "POSTED"
        assert_instant(posted["posted_at"], CLOCK_REGISTRY, "posted_at")
        assert posted["notice_days"] == 21
        assert posted["addenda_count"] == 0
        assert posted["responsive_response_count"] == 0
        assert posted["audit_package_status"] == "NOT_ASSEMBLED"
        refused = api.create_solicitation(
            solicitation_payload(
                title="Second Janitorial Solicitation",
                solicitation_number="COOP-2026-002",
                status="AWARDED",
                notice_days=90,
            ),
            OFFICER_CONDUCTOR,
        )
        validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST, 400)
        _, solicitations = validate_paginated(api.list_solicitations(AUDITOR))
        assert solicitations["total_count"] == 1

    def test_08_the_server_mints_the_system_fields_and_advances_the_version(self, api):
        """PRD §2.4: "Mutable resources — `Solicitation`, `Supplier`, `SolicitationResponse`,
        `MasterContract`, `ContractLineItem`, `MemberAgency`, `PiggybackAnalysis`,
        `ContractUsage`, `UsageReport`, `ContractAmendment` and `MemberComplaint` —
        additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every change
        to the row, and `version`, an integer that starts at 1 on creation and increments by
        exactly 1 on every mutation." PRD §3.1: "A newly registered supplier starts
        `UNQUALIFIED` with a pristine record: `performance_score` 100.00,
        `deduction_points_total` 0.00, `performance_tier` `PREFERRED`,
        `substantiated_complaint_count` 0, `delinquent_report_count` 0, and
        `fee_assessed_cents_total` and `fee_remitted_cents_total` both 0."

        Design: Corner/Entities/system_fields_are_minted_by_the_server_and_version_advances_on_each_write
        """
        _registry(api)

        created = validate_success(
            api.create_supplier(supplier_payload(), ADMIN_INTAKE), 201
        )

        assert_system_fields(created, expect_version=1)
        assert_instant(created["created_at"], CLOCK_REGISTRY, "created_at")
        assert_instant(created["updated_at"], created["created_at"], "updated_at")
        assert created["qualification_status"] == "UNQUALIFIED"
        qualified = validate_success(
            api.supplier_qualification(created["id"], {"action": "QUALIFY"}, ADMIN_REVIEW)
        )
        assert qualified["version"] == 2
        assert qualified["qualification_status"] == "QUALIFIED"
        assert_score(qualified["performance_score"], 100.00, "performance_score")
        assert qualified["performance_tier"] == "PREFERRED"
        assert_score(qualified["deduction_points_total"], 0.00, "deduction_points_total")

    def test_09_enum_membership_and_numeric_ranges_are_refused_on_input(self, api):
        """PRD §3.4: "`member_category` is one of `STATE_AGENCY`, `CITY`, `COUNTY`,
        `K12_DISTRICT`, `HIGHER_ED`, `SPECIAL_DISTRICT` or `NONPROFIT_501C3`." PRD §3.3:
        "Each line carries a `sku` of 1 to 40 characters, an `item_description` printed on
        the price sheet, a `unit_of_measure` that is one of `EACH`, `CASE`, `PALLET` or
        `HOUR`, a `base_unit_price_cents` of at least 1 giving the awarded nationwide unit
        price before any member discount, and a `price_floor_cents` of at least 0 that must
        not exceed `base_unit_price_cents`; a floor above the base price is
        `ERR_PRICE_BELOW_FLOOR`."

        Design: Corner/Entities/enum_membership_and_numeric_range_constraints_are_enforced_on_input
        """
        world = setup_active_contract(api)
        contract_id = world["contract"]["id"]

        bad_category = api.create_member_agency(
            member_agency_payload(
                legal_name="Springfield Township",
                state_code="TX",
                member_category="TOWNSHIP",
                annual_spend_ceiling_cents=5000000,
                governing_body_resolution_number="RES-2026-301",
            ),
            ADMIN_INTAKE,
        )
        bad_measure = api.create_line_item(
            contract_id, line_item_payload(**{**MOP_LINE, "unit_of_measure": "BOX"}), OFFICER_AWARDER
        )
        bad_notice = api.create_state_law_rule(
            state_law_rule_payload(**{**NV_RULE, "min_notice_days": 91}), ADMIN_INTAKE
        )
        bad_fee_rate = api.create_master_contract(
            master_contract_payload(
                world["solicitation"]["id"],
                world["supplier_a"]["id"],
                contract_number="COOP-MC-2026-999",
                admin_fee_rate_bps=0,
            ),
            OFFICER_AWARDER,
        )

        for response in (bad_category, bad_measure, bad_notice, bad_fee_rate):
            validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        lines, lines_meta = validate_paginated(
            api.list_contract_line_items(AUDITOR, {"contract_id": contract_id})
        )
        assert lines_meta["total_count"] == 1
        assert lines[0]["sku"] == SKU_DISPENSER
        _, contracts = validate_paginated(api.list_master_contracts(AUDITOR))
        assert contracts["total_count"] == 1
        _, rules = validate_paginated(api.list_state_law_rules(AUDITOR))
        assert rules["total_count"] == 2
        _, members = validate_paginated(api.list_member_agencies(AUDITOR))
        assert members["total_count"] == 0

    def test_10_a_configuration_row_is_unversioned_and_cannot_be_rewritten(self, api):
        """PRD §2.4: "A state law configuration row is immutable after creation: it carries
        only `id` and `created_at`. It has no `updated_at` field and no `version` field,
        there is no update endpoint for it, and it therefore never participates in optimistic
        concurrency."

        Design: Corner/Entities/state_law_rules_are_immutable_configuration_with_no_version_and_no_write_surface
        """
        rules = _registry(api)
        rule_id = rules["TX"]["id"]

        stored = validate_success(api.get_state_law_rule(rule_id, AUDITOR))

        assert "version" not in stored
        assert "updated_at" not in stored
        assert_instant(stored["created_at"], CLOCK_REGISTRY, "created_at")
        rewrite = api.create_state_law_rule(
            state_law_rule_payload(
                state_code="TX",
                piggyback_doctrine="RECIPROCITY_LIBERAL",
                min_notice_days=30,
                requires_lead_agency_in_state=True,
                allows_nonprofit_participation=False,
                max_contract_term_months=36,
                requires_local_solicitation_waiver=True,
                reciprocity_state_codes=["OK"],
            ),
            ADMIN_INTAKE,
        )
        validate_error(rewrite, ApiErrorId.ERR_DUPLICATE_STATE_LAW_RULE, 409)
        unchanged = validate_success(api.get_state_law_rule(rule_id, AUDITOR))
        assert unchanged["min_notice_days"] == 14
        assert unchanged["piggyback_doctrine"] == "STATUTORY_STRICT"


class TestGraphTopology:
    def test_11_the_nested_create_resolves_its_parent_before_the_body(self, api):
        """PRD §2.8: "Where a path carries more than one identifier, they are resolved
        strictly left to right, and the first one that does not resolve produces its own 404 —
        a request against a line item of a non-existent contract reports
        `ERR_CONTRACT_NOT_FOUND`, never `ERR_LINE_ITEM_NOT_FOUND`."

        Design: Corner/Entities/line_item_creation_requires_an_existing_parent_and_the_sub_resource_route_reads_back
        """
        world = setup_active_contract(api)
        contract_id = world["contract"]["id"]

        orphan = api.create_line_item(
            NON_EXISTENT_UUID, line_item_payload(**MOP_LINE), OFFICER_AWARDER
        )

        validate_error(orphan, ApiErrorId.ERR_CONTRACT_NOT_FOUND, 404)
        nested, nested_meta = validate_paginated(
            api.list_line_items_of_contract(contract_id, AUDITOR)
        )
        assert nested_meta["total_count"] == 1
        assert nested[0]["sku"] == SKU_DISPENSER
        assert nested[0]["contract_id"] == contract_id
        assert nested[0]["status"] == "ACTIVE"
        assert nested[0]["origin"] == "AWARD"
        filtered, filtered_meta = validate_paginated(
            api.list_contract_line_items(AUDITOR, {"contract_id": contract_id})
        )
        assert filtered_meta["total_count"] == 1
        assert filtered[0]["id"] == nested[0]["id"]
        _, everything = validate_paginated(api.list_contract_line_items(AUDITOR))
        assert everything["total_count"] == 1

    def test_12_the_cited_opinion_must_cover_both_sides_of_the_order(self, api):
        """PRD §2.9: "The cited analysis covers exactly this member and contract —
        `ERR_ANALYSIS_PAIR_MISMATCH`, 422, on `POST /coop/contract-usages`."

        Design: Corner/Entities/pair_scoped_junction_rows_must_match_both_foreign_keys_of_the_usage
        """
        world = setup_active_contract(api)
        riverside, riverside_analysis = setup_authorised_member(api, world)
        austin, austin_analysis = setup_authorised_member(api, world, **AUSTIN)
        line_id = world["lines"][SKU_DISPENSER]["id"]

        crossed = api.create_contract_usage(
            contract_usage_payload(
                world["contract"]["id"], riverside["id"], line_id, austin_analysis["id"]
            ),
            make_member_headers(riverside["id"]),
        )

        validate_error(crossed, ApiErrorId.ERR_ANALYSIS_PAIR_MISMATCH, 422)
        assert_cents(
            read_member(api, riverside["id"])["committed_spend_cents"], 0, "committed_spend_cents"
        )
        assert read_analysis(api, austin_analysis["id"])["determination"] == "AUTHORIZED"
        assert read_analysis(api, riverside_analysis["id"])["determination"] == "CONDITIONAL"
        accepted = validate_success(
            api.create_contract_usage(
                contract_usage_payload(
                    world["contract"]["id"], riverside["id"], line_id, riverside_analysis["id"]
                ),
                make_member_headers(riverside["id"]),
            ),
            201,
        )
        assert accepted["status"] == "RECORDED"
        assert_cents(accepted["net_unit_price_cents"], 12500, "net_unit_price_cents")
        assert_cents(accepted["chargeable_base_cents"], 12500, "chargeable_base_cents")
        assert_cents(accepted["admin_fee_cents"], 250, "admin_fee_cents")
        assert_cents(accepted["total_cents"], 12750, "total_cents")
        assert_cents(
            read_member(api, riverside["id"])["committed_spend_cents"],
            12750,
            "committed_spend_cents",
        )
        own, own_meta = validate_paginated(api.list_analyses_of_member(riverside["id"], AUDITOR))
        assert own_meta["total_count"] == 1
        assert own[0]["id"] == riverside_analysis["id"]
        assert austin["legal_name"] == "City of Austin"

    def test_13_one_member_holds_authority_on_two_contracts_at_once(self, api):
        """PRD §3.6: "A `MemberRepresentative` records a purchase against a contract line by
        naming `contract_id`, `member_agency_id`, `line_item_id` and the
        `piggyback_analysis_id` of the opinion it relies on, a `quantity` of at least 1, and
        optionally the `add_on_codes` it elects." PRD §3.6: "A recorded order starts with
        `status` `RECORDED`, `usage_report_id` null and `retracted_at` null."

        Design: Corner/Entities/the_entity_graph_is_navigable_from_every_junction_row_in_both_directions
        """
        world = setup_active_contract(api)
        member, first_analysis = setup_authorised_member(api, world)
        second, cart_line = _second_contract(api, world)
        member_headers = make_member_headers(member["id"])

        opened = open_analysis(api, member["id"], second["id"], headers=member_headers)
        assert opened["status"] == "PENDING"
        second_analysis = determine_analysis(api, opened["id"])
        order = validate_success(
            api.create_contract_usage(
                contract_usage_payload(
                    second["id"], member["id"], cart_line["id"], second_analysis["id"], quantity=3
                ),
                member_headers,
            ),
            201,
        )

        assert second_analysis["status"] == "DETERMINED"
        assert second_analysis["member_agency_id"] == member["id"]
        assert second_analysis["contract_id"] == second["id"]
        earlier = read_analysis(api, first_analysis["id"])
        assert earlier["contract_id"] == world["contract"]["id"]
        assert earlier["status"] == "DETERMINED"
        assert order["contract_id"] == second["id"]
        assert order["member_agency_id"] == member["id"]
        assert order["line_item_id"] == cart_line["id"]
        assert order["piggyback_analysis_id"] == second_analysis["id"]
        assert order["usage_report_id"] is None
        assert order["retracted_at"] is None
        assert order["status"] == "RECORDED"
        _, analyses = validate_paginated(
            api.list_piggyback_analyses(ADMIN_REVIEW, {"member_agency_id": member["id"]})
        )
        assert analyses["total_count"] == 2
        orders, orders_meta = validate_paginated(
            api.list_contract_usages(ADMIN_REVIEW, {"contract_id": second["id"]})
        )
        assert orders_meta["total_count"] == 1
        assert orders[0]["id"] == order["id"]
        lines, lines_meta = validate_paginated(
            api.list_line_items_of_contract(second["id"], ADMIN_REVIEW)
        )
        assert lines_meta["total_count"] == 1
        assert lines[0]["sku"] == SKU_CART
        assert_cents(
            read_contract(api, second["id"])["usage_chargeable_cents_total"],
            30000,
            "usage_chargeable_cents_total",
        )
        assert_cents(
            read_contract(api, world["contract"]["id"])["usage_chargeable_cents_total"],
            0,
            "usage_chargeable_cents_total",
        )
