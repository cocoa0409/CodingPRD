"""Dual-variant computations that disagree over one unchanged set of stored rows.

Three domains, three units: playlist timing variance in seconds (§3.5), asset
technical scoring in points (§3.4) and multiplex bitrate allocation in kilobits
per second (§3.2). Each domain publishes two figures over the same stored data,
and each pair is asserted separately and then asserted to diverge.
"""
from test_helpers import validate_success
from test_helpers import fixtures as fx

# ---------------------------------------------------------------------------
# Private setup helpers. Each builds its preconditions from an empty database
# through PRD endpoints only, starting from the default logical clock.
# ---------------------------------------------------------------------------

_SD_ASSET_KWARGS = {
    "asset_overrides": {
        "required_resolution_class": "SD_480I",
        "delivery_deadline_utc": "2026-08-05T00:00:00Z",
    },
    "delivery_overrides": {"received_utc": "2026-08-01T10:00:00Z"},
}


def _sd_station() -> dict:
    """One FULL_POWER transmitter carrying MUX-A (20000 kbps, 500 pilot) and 12.1.

    Channel 12.1 is SD_480I with floor 2000 and request 6000 at priority rank 1,
    so the 19500 kbps pool grants it 6000 kbps and it can be lit.
    """
    return fx.setup_base_plant(
        with_subchannel=False,
        clock_utc="2026-08-01T10:00:00Z",
        mux_overrides={"total_capacity_kbps": 20000, "pilot_reserved_kbps": 500},
        ch1_overrides={
            "resolution_class": "SD_480I",
            "requested_bitrate_kbps": 6000,
            "floor_bitrate_kbps": 2000,
            "priority_rank": 1,
        },
    )


def _station_with_1800_second_day() -> dict:
    """The 1800-second broadcast day on air with element one playing.

    Four contiguous elements — PROGRAM 1200, COMMERCIAL 30, COMMERCIAL 30,
    PROGRAM 540 — sum to exactly the 1800-second window. Element one is CUED,
    STARTed at 12:00:00Z and the clock then stands at 12:19:30Z, thirty seconds
    before the booked end of that element.
    """
    scn = _sd_station()
    asset_a = fx.setup_qc_passed_asset(scn, 1200, **_SD_ASSET_KWARGS)
    asset_b = fx.setup_qc_passed_asset(scn, 30, **_SD_ASSET_KWARGS)
    asset_c = fx.setup_qc_passed_asset(scn, 540, **_SD_ASSET_KWARGS)
    order = fx.create_order(
        scn,
        advertiser_name="Acme",
        ordered_spots=2,
        unit_duration_seconds=30,
        rate_cents_total=1000,
        daypart="DAYTIME",
        priority_class="PREEMPTIBLE",
        makegood_deadline_utc="2026-08-10T00:00:00Z",
    )
    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": asset_a["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1200, "max_trim_seconds": 0},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": asset_b["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T12:20:00Z",
         "scheduled_duration_seconds": 30, "max_trim_seconds": 0},
        {"sequence_number": 3, "element_kind": "COMMERCIAL",
         "asset_id": asset_b["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T12:20:30Z",
         "scheduled_duration_seconds": 30, "max_trim_seconds": 0},
        {"sequence_number": 4, "element_kind": "PROGRAM",
         "asset_id": asset_c["id"],
         "scheduled_start_utc": "2026-08-01T12:21:00Z",
         "scheduled_duration_seconds": 540, "max_trim_seconds": 0},
    ]
    playlist = fx.ingest(scn, items, window_duration_seconds=1800)
    persisted = fx.list_items(playlist["id"], scn["mco_headers"])
    mco = scn["mco_headers"]
    fx.drive_playlist(scn, playlist["id"], "VALIDATED", headers=mco)
    fx.drive_playlist(scn, playlist["id"], "ARMED", headers=mco)
    fx.set_clock("2026-08-01T12:00:00Z")
    fx.set_air_status(scn, scn["ch1"]["id"], "ON_AIR")
    scn["playlist"] = fx.drive_playlist(scn, playlist["id"], "ON_AIR", headers=mco)
    scn["items"] = persisted
    scn["item1"] = persisted[0]
    fx.cue_item(scn, persisted[0]["id"], "2026-08-01T12:00:00Z")
    fx.start_item(scn, persisted[0]["id"], "2026-08-01T12:00:00Z")
    fx.set_clock("2026-08-01T12:19:30Z")
    return scn


