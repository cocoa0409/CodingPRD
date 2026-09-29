"""State-machine behaviour: revision loops, closing, cascades and boundaries.

Every test builds its own preconditions from an empty database through PRD
endpoints, so it is independent of every other test in the suite.
"""
from test_helpers import (
    as_run_kinds,
    assert_spot_count_conservation,
    item_by_sequence,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Private helpers (this module only)
# ---------------------------------------------------------------------------

def _armed_scenario():
    """The canonical broadcast day, validated and armed, nothing aired yet."""
    scn = fx.setup_playlist_scenario()
    fx.validate_playlist(scn)
    scn["playlist"] = fx.arm_playlist(scn)
    return scn


def _revision_items(scn):
    """A three-element replacement day that still fills the 3600-second window."""
    return [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": scn["assets"]["prog1"]["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1800},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": scn["assets"]["spot"]["id"],
         "spot_order_id": scn["order"]["id"],
         "scheduled_start_utc": "2026-08-01T12:30:00Z",
         "scheduled_duration_seconds": 30},
        {"sequence_number": 3, "element_kind": "PROGRAM",
         "asset_id": scn["assets"]["prog1"]["id"],
         "scheduled_start_utc": "2026-08-01T12:30:30Z",
         "scheduled_duration_seconds": 1770},
    ]


# ===========================================================================
# Traffic revisions: the backward edge out of ARMED
# ===========================================================================

def test_revision_pulls_an_armed_playlist_back_to_imported(api):
    """A revision drops the arm, bumps the revision counter and clears armed_at_utc.

    PRD §3.5: "Applying a revision increments `traffic_revision` by one and **pulls a `VALIDATED` or `ARMED` playlist back to `IMPORTED`**, clearing `armed_at_utc` to null."

    Design: Corner/state_machines/traffic_revision_returns_an_armed_playlist_to_imported_and_reconserves_spots
    """
    scn = _armed_scenario()
    armed_version = scn["playlist"]["version"]
    assert scn["playlist"]["status"] == "ARMED"
    assert scn["playlist"]["armed_at_utc"] is not None

    resp = api.apply_traffic_revision(
        scn["playlist"]["id"],
        {"expected_playlist_version": armed_version,
         "items": _revision_items(scn)},
        scn["traffic_headers"],
    )
    revised = validate_success(resp)

    assert revised["status"] == "IMPORTED"
    assert revised["traffic_revision"] == 2
    assert revised["armed_at_utc"] is None
    assert revised["version"] == armed_version + 1


def test_revision_replaces_every_scheduled_element_wholesale(api):
    """The seven scheduled elements are deleted and the three supplied ones take over.

    PRD §3.5: "Every existing item whose `playout_status` is still `SCHEDULED` is deleted and replaced by the supplied revision items"

    Design: Corner/state_machines/traffic_revision_returns_an_armed_playlist_to_imported_and_reconserves_spots
    """
    scn = _armed_scenario()

    resp = api.apply_traffic_revision(
        scn["playlist"]["id"],
        {"expected_playlist_version": scn["playlist"]["version"],
         "items": _revision_items(scn)},
        scn["traffic_headers"],
    )
    revised = validate_success(resp)

    items, meta = validate_paginated(
        api.list_playlist_items(scn["playlist"]["id"], scn["traffic_headers"])
    )
    assert meta["total_count"] == 3
    assert [item["sequence_number"] for item in items] == [1, 2, 3]
    assert all(item["playout_status"] == "SCHEDULED" for item in items)

    assert revised["item_count"] == 3
    assert revised["blocked_item_count"] == 0
    assert revised["scheduled_total_seconds"] == 3600
    assert revised["projected_end_variance_seconds"] == 0
    assert revised["commercial_seconds_by_hour"] == {"0": 30}


def test_revision_recomputes_the_referenced_order_spot_counters(api):
    """Dropping one of the two commercials returns that spot to the unplaced slack.

    PRD §3.5: "Spot orders referenced by the removed items and by the added items have their `scheduled_spots` and `unplaced_spots` recomputed so the spot-count invariant holds"

    Design: Corner/state_machines/traffic_revision_returns_an_armed_playlist_to_imported_and_reconserves_spots
    """
    scn = _armed_scenario()
    before = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert before["scheduled_spots"] == 2
    assert before["unplaced_spots"] == 2

    validate_success(api.apply_traffic_revision(
        scn["playlist"]["id"],
        {"expected_playlist_version": scn["playlist"]["version"],
         "items": _revision_items(scn)},
        scn["traffic_headers"],
    ))

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["scheduled_spots"] == 1
    assert order["unplaced_spots"] == 3
    assert order["aired_spots"] == 0
    assert order["short_aired_spots"] == 0
    assert order["credited_spots"] == 0
    assert order["status"] == "OPEN"
    assert order["credit_accrued_cents"] == 0
    assert order["ordered_spots"] == 4
    assert_spot_count_conservation(order)


def test_the_revision_loop_is_traversable_again_after_a_revision(api):
    """After the revision the day validates and arms once more, rewriting armed_at_utc.

    PRD §3.5: "The cycle `IMPORTED` to `VALIDATED` to `ARMED` and back to `IMPORTED` is the ordinary revision loop and may be traversed any number of times."
    PRD §3.5: "A successful arm writes `armed_at_utc` at the current logical time and increments `version`."

    Design: Corner/state_machines/traffic_revision_returns_an_armed_playlist_to_imported_and_reconserves_spots
    """
    scn = _armed_scenario()
    validate_success(api.apply_traffic_revision(
        scn["playlist"]["id"],
        {"expected_playlist_version": scn["playlist"]["version"],
         "items": _revision_items(scn)},
        scn["traffic_headers"],
    ))

    validated = fx.drive_playlist(scn, scn["playlist"]["id"], "VALIDATED")
    assert validated["status"] == "VALIDATED"

    fx.set_clock("2026-08-01T09:05:00Z")
    rearmed = fx.drive_playlist(scn, scn["playlist"]["id"], "ARMED")
    assert rearmed["status"] == "ARMED"
    assert rearmed["armed_at_utc"] == "2026-08-01T09:05:00Z"
    assert rearmed["version"] > validated["version"]


# ===========================================================================
# Closing an on-air day: the skip sweep and the final settlement
# ===========================================================================

def _day_with_second_spot_playing():
    """The canonical day on air: element one played in full, element two playing."""
    scn = fx.setup_on_air_playlist()
    fx.air_item(scn, item_by_sequence(scn["items"], 1),
                "2026-08-01T12:00:00Z", "2026-08-01T12:30:00Z", 1800)
    item2 = item_by_sequence(scn["items"], 2)
    fx.cue_item(scn, item2["id"], "2026-08-01T12:30:00Z")
    fx.start_item(scn, item2["id"], "2026-08-01T12:30:00Z")
    return scn


