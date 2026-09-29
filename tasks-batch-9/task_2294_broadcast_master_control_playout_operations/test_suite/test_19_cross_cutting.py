"""Cross-cutting layers: concurrency tokens, envelopes, cascades and the ladder.

The three optimistic-concurrency tokens of PRD §2.6 sit on exactly six writes
and nowhere else, the envelopes of §2.2 are uniform across every response, the
cascades of §2.12 land before the response is returned, and the ladder of §2.8
fixes which of several simultaneous violations a client is shown. These tests
exercise those layers where they meet the domain.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    as_run_kinds,
    assert_as_run_entry,
    assert_asset,
    assert_bandwidth_conservation,
    assert_channel,
    assert_envelope_meta,
    assert_feed_window,
    assert_multiplex,
    assert_operator,
    assert_override,
    assert_playlist,
    assert_playlist_item,
    assert_qc_report,
    assert_regulatory_notification,
    assert_spot_count_conservation,
    assert_spot_order,
    assert_technical_fault,
    assert_transmitter,
    item_by_sequence,
    make_headers,
    make_master_control_headers,
    make_qc_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

# ---------------------------------------------------------------------------
# Private setup helpers (test_helpers is read-only, so these live here)
# ---------------------------------------------------------------------------

_NEXT_DAY = "2026-08-02"
_NEXT_DAY_START = "2026-08-02T12:00:00Z"


def _plant_with_three_assets():
    """Base plant plus three passed assets of 1800, 30 and 60 seconds."""
    plant = fx.setup_base_plant()
    plant["a1800"] = fx.setup_qc_passed_asset(plant, 1800)
    plant["a30"] = fx.setup_qc_passed_asset(plant, 30)
    plant["a60"] = fx.setup_qc_passed_asset(plant, 60)
    return plant


def _single_element_playlist(plant):
    """One 1800-second programme element starting exactly at the booked start."""
    return fx.ingest(
        plant,
        [{"sequence_number": 1, "element_kind": "PROGRAM",
          "asset_id": plant["a1800"]["id"],
          "scheduled_start_utc": _NEXT_DAY_START,
          "scheduled_duration_seconds": 1800}],
        broadcast_day=_NEXT_DAY,
        schedule_start_utc=_NEXT_DAY_START,
    )


def _three_element_revision_items(plant):
    """Three contiguous elements: 1800 + 30 + 60 seconds from the booked start."""
    return [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": plant["a1800"]["id"],
         "scheduled_start_utc": _NEXT_DAY_START,
         "scheduled_duration_seconds": 1800},
        {"sequence_number": 2, "element_kind": "PROMO",
         "asset_id": plant["a30"]["id"],
         "scheduled_start_utc": "2026-08-02T12:30:00Z",
         "scheduled_duration_seconds": 30},
        {"sequence_number": 3, "element_kind": "INTERSTITIAL",
         "asset_id": plant["a60"]["id"],
         "scheduled_start_utc": "2026-08-02T12:30:30Z",
         "scheduled_duration_seconds": 60},
    ]


def _instant(timestamp):
    """Strip fractional seconds and the zone marker for whole-second equality."""
    return timestamp.replace("Z", "").split(".")[0]


# ---------------------------------------------------------------------------
# One playlist token per call, however many elements the call rewrites
# ---------------------------------------------------------------------------

def test_a_three_element_revision_bumps_the_parent_version_exactly_once(api):
    """Replacing one element with three is a single mutation of the playlist.

    PRD §2.5: "a `version` integer that starts at 1 and increments by exactly one on every mutation of that record"

    Design: Corner/cross_cutting_layers/playlist_revision_occ_counts_the_parent_once_per_call_no_matter_how_many_children_it_rewrites
    """
    plant = _plant_with_three_assets()
    playlist = _single_element_playlist(plant)
    assert playlist["status"] == "IMPORTED"
    before = playlist["version"]

    revised = validate_success(api.apply_traffic_revision(
        playlist["id"],
        {"expected_playlist_version": before,
         "items": _three_element_revision_items(plant)},
        plant["traffic_headers"],
    ))

    assert revised["version"] == before + 1, (
        "three rewritten children still count the parent once"
    )
    assert revised["item_count"] == 3
    assert revised["traffic_revision"] == 2


def test_a_playlist_token_from_before_a_prior_revision_is_refused(api):
    """The token the first revision consumed cannot be spent a second time.

    PRD §2.6: "A mismatch is rejected with `ERR_STALE_PLAYLIST_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_layers/playlist_revision_occ_counts_the_parent_once_per_call_no_matter_how_many_children_it_rewrites
    """
    plant = _plant_with_three_assets()
    playlist = _single_element_playlist(plant)
    pre_image = playlist["version"]

    validate_success(api.apply_traffic_revision(
        playlist["id"],
        {"expected_playlist_version": pre_image,
         "items": _three_element_revision_items(plant)},
        plant["traffic_headers"],
    ))

    resp = api.apply_traffic_revision(
        playlist["id"],
        {"expected_playlist_version": pre_image,
         "items": _three_element_revision_items(plant)},
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_STALE_PLAYLIST_VERSION", expected_status=412)

    after = fx.read_playlist(playlist["id"], plant["traffic_headers"])
    assert after["version"] == pre_image + 1
    assert after["traffic_revision"] == 2
    assert after["item_count"] == 3


def test_a_refused_revision_advances_neither_counter_on_the_playlist(api):
    """A one-second hole rejects the whole call, so no child and no counter moves.

    PRD §3.5: "if the next element's `scheduled_start_utc` is *after* that end there is a hole and the pass fails with `ERR_SCHEDULE_GAP_DETECTED` — **a one-second hole is a gap**"

    Design: Corner/cross_cutting_layers/playlist_revision_occ_counts_the_parent_once_per_call_no_matter_how_many_children_it_rewrites
    """
    plant = _plant_with_three_assets()
    playlist = _single_element_playlist(plant)
    before = playlist["version"]

    resp = api.apply_traffic_revision(
        playlist["id"],
        {"expected_playlist_version": before,
         "items": [
             {"sequence_number": 1, "element_kind": "PROGRAM",
              "asset_id": plant["a1800"]["id"],
              "scheduled_start_utc": _NEXT_DAY_START,
              "scheduled_duration_seconds": 1800},
             {"sequence_number": 2, "element_kind": "PROMO",
              "asset_id": plant["a30"]["id"],
              "scheduled_start_utc": "2026-08-02T12:30:01Z",
              "scheduled_duration_seconds": 30},
         ]},
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_SCHEDULE_GAP_DETECTED")

    after = fx.read_playlist(playlist["id"], plant["traffic_headers"])
    assert after["version"] == before
    assert after["traffic_revision"] == 1
    assert after["item_count"] == 1


def test_removals_and_additions_are_one_revision_and_one_version_step(api):
    """Dropping two elements while re-supplying one still costs a single token.

    PRD §3.5: "Every existing item whose `playout_status` is still `SCHEDULED` is deleted and replaced by the supplied revision items"

    Design: Corner/cross_cutting_layers/playlist_revision_occ_counts_the_parent_once_per_call_no_matter_how_many_children_it_rewrites
    """
    plant = _plant_with_three_assets()
    playlist = _single_element_playlist(plant)

    grown = validate_success(api.apply_traffic_revision(
        playlist["id"],
        {"expected_playlist_version": playlist["version"],
         "items": _three_element_revision_items(plant)},
        plant["traffic_headers"],
    ))
    assert grown["item_count"] == 3

    shrunk = validate_success(api.apply_traffic_revision(
        playlist["id"],
        {"expected_playlist_version": grown["version"],
         "items": [
             {"sequence_number": 1, "element_kind": "PROGRAM",
              "asset_id": plant["a1800"]["id"],
              "scheduled_start_utc": _NEXT_DAY_START,
              "scheduled_duration_seconds": 1800},
         ],
         "removed_sequence_numbers": [2, 3]},
        plant["traffic_headers"],
    ))

    assert shrunk["version"] == grown["version"] + 1
    assert shrunk["item_count"] == 1
    assert shrunk["traffic_revision"] == 3

    items, meta = validate_paginated(
        api.list_playlist_items(playlist["id"], plant["traffic_headers"])
    )
    assert meta["total_count"] == 1
    assert items[0]["sequence_number"] == 1


# ---------------------------------------------------------------------------
# The makegood token names a playlist while the path names a spot order
# ---------------------------------------------------------------------------

def _two_order_day_on_air():
    """A four-element day on air whose two commercials belong to two orders."""
    plant = fx.setup_base_plant()
    plant["a1800"] = fx.setup_qc_passed_asset(plant, 1800)
    plant["a30"] = fx.setup_qc_passed_asset(plant, 30)
    plant["a1740"] = fx.setup_qc_passed_asset(plant, 1740)
    plant["order1"] = fx.create_order(plant)
    plant["order2"] = fx.create_order(plant)
    plant["playlist"] = fx.ingest(plant, [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": plant["a1800"]["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1800},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": plant["a30"]["id"], "spot_order_id": plant["order1"]["id"],
         "scheduled_start_utc": "2026-08-01T12:30:00Z",
         "scheduled_duration_seconds": 30},
        {"sequence_number": 3, "element_kind": "COMMERCIAL",
         "asset_id": plant["a30"]["id"], "spot_order_id": plant["order2"]["id"],
         "scheduled_start_utc": "2026-08-01T12:30:30Z",
         "scheduled_duration_seconds": 30},
        {"sequence_number": 4, "element_kind": "PROGRAM",
         "asset_id": plant["a1740"]["id"],
         "scheduled_start_utc": "2026-08-01T12:31:00Z",
         "scheduled_duration_seconds": 1740},
    ])
    fx.drive_playlist(plant, plant["playlist"]["id"], "VALIDATED")
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    fx.drive_playlist(plant, plant["playlist"]["id"], "ARMED")
    fx.set_clock("2026-08-01T11:59:00Z")
    plant["playlist"] = fx.drive_playlist(plant, plant["playlist"]["id"], "ON_AIR")
    plant["items"] = fx.list_items(plant["playlist"]["id"], plant["traffic_headers"])
    return plant


def _credit_both_orders(plant):
    """Skip the two commercials so each order carries one credited spot."""
    for sequence_number in (2, 3):
        item = item_by_sequence(plant["items"], sequence_number)
        fx.skip_item(plant, item["id"], "2026-08-01T11:59:00Z")


def _makegood_target_playlist(plant):
    """The next broadcast day on the same channel, one programme element long."""
    return fx.ingest(
        plant,
        [{"sequence_number": 1, "element_kind": "PROGRAM",
          "asset_id": plant["a1800"]["id"],
          "scheduled_start_utc": _NEXT_DAY_START,
          "scheduled_duration_seconds": 1800}],
        broadcast_day=_NEXT_DAY,
        schedule_start_utc=_NEXT_DAY_START,
    )


def test_a_makegood_returns_a_playlist_element_although_the_path_names_the_order(api):
    """The token belongs to the playlist in the body, not to the order in the path.

    PRD §3.9: "A successful makegood creates a playlist element with `is_makegood` set to true, `element_kind` `COMMERCIAL`, and `replaces_item_id` pointing at the credited element, in `playout_status` `SCHEDULED`."

    Design: Corner/cross_cutting_layers/the_makegood_token_names_a_playlist_while_the_path_names_a_spot_order
    """
    plant = _two_order_day_on_air()
    _credit_both_orders(plant)
    credited = item_by_sequence(plant["items"], 2)
    target = _makegood_target_playlist(plant)

    resp = api.place_makegood(
        plant["order1"]["id"],
        {"target_playlist_id": target["id"],
         "expected_playlist_version": target["version"],
         "sequence_number": 2,
         "scheduled_start_utc": "2026-08-02T12:30:00Z",
         "scheduled_duration_seconds": 30},
        plant["traffic_headers"],
    )
    created = validate_success(resp, 201)

    assert created["is_makegood"] is True
    assert created["element_kind"] == "COMMERCIAL"
    assert created["playout_status"] == "SCHEDULED"
    assert created["sequence_number"] == 2
    assert created["replaces_item_id"] == credited["id"]
    assert created["playlist_id"] == target["id"]


def test_a_makegood_from_a_second_order_collides_on_the_shared_target_playlist(api):
    """Two orders placing into one playlist serialise on that playlist's version.

    PRD §2.6: "Placing a makegood spot requires `expected_playlist_version` to equal the target playlist's current `version`."

    Design: Corner/cross_cutting_layers/the_makegood_token_names_a_playlist_while_the_path_names_a_spot_order
    """
    plant = _two_order_day_on_air()
    _credit_both_orders(plant)
    target = _makegood_target_playlist(plant)
    pre_image = target["version"]

    fx.place_makegood(plant, plant["order1"]["id"], target["id"], pre_image, 2,
                      "2026-08-02T12:30:00Z", scheduled_duration_seconds=30)

    resp = api.place_makegood(
        plant["order2"]["id"],
        {"target_playlist_id": target["id"],
         "expected_playlist_version": pre_image,
         "sequence_number": 3,
         "scheduled_start_utc": "2026-08-02T12:30:30Z",
         "scheduled_duration_seconds": 30},
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_STALE_PLAYLIST_VERSION", expected_status=412)

    order2 = fx.read_order(plant["order2"]["id"], plant["traffic_headers"])
    assert order2["credited_spots"] == 1, "the refused makegood reversed nothing"
    assert_spot_count_conservation(order2)


def test_the_target_playlist_version_advances_once_per_makegood(api):
    """Refreshing the token lets the second order place its own compensating spot.

    PRD §3.9: "It increments both the order's `version` and the playlist's `version`."

    Design: Corner/cross_cutting_layers/the_makegood_token_names_a_playlist_while_the_path_names_a_spot_order
    """
    plant = _two_order_day_on_air()
    _credit_both_orders(plant)
    target = _makegood_target_playlist(plant)
    pre_image = target["version"]

    fx.place_makegood(plant, plant["order1"]["id"], target["id"], pre_image, 2,
                      "2026-08-02T12:30:00Z", scheduled_duration_seconds=30)
    after_first = fx.read_playlist(target["id"], plant["traffic_headers"])
    assert after_first["version"] == pre_image + 1
    assert after_first["item_count"] == 2

    fx.place_makegood(plant, plant["order2"]["id"], target["id"],
                      after_first["version"], 3, "2026-08-02T12:30:30Z",
                      scheduled_duration_seconds=30)
    after_second = fx.read_playlist(target["id"], plant["traffic_headers"])
    assert after_second["version"] == pre_image + 2
    assert after_second["item_count"] == 3

    for order_key in ("order1", "order2"):
        order = fx.read_order(plant[order_key]["id"], plant["traffic_headers"])
        assert order["credited_spots"] == 0
        assert order["scheduled_spots"] == 1
        assert order["credit_accrued_cents"] == 0
        assert_spot_count_conservation(order)

# ---------------------------------------------------------------------------
# Three bandwidth writes share one multiplex counter
# ---------------------------------------------------------------------------

def _demand_change(api, plant, expected_multiplex_version, requested_bitrate_kbps,
                   channel_key="ch1"):
    """Re-run the waterfall by moving one channel's requested bitrate."""
    return api.patch_channel_allocation(
        plant[channel_key]["id"],
        {"expected_multiplex_version": expected_multiplex_version,
         "requested_bitrate_kbps": requested_bitrate_kbps},
        plant["eng_headers"],
    )


