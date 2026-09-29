"""Formulas whose result depends on several independent selectors at once.

Three families live here. A circuit's power figures are produced by one formula that
branches on the cabinet nameplate clamp and on the redundancy role, so the same
breaker plate yields three different numbers. A period close prices cross-connects
through six pinned steps whose volume tier is keyed on the post-allowance subtotal.
And remote-hands labour chains three rounding decisions — per-segment ceiling, then
the bundled-minute waterfall, then per-segment money rounding.
"""

from datetime import datetime

from test_helpers import assertions as ax, constants as k, factories as f, fixtures as fx
from test_helpers import BILLING_OPERATOR, validate_success

PERIOD_START = "2026-07-01T00:00:00Z"
PERIOD_END = "2026-08-01T00:00:00Z"


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into an aware datetime for instant comparison."""
    assert value, f"expected an ISO 8601 UTC timestamp, got {value!r}"
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _contract_lines(api, contract_id):
    """Every invoice line standing against one contract."""
    lines = fx.invoice_lines(api, contract_id)
    return [line for line in lines if line.get("contract_id") == contract_id]


class TestCircuitAllocationVersusCoolingContribution:
    """One 17.280 kW breaker plate, three different derived numbers."""

    ROW = {
        "hall_code": "H3",
        "row_code": "R1",
        "cabinet_slot_count": 8,
        "design_density_kw_per_cabinet": 20.0,
        "max_row_power_kw": 200.0,
        "cooling_capacity_kw": 60.0,
        "escort_slot_count": 1,
        "decommission_flag": False,
    }
    CONTRACT = {
        "billing_mode": "METERED_PLUS_COMMIT",
        "committed_cabinet_count": 2,
        "power_commit_kw": 20.0,
        "redundancy_requirement": "N",
        "cross_connect_cap": 4,
    }
    CABINET = {"cabinet_code": "C01", "rated_power_kw": 15.0}

    def _both_feeds_energized(self, api):
        """A 15.0 kW cabinet carrying an energized 90 A primary feed on busway A and an
        energized 90 A redundant feed on busway B, each derating to 17.280 kW."""
        scenario = fx.setup_installed_cabinet(
            api, row=self.ROW, contract=self.CONTRACT, cabinet=self.CABINET
        )
        primary = fx.add_approved_circuit(
            api,
            scenario,
            circuit_code="A-1",
            feed_side="A",
            redundancy_role="PRIMARY",
            breaker_amps=90,
            volts=240,
            phase="SINGLE",
        )
        redundant = fx.add_approved_circuit(
            api,
            scenario,
            circuit_code="B-1",
            feed_side="B",
            redundancy_role="REDUNDANT",
            breaker_amps=90,
            volts=240,
            phase="SINGLE",
        )
        fx.energize_circuit(api, primary["id"], scenario.row_id)
        fx.energize_circuit(api, redundant["id"], scenario.row_id)
        return scenario, primary["id"], redundant["id"]

    def test_primary_allocation_is_clamped_by_the_nameplate_but_its_heat_is_not(self, api):
        """PRD §3.4: "`derated_kw` is the breaker amperage multiplied by the voltage, multiplied by the phase factor — 1.0 for a `SINGLE`-phase supply and 1.732 for a `THREE`-phase supply — divided by 1000 to convert volt-amperes to kilowatts, then multiplied by the 0.80 continuous-load derate that electrical code requires, and finally rounded half-up to three decimal places."
        PRD §3.4: "For a `PRIMARY` circuit, `allocated_kw` is the lesser of its derated capacity and the host cabinet's `rated_power_kw` — the cabinet nameplate clamps what the floor will bill for, and the clamp is applied to the already-rounded derated figure — while `cooling_contribution_kw` is the full derated capacity, because heat is not clamped by a nameplate."

        Design: Difficulty/combinatorial_formula/circuit_allocation_clamped_while_cooling_load_is_not
        """
        _, primary_id, _ = self._both_feeds_energized(api)

        circuit = fx.read_circuit(api, primary_id)
        ax.assert_circuit_power(
            circuit,
            status="ENERGIZED",
            derated_kw=17.280,
            allocated_kw=15.000,
            cooling_contribution_kw=17.280,
        )

    def test_redundant_feed_allocates_no_power_but_a_quarter_of_its_heat(self, api):
        """PRD §3.4: "For a `REDUNDANT` circuit, `allocated_kw` is 0.000, since a standby feed allocates no billable power, while `cooling_contribution_kw` is one quarter of its derated capacity, rounded to three decimals, reflecting the idle draw of a live standby feed."

        Design: Difficulty/combinatorial_formula/circuit_allocation_clamped_while_cooling_load_is_not
        """
        _, _, redundant_id = self._both_feeds_energized(api)

        circuit = fx.read_circuit(api, redundant_id)
        ax.assert_circuit_power(
            circuit,
            status="ENERGIZED",
            derated_kw=17.280,
            allocated_kw=0.000,
            cooling_contribution_kw=4.320,
        )

    def test_cabinet_rollup_reports_clamped_power_against_unclamped_heat(self, api):
        """PRD §3.3: "Alongside `allocated_power_kw` and `cooling_load_kw`, which sum `allocated_kw` and `cooling_contribution_kw` over the cabinet's energized circuits to three decimals, `energized_primary_circuit_count` is the cabinet's third derived field and counts its circuits that are both `ENERGIZED` and `PRIMARY`."
        PRD §3.3: "When the first `PRIMARY` circuit on an `INSTALLED` cabinet reaches `ENERGIZED` — that is, when `energized_primary_circuit_count` moves from zero to one — the cabinet advances `INSTALLED` → `ACTIVE`, the row's `energized_cabinet_count` rises by one and the row's `allocated_power_kw`, `cooling_load_kw`, stranded views and posture are recomputed."

        Design: Difficulty/combinatorial_formula/circuit_allocation_clamped_while_cooling_load_is_not
        """
        scenario, _, _ = self._both_feeds_energized(api)

        cabinet = fx.read_cabinet(api, scenario.cabinet_id)
        ax.assert_cabinet_power(
            cabinet,
            status="ACTIVE",
            allocated_power_kw=15.000,
            cooling_load_kw=21.600,
            energized_primary_circuit_count=1,
        )

    def test_row_rollup_sums_allocation_and_cooling_over_the_same_energized_set(self, api):
        """PRD §3.2: "`allocated_power_kw` is the sum of `allocated_kw` over the energized circuits of the row's cabinets, rounded to three decimals, and `cooling_load_kw` is the sum of `cooling_contribution_kw` over the same set, likewise rounded to three decimals."

        Design: Difficulty/combinatorial_formula/circuit_allocation_clamped_while_cooling_load_is_not
        """
        scenario, _, _ = self._both_feeds_energized(api)

        row = fx.read_row(api, scenario.row_id)
        ax.assert_row_capacity_view(row, allocated_power_kw=15.000, cooling_load_kw=21.600)

    def test_contract_provisioning_rollup_counts_only_clamped_primary_allocation(self, api):
        """PRD §3.4: "`provisioned_power_kw` is the sum of `allocated_kw` over circuits that are both `ENERGIZED` and `PRIMARY` on cabinets whose `contract_id` is this contract, rounded to three decimals."
        PRD §3.4: "`stranded_commit_kw` is the contracted commitment minus that provisioned figure, floored at zero so an over-provisioned contract reports 0.000 rather than a negative number, rounded to three decimals."
        PRD §3.4: "`commit_utilization_pct` is the provisioned figure divided by `power_commit_kw`, multiplied by 100 and rounded to one decimal place."

        Design: Difficulty/combinatorial_formula/circuit_allocation_clamped_while_cooling_load_is_not
        """
        scenario, _, _ = self._both_feeds_energized(api)

        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract_power_rollup(
            contract,
            provisioned_power_kw=15.000,
            stranded_commit_kw=5.000,
            commit_utilization_pct=75.0,
        )


class TestCrossConnectPeriodBilling:
    """The six pinned steps that turn `ACTIVE` cross-connects into two ledger lines."""

    CONTRACT = {
        "billing_mode": "COMMITTED_ONLY",
        "committed_cabinet_count": 2,
        "power_commit_kw": 20.0,
        "cross_connect_allowance": 1,
        "cross_connect_cap": 6,
    }

    def _three_active_smf_cross_connects(self, api):
        """One contract carrying three `ACTIVE` SMF cross-connects, each pinned at
        300.00 USD, raised in creation order across three free port pairs."""
        scenario = fx.setup_active_cross_connect(
            api, contract=self.CONTRACT, port_pairs=3, media_type="SMF"
        )
        a_ports = fx.a_ports(scenario)
        z_ports = fx.z_ports(scenario)
        for index in (1, 2):
            fx.add_active_cross_connect(
                api, scenario, a_port=a_ports[index], z_port=z_ports[index], media_type="SMF"
            )
        return scenario

    def test_monthly_rate_is_pinned_from_the_cable_type_at_creation(self, api):
        """PRD §3.5: "A created order opens in `SUBMITTED` with `revision_count` at 0, no route pinned, and `mrc_usd` fixed from the media it will use: 300.00 USD for `SMF`, 250.00 USD for `MMF`, 175.00 USD for `CAT6A`, 225.00 USD for `COAX`."
        PRD §3.5: "Bringing the circuit into service, `INSTALLED` → `ACTIVE`, is a `FacilityManager` action that requires the contract to be `ACTIVE`, stamps `activated_at` from the logical clock, raises the contract's `active_cross_connect_count` by one, and increments both the order's and the contract's `version`."

        Design: Difficulty/combinatorial_formula/cross_connect_close_pinned_six_step_order
        """
        scenario = self._three_active_smf_cross_connects(api)

        for order in scenario.orders:
            live = fx.read_order(api, order["id"])
            assert live["status"] == "ACTIVE", (
                f"order {order['id']} should be ACTIVE before the close, got {live['status']}"
            )
            ax.assert_amount_equals(live["mrc_usd"], 300.00, "order.mrc_usd")

        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract_billing_rollup(contract, active_cross_connect_count=3)

    def test_allowance_waives_the_cheapest_candidate_and_the_tier_reads_the_remainder(self, api):
        """PRD §3.9: "Second, the first `cross_connect_allowance` candidates in that ranking are waived — they bill 0.00 and do not appear in any line's quantity — which means the allowance always consumes the cheapest cross-connects first and leaves the expensive ones billable."
        PRD §3.9: "Fourth, the volume tier is keyed on that post-allowance subtotal and nothing else: a subtotal of 800.00 USD or more earns a 10 percent discount, a subtotal of at least 500.00 USD but below 800.00 USD earns 5 percent, and anything below 500.00 USD earns none."
        PRD §3.9: "Third, the subtotal is the sum of `mrc_usd` over the remaining candidates, rounded to two decimals."
        PRD §3.9: "Fifth, the discounted subtotal is the subtotal multiplied by one minus the discount fraction, rounded to two decimals."
        PRD §3.9: "Two lines are appended, in this order and only when the discounted subtotal is greater than zero: a `CROSS_CONNECT_MRC` line whose `amount_usd` is the discounted subtotal, and a `CROSS_CONNECT_SURCHARGE` line whose `amount_usd` is the surcharge, each carrying a `quantity` equal to the number of billed candidates — the waived ones excluded."

        Design: Difficulty/combinatorial_formula/cross_connect_close_pinned_six_step_order
        """
        scenario = self._three_active_smf_cross_connects(api)

        validate_success(
            api.close_billing_period(
                scenario.contract_id,
                f.billing_close_payload(PERIOD_START, PERIOD_END),
                BILLING_OPERATOR,
            )
        )

        lines = _contract_lines(api, scenario.contract_id)
        ax.assert_invoice_line_values(
            ax.one_line(lines, "CROSS_CONNECT_MRC"),
            line_type="CROSS_CONNECT_MRC",
            amount_usd=570.00,
            quantity=2,
        )

    def test_surcharge_is_twenty_percent_of_the_discounted_subtotal(self, api):
        """PRD §3.9: "Sixth, the infrastructure surcharge is 20 percent of that discounted subtotal, rounded to two decimals, and the period total is the discounted subtotal plus the surcharge, rounded to two decimals."
        PRD §3.9: "The surcharge is keyed on the discounted figure, never on the pre-discount subtotal."
        PRD §3.9: "Two lines are appended, in this order and only when the discounted subtotal is greater than zero: a `CROSS_CONNECT_MRC` line whose `amount_usd` is the discounted subtotal, and a `CROSS_CONNECT_SURCHARGE` line whose `amount_usd` is the surcharge, each carrying a `quantity` equal to the number of billed candidates — the waived ones excluded."

        Design: Difficulty/combinatorial_formula/cross_connect_close_pinned_six_step_order
        """
        scenario = self._three_active_smf_cross_connects(api)

        validate_success(
            api.close_billing_period(
                scenario.contract_id,
                f.billing_close_payload(PERIOD_START, PERIOD_END),
                BILLING_OPERATOR,
            )
        )

        lines = _contract_lines(api, scenario.contract_id)
        ax.assert_invoice_line_values(
            ax.one_line(lines, "CROSS_CONNECT_SURCHARGE"),
            line_type="CROSS_CONNECT_SURCHARGE",
            amount_usd=114.00,
            quantity=2,
        )

    def test_close_appends_power_then_cross_connect_lines_and_nothing_else(self, api):
        """PRD §3.9: "First, the candidates are the contract's cross-connect orders whose status is `ACTIVE` at close time, ranked by `mrc_usd` ascending with ties broken by `created_at` ascending; orders in `SUBMITTED`, `ROUTE_PROPOSED`, `CHANGES_REQUESTED`, `APPROVED`, `INSTALLED`, `DECOMMISSIONED` or `ABORTED` are excluded entirely."
        PRD §3.9: "Power billing begins with the committed charge, which is `power_commit_kw` multiplied by the standing rate of 175.00 USD per contracted kilowatt per month, rounded to two decimals."
        PRD §3.9: "Two lines may result, in this order: a `POWER_COMMIT` line whose `amount_usd` is the committed charge and whose `quantity` is `power_commit_kw`, always; and a `POWER_OVERAGE` line whose `amount_usd` is the overage charge and whose `quantity` is the overage energy, appended only when the overage energy is greater than zero."
        PRD §3.9: "Under `COMMITTED_ONLY`, the meter intervals are ignored altogether and consumption is deemed: the sum of `allocated_kw` over circuits that are both `ENERGIZED` and `PRIMARY` on the contract's cabinets at close time, multiplied by the same 730 hours, then multiplied by a deemed load factor of 0.65, rounded to three decimals."
        PRD §3.9: "Two lines are appended, in this order and only when the discounted subtotal is greater than zero: a `CROSS_CONNECT_MRC` line whose `amount_usd` is the discounted subtotal, and a `CROSS_CONNECT_SURCHARGE` line whose `amount_usd` is the surcharge, each carrying a `quantity` equal to the number of billed candidates — the waived ones excluded."

        Design: Difficulty/combinatorial_formula/cross_connect_close_pinned_six_step_order
        """
        scenario = self._three_active_smf_cross_connects(api)

        validate_success(
            api.close_billing_period(
                scenario.contract_id,
                f.billing_close_payload(PERIOD_START, PERIOD_END),
                BILLING_OPERATOR,
            )
        )

        lines = _contract_lines(api, scenario.contract_id)
        assert len(lines) == 3, (
            f"Expected POWER_COMMIT, CROSS_CONNECT_MRC and CROSS_CONNECT_SURCHARGE only, got "
            f"{[line['line_type'] for line in lines]}"
        )
        ax.assert_invoice_line_values(
            ax.one_line(lines, "POWER_COMMIT"),
            line_type="POWER_COMMIT",
            amount_usd=3500.00,
            quantity=20.0,
        )
        assert not ax.find_lines(lines, "POWER_OVERAGE"), (
            "no circuit is energized, so deemed consumption is zero and no POWER_OVERAGE "
            "line may be appended"
        )

    def test_close_refreshes_the_cross_connect_and_total_billing_rollups(self, api):
        """PRD §3.4: "The same rollup pass also refreshes `active_cross_connect_count`, the count of the contract's cross-connect orders in `ACTIVE`; `billed_total_usd`, the sum of `amount_usd` across every invoice line ever appended to the contract, credits and reversals included, rounded to two decimals; and `cross_connect_billed_usd`, the same sum restricted to lines whose `line_type` is `CROSS_CONNECT_MRC` or `CROSS_CONNECT_SURCHARGE`, likewise rounded to two decimals."
        PRD §3.9: "When the close completes, `last_closed_period_end` is set to the supplied `period_end` and `billed_total_usd` and `cross_connect_billed_usd` are refreshed."

        Design: Difficulty/combinatorial_formula/cross_connect_close_pinned_six_step_order
        """
        scenario = self._three_active_smf_cross_connects(api)

        validate_success(
            api.close_billing_period(
                scenario.contract_id,
                f.billing_close_payload(PERIOD_START, PERIOD_END),
                BILLING_OPERATOR,
            )
        )

        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract_billing_rollup(
            contract,
            cross_connect_billed_usd=684.00,
            billed_total_usd=4184.00,
            active_cross_connect_count=3,
        )
        assert _instant(contract["last_closed_period_end"]) == _instant(PERIOD_END), (
            f"contract.last_closed_period_end: expected the supplied {PERIOD_END}, "
            f"got {contract['last_closed_period_end']}"
        )


class TestRemoteHandsIncrementBilling:
    """Per-segment ceiling, then the bundle waterfall, then per-segment money rounding."""

    CONTRACT = {
        "billing_mode": "COMMITTED_ONLY",
        "committed_cabinet_count": 1,
        "power_commit_kw": 20.0,
        "remote_hands_included_minutes": 15,
    }
    SEGMENTS = (
        ("2026-08-01T08:00:00Z", "2026-08-01T08:07:00Z"),
        ("2026-08-01T22:00:00Z", "2026-08-01T22:10:00Z"),
        ("2026-08-01T23:00:00Z", "2026-08-01T23:12:00Z"),
    )

    def _dispatched_standard_ticket(self, api):
        """A `STANDARD` ticket authorized and dispatched at the default clock instant,
        with the clock then advanced a day so the work can be recorded."""
        scenario = fx.setup_dispatched_ticket(
            api,
            contract=self.CONTRACT,
            cabinet={"cabinet_code": "C01", "rated_power_kw": 20.0},
            severity="STANDARD",
            description="Reseat two SFPs and relabel patch leads",
        )
        fx.set_clock(api, "2026-08-02T00:00:00Z")
        return scenario

    def _complete(self, api, ticket_id):
        return fx.complete_ticket(
            api, ticket_id, *[f.work_segment(start, end) for start, end in self.SEGMENTS]
        )

    def test_standard_severity_deadline_is_met_by_a_same_instant_dispatch(self, api):
        """PRD §3.6: "`response_deadline_at` is `authorized_at` advanced by 30 minutes for a `CRITICAL` ticket, by 120 minutes for a `HIGH` ticket, and by 480 minutes — eight hours — for a `STANDARD` ticket."
        PRD §3.6: "On success `dispatched_at` is stamped from the logical clock and `sla_breached` is set true only when `dispatched_at` is strictly later than `response_deadline_at`; a dispatch landing exactly on the deadline instant has met the commitment, not breached it."

        Design: Difficulty/combinatorial_formula/remote_hands_per_segment_ceiling_then_per_segment_rounding
        """
        scenario = self._dispatched_standard_ticket(api)

        ticket = fx.read_ticket(api, scenario.ticket["id"])
        assert _instant(ticket["response_deadline_at"]) == _instant("2026-08-01T08:00:00Z"), (
            f"ticket.response_deadline_at: expected 2026-08-01T08:00:00Z for a STANDARD ticket "
            f"authorized at {k.DEFAULT_CLOCK}, got {ticket['response_deadline_at']}"
        )
        ax.assert_ticket_labor(ticket, sla_breached=False)

    def test_increments_are_ceilinged_per_segment_not_over_the_summed_minutes(self, api):
        """PRD §3.6: "For each segment, the raw duration is the whole minutes between its `started_at` and its `ended_at`, discarding any remaining seconds; a segment of zero whole minutes contributes zero increments, and any other segment contributes its raw minutes divided by 15 and rounded **up** to the next whole increment."
        PRD §3.6: "Those per-segment increments are then summed into `billable_increments`; summing raw minutes across segments first and taking a single ceiling is expressly not the rule, so two seven-minute segments bill two increments rather than one."
        PRD §3.6: "`billed_minutes` is `billable_increments` multiplied by 15."

        Design: Difficulty/combinatorial_formula/remote_hands_per_segment_ceiling_then_per_segment_rounding
        """
        scenario = self._dispatched_standard_ticket(api)

        self._complete(api, scenario.ticket["id"])

        ticket = fx.read_ticket(api, scenario.ticket["id"])
        ax.assert_ticket_labor(ticket, billable_increments=3, billed_minutes=45)

    def test_bundle_absorbs_the_chronologically_earliest_segment(self, api):
        """PRD §3.6: "The included budget is the contract's `remote_hands_remaining_minutes` divided by 15 and rounded **down** to whole increments, and `included_increments_applied` is the lesser of that budget and `billable_increments`."
        PRD §3.6: "The budget is walked against the segments in the same order they were billed, earliest segment first, so the earliest work is the work that gets absorbed."
        PRD §3.6: "The contract's `remote_hands_remaining_minutes` is reduced by `included_increments_applied` multiplied by 15."

        Design: Difficulty/combinatorial_formula/remote_hands_per_segment_ceiling_then_per_segment_rounding
        """
        scenario = self._dispatched_standard_ticket(api)

        self._complete(api, scenario.ticket["id"])

        ticket = fx.read_ticket(api, scenario.ticket["id"])
        ax.assert_ticket_labor(ticket, included_increments_applied=1)
        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract_billing_rollup(contract, remote_hands_remaining_minutes=0)

    def test_after_hours_money_is_rounded_per_segment_then_summed(self, api):
        """PRD §3.6: "Money is then computed per segment and rounded per segment: a segment's charge is the increments it contributed *minus* the increments the bundle absorbed from it, multiplied by 62.50 USD per increment, multiplied by an after-hours factor of 1.35 when the segment began outside business hours, and rounded half-up to two decimals."
        PRD §3.6: "A segment counts as after hours when the UTC hour of its `started_at` is before 08:00 or at or after 20:00."
        PRD §3.6: "`labor_charge_usd` is the sum of those per-segment charges; summing first and rounding once is not the rule."

        Design: Difficulty/combinatorial_formula/remote_hands_per_segment_ceiling_then_per_segment_rounding
        """
        scenario = self._dispatched_standard_ticket(api)

        self._complete(api, scenario.ticket["id"])

        ticket = fx.read_ticket(api, scenario.ticket["id"])
        ax.assert_ticket_labor(ticket, labor_charge_usd=168.76)

    def test_completion_appends_one_labour_line_and_no_sla_credit(self, api):
        """PRD §3.6: "When `labor_charge_usd` is greater than zero, an invoice line of `line_type` `REMOTE_HANDS` is appended carrying that amount, a `quantity` equal to `billable_increments` minus `included_increments_applied`, and `included_minutes_consumed` equal to the absorbed increments multiplied by 15."
        PRD §3.6: "When that line exists *and* `sla_breached` is true, a second line of `line_type` `SLA_CREDIT` is appended for the negative of 25 percent of `labor_charge_usd`, rounded to two decimals — a breach with no billable charge produces no credit, because there is nothing to credit against."
        PRD §3.6: "The ticket's `completed_at` is stamped, `execution_state` becomes `COMPLETED`, the contract's `billed_total_usd` is refreshed, and both the ticket's and the contract's `version` increment."

        Design: Difficulty/combinatorial_formula/remote_hands_per_segment_ceiling_then_per_segment_rounding
        """
        scenario = self._dispatched_standard_ticket(api)

        self._complete(api, scenario.ticket["id"])

        lines = _contract_lines(api, scenario.contract_id)
        assert len(lines) == 1, (
            f"a met response commitment produces the labour line alone, got "
            f"{[line['line_type'] for line in lines]}"
        )
        ax.assert_invoice_line_values(
            ax.one_line(lines, "REMOTE_HANDS"),
            line_type="REMOTE_HANDS",
            amount_usd=168.76,
            quantity=2,
            included_minutes_consumed=15,
        )
        assert not ax.find_lines(lines, "SLA_CREDIT"), (
            "sla_breached is false, so no SLA_CREDIT line may be appended"
        )

        ticket = fx.read_ticket(api, scenario.ticket["id"])
        assert ticket["execution_state"] == "COMPLETED", (
            f"ticket.execution_state: expected COMPLETED, got {ticket['execution_state']}"
        )
        assert ticket["authorization_state"] == "AUTHORIZED", (
            f"ticket.authorization_state must stay AUTHORIZED through completion, got "
            f"{ticket['authorization_state']}"
        )
        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract_billing_rollup(contract, billed_total_usd=168.76)
