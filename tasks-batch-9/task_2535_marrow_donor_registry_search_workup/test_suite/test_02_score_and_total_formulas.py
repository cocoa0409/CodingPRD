"""Two multi-input formulas whose inputs interact non-linearly.

The candidate ranking score folds match quality, donor age and logistical
practicality into one number through a clamped age curve and a three-branch
logistics rule; the reimbursement total folds seven lines into a subtotal, a
tier keyed on that subtotal alone, and a coordination fee charged on the
post-discount base.
"""
import pytest

from test_helpers import (
    assertions as A,
    factories as f,
    fixtures,
    validate_success,
)

# The international partner registry of the design's claim scenarios: DE/EUR at
# an fx rate of 1.0850 and cooperation tier 2.
INTL_REGISTRY = {
    "country_code": "DE",
    "currency_code": "EUR",
    "fx_rate_to_usd": 1.0850,
    "is_domestic": False,
    "cooperation_tier": 2,
    "ct_response_deadline_hours": 168,
}

# A 41-year-old CMV-negative partner-registry volunteer with one prior donation
# and an ambiguous DQB1 locus.
D2_HLA = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "11:01"],
    "C": ["07:02", "07:04"],
    "DRB1": ["15:01", "03:01"],
    "DQB1": ["06", "02"],
}

D2_DONOR = {
    "age_years": 41,
    "sex": "M",
    "weight_kg": 84.0,
    "cmv_status": "NEGATIVE",
    "hla_typing_registry": D2_HLA,
    "consented_methods": ["PBSC", "MARROW"],
    "ambiguous_loci": ["DQB1"],
    "prior_donation_count": 1,
}

# A 55-year-old domestic volunteer with no ambiguity and a poorer clinical match.
D3_HLA = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "15:01"],
    "C": ["07:02", "03:04"],
    "DRB1": ["15:01", "11:01"],
    "DQB1": ["06:02", "02:01"],
}

D3_DONOR = {
    "age_years": 55,
    "sex": "M",
    "weight_kg": 91.0,
    "cmv_status": "POSITIVE",
    "hla_typing_registry": D3_HLA,
    "consented_methods": ["PBSC"],
    "ambiguous_loci": [],
    "prior_donation_count": 0,
}

INTL_SCOPE = {"search_scope": "DOMESTIC_AND_INTERNATIONAL"}


def by_donor(candidates: list) -> dict:
    """The materialised candidates keyed by `donor_id`."""
    return {candidate["donor_id"]: candidate for candidate in candidates}


