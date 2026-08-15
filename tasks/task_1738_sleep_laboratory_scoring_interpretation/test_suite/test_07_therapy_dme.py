"""Therapy prescriptions (device-field rules, report-state gate, severity
indication, OCC), the titration pressure recommendation, and DME fulfillment
with adherence follow-up."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_dme_order,
    assert_therapy_prescription,
    create_prescription,
    create_report,
    get_success_data,
    make_physician_headers,
    setup_delivered_dme,
    setup_finalized_report,
    setup_ordered_prescription,
    setup_scored_study,
    setup_signed_report,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["lab_director_headers"]
DME = TEST_USERS["dme_coordinator_headers"]

MILD_SUBMIT = {"obstructive_apneas": 40, "hypopneas": 56}  # REI 12.0 -> MILD


class TestPrescriptionReportStateGate:
    def test_prescription_on_draft_report_rejected(self, api):
        """PRD: "Where interpretation indicates therapy, the author creates a
        **TherapyPrescription** against a report in `SIGNED` or `FINALIZED` —
        any other report state is rejected with `ERR_REPORT_INVALID_STATE` —
        carrying `expected_interpretation_report_version` per §2.7."

        Design: Difficulty/cross_entity_state_dependency/prescription_requires_signed_report
        """
        ws = setup_scored_study(study_type="HST", submit_overrides=MILD_SUBMIT)
        create_report(ws)
        assert ws["report"]["status"] == "DRAFT"

        resp = api.create_therapy_prescription(
            {"report_id": ws["report"]["id"], "device_type": "CPAP",
             "mask_type": "NASAL", "cpap_pressure_cm": 9.0,
             "expected_interpretation_report_version":
                 ws["report"]["version"]},
            make_physician_headers(ws["physician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_STATE, 409)

        _, meta = validate_paginated(api.list_therapy_prescriptions(
            DIRECTOR, {"report_id": ws["report"]["id"]}))
        assert meta["total_count"] == 0

    def test_prescription_on_finalized_report_accepted(self, api):
        """PRD: "Where interpretation indicates therapy, the author creates a
        **TherapyPrescription** against a report in `SIGNED` or `FINALIZED` —
        any other report state is rejected with `ERR_REPORT_INVALID_STATE`."
        PRD: "Creation opens the prescription in `DRAFT`, denormalizes the
        report's study onto the prescription's `study_id`, increments the
        report's `version` by one"

        Design: Difficulty/cross_entity_state_dependency/prescription_requires_signed_report
        """
        ws = setup_finalized_report(study_type="HST",
                                    submit_overrides=MILD_SUBMIT)
        assert ws["report"]["status"] == "FINALIZED"

        rx = create_prescription(ws, device_type="CPAP", mask_type="NASAL",
                                 cpap_pressure_cm=9.0)
        assert_therapy_prescription(rx)
        assert rx["status"] == "DRAFT"
        assert rx["report_id"] == ws["report"]["id"]
        assert rx["study_id"] == ws["study"]["id"], (
            "The report's study is denormalized onto the prescription")


class TestPrescriptionFieldRules:
    def test_rx_device_fields_bipap_invalid(self, api):
        """PRD: "Device-specific pressure fields must be present and coherent
        for the chosen `device_type`, with violations rejected as
        `ERR_RX_DEVICE_FIELDS_INVALID`"
        PRD: "`BIPAP` requires `bipap_epap_cm` strictly below `bipap_ipap_cm`,
        both within 4.0 to 25.0 inclusive and on 0.5 steps."

        Design: Corner/validations/rx_device_fields_bipap_invalid
        """
        ws = setup_signed_report(study_type="HST",
                                 submit_overrides=MILD_SUBMIT)
        report = get_success_data(
            api.get_interpretation_report(ws["report"]["id"], DIRECTOR))

        resp = api.create_therapy_prescription(
            {"report_id": report["id"], "device_type": "BIPAP",
             "mask_type": "NASAL", "bipap_ipap_cm": 8.0,
             "bipap_epap_cm": 10.0,
             "expected_interpretation_report_version": report["version"]},
            make_physician_headers(report["physician_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RX_DEVICE_FIELDS_INVALID, 400)

        _, meta = validate_paginated(api.list_therapy_prescriptions(
            DIRECTOR, {"report_id": report["id"]}))
        assert meta["total_count"] == 0

    def test_rx_on_normal_severity_rejected(self, api):
        """PRD: "A report whose signed `severity` is `NORMAL` does not support
        PAP therapy and rejects prescription creation with
        `ERR_THERAPY_NOT_INDICATED`."

        Design: Corner/validations/rx_on_normal_severity_rejected
        """
        ws = setup_signed_report(
            study_type="HST",
            submit_overrides={"obstructive_apneas": 10, "hypopneas": 10},
            icd10_primary="R06.83")
        # 20 events * 60 / 480 = REI 2.5 < 5.0 -> NORMAL.
        report = ws["report"]
        assert report["severity"] == "NORMAL"
        assert report["index_at_interpretation"] == pytest.approx(2.5)

        resp = api.create_therapy_prescription(
            {"report_id": report["id"], "device_type": "CPAP",
             "mask_type": "NASAL", "cpap_pressure_cm": 9.0,
             "expected_interpretation_report_version": report["version"]},
            make_physician_headers(report["physician_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_THERAPY_NOT_INDICATED, 422)

    def test_occ_rx_create_stale_version_rejected(self, api):
        """PRD: "Creating a therapy prescription requires
        `expected_interpretation_report_version`, matching the report's
        current `version`; a prescription created in the interim legitimately
        supersedes the prior active one, so a stale `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_rx_create_stale_version_rejected
        """
        ws = setup_signed_report(study_type="HST",
                                 submit_overrides=MILD_SUBMIT)
        report = get_success_data(
            api.get_interpretation_report(ws["report"]["id"], DIRECTOR))
        observed_version = report["version"]
        author = make_physician_headers(report["physician_id"])

        first = validate_success(api.create_therapy_prescription(
            {"report_id": report["id"], "device_type": "CPAP",
             "mask_type": "NASAL", "cpap_pressure_cm": 9.0,
             "expected_interpretation_report_version": observed_version},
            author), 201)
        assert first["status"] == "DRAFT"

        resp = api.create_therapy_prescription(
            {"report_id": report["id"], "device_type": "CPAP",
             "mask_type": "FULL_FACE", "cpap_pressure_cm": 10.0,
             "expected_interpretation_report_version": observed_version},
            author,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        _, meta = validate_paginated(api.list_therapy_prescriptions(
            DIRECTOR, {"report_id": report["id"]}))
        assert meta["total_count"] == 1


class TestTitrationRecommendation:
    def test_titration_recommendation_raw_band_pinned(self, api):
        """PRD: "First the raw pressure determines a band: at most 10.0 cm is
        the low band, anything above is the high band, and the band is
        computed from the raw pressure alone — it is never recomputed after
        adjustment. The residual index contributes an adjustment of 1.0 when
        at least 10.0, 0.5 when at least 5.0 but below 10.0, and 0.0 below
        5.0. The leak contributes 0.5 when the band is low and the leak
        exceeds 24.0 L/min, 1.0 when the band is high and the leak exceeds
        36.0 L/min, and 0.0 otherwise. The recommendation is the raw pressure
        plus both adjustments, clamped to no less than 4.0 and no more than
        20.0, then rounded to the nearest 0.5 step round-half-up (§2.6)."

        Design: Corner/calculations/titration_recommendation_raw_band_pinned
        """
        ws = setup_scored_study(
            study_type="TITRATION_PAP",
            total_recording_time_minutes=420,
            titration_final_pressure_cm=10.0,
            leak_95th_l_min=30.0,
            submit_overrides={
                "obstructive_apneas": 12, "central_apneas": 0,
                "mixed_apneas": 0, "hypopneas": 12, "reras": 0,
                "epochs_total": 720, "total_sleep_time_minutes": 240,
                "total_recording_time_minutes": 420,
            })
        # 24 events * 60 / 240 TST = residual AHI 6.0.
        assert ws["study"]["accepted_ahi"] == pytest.approx(6.0)

        rec = validate_success(api.titration_recommendation(
            ws["study"]["id"],
            make_physician_headers(ws["physician"]["id"])))
        # raw 10.0 -> LOW band; leak 30.0 > 24.0 -> +0.5; AHI 6.0 -> +0.5.
        assert rec["recommended_cpap_cm"] == pytest.approx(11.0), (
            "The band is computed from the raw pressure alone: re-banding "
            "after the +1.0 adjustment would (incorrectly) yield 10.5")
        assert rec["raw_pressure_cm"] == pytest.approx(10.0)
        assert rec["residual_ahi"] == pytest.approx(6.0)
        assert rec["leak_95th_l_min"] == pytest.approx(30.0)

    def test_titration_recommendation_unavailable_for_hst(self, api):
        """PRD: "It is available only for a `TITRATION_PAP` study, or a
        `SPLIT_NIGHT` study whose `split_outcome` is `CONVERT_TO_TITRATION`,
        that has an accepted `PRIMARY` scoring task; anything else is rejected
        with `ERR_TITRATION_RECOMMENDATION_UNAVAILABLE`."

        Design: Corner/validations/titration_recommendation_unavailable_for_hst
        """
        ws = setup_scored_study(study_type="HST")

        resp = api.titration_recommendation(
            ws["study"]["id"],
            make_physician_headers(ws["physician"]["id"]))
        validate_error(
            resp, ApiErrorId.ERR_TITRATION_RECOMMENDATION_UNAVAILABLE, 409)


class TestDmeFulfillment:
    def test_dme_dispatch_on_draft_rx_rejected(self, api):
        """PRD: "Dispatching a **DmeOrder** names the `prescription_id` and the
        `vendor_name`; the prescription must be `ORDERED`
        (`ERR_RX_INVALID_STATE` otherwise)"

        Design: Corner/validations/dme_dispatch_on_draft_rx_rejected
        """
        ws = setup_signed_report(study_type="HST",
                                 submit_overrides=MILD_SUBMIT)
        create_prescription(ws, device_type="CPAP", mask_type="NASAL",
                            cpap_pressure_cm=9.0)

        resp = api.create_dme_order(
            {"prescription_id": ws["rx"]["id"], "vendor_name": "DME Corp"},
            DME,
        )
        validate_error(resp, ApiErrorId.ERR_RX_INVALID_STATE, 409)

        _, meta = validate_paginated(api.list_dme_orders(
            DIRECTOR, {"prescription_id": ws["rx"]["id"]}))
        assert meta["total_count"] == 0

    def test_second_dme_dispatch_rejected(self, api):
        """PRD: "a prescription may have only one non-terminal DME order at a
        time (`ERR_DME_ORDER_ACTIVE`)."

        Design: Corner/errors/second_dme_dispatch_rejected
        """
        ws = setup_ordered_prescription(study_type="HST",
                                        submit_overrides=MILD_SUBMIT)
        get_success_data(api.create_dme_order(
            {"prescription_id": ws["rx"]["id"], "vendor_name": "DME Corp"},
            DME))

        resp = api.create_dme_order(
            {"prescription_id": ws["rx"]["id"], "vendor_name": "DME Rival"},
            DME,
        )
        validate_error(resp, ApiErrorId.ERR_DME_ORDER_ACTIVE, 409)

        _, meta = validate_paginated(api.list_dme_orders(
            DIRECTOR, {"prescription_id": ws["rx"]["id"]}))
        assert meta["total_count"] == 1

    def test_deliver_on_declined_dme_rejected(self, api):
        """PRD: "or records a vendor decline to `DECLINED`, or cancels the
        order to `CANCELLED`; each of these three actions requires
        `DISPATCHED` (`ERR_DME_INVALID_STATE` otherwise)."

        Design: Corner/validations/deliver_on_declined_dme_rejected
        """
        ws = setup_ordered_prescription(study_type="HST",
                                        submit_overrides=MILD_SUBMIT)
        dme_order = get_success_data(api.create_dme_order(
            {"prescription_id": ws["rx"]["id"], "vendor_name": "DME Corp"},
            DME))
        declined = get_success_data(api.decline_dme_order(dme_order["id"], DME))
        assert declined["status"] == "DECLINED"

        resp = api.deliver_dme_order(dme_order["id"], DME)
        validate_error(resp, ApiErrorId.ERR_DME_INVALID_STATE, 409)

        reread = get_success_data(api.get_dme_order(dme_order["id"], DIRECTOR))
        assert reread["status"] == "DECLINED"

    def test_dme_followup_boundary_seventy_percent_passes(self, api):
        """PRD: "The order is adherence-compliant when average usage is at
        least 4.0 hours and the compliant-nights percentage is at least 70.0 —
        both boundaries inclusive, so exactly 4.0 hours and exactly 70.0
        percent pass. The verdict is stored in `adherence_compliant`, which is
        null until follow-up is recorded: a compliant order moves to
        `FOLLOW_UP_PASSED`, and a non-compliant order moves to
        `ADHERENCE_REVIEW`."
        PRD: "Delivery of the equipment fulfills an `ORDERED` prescription
        automatically."

        Design: Corner/calculations/dme_followup_boundary_seventy_percent_passes
        """
        ws = setup_delivered_dme(study_type="HST",
                                 submit_overrides=MILD_SUBMIT)
        assert ws["dme"]["status"] == "DELIVERED"
        assert ws["rx"]["status"] == "FULFILLED", (
            "The delivery cascade fulfilled the prescription")

        followed = get_success_data(api.record_dme_follow_up(
            ws["dme"]["id"],
            {"usage_hours_avg": 4.0, "compliant_nights_percent": 70.0},
            DME))
        assert_dme_order(followed)
        assert followed["status"] == "FOLLOW_UP_PASSED"
        assert followed["adherence_compliant"] is True
        assert followed["follow_up_usage_hours_avg"] == pytest.approx(4.0)
        assert followed["follow_up_compliant_nights_percent"] == \
            pytest.approx(70.0)

    def test_dme_adherence_review_resolution_branch(self, api):
        """PRD: "a non-compliant order moves to `ADHERENCE_REVIEW`. From
        `ADHERENCE_REVIEW`, the coordinator resolves the case with an `action`
        — `CONTINUE_THERAPY` or `ESCALATE_TO_PHYSICIAN` — which is stored as
        `resolution_action`, null until resolution, and moves the order to
        `FOLLOW_UP_RESOLVED`."

        Design: Corner/calculations/dme_adherence_review_resolution_branch
        """
        ws = setup_delivered_dme(
            study_type="HST", submit_overrides=MILD_SUBMIT,
            rx_overrides={"device_type": "APAP", "mask_type": "FULL_FACE",
                          "cpap_pressure_cm": None,
                          "apap_min_cm": 5.0, "apap_max_cm": 15.0})

        reviewed = get_success_data(api.record_dme_follow_up(
            ws["dme"]["id"],
            {"usage_hours_avg": 3.5, "compliant_nights_percent": 65.0},
            DME))
        assert reviewed["status"] == "ADHERENCE_REVIEW"
        assert reviewed["adherence_compliant"] is False

        resolved = get_success_data(api.resolve_dme_adherence(
            ws["dme"]["id"], "ESCALATE_TO_PHYSICIAN", DME))
        assert resolved["status"] == "FOLLOW_UP_RESOLVED"
        assert resolved["resolution_action"] == "ESCALATE_TO_PHYSICIAN"
