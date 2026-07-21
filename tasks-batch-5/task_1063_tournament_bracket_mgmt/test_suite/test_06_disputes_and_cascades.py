"""Disputes: the report/dispute/reject cycle, the uphold/reject fork, the
compensation cascade that un-eliminates a competitor, and dispute-time SoD.

Queue A: match_report_dispute_reject_cycle, dispute_open_fork_uphold_vs_reject,
uphold_dispute_void_match_uneliminate_chain, participant_conservation_confirm_void.
Queue B: second_open_dispute_rejected, sod_confirmer_cannot_resolve_dispute.
"""
from test_helpers import (
    validate_error, ApiErrorId, get_success_data,
    resolve_dispute_payload, create_dispute_payload,
    assert_participant_conservation, TEST_USERS, make_referee_headers,
    make_player_headers,
)
from test_helpers import fixtures as F

REFEREE = TEST_USERS["referee_headers"]


def _reported_final_with_dispute(reporter_is_player=True):
    """2-player SINGLE_ELIM final REPORTED (P1 2-0), then P2 disputes -> DISPUTED."""
    ctx = F.build_two_player_single_elim()
    F.schedule(ctx["m_id"], ctx["st_id"], window="a")
    reporter = make_player_headers(ctx["p1"]) if reporter_is_player else make_referee_headers("ref-rep")
    F.report_winner(ctx["m_id"], ctx["r1"], reporter)
    dispute = F.raise_dispute(ctx["m_id"], ctx["r2"], ctx["p2"], reason="wrong score")
    ctx["d_id"] = dispute["id"]
    ctx["m_ver"] = F.get_match(ctx["m_id"])["version"]
    return ctx


def _confirmed_final_with_open_dispute(confirmer_user_id="ref-confirmer",
                                       p1_tax=False, p2_tax=False, prize=0, paid=1):
    """2-player SINGLE_ELIM final CONFIRMED (P1 wins, P2 eliminated), then P2 raises
    an OPEN dispute on the CONFIRMED match (match stays CONFIRMED)."""
    ctx = F.build_two_player_single_elim(prize_pool_cents=prize, paid_places=paid,
                                         p1_tax=p1_tax, p2_tax=p2_tax)
    F.play_final_confirmed(ctx, ctx["r1"], confirmer_user_id=confirmer_user_id)
    dispute = F.raise_dispute(ctx["m_id"], ctx["r2"], ctx["p2"], reason="review")
    ctx["d_id"] = dispute["id"]
    ctx["m_ver"] = F.get_match(ctx["m_id"])["version"]
    return ctx


# --------------------------------------------------------------------------
# Queue A — REPORTED -> DISPUTED -> REPORTED cycle (reject)
# --------------------------------------------------------------------------
def test_dispute_freezes_reported_match(api):
    """PRD §3.6: "When the disputed match is still REPORTED, raising the dispute
    freezes it, moving the match REPORTED → DISPUTED".

    Design: Difficulty/non_linear_state_machine/match_report_dispute_reject_cycle
    """
    ctx = _reported_final_with_dispute()
    assert F.get_match(ctx["m_id"])["status"] == "DISPUTED"


def test_reject_returns_match_to_reported(api):
    """PRD §3.6: "A REJECTED outcome moves the dispute OPEN → REJECTED and
    unfreezes the match, moving it DISPUTED → REPORTED so it may be confirmed
    again."

    Design: Difficulty/non_linear_state_machine/match_report_dispute_reject_cycle
    """
    ctx = _reported_final_with_dispute()
    resp = api.resolve_dispute(ctx["d_id"], resolve_dispute_payload(
        "REJECTED", ctx["m_ver"], resolution_note="score stands"),
        make_referee_headers("ref-9"))
    get_success_data(resp)
    assert F.get_match(ctx["m_id"])["status"] == "REPORTED"
    assert F.get_success_data(api.get_dispute(ctx["d_id"], REFEREE))["status"] == "REJECTED"


# --------------------------------------------------------------------------
# Queue A — OPEN fork: UPHELD voids a CONFIRMED match
# --------------------------------------------------------------------------
def test_uphold_voids_confirmed_match(api):
    """PRD §3.6: "An UPHELD outcome moves the dispute OPEN → UPHELD and voids the
    match ... If the match had already been CONFIRMED, it moves CONFIRMED → VOIDED".

    Design: Difficulty/non_linear_state_machine/dispute_open_fork_uphold_vs_reject
    """
    ctx = _confirmed_final_with_open_dispute()
    resp = api.resolve_dispute(ctx["d_id"], resolve_dispute_payload(
        "UPHELD", ctx["m_ver"], resolution_note="confirmed cheating"),
        make_referee_headers("ref-9"))
    get_success_data(resp)
    assert F.get_success_data(api.get_dispute(ctx["d_id"], REFEREE))["status"] == "UPHELD"
    assert F.get_match(ctx["m_id"])["status"] == "VOIDED"


