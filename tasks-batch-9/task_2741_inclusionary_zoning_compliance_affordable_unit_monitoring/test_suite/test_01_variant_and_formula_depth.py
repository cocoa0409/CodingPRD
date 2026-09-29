"""Depth coverage for the two-variant calculations and the ordered money pipelines.

Every test here drives one scenario end to end through declared endpoints and
checks the exact figures the contract derives, so a collapsed formula or a
reordered rounding step is observable in a single assertion.
"""

from test_helpers import factories, fixtures, validate_success
from test_helpers.assertions import (
    assert_fee_pricing_chain,
    assert_obligation_equivalents_conserved,
    round_half_up,
    same_calendar_day,
)
from test_helpers.constants import (
    AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE,
    AMI_2028_MEDIAN_INCOME_CENTS_BY_SIZE,
    CANONICAL_UTILITY_ALLOWANCE_CENTS_BY_BEDROOMS,
    CLOCK_STARTUP_DEFAULT,
    INCOME_LIMIT_SIZE_3_AT_5000_BPS,
    MAX_ALLOWED_RENT_2BR_AT_5000_BPS,
)

# A two-bedroom ownership unit that clears the comparability floor: 1100 square
# feet of market comparable requires at least 880, and this unit offers 950.
OWNERSHIP_UNIT = {
    "bedrooms": 2,
    "sqft": 950,
    "market_comparable_sqft": 1100,
    "tenure": "OWNERSHIP",
    "affordability_level_bps": 5000,
}

RENTAL_UNIT = {
    "bedrooms": 2,
    "sqft": 900,
    "market_comparable_sqft": 1000,
    "tenure": "RENTAL",
    "affordability_level_bps": 5000,
}

RESALE_TERMS = {
    "appraised_value_cents": 41000000,
    "capital_improvements_cents": 2500000,
    "deferred_maintenance_cents": 400000,
    "broker_fee_cents": 1000000,
}


def build_ownership_project(
    name: str,
    unit_number: str,
    resale_formula: str,
    doc_number: str,
    developer_headers: dict,
) -> dict:
    """One ten-unit R-2 development on the onsite path with a restricted unit."""
    project = fixtures.register_project(
        headers=developer_headers,
        name=name,
        zoning_district="R-2",
        total_units=10,
        approval_date="2026-01-15",
    )
    fixtures.screen_project(project["id"])
    fixtures.elect_path(project["id"], "ONSITE", headers=developer_headers)
    agreement = fixtures.draft_agreement(
        project["id"],
        term_years=45,
        resale_formula=resale_formula,
        owner_appreciation_share_bps=2500,
        max_refinance_ltv_bps=9000,
    )
    agreement = fixtures.record_agreement(
        agreement["id"], doc_number=doc_number, recorded_at="2026-08-01"
    )
    unit = fixtures.add_unit(
        project["id"],
        agreement["id"],
        headers=developer_headers,
        unit_number=unit_number,
        **OWNERSHIP_UNIT,
    )
    unit = fixtures.record_restriction(
        unit["id"], original_purchase_price_cents=32500000, recorded_at="2026-08-01"
    )
    return {"project": project, "agreement": agreement, "unit": unit}


def submit_ceiling_resale(api, unit_id: str, proposed_price_cents: int, headers: dict) -> dict:
    """Submit a resale carrying a freshly read expected_unit_version."""
    unit = fixtures.live_unit(unit_id)
    payload = factories.create_resale_payload(
        unit["id"],
        unit["version"],
        proposed_price_cents=proposed_price_cents,
        **RESALE_TERMS,
    )
    return validate_success(api.create_resale(payload, headers=headers), 201)


