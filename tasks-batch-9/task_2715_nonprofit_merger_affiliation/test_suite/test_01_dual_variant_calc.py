"""Two named variants of one calculation over identical stored rows.

PRD 3.2 defines the SCREENING and DILIGENCE_ADJUSTED alignment variants, which
differ in program admission, exposure netting and the restricted-funds
deduction. PRD 3.6 defines the DONOR_CONSENT and JUDICIAL_MODIFICATION release
rules, which differ for a PERM_ENDOWMENT.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    DILIGENCE_LEAD,
    INTEGRATION_MANAGER,
    TRUST_COUNSEL,
    make_strategy_officer_headers,
)

# PRD 3.6: a permanent endowment whose historic dollar value caps judicial release.
ENDOWMENT = {
    "fund_type": "PERM_ENDOWMENT",
    "principal_cents": 50000000,
    "accumulated_appreciation_cents": 12000000,
    "historic_dollar_value_cents": 45000000,
    "restriction_purpose_code": "YM-MENTOR_STIPENDS",
}
FUND_VALUE_CENTS = 62000000
JUDICIAL_RELEASE_CENTS = 20150000


def _deal_with_five_programs(api):
    """Two identically-missioned CA parties, five programs, one sunset, one open finding."""
    ctx = fx.setup_deal_diligence(api)
    org_a, org_b, deal_id = ctx["org_a"]["id"], ctx["org_b"]["id"], ctx["deal"]["id"]
    fx.create_program(
        api, org_a, name="A Mentoring", service_category="YOUTH_MENTORING",
        county_code="CA-ALAMEDA",
    )
    fx.create_program(
        api, org_a, name="A Pantry", service_category="FOOD_SECURITY",
        county_code="CA-ALAMEDA",
    )
    fx.create_program(
        api, org_b, name="B Mentoring", service_category="YOUTH_MENTORING",
        county_code="CA-ALAMEDA",
    )
    prog_b2 = fx.create_program(
        api, org_b, name="B Pantry", service_category="FOOD_SECURITY",
        county_code="CA-ALAMEDA",
    )
    fx.create_program(
        api, org_b, name="B Housing", service_category="HOUSING",
        county_code="CA-ALAMEDA",
    )
    validate_success(
        api.continuity_decision(
            prog_b2["id"],
            f.continuity_decision_payload(deal_id, disposition="SUNSET"),
            INTEGRATION_MANAGER,
        )
    )
    validate_success(
        api.create_diligence_request(f.diligence_request_payload(deal_id), DILIGENCE_LEAD), 201
    )
    ctx["deal"] = fx.read_deal(api, deal_id)
    return ctx


def _snapshot(api, ctx, variant):
    return validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(ctx["deal"]["id"], variant),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        ),
        201,
    )


def test_screening_variant_admits_every_program_and_nets_no_exposure(api):
    """A SCREENING snapshot admits all five programs and reads zero open exposure.

    PRD 3.2: "SCREENING admits every program of both parties regardless of
    continuity_status", and "open_diligence_exposure_cents ... is always 0 for a
    SCREENING snapshot". With five admitted programs, two overlapping
    initiator/target pairs and a denominator of min(2, 3) = 2, the index caps at
    1.0000 and thirty points times one minus twice the absolute difference from
    0.5 yields 0.00 overlap points. Identical mission codes earn 40.00 points and
    a SCREENING snapshot never applies the restricted-funds deduction. Combined
    unrestricted assets of 99916670 cents over a combined monthly expense of
    16666668 cents give reserve_months 5.99, which sits in the "at least three but
    under six" tier worth 20.00 points, so composite_score is 60.00 and the band
    "at least 60.00 but under 80" makes composite_rating MODERATE.

    Design: Difficulty/dual_variant_calc/alignment_screening_vs_diligence_adjusted_variant_divergence
    """
    ctx = _deal_with_five_programs(api)
    scr = _snapshot(api, ctx, "SCREENING")

    a.assert_field(scr, "variant", "SCREENING")
    a.assert_field(scr, "included_program_count", 5)
    a.assert_field(scr, "overlap_pair_count", 2)
    a.assert_decimal_equals(scr["program_overlap_index"], 1.0000, 4, "program_overlap_index")
    a.assert_decimal_equals(scr["program_overlap_points"], 0.00, 2, "program_overlap_points")
    a.assert_decimal_equals(scr["mission_alignment_points"], 40.00, 2, "mission_alignment_points")
    a.assert_money_equals(
        scr["open_diligence_exposure_cents"], 0, "open_diligence_exposure_cents"
    )
    a.assert_money_equals(
        scr["combined_monthly_expense_cents"], 16666668, "combined_monthly_expense_cents"
    )
    a.assert_money_equals(
        scr["available_unrestricted_cents"], 99916670, "available_unrestricted_cents"
    )
    a.assert_decimal_equals(scr["reserve_months"], 5.99, 2, "reserve_months")
    a.assert_decimal_equals(scr["sustainability_points"], 20.00, 2, "sustainability_points")
    a.assert_decimal_equals(scr["composite_score"], 60.00, 2, "composite_score")
    a.assert_field(scr, "composite_rating", "MODERATE")


def test_diligence_adjusted_variant_drops_the_sunset_program_and_nets_open_exposure(api):
    """A DILIGENCE_ADJUSTED snapshot drops the sunset program and subtracts open exposure.

    PRD 3.2: "DILIGENCE_ADJUSTED admits only programs whose continuity_status is
    ACTIVE or PLANNED_TRANSFER", and for that variant open exposure "is the sum of
    exposure_cents over the deal's diligence findings whose status is OPEN,
    RESPONDED or ESCALATED". PRD 3.8 confirms "a PLANNED_SUNSET program is dropped
    from the DILIGENCE_ADJUSTED inclusion set of every later assessment". Dropping
    the target's sunset pantry leaves four admitted programs, one overlapping pair
    and a denominator of min(2, 2) = 2, so the index is exactly 0.5000 and the
    overlap component peaks at the full 30.00. Netting the 29916670-cent open
    finding leaves 70000000 cents available, which over 16666668 cents of combined
    monthly expense is reserve_months 4.20 and 20.00 sustainability points, so
    composite_score is 90.00 and the "at least 80.00" band makes it STRONG.

    Design: Difficulty/dual_variant_calc/alignment_screening_vs_diligence_adjusted_variant_divergence
    """
    ctx = _deal_with_five_programs(api)
    adj = _snapshot(api, ctx, "DILIGENCE_ADJUSTED")

    a.assert_field(adj, "variant", "DILIGENCE_ADJUSTED")
    a.assert_field(adj, "included_program_count", 4)
    a.assert_field(adj, "overlap_pair_count", 1)
    a.assert_decimal_equals(adj["program_overlap_index"], 0.5000, 4, "program_overlap_index")
    a.assert_decimal_equals(adj["program_overlap_points"], 30.00, 2, "program_overlap_points")
    a.assert_decimal_equals(adj["mission_alignment_points"], 40.00, 2, "mission_alignment_points")
    a.assert_money_equals(
        adj["open_diligence_exposure_cents"], 29916670, "open_diligence_exposure_cents"
    )
    a.assert_money_equals(
        adj["available_unrestricted_cents"], 70000000, "available_unrestricted_cents"
    )
    a.assert_decimal_equals(adj["reserve_months"], 4.20, 2, "reserve_months")
    a.assert_decimal_equals(adj["sustainability_points"], 20.00, 2, "sustainability_points")
    a.assert_decimal_equals(adj["composite_score"], 90.00, 2, "composite_score")
    a.assert_field(adj, "composite_rating", "STRONG")


def test_one_database_yields_two_scores_and_two_ratings(api):
    """The same stored rows produce 60.00 MODERATE and 90.00 STRONG side by side.

    PRD 3.2: "Because the two variants differ in program admission, in exposure
    netting and in the restricted-funds deduction, the same stored data
    legitimately produces two different composite_score values and can produce two
    different composite_rating values." Taken back to back against one unchanged
    database, the screening snapshot scores 60.00 (MODERATE) and the
    diligence-adjusted snapshot scores 90.00 (STRONG), a thirty-point divergence
    driven only by the variant. Each new snapshot also "receives a sequence_no
    equal to one plus the count of prior snapshots of the same deal and the same
    variant", so the two variants number independently.

    Design: Difficulty/dual_variant_calc/alignment_screening_vs_diligence_adjusted_variant_divergence
    """
    ctx = _deal_with_five_programs(api)
    scr = _snapshot(api, ctx, "SCREENING")
    adj = _snapshot(api, ctx, "DILIGENCE_ADJUSTED")

    a.assert_decimal_equals(scr["composite_score"], 60.00, 2, "screening composite_score")
    a.assert_decimal_equals(adj["composite_score"], 90.00, 2, "adjusted composite_score")
    assert scr["composite_score"] != adj["composite_score"]
    a.assert_field(scr, "composite_rating", "MODERATE")
    a.assert_field(adj, "composite_rating", "STRONG")
    assert adj["included_program_count"] < scr["included_program_count"]
    assert adj["open_diligence_exposure_cents"] > scr["open_diligence_exposure_cents"]
    # The screening snapshot of the setup already consumed sequence_no 1 of its variant.
    a.assert_field(adj, "sequence_no", 1)
    a.assert_field(scr, "sequence_no", 2)


def test_donor_consent_releases_the_entire_endowment_value(api):
    """Donor consent releases principal plus appreciation and ignores the historic dollar value.

    PRD 3.6: on GRANTED "transferable_amount_cents is fixed at the full fund value
    - principal_cents plus accumulated_appreciation_cents, with
    historic_dollar_value_cents ignored entirely, because a consenting donor can
    release their own appreciation", and "Under a DONOR_CONSENT basis,
    transferable_amount_cents is the entire fund value". For a PERM_ENDOWMENT of
    50000000 principal and 12000000 appreciation carrying a 45000000 historic
    dollar value, the consent branch therefore releases the whole 62000000 cents.

    Design: Difficulty/dual_variant_calc/restricted_fund_donor_consent_vs_judicial_modification_divergence
    """
    org = fx.create_organization(api)
    fund = fx.setup_fund_consent_granted(
        api, org["id"], fund_name="Delaney Endowment", restriction_conflict=False, **ENDOWMENT
    )

    a.assert_field(fund, "transfer_status", "CONSENT_GRANTED")
    a.assert_field(fund, "consent_decision", "GRANTED")
    a.assert_money_equals(
        fund["transferable_amount_cents"], FUND_VALUE_CENTS, "transferable_amount_cents"
    )


def test_judicial_modification_caps_a_permanent_endowment_release(api):
    """Judicial modification of a permanent endowment releases only the excess plus a truncated slice.

    PRD 3.6: "For a PERM_ENDOWMENT - the one class whose judicial release is capped
    - the releasable amount is the excess of the fund value over
    historic_dollar_value_cents, floored at 0 ..., plus a capped slice equal to
    seven percent of historic_dollar_value_cents, that slice being truncated toward
    zero rather than rounded half up." On identical stored inputs that is
    62000000 - 45000000 = 17000000 plus seven percent of 45000000 = 3150000, so
    transferable_amount_cents is 20150000. PRD 3.6 also places the join at
    "PETITION_FILED -> MODIFIED" storing the outcome in court_decision.

    Design: Difficulty/dual_variant_calc/restricted_fund_donor_consent_vs_judicial_modification_divergence
    """
    org = fx.create_organization(api)
    fund = fx.create_fund(
        api, org["id"], fund_name="Jarvis Endowment", restriction_conflict=True, **ENDOWMENT
    )
    validate_success(api.seek_consent(fund["id"], f.seek_consent_payload(), TRUST_COUNSEL))
    validate_success(
        api.record_consent(fund["id"], f.record_consent_payload("DENIED"), TRUST_COUNSEL)
    )
    validate_success(api.file_petition(fund["id"], f.file_petition_payload(), TRUST_COUNSEL))
    fund = validate_success(
        api.record_court_decision(
            fund["id"],
            f.court_decision_payload(
                "GRANTED_WITH_CONDITIONS", modified_purpose_code="YM-YOUTH_PROGRAMS"
            ),
            TRUST_COUNSEL,
        )
    )

    a.assert_field(fund, "transfer_status", "MODIFIED")
    a.assert_field(fund, "court_decision", "GRANTED_WITH_CONDITIONS")
    a.assert_money_equals(
        fund["transferable_amount_cents"], JUDICIAL_RELEASE_CENTS, "transferable_amount_cents"
    )


def test_the_two_authorities_diverge_on_byte_identical_endowment_inputs(api):
    """On identical endowment data the judicial route releases strictly less than consent.

    PRD 3.6: "The consequence for a permanent endowment with identical stored data
    is that the judicial route releases strictly less than the consent route." Two
    endowments registered with the same principal, appreciation and historic dollar
    value release 62000000 under DONOR_CONSENT and 20150000 under
    JUDICIAL_MODIFICATION, a divergence of 41850000 cents attributable entirely to
    the authority relied on.

    Design: Difficulty/dual_variant_calc/restricted_fund_donor_consent_vs_judicial_modification_divergence
    """
    org = fx.create_organization(api)
    fund_d = fx.setup_fund_consent_granted(
        api, org["id"], fund_name="Delaney Endowment", restriction_conflict=False, **ENDOWMENT
    )
    fund_j = fx.setup_fund_modified(
        api, org["id"], fund_name="Jarvis Endowment", restriction_conflict=True, **ENDOWMENT
    )

    a.assert_field(fund_d, "transfer_status", "CONSENT_GRANTED")
    a.assert_field(fund_j, "transfer_status", "MODIFIED")
    a.assert_money_equals(
        fund_d["transferable_amount_cents"], FUND_VALUE_CENTS, "consent transferable_amount_cents"
    )
    a.assert_money_equals(
        fund_j["transferable_amount_cents"],
        JUDICIAL_RELEASE_CENTS,
        "judicial transferable_amount_cents",
    )
    assert fund_j["transferable_amount_cents"] < fund_d["transferable_amount_cents"]
    assert (
        fund_d["transferable_amount_cents"] - fund_j["transferable_amount_cents"] == 41850000
    )


def test_judicial_modification_of_a_temp_restricted_fund_releases_everything(api):
    """The judicial cap applies only to a permanent endowment, not to a temp-restricted fund.

    PRD 3.6: "For a TEMP_RESTRICTED or CONDITIONAL_PLEDGE fund the judicial rule
    releases the entire fund value, the same as consent would." A TEMP_RESTRICTED
    fund carrying the identical 45000000 historic dollar value therefore releases
    the whole 62000000 cents down the judicial branch, proving the historic dollar
    value enters the release rule only for the PERM_ENDOWMENT class.

    Design: Difficulty/dual_variant_calc/restricted_fund_donor_consent_vs_judicial_modification_divergence
    """
    org = fx.create_organization(api)
    inputs = dict(ENDOWMENT, fund_type="TEMP_RESTRICTED")
    fund = fx.setup_fund_modified(
        api, org["id"], fund_name="Ortiz Program Fund", restriction_conflict=True, **inputs
    )

    a.assert_field(fund, "transfer_status", "MODIFIED")
    a.assert_money_equals(
        fund["transferable_amount_cents"], FUND_VALUE_CENTS, "transferable_amount_cents"
    )
    assert fund["transferable_amount_cents"] != JUDICIAL_RELEASE_CENTS
