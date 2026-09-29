"""Entity shape, defaults, computed fields and identity resolution.

These cases hold the twelve entity types to their declared field lists: what a
create echoes back, what the server stamps without being asked, what a default
means when a field is omitted, and which not-found error a bad id draws.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_inventory_lot,
    add_store,
    api_client,
    assert_engagement,
    assert_instant_equals,
    assert_inventory_lot,
    assert_jurisdiction,
    assert_store,
    create_engagement,
    create_jurisdiction,
    employee_payload,
    engagement_payload,
    jurisdiction_payload,
    inventory_lot_payload,
    make_compliance_headers,
    make_consultant_headers,
    make_store_manager_headers,
    pin_clock,
    read_store,
    setup_planned_store,
    setup_selling_store,
    store_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}


class TestJurisdictionShape:
    def test_a_create_echoes_all_eleven_rule_set_values(self):
        """Every rule the statute declares comes back verbatim on the 201.

        The PRD says: "All eleven rule-set values are read back verbatim by the
        jurisdiction read, which is open to the `ComplianceOfficer`, the
        `LiquidationConsultant`, and the `RetailerController` alike."

        Design: Corner/entities/jurisdiction_create_returns_every_declared_field_with_201
        """
        pin_clock("2026-09-15T00:00:00Z")
        response = api_client.create_jurisdiction(
            jurisdiction_payload(**NY_RULES), make_compliance_headers()
        )
        jurisdiction = validate_success(response, 201)
        assert response.json()["response_type"] == "object"
        assert_jurisdiction(jurisdiction)
        assert jurisdiction["code"] == "NY"
        assert jurisdiction["name"] == "New York"
        assert jurisdiction["gob_license_required"] is True
        assert jurisdiction["max_sale_days"] == 60
        assert jurisdiction["license_cooling_off_days"] == 30
        assert jurisdiction["max_augmentation_ratio"] == pytest.approx(
            0.1000, abs=0.00001
        )
        assert jurisdiction["augmentation_disclosure_required"] is True
        assert jurisdiction["advertising_disclosure_required"] is False
        assert jurisdiction["surrender_notice_days"] == 10
        assert jurisdiction["version"] == 1
        assert_instant_equals(
            jurisdiction["created_at"], jurisdiction["updated_at"], "created_at"
        )

    def test_omitting_the_two_optional_flags_applies_their_declared_defaults(self):
        """A jurisdiction that says nothing about prohibition gets false and an empty
        list.

        The PRD says: "`augmentation_prohibited` (false unless stated) forbids
        augmentation merchandise outright, so nothing may even be proposed;
        `prohibited_claim_codes` (an empty list unless stated) names the advertising
        claims the jurisdiction bans"

        Design: Corner/entities/jurisdiction_create_omitting_optional_flags_applies_declared_defaults
        """
        pin_clock("2026-09-15T00:00:00Z")
        payload = {
            "code": "OR", "name": "Oregon", "gob_license_required": False,
            "max_sale_days": 90, "license_cooling_off_days": 0,
            "max_augmentation_ratio": 0.25,
            "augmentation_disclosure_required": False,
            "advertising_disclosure_required": False, "surrender_notice_days": 0,
        }
        jurisdiction = validate_success(
            api_client.create_jurisdiction(payload, make_compliance_headers()), 201
        )
        assert jurisdiction["augmentation_prohibited"] is False
        assert jurisdiction["prohibited_claim_codes"] == []
        assert jurisdiction["gob_license_required"] is False
        assert jurisdiction["max_augmentation_ratio"] == pytest.approx(
            0.2500, abs=0.00001
        )


class TestEngagementShape:
    def test_the_server_stamps_identity_timestamps_and_version_unasked(self):
        """No id, no timestamps and no version were submitted, yet all four come back.

        The PRD says: "Every resource carries a server-minted `id`: a UUID string with
        no type prefix, ignoring any id a client attempts to supply."

        Design: Corner/entities/engagement_create_stamps_system_fields_without_client_input
        """
        pin_clock("2026-09-15T00:00:00Z")
        engagement = validate_success(
            api_client.create_engagement(
                engagement_payload(), make_consultant_headers()
            ),
            201,
        )
        assert_engagement(engagement)
        assert isinstance(engagement["id"], str) and engagement["id"]
        assert engagement["version"] == 1
        assert_instant_equals(
            engagement["created_at"], "2026-09-15T00:00:00Z", "created_at"
        )
        assert_instant_equals(
            engagement["updated_at"], "2026-09-15T00:00:00Z", "updated_at"
        )

    def test_a_fresh_agreement_opens_with_every_aggregate_at_zero(self):
        """DRAFT, no strikes, an OPEN posture and no money anywhere.

        The PRD says: "A freshly drafted engagement begins with `engagement_status` of
        `DRAFT`, a `compliance_strike_count` of 0, a `compliance_posture` of `OPEN`,
        and every money aggregate — `original_cost_value_cents`,
        `guaranty_amount_cents`, `projected_gross_recovery_cents`,
        `projected_shortfall_cents`, `original_net_sales_cents`,
        `augmentation_net_sales_cents`, `gross_recovery_cents`,
        `expense_total_cents`, `expense_liquidator_share_cents`,
        `expense_retailer_share_cents`, and `retention_accrual_cents` — initialised to
        0."

        Design: Corner/entities/engagement_create_stamps_system_fields_without_client_input
        """
        pin_clock("2026-09-15T00:00:00Z")
        engagement = create_engagement()
        assert engagement["engagement_status"] == "DRAFT"
        assert engagement["compliance_strike_count"] == 0
        assert engagement["compliance_posture"] == "OPEN"
        for field in (
            "original_cost_value_cents", "guaranty_amount_cents",
            "projected_gross_recovery_cents", "projected_shortfall_cents",
            "original_net_sales_cents", "augmentation_net_sales_cents",
            "gross_recovery_cents", "expense_total_cents",
            "expense_liquidator_share_cents", "expense_retailer_share_cents",
            "retention_accrual_cents",
        ):
            assert engagement[field] == 0, field

    def test_omitting_the_expense_responsibility_is_a_malformed_request(self):
        """The field has no default, so the create cannot proceed without it.

        The PRD says: "Request shape on every endpoint: the body must be a JSON object,
        every required field must be present, every field must carry its declared JSON
        type, enum fields must hold a declared enum value, percentage fields must lie
        within their declared range (0 to 1 everywhere except `guaranty_pct`, whose
        range is 0 to 1.5), money and unit fields must be integers of at least 0, dates
        must be ISO 8601 `YYYY-MM-DD`, timestamps must be ISO 8601 UTC with a trailing
        `Z`, and `limit` and `offset` must lie within the bounds of §2.3 — otherwise
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/engagement_create_missing_expense_responsibility_rejects_request
        """
        pin_clock("2026-09-15T00:00:00Z")
        payload = engagement_payload()
        payload.pop("expense_responsibility")
        response = api_client.create_engagement(payload, make_consultant_headers())
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


class TestStoreShape:
    def test_a_read_returns_the_stored_row_with_its_computed_roll_ups(self):
        """PLANNED, unsuspended, unstarted, and carrying its lot's cost value.

        The PRD says: "A new store starts at `store_status` of `PLANNED` with
        `suspension_reason` of `NONE`, `selling_start_date` and `selling_end_date` both
        unset, `planned_avg_discount_pct` at exactly 0.0000, and every cost, unit, and
        recovery aggregate at 0."

        Design: Corner/entities/store_get_returns_exactly_the_stored_row
        """
        scenario = setup_planned_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={"store_code": "S-9001", "address_line": "1 Corner Way"},
        )
        store = validate_success(
            api_client.get_store(scenario["store"]["id"], make_consultant_headers())
        )
        assert_store(store)
        assert store["id"] == scenario["store"]["id"]
        assert store["engagement_id"] == scenario["engagement"]["id"]
        assert store["jurisdiction_id"] == scenario["jurisdiction"]["id"]
        assert store["store_code"] == "S-9001"
        assert store["address_line"] == "1 Corner Way"
        assert store["store_status"] == "PLANNED"
        assert store["suspension_reason"] == "NONE"
        assert store["selling_start_date"] is None
        assert store["original_cost_value_cents"] == 2000000
        assert store["units_initial_total"] == 1000
        assert store["units_sold_total"] == 0
        assert store["realized_sell_through_pct"] == pytest.approx(
            0.0000, abs=0.00001
        )
        assert store["planned_avg_discount_pct"] == pytest.approx(0.0000, abs=0.00001)
        assert store["augmentation_units_accounted"] == 0

    def test_the_listing_windows_three_stores_across_two_pages(self):
        """limit 2 gives two rows and has_more, and offset 2 gives the remaining one.

        The PRD says: "The `meta` block of a list response carries `limit`, `offset`,
        `total_count` — the count of rows matching the filter before the window is
        applied — and `has_more`, which is true when rows remain beyond the current
        window."

        Design: Corner/entities/store_list_paginates_with_limit_offset_total_count_and_has_more
        """
        pin_clock("2026-09-15T00:00:00Z")
        jurisdiction = create_jurisdiction(**NY_RULES)
        engagement = create_engagement()
        for index in (1, 2, 3):
            add_store(
                engagement["id"], jurisdiction["id"],
                store_code=f"S-910{index}", address_line=f"{index} List Rd",
            )
        headers = make_consultant_headers()
        first_page, first_meta = validate_paginated(
            api_client.list_stores(
                headers,
                params={"engagement_id": engagement["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(first_page) == 2
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        second_page, second_meta = validate_paginated(
            api_client.list_stores(
                headers,
                params={"engagement_id": engagement["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(second_page) == 1
        assert second_meta["limit"] == 2
        assert second_meta["offset"] == 2
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        codes = [row["store_code"] for row in first_page + second_page]
        assert sorted(codes) == ["S-9101", "S-9102", "S-9103"]

    def test_an_unknown_store_id_draws_the_store_not_found_error(self):
        """A well-formed but unused UUID is a 404, not an empty 200.

        The PRD says: "Each entity type has its own not-found error:
        `ERR_JURISDICTION_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`,
        `ERR_STORE_NOT_FOUND`, `ERR_INVENTORY_LOT_NOT_FOUND`,
        `ERR_CONSIGNMENT_NOT_FOUND`, `ERR_MARKDOWN_STAGE_NOT_FOUND`,
        `ERR_LICENSE_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_SALES_DAY_NOT_FOUND`,
        `ERR_EXPENSE_ITEM_NOT_FOUND`, `ERR_LEASE_DISPOSITION_NOT_FOUND`, and
        `ERR_SETTLEMENT_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/store_get_unknown_id_returns_store_not_found
        """
        pin_clock("2026-09-15T00:00:00Z")
        response = api_client.get_store(NON_EXISTENT_UUID, make_consultant_headers())
        error = validate_error(response, ApiErrorId.ERR_STORE_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"
        assert error["message"].strip()

    def test_the_engagement_path_id_is_resolved_before_the_payload_foreign_key(self):
        """Both ids are unknown, and the path id is the one that reports.

        The PRD says: "Nested paths are validated left to right. When a request
        addresses a child collection under a parent, the parent id is resolved first
        and a miss returns that parent's own not-found error before the child is
        considered."

        Design: Corner/entities/store_create_under_unknown_engagement_returns_engagement_not_found
        """
        pin_clock("2026-09-15T00:00:00Z")
        response = api_client.create_store(
            NON_EXISTENT_UUID,
            store_payload(
                "11111111-1111-1111-1111-111111111111",
                store_code="S-9401", address_line="7 Ghost St",
            ),
            make_consultant_headers(),
        )
        error = validate_error(
            response, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value, 404
        )
        assert error["error_id"] != ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value

    def test_an_unknown_jurisdiction_in_the_body_draws_its_own_not_found(self):
        """A good engagement path with a dead jurisdiction reference is refused.

        The PRD says: "Foreign keys carried in the payload are resolved after every
        path id, and where a payload declares more than one foreign key they are
        resolved in the order the endpoint declares them."

        Design: Corner/entities/store_create_with_unknown_jurisdiction_returns_jurisdiction_not_found
        """
        pin_clock("2026-09-15T00:00:00Z")
        create_jurisdiction(**NY_RULES)
        engagement = create_engagement()
        response = api_client.create_store(
            engagement["id"],
            store_payload(
                "22222222-2222-2222-2222-222222222222",
                store_code="S-9501", address_line="8 Nowhere Ave",
            ),
            make_consultant_headers(),
        )
        validate_error(response, ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value, 404)
        _rows, meta = validate_paginated(
            api_client.list_stores(
                make_consultant_headers(),
                params={"engagement_id": engagement["id"]},
            )
        )
        assert meta["total_count"] == 0


class TestInventoryLotComputedFields:
    def test_the_two_value_fields_are_derived_from_units_and_unit_prices(self):
        """Four hundred units at 3,000 and 7,000 cents give 1,200,000 and 2,800,000.

        The PRD says: "Its `cost_value_cents` and `retail_value_cents` are the initial
        units less any returned units, multiplied by `unit_cost_cents` and
        `unit_retail_cents` respectively; at creation, with nothing returned, they are
        simply the initial units times the respective unit price."

        Design: Corner/entities/inventory_lot_value_fields_are_computed_from_units_and_unit_prices
        """
        pin_clock("2026-09-15T00:00:00Z")
        jurisdiction = create_jurisdiction(**NY_RULES)
        engagement = create_engagement()
        store = add_store(
            engagement["id"], jurisdiction["id"],
            store_code="S-9201", address_line="4 Lot Ln",
        )
        lot = validate_success(
            api_client.create_inventory_lot(
                store["id"],
                inventory_lot_payload(
                    category="FOOTWEAR", units_initial=400,
                    unit_cost_cents=3000, unit_retail_cents=7000,
                ),
                make_consultant_headers(),
            ),
            201,
        )
        assert_inventory_lot(lot)
        assert lot["cost_value_cents"] == 1200000
        assert lot["retail_value_cents"] == 2800000
        assert lot["units_on_hand"] == 400
        assert lot["units_sold"] == 0
        assert lot["units_returned"] == 0
        assert lot["lot_status"] == "ON_FLOOR"

    def test_the_new_lot_lands_in_the_store_and_engagement_roll_ups(self):
        """Floored footwear units at full ticket give a 2,240,000-cent projection.

        The PRD says: "Those category sell-through rates are fixed constants of the
        model, one per `category` reading: `APPAREL` is 0.85, `FOOTWEAR` is 0.80, `HOME`
        is 0.70, `ELECTRONICS` is 0.95, `JEWELRY` is 0.60, and `SEASONAL` is 0.90."

        Design: Corner/entities/inventory_lot_value_fields_are_computed_from_units_and_unit_prices
        """
        pin_clock("2026-09-15T00:00:00Z")
        jurisdiction = create_jurisdiction(**NY_RULES)
        engagement = create_engagement()
        store = add_store(
            engagement["id"], jurisdiction["id"],
            store_code="S-9202", address_line="5 Lot Ln",
        )
        add_inventory_lot(
            store["id"], category="FOOTWEAR", units_initial=400,
            unit_cost_cents=3000, unit_retail_cents=7000,
        )
        read_back = read_store(store["id"])
        assert read_back["original_cost_value_cents"] == 1200000
        assert read_back["units_initial_total"] == 400
        assert read_back["projected_gross_recovery_cents"] == 2240000


class TestEmployeeTypeConstraints:
    def test_an_attendance_rate_above_one_is_refused_before_any_arithmetic(self):
        """1.25 is outside the declared zero-to-one range for a percentage field.

        The PRD says: "Ratios and percentages — recovery ratios, discount fractions,
        sell-through figures, fee rates, attendance rates — are decimal fractions
        between 0 and 1 rounded half up to four decimal places, with the sole exception
        of `guaranty_pct`, whose permitted range runs from 0 to 1.5 inclusive."

        Design: Corner/entities/employee_create_with_attendance_rate_above_one_is_refused
        """
        scenario = setup_selling_store(
            jurisdiction_overrides=NY_RULES,
            store_overrides={"store_code": "S-9301", "address_line": "6 Rate Rd"},
            license_overrides={"license_number": "NY-GOB-9301"},
        )
        store = scenario["store"]
        headers = make_store_manager_headers(store["id"])
        response = api_client.create_employee(
            store["id"],
            employee_payload(
                employee_code="EMP-Z", retention_bonus_cents=100000,
                attendance_rate=1.25,
            ),
            headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        rows, _meta = validate_paginated(
            api_client.list_employees(store["id"], headers)
        )
        assert rows == []