def _end_item_one_short(api, scn):
    """Report the END event that closes element one thirty seconds short."""
    return api.post_playout_event(
        scn["item1"]["id"],
        {
            "event_kind": "END",
            "event_utc": "2026-08-01T12:19:30Z",
            "measured_duration_seconds": 1170,
        },
        scn["mco_headers"],
    )


# ===========================================================================
# Playlist timing variance in seconds
# ===========================================================================

def test_projected_variance_still_counts_the_full_booked_length(api):
    """Projected variance trusts the booked schedule even after an element aired short.

    PRD §3.5: "`projected_end_variance_seconds` is the forward-looking figure:
    sum `scheduled_duration_seconds` over every item of the playlist whose
    `playout_status` is not `SKIPPED` and not `PREEMPTED`, then subtract
    `window_duration_seconds`." It "trusts the booked schedule for everything
    that has not been dropped, including items that already aired short."

    Design: Difficulty/dual_variant_calc/playlist_projected_vs_asrun_variance_diverge_on_short_air
    """
    scn = _station_with_1800_second_day()

    entry = validate_success(_end_item_one_short(api, scn), 201)
    assert entry["event_kind"] == "END"
    assert entry["measured_duration_seconds"] == 1170

    item = validate_success(api.get_playlist_item(scn["item1"]["id"], scn["mco_headers"]))
    assert item["playout_status"] == "PLAYED"
    assert item["measured_duration_seconds"] == 1170

    playlist = validate_success(api.get_playlist(scn["playlist"]["id"], scn["mco_headers"]))
    assert playlist["status"] == "ON_AIR"
    assert playlist["scheduled_total_seconds"] == 1800
    assert playlist["projected_end_variance_seconds"] == 0


def test_asrun_variance_records_the_thirty_seconds_that_never_aired(api):
    """As-run variance accumulates the measured length of the element that aired.

    PRD §3.5: "`asrun_end_variance_seconds` is the chronological figure: walk the
    items in `sequence_number` ascending order accumulating, for each, its
    `measured_duration_seconds` when its `playout_status` is `PLAYED` or
    `TRUNCATED`, zero when its `playout_status` is `SKIPPED` or `PREEMPTED`, and
    its `scheduled_duration_seconds` in every other case; then subtract
    `window_duration_seconds`."

    Design: Difficulty/dual_variant_calc/playlist_projected_vs_asrun_variance_diverge_on_short_air
    """
    scn = _station_with_1800_second_day()

    validate_success(_end_item_one_short(api, scn), 201)

    playlist = validate_success(api.get_playlist(scn["playlist"]["id"], scn["mco_headers"]))
    assert playlist["asrun_end_variance_seconds"] == -30


def test_the_two_playlist_variance_figures_disagree_over_identical_stored_data(api):
    """The projected and as-run figures of one playlist differ by the short air.

    PRD §3.5: the two variance figures "deliberately disagree for identical
    stored data whenever any item's `measured_duration_seconds` differs from its
    `scheduled_duration_seconds`".

    Design: Difficulty/dual_variant_calc/playlist_projected_vs_asrun_variance_diverge_on_short_air
    """
    scn = _station_with_1800_second_day()

    validate_success(_end_item_one_short(api, scn), 201)

    playlist = validate_success(api.get_playlist(scn["playlist"]["id"], scn["mco_headers"]))
    assert playlist["projected_end_variance_seconds"] == 0
    assert playlist["asrun_end_variance_seconds"] == -30
    assert (
        playlist["projected_end_variance_seconds"]
        != playlist["asrun_end_variance_seconds"]
    )


# ===========================================================================
# Asset technical score in points
# ===========================================================================

