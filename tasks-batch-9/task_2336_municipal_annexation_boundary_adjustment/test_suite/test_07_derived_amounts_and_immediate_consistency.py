"""Derived money amounts on the annexation record, and the immediacy of the
boundary cut-over.

Two related concerns are covered here. First, the amounts the service derives
rather than accepts: the territory aggregates that a carve-out recomputes, the
municipal service district assessment, the per-signature qualified value and the
order in which those values are rounded and summed, the outside-city utility
rate, the admissible effective date, and the de-annexation refund the statute's
chosen basis produces. Second, the visibility of those results: the response to
the boundary change and to the tax-roll posting must already publish everything
the request touched, so that an immediately following independent read agrees
with it without any re-read, retry or delay.
"""
from decimal import Decimal

from test_helpers import (
    assertions,
    constants,
    factories,
    fixtures,
    get_success_data,
    make_municipal_planner_headers,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ERR_EFFECTIVE_DATE_INVALID


# ==========================================================================
# Local helpers
# ==========================================================================
def _matched_jurisdiction(**statute_overrides):
    """A statute profile and a municipality pinned to the same state code,
    because PRD §3.1 requires a city's `state_code` to equal the referenced
    profile's. Returns the two override dictionaries the builders take."""
    code = factories.unique_state_code()
    statute = dict(statute_overrides)
    statute["state_code"] = code
    return statute, {"state_code": code}


def _total_count(response):
    """The `total_count` a list response reports before pagination is applied
    (PRD §2.3)."""
    _, meta = validate_paginated(response)
    return meta["total_count"]


def _one_water_account_case_ready_to_effectuate(api):
    """A city whose statute requires water service only, a single 100,000,000-cent
    parcel carrying one outside-city water account, and an adopted plan whose
    water commitment undertakes to cut exactly that one account over.

    The case is carried to `ORDINANCE_ADOPTED` so that the very next act is the
    boundary change itself.
    """
    statute, municipality = _matched_jurisdiction(required_service_types=["WATER"])
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        parcel_count=1,
        parcel_values_cents=[100000000],
    )
    # Registered while the territory is still outside the corporate limits, so
    # the cut-over has something to move.
    ctx["account"] = fixtures.add_utility_account(
        api,
        ctx["municipality"]["id"],
        ctx["parcels"][0]["id"],
        ctx["provider"]["id"],
        monthly_base_cents=10000,
    )
    # A committed account count of 1 keeps the commitment short of FULFILLED
    # until the effectuation cascade actually cuts the account over.
    fixtures.setup_adopted_plan(api, ctx, account_counts={"WATER": 1})
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)
    fixtures.close_protest_period(api, ctx)
    fixtures.setup_finalized_analysis(api, ctx)
    fixtures.adopt_ordinance(api, ctx)
    return ctx


# ==========================================================================
# Territory aggregates after a carve-out
# ==========================================================================
def test_excluding_a_parcel_drops_it_from_every_territory_aggregate(api):
    """PRD §3.2: "Parcels in `EXCLUDED` or `DE_ANNEXED` never enter any
    territory aggregate. `parcel_count` is the number of such parcels,
    `territory_acreage` is the sum of their `acreage` values rounded half up to
    two decimal places, and `territory_assessed_value_cents` is the exact
    integer sum of their `assessed_value_cents`."

    Design: Corner/calculations/excluding_a_parcel_drops_it_from_every_territory_aggregate
    """
    statute, municipality = _matched_jurisdiction()
    # Four distinct values so that dropping the largest is unmistakable in the
    # assessed-value aggregate.
    ctx = fixtures.setup_draft_case(
        api,
        statute=statute,
        municipality=municipality,
        parcel_values_cents=[40000000, 30000000, 20000000, 10000000],
    )
    planner = fixtures.planner(ctx)
    before = ctx["case"]

    assert before["parcel_count"] == 4
    assertions.assert_numeric_equals(
        before["territory_acreage"], assertions.acres("20.00"), "territory_acreage"
    )
    assert before["territory_assessed_value_cents"] == 100000000

    excluded = get_success_data(api.exclude_parcel(planner, ctx["parcels"][0]["id"]))
    assert excluded["parcel_status"] == "EXCLUDED"

    after = fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])
    assert after["parcel_count"] == 3
    assertions.assert_numeric_equals(
        after["territory_acreage"], assertions.acres("15.00"), "territory_acreage"
    )
    assert after["territory_assessed_value_cents"] == 60000000
    # The carve-out is admissible from DRAFT and leaves the case where it was.
    assert after["status"] == "DRAFT"
    assert after["version"] == before["version"] + 1

    # The row itself survives the exclusion and is still discoverable.
    assert (
        _total_count(
            api.list_parcels(
                planner,
                annexation_case_id=ctx["case"]["id"],
                parcel_status="EXCLUDED",
            )
        )
        == 1
    )
    assert (
        _total_count(
            api.list_parcels(
                planner,
                annexation_case_id=ctx["case"]["id"],
                parcel_status="PROPOSED",
            )
        )
        == 3
    )