def test_ami_indexed_resale_ceiling_indexes_the_frozen_basis_to_the_active_schedule(
    api, compliance_officer, developer
):
    """An AMI_INDEXED agreement prices the resale ceiling off AMI growth alone.

    The unit's basis was frozen at 32500000 cents against the 2026 size-three
    median, so publishing the 2028 schedule lifts the indexed base to 34772471
    cents while the submitted appraisal plays no part in the figure at all.

    PRD: "Under `AMI_INDEXED`, multiply the unit's `original_purchase_price_cents` by the active schedule's median income for `bedrooms` plus one, divide by the unit's frozen `ami_income_at_purchase_cents`, and round half up."

    Design: Difficulty/dual_variant_calc/resale_price_ami_indexed_vs_shared_appreciation_diverge
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()
    ctx = build_ownership_project(
        "Larkspur Row", "L-101", "AMI_INDEXED", "DOC-P1-0001", developer
    )
    assert ctx["unit"]["ami_income_at_purchase_cents"] == AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE["3"]

    fixtures.publish_later_ami_schedule()
    resale = submit_ceiling_resale(api, ctx["unit"]["id"], 36872471, compliance_officer)

    assert resale["resale_formula_applied"] == "AMI_INDEXED"
    assert resale["improvement_credit_cents"] == 2500000
    assert resale["indexed_base_cents"] == 34772471
    assert resale["indexed_base_cents"] == round_half_up(
        32500000 * AMI_2028_MEDIAN_INCOME_CENTS_BY_SIZE["3"],
        AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE["3"],
    )
    assert resale["max_resale_price_cents"] == 36872471
    assert resale["state"] == "SUBMITTED"


def test_shared_appreciation_resale_ceiling_diverges_from_the_ami_indexed_one(
    api, compliance_officer, developer, rival_developer
):
    """Two agreements over identical units and identical terms yield two ceilings.

    The AMI_INDEXED unit is priced from the 2028 median and lands at 36872471
    cents; the SHARED_APPRECIATION unit is priced from the appraisal and lands
    at 36725000, exactly 147471 cents lower, on the same 32500000-cent basis.

    PRD: "The same unit with the same submitted numbers under two different agreements yields two different ceilings."

    Design: Difficulty/dual_variant_calc/resale_price_ami_indexed_vs_shared_appreciation_diverge
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()
    indexed = build_ownership_project(
        "Larkspur Row", "L-101", "AMI_INDEXED", "DOC-P1-0001", developer
    )
    shared = build_ownership_project(
        "Marigold Court", "M-101", "SHARED_APPRECIATION", "DOC-P2-0001", rival_developer
    )
    fixtures.publish_later_ami_schedule()

    indexed_resale = submit_ceiling_resale(
        api, indexed["unit"]["id"], 36872471, compliance_officer
    )
    shared_resale = submit_ceiling_resale(
        api, shared["unit"]["id"], 36725000, compliance_officer
    )

    assert shared_resale["resale_formula_applied"] == "SHARED_APPRECIATION"
    assert shared_resale["improvement_credit_cents"] == 2500000
    assert shared_resale["indexed_base_cents"] == 34625000
    assert shared_resale["indexed_base_cents"] == 32500000 + round_half_up(
        (41000000 - 32500000) * 2500, 10000
    )
    assert shared_resale["max_resale_price_cents"] == 36725000
    assert indexed_resale["max_resale_price_cents"] == 36872471
    assert (
        indexed_resale["max_resale_price_cents"] - shared_resale["max_resale_price_cents"]
        == 147471
    )
    assert (
        shared["unit"]["ami_income_at_purchase_cents"]
        == indexed["unit"]["ami_income_at_purchase_cents"]
        == AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE["3"]
    )


def build_partly_occupied_rental_project() -> dict:
    """A forty-unit C-2 development owing eight units and delivering two."""
    ctx = fixtures.project_with_unit(
        unit_overrides=dict(RENTAL_UNIT, unit_number="C-101"),
        project_overrides={
            "name": "Cedar Yards",
            "zoning_district": "C-2",
            "total_units": 40,
            "approval_date": "2026-01-15",
        },
        agreement_overrides={
            "term_years": 45,
            "resale_formula": "AMI_INDEXED",
            "owner_appreciation_share_bps": 2500,
            "max_refinance_ltv_bps": 9000,
        },
    )
    ctx["second_unit"] = fixtures.add_unit(
        ctx["project"]["id"],
        ctx["agreement"]["id"],
        unit_number="C-102",
        **RENTAL_UNIT,
    )
    ctx["household"] = fixtures.register_household(
        applicant_name="Nadia Okonjo", household_size=3, gross_annual_income_cents=6000000
    )
    ctx["certification"] = fixtures.certify_income(
        ctx["household"]["id"],
        ctx["unit"]["id"],
        contract_rent_cents=140000,
        effective_date="2026-08-01",
    )
    # Certifying the household moved the first unit "`PLANNED → OCCUPIED`", so
    # re-read it: the snapshot taken at creation still shows the pre-placement
    # `PLANNED` status.
    ctx["unit"] = fixtures.live_unit(ctx["unit"]["id"])
    ctx["project"] = fixtures.live_project(ctx["project"]["id"])
    return ctx


