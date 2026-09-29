"""Arithmetic tests for the two composite variants, the two tuition variants,
the aid waterfall and the income-band aid cap.

Every test builds its own state from an empty database through public
endpoints only, because the harness restarts the server and empties the
database before each test.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_aid_pool_conserved
from test_helpers.test_users import (
    FINANCE_HEADERS,
    FINANCE_HEADERS_2,
    guardian_headers,
)

# --------------------------------------------------------------------------
# Local builders (the shared helpers cover the single-member happy path only)
# --------------------------------------------------------------------------

# Four rubric sheets whose weighted totals are 81.80, 94.60, 66.60 and 82.40.
_VARIED_RUBRICS: List[Dict[str, int]] = [
    {"tone_score": 22, "rhythm_score": 20, "intonation_score": 21, "sight_reading_score": 18},
    {"tone_score": 25, "rhythm_score": 24, "intonation_score": 23, "sight_reading_score": 22},
    {"tone_score": 18, "rhythm_score": 17, "intonation_score": 16, "sight_reading_score": 15},
    {"tone_score": 21, "rhythm_score": 22, "intonation_score": 20, "sight_reading_score": 19},
]


def _four_sheet_scored_audition(api: ApiClient) -> Dict[str, Any]:
    """A VIOLIN audition in `SCORED` holding four sheets with distinct totals."""
    ctx = X.open_season_with_ensemble(
        api,
        clock=C.FIXTURE_CLOCK,
        ensemble_overrides={"tier": "PHILHARMONIC", "max_total_size": 4},
        quota_overrides={"instrument": "VIOLIN"},
    )
    member = X.create_member(api, legal_name="Ada Strings", primary_instrument="VIOLIN")
    panelists = X.create_panelists(api, count=4, instrument_expertise="VIOLIN")
    slot = X.create_audition_slot(
        api,
        ctx["season"]["id"],
        [p["id"] for p in panelists],
        instrument_focus="VIOLIN",
        quorum_required=4,
        capacity=4,
    )
    audition = X.create_audition(api, member["id"], ctx["season"]["id"])
    X.schedule_audition(api, audition["id"], slot["id"])
    sheets = [
        X.submit_sheet(api, audition["id"], panelists[index]["id"], **_VARIED_RUBRICS[index])
        for index in range(4)
    ]
    ctx.update(
        {
            "member": member,
            "panelists": panelists,
            "slot": slot,
            "audition": X.read_audition(api, audition["id"]),
            "sheets": sheets,
        }
    )
    return ctx


def _preliminary_account(api: ApiClient, household_income_band: str) -> Dict[str, Any]:
    """A seated PHILHARMONIC musician with a `PRELIMINARY` tuition account.

    `tuition_base_cents` is the fixture default 123223 and the tier multiplier
    is 1.00, so the gross tier-adjusted figure is exactly 123223.
    """
    return X.accepted_placement(
        api,
        instrument_loan_requested=False,
        member_overrides={
            "household_income_band": household_income_band,
            "sibling_enrolled": True,
            "years_in_org": 1,
        },
    )


def _request_aid(api: ApiClient, account_id: str, member_id: str, cents: int) -> Dict[str, Any]:
    return validate_success(
        api.request_aid(account_id, F.aid_request_payload(cents), guardian_headers(member_id))
    )


def _review_aid(api: ApiClient, account_id: str) -> Dict[str, Any]:
    return validate_success(api.review_aid(account_id, {}, FINANCE_HEADERS))


def _run_aid_award(api: ApiClient, season_id: str) -> Dict[str, Any]:
    """Execute the waterfall as a second officer, so segregation of duties holds."""
    payload = F.aid_award_run_payload(X.season_version(api, season_id))
    return validate_success(api.aid_award_run(season_id, payload, FINANCE_HEADERS_2))


def _finalize(api: ApiClient, account_id: str) -> Dict[str, Any]:
    return validate_success(api.finalize_assessment(account_id, {}, FINANCE_HEADERS))


def _capped_award_account(api: ApiClient) -> Dict[str, Any]:
    """A `BAND_C` account carrying an `APPROVED`, still-uncapped award of 30000."""
    ctx = _preliminary_account(api, "BAND_C")
    account_id = ctx["account"]["id"]
    _request_aid(api, account_id, ctx["member"]["id"], 30000)
    _review_aid(api, account_id)
    ctx["run"] = _run_aid_award(api, ctx["season"]["id"])
    ctx["account"] = X.read_account(api, account_id)
    ctx["season"] = X.read_season(api, ctx["season"]["id"])
    return ctx


_AID_MEMBERS = [
    {
        "legal_name": "Aid One",
        "primary_instrument": "VIOLIN",
        "grade_level": 11,
        "graduation_year": 2028,
        "household_income_band": "BAND_A",
        "years_in_org": 2,
    },
    {
        "legal_name": "Aid Two",
        "primary_instrument": "VIOLIN",
        "grade_level": 10,
        "graduation_year": 2029,
        "household_income_band": "BAND_B",
        "years_in_org": 1,
    },
    {
        "legal_name": "Aid Three",
        "primary_instrument": "VIOLIN",
        "grade_level": 9,
        "graduation_year": 2030,
        "household_income_band": "BAND_C",
        "years_in_org": 0,
    },
]

_AID_REQUESTS = [12000, 3000, 12000]


def _reviewed_aid_queue(api: ApiClient) -> Dict[str, Any]:
    """Three seated PHILHARMONIC musicians whose accounts all sit `UNDER_REVIEW`.

    `aid_budget_cents` is 40000, so the per-member ceiling is 12000 cents.
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api, aid_budget_cents=40000)
    ensemble = X.create_ensemble(
        api, season["id"], tier="PHILHARMONIC", min_total_size=3, max_total_size=6
    )
    quota = X.create_section_quota(
        api, ensemble["id"], instrument="VIOLIN", min_count=1, target_count=3, max_count=3
    )
    members = [X.create_member(api, **spec) for spec in _AID_MEMBERS]
    panelists = X.create_panelists(api, count=3, instrument_expertise="VIOLIN")
    X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    slot = X.create_audition_slot(
        api,
        season["id"],
        [p["id"] for p in panelists],
        instrument_focus="VIOLIN",
        end_at="2026-08-12T11:00:00Z",
        quorum_required=3,
        capacity=4,
    )
    auditions = []
    for member in members:
        audition = X.create_audition(api, member["id"], season["id"])
        X.schedule_audition(api, audition["id"], slot["id"])
        auditions.append(audition)
    for audition in auditions:
        X.submit_uniform_sheets(api, audition["id"], panelists, 20)
        X.adjudicate(api, audition["id"])
    X.advance_season(api, season["id"], "PLACEMENT")
    placements = [
        X.create_placement(api, audition["id"], ensemble["id"], offer_kind="OFFER")
        for audition in auditions
    ]
    for placement, member in zip(placements, members):
        X.accept_placement(
            api, placement["id"], member["id"], instrument_loan_requested=False
        )
    accounts = [X.sole_account(api, member["id"], season["id"]) for member in members]
    for account, member, cents in zip(accounts, members, _AID_REQUESTS):
        _request_aid(api, account["id"], member["id"], cents)
    accounts = [_review_aid(api, account["id"]) for account in accounts]
    return {
        "season": X.read_season(api, season["id"]),
        "ensemble": ensemble,
        "quota": quota,
        "members": members,
        "accounts": accounts,
    }


