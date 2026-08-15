"""Compartment capacity, plan-finalize aggregates, and allocation totals.

Covers PRD §3.3 (allocation capacity checks and totals) and §3.4 (finalize
checks: single trailer, exact totals, GVWR).
"""
from test_helpers import (
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId as E
from test_helpers.fixtures import (
    allocate_all,
    create_load,
    create_shipper,
    create_trailer,
    get_load,
)

DISP = TEST_USERS["dispatcher_headers"]


class TestCompartmentHeadBoundary:
    def test_exactly_at_head_capacity_succeeds(self, api):
        """PRD §3.3: "the compartment's head room must suffice —
        `occupied_head_count` plus the new `head_count` may not exceed
        `max_head_count`, with a placement exactly at capacity allowed
        (`ERR_COMPARTMENT_HEAD_EXCEEDED`, HTTP 422)"

        Design: Difficulty/boundary_precision_check/compartment_head_count_exact_capacity_boundary
        """
        shipper = create_shipper()
        tt = create_trailer(compartments=[
            {"compartment_index": 1, "max_head_count": 10,
             "max_weight_lb": 50000}])
        comp_id = tt["compartments"][0]["id"]
        load = create_load(shipper["id"])

        alloc = validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": comp_id, "head_count": 10,
                 "avg_weight_lb": 1000,
                 "expected_load_version": load["version"]},
                DISP), 201)
        assert alloc["head_count"] == 10

        comps, _ = validate_paginated(
            api.list_compartments(tt["trailer"]["id"], DISP))
        assert comps[0]["occupied_head_count"] == 10

    def test_one_over_head_capacity_rejected(self, api):
        """PRD §3.3: "the compartment's head room must suffice —
        `occupied_head_count` plus the new `head_count` may not exceed
        `max_head_count`, with a placement exactly at capacity allowed
        (`ERR_COMPARTMENT_HEAD_EXCEEDED`, HTTP 422)"

        Design: Difficulty/boundary_precision_check/compartment_head_count_exact_capacity_boundary
        """
        shipper = create_shipper()
        tt = create_trailer(compartments=[
            {"compartment_index": 1, "max_head_count": 10,
             "max_weight_lb": 50000}])
        comp_id = tt["compartments"][0]["id"]
        load = create_load(shipper["id"])

        validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": comp_id, "head_count": 10,
                 "avg_weight_lb": 1000,
                 "expected_load_version": load["version"]},
                DISP), 201)
        load_after = get_load(load["id"])

        resp = api.create_allocation(
            load["id"],
            {"trailer_compartment_id": comp_id, "head_count": 1,
             "avg_weight_lb": 500,
             "expected_load_version": load_after["version"]},
            DISP)
        validate_error(resp, E.ERR_COMPARTMENT_HEAD_EXCEEDED)

        comps, _ = validate_paginated(
            api.list_compartments(tt["trailer"]["id"], DISP))
        assert comps[0]["occupied_head_count"] == 10
        assert comps[0]["occupied_weight_lb"] == 10000


class TestCompartmentWeightCapacity:
    def test_allocate_over_compartment_weight_rejected(self, api):
        """PRD §3.3: "the compartment's weight room must suffice —
        `occupied_weight_lb` plus the new allocation's `weight_lb` may not
        exceed `max_weight_lb` (`ERR_COMPARTMENT_WEIGHT_EXCEEDED`, HTTP 422)."

        Design: Corner/errors/allocate_over_compartment_weight_rejected
        """
        shipper = create_shipper()
        tt = create_trailer(compartments=[
            {"compartment_index": 1, "max_head_count": 10,
             "max_weight_lb": 10000}])
        load = create_load(shipper["id"])
        resp = api.create_allocation(
            load["id"],
            {"trailer_compartment_id": tt["compartments"][0]["id"],
             "head_count": 6, "avg_weight_lb": 2000,
             "expected_load_version": load["version"]},
            DISP)
        validate_error(resp, E.ERR_COMPARTMENT_WEIGHT_EXCEEDED)


