"""State-machine precondition and invalid-transition claims across Game,
CrewSlot, Assignment, League and PenaltyAppeal, plus the two cross-entity
state-dependency difficulty instances.

Each test translates exactly one design instance (Difficulty queue A or Corner queue B).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_league_payload, create_game_payload, create_crew_slot_payload,
    create_evaluation_payload, create_appeal_payload,
    TEST_USERS, make_official_headers,
    setup_open_game_with_slot, setup_offered_assignment, setup_accepted_assignment,
    setup_locked_game, setup_declined_with_appeal,
    offer_slot, accept_assignment, current_game_version,
    set_clock,
)

ADMIN = TEST_USERS["league_admin_headers"]
ASSIGNOR = TEST_USERS["assignor_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]


# ─── Cross-entity state dependency (Difficulty) ──────────────────────────────

def test_open_game_requires_league_open(api):
    """PRD §3.3: "This is only permitted when the game is in `DRAFT` (otherwise
    `ERR_INVALID_STATE`), when its league is `OPEN` (otherwise
    `ERR_LEAGUE_NOT_OPEN`), and when the number of crew slots provisioned exactly
    equals `required_crew_size` (otherwise `ERR_CREW_NOT_PROVISIONED`)."

    Design: Difficulty/cross_entity_state_dependency/game_open_requires_league_open
    """
    league = validate_success(api.create_league(create_league_payload(sport="SOCCER"), ADMIN), 201)
    # League left in SETUP (not activated).
    game = validate_success(api.create_game(create_game_payload(league["id"]), ASSIGNOR), 201)
    validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    res = api.open_game(game["id"], ASSIGNOR)
    validate_error(res, "ERR_LEAGUE_NOT_OPEN", expected_status=409)


def test_open_game_requires_league_open_variant_repeat(api):
    """PRD §3.3: "This is only permitted when the game is in `DRAFT` (otherwise
    `ERR_INVALID_STATE`), when its league is `OPEN` (otherwise
    `ERR_LEAGUE_NOT_OPEN`), and when the number of crew slots provisioned exactly
    equals `required_crew_size` (otherwise `ERR_CREW_NOT_PROVISIONED`)."

    Design: Difficulty/cross_entity_state_dependency/game_open_requires_league_open
    """
    league = validate_success(api.create_league(create_league_payload(sport="BASKETBALL"), ADMIN), 201)
    game = validate_success(api.create_game(
        create_game_payload(league["id"], required_crew_size=2), ASSIGNOR), 201)
    validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="OBSERVER"), ASSIGNOR), 201)
    res = api.open_game(game["id"], ASSIGNOR)
    validate_error(res, "ERR_LEAGUE_NOT_OPEN", expected_status=409)


def test_evaluation_requires_assignment_completed(api):
    """PRD §3.11: "An evaluation may target only a `COMPLETED` assignment, and only
    one evaluation may exist per assignment; rating a non-completed assignment or
    adding a second evaluation to one already rated is rejected with
    `ERR_ASSIGNMENT_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/evaluation_requires_assignment_completed
    """
    ctx = setup_accepted_assignment()  # assignment ACCEPTED, not COMPLETED
    res = api.create_evaluation(ctx["assignment"]["id"], create_evaluation_payload(4.0), EVALUATOR)
    validate_error(res, "ERR_ASSIGNMENT_NOT_COMPLETED", expected_status=409)


def test_evaluation_on_offered_assignment_rejected(api):
    """PRD §3.11: "An evaluation may target only a `COMPLETED` assignment, and only
    one evaluation may exist per assignment; rating a non-completed assignment or
    adding a second evaluation to one already rated is rejected with
    `ERR_ASSIGNMENT_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/evaluation_requires_assignment_completed
    """
    ctx = setup_offered_assignment()  # assignment OFFERED, not COMPLETED
    res = api.create_evaluation(ctx["assignment"]["id"], create_evaluation_payload(3.0), EVALUATOR)
    validate_error(res, "ERR_ASSIGNMENT_NOT_COMPLETED", expected_status=409)


# ─── Game state-machine precondition / invalid-transition claims (Corner) ────

def test_open_already_open_game_returns_invalid_state(api):
    """PRD §3.3: "Opening a game advances it from `DRAFT` to `OPEN`. This is only
    permitted when the game is in `DRAFT` (otherwise `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/open_already_open_game_returns_invalid_state
    """
    ctx = setup_open_game_with_slot()
    res = api.open_game(ctx["game"]["id"], ASSIGNOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_open_game_without_provisioned_crew(api):
    """PRD §3.3: "when the number of crew slots provisioned exactly equals
    `required_crew_size` (otherwise `ERR_CREW_NOT_PROVISIONED`)."

    Design: Corner/state_machines/open_game_without_provisioned_crew_returns_crew_not_provisioned
    """
    league = validate_success(api.create_league(create_league_payload(sport="SOCCER"), ADMIN), 201)
    league = validate_success(api.activate_league(league["id"], ADMIN), 200)
    game = validate_success(api.create_game(create_game_payload(league["id"]), ASSIGNOR), 201)
    res = api.open_game(game["id"], ASSIGNOR)  # no slots provisioned
    validate_error(res, "ERR_CREW_NOT_PROVISIONED", expected_status=409)


def test_lock_game_not_staffed_returns_invalid_state(api):
    """PRD §3.9: "When a crew is complete, an `Assignor` locks the game, a
    `STAFFED → LOCKED` move that is permitted only when the game is in `STAFFED`
    (else `ERR_INVALID_STATE`) and its `crew_filled_count` equals
    `required_crew_size` (else `ERR_CREW_INCOMPLETE`)."

    Design: Corner/state_machines/lock_game_with_incomplete_crew_returns_crew_incomplete
    """
    # 2-slot game, only one filled => game stays OPEN (not STAFFED).
    league = validate_success(api.create_league(create_league_payload(sport="SOCCER"), ADMIN), 201)
    league = validate_success(api.activate_league(league["id"], ADMIN), 200)
    official = validate_success(api.create_official(
        {"league_id": league["id"], "full_name": "A", "home_lat": 40.0, "home_lon": -75.0},
        ADMIN), 201)
    validate_success(api.create_availability(
        {"official_id": official["id"], "window_start_utc": "2026-01-01T00:00:00Z",
         "window_end_utc": "2027-01-01T00:00:00Z"},
        make_official_headers(official["id"])), 201)
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(
        create_game_payload(league["id"], required_crew_size=2), ASSIGNOR), 201)
    s1 = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    asg = offer_slot(s1["id"], official["id"], game["id"])
    accept_assignment(asg["id"], official["id"], game["id"])
    gv = current_game_version(game["id"])
    res = api.lock_game(game["id"], {"expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    fetched = validate_success(api.get_game(game["id"], ASSIGNOR), 200)
    assert fetched["status"] == "OPEN"


def test_settle_before_game_start_returns_game_not_started(api):
    """PRD §3.9: "Settling a game is the season's payday. It is defined only from
    `LOCKED` (else `ERR_INVALID_STATE`) and only once the game has started — its
    `start_utc` must be at or before the current clock (else
    `ERR_GAME_NOT_STARTED`)."

    Design: Corner/state_machines/settle_before_game_start_returns_game_not_started
    """
    ctx = setup_locked_game()  # clock pinned 2026-06-01, game starts 2026-06-20
    gv = current_game_version(ctx["game"]["id"])
    res = api.settle_game(ctx["game"]["id"], {"expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_GAME_NOT_STARTED", expected_status=409)


def test_terminal_cancelled_game_no_transitions(api):
    """PRD §3.10: "An `Assignor` may cancel a game from any of `DRAFT`, `OPEN`,
    `STAFFED`, or `LOCKED`; attempting cancellation from a terminal state is
    rejected with `ERR_INVALID_STATE`."
    PRD §3.3: "Opening a game advances it from `DRAFT` to `OPEN`. This is only
    permitted when the game is in `DRAFT` (otherwise `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/terminal_game_cancelled_no_transitions
    """
    league = validate_success(api.create_league(create_league_payload(), ADMIN), 201)
    league = validate_success(api.activate_league(league["id"], ADMIN), 200)
    game = validate_success(api.create_game(create_game_payload(league["id"]), ASSIGNOR), 201)
    validate_success(api.cancel_game(game["id"], ASSIGNOR), 200)
    res = api.open_game(game["id"], ASSIGNOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_offer_already_offered_slot_returns_slot_not_vacant(api):
    """PRD §3.4: "The offer is defined only from a slot in `VACANT` (otherwise
    `ERR_SLOT_NOT_VACANT`) on a game whose `status` is `OPEN` (otherwise
    `ERR_GAME_NOT_OPEN`)."

    Design: Corner/state_machines/offer_already_offered_slot_returns_slot_not_vacant
    """
    ctx = setup_offered_assignment()  # slot already OFFERED to the official
    # A second offer (to any official) on the already-OFFERED slot.
    other = validate_success(api.create_official(
        {"league_id": ctx["league"]["id"], "full_name": "B", "home_lat": 40.0, "home_lon": -75.0},
        ADMIN), 201)
    validate_success(api.create_availability(
        {"official_id": other["id"], "window_start_utc": "2026-01-01T00:00:00Z",
         "window_end_utc": "2027-01-01T00:00:00Z"},
        make_official_headers(other["id"])), 201)
    gv = current_game_version(ctx["game"]["id"])
    res = api.offer_crew_slot(
        ctx["slot"]["id"], {"official_id": other["id"], "expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_SLOT_NOT_VACANT", expected_status=409)


def test_noshow_before_game_start_returns_game_not_started(api):
    """PRD §3.7: "Recording a no-show is defined only from an `ACCEPTED` assignment
    (else `ERR_INVALID_STATE`), requires the game to be in `STAFFED` or `LOCKED`
    (else `ERR_INVALID_STATE`), and requires the game to have actually started —
    its `start_utc` must be at or before the current clock (else
    `ERR_GAME_NOT_STARTED`)."

    Design: Corner/state_machines/noshow_before_game_start_returns_game_not_started
    """
    ctx = setup_accepted_assignment()  # game STAFFED, clock 2026-06-01 before start
    res = api.no_show_assignment(ctx["assignment"]["id"], ASSIGNOR)
    validate_error(res, "ERR_GAME_NOT_STARTED", expected_status=409)


def test_withdraw_after_lock_returns_game_locked(api):
    """PRD §3.6: "An official may also withdraw from an assignment they have already
    accepted, provided the game has not yet been locked. Withdrawal is defined only
    from `ACCEPTED`, requires ownership (`ERR_NOT_ASSIGNMENT_OWNER`), and is
    permitted only while the game is `OPEN` or `STAFFED`; attempting it once the
    game is `LOCKED` is rejected with `ERR_GAME_LOCKED`."

    Design: Corner/state_machines/withdraw_after_lock_returns_game_locked
    """
    ctx = setup_locked_game(position="ASSISTANT", official_overrides={})  # ROOKIE ok for ASSISTANT
    res = api.withdraw_assignment(
        ctx["assignment"]["id"], make_official_headers(ctx["official"]["id"]))
    validate_error(res, "ERR_GAME_LOCKED", expected_status=409)


# ─── PenaltyAppeal state-machine claims (Corner) ─────────────────────────────

def test_appeal_denied_branch_leaves_penalty_unchanged(api):
    """PRD §3.13: "Denying an appeal is the divergent branch. It is defined only
    from `PENDING`, leaves `reversed_points` at 0, advances the appeal
    `PENDING → DENIED`, and makes no change to any ledger — the explicit contrast
    with the upheld branch, which alone reverses points."

    Design: Corner/state_machines/appeal_denied_branch_leaves_penalty_unchanged
    """
    from test_helpers import get_season_ledger
    ctx = setup_declined_with_appeal(reason="weather")
    assert ctx["assignment"]["penalty_assessed_points"] == 8
    appeal = validate_success(api.deny_appeal(ctx["appeal"]["id"], ADMIN), 200)
    assert appeal["status"] == "DENIED"
    assert appeal["reversed_points"] == 0
    ledger = get_season_ledger(ctx["league"]["id"], ctx["official"]["id"])
    assert ledger["penalty_points"] == 8


def test_uphold_already_upheld_appeal_returns_invalid_state(api):
    """PRD §3.13: "A `LeagueAdmin` adjudicates. Upholding an appeal is defined only
    from `PENDING`, and additionally requires that the appealed assignment is still
    in `DECLINED` or `NO_SHOW` (else `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/uphold_already_upheld_appeal_returns_invalid_state
    """
    ctx = setup_declined_with_appeal(reason="x")
    validate_success(api.uphold_appeal(ctx["appeal"]["id"], ADMIN), 200)
    res = api.uphold_appeal(ctx["appeal"]["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_appeal_non_penalized_assignment_returns_not_appealable(api):
    """PRD §3.13: "An appeal may be filed only against an assignment in `DECLINED`
    or `NO_SHOW` whose `penalty_assessed_points` is greater than 0, and at most one
    appeal that is `PENDING` or `UPHELD` may exist per assignment; an attempt that
    violates either condition is rejected with `ERR_NOT_APPEALABLE`."

    Design: Corner/state_machines/appeal_non_penalized_assignment_returns_not_appealable
    """
    ctx = setup_accepted_assignment()  # ACCEPTED assignment, no penalty
    res = api.create_appeal(
        ctx["assignment"]["id"], create_appeal_payload(reason="nope"),
        make_official_headers(ctx["official"]["id"]))
    validate_error(res, "ERR_NOT_APPEALABLE", expected_status=409)


def test_official_cannot_uphold_own_appeal_returns_forbidden_role(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §3.13: "A `LeagueAdmin` adjudicates."

    Design: Corner/state_machines/official_cannot_uphold_own_appeal_returns_forbidden_role
    """
    ctx = setup_declined_with_appeal(reason="x")
    res = api.uphold_appeal(ctx["appeal"]["id"], make_official_headers(ctx["official"]["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