def _third_channel_payload(plant, expected_multiplex_version):
    """A shape-valid third service on the same multiplex."""
    return {
        "multiplex_id": plant["multiplex"]["id"],
        "expected_multiplex_version": expected_multiplex_version,
        "call_sign": "WXYZ-DT3",
        "channel_number": "12.3",
        "service_class": "SUBCHANNEL",
        "parent_channel_id": plant["ch1"]["id"],
        "resolution_class": "SD_480I",
        "requested_bitrate_kbps": 4000,
        "floor_bitrate_kbps": 2000,
        "priority_rank": 3,
    }


def test_a_demand_change_reslices_the_pool_and_steps_the_counter_once(api):
    """One allocation write, one waterfall run, one increment of the multiplex.

    PRD §3.2: "`assigned_kbps` is the sum of `allocated_bitrate_kbps` over the candidate channels whose `allocation_state` ended as `ACTIVE` or `STANDBY`; `available_kbps` is `effective_capacity_kbps` less `assigned_kbps`; and `starved_channel_count` is the number of candidates that ended as `STARVED`."

    Design: Corner/cross_cutting_layers/three_multiplex_writes_share_one_counter_so_every_bitrate_change_in_a_pool_serialises
    """
    plant = fx.setup_base_plant()
    before = plant["multiplex"]["version"]

    validate_success(_demand_change(api, plant, before, 12000))

    mux = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert mux["version"] == before + 1, "one pool rewrite is one mutation"
    assert mux["effective_capacity_kbps"] == 38000
    assert mux["assigned_kbps"] == 18000
    assert mux["available_kbps"] == 20000
    assert mux["starved_channel_count"] == 0
    assert_bandwidth_conservation(mux)

    ch1 = fx.read_channel(plant["ch1"]["id"], plant["eng_headers"])
    ch2 = fx.read_channel(plant["ch2"]["id"], plant["eng_headers"])
    assert ch1["allocated_bitrate_kbps"] == 12000
    assert ch2["allocated_bitrate_kbps"] == 6000