class TestSpeciesSeparation:
    def test_allocate_swine_into_cattle_occupied_compartment_rejected(self, api):
        """PRD §3.3: "the compartment must not already hold an `ACTIVE`
        allocation of a different species (`ERR_SPECIES_MIX_FORBIDDEN`,
        HTTP 422)"

        Design: Corner/validations/allocate_swine_into_cattle_occupied_compartment_rejected
        """
        shipper = create_shipper()
        tt = create_trailer(compartments=[
            {"compartment_index": 1, "max_head_count": 10,
             "max_weight_lb": 50000}])
        comp_id = tt["compartments"][0]["id"]

        cattle = create_load(shipper["id"], declared_head_count=4,
                             declared_weight_lb=8000)
        validate_success(
            api.create_allocation(
                cattle["id"],
                {"trailer_compartment_id": comp_id, "head_count": 4,
                 "avg_weight_lb": 2000,
                 "expected_load_version": cattle["version"]},
                DISP), 201)

        swine = create_load(shipper["id"], species="SWINE",
                            declared_head_count=2, declared_weight_lb=1000,
                            planned_departure_at="2026-08-03T08:00:00Z")
        resp = api.create_allocation(
            swine["id"],
            {"trailer_compartment_id": comp_id, "head_count": 2,
             "avg_weight_lb": 500,
             "expected_load_version": swine["version"]},
            DISP)
        validate_error(resp, E.ERR_SPECIES_MIX_FORBIDDEN)

        comps, _ = validate_paginated(
            api.list_compartments(tt["trailer"]["id"], DISP))
        assert comps[0]["occupied_head_count"] == 4


class TestFinalizeAggregates:
    def test_finalize_with_gvwr_exceeded_rejected(self, api):
        """PRD §3.4: "the load's `allocated_weight_lb` must not exceed the
        trailer's `max_gross_weight_lb` (`ERR_GVWR_EXCEEDED`, HTTP 422)."

        Design: Corner/validations/finalize_with_gvwr_exceeded_rejected
        """
        shipper = create_shipper()
        tt = create_trailer(max_gross_weight_lb=30000, compartments=[
            {"compartment_index": 1, "max_head_count": 40,
             "max_weight_lb": 45000}])
        load = create_load(shipper["id"])
        allocate_all(load, [tt["compartments"][0]["id"]])

        resp = api.finalize_plan(load["id"], DISP)
        validate_error(resp, E.ERR_GVWR_EXCEEDED)
        assert get_load(load["id"])["status"] == "DRAFT"

    def test_finalize_with_head_total_mismatch_rejected(self, api):
        """PRD §3.4: "at least one `ACTIVE` allocation exists and the allocated
        totals equal the declared totals — `allocated_head_count` must equal
        `declared_head_count` and `allocated_weight_lb` must equal
        `declared_weight_lb` (`ERR_ALLOCATION_TOTAL_MISMATCH`, HTTP 422)"

        Design: Corner/validations/finalize_with_head_total_mismatch_rejected
        """
        shipper = create_shipper()
        tt = create_trailer()
        load = create_load(shipper["id"], declared_head_count=40,
                           declared_weight_lb=30000)
        validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": tt["compartments"][0]["id"],
                 "head_count": 30, "avg_weight_lb": 1000,
                 "expected_load_version": load["version"]},
                DISP), 201)
        resp = api.finalize_plan(load["id"], DISP)
        validate_error(resp, E.ERR_ALLOCATION_TOTAL_MISMATCH)

    def test_finalize_with_mixed_trailers_rejected(self, api):
        """PRD §3.4: "every `ACTIVE` allocation belongs to compartments of a
        single trailer (`ERR_MIXED_TRAILER_ALLOCATIONS`, HTTP 422)"

        Design: Corner/validations/finalize_with_mixed_trailers_rejected
        """
        shipper = create_shipper()
        t1 = create_trailer()
        t2 = create_trailer()
        load = create_load(shipper["id"])
        allocate_all(load, [t1["compartments"][0]["id"]],
                     head_per_alloc=20, avg_weight_lb=2000)
        load_mid = get_load(load["id"])
        validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": t2["compartments"][0]["id"],
                 "head_count": 20, "avg_weight_lb": 2000,
                 "expected_load_version": load_mid["version"]},
                DISP), 201)

        resp = api.finalize_plan(load["id"], DISP)
        validate_error(resp, E.ERR_MIXED_TRAILER_ALLOCATIONS)
        assert get_load(load["id"])["trailer_id"] is None


