"""Gates that read through to a different row.

Two entity pairs are exercised here. A playlist element's own automation axis is
gated by the status of the asset it points at, and a transmitter's own power axis
is gated by the lifecycle state and derived severity of a technical fault hanging
off it. In both cases nothing about the gated row changes when the refusal
appears, and in both cases the identical call succeeds once the *other* row moves.
"""
from test_helpers import as_run_kinds, item_by_sequence, validate_error, validate_success
from test_helpers import fixtures as fx

SD_PLANT_MUX = {
    "total_capacity_kbps": 20000,
    "pilot_reserved_kbps": 500,
    "live_encoder_units_total": 2,
}
SD_PLANT_CH1 = {
    "resolution_class": "SD_480I",
    "requested_bitrate_kbps": 6000,
    "floor_bitrate_kbps": 2000,
    "priority_rank": 1,
}


def _sd_plant() -> dict:
    """One FULL_POWER transmitter, MUX-A (20000/500) and one ACTIVE SD channel 12.1."""
    return fx.setup_base_plant(
        with_subchannel=False,
        mux_overrides=dict(SD_PLANT_MUX),
        ch1_overrides=dict(SD_PLANT_CH1),
    )


def _sd_asset(plant: dict, duration_seconds: int) -> dict:
    """A QC_PASSED SD_480I asset scoring a clean 100."""
    return fx.setup_qc_passed_asset(
        plant,
        duration_seconds,
        asset_overrides={"required_resolution_class": "SD_480I"},
    )


def _two_program_day_on_air() -> dict:
    """The SD plant plus a two-element broadcast day driven all the way to air.

    Window 1800 s and two booked 900 s programmes give a projected end variance of
    exactly 0, so the day validates and arms; the channel is then lit and the
    playlist taken to air with the logical clock at the booked start.
    """
    plant = _sd_plant()
    plant["asset_a"] = _sd_asset(plant, 900)
    plant["asset_b"] = _sd_asset(plant, 900)
    plant["playlist"] = fx.ingest(
        plant,
        [
            {"sequence_number": 1, "element_kind": "PROGRAM",
             "asset_id": plant["asset_a"]["id"],
             "scheduled_start_utc": "2026-08-01T12:00:00Z",
             "scheduled_duration_seconds": 900, "max_trim_seconds": 0},
            {"sequence_number": 2, "element_kind": "PROGRAM",
             "asset_id": plant["asset_b"]["id"],
             "scheduled_start_utc": "2026-08-01T12:15:00Z",
             "scheduled_duration_seconds": 900, "max_trim_seconds": 0},
        ],
        window_duration_seconds=1800,
    )
    plant["items"] = fx.list_items(plant["playlist"]["id"], plant["traffic_headers"])
    fx.drive_playlist(plant, plant["playlist"]["id"], "VALIDATED")
    fx.drive_playlist(plant, plant["playlist"]["id"], "ARMED")
    fx.set_clock("2026-08-01T12:00:00Z")
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    fx.drive_playlist(plant, plant["playlist"]["id"], "ON_AIR")
    return plant


