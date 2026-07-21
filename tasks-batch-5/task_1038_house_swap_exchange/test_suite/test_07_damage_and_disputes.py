"""Damage claims (provisional vs final payout, adjudication cascade) and disputes
(the review fork), plus their filing preconditions and terminal guards.
"""
from test_helpers import (
    validate_success, validate_error,
    create_damage_claim_payload,
    make_admin_headers,
    build_points_scenario, get_member,
    file_damage_claim, adjudicate_claim, open_dispute, review_dispute, resolve_dispute,
    make_member_headers,
)

ADMIN = make_admin_headers()


def _completed_scenario():
    """COMPLETED POINTS agreement; host PLUS -> coverage_limit_points 5000 at confirm.
    Guest settled 730, host settled 1270, both trust 52."""
    return build_points_scenario("completed", points_per_night=100, guest_tier="PLUS",
                                 host_tier="PLUS", confirm_as="guest", complete_as="guest")


# ── Difficulty 1b: provisional vs final payout diverge ───────────────────────
def test_damage_provisional_payout_from_claimed_amount(api):
    """PRD §3.7: "A tiered deductible rate is chosen by band: an amount of 500 points
    or less uses a rate of twenty percent, an amount over 500 up to and including 2000
    uses ten percent, and an amount above 2000 uses five percent. The deductible is
    the larger of the fixed floor of 50 points and the amount multiplied by that rate,
    rounded half up. The payout is then the amount capped at the agreement's
    `coverage_limit_points`, less the deductible, and never below zero".
    PRD §3.7: "The `provisional_payout` is computed at filing from the
    claimant-asserted `claimed_amount`."

    Design: Difficulty/dual_variant_calc/damage_payout_provisional_vs_final_diverge
    """
    sc = _completed_scenario()
    claim = file_damage_claim(sc["agreement"]["id"], sc["host"]["id"], 1200)
    # 1200 -> rate 0.10, deductible max(50, 120)=120, payout min(1200,5000)-120 = 1080.
    assert claim["provisional_payout"] == 1080


def test_damage_final_payout_diverges_from_provisional(api):
    """PRD §3.7: "the same formula run against it produces the `final_payout` and the
    `deductible_points` actually applied."
    PRD §3.7: "Both the provisional payout and the eventual final payout are computed
    by the same formula, differing only in their input amount."

    Design: Difficulty/dual_variant_calc/damage_payout_provisional_vs_final_diverge
    """
    sc = _completed_scenario()
    claim = file_damage_claim(sc["agreement"]["id"], sc["host"]["id"], 1200)
    settled = adjudicate_claim(claim["id"], "APPROVE", assessed_amount=1000)
    # 1000 -> rate 0.10, deductible max(50,100)=100, payout min(1000,5000)-100 = 900.
    assert settled["final_payout"] == 900
    assert settled["deductible_points"] == 100
    assert settled["provisional_payout"] != settled["final_payout"]


# ── Difficulty 2b: tiered-deductible final payout ────────────────────────────
def test_damage_final_payout_tiered_deductible(api):
    """PRD §3.7: "an amount over 500 up to and including 2000 uses ten percent ...
    The payout is then the amount capped at the agreement's `coverage_limit_points`,
    less the deductible, and never below zero".

    Design: Difficulty/combinatorial_formula/damage_final_payout_tiered_deductible_mode_a
    """
    sc = _completed_scenario()
    claim = file_damage_claim(sc["agreement"]["id"], sc["host"]["id"], 800)
    settled = adjudicate_claim(claim["id"], "APPROVE", assessed_amount=1000)
    assert settled["final_payout"] == 900