def test_rank_score_blends_match_age_and_logistics_over_a_mixed_pool(
    api, coordinator_headers
):
    """PRD §3.3: "The age factor is one hundred reduced by 2.5 points for every whole year the donor's `age_years` differs from the ideal donor age of 27, taking the absolute difference in either direction, and the result is then held to no less than zero and no more than one hundred."
    PRD §3.3: "An international donor scores 55 plus 5 points per unit of its registry's `cooperation_tier`, but never rising above 70."
    PRD §3.3: "The ranking score is then 0.55 multiplied by the donor's already-rounded two-decimal `preliminary_score`, plus 0.25 multiplied by the age factor, plus 0.20 multiplied by the logistics factor, with the resulting weighted sum rounded half up to three decimal places exactly once."
    PRD §3.3: "Roles follow directly from position: the candidate at position 1 becomes `PRIMARY`, positions 2 and 3 become `BACKUP` — two backup slots — and positions 4 and 5 become `ARCHIVED_POOL`."
    PRD §3.3: "The search's `match_pool_size` records how many candidates were written and `backup_candidate_count` records how many of them are backups."
    PRD §3.3: "The coordinator supplies `patient_id`, a `search_scope` of either `DOMESTIC_ONLY` or `DOMESTIC_AND_INTERNATIONAL`, and optionally `min_preliminary_score` — a two-decimal number in the closed range 0.00 to 100.00 that defaults to 60.00 and acts as the floor a donor must reach to be worth materialising."
    PRD §3.3: "Each materialised candidate records its `search_request_id`, its `donor_id`, the computed `preliminary_score` and `rank_score`, its frozen `rank_position` and its `candidate_role`, opens in `status` `IDENTIFIED` with `ct_attempt_count` at zero, and carries `confirmed_score`, `confirmed_match_grade`, `screening_outcome`, `screening_deferral_type` and `promoted_from_rank` all null."
    PRD §2.3: "Two lists override that default: match-candidate lists are ordered by `rank_position` ascending and then by `created_at` ascending, and collection-booking lists are ordered by `start_at` ascending and then by `created_at` ascending."

    Design: Difficulty/combinatorial_formula/candidate_rank_score_combines_three_clamped_factors_mode_a
    """
    domestic = fixtures.create_registry()
    international = fixtures.create_international_registry()
    d1 = fixtures.create_donor(domestic["id"])
    d2 = fixtures.create_donor(international["id"], **D2_DONOR)
    d3 = fixtures.create_donor(domestic["id"], **D3_DONOR)
    patient = fixtures.create_patient(headers=coordinator_headers)

    search = validate_success(
        api.create_search_request(
            f.create_search_request_payload(patient["id"], **INTL_SCOPE),
            coordinator_headers,
        ),
        201,
    )
    A.assert_search_request(search)
    assert search["match_pool_size"] == 3
    assert search["backup_candidate_count"] == 2
    assert float(search["min_preliminary_score"]) == pytest.approx(60.00, abs=0.001), (
        "min_preliminary_score was omitted, so it defaults to 60.00"
    )

    candidates = fixtures.list_candidates(search["id"], headers=coordinator_headers)
    assert [candidate["donor_id"] for candidate in candidates] == [
        d1["id"],
        d2["id"],
        d3["id"],
    ], "the list must come back in rank_position order, which is rank_score descending"

    scored = by_donor(candidates)
    for candidate in candidates:
        A.assert_match_candidate(candidate)
        assert candidate["status"] == "IDENTIFIED"
        assert candidate["confirmed_score"] is None
        assert candidate["ct_attempt_count"] == 0

    c1 = scored[d1["id"]]
    assert float(c1["preliminary_score"]) == pytest.approx(94.75, abs=0.001)
    assert float(c1["rank_score"]) == pytest.approx(97.113, abs=0.0001), (
        "0.55*94.75 + 0.25*100 + 0.20*100 = 97.1125, which must round half up to "
        f"97.113, got {c1['rank_score']}"
    )
    assert c1["rank_position"] == 1
    assert c1["candidate_role"] == "PRIMARY"

    c2 = scored[d2["id"]]
    assert float(c2["preliminary_score"]) == pytest.approx(86.58, abs=0.001)
    assert float(c2["rank_score"]) == pytest.approx(76.869, abs=0.0001), (
        "0.55*86.58 + 0.25*65 + 0.20*min(70, 55+5*2) = 76.869, got "
        f"{c2['rank_score']}"
    )
    assert c2["rank_position"] == 2
    assert c2["candidate_role"] == "BACKUP"

    c3 = scored[d3["id"]]
    assert float(c3["preliminary_score"]) == pytest.approx(69.17, abs=0.001)
    assert float(c3["rank_score"]) == pytest.approx(65.544, abs=0.0001), (
        "0.55*69.17 + 0.25*max(0, 100-2.5*28) + 0.20*100 = 65.5435, which must round "
        f"half up to 65.544, got {c3['rank_score']}"
    )
    assert c3["rank_position"] == 3
    assert c3["candidate_role"] == "BACKUP"