def test_a_sibling_allocation_change_holding_the_pre_image_token_is_refused(api):
    """Two channels in one pool serialise on the multiplex, not on themselves.

    PRD §2.6: "Changing a channel's bitrate demand, floor, priority rank or pinned allocation requires `expected_multiplex_version` to equal the parent multiplex's current `version`, because the new allocation set supersedes the one the client based its request on."

    Design: Corner/cross_cutting_layers/three_multiplex_writes_share_one_counter_so_every_bitrate_change_in_a_pool_serialises
    """
    plant = fx.setup_base_plant()
    pre_image = plant["multiplex"]["version"]

    validate_success(_demand_change(api, plant, pre_image, 12000))

    resp = _demand_change(api, plant, pre_image, 5000, channel_key="ch2")
    validate_error(resp, "ERR_STALE_MULTIPLEX_VERSION", expected_status=412)

    ch2 = fx.read_channel(plant["ch2"]["id"], plant["eng_headers"])
    assert ch2["requested_bitrate_kbps"] == 6000, "the refused write changed nothing"
    assert ch2["allocated_bitrate_kbps"] == 6000


def test_channel_admission_consumes_the_same_counter_as_an_allocation_change(api):
    """Creating a service on the pool is stale once a sibling has re-sliced it.

    PRD §2.6: "Creating a channel requires `expected_multiplex_version` to equal the parent multiplex's current `version`."

    Design: Corner/cross_cutting_layers/three_multiplex_writes_share_one_counter_so_every_bitrate_change_in_a_pool_serialises
    """
    plant = fx.setup_base_plant()
    pre_image = plant["multiplex"]["version"]

    validate_success(_demand_change(api, plant, pre_image, 12000))

    resp = api.create_channel(_third_channel_payload(plant, pre_image),
                              plant["eng_headers"])
    validate_error(resp, "ERR_STALE_MULTIPLEX_VERSION", expected_status=412)

    mux = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert mux["assigned_kbps"] == 18000
    assert mux["available_kbps"] == 20000

    accepted = validate_success(
        api.create_channel(_third_channel_payload(plant, mux["version"]),
                           plant["eng_headers"]),
        201,
    )
    assert accepted["allocated_bitrate_kbps"] == 4000
    grown = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert grown["assigned_kbps"] == 22000
    assert grown["available_kbps"] == 16000
    assert_bandwidth_conservation(grown)


def test_a_rebalance_spends_the_same_counter_as_the_allocation_change(api):
    """The third bandwidth write reads and bumps the one shared version too.

    PRD §2.6: "Re-running the bitrate waterfall across a multiplex requires `expected_multiplex_version` to equal that multiplex's current `version`."

    Design: Corner/cross_cutting_layers/three_multiplex_writes_share_one_counter_so_every_bitrate_change_in_a_pool_serialises
    """
    plant = fx.setup_base_plant()
    pre_image = plant["multiplex"]["version"]

    validate_success(_demand_change(api, plant, pre_image, 12000))

    resp = api.rebalance_multiplex(plant["multiplex"]["id"],
                                   {"expected_multiplex_version": pre_image},
                                   plant["eng_headers"])
    validate_error(resp, "ERR_STALE_MULTIPLEX_VERSION", expected_status=412)

    stale_free = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert stale_free["version"] == pre_image + 1

    fx.rebalance(plant, stale_free["version"])
    after = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert after["version"] == pre_image + 2
    assert after["assigned_kbps"] == 18000
    assert after["available_kbps"] == 20000
    assert_bandwidth_conservation(after)

# ---------------------------------------------------------------------------
# The asset token has exactly one call site although two transitions claim it
# ---------------------------------------------------------------------------

_JUSTIFICATION = "Programme must air tonight; the defect is cosmetic only."


def _ingest_report(expected_asset_version, inspector_id, defect_codes):
    return {
        "expected_asset_version": expected_asset_version,
        "inspected_by_operator_id": inspector_id,
        "basis": "INGEST",
        "defect_codes": defect_codes,
        "measured_duration_seconds": 1800,
    }


def test_both_qc_verdicts_travel_through_the_single_token_bearing_write(api):
    """Failing and passing inspections are the same endpoint spending one token.

    PRD §3.4: "Either outcome increments the asset's `version` by one."

    Design: Corner/cross_cutting_layers/the_asset_token_has_exactly_one_call_site_although_two_transitions_claim_it
    """
    plant = fx.setup_base_plant()
    asset = fx.create_asset(plant, expected_duration_seconds=1800)
    delivered = fx.deliver_asset(plant, asset["id"], measured_duration_seconds=1800)

    failing = validate_success(api.submit_qc_report(
        asset["id"],
        _ingest_report(delivered["version"], plant["qc"]["id"], ["AUDIO_LOSS"]),
        plant["qc_headers"],
    ), 201)
    assert failing["verdict"] == "FAIL"
    after_fail = fx.read_asset(asset["id"], plant["qc_headers"])
    assert after_fail["status"] == "QC_FAILED"
    assert after_fail["version"] == delivered["version"] + 1

    redelivered = fx.deliver_asset(plant, asset["id"], measured_duration_seconds=1800)
    assert redelivered["technical_score_ingest"] is None
    assert redelivered["qc_verdict"] is None

    passing = validate_success(api.submit_qc_report(
        asset["id"],
        _ingest_report(redelivered["version"], plant["qc"]["id"], []),
        plant["qc_headers"],
    ), 201)
    assert passing["verdict"] == "PASS"
    after_pass = fx.read_asset(asset["id"], plant["qc_headers"])
    assert after_pass["status"] == "QC_PASSED"
    assert after_pass["version"] == redelivered["version"] + 1


def test_the_waiver_and_the_retraction_carry_no_asset_token_at_all(api):
    """Two further asset transitions mutate the record without any version field.

    PRD §2.6: "No other endpoint accepts a version field, and none should be invented for them"

    Design: Corner/cross_cutting_layers/the_asset_token_has_exactly_one_call_site_although_two_transitions_claim_it
    """
    plant = fx.setup_base_plant()
    asset = fx.setup_qc_failed_asset(plant, 1800)
    assert asset["status"] == "QC_FAILED"
    assert asset["technical_score_ingest"] == 75
    before = asset["version"]

    waived = validate_success(api.sign_qc_waiver(
        asset["id"],
        {"waived_by_operator_id": plant["pd"]["id"],
         "waiver_justification": _JUSTIFICATION},
        plant["pd_headers"],
    ))
    assert waived["status"] == "QC_WAIVED"
    assert waived["version"] == before + 1

    retracted = validate_success(api.retract_asset(
        asset["id"], {"reason": "Rights pull from the distributor"},
        plant["pd_headers"],
    ))
    assert retracted["status"] == "RETRACTED"
    assert retracted["version"] == before + 2

    resp = api.retract_asset(asset["id"], {"reason": "Second attempt"},
                             plant["pd_headers"])
    validate_error(resp, "ERR_ASSET_INVALID_STATE")