def _station_with_aired_and_faulted_asset() -> dict:
    """One asset graded on ingest, aired short, and carrying one resolved fault.

    Asset A is expected to run 1200 seconds and arrives measuring exactly 1200 at
    -24.0 LKFS, so its INGEST report carrying only `VIDEO_ARTIFACT` pays the
    10-point defect penalty alone. The single-element day then airs it for 1170
    seconds and a `BLACK_FRAME` fault raised against that element is driven all
    the way to `RESOLVED`.
    """
    scn = _sd_station()
    asset = fx.create_asset(
        scn,
        title="Feature A",
        expected_duration_seconds=1200,
        delivery_deadline_utc="2026-08-05T00:00:00Z",
        required_resolution_class="SD_480I",
        captions_required=False,
    )
    delivered = fx.deliver_asset(
        scn, asset["id"],
        received_utc="2026-08-01T10:00:00Z",
        measured_duration_seconds=1200,
        delivered_resolution_class="SD_480I",
        audio_loudness_lkfs=-24.0,
        caption_present=False,
    )
    scn["asset"] = asset
    scn["ingest_report"] = fx.submit_qc(
        scn, asset["id"], delivered["version"],
        basis="INGEST",
        defect_codes=["VIDEO_ARTIFACT"],
        measured_duration_seconds=1200,
    )

    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": asset["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1200, "max_trim_seconds": 0},
    ]
    playlist = fx.ingest(scn, items, window_duration_seconds=1200)
    persisted = fx.list_items(playlist["id"], scn["mco_headers"])
    mco = scn["mco_headers"]
    fx.drive_playlist(scn, playlist["id"], "VALIDATED", headers=mco)
    fx.drive_playlist(scn, playlist["id"], "ARMED", headers=mco)
    fx.set_clock("2026-08-01T12:00:00Z")
    fx.set_air_status(scn, scn["ch1"]["id"], "ON_AIR")
    scn["playlist"] = fx.drive_playlist(scn, playlist["id"], "ON_AIR", headers=mco)
    scn["item1"] = persisted[0]

    fx.cue_item(scn, scn["item1"]["id"], "2026-08-01T12:00:00Z")
    fx.start_item(scn, scn["item1"]["id"], "2026-08-01T12:00:00Z")
    fx.set_clock("2026-08-01T12:19:30Z")
    fx.end_item(scn, scn["item1"]["id"], "2026-08-01T12:19:30Z", 1170)

    fault = fx.report_fault(
        scn, "BLACK_FRAME", "MAJOR", "2026-08-01T12:19:30Z",
        channel_id=scn["ch1"]["id"], playlist_item_id=scn["item1"]["id"],
    )
    fx.advance_fault(scn, fault["id"], "ACKNOWLEDGED")
    fx.advance_fault(scn, fault["id"], "MITIGATED", mitigation_code="RESTART_ENCODER")
    fx.set_clock("2026-08-01T12:20:00Z")
    fx.advance_fault(scn, fault["id"], "RESOLVED", cleared_utc="2026-08-01T12:20:00Z")
    scn["fault"] = fault
    return scn


def _submit_air_check_report(api, scn, asset_version):
    """Grade the same asset again on the air-check basis against the aired length."""
    return api.submit_qc_report(
        scn["asset"]["id"],
        {
            "expected_asset_version": asset_version,
            "inspected_by_operator_id": scn["qc"]["id"],
            "basis": "AIR_CHECK",
            "defect_codes": ["VIDEO_ARTIFACT"],
            "measured_duration_seconds": 1170,
        },
        scn["qc_headers"],
    )


def test_ingest_report_forces_the_fault_penalty_to_zero_and_scores_ninety(api):
    """The ingest variant pays only the defect penalty and passes the asset.

    PRD §3.4: "The *fault penalty* exists only for air-check reports and is forced
    to zero for ingest reports." And: "An ingest report forces the fault penalty
    to zero, uses the ingest measurement, and its score — written to
    `technical_score_ingest` — is the one that decides whether the asset moves
    from `RECEIVED` to `QC_PASSED` or to `QC_FAILED`."

    Design: Difficulty/dual_variant_calc/asset_ingest_vs_aircheck_score_diverge_by_fault_penalty
    """
    scn = _station_with_aired_and_faulted_asset()

    report = validate_success(
        api.get_qc_report(scn["ingest_report"]["id"], scn["qc_headers"])
    )
    assert report["basis"] == "INGEST"
    assert report["defect_penalty_points"] == 10
    assert report["duration_penalty_points"] == 0
    assert report["loudness_penalty_points"] == 0
    assert report["fault_penalty_points"] == 0
    assert report["technical_score"] == 90
    assert report["verdict"] == "PASS"

    asset = validate_success(api.get_asset(scn["asset"]["id"], scn["qc_headers"]))
    assert asset["technical_score_ingest"] == 90
    assert asset["status"] == "QC_PASSED"