def _awarded_aid_queue(api: ApiClient) -> Dict[str, Any]:
    ctx = _reviewed_aid_queue(api)
    ctx["run"] = _run_aid_award(api, ctx["season"]["id"])
    ctx["accounts"] = [X.read_account(api, a["id"]) for a in ctx["accounts"]]
    ctx["season"] = X.read_season(api, ctx["season"]["id"])
    return ctx


# --------------------------------------------------------------------------
# The two audition composites over one identical sheet set
# --------------------------------------------------------------------------

def test_rubric_sheet_weighted_total_applies_the_four_declared_weights(api):
    """Each sheet's weighted_total weights tone 1.2, rhythm 1.0, intonation 1.0 and sight-reading 0.8.

    PRD §3.4: "Each sheet's `weighted_total` is computed before the row is persisted, by weighting the four raw rubric integers and rounding the sum half up to two decimal places: tone counts 1.2 times its raw score, rhythm 1.0 times, intonation 1.0 times, and sight-reading 0.8 times."

    Design: Difficulty/dual_variant_calc/audition_composite_provisional_vs_final_diverge
    """
    ctx = _four_sheet_scored_audition(api)

    totals = [float(sheet["weighted_total"]) for sheet in ctx["sheets"]]
    assert totals == [81.80, 94.60, 66.60, 82.40]