def _both_spots_short_aired(scn):
    """End both commercials 28 seconds in, two seconds short of the contracted 30."""
    item2 = item_by_sequence(scn["items"], 2)
    item3 = item_by_sequence(scn["items"], 3)
    fx.set_clock("2026-08-01T12:30:28Z")
    fx.end_item(scn, item2["id"], "2026-08-01T12:30:28Z", 28)
    fx.cue_item(scn, item3["id"], "2026-08-01T12:30:28Z")
    fx.start_item(scn, item3["id"], "2026-08-01T12:30:28Z")
    fx.set_clock("2026-08-01T12:30:56Z")
    fx.end_item(scn, item3["id"], "2026-08-01T12:30:56Z", 28)
    return scn


def test_close_is_refused_while_an_element_is_still_playing(api):
    """An on-air day cannot be closed out from under a radiating element.

    PRD §3.5: "**Closing** an on-air playlist requires that no item is still `PLAYING`, otherwise `ERR_PLAYLIST_ITEM_STILL_PLAYING`"

    Design: Corner/state_machines/closing_an_on_air_playlist_sweeps_skips_and_runs_final_settlement
    """
    scn = _day_with_second_spot_playing()
    assert fx.read_item(item_by_sequence(scn["items"], 2)["id"],
                        scn["mco_headers"])["playout_status"] == "PLAYING"

    resp = api.change_playlist_state(scn["playlist"]["id"],
                                     {"target_status": "CLOSED"},
                                     scn["mco_headers"])
    validate_error(resp, "ERR_PLAYLIST_ITEM_STILL_PLAYING")

    assert fx.read_playlist(scn["playlist"]["id"],
                            scn["mco_headers"])["status"] == "ON_AIR"


def test_close_sweeps_the_untouched_tail_into_system_sourced_skips(api):
    """Closing stamps closed_at_utc and skips the four elements that never ran.

    PRD §3.5: "The close writes `closed_at_utc` at the current logical time, flips every item still in `SCHEDULED` or `CUED` to `SKIPPED` with a system-sourced skip row appended to the as-run log for each"

    Design: Corner/state_machines/closing_an_on_air_playlist_sweeps_skips_and_runs_final_settlement
    """
    scn = _both_spots_short_aired(_day_with_second_spot_playing())

    closed = fx.drive_playlist(scn, scn["playlist"]["id"], "CLOSED",
                               headers=scn["mco_headers"])
    assert closed["status"] == "CLOSED"
    assert closed["closed_at_utc"] == "2026-08-01T12:30:56Z"

    skip_rows, skip_meta = validate_paginated(api.get_playlist_as_run(
        scn["playlist"]["id"], scn["traffic_headers"],
        params={"event_kind": "SKIP"},
    ))
    assert skip_meta["total_count"] == 4
    assert as_run_kinds(skip_rows) == ["SKIP"] * len(skip_rows)
    assert all(row["source"] == "SYSTEM" for row in skip_rows)

    skipped, skipped_meta = validate_paginated(api.list_playlist_items(
        scn["playlist"]["id"], scn["traffic_headers"],
        params={"playout_status": "SKIPPED"},
    ))
    assert skipped_meta["total_count"] == 4
    assert sorted(item["sequence_number"] for item in skipped) == [4, 5, 6, 7]

    every_item = fx.list_items(scn["playlist"]["id"], scn["traffic_headers"])
    assert not [item for item in every_item
                if item["playout_status"] in ("SCHEDULED", "CUED")]


def test_both_commercials_settle_as_short_airs_not_as_full_airs(api):
    """Twenty-eight seconds of a thirty-second spot is a short air, not a full air.

    PRD §3.9: "It is a **short air** when its `playout_status` is `TRUNCATED`, or when its `playout_status` is `PLAYED` but its `measured_duration_seconds` falls below that tolerance boundary."

    Design: Corner/state_machines/closing_an_on_air_playlist_sweeps_skips_and_runs_final_settlement
    """
    scn = _both_spots_short_aired(_day_with_second_spot_playing())
    for sequence_number in (2, 3):
        item = fx.read_item(item_by_sequence(scn["items"], sequence_number)["id"],
                            scn["mco_headers"])
        assert item["playout_status"] == "PLAYED"
        assert item["measured_duration_seconds"] == 28

    fx.drive_playlist(scn, scn["playlist"]["id"], "CLOSED",
                      headers=scn["mco_headers"])

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["short_aired_spots"] == 2
    assert order["aired_spots"] == 0
    assert order["scheduled_spots"] == 0
    assert_spot_count_conservation(order)


def test_final_settlement_credits_every_unplaced_spot_in_full(api):
    """The close adds two unplaced spots at the full rate on top of the short-air credits.

    PRD §3.9: "On the **final** basis, every ordered spot must be accounted for: the unplaced count is the order's `ordered_spots` less the number of linked elements, floored at zero, and each unplaced spot is credited in full at the rounded per-spot rate, that total being added to the credit."

    Design: Corner/state_machines/closing_an_on_air_playlist_sweeps_skips_and_runs_final_settlement
    """
    scn = _both_spots_short_aired(_day_with_second_spot_playing())

    closed = fx.drive_playlist(scn, scn["playlist"]["id"], "CLOSED",
                               headers=scn["mco_headers"])

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["unplaced_spots"] == 2
    assert order["credit_accrued_cents"] == 213334
    assert closed["reconciliation_credit_cents"] == 213334


def test_close_settlement_drives_the_order_to_closed_with_credit(api):
    """Every ordered spot is accounted for, so the order lands on CLOSED_WITH_CREDIT.

    PRD §3.9: "It moves from `PARTIALLY_CREDITED` to `CLOSED_WITH_CREDIT` at close settlement when the four settled counters plus `unplaced_spots` account for the whole `ordered_spots`, `scheduled_spots` is zero, and the sum of `credited_spots` and `unplaced_spots` is greater than zero, writing the final-basis credit into `credit_accrued_cents` and into the playlist's `reconciliation_credit_cents`."

    Design: Corner/state_machines/closing_an_on_air_playlist_sweeps_skips_and_runs_final_settlement
    """
    scn = _both_spots_short_aired(_day_with_second_spot_playing())

    fx.drive_playlist(scn, scn["playlist"]["id"], "CLOSED",
                      headers=scn["mco_headers"])

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["status"] == "CLOSED_WITH_CREDIT"
    assert order["scheduled_spots"] == 0
    assert order["credited_spots"] + order["unplaced_spots"] > 0


def test_a_closed_playlist_cannot_be_taken_back_on_air(api):
    """CLOSED is terminal, so there is no way back to ON_AIR.

    PRD §3.5: "`CLOSED` and `ABANDONED` are terminal. Anything else is refused with `ERR_PLAYLIST_INVALID_STATE`."

    Design: Corner/state_machines/closing_an_on_air_playlist_sweeps_skips_and_runs_final_settlement
    """
    scn = _both_spots_short_aired(_day_with_second_spot_playing())
    fx.drive_playlist(scn, scn["playlist"]["id"], "CLOSED",
                      headers=scn["mco_headers"])

    resp = api.change_playlist_state(scn["playlist"]["id"],
                                     {"target_status": "ON_AIR"},
                                     scn["mco_headers"])
    validate_error(resp, "ERR_PLAYLIST_INVALID_STATE")
    assert fx.read_playlist(scn["playlist"]["id"],
                            scn["mco_headers"])["status"] == "CLOSED"


# ===========================================================================
# Asset retraction: the three-hop block, arm reversal and spot credit
# ===========================================================================