def test_entitlement_basis_credits_every_delivered_equivalent_on_paper(
    api, fund_auditor
):
    """The entitlement ratio counts units the moment they exist.

    Cedar Yards owes 80000 basis points and has created two units, so 20000
    basis points are delivered on paper and the ratio is 2500 even though only
    one of the two units is actually occupied.

    PRD: "On the `ENTITLEMENT` basis the ratio is 10000 multiplied by `delivered_equivalents_bps`, divided by `total_obligation_bps`, rounded half up."

    Design: Difficulty/dual_variant_calc/funder_report_entitlement_vs_occupancy_diverge
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = build_partly_occupied_rental_project()
    project = ctx["project"]
    assert project["total_obligation_bps"] == 80000
    assert project["onsite_unit_equivalents_bps"] == 20000
    assert project["fee_covered_equivalents_bps"] == 0

    report = validate_success(
        api.get_funder_report(project["id"], "ENTITLEMENT", headers=fund_auditor)
    )

    assert report["project_id"] == project["id"]
    assert report["basis"] == "ENTITLEMENT"
    assert report["total_obligation_bps"] == 80000
    assert report["delivered_equivalents_bps"] == 20000
    assert report["compliance_ratio_bps"] == 2500
    assert report["compliance_ratio_bps"] == round_half_up(10000 * 20000, 80000)
    assert report["open_findings_count"] == 0
    assert report["total_fees_assessed_cents"] == 0
    assert report["total_fees_paid_cents"] == 0


def test_occupancy_basis_credits_only_housed_households_and_diverges(api, fund_auditor):
    """The occupancy ratio counts only units both occupied and compliant.

    The same project, read on the other basis at the same instant, reports 10000
    occupied basis points against 20000 delivered, so the occupancy ratio is
    1250 — exactly half the entitlement ratio of 2500.

    PRD: "On the `OCCUPANCY` basis the ratio is 10000 multiplied by `occupied_equivalents_bps`, divided by `total_obligation_bps`, rounded half up."

    Design: Difficulty/dual_variant_calc/funder_report_entitlement_vs_occupancy_diverge
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = build_partly_occupied_rental_project()
    project_id = ctx["project"]["id"]
    assert ctx["unit"]["occupancy_status"] == "OCCUPIED"
    assert ctx["second_unit"]["occupancy_status"] == "PLANNED"

    entitlement = validate_success(
        api.get_funder_report(project_id, "ENTITLEMENT", headers=fund_auditor)
    )
    occupancy = validate_success(
        api.get_funder_report(project_id, "OCCUPANCY", headers=fund_auditor)
    )

    assert occupancy["basis"] == "OCCUPANCY"
    assert occupancy["occupied_equivalents_bps"] == 10000
    assert occupancy["delivered_equivalents_bps"] == 20000
    assert occupancy["compliance_ratio_bps"] == 1250
    assert entitlement["compliance_ratio_bps"] == 2500
    assert occupancy["total_obligation_bps"] == entitlement["total_obligation_bps"] == 80000
    assert occupancy["open_findings_count"] == entitlement["open_findings_count"] == 0
    assert (
        occupancy["total_fees_assessed_cents"]
        == entitlement["total_fees_assessed_cents"]
        == 0
    )


# Tiers tuned so that the capped and the uncapped pre-discount totals straddle
# the 198000000-cent boundary between the 150 and 400 basis-point rates.
STRADDLING_TIERS = [
    {"min_pre_discount_cents": 0, "discount_bps": 0},
    {"min_pre_discount_cents": 196000000, "discount_bps": 150},
    {"min_pre_discount_cents": 198000000, "discount_bps": 400},
]

