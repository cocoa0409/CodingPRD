"""Seeding assignment and tournament-lifecycle state guards.

Queue B: seeding_by_rating_descending, start_before_bracket_ready_invalid_state.
"""
from test_helpers import validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as F

DIRECTOR = TEST_USERS["director_headers"]


def test_seeding_by_rating_highest_gets_seed_one(api):
    """PRD §3.3: "Under RATING, candidates are ordered by the player's rating from
    highest to lowest ... Walking the resulting order, the first registration
    receives seed 1, the second seed 2, and so on."

    Design: Corner/calculations/seeding_by_rating_descending
    """
    venue = F.create_venue()
    p_hi = F.create_player(rating=1600, display_name="Hi")
    p_lo = F.create_player(rating=900, display_name="Lo")
    t = F.create_tournament(venue["id"], format="SINGLE_ELIM", max_participants=4,
                            prize_pool_cents=0, paid_places=1, seeding_method="RATING")
    F.open_registration(t["id"])
    r_hi = F.register(t["id"], p_hi["id"])
    r_lo = F.register(t["id"], p_lo["id"])
    F.close_registration(t["id"])
    F.check_in(r_hi["id"], p_hi["id"])
    F.check_in(r_lo["id"], p_lo["id"])
    F.generate_bracket(t["id"])
    assert F.get_registration(r_hi["id"])["seed"] == 1
    assert F.get_registration(r_lo["id"])["seed"] == 2


def test_start_before_bracket_ready_invalid_state(api):
    """PRD §3.3: "A Director starts the tournament, moving BRACKET_READY →
    IN_PROGRESS". PRD §2.11: state precondition failures return ERR_INVALID_STATE.

    Design: Corner/state_machines/start_before_bracket_ready_invalid_state
    """
    venue = F.create_venue()
    t = F.create_tournament(venue["id"], format="SINGLE_ELIM", max_participants=4,
                            prize_pool_cents=0, paid_places=1)
    resp = api.start_tournament(t["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert F.get_tournament(t["id"])["status"] == "DRAFT"
