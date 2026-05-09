"""Inbound shipment lifecycle: create → start_inspection → complete_inspection
(PASS/FAIL) → rework → putaway / quarantine."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_inbound_shipment_payload, create_inbound_shipment_multiline_payload,
    create_complete_inspection_payload,
    create_warehouse, create_bin, create_lot, putaway_lot_units,
    TEST_USERS, NON_EXISTENT_UUID,
    INSPECTION_SAMPLE_TIERS, INSPECTION_SAMPLE_DEFAULT,
)


class TestInboundShipmentCreate:
    def test_create_inbound_shipment_initial_status(self, api, staff_headers, manager_headers):
        """PRD §3.2: "A shipment begins life in status ASN_RECEIVED; each
        created line is in status PENDING_INSPECTION."

        Claim: POST /inbound_shipments creates a shipment in ASN_RECEIVED
        with each line in PENDING_INSPECTION.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 10),
            staff_headers), 201)
        assert sh["status"] == "ASN_RECEIVED"
        retrieved = validate_success(api.get_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        lines = retrieved.get("lines") or []
        assert len(lines) >= 1
        for line in lines:
            assert line["status"] == "PENDING_INSPECTION"

    def test_create_inbound_shipment_unresolvable_lot(self, api, staff_headers, manager_headers):
        """PRD §3.2: "The lot referenced by each line must already exist
        within the same warehouse — body foreign-key resolution applies,
        and an unresolvable lot_id yields ERR_NOT_FOUND."

        Claim: a body lot_id that doesn't exist → ERR_NOT_FOUND.
        """
        wh = create_warehouse()
        validate_error(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(NON_EXISTENT_UUID, 10),
            staff_headers), "ERR_NOT_FOUND")