def test_provisional_composite_is_the_untrimmed_mean_of_the_current_round(api):
    """Reaching quorum stores the plain mean of all four sheets, 81.35, with no trimming.

    PRD §3.4: "When that count reaches the slot's `quorum_required`, the server advances the audition `SCHEDULED → SCORED` and stores `composite_provisional_score`: the plain arithmetic mean of the `weighted_total` values of every sheet in the current round, rounded half up to two decimal places, with no trimming whatever the number of sheets."

    Design: Difficulty/dual_variant_calc/audition_composite_provisional_vs_final_diverge
    """
    ctx = _four_sheet_scored_audition(api)

    audition = ctx["audition"]
    assert audition["status"] == "SCORED"
    assert audition["submitted_score_count"] == 4
    assert float(audition["composite_provisional_score"]) == 81.35


def test_final_composite_discards_one_maximum_and_one_minimum_sheet(api):
    """Adjudicating four sheets trims 94.60 and 66.60 and averages the survivors to 82.10.

    PRD §3.4: "When the round holds four or more sheets, exactly one sheet holding the maximum `weighted_total` and exactly one sheet holding the minimum are discarded — and where several sheets tie on an extreme value, the one with the earliest `created_at` is the one discarded, never the one with the lowest `id` — after which the mean of the surviving sheets is rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/audition_composite_provisional_vs_final_diverge
    """
    ctx = _four_sheet_scored_audition(api)

    audition = X.adjudicate(api, ctx["audition"]["id"])

    assert audition["status"] == "ADJUDICATED"
    assert float(audition["composite_final_score"]) == 82.10
    assert audition["submitted_score_count"] == 4


def test_the_two_composites_diverge_on_one_identical_sheet_set(api):
    """Sheets of 81.80, 94.60, 66.60 and 82.40 leave the adjudicated row holding 81.35 and 82.10.

    PRD §3.4: "The two composites therefore diverge whenever the discarded extremes are not symmetric about the mean: four sheets scoring 81.80, 94.60, 66.60 and 82.40 yield a provisional composite of 81.35 and a final composite of 82.10."

    Design: Difficulty/dual_variant_calc/audition_composite_provisional_vs_final_diverge
    """
    ctx = _four_sheet_scored_audition(api)
    assert [float(sheet["weighted_total"]) for sheet in ctx["sheets"]] == [
        81.80,
        94.60,
        66.60,
        82.40,
    ]

    audition = X.adjudicate(api, ctx["audition"]["id"])

    assert float(audition["composite_provisional_score"]) == 81.35
    assert float(audition["composite_final_score"]) == 82.10
    assert round(
        float(audition["composite_final_score"])
        - float(audition["composite_provisional_score"]),
        2,
    ) == 0.75


def test_tier_recommendation_derives_from_the_final_composite(api):
    """A final composite of 82.10 falls in the inclusive 75.00 band and recommends PHILHARMONIC.

    PRD §3.4: "Immediately after the final composite is stored, `tier_recommendation` is derived from it by three inclusive threshold comparisons on the two-decimal value: a composite of at least 85.00 recommends `SYMPHONY`; otherwise a composite of at least 75.00 recommends `PHILHARMONIC`; otherwise a composite of at least 62.50 recommends `CONCERT_ORCHESTRA`; and anything below that is `NOT_PLACED`."

    Design: Difficulty/dual_variant_calc/audition_composite_provisional_vs_final_diverge
    """
    ctx = _four_sheet_scored_audition(api)

    audition = X.adjudicate(api, ctx["audition"]["id"])

    assert float(audition["composite_final_score"]) == 82.10
    assert audition["tier_recommendation"] == "PHILHARMONIC"


# --------------------------------------------------------------------------
# The two tuition assessment variants over one identical member
# --------------------------------------------------------------------------

