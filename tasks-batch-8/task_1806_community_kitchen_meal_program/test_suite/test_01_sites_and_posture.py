"""Sites, equipment posture derivation, and maintenance-window overlap rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_site,
    get_success_data,
    validate_error,
    validate_success,
    NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    MANAGER,
    create_equipment_asset,
    create_site,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


class TestSiteCreationDefaults:
    def test_site_create_success_and_defaults(self, api):
        """PRD 3.1: "A new site begins life `OPEN`".
        PRD 3.1: "Each site also carries a computed `equipment_posture`,
        initialized to `OPERATIONAL` when the site is created and recomputed on
        every equipment status transition at that site."

        Design: Corner/entities/site_create_success_and_defaults
        """
        resp = api.create_site(
            {
                "name": "Default Site",
                "dine_in_capacity": 30,
                "togo_capacity_per_window": 15,
                "delivery_radius_km": 5,
            },
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert_site(data)
        assert data["status"] == "OPEN", (
            f"new site must begin OPEN, got {data['status']!r}"
        )
        assert data["equipment_posture"] == "OPERATIONAL", (
            f"site with zero assets must be OPERATIONAL, got {data['equipment_posture']!r}"
        )

    def test_site_get_not_found_returns_404(self, api):
        """PRD 2.6: "Existence: every path-referenced resource exists,
        validated left to right, else `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/site_get_not_found_returns_404
        """
        resp = api.get_site("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404


class TestEquipmentPostureDerivation:
    def test_equipment_posture_derived_reconciliation(self, api):
        """PRD 3.1: "The posture aggregates only the site's `CRITICAL`
        equipment assets: it is `OPERATIONAL` when every critical asset is
        `OPERATIONAL`, `RESTRICTED` when exactly one critical asset is
        `DOWN_FOR_REPAIR` or `IN_MAINTENANCE`, and `HALTED` when two or more
        critical assets are down or in maintenance."
        PRD 3.1: "An asset that will not be repaired is moved from
        `DOWN_FOR_REPAIR` to `DECOMMISSIONED`, at which point it leaves the
        posture set entirely and the posture is recomputed once more."

        Design: Corner/cross_cutting_layers/equipment_posture_derived_reconciliation
        """
        site = create_site(name="Posture Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        a1 = create_equipment_asset(site["id"], name="O1",
                                    equipment_class="OVEN", criticality="CRITICAL")
        a2 = create_equipment_asset(site["id"], name="O2",
                                    equipment_class="OVEN", criticality="CRITICAL")
        a3 = create_equipment_asset(site["id"], name="C1",
                                    equipment_class="COLD_HOLDING", criticality="CRITICAL")

        # One CRITICAL asset down -> RESTRICTED.
        get_success_data(api.report_fault(a1["id"], MANAGER))
        site = get_success_data(api.get_site(site["id"], MANAGER))
        assert site["equipment_posture"] == "RESTRICTED", (
            f"one CRITICAL down must give RESTRICTED, got {site['equipment_posture']!r}"
        )

        # Two CRITICAL assets down -> HALTED.
        get_success_data(api.report_fault(a2["id"], MANAGER))
        site = get_success_data(api.get_site(site["id"], MANAGER))
        assert site["equipment_posture"] == "HALTED", (
            f"two CRITICAL down must give HALTED, got {site['equipment_posture']!r}"
        )

        # Decommissioning one downed asset removes it from the posture set.
        get_success_data(api.decommission_asset(a2["id"], MANAGER))
        site = get_success_data(api.get_site(site["id"], MANAGER))
        assert site["equipment_posture"] == "RESTRICTED", (
            "after decommission only one CRITICAL asset remains down; "
            f"expected RESTRICTED, got {site['equipment_posture']!r}"
        )


class TestServiceOpenGatedByEquipmentPosture:
    """Queue A: cross_entity_state_dependency / service_open_gated_by_equipment_posture."""

    def _setup_locked_day_with_service(self, api):
        from test_helpers.fixtures import (
            allocate,
            confirm_item,
            create_accepted_batch,
            create_menu_day,
            create_menu_item,
            create_service,
            lock_forecast,
            set_clock,
        )

        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Gate Kitchen", dine_in_capacity=50,
                           togo_capacity_per_window=20, delivery_radius_km=8)
        a1 = create_equipment_asset(site["id"], name="Oven 1",
                                    equipment_class="OVEN", criticality="CRITICAL")
        a2 = create_equipment_asset(site["id"], name="Oven 2",
                                    equipment_class="OVEN", criticality="CRITICAL")
        batch = create_accepted_batch(site["id"], item_description="beans",
                                      quantity_servings=20,
                                      unit_cost_cents_per_serving=50)
        menu_day = create_menu_day(site["id"], "2026-08-10")
        item = create_menu_item(menu_day["id"], name="Beans", planned_servings=10,
                                requires_equipment_class="OVEN")
        allocate(item["id"], batch["id"], 10)
        confirm_item(item["id"])
        lock_forecast(menu_day["id"])
        return site, a1, a2, menu_day

    def _create_gate_service(self, menu_day):
        """A service may only attach to an IN_PRODUCTION or SERVING day
        (PRD 3.6), so this runs after start_production, never on a
        FORECAST_LOCKED day."""
        from test_helpers.fixtures import create_service

        return create_service(menu_day["id"], service_model="DINE_IN",
                              window_start="2026-08-10T11:00:00Z",
                              window_end="2026-08-10T13:00:00Z", capacity=10)

    def test_halted_posture_rejects_start_production_restricted_allows(self, api):
        """PRD 3.2: "Starting production moves the day `FORECAST_LOCKED` →
        `IN_PRODUCTION` and requires the site's `status` to be `OPEN` and its
        `equipment_posture` to be anything other than `HALTED` — a halted
        kitchen rejects the start with `ERR_EQUIPMENT_HALTED`."

        Design: Difficulty/cross_entity_state_dependency/service_open_gated_by_equipment_posture
        """
        site, a1, a2, menu_day = self._setup_locked_day_with_service(api)

        # Two CRITICAL faults -> HALTED.
        get_success_data(api.report_fault(a1["id"], MANAGER))
        get_success_data(api.report_fault(a2["id"], MANAGER))

        resp = api.start_production(menu_day["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_HALTED)

        # Repair one asset -> RESTRICTED (exactly one CRITICAL down).
        get_success_data(api.complete_repair(a1["id"], {"inspected": True}, MANAGER))
        site = get_success_data(api.get_site(site["id"], MANAGER))
        assert site["equipment_posture"] == "RESTRICTED"

        resp = api.start_production(menu_day["id"], MANAGER)
        data = validate_success(resp, 200)
        assert data["status"] == "IN_PRODUCTION", (
            f"RESTRICTED posture must not gate start-production, got {data['status']!r}"
        )

    def test_halted_posture_rejects_service_open(self, api):
        """PRD 3.6: "Opening the service moves `PLANNED` → `OPEN` and is the
        most heavily gated transition in the program."
        PRD 3.6: "The parent menu day must be `IN_PRODUCTION`; the site's
        `equipment_posture` must not be `HALTED`, else `ERR_EQUIPMENT_HALTED`"

        Design: Difficulty/cross_entity_state_dependency/service_open_gated_by_equipment_posture
        """
        from test_helpers.fixtures import get_menu_day, start_production

        site, a1, a2, menu_day = self._setup_locked_day_with_service(api)
        start_production(menu_day["id"])
        service = self._create_gate_service(menu_day)

        # Halt the site after production started.
        get_success_data(api.report_fault(a1["id"], MANAGER))
        get_success_data(api.report_fault(a2["id"], MANAGER))

        version = get_menu_day(menu_day["id"])["version"]
        resp = api.open_service(
            service["id"], {"expected_menu_day_version": version}, MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_HALTED)

        # Restore to RESTRICTED; open now succeeds.
        get_success_data(api.complete_repair(a1["id"], {"inspected": True}, MANAGER))
        version = get_menu_day(menu_day["id"])["version"]
        resp = api.open_service(
            service["id"], {"expected_menu_day_version": version}, MANAGER
        )
        data = validate_success(resp, 200)
        assert data["status"] == "OPEN"


class TestMaintenanceWindowOverlap:
    """Queue A: resource_temporal_overlap / equipment_maintenance_closed_interval_buffer."""

    def _setup_two_ovens_one_in_maintenance(self, api):
        from test_helpers.fixtures import set_clock

        set_clock("2026-08-01T08:00:00Z")
        site = create_site(name="Maint Kitchen", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        a1 = create_equipment_asset(site["id"], name="Oven A",
                                    equipment_class="OVEN", criticality="SUPPORT")
        a2 = create_equipment_asset(site["id"], name="Oven B",
                                    equipment_class="OVEN", criticality="SUPPORT")
        get_success_data(
            api.schedule_maintenance(
                a1["id"],
                {"maint_start": "2026-08-12T08:00:00Z",
                 "maint_end": "2026-08-12T12:00:00Z"},
                MANAGER,
            )
        )
        return site, a1, a2

    def test_touching_maintenance_windows_conflict(self, api):
        """PRD 3.1: "The maintenance window must not collide with any other
        in-maintenance record for the same `equipment_class` at the same site;
        the collision test treats each window as a closed interval and widens
        it by a fifteen-minute buffer on both sides, and a collision is
        rejected with `ERR_TEMPORAL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/equipment_maintenance_closed_interval_buffer
        """
        site, a1, a2 = self._setup_two_ovens_one_in_maintenance(api)
        # Closed-interval semantics: [08:00,12:00] and [12:00,14:00] share 12:00.
        resp = api.schedule_maintenance(
            a2["id"],
            {"maint_start": "2026-08-12T12:00:00Z",
             "maint_end": "2026-08-12T14:00:00Z"},
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_CONFLICT)

    def test_maintenance_window_inside_buffer_conflicts(self, api):
        """PRD 3.1: "the collision test treats each window as a closed
        interval and widens it by a fifteen-minute buffer on both sides, and a
        collision is rejected with `ERR_TEMPORAL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/equipment_maintenance_closed_interval_buffer
        """
        site, a1, a2 = self._setup_two_ovens_one_in_maintenance(api)
        # A gap of only 10 minutes after the prior window is inside the buffer.
        resp = api.schedule_maintenance(
            a2["id"],
            {"maint_start": "2026-08-12T12:10:00Z",
             "maint_end": "2026-08-12T14:00:00Z"},
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_CONFLICT)
