"""Difficulty-design coverage — priority queue from
SCAFFOLD_DIFFICULTY_DESIGN.yaml.

Each scaffold_difficulty_design[*].instances[*] is covered by at least
two tests tagged ``# difficulty: <rule_id>/<instance.name>``. Citations
trace to PRD prose for the underlying rule (PRD-First).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    build_user_headers,
    compile_report,
    create_active_project,
    create_activity_data,
    create_approved_factor,
    create_credit,
    create_facility,
    create_factor_draft,
    create_organization,
    create_project,
    create_report,
    create_reporting_period,
    create_source,
    retire_credit,
    setup_compilable_report,
    setup_completeness_dataset,
    setup_credit_lifecycle_dataset,
    setup_dual_scope2_dataset,
    setup_equity_share_two_facility_dataset,
    setup_one_source_one_factor,
    setup_org_facility_period,
    setup_period_close_cascade_dataset,
    setup_supersession_cascade_dataset,
    validate_error,
    validate_success,
)


# =============================================================================
# Rule 1 — dual_variant_calc
# =============================================================================

# difficulty: dual_variant_calc/scope2_location_vs_market_on_report
def test_scope2_location_and_market_subtotals_differ_for_same_activity(api):
    """PRD §3.7: "For identical underlying activity data the two scope-2
    subtotals can differ strictly for identical underlying activity data
    — the report carries both."
    PRD §3.7: "gross_scope2_location_kg_co2e is the sum across SCOPE_2
    records whose scope2_method is LOCATION_BASED, gross_scope2_market_kg_co2e
    is the sum across SCOPE_2 records whose scope2_method is MARKET_BASED."
    """
    base = setup_dual_scope2_dataset(
        quantity_kwh=10000.0000,
        location_kg_per_unit=0.500000,
        market_kg_per_unit=0.200000,
    )
    report = create_report(base["org"]["id"], base["period"]["id"])
    rep = compile_report(base["org"]["id"], report["id"])
    # 10000 * 0.5 * 1 = 5000.0 ; 10000 * 0.2 * 1 = 2000.0
    assert float(rep["gross_scope2_location_kg_co2e"]) == pytest.approx(5000.0000, abs=1e-4)
    assert float(rep["gross_scope2_market_kg_co2e"]) == pytest.approx(2000.0000, abs=1e-4)


# difficulty: dual_variant_calc/scope2_location_vs_market_on_report
def test_dual_scope2_endpoint_returns_delta_between_variants(
        api, data_steward_headers):
    """PRD §3.7: "The report exposes a dual-scope-2 readout that returns
    three numbers — net_with_location_scope2 (computed by substituting
    gross_scope2_location_kg_co2e for the market-based subtotal in the
    canonical net formula), net_with_market_scope2 (the canonical net),
    and delta_kg_co2e (the location-based net minus the market-based
    net) — for compliance teams that need both views."
    """
    base = setup_dual_scope2_dataset(
        quantity_kwh=10000.0000,
        location_kg_per_unit=0.500000,
        market_kg_per_unit=0.200000,
    )
    report = create_report(base["org"]["id"], base["period"]["id"])
    compile_report(base["org"]["id"], report["id"])
    res = api.get_report_dual_scope2(
        base["org"]["id"], report["id"], data_steward_headers,
    )
    data = validate_success(res)
    # No offsets, no scope1/3 → net_with_location = 5000, net_with_market = 2000
    assert float(data["net_with_location_scope2"]) == pytest.approx(5000.0000, abs=1e-4)
    assert float(data["net_with_market_scope2"]) == pytest.approx(2000.0000, abs=1e-4)
    assert float(data["delta_kg_co2e"]) == pytest.approx(3000.0000, abs=1e-4)


# difficulty: dual_variant_calc/equity_share_vs_financial_control_on_facility
def test_equity_share_consolidation_weights_scope1_by_ownership(api):
    """PRD §3.7: "under EQUITY_SHARE, the weight is the facility's
    ownership_share_pct divided by 100."
    PRD §3.7: "For identical facility rows, switching the approach can
    flip included_in_boundary from true to false and produce a strictly
    different scope-1 total."

    Under EQUITY_SHARE, a 30% facility weights its contribution at 0.30,
    so identical activity data produces 0.30x the scope-1 of a
    FINANCIAL_CONTROL org of the same data.
    """
    org = create_organization(
        consolidation_approach="EQUITY_SHARE",
        materiality_threshold_pct=0.00,
    )
    fac = create_facility(
        org["id"], ownership_share_pct=30.00,
        financial_control=True, operational_control=False,
    )
    period = create_reporting_period(org["id"])
    factor, src = setup_one_source_one_factor(
        org, fac, kg_per_unit=1.000000, gas_type="CO2",
    )
    create_activity_data(
        org["id"], period["id"], src["id"], quantity=1000.0,
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    report = create_report(org["id"], period["id"])
    rep = compile_report(org["id"], report["id"])
    # 1000 * 1.0 * 1 * 0.30 = 300.0000
    assert float(rep["gross_scope1_kg_co2e"]) == pytest.approx(300.0000, abs=1e-4)


# difficulty: dual_variant_calc/equity_share_vs_financial_control_on_facility
def test_financial_control_weight_is_one_for_controlled_facility(api):
    """PRD §3.7: "under FINANCIAL_CONTROL, the weight is 1 when the
    facility's financial_control flag is true and 0 otherwise."

    Identical 1000-quantity activity under FINANCIAL_CONTROL produces
    1000 kg_co2e, vs 300 kg_co2e under EQUITY_SHARE at 30% ownership.
    The two approaches produce strictly different gross_scope1 for the
    same Facility row.
    """
    org = create_organization(
        consolidation_approach="FINANCIAL_CONTROL",
        materiality_threshold_pct=0.00,
    )
    fac = create_facility(
        org["id"], ownership_share_pct=30.00,
        financial_control=True, operational_control=False,
    )
    period = create_reporting_period(org["id"])
    factor, src = setup_one_source_one_factor(
        org, fac, kg_per_unit=1.000000, gas_type="CO2",
    )
    create_activity_data(
        org["id"], period["id"], src["id"], quantity=1000.0,
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    report = create_report(org["id"], period["id"])
    rep = compile_report(org["id"], report["id"])
    # 1000 * 1.0 * 1 * 1.0 = 1000.0000
    assert float(rep["gross_scope1_kg_co2e"]) == pytest.approx(1000.0000, abs=1e-4)


# =============================================================================
# Rule 2 — combinatorial_formula
# =============================================================================

# difficulty: combinatorial_formula/emission_record_three_input_nonlinear_formula
def test_n2o_record_uses_gwp_265_three_input_product(api,
                                                    data_steward_headers):
    """PRD §3.5: "kg_co2e is the quantity from the activity row
    multiplied by the pinned factor's kg_per_unit multiplied by the
    GWP value, with the final result rounded half up to four decimal
    places."
    PRD §3.5: "gwp_factor is the GWP-100 value for that gas
    (CO2 = 1, CH4 = 28, N2O = 265, ...)."

    For N2O at 500 quantity × 0.001 kg_per_unit × 265 GWP:
        kg_co2e = round_half_up(500 * 0.001 * 265, 4) = 132.5000.
    """
    org, fac, period = setup_org_facility_period(materiality_threshold_pct=0.00)
    factor, src = setup_one_source_one_factor(
        org, fac, category="PROCESS", gas_type="N2O", kg_per_unit=0.001000,
    )
    act = create_activity_data(
        org["id"], period["id"], src["id"], quantity=500.0000,
        activity_start="2025-06-15T00:00:00.000Z",
        activity_end="2025-07-15T00:00:00.000Z",
    )
    res = api.list_emission_records(
        org["id"], period["id"], data_steward_headers, params={"limit": 100},
    )
    rec = next(r for r in res.json()["data"]
               if r["activity_data_id"] == act["id"])
    assert rec["gwp_factor"] == 265
    assert float(rec["kg_co2e"]) == pytest.approx(132.5000, abs=1e-4)


# difficulty: combinatorial_formula/emission_record_three_input_nonlinear_formula
def test_factor_pinning_selects_active_by_effective_from(api,
                                                        data_steward_headers,
                                                        factor_manager_headers):
    """PRD §3.5: "the server picks the EmissionFactor whose code equals
    the source's factor_code, whose status is ACTIVE, whose
    effective_from is less than or equal to activity_start."

    Approve v1 effective 2025-01-01; post activity at 2025-06-15 — the
    pinning picks v1 and the kg_co2e reflects v1.kg_per_unit.
    """
    org, fac, period = setup_org_facility_period(materiality_threshold_pct=0.00)
    code = "PIN-N2O"
    v1 = create_approved_factor(
        org["id"], code=code, gas_type="N2O", kg_per_unit=0.001000,
        effective_from="2025-01-01T00:00:00.000Z",
    )
    src = create_source(
        org["id"], fac["id"], category="PROCESS", gas_type="N2O",
        factor_code=code,
    )
    act = create_activity_data(
        org["id"], period["id"], src["id"], quantity=500.0000,
        activity_start="2025-06-15T00:00:00.000Z",
        activity_end="2025-07-15T00:00:00.000Z",
    )
    res = api.list_emission_records(
        org["id"], period["id"], data_steward_headers, params={"limit": 100},
    )
    rec = next(r for r in res.json()["data"]
               if r["activity_data_id"] == act["id"])
    assert rec["emission_factor_id"] == v1["id"], (
        "EmissionRecord must pin the v1 factor whose effective_from <= "
        "activity_start (PRD §3.5)"
    )


# difficulty: combinatorial_formula/report_compile_round_per_subtotal_then_sum
def test_report_compile_rounds_per_facility_subtotal_then_sums(api):
    """PRD §3.7: "The four gross subtotals are computed by accumulating
    contributions per facility-scope combination, rounding each
    per-facility-scope subtotal half up to four decimal places, then
    summing the rounded subtotals — explicitly not round-once-at-end."

    Two EQUITY_SHARE facilities at 33.33% and 66.67%, each with 100.0001
    activity quantity × kg_per_unit 1.0 × GWP 1:
      per-facility A contribution = 100.0001 * 0.3333  = 33.33003333
        → round_half_up to 4dp                          = 33.3300
      per-facility B contribution = 100.0001 * 0.6667  = 66.67006667
        → round_half_up to 4dp                          = 66.6701
      Report.gross_scope1 = 33.3300 + 66.6701           = 100.0001
    """
    base = setup_equity_share_two_facility_dataset(
        ownership_a=33.33, ownership_b=66.67,
        quantity_a=100.0001, quantity_b=100.0001,
        kg_per_unit=1.000000,
    )
    report = create_report(base["org"]["id"], base["period"]["id"])
    rep = compile_report(base["org"]["id"], report["id"])
    assert float(rep["gross_scope1_kg_co2e"]) == pytest.approx(100.0001, abs=1e-4)


# difficulty: combinatorial_formula/report_compile_round_per_subtotal_then_sum
def test_report_compile_pinned_totals_have_at_most_four_decimals(api):
    """PRD §2.6: "The pinned report totals — gross_scope1_kg_co2e,
    gross_scope2_location_kg_co2e, gross_scope2_market_kg_co2e,
    gross_scope3_kg_co2e, applied_offsets_kg_co2e, net_emissions_kg_co2e,
    ... are also rounded half up to four decimal places."
    """
    base = setup_equity_share_two_facility_dataset(
        ownership_a=33.33, ownership_b=66.67,
        quantity_a=100.0001, quantity_b=100.0001,
        kg_per_unit=1.000000,
    )
    report = create_report(base["org"]["id"], base["period"]["id"])
    rep = compile_report(base["org"]["id"], report["id"])
    # The 4dp invariant: value * 10000 should be an integer (within fp noise)
    for field in ("gross_scope1_kg_co2e", "gross_scope2_location_kg_co2e",
                  "gross_scope2_market_kg_co2e", "gross_scope3_kg_co2e",
                  "applied_offsets_kg_co2e", "net_emissions_kg_co2e"):
        v = float(rep[field])
        scaled = v * 10000
        assert abs(scaled - round(scaled)) < 1e-6, (
            f"{field}={v} must carry at most four decimal places (PRD §2.6)"
        )


# =============================================================================
# Rule 3 — non_linear_state_machine
# =============================================================================

# difficulty: non_linear_state_machine/report_review_cycle_with_revert
def test_report_request_revisions_then_reopen_clears_pinned_totals(
        api, data_steward_headers, verifier_headers):
    """PRD §3.7: "From REVISIONS_REQUIRED, a DataSteward reopens it back
    to DRAFT, at which point compiled_at is cleared to null and every
    pinned total is reset to null."

    Compile pins totals → request-revisions → reopen clears them.
    """
    base = setup_compilable_report(materiality_threshold_pct=0.00)
    rep1 = compile_report(base["org"]["id"], base["report"]["id"])
    assert rep1["status"] == "UNDER_REVIEW"
    initial_net = rep1["net_emissions_kg_co2e"]
    assert initial_net is not None

    res_rr = api.request_revisions(
        base["org"]["id"], base["report"]["id"], verifier_headers,
    )
    rep2 = validate_success(res_rr)
    assert rep2["status"] == "REVISIONS_REQUIRED"

    res_ro = api.reopen_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    rep3 = validate_success(res_ro)
    assert rep3["status"] == "DRAFT"
    assert rep3["compiled_at"] is None
    assert rep3["net_emissions_kg_co2e"] is None


# difficulty: non_linear_state_machine/report_review_cycle_with_revert
def test_report_second_compile_re_pins_totals(api, data_steward_headers,
                                              verifier_headers):
    """PRD §3.7: After a reopen the report is in DRAFT; a subsequent
    compile pins the totals again. Re-entry into DRAFT is unbounded
    (PRD §3.7 — DRAFT→UNDER_REVIEW→REVISIONS_REQUIRED→DRAFT cycle)."""
    base = setup_compilable_report(materiality_threshold_pct=0.00)
    rep1 = compile_report(base["org"]["id"], base["report"]["id"])
    api.request_revisions(
        base["org"]["id"], base["report"]["id"], verifier_headers,
    )
    api.reopen_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    rep2 = compile_report(base["org"]["id"], base["report"]["id"])
    assert rep2["status"] == "UNDER_REVIEW"
    assert rep2["compiled_at"] is not None
    assert rep2["gross_scope1_kg_co2e"] == rep1["gross_scope1_kg_co2e"]


# difficulty: non_linear_state_machine/carbon_credit_branching_terminal
def test_credit_branches_to_retired_terminal(api, discloser_headers):
    """PRD §3.6: "On a successful retire, retired_at is set to the
    current server time."

    PURCHASED→RETIRED branch is one of two mutually exclusive terminal
    states (the other being TRANSFERRED).
    """
    base = setup_credit_lifecycle_dataset()
    from test_helpers import retire_credit_payload
    res = api.retire_credit(
        base["org"]["id"], base["credit_a"]["id"],
        retire_credit_payload(), discloser_headers,
    )
    data = validate_success(res)
    assert data["status"] == "RETIRED"
    assert data["retired_at"] is not None


# difficulty: non_linear_state_machine/carbon_credit_branching_terminal
def test_credit_branches_to_transferred_terminal(api, discloser_headers):
    """PRD §3.6: "Alternatively, a Discloser may transfer a credit out,
    moving it from PURCHASED to TRANSFERRED."

    PURCHASED→TRANSFERRED branch is the second mutually exclusive
    terminal state. retired_at remains null (vs RETIRED branch where
    it is set), demonstrating divergent side-effect sets.
    """
    base = setup_credit_lifecycle_dataset()
    res = api.transfer_credit(
        base["org"]["id"], base["credit_b"]["id"], discloser_headers,
    )
    data = validate_success(res)
    assert data["status"] == "TRANSFERRED"
    assert data["retired_at"] is None


# =============================================================================
# Rule 4 — transitive_cascade
# =============================================================================

# difficulty: transitive_cascade/factor_approve_cascade_depth_3
def test_factor_approve_three_hop_cascade(api, factor_manager_headers,
                                          data_steward_headers):
    """PRD §3.4: "On a successful approval, the predecessor (if any)
    transitions from ACTIVE to SUPERSEDED and its effective_to is set
    equal to the new version's effective_from."
    PRD §3.4: "Every EmissionRecord whose emission_factor_id equals the
    now-superseded row and whose parent ReportingPeriod is OPEN flips
    from FRESH to STALE."
    PRD §3.4: "Every Report whose status is DRAFT or UNDER_REVIEW and
    whose reporting_period_id lies among the affected periods flips to
    RECOMPUTE_REQUIRED."

    The three hops fire from one /factors/{id}/approve call.
    """
    base = setup_supersession_cascade_dataset()
    api.approve_factor(
        base["org"]["id"], base["factor_v2_draft"]["id"], factor_manager_headers,
    )
    # Hop 1: v1 SUPERSEDED with effective_to = v2.effective_from
    res_factors = api.list_factors(
        base["org"]["id"], factor_manager_headers,
        params={"code": base["factor_v1"]["code"], "limit": 100},
    )
    v1 = next(f for f in res_factors.json()["data"]
              if f["id"] == base["factor_v1"]["id"])
    assert v1["status"] == "SUPERSEDED"
    assert v1["effective_to"] == base["factor_v2_draft"]["effective_from"]
    # Hop 2: EmissionRecord STALE
    res_recs = api.list_emission_records(
        base["org"]["id"], base["period"]["id"], data_steward_headers,
        params={"limit": 100},
    )
    rec = next(r for r in res_recs.json()["data"]
               if r["activity_data_id"] == base["activity"]["id"])
    assert rec["status"] == "STALE"
    # Hop 3: Report RECOMPUTE_REQUIRED
    rep = api.get_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    ).json()["data"]
    assert rep["status"] == "RECOMPUTE_REQUIRED"


# difficulty: transitive_cascade/factor_approve_cascade_depth_3
def test_factor_cascade_originates_with_supersession_not_directly(
        api, factor_manager_headers, data_steward_headers):
    """PRD §3.4: hop 2 is caused by v1's supersession, not by approve
    directly: "Every EmissionRecord whose emission_factor_id equals the
    now-superseded row ... flips from FRESH to STALE."

    Approving a factor with a different code does NOT cascade to
    EmissionRecords pinned to a sibling code — they remain FRESH.
    """
    base = setup_supersession_cascade_dataset()
    # Create AND approve an UNRELATED factor code — should not fire cascade
    from test_helpers import create_approved_factor
    create_approved_factor(
        base["org"]["id"], code="UNRELATED-CODE", gas_type="CO2",
        kg_per_unit=1.000000,
        effective_from="2025-09-01T00:00:00.000Z",
    )
    res = api.list_emission_records(
        base["org"]["id"], base["period"]["id"], data_steward_headers,
        params={"limit": 100},
    )
    rec = next(r for r in res.json()["data"]
               if r["activity_data_id"] == base["activity"]["id"])
    assert rec["status"] == "FRESH", (
        "Unrelated factor approval must NOT cascade to existing records "
        "(PRD §3.4 — cascade is per code)"
    )


# difficulty: transitive_cascade/period_close_cascade_depth_3
def test_period_close_three_hop_cascade(api, data_steward_headers):
    """PRD §3.2: "Closing a period mass-archives every ActivityData row
    whose reporting_period_id matches (status RECORDED becomes
    ARCHIVED), then mass-archives every EmissionRecord of the period
    (both FRESH and STALE become ARCHIVED), and finally auto-transitions
    any Report still in DRAFT or UNDER_REVIEW for that period to
    REVISIONS_REQUIRED."

    The three hops fire from one /reporting-periods/{id}/close call.
    """
    base = setup_period_close_cascade_dataset()
    api.close_reporting_period(
        base["org"]["id"], base["period"]["id"], data_steward_headers,
    )
    # Hop 1: ActivityData ARCHIVED
    acts = api.list_activity_data(
        base["org"]["id"], base["period"]["id"], data_steward_headers,
        params={"limit": 100},
    ).json()["data"]
    assert all(a["status"] == "ARCHIVED" for a in acts)
    # Hop 2: EmissionRecord ARCHIVED
    recs = api.list_emission_records(
        base["org"]["id"], base["period"]["id"], data_steward_headers,
        params={"limit": 100},
    ).json()["data"]
    assert all(r["status"] == "ARCHIVED" for r in recs)
    # Hop 3: Report REVISIONS_REQUIRED
    rep = api.get_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    ).json()["data"]
    assert rep["status"] == "REVISIONS_REQUIRED"


# difficulty: transitive_cascade/period_close_cascade_depth_3
def test_period_close_originates_with_activity_archive_audit(
        api, data_steward_headers, platform_admin_headers):
    """PRD §3.2: "An AuditLog row with event_type ACTIVITY_ARCHIVE is
    appended."

    Close trigger appends exactly one ACTIVITY_ARCHIVE audit row,
    distinguishing this cascade origin from factor_approve (which logs
    FACTOR_APPROVE + FACTOR_SUPERSEDE).
    """
    base = setup_period_close_cascade_dataset()
    api.close_reporting_period(
        base["org"]["id"], base["period"]["id"], data_steward_headers,
    )
    res = api.list_audit_log(
        base["org"]["id"], platform_admin_headers,
        params={"event_type": "ACTIVITY_ARCHIVE", "limit": 100},
    )
    body = res.json()
    assert any(
        e["event_type"] == "ACTIVITY_ARCHIVE" for e in body["data"]
    ), "ACTIVITY_ARCHIVE audit row must be appended on period close (PRD §3.2)"


# =============================================================================
# Rule 5 — priority_pair_validation_conflict
# =============================================================================

# difficulty: priority_pair_validation_conflict/state_before_segregation_of_duties_on_verify
def test_verify_in_draft_returns_invalid_state_not_segregation(api):
    """PRD §2.8: "they are evaluated in a fixed order so that the most
    specific cause surfaces. The order is: (1) presence of both auth
    headers ...; (4) state precondition on the target resource —
    ERR_INVALID_STATE ...; (6) segregation of duties on report
    verification — ERR_SEGREGATION_OF_DUTIES."

    Priority 4 (state) fires before priority 6 (segregation of duties).
    When both would fail, ERR_INVALID_STATE wins.
    """
    shared_id = "shared-bad-user-001"
    steward = build_user_headers(shared_id, "DataSteward")
    verifier = build_user_headers(shared_id, "Verifier")
    # Build a DRAFT report — steward enters activity using user `shared_id`
    base = setup_compilable_report(
        materiality_threshold_pct=0.00, steward_headers=steward,
    )
    # report is in DRAFT (not UNDER_REVIEW); the verifier is the same id
    # that entered activity — both checks would fail; priority 4 wins.
    res = api.verify_report(
        base["org"]["id"], base["report"]["id"], verifier,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# difficulty: priority_pair_validation_conflict/state_before_segregation_of_duties_on_verify
def test_segregation_of_duties_fires_when_state_ok(api):
    """PRD §3.7: "the verifying user's X-User-ID must not equal the
    entered_by_user_id of any ActivityData row whose reporting_period_id
    matches the report's reporting period ... A violation surfaces as
    ERR_SEGREGATION_OF_DUTIES with HTTP 403."

    With the report in UNDER_REVIEW (state OK), the priority-6
    segregation check fires when verifier == steward.
    """
    shared_id = "shared-bad-user-002"
    steward = build_user_headers(shared_id, "DataSteward")
    verifier = build_user_headers(shared_id, "Verifier")
    base = setup_compilable_report(
        materiality_threshold_pct=0.00, steward_headers=steward,
    )
    # compile from a different user so the steward's id is captured on
    # ActivityData; compile itself is harmless for SoD.
    compile_report(base["org"]["id"], base["report"]["id"])
    res = api.verify_report(
        base["org"]["id"], base["report"]["id"], verifier,
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# difficulty: priority_pair_validation_conflict/temporal_before_referential_on_activity_data
def test_activity_outside_period_fires_before_no_factor(api,
                                                       data_steward_headers):
    """PRD §2.8: priority 9 (activity-data window inside reporting
    period — ERR_ACTIVITY_OUTSIDE_PERIOD); priority 12 (applicable
    factor exists — ERR_NO_APPLICABLE_FACTOR).

    When activity_start is outside the period AND no ACTIVE factor
    exists, priority 9 fires first.
    """
    from test_helpers import create_source_payload
    org, fac, period = setup_org_facility_period(
        period_start="2025-01-01T00:00:00.000Z",
        period_end="2026-01-01T00:00:00.000Z",
    )
    # Create a source with a factor code for which no factor exists.
    res_src = api.create_source(
        org["id"],
        create_source_payload(
            facility_id=fac["id"], category="STATIONARY_COMBUSTION",
            gas_type="CO2", factor_code="ORPHAN-CODE-NEVER-EXISTS",
        ),
        data_steward_headers,
    )
    src = res_src.json()["data"]
    from test_helpers import create_activity_data_payload
    # activity window OUTSIDE the period AND factor missing — temporal wins
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"], quantity=1.0,
            activity_start="2024-06-01T00:00:00.000Z",
            activity_end="2024-07-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_ACTIVITY_OUTSIDE_PERIOD.value)


# difficulty: priority_pair_validation_conflict/temporal_before_referential_on_activity_data
def test_no_factor_fires_when_temporal_ok(api, data_steward_headers):
    """PRD §3.5: "If no such factor exists, the request is rejected with
    ERR_NO_APPLICABLE_FACTOR."

    With activity_start INSIDE the period, the priority-12 referential
    check (no applicable factor) fires.
    """
    from test_helpers import create_source_payload, create_activity_data_payload
    org, fac, period = setup_org_facility_period(
        period_start="2025-01-01T00:00:00.000Z",
        period_end="2026-01-01T00:00:00.000Z",
    )
    res_src = api.create_source(
        org["id"],
        create_source_payload(
            facility_id=fac["id"], category="STATIONARY_COMBUSTION",
            gas_type="CO2", factor_code="ORPHAN-CODE-AGAIN",
        ),
        data_steward_headers,
    )
    src = res_src.json()["data"]
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"], quantity=1.0,
            activity_start="2025-03-01T00:00:00.000Z",
            activity_end="2025-04-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_NO_APPLICABLE_FACTOR.value)


# =============================================================================
# Rule 6 — boundary_precision_check
# =============================================================================

# difficulty: boundary_precision_check/completeness_pct_ge_threshold_on_compile
def test_completeness_passes_at_exact_threshold(api):
    """PRD §3.7: "completeness_passes is true when completeness_pct is
    greater than or equal to the threshold (the comparison is inclusive
    — >=, not strict >)."

    Boundary: 99/100 covered with materiality 1.0% ⇒ threshold 99.00 ⇒
    completeness_pct == 99.00 ⇒ passes is TRUE (inclusive).
    """
    base = setup_completeness_dataset(
        materiality_threshold_pct=1.00,
        identified_sources=100, covered_sources=99,
    )
    report = create_report(base["org"]["id"], base["period"]["id"])
    rep = compile_report(base["org"]["id"], report["id"])
    assert float(rep["completeness_pct"]) == pytest.approx(99.00, abs=1e-2)
    assert rep["completeness_passes"] is True


# difficulty: boundary_precision_check/completeness_pct_ge_threshold_on_compile
def test_completeness_fails_one_step_below_threshold(api):
    """PRD §3.7: ">=, not strict >" — at one step below threshold,
    completeness_passes is false.

    98/100 covered with materiality 1.0% ⇒ threshold 99.00 ⇒
    completeness_pct == 98.00 < 99.00 ⇒ passes is FALSE.
    """
    base = setup_completeness_dataset(
        materiality_threshold_pct=1.00,
        identified_sources=100, covered_sources=98,
    )
    report = create_report(base["org"]["id"], base["period"]["id"])
    rep = compile_report(base["org"]["id"], report["id"])
    assert float(rep["completeness_pct"]) == pytest.approx(98.00, abs=1e-2)
    assert rep["completeness_passes"] is False


# difficulty: boundary_precision_check/ownership_share_strict_gt_zero_on_equity_share
def test_equity_share_zero_excluded_even_with_financial_control(api):
    """PRD §3.1: "under EQUITY_SHARE, a facility is in boundary when its
    ownership_share_pct is strictly greater than zero — a facility with
    0.00 percent share is excluded even if financial_control is true."

    Boundary: ownership 0.00, financial_control true → excluded
    (strict '>').
    """
    org = create_organization(consolidation_approach="EQUITY_SHARE")
    fac = create_facility(
        org["id"], ownership_share_pct=0.00,
        financial_control=True, operational_control=True,
    )
    assert fac["included_in_boundary"] is False


# difficulty: boundary_precision_check/ownership_share_strict_gt_zero_on_equity_share
def test_equity_share_smallest_positive_share_included(api,
                                                      platform_admin_headers):
    """PRD §3.1: "strictly greater than zero" — 0.01% > 0.00% so the
    facility IS included. After PATCH down to 0.00 it must flip to
    excluded.
    """
    org = create_organization(consolidation_approach="EQUITY_SHARE")
    fac = create_facility(
        org["id"], ownership_share_pct=0.01,
        financial_control=True, operational_control=True,
    )
    assert fac["included_in_boundary"] is True
    res = api.update_facility(
        org["id"], fac["id"], {"ownership_share_pct": 0.00},
        platform_admin_headers,
    )
    updated = validate_success(res)
    assert updated["included_in_boundary"] is False


# =============================================================================
# Rule 7 — cross_entity_state_dependency
# =============================================================================

# difficulty: cross_entity_state_dependency/report_compile_depends_on_emission_record_freshness
def test_compile_blocked_by_single_stale_emission_record(
        api, data_steward_headers, factor_manager_headers):
    """PRD §3.7: "Compilation requires ... that no EmissionRecord for the
    period is in STALE status; either violation is rejected with
    ERR_INVALID_STATE."
    """
    base = setup_compilable_report(materiality_threshold_pct=0.00)
    # Approve a v2 factor → cascade FRESH→STALE on the pinned record
    v2 = create_factor_draft(
        base["org"]["id"], code=base["factor"]["code"], gas_type="CO2",
        kg_per_unit=2.0,
        effective_from="2025-08-01T00:00:00.000Z",
    )
    api.approve_factor(base["org"]["id"], v2["id"], factor_manager_headers)
    # Report is fresh DRAFT but the period now has a STALE record;
    # compile must fail with ERR_INVALID_STATE.
    res = api.compile_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# difficulty: cross_entity_state_dependency/report_compile_depends_on_emission_record_freshness
def test_compile_succeeds_when_no_stale_records(api, data_steward_headers):
    """PRD §3.7: "Compilation requires ... that no EmissionRecord for
    the period is in STALE status." With all records FRESH, compile
    succeeds.
    """
    base = setup_compilable_report(materiality_threshold_pct=0.00)
    res = api.compile_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    rep = validate_success(res)
    assert rep["status"] == "UNDER_REVIEW"


# difficulty: cross_entity_state_dependency/credit_retire_depends_on_reduction_project_state
def test_credit_retire_blocked_when_project_planned(api, discloser_headers):
    """PRD §3.6: "the linked reduction project must be in ACTIVE
    status ... the credit must currently be PURCHASED — otherwise the
    call is rejected with ERR_INVALID_STATE."
    """
    org, _fac, period = setup_org_facility_period()
    proj = create_project(
        org["id"], period["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=0.0,
    )
    # Project remains PLANNED
    credit = create_credit(
        org["id"], period["id"], proj["id"],
        quantity_kg_co2e=10.0, vintage_year=2024,
    )
    from test_helpers import retire_credit_payload
    res = api.retire_credit(
        org["id"], credit["id"], retire_credit_payload(), discloser_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# difficulty: cross_entity_state_dependency/credit_retire_depends_on_reduction_project_state
def test_credit_retire_succeeds_after_project_activated(api, discloser_headers):
    """PRD §3.6: "the linked reduction project must be in ACTIVE status."

    After moving the project PLANNED→ACTIVE, the same retire call
    succeeds.
    """
    org, _fac, period = setup_org_facility_period()
    proj = create_active_project(
        org["id"], period["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=0.0,
    )
    credit = create_credit(
        org["id"], period["id"], proj["id"],
        quantity_kg_co2e=10.0, vintage_year=2024,
    )
    from test_helpers import retire_credit_payload
    res = api.retire_credit(
        org["id"], credit["id"], retire_credit_payload(), discloser_headers,
    )
    data = validate_success(res)
    assert data["status"] == "RETIRED"


# =============================================================================
# Rule 8 — resource_temporal_overlap
# =============================================================================

# difficulty: resource_temporal_overlap/activity_data_half_open_overlap_on_source
def test_activity_data_overlap_strict_rejected(api, data_steward_headers):
    """PRD §3.5: "two activity rows of the same source must not overlap
    on their half-open intervals [activity_start, activity_end), and a
    second writer is rejected with ERR_ACTIVITY_INTERVAL_OVERLAP."
    """
    org, fac, period = setup_org_facility_period()
    factor, src = setup_one_source_one_factor(org, fac)
    create_activity_data(
        org["id"], period["id"], src["id"],
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    from test_helpers import create_activity_data_payload
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"],
            activity_start="2025-03-15T00:00:00.000Z",
            activity_end="2025-04-15T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_ACTIVITY_INTERVAL_OVERLAP.value)


# difficulty: resource_temporal_overlap/activity_data_half_open_overlap_on_source
def test_activity_data_touching_intervals_allowed(api, data_steward_headers):
    """PRD §3.5: half-open [activity_start, activity_end). Two records
    touching at the boundary do NOT overlap and the second writer
    succeeds with 201.
    """
    org, fac, period = setup_org_facility_period()
    factor, src = setup_one_source_one_factor(org, fac)
    create_activity_data(
        org["id"], period["id"], src["id"],
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    from test_helpers import create_activity_data_payload
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"],
            activity_start="2025-04-01T00:00:00.000Z",  # touches at boundary
            activity_end="2025-05-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    validate_success(res, expected_status=201)


# difficulty: resource_temporal_overlap/factor_effective_from_strict_order_per_code
def test_factor_effective_from_must_be_strictly_greater(api,
                                                       factor_manager_headers):
    """PRD §3.4: "The new version's effective_from must be strictly
    greater than the predecessor ACTIVE version's effective_from for
    the same code — zero-length windows and reverse-time approvals are
    rejected with ERR_FACTOR_EFFECTIVE_FROM_ORDER."
    """
    org = create_organization()
    v1 = create_approved_factor(
        org["id"], code="ORDER-STRICT",
        effective_from="2025-01-01T00:00:00.000Z",
    )
    v2_draft = create_factor_draft(
        org["id"], code="ORDER-STRICT",
        effective_from="2025-01-01T00:00:00.000Z",  # SAME — zero-length
    )
    res = api.approve_factor(
        org["id"], v2_draft["id"], factor_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_FACTOR_EFFECTIVE_FROM_ORDER.value)


# difficulty: resource_temporal_overlap/factor_effective_from_strict_order_per_code
def test_factor_approval_sets_predecessor_effective_to(api,
                                                      factor_manager_headers):
    """PRD §3.4: "The predecessor's effective_to is then auto-set equal
    to the new version's effective_from (adjacency-allowed, half-open
    chain)."

    Geometric distinction from ActivityData overlap: the chain
    forward-extends by setting effective_to on approval, not by
    requiring a second-row construction.
    """
    org = create_organization()
    v1 = create_approved_factor(
        org["id"], code="ADJACENCY-CHAIN",
        effective_from="2025-01-01T00:00:00.000Z",
    )
    v2_draft = create_factor_draft(
        org["id"], code="ADJACENCY-CHAIN",
        effective_from="2025-06-01T00:00:00.000Z",
    )
    api.approve_factor(org["id"], v2_draft["id"], factor_manager_headers)
    # v1 should now be SUPERSEDED with effective_to = v2.effective_from
    res = api.list_factors(
        org["id"], factor_manager_headers,
        params={"code": "ADJACENCY-CHAIN", "limit": 100},
    )
    body = res.json()
    v1_after = next(f for f in body["data"] if f["id"] == v1["id"])
    assert v1_after["status"] == "SUPERSEDED"
    assert v1_after["effective_to"] == "2025-06-01T00:00:00.000Z"


# =============================================================================
# Rule 9 — compensating_invariant
# =============================================================================

# difficulty: compensating_invariant/report_reopen_recompile_preserves_net_emissions
def test_reopen_recompile_preserves_net_when_underlying_unchanged(
        api, data_steward_headers, verifier_headers):
    """PRD §3.7: "From REVISIONS_REQUIRED, a DataSteward reopens it back
    to DRAFT, at which point compiled_at is cleared to null and every
    pinned total is reset to null."

    Forward (compile) and compensating (request-revisions + reopen +
    compile again) preserve net_emissions when no ActivityData /
    EmissionFactor / ReductionProject / CarbonCredit row changes in
    between.
    """
    base = setup_compilable_report(
        consolidation_approach="FINANCIAL_CONTROL",
        materiality_threshold_pct=0.00,
        kg_per_unit=2.687000, quantity=1000.0000,
    )
    rep1 = compile_report(base["org"]["id"], base["report"]["id"])
    net_initial = float(rep1["net_emissions_kg_co2e"])
    # 1000 * 2.687 * 1 * 1.0 = 2687.0000
    assert net_initial == pytest.approx(2687.0000, abs=1e-4)

    api.request_revisions(
        base["org"]["id"], base["report"]["id"], verifier_headers,
    )
    res_ro = api.reopen_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    reopened = validate_success(res_ro)
    assert reopened["net_emissions_kg_co2e"] is None

    rep2 = compile_report(base["org"]["id"], base["report"]["id"])
    assert float(rep2["net_emissions_kg_co2e"]) == pytest.approx(
        net_initial, abs=1e-4,
    )


# difficulty: compensating_invariant/report_reopen_recompile_preserves_net_emissions
def test_reopen_clears_compiled_at_and_pinned_totals(api,
                                                    data_steward_headers,
                                                    verifier_headers):
    """PRD §3.7: "compiled_at is cleared to null and every pinned total
    is reset to null."
    """
    base = setup_compilable_report(materiality_threshold_pct=0.00)
    rep1 = compile_report(base["org"]["id"], base["report"]["id"])
    assert rep1["compiled_at"] is not None
    api.request_revisions(
        base["org"]["id"], base["report"]["id"], verifier_headers,
    )
    res_ro = api.reopen_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    reopened = validate_success(res_ro)
    assert reopened["compiled_at"] is None
    # All scope subtotals reset to null
    for field in ("gross_scope1_kg_co2e", "gross_scope2_location_kg_co2e",
                  "gross_scope2_market_kg_co2e", "gross_scope3_kg_co2e",
                  "applied_offsets_kg_co2e", "net_emissions_kg_co2e"):
        assert reopened[field] is None, f"{field} must be null after reopen"


# difficulty: compensating_invariant/credit_transfer_preserves_applied_offsets
def test_credit_transfer_does_not_change_applied_offsets(
        api, data_steward_headers, discloser_headers, verifier_headers):
    """PRD §3.7: "The applied offsets are the sum of quantity_kg_co2e
    for every CarbonCredit whose status is RETIRED."

    PRD §3.6: "Alternatively, a Discloser may transfer a credit out,
    moving it from PURCHASED to TRANSFERRED."

    Since applied_offsets counts only RETIRED credits, a PURCHASED→
    TRANSFERRED transition of a never-retired credit leaves
    applied_offsets unchanged after recompile.
    """
    # Compile baseline: org + period + one retired credit C1 (=500)
    org, _fac, period = setup_org_facility_period(
        materiality_threshold_pct=0.00,
    )
    factor, src = setup_one_source_one_factor(org, _fac, kg_per_unit=1.0)
    create_activity_data(
        org["id"], period["id"], src["id"], quantity=100.0,
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    proj = create_active_project(
        org["id"], period["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=0.0,
    )
    c1 = create_credit(
        org["id"], period["id"], proj["id"],
        quantity_kg_co2e=500.0000, vintage_year=2024,
    )
    c2 = create_credit(
        org["id"], period["id"], proj["id"],
        quantity_kg_co2e=500.0000, vintage_year=2024,
    )
    retire_credit(org["id"], c1["id"])
    report = create_report(org["id"], period["id"])
    rep1 = compile_report(org["id"], report["id"])
    applied_before = float(rep1["applied_offsets_kg_co2e"])
    # c1 retired (500), c2 still PURCHASED ⇒ applied_offsets includes
    # only RETIRED → 500.0000.
    assert applied_before == pytest.approx(500.0000, abs=1e-4)

    # Transfer c2 — should NOT change applied_offsets after recompile.
    api.transfer_credit(org["id"], c2["id"], discloser_headers)
    api.request_revisions(org["id"], report["id"], verifier_headers)
    api.reopen_report(org["id"], report["id"], data_steward_headers)
    rep2 = compile_report(org["id"], report["id"])
    assert float(rep2["applied_offsets_kg_co2e"]) == pytest.approx(
        500.0000, abs=1e-4,
    ), "PURCHASED→TRANSFERRED of an un-retired credit must NOT change applied_offsets"


# difficulty: compensating_invariant/credit_transfer_preserves_applied_offsets
def test_credit_retire_vs_transfer_diverge_on_applied_offsets(
        api, data_steward_headers, discloser_headers, verifier_headers):
    """PRD §3.7: "the sum of quantity_kg_co2e for every CarbonCredit
    whose status is RETIRED."

    Control demonstration: retiring c2 (instead of transferring it)
    increases applied_offsets by c2.quantity. The PURCHASED→TRANSFERRED
    invariant is specific to TRANSFERRED, not RETIRED.
    """
    org, _fac, period = setup_org_facility_period(
        materiality_threshold_pct=0.00,
    )
    factor, src = setup_one_source_one_factor(org, _fac, kg_per_unit=1.0)
    create_activity_data(
        org["id"], period["id"], src["id"], quantity=100.0,
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    proj = create_active_project(
        org["id"], period["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=0.0,
    )
    c1 = create_credit(
        org["id"], period["id"], proj["id"],
        quantity_kg_co2e=500.0000, vintage_year=2024,
    )
    c2 = create_credit(
        org["id"], period["id"], proj["id"],
        quantity_kg_co2e=500.0000, vintage_year=2024,
    )
    retire_credit(org["id"], c1["id"])
    report = create_report(org["id"], period["id"])
    rep1 = compile_report(org["id"], report["id"])
    assert float(rep1["applied_offsets_kg_co2e"]) == pytest.approx(500.0000, abs=1e-4)

    # Retire (not transfer) c2 — should bump applied_offsets to 1000.0
    retire_credit(org["id"], c2["id"])
    api.request_revisions(org["id"], report["id"], verifier_headers)
    api.reopen_report(org["id"], report["id"], data_steward_headers)
    rep2 = compile_report(org["id"], report["id"])
    assert float(rep2["applied_offsets_kg_co2e"]) == pytest.approx(
        1000.0000, abs=1e-4,
    )
