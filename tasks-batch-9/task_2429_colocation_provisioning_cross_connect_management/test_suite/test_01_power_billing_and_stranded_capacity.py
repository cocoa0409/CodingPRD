"""Power money and power capacity, each reported under two competing definitions.

`billing_mode` decides whether a period close consumes recorded meter intervals or
discards them and deems consumption from energized capacity; a floor row reports
stranded capacity twice, once against energized breaker plates and once against the
largest peak actually observed in the trailing window. Both pairs are exercised here
against byte-identical physical setups so the divergence is attributable to the
variant alone.
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


def _setup_twin_power_contracts(api):
    """Two contracts under one customer holding identical energized capacity and
    identical meter intervals, differing only in `billing_mode`.

    Each contract owns one 20.0 kW cabinet in the same row carrying one energized
    100 A / 240 V single-phase primary circuit, and each circuit carries the same two
    July intervals of 8000 kWh and 8300 kWh.
    """
    fx.set_clock(api, k.DEFAULT_CLOCK)
    customer = fx.create_customer(api)
    row = fx.create_row(
        api,
        hall_code="H1",
        row_code="R1",
        cabinet_slot_count=10,
        design_density_kw_per_cabinet=25.0,
        max_row_power_kw=200.0,
        cooling_capacity_kw=60.0,
        escort_slot_count=1,
        decommission_flag=False,
    )

    built = {"row_id": row["id"]}
    for label, billing_mode, number, cabinet_code in (
        ("metered", "METERED_PLUS_COMMIT", "C-METERED", "C01"),
        ("committed", "COMMITTED_ONLY", "C-COMMITTED", "C02"),
    ):
        contract = fx.create_contract(
            api,
            customer["id"],
            contract_number=number,
            billing_mode=billing_mode,
            committed_cabinet_count=1,
            power_commit_kw=20.0,
            committed_bandwidth_mbps=1000,
            cross_connect_cap=6,
            committed_cage_sqft=0,
            redundancy_requirement="N",
            cross_connect_allowance=0,
            remote_hands_included_minutes=0,
        )
        fx.move_contract(api, contract["id"], "PENDING_ACTIVATION")
        cabinet = fx.create_cabinet(
            api, row["id"], cabinet_code=cabinet_code, rated_power_kw=20.0
        )
        fx.reserve_cabinet(api, cabinet["id"], contract["id"])
        fx.move_contract(api, contract["id"], "ACTIVE")
        fx.move_cabinet(api, cabinet["id"], "INSTALLED")
        circuit = fx.create_circuit(
            api,
            cabinet["id"],
            feed_side="A",
            redundancy_role="PRIMARY",
            breaker_amps=100,
            volts=240,
            phase="SINGLE",
        )
        fx.approve_circuit(api, circuit["id"])
        fx.energize_circuit(api, circuit["id"], row["id"])
        fx.append_reading(
            api, circuit["id"], "2026-07-05T00:00:00Z", "2026-07-06T00:00:00Z", 8000, 12.5
        )
        fx.append_reading(
            api, circuit["id"], "2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z", 8300, 11.0
        )
        built[f"{label}_contract_id"] = contract["id"]
        built[f"{label}_cabinet_id"] = cabinet["id"]
        built[f"{label}_circuit_id"] = circuit["id"]
    return built


def _close(api, contract_id):
    return validate_success(
        api.close_billing_period(
            contract_id, f.billing_close_payload(PERIOD_START, PERIOD_END), BILLING_OPERATOR
        )
    )


class TestMeteredVersusDeemedPowerBilling:
    """One power-billing formula, two `billing_mode` variants, two different totals."""

    def test_energized_primary_circuit_pins_its_derated_and_allocated_capacity(self, api):
        """PRD §3.4: "`derated_kw` is the breaker amperage multiplied by the voltage, multiplied by the phase factor — 1.0 for a `SINGLE`-phase supply and 1.732 for a `THREE`-phase supply — divided by 1000 to convert volt-amperes to kilowatts, then multiplied by the 0.80 continuous-load derate that electrical code requires, and finally rounded half-up to three decimal places."
        PRD §3.4: "For a `PRIMARY` circuit, `allocated_kw` is the lesser of its derated capacity and the host cabinet's `rated_power_kw` — the cabinet nameplate clamps what the floor will bill for, and the clamp is applied to the already-rounded derated figure — while `cooling_contribution_kw` is the full derated capacity, because heat is not clamped by a nameplate."

        Design: Difficulty/dual_variant_calc/power_billing_metered_final_versus_deemed_capacity
        """
        built = _setup_twin_power_contracts(api)

        for label in ("metered", "committed"):
            circuit = fx.read_circuit(api, built[f"{label}_circuit_id"])
            ax.assert_circuit_power(
                circuit,
                status="ENERGIZED",
                derated_kw=19.200,
                allocated_kw=19.200,
                cooling_contribution_kw=19.200,
            )

    def test_metered_close_bills_the_recorded_intervals_above_the_included_allowance(self, api):
        """PRD §3.9: "Under `METERED_PLUS_COMMIT`, billable consumption is the sum of `kwh` over the meter intervals of every circuit on the contract's cabinets whose `interval_start` falls at or after `period_start` and strictly before `period_end`, rounded to three decimals."
        PRD §3.9: "The commitment also buys energy: `included_kwh` is `power_commit_kw` multiplied by 730, the hours the site bills as a month, rounded to three decimals."
        PRD §3.9: "The overage charge walks a marginal three-tier ladder, low tier first: the first 500 kWh of overage bill at 0.1800 USD per kWh, the next 1500 kWh — that is, overage between 500 and 2000 kWh — bill at 0.1550 USD per kWh, and everything beyond 2000 kWh bills at 0.1350 USD per kWh."
        PRD §3.9: "Two lines may result, in this order: a `POWER_COMMIT` line whose `amount_usd` is the committed charge and whose `quantity` is `power_commit_kw`, always; and a `POWER_OVERAGE` line whose `amount_usd` is the overage charge and whose `quantity` is the overage energy, appended only when the overage energy is greater than zero."

        Design: Difficulty/dual_variant_calc/power_billing_metered_final_versus_deemed_capacity
        """
        built = _setup_twin_power_contracts(api)

        _close(api, built["metered_contract_id"])

        lines = _contract_lines(api, built["metered_contract_id"])
        assert len(lines) == 2, (
            f"Expected exactly a POWER_COMMIT and a POWER_OVERAGE line, got "
            f"{[line['line_type'] for line in lines]}"
        )
        ax.assert_invoice_line_values(
            ax.one_line(lines, "POWER_COMMIT"),
            line_type="POWER_COMMIT",
            amount_usd=3500.00,
            quantity=20.0,
        )
        ax.assert_invoice_line_values(
            ax.one_line(lines, "POWER_OVERAGE"),
            line_type="POWER_OVERAGE",
            amount_usd=276.00,
            quantity=1700.000,
        )

    def test_committed_only_close_discards_the_intervals_and_deems_consumption(self, api):
        """PRD §3.9: "Under `COMMITTED_ONLY`, the meter intervals are ignored altogether and consumption is deemed: the sum of `allocated_kw` over circuits that are both `ENERGIZED` and `PRIMARY` on the contract's cabinets at close time, multiplied by the same 730 hours, then multiplied by a deemed load factor of 0.65, rounded to three decimals."
        PRD §3.9: "Overage energy is billable consumption minus `included_kwh`, rounded to three decimals and floored at zero, so consumption exactly equal to the allowance yields no overage at all."
        PRD §3.9: "Power billing begins with the committed charge, which is `power_commit_kw` multiplied by the standing rate of 175.00 USD per contracted kilowatt per month, rounded to two decimals."

        Design: Difficulty/dual_variant_calc/power_billing_metered_final_versus_deemed_capacity
        """
        built = _setup_twin_power_contracts(api)

        _close(api, built["committed_contract_id"])

        lines = _contract_lines(api, built["committed_contract_id"])
        assert len(lines) == 1, (
            f"Deemed consumption of 9110.400 kWh sits below the 14600.000 kWh allowance, so only "
            f"the committed charge is billable; got {[line['line_type'] for line in lines]}"
        )
        ax.assert_invoice_line_values(
            ax.one_line(lines, "POWER_COMMIT"),
            line_type="POWER_COMMIT",
            amount_usd=3500.00,
            quantity=20.0,
        )
        assert not ax.find_lines(lines, "POWER_OVERAGE"), (
            "COMMITTED_ONLY deems 19.200 * 730 * 0.65 kWh, below the allowance, so no "
            "POWER_OVERAGE line may be appended"
        )

    def test_two_billing_modes_settle_identical_capacity_to_different_totals(self, api):
        """PRD §3.9: "Identical recorded intervals therefore produce a different — and usually lower — overage under `COMMITTED_ONLY` than under `METERED_PLUS_COMMIT`, which is the whole commercial point of the distinction."
        PRD §3.4: "The same rollup pass also refreshes `active_cross_connect_count`, the count of the contract's cross-connect orders in `ACTIVE`; `billed_total_usd`, the sum of `amount_usd` across every invoice line ever appended to the contract, credits and reversals included, rounded to two decimals; and `cross_connect_billed_usd`, the same sum restricted to lines whose `line_type` is `CROSS_CONNECT_MRC` or `CROSS_CONNECT_SURCHARGE`, likewise rounded to two decimals."

        Design: Difficulty/dual_variant_calc/power_billing_metered_final_versus_deemed_capacity
        """
        built = _setup_twin_power_contracts(api)

        _close(api, built["metered_contract_id"])
        _close(api, built["committed_contract_id"])

        metered = fx.read_contract(api, built["metered_contract_id"])
        committed = fx.read_contract(api, built["committed_contract_id"])

        ax.assert_contract_billing_rollup(metered, billed_total_usd=3776.00)
        ax.assert_contract_billing_rollup(committed, billed_total_usd=3500.00)
        gap = ax.round_half_up(metered["billed_total_usd"], 2) - ax.round_half_up(
            committed["billed_total_usd"], 2
        )
        ax.assert_amount_equals(gap, 276.00, "metered-minus-deemed billing gap")

    def test_close_stamps_the_supplied_period_end_on_both_contracts(self, api):
        """PRD §3.9: "When the close completes, `last_closed_period_end` is set to the supplied `period_end` and `billed_total_usd` and `cross_connect_billed_usd` are refreshed."

        Design: Difficulty/dual_variant_calc/power_billing_metered_final_versus_deemed_capacity
        """
        built = _setup_twin_power_contracts(api)

        _close(api, built["metered_contract_id"])
        _close(api, built["committed_contract_id"])

        for label in ("metered", "committed"):
            contract = fx.read_contract(api, built[f"{label}_contract_id"])
            assert _instant(contract["last_closed_period_end"]) == _instant(PERIOD_END), (
                f"{label} contract.last_closed_period_end: expected the supplied "
                f"{PERIOD_END}, got {contract['last_closed_period_end']}"
            )


class TestRowStrandedCapacityViews:
    """One row, one effective ceiling, two stranded-capacity definitions."""

    ROW = {
        "hall_code": "H2",
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
        "cross_connect_cap": 4,
    }
    CABINET = {"cabinet_code": "C01", "rated_power_kw": 20.0}
    CIRCUIT = {
        "circuit_code": "A-1",
        "feed_side": "A",
        "redundancy_role": "PRIMARY",
        "breaker_amps": 100,
        "volts": 240,
        "phase": "SINGLE",
    }

    def _energized_row(self, api):
        return fx.setup_energized_cabinet(
            api, row=self.ROW, contract=self.CONTRACT, cabinet=self.CABINET, circuit=self.CIRCUIT
        )

    def test_nameplate_view_charges_the_row_for_every_energized_breaker_plate(self, api):
        """PRD §3.2: "`occupied_slot_count` counts the cabinets in the row whose `status` is `RESERVED`, `CAPACITY_HELD`, `INSTALLED`, `ACTIVE` or `DECOMMISSIONING`; an `AVAILABLE` or `RELEASED` cabinet occupies nothing."
        PRD §3.2: "`density_ceiling_kw` is the design density multiplied by the number of occupied slots, rounded to three decimals — a row engineered at 8 kW per cabinet with five occupied slots carries a ceiling of 40 kW, and that ceiling grows and shrinks with occupancy rather than with the row's physical slot count."
        PRD §3.2: "`effective_ceiling_kw` is the smallest of three numbers: the busway limit `max_row_power_kw`, the density ceiling just derived, and the cooling capacity."
        PRD §3.2: "The **nameplate view**, `stranded_nameplate_kw`, is the effective ceiling minus `allocated_power_kw`, rounded to three decimals: it charges the row for every breaker plate that has been energized, so a lightly loaded cabinet with a large breaker strands nothing at all."

        Design: Difficulty/dual_variant_calc/row_stranded_capacity_nameplate_versus_measured
        """
        scenario = self._energized_row(api)

        row = fx.read_row(api, scenario.row_id)
        ax.assert_row_capacity_view(
            row,
            occupied_slot_count=1,
            density_ceiling_kw=20.000,
            effective_ceiling_kw=20.000,
            allocated_power_kw=19.200,
            stranded_nameplate_kw=0.800,
        )

    def test_measured_view_reports_the_whole_ceiling_before_any_interval_is_recorded(self, api):
        """PRD §3.2: "The **measured view**, `stranded_measured_kw`, is the effective ceiling minus `measured_peak_kw`, rounded to three decimals, where `measured_peak_kw` is the largest `peak_kw` recorded across the meter intervals of the row's circuits whose `interval_start` falls at or after 30 days before the logical clock, and is 0 when the trailing window holds no interval at all."

        Design: Difficulty/dual_variant_calc/row_stranded_capacity_nameplate_versus_measured
        """
        scenario = self._energized_row(api)

        row = fx.read_row(api, scenario.row_id)
        ax.assert_kw_equals(row["measured_peak_kw"], 0, "row.measured_peak_kw")
        ax.assert_row_capacity_view(row, stranded_measured_kw=20.000)

    def test_measured_view_follows_the_recorded_peak_of_the_trailing_window(self, api):
        """PRD §3.2: "The **measured view**, `stranded_measured_kw`, is the effective ceiling minus `measured_peak_kw`, rounded to three decimals, where `measured_peak_kw` is the largest `peak_kw` recorded across the meter intervals of the row's circuits whose `interval_start` falls at or after 30 days before the logical clock, and is 0 when the trailing window holds no interval at all."
        PRD §3.4: "Appending a reading recomputes the host row's `measured_peak_kw` and therefore its `stranded_measured_kw`, which is how a row's measured stranded capacity can change without any electrical work taking place."

        Design: Difficulty/dual_variant_calc/row_stranded_capacity_nameplate_versus_measured
        """
        scenario = self._energized_row(api)

        fx.append_reading(
            api, scenario.circuit_id, "2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z", 8000, 12.5
        )

        row = fx.read_row(api, scenario.row_id)
        ax.assert_kw_equals(row["measured_peak_kw"], 12.500, "row.measured_peak_kw")
        ax.assert_row_capacity_view(row, stranded_measured_kw=7.500)

    def test_measured_view_strands_more_than_the_nameplate_view_on_the_same_row(self, api):
        """PRD §3.2: "Because observed peak draw is usually below energized breaker capacity, the same row normally reports *more* stranded capacity under the measured view than under the nameplate view, and that gap is the number the capacity team sells against."
        PRD §3.2: "`allocated_power_kw` is the sum of `allocated_kw` over the energized circuits of the row's cabinets, rounded to three decimals, and `cooling_load_kw` is the sum of `cooling_contribution_kw` over the same set, likewise rounded to three decimals."

        Design: Difficulty/dual_variant_calc/row_stranded_capacity_nameplate_versus_measured
        """
        scenario = self._energized_row(api)

        fx.append_reading(
            api, scenario.circuit_id, "2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z", 8000, 12.5
        )

        row = fx.read_row(api, scenario.row_id)
        ax.assert_row_capacity_view(
            row,
            allocated_power_kw=19.200,
            stranded_nameplate_kw=0.800,
            stranded_measured_kw=7.500,
        )
        gap = ax.round_half_up(row["stranded_measured_kw"], 3) - ax.round_half_up(
            row["stranded_nameplate_kw"], 3
        )
        ax.assert_kw_equals(gap, 6.700, "measured-minus-nameplate stranded gap")

    def test_row_below_its_density_ceiling_stays_open_under_both_views(self, api):
        """PRD §3.2: "Posture, exposed as `row_status`, is derived from the same figures and is evaluated as an ordered cascade in which the first matching condition wins and the remaining conditions are not consulted."
        PRD §3.2: "Otherwise, if at least one slot is occupied and `allocated_power_kw` has reached or passed `density_ceiling_kw` the row is `DENSITY_CAPPED`."
        PRD §3.2: "Otherwise the row is `OPEN`."
        PRD §3.2: "`density_ceiling_kw` is the design density multiplied by the number of occupied slots, rounded to three decimals — a row engineered at 8 kW per cabinet with five occupied slots carries a ceiling of 40 kW, and that ceiling grows and shrinks with occupancy rather than with the row's physical slot count."
        PRD §3.2: "`allocated_power_kw` is the sum of `allocated_kw` over the energized circuits of the row's cabinets, rounded to three decimals, and `cooling_load_kw` is the sum of `cooling_contribution_kw` over the same set, likewise rounded to three decimals."

        Design: Difficulty/dual_variant_calc/row_stranded_capacity_nameplate_versus_measured
        """
        scenario = self._energized_row(api)

        fx.append_reading(
            api, scenario.circuit_id, "2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z", 8000, 12.5
        )

        row = fx.read_row(api, scenario.row_id)
        ax.assert_row_capacity_view(
            row, density_ceiling_kw=20.000, allocated_power_kw=19.200, row_status="OPEN"
        )
