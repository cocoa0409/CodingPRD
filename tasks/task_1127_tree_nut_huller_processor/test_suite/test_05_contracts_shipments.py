"""Buyer contracts, shipment planning, OCC, fiscal gates, and safety cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_bin,
    create_buyer,
    create_contract,
    create_grower,
    create_placement,
    create_processed_lot,
    create_routed_lot,
    get_lot,
    make_admin_headers,
    make_lab_headers,
    make_operator_headers,
    record_aflatoxin,
    setup_bin_with_stored_placement,
    setup_planned_shipment,
    validate_error,
    validate_success,
)


class TestContractShipments:
    def test_shipment_quantity_beyond_contract_remaining_rejected(self, api):
        """PRD (Buyer Contracts and Shipment Planning): "the contract's
        `reserved_qty_lbs` plus `delivered_qty_lbs` plus the new `quantity_lbs`
        may not exceed `required_qty_lbs`, else
        `ERR_CONTRACT_REMAINING_EXCEEDED`."

        Design: Corner/validations/shipment_quantity_beyond_contract_remaining_rejected
        """
        scenario = setup_bin_with_stored_placement(
            bin_capacity_lbs=8000, placement_quantity=3000,
            kernel_out_lbs=3500, shell_out_lbs=1500, hull_out_lbs=900,
            gross_weight_lbs=8000,
        )
        buyer = create_buyer()
        contract = create_contract(
            buyer["id"], size_spec="UNSIZED", required_qty_lbs=1000,
        )
        resp = api.create_shipment(
            {
                "contract_id": contract["id"],
                "bin_id": scenario["bin"]["id"],
                "quantity_lbs": 1500,
                "expected_contract_version": contract["version"],
            },
            make_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_REMAINING_EXCEEDED)

    def test_shipment_spec_vs_contract_remaining(self, api):
        """PRD (Validation Order): "when a request violates rules from several
        of the ten categories below, the violation belonging to the earliest
        category is the one reported" — category 9 "the sizing-spec gate on
        shipment allocation (`ERR_SPEC_MISMATCH`, 422)" precedes category 10
        "Contract remaining quantity (`ERR_CONTRACT_REMAINING_EXCEEDED`, 422)".

        Design: Difficulty/priority_pair_validation_conflict/shipment_spec_vs_contract_remaining
        """
        scenario = setup_bin_with_stored_placement(
            bin_capacity_lbs=8000, placement_quantity=3000,
            kernel_out_lbs=3500, shell_out_lbs=1500, hull_out_lbs=900,
            size_spec="SPEC_23_25",
            gross_weight_lbs=8000,
        )
        buyer = create_buyer()
        contract = create_contract(
            buyer["id"], size_spec="SPEC_25_27", required_qty_lbs=2000,
        )
        resp = api.create_shipment(
            {
                "contract_id": contract["id"],
                "bin_id": scenario["bin"]["id"],
                "quantity_lbs": 5000,
                "expected_contract_version": contract["version"],
            },
            make_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_SPEC_MISMATCH, expected_status=422)
        contract_after = validate_success(
            api.get_contract(contract["id"], make_operator_headers())
        )
        assert contract_after["reserved_qty_lbs"] == pytest.approx(0, abs=0.01)

    def test_shipment_spec_mismatch_alone_rejected(self, api):
        """PRD (Buyer Contracts and Shipment Planning): "when the contract's
        size_spec is anything but UNSIZED, every allocated placement's lot must
        carry exactly that size_spec, else ERR_SPEC_MISMATCH."

        Design: Difficulty/priority_pair_validation_conflict/shipment_spec_vs_contract_remaining
        """
        scenario = setup_bin_with_stored_placement(
            bin_capacity_lbs=8000, placement_quantity=3000,
            kernel_out_lbs=3500, shell_out_lbs=1500, hull_out_lbs=900,
            size_spec="SPEC_23_25",
            gross_weight_lbs=8000,
        )
        buyer = create_buyer()
        # Sized contract with plenty of remaining headroom: only the spec gate
        # can fail.
        contract = create_contract(
            buyer["id"], size_spec="SPEC_25_27", required_qty_lbs=20000,
        )
        resp = api.create_shipment(
            {
                "contract_id": contract["id"],
                "bin_id": scenario["bin"]["id"],
                "quantity_lbs": 500,
                "expected_contract_version": contract["version"],
            },
            make_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_SPEC_MISMATCH, expected_status=422)

    def test_contract_close_with_reserved_shipment_rejected(self, api):
        """PRD (Buyer Contracts and Shipment Planning): "Contracts close from
        OPEN, SUSPENDED, or FULFILLED to CLOSED, but only when reserved_qty_lbs
        is exactly zero — the plant will not close a contract with stock still
        reserved."
        PRD (Validation Order): "State preconditions. The target entity is in a
        valid from-state for the requested transition ... any other invalid
        from-state with ERR_INVALID_STATE (409)."

        Design: Corner/errors/contract_close_with_reserved_shipment_rejected
        """
        scenario = setup_planned_shipment(
            required_qty_lbs=5000, shipment_quantity=500,
        )
        resp = api.close_contract(scenario["contract"]["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        contract_after = validate_success(
            api.get_contract(scenario["contract"]["id"], make_operator_headers())
        )
        assert contract_after["status"] == "OPEN"


class TestBinCapacityProjection:
    def test_available_now_vs_projected_after_planned_shipment(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals):
        "`available_now_lbs` is the current capacity picture: `capacity_lbs`
        minus `occupied_lbs`, what could be placed right now.
        `projected_available_lbs` is the forward-looking picture: it
        additionally subtracts the `allocated_planned_lbs` reserved by planned
        or blocked shipments across those same placements".

        Design: Difficulty/dual_variant_calc/bin_capacity_now_vs_projected
        """
        scenario = setup_planned_shipment(
            required_qty_lbs=10000, shipment_quantity=1000,
            bin_capacity_lbs=5000, placement_quantity=2000,
        )
        bin_after = validate_success(
            api.get_bin(scenario["bin"]["id"], make_operator_headers())
        )
        assert bin_after["occupied_lbs"] == pytest.approx(2000, abs=0.01)
        assert bin_after["available_now_lbs"] == pytest.approx(3000, abs=0.01)
        assert bin_after["projected_available_lbs"] == pytest.approx(2000, abs=0.01)
        assert bin_after["projected_available_lbs"] != bin_after["available_now_lbs"]

    def test_projected_variant_counts_only_planned_or_blocked(self, api):
        """PRD (Storage Bins, Placements, and FIFO Withdrawals):
        "projected_available_lbs ... answering what remains free assuming every
        outstanding shipment actually ships, and is therefore never greater than
        available_now_lbs" and PLANNED shipment creation leaves "remaining_lbs
        stays put" while "allocated_planned_lbs rises by the reserved quantity".

        Design: Difficulty/dual_variant_calc/bin_capacity_now_vs_projected
        """
        scenario = setup_planned_shipment(
            required_qty_lbs=10000, shipment_quantity=1000,
            bin_capacity_lbs=5000, placement_quantity=2000,
        )
        sh = validate_success(
            api.get_shipment(scenario["shipment"]["id"], make_operator_headers())
        )
        assert sh["status"] == "PLANNED"
        p_after = validate_success(
            api.get_placement(scenario["placement"]["id"], make_operator_headers())
        )
        assert p_after["remaining_lbs"] == pytest.approx(2000, abs=0.01)
        assert p_after["allocated_planned_lbs"] == pytest.approx(1000, abs=0.01)
        bin_after = validate_success(
            api.get_bin(scenario["bin"]["id"], make_operator_headers())
        )
        assert bin_after["projected_available_lbs"] == pytest.approx(2000, abs=0.01)