def test_air_check_report_adds_the_capped_fault_penalty_and_scores_forty_two(api):
    """The air-check variant pays the resolved fault and the shortened air.

    PRD §3.4: "An air-check report adds the capped fault penalty and uses the
    post-air measurement, so the same asset with the same defect list scores
    strictly lower on air-check than on ingest whenever at least one resolved
    fault is linked to an aired element; its score is written to
    `technical_score_aircheck` and it never changes the asset's `status`." The
    per-fault-code values are "18 for `BLACK_FRAME`" and "any discrepancy of 20
    seconds or more costs the capped 30".

    Design: Difficulty/dual_variant_calc/asset_ingest_vs_aircheck_score_diverge_by_fault_penalty
    """
    scn = _station_with_aired_and_faulted_asset()
    before = validate_success(api.get_asset(scn["asset"]["id"], scn["qc_headers"]))

    report = validate_success(_submit_air_check_report(api, scn, before["version"]), 201)
    assert report["basis"] == "AIR_CHECK"
    assert report["defect_penalty_points"] == 10
    assert report["duration_penalty_points"] == 30
    assert report["loudness_penalty_points"] == 0
    assert report["fault_penalty_points"] == 18
    assert report["technical_score"] == 42
    assert report["verdict"] == "FAIL"

    asset = validate_success(api.get_asset(scn["asset"]["id"], scn["qc_headers"]))
    assert asset["technical_score_aircheck"] == 42
    assert asset["status"] == "QC_PASSED"


def test_the_two_technical_scores_of_one_asset_diverge_by_the_fault_penalty(api):
    """Ingest 90 and air-check 42 stand side by side on the same asset.

    PRD §3.4: "the same asset with the same defect list scores strictly lower on
    air-check than on ingest whenever at least one resolved fault is linked to an
    aired element". And: "Submitting a report supersedes any earlier report of the
    same `basis` on that asset by setting the earlier report's `superseded` to
    true."

    Design: Difficulty/dual_variant_calc/asset_ingest_vs_aircheck_score_diverge_by_fault_penalty
    """
    scn = _station_with_aired_and_faulted_asset()
    before = validate_success(api.get_asset(scn["asset"]["id"], scn["qc_headers"]))
    assert before["technical_score_ingest"] == 90

    validate_success(_submit_air_check_report(api, scn, before["version"]), 201)

    asset = validate_success(api.get_asset(scn["asset"]["id"], scn["qc_headers"]))
    assert asset["technical_score_ingest"] == 90
    assert asset["technical_score_aircheck"] == 42
    assert asset["technical_score_ingest"] != asset["technical_score_aircheck"]

    ingest_report = validate_success(
        api.get_qc_report(scn["ingest_report"]["id"], scn["qc_headers"])
    )
    assert ingest_report["superseded"] is False


# ===========================================================================
# Multiplex bitrate allocation in kilobits per second
# ===========================================================================

def _three_channel_multiplex() -> dict:
    """MUX-A carrying 12.1, 12.2 and 12.3 with unchanging demands.

    Floors 2000 + 3000 + 5000 sum to 10000 and the requests 6000 + 9000 + 12000
    give weights of 4000, 6000 and 7000 for a total weight of 17000. Only the
    transmitter's `derate_factor` ever changes across the two variants.
    """
    scn = _sd_station()
    eng = scn["eng_headers"]
    mux = fx.read_multiplex(scn["multiplex"]["id"], eng)
    scn["ch2"] = fx.create_subchannel(
        eng, mux["id"], mux["version"], scn["ch1"]["id"],
        call_sign="WXYZ-DT2", channel_number="12.2", resolution_class="SD_480I",
        requested_bitrate_kbps=9000, floor_bitrate_kbps=3000, priority_rank=2,
    )
    mux = fx.read_multiplex(scn["multiplex"]["id"], eng)
    scn["ch3"] = fx.create_subchannel(
        eng, mux["id"], mux["version"], scn["ch1"]["id"],
        call_sign="WXYZ-DT3", channel_number="12.3", resolution_class="HD_720P",
        requested_bitrate_kbps=12000, floor_bitrate_kbps=5000, priority_rank=3,
    )
    return scn


def _reduce_power_to_sixty_percent(api, scn):
    """Take the transmitter to REDUCED_POWER at 60 percent of licensed power."""
    return api.change_transmitter_power_state(
        scn["transmitter"]["id"],
        {"target_state": "REDUCED_POWER", "power_pct": 60,
         "reason": "antenna maintenance"},
        scn["eng_headers"],
    )