def test_a_stale_asset_token_outranks_the_state_precondition_on_the_same_call(api):
    """A retracted asset with a stale token reports the token, not the status.

    PRD §2.6: "the version check is strictly earlier in the ladder than any state precondition."

    Design: Corner/cross_cutting_layers/the_asset_token_has_exactly_one_call_site_although_two_transitions_claim_it
    """
    plant = fx.setup_base_plant()
    asset = fx.create_asset(plant, expected_duration_seconds=1800)
    stale = asset["version"]
    delivered = fx.deliver_asset(plant, asset["id"], measured_duration_seconds=1800)
    assert delivered["version"] == stale + 1

    retracted = fx.retract(plant, asset["id"])
    assert retracted["status"] == "RETRACTED"

    resp = api.submit_qc_report(
        asset["id"], _ingest_report(stale, plant["qc"]["id"], []),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_STALE_ASSET_VERSION", expected_status=412)

    reports, meta = validate_paginated(api.list_qc_reports(plant["qc_headers"]))
    assert meta["total_count"] == 0, "the refused inspection wrote no report"
    assert reports == []

    after = fx.read_asset(asset["id"], plant["qc_headers"])
    assert after["status"] == "RETRACTED"
    assert after["version"] == retracted["version"]

# ---------------------------------------------------------------------------
# Every other mutating write is token-free and simply takes the last writer
# ---------------------------------------------------------------------------

def test_successive_air_state_changes_take_no_token_and_the_last_one_stands(api):
    """Three deliberate air moves in a row, each accepted on its own merits.

    PRD §3.3: "Every air-state change recomputes `posture` and increments the channel's `version` by one."

    Design: Corner/cross_cutting_layers/every_other_mutating_endpoint_is_token_free_so_last_writer_wins_is_the_declared_model_there
    """
    plant = fx.setup_base_plant()
    before = fx.read_channel(plant["ch1"]["id"], plant["mco_headers"])["version"]

    lit = validate_success(api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "ON_AIR"}, plant["mco_headers"]))
    assert lit["air_status"] == "ON_AIR"
    assert lit["version"] == before + 1
    assert lit["posture"] == "NORMAL"

    bars = validate_success(api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "BARS_AND_TONE"},
        plant["mco_headers"]))
    assert bars["air_status"] == "BARS_AND_TONE"
    assert bars["version"] == before + 2

    back = validate_success(api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "ON_AIR", "reason": "Fault cleared"},
        plant["mco_headers"]))
    assert back["air_status"] == "ON_AIR"
    assert back["version"] == before + 3

    assert fx.read_channel(plant["ch1"]["id"], plant["mco_headers"])["air_status"] == "ON_AIR"


def test_successive_fault_transitions_take_no_token_and_each_advance_stands(api):
    """A fault walks its whole path with nothing but a target state each time.

    PRD §3.3: "Every fault transition increments the fault's `version`, and those that change the channel increment the channel's `version` as well."

    Design: Corner/cross_cutting_layers/every_other_mutating_endpoint_is_token_free_so_last_writer_wins_is_the_declared_model_there
    """
    plant = fx.setup_base_plant()
    fault = fx.report_channel_fault(plant, "CAPTION_LOSS", "MINOR",
                                    "2026-08-01T09:00:00Z")
    assert fault["state"] == "DETECTED"
    before = fault["version"]

    acknowledged = validate_success(api.change_fault_state(
        fault["id"], {"target_state": "ACKNOWLEDGED"}, plant["mco_headers"]))
    assert acknowledged["state"] == "ACKNOWLEDGED"
    assert acknowledged["version"] == before + 1

    mitigated = validate_success(api.change_fault_state(
        fault["id"], {"target_state": "MITIGATED",
                      "mitigation_code": "SWITCH_TO_BACKUP"},
        plant["mco_headers"]))
    assert mitigated["state"] == "MITIGATED"
    assert mitigated["version"] == before + 2

    resolved = validate_success(api.change_fault_state(
        fault["id"], {"target_state": "RESOLVED"}, plant["mco_headers"]))
    assert resolved["state"] == "RESOLVED"
    assert resolved["version"] == before + 3
    assert resolved["cleared_utc"] is not None

    channel = fx.read_channel(plant["ch1"]["id"], plant["mco_headers"])
    assert channel["open_fault_count"] == 0
    assert channel["posture"] == "NORMAL"


def test_playout_events_take_no_token_and_append_one_row_each(api):
    """Automation reports two events in sequence with no concurrency field at all.

    PRD §3.6: "Every accepted event appends **exactly one** as-run entry; the as-run log is the only durable record of what aired."

    Design: Corner/cross_cutting_layers/every_other_mutating_endpoint_is_token_free_so_last_writer_wins_is_the_declared_model_there
    """
    scn = fx.setup_on_air_playlist()
    item1 = scn["items"][0]
    fx.set_clock("2026-08-01T12:00:00Z")

    cued = validate_success(api.post_playout_event(
        item1["id"], {"event_kind": "CUE", "event_utc": "2026-08-01T12:00:00Z"},
        scn["mco_headers"]), 201)
    assert cued["event_kind"] == "CUE"

    started = validate_success(api.post_playout_event(
        item1["id"], {"event_kind": "START", "event_utc": "2026-08-01T12:00:00Z"},
        scn["mco_headers"]), 201)
    assert started["event_kind"] == "START"

    entries = fx.list_item_as_run(item1["id"], scn["mco_headers"])
    assert as_run_kinds(entries) == ["CUE", "START"]

    item = fx.read_item(item1["id"], scn["mco_headers"])
    assert item["playout_status"] == "PLAYING"


def test_a_transmitter_power_change_takes_no_token_and_files_immediately(api):
    """The plant write carries a target state and a percentage, never a version.

    PRD §3.1: "a reduction to below 80 percent of licensed power creates a `POWER_REDUCTION` notification in status `PENDING`, with `triggering_utc` set to the logical clock instant of the change, `due_utc` set to 24 hours after that instant, and `observed_power_pct` recording the percentage observed at the triggering event"

    Design: Corner/cross_cutting_layers/every_other_mutating_endpoint_is_token_free_so_last_writer_wins_is_the_declared_model_there
    """
    plant = fx.setup_base_plant()
    before = plant["transmitter"]["version"]

    reduced = validate_success(api.change_transmitter_power_state(
        plant["transmitter"]["id"], {"target_state": "REDUCED_POWER", "power_pct": 70},
        plant["eng_headers"]))
    assert reduced["operational_state"] == "REDUCED_POWER"
    assert reduced["current_power_pct"] == 70
    assert reduced["notification_pending_count"] == 1
    assert reduced["version"] == before + 1

    notifications = fx.list_notifications(plant["transmitter"]["id"],
                                          plant["compliance_headers"])
    assert len(notifications) == 1
    filing = notifications[0]
    assert filing["kind"] == "POWER_REDUCTION"
    assert filing["status"] == "PENDING"
    assert _instant(filing["triggering_utc"]) == "2026-08-01T09:00:00"
    assert _instant(filing["due_utc"]) == "2026-08-02T09:00:00"
    assert filing["observed_power_pct"] == 70

# ---------------------------------------------------------------------------
# One chronological run over every entity and every cascade in the domain
# ---------------------------------------------------------------------------

