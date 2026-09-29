"""Load, rent and billing arithmetic of the Tower Colocation Master Lease API.

Covers the pinned formulas and their rounding orders: the equipment-line
elevation ladder and the per-line-then-sum load rollup of PRD §3.4, the
dual-variant structural analysis and the review-time credit of PRD §3.5, the
simply-escalating ground rent and its per-month remittance of PRD §3.2, the
capped compounding site rent of PRD §3.7, the seven-step modification cost
pipeline and its floored cost-share allocation of PRD §3.6, the retroactive
whole-month billing of PRD §3.9, and the capacity posture boundaries of
PRD §2.7 and §2.8.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_amendment_axes,
    assert_analysis_outcome,
    assert_capacity_summary,
    assert_cents,
    assert_load_units,
    assert_pct,
    assert_tenant_ledger,
    assert_tower_capacity,
)
from test_helpers.constants import RESTRICTED_LOAD_PCT
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    ENGINEER_HEADERS,
    make_tenant_headers,
)

# ─── Equipment-line load (PRD §3.4) ──────────────────────────────────────────

TIER_BOUNDARY_LINES = (
    {
        "equipment_type": "ANTENNA",
        "model_code": "T1-50",
        "quantity": 1,
        "unit_weight_lbs": 50,
        "wind_area_sqft": 0,
        "mount_elevation_ft": 99,
    },
    {
        "equipment_type": "ANTENNA",
        "model_code": "T2-50",
        "quantity": 1,
        "unit_weight_lbs": 50,
        "wind_area_sqft": 0,
        "mount_elevation_ft": 100,
    },
    {
        "equipment_type": "ANTENNA",
        "model_code": "T3-50",
        "quantity": 1,
        "unit_weight_lbs": 50,
        "wind_area_sqft": 0,
        "mount_elevation_ft": 200,
    },
)


def _tier_boundary_application(api):
    """A tower, an ACTIVE master lease and one DRAFT application spanning 90..210 ft."""
    tower = fixtures.new_tower(
        api,
        site_name="Tier Edge Tower",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Tier Edge Telecom"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
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
        requested_elevation_top_ft=210,
        requested_ground_space_sqft=200,
    )
    return tower, carrier["tenant"], application


def test_equipment_line_multiplier_steps_up_at_exactly_one_hundred_and_two_hundred_feet(api):
    """PRD §3.4: "A line's `load_units` is derived by first selecting an elevation
    multiplier from a strict three-tier ladder on `mount_elevation_ft`: below 100
    feet the multiplier is 1.00; from 100 feet up to but not including 200 feet it
    is 1.25; at 200 feet and above it is 1.50."

    Design: Corner/calculations/equipment_line_tier_boundaries_at_exactly_100_and_200_ft
    """
    _tower, tenant, application = _tier_boundary_application(api)
    tenant_headers = make_tenant_headers(tenant["id"])

    below_the_step = validate_success(
        api.create_equipment_line(
            application["id"],
            factories.equipment_line_payload(**TIER_BOUNDARY_LINES[0]),
            tenant_headers,
        ),
        201,
    )
    on_the_first_step = validate_success(
        api.create_equipment_line(
            application["id"],
            factories.equipment_line_payload(**TIER_BOUNDARY_LINES[1]),
            tenant_headers,
        ),
        201,
    )
    on_the_second_step = validate_success(
        api.create_equipment_line(
            application["id"],
            factories.equipment_line_payload(**TIER_BOUNDARY_LINES[2]),
            tenant_headers,
        ),
        201,
    )

    # 50 lbs of gear with no wind area: 99 ft takes 1.00, 100 ft takes 1.25 and
    # 200 ft takes 1.50.
    assert_load_units(below_the_step["load_units"], 50.0, "load_units at 99 ft")
    assert_load_units(on_the_first_step["load_units"], 62.5, "load_units at 100 ft")
    assert_load_units(on_the_second_step["load_units"], 75.0, "load_units at 200 ft")


def test_application_total_load_sums_the_already_rounded_line_figures(api):
    """PRD §3.4: "The application's `total_load_units` is the sum of the **already
    rounded** per-line figures, so each line is rounded to three decimals first and
    only then are the lines added together."

    Design: Corner/calculations/equipment_line_tier_boundaries_at_exactly_100_and_200_ft
    """
    _tower, tenant, application = _tier_boundary_application(api)
    lines = [
        fixtures.add_equipment_line(api, application["id"], tenant["id"], **line)
        for line in TIER_BOUNDARY_LINES
    ]

    submitted = validate_success(
        api.submit_colocation_application(
            application["id"], {}, make_tenant_headers(tenant["id"])
        ),
        200,
    )

    # 50.0 + 62.5 + 75.0
    assert_load_units(submitted["total_load_units"], 187.5, "total_load_units")
    for line, expected in zip(lines, (50.0, 62.5, 75.0)):
        assert_load_units(
            fixtures.read_equipment_line(api, line["id"])["load_units"],
            expected,
            "load_units",
        )


# ─── The dual-variant structural analysis (PRD §3.5) ─────────────────────────


def test_detailed_analysis_pipeline_counts_approved_but_not_reviewing_siblings(api):
    """PRD §3.5: "For a `DETAILED` sealed analysis the pipeline term is the sum of
    `total_load_units` over every **other** application on the same tower whose
    `status` is `APPROVED` or `MODIFICATION_REQUIRED`, plus every other application
    on the tower whose `status` is `AMENDMENT_ISSUED` and whose site amendment has
    an `execution_status` of `DRAFT` or `PENDING_SIGNATURE`. Applications on the
    tower in `DRAFT`, `SUBMITTED`, `UNDER_STRUCTURAL_REVIEW`, `CAPACITY_HOLD`,
    `ON_HOLD`, `REJECTED` or `WITHDRAWN` are excluded from both variants."

    Design: Corner/calculations/detailed_analysis_pipeline_excludes_reviewing_applications
    """
    approved = fixtures.build_colocation_chain(
        api,
        stage="APPROVED",
        with_ground_lease=False,
        tower_overrides={
            "site_name": "Detailed Divide",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 400,
            "ground_space_total_sqft": 9000,
        },
        tenant_overrides={"legal_name": "Detailed Divide Radio"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 100,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "D1-80",
                "quantity": 5,
                "unit_weight_lbs": 80,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )
    tower, tenant, mla = approved["tower"], approved["tenant"], approved["mla"]

    reviewing_sibling = fixtures.build_colocation_chain(
        api,
        stage="SUBMITTED",
        tower=tower,
        tenant=tenant,
        mla=mla,
        application_overrides={
            "requested_elevation_bottom_ft": 200,
            "requested_elevation_top_ft": 240,
            "requested_ground_space_sqft": 100,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "D2-60",
                "quantity": 5,
                "unit_weight_lbs": 60,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )
    subject = fixtures.build_colocation_chain(
        api,
        stage="SUBMITTED",
        tower=tower,
        tenant=tenant,
        mla=mla,
        application_overrides={
            "requested_elevation_bottom_ft": 300,
            "requested_elevation_top_ft": 340,
            "requested_ground_space_sqft": 100,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "D3-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )

    analysis = validate_success(
        api.create_structural_analysis(
            factories.structural_analysis_payload(
                subject["application"]["id"],
                fixtures.read_tower_version(api, tower["id"]),
                "DETAILED",
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )

    # Base 0.0 standing on the structure, subject 500.0, pipeline 400.0 from the
    # APPROVED sibling only: 900.0 of 9000 rated units.
    assert_analysis_outcome(
        analysis,
        variant="DETAILED",
        included_load_units=900.0,
        projected_loading_pct=10.0,
        result="PASS",
        status="ISSUED",
    )
    assert (
        fixtures.read_application(api, reviewing_sibling["application"]["id"])["status"]
        == "UNDER_STRUCTURAL_REVIEW"
    )
    assert fixtures.read_application(api, approved["application"]["id"])["status"] == "APPROVED"
    assert_tower_capacity(fixtures.read_tower(api, tower["id"]), reserved_load_units=0.0)


# ─── The review-time commitment (PRD §3.5) ───────────────────────────────────


def _application_awaiting_analysis(api, site_name: str, tenant_name: str):
    """One submitted application whose 45-day review deadline is 2026-09-15T00:00:00Z."""
    chain = fixtures.build_colocation_chain(
        api,
        stage="SUBMITTED",
        with_ground_lease=False,
        tower_overrides={
            "site_name": site_name,
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        tenant_overrides={"legal_name": tenant_name},
        mla_overrides={
            "base_monthly_rent_cents": 250000,
            "escalator_pct": 3.5,
            "initial_term_years": 10,
            "renewal_terms_count": 2,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "SL-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )
    assert chain["application"]["review_deadline_at"].startswith("2026-09-15T00:00:00")
    return chain


def test_rent_credit_issued_when_analysis_is_issued_past_the_review_deadline(api):
    """PRD §3.5: "When a breach is detected and `sla_breached` was still `false`,
    `sla_breached` is set to `true` and a rent credit is issued: the credit is
    twenty-five percent of the master lease's `base_monthly_rent_cents`, rounded
    half up to whole cents, and that amount is subtracted from the tenant's
    `outstanding_balance_cents`, which may take the balance negative."

    Design: Corner/calculations/sla_credit_issued_when_analysis_lands_after_review_deadline
    """
    chain = _application_awaiting_analysis(api, "SLA Ridge", "SLA Ridge Wireless")
    tower, tenant, application = chain["tower"], chain["tenant"], chain["application"]
    fixtures.advance_clock(api, "2026-09-16T00:00:00Z")

    analysis = validate_success(
        api.create_structural_analysis(
            factories.structural_analysis_payload(
                application["id"], fixtures.read_tower_version(api, tower["id"]), "PRELIMINARY"
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )

    assert analysis["issued_at"].startswith("2026-09-16T00:00:00")
    # 500.0 subject units of 9000 rated units.
    assert_analysis_outcome(analysis, projected_loading_pct=5.556, result="PASS")

    reviewed = fixtures.read_application(api, application["id"])
    assert reviewed["status"] == "UNDER_STRUCTURAL_REVIEW"
    assert reviewed["sla_breached"] is True
    # 25 percent of the 250,000-cent base rent, credited to the carrier.
    assert_tenant_ledger(
        fixtures.read_tenant(api, tenant["id"]),
        outstanding_balance_cents=-62500,
        credit_status="CURRENT",
    )


def test_no_rent_credit_when_analysis_is_issued_exactly_at_the_review_deadline(api):
    """PRD §3.5: "A breach occurs when the analysis's `issued_at` is **strictly**
    after `review_deadline_at`; an analysis issued at exactly the deadline instant
    is not a breach."

    Design: Corner/calculations/sla_credit_withheld_when_analysis_lands_exactly_on_deadline
    """
    chain = _application_awaiting_analysis(api, "On Time Tor", "On Time Telecom")
    tower, tenant, application = chain["tower"], chain["tenant"], chain["application"]
    fixtures.advance_clock(api, "2026-09-15T00:00:00Z")

    analysis = validate_success(
        api.create_structural_analysis(
            factories.structural_analysis_payload(
                application["id"], fixtures.read_tower_version(api, tower["id"]), "PRELIMINARY"
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )

    assert analysis["issued_at"].startswith("2026-09-15T00:00:00")
    reviewed = fixtures.read_application(api, application["id"])
    assert reviewed["review_deadline_at"].startswith("2026-09-15T00:00:00")
    assert reviewed["sla_breached"] is False
    assert_tenant_ledger(
        fixtures.read_tenant(api, tenant["id"]),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )


# ─── Ground rent and remittance (PRD §3.2) ───────────────────────────────────


def test_ground_lease_rent_escalates_simply_with_a_single_rounding_step(api):
    """PRD §3.2: "To evaluate the rent as of some instant, count the anniversaries of
    `commencement_date` that fall at or before that instant — that is, the number of
    whole years, at least one, that have elapsed since commencement — then multiply
    `base_monthly_rent_cents` by one plus `escalator_pct` divided by one hundred
    multiplied by that anniversary count, and round the product half up to whole
    cents in exactly one rounding step."

    Design: Corner/calculations/ground_lease_rent_uses_simple_escalator_with_one_rounding
    """
    tower = fixtures.new_tower(
        api,
        site_name="Simple Escalator Slope",
        structure_type="MONOPOLE",
        rated_capacity_load_units=6000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=250,
        ground_space_total_sqft=6000,
    )
    landlord = fixtures.new_landlord(
        api,
        legal_name="Slope Land Trust",
        remit_contact_email="ap@slope.example",
        w9_on_file=True,
    )

    lease = validate_success(
        api.create_ground_lease(
            factories.ground_lease_payload(
                tower["id"],
                landlord["id"],
                base_monthly_rent_cents=400000,
                escalator_pct=2.5,
                commencement_date="2020-06-01",
                term_end_date="2031-05-31",
                renewal_option_count=2,
                renewal_term_years=5,
                buyout_price_cents=12000000,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )

    assert lease["status"] == "ACTIVE"
    # Six anniversaries of 2020-06-01 have passed at the 2026-08-01 clock:
    # 400000 * (1 + 0.025 * 6).
    assert_cents(lease["current_monthly_rent_cents"], 460000, "current_monthly_rent_cents")
    assert lease["renewals_exercised"] == 0
    assert lease["paid_through_date"] is None
    assert_cents(lease["buyout_paid_cents"], 0, "buyout_paid_cents")


def test_landlord_payment_sums_the_rounded_rent_of_each_covered_month(api):
    """PRD §3.2: "A recorded payment computes `months_covered` as the count of whole
    calendar months contained in the inclusive-to-inclusive interval running from
    `period_start_date` through `period_end_date`, and computes `amount_cents` by
    evaluating the lease rent at the first day of each of those months, rounding
    each month's figure to whole cents, and summing the rounded monthly figures —
    never by summing first and rounding once."

    Design: Corner/calculations/landlord_payment_sums_per_month_rents_across_an_anniversary
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "Anniversary Arroyo",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 6000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 250,
            "ground_space_total_sqft": 6000,
        },
        landlord_overrides={
            "legal_name": "Arroyo Land Trust",
            "remit_contact_email": "ap@arroyo.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 400000,
            "escalator_pct": 2.5,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
        },
    )
    lease = site["ground_lease"]

    payment = validate_success(
        api.create_landlord_payment(
            factories.landlord_payment_payload(lease["id"], "2026-04-01", "2026-07-31"),
            ADMIN_HEADERS,
        ),
        201,
    )

    assert payment["months_covered"] == 4
    # April and May price at five anniversaries (450000) and June and July at six
    # (460000), because the 2026-06-01 anniversary lands inside the period.
    assert_cents(payment["amount_cents"], 1820000, "amount_cents")

    settled = fixtures.read_ground_lease(api, lease["id"])
    assert settled["paid_through_date"] == "2026-07-31"
    assert_cents(settled["current_monthly_rent_cents"], 460000, "current_monthly_rent_cents")


