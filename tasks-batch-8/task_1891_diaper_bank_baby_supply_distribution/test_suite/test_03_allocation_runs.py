"""Monthly allocation runs: formula variants, floor/cap waterfall, lifecycle guards."""
from test_helpers import (
    NEXT_PERIOD,
    PAST_PERIOD,
    ApiErrorId,
    TEST_USERS,
    assert_allocation_line,
    create_agency,
    create_run,
    get_run,
    get_run_lines,
    init_inventory,
    post_donation,
    setup_allocation_scenario,
    size_entry,
    get_inventory,
    supply_line,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bank_admin_headers"]


class TestAllocationFormulaVariants:
    def test_need_weighted_allocates_proportional_to_children(self, api):
        """PRD §3.4: "Under `NEED_WEIGHTED`, an agency's raw share is the pool multiplied by the agency's `children_served_monthly` divided by the total `children_served_monthly` across all eligible agencies, rounded down to a whole unit; when that total is zero, every raw share is zero."
        PRD §3.4: "The eligible set is exactly the agencies whose `status` is `ACTIVE`, sorted by `children_served_monthly` descending with ties broken by `created_at` ascending."

        Design: Difficulty/dual_variant_calc/allocation_formula_need_weighted_vs_equal_split
        """
        scenario = setup_allocation_scenario(
            size_code="SIZE_1", stock_units=1000,
            agencies=((300, 100000), (100, 100000)),
            period="2026-08", formula_variant="NEED_WEIGHTED",
        )
        lines = scenario["lines"]
        assert len(lines) == 2, "Only the stocked size produces lines"
        for line in lines:
            assert_allocation_line(line)
            assert line["size_code"] == "SIZE_1"
            assert line["status"] == "PROJECTED"

        agency_a, agency_b = scenario["agencies"]
        # Lines are sorted by size_code, then children_served_monthly descending:
        # agency A (300 children) precedes agency B (100 children).
        assert lines[0]["agency_id"] == agency_a["id"]
        assert lines[1]["agency_id"] == agency_b["id"]
        # raw A = floor(1000 * 300 / 400) = 750; raw B = floor(1000 * 100 / 400) = 250.
        assert lines[0]["allocated_units"] == 750
        assert lines[1]["allocated_units"] == 250
        assert scenario["run"]["total_allocated_units"] == 1000
        assert scenario["run"]["computed_at"] is not None

    def test_equal_split_divides_pool_evenly_and_diverges(self, api):
        """PRD §3.4: "Under `EQUAL_SPLIT`, the raw share is the pool divided by the number of eligible agencies, rounded down — or zero when no agency is eligible; the floor, cap, and waterfall order are identical, but identical inputs produce different `allocated_units` under the two variants."
        PRD §3.4: "For each of the eight size codes, the pool is that size's `available_units` at compute time — on hand minus reserved, so stock already promised by other published runs is never re-promised."

        Design: Difficulty/dual_variant_calc/allocation_formula_need_weighted_vs_equal_split
        """
        scenario = setup_allocation_scenario(
            size_code="SIZE_1", stock_units=1000,
            agencies=((300, 100000), (100, 100000)),
            period="2026-08", formula_variant="NEED_WEIGHTED",
        )
        agency_a = scenario["agencies"][0]
        need_weighted_a = scenario["lines"][0]["allocated_units"]

        # A second run computes against the same available pool: neither run is
        # published, and reservations only happen at publish time.
        run_es = create_run(period=NEXT_PERIOD, formula_variant="EQUAL_SPLIT")
        compute_resp = api.compute_allocation_run(run_es["id"], ADMIN)
        assert validate_success(compute_resp, 200)["total_allocated_units"] == 1000
        es_lines = get_run_lines(run_es["id"])
        assert len(es_lines) == 2
        assert es_lines[0]["agency_id"] == agency_a["id"]
        # raw = floor(1000 / 2) = 500 for each agency.
        assert es_lines[0]["allocated_units"] == 500
        assert es_lines[1]["allocated_units"] == 500

        assert need_weighted_a == 750
        assert es_lines[0]["allocated_units"] != need_weighted_a, (
            "Identical inputs produce different allocations under the two variants"
        )


class TestFloorCapWaterfall:
    def test_capacity_cap_binds_high_share_agency(self, api):
        """PRD §3.4: "A capacity cap applies next: no agency receives more for a size than half of its `storage_capacity_units`, rounded down to a whole unit."
        PRD §3.4: "The final grant is the smallest of the raw share, the capacity cap, and the units remaining in the pool."

        Design: Difficulty/combinatorial_formula/allocation_formula_floor_cap_waterfall
        """
        scenario = setup_allocation_scenario(
            size_code="SIZE_3", stock_units=1000,
            agencies=((1000, 300), (10, 10000), (5, 10000)),
            period="2026-08",
        )
        lines = scenario["lines"]
        assert len(lines) == 3
        agency_a, _agency_b, _agency_c = scenario["agencies"]
        # Waterfall order is children_served_monthly descending: A, B, C.
        assert lines[0]["agency_id"] == agency_a["id"]
        # A's raw share is floor(1000 * 1000 / 1015) = 985, but its capacity cap
        # is floor(300 * 0.5) = 150, and the cap binds.
        assert lines[0]["allocated_units"] == 150

    def test_dignity_floor_raises_small_shares(self, api):
        """PRD §3.4: "A dignity floor applies in both variants: when an agency serves at least one child and its raw share falls below 100 units, the share is raised to 100, provided at least 100 units still remain in the pool."
        PRD §3.4: "Each compute stamps `computed_at` from the logical clock and recomputes the run's `total_allocated_units`, the sum of `allocated_units` over all its lines."

        Design: Difficulty/combinatorial_formula/allocation_formula_floor_cap_waterfall
        """
        scenario = setup_allocation_scenario(
            size_code="SIZE_3", stock_units=1000,
            agencies=((1000, 300), (10, 10000), (5, 10000)),
            period="2026-08",
        )
        lines = scenario["lines"]
        _agency_a, agency_b, agency_c = scenario["agencies"]
        assert lines[1]["agency_id"] == agency_b["id"]
        assert lines[2]["agency_id"] == agency_c["id"]
        # B's raw share floor(1000 * 10 / 1015) = 9 and C's floor(1000 * 5 / 1015) = 4
        # both fall below 100, and at least 100 units remain for each, so both
        # are raised to the 100-unit dignity floor.
        assert lines[1]["allocated_units"] == 100
        assert lines[2]["allocated_units"] == 100
        assert scenario["run"]["total_allocated_units"] == 350, (
            "150 (capped) + 100 (floor) + 100 (floor)"
        )


class TestRunLifecycleGuards:
    def test_compute_replaces_lines_idempotently(self, api):
        """PRD §3.4: "Computation is only valid from `DRAFT` (otherwise `ERR_RUN_NOT_DRAFT`); recomputing discards every line the run previously produced — whatever their status — and writes a fresh set, so recomputation is idempotent and never duplicates lines."

        Design: Corner/endpoints/compute_replaces_lines_idempotently
        """
        init_inventory()
        post_donation([supply_line("SIZE_1", 200)], donor_name="Donor C2")
        create_agency(children_served_monthly=100, storage_capacity_units=100000,
                      name="Agency C2", agency_code="AG-C2",
                      contact_email="c2@x.org")
        run = create_run(period="2026-08")

        validate_success(api.compute_allocation_run(run["id"], ADMIN), 200)
        validate_success(api.compute_allocation_run(run["id"], ADMIN), 200)

        lines = get_run_lines(run["id"])
        assert len(lines) == 1, "Two computes must not duplicate lines"
        assert lines[0]["allocated_units"] == 200
        assert lines[0]["status"] == "PROJECTED", "The run is still DRAFT"

        run_after = get_run(run["id"])
        assert run_after["status"] == "DRAFT"
        assert run_after["total_allocated_units"] == 200

    def test_run_period_in_past_rejected(self, api):
        """PRD §3.4: "The period must be unique across all runs (a repeat is rejected with `ERR_DUPLICATE_PERIOD`) and must not fall before the logical clock's current calendar month (a past period is rejected with `ERR_PERIOD_IN_PAST`)."

        Design: Corner/validations/run_period_in_past_rejected
        """
        # The logical clock starts at 2026-08-01T00:00:00Z, so 2026-07 is past.
        resp = api.create_allocation_run({"period": PAST_PERIOD}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PERIOD_IN_PAST)

    def test_run_duplicate_period_rejected(self, api):
        """PRD §3.4: "The period must be unique across all runs (a repeat is rejected with `ERR_DUPLICATE_PERIOD`) and must not fall before the logical clock's current calendar month (a past period is rejected with `ERR_PERIOD_IN_PAST`)."

        Design: Corner/validations/run_duplicate_period_rejected
        """
        create_run(period="2026-08")
        resp = api.create_allocation_run(
            {"period": "2026-08", "formula_variant": "EQUAL_SPLIT"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD)

    def test_publish_before_compute_rejected(self, api):
        """PRD §3.4: "A `BankAdmin` publishes a run — `DRAFT` → `PUBLISHED` — only when the run is still `DRAFT` (`ERR_RUN_NOT_DRAFT`), has been computed at least once (`computed_at` non-null, otherwise `ERR_RUN_NOT_COMPUTED`), and passes a final stock gate: for each size, the sum of `allocated_units` over the run's lines must not exceed the inventory's `on_hand_units` for that size (otherwise `ERR_INSUFFICIENT_STOCK`)."

        Design: Corner/validations/publish_before_compute_rejected
        """
        run = create_run(period="2026-08")
        resp = api.publish_allocation_run(run["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_COMPUTED)

        run_after = get_run(run["id"])
        assert run_after["status"] == "DRAFT"
        assert run_after["computed_at"] is None

    def test_publish_with_stock_below_allocated_rejected(self, api):
        """PRD §3.4: "A `BankAdmin` publishes a run — `DRAFT` → `PUBLISHED` — only when the run is still `DRAFT` (`ERR_RUN_NOT_DRAFT`), has been computed at least once (`computed_at` non-null, otherwise `ERR_RUN_NOT_COMPUTED`), and passes a final stock gate: for each size, the sum of `allocated_units` over the run's lines must not exceed the inventory's `on_hand_units` for that size (otherwise `ERR_INSUFFICIENT_STOCK`)."

        Design: Corner/validations/publish_with_stock_below_allocated_rejected
        """
        init_inventory()
        batch = post_donation([supply_line("SIZE_1", 300)], donor_name="Donor S")
        create_agency(children_served_monthly=300, storage_capacity_units=100000,
                      name="Agency S", agency_code="AG-S", contact_email="s@x.org")
        run = create_run(period="2026-08")
        computed = validate_success(api.compute_allocation_run(run["id"], ADMIN), 200)
        assert computed["total_allocated_units"] == 300

        # Drain the stock after compute: voiding the POSTED batch reverses it.
        validate_success(api.void_intake_batch(batch["id"], {}, TEST_USERS["warehouse_manager_headers"]), 200)
        assert size_entry(get_inventory(), "SIZE_1")["on_hand_units"] == 0

        resp = api.publish_allocation_run(run["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)

        run_after = get_run(run["id"])
        assert run_after["status"] == "DRAFT", "A rejected publish must not move the run"
        assert run_after["published_at"] is None
        assert size_entry(get_inventory(), "SIZE_1")["reserved_units"] == 0, (
            "No reservation is applied when the stock gate fails"
        )
