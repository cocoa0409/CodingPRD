"""Match scheduling, weather contingency, reschedule queue, and officials."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_instant_equals,
    ApiErrorId,
    create_event, award_event_bid, create_contracted_venue, create_hotel_block,
    advance_posture, create_division, create_field_payload,
    create_weather_alert_payload, create_official_payload,
    create_active_official, propose_and_accept_assignment,
    setup_event_in_registration_open, setup_published_bracket,
    setup_match_in_reschedule_queue, list_division_matches, get_event,
    make_official_headers, make_venue_manager_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ANY = TEST_USERS["any_headers"]


def _get_match(api, match_id):
    return get_success_data(api.get_match(match_id, ANY))


def _get_official(api, official_id):
    return get_success_data(api.get_official(official_id, ANY))


def _get_assignment(api, assignment_id):
    return get_success_data(api.get_assignment(assignment_id, ANY))


# ===========================================================================
# Queue A: non_linear_state_machine / match_weather_reschedule_cycle
# ===========================================================================

def test_match_weather_reschedule_cycle(api):
    """PRD §3.6: "A successful reschedule updates `field_id`, `scheduled_start`,
    and the computed `scheduled_end`, preserves `original_scheduled_start`, and
    returns the match to `SCHEDULED`. The loop `SCHEDULED` → `WEATHER_DELAYED` →
    `RESCHEDULE_QUEUE` → `SCHEDULED` is cyclic and may repeat as often as the
    weather demands."

    Design: Difficulty/non_linear_state_machine/match_weather_reschedule_cycle
    """
    ctx = setup_match_in_reschedule_queue()
    assert ctx["match"]["status"] == "RESCHEDULE_QUEUE"
    rescheduled = validate_success(api.reschedule_match(
        ctx["match"]["id"], {"field_id": ctx["field"]["id"],
                             "scheduled_start": "2026-10-11T09:00:00Z"}, ADMIN))
    assert rescheduled["status"] == "SCHEDULED"
    assert_instant_equals(rescheduled["original_scheduled_start"], "2026-10-10T14:00:00Z", "original_scheduled_start")
    assert_instant_equals(rescheduled["scheduled_start"], "2026-10-11T09:00:00Z", "scheduled_start")
    assert_instant_equals(rescheduled["scheduled_end"], "2026-10-11T10:30:00Z", "scheduled_end")


def test_match_weather_delay_clears_field_and_time(api):
    """PRD §3.6: "Resolving an `ACTIVE` alert moves it to `RESOLVED` and pushes
    every match it delayed from `WEATHER_DELAYED` into `RESCHEDULE_QUEUE`,
    clearing each such match's `field_id` and `scheduled_start` — the queue
    holds only `original_scheduled_start` as its memory of the original plan."

    Design: Difficulty/non_linear_state_machine/match_weather_reschedule_cycle
    """
    ctx = setup_match_in_reschedule_queue()
    queued = ctx["match"]
    assert queued["status"] == "RESCHEDULE_QUEUE"
    assert queued["field_id"] is None
    assert queued["scheduled_start"] is None
    assert_instant_equals(queued["original_scheduled_start"], "2026-10-10T14:00:00Z", "original_scheduled_start")


# ===========================================================================
# Queue A: transitive_cascade / weather_alert_three_hop_cascade
# ===========================================================================

def _setup_live_final_with_accepted_official(certification="NATIONAL", slot_role="CREW_CHIEF",
                                             game_limit=None):
    """LIVE event; final SCHEDULED 2026-10-10T14:00; one ACTIVE official with an
    ACCEPTED assignment on it. Returns (ctx, match, official, assignment)."""
    from test_helpers import api_client as _api
    ctx = setup_published_bracket(team_ratings=[90, 70], advance_to_live=True)
    match = ctx["matches"][-1]
    validate_success(_api.schedule_match(
        match["id"], {"field_id": ctx["field"]["id"],
                      "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    payload = {"name": "Nat Ref", "certification_level": certification}
    if game_limit is not None:
        payload["game_limit_per_day"] = game_limit
    official = create_active_official(ctx["event"]["id"], **payload)
    assignment = propose_and_accept_assignment(match["id"], official["id"], slot_role=slot_role)
    return ctx, match, official, assignment


def test_weather_alert_three_hop_cascade(api):
    """PRD §3.6: "Activation is the gated step: it requires `COMPETITION_SETUP`
    or `LIVE` posture (otherwise `ERR_EVENT_POSTURE_FORBIDS`) and moves the
    alert `ISSUED` → `ACTIVE`. Every match in `SCHEDULED` or `IN_PROGRESS` on a
    field of the scoped venues whose half-open playing window intersects the
    alert window becomes `WEATHER_DELAYED`, each incrementing its `version`;
    each such transition releases the match's assignments in `PROPOSED` or
    `ACCEPTED` with `released_reason` `WEATHER` and recomputes each affected
    official's `assigned_game_count`."

    Design: Difficulty/transitive_cascade/weather_alert_three_hop_cascade
    """
    ctx, match, official, assignment = _setup_live_final_with_accepted_official()
    assert _get_official(api, official["id"])["assigned_game_count"] == 1
    alert = get_success_data(api.create_weather_alert(
        ctx["event"]["id"],
        create_weather_alert_payload(venue_id=ctx["venue"]["id"]), ADMIN))
    validate_success(api.activate_alert(alert["id"], ADMIN))
    # hop 1: alert -> match
    assert _get_match(api, match["id"])["status"] == "WEATHER_DELAYED"
    # hop 2: match delay -> assignment release
    released = _get_assignment(api, assignment["id"])
    assert released["status"] == "RELEASED"
    assert released["released_reason"] == "WEATHER"
    # hop 3: release -> official load recompute
    assert _get_official(api, official["id"])["assigned_game_count"] == 0


def test_weather_alert_resolve_expires_unactivated_issued(api):
    """PRD §3.6: "Resolving an alert that was never activated instead expires
    it, `ISSUED` → `EXPIRED`, with no match cascade at all."

    Design: Difficulty/transitive_cascade/weather_alert_three_hop_cascade
    """
    ctx, match, official, assignment = _setup_live_final_with_accepted_official()
    alert = get_success_data(api.create_weather_alert(
        ctx["event"]["id"],
        create_weather_alert_payload(venue_id=ctx["venue"]["id"]), ADMIN))
    # Resolve without activating: expires, no match cascade.
    resolved = validate_success(api.resolve_alert(alert["id"], ADMIN))
    assert resolved["status"] == "EXPIRED"
    assert _get_match(api, match["id"])["status"] == "SCHEDULED"
    assert _get_assignment(api, assignment["id"])["status"] == "ACCEPTED"
    assert _get_official(api, official["id"])["assigned_game_count"] == 1


# ===========================================================================
# Queue A: resource_temporal_overlap / field_half_open_adjacency_and_conflict
# ===========================================================================

def test_field_half_open_adjacency_and_conflict(api):
    """PRD §3.5: "the match's half-open window from `scheduled_start` to
    `scheduled_end` must not overlap the window of any other `SCHEDULED` or
    `IN_PROGRESS` match on the same field — half-open adjacency is allowed, so
    one match ending exactly when another begins is not a conflict (an overlap
    is `ERR_FIELD_TIME_CONFLICT`, HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/field_half_open_adjacency_and_conflict
    """
    ctx = setup_published_bracket(team_ratings=[90, 85, 70, 65], advance_to_live=True)
    matches = ctx["matches"]
    by_pos = {(m["round_number"], m["bracket_slot"]): m for m in matches}
    r1m1, r1m2 = by_pos[(1, 1)], by_pos[(1, 2)]
    f1 = ctx["field"]["id"]
    validate_success(api.schedule_match(
        r1m1["id"], {"field_id": f1, "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    # 15:00 is inside [14:00, 15:30): conflict.
    resp = api.schedule_match(r1m2["id"], {"field_id": f1,
                                           "scheduled_start": "2026-10-10T15:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FIELD_TIME_CONFLICT)
    assert _get_match(api, r1m2["id"])["status"] == "PENDING_TEAMS"
    # 15:30 is exactly M1's end: half-open adjacency is allowed.
    scheduled = validate_success(api.schedule_match(
        r1m2["id"], {"field_id": f1, "scheduled_start": "2026-10-10T15:30:00Z"}, ADMIN))
    assert scheduled["status"] == "SCHEDULED"
    assert_instant_equals(scheduled["scheduled_end"], "2026-10-10T17:00:00Z", "scheduled_end")


def test_field_time_conflict_with_in_progress_match(api):
    """PRD §3.5: "the match's half-open window from `scheduled_start` to
    `scheduled_end` must not overlap the window of any other `SCHEDULED` or
    `IN_PROGRESS` match on the same field — half-open adjacency is allowed, so
    one match ending exactly when another begins is not a conflict (an overlap
    is `ERR_FIELD_TIME_CONFLICT`, HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/field_half_open_adjacency_and_conflict
    """
    ctx = setup_published_bracket(team_ratings=[90, 85, 70, 65], advance_to_live=True)
    by_pos = {(m["round_number"], m["bracket_slot"]): m for m in ctx["matches"]}
    r1m1, r1m2 = by_pos[(1, 1)], by_pos[(1, 2)]
    f1 = ctx["field"]["id"]
    validate_success(api.schedule_match(
        r1m1["id"], {"field_id": f1, "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    validate_success(api.start_match(r1m1["id"], ADMIN))
    # M1 is IN_PROGRESS 14:00-15:30; a 15:29 start still intersects.
    resp = api.schedule_match(r1m2["id"], {"field_id": f1,
                                           "scheduled_start": "2026-10-10T15:29:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FIELD_TIME_CONFLICT)


# ===========================================================================
# Queue A: priority_pair_validation_conflict /
#          assignment_cert_vs_window_priority_rejected
# ===========================================================================

def _setup_two_division_event():
    """LIVE event with two published 2-team divisions (D1, D2) and two fields.

    Returns dict with ctx fields plus d2, m1, m2, f2."""
    from test_helpers import api_client as _api
    from test_helpers import make_team_eligible as _mk
    ctx = setup_event_in_registration_open()
    ev_id = ctx["event"]["id"]
    d1 = ctx["division"]
    d2 = create_division(ev_id, name="U18", team_cap=4, min_teams=2,
                         registration_fee_cents=10000)
    _mk(d1["id"], name="Tigers", contact_email="t@x.com", strength_rating=90)
    _mk(d1["id"], name="Sharks", contact_email="s@x.com", strength_rating=70)
    _mk(d2["id"], name="Wolves", contact_email="w@x.com", strength_rating=85)
    _mk(d2["id"], name="Bears", contact_email="b@x.com", strength_rating=65)
    validate_success(_api.lock_seeding(d1["id"], ADMIN))
    validate_success(_api.lock_seeding(d2["id"], ADMIN))
    advance_posture(ev_id, "COMPETITION_SETUP")
    validate_success(_api.publish_bracket(d1["id"], ADMIN))
    validate_success(_api.publish_bracket(d2["id"], ADMIN))
    f2 = get_success_data(_api.create_field(
        ctx["venue"]["id"], create_field_payload(name="Field 2", surface_type="GRASS",
                                                 has_lights=True, slot_minutes=90), ADMIN))
    m1 = list_division_matches(d1["id"])[0]
    m2 = list_division_matches(d2["id"])[0]
    advance_posture(ev_id, "LIVE")
    return {"ctx": ctx, "d2": d2, "m1": m1, "m2": m2, "f2": f2}


def test_assignment_cert_vs_window_priority_rejected(api):
    """PRD §2.9: "...Segregation-of-duties checks (`ERR_SOD_VIOLATION`) run
    after state legality, followed by business-constraint checks (completeness,
    uniqueness, duplication, score thresholds), then temporal window rules, then
    cross-event referential integrity (`ERR_CROSS_EVENT_REFERENCE`), and finally
    capacity and fiscal limits (room inventory, shift capacity, daily assignment
    limits, block reconcilability)."
    PRD §3.7: "certification must suffice — `CREW_CHIEF` requires `REGIONAL` or
    `NATIONAL`, on the final round `CREW_CHIEF` requires `NATIONAL`, and a
    `TRAINEE` may only ever hold `ASSISTANT` (violations are
    `ERR_CERTIFICATION_INSUFFICIENT`, HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/assignment_cert_vs_window_priority_rejected
    """
    bundle = _setup_two_division_event()
    ctx, m1, m2, f2 = bundle["ctx"], bundle["m1"], bundle["m2"], bundle["f2"]
    validate_success(api.schedule_match(
        m1["id"], {"field_id": ctx["field"]["id"],
                   "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    validate_success(api.schedule_match(
        m2["id"], {"field_id": f2["id"], "scheduled_start": "2026-10-10T15:00:00Z"}, ADMIN))
    official = create_active_official(ctx["event"]["id"], name="Reg Ref",
                                      certification_level="REGIONAL")
    a1 = propose_and_accept_assignment(m1["id"], official["id"], slot_role="ASSISTANT")
    # REGIONAL cannot hold CREW_CHIEF on a final-round match; the window
    # conflict (15:00 within M1's buffered 13:30-16:00) must lose to it.
    resp = api.create_assignment(m2["id"], {"official_id": official["id"],
                                            "slot_role": "CREW_CHIEF"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT)
    data, meta = validate_paginated(api.list_match_assignments(m2["id"], ANY))
    assert meta["total_count"] == 0


def test_assignment_trainee_crew_chief_rejected(api):
    """PRD §3.7: "certification must suffice — `CREW_CHIEF` requires `REGIONAL`
    or `NATIONAL`, on the final round `CREW_CHIEF` requires `NATIONAL`, and a
    `TRAINEE` may only ever hold `ASSISTANT` (violations are
    `ERR_CERTIFICATION_INSUFFICIENT`, HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/assignment_cert_vs_window_priority_rejected
    """
    ctx = setup_published_bracket(team_ratings=[90, 70], advance_to_live=True)
    match = ctx["matches"][-1]
    validate_success(api.schedule_match(
        match["id"], {"field_id": ctx["field"]["id"],
                      "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    trainee = create_active_official(ctx["event"]["id"], name="Trainee Ref",
                                     certification_level="TRAINEE")
    # TRAINEE may only ever hold ASSISTANT (isolated certification violation).
    resp = api.create_assignment(match["id"], {"official_id": trainee["id"],
                                               "slot_role": "CREW_CHIEF"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT)
    # The same official as ASSISTANT is admitted.
    ok = validate_success(api.create_assignment(
        match["id"], {"official_id": trainee["id"], "slot_role": "ASSISTANT"}, ADMIN),
        expected_status=201)
    assert ok["status"] == "PROPOSED"


# ===========================================================================
# Corner / cross_cutting_layers (blackout cascade)
# ===========================================================================

def test_field_blackout_cascade_releases_assignments(api):
    """PRD §3.2: "Blacking out moves the field to `BLACKED_OUT` and records the
    window — and it does not silently move matches: every match on the field in
    `SCHEDULED` status whose half-open playing window intersects the blackout
    window is pushed into `RESCHEDULE_QUEUE` (each match's `version` increments,
    and its `original_scheduled_start` is preserved), while assignments on those
    matches in `PROPOSED` or `ACCEPTED` are released with `released_reason`
    `MATCH_CANCELLED` and each affected official's `assigned_game_count` is
    recomputed."

    Design: Corner/cross_cutting_layers/field_blackout_cascade_releases_assignments
    """
    ctx, match, official, assignment = _setup_live_final_with_accepted_official()
    assert _get_official(api, official["id"])["assigned_game_count"] == 1
    field = validate_success(api.blackout_field(ctx["field"]["id"], {
        "blackout_start": "2026-10-10T12:00:00Z",
        "blackout_end": "2026-10-10T18:00:00Z",
        "reason": "lightning stand",
    }, make_venue_manager_headers(ctx["venue"]["id"])))
    assert field["status"] == "BLACKED_OUT"
    assert_instant_equals(field["blackout_start"], "2026-10-10T12:00:00Z", "blackout_start")
    assert_instant_equals(field["blackout_end"], "2026-10-10T18:00:00Z", "blackout_end")
    # The blackout enqueues the match directly (no WEATHER_DELAYED hop).
    queued = _get_match(api, match["id"])
    assert queued["status"] == "RESCHEDULE_QUEUE"
    assert_instant_equals(queued["original_scheduled_start"], "2026-10-10T14:00:00Z", "original_scheduled_start")
    released = _get_assignment(api, assignment["id"])
    assert released["status"] == "RELEASED"
    assert released["released_reason"] == "MATCH_CANCELLED"
    assert _get_official(api, official["id"])["assigned_game_count"] == 0


# ===========================================================================
# Corner / consistency_model (immediate visibility)
# ===========================================================================

def test_finalize_response_immediate_visibility(api):
    """PRD §3.6: "The higher scorer becomes `winner_team_id` and the match
    becomes `FINAL`."
    PRD §2.10: "State changes propagate. When a parent transitions in a way that
    resolves its children — an event cancelled, a division locked, a field
    blacked out, a weather alert activated, a shift completed, a settlement paid
    — every affected child entity transitions with it, and each touched entity
    independently increments its `version` by one and refreshes its
    `updated_at`. Derived counters such as a division's `entered_team_count`, a
    shift's `confirmed_count`, a block's `picked_up_room_nights`, and an
    official's `assigned_game_count` are recomputed as part of the same
    operation, never left stale."

    Design: Corner/consistency_model/finalize_response_immediate_visibility
    """
    ctx = setup_published_bracket(team_ratings=[90, 70], advance_to_live=True)
    t1 = ctx["team_ids"][0]
    match = ctx["matches"][-1]
    validate_success(api.schedule_match(
        match["id"], {"field_id": ctx["field"]["id"],
                      "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    validate_success(api.start_match(match["id"], ADMIN))
    resp = api.finalize_match(match["id"], {"home_score": 3, "away_score": 1}, ADMIN)
    finished = validate_success(resp)
    assert finished["status"] == "FINAL"
    assert finished["winner_team_id"] == t1
    assert finished["home_score"] == 3
    # A subsequent read returns identical values (no lag).
    reread = _get_match(api, match["id"])
    assert reread["status"] == "FINAL"
    assert reread["winner_team_id"] == t1


# ===========================================================================
# Corner / calculations (reschedule queue order)
# ===========================================================================

def test_reschedule_queue_order_enforced(api):
    """PRD §3.6: "Within a division, queued matches are ordered by
    `round_number` ascending, then `original_scheduled_start` ascending with
    empty values last, then `created_at` ascending; a queued match may only be
    rescheduled once every other queued match of the same division that sorts
    earlier has already left the queue — that is, is `SCHEDULED` or in a
    terminal state — and jumping the queue is rejected with
    `ERR_RESCHEDULE_ORDER_VIOLATION` (HTTP 409)."

    Design: Corner/calculations/reschedule_queue_order_enforced
    """
    ctx = setup_published_bracket(team_ratings=[90, 85, 70, 65], advance_to_live=True)
    by_pos = {(m["round_number"], m["bracket_slot"]): m for m in ctx["matches"]}
    r1m1, r1m2 = by_pos[(1, 1)], by_pos[(1, 2)]
    f1 = ctx["field"]["id"]
    validate_success(api.schedule_match(
        r1m1["id"], {"field_id": f1, "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    validate_success(api.schedule_match(
        r1m2["id"], {"field_id": f1, "scheduled_start": "2026-10-10T15:30:00Z"}, ADMIN))
    alert = get_success_data(api.create_weather_alert(
        ctx["event"]["id"],
        create_weather_alert_payload(venue_id=ctx["venue"]["id"]), ADMIN))
    validate_success(api.activate_alert(alert["id"], ADMIN))
    validate_success(api.resolve_alert(alert["id"], ADMIN))
    # M2 (original start 15:30) sorts after M1 (14:00): rescheduling M2 first
    # jumps the queue.
    resp = api.reschedule_match(r1m2["id"], {"field_id": f1,
                                             "scheduled_start": "2026-10-11T09:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RESCHEDULE_ORDER_VIOLATION)
    # In order: M1 then M2 succeed.
    m1_after = validate_success(api.reschedule_match(
        r1m1["id"], {"field_id": f1, "scheduled_start": "2026-10-11T09:00:00Z"}, ADMIN))
    assert m1_after["status"] == "SCHEDULED"
    assert_instant_equals(m1_after["scheduled_start"], "2026-10-11T09:00:00Z", "m1 scheduled_start")
    m2_after = validate_success(api.reschedule_match(
        r1m2["id"], {"field_id": f1, "scheduled_start": "2026-10-11T11:00:00Z"}, ADMIN))
    assert m2_after["status"] == "SCHEDULED"
    assert_instant_equals(m2_after["scheduled_start"], "2026-10-11T11:00:00Z", "m2 scheduled_start")


# ===========================================================================
# Corner / errors (match scheduling battery, official assignment battery,
# generic state + alert)
# ===========================================================================

def test_match_scheduling_error_battery_rejected(api):
    """PRD §3.5: "The preconditions, applied in the order of §2.9, are: both
    `home_team_id` and `away_team_id` must already be set (otherwise
    `ERR_MATCH_TEAMS_INCOMPLETE`, HTTP 409); the match must be `PENDING_TEAMS`
    and its division `BRACKET_PUBLISHED` (otherwise `ERR_MATCH_NOT_SCHEDULABLE`,
    HTTP 409); the event must be in `COMPETITION_SETUP` or `LIVE` (otherwise
    `ERR_EVENT_POSTURE_FORBIDS`); the field must belong to a `CONTRACTED` venue
    of the same event (otherwise `ERR_CROSS_EVENT_REFERENCE`, HTTP 409); the
    field must be `AVAILABLE` (otherwise `ERR_FIELD_BLACKED_OUT`, HTTP 409); the
    match's half-open window from `scheduled_start` to `scheduled_end` must not
    overlap the window of any other `SCHEDULED` or `IN_PROGRESS` match on the
    same field — half-open adjacency is allowed, so one match ending exactly
    when another begins is not a conflict (an overlap is
    `ERR_FIELD_TIME_CONFLICT`, HTTP 409); a `scheduled_start` at or after 18:00
    local requires the field's `has_lights` to be true (otherwise
    `ERR_FIELD_NO_LIGHTS`, HTTP 409); and the scheduled date must fall within
    the event's `starts_on` through `ends_on` inclusive (otherwise
    `ERR_MATCH_OUTSIDE_EVENT_DATES`, HTTP 422)."
    PRD §3.6: "A match not currently in `RESCHEDULE_QUEUE` cannot be rescheduled
    this way at all (`ERR_MATCH_NOT_RESCHEDULABLE`, HTTP 409)."
    PRD §3.2: "A contracted venue can later be released to `RELEASED`, but only
    while none of its fields hosts a match in `SCHEDULED`, `WEATHER_DELAYED`,
    `RESCHEDULE_QUEUE`, or `IN_PROGRESS` — a release attempted against active
    matches fails with `ERR_VENUE_HAS_ACTIVE_MATCHES` (HTTP 409)."
    PRD §3.6: "Finalizing records the result: the administrator submits
    `home_score` and `away_score`, both of which must be zero or greater (a
    negative score is `ERR_SCORE_INVALID`, HTTP 422) and which must differ (a
    tie is `ERR_TIE_NOT_ALLOWED`, HTTP 422)."

    Design: Corner/errors/match_scheduling_error_battery_rejected
    """
    ctx = setup_published_bracket(team_ratings=[90, 85, 70, 65], advance_to_live=True)
    by_pos = {(m["round_number"], m["bracket_slot"]): m for m in ctx["matches"]}
    r1m1, r1m2, fin = by_pos[(1, 1)], by_pos[(1, 2)], by_pos[(2, 1)]
    f1 = ctx["field"]["id"]
    # An unlit 60-minute field on the same venue.
    f2 = get_success_data(api.create_field(
        ctx["venue"]["id"], create_field_payload(name="Field 2", surface_type="GRASS",
                                                 has_lights=False, slot_minutes=60), ADMIN))
    # A second event with its own contracted venue + field (foreign field).
    ev2 = create_event(name="Other Cup", host_city="Other City",
                       starts_on="2026-11-01", ends_on="2026-11-03")
    v2 = get_success_data(api.create_venue(ev2["id"], {
        "name": "Other Park", "address": "9 Far Lane",
        "rental_fee_cents": 50000, "revenue_share_pct": 0.10}, ADMIN))
    validate_success(api.contract_venue(v2["id"], {"contract_uri": "s3://contracts/v2.pdf"}, ADMIN))
    f3 = get_success_data(api.create_field(v2["id"], create_field_payload(name="Far Field"), ADMIN))
    # e1: the final has no teams yet.
    resp = api.schedule_match(fin["id"], {"field_id": f1,
                                          "scheduled_start": "2026-10-10T10:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MATCH_TEAMS_INCOMPLETE)
    # e2: 2026-10-20 is beyond the event's ends_on 2026-10-12.
    resp = api.schedule_match(r1m1["id"], {"field_id": f1,
                                           "scheduled_start": "2026-10-20T10:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MATCH_OUTSIDE_EVENT_DATES)
    # e3: F3 belongs to another event.
    resp = api.schedule_match(r1m1["id"], {"field_id": f3["id"],
                                           "scheduled_start": "2026-10-10T10:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CROSS_EVENT_REFERENCE)
    # e4: 19:00 start on the unlit F2.
    resp = api.schedule_match(r1m1["id"], {"field_id": f2["id"],
                                           "scheduled_start": "2026-10-10T19:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FIELD_NO_LIGHTS)
    # e5: F2 blacked out across the morning.
    validate_success(api.blackout_field(f2["id"], {
        "blackout_start": "2026-10-10T00:00:00Z",
        "blackout_end": "2026-10-10T18:00:00Z",
        "reason": "waterlogged",
    }, make_venue_manager_headers(ctx["venue"]["id"])))
    resp = api.schedule_match(r1m1["id"], {"field_id": f2["id"],
                                           "scheduled_start": "2026-10-10T10:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FIELD_BLACKED_OUT)
    # e6: M1 already SCHEDULED.
    validate_success(api.schedule_match(r1m1["id"], {"field_id": f1,
                                                     "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    resp = api.schedule_match(r1m1["id"], {"field_id": f1,
                                           "scheduled_start": "2026-10-11T09:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MATCH_NOT_SCHEDULABLE)
    # e7: M1 is not in RESCHEDULE_QUEUE.
    resp = api.reschedule_match(r1m1["id"], {"field_id": f1,
                                             "scheduled_start": "2026-10-11T09:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MATCH_NOT_RESCHEDULABLE)
    # e8: the venue still hosts scheduled matches.
    validate_success(api.schedule_match(r1m2["id"], {"field_id": f1,
                                                     "scheduled_start": "2026-10-10T16:00:00Z"}, ADMIN))
    resp = api.release_venue(ctx["venue"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_VENUE_HAS_ACTIVE_MATCHES)
    # e9/e10: tie and negative score at finalize; then the valid finalize.
    validate_success(api.start_match(r1m1["id"], ADMIN))
    resp = api.finalize_match(r1m1["id"], {"home_score": 2, "away_score": 2}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TIE_NOT_ALLOWED)
    resp = api.finalize_match(r1m1["id"], {"home_score": -1, "away_score": 0}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SCORE_INVALID)
    finished = validate_success(api.finalize_match(r1m1["id"], {"home_score": 3, "away_score": 1}, ADMIN))
    assert finished["status"] == "FINAL"


def test_official_assignment_error_battery_rejected(api):
    """PRD §3.7: "the official must be `ACTIVE` (otherwise
    `ERR_OFFICIAL_NOT_ACTIVE`, HTTP 409)"
    PRD §3.7: "First, turnover: the candidate match's window, expanded by thirty
    minutes on each side, must not intersect the match window of any of that
    official's `ACCEPTED` or `WORKED` assignments (an intersection is
    `ERR_OFFICIAL_WINDOW_CONFLICT`, HTTP 409)."
    PRD §3.7: "the official must not already hold a non-terminal assignment on
    the same match, and the match must not already have a non-terminal
    `CREW_CHIEF` (violations are `ERR_DUPLICATE_ASSIGNMENT`, HTTP 409)"
    PRD §3.7: "Second, the daily cap: counting the official's `ACCEPTED` and
    `WORKED` assignments whose match `scheduled_start` falls on the same UTC
    calendar date as the candidate match, the proposal is rejected with
    `ERR_OFFICIAL_DAILY_LIMIT` (HTTP 409) when that count already equals or
    exceeds the official's `game_limit_per_day` — reaching exactly the limit is
    allowed, and it is the assignment that would exceed it that is refused."

    Design: Corner/errors/official_assignment_error_battery_rejected
    """
    from test_helpers import api_client as _api
    from test_helpers import make_team_eligible as _mk
    ctx = setup_event_in_registration_open()
    ev_id = ctx["event"]["id"]
    d1 = ctx["division"]
    d2 = create_division(ev_id, name="U18", team_cap=4, min_teams=2,
                         registration_fee_cents=10000)
    d3 = create_division(ev_id, name="U21", team_cap=4, min_teams=2,
                         registration_fee_cents=10000)
    _mk(d1["id"], name="Tigers", contact_email="t@x.com", strength_rating=90)
    _mk(d1["id"], name="Sharks", contact_email="s@x.com", strength_rating=70)
    _mk(d2["id"], name="Wolves", contact_email="w@x.com", strength_rating=85)
    _mk(d2["id"], name="Bears", contact_email="b@x.com", strength_rating=65)
    _mk(d3["id"], name="Foxes", contact_email="f@x.com", strength_rating=80)
    _mk(d3["id"], name="Owls", contact_email="o@x.com", strength_rating=60)
    for d in (d1, d2, d3):
        validate_success(_api.lock_seeding(d["id"], ADMIN))
    advance_posture(ev_id, "COMPETITION_SETUP")
    for d in (d1, d2, d3):
        validate_success(_api.publish_bracket(d["id"], ADMIN))
    m1 = list_division_matches(d1["id"])[0]
    m2 = list_division_matches(d2["id"])[0]
    m3 = list_division_matches(d3["id"])[0]
    # O1 never vetted (stays REGISTERED); O2 NATIONAL with a daily limit of 1.
    o1 = get_success_data(api.create_official(ev_id, {"name": "Rookie Ref",
                                                      "certification_level": "REGIONAL"}, ADMIN))
    o2 = create_active_official(ev_id, name="Nat Ref", certification_level="NATIONAL",
                                game_limit_per_day=1)
    advance_posture(ev_id, "LIVE")
    f1 = ctx["field"]["id"]
    validate_success(api.schedule_match(m1["id"], {"field_id": f1,
                                                   "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    validate_success(api.schedule_match(m2["id"], {"field_id": f1,
                                                   "scheduled_start": "2026-10-10T15:45:00Z"}, ADMIN))
    validate_success(api.schedule_match(m3["id"], {"field_id": f1,
                                                   "scheduled_start": "2026-10-10T18:30:00Z"}, ADMIN))
    # e1: O1 is REGISTERED, not ACTIVE.
    resp = api.create_assignment(m1["id"], {"official_id": o1["id"], "slot_role": "ASSISTANT"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_OFFICIAL_NOT_ACTIVE)
    # O2 as CREW_CHIEF on the M1 final (NATIONAL satisfies the final-round rule).
    a_ok = validate_success(api.create_assignment(
        m1["id"], {"official_id": o2["id"], "slot_role": "CREW_CHIEF"}, ADMIN), expected_status=201)
    validate_success(api.respond_assignment(a_ok["id"], {"response": "ACCEPTED"},
                                            make_official_headers(o2["id"])))
    # e2: M2 15:45 intersects M1's buffered window (13:30-16:00).
    resp = api.create_assignment(m2["id"], {"official_id": o2["id"], "slot_role": "ASSISTANT"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_OFFICIAL_WINDOW_CONFLICT)
    # e3: O2 already holds a non-terminal assignment on M1.
    resp = api.create_assignment(m1["id"], {"official_id": o2["id"], "slot_role": "ASSISTANT"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT)
    # e4: M3 18:30 clears the buffer, but O2 already has 1 ACCEPTED on the date
    # and game_limit_per_day is 1.
    resp = api.create_assignment(m3["id"], {"official_id": o2["id"], "slot_role": "ASSISTANT"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_OFFICIAL_DAILY_LIMIT)


def test_generic_state_and_alert_errors_rejected(api):
    """PRD §3.7: "The official lifecycle runs through `action` values on a
    transition endpoint: `VET` moves `REGISTERED` → `VETTED`; `ACTIVATE` moves
    `VETTED` → `ACTIVE`; ..."
    PRD §3.6: "A `CommissionAdmin` issues an alert with a `severity` of `WATCH`,
    `WARNING`, or `EMERGENCY`, a `window_start`, and a `window_end` strictly
    after the start (otherwise `ERR_ALERT_WINDOW_INVALID`, HTTP 422)..."
    PRD §3.3: "Check-in requires the logical clock's date to be on or after
    `check_in_date` (otherwise `ERR_VALIDATION`) and moves `CONFIRMED` →
    `CHECKED_IN`; check-out moves `CHECKED_IN` → `CHECKED_OUT`."
    PRD §5: `ERR_INVALID_STATE` (409) is the generic state error for a
    transition the entity's state does not permit.

    Design: Corner/errors/generic_state_and_alert_errors_rejected
    """
    from test_helpers import create_hotel_block, create_booking
    ev = create_event()
    o1 = get_success_data(api.create_official(ev["id"], {"name": "Rookie Ref",
                                                         "certification_level": "REGIONAL"}, ADMIN))
    # e1: ACTIVATE from REGISTERED (must pass through VETTED first).
    resp = api.transition_official(o1["id"], {"action": "ACTIVATE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    # e2: window_end before window_start.
    resp = api.create_weather_alert(ev["id"], {
        "severity": "WARNING",
        "window_start": "2026-10-10T18:00:00Z",
        "window_end": "2026-10-10T12:00:00Z",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ALERT_WINDOW_INVALID)
    # e3: CHECK_IN requires CONFIRMED; the booking is RESERVED.
    block = create_hotel_block(ev["id"], contracted=True)
    booking = create_booking(block["id"], rooms_count=1, guest_name="Block A",
                             check_in_date="2026-10-08", check_out_date="2026-10-10")
    resp = api.transition_booking(booking["id"], {"action": "CHECK_IN"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
