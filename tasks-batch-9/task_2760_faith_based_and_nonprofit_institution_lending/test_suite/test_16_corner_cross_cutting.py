"""
Queue B — §1.9 section ``cross_cutting_complexity_layers``.

The two stale-version guards of PRD §2.8 exercised where the parent's version
moved for a reason the client never asked for — a covenant test that shifted the
loan's posture, and a sibling pledge that shifted the campaign's buckets — plus
the cumulative counter that lapses a pledge at exactly the third miss.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_PLEDGE_INVALID_STATE,
    ERR_STALE_CAMPAIGN_VERSION,
    ERR_STALE_LOAN_VERSION,
)
from test_helpers.assertions import (
    assert_created_fresh,
    assert_fields,
    assert_pagination_meta,
    assert_ratio,
    assert_score,
)
from test_helpers.factories import (
    covenant_test_payload,
    installment_payload,
    pledge_payload,
    workout_plan_payload,
)
from test_helpers.fixtures import (
    build_covenant,
    build_institution,
    build_pledge_campaign,
    chain_through_loan,
    reset_clock,
)
from test_helpers.test_users import CREDIT_ANALYST, LOAN_SERVICER

# The recipes in this section file no endowment figure.
BORROWER = {"endowment_market_value_cents": None}


def test_a_workout_proposal_carrying_the_version_from_before_the_covenant_test_is_refused(api):
    """
    A covenant test moves the loan's version by shifting its posture to WATCH, so a
    proposal that still declares the version read at origination is refused on the
    version alone even though the posture gate it would hit next is now satisfied;
    re-reading the loan and resubmitting the identical body succeeds.

    PRD §2.8: "`POST /workout-plans` requires `expected_loan_version`, carrying the client's last observed `version` of the target `Loan`. If the loan's current `version` differs, the proposal is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412)."
    PRD §2.10: "`expected_loan_version` matches the target loan's current `version` — `ERR_STALE_LOAN_VERSION` (HTTP 412), on workout-plan creation."
    PRD §3.8: "Writing it re-evaluates the loan's risk posture, which cannot change as a result — a brand-new covenant is compliant by construction."
    PRD §3.8: "From `COMPLIANT`, a failing test moves the covenant `COMPLIANT → BREACH_PENDING_CURE` and sets `consecutive_fail_count` to 1. This is the soft-breach window, and it is what drives the loan `OPEN → WATCH` on the risk dimension."
    PRD §2.4: "When a covenant test drives a loan's risk posture, the loan's `version` increases and its `updated_at` is refreshed even though the client addressed the covenant."
    PRD §3.9: "A successful proposal opens the plan in `PROPOSED`, with `approved_by_user_id` null and not one ledger figure on the loan moved."
    PRD §3.9: "The four component scores are then weighted: 35 percent on `membership_trend_points`, 25 percent on `giving_trend_points`, 20 percent on `community_points` and 20 percent on `denominational_points`."
    PRD §3.9: "`denominational_points` is 100 when the plan's `denominational_support_letter` is true and 0 when it is false."

    Design: Corner/cross_cutting_complexity_layers/workout_plan_create_against_a_stale_loan_version_is_rejected
    """
    reset_clock(api)
    chain = chain_through_loan(api, institution_overrides=BORROWER)
    version_at_origination = chain.loan["version"]

    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.3000)
    # 432001 dollars of net available over 360000 dollars of debt service is a
    # 1.2000 ratio, short of the 1.3000 threshold.
    tested = get_success_data(
        api.run_covenant_test(covenant["id"], covenant_test_payload(), LOAN_SERVICER)
    )
    assert tested["last_test_result"] == "FAIL"

    validate_error(
        api.create_workout_plan(
            workout_plan_payload(chain.loan_id, version_at_origination), LOAN_SERVICER
        ),
        ERR_STALE_LOAN_VERSION,
        412,
    )
    _, empty_meta = validate_paginated(
        api.list_workout_plans(LOAN_SERVICER, {"loan_id": chain.loan_id})
    )
    assert_pagination_meta(empty_meta, total_count=0)

    current = chain.read_loan()
    assert current["version"] == version_at_origination + 1, (
        "the covenant test must advance the loan's version exactly once"
    )
    assert_fields(current, risk_posture="WATCH", servicing_status="PENDING_FIRST_DRAW")

    plan = get_success_data(
        api.create_workout_plan(
            workout_plan_payload(chain.loan_id, current["version"]), LOAN_SERVICER
        ),
        201,
    )
    assert_created_fresh(plan)
    assert_fields(
        plan,
        status="PROPOSED",
        option="PAYMENT_DEFERRAL",
        denominational_points=0,
    )
    # 100 household points and 100 giving points on a growing window, 60 community
    # points for three programs, and no support letter: 35 + 25 + 12 + 0.
    assert_score(plan["mission_impact_score"], 72.00)

    after = chain.read_loan()
    assert after["version"] == current["version"], "a proposal moves nothing on the loan"
    assert after["deferred_payments_count"] == 0


def test_a_second_pledge_replaying_the_version_the_campaign_had_first_is_refused(api):
    """
    The first pledge advances the campaign's version, so a second pledge still
    declaring the version read at launch is refused; re-reading the campaign and
    resubmitting the identical body lands the MAJOR tier's own discount, and the two
    valuations diverge exactly as the per-pledge and aggregate orders require.

    PRD §2.8: "`POST /pledges` requires `expected_pledge_campaign_version`, carrying the client's last observed `version` of the target `PledgeCampaign`. If the campaign's current `version` differs from the submitted value — because another writer has recorded a pledge, an installment, a lapse or a reinstatement since the client read the campaign — the create is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)."
    PRD §2.10: "`expected_pledge_campaign_version` matches the target campaign's current `version` — `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412), on pledge creation."
    PRD §3.3: "A new pledge opens `ACTIVE` with `collected_cents`, `payments_made_count` and `missed_payments_count` all 0, `lapse_reason` null, and `effective_attrition_pct` at its tier's base rate."
    PRD §3.3: "The campaign is reconciled in the same call: `total_pledged_cents` and `active_pledged_cents` each rise by the pledged amount, both projected values are recomputed, and the campaign's `version` advances by 1."
    PRD §3.3: "The base attrition rate is fixed by tier: 5 percent for a `LEAD` donor, 12 percent for a `MAJOR` donor and 22 percent for a `GENERAL` donor."
    PRD §3.3: "Every pledge still in `ACTIVE` status then contributes its remaining balance, being its `pledged_amount_cents` less its `collected_cents`, multiplied by 1 less that pledge's own effective attrition rate, and floored to whole cents **per pledge**."
    PRD §3.3: "It aggregates first and discounts once: the remaining balances of every `ACTIVE` pledge are summed, that single total is multiplied by the campaign's `sponsor_collection_rate_bps` divided by 10000, the product is floored once to whole cents, and the collected cash is added."
    PRD §3.3: "The first is a maturity condition: `total_pledged_cents` must have reached the floor of the goal multiplied by 90 percent, which keeps a brand-new campaign with no pledges at all comfortably in `OPEN`."

    Design: Corner/cross_cutting_complexity_layers/pledge_create_against_a_stale_campaign_version_is_rejected
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    campaign = build_pledge_campaign(api, institution["id"])
    version_at_launch = campaign["version"]

    lead = get_success_data(
        api.create_pledge(
            pledge_payload(
                campaign["id"],
                version_at_launch,
                donor_tier="LEAD",
                pledged_amount_cents=10000000,
                installment_count=12,
            ),
            CREDIT_ANALYST,
        ),
        201,
    )
    assert lead["donor_tier"] == "LEAD"

    stale_body = pledge_payload(
        campaign["id"],
        version_at_launch,
        donor_tier="MAJOR",
        pledged_amount_cents=5000000,
        installment_count=12,
    )
    validate_error(
        api.create_pledge(stale_body, CREDIT_ANALYST), ERR_STALE_CAMPAIGN_VERSION, 412
    )
    _, pledge_meta = validate_paginated(
        api.list_pledges(CREDIT_ANALYST, {"pledge_campaign_id": campaign["id"]})
    )
    assert_pagination_meta(pledge_meta, total_count=1)

    reread = get_success_data(api.get_pledge_campaign(campaign["id"], CREDIT_ANALYST))
    assert reread["version"] == version_at_launch + 1, (
        "the first pledge must advance the campaign exactly once"
    )
    # One LEAD pledge: floor(10000000 x 0.95) conservative against
    # floor(10000000 x 0.9000) optimistic.
    assert_fields(
        reread,
        total_pledged_cents=10000000,
        attrition_adjusted_value_cents=9500000,
        sponsor_projected_value_cents=9000000,
    )

    major = get_success_data(
        api.create_pledge(
            pledge_payload(
                campaign["id"],
                reread["version"],
                donor_tier="MAJOR",
                pledged_amount_cents=5000000,
                installment_count=12,
            ),
            CREDIT_ANALYST,
        ),
        201,
    )
    assert_fields(major, status="ACTIVE", collected_cents=0, missed_payments_count=0)
    assert_ratio(major["effective_attrition_pct"], 0.1200, "effective_attrition_pct")

    settled = get_success_data(api.get_pledge_campaign(campaign["id"], CREDIT_ANALYST))
    assert settled["version"] == reread["version"] + 1
    assert_fields(
        settled,
        status="OPEN",
        total_pledged_cents=15000000,
        active_pledged_cents=15000000,
        lapsed_pledged_cents=0,
        fulfilled_pledged_cents=0,
        collected_to_date_cents=0,
    )
    # Per pledge: floor(10000000 x 0.95) + floor(5000000 x 0.88) == 13900000.
    # Aggregate once: floor(15000000 x 0.9000) == 13500000.
    assert_fields(
        settled,
        attrition_adjusted_value_cents=13900000,
        sponsor_projected_value_cents=13500000,
    )
    # 15000000 pledged is far below floor(200000000 x 90%) == 180000000, so the
    # maturity condition of the underperformance gate never opens.
    assert settled["total_pledged_cents"] < 180000000