def _run_the_whole_day(api):
    """Drive the plant, the media chain, the day, a window, a fault and an alert."""
    scn = fx.setup_on_air_playlist()

    scn["window"] = fx.create_window(scn, "2026-08-01T12:31:00Z",
                                     "2026-08-01T12:36:00Z")

    fx.set_clock("2026-08-01T12:00:00Z")
    item1 = scn["items"][0]
    fx.cue_item(scn, item1["id"], "2026-08-01T12:00:00Z")
    fx.start_item(scn, item1["id"], "2026-08-01T12:00:00Z")

    fault = fx.report_channel_fault(scn, "CAPTION_LOSS", "MINOR",
                                    "2026-08-01T12:00:00Z")
    fx.advance_fault(scn, fault["id"], "ACKNOWLEDGED")
    fx.advance_fault(scn, fault["id"], "MITIGATED",
                     mitigation_code="SWITCH_TO_BACKUP")
    scn["fault"] = fx.advance_fault(scn, fault["id"], "RESOLVED")

    override = fx.setup_active_override(scn, "CRAWL")
    scn["override"] = fx.release_override(scn, override["id"])

    scn["transmitter"] = fx.change_power_state(scn, "REDUCED_POWER", power_pct=70)
    return scn


def test_one_chronological_run_reaches_every_entity_in_the_domain(api):
    """Twelve versioned resources and two records of fact all exist and are sound.

    PRD §2.5: "Every other entity in the domain (transmitters, multiplexes, channels, operators, assets, playlists, playlist items, spot orders, network feed windows, emergency overrides, technical faults and regulatory notifications) carries the full set of `id`, `created_at`, `updated_at` and `version`."

    Design: Corner/cross_cutting_layers/one_chronological_scenario_touches_all_14_entities_and_every_cascade_edge_in_the_domain
    """
    scn = _run_the_whole_day(api)

    assert_transmitter(fx.read_transmitter(scn["transmitter"]["id"], scn["eng_headers"]))
    assert_multiplex(fx.read_multiplex(scn["multiplex"]["id"], scn["eng_headers"]))
    assert_channel(fx.read_channel(scn["ch1"]["id"], scn["mco_headers"]))
    assert_operator(fx.read_operator(scn["mco"]["id"], scn["admin_headers"]))
    assert_asset(fx.read_asset(scn["assets"]["prog1"]["id"], scn["qc_headers"]))
    assert_playlist(fx.read_playlist(scn["playlist"]["id"], scn["traffic_headers"]))
    assert_playlist_item(fx.read_item(scn["items"][0]["id"], scn["mco_headers"]))
    assert_spot_order(fx.read_order(scn["order"]["id"], scn["traffic_headers"]))
    assert_feed_window(fx.read_feed_window(scn["window"]["id"], scn["mco_headers"]))
    assert_override(fx.read_override(scn["override"]["id"], scn["mco_headers"]))
    assert_technical_fault(fx.read_fault(scn["fault"]["id"], scn["mco_headers"]))

    notifications = fx.list_notifications(scn["transmitter"]["id"],
                                          scn["compliance_headers"])
    assert len(notifications) == 1
    assert_regulatory_notification(
        fx.read_notification(notifications[0]["id"], scn["compliance_headers"]))

    reports, _ = validate_paginated(api.list_qc_reports(scn["qc_headers"]))
    assert len(reports) == 4
    assert_qc_report(validate_success(
        api.get_qc_report(reports[0]["id"], scn["qc_headers"])))

    entries = fx.list_as_run(scn["playlist"]["id"], scn["mco_headers"])
    assert len(entries) >= 4
    for entry in entries:
        assert_as_run_entry(entry)


def test_the_retraction_cascade_blocks_reverts_and_credits_in_one_call(api):
    """Cascade B walks item, playlist and order without the caller naming any.

    PRD §3.4: "Third, also caused by that flip, every newly blocked item that carries a `spot_order_id` moves one spot on that order from `scheduled_spots` to `credited_spots`, adds the full per-spot credit to `credit_accrued_cents`, and refreshes the order's `status` to `PARTIALLY_CREDITED` or `CLOSED_WITH_CREDIT` as described in §3.9."

    Design: Corner/cross_cutting_layers/one_chronological_scenario_touches_all_14_entities_and_every_cascade_edge_in_the_domain
    """
    scn = fx.setup_playlist_scenario()
    fx.validate_playlist(scn)
    fx.set_air_status(scn, scn["ch1"]["id"], "ON_AIR")
    armed = fx.arm_playlist(scn)
    assert armed["status"] == "ARMED"
    assert armed["armed_at_utc"] is not None

    retracted = validate_success(api.retract_asset(
        scn["assets"]["spot"]["id"], {"reason": "Rights pull from the distributor"},
        scn["pd_headers"]))
    assert retracted["status"] == "RETRACTED"

    items = fx.list_items(scn["playlist"]["id"], scn["traffic_headers"])
    for sequence_number in (2, 3):
        item = item_by_sequence(items, sequence_number)
        assert item["clearance_status"] == "BLOCKED"
        assert item["playout_status"] == "SCHEDULED"

    playlist = fx.read_playlist(scn["playlist"]["id"], scn["traffic_headers"])
    assert playlist["blocked_item_count"] == 2
    assert playlist["status"] == "IMPORTED"
    assert playlist["armed_at_utc"] is None

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["credited_spots"] == 2
    assert order["scheduled_spots"] == 0
    assert order["credit_accrued_cents"] == 200000
    assert order["status"] == "PARTIALLY_CREDITED"
    assert_spot_count_conservation(order)

def test_the_transmitter_cascade_darkens_the_plant_and_preempts_the_day(api):
    """Cascade A runs from the plant to the money in a single off-air call.

    PRD §3.1: "Cascade A then runs with a zero derate: every child multiplex recomputes its `effective_capacity_kbps`, which floors at 0; every channel on every one of those multiplexes is driven to `allocation_state` `STARVED`; each such channel's `posture` becomes `SUSPENDED` and its `air_status` becomes `DARK`; every element of those channels' on-air playlists that has not already reached a terminal playout state is driven to `PREEMPTED`, with the playing element, if any, truncated first; and spot credit is accrued for each affected commercial."

    Design: Corner/cross_cutting_layers/one_chronological_scenario_touches_all_14_entities_and_every_cascade_edge_in_the_domain
    """
    scn = fx.setup_playing_item1()
    fx.set_clock("2026-08-01T12:05:00Z")

    dark = validate_success(api.change_transmitter_power_state(
        scn["transmitter"]["id"],
        {"target_state": "OFF_AIR", "reason": "Antenna strike, plant shut down"},
        scn["eng_headers"]))
    assert dark["operational_state"] == "OFF_AIR"
    assert dark["current_power_pct"] == 0
    assert float(dark["derate_factor"]) == 0.00

    mux = fx.read_multiplex(scn["multiplex"]["id"], scn["eng_headers"])
    assert mux["effective_capacity_kbps"] == 0
    assert mux["assigned_kbps"] == 0
    assert mux["available_kbps"] == 0
    assert mux["starved_channel_count"] == 2
    assert_bandwidth_conservation(mux)

    for channel_key in ("ch1", "ch2"):
        channel = fx.read_channel(scn[channel_key]["id"], scn["mco_headers"])
        assert channel["allocation_state"] == "STARVED"
        assert channel["allocated_bitrate_kbps"] == 0
        assert channel["posture"] == "SUSPENDED"
        assert channel["air_status"] == "DARK"

    items = fx.list_items(scn["playlist"]["id"], scn["traffic_headers"])
    first = item_by_sequence(items, 1)
    assert first["playout_status"] == "TRUNCATED"
    assert first["measured_duration_seconds"] == 300
    for sequence_number in range(2, 8):
        assert item_by_sequence(items, sequence_number)["playout_status"] == "PREEMPTED"

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["credited_spots"] == 2
    assert order["credit_accrued_cents"] == 200000
    assert order["status"] == "PARTIALLY_CREDITED"
    assert_spot_count_conservation(order)


