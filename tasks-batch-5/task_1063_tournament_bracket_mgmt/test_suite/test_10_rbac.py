"""Role-based access control: Director-exclusive and Referee/Director-only ops.

Queue B: player_cannot_create_tournament, player_cannot_confirm_match.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    create_tournament_payload, confirm_match_payload,
    make_player_headers, make_referee_headers,
)
from test_helpers import fixtures as F


def test_player_cannot_create_tournament(api):
    """PRD §4: POST /tournaments is authorized for Director only. PRD §2.1: "When
    the headers are valid but the role is not permitted to perform the requested
    operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/player_cannot_create_tournament
    """
    venue = F.create_venue()
    player = F.create_player()
    resp = api.create_tournament(
        create_tournament_payload(venue["id"], name="X", format="SINGLE_ELIM",
                                  max_participants=4, prize_pool_cents=0, paid_places=1),
        make_player_headers(player["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_player_cannot_confirm_match(api):
    """PRD §4: POST /matches/{id}/confirm is authorized for Referee, Director. PRD
    §2.1: "the request is rejected with ERR_UNAUTHORIZED (HTTP 403)" when the role
    is not permitted.

    Design: Corner/rbac/player_cannot_confirm_match
    """
    ctx = F.build_two_player_single_elim()
    F.schedule(ctx["m_id"], ctx["st_id"], window="a")
    reported = F.report_winner(ctx["m_id"], ctx["r1"], make_referee_headers("ref-rep"))
    resp = api.confirm_match(ctx["m_id"], confirm_match_payload(reported["version"]),
                             make_player_headers(ctx["p1"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert F.get_match(ctx["m_id"])["status"] == "REPORTED"