FEE_PROJECT = {
    "name": "Foundry Block",
    "zoning_district": "C-2",
    "total_units": 40,
    "approval_date": "2026-01-15",
}


def assess_full_fee(api, project_id: str, headers: dict) -> dict:
    """Assess the whole outstanding obligation with a freshly read version."""
    project = fixtures.live_project(project_id)
    payload = factories.create_in_lieu_fee_payload(project_id, project["version"], basis="FULL")
    return validate_success(api.create_in_lieu_fee(payload, headers=headers), 201)


def test_capped_surcharge_selects_the_lower_discount_tier(api, program_admin):
    """The clamped surcharge is what the tier scan sees, so 150 basis points win.

    The unclamped surcharge would have been 6720000 cents, but the vintage caps
    it at 5000000, holding the pre-discount total at 197000000 — below the
    198000000 boundary — so the assessment settles at 194045000 cents.

    PRD: "The scale discount is selected on `pre_discount_total_cents` — the total **after** the surcharge — and not on `base_amount_cents`."

    Design: Difficulty/combinatorial_formula/in_lieu_fee_capped_surcharge_and_post_surcharge_tier_scan
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.fee_path_project(
        project_overrides=FEE_PROJECT,
        ordinance_overrides={"discount_tiers": STRADDLING_TIERS},
    )

    fee = assess_full_fee(api, ctx["project"]["id"], program_admin)

    assert fee["unit_equivalent_bps"] == 80000
    assert fee["base_amount_cents"] == 192000000
    assert round_half_up(192000000 * 350, 10000) == 6720000
    assert fee["surcharge_cents"] == 5000000
    assert fee["pre_discount_total_cents"] == 197000000
    assert fee["discount_bps_applied"] == 150
    assert fee["discount_cents"] == 2955000
    assert fee["assessed_amount_cents"] == 194045000
    assert_fee_pricing_chain(fee)
    assert fee["basis"] == "FULL"
    assert fee["state"] == "ASSESSED"
    assert fee["paid_amount_cents"] == 0
    assert fee["due_date"] == "2026-09-15"
    assert fee["ordinance_id"] == ctx["ordinance"]["id"]


def test_uncapped_surcharge_on_the_same_base_selects_the_higher_discount_tier(
    api, program_admin
):
    """Lifting the cap changes the tier, proving the clamp precedes the scan.

    With the cap raised the surcharge stands at its full 6720000 cents, the
    pre-discount total reaches 198720000 and the 400 basis-point tier qualifies,
    landing the same 192000000-cent base at 190771200 instead.

    PRD: "In particular, the surcharge cap can pull the pre-discount total back below a tier boundary, so a capped surcharge and an uncapped one can select **different** discount tiers from the same base amount — which is precisely why the cap must be applied before the tier scan rather than after it."

    Design: Difficulty/combinatorial_formula/in_lieu_fee_capped_surcharge_and_post_surcharge_tier_scan
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.fee_path_project(
        project_overrides=FEE_PROJECT,
        ordinance_overrides={
            "discount_tiers": STRADDLING_TIERS,
            "surcharge_cap_cents": 10000000,
        },
    )

    fee = assess_full_fee(api, ctx["project"]["id"], program_admin)

    assert fee["base_amount_cents"] == 192000000
    assert fee["surcharge_cents"] == 6720000
    assert fee["pre_discount_total_cents"] == 198720000
    assert fee["discount_bps_applied"] == 400
    assert fee["discount_cents"] == 7948800
    assert fee["assessed_amount_cents"] == 190771200
    assert_fee_pricing_chain(fee)


RENTAL_PROJECT = {
    "zoning_district": "C-2",
    "total_units": 40,
    "approval_date": "2026-01-15",
}


def certify_at(api, household_id: str, unit_id: str, rent_cents: int, headers: dict) -> dict:
    """Certify a household into a unit with an explicitly chosen effective date."""
    payload = factories.create_certification_payload(
        household_id,
        unit_id,
        certified_income_cents=6000000,
        contract_rent_cents=rent_cents,
        effective_date="2026-08-01",
    )
    return validate_success(api.create_certification(payload, headers=headers), 201)