def test_retraction_blocks_every_unaired_element_that_references_the_asset(api):
    """Both commercials fed by the pulled creative flip to BLOCKED on the content axis.

    PRD §3.4: "First, every playlist item referencing the asset whose `playout_status` is `SCHEDULED` or `CUED` has its `clearance_status` flipped to `BLOCKED`."

    Design: Corner/state_machines/cascade_b_retraction_blocks_items_reverts_the_arm_and_credits_the_spots
    """
    scn = _armed_scenario()

    resp = api.retract_asset(scn["assets"]["spot"]["id"],
                             {"reason": "advertiser pulled the creative"},
                             scn["pd_headers"])
    retracted = validate_success(resp)
    assert retracted["status"] == "RETRACTED"

    blocked, meta = validate_paginated(api.list_all_playlist_items(
        scn["traffic_headers"],
        params={"playlist_id": scn["playlist"]["id"],
                "asset_id": scn["assets"]["spot"]["id"]},
    ))
    assert meta["total_count"] == 2
    assert sorted(item["sequence_number"] for item in blocked) == [2, 3]
    for item in blocked:
        assert item["clearance_status"] == "BLOCKED"
        assert item["playout_status"] == "SCHEDULED"


def test_retraction_reverts_the_armed_playlist_to_imported(api):
    """The block bubbles up: the day loses its arm and counts its blocked elements.

    PRD §3.4: "Second, caused by that flip, each owning playlist increments `blocked_item_count` and, when its `status` is `VALIDATED` or `ARMED`, reverts to `IMPORTED` with `armed_at_utc` cleared."

    Design: Corner/state_machines/cascade_b_retraction_blocks_items_reverts_the_arm_and_credits_the_spots
    """
    scn = _armed_scenario()
    fx.retract(scn, scn["assets"]["spot"]["id"],
               reason="advertiser pulled the creative")

    playlist = fx.read_playlist(scn["playlist"]["id"], scn["traffic_headers"])
    assert playlist["status"] == "IMPORTED"
    assert playlist["armed_at_utc"] is None
    assert playlist["blocked_item_count"] == 2
    assert playlist["traffic_revision"] == 1


def test_retraction_credits_the_blocked_spots_at_the_full_per_spot_rate(api):
    """Two blocked spots move from scheduled to credited at 100000 cents each.

    PRD §3.4: "Third, also caused by that flip, every newly blocked item that carries a `spot_order_id` moves one spot on that order from `scheduled_spots` to `credited_spots`, adds the full per-spot credit to `credit_accrued_cents`, and refreshes the order's `status` to `PARTIALLY_CREDITED` or `CLOSED_WITH_CREDIT` as described in §3.9."

    Design: Corner/state_machines/cascade_b_retraction_blocks_items_reverts_the_arm_and_credits_the_spots
    """
    scn = _armed_scenario()
    fx.retract(scn, scn["assets"]["spot"]["id"],
               reason="advertiser pulled the creative")

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["scheduled_spots"] == 0
    assert order["credited_spots"] == 2
    assert order["credit_accrued_cents"] == 200000
    assert order["status"] == "PARTIALLY_CREDITED"
    assert order["aired_spots"] == 0
    assert order["short_aired_spots"] == 0
    assert order["unplaced_spots"] == 2
    assert_spot_count_conservation(order)


def test_a_blocked_day_cannot_be_revalidated(api):
    """With two blocked elements the day cannot climb back towards the arm.

    PRD §3.5: "And `blocked_item_count` must be exactly 0, otherwise `ERR_UNCLEARED_CONTENT_ON_AIR`."

    Design: Corner/state_machines/cascade_b_retraction_blocks_items_reverts_the_arm_and_credits_the_spots
    """
    scn = _armed_scenario()
    fx.retract(scn, scn["assets"]["spot"]["id"],
               reason="advertiser pulled the creative")

    resp = api.change_playlist_state(scn["playlist"]["id"],
                                     {"target_status": "VALIDATED"},
                                     scn["mco_headers"])
    validate_error(resp, "ERR_UNCLEARED_CONTENT_ON_AIR")
    assert fx.read_playlist(scn["playlist"]["id"],
                            scn["traffic_headers"])["status"] == "IMPORTED"


# ===========================================================================
# The two axes of an element move independently
# ===========================================================================

def _cued_spot_then_retracted():
    """Element one played, element two cued, then its creative is pulled mid-break."""
    scn = fx.setup_on_air_playlist()
    fx.air_item(scn, item_by_sequence(scn["items"], 1),
                "2026-08-01T12:00:00Z", "2026-08-01T12:30:00Z", 1800)
    fx.cue_item(scn, item_by_sequence(scn["items"], 2)["id"],
                "2026-08-01T12:30:00Z")
    fx.retract(scn, scn["assets"]["spot"]["id"],
               reason="legal takedown mid-break")
    return scn


def test_a_mid_break_retraction_leaves_the_on_air_day_on_air(api):
    """Only a validated or armed day is pulled back; an on-air day keeps radiating.

    PRD §3.4: "Second, caused by that flip, each owning playlist increments `blocked_item_count` and, when its `status` is `VALIDATED` or `ARMED`, reverts to `IMPORTED` with `armed_at_utc` cleared."

    Design: Corner/state_machines/item_playout_and_clearance_axes_advance_independently
    """
    scn = _cued_spot_then_retracted()

    playlist = fx.read_playlist(scn["playlist"]["id"], scn["traffic_headers"])
    assert playlist["status"] == "ON_AIR"

    item2 = fx.read_item(item_by_sequence(scn["items"], 2)["id"],
                         scn["mco_headers"])
    assert item2["clearance_status"] == "BLOCKED"
    assert item2["playout_status"] == "CUED"


def test_a_blocked_cued_element_still_starts_and_ends_as_played(api):
    """Automation carries the cued element to PLAYED even though its content is blocked.

    PRD §3.6: "an element that is `PLAYED` and `BLOCKED` is perfectly reachable, because an asset may be retracted after the element has already aired."

    Design: Corner/state_machines/item_playout_and_clearance_axes_advance_independently
    """
    scn = _cued_spot_then_retracted()
    item2_id = item_by_sequence(scn["items"], 2)["id"]

    fx.start_item(scn, item2_id, "2026-08-01T12:30:00Z")
    playing = fx.read_item(item2_id, scn["mco_headers"])
    assert playing["playout_status"] == "PLAYING"
    assert playing["actual_start_utc"] == "2026-08-01T12:30:00Z"
    assert playing["clearance_status"] == "BLOCKED"

    fx.set_clock("2026-08-01T12:30:30Z")
    fx.end_item(scn, item2_id, "2026-08-01T12:30:30Z", 30)

    played = fx.read_item(item2_id, scn["mco_headers"])
    assert played["playout_status"] == "PLAYED"
    assert played["measured_duration_seconds"] == 30
    assert played["clearance_status"] == "BLOCKED"

    _, blocked_meta = validate_paginated(api.list_playlist_items(
        scn["playlist"]["id"], scn["traffic_headers"],
        params={"clearance_status": "BLOCKED"},
    ))
    assert blocked_meta["total_count"] == 2

    _, played_meta = validate_paginated(api.list_playlist_items(
        scn["playlist"]["id"], scn["traffic_headers"],
        params={"playout_status": "PLAYED"},
    ))
    assert played_meta["total_count"] == 2


