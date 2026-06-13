"""Optimistic concurrency (OCC), boundary input validation, RBAC, reverse-
reachability reads, derived-counter reconciliation, and immediate consistency.

Each test translates exactly one design instance (Difficulty queue A or Corner queue B).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    create_league_payload, create_official_payload, create_game_payload,
    create_crew_slot_payload, create_evaluation_payload, update_official_payload,
    TEST_USERS, make_official_headers,
    create_league, create_official, create_wide_availability,
    offer_slot, accept_assignment, current_game_version, set_clock, lock_game,
    setup_two_slot_open_game, setup_open_game_with_slot, setup_completed_assignment,
)

ADMIN = TEST_USERS["league_admin_headers"]
ASSIGNOR = TEST_USERS["assignor_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]


# ─── OCC boundary on Game.version (Difficulty) ───────────────────────────────

def test_stale_game_version_on_offer_rejected_412(api):
    """PRD §2.6: "If a prior offer or acceptance against a sibling slot has already
    advanced the game's version since the assignor last read it — for example,
    because a previous fill recomputed `crew_filled_count` or bubbled the game to
    `STAFFED` — then the submitted `expected_game_version` no longer matches the
    game's current `version`, and the offer is rejected with `ERR_STALE_GAME_VERSION`
    (HTTP 412)."

    Design: Difficulty/boundary_precision_check/stale_game_version_on_offer_rejected_412
    """
    ctx = setup_two_slot_open_game()
    gv1 = ctx["game"]["version"]  # version captured right after open
    a1 = offer_slot(ctx["slot1"]["id"], ctx["official_a"]["id"], ctx["game"]["id"])
    accept_assignment(a1["id"], ctx["official_a"]["id"], ctx["game"]["id"])  # bumps version
    # Second offer carrying the stale pre-accept version gv1.
    res = api.offer_crew_slot(
        ctx["slot2"]["id"],
        {"official_id": ctx["official_b"]["id"], "expected_game_version": gv1}, ASSIGNOR)
    validate_error(res, "ERR_STALE_GAME_VERSION", expected_status=412)


def test_zero_required_crew_size_rejected(api):
    """PRD §3.3: "The crew size is given by `required_crew_size`, which must be at
    least 1."
    PRD §2.9: "structural input validity — required fields present, enums
    recognized, numeric ranges respected — is the last gate, surfacing
    `ERR_INVALID_REQUEST`."

    Design: Difficulty/boundary_precision_check/zero_required_crew_size_rejected_invalid_request
    """
    league = create_league(sport="BASKETBALL")
    res = api.create_game(create_game_payload(league["id"], required_crew_size=0), ASSIGNOR)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_stale_official_version_on_patch_rejected_412(api):
    """PRD §2.6: "An update to an official must submit `expected_official_version`;
    if it does not equal the official's current `version`, the update is rejected
    with `ERR_STALE_OFFICIAL_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_official_version_on_patch_returns_412
    """
    league = validate_success(api.create_league(create_league_payload(sport="SOCCER"), ADMIN), 201)
    official = validate_success(api.create_official(create_official_payload(league["id"]), ADMIN), 201)
    ov1 = validate_success(api.get_official(official["id"], ADMIN), 200)["version"]
    # First patch advances version past ov1.
    validate_success(api.update_official(
        official["id"], update_official_payload(ov1, rank="CERTIFIED"), ADMIN), 200)
    # Second patch carrying the now-stale ov1.
    res = api.update_official(
        official["id"], update_official_payload(ov1, rank="SENIOR"), ADMIN)
    validate_error(res, "ERR_STALE_OFFICIAL_VERSION", expected_status=412)


def test_game_version_increments_on_lock(api):
    """PRD §3.9: "Locking carries `expected_game_version`, freezes all filled slots
    so that no further offers are accepted, and increments the game's `version` by
    one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_game_write
    """
    league = create_league(sport="SOCCER")
    official = create_official(league["id"])
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(league["id"]), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    asg = offer_slot(slot["id"], official["id"], game["id"])
    accept_assignment(asg["id"], official["id"], game["id"])
    gv3 = current_game_version(game["id"])
    locked = validate_success(api.lock_game(game["id"], {"expected_game_version": gv3}, ASSIGNOR), 200)
    assert locked["status"] == "LOCKED"
    assert locked["version"] == gv3 + 1


def test_crew_filled_count_reconciles_after_accept(api):
    """PRD §2.5: "When an official accepts an offer, the slot becomes filled, the
    owning game's `crew_filled_count` is recomputed, and — if that count reaches the
    game's `required_crew_size` — the game automatically advances from `OPEN` to
    `STAFFED` without any explicit request on the game itself."

    Design: Corner/cross_cutting_complexity_layers/derived_crew_filled_count_reconciles_after_accept
    """
    ctx = setup_open_game_with_slot()
    asg = offer_slot(ctx["slot"]["id"], ctx["official"]["id"], ctx["game"]["id"])
    before = validate_success(api.get_game(ctx["game"]["id"], ASSIGNOR), 200)
    assert before["crew_filled_count"] == 0
    accept_assignment(asg["id"], ctx["official"]["id"], ctx["game"]["id"])
    after = validate_success(api.get_game(ctx["game"]["id"], ASSIGNOR), 200)
    assert after["crew_filled_count"] == 1
    assert after["status"] == "STAFFED"


def test_settle_immediate_consistency(api):
    """PRD §2.5: "Many operations ripple across more than one entity, and the system
    reconciles those effects immediately rather than lazily."
    PRD §3.9: "after settlement, `settlement_total_cents` is the sum of
    `final_pay_cents` over the game's completed assignments."

    Design: Corner/consistency_model/settle_immediate_consistency_all_fields_in_response
    """
    ctx = setup_completed_assignment(position="REFEREE", official_overrides={"rank": "SENIOR"})
    fetched = validate_success(api.get_game(ctx["game"]["id"], ASSIGNOR), 200)
    assert fetched["status"] == "COMPLETED"
    assert fetched["settlement_total_cents"] == 15000  # SENIOR base 15000, mileage 0


# ─── RBAC (Corner) ───────────────────────────────────────────────────────────

def test_official_cannot_create_game_returns_forbidden_role(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "An `Assignor` owns game creation, crew provisioning, slot offers,
    locking, settlement, cancellation, and no-show recording."

    Design: Corner/endpoints/official_cannot_create_game_returns_forbidden_role
    """
    league = create_league(sport="BASKETBALL")
    official = create_official(league["id"])
    res = api.create_game(create_game_payload(league["id"]),
                          make_official_headers(official["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two authentication headers: `X-User-ID`,
    which identifies the acting user, and `X-User-Role`, which declares the capacity
    in which they are acting. If either header is missing or malformed, the request
    is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/endpoints/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_leagues({})  # no auth headers
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_assignor_cannot_evaluate_returns_forbidden_role(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "An `Evaluator` rates officials on completed assignments."

    Design: Corner/rbac/assignor_cannot_evaluate_returns_forbidden_role
    """
    ctx = setup_completed_assignment(position="REFEREE", official_overrides={"rank": "SENIOR"})
    res = api.create_evaluation(
        ctx["assignment"]["id"], create_evaluation_payload(4.0), ASSIGNOR)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_official_cannot_accept_others_assignment(api):
    """PRD §2.1: "when an official accepts, declines, withdraws, or appeals an
    assignment, the system requires that `X-User-ID` equal the assignment's
    `official_id`; a mismatch is rejected with `ERR_NOT_ASSIGNMENT_OWNER`."

    Design: Corner/rbac/official_cannot_accept_others_assignment_returns_not_owner
    """
    league = create_league(sport="BASKETBALL")
    oa = create_official(league["id"], full_name="A")
    ob = create_official(league["id"], full_name="B")
    create_wide_availability(oa["id"])
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(league["id"]), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    asg = offer_slot(slot["id"], oa["id"], game["id"])  # offered to A
    gv = current_game_version(game["id"])
    res = api.accept_assignment(
        asg["id"], {"expected_game_version": gv}, make_official_headers(ob["id"]))  # B accepts
    validate_error(res, "ERR_NOT_ASSIGNMENT_OWNER", expected_status=403)


# ─── Evaluation constraints (Corner) ─────────────────────────────────────────

def test_second_evaluation_on_same_assignment_rejected(api):
    """PRD §3.11: "An evaluation may target only a `COMPLETED` assignment, and only
    one evaluation may exist per assignment; rating a non-completed assignment or
    adding a second evaluation to one already rated is rejected with
    `ERR_ASSIGNMENT_NOT_COMPLETED`."

    Design: Corner/validations/second_evaluation_on_same_assignment_rejected
    """
    ctx = setup_completed_assignment(position="REFEREE", official_overrides={"rank": "SENIOR"})
    validate_success(api.create_evaluation(
        ctx["assignment"]["id"], create_evaluation_payload(4.0), EVALUATOR), 201)
    res = api.create_evaluation(
        ctx["assignment"]["id"], create_evaluation_payload(5.0), EVALUATOR)
    validate_error(res, "ERR_ASSIGNMENT_NOT_COMPLETED", expected_status=409)


def test_evaluation_score_out_of_range_rejected(api):
    """PRD §3.11: "a `score` on the one-to-five scale (the score must be at least 1.0
    and at most 5.0, else `ERR_INVALID_REQUEST`)".

    Design: Corner/validations/evaluation_score_out_of_range_rejected
    """
    ctx = setup_completed_assignment(position="REFEREE", official_overrides={"rank": "SENIOR"})
    res = api.create_evaluation(
        ctx["assignment"]["id"], create_evaluation_payload(6.0), EVALUATOR)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ─── Reverse-reachability reads (Corner) ─────────────────────────────────────

def test_filtered_assignments_by_game_id(api):
    """PRD §2.7: "These reverse-reachability lists let a caller walk the entity
    graph without the API resorting to deep URL nesting; the underlying entities
    remain peers linked by foreign keys."
    PRD §4 (GET /assignments): "List/filter assignments by FK".

    Design: Corner/endpoints/filtered_assignments_by_game_id_returns_array
    """
    ctx = setup_open_game_with_slot()
    asg = offer_slot(ctx["slot"]["id"], ctx["official"]["id"], ctx["game"]["id"])
    data, meta = validate_paginated(api.list_assignments(ASSIGNOR, params={"game_id": ctx["game"]["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == asg["id"]


def test_crewslots_subresource_returns_array(api):
    """PRD §2.7: "Several read endpoints address a resource through a parent
    identifier in the path — for example, the crew slots of a game".
    PRD §4 (GET /games/{id}/crew-slots): "List crew slots for a game".

    Design: Corner/endpoints/crewslots_subresource_returns_array_for_game
    """
    league = create_league(sport="BASKETBALL")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], required_crew_size=2), ASSIGNOR), 201)
    validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
    validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    data, meta = validate_paginated(api.list_game_crew_slots(game["id"], ASSIGNOR))
    assert len(data) == 2
