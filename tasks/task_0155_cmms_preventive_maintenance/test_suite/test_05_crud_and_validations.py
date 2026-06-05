"""Resource creation, defaults, required-field and type validation, not-found,
self-referential parenting, and each remaining business-rule error trigger.

Covers the Corner entities and validations sections.
"""
import pytest

from test_helpers import (
    fixtures as fx,
    validate_success,
    validate_error,
    TEST_USERS,
    NON_EXISTENT_UUID,
)

MANAGER = TEST_USERS["manager_headers"]
PLANNER = TEST_USERS["planner_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]


# =========================================================================
# Corner — entities section
# =========================================================================

class TestEntityCreation:
    def test_create_site_returns_201_budget_spent_zero_timezone_default(self, api):
        """PRD §3.1: "The site's budget_spent_cents begins at 0".
        PRD §3.1: "an optional timezone (an IANA identifier used for display only
        ... and the timezone defaults to UTC when omitted)".

        Design: Corner/entities/create_site_returns_201_with_budget_spent_zero
        """
        data = validate_success(
            api.create_site({"name": "Greenfield", "maintenance_budget_cents": 5_000_000}, MANAGER),
            expected_status=201,
        )
        assert data["budget_spent_cents"] == 0
        assert data["timezone"] == "UTC"

    def test_create_asset_missing_site_id_invalid_request(self, api):
        """PRD §2.8: "every create or action request body must contain its
        required fields with the correct types and valid enum values; a missing
        field, wrong type, or unrecognized enum value yields ERR_INVALID_REQUEST."

        Design: Corner/entities/create_asset_missing_site_id_returns_invalid_request
        """
        validate_error(
            api.create_asset({"name": "No Site Asset", "criticality": "LOW"}, MANAGER),
            "ERR_INVALID_REQUEST",
            expected_status=400,
        )

    def test_create_asset_applies_defaults(self, api):
        """PRD §3.2: "Optional inputs include criticality (LOW, MEDIUM, HIGH, or
        CRITICAL, defaulting to MEDIUM), meter_unit (HOURS, CYCLES, or KM,
        defaulting to HOURS)".
        PRD §3.2: "On creation an asset's status is OPERATIONAL, its
        meter_reading is 0".

        Design: Corner/entities/create_asset_defaults_criticality_medium_meter_unit_hours
        """
        site = fx.create_site()
        data = validate_success(
            api.create_asset({"site_id": site["id"], "name": "Default Asset"}, MANAGER),
            expected_status=201,
        )
        assert data["criticality"] == "MEDIUM"
        assert data["meter_unit"] == "HOURS"
        assert data["status"] == "OPERATIONAL"
        assert data["meter_reading"] == 0

    def test_get_nonexistent_work_order_not_found(self, api):
        """PRD §2.8: "the system validates them left to right and rejects the
        first one that does not resolve with ERR_NOT_FOUND."

        Design: Corner/entities/get_work_order_nonexistent_returns_not_found
        """
        validate_error(
            api.get_work_order(NON_EXISTENT_UUID, PLANNER),
            "ERR_NOT_FOUND",
            expected_status=404,
        )

    def test_meter_reading_has_id_and_created_at(self, api):
        """PRD §2.4: "A MeterReading is immutable once recorded: it carries only
        id and created_at, and it has neither updated_at nor version."

        Design: Corner/entities/meter_reading_id_created_at_system_generated
        """
        from test_helpers import is_valid_uuid, is_iso8601_timestamp
        fx.set_clock("2026-01-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset()
        data = validate_success(
            api.create_meter_reading(
                asset["id"], {"value": 50, "reading_at": "2026-01-01T00:00:00Z"},
                TEST_USERS["technician_headers"],
            ),
            expected_status=201,
        )
        assert is_valid_uuid(data["id"]), "MeterReading.id is a server-minted UUID"
        assert is_iso8601_timestamp(data["created_at"]), "created_at present (ISO 8601 UTC)"

    def test_create_asset_invalid_criticality_enum_rejected(self, api):
        """PRD §2.8: "a missing field, wrong type, or unrecognized enum value
        yields ERR_INVALID_REQUEST."

        Design: Corner/entities/create_asset_invalid_criticality_enum_rejected
        """
        site = fx.create_site()
        validate_error(
            api.create_asset(
                {"site_id": site["id"], "name": "Bad Enum", "criticality": "URGENT"}, MANAGER
            ),
            "ERR_INVALID_REQUEST",
        )

    def test_create_asset_bad_parent_reference_not_found(self, api):
        """PRD §2.8: "When a create request body carries a foreign key — an
        asset's site_id or parent_asset_id ... — each referenced resource must
        exist, or the request is rejected with ERR_REFERENCE_NOT_FOUND."

        Design: Corner/entities/create_asset_bad_parent_reference_returns_reference_not_found
        """
        site = fx.create_site()
        validate_error(
            api.create_asset(
                {"site_id": site["id"], "name": "Orphan",
                 "parent_asset_id": NON_EXISTENT_UUID, "acquisition_cost_cents": 1},
                MANAGER,
            ),
            "ERR_REFERENCE_NOT_FOUND",
        )

    def test_priority_score_is_server_computed(self, api):
        """PRD §3.4: "in every other case the overrun multiplier is exactly 1.0.
        The base is the product of the criticality weight, the severity weight,
        and the overrun multiplier. To this base, add 10 when the work order is
        CORRECTIVE and 0 otherwise."

        Design: Corner/entities/work_order_priority_score_is_computed_input_ignored
        """
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "LOW", "acquisition_cost_cents": 10_000}
        )
        wo = validate_success(
            api.create_work_order(
                {"asset_id": asset["id"], "wo_type": "CORRECTIVE", "severity": "ROUTINE",
                 "estimated_labor_hours": 1},
                PLANNER,
            ),
            expected_status=201,
        )
        # LOW(1) * ROUTINE(1) * 1.0 + 10 = 11.
        assert wo["priority_score"] == pytest.approx(11, abs=0.01)