# ==========================================================================
# The municipal service district assessment
# ==========================================================================
def test_msd_assessment_is_three_quarters_of_the_adopted_plans_committed_cost(api):
    """PRD §3.9: "Adoption computes `msd_annual_assessment_cents` as that plan's
    `committed_cost_cents` — which already excludes commitments in `DRAFT` or
    `VOIDED` — multiplied by the statute's `msd_cost_recovery_pct`, rounded half
    up to a whole cent."

    Design: Corner/calculations/msd_assessment_is_three_quarters_of_the_adopted_plans_committed_cost
    """
    # A statute that requires police service only, so a single police
    # commitment is enough for the plan to be adoptable.
    statute, municipality = _matched_jurisdiction(required_service_types=["POLICE"])
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        parcel_values_cents=[40000000, 30000000, 20000000, 10000000],
    )
    fixtures.setup_adopted_plan(api, ctx, cost_cents=1200000)
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)
    # A single 100% objection on the 40,000,000-cent parcel is 40.00% of a
    # 100,000,000-cent territory, well past the 20.00 statutory threshold.
    fixtures.set_clock(api, constants.CLOCK_DURING_PROTEST_WINDOW)
    filing = fixtures.file_protest(api, ctx, parcel_index=0)
    fixtures.close_protest_period(api, ctx)

    assert filing["protest_value_cents"] == 40000000
    assertions.assert_numeric_equals(
        ctx["case"]["protest_pct"],
        assertions.expected_weight_pct(40000000, 100000000),
        "protest_pct",
    )
    assert ctx["case"]["protest_outcome"] == "SUSTAINED"
    assert ctx["case"]["status"] == "PROTEST_SUSTAINED"

    plan = fixtures.read_plan(api, ctx["municipality"]["id"], ctx["plan"]["id"])
    assert plan["adoption_status"] == "ADOPTED"
    assert plan["committed_cost_cents"] == 1200000

    case = get_success_data(
        api.adopt_msd_alternative(fixtures.clerk(ctx), ctx["case"]["id"])
    )
    assert case["status"] == "MSD_ALTERNATIVE_ADOPTED"
    # Three quarters of the promised service cost — not of the 100,000,000-cent
    # territory value, which would give a wildly different figure.
    assert case["msd_annual_assessment_cents"] == assertions.expected_msd_assessment_cents(
        1200000, constants.DEFAULT_MSD_COST_RECOVERY_PCT
    )
    assert case["territory_assessed_value_cents"] == 100000000

    # No boundary changes, so the whole territory is carved back out.
    assert (
        _total_count(
            api.list_parcels(
                fixtures.planner(ctx),
                annexation_case_id=ctx["case"]["id"],
                parcel_status="EXCLUDED",
            )
        )
        == 4
    )