def test_the_rent_ceiling_keeps_each_steps_rounding_and_lands_one_cent_low(
    api, compliance_officer
):
    """The four-step pipeline yields 143872 where a collapsed formula yields 143873.

    Truncating the annual limit to a monthly figure before applying the 3000
    basis-point housing share loses a third of a cent that a single algebraic
    expression would have carried forward into the ceiling.

    PRD: "Each step's rounding is an input to the next, so the pipeline may not be algebraically collapsed into a single expression — a collapsed formula returns a figure one cent away from the correct answer, and that cent is observable in the stored value and in every downstream rent comparison."

    Design: Difficulty/combinatorial_formula/max_allowed_rent_pinned_rounding_order_yields_one_cent_less
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.project_with_unit(
        unit_overrides=dict(RENTAL_UNIT, unit_number="W-201"),
        project_overrides=dict(RENTAL_PROJECT, name="Willow Terrace"),
    )
    household = fixtures.register_household(
        applicant_name="Priya Raman", household_size=3, gross_annual_income_cents=6000000
    )

    certification = certify_at(
        api, household["id"], ctx["unit"]["id"], 140000, compliance_officer
    )

    assert certification["ami_schedule_year"] == 2026
    assert certification["income_limit_cents"] == INCOME_LIMIT_SIZE_3_AT_5000_BPS == 6334900
    utility_allowance = CANONICAL_UTILITY_ALLOWANCE_CENTS_BY_BEDROOMS["2"]
    truncated_monthly = 6334900 // 12
    pinned = round_half_up(truncated_monthly * 3000, 10000) - utility_allowance
    collapsed = round_half_up(round_half_up(6334900 * 3000, 10000), 12) - utility_allowance
    assert pinned == 143872
    assert collapsed == 143873
    assert certification["max_rent_cents"] == 143872
    assert certification["max_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS
    assert certification["max_rent_cents"] != collapsed
    assert certification["state"] == "CERTIFIED"
    assert certification["contract_rent_cents"] == 140000
    assert str(certification["expires_at"]).startswith("2027-08-01")


def test_the_unit_freezes_the_pinned_ceiling_it_was_certified_against(
    api, compliance_officer
):
    """Occupancy copies the certification's ceiling verbatim onto the unit.

    The unit's frozen ceiling is the pipeline's 143872 rather than the collapsed
    143873, which is what every later rent comparison is measured against, while
    the contract rent of 140000 sits below it.

    PRD: "From `RESERVED` — permitted only when the certification's `unit_id` and `household_id` match the unit and its `occupant_household_id` — the unit moves `RESERVED → OCCUPIED`, setting `current_rent_cents` to the certification's `contract_rent_cents` and `max_allowed_rent_cents` to its `max_rent_cents`."

    PRD: "From `PLANNED` the unit moves `PLANNED → OCCUPIED` — direct placement without a lottery, which is the normal path for `OWNERSHIP` units — additionally setting `occupant_household_id` from the certification."

    Design: Difficulty/combinatorial_formula/max_allowed_rent_pinned_rounding_order_yields_one_cent_less
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.project_with_unit(
        unit_overrides=dict(RENTAL_UNIT, unit_number="W-201"),
        project_overrides=dict(RENTAL_PROJECT, name="Willow Terrace"),
    )
    household = fixtures.register_household(
        applicant_name="Priya Raman", household_size=3, gross_annual_income_cents=6000000
    )
    assert ctx["unit"]["occupancy_status"] == "PLANNED"

    certification = certify_at(
        api, household["id"], ctx["unit"]["id"], 140000, compliance_officer
    )
    unit = fixtures.live_unit(ctx["unit"]["id"])

    assert unit["max_allowed_rent_cents"] == certification["max_rent_cents"] == 143872
    assert unit["current_rent_cents"] == 140000
    assert unit["occupancy_status"] == "OCCUPIED"
    assert unit["occupant_household_id"] == household["id"]


