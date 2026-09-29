"""Every quantity a cascade consumes must be given back exactly by its compensating move.

Two compensations are exercised. De-energizing a circuit unwinds the whole energization
cascade — circuit, cabinet, row posture, the neighbour cabinet's capacity hold and the
contract's provisioning rollups — while leaving the reservation-derived figures alone,
and re-energizing reproduces the original numbers to the last digit. Reversing a
remote-hands invoice line unwinds two ledgers at once: the money and the non-monetary
bundle of included minutes, without ever mutating the immutable original line.
"""

from test_helpers import assertions as ax, factories as f, fixtures as fx
from test_helpers import ApiErrorId, validate_success, validate_error, validate_paginated, get_success_data
from test_helpers import BILLING_OPERATOR, ENGINEER_1, FACILITY_MANAGER


class TestPowerCyclingLeavesNoResidue:
    """A 90 A / 240 V single-phase primary feed (derated 17.280 kW) on an 18 kW cabinet
    in a row engineered at 8 kW per cabinet, so energization drives the row to
    `DENSITY_CAPPED` and puts the neighbour reservation on hold."""

    def _scenery(self, api):
        scenario = fx.setup_installed_cabinet(
            api,
            row={"design_density_kw_per_cabinet": 8.0, "max_row_power_kw": 200.0, "cooling_capacity_kw": 60.0},
            contract={"committed_cabinet_count": 2, "power_commit_kw": 20.0},
            cabinet={"cabinet_code": "C01", "rated_power_kw": 18.0},
        )
        neighbour = fx.add_reserved_cabinet(api, scenario, cabinet_code="C02", rated_power_kw=10.0)
        primary = fx.add_approved_circuit(
            api, scenario, cabinet_id=scenario.cabinets[0]["id"], circuit_code="A-1", breaker_amps=90
        )
        held_circuit = fx.add_designed_circuit(
            api, scenario, cabinet_id=neighbour["id"], circuit_code="A-2", breaker_amps=25
        )
        fx.energize_circuit(api, primary["id"], scenario.row_id)
        return scenario, neighbour, primary, held_circuit

    def _de_energize(self, api, circuit_id):
        return validate_success(
            api.set_circuit_state(circuit_id, f.state_payload("DE_ENERGIZED"), FACILITY_MANAGER)
        )

    def test_de_energization_zeroes_exactly_what_energization_allocated(self, api):
        """PRD §2.8: "Every quantity a cascade consumes is given back by the compensating transition: de-energizing a circuit zeroes exactly the kilowatts the energization allocated, releasing a reservation removes exactly the slot the reservation occupied, aborting a cross-connect order frees exactly the ports it reserved, and a reversal line restores exactly the bundled remote-hands minutes the original line consumed."
        PRD §3.4: "De-energizing an `ENERGIZED` circuit is available to a `ProvisioningEngineer` or a `FacilityManager` and compensates that cascade exactly: `allocated_kw` and `cooling_contribution_kw` return to 0.000; the cabinet's rollups are recomputed and the cabinet steps `ACTIVE` → `INSTALLED` when its primary count fell from one to zero; the row's allocated power, cooling load, stranded views and posture are recomputed, and if the posture returns to `OPEN` every `CAPACITY_HELD` cabinet returns to `RESERVED` with its `BLOCKED` circuits back in `DESIGNED`; the contract's provisioning rollups are refreshed; and circuit, cabinet and row versions increment."

        Design: Difficulty/compensating_invariant/de_energize_then_re_energize_restores_every_rollup_without_drift
        """
        scenario, _neighbour, primary, _held = self._scenery(api)

        de_energized = self._de_energize(api, primary["id"])
        ax.assert_circuit_power(
            de_energized, status="DE_ENERGIZED", allocated_kw=0.000, cooling_contribution_kw=0.000
        )

        ax.assert_cabinet_power(
            fx.read_cabinet(api, scenario.cabinets[0]["id"]),
            status="INSTALLED",
            allocated_power_kw=0.000,
            cooling_load_kw=0.000,
            energized_primary_circuit_count=0,
        )
        ax.assert_row_capacity_view(
            fx.read_row(api, scenario.row_id),
            allocated_power_kw=0.000,
            cooling_load_kw=0.000,
            energized_cabinet_count=0,
            row_status="OPEN",
        )
        ax.assert_contract_power_rollup(
            fx.read_contract(api, scenario.contract_id),
            provisioned_power_kw=0.000,
            stranded_commit_kw=20.000,
            commit_utilization_pct=0.0,
        )

    def test_de_energization_leaves_the_reservation_derived_figures_alone(self, api):
        """PRD §3.2: "`density_ceiling_kw` is the design density multiplied by the number of occupied slots, rounded to three decimals — a row engineered at 8 kW per cabinet with five occupied slots carries a ceiling of 40 kW, and that ceiling grows and shrinks with occupancy rather than with the row's physical slot count."
        PRD §3.3: "When the row's posture returns to `OPEN` — because a circuit was de-energized, because a reservation was released, or because a manager raised the row's limits — every `CAPACITY_HELD` cabinet returns to `RESERVED` and every `BLOCKED` circuit on it returns to `DESIGNED`."

        Design: Difficulty/compensating_invariant/de_energize_then_re_energize_restores_every_rollup_without_drift
        """
        scenario, neighbour, primary, held = self._scenery(api)

        self._de_energize(api, primary["id"])

        ax.assert_row_capacity_view(
            fx.read_row(api, scenario.row_id),
            occupied_slot_count=2,
            density_ceiling_kw=16.000,
            effective_ceiling_kw=16.000,
            stranded_nameplate_kw=16.000,
            stranded_measured_kw=16.000,
        )

        released_cabinet = fx.read_cabinet(api, neighbour["id"])
        assert released_cabinet["status"] == "RESERVED", (
            f"the held neighbour returns to RESERVED once the row re-opens, got {released_cabinet['status']}"
        )
        released_circuit = fx.read_circuit(api, held["id"])
        assert released_circuit["status"] == "DESIGNED", (
            f"the blocked circuit returns to DESIGNED once the row re-opens, got {released_circuit['status']}"
        )

    def test_re_energization_reproduces_the_identical_cascade(self, api):
        """PRD §3.4: "The circuit must be in `APPROVED` or in `DE_ENERGIZED` — a circuit may be cycled between `DE_ENERGIZED` and `ENERGIZED` any number of times as long as its cabinet is not decommissioning — and the identical set of guards applies to both entry paths."
        PRD §3.2: "The **nameplate view**, `stranded_nameplate_kw`, is the effective ceiling minus `allocated_power_kw`, rounded to three decimals: it charges the row for every breaker plate that has been energized, so a lightly loaded cabinet with a large breaker strands nothing at all."
        PRD §3.4: "`commit_utilization_pct` is the provisioned figure divided by `power_commit_kw`, multiplied by 100 and rounded to one decimal place."

        Design: Difficulty/compensating_invariant/de_energize_then_re_energize_restores_every_rollup_without_drift
        """
        scenario, neighbour, primary, held = self._scenery(api)

        self._de_energize(api, primary["id"])
        re_energized = validate_success(
            api.energize_circuit(
                primary["id"],
                {"expected_row_version": fx.row_version(api, scenario.row_id)},
                ENGINEER_1,
            )
        )
        ax.assert_circuit_power(
            re_energized, status="ENERGIZED", allocated_kw=17.280, cooling_contribution_kw=17.280
        )

        ax.assert_cabinet_power(fx.read_cabinet(api, scenario.cabinets[0]["id"]), status="ACTIVE")
        ax.assert_row_capacity_view(
            fx.read_row(api, scenario.row_id),
            allocated_power_kw=17.280,
            cooling_load_kw=17.280,
            row_status="DENSITY_CAPPED",
            stranded_nameplate_kw=-1.280,
        )

        re_held_cabinet = fx.read_cabinet(api, neighbour["id"])
        assert re_held_cabinet["status"] == "CAPACITY_HELD", (
            f"the capped row must hold the neighbour reservation again, got {re_held_cabinet['status']}"
        )
        re_held_circuit = fx.read_circuit(api, held["id"])
        assert re_held_circuit["status"] == "BLOCKED", (
            f"the held cabinet's designed circuit must be BLOCKED again, got {re_held_circuit['status']}"
        )

        ax.assert_contract_power_rollup(
            fx.read_contract(api, scenario.contract_id),
            provisioned_power_kw=17.280,
            stranded_commit_kw=2.720,
            commit_utilization_pct=86.4,
        )


