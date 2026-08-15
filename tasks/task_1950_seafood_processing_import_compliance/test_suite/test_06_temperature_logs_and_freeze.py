"""Temperature logs: half-open interval overlap, subject ambiguity, and
freeze-protocol compliance accumulation (incl. COMBO phases)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_supplier,
    create_lot,
    create_released_entry,
    create_temperature_log_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

QA = TEST_USERS["qa_tech_headers"]
RI = TEST_USERS["receiving_inspector_headers"]
CM = TEST_USERS["compliance_manager_headers"]


def _setup_lot(api, frn="FRN-9001", entry_number="E-9001", species="COD",
               freeze_protocol="NONE", transport_mode="ROAD"):
    supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                        frn=frn)
    entry = create_released_entry(supplier["id"], entry_number=entry_number,
                                  species=species, transport_mode=transport_mode)
    lot = create_lot(entry["id"], species=species, quantity_received_kg=100,
                     freeze_protocol=freeze_protocol)
    return supplier, entry, lot


class TestIntervalOverlap:
    def test_temperature_log_adjacent_half_open_allowed(self, api):
        """PRD: "Temperature intervals for the same subject are half-open: the
        start is inclusive, the end is exclusive. A new interval that overlaps
        an existing interval for the same subject is rejected with
        `ERR_TEMPERATURE_INTERVAL_OVERLAP` (HTTP 422). Adjacency is allowed —
        a new interval whose start equals an existing interval's end is not an
        overlap."

        Design: Difficulty/resource_temporal_overlap/temperature_log_adjacent_half_open_allowed
        """
        supplier, entry, lot = _setup_lot(api)
        log1 = validate_success(api.create_temperature_log(
            create_temperature_log_payload(
                receipt_lot_id=lot["id"],
                interval_start="2026-07-25T10:00:00Z",
                interval_end="2026-07-25T11:00:00Z"),
            QA), 201)
        # Adjacent: new start == existing end -> allowed.
        log2 = validate_success(api.create_temperature_log(
            create_temperature_log_payload(
                receipt_lot_id=lot["id"],
                interval_start="2026-07-25T11:00:00Z",
                interval_end="2026-07-25T12:00:00Z"),
            QA), 201)

        # True overlap: 10:30-11:30 intersects both existing intervals.
        resp = api.create_temperature_log(
            create_temperature_log_payload(
                receipt_lot_id=lot["id"],
                interval_start="2026-07-25T10:30:00Z",
                interval_end="2026-07-25T11:30:00Z",
                source="MANUAL_PROBE"),
            QA)
        validate_error(resp, ApiErrorId.ERR_TEMPERATURE_INTERVAL_OVERLAP)

        logs, meta = validate_paginated(api.list_temperature_logs(
            QA, params={"receipt_lot_id": lot["id"]}))
        assert meta["total_count"] == 2
        assert {l["id"] for l in logs} == {log1["id"], log2["id"]}

    def test_overlap_rejection_leaves_existing_intervals_intact(self, api):
        """PRD: "A new interval that overlaps an existing interval for the same
        subject is rejected with `ERR_TEMPERATURE_INTERVAL_OVERLAP` (HTTP
        422)." A rejected append does not remove or modify existing logs.

        Design: Difficulty/resource_temporal_overlap/temperature_log_adjacent_half_open_allowed
        """
        supplier, entry, lot = _setup_lot(api)
        get_success_data(api.create_temperature_log(
            create_temperature_log_payload(
                receipt_lot_id=lot["id"],
                interval_start="2026-07-25T10:00:00Z",
                interval_end="2026-07-25T11:00:00Z"), QA))
        resp = api.create_temperature_log(
            create_temperature_log_payload(
                receipt_lot_id=lot["id"],
                interval_start="2026-07-25T10:45:00Z",
                interval_end="2026-07-25T11:45:00Z",
                source="MANUAL_PROBE"), QA)
        validate_error(resp, ApiErrorId.ERR_TEMPERATURE_INTERVAL_OVERLAP)
        logs, meta = validate_paginated(api.list_temperature_logs(
            QA, params={"receipt_lot_id": lot["id"]}))
        assert meta["total_count"] == 1


class TestAmbiguousSubject:
    def test_ambiguous_temperature_subject_rejected(self, api):
        """PRD: "Temperature logs record thermal intervals for either a receipt
        lot or a processing batch — exactly one subject must be specified per
        log. Providing both `receipt_lot_id` and `processing_batch_id`, or
        neither, is rejected with `ERR_AMBIGUOUS_SUBJECT` (HTTP 400)."

        Design: Corner/validations/ambiguous_temperature_subject_rejected
        """
        resp = api.create_temperature_log(
            create_temperature_log_payload(), QA)
        validate_error(resp, ApiErrorId.ERR_AMBIGUOUS_SUBJECT)


class TestFreezeComboProtocol:
    def test_freeze_combo_protocol_cumulative_phases(self, api):
        """PRD: "`COMBO`: two phases. Phase 1 requires at least 240 minutes
        (4 hours) with `core_temp_c` at or below -35.0. Phase 2 counts only
        intervals whose `interval_start` is at or after the end of the first
        interval that reached -35.0 or below; in those intervals, minutes with
        `core_temp_c` at or below -20.0 must total at least 1,440 minutes
        (24 hours). Both phases must pass."
        PRD: "Intervals above the threshold contribute 0 minutes — the
        accumulation pauses but does not reset."

        Design: Difficulty/combinatorial_formula/freeze_combo_protocol_cumulative
        """
        supplier = create_approved_supplier(name="Nordic Fish Co", country="NO",
                                            frn="FRN-3001")
        entry = create_released_entry(
            supplier["id"], entry_number="E-3001", species="SALMON",
            transport_mode="AIR", goods_value_cents=800000,
            freight_cost_cents=90000, duty_rate_pct=0.0, total_weight_kg=120)
        lot = create_lot(entry["id"], species="SALMON",
                         quantity_received_kg=120, harvest_country_code="NO",
                         catch_area_code="FAO27", production_method="FARMED",
                         vessel_name="FV Nord", receiving_temp_c=0.0,
                         freeze_protocol="COMBO")

        # Phase 1: 300 min at -36.0 (>= 240 blast requirement met).
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-25T08:00:00Z",
             "interval_end": "2026-07-25T13:00:00Z",
             "core_temp_c": -36.0, "avg_temp_c": -33.0,
             "source": "CONTINUOUS_MONITOR"}, QA))
        mid1 = validate_success(api.get_receipt_lot(lot["id"], QA))
        # Blast met, but hold phase has no qualifying minutes yet.
        assert mid1["freeze_compliant"] is False

        # 120 min at -18.0: above the -20.0 hold threshold -> pause, no reset.
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-25T13:00:00Z",
             "interval_end": "2026-07-25T15:00:00Z",
             "core_temp_c": -18.0, "avg_temp_c": -16.0,
             "source": "CONTINUOUS_MONITOR"}, QA))
        mid2 = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert mid2["freeze_compliant"] is False

        # 1500 min at -22.0 (<= -20.0): hold accumulates past 1440 -> pass.
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-25T15:00:00Z",
             "interval_end": "2026-07-26T16:00:00Z",
             "core_temp_c": -22.0, "avg_temp_c": -21.0,
             "source": "CONTINUOUS_MONITOR"}, QA))
        done = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert done["freeze_compliant"] is True

    def test_freeze_pause_does_not_reset_accumulation(self, api):
        """PRD: "Intervals above the threshold contribute 0 minutes — the
        accumulation pauses but does not reset." An intervening warm interval
        leaves previously accumulated qualifying minutes intact, so a
        subsequent qualifying interval can complete the requirement.

        Design: Difficulty/combinatorial_formula/freeze_combo_protocol_cumulative
        """
        supplier = create_approved_supplier(name="Nordic Fish Co", country="NO",
                                            frn="FRN-3001")
        entry = create_released_entry(
            supplier["id"], entry_number="E-3001", species="SALMON",
            transport_mode="AIR", goods_value_cents=800000,
            freight_cost_cents=90000, duty_rate_pct=0.0, total_weight_kg=120)
        lot = create_lot(entry["id"], species="SALMON",
                         quantity_received_kg=120, harvest_country_code="NO",
                         catch_area_code="FAO27", production_method="FARMED",
                         vessel_name="FV Nord", receiving_temp_c=0.0,
                         freeze_protocol="COMBO")

        # Blast phase: exactly 240 minutes at <= -35.
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-25T08:00:00Z",
             "interval_end": "2026-07-25T12:00:00Z",
             "core_temp_c": -36.0, "avg_temp_c": -33.0,
             "source": "CONTINUOUS_MONITOR"}, QA))
        # Warm pause (above -20.0).
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-25T12:00:00Z",
             "interval_end": "2026-07-25T14:00:00Z",
             "core_temp_c": -18.0, "avg_temp_c": -16.0,
             "source": "CONTINUOUS_MONITOR"}, QA))
        # First hold leg: 1000 minutes at <= -20.
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-25T14:00:00Z",
             "interval_end": "2026-07-26T06:40:00Z",
             "core_temp_c": -22.0, "avg_temp_c": -21.0,
             "source": "CONTINUOUS_MONITOR"}, QA))
        mid = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert mid["freeze_compliant"] is False

        # Second warm pause: proves accumulation pauses rather than resets.
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-26T06:40:00Z",
             "interval_end": "2026-07-26T08:00:00Z",
             "core_temp_c": -18.0, "avg_temp_c": -16.0,
             "source": "CONTINUOUS_MONITOR"}, QA))
        # Final hold leg: 440 more minutes at <= -20 -> 1440 total.
        get_success_data(api.create_temperature_log(
            {"receipt_lot_id": lot["id"],
             "interval_start": "2026-07-26T08:00:00Z",
             "interval_end": "2026-07-26T15:20:00Z",
             "core_temp_c": -22.0, "avg_temp_c": -21.0,
             "source": "CONTINUOUS_MONITOR"}, QA))
        done = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert done["freeze_compliant"] is True
