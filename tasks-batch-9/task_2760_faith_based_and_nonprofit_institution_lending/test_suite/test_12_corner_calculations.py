"""
Queue B — §1.9 section ``calculations``.

The pinned arithmetic of the domain, exercised at the points where a plausible
misreading changes the answer: the three-step collateral valuation and its
score/type-cap tie, the zero advance-rate cap, the strict seasoning boundary,
the two donor-restricted exclusions inside the giving figures, and the weighted
mission impact score.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.assertions import (
    assert_created_fresh,
    assert_fields,
    assert_integer_cents,
    assert_nulls,
    assert_score,
)
from test_helpers.factories import (
    REFERENCE_AUDITED_QUARTERS,
    collateral_asset_payload,
    covenant_test_payload,
    forbearance_payload,
)
from test_helpers.fixtures import (
    build_collateral_asset,
    build_covenant,
    build_giving_periods,
    build_institution,
    chain_through_loan,
    reset_clock,
)
from test_helpers.test_users import CREDIT_ANALYST, LOAN_SERVICER

# The institution carries no endowment and no program count unless a test needs
# one; ``None`` removes the key so the endpoint's declared default applies.
PLAIN_INSTITUTION = {
    "requires_denominational_approval": None,
    "community_program_count": None,
    "endowment_market_value_cents": None,
}


def test_parsonage_whose_score_rate_equals_its_type_cap_takes_the_plain_advance_rate(api):
    """
    A PARSONAGE at alternative_use_score 4 proposes 70 percent and is capped at 70
    percent, so the tie resolves to the same rate either way; its 92-day-old
    appraisal is inside the seasoning window, so no haircut follows.

    PRD §3.4: "The alternative-use score proposes a rate — 40 percent at a score of 1, 50 percent at 2, 60 percent at 3, 70 percent at 4 and 75 percent at 5 — and the asset type imposes a ceiling on it: 55 percent for a `SANCTUARY`, 65 percent for an `EDUCATION_WING`, 70 percent for a `PARSONAGE`, 50 percent for `LAND`, 60 percent for a `FELLOWSHIP_HALL` and 0 percent for a `DONOR_RESTRICTED_ENDOWMENT`."
    PRD §3.4: "The effective advance rate is whichever of the two is lower, so a readily convertible sanctuary is still capped at 55 percent, and a donor-restricted endowment is valued at nothing whatever its score."
    PRD §3.4: "An asset with no current assignment is valued as though it would take a first lien."
    PRD §3.4: "When `appraisal_age_days` is strictly greater than 365 — that is, when the appraisal report is more than a year old on the logical clock — the running figure is multiplied by 90 percent; at 365 days or fewer no seasoning discount applies."
    PRD §3.4: "Registration computes `appraisal_age_days` and `lending_value_cents` immediately, and leaves `assigned_loan_application_id`, `lien_position`, `lien_effective_from` and `lien_effective_to` all null with `lien_history` an empty list."

    Design: Corner/calculations/parsonage_first_lien_value_where_score_rate_and_type_cap_tie
    """
    reset_clock(api)
    institution = build_institution(api, **PLAIN_INSTITUTION)

    response = api.create_collateral_asset(
        collateral_asset_payload(
            institution["id"],
            asset_type="PARSONAGE",
            description_label="Pastor residence on Elm Street",
            appraised_value_cents=100000000,
            appraisal_date="2026-05-01T00:00:00Z",
            alternative_use_score=4,
        ),
        CREDIT_ANALYST,
    )
    asset = get_success_data(response, 201)

    # 2026-05-01 to 2026-08-01 on the frozen clock is 31 + 30 + 31 whole days.
    assert_fields(
        asset,
        asset_type="PARSONAGE",
        appraised_value_cents=100000000,
        alternative_use_score=4,
        appraisal_age_days=92,
        # min(0.70 proposed, 0.70 cap) applied to 100000000, first-lien factor
        # 1.00, seasoning factor 1.00 at 92 days.
        lending_value_cents=70000000,
    )
    assert_integer_cents(asset, "appraised_value_cents", "lending_value_cents")
    # The value already assumes a first lien even though none is recorded yet.
    assert_nulls(
        asset,
        "assigned_loan_application_id",
        "lien_position",
        "lien_effective_from",
        "lien_effective_to",
    )
    assert asset["lien_history"] == []
    assert_created_fresh(asset)


def test_donor_restricted_endowment_values_at_zero_however_convertible_it_is(api):
    """
    A 900000000-cent endowment at the most convertible alternative_use_score of 5
    proposes 75 percent, but its type ceiling of 0 percent wins, so the recorded
    lending value is exactly 0 rather than 675000000.

    PRD §2.7: "On the collateral side, an asset whose `asset_type` is `DONOR_RESTRICTED_ENDOWMENT` carries an advance-rate cap of zero, so its `lending_value_cents` is always 0, and it is barred from assignment outright: an attempt to pledge one to a loan application is rejected with `ERR_ENDOWMENT_COLLATERAL_INELIGIBLE` (HTTP 422)."
    PRD §3.4: "The effective advance rate is whichever of the two is lower, so a readily convertible sanctuary is still capped at 55 percent, and a donor-restricted endowment is valued at nothing whatever its score."
    PRD §3.4: "Registration computes `appraisal_age_days` and `lending_value_cents` immediately, and leaves `assigned_loan_application_id`, `lien_position`, `lien_effective_from` and `lien_effective_to` all null with `lien_history` an empty list."

    Design: Corner/calculations/donor_restricted_endowment_asset_values_to_zero_through_its_type_cap
    """
    reset_clock(api)
    institution = build_institution(
        api,
        requires_denominational_approval=None,
        community_program_count=None,
        endowment_market_value_cents=900000000,
    )

    response = api.create_collateral_asset(
        collateral_asset_payload(
            institution["id"],
            asset_type="DONOR_RESTRICTED_ENDOWMENT",
            description_label="Hargrove memorial endowment fund",
            appraised_value_cents=900000000,
            appraisal_date="2026-05-01T00:00:00Z",
            alternative_use_score=5,
        ),
        CREDIT_ANALYST,
    )
    # The asset may be recorded; it simply cannot be lent against.
    asset = get_success_data(response, 201)

    assert_fields(
        asset,
        asset_type="DONOR_RESTRICTED_ENDOWMENT",
        alternative_use_score=5,
        # The inputs are still reported faithfully alongside the zero value.
        appraised_value_cents=900000000,
        appraisal_age_days=92,
        lending_value_cents=0,
    )
    assert_integer_cents(asset, "lending_value_cents")
    assert_nulls(asset, "assigned_loan_application_id", "lien_position")

    stored = get_success_data(api.get_collateral_asset(asset["id"], CREDIT_ANALYST))
    assert_fields(stored, lending_value_cents=0, appraised_value_cents=900000000)


def test_seasoning_haircut_begins_one_day_past_the_boundary_and_neither_hall_is_stale(api):
    """
    Two otherwise identical fellowship halls, one appraised exactly 365 days ago and
    one 366 days ago, must differ by exactly the 10 percent seasoning haircut, and
    neither is anywhere near the 730-day staleness bar.

    PRD §3.4: "When `appraisal_age_days` is strictly greater than 365 — that is, when the appraisal report is more than a year old on the logical clock — the running figure is multiplied by 90 percent; at 365 days or fewer no seasoning discount applies."
    PRD §3.4: "The result is floored a third time, and that final integer is `lending_value_cents`."
    PRD §3.4: "An asset whose `appraisal_age_days` exceeds 730 — two years of staleness — is refused with `ERR_COLLATERAL_APPRAISAL_STALE`; at exactly 730 days it is still acceptable."
    PRD §2.5: "Four families of rule consult the clock, and all four are rebased the moment it moves: a collateral asset's `appraisal_age_days`, computed as whole days from `appraisal_date` to the current logical instant with any fractional day discarded; the giving-period selection window, which admits only periods whose `period_end` falls at or before the current instant; the expiry test on a governance packet's `expires_on`; and the lien-window comparisons that decide whether a proposed collateral occupation collides with a prior one."

    Design: Corner/calculations/seasoning_haircut_starts_one_day_past_the_seasoning_window
    """
    reset_clock(api)
    institution = build_institution(api, **PLAIN_INSTITUTION)

    # 2025-08-01 is exactly 365 days before the pinned instant.
    at_boundary = build_collateral_asset(
        api,
        institution["id"],
        asset_type="FELLOWSHIP_HALL",
        description_label="North fellowship hall",
        appraised_value_cents=100000000,
        appraisal_date="2025-08-01T00:00:00Z",
        alternative_use_score=3,
    )
    # 2025-07-31 is one day older, which is one day past the window.
    past_boundary = build_collateral_asset(
        api,
        institution["id"],
        asset_type="FELLOWSHIP_HALL",
        description_label="South fellowship hall",
        appraised_value_cents=100000000,
        appraisal_date="2025-07-31T00:00:00Z",
        alternative_use_score=3,
    )

    # min(0.60 proposed at score 3, 0.60 FELLOWSHIP_HALL cap) == 0.60.
    assert_fields(
        at_boundary,
        appraisal_age_days=365,
        lending_value_cents=60000000,
    )
    assert_fields(
        past_boundary,
        appraisal_age_days=366,
        # floor(60000000 * 0.90)
        lending_value_cents=54000000,
    )
    assert (
        at_boundary["lending_value_cents"] - past_boundary["lending_value_cents"] == 6000000
    ), "one day past the seasoning window must cost exactly 10 percent of the value"
    assert_integer_cents(at_boundary, "lending_value_cents")
    assert_integer_cents(past_boundary, "lending_value_cents")

    # 366 days is far below the staleness bar, so both remain assignable.
    for asset in (at_boundary, past_boundary):
        assert asset["appraisal_age_days"] <= 730


def test_giving_base_and_net_available_exclude_both_donor_restricted_deductions(api):
    """
    Across four audited quarters the base is contributions net of BOTH the restricted
    gifts and the endowment draw, the net-available figure rounds per period before
    summing, and the institution's endowment market value enters neither.

    PRD §3.1: "`unrestricted_contributions_cents` is total contributions reduced by restricted contributions and reduced again by the donor-restricted endowment draw, with the result floored at zero if those two deductions together would exceed the total."
    PRD §3.1: "The giving base is the sum of those per-period contributions across the window."
    PRD §3.1: "An institution's `unrestricted_giving_base_cents` and `net_available_for_debt_service_dollars` are reported under the mandated basis rather than a caller-chosen one: `AUDITED_ONLY` when `audited_period_count` is 4 or more, and `BLENDED` otherwise."
    PRD §3.5: "Convert that per-period cent figure to whole dollars by dividing by 100 and rounding half up."
    PRD §3.5: "Only then sum the four rounded per-period dollar figures."
    PRD §2.7: "At the institution level, `endowment_market_value_cents` is recorded for disclosure and is never an input to any calculation in this specification."

    Design: Corner/calculations/giving_base_and_net_available_exclude_restricted_and_endowment_money
    """
    reset_clock(api)
    institution = build_institution(api, community_program_count=3, endowment_market_value_cents=800000000)
    build_giving_periods(api, institution["id"], REFERENCE_AUDITED_QUARTERS)

    reconciled = get_success_data(api.get_institution(institution["id"], CREDIT_ANALYST))

    assert_fields(
        reconciled,
        period_count=4,
        audited_period_count=4,
        # 50000000 + 52000000 + 50000000 + 55000000, not the 247000000 gross of
        # contributions: both deductions come off every quarter.
        unrestricted_giving_base_cents=207000000,
        # 100001 + 110001 + 90001 + 131998 — each quarter rounded half up to whole
        # dollars first, and only then summed.
        net_available_for_debt_service_dollars=432001,
        # Reported for information; it contributes to neither figure above.
        endowment_market_value_cents=800000000,
    )
    assert_integer_cents(
        reconciled, "unrestricted_giving_base_cents", "endowment_market_value_cents"
    )
    assert isinstance(reconciled["net_available_for_debt_service_dollars"], int)
    gross_contributions = sum(
        quarter["total_contributions_cents"] for quarter in REFERENCE_AUDITED_QUARTERS
    )
    assert reconciled["unrestricted_giving_base_cents"] < gross_contributions


def test_mission_impact_score_without_a_support_letter_lands_at_seventy_two(api):
    """
    Rising households and rising unrestricted giving both score 100, three community
    programs score 60, and with no denominational letter that component contributes
    0, so the weighted score is exactly 72.00.

    PRD §3.9: "Each trend is then scored on the same four-step scale: 100 points when the change is zero or positive, 70 points when it is negative but no worse than a 5 percent decline, 40 points when it is worse than that but no worse than a 15 percent decline, and 10 points for anything steeper."
    PRD §3.9: "`community_points` is the institution's `community_program_count` multiplied by 20, capped at 100 — so five ongoing programs earn full marks and a sixth adds nothing."
    PRD §3.9: "`denominational_points` is 100 when the plan's `denominational_support_letter` is true and 0 when it is false."
    PRD §3.9: "The four component scores are then weighted: 35 percent on `membership_trend_points`, 25 percent on `giving_trend_points`, 20 percent on `community_points` and 20 percent on `denominational_points`."
    PRD §3.9: "Each option requires its own quantitative field and forbids the others: `deferral_months` is required for `PAYMENT_DEFERRAL` and must be between 1 and 24 inclusive; `extension_months` is required for `TERM_EXTENSION` and must be between 1 and 120 inclusive; `forgiveness_amount_cents` is required for `PARTIAL_FORGIVENESS` and must be strictly positive; `MISSION_IMPACT_FORBEARANCE` requires none of the three."
    PRD §3.9: "Two score floors then apply, and both are inclusive: a `PARTIAL_FORGIVENESS` plan requires a `mission_impact_score` of at least 92.00, and a `MISSION_IMPACT_FORBEARANCE` plan requires at least 50.00."

    Design: Corner/calculations/mission_impact_score_without_a_denominational_letter_lands_at_seventy_two
    """
    chain = chain_through_loan(
        api, institution_overrides={"endowment_market_value_cents": None}
    )
    # A 1.3000 threshold against a 1.2000 actual ratio fails once, moving the
    # posture off OPEN so a proposal is admissible at all.
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.3000)
    tested = get_success_data(
        api.run_covenant_test(covenant["id"], covenant_test_payload(), LOAN_SERVICER)
    )
    assert_fields(tested, last_test_result="FAIL")
    assert_fields(chain.read_loan(), risk_posture="WATCH")

    loan = chain.read_loan()
    response = api.create_workout_plan(
        forbearance_payload(
            chain.loan_id,
            loan["version"],
            denominational_support_letter=False,
            narrative="No presbytery letter yet; mission case rests on local programs",
        ),
        LOAN_SERVICER,
    )
    plan = get_success_data(response, 201)

    assert_fields(
        plan,
        option="MISSION_IMPACT_FORBEARANCE",
        status="PROPOSED",
        denominational_support_letter=False,
        # 520 households against 500, and 55000000 unrestricted against 50000000.
        membership_trend_points=100,
        giving_trend_points=100,
        # 3 programs * 20, uncapped at that level.
        community_points=60,
        denominational_points=0,
    )
    # 0.35*100 + 0.25*100 + 0.20*60 + 0.20*0
    assert_score(plan["mission_impact_score"], 72.00)
    assert_nulls(plan, "deferral_months", "extension_months", "forgiveness_amount_cents")
    assert_created_fresh(plan)
    # Clears the 50.00 forbearance floor while falling short of the 92.00
    # forgiveness floor.
    assert float(plan["mission_impact_score"]) >= 50.00
    assert float(plan["mission_impact_score"]) < 92.00
