"""Posture roll-up cascades: reading->order->vessel->site and quality breach->void."""
import pytest

from test_helpers import (
    make_plant_operator_headers,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_approved_ticket,
    create_draft_permit,
    create_flow_impaired_vessel,
    create_site,
    create_site_vessel_technician,
    create_vessel,
    post_quality_report,
    post_reading,
)
from test_helpers.test_users import TEST_USERS

SM = TEST_USERS["service_manager_headers"]
SO = TEST_USERS["safety_officer_headers"]


class TestReadingOrderVesselSiteCascade:
    def test_reading_auto_creates_order_links_to_trigger_reading(self, api):
        """PRD §3.2: "If the new reading's `level_pct` is at or below the vessel's
        `reorder_point_pct`, and there is no replenishment order for the vessel in
        `TRIGGERED` or `DISPATCHED` status, the system auto-creates a
        `ReplenishmentOrder` in `TRIGGERED` status, snapshotting the vessel's
        current `replenishment_policy` onto `policy_used` and the triggering
        reading's `id` onto `trigger_reading_id`."

        Design: Difficulty/transitive_cascade/reading_order_vessel_site_cascade
        """
        site = create_site(name="Site Seven", state_code="MO")
        vessel = create_vessel(
            site["id"],
            name="SILO-I",
            capacity_tons=100,
            material_name="cement",
            reorder_point_pct=30,
            target_fill_pct=90,
        )
        assert site["site_posture"] == "NORMAL"

        reading = post_reading(
            vessel["id"], "2026-08-02T00:00:00Z", 25.0, site["id"]
        )
        data, meta = validate_paginated(
            api.list_replenishment_orders(
                SM, params={"vessel_id": vessel["id"], "status": "TRIGGERED"}
            )
        )
        assert meta["total_count"] == 1
        order = data[0]
        assert order["order_quantity_tons"] == pytest.approx(65.0, abs=1e-9)
        # cascade link 1: order bound to the triggering reading
        assert order["trigger_reading_id"] == reading["id"]

    def test_reading_order_vessel_site_posture_chain(self, api):
        """PRD §2.4: "A vessel is `FLOW_IMPAIRED` when its most recent
        `MaterialQualityReport` breaches either the vessel's moisture limit or the
        caking threshold; otherwise it is `PENDING_REPLENISHMENT` when at least one
        open `ReplenishmentOrder` (status `TRIGGERED` or `DISPATCHED`) exists for
        the vessel; otherwise it is `NORMAL`."
        PRD §2.4: "The site is `CRITICAL` if any of its vessels is
        `FLOW_IMPAIRED`, else `ATTENTION` if any is `PENDING_REPLENISHMENT`, else
        `NORMAL`."

        Design: Difficulty/transitive_cascade/reading_order_vessel_site_cascade
        """
        site = create_site(name="Site Seven", state_code="MO")
        vessel = create_vessel(
            site["id"],
            name="SILO-I",
            capacity_tons=100,
            material_name="cement",
            reorder_point_pct=30,
            target_fill_pct=90,
        )
        post_reading(vessel["id"], "2026-08-02T00:00:00Z", 25.0, site["id"])

        # cascade link 2: the open order lifts the vessel
        fetched_vessel = validate_success(api.get_vessel(vessel["id"], SM), 200)
        assert fetched_vessel["flow_posture"] == "PENDING_REPLENISHMENT"
        # cascade link 3: the vessel mutation lifts the site
        fetched_site = validate_success(api.get_site(site["id"], SM), 200)
        assert fetched_site["site_posture"] == "ATTENTION"


