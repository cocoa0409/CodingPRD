"""Divergence between the two variants of the claim score and the two variants
of the seller strike ledger."""

from test_helpers import (
    ANALYST,
    CLAIM_STATUS_DRAFT,
    CLAIM_STATUS_SUBSTANTIATED,
    SELLER_STATUS_ACTIVE,
    SELLER_STATUS_UNDER_INVESTIGATION,
    VIOLATION_TYPE_COUNTERFEIT,
    assert_score_2dp,
    assert_score_4dp,
    assert_seller_strikes,
    authenticate_test_buy,
    create_claim,
    create_seller,
    create_test_buy,
    full_substantiation_score,
    preliminary_score,
    read_claim,
    read_seller,
    receive_test_buy,
    setup_flagged_listing,
    setup_removed_takedown,
    setup_second_removal_on_same_seller,
    validate_success,
)


def _counterfeit_claim_with_corroborating_buy(api):
    """A flagged listing scoring 0.8620 with a counterfeit-confirmed test buy.

    A 10000-cent reference against a 3000-cent price deviates 0.7000, and
    matcher output of 0.92 / 0.88 accumulates a match score of 0.8620.
    """
    ctx = setup_flagged_listing(
        api, clock="2026-08-03T09:00:00Z", price_cents=3000,
        image_match_score=0.92, text_match_score=0.88)
    ctx["claim"] = create_claim(
        api, ctx["brand"]["id"], ctx["listing"]["id"], ctx["registration"]["id"],
        claimed_violation_type=VIOLATION_TYPE_COUNTERFEIT)
    test_buy = create_test_buy(api, ctx["claim"]["id"], 4200, 700, 0)
    receive_test_buy(api, test_buy["id"], "LOT-2026-A", "COC-1")
    ctx["test_buy"] = authenticate_test_buy(api, test_buy["id"], "COUNTERFEIT", "LAB-1")
    return ctx


def test_preliminary_and_full_claim_variants_diverge_on_identical_rows(api):
    """PRD §3.5: "The *preliminary* variant runs at claim creation, when no evidence has been gathered yet: it multiplies the base by eighty hundredths and rounds half-up to two decimal places to produce `preliminary_score`."
    PRD §3.5: "It uses the undiscounted base and adds a corroboration bonus of 20.00 points when — and only when — there exists a test buy on this same claim whose status is `AUTHENTICATED_COUNTERFEIT` **and** whose `chain_of_custody_ref` is non-null."
    PRD §3.5: "Worked examples: a `match_score` of 0.8620 with a registration strength of 1.00 and zero standalone points yields a base of 51.72 plus 25 plus 0, or 76.72; the preliminary score is 61.376, which rounds to 61.38; the full score without corroboration is 76.72, which is below the threshold, and with corroboration is 96.72, which clears it."

    Design: Difficulty/dual_variant_calc/claim_preliminary_and_full_variants_diverge_on_identical_data
    """
    ctx = _counterfeit_claim_with_corroborating_buy(api)

    listing = ctx["listing"]
    assert_score_4dp(listing["match_score"], 0.8620, "match_score")

    claim = read_claim(api, ctx["claim"]["id"])
    assert_score_2dp(claim["registration_strength"], 1.00, "registration_strength")
    assert_score_2dp(claim["preliminary_score"], preliminary_score(0.8620, 1.00), "preliminary_score")
    assert_score_2dp(claim["preliminary_score"], 61.38, "preliminary_score")

    promoted = validate_success(api.substantiate_claim(claim["id"], headers=ANALYST), 200)
    assert_score_2dp(
        promoted["substantiation_score"],
        full_substantiation_score(0.8620, 1.00, 0.0, corroborated=True), "substantiation_score")
    assert_score_2dp(promoted["substantiation_score"], 96.72, "substantiation_score")
    assert promoted["status"] == CLAIM_STATUS_SUBSTANTIATED, (
        f"Expected SUBSTANTIATED, got {promoted['status']}")

    divergence = promoted["substantiation_score"] - promoted["preliminary_score"]
    assert abs(divergence - 35.34) < 5e-3, (
        f"Expected the two variants to diverge by 35.34, got {divergence}")


