"""Aflatoxin certificates: thresholds, retest cycle, uniqueness, SoD, and the
load's three parallel state axes (status x aflatoxin x drying)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_dryer,
    add_warehouse,
    api_client,
    assert_aflatoxin_certificate,
    confirm_certificate,
    create_dryer_booking_payload,
    draw_certificate,
    get_load,
    grade_load,
    record_result,
    report_load,
    setup_buying_point,
    setup_grower,
    setup_settlement_foundation,
    store_load,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_load,
)

ADMIN = TEST_USERS["admin_headers"]
LAB_1 = TEST_USERS["lab_tech_headers"]
LAB_2 = TEST_USERS["lab_tech_2_headers"]


class TestAflatoxinThresholds:

    def test_ppb_1500_inclusive_pass_and_5000_inclusive_segregate(self):
        """PRD section 3.5: "The determination thresholds are pinned: a result
        at or below 15.00 parts per billion is `PASS`; a result above 15.00 and
        at or below 50.00 is `SEGREGATE`; a result above 50.00 is `REJECT`."
        PRD section 3.5: "Confirmation maps the determination onto the load —
        `aflatoxin_status` becomes `PASSED`, `SEGREGATED`, or `REJECTED`
        respectively".

        Design: Difficulty/boundary_precision_check/aflatoxin_ppb_inclusive_thresholds
        """
        f = setup_settlement_foundation()
        load1 = report_load(f["grower"]["id"])
        weigh_load(load1["id"], 25.0)
        load2 = report_load(f["grower"]["id"])
        weigh_load(load2["id"], 25.0)

        cert1 = draw_certificate(load1["id"], "S-1")
        recorded1 = record_result(cert1["id"], 15.0)
        assert recorded1["determination"] == "PASS", "15.00 is inclusive PASS"
        confirm_certificate(cert1["id"])
        assert get_load(load1["id"])["aflatoxin_status"] == "PASSED"

        cert2 = draw_certificate(load2["id"], "S-2")
        recorded2 = record_result(cert2["id"], 50.0)
        assert recorded2["determination"] == "SEGREGATE", \
            "50.00 is the inclusive upper bound of the segregate band"
        confirm_certificate(cert2["id"])
        assert get_load(load2["id"])["aflatoxin_status"] == "SEGREGATED"

    def test_ppb_5001_rejects_load_terminally(self):
        """PRD section 3.5: "a result above 50.00 is `REJECT`."
        PRD section 3.5: "when the determination is `REJECT` and the load is
        still `WEIGHED` or `GRADED`, the load itself moves terminally to
        `REJECTED` and may not be stored."

        Design: Difficulty/boundary_precision_check/aflatoxin_ppb_inclusive_thresholds
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weigh_load(load["id"], 25.0)
        cert = draw_certificate(load["id"], "S-3")
        recorded = record_result(cert["id"], 50.01)
        assert recorded["determination"] == "REJECT"
        confirm_certificate(cert["id"])
        load_after = get_load(load["id"])
        assert load_after["aflatoxin_status"] == "REJECTED"
        assert load_after["status"] == "REJECTED"


