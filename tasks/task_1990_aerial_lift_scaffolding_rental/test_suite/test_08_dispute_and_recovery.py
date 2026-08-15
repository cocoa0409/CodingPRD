"""Claim disputes, the dispute cycle, waived-terminal lockdown, and the
loss/recovery fleet conservation flow."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_customer, create_equipment_class, create_equipment_unit,
    create_contract, add_line, activate_contract, set_clock, deliver_line,
    setup_charged_damage_claim,
    create_claim, assess_claim, charge_claim, dispute_claim, resolve_claim,
    get_contract, get_claim, get_unit, count_units,
    make_customer_headers,
    assert_damage_claim,
)


class TestClaimDisputeCycle:
    def test_charge_dispute_uphold_dispute_waive_cycle(self, api):
        """PRD §3.8: "Upholding returns the claim from `DISPUTED` to `CHARGED`
        and re-stamps `resolved_by` — no monetary change occurs, because the
        chargeback was already applied at charge time — and the `CHARGED` →
        `DISPUTED` → `CHARGED` cycle may repeat. Waiving moves the claim from
        `DISPUTED` to `WAIVED`, the compensating action of the charge: the
        chargeback is removed from the contract's `damage_subtotal_cents`,
        which is recomputed with the contract's `version` incrementing, the
        customer's balance is recomputed with a possible suspension cascade,
        and the claim's `version` increments. `WAIVED` is terminal."

        Design: Difficulty/non_linear_state_machine/claim_charge_dispute_cycle
        """
        ctx = setup_charged_damage_claim(repair_estimate_cents=50_000)
        claim_id = ctx["claim"]["id"]
        contract_id = ctx["contract"]["id"]
        assert get_contract(contract_id)["damage_subtotal_cents"] == 50000

        disputed = dispute_claim(claim_id, ctx["customer"]["id"])
        assert disputed["status"] == "DISPUTED"

        upheld = resolve_claim(claim_id, "UPHOLD")
        assert upheld["status"] == "CHARGED", "cycle CHARGED -> DISPUTED -> CHARGED"

        disputed2 = dispute_claim(claim_id, ctx["customer"]["id"])
        assert disputed2["status"] == "DISPUTED", "cycle repeats"

        waived = resolve_claim(claim_id, "WAIVE")
        assert_damage_claim(waived)
        assert waived["status"] == "WAIVED", "terminal"
        assert get_contract(contract_id)["damage_subtotal_cents"] == 0

    def test_uphold_resolve_makes_no_monetary_change(self, api):
        """PRD §3.8: "Upholding returns the claim from `DISPUTED` to `CHARGED`
        and re-stamps `resolved_by` — no monetary change occurs, because the
        chargeback was already applied at charge time".

        Design: Difficulty/non_linear_state_machine/claim_charge_dispute_cycle
        """
        ctx = setup_charged_damage_claim(repair_estimate_cents=50_000)
        claim_id = ctx["claim"]["id"]
        contract_id = ctx["contract"]["id"]

        dispute_claim(claim_id, ctx["customer"]["id"])
        upheld = resolve_claim(claim_id, "UPHOLD")
        assert upheld["status"] == "CHARGED"
        assert upheld["chargeback_cents"] == 50000
        assert get_contract(contract_id)["damage_subtotal_cents"] == 50000, (
            "upholding leaves the money exactly where the charge put it")

    def test_waived_claim_terminal_lockdown_rejected(self, api):
        """PRD §3.8: "`WAIVED` is terminal." PRD §3.8: "the `Customer` owning
        the contract disputes a `CHARGED` claim (`ERR_INVALID_STATE` if it is
        not `CHARGED`; `ERR_FORBIDDEN` if the caller is not the contract's
        customer), moving it to `DISPUTED` with its `version` incrementing."

        Design: Corner/state_machines/claim_waived_terminal_lockdown_rejected
        """
        ctx = setup_charged_damage_claim(repair_estimate_cents=50_000)
        claim_id = ctx["claim"]["id"]
        dispute_claim(claim_id, ctx["customer"]["id"])
        resolve_claim(claim_id, "WAIVE")
        assert get_claim(claim_id)["status"] == "WAIVED"

        res = api.dispute_damage_claim(
            claim_id, make_customer_headers(ctx["customer"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestFleetCountConservation:
    def _lost_unit_scenario(self):
        """Two units of one class; contract ACTIVE (no waiver); line on the
        first unit delivered 2026-08-10T09:00:00Z; LOST claim charged.
        Returns (customer, cls, unit1, unit2, contract, line, assessed claim,
        charged claim)."""
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Fleet Count Co", "ops@fleet.example")
        cls = create_equipment_class(class_code="S19Z",
                                     replacement_value_cents=2_500_000)
        uz1 = create_equipment_unit(cls["id"], "S19Z-001")
        uz2 = create_equipment_unit(cls["id"], "S19Z-002")
        contract = create_contract(customer["id"], "77 Fleet St")
        line = add_line(contract["id"], uz1["id"], "2026-08-10",
                        "2026-08-20", 20)
        activate_contract(contract["id"])
        deliver_line(contract["id"], line["id"], "drv-1",
                     "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z",
                     deliver_at="2026-08-10T09:00:00Z")
        claim = create_claim(line["id"], "LOST",
                             "unit stolen from jobsite overnight",
                             reporter_customer_id=customer["id"])
        assessed = assess_claim(claim["id"])
        charged = charge_claim(claim["id"])
        return customer, cls, uz1, uz2, contract, line, assessed, charged

    def test_dispatch_loss_recovery_credit_flow(self, api,
                                                branch_manager_headers):
        """PRD §3.8: "For `LOST` and `STOLEN` claims no estimate is needed:
        the system sets `repair_estimate_cents` itself to the class's full
        `replacement_value_cents`." and "for `LOST` and `STOLEN` claims the
        waiver never applies and the chargeback is always the class's full
        `replacement_value_cents`" and "Every claim on that unit with
        `claim_type` `LOST` or `STOLEN`, still in `CHARGED` status, and with
        `recovery_credit_cents` still null receives a recovery credit equal to
        eighty percent of its `chargeback_cents`, rounded half-up to whole
        cents per claim."

        Design: Difficulty/compensating_invariant/fleet_count_conserved_through_dispatch_loss_recovery
        """
        (customer, cls, uz1, _uz2, contract, _line,
         assessed, charged) = self._lost_unit_scenario()

        assert assessed["repair_estimate_cents"] == 2_500_000, (
            "assess auto-sets the class replacement value for LOST")
        assert charged["chargeback_cents"] == 2_500_000, (
            "the waiver never applies to LOST")
        assert get_unit(uz1["id"])["status"] == "LOST", (
            "charging a LOST claim marks the unit lost")

        recovered = validate_success(
            api.recover_equipment_unit(uz1["id"], branch_manager_headers))
        assert recovered["status"] == "AVAILABLE", (
            "clock date 2026-08-10 is on or before next_inspection_due_date")

        credited = get_claim(charged["id"])
        assert credited["recovery_credit_cents"] == 2_000_000, (
            "round_half_up(0.80 * 2500000)")
        assert get_contract(contract["id"])["damage_subtotal_cents"] == 500000, (
            "chargeback minus recovery credit")

    def test_fleet_status_counts_conserved(self, api, branch_manager_headers):
        """PRD §3.2: "A unit's `status` cycles through `AVAILABLE`, `ON_RENT`,
        `QUARANTINED`, and `LOST` as trips complete, inspections certify,
        claims charge, and recoveries occur" — status mutates; the class's
        registered unit cardinality does not.

        Design: Difficulty/compensating_invariant/fleet_count_conserved_through_dispatch_loss_recovery
        """
        (customer, cls, uz1, uz2, contract, line,
         assessed, charged) = self._lost_unit_scenario()
        # After charge: the dispatched unit is LOST, the spare is AVAILABLE.
        assert count_units(cls["id"], "LOST") == 1
        assert count_units(cls["id"], "AVAILABLE") == 1
        assert count_units(cls["id"], "ON_RENT") == 0

        validate_success(api.recover_equipment_unit(
            uz1["id"], branch_manager_headers))
        assert count_units(cls["id"], "AVAILABLE") == 2
        assert count_units(cls["id"], "LOST") == 0