def _allocations(api, scn):
    """The three channels' allocated bitrates in priority-rank order."""
    eng = scn["eng_headers"]
    return [
        validate_success(api.get_channel(scn[key]["id"], eng))["allocated_bitrate_kbps"]
        for key in ("ch1", "ch2", "ch3")
    ]


def test_full_pool_waterfall_grants_4236_6353_and_8911_kbps(api):
    """At derate 1.00 the 19500 kbps pool is sliced by weight and swept to the kilobit.

    PRD §3.2: "each granted channel's share is the smaller of two figures: the
    remainder multiplied by that channel's weight and divided by the total weight
    with the quotient truncated downward, and the channel's own weight. Each
    granted channel's `allocated_bitrate_kbps` is then its `floor_bitrate_kbps`
    plus its share." The leftover is then swept up: "the granted channels whose
    `allocated_bitrate_kbps` is still strictly below their
    `requested_bitrate_kbps` are gathered in the same deterministic order —
    `priority_rank` ascending, then `created_at` ascending — and each in turn
    receives one additional kilobit".

    Design: Difficulty/dual_variant_calc/multiplex_full_pool_vs_derated_pool_allocations_diverge
    """
    scn = _three_channel_multiplex()
    eng = scn["eng_headers"]

    mux = validate_success(api.get_multiplex(scn["multiplex"]["id"], eng))
    assert mux["effective_capacity_kbps"] == 19500

    assert _allocations(api, scn) == [4236, 6353, 8911]
    assert mux["assigned_kbps"] == 19500
    assert mux["available_kbps"] == 0
    assert mux["starved_channel_count"] == 0


def test_derated_pool_waterfall_grants_3059_4589_and_6852_kbps(api):
    """At derate 0.75 the 14500 kbps pool re-slices every channel downward.

    PRD §3.1: reducing power "publishes a new `derate_factor`, which is 0.75 when
    `power_pct` is at least 50 and 0.50 when it is below 50." PRD §3.2: "take
    `total_capacity_kbps`, multiply by the parent transmitter's current
    `derate_factor`, truncate the product downward to a whole kilobit, subtract
    `pilot_reserved_kbps`, and floor the result at 0."

    Design: Difficulty/dual_variant_calc/multiplex_full_pool_vs_derated_pool_allocations_diverge
    """
    scn = _three_channel_multiplex()
    eng = scn["eng_headers"]

    transmitter = validate_success(_reduce_power_to_sixty_percent(api, scn))
    assert transmitter["operational_state"] == "REDUCED_POWER"
    assert float(transmitter["current_power_pct"]) == 60
    assert float(transmitter["derate_factor"]) == 0.75

    mux = validate_success(api.get_multiplex(scn["multiplex"]["id"], eng))
    assert mux["effective_capacity_kbps"] == 14500
    assert _allocations(api, scn) == [3059, 4589, 6852]
    assert mux["assigned_kbps"] == 14500
    assert mux["available_kbps"] == 0
    assert mux["starved_channel_count"] == 0
    for key in ("ch1", "ch2", "ch3"):
        channel = validate_success(api.get_channel(scn[key]["id"], eng))
        assert channel["allocation_state"] == "ACTIVE"


def test_derate_changes_every_allocation_though_no_channel_changed_its_request(api):
    """The full pool and the derated pool answer differently for identical demands.

    PRD §3.2: "The station therefore has two structurally different pools: a full
    pool, where the whole nominal capacity less pilot reservation is available,
    and a derated pool, where the shrunken capacity starves the tail of the
    priority order even though no channel changed its own request."

    Design: Difficulty/dual_variant_calc/multiplex_full_pool_vs_derated_pool_allocations_diverge
    """
    scn = _three_channel_multiplex()
    eng = scn["eng_headers"]

    full_pool = _allocations(api, scn)
    assert full_pool == [4236, 6353, 8911]

    validate_success(_reduce_power_to_sixty_percent(api, scn))

    derated_pool = _allocations(api, scn)
    assert derated_pool == [3059, 4589, 6852]
    for before, after in zip(full_pool, derated_pool):
        assert before != after

    for key, requested, floor in (
        ("ch1", 6000, 2000), ("ch2", 9000, 3000), ("ch3", 12000, 5000),
    ):
        channel = validate_success(api.get_channel(scn[key]["id"], eng))
        assert channel["requested_bitrate_kbps"] == requested
        assert channel["floor_bitrate_kbps"] == floor
