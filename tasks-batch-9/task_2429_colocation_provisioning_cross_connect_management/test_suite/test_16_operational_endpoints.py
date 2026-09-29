"""Operational endpoints and same-request consistency.

The logical clock, the credit-hold toggle, row re-limiting and the append-only meter
stream are the four operations that touch the system without moving any lifecycle,
and the two consistency cases prove that a cascade's derived figures are readable on
the very next request.
"""

from datetime import datetime, timezone

from test_helpers import assertions as ax, factories as f, fixtures as fx
from test_helpers import ENGINEER_1, FACILITY_MANAGER, validate_paginated, validate_success


# --- local helpers ---------------------------------------------------------


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp regardless of how many fractional digits it
    carries, so an instant is compared as an instant."""
    assert isinstance(value, str), f"expected an ISO 8601 timestamp, got {value!r}"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def assert_instant_equals(actual, expected: str, label: str) -> None:
    assert actual is not None, f"{label} must be present"
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------


def test_clock_set_drives_later_timestamps_and_rewrites_nothing_already_stored(
    api, billing_operator_headers, security_officer_headers, facility_manager_headers
):
    """PRD §2.4: "An operator-facing capability sets that clock to a supplied `current_utc` instant, and every subsequent timestamp, deadline comparison, quarantine expiry and window test uses the new value."
    PRD §2.4: "Setting the clock mutates no entity; it only changes what later writes observe."
    PRD §3.7: "Enrolling stamps `enrolled_at` from the logical clock."

    Design: Corner/endpoints/clock_endpoint_echoes_the_logical_now_and_mutates_no_entity
    """
    fx.set_clock(api)
    customer = fx.create_customer(api)
    contact = fx.create_contact(
        api, customer["id"], authorization_scopes=["SITE_ACCESS"], access_level="UNESCORTED"
    )
    assert contact["biometric_state"] == "NOT_ENROLLED", (
        f"a new contact starts NOT_ENROLLED, got {contact['biometric_state']}"
    )

    # Moving the clock is itself a mutation of nothing at all.
    validate_success(api.set_clock("2026-09-15T12:00:00Z", billing_operator_headers))

    enrolled = validate_success(
        api.set_contact_biometric_state(
            contact["id"], f.state_payload("ENROLLED"), security_officer_headers
        )
    )
    assert enrolled["biometric_state"] == "ENROLLED", (
        f"biometric_state: expected ENROLLED, got {enrolled['biometric_state']}"
    )
    assert_instant_equals(
        enrolled["enrolled_at"], "2026-09-15T12:00:00Z", "contact.enrolled_at"
    )

    # The customer was written under the old clock and the new clock rewrote nothing.
    reread = validate_success(api.get_customer(customer["id"], facility_manager_headers))
    assert_instant_equals(reread["created_at"], "2026-08-01T00:00:00Z", "customer.created_at")


# ---------------------------------------------------------------------------
# The credit-hold toggle
# ---------------------------------------------------------------------------


def test_credit_hold_toggle_writes_only_the_flag(api, billing_operator_headers):
    """PRD §3.1: "Setting or clearing the hold is a separate `BillingOperator` capability that writes the `credit_hold` flag from the request body and nothing else: existing orders, tickets and visits are never retro-actively cancelled when a hold goes on."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/endpoints/credit_hold_toggle_flips_the_flag_without_changing_contract_status
    """
    scenario = fx.setup_active_contract(api, contract={"power_commit_kw": 20.0})
    contract_id = scenario.contract_id

    held = validate_success(
        api.set_credit_hold(contract_id, {"credit_hold": True}, billing_operator_headers)
    )
    assert held["credit_hold"] is True, f"credit_hold: expected True, got {held['credit_hold']}"
    assert held["status"] == "ACTIVE", (
        f"raising the hold implies no lifecycle move; status became {held['status']}"
    )

    cleared = validate_success(
        api.set_credit_hold(contract_id, {"credit_hold": False}, billing_operator_headers)
    )
    assert cleared["credit_hold"] is False, (
        f"credit_hold: expected False, got {cleared['credit_hold']}"
    )
    assert cleared["status"] == "ACTIVE", (
        f"clearing the hold implies no lifecycle move; status became {cleared['status']}"
    )

    cabinets, _meta = validate_paginated(
        api.list_cabinets(billing_operator_headers, params={"contract_id": contract_id})
    )
    assert len(cabinets) == 1, f"expected the contract's one cabinet, got {len(cabinets)}"
    assert cabinets[0]["status"] == "RESERVED", (
        f"the hold cancelled provisioned space: cabinet is {cabinets[0]['status']}"
    )


# ---------------------------------------------------------------------------
# Re-limiting a live row
# ---------------------------------------------------------------------------


def test_row_relimit_recomputes_every_ceiling_and_increments_the_version(api):
    """PRD §3.2: "Re-limiting recomputes the row's whole capacity picture, which means `row_status` can flip — in either direction — without a single cabinet or circuit having changed, and the row's `version` increments on every such adjustment."
    PRD §3.2: "`density_ceiling_kw` is the design density multiplied by the number of occupied slots, rounded to three decimals — a row engineered at 8 kW per cabinet with five occupied slots carries a ceiling of 40 kW, and that ceiling grows and shrinks with occupancy rather than with the row's physical slot count."
    PRD §3.2: "`effective_ceiling_kw` is the smallest of three numbers: the busway limit `max_row_power_kw`, the density ceiling just derived, and the cooling capacity."
    PRD §3.2: "The **nameplate view**, `stranded_nameplate_kw`, is the effective ceiling minus `allocated_power_kw`, rounded to three decimals: it charges the row for every breaker plate that has been energized, so a lightly loaded cabinet with a large breaker strands nothing at all."

    Design: Corner/endpoints/row_repricing_recomputes_ceilings_and_bumps_the_row_version
    """
    scenario = fx.setup_reserved_cabinet(
        api,
        row={"design_density_kw_per_cabinet": 10.0, "max_row_power_kw": 200.0, "cooling_capacity_kw": 60.0},
        contract={"committed_cabinet_count": 2, "power_commit_kw": 40.0},
        cabinet={"cabinet_code": "C01"},
    )
    fx.add_reserved_cabinet(api, scenario, cabinet_code="C02")

    before = fx.read_row(api, scenario.row_id)
    ax.assert_row_capacity_view(
        before,
        occupied_slot_count=2,
        density_ceiling_kw=20.000,
        effective_ceiling_kw=20.000,
        stranded_nameplate_kw=20.000,
    )
    version_before = before["version"]

    denser = validate_success(
        api.update_row(
            scenario.row_id,
            f.update_row_payload(design_density_kw_per_cabinet=30.0),
            FACILITY_MANAGER,
        )
    )
    ax.assert_row_capacity_view(
        denser,
        occupied_slot_count=2,
        density_ceiling_kw=60.000,
        effective_ceiling_kw=60.000,
        stranded_nameplate_kw=60.000,
        row_status="OPEN",
    )

    cooler = validate_success(
        api.update_row(
            scenario.row_id, f.update_row_payload(cooling_capacity_kw=15.0), FACILITY_MANAGER
        )
    )
    ax.assert_row_capacity_view(
        cooler,
        occupied_slot_count=2,
        density_ceiling_kw=60.000,
        effective_ceiling_kw=15.000,
        stranded_nameplate_kw=15.000,
        row_status="OPEN",
    )

    assert cooler["version"] == version_before + 2, (
        f"row.version: expected {version_before + 2} after two adjustments, got {cooler['version']}"
    )


# ---------------------------------------------------------------------------
# The append-only meter stream
# ---------------------------------------------------------------------------


def test_meter_readings_are_retained_in_append_order_and_refresh_the_measured_view(
    api, billing_operator_headers
):
    """PRD §3.4: "Intervals are retained in the order they were appended, in the circuit's `meter_intervals` collection, and an interval whose `interval_end` is not after its `interval_start` is refused with `ERR_BILLING_PERIOD_INVALID`."
    PRD §3.4: "Appending a reading recomputes the host row's `measured_peak_kw` and therefore its `stranded_measured_kw`, which is how a row's measured stranded capacity can change without any electrical work taking place."
    PRD §3.2: "The **measured view**, `stranded_measured_kw`, is the effective ceiling minus `measured_peak_kw`, rounded to three decimals, where `measured_peak_kw` is the largest `peak_kw` recorded across the meter intervals of the row's circuits whose `interval_start` falls at or after 30 days before the logical clock, and is 0 when the trailing window holds no interval at all."

    Design: Corner/endpoints/meter_readings_are_appended_in_request_order_and_refresh_the_measured_view
    """
    scenario = fx.setup_reserved_cabinet(
        api,
        row={"design_density_kw_per_cabinet": 25.0, "max_row_power_kw": 200.0, "cooling_capacity_kw": 60.0},
        contract={"committed_cabinet_count": 1, "power_commit_kw": 20.0},
        cabinet={"cabinet_code": "C01"},
    )
    circuit = fx.add_designed_circuit(api, scenario, circuit_code="A-1")
    assert circuit["status"] == "DESIGNED", (
        f"a new circuit opens DESIGNED, got {circuit['status']}"
    )

    # Deliberately out of chronological order: the stream records arrival order.
    for interval_start, interval_end, peak_kw in (
        ("2026-07-25T00:00:00Z", "2026-07-26T00:00:00Z", 7.0),
        ("2026-07-15T00:00:00Z", "2026-07-16T00:00:00Z", 11.0),
        ("2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z", 4.0),
    ):
        validate_success(
            api.append_meter_reading(
                circuit["id"],
                f.meter_reading_payload(interval_start, interval_end, 100.0, peak_kw),
                billing_operator_headers,
            ),
            expected_status=201,
        )

    stored = fx.read_circuit(api, circuit["id"])["meter_intervals"]
    assert len(stored) == 3, f"expected three retained intervals, got {len(stored)}"
    assert [ax.round_half_up(i["peak_kw"], 3) for i in stored] == [
        ax.round_half_up(7.0, 3),
        ax.round_half_up(11.0, 3),
        ax.round_half_up(4.0, 3),
    ], f"meter_intervals must keep append order, got {[i['peak_kw'] for i in stored]}"

    row = fx.read_row(api, scenario.row_id)
    ax.assert_kw_equals(row["measured_peak_kw"], 11.000, "row.measured_peak_kw")
    ax.assert_row_capacity_view(
        row,
        effective_ceiling_kw=25.000,
        stranded_measured_kw=14.000,
        stranded_nameplate_kw=25.000,
    )


# ---------------------------------------------------------------------------
# Same-request consistency
# ---------------------------------------------------------------------------


def test_energization_rollups_are_readable_on_the_next_request(api, billing_operator_headers):
    """PRD §2.8: "The rule is that a cascade runs to completion inside the same request, in a fixed inside-out order — the circuit first, then its cabinet, then the cabinet's row, then any cabinets and circuits the row's new posture affects, and finally the contract's rollups — and every entity the cascade touches has its `updated_at` refreshed and its `version` incremented, exactly as if a client had written to it."
    PRD §3.4: "The cabinet's `allocated_power_kw`, `cooling_load_kw` and `energized_primary_circuit_count` are recomputed, and the cabinet advances `INSTALLED` → `ACTIVE` when its primary count moved from zero to one."
    PRD §3.4: "`provisioned_power_kw` is the sum of `allocated_kw` over circuits that are both `ENERGIZED` and `PRIMARY` on cabinets whose `contract_id` is this contract, rounded to three decimals."
    PRD §3.4: "`commit_utilization_pct` is the provisioned figure divided by `power_commit_kw`, multiplied by 100 and rounded to one decimal place."

    Design: Corner/consistency_model/energization_is_visible_in_every_rollup_within_the_same_request_cycle
    """
    scenario = fx.setup_approved_circuit(
        api,
        row={"design_density_kw_per_cabinet": 25.0, "max_row_power_kw": 200.0, "cooling_capacity_kw": 60.0},
        contract={"committed_cabinet_count": 1, "power_commit_kw": 20.0},
        cabinet={"cabinet_code": "C01", "rated_power_kw": 20.0},
        circuit={"circuit_code": "A-1", "breaker_amps": 50, "volts": 240, "phase": "SINGLE"},
    )
    row_version = fx.row_version(api, scenario.row_id)

    energized = validate_success(
        api.energize_circuit(
            scenario.circuit_id, {"expected_row_version": row_version}, ENGINEER_1
        )
    )
    ax.assert_circuit_power(
        energized,
        status="ENERGIZED",
        derated_kw=9.600,
        allocated_kw=9.600,
        cooling_contribution_kw=9.600,
    )
    assert_instant_equals(
        energized["energized_at"], "2026-08-01T00:00:00Z", "circuit.energized_at"
    )

    cabinet = fx.read_cabinet(api, scenario.cabinet_id)
    ax.assert_cabinet_power(
        cabinet,
        status="ACTIVE",
        allocated_power_kw=9.600,
        cooling_load_kw=9.600,
        energized_primary_circuit_count=1,
    )

    row = fx.read_row(api, scenario.row_id)
    ax.assert_row_capacity_view(
        row,
        energized_cabinet_count=1,
        allocated_power_kw=9.600,
        cooling_load_kw=9.600,
        density_ceiling_kw=25.000,
        effective_ceiling_kw=25.000,
        stranded_nameplate_kw=15.400,
        row_status="OPEN",
    )

    contract = validate_success(api.get_contract(scenario.contract_id, billing_operator_headers))
    ax.assert_contract_power_rollup(
        contract,
        provisioned_power_kw=9.600,
        stranded_commit_kw=10.400,
        commit_utilization_pct=48.0,
    )


def test_closed_period_lines_are_listable_on_the_next_request(api, billing_operator_headers):
    """PRD §3.9: "When the close completes, `last_closed_period_end` is set to the supplied `period_end` and `billed_total_usd` and `cross_connect_billed_usd` are refreshed."
    PRD §3.9: "Power billing begins with the committed charge, which is `power_commit_kw` multiplied by the standing rate of 175.00 USD per contracted kilowatt per month, rounded to two decimals."
    PRD §3.9: "Two lines may result, in this order: a `POWER_COMMIT` line whose `amount_usd` is the committed charge and whose `quantity` is `power_commit_kw`, always; and a `POWER_OVERAGE` line whose `amount_usd` is the overage charge and whose `quantity` is the overage energy, appended only when the overage energy is greater than zero."
    PRD §3.9: "Overage energy is billable consumption minus `included_kwh`, rounded to three decimals and floored at zero, so consumption exactly equal to the allowance yields no overage at all."

    Design: Corner/consistency_model/closed_period_invoice_lines_are_queryable_immediately
    """
    scenario = fx.setup_active_contract(
        api,
        contract={
            "billing_mode": "METERED_PLUS_COMMIT",
            "committed_cabinet_count": 1,
            "power_commit_kw": 20.0,
        },
        cabinet={"cabinet_code": "C01"},
    )
    contract_id = scenario.contract_id

    closed = validate_success(
        api.close_billing_period(
            contract_id,
            f.billing_close_payload("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"),
            billing_operator_headers,
        )
    )
    ax.assert_contract_billing_rollup(
        closed, billed_total_usd=3500.00, cross_connect_billed_usd=0.00
    )
    assert_instant_equals(
        closed["last_closed_period_end"],
        "2026-08-01T00:00:00Z",
        "contract.last_closed_period_end",
    )

    lines, meta = validate_paginated(
        api.list_invoice_lines(billing_operator_headers, params={"contract_id": contract_id})
    )
    assert meta["total_count"] == 1, (
        f"the close appended exactly one line; total_count is {meta['total_count']}"
    )
    assert len(lines) == 1, f"expected one ledger row, got {len(lines)}"
    ax.assert_invoice_line(lines[0])
    ax.assert_invoice_line_values(
        lines[0], line_type="POWER_COMMIT", amount_usd=3500.00, quantity=20.0
    )

    reread = validate_success(api.get_contract(contract_id, billing_operator_headers))
    ax.assert_contract_billing_rollup(
        reread, billed_total_usd=3500.00, cross_connect_billed_usd=0.00
    )
    assert_instant_equals(
        reread["last_closed_period_end"],
        "2026-08-01T00:00:00Z",
        "contract.last_closed_period_end",
    )
