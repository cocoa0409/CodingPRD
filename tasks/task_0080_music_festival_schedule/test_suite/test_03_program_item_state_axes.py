"""ProgramItem state machine — the two parallel axes (the lifecycle axis
PROPOSED → CONFIRMED → ANNOUNCED → ON_STAGE → PERFORMED with a CANCELLED
branch, and the independent sound-check axis NOT_REQUIRED → REQUESTED →
SCHEDULED → COMPLETED with a WAIVED absorbing terminal).

The PRD §3.3 prose names the entity as carrying both axes on the same
row, with synchronisation only at the announce-precondition that gates
non-headliner announcements on the sound-check axis being in
{COMPLETED, WAIVED, NOT_REQUIRED}.  The HEADLINER carve-out lets a
headliner announce while its sound-check is still REQUESTED or
SCHEDULED, as the PRD §3.3 narrative spells out.

Difficulty rule 3 instance B: the parallel-axes shape on the ProgramItem
entity is one of the three non-linear-state-machine instances, and the
PRD's announce-time cross-axis gate is the synchronisation point the
test fixture exercises.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    AuditEventCategory,
    ArtistTier,
    add_program_item,
    advance_clock_to,
    base_world,
    confirm_item,
    confirmed_item_world,
    get_success_data,
    get_festival_snapshot,
    publish_version,
    PRODUCER_HEADERS,
    LIAISON_HEADERS,
    STAGE_HEADERS,
    AUDIT_HEADERS,
    rider_payload,
    rider_fulfil_payload,
    waive_sound_check_payload,
    register_artist,
    THRESHOLDS,
    validate_error,
    validate_success,
    assert_program_item_shape,
    assert_audit_contains,
    read_audit_log,
    factories as F,
)


# ---------------------------------------------------------------------------
# Lifecycle: PROPOSED → CONFIRMED  on an item under a still-DRAFT version
# (the pre-publish carve-out) and on an item under the festival's pinned
# current version (the post-publish gate).  PRD §3.3 narrative spells out
# the cross-state guard with `ERR_PROGRAM_VERSION_SUPERSEDED`.
# ---------------------------------------------------------------------------


def test_confirm_program_item_advances_proposed_to_confirmed(api):
    """PRD §3.3: "The advance from `PROPOSED` to `CONFIRMED` is the
    `confirm` capability the artist-liaison ... exercises through the
    confirm endpoint with an optional `If-Match` header."

    Claim: a fresh PROPOSED item under a still-DRAFT version (the
    pre-first-publish carve-out where "before any version has yet
    published the gate is relaxed to 'the `program_version_id`
    references a non-`WITHDRAWN`-non-`SUPERSEDED` version under the
    festival'") confirms cleanly and the response carries status
    CONFIRMED.  A STATE_TRANSITION audit row is appended.
    """
    bag = base_world(api, day_count=2)
    item = add_program_item(api, bag, day_index=0, hour_offset_in_day=12)
    item_id = str(item["id"])
    resp = api.confirm_program_item(bag.festival_id, item_id, LIAISON_HEADERS)
    data = validate_success(resp)
    assert_program_item_shape(data)
    assert data["status"] == "CONFIRMED", \
        "Confirm advances the lifecycle axis from PROPOSED to CONFIRMED per PRD §3.3"
    # The slot_priority_score is recomputed as a side-effect of confirm
    # per the §3.3 sentence "The side effect of a successful confirm is
    # the recomputation of `slot_priority_score` and an audit entry of
    # category `STATE_TRANSITION`".
    assert isinstance(data["slot_priority_score"], (int, float)), \
        "slot_priority_score is a number on the confirmed item per PRD §3.5"
    entries = read_audit_log(api, bag,
                             event_category=AuditEventCategory.STATE_TRANSITION.value,
                             subject_entity_type="ProgramItem")
    assert any(e.get("subject_entity_id") == item_id and e.get("to_state") == "CONFIRMED"
               for e in entries), \
        "A STATE_TRANSITION audit row with to_state==CONFIRMED is appended per PRD §3.3"


def test_confirm_then_announce_on_non_headliner_requires_sound_check_terminal(api):
    """PRD §3.3: "the cross-entity gate between the lifecycle axis and
    the sound-check axis is the rule that says a non-headliner cannot
    announce while its `sound_check_status` is in the set `REQUESTED`
    or `SCHEDULED` (the sound-check is in flight and the
    audience-facing announcement would be premature); a headliner is
    granted a carve-out from that gate because the headliner's
    announcement is what drives the bulk of late ticket sales".  And:
    "the announce is allowed when the headliner's sound_check_status
    is in `COMPLETED` or `WAIVED` or `NOT_REQUIRED`, and the carve-out
    adds the `REQUESTED` and `SCHEDULED` states to the allowed set
    when and only when the artist's tier is `HEADLINER`. When the gate
    rejects, the error id is the cross-entity-state error
    `ERR_PARENT_ITEM_NOT_READY` at HTTP 409".

    Claim: a non-HEADLINER (OPENER) item with an active sound-check
    slot (status REQUESTED on the parallel axis after the sound-check
    is created) cannot announce until the sound-check axis lands on
    one of the terminal-or-non-required states; the rejection is
    `ERR_PARENT_ITEM_NOT_READY` at HTTP 409.  The same item with the
    sound-check waived (axis flipped to WAIVED via the waive endpoint
    per PRD §3.3) announces cleanly.

    The HEADLINER-carve-out is asserted by the next test.

    # difficulty: non_linear_state_machine/program_item_parallel_lifecycle_and_soundcheck_axes
    """
    # An OPENER artist so the cardinality-minimum-on-blocking-riders
    # gate (HEADLINER_MIN_BLOCKING_RIDERS=1) does not apply per PRD
    # §3.3 — non-HEADLINER tiers have a required-blocking minimum of 0.
    bag = base_world(api, day_count=3, artist_tier="OPENER",
                     stage_zone_capacity=10)
    add_program_item(api, bag, day_index=1, hour_offset_in_day=14,
                     duration_seconds=3600)
    item_id = str(bag.program_item["id"])
    confirm_item(api, bag, item_id)
    # Festival publish so the announce step's
    # ERR_FESTIVAL_NOT_PUBLISHED guard (PRD §3.3 "The parent festival's
    # status must be exactly `PUBLISHED` for an announcement to be
    # legal") doesn't fire.
    publish_version(api, bag)
    # Create a sound-check slot under the item.  PRD §3.3: "The slot's
    # initial status on create is `REQUESTED`" and "the parent
    # ProgramItem's `sound_check_status` axis [is] set to `REQUESTED` as
    # a side effect of the first sound-check-slot creation on the
    # item".
    # The slot's window must precede the item's start by at least
    # TEAM_HANDOFF_SECONDS (PRD §3.5), but the slot's window can be
    # left unspecified on the create per PRD §1.5 (the times default to
    # null at create and are supplied on the schedule PATCH).
    item_start = int(bag.program_item["start_time"])
    sc_end = item_start - int(THRESHOLDS["TEAM_HANDOFF_SECONDS"]) - 60
    sc_start = sc_end - 1800
    sc_resp = api.create_sound_check(
        bag.festival_id, item_id,
        F.sound_check_create_payload(scheduled_window_start=sc_start,
                                     scheduled_window_end=sc_end),
        STAGE_HEADERS,
    )
    get_success_data(sc_resp)
    # The item's sound_check_status is now REQUESTED — read the
    # post-create item state to confirm before attempting the
    # announce.
    item_after_sc = get_success_data(
        api.get_program_item(bag.festival_id, item_id, AUDIT_HEADERS)
    )
    assert item_after_sc["sound_check_status"] == "REQUESTED", \
        ("The first sound-check-slot creation side-effects the parent item's "
         "sound_check_status axis to REQUESTED per PRD §3.3.")
    # The announce is rejected because the artist is OPENER (not
    # HEADLINER) and the sound-check axis is in REQUESTED, which is in
    # the disallowed set for non-headliners per PRD §3.3.
    bad = api.announce_program_item(bag.festival_id, item_id, LIAISON_HEADERS)
    validate_error(bad, ApiErrorId.ERR_PARENT_ITEM_NOT_READY.value,
                   expected_status=409)
    # Waive the sound-check axis — the PRD §3.3 sentence "the
    # sound-check-waive capability ... flips the parallel
    # `sound_check_status` axis to `WAIVED` from whichever of
    # `NOT_REQUIRED` or `REQUESTED` it currently sits in" — and retry
    # the announce.
    waive_resp = api.waive_sound_check(bag.festival_id, item_id,
                                       waive_sound_check_payload(reason="test-waive"),
                                       STAGE_HEADERS)
    waived_item = get_success_data(waive_resp)
    assert waived_item["sound_check_status"] == "WAIVED", \
        "Waive flips sound_check_status to WAIVED per PRD §3.3"
    good = api.announce_program_item(bag.festival_id, item_id, LIAISON_HEADERS)
    announced = validate_success(good)
    assert announced["status"] == "ANNOUNCED", \
        ("After the sound-check is waived, the announce-time cross-axis gate "
         "no longer fires per PRD §3.3, and the lifecycle axis advances to "
         "ANNOUNCED.")


def test_headliner_carve_out_allows_announce_with_sound_check_in_requested(api):
    """PRD §3.3: "a headliner is granted a carve-out from that gate
    because the headliner's announcement is what drives the bulk of
    late ticket sales, and so a headliner may announce even with its
    sound-check still in `REQUESTED` or `SCHEDULED`.  The carve-out is
    symmetric across both directions: the announce is allowed when
    the headliner's sound_check_status is in `COMPLETED` or `WAIVED`
    or `NOT_REQUIRED`, and the carve-out adds the `REQUESTED` and
    `SCHEDULED` states to the allowed set when and only when the
    artist's tier is `HEADLINER`."

    Also: "a headliner-specific cardinality minimum ... when the
    artist's `tier` is `HEADLINER`, the total count of blocking
    riders on the item must be at least the constant
    `HEADLINER_MIN_BLOCKING_RIDERS = 1`".

    Claim: a HEADLINER item with one fulfilled blocking rider and an
    active REQUESTED sound-check axis can announce.  The pinning is
    on the carve-out's "allowed set" of {COMPLETED, WAIVED,
    NOT_REQUIRED, REQUESTED, SCHEDULED}.

    # difficulty: non_linear_state_machine/program_item_parallel_lifecycle_and_soundcheck_axes
    """
    bag = base_world(api, day_count=3, artist_tier="HEADLINER",
                     stage_zone_capacity=10)
    add_program_item(api, bag, day_index=1, hour_offset_in_day=14,
                     duration_seconds=3600)
    item_id = str(bag.program_item["id"])
    # Add one blocking rider and fulfil it — the headliner's cardinality
    # minimum of one is satisfied per PRD §3.3.
    r = get_success_data(api.create_rider(
        bag.festival_id, item_id,
        rider_payload(is_blocking=True, category="HOSPITALITY",
                      description="green-room blocker"),
        LIAISON_HEADERS,
    ))
    get_success_data(api.fulfil_rider(
        bag.festival_id, item_id, str(r["id"]),
        rider_fulfil_payload(), LIAISON_HEADERS,
    ))
    confirm_item(api, bag, item_id)
    publish_version(api, bag)
    # Sound-check slot — the headliner's sound_check axis lands in
    # REQUESTED after this create call per the §3.3 side-effect line.
    item_start = int(bag.program_item["start_time"])
    sc_end = item_start - int(THRESHOLDS["TEAM_HANDOFF_SECONDS"]) - 60
    sc_start = sc_end - 1800
    get_success_data(api.create_sound_check(
        bag.festival_id, item_id,
        F.sound_check_create_payload(scheduled_window_start=sc_start,
                                     scheduled_window_end=sc_end),
        STAGE_HEADERS,
    ))
    # The carve-out applies: the headliner can announce while the
    # sound-check axis is still in REQUESTED.
    announced = validate_success(
        api.announce_program_item(bag.festival_id, item_id, LIAISON_HEADERS)
    )
    assert announced["status"] == "ANNOUNCED", \
        ("HEADLINER carve-out per PRD §3.3 admits the announce while the "
         "sound-check axis is in REQUESTED.")
    assert announced["announcement_sync_state"] in {"QUEUED", "PENDING", "ACKED", "FAILED"}, \
        "announcement_sync_state is one of the four PRD §3.3 enum values"


def test_confirm_on_non_proposed_item_returns_state_gate_error(api):
    """PRD §2.6 priority-5 state gate: "the family ...
    `ERR_PROGRAM_ITEM_NOT_PROPOSED`" — the confirm endpoint requires the
    item to be in PROPOSED.

    Claim: a second confirm call on an item that is already CONFIRMED
    is rejected with `ERR_PROGRAM_ITEM_NOT_PROPOSED` at HTTP 409.
    """
    bag = confirmed_item_world(api, artist_tier="OPENER",
                               publish_the_version=False)
    item_id = str(bag.program_item["id"])
    # The item is already CONFIRMED.  A second confirm is the
    # state-gate-rejection case the §2.6 priority-5 narrative names.
    resp = api.confirm_program_item(bag.festival_id, item_id, LIAISON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_ITEM_NOT_PROPOSED.value,
                   expected_status=409)


def test_announce_on_non_confirmed_item_returns_state_gate_error(api):
    """PRD §2.6 priority-5: "the family ... `ERR_PROGRAM_ITEM_NOT_CONFIRMED`".

    Claim: an announce call on a PROPOSED item (one that has not been
    confirmed yet) is rejected with `ERR_PROGRAM_ITEM_NOT_CONFIRMED` at
    HTTP 409.
    """
    bag = base_world(api, day_count=2, artist_tier="OPENER")
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    publish_version(api, bag)  # the parent festival is PUBLISHED so the
                                # ERR_FESTIVAL_NOT_PUBLISHED gate doesn't
                                # also fire.
    # The item is still in PROPOSED — we never called confirm on it,
    # we just published a different version.  Wait, publish_version
    # snapshots the version's program_item_ids at publish time per
    # PRD §3.3, and the item we created was attached to the version,
    # so it does land in the snapshot.  The item's own status is still
    # PROPOSED because we never hit the confirm endpoint.
    # We need to re-add a fresh PROPOSED item under the now-PUBLISHED
    # version so the parent-version-superseded gate (the version-pin
    # cross-entity-state gate of §3.3) doesn't fire.  Per PRD §3.3 the
    # cross-state "the item's `program_version_id` must equal the
    # parent festival's `current_program_version_id`" applies after the
    # first publish; the item's program_version_id was set to the bag's
    # original DRAFT version at create-time, which has now become the
    # festival's pinned current version — so the gate passes.
    item_id = str(bag.program_item["id"])
    resp = api.announce_program_item(bag.festival_id, item_id, LIAISON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_ITEM_NOT_CONFIRMED.value,
                   expected_status=409)


def test_announce_headliner_with_zero_blocking_riders_rejected(api):
    """PRD §3.3 / §3.5: "the `blocking_rider_minimum_check`: when the
    artist's `tier` is `HEADLINER`, the total count of blocking
    riders on the item must be at least the constant
    `HEADLINER_MIN_BLOCKING_RIDERS = 1`, otherwise
    `ERR_HEADLINER_MISSING_BLOCKING_RIDER` at HTTP 422 fires, with the
    boundary precisely at zero versus one — a HEADLINER announcing
    with zero blocking riders is rejected and a HEADLINER announcing
    with exactly one fulfilled blocking rider on file is accepted."

    Claim: the boundary at zero rejects with the headliner-rider error
    id at HTTP 422.  The accepted side (one fulfilled blocking rider)
    is asserted in test_06_validations_and_boundaries.py as the rule-6
    instance-C boundary-precision test.

    # difficulty: boundary_precision_check/headliner_blocking_rider_cardinality_zero_vs_one_on_announce
    """
    bag = confirmed_item_world(api, artist_tier="HEADLINER",
                               publish_the_version=True)
    item_id = str(bag.program_item["id"])
    # The item has zero blocking riders — the HEADLINER cardinality
    # minimum of one is violated.
    resp = api.announce_program_item(bag.festival_id, item_id, LIAISON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_HEADLINER_MISSING_BLOCKING_RIDER.value,
                   expected_status=422)


def test_announce_headliner_with_unfulfilled_blocking_rider_rejected(api):
    """PRD §3.3: the announce-precondition list includes "every
    blocking `RiderRequirement` on the item — a rider whose
    `is_blocking` flag is true — has a non-null `fulfilled_at`
    timestamp (the `ERR_BLOCKING_RIDERS_UNFULFILLED` at HTTP 422 fires
    otherwise)".

    Claim: a HEADLINER item with one blocking rider that has not yet
    been fulfilled (its `fulfilled_at` is still null) is rejected on
    announce with `ERR_BLOCKING_RIDERS_UNFULFILLED` at HTTP 422.  The
    boundary-pair to the cardinality-zero test above: cardinality is
    one, but fulfillment is zero.
    """
    bag = confirmed_item_world(api, artist_tier="HEADLINER",
                               publish_the_version=True)
    item_id = str(bag.program_item["id"])
    # Append a blocking rider but do not fulfil it.
    get_success_data(api.create_rider(
        bag.festival_id, item_id,
        rider_payload(is_blocking=True, category="TECHNICAL",
                      description="unfulfilled rider"),
        LIAISON_HEADERS,
    ))
    resp = api.announce_program_item(bag.festival_id, item_id, LIAISON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_BLOCKING_RIDERS_UNFULFILLED.value,
                   expected_status=422)


def test_program_item_patch_past_announced_returns_not_mutable(api):
    """PRD §3.3: "The PATCH on a program item ... is rejected on an
    item already past `ANNOUNCED` on the lifecycle axis with
    `ERR_PROGRAM_ITEM_NOT_MUTABLE` at HTTP 409 — the orchestrator must
    instead create a `ScheduleChange` of kind `ITEM_RESCHEDULE` ... or
    kind `STAGE_SWAP`".

    The PRD's specific phrase "already past `ANNOUNCED`" pins the gate.
    An ANNOUNCED item itself is on the boundary; the PRD does not pin
    whether an ANNOUNCED-but-not-yet-ON_STAGE item is mutable or not
    via the standalone PATCH path.  The clean assertion is on an
    item the test has driven to ON_STAGE via clock advance — past the
    boundary.

    Claim: a PATCH on an ON_STAGE item is rejected with
    `ERR_PROGRAM_ITEM_NOT_MUTABLE` at HTTP 409.
    """
    from test_helpers import confirmed_item_world, advance_clock_to, AUDIT_HEADERS
    bag = confirmed_item_world(api, artist_tier="OPENER", publish_the_version=True)
    item_id = str(bag.program_item["id"])
    # The item is in CONFIRMED.  Drive the item into ANNOUNCED via the
    # standard announce path — a non-headliner with NO sound-check axis
    # active (the axis is NOT_REQUIRED by default) can announce
    # immediately per PRD §3.3.
    announce_resp = api.announce_program_item(bag.festival_id, item_id, LIAISON_HEADERS)
    announced = validate_success(announce_resp)
    assert announced["status"] == "ANNOUNCED"
    # Now advance the test clock past the festival's start_time so the
    # festival itself flips PUBLISHED → LIVE (per PRD §3.1) and the
    # program item's ANNOUNCED → ON_STAGE clock-tick fires (per PRD
    # §3.3 "The advance from `ANNOUNCED` to `ON_STAGE` is system-driven:
    # the clock-advance endpoint's logical wall clock crossing the
    # item's `start_time` while the parent festival is `LIVE` flips the
    # item's status").
    target = int(bag.program_item["start_time"]) + 5
    advance_clock_to(api, festival_id=bag.festival_id, to_unix_seconds=target)
    # Confirm the item's status is now ON_STAGE.
    on_stage = get_success_data(api.get_program_item(bag.festival_id, item_id, AUDIT_HEADERS))
    assert on_stage["status"] in {"ON_STAGE", "PERFORMED"}, \
        ("After advancing the clock past the item's start_time while the "
         "festival is LIVE, the item must be at least ON_STAGE per PRD §3.3.")
    # The PATCH on an item past ANNOUNCED is the rejected case.
    patch_resp = api.patch_program_item(
        bag.festival_id, item_id, {"genre": "new-genre"}, LIAISON_HEADERS,
    )
    validate_error(patch_resp, ApiErrorId.ERR_PROGRAM_ITEM_NOT_MUTABLE.value,
                   expected_status=409)


def test_program_item_announce_without_published_festival_rejected(api):
    """PRD §3.3: "The parent festival's status must be exactly
    `PUBLISHED` for an announcement to be legal (`ERR_FESTIVAL_NOT_PUBLISHED`
    at HTTP 409 otherwise — the announcement has no public surface to
    publish to before then and the festival's window-close at
    `CLOSED` rules out any post-close announcement)."

    Claim: an announce on a CONFIRMED item under a festival that is
    still in SCHEDULING (no program version has yet published) is
    rejected with `ERR_FESTIVAL_NOT_PUBLISHED` at HTTP 409.
    """
    # confirmed_item_world with publish_the_version=False leaves the
    # festival in SCHEDULING and the item in CONFIRMED under the
    # still-DRAFT initial version V1.
    bag = confirmed_item_world(api, artist_tier="OPENER", publish_the_version=False)
    item_id = str(bag.program_item["id"])
    resp = api.announce_program_item(bag.festival_id, item_id, LIAISON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_PUBLISHED.value,
                   expected_status=409)


def test_sound_check_waive_sets_status_to_waived(api):
    """PRD §3.3: "The sound-check-waive capability, ... flips the
    parallel `sound_check_status` axis to `WAIVED` from whichever of
    `NOT_REQUIRED` or `REQUESTED` it currently sits in".

    Claim: calling waive on an item with sound_check_status ==
    NOT_REQUIRED flips the axis to WAIVED.
    """
    bag = confirmed_item_world(api, artist_tier="OPENER", publish_the_version=True)
    item_id = str(bag.program_item["id"])
    # No sound-check slot has been created, so the axis is at the
    # default NOT_REQUIRED per the PRD §3.3 narrative.  The waive flips
    # the axis to WAIVED.
    resp = api.waive_sound_check(bag.festival_id, item_id,
                                 waive_sound_check_payload(reason="not-needed"),
                                 STAGE_HEADERS)
    data = validate_success(resp)
    assert_program_item_shape(data)
    assert data["sound_check_status"] == "WAIVED", \
        ("The waive flips the sound-check axis to WAIVED from NOT_REQUIRED "
         "per PRD §3.3.")


def test_program_item_cancel_appends_audit_and_keeps_terminal_state(api):
    """PRD §3.3: "The branch from any of `PROPOSED`, `CONFIRMED`, or
    `ANNOUNCED` to the absorbing state `CANCELLED` is the `cancel`
    capability the artist-liaison (or producer) exercises directly
    through the cancel endpoint, with a required `reason` string ...
    The state-gate error when the item is already `CANCELLED` ... is
    `ERR_PROGRAM_ITEM_ALREADY_CANCELLED` at HTTP 409 for the
    already-cancelled case".

    Claim: a cancel of a CONFIRMED item flips the item's status to the
    terminal CANCELLED, appends an audit row, and a second cancel
    attempt on the now-terminal item returns
    `ERR_PROGRAM_ITEM_ALREADY_CANCELLED` at HTTP 409.
    """
    bag = confirmed_item_world(api, artist_tier="OPENER", publish_the_version=True)
    item_id = str(bag.program_item["id"])
    # First cancel: flips to CANCELLED.
    cancel_resp = api.cancel_program_item(bag.festival_id, item_id,
                                          F.cancel_program_item_payload(reason="weather"),
                                          LIAISON_HEADERS)
    cancelled = validate_success(cancel_resp)
    assert cancelled["status"] == "CANCELLED", \
        ("The direct cancel flips the lifecycle axis to the absorbing CANCELLED "
         "per PRD §3.3.")
    # Audit row.
    entries = read_audit_log(api, bag,
                             subject_entity_type="ProgramItem")
    cancelled_rows = [e for e in entries
                      if e.get("subject_entity_id") == item_id and e.get("to_state") == "CANCELLED"]
    assert cancelled_rows, ("A state-transition audit row for the cancellation is "
                            "appended per PRD §3.3.")
    # Second cancel: rejected.
    bad = api.cancel_program_item(bag.festival_id, item_id,
                                  F.cancel_program_item_payload(reason="dup"),
                                  LIAISON_HEADERS)
    validate_error(bad, ApiErrorId.ERR_PROGRAM_ITEM_ALREADY_CANCELLED.value,
                   expected_status=409)


def test_program_item_recompute_priority_idempotent_and_returns_score(api):
    """PRD §3.3: "The recompute-priority capability, exposed at the
    recompute-priority idempotent capability for `FestivalProducer` and
    `PlatformAdmin`, recomputes the `slot_priority_score` field
    without driving any state transition and is the harness's hook for
    forcing the formula to re-evaluate.  The capability is idempotent
    — a recompute that yields the same numeric value is a no-op except
    for the score-unchanged audit entry."

    Claim: the recompute endpoint returns the program item with a
    numeric `slot_priority_score` field and the second call with no
    intervening input change returns the same score.
    """
    bag = confirmed_item_world(api, artist_tier="OPENER", publish_the_version=False)
    item_id = str(bag.program_item["id"])
    r1 = validate_success(
        api.recompute_program_item_priority(bag.festival_id, item_id, PRODUCER_HEADERS)
    )
    s1 = r1["slot_priority_score"]
    r2 = validate_success(
        api.recompute_program_item_priority(bag.festival_id, item_id, PRODUCER_HEADERS)
    )
    s2 = r2["slot_priority_score"]
    assert s1 == s2, \
        ("Two recompute calls with no intervening change yield the same "
         "score per PRD §3.3 idempotent contract.")