class TestRetestCycle:

    def test_retest_cycle_traversal_and_determination_tracking(self):
        """PRD section 3.5: "Ordering a retest cycles the certificate back to
        `SAMPLED`, increments `retest_count`, and retains the prior
        `result_ppb` and `determination` until a new recording overwrites
        them".
        PRD section 3.5: "the `determination` is recomputed on every
        recording."

        Design: Difficulty/non_linear_state_machine/aflatoxin_retest_cycle_bounded
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weigh_load(load["id"], 25.0)
        cert = draw_certificate(load["id"])

        r1 = record_result(cert["id"], 18.5)
        assert r1["status"] == "RESULT_RECORDED"
        assert r1["determination"] == "SEGREGATE"

        resp = api_client.order_retest(cert["id"], LAB_1)
        cycled = resp.json()["data"]
        assert cycled["status"] == "SAMPLED"
        assert cycled["retest_count"] == 1
        assert cycled["result_ppb"] == 18.5, "prior result retained until overwritten"
        assert cycled["determination"] == "SEGREGATE"

        r2 = record_result(cert["id"], 12.0)
        assert r2["determination"] == "PASS"

        cycled2 = api_client.order_retest(cert["id"], LAB_1).json()["data"]
        assert cycled2["status"] == "SAMPLED"
        assert cycled2["retest_count"] == 2

        r3 = record_result(cert["id"], 14.0)
        assert r3["determination"] == "PASS"

    def test_third_retest_rejected_then_confirm_passes(self):
        """PRD section 3.5: "the retest cycle is capped at two, and ordering a
        retest when `retest_count` has already reached 2 is rejected with
        `ERR_RETEST_LIMIT_EXCEEDED`."
        PRD section 3.5: "Confirmation maps the determination onto the load —
        `aflatoxin_status` becomes `PASSED`, `SEGREGATED`, or `REJECTED`
        respectively".

        Design: Difficulty/non_linear_state_machine/aflatoxin_retest_cycle_bounded
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weigh_load(load["id"], 25.0)
        cert = draw_certificate(load["id"])

        record_result(cert["id"], 18.5)
        api_client.order_retest(cert["id"], LAB_1)
        record_result(cert["id"], 12.0)
        api_client.order_retest(cert["id"], LAB_1)
        record_result(cert["id"], 14.0)

        resp = api_client.order_retest(cert["id"], LAB_1)
        validate_error(resp, ApiErrorId.ERR_RETEST_LIMIT_EXCEEDED)

        confirmed = confirm_certificate(cert["id"], tech="lab-2")
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["retest_count"] == 2
        assert confirmed["determination"] == "PASS"
        assert_aflatoxin_certificate(confirmed)
        assert get_load(load["id"])["aflatoxin_status"] == "PASSED"


class TestParallelAxes:

    def _two_loads(self):
        """Load A WEIGHED 25.0t; load B WEIGHED 24.0t; dryer D1 12t/6h."""
        f = setup_settlement_foundation(with_dryer=True)
        load_a = report_load(f["grower"]["id"])
        weighed_a = weigh_load(load_a["id"], 25.0)
        load_b = report_load(f["grower"]["id"])
        weighed_b = weigh_load(load_b["id"], 24.0)
        return f, load_a, weighed_a, load_b, weighed_b

    def test_axes_advance_independently(self):
        """PRD section 3.5: "Confirmation maps the determination onto the load
        — `aflatoxin_status` becomes `PASSED`, `SEGREGATED`, or `REJECTED`
        respectively".
        PRD section 3.6: "The booking tonnage must equal the load's
        `gross_tons`, and the load's drying axis must be `REQUIRED` at booking
        time".

        Design: Difficulty/non_linear_state_machine/load_parallel_axes_independence_and_gate
        """
        f, load_a, weighed_a, load_b, weighed_b = self._two_loads()

        # Aflatoxin axis reaches PASSED while the grading axis is still WEIGHED.
        cert_a = draw_certificate(load_a["id"], "SAMP-A1")
        record_result(cert_a["id"], 5.0)
        confirm_certificate(cert_a["id"])
        mid_a = get_load(load_a["id"])
        assert mid_a["aflatoxin_status"] == "PASSED"
        assert mid_a["status"] == "WEIGHED", \
            "the aflatoxin axis advanced ahead of the grading axis"

        # Drying axis reaches BOOKED while the aflatoxin axis is still UNTESTED.
        grade_load(load_b["id"], weighed_b["version"], moisture_pct=11.2,
                   foreign_material_pct=3.0, damage_pct=0.0, lsk_pct=0.0)
        bk_b = validate_success(api_client.create_dryer_booking(
            create_dryer_booking_payload(dryer_id=f["dryer"]["id"],
                                         load_id=load_b["id"], tons=24.0,
                                         starts_at="2026-09-03T06:00:00Z"), ADMIN),
            expected_status=201)
        mid_b = get_load(load_b["id"])
        assert mid_b["drying_status"] == "BOOKED"
        assert mid_b["aflatoxin_status"] == "UNTESTED", \
            "the drying axis is independent of the laboratory axis"

    def test_storage_gate_joins_all_axes_and_final_states(self):
        """PRD section 3.7: "The drying axis must be `NOT_REQUIRED` or `DRIED`
        (`ERR_DRYING_REQUIRED`). The aflatoxin axis must be `PASSED` or
        `SEGREGATED` (`ERR_AFLATOXIN_NOT_CLEARED`)."
        PRD section 3.6: "the number of cycles is the booking tonnage divided
        by the dryer's `cycle_capacity_tons`, rounded up to a whole cycle, and
        the end is the start plus that many cycles times the dryer's
        `cycle_hours`."

        Design: Difficulty/non_linear_state_machine/load_parallel_axes_independence_and_gate
        """
        f, load_a, weighed_a, load_b, weighed_b = self._two_loads()

        grade_load(load_a["id"], weighed_a["version"], moisture_pct=9.2,
                   foreign_material_pct=5.5, damage_pct=2.0, lsk_pct=1.0)
        cert_a = draw_certificate(load_a["id"], "SAMP-A1")
        record_result(cert_a["id"], 5.0)
        confirm_certificate(cert_a["id"])
        store_load(load_a["id"], f["warehouse"]["id"])

        grade_load(load_b["id"], weighed_b["version"], moisture_pct=11.2,
                   foreign_material_pct=3.0, damage_pct=0.0, lsk_pct=0.0)
        bk_b = validate_success(api_client.create_dryer_booking(
            create_dryer_booking_payload(dryer_id=f["dryer"]["id"],
                                         load_id=load_b["id"], tons=24.0,
                                         starts_at="2026-09-03T06:00:00Z"), ADMIN),
            expected_status=201)
        # ceil(24/12) = 2 cycles x 6h from 06:00
        assert bk_b["ends_at"].startswith("2026-09-03T18:00:00")
        api_client.complete_dryer_booking(
            bk_b["id"], {"actual_moisture_after": 9.0}, ADMIN)
        cert_b = draw_certificate(load_b["id"], "SAMP-B1")
        record_result(cert_b["id"], 7.5)
        confirm_certificate(cert_b["id"])
        store_load(load_b["id"], f["warehouse"]["id"])

        final_a = get_load(load_a["id"])
        assert final_a["status"] == "STORED"
        assert final_a["aflatoxin_status"] == "PASSED"
        assert final_a["drying_status"] == "NOT_REQUIRED"

        final_b = get_load(load_b["id"])
        assert final_b["status"] == "STORED"
        assert final_b["aflatoxin_status"] == "PASSED"
        assert final_b["drying_status"] == "DRIED"
        assert final_b["payable_tons"] == 23.28  # 24 - fm 0.72


