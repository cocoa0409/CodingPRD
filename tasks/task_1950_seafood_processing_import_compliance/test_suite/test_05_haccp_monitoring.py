"""HACCP monitoring: histamine screening vs confirmatory variants, the 50 ppm
critical limit boundary, subsample-count validation, and temperature-abuse
accumulation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_supplier,
    create_lot,
    create_released_entry,
    get_success_data,
    make_compliance_manager_headers,
    make_qa_tech_headers,
    validate_error,
    validate_paginated,
    validate_success,
    verify_species,
)

CM = TEST_USERS["compliance_manager_headers"]
QA = TEST_USERS["qa_tech_headers"]
RI = TEST_USERS["receiving_inspector_headers"]


def _setup_tuna_lot(api, frn="FRN-2001", entry_number="E-2001", country="ES",
                    receiving_temp_c=1.5, grade="A", quantity_received_kg=80,
                    name="Bluefin Traders"):
    supplier = create_approved_supplier(name=name, country=country, frn=frn)
    entry = create_released_entry(
        supplier["id"], entry_number=entry_number, species="TUNA",
        transport_mode="VESSEL", goods_value_cents=500000,
        freight_cost_cents=20000, duty_rate_pct=0.0, total_weight_kg=100)
    lot = create_lot(entry["id"], species="TUNA", grade=grade,
                     quantity_received_kg=quantity_received_kg,
                     harvest_country_code=country, catch_area_code="FAO27",
                     vessel_name="FV Azul", receiving_temp_c=receiving_temp_c)
    return supplier, entry, lot


class TestScreeningVsConfirmatory:
    def test_screening_deviation_confirmatory_pass_diverge(self, api):
        """PRD: "In the **screening** variant, the verdict is `DEVIATION` if
        the measured value is 50.0 ppm or greater, otherwise `PASS`. In the
        **confirmatory** variant, the average of all subsample values is
        computed and rounded half-up to 2 decimal places. The verdict is `PASS`
        only if the rounded average is below 50.0 ppm **and** every individual
        subsample value is below 100.0 ppm."
        PRD: "A lot can fail screening yet pass confirmatory — the two variants
        use different logic."

        Design: Difficulty/dual_variant_calc/histamine_screening_vs_confirmatory_diverge
        """
        supplier, entry, lot = _setup_tuna_lot(api)
        qa01 = make_qa_tech_headers("qa-01")

        screening = validate_success(api.create_haccp_record(
            {"hazard_type": "HISTAMINE", "receipt_lot_id": lot["id"],
             "phase": "SCREENING", "measured_value": 60.0,
             "measured_at": "2026-07-25T10:00:00Z"}, qa01), 201)
        assert screening["verdict"] == "DEVIATION"

        confirmatory = validate_success(api.create_haccp_record(
            {"hazard_type": "HISTAMINE", "receipt_lot_id": lot["id"],
             "phase": "CONFIRMATORY",
             "subsample_values": [45.0, 48.0, 52.0],
             "measured_at": "2026-07-26T10:00:00Z"}, qa01), 201)
        # avg = 48.33 < 50.0 and max 52.0 < 100.0 -> PASS.
        assert confirmatory["verdict"] == "PASS"

    def test_screening_deviation_quarantines_lot_and_creates_ca(self, api):
        """PRD: "When the verdict is `DEVIATION`, the system auto-creates a
        CorrectiveAction with `source_type` `HISTAMINE_DEVIATION`,
        `monitoring_record_id` set to the record, `receipt_lot_id` set to the
        record's lot, `supplier_id` traced through the lot's import entry, and
        `opened_by` set to the requesting `X-User-ID`. The lot transitions from
        `UNDER_INSPECTION` or `ACCEPTED` to `QUARANTINED`."

        Design: Difficulty/dual_variant_calc/histamine_screening_vs_confirmatory_diverge
        """
        supplier, entry, lot = _setup_tuna_lot(api)
        qa01 = make_qa_tech_headers("qa-01")
        screening = validate_success(api.create_haccp_record(
            {"hazard_type": "HISTAMINE", "receipt_lot_id": lot["id"],
             "phase": "SCREENING", "measured_value": 60.0,
             "measured_at": "2026-07-25T10:00:00Z"}, qa01), 201)
        assert screening["verdict"] == "DEVIATION"

        lot_after = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert lot_after["status"] == "QUARANTINED"

        cas, meta = validate_paginated(api.list_corrective_actions(
            CM, params={"receipt_lot_id": lot["id"]}))
        assert meta["total_count"] == 1
        ca = cas[0]
        assert ca["source_type"] == "HISTAMINE_DEVIATION"
        assert ca["status"] == "OPEN"
        assert ca["opened_by"] == "qa-01"
        assert ca["monitoring_record_id"] == screening["id"]


class TestCriticalLimitBoundary:
    def test_histamine_49_9_passes_50_0_deviates(self, api):
        """PRD: "In the **screening** variant, the verdict is `DEVIATION` if
        the measured value is 50.0 ppm or greater, otherwise `PASS`."

        Design: Difficulty/boundary_precision_check/histamine_exact_50ppm_deviation
        """
        supplier, entry, lot1 = _setup_tuna_lot(
            api, frn="FRN-7001", entry_number="E-7001", country="EC",
            receiving_temp_c=2.0, name="Meridian Marine")
        lot2 = create_lot(entry["id"], species="TUNA", grade="A",
                          quantity_received_kg=80, harvest_country_code="EC",
                          catch_area_code="FAO87", vessel_name="FV Meridiano",
                          receiving_temp_c=2.0)

        rec1 = validate_success(api.create_haccp_record(
            {"hazard_type": "HISTAMINE", "receipt_lot_id": lot1["id"],
             "phase": "SCREENING", "measured_value": 49.9,
             "measured_at": "2026-07-25T10:00:00Z"}, QA), 201)
        assert rec1["verdict"] == "PASS"

        qa07 = make_qa_tech_headers("qa-07")
        rec2 = validate_success(api.create_haccp_record(
            {"hazard_type": "HISTAMINE", "receipt_lot_id": lot2["id"],
             "phase": "SCREENING", "measured_value": 50.0,
             "measured_at": "2026-07-25T10:01:00Z"}, qa07), 201)
        assert rec2["verdict"] == "DEVIATION"

    def test_deviation_quarantines_only_the_deviating_lot(self, api):
        """PRD: "When the verdict is `DEVIATION` ... The lot transitions from
        `UNDER_INSPECTION` or `ACCEPTED` to `QUARANTINED`." A PASS verdict
        carries no such side effect: "On `PASS`, the `corrective_action_id` on
        the monitoring record remains null."

        Design: Difficulty/boundary_precision_check/histamine_exact_50ppm_deviation
        """
        supplier, entry, lot1 = _setup_tuna_lot(
            api, frn="FRN-7001", entry_number="E-7001", country="EC",
            receiving_temp_c=2.0, name="Meridian Marine")
        lot2 = create_lot(entry["id"], species="TUNA", grade="A",
                          quantity_received_kg=80, harvest_country_code="EC",
                          catch_area_code="FAO87", vessel_name="FV Meridiano",
                          receiving_temp_c=2.0)

        rec1 = validate_success(api.create_haccp_record(
            {"hazard_type": "HISTAMINE", "receipt_lot_id": lot1["id"],
             "phase": "SCREENING", "measured_value": 49.9,
             "measured_at": "2026-07-25T10:00:00Z"}, QA), 201)
        assert rec1["corrective_action_id"] is None

        qa07 = make_qa_tech_headers("qa-07")
        validate_success(api.create_haccp_record(
            {"hazard_type": "HISTAMINE", "receipt_lot_id": lot2["id"],
             "phase": "SCREENING", "measured_value": 50.0,
             "measured_at": "2026-07-25T10:01:00Z"}, qa07), 201)

        lot1_after = validate_success(api.get_receipt_lot(lot1["id"], QA))
        lot2_after = validate_success(api.get_receipt_lot(lot2["id"], QA))
        assert lot1_after["status"] == "UNDER_INSPECTION"
        assert lot2_after["status"] == "QUARANTINED"


class TestConfirmatoryValidation:
    def test_confirmatory_requires_three_subsamples(self, api):
        """PRD: "For `CONFIRMATORY` phase HISTAMINE records, `subsample_values`
        is required — an array of at least 3 subsample ppm values. ...
        Providing fewer than 3 subsamples yields `ERR_VALIDATION_FAILED`
        (HTTP 400)."

        Design: Corner/calculations/confirmatory_requires_three_subsamples
        """
        supplier, entry, lot = _setup_tuna_lot(
            api, frn="FRN-CAL3", entry_number="E-CAL3", country="EC",
            receiving_temp_c=2.0, name="Meridian Marine")
        resp = api.create_haccp_record(
            {"hazard_type": "HISTAMINE", "receipt_lot_id": lot["id"],
             "phase": "CONFIRMATORY", "subsample_values": [45.0, 48.0],
             "measured_at": "2026-07-25T10:00:00Z"}, QA)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


class TestTemperatureAbuseBoundary:
    def test_abuse_minutes_240_boundary(self, api):
        """PRD: "When `cumulative_abuse_minutes` reaches or exceeds 240 and the
        lot is not already quarantined or rejected, the system auto-creates a
        CorrectiveAction with `source_type` `TEMPERATURE_ABUSE` and `opened_by`
        set to the requesting `X-User-ID`, transitions the lot from
        `UNDER_INSPECTION` or `ACCEPTED` to `QUARANTINED`... The boundary is
        inclusive: exactly 240 blocks acceptance."

        Design: Corner/calculations/abuse_minutes_240_boundary
        """
        supplier, entry, lot = _setup_tuna_lot(
            api, frn="FRN-CAL2", entry_number="E-CAL2", country="EC",
            receiving_temp_c=5.0, name="Meridian Marine")
        # avg 5.0 > 4.4 on every interval: all minutes count as abuse.
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-25T09:00:00Z",
             "interval_end": "2026-07-25T11:00:00Z",
             "core_temp_c": 5.0, "avg_temp_c": 5.0,
             "source": "CONTINUOUS_MONITOR"}, QA))
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-25T11:00:00Z",
             "interval_end": "2026-07-25T12:59:00Z",
             "core_temp_c": 5.0, "avg_temp_c": 5.0,
             "source": "CONTINUOUS_MONITOR"}, QA))
        mid = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert mid["cumulative_abuse_minutes"] == 239
        assert mid["status"] == "UNDER_INSPECTION"

        qa09 = make_qa_tech_headers("qa-09")
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-25T12:59:00Z",
             "interval_end": "2026-07-25T13:00:00Z",
             "core_temp_c": 5.0, "avg_temp_c": 5.0,
             "source": "MANUAL_PROBE"}, qa09))
        after = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert after["cumulative_abuse_minutes"] == 240
        assert after["status"] == "QUARANTINED"

        cas, meta = validate_paginated(api.list_corrective_actions(
            CM, params={"receipt_lot_id": lot["id"]}))
        assert meta["total_count"] == 1
        assert cas[0]["source_type"] == "TEMPERATURE_ABUSE"
        assert cas[0]["opened_by"] == "qa-09"

    def test_abuse_accumulation_permanently_blocks_acceptance(self, api):
        """PRD: "The lot's `cumulative_abuse_minutes` must be strictly less
        than 240. At exactly 240 or above, acceptance is rejected with
        `ERR_TEMPERATURE_ABUSE_EXCEEDED` (HTTP 422)." The quarantine-release
        path re-applies the same gate: "abuse minutes must be below 240
        (`ERR_TEMPERATURE_ABUSE_EXCEEDED`)".

        Design: Corner/calculations/abuse_minutes_240_boundary
        """
        supplier, entry, lot = _setup_tuna_lot(
            api, frn="FRN-CAL2", entry_number="E-CAL2", country="EC",
            receiving_temp_c=5.0, name="Meridian Marine")
        qa09 = make_qa_tech_headers("qa-09")
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-25T09:00:00Z",
             "interval_end": "2026-07-25T13:00:00Z",
             "core_temp_c": 5.0, "avg_temp_c": 5.0,
             "source": "CONTINUOUS_MONITOR"}, qa09))
        after = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert after["cumulative_abuse_minutes"] == 240
        assert after["status"] == "QUARANTINED"

        # Satisfy the other quarantine-release gates (verification CONFIRMED
        # and histamine PASS are both attainable on a QUARANTINED lot) so the
        # abuse gate is the only failing check.
        verify_species(lot["id"], "TUNA")
        get_success_data(api.create_haccp_record(
            {"hazard_type": "HISTAMINE", "receipt_lot_id": lot["id"],
             "phase": "SCREENING", "measured_value": 30.0,
             "measured_at": "2026-07-25T14:00:00Z"}, QA))

        # Even with the CA resolved, the abuse gate still blocks release.
        cas, _ = validate_paginated(api.list_corrective_actions(
            CM, params={"receipt_lot_id": lot["id"]}))
        ca_id = cas[0]["id"]
        cm01 = make_compliance_manager_headers("cm-01")
        get_success_data(api.investigate_corrective_action(ca_id, cm01))
        get_success_data(api.resolve_corrective_action(
            ca_id, "lot destroyed documentation", cm01))
        resp = api.quarantine_release_receipt_lot(lot["id"], CM)
        validate_error(resp, ApiErrorId.ERR_TEMPERATURE_ABUSE_EXCEEDED)
