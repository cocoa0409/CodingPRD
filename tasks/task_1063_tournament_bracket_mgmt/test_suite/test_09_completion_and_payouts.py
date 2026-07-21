"""Completion cascade: final placements, provisional->final payout remapping,
pinned rounding order, tax withholding, and the money-conservation invariant.

Queue A: complete_tournament_placement_payout_tax_chain,
payout_provisional_vs_final_registration_mapping,
payout_rounding_order_remainder_to_first, money_conservation_payout_void.
Queue B: complete_with_incomplete_matches_rejected.
"""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId,
    api_client, complete_tournament_payload, assert_money_conservation,
    TEST_USERS,
)
from test_helpers import fixtures as F

DIRECTOR = TEST_USERS["director_headers"]


def _ready_to_complete(winner_key, prize, paid, p1_tax=False, p2_tax=False):
    """2-player SINGLE_ELIM with the final CONFIRMED (winner_key wins). Not yet
    completed; PROVISIONAL payouts already exist from bracket generation."""
    ctx = F.build_two_player_single_elim(
        prize_pool_cents=prize, paid_places=paid, p1_tax=p1_tax, p2_tax=p2_tax)
    F.play_final_confirmed(ctx, ctx[winner_key])
    return ctx


def _complete(t_id):
    t = F.get_tournament(t_id)
    return get_success_data(api_client.complete_tournament(
        t_id, complete_tournament_payload(t["version"]), DIRECTOR))


def _by_placement(t_id, variant):
    return {p["placement"]: p for p in F.list_payouts(t_id, variant=variant)}


# --------------------------------------------------------------------------
# Queue A — complete -> placement -> payout -> tax cascade (P1 no tax beats P2)
# --------------------------------------------------------------------------
def test_complete_sets_champion_and_placements(api):
    """PRD §3.8: "The unique first-place finisher is moved CHECKED_IN → CHAMPION
    and has its final_placement set to 1." Placements are dense 1..checked_in_count.

    Design: Difficulty/transitive_cascade/complete_tournament_placement_payout_tax_chain
    """
    ctx = _ready_to_complete("r1", prize=100000, paid=2, p1_tax=False, p2_tax=True)
    _complete(ctx["t_id"])
    r1 = F.get_registration(ctx["r1"])
    r2 = F.get_registration(ctx["r2"])
    assert r1["status"] == "CHAMPION" and r1["final_placement"] == 1, r1
    assert r2["final_placement"] == 2, r2


def test_final_payout_gross_tax_net_amounts(api):
    """PRD §3.8: "when that player's tax_id_provided is true the rate is 0 percent,
    and when it is false the rate is 24 percent (backup withholding). For each
    payout, tax_withheld_cents is gross_amount_cents multiplied by the applicable
    rate ... and net_amount_cents is gross_amount_cents minus tax_withheld_cents."

    Design: Difficulty/transitive_cascade/complete_tournament_placement_payout_tax_chain
    """
    ctx = _ready_to_complete("r1", prize=100000, paid=2, p1_tax=False, p2_tax=True)
    _complete(ctx["t_id"])
    finals = _by_placement(ctx["t_id"], "FINAL")
    champ = finals[1]
    runner = finals[2]
    assert champ["registration_id"] == ctx["r1"]
    assert champ["gross_amount_cents"] == 70000
    assert champ["tax_withheld_cents"] == 16800  # 24% backup withholding, no tax id
    assert champ["net_amount_cents"] == 53200
    assert runner["registration_id"] == ctx["r2"]
    assert runner["gross_amount_cents"] == 30000
    assert runner["tax_withheld_cents"] == 0  # tax_id_provided true
    assert runner["net_amount_cents"] == 30000


# --------------------------------------------------------------------------
# Queue A — provisional (seed projection) vs final (actual placement) mapping
# --------------------------------------------------------------------------
def test_provisional_maps_placement_one_to_seed_one(api):
    """PRD §3.8: "The provisional run happens at bracket generation ... each
    placement is projected onto the registration whose seed equals that placement
    (seed 1 is projected first place, and so on)".

    Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_registration_mapping
    """
    # P2 (seed 2) upsets P1 (seed 1) in the final.
    ctx = _ready_to_complete("r2", prize=100000, paid=2)
    provisional = _by_placement(ctx["t_id"], "PROVISIONAL")
    assert provisional[1]["registration_id"] == ctx["r1"]  # seed-1 projection
    _complete(ctx["t_id"])
    finals = _by_placement(ctx["t_id"], "FINAL")
    assert finals[1]["registration_id"] == ctx["r2"]  # actual champion


