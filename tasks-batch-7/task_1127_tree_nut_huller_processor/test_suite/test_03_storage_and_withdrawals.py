"""Storage bins, placements, FIFO withdrawals, and the dispose cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_placement,
    create_bin,
    create_completed_run,
    create_grower,
    create_placement,
    create_processed_lot,
    get_lot,
    make_admin_headers,
    make_intake_headers,
    make_operator_headers,
    record_aflatoxin,
    record_kernel_grade,
    set_clock,
    setup_bin_with_stored_placement,
    setup_planned_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlacementGuards:
    def test_bin_rejects_disallowed_product_form(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals): "The bin must
        admit the form: a `product_form` outside the bin's
        `allowed_product_forms` draws `ERR_BIN_PRODUCT_MISMATCH`."

        Design: Corner/validations/bin_rejects_disallowed_product_form
        """
        processed = create_processed_lot(
            gross_weight_lbs=5000, kernel_out_lbs=2400, shell_out_lbs=1300,
            hull_out_lbs=900, record_grade=False,
        )
        bin_ = create_bin(bin_code="B-K", capacity_lbs=5000,
                          allowed_product_forms=["KERNEL"])
        resp = api.create_placement(
            {
                "bin_id": bin_["id"],
                "lot_id": processed["lot"]["id"],
                "product_form": "HULL",
                "quantity_lbs": 100,
            },
            make_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_BIN_PRODUCT_MISMATCH)

    def test_placement_cumulative_lot_output_exceeded(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals): "the cumulative
        placed weight of that product_form for that lot — across all bins — may
        not exceed the lot's recorded output of that form, else
        ERR_LOT_OUTPUT_EXCEEDED."

        Design: Corner/validations/placement_cumulative_lot_output_exceeded
        """
        processed = create_processed_lot(
            gross_weight_lbs=5000, kernel_out_lbs=2400, shell_out_lbs=1300,
            hull_out_lbs=900,
        )
        bin_ = create_bin(capacity_lbs=8000, allowed_product_forms=["KERNEL"])
        create_placement(bin_["id"], processed["lot"]["id"], quantity_lbs=2000)
        resp = api.create_placement(
            {
                "bin_id": bin_["id"],
                "lot_id": processed["lot"]["id"],
                "product_form": "KERNEL",
                "quantity_lbs": 500,
            },
            make_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_LOT_OUTPUT_EXCEEDED)

    def test_bin_capacity_exact_fill(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals): "Capacity must
        hold with equality allowed: the bin's occupied_lbs plus the new
        quantity_lbs may equal but not exceed capacity_lbs, else
        ERR_BIN_CAPACITY_EXCEEDED."

        Design: Difficulty/boundary_precision_check/bin_capacity_exact_fill
        """
        processed = create_processed_lot(
            gross_weight_lbs=5000, kernel_out_lbs=2500, shell_out_lbs=1200,
            hull_out_lbs=900,
        )
        bin_ = create_bin(capacity_lbs=2000, allowed_product_forms=["KERNEL"])
        create_placement(bin_["id"], processed["lot"]["id"], quantity_lbs=1200)
        resp = api.create_placement(
            {
                "bin_id": bin_["id"],
                "lot_id": processed["lot"]["id"],
                "product_form": "KERNEL",
                "quantity_lbs": 800,
            },
            make_operator_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert_placement(data)
        bin_after = validate_success(api.get_bin(bin_["id"], make_operator_headers()))
        assert bin_after["occupied_lbs"] == pytest.approx(2000, abs=0.01)
        assert bin_after["available_now_lbs"] == pytest.approx(0, abs=0.01)

    def test_bin_capacity_one_pound_over_rejected(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals): "Capacity must
        hold with equality allowed: the bin's `occupied_lbs` plus the new
        `quantity_lbs` may equal but not exceed `capacity_lbs`, else
        `ERR_BIN_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/bin_capacity_exact_fill
        """
        processed = create_processed_lot(
            gross_weight_lbs=6000, kernel_out_lbs=2500, shell_out_lbs=1200,
            hull_out_lbs=900,
        )
        bin_ = create_bin(capacity_lbs=2000, allowed_product_forms=["KERNEL"])
        create_placement(bin_["id"], processed["lot"]["id"], quantity_lbs=1200)
        create_placement(bin_["id"], processed["lot"]["id"], quantity_lbs=800)
        resp = api.create_placement(
            {
                "bin_id": bin_["id"],
                "lot_id": processed["lot"]["id"],
                "product_form": "KERNEL",
                "quantity_lbs": 1,
            },
            make_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_BIN_CAPACITY_EXCEEDED, expected_status=422)


class TestFifoWithdrawal:
    def test_fifo_withdrawal_consumes_oldest_placement_first(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals): "the server
        consumes the bin's STORED placements of that form in first-in-first-out
        order — sorted by placed_at ascending, ties broken by created_at
        ascending, never by identifier."

        Design: Corner/calculations/fifo_withdrawal_consumes_oldest_placement_first
        """
        processed = create_processed_lot(
            gross_weight_lbs=5000, kernel_out_lbs=2400, shell_out_lbs=1300,
            hull_out_lbs=900,
        )
        bin_ = create_bin(capacity_lbs=5000, allowed_product_forms=["KERNEL"])
        p1 = create_placement(bin_["id"], processed["lot"]["id"], quantity_lbs=500)
        set_clock("2026-05-02T00:00:00Z")
        p2 = create_placement(bin_["id"], processed["lot"]["id"], quantity_lbs=500)

        resp = api.create_withdrawal(
            {"bin_id": bin_["id"], "product_form": "KERNEL", "quantity_lbs": 700},
            make_operator_headers(),
        )
        wd = validate_success(resp, expected_status=201)
        assert len(wd["allocations"]) == 2
        assert wd["allocations"][0]["placement_id"] == p1["id"]
        assert wd["allocations"][0]["quantity_lbs"] == pytest.approx(500, abs=0.01)
        assert wd["allocations"][1]["placement_id"] == p2["id"]
        assert wd["allocations"][1]["quantity_lbs"] == pytest.approx(200, abs=0.01)

        p1_after = validate_success(api.get_placement(p1["id"], make_operator_headers()))
        p2_after = validate_success(api.get_placement(p2["id"], make_operator_headers()))
        assert p1_after["status"] == "WITHDRAWN"
        assert p1_after["remaining_lbs"] == pytest.approx(0, abs=0.01)
        assert p2_after["remaining_lbs"] == pytest.approx(300, abs=0.01)
        bin_after = validate_success(api.get_bin(bin_["id"], make_operator_headers()))
        assert bin_after["occupied_lbs"] == pytest.approx(300, abs=0.01)

    def test_withdrawal_beyond_stored_pool_rejected(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals): "If the free
        pool across all matching stored placements is smaller than the request,
        the withdrawal is rejected with ERR_INSUFFICIENT_STORED."

        Design: Corner/validations/withdrawal_beyond_stored_pool_rejected
        """
        scenario = setup_bin_with_stored_placement(placement_quantity=600)
        resp = api.create_withdrawal(
            {
                "bin_id": scenario["bin"]["id"],
                "product_form": "KERNEL",
                "quantity_lbs": 1000,
            },
            make_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STORED)
        p_after = validate_success(
            api.get_placement(scenario["placement"]["id"], make_operator_headers())
        )
        assert p_after["remaining_lbs"] == pytest.approx(600, abs=0.01)


class TestBinOccupancyRoundtrip:
    def test_place_then_withdraw_returns_occupancy_to_zero(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals): "occupied_lbs
        sums remaining_lbs over the bin's placements in STORED, FUMIGATION_HOLD,
        or QUARANTINED status — withdrawn and disposed placements no longer
        occupy space."

        Design: Difficulty/compensating_invariant/bin_occupancy_place_withdraw_roundtrip
        """
        processed = create_processed_lot(
            gross_weight_lbs=5000, kernel_out_lbs=2400, shell_out_lbs=1300,
            hull_out_lbs=900,
        )
        bin_ = create_bin(capacity_lbs=5000, allowed_product_forms=["KERNEL"])
        before = validate_success(api.get_bin(bin_["id"], make_operator_headers()))
        assert before["occupied_lbs"] == pytest.approx(0, abs=0.01)

        placement = create_placement(bin_["id"], processed["lot"]["id"],
                                     quantity_lbs=2000)
        mid = validate_success(api.get_bin(bin_["id"], make_operator_headers()))
        assert mid["occupied_lbs"] == pytest.approx(2000, abs=0.01)

        validate_success(
            api.create_withdrawal(
                {"bin_id": bin_["id"], "product_form": "KERNEL", "quantity_lbs": 2000},
                make_operator_headers(),
            ),
            expected_status=201,
        )
        after = validate_success(api.get_bin(bin_["id"], make_operator_headers()))
        assert after["occupied_lbs"] == pytest.approx(0, abs=0.01)

    def test_withdrawal_allocations_record_and_placement_withdrawn(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals): "The
        consumption is recorded on the withdrawal as allocations, an ordered
        list of the placements consumed with each entry's placement, its lot,
        and the quantity taken" and "Placements whose remaining_lbs reaches zero
        — here or through shipment confirmation — transition from STORED to
        WITHDRAWN".

        Design: Difficulty/compensating_invariant/bin_occupancy_place_withdraw_roundtrip
        """
        processed = create_processed_lot(
            gross_weight_lbs=5000, kernel_out_lbs=2400, shell_out_lbs=1300,
            hull_out_lbs=900,
        )
        bin_ = create_bin(capacity_lbs=5000, allowed_product_forms=["KERNEL"])
        placement = create_placement(bin_["id"], processed["lot"]["id"],
                                     quantity_lbs=2000)
        resp = api.create_withdrawal(
            {"bin_id": bin_["id"], "product_form": "KERNEL", "quantity_lbs": 2000},
            make_operator_headers(),
        )
        wd = validate_success(resp, expected_status=201)
        assert len(wd["allocations"]) == 1
        assert wd["allocations"][0]["placement_id"] == placement["id"]
        assert wd["allocations"][0]["lot_id"] == processed["lot"]["id"]
        assert wd["allocations"][0]["quantity_lbs"] == pytest.approx(2000, abs=0.01)
        p_after = validate_success(
            api.get_placement(placement["id"], make_operator_headers())
        )
        assert p_after["status"] == "WITHDRAWN"
        assert p_after["remaining_lbs"] == pytest.approx(0, abs=0.01)


class TestDisposeCascade:
    def test_lot_dispose_cascades_quarantined_placements_to_disposed(self, api):
        """PRD (Field Lot Intake): "disposing a REJECTED lot moves it to
        DISPOSED, moves its QUARANTINED placements to DISPOSED, and recomputes
        the affected bins' occupancy fields since the disposed weight physically
        leaves the bins."

        Design: Corner/state_machines/lot_dispose_cascades_quarantined_placements_to_disposed
        """
        scenario = setup_bin_with_stored_placement(placement_quantity=2000)
        lot_id = scenario["lot"]["id"]
        record_aflatoxin(lot_id, aflatoxin_ppb=30.0)  # FAIL -> REJECTED + quarantine

        resp = api.dispose_lot(lot_id, make_intake_headers())
        data = validate_success(resp)
        assert data["status"] == "DISPOSED"

        p_after = validate_success(
            api.get_placement(scenario["placement"]["id"], make_operator_headers())
        )
        assert p_after["status"] == "DISPOSED"
        bin_after = validate_success(
            api.get_bin(scenario["bin"]["id"], make_operator_headers())
        )
        assert bin_after["occupied_lbs"] == pytest.approx(0, abs=0.01)


class TestPlacementListing:
    def test_placements_filtered_list_reverse_reaches_fk(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals): "Placements and
        withdrawals may be listed — placements filtered by bin_id, lot_id, or
        status".

        Design: Corner/endpoints/placements_filtered_list_reverse_reaches_fk
        """
        scenario = setup_bin_with_stored_placement(placement_quantity=700)
        bin_id = scenario["bin"]["id"]
        lot_id = scenario["lot"]["id"]
        placement_id = scenario["placement"]["id"]

        data1, meta1 = validate_paginated(
            api.list_placements(make_operator_headers(), params={"bin_id": bin_id})
        )
        assert len(data1) == 1
        assert data1[0]["id"] == placement_id

        data2, meta2 = validate_paginated(
            api.list_placements(
                make_operator_headers(), params={"lot_id": lot_id, "status": "STORED"}
            )
        )
        assert len(data2) == 1
        assert data2[0]["id"] == placement_id


class TestImmediateConsistency:
    def test_placement_create_immediately_visible_in_bin_read(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals): "A successful
        placement is created in `STORED` status with `remaining_lbs` initialized
        equal to `quantity_lbs`, `allocated_planned_lbs` at 0, and `placed_at`
        stamped from the logical clock; the bin's occupancy figures are
        recomputed." PRD (Introduction): "weights, reservations, and cents are
        recomputed deterministically from recorded events".

        Design: Corner/consistency_model/placement_create_immediately_visible_in_bin_read
        """
        processed = create_processed_lot(
            gross_weight_lbs=5000, kernel_out_lbs=2400, shell_out_lbs=1300,
            hull_out_lbs=900,
        )
        bin_ = create_bin(capacity_lbs=5000, allowed_product_forms=["KERNEL"])
        resp = api.create_placement(
            {
                "bin_id": bin_["id"],
                "lot_id": processed["lot"]["id"],
                "product_form": "KERNEL",
                "quantity_lbs": 700,
            },
            make_operator_headers(),
        )
        placement = validate_success(resp, expected_status=201)
        assert placement["remaining_lbs"] == pytest.approx(700, abs=0.01)
        assert placement["status"] == "STORED"
        bin_after = validate_success(api.get_bin(bin_["id"], make_operator_headers()))
        assert bin_after["occupied_lbs"] == pytest.approx(700, abs=0.01)
        assert bin_after["available_now_lbs"] == pytest.approx(4300, abs=0.01)