def test_damage_final_deductible_is_floor_or_rate(api):
    """PRD §3.7: "The deductible is the larger of the fixed floor of 50 points and the
    amount multiplied by that rate, rounded half up."

    Design: Difficulty/combinatorial_formula/damage_final_payout_tiered_deductible_mode_a
    """
    sc = _completed_scenario()
    claim = file_damage_claim(sc["agreement"]["id"], sc["host"]["id"], 800)
    settled = adjudicate_claim(claim["id"], "APPROVE", assessed_amount=1000)
    # 1000 * 0.10 = 100 > fixed floor 50, so deductible is 100.
    assert settled["deductible_points"] == 100


# ── Difficulty 4b: adjudicate cascade (settlement -> ledger -> trust) ─────────
def test_adjudicate_settles_claim_with_final_payout(api):
    """PRD §3.7: "An approval moves the claim `FILED → SETTLED`: the admin's
    `assessed_amount` is recorded, and the same formula run against it produces the
    `final_payout` and the `deductible_points` actually applied."

    Design: Difficulty/transitive_cascade/adjudicate_cascades_claim_settlement_ledger_trust
    """
    sc = _completed_scenario()
    claim = file_damage_claim(sc["agreement"]["id"], sc["host"]["id"], 1000)
    settled = adjudicate_claim(claim["id"], "APPROVE", assessed_amount=1000)
    assert settled["status"] == "SETTLED"
    assert settled["final_payout"] == 900


def test_adjudicate_transfers_points_and_penalizes_trust(api):
    """PRD §3.7: "The settlement then posts a `DAMAGE_SETTLEMENT` debit of the
    negative final payout against the respondent and a `DAMAGE_SETTLEMENT` credit of
    the equal positive amount to the claimant, recomputes both balances, increments
    the respondent's `upheld_damage_count` by one, and recomputes the respondent's
    `trust_score`."
    PRD §3.6: "A member's trust score is fifty, plus two for every completed exchange,
    minus ten for every upheld damage claim recorded against them, and minus fifteen
    for every dispute they have lost, with the result clamped to lie between 0 and 100
    inclusive."

    Design: Difficulty/transitive_cascade/adjudicate_cascades_claim_settlement_ledger_trust
    """
    sc = _completed_scenario()
    claim = file_damage_claim(sc["agreement"]["id"], sc["host"]["id"], 1000)
    adjudicate_claim(claim["id"], "APPROVE", assessed_amount=1000)
    guest = get_member(sc["guest"]["id"])   # respondent
    host = get_member(sc["host"]["id"])     # claimant
    assert guest["settled_points_balance"] == -170   # 730 - 900
    assert host["settled_points_balance"] == 2170     # 1270 + 900
    assert guest["upheld_damage_count"] == 1
    assert guest["trust_score"] == 42                 # 50 + 2*1 - 10*1


# ── Difficulty 3b: dispute review forks toward the claimant ──────────────────
def test_dispute_resolved_for_claimant_status(api):
    """PRD §3.8: "A resolution for the claimant moves it
    `UNDER_REVIEW → RESOLVED_FOR_CLAIMANT`".

    Design: Difficulty/non_linear_state_machine/dispute_review_forks_claimant_vs_respondent
    """
    sc = _completed_scenario()
    dispute = open_dispute(sc["agreement"]["id"], sc["host"]["id"], 100, reason="left place damaged")
    review_dispute(dispute["id"])
    resolved = resolve_dispute(dispute["id"], "FOR_CLAIMANT", resolution_note="damage confirmed")
    assert resolved["status"] == "RESOLVED_FOR_CLAIMANT"