def test_preliminary_assessment_forces_both_discount_components_to_zero(api):
    """The preliminary variant zeroes both discounts, so assessed_cents is the gross 123223.

    PRD §3.7: "It forces both discount components to zero — `sibling_discount_cents` is 0 and `loyalty_credit_cents` is 0 — so `assessed_cents` equals the gross tier-adjusted figure exactly."

    Design: Difficulty/dual_variant_calc/tuition_preliminary_vs_final_assessment_diverge
    """
    ctx = _preliminary_account(api, "BAND_B")

    account = ctx["account"]
    assert account["assessment_variant"] == "PRELIMINARY"
    assert account["assessed_cents"] == 123223
    assert account["sibling_discount_cents"] == 0
    assert account["loyalty_credit_cents"] == 0


def test_preliminary_assessment_moves_billing_status_to_current(api):
    """A positive preliminary assessment moves the account out of PENDING_ASSESSMENT.

    PRD §3.7: "With a positive `assessed_cents` the account's `billing_status` moves `PENDING_ASSESSMENT → CURRENT`."

    Design: Difficulty/dual_variant_calc/tuition_preliminary_vs_final_assessment_diverge
    """
    ctx = _preliminary_account(api, "BAND_B")

    account = ctx["account"]
    assert account["assessed_cents"] == 123223
    assert account["billing_status"] == "CURRENT"


def test_final_assessment_subtracts_both_components_from_the_gross(api):
    """Finalizing the same member's account switches the variant and assesses 109053.

    PRD §3.7: "`assessed_cents` is then the gross minus `sibling_discount_cents` minus `loyalty_credit_cents`."

    Design: Difficulty/dual_variant_calc/tuition_preliminary_vs_final_assessment_diverge
    """
    ctx = _preliminary_account(api, "BAND_B")
    assert ctx["account"]["assessed_cents"] == 123223

    account = _finalize(api, ctx["account"]["id"])

    assert account["assessment_variant"] == "FINAL"
    assert account["assessed_cents"] == 109053
    # The two variants disagree by exactly the two rounded components.
    assert 123223 - account["assessed_cents"] == 14170


# --------------------------------------------------------------------------
# Component rounding order inside the final tuition assessment
# --------------------------------------------------------------------------

def test_sibling_discount_is_ten_percent_of_the_gross_rounded_on_its_own(api):
    """An exact sibling component of 12322.30 on a gross of 123223 stores 12322.

    PRD §3.7: "`sibling_discount_cents` is ten percent of the gross, rounded half up to whole cents, when the musician's `sibling_enrolled` is true, and 0 otherwise."

    Design: Difficulty/combinatorial_formula/tuition_component_rounding_order_pinned
    """
    ctx = _preliminary_account(api, "BAND_B")

    account = _finalize(api, ctx["account"]["id"])

    assert account["sibling_discount_cents"] == 12322


def test_loyalty_credit_is_one_and_a_half_percent_per_credited_year_rounded_on_its_own(api):
    """One credited year on a gross of 123223 gives an exact 1848.345 and stores 1848.

    PRD §3.7: "The loyalty component first caps the credited years at four: the credited year count is the lesser of the musician's `years_in_org` and 4, and when that count is at least 1, `loyalty_credit_cents` is one and a half percent of the gross multiplied by the credited year count, rounded half up to whole cents, and 0 when the credited year count is zero."

    Design: Difficulty/combinatorial_formula/tuition_component_rounding_order_pinned
    """
    ctx = _preliminary_account(api, "BAND_B")

    account = _finalize(api, ctx["account"]["id"])

    assert account["loyalty_credit_cents"] == 1848


def test_assessed_cents_subtracts_rounded_components_not_a_rounded_sum(api):
    """Rounding each component before subtracting leaves 109053, never the 109052 of a rounded sum.

    PRD §3.7: "The rounding order here is pinned and observable: each component is rounded to whole cents *first*, and only then are the rounded components subtracted from the gross."

    Design: Difficulty/combinatorial_formula/tuition_component_rounding_order_pinned
    """
    ctx = _preliminary_account(api, "BAND_B")

    account = _finalize(api, ctx["account"]["id"])

    assert account["sibling_discount_cents"] + account["loyalty_credit_cents"] == 14170
    assert account["assessed_cents"] == 109053
    assert account["assessed_cents"] != 109052


