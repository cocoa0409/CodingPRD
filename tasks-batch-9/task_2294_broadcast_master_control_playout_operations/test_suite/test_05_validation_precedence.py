"""Validation-ladder precedence: which error id wins when two rules fail at once.

PRD §2.8 pins one ordered ladder of checks and states that "the first failing
check is the whole response and no later check is evaluated". Each pair below
builds a request that violates two rules simultaneously, asserts the earlier
band's identifier is returned, and then repairs only the earlier violation so the
later rule proves it was live all along.
"""
from test_helpers import (
    ADMIN,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

# PRD §2.4: the logical clock starts at 2026-08-01T00:00:00Z and only moves when
# a client asks it to; every scenario below pins it explicitly first.
_CLOCK = "2026-08-01T10:00:00Z"


def _passed_asset_and_suspended_director(plant):
    """A QC_PASSED asset plus a SUSPENDED programme director on the same bench.

    The asset is delivered exactly to its booked length with loudness on target
    and no defect codes, so the ingest report scores a clean 100 and the asset
    reaches QC_PASSED — a status from which a waiver is not legal.
    """
    asset = fx.setup_qc_passed_asset(plant, 600)
    assert asset["status"] == "QC_PASSED", "setup must leave the asset QC_PASSED"
    suspended = fx.suspend_operator(plant["pd"]["id"])
    assert suspended["status"] == "SUSPENDED", "setup must suspend the director"
    return asset


# ===========================================================================
# Pair 1 — actor fitness (403) outranks entity state (409) on a QC waiver
# ===========================================================================

def test_suspended_director_waiving_a_passed_asset_reports_suspension(api):
    """Suspension of the acting operator outranks the asset's wrong status.

    PRD §2.8: "A suspended operator calling a mutation on a resource that is
    also in the wrong state receives `ERR_OPERATOR_SUSPENDED`, never the state
    error."

    Design: Difficulty/priority_pair_validation_conflict/suspended_operator_auth_beats_asset_state_on_qc_waiver
    """
    plant = fx.bootstrap_operators(clock_utc=_CLOCK)
    asset = _passed_asset_and_suspended_director(plant)

    resp = api.sign_qc_waiver(
        asset["id"],
        factories.qc_waiver_payload(plant["pd"]["id"]),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_OPERATOR_SUSPENDED")

    after = fx.read_asset(asset["id"])
    assert after["status"] == "QC_PASSED", "the refused waiver must not move the asset"
    assert after.get("waived_by_operator_id") is None
    assert after.get("waiver_justification") is None


def test_reinstated_director_waiving_a_passed_asset_reports_asset_state(api):
    """With the operator back to ACTIVE the very same waiver hits the state rule.

    PRD §3.4: "The waiver supplies `waived_by_operator_id` and a
    `waiver_justification`, and is legal only from `QC_FAILED`; from any other
    status it is refused with `ERR_ASSET_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_operator_auth_beats_asset_state_on_qc_waiver
    """
    plant = fx.bootstrap_operators(clock_utc=_CLOCK)
    asset = _passed_asset_and_suspended_director(plant)
    waiver = factories.qc_waiver_payload(plant["pd"]["id"])

    validate_error(
        api.sign_qc_waiver(asset["id"], waiver, plant["pd_headers"]),
        "ERR_OPERATOR_SUSPENDED",
    )

    reinstated = validate_success(
        api.update_operator_status(plant["pd"]["id"], {"status": "ACTIVE"}, ADMIN)
    )
    assert reinstated["status"] == "ACTIVE"

    validate_error(
        api.sign_qc_waiver(asset["id"], waiver, plant["pd_headers"]),
        "ERR_ASSET_INVALID_STATE",
    )

    after = fx.read_asset(asset["id"])
    assert after["status"] == "QC_PASSED"
    assert after.get("waived_by_operator_id") is None


# ===========================================================================
# Pair 2 — the temporal overlap rule (409) outranks anchor resolution (409)
# ===========================================================================

def _armed_network_join_day(plant, channel_id=None, asset=None):
    """An ARMED broadcast day whose only network-join anchor is sequence number 2.

    Element one runs 1740 seconds from 12:00:00Z and element two is a 60-second
    NETWORK_JOIN starting exactly at 12:29:00Z, so the two are adjacent and the
    1800-second total matches the window: the projected variance is 0 and the day
    both validates and arms.
    """
    asset = asset or fx.setup_qc_passed_asset(plant, 1740)
    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM", "asset_id": asset["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1740, "max_trim_seconds": 0},
        {"sequence_number": 2, "element_kind": "NETWORK_JOIN",
         "scheduled_start_utc": "2026-08-01T12:29:00Z",
         "scheduled_duration_seconds": 60, "max_trim_seconds": 0},
    ]
    playlist = fx.ingest(plant, items, channel_id=channel_id,
                         window_duration_seconds=1800)
    fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    armed = fx.drive_playlist(plant, playlist["id"], "ARMED")
    assert armed["status"] == "ARMED", "setup must leave the day ARMED"
    return armed


