"""Entity shapes: creation defaults, computed fields, immutability and listing.

Each test builds its preconditions through PRD endpoints only, starting from the
empty database and the default logical clock the harness guarantees, and asserts
the housekeeping shape, the initial-state values and the derived figures the PRD
pins for one entity of the domain.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_append_only_common_fields,
    assert_as_run_entry,
    assert_asset,
    assert_channel,
    assert_full_common_fields,
    assert_multiplex,
    assert_playlist,
    assert_playlist_item,
    assert_qc_report,
    assert_transmitter,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]


def _mux_b(plant):
    """A second transport stream on the same transmitter carrying its own primary.

    MUX-B (total 20000, pilot 500) hosts channel 20.1, which is the
    cross-multiplex parent candidate and the third channel of the station.
    """
    mux = fx.create_multiplex(
        plant["eng_headers"], plant["transmitter"]["id"],
        name="MUX-B", total_capacity_kbps=20000, pilot_reserved_kbps=500,
        live_encoder_units_total=1,
    )
    channel = fx.create_channel(
        plant["eng_headers"], mux["id"], mux["version"],
        call_sign="WABC-DT1", channel_number="20.1", resolution_class="HD_720P",
        requested_bitrate_kbps=6000, floor_bitrate_kbps=5000, priority_rank=1,
    )
    return mux, channel


def test_transmitter_registration_starts_at_full_licence_with_zero_counters(api):
    """A newly registered facility radiates at full licence with every counter at zero.

    PRD §3.1: "A newly registered transmitter starts radiating at full licence:
    `operational_state` is `FULL_POWER`, `current_power_pct` is 100,
    `derate_factor` is 1.00, `outage_started_utc` is null, and
    `last_outage_seconds`, `cumulative_outage_seconds` and
    `notification_pending_count` are all 0."

    Design: Corner/entities/transmitter_create_returns_201_with_initial_state_and_zero_counters
    """
    plant = fx.bootstrap_operators()

    resp = api.create_transmitter(
        {"facility_id": "FAC-70011", "call_sign": "WXYZ", "authorized_erp_kw": 100},
        plant["eng_headers"],
    )
    tx = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object"

    assert_transmitter(tx)
    assert tx["operational_state"] == "FULL_POWER"
    assert tx["current_power_pct"] == 100
    assert float(tx["derate_factor"]) == 1.00
    assert tx["outage_started_utc"] is None
    assert tx["last_outage_seconds"] == 0
    assert tx["cumulative_outage_seconds"] == 0
    assert tx["notification_pending_count"] == 0
    assert_full_common_fields(tx)
    assert tx["version"] == 1


def test_multiplex_creation_applies_the_pilot_and_encoder_defaults(api):
    """Omitting both optional inputs pins pilot 500, two encoder units and 11500 kbps.

    PRD §3.2: "`pilot_reserved_kbps`, the kilobits permanently set aside for PSIP
    tables and null padding, defaults to 500 and must be at least 0 and strictly
    less than `total_capacity_kbps`; and `live_encoder_units_total`, the number of
    live-encoder units the multiplex can lend to feed windows, defaults to 2 and
    must be at least 1."

    Design: Corner/entities/multiplex_create_applies_pilot_and_encoder_defaults
    """
    plant = fx.bootstrap_operators()
    tx = fx.create_transmitter(plant["eng_headers"])

    resp = api.create_multiplex(
        {"transmitter_id": tx["id"], "name": "MUX-DEFAULTS",
         "total_capacity_kbps": 12000},
        plant["eng_headers"],
    )
    mux = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object"

    assert_multiplex(mux)
    assert mux["pilot_reserved_kbps"] == 500
    assert mux["live_encoder_units_total"] == 2
    # §3.2: take total_capacity_kbps, multiply by the derate 1.00, truncate, then
    # subtract pilot_reserved_kbps -> 11500.
    assert mux["effective_capacity_kbps"] == 11500
    assert mux["assigned_kbps"] == 0
    assert mux["available_kbps"] == 11500
    assert mux["starved_channel_count"] == 0
    assert mux["version"] == 1


def test_channel_admission_grants_floor_plus_weighted_share_and_starts_dark(api):
    """The only claimant on a 38000 kbps pool is granted its floor plus its whole weight.

    PRD §3.2: "A freshly admitted channel begins with `allocated_bitrate_kbps` at
    0 before the waterfall runs, `air_status` `DARK`, and `posture` `NORMAL`."

    Design: Corner/entities/channel_create_returns_201_and_grants_the_full_request_from_the_waterfall
    """
    plant = fx.setup_base_plant(with_subchannel=False)
    channel = fx.read_channel(plant["ch1"]["id"], plant["eng_headers"])
    mux = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])

    assert_channel(channel)
    # §3.2 step three: share = min(floor(28000 * 8000 / 8000), 8000) = 8000, so
    # allocated = floor 8000 + share 8000.
    assert channel["allocated_bitrate_kbps"] == 16000
    assert channel["allocation_state"] == "ACTIVE"
    assert channel["air_status"] == "DARK"
    assert channel["posture"] == "NORMAL"
    assert channel["open_fault_count"] == 0
    assert channel["service_class"] == "PRIMARY"
    assert channel["parent_channel_id"] is None
    assert channel["version"] == 1

    assert_multiplex(mux)
    assert mux["effective_capacity_kbps"] == 38000
    assert mux["assigned_kbps"] == 16000
    assert mux["available_kbps"] == 22000
    assert mux["starved_channel_count"] == 0


def test_subchannel_links_its_primary_and_re_slices_the_whole_pool(api):
    """Admitting the subchannel re-derives the incumbent's allocation, not just its own.

    PRD §2.6: "Every channel creation re-slices the whole bit pool and
    legitimately supersedes the prior allocation set, so a writer holding a stale
    view of the multiplex would compute its bitrate expectations against a pool
    that has already been re-divided."

    Design: Corner/entities/subchannel_create_links_its_parent_and_shares_the_multiplex_pool
    """
    plant = fx.setup_base_plant()
    ch1 = fx.read_channel(plant["ch1"]["id"], plant["eng_headers"])
    ch2 = fx.read_channel(plant["ch2"]["id"], plant["eng_headers"])
    mux = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])

    assert_channel(ch2)
    assert ch2["service_class"] == "SUBCHANNEL"
    assert ch2["parent_channel_id"] == ch1["id"]
    # Floors 8000 + 2000 = 10000, remainder 28000, weights 8000 and 4000, shares
    # 8000 and 4000 -> ch1 16000 and ch2 6000.
    assert ch2["allocated_bitrate_kbps"] == 6000
    assert ch2["allocation_state"] == "ACTIVE"
    assert ch1["allocated_bitrate_kbps"] == 16000
    assert ch1["allocation_state"] == "ACTIVE"

    assert mux["assigned_kbps"] == 22000
    assert mux["available_kbps"] == 16000
    # §2.5: version starts at 1 and increments by exactly one on every mutation,
    # and each admission re-slices the pool the multiplex owns.
    assert mux["version"] == 3

    data, meta = validate_paginated(
        api.list_channels(plant["eng_headers"], params={"parent_channel_id": ch1["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in data] == [ch2["id"]]


def test_every_malformed_channel_parent_linkage_reports_its_own_error(api):
    """Each of the four bad parent linkages, and an unknown parent id, is coded separately.

    PRD §3.2: "A `service_class` of `SUBCHANNEL` submitted without a
    `parent_channel_id` yields `ERR_SUBCHANNEL_PARENT_REQUIRED`; a `service_class`
    of `PRIMARY` submitted *with* a `parent_channel_id` yields
    `ERR_PRIMARY_CHANNEL_PARENT_FORBIDDEN` — which of the two codes applies is
    selected by the submitted `service_class`."

    Design: Corner/entities/channel_parent_graph_constraints_cannot_be_violated
    """
    plant = fx.setup_base_plant()
    eng = plant["eng_headers"]
    mux1_id = plant["multiplex"]["id"]
    _mux_b_row, ch_other = _mux_b(plant)

    def probe(call_sign, channel_number, service_class, parent_channel_id=None):
        payload = {
            "multiplex_id": mux1_id,
            "expected_multiplex_version": fx.read_multiplex(mux1_id, eng)["version"],
            "call_sign": call_sign,
            "channel_number": channel_number,
            "service_class": service_class,
            "resolution_class": "SD_480I",
            "requested_bitrate_kbps": 3000,
            "floor_bitrate_kbps": 2000,
            "priority_rank": 3,
        }
        if parent_channel_id is not None:
            payload["parent_channel_id"] = parent_channel_id
        return api.create_channel(payload, eng)

    # A subchannel with no parent at all.
    validate_error(probe("WXYZ-DT3", "12.3", "SUBCHANNEL"),
                   "ERR_SUBCHANNEL_PARENT_REQUIRED")
    # A primary that names a parent.
    validate_error(probe("WXYZ-DT4", "12.4", "PRIMARY", plant["ch1"]["id"]),
                   "ERR_PRIMARY_CHANNEL_PARENT_FORBIDDEN")
    # §3.2: "`parent_channel_id` must reference a channel whose own `service_class`
    # is `PRIMARY`, so a subchannel may not parent another subchannel".
    validate_error(probe("WXYZ-DT5", "12.5", "SUBCHANNEL", plant["ch2"]["id"]),
                   "ERR_INVALID_CHANNEL_PARENT")
    # §3.2: "a cross-stream parent yields `ERR_CROSS_MULTIPLEX_PARENT`".
    validate_error(probe("WXYZ-DT6", "12.6", "SUBCHANNEL", ch_other["id"]),
                   "ERR_CROSS_MULTIPLEX_PARENT")
    # §2.7: an unknown `channel_id` in the body yields `ERR_CHANNEL_NOT_FOUND`.
    validate_error(
        probe("WXYZ-DT7", "12.7", "SUBCHANNEL", "00000000-0000-4000-8000-00000000ffff"),
        "ERR_CHANNEL_NOT_FOUND",
    )


def test_expected_asset_reads_back_with_its_inputs_and_no_grading(api):
    """A booked-but-undelivered asset is EXPECTED with no delivery or QC figures.

    PRD §3.4: "The asset is created in `status` `EXPECTED`."

    Design: Corner/entities/asset_retrieval_returns_stored_input_and_null_computed_fields
    """
    plant = fx.bootstrap_operators()
    created = fx.create_asset(
        plant,
        house_number="HN-PROG-01", title="Evening Magazine", source="FILE_DELIVERY",
        expected_duration_seconds=1800, delivery_deadline_utc="2026-08-01T10:00:00Z",
        required_resolution_class="HD_1080I", captions_required=True,
    )

    resp = api.get_asset(created["id"], plant["traffic_headers"])
    asset = validate_success(resp)
    assert resp.json()["response_type"] == "object"

    assert_asset(asset)
    assert asset["status"] == "EXPECTED"
    assert asset["house_number"] == "HN-PROG-01"
    assert asset["expected_duration_seconds"] == 1800
    assert asset["required_resolution_class"] == "HD_1080I"
    assert asset["captions_required"] is True
    # §3.4: "A successful delivery writes `received_utc` and all the delivered
    # format fields" — none of them exist before the file lands.
    for field in ("received_utc", "measured_duration_seconds", "video_codec",
                  "delivered_resolution_class", "frame_rate", "audio_loudness_lkfs",
                  "audio_channel_config", "caption_present", "caption_language"):
        assert asset.get(field) is None, f"{field} must be unset before delivery"
    # §3.4: a delivery "resets `technical_score_ingest`, `technical_score_aircheck`
    # and `qc_verdict` to null", so null is their ungraded value.
    for field in ("technical_score_ingest", "technical_score_aircheck", "qc_verdict",
                  "waived_by_operator_id", "waiver_justification"):
        assert asset.get(field) is None, f"{field} must be null before grading"
    assert asset["version"] == 1

    data, meta = validate_paginated(
        api.list_assets(plant["traffic_headers"], params={"house_number": "HN-PROG-01"})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert data[0]["id"] == created["id"]


def test_clean_ingest_report_scores_100_from_the_stored_measurements(api):
    """A flawless inspection scores 100 with all four penalty buckets at zero.

    PRD §3.4: "The *loudness penalty* is a flat 12 points when the asset's
    `audio_loudness_lkfs` is present and its absolute distance from the station
    target of -24.0 LKFS exceeds 2.0 LKFS, and zero otherwise."

    Design: Corner/entities/qc_report_computed_scores_ignore_client_supplied_values
    """
    plant = fx.bootstrap_operators()
    asset = fx.create_asset(
        plant,
        house_number="HN-PROG-01", title="Evening Magazine", source="FILE_DELIVERY",
        expected_duration_seconds=1800, delivery_deadline_utc="2026-08-01T10:00:00Z",
        required_resolution_class="HD_1080I", captions_required=True,
    )
    delivered = fx.deliver_asset(
        plant, asset["id"],
        received_utc="2026-08-01T09:00:00Z", measured_duration_seconds=1800,
        video_codec="H264", delivered_resolution_class="HD_1080I", frame_rate=29.97,
        audio_loudness_lkfs=-24.0, audio_channel_config="STEREO_2_0",
        caption_present=True, caption_language="en-US",
    )

    resp = api.submit_qc_report(
        asset["id"],
        {"expected_asset_version": delivered["version"],
         "inspected_by_operator_id": plant["qc"]["id"],
         "basis": "INGEST",
         "defect_codes": [],
         "measured_duration_seconds": 1800,
         # A client reading far off target must not move the score: the penalty is
         # derived from the asset's own stored -24.0 LKFS.
         "audio_loudness_lkfs": -12.0,
         "notes": "clean pass"},
        plant["qc_headers"],
    )
    report = validate_success(resp, 201)

    assert_qc_report(report)
    assert report["technical_score"] == 100
    assert report["defect_penalty_points"] == 0
    assert report["duration_penalty_points"] == 0
    assert report["loudness_penalty_points"] == 0
    assert report["fault_penalty_points"] == 0
    assert report["verdict"] == "PASS"
    assert report["superseded"] is False
    assert report["basis"] == "INGEST"

    graded = fx.read_asset(asset["id"], plant["qc_headers"])
    assert graded["status"] == "QC_PASSED"
    assert graded["technical_score_ingest"] == 100
    assert graded["qc_verdict"] == "PASS"
    assert graded["technical_score_aircheck"] is None
    # §3.4: "a `received_utc` exactly at the deadline is on time and carries
    # `late_delivery` false" — 09:00:00 is an hour inside the 10:00:00 deadline.
    assert graded["late_delivery"] is False


def test_superseded_report_keeps_its_own_frozen_score_after_a_redelivery(api):
    """The failing report survives the redelivery loop unchanged, only flagged superseded.

    PRD §3.4: "Submitting a report supersedes any earlier report of the same
    `basis` on that asset by setting the earlier report's `superseded` to true.
    **Only the newest non-superseded report of a given basis governs** the asset's
    `qc_verdict`; superseded reports keep their own stored score forever but never
    drive asset status again."

    Design: Corner/entities/qc_report_rows_are_immutable_and_the_redelivery_loop_supersedes_them
    """
    plant = fx.bootstrap_operators()
    asset = fx.create_asset(
        plant,
        house_number="HN-BAD-01", title="Faulty Feature", source="FILE_DELIVERY",
        expected_duration_seconds=1800, delivery_deadline_utc="2026-08-01T10:00:00Z",
        required_resolution_class="HD_1080I", captions_required=False,
    )
    bad_delivery = fx.deliver_asset(
        plant, asset["id"],
        received_utc="2026-08-01T09:00:00Z", measured_duration_seconds=1782,
        audio_loudness_lkfs=-20.0,
    )

    first = validate_success(
        api.submit_qc_report(
            asset["id"],
            {"expected_asset_version": bad_delivery["version"],
             "inspected_by_operator_id": plant["qc"]["id"],
             "basis": "INGEST",
             "defect_codes": ["LOUDNESS_OUT_OF_SPEC", "VIDEO_ARTIFACT"],
             "measured_duration_seconds": 1782},
            plant["qc_headers"],
        ),
        201,
    )
    assert_qc_report(first)
    # Defects 12 + 10 = 22; discrepancy 18 -> ceil(18/2) * 3 = 27; loudness
    # distance 4.0 from -24.0 -> 12. 100 - 22 - 27 - 12 = 39.
    assert first["defect_penalty_points"] == 22
    assert first["duration_penalty_points"] == 27
    assert first["loudness_penalty_points"] == 12
    assert first["fault_penalty_points"] == 0
    assert first["technical_score"] == 39
    assert first["verdict"] == "FAIL"
    assert first["superseded"] is False
    failed = fx.read_asset(asset["id"], plant["qc_headers"])
    assert failed["status"] == "QC_FAILED"
    assert failed["technical_score_ingest"] == 39

    # §3.4: "Delivery is legal from `EXPECTED` and from `QC_FAILED`, the latter
    # being the redelivery of corrected media".
    good_delivery = fx.deliver_asset(
        plant, asset["id"],
        received_utc="2026-08-01T09:00:00Z", measured_duration_seconds=1800,
        audio_loudness_lkfs=-24.0,
    )
    second = validate_success(
        api.submit_qc_report(
            asset["id"],
            {"expected_asset_version": good_delivery["version"],
             "inspected_by_operator_id": plant["qc"]["id"],
             "basis": "INGEST",
             "defect_codes": [],
             "measured_duration_seconds": 1800},
            plant["qc_headers"],
        ),
        201,
    )
    assert second["technical_score"] == 100
    assert second["verdict"] == "PASS"
    assert second["superseded"] is False

    frozen = validate_success(api.get_qc_report(first["id"], plant["qc_headers"]))
    assert frozen["superseded"] is True
    assert frozen["technical_score"] == 39
    assert frozen["verdict"] == "FAIL"
    assert frozen["defect_penalty_points"] == 22
    assert frozen["duration_penalty_points"] == 27
    assert frozen["loudness_penalty_points"] == 12
    assert sorted(frozen["defect_codes"]) == ["LOUDNESS_OUT_OF_SPEC", "VIDEO_ARTIFACT"]
    # §2.5: a report is "append-only" and carries "`id` and `created_at` only".
    assert_append_only_common_fields(frozen)

    both, meta = validate_paginated(
        api.list_qc_reports(plant["qc_headers"], params={"asset_id": asset["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in both} == {first["id"], second["id"]}

    live, live_meta = validate_paginated(
        api.list_qc_reports(
            plant["qc_headers"],
            params={"asset_id": asset["id"], "include_superseded": "false"},
        )
    )
    assert live_meta["total_count"] == 1
    assert [row["id"] for row in live] == [second["id"]]

    passed = fx.read_asset(asset["id"], plant["qc_headers"])
    assert passed["status"] == "QC_PASSED"
    assert passed["technical_score_ingest"] == 100
    assert passed["qc_verdict"] == "PASS"
    # §3.4: "Either outcome increments the asset's `version` by one."
    assert passed["version"] == good_delivery["version"] + 1


def test_ending_an_element_appends_an_immutable_as_run_entry(api):
    """The end event writes a versionless log row snapshotting the element it describes.

    PRD §3.6: "An as-run entry is immutable and append-only; it carries only its
    own identifier and creation timestamp as housekeeping fields, and it is never
    updated, versioned or deleted."

    Design: Corner/entities/as_run_entry_rows_are_append_only_with_no_version_field
    """
    scn = fx.setup_playing_item1()
    item1 = scn["item1"]
    fx.set_clock("2026-08-01T12:30:00Z")

    resp = api.post_playout_event(
        item1["id"],
        {"event_kind": "END", "event_utc": "2026-08-01T12:30:00Z",
         "measured_duration_seconds": 1800, "source": "AUTOMATION"},
        scn["mco_headers"],
    )
    entry = validate_success(resp, 201)

    assert_as_run_entry(entry)
    assert "version" not in entry
    assert "updated_at" not in entry
    assert entry["event_kind"] == "END"
    assert entry["measured_duration_seconds"] == 1800
    assert entry["source"] == "AUTOMATION"
    assert entry["playlist_item_id"] == item1["id"]
    assert entry["playlist_id"] == scn["playlist"]["id"]
    # §3.6: the entry snapshots the element's `sequence_number`, `house_number` and
    # `element_kind` "taken at write time".
    assert entry["sequence_number"] == 1
    assert entry["element_kind"] == "PROGRAM"
    assert entry["house_number"] == scn["assets"]["prog1"]["house_number"]
    # §3.6: `recorded_by_user_id` holds "the opaque user identifier of the actor
    # whose call produced the entry".
    assert entry["recorded_by_user_id"] == scn["mco"]["id"]

    log, meta = validate_paginated(
        api.get_playlist_as_run(scn["playlist"]["id"], scn["mco_headers"])
    )
    assert meta["total_count"] == 3
    assert [row["event_kind"] for row in log] == ["CUE", "START", "END"]

    cues, cue_meta = validate_paginated(
        api.get_playlist_as_run(scn["playlist"]["id"], scn["mco_headers"],
                                params={"event_kind": "CUE"})
    )
    assert cue_meta["total_count"] == 1
    # §3.6: a `measured_duration_seconds` "that carries the seconds aired for end
    # and truncation events and **0 for every other event kind**".
    assert cues[0]["measured_duration_seconds"] == 0

    aired = fx.read_item(item1["id"], scn["mco_headers"])
    # §3.6: the end "writes that value onto the element"; §3.9 classifies an
    # element aired in full by its `PLAYED` status and that same figure.
    assert aired["playout_status"] == "PLAYED"
    assert aired["measured_duration_seconds"] == 1800
    assert aired["actual_start_utc"] == "2026-08-01T12:00:00Z"

    playlist = fx.read_playlist(scn["playlist"]["id"], scn["mco_headers"])
    # §3.5: 1800 aired + 30 + 30 + 300 + 60 + 60 + 1320 still booked = 3600,
    # less the 3600-second window.
    assert playlist["asrun_end_variance_seconds"] == 0


def test_channel_and_multiplex_lists_page_and_filter_through_the_envelope(api):
    """The declared narrowing parameters and the limit/offset window both apply.

    PRD §2.3: "`limit` caps the number of records returned; it defaults to 10 when
    omitted, may not be lower than 1, and may not be higher than 100. `offset` is
    the number of records to skip and defaults to 0. Both appear echoed back in
    the `meta` object of the response envelope alongside `total_count` (the number
    of records matching the query before pagination is applied) and `has_more`."

    Design: Corner/entities/list_endpoints_return_the_paginated_envelope_with_declared_filters
    """
    plant = fx.setup_base_plant()
    eng = plant["eng_headers"]
    mux1_id = plant["multiplex"]["id"]
    _mux_b(plant)

    # §3.2: "Channels can be listed narrowed by `multiplex_id`" — the third channel
    # of the station sits on the other transport stream and is excluded.
    data, meta = validate_paginated(
        api.list_channels(eng, params={"multiplex_id": mux1_id})
    )
    assert meta["total_count"] == 2
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert len(data) == 2

    # §3.2: "by `posture` or by `air_status`" — both channels are still dark and
    # normal, so narrowing further changes nothing.
    data, meta = validate_paginated(
        api.list_channels(eng, params={"multiplex_id": mux1_id,
                                       "air_status": "DARK", "posture": "NORMAL"})
    )
    assert meta["total_count"] == 2
    assert len(data) == 2

    # §3.2: "multiplexes can be listed narrowed by `transmitter_id`".
    data, meta = validate_paginated(
        api.list_multiplexes(eng, params={"transmitter_id": plant["transmitter"]["id"]})
    )
    assert meta["total_count"] == 2

    first_page, meta = validate_paginated(
        api.list_channels(eng, params={"multiplex_id": mux1_id, "limit": 1, "offset": 0})
    )
    assert len(first_page) == 1
    assert meta["total_count"] == 2
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    second_page, meta = validate_paginated(
        api.list_channels(eng, params={"multiplex_id": mux1_id, "limit": 1, "offset": 1})
    )
    assert len(second_page) == 1
    assert meta["offset"] == 1
    assert meta["has_more"] is False
    assert second_page[0]["id"] != first_page[0]["id"]

    validate_error(api.list_channels(eng, params={"limit": 0}), "ERR_INVALID_FIELD_VALUE")
    validate_error(api.list_channels(eng, params={"limit": 101}), "ERR_INVALID_FIELD_VALUE")


@pytest.mark.parametrize("path,error_id", [
    ("/transmitters/00000000-0000-4000-8000-000000000001", "ERR_TRANSMITTER_NOT_FOUND"),
    ("/multiplexes/00000000-0000-4000-8000-000000000002", "ERR_MULTIPLEX_NOT_FOUND"),
    ("/channels/00000000-0000-4000-8000-000000000003", "ERR_CHANNEL_NOT_FOUND"),
    ("/operators/00000000-0000-4000-8000-000000000004",
     "ERR_OPERATOR_REFERENCE_NOT_FOUND"),
    ("/assets/00000000-0000-4000-8000-000000000005", "ERR_ASSET_NOT_FOUND"),
    ("/qc-reports/00000000-0000-4000-8000-000000000006", "ERR_QC_REPORT_NOT_FOUND"),
    ("/playlists/00000000-0000-4000-8000-000000000007", "ERR_PLAYLIST_NOT_FOUND"),
    ("/playlist-items/00000000-0000-4000-8000-000000000008",
     "ERR_PLAYLIST_ITEM_NOT_FOUND"),
    ("/spot-orders/00000000-0000-4000-8000-000000000009", "ERR_SPOT_ORDER_NOT_FOUND"),
    ("/network-feed-windows/00000000-0000-4000-8000-00000000000a",
     "ERR_FEED_WINDOW_NOT_FOUND"),
    ("/emergency-overrides/00000000-0000-4000-8000-00000000000b",
     "ERR_OVERRIDE_NOT_FOUND"),
    ("/technical-faults/00000000-0000-4000-8000-00000000000c", "ERR_FAULT_NOT_FOUND"),
    ("/regulatory-notifications/00000000-0000-4000-8000-00000000000d",
     "ERR_NOTIFICATION_NOT_FOUND"),
])
def test_unknown_identifier_reports_the_code_of_its_own_path_segment(api, path, error_id):
    """Each entity segment carries its own 404 code, never a shared not-found code.

    PRD §2.7: "Each URL segment maps to its own not-found code: a transmitter
    segment yields `ERR_TRANSMITTER_NOT_FOUND`, a multiplex segment
    `ERR_MULTIPLEX_NOT_FOUND`, a channel segment `ERR_CHANNEL_NOT_FOUND`, an
    operator segment `ERR_OPERATOR_REFERENCE_NOT_FOUND`, an asset segment
    `ERR_ASSET_NOT_FOUND`, a QC-report segment `ERR_QC_REPORT_NOT_FOUND`, a
    playlist segment `ERR_PLAYLIST_NOT_FOUND`, a playlist-item segment
    `ERR_PLAYLIST_ITEM_NOT_FOUND`, a spot-order segment
    `ERR_SPOT_ORDER_NOT_FOUND`, a network-feed-window segment
    `ERR_FEED_WINDOW_NOT_FOUND`, an emergency-override segment
    `ERR_OVERRIDE_NOT_FOUND`, a technical-fault segment `ERR_FAULT_NOT_FOUND`, and
    a regulatory-notification segment `ERR_NOTIFICATION_NOT_FOUND`. All of these
    are HTTP 404."

    Design: Corner/entities/every_entity_id_returns_its_own_not_found_error
    """
    validate_error(api.get(path, headers=ADMIN), error_id)


def test_omitted_mandatory_inputs_are_refused_and_change_nothing(api):
    """Every mandatory field of a registration or a power move is enforced on its own.

    PRD §2.9: "a field listed without a trailing question mark in §3's narrative or
    §4's contract is mandatory and its absence yields `ERR_MISSING_REQUIRED_FIELD`
    (HTTP 422)."

    Design: Corner/entities/missing_required_fields_return_422_before_any_row_is_written
    """
    plant = fx.setup_base_plant(with_subchannel=False)
    eng = plant["eng_headers"]

    # §3.1: the engineer supplies "its licensed `authorized_erp_kw`".
    validate_error(
        api.create_transmitter({"facility_id": "FAC-70099", "call_sign": "WNEW"}, eng),
        "ERR_MISSING_REQUIRED_FIELD",
    )
    # §3.2: a multiplex is registered with its `total_capacity_kbps`.
    validate_error(
        api.create_multiplex(
            {"transmitter_id": plant["transmitter"]["id"], "name": "MUX-NO-CAP"}, eng),
        "ERR_MISSING_REQUIRED_FIELD",
    )
    # §3.3: an operator is registered with a `certification_expires_utc`.
    validate_error(
        api.create_operator(
            {"full_name": "Eve Nolan", "role_class": "QC", "override_authority": "NONE"},
            ADMIN),
        "ERR_MISSING_REQUIRED_FIELD",
    )
    # §3.4: registration supplies "the `delivery_deadline_utc` by which the file
    # must land, the `required_resolution_class` the channel needs, and
    # `captions_required`".
    validate_error(
        api.create_asset(
            {"house_number": "HN-INCOMPLETE", "title": "No Metadata",
             "source": "FILE_DELIVERY", "expected_duration_seconds": 1800},
            plant["traffic_headers"]),
        "ERR_MISSING_REQUIRED_FIELD",
    )
    # §3.1: "an off-air transition additionally requires a `reason`, and omitting
    # it is a missing-required-field failure".
    validate_error(
        api.change_transmitter_power_state(
            plant["transmitter"]["id"], {"target_state": "OFF_AIR"}, eng),
        "ERR_MISSING_REQUIRED_FIELD",
    )
    # §3.1: "When the target is `REDUCED_POWER`, `power_pct` must be present".
    validate_error(
        api.change_transmitter_power_state(
            plant["transmitter"]["id"], {"target_state": "REDUCED_POWER"}, eng),
        "ERR_MISSING_REQUIRED_FIELD",
    )

    untouched = fx.read_transmitter(plant["transmitter"]["id"], eng)
    assert untouched["operational_state"] == "FULL_POWER"
    assert untouched["current_power_pct"] == 100
    assert untouched["version"] == 1


def test_unknown_enum_literals_and_out_of_range_numbers_are_coded_apart(api):
    """A literal outside a vocabulary and a number outside its range carry different codes.

    PRD §2.9: "Every enum-typed field must carry one of the exact literals below,
    matched case-sensitively; anything else yields `ERR_INVALID_ENUM_VALUE` (HTTP
    422). Type and range violations yield `ERR_INVALID_FIELD_VALUE` (HTTP 422)."

    Design: Corner/entities/enum_and_range_type_constraints_are_rejected_with_invalid_enum_or_field_value
    """
    plant = fx.setup_base_plant()
    eng = plant["eng_headers"]
    traffic = plant["traffic_headers"]
    mux_id = plant["multiplex"]["id"]

    def asset_payload(**overrides):
        payload = {
            "house_number": f"HN-RANGE-{overrides.pop('tag')}",
            "title": "Range Probe", "source": "FILE_DELIVERY",
            "expected_duration_seconds": 1800,
            "delivery_deadline_utc": "2026-08-01T10:00:00Z",
            "required_resolution_class": "HD_1080I", "captions_required": False,
        }
        payload.update(overrides)
        return payload

    def order_payload(**overrides):
        payload = {
            "channel_id": plant["ch1"]["id"], "advertiser_name": "Delta Motors",
            "order_reference": f"ORD-RANGE-{overrides.pop('tag')}",
            "ordered_spots": 4, "unit_duration_seconds": 30,
            "rate_cents_total": 400000, "daypart": "PRIME",
            "priority_class": "PREEMPTIBLE",
            "makegood_deadline_utc": "2026-08-02T00:00:00Z",
        }
        payload.update(overrides)
        return payload

    def channel_payload(**overrides):
        payload = {
            "multiplex_id": mux_id,
            "expected_multiplex_version": fx.read_multiplex(mux_id, eng)["version"],
            "call_sign": f"WXYZ-DT{overrides.pop('tag')}",
            "channel_number": "12.9", "service_class": "PRIMARY",
            "resolution_class": "SD_480I", "requested_bitrate_kbps": 3000,
            "floor_bitrate_kbps": 2000, "priority_rank": 3,
        }
        payload.update(overrides)
        return payload

    # §2.9: asset `source` is one of SATELLITE_FEED, FILE_DELIVERY, LIVE_LINE,
    # LOCAL_ARCHIVE.
    validate_error(
        api.create_asset(asset_payload(tag="1", source="BLURAY_DISC"), traffic),
        "ERR_INVALID_ENUM_VALUE",
    )
    # §2.9: `required_resolution_class` is one of HD_1080I, HD_720P, SD_480I.
    validate_error(
        api.create_asset(
            asset_payload(tag="2", required_resolution_class="UHD_2160P"), traffic),
        "ERR_INVALID_ENUM_VALUE",
    )
    # §2.9: spot order `daypart` is one of EARLY_MORNING, DAYTIME, EARLY_FRINGE,
    # PRIME, LATE_NIGHT.
    validate_error(
        api.create_spot_order(order_payload(tag="3", daypart="OVERNIGHT"), traffic),
        "ERR_INVALID_ENUM_VALUE",
    )
    # §3.2: the `channel_number` is "written as major and minor parts separated by a
    # dot — one to three digits, a dot, then one or two digits".
    validate_error(
        api.create_channel(channel_payload(tag="A", channel_number="121"), eng),
        "ERR_INVALID_FIELD_VALUE",
    )
    # §3.2: "`floor_bitrate_kbps` must itself be at least 100 and `priority_rank`
    # at least 1."
    validate_error(
        api.create_channel(
            channel_payload(tag="B", channel_number="12.8", priority_rank=0), eng),
        "ERR_INVALID_FIELD_VALUE",
    )
    # §3.2: the multiplex's "`total_capacity_kbps`, which must be at least 1000".
    validate_error(
        api.create_multiplex(
            {"transmitter_id": plant["transmitter"]["id"], "name": "MUX-TINY",
             "total_capacity_kbps": 999}, eng),
        "ERR_INVALID_FIELD_VALUE",
    )
    # §3.9: "the contracted `unit_duration_seconds` of each spot — at least 5".
    validate_error(
        api.create_spot_order(order_payload(tag="4", unit_duration_seconds=4), traffic),
        "ERR_INVALID_FIELD_VALUE",
    )


def test_ingest_without_a_window_measures_the_day_against_a_full_24_hours(api):
    """The omitted window defaults to 86400, which drives both variance figures.

    PRD §3.5: "optionally the `window_duration_seconds` the day is measured
    against, which defaults to 86400 — a full 24 hours expressed in seconds — and
    must be at least 60."

    Design: Corner/entities/playlist_ingest_defaults_window_duration_and_seeds_item_system_fields
    """
    plant = fx.setup_base_plant()
    programme = fx.setup_qc_passed_asset(
        plant, 600, asset_overrides={"house_number": "HN-PROG-01"})
    spot = fx.setup_qc_passed_asset(plant, 30)

    resp = api.ingest_playlist(
        {"channel_id": plant["ch2"]["id"],
         "broadcast_day": "2026-08-01",
         "schedule_start_utc": "2026-08-01T14:00:00Z",
         "items": [
             {"sequence_number": 1, "element_kind": "PROGRAM",
              "house_number": "HN-PROG-01", "asset_id": programme["id"],
              "scheduled_start_utc": "2026-08-01T14:00:00Z",
              "scheduled_duration_seconds": 600},
             {"sequence_number": 2, "element_kind": "COMMERCIAL",
              "asset_id": spot["id"],
              "scheduled_start_utc": "2026-08-01T14:10:00Z",
              "scheduled_duration_seconds": 30},
         ]},
        plant["traffic_headers"],
    )
    playlist = validate_success(resp, 201)

    assert_playlist(playlist)
    assert playlist["window_duration_seconds"] == 86400
    # §3.5: the playlist "is created in `status` `IMPORTING` and, at the end of a
    # successful ingest transaction, moves automatically to `IMPORTED`", and the
    # ingest "sets `traffic_revision` to 1".
    assert playlist["status"] == "IMPORTED"
    assert playlist["traffic_revision"] == 1
    assert playlist["version"] == 1
    assert playlist["item_count"] == 2
    assert playlist["blocked_item_count"] == 0
    assert playlist["scheduled_total_seconds"] == 630
    # 600 + 30 booked seconds less the 86400-second window.
    assert playlist["projected_end_variance_seconds"] == -85770
    assert playlist["asrun_end_variance_seconds"] == -85770
    # §3.5: only COMMERCIAL elements count, keyed by "the decimal string of that
    # index" measured from schedule_start_utc.
    assert playlist["commercial_seconds_by_hour"] == {"0": 30}
    assert playlist.get("armed_at_utc") is None

    items = fx.list_items(playlist["id"], plant["traffic_headers"])
    assert [row["sequence_number"] for row in items] == [1, 2]
    item1 = items[0]
    assert_playlist_item(item1)
    # §3.5: the ingest "creates every item row with `playout_status` `SCHEDULED`"
    # and creates an item "`CLEARED` when its `asset_id` points at an asset whose
    # `status` is `QC_PASSED` or `QC_WAIVED`".
    assert item1["playout_status"] == "SCHEDULED"
    assert item1["clearance_status"] == "CLEARED"
    assert item1["house_number"] == "HN-PROG-01"
    assert item1["element_kind"] == "PROGRAM"
    assert item1["scheduled_duration_seconds"] == 600
    # §3.5: "`max_trim_seconds` defaults to 0".
    assert item1["max_trim_seconds"] == 0
    assert item1["trim_applied_seconds"] == 0
    assert item1["is_makegood"] is False
    assert item1.get("actual_start_utc") is None
    assert item1["version"] == 1