# --------------------------------------------------------------------------
# The aid waterfall: a three-input clamp and a floor that spares the pool
# --------------------------------------------------------------------------

def test_aid_need_score_sums_band_seniority_and_tier_points(api):
    """Opening each request for funding scores 40+6+3, 25+3+3 and 10+0+3 need points.

    PRD §3.7: "The review records `aid_reviewed_by_user_id` from the acting `X-User-ID`, which becomes the segregation-of-duties anchor for the award run, and it computes the waterfall sort key `aid_need_score` as an integer with no rounding: the band contributes 40 points for `BAND_A`, 25 for `BAND_B` and 10 for `BAND_C`; an enrolled sibling adds 8 points; seniority adds 3 points for each year in the organization up to a ceiling of five counted years, so the seniority term is 3 multiplied by the lesser of `years_in_org` and 5; a requested instrument loan on the accepted placement adds 6 points; and the tier snapshot adds 5 points for `SYMPHONY`, 3 for `PHILHARMONIC` and 1 for `CONCERT_ORCHESTRA`."

    Design: Difficulty/combinatorial_formula/aid_grant_triple_min_with_floor_branch
    """
    ctx = _reviewed_aid_queue(api)

    scores = [account["aid_need_score"] for account in ctx["accounts"]]
    assert scores == [49, 31, 13]
    assert all(account["aid_status"] == "UNDER_REVIEW" for account in ctx["accounts"])


def test_grant_is_the_smallest_of_request_ceiling_and_running_remainder(api):
    """The head of the queue requests 12000 against a 12000 ceiling and is awarded 12000.

    PRD §3.7: "The queue is then walked strictly in order, one account at a time: the candidate grant is the smallest of the account's `aid_requested_cents`, the per-member ceiling, and the running remainder."

    Design: Difficulty/combinatorial_formula/aid_grant_triple_min_with_floor_branch
    """
    ctx = _awarded_aid_queue(api)

    first = ctx["accounts"][0]
    assert first["aid_status"] == "APPROVED"
    assert first["aid_awarded_cents"] == 12000
    assert first["aid_effective_cents"] == 12000


def test_clamped_grant_below_the_minimum_award_is_denied_below_min_award(api):
    """A 3000-cent request clamps to 3000, falls under the 5000 floor and is denied.

    PRD §3.7: "If the candidate grant falls below 5000 cents, the account is denied instead — `aid_awarded_cents` is set to 0, `aid_status` becomes `DENIED`, and `aid_denial_reason` records `INSUFFICIENT_BUDGET` when the running remainder was the binding constraint by being itself below 5000 cents, and `BELOW_MIN_AWARD` otherwise."

    Design: Difficulty/combinatorial_formula/aid_grant_triple_min_with_floor_branch
    """
    ctx = _awarded_aid_queue(api)

    second = ctx["accounts"][1]
    assert second["aid_status"] == "DENIED"
    assert second["aid_awarded_cents"] == 0
    assert second["aid_denial_reason"] == "BELOW_MIN_AWARD"


def test_a_denial_leaves_the_remainder_for_the_applicant_behind_it(api):
    """The denied 3000 never leaves the pool, so the last applicant still draws a full 12000.

    PRD §3.7: "Crucially, a denial does **not** decrease the running remainder: the money stays in the pool for the applicants behind it, and clamping the grant *before* the minimum-award test, rather than committing and then reversing, is what makes the later applicants' outcomes depend observably on queue order."

    Design: Difficulty/combinatorial_formula/aid_grant_triple_min_with_floor_branch
    """
    ctx = _awarded_aid_queue(api)

    third = ctx["accounts"][2]
    assert third["aid_status"] == "APPROVED"
    assert third["aid_awarded_cents"] == 12000
    assert ctx["season"]["aid_committed_cents"] == 24000
    assert ctx["season"]["aid_available_cents"] == 16000
    assert_aid_pool_conserved(ctx["season"])


