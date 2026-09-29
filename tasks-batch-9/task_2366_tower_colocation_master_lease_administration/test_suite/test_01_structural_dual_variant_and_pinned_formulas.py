"""Pinned arithmetic of the Tower Colocation Master Lease API.

This file covers the two-variant calculations and the formula orders PRD.md fixes
by hand: the PRELIMINARY versus DETAILED structural analysis of PRD §3.5, the
INSTALL_DATE_BASIS versus DISCOVERY_LIMITED retroactive billing of PRD §3.9, the
tiered equipment-line load ladder of PRD §3.4, the round-at-every-anniversary
site rent of PRD §3.7 and the seven-step modification cost pipeline of PRD §3.6.
"""

import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_amendment_axes,
    assert_analysis_outcome,
    assert_cents,
    assert_load_units,
    assert_occupied_band,
    assert_tenant_ledger,
    assert_tower_capacity,
)
from test_helpers.constants import DISCOUNT_TIER_2_PCT, RETRO_CAP_MONTHS
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    ENGINEER_HEADERS,
    make_tenant_headers,
)

# ─── Shared world builders (PRD §3.1 through §3.7) ───────────────────────────


def _issue_analysis(api, app_id, tower_id, variant):
    """Run one structural analysis, threading the tower version of PRD §2.11."""
    version = fixtures.read_tower_version(api, tower_id)
    return validate_success(
        api.create_structural_analysis(
            factories.structural_analysis_payload(app_id, version, variant), ENGINEER_HEADERS
        ),
        201,
    )