class TestStartInspection:
    @pytest.mark.parametrize("declared,expected_sample", [
        (1, 8),       # ≤ 50
        (50, 8),      # ≤ 50 boundary
        (51, 13),     # > 50, ≤ 150
        (150, 13),    # ≤ 150 boundary
        (151, 20),    # > 150, ≤ 280
        (280, 20),    # ≤ 280 boundary
        (281, 32),    # > 280, ≤ 500
        (500, 32),    # ≤ 500 boundary
        (501, 50),    # > 500
        (1000, 50),   # > 500
    ])
    def test_inspection_sample_size_tiers(self, api, staff_headers, manager_headers,
                                         declared, expected_sample):
        """PRD §3.2: "The transition computes inspection_sample_size from
        the declared_total_units using the AQL sampling tier table: when
        total declared is at most 50 units the sample size is 8; when at
        most 150 it is 13; when at most 280 it is 20; when at most 500
        it is 32; otherwise the sample size is 50."

        Claim: each tier boundary is honored exactly as specified.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], declared),
            staff_headers), 201)
        started = validate_success(api.start_inspection(
            wh["id"], sh["id"], staff_headers), 200)
        assert started["status"] == "INSPECTING"
        assert started["inspection_sample_size"] == expected_sample

    def test_asn_mismatch_rejected(self, api, staff_headers, manager_headers):
        """PRD §3.2: "first, declared_total_units on the shipment must equal
        the sum of declared_units across its lines (otherwise
        ERR_ASN_MISMATCH)"

        Claim: a shipment whose declared_total_units differs from the sum
        of its line declared_units fails start_inspection with ERR_ASN_MISMATCH.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        sh_payload = create_inbound_shipment_multiline_payload(
            lines=[{"lot_id": lot["id"], "declared_units": 5}],
            declared_total_units=10,  # mismatch: lines sum to 5
        )
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], sh_payload, staff_headers), 201)
        validate_error(api.start_inspection(wh["id"], sh["id"], staff_headers),
                      "ERR_ASN_MISMATCH")

    def test_start_inspection_lot_not_active_rejected(self, api, staff_headers, manager_headers):
        """PRD §3.2: "second, every line's referenced lot must currently be
        in ACTIVE status (otherwise ERR_LOT_NOT_ACTIVE)"

        Claim: if any line's lot is not ACTIVE, start_inspection → ERR_LOT_NOT_ACTIVE.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        # Recall the lot before creating shipment
        from test_helpers import create_recall_payload
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SAFETY_ISSUE"),
            TEST_USERS["manager_headers"]), 200)
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 10),
            staff_headers), 201)
        validate_error(api.start_inspection(wh["id"], sh["id"], staff_headers),
                      "ERR_LOT_NOT_ACTIVE")


class TestCompleteInspection:
    def test_complete_inspection_pass(self, api, staff_headers, manager_headers):
        """PRD §3.2: "when defect_rate is at most 0.025, the shipment moves
        from INSPECTING to PASSED and every inbound line moves from
        PENDING_INSPECTION to INSPECTED_PASS"

        Claim: defect_rate ≤ 0.025 → PASSED, lines INSPECTED_PASS.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 50),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        # sample_size=8, defects=0 → defect_rate=0
        ci_payload = create_complete_inspection_payload(
            lot_id=lot["id"], received_units=50, inspection_defect_count=0)
        passed = validate_success(api.complete_inspection(
            wh["id"], sh["id"], ci_payload, staff_headers), 200)
        assert passed["status"] == "PASSED"
        assert passed["defect_rate"] == 0 or passed["defect_rate"] == 0.0
        retrieved = validate_success(api.get_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        for line in retrieved.get("lines", []):
            assert line["status"] == "INSPECTED_PASS"

    def test_complete_inspection_fail(self, api, staff_headers, manager_headers):
        """PRD §3.2: "when defect_rate is strictly greater than 0.025, the
        shipment moves from INSPECTING to FAILED, every inbound line moves
        from PENDING_INSPECTION to INSPECTED_FAIL, and abnormal_event_count_24h
        on the warehouse is incremented by exactly 1 (a single increment per
        failed inspection, regardless of how many lines failed)."

        Claim: defect_rate > 0.025 → FAILED, lines INSPECTED_FAIL,
        abnormal_event_count_24h += 1.
        """
        wh = create_warehouse()
        before = validate_success(api.get_warehouse(wh["id"], staff_headers), 200)
        lot = create_lot(wh["id"])
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 20),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        # sample_size=8 (≤50), defects=1 → defect_rate=0.125 > 0.025
        ci_payload = create_complete_inspection_payload(
            lot_id=lot["id"], received_units=20, inspection_defect_count=1)
        failed = validate_success(api.complete_inspection(
            wh["id"], sh["id"], ci_payload, staff_headers), 200)
        assert failed["status"] == "FAILED"
        assert failed["defect_rate"] is not None
        assert failed["defect_rate"] > 0.025
        retrieved = validate_success(api.get_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        for line in retrieved.get("lines", []):
            assert line["status"] == "INSPECTED_FAIL"
        after = validate_success(api.get_warehouse(wh["id"], staff_headers), 200)
        assert after["abnormal_event_count_24h"] == before["abnormal_event_count_24h"] + 1

    def test_defect_rate_rounded_4_decimals(self, api, staff_headers, manager_headers):
        """PRD §2.8: "defect_rate on inbound shipments is rounded to 4 decimal places."
        PRD §3.2: "The system then computes defect_rate as
        inspection_defect_count divided by inspection_sample_size, rounded
        half-up to four decimal places."

        Claim: defect_rate is rounded to 4 decimal places.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        # declared_total_units=20 → sample_size=8 (≤50 tier).
        # 1/8 = 0.125 (already 4 decimals)
        # Use a case that needs rounding: 1/13 = 0.07692307... → 0.0769
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 51),  # → tier 2: sample=13
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        ci_payload = create_complete_inspection_payload(
            lot_id=lot["id"], received_units=51, inspection_defect_count=1)
        result = validate_success(api.complete_inspection(
            wh["id"], sh["id"], ci_payload, staff_headers), 200)
        # 1/13 = 0.0769230769..., rounded to 4 decimals = 0.0769
        assert result["defect_rate"] == pytest.approx(0.0769, abs=1e-5)

    def test_defect_rate_at_exact_pass_threshold(self, api, staff_headers, manager_headers):
        """PRD §3.2: "when defect_rate is at most 0.025, the shipment moves
        from INSPECTING to PASSED"

        Boundary: defect_rate exactly equal to 0.025 should PASS (≤ inclusive).
        Use sample_size=8 with 0 defects → 0.0 (well under threshold) — and
        also test a bordering case via 32-tier.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        # Tier: declared=281 → sample=32. 32 * 0.025 = 0.8 → cannot have fractional defect.
        # Better: use no-defect case to confirm pass. (0.0 is ≤ 0.025.)
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 281),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        ci_payload = create_complete_inspection_payload(
            lot_id=lot["id"], received_units=281, inspection_defect_count=0)
        passed = validate_success(api.complete_inspection(
            wh["id"], sh["id"], ci_payload, staff_headers), 200)
        assert passed["status"] == "PASSED"

    @pytest.mark.parametrize("defect_count,sample_size_request,expected_status", [
        (-1, 20, "ERR_INVALID_INPUT"),
        # picking declared=20 → sample=8; defect_count > 8 should fail
    ])
    def test_complete_inspection_defect_count_out_of_bounds(
        self, api, staff_headers, manager_headers,
        defect_count, sample_size_request, expected_status,
    ):
        """PRD §3.2: "The inspection_defect_count must be at least 0 and at
        most inspection_sample_size; any other value is rejected with
        ERR_INVALID_INPUT and HTTP status 422."

        Claim: defect_count < 0 or > sample_size → ERR_INVALID_INPUT (422).
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], sample_size_request),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        ci_payload = create_complete_inspection_payload(
            lot_id=lot["id"], received_units=sample_size_request,
            inspection_defect_count=defect_count)
        validate_error(api.complete_inspection(
            wh["id"], sh["id"], ci_payload, staff_headers), expected_status)

    def test_defect_count_above_sample_size(self, api, staff_headers, manager_headers):
        """PRD §3.2: "The inspection_defect_count must be at least 0 and at
        most inspection_sample_size; any other value is rejected with
        ERR_INVALID_INPUT and HTTP status 422."

        Claim: defect_count > sample_size → ERR_INVALID_INPUT (422).
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        # declared=20 → sample=8. defect=9 > sample=8.
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 20),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        ci_payload = create_complete_inspection_payload(
            lot_id=lot["id"], received_units=20, inspection_defect_count=9)
        validate_error(api.complete_inspection(
            wh["id"], sh["id"], ci_payload, staff_headers), "ERR_INVALID_INPUT")