# ==========================================================================
# Petition signature weight: rounding order
# ==========================================================================
def test_consent_qualified_value_rounds_a_half_cent_share_up(api):
    """PRD §3.3: "The consent is stored with `consent_status` `SIGNED` and
    `signed_at` set to the clock, and its `qualified_value_cents` is computed
    immediately as the parcel's `assessed_value_cents` multiplied by
    `ownership_share_pct`, divided by one hundred, and rounded half up to a
    whole cent; the owning petition's signature aggregates are then recomputed
    by the rule stated below."

    Design: Corner/calculations/consent_qualified_value_rounds_half_up_before_the_petition_sum
    """
    statute, municipality = _matched_jurisdiction()
    # An odd assessed value so that a half share is exactly half a cent past a
    # whole cent: 1,000,001 / 2 = 500,000.5.
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        case={"method": "PETITION_MAJORITY"},
        parcel_count=1,
        parcel_values_cents=[1000001],
        parcel_overrides={"acreage": 1.00},
    )
    fixtures.open_petition(api, ctx, petition_type="OWNER_MAJORITY")

    consent = fixtures.sign_consent(api, ctx, parcel_index=0, ownership_share_pct=50.00)
    assert consent["consent_status"] == "SIGNED"
    assert consent["qualified_value_cents"] == assertions.expected_share_value_cents(
        1000001, 50.00
    )
    assert consent["qualified_value_cents"] == 500001

    petition = get_success_data(
        api.certify_sufficiency(fixtures.clerk(ctx), ctx["petition"]["id"])
    )
    # The petition total is the already-rounded share, so the half cent is not
    # lost between the consent and the aggregate.
    assert petition["qualified_signature_assessed_value_cents"] == 500001
    assert petition["qualified_signature_owner_count"] == 1
    assertions.assert_numeric_equals(
        petition["signature_value_pct"],
        assertions.expected_weight_pct(500001, 1000001),
        "signature_value_pct",
    )
    assertions.assert_numeric_equals(
        petition["signature_owner_pct"],
        assertions.expected_weight_pct(1, 1),
        "signature_owner_pct",
    )
    # 50.00 measured against the statute's 50.00 threshold is sufficient.
    assert petition["sufficiency_status"] == "SUFFICIENT"
    case = fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])
    assert case["status"] == "SUFFICIENCY_REVIEW"


def test_petition_total_sums_the_already_rounded_consent_shares(api):
    """PRD §2.7: "First, when petition or protest weight is aggregated across
    owner shares, each individual share is rounded to a whole cent **before**
    the shares are summed — the per-consent `qualified_value_cents` and the
    per-filing `protest_value_cents` are each rounded, and the petition and
    hearing totals are exact integer sums of those already-rounded values."

    Design: Corner/calculations/consent_qualified_value_rounds_half_up_before_the_petition_sum
    """
    statute, municipality = _matched_jurisdiction()
    parcel_value_cents = 1000001
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        case={"method": "PETITION_MAJORITY"},
        parcel_count=1,
        parcel_values_cents=[parcel_value_cents],
        parcel_overrides={"acreage": 1.00},
    )
    fixtures.open_petition(api, ctx, petition_type="OWNER_MAJORITY")

    # Two half interests in the same odd-valued parcel: each share is
    # 500,000.5 cents, so the two rounding orders disagree by a whole cent.
    co_owner = fixtures.create_owner(api)
    ctx["owners"].append(co_owner)
    first = fixtures.sign_consent(
        api, ctx, parcel_index=0, owner_index=0, ownership_share_pct=50.00
    )
    second = fixtures.sign_consent(
        api, ctx, parcel_index=0, owner_index=1, ownership_share_pct=50.00
    )

    per_share_cents = assertions.expected_share_value_cents(parcel_value_cents, 50.00)
    assert first["qualified_value_cents"] == per_share_cents
    assert second["qualified_value_cents"] == per_share_cents

    round_each_then_sum = per_share_cents * 2
    raw_share = Decimal(parcel_value_cents) * Decimal("50.00") / Decimal(100)
    sum_then_round_once = assertions.cents(raw_share * 2)
    # The two orders genuinely differ here, which is what makes the pinned
    # order observable rather than academic.
    assert round_each_then_sum != sum_then_round_once
    assert round_each_then_sum == 1000002
    assert sum_then_round_once == 1000001

    petition = get_success_data(
        api.certify_sufficiency(fixtures.clerk(ctx), ctx["petition"]["id"])
    )
    assert petition["qualified_signature_assessed_value_cents"] == round_each_then_sum
    assert petition["qualified_signature_owner_count"] == 2
    assert petition["sufficiency_status"] == "SUFFICIENT"