def test_domestic_logistics_factor_falls_15_per_prior_donation_down_to_its_floor(
    api, coordinator_headers
):
    """PRD §3.3: "A domestic donor who has never donated before — `prior_donation_count` of zero — scores a full 100."
    PRD §3.3: "A domestic donor with prior donations scores one hundred reduced by 15 points per prior donation, but never dropping below 40."
    PRD §3.3: "The ranking score is then 0.55 multiplied by the donor's already-rounded two-decimal `preliminary_score`, plus 0.25 multiplied by the age factor, plus 0.20 multiplied by the logistics factor, with the resulting weighted sum rounded half up to three decimal places exactly once."
    PRD §3.3: "Eligible donors are ordered by `rank_score` descending, then — for donors whose ranking scores tie — by `preliminary_score` descending, and finally by the donor profile's `created_at` ascending, so that the volunteer enrolled earliest wins a genuine tie."

    Design: Difficulty/combinatorial_formula/candidate_rank_score_combines_three_clamped_factors_mode_a
    """
    registry = fixtures.create_registry()
    fresh = fixtures.create_donor(registry["id"], prior_donation_count=0)
    once = fixtures.create_donor(registry["id"], prior_donation_count=1)
    veteran = fixtures.create_donor(registry["id"], prior_donation_count=5)
    patient = fixtures.create_patient(headers=coordinator_headers)

    search = validate_success(
        api.create_search_request(
            f.create_search_request_payload(patient["id"]), coordinator_headers
        ),
        201,
    )
    assert search["match_pool_size"] == 3
    assert search["backup_candidate_count"] == 2

    scored = by_donor(
        fixtures.list_candidates(search["id"], headers=coordinator_headers)
    )
    expected = [
        (fresh["id"], 97.113, 1, "PRIMARY", "logistics 100 for a donor who never donated"),
        (once["id"], 94.113, 2, "BACKUP", "logistics 100 - 15*1 = 85"),
        (veteran["id"], 85.113, 3, "BACKUP", "logistics max(40, 100 - 15*5) = 40, the floor"),
    ]
    for donor_id, rank_score, position, role, why in expected:
        candidate = scored[donor_id]
        assert float(candidate["preliminary_score"]) == pytest.approx(94.75, abs=0.001), (
            "prior donations feed the ranking only, never the clinical match score"
        )
        assert float(candidate["rank_score"]) == pytest.approx(rank_score, abs=0.0001), (
            f"{why}: expected rank_score {rank_score}, got {candidate['rank_score']}"
        )
        assert candidate["rank_position"] == position
        assert candidate["candidate_role"] == role


def test_international_logistics_factor_rises_five_points_per_cooperation_tier(
    api, coordinator_headers
):
    """PRD §3.3: "An international donor scores 55 plus 5 points per unit of its registry's `cooperation_tier`, but never rising above 70."
    PRD §3.3: "The third is a domestic bonus of 1.0 point, awarded when the donor's registry has `is_domestic` true and otherwise zero."
    PRD §3.3: "The ranking score is then 0.55 multiplied by the donor's already-rounded two-decimal `preliminary_score`, plus 0.25 multiplied by the age factor, plus 0.20 multiplied by the logistics factor, with the resulting weighted sum rounded half up to three decimal places exactly once."
    PRD §3.3: "The search's `match_pool_size` records how many candidates were written and `backup_candidate_count` records how many of them are backups."

    Design: Difficulty/combinatorial_formula/candidate_rank_score_combines_three_clamped_factors_mode_a
    """
    tier_one = fixtures.create_international_registry(cooperation_tier=1)
    tier_three = fixtures.create_international_registry(cooperation_tier=3)
    weakly_served = fixtures.create_donor(tier_one["id"])
    strongly_served = fixtures.create_donor(tier_three["id"])
    patient = fixtures.create_patient(headers=coordinator_headers)

    search = validate_success(
        api.create_search_request(
            f.create_search_request_payload(patient["id"], **INTL_SCOPE),
            coordinator_headers,
        ),
        201,
    )
    assert search["match_pool_size"] == 2
    assert search["backup_candidate_count"] == 1

    scored = by_donor(
        fixtures.list_candidates(search["id"], headers=coordinator_headers)
    )
    for donor in (weakly_served, strongly_served):
        assert float(scored[donor["id"]]["preliminary_score"]) == pytest.approx(
            93.75, abs=0.001
        ), (
            "a partner-registry donor forgoes the 1.0-point domestic bonus, so the "
            "clinical score is 93.75 rather than 94.75"
        )

    strong = scored[strongly_served["id"]]
    assert float(strong["rank_score"]) == pytest.approx(90.563, abs=0.0001), (
        "0.55*93.75 + 0.25*100 + 0.20*min(70, 55+5*3) = 90.5625, which must round "
        f"half up to 90.563, got {strong['rank_score']}"
    )
    assert strong["rank_position"] == 1
    assert strong["candidate_role"] == "PRIMARY"

    weak = scored[weakly_served["id"]]
    assert float(weak["rank_score"]) == pytest.approx(88.563, abs=0.0001), (
        "0.55*93.75 + 0.25*100 + 0.20*min(70, 55+5*1) = 88.5625, which must round "
        f"half up to 88.563, got {weak['rank_score']}"
    )
    assert weak["rank_position"] == 2
    assert weak["candidate_role"] == "BACKUP"


