"""Compensating invariants: unit conservation, reservation symmetry, ledger parity."""
from test_helpers import (
    get_order,
    get_success_data,
    get_unit,
    issue_all,
    list_wastage,
    make_compatible_crossmatch,
    make_issue,
    make_pending_crossmatch,
    make_stock,
    make_typed_patient,
    make_verified_order,
    receive_unit_descriptor,
    release_unit,
    return_issue_payload,
    run_sweep,
    set_clock,
    setup_order_with_reserved_units,
    validate_paginated,
    validate_success,
    SUPERVISOR,
    TECH_A,
    TECH_B,
    QO_1,
    api_client,
)


class TestBucketUnitCountConservation:
    def _setup_issued_pair(self, api):
        ctx = setup_order_with_reserved_units(
            num_units=2, units_requested=2, mrn="M-9050",
            unit_numbers=["U-501", "U-502"], donor_prefix="D-910",
            lot_number="LOT-10")
        issue_all(ctx)
        return ctx

    def _run_both_returns(self, api, ctx):
        set_clock("2026-08-10T09:20:00Z")
        validate_success(api.return_issue(ctx["issues"]["U-501"]["id"],
                                          return_issue_payload(True, False), TECH_A))
        set_clock("2026-08-10T09:31:00Z")
        validate_success(api.return_issue(ctx["issues"]["U-502"]["id"],
                                          return_issue_payload(True, False), TECH_A))

    def test_restock_pair_conserves_bucket_count(self, api):
        """PRD §3.5: "A `RESTOCKED` return moves the unit from `ISSUED` back to
        `AVAILABLE` and recomputes posture"
        PRD §3.3: "a return or stop that drops fulfillment below the requested
        count reverts `PARTIALLY_ISSUED` to `AWAITING_CROSSMATCH`"

        Design: Difficulty/compensating_invariant/bucket_unit_count_conservation
        """
        ctx = self._setup_issued_pair(api)
        self._run_both_returns(api, ctx)
        _data, meta = validate_paginated(api.list_blood_units(
            TECH_A, params={"product_type": "RBC", "abo_type": "O",
                            "rh_type": "NEG"}))
        assert meta["total_count"] == 2, (
            "issue plus return-restock creates and destroys nothing"
        )
        assert get_unit(ctx["units"]["U-501"]["id"])["status"] == "AVAILABLE", (
            "the 20-minute return restocked the first unit"
        )
        assert get_order(ctx["order"]["id"])["status"] == "AWAITING_CROSSMATCH", (
            "both issued slots were lost"
        )

    def test_discard_pair_conserves_bucket_count(self, api):
        """PRD §3.5: "Either discard disposition moves the unit to `DISCARDED` and
        writes a wastage record with reason `RETURNED_OVER_30MIN` or
        `RETURNED_COMPROMISED` as applicable, recomputing posture and the rolling
        wastage rate."

        Design: Difficulty/compensating_invariant/bucket_unit_count_conservation
        """
        ctx = self._setup_issued_pair(api)
        self._run_both_returns(api, ctx)
        assert get_unit(ctx["units"]["U-502"]["id"])["status"] == "DISCARDED", (
            "the 31-minute return discarded the second unit — a state, not a "
            "deletion"
        )
        records = list_wastage({"unit_id": ctx["units"]["U-502"]["id"]})
        assert len(records) == 1
        assert records[0]["reason"] == "RETURNED_OVER_30MIN"
        _data, meta = validate_paginated(api.list_blood_units(
            TECH_A, params={"product_type": "RBC", "abo_type": "O",
                            "rh_type": "NEG"}))
        assert meta["total_count"] == 2, "the discarded unit is still counted"