def test_preliminary_score_survives_the_corroborating_verdict_unrecomputed(api):
    """PRD §3.5: "`preliminary_score` is stamped once at creation and is never recomputed afterwards, no matter what happens to the listing, the seller or the registration later."
    PRD §3.6: "The parent claim's `substantiation_score` is recomputed with the full variant — the 20.00-point corroboration bonus now applies, since this row is exactly the corroborating buy the variant looks for — and the recomputed value is persisted on the claim, whose `version` is incremented by 1 alongside the test buy's."
    PRD §3.6: "The claim's status is **not** auto-advanced: reaching `SUBSTANTIATED` still requires the analyst to ask for substantiation explicitly."

    Design: Difficulty/dual_variant_calc/claim_preliminary_and_full_variants_diverge_on_identical_data
    """
    ctx = _counterfeit_claim_with_corroborating_buy(api)

    claim = read_claim(api, ctx["claim"]["id"])
    assert_score_2dp(claim["preliminary_score"], 61.38, "preliminary_score")
    assert_score_2dp(claim["substantiation_score"], 96.72, "substantiation_score")
    assert claim["status"] == CLAIM_STATUS_DRAFT, (
        f"A counterfeit verdict must not advance the claim itself, got {claim['status']}")


def test_standalone_and_cluster_strike_variants_diverge_after_an_alias_link(api):
    """PRD §3.3: "`standalone_strike_points` counts only strikes attributed to that exact seller row, ignoring every alias and the canonical root."
    PRD §3.3: "`cluster_strike_points` counts strikes across the whole alias cluster: the cluster is the root — which is the row's own `canonical_seller_id` when it has one, and otherwise the row's own `id` — unioned with every row that names that root as its `canonical_seller_id`."
    PRD §3.3: "To make the thresholds concrete: a single fresh takedown-removal strike is 12.55 points and leaves the seller `ACTIVE`; two fresh takedown-removal strikes total 25.10 and escalate the seller to `UNDER_INVESTIGATION`; one fresh seizure-confirmed strike is 25.15 and escalates on its own; one fresh cease-and-desist-ignored strike is 5.05."

    Design: Difficulty/dual_variant_calc/seller_standalone_and_cluster_strike_variants_diverge_after_alias_link
    """
    ctx = setup_removed_takedown(api, clock="2026-08-10T09:00:00Z")
    canonical = read_seller(api, ctx["seller"]["id"])
    assert_seller_strikes(canonical, 12.55, 12.55, SELLER_STATUS_ACTIVE)

    alias = create_seller(api, seller_ref="A2ALIAS", legal_name="Nightmarket Alias Ltd")
    assert_seller_strikes(alias, 0.00, 0.00, SELLER_STATUS_ACTIVE)

    linked = validate_success(
        api.link_alias(alias["id"], canonical["id"], canonical["version"], headers=ANALYST), 200)
    assert linked["canonical_seller_id"] == canonical["id"], (
        f"Expected canonical_seller_id {canonical['id']}, got {linked['canonical_seller_id']}")
    assert_seller_strikes(linked, 0.00, 12.55, SELLER_STATUS_ACTIVE)

    canonical_after = read_seller(api, canonical["id"])
    assert_seller_strikes(canonical_after, 12.55, 12.55, SELLER_STATUS_ACTIVE)


def test_cluster_variant_escalates_an_alias_carrying_no_strikes_of_its_own(api):
    """PRD §3.3: "A seller with zero standalone points can therefore still be blocked on the strength of a sibling's history."
    PRD §3.3: "Every recompute rewrites `status` for **every member of the cluster** from the cluster total, so all members always share the same status, and every member whose status or point totals actually changed has its `version` incremented by 1."
    PRD §3.3: "At a cluster total of 60.00 or more the seller is `BLOCKED`; at a cluster total of at least 25.00 but below 60.00 the seller is `UNDER_INVESTIGATION`; below 25.00 the seller is `ACTIVE`."

    Design: Difficulty/dual_variant_calc/seller_standalone_and_cluster_strike_variants_diverge_after_alias_link
    """
    ctx = setup_removed_takedown(api, clock="2026-08-10T09:00:00Z")
    ctx = setup_second_removal_on_same_seller(api, ctx)
    canonical = read_seller(api, ctx["seller"]["id"])
    assert_seller_strikes(canonical, 25.10, 25.10, SELLER_STATUS_UNDER_INVESTIGATION)

    alias = create_seller(api, seller_ref="A2ALIAS", legal_name="Nightmarket Alias Ltd")
    linked = validate_success(
        api.link_alias(alias["id"], canonical["id"], canonical["version"], headers=ANALYST), 200)
    assert_seller_strikes(linked, 0.00, 25.10, SELLER_STATUS_UNDER_INVESTIGATION)

    canonical_after = read_seller(api, canonical["id"])
    assert canonical_after["status"] == SELLER_STATUS_UNDER_INVESTIGATION, (
        f"Every cluster member shares one status, got {canonical_after['status']}")