def test_coordination_fee_is_charged_on_the_post_discount_base(api, operations_headers):
    """PRD §3.9: "The `COURIER` line starts from a base of 265,000 cents, and when the billing registry has `is_domestic` false that base is increased by a thirty-five per cent international surcharge — the base multiplied by one plus 0.35, rounded half up to whole cents — while a domestic registry pays the base unchanged."
    PRD §3.9: "The `subtotal_usd_cents` is the exact integer sum of those seven already-rounded lines."
    PRD §3.9: "From the subtotal alone — never from the total, never from any individual line — a `volume_discount_pct` is selected: a subtotal of at least 4,000,000 cents earns 0.09, otherwise a subtotal of at least 2,500,000 cents earns 0.05, and anything below that earns nothing."
    PRD §3.9: "The `discount_usd_cents` is the subtotal multiplied by that rate, rounded half up to whole cents."
    PRD §3.9: "The `intl_coordination_fee_usd_cents` applies only when the billing registry has `is_domestic` false, in which case it is the subtotal less the discount, multiplied by 0.08, that is eight per cent, rounded half up to whole cents; for a domestic registry it is zero."
    PRD §3.9: "The `total_usd_cents` is then the subtotal less the discount plus the coordination fee."
    PRD §3.9: "Finally, `billed_amount_local_cents` converts that total into the registry's own currency: the total divided by `fx_rate_snapshot`, rounded half up to a whole local cent."

    Design: Difficulty/combinatorial_formula/reimbursement_total_requires_pinned_discount_then_fee_order_mode_c
    """
    ctx = fixtures.setup_pipeline(
        "delivered",
        method="MARROW",
        registry_overrides=INTL_REGISTRY,
        donor_overrides=D2_DONOR,
        search_overrides=INTL_SCOPE,
    )
    fixtures.drive_conditioning(ctx, "INFUSE")

    claim = validate_success(
        api.finalize_reimbursement_claim(ctx["claim_id"], operations_headers)
    )
    A.assert_reimbursement_claim(claim)
    A.assert_claim_arithmetic(claim)
    assert [
        (line["line_type"], line["amount_usd_cents"]) for line in claim["line_items"]
    ] == [
        ("CT_TYPING", 34500),
        ("WORKUP_PHYSICAL", 78000),
        ("IDM_PANEL", 52500),
        ("COLLECTION", 1980000),
        ("COURIER", 357750),
        ("DONOR_LOST_WAGE", 256000),
        ("CANCELLATION", 0),
    ], f"unexpected line amounts: {claim['line_items']}"
    assert A.claim_line(claim, "COURIER") == 357750, (
        "the 35 per cent international surcharge is applied to the courier line "
        "itself, before the sum: round_half_up(265000 * 1.35)"
    )
    assert claim["subtotal_usd_cents"] == 2758750
    assert float(claim["volume_discount_pct"]) == 0.05, (
        "the tier is keyed on the 2758750-cent subtotal alone, not on the "
        "fee-inclusive total"
    )
    assert claim["discount_usd_cents"] == 137938, (
        "0.05 * 2758750 = 137937.5, which must round half up to 137938, got "
        f"{claim['discount_usd_cents']}"
    )
    assert claim["intl_coordination_fee_usd_cents"] == 209665, (
        "the fee is 0.08 * (2758750 - 137938) = 209664.96 rounded half up, NOT "
        f"0.08 * 2758750 = 220700, got {claim['intl_coordination_fee_usd_cents']}"
    )
    assert claim["total_usd_cents"] == 2830477
    assert float(claim["fx_rate_snapshot"]) == pytest.approx(1.0850, abs=0.00001)
    assert claim["billed_amount_local_cents"] == 2608735, (
        "2830477 / 1.0850 rounded half up to a whole local cent, got "
        f"{claim['billed_amount_local_cents']}"
    )
    assert claim["cancellation_fee_applied"] is False


