"""Entity surface: creation defaults, pure reads, listing windows and input judgement."""

from typing import Any, Dict

import pytest
from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    DECLARANT_HEADERS,
    DEFAULT_CLOCK_UTC,
    ERR_ASSESSMENT_SCHEDULE_NOT_FOUND,
    ERR_ASSOCIATION_NOT_FOUND,
    ERR_AUDIT_ENGAGEMENT_NOT_FOUND,
    ERR_COMPONENT_NOT_FOUND,
    ERR_DEFECT_CLAIM_NOT_FOUND,
    ERR_DIRECTOR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LOT_NOT_FOUND,
    ERR_RECORDS_ITEM_NOT_FOUND,
    ERR_RESERVE_STUDY_NOT_FOUND,
    ERR_SUBSIDY_ENTRY_NOT_FOUND,
    ERR_TURNOVER_CASE_EXISTS,
    ERR_TURNOVER_CASE_NOT_FOUND,
    ERR_VENDOR_CONTRACT_NOT_FOUND,
    FORECAST_CURRENT,
    INSPECTOR_HEADERS,
    MILESTONE_BUILD_COMPLETE,
    MILESTONE_DEED_TENDERED,
    NON_EXISTENT_UUID,
    RECORDS_ACTION_DELIVER,
    STUDY_ACTION_ADOPT,
    ApiClient,
    assert_instant,
    assert_pct,
    association_payload,
    audit_engagement_payload,
    close_sale_payload,
    component_payload,
    defect_claim_payload,
    do_close_sale,
    is_valid_uuid,
    lot_payload,
    make_transition_committee_headers,
    milestone_payload,
    read_association,
    records_item_payload,
    records_transition_payload,
    seed_association,
    seed_component,
    seed_lot,
    seed_turnover_case,
    set_clock,
    study_action_payload,
    subsidy_entry_payload,
    turnover_case_payload,
    validate_error,
    validate_paginated,
    validate_success,
    vendor_contract_payload,
)