# ==========================================================================
# The outside-city utility rate
# ==========================================================================
def test_utility_effective_rate_applies_each_municipalitys_own_surcharge_constant(api):
    """PRD §3.8: "`effective_monthly_cents` is recomputed on registration and on
    every change of `rate_schedule`: while the schedule is
    `OUTSIDE_CITY_SURCHARGE` it is `monthly_base_cents` multiplied by one plus
    the municipality's `utility_outside_surcharge_pct`, rounded half up to a
    whole cent; while the schedule is `INSIDE_CITY` it is simply
    `monthly_base_cents` with no surcharge at all."

    Design: Corner/calculations/utility_effective_rate_applies_each_municipalitys_own_surcharge_constant
    """
    # An odd base rate, so the 0.50 surcharge lands exactly on a half cent and
    # the 0.25 surcharge on a quarter cent: both need the half-up rule.
    monthly_base_cents = 5001
    code = factories.unique_state_code()
    statute = fixtures.create_statute(api, state_code=code)
    # Two cities under the same statute: one on the declared 0.50 default, the
    # other configured at 0.25.
    default_city = fixtures.create_municipality(api, statute["id"], state_code=code)
    quarter_city = fixtures.create_municipality(
        api, statute["id"], state_code=code, utility_outside_surcharge_pct=0.25
    )

    accounts = {}
    parcels = {}
    for city in (default_city, quarter_city):
        provider = fixtures.create_provider(api, city["id"])
        case = fixtures.create_case(api, city["id"])
        owner = fixtures.create_owner(api)
        parcel = fixtures.add_parcel(api, city["id"], case["id"], owner["id"])
        parcels[city["id"]] = parcel
        accounts[city["id"]] = fixtures.add_utility_account(
            api,
            city["id"],
            parcel["id"],
            provider["id"],
            service_type="WATER",
            monthly_base_cents=monthly_base_cents,
        )

    assertions.assert_numeric_equals(
        default_city["utility_outside_surcharge_pct"],
        constants.DEFAULT_UTILITY_OUTSIDE_SURCHARGE_PCT,
        "utility_outside_surcharge_pct",
    )

    default_account = accounts[default_city["id"]]
    quarter_account = accounts[quarter_city["id"]]

    assert default_account["monthly_base_cents"] == monthly_base_cents
    assert quarter_account["monthly_base_cents"] == monthly_base_cents
    assert default_account["account_status"] == "OUTSIDE_CITY"
    assert default_account["rate_schedule"] == "OUTSIDE_CITY_SURCHARGE"
    assert quarter_account["account_status"] == "OUTSIDE_CITY"
    assert quarter_account["rate_schedule"] == "OUTSIDE_CITY_SURCHARGE"

    # The multiplier comes from the city that owns the account's parcel, so the
    # identical base rate bills differently in the two jurisdictions.
    assert default_account[
        "effective_monthly_cents"
    ] == assertions.expected_outside_city_monthly_cents(
        monthly_base_cents, constants.DEFAULT_UTILITY_OUTSIDE_SURCHARGE_PCT
    )
    assert default_account["effective_monthly_cents"] == 7502
    assert quarter_account[
        "effective_monthly_cents"
    ] == assertions.expected_outside_city_monthly_cents(monthly_base_cents, 0.25)
    assert quarter_account["effective_monthly_cents"] == 6251

    assert (
        _total_count(
            api.list_utility_accounts(
                make_municipal_planner_headers(quarter_city["id"]),
                parcel_id=parcels[quarter_city["id"]]["id"],
            )
        )
        == 1
    )