def test_provisional_total_below_the_discount_tier_still_carries_the_fee(api):
    """PRD §3.9: "From the subtotal alone — never from the total, never from any individual line — a `volume_discount_pct` is selected: a subtotal of at least 4,000,000 cents earns 0.09, otherwise a subtotal of at least 2,500,000 cents earns 0.05, and anything below that earns nothing."
    PRD §3.9: "The `intl_coordination_fee_usd_cents` applies only when the billing registry has `is_domestic` false, in which case it is the subtotal less the discount, multiplied by 0.08, that is eight per cent, rounded half up to whole cents; for a domestic registry it is zero."
    PRD §3.9: "The `total_usd_cents` is then the subtotal less the discount plus the coordination fee."
    PRD §3.9: "Its `currency_code` is copied from that registry's `currency_code`, and its `fx_rate_snapshot` captures that registry's `fx_rate_to_usd` at the moment the current numbers were computed."
    PRD §3.6: "A provisional reimbursement claim is created in the same breath, raising the patient's `committed_cost_cents` by its total."

    Design: Difficulty/combinatorial_formula/reimbursement_total_requires_pinned_discount_then_fee_order_mode_c
    """
    ctx = fixtures.setup_pipeline(
        "workup_open",
        registry_overrides=INTL_REGISTRY,
        donor_overrides=D2_DONOR,
        search_overrides=INTL_SCOPE,
    )

    claim = fixtures.read_claim(ctx["claim_id"])
    A.assert_reimbursement_claim(claim)
    A.assert_claim_arithmetic(claim)
    assert claim["variant_applied"] == "PROVISIONAL"
    assert claim["currency_code"] == "EUR"
    assert A.claim_line(claim, "COURIER") == 357750
    assert A.claim_line(claim, "COLLECTION") == 1450000
    assert A.claim_line(claim, "DONOR_LOST_WAGE") == 192000
    assert claim["subtotal_usd_cents"] == 2164750
    assert float(claim["volume_discount_pct"]) == 0.0, (
        "a 2164750-cent subtotal sits below the 2500000-cent tier and earns nothing"
    )
    assert claim["discount_usd_cents"] == 0
    assert claim["intl_coordination_fee_usd_cents"] == 173180, (
        "with no discount the fee base is the bare subtotal: 0.08 * 2164750, got "
        f"{claim['intl_coordination_fee_usd_cents']}"
    )
    assert claim["total_usd_cents"] == 2337930
    assert claim["billed_amount_local_cents"] == 2154774
    assert fixtures.read_patient(ctx["patient_id"])["committed_cost_cents"] == 2337930


