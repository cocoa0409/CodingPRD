"""Shelf-space allocation (overlap, exclusivity, capacity gates) and seasonal
set lifecycle with teardown penalties."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_space_allocation_payload,
    get_seasonal_set,
    get_success_data,
    make_route_driver_headers,
    new_active_agreement,
    new_program,
    new_seasonal_set,
    new_space_allocation,
    new_store,
    set_clock,
    setup_shop,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["jobber_admin_headers"]
DRIVER = TEST_USERS["route_driver_headers"]


class TestSpaceWindowShape:
    def test_window_inverted_rejected(self, api):
        """PRD section 3.4: "An inverted window — start not before end under
        the half-open convention — is rejected with `ERR_WINDOW_INVALID`."

        Design: Corner/validations/window_inverted_rejected
        """
        ctx = setup_shop(with_product=False)
        res = api.create_space_allocation(
            create_space_allocation_payload(
                ctx["agreement"]["id"], category="SNACKS", facings=4,
                window_start_date="2026-09-01", window_end_date="2026-08-01"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_WINDOW_INVALID)

    def test_facings_below_range_rejected(self, api):
        """PRD section 2.8: "Numeric ranges: `quantity`, `facings`, and `units`
        must be at least 1; percentage fields must lie between 0 and 1
        inclusive; promotion depth must be greater than 0 and at most 0.50;
        prices must be at least 1 cent. Violations fail with
        `ERR_RANGE_INVALID` (HTTP 422)."

        Design: Corner/validations/facings_below_range_rejected
        """
        ctx = setup_shop(with_product=False)
        res = api.create_space_allocation(
            create_space_allocation_payload(
                ctx["agreement"]["id"], category="SNACKS", facings=0,
                window_start_date="2026-08-01", window_end_date="2026-09-01"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_RANGE_INVALID)


class TestSpaceOverlapAdjacency:
    def test_touching_windows_do_not_intersect(self, api):
        """PRD section 3.4: "Two half-open windows intersect when each starts
        before the other ends; windows that merely touch — one beginning on the
        very day the other ends — do not intersect."

        Design: Difficulty/resource_temporal_overlap/space_allocation_half_open_adjacency
        """
        ctx = setup_shop(with_product=False,
                         store_overrides={"total_facings": 100})
        agreement = ctx["agreement"]
        w1 = new_space_allocation(
            agreement["id"], category="SNACKS", facings=10,
            window_start_date="2026-08-01", window_end_date="2026-09-01")
        assert w1["status"] == "ACTIVE", (
            "a window covering the clock date at creation lands ACTIVE")
        w2 = validate_success(api.create_space_allocation(
            create_space_allocation_payload(
                agreement["id"], category="SNACKS", facings=10,
                window_start_date="2026-09-01", window_end_date="2026-10-01"),
            ADMIN), 201)
        assert w2["status"] == "PLANNED", (
            "a future window lands PLANNED; adjacency is permitted")

    def test_one_day_intersection_rejected(self, api):
        """PRD section 3.4: "The overlap gate rejects a candidate whose window
        intersects another non-closed allocation of the same store, same
        category, and same program with `ERR_SPACE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/space_allocation_half_open_adjacency
        """
        ctx = setup_shop(with_product=False,
                         store_overrides={"total_facings": 100})
        agreement = ctx["agreement"]
        new_space_allocation(
            agreement["id"], category="SNACKS", facings=10,
            window_start_date="2026-08-01", window_end_date="2026-09-01")
        res = api.create_space_allocation(
            create_space_allocation_payload(
                agreement["id"], category="SNACKS", facings=5,
                window_start_date="2026-08-31", window_end_date="2026-10-01"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_SPACE_WINDOW_OVERLAP)


class TestSpaceCapacityBoundary:
    def test_exact_fit_at_total_facings_allowed(self, api):
        """PRD section 3.4: "The capacity gate sums the `facings` of every
        overlapping allocation of the store in `PLANNED` or `ACTIVE` status,
        adds the candidate's `facings`, and rejects with
        `ERR_SPACE_CAPACITY_EXCEEDED` only when that committed total strictly
        exceeds the store's `total_facings` — a commitment exactly equal to
        capacity is allowed."

        Design: Difficulty/boundary_precision_check/space_capacity_exact_fit_boundary
        """
        ctx = setup_shop(with_product=False,
                         store_overrides={"total_facings": 10})
        agreement = ctx["agreement"]
        new_space_allocation(
            agreement["id"], category="SNACKS", facings=6,
            window_start_date="2026-08-01", window_end_date="2026-09-01")
        w2 = validate_success(api.create_space_allocation(
            create_space_allocation_payload(
                agreement["id"], category="BEVERAGES", facings=4,
                window_start_date="2026-08-10", window_end_date="2026-08-20"),
            ADMIN), 201)
        assert w2["status"] == "PLANNED", (
            "6 + 4 == 10 == total_facings: equality is allowed")

    def test_one_facing_over_capacity_rejected(self, api):
        """PRD section 3.4: "The capacity gate sums the `facings` of every
        overlapping allocation of the store in `PLANNED` or `ACTIVE` status,
        adds the candidate's `facings`, and rejects with
        `ERR_SPACE_CAPACITY_EXCEEDED` only when that committed total strictly
        exceeds the store's `total_facings` — a commitment exactly equal to
        capacity is allowed."

        Design: Difficulty/boundary_precision_check/space_capacity_exact_fit_boundary
        """
        ctx = setup_shop(with_product=False,
                         store_overrides={"total_facings": 10})
        agreement = ctx["agreement"]
        new_space_allocation(
            agreement["id"], category="SNACKS", facings=6,
            window_start_date="2026-08-01", window_end_date="2026-09-01")
        new_space_allocation(
            agreement["id"], category="BEVERAGES", facings=4,
            window_start_date="2026-08-10", window_end_date="2026-08-20")
        res = api.create_space_allocation(
            create_space_allocation_payload(
                agreement["id"], category="IMPULSE", facings=1,
                window_start_date="2026-08-10", window_end_date="2026-08-20"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_SPACE_CAPACITY_EXCEEDED)


class TestSpaceGatePrecedence:
    def test_overlap_outranks_capacity(self, api):
        """PRD section 3.4: "Three independent gates guard creation, evaluated
        in the precedence order of §2.8: same-program overlap first,
        cross-program exclusivity second, physical capacity third."

        Design: Difficulty/priority_pair_validation_conflict/space_create_temporal_beats_constraint
        """
        ctx = setup_shop(with_product=False,
                         store_overrides={"total_facings": 10})
        agreement = ctx["agreement"]
        new_space_allocation(
            agreement["id"], category="SNACKS", facings=6,
            window_start_date="2026-08-01", window_end_date="2026-09-01")
        # Candidate both overlaps (same store/category/program) and breaches
        # capacity (6 + 6 = 12 > 10); the overlap gate sits higher.
        res = api.create_space_allocation(
            create_space_allocation_payload(
                agreement["id"], category="SNACKS", facings=6,
                window_start_date="2026-08-15", window_end_date="2026-09-15"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_SPACE_WINDOW_OVERLAP)
        rows, meta = validate_paginated(api.list_space_allocations(
            ADMIN, params={"store_agreement_id": agreement["id"]}))
        assert meta["total_count"] == 1, (
            "the rejected candidate persisted nothing")

    def test_capacity_fires_when_no_overlap(self, api):
        """PRD section 3.4: "Three independent gates guard creation, evaluated
        in the precedence order of §2.8: same-program overlap first,
        cross-program exclusivity second, physical capacity third."
        PRD section 3.4: "The capacity gate sums the `facings` of every
        overlapping allocation of the store in `PLANNED` or `ACTIVE` status,
        adds the candidate's `facings`, and rejects with
        `ERR_SPACE_CAPACITY_EXCEEDED` only when that committed total strictly
        exceeds the store's `total_facings` — a commitment exactly equal to
        capacity is allowed."

        Design: Difficulty/priority_pair_validation_conflict/space_create_temporal_beats_constraint
        """
        ctx = setup_shop(with_product=False,
                         store_overrides={"total_facings": 10})
        agreement = ctx["agreement"]
        new_space_allocation(
            agreement["id"], category="SNACKS", facings=6,
            window_start_date="2026-08-01", window_end_date="2026-09-01")
        # Different category: no same-program overlap; capacity alone fails
        # (6 + 6 = 12 > 10), proving the fiscal-style gate exists below the
        # temporal one.
        res = api.create_space_allocation(
            create_space_allocation_payload(
                agreement["id"], category="BEVERAGES", facings=6,
                window_start_date="2026-08-15", window_end_date="2026-09-15"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_SPACE_CAPACITY_EXCEEDED)


class TestCategoryExclusivity:
    def test_cross_program_category_conflict_rejected(self, api):
        """PRD section 3.4: "The exclusivity gate enforces category exclusivity
        across programs: a candidate whose window intersects an allocation of
        the same store and same category owned by a different program is
        rejected with `ERR_CATEGORY_EXCLUSIVE_CONFLICT`."

        Design: Corner/validations/category_exclusivity_conflict_rejected
        """
        set_clock()
        program_a = new_program(name="Excl A")
        program_b = new_program(name="Excl B")
        store = new_store(name="ExclStore", store_code="EXC",
                          total_facings=100)
        agr_a = new_active_agreement(program_a["id"], store["id"])
        agr_b = new_active_agreement(program_b["id"], store["id"])
        new_space_allocation(
            agr_a["id"], category="SNACKS", facings=4,
            window_start_date="2026-08-01", window_end_date="2026-09-01")
        res = api.create_space_allocation(
            create_space_allocation_payload(
                agr_b["id"], category="SNACKS", facings=4,
                window_start_date="2026-08-15", window_end_date="2026-09-15"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_CATEGORY_EXCLUSIVE_CONFLICT)


class TestSpaceAllocationSweep:
    def test_planned_allocation_activates_on_sweep(self, api):
        """PRD section 2.6: "A planned space allocation whose window has opened
        becomes `ACTIVE`, provided its agreement is `ACTIVE`."
        PRD section 3.4: "A window covering the clock date at creation lands
        `ACTIVE`; a future window lands `PLANNED` and is opened by the time
        sweep, provided the agreement is `ACTIVE` at that moment."

        Design: Corner/state_machines/space_allocation_sweep_activation
        """
        ctx = setup_shop(with_product=False)
        alloc = new_space_allocation(
            ctx["agreement"]["id"], category="BEVERAGES", facings=5,
            window_start_date="2026-08-10", window_end_date="2026-09-01")
        assert alloc["status"] == "PLANNED"
        set_clock("2026-08-10T00:00:00Z")
        after = get_success_data(
            api.get_space_allocation(alloc["id"], ADMIN))
        assert after["status"] == "ACTIVE"


class TestSeasonalSetLifecycle:
    def test_begin_setup_outside_window_rejected(self, api):
        """PRD section 3.4: "A `RouteDriver` begins setup — `PLANNED` to
        `SET_IN_PROGRESS` — only while the clock date lies within the closed
        setup window, failing with `ERR_SEASONAL_WINDOW_NOT_OPEN` otherwise".

        Design: Corner/state_machines/seasonal_begin_setup_outside_window_rejected
        """
        ctx = setup_shop(with_product=False)
        seasonal = new_seasonal_set(ctx["agreement"]["id"], theme="Halloween",
                                    set_window_start="2026-08-05",
                                    set_window_end="2026-08-10",
                                    teardown_deadline="2026-08-20")
        res = api.begin_setup_seasonal_set(
            seasonal["id"], make_route_driver_headers("drv-1"))
        validate_error(res, ApiErrorId.ERR_SEASONAL_WINDOW_NOT_OPEN)
        after = get_seasonal_set(seasonal["id"])
        assert after["status"] == "PLANNED"

    def test_complete_setup_without_allocation_rejected(self, api):
        """PRD section 3.4: "completes setup — `SET_IN_PROGRESS` to
        `SET_COMPLETE` — only when an `ACTIVE` space allocation exists for the
        agreement in the set's category with facings at least equal to
        `allocated_facings`, failing with `ERR_SEASONAL_ALLOCATION_MISSING`
        otherwise."

        Design: Corner/validations/seasonal_complete_setup_without_allocation_rejected
        """
        ctx = setup_shop(with_product=False)
        seasonal = new_seasonal_set(ctx["agreement"]["id"], theme="NoAlloc Set",
                                    allocated_facings=2,
                                    set_window_start="2026-08-05",
                                    set_window_end="2026-08-10",
                                    teardown_deadline="2026-08-20")
        set_clock("2026-08-05T00:00:00Z")
        begun = validate_success(api.begin_setup_seasonal_set(
            seasonal["id"], make_route_driver_headers("drv-1")), 200)
        assert begun["status"] == "SET_IN_PROGRESS"
        res = api.complete_setup_seasonal_set(
            seasonal["id"], make_route_driver_headers("drv-1"))
        validate_error(res, ApiErrorId.ERR_SEASONAL_ALLOCATION_MISSING)
        after = get_seasonal_set(seasonal["id"])
        assert after["status"] == "SET_IN_PROGRESS"

    def test_late_teardown_penalty_and_reconcile(self, api):
        """PRD section 3.4: "The penalty grants a two-day grace period: the
        days late are the calendar days between `teardown_deadline` and
        `actual_teardown_date`, minus two, floored at zero; the penalty is the
        days late multiplied by 2500 cents per day, capped at 100000 cents. A
        deadline of 2026-08-20 with teardown on 2026-08-25 is five days late,
        three after grace, and costs 7500 cents."
        PRD section 3.4: "Once the clock passes `teardown_deadline`, the sweep
        moves `ACTIVE_SEASON` to `TEARDOWN_DUE`."

        Design: Corner/state_machines/seasonal_late_teardown_penalty
        """
        ctx = setup_shop(with_product=False)
        agreement = ctx["agreement"]
        new_space_allocation(
            agreement["id"], category="SEASONAL", facings=4,
            window_start_date="2026-08-01", window_end_date="2026-09-01")
        seasonal = new_seasonal_set(
            agreement["id"], theme="Halloween", category="SEASONAL",
            allocated_facings=4, set_window_start="2026-08-05",
            set_window_end="2026-08-10", teardown_deadline="2026-08-20")
        set_clock("2026-08-05T00:00:00Z")
        driver = make_route_driver_headers("drv-1")
        validate_success(api.begin_setup_seasonal_set(seasonal["id"], driver),
                         200)
        validate_success(
            api.complete_setup_seasonal_set(seasonal["id"], driver), 200)
        validate_success(api.activate_seasonal_set(seasonal["id"], ADMIN), 200)
        set_clock("2026-08-25T00:00:00Z")
        mid = get_seasonal_set(seasonal["id"])
        assert mid["status"] == "TEARDOWN_DUE", (
            "sweep past the deadline moves ACTIVE_SEASON to TEARDOWN_DUE")
        torn = validate_success(
            api.teardown_seasonal_set(seasonal["id"], driver), 200)
        assert torn["status"] == "TORN_DOWN"
        assert torn["actual_teardown_date"] == "2026-08-25"
        assert torn["penalty_cents"] == 7500, (
            "five days late minus two grace days, times 2500 cents per day")
        reconciled = validate_success(
            api.reconcile_seasonal_set(seasonal["id"], ADMIN), 200)
        assert reconciled["status"] == "RECONCILED"
