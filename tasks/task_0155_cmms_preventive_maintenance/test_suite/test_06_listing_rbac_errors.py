"""List pagination envelope, reverse-reachability filters, OCC stale-version,
authentication, skill-gate, and peer-role RBAC denials.

Covers the Corner endpoints, errors (non-stub), and rbac sections.
"""
from test_helpers import (
    fixtures as fx,
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
PLANNER = TEST_USERS["planner_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]
TECH = TEST_USERS["technician_headers"]


# =========================================================================
# Corner — endpoints section (listing + reverse-reachability)
# =========================================================================

class TestListingEnvelope:
    def test_list_spare_parts_pagination_envelope(self, api):
        """PRD §2.3: "For every list response, the envelope's meta object includes
        limit, offset, total_count, and has_more, where total_count is the number
        of matching resources before pagination and has_more indicates whether
        further pages remain."

        Design: Corner/endpoints/list_spare_parts_pagination_envelope
        """
        fx.create_spare_part(sku="A-1", name="Part A", on_hand_qty=1, unit_cost_cents=100)
        fx.create_spare_part(sku="B-1", name="Part B", on_hand_qty=1, unit_cost_cents=100)
        data, meta = validate_paginated(api.list_spare_parts(CLERK))
        assert meta["total_count"] == 2
        assert meta["has_more"] is False


class TestReverseReachability:
    def test_assets_filtered_by_site(self, api):
        """PRD §2.8: "Assets can be filtered by site_id or parent_asset_id".

        Design: Corner/endpoints/assets_filtered_by_site_reverse_reachability
        """
        site, asset = fx.setup_site_and_asset(asset_overrides={"acquisition_cost_cents": 100})
        data, meta = validate_paginated(api.list_assets(PLANNER, params={"site_id": site["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == asset["id"]

    def test_assets_filtered_by_parent(self, api):
        """PRD §2.8: "Assets can be filtered by site_id or parent_asset_id".

        Design: Corner/entities/list_assets_filtered_by_parent_self_referential_topology
        """
        site = fx.create_site()
        parent = fx.create_asset(site["id"], name="Parent", acquisition_cost_cents=100)
        child = fx.create_asset(
            site["id"], name="Child", parent_asset_id=parent["id"], acquisition_cost_cents=100
        )
        data, meta = validate_paginated(
            api.list_assets(PLANNER, params={"parent_asset_id": parent["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == child["id"]

    def test_reservations_filtered_by_spare_part(self, api):
        """PRD §2.8: "reservations by spare_part_id".

        Design: Corner/endpoints/reservations_filtered_by_spare_part_reverse_reachability
        """
        site, asset, part, wo = fx.setup_unassigned_wo_with_part(
            on_hand_qty=10, unit_cost_cents=100, sku="RR-1"
        )
        resv = fx.reserve(wo["id"], part["id"], 2, part["version"])
        data, meta = validate_paginated(
            api.list_reservations(CLERK, params={"spare_part_id": part["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == resv["id"]

    def test_downtime_events_filtered_by_work_order(self, api):
        """PRD §2.8: "downtime events by work_order_id".

        Design: Corner/endpoints/downtime_events_filtered_by_work_order_reverse_reachability
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset()
        wo = fx.create_corrective_work_order(asset["id"], severity="MAJOR", estimated_labor_hours=2)
        dt = fx.open_downtime(
            asset["id"], "MECHANICAL_FAILURE", "2026-05-01T01:00:00Z", work_order_id=wo["id"]
        )
        data, meta = validate_paginated(
            api.list_downtime_events(PLANNER, params={"work_order_id": wo["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == dt["id"]

    def test_warranty_claims_filtered_by_asset(self, api):
        """PRD §2.8: "warranty claims by asset_id or work_order_id".

        Design: Corner/endpoints/warranty_claims_filtered_by_asset_reverse_reachability
        """
        site, asset, tech, closed, claim = fx.setup_warranted_closed_wo_with_claim(
            claim_type="REPAIR", actual_cost_cents=50_000, acquisition_cost_cents=200_000
        )
        data, meta = validate_paginated(
            api.list_warranty_claims(WARRANTY, params={"asset_id": asset["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == claim["id"]

    def test_warranty_claims_filtered_by_work_order(self, api):
        """PRD §2.8: "warranty claims by asset_id or work_order_id".

        Design: Corner/endpoints/warranty_claims_filtered_by_work_order_reverse_reachability
        """
        site, asset, tech, closed, claim = fx.setup_warranted_closed_wo_with_claim(
            claim_type="REPAIR", actual_cost_cents=40_000, acquisition_cost_cents=200_000
        )
        data, meta = validate_paginated(
            api.list_warranty_claims(WARRANTY, params={"work_order_id": closed["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == claim["id"]

    def test_work_orders_filtered_by_assigned_technician(self, api):
        """PRD §2.8: "work orders by asset_id, pm_schedule_id,
        assigned_technician_id, or warranty_claim_id".

        Design: Corner/endpoints/work_orders_filtered_by_assigned_technician_reverse_reachability
        """
        site, asset, tech = fx.setup_site_asset_tech(tech_overrides={"skill_level": "SENIOR"})
        wo = fx.setup_assigned_work_order(
            asset["id"], tech["id"], severity="MAJOR", estimated_labor_hours=2
        )
        data, meta = validate_paginated(
            api.list_work_orders(PLANNER, params={"assigned_technician_id": tech["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == wo["id"]

    def test_work_orders_filtered_by_pm_schedule(self, api):
        """PRD §2.8: "work orders by asset_id, pm_schedule_id,
        assigned_technician_id, or warranty_claim_id".

        Design: Corner/endpoints/work_orders_filtered_by_pm_schedule_reverse_reachability
        """
        fx.set_clock("2026-03-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "MEDIUM", "acquisition_cost_cents": 100}
        )
        sched = fx.create_pm_schedule(
            asset["id"], "METER", meter_interval=100, estimated_labor_hours=2, severity="ROUTINE"
        )
        fx.create_meter_reading(asset["id"], 100, "2026-03-01T01:00:00Z")
        data, meta = validate_paginated(
            api.list_work_orders(PLANNER, params={"pm_schedule_id": sched["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["wo_type"] == "PREVENTIVE"

    def test_pm_schedules_listed_under_asset(self, api):
        """PRD §2.8: "PM schedules ... by asset_id".

        Design: Corner/endpoints/pm_schedules_listed_under_asset_reverse_reachability
        """
        site, asset = fx.setup_site_and_asset()
        sched = fx.create_pm_schedule(
            asset["id"], "METER", meter_interval=250, estimated_labor_hours=2, severity="ROUTINE"
        )
        data, meta = validate_paginated(api.list_pm_schedules(asset["id"], PLANNER))
        assert meta["total_count"] == 1
        assert data[0]["id"] == sched["id"]

    def test_work_order_reservations_listed(self, api):
        """PRD §3.7: "Creating the reservation records it with status RESERVED,
        recomputes the part's reserved_qty, increments the part's version, and
        sets the work order's parts_status to RESERVED".

        Design: Corner/endpoints/work_order_reservations_listed_reverse_reachability
        """
        site, asset, part, wo = fx.setup_unassigned_wo_with_part(
            on_hand_qty=5, unit_cost_cents=100, sku="WR-1"
        )
        resv = fx.reserve(wo["id"], part["id"], 1, part["version"])
        data, meta = validate_paginated(api.list_wo_reservations(wo["id"], CLERK))
        assert meta["total_count"] == 1
        assert data[0]["id"] == resv["id"]

    def test_meter_readings_listed_under_asset(self, api):
        """PRD §2.8: "meter readings ... by asset_id".

        Design: Corner/endpoints/meter_readings_listed_under_asset_reverse_reachability
        """
        fx.set_clock("2026-01-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset()
        reading = fx.create_meter_reading(asset["id"], 10, "2026-01-01T01:00:00Z")
        data, meta = validate_paginated(api.list_meter_readings(asset["id"], TECH))
        assert meta["total_count"] == 1
        assert data[0]["id"] == reading["id"]


# =========================================================================
# Corner — errors section (non-stub)
# =========================================================================

class TestErrorTriggers:
    def test_stale_version_on_reservation_create(self, api):
        """PRD §2.6: "If that value does not match the part's current version —
        because another reservation against the same part has already consumed
        availability and advanced the part's version since the client read it —
        the request is rejected with ERR_STALE_VERSION and HTTP status 412."

        Design: Corner/errors/error_stale_version_on_reservation_create
        """
        site, asset, part, wo = fx.setup_unassigned_wo_with_part(
            on_hand_qty=20, unit_cost_cents=100, sku="SV-1"
        )
        stale_version = part["version"]
        # First reservation succeeds and bumps the part version.
        fx.reserve(wo["id"], part["id"], 2, stale_version)
        # Second reservation reuses the now-stale version.
        validate_error(
            api.create_reservation(
                wo["id"],
                {"spare_part_id": part["id"], "qty": 2,
                 "expected_spare_part_version": stale_version},
                CLERK,
            ),
            "ERR_STALE_VERSION",
            expected_status=412,
        )

    def test_unauthenticated_unrecognized_role(self, api):
        """PRD §2.1: "If X-User-Role is missing or is not one of the recognized
        roles, the request is rejected with ERR_UNAUTHENTICATED."

        Design: Corner/errors/error_unauthenticated_missing_role_header
        """
        validate_error(
            api.list_spare_parts(TEST_USERS["ghost_headers"]),
            "ERR_UNAUTHENTICATED",
            expected_status=401,
        )

    def test_assign_junior_to_overhaul_skill_insufficient(self, api):
        """PRD §3.5: "the technician's skill rank must be greater than or equal to
        the work order's severity rank — an exact match is allowed — otherwise
        the assignment is rejected with ERR_SKILL_INSUFFICIENT."

        Design: Corner/errors/assign_junior_to_overhaul_skill_insufficient
        """
        site, asset, tech = fx.setup_site_asset_tech(
            tech_overrides={"skill_level": "JUNIOR", "weekly_capacity_hours": 40}
        )
        wo = fx.create_corrective_work_order(
            asset["id"], severity="OVERHAUL", estimated_labor_hours=4
        )
        fx.release_to_queue(wo["id"])
        validate_error(
            api.assign_work_order(wo["id"], {"technician_id": tech["id"]}, PLANNER),
            "ERR_SKILL_INSUFFICIENT",
        )
        after = validate_success(api.get_work_order(wo["id"], PLANNER))
        assert after["execution_status"] == "UNASSIGNED"


# =========================================================================
# Corner — rbac section (peer-role denials)
# =========================================================================

class TestRbacDenials:
    def test_technician_cannot_assign_work_order(self, api):
        """PRD §2.1: "When the header is present and recognized but the role is
        not permitted to perform the requested operation, the request is
        rejected with ERR_FORBIDDEN."
        PRD §4: "Assign an UNASSIGNED work order to a technician | Planner,
        MaintenanceManager" (Technician is not in the authorized set).

        Design: Corner/rbac/technician_cannot_assign_work_order_forbidden
        """
        site, asset, tech = fx.setup_site_asset_tech(tech_overrides={"skill_level": "SENIOR"})
        wo = fx.create_corrective_work_order(asset["id"], severity="MAJOR", estimated_labor_hours=2)
        fx.release_to_queue(wo["id"])
        validate_error(
            api.assign_work_order(
                wo["id"], {"technician_id": tech["id"]},
                fx.make_technician_headers(tech["id"]),
            ),
            "ERR_FORBIDDEN",
        )
        after = validate_success(api.get_work_order(wo["id"], PLANNER))
        assert after["execution_status"] == "UNASSIGNED"

    def test_planner_cannot_create_reservation(self, api):
        """PRD §2.1: "the request is rejected with ERR_FORBIDDEN."
        PRD §4: "Reserve units of a spare part for a work order (OCC-guarded on
        the part) | InventoryClerk" (Planner is not in the authorized set).

        Design: Corner/rbac/planner_cannot_create_reservation_forbidden
        """
        site, asset, part, wo = fx.setup_unassigned_wo_with_part(
            on_hand_qty=5, unit_cost_cents=100, sku="RB2-1"
        )
        validate_error(
            api.create_reservation(
                wo["id"],
                {"spare_part_id": part["id"], "qty": 1,
                 "expected_spare_part_version": part["version"]},
                PLANNER,
            ),
            "ERR_FORBIDDEN",
        )

    def test_inventory_clerk_cannot_approve_warranty(self, api):
        """PRD §2.1: "the request is rejected with ERR_FORBIDDEN."
        PRD §4: "Approve a claim; computes payable, links work order, reimburses
        budget | WarrantyAdmin" (InventoryClerk is not in the authorized set).

        Design: Corner/rbac/inventory_clerk_cannot_approve_warranty_forbidden
        """
        site, asset, tech, closed, claim = fx.setup_warranted_closed_wo_with_claim(
            claim_type="REPAIR", actual_cost_cents=30_000, acquisition_cost_cents=200_000
        )
        validate_error(
            api.approve_claim(claim["id"], {"decision_reason": "nope"}, CLERK),
            "ERR_FORBIDDEN",
        )
        after = validate_success(api.get_warranty_claim(claim["id"], WARRANTY))
        assert after["status"] == "SUBMITTED"

    def test_planner_cannot_create_site(self, api):
        """PRD §2.1: "the request is rejected with ERR_FORBIDDEN."
        PRD §4: "Create a site with a maintenance budget | MaintenanceManager"
        (Planner is not in the authorized set).

        Design: Corner/rbac/planner_cannot_create_site_forbidden
        """
        validate_error(
            api.create_site({"name": "Sneaky Site", "maintenance_budget_cents": 100}, PLANNER),
            "ERR_FORBIDDEN",
        )