def test_award_run_reports_its_approved_and_denied_counts(api):
    """The run over three reviewed accounts reports two approvals and one denial.

    PRD §3.7: "The run reports `approved_count`, `denied_count`, and the season's resulting `aid_committed_cents` and `aid_available_cents`, and it increments the season's `version`."

    Design: Difficulty/combinatorial_formula/aid_grant_triple_min_with_floor_branch
    """
    ctx = _awarded_aid_queue(api)

    assert ctx["run"]["approved_count"] == 2
    assert ctx["run"]["denied_count"] == 1
    assert ctx["run"]["aid_committed_cents"] == 24000
    assert ctx["run"]["aid_available_cents"] == 16000


# --------------------------------------------------------------------------
# The income-band aid cap and the order it is evaluated in
# --------------------------------------------------------------------------

def test_award_run_credits_the_grant_uncapped_while_the_assessment_is_preliminary(api):
    """A 30000-cent grant is credited in full against the preliminary assessment of 123223.

    PRD §3.7: "If that candidate grant is at least 5000 cents, the account is approved — `aid_awarded_cents` is set to the grant, `aid_effective_cents` is set to the same grant (uncapped, because `assessment_variant` is still `PRELIMINARY`), `aid_awarded_by_user_id` records the acting officer, `aid_status` becomes `APPROVED`, the running remainder decreases by the grant, and the season's `aid_committed_cents` increases by the grant."

    Design: Difficulty/combinatorial_formula/aid_cap_evaluation_order_pinned
    """
    ctx = _capped_award_account(api)

    account = ctx["account"]
    assert account["aid_status"] == "APPROVED"
    assert account["aid_awarded_cents"] == 30000
    assert account["aid_effective_cents"] == 30000
    assert account["assessed_cents"] == 123223
    assert account["balance_cents"] == 93223
    assert ctx["season"]["aid_committed_cents"] == 30000
    assert ctx["season"]["aid_available_cents"] == 70000


def test_income_band_cap_is_a_percentage_of_the_final_assessed_amount(api):
    """The BAND_C cap is 25 percent of the recomputed 109053, so 27263 caps the 30000 award.

    PRD §3.7: "The cap is a percentage of the freshly recomputed `assessed_cents`, rounded half up to whole cents — sixty percent for `BAND_A`, forty percent for `BAND_B`, and twenty-five percent for `BAND_C`."

    Design: Difficulty/combinatorial_formula/aid_cap_evaluation_order_pinned
    """
    ctx = _capped_award_account(api)

    account = _finalize(api, ctx["account"]["id"])

    assert account["assessed_cents"] == 109053
    assert account["aid_effective_cents"] == 27263
    # The award itself is never rewritten by the cap.
    assert account["aid_awarded_cents"] == 30000


def test_capped_surplus_returns_to_the_season_aid_pool(api):
    """Capping 30000 down to 27263 hands the 2737-cent surplus back to the season.

    PRD §3.7: "`aid_effective_cents` becomes the lesser of `aid_awarded_cents` and that cap, and the surplus — the awarded amount minus the effective amount — is returned to the season pool: `aid_committed_cents` decreases by the surplus and `aid_available_cents` increases by the same surplus, preserving the invariant of §2.11."

    Design: Difficulty/combinatorial_formula/aid_cap_evaluation_order_pinned
    """
    ctx = _capped_award_account(api)

    _finalize(api, ctx["account"]["id"])
    season = X.read_season(api, ctx["season"]["id"])

    assert season["aid_committed_cents"] == 27263
    assert season["aid_available_cents"] == 72737
    assert season["aid_budget_cents"] == 100000
    assert_aid_pool_conserved(season)


def test_balance_recomputes_from_the_capped_effective_aid(api):
    """The balance falls out of the final assessed 109053 less the capped 27263.

    PRD §3.7: "The account's `balance_cents` is then `assessed_cents`, less `aid_effective_cents`, plus `instrument_loan_fee_cents`, less `payments_total_cents`."

    Design: Difficulty/combinatorial_formula/aid_cap_evaluation_order_pinned
    """
    ctx = _capped_award_account(api)
    assert ctx["account"]["balance_cents"] == 93223

    account = _finalize(api, ctx["account"]["id"])

    assert account["instrument_loan_fee_cents"] == 0
    assert account["payments_total_cents"] == 0
    assert account["balance_cents"] == 81790
