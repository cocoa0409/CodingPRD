"""Appraisal valuation variants, segregation of duties, OCC, and insurance pricing."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    onboard_member, setup_member_locker_bottle, setup_active_member_with_locker,
    store_bottle, create_appraisal, finalize_appraisal, create_finalized_appraisal,
    quote_policy, make_appraiser_headers,
    APPRAISER_ALPHA, APPRAISER_BETA,
)

MGR = TEST_USERS["cellar_manager_headers"]
AGENT = TEST_USERS["insurance_agent_headers"]


# --------------------------------------------------------------------------- #
# Queue A — dual_variant_calc / appraisal_market_vs_replacement_diverge
# --------------------------------------------------------------------------- #
def test_appraisal_market_comparable_no_uplift(api):
    """PRD §3.5: "under `MARKET_COMPARABLE` the `assessed_value_cents` is the
    `base_value_cents` as-is, taken as an auction comparable with no uplift".

    Design: Difficulty/dual_variant_calc/appraisal_market_vs_replacement_diverge
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, size_tier="LARGE", climate_zone="RED", capacity=6, tier="RESERVE"
    )
    ap = create_appraisal(api, bottle["id"], method="MARKET_COMPARABLE", base_value_cents=5_000_000)
    assert ap["assessed_value_cents"] == 5_000_000, (
        f"market-comparable assessed should equal base, got {ap['assessed_value_cents']}"
    )


def test_appraisal_replacement_cost_uplift_diverges(api):
    """PRD §3.5: "under `REPLACEMENT_COST` the `assessed_value_cents` is the
    `base_value_cents` multiplied by a replacement uplift of 1.20, rounded half-up to
    integer cents. So the same `base_value_cents` yields a higher assessed value under
    replacement cost than under market comparable."

    Design: Difficulty/dual_variant_calc/appraisal_market_vs_replacement_diverge
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, size_tier="LARGE", climate_zone="RED", capacity=6, tier="RESERVE"
    )
    market = create_appraisal(api, bottle["id"], method="MARKET_COMPARABLE", base_value_cents=5_000_000)
    repl = create_appraisal(api, bottle["id"], method="REPLACEMENT_COST", base_value_cents=5_000_000)
    assert repl["assessed_value_cents"] == 6_000_000, (
        f"replacement assessed should be 6000000, got {repl['assessed_value_cents']}"
    )
    assert repl["assessed_value_cents"] - market["assessed_value_cents"] == 1_000_000, (
        "replacement must exceed market by exactly 1000000 for the same base"
    )


# --------------------------------------------------------------------------- #
# Queue A — combinatorial_formula / insurance_premium_round_per_bottle_then_sum
# --------------------------------------------------------------------------- #
def _two_documented_appraised_bottles(api, appraised=700):
    member, locker = setup_active_member_with_locker(
        api, size_tier="SMALL", climate_zone="RED", capacity=4, tier="PREMIUM"
    )
    b1 = store_bottle(api, locker["id"], member["id"], wine_name="Wine One",
                      varietal="Nebbiolo", provenance_status="DOCUMENTED")
    b2 = store_bottle(api, locker["id"], member["id"], wine_name="Wine Two",
                      varietal="Nebbiolo", provenance_status="DOCUMENTED")
    create_finalized_appraisal(api, b1, method="MARKET_COMPARABLE", base_value_cents=appraised)
    create_finalized_appraisal(api, b2, method="MARKET_COMPARABLE", base_value_cents=appraised)
    return member, b1, b2


def test_insurance_premium_rounds_per_bottle_then_sums(api):
    """PRD §3.6: "the resulting term is rounded half-up to integer cents; the policy
    premium is the sum of those already-rounded per-bottle terms, not the single rounding
    of a raw total."

    Design: Difficulty/combinatorial_formula/insurance_premium_round_per_bottle_then_sum
    """
    member, b1, b2 = _two_documented_appraised_bottles(api, appraised=700)
    policy = quote_policy(api, member["id"], [b1["id"], b2["id"]], coverage_tier="FULL")
    # round(700*0.015)=11 per bottle -> 11+11 = 22 (NOT round(10.5+10.5)=21)
    assert policy["premium_cents"] == 22, (
        f"premium must be 22 (round-per-bottle then sum), got {policy['premium_cents']}"
    )


def test_insurance_insured_value_sums_appraised(api):
    """PRD §3.6: "The `insured_value_cents` is the sum of `appraised_value_cents` across
    the covered bottles."

    Design: Difficulty/combinatorial_formula/insurance_premium_round_per_bottle_then_sum
    """
    member, b1, b2 = _two_documented_appraised_bottles(api, appraised=700)
    policy = quote_policy(api, member["id"], [b1["id"], b2["id"]], coverage_tier="FULL")
    assert policy["insured_value_cents"] == 1400, (
        f"insured value must sum appraised (700+700), got {policy['insured_value_cents']}"
    )


# --------------------------------------------------------------------------- #
# Queue B — errors / finalize_by_creator_returns_segregation_of_duties
# --------------------------------------------------------------------------- #
def test_finalize_by_creator_returns_segregation_of_duties(api):
    """PRD §3.5: "the acting `X-User-ID` must differ from the appraisal's
    `created_by_user_id` — an appraiser finalizing their own draft is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/finalize_by_creator_returns_segregation_of_duties
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, tier="PREMIUM", bottle_overrides={"provenance_status": "DOCUMENTED"}
    )
    ap = create_appraisal(api, bottle["id"], method="MARKET_COMPARABLE",
                          base_value_cents=4_000_000, creator=APPRAISER_ALPHA)
    validate_error(
        api.finalize_appraisal(ap["id"], {"expected_bottle_version": bottle["version"]},
                               make_appraiser_headers(APPRAISER_ALPHA)),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )


