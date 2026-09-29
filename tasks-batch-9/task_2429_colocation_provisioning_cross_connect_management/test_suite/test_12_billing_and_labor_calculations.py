"""Money and metering arithmetic: the trailing measured-peak window, the marginal
power-overage ladder, the cross-connect close candidate set, remote-hands increment
billing with its after-hours factor and SLA credit, and the period-bound guard.
"""

from datetime import datetime

import pytest

from test_helpers import assertions as ax, constants as k, factories as f, fixtures as fx
from test_helpers import (
    ENGINEER_2,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable datetime."""
    assert isinstance(value, str), f"expected an ISO 8601 UTC timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_same_instant(actual, expected, label):
    assert _instant(actual) == _instant(expected), f"{label}: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# The trailing measured-peak window
# ---------------------------------------------------------------------------


def test_measured_peak_ignores_an_interval_starting_before_the_thirty_day_window(
    api, facility_manager_headers
):
    """PRD §3.2: "The **measured view**, `stranded_measured_kw`, is the effective ceiling minus `measured_peak_kw`, rounded to three decimals, where `measured_peak_kw` is the largest `peak_kw` recorded across the meter intervals of the row's circuits whose `interval_start` falls at or after 30 days before the logical clock, and is 0 when the trailing window holds no interval at all."
    PRD §3.4: "Appending a reading recomputes the host row's `measured_peak_kw` and therefore its `stranded_measured_kw`, which is how a row's measured stranded capacity can change without any electrical work taking place."

    Design: Corner/calculations/measured_peak_window_boundary_admits_day_thirty_and_ignores_day_thirty_one
    """
    scenario = fx.setup_reserved_cabinet(api)
    fx.set_clock(api, k.DEFAULT_CLOCK)
    circuit = fx.add_designed_circuit(api, scenario)

    # The older interval starts an hour before the window opens; the second starts
    # exactly on the boundary instant 30 days before the clock.
    fx.append_reading(
        api, circuit["id"], "2026-07-01T23:00:00Z", "2026-07-02T00:00:00Z", 9.0, 9.0
    )
    fx.append_reading(
        api, circuit["id"], "2026-07-02T00:00:00Z", "2026-07-02T01:00:00Z", 5.0, 5.0
    )

    row = validate_success(api.get_row(scenario.row_id, facility_manager_headers))
    ax.assert_floor_row(row)
    ax.assert_kw_equals(row["measured_peak_kw"], 5.000, "row.measured_peak_kw")
    ax.assert_kw_equals(row["stranded_measured_kw"], 20.000, "row.stranded_measured_kw")


def test_row_ceilings_and_nameplate_view_while_the_only_circuit_is_designed(
    api, facility_manager_headers
):
    """PRD §3.2: "`density_ceiling_kw` is the design density multiplied by the number of occupied slots, rounded to three decimals — a row engineered at 8 kW per cabinet with five occupied slots carries a ceiling of 40 kW, and that ceiling grows and shrinks with occupancy rather than with the row's physical slot count."
    PRD §3.2: "`effective_ceiling_kw` is the smallest of three numbers: the busway limit `max_row_power_kw`, the density ceiling just derived, and the cooling capacity."
    PRD §3.2: "The **nameplate view**, `stranded_nameplate_kw`, is the effective ceiling minus `allocated_power_kw`, rounded to three decimals: it charges the row for every breaker plate that has been energized, so a lightly loaded cabinet with a large breaker strands nothing at all."
    PRD §3.4: "While a circuit's `status` is `DESIGNED`, `APPROVED`, `BLOCKED`, `DE_ENERGIZED` or `REMOVED`, both `allocated_kw` and `cooling_contribution_kw` are 0.000."
    PRD §3.2: "Otherwise the row is `OPEN`."

    Design: Corner/calculations/measured_peak_window_boundary_admits_day_thirty_and_ignores_day_thirty_one
    """
    scenario = fx.setup_reserved_cabinet(api)
    fx.set_clock(api, k.DEFAULT_CLOCK)
    circuit = fx.add_designed_circuit(api, scenario)
    fx.append_reading(
        api, circuit["id"], "2026-07-01T23:00:00Z", "2026-07-02T00:00:00Z", 9.0, 9.0
    )
    fx.append_reading(
        api, circuit["id"], "2026-07-02T00:00:00Z", "2026-07-02T01:00:00Z", 5.0, 5.0
    )

    row = validate_success(api.get_row(scenario.row_id, facility_manager_headers))
    ax.assert_row_capacity_view(
        row,
        occupied_slot_count=1,
        density_ceiling_kw=25.000,
        effective_ceiling_kw=25.000,
        allocated_power_kw=0.000,
        cooling_load_kw=0.000,
        stranded_nameplate_kw=25.000,
        row_status="OPEN",
    )


def test_meter_intervals_are_retained_on_the_circuit_in_append_order(api):
    """PRD §3.4: "Intervals are retained in the order they were appended, in the circuit's `meter_intervals` collection, and an interval whose `interval_end` is not after its `interval_start` is refused with `ERR_BILLING_PERIOD_INVALID`."

    Design: Corner/calculations/measured_peak_window_boundary_admits_day_thirty_and_ignores_day_thirty_one
    """
    scenario = fx.setup_reserved_cabinet(api)
    fx.set_clock(api, k.DEFAULT_CLOCK)
    circuit = fx.add_designed_circuit(api, scenario)
    fx.append_reading(
        api, circuit["id"], "2026-07-01T23:00:00Z", "2026-07-02T00:00:00Z", 9.0, 9.0
    )
    fx.append_reading(
        api, circuit["id"], "2026-07-02T00:00:00Z", "2026-07-02T01:00:00Z", 5.0, 5.0
    )

    stored = fx.read_circuit(api, circuit["id"])
    intervals = stored["meter_intervals"]
    assert len(intervals) == 2, f"expected both appended intervals, got {intervals}"
    assert [i["peak_kw"] for i in intervals] == pytest.approx([9.0, 5.0], abs=0.001), (
        f"meter_intervals must keep the order they were appended in, got {intervals}"
    )


# ---------------------------------------------------------------------------
# The power-overage ladder
# ---------------------------------------------------------------------------


def _metered_contract_with_one_july_interval(api, kwh):
    """An `ACTIVE` 1.0 kW metered contract carrying a single July meter interval."""
    scenario = fx.setup_active_contract(
        api,
        contract={
            "billing_mode": "METERED_PLUS_COMMIT",
            "power_commit_kw": 1.0,
            "cross_connect_cap": 1,
            "cross_connect_allowance": 0,
        },
    )
    circuit = fx.add_designed_circuit(api, scenario)
    fx.append_reading(
        api, circuit["id"], "2026-07-10T00:00:00Z", "2026-07-11T00:00:00Z", kwh, 5.0
    )
    return scenario


def test_power_overage_walks_all_three_marginal_tiers(api, billing_operator_headers):
    """PRD §3.9: "The overage charge walks a marginal three-tier ladder, low tier first: the first 500 kWh of overage bill at 0.1800 USD per kWh, the next 1500 kWh — that is, overage between 500 and 2000 kWh — bill at 0.1550 USD per kWh, and everything beyond 2000 kWh bills at 0.1350 USD per kWh."
    PRD §3.9: "The three tier products are summed and the sum is rounded once, half-up, to two decimals; the tiers are not rounded individually."
    PRD §3.9: "Overage energy is billable consumption minus `included_kwh`, rounded to three decimals and floored at zero, so consumption exactly equal to the allowance yields no overage at all."
    PRD §3.9: "Under `METERED_PLUS_COMMIT`, billable consumption is the sum of `kwh` over the meter intervals of every circuit on the contract's cabinets whose `interval_start` falls at or after `period_start` and strictly before `period_end`, rounded to three decimals."

    Design: Corner/calculations/power_overage_ladder_straddles_all_three_marginal_tiers
    """
    scenario = _metered_contract_with_one_july_interval(api, 3230.0)

    closed = validate_success(
        api.close_billing_period(
            scenario.contract_id,
            f.billing_close_payload("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"),
            billing_operator_headers,
        )
    )

    ax.assert_contract_billing_rollup(
        closed, billed_total_usd=565.00, cross_connect_billed_usd=0.00
    )
    _assert_same_instant(
        closed["last_closed_period_end"],
        "2026-08-01T00:00:00Z",
        "contract.last_closed_period_end",
    )

    lines, meta = validate_paginated(
        api.list_invoice_lines(
            billing_operator_headers, params={"contract_id": scenario.contract_id}
        )
    )
    assert meta["total_count"] == 2, f"expected exactly two ledger rows, got {lines}"
    overage = ax.one_line(lines, "POWER_OVERAGE")
    ax.assert_invoice_line_values(overage, amount_usd=390.00, quantity=2500.000)


def test_power_close_appends_the_commit_line_alongside_the_overage_line(
    api, billing_operator_headers
):
    """PRD §3.9: "Power billing begins with the committed charge, which is `power_commit_kw` multiplied by the standing rate of 175.00 USD per contracted kilowatt per month, rounded to two decimals."
    PRD §3.9: "Two lines may result, in this order: a `POWER_COMMIT` line whose `amount_usd` is the committed charge and whose `quantity` is `power_commit_kw`, always; and a `POWER_OVERAGE` line whose `amount_usd` is the overage charge and whose `quantity` is the overage energy, appended only when the overage energy is greater than zero."
    PRD §3.9: "When the close completes, `last_closed_period_end` is set to the supplied `period_end` and `billed_total_usd` and `cross_connect_billed_usd` are refreshed."

    Design: Corner/calculations/power_overage_ladder_straddles_all_three_marginal_tiers
    """
    scenario = _metered_contract_with_one_july_interval(api, 3230.0)
    fx.close_period(
        api, scenario.contract_id, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
    )

    lines, _ = validate_paginated(
        api.list_invoice_lines(
            billing_operator_headers, params={"contract_id": scenario.contract_id}
        )
    )
    commit = ax.one_line(lines, "POWER_COMMIT")
    ax.assert_invoice_line(commit)
    ax.assert_invoice_line_values(
        commit, amount_usd=175.00, quantity=1.0, unit_rate_usd=175.0000
    )


def test_consumption_equal_to_the_allowance_appends_no_overage_line(
    api, billing_operator_headers
):
    """PRD §3.9: "Overage energy is billable consumption minus `included_kwh`, rounded to three decimals and floored at zero, so consumption exactly equal to the allowance yields no overage at all."
    PRD §3.9: "The commitment also buys energy: `included_kwh` is `power_commit_kw` multiplied by 730, the hours the site bills as a month, rounded to three decimals."
    PRD §3.9: "Two lines may result, in this order: a `POWER_COMMIT` line whose `amount_usd` is the committed charge and whose `quantity` is `power_commit_kw`, always; and a `POWER_OVERAGE` line whose `amount_usd` is the overage charge and whose `quantity` is the overage energy, appended only when the overage energy is greater than zero."

    Design: Corner/calculations/overage_is_zero_when_consumption_equals_the_included_allowance_exactly
    """
    scenario = _metered_contract_with_one_july_interval(api, 730.0)

    closed = validate_success(
        api.close_billing_period(
            scenario.contract_id,
            f.billing_close_payload("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"),
            billing_operator_headers,
        )
    )
    ax.assert_contract_billing_rollup(closed, billed_total_usd=175.00)

    lines, meta = validate_paginated(
        api.list_invoice_lines(
            billing_operator_headers, params={"contract_id": scenario.contract_id}
        )
    )
    assert meta["total_count"] == 1, f"only the commit line may be appended, got {lines}"
    assert ax.find_lines(lines, "POWER_OVERAGE") == [], (
        "a zero overage must suppress the POWER_OVERAGE line entirely"
    )
    ax.assert_invoice_line_values(lines[0], line_type="POWER_COMMIT", amount_usd=175.00)


# ---------------------------------------------------------------------------
# Cross-connect close candidates
# ---------------------------------------------------------------------------


def test_close_excludes_a_cross_connect_order_still_in_submitted(
    api, billing_operator_headers
):
    """PRD §3.9: "First, the candidates are the contract's cross-connect orders whose status is `ACTIVE` at close time, ranked by `mrc_usd` ascending with ties broken by `created_at` ascending; orders in `SUBMITTED`, `ROUTE_PROPOSED`, `CHANGES_REQUESTED`, `APPROVED`, `INSTALLED`, `DECOMMISSIONED` or `ABORTED` are excluded entirely."
    PRD §3.9: "Two lines are appended, in this order and only when the discounted subtotal is greater than zero: a `CROSS_CONNECT_MRC` line whose `amount_usd` is the discounted subtotal, and a `CROSS_CONNECT_SURCHARGE` line whose `amount_usd` is the surcharge, each carrying a `quantity` equal to the number of billed candidates — the waived ones excluded."
    PRD §3.4: "The same rollup pass also refreshes `active_cross_connect_count`, the count of the contract's cross-connect orders in `ACTIVE`; `billed_total_usd`, the sum of `amount_usd` across every invoice line ever appended to the contract, credits and reversals included, rounded to two decimals; and `cross_connect_billed_usd`, the same sum restricted to lines whose `line_type` is `CROSS_CONNECT_MRC` or `CROSS_CONNECT_SURCHARGE`, likewise rounded to two decimals."
    PRD §3.5: "A created order opens in `SUBMITTED` with `revision_count` at 0, no route pinned, and `mrc_usd` fixed from the media it will use: 300.00 USD for `SMF`, 250.00 USD for `MMF`, 175.00 USD for `CAT6A`, 225.00 USD for `COAX`."

    Design: Corner/calculations/cross_connect_close_ignores_an_order_that_never_reached_active
    """
    scenario = fx.setup_installed_cabinet(
        api,
        contract={
            "billing_mode": "METERED_PLUS_COMMIT",
            "power_commit_kw": 1.0,
            "cross_connect_cap": 2,
            "cross_connect_allowance": 0,
        },
        cabinet={"cabinet_code": "C01"},
    )
    scenario.cabinets.append(fx.create_cabinet(api, scenario.row_id, cabinet_code="C02"))
    scenario.contacts.append(fx.create_contact(api, scenario.customer_id))

    order = fx.raise_cross_connect_order(api, scenario, cable_type="SMF")
    assert order["status"] == "SUBMITTED", f"order must open in SUBMITTED, got {order['status']}"
    assert order["revision_count"] == 0, "a new order carries revision_count 0"
    ax.assert_amount_equals(order["mrc_usd"], 300.00, "order.mrc_usd")

    closed = validate_success(
        api.close_billing_period(
            scenario.contract_id,
            f.billing_close_payload("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"),
            billing_operator_headers,
        )
    )
    ax.assert_contract_billing_rollup(
        closed,
        billed_total_usd=175.00,
        cross_connect_billed_usd=0.00,
        active_cross_connect_count=0,
    )

    lines, meta = validate_paginated(
        api.list_invoice_lines(
            billing_operator_headers, params={"contract_id": scenario.contract_id}
        )
    )
    assert meta["total_count"] == 1, f"only the power commit line may exist, got {lines}"
    assert ax.find_lines(lines, "CROSS_CONNECT_MRC") == [], (
        "a SUBMITTED order is not a close candidate"
    )
    assert ax.find_lines(lines, "CROSS_CONNECT_SURCHARGE") == [], (
        "no surcharge may follow an empty candidate set"
    )


# ---------------------------------------------------------------------------
# Remote-hands increment billing
# ---------------------------------------------------------------------------


def _standard_ticket_dispatched_at_0730(api):
    """A `STANDARD` ticket authorized on the hour and dispatched at 07:30, well
    inside its 480-minute commitment."""
    scenario = fx.setup_authorized_ticket(api, severity="STANDARD")
    fx.set_clock(api, "2026-08-01T07:30:00Z")
    return scenario


def test_after_hours_multiplier_applies_only_to_the_segment_that_started_before_eight(
    api, provisioning_engineer_2_headers
):
    """PRD §3.6: "Money is then computed per segment and rounded per segment: a segment's charge is the increments it contributed *minus* the increments the bundle absorbed from it, multiplied by 62.50 USD per increment, multiplied by an after-hours factor of 1.35 when the segment began outside business hours, and rounded half-up to two decimals."
    PRD §3.6: "A segment counts as after hours when the UTC hour of its `started_at` is before 08:00 or at or after 20:00."
    PRD §3.6: "`labor_charge_usd` is the sum of those per-segment charges; summing first and rounding once is not the rule."
    PRD §3.6: "Those per-segment increments are then summed into `billable_increments`; summing raw minutes across segments first and taking a single ceiling is expressly not the rule, so two seven-minute segments bill two increments rather than one."
    PRD §3.6: "`billed_minutes` is `billable_increments` multiplied by 15."

    Design: Corner/calculations/after_hours_boundary_splits_one_ticket_across_two_rates
    """
    scenario = _standard_ticket_dispatched_at_0730(api)
    ticket_id = scenario.ticket["id"]
    dispatched = fx.dispatch_ticket(api, ticket_id)
    _assert_same_instant(
        dispatched["response_deadline_at"],
        "2026-08-01T08:00:00Z",
        "ticket.response_deadline_at",
    )
    ax.assert_ticket_labor(dispatched, sla_breached=False)

    completed = validate_success(
        api.complete_ticket(
            ticket_id,
            f.complete_ticket_payload(
                f.work_segment("2026-08-01T07:45:00Z", "2026-08-01T08:00:00Z"),
                f.work_segment("2026-08-01T08:00:00Z", "2026-08-01T08:15:00Z"),
            ),
            provisioning_engineer_2_headers,
        )
    )

    assert completed["execution_state"] == "COMPLETED", (
        f"completion closes the execution dimension, got {completed['execution_state']}"
    )
    ax.assert_ticket_labor(
        completed,
        billable_increments=2,
        billed_minutes=30,
        included_increments_applied=0,
        labor_charge_usd=146.88,
    )


def test_after_hours_split_ticket_appends_one_labour_line_and_no_sla_credit(
    api, billing_operator_headers, provisioning_engineer_2_headers
):
    """PRD §3.6: "When `labor_charge_usd` is greater than zero, an invoice line of `line_type` `REMOTE_HANDS` is appended carrying that amount, a `quantity` equal to `billable_increments` minus `included_increments_applied`, and `included_minutes_consumed` equal to the absorbed increments multiplied by 15."
    PRD §3.6: "When that line exists *and* `sla_breached` is true, a second line of `line_type` `SLA_CREDIT` is appended for the negative of 25 percent of `labor_charge_usd`, rounded to two decimals — a breach with no billable charge produces no credit, because there is nothing to credit against."
    PRD §3.6: "The contract's `remote_hands_remaining_minutes` is reduced by `included_increments_applied` multiplied by 15."

    Design: Corner/calculations/after_hours_boundary_splits_one_ticket_across_two_rates
    """
    scenario = _standard_ticket_dispatched_at_0730(api)
    ticket_id = scenario.ticket["id"]
    fx.dispatch_ticket(api, ticket_id)
    validate_success(
        api.complete_ticket(
            ticket_id,
            f.complete_ticket_payload(
                f.work_segment("2026-08-01T07:45:00Z", "2026-08-01T08:00:00Z"),
                f.work_segment("2026-08-01T08:00:00Z", "2026-08-01T08:15:00Z"),
            ),
            provisioning_engineer_2_headers,
        )
    )

    lines, meta = validate_paginated(
        api.list_invoice_lines(
            billing_operator_headers, params={"contract_id": scenario.contract_id}
        )
    )
    assert meta["total_count"] == 1, f"exactly one labour line is expected, got {lines}"
    labour = ax.one_line(lines, "REMOTE_HANDS")
    ax.assert_invoice_line(labour)
    ax.assert_invoice_line_values(
        labour, amount_usd=146.88, quantity=2, included_minutes_consumed=0
    )
    assert ax.find_lines(lines, "SLA_CREDIT") == [], (
        "a met commitment must not produce an SLA credit"
    )

    contract = fx.read_contract(api, scenario.contract_id)
    ax.assert_contract_billing_rollup(
        contract, billed_total_usd=146.88, remote_hands_remaining_minutes=0
    )


def test_sla_credit_is_appended_when_a_critical_dispatch_misses_the_deadline(
    api, billing_operator_headers, provisioning_engineer_2_headers
):
    """PRD §3.6: "`response_deadline_at` is `authorized_at` advanced by 30 minutes for a `CRITICAL` ticket, by 120 minutes for a `HIGH` ticket, and by 480 minutes — eight hours — for a `STANDARD` ticket."
    PRD §3.6: "On success `dispatched_at` is stamped from the logical clock and `sla_breached` is set true only when `dispatched_at` is strictly later than `response_deadline_at`; a dispatch landing exactly on the deadline instant has met the commitment, not breached it."
    PRD §3.6: "When that line exists *and* `sla_breached` is true, a second line of `line_type` `SLA_CREDIT` is appended for the negative of 25 percent of `labor_charge_usd`, rounded to two decimals — a breach with no billable charge produces no credit, because there is nothing to credit against."
    PRD §3.9: "`source_ref_id` is a polymorphic back-reference resolved by `line_type` — the cross-connect order, the remote-hands ticket, or the reversed line — and it is deliberately never consulted in any ordering or selection decision."

    Design: Corner/calculations/sla_credit_is_issued_when_dispatch_misses_the_critical_deadline
    """
    scenario = fx.setup_authorized_ticket(api, severity="CRITICAL")
    ticket_id = scenario.ticket["id"]

    fx.set_clock(api, "2026-08-01T00:31:00Z")
    dispatched = fx.dispatch_ticket(api, ticket_id)
    _assert_same_instant(
        dispatched["response_deadline_at"],
        "2026-08-01T00:30:00Z",
        "ticket.response_deadline_at",
    )
    _assert_same_instant(
        dispatched["dispatched_at"], "2026-08-01T00:31:00Z", "ticket.dispatched_at"
    )
    ax.assert_ticket_labor(dispatched, sla_breached=True)

    fx.set_clock(api, "2026-08-01T10:20:00Z")
    completed = validate_success(
        api.complete_ticket(
            ticket_id,
            f.complete_ticket_payload(
                f.work_segment("2026-08-01T10:00:00Z", "2026-08-01T10:15:00Z")
            ),
            provisioning_engineer_2_headers,
        )
    )
    ax.assert_ticket_labor(
        completed, billable_increments=1, labor_charge_usd=62.50, sla_breached=True
    )

    lines, meta = validate_paginated(
        api.list_invoice_lines(
            billing_operator_headers, params={"contract_id": scenario.contract_id}
        )
    )
    assert meta["total_count"] == 2, f"a labour line and its credit are expected, got {lines}"
    ax.assert_invoice_line_values(
        ax.one_line(lines, "REMOTE_HANDS"), amount_usd=62.50, quantity=1
    )
    credit = ax.one_line(lines, "SLA_CREDIT")
    ax.assert_invoice_line_values(credit, amount_usd=-15.63, source_ref_id=ticket_id)

    contract = fx.read_contract(api, scenario.contract_id)
    ax.assert_contract_billing_rollup(contract, billed_total_usd=46.87)


def test_dispatch_exactly_at_the_response_deadline_is_not_a_breach(api):
    """PRD §3.6: "On success `dispatched_at` is stamped from the logical clock and `sla_breached` is set true only when `dispatched_at` is strictly later than `response_deadline_at`; a dispatch landing exactly on the deadline instant has met the commitment, not breached it."
    PRD §3.6: "`response_deadline_at` is `authorized_at` advanced by 30 minutes for a `CRITICAL` ticket, by 120 minutes for a `HIGH` ticket, and by 480 minutes — eight hours — for a `STANDARD` ticket."
    PRD §3.6: "Dispatch does not advance execution any further: `DISPATCHED` is an observable state in its own right."

    Design: Corner/calculations/dispatch_exactly_at_the_response_deadline_is_met_not_breached
    """
    scenario = fx.setup_authorized_ticket(api, severity="CRITICAL")
    fx.set_clock(api, "2026-08-01T00:30:00Z")

    # Dispatch is a ProvisioningEngineer's act, and not the engineer who raised it.
    dispatched = validate_success(api.dispatch_ticket(scenario.ticket["id"], ENGINEER_2))

    assert dispatched["execution_state"] == "DISPATCHED", (
        f"dispatch moves execution to DISPATCHED, got {dispatched['execution_state']}"
    )
    _assert_same_instant(
        dispatched["dispatched_at"], "2026-08-01T00:30:00Z", "ticket.dispatched_at"
    )
    _assert_same_instant(
        dispatched["response_deadline_at"],
        "2026-08-01T00:30:00Z",
        "ticket.response_deadline_at",
    )
    ax.assert_ticket_labor(dispatched, sla_breached=False)
    assert dispatched["authorization_state"] == "AUTHORIZED", (
        "the two state dimensions advance independently"
    )


# ---------------------------------------------------------------------------
# Escort requirement pinned at booking
# ---------------------------------------------------------------------------


def test_meet_me_footprint_alone_pins_escort_required_true(api, security_officer_headers):
    """PRD §3.7: "`escort_required` is computed once, at booking, and pinned on the visit."
    PRD §3.7: "It is true when any one of three conditions holds: the contact's `access_level` is `ESCORTED_ONLY`, or the visit's `purpose` is `CARRIER_INSTALL`, or the target cabinet's `footprint_type` is `MEET_ME`."
    PRD §3.7: "New visits open in `SCHEDULED`, and the lifecycle is `SCHEDULED` → `CHECKED_IN` → `CHECKED_OUT`, with `SCHEDULED` → `CANCELLED` as the abandonment path; `CHECKED_OUT` and `CANCELLED` are both terminal."

    Design: Corner/calculations/escort_requirement_is_pinned_true_by_a_meet_me_cabinet_alone
    """
    scenario = fx.setup_visit_scenery(
        api,
        row={"escort_slot_count": 2},
        cabinet={"footprint_type": "MEET_ME"},
        access_level="UNESCORTED",
        enrolled=False,
    )

    visit = validate_success(
        api.create_access_visit(
            f.create_access_visit_payload(
                scenario.contract_id,
                scenario.contact["id"],
                scenario.cabinet_id,
                "2026-08-01T09:00:00Z",
                "2026-08-01T11:00:00Z",
                purpose="MAINTENANCE",
            ),
            security_officer_headers,
        ),
        expected_status=201,
    )

    ax.assert_access_visit(visit)
    assert visit["escort_required"] is True, (
        "a MEET_ME cabinet alone pins escort_required true, "
        "even for an UNESCORTED contact on a MAINTENANCE visit"
    )
    assert visit["status"] == "SCHEDULED", f"new visits open SCHEDULED, got {visit['status']}"


# ---------------------------------------------------------------------------
# Period bounds
# ---------------------------------------------------------------------------


def test_billing_close_over_a_non_advancing_period_is_refused(api, billing_operator_headers):
    """PRD §3.9: "Closing a period is exclusive to a `BillingOperator`, requires the contract to be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE` otherwise), and carries the `period_start` and `period_end` of the period being closed, with the end strictly after the start (`ERR_BILLING_PERIOD_INVALID` otherwise)."
    PRD §2.5: "`period_end` is strictly after `period_start`, a metered interval's `interval_end` is after its `interval_start`, and every work segment's `ended_at` is greater than or equal to its `started_at`, otherwise `ERR_BILLING_PERIOD_INVALID` (422)."
    PRD §3.1: "A newly created contract opens in `DRAFT` with `credit_hold` false, `remote_hands_remaining_minutes` initialised to `remote_hands_included_minutes`, every rollup field (`provisioned_power_kw`, `stranded_commit_kw`, `commit_utilization_pct`, `active_cross_connect_count`, `billed_total_usd`, `cross_connect_billed_usd`) at zero and `last_closed_period_end` unset."

    Design: Corner/validations/billing_close_over_a_non_advancing_period_is_refused
    """
    scenario = fx.setup_active_contract(api, contract={"power_commit_kw": 10.0})

    validate_error(
        api.close_billing_period(
            scenario.contract_id,
            f.billing_close_payload("2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
            billing_operator_headers,
        ),
        ApiErrorId.ERR_BILLING_PERIOD_INVALID,
    )

    contract = fx.read_contract(api, scenario.contract_id)
    assert contract["last_closed_period_end"] is None, (
        "a refused close must leave last_closed_period_end unset"
    )
    ax.assert_contract_billing_rollup(contract, billed_total_usd=0.00)

    lines, meta = validate_paginated(
        api.list_invoice_lines(
            billing_operator_headers, params={"contract_id": scenario.contract_id}
        )
    )
    assert meta["total_count"] == 0, f"a refused close appends no lines, got {lines}"