def test_the_cut_in_cascade_truncates_preempts_and_settles_in_one_call(api):
    """Cascade C reaches the channel, the elements, the money and the variance.

    PRD §3.8: "every element whose own booked span, from its `scheduled_start_utc` up to but not including that instant plus its `scheduled_duration_seconds`, lies entirely inside the override's expected span, from the current logical time up to but not including that instant plus `expected_duration_seconds`, and whose `playout_status` is `SCHEDULED` or `CUED`, flips to `PREEMPTED`"

    Design: Corner/cross_cutting_layers/one_chronological_scenario_touches_all_14_entities_and_every_cascade_edge_in_the_domain
    """
    scn = fx.setup_playing_item1()
    fx.set_clock("2026-08-01T12:29:50Z")
    requested = fx.request_override(scn, "CUT_IN",
                                    requested_start_utc="2026-08-01T12:29:50Z")

    activated = validate_success(api.activate_override(
        requested["id"],
        {"authorized_by_operator_id": scn["pd"]["id"], "override_mode": "CUT_IN"},
        scn["pd_headers"]))
    assert activated["state"] == "ACTIVE_CUTIN"
    assert activated["active_mode"] == "CUT_IN"
    assert activated["truncated_item_count"] == 1
    assert activated["preempted_item_count"] == 2

    channel = fx.read_channel(scn["ch1"]["id"], scn["mco_headers"])
    assert channel["air_status"] == "EAS_OVERRIDE"
    assert channel["posture"] == "EMERGENCY"

    items = fx.list_items(scn["playlist"]["id"], scn["traffic_headers"])
    first = item_by_sequence(items, 1)
    assert first["playout_status"] == "TRUNCATED"
    assert first["measured_duration_seconds"] == 1790
    assert item_by_sequence(items, 2)["playout_status"] == "PREEMPTED"
    assert item_by_sequence(items, 3)["playout_status"] == "PREEMPTED"
    assert item_by_sequence(items, 4)["playout_status"] == "SCHEDULED", (
        "an element straddling the end of the expected span is not preempted"
    )

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["credited_spots"] == 2
    assert order["credit_accrued_cents"] == 200000
    assert_spot_count_conservation(order)

    entries = fx.list_as_run(scn["playlist"]["id"], scn["mco_headers"])
    kinds = as_run_kinds(entries)
    assert kinds.count("TRUNCATION") == 1
    assert kinds.count("PREEMPTION") == 2
    assert kinds.count("OVERRIDE_IN") == 1


def test_the_expiry_cascade_blocks_and_reverts_but_accrues_no_credit(api):
    """Cascade B prime stops one hop short of the spot ledger.

    PRD §2.12: "**Cascade B′** is the same shape but starts at an asset expiring for non-delivery, and it stops one hop short: it blocks elements and reverts playlists but does not itself accrue spot credit."

    Design: Corner/cross_cutting_layers/one_chronological_scenario_touches_all_14_entities_and_every_cascade_edge_in_the_domain
    """
    plant = fx.setup_base_plant()
    opener = fx.setup_qc_passed_asset(plant, 1800)
    closer = fx.setup_qc_passed_asset(plant, 1770)
    never_arrives = fx.create_asset(plant, expected_duration_seconds=30,
                                    delivery_deadline_utc="2026-08-01T10:00:00Z")
    order = fx.create_order(plant)
    playlist = fx.ingest(plant, [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": opener["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1800},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": never_arrives["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T12:30:00Z",
         "scheduled_duration_seconds": 30},
        {"sequence_number": 3, "element_kind": "PROGRAM",
         "asset_id": closer["id"],
         "scheduled_start_utc": "2026-08-01T12:30:30Z",
         "scheduled_duration_seconds": 1770},
    ])
    assert item_by_sequence(
        fx.list_items(playlist["id"], plant["traffic_headers"]), 2
    )["clearance_status"] == "UNCLEARED"
    validated = fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    assert validated["status"] == "VALIDATED"

    fx.set_clock("2026-08-01T11:00:01Z")

    assert fx.read_asset(never_arrives["id"], plant["qc_headers"])["status"] == "EXPIRED"
    item2 = item_by_sequence(fx.list_items(playlist["id"], plant["traffic_headers"]), 2)
    assert item2["clearance_status"] == "BLOCKED"

    after = fx.read_playlist(playlist["id"], plant["traffic_headers"])
    assert after["blocked_item_count"] == 1
    assert after["status"] == "IMPORTED"

    settled = fx.read_order(order["id"], plant["traffic_headers"])
    assert settled["credited_spots"] == 0
    assert settled["credit_accrued_cents"] == 0
    assert settled["scheduled_spots"] == 1
    assert settled["status"] == "OPEN"
    assert_spot_count_conservation(settled)

# ---------------------------------------------------------------------------
# Two uniform envelopes, and a clock that is written and never read
# ---------------------------------------------------------------------------

def test_the_object_envelope_is_identical_on_a_create_and_on_a_read(api):
    """A 201 registration and a 200 read carry the same meta and the same shape.

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/cross_cutting_layers/the_two_envelopes_are_uniform_and_the_logical_clock_has_no_read_endpoint_at_all
    """
    plant = fx.setup_base_plant()

    created_resp = api.create_channel(_third_channel_payload(
        plant, plant["multiplex"]["version"]), plant["eng_headers"])
    created = validate_success(created_resp, 201)
    created_body = created_resp.json()
    assert_envelope_meta(created_body)
    assert created_body["response_type"] == "object"
    assert created_body["data"]["id"] == created["id"]

    read_resp = api.get_channel(created["id"], plant["mco_headers"])
    validate_success(read_resp)
    read_body = read_resp.json()
    assert_envelope_meta(read_body)
    assert read_body["response_type"] == "object"
    assert read_body["data"]["call_sign"] == "WXYZ-DT3"
    assert read_body["meta"]["api_request_id"] != created_body["meta"]["api_request_id"]


def test_the_array_envelope_echoes_the_pagination_window(api):
    """A list read adds four pagination figures and nothing else changes.

    PRD §2.3: "Both appear echoed back in the `meta` object of the response envelope alongside `total_count` (the number of records matching the query before pagination is applied) and `has_more` (true when records remain beyond the current page)."

    Design: Corner/cross_cutting_layers/the_two_envelopes_are_uniform_and_the_logical_clock_has_no_read_endpoint_at_all
    """
    plant = fx.setup_base_plant()

    first_page, meta = validate_paginated(
        api.list_channels(plant["mco_headers"], params={"limit": 1, "offset": 0}))
    assert len(first_page) == 1
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    resp = api.list_channels(plant["mco_headers"], params={"limit": 1, "offset": 1})
    second_page, second_meta = validate_paginated(resp)
    assert len(second_page) == 1
    assert second_meta["offset"] == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert resp.json()["response_type"] == "array"
    assert_envelope_meta(resp.json())
    assert second_page[0]["id"] != first_page[0]["id"]


def test_the_error_envelope_is_uniform_across_two_different_bands(api):
    """A 404 path failure and a 422 enum failure report in exactly one shape.

    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/cross_cutting_layers/the_two_envelopes_are_uniform_and_the_logical_clock_has_no_read_endpoint_at_all
    """
    plant = fx.setup_base_plant()

    missing = api.get_transmitter(NON_EXISTENT_UUID, plant["eng_headers"])
    validate_error(missing, "ERR_TRANSMITTER_NOT_FOUND", expected_status=404)

    bad_enum = api.change_channel_air_state(
        plant["ch1"]["id"], {"target_air_status": "SPARKLING"}, plant["mco_headers"])
    validate_error(bad_enum, "ERR_INVALID_ENUM_VALUE", expected_status=422)

    for resp in (missing, bad_enum):
        body = resp.json()
        assert_envelope_meta(body)
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
        assert body["response_type"] == "error"
        assert set(body["data"].keys()) == {"error_id", "message"}
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]

    unchanged = fx.read_channel(plant["ch1"]["id"], plant["mco_headers"])
    assert unchanged["air_status"] == "DARK"