# --------------------------------------------------------------------------- #
# Queue B — errors / bind_underfunded_returns_insufficient_funds
# --------------------------------------------------------------------------- #
def test_bind_underfunded_returns_insufficient_funds(api):
    """PRD §3.6: "the member's `wallet_balance_cents` minus the policy `premium_cents`
    must be at least the wallet floor of −100,000 cents; a bind that would drop the wallet
    below that floor is refused with `ERR_INSUFFICIENT_FUNDS`."

    Design: Corner/errors/bind_underfunded_returns_insufficient_funds
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, tier="PREMIUM", bottle_overrides={"provenance_status": "DOCUMENTED"}
    )
    create_finalized_appraisal(api, bottle, method="MARKET_COMPARABLE", base_value_cents=7_000_000)
    policy = quote_policy(api, member["id"], [bottle["id"]], coverage_tier="FULL")
    # premium = round(7000000*0.015) = 105000 ; 0 - 105000 = -105000 < -100000 floor
    assert policy["premium_cents"] == 105000
    validate_error(
        api.bind_insurance_policy(policy["id"], AGENT), ApiErrorId.ERR_INSUFFICIENT_FUNDS.value
    )


# --------------------------------------------------------------------------- #
# Queue B — errors / policy_covering_unowned_bottle_returns_not_owned
# --------------------------------------------------------------------------- #
def test_policy_covering_unowned_bottle_returns_not_owned(api):
    """PRD §3.6: "Every covered bottle must belong to the named member; a policy
    referencing a bottle the member does not own is refused with `ERR_BOTTLE_NOT_OWNED`."

    Design: Corner/errors/policy_covering_unowned_bottle_returns_not_owned
    """
    member_a, locker_a, bottle_a = setup_member_locker_bottle(
        api, size_tier="SMALL", climate_zone="RED", capacity=2, tier="PREMIUM"
    )
    member_b = onboard_member(api, tier="PREMIUM")
    from test_helpers import create_insurance_policy_payload
    payload = create_insurance_policy_payload(
        member_id=member_b["id"], coverage_tier="FULL", covered_bottle_ids=[bottle_a["id"]]
    )
    validate_error(
        api.create_insurance_policy(payload, AGENT), ApiErrorId.ERR_BOTTLE_NOT_OWNED.value
    )


# --------------------------------------------------------------------------- #
# Queue B — cross_cutting / appraisal_finalize_stale_bottle_version_returns_stale_version
# --------------------------------------------------------------------------- #
def test_appraisal_finalize_stale_bottle_version_returns_stale_version(api):
    """PRD §2.7: "The finalize request must carry `expected_bottle_version`, a
    non-optional input field carrying the client's last observed `version` of the target
    `Bottle`. If that value does not match the bottle's current `version`, the finalize is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/appraisal_finalize_stale_bottle_version_returns_stale_version
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, tier="PREMIUM", bottle_overrides={"provenance_status": "DOCUMENTED"}
    )
    b_v = bottle["version"]
    ap1 = create_appraisal(api, bottle["id"], method="MARKET_COMPARABLE",
                           base_value_cents=5_000_000, creator=APPRAISER_ALPHA)
    ap2 = create_appraisal(api, bottle["id"], method="REPLACEMENT_COST",
                           base_value_cents=5_000_000, creator=APPRAISER_ALPHA)
    finalize_appraisal(api, ap1["id"], b_v, finalizer=APPRAISER_BETA)  # bumps bottle.version
    # ap2 still carries the pre-bump version -> stale
    validate_error(
        api.finalize_appraisal(ap2["id"], {"expected_bottle_version": b_v},
                               make_appraiser_headers(APPRAISER_BETA)),
        ApiErrorId.ERR_STALE_VERSION.value,
    )