class TestAssociationRegistration:
    """The declaration's parameters come back verbatim; everything else is derived."""

    def test_creation_returns_every_input_plus_the_declared_empty_derivations(
        self, api: ApiClient
    ) -> None:
        """A brand-new community has an available claim pool equal to its whole pool.

        "Everything derived starts empty: `sold_lot_count` at 0, `sold_lot_pct` at
        0.00, `subsidy_receivable_cents` at 0, `reserve_claim_committed_cents` at
        0, `reserve_claim_available_cents` equal to `reserve_claim_pool_cents`,
        `subsidy_end_date` null, and `budget_forecast_status` at `CURRENT`."

        Design: Corner/entities/association_creation_returns_every_declared_field_with_derived_defaults
        """
        set_clock(api, DEFAULT_CLOCK_UTC)

        association = validate_success(
            api.create_association(
                association_payload(
                    name="Alder Commons",
                    total_planned_lots=40,
                    turnover_threshold_pct=75.00,
                    fixed_turnover_date="2028-01-01T00:00:00Z",
                    statute_of_repose_years=10,
                    reserve_pool_cents=900000,
                    reserve_claim_pool_cents=2500000,
                    declarant_monthly_subsidy_cents=70000,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert association["name"] == "Alder Commons"
        assert association["total_planned_lots"] == 40
        assert_pct(association["turnover_threshold_pct"], 75.00, "turnover_threshold_pct")
        assert_instant(
            association["fixed_turnover_date"],
            "2028-01-01T00:00:00Z",
            "fixed_turnover_date",
        )
        assert association["statute_of_repose_years"] == 10
        assert association["reserve_pool_cents"] == 900000
        assert association["reserve_claim_pool_cents"] == 2500000
        assert association["declarant_monthly_subsidy_cents"] == 70000

        assert association["sold_lot_count"] == 0
        assert_pct(association["sold_lot_pct"], 0.00, "sold_lot_pct")
        assert association["subsidy_receivable_cents"] == 0
        assert association["reserve_claim_committed_cents"] == 0
        assert association["reserve_claim_available_cents"] == 2500000
        assert association["subsidy_end_date"] is None
        assert association["budget_forecast_status"] == FORECAST_CURRENT

        assert is_valid_uuid(association["id"])
        assert association["version"] == 1
        assert "created_at" in association
        assert "updated_at" in association

    def test_retrieval_is_a_pure_read_that_moves_no_version(
        self, api: ApiClient
    ) -> None:
        """Any of the five roles may read, and the read is not a mutation.

        "`updated_at` is an ISO 8601 UTC timestamp in the same format, refreshed on
        every mutation of the record, including mutations the server performs on
        its own initiative as a cascade of some other request."

        Design: Corner/entities/association_retrieval_returns_the_stored_row_unchanged
        """
        created = seed_association(
            api,
            name="Birchfield",
            total_planned_lots=12,
            turnover_threshold_pct=66.67,
            fixed_turnover_date="2027-01-01T00:00:00Z",
            statute_of_repose_years=8,
            reserve_pool_cents=100000,
            reserve_claim_pool_cents=400000,
            declarant_monthly_subsidy_cents=20000,
        )

        read = validate_success(api.get_association(created["id"], AUDITOR_HEADERS))
        assert read["id"] == created["id"]
        assert read["name"] == "Birchfield"
        assert read["reserve_claim_available_cents"] == 400000
        assert read["version"] == created["version"], "The read bumped no version"
        assert_instant(read["updated_at"], created["updated_at"], "updated_at")


class TestLotListingWindow:
    """The filter narrows the set before limit and offset carve a page out of it."""

    def test_the_sale_status_filter_sets_the_total_count_the_pages_walk(
        self, api: ApiClient
    ) -> None:
        """Three of five lots are CLOSED, so the filtered walk reports three.

        "List responses report `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope, where `total_count` is the size
        of the filtered set before the window is applied and `has_more` indicates
        whether records remain beyond it."

        Design: Corner/entities/lots_listing_applies_filter_then_pagination_with_stable_total_count
        """
        association = seed_association(
            api,
            name="Cinder Row",
            total_planned_lots=5,
            turnover_threshold_pct=66.67,
            fixed_turnover_date="2027-01-01T00:00:00Z",
            statute_of_repose_years=8,
            reserve_pool_cents=50000,
            reserve_claim_pool_cents=100000,
            declarant_monthly_subsidy_cents=10000,
        )
        committee = make_transition_committee_headers(association["id"])

        lots = [
            seed_lot(api, association["id"], f"C-00{number}") for number in range(1, 6)
        ]
        closed_ids = []
        for index, closing_date in enumerate(
            ("2026-02-01T00:00:00Z", "2026-02-02T00:00:00Z", "2026-02-03T00:00:00Z")
        ):
            do_close_sale(api, lots[index]["id"], closing_date)
            closed_ids.append(lots[index]["id"])

        first_page, first_meta = validate_paginated(
            api.list_lots(
                association["id"],
                committee,
                {"sale_status": "CLOSED", "limit": 2, "offset": 0},
            )
        )
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert len(first_page) == 2
        assert all(row["sale_status"] == "CLOSED" for row in first_page)

        second_page, second_meta = validate_paginated(
            api.list_lots(
                association["id"],
                committee,
                {"sale_status": "CLOSED", "limit": 2, "offset": 2},
            )
        )
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert len(second_page) == 1
        assert second_page[0]["sale_status"] == "CLOSED"

        walked = [row["id"] for row in first_page] + [row["id"] for row in second_page]
        assert len(set(walked)) == 3, "The two pages are disjoint"
        assert set(walked) == set(closed_ids), "The two pages are exhaustive"

        unfiltered, unfiltered_meta = validate_paginated(
            api.list_lots(association["id"], committee, {"limit": 10, "offset": 0})
        )
        assert unfiltered_meta["total_count"] == 5
        assert unfiltered_meta["has_more"] is False
        assert len(unfiltered) == 5

        association = read_association(api, association["id"])
        assert association["sold_lot_count"] == 3
        assert_pct(association["sold_lot_pct"], 60.00, "sold_lot_pct")


class TestPathResolution:
    """Each entity answers an unresolvable path id with its own code."""

    def test_every_unresolvable_path_id_names_its_own_entity(
        self, api: ApiClient
    ) -> None:
        """Twelve operations across twelve entities, twelve distinct 404 codes.

        "Identifiers in a request path are resolved strictly left to right, and the
        first one that fails to resolve determines the error."

        Design: Corner/entities/every_path_id_that_does_not_resolve_returns_its_own_not_found_error
        """
        control = seed_association(
            api,
            name="Control Association",
            total_planned_lots=4,
            turnover_threshold_pct=66.67,
            fixed_turnover_date="2027-01-01T00:00:00Z",
            statute_of_repose_years=8,
            reserve_pool_cents=0,
            reserve_claim_pool_cents=0,
            declarant_monthly_subsidy_cents=0,
        )
        committee = make_transition_committee_headers(control["id"])

        validate_error(
            api.get_association(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_ASSOCIATION_NOT_FOUND,
        )
        validate_error(
            api.close_lot_sale(
                NON_EXISTENT_UUID,
                close_sale_payload(DEFAULT_CLOCK_UTC),
                DECLARANT_HEADERS,
            ),
            ERR_LOT_NOT_FOUND,
        )
        validate_error(
            api.record_milestone(
                NON_EXISTENT_UUID,
                milestone_payload(MILESTONE_DEED_TENDERED),
                DECLARANT_HEADERS,
            ),
            ERR_COMPONENT_NOT_FOUND,
        )
        validate_error(
            api.get_turnover_case(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_TURNOVER_CASE_NOT_FOUND,
        )
        validate_error(
            api.reserve_study_action(
                NON_EXISTENT_UUID, study_action_payload(STUDY_ACTION_ADOPT), committee
            ),
            ERR_RESERVE_STUDY_NOT_FOUND,
        )
        validate_error(
            api.get_subsidy_entry(NON_EXISTENT_UUID, AUDITOR_HEADERS),
            ERR_SUBSIDY_ENTRY_NOT_FOUND,
        )
        validate_error(
            api.issue_audit_engagement(NON_EXISTENT_UUID, AUDITOR_HEADERS),
            ERR_AUDIT_ENGAGEMENT_NOT_FOUND,
        )
        validate_error(
            api.get_defect_claim(NON_EXISTENT_UUID, AUDITOR_HEADERS),
            ERR_DEFECT_CLAIM_NOT_FOUND,
        )
        validate_error(
            api.get_vendor_contract(NON_EXISTENT_UUID, AUDITOR_HEADERS),
            ERR_VENDOR_CONTRACT_NOT_FOUND,
        )
        validate_error(
            api.records_item_transition(
                NON_EXISTENT_UUID,
                records_transition_payload(RECORDS_ACTION_DELIVER),
                DECLARANT_HEADERS,
            ),
            ERR_RECORDS_ITEM_NOT_FOUND,
        )
        validate_error(
            api.rescind_director(NON_EXISTENT_UUID, INSPECTOR_HEADERS),
            ERR_DIRECTOR_NOT_FOUND,
        )
        validate_error(
            api.adopt_assessment_schedule(NON_EXISTENT_UUID, committee),
            ERR_ASSESSMENT_SCHEDULE_NOT_FOUND,
        )

        unchanged = read_association(api, control["id"])
        assert unchanged["version"] == control["version"], (
            "None of the twelve refusals mutated anything"
        )


class TestRequestShape:
    """Missing fields, illegal members and reversed intervals are all shape faults."""

    @pytest.fixture
    def dovetail_yard(self, api: ApiClient) -> Dict[str, Any]:
        association = seed_association(
            api,
            name="Dovetail Yard",
            total_planned_lots=8,
            turnover_threshold_pct=66.67,
            fixed_turnover_date="2027-01-01T00:00:00Z",
            statute_of_repose_years=8,
            reserve_pool_cents=10000,
            reserve_claim_pool_cents=50000,
            declarant_monthly_subsidy_cents=5000,
        )
        component = seed_component(
            api,
            association["id"],
            name="Mail Kiosk",
            category="INFRASTRUCTURE",
            replacement_cost_cents=120000,
            useful_life_years=15,
            effective_age_years=1,
            promised_completion_date="2026-01-01T00:00:00Z",
        )
        return {
            "association": association,
            "component": component,
            "committee_headers": make_transition_committee_headers(association["id"]),
        }

    def test_omitting_a_required_or_action_conditional_field_is_rejected(
        self, api: ApiClient, dovetail_yard: Dict[str, Any]
    ) -> None:
        """A BUILD_COMPLETE with no effective_date is as invalid as a lot with no number.

        "Required fields present, enum members legal, numbers inside their declared
        ranges, `period_month` matching a four-digit year, a hyphen and a
        two-digit month in the range 01 through 12, `period_end` at or after
        `period_start`, `service_window_end` strictly after
        `service_window_start`, and action-conditional fields present —
        `effective_date` for `BUILD_COMPLETE`, `valuation_basis` for `RESERVE`,
        `settlement_amount_cents` for `ACCEPT`, `rejection_reason` for `REJECT`,
        `method` for `RECOMPUTE`, and `subsidy_end_date` when the financial
        dimension is advanced out of `SUBSIDY_ACTIVE`."

        Design: Corner/entities/create_calls_missing_required_input_fields_are_rejected
        """
        association_id = dovetail_yard["association"]["id"]
        component_id = dovetail_yard["component"]["id"]
        committee = dovetail_yard["committee_headers"]

        validate_error(
            api.create_lot(
                lot_payload(association_id, lot_number=None), DECLARANT_HEADERS
            ),
            ERR_INVALID_REQUEST,
        )
        validate_error(
            api.create_association(
                association_payload(
                    name="No Threshold HOA", turnover_threshold_pct=None
                ),
                ADMIN_HEADERS,
            ),
            ERR_INVALID_REQUEST,
        )
        validate_error(
            api.create_defect_claim(
                defect_claim_payload(
                    association_id,
                    component_id,
                    defect_summary="Kiosk lock failure",
                    repair_cost_estimate_cents=None,
                    diminution_value_cents=None,
                ),
                committee,
            ),
            ERR_INVALID_REQUEST,
        )
        validate_error(
            api.record_milestone(
                component_id,
                milestone_payload(MILESTONE_BUILD_COMPLETE, effective_date=None),
                DECLARANT_HEADERS,
            ),
            ERR_INVALID_REQUEST,
        )

        _lots, lot_meta = validate_paginated(api.list_lots(association_id, committee))
        assert lot_meta["total_count"] == 0
        _claims, claim_meta = validate_paginated(
            api.list_defect_claims(committee, {"association_id": association_id})
        )
        assert claim_meta["total_count"] == 0

        components, _meta = validate_paginated(
            api.list_components(association_id, committee)
        )
        assert components[0]["build_status"] == "UNBUILT"
        assert components[0]["substantial_completion_date"] is None

    def test_illegal_enum_members_ranges_and_interval_orders_are_rejected(
        self, api: ApiClient, dovetail_yard: Dict[str, Any]
    ) -> None:
        """An out-of-enum category, an even seat count, a thirteenth month, two bad orders.

        "the service window bounded by an inclusive `service_window_start` and an
        exclusive `service_window_end` that must be strictly later."

        Design: Corner/entities/enum_range_and_ordering_constraints_are_rejected_on_create
        """
        association_id = dovetail_yard["association"]["id"]
        component_id = dovetail_yard["component"]["id"]
        committee = dovetail_yard["committee_headers"]

        validate_error(
            api.create_component(
                component_payload(
                    association_id,
                    name="Odd Thing",
                    category="LANDSCAPE",
                    replacement_cost_cents=1000,
                    useful_life_years=5,
                    effective_age_years=0,
                    promised_completion_date="2027-01-01T00:00:00Z",
                ),
                DECLARANT_HEADERS,
            ),
            ERR_INVALID_REQUEST,
        )
        validate_error(
            api.create_turnover_case(
                turnover_case_payload(association_id, total_seats=4), ADMIN_HEADERS
            ),
            ERR_INVALID_REQUEST,
        )
        validate_error(
            api.create_subsidy_entry(
                subsidy_entry_payload(
                    association_id,
                    direction="ACCRUAL",
                    amount_cents=12000,
                    period_month="2026-13",
                ),
                DECLARANT_HEADERS,
            ),
            ERR_INVALID_REQUEST,
        )
        validate_error(
            api.create_audit_engagement(
                audit_engagement_payload(
                    association_id,
                    period_start="2026-06-30T00:00:00Z",
                    period_end="2026-01-01T00:00:00Z",
                ),
                AUDITOR_HEADERS,
            ),
            ERR_INVALID_REQUEST,
        )
        validate_error(
            api.create_vendor_contract(
                vendor_contract_payload(
                    association_id,
                    component_id,
                    vendor_name="Zero Window Services",
                    developer_affiliated=False,
                    annual_cost_cents=1000,
                    service_window_start="2026-03-01T00:00:00Z",
                    service_window_end="2026-03-01T00:00:00Z",
                ),
                DECLARANT_HEADERS,
            ),
            ERR_INVALID_REQUEST,
        )

        _components, component_meta = validate_paginated(
            api.list_components(association_id, committee)
        )
        assert component_meta["total_count"] == 1
        _cases, case_meta = validate_paginated(
            api.list_turnover_cases(association_id, committee)
        )
        assert case_meta["total_count"] == 0
        _entries, entry_meta = validate_paginated(
            api.list_subsidy_entries(committee, {"association_id": association_id})
        )
        assert entry_meta["total_count"] == 0
        _engagements, engagement_meta = validate_paginated(
            api.list_audit_engagements(association_id, committee)
        )
        assert engagement_meta["total_count"] == 0
        _contracts, contract_meta = validate_paginated(
            api.list_vendor_contracts(committee, {"association_id": association_id})
        )
        assert contract_meta["total_count"] == 0

        assert read_association(api, association_id)["version"] == 1, (
            "None of the five rejections touched the association"
        )


class TestDeclaredDefaults:
    """Each optional input has exactly one default, and the derivations honour it."""

    def test_omitted_optional_inputs_take_their_declared_values(
        self, api: ApiClient
    ) -> None:
        """The default-required permits item drops a vacuously complete case to 0.00.

        "each piece of it is registered as an item against a `turnover_case_id`
        with a `category` of `FINANCIAL_RECORDS`, `WARRANTIES`,
        `PLANS_AND_SPECS`, `VENDOR_CONTRACTS` or `PERMITS`, plus a `required` flag
        that defaults to true. Items begin `OUTSTANDING`, with `delivered_at` and
        `rejection_reason` both null."

        Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
        """
        association = seed_association(
            api,
            name="Everly Point",
            total_planned_lots=6,
            turnover_threshold_pct=66.67,
            fixed_turnover_date="2027-01-01T00:00:00Z",
            statute_of_repose_years=8,
            reserve_pool_cents=0,
            reserve_claim_pool_cents=0,
            declarant_monthly_subsidy_cents=0,
        )
        case = seed_turnover_case(api, association["id"], total_seats=3)
        committee = make_transition_committee_headers(association["id"])

        lot = validate_success(
            api.create_lot(
                lot_payload(association["id"], "E-001"), DECLARANT_HEADERS
            ),
            expected_status=201,
        )
        assert lot["sale_status"] == "UNSOLD"
        assert lot["closing_date"] is None

        component = validate_success(
            api.create_component(
                component_payload(
                    association["id"],
                    name="Playground",
                    category="AMENITY",
                    replacement_cost_cents=300000,
                    useful_life_years=12,
                    effective_age_years=0,
                    promised_completion_date="2029-01-01T00:00:00Z",
                ),
                DECLARANT_HEADERS,
            ),
            expected_status=201,
        )
        assert component["build_status"] == "UNBUILT"
        assert component["substantial_completion_date"] is None
        assert component["conveyance_status"] == "NOT_CONVEYED"

        item = validate_success(
            api.create_records_item(
                records_item_payload(case["id"], "PERMITS"), DECLARANT_HEADERS
            ),
            expected_status=201,
        )
        assert item["required"] is True
        assert item["status"] == "OUTSTANDING"
        assert item["delivered_at"] is None
        assert item["rejection_reason"] is None

        association = read_association(api, association["id"])
        assert association["sold_lot_count"] == 0
        assert_pct(association["sold_lot_pct"], 0.00, "sold_lot_pct")

        case = validate_success(api.get_turnover_case(case["id"], committee))
        assert_pct(
            case["records_transfer_completeness_pct"],
            0.00,
            "records_transfer_completeness_pct",
        )
        assert case["vacant_seats"] == 3
        assert case["owner_elected_seats_required"] == 0


class TestClientSuppliedComputedFields:
    """Server-owned fields in a body are dropped, not grounds for a rejection."""

    def test_computed_and_system_fields_in_the_body_are_ignored(
        self, api: ApiClient
    ) -> None:
        """Three creations succeed while every smuggled field is discarded.

        "Computed and system-owned fields that a client supplies anyway are
        silently ignored rather than rejected."

        Design: Corner/entities/computed_and_system_fields_supplied_by_a_client_are_input_ignored
        """
        set_clock(api, DEFAULT_CLOCK_UTC)

        association = validate_success(
            api.create_association(
                association_payload(
                    name="Foxglen",
                    total_planned_lots=10,
                    turnover_threshold_pct=66.67,
                    fixed_turnover_date="2027-01-01T00:00:00Z",
                    statute_of_repose_years=8,
                    reserve_pool_cents=100000,
                    reserve_claim_pool_cents=600000,
                    declarant_monthly_subsidy_cents=15000,
                    sold_lot_count=9,
                    sold_lot_pct=90.00,
                    reserve_claim_committed_cents=500000,
                    budget_forecast_status="STALE",
                    id="client-chosen-id",
                    version=77,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert association["id"] != "client-chosen-id"
        assert association["version"] == 1
        assert association["sold_lot_count"] == 0
        assert_pct(association["sold_lot_pct"], 0.00, "sold_lot_pct")
        assert association["reserve_claim_committed_cents"] == 0
        assert association["reserve_claim_available_cents"] == 600000
        assert association["budget_forecast_status"] == FORECAST_CURRENT

        committee = make_transition_committee_headers(association["id"])

        component = validate_success(
            api.create_component(
                component_payload(
                    association["id"],
                    name="Gatehouse",
                    category="STRUCTURE",
                    replacement_cost_cents=500000,
                    useful_life_years=30,
                    effective_age_years=0,
                    promised_completion_date="2027-06-01T00:00:00Z",
                    conveyance_status="CONVEYED",
                    substantial_completion_date="2020-01-01T00:00:00Z",
                ),
                DECLARANT_HEADERS,
            ),
            expected_status=201,
        )
        assert component["conveyance_status"] == "NOT_CONVEYED"
        assert component["substantial_completion_date"] is None
        assert component["conveyed_at"] is None

        claim = validate_success(
            api.create_defect_claim(
                defect_claim_payload(
                    association["id"],
                    component["id"],
                    defect_summary="Gatehouse arch cracking",
                    repair_cost_estimate_cents=200000,
                    diminution_value_cents=100000,
                    status="RESERVED",
                    reserved_amount_cents=999999,
                    repose_deadline="2099-01-01T00:00:00Z",
                    negotiation_round=5,
                ),
                committee,
            ),
            expected_status=201,
        )
        assert claim["status"] == "INVESTIGATING"
        assert claim["negotiation_round"] == 0
        assert claim["reserved_amount_cents"] == 0
        assert claim["valuation_basis"] is None
        assert claim["repose_deadline"] is None, (
            "The deadline is derived from the component, which has no completion date"
        )
        assert claim["version"] == 1


class TestBodyForeignKeys:
    """A body reference must resolve and must belong to the association named beside it."""

    def test_an_unknown_or_foreign_component_is_a_not_found_not_a_permission_fault(
        self, api: ApiClient
    ) -> None:
        """A component of another community is reported as a missing component.

        "A component that exists but belongs to a different association is
        reported as `ERR_COMPONENT_NOT_FOUND`, not as a permission problem."

        Design: Corner/entities/body_foreign_keys_must_resolve_and_agree_across_entities
        """
        hazel_park = seed_association(
            api,
            name="Hazel Park",
            total_planned_lots=9,
            turnover_threshold_pct=66.67,
            fixed_turnover_date="2027-01-01T00:00:00Z",
            statute_of_repose_years=8,
            reserve_pool_cents=0,
            reserve_claim_pool_cents=100000,
            declarant_monthly_subsidy_cents=0,
        )
        iron_wharf = seed_association(
            api,
            name="Iron Wharf",
            total_planned_lots=9,
            turnover_threshold_pct=66.67,
            fixed_turnover_date="2027-01-01T00:00:00Z",
            statute_of_repose_years=8,
            reserve_pool_cents=0,
            reserve_claim_pool_cents=100000,
            declarant_monthly_subsidy_cents=0,
        )
        boardwalk = seed_component(
            api,
            iron_wharf["id"],
            name="Boardwalk",
            category="STRUCTURE",
            replacement_cost_cents=700000,
            useful_life_years=20,
            effective_age_years=2,
            promised_completion_date="2026-01-01T00:00:00Z",
        )
        hazel_committee = make_transition_committee_headers(hazel_park["id"])

        validate_error(
            api.create_lot(
                lot_payload(NON_EXISTENT_UUID, "H-001"), DECLARANT_HEADERS
            ),
            ERR_ASSOCIATION_NOT_FOUND,
        )
        validate_error(
            api.create_defect_claim(
                defect_claim_payload(
                    hazel_park["id"],
                    boardwalk["id"],
                    defect_summary="Boardwalk plank rot",
                    repair_cost_estimate_cents=100000,
                    diminution_value_cents=50000,
                ),
                hazel_committee,
            ),
            ERR_COMPONENT_NOT_FOUND,
        )
        validate_error(
            api.create_vendor_contract(
                vendor_contract_payload(
                    hazel_park["id"],
                    boardwalk["id"],
                    vendor_name="Plank & Sons",
                    developer_affiliated=False,
                    annual_cost_cents=50000,
                    service_window_start="2026-01-01T00:00:00Z",
                    service_window_end="2026-12-01T00:00:00Z",
                ),
                DECLARANT_HEADERS,
            ),
            ERR_COMPONENT_NOT_FOUND,
        )

        _lots, lot_meta = validate_paginated(
            api.list_lots(hazel_park["id"], hazel_committee)
        )
        assert lot_meta["total_count"] == 0
        _claims, claim_meta = validate_paginated(
            api.list_defect_claims(hazel_committee, {"association_id": hazel_park["id"]})
        )
        assert claim_meta["total_count"] == 0
        _contracts, contract_meta = validate_paginated(
            api.list_vendor_contracts(
                hazel_committee, {"association_id": hazel_park["id"]}
            )
        )
        assert contract_meta["total_count"] == 0

        _components, component_meta = validate_paginated(
            api.list_components(
                iron_wharf["id"], make_transition_committee_headers(iron_wharf["id"])
            )
        )
        assert component_meta["total_count"] == 1


class TestOneCasePerAssociation:
    """The uniqueness scope is the association, not the platform."""

    def test_a_second_case_is_refused_while_another_community_may_still_open_one(
        self, api: ApiClient
    ) -> None:
        """The same legal payload succeeds elsewhere, proving the scope.

        "At most one case may exist per association; a second attempt is refused
        with `ERR_TURNOVER_CASE_EXISTS`."

        Design: Corner/entities/second_turnover_case_for_one_association_is_rejected
        """
        juniper_mesa = seed_association(
            api,
            name="Juniper Mesa",
            total_planned_lots=9,
            turnover_threshold_pct=66.67,
            fixed_turnover_date="2027-01-01T00:00:00Z",
            statute_of_repose_years=8,
            reserve_pool_cents=0,
            reserve_claim_pool_cents=0,
            declarant_monthly_subsidy_cents=0,
        )
        kelp_bay = seed_association(
            api,
            name="Kelp Bay",
            total_planned_lots=9,
            turnover_threshold_pct=66.67,
            fixed_turnover_date="2027-01-01T00:00:00Z",
            statute_of_repose_years=8,
            reserve_pool_cents=0,
            reserve_claim_pool_cents=0,
            declarant_monthly_subsidy_cents=0,
        )
        first_case = seed_turnover_case(api, juniper_mesa["id"], total_seats=5)

        validate_error(
            api.create_turnover_case(
                turnover_case_payload(juniper_mesa["id"], total_seats=7), ADMIN_HEADERS
            ),
            ERR_TURNOVER_CASE_EXISTS,
        )

        committee = make_transition_committee_headers(juniper_mesa["id"])
        unchanged = validate_success(
            api.get_turnover_case(first_case["id"], committee)
        )
        assert unchanged["total_seats"] == 5
        _cases, meta = validate_paginated(
            api.list_turnover_cases(juniper_mesa["id"], committee)
        )
        assert meta["total_count"] == 1

        elsewhere = validate_success(
            api.create_turnover_case(
                turnover_case_payload(kelp_bay["id"], total_seats=7), ADMIN_HEADERS
            ),
            expected_status=201,
        )
        assert elsewhere["total_seats"] == 7
        assert elsewhere["vacant_seats"] == 7