def test_clearance_is_enforced_on_the_cue_edge_only(api):
    """The blocked sibling cannot be cued, and it is not auto-skipped either.

    PRD §3.6: "for elements whose `element_kind` is `PROGRAM`, `COMMERCIAL`, `INTERSTITIAL` or `PROMO` the `clearance_status` must be `CLEARED`, otherwise `ERR_UNCLEARED_CONTENT_ON_AIR`"

    Design: Corner/state_machines/item_playout_and_clearance_axes_advance_independently
    """
    scn = _cued_spot_then_retracted()
    item2_id = item_by_sequence(scn["items"], 2)["id"]
    item3_id = item_by_sequence(scn["items"], 3)["id"]

    fx.start_item(scn, item2_id, "2026-08-01T12:30:00Z")
    fx.set_clock("2026-08-01T12:30:30Z")
    fx.end_item(scn, item2_id, "2026-08-01T12:30:30Z", 30)

    resp = api.post_playout_event(
        item3_id,
        {"event_kind": "CUE", "event_utc": "2026-08-01T12:30:30Z",
         "source": "AUTOMATION"},
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_UNCLEARED_CONTENT_ON_AIR")

    item3 = fx.read_item(item3_id, scn["mco_headers"])
    assert item3["playout_status"] == "SCHEDULED"
    assert item3["clearance_status"] == "BLOCKED"


# ===========================================================================
# The emergency cut-in cascade and the EAS dwell boundary
# ===========================================================================

_CRAWL_TEXT = "Tornado warning for this viewing area until 13:15 UTC."


def _mandatory_cutin_on_air():
    """Element one playing since 12:00:00, then a mandatory cut-in at 12:29:00."""
    scn = fx.setup_playing_item1()
    requested = fx.request_override(
        scn, "CUT_IN",
        alert_class="EAS_MANDATORY",
        requested_start_utc="2026-08-01T12:29:00Z",
        expected_duration_seconds=300,
        crawl_text=_CRAWL_TEXT,
    )
    fx.set_clock("2026-08-01T12:29:00Z")
    scn["override"] = fx.activate_override(scn, requested["id"], "CUT_IN")
    return scn


def test_cutin_activation_drives_the_channel_to_eas_override(api):
    """Hops one and two: the override goes active and the channel switches away.

    PRD §3.8: "Hop one writes `authorized_by_operator_id`, `activated_utc` at the current logical time, and `active_mode` `CUT_IN`. Hop two, caused by hop one, drives the channel's `air_status` to `EAS_OVERRIDE` and its `posture` to `EMERGENCY`."

    Design: Corner/state_machines/override_cutin_cycle_runs_cascade_c_and_honours_the_dwell_boundary
    """
    scn = _mandatory_cutin_on_air()
    override = scn["override"]

    assert override["state"] == "ACTIVE_CUTIN"
    assert override["active_mode"] == "CUT_IN"
    assert override["activated_utc"] == "2026-08-01T12:29:00Z"
    assert override["authorized_by_operator_id"] == scn["pd"]["id"]

    channel = fx.read_channel(scn["ch1"]["id"], scn["mco_headers"])
    assert channel["air_status"] == "EAS_OVERRIDE"
    assert channel["posture"] == "EMERGENCY"


def test_cutin_truncates_the_playing_element_and_preempts_only_contained_ones(api):
    """Hop three: containment, not overlap, decides which booked elements are preempted.

    PRD §3.8: "Hop three, caused by hop two, rewrites the playlist: the element that was `PLAYING` on the channel's on-air playlist flips to `TRUNCATED` with its `measured_duration_seconds` set to the whole seconds from its `actual_start_utc` to the current logical time; and **every element whose own booked span, from its `scheduled_start_utc` up to but not including that instant plus its `scheduled_duration_seconds`, lies entirely inside the override's expected span, from the current logical time up to but not including that instant plus `expected_duration_seconds`, and whose `playout_status` is `SCHEDULED` or `CUED`, flips to `PREEMPTED`**."

    Design: Corner/state_machines/override_cutin_cycle_runs_cascade_c_and_honours_the_dwell_boundary
    """
    scn = _mandatory_cutin_on_air()

    items = fx.list_items(scn["playlist"]["id"], scn["traffic_headers"])
    item1 = item_by_sequence(items, 1)
    assert item1["playout_status"] == "TRUNCATED"
    assert item1["measured_duration_seconds"] == 1740

    assert item_by_sequence(items, 2)["playout_status"] == "PREEMPTED"
    assert item_by_sequence(items, 3)["playout_status"] == "PREEMPTED"
    assert item_by_sequence(items, 4)["playout_status"] == "SCHEDULED"

    assert scn["override"]["truncated_item_count"] == 1
    assert scn["override"]["preempted_item_count"] == 2


def test_cutin_settles_the_preempted_spots_at_the_full_rate(api):
    """Hop four: the two preempted commercials are credited in full.

    PRD §3.8: "Hop four, caused by hop three, settles the money: every affected element carrying a `spot_order_id` moves that spot to `short_aired_spots` when it was truncated or to `credited_spots` when it was preempted, accrues the corresponding credit, and refreshes the order's `status`."

    Design: Corner/state_machines/override_cutin_cycle_runs_cascade_c_and_honours_the_dwell_boundary
    """
    scn = _mandatory_cutin_on_air()

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["credited_spots"] == 2
    assert order["credit_accrued_cents"] == 200000
    assert order["scheduled_spots"] == 0
    assert order["status"] == "PARTIALLY_CREDITED"
    assert_spot_count_conservation(order)


def test_the_channel_cannot_be_darkened_while_the_override_is_active(api):
    """The alert must keep radiating, so the operator cannot pull the channel dark.

    PRD §3.3: "An operator may not take a channel `DARK` while an emergency override on that channel is in state `ACTIVE_CRAWL` or `ACTIVE_CUTIN`; the attempt is refused with `ERR_EAS_OVERRIDE_ACTIVE`."

    Design: Corner/state_machines/override_cutin_cycle_runs_cascade_c_and_honours_the_dwell_boundary
    """
    # The override is an ACTIVE_CRAWL rather than a cut-in, because a crawl leaves
    # `air_status` at `ON_AIR` ("air_status is unchanged because a crawl is an
    # overlay rather than a substitution") and so DARK remains one of the moves
    # PRD 3.3 declares reachable. From `EAS_OVERRIDE` the request would already be
    # answered by the earlier reachability check with ERR_CHANNEL_INVALID_AIR_STATE.
    scn = fx.setup_playing_item1()
    fx.setup_active_override(scn, "CRAWL")

    resp = api.change_channel_air_state(
        scn["ch1"]["id"],
        {"target_air_status": "DARK",
         "reason": "operator attempts to go dark mid-alert"},
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_EAS_OVERRIDE_ACTIVE")

    channel = fx.read_channel(scn["ch1"]["id"], scn["mco_headers"])
    assert channel["air_status"] == "ON_AIR"


def test_mandatory_de_escalation_is_refused_one_second_before_the_dwell(api):
    """At 119 seconds on air the mandatory alert may not be relaxed to a crawl.

    PRD §3.8: "when `alert_class` is `EAS_MANDATORY`, it requires that at least 120 seconds have elapsed since `activated_utc` — **at exactly 120 seconds the de-escalation is permitted** and any earlier attempt is refused with `ERR_EAS_MINIMUM_DURATION_NOT_MET`."

    Design: Corner/state_machines/override_cutin_cycle_runs_cascade_c_and_honours_the_dwell_boundary
    """
    scn = _mandatory_cutin_on_air()
    fx.set_clock("2026-08-01T12:30:59Z")

    resp = api.activate_override(
        scn["override"]["id"],
        {"authorized_by_operator_id": scn["pd"]["id"],
         "override_mode": "CRAWL",
         "crawl_text": "Tornado warning continues."},
        scn["pd_headers"],
    )
    validate_error(resp, "ERR_EAS_MINIMUM_DURATION_NOT_MET")

    override = fx.read_override(scn["override"]["id"], scn["mco_headers"])
    assert override["state"] == "ACTIVE_CUTIN"
    assert override["active_mode"] == "CUT_IN"


def _de_escalated_at_the_dwell(scn):
    """Relax the cut-in to a crawl at exactly 120 seconds on air."""
    fx.set_clock("2026-08-01T12:31:00Z")
    return fx.activate_override(scn, scn["override"]["id"], "CRAWL",
                                crawl_text="Tornado warning continues.")


def test_mandatory_de_escalation_is_permitted_at_exactly_the_dwell(api):
    """At 120 seconds the cut-in relaxes to a crawl and programming returns.

    PRD §3.8: "**De-escalating** a cut-in back to a crawl sets `active_mode` to `CRAWL` and returns the channel's `air_status` from `EAS_OVERRIDE` to `ON_AIR` while `posture` stays `EMERGENCY`"

    Design: Corner/state_machines/override_cutin_cycle_runs_cascade_c_and_honours_the_dwell_boundary
    """
    scn = _mandatory_cutin_on_air()

    relaxed = _de_escalated_at_the_dwell(scn)
    assert relaxed["state"] == "ACTIVE_CRAWL"
    assert relaxed["active_mode"] == "CRAWL"

    channel = fx.read_channel(scn["ch1"]["id"], scn["mco_headers"])
    assert channel["air_status"] == "ON_AIR"
    assert channel["posture"] == "EMERGENCY"


def test_de_escalation_restores_nothing_that_the_cutin_took(api):
    """Relaxing the alert is not a compensating action for the elements it dropped.

    PRD §3.8: "**Elements already truncated or preempted are not restored**: there is no compensation on de-escalation."

    Design: Corner/state_machines/override_cutin_cycle_runs_cascade_c_and_honours_the_dwell_boundary
    """
    scn = _mandatory_cutin_on_air()
    _de_escalated_at_the_dwell(scn)

    items = fx.list_items(scn["playlist"]["id"], scn["traffic_headers"])
    assert item_by_sequence(items, 1)["playout_status"] == "TRUNCATED"
    assert item_by_sequence(items, 2)["playout_status"] == "PREEMPTED"
    assert item_by_sequence(items, 3)["playout_status"] == "PREEMPTED"

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["credited_spots"] == 2
    assert order["credit_accrued_cents"] == 200000


def test_re_escalation_preempts_afresh_inside_the_new_span(api):
    """The second cut-in pass reaches the element that survived the first one.

    PRD §3.8: "The cycle from crawl to cut-in and back may repeat any number of times, each pass truncating and preempting afresh."

    Design: Corner/state_machines/override_cutin_cycle_runs_cascade_c_and_honours_the_dwell_boundary
    """
    scn = _mandatory_cutin_on_air()
    _de_escalated_at_the_dwell(scn)

    re_escalated = fx.activate_override(scn, scn["override"]["id"], "CUT_IN")
    assert re_escalated["state"] == "ACTIVE_CUTIN"
    assert re_escalated["active_mode"] == "CUT_IN"
    # PRD says only that "truncated_item_count and preempted_item_count are
    # written" by hop three; it never says whether a later pass overwrites them
    # with its own tally or adds to the running total, so the value the counter
    # carries after a second pass is not asserted here. What the PRD does pin is
    # which elements the fresh pass reaches.

    items = fx.list_items(scn["playlist"]["id"], scn["traffic_headers"])
    assert item_by_sequence(items, 4)["playout_status"] == "PREEMPTED"
    assert item_by_sequence(items, 5)["playout_status"] == "SCHEDULED"

    channel = fx.read_channel(scn["ch1"]["id"], scn["mco_headers"])
    assert channel["air_status"] == "EAS_OVERRIDE"


def test_releasing_the_cutin_hands_the_channel_back_to_the_playlist(api):
    """The release stamps the instant, drops the active mode and restores ON_AIR.

    PRD §3.8: "A release writes `released_utc` at the current logical time and sets `active_mode` to null."
    PRD §3.8: "Releasing a cut-in additionally returns `air_status` from `EAS_OVERRIDE` to `ON_AIR`, which is permitted only when no override on the channel remains in `ACTIVE_CUTIN`."

    Design: Corner/state_machines/override_cutin_cycle_runs_cascade_c_and_honours_the_dwell_boundary
    """
    scn = _mandatory_cutin_on_air()
    _de_escalated_at_the_dwell(scn)
    fx.activate_override(scn, scn["override"]["id"], "CUT_IN")

    released = fx.release_override(scn, scn["override"]["id"])
    assert released["state"] == "RELEASED"
    assert released["released_utc"] == "2026-08-01T12:31:00Z"
    assert released["active_mode"] is None

    channel = fx.read_channel(scn["ch1"]["id"], scn["mco_headers"])
    assert channel["air_status"] == "ON_AIR"


def test_the_release_does_not_reverse_the_preemption_credits(api):
    """Handing the channel back leaves the spot ledger exactly where the cut-in left it.

    PRD §3.8: "**Preempted commercial spots stay credited; the spot ledger is not reversed by the release itself.**"

    Design: Corner/state_machines/override_cutin_cycle_runs_cascade_c_and_honours_the_dwell_boundary
    """
    scn = _mandatory_cutin_on_air()
    _de_escalated_at_the_dwell(scn)
    fx.activate_override(scn, scn["override"]["id"], "CUT_IN")
    fx.release_override(scn, scn["override"]["id"])

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["credited_spots"] == 2
    assert order["credit_accrued_cents"] == 200000
    assert order["scheduled_spots"] == 0
    assert_spot_count_conservation(order)

    _, preempted_meta = validate_paginated(api.list_playlist_items(
        scn["playlist"]["id"], scn["traffic_headers"],
        params={"playout_status": "PREEMPTED"},
    ))
    assert preempted_meta["total_count"] == 3


# ===========================================================================
# Technical faults: the escalation dwell and the hand-worked path
# ===========================================================================

def _acknowledged_caption_fault():
    """A minor caption fault on ch1 observed at 09:00:00 and acknowledged at once."""
    plant = fx.setup_base_plant()
    fault = fx.report_channel_fault(plant, "CAPTION_LOSS", "MINOR",
                                    "2026-08-01T09:00:00Z")
    plant["fault"] = fx.advance_fault(plant, fault["id"], "ACKNOWLEDGED")
    return plant


def test_escalation_is_refused_one_second_before_the_fault_dwell(api):
    """A fault that has run 119 seconds is not yet escalatable.

    PRD §3.3: "Escalating requires that `duration_seconds` has reached at least 120 seconds; **at exactly 120 seconds escalation is permitted**, and below that it is refused with `ERR_FAULT_ESCALATION_TOO_EARLY`."

    Design: Corner/state_machines/fault_escalation_dwell_and_minor_auto_clear_boundaries
    """
    plant = _acknowledged_caption_fault()
    fx.set_clock("2026-08-01T09:01:59Z")

    resp = api.change_fault_state(plant["fault"]["id"],
                                  {"target_state": "ESCALATED"},
                                  plant["eng_headers"])
    validate_error(resp, "ERR_FAULT_ESCALATION_TOO_EARLY")

    fault = fx.read_fault(plant["fault"]["id"], plant["eng_headers"])
    assert fault["state"] == "ACKNOWLEDGED"
    assert fault["severity"] == "MINOR"


def test_escalation_at_exactly_the_dwell_raises_the_severity_one_step(api):
    """At 120 seconds the fault escalates and a minor condition becomes major.

    PRD §3.3: "Escalation raises `severity` one step, from `MINOR` to `MAJOR` and from `MAJOR` to `CRITICAL`, with `CRITICAL` staying `CRITICAL`, and it recomputes `posture`, which may flip the channel to `DEGRADED_CRITICAL` and thereby block playlist arming as described in §3.5."

    Design: Corner/state_machines/fault_escalation_dwell_and_minor_auto_clear_boundaries
    """
    plant = _acknowledged_caption_fault()
    fx.set_clock("2026-08-01T09:02:00Z")

    escalated = fx.advance_fault(plant, plant["fault"]["id"], "ESCALATED",
                                 headers=plant["eng_headers"])
    assert escalated["state"] == "ESCALATED"
    assert escalated["severity"] == "MAJOR"
    assert escalated["duration_seconds"] == 120


def test_a_single_major_fault_does_not_degrade_the_channel(api):
    """One major fault is not enough; the fourth posture clause needs two.

    PRD §3.3: "Otherwise, fourth, it is `DEGRADED` if the number of open faults with `severity` `MAJOR` is at least two, or if the transmitter's `operational_state` is `REDUCED_POWER`; **exactly two major faults already degrade the channel**, one does not, and reduced transmitter power degrades every channel it carries on its own with no faults at all."

    Design: Corner/state_machines/fault_escalation_dwell_and_minor_auto_clear_boundaries
    """
    plant = _acknowledged_caption_fault()
    fx.set_clock("2026-08-01T09:02:00Z")
    fx.advance_fault(plant, plant["fault"]["id"], "ESCALATED",
                     headers=plant["eng_headers"])

    channel = fx.read_channel(plant["ch1"]["id"], plant["eng_headers"])
    assert channel["posture"] == "NORMAL"
    assert channel["open_fault_count"] == 1


def test_an_escalated_major_fault_never_ages_out(api):
    """A major, acknowledged fault must be worked by hand however long it sits.

    PRD §3.3: "**Major and critical faults never auto-clear and must be worked by hand**, and a fault that an operator acknowledged is likewise excluded from ageing out no matter how long it sits."

    Design: Corner/state_machines/fault_escalation_dwell_and_minor_auto_clear_boundaries
    """
    plant = _acknowledged_caption_fault()
    fx.set_clock("2026-08-01T09:02:00Z")
    fx.advance_fault(plant, plant["fault"]["id"], "ESCALATED",
                     headers=plant["eng_headers"])

    fx.set_clock("2026-08-01T09:20:00Z")

    fault = fx.read_fault(plant["fault"]["id"], plant["eng_headers"])
    assert fault["state"] == "ESCALATED"
    assert fault["cleared_utc"] is None
    assert fx.read_channel(plant["ch1"]["id"],
                           plant["eng_headers"])["open_fault_count"] == 1


def test_mitigation_without_a_mitigation_code_is_refused(api):
    """An escalated fault cannot be mitigated without naming what was done.

    PRD §3.3: "Mitigating a fault, whether from `ACKNOWLEDGED` or from `ESCALATED`, requires a `mitigation_code`; its absence yields `ERR_MITIGATION_CODE_REQUIRED`."

    Design: Corner/state_machines/fault_escalation_dwell_and_minor_auto_clear_boundaries
    """
    plant = _acknowledged_caption_fault()
    fx.set_clock("2026-08-01T09:02:00Z")
    fx.advance_fault(plant, plant["fault"]["id"], "ESCALATED",
                     headers=plant["eng_headers"])

    resp = api.change_fault_state(plant["fault"]["id"],
                                  {"target_state": "MITIGATED"},
                                  plant["eng_headers"])
    validate_error(resp, "ERR_MITIGATION_CODE_REQUIRED")

    fault = fx.read_fault(plant["fault"]["id"], plant["eng_headers"])
    assert fault["state"] == "ESCALATED"
    assert fault["mitigation_code"] is None


def test_resolving_a_mitigated_fault_freezes_its_duration_and_clears_it(api):
    """Resolution stamps the clearing instant and empties the channel's open set.

    PRD §3.3: "Resolving a mitigated fault writes `cleared_utc` at the current logical time and freezes `duration_seconds` at the elapsed interval, decrements the channel's `open_fault_count` and recomputes `posture`, which may return the channel from `DEGRADED_CRITICAL` or `DEGRADED` to `NORMAL`."

    Design: Corner/state_machines/fault_escalation_dwell_and_minor_auto_clear_boundaries
    """
    plant = _acknowledged_caption_fault()
    fx.set_clock("2026-08-01T09:02:00Z")
    fx.advance_fault(plant, plant["fault"]["id"], "ESCALATED",
                     headers=plant["eng_headers"])

    fx.set_clock("2026-08-01T09:15:00Z")
    fx.advance_fault(plant, plant["fault"]["id"], "MITIGATED",
                     headers=plant["eng_headers"],
                     mitigation_code="RESTART_ENCODER")
    resolved = fx.advance_fault(plant, plant["fault"]["id"], "RESOLVED",
                                headers=plant["eng_headers"])

    assert resolved["state"] == "RESOLVED"
    assert resolved["cleared_utc"] == "2026-08-01T09:15:00Z"
    assert resolved["duration_seconds"] == 900
    assert resolved["mitigation_code"] == "RESTART_ENCODER"

    channel = fx.read_channel(plant["ch1"]["id"], plant["eng_headers"])
    assert channel["open_fault_count"] == 0
    assert channel["posture"] == "NORMAL"


# ===========================================================================
# Network feed windows: the join guard, the breakaway guard and abandonment
# ===========================================================================

def _two_planned_windows():
    """Two non-overlapping windows on the on-air channel, both anchored on element four."""
    scn = fx.setup_on_air_playlist()
    scn["w1"] = fx.create_window(
        scn, "2026-08-01T12:00:00Z", "2026-08-01T12:05:00Z",
        anchor_sequence_number=4, feed_source="NETWORK_PRIMARY",
        backtiming_mode="TOLERANT", guard_seconds=2, live_encoder_units=1,
    )
    scn["w2"] = fx.create_window(
        scn, "2026-08-01T12:10:00Z", "2026-08-01T12:12:00Z",
        anchor_sequence_number=4, feed_source="NETWORK_ALT",
        backtiming_mode="STRICT", guard_seconds=2, live_encoder_units=1,
    )
    return scn


def _playing_at(scn, event_utc):
    """Cue and start element one at the supplied instant."""
    item1 = item_by_sequence(scn["items"], 1)
    fx.set_clock(event_utc)
    fx.cue_item(scn, item1["id"], event_utc)
    fx.start_item(scn, item1["id"], event_utc)
    return item1


def test_a_join_before_the_guard_window_opens_is_refused(api):
    """Fifty-eight seconds before the guard opens the join is premature.

    PRD §3.7: "The join must also be issued inside the guard window: the logical clock must be at or after `join_utc` less `guard_seconds` and at or before `join_utc` plus a late-join limit of 30 seconds."

    Design: Corner/state_machines/feed_window_join_and_breakaway_guard_boundaries_and_system_abandonment
    """
    scn = _two_planned_windows()

    resp = api.join_feed_window(scn["w1"]["id"], {}, scn["mco_headers"])
    validate_error(resp, "ERR_JOIN_OUTSIDE_GUARD_WINDOW")

    window = fx.read_feed_window(scn["w1"]["id"], scn["mco_headers"])
    assert window["state"] == "PLANNED"
    assert window["version"] == scn["w1"]["version"]


def test_a_join_thirty_one_seconds_late_forfeits_the_window(api):
    """The late-join limit is inclusive at plus thirty, so plus thirty-one is refused.

    PRD §3.7: "either failure is `ERR_JOIN_OUTSIDE_GUARD_WINDOW`, and **exactly `join_utc` plus 30 seconds is accepted while plus 31 is refused**."

    Design: Corner/state_machines/feed_window_join_and_breakaway_guard_boundaries_and_system_abandonment
    """
    scn = _two_planned_windows()
    _playing_at(scn, "2026-08-01T12:00:00Z")
    fx.set_clock("2026-08-01T12:00:31Z")

    resp = api.join_feed_window(scn["w1"]["id"],
                               {"actual_join_utc": "2026-08-01T12:00:31Z"},
                               scn["mco_headers"])
    validate_error(resp, "ERR_JOIN_OUTSIDE_GUARD_WINDOW")

    windows, meta = validate_paginated(api.list_channel_feed_windows(
        scn["ch1"]["id"], scn["mco_headers"], params={"state": "PLANNED"},
    ))
    assert meta["total_count"] == 2
    assert all(window["state"] == "PLANNED" for window in windows)
    assert fx.read_feed_window(scn["w1"]["id"],
                              scn["mco_headers"])["version"] == scn["w1"]["version"]


def test_a_join_at_exactly_the_late_limit_is_a_join_in_progress(api):
    """Thirty seconds late the feed has already started, so the plan carries no pad or trim.

    PRD §3.7: "If **remaining is zero or negative**, the feed has already started and the action is `JOIN_IN_PROGRESS`: `late_join_seconds` is the magnitude of the overshoot, and the pad, the trim and the skip list are all empty."

    Design: Corner/state_machines/feed_window_join_and_breakaway_guard_boundaries_and_system_abandonment
    """
    scn = _two_planned_windows()
    _playing_at(scn, "2026-08-01T12:00:00Z")
    fx.set_clock("2026-08-01T12:00:30Z")

    joined = fx.join_window(scn, scn["w1"]["id"],
                            actual_join_utc="2026-08-01T12:00:30Z")
    assert joined["state"] == "JOINED"
    assert joined["plan_action"] == "JOIN_IN_PROGRESS"
    assert joined["late_join_seconds"] == 30
    assert joined["backtime_pad_seconds"] == 0
    assert joined["backtime_trim_seconds"] == 0
    assert joined["skipped_item_sequences"] == []


def test_a_join_in_progress_truncates_the_element_on_air(api):
    """The element the feed cut into is truncated at the join instant.

    PRD §3.7: "A `JOIN_IN_PROGRESS` join truncates the currently playing element, if any, and records `late_join_seconds`."

    Design: Corner/state_machines/feed_window_join_and_breakaway_guard_boundaries_and_system_abandonment
    """
    scn = _two_planned_windows()
    item1 = _playing_at(scn, "2026-08-01T12:00:00Z")
    fx.set_clock("2026-08-01T12:00:30Z")

    fx.join_window(scn, scn["w1"]["id"],
                   actual_join_utc="2026-08-01T12:00:30Z")

    truncated = fx.read_item(item1["id"], scn["mco_headers"])
    assert truncated["playout_status"] == "TRUNCATED"
    assert truncated["measured_duration_seconds"] == 30


def _joined_window(scn):
    """Join W1 thirty seconds late so the window sits in JOINED."""
    _playing_at(scn, "2026-08-01T12:00:00Z")
    fx.set_clock("2026-08-01T12:00:30Z")
    return fx.join_window(scn, scn["w1"]["id"],
                          actual_join_utc="2026-08-01T12:00:30Z")


def test_a_breakaway_one_second_before_the_guard_instant_is_refused(api):
    """The return to local may not be taken before breakaway_utc less the guard.

    PRD §3.7: "It requires that the logical clock has reached at least `breakaway_utc` less `guard_seconds`; **at exactly that instant the breakaway is permitted** and any earlier attempt is refused with `ERR_BREAKAWAY_TOO_EARLY`."

    Design: Corner/state_machines/feed_window_join_and_breakaway_guard_boundaries_and_system_abandonment
    """
    scn = _two_planned_windows()
    _joined_window(scn)
    fx.set_clock("2026-08-01T12:04:57Z")

    resp = api.breakaway_feed_window(scn["w1"]["id"], {}, scn["mco_headers"])
    validate_error(resp, "ERR_BREAKAWAY_TOO_EARLY")

    assert fx.read_feed_window(scn["w1"]["id"],
                              scn["mco_headers"])["state"] == "JOINED"


def test_a_breakaway_at_exactly_the_guard_instant_returns_to_local(api):
    """At breakaway_utc less the guard the window closes with an operator-sourced row.

    PRD §3.7: "The breakaway computes `residual_dead_air_seconds` for the return to local, appends a breakaway entry sourced `OPERATOR`, re-cues the local tail, releases the window's `live_encoder_units` — which lowers the multiplex's `live_encoder_units_peak` at the next evaluation — recomputes the as-run variance, and moves the window from `JOINED` to `BROKEN_AWAY`, which is terminal."

    Design: Corner/state_machines/feed_window_join_and_breakaway_guard_boundaries_and_system_abandonment
    """
    scn = _two_planned_windows()
    _joined_window(scn)
    fx.set_clock("2026-08-01T12:04:58Z")

    broken = fx.breakaway_window(scn, scn["w1"]["id"])
    assert broken["state"] == "BROKEN_AWAY"

    rows, meta = validate_paginated(api.get_playlist_as_run(
        scn["playlist"]["id"], scn["mco_headers"],
        params={"event_kind": "BREAKAWAY"},
    ))
    assert meta["total_count"] == 1
    assert as_run_kinds(rows) == ["BREAKAWAY"]
    assert rows[0]["source"] == "OPERATOR"


def test_darkening_the_channel_abandons_a_still_planned_window(api):
    """A window nobody joined is abandoned by the system rather than left dangling.

    PRD §3.7: "A `PLANNED` window is abandoned by the system when its channel is taken from `ON_AIR` to `DARK` or when the transmitter cascade drives the channel to `SUSPENDED` posture; abandonment requires that the channel's `posture` is `SUSPENDED` or its `air_status` is `DARK`, releases the window's `live_encoder_units`, and increments the window's `version`."

    Design: Corner/state_machines/feed_window_join_and_breakaway_guard_boundaries_and_system_abandonment
    """
    scn = _two_planned_windows()

    fx.set_air_status(scn, scn["ch1"]["id"], "DARK",
                      reason="transmission halted for the day")

    window = fx.read_feed_window(scn["w2"]["id"], scn["mco_headers"])
    assert window["state"] == "ABANDONED"
    assert window["version"] > scn["w2"]["version"]


# ===========================================================================
# Replaying an action is never idempotent: the state machine refuses it
# ===========================================================================

def test_re_cueing_an_already_cued_element_is_refused(api):
    """A cue is legal from SCHEDULED only, so the identical second call fails.

    PRD §3.6: "An event is legal only for certain current `playout_status` values: `CUE` requires `SCHEDULED`, `START` requires `CUED`, `END` requires `PLAYING`, `TRUNCATION` requires `PLAYING`, and `SKIP` requires `SCHEDULED` or `CUED`. An event against an element that is already `PLAYED`, `TRUNCATED`, `SKIPPED` or `PREEMPTED` is refused with `ERR_ITEM_INVALID_PLAYOUT_STATE`; those four are terminal on the automation axis."

    Design: Corner/state_machines/repeated_calls_are_not_idempotent_and_are_rejected_by_state
    """
    scn = fx.setup_on_air_playlist()
    item1_id = item_by_sequence(scn["items"], 1)["id"]
    fx.set_clock("2026-08-01T12:00:00Z")
    fx.cue_item(scn, item1_id, "2026-08-01T12:00:00Z")
    cued = fx.read_item(item1_id, scn["mco_headers"])

    resp = api.post_playout_event(
        item1_id,
        {"event_kind": "CUE", "event_utc": "2026-08-01T12:00:00Z",
         "source": "AUTOMATION"},
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_ITEM_INVALID_PLAYOUT_STATE")

    after = fx.read_item(item1_id, scn["mco_headers"])
    assert after["playout_status"] == "CUED"
    assert after["version"] == cued["version"]

    cue_rows, cue_meta = validate_paginated(api.get_playlist_as_run(
        scn["playlist"]["id"], scn["mco_headers"], params={"event_kind": "CUE"},
    ))
    assert cue_meta["total_count"] == 1
    assert as_run_kinds(cue_rows) == ["CUE"]


def test_re_activating_an_active_crawl_in_the_same_mode_is_refused(api):
    """An active override only accepts a mode that differs from the one on air.

    PRD §3.8: "It is accepted from `PENDING`, from `ACTIVE_CRAWL` and from `ACTIVE_CUTIN` — the two active states permit the declared escalation and relaxation moves — and **when the override is already active the requested `override_mode` must differ from the current `active_mode`**; anything else is refused with `ERR_OVERRIDE_INVALID_STATE`."

    Design: Corner/state_machines/repeated_calls_are_not_idempotent_and_are_rejected_by_state
    """
    plant = fx.setup_base_plant()
    active = fx.setup_active_override(plant, "CRAWL")
    assert active["state"] == "ACTIVE_CRAWL"

    resp = api.activate_override(
        active["id"],
        {"authorized_by_operator_id": plant["pd"]["id"],
         "override_mode": "CRAWL",
         "crawl_text": "Severe thunderstorm warning for the viewing area."},
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_OVERRIDE_INVALID_STATE")

    override = fx.read_override(active["id"], plant["mco_headers"])
    assert override["state"] == "ACTIVE_CRAWL"
    assert override["active_mode"] == "CRAWL"
    assert override["activated_utc"] == active["activated_utc"]
    assert override["version"] == active["version"]


def test_re_filing_an_already_filed_notification_is_refused(api):
    """A regulatory filing is a one-shot terminal outcome, not a replayable command.

    PRD §3.1: "Filing against a notification already `FILED` or `LATE_FILED` is refused with `ERR_NOTIFICATION_INVALID_STATE`."

    Design: Corner/state_machines/repeated_calls_are_not_idempotent_and_are_rejected_by_state
    """
    plant = fx.setup_base_plant()
    fx.change_power_state(plant, "REDUCED_POWER", power_pct=50,
                          reason="antenna icing")

    notifications = fx.list_notifications(plant["transmitter"]["id"],
                                          plant["compliance_headers"],
                                          params={"kind": "POWER_REDUCTION"})
    assert len(notifications) == 1
    filed = fx.file_notification(
        plant, notifications[0]["id"],
        filed_reference="FCC-2026-08-01-0001",
        narrative="Power reduced to 50 percent for antenna de-icing; ERP restored the same day.",
    )
    assert filed["status"] in ("FILED", "LATE_FILED")

    resp = api.file_notification(
        notifications[0]["id"],
        {"filed_reference": "FCC-2026-08-01-0001",
         "narrative": "Power reduced to 50 percent for antenna de-icing; ERP restored the same day."},
        plant["compliance_headers"],
    )
    validate_error(resp, "ERR_NOTIFICATION_INVALID_STATE")

    notification = fx.read_notification(notifications[0]["id"],
                                        plant["compliance_headers"])
    assert notification["status"] == filed["status"]
    assert notification["filed_reference"] == "FCC-2026-08-01-0001"
    assert notification["version"] == filed["version"]

    transmitter = fx.read_transmitter(plant["transmitter"]["id"],
                                      plant["eng_headers"])
    assert transmitter["notification_pending_count"] == 0


def test_setting_the_clock_to_its_present_value_is_refused(api):
    """The logical clock only moves forward, so an equal value is not a no-op.

    PRD §2.4: "A clock advance must move strictly forward: a request whose `current_utc` equals or precedes the present clock value is rejected with `ERR_CLOCK_NOT_MONOTONIC`."

    Design: Corner/state_machines/repeated_calls_are_not_idempotent_and_are_rejected_by_state
    """
    plant = fx.bootstrap_operators()
    fx.set_clock("2026-08-01T10:00:00Z")

    resp = api.set_clock("2026-08-01T10:00:00Z", plant["admin_headers"])
    validate_error(resp, "ERR_CLOCK_NOT_MONOTONIC")

    resp_backwards = api.set_clock("2026-08-01T09:59:59Z", plant["admin_headers"])
    validate_error(resp_backwards, "ERR_CLOCK_NOT_MONOTONIC")