def build_overcharge_finding(api, compliance_officer) -> dict:
    """One occupied rental unit carrying a 2027 finding for a 165000-cent rent."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.occupied_rental_unit(
        unit_overrides=dict(RENTAL_UNIT, unit_number="A-301"),
        project_overrides=dict(RENTAL_PROJECT, name="Alder Mews"),
        household_overrides={
            "applicant_name": "Tomas Berger",
            "household_size": 3,
            "gross_annual_income_cents": 6000000,
        },
        certification_overrides={
            "contract_rent_cents": 140000,
            "effective_date": "2026-08-01",
        },
    )
    fixtures.set_clock("2027-03-01T00:00:00Z")
    payload = factories.create_monitoring_review_payload(
        ctx["unit"]["id"], review_year=2027, reported_rent_cents=165000
    )
    ctx["monitoring_review"] = validate_success(
        api.create_monitoring_review(payload, headers=compliance_officer), 201
    )
    return ctx


def test_the_cure_extension_is_decided_from_the_base_penalty_at_issue(
    api, compliance_officer
):
    """A base penalty below the threshold earns no extension at all.

    The unit overcharges by 21128 cents a month, so the one-month base penalty is
    88384 — under the inclusive 100000-cent threshold — and the deadline is a
    plain thirty days after issue.

    PRD: "`cure_extension_days` is 15 when `penalty_at_base_cents` is at least 100000 cents, and 0 otherwise — a serious violation earns more time to fix, not less."

    Design: Difficulty/combinatorial_formula/cure_extension_frozen_from_base_penalty_not_final_penalty
    """
    ctx = build_overcharge_finding(api, compliance_officer)
    review = ctx["monitoring_review"]

    assert review["state"] == "FINDING_ISSUED"
    assert review["finding_types"] == ["RENT_OVERCHARGE"]
    assert review["overcharge_monthly_cents"] == 165000 - 143872 == 21128
    assert review["penalty_at_base_cents"] == 21128 * 3 + 25000 == 88384
    assert review["penalty_at_base_cents"] < 100000
    assert review["cure_extension_days"] == 0
    assert same_calendar_day(review["finding_issued_at"], "2027-03-01T00:00:00Z")
    assert str(review["cure_deadline"]).startswith("2027-03-31")
    # `penalty_final_cents` is only ever defined by the cure submission that
    # "computes `penalty_final_cents` at that instant"; the contract states no
    # value for it before the first cure lands, so nothing about it is asserted
    # on a review still sitting at `FINDING_ISSUED`.


def test_a_late_cure_grows_the_final_penalty_without_moving_the_frozen_deadline(
    api, compliance_officer, developer
):
    """The larger final penalty never re-derives the extension it postdates.

    Curing on 2027-04-05 is the thirty-fifth day, so the penalty climbs to two
    months at 113384 cents — over the 100000-cent threshold — yet the extension
    stays 0 and the deadline stays the 2027-03-31 the base penalty bought.

    PRD: "`cure_extension_days` and `cure_deadline` are decided exactly once, at issue, from `penalty_at_base_cents` alone."

    Design: Difficulty/combinatorial_formula/cure_extension_frozen_from_base_penalty_not_final_penalty
    """
    ctx = build_overcharge_finding(api, compliance_officer)
    review_id = ctx["monitoring_review"]["id"]

    fixtures.set_clock("2027-04-05T00:00:00Z")
    review = validate_success(api.submit_cure(review_id, 143872, headers=developer))

    assert review["penalty_final_cents"] == 21128 * 3 + 2 * 25000 == 113384
    assert review["penalty_final_cents"] > 100000
    assert review["penalty_at_base_cents"] == 88384
    assert review["cure_extension_days"] == 0
    assert str(review["cure_deadline"]).startswith("2027-03-31")
    assert review["state"] == "ESCALATED"
    unit = fixtures.live_unit(ctx["unit"]["id"])
    assert unit["compliance_status"] == "OUT_OF_COMPLIANCE"
    project = fixtures.live_project(ctx["project"]["id"])
    assert project["compliance_posture"] == "UNDER_ENFORCEMENT"
    assert_obligation_equivalents_conserved(project)
