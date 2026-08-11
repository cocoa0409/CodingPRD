"""Pickup-plan negotiation: claim-state dependency, alternating counterparty
rule, the 3-round loop, and the 15-minute porch overlap buffer
(PRD §3.4, §2.11)."""
from test_helpers import (
    ApiErrorId,
    assert_iso_instant,
    create_accepted_claim,
    create_claim,
    create_confirmed_plan,
    create_post,
    create_proposed_plan,
    create_and_publish_post,
    get_claim,
    get_plan,
    make_member_headers,
    publish_post,
    setup_group_with_members,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Cross-entity dependency: PickupPlan requires Claim ACCEPTED
# ---------------------------------------------------------------------------

def test_pickup_plan_on_offered_claim_rejected(api):
    """PRD §3.4: "Creating a plan on a claim that is not `ACCEPTED` fails with
    `ERR_CLAIM_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/pickup_plan_requires_claim_accepted
    """
    group, members = setup_group_with_members(
        [("yg@x.com", "G"), ("ym@x.com", "M")], name="Pickup Dep Group", zip_code="98113"
    )
    g, m = members["yg@x.com"], members["ym@x.com"]
    post = create_and_publish_post(g, group, title="Crib", category="FURNITURE")
    claim = create_claim(m, post)
    assert claim["status"] == "OFFERED"
    res = api.create_pickup_plan(
        {"claim_id": claim["id"], "window_start": "2026-05-11T10:00:00Z",
         "window_end": "2026-05-11T11:00:00Z"},
        make_member_headers(g["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_ACCEPTED, expected_status=409)


def test_pickup_plan_created_after_claim_accepted(api):
    """PRD §3.4: "Creating a plan on a claim that is not `ACCEPTED` fails with
    `ERR_CLAIM_NOT_ACCEPTED`. The plan is born `PROPOSED` with `round_number` 1,
    the creator recorded as both `proposer_id` and `last_proposer_id`."

    Design: Difficulty/cross_entity_state_dependency/pickup_plan_requires_claim_accepted
    """
    group, members = setup_group_with_members(
        [("yg2@x.com", "G"), ("ym2@x.com", "M")], name="Pickup Dep Group 2",
        zip_code="98113",
    )
    g, m = members["yg2@x.com"], members["ym2@x.com"]
    post = create_and_publish_post(g, group, title="Crib", category="FURNITURE")
    claim = create_claim(m, post)
    validate_success(api.accept_claim(claim["id"], make_member_headers(m["id"])), 200)
    res = api.create_pickup_plan(
        {"claim_id": claim["id"], "window_start": "2026-05-11T10:00:00Z",
         "window_end": "2026-05-11T11:00:00Z"},
        make_member_headers(g["id"]),
    )
    plan = validate_success(res, 201)
    assert plan["status"] == "PROPOSED"
    assert plan["round_number"] == 1
    assert plan["proposer_id"] == g["id"]
    assert plan["last_proposer_id"] == g["id"]


# ---------------------------------------------------------------------------
# Negotiation loop bounded at 3 rounds (Difficulty/non_linear_state_machine)
# ---------------------------------------------------------------------------

def _setup_proposed_plan():
    """Giver GV proposes a plan on M's ACCEPTED claim. Returns (group, gv, m, post, claim, plan)."""
    group, members = setup_group_with_members(
        [("ng@x.com", "GV"), ("nm@x.com", "M")], name="Negotiation Group", zip_code="98105"
    )
    gv, m = members["ng@x.com"], members["nm@x.com"]
    post, claim = create_accepted_claim(gv, m, group, title="Bookshelf", category="FURNITURE")
    plan = create_proposed_plan(gv, claim, "2026-05-11T10:00:00Z", "2026-05-11T11:00:00Z")
    return group, gv, m, post, claim, plan


def test_pickup_counter_loop_max_rounds_rejects_fourth(api):
    """PRD §3.4: "The loop is capped at three rounds: a counter attempted when
    `round_number` has already reached 3 is rejected with
    `ERR_MAX_NEGOTIATION_ROUNDS` (HTTP 422)."
    PRD §3.4: "A counter-proposal replaces `window_start`, `window_end`, and
    optionally `location_note`, moves the plan from `PROPOSED` to `COUNTERED`
    (or keeps it in `COUNTERED`), increments `round_number` by one, and records
    the actor as the new `last_proposer_id`."

    Design: Difficulty/non_linear_state_machine/pickup_plan_counter_loop_max_rounds
    """
    group, gv, m, post, claim, plan = _setup_proposed_plan()

    # Round 2: claimer counters.
    res = api.counter_pickup_plan(
        plan["id"], {"window_start": "2026-05-11T14:00:00Z",
                     "window_end": "2026-05-11T15:00:00Z"},
        make_member_headers(m["id"]),
    )
    plan = validate_success(res, 200)
    assert plan["round_number"] == 2
    assert plan["status"] == "COUNTERED"
    assert plan["last_proposer_id"] == m["id"]

    # Round 3: giver counters back.
    res = api.counter_pickup_plan(
        plan["id"], {"window_start": "2026-05-11T16:00:00Z",
                     "window_end": "2026-05-11T17:00:00Z"},
        make_member_headers(gv["id"]),
    )
    plan = validate_success(res, 200)
    assert plan["round_number"] == 3
    assert plan["status"] == "COUNTERED"
    assert plan["last_proposer_id"] == gv["id"]

    # Round 4: rejected — the cap is reached.
    res = api.counter_pickup_plan(
        plan["id"], {"window_start": "2026-05-11T18:00:00Z",
                     "window_end": "2026-05-11T19:00:00Z"},
        make_member_headers(m["id"]),
    )
    validate_error(res, ApiErrorId.ERR_MAX_NEGOTIATION_ROUNDS, expected_status=422)


def test_pickup_counter_loop_joins_confirmed_at_round_three(api):
    """PRD §3.4: "Confirmation mirrors countering in its actors: the party who
    did **not** make the latest proposal confirms it, moving the plan from
    `PROPOSED` or `COUNTERED` to `CONFIRMED`."

    Second angle on the bounded loop: after two counters (round_number 3) the
    loop still joins at CONFIRMED on the latest window.

    Design: Difficulty/non_linear_state_machine/pickup_plan_counter_loop_max_rounds
    """
    group, gv, m, post, claim, plan = _setup_proposed_plan()
    res = api.counter_pickup_plan(
        plan["id"], {"window_start": "2026-05-11T14:00:00Z",
                     "window_end": "2026-05-11T15:00:00Z"},
        make_member_headers(m["id"]),
    )
    validate_success(res, 200)
    res = api.counter_pickup_plan(
        plan["id"], {"window_start": "2026-05-11T16:00:00Z",
                     "window_end": "2026-05-11T17:00:00Z"},
        make_member_headers(gv["id"]),
    )
    validate_success(res, 200)
    # The claimer (not the latest proposer) confirms the round-3 window.
    res = api.confirm_pickup_plan(plan["id"], make_member_headers(m["id"]))
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["round_number"] == 3
    assert_iso_instant(confirmed["window_start"], "2026-05-11T16:00:00Z")
    assert_iso_instant(confirmed["window_end"], "2026-05-11T17:00:00Z")


# ---------------------------------------------------------------------------
# Corner/state_machines — pickup plan invalid transitions and preconditions
# ---------------------------------------------------------------------------

def test_counter_on_confirmed_plan_returns_not_negotiable(api):
    """PRD §3.4: "Countering or confirming a plan that has left the negotiable
    states — anything other than `PROPOSED` or `COUNTERED` — fails with
    `ERR_PICKUP_NOT_NEGOTIABLE`."

    Design: Corner/state_machines/counter_on_confirmed_plan_returns_not_negotiable
    """
    group, members = setup_group_with_members(
        [("cng@x.com", "G"), ("cnm@x.com", "M")], name="Counter Group", zip_code="98216"
    )
    g, m = members["cng@x.com"], members["cnm@x.com"]
    post, claim = create_accepted_claim(g, m, group, title="Fan", category="HOUSEHOLD")
    plan = create_confirmed_plan(g, m, claim)
    assert plan["status"] == "CONFIRMED"
    res = api.counter_pickup_plan(
        plan["id"], {"window_start": "2026-05-11T12:00:00Z",
                     "window_end": "2026-05-11T13:00:00Z"},
        make_member_headers(g["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PICKUP_NOT_NEGOTIABLE, expected_status=409)
    after = get_plan(plan["id"], make_member_headers(g["id"]))
    assert after["status"] == "CONFIRMED"


def test_complete_proposed_plan_returns_not_confirmed(api):
    """PRD §3.4: "The giver alone closes out a confirmed plan, and only while it
    is `CONFIRMED` (`ERR_PICKUP_NOT_CONFIRMED` otherwise)."

    Design: Corner/state_machines/complete_proposed_plan_returns_not_confirmed
    """
    group, members = setup_group_with_members(
        [("cpg@x.com", "G"), ("cpm@x.com", "M")], name="Complete Group", zip_code="98217"
    )
    g, m = members["cpg@x.com"], members["cpm@x.com"]
    post, claim = create_accepted_claim(g, m, group, title="Heater", category="HOUSEHOLD")
    plan = create_proposed_plan(g, claim)
    assert plan["status"] == "PROPOSED"
    res = api.complete_pickup_plan(plan["id"], make_member_headers(g["id"]))
    validate_error(res, ApiErrorId.ERR_PICKUP_NOT_CONFIRMED, expected_status=409)
    plan_after = get_plan(plan["id"], make_member_headers(g["id"]))
    claim_after = get_claim(claim["id"], make_member_headers(m["id"]))
    assert plan_after["status"] == "PROPOSED"
    assert claim_after["status"] == "ACCEPTED"


def test_pickup_miss_before_window_end_returns_window_not_passed(api):
    """PRD §3.4: "If instead the window passes with no handoff, the giver
    reports a no-show — but only after the logical now has passed `window_end`
    (`ERR_PICKUP_WINDOW_NOT_PASSED` before then) — which moves the plan to
    `MISSED` and the claim from `ACCEPTED` to `NO_SHOW`"

    Design: Corner/state_machines/pickup_miss_before_window_end_returns_window_not_passed
    """
    group, members = setup_group_with_members(
        [("msg@x.com", "G"), ("msm@x.com", "M")], name="Miss Group", zip_code="98208"
    )
    g, m = members["msg@x.com"], members["msm@x.com"]
    post, claim = create_accepted_claim(g, m, group, title="Rake")
    plan = create_confirmed_plan(g, m, claim,
                                 window_start="2026-05-11T10:00:00Z",
                                 window_end="2026-05-11T11:00:00Z")
    # Logical now is 2026-05-10T09:00:00Z < window_end 2026-05-11T11:00:00Z.
    res = api.miss_pickup_plan(plan["id"], make_member_headers(g["id"]))
    validate_error(res, ApiErrorId.ERR_PICKUP_WINDOW_NOT_PASSED, expected_status=409)
    plan_after = get_plan(plan["id"], make_member_headers(g["id"]))
    claim_after = get_claim(claim["id"], make_member_headers(m["id"]))
    assert plan_after["status"] == "CONFIRMED"
    assert claim_after["status"] == "ACCEPTED"


def test_proposer_confirm_own_plan_rejected(api):
    """PRD §3.4: "The alternation is strict: the actor must be the giver or the
    claimer of the underlying claim and must not be the member who made the most
    recent proposal — violations surface `ERR_NOT_COUNTERPARTY` (HTTP 403),
    which also greets non-parties."

    Design: Corner/validations/proposer_confirm_own_plan_rejected
    """
    group, members = setup_group_with_members(
        [("ncg@x.com", "G"), ("ncm@x.com", "M")], name="Counterparty Group",
        zip_code="98230",
    )
    g, m = members["ncg@x.com"], members["ncm@x.com"]
    post, claim = create_accepted_claim(g, m, group, title="Table", category="FURNITURE")
    plan = create_proposed_plan(g, claim)
    res = api.confirm_pickup_plan(plan["id"], make_member_headers(g["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_COUNTERPARTY, expected_status=403)
    after = get_plan(plan["id"], make_member_headers(g["id"]))
    assert after["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Porch overlap buffer (Difficulty/resource_temporal_overlap)
# ---------------------------------------------------------------------------

def _setup_giver_with_confirmed_window():
    """Giver G has a CONFIRMED plan for M1's claim with window
    [2026-05-11T10:00:00Z, 2026-05-11T11:00:00Z]; M2 holds a second ACCEPTED
    claim on another of G's posts."""
    group, members = setup_group_with_members(
        [("wg@x.com", "G"), ("wm1@x.com", "M1"), ("wm2@x.com", "M2")],
        name="Window Group", zip_code="98114",
    )
    g, m1, m2 = members["wg@x.com"], members["wm1@x.com"], members["wm2@x.com"]
    p1, c1 = create_accepted_claim(g, m1, group, title="Lamp A", category="HOUSEHOLD")
    create_confirmed_plan(g, m1, c1, "2026-05-11T10:00:00Z", "2026-05-11T11:00:00Z")
    p2, c2 = create_accepted_claim(g, m2, group, title="Lamp B", category="HOUSEHOLD")
    return group, g, m1, m2, p1, c1, p2, c2


def test_pickup_window_inside_buffer_rejected(api):
    """PRD §2.11: "Pickup windows are **closed intervals** guarded by a buffer:
    a proposed window conflicts with an existing confirmed window on the same
    porch when the new window's start falls before the existing window's end
    plus 15 minutes *and* the new window's end falls after the existing window's
    start minus 15 minutes — both comparisons strict, so a new window starting
    exactly at the existing end plus 15 minutes does not conflict."
    PRD §3.4: "the competing set is the giver's other `CONFIRMED` plans (plans
    that are merely `PROPOSED` or `COUNTERED`, or already `COMPLETED`, `MISSED`,
    or `CANCELLED`, never block), and a collision under the 15-minute
    double-sided buffer is rejected with `ERR_PICKUP_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/pickup_window_buffer_overlap
    """
    group, g, m1, m2, p1, c1, p2, c2 = _setup_giver_with_confirmed_window()
    # [11:10, 12:00]: 11:10 < 11:00 + 15min and 12:00 > 10:00 - 15min -> conflict.
    res = api.create_pickup_plan(
        {"claim_id": c2["id"], "window_start": "2026-05-11T11:10:00Z",
         "window_end": "2026-05-11T12:00:00Z"},
        make_member_headers(g["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PICKUP_WINDOW_CONFLICT, expected_status=409)


def test_pickup_window_starting_exactly_at_buffer_edge_allowed(api):
    """PRD §2.11: "Pickup windows are **closed intervals** guarded by a buffer:
    a proposed window conflicts with an existing confirmed window on the same
    porch when the new window's start falls before the existing window's end
    plus 15 minutes *and* the new window's end falls after the existing window's
    start minus 15 minutes — both comparisons strict, so a new window starting
    exactly at the existing end plus 15 minutes does not conflict."

    Design: Difficulty/resource_temporal_overlap/pickup_window_buffer_overlap
    """
    group, g, m1, m2, p1, c1, p2, c2 = _setup_giver_with_confirmed_window()
    # [11:15, 12:15]: starts exactly at existing_end + 15min -> strict inequality
    # means NO conflict.
    res = api.create_pickup_plan(
        {"claim_id": c2["id"], "window_start": "2026-05-11T11:15:00Z",
         "window_end": "2026-05-11T12:15:00Z"},
        make_member_headers(g["id"]),
    )
    plan = validate_success(res, 201)
    assert plan["status"] == "PROPOSED", (
        "a window starting exactly at existing_end + 15min must be accepted"
    )