def test_ct_typing_line_bills_both_attempts_of_a_twice_typed_candidate(api):
    """PRD §3.9: "The `CT_TYPING` line is 34,500 cents — three hundred and forty-five dollars — for every confirmatory-typing attempt the candidate consumed, so it is 34,500 multiplied by the candidate's `ct_attempt_count`; a candidate typed twice therefore bills two attempts."
    PRD §3.4: "When the donor's registry has `is_domestic` false, a further 48 hours of grace — two full days — are added, in recognition of the time zones and translation involved in international coordination."
    PRD §3.4: "An expiring request moves `REQUESTED → EXPIRED`, has `expired_by_sweep_at` stamped with the sweep instant, and drags its candidate `TYPING_REQUESTED → TYPING_EXPIRED`."
    PRD §3.4: "A successful request raises the candidate's `ct_attempt_count` by one and moves the candidate `IDENTIFIED → TYPING_REQUESTED`, or `TYPING_EXPIRED → TYPING_REQUESTED` on the second attempt, which is exactly why the candidate's history is cyclic: `TYPING_REQUESTED → TYPING_EXPIRED → TYPING_REQUESTED`, bounded to two attempts in total."
    PRD §3.9: "The `subtotal_usd_cents` is the exact integer sum of those seven already-rounded lines."
    PRD §3.9: "The `intl_coordination_fee_usd_cents` applies only when the billing registry has `is_domestic` false, in which case it is the subtotal less the discount, multiplied by 0.08, that is eight per cent, rounded half up to whole cents; for a domestic registry it is zero."
    PRD §3.9: "Finally, `billed_amount_local_cents` converts that total into the registry's own currency: the total divided by `fx_rate_snapshot`, rounded half up to a whole local cent."

    Design: Difficulty/combinatorial_formula/reimbursement_total_requires_pinned_discount_then_fee_order_mode_c
    """
    ctx = fixtures.setup_primary_candidate(
        registry_overrides=INTL_REGISTRY,
        donor_overrides=D2_DONOR,
        search_overrides=INTL_SCOPE,
    )
    fixtures.advance_to_typing_requested(ctx)

    # 168 contractual hours plus 48 hours of partner grace put the deadline at
    # 2026-08-10T00:00:00Z, so one second later the sweep expires the attempt.
    fixtures.set_clock("2026-08-10T00:00:01Z")
    fixtures.sweep(ctx)
    candidate = fixtures.read_candidate(ctx["candidate_id"])
    assert candidate["status"] == "TYPING_EXPIRED"
    assert candidate["ct_attempt_count"] == 1
    assert candidate["candidate_role"] == "PRIMARY"

    second = fixtures.advance_to_typing_requested(ctx)
    assert second["attempt_number"] == 2
    assert fixtures.read_candidate(ctx["candidate_id"])["ct_attempt_count"] == 2

    fixtures.advance_to_typing_responded(ctx)
    fixtures.advance_to_screening_passed(ctx)
    fixtures.advance_to_workup_open(ctx)

    claim = fixtures.read_claim(ctx["claim_id"])
    A.assert_claim_arithmetic(claim)
    assert A.claim_line(claim, "CT_TYPING") == 69000, (
        "two consumed attempts must bill 34500 twice, got "
        f"{A.claim_line(claim, 'CT_TYPING')}"
    )
    assert claim["subtotal_usd_cents"] == 2199250
    assert float(claim["volume_discount_pct"]) == 0.0
    assert claim["discount_usd_cents"] == 0
    assert claim["intl_coordination_fee_usd_cents"] == 175940, (
        "0.08 * 2199250, got " f"{claim['intl_coordination_fee_usd_cents']}"
    )
    assert claim["total_usd_cents"] == 2375190
    assert claim["billed_amount_local_cents"] == 2189115, (
        "2375190 / 1.0850 rounded half up, got "
        f"{claim['billed_amount_local_cents']}"
    )