def _site_with_approved_pipeline_demand(api):
    """A tower carrying one APPROVED application plus one application in review.

    Rated capacity 7200 load units over a 3000-unit baseline, an ACTIVE ground
    lease and posture OPEN. Carrier BBB's application is APPROVED with 2500
    total load units, so PRD §3.5 counts it as pipeline demand while nothing of
    it stands on the structure. Carrier AAA's application carries 1600 total
    load units and sits in UNDER_STRUCTURAL_REVIEW.
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "T3 Summit",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 7200,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 20000,
            "baseline_reserved_load_units": 3000,
            "baseline_reserved_ground_sqft": 0,
        },
        landlord_overrides={
            "legal_name": "Summit Land LLC",
            "remit_contact_email": "pay@summit.example",
            "w9_on_file": True,
        },
    )
    tower = site["tower"]

    carrier_b = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Beta Mobility", "carrier_code": "BBB"},
        mla_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 2,
            "expires_on": "2036-07-31",
        },
    )
    app_b = fixtures.new_application(
        api,
        tower["id"],
        carrier_b["mla"]["id"],
        carrier_b["tenant"]["id"],
        requested_elevation_bottom_ft=100,
        requested_elevation_top_ft=140,
        requested_ground_space_sqft=400,
    )
    # 10 x 250 lbs with no wind area at 80 ft: tier-1 multiplier 1.00 (PRD §3.4).
    fixtures.add_equipment_line(
        api,
        app_b["id"],
        carrier_b["tenant"]["id"],
        equipment_type="ANTENNA",
        model_code="PX-250",
        quantity=10,
        unit_weight_lbs=250,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )
    fixtures.submit_application(api, app_b["id"], carrier_b["tenant"]["id"])
    fixtures.run_analysis(api, app_b["id"], tower["id"], "PRELIMINARY")
    fixtures.approve_application(api, app_b["id"])

    carrier_a = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Alpha Wireless", "carrier_code": "AAA"},
        mla_overrides={
            "base_monthly_rent_cents": 250000,
            "escalator_pct": 3.5,
            "initial_term_years": 10,
            "renewal_terms_count": 2,
            "expires_on": "2036-07-31",
            "expedited_review_days": 15,
        },
    )
    app_a = fixtures.new_application(
        api,
        tower["id"],
        carrier_a["mla"]["id"],
        carrier_a["tenant"]["id"],
        requested_elevation_bottom_ft=150,
        requested_elevation_top_ft=190,
        requested_ground_space_sqft=500,
    )
    fixtures.add_equipment_line(
        api,
        app_a["id"],
        carrier_a["tenant"]["id"],
        equipment_type="ANTENNA",
        model_code="PX-160",
        quantity=10,
        unit_weight_lbs=160,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )
    app_a = fixtures.submit_application(api, app_a["id"], carrier_a["tenant"]["id"])

    return {
        "tower": tower,
        "app_a": app_a,
        "app_b": app_b,
        "carrier_a": carrier_a,
        "carrier_b": carrier_b,
    }


# ─── PRD §3.5 — the dual-variant structural analysis ────────────────────────


def test_preliminary_screen_omits_pipeline_load_and_passes(api):
    """PRD §3.5: "For a `PRELIMINARY` desktop screen the pipeline term is zero, so reserved-but-unbuilt demand from other carriers is invisible and the same tower with the same equipment can pass."

    The base term is the tower's 3000 reserved load units and the subject term is
    the application's own 1600, so PRD §3.5 gives 4600 included load units and
    63.889 percent of the 7200-unit rating — at or below 95.000 percent, a PASS
    that leaves the application in UNDER_STRUCTURAL_REVIEW.

    Design: Difficulty/dual_variant_calc/structural_analysis_preliminary_vs_detailed_divergence_on_tower
    """
    world = _site_with_approved_pipeline_demand(api)

    preliminary = _issue_analysis(
        api, world["app_a"]["id"], world["tower"]["id"], "PRELIMINARY"
    )

    assert_analysis_outcome(
        preliminary,
        variant="PRELIMINARY",
        status="ISSUED",
        included_load_units=4600,
        projected_loading_pct=63.889,
        result="PASS",
    )
    application = validate_success(
        api.get_colocation_application(world["app_a"]["id"], ADMIN_HEADERS), 200
    )
    assert application["status"] == "UNDER_STRUCTURAL_REVIEW"
    tower = validate_success(api.get_tower(world["tower"]["id"], ADMIN_HEADERS), 200)
    assert_tower_capacity(
        tower, reserved_load_units=3000, open_review_count=1, capacity_posture="OPEN"
    )


def test_detailed_analysis_adds_approved_pipeline_load_and_requires_modification(api):
    """PRD §3.5: "For a `DETAILED` sealed analysis the pipeline term is the sum of `total_load_units` over every **other** application on the same tower whose `status` is `APPROVED` or `MODIFICATION_REQUIRED`, plus every other application on the tower whose `status` is `AMENDMENT_ISSUED` and whose site amendment has an `execution_status` of `DRAFT` or `PENDING_SIGNATURE`."

    The identical subject application on the identical tower now carries the
    APPROVED neighbour's 2500 units as well, so PRD §3.5 gives 3000 + 1600 +
    2500 = 7100 included load units, 98.611 percent of the 7200-unit rating and
    a MODIFICATION_REQUIRED result. The pipeline demand is contractual only, so
    the tower's own reserved load is untouched at 3000.

    Design: Difficulty/dual_variant_calc/structural_analysis_preliminary_vs_detailed_divergence_on_tower
    """
    world = _site_with_approved_pipeline_demand(api)

    detailed = _issue_analysis(api, world["app_a"]["id"], world["tower"]["id"], "DETAILED")

    assert_analysis_outcome(
        detailed,
        variant="DETAILED",
        status="ISSUED",
        included_load_units=7100,
        projected_loading_pct=98.611,
        result="MODIFICATION_REQUIRED",
    )
    tower = validate_success(api.get_tower(world["tower"]["id"], ADMIN_HEADERS), 200)
    assert_tower_capacity(
        tower, reserved_load_units=3000, rated_capacity_load_units=7200, occupied_band_count=0
    )


def test_detailed_result_supersedes_the_preliminary_and_leaves_review(api):
    """PRD §3.5: "A result of `MODIFICATION_REQUIRED` moves the application `UNDER_STRUCTURAL_REVIEW → MODIFICATION_REQUIRED`, decrements the tower's `open_review_count` by one, and recomputes `sla_breached`; this branch is only taken when the analysis just created is the only non-superseded analysis of the application."

    PRD §3.5 also says creating an analysis "sets every earlier analysis of the
    same application whose `status` is `ISSUED` or `QUOTED` to `SUPERSEDED`", so
    the passing PRELIMINARY screen is retired by the DETAILED one that follows
    it and the review slot the application held is given back.

    Design: Difficulty/dual_variant_calc/structural_analysis_preliminary_vs_detailed_divergence_on_tower
    """
    world = _site_with_approved_pipeline_demand(api)
    preliminary = _issue_analysis(
        api, world["app_a"]["id"], world["tower"]["id"], "PRELIMINARY"
    )

    detailed = _issue_analysis(api, world["app_a"]["id"], world["tower"]["id"], "DETAILED")

    retired = fixtures.read_analysis(api, world["app_a"]["id"], preliminary["id"])
    assert_analysis_outcome(retired, status="SUPERSEDED", result="PASS")
    assert_analysis_outcome(detailed, status="ISSUED", result="MODIFICATION_REQUIRED")
    application = validate_success(
        api.get_colocation_application(world["app_a"]["id"], ADMIN_HEADERS), 200
    )
    assert application["status"] == "MODIFICATION_REQUIRED"
    tower = validate_success(api.get_tower(world["tower"]["id"], ADMIN_HEADERS), 200)
    assert_tower_capacity(tower, open_review_count=0, capacity_posture="OPEN")


# ─── PRD §3.9 — the retroactive-billing basis ───────────────────────────────


def _tower_and_carrier_for_walk_down(api):
    """A tower and a zero-balance carrier for the compliance walk-down."""
    tower = fixtures.new_tower(
        api,
        site_name="T5 Mesa",
        structure_type="GUYED",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=40,
        max_elevation_ft=320,
        ground_space_total_sqft=15000,
    )
    tenant = fixtures.new_tenant(api, legal_name="Gamma Telecom", carrier_code="CCC")
    return tower, tenant


def _audit_with_one_finding(api, tower_id, tenant_id, basis, description):
    """One IN_PROGRESS audit dated 2026-07-31 carrying a single finding.

    The finding is 120 observed load units installed on 2023-02-15, which PRD
    §3.9 turns into a gross count of 41 whole months as of the audit date.
    """
    return fixtures.audit_with_findings(
        api,
        tower_id,
        [
            {
                "tenant_id": tenant_id,
                "description": description,
                "observed_load_units": 120,
                "installed_on_date": "2023-02-15",
                "mount_elevation_ft": 180,
            }
        ],
        audit_overrides={"audit_date": "2026-07-31", "basis": basis},
        finalize=False,
    )


def test_install_date_basis_bills_every_gross_month(api):
    """PRD §3.9: "Under `INSTALL_DATE_BASIS`, `months_billable` is the gross count outright, with no ceiling — an installation forty-one months old bills forty-one months."

    The monthly rate of PRD §3.9 is 25 cents per load unit, so 120 observed load
    units bill 3,000 cents a month; 41 months at that rate with the 1.5 penalty
    multiplier is 184,500 cents, and the finding moves OPEN → BILLED.

    Design: Difficulty/dual_variant_calc/retroactive_billing_install_date_vs_discovery_limited_on_tenant
    """
    tower, tenant = _tower_and_carrier_for_walk_down(api)
    walk_down = _audit_with_one_finding(
        api,
        tower["id"],
        tenant["id"],
        "INSTALL_DATE_BASIS",
        "Unpermitted 4-panel array on north leg",
    )

    audit = validate_success(
        api.finalize_equipment_audit(walk_down["audit"]["id"], {}, AUDITOR_HEADERS), 200
    )

    assert audit["status"] == "FINALIZED"
    assert_cents(
        audit["retroactive_billing_total_cents"], 184500, "retroactive_billing_total_cents"
    )
    finding = validate_success(
        api.get_audit_finding(walk_down["findings"][0]["id"], ADMIN_HEADERS), 200
    )
    assert finding["months_billable"] == 41
    assert_cents(finding["retroactive_billing_cents"], 184500, "retroactive_billing_cents")
    assert finding["status"] == "BILLED"
    carrier = validate_success(api.get_tenant(tenant["id"], ADMIN_HEADERS), 200)
    assert_tenant_ledger(carrier, outstanding_balance_cents=184500, credit_status="CURRENT")


def test_discovery_limited_basis_caps_the_same_finding_at_two_years(api):
    """PRD §3.9: "Under `DISCOVERY_LIMITED`, `months_billable` is the lesser of the gross count and a two-year ceiling of 24 months, so the identical finding against the identical carrier bills a strictly smaller amount whenever the gross count exceeds 24."

    The gross count is 41 months, so the ceiling bites: 24 months at the 3,000
    cent monthly rate with the 1.5 penalty multiplier of PRD §3.9 is 108,000
    cents rather than 184,500.

    Design: Difficulty/dual_variant_calc/retroactive_billing_install_date_vs_discovery_limited_on_tenant
    """
    tower, tenant = _tower_and_carrier_for_walk_down(api)
    walk_down = _audit_with_one_finding(
        api,
        tower["id"],
        tenant["id"],
        "DISCOVERY_LIMITED",
        "Unpermitted 4-panel array on south leg",
    )

    audit = validate_success(
        api.finalize_equipment_audit(walk_down["audit"]["id"], {}, AUDITOR_HEADERS), 200
    )

    assert audit["status"] == "FINALIZED"
    assert_cents(
        audit["retroactive_billing_total_cents"], 108000, "retroactive_billing_total_cents"
    )
    finding = validate_success(
        api.get_audit_finding(walk_down["findings"][0]["id"], ADMIN_HEADERS), 200
    )
    assert finding["months_billable"] == RETRO_CAP_MONTHS
    assert_cents(finding["retroactive_billing_cents"], 108000, "retroactive_billing_cents")
    assert finding["status"] == "BILLED"
    carrier = validate_success(api.get_tenant(tenant["id"], ADMIN_HEADERS), 200)
    assert_tenant_ledger(carrier, outstanding_balance_cents=108000, credit_status="CURRENT")


def test_both_bases_bill_the_same_carrier_and_the_balance_carries_both(api):
    """PRD §3.9: "Because the findings were billed, each affected tenant's `outstanding_balance_cents` is increased by that tenant's own finding total."

    The same carrier is caught twice with identical gear: 184,500 cents under
    INSTALL_DATE_BASIS and the strictly smaller 108,000 cents under
    DISCOVERY_LIMITED, so its balance lands on 292,500 cents, which PRD §2.12
    leaves CURRENT because it is below 5,000,000 cents.

    Design: Difficulty/dual_variant_calc/retroactive_billing_install_date_vs_discovery_limited_on_tenant
    """
    tower, tenant = _tower_and_carrier_for_walk_down(api)
    install_basis = _audit_with_one_finding(
        api,
        tower["id"],
        tenant["id"],
        "INSTALL_DATE_BASIS",
        "Unpermitted 4-panel array on north leg",
    )
    discovery_basis = _audit_with_one_finding(
        api,
        tower["id"],
        tenant["id"],
        "DISCOVERY_LIMITED",
        "Unpermitted 4-panel array on south leg",
    )

    install_audit = validate_success(
        api.finalize_equipment_audit(install_basis["audit"]["id"], {}, AUDITOR_HEADERS), 200
    )
    discovery_audit = validate_success(
        api.finalize_equipment_audit(discovery_basis["audit"]["id"], {}, AUDITOR_HEADERS), 200
    )

    assert_cents(install_audit["retroactive_billing_total_cents"], 184500, "install basis total")
    assert_cents(
        discovery_audit["retroactive_billing_total_cents"], 108000, "discovery basis total"
    )
    assert (
        discovery_audit["retroactive_billing_total_cents"]
        < install_audit["retroactive_billing_total_cents"]
    ), "the two-year ceiling must bill strictly less than the uncapped basis"
    carrier = validate_success(api.get_tenant(tenant["id"], ADMIN_HEADERS), 200)
    assert_tenant_ledger(carrier, outstanding_balance_cents=292500, credit_status="CURRENT")


# ─── PRD §3.4 — the tiered equipment-line load ladder ───────────────────────

_TIER_2_LINE = {
    "equipment_type": "ANTENNA",
    "model_code": "AX-60",
    "quantity": 3,
    "unit_weight_lbs": 60,
    "wind_area_sqft": 8,
    "mount_elevation_ft": 125,
}
_TIER_1_LINE = {
    "equipment_type": "RRU",
    "model_code": "RU-55",
    "quantity": 6,
    "unit_weight_lbs": 55,
    "wind_area_sqft": 2,
    "mount_elevation_ft": 95,
}
_TIER_3_LINE = {
    "equipment_type": "DISH",
    "model_code": "MW-20",
    "quantity": 4,
    "unit_weight_lbs": 20,
    "wind_area_sqft": 0.5,
    "mount_elevation_ft": 250,
}


def _draft_application_spanning_three_tiers(api):
    """A DRAFT application on a tower whose usable range spans all three tiers."""
    tower = fixtures.new_tower(
        api,
        site_name="T6 Bluff",
        structure_type="MONOPOLE",
        rated_capacity_load_units=12000,
        min_colocation_elevation_ft=40,
        max_elevation_ft=320,
        ground_space_total_sqft=18000,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Delta Networks", "carrier_code": "DDD"},
        mla_overrides={
            "base_monthly_rent_cents": 220000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    application = fixtures.new_application(
        api,
        tower["id"],
        carrier["mla"]["id"],
        carrier["tenant"]["id"],
        requested_elevation_bottom_ft=90,
        requested_elevation_top_ft=260,
        requested_ground_space_sqft=600,
    )
    return {"tower": tower, "carrier": carrier, "application": application}


def test_equipment_line_load_selects_its_elevation_tier_multiplier(api):
    """PRD §3.4: "A line's `load_units` is derived by first selecting an elevation multiplier from a strict three-tier ladder on `mount_elevation_ft`: below 100 feet the multiplier is 1.00; from 100 feet up to but not including 200 feet it is 1.25; at 200 feet and above it is 1.50."

    PRD §3.4 then says "The raw figure is then the sum of `unit_weight_lbs` and
    thirty times `wind_area_sqft` — thirty being the wind coefficient in pounds
    per square foot — multiplied by `quantity`, multiplied by the elevation
    multiplier." Three lines on one application therefore land in three
    different tiers: (60 + 240) x 3 x 1.25 = 1125, (55 + 60) x 6 x 1.00 = 690
    and (20 + 15) x 4 x 1.50 = 210.

    Design: Difficulty/combinatorial_formula/equipment_line_load_tiered_elevation_multiplier_mode_a
    """
    world = _draft_application_spanning_three_tiers(api)
    tenant_headers = make_tenant_headers(world["carrier"]["tenant"]["id"])
    app_id = world["application"]["id"]

    tier_2 = validate_success(
        api.create_equipment_line(
            app_id, factories.equipment_line_payload(**_TIER_2_LINE), tenant_headers
        ),
        201,
    )
    tier_1 = validate_success(
        api.create_equipment_line(
            app_id, factories.equipment_line_payload(**_TIER_1_LINE), tenant_headers
        ),
        201,
    )
    tier_3 = validate_success(
        api.create_equipment_line(
            app_id, factories.equipment_line_payload(**_TIER_3_LINE), tenant_headers
        ),
        201,
    )

    assert_load_units(tier_2["load_units"], 1125.0, "tier-2 line load_units")
    assert_load_units(tier_1["load_units"], 690.0, "tier-1 line load_units")
    assert_load_units(tier_3["load_units"], 210.0, "tier-3 line load_units")


def test_application_total_load_sums_the_already_rounded_line_figures(api):
    """PRD §3.4: "The application's `total_load_units` is the sum of the **already rounded** per-line figures, so each line is rounded to three decimals first and only then are the lines added together."

    The three tiers contribute 1125, 690 and 210 load units, so the application
    reports 2025 total load units while each line keeps its own figure.

    Design: Difficulty/combinatorial_formula/equipment_line_load_tiered_elevation_multiplier_mode_a
    """
    world = _draft_application_spanning_three_tiers(api)
    tenant_id = world["carrier"]["tenant"]["id"]
    app_id = world["application"]["id"]
    for line in (_TIER_2_LINE, _TIER_1_LINE, _TIER_3_LINE):
        fixtures.add_equipment_line(api, app_id, tenant_id, **line)

    application = validate_success(api.get_colocation_application(app_id, ADMIN_HEADERS), 200)

    assert_load_units(application["total_load_units"], 2025.0, "total_load_units")
    lines, _meta = validate_paginated(
        api.list_equipment_lines({"colocation_application_id": app_id, "limit": 100}, ADMIN_HEADERS)
    )
    assert len(lines) == 3
    assert sorted(float(line["load_units"]) for line in lines) == [210.0, 690.0, 1125.0]


# ─── PRD §3.7 — site rent compounding over already-rounded cents ────────────


def _papered_amendment_four_anniversaries_old(api):
    """A DRAFT amendment whose effective date is exactly four anniversaries back.

    The logical clock stands at its 2026-08-01 cold-start instant and the
    amendment is effective 2022-08-01 at 250,000 cents with a 3.5 percent
    escalator, so PRD §3.7 walks exactly four anniversaries.
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "T1 Ridge",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 10000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 20000,
            "baseline_reserved_load_units": 2000,
            "baseline_reserved_ground_sqft": 0,
        },
        landlord_overrides={
            "legal_name": "Ridge Land LLC",
            "remit_contact_email": "pay@ridge.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 400000,
            "escalator_pct": 2.5,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 2,
            "renewal_term_years": 5,
            "buyout_price_cents": 12000000,
        },
    )
    tower = site["tower"]
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Alpha Wireless", "carrier_code": "AAA"},
        mla_overrides={
            "base_monthly_rent_cents": 250000,
            "escalator_pct": 3.5,
            "initial_term_years": 10,
            "renewal_terms_count": 2,
            "expires_on": "2036-07-31",
            "expedited_review_days": 15,
        },
    )
    tenant_id = carrier["tenant"]["id"]
    application = fixtures.new_application(
        api,
        tower["id"],
        carrier["mla"]["id"],
        tenant_id,
        requested_elevation_bottom_ft=150,
        requested_elevation_top_ft=190,
        requested_ground_space_sqft=500,
    )
    for line in (_TIER_2_LINE, _TIER_1_LINE):
        fixtures.add_equipment_line(api, application["id"], tenant_id, **line)
    fixtures.submit_application(api, application["id"], tenant_id)
    analysis = fixtures.run_analysis(api, application["id"], tower["id"], "PRELIMINARY")
    fixtures.approve_application(api, application["id"])
    amendment = fixtures.paper_amendment(
        api,
        carrier["mla"]["id"],
        tower["id"],
        application["id"],
        effective_date="2022-08-01",
        term_end_date="2031-05-31",
        base_monthly_rent_cents=250000,
        escalator_pct=3.5,
        restoration_deposit_cents=0,
    )
    return {
        "tower": tower,
        "ground_lease": site["ground_lease"],
        "carrier": carrier,
        "application": application,
        "analysis": analysis,
        "amendment": amendment,
    }


