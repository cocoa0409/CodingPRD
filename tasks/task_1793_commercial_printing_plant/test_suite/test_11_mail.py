"""Mail drops: presort waterfall tiers, daily aggregate capacity, the
drop-state gate, and the fulfillment channel boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_estimate,
    approve_proof,
    complete_bindery_and_deliver,
    complete_press_run,
    create_accepted_job,
    create_customer,
    create_fulfilled_mail_job,
    create_job_in_bindery,
    create_mail_drop_for_job,
    create_plated_job,
    create_press,
    create_received_stock,
    create_stock,
    get_success_data,
    make_customer_headers,
    minimal_signature,
    quote_estimate,
    create_estimate,
    schedule_press_run,
    standard_signatures,
    upload_proof,
    validate_error,
    validate_success,
)

_MAIL = TEST_USERS["mail_headers"]
_PM = TEST_USERS["plant_manager_headers"]
_SCH = TEST_USERS["scheduler_headers"]


def _accepted_mail_job(cust, stock, quantity=100, job_name="MJ"):
    est, job = create_accepted_job(
        cust["id"], minimal_signature(stock["id"], make_ready_cents=1000,
                                      rate_per_thousand_cents=1000),
        quantity_ordered=quantity, job_name=job_name, fulfillment_type="MAIL",
    )
    return job


class TestPresortWaterfall:
    def _mail_job(self, name="PS Cust", qty=570):
        cust = create_customer(name=name)
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        job = _accepted_mail_job(cust, stock, quantity=qty)
        return job

    def test_presort_waterfall_mixed_tiers(self, api):
        """PRD §3.9: "each `zip_counts` entry whose piece count is at least
        150 qualifies entirely at the five-digit rate... The remaining pieces
        are then pooled by the first three digits of the ZIP prefix, and each
        three-digit pool with at least 150 pieces qualifies entirely at the
        three-digit rate. All remaining pieces fall to the AADC rate. The
        `tier_breakdown` records the resulting `five_digit_pieces`,
        `three_digit_pieces`, and `aadc_pieces`, and `postage_cents` is
        `five_digit_pieces` times 24 plus `three_digit_pieces` times 28 plus
        `aadc_pieces` times 31."
        90210:200 + 90401:180 -> 5-digit 380; 90211:100 pools to 902 (100<150);
        10001:90 pools to 100 (90<150) -> AADC 190; postage 380x24 + 190x31 =
        15010.

        Design: Corner/calculations/presort_waterfall_mixed_tiers
        """
        job = self._mail_job()
        drop = create_mail_drop_for_job(job["id"], [
            {"zip5": "90210", "pieces": 200}, {"zip5": "90211", "pieces": 100},
            {"zip5": "90401", "pieces": 180}, {"zip5": "10001", "pieces": 90},
        ])
        data = validate_success(api.presort_mail_drop(drop["id"], _MAIL), 200)
        assert data["tier_breakdown"] == {
            "five_digit_pieces": 380, "three_digit_pieces": 0, "aadc_pieces": 190}
        assert data["postage_cents"] == 15010

    def test_presort_tier_minimum_150_boundary(self, api):
        """PRD §3.9: "a tier minimum of 150 pieces" — an entry "whose piece
        count is at least 150 qualifies entirely at the five-digit rate":
        exactly 150 qualifies; 149 does not.

        Design: Corner/calculations/presort_tier_minimum_150_boundary
        """
        job = self._mail_job("PB Cust", 1000)
        da = create_mail_drop_for_job(job["id"], [
            {"zip5": "90210", "pieces": 150}, {"zip5": "90401", "pieces": 350}],
            drop_date="2026-08-25")
        db = create_mail_drop_for_job(job["id"], [
            {"zip5": "90210", "pieces": 149}, {"zip5": "90401", "pieces": 351}],
            drop_date="2026-08-26")
        a = validate_success(api.presort_mail_drop(da["id"], _MAIL), 200)
        assert a["tier_breakdown"] == {
            "five_digit_pieces": 500, "three_digit_pieces": 0, "aadc_pieces": 0}
        assert a["postage_cents"] == 12000
        b = validate_success(api.presort_mail_drop(db["id"], _MAIL), 200)
        assert b["tier_breakdown"] == {
            "five_digit_pieces": 351, "three_digit_pieces": 0, "aadc_pieces": 149}
        assert b["postage_cents"] == 13043

    def test_presort_global_minimum_499_vs_500(self, api):
        """PRD §3.9: "if the drop's `total_pieces` is below the global minimum
        of 500, every piece is priced at the AADC rate and the waterfall
        stops." 499 -> all AADC (15469); exactly 500 runs the waterfall
        (5D 200, 3D 180, AADC 120 -> 13560).

        Design: Corner/calculations/presort_global_minimum_499_vs_500
        """
        job = self._mail_job("PG Cust", 1000)
        d499 = create_mail_drop_for_job(job["id"], [
            {"zip5": "90210", "pieces": 200}, {"zip5": "90211", "pieces": 150},
            {"zip5": "10001", "pieces": 149}], drop_date="2026-08-25")
        d500 = create_mail_drop_for_job(job["id"], [
            {"zip5": "90210", "pieces": 200}, {"zip5": "90211", "pieces": 100},
            {"zip5": "90212", "pieces": 80}, {"zip5": "10001", "pieces": 120}],
            drop_date="2026-08-26")
        a = validate_success(api.presort_mail_drop(d499["id"], _MAIL), 200)
        assert a["tier_breakdown"] == {
            "five_digit_pieces": 0, "three_digit_pieces": 0, "aadc_pieces": 499}
        assert a["postage_cents"] == 15469
        b = validate_success(api.presort_mail_drop(d500["id"], _MAIL), 200)
        assert b["tier_breakdown"] == {
            "five_digit_pieces": 200, "three_digit_pieces": 180, "aadc_pieces": 120}
        assert b["postage_cents"] == 13560


class TestMailDailyCapacity:
    def _capacity_setup(self):
        cust = create_customer(name="MC Cust")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        j1 = _accepted_mail_job(cust, stock, quantity=60000, job_name="M1")
        j2 = _accepted_mail_job(cust, stock, quantity=40000, job_name="M2")
        j3 = _accepted_mail_job(cust, stock, quantity=2, job_name="M3")
        d1 = create_mail_drop_for_job(j1["id"], [{"zip5": "94101", "pieces": 60000}],
                                      drop_date="2026-08-25", destination_entry="BMC")
        d2 = create_mail_drop_for_job(j2["id"], [{"zip5": "94102", "pieces": 40000}],
                                      drop_date="2026-08-25", destination_entry="BMC")
        d3 = create_mail_drop_for_job(j3["id"], [{"zip5": "94103", "pieces": 1}],
                                      drop_date="2026-08-25", destination_entry="BMC")
        d4 = create_mail_drop_for_job(j3["id"], [{"zip5": "94103", "pieces": 1}],
                                      drop_date="2026-08-26", destination_entry="BMC")
        return d1, d2, d3, d4

    def test_capacity_equality_allowed(self, api):
        """PRD §3.9: "Presorting is rejected with `ERR_MAIL_CAPACITY_EXCEEDED`
        exactly when committed plus this drop's `total_pieces` would exceed
        100000 pieces; equality is allowed." 60000 + 40000 == 100000 presorts
        cleanly.

        Design: Difficulty/resource_temporal_overlap/mail_daily_aggregate_capacity
        """
        d1, d2, _d3, _d4 = self._capacity_setup()
        validate_success(api.presort_mail_drop(d1["id"], _MAIL), 200)
        ok = api.presort_mail_drop(d2["id"], _MAIL)
        data = validate_success(ok, 200)
        assert data["status"] == "PRESORTED"

    def test_one_piece_over_capacity_rejected_and_adjacent_date_independent(self, api):
        """PRD §3.9: "The capacity is a per-calendar-date aggregate, not a
        pairwise interval check — adjacent dates are independent." At
        committed 100000, one further piece on the same date is rejected; the
        same piece on 2026-08-26 is admitted.

        Design: Difficulty/resource_temporal_overlap/mail_daily_aggregate_capacity
        """
        d1, d2, d3, d4 = self._capacity_setup()
        api.presort_mail_drop(d1["id"], _MAIL)
        api.presort_mail_drop(d2["id"], _MAIL)
        r3 = api.presort_mail_drop(d3["id"], _MAIL)
        validate_error(r3, ApiErrorId.ERR_MAIL_CAPACITY_EXCEEDED)
        r4 = api.presort_mail_drop(d4["id"], _MAIL)
        validate_success(r4, 200)


class TestDropRequiresReadyToShip:
    def test_mail_drop_requires_job_ready_to_ship(self, api):
        """PRD §3.9: "Executing the drop requires the job to be in
        `READY_TO_SHIP` with `fulfillment_type` `MAIL` (else
        `ERR_JOB_INVALID_STATE`)." A BINDERY job rejects the drop while the
        drop stays PRESORTED.

        Design: Difficulty/cross_entity_state_dependency/mail_drop_requires_job_ready_to_ship
        """
        from test_helpers import api_client
        cust = create_customer(name="MD Cust")
        stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=50000)
        est = create_estimate(
            cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
            quantity_ordered=1000, fulfillment_type="MAIL", job_name="MJ",
        )
        quote_estimate(est["id"])
        job = accept_estimate(est["id"], cust["id"])
        p = upload_proof(job["id"], "s3://m.pdf")
        approve_proof(p["id"], cust["id"])
        press = create_press(name="W1")
        run = schedule_press_run(press, job_id=job["id"], run_quantity=1000)
        complete_press_run(run["id"], gross_impressions=1000, sheets_used=1000, waste_sheets=0)
        api_client.create_bindery_ticket(
            {"job_id": job["id"], "operation": "FOLD", "sequence_no": 1}, _PM)
        drop = create_mail_drop_for_job(
            job["id"], [{"zip5": "94101", "pieces": 1000}],
            drop_date="2026-08-25", destination_entry="SCF")
        drop = get_success_data(api.presort_mail_drop(drop["id"], _MAIL))
        assert drop["status"] == "PRESORTED"
        resp = api.drop_mail_drop(drop["id"], _MAIL)
        validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)
        after = get_success_data(api.get_mail_drop(drop["id"], _MAIL))
        assert after["status"] == "PRESORTED"
        job_after = get_success_data(api.get_job(job["id"], _PM))
        assert job_after["production_status"] == "BINDERY"

    def test_presort_carries_no_job_state_gate(self, api):
        """PRD §3.9 assigns the job-state gate to the drop transition only
        ("Executing the drop requires..."); presort's own precondition is the
        capacity rule ("Presort is also where the daily capacity check
        runs"), so presort succeeds while the job is still BINDERY.

        Design: Difficulty/cross_entity_state_dependency/mail_drop_requires_job_ready_to_ship
        """
        from test_helpers import api_client
        cust = create_customer(name="MD2 Cust")
        stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=50000)
        est = create_estimate(
            cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
            quantity_ordered=1000, fulfillment_type="MAIL", job_name="MJ2",
        )
        quote_estimate(est["id"])
        job = accept_estimate(est["id"], cust["id"])
        p = upload_proof(job["id"], "s3://m2.pdf")
        approve_proof(p["id"], cust["id"])
        press = create_press(name="W1")
        run = schedule_press_run(press, job_id=job["id"], run_quantity=1000)
        complete_press_run(run["id"], gross_impressions=1000, sheets_used=1000, waste_sheets=0)
        drop = create_mail_drop_for_job(
            job["id"], [{"zip5": "94101", "pieces": 1000}], drop_date="2026-08-25")
        ok = api.presort_mail_drop(drop["id"], _MAIL)
        data = validate_success(ok, 200)
        assert data["status"] == "PRESORTED"
        job_after = get_success_data(api.get_job(job["id"], _PM))
        assert job_after["production_status"] == "BINDERY"


class TestMailDropStateGate:
    def test_mail_drop_before_presort_rejected(self, api):
        """PRD §3.9: "Executing the drop requires the job to be in
        `READY_TO_SHIP` with `fulfillment_type` `MAIL` (else
        `ERR_JOB_INVALID_STATE`). The drop moves `PRESORTED → DROPPED`" — a
        PLANNED drop cannot be dropped; §2.7: "the target entity must be in
        the required state for the operation."

        Design: Corner/state_machines/mail_drop_before_presort_rejected
        """
        cust = create_customer(name="M Cust")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        job = _accepted_mail_job(cust, stock, quantity=100)
        drop = create_mail_drop_for_job(job["id"], [{"zip5": "94101", "pieces": 100}])
        resp = api.drop_mail_drop(drop["id"], _MAIL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_mail_drop(drop["id"], _MAIL))
        assert after["status"] == "PLANNED"


class TestFulfillmentChannelMismatch:
    def _setup(self):
        cust = create_customer(name="FC Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        # MAIL job driven to READY_TO_SHIP
        _est, job_m, _run, _press = create_job_in_bindery(
            cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
            quantity_ordered=1000, fulfillment_type="MAIL", job_name="M",
        )
        complete_bindery_and_deliver(job_m["id"], delivered_quantity=None,
                                     pieces_completed=1000)
        # SHIP job accepted (PREPRESS)
        _est2, job_s = create_accepted_job(
            cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
            quantity_ordered=1000, job_name="S", fulfillment_type="SHIP",
        )
        return cust, job_m, job_s

    def test_record_delivery_on_mail_job_rejected(self, api):
        """PRD §3.10: "recording delivery on a job whose `fulfillment_type` is
        not `SHIP` is rejected with `ERR_FULFILLMENT_CHANNEL_MISMATCH`."

        Design: Corner/errors/fulfillment_channel_mismatch_battery
        """
        _cust, job_m, _job_s = self._setup()
        resp = api.record_delivery(job_m["id"], {"delivered_quantity": 1000}, _PM)
        validate_error(resp, ApiErrorId.ERR_FULFILLMENT_CHANNEL_MISMATCH)

    def test_mail_drop_on_ship_job_rejected(self, api):
        """PRD §3.9: "Creating a mail drop on a job whose `fulfillment_type`
        is not `MAIL` is rejected with `ERR_FULFILLMENT_CHANNEL_MISMATCH`."

        Design: Corner/errors/fulfillment_channel_mismatch_battery
        """
        _cust, _job_m, job_s = self._setup()
        resp = api.create_mail_drop(
            {"job_id": job_s["id"], "drop_date": "2026-08-25", "destination_entry": "NONE",
             "piece_weight_oz": 2.0, "zip_counts": [{"zip5": "94101", "pieces": 100}]}, _MAIL)
        validate_error(resp, ApiErrorId.ERR_FULFILLMENT_CHANNEL_MISMATCH)
