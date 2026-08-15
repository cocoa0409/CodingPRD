"""Read endpoints and filtered reverse reads, plus job list filtering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_estimate,
    approve_proof,
    create_accepted_job,
    create_bindery_ticket_payload,
    create_customer,
    create_estimate,
    create_gang_run,
    create_mail_drop_for_job,
    create_plated_job,
    create_press,
    create_received_stock,
    create_stock,
    get_success_data,
    make_customer_headers,
    minimal_signature,
    quote_estimate,
    schedule_press_run,
    upload_proof,
    validate_paginated,
    validate_success,
)

_PM = TEST_USERS["plant_manager_headers"]
_EST = TEST_USERS["estimator_headers"]
_PRE = TEST_USERS["prepress_headers"]
_SCH = TEST_USERS["scheduler_headers"]
_PUR = TEST_USERS["purchasing_headers"]
_MAIL = TEST_USERS["mail_headers"]


class TestJobSnapshot:
    def test_job_snapshot_fields_from_accept(self, api):
        """PRD §3.3: "On a successful accept, the system creates a `Job`
        snapshotting the estimate: `estimate_id` is set, `parent_job_id` is
        null, `customer_id` is denormalized from the estimate, `zero_charge`
        is false... and `tolerance_pct` is the customer's
        `default_tolerance_pct` at the moment of acceptance. The job begins
        with `production_status` `PREPRESS` and `billing_status` `UNBILLED`."

        Design: Corner/entities/job_snapshot_fields_from_accept
        """
        cust = create_customer(name="Snap Cust", default_tolerance_pct=7)
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        est = create_estimate(cust["id"], minimal_signature(stock["id"],
                              make_ready_cents=50000),
                              quantity_ordered=1000, job_name="Snap")
        quote_estimate(est["id"])
        job = accept_estimate(est["id"], cust["id"])
        assert job["total_price_cents"] == 85000
        assert job["tolerance_pct"] == 7
        assert job["production_status"] == "PREPRESS"
        assert job["billing_status"] == "UNBILLED"
        assert job["zero_charge"] is False
        assert job["estimate_id"] == est["id"]
        assert job["parent_job_id"] is None
        assert job["gang_run_id"] is None


class TestJobsListFiltering:
    def test_jobs_list_filter_by_customer_and_status(self, api):
        """PRD §3.15: "Jobs may be listed filtered by `customer_id`,
        `estimate_id`, `gang_run_id`, `parent_job_id`, `production_status`,
        or `billing_status`."

        Design: Corner/endpoints/jobs_list_filter_by_customer_and_status
        """
        ca = create_customer(name="FA")
        cb = create_customer(name="FB")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        for c, names in ((ca, ("A1", "A2")), (cb, ("B1",))):
            for n in names:
                create_accepted_job(c["id"], minimal_signature(stock["id"],
                                    make_ready_cents=1000, rate_per_thousand_cents=1000),
                                    quantity_ordered=100, job_name=n)
        rows, meta = validate_paginated(api.list_jobs(
            _PM, params={"customer_id": ca["id"], "production_status": "PREPRESS"}))
        assert meta["total_count"] == 2
        for row in rows:
            assert row["customer_id"] == ca["id"]
            assert row["production_status"] == "PREPRESS"


class TestResourceReadback:
    def _scenario(self):
        cust = create_customer(name="RB Cust")
        stock, po = create_received_stock(name="70U", grade="UNCOATED",
                                          cost_per_sheet_cents=5, sheets=5000)
        e1 = create_estimate(cust["id"], minimal_signature(stock["id"],
                             make_ready_cents=1000, rate_per_thousand_cents=1000),
                             quantity_ordered=100, job_name="SHIP")
        e2 = create_estimate(cust["id"], minimal_signature(stock["id"],
                             make_ready_cents=1000, rate_per_thousand_cents=1000),
                             quantity_ordered=100, job_name="MAIL",
                             fulfillment_type="MAIL")
        quote_estimate(e1["id"])
        quote_estimate(e2["id"])
        j1 = accept_estimate(e1["id"], cust["id"])
        j2 = accept_estimate(e2["id"], cust["id"])
        proof = upload_proof(j1["id"], "s3://r.pdf")
        approve_proof(proof["id"], cust["id"])
        press = create_press(name="W1")
        run = schedule_press_run(press, job_id=j1["id"], run_quantity=100)
        bt = get_success_data(_create_ticket(j1["id"]))
        gang = create_gang_run(stock["id"])
        drop = create_mail_drop_for_job(j2["id"], [{"zip5": "94101", "pieces": 100}])
        return {
            "cust": cust, "stock": stock, "po": po, "e1": e1, "e2": e2,
            "j1": j1, "j2": j2, "proof": proof, "press": press,
            "run": run, "bt": bt, "gang": gang, "drop": drop,
        }

    def test_estimate_and_proof_readback(self, api):
        """PRD §2.8: "Reverse reads of these relationships are performed
        through filtered list endpoints." GET endpoints return the persisted
        resources (PRD §4).

        Design: Corner/endpoints/resource_readback_battery
        """
        s = self._scenario()
        est = get_success_data(api.get_estimate(s["e1"]["id"], _EST))
        assert est["total_price_cents"] == 1600, (
            "subtotal 1000 make-ready + 100 running + 500 paper = 1600, 0% tier"
        )
        proof = get_success_data(api.get_proof(s["proof"]["id"], _PRE))
        assert proof["status"] == "APPROVED"
        rows, meta = validate_paginated(api.list_proofs(_PRE, params={"job_id": s["j1"]["id"]}))
        assert meta["total_count"] == 1

    def test_bindery_gang_press_run_readback(self, api):
        """PRD §2.8: "Reverse reads of these relationships are performed
        through filtered list endpoints — for example, listing jobs by
        `gang_run_id` or by `parent_job_id` — rather than through nested URL
        hierarchies, because all resources are top-level." Bindery tickets,
        gang runs, presses, and press runs read back their persisted state.

        Design: Corner/endpoints/resource_readback_battery
        """
        s = self._scenario()
        bt = get_success_data(api.get_bindery_ticket(s["bt"]["id"], _PM))
        assert bt["status"] == "QUEUED"
        rows, meta = validate_paginated(api.list_bindery_tickets(_PM, params={"job_id": s["j1"]["id"]}))
        assert meta["total_count"] == 1
        gangs, gmeta = validate_paginated(api.list_gang_runs(
            _SCH, params={"status": "FORMING", "paper_stock_id": s["stock"]["id"]}))
        assert any(g["id"] == s["gang"]["id"] for g in gangs)
        presses, pmeta = validate_paginated(api.list_presses(_SCH, params={"press_type": "WEB"}))
        assert any(p["id"] == s["press"]["id"] for p in presses)
        run = get_success_data(api.get_press_run(s["run"]["id"], _SCH))
        assert run["status"] == "SCHEDULED"
        assert run["planned_impressions"] == 100
        runs, rmeta = validate_paginated(api.list_press_runs(
            _SCH, params={"press_id": s["press"]["id"], "job_id": s["j1"]["id"]}))
        assert rmeta["total_count"] == 1

    def test_po_stock_and_mail_drop_readback(self, api):
        """PRD §4 read endpoints: purchase orders, paper stocks, and mail
        drops read back persisted state; §3.9: "The drop lands in `PLANNED`
        with `total_pieces` computed as the sum of the per-entry piece
        counts."

        Design: Corner/endpoints/resource_readback_battery
        """
        s = self._scenario()
        po = get_success_data(api.get_paper_purchase_order(s["po"]["id"], _PUR))
        assert po["status"] == "RECEIVED"
        stocks, smeta = validate_paginated(api.list_paper_stocks(_PUR))
        assert smeta["total_count"] == 1
        drop = get_success_data(api.get_mail_drop(s["drop"]["id"], _MAIL))
        assert drop["status"] == "PLANNED"
        assert drop["total_pieces"] == 100
        drops, dmeta = validate_paginated(api.list_mail_drops(_MAIL, params={"job_id": s["j2"]["id"]}))
        assert dmeta["total_count"] == 1


def _create_ticket(job_id):
    from test_helpers import api_client
    return api_client.create_bindery_ticket(
        {"job_id": job_id, "operation": "FOLD", "sequence_no": 1}, _PM)