class TestAllocationReleaseRoundtrip:
    def test_allocate_release_roundtrip_restores_capacity(self, api):
        """PRD §3.3: "A `Dispatcher` may also release an allocation manually.
        The load must be `DRAFT` (`ERR_LOAD_NOT_DRAFT`) and the request must
        carry `expected_load_version` matching the load's current `version`
        (`ERR_STALE_VERSION`). The allocation's `status` becomes `RELEASED`
        with `release_reason` `REPLANNED`; the compartment occupancy and the
        load's totals are recomputed; and the load `version` increments by 1."
        PRD §3.3: "Creating an allocation recomputes the compartment's
        occupancy and the load's totals and increments the load `version` by
        1."

        Design: Difficulty/compensating_invariant/compartment_capacity_allocate_release_roundtrip_invariant
        """
        shipper = create_shipper()
        tt = create_trailer(compartments=[
            {"compartment_index": 1, "max_head_count": 10,
             "max_weight_lb": 20000}])
        comp_id = tt["compartments"][0]["id"]
        load = create_load(shipper["id"])
        assert load["version"] == 1

        # forward action: allocate 6 head / 12000 lb
        alloc = validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": comp_id, "head_count": 6,
                 "avg_weight_lb": 2000,
                 "expected_load_version": load["version"]},
                DISP), 201)
        mid = get_load(load["id"])
        assert mid["version"] == 2

        # compensating action: release restores the conserved capacity exactly
        validate_success(
            api.release_allocation(
                alloc["id"], {"expected_load_version": mid["version"]},
                DISP), 200)

        comps, _ = validate_paginated(
            api.list_compartments(tt["trailer"]["id"], DISP))
        assert comps[0]["occupied_head_count"] == 0
        assert comps[0]["occupied_weight_lb"] == 0

        final = get_load(load["id"])
        assert final["allocated_head_count"] == 0
        assert final["allocated_weight_lb"] == 0
        # exactly +2 over creation: one for allocate, one for release
        assert final["version"] == 3

        alloc_after = validate_success(api.get_allocation(alloc["id"], DISP))
        assert alloc_after["status"] == "RELEASED"
        assert alloc_after["release_reason"] == "REPLANNED"

    def test_allocate_release_roundtrip_allows_fresh_reallocation(self, api):
        """PRD §3.3: "A `Dispatcher` may also release an allocation manually.
        The load must be `DRAFT` (`ERR_LOAD_NOT_DRAFT`) and the request must
        carry `expected_load_version` matching the load's current `version`
        (`ERR_STALE_VERSION`). The allocation's `status` becomes `RELEASED`
        with `release_reason` `REPLANNED`; the compartment occupancy and the
        load's totals are recomputed; and the load `version` increments by 1."
        PRD §3.3: "The load's `allocated_head_count` and `allocated_weight_lb`
        are the sums of `head_count` and `weight_lb` over its `ACTIVE`
        allocations only; `RELEASED` rows are excluded."

        Design: Difficulty/compensating_invariant/compartment_capacity_allocate_release_roundtrip_invariant
        """
        shipper = create_shipper()
        tt = create_trailer(compartments=[
            {"compartment_index": 1, "max_head_count": 10,
             "max_weight_lb": 20000}])
        comp_id = tt["compartments"][0]["id"]
        load = create_load(shipper["id"])

        alloc = validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": comp_id, "head_count": 6,
                 "avg_weight_lb": 2000,
                 "expected_load_version": load["version"]},
                DISP), 201)
        validate_success(
            api.release_allocation(
                alloc["id"],
                {"expected_load_version": get_load(load["id"])["version"]},
                DISP), 200)

        # after the round-trip the compartment is empty, so a fresh allocation
        # against the current version succeeds
        validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": comp_id, "head_count": 4,
                 "avg_weight_lb": 1000,
                 "expected_load_version": get_load(load["id"])["version"]},
                DISP), 201)
        final = get_load(load["id"])
        assert final["allocated_head_count"] == 4
        assert final["allocated_weight_lb"] == 4000
        comps, _ = validate_paginated(
            api.list_compartments(tt["trailer"]["id"], DISP))
        assert comps[0]["occupied_head_count"] == 4


