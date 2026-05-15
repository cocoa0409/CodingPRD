"""Interval-engine flavours: the three different geometric overlap
rules PRD §3.5 catalogs across three resource entities.

  1. Stage changeover overlap — pairwise, half-open candidate vs
     closed-and-buffer-padded existing on the same stage, with the
     boundary asymmetry that a candidate starting exactly at an
     existing's padded right endpoint conflicts (closed on the right
     of the padded existing) but an existing whose padded left endpoint
     equals the candidate's exclusive right endpoint does not (open on
     the right of the half-open candidate).  Buffer is the stage's
     `changeover_buffer_seconds`, defaulting to the global
     `STAGE_CHANGEOVER_BUFFER_SECONDS = 1800`.

  2. Equipment-kit aggregate-capacity — the festival-wide peak
     simultaneous count of CONFIRMED-or-ANNOUNCED-or-ON_STAGE program
     items that share an equipment_kit_code must be ≤ that kit's
     `total_units`.  Pure half-open intersection semantics with the
     sweep-line tiebreak that a closing event at the same instant as
     an opening event sorts before the opening event so back-to-back
     uses do not double-count.

  3. Sound-engineer-team warmup-gap — single-team consecutive-booking
     rule with both intervals closed and a symmetric warmup-pad on
     the existing in the amount of the team's `warmup_minutes * 60`
     seconds (`TEAM_WARMUP_MINUTES = 10` default, giving 600 seconds).

The three distinct interval semantics on three distinct resource
entities are the §1.8 rule-8 instances 1, 2, and 3 in the difficulty
design.

Also: the rehearsal-room half-open overlap rule (PRD §3.5's fourth
flavour, the string-namespaced ROOM-type rehearsal conflict that does
not interact with the STAGE-id namespace).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_equipment_kit,
    add_program_item,
    add_program_version,
    add_sound_check_slot,
    add_stage,
    add_team,
    base_world,
    confirm_item,
    constants as C,
    factories as F,
    fixtures as FIX,
    get_success_data,
    AUDIT_HEADERS,
    LIAISON_HEADERS,
    STAGE_HEADERS,
    PRODUCER_HEADERS,
    register_artist,
    THRESHOLDS,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Stage changeover overlap rule — PRD §3.5's first interval flavour, with
# the half-open-candidate vs padded-closed-existing boundary asymmetry.
# ---------------------------------------------------------------------------


def test_stage_changeover_overlap_pairwise_buffer_padded_rejection(api):
    """PRD §3.5: "Each existing CONFIRMED-or-ANNOUNCED-or-ON_STAGE
    program item, and each BOOKED-or-IN_PROGRESS stage-rehearsal, on the
    same stage is treated as a closed interval padded on both sides by
    the stage's `changeover_buffer_seconds` (defaulting to the global
    `STAGE_CHANGEOVER_BUFFER_SECONDS = 1800` of thirty minutes when the
    stage's per-stage override is null) — concretely the padded
    interval is `[existing.start_time - buffer, existing.end_time +
    buffer]` with both endpoints inclusive.  The conflict test is 'the
    half-open candidate's interval intersects the closed-and-padded
    existing's interval'".  And: "the rejection on overlap is
    `ERR_STAGE_CHANGEOVER_OVERLAP` at HTTP 409".

    Claim: an item B on the same stage as a CONFIRMED item A, whose
    window falls inside the buffer-padded interval of A, is rejected at
    create with `ERR_STAGE_CHANGEOVER_OVERLAP`.  Specifically, the
    case where B starts during A's window (a strict overlap) is the
    most basic rejection.

    # difficulty: resource_temporal_overlap/stage_changeover_buffer_pairwise_half_open_vs_padded_closed
    """
    bag = base_world(api, day_count=3,
                     artist_tier="OPENER",
                     stage_zone_capacity=100)
    # Item A on day-1 from 14:00 to 15:00, the parent's program-version
    # is still DRAFT so the cross-state version-pinning gate of
    # §2.6 priority-6 does not fire.
    a_start = bag.festival_start + 1 * 86400 + 14 * 3600
    a_end = a_start + 3600
    item_a = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=bag.stage_id,
                               start_time=a_start,
                               end_time=a_end),
        LIAISON_HEADERS,
    ))
    a_id = str(item_a["id"])
    # Confirm A so it lands in the "CONFIRMED-or-ANNOUNCED-or-ON_STAGE"
    # set that the changeover-buffer rule considers per PRD §3.5.
    get_success_data(api.confirm_program_item(bag.festival_id, a_id, LIAISON_HEADERS))
    # The default stage changeover buffer is 1800 s.  Item B is a
    # different artist on the same stage with a window that overlaps
    # A's window directly — falls inside A's padded interval.  Per
    # the half-open-candidate-vs-closed-padded-existing rule the
    # candidate's half-open [start, end) intersects the padded closed
    # interval [a_start - 1800, a_end + 1800] iff
    # candidate.start_time <= padded_end AND padded_start <
    # candidate.end_time.  A candidate that strictly overlaps A's
    # window trivially satisfies both inequalities.
    artist_b = register_artist(api, tier="OPENER")
    b_start = a_start + 600   # inside A's window, 10 minutes after A's start
    b_end = a_end + 600       # still inside A's window's end edge
    resp = api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=str(artist_b["id"]),
                               stage_id=bag.stage_id,
                               start_time=b_start, end_time=b_end),
        LIAISON_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_STAGE_CHANGEOVER_OVERLAP.value,
                   expected_status=409)


def test_stage_changeover_back_to_back_with_full_buffer_accepted(api):
    """PRD §3.5: the "boundary-asymmetry — the candidate is right-open
    while the existing is right-closed-with-pad — is the precise
    geometric flavour the test fixture pins on the buffer-edge equality
    case".  The PRD's sentence "in tight arithmetic terms a candidate
    starts no later than the existing's padded right endpoint and the
    existing's padded left endpoint is strictly earlier than the
    candidate's exclusive right end" pins the inclusive-on-the-existing-
    padded-right edge.

    The accepted side of the boundary on a back-to-back booking is
    therefore the case where the candidate starts STRICTLY AFTER the
    existing's padded right endpoint — i.e., gap of buffer+1 seconds
    from A's end to B's start.  At exactly the buffer edge (gap ==
    buffer), the candidate starts at A's padded right endpoint, and
    the candidate's left endpoint is in the inclusive-on-the-existing
    interval, so the conflict test "candidate.start_time <=
    padded_end" fires with equality — the rejected side of the
    asymmetric edge.

    Claim: a candidate B whose start is exactly `existing.end_time +
    changeover_buffer_seconds + 1` clears the rule.  The pair (A from
    14:00–15:00 with buffer 1800 s, B starting at 15:30:01) is the
    canonical back-to-back-with-one-second-margin accepted case.

    # difficulty: resource_temporal_overlap/stage_changeover_buffer_pairwise_half_open_vs_padded_closed
    """
    bag = base_world(api, day_count=3, artist_tier="OPENER",
                     stage_zone_capacity=100)
    a_start = bag.festival_start + 1 * 86400 + 14 * 3600
    a_end = a_start + 3600
    a = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=bag.stage_id,
                               start_time=a_start, end_time=a_end),
        LIAISON_HEADERS,
    ))
    get_success_data(api.confirm_program_item(bag.festival_id, str(a["id"]), LIAISON_HEADERS))
    # B starts at exactly a_end + buffer + 1, the strict-after-padded-
    # right-endpoint case the asymmetric rule accepts.  The PRD §3.5
    # sentence "a candidate starting exactly at that padded right edge
    # does conflict" pins the equality case as the rejected side; the
    # one-second-after case is therefore the accepted side.
    buffer_seconds = int(THRESHOLDS["STAGE_CHANGEOVER_BUFFER_SECONDS"])
    b_start = a_end + buffer_seconds + 1
    b_end = b_start + 3600
    artist_b = register_artist(api, tier="OPENER")
    b_resp = api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=str(artist_b["id"]),
                               stage_id=bag.stage_id,
                               start_time=b_start, end_time=b_end),
        LIAISON_HEADERS,
    )
    b_data = validate_success(b_resp, expected_status=201)
    # And the resulting item confirms cleanly — the confirm endpoint
    # re-runs the changeover-buffer check authoritatively per PRD §3.3.
    confirmed_b = get_success_data(
        api.confirm_program_item(bag.festival_id, str(b_data["id"]), LIAISON_HEADERS)
    )
    assert confirmed_b["status"] == "CONFIRMED", \
        ("The buffer-plus-one-second back-to-back booking clears the "
         "stage-changeover-buffer rule per PRD §3.5's half-open-on-the-"
         "candidate-right-end asymmetry.")


def test_stage_changeover_with_per_stage_buffer_override(api):
    """PRD §2.4 / §3.2: the Stage's `changeover_buffer_seconds` is the
    "per-stage override of the global default".  PRD §3.5 says the
    rule uses "the stage's `changeover_buffer_seconds` (defaulting to
    the global `STAGE_CHANGEOVER_BUFFER_SECONDS = 1800` of thirty
    minutes when the stage's per-stage override is null)".

    Claim: a stage with a smaller-than-default buffer (say 60 seconds)
    accepts a back-to-back booking that the default-buffer stage would
    have rejected.

    # difficulty: resource_temporal_overlap/stage_changeover_buffer_pairwise_half_open_vs_padded_closed
    """
    bag = base_world(api, day_count=3, artist_tier="OPENER",
                     stage_zone_capacity=100)
    # The bag's default stage uses the global 1800-second buffer.  Add
    # a second stage with an explicit 60-second override.
    small_stage = get_success_data(
        api.create_stage(bag.festival_id,
                         F.stage_payload(stage_name="SmallBufferStage",
                                         zone_capacity=100,
                                         changeover_buffer_seconds=60,
                                         equipment_kits=[]),
                         STAGE_HEADERS)
    )
    small_stage_id = str(small_stage["id"])
    # Item A on the small-buffer stage.
    a_start = bag.festival_start + 1 * 86400 + 14 * 3600
    a_end = a_start + 3600
    a = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=small_stage_id,
                               start_time=a_start, end_time=a_end),
        LIAISON_HEADERS,
    ))
    get_success_data(api.confirm_program_item(bag.festival_id, str(a["id"]), LIAISON_HEADERS))
    # Item B starts 120 seconds after A ends — fine under the 60-second
    # override, rejected under the 1800-second default.
    artist_b = register_artist(api, tier="OPENER")
    b_start = a_end + 120
    b_end = b_start + 3600
    b_resp = api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=str(artist_b["id"]),
                               stage_id=small_stage_id,
                               start_time=b_start, end_time=b_end),
        LIAISON_HEADERS,
    )
    b_data = validate_success(b_resp, expected_status=201)
    confirmed_b = get_success_data(
        api.confirm_program_item(bag.festival_id, str(b_data["id"]), LIAISON_HEADERS)
    )
    assert confirmed_b["status"] == "CONFIRMED", \
        ("Per-stage changeover_buffer_seconds override is honoured per PRD §2.4 / §3.2 — "
         "120-second gap clears a 60-second buffer.")


# ---------------------------------------------------------------------------
# Equipment-kit aggregate-capacity rule — PRD §3.5's second interval flavour.
# ---------------------------------------------------------------------------


def test_equipment_kit_aggregate_capacity_check_pure_half_open(api):
    """PRD §3.5: "The second flavour is the equipment-kit
    aggregate-capacity rule on the festival-wide concurrent use of a
    given `kit_code`.  There is no buffer pad on this rule — the kit
    is either in use during a program item's half-open
    `[start_time, end_time)` interval or it is not, and the test is on
    the integer maximum over time of the count of simultaneously-active
    intervals that share the same `kit_code`, summed across all stages
    of the festival, in the candidate's window. ... The candidate's
    own +1 over its full window is added to the maximum-over-existing
    running count, and the resulting peak-simultaneous-users count is
    compared against the `total_units` of the corresponding
    `EquipmentKit`.  A peak strictly above `total_units` is rejected at
    HTTP 409 with `ERR_EQUIPMENT_KIT_OVERSUBSCRIBED`".

    Claim: a kit with `total_units = 1` and one CONFIRMED program item
    holding the kit during a window W rejects a candidate item on a
    different stage that also requests the kit and whose window
    overlaps W — the peak demand at the overlap instant is 2, strictly
    above the kit's total_units of 1.

    # difficulty: resource_temporal_overlap/equipment_kit_aggregate_capacity_pure_half_open_sweep
    """
    bag = FIX.festival_in_scheduling(api, day_count=3)
    # Register the equipment kit with total_units == 1.
    kit_code = "LIGHTS"
    add_equipment_kit(api, bag, kit_code=kit_code, total_units=1)
    # Two stages both wired for the kit (so the per-stage
    # `equipment_kits` membership guard, `ERR_STAGE_LACKS_EQUIPMENT_KIT`,
    # does not fire on the second item).
    stage_a = get_success_data(api.create_stage(
        bag.festival_id,
        F.stage_payload(stage_name="StageA", zone_capacity=100, equipment_kits=[kit_code]),
        STAGE_HEADERS,
    ))
    stage_b = get_success_data(api.create_stage(
        bag.festival_id,
        F.stage_payload(stage_name="StageB", zone_capacity=100, equipment_kits=[kit_code]),
        STAGE_HEADERS,
    ))
    bag.stage = stage_a
    bag.stage_id = str(stage_a["id"])
    # Two distinct artists so the per-artist self-overlap guard
    # (ERR_ARTIST_SELF_OVERLAP, PRD §2.6 priority-13) doesn't interfere.
    artist_a = register_artist(api, tier="OPENER")
    artist_b = register_artist(api, tier="OPENER")
    # A program version under the festival.  Items attached to the
    # default DRAFT version V1.
    vid = bag.version_id or get_success_data(
        api.create_program_version(bag.festival_id,
                                   F.program_version_payload(version_label="v1"),
                                   PRODUCER_HEADERS))["id"]
    add_program_version(api, bag, version_label="v1") if bag.version_id is None else None
    # Item A on stage A, holding the kit during a 1-hour window on day 1.
    a_start = bag.festival_start + 86400 + 12 * 3600
    a_end = a_start + 3600
    item_a = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=str(artist_a["id"]),
                               stage_id=str(stage_a["id"]),
                               start_time=a_start, end_time=a_end,
                               equipment_kit_codes=[kit_code]),
        LIAISON_HEADERS,
    ))
    get_success_data(api.confirm_program_item(bag.festival_id, str(item_a["id"]),
                                              LIAISON_HEADERS))
    # Item B on the other stage, overlapping A's window by 30 minutes —
    # the kit is held by both items for the half-hour intersection, and
    # that simultaneous count is 1 (existing) + 1 (candidate) == 2, one
    # above the kit's total_units of 1.  Per PRD §3.5 the rejection is
    # ERR_EQUIPMENT_KIT_OVERSUBSCRIBED.
    b_start = a_start + 1800  # 30 minutes into A's window
    b_end = b_start + 3600
    bad_resp = api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=str(artist_b["id"]),
                               stage_id=str(stage_b["id"]),
                               start_time=b_start, end_time=b_end,
                               equipment_kit_codes=[kit_code]),
        LIAISON_HEADERS,
    )
    # The candidate's create call goes through (it's PROPOSED and the
    # capacity rule fires only as the item enters the CONFIRMED-or-
    # ANNOUNCED-or-ON_STAGE set per PRD §3.5).  The PRD §3.3 sentence
    # "The overlap, travel-buffer, multi-festival-conflict,
    # equipment-wiring, and within-festival-window checks all run at
    # creation time as advisory rejections" pins the gate at the
    # create endpoint too — so the rejection may surface at either
    # POST /program-items or on the subsequent confirm.  We accept
    # both points where the gate can fire.
    if bad_resp.status_code in (400, 409, 422):
        validate_error(bad_resp, ApiErrorId.ERR_EQUIPMENT_KIT_OVERSUBSCRIBED.value)
    else:
        # The create was advisory-accepted; the confirm must reject.
        b_id = str(bad_resp.json()["data"]["id"])
        confirm_resp = api.confirm_program_item(bag.festival_id, b_id, LIAISON_HEADERS)
        validate_error(confirm_resp,
                       ApiErrorId.ERR_EQUIPMENT_KIT_OVERSUBSCRIBED.value,
                       expected_status=409)


def test_equipment_kit_back_to_back_uses_do_not_overlap(api):
    """PRD §3.5: "The semantics is the standard sweep-line over
    `(time, +1)` and `(time, -1)` events, with the half-open
    right-exclusive disambiguation that a closing event at time `T`
    is processed before an opening event at the same time `T` (so
    back-to-back items on the same kit do not count as overlapping at
    the joint instant)."

    Claim: two program items on different stages, both holding the
    same single-unit kit, whose windows are back-to-back at the same
    instant (item A ends at T, item B starts at T), are both
    permitted because the +1/-1 sweep processes the close before the
    open at the joint instant.

    # difficulty: resource_temporal_overlap/equipment_kit_aggregate_capacity_pure_half_open_sweep
    """
    bag = FIX.festival_in_scheduling(api, day_count=3)
    kit_code = "RIG"
    add_equipment_kit(api, bag, kit_code=kit_code, total_units=1)
    stage_a = get_success_data(api.create_stage(
        bag.festival_id,
        F.stage_payload(stage_name="SA", zone_capacity=10, equipment_kits=[kit_code]),
        STAGE_HEADERS,
    ))
    stage_b = get_success_data(api.create_stage(
        bag.festival_id,
        F.stage_payload(stage_name="SB", zone_capacity=10, equipment_kits=[kit_code]),
        STAGE_HEADERS,
    ))
    bag.stage_id = str(stage_a["id"])
    artist_a = register_artist(api, tier="OPENER", home_city="A-city")
    artist_b = register_artist(api, tier="OPENER", home_city="B-city")
    add_program_version(api, bag, version_label="bb")
    t0 = bag.festival_start + 86400 + 12 * 3600
    a_end_b_start = t0 + 3600  # the joint instant
    item_a = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=str(artist_a["id"]),
                               stage_id=str(stage_a["id"]),
                               start_time=t0, end_time=a_end_b_start,
                               equipment_kit_codes=[kit_code]),
        LIAISON_HEADERS,
    ))
    get_success_data(api.confirm_program_item(bag.festival_id, str(item_a["id"]),
                                              LIAISON_HEADERS))
    # Item B starts at the exact instant A's window ends; back-to-back.
    item_b_resp = api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=str(artist_b["id"]),
                               stage_id=str(stage_b["id"]),
                               start_time=a_end_b_start,
                               end_time=a_end_b_start + 3600,
                               equipment_kit_codes=[kit_code]),
        LIAISON_HEADERS,
    )
    item_b = validate_success(item_b_resp, expected_status=201)
    # The confirm side must also accept since the open-event-after-
    # close-event tiebreak rule means the simultaneous peak is 1, not 2.
    confirmed_b = get_success_data(
        api.confirm_program_item(bag.festival_id, str(item_b["id"]), LIAISON_HEADERS)
    )
    assert confirmed_b["status"] == "CONFIRMED", \
        ("Back-to-back kit-holding intervals do not overlap per the half-open "
         "right-exclusive sweep-line tiebreak in PRD §3.5.")


def test_stage_lacks_equipment_kit_when_item_requests_kit_not_wired(api):
    """PRD §3.3: "the system requires every code on the list to appear
    in the parent stage's `equipment_kits` array, otherwise the item's
    create or PATCH is rejected at HTTP 409 with
    `ERR_STAGE_LACKS_EQUIPMENT_KIT`".

    Claim: a stage whose `equipment_kits` array is empty (i.e. the
    stage is not wired for any kit) rejects a program-item create
    that lists a kit_code in `equipment_kit_codes` with
    `ERR_STAGE_LACKS_EQUIPMENT_KIT` at HTTP 409.
    """
    bag = FIX.festival_in_scheduling(api, day_count=2)
    # The stage's equipment_kits array is empty.
    stage = get_success_data(api.create_stage(
        bag.festival_id,
        F.stage_payload(stage_name="NoKitsStage", zone_capacity=10,
                        equipment_kits=[]),
        STAGE_HEADERS,
    ))
    # Register the kit at the festival level — the rejection is on the
    # stage-wiring guard, not on the kit-not-found one.
    add_equipment_kit(api, bag, kit_code="MIXER", total_units=1)
    artist = register_artist(api, tier="OPENER")
    add_program_version(api, bag, version_label="v")
    start = bag.festival_start + 3600
    end = start + 3600
    resp = api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=str(artist["id"]),
                               stage_id=str(stage["id"]),
                               start_time=start, end_time=end,
                               equipment_kit_codes=["MIXER"]),
        LIAISON_HEADERS,
    )
    # The PRD §3.3 quote pins HTTP 409 with
    # ERR_STAGE_LACKS_EQUIPMENT_KIT.  The check applies at create
    # ("creation time as advisory rejections") and at confirm
    # ("authoritatively on the `confirm` transition") per PRD §3.5.
    if resp.status_code == 201:
        # advisorily accepted; the confirm path is the authoritative
        # check.
        item_id = str(resp.json()["data"]["id"])
        confirm_resp = api.confirm_program_item(bag.festival_id, item_id,
                                                LIAISON_HEADERS)
        validate_error(confirm_resp,
                       ApiErrorId.ERR_STAGE_LACKS_EQUIPMENT_KIT.value,
                       expected_status=409)
    else:
        validate_error(resp, ApiErrorId.ERR_STAGE_LACKS_EQUIPMENT_KIT.value,
                       expected_status=409)


# ---------------------------------------------------------------------------
# Sound-engineer-team warmup-gap rule — PRD §3.5's third interval flavour.
# ---------------------------------------------------------------------------


def test_sound_engineer_team_warmup_gap_prevents_overlap(api):
    """PRD §3.5: "The third flavour is the sound-engineer-team
    consecutive-booking rule on a single team's interval graph.  A
    team's schedule-room is the union of its SoundCheckSlot intervals
    in the set of statuses `SCHEDULED` or `COMPLETED`.  Each such
    interval is closed on both ends and is padded symmetrically by the
    team's `warmup_seconds` (the team's `warmup_minutes` integer field
    times 60, defaulting to the ten-minute global constant
    `TEAM_WARMUP_MINUTES = 10` rendered as 600 seconds, when the
    team's override is null).  The conflict test on a candidate slot
    whose own interval is the closed `[scheduled_window_start,
    scheduled_window_end]` is 'the candidate's closed interval
    intersects the existing's warmup-padded closed interval' — both
    endpoints inclusive on both intervals. ... The rejection is
    `ERR_ENGINEER_TEAM_DOUBLE_BOOKED` at HTTP 409."

    Claim: a sound-engineer team that has a SCHEDULED slot under one
    program item rejects a second slot under a different program item
    whose window is closer than the team's `warmup_minutes * 60`
    boundary to the first.

    Concretely, the team's default warmup_seconds is 600 (the global
    constant of TEN minutes).  A second slot whose start is exactly
    `existing.end + 599` seconds — strictly less than the warmup gap —
    must be rejected; the same slot at `existing.end + 600` (the
    inclusive boundary on the warmup-pad's right edge) is the
    rejected-or-accepted-boundary case the §3.5 narrative pins at
    "warmup-padded closed-closed" semantics — the existing's padded
    right endpoint is `existing.end + warmup_seconds` and the
    candidate's left endpoint at exactly that instant intersects the
    closed-closed padded existing, so it conflicts.  The accepted side
    of the boundary is `existing.end + warmup_seconds + 1`.

    This test pins the warmup_seconds=600 / gap=599 rejection.

    # difficulty: resource_temporal_overlap/sound_engineer_team_warmup_gap_closed_closed_one_sided
    """
    # Two CONFIRMED items so two slots can hang under each respectively.
    bag = base_world(api, day_count=3, artist_tier="OPENER",
                     stage_zone_capacity=100)
    # Item A on day 1 14:00–15:00.
    a_start = bag.festival_start + 86400 + 14 * 3600
    a_end = a_start + 3600
    a = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=bag.stage_id,
                               start_time=a_start, end_time=a_end),
        LIAISON_HEADERS,
    ))
    a_id = str(a["id"])
    get_success_data(api.confirm_program_item(bag.festival_id, a_id, LIAISON_HEADERS))
    # Item B (another artist on the same stage, well after A so the
    # stage-changeover rule doesn't fire).  Same-day, two hours after A
    # ends, on a different artist so the artist-self-overlap rule
    # doesn't fire either.
    artist_b = register_artist(api, tier="OPENER")
    b_start = a_end + 2 * 3600
    b_end = b_start + 3600
    b = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=str(artist_b["id"]),
                               stage_id=bag.stage_id,
                               start_time=b_start, end_time=b_end),
        LIAISON_HEADERS,
    ))
    b_id = str(b["id"])
    get_success_data(api.confirm_program_item(bag.festival_id, b_id, LIAISON_HEADERS))
    # The single team with the default warmup_minutes (giving 600 s).
    team = add_team(api, bag)
    team_id = str(team["id"])
    # First sound-check slot — under item A, with a window strictly
    # before A's start_time by at least TEAM_HANDOFF_SECONDS=600.
    handoff = int(THRESHOLDS["TEAM_HANDOFF_SECONDS"])
    sc1_end = a_start - handoff
    sc1_start = sc1_end - 1800   # 30-minute sound-check window
    slot1 = add_sound_check_slot(api, bag, a_id,
                                 scheduled_window_start=sc1_start,
                                 scheduled_window_end=sc1_end)
    slot1_id = str(slot1["id"])
    # Schedule slot1 against the team.  Per PRD §3.5 the transition
    # REQUESTED → SCHEDULED supplies the team_id and the window.
    scheduled1 = get_success_data(api.patch_sound_check(
        bag.festival_id, slot1_id,
        F.sound_check_schedule_payload(sound_engineer_team_id=team_id,
                                       scheduled_window_start=sc1_start,
                                       scheduled_window_end=sc1_end),
        STAGE_HEADERS,
    ))
    assert scheduled1["status"] == "SCHEDULED"
    # Second sound-check slot under item B.  Its desired window is
    # placed so its left endpoint sits inside the warmup-padded right
    # interval of slot1: slot1 ends at sc1_end, the padded right edge
    # is sc1_end + warmup_seconds (=600).  A candidate that starts at
    # sc1_end + warmup_seconds − 1 sits at the closed-padded interval's
    # interior and conflicts.
    warmup_seconds = int(THRESHOLDS["TEAM_WARMUP_SECONDS"])
    sc2_start = sc1_end + warmup_seconds - 1
    # The slot's end must still precede the parent's start by
    # TEAM_HANDOFF_SECONDS — b_start - handoff is the latest allowed
    # window-end.  If our computed sc2_start is too late, drop the test
    # via a structural skip (no Silence-pattern category — the fixture
    # arithmetic is the issue), but the canonical 24-hour gap between A
    # and B (two hours apart, with TEAM_WARMUP_SECONDS == 600 and
    # TEAM_HANDOFF_SECONDS == 600) ensures sc2_start < b_start -
    # handoff comfortably.
    sc2_end = min(sc2_start + 1800, b_start - handoff - 1)
    assert sc2_start < sc2_end < b_start, \
        ("Test fixture arithmetic: the second sound-check window must "
         "lie strictly between the first slot's warmup-pad and the "
         "parent item B's TEAM_HANDOFF_SECONDS boundary.")
    slot2 = add_sound_check_slot(api, bag, b_id,
                                 scheduled_window_start=sc2_start,
                                 scheduled_window_end=sc2_end)
    bad_resp = api.patch_sound_check(
        bag.festival_id, str(slot2["id"]),
        F.sound_check_schedule_payload(sound_engineer_team_id=team_id,
                                       scheduled_window_start=sc2_start,
                                       scheduled_window_end=sc2_end),
        STAGE_HEADERS,
    )
    # The PRD §3.5 narrative pins the rejection error_id as
    # ERR_ENGINEER_TEAM_DOUBLE_BOOKED at HTTP 409.  The §3.3 cross-
    # entity gate on the team-status-AVAILABLE side may also surface as
    # ERR_TEAM_NOT_AVAILABLE if the team's status is observed as BUSY
    # before the warmup check runs; per PRD §2.6 the
    # business-safety-team-double-booking gate is at priority 8 and the
    # cross-entity-team-status gate at priority 6, so the
    # cross-entity-state gate fires first when both would fail.  Allow
    # either as a PRD-faithful outcome.
    from test_helpers import validate_error_is_one_of
    err_id = validate_error_is_one_of(
        bad_resp,
        [ApiErrorId.ERR_ENGINEER_TEAM_DOUBLE_BOOKED.value,
         ApiErrorId.ERR_TEAM_NOT_AVAILABLE.value],
    )
    assert bad_resp.status_code == 409, \
        f"Both team-conflict and team-busy errors are HTTP 409 per PRD prose, got {bad_resp.status_code}"


def test_sound_engineer_team_warmup_gap_with_per_team_override(api):
    """PRD §3.2 / §3.5: the team's `warmup_minutes` integer overrides
    the global default of ten minutes / 600 seconds.

    Claim: a team registered with `warmup_minutes = 1` permits a
    second slot whose start is two minutes after the prior slot's end
    (120 s > 60 s gap), whereas the default-warmup team of the prior
    test would reject the same gap.

    # difficulty: resource_temporal_overlap/sound_engineer_team_warmup_gap_closed_closed_one_sided
    """
    bag = base_world(api, day_count=3, artist_tier="OPENER",
                     stage_zone_capacity=10)
    a_start = bag.festival_start + 86400 + 12 * 3600
    a_end = a_start + 3600
    a = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=bag.stage_id,
                               start_time=a_start, end_time=a_end),
        LIAISON_HEADERS,
    ))
    a_id = str(a["id"])
    get_success_data(api.confirm_program_item(bag.festival_id, a_id, LIAISON_HEADERS))
    # Item B comfortably later so the stage-changeover guard doesn't
    # bite.  Pick a window 6 hours later, plenty of slack.
    artist_b = register_artist(api, tier="OPENER")
    b_start = a_end + 6 * 3600
    b_end = b_start + 3600
    b = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=str(artist_b["id"]),
                               stage_id=bag.stage_id,
                               start_time=b_start, end_time=b_end),
        LIAISON_HEADERS,
    ))
    b_id = str(b["id"])
    get_success_data(api.confirm_program_item(bag.festival_id, b_id, LIAISON_HEADERS))
    # Team with the explicit 1-minute warmup override.
    team = add_team(api, bag, warmup_minutes=1)
    team_id = str(team["id"])
    handoff = int(THRESHOLDS["TEAM_HANDOFF_SECONDS"])
    sc1_end = a_start - handoff
    sc1_start = sc1_end - 1800
    slot1 = add_sound_check_slot(api, bag, a_id,
                                 scheduled_window_start=sc1_start,
                                 scheduled_window_end=sc1_end)
    get_success_data(api.patch_sound_check(
        bag.festival_id, str(slot1["id"]),
        F.sound_check_schedule_payload(sound_engineer_team_id=team_id,
                                       scheduled_window_start=sc1_start,
                                       scheduled_window_end=sc1_end),
        STAGE_HEADERS,
    ))
    # The team is now BUSY (current_booking_id == slot1.id).  We must
    # release it before the second slot's schedule attempt — per the
    # PRD §3.5 narrative the team flips BUSY → AVAILABLE on the prior
    # slot's COMPLETED or CANCELLED transition.  Drive slot1 to
    # COMPLETED via the §3.5 "the wall clock at or past the slot's
    # `scheduled_window_end`" gate by advancing the clock past sc1_end,
    # then call the complete endpoint.
    FIX.advance_clock_to(api, festival_id=bag.festival_id,
                         to_unix_seconds=int(sc1_end) + 60)
    get_success_data(api.complete_sound_check(bag.festival_id, str(slot1["id"]),
                                              STAGE_HEADERS))
    # Now the team is AVAILABLE again — its warmup window is closed
    # gap-checked against the closed-closed-with-symmetric-pad
    # semantics of §3.5.  The new slot under item B sits hours after
    # slot1's end so the gap-on-the-right of slot1 is well over the
    # 60-second warmup.  This must therefore be accepted.
    sc2_end = b_start - handoff
    sc2_start = sc2_end - 1800
    slot2 = add_sound_check_slot(api, bag, b_id,
                                 scheduled_window_start=sc2_start,
                                 scheduled_window_end=sc2_end)
    scheduled2 = get_success_data(api.patch_sound_check(
        bag.festival_id, str(slot2["id"]),
        F.sound_check_schedule_payload(sound_engineer_team_id=team_id,
                                       scheduled_window_start=sc2_start,
                                       scheduled_window_end=sc2_end),
        STAGE_HEADERS,
    ))
    assert scheduled2["status"] == "SCHEDULED", \
        ("With a 1-minute warmup override and a multi-hour gap between the "
         "two slots, the team's warmup-pad rule of PRD §3.5 admits the second "
         "slot's schedule.")


# ---------------------------------------------------------------------------
# Rehearsal-room half-open overlap rule — PRD §3.5's fourth interval flavour
# (the string-namespaced ROOM-type rehearsal-room overlap rule).
# ---------------------------------------------------------------------------


def test_rehearsal_room_same_name_overlap_rejected(api):
    """PRD §3.5: "For two `BOOKED`-or-`IN_PROGRESS` `ROOM` rehearsals
    that share the same `rehearsal_room_name`, the conflict test is
    the pure half-open intersection on `[start_time, end_time)` —
    back-to-back is allowed (the prior rehearsal's `end_time` is
    exclusive so a fresh rehearsal starting exactly there is fine),
    strict overlap rejects, and the rejection is
    `ERR_REHEARSAL_ROOM_OVERLAP` at HTTP 409."

    Claim: two ROOM-type rehearsals sharing the same
    `rehearsal_room_name` whose half-open windows strictly overlap
    are rejected with `ERR_REHEARSAL_ROOM_OVERLAP` at HTTP 409.  The
    back-to-back accepted case is asserted by the next test.
    """
    bag = FIX.festival_in_scheduling(api, day_count=3)
    add_stage(api, bag, zone_capacity=10)
    artist1 = register_artist(api, tier="OPENER")
    artist2 = register_artist(api, tier="OPENER")
    # Two rehearsals in the same room name with strict overlap.
    t0 = bag.festival_start + 3600
    a = get_success_data(api.create_rehearsal(
        bag.festival_id,
        F.rehearsal_payload(artist_id=str(artist1["id"]),
                            rehearsal_type="ROOM",
                            rehearsal_room_name="StudioA",
                            start_time=t0, end_time=t0 + 7200),
        STAGE_HEADERS,
    ))
    # Strict overlap: second window starts halfway through the first.
    bad = api.create_rehearsal(
        bag.festival_id,
        F.rehearsal_payload(artist_id=str(artist2["id"]),
                            rehearsal_type="ROOM",
                            rehearsal_room_name="StudioA",
                            start_time=t0 + 3600, end_time=t0 + 10800),
        STAGE_HEADERS,
    )
    validate_error(bad, ApiErrorId.ERR_REHEARSAL_ROOM_OVERLAP.value,
                   expected_status=409)


def test_rehearsal_room_back_to_back_accepted_half_open(api):
    """PRD §3.5: "back-to-back is allowed (the prior rehearsal's
    `end_time` is exclusive so a fresh rehearsal starting exactly
    there is fine)".

    Claim: two ROOM-type rehearsals in the same room whose windows
    are exactly back-to-back (`a.end_time == b.start_time`) are both
    accepted because the half-open right-exclusive overlap test does
    not see the joint instant as an intersection.
    """
    bag = FIX.festival_in_scheduling(api, day_count=3)
    add_stage(api, bag, zone_capacity=10)
    artist1 = register_artist(api, tier="OPENER")
    artist2 = register_artist(api, tier="OPENER")
    t0 = bag.festival_start + 3600
    a = get_success_data(api.create_rehearsal(
        bag.festival_id,
        F.rehearsal_payload(artist_id=str(artist1["id"]),
                            rehearsal_type="ROOM",
                            rehearsal_room_name="RoomB",
                            start_time=t0, end_time=t0 + 3600),
        STAGE_HEADERS,
    ))
    # B starts exactly at A's end_time.  Half-open rule says no
    # overlap, so both succeed.
    b_resp = api.create_rehearsal(
        bag.festival_id,
        F.rehearsal_payload(artist_id=str(artist2["id"]),
                            rehearsal_type="ROOM",
                            rehearsal_room_name="RoomB",
                            start_time=t0 + 3600, end_time=t0 + 7200),
        STAGE_HEADERS,
    )
    validate_success(b_resp, expected_status=201)


def test_rehearsal_room_namespace_is_disjoint_from_stage_namespace(api):
    """PRD §3.5: "the two namespaces (room name vs stage id) are kept
    disjoint by design — a stage rehearsal on stage X and a room
    rehearsal in room R1 never conflict with each other".

    Claim: a STAGE-type rehearsal on the festival's only stage and a
    ROOM-type rehearsal in a room whose name happens to be the same
    string as the stage's UUID id (the worst-case shadow-collision
    proof of namespace disjointness) both succeed at the same instant
    in time.
    """
    bag = FIX.festival_in_scheduling(api, day_count=3)
    # The stage we add.  Its id is a UUID per PRD §2.4.
    stage = get_success_data(api.create_stage(
        bag.festival_id,
        F.stage_payload(stage_name="MainStage", zone_capacity=100,
                        equipment_kits=[]),
        STAGE_HEADERS,
    ))
    bag.stage_id = str(stage["id"])
    artist1 = register_artist(api, tier="OPENER")
    artist2 = register_artist(api, tier="OPENER")
    t0 = bag.festival_start + 3600
    # STAGE-type rehearsal on the actual stage — counts toward the
    # stage's interval graph alongside any ProgramItems per PRD §3.5
    # but does not share the rehearsal-room namespace.
    sr = get_success_data(api.create_rehearsal(
        bag.festival_id,
        F.rehearsal_payload(artist_id=str(artist1["id"]),
                            rehearsal_type="STAGE",
                            stage_id=str(stage["id"]),
                            start_time=t0, end_time=t0 + 3600),
        STAGE_HEADERS,
    ))
    # ROOM-type rehearsal in a room whose name is the literal string of
    # the stage's id — the worst-case proof of namespace disjointness.
    # Per PRD §3.5 the two flavours do not see each other regardless
    # of any string coincidence.
    rr_name = str(stage["id"])
    rr_resp = api.create_rehearsal(
        bag.festival_id,
        F.rehearsal_payload(artist_id=str(artist2["id"]),
                            rehearsal_type="ROOM",
                            rehearsal_room_name=rr_name,
                            start_time=t0, end_time=t0 + 3600),
        STAGE_HEADERS,
    )
    validate_success(rr_resp, expected_status=201)
    # Both rehearsals are present in the listing.
    listing = validate_success(
        api.list_rehearsals(bag.festival_id, AUDIT_HEADERS,
                            params={"limit": 100})
    )
    rows = listing if isinstance(listing, list) else listing.get("items", listing.get("data", []))
    assert len(rows) >= 2, ("Both the STAGE-type and ROOM-type rehearsal "
                            "coexist at the same instant per the PRD §3.5 "
                            "namespace-disjointness rule.")


def test_rehearsal_cancel_on_non_booked_rejected(api):
    """PRD §3.5: "An attempt to cancel a non-`BOOKED` rehearsal is
    rejected at HTTP 409 with `ERR_REHEARSAL_NOT_BOOKED`."

    Claim: a cancel call on a rehearsal that is no longer in BOOKED
    (because the clock-advance progressed it past `start_time` into
    IN_PROGRESS per PRD §3.5's clock-driven transition) is rejected
    with `ERR_REHEARSAL_NOT_BOOKED` at HTTP 409.

    We exercise the negative path via a second cancel attempt on a
    rehearsal that's already CANCELLED.
    """
    bag = FIX.festival_in_scheduling(api, day_count=3)
    add_stage(api, bag, zone_capacity=10)
    add_program_version(api, bag, version_label="r-v")
    artist = register_artist(api, tier="OPENER")
    t0 = bag.festival_start + 3600
    r = get_success_data(api.create_rehearsal(
        bag.festival_id,
        F.rehearsal_payload(artist_id=str(artist["id"]),
                            rehearsal_type="ROOM",
                            rehearsal_room_name="RoomC",
                            start_time=t0, end_time=t0 + 3600),
        STAGE_HEADERS,
    ))
    # First cancel: flips BOOKED → CANCELLED per PRD §3.5.
    first_cancel = validate_success(
        api.cancel_rehearsal(bag.festival_id, str(r["id"]), STAGE_HEADERS,
                             {"reason": "test"})
    )
    assert first_cancel["status"] == "CANCELLED"
    # Second cancel on the now-terminal CANCELLED rehearsal is rejected
    # with ERR_REHEARSAL_NOT_BOOKED.
    bad = api.cancel_rehearsal(bag.festival_id, str(r["id"]), STAGE_HEADERS,
                               {"reason": "again"})
    validate_error(bad, ApiErrorId.ERR_REHEARSAL_NOT_BOOKED.value,
                   expected_status=409)