# =========================================================================
# Corner — validations section
# =========================================================================

class TestBusinessValidations:
    def test_pm_schedule_meter_with_calendar_interval_config_invalid(self, api):
        """PRD §3.3: "A METER schedule must supply a meter_interval (greater than
        zero) ... and must leave calendar_interval_days null. ... Any other
        combination — a meter schedule missing its interval or carrying a
        calendar interval, or vice versa — is rejected with
        ERR_SCHEDULE_CONFIG_INVALID."

        Design: Corner/validations/pm_schedule_meter_without_interval_config_invalid
        """
        site, asset = fx.setup_site_and_asset()
        validate_error(
            api.create_pm_schedule(
                asset["id"],
                {"trigger_type": "METER", "calendar_interval_days": 30,
                 "estimated_labor_hours": 2},
                PLANNER,
            ),
            "ERR_SCHEDULE_CONFIG_INVALID",
        )

    def test_meter_reading_non_monotonic_value_rejected(self, api):
        """PRD §3.2: "the submitted value must be at least the asset's current
        meter_reading and the reading_at must be strictly later than the latest
        existing reading's reading_at; a value below the current reading or a
        non-advancing timestamp is rejected with ERR_METER_NOT_MONOTONIC."

        Design: Corner/validations/meter_reading_non_monotonic_value_rejected
        """
        fx.set_clock("2026-01-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset()
        fx.create_meter_reading(asset["id"], 100, "2026-01-01T01:00:00Z")
        validate_error(
            api.create_meter_reading(
                asset["id"], {"value": 40, "reading_at": "2026-01-01T02:00:00Z"},
                TEST_USERS["technician_headers"],
            ),
            "ERR_METER_NOT_MONOTONIC",
        )

    def test_downtime_resolve_ended_before_started_invalid_interval(self, api):
        """PRD §3.8: "Resolving an open event is done by a Technician or
        MaintenanceManager who supplies the ended_at instant, which must be
        strictly after started_at. ... a violation of either bound is rejected
        with ERR_DOWNTIME_INTERVAL_INVALID."

        Design: Corner/validations/downtime_resolve_ended_before_started_invalid_interval
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset()
        dt = fx.open_downtime(asset["id"], "MECHANICAL_FAILURE", "2026-05-01T01:00:00Z")
        validate_error(
            api.resolve_downtime_event(
                dt["id"], {"ended_at": "2026-05-01T00:30:00Z"},
                TEST_USERS["technician_headers"],
            ),
            "ERR_DOWNTIME_INTERVAL_INVALID",
        )

    def test_reservation_insufficient_stock_rejected(self, api):
        """PRD §3.7: "the part's on_hand_qty minus its reserved_qty must be at
        least the requested qty, otherwise the reservation is rejected with
        ERR_INSUFFICIENT_STOCK."

        Design: Corner/validations/reservation_insufficient_stock_rejected
        """
        site, asset, part, wo = fx.setup_unassigned_wo_with_part(
            on_hand_qty=4, unit_cost_cents=100, sku="BOLT-3"
        )
        validate_error(
            api.create_reservation(
                wo["id"],
                {"spare_part_id": part["id"], "qty": 5,
                 "expected_spare_part_version": part["version"]},
                CLERK,
            ),
            "ERR_INSUFFICIENT_STOCK",
        )
        refreshed = fx.get_spare_part(part["id"])
        assert refreshed["reserved_qty"] == 0

    def test_assign_exceeds_backlog_capacity_rejected(self, api):
        """PRD §3.5: "Second is the backlog gate: the technician's backlog_hours
        plus the work order's estimated_labor_hours must not exceed the
        technician's weekly_capacity_hours, or the assignment is rejected with
        ERR_BACKLOG_EXCEEDED."

        Design: Corner/validations/assign_exceeds_backlog_capacity_rejected
        """
        site, asset, tech = fx.setup_site_asset_tech(
            tech_overrides={"skill_level": "SENIOR", "weekly_capacity_hours": 10}
        )
        fx.setup_assigned_work_order(
            asset["id"], tech["id"], severity="MAJOR", estimated_labor_hours=8
        )
        wo2 = fx.create_corrective_work_order(
            asset["id"], severity="MAJOR", estimated_labor_hours=5
        )
        fx.release_to_queue(wo2["id"])
        validate_error(
            api.assign_work_order(wo2["id"], {"technician_id": tech["id"]}, PLANNER),
            "ERR_BACKLOG_EXCEEDED",
        )
        after = validate_success(api.get_work_order(wo2["id"], PLANNER))
        assert after["execution_status"] == "UNASSIGNED"

    def test_warranty_approve_after_coverage_expired_rejected(self, api):
        """PRD §3.9: "the work order's closed_at to fall strictly before the
        asset's warranty_expires_at (otherwise ERR_WARRANTY_EXPIRED)".

        Design: Corner/validations/warranty_approve_after_coverage_expired_rejected
        """
        # closed_at 2026-06-01 but warranty expires 2026-05-01 -> expired.
        site, asset, tech, closed, claim = fx.setup_warranted_closed_wo_with_claim(
            claim_type="REPAIR",
            actual_cost_cents=90_000,
            acquisition_cost_cents=500_000,
            warranty_expires_at="2026-05-01T00:00:00Z",
            closed_at_clock="2026-06-01T00:00:00Z",
        )
        validate_error(
            api.approve_claim(claim["id"], {"decision_reason": "late"}, WARRANTY),
            "ERR_WARRANTY_EXPIRED",
        )
        after = validate_success(api.get_warranty_claim(claim["id"], WARRANTY))
        assert after["status"] == "SUBMITTED"

    def test_close_with_reserved_uncommitted_parts_rejected(self, api):
        """PRD §3.6: "No reservation on the order may still be RESERVED — the
        parts status must be NONE or COMMITTED, and any uncommitted reservation
        blocks the close with ERR_PARTS_NOT_COMMITTED."

        Design: Corner/validations/close_with_reserved_uncommitted_parts_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        site, asset, tech = fx.setup_site_asset_tech(tech_overrides={"skill_level": "SENIOR"})
        part = fx.create_spare_part(sku="HOSE-2", on_hand_qty=10, unit_cost_cents=500)
        wo = fx.create_corrective_work_order(asset["id"], severity="MAJOR", estimated_labor_hours=2)
        fx.release_to_queue(wo["id"])
        fx.assign(wo["id"], tech["id"])
        fx.reserve(wo["id"], part["id"], 2, part["version"])
        fx.start(wo["id"], tech["id"])
        validate_error(
            api.close_work_order(wo["id"], {"actual_cost_cents": 1000},
                                 fx.make_technician_headers(tech["id"])),
            "ERR_PARTS_NOT_COMMITTED",
        )
        after = validate_success(api.get_work_order(wo["id"], PLANNER))
        assert after["execution_status"] == "IN_PROGRESS"

    def test_duplicate_spare_part_sku_rejected(self, api):
        """PRD §3.1: "Each part has a sku that must be non-empty and unique across
        all parts by exact case-sensitive match — a duplicate sku at create time
        is rejected with ERR_DUPLICATE_SKU."

        Design: Corner/validations/duplicate_spare_part_sku_rejected
        """
        fx.create_spare_part(sku="PUMP-X", name="Pump Kit", on_hand_qty=3, unit_cost_cents=9000)
        validate_error(
            api.create_spare_part(
                {"sku": "PUMP-X", "name": "Dup", "on_hand_qty": 1, "unit_cost_cents": 100}, CLERK
            ),
            "ERR_DUPLICATE_SKU",
        )

    def test_pagination_limit_over_max_returns_validation(self, api):
        """PRD §2.3: "it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100. ... A limit or offset outside its allowed range is
        rejected with ERR_VALIDATION."

        Design: Corner/validations/pagination_limit_over_max_returns_validation
        """
        validate_error(
            api.list_spare_parts(CLERK, params={"limit": 500}),
            "ERR_VALIDATION",
            expected_status=400,
        )
