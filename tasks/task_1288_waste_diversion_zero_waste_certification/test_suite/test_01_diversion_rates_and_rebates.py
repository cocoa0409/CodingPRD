"""Diversion-rate dual variants and rebate/cost-avoidance formulas (PRD §3.4, §3.7)."""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    setup_open_period_scenario, create_ticket, validate_ticket, create_audit,
    set_clock,
    TEST_USERS,
)

OFFICER = TEST_USERS["officer_headers"]


# ============================================================ dual_variant_calc

def _dv_scenario():
    """Shared setup: T1 RECYCLING 2000 VALIDATED; T2 RECYCLING 1000 PENDING;
    T3 LANDFILL 1000 VALIDATED."""
    site, vendor, contract, period = setup_open_period_scenario("Site DV")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=3000,
                       tare_weight_lbs=1000, external_ticket_ref="DV-T1")
    validate_ticket(t1["id"])
    create_ticket(site["id"], vendor["id"], contract["id"],
                  disposal_route="RECYCLING", gross_weight_lbs=2000,
                  tare_weight_lbs=1000, external_ticket_ref="DV-T2")
    t3 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="LANDFILL", gross_weight_lbs=2000,
                       tare_weight_lbs=1000, external_ticket_ref="DV-T3")
    validate_ticket(t3["id"])
    return site, vendor, contract, period


def test_provisional_rate_includes_pending_tickets(api):
    """PRD §3.4: "The provisional figures widen the set to include PENDING
    tickets alongside VALIDATED ones — REJECTED and VOIDED tickets are excluded
    from both sets — producing total_waste_lbs_provisional,
    diverted_lbs_provisional, and diversion_rate_provisional_pct by the same
    arithmetic."

    Design: Difficulty/dual_variant_calc/diversion_rate_provisional_vs_certified
    """
    site, vendor, contract, period = _dv_scenario()
    p = get_success_data(api.get_period(period["id"], OFFICER))
    assert p["total_waste_lbs_provisional"] == 4000
    assert p["diverted_lbs_provisional"] == 3000
    assert p["diversion_rate_provisional_pct"] == pytest.approx(75.00, abs=0.005)


def test_certified_rate_counts_validated_only(api):
    """PRD §3.4: "The certified figures cover the site's VALIDATED tickets whose
    ticket_date falls in the window: total_waste_lbs_validated sums their
    net_weight_lbs, and diverted_lbs_validated sums the same measure over
    tickets whose disposal_route is one of the three diverted routes —
    RECYCLING, COMPOSTING, or REUSE; LANDFILL and ENERGY_RECOVERY never count
    as diverted."

    Design: Difficulty/dual_variant_calc/diversion_rate_provisional_vs_certified
    """
    site, vendor, contract, period = _dv_scenario()
    p = get_success_data(api.get_period(period["id"], OFFICER))
    assert p["total_waste_lbs_validated"] == 3000
    assert p["diverted_lbs_validated"] == 2000
    assert p["diversion_rate_certified_pct"] == pytest.approx(66.67, abs=0.005)
    # The two variants diverge on identical underlying data.
    assert p["diversion_rate_provisional_pct"] != p["diversion_rate_certified_pct"]


def _rb_scenario():
    """T1 RECYCLING net 4000 pct 12 VALIDATED; audit reports stream pct 3."""
    site, vendor, contract, period = setup_open_period_scenario("Site RB")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=5000,
                       tare_weight_lbs=1000, contamination_pct=12,
                       external_ticket_ref="RB-T1")
    validate_ticket(t1["id"])
    audit = create_audit(site["id"], audit_date="2026-08-06", auditor_name="Aud A",
                         stream_findings=[{
                             "material_stream": "MIXED_RECYCLABLES",
                             "sampled_weight_lbs": 500,
                             "contamination_pct": 3,
                         }])
    return site, vendor, contract, period, audit


def test_rebate_estimate_uses_ticket_reported_contamination(api):
    """PRD §3.7: "the contamination percentage is the ticket's own
    contamination_pct, treated as 0 when absent. A quality factor scales the
    rebate: 1.0 when the percentage is below 5; 0.75 when it is at least 5 but
    below 10; 0.5 when it is at least 10. ... The penalty part applies only when
    the percentage is at least 10."

    Design: Difficulty/dual_variant_calc/rebate_estimate_vs_audit_settlement
    """
    site, vendor, contract, period, audit = _rb_scenario()
    p = get_success_data(api.get_period(period["id"], OFFICER))
    # 2t * 10000c * 0.5 - 2t * 2000c = 10000 - 4000 = 6000
    assert p["rebate_estimate_cents"] == 6000


