"""Calculation corners of the inclusionary-zoning compliance contract.

Each test drives one named calculation to a corner the contract determines
exactly: the two lookups that key off ``bedrooms + 1``, the status-blind
ordinance vintage lookup, the comparability floor constant, the improvement
credit clamp, the resale-formula variant switch, the post-surcharge discount
tier scan, the degenerate resale waterfall, the lottery tie-break and the
ordered compliance-posture clauses.
"""

from test_helpers import (
    CLOCK_STARTUP_DEFAULT,
    INCOME_LIMIT_SIZE_2_AT_5000_BPS,
    INCOME_LIMIT_SIZE_3_AT_5000_BPS,
    MAX_ALLOWED_RENT_1BR_AT_5000_BPS,
    MAX_ALLOWED_RENT_2BR_AT_5000_BPS,
    THRESHOLDS,
    ApiErrorId,
    api_client,
    apply_bps,
    assert_fee_pricing_chain,
    assert_money_cents,
    assert_obligation_equivalents_conserved,
    assert_project_state,
    assert_unit_dimensions,
    assert_waterfall_conserved,
    date_plus_days,
    factories,
    fixtures,
    get_success_data,
    make_resident_headers,
    parse_instant,
    round_half_up,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AUDITOR, DEV, DEV2, HCO, HCO2, PA

# The 2026 schedule leaves the AMI index factor at exactly 1, so an AMI_INDEXED
# ceiling reduces to the recorded purchase basis.
OWNERSHIP_BASIS_CENTS = 32500000


def _calendar_day(value: str) -> str:
    """The calendar date of an instant or plain date, as YYYY-MM-DD."""
    return parse_instant(value).date().isoformat()


def test_income_limit_and_rent_ceiling_key_off_bedrooms_plus_one():
    """Two units at the same affordability level get different ceilings from one schedule.

    PRD: "Step one: take the household size implied by the unit itself — the unit's `bedrooms` plus one — and compute the annual income limit for that size at the unit's `affordability_level_bps`, which includes the whole-dollar half-up rounding."

    Design: Corner/calculations/income_limits_and_rent_ceilings_are_correct_for_both_bedroom_counts
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.agreement_recorded_project(
        project_overrides={
            "name": "Eligibility Lane",
            "zoning_district": "R-2",
            "total_units": 20,
            "approval_date": "2026-01-15",
        }
    )
    project_id = ctx["project"]["id"]
    agreement_id = ctx["agreement"]["id"]

    unit_2br = fixtures.add_unit(
        project_id,
        agreement_id,
        unit_number="EL-101",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="RENTAL",
        affordability_level_bps=5000,
    )
    unit_1br = fixtures.add_unit(
        project_id,
        agreement_id,
        unit_number="EL-102",
        bedrooms=1,
        sqft=600,
        market_comparable_sqft=700,
        tenure="RENTAL",
        affordability_level_bps=5000,
    )
    household_3 = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    household_2 = fixtures.register_household(
        applicant_name="Ines Novak", household_size=2, gross_annual_income_cents=5000000
    )

    cert_2br = fixtures.certify_income(
        household_3["id"],
        unit_2br["id"],
        certified_income_cents=6000000,
        contract_rent_cents=143000,
        effective_date="2026-08-01",
    )
    cert_1br = fixtures.certify_income(
        household_2["id"],
        unit_1br["id"],
        certified_income_cents=5000000,
        contract_rent_cents=129000,
        effective_date="2026-08-01",
    )

    # bedrooms + 1 selects median 12669800 with a 14500 utility allowance for the
    # two-bedroom, and median 11278000 with an 11000 allowance for the one-bedroom.
    assert cert_2br["income_limit_cents"] == INCOME_LIMIT_SIZE_3_AT_5000_BPS == 6334900
    assert cert_2br["max_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS == 143872
    assert cert_1br["income_limit_cents"] == INCOME_LIMIT_SIZE_2_AT_5000_BPS == 5639000
    assert cert_1br["max_rent_cents"] == MAX_ALLOWED_RENT_1BR_AT_5000_BPS == 129975
    assert cert_2br["income_limit_cents"] != cert_1br["income_limit_cents"]
    assert cert_2br["max_rent_cents"] != cert_1br["max_rent_cents"]
    assert_money_cents(cert_2br["max_rent_cents"], "max_rent_cents")

    # ami_pct_bps is measured against the household's OWN size median, not the
    # unit's imputed size: 6000000 of 12669800 is 4736 bps, 5000000 of 11278000
    # is 4433 bps.
    assert cert_2br["ami_pct_bps"] == round_half_up(6000000 * 10000, 12669800) == 4736
    assert cert_1br["ami_pct_bps"] == round_half_up(5000000 * 10000, 11278000) == 4433

    for cert in (cert_2br, cert_1br):
        assert cert["state"] == "CERTIFIED"
        assert cert["ami_schedule_year"] == 2026
        assert _calendar_day(cert["expires_at"]) == date_plus_days("2026-08-01", 365) == "2027-08-01"

    live_2br = fixtures.live_unit(unit_2br["id"])
    live_1br = fixtures.live_unit(unit_1br["id"])
    assert live_2br["max_allowed_rent_cents"] == 143872
    assert live_1br["max_allowed_rent_cents"] == 129975

    project = fixtures.live_project(project_id)
    assert_project_state(
        project, state="MONITORING", applicability="SUBJECT",
        compliance_posture="COMPLIANT_ONSITE",
    )
    assert project["onsite_unit_equivalents_bps"] == 20000
    assert project["total_obligation_bps"] == 20000
    assert_obligation_equivalents_conserved(project)


def test_a_superseded_vintage_still_governs_an_earlier_approval():
    """Vintage selection filters on effective_date alone, so a SUPERSEDED row can win.

    PRD: "Selecting the governing vintage for a development is a chronological lookup performed at screening, and it deliberately ignores `status`."

    Design: Corner/calculations/a_superseded_ordinance_vintage_still_governs_an_earlier_approval
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ordinance_2018 = fixtures.publish_ordinance(
        code="IZ-2018-01",
        effective_date="2018-01-01",
        min_project_units_threshold=20,
        set_aside_bps_by_district={"R-2": 500, "R-4": 800, "C-2": 1000},
        gap_basis_cents_by_level={"5000": 12000000},
        fee_gap_level_bps=5000,
        surcharge_bps=0,
        discount_tiers=[{"min_pre_discount_cents": 0, "discount_bps": 0}],
        fee_due_days=60,
        alternative_paths_allowed=["IN_LIEU_FEE"],
    )
    ordinance_2024 = fixtures.publish_ordinance()
    ordinance_2026 = fixtures.publish_ordinance(
        code="IZ-2026-06",
        effective_date="2026-06-01",
        min_project_units_threshold=10,
        set_aside_bps_by_district={"R-2": 1500, "R-4": 2000, "C-2": 2500},
        gap_basis_cents_by_level={"5000": 30000000},
        fee_gap_level_bps=5000,
        discount_tiers=[{"min_pre_discount_cents": 0, "discount_bps": 0}],
        fee_due_days=30,
        alternative_paths_allowed=["IN_LIEU_FEE"],
    )
    fixtures.publish_ami_schedule()

    older = fixtures.register_project(
        name="Vintage Older", zoning_district="R-2", total_units=10,
        approval_date="2026-01-15",
    )
    newer = fixtures.register_project(
        name="Vintage Newer", zoning_district="R-2", total_units=10,
        approval_date="2026-07-01",
    )

    screened_older = fixtures.screen_project(older["id"])
    screened_newer = fixtures.screen_project(newer["id"])

    # Publishing in ascending effective_date order leaves only the newest ACTIVE.
    assert get_success_data(
        api_client.get_ordinance(ordinance_2018["id"], headers=PA)
    )["status"] == "SUPERSEDED"
    assert get_success_data(
        api_client.get_ordinance(ordinance_2024["id"], headers=PA)
    )["status"] == "SUPERSEDED"
    assert get_success_data(
        api_client.get_ordinance(ordinance_2026["id"], headers=PA)
    )["status"] == "ACTIVE"

    # The 2026-01-15 approval pins the SUPERSEDED 2024 vintage: 10 units at
    # 1000 bps is exactly one whole dwelling and no residual fraction.
    assert screened_older["ordinance_id"] == ordinance_2024["id"]
    assert_project_state(screened_older, state="SCREENED_SUBJECT", applicability="SUBJECT")
    assert screened_older["required_affordable_units"] == 1
    assert screened_older["fractional_obligation_bps"] == 0
    assert screened_older["total_obligation_bps"] == 10000

    # The 2026-07-01 approval pins the ACTIVE 2026 vintage: 10 units at 1500 bps
    # is 15000 raw bps, whose 5000 bps residual rounds up into a whole unit.
    assert screened_newer["ordinance_id"] == ordinance_2026["id"]
    assert_project_state(screened_newer, state="SCREENED_SUBJECT", applicability="SUBJECT")
    assert screened_newer["required_affordable_units"] == 2
    assert screened_newer["fractional_obligation_bps"] == 0
    assert screened_newer["total_obligation_bps"] == 20000

    # Neither project pins the 2018 vintage, whose 20-unit threshold would have
    # reported EXEMPT for both.
    assert ordinance_2018["id"] not in (
        screened_older["ordinance_id"], screened_newer["ordinance_id"]
    )


def test_the_comparability_floor_applies_the_eighty_percent_constant():
    """The per-unit floor is 8000 bps of that unit's own comparable, refusing only sqft below it.

    PRD: "Take the unit's `market_comparable_sqft`, multiply by 8000 basis points — four fifths of the comparable — and round half up to a whole square foot; call that the minimum."

    Design: Corner/calculations/the_comparability_floor_applies_the_eighty_percent_constant
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.agreement_recorded_project(
        project_overrides={
            "name": "Comparable Court",
            "zoning_district": "R-2",
            "total_units": 40,
            "approval_date": "2026-01-15",
        }
    )
    project_id = ctx["project"]["id"]
    agreement_id = ctx["agreement"]["id"]

    assert THRESHOLDS["COMPARABILITY_MIN_BPS"] == 8000
    floor_1000 = apply_bps(1000, 8000)
    floor_700 = apply_bps(700, 8000)
    assert floor_1000 == 800 and floor_700 == 560

    # Exactly at the floor: accepted.
    at_floor = validate_success(
        api_client.create_unit(
            factories.create_unit_payload(
                project_id, agreement_id, unit_number="CO-101", bedrooms=2,
                sqft=floor_1000, market_comparable_sqft=1000, tenure="RENTAL",
                affordability_level_bps=5000,
            ),
            headers=DEV,
        ),
        201,
    )
    assert at_floor["sqft"] == 800
    assert_unit_dimensions(
        at_floor, occupancy_status="PLANNED", compliance_status="COMPLIANT",
        restriction_state="NOT_RECORDED",
    )

    # One square foot below the same floor: refused, and no row is created.
    validate_error(
        api_client.create_unit(
            factories.create_unit_payload(
                project_id, agreement_id, unit_number="CO-102", bedrooms=2,
                sqft=floor_1000 - 1, market_comparable_sqft=1000, tenure="RENTAL",
                affordability_level_bps=5000,
            ),
            headers=DEV,
        ),
        ApiErrorId.ERR_COMPARABILITY_STANDARD_FAILED.value,
        422,
    )

    # The floor is recomputed per unit, so 560 sqft clears a 700 sqft comparable
    # inside the very same project that just refused 799 against 1000.
    small_unit = validate_success(
        api_client.create_unit(
            factories.create_unit_payload(
                project_id, agreement_id, unit_number="CO-103", bedrooms=1,
                sqft=floor_700, market_comparable_sqft=700, tenure="RENTAL",
                affordability_level_bps=5000,
            ),
            headers=DEV,
        ),
        201,
    )

    units, meta = validate_paginated(api_client.list_units(project_id=project_id, headers=HCO))
    assert meta["total_count"] == 2
    assert {u["id"] for u in units} == {at_floor["id"], small_unit["id"]}

    project = fixtures.live_project(project_id)
    assert project["total_obligation_bps"] == 40000
    assert project["onsite_unit_equivalents_bps"] == 20000


def test_improvement_credit_is_clamped_at_ten_percent_of_the_purchase_basis():
    """The credit is min(claim, 1000 bps of basis), inclusive at the cap, and freezes per row.

    PRD: "First, common to both: `resale_formula_applied` is copied from the agreement's `resale_formula`, pinning which variant runs for the life of this transaction, and `improvement_credit_cents` is the lesser of the submitted `capital_improvements_cents` and the credit cap — the unit's `original_purchase_price_cents` multiplied by 1000 basis points, divided by 10000 and rounded half up."

    Design: Corner/calculations/improvement_credit_is_clamped_at_ten_percent_of_the_purchase_basis
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.restricted_ownership_unit(
        unit_overrides={
            "unit_number": "IC-101",
            "bedrooms": 2,
            "sqft": 900,
            "market_comparable_sqft": 1000,
            "tenure": "OWNERSHIP",
            "affordability_level_bps": 5000,
        },
        original_purchase_price_cents=OWNERSHIP_BASIS_CENTS,
        restriction_recorded_at="2026-08-01",
        project_overrides={
            "name": "Improvement Cap",
            "zoning_district": "R-2",
            "total_units": 10,
            "approval_date": "2026-01-15",
        },
        agreement_overrides={
            "term_years": 45,
            "resale_formula": "AMI_INDEXED",
            "owner_appreciation_share_bps": 2500,
            "max_refinance_ltv_bps": 9000,
        },
    )
    unit_id = ctx["unit"]["id"]
    seller = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    fixtures.certify_income(
        seller["id"], unit_id, certified_income_cents=6000000,
        contract_rent_cents=0, effective_date="2026-08-01",
    )
    seller_headers = make_resident_headers(seller["id"])

    assert THRESHOLDS["IMPROVEMENT_CAP_BPS"] == 1000
    credit_cap = apply_bps(OWNERSHIP_BASIS_CENTS, 1000)
    assert credit_cap == 3250000

    def submit(capital_improvements_cents):
        # Every submission bumps the unit's version, so each one re-reads it.
        unit = fixtures.live_unit(unit_id)
        payload = factories.create_resale_payload(
            unit_id,
            unit["version"],
            proposed_price_cents=32000000,
            appraised_value_cents=45000000,
            capital_improvements_cents=capital_improvements_cents,
            deferred_maintenance_cents=0,
            broker_fee_cents=0,
        )
        return validate_success(
            api_client.create_resale(payload, headers=seller_headers), 201
        )

    over_cap = submit(credit_cap + 50000)
    at_cap = submit(credit_cap)
    under_cap = submit(1000000)

    # The clamp is a min(): above the cap it bites, exactly at the cap the whole
    # claim survives, below the cap the claim passes through untouched.
    assert over_cap["improvement_credit_cents"] == credit_cap == 3250000
    assert at_cap["improvement_credit_cents"] == credit_cap == 3250000
    assert under_cap["improvement_credit_cents"] == 1000000

    # max_resale_price_cents is indexed_base + credit - deferred_maintenance, and
    # the AMI factor is 1, so the base is the 32500000 recorded basis.
    for row in (over_cap, at_cap, under_cap):
        assert row["resale_formula_applied"] == "AMI_INDEXED"
        assert row["indexed_base_cents"] == OWNERSHIP_BASIS_CENTS
        assert (
            row["max_resale_price_cents"]
            == row["indexed_base_cents"] + row["improvement_credit_cents"] - 0
        )
    assert over_cap["max_resale_price_cents"] == 35750000
    assert at_cap["max_resale_price_cents"] == 35750000
    assert under_cap["max_resale_price_cents"] == 33500000

    # Each submission supersedes its predecessor, yet every frozen ceiling stays
    # readable on the superseded row.
    frozen_over = get_success_data(api_client.get_resale(over_cap["id"], headers=HCO))
    frozen_at = get_success_data(api_client.get_resale(at_cap["id"], headers=HCO))
    frozen_under = get_success_data(api_client.get_resale(under_cap["id"], headers=HCO))
    assert frozen_over["state"] == "SUPERSEDED"
    assert frozen_at["state"] == "SUPERSEDED"
    assert frozen_under["state"] == "SUBMITTED"
    assert frozen_over["max_resale_price_cents"] == 35750000
    assert frozen_at["max_resale_price_cents"] == 35750000
    assert frozen_under["max_resale_price_cents"] == 33500000


def test_the_resale_formula_branch_comes_from_the_agreement_not_the_payload():
    """Identical submissions on twin units diverge because their agreements pin different variants.

    PRD: "The same unit with the same submitted numbers under two different agreements yields two different ceilings."

    Design: Corner/calculations/the_resale_formula_branch_comes_from_the_agreement_not_the_payload
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    def build_restricted_unit(name, unit_number, doc_number, formula, developer_headers):
        project = fixtures.register_project(
            headers=developer_headers, name=name, zoning_district="R-2",
            total_units=10, approval_date="2026-01-15",
        )
        fixtures.screen_project(project["id"])
        fixtures.elect_path(project["id"], "ONSITE", headers=developer_headers)
        agreement = fixtures.draft_agreement(
            project["id"], term_years=45, resale_formula=formula,
            owner_appreciation_share_bps=2500, max_refinance_ltv_bps=9000,
        )
        agreement = fixtures.record_agreement(
            agreement["id"], doc_number=doc_number, recorded_at="2026-06-01"
        )
        unit = fixtures.add_unit(
            project["id"], agreement["id"], headers=developer_headers,
            unit_number=unit_number, bedrooms=2, sqft=900, market_comparable_sqft=1000,
            tenure="OWNERSHIP", affordability_level_bps=5000,
        )
        unit = fixtures.record_restriction(
            unit["id"], original_purchase_price_cents=OWNERSHIP_BASIS_CENTS,
            recorded_at="2026-08-01",
        )
        return {"project": project, "agreement": agreement, "unit": unit}

    indexed = build_restricted_unit(
        "Indexed Row", "VA-101", "DOC-VA-0001", "AMI_INDEXED", DEV
    )
    shared = build_restricted_unit(
        "Shared Row", "VB-101", "DOC-VB-0001", "SHARED_APPRECIATION", DEV2
    )

    # Both agreements share the appreciation split, so only the formula differs.
    assert indexed["agreement"]["resale_formula"] == "AMI_INDEXED"
    assert shared["agreement"]["resale_formula"] == "SHARED_APPRECIATION"
    assert (
        indexed["agreement"]["owner_appreciation_share_bps"]
        == shared["agreement"]["owner_appreciation_share_bps"]
        == 2500
    )
    # Both units froze the same basis and the same AMI reference point.
    assert (
        indexed["unit"]["original_purchase_price_cents"]
        == shared["unit"]["original_purchase_price_cents"]
        == OWNERSHIP_BASIS_CENTS
    )
    assert (
        indexed["unit"]["ami_income_at_purchase_cents"]
        == shared["unit"]["ami_income_at_purchase_cents"]
        == 12669800
    )

    seller_indexed = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    seller_shared = fixtures.register_household(
        applicant_name="Ines Novak", household_size=3, gross_annual_income_cents=6100000
    )
    fixtures.certify_income(
        seller_indexed["id"], indexed["unit"]["id"], certified_income_cents=6000000,
        contract_rent_cents=0, effective_date="2026-08-01",
    )
    fixtures.certify_income(
        seller_shared["id"], shared["unit"]["id"], certified_income_cents=6100000,
        contract_rent_cents=0, effective_date="2026-08-01",
    )
    sellers = {
        indexed["unit"]["id"]: make_resident_headers(seller_indexed["id"]),
        shared["unit"]["id"]: make_resident_headers(seller_shared["id"]),
    }

    def submit(unit_id, appraised_value_cents):
        # Byte-identical commercial terms; only unit_id and the OCC token differ.
        terms = {
            "proposed_price_cents": 32000000,
            "appraised_value_cents": appraised_value_cents,
            "capital_improvements_cents": 0,
            "deferred_maintenance_cents": 0,
            "broker_fee_cents": 0,
        }
        payload = factories.create_resale_payload(
            unit_id, fixtures.live_unit(unit_id)["version"], **terms
        )
        row = validate_success(
            api_client.create_resale(payload, headers=sellers[unit_id]), 201
        )
        for field, value in terms.items():
            assert row[field] == value
        return row

    indexed_low = submit(indexed["unit"]["id"], 41000000)
    shared_low = submit(shared["unit"]["id"], 41000000)
    indexed_high = submit(indexed["unit"]["id"], 50000000)
    shared_high = submit(shared["unit"]["id"], 50000000)

    # AMI_INDEXED ignores the appraisal entirely: the 2026 schedule's median for
    # bedrooms + 1 equals the frozen reference, so the base is the bare basis.
    assert indexed_low["resale_formula_applied"] == "AMI_INDEXED"
    assert indexed_high["resale_formula_applied"] == "AMI_INDEXED"
    assert indexed_low["indexed_base_cents"] == OWNERSHIP_BASIS_CENTS
    assert indexed_high["indexed_base_cents"] == OWNERSHIP_BASIS_CENTS
    assert indexed_low["max_resale_price_cents"] == indexed_high["max_resale_price_cents"]
    assert indexed_high["max_resale_price_cents"] == 32500000

    # SHARED_APPRECIATION ignores the AMI schedule and tracks the appraisal:
    # basis plus 2500 bps of the appreciation over that basis.
    assert shared_low["resale_formula_applied"] == "SHARED_APPRECIATION"
    assert shared_high["resale_formula_applied"] == "SHARED_APPRECIATION"
    assert shared_low["indexed_base_cents"] == OWNERSHIP_BASIS_CENTS + apply_bps(
        41000000 - OWNERSHIP_BASIS_CENTS, 2500
    ) == 34625000
    assert shared_high["indexed_base_cents"] == OWNERSHIP_BASIS_CENTS + apply_bps(
        50000000 - OWNERSHIP_BASIS_CENTS, 2500
    ) == 36875000
    assert shared_low["max_resale_price_cents"] == 34625000
    assert shared_high["max_resale_price_cents"] == 36875000

    # Same numbers in, two different ceilings out, at both appraisals.
    assert indexed_low["max_resale_price_cents"] != shared_low["max_resale_price_cents"]
    assert indexed_high["max_resale_price_cents"] != shared_high["max_resale_price_cents"]

    # The formula travels with the transaction, not with the payload.
    for row in (indexed_low, shared_low, indexed_high, shared_high):
        assert row["improvement_credit_cents"] == 0
        assert row["max_resale_price_cents"] == row["indexed_base_cents"]
        assert row["state"] in ("SUBMITTED", "SUPERSEDED")


def test_the_discount_tier_is_scanned_on_the_post_surcharge_total():
    """A base amount under a tier boundary still buys the higher discount once surcharged.

    PRD: "The scale discount is selected on `pre_discount_total_cents` — the total **after** the surcharge — and not on `base_amount_cents`."

    Design: Corner/calculations/the_discount_tier_is_scanned_on_the_post_surcharge_total
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    program = fixtures.bootstrap_program()
    ordinance_id = program["ordinance"]["id"]

    def fee_project(name, zoning_district, total_units, developer_headers):
        project = fixtures.register_project(
            headers=developer_headers, name=name, zoning_district=zoning_district,
            total_units=total_units, approval_date="2026-03-01",
        )
        screened = fixtures.screen_project(project["id"])
        fixtures.elect_path(project["id"], "IN_LIEU_FEE", headers=developer_headers)
        return screened

    below_boundary = fee_project("Tier Below", "C-2", 20, DEV)
    above_boundary = fee_project("Tier Above", "R-4", 27, DEV)
    fractional_only = fee_project("Tier Fraction", "R-4", 27, DEV2)

    assert below_boundary["total_obligation_bps"] == 40000
    assert above_boundary["total_obligation_bps"] == 40500
    assert above_boundary["fractional_obligation_bps"] == 500

    fee_below = fixtures.assess_fee(below_boundary["id"], basis="FULL")
    fee_above = fixtures.assess_fee(above_boundary["id"], basis="FULL")
    fee_fraction = fixtures.assess_fee(fractional_only["id"], basis="FRACTIONAL")

    # 4.0 unit equivalents: 96000000 base, 3360000 surcharge, 99360000 total,
    # which sits just under the 100000000 boundary and takes the 150 bps tier.
    assert fee_below["unit_equivalent_bps"] == 40000
    assert fee_below["base_amount_cents"] == 96000000
    assert fee_below["surcharge_cents"] == 3360000
    assert fee_below["pre_discount_total_cents"] == 99360000
    assert fee_below["discount_bps_applied"] == 150
    assert fee_below["discount_cents"] == 1490400
    assert fee_below["assessed_amount_cents"] == 97869600

    # 4.05 unit equivalents: a base still under the boundary, but the surcharge
    # carries the pre-discount total across it into the 400 bps tier.
    assert fee_above["unit_equivalent_bps"] == 40500
    assert fee_above["base_amount_cents"] == 97200000
    assert fee_above["base_amount_cents"] < 100000000
    assert fee_above["surcharge_cents"] == 3402000
    assert fee_above["pre_discount_total_cents"] == 100602000
    assert fee_above["discount_bps_applied"] == 400
    assert fee_above["discount_cents"] == 4024080
    assert fee_above["assessed_amount_cents"] == 96577920

    # The bigger obligation ends up owing less, which only the post-surcharge
    # scan produces: scanning the base alone would have priced both at 150 bps.
    assert fee_above["base_amount_cents"] > fee_below["base_amount_cents"]
    assert fee_above["assessed_amount_cents"] < fee_below["assessed_amount_cents"]
    assert (
        fee_below["assessed_amount_cents"] - fee_above["assessed_amount_cents"] == 1291680
    )

    # A 500 bps residual lands in the opening 0 bps tier, so no discount at all.
    assert fee_fraction["unit_equivalent_bps"] == 500
    assert fee_fraction["base_amount_cents"] == 1200000
    assert fee_fraction["surcharge_cents"] == 42000
    assert fee_fraction["pre_discount_total_cents"] == 1242000
    assert fee_fraction["discount_bps_applied"] == 0
    assert fee_fraction["discount_cents"] == 0
    assert fee_fraction["assessed_amount_cents"] == 1242000

    for fee in (fee_below, fee_above, fee_fraction):
        assert_fee_pricing_chain(fee)
        assert_money_cents(fee["assessed_amount_cents"], "assessed_amount_cents")
        # No surcharge reached the cap, so the cap never disturbed the tier scan.
        assert fee["surcharge_cents"] < 5000000
        assert fee["state"] == "ASSESSED"
        assert fee["paid_amount_cents"] == 0
        assert fee["ordinance_id"] == ordinance_id
        assert fee["due_date"] == date_plus_days("2026-08-01", 45) == "2026-09-15"


def test_the_waterfall_conserves_every_cent_on_an_underwater_sale():
    """Net proceeds below the equity basis leave buckets 2, 3 and 4 at zero and lose nothing.

    PRD: "The four buckets always sum to `net_proceeds_cents` exactly, for every input including an underwater sale where buckets 2, 3 and 4 all collapse to 0, because bucket 4 absorbs the remainder rather than rounding on its own."

    Design: Corner/calculations/the_waterfall_conserves_every_cent_on_an_underwater_sale
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.restricted_ownership_unit(
        unit_overrides={
            "unit_number": "UW-101",
            "bedrooms": 2,
            "sqft": 900,
            "market_comparable_sqft": 1000,
            "tenure": "OWNERSHIP",
            "affordability_level_bps": 5000,
        },
        original_purchase_price_cents=OWNERSHIP_BASIS_CENTS,
        restriction_recorded_at="2026-08-01",
        project_overrides={
            "name": "Underwater Walk",
            "zoning_district": "R-2",
            "total_units": 10,
            "approval_date": "2026-01-15",
        },
        agreement_overrides={
            "term_years": 45,
            "resale_formula": "AMI_INDEXED",
            "owner_appreciation_share_bps": 2500,
            "max_refinance_ltv_bps": 9000,
        },
    )
    unit_id = ctx["unit"]["id"]

    seller = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    seller_cert = fixtures.certify_income(
        seller["id"], unit_id, certified_income_cents=6000000,
        contract_rent_cents=0, effective_date="2026-08-01",
    )

    resale = validate_success(
        api_client.create_resale(
            factories.create_resale_payload(
                unit_id,
                fixtures.live_unit(unit_id)["version"],
                proposed_price_cents=32000000,
                appraised_value_cents=40000000,
                capital_improvements_cents=0,
                deferred_maintenance_cents=0,
                broker_fee_cents=1000000,
            ),
            headers=make_resident_headers(seller["id"]),
        ),
        201,
    )
    assert resale["seller_household_id"] == seller["id"]
    assert resale["max_resale_price_cents"] == OWNERSHIP_BASIS_CENTS

    approved = get_success_data(api_client.approve_resale_price(resale["id"], headers=HCO))
    assert approved["state"] == "PRICE_APPROVED"
    waived = get_success_data(api_client.rofr_decision(resale["id"], "WAIVE", headers=PA))
    assert waived["state"] == "ROFR_WAIVED"
    assert waived["rofr_auto_waived"] is False

    buyer = fixtures.register_household(
        applicant_name="Ines Novak", household_size=2, gross_annual_income_cents=5000000
    )
    buyer_cert = fixtures.certify_income(
        buyer["id"], unit_id, certified_income_cents=5000000,
        contract_rent_cents=0, effective_date="2026-08-01",
    )
    # The officer who approved the price may not certify the buyer.
    certified = get_success_data(
        api_client.certify_buyer(resale["id"], buyer["id"], buyer_cert["id"], headers=HCO2)
    )
    assert certified["state"] == "BUYER_CERTIFIED"

    closed = get_success_data(api_client.close_resale(resale["id"], headers=HCO2))
    assert closed["state"] == "CLOSED"
    assert _calendar_day(closed["closed_at"]) == "2026-08-01"

    # 32000000 asked minus a 1000000 broker fee leaves 31000000 net, which is
    # less than the 32500000 equity basis, so bucket 1 swallows all of it.
    assert closed["net_proceeds_cents"] == 32000000 - 1000000 == 31000000
    assert closed["seller_equity_cents"] == 31000000
    assert closed["seller_improvement_credit_cents"] == 0
    assert closed["seller_appreciation_share_cents"] == 0
    assert closed["city_recapture_cents"] == 0
    buckets = (
        closed["seller_equity_cents"],
        closed["seller_improvement_credit_cents"],
        closed["seller_appreciation_share_cents"],
        closed["city_recapture_cents"],
    )
    assert sum(buckets) == closed["net_proceeds_cents"]
    assert_waterfall_conserved(closed)
    for value in buckets:
        assert_money_cents(value, "waterfall bucket")

    # The basis resets downward to the price actually paid, and the unit changes hands.
    unit = fixtures.live_unit(unit_id)
    assert unit["original_purchase_price_cents"] == 32000000
    assert unit["occupant_household_id"] == buyer["id"]
    assert_unit_dimensions(unit, occupancy_status="OCCUPIED", restriction_state="RECORDED")

    assert get_success_data(
        api_client.get_certification(seller_cert["id"], headers=HCO)
    )["state"] == "SUPERSEDED"
    assert get_success_data(
        api_client.get_certification(buyer_cert["id"], headers=HCO)
    )["state"] == "CERTIFIED"

    # Nothing was recaptured, so the fund never moved.
    fund = fixtures.fund_summary(headers=AUDITOR)
    assert fund["total_recapture_cents"] == 0
    assert fund["total_paid_fees_cents"] == 0
    assert fund["total_inflow_cents"] == 0
    assert fund["unencumbered_balance_cents"] == 0
    assert fund["admin_cap_cents"] == 0


def test_equal_preference_scores_are_ranked_by_created_at_ascending():
    """With no preference categories every score ties at zero and creation order decides.

    PRD: "Recompute each pooled household's `preference_score` against the plan's `preference_categories`, then order the pool by `preference_score` descending, breaking ties by `created_at` ascending — a household's own `id` never participates in the ordering — and assign each household its 1-based `rank_position` in that order."

    Design: Corner/calculations/equal_preference_scores_are_ranked_by_created_at_ascending
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.agreement_recorded_project(
        project_overrides={
            "name": "Tiebreak Terrace",
            "zoning_district": "R-2",
            "total_units": 20,
            "approval_date": "2026-01-15",
        }
    )
    project_id = ctx["project"]["id"]
    agreement_id = ctx["agreement"]["id"]
    unit_one = fixtures.add_unit(
        project_id, agreement_id, unit_number="TB-101", bedrooms=2, sqft=900,
        market_comparable_sqft=1000, tenure="RENTAL", affordability_level_bps=5000,
    )
    unit_two = fixtures.add_unit(
        project_id, agreement_id, unit_number="TB-102", bedrooms=2, sqft=900,
        market_comparable_sqft=1000, tenure="RENTAL", affordability_level_bps=5000,
    )

    # The plan declares no preference categories at all, so no claim can score.
    plan_payload = factories.create_marketing_plan_payload(
        project_id,
        lottery_open_at="2026-08-05T00:00:00Z",
        lottery_close_at="2026-08-20T00:00:00Z",
    )
    plan_payload.pop("preference_categories")
    plan = validate_success(api_client.create_marketing_plan(plan_payload, headers=DEV), 201)
    plan = get_success_data(api_client.review_marketing_plan(plan["id"], "APPROVE", headers=HCO))
    assert plan["state"] == "APPROVED"

    lottery = validate_success(
        api_client.create_lottery_event(
            factories.create_lottery_event_payload(
                plan["id"], units_offered=2, eligibility_level_bps=5000
            ),
            headers=PA,
        ),
        201,
    )
    assert lottery["round_seq"] == 1

    # Registering on four successive logical days makes created_at strictly
    # ascending, which is the only thing left to break the score tie.
    fixtures.set_clock("2026-08-06T00:00:00Z")
    first = fixtures.register_household(
        applicant_name="Ada Nakamura", household_size=3, gross_annual_income_cents=6000000
    )
    fixtures.set_clock("2026-08-07T00:00:00Z")
    second = fixtures.register_household(
        applicant_name="Bo Okafor", household_size=2, gross_annual_income_cents=5000000
    )
    fixtures.set_clock("2026-08-08T00:00:00Z")
    third = fixtures.register_household(
        applicant_name="Cai Delgado", household_size=3, gross_annual_income_cents=6200000
    )
    fixtures.set_clock("2026-08-09T00:00:00Z")
    over_income = fixtures.register_household(
        applicant_name="Dara Whitfield", household_size=3, gross_annual_income_cents=6400000
    )

    fixtures.set_clock("2026-08-10T00:00:00Z")
    fixtures.apply_to_lottery(first["id"], lottery["id"], ["LIVE_WORK"])
    fixtures.apply_to_lottery(second["id"], lottery["id"], ["DISPLACED"])
    fixtures.apply_to_lottery(third["id"], lottery["id"], ["LIVE_WORK", "DISPLACED"])
    fixtures.apply_to_lottery(over_income["id"], lottery["id"], ["PUBLIC_EMPLOYEE"])

    fixtures.set_clock("2026-08-20T00:00:00Z")
    drawn = get_success_data(api_client.draw_lottery(lottery["id"], headers=PA))
    assert drawn["state"] == "DRAWN"
    assert drawn["round_seq"] == 1

    # Every claim scored nothing, so the three eligible households tie at zero
    # and rank purely in registration order.
    assert drawn["selected_household_ids"] == [first["id"], second["id"]]
    assert drawn["waitlisted_household_ids"] == [third["id"]]

    rows = {
        name: get_success_data(api_client.get_household(household["id"], headers=PA))
        for name, household in (
            ("first", first), ("second", second), ("third", third),
            ("over_income", over_income),
        )
    }
    for row in rows.values():
        assert row["preference_score"] == 0
    assert rows["first"]["rank_position"] == 1
    assert rows["second"]["rank_position"] == 2
    assert rows["third"]["rank_position"] == 3
    assert rows["first"]["state"] == "SELECTED"
    assert rows["second"]["state"] == "SELECTED"
    assert rows["third"]["state"] == "WAITLISTED"
    created = [
        parse_instant(rows[name]["created_at"])
        for name in ("first", "second", "third")
    ]
    assert created == sorted(created)

    # The fourth household's income exceeds its own size's limit, so it never
    # entered the pool: no rank, and neither list names it.
    assert rows["over_income"]["state"] == "APPLIED"
    assert rows["over_income"]["rank_position"] is None
    assert rows["over_income"]["gross_annual_income_cents"] > INCOME_LIMIT_SIZE_3_AT_5000_BPS
    assert over_income["id"] not in drawn["selected_household_ids"]
    assert over_income["id"] not in drawn["waitlisted_household_ids"]

    # Units pair rank-for-rank in ascending unit_number order.
    reserved_one = fixtures.live_unit(unit_one["id"])
    reserved_two = fixtures.live_unit(unit_two["id"])
    assert reserved_one["occupant_household_id"] == first["id"]
    assert reserved_two["occupant_household_id"] == second["id"]
    assert_unit_dimensions(reserved_one, occupancy_status="RESERVED")
    assert_unit_dimensions(reserved_two, occupancy_status="RESERVED")


def test_posture_clauses_are_evaluated_in_order_so_enforcement_outranks_deficiency():
    """A project short of its obligation and holding a bad unit reports UNDER_ENFORCEMENT.

    PRD: "Clause order is normative, and clause 3 is the one that surprises people: enforcement outranks deficiency, so a project that is both short of its obligation *and* holding an out-of-compliance unit reports `UNDER_ENFORCEMENT`, not `DEFICIENT`."

    Design: Corner/calculations/posture_clauses_are_evaluated_in_order_so_enforcement_outranks_deficiency
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.agreement_recorded_project(
        project_overrides={
            "name": "Clause Order Commons",
            "zoning_district": "R-4",
            "total_units": 27,
            "approval_date": "2026-01-15",
        }
    )
    project_id = ctx["project"]["id"]
    agreement_id = ctx["agreement"]["id"]

    # 27 units at 1500 bps is 40500 raw bps: four whole dwellings and a 500 bps
    # residual that does not round up, so four units can never reach the whole.
    assert ctx["project"]["total_obligation_bps"] == 40500
    assert ctx["project"]["required_affordable_units"] == 4
    assert ctx["project"]["fractional_obligation_bps"] == 500

    units = [
        fixtures.add_unit(
            project_id, agreement_id, unit_number=number, bedrooms=2, sqft=900,
            market_comparable_sqft=1000, tenure="RENTAL", affordability_level_bps=5000,
        )
        for number in ("EN-101", "EN-102", "EN-103", "EN-104")
    ]
    monitored_unit_id = units[0]["id"]

    household = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    fixtures.certify_income(
        household["id"], monitored_unit_id, certified_income_cents=6000000,
        contract_rent_cents=140000, effective_date="2026-08-01",
    )
    project = fixtures.live_project(project_id)
    assert project["onsite_unit_equivalents_bps"] == 40000
    assert project["fee_covered_equivalents_bps"] == 0
    # Clause 4 already bites: 40000 + 0 is strictly short of 40500.
    assert_project_state(
        project, state="MONITORING", applicability="SUBJECT",
        compliance_posture="DEFICIENT",
    )
    assert_obligation_equivalents_conserved(project)

    fixtures.set_clock("2027-03-01T00:00:00Z")
    review = validate_success(
        api_client.create_monitoring_review(
            factories.create_monitoring_review_payload(
                monitored_unit_id, review_year=2027, reported_rent_cents=165000,
                reported_income_cents=6000000, occupancy_verified=True,
            ),
            headers=HCO,
        ),
        201,
    )
    # Only the rent finding fires: 6000000 is under the 140-percent recertification
    # ceiling and occupancy was proven.
    assert review["state"] == "FINDING_ISSUED"
    assert review["finding_types"] == ["RENT_OVERCHARGE"]
    assert review["overcharge_monthly_cents"] == 165000 - MAX_ALLOWED_RENT_2BR_AT_5000_BPS == 21128
    assert review["penalty_at_base_cents"] == 21128 * 3 + THRESHOLDS["FLAT_MONTHLY_PENALTY_CENTS"]
    assert review["penalty_at_base_cents"] == 88384
    assert review["penalty_at_base_cents"] < THRESHOLDS["PENALTY_EXTENSION_THRESHOLD_CENTS"]
    assert review["cure_extension_days"] == 0
    frozen_deadline = review["cure_deadline"]
    assert _calendar_day(frozen_deadline) == date_plus_days("2027-03-01", 30) == "2027-03-31"

    # A FINDING_OPEN unit is not yet out of compliance, so clause 4 still wins.
    assert_unit_dimensions(fixtures.live_unit(monitored_unit_id), compliance_status="FINDING_OPEN")
    assert_project_state(fixtures.live_project(project_id), compliance_posture="DEFICIENT")

    cured = get_success_data(api_client.submit_cure(review["id"], 140000, headers=DEV))
    assert cured["state"] == "CURE_SUBMITTED"
    assert cured["penalty_final_cents"] == 88384
    assert_unit_dimensions(fixtures.live_unit(monitored_unit_id), compliance_status="CURE_PENDING")
    assert_project_state(fixtures.live_project(project_id), compliance_posture="DEFICIENT")

    escalated = get_success_data(api_client.escalate_review(review["id"], headers=HCO2))
    assert escalated["state"] == "ESCALATED"
    assert_unit_dimensions(
        fixtures.live_unit(monitored_unit_id), compliance_status="OUT_OF_COMPLIANCE"
    )

    # Both conditions now hold at once, and clause 3 outranks clause 4.
    enforced = fixtures.live_project(project_id)
    assert enforced["onsite_unit_equivalents_bps"] == 40000
    assert enforced["fee_covered_equivalents_bps"] == 0
    assert (
        enforced["onsite_unit_equivalents_bps"] + enforced["fee_covered_equivalents_bps"]
        < enforced["total_obligation_bps"]
    )
    assert_project_state(enforced, compliance_posture="UNDER_ENFORCEMENT")
    assert_obligation_equivalents_conserved(enforced)

    # Leaving enforcement drops the project back to the clause it was hiding.
    resubmitted = get_success_data(api_client.submit_cure(review["id"], 139000, headers=DEV))
    assert resubmitted["state"] == "CURE_SUBMITTED"
    assert_unit_dimensions(fixtures.live_unit(monitored_unit_id), compliance_status="CURE_PENDING")
    assert_project_state(fixtures.live_project(project_id), compliance_posture="DEFICIENT")

    cleared = get_success_data(api_client.clear_cure(review["id"], headers=HCO2))
    assert cleared["state"] == "CURED"
    assert_unit_dimensions(fixtures.live_unit(monitored_unit_id), compliance_status="COMPLIANT")
    assert_project_state(fixtures.live_project(project_id), compliance_posture="DEFICIENT")

    # The deadline frozen at issue never moved through any of those transitions.
    for row in (cured, escalated, resubmitted, cleared):
        assert row["cure_extension_days"] == 0
        assert same_instant(row["cure_deadline"], frozen_deadline)