class TestAflatoxinThreeHopCascade:
    def _setup_processed_lot_with_planned_shipment(self, api):
        return setup_planned_shipment(
            required_qty_lbs=10000, shipment_quantity=1000,
            bin_capacity_lbs=5000, placement_quantity=2000,
        )

    def test_aflatoxin_fail_rejects_lot_and_quarantines_placement(self, api):
        """PRD (Field Lot Intake): "A `FAIL` — from any lot in `SAMPLED`,
        `GRADED`, `ROUTED_IN_SHELL`, `ROUTED_KERNEL`, `PROCESSING`, or
        `PROCESSED` — drives the lot to `REJECTED`, copies the sample onto
        `aflatoxin_ppb`, and fires the first cascade of §2.10: every `STORED`
        placement of this lot moves to `QUARANTINED`".

        Design: Difficulty/transitive_cascade/aflatoxin_fail_three_hop_quarantine
        """
        scenario = self._setup_processed_lot_with_planned_shipment(api)
        assert scenario["lot"]["status"] == "PROCESSED"
        record_aflatoxin(scenario["lot"]["id"], aflatoxin_ppb=30.0)

        lot_after = get_lot(scenario["lot"]["id"])
        assert lot_after["status"] == "REJECTED"
        p_after = validate_success(
            api.get_placement(scenario["placement"]["id"], make_operator_headers())
        )
        assert p_after["status"] == "QUARANTINED"

    def test_aflatoxin_fail_blocks_planned_shipment(self, api):
        """PRD (Field Lot Intake): "every PLANNED shipment whose allocations
        reference any of those placements moves to BLOCKED."
        PRD (Plant-Wide Safety Cascades): "When a recorded aflatoxin sample
        fails the action level, the lot is rejected, every stored placement of
        that lot is quarantined, and every planned shipment whose reservations
        touch those placements is blocked."

        Design: Difficulty/transitive_cascade/aflatoxin_fail_three_hop_quarantine
        """
        scenario = self._setup_processed_lot_with_planned_shipment(api)
        record_aflatoxin(scenario["lot"]["id"], aflatoxin_ppb=30.0)

        p_after = validate_success(
            api.get_placement(scenario["placement"]["id"], make_operator_headers())
        )
        assert p_after["status"] == "QUARANTINED"
        sh_after = validate_success(
            api.get_shipment(scenario["shipment"]["id"], make_operator_headers())
        )
        assert sh_after["status"] == "BLOCKED"