def _window_payload(channel_id, anchor_sequence_number, join_utc, breakaway_utc,
                    **overrides):
    return factories.create_feed_window_payload(
        channel_id, anchor_sequence_number, join_utc, breakaway_utc,
        backtiming_mode="STRICT", guard_seconds=2, live_encoder_units=1,
        **overrides,
    )


def test_overlapping_window_with_unknown_anchor_reports_the_overlap(api):
    """A plan that both collides and names no anchor reports the collision.

    PRD §2.8: "A feed-window plan that both overlaps an existing window and names
    a sequence number matching no anchor element receives
    `ERR_FEED_WINDOW_OVERLAP`, never `ERR_ANCHOR_ITEM_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/feed_window_overlap_temporal_beats_missing_anchor_constraint
    """
    plant = fx.setup_base_plant(with_subchannel=False, clock_utc=_CLOCK)
    _armed_network_join_day(plant)

    first = fx.create_window(plant, "2026-08-01T12:00:00Z", "2026-08-01T12:10:00Z",
                             anchor_sequence_number=2, backtiming_mode="STRICT",
                             guard_seconds=2, live_encoder_units=1)
    assert first["state"] == "PLANNED"

    resp = api.create_feed_window(
        _window_payload(plant["ch1"]["id"], 7, "2026-08-01T12:05:00Z",
                        "2026-08-01T12:15:00Z", feed_source="NETWORK_ALT"),
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_FEED_WINDOW_OVERLAP")

    windows, _meta = validate_paginated(
        api.list_channel_feed_windows(plant["ch1"]["id"], plant["mco_headers"])
    )
    assert [w["id"] for w in windows] == [first["id"]], \
        "the refused plan must not persist a second window"
    assert fx.read_feed_window(first["id"])["state"] == "PLANNED"


def test_disjoint_window_with_unknown_anchor_reports_the_missing_anchor(api):
    """Moved clear of the other window, the same anchor-less plan hits the anchor rule.

    PRD §3.7: "`anchor_sequence_number` must be at least 1 and must match an
    existing element's `sequence_number` in the channel's most recently armed or
    on-air playlist, and **that element's `element_kind` must be
    `NETWORK_JOIN`**; otherwise the plan is refused with
    `ERR_ANCHOR_ITEM_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/feed_window_overlap_temporal_beats_missing_anchor_constraint
    """
    plant = fx.setup_base_plant(with_subchannel=False, clock_utc=_CLOCK)
    _armed_network_join_day(plant)
    first = fx.create_window(plant, "2026-08-01T12:00:00Z", "2026-08-01T12:10:00Z",
                             anchor_sequence_number=2, backtiming_mode="STRICT",
                             guard_seconds=2, live_encoder_units=1)

    resp = api.create_feed_window(
        _window_payload(plant["ch1"]["id"], 7, "2026-08-01T12:20:00Z",
                        "2026-08-01T12:30:00Z", feed_source="NETWORK_ALT"),
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_ANCHOR_ITEM_NOT_FOUND")

    windows, _meta = validate_paginated(
        api.list_channel_feed_windows(plant["ch1"]["id"], plant["mco_headers"])
    )
    assert [w["id"] for w in windows] == [first["id"]]


def test_disjoint_window_naming_the_real_anchor_is_planned(api):
    """The same disjoint interval with the anchor that does exist is accepted.

    PRD §3.7: "a new window's span from `join_utc` less `guard_seconds` through
    `breakaway_utc` plus `guard_seconds`, endpoints included, must not intersect
    the equally guarded span of any other window on the same channel whose
    `state` is `PLANNED` or `JOINED`."

    Design: Difficulty/priority_pair_validation_conflict/feed_window_overlap_temporal_beats_missing_anchor_constraint
    """
    plant = fx.setup_base_plant(with_subchannel=False, clock_utc=_CLOCK)
    _armed_network_join_day(plant)
    fx.create_window(plant, "2026-08-01T12:00:00Z", "2026-08-01T12:10:00Z",
                     anchor_sequence_number=2, backtiming_mode="STRICT",
                     guard_seconds=2, live_encoder_units=1)

    resp = api.create_feed_window(
        _window_payload(plant["ch1"]["id"], 2, "2026-08-01T12:20:00Z",
                        "2026-08-01T12:30:00Z", feed_source="NETWORK_ALT"),
        plant["mco_headers"],
    )
    created = validate_success(resp, 201)
    assert created["state"] == "PLANNED"
    assert created["anchor_sequence_number"] == 2


# ===========================================================================
# Pair 3 — the safety band (409) outranks the temporal band (409) on an arm
# ===========================================================================

def _validated_day_uncleared_and_over_variance(plant):
    """A VALIDATED day that carries an ungraded PROGRAM and a +31 second overrun.

    Element one is a 1000-second QC_PASSED programme from 12:00:00Z and element
    two is an 831-second programme whose asset was delivered but never graded, so
    that element is created UNCLEARED rather than BLOCKED. The two are exactly
    adjacent (12:00:00 plus 1000 seconds is 12:16:40) so the timeline walk passes,
    while the 1831-second total against an 1800-second window leaves the projected
    variance one second past the arming tolerance.
    """
    passed = fx.setup_qc_passed_asset(plant, 1000)
    ungraded = fx.create_asset(plant, expected_duration_seconds=831)
    delivered = fx.deliver_asset(plant, ungraded["id"], measured_duration_seconds=831)
    assert fx.read_asset(ungraded["id"])["status"] == "RECEIVED", \
        "setup must leave the second asset delivered but ungraded"

    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM", "asset_id": passed["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1000, "max_trim_seconds": 0},
        {"sequence_number": 2, "element_kind": "PROGRAM", "asset_id": ungraded["id"],
         "scheduled_start_utc": "2026-08-01T12:16:40Z",
         "scheduled_duration_seconds": 831, "max_trim_seconds": 0},
    ]
    playlist = fx.ingest(plant, items, window_duration_seconds=1800)
    validated = fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    assert validated["status"] == "VALIDATED"
    assert validated["blocked_item_count"] == 0
    assert validated["projected_end_variance_seconds"] == 31

    element_two = fx.list_items(playlist["id"], plant["mco_headers"])[1]
    assert element_two["clearance_status"] == "UNCLEARED"
    return {
        "playlist": validated,
        "ungraded": ungraded,
        "ungraded_version": delivered["version"],
        "element_two": element_two,
    }


