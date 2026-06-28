"""Cancellation cascades and compensating invariants:
depth-3 cancel fan-out (placement -> unit -> chamber), place/remove pool
conservation, contents waterfall conservation.
"""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_paginated,
    get_success_data,
    setup_monitoring_job,
    setup_job_with_chamber,
    add_contents,
    create_claim,
    create_job,
    create_unit,
    create_chamber_payload,
    create_placement_payload,
)
from test_helpers.fixtures import (
    DISPATCHER,
    ADJUSTER,
    _place_units,
)
from test_helpers.assertions import assert_pool_conserved, assert_waterfall_conserved


# ===========================================================================
# Depth-3 cancel cascade (Difficulty/transitive_cascade)
# ===========================================================================
class TestCancelDepth3Cascade:
    def test_cancel_removes_placement_and_frees_unit(self):
        """PRD §3.6: "Hop one: every `ACTIVE` equipment placement on the job is
        moved to `REMOVED`. Hop two: each unit freed in hop one has its `status`
        set back to `AVAILABLE` and its `active_placement_id` cleared to null."

        Design: Difficulty/transitive_cascade/cancel_depth3_placement_unit_chamber
        """
        ctx = setup_monitoring_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 500000})
        job_id = ctx["job"]["id"]
        air_pl = ctx["air_placement"]
        unit_id = air_pl["equipment_unit_id"]
        cancelled = validate_success(api.cancel_job(job_id, DISPATCHER), 200)
        assert cancelled["status"] == "CANCELLED"
        pl = get_success_data(api.get_placement(air_pl["id"], DISPATCHER))
        assert pl["status"] == "REMOVED"
        unit = get_success_data(api.get_equipment_unit(unit_id, DISPATCHER))
        assert unit["status"] == "AVAILABLE"
        assert unit["active_placement_id"] is None
        assert_pool_conserved(unit)

    def test_cancel_decommissions_open_chambers_and_returns_contents(self):
        """PRD §3.6: "Hop three: every `OPEN` drying chamber on the job is moved
        to `DECOMMISSIONED`. In addition, every contents item still in
        `PACKED_OUT` or `STORED` is moved to `RETURNED`."

        Design: Difficulty/transitive_cascade/cancel_depth3_placement_unit_chamber
        """
        ctx = setup_monitoring_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 500000})
        job_id = ctx["job"]["id"]
        ch_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        packed = add_contents(job_id, tech_hdr, "Sofa", 50000)
        stored = add_contents(job_id, tech_hdr, "TV", 30000)
        get_success_data(api.store_contents(stored["id"], tech_hdr))
        validate_success(api.cancel_job(job_id, DISPATCHER), 200)
        chamber = get_success_data(api.get_chamber(ch_id, tech_hdr))
        assert chamber["status"] == "DECOMMISSIONED"
        assert get_success_data(api.get_contents(packed["id"], tech_hdr))["status"] == "RETURNED"
        assert get_success_data(api.get_contents(stored["id"], tech_hdr))["status"] == "RETURNED"