class TestRemoteHandsReversalRestoresMoneyAndMinutes:
    """A `STANDARD` ticket dispatched on the deadline clock and completed with a single
    in-hours twenty-minute segment: two increments, one absorbed by a fifteen-minute
    bundle, 62.50 USD charged."""

    def _completed_ticket(self, api):
        scenario = fx.setup_dispatched_ticket(
            api, contract={"remote_hands_included_minutes": 15}, severity="STANDARD"
        )
        fx.set_clock(api, "2026-08-01T10:00:00Z")
        ticket = fx.complete_ticket(
            api,
            scenario.ticket["id"],
            f.work_segment("2026-08-01T09:00:00Z", "2026-08-01T09:20:00Z"),
        )
        lines = fx.invoice_lines(api, scenario.contract_id, line_type="REMOTE_HANDS")
        assert len(lines) == 1, f"the completion must append exactly one labour line, got {len(lines)}"
        return scenario, ticket, lines[0]

    def test_reversal_appends_a_negative_line_without_mutating_the_original(self, api):
        """PRD §3.9: "A `BillingOperator` names the `invoice_line_id` to compensate and a `reason`, and the server appends a `REVERSAL` line whose `amount_usd` is the exact negative of the original line's amount and marks the original's `reversed` flag true."
        PRD §2.4: "A billing mistake is never edited — it is compensated by a further line, as described in §3.9."
        PRD §3.4: "The same rollup pass also refreshes `active_cross_connect_count`, the count of the contract's cross-connect orders in `ACTIVE`; `billed_total_usd`, the sum of `amount_usd` across every invoice line ever appended to the contract, credits and reversals included, rounded to two decimals; and `cross_connect_billed_usd`, the same sum restricted to lines whose `line_type` is `CROSS_CONNECT_MRC` or `CROSS_CONNECT_SURCHARGE`, likewise rounded to two decimals."

        Design: Difficulty/compensating_invariant/remote_hands_reversal_restores_both_money_and_bundled_minutes
        """
        scenario, ticket, original = self._completed_ticket(api)

        ax.assert_invoice_line_values(
            original,
            line_type="REMOTE_HANDS",
            amount_usd=62.50,
            quantity=1,
            included_minutes_consumed=15,
            source_ref_id=ticket["id"],
            reversed_flag=False,
        )
        ax.assert_contract_billing_rollup(
            fx.read_contract(api, scenario.contract_id), billed_total_usd=62.50
        )

        reversal = validate_success(
            api.create_invoice_adjustment(
                scenario.contract_id,
                f.invoice_adjustment_payload(
                    original["id"], "Work was performed under an existing project credit"
                ),
                BILLING_OPERATOR,
            ),
            201,
        )
        ax.assert_invoice_line(reversal)
        ax.assert_invoice_line_values(
            reversal, line_type="REVERSAL", amount_usd=-62.50, source_ref_id=original["id"]
        )

        re_read = get_success_data(api.get_invoice_line(original["id"], BILLING_OPERATOR))
        ax.assert_invoice_line_values(re_read, amount_usd=62.50, reversed_flag=True)

        ax.assert_contract_billing_rollup(
            fx.read_contract(api, scenario.contract_id), billed_total_usd=0.00
        )

        _lines, meta = validate_paginated(
            api.list_invoice_lines(BILLING_OPERATOR, params={"contract_id": scenario.contract_id})
        )
        assert meta["total_count"] == 2, (
            f"the ledger must hold the original and its reversal only, got {meta['total_count']}"
        )

    def test_reversal_restores_the_bundled_minutes_the_line_consumed(self, api):
        """PRD §3.9: "Reversal is symmetric with the line it compensates, so reversing a `REMOTE_HANDS` line restores the contract's `remote_hands_remaining_minutes` by exactly that line's `included_minutes_consumed`, and the contract's `billed_total_usd` is recomputed across the whole ledger afterwards."
        PRD §3.6: "The contract's `remote_hands_remaining_minutes` is reduced by `included_increments_applied` multiplied by 15."
        PRD §3.6: "When `labor_charge_usd` is greater than zero, an invoice line of `line_type` `REMOTE_HANDS` is appended carrying that amount, a `quantity` equal to `billable_increments` minus `included_increments_applied`, and `included_minutes_consumed` equal to the absorbed increments multiplied by 15."

        Design: Difficulty/compensating_invariant/remote_hands_reversal_restores_both_money_and_bundled_minutes
        """
        scenario, ticket, original = self._completed_ticket(api)

        ax.assert_ticket_labor(
            ticket,
            billable_increments=2,
            billed_minutes=30,
            included_increments_applied=1,
            labor_charge_usd=62.50,
        )
        ax.assert_contract_billing_rollup(
            fx.read_contract(api, scenario.contract_id), remote_hands_remaining_minutes=0
        )

        validate_success(
            api.create_invoice_adjustment(
                scenario.contract_id,
                f.invoice_adjustment_payload(original["id"], "Absorbed minutes were mis-applied"),
                BILLING_OPERATOR,
            ),
            201,
        )

        ax.assert_contract_billing_rollup(
            fx.read_contract(api, scenario.contract_id),
            remote_hands_remaining_minutes=15,
            billed_total_usd=0.00,
        )

        unchanged_ticket = fx.read_ticket(api, ticket["id"])
        ax.assert_ticket_labor(unchanged_ticket, labor_charge_usd=62.50)
        assert unchanged_ticket["execution_state"] == "COMPLETED", (
            "the ledger compensation must not rewrite the ticket, got execution_state "
            f"{unchanged_ticket['execution_state']}"
        )

    def test_neither_a_reversed_line_nor_its_reversal_can_be_compensated_again(self, api):
        """PRD §3.9: "A line that already carries `reversed` true, or that is itself a `REVERSAL`, is refused with `ERR_LINE_ALREADY_REVERSED`: each billed line may be compensated exactly once."
        PRD §2.4: "An `InvoiceLine` is an immutable ledger entry and carries only `id` and `created_at`; it has neither `updated_at` nor `version`."

        Design: Difficulty/compensating_invariant/remote_hands_reversal_restores_both_money_and_bundled_minutes
        """
        scenario, _ticket, original = self._completed_ticket(api)

        reversal = validate_success(
            api.create_invoice_adjustment(
                scenario.contract_id,
                f.invoice_adjustment_payload(original["id"], "Billed against the wrong project"),
                BILLING_OPERATOR,
            ),
            201,
        )
        ax.assert_ledger_common_fields(reversal)

        validate_error(
            api.create_invoice_adjustment(
                scenario.contract_id,
                f.invoice_adjustment_payload(original["id"], "Duplicate adjustment attempt"),
                BILLING_OPERATOR,
            ),
            ApiErrorId.ERR_LINE_ALREADY_REVERSED,
        )
        validate_error(
            api.create_invoice_adjustment(
                scenario.contract_id,
                f.invoice_adjustment_payload(reversal["id"], "Attempt to compensate the compensation"),
                BILLING_OPERATOR,
            ),
            ApiErrorId.ERR_LINE_ALREADY_REVERSED,
        )

        _lines, meta = validate_paginated(
            api.list_invoice_lines(BILLING_OPERATOR, params={"contract_id": scenario.contract_id})
        )
        assert meta["total_count"] == 2, (
            f"the refused attempts must append nothing, got {meta['total_count']} lines"
        )
        ax.assert_contract_billing_rollup(
            fx.read_contract(api, scenario.contract_id),
            billed_total_usd=0.00,
            remote_hands_remaining_minutes=15,
        )
