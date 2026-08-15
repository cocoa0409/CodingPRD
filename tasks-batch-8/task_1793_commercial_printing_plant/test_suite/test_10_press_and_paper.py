"""Presses, press runs, paper lots: window conflicts, state gates, paper
conservation, auto-replenishment cascade, OCC, and PO boundaries."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_estimate,
    approve_proof,
    complete_press_run,
    create_accepted_job,
    create_customer,
    create_estimate,
    create_job_in_bindery,
    create_plated_job,
    create_press,
    create_received_stock,
    create_stock,
    get_success_data,
    make_customer_headers,
    minimal_signature,
    quote_estimate,
    refresh_press,
    schedule_press_run,
    upload_proof,
    validate_error,
    validate_paginated,
    validate_success,
)

_SCH = TEST_USERS["scheduler_headers"]
_PM = TEST_USERS["plant_manager_headers"]
_PUR = TEST_USERS["purchasing_headers"]


class TestPressRunRequiresJobPlated:
    def _proof_review_job(self):
        cust = create_customer(name="X Cust")
        stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=50000)
        est, job = create_accepted_job(
            cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
            quantity_ordered=1000,
        )
        upload_proof(job["id"], "s3://j.pdf")  # -> PROOF_REVIEW, not approved
        press = create_press(name="W1")
        return cust, job, press

    def test_press_run_requires_job_plated(self, api):
        """PRD §3.6: "The press's `press_type` must match the job's
        `press_type`, else `ERR_PRESS_TYPE_MISMATCH`. The press must be
        `AVAILABLE`, else `ERR_PRESS_UNAVAILABLE`. The job must be in `PLATED`
        state." — scheduling against a PROOF_REVIEW job fails the job-state
        gate with ERR_JOB_INVALID_STATE even though press, window, OCC, and
        paper are all valid.

        Design: Difficulty/cross_entity_state_dependency/press_run_requires_job_plated
        """
        _cust, job, press = self._proof_review_job()
        resp = api.create_press_run(
            {"press_id": press["id"], "job_id": job["id"], "run_quantity": 1000,
             "scheduled_start": "2026-08-10T08:00:00Z",
             "expected_press_version": press["version"]}, _SCH)
        validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)

    def test_rejected_schedule_leaves_job_and_runs_unchanged(self, api):
        """PRD §3.6: "The press must be `AVAILABLE`, else
        `ERR_PRESS_UNAVAILABLE`. The job must be in `PLATED` state." — the
        state gate precedes any mutation, so a rejected schedule leaves the
        job in PROOF_REVIEW and records no run.

        Design: Difficulty/cross_entity_state_dependency/press_run_requires_job_plated
        """
        _cust, job, press = self._proof_review_job()
        api.create_press_run(
            {"press_id": press["id"], "job_id": job["id"], "run_quantity": 1000,
             "scheduled_start": "2026-08-10T08:00:00Z",
             "expected_press_version": press["version"]}, _SCH)
        job_after = get_success_data(api.get_job(job["id"], _PM))
        assert job_after["production_status"] == "PROOF_REVIEW"
        rows, meta = validate_paginated(api.list_press_runs(_SCH, params={"job_id": job["id"]}))
        assert meta["total_count"] == 0


class TestWashupBufferOverlap:
    def _press_and_two_jobs(self):
        cust = create_customer(name="PR Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=100000)
        ja = self._mk_job(cust, stock, "JA")
        jb = self._mk_job(cust, stock, "JB")
        press = create_press(name="W1")
        return cust, ja, jb, press

    def _mk_job(self, cust, stock, name):
        return create_plated_job(
            cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
            quantity_ordered=21000, job_name=name,
        )[1]

    def test_candidate_inside_washup_buffer_conflicts(self, api):
        """PRD §3.6: "Each existing run occupies the half-open interval from
        its `scheduled_start` to its `scheduled_end` plus the press's
        `washup_buffer_minutes` — a trailing washup buffer. A candidate run
        conflicts when its `scheduled_start` is strictly before some existing
        run's buffered end and its `scheduled_end` is strictly after that same
        run's start; such a conflict is rejected with
        `ERR_PRESS_WINDOW_CONFLICT`."
        Run A: 21000 impressions -> 171 min -> [08:00, 10:51 + 30) = 11:21;
        candidate at 11:20 conflicts.

        Design: Difficulty/resource_temporal_overlap/press_run_washup_buffer_overlap
        """
        _cust, ja, jb, press = self._press_and_two_jobs()
        ra = schedule_press_run(press, job_id=ja["id"], run_quantity=21000)
        assert ra["duration_minutes"] == 171
        assert ra["scheduled_end"] == "2026-08-10T10:51:00Z" or ra["scheduled_end"].startswith("2026-08-10T10:51")
        fresh = refresh_press(press["id"])
        resp = api.create_press_run(
            {"press_id": press["id"], "job_id": jb["id"], "run_quantity": 21000,
             "scheduled_start": "2026-08-10T11:20:00Z",
             "expected_press_version": fresh["version"]}, _SCH)
        validate_error(resp, ApiErrorId.ERR_PRESS_WINDOW_CONFLICT)

    def test_candidate_at_exact_buffered_end_allowed(self, api):
        """PRD §3.6: "A candidate starting exactly at an existing run's
        buffered end is allowed." 11:21 == 10:51 + 30 min.

        Design: Difficulty/resource_temporal_overlap/press_run_washup_buffer_overlap
        """
        _cust, ja, jb, press = self._press_and_two_jobs()
        schedule_press_run(press, job_id=ja["id"], run_quantity=21000)
        fresh = refresh_press(press["id"])
        resp = api.create_press_run(
            {"press_id": press["id"], "job_id": jb["id"], "run_quantity": 21000,
             "scheduled_start": "2026-08-10T11:21:00Z",
             "expected_press_version": fresh["version"]}, _SCH)
        data = validate_success(resp, 201)
        assert data["scheduled_start"].startswith("2026-08-10T11:21")


class TestPaperConservation:
    def _reserved_lot(self, api):
        cust = create_customer(name="PC Cust")
        stock, po = create_received_stock(name="70U", grade="UNCOATED",
                                          cost_per_sheet_cents=5, sheets=5000)
        lots, _meta = validate_paginated(
            api.list_paper_lots(_PUR, params={"paper_purchase_order_id": po["id"]}))
        lot_id = lots[0]["id"]
        _est, job, _proof = create_plated_job(
            cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
            quantity_ordered=1000, press_spoilage_pct=3, bindery_spoilage_pct=2,
        )
        press = create_press(name="W1")
        lot0 = get_success_data(api.get_paper_lot(lot_id, _PUR))
        return cust, job, press, lot_id, lot0

    def test_reserve_then_cancel_restores_conservation(self, api):
        """PRD §3.5: "The lot's `remaining_sheets` is a conservation
        invariant: `received_sheets` minus `reserved_sheets` minus
        `consumed_sheets` minus `damaged_sheets`." Receive 5000, reserve 1051
        (ceil(ceil(1000x1.03)x1.02)), then cancel releases the reservation.

        Design: Difficulty/compensating_invariant/paper_sheet_conservation_across_reserve_and_cancel
        """
        _cust, job, press, lot_id, lot0 = self._reserved_lot(api)
        assert lot0["remaining_sheets"] == 5000
        run = schedule_press_run(press, job_id=job["id"], run_quantity=1000)
        assert run["planned_sheets"] == 1051
        lot1 = get_success_data(api.get_paper_lot(lot_id, _PUR))
        assert lot1["reserved_sheets"] == 1051
        assert lot1["remaining_sheets"] == 3949
        api.cancel_press_run(run["id"], _SCH)
        lot2 = get_success_data(api.get_paper_lot(lot_id, _PUR))
        assert lot2["reserved_sheets"] == 0
        assert lot2["remaining_sheets"] == 5000, (
            "compensating cancel must restore the conserved quantity exactly"
        )

    def test_lot_conservation_holds_at_each_checkpoint(self, api):
        """PRD §3.5: "The lot's `remaining_sheets` is a conservation
        invariant: `received_sheets` minus `reserved_sheets` minus
        `consumed_sheets` minus `damaged_sheets`." The invariant is evaluated
        after receive, after schedule, and after cancel.

        Design: Difficulty/compensating_invariant/paper_sheet_conservation_across_reserve_and_cancel
        """
        _cust, job, press, lot_id, lot0 = self._reserved_lot(api)
        for snapshot in (lot0,):
            assert snapshot["remaining_sheets"] == (
                snapshot["received_sheets"] - snapshot["reserved_sheets"]
                - snapshot["consumed_sheets"] - snapshot["damaged_sheets"])
        run = schedule_press_run(press, job_id=job["id"], run_quantity=1000)
        lot1 = get_success_data(api.get_paper_lot(lot_id, _PUR))
        assert lot1["remaining_sheets"] == (
            lot1["received_sheets"] - lot1["reserved_sheets"]
            - lot1["consumed_sheets"] - lot1["damaged_sheets"])
        api.cancel_press_run(run["id"], _SCH)
        lot2 = get_success_data(api.get_paper_lot(lot_id, _PUR))
        assert lot2["remaining_sheets"] == (
            lot2["received_sheets"] - lot2["reserved_sheets"]
            - lot2["consumed_sheets"] - lot2["damaged_sheets"])


class TestAutoReplenishmentCascade:
    def _setup(self, api):
        cust = create_customer(name="PO Cust")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5,
                             reorder_threshold_sheets=5000, reorder_quantity_sheets=20000)
        po = get_success_data(api.create_paper_purchase_order(
            {"paper_stock_id": stock["id"], "ordered_sheets": 8000,
             "cost_per_sheet_cents": 5}, _PUR))
        api.receive_paper_purchase_order(po["id"], {"sheets_received": 8000}, _PUR)
        _est, job, _proof = create_plated_job(
            cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
            quantity_ordered=1000,
        )
        press = create_press(name="W2")
        run = schedule_press_run(press, job_id=job["id"], run_quantity=1000)
        return cust, stock, job, press, run

    def test_no_auto_po_before_threshold_breach(self, api):
        """PRD §3.6: auto-replenishment fires only "if it has dropped strictly
        below the stock's `reorder_threshold_sheets`" — after reserving 1000
        of 8000, available is 7000 >= 5000 so no AUTO_REPLENISH order exists.

        Design: Difficulty/transitive_cascade/press_complete_to_lot_to_auto_po_cascade
        """
        _cust, stock, _job, _press, _run = self._setup(api)
        rows, meta = validate_paginated(api.list_paper_purchase_orders(
            _PUR, params={"paper_stock_id": stock["id"], "source": "AUTO_REPLENISH"}))
        assert meta["total_count"] == 0

    def test_complete_breaching_threshold_creates_auto_po(self, api):
        """PRD §3.6: "if it has dropped strictly below the stock's
        `reorder_threshold_sheets` and no open auto-replenishment purchase
        order... already exists for the stock, the system creates one with
        `ordered_sheets` equal to the stock's `reorder_quantity_sheets`,
        `cost_per_sheet_cents` equal to the stock's `cost_per_sheet_cents`,
        `source` `AUTO_REPLENISH`, and status `ORDERED`." Completing with
        sheets_used 4000 draws available to 4000 < 5000.

        Design: Difficulty/transitive_cascade/press_complete_to_lot_to_auto_po_cascade
        """
        _cust, stock, _job, _press, run = self._setup(api)
        complete_press_run(run["id"], gross_impressions=1000, sheets_used=4000, waste_sheets=200)
        stock_after = get_success_data(api.get_paper_stock(stock["id"], _PUR))
        assert stock_after["available_sheets"] == 4000
        rows, meta = validate_paginated(api.list_paper_purchase_orders(
            _PUR, params={"paper_stock_id": stock["id"], "source": "AUTO_REPLENISH"}))
        assert meta["total_count"] == 1
        auto = rows[0]
        assert auto["ordered_sheets"] == 20000
        assert auto["cost_per_sheet_cents"] == 5
        assert auto["status"] == "ORDERED"
        # Lot: excess 3000 beyond the 1000 reservation drawn FIFO.
        lots, _m = validate_paginated(api.list_paper_lots(
            _PUR, params={"paper_stock_id": stock["id"]}))
        lot = lots[0]
        assert lot["consumed_sheets"] == 4000
        assert lot["reserved_sheets"] == 0


class TestPressRunCompleteTwice:
    def test_press_run_complete_twice_rejected(self, api):
        """PRD §3.6: "On a successful completion the run moves `SCHEDULED →
        COMPLETE`"; PRD §2.7: "State-machine validity follows, where the
        target entity must be in the required state for the operation" — a
        second complete from COMPLETE is rejected ERR_INVALID_STATE and must
        not double-consume paper (PRD §3.5 conservation).

        Design: Corner/state_machines/press_run_complete_twice_rejected
        """
        cust = create_customer(name="CT Cust")
        stock, po = create_received_stock(name="70U", grade="UNCOATED",
                                          cost_per_sheet_cents=5, sheets=5000)
        _est, job, run, _press = create_job_in_bindery(
            cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
            quantity_ordered=1000,
        )
        resp = api.complete_press_run(
            run["id"], {"gross_impressions": 1000, "sheets_used": 1000, "waste_sheets": 0}, _SCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        lots, _m = validate_paginated(api.list_paper_lots(
            _PUR, params={"paper_purchase_order_id": po["id"]}))
        assert lots[0]["consumed_sheets"] == 1000, "no double consumption"


class TestPressRunCreationErrors:
    def _three_jobs_three_presses(self):
        cust = create_customer(name="PE Cust")
        sa = create_stock(name="A", grade="UNCOATED", cost_per_sheet_cents=5)
        sb = create_stock(name="B", grade="UNCOATED", cost_per_sheet_cents=5)
        sc = create_stock(name="C", grade="UNCOATED", cost_per_sheet_cents=5)
        for s, sheets in ((sa, 1000), (sb, 1000)):
            po = get_success_data(_create_po(s["id"], sheets))
            _receive_po(po["id"], sheets)
        jobs = {}
        for key, s in (("ja", sa), ("jb", sb), ("jc", sc)):
            jobs[key] = create_plated_job(
                cust["id"], minimal_signature(s["id"], make_ready_cents=1000,
                                              rate_per_thousand_cents=1000),
                quantity_ordered=100, job_name=key.upper(),
            )[1]
        p_down = create_press(name="PD", status="DOWN")
        p_sf = create_press(name="PS", press_type="SHEETFED")
        p_ok = create_press(name="PO")
        return jobs, p_down, p_sf, p_ok

    def test_press_down_rejected(self, api):
        """PRD §3.6: "The press's `press_type` must match the job's
        `press_type`, else `ERR_PRESS_TYPE_MISMATCH`. The press must be
        `AVAILABLE`, else `ERR_PRESS_UNAVAILABLE`. The job must be in `PLATED`
        state."

        Design: Corner/errors/press_run_creation_error_battery
        """
        jobs, p_down, _p_sf, _p_ok = self._three_jobs_three_presses()
        resp = api.create_press_run(
            {"press_id": p_down["id"], "job_id": jobs["ja"]["id"], "run_quantity": 100,
             "scheduled_start": "2026-08-10T08:00:00Z",
             "expected_press_version": p_down["version"]}, _SCH)
        validate_error(resp, ApiErrorId.ERR_PRESS_UNAVAILABLE)

    def test_press_type_mismatch_rejected(self, api):
        """PRD §3.6: "The press's `press_type` must match the job's
        `press_type`, else `ERR_PRESS_TYPE_MISMATCH`."

        Design: Corner/errors/press_run_creation_error_battery
        """
        jobs, _p_down, p_sf, _p_ok = self._three_jobs_three_presses()
        resp = api.create_press_run(
            {"press_id": p_sf["id"], "job_id": jobs["jb"]["id"], "run_quantity": 100,
             "scheduled_start": "2026-08-10T08:00:00Z",
             "expected_press_version": p_sf["version"]}, _SCH)
        validate_error(resp, ApiErrorId.ERR_PRESS_TYPE_MISMATCH)

    def test_paper_insufficient_rejected(self, api):
        """PRD §3.6: "if the aggregate `remaining_sheets` across lots of a
        required stock cannot cover the reservation, scheduling is rejected
        with `ERR_PAPER_INSUFFICIENT`."

        Design: Corner/errors/press_run_creation_error_battery
        """
        jobs, _p_down, _p_sf, p_ok = self._three_jobs_three_presses()
        resp = api.create_press_run(
            {"press_id": p_ok["id"], "job_id": jobs["jc"]["id"], "run_quantity": 100,
             "scheduled_start": "2026-08-10T08:00:00Z",
             "expected_press_version": p_ok["version"]}, _SCH)
        validate_error(resp, ApiErrorId.ERR_PAPER_INSUFFICIENT)


def _create_po(stock_id, sheets):
    from test_helpers import api_client
    return api_client.create_paper_purchase_order(
        {"paper_stock_id": stock_id, "ordered_sheets": sheets, "cost_per_sheet_cents": 5}, _PUR)


def _receive_po(po_id, sheets):
    from test_helpers import api_client
    return api_client.receive_paper_purchase_order(po_id, {"sheets_received": sheets}, _PUR)


class TestPressRunOCC:
    def test_occ_press_run_create_stale_version(self, api):
        """PRD §2.4: "Scheduling a press run must carry
        `expected_press_version` matching the target press's current
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        The first run bumps the press version; replaying the pre-first-create
        version is rejected even with a free window and a PLATED job.

        Design: Corner/cross_cutting_layers/occ_press_run_create_stale_version
        """
        cust = create_customer(name="OP Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        j1 = create_plated_job(cust["id"], minimal_signature(stock["id"],
                               make_ready_cents=1000, rate_per_thousand_cents=1000),
                               quantity_ordered=100, job_name="J1")[1]
        j2 = create_plated_job(cust["id"], minimal_signature(stock["id"],
                               make_ready_cents=1000, rate_per_thousand_cents=1000),
                               quantity_ordered=100, job_name="J2")[1]
        press = create_press(name="W1")
        pv = press["version"]
        r1 = api.create_press_run(
            {"press_id": press["id"], "job_id": j1["id"], "run_quantity": 100,
             "scheduled_start": "2026-08-10T08:00:00Z", "expected_press_version": pv}, _SCH)
        validate_success(r1, 201)
        r2 = api.create_press_run(
            {"press_id": press["id"], "job_id": j2["id"], "run_quantity": 100,
             "scheduled_start": "2026-08-12T08:00:00Z", "expected_press_version": pv}, _SCH)
        validate_error(r2, ApiErrorId.ERR_STALE_VERSION)

    def test_press_version_advances_per_run_create(self, api):
        """PRD §3.6: "Successful scheduling transitions the job `PLATED →
        PRESS_SCHEDULED`, bumps the press's `version` by 1, and records the
        new run in `SCHEDULED` status." — PRD §2.4 version semantics make the
        stale replay rejectable.

        Design: Corner/cross_cutting_layers/occ_press_run_create_stale_version
        """
        cust = create_customer(name="OP2 Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        j1 = create_plated_job(cust["id"], minimal_signature(stock["id"],
                               make_ready_cents=1000, rate_per_thousand_cents=1000),
                               quantity_ordered=100, job_name="J1")[1]
        press = create_press(name="W1")
        pv = press["version"]
        r1 = api.create_press_run(
            {"press_id": press["id"], "job_id": j1["id"], "run_quantity": 100,
             "scheduled_start": "2026-08-10T08:00:00Z", "expected_press_version": pv}, _SCH)
        validate_success(r1, 201)
        after = refresh_press(press["id"])
        assert after["version"] == pv + 1


class TestPOBoundaries:
    def test_po_over_receipt_boundary(self, api, purchasing_headers):
        """PRD §3.5: "Over-receipt is capped: cumulative
        `received_sheets_total` plus the new `sheets_received` may not exceed
        `ordered_sheets` multiplied by 1.10 and rounded down to a whole sheet
        — exceeding that cap is rejected with `ERR_OVER_RECEIPT` (HTTP 422)."
        floor(1000 x 1.10) = 1100: 600+500 accepted; 600+501 rejected.

        Design: Corner/errors/po_over_receipt_battery
        """
        sa = create_stock(name="SA", grade="UNCOATED", cost_per_sheet_cents=5)
        sb = create_stock(name="SB", grade="UNCOATED", cost_per_sheet_cents=5)
        poa = get_success_data(_create_po(sa["id"], 1000))
        pob = get_success_data(_create_po(sb["id"], 1000))
        _receive_po(poa["id"], 600)
        _receive_po(pob["id"], 600)
        r_ok = api.receive_paper_purchase_order(poa["id"], {"sheets_received": 500},
                                                purchasing_headers)
        data = validate_success(r_ok, 200)
        assert data["status"] == "RECEIVED"
        assert data["received_sheets_total"] == 1100
        r_bad = api.receive_paper_purchase_order(pob["id"], {"sheets_received": 501},
                                                 purchasing_headers)
        validate_error(r_bad, ApiErrorId.ERR_OVER_RECEIPT)
        pob_after = get_success_data(api.get_paper_purchase_order(pob["id"], purchasing_headers))
        assert pob_after["status"] == "PARTIALLY_RECEIVED"
        assert pob_after["received_sheets_total"] == 600

    def test_po_receive_after_cancel_rejected(self, api, purchasing_headers):
        """PRD §3.5: "Receive or cancel attempted on an order already in
        `RECEIVED` or `CANCELLED` is rejected with `ERR_PO_STATE`."

        Design: Corner/state_machines/po_receive_after_cancel_rejected
        """
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        po = get_success_data(_create_po(stock["id"], 5000))
        _receive_po(po["id"], 2000)
        api.cancel_paper_purchase_order(po["id"], purchasing_headers)
        resp = api.receive_paper_purchase_order(po["id"], {"sheets_received": 1000},
                                                purchasing_headers)
        validate_error(resp, ApiErrorId.ERR_PO_STATE)
        after = get_success_data(api.get_paper_purchase_order(po["id"], purchasing_headers))
        assert after["received_sheets_total"] == 2000


class TestAvailableSheets:
    def test_paper_stock_available_sheets_computed(self, api):
        """PRD §3.5: "The stock's `available_sheets` is a derived quantity:
        the sum of `remaining_sheets` across all lots of that stock" and the
        lot conservation invariant nets damaged sheets out: receive 3000 +
        receive 2000 with 50 damaged -> 3000 + 1950 = 4950.

        Design: Corner/entities/paper_stock_available_sheets_computed
        """
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        po1 = get_success_data(_create_po(stock["id"], 3000))
        _receive_po(po1["id"], 3000)
        po2 = get_success_data(_create_po(stock["id"], 2000))
        from test_helpers import api_client
        api_client.receive_paper_purchase_order(
            po2["id"], {"sheets_received": 2000, "sheets_damaged": 50}, _PUR)
        after = get_success_data(api.get_paper_stock(stock["id"], _PUR))
        assert after["available_sheets"] == 4950
