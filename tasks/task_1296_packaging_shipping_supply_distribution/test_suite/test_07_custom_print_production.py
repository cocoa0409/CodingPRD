"""Custom print production: the QUEUED -> PLATING -> PRINTING pipeline, the
scrap/rework loop, press occupancy, and the cancellation guard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line,
    assert_custom_print_job,
    assert_order,
    assert_order_line,
    complete_print_job,
    create_custom_product,
    create_draft_order,
    find_job_for_line,
    get_success_data,
    instants_equal,
    make_buyer_headers,
    run_job_to_printing,
    set_clock,
    setup_custom_order_with_job,
    setup_shipped_custom_order,
    setup_warehouse_and_account,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["warehouse_ops_headers"]


class TestScrapReworkCycle:
    """Line qty 100 at tolerance 10: the band is [90, 110] whole units."""

    def test_out_of_tolerance_receive_scraps_and_requeues(self, api, platform_admin_headers):
        """PRD section 3.6: "Outside the band, the run is a loss: the job
        becomes `SCRAPPED`, a replacement job is created `QUEUED` for the same
        line with `warehouse_id` copied over, and the line cycles from
        `IN_PRODUCTION` back to `OPEN` and immediately into `IN_PRODUCTION`
        again under the new job — a rework loop that may repeat."

        Design: Difficulty/non_linear_state_machine/custom_job_scrap_rework_cycle
        """
        ctx = setup_custom_order_with_job(qty=100, lead_time_days=3, tolerance_pct=10,
                                          base_price_cents=1000, sku="ML-C1",
                                          category="MAILERS", pallet_qty=1000,
                                          artwork="art-r")
        job1 = ctx["job"]
        run_job_to_printing(job1["id"])

        scrapped = validate_success(api.receive_custom_print_job(
            job1["id"], {"actual_qty": 120, "receive_note": "overrun beyond tolerance"}, OPS))
        assert scrapped["status"] == "SCRAPPED"  # 120 lies outside [90, 110]

        replacement = find_job_for_line(ctx["line"]["id"], status="QUEUED")
        assert_custom_print_job(replacement)
        assert replacement["id"] != job1["id"]
        assert replacement["warehouse_id"] == job1["warehouse_id"], "warehouse_id is copied over"

    def test_rework_completion_bills_actual_qty(self, api, platform_admin_headers,
                                                warehouse_ops_headers):
        """PRD section 3.6: "Inside the band, the job becomes `COMPLETED` with
        `actual_qty` recorded; the line becomes `ALLOCATED` with its billing
        quantity adjusted to `actual_qty`; order pricing is recomputed on the
        new quantity; and a reservation of `actual_qty` is taken at the
        allocated warehouse — but only when an inventory row exists there for
        the product, since made-to-order items may have none, in which case the
        reservation is skipped."
        PRD section 3.6: "Outside the band, the run is a loss: the job becomes
        `SCRAPPED`, a replacement job is created `QUEUED` for the same line
        with `warehouse_id` copied over, and the line cycles from
        `IN_PRODUCTION` back to `OPEN` and immediately into `IN_PRODUCTION`
        again under the new job — a rework loop that may repeat."

        Design: Difficulty/non_linear_state_machine/custom_job_scrap_rework_cycle
        """
        ctx = setup_custom_order_with_job(qty=100, lead_time_days=3, tolerance_pct=10,
                                          base_price_cents=1000, sku="ML-C1",
                                          category="MAILERS", pallet_qty=1000,
                                          artwork="art-r")
        # First run scraps at 120; the replacement completes at 105 (in band).
        complete_print_job(ctx["job"]["id"], 120)
        job2 = find_job_for_line(ctx["line"]["id"], status="QUEUED")
        finished = complete_print_job(job2["id"], 105)
        assert finished["status"] == "COMPLETED"

        shipped = validate_success(api.ship_order(ctx["order"]["id"], warehouse_ops_headers))
        assert_order(shipped)
        assert shipped["status"] == "SHIPPED"
        # Billed at produced 105 x surcharged unit ceil(1000 x 1.15) = 1150.
        assert shipped["subtotal_cents"] == 120750

        line = validate_success(api.get_order_line(ctx["line"]["id"], platform_admin_headers))
        assert_order_line(line)
        assert line["status"] == "SHIPPED"
        assert line["shipped_qty"] == 105


class TestPressOccupancy:
    """Single-press ATL; two custom orders each spawn one QUEUED job."""

    def _setup_two_queued_jobs(self, api):
        wh, acct = setup_warehouse_and_account()
        prod = create_custom_product(sku="BX-C1", base_price_cents=1000, lead_time_days=3,
                                     pallet_qty=500, weight_lbs_per_unit=5)
        set_clock("2026-08-03T10:00:00Z")  # Monday
        o1 = create_draft_order(acct["id"], ship_zone=5)
        l1 = add_line(o1["id"], acct["id"], prod["id"], 10,
                      print_artwork_ref="art-1", over_under_tolerance_pct=10)
        validate_success(api.submit_order(o1["id"], make_buyer_headers(acct["id"])))
        o2 = create_draft_order(acct["id"], ship_zone=5)
        l2 = add_line(o2["id"], acct["id"], prod["id"], 10,
                      print_artwork_ref="art-2", over_under_tolerance_pct=10)
        validate_success(api.submit_order(o2["id"], make_buyer_headers(acct["id"])))
        return find_job_for_line(l1["id"]), find_job_for_line(l2["id"])

    def test_second_start_during_occupancy_rejected_and_window_recorded(self, api):
        """PRD section 3.6: "Starting a job — `QUEUED` to `PLATING` — enforces
        press occupancy: at the job's warehouse, the count of *other* jobs in
        `PLATING` or `PRINTING` whose half-open occupancy intervals from
        `started_at` to `occupied_until` intersect the new job's prospective
        occupancy — from now through the instant `lead_time_days` business days
        after now — must be less than the facility's `press_count`."
        PRD section 3.6: "A start that would exceed the press budget is
        rejected with `ERR_PRESS_OCCUPIED` (HTTP 409). A successful start
        stamps `started_at` from the logical clock, computes `occupied_until`
        as `lead_time_days` business days after that start, and increments the
        job's `version`."

        Design: Difficulty/resource_temporal_overlap/press_occupancy_derived_duration_back_to_back
        """
        job1, job2 = self._setup_two_queued_jobs(api)
        started = validate_success(api.start_custom_print_job(job1["id"], OPS))
        assert started["status"] == "PLATING"
        # Monday 2026-08-03 + 3 business days = Thursday 2026-08-06.
        assert instants_equal(started["occupied_until"], "2026-08-06T10:00:00Z")

        resp = api.start_custom_print_job(job2["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_PRESS_OCCUPIED)

    def test_back_to_back_start_at_occupied_until_allowed(self, api):
        """PRD section 3.6: "Back-to-back scheduling is not an intersection: a
        new job starting exactly when another's `occupied_until` arrives is
        allowed."
        PRD section 3.6: "A successful start stamps `started_at` from the
        logical clock, computes `occupied_until` as `lead_time_days` business
        days after that start, and increments the job's `version`."

        Design: Difficulty/resource_temporal_overlap/press_occupancy_derived_duration_back_to_back
        """
        job1, job2 = self._setup_two_queued_jobs(api)
        validate_success(api.start_custom_print_job(job1["id"], OPS))
        validate_error(api.start_custom_print_job(job2["id"], OPS),
                       ApiErrorId.ERR_PRESS_OCCUPIED)

        set_clock("2026-08-06T10:00:00Z")  # exactly job1's occupied_until
        started2 = validate_success(api.start_custom_print_job(job2["id"], OPS))
        assert started2["status"] == "PLATING"
        assert instants_equal(started2["started_at"], "2026-08-06T10:00:00Z")
        # Thursday + 3 business days skips the weekend -> Tuesday 2026-08-11.
        assert instants_equal(started2["occupied_until"], "2026-08-11T10:00:00Z")


class TestAdvanceGuard:
    def test_advance_from_queued_is_invalid(self, api, warehouse_ops_headers):
        """PRD section 3.6: "Advancing moves `PLATING` to `PRINTING` with a
        version increment."
        PRD section 2.9: "Next, the requested transition must exist from the
        target resource's current state, including terminal-state lockdown
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/custom_job_advance_from_queued_invalid
        """
        ctx = setup_custom_order_with_job(qty=5, lead_time_days=2, sku="G-1",
                                          category="LABELS", base_price_cents=100,
                                          pallet_qty=10, weight_lbs_per_unit=1,
                                          artwork="art-g")
        resp = api.advance_custom_print_job(ctx["job"]["id"], warehouse_ops_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCustomCancelGuard:
    def _setup_two_custom_orders_one_started(self, api):
        wh, acct = setup_warehouse_and_account()
        prod = create_custom_product(sku="U-1", category="LABELS", base_price_cents=100,
                                     lead_time_days=2, pallet_qty=10,
                                     weight_lbs_per_unit=1)
        set_clock("2026-08-03T10:00:00Z")
        o_a = create_draft_order(acct["id"], ship_zone=5)
        l_a = add_line(o_a["id"], acct["id"], prod["id"], 5,
                       print_artwork_ref="art-a", over_under_tolerance_pct=10)
        validate_success(api.submit_order(o_a["id"], make_buyer_headers(acct["id"])))
        o_b = create_draft_order(acct["id"], ship_zone=5)
        l_b = add_line(o_b["id"], acct["id"], prod["id"], 5,
                       print_artwork_ref="art-b", over_under_tolerance_pct=10)
        validate_success(api.submit_order(o_b["id"], make_buyer_headers(acct["id"])))
        job_b = find_job_for_line(l_b["id"])
        validate_success(api.start_custom_print_job(job_b["id"], OPS))  # now PLATING
        return acct, o_a, l_a, o_b

    def test_cancel_with_queued_job_succeeds_and_scraps_it(self, api, platform_admin_headers):
        """PRD section 3.7: "Cancellation releases every allocated line's
        reservation (each affected row's `reserved_qty` drops, the lines become
        `CANCELLED`, the freed stock raises `available_qty` and runs the
        replenishment threshold check), scraps every still-`QUEUED` print job,
        sets `invoice_status` to `VOID`, refreshes the receivable, and
        increments `version`."

        Design: Corner/validations/error_custom_production_started_blocks_cancel
        """
        acct, o_a, l_a, o_b = self._setup_two_custom_orders_one_started(api)
        cancelled = validate_success(api.cancel_order(o_a["id"], {}, make_buyer_headers(acct["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["invoice_status"] == "VOID"

        job_a = find_job_for_line(l_a["id"])
        assert job_a["status"] == "SCRAPPED", "the cancel cascade scraps the QUEUED job"

    def test_cancel_blocked_once_job_left_queued(self, api):
        """PRD section 3.6: "Because production consumes press capacity and
        materials, cancellation is guarded: an order carrying a custom-print
        line cannot be cancelled once that line's job has left `QUEUED`, and
        the attempt is rejected with `ERR_CUSTOM_PRODUCTION_STARTED`
        (HTTP 409)."

        Design: Corner/validations/error_custom_production_started_blocks_cancel
        """
        acct, o_a, l_a, o_b = self._setup_two_custom_orders_one_started(api)
        resp = api.cancel_order(o_b["id"], {}, make_buyer_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_CUSTOM_PRODUCTION_STARTED)
