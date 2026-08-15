"""Date-hold placement, challenge, confirm cascade, and expiry timing."""
from test_helpers import (
    VM,
    ApiErrorId,
    assert_date_hold,
    create_agent,
    create_artist,
    create_show,
    get_show,
    make_booking_agent_headers,
    place_hold,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_hold_confirm_releases_competing_holds(api):
    """PRD §3.2: "A successful confirmation does four things as one cascade:
    the hold becomes `CONFIRMED`; the show moves from `HOLD_PENDING` to
    `CONFIRMED` and its `hold_priority` is copied from the confirmed hold's
    `priority`; every other date hold on the same room and date that is
    `ACTIVE` or `CHALLENGED` is released to `RELEASED`; and the show's
    `version` increments by one."

    Design: Difficulty/transitive_cascade/hold_confirm_releases_competing_holds
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    # Three shows on the same (room, show_date), each with its own hold.
    show_kw = dict(
        room="MAIN_ROOM", show_date="2026-10-10",
        doors_at_utc="2026-10-10T19:00:00Z",
        curfew_at_utc="2026-10-10T23:00:00Z",
        total_capacity=500, on_sale_at_utc="2026-08-20T10:00:00Z",
    )
    sa = create_show(artist["id"], agent=agent, **show_kw)
    sb = create_show(artist["id"], agent=agent, **show_kw)
    sc = create_show(artist["id"], agent=agent, **show_kw)
    ha = place_hold(sa["id"], agent, priority="P1")
    hb = place_hold(sb["id"], agent, priority="P2")
    hc = place_hold(sc["id"], agent, priority="COURTESY")

    v_sa = get_show(sa["id"])["version"]
    confirm_resp = api.confirm_date_hold(
        sa["id"], ha["id"],
        {"expected_show_version": v_sa},
        make_booking_agent_headers(agent["id"]),
    )
    validate_success(confirm_resp, 200)

    # Link 1: confirmed hold
    ha_after = validate_success(
        api.get_show_date_hold(sa["id"], ha["id"], VM), 200,
    )
    assert ha_after["status"] == "CONFIRMED"
    # Link 2: show flips to CONFIRMED with hold_priority copied
    sa_after = get_show(sa["id"])
    assert sa_after["status"] == "CONFIRMED"
    assert sa_after["hold_priority"] == "P1"
    # Link 3: competing holds on same (room, date) are released
    hb_after = validate_success(
        api.get_show_date_hold(sb["id"], hb["id"], VM), 200,
    )
    hc_after = validate_success(
        api.get_show_date_hold(sc["id"], hc["id"], VM), 200,
    )
    assert hb_after["status"] == "RELEASED"
    assert hc_after["status"] == "RELEASED"
    # The losing shows themselves remain HOLD_PENDING (their holds released).
    assert get_show(sb["id"])["status"] == "HOLD_PENDING"
    assert get_show(sc["id"])["status"] == "HOLD_PENDING"


def test_hold_confirm_releases_challenged_competitor(api):
    """PRD §3.2: "A successful confirmation does four things as one cascade:
    the hold becomes `CONFIRMED`; the show moves from `HOLD_PENDING` to
    `CONFIRMED` and its `hold_priority` is copied from the confirmed hold's
    `priority`; every other date hold on the same room and date that is
    `ACTIVE` or `CHALLENGED` is released to `RELEASED`; and the show's
    `version` increments by one."

    Design: Difficulty/transitive_cascade/hold_confirm_releases_competing_holds
    """
    set_clock()
    artist = create_artist()
    agent_a = create_agent()
    agent_b = create_agent()
    show_kw = dict(
        room="MAIN_ROOM", show_date="2026-10-11",
        doors_at_utc="2026-10-11T19:00:00Z",
        curfew_at_utc="2026-10-11T23:00:00Z",
        total_capacity=500, on_sale_at_utc="2026-08-20T10:00:00Z",
    )
    s1 = create_show(artist["id"], agent=agent_a, **show_kw)
    s2 = create_show(artist["id"], agent=agent_b, **show_kw)
    # agent_a holds P2 on s1; agent_b challenges with P1 from s2's side via
    # s1's hold.
    h1 = place_hold(s1["id"], agent_a, priority="P2")
    # Agent B places its own P1 hold on s2 then challenges agent A's P2 hold.
    h2 = place_hold(s2["id"], agent_b, priority="P1")
    challenge_resp = api.challenge_date_hold(
        s1["id"], h1["id"],
        {"challenger_agent_id": agent_b["id"], "challenger_priority": "P1"},
        make_booking_agent_headers(agent_b["id"]),
    )
    validate_success(challenge_resp, 201)
    # h1 is now CHALLENGED; h2 is ACTIVE.
    # Confirm h2 (P1) — should release h1 (CHALLENGED) on same room+date.
    v_s2 = get_show(s2["id"])["version"]
    confirm_resp = api.confirm_date_hold(
        s2["id"], h2["id"],
        {"expected_show_version": v_s2},
        make_booking_agent_headers(agent_b["id"]),
    )
    validate_success(confirm_resp, 200)

    h1_after = validate_success(
        api.get_show_date_hold(s1["id"], h1["id"], VM), 200,
    )
    assert h1_after["status"] == "RELEASED"


def test_date_hold_same_room_date_exclusion(api):
    """PRD §3.2: "An unchallenged `ACTIVE` hold may be confirmed by the agent
    that placed it — the caller's identity must equal the hold's
    `booked_by_agent_id` — provided the confirmation lands strictly before
    the hold's `hold_expires_at_utc` and no competing hold blocks it: no
    other `ACTIVE` hold on the same room and date may hold a strictly
    higher priority, and among equal-priority `ACTIVE` competitors the
    earliest-created hold wins."
    PRD §3.2: "confirming a hold that is not in the `ACTIVE` or `CHALLENGED`
    from-state is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/date_hold_same_room_date_exclusion
    """
    set_clock()
    artist = create_artist()
    agent_a = create_agent()
    agent_b = create_agent()
    show_kw = dict(
        room="MAIN_ROOM", show_date="2026-12-01",
        doors_at_utc="2026-12-01T19:00:00Z",
        curfew_at_utc="2026-12-01T23:00:00Z",
        total_capacity=500, on_sale_at_utc="2026-09-01T10:00:00Z",
    )
    s1 = create_show(artist["id"], agent=agent_a, **show_kw)
    s2 = create_show(artist["id"], agent=agent_b, **show_kw)
    place_hold(s1["id"], agent_a, priority="P1")
    h2 = place_hold(s2["id"], agent_b, priority="P2")

    v2 = get_show(s2["id"])["version"]
    resp = api.confirm_date_hold(
        s2["id"], h2["id"],
        {"expected_show_version": v2},
        make_booking_agent_headers(agent_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    h2_after = validate_success(
        api.get_show_date_hold(s2["id"], h2["id"], VM), 200,
    )
    assert h2_after["status"] == "ACTIVE"
    assert get_show(s2["id"])["status"] == "HOLD_PENDING"


def test_date_hold_priority_preemption_blocks_lower_priority_confirm(api):
    """PRD §3.2: "no other `ACTIVE` hold on the same room and date may hold
    a strictly higher priority, and among equal-priority `ACTIVE` competitors
    the earliest-created hold wins."

    Design: Difficulty/resource_temporal_overlap/date_hold_same_room_date_exclusion
    """
    set_clock()
    artist = create_artist()
    agent_a = create_agent()
    agent_b = create_agent()
    show_kw = dict(
        room="LOUNGE", show_date="2026-12-02",
        doors_at_utc="2026-12-02T19:00:00Z",
        curfew_at_utc="2026-12-02T23:00:00Z",
        total_capacity=200, on_sale_at_utc="2026-09-01T10:00:00Z",
    )
    s1 = create_show(artist["id"], agent=agent_a, **show_kw)
    s2 = create_show(artist["id"], agent=agent_b, **show_kw)
    # COURTESY placed first, then P1 — the later P1 still wins.
    hc = place_hold(s1["id"], agent_a, priority="COURTESY")
    place_hold(s2["id"], agent_b, priority="P1")

    v1 = get_show(s1["id"])["version"]
    resp = api.confirm_date_hold(
        s1["id"], hc["id"],
        {"expected_show_version": v1},
        make_booking_agent_headers(agent_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_hold_expired_temporal_check_fires(api):
    """PRD §3.2: "Confirming at or past the applicable deadline is rejected
    with `ERR_HOLD_EXPIRED` (HTTP 422); confirming a hold that is not in the
    `ACTIVE` or `CHALLENGED` from-state is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."
    PRD §3.2: "The platform stamps the hold `ACTIVE` and computes its
    `hold_expires_at_utc` from a fixed time-to-live ladder: a `P1` hold
    lives 48 hours, a `P2` hold 24 hours, and a `COURTESY` hold 12 hours."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_hold_confirm
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show = create_show(
        artist["id"], agent=agent,
        room="MAIN_ROOM", show_date="2026-11-01",
        doors_at_utc="2026-11-01T19:00:00Z",
        curfew_at_utc="2026-11-01T23:00:00Z",
        total_capacity=500, on_sale_at_utc="2026-09-01T10:00:00Z",
    )
    hold = place_hold(show["id"], agent, priority="P2")
    # Advance 25 hours so the P2 hold has expired.
    set_clock("2026-08-02T01:00:01Z")
    v = get_show(show["id"])["version"]
    resp = api.confirm_date_hold(
        show["id"], hold["id"],
        {"expected_show_version": v},
        make_booking_agent_headers(agent["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HOLD_EXPIRED, 422)
    h_after = validate_success(
        api.get_show_date_hold(show["id"], hold["id"], VM), 200,
    )
    assert h_after["status"] in ("ACTIVE", "EXPIRED")
    assert h_after["status"] != "CONFIRMED"


def test_hold_expired_p1_after_48h(api):
    """PRD §3.2: "The platform stamps the hold `ACTIVE` and computes its
    `hold_expires_at_utc` from a fixed time-to-live ladder: a `P1` hold
    lives 48 hours, a `P2` hold 24 hours, and a `COURTESY` hold 12 hours."
    PRD §3.2: "Confirming at or past the applicable deadline is rejected
    with `ERR_HOLD_EXPIRED` (HTTP 422); confirming a hold that is not in the
    `ACTIVE` or `CHALLENGED` from-state is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_hold_confirm
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show = create_show(
        artist["id"], agent=agent,
        room="MAIN_ROOM", show_date="2026-11-02",
        doors_at_utc="2026-11-02T19:00:00Z",
        curfew_at_utc="2026-11-02T23:00:00Z",
        total_capacity=500, on_sale_at_utc="2026-09-01T10:00:00Z",
    )
    hold = place_hold(show["id"], agent, priority="P1")
    assert_date_hold(hold)
    # Advance 49 hours so even the P1 hold has lapsed.
    set_clock("2026-08-03T01:00:01Z")
    v = get_show(show["id"])["version"]
    resp = api.confirm_date_hold(
        show["id"], hold["id"],
        {"expected_show_version": v},
        make_booking_agent_headers(agent["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HOLD_EXPIRED, 422)


def test_date_hold_release_from_terminal_confirmed_fails(api):
    """PRD §3.2: "Between challenge and confirmation, either side can stand
    down: the agent that placed a hold may release it, moving it from
    `ACTIVE` to `RELEASED` or from `CHALLENGED` to `RELEASED`, again only
    when the caller is the hold's `booked_by_agent_id`."
    PRD §2.8: "From-state validity for the requested transition, per the
    state machines of §3; failures yield `ERR_INVALID_STATE` (HTTP 409).
    When the target entity is already in a terminal state and no transition
    is defined at all, the rejection is `ERR_ALREADY_TERMINAL` (HTTP 409)."
    A CONFIRMED hold is terminal with no outbound transitions, so the two
    §2.8 sentences overlap here; either member of the pair is a faithful
    rejection (both are HTTP 409).

    Design: Corner/state_machines/date_hold_release_from_terminal_confirmed_fails
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show = create_show(artist["id"], agent=agent)
    hold = place_hold(show["id"], agent, priority="P1")
    v = get_show(show["id"])["version"]
    validate_success(
        api.confirm_date_hold(
            show["id"], hold["id"],
            {"expected_show_version": v},
            make_booking_agent_headers(agent["id"]),
        ),
        200,
    )
    resp = api.release_date_hold(
        show["id"], hold["id"], make_booking_agent_headers(agent["id"]),
    )
    assert resp.status_code == 409
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL],
    )
    h_after = validate_success(
        api.get_show_date_hold(show["id"], hold["id"], VM), 200,
    )
    assert h_after["status"] == "CONFIRMED"