# ==========================================================================
# Effective-date admissibility
# ==========================================================================
def test_effective_date_equal_to_the_clock_date_is_refused_under_the_next_quarter_rule(api):
    """PRD §3.8: "Under `NEXT_QUARTER_START`, it must equal the first day of the
    calendar quarter following the quarter that contains the clock's date — the
    first of April for a clock in January through March, the first of July for
    April through June, the first of October for July through September, and the
    first of January of the following year for October through December." And:
    "Any other date is refused with `ERR_EFFECTIVE_DATE_INVALID`."

    Design: Corner/calculations/effective_date_must_equal_the_next_quarter_start_or_is_rejected
    """
    statute, municipality = _matched_jurisdiction(
        effective_date_rule="NEXT_QUARTER_START"
    )
    ctx = fixtures.setup_case_ordinance_adopted(
        api, statute=statute, municipality=municipality
    )
    assert ctx["case"]["status"] == "ORDINANCE_ADOPTED"

    # The clock's own date would be the sole admissible value under the
    # IMMEDIATE rule, and is inadmissible under this one.
    response = api.effectuate(
        fixtures.planner(ctx),
        ctx["case"]["id"],
        constants.EFFECTIVE_DATE_AFTER_PROTEST,
    )
    validate_error(response, ERR_EFFECTIVE_DATE_INVALID)

    case = fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])
    assert case["status"] == "ORDINANCE_ADOPTED"
    assert case["tax_roll_status"] == "NOT_TRANSFERRED"


def test_effective_date_at_the_next_quarter_start_effectuates_the_boundary_change(api):
    """PRD §3.8: "Under `NEXT_QUARTER_START`, it must equal the first day of the
    calendar quarter following the quarter that contains the clock's date — the
    first of April for a clock in January through March, the first of July for
    April through June, the first of October for July through September, and the
    first of January of the following year for October through December."

    Design: Corner/calculations/effective_date_must_equal_the_next_quarter_start_or_is_rejected
    """
    statute, municipality = _matched_jurisdiction(
        effective_date_rule="NEXT_QUARTER_START"
    )
    ctx = fixtures.setup_case_ordinance_adopted(
        api, statute=statute, municipality=municipality
    )

    # A clock in the October-through-December quarter rolls the year over.
    admissible = assertions.next_quarter_start(
        constants.EFFECTIVE_DATE_AFTER_PROTEST
    ).isoformat()
    assert admissible == "2027-01-01"

    case = get_success_data(
        api.effectuate(fixtures.planner(ctx), ctx["case"]["id"], admissible)
    )
    assert case["status"] == "EFFECTIVE"
    assert case["effective_date"] == admissible
    # The stamped date is the statutory one, not the clock's own reading.
    assert case["effective_date"] != constants.EFFECTIVE_DATE_AFTER_PROTEST
    # The tax roll moves on its own axis and has not been posted yet.
    assert case["tax_roll_status"] == "NOT_TRANSFERRED"

    planner = fixtures.planner(ctx)
    assert (
        _total_count(
            api.list_parcels(
                planner,
                annexation_case_id=ctx["case"]["id"],
                parcel_status="INCORPORATED",
            )
        )
        == 4
    )