class TestCertificateConstraints:

    def test_certificate_second_sample_rejected(self):
        """PRD section 3.5: "at most one certificate may ever exist for a load
        — a second draw is rejected with `ERR_CERTIFICATE_EXISTS`."

        Design: Corner/entities/certificate_second_sample_rejected
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weigh_load(load["id"], 25.0)
        draw_certificate(load["id"], "SAMP-A1")

        resp = api_client.create_aflatoxin_certificate(
            load["id"], {"sample_ref": "SAMP-A2"}, LAB_1)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_EXISTS)

        resp = api_client.list_aflatoxin_certificates(
            ADMIN, params={"load_id": load["id"]})
        _data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1

    def test_sod_aflatoxin_confirm_same_recorder_rejected(self):
        """PRD section 2.11: "The technician who records an aflatoxin result
        may not confirm it."
        PRD section 3.5: "the confirming technician's `X-User-ID` must differ
        from `result_recorded_by` per §2.11 (a self-confirm is rejected with
        `ERR_SEG_OF_DUTIES`), `confirmed_by` is stamped, and the certificate
        reaches `CONFIRMED`."

        Design: Corner/validations/sod_aflatoxin_confirm_same_recorder_rejected
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weigh_load(load["id"], 25.0)
        cert = draw_certificate(load["id"], "SAMP-A1", tech="lab-1")
        record_result(cert["id"], 8.0, tech="lab-1")

        resp = api_client.confirm_aflatoxin_certificate(cert["id"], LAB_1)
        validate_error(resp, ApiErrorId.ERR_SEG_OF_DUTIES)
        still = api_client.get_aflatoxin_certificate(cert["id"], ADMIN).json()["data"]
        assert still["status"] == "RESULT_RECORDED"

        confirmed = confirm_certificate(cert["id"], tech="lab-2")
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmed_by"] == "lab-2"
        assert confirmed["result_recorded_by"] == "lab-1"
        assert get_load(load["id"])["aflatoxin_status"] == "PASSED"