class TestImmediateConsistency:
    def test_post_allocation_get_load_reflects_totals_immediately(self, api):
        """PRD §2.9: "Derived fields are never cached stale: every derived
        value described in §3 is recomputed within the request that triggers
        it, and reads of a driver or a trailer recompute that resource's
        derived fields at read time."
        PRD §3.3: "Creating an allocation recomputes the compartment's
        occupancy and the load's totals and increments the load `version` by
        1."

        Design: Corner/consistency_model/post_allocation_get_load_reflects_totals_immediately
        """
        shipper = create_shipper()
        tt = create_trailer()
        load = create_load(shipper["id"])
        before_version = load["version"]

        validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": tt["compartments"][0]["id"],
                 "head_count": 6, "avg_weight_lb": 2000,
                 "expected_load_version": before_version},
                DISP), 201)

        # the read immediately after the write reflects the updated totals
        load_after = get_load(load["id"])
        assert load_after["allocated_head_count"] == 6
        assert load_after["allocated_weight_lb"] == 12000
        assert load_after["version"] == before_version + 1

        comps, _ = validate_paginated(
            api.list_compartments(tt["trailer"]["id"], DISP))
        assert comps[0]["occupied_head_count"] == 6
        assert comps[0]["occupied_weight_lb"] == 12000


class TestAllocationTotalsFiltering:
    def test_load_totals_aggregate_only_active_allocations(self, api):
        """PRD §3.3: "The load's `allocated_head_count` and
        `allocated_weight_lb` are the sums of `head_count` and `weight_lb` over
        its `ACTIVE` allocations only; `RELEASED` rows are excluded."

        Design: Corner/calculations/load_totals_aggregate_only_active_allocations
        """
        shipper = create_shipper()
        tt = create_trailer()
        comp_id = tt["compartments"][0]["id"]
        load = create_load(shipper["id"])

        alloc = validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": comp_id, "head_count": 6,
                 "avg_weight_lb": 1000,
                 "expected_load_version": load["version"]},
                DISP), 201)
        load_v2 = get_load(load["id"])
        validate_success(
            api.release_allocation(
                alloc["id"],
                {"expected_load_version": load_v2["version"]},
                DISP), 200)
        load_v3 = get_load(load["id"])
        validate_success(
            api.create_allocation(
                load["id"],
                {"trailer_compartment_id": comp_id, "head_count": 4,
                 "avg_weight_lb": 1000,
                 "expected_load_version": load_v3["version"]},
                DISP), 201)

        load_final = get_load(load["id"])
        assert load_final["allocated_head_count"] == 4
        assert load_final["allocated_weight_lb"] == 4000
        comps, _ = validate_paginated(
            api.list_compartments(tt["trailer"]["id"], DISP))
        assert comps[0]["occupied_head_count"] == 4
