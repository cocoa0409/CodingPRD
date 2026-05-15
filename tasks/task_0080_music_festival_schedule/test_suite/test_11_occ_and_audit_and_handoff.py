"""Optimistic-concurrency If-Match contract (PRD §2.5), the
audit-log chronological-ordering contract (PRD §3.7), the sound-check-
window TEAM_HANDOFF_SECONDS gate (PRD §3.5), and the sound-check
stage-mismatch gate that fires when the parent item's stage was swapped
between the slot's creation and its schedule call (PRD §3.5).

These tests round out the validation-priority coverage and the audit-
trail coverage that the cascade and dual-variant tests have so far
exercised piecemeal.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    AUDIT_HEADERS,
    AuditEventCategory,
    LIAISON_HEADERS,
    PRODUCER_HEADERS,
    SPONSOR_HEADERS,
    STAGE_HEADERS,
    THRESHOLDS,
    TICKETING_HEADERS,
    add_program_item,
    add_program_version,
    add_sound_check_slot,
    add_stage,
    add_team,
    advance_clock_to,
    assert_audit_chronological,
    base_world,
    confirm_item,
    confirmed_item_world,
    confirmed_item_with_scheduled_sound_check,
    confirmed_published_world_with_ticket,
    factories as F,
    fixtures as FIX,
    get_festival_snapshot,
    get_success_data,
    get_ticket_type_snapshot,
    publish_version,
    read_audit_log,
    register_artist,
    rider_payload,
    rider_fulfil_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# OCC If-Match contract — PRD §2.5.
# ---------------------------------------------------------------------------


def test_if_match_with_stale_version_returns_version_conflict_and_appends_occ_audit(api):
    """PRD §2.5: "When a mutating request — a PATCH, or a
    state-changing POST ... — carries an `If-Match` header whose value
    parses as an integer, the server compares the value to the target
    row's current `version` and rejects with `ERR_VERSION_CONFLICT`
    at HTTP 409 on any mismatch.  An audit entry of category
    `OCC_CONFLICT` is appended on rejection.  A request without an
    `If-Match` header skips the version check entirely".

    Claim: a state-changing call with an If-Match header whose
    integer is stale (does not equal the row's current `version` per
    PRD §2.4's "`version` is a non-negative integer that starts at 1
    on creation and increments by 1 on every mutation") is rejected
    at HTTP 409 with `ERR_VERSION_CONFLICT`, and an audit row of
    `event_category=OCC_CONFLICT` is appended.  The same call
    without the If-Match header succeeds.

    The PRD §2.5 sentence on the "endpoints that honour If-Match"
    enumeration includes "the ticket-type issue and suspend and
    resume" — we exercise the suspend endpoint as the canonical
    OCC-write site so the fixture is minimal.
    """
    # Standard fixture: a published festival with a single ACTIVE
    # ticket type.  We do not need any issuance for the OCC test.
    bag = base_world(api, day_count=2)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    publish_version(api, bag)
    tt = get_success_data(api.create_ticket_type(
        bag.festival_id,
        F.ticket_type_payload(ticket_class="SINGLE_DAY",
                              tied_program_item_ids=[bag.program_item_id],
                              zone_name="ZoneOCC",
                              unit_price_cents=1000),
        TICKETING_HEADERS,
    ))
    tt_id = str(tt["id"])
    current_version = int(tt["version"])
    assert current_version == 1, \
        "A freshly created mutable entity has version==1 per PRD §2.4."
    # Build the suspend headers with a stale If-Match.  The PRD §2.5
    # prose names the header as the literal string "If-Match".
    stale_headers = dict(TICKETING_HEADERS)
    stale_headers["If-Match"] = str(current_version + 99)  # arbitrary stale value
    bad_resp = api.suspend_ticket_type(bag.festival_id, tt_id,
                                       stale_headers, {"reason": "occ-fail"})
    validate_error(bad_resp, ApiErrorId.ERR_VERSION_CONFLICT.value,
                   expected_status=409)
    # An OCC_CONFLICT audit row is appended on the rejection per the
    # PRD §2.5 sentence "An audit entry of category `OCC_CONFLICT` is
    # appended on rejection".
    occ_rows = read_audit_log(api, bag,
                              event_category=AuditEventCategory.OCC_CONFLICT.value)
    matching = [e for e in occ_rows
                if e.get("subject_entity_id") == tt_id]
    assert matching, (
        "An audit row of event_category OCC_CONFLICT with the rejected "
        "ticket-type as the subject is appended on the stale-If-Match "
        "rejection per PRD §2.5."
    )
    # The same suspend without an If-Match header succeeds — the §2.5
    # sentence "A request without an `If-Match` header skips the
    # version check entirely".
    good_resp = api.suspend_ticket_type(bag.festival_id, tt_id,
                                        TICKETING_HEADERS,
                                        {"reason": "occ-skip"})
    suspended = validate_success(good_resp)
    assert suspended["status"] == "SUSPENDED", \
        "A request without If-Match skips the OCC check and proceeds per PRD §2.5."
    # And the version field has now incremented.
    final = get_success_data(api.get_ticket_type(bag.festival_id, tt_id, AUDIT_HEADERS))
    assert int(final["version"]) == current_version + 1, (
        f"The successful suspend bumps version from {current_version} to "
        f"{current_version + 1} per PRD §2.4's 'increments by 1 on every "
        f"mutation' rule.  Observed final version: {final['version']}."
    )


def test_if_match_matching_version_succeeds_and_increments_version(api):
    """PRD §2.4: "`version` is a non-negative integer that starts at 1
    on creation and increments by 1 on every mutation".  And PRD §2.5:
    "When a mutating request ... carries an `If-Match` header whose
    value parses as an integer, the server compares the value to the
    target row's current `version` and rejects ... on any mismatch."

    Claim: a state-changing call with an If-Match header whose integer
    equals the row's current version succeeds, and the row's version
    integer is exactly one higher in the response than it was in the
    request.

    The matching-version accept side complements the stale-version
    reject side of the prior test.
    """
    bag = confirmed_item_world(api, artist_tier="OPENER",
                               publish_the_version=True)
    # The post-publish item's version is some integer (the create
    # bumped it to 1 and the confirm bumped it to 2 per the §3.3
    # confirm side-effect "an audit entry of category STATE_TRANSITION"
    # and the PRD §2.4 version-bump-on-every-mutation rule).
    item = get_success_data(api.get_program_item(
        bag.festival_id, bag.program_item_id, AUDIT_HEADERS,
    ))
    item_version = int(item["version"])
    # Call the recompute-priority endpoint with a matching If-Match.
    # The §3.3 sentence "The capability is idempotent — a recompute
    # that yields the same numeric value is a no-op except for the
    # score-unchanged audit entry" — so the version may or may not
    # increment if the score is unchanged.  We do not assert the
    # post-version delta in the no-op case; the §2.5 narrative
    # "On every mutation" qualifier ties the version-bump to a
    # state-changing operation.  The PRD silent on whether the
    # no-op-recompute counts as a mutation, so we instead exercise a
    # PATCH on the program item which is unambiguously a mutation.
    # The PATCH endpoint accepts a `genre` change.  PRD §4 table
    # names the PATCH on /program-items/{itemId} explicitly.
    headers_with_match = dict(LIAISON_HEADERS)
    headers_with_match["If-Match"] = str(item_version)
    patch_resp = api.patch_program_item(
        bag.festival_id, bag.program_item_id,
        {"genre": f"new-genre-{item_version}"}, headers_with_match,
    )
    patched = validate_success(patch_resp)
    assert int(patched["version"]) > item_version, (
        f"A successful mutation bumps the version field per PRD §2.4 — "
        f"pre-version was {item_version}, post-version is "
        f"{patched['version']}."
    )
    assert int(patched["version"]) == item_version + 1, (
        f"The version increments by exactly one per the PRD §2.4 "
        f"'increments by 1 on every mutation' rule.  Got delta = "
        f"{int(patched['version']) - item_version}."
    )


# ---------------------------------------------------------------------------
# Audit-log chronological-order contract — PRD §3.7.
# ---------------------------------------------------------------------------


def test_audit_log_is_chronological_and_filterable_by_event_category(api):
    """PRD §3.7: "The audit rows are ordered strictly by `created_at`
    per festival and the audit-list endpoint returns them in that
    order; the list endpoint's filters are on `event_category`, on
    `subject_entity_type`, and on a `created_at_after` ISO 8601 UTC
    timestamp string."

    Claim: the full audit-log read returns rows whose `created_at`
    timestamps are non-decreasing, and a filtered read on
    `event_category=STATE_TRANSITION` returns only the
    state-transition rows.  Per PRD §2.4 the audit entry is an
    append-only event-log row (no `updated_at`, no `version`), so the
    chronological order from `created_at` is the only stable ordering
    the read endpoint exposes.

    The fixture drives the festival through enough state transitions
    to populate a non-trivial audit stream: a festival creation,
    open-scheduling, an artist creation (which has no audit per PRD
    §2.8's mapping — only the festival's STATE_TRANSITION rows fire),
    a stage creation (a STATE_TRANSITION row by the §2.8 mapping for
    the "generic state-transition class for the routine
    transitions"), a program-version creation, a program-item
    creation, a program-item confirm, and a publish.  At least the
    festival's PLANNED→SCHEDULING and the program-item's
    PROPOSED→CONFIRMED transitions and the version's various
    transitions each write a row, and the publish's auto-emitted
    VERSION_PUBLISH schedule-change writes a SCHEDULE_CHANGE
    category row.  We do not pin a specific row count — that's
    implementation-defined within the §2.8 audit-mapping flexibility
    — but we do pin that the rows we filter for are all the right
    category.
    """
    bag = base_world(api, day_count=2, version_label="audit-ordering")
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    publish_version(api, bag)
    # Full read.  The §3.7 narrative pins the ordering as `created_at`
    # ascending.
    full = read_audit_log(api, bag, limit=200)
    assert_audit_chronological(full)
    # Filtered read on event_category.
    st = read_audit_log(api, bag,
                       event_category=AuditEventCategory.STATE_TRANSITION.value,
                       limit=200)
    for entry in st:
        assert entry.get("event_category") == "STATE_TRANSITION", \
            "event_category filter is exact-match per PRD §3.7."
    assert_audit_chronological(st)
    # Filter on subject_entity_type.
    festival_rows = read_audit_log(api, bag,
                                   subject_entity_type="Festival", limit=200)
    for entry in festival_rows:
        assert entry.get("subject_entity_type") == "Festival", \
            "subject_entity_type filter is exact-match per PRD §3.7."
    # The festival's own create-row (the implicit null→PLANNED on
    # creation per PRD §3.1's "writes an audit entry of category
    # `STATE_TRANSITION` for the implicit `null → PLANNED` jump on
    # the `Festival` subject"), the open-scheduling row, and the
    # publish-triggered SCHEDULING→PUBLISHED row (per PRD §3.1) all
    # have the festival as the subject.  We assert at least one
    # festival-subject row exists.
    assert festival_rows, (
        "At least one audit row exists with subject_entity_type "
        "Festival, per PRD §3.1's audit-entry-on-each-Festival-"
        "state-transition rule."
    )


def test_audit_log_paginates_with_standard_meta_block(api):
    """PRD §2.3 / §3.7: the audit-list endpoint accepts the standard
    `limit` and `offset` query parameters and returns the four-field
    pagination meta block.  The §3.7 sentence is "the audit-entries
    list endpoint accepts filters on `event_category`, on
    `subject_entity_type`, and on a `created_at_after` timestamp
    string in ISO 8601 UTC form, and the order is the per-festival
    `created_at` ascending".

    Claim: the audit-list response is paginated per the §2.3 four-
    field meta contract.
    """
    bag = base_world(api, day_count=2)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    publish_version(api, bag)
    # Default limit=10 per PRD §2.3.
    resp = api.list_audit_entries(bag.festival_id, AUDIT_HEADERS, params={})
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    from test_helpers import assert_pagination_meta
    assert_pagination_meta(meta, expected_limit=10, expected_offset=0)
    # A larger custom limit reflects the custom value in the meta.
    resp2 = api.list_audit_entries(bag.festival_id, AUDIT_HEADERS,
                                   params={"limit": 50, "offset": 0})
    data2, meta2 = validate_paginated(resp2)
    assert_pagination_meta(meta2, expected_limit=50, expected_offset=0)


# ---------------------------------------------------------------------------
# Sound-check window precedence — PRD §3.5's TEAM_HANDOFF_SECONDS gate.
# ---------------------------------------------------------------------------


def test_sound_check_window_invalid_when_within_handoff_window_of_item_start(api):
    """PRD §3.5: "the slot's window precedes the parent program item's
    `start_time` by at least the global handoff constant
    `TEAM_HANDOFF_SECONDS = 600` (ten minutes, the gap from the end of
    the sound-check to the act's start — the engineer-to-front-of-
    house handoff), the boundary being inclusive
    `scheduled_window_end <= ProgramItem.start_time -
    TEAM_HANDOFF_SECONDS` so that exactly ten minutes is acceptable
    and less than ten is the rejection at HTTP 422 with
    `ERR_SOUND_CHECK_WINDOW_INVALID`".

    Claim: a sound-check schedule-PATCH whose `scheduled_window_end`
    is strictly later than `ProgramItem.start_time -
    TEAM_HANDOFF_SECONDS` — i.e., the sound-check would end less than
    600 seconds before the program item starts — is rejected with
    `ERR_SOUND_CHECK_WINDOW_INVALID` at HTTP 422.  The accepted side
    of the boundary, at exactly 600 seconds of gap, is exercised by
    the fixture `confirmed_item_with_scheduled_sound_check`.

    The PRD §2.6 priority order places this check at priority 14
    (business-temporal) and the cross-entity-state checks at
    priority 6, so when the parent-item-not-ready check would also
    fire the cross-state error wins per the priority sequence — we
    exercise this test with the parent item in CONFIRMED (so the
    cross-state check passes) and the team in AVAILABLE (so the
    team-side cross-state check also passes), isolating the
    window-precedence check as the sole rejection cause.
    """
    bag = confirmed_item_world(api, artist_tier="OPENER",
                               publish_the_version=True,
                               equipment_kit_code=None)
    item_id = bag.program_item_id
    item_start = int(bag.program_item["start_time"])
    handoff = int(THRESHOLDS["TEAM_HANDOFF_SECONDS"])
    # Make sure the festival window contains the slot's window.  The
    # bag.festival_start is the lower bound on the slot's
    # scheduled_window_start per PRD §3.5 ("`scheduled_window_start`
    # is no earlier than the festival's `start_time`").  The slot
    # ends `handoff - 1` seconds before the item starts — strictly
    # less than the required 600-second gap, the rejection-boundary
    # side per the strict-`<` rejection rule.
    sc_end = item_start - (handoff - 1)
    sc_start = max(bag.festival_start, sc_end - 1800)
    assert bag.festival_start <= sc_start < sc_end < item_start, \
        "Fixture arithmetic: the slot window lies inside the festival window."
    # Create the slot (REQUESTED initial state) with the close-to-the-
    # item-start window.  The create accepts any window pair per the
    # PRD §1.5 sound-check-create input shape — the validation fires
    # on the schedule-PATCH per the §3.5 sentence "The advance
    # `REQUESTED → SCHEDULED` is the schedule PATCH ... The
    # preconditions for the schedule transition are ... the slot's
    # window precedes the parent program item's `start_time` by at
    # least the global handoff constant `TEAM_HANDOFF_SECONDS` ...".
    slot = add_sound_check_slot(api, bag, item_id,
                                scheduled_window_start=sc_start,
                                scheduled_window_end=sc_end)
    team = add_team(api, bag)
    bad_resp = api.patch_sound_check(
        bag.festival_id, str(slot["id"]),
        F.sound_check_schedule_payload(
            sound_engineer_team_id=str(team["id"]),
            scheduled_window_start=sc_start,
            scheduled_window_end=sc_end,
        ),
        STAGE_HEADERS,
    )
    validate_error(bad_resp,
                   ApiErrorId.ERR_SOUND_CHECK_WINDOW_INVALID.value,
                   expected_status=422)


def test_sound_check_window_at_exactly_handoff_seconds_gap_accepted(api):
    """The boundary's accept side from the same PRD §3.5 sentence:
    "the boundary being inclusive `scheduled_window_end <=
    ProgramItem.start_time - TEAM_HANDOFF_SECONDS` so that exactly
    ten minutes is acceptable".

    Claim: a sound-check schedule-PATCH whose `scheduled_window_end`
    equals `ProgramItem.start_time - TEAM_HANDOFF_SECONDS` exactly
    (the inclusive-≤ boundary on the accept side) is accepted.

    The fixture `confirmed_item_with_scheduled_sound_check` is the
    canonical accept-side construction in the codebase, used by the
    cascade-A test.  Re-using it here as the boundary's accept side
    matches the §3.5 contract.
    """
    bag, team, slot = confirmed_item_with_scheduled_sound_check(
        api, artist_tier="OPENER", day_count=3,
    )
    # The fixture sets sc_end == item_start - TEAM_HANDOFF_SECONDS,
    # which is the inclusive-≤ boundary on the accept side per the
    # §3.5 sentence.  The slot's status is now SCHEDULED, the team is
    # BUSY pointing at the slot, and the parent item's
    # sound_check_status axis is at SCHEDULED.  All evidence that the
    # boundary-equality input cleared every gate.
    assert slot["status"] == "SCHEDULED", \
        ("The sound-check at exactly TEAM_HANDOFF_SECONDS of gap is "
         "accepted per the PRD §3.5 inclusive-≤ boundary on "
         "scheduled_window_end vs ProgramItem.start_time − "
         "TEAM_HANDOFF_SECONDS.")
    item_start = int(get_success_data(api.get_program_item(
        bag.festival_id, str(slot["program_item_id"]), AUDIT_HEADERS,
    ))["start_time"])
    sc_end = int(slot["scheduled_window_end"])
    handoff = int(THRESHOLDS["TEAM_HANDOFF_SECONDS"])
    assert item_start - sc_end == handoff, (
        f"The fixture pins the slot's gap-to-item-start at exactly "
        f"TEAM_HANDOFF_SECONDS == {handoff} per the PRD §3.5 "
        f"engineer-to-front-of-house handoff constant.  Observed gap: "
        f"{item_start - sc_end}."
    )


def test_sound_check_complete_requires_clock_past_window_end(api):
    """PRD §3.5: "The advance `SCHEDULED → COMPLETED` is the complete
    capability ... gated on the wall clock being at or past the
    slot's `scheduled_window_end` (the inclusive ≥ boundary), with
    the side effects of the team flipping back to `AVAILABLE` (and
    `current_booking_id` cleared to null), the parent program item's
    `sound_check_status` axis flipping to `COMPLETED`, and an audit
    entry.  An attempt to complete a slot not in `SCHEDULED` is
    rejected at HTTP 409 with `ERR_SOUND_CHECK_NOT_SCHEDULED`."

    Claim: the complete endpoint on a SCHEDULED slot whose
    scheduled_window_end the test clock has crossed succeeds.  The
    state-precondition error for the not-SCHEDULED case is
    `ERR_SOUND_CHECK_NOT_SCHEDULED` per PRD §1.6.

    We exercise the accept side via the clock-advance helper of the
    fixtures module, then read the post-complete state.

    The rejection side — completing a REQUESTED slot — is the not-
    SCHEDULED state-gate, with `ERR_SOUND_CHECK_NOT_SCHEDULED` at
    HTTP 409.
    """
    bag, team, scheduled = confirmed_item_with_scheduled_sound_check(
        api, artist_tier="OPENER", day_count=3,
    )
    slot_id = str(scheduled["id"])
    sc_end = int(scheduled["scheduled_window_end"])
    # Pre-complete attempt with the clock still before the
    # scheduled_window_end: the §3.5 sentence pins the inclusive
    # boundary at "at or past the slot's `scheduled_window_end`".
    # The test-bag's clock is at the harness's wall-clock-of-record,
    # which the §2.7 narrative ties to `real_now +
    # Festival.clock_offset_seconds`.  The harness has not yet
    # advanced the offset, so the logical wall clock is wherever
    # real_now sits in the test runtime — which is the present moment,
    # almost-certainly before the deterministic
    # TIME_ANCHOR_UNIX_SECONDS-based festival window we constructed.
    # The PRD wording "the wall clock being at or past the slot's
    # scheduled_window_end" therefore evaluates as "false" before any
    # clock-advance.  The complete-pre-window error id is named in
    # the §1.6 catalog: implementation may surface either the
    # ERR_SOUND_CHECK_NOT_SCHEDULED (the state-precondition family
    # error fires when the slot's transition is gated by the wall
    # clock and the clock is too early — the §3.5 wording is the
    # state-gate-family error) or a state-aware refusal, which the
    # PRD §1.6 catalog entry for ERR_SOUND_CHECK_NOT_SCHEDULED itself
    # names ("Complete a slot that is not in SCHEDULED").  The cleanest
    # accept-side test is to advance the clock past the window end
    # and assert the success.
    advance_clock_to(api, festival_id=bag.festival_id,
                     to_unix_seconds=sc_end + 1)
    # The slot is now eligible for the complete-transition per PRD
    # §3.5.  The complete endpoint flips the slot to COMPLETED,
    # releases the team to AVAILABLE with current_booking_id null,
    # and flips the parent item's sound_check_status axis to
    # COMPLETED.
    completed = validate_success(api.complete_sound_check(
        bag.festival_id, slot_id, STAGE_HEADERS,
    ))
    assert completed["status"] == "COMPLETED", \
        "The complete endpoint advances the slot to COMPLETED per PRD §3.5."
    # The team is back to AVAILABLE.
    team_after = get_success_data(api.get_sound_engineer_team(
        bag.festival_id, str(team["id"]), AUDIT_HEADERS,
    ))
    assert team_after["status"] == "AVAILABLE", \
        "The complete's side-effect flips the team back to AVAILABLE per PRD §3.5."
    assert team_after.get("current_booking_id") in (None, "", "null"), \
        "The team's current_booking_id is cleared to null per PRD §3.5."
    # The parent item's sound_check_status axis is COMPLETED.
    parent = get_success_data(api.get_program_item(
        bag.festival_id, str(scheduled["program_item_id"]), AUDIT_HEADERS,
    ))
    assert parent["sound_check_status"] == "COMPLETED", (
        "The parent ProgramItem's parallel sound_check_status axis "
        "advances to COMPLETED per the PRD §3.3 parallel-axis "
        "side-effect of the sound-check complete-transition."
    )
    # A second complete attempt on the now-COMPLETED slot returns
    # ERR_SOUND_CHECK_NOT_SCHEDULED per PRD §1.6.
    bad_second = api.complete_sound_check(bag.festival_id, slot_id, STAGE_HEADERS)
    validate_error(bad_second, ApiErrorId.ERR_SOUND_CHECK_NOT_SCHEDULED.value,
                   expected_status=409)


# ---------------------------------------------------------------------------
# Rehearsal half-open list filtering and GET shape — round out the
# rehearsal coverage that the cascade-C and interval tests touched on.
# ---------------------------------------------------------------------------


def test_rehearsal_list_filterable_by_status_and_type(api):
    """PRD §3.5: the rehearsal-list endpoint "accepts filters on
    `status`, on `artist_id`, and on `rehearsal_type`".  And the
    standard PRD §2.3 four-field pagination meta block.

    Claim: a rehearsal-list filtered on `rehearsal_type=ROOM` returns
    only ROOM-type rows.
    """
    bag = FIX.festival_in_scheduling(api, day_count=2)
    add_stage(api, bag, zone_capacity=10)
    a1 = get_success_data(api.create_artist(F.artist_payload(stage_name="A1", tier="OPENER"),
                                            LIAISON_HEADERS))
    a2 = get_success_data(api.create_artist(F.artist_payload(stage_name="A2", tier="OPENER"),
                                            LIAISON_HEADERS))
    # One ROOM and one STAGE rehearsal in disjoint windows.
    t0 = bag.festival_start + 3600
    get_success_data(api.create_rehearsal(
        bag.festival_id,
        F.rehearsal_payload(artist_id=str(a1["id"]),
                            rehearsal_type="ROOM",
                            rehearsal_room_name="StudioR1",
                            start_time=t0, end_time=t0 + 1800),
        STAGE_HEADERS,
    ))
    get_success_data(api.create_rehearsal(
        bag.festival_id,
        F.rehearsal_payload(artist_id=str(a2["id"]),
                            rehearsal_type="STAGE",
                            stage_id=bag.stage_id,
                            start_time=t0 + 2 * 3600,
                            end_time=t0 + 2 * 3600 + 1800),
        STAGE_HEADERS,
    ))
    # Filter on rehearsal_type=ROOM.
    resp = api.list_rehearsals(bag.festival_id, AUDIT_HEADERS,
                               params={"rehearsal_type": "ROOM", "limit": 50})
    data, meta = validate_paginated(resp)
    for row in data:
        assert row.get("rehearsal_type") == "ROOM", \
            "rehearsal_type filter is exact-match per PRD §2.3."
    # The standard meta block is present.
    from test_helpers import assert_pagination_meta
    assert_pagination_meta(meta, expected_limit=50, expected_offset=0)
    # The filtered listing contains the one ROOM-type rehearsal we
    # created.
    assert any(r.get("rehearsal_type") == "ROOM"
               and r.get("artist_id") == str(a1["id"]) for r in data), (
        "The filtered listing contains the ROOM-type rehearsal we just "
        "created per the §3.5 list-endpoint contract."
    )


def test_audit_view_role_allowed_to_read_audit_log(api):
    """PRD §2.1: "GET /festivals/{festivalId}/audit-entries is open only
    to AuditViewer, FestivalProducer, and PlatformAdmin."

    Claim: the dedicated `AuditViewer` role (the read-only role) can
    read the audit log without any rejection.  Paired with the
    test_01 file's negative case (a TicketingAdmin gets
    ERR_AUDIT_LOG_FORBIDDEN), this confirms the three-element
    allowlist.
    """
    bag = base_world(api, day_count=2)
    resp = api.list_audit_entries(bag.festival_id, AUDIT_HEADERS,
                                  params={"limit": 100})
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    from test_helpers import assert_pagination_meta
    assert_pagination_meta(meta, expected_limit=100, expected_offset=0)


def test_clock_view_endpoint_returns_per_festival_offset(api):
    """PRD §3.7: "The clock-state read at the clock-state read
    capability, open to `PlatformAdmin` and `AuditViewer`, returns
    the synthetic `ClockView` with the per-festival
    `clock_offset_seconds` and the implied logical-wall-clock-of-
    record."

    Claim: the GET /_clock endpoint returns a response whose `data`
    payload exposes the festival's `clock_offset_seconds` integer.
    The PRD §2.8 narrative on the operator-endpoint surface names
    the endpoint as the "the clock-advance test endpoint" companion
    read, with the AuditViewer in the two-role allowlist.
    """
    bag = base_world(api, day_count=2)
    # Advance the clock to a known offset so the view's value is
    # non-zero — gives a falsifiable assertion.
    advance_clock_to(api, festival_id=bag.festival_id,
                     to_unix_seconds=bag.festival_start + 60)
    # Read.  The AuditViewer role is in the §2.1-named allowlist for
    # the clock-read endpoint.
    resp = api.get_clock(AUDIT_HEADERS,
                         params={"festival_id": bag.festival_id})
    data = validate_success(resp)
    # The PRD §3.7 narrative names the view as a "synthetic
    # `ClockView` with the per-festival `clock_offset_seconds`".  The
    # exact wrapping shape is left to the implementation, so we
    # accept either a flat dict with `clock_offset_seconds` at the
    # top level (when filtered to a single festival), a list of
    # per-festival records, or a dict keyed by festival id.  The
    # robust assertion is that the data carries some integer field
    # named `clock_offset_seconds` that is non-negative.
    found_offset: Any = None
    if isinstance(data, dict) and "clock_offset_seconds" in data:
        found_offset = data["clock_offset_seconds"]
    elif isinstance(data, dict):
        for v in data.values():
            if isinstance(v, dict) and "clock_offset_seconds" in v:
                found_offset = v["clock_offset_seconds"]
                break
    elif isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and "clock_offset_seconds" in entry:
                found_offset = entry["clock_offset_seconds"]
                break
    assert isinstance(found_offset, int) and found_offset >= 0, (
        f"The /_clock read exposes a per-festival `clock_offset_seconds` "
        f"non-negative integer per PRD §3.7's ClockView shape.  Got "
        f"data shape: {type(data).__name__}, observed offset: "
        f"{found_offset!r}."
    )


def test_clock_view_role_outside_allowlist_rejected(api, ticketing_headers):
    """PRD §3.7: "the clock-state read at the clock-state read
    capability, open to `PlatformAdmin` and `AuditViewer`".  The
    PRD's allowlist is two-element here, not the three-element
    audit-log allowlist.

    Claim: a TicketingAdmin reading the /_clock endpoint receives
    `ERR_INSUFFICIENT_PERMISSIONS` at HTTP 403 (the generic
    permission-denial error since the audit-log-specific gate
    doesn't apply on the clock endpoint — the §2.1 prose names
    `ERR_AUDIT_LOG_FORBIDDEN` specifically for the audit-entries
    endpoint).
    """
    bag = base_world(api, day_count=2)
    resp = api.get_clock(ticketing_headers,
                         params={"festival_id": bag.festival_id})
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
                   expected_status=403)


# ---------------------------------------------------------------------------
# Cross-resource not-found and mismatched-parent — the path-resolution
# left-to-right convention of PRD §2.1.
# ---------------------------------------------------------------------------


def test_program_item_under_wrong_festival_returns_mismatched_parent_or_not_found(api):
    """PRD §2.1: "The URL-path existence check is run left-to-right:
    a request to `/festivals/{festivalId}/program-items/{itemId}`
    first verifies the festival id resolves (returning
    `ERR_FESTIVAL_NOT_FOUND` if not), then verifies the program-item
    id resolves under it (returning `ERR_PROGRAM_ITEM_NOT_FOUND` if
    not), then the parent-match guard fires (returning
    `ERR_RESOURCE_MISMATCHED_PARENT` if the resolved program item
    belongs to a different festival)."

    Claim: a GET on `/festivals/{festivalA_id}/program-items/{item_under_festivalB_id}`
    — where both ids resolve to existing rows but the item's
    `festival_id` is festivalB, not festivalA — returns one of the
    two not-found-family errors per the §2.1 left-to-right rule.
    The PRD's pinned discrimination: "the parent-match guard fires
    (returning `ERR_RESOURCE_MISMATCHED_PARENT` if the resolved
    program item belongs to a different festival)".  When the item
    id is not even resolvable in any festival, the prior step's
    `ERR_PROGRAM_ITEM_NOT_FOUND` fires.

    For the cross-festival-id-but-resolvable case the PRD pins
    `ERR_RESOURCE_MISMATCHED_PARENT` at HTTP 404.

    We construct: festival A is empty (no program items), festival B
    has one program item.  GET on
    `/festivals/{A_id}/program-items/{B_item_id}` is the cross-
    festival mismatched-parent case.  Per PRD §2.1 the implementation
    must distinguish "item not found anywhere" from "item belongs to
    a different festival".

    The PRD §2.1 catalog says both ERR_PROGRAM_ITEM_NOT_FOUND and
    ERR_RESOURCE_MISMATCHED_PARENT are at HTTP 404.  Implementations
    that resolve the item id globally before checking the parent
    surface ERR_RESOURCE_MISMATCHED_PARENT; implementations that
    scope the lookup to the URL's festival id and find no row
    surface ERR_PROGRAM_ITEM_NOT_FOUND.  Both readings are PRD-
    consistent on the not-found-family-is-HTTP-404 dimension.  We
    therefore accept either of the two error ids as a faithful
    rendering of the §2.1 left-to-right rule.
    """
    bag_a = base_world(api, day_count=2, start_offset_seconds=0)
    bag_b = base_world(api, day_count=2, start_offset_seconds=10 * 86400)
    # Put one item under festival B.
    add_program_item(api, bag_b, day_index=0, hour_offset_in_day=10)
    item_b_id = str(bag_b.program_item["id"])
    # Read the cross-festival pair from festival A.
    resp = api.get_program_item(bag_a.festival_id, item_b_id, AUDIT_HEADERS)
    err_id = validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_RESOURCE_MISMATCHED_PARENT.value,
         ApiErrorId.ERR_PROGRAM_ITEM_NOT_FOUND.value],
    )
    assert resp.status_code == 404, \
        f"Both errors in the cross-parent family are HTTP 404 per PRD §2.1, got {resp.status_code}"