# --------------------------------------------------------------------------- #
# Queue B — cross_cutting / appraisal_finalize_correct_version_bumps_bottle_version
# --------------------------------------------------------------------------- #
def test_appraisal_finalize_correct_version_bumps_bottle_version(api):
    """PRD §3.5: "The bottle's `appraised_value_cents` is rewritten to this appraisal's
    `assessed_value_cents`, the appraisal's `effective_date` is stamped from the current
    logical clock, and the bottle's `version` is incremented".

    Design: Corner/cross_cutting_complexity_layers/appraisal_finalize_correct_version_bumps_bottle_version
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, tier="PREMIUM", bottle_overrides={"provenance_status": "DOCUMENTED"}
    )
    ap = create_appraisal(api, bottle["id"], method="MARKET_COMPARABLE",
                          base_value_cents=5_000_000, creator=APPRAISER_ALPHA)
    finalize_appraisal(api, ap["id"], bottle["version"], finalizer=APPRAISER_BETA)
    b = validate_success(api.get_bottle(bottle["id"], MGR))
    assert b["appraised_value_cents"] == 5_000_000, (
        f"appraised value must be rewritten to 5000000, got {b['appraised_value_cents']}"
    )
    assert b["version"] == 2, f"bottle version must increment 1->2, got {b['version']}"


# --------------------------------------------------------------------------- #
# Queue B — consistency_model / bottle_appraised_value_visible_immediately_after_finalize
# --------------------------------------------------------------------------- #
def test_bottle_appraised_value_visible_immediately_after_finalize(api):
    """PRD §3.5: "A bottle's `appraised_value_cents` therefore always reflects the latest
    finalized appraisal, or remains 0 if none exists."

    Design: Corner/consistency_model/bottle_appraised_value_visible_immediately_after_finalize
    """
    member, locker, bottle = setup_member_locker_bottle(
        api, tier="PREMIUM", bottle_overrides={"provenance_status": "DOCUMENTED"}
    )
    ap = create_appraisal(api, bottle["id"], method="REPLACEMENT_COST",
                          base_value_cents=5_000_000, creator=APPRAISER_ALPHA)
    finalize_appraisal(api, ap["id"], bottle["version"], finalizer=APPRAISER_BETA)
    b = validate_success(api.get_bottle(bottle["id"], MGR))
    assert b["appraised_value_cents"] == 6_000_000, (
        f"REPLACEMENT_COST 5000000 -> 6000000 visible immediately, got {b['appraised_value_cents']}"
    )