def test_arming_uncleared_and_overrunning_day_reports_the_uncleared_content(api):
    """The content-safety gate answers before the variance gate on the same arm.

    PRD §3.5: "Every item whose `element_kind` is `PROGRAM`, `COMMERCIAL`,
    `INTERSTITIAL` or `PROMO` must have `clearance_status` `CLEARED`, otherwise
    `ERR_UNCLEARED_CONTENT_ON_AIR`."

    PRD §2.8 puts that gate ahead of the overrun: the bands run "state
    preconditions (14–24), safety and regulatory rules (25–34), temporal rules
    (35–46)".

    Design: Difficulty/priority_pair_validation_conflict/uncleared_content_safety_beats_arm_variance_temporal
    """
    plant = fx.setup_base_plant(with_subchannel=False, clock_utc=_CLOCK)
    scene = _validated_day_uncleared_and_over_variance(plant)

    resp = api.change_playlist_state(
        scene["playlist"]["id"], {"target_status": "ARMED"}, plant["mco_headers"]
    )
    error = validate_error(resp, "ERR_UNCLEARED_CONTENT_ON_AIR")
    assert error["error_id"] != "ERR_ARM_VARIANCE_EXCEEDED"

    after = fx.read_playlist(scene["playlist"]["id"])
    assert after["status"] == "VALIDATED", "a refused arm must leave the day validated"
    assert after.get("armed_at_utc") is None
    assert fx.read_item(scene["element_two"]["id"])["clearance_status"] == "UNCLEARED"


def test_arming_a_cleared_but_overrunning_day_reports_the_variance(api):
    """Grading the missing media clears the element and exposes the overrun.

    PRD §3.5: "the absolute value of `projected_end_variance_seconds` must not
    exceed 30 seconds — **exactly plus or minus 30 seconds arms successfully and
    31 does not** — otherwise `ERR_ARM_VARIANCE_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/uncleared_content_safety_beats_arm_variance_temporal
    """
    plant = fx.setup_base_plant(with_subchannel=False, clock_utc=_CLOCK)
    scene = _validated_day_uncleared_and_over_variance(plant)
    arm = {"target_status": "ARMED"}

    validate_error(
        api.change_playlist_state(scene["playlist"]["id"], arm, plant["mco_headers"]),
        "ERR_UNCLEARED_CONTENT_ON_AIR",
    )

    report = fx.submit_qc(plant, scene["ungraded"]["id"], scene["ungraded_version"],
                          defect_codes=[], measured_duration_seconds=831)
    assert report["verdict"] == "PASS"
    assert report["technical_score"] == 100
    assert fx.read_asset(scene["ungraded"]["id"])["status"] == "QC_PASSED"
    assert fx.read_item(scene["element_two"]["id"])["clearance_status"] == "CLEARED"

    graded_day = fx.read_playlist(scene["playlist"]["id"])
    assert graded_day["status"] == "VALIDATED"
    assert graded_day["projected_end_variance_seconds"] == 31, \
        "grading media must not change any booked duration"

    validate_error(
        api.change_playlist_state(scene["playlist"]["id"], arm, plant["mco_headers"]),
        "ERR_ARM_VARIANCE_EXCEEDED",
    )
    assert fx.read_playlist(scene["playlist"]["id"])["status"] == "VALIDATED"