class TestOrderReservationSymmetry:
    def _setup_ready_pair(self, api):
        ctx = setup_order_with_reserved_units(
            num_units=2, units_requested=2, mrn="M-9051",
            unit_numbers=["U-511", "U-512"], donor_prefix="D-920",
            lot_number="LOT-11")
        assert get_order(ctx["order"]["id"])["units_crossmatched"] == 2
        return ctx

    def test_cancel_decrements_crossmatched_and_reverts_order(self, api):
        """PRD §3.4: "From `COMPATIBLE`, the reserved unit returns from `RESERVED`
        to `AVAILABLE` — except when the same cascade is moving that unit into
        `QUARANTINED_HOLD`, in which case the hold wins and no release occurs —
        while the order's `units_crossmatched` decrements by one; if fulfillment
        falls below `units_requested`, a `READY` order reverts to
        `AWAITING_CROSSMATCH`"

        Design: Difficulty/compensating_invariant/order_reservation_symmetry
        """
        ctx = self._setup_ready_pair(api)
        validate_success(api.cancel_crossmatch(
            ctx["crossmatches"]["U-511"]["id"], TECH_A))

        order = get_order(ctx["order"]["id"])
        assert order["units_crossmatched"] == 1
        assert order["status"] == "AWAITING_CROSSMATCH"
        assert get_unit(ctx["units"]["U-511"]["id"])["status"] == "AVAILABLE"
        assert get_unit(ctx["units"]["U-512"]["id"])["status"] == "RESERVED"

    def test_cancel_then_recrossmatch_restores_symmetry(self, api):
        """PRD §3.4: "On success the unit moves from `AVAILABLE` to `RESERVED`
        (decrementing the bucket's usable count and recomputing posture),
        `resulted_at` and `resulted_by_user_id` are stamped, and the reservation
        window is set"
        PRD §3.4: "The order's `units_crossmatched` increments by one, and if
        fulfillment thereby reaches `units_requested` the order advances from
        `AWAITING_CROSSMATCH` to `READY`."

        Design: Difficulty/compensating_invariant/order_reservation_symmetry
        """
        ctx = self._setup_ready_pair(api)
        validate_success(api.cancel_crossmatch(
            ctx["crossmatches"]["U-511"]["id"], TECH_A))
        xm3 = make_compatible_crossmatch(ctx["order"]["id"],
                                         ctx["units"]["U-511"]["id"])

        order = get_order(ctx["order"]["id"])
        assert order["units_crossmatched"] == 2, "symmetry restored with no drift"
        assert order["status"] == "READY"
        assert get_unit(ctx["units"]["U-511"]["id"])["status"] == "RESERVED"
        assert get_unit(ctx["units"]["U-512"]["id"])["status"] == "RESERVED"
        assert get_success_data(api.get_crossmatch(
            ctx["crossmatches"]["U-511"]["id"], TECH_A))["status"] == "CANCELLED"
        assert xm3["status"] == "COMPATIBLE"


class TestWastageLedgerParity:
    def _setup_three_waste_paths(self, api):
        """U-521: manual discard. U-522: sweep expiry. U-523: 30-minute discard."""
        stock = make_stock([
            receive_unit_descriptor("U-521", donor_id="D-930", lot_number="LOT-12"),
            receive_unit_descriptor("U-522", product_type="PLT_APHERESIS",
                                    volume_ml=200,
                                    collected_at="2026-08-06T00:00:00Z",
                                    donor_id="D-931", lot_number="LOT-12"),
            receive_unit_descriptor("U-523", donor_id="D-932", lot_number="LOT-12"),
        ], release=False)
        release_unit(stock["units"]["U-521"]["id"])
        release_unit(stock["units"]["U-523"]["id"])
        get_success_data(api_client.discard_unit(stock["units"]["U-521"]["id"],
                                                 {"note": "damaged in handling"},
                                                 SUPERVISOR))
        patient, _ts = make_typed_patient(mrn="M-9052", full_name="Pat Fiftytwo",
                                          date_of_birth="1995-09-09")
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        make_compatible_crossmatch(order["id"], stock["units"]["U-523"]["id"])
        issue = make_issue(order["id"], stock["units"]["U-523"]["id"])
        stock["issue"] = issue
        return stock

    def _run_trigger(self, api, stock):
        set_clock("2026-08-11T00:00:00Z")  # U-522 (PLT, +120h) reaches its expiry
        run_sweep()
        validate_success(api.return_issue(stock["issue"]["id"],
                                          return_issue_payload(True, False), TECH_A))

    def test_three_waste_paths_write_three_records(self, api):
        """PRD §3.2: "the unit settles in `DISCARDED` and a wastage record with
        reason `MANUAL` is written"
        PRD §2.4: "expires every blood unit whose `expires_at` has been reached —
        units in `ISSUED` status are exempt, because the four-hour start window and
        the thirty-minute return rule govern them instead — creating an `EXPIRED`
        wastage record for each"

        Design: Difficulty/compensating_invariant/wastage_ledger_parity
        """
        stock = self._setup_three_waste_paths(api)
        self._run_trigger(api, stock)
        records = list_wastage()
        assert len(records) == 3
        by_unit = {r["unit_id"]: r["reason"] for r in records}
        assert by_unit[stock["units"]["U-521"]["id"]] == "MANUAL"
        assert by_unit[stock["units"]["U-522"]["id"]] == "EXPIRED"
        assert by_unit[stock["units"]["U-523"]["id"]] == "RETURNED_OVER_30MIN"

    def test_waste_state_units_match_records_one_to_one(self, api):
        """PRD §3.8: "a `quantity_units` that is always 1 in this benchmark (one
        record per wasted unit)"
        PRD §3.5: "Either discard disposition moves the unit to `DISCARDED` and
        writes a wastage record with reason `RETURNED_OVER_30MIN` or
        `RETURNED_COMPROMISED` as applicable"

        Design: Difficulty/compensating_invariant/wastage_ledger_parity
        """
        stock = self._setup_three_waste_paths(api)
        self._run_trigger(api, stock)
        _data, discarded = validate_paginated(
            api.list_blood_units(TECH_A, params={"status": "DISCARDED"}))
        _data, expired = validate_paginated(
            api.list_blood_units(TECH_A, params={"status": "EXPIRED"}))
        assert discarded["total_count"] == 2
        assert expired["total_count"] == 1
        records = list_wastage()
        assert len(records) == 3, (
            "waste-state units (3) and wastage records (3) are in exact 1:1 parity"
        )
        for record in records:
            assert record["quantity_units"] == 1