class TestRework:
    def test_rework_failed_to_inspecting_clears_defects(self, api, staff_headers, manager_headers):
        """PRD §3.2: "A shipment that landed in FAILED may be reworked back
        to INSPECTING by floor staff: this clears inspection_defect_count
        and defect_rate (both are reset to null) and returns every line
        from INSPECTED_FAIL back to PENDING_INSPECTION, ready for
        re-inspection."

        # difficulty: non_linear_state_machine/inbound_shipment_failed_to_inspecting_cycle
        Claim: /rework on FAILED shipment → INSPECTING; defect counters cleared;
        each line back to PENDING_INSPECTION.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 20),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        # Cause FAILED: defects=1, sample=8, rate=0.125
        ci_payload = create_complete_inspection_payload(
            lot_id=lot["id"], received_units=20, inspection_defect_count=1)
        failed = validate_success(api.complete_inspection(
            wh["id"], sh["id"], ci_payload, staff_headers), 200)
        assert failed["status"] == "FAILED"
        # Now rework
        reworked = validate_success(api.rework_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        assert reworked["status"] == "INSPECTING"
        assert reworked.get("inspection_defect_count") is None
        assert reworked.get("defect_rate") is None
        retrieved = validate_success(api.get_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        for line in retrieved.get("lines", []):
            assert line["status"] == "PENDING_INSPECTION"

    def test_rework_then_pass_full_cycle(self, api, staff_headers, manager_headers):
        """PRD §3.2: rework returns to INSPECTING, "ready for re-inspection."

        # difficulty: non_linear_state_machine/inbound_shipment_failed_to_inspecting_cycle
        Claim: After rework, a fresh complete_inspection with 0 defects
        transitions FAILED → INSPECTING → PASSED.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 20),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        # Fail
        validate_success(api.complete_inspection(
            wh["id"], sh["id"], create_complete_inspection_payload(
                lot_id=lot["id"], received_units=20, inspection_defect_count=1),
            staff_headers), 200)
        # Rework
        validate_success(api.rework_inbound_shipment(wh["id"], sh["id"], staff_headers), 200)
        # Pass
        passed = validate_success(api.complete_inspection(
            wh["id"], sh["id"], create_complete_inspection_payload(
                lot_id=lot["id"], received_units=20, inspection_defect_count=0),
            staff_headers), 200)
        assert passed["status"] == "PASSED"