def test_the_clock_is_only_ever_written_and_observed_through_its_stamps(api):
    """The instant is set, never queried, and only shows up in derived fields.

    PRD §2.4: "A clock advance must move strictly forward: a request whose `current_utc` equals or precedes the present clock value is rejected with `ERR_CLOCK_NOT_MONOTONIC`."

    Design: Corner/cross_cutting_layers/the_two_envelopes_are_uniform_and_the_logical_clock_has_no_read_endpoint_at_all
    """
    plant = fx.setup_base_plant()

    advanced = api.set_clock("2026-08-01T09:30:00Z", plant["eng_headers"])
    validate_success(advanced)
    assert_envelope_meta(advanced.json())

    repeated = api.set_clock("2026-08-01T09:30:00Z", plant["eng_headers"])
    validate_error(repeated, "ERR_CLOCK_NOT_MONOTONIC", expected_status=409)

    backwards = api.set_clock("2026-08-01T09:29:59Z", plant["eng_headers"])
    validate_error(backwards, "ERR_CLOCK_NOT_MONOTONIC", expected_status=409)

    fx.change_power_state(plant, "REDUCED_POWER", power_pct=70)
    filing = fx.list_notifications(plant["transmitter"]["id"],
                                   plant["compliance_headers"])[0]
    assert _instant(filing["triggering_utc"]) == "2026-08-01T09:30:00", (
        "the only reading of the clock is the stamp it leaves behind"
    )

# ---------------------------------------------------------------------------
# One governing-report policy, read by rule after rule
# ---------------------------------------------------------------------------

def _delivered_asset(plant, duration_seconds=1800):
    """An asset in RECEIVED, ready for its first inspection."""
    asset = fx.create_asset(plant, expected_duration_seconds=duration_seconds)
    delivered = fx.deliver_asset(plant, asset["id"],
                                measured_duration_seconds=duration_seconds)
    return delivered


def test_the_newest_ingest_report_supersedes_the_older_one_and_governs(api):
    """The verdict on the asset is the newest report's verdict, not the first's.

    PRD §3.4: "Submitting a report supersedes any earlier report of the same `basis` on that asset by setting the earlier report's `superseded` to true."

    Design: Corner/cross_cutting_layers/the_governing_qc_report_selector_is_one_policy_read_by_six_different_rules
    """
    plant = fx.setup_base_plant()
    delivered = _delivered_asset(plant)

    first = validate_success(api.submit_qc_report(
        delivered["id"], _ingest_report(delivered["version"], plant["qc"]["id"],
                                        ["AUDIO_LOSS"]),
        plant["qc_headers"]), 201)
    assert first["technical_score"] == 75
    assert first["verdict"] == "FAIL"
    assert first["superseded"] is False
    failed = fx.read_asset(delivered["id"], plant["qc_headers"])
    assert failed["status"] == "QC_FAILED"
    assert failed["technical_score_ingest"] == 75
    assert failed["qc_verdict"] == "FAIL"

    redelivered = fx.deliver_asset(plant, delivered["id"],
                                   measured_duration_seconds=1800)
    second = validate_success(api.submit_qc_report(
        redelivered["id"], _ingest_report(redelivered["version"], plant["qc"]["id"], []),
        plant["qc_headers"]), 201)
    assert second["technical_score"] == 100
    assert second["verdict"] == "PASS"

    governed = fx.read_asset(delivered["id"], plant["qc_headers"])
    assert governed["status"] == "QC_PASSED"
    assert governed["technical_score_ingest"] == 100
    assert governed["qc_verdict"] == "PASS"

    assert validate_success(api.get_qc_report(first["id"],
                                             plant["qc_headers"]))["superseded"] is True
    assert validate_success(api.get_qc_report(second["id"],
                                             plant["qc_headers"]))["superseded"] is False


def test_the_waiver_threshold_reads_the_same_governing_score(api):
    """A hopeless score blocks the waiver until a better report governs.

    PRD §3.4: "The governing non-superseded ingest score in `technical_score_ingest` must be at least 40 — **exactly 40 is waivable, 39 is not** — otherwise `ERR_QC_WAIVER_SCORE_TOO_LOW`."

    Design: Corner/cross_cutting_layers/the_governing_qc_report_selector_is_one_policy_read_by_six_different_rules
    """
    plant = fx.setup_base_plant()
    asset = fx.setup_qc_failed_asset(plant, 1800, defect_codes=[
        "AUDIO_LOSS", "CAPTION_MISSING", "FORMAT_MISMATCH", "VIDEO_ARTIFACT"])
    assert asset["technical_score_ingest"] == 30

    refused = api.sign_qc_waiver(
        asset["id"], {"waived_by_operator_id": plant["pd"]["id"],
                      "waiver_justification": _JUSTIFICATION},
        plant["pd_headers"])
    validate_error(refused, "ERR_QC_WAIVER_SCORE_TOO_LOW", expected_status=409)

    redelivered = fx.deliver_asset(plant, asset["id"], measured_duration_seconds=1800)
    validate_success(api.submit_qc_report(
        asset["id"], _ingest_report(redelivered["version"], plant["qc"]["id"],
                                    ["AUDIO_LOSS"]),
        plant["qc_headers"]), 201)
    regraded = fx.read_asset(asset["id"], plant["qc_headers"])
    assert regraded["technical_score_ingest"] == 75
    assert regraded["status"] == "QC_FAILED"

    waived = validate_success(api.sign_qc_waiver(
        asset["id"], {"waived_by_operator_id": plant["pd"]["id"],
                      "waiver_justification": _JUSTIFICATION},
        plant["pd_headers"]))
    assert waived["status"] == "QC_WAIVED"


def test_an_air_check_report_governs_its_own_basis_and_moves_no_status(api):
    """The two bases are selected independently, so the air check is inert.

    PRD §3.4: "its score is written to `technical_score_aircheck` and it never changes the asset's `status`"

    Design: Corner/cross_cutting_layers/the_governing_qc_report_selector_is_one_policy_read_by_six_different_rules
    """
    plant = fx.setup_base_plant()
    asset = fx.setup_qc_passed_asset(plant, 1800)
    assert asset["status"] == "QC_PASSED"
    assert asset["technical_score_ingest"] == 100

    aircheck = validate_success(api.submit_qc_report(
        asset["id"],
        {"expected_asset_version": asset["version"],
         "inspected_by_operator_id": plant["qc"]["id"],
         "basis": "AIR_CHECK",
         "defect_codes": ["CAPTION_MISTIMED"],
         "measured_duration_seconds": 1800},
        plant["qc_headers"]), 201)
    assert aircheck["basis"] == "AIR_CHECK"
    assert aircheck["technical_score"] == 92
    assert aircheck["fault_penalty_points"] == 0
    assert aircheck["superseded"] is False

    after = fx.read_asset(asset["id"], plant["qc_headers"])
    assert after["status"] == "QC_PASSED", "an air check never moves the status"
    assert after["technical_score_aircheck"] == 92
    assert after["technical_score_ingest"] == 100

    reports, meta = validate_paginated(
        api.list_qc_reports(plant["qc_headers"], params={"asset_id": asset["id"]}))
    assert meta["total_count"] == 2
    ingest_report = [r for r in reports if r["basis"] == "INGEST"][0]
    assert ingest_report["superseded"] is False, (
        "a report of the other basis is not superseded"
    )


def test_the_report_list_still_shows_the_superseded_row(api):
    """History is kept: the loser of the selection is listed alongside the winner.

    PRD §3.4: "superseded reports are included in the list unless `include_superseded` is used to exclude them"

    Design: Corner/cross_cutting_layers/the_governing_qc_report_selector_is_one_policy_read_by_six_different_rules
    """
    plant = fx.setup_base_plant()
    delivered = _delivered_asset(plant)
    validate_success(api.submit_qc_report(
        delivered["id"], _ingest_report(delivered["version"], plant["qc"]["id"],
                                        ["AUDIO_LOSS"]),
        plant["qc_headers"]), 201)
    redelivered = fx.deliver_asset(plant, delivered["id"],
                                   measured_duration_seconds=1800)
    validate_success(api.submit_qc_report(
        redelivered["id"], _ingest_report(redelivered["version"], plant["qc"]["id"], []),
        plant["qc_headers"]), 201)

    reports, meta = validate_paginated(
        api.list_qc_reports(plant["qc_headers"], params={"asset_id": delivered["id"]}))
    assert meta["total_count"] == 2
    assert [report["superseded"] for report in reports].count(True) == 1
    assert [report["superseded"] for report in reports].count(False) == 1
    assert {report["technical_score"] for report in reports} == {75, 100}