class TestQualityBreachPermitVoidCascade:
    def _setup_draft_permit(self):
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={"name": "Site Eight", "state_code": "MO"},
            vessel_overrides={
                "name": "BIN-J",
                "vessel_kind": "BIN",
                "capacity_tons": 60,
                "material_name": "sugar",
                "reorder_point_pct": 30,
                "moisture_limit_pct": 12.0,
            },
            tech_overrides={"name": "Tech Four", "weekly_capacity_hours": 40},
        )
        ticket = create_approved_ticket(
            site["id"], vessel["id"],
            job_type="CLEANOUT", requires_entry=True, est_hours=4, crew_size=1,
        )
        permit = create_draft_permit(
            vessel["id"], ticket["id"], tech["id"],
            window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T10:00:00Z",
        )
        return site, vessel, tech, ticket, permit

    def test_quality_breach_impairs_vessel_and_lifts_site(self, api):
        """PRD §3.3: "The vessel is `FLOW_IMPAIRED` whenever its latest quality
        report (latest by `sampled_at`, ties by `created_at`) breaches either the
        moisture limit or the caking threshold of 4."
        PRD §2.4: "The site is `CRITICAL` if any of its vessels is
        `FLOW_IMPAIRED`, else `ATTENTION` if any is `PENDING_REPLENISHMENT`, else
        `NORMAL`."

        Design: Difficulty/transitive_cascade/quality_breach_posture_permit_void_cascade
        """
        site, vessel, tech, ticket, permit = self._setup_draft_permit()
        post_quality_report(
            vessel["id"], tech["id"],
            sampled_at="2026-08-02T00:00:00Z",
            moisture_pct=15.0, caking_index=2,
        )
        fetched_vessel = validate_success(api.get_vessel(vessel["id"], SM), 200)
        # 15.0 > 12.0 moisture limit
        assert fetched_vessel["flow_posture"] == "FLOW_IMPAIRED"
        fetched_site = validate_success(api.get_site(site["id"], SM), 200)
        assert fetched_site["site_posture"] == "CRITICAL"

    def test_quality_breach_auto_voids_draft_permit(self, api):
        """PRD §2.4: "when a vessel's `flow_posture` becomes `FLOW_IMPAIRED`, every
        `EntryPermit` for that vessel whose status is `DRAFT` or `ISSUED` is
        automatically transitioned to `VOIDED` with `void_reason` set to
        `AUTO_QUALITY_HAZARD`. The transition is system-initiated; no client call
        is required."

        Design: Difficulty/transitive_cascade/quality_breach_posture_permit_void_cascade
        """
        site, vessel, tech, ticket, permit = self._setup_draft_permit()
        post_quality_report(
            vessel["id"], tech["id"],
            sampled_at="2026-08-02T00:00:00Z",
            moisture_pct=15.0, caking_index=2,
        )
        fetched_permit = validate_success(
            api.get_entry_permit(permit["id"], SM), 200
        )
        assert fetched_permit["status"] == "VOIDED"
        assert fetched_permit["void_reason"] == "AUTO_QUALITY_HAZARD"


class TestPosturePrecedence:
    def test_posture_precedence_flow_impaired_over_pending(self, api):
        """PRD §2.4: "A vessel is `FLOW_IMPAIRED` when its most recent
        `MaterialQualityReport` breaches either the vessel's moisture limit or the
        caking threshold; otherwise it is `PENDING_REPLENISHMENT` when at least one
        open `ReplenishmentOrder` (status `TRIGGERED` or `DISPATCHED`) exists for
        the vessel; otherwise it is `NORMAL`."
        PRD §3.3: "The system derives a `flowability_grade`: the report is `POOR`
        if `moisture_pct` exceeds the vessel's `moisture_limit_pct` or
        `caking_index` is at least 4; otherwise it is `MARGINAL` if `moisture_pct`
        exceeds the vessel's `moisture_limit_pct` minus 2 or `caking_index` is
        exactly 3; otherwise it is `GOOD`."

        Design: Corner/calculations/posture_precedence_flow_impaired_over_pending
        """
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={"name": "PP Site", "state_code": "IA"},
            vessel_overrides={
                "name": "SILO-PP",
                "capacity_tons": 100,
                "material_name": "flour",
                "reorder_point_pct": 30,
                "target_fill_pct": 90,
                "moisture_limit_pct": 12.0,
            },
            tech_overrides={"name": "Tech Q", "weekly_capacity_hours": 40},
        )
        # Open order -> PENDING_REPLENISHMENT first
        post_reading(vessel["id"], "2026-08-02T00:00:00Z", 25.0, site["id"])
        vessel_pending = validate_success(api.get_vessel(vessel["id"], SM), 200)
        assert vessel_pending["flow_posture"] == "PENDING_REPLENISHMENT"

        # Moisture breach while the order is still open
        report = post_quality_report(
            vessel["id"], tech["id"],
            sampled_at="2026-08-03T00:00:00Z",
            moisture_pct=13.0, caking_index=1,
        )
        # 13.0 > 12.0 -> POOR
        assert report["flowability_grade"] == "POOR"

        fetched_vessel = validate_success(api.get_vessel(vessel["id"], SM), 200)
        # FLOW_IMPAIRED wins over PENDING_REPLENISHMENT despite the open order
        assert fetched_vessel["flow_posture"] == "FLOW_IMPAIRED"
        fetched_site = validate_success(api.get_site(site["id"], SM), 200)
        assert fetched_site["site_posture"] == "CRITICAL"