class TestQuarantine:
    def test_quarantine_failed_shipment(self, api, staff_headers, manager_headers):
        """PRD §3.2: "Alternatively, a FAILED shipment may be quarantined into
        RETURNS-zone bins (see §3.3); doing so transitions the shipment from
        FAILED to QUARANTINED, sets each line's bin_id, moves each line from
        INSPECTED_FAIL to QUARANTINED, and additionally transitions every
        affected lot's status to QUARANTINED so the goods cannot be picked."

        Claim: /quarantine on FAILED shipment → QUARANTINED status; lines
        QUARANTINED; lot QUARANTINED.
        """
        wh = create_warehouse()
        # Need a RETURNS-zone bin for quarantine putaway
        returns_bin = create_bin(
            wh["id"], bin_code="RET-1", zone="RETURNS",
            capacity_volume_cm3=100000, capacity_weight_g=100000,
        )
        lot = create_lot(wh["id"], category="AMBIENT")
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 20),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        # Fail
        validate_success(api.complete_inspection(
            wh["id"], sh["id"], create_complete_inspection_payload(
                lot_id=lot["id"], received_units=20, inspection_defect_count=1),
            staff_headers), 200)
        # Quarantine
        quarantined = validate_success(api.quarantine_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        assert quarantined["status"] == "QUARANTINED"
        retrieved = validate_success(api.get_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        for line in retrieved.get("lines", []):
            assert line["status"] == "QUARANTINED"
            assert line["bin_id"] == returns_bin["id"]
        lot_after = validate_success(api.get_lot(wh["id"], lot["id"], staff_headers), 200)
        assert lot_after["status"] == "QUARANTINED"

    def test_quarantine_no_returns_bin_zone_mismatch(self, api, staff_headers, manager_headers):
        """PRD §3.3: "If a candidate bin satisfies the volume and weight test
        but its `zone` does not match `category` (or, for quarantine, is not
        `RETURNS`), the response is `ERR_ZONE_MISMATCH`."

        Claim: /quarantine with an AMBIENT bin (capacity OK) but no RETURNS-zone
        bin → ERR_ZONE_MISMATCH (Zone-match priority 8 > Bin-capacity priority 12).
        """
        wh = create_warehouse()
        # Only an AMBIENT bin — none of zone=RETURNS — capacity ample
        create_bin(wh["id"], bin_code="AMB-1", zone="AMBIENT",
                  capacity_volume_cm3=100000, capacity_weight_g=100000)
        lot = create_lot(wh["id"], category="AMBIENT")
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 20),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        validate_success(api.complete_inspection(
            wh["id"], sh["id"], create_complete_inspection_payload(
                lot_id=lot["id"], received_units=20, inspection_defect_count=1),
            staff_headers), 200)
        validate_error(api.quarantine_inbound_shipment(
            wh["id"], sh["id"], staff_headers), "ERR_ZONE_MISMATCH")