def test_executed_amendment_rent_compounds_over_already_rounded_cents(api):
    """PRD §3.7: "For a base of 250,000 cents at an escalator of 3.5 percent across four anniversaries, the pinned per-anniversary order yields 286,880 cents, whereas the single-shot power form would yield 286,881; the implementation must produce 286,880."

    PRD §3.7 caps the figure at base rent times 1.50, which is 375,000 cents
    here, so the compounded 286,880 cents is the lesser figure and stands.

    Design: Difficulty/combinatorial_formula/amendment_rent_rounds_at_every_anniversary_mode_b
    """
    world = _papered_amendment_four_anniversaries_old(api)

    executed = validate_success(
        api.execute_site_amendment(
            world["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
        ),
        200,
    )

    assert_cents(executed["current_monthly_rent_cents"], 286880, "current_monthly_rent_cents")
    reread = validate_success(
        api.get_site_amendment(world["amendment"]["id"], ADMIN_HEADERS), 200
    )
    assert_cents(reread["current_monthly_rent_cents"], 286880, "current_monthly_rent_cents")


def test_execution_starts_billing_and_leaves_no_restoration_obligation(api):
    """PRD §3.7: "`restoration_status` is set to `PENDING` when `restoration_deposit_cents` is greater than zero, and to `NOT_REQUIRED` otherwise."

    Execution also moves the billing axis NOT_BILLING → BILLING per PRD §3.7,
    and because the deposit is zero the tenant's balance of PRD §2.12 is left
    at 0 cents and CURRENT.

    Design: Difficulty/combinatorial_formula/amendment_rent_rounds_at_every_anniversary_mode_b
    """
    world = _papered_amendment_four_anniversaries_old(api)

    executed = validate_success(
        api.execute_site_amendment(
            world["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
        ),
        200,
    )

    assert_amendment_axes(
        executed,
        execution_status="EXECUTED",
        billing_status="BILLING",
        restoration_status="NOT_REQUIRED",
    )
    carrier = validate_success(
        api.get_tenant(world["carrier"]["tenant"]["id"], ADMIN_HEADERS), 200
    )
    assert_tenant_ledger(carrier, outstanding_balance_cents=0, credit_status="CURRENT")


def test_executed_amendment_load_reconciles_onto_the_tower(api):
    """PRD §2.7: "`reserved_load_units` is `baseline_reserved_load_units` plus the sum of `reserved_load_units` over the contributing amendments."

    The amendment carries the application's 1815 total load units onto a tower
    whose baseline is 2000, giving 3815 reserved load units and, against the
    10000-unit rating, 38.150 percent. Its 500 square feet of compound space
    leave 19500 available, and the band it now occupies runs 150 to 190 feet.

    Design: Difficulty/combinatorial_formula/amendment_rent_rounds_at_every_anniversary_mode_b
    """
    world = _papered_amendment_four_anniversaries_old(api)
    assert_analysis_outcome(
        fixtures.read_analysis(api, world["application"]["id"], world["analysis"]["id"]),
        projected_loading_pct=38.15,
        result="PASS",
    )

    validate_success(
        api.execute_site_amendment(
            world["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
        ),
        200,
    )

    tower = validate_success(api.get_tower(world["tower"]["id"], ADMIN_HEADERS), 200)
    assert_tower_capacity(
        tower,
        reserved_load_units=3815.0,
        reserved_load_pct=38.15,
        reserved_ground_space_sqft=500,
        available_ground_space_sqft=19500,
        occupied_band_count=1,
        capacity_posture="OPEN",
    )
    assert_occupied_band(
        tower["occupied_elevation_bands"][0],
        amendment_id=world["amendment"]["id"],
        bottom_ft=150,
        top_ft=190,
        tenant_id=world["carrier"]["tenant"]["id"],
    )


# ─── PRD §3.6 — the pinned modification cost pipeline ───────────────────────


def _application_requiring_modification(api):
    """An application whose PRELIMINARY analysis lands just above the pass limit.

    The tower is rated 4000 load units over a 3000-unit baseline and the single
    equipment line contributes 800.1 units, so PRD §3.5 gives 3800.1 included
    load units, 95.003 percent and a MODIFICATION_REQUIRED result.
    """
    tower = fixtures.new_tower(
        api,
        site_name="T2 Crest",
        structure_type="SELF_SUPPORT",
        rated_capacity_load_units=4000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=10000,
        baseline_reserved_load_units=3000,
        baseline_reserved_ground_sqft=0,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Epsilon Cellular", "carrier_code": "EEE"},
        mla_overrides={
            "base_monthly_rent_cents": 240000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    tenant_id = carrier["tenant"]["id"]
    application = fixtures.new_application(
        api,
        tower["id"],
        carrier["mla"]["id"],
        tenant_id,
        requested_elevation_bottom_ft=100,
        requested_elevation_top_ft=140,
        requested_ground_space_sqft=400,
    )
    fixtures.add_equipment_line(
        api,
        application["id"],
        tenant_id,
        equipment_type="ANTENNA",
        model_code="QX-80",
        quantity=10,
        unit_weight_lbs=80.01,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )
    fixtures.submit_application(api, application["id"], tenant_id)
    return {"tower": tower, "carrier": carrier, "application": application}


def _quoted_project_on_that_analysis(api, world, analysis_id):
    """Quote the analysis at 22,400,000 cents and propose the reinforcement."""
    return fixtures.quoted_analysis_with_project(
        api,
        tower_id=world["tower"]["id"],
        analysis_id=analysis_id,
        cost_cents=22400000,
        project_overrides={
            "construction_window_start_date": "2026-09-01",
            "construction_window_end_date": "2026-10-31",
            "allocation_basis": "PRO_RATA_LOAD",
        },
    )


def test_loading_just_above_the_pass_limit_requires_modification(api):
    """PRD §3.5: "The `result` is then read off that rounded percentage against two limits: at or below 95.000 percent the result is `PASS`; above 95.000 percent but strictly below 100.000 percent the result is `MODIFICATION_REQUIRED`; at 100.000 percent or above the result is `CAPACITY_EXCEEDED`."

    A base of 3000 plus a subject of 800.1 against a 4000-unit rating is
    95.0025 percent, which PRD §2.10 rounds half up to 95.003 — above the pass
    limit, so the application leaves review for MODIFICATION_REQUIRED.

    Design: Difficulty/combinatorial_formula/modification_cost_pipeline_pins_discount_tier_mode_c
    """
    world = _application_requiring_modification(api)

    analysis = _issue_analysis(
        api, world["application"]["id"], world["tower"]["id"], "PRELIMINARY"
    )

    assert_analysis_outcome(
        analysis,
        included_load_units=3800.1,
        projected_loading_pct=95.003,
        result="MODIFICATION_REQUIRED",
        status="ISSUED",
    )
    application = validate_success(
        api.get_colocation_application(world["application"]["id"], ADMIN_HEADERS), 200
    )
    assert application["status"] == "MODIFICATION_REQUIRED"
    assert_load_units(application["total_load_units"], 800.1, "total_load_units")
    tower = validate_success(api.get_tower(world["tower"]["id"], ADMIN_HEADERS), 200)
    assert_tower_capacity(tower, open_review_count=0, reserved_load_units=3000)


def test_cost_pipeline_selects_the_discount_tier_from_the_pre_discount_total(api):
    """PRD §3.6: "Fourth, `volume_discount_pct` is selected **once** from that pre-discount total: it is 0.03 when the pre-discount total is at least 25,000,000 cents (250,000 dollars), otherwise 0.015 when the pre-discount total is at least 10,000,000 cents (100,000 dollars), otherwise 0; the tier is never re-derived from the post-discount total."

    A quoted construction cost of 22,400,000 cents carries a provisional
    twelve-percent fee of 2,688,000, so the pre-discount total is 25,088,000 and
    the 3 percent tier is selected. The discounted construction figure is
    22,400,000 less 672,000 = 21,728,000, and PRD §3.6 recomputes the fee from
    that discounted figure as 2,607,360, giving a total cost of 24,335,360 —
    not the 24,711,680 a re-derived 1.5 percent tier would produce.

    Design: Difficulty/combinatorial_formula/modification_cost_pipeline_pins_discount_tier_mode_c
    """
    world = _application_requiring_modification(api)
    analysis = _issue_analysis(
        api, world["application"]["id"], world["tower"]["id"], "PRELIMINARY"
    )
    project = _quoted_project_on_that_analysis(api, world, analysis["id"])["project"]

    allocated = validate_success(
        api.allocate_cost_shares(project["id"], {}, ENGINEER_HEADERS), 200
    )

    assert_cents(
        allocated["base_construction_cost_cents"], 22400000, "base_construction_cost_cents"
    )
    assert float(allocated["volume_discount_pct"]) == pytest.approx(DISCOUNT_TIER_2_PCT)
    assert_cents(allocated["engineering_fee_cents"], 2607360, "engineering_fee_cents")
    assert_cents(allocated["total_cost_cents"], 24335360, "total_cost_cents")
    assert_cents(allocated["allocated_cents"], 24335360, "allocated_cents")
    assert allocated["status"] == "COST_ALLOCATED"


def test_allocation_mints_one_pending_share_for_the_sole_beneficiary(api):
    """PRD §3.6: "Allocation mints one cost share per beneficiary in `status` `PENDING` and sets the project's `allocated_cents` to `total_cost_cents`."

    Nothing is executed on this tower, so the only beneficiary PRD §3.6
    resolves is the originating analysis's own application, sitting in
    MODIFICATION_REQUIRED. It therefore carries the whole 24,335,360 cent total,
    which is also the sum the project's `allocated_cents` reports.

    Design: Difficulty/combinatorial_formula/modification_cost_pipeline_pins_discount_tier_mode_c
    """
    world = _application_requiring_modification(api)
    analysis = _issue_analysis(
        api, world["application"]["id"], world["tower"]["id"], "PRELIMINARY"
    )
    project = _quoted_project_on_that_analysis(api, world, analysis["id"])["project"]

    validate_success(api.allocate_cost_shares(project["id"], {}, ENGINEER_HEADERS), 200)

    shares, _meta = validate_paginated(
        api.list_cost_shares({"modification_project_id": project["id"], "limit": 100}, ADMIN_HEADERS)
    )
    assert len(shares) == 1
    share = shares[0]
    assert share["tenant_id"] == world["carrier"]["tenant"]["id"]
    assert share["status"] == "PENDING"
    assert_cents(share["share_cents"], 24335360, "share_cents")
    reread = validate_success(api.get_modification_project(project["id"], ADMIN_HEADERS), 200)
    assert_cents(reread["allocated_cents"], 24335360, "allocated_cents")
    # PRD §3.6: "Allocation on its own does not change the tower's posture."
    tower = validate_success(api.get_tower(world["tower"]["id"], ADMIN_HEADERS), 200)
    assert_tower_capacity(tower, capacity_posture="OPEN", reserved_load_units=3000)