# ==========================================================================
# The de-annexation refund basis
# ==========================================================================
def test_whole_quarter_de_annexation_refund_returns_the_containing_quarter_in_full(api):
    """PRD §3.9: "Under `WHOLE_QUARTER`, count the calendar quarters remaining
    including the one that contains the effective date — four for an effective
    date in January through March, three for April through June, two for July
    through September, one for October through December — and set the refund to
    the predecessor's posted tax multiplied by those remaining quarters, divided
    by the four quarters of the year, rounded half up to a whole cent."

    Design: Corner/calculations/de_annexation_refund_uses_the_whole_quarter_variant_selected_by_the_statute
    """
    statute, municipality = _matched_jurisdiction(
        de_annexation_refund_basis="WHOLE_QUARTER"
    )
    # The odd first parcel makes the posted total 210,962 cents, whose three
    # quarters is exactly 158,221.5 — a genuine half-cent boundary.
    parcel_values_cents = [25001000, 25000000, 25000000, 25000000]
    ctx = fixtures.setup_effective_case(
        api,
        statute=statute,
        municipality=municipality,
        parcel_values_cents=parcel_values_cents,
    )
    fixtures.post_tax_roll(api, ctx)

    millage = ctx["municipality"]["general_fund_millage_rate"]
    remaining_days = assertions.remaining_fiscal_days(
        constants.EFFECTIVE_DATE_AFTER_PROTEST,
        constants.DEFAULT_FISCAL_YEAR_END_MONTH_DAY,
    )
    expected_posted_tax_cents = sum(
        assertions.expected_prorated_tax_cents(
            assertions.expected_property_tax_cents(value, millage), remaining_days
        )
        for value in parcel_values_cents
    )
    posted_tax_cents = ctx["case"]["tax_roll_transferred_tax_cents"]
    assert posted_tax_cents == expected_posted_tax_cents
    assert ctx["case"]["tax_roll_status"] == "POSTED"

    first_parcel = fixtures.read_parcel(
        api, ctx["municipality"]["id"], ctx["parcels"][0]["id"]
    )
    assert first_parcel["annual_tax_cents"] == assertions.expected_property_tax_cents(
        parcel_values_cents[0], millage
    )
    assert first_parcel["prorated_tax_cents"] == assertions.expected_prorated_tax_cents(
        first_parcel["annual_tax_cents"], remaining_days
    )

    successor = fixtures.setup_de_annexation_case(api, ctx)
    # A late-May unwinding: three quarters remain, and the whole of the quarter
    # containing 20 May comes back.
    de_annexation_effective_date = "2027-05-20"
    fixtures.set_clock(api, "2027-05-20T09:00:00Z")
    case = get_success_data(
        api.effectuate(
            fixtures.planner(successor),
            successor["case"]["id"],
            de_annexation_effective_date,
        )
    )
    assert case["status"] == "EFFECTIVE"
    assert case["effective_date"] == de_annexation_effective_date

    expected_refund_cents = assertions.expected_whole_quarter_refund_cents(
        posted_tax_cents, de_annexation_effective_date
    )
    daily_proration_refund_cents = assertions.expected_daily_proration_refund_cents(
        posted_tax_cents,
        de_annexation_effective_date,
        constants.DEFAULT_FISCAL_YEAR_END_MONTH_DAY,
    )
    # The statute's chosen basis, not the date, decides the amount.
    assert expected_refund_cents != daily_proration_refund_cents
    assert expected_refund_cents == 158222
    assert case["de_annexation_refund_cents"] == expected_refund_cents

    predecessor = fixtures.read_case(
        api, ctx["municipality"]["id"], ctx["case"]["id"]
    )
    assert predecessor["status"] == "DE_ANNEXED"
    assert predecessor["tax_roll_status"] == "REVERSED"
    assert predecessor["tax_roll_transferred_tax_cents"] == posted_tax_cents
    assert (
        _total_count(
            api.list_parcels(
                fixtures.planner(ctx),
                annexation_case_id=ctx["case"]["id"],
                parcel_status="DE_ANNEXED",
            )
        )
        == 4
    )
    assert (
        fixtures.read_municipality(api, ctx["municipality"]["id"])[
            "taxable_assessed_value_cents"
        ]
        == 0
    )