def test_uphold_clears_winner_and_unelim_competitor(api):
    """PRD §3.6: "winner_registration_id, loser_registration_id, and both scores
    are cleared; ... the losing registration that had been eliminated is reverted
    ELIMINATED → CHECKED_IN".

    Design: Difficulty/non_linear_state_machine/dispute_open_fork_uphold_vs_reject
    """
    ctx = _confirmed_final_with_open_dispute()
    api.resolve_dispute(ctx["d_id"], resolve_dispute_payload(
        "UPHELD", ctx["m_ver"], resolution_note="void"), make_referee_headers("ref-9"))
    assert F.get_match(ctx["m_id"])["winner_registration_id"] is None
    assert F.get_registration(ctx["r2"])["status"] == "CHECKED_IN"


# --------------------------------------------------------------------------
# Queue A — transitive cascade: uphold -> void -> un-eliminate + counters
# --------------------------------------------------------------------------
def test_uphold_void_reverts_match_state(api):
    """PRD §3.6: "If the match had already been CONFIRMED, it moves CONFIRMED →
    VOIDED with a full compensation cascade ... winner_registration_id ... are
    cleared".

    Design: Difficulty/transitive_cascade/uphold_dispute_void_match_uneliminate_chain
    """
    ctx = _confirmed_final_with_open_dispute()
    api.resolve_dispute(ctx["d_id"], resolve_dispute_payload(
        "UPHELD", ctx["m_ver"], resolution_note="void it"), make_referee_headers("ref-9"))
    match = F.get_match(ctx["m_id"])
    assert match["status"] == "VOIDED"
    assert match["winner_registration_id"] is None


def test_uphold_void_uneliminates_and_updates_counters(api):
    """PRD §3.6: "the losing registration that had been eliminated is reverted
    ELIMINATED → CHECKED_IN with alive_count incremented and eliminated_count
    decremented".

    Design: Difficulty/transitive_cascade/uphold_dispute_void_match_uneliminate_chain
    """
    ctx = _confirmed_final_with_open_dispute()
    api.resolve_dispute(ctx["d_id"], resolve_dispute_payload(
        "UPHELD", ctx["m_ver"], resolution_note="void it"), make_referee_headers("ref-9"))
    reg = F.get_registration(ctx["r2"])
    assert reg["status"] == "CHECKED_IN"
    assert reg["eliminated"] is False
    t = F.get_tournament(ctx["t_id"])
    assert t["alive_count"] == 2 and t["eliminated_count"] == 0, t


# --------------------------------------------------------------------------
# Queue A — participant-conservation invariant across confirm+void
# --------------------------------------------------------------------------
def test_participant_conservation_after_confirm(api):
    """PRD §2.9: "Each confirm that eliminates a competitor moves exactly one
    registration from alive to eliminated (alive_count decreases by one,
    eliminated_count increases by one)".

    Design: Difficulty/compensating_invariant/participant_conservation_confirm_void
    """
    ctx = _confirmed_final_with_open_dispute()
    t = F.get_tournament(ctx["t_id"])
    assert t["alive_count"] == 1 and t["eliminated_count"] == 1, t
    assert_participant_conservation(t)


def test_participant_conservation_after_compensating_void(api):
    """PRD §2.9: "an upheld-dispute void of an eliminating match moves exactly one
    registration back the other way (alive_count increases by one, eliminated_count
    decreases by one)".

    Design: Difficulty/compensating_invariant/participant_conservation_confirm_void
    """
    ctx = _confirmed_final_with_open_dispute()
    api.resolve_dispute(ctx["d_id"], resolve_dispute_payload(
        "UPHELD", ctx["m_ver"], resolution_note="restore"), make_referee_headers("ref-9"))
    t = F.get_tournament(ctx["t_id"])
    assert t["alive_count"] == 2 and t["eliminated_count"] == 0, t
    assert_participant_conservation(t)
    assert F.get_registration(ctx["r2"])["eliminated"] is False


# --------------------------------------------------------------------------
# Queue B — at most one OPEN dispute; confirmer may not resolve (SoD)
# --------------------------------------------------------------------------
def test_second_open_dispute_rejected(api):
    """PRD §3.6: "at most one OPEN dispute may exist for a match at a time, so a
    second concurrent challenge is rejected with ERR_DISPUTE_ALREADY_OPEN (HTTP
    409)".

    Design: Corner/validations/second_open_dispute_rejected
    """
    # Use a CONFIRMED match: it stays CONFIRMED (disputable) with an OPEN dispute,
    # so the second challenge is unambiguously the already-open case.
    ctx = _confirmed_final_with_open_dispute()
    resp = api.create_dispute(create_dispute_payload(ctx["m_id"], ctx["r2"], "two"),
                              make_player_headers(ctx["p2"]))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN.value, 409)


def test_confirmer_cannot_resolve_own_dispute(api):
    """PRD §3.6: "the resolving X-User-ID must differ from the disputed match's
    confirmed_by_user_id ... otherwise it is rejected with
    ERR_SOD_CONFIRMER_RESOLVE (HTTP 409)".

    Design: Corner/rbac/sod_confirmer_cannot_resolve_dispute
    """
    ctx = _confirmed_final_with_open_dispute(confirmer_user_id="ref-3")
    resp = api.resolve_dispute(ctx["d_id"], resolve_dispute_payload(
        "REJECTED", ctx["m_ver"], resolution_note="x"), make_referee_headers("ref-3"))
    validate_error(resp, ApiErrorId.ERR_SOD_CONFIRMER_RESOLVE.value, 409)
    assert F.get_success_data(api.get_dispute(ctx["d_id"], REFEREE))["status"] == "OPEN"