def test_the_third_missed_installment_lapses_the_pledge_and_empties_the_active_bucket(api):
    """
    One GENERAL pledge missed three times: the first miss draws no penalty, the
    second adds the fifteen-point penalty while the pledge stays ACTIVE, and only the
    third flips it to LAPSED — which moves the pledged dollars into the lapsed bucket,
    drops both valuations to nothing, and closes the pledge to further installments.

    PRD §3.3: "The base attrition rate is fixed by tier: 5 percent for a `LEAD` donor, 12 percent for a `MAJOR` donor and 22 percent for a `GENERAL` donor. A donor who has missed two or more installments is penalised a further 15 percentage points, and the resulting rate is capped at 60 percent no matter how the components add up."
    PRD §3.3: "A `PAID` installment raises `collected_cents` by the amount and `payments_made_count` by 1; a `MISSED` installment raises `missed_payments_count` by 1."
    PRD §3.3: "Separately, once a `MISSED` installment brings `missed_payments_count` to exactly 3, the pledge moves `ACTIVE → LAPSED` automatically: `lapse_reason` is set to the literal string `AUTO_THREE_MISSED_INSTALLMENTS`, its pledged amount leaves `active_pledged_cents` and enters `lapsed_pledged_cents`, both projected values are recomputed, `version` advances by 1, and the campaign may itself be driven `OPEN → UNDERPERFORMING`."
    PRD §3.3: "Pledges in `LAPSED` or `FULFILLED` status contribute nothing beyond the cash already counted in the collected total."
    PRD §2.10: "The pledge is `ACTIVE` for an installment record or a lapse, and `LAPSED` for a reinstatement — `ERR_PLEDGE_INVALID_STATE` (HTTP 409), on those three pledge actions."

    Design: Corner/cross_cutting_complexity_layers/pledge_auto_lapses_at_exactly_the_third_missed_installment
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    campaign = build_pledge_campaign(api, institution["id"])
    pledge = get_success_data(
        api.create_pledge(
            pledge_payload(
                campaign["id"],
                campaign["version"],
                donor_tier="GENERAL",
                pledged_amount_cents=10000000,
                installment_count=12,
            ),
            CREDIT_ANALYST,
        ),
        201,
    )

    first = get_success_data(
        api.record_pledge_payment(
            pledge["id"], installment_payload(1, "MISSED", 0), LOAN_SERVICER
        )
    )
    assert_fields(first, status="ACTIVE", missed_payments_count=1)
    # One miss is below the two-miss trigger, so the GENERAL base rate stands.
    assert_ratio(first["effective_attrition_pct"], 0.2200, "effective_attrition_pct")
    after_first = get_success_data(api.get_pledge_campaign(campaign["id"], CREDIT_ANALYST))
    assert after_first["attrition_adjusted_value_cents"] == 7800000

    second = get_success_data(
        api.record_pledge_payment(
            pledge["id"], installment_payload(2, "MISSED", 0), LOAN_SERVICER
        )
    )
    assert_fields(second, status="ACTIVE", missed_payments_count=2)
    # 0.22 plus the 0.15 penalty is 0.37, still under the 0.60 ceiling.
    assert_ratio(second["effective_attrition_pct"], 0.3700, "effective_attrition_pct")
    after_second = get_success_data(api.get_pledge_campaign(campaign["id"], CREDIT_ANALYST))
    assert_fields(
        after_second,
        attrition_adjusted_value_cents=6300000,
        active_pledged_cents=10000000,
    )

    third = get_success_data(
        api.record_pledge_payment(
            pledge["id"], installment_payload(3, "MISSED", 0), LOAN_SERVICER
        )
    )
    assert_fields(
        third,
        status="LAPSED",
        missed_payments_count=3,
        lapse_reason="AUTO_THREE_MISSED_INSTALLMENTS",
        collected_cents=0,
        payments_made_count=0,
    )
    lapsed_campaign = get_success_data(
        api.get_pledge_campaign(campaign["id"], CREDIT_ANALYST)
    )
    assert_fields(
        lapsed_campaign,
        active_pledged_cents=0,
        lapsed_pledged_cents=10000000,
        total_pledged_cents=10000000,
        attrition_adjusted_value_cents=0,
        sponsor_projected_value_cents=0,
    )

    validate_error(
        api.record_pledge_payment(
            pledge["id"], installment_payload(4, "MISSED", 0), LOAN_SERVICER
        ),
        ERR_PLEDGE_INVALID_STATE,
        409,
    )
