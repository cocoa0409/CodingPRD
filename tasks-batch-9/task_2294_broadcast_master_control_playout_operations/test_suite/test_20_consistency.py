"""The consistency model: immediate derivation and all-or-nothing writes.

Nothing in this domain is eventual. A write that computes a figure returns that
figure, a write whose consequences land on other records leaves them already
consistent for the very next read, and a write that is refused leaves the
database exactly as it found it — counters, ledgers, logs and versions alike.
"""
from test_helpers import (
    as_run_kinds,
    assert_asset,
    assert_bandwidth_conservation,
    assert_channel,
    assert_multiplex,
    assert_playlist,
    assert_playlist_item,
    assert_qc_report,
    assert_regulatory_notification,
    assert_transmitter,
    item_by_sequence,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

# ---------------------------------------------------------------------------
# Private setup helpers (test_helpers is read-only, so these live here)
# ---------------------------------------------------------------------------


def _plant_with_received_promo():
    """Base plant plus one 60-second asset delivered and awaiting inspection."""
    plant = fx.setup_base_plant()
    asset = fx.create_asset(plant, expected_duration_seconds=60)
    plant["promo"] = fx.deliver_asset(plant, asset["id"],
                                      measured_duration_seconds=60)
    return plant


def _one_element_playlist(plant, asset_id):
    """A single 1800-second programme element booked at the day's start."""
    return fx.ingest(
        plant,
        [{"sequence_number": 1, "element_kind": "PROGRAM",
          "asset_id": asset_id,
          "scheduled_start_utc": "2026-08-01T12:00:00Z",
          "scheduled_duration_seconds": 1800}],
    )


# ---------------------------------------------------------------------------
# Derived fields are already present in the response that caused them
# ---------------------------------------------------------------------------

def test_the_qc_response_already_carries_the_score_and_verdict_it_computed(api):
    """The inspection result is in the 201 body, not one read later.

    PRD §3.4: "The verdict is `FAIL` if the score is below 70, **or** if any of the report's distinct defect codes is `AUDIO_LOSS` or `FORMAT_MISMATCH`, which are the non-negotiable defects, **or** if the asset's `captions_required` is true while its `caption_present` is false, **or** if the asset's `delivered_resolution_class` differs from its `required_resolution_class`."

    Design: Corner/consistency_model/every_derived_field_is_immediate_and_visible_in_the_causing_response_itself
    """
    plant = _plant_with_received_promo()
    promo = plant["promo"]

    report = assert_qc_report(validate_success(api.submit_qc_report(
        promo["id"],
        {"expected_asset_version": promo["version"],
         "inspected_by_operator_id": plant["qc"]["id"],
         "basis": "INGEST",
         "defect_codes": ["AUDIO_LOSS", "FORMAT_MISMATCH"],
         "measured_duration_seconds": 60},
        plant["qc_headers"],
    ), 201))

    # 100 less the 25 and 15 point defects, with no duration, loudness or
    # fault penalty: the caller reads the arithmetic off the create response.
    assert report["defect_penalty_points"] == 40
    assert report["duration_penalty_points"] == 0
    assert report["loudness_penalty_points"] == 0
    assert report["fault_penalty_points"] == 0
    assert report["technical_score"] == 60
    assert report["verdict"] == "FAIL"
    assert report["superseded"] is False


def test_the_retraction_response_is_followed_by_an_already_settled_playlist(api):
    """The three cascade hops are complete before the caller reads anything.

    PRD §2.12: "By the time a response is returned, every derived counter, every dependent state and every ledger figure the operation touched is already consistent — there is no eventual reconciliation and no deferred job."

    Design: Corner/consistency_model/every_derived_field_is_immediate_and_visible_in_the_causing_response_itself
    """
    scn = fx.setup_playlist_scenario()
    fx.validate_playlist(scn)
    tail = item_by_sequence(scn["items"], 7)

    retracted = assert_asset(validate_success(api.retract_asset(
        tail["asset_id"], {"reason": "Rights pulled by the distributor."},
        scn["pd_headers"])))
    assert retracted["status"] == "RETRACTED"

    # The very next reads, with no refresh call and no clock movement.
    element = assert_playlist_item(fx.read_item(tail["id"], scn["mco_headers"]))
    assert element["clearance_status"] == "BLOCKED"
    playlist = assert_playlist(
        fx.read_playlist(scn["playlist"]["id"], scn["traffic_headers"]))
    assert playlist["blocked_item_count"] == 1
    assert playlist["item_count"] == 7
    assert playlist["status"] == "IMPORTED"
    assert playlist["armed_at_utc"] is None


def test_the_rebalance_response_carries_the_whole_recomputed_pool(api):
    """An acknowledgement is not enough: the pool figures come back with it.

    PRD §3.2: "*Step five* rolls the pool up. `effective_capacity_kbps` is written to the multiplex; `assigned_kbps` is the sum of `allocated_bitrate_kbps` over the candidate channels whose `allocation_state` ended as `ACTIVE` or `STANDBY`; `available_kbps` is `effective_capacity_kbps` less `assigned_kbps`; and `starved_channel_count` is the number of candidates that ended as `STARVED`."

    Design: Corner/consistency_model/every_derived_field_is_immediate_and_visible_in_the_causing_response_itself
    """
    plant = fx.setup_base_plant()
    mux = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])

    rebalanced = assert_multiplex(validate_success(api.rebalance_multiplex(
        mux["id"], {"expected_multiplex_version": mux["version"]},
        plant["eng_headers"])))

    assert rebalanced["effective_capacity_kbps"] == 38000
    assert rebalanced["assigned_kbps"] == 22000
    assert rebalanced["available_kbps"] == 16000
    assert rebalanced["starved_channel_count"] == 0
    assert_bandwidth_conservation(rebalanced)