def test_audit_adjusted_settlement_replaces_contamination(api):
    """PRD §3.7: "for each material stream, if a waste audit of the same site
    has an audit_date inside the period window and reports that stream in its
    stream_findings, the audit's contamination_pct replaces every such ticket's
    own percentage for that stream."

    Design: Difficulty/dual_variant_calc/rebate_estimate_vs_audit_settlement
    """
    site, vendor, contract, period, audit = _rb_scenario()
    closed = get_success_data(api.close_period(period["id"], OFFICER))
    assert closed["status"] == "CLOSED"
    # Audit pct 3 -> factor 1.0, no penalty: 2t * 10000c = 20000
    assert closed["rebate_settled_cents"] == 20000
    # The estimate field is preserved at its accrual-time value.
    assert closed["rebate_estimate_cents"] == 6000


# ============================================================ combinatorial_formula

def test_rebate_estimate_tiered_quality_factor_and_route_gate(api):
    """PRD §3.7: "A quality factor scales the rebate: 1.0 when the percentage
    is below 5; 0.75 when it is at least 5 but below 10; 0.5 when it is at
    least 10. ... The penalty part applies only when the percentage is at least
    10 ... LANDFILL and ENERGY_RECOVERY loads accrue zero: no rebate, no
    penalty."

    Design: Difficulty/combinatorial_formula/rebate_estimate_tiered_quality_factor
    """
    site, vendor, contract, period = setup_open_period_scenario("Site TQ")
    ta = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=5000,
                       tare_weight_lbs=1000, contamination_pct=4,
                       external_ticket_ref="TQ-TA")
    tb = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=5000,
                       tare_weight_lbs=1000, contamination_pct=12,
                       external_ticket_ref="TQ-TB")
    tc = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="LANDFILL", gross_weight_lbs=5000,
                       tare_weight_lbs=1000, external_ticket_ref="TQ-TC")
    for t in (ta, tb, tc):
        validate_ticket(t["id"])
    p = get_success_data(api.get_period(period["id"], OFFICER))
    # TA: 2t*10000*1.0 = 20000; TB: 2t*10000*0.5 - 2t*2000 = 6000; TC: 0
    assert p["rebate_estimate_cents"] == 26000


def test_rebate_estimate_landfill_route_contributes_zero(api):
    """PRD §3.7: "The per-ticket rebate estimate accrues when a ticket is
    validated, and only for diverted-route tickets — RECYCLING, COMPOSTING, or
    REUSE. LANDFILL and ENERGY_RECOVERY loads accrue zero: no rebate, no
    penalty."

    Design: Difficulty/combinatorial_formula/rebate_estimate_tiered_quality_factor
    """
    site, vendor, contract, period = setup_open_period_scenario("Site TQ2")
    t = create_ticket(site["id"], vendor["id"], contract["id"],
                      disposal_route="LANDFILL", gross_weight_lbs=5000,
                      tare_weight_lbs=1000, contamination_pct=15,
                      external_ticket_ref="TQ2-TC")
    validate_ticket(t["id"])
    p = get_success_data(api.get_period(period["id"], OFFICER))
    assert p["rebate_estimate_cents"] == 0


def test_cost_avoidance_rounds_per_ticket_then_sums(api):
    """PRD §3.7: "The rounding order is pinned: each ticket is rounded to cents
    first, and the period total is the sum of those rounded per-ticket amounts.
    Summing tonnage first and rounding once at the end produces a different
    total and is not the specified behavior."

    Design: Difficulty/combinatorial_formula/cost_avoidance_per_ticket_rounding
    """
    site, vendor, contract, period = setup_open_period_scenario("Site CA")
    for ref in ("CA-T1", "CA-T2", "CA-T3"):
        t = create_ticket(site["id"], vendor["id"], contract["id"],
                          disposal_route="RECYCLING", gross_weight_lbs=2,
                          tare_weight_lbs=1, external_ticket_ref=ref)
        validate_ticket(t["id"])
    closed = get_success_data(api.close_period(period["id"], OFFICER))
    # Per ticket: round_half_up(1/2000 * 5500) = round_half_up(2.75) = 3
    # Sum: 3 * 3 = 9 (sum-then-round would give round_half_up(8.25) = 8)
    assert closed["cost_avoided_cents"] == 9


def test_cost_avoidance_excludes_non_diverted_tickets(api):
    """PRD §3.7: "Cost avoidance, also computed at close and frozen into
    cost_avoided_cents, values each VALIDATED diverted-route ticket in the
    window at the landfill fee it avoided."

    Design: Difficulty/combinatorial_formula/cost_avoidance_per_ticket_rounding
    """
    site, vendor, contract, period = setup_open_period_scenario("Site CA2")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=3000,
                       tare_weight_lbs=1000, external_ticket_ref="CA2-T1")
    validate_ticket(t1["id"])
    t2 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="LANDFILL", gross_weight_lbs=5000,
                       tare_weight_lbs=1000, external_ticket_ref="CA2-T2")
    validate_ticket(t2["id"])
    closed = get_success_data(api.close_period(period["id"], OFFICER))
    # Only the RECYCLING ticket: round_half_up(2000/2000 * 5500) = 5500
    assert closed["cost_avoided_cents"] == 5500