# ==========================================================================
# Immediate visibility of the cut-over
# ==========================================================================
def test_the_effectuate_response_already_reflects_the_whole_cutover(api):
    """PRD §3.8: "Admitted, the case's `status` becomes `EFFECTIVE` and
    `effective_date` is stamped, and a six-link cascade runs." And: "Because
    those parcels became `INCORPORATED`, each of their utility accounts in
    `OUTSIDE_CITY` moves to `INSIDE_CITY_PENDING_TRANSITION`, its
    `rate_schedule` moves from `OUTSIDE_CITY_SURCHARGE` to `INSIDE_CITY`, and
    its `effective_monthly_cents` is recomputed with the surcharge dropped."

    Design: Corner/consistency_model/the_effectuate_response_already_reflects_the_whole_cutover
    """
    ctx = _one_water_account_case_ready_to_effectuate(api)
    municipality_id = ctx["municipality"]["id"]
    account_id = ctx["account"]["id"]
    commitment_id = ctx["commitments"]["WATER"]["id"]

    # The world before the boundary change: still outside the limits, and the
    # water commitment is still waiting for its one account.
    before_account = fixtures.read_account(api, municipality_id, account_id)
    assert before_account["account_status"] == "OUTSIDE_CITY"
    assert before_account["rate_schedule"] == "OUTSIDE_CITY_SURCHARGE"
    assert before_account[
        "effective_monthly_cents"
    ] == assertions.expected_outside_city_monthly_cents(
        10000, constants.DEFAULT_UTILITY_OUTSIDE_SURCHARGE_PCT
    )
    before_commitment = fixtures.read_commitment(api, municipality_id, commitment_id)
    assert before_commitment["commitment_status"] == "ACTIVE"
    assert before_commitment["activated_account_count"] == 0
    assert fixtures.read_plan(api, municipality_id, ctx["plan"]["id"])[
        "service_readiness"
    ] == "PARTIAL"

    # The response to the boundary change itself already publishes the outcome.
    effectuated = get_success_data(
        api.effectuate(
            fixtures.planner(ctx),
            ctx["case"]["id"],
            constants.EFFECTIVE_DATE_AFTER_PROTEST,
        )
    )
    assert effectuated["status"] == "EFFECTIVE"
    assert effectuated["effective_date"] == constants.EFFECTIVE_DATE_AFTER_PROTEST

    # The very next independent reads agree with it, with no intervening write.
    parcel = fixtures.read_parcel(api, municipality_id, ctx["parcels"][0]["id"])
    assert parcel["parcel_status"] == "INCORPORATED"

    account = fixtures.read_account(api, municipality_id, account_id)
    assert account["rate_schedule"] == "INSIDE_CITY"
    assert account["effective_monthly_cents"] == account["monthly_base_cents"]
    assert account["effective_monthly_cents"] == 10000
    assert account["account_status"] == "INSIDE_CITY_ACTIVE"

    commitment = fixtures.read_commitment(api, municipality_id, commitment_id)
    assert commitment["activated_account_count"] == 1
    assert commitment["commitment_status"] == "FULFILLED"

    plan = fixtures.read_plan(api, municipality_id, ctx["plan"]["id"])
    assert plan["service_readiness"] == "READY"
    assert plan["covered_service_types"] == assertions.ordered_service_types(["WATER"])


def test_the_tax_roll_response_carries_the_totals_the_ledger_read_back_agrees_with(
    api, county_assessor
):
    """PRD §3.8: "The municipality's `taxable_assessed_value_cents` is increased
    by that transferred assessed value, `tax_roll_status` advances
    `NOT_TRANSFERRED → POSTED`, and the case's `version` increments."

    Design: Corner/consistency_model/the_effectuate_response_already_reflects_the_whole_cutover
    """
    ctx = _one_water_account_case_ready_to_effectuate(api)
    municipality_id = ctx["municipality"]["id"]
    fixtures.effectuate(api, ctx, constants.EFFECTIVE_DATE_AFTER_PROTEST)

    # The city ledger only rises when a case posts its roll.
    assert (
        fixtures.read_municipality(api, municipality_id)["taxable_assessed_value_cents"]
        == 0
    )

    posted = get_success_data(api.post_tax_roll(county_assessor, ctx["case"]["id"]))

    millage = ctx["municipality"]["general_fund_millage_rate"]
    remaining_days = assertions.remaining_fiscal_days(
        constants.EFFECTIVE_DATE_AFTER_PROTEST,
        constants.DEFAULT_FISCAL_YEAR_END_MONTH_DAY,
    )
    expected_annual_tax_cents = assertions.expected_property_tax_cents(
        100000000, millage
    )
    expected_prorated_tax_cents = assertions.expected_prorated_tax_cents(
        expected_annual_tax_cents, remaining_days
    )

    # The posting response itself carries the transferred totals.
    assert posted["tax_roll_status"] == "POSTED"
    assert posted["tax_roll_transferred_assessed_value_cents"] == 100000000
    assert posted["tax_roll_transferred_tax_cents"] == expected_prorated_tax_cents
    assert posted["tax_roll_transferred_tax_cents"] == 210959

    # And the ledger read immediately afterwards agrees with the response.
    municipality = fixtures.read_municipality(api, municipality_id)
    assert municipality["taxable_assessed_value_cents"] == 100000000
    assert (
        municipality["taxable_assessed_value_cents"]
        == posted["tax_roll_transferred_assessed_value_cents"]
    )

    parcel = fixtures.read_parcel(api, municipality_id, ctx["parcels"][0]["id"])
    assert parcel["annual_tax_cents"] == expected_annual_tax_cents
    assert parcel["prorated_tax_cents"] == expected_prorated_tax_cents