def test_dispute_for_claimant_transfers_penalty_and_trust(api):
    """PRD §3.8: "it posts a `DISPUTE_PENALTY` debit of the negative `penalty_points`
    against the respondent and a `DISPUTE_PENALTY` credit of the equal positive amount
    to the claimant, recomputes both balances, increments the respondent's
    `disputes_lost_count` by one, recomputes the respondent's `trust_score`, and
    records the `resolution_note`."
    PRD §3.6: "A member's trust score is fifty, plus two for every completed exchange,
    minus ten for every upheld damage claim recorded against them, and minus fifteen
    for every dispute they have lost, with the result clamped to lie between 0 and 100
    inclusive."

    Design: Difficulty/non_linear_state_machine/dispute_review_forks_claimant_vs_respondent
    """
    sc = _completed_scenario()
    dispute = open_dispute(sc["agreement"]["id"], sc["host"]["id"], 100, reason="left place damaged")
    review_dispute(dispute["id"])
    resolve_dispute(dispute["id"], "FOR_CLAIMANT", resolution_note="damage confirmed")
    guest = get_member(sc["guest"]["id"])   # respondent
    host = get_member(sc["host"]["id"])     # claimant
    assert guest["settled_points_balance"] == 630   # 730 - 100
    assert host["settled_points_balance"] == 1370    # 1270 + 100
    assert guest["disputes_lost_count"] == 1
    assert guest["trust_score"] == 37               # 50 + 2*1 - 15*1


# ── Difficulty 7b: damage filing depends on agreement COMPLETED ──────────────
def test_damage_claim_on_confirmed_agreement_rejected(api):
    """PRD §3.7: "Filing is permitted only when the underlying agreement is in
    `COMPLETED` status and the claimant is a party to it, otherwise
    `ERR_AGREEMENT_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/damage_claim_requires_agreement_completed
    """
    sc = build_points_scenario("confirmed", points_per_night=100, guest_tier="PLUS",
                               host_tier="PLUS", confirm_as="host")
    res = api.create_damage_claim(
        sc["agreement"]["id"], create_damage_claim_payload(sc["host"]["id"], 500),
        make_member_headers(sc["host"]["id"]))
    validate_error(res, "ERR_AGREEMENT_NOT_COMPLETED")


def test_damage_claim_on_completed_agreement_accepted(api):
    """PRD §3.7: "Filing is permitted only when the underlying agreement is in
    `COMPLETED` status and the claimant is a party to it".
    PRD §3.7: "The claim opens in `FILED`."

    Design: Difficulty/cross_entity_state_dependency/damage_claim_requires_agreement_completed
    """
    sc = _completed_scenario()
    res = api.create_damage_claim(
        sc["agreement"]["id"], create_damage_claim_payload(sc["host"]["id"], 500),
        make_member_headers(sc["host"]["id"]))
    claim = validate_success(res, 201)
    assert claim["status"] == "FILED"


# ── Corner: filing amount and adjudication idempotency guards ────────────────
def test_damage_claim_zero_amount_returns_invalid_claim_amount(api):
    """PRD §3.7: "A claim is filed on an agreement by naming the `agreement_id`, the
    `claimant_member_id`, and a `claimed_amount` of at least 1; a `claimed_amount`
    below 1 is rejected with `ERR_INVALID_CLAIM_AMOUNT`."

    Design: Corner/validations/damage_claim_zero_amount_returns_invalid_claim_amount
    """
    sc = _completed_scenario()
    res = api.create_damage_claim(
        sc["agreement"]["id"], create_damage_claim_payload(sc["host"]["id"], 0),
        make_member_headers(sc["host"]["id"]))
    validate_error(res, "ERR_INVALID_CLAIM_AMOUNT")


def test_adjudicate_already_settled_claim_returns_already_adjudicated(api):
    """PRD §3.7: "Adjudicating a claim that is not `FILED` is rejected with
    `ERR_CLAIM_ALREADY_ADJUDICATED`."

    Design: Corner/state_machines/adjudicate_already_settled_claim_returns_already_adjudicated
    """
    sc = _completed_scenario()
    claim = file_damage_claim(sc["agreement"]["id"], sc["host"]["id"], 1000)
    adjudicate_claim(claim["id"], "APPROVE", assessed_amount=1000)   # -> SETTLED
    from test_helpers import adjudicate_payload
    res = api.adjudicate_damage_claim(claim["id"], adjudicate_payload("REJECT"), ADMIN)
    validate_error(res, "ERR_CLAIM_ALREADY_ADJUDICATED")
