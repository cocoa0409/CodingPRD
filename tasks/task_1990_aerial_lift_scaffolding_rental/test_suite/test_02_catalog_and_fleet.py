"""Catalog and fleet: class creation shape, unit system fields, pagination."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, create_equipment_class_payload, create_equipment_unit_payload,
    create_equipment_class, create_equipment_unit, set_clock,
    assert_equipment_unit,
)


class TestClassCreationShape:
    def test_create_class_missing_required_field_returns_invalid_request(
            self, api, branch_manager_headers):
        """PRD §2.8: "all required fields present, types correct, enum values
        valid, date and datetime formats valid, `requested_end_date` not
        earlier than `requested_start_date`, and `planned_end_utc` strictly
        later than `planned_start_utc` — otherwise `ERR_INVALID_REQUEST`
        (HTTP 400)." PRD §3.2: "Pricing is three-tiered: `daily_rate_cents`
        per billable day, `weekly_rate_cents` per seven-day week block, and
        `monthly_rate_cents` per twenty-eight-day month block, each zero or
        positive."

        Design: Corner/entities/create_class_missing_required_field_returns_invalid_request
        """
        payload = create_equipment_class_payload(class_code="BAD1")
        del payload["daily_rate_cents"]
        res = api.create_equipment_class(payload, branch_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_class_invalid_enum_returns_invalid_request(
            self, api, branch_manager_headers):
        """PRD §3.2: "a `category` of either `AERIAL_LIFT` or `SCAFFOLD`".
        PRD §2.8: request-shape violations are "otherwise
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_class_invalid_enum_returns_invalid_request
        """
        payload = create_equipment_class_payload(class_code="BAD2",
                                                 category="CRANE")
        res = api.create_equipment_class(payload, branch_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestUnitRegistration:
    def test_unit_create_system_fields(self, api, branch_manager_headers):
        """PRD §3.2: "Registration stamps the unit's
        `last_annual_inspection_date` to the logical-clock date — the factory
        pre-delivery inspection — and computes `next_inspection_due_date`
        three hundred sixty-five days later; the unit enters service in
        `AVAILABLE` status."

        Design: Corner/entities/unit_create_system_fields
        """
        set_clock("2026-08-01T09:00:00Z")
        cls = create_equipment_class(class_code="S19U")
        unit = validate_success(api.create_equipment_unit(
            create_equipment_unit_payload(cls["id"], "S19U-001"),
            branch_manager_headers), 201)
        assert_equipment_unit(unit)
        assert unit["status"] == "AVAILABLE"
        assert unit["last_annual_inspection_date"] == "2026-08-01"
        assert unit["next_inspection_due_date"] == "2027-08-01"


class TestFleetListing:
    def test_equipment_units_pagination(self, api, branch_manager_headers):
        """PRD §2.3: "`limit` caps the number of items returned: it defaults
        to 10 when omitted, with a minimum of 1 and a maximum of 100.
        `offset` skips that many items from the front of the result set and
        defaults to 0." PRD §3.2: "the list accepts optional `class_id` and
        `status` filters alongside `limit` and `offset`."

        Design: Corner/entities/equipment_units_pagination
        """
        set_clock("2026-08-01T09:00:00Z")
        cls = create_equipment_class(class_code="S19P")
        for serial in ("S19P-001", "S19P-002", "S19P-003"):
            create_equipment_unit(cls["id"], serial)

        page1, meta1 = validate_paginated(api.list_equipment_units(
            branch_manager_headers,
            params={"class_id": cls["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_equipment_units(
            branch_manager_headers,
            params={"class_id": cls["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestReferenceResolution:
    def test_get_contract_not_found_returns_404(
            self, api, rental_coordinator_headers):
        """PRD §2.8: "Path identifiers are validated left to right — the
        first identifier that does not resolve yields `ERR_NOT_FOUND`
        (HTTP 404) — followed by body references such as `customer_id`,
        `unit_id`, `contract_id`, `line_id`, and `class_id`, each of which
        must name an existing resource."

        Design: Corner/entities/get_contract_not_found_returns_404
        """
        res = api.get_rental_contract(NON_EXISTENT_UUID,
                                      rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)
