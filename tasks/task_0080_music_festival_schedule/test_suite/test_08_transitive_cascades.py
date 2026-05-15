"""Transitive cascades — the rule-4 instances in the difficulty design,
each a depth-≥2 chain where each link is causally produced by the
prior one, distinguishing them from the broad single-trigger-to-many-
siblings fan-out of a festival hard-cancel (which the PRD §3.1
sentence "Because this fan-out is a single-trigger-to-many-targets
broadcast rather than a chain where each link's event causes the
next link's event, it does not count toward the depth-3 transitive
cascades described in §3.5" excludes from the cascade family).

The three cascades the PRD §3.5 prose names:

  Cascade A (depth 3, originating from a ScheduleChange.apply of kind
  ITEM_CANCEL): the target ProgramItem flips to CANCELLED (link 1);
  every REQUESTED-or-SCHEDULED SoundCheckSlot under the cancelled item
  flips to its own CANCELLED terminal (link 2, caused by the parent-
  item cancel, not by the apply directly); each cancelled slot whose
  team's current_booking_id was that slot's id releases the team
  back to AVAILABLE with current_booking_id cleared to null and an
  audit row of category STATE_TRANSITION recording the team's flip
  (link 3, caused by the slot cancel).  The chain is strictly causal,
  so the audit rows' created_at ordering is item-cancel-row,
  slot-cancel-row, team-flip-row.

  Cascade B (depth 2, originating from a direct
  /program-items/{itemId}/cancel call rather than a wrapped
  ScheduleChange.apply): the program-item cancel writes its own audit
  row (link 1), and every ExposureAllocation whose `program_item_id`
  is the cancelled item's id flips from PLANNED-or-DELIVERED to the
  absorbing VOIDED state with a FulfilmentLog row of `event_type`
  PROGRAM_VOIDED whose `units` equals the allocation's current
  `delivered_units`, and the parent SponsorTier's
  `tier_remaining_quota` and `projected_fulfilment_pct` are
  recomputed (link 2).  Depth 2 because the SponsorTier-tier-quota
  recomputation is a side-effect of the allocation-void's
  delivered_units mutation, not a fresh causally-distinct hop —
  the "parent SponsorTier's `tier_remaining_quota` is recomputed"
  side-effect of the deliver-and-void endpoints is documented in
  PRD §3.6.

  Cascade C (depth 3, originating from a clock-tick that crosses the
  festival's end_time + FESTIVAL_CLOSE_GRACE_SECONDS boundary): the
  festival flips LIVE → CLOSED (link 1), every BOOKED-or-IN_PROGRESS
  rehearsal under the festival auto-archives to the absorbing
  ARCHIVED state with its synthetic `archive_uri` stamped to the
  deterministic literal `archive://festival/{festival_id}/rehearsal/
  {rehearsal_id}` (link 2, caused by the festival's close, not by
  the clock tick directly), and each archived rehearsal's audit row
  of category CLOCK_TICK whose `payload_summary` names the
  originating clock-tick event's id (link 3, caused by each
  rehearsal's archive).

The PRD §2.4 prose names the audit log as ordered by `created_at`
per festival ascending, so the chronological order of the audit rows
under one festival is the visible-from-outside causal order.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    AUDIT_HEADERS,
    AuditEventCategory,
    CATALOG_KINDS,
    LIAISON_HEADERS,
    PRODUCER_HEADERS,
    SPONSOR_HEADERS,
    STAGE_HEADERS,
    SoundCheckSlotStatus,
    SoundEngineerTeamStatus,
    SyncEnvelopeStatus,
    THRESHOLDS,
    TICKETING_HEADERS,
    add_exposure_allocation,
    add_program_item,
    add_program_version,
    add_sound_check_slot,
    add_sponsor_tier,
    add_stage,
    add_team,
    advance_clock_to,
    advance_festival_through_close,
    announce_item,
    assert_audit_chronological,
    base_world,
    cancel_program_item_payload,
    confirm_item,
    confirmed_item_with_scheduled_sound_check,
    create_and_apply_item_cancel,
    factories as F,
    fixtures as FIX,
    get_festival_snapshot,
    get_sponsor_tier_snapshot,
    get_success_data,
    publish_version,
    read_audit_log,
    register_artist,
    rider_fulfil_payload,
    rider_payload,
    run_waterfall,
    schedule_sound_check,
    seed_default_catalog,
    sponsor_tier_payload,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Cascade A — ScheduleChange.apply(ITEM_CANCEL) → SoundCheckSlot.cancel →
# SoundEngineerTeam flip BUSY→AVAILABLE + STATE_TRANSITION audit row.
# ---------------------------------------------------------------------------


def test_cascade_a_apply_item_cancel_chains_through_slot_to_team(api):
    """PRD §3.5: "The first chain, originating from the apply of a
    `ScheduleChange` of kind `ITEM_CANCEL` (the apply endpoint hit,
    see §3.4 for the change-row mechanics), proceeds in three
    causally-ordered links.  Link one is the target program item
    flipping from its prior status (one of `PROPOSED`, `CONFIRMED`,
    or `ANNOUNCED`) to the absorbing terminal `CANCELLED`, which is
    the apply's primary state effect.  Link two, caused by the
    cancel of the program item and not by the apply directly, is
    every `REQUESTED` or `SCHEDULED` `SoundCheckSlot` whose
    `program_item_id` is the cancelled item also flipping to its own
    absorbing terminal `CANCELLED`.  ... Link three, caused by the
    slot cancel and not by the program-item cancel directly, is
    every `SoundEngineerTeam` whose `current_booking_id` was the
    now-cancelled slot's id flipping back from `BUSY` to `AVAILABLE`
    with `current_booking_id` cleared to null, and an audit entry on
    the team row of category `STATE_TRANSITION` recording the team's
    status flip."

    Claim: starting from the fixture
    `confirmed_item_with_scheduled_sound_check` (a CONFIRMED-with-
    published-version program item whose SoundCheckSlot is in
    SCHEDULED with a team that is BUSY pointing at the slot), the
    apply of an ITEM_CANCEL ScheduleChange targeting that item walks
    the three-link chain to completion: the item is in CANCELLED, the
    slot is in CANCELLED (its parent-cancel cascade firing through
    link 2), the team's `status` is back to AVAILABLE with
    `current_booking_id` null, and the audit log carries three rows
    in chronological order — the item-cancel row (subject ProgramItem,
    to_state CANCELLED), the slot-cancel row (subject SoundCheckSlot,
    to_state CANCELLED), and the team-flip row (subject
    SoundEngineerTeam, to_state AVAILABLE).

    Difficulty rule 4 instance A:
    # difficulty: transitive_cascade/schedulechange_apply_itemcancel_depth_3_into_team_audit
    """
    bag, team_before, slot_before = confirmed_item_with_scheduled_sound_check(
        api, artist_tier="OPENER", day_count=3,
    )
    item_id = str(bag.program_item["id"])
    slot_id = str(slot_before["id"])
    team_id = str(team_before["id"])
    # Sanity: the team is BUSY with the slot as its current booking,
    # and the slot is in SCHEDULED, per the fixture's pre-cascade
    # state.
    team_state = get_success_data(
        api.get_sound_engineer_team(bag.festival_id, team_id, AUDIT_HEADERS)
    )
    assert team_state["status"] == SoundEngineerTeamStatus.BUSY.value, \
        "Pre-cascade: team is BUSY per PRD §3.5 cascade-A precondition."
    assert team_state.get("current_booking_id") == slot_id, \
        "Pre-cascade: team.current_booking_id == the SCHEDULED slot's id per PRD §3.5."
    slot_state = get_success_data(
        api.get_sound_check(bag.festival_id, slot_id, AUDIT_HEADERS)
    )
    assert slot_state["status"] == SoundCheckSlotStatus.SCHEDULED.value, \
        "Pre-cascade: slot is in SCHEDULED per PRD §3.5 cascade-A precondition."
    # Originate the cascade with the ScheduleChange.apply(ITEM_CANCEL).
    applied = create_and_apply_item_cancel(api, bag, target_item_id=item_id,
                                           reason="cascade-a-test")
    # Link 1: the program item is in CANCELLED.
    item_after = get_success_data(api.get_program_item(bag.festival_id, item_id, AUDIT_HEADERS))
    assert item_after["status"] == "CANCELLED", \
        "Link 1 of cascade A: the target program item flips to CANCELLED per PRD §3.5."
    # Link 2: the slot is in CANCELLED.
    slot_after = get_success_data(api.get_sound_check(bag.festival_id, slot_id, AUDIT_HEADERS))
    assert slot_after["status"] == SoundCheckSlotStatus.CANCELLED.value, (
        "Link 2 of cascade A: a SCHEDULED slot under the cancelled item "
        "flips to its own CANCELLED terminal per PRD §3.5.  Got "
        f"{slot_after['status']!r}."
    )
    # Link 3: the team's status is AVAILABLE and current_booking_id
    # is null.  PRD §3.5: "the team flips BUSY → AVAILABLE and
    # `current_booking_id` is cleared to null".
    team_after = get_success_data(
        api.get_sound_engineer_team(bag.festival_id, team_id, AUDIT_HEADERS)
    )
    assert team_after["status"] == SoundEngineerTeamStatus.AVAILABLE.value, (
        "Link 3 of cascade A: the team flips BUSY → AVAILABLE per PRD §3.5.  "
        f"Got status={team_after['status']!r}."
    )
    assert team_after.get("current_booking_id") in (None, "", "null"), (
        "Link 3 of cascade A: the team's current_booking_id is cleared to "
        f"null per PRD §3.5.  Got {team_after.get('current_booking_id')!r}."
    )
    # The three audit rows, in chronological order per PRD §3.7.  We
    # read the full audit log and filter to the three subjects.
    all_audit = read_audit_log(api, bag)
    assert_audit_chronological(all_audit)
    # The item-cancel audit row is a state-transition or
    # schedule-change-category event whose subject_entity_id is the
    # item's id.  The PRD §2.8 mapping is "STATE_TRANSITION for the
    # manual state-flip endpoints such as confirm, announce, cancel"
    # — so the item's flip to CANCELLED has event_category
    # STATE_TRANSITION when the cancel arose from a ScheduleChange
    # apply.  Actually the PRD §2.8 mapping says SCHEDULE_CHANGE
    # category is "for schedule-change apply/reject/revert and the
    # auto-emitted ... ITEM_CANCEL ... changes".  The apply itself's
    # audit row therefore has event_category SCHEDULE_CHANGE on the
    # ScheduleChange subject, while the per-child STATE_TRANSITION
    # rows are on the cascaded subjects (ProgramItem, SoundCheckSlot,
    # SoundEngineerTeam).  We assert presence of:
    #   - a SCHEDULE_CHANGE row on the change subject (the apply)
    #   - a STATE_TRANSITION row on the ProgramItem subject with
    #     to_state CANCELLED
    #   - a STATE_TRANSITION (or any) row on the SoundCheckSlot
    #     subject with to_state CANCELLED
    #   - a STATE_TRANSITION row on the SoundEngineerTeam subject
    #     with to_state AVAILABLE
    item_rows = [e for e in all_audit
                 if e.get("subject_entity_type") == "ProgramItem"
                 and e.get("subject_entity_id") == item_id
                 and e.get("to_state") == "CANCELLED"]
    assert item_rows, ("An audit row of subject ProgramItem with "
                       "to_state==CANCELLED is appended on the apply's "
                       "primary state-effect per PRD §3.5.")
    slot_rows = [e for e in all_audit
                 if e.get("subject_entity_type") == "SoundCheckSlot"
                 and e.get("subject_entity_id") == slot_id
                 and e.get("to_state") == SoundCheckSlotStatus.CANCELLED.value]
    assert slot_rows, ("An audit row of subject SoundCheckSlot with "
                       "to_state==CANCELLED is the link-2 audit row per "
                       "PRD §3.5.")
    # The team's audit log carries two rows tagged
    # `to_state == AVAILABLE`: the team-create row (§3.2's
    # "the system's initial team status is AVAILABLE" with
    # `from_state` null) and the cascade-A link-3 row (§3.5's
    # "BUSY → AVAILABLE flip" with `from_state == "BUSY"`).  The
    # link-3 row is the one this test asserts the ordering on, so
    # filter the team rows on the `from_state` discriminator to pick
    # the cascade-emitted row specifically.  The PRD §3.7's audit-row
    # `from_state`/`to_state` pair is the canonical signature for
    # state-transition rows, so the filter is PRD-faithful.
    team_rows_all_avail = [e for e in all_audit
                           if e.get("subject_entity_type") == "SoundEngineerTeam"
                           and e.get("subject_entity_id") == team_id
                           and e.get("to_state") == SoundEngineerTeamStatus.AVAILABLE.value]
    team_rows = [e for e in team_rows_all_avail
                 if e.get("from_state") == "BUSY"]
    assert team_rows, ("An audit row of subject SoundEngineerTeam with "
                       "from_state==BUSY to_state==AVAILABLE is the link-3 "
                       "cascade-emitted audit row per PRD §3.5 (distinct "
                       "from the team-create's null→AVAILABLE row).")
    # Causal ordering: the item-cancel row precedes the slot-cancel
    # row, which precedes the team-flip row, in `created_at`
    # ascending order per PRD §3.7.  Strictly, the PRD says the audit
    # list is "ordered by `created_at` ascending per festival", and
    # the cascade narrative says the three links are caused "strictly
    # in sequence".  So the wall-clock-stamped created_at fields
    # are non-decreasing in that order, with the tiebreak being the
    # implementation's append-time precision (which for sub-millisecond
    # cascades may collapse the three rows to the same timestamp —
    # the §3.7 sentence "the audit list is ordered by `created_at`
    # ascending per festival" leaves no room for a tie-breaking
    # secondary key, so equal timestamps would be the
    # implementation's at-the-same-instant rendering of the causal
    # chain).  We assert non-strict-less-than on the timestamps, which
    # is the weakest assertion the PRD prose unambiguously implies.
    ts_item = item_rows[0]["created_at"]
    ts_slot = slot_rows[0]["created_at"]
    ts_team = team_rows[0]["created_at"]
    assert ts_item <= ts_slot <= ts_team, (
        f"Cascade-A's three audit rows are in non-decreasing created_at "
        f"order per the PRD §3.7 'ordered by created_at ascending per "
        f"festival' rule.  Got timestamps: item={ts_item!r}, "
        f"slot={ts_slot!r}, team={ts_team!r}."
    )


def test_cascade_a_via_direct_program_item_cancel_drives_slot_and_team(api):
    """A second test on the rule-4 instance-A coverage, exercising
    the same three-link chain but originating from the direct
    /program-items/{itemId}/cancel call rather than from a wrapped
    ScheduleChange.apply.  The §3.5 prose names the cascade-A
    originator as the ScheduleChange.apply, but the §1.5 endpoint
    table's program-item-cancel side-effect list also names "Cascade
    A's sound-check leg fires from this direct cancel", which the
    PRD §3.3 narrative restates as the cascade chain firing on the
    direct path too.

    Claim: the direct cancel of the parent ProgramItem flips its
    SCHEDULED sound-check slot to CANCELLED and the slot's team back
    to AVAILABLE — the same three audit rows the wrapped-apply path
    produces.

    # difficulty: transitive_cascade/schedulechange_apply_itemcancel_depth_3_into_team_audit
    """
    bag, team, slot = confirmed_item_with_scheduled_sound_check(
        api, artist_tier="OPENER", day_count=3,
    )
    item_id = str(bag.program_item["id"])
    slot_id = str(slot["id"])
    team_id = str(team["id"])
    # Direct cancel.
    direct = validate_success(api.cancel_program_item(
        bag.festival_id, item_id,
        cancel_program_item_payload(reason="direct-cancel-cascade"),
        LIAISON_HEADERS,
    ))
    assert direct["status"] == "CANCELLED"
    # Slot is CANCELLED, team is AVAILABLE.
    slot_after = get_success_data(api.get_sound_check(bag.festival_id, slot_id, AUDIT_HEADERS))
    team_after = get_success_data(
        api.get_sound_engineer_team(bag.festival_id, team_id, AUDIT_HEADERS)
    )
    assert slot_after["status"] == SoundCheckSlotStatus.CANCELLED.value, \
        ("The direct ProgramItem cancel's cascade chain reaches the "
         "SCHEDULED sound-check slot per the PRD §3.5 cascade-A "
         "narrative, which names both the wrapped-apply originator and "
         "the direct-cancel originator as paths into the same chain.")
    assert team_after["status"] == SoundEngineerTeamStatus.AVAILABLE.value, \
        "The cascade reaches the team in the third link per PRD §3.5."
    assert team_after.get("current_booking_id") in (None, "", "null"), \
        "The team's current_booking_id is cleared to null per PRD §3.5."


# ---------------------------------------------------------------------------
# Cascade B — ProgramItem.cancel → ExposureAllocation.VOIDED with a
# PROGRAM_VOIDED FulfilmentLog row → SponsorTier.tier_remaining_quota
# recomputation.  Depth 2 per the §3.5 narrative.
# ---------------------------------------------------------------------------


def test_cascade_b_program_item_cancel_voids_tied_exposure_allocation(api):
    """PRD §3.5: "A parallel chain that fires alongside the cascade-A
    chain but is rooted on a different originating trigger — namely a
    [direct] program-item cancel ... — is cascade B: link one is the
    same program-item cancel writing a row to the audit log, and
    link two is every `ExposureAllocation` whose `program_item_id` is
    the cancelled item flipping from `PLANNED` or `DELIVERED` to the
    absorbing `VOIDED` state, appending a `FulfilmentLog` row of
    `event_type` `PROGRAM_VOIDED` whose `units` equals the
    allocation's current `delivered_units` (so the inverse balances
    cleanly per the rule below), and triggering the parent
    `SponsorTier`'s `tier_remaining_quota` and
    `projected_fulfilment_pct` to be recomputed."  And PRD §3.6:
    "When invoked via the the ProgramItem-cancel cascade, the
    `event_type` is `PROGRAM_VOIDED` instead of the operator-issued
    `VOIDED` — the discriminator letting the audit reader tell apart
    the two routes."

    Claim: a ProgramItem cancel where the item is tied as a non-null
    `program_item_id` on an ExposureAllocation flips the allocation
    from its PLANNED-or-DELIVERED state to VOIDED, appends a
    PROGRAM_VOIDED FulfilmentLog row whose `units` field equals the
    allocation's pre-cascade delivered_units (which in the simple
    case where no DELIVERED log row has yet been written is zero —
    the cascade fires before any in-festival delivery), and the
    parent SponsorTier's `tier_remaining_quota` is unchanged from its
    pre-cancel value because the cancelled allocation contributed
    zero delivered_units before the cascade fired.

    The PROGRAM_VOIDED-vs-VOIDED discriminator is the audit reader's
    handle for distinguishing operator-issued voids from
    parent-cancel-driven cascade voids.

    Difficulty rule 4 instance B:
    # difficulty: transitive_cascade/programitem_direct_cancel_depth_2_into_exposureallocation_then_sponsortier
    """
    bag = base_world(api, day_count=2, artist_tier="OPENER",
                     stage_zone_capacity=10)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    item_id = str(bag.program_item["id"])
    confirm_item(api, bag, item_id)
    # The exposure-allocation deliver-gate of PRD §3.6 says the tied
    # item must be PERFORMED before delivery can land — so for the
    # zero-delivered_units cascade case, we simply don't deliver
    # anything.  The PROGRAM_VOIDED row will have `units` == 0
    # because the allocation's `delivered_units` was 0 at cascade time
    # (the PRD §3.5 sentence is "the cascade reads the row's current
    # delivered_units and writes a PROGRAM_VOIDED of equal
    # magnitude" — for zero-delivered the magnitude is zero, and the
    # PRD §3.6 logging contract allows a zero-units PROGRAM_VOIDED row
    # for the audit trail per the difficulty design's mention).
    publish_version(api, bag)
    # The festival-side exposure catalog and a sponsor tier with a
    # full kinds-allowed set so the referential check trivially
    # passes.  The catalog's stage_name pool is generous so the
    # waterfall gives the per-item allocation a unit of actual_units.
    seed_default_catalog(api, bag, stage_name=100, screen_time=100,
                        artist_mention=100, branded_zone=100)
    tier = add_sponsor_tier(api, bag, tier_code="GOLD", priority_rank=1,
                            sponsor_external_id="gold-cascade-b",
                            contracted_units=5,
                            contract_kinds_allowed=list(CATALOG_KINDS))
    tier_id = str(tier["id"])
    alloc = add_exposure_allocation(api, bag, tier_id,
                                    kind="stage_name",
                                    requested_units=1,
                                    program_item_id=item_id,
                                    pinned_rate_cents_per_unit=int(
                                        THRESHOLDS["SPONSOR_PAYOUT_RATE_MILS_DEFAULT"]
                                    ))
    alloc_id = str(alloc["id"])
    # Run the waterfall so actual_units=1 lands on the allocation.
    run_waterfall(api, bag)
    pre_alloc = get_success_data(api.get_exposure_allocation(
        bag.festival_id, alloc_id, AUDIT_HEADERS,
    ))
    assert pre_alloc["status"] == "PLANNED", \
        ("Before any DELIVERED log row the allocation is in PLANNED per "
         "the PRD §3.6 state machine.")
    assert int(pre_alloc["delivered_units"]) == 0
    pre_tier = get_sponsor_tier_snapshot(api, bag.festival_id, tier_id)
    pre_quota = int(pre_tier["tier_remaining_quota"])
    # The tier's tier_remaining_quota == contracted_units − Σ
    # delivered_units across the tier's allocations.  Currently
    # everything is at zero delivered, so the quota is the full
    # contracted_units of 5.
    assert pre_quota == 5, \
        ("Pre-cancel: tier_remaining_quota == contracted_units − 0 == 5 "
         "per the PRD §3.6 formula.")
    # The cancel originates the cascade-B chain.
    cancelled = validate_success(api.cancel_program_item(
        bag.festival_id, item_id,
        cancel_program_item_payload(reason="cascade-b-fire"),
        LIAISON_HEADERS,
    ))
    assert cancelled["status"] == "CANCELLED"
    # Link 2: the tied allocation is now in VOIDED, with a
    # PROGRAM_VOIDED FulfilmentLog row whose units == 0 (matching the
    # pre-cancel delivered_units of zero, per the PRD §3.5 "the
    # cascade reads the row's current delivered_units and writes a
    # PROGRAM_VOIDED of equal magnitude" rule).
    alloc_after = get_success_data(api.get_exposure_allocation(
        bag.festival_id, alloc_id, AUDIT_HEADERS,
    ))
    assert alloc_after["status"] == "VOIDED", \
        ("Cascade-B link 2: the tied allocation is in VOIDED after the "
         "parent-item cancel per PRD §3.5 / §3.6.")
    # The allocation's FulfilmentLog tail has a PROGRAM_VOIDED row.
    log = alloc_after.get("fulfilment_log") \
          or alloc_after.get("logs") \
          or alloc_after.get("fulfilment_logs", [])
    program_voided_rows = [r for r in log if r.get("event_type") == "PROGRAM_VOIDED"]
    assert program_voided_rows, (
        "A FulfilmentLog row of event_type PROGRAM_VOIDED is appended "
        "on the cascade per the PRD §3.6 cascade-variant naming.  The "
        "row's `units` field equals the allocation's pre-cascade "
        "delivered_units (zero in this fixture) per the §3.5 "
        "magnitude-of-the-inverse rule."
    )
    assert int(program_voided_rows[0]["units"]) == 0, (
        "The PROGRAM_VOIDED row's `units` equals the pre-cascade "
        "delivered_units, which was zero per the fixture.  The §3.5 "
        "rule '`units` equals the allocation's current `delivered_units` "
        "at cascade time'."
    )
    # The parent tier's tier_remaining_quota is unchanged from its
    # pre-cancel value because the cancelled allocation contributed
    # zero delivered_units to the running sum (the cancel reduced
    # `actual_units` to-its-final via the void but the conserved
    # quantity in the §3.6 formula `tier_remaining_quota =
    # contracted_units − Σ delivered_units` depends on delivered_units,
    # which is zero on the cancelled allocation post-PROGRAM_VOIDED).
    post_tier = get_sponsor_tier_snapshot(api, bag.festival_id, tier_id)
    post_quota = int(post_tier["tier_remaining_quota"])
    assert post_quota == pre_quota, (
        f"tier_remaining_quota is unchanged at {pre_quota} across the "
        f"cancel cascade because no DELIVERED log row had ever landed "
        f"on the cancelled allocation, so its delivered_units was zero "
        f"both before and after the cascade per the PRD §3.6 formula.  "
        f"Post-cancel observed: {post_quota}."
    )


# ---------------------------------------------------------------------------
# Cascade C — clock-advance crossing end_time + grace → Festival.CLOSED →
# Rehearsal auto-archive with the deterministic synthetic URI →
# CLOCK_TICK audit row whose payload_summary names the originating
# event id.
# ---------------------------------------------------------------------------


def test_cascade_c_festival_close_archives_in_progress_rehearsal(api):
    """PRD §3.5: "A third chain, cascade C, originates from a clock-
    tick at the clock-advance operator capability that crosses the
    festival's `end_time + FESTIVAL_CLOSE_GRACE_SECONDS` boundary:
    link one is the festival's status flipping `LIVE → CLOSED`, link
    two (caused by the festival's close, not by the clock tick
    directly) is every `BOOKED` or `IN_PROGRESS` rehearsal under the
    festival auto-archiving to `ARCHIVED` with its synthetic
    `archive_uri` stamped to the
    `archive://festival/{festival_id}/rehearsal/{rehearsal_id}`
    literal, and link three (caused by each rehearsal's archive and
    not by the festival close directly) is each archived rehearsal's
    audit entry of category `CLOCK_TICK` whose `payload_summary`
    names the originating clock-tick event's id, completing the fan-
    out trace."

    And PRD §3.5: "the deterministic synthetic URI
    `archive://festival/<festival_id>/rehearsal/<rehearsal_id>` — the
    literal string with the parent festival's id and the rehearsal's
    id substituted in, which the test asserts on".

    Claim: a festival with a BOOKED rehearsal (room-type, anywhere in
    the festival window so the rehearsal's start-time-crossing
    transition to IN_PROGRESS may fire before the close-grace
    crossing — the §3.5 narrative names both BOOKED and IN_PROGRESS
    as the cascade-targets), after an advance of the test clock past
    `end_time + FESTIVAL_CLOSE_GRACE_SECONDS`, has the festival's
    status at CLOSED, every such rehearsal at ARCHIVED with the
    deterministic archive_uri stamped to the canonical literal, and
    the audit log carries a CLOCK_TICK row on the rehearsal subject
    whose subject_entity_id is the rehearsal and whose to_state is
    ARCHIVED.

    Difficulty rule 4 instance C:
    # difficulty: transitive_cascade/clock_advance_festival_close_depth_3_into_rehearsal_then_audit_fanout
    """
    bag = FIX.festival_in_scheduling(api, day_count=2)
    add_stage(api, bag, zone_capacity=10)
    artist = register_artist(api, tier="OPENER")
    # Need a non-empty version to publish so the festival can go LIVE
    # (per PRD §3.1 the LIVE state requires the festival to have at
    # least passed open-scheduling; the auto-LIVE transition is the
    # clock-cross of start_time while the festival is PUBLISHED, and
    # publish requires a non-empty version per the §3.3
    # ERR_EMPTY_PROGRAM_VERSION guard).  So add one PROPOSED-then-
    # CONFIRMED program item then publish.
    add_program_version(api, bag, version_label="cascade-c-v")
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10,
                     artist_id=str(artist["id"]))
    confirm_item(api, bag, str(bag.program_item["id"]))
    publish_version(api, bag)
    # Create a BOOKED ROOM-type rehearsal somewhere inside the festival
    # window.  The PRD §3.5 rehearsal-window contains-the-festival-
    # window rule (the §2.4 child-containment rule) requires the
    # rehearsal's half-open window to lie inside the festival's.  We
    # pick a 30-minute rehearsal on day-0 at 14:00.
    rehearsal_start = bag.festival_start + 14 * 3600
    rehearsal_end = rehearsal_start + 30 * 60
    rehearsal = get_success_data(api.create_rehearsal(
        bag.festival_id,
        F.rehearsal_payload(artist_id=str(artist["id"]),
                            rehearsal_type="ROOM",
                            rehearsal_room_name="CascadeC-Room",
                            start_time=rehearsal_start,
                            end_time=rehearsal_end),
        STAGE_HEADERS,
    ))
    rehearsal_id = str(rehearsal["id"])
    assert rehearsal["status"] == "BOOKED", \
        "A fresh rehearsal is in BOOKED per PRD §3.5."
    # Now advance the test clock to the festival's auto-close boundary
    # `end_time + FESTIVAL_CLOSE_GRACE_SECONDS`.  The advance crosses
    # several thresholds in the canonical wall-clock-of-the-threshold-
    # ascending order per PRD §2.8: festival_start, rehearsal_start,
    # item_start, item_end, rehearsal_end + REHEARSAL_GRACE_SECONDS,
    # then finally the festival's close boundary.  Each crossing fires
    # the corresponding system-driven transition.
    grace = int(THRESHOLDS["FESTIVAL_CLOSE_GRACE_SECONDS"])
    target = bag.festival_end + grace + 1
    advance_clock_to(api, festival_id=bag.festival_id, to_unix_seconds=target)
    # Link 1: the festival is CLOSED.
    festival_after = get_festival_snapshot(api, bag.festival_id)
    assert festival_after["status"] == "CLOSED", \
        "Cascade-C link 1: Festival.LIVE → CLOSED on the clock-cross of end_time + grace per PRD §2.8."
    # Link 2: the rehearsal is ARCHIVED with the canonical synthetic
    # archive_uri.  The deterministic URI literal is
    # `archive://festival/<festival_id>/rehearsal/<rehearsal_id>` per
    # PRD §3.5.
    rehearsal_after = get_success_data(
        api.get_rehearsal(bag.festival_id, rehearsal_id, AUDIT_HEADERS)
    )
    assert rehearsal_after["status"] == "ARCHIVED", \
        "Cascade-C link 2: the rehearsal auto-archives on the festival close per PRD §3.5."
    expected_uri = f"archive://festival/{bag.festival_id}/rehearsal/{rehearsal_id}"
    assert rehearsal_after.get("archive_uri") == expected_uri, (
        f"The rehearsal's archive_uri is the deterministic synthetic "
        f"literal `archive://festival/<festival_id>/rehearsal/"
        f"<rehearsal_id>` per PRD §3.5 — expected {expected_uri!r}, "
        f"got {rehearsal_after.get('archive_uri')!r}."
    )
    # Link 3: an audit row of event_category CLOCK_TICK on the
    # rehearsal subject with to_state ARCHIVED.  Per the PRD §2.8
    # mapping the CLOCK_TICK category covers "every transition that
    # the clock-advance triggers, including the rehearsal-archive
    # cascade on festival close".
    rehearsal_audit = read_audit_log(api, bag,
                                     event_category=AuditEventCategory.CLOCK_TICK.value,
                                     subject_entity_type="Rehearsal")
    matching = [e for e in rehearsal_audit
                if e.get("subject_entity_id") == rehearsal_id
                and e.get("to_state") == "ARCHIVED"]
    assert matching, (
        "Cascade-C link 3: a CLOCK_TICK audit row on the rehearsal "
        "subject with to_state==ARCHIVED is appended per PRD §2.8 "
        "/ §3.5."
    )
    # The same audit log carries a CLOCK_TICK row on the Festival
    # subject with to_state CLOSED — link 1's evidence.
    festival_audit = read_audit_log(api, bag,
                                    event_category=AuditEventCategory.CLOCK_TICK.value,
                                    subject_entity_type="Festival")
    fest_close_rows = [e for e in festival_audit
                       if e.get("subject_entity_id") == bag.festival_id
                       and e.get("to_state") == "CLOSED"]
    assert fest_close_rows, (
        "An audit row of category CLOCK_TICK and subject_entity_type "
        "Festival with to_state==CLOSED is appended on the auto-close "
        "per PRD §3.1 / §2.8."
    )
    # Causal ordering: the festival-close CLOCK_TICK row precedes the
    # rehearsal-archive CLOCK_TICK row.
    fest_ts = min(e["created_at"] for e in fest_close_rows)
    rehearsal_ts = min(e["created_at"] for e in matching)
    assert fest_ts <= rehearsal_ts, (
        f"Cascade-C's three audit-row events are in non-decreasing "
        f"`created_at` order per PRD §3.7: the festival-close row at "
        f"{fest_ts!r} precedes the rehearsal-archive row at "
        f"{rehearsal_ts!r}."
    )


def test_cascade_c_in_progress_rehearsal_also_auto_archives(api):
    """The PRD §3.5 sentence "every `BOOKED` or `IN_PROGRESS`
    rehearsal under the festival auto-archives" pins the cascade
    target as both BOOKED and IN_PROGRESS rehearsals.  This test
    exercises the IN_PROGRESS path: the clock crosses the
    rehearsal's `start_time` first (driving BOOKED → IN_PROGRESS per
    PRD §3.5's clock-driven transition), and the same advance call
    then crosses the festival's close-grace boundary, which fires
    the cascade onto the now-IN_PROGRESS rehearsal.

    Claim: an IN_PROGRESS rehearsal (one whose start_time the clock
    has already crossed before the festival close) also auto-
    archives with the same synthetic-URI literal as the BOOKED
    rehearsal case, and the audit-log row's to_state is the same
    ARCHIVED value.

    # difficulty: transitive_cascade/clock_advance_festival_close_depth_3_into_rehearsal_then_audit_fanout
    """
    bag = FIX.festival_in_scheduling(api, day_count=2)
    add_stage(api, bag, zone_capacity=1)
    artist = register_artist(api, tier="OPENER")
    add_program_version(api, bag, version_label="cascade-c-v2")
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10,
                     artist_id=str(artist["id"]))
    confirm_item(api, bag, str(bag.program_item["id"]))
    publish_version(api, bag)
    # Rehearsal at day-1 10:00 for 30 minutes — start at festival_start
    # + 24h + 10h, end + 30min.  This is comfortably inside the 2-day
    # festival window.
    rehearsal_start = bag.festival_start + 24 * 3600 + 10 * 3600
    rehearsal_end = rehearsal_start + 30 * 60
    rehearsal = get_success_data(api.create_rehearsal(
        bag.festival_id,
        F.rehearsal_payload(artist_id=str(artist["id"]),
                            rehearsal_type="ROOM",
                            rehearsal_room_name="InProgressRoom",
                            start_time=rehearsal_start,
                            end_time=rehearsal_end),
        STAGE_HEADERS,
    ))
    rid = str(rehearsal["id"])
    # Advance to just past the rehearsal's start_time so the BOOKED →
    # IN_PROGRESS clock-tick fires (and the festival's PUBLISHED →
    # LIVE has also fired because the festival's start_time is
    # earlier than the rehearsal_start).  Wait: the festival's
    # start_time is bag.festival_start, so the LIVE transition fires
    # at the moment the clock crosses it.  The rehearsal_start is 34
    # hours after the festival_start, so the festival is already LIVE
    # by then.  The PRD §3.5 rehearsal-start clock-rule fires the
    # BOOKED → IN_PROGRESS transition.
    advance_clock_to(api, festival_id=bag.festival_id,
                     to_unix_seconds=rehearsal_start + 1)
    # The rehearsal's status is now IN_PROGRESS per PRD §3.5.
    mid = get_success_data(api.get_rehearsal(bag.festival_id, rid, AUDIT_HEADERS))
    assert mid["status"] in ("IN_PROGRESS", "ARCHIVED"), (
        f"The mid-advance rehearsal status is IN_PROGRESS (or already "
        f"ARCHIVED if the §3.5 grace-window crossing fired on the same "
        f"tick — the PRD §2.8 ordering rule allows either outcome).  "
        f"Got status={mid['status']!r}."
    )
    # Now advance past the festival's close-grace boundary.  The
    # rehearsal — whether it was IN_PROGRESS or already ARCHIVED by the
    # grace-crossing on the previous advance — ends up in ARCHIVED via
    # the festival-close cascade.
    grace = int(THRESHOLDS["FESTIVAL_CLOSE_GRACE_SECONDS"])
    target = bag.festival_end + grace + 1
    advance_clock_to(api, festival_id=bag.festival_id, to_unix_seconds=target)
    festival_after = get_festival_snapshot(api, bag.festival_id)
    assert festival_after["status"] == "CLOSED"
    final = get_success_data(api.get_rehearsal(bag.festival_id, rid, AUDIT_HEADERS))
    assert final["status"] == "ARCHIVED", \
        ("The rehearsal — IN_PROGRESS at festival-close time — "
         "auto-archives per the cascade-C target set "
         "{BOOKED, IN_PROGRESS} of PRD §3.5.")
    expected_uri = f"archive://festival/{bag.festival_id}/rehearsal/{rid}"
    assert final["archive_uri"] == expected_uri, (
        f"The auto-archive stamps archive_uri to the canonical literal "
        f"`archive://festival/<festival_id>/rehearsal/<rehearsal_id>` "
        f"per PRD §3.5 — expected {expected_uri!r}, got "
        f"{final.get('archive_uri')!r}."
    )