# ---------------------------------------------------------------------------
# One maximally illegal substitution, peeled one violation at a time
# ---------------------------------------------------------------------------

def _illegal_substitution_body():
    """A substitution body with its one required field left out."""
    return {"reason": "LATE_DELIVERY"}


def test_the_four_authentication_checks_precede_every_other_violation(api):
    """The same unauthenticated call reports its header problem, never its body.

    PRD §2.8: "The ladder is evaluated strictly in ascending order; **the first
    failing check is the whole response and no later check is evaluated**."

    Design: Corner/cross_cutting_layers/one_maximally_illegal_call_pins_the_entire_priority_ladder_from_auth_to_arithmetic
    """
    plant = fx.setup_base_plant()
    body = _illegal_substitution_body()

    validate_error(api.substitute_item(NON_EXISTENT_UUID, body, {}),
                   "ERR_MISSING_AUTH_HEADERS")
    validate_error(
        api.substitute_item(NON_EXISTENT_UUID, body,
                            make_headers("PlayoutRobot", plant["mco"]["id"])),
        "ERR_UNKNOWN_ROLE")
    validate_error(
        api.substitute_item(NON_EXISTENT_UUID, body,
                            make_master_control_headers(NON_EXISTENT_UUID)),
        "ERR_OPERATOR_NOT_FOUND")
    validate_error(
        api.substitute_item(NON_EXISTENT_UUID, body,
                            make_master_control_headers(plant["qc"]["id"])),
        "ERR_ROLE_IDENTITY_MISMATCH")


def test_authorisation_shape_and_the_two_existence_bands_come_next_in_order(api):
    """Peeling the header problem exposes the next violation, one band at a time.

    PRD §2.8: "Concretely, in priority order: header presence (`ERR_MISSING_AUTH_HEADERS`), role recognition (`ERR_UNKNOWN_ROLE`), operator resolution for entity-backed roles (`ERR_OPERATOR_NOT_FOUND`), role-class agreement (`ERR_ROLE_IDENTITY_MISMATCH`), endpoint authorisation (`ERR_ROLE_NOT_PERMITTED`), operator not suspended (`ERR_OPERATOR_SUSPENDED`), operator certification valid (`ERR_OPERATOR_CERTIFICATION_EXPIRED`), required fields present (`ERR_MISSING_REQUIRED_FIELD`), enum literals valid (`ERR_INVALID_ENUM_VALUE`), types and ranges valid (`ERR_INVALID_FIELD_VALUE`), path segments resolve (the per-segment 404 codes of §2.7), body references resolve (the same 404 codes), parent version matches (`ERR_STALE_PLAYLIST_VERSION`, `ERR_STALE_MULTIPLEX_VERSION`, `ERR_STALE_ASSET_VERSION`), then the per-entity state-transition legality checks, then the safety band, the temporal band, the constraint band, the referential band, and the fiscal band."

    Design: Corner/cross_cutting_layers/one_maximally_illegal_call_pins_the_entire_priority_ladder_from_auth_to_arithmetic
    """
    scn = fx.setup_playlist_scenario()
    promo = item_by_sequence(scn["items"], 5)
    replacement = fx.setup_qc_passed_asset(scn, 30)
    body = _illegal_substitution_body()

    # A resolvable QC identity is simply not on this endpoint's role list.
    validate_error(
        api.substitute_item(NON_EXISTENT_UUID, body, make_qc_headers(scn["qc"]["id"])),
        "ERR_ROLE_NOT_PERMITTED")
    # Permitted, so the missing required field surfaces, ahead of both 404s.
    validate_error(api.substitute_item(NON_EXISTENT_UUID, body, scn["mco_headers"]),
                   "ERR_MISSING_REQUIRED_FIELD")
    # Body complete, so the unresolvable path segment surfaces next.
    named = dict(body, replacement_asset_id=replacement["id"])
    validate_error(api.substitute_item(NON_EXISTENT_UUID, named, scn["mco_headers"]),
                   "ERR_PLAYLIST_ITEM_NOT_FOUND")
    # Path resolves, so the unresolvable body reference is last of the four.
    dangling = dict(body, replacement_asset_id=NON_EXISTENT_UUID)
    validate_error(api.substitute_item(promo["id"], dangling, scn["mco_headers"]),
                   "ERR_ASSET_NOT_FOUND")


def test_the_state_precondition_outranks_the_resolution_and_trim_rules(api):
    """A playing element refuses on its status even when the replacement misfits.

    PRD §3.5: "The target element's `playout_status` must be `SCHEDULED` or `CUED`; an element already `PLAYING` or terminal cannot be substituted and the attempt is refused with `ERR_ITEM_INVALID_PLAYOUT_STATE`."

    Design: Corner/cross_cutting_layers/one_maximally_illegal_call_pins_the_entire_priority_ladder_from_auth_to_arithmetic
    """
    scn = fx.setup_playing_item1()
    playing = item_by_sequence(
        fx.list_items(scn["playlist"]["id"], scn["traffic_headers"]), 1)
    assert playing["playout_status"] == "PLAYING"
    # 30 seconds against a 1800-second element is far outside any trim window,
    # yet the state band is evaluated before the structural band.
    misfit = fx.setup_qc_passed_asset(scn, 30)
    validate_error(
        api.substitute_item(playing["id"],
                            {"replacement_asset_id": misfit["id"],
                             "reason": "RIGHTS_PULL"},
                            scn["mco_headers"]),
        "ERR_ITEM_INVALID_PLAYOUT_STATE")


def test_with_every_earlier_violation_cleared_the_structural_rule_speaks_last(api):
    """Only once the call is otherwise clean does the trim window decide it.

    PRD §3.5: "The replacement asset's `delivered_resolution_class` must equal the outgoing element's asset's `required_resolution_class`, and the replacement's `measured_duration_seconds` must lie within the outgoing element's `max_trim_seconds` of the outgoing `scheduled_duration_seconds`; either failure is refused with `ERR_SUBSTITUTE_RESOLUTION_MISMATCH`."

    Design: Corner/cross_cutting_layers/one_maximally_illegal_call_pins_the_entire_priority_ladder_from_auth_to_arithmetic
    """
    scn = fx.setup_playlist_scenario()
    promo = item_by_sequence(scn["items"], 5)
    assert promo["scheduled_duration_seconds"] == 60
    assert promo["max_trim_seconds"] == 30

    # 20 seconds is 40 short of 60, outside the 30-second window.
    too_short = fx.setup_qc_passed_asset(scn, 20)
    validate_error(
        api.substitute_item(promo["id"],
                            {"replacement_asset_id": too_short["id"],
                             "reason": "LATE_DELIVERY"},
                            scn["mco_headers"]),
        "ERR_SUBSTITUTE_RESOLUTION_MISMATCH")

    # 30 seconds is exactly 30 short, and a trim equal to the maximum is legal.
    exact = fx.setup_qc_passed_asset(scn, 30)
    created = assert_playlist_item(validate_success(
        api.substitute_item(promo["id"],
                            {"replacement_asset_id": exact["id"],
                             "reason": "LATE_DELIVERY"},
                            scn["mco_headers"]), 201))
    assert created["replaces_item_id"] == promo["id"]
    assert created["asset_id"] == exact["id"]
    outgoing = assert_playlist_item(
        fx.read_item(promo["id"], scn["traffic_headers"]))
    assert outgoing["playout_status"] == "SKIPPED"