def _instant(timestamp):
    """Strip fractional seconds and the zone marker for whole-second equality."""
    return timestamp.replace("Z", "").split(".")[0]


def test_a_power_write_lands_its_pool_and_its_filing_before_any_clock_move(api):
    """The transmitter comes back while its consequences are already in place.

    PRD §3.1: "Reducing power writes `current_power_pct` from the supplied `power_pct` and publishes a new `derate_factor`, which is 0.75 when `power_pct` is at least 50 and 0.50 when it is below 50."

    Design: Corner/consistency_model/every_derived_field_is_immediate_and_visible_in_the_causing_response_itself
    """
    plant = fx.setup_base_plant()

    reduced = assert_transmitter(validate_success(
        api.change_transmitter_power_state(
            plant["transmitter"]["id"],
            {"target_state": "REDUCED_POWER", "power_pct": 60,
             "reason": "Amplifier derate under thermal load."},
            plant["eng_headers"])))
    assert reduced["operational_state"] == "REDUCED_POWER"
    assert reduced["current_power_pct"] == 60
    assert float(reduced["derate_factor"]) == 0.75
    assert reduced["notification_pending_count"] == 1

    # 38800 derated to 29100, less the 800 pilot reservation, is 28300; both
    # channels still clear their floors, so 22000 stays assigned.
    mux = assert_multiplex(
        fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"]))
    assert mux["effective_capacity_kbps"] == 28300
    assert mux["assigned_kbps"] == 22000
    assert mux["available_kbps"] == 6300
    assert_bandwidth_conservation(mux)

    channel = assert_channel(fx.read_channel(plant["ch1"]["id"], plant["mco_headers"]))
    assert channel["allocated_bitrate_kbps"] == 16000
    assert channel["posture"] == "DEGRADED"

    filings = fx.list_notifications(plant["transmitter"]["id"], plant["eng_headers"],
                                   params={"status": "PENDING"})
    assert len(filings) == 1
    filing = assert_regulatory_notification(filings[0])
    assert filing["kind"] == "POWER_REDUCTION"
    assert filing["status"] == "PENDING"
    assert filing["observed_power_pct"] == 60
    assert _instant(filing["triggering_utc"]) == "2026-08-01T09:00:00"
    assert _instant(filing["due_utc"]) == "2026-08-02T09:00:00"


# ---------------------------------------------------------------------------
# A refused call leaves nothing behind, a successful one leaves everything
# ---------------------------------------------------------------------------

def test_an_over_capacity_pin_moves_neither_the_pool_nor_the_version(api):
    """The last check in the ladder must not have bumped the shared counter.

    PRD §3.2: "Separately, an explicit pin — `pin_allocated_kbps` on a demand change — or an admission that must be accepted as `ACTIVE` is refused with `ERR_MULTIPLEX_CAPACITY_EXCEEDED` when the resulting pinned total would exceed the multiplex's `effective_capacity_kbps`; a total exactly equal to the effective capacity is accepted."

    Design: Corner/consistency_model/a_rejected_call_leaves_no_trace_and_a_successful_one_leaves_every_trace_atomically
    """
    plant = fx.setup_base_plant()
    before = assert_multiplex(
        fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"]))
    assert before["assigned_kbps"] == 22000
    assert before["available_kbps"] == 16000

    resp = api.patch_channel_allocation(
        plant["ch1"]["id"],
        {"expected_multiplex_version": before["version"],
         "pin_allocated_kbps": 38001},
        plant["eng_headers"])
    validate_error(resp, "ERR_MULTIPLEX_CAPACITY_EXCEEDED")

    after = assert_multiplex(
        fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"]))
    assert after["version"] == before["version"], (
        "a refused write must never burn a concurrency token"
    )
    assert after["assigned_kbps"] == 22000
    assert after["available_kbps"] == 16000
    assert after["starved_channel_count"] == 0

    channel = assert_channel(fx.read_channel(plant["ch1"]["id"], plant["eng_headers"]))
    assert channel["allocated_bitrate_kbps"] == 16000
    assert channel["allocation_state"] == "ACTIVE"


def test_a_sparse_revision_ingests_none_of_its_items_and_no_counter(api):
    """Three items are one transaction: the hole at sequence three sinks it all.

    PRD §3.5: "Within one playlist, `sequence_number` is unique and the submitted revision's items must form **a dense run from 1 to N with no duplicates and no holes**, otherwise `ERR_SEQUENCE_NUMBER_CONFLICT`."

    Design: Corner/consistency_model/a_rejected_call_leaves_no_trace_and_a_successful_one_leaves_every_trace_atomically
    """
    plant = fx.setup_base_plant()
    prog = fx.setup_qc_passed_asset(plant, 1800)
    spot = fx.setup_qc_passed_asset(plant, 30)
    promo = fx.setup_qc_passed_asset(plant, 60)
    playlist = _one_element_playlist(plant, prog["id"])
    assert playlist["item_count"] == 1
    assert playlist["traffic_revision"] == 1

    resp = api.apply_traffic_revision(
        playlist["id"],
        {"expected_playlist_version": playlist["version"],
         "items": [
             {"sequence_number": 1, "element_kind": "PROGRAM",
              "asset_id": prog["id"],
              "scheduled_start_utc": "2026-08-01T12:00:00Z",
              "scheduled_duration_seconds": 1800},
             {"sequence_number": 2, "element_kind": "PROMO",
              "asset_id": spot["id"],
              "scheduled_start_utc": "2026-08-01T12:30:00Z",
              "scheduled_duration_seconds": 30},
             {"sequence_number": 4, "element_kind": "INTERSTITIAL",
              "asset_id": promo["id"],
              "scheduled_start_utc": "2026-08-01T12:30:30Z",
              "scheduled_duration_seconds": 60},
         ]},
        plant["traffic_headers"])
    validate_error(resp, "ERR_SEQUENCE_NUMBER_CONFLICT")

    after = assert_playlist(fx.read_playlist(playlist["id"], plant["traffic_headers"]))
    assert after["item_count"] == 1
    assert after["version"] == playlist["version"]
    assert after["traffic_revision"] == 1


def test_the_element_that_survives_a_refused_revision_is_the_original(api):
    """No orphan from the rejected batch is left in the collection.

    PRD §3.5: "Every existing item whose `playout_status` is still `SCHEDULED` is deleted and replaced by the supplied revision items, while items whose `playout_status` is `CUED`, `PLAYING`, `PLAYED`, `TRUNCATED`, `SKIPPED` or `PREEMPTED` are **retained untouched** — a revision can never rewrite history or steal an element automation has already cued."

    Design: Corner/consistency_model/a_rejected_call_leaves_no_trace_and_a_successful_one_leaves_every_trace_atomically
    """
    plant = fx.setup_base_plant()
    prog = fx.setup_qc_passed_asset(plant, 1800)
    other = fx.setup_qc_passed_asset(plant, 30)
    playlist = _one_element_playlist(plant, prog["id"])
    original = fx.list_items(playlist["id"], plant["traffic_headers"])[0]

    resp = api.apply_traffic_revision(
        playlist["id"],
        {"expected_playlist_version": playlist["version"],
         "items": [
             {"sequence_number": 2, "element_kind": "PROMO",
              "asset_id": other["id"],
              "scheduled_start_utc": "2026-08-01T12:00:00Z",
              "scheduled_duration_seconds": 30},
         ]},
        plant["traffic_headers"])
    validate_error(resp, "ERR_SEQUENCE_NUMBER_CONFLICT")

    rows, meta = validate_paginated(
        api.list_playlist_items(playlist["id"], plant["traffic_headers"]))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    survivor = assert_playlist_item(rows[0])
    assert survivor["id"] == original["id"]
    assert survivor["sequence_number"] == 1
    assert survivor["asset_id"] == prog["id"]
    assert survivor["playout_status"] == "SCHEDULED"


def test_a_refused_air_transition_writes_no_row_and_a_legal_one_writes_exactly_one(api):
    """The compliance log can never hold an event that did not happen.

    PRD §3.3: "A `target_air_status` that is not reachable from the channel's present `air_status` is refused with `ERR_CHANNEL_INVALID_AIR_STATE`, and **`EAS_OVERRIDE` is never reachable through the air-state endpoint at all** — asking for it there is refused with the same code even when the channel is `ON_AIR`, because that state belongs exclusively to the override cascade of §3.8."

    Design: Corner/consistency_model/a_rejected_call_leaves_no_trace_and_a_successful_one_leaves_every_trace_atomically
    """
    scn = fx.setup_playing_item1()
    playlist_id = scn["playlist"]["id"]
    item1 = item_by_sequence(fx.list_items(playlist_id, scn["traffic_headers"]), 1)
    assert item1["playout_status"] == "PLAYING"
    before_channel = assert_channel(fx.read_channel(scn["ch1"]["id"], scn["mco_headers"]))
    before_log = fx.list_as_run(playlist_id, scn["mco_headers"])

    resp = api.change_channel_air_state(
        scn["ch1"]["id"],
        {"target_air_status": "EAS_OVERRIDE",
         "reason": "Trying to reach the override state the wrong way."},
        scn["mco_headers"])
    validate_error(resp, "ERR_CHANNEL_INVALID_AIR_STATE")

    unchanged = assert_channel(fx.read_channel(scn["ch1"]["id"], scn["mco_headers"]))
    assert unchanged["air_status"] == "ON_AIR"
    assert unchanged["version"] == before_channel["version"]
    assert fx.read_item(item1["id"], scn["mco_headers"])["playout_status"] == "PLAYING"
    assert fx.list_as_run(playlist_id, scn["mco_headers"]) == before_log

    # The legal fallback truncates the playing element and logs it, together.
    bars = assert_channel(validate_success(api.change_channel_air_state(
        scn["ch1"]["id"],
        {"target_air_status": "BARS_AND_TONE", "reason": "Safe fallback."},
        scn["mco_headers"])))
    assert bars["air_status"] == "BARS_AND_TONE"
    assert fx.read_item(item1["id"], scn["mco_headers"])["playout_status"] == "TRUNCATED"
    after_log = fx.list_as_run(playlist_id, scn["mco_headers"])
    assert len(after_log) == len(before_log) + 1
    assert as_run_kinds(after_log[-1:]) == ["TRUNCATION"]


def test_a_stale_qc_submission_leaves_no_report_and_no_version_step(api):
    """The concurrency refusal costs the asset nothing at all.

    PRD §2.6: "A mismatch is rejected with `ERR_STALE_ASSET_VERSION` and HTTP 412."

    Design: Corner/consistency_model/a_rejected_call_leaves_no_trace_and_a_successful_one_leaves_every_trace_atomically
    """
    plant = _plant_with_received_promo()
    promo = plant["promo"]
    assert promo["status"] == "RECEIVED"

    resp = api.submit_qc_report(
        promo["id"],
        {"expected_asset_version": promo["version"] - 1,
         "inspected_by_operator_id": plant["qc"]["id"],
         "basis": "INGEST",
         "defect_codes": ["AUDIO_LOSS"],
         "measured_duration_seconds": 60},
        plant["qc_headers"])
    validate_error(resp, "ERR_STALE_ASSET_VERSION", expected_status=412)

    rows, meta = validate_paginated(
        api.list_qc_reports(plant["qc_headers"], params={"asset_id": promo["id"]}))
    assert meta["total_count"] == 0
    assert rows == []
    after = assert_asset(fx.read_asset(promo["id"], plant["traffic_headers"]))
    assert after["version"] == promo["version"]
    assert after["status"] == "RECEIVED"
    assert after["qc_verdict"] is None