class TestOptimisticConcurrency:
    def test_occ_stale_lot_version_on_run_create(self, api):
        """PRD (Optimistic Concurrency on Lots and Contracts): "If the lot's
        current version no longer matches — because another write, such as an
        earlier run creation or a state cascade, has advanced it — the creation
        is rejected with ERR_STALE_LOT_VERSION (HTTP 412)." and "a second
        creation carrying a current version succeeds, since multiple runs per
        lot ... are legitimate."

        Design: Corner/cross_cutting_layers/occ_stale_lot_version_on_run_create
        """
        _, lot = create_routed_lot(gross_weight_lbs=2000)
        observed_version = lot["version"]
        first = validate_success(
            api.create_processing_run(
                {"lot_id": lot["id"], "expected_lot_version": observed_version},
                make_operator_headers(),
            ),
            expected_status=201,
        )
        # Replay with the stale observed version.
        resp = api.create_processing_run(
            {"lot_id": lot["id"], "expected_lot_version": observed_version},
            make_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION, expected_status=412)
        # Fresh read, then a legitimate second run succeeds.
        fresh = get_lot(lot["id"])
        second = validate_success(
            api.create_processing_run(
                {"lot_id": lot["id"], "expected_lot_version": fresh["version"]},
                make_operator_headers(),
            ),
            expected_status=201,
        )
        assert second["id"] != first["id"]

    def test_occ_stale_contract_version_on_shipment_create(self, api):
        """PRD (Optimistic Concurrency on Lots and Contracts): "Creating a
        shipment likewise requires `expected_contract_version`, matched against
        the buyer contract's current `version`; a mismatch is rejected with
        `ERR_STALE_CONTRACT_VERSION` (HTTP 412)." and "Successful creation under
        either rule itself increments the parent's `version` by one (and
        refreshes its `updated_at`)".

        Design: Corner/cross_cutting_layers/occ_stale_contract_version_on_shipment_create
        """
        scenario = setup_bin_with_stored_placement(
            bin_capacity_lbs=5000, placement_quantity=2000,
        )
        buyer = create_buyer()
        contract = create_contract(buyer["id"], required_qty_lbs=10000)
        observed_version = contract["version"]

        first = validate_success(
            api.create_shipment(
                {
                    "contract_id": contract["id"],
                    "bin_id": scenario["bin"]["id"],
                    "quantity_lbs": 100,
                    "expected_contract_version": observed_version,
                },
                make_operator_headers(),
            ),
            expected_status=201,
        )
        contract_after_first = validate_success(
            api.get_contract(contract["id"], make_operator_headers())
        )
        assert contract_after_first["reserved_qty_lbs"] == pytest.approx(100, abs=0.01)
        assert contract_after_first["version"] == observed_version + 1

        # Replay with stale version.
        resp = api.create_shipment(
            {
                "contract_id": contract["id"],
                "bin_id": scenario["bin"]["id"],
                "quantity_lbs": 100,
                "expected_contract_version": observed_version,
            },
            make_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION, expected_status=412)

        # Fresh version succeeds.
        fresh = validate_success(
            api.get_contract(contract["id"], make_operator_headers())
        )
        second = validate_success(
            api.create_shipment(
                {
                    "contract_id": contract["id"],
                    "bin_id": scenario["bin"]["id"],
                    "quantity_lbs": 100,
                    "expected_contract_version": fresh["version"],
                },
                make_operator_headers(),
            ),
            expected_status=201,
        )
        assert second["id"] != first["id"]
        contract_final = validate_success(
            api.get_contract(contract["id"], make_operator_headers())
        )
        assert contract_final["reserved_qty_lbs"] == pytest.approx(200, abs=0.01)