# ─── Site rent compounding and its cap (PRD §3.7) ────────────────────────────


def test_amendment_rent_capped_at_one_and_a_half_times_base(api):
    """PRD §3.7: "Separately compute the cap as `base_monthly_rent_cents` multiplied
    by 1.50, rounded half up to whole cents. `current_monthly_rent_cents` is the
    lesser of the compounded running amount and that cap."

    Design: Corner/calculations/amendment_rent_capped_at_150_pct_of_base
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="EXECUTED",
        tower_overrides={
            "site_name": "Capped Crag",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 10000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": "Crag Land Co",
            "remit_contact_email": "ap@crag.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
        tenant_overrides={"legal_name": "Capped Crag Cellular"},
        mla_overrides={
            "base_monthly_rent_cents": 250000,
            "escalator_pct": 10.0,
            "initial_term_years": 15,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "CP-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        amendment_overrides={
            "effective_date": "2020-08-01",
            "term_end_date": "2031-05-31",
            "base_monthly_rent_cents": 250000,
            "escalator_pct": 10.0,
        },
    )
    fixtures.advance_clock(api, "2031-05-01T00:00:00Z")

    amendment = validate_success(api.get_site_amendment(chain["amendment"]["id"], ADMIN_HEADERS), 200)

    assert_cents(amendment["base_monthly_rent_cents"], 250000, "base_monthly_rent_cents")
    # Ten anniversaries of a 10 percent escalator compound to 648437 cents, but the
    # cap is 250000 * 1.50 computed off the original base.
    assert_cents(amendment["current_monthly_rent_cents"], 375000, "current_monthly_rent_cents")
    assert_amendment_axes(amendment, execution_status="EXECUTED", billing_status="BILLING")
    assert_tower_capacity(
        fixtures.read_tower(api, chain["tower"]["id"]), capacity_posture="OPEN"
    )


# ─── The modification cost pipeline (PRD §3.6) ───────────────────────────────


def test_volume_discount_tier_selected_once_from_the_pre_discount_total(api):
    """PRD §3.6: "Fourth, `volume_discount_pct` is selected **once** from that
    pre-discount total: it is 0.03 when the pre-discount total is at least
    25,000,000 cents (250,000 dollars), otherwise 0.015 when the pre-discount total
    is at least 10,000,000 cents (100,000 dollars), otherwise 0; the tier is never
    re-derived from the post-discount total."

    Design: Corner/calculations/modification_cost_tier_one_boundary_at_exactly_ten_million
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="REVIEWED",
        with_ground_lease=False,
        tower_overrides={
            "site_name": "Tier One Ledge",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 4000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
            "baseline_reserved_load_units": 3000,
        },
        tenant_overrides={"legal_name": "Tier One Radio"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "TR-80",
                "quantity": 10,
                "unit_weight_lbs": 80.01,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )
    quoted = fixtures.quoted_analysis_with_project(
        api,
        tower_id=chain["tower"]["id"],
        analysis_id=chain["analysis"]["id"],
        cost_cents=8928571,
    )
    project_id = quoted["project"]["id"]

    project = validate_success(api.allocate_cost_shares(project_id, {}, ENGINEER_HEADERS), 200)

    assert project["status"] == "COST_ALLOCATED"
    assert_cents(
        project["base_construction_cost_cents"], 8928571, "base_construction_cost_cents"
    )
    # A provisional fee of 1071429 lifts the pre-discount total to exactly
    # 10,000,000, so the inclusive tier-1 discount applies; the discounted
    # construction figure of 8794642 then carries its own 12 percent fee.
    assert_pct(project["volume_discount_pct"], 0.015, "volume_discount_pct")
    assert_cents(project["engineering_fee_cents"], 1055357, "engineering_fee_cents")
    assert_cents(project["total_cost_cents"], 9849999, "total_cost_cents")
    assert_cents(project["allocated_cents"], 9849999, "allocated_cents")

    shares, meta = validate_paginated(
        api.list_cost_shares(
            {"modification_project_id": project_id, "limit": 100}, ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 1
    assert shares[0]["status"] == "PENDING"
    assert shares[0]["tenant_id"] == chain["tenant"]["id"]
    assert_cents(shares[0]["share_cents"], 9849999, "share_cents")
    assert_load_units(shares[0]["basis_load_units"], 800.1, "basis_load_units")


def test_equal_share_remainder_cent_goes_wholly_to_the_earliest_basis(api):
    """PRD §3.6: "Flooring leaves a remainder equal to `total_cost_cents` less the
    sum of the floored shares, and that **entire** remainder is added to exactly one
    beneficiary's share — never spread across several. The remainder recipient is
    chosen by ranking beneficiaries by `basis_created_at` ascending, then by the
    beneficiary tenant's own `created_at` ascending, then by `basis_load_units`
    ascending, and taking the first."

    Design: Corner/calculations/equal_share_allocation_gives_remainder_cent_to_earliest_basis
    """
    incumbent = fixtures.build_colocation_chain(
        api,
        stage="EXECUTED",
        tower_overrides={
            "site_name": "Equal Share Basin",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 3900,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 400,
            "ground_space_total_sqft": 10000,
        },
        landlord_overrides={
            "legal_name": "Equal Basin Land",
            "remit_contact_email": "ap@eqbasin.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
        tenant_overrides={"legal_name": "Equal Alpha"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 400,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "EA-160",
                "quantity": 10,
                "unit_weight_lbs": 160,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        amendment_overrides={
            "effective_date": "2025-08-01",
            "term_end_date": "2031-05-31",
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
        },
    )
    applicant = fixtures.add_carrier_to_site(
        api,
        {"tower": incumbent["tower"], "ground_lease": incumbent["ground_lease"]},
        stage="REVIEWED",
        tenant_overrides={"legal_name": "Equal Bravo"},
        mla_overrides={
            "base_monthly_rent_cents": 250000,
            "escalator_pct": 3.5,
            "initial_term_years": 10,
            "renewal_terms_count": 2,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 150,
            "requested_elevation_top_ft": 190,
            "requested_ground_space_sqft": 500,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "EB-175",
                "quantity": 10,
                "unit_weight_lbs": 175,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 125,
            }
        ],
    )
    quoted = fixtures.quoted_analysis_with_project(
        api,
        tower_id=incumbent["tower"]["id"],
        analysis_id=applicant["analysis"]["id"],
        cost_cents=8000001,
        project_overrides={"allocation_basis": "EQUAL_SHARE"},
    )
    project_id = quoted["project"]["id"]

    project = validate_success(api.allocate_cost_shares(project_id, {}, ENGINEER_HEADERS), 200)

    assert project["allocation_basis"] == "EQUAL_SHARE"
    # A 960000-cent fee keeps the pre-discount total of 8960001 below the tier-1
    # threshold, so no discount applies.
    assert_pct(project["volume_discount_pct"], 0.0, "volume_discount_pct")
    assert_cents(project["total_cost_cents"], 8960001, "total_cost_cents")
    assert_cents(project["allocated_cents"], 8960001, "allocated_cents")

    incumbent_shares, _ = validate_paginated(
        api.list_cost_shares(
            {
                "modification_project_id": project_id,
                "tenant_id": incumbent["tenant"]["id"],
                "limit": 100,
            },
            ADMIN_HEADERS,
        )
    )
    applicant_shares, _ = validate_paginated(
        api.list_cost_shares(
            {
                "modification_project_id": project_id,
                "tenant_id": applicant["tenant"]["id"],
                "limit": 100,
            },
            ADMIN_HEADERS,
        )
    )

    # Each floored share is 4480000; the single leftover cent goes entirely to the
    # executed amendment, whose basis is the earlier of the two.
    assert len(incumbent_shares) == 1
    assert_cents(incumbent_shares[0]["share_cents"], 4480001, "share_cents")
    assert incumbent_shares[0]["site_amendment_id"] == incumbent["amendment"]["id"]
    assert len(applicant_shares) == 1
    assert_cents(applicant_shares[0]["share_cents"], 4480000, "share_cents")
    assert applicant_shares[0]["site_amendment_id"] is None


# ─── Retroactive billing of unauthorized installations (PRD §3.9) ────────────


def test_retroactive_billing_never_charges_the_partial_month(api):
    """PRD §3.9: "If the audit date's day of the month is earlier than the
    installation date's day of the month, subtract one, because a partial month is
    never billed."

    Design: Corner/calculations/retroactive_billing_drops_the_partial_month
    """
    tower = fixtures.new_tower(
        api,
        site_name="Partial Month Bench",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    tenant = fixtures.new_tenant(api, legal_name="Partial Month Broadcasting")
    fixtures.advance_clock(api, "2026-08-02T00:00:00Z")
    audit = fixtures.schedule_audit(
        api, tower["id"], audit_date="2026-08-01", basis="INSTALL_DATE_BASIS"
    )
    fixtures.start_audit(api, audit["id"])
    finding = fixtures.record_finding(
        api,
        audit["id"],
        tenant["id"],
        description="Unpermitted 40-unit RRU cluster on the south leg",
        observed_load_units=40,
        installed_on_date="2026-03-20",
        mount_elevation_ft=120,
    )

    finalized = validate_success(
        api.finalize_equipment_audit(audit["id"], {}, AUDITOR_HEADERS), 200
    )

    assert finalized["status"] == "FINALIZED"
    assert finalized["finding_count"] == 1
    # Five month boundaries but only four whole months, at 25 cents per load unit
    # and a 1.5 penalty multiplier: 4 * 1000 * 1.5.
    assert_cents(
        finalized["retroactive_billing_total_cents"], 6000, "retroactive_billing_total_cents"
    )

    billed = fixtures.read_finding(api, finding["id"])
    assert billed["months_billable"] == 4
    assert_cents(billed["retroactive_billing_cents"], 6000, "retroactive_billing_cents")
    assert billed["status"] == "BILLED"
    assert_tenant_ledger(
        fixtures.read_tenant(api, tenant["id"]),
        outstanding_balance_cents=6000,
        credit_status="CURRENT",
    )


# ─── The capacity posture boundaries (PRD §2.7, §2.8) ────────────────────────


def _tower_at_exactly_ninety_percent_with_a_papered_amendment(api):
    """A tower whose baseline reserves exactly 90.000 percent, plus a DRAFT amendment
    carrying one further 0.1 load unit."""
    return fixtures.build_colocation_chain(
        api,
        stage="PAPERED",
        tower_overrides={
            "site_name": "Ninety Notch",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 4000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
            "baseline_reserved_load_units": 3600,
        },
        landlord_overrides={
            "legal_name": "Notch Land Trust",
            "remit_contact_email": "ap@notchland.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
        tenant_overrides={"legal_name": "Ninety Notch Networks"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "TMA",
                "model_code": "NI-01",
                "quantity": 1,
                "unit_weight_lbs": 0.1,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 60,
            }
        ],
        amendment_overrides={
            "effective_date": "2026-08-01",
            "term_end_date": "2031-05-31",
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
        },
    )


def test_tower_stays_open_at_exactly_ninety_percent_reserved_load(api):
    """PRD §2.8: "A `reserved_load_pct` of exactly 90.000 is not `RESTRICTED`;
    anything above it is."

    Design: Corner/calculations/posture_turns_restricted_only_strictly_above_ninety_percent
    """
    chain = _tower_at_exactly_ninety_percent_with_a_papered_amendment(api)

    summary = validate_success(api.get_capacity_summary(chain["tower"]["id"], ADMIN_HEADERS), 200)

    # 3600 of 4000 rated units, and the papered amendment is still DRAFT so it
    # contributes nothing.
    assert_capacity_summary(
        summary,
        reserved_load_units=3600.0,
        reserved_load_pct=RESTRICTED_LOAD_PCT,
        capacity_posture="OPEN",
        occupied_band_count=0,
    )


def test_tower_turns_restricted_once_reserved_load_passes_ninety_percent(api):
    """PRD §2.8: "Otherwise, if `reserved_load_pct` is strictly greater than 90.000
    percent, or `available_ground_space_sqft` is zero or negative, the posture is
    `RESTRICTED`."

    Design: Corner/calculations/posture_turns_restricted_only_strictly_above_ninety_percent
    """
    chain = _tower_at_exactly_ninety_percent_with_a_papered_amendment(api)
    tower_id = chain["tower"]["id"]

    executed = validate_success(
        api.execute_site_amendment(
            chain["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
        ),
        200,
    )

    assert_amendment_axes(executed, execution_status="EXECUTED")
    # 3600.1 of 4000 rated units rounds to 90.003 percent, the first step above the
    # threshold.
    assert_capacity_summary(
        validate_success(api.get_capacity_summary(tower_id, ADMIN_HEADERS), 200),
        reserved_load_units=3600.1,
        reserved_load_pct=90.003,
        capacity_posture="RESTRICTED",
    )
    assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        available_ground_space_sqft=8700,
        capacity_posture="RESTRICTED",
    )


def test_tower_turns_restricted_when_ground_space_is_fully_consumed(api):
    """PRD §2.8: "A `reserved_load_pct` of exactly 90.000 is not `RESTRICTED`;
    anything above it is. An `available_ground_space_sqft` of exactly 0 **is**
    `RESTRICTED`."

    Design: Corner/calculations/posture_turns_restricted_when_ground_space_reaches_zero
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="PAPERED",
        tower_overrides={
            "site_name": "Ground Space Zero",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 300,
        },
        landlord_overrides={
            "legal_name": "Zero Compound Land",
            "remit_contact_email": "ap@zerocompound.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
        tenant_overrides={"legal_name": "Ground Space Zero Comms"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "GZ-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        amendment_overrides={
            "effective_date": "2026-08-01",
            "term_end_date": "2031-05-31",
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
        },
    )

    executed = validate_success(
        api.execute_site_amendment(
            chain["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
        ),
        200,
    )

    assert_amendment_axes(executed, execution_status="EXECUTED")
    # The whole 300-sqft compound is now reserved even though only 500.0 of 9000
    # load units are taken.
    assert_tower_capacity(
        fixtures.read_tower(api, chain["tower"]["id"]),
        reserved_ground_space_sqft=300,
        available_ground_space_sqft=0,
        reserved_load_pct=5.556,
        capacity_posture="RESTRICTED",
    )
