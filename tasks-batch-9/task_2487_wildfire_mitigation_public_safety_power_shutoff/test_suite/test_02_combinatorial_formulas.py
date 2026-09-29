"""Formulas whose factors cannot be dropped or reordered: the four-component index
blend with its hardening discount, the per-term ignition-risk rounding, and the
credit rate keyed on the unadjusted impact score."""

from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_4dp,
    assert_activation_summary,
    assert_center_state,
    assert_fpi,
    assert_fpi_components,
    assert_impact_counts,
    assert_integer,
    assert_net_benefit,
    assert_scope_counts,
    assert_scope_row,
)
from test_helpers.fixtures import (
    activate_centers,
    build_alpha_station_network,
    build_completed_hardening,
    build_feeder_chain,
    compute_index,
    file_observation,
    open_event,
    read_center,
    read_circuit,
    read_event,
    read_project,
    read_scope_rows,
    register_center,
    register_circuit,
    register_customer,
    register_station,
    scope_event,
)
from test_helpers.types import (
    ComputationVariant,
    CustomerClass,
    HftdTier,
    ProgramType,
    TelemetryStatus,
)


def _kilo_circuit_with_five_accounts():
    """KILO scores exactly 60.00 / R4 and serves one critical facility plus four
    medical-baseline households."""
    kilo = register_circuit(
        circuit_code="KILO",
        district_code="D-KILO",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=5.0,
        equipment_condition_index=80,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    station = register_station(
        kilo["id"],
        station_code="WS-K1",
        elevation_ft=1800,
        representativeness_weight=1.00,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    file_observation(
        station["id"],
        "2026-09-09T12:00:00Z",
        wind_gust_mph=52.0,
        relative_humidity_pct=62.0,
        temperature_f=92.0,
        dead_fuel_moisture_pct=9.0,
    )
    index = compute_index(kilo["id"], "2026-09-10", ComputationVariant.FORECAST.value)
    register_customer(
        kilo["id"],
        account_number="ACC-K1",
        customer_class=CustomerClass.CRITICAL_FACILITY.value,
        notification_channels=["VOICE"],
        address_zone_code="ZK",
    )
    for suffix in ("K2", "K3", "K4", "K5"):
        register_customer(
            kilo["id"],
            account_number=f"ACC-{suffix}",
            medical_baseline=True,
            notification_channels=["SMS"],
            address_zone_code="ZK",
        )
    return kilo, index


# --------------------------------------------------------------------------
# The four-component blend and the hardening discount
# --------------------------------------------------------------------------
def test_hardening_discount_drops_the_index_a_whole_tier():
    """4.0 covered-conductor miles on 7.0 overhead miles discount the identical weather
    from 85.93 / R5 down to 74.14 / R4.

    "`hardened_fraction_applied` snapshots the circuit's `hardened_fraction` at
    computation time, and the raw score is discounted by multiplying it by one minus 40
    percent of that snapshot — so a fully hardened circuit keeps 60 percent of its raw
    score, and mitigation can never discount a circuit's index below that floor."

    Design: Difficulty/combinatorial_formula/fpi_four_component_blend_with_hardening_discount_drops_tier
    """
    alpha = register_circuit(
        circuit_code="ALPHA",
        district_code="D-NORTH",
        hftd_tier=HftdTier.TIER_3.value,
        overhead_miles=7.0,
        equipment_condition_index=55,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    build_alpha_station_network(alpha["id"])
    project = build_completed_hardening(
        alpha["id"],
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=4.0,
        completion_date="2026-07-20T00:00:00Z",
        project_code="MP-CC-1",
        unit_cost_per_mile_cents=1250000,
    )

    hardened = read_circuit(alpha["id"])
    assert read_project(project["id"])["status"] == "COMPLETED"
    assert_1dp(hardened["covered_conductor_miles"], 4.0)
    assert_4dp(hardened["hardened_fraction"], 0.3429)

    index = compute_index(alpha["id"], "2026-08-15", ComputationVariant.FORECAST.value)

    assert_4dp(index["hardened_fraction_applied"], 0.3429)
    assert_fpi(index, 74.14, "R4")
    assert_2dp(read_circuit(alpha["id"])["latest_forecast_fpi_score"], 74.14)
    assert read_circuit(alpha["id"])["latest_forecast_fpi_tier"] == "R4"


def test_every_component_of_the_blend_is_published_alongside_the_score():
    """Wind 91.25, dryness 90.8, terrain 100 and equipment 45 are each visible, and the
    booked work package reports 3.72 risk reduction on a truncated 5,000,000-cent budget.

    "The raw score is the weighted sum of the four components with fixed weights: 35
    percent on the wind component, 30 percent on the dryness component, 20 percent on
    the terrain component, and 15 percent on the equipment component."

    Design: Difficulty/combinatorial_formula/fpi_four_component_blend_with_hardening_discount_drops_tier
    """
    alpha = register_circuit(
        circuit_code="ALPHA",
        district_code="D-NORTH",
        hftd_tier=HftdTier.TIER_3.value,
        overhead_miles=7.0,
        equipment_condition_index=55,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    build_alpha_station_network(alpha["id"])
    project = build_completed_hardening(
        alpha["id"],
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=4.0,
        completion_date="2026-07-20T00:00:00Z",
        project_code="MP-CC-1",
        unit_cost_per_mile_cents=1250000,
    )

    assert_2dp(project["risk_reduction_score"], 3.72)
    assert_integer(project["budget_cents"], 5000000)

    index = compute_index(alpha["id"], "2026-08-15", ComputationVariant.FORECAST.value)

    assert_fpi_components(index, wind=91.25, dryness=90.8, terrain=100, equipment=45)
    assert index["inspection_overdue"] is False
    assert_2dp(index["fpi_score"], 74.14)


# --------------------------------------------------------------------------
# The pinned order of the ignition-risk rounding
# --------------------------------------------------------------------------
def test_ignition_risk_sums_already_rounded_per_circuit_terms():
    """6.02 plus 5.16 plus 4.30 publishes 15.48 and never the 15.47 that a single final
    rounding would produce.

    "The ignition-risk score rounds **each per-circuit term** to two decimal places and
    then sums those already-rounded terms; it never sums at full precision and rounds
    once."

    Design: Difficulty/combinatorial_formula/ignition_risk_per_term_rounding_order_pinned
    """
    ctx = build_feeder_chain()
    event = open_event(ctx["fpi_forecast"]["id"])

    scoped = scope_event(event["id"], event["version"])

    rows = read_scope_rows(event["id"])
    assert_scope_row(rows, ctx["alpha"]["id"], ignition_risk_term=6.02)
    assert_scope_row(rows, ctx["bravo"]["id"], ignition_risk_term=5.16)
    assert_scope_row(rows, ctx["charlie"]["id"], ignition_risk_term=4.30)

    assert_2dp(scoped["ignition_risk_avoided_score"], 15.48)
    assert abs(scoped["ignition_risk_avoided_score"] - 15.47) > 0.005, (
        "summing at full precision and rounding once is not what this system publishes"
    )


def test_downstream_scope_rows_inherit_the_primary_risk_score():
    """The two dependants carry ALPHA's 85.93 and the basis that explains why they are
    dark.

    "A downstream row does not have its own qualifying index — it **inherits**
    `fpi_score_applied` from the nearest ancestor scope row whose `inclusion_basis` is
    `PRIMARY_RISK`, found by walking the feeder chain upward."

    Design: Difficulty/combinatorial_formula/ignition_risk_per_term_rounding_order_pinned
    """
    ctx = build_feeder_chain()
    event = open_event(ctx["fpi_forecast"]["id"])

    scoped = scope_event(event["id"], event["version"])

    assert scoped["scope_status"] == "SCOPED"
    assert_scope_counts(scoped, confirmed=3, excluded=0)
    assert_impact_counts(scoped, impacted=5, medical_baseline=1, critical_facility=1)

    rows = read_scope_rows(event["id"])
    assert_scope_row(
        rows,
        ctx["alpha"]["id"],
        scope_status="CONFIRMED",
        inclusion_basis="PRIMARY_RISK",
        fpi_score_applied=85.93,
    )
    assert_scope_row(
        rows,
        ctx["bravo"]["id"],
        scope_status="CONFIRMED",
        inclusion_basis="DOWNSTREAM_DEPENDENCY",
        fpi_score_applied=85.93,
    )
    assert_scope_row(
        rows,
        ctx["charlie"]["id"],
        scope_status="CONFIRMED",
        inclusion_basis="DOWNSTREAM_DEPENDENCY",
        fpi_score_applied=85.93,
    )


# --------------------------------------------------------------------------
# The credit rate keyed on the unadjusted score
# --------------------------------------------------------------------------
def test_credit_rate_is_read_from_the_unadjusted_impact_score():
    """An impact of 62.00 earns the 0.12 band and a 7.44 credit, not the 2.73 that
    re-deriving the rate from the adjusted 54.56 would give.

    "*Step two — the credit rate.* The rate is read from `customer_impact_score` as
    computed in step one, on four bands: a score below 20 earns a rate of 0.00, a score
    from 20 up to but not including 60 earns 0.05, a score from 60 up to but not
    including 200 earns 0.12, and a score of 200 or above earns 0.20."

    Design: Difficulty/combinatorial_formula/net_benefit_credit_rate_keyed_on_unadjusted_score
    """
    kilo, index = _kilo_circuit_with_five_accounts()
    register_center(
        resource_center_code="CRC-K1",
        district_code="D-KILO",
        site_capacity=10,
        accessibility_certified=True,
    )
    event = open_event(
        index["id"],
        onset_at="2026-09-10T00:00:00Z",
        all_clear_at="2026-09-10T20:00:00Z",
        event_code="EV-K",
    )
    scope_event(event["id"], event["version"])

    activate_centers(event["id"])

    scored = read_event(event["id"])
    assert_fpi(index, 60.00, "R4")
    assert_net_benefit(
        scored,
        duration_hours=20,
        customer_impact_score=62.00,
        crc_mitigation_credit=7.44,
        adjusted_customer_impact_score=54.56,
        ignition_risk_avoided_score=3.00,
        net_benefit_ratio=0.0550,
    )
    assert abs(scored["crc_mitigation_credit"] - 2.73) > 0.005, (
        "the credit rate must not be re-derived from the adjusted score"
    )


def test_selector_activation_reports_its_capacity_summary_and_stamps_the_site():
    """A single ten-place site covers the five required places and reports no unmet
    capacity.

    "The coverage ratio is `crc_capacity_served` divided by `crc_capacity_required`,
    where a required capacity of zero is treated as one to keep the division defined,
    and the quotient is capped at 1 so over-provisioning earns no extra credit."

    Design: Difficulty/combinatorial_formula/net_benefit_credit_rate_keyed_on_unadjusted_score
    """
    kilo, index = _kilo_circuit_with_five_accounts()
    center = register_center(
        resource_center_code="CRC-K1",
        district_code="D-KILO",
        site_capacity=10,
        accessibility_certified=True,
    )
    event = open_event(
        index["id"],
        onset_at="2026-09-10T00:00:00Z",
        all_clear_at="2026-09-10T20:00:00Z",
        event_code="EV-K",
    )
    scoped = scope_event(event["id"], event["version"])
    assert_integer(scoped["crc_capacity_required"], 5)

    summary = activate_centers(event["id"])

    assert_activation_summary(
        summary,
        activated_count=1,
        activated_capacity=10,
        unmet_capacity=0,
        activated_ids=[center["id"]],
    )
    assert_center_state(
        read_center(center["id"]),
        "ACTIVATED",
        activation_order=1,
        psps_event_id=event["id"],
    )
    assert_integer(read_event(event["id"])["crc_capacity_served"], 10)