# ===========================================================================
# Compensating invariant: place/remove conserves pool availability
# (Difficulty/compensating_invariant)
# ===========================================================================
class TestPoolConservation:
    def test_place_deploys_unit(self):
        """PRD §3.4: "As a cross-entity side effect, the deployed unit's `status`
        flips to `DEPLOYED` and its `active_placement_id` is set to this
        placement's id."

        Design: Difficulty/compensating_invariant/place_remove_conserves_pool_availability
        """
        ctx = setup_job_with_chamber(certification="ASD")
        job_id = ctx["job"]["id"]
        ch_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        unit = create_unit(asset_tag="POOL-AM", kind="AIR_MOVER")
        # Before place: exactly one AVAILABLE unit in the pool.
        _, meta_before = validate_paginated(
            api.list_equipment_units(DISPATCHER, params={"status": "AVAILABLE"})
        )
        assert meta_before["total_count"] == 1
        placement = get_success_data(
            api.create_placement(
                create_placement_payload(job_id, ch_id, unit["id"]), tech_hdr
            )
        )
        deployed = get_success_data(api.get_equipment_unit(unit["id"], DISPATCHER))
        assert deployed["status"] == "DEPLOYED"
        assert deployed["active_placement_id"] == placement["id"]

    def test_remove_returns_unit_and_conserves_available_count(self):
        """PRD §3.4: "The cross-entity effect mirrors placement: the unit's
        `status` returns to `AVAILABLE` and its `active_placement_id` is cleared to
        null, returning it to the shared pool."

        Design: Difficulty/compensating_invariant/place_remove_conserves_pool_availability
        """
        ctx = setup_job_with_chamber(certification="ASD")
        job_id = ctx["job"]["id"]
        ch_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        unit = create_unit(asset_tag="POOL-AM2", kind="AIR_MOVER")
        placement = get_success_data(
            api.create_placement(
                create_placement_payload(job_id, ch_id, unit["id"]), tech_hdr
            )
        )
        # After place: 0 available.
        _, meta_deployed = validate_paginated(
            api.list_equipment_units(DISPATCHER, params={"status": "AVAILABLE"})
        )
        assert meta_deployed["total_count"] == 0
        get_success_data(api.remove_placement(placement["id"], tech_hdr))
        unit_after = get_success_data(api.get_equipment_unit(unit["id"], DISPATCHER))
        assert unit_after["status"] == "AVAILABLE"
        assert unit_after["active_placement_id"] is None
        # Conserved: AVAILABLE count returns to its pre-place value of 1.
        _, meta_after = validate_paginated(
            api.list_equipment_units(DISPATCHER, params={"status": "AVAILABLE"})
        )
        assert meta_after["total_count"] == 1


# ===========================================================================
# Compensating invariant: contents waterfall conserves allocation total
# (Difficulty/compensating_invariant)
# ===========================================================================
class TestWaterfallConservation:
    def _build_three_items(self):
        """WATER job, claim coverage 100000 deductible 0, three PACKED_OUT items
        50000/30000/40000 in created_at order."""
        claim = create_claim(coverage_limit_cents=100000, deductible_cents=0)
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        from test_helpers.test_users import make_technician_headers
        tech_hdr = make_technician_headers("tech-x")
        i1 = add_contents(job["id"], tech_hdr, "Sofa", 50000)
        i2 = add_contents(job["id"], tech_hdr, "TV", 30000)
        i3 = add_contents(job["id"], tech_hdr, "Desk", 40000)
        return claim, job, tech_hdr, (i1, i2, i3)

    def test_waterfall_allocations_in_created_at_order(self):
        """PRD §3.6: "Then walk the job's contents items whose status is
        `PACKED_OUT` or `STORED`, in `created_at` ascending order (never by id),
        and for each item allocate the smaller of the remaining pool and the
        item's `declared_value_cents` into that item's `allocated_value_cents`,
        decrementing the remaining pool by the amount allocated."

        Design: Difficulty/compensating_invariant/contents_waterfall_conserves_allocation_total
        """
        claim, job, tech_hdr, (i1, i2, i3) = self._build_three_items()
        resp = api.value_contents(job["id"], ADJUSTER)
        data = validate_success(resp, 200)
        a1 = get_success_data(api.get_contents(i1["id"], tech_hdr))
        a2 = get_success_data(api.get_contents(i2["id"], tech_hdr))
        a3 = get_success_data(api.get_contents(i3["id"], tech_hdr))
        assert a1["allocated_value_cents"] == 50000
        assert a2["allocated_value_cents"] == 30000
        assert a3["allocated_value_cents"] == 20000

    def test_waterfall_total_conserved(self):
        """PRD §3.6: "The conserved property is that the sum of allocated values
        over the included items equals the smaller of the available pool and the
        total declared value of those items."

        Design: Difficulty/compensating_invariant/contents_waterfall_conserves_allocation_total
        """
        claim, job, tech_hdr, items = self._build_three_items()
        resp = api.value_contents(job["id"], ADJUSTER)
        data = validate_success(resp, 200)
        # min(100000, 120000) == 100000
        assert data["allocated_total_cents"] == 100000
        assert_waterfall_conserved(
            data["allocated_total_cents"], claim_limit=100000, declared_total=120000
        )