def test_final_supersedes_provisional_after_upset(api):
    """PRD §3.8: "At completion the system voids all provisional payouts ... runs
    the final allocation to create the FINAL rows, sets payout_variant to FINAL".

    Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_registration_mapping
    """
    ctx = _ready_to_complete("r2", prize=100000, paid=2)
    _complete(ctx["t_id"])
    provisional = F.list_payouts(ctx["t_id"], variant="PROVISIONAL")
    assert provisional and all(p["status"] == "VOID" for p in provisional), provisional
    finals = _by_placement(ctx["t_id"], "FINAL")
    assert finals[1]["gross_amount_cents"] == 70000
    assert F.get_tournament(ctx["t_id"])["payout_variant"] == "FINAL"


# --------------------------------------------------------------------------
# Queue A — pinned rounding order pushes remainder to first place
# --------------------------------------------------------------------------
def test_payout_rounding_remainder_pushed_to_first(api):
    """PRD §3.8: "for each rewarded placement in turn, its gross is prize_pool_cents
    multiplied by that placement's percentage and rounded half up to whole cents,
    computed independently ... the leftover remainder ... is added onto first
    place's gross, so first place absorbs the rounding remainder."

    Design: Difficulty/combinatorial_formula/payout_rounding_order_remainder_to_first
    """
    # 333 cents, [.50,.30,.20] -> [167,100,67] sums 334; -1 remainder to place 1.
    ctx = _ready_to_complete("r1", prize=333, paid=3, p1_tax=True, p2_tax=True)
    _complete(ctx["t_id"])
    finals = _by_placement(ctx["t_id"], "FINAL")
    assert finals[1]["gross_amount_cents"] == 166
    assert finals[2]["gross_amount_cents"] == 100
    assert finals[3]["gross_amount_cents"] == 67


def test_payout_grosses_sum_to_prize_pool(api):
    """PRD §2.8: "the sum of gross_amount_cents across every Payout whose status is
    not VOID, plus the tournament's unallocated_prize_cents, always equals the
    tournament's prize_pool_cents."

    Design: Difficulty/combinatorial_formula/payout_rounding_order_remainder_to_first
    """
    ctx = _ready_to_complete("r1", prize=333, paid=3, p1_tax=True, p2_tax=True)
    _complete(ctx["t_id"])
    finals = F.list_payouts(ctx["t_id"], variant="FINAL")
    assert sum(p["gross_amount_cents"] for p in finals) == 333


# --------------------------------------------------------------------------
# Queue A — money conservation across the provisional->final void switch
# --------------------------------------------------------------------------
def test_money_conserved_after_completion(api):
    """PRD §2.8: "the sum of gross_amount_cents across every Payout whose status is
    not VOID, plus the tournament's unallocated_prize_cents, always equals the
    tournament's prize_pool_cents."

    Design: Difficulty/compensating_invariant/money_conservation_payout_void
    """
    ctx = _ready_to_complete("r1", prize=100000, paid=2, p1_tax=True, p2_tax=True)
    _complete(ctx["t_id"])
    t = F.get_tournament(ctx["t_id"])
    all_payouts = F.list_payouts(ctx["t_id"])
    non_void = sum(p["gross_amount_cents"] for p in all_payouts if p["status"] != "VOID")
    assert non_void == 100000, non_void
    assert t["unallocated_prize_cents"] == 0, t["unallocated_prize_cents"]
    assert_money_conservation(t, all_payouts)


def test_provisional_payouts_voided_at_completion(api):
    """PRD §2.8: "the switch from provisional to final payouts voids every
    provisional row (returning their gross to the pool) before any final row is
    created."

    Design: Difficulty/compensating_invariant/money_conservation_payout_void
    """
    ctx = _ready_to_complete("r1", prize=100000, paid=2, p1_tax=True, p2_tax=True)
    _complete(ctx["t_id"])
    provisional = F.list_payouts(ctx["t_id"], variant="PROVISIONAL")
    assert provisional and all(p["status"] == "VOID" for p in provisional), provisional


# --------------------------------------------------------------------------
# Queue B — complete blocked by a non-terminal match
# --------------------------------------------------------------------------
def test_complete_with_incomplete_match_rejected(api):
    """PRD §3.8: "requires that every match be terminal — that is, every match is
    CONFIRMED or VOIDED ... if any match is non-terminal the completion is rejected
    with ERR_MATCHES_INCOMPLETE (HTTP 409)."

    Design: Corner/validations/complete_with_incomplete_matches_rejected
    """
    ctx = F.build_two_player_single_elim()
    F.schedule(ctx["m_id"], ctx["st_id"], window="a")  # final SCHEDULED, not confirmed
    t = F.get_tournament(ctx["t_id"])
    resp = api.complete_tournament(ctx["t_id"], complete_tournament_payload(t["version"]), DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_MATCHES_INCOMPLETE.value, 409)
    assert F.get_tournament(ctx["t_id"])["status"] == "IN_PROGRESS"