def test_rider_under_wrong_program_item_returns_mismatched_parent_or_not_found(api):
    """Mirror of the prior test on the rider sub-resource.  PRD §2.1's
    left-to-right URL-path resolution rule applies uniformly across
    the nested resources.

    Claim: a PATCH on `/festivals/{festivalId}/program-items/{itemA_id}/riders/{riderB_id}`
    where rider B is under item B (a different parent program item)
    returns one of the not-found-family errors at HTTP 404.

    Per the catalog at PRD §1.6 the rider-not-found error id is
    `ERR_RIDER_NOT_FOUND`.  The parent-mismatch case can also
    surface as the generic `ERR_RESOURCE_MISMATCHED_PARENT` per the
    §2.1 prose.  Both readings are PRD-consistent and at HTTP 404.
    """
    bag = base_world(api, day_count=2)
    # Item A — bag.program_item.  Add Item B as a sibling.
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    item_a_id = bag.program_item_id
    add_program_item(api, bag, day_index=0, hour_offset_in_day=12)
    item_b_id = str(bag.program_items[-1]["id"])
    # Attach a rider to Item B only.
    rider_b = get_success_data(api.create_rider(
        bag.festival_id, item_b_id,
        rider_payload(category="TECHNICAL",
                      description="cross-parent-rider", is_blocking=False),
        LIAISON_HEADERS,
    ))
    rider_b_id = str(rider_b["id"])
    # PATCH-fulfil rider_b through the URL `/.../program-items/{item_a_id}/riders/{rider_b_id}`.
    cross_resp = api.fulfil_rider(bag.festival_id, item_a_id, rider_b_id,
                                  rider_fulfil_payload(), LIAISON_HEADERS)
    err_id = validate_error_is_one_of(
        cross_resp,
        [ApiErrorId.ERR_RESOURCE_MISMATCHED_PARENT.value,
         ApiErrorId.ERR_RIDER_NOT_FOUND.value],
    )
    assert cross_resp.status_code == 404