def test_cue_is_refused_when_the_referenced_asset_has_been_retracted(api):
    """The element's own automation axis is blocked by the status of the asset row it points at.

    PRD §3.6: "for elements whose `element_kind` is `PROGRAM`, `COMMERCIAL`, `INTERSTITIAL` or `PROMO` the `clearance_status` must be `CLEARED`, otherwise `ERR_UNCLEARED_CONTENT_ON_AIR`, a dependency that reads from the element through to its asset"

    PRD §3.4: "every playlist item referencing the asset whose `playout_status` is `SCHEDULED` or `CUED` has its `clearance_status` flipped to `BLOCKED`"

    Design: Difficulty/cross_entity_state_dependency/cue_refused_because_the_referenced_asset_was_retracted
    """
    plant = _two_program_day_on_air()
    item2 = item_by_sequence(plant["items"], 2)
    fx.retract(plant, plant["asset_b"]["id"], reason="rights window withdrawn")

    resp = api.post_playout_event(
        item2["id"],
        {"event_kind": "CUE", "event_utc": "2026-08-01T12:00:00Z"},
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_UNCLEARED_CONTENT_ON_AIR")

    refused = fx.read_item(item2["id"], plant["mco_headers"])
    assert refused["playout_status"] == "SCHEDULED"
    assert refused["clearance_status"] == "BLOCKED"
    assert fx.read_asset(plant["asset_b"]["id"], plant["pd_headers"])["status"] == "RETRACTED"
    assert fx.read_playlist(plant["playlist"]["id"])["blocked_item_count"] == 1
    assert "CUE" not in as_run_kinds(fx.list_as_run(plant["playlist"]["id"]))


def test_sibling_element_whose_asset_is_still_passed_cues_successfully(api):
    """Nothing about the element's own axis is at fault: the cleared sibling cues on the same day.

    PRD §3.6: "**Cueing** an element requires four things: the owning playlist's `status` must be `ON_AIR`, otherwise `ERR_PLAYLIST_NOT_ON_AIR`; for elements whose `element_kind` is `PROGRAM`, `COMMERCIAL`, `INTERSTITIAL` or `PROMO` the `clearance_status` must be `CLEARED`"

    Design: Difficulty/cross_entity_state_dependency/cue_refused_because_the_referenced_asset_was_retracted
    """
    plant = _two_program_day_on_air()
    item1 = item_by_sequence(plant["items"], 1)
    item2 = item_by_sequence(plant["items"], 2)
    fx.retract(plant, plant["asset_b"]["id"], reason="rights window withdrawn")

    resp = api.post_playout_event(
        item1["id"],
        {"event_kind": "CUE", "event_utc": "2026-08-01T12:00:00Z"},
        plant["mco_headers"],
    )
    validate_success(resp, 201)

    assert fx.read_item(item1["id"], plant["mco_headers"])["playout_status"] == "CUED"
    assert fx.read_item(item1["id"], plant["mco_headers"])["clearance_status"] == "CLEARED"
    assert fx.read_item(item2["id"], plant["mco_headers"])["playout_status"] == "SCHEDULED"
    assert as_run_kinds(fx.list_as_run(plant["playlist"]["id"])) == ["CUE"]


def test_cue_succeeds_after_substituting_a_passed_replacement_asset(api):
    """Moving the asset side — a fresh element against a QC_PASSED file — makes the identical cue legal.

    PRD §3.6: "A successful substitution moves the outgoing element to `SKIPPED` with an as-run skip entry, creates a new element that records the outgoing element's identifier in its `replaces_item_id`, derives the new element's `clearance_status` from the replacement asset's status"

    Design: Difficulty/cross_entity_state_dependency/cue_refused_because_the_referenced_asset_was_retracted
    """
    plant = _two_program_day_on_air()
    item2 = item_by_sequence(plant["items"], 2)
    replacement = _sd_asset(plant, 900)
    fx.retract(plant, plant["asset_b"]["id"], reason="rights window withdrawn")

    refused = api.post_playout_event(
        item2["id"],
        {"event_kind": "CUE", "event_utc": "2026-08-01T12:00:00Z"},
        plant["mco_headers"],
    )
    validate_error(refused, "ERR_UNCLEARED_CONTENT_ON_AIR")

    fx.substitute(plant, item2["id"], replacement["id"],
                  scheduled_duration_seconds=900, reason="retraction cover")
    successors = validate_success(
        api.list_all_playlist_items(plant["mco_headers"],
                                    params={"replaces_item_id": item2["id"]})
    )
    assert len(successors) == 1, "the substitution creates exactly one replacement element"
    successor = successors[0]
    assert successor["clearance_status"] == "CLEARED"
    assert fx.read_item(item2["id"], plant["mco_headers"])["playout_status"] == "SKIPPED"

    accepted = api.post_playout_event(
        successor["id"],
        {"event_kind": "CUE", "event_utc": "2026-08-01T12:00:00Z"},
        plant["mco_headers"],
    )
    validate_success(accepted, 201)
    assert fx.read_item(successor["id"], plant["mco_headers"])["playout_status"] == "CUED"


def _reduced_power_with_escalated_rf_fault() -> dict:
    """Reduce the plant to 90 percent, then escalate an RF_POWER_FAULT to CRITICAL.

    Detection at 12:00:00Z and escalation at 12:02:00Z put the fault's dwell at
    exactly the 120-second escalation threshold, and escalation raises MAJOR one
    step to CRITICAL.
    """
    plant = _sd_plant()
    fx.set_clock("2026-08-01T12:00:00Z")
    fx.change_power_state(plant, "REDUCED_POWER", power_pct=90,
                          reason="antenna maintenance")
    fault = fx.report_transmitter_fault(
        plant, "RF_POWER_FAULT", "MAJOR", "2026-08-01T12:00:00Z",
        headers=plant["eng_headers"], notes="forward power sag on the main line",
    )
    fx.set_clock("2026-08-01T12:00:30Z")
    fx.advance_fault(plant, fault["id"], "ACKNOWLEDGED",
                     headers=plant["eng_headers"],
                     notes="engineer on the line with the site")
    fx.set_clock("2026-08-01T12:02:00Z")
    plant["fault"] = fx.advance_fault(plant, fault["id"], "ESCALATED",
                                      headers=plant["eng_headers"],
                                      notes="no recovery after acknowledgement")
    return plant


def test_full_power_restore_is_refused_while_an_escalated_rf_fault_is_open(api):
    """The transmitter's own power axis is gated by the lifecycle state of a child fault row.

    PRD §3.1: "A restoration to `FULL_POWER`, from either `REDUCED_POWER` or `OFF_AIR`, is refused with `ERR_RF_FAULT_BLOCKS_RESTORE` while any technical fault on that transmitter has `fault_code` `RF_POWER_FAULT` and a `state` of `DETECTED`, `ACKNOWLEDGED` or `ESCALATED`."

    Design: Difficulty/cross_entity_state_dependency/full_power_restore_refused_while_an_escalated_rf_fault_is_open
    """
    plant = _reduced_power_with_escalated_rf_fault()
    before = fx.read_transmitter(plant["transmitter"]["id"], plant["eng_headers"])

    resp = api.change_transmitter_power_state(
        plant["transmitter"]["id"],
        {"target_state": "FULL_POWER", "reason": "maintenance complete"},
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_RF_FAULT_BLOCKS_RESTORE")

    fault = fx.read_fault(plant["fault"]["id"], plant["eng_headers"])
    assert fault["state"] == "ESCALATED"
    assert fault["severity"] == "CRITICAL"

    after = fx.read_transmitter(plant["transmitter"]["id"], plant["eng_headers"])
    assert after["operational_state"] == "REDUCED_POWER"
    assert after["current_power_pct"] == 90
    assert after["version"] == before["version"], "a refused call performs no write"
    assert float(after["derate_factor"]) == 0.75
    mux = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert mux["effective_capacity_kbps"] == 14500


def test_full_power_restore_succeeds_once_the_rf_fault_reaches_resolved(api):
    """A RESOLVED fault is outside the blocking set, so the identical restore is legal.

    PRD §3.1: "A clean restoration writes `current_power_pct` to 100 and `derate_factor` to 1.00 and re-runs the bitrate waterfall across every child multiplex"

    Design: Difficulty/cross_entity_state_dependency/full_power_restore_refused_while_an_escalated_rf_fault_is_open
    """
    plant = _reduced_power_with_escalated_rf_fault()
    fx.advance_fault(plant, plant["fault"]["id"], "MITIGATED",
                     headers=plant["eng_headers"], mitigation_code="SWITCH_TO_BACKUP")
    fx.set_clock("2026-08-01T12:03:00Z")
    resolved = fx.advance_fault(plant, plant["fault"]["id"], "RESOLVED",
                                headers=plant["eng_headers"],
                                cleared_utc="2026-08-01T12:03:00Z")
    assert resolved["state"] == "RESOLVED"

    resp = api.change_transmitter_power_state(
        plant["transmitter"]["id"],
        {"target_state": "FULL_POWER", "reason": "maintenance complete"},
        plant["eng_headers"],
    )
    restored = validate_success(resp)
    assert restored["operational_state"] == "FULL_POWER"
    assert restored["current_power_pct"] == 100
    assert float(restored["derate_factor"]) == 1.00
    mux = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert mux["effective_capacity_kbps"] == 19500
