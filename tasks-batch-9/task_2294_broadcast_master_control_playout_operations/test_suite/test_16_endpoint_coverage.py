"""Endpoint-surface coverage: envelopes, pagination, filters and write shapes.

Every endpoint in §4 returns the standard envelope of §2.2 and every list
endpoint honours the pagination contract of §2.3. The tests below walk that
surface: the collection reads and their declared ordering, the single-resource
projections and their purity, the declared query filters, the two allocation
writes behind a parent version token, substitution defaults, the ops-run
checkpoint, the 201/200 split, the reconciliation variant and the operator
status patch.
"""
import pytest

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    TRAFFIC,
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
    assert_spot_order,
    assert_technical_fault,
    assert_transmitter,
    factories,
    fixtures as fx,
    item_by_sequence,
    make_master_control_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# PRD §2.4: the logical clock reads exactly 2026-08-01T00:00:00Z before any
# client touches it, so every scenario pins the instants it depends on.
_ITEM1_START = "2026-08-01T12:00:00Z"
_ITEM1_END = "2026-08-01T12:30:00Z"


# ---------------------------------------------------------------------------
# Private setup helpers (test_helpers/ is read-only, so extras live here)
# ---------------------------------------------------------------------------

def _rig_with_first_element_aired():
    """The canonical broadcast day on air with element one cued, started, ended."""
    scn = fx.setup_on_air_playlist()
    fx.air_item(scn, scn["items"][0], _ITEM1_START, _ITEM1_END, 1800)
    return scn


def _collection_reads(api, scn):
    """The fourteen endpoints of §4 whose response is an array of resources."""
    playlist_id = scn["playlist"]["id"]
    item_id = scn["items"][0]["id"]
    return [
        ("GET /multiplexes",
         lambda p=None: api.list_multiplexes(ADMIN, params=p)),
        ("GET /channels",
         lambda p=None: api.list_channels(ADMIN, params=p)),
        ("GET /assets",
         lambda p=None: api.list_assets(ADMIN, params=p)),
        ("GET /qc-reports",
         lambda p=None: api.list_qc_reports(ADMIN, params=p)),
        ("GET /playlist-items",
         lambda p=None: api.list_all_playlist_items(ADMIN, params=p)),
        ("GET /spot-orders",
         lambda p=None: api.list_spot_orders(ADMIN, params=p)),
        ("GET /emergency-overrides",
         lambda p=None: api.list_overrides(ADMIN, params=p)),
        ("GET /technical-faults",
         lambda p=None: api.list_faults(ADMIN, params=p)),
        ("GET /transmitters/{id}/notifications",
         lambda p=None: api.list_transmitter_notifications(
             scn["transmitter"]["id"], ADMIN, params=p)),
        ("GET /channels/{id}/playlists",
         lambda p=None: api.list_channel_playlists(scn["ch1"]["id"], ADMIN, params=p)),
        ("GET /channels/{id}/feed-windows",
         lambda p=None: api.list_channel_feed_windows(scn["ch1"]["id"], ADMIN, params=p)),
        ("GET /playlists/{id}/items",
         lambda p=None: api.list_playlist_items(playlist_id, ADMIN, params=p)),
        ("GET /playlists/{id}/as-run",
         lambda p=None: api.get_playlist_as_run(playlist_id, ADMIN, params=p)),
        ("GET /playlist-items/{id}/as-run",
         lambda p=None: api.get_item_as_run(item_id, ADMIN, params=p)),
    ]


# ===========================================================================
# The fourteen collection reads
# ===========================================================================

def test_every_collection_read_returns_the_paginated_array_envelope(api):
    """All fourteen array endpoints carry the same envelope and pagination meta.

    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/endpoints/all_14_collection_reads_share_the_paginated_array_envelope_and_a_deterministic_order
    """
    scn = _rig_with_first_element_aired()

    for label, call in _collection_reads(api, scn):
        resp = call()
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert_envelope_meta(body)
        assert body["response_type"] == "array", (
            f"{label} returns a list of resources, so response_type must be 'array'"
        )
        assert isinstance(data, list), f"{label} must return a JSON array in data"
        assert meta["limit"] == 10, f"{label}: limit defaults to 10 when omitted"
        assert meta["offset"] == 0, f"{label}: offset defaults to 0 when omitted"
        assert isinstance(meta["total_count"], int) and meta["total_count"] >= len(data)
        assert meta["has_more"] is (meta["total_count"] > meta["offset"] + len(data)), (
            f"{label}: has_more is true only when records remain beyond the page"
        )


def test_collection_totals_count_every_matching_row_not_the_returned_page(api):
    """total_count reports the whole match set while data reports one window.

    PRD §2.3: "Both appear echoed back in the `meta` object of the response
    envelope alongside `total_count` (the number of records matching the query
    before pagination is applied) and `has_more` (true when records remain
    beyond the current page)."

    Design: Corner/endpoints/all_14_collection_reads_share_the_paginated_array_envelope_and_a_deterministic_order
    """
    plant = fx.setup_base_plant()
    for duration in (1800, 30, 60, 1320):
        fx.setup_qc_passed_asset(plant, duration)
    expected_only = fx.create_asset(plant, delivery_deadline_utc="2026-08-01T18:00:00Z")

    full, meta = validate_paginated(api.list_assets(ADMIN))
    assert meta["total_count"] == 5, "five assets were registered on this bench"
    assert len(full) == 5 and meta["has_more"] is False

    first, meta_first = validate_paginated(
        api.list_assets(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(first) == 2, "the page carries only the requested window"
    assert meta_first["total_count"] == 5, "total_count is the match count, not the page size"
    assert meta_first["has_more"] is True

    second, meta_second = validate_paginated(
        api.list_assets(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(second) == 2
    assert meta_second["total_count"] == 5
    assert meta_second["has_more"] is True

    tail, meta_tail = validate_paginated(
        api.list_assets(ADMIN, params={"limit": 2, "offset": 4})
    )
    assert len(tail) == 1 and meta_tail["has_more"] is False

    filtered, meta_filtered = validate_paginated(
        api.list_assets(ADMIN, params={"status": "QC_PASSED"})
    )
    assert len(filtered) == 4, "the four passed assets match"
    assert meta_filtered["total_count"] == 4, (
        "the filter narrows data and total_count together, so total_count counts "
        "the rows matching the query"
    )
    assert expected_only["id"] not in [row["id"] for row in filtered]


@pytest.mark.parametrize("bad_limit", [0, 101])
def test_a_limit_outside_its_declared_range_is_rejected(api, bad_limit):
    """limit may be neither below 1 nor above 100, and 100 itself is legal.

    PRD §2.3: "`limit` caps the number of records returned; it defaults to 10
    when omitted, may not be lower than 1, and may not be higher than 100."

    Design: Corner/endpoints/all_14_collection_reads_share_the_paginated_array_envelope_and_a_deterministic_order
    """
    fx.setup_base_plant()

    validate_error(
        api.list_channels(ADMIN, params={"limit": bad_limit}),
        "ERR_INVALID_FIELD_VALUE",
    )

    _, meta = validate_paginated(api.list_channels(ADMIN, params={"limit": 100}))
    assert meta["limit"] == 100, "the declared maximum is accepted and echoed back"


def test_playlist_items_are_listed_in_sequence_number_order(api):
    """The element list follows the ordering its §4 description names.

    PRD §2.3: "Endpoints whose §4 description names a different ordering — the
    notification list ordered by newest `triggering_utc`, the playlist list
    ordered by newest `broadcast_day`, the feed-window list ascending by
    `join_utc`, the item list in `sequence_number` order, the as-run views in
    `event_utc` order — follow the ordering stated there."

    Design: Corner/endpoints/all_14_collection_reads_share_the_paginated_array_envelope_and_a_deterministic_order
    """
    scn = fx.setup_on_air_playlist()

    data, meta = validate_paginated(
        api.list_playlist_items(scn["playlist"]["id"], ADMIN)
    )
    assert meta["total_count"] == 7, "the canonical day carries seven elements"
    assert meta["has_more"] is False, "seven rows fit inside the default limit of 10"
    sequences = [row["sequence_number"] for row in data]
    assert sequences == [1, 2, 3, 4, 5, 6, 7], (
        f"the item list must be ordered by sequence_number, got {sequences}"
    )
    assert data[0]["id"] == item_by_sequence(scn["items"], 1)["id"]


def test_the_as_run_log_is_listed_in_event_utc_order(api):
    """The as-run views are chronological and append-only in time order.

    PRD §3.6: "`event_utc` must be at or after the `event_utc` of the most
    recent as-run entry for the same playlist, because the log is append-only
    in time order"

    Design: Corner/endpoints/all_14_collection_reads_share_the_paginated_array_envelope_and_a_deterministic_order
    """
    scn = _rig_with_first_element_aired()

    data, meta = validate_paginated(
        api.get_playlist_as_run(scn["playlist"]["id"], ADMIN)
    )
    assert meta["total_count"] == 3, "one cue, one start and one end were reported"
    stamps = [row["event_utc"] for row in data]
    assert stamps == sorted(stamps), f"the log must be ordered by event_utc, got {stamps}"
    assert [row["event_kind"] for row in data] == ["CUE", "START", "END"], (
        "the cue and the start share an instant, so the append order decides"
    )
    for row in data:
        assert_as_run_entry(row)


# ===========================================================================
# The fourteen single-resource reads
# ===========================================================================

def _fully_populated_plant(api):
    """The on-air day plus a feed window, an override request, a fault, a filing.

    Reducing power to 79 percent trips the reduction filing, so every one of the
    domain's read surfaces has at least one row to project.
    """
    scn = _rig_with_first_element_aired()
    scn["window"] = fx.create_window(
        scn, "2026-08-01T12:31:00Z", "2026-08-01T12:36:00Z",
        anchor_sequence_number=4,
    )
    scn["override"] = fx.request_override(
        scn, requested_start_utc="2026-08-01T12:45:00Z"
    )
    scn["fault"] = fx.report_channel_fault(
        scn, "CAPTION_LOSS", "MINOR", "2026-08-01T12:00:00Z"
    )
    scn["transmitter"] = fx.change_power_state(scn, "REDUCED_POWER", power_pct=79)
    scn["notification"] = fx.list_notifications(scn["transmitter"]["id"])[0]
    reports, _meta = validate_paginated(api.list_qc_reports(scn["qc_headers"]))
    scn["report"] = reports[0]
    return scn


def test_every_single_resource_read_returns_the_object_envelope(api):
    """All fourteen detail reads answer with a single resource in an object envelope.

    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/all_14_single_resource_reads_project_every_computed_field_and_never_mutate
    """
    scn = _fully_populated_plant(api)
    item1 = scn["items"][0]

    reads = [
        ("GET /transmitters/{id}", api.get_transmitter(scn["transmitter"]["id"], ADMIN),
         assert_transmitter),
        ("GET /multiplexes/{id}", api.get_multiplex(scn["multiplex"]["id"], ADMIN),
         assert_multiplex),
        ("GET /operators/{id}", api.get_operator(scn["mco"]["id"], ADMIN),
         assert_operator),
        ("GET /channels/{id}", api.get_channel(scn["ch1"]["id"], ADMIN),
         assert_channel),
        ("GET /assets/{id}", api.get_asset(scn["assets"]["prog1"]["id"], ADMIN),
         assert_asset),
        ("GET /qc-reports/{id}", api.get_qc_report(scn["report"]["id"], ADMIN),
         assert_qc_report),
        ("GET /playlists/{id}", api.get_playlist(scn["playlist"]["id"], ADMIN),
         assert_playlist),
        ("GET /playlist-items/{id}", api.get_playlist_item(item1["id"], ADMIN),
         assert_playlist_item),
        ("GET /network-feed-windows/{id}", api.get_feed_window(scn["window"]["id"], ADMIN),
         assert_feed_window),
        ("GET /emergency-overrides/{id}", api.get_override(scn["override"]["id"], ADMIN),
         assert_override),
        ("GET /technical-faults/{id}", api.get_fault(scn["fault"]["id"], ADMIN),
         assert_technical_fault),
        ("GET /spot-orders/{id}", api.get_spot_order(scn["order"]["id"], ADMIN),
         assert_spot_order),
        ("GET /regulatory-notifications/{id}",
         api.get_notification(scn["notification"]["id"], ADMIN),
         assert_regulatory_notification),
        ("GET /playlists/{id}/reconciliation",
         api.get_playlist_reconciliation(scn["playlist"]["id"], ADMIN), None),
    ]

    assert len(reads) == 14, "the surface offers fourteen single-resource reads"
    for label, resp, shape in reads:
        data = validate_success(resp)
        body = resp.json()
        assert_envelope_meta(body)
        assert body["response_type"] == "object", (
            f"{label} returns one resource, so response_type must be 'object'"
        )
        assert "limit" not in body["meta"], (
            f"{label} is not a list endpoint, so it carries no pagination meta"
        )
        assert isinstance(data, dict), f"{label} must return a JSON object in data"
        if shape is not None:
            # The reconciliation read is a computed view rather than a stored
            # resource: PRD 2.5 gives `id` to entities, and PRD 3.9 describes the
            # view only as returning "the settlement figures without persisting
            # anything", so no identifier is declared for it.
            assert data.get("id"), f"{label} must project an id"
            shape(data)


def test_a_derate_is_visible_through_the_multiplex_read(api):
    """The detail read projects the recomputed pool the derate produced.

    PRD §2.11: "For every multiplex, the sum of `available_kbps` and
    `assigned_kbps` equals its `effective_capacity_kbps` — which is itself the
    nominal `total_capacity_kbps` scaled by the parent transmitter's
    `derate_factor`, truncated downward, less `pilot_reserved_kbps`, and floored
    at 0."

    Design: Corner/endpoints/all_14_single_resource_reads_project_every_computed_field_and_never_mutate
    """
    plant = fx.setup_base_plant()
    before = fx.read_multiplex(plant["multiplex"]["id"])
    assert before["effective_capacity_kbps"] == 38000
    assert before["assigned_kbps"] == 22000
    assert before["available_kbps"] == 16000

    fx.change_power_state(plant, "REDUCED_POWER", power_pct=75)
    assert fx.read_transmitter(plant["transmitter"]["id"])["derate_factor"] == 0.75

    after = validate_success(api.get_multiplex(plant["multiplex"]["id"], ADMIN))
    assert after["effective_capacity_kbps"] == 28300, (
        "38800 scaled by 0.75 truncates to 29100 and loses the 800 kbps pilot"
    )
    assert after["assigned_kbps"] == 22000, "both floors and both requests still fit"
    assert after["available_kbps"] == 6300
    assert_bandwidth_conservation(after)

    again = validate_success(api.get_multiplex(plant["multiplex"]["id"], ADMIN))
    assert again["version"] == after["version"], (
        "a read is not a mutation, so the version may not move between two reads"
    )
    assert again["updated_at"] == after["updated_at"]


def test_repeated_reads_never_expire_anything(api):
    """Reading an overdue asset or a stale fault does not sweep either of them.

    PRD §2.4: "Advancing the clock is also the system's **ops-run checkpoint**,
    and it is the only mechanism by which anything expires. There are no
    background jobs."

    Design: Corner/endpoints/all_14_single_resource_reads_project_every_computed_field_and_never_mutate
    """
    scn = fx.setup_on_air_playlist()
    stale_asset = fx.create_asset(scn, delivery_deadline_utc="2026-08-01T10:00:00Z")
    assert stale_asset["status"] == "EXPECTED"
    stale_fault = fx.report_channel_fault(
        scn, "CAPTION_LOSS", "MINOR", "2026-08-01T11:00:00Z"
    )
    assert stale_fault["state"] == "DETECTED"

    for _ in range(3):
        asset = validate_success(api.get_asset(stale_asset["id"], ADMIN))
        fault = validate_success(api.get_fault(stale_fault["id"], ADMIN))
        assert asset["status"] == "EXPECTED", (
            "the delivery grace lapsed at 11:00 but only a clock advance expires it"
        )
        assert asset["version"] == stale_asset["version"]
        assert fault["state"] == "DETECTED", (
            "the fault is well past its auto-clear dwell but no read may clear it"
        )
        assert fault.get("cleared_utc") is None
        assert fault["version"] == stale_fault["version"]


def test_suspended_and_uncertified_operators_may_still_read(api):
    """Neither suspension nor a lapsed certification closes the read surface.

    PRD §2.1: "A suspended operator — one whose `status` is `SUSPENDED` rather
    than `ACTIVE` — is refused every mutating request with
    `ERR_OPERATOR_SUSPENDED`, while read endpoints remain available to them."
    The certification gate "is not applied to any read endpoint."

    Design: Corner/endpoints/all_14_single_resource_reads_project_every_computed_field_and_never_mutate
    """
    plant = fx.setup_base_plant()
    asset = fx.setup_qc_passed_asset(plant, 600)

    suspended = fx.suspend_operator(plant["mco"]["id"])
    assert suspended["status"] == "SUSPENDED"
    lapsed = fx.create_operator(
        "MASTER_CONTROL", "NONE", "2026-08-01T08:00:00Z", full_name="Eve Lapsed"
    )
    assert lapsed["certification_state"] == "EXPIRED"
    lapsed_headers = make_master_control_headers(lapsed["id"])

    for headers, who in ((plant["mco_headers"], "the suspended operator"),
                         (lapsed_headers, "the uncertified operator")):
        channel = validate_success(api.get_channel(plant["ch1"]["id"], headers))
        assert channel["id"] == plant["ch1"]["id"], f"{who} must still be able to read"
        read_asset = validate_success(api.get_asset(asset["id"], headers))
        assert read_asset["status"] == "QC_PASSED"
        _data, meta = validate_paginated(api.list_channels(headers))
        assert meta["total_count"] == 2


def test_a_multiplex_id_in_the_channel_segment_reports_no_such_channel(api):
    """Each path segment answers with the error naming its own segment.

    PRD §2.7: "Each URL segment maps to its own not-found code: a transmitter
    segment yields `ERR_TRANSMITTER_NOT_FOUND`, a multiplex segment
    `ERR_MULTIPLEX_NOT_FOUND`, a channel segment `ERR_CHANNEL_NOT_FOUND`, ...
    an asset segment `ERR_ASSET_NOT_FOUND`"

    Design: Corner/endpoints/all_14_single_resource_reads_project_every_computed_field_and_never_mutate
    """
    plant = fx.setup_base_plant()

    validate_error(
        api.get_channel(plant["multiplex"]["id"], ADMIN), "ERR_CHANNEL_NOT_FOUND"
    )
    validate_error(
        api.get_multiplex(plant["ch1"]["id"], ADMIN), "ERR_MULTIPLEX_NOT_FOUND"
    )
    validate_error(
        api.get_transmitter(plant["multiplex"]["id"], ADMIN),
        "ERR_TRANSMITTER_NOT_FOUND",
    )
    validate_error(
        api.get_asset(plant["ch1"]["id"], ADMIN), "ERR_ASSET_NOT_FOUND"
    )


# ===========================================================================
# The declared query filters
# ===========================================================================

def _declared_filters(api, scn):
    """Every filter §3 declares, as (label, response, row field, value, count).

    A count of None means the population is not pinned by this bench, so only
    the per-row field check applies.
    """
    tx = scn["transmitter"]["id"]
    mux = scn["multiplex"]["id"]
    ch1 = scn["ch1"]["id"]
    ch2 = scn["ch2"]["id"]
    playlist = scn["playlist"]["id"]
    item1 = scn["items"][0]["id"]
    order = scn["order"]["id"]
    prog1 = scn["assets"]["prog1"]
    spot = scn["assets"]["spot"]["id"]
    posture = fx.read_channel(ch1)["posture"]
    broadcast_day = fx.read_playlist(playlist)["broadcast_day"]

    def notifications(params):
        return api.list_transmitter_notifications(tx, ADMIN, params=params)

    return [
        ("notifications?status", notifications({"status": "PENDING"}),
         "status", "PENDING", 1),
        ("notifications?kind", notifications({"kind": "POWER_REDUCTION"}),
         "kind", "POWER_REDUCTION", 1),
        ("multiplexes?transmitter_id",
         api.list_multiplexes(ADMIN, params={"transmitter_id": tx}),
         "transmitter_id", tx, 1),
        ("channels?multiplex_id",
         api.list_channels(ADMIN, params={"multiplex_id": mux}),
         "multiplex_id", mux, 2),
        ("channels?parent_channel_id",
         api.list_channels(ADMIN, params={"parent_channel_id": ch1}),
         "parent_channel_id", ch1, 1),
        ("channels?posture",
         api.list_channels(ADMIN, params={"posture": posture}),
         "posture", posture, None),
        ("channels?air_status",
         api.list_channels(ADMIN, params={"air_status": "ON_AIR"}),
         "air_status", "ON_AIR", 1),
        ("channel playlists?status",
         api.list_channel_playlists(ch1, ADMIN, params={"status": "ON_AIR"}),
         "status", "ON_AIR", 1),
        ("channel playlists?broadcast_day",
         api.list_channel_playlists(ch1, ADMIN,
                                    params={"broadcast_day": broadcast_day}),
         "broadcast_day", broadcast_day, 1),
        ("feed-windows?state",
         api.list_channel_feed_windows(ch1, ADMIN, params={"state": "PLANNED"}),
         "state", "PLANNED", 1),
        ("assets?status",
         api.list_assets(ADMIN, params={"status": "QC_PASSED"}),
         "status", "QC_PASSED", 4),
        ("assets?house_number",
         api.list_assets(ADMIN, params={"house_number": prog1["house_number"]}),
         "house_number", prog1["house_number"], 1),
        ("assets?waived_by_operator_id",
         api.list_assets(ADMIN, params={"waived_by_operator_id": scn["pd"]["id"]}),
         "waived_by_operator_id", scn["pd"]["id"], 0),
        ("qc-reports?asset_id",
         api.list_qc_reports(ADMIN, params={"asset_id": prog1["id"]}),
         "asset_id", prog1["id"], 1),
        ("qc-reports?inspected_by_operator_id",
         api.list_qc_reports(
             ADMIN, params={"inspected_by_operator_id": scn["qc"]["id"]}),
         "inspected_by_operator_id", scn["qc"]["id"], 4),
        ("qc-reports?basis",
         api.list_qc_reports(ADMIN, params={"basis": "INGEST"}),
         "basis", "INGEST", 4),
        ("qc-reports?include_superseded",
         api.list_qc_reports(ADMIN, params={"include_superseded": False}),
         None, None, None),
        ("playlist items?playout_status",
         api.list_playlist_items(playlist, ADMIN, params={"playout_status": "PLAYED"}),
         "playout_status", "PLAYED", 1),
        ("playlist items?clearance_status",
         api.list_playlist_items(playlist, ADMIN,
                                 params={"clearance_status": "CLEARED"}),
         "clearance_status", "CLEARED", None),
        ("playlist items?element_kind",
         api.list_playlist_items(playlist, ADMIN,
                                 params={"element_kind": "COMMERCIAL"}),
         "element_kind", "COMMERCIAL", 2),
        ("as-run?event_kind",
         api.get_playlist_as_run(playlist, ADMIN, params={"event_kind": "CUE"}),
         "event_kind", "CUE", 1),
        ("playlist-items?playlist_id",
         api.list_all_playlist_items(ADMIN, params={"playlist_id": playlist}),
         "playlist_id", playlist, 7),
        ("playlist-items?asset_id",
         api.list_all_playlist_items(ADMIN, params={"asset_id": spot}),
         "asset_id", spot, 2),
        ("playlist-items?spot_order_id",
         api.list_all_playlist_items(ADMIN, params={"spot_order_id": order}),
         "spot_order_id", order, 2),
        ("playlist-items?feed_window_id",
         api.list_all_playlist_items(
             ADMIN, params={"feed_window_id": scn["window"]["id"]}),
         "feed_window_id", scn["window"]["id"], None),
        ("playlist-items?replaces_item_id",
         api.list_all_playlist_items(ADMIN, params={"replaces_item_id": item1}),
         "replaces_item_id", item1, 0),
        ("playlist-items?playout_status",
         api.list_all_playlist_items(ADMIN, params={"playout_status": "SCHEDULED"}),
         "playout_status", "SCHEDULED", 6),
        ("overrides?channel_id",
         api.list_overrides(ADMIN, params={"channel_id": ch1}),
         "channel_id", ch1, 1),
        ("overrides?requested_by_operator_id",
         api.list_overrides(
             ADMIN, params={"requested_by_operator_id": scn["mco"]["id"]}),
         "requested_by_operator_id", scn["mco"]["id"], 1),
        ("overrides?authorized_by_operator_id",
         api.list_overrides(
             ADMIN, params={"authorized_by_operator_id": scn["pd"]["id"]}),
         "authorized_by_operator_id", scn["pd"]["id"], 0),
        ("overrides?state",
         api.list_overrides(ADMIN, params={"state": "PENDING"}),
         "state", "PENDING", 1),
        ("faults?channel_id (the channel that has one)",
         api.list_faults(ADMIN, params={"channel_id": ch1}),
         "channel_id", ch1, 1),
        ("faults?channel_id (the channel that has none)",
         api.list_faults(ADMIN, params={"channel_id": ch2}),
         "channel_id", ch2, 0),
        ("faults?transmitter_id",
         api.list_faults(ADMIN, params={"transmitter_id": tx}),
         None, None, None),
        ("faults?playlist_item_id",
         api.list_faults(ADMIN, params={"playlist_item_id": item1}),
         "playlist_item_id", item1, 0),
        ("faults?state",
         api.list_faults(ADMIN, params={"state": "DETECTED"}),
         "state", "DETECTED", 1),
        ("faults?severity",
         api.list_faults(ADMIN, params={"severity": "MINOR"}),
         "severity", "MINOR", 1),
        ("spot-orders?channel_id",
         api.list_spot_orders(ADMIN, params={"channel_id": ch1}),
         "channel_id", ch1, 1),
        ("spot-orders?status",
         api.list_spot_orders(ADMIN, params={"status": "OPEN"}),
         "status", "OPEN", 1),
        ("spot-orders?priority_class",
         api.list_spot_orders(ADMIN, params={"priority_class": "PREEMPTIBLE"}),
         "priority_class", "PREEMPTIBLE", 1),
    ]


def test_every_declared_query_filter_narrows_without_erroring(api):
    """Each filter §3 declares is accepted and every returned row satisfies it.

    PRD §3.2: "Channels can be listed narrowed by `multiplex_id`, by
    `parent_channel_id` to see the subchannels of a primary, by `posture` or by
    `air_status`; multiplexes can be listed narrowed by `transmitter_id`."
    §3.1, §3.3, §3.4, §3.5, §3.6, §3.7, §3.8 and §3.9 declare the rest in the
    same form.

    Design: Corner/endpoints/all_31_declared_query_filters_narrow_without_erroring_and_bad_enum_values_still_422
    """
    scn = _fully_populated_plant(api)

    for label, resp, field, value, expected in _declared_filters(api, scn):
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array", f"{label} must stay a list read"
        if field is not None:
            for row in data:
                assert row[field] == value, (
                    f"{label} returned a row whose {field} is {row[field]!r}"
                )
        if expected is not None:
            assert meta["total_count"] == expected, (
                f"{label} should match {expected} rows on this bench, "
                f"got {meta['total_count']}"
            )
            assert len(data) == expected


def test_as_run_bounds_exclude_entries_outside_the_interval(api):
    """from_utc and to_utc bound the log window they are given.

    PRD §3.6: "The log can be read for a whole playlist in `event_utc` order,
    narrowed by `event_kind` or bounded by `from_utc` and `to_utc`, and it can
    be read for a single element in `event_utc` order."

    Design: Corner/endpoints/all_31_declared_query_filters_narrow_without_erroring_and_bad_enum_values_still_422
    """
    scn = _rig_with_first_element_aired()
    playlist = scn["playlist"]["id"]

    everything, meta = validate_paginated(api.get_playlist_as_run(playlist, ADMIN))
    assert meta["total_count"] == 3

    later, meta_later = validate_paginated(
        api.get_playlist_as_run(playlist, ADMIN,
                                params={"from_utc": "2026-08-01T12:00:01Z"})
    )
    assert meta_later["total_count"] == 1, (
        "the cue and the start both sit at 12:00:00, strictly before the bound"
    )
    assert [row["event_kind"] for row in later] == ["END"]

    earlier, meta_earlier = validate_paginated(
        api.get_playlist_as_run(playlist, ADMIN,
                                params={"to_utc": "2026-08-01T12:29:59Z"})
    )
    assert meta_earlier["total_count"] == 2, "the end at 12:30:00 lies past the bound"
    assert [row["event_kind"] for row in earlier] == ["CUE", "START"]
    assert everything[-1]["event_kind"] == "END"


def test_a_filter_matching_nothing_returns_an_empty_page(api):
    """A filter that no row satisfies is an empty page, not a failure.

    PRD §2.3: "`total_count` (the number of records matching the query before
    pagination is applied)"

    Design: Corner/endpoints/all_31_declared_query_filters_narrow_without_erroring_and_bad_enum_values_still_422
    """
    plant = fx.setup_base_plant()

    for params in ({"severity": "CRITICAL"}, {"state": "RESOLVED"}):
        data, meta = validate_paginated(api.list_faults(ADMIN, params=params))
        assert data == [], f"no fault matches {params} on an untouched bench"
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

    data, meta = validate_paginated(
        api.list_assets(ADMIN, params={"status": "RETRACTED"})
    )
    assert data == [] and meta["total_count"] == 0
    assert plant["ch1"]["id"]


def test_an_illegal_enum_filter_value_is_rejected(api):
    """Enum-typed filters are matched case-sensitively against their literals.

    PRD §2.9: "Every enum-typed field must carry one of the exact literals
    below, matched case-sensitively; anything else yields
    `ERR_INVALID_ENUM_VALUE` (HTTP 422)."

    Design: Corner/endpoints/all_31_declared_query_filters_narrow_without_erroring_and_bad_enum_values_still_422
    """
    scn = fx.setup_on_air_playlist()

    validate_error(
        api.list_faults(ADMIN, params={"severity": "BLOCKER"}),
        "ERR_INVALID_ENUM_VALUE",
    )
    validate_error(
        api.list_assets(ADMIN, params={"status": "qc_passed"}),
        "ERR_INVALID_ENUM_VALUE",
    )
    validate_error(
        api.list_playlist_items(scn["playlist"]["id"], ADMIN,
                                params={"element_kind": "commercial"}),
        "ERR_INVALID_ENUM_VALUE",
    )
    validate_error(
        api.list_overrides(ADMIN, params={"state": "ACTIVE_NOW"}),
        "ERR_INVALID_ENUM_VALUE",
    )

    _data, meta = validate_paginated(
        api.list_playlist_items(scn["playlist"]["id"], ADMIN,
                                params={"element_kind": "COMMERCIAL"})
    )
    assert meta["total_count"] == 2, "the exact literal is the one that matches"


def test_an_unknown_identifier_filter_value_returns_an_empty_page(api):
    """A filter value naming no row is not the same as a missing path segment.

    PRD §2.7: "Body-reference resolution applies to channel creation, playlist
    ingest, traffic revision, element substitution, feed-window planning,
    override creation, override activation, fault reporting, spot-order
    creation, makegood placement, QC report submission and QC waiver signing."

    Design: Corner/endpoints/all_31_declared_query_filters_narrow_without_erroring_and_bad_enum_values_still_422
    """
    scn = fx.setup_on_air_playlist()

    data, meta = validate_paginated(
        api.list_all_playlist_items(ADMIN, params={"playlist_id": NON_EXISTENT_UUID})
    )
    assert data == [], "an unresolvable filter value simply matches nothing"
    assert meta["total_count"] == 0

    data, meta = validate_paginated(
        api.list_faults(ADMIN, params={"channel_id": NON_EXISTENT_UUID})
    )
    assert data == [] and meta["total_count"] == 0

    validate_error(
        api.list_playlist_items(NON_EXISTENT_UUID, ADMIN), "ERR_PLAYLIST_NOT_FOUND"
    )
    assert fx.read_playlist(scn["playlist"]["id"])["status"] == "ON_AIR"


# ===========================================================================
# The allocation patch
# ===========================================================================

def _patch_allocation(api, plant, channel_id, **fields):
    """PATCH one channel's demand with the multiplex version read right now."""
    version = fx.read_multiplex(plant["multiplex"]["id"])["version"]
    return api.patch_channel_allocation(
        channel_id,
        factories.allocation_patch_payload(version, **fields),
        plant["eng_headers"],
    )


def test_an_allocation_patch_changes_only_the_fields_it_supplies(api):
    """Supplying one demand field leaves the other three where they were.

    PRD §3.2: "Changing a channel's demand after admission is done by supplying
    `expected_multiplex_version` together with any of `requested_bitrate_kbps`,
    `floor_bitrate_kbps`, `priority_rank` or `pin_allocated_kbps`, and it
    re-runs the waterfall for the whole multiplex, not just for the channel
    named."

    Design: Corner/endpoints/patch_allocation_is_a_true_partial_update_whose_occ_token_belongs_to_the_parent
    """
    plant = fx.setup_base_plant()
    before = fx.read_channel(plant["ch1"]["id"])
    assert before["priority_rank"] == 1
    assert before["requested_bitrate_kbps"] == 16000
    assert before["floor_bitrate_kbps"] == 8000
    assert before["allocated_bitrate_kbps"] == 16000

    resp = _patch_allocation(api, plant, plant["ch1"]["id"], priority_rank=3)
    patched = validate_success(resp)
    assert resp.json()["response_type"] == "object", "the updated channel is returned"
    assert_channel(patched)

    assert patched["priority_rank"] == 3, "the supplied field is the one that moves"
    assert patched["requested_bitrate_kbps"] == 16000, "an omitted field is untouched"
    assert patched["floor_bitrate_kbps"] == 8000, "an omitted field is untouched"
    assert patched.get("pin_allocated_kbps") is None, "no pin was ever supplied"
    assert patched["version"] == before["version"] + 1
    assert patched["allocated_bitrate_kbps"] == 16000, (
        "ch1 still clears its floor first and still takes its whole weight share"
    )

    sibling = fx.read_channel(plant["ch2"]["id"])
    assert sibling["priority_rank"] == 2, "the sibling's own demand fields are untouched"
    assert sibling["allocated_bitrate_kbps"] == 6000

    mux = fx.read_multiplex(plant["multiplex"]["id"])
    assert mux["assigned_kbps"] == 22000
    assert mux["available_kbps"] == 16000
    assert mux["starved_channel_count"] == 0
    assert_bandwidth_conservation(mux)


def test_the_allocation_patch_token_is_the_parent_multiplex_version(api):
    """The version the patch must state belongs to the multiplex, not the channel.

    PRD §2.6: "Changing a channel's bitrate demand, floor, priority rank or
    pinned allocation requires `expected_multiplex_version` to equal the parent
    multiplex's current `version`, because the new allocation set supersedes the
    one the client based its request on. A mismatch is rejected with
    `ERR_STALE_MULTIPLEX_VERSION` and HTTP 412."

    Design: Corner/endpoints/patch_allocation_is_a_true_partial_update_whose_occ_token_belongs_to_the_parent
    """
    plant = fx.setup_base_plant()
    stale = fx.read_multiplex(plant["multiplex"]["id"])["version"]

    accepted = validate_success(
        api.patch_channel_allocation(
            plant["ch1"]["id"],
            factories.allocation_patch_payload(stale, requested_bitrate_kbps=12000),
            plant["eng_headers"],
        )
    )
    assert accepted["requested_bitrate_kbps"] == 12000
    assert accepted["allocated_bitrate_kbps"] == 12000, (
        "the remainder share is capped by the channel's own weight of 4000"
    )

    mux = fx.read_multiplex(plant["multiplex"]["id"])
    assert mux["assigned_kbps"] == 18000, "12000 for ch1 and 6000 for ch2"
    assert mux["available_kbps"] == 20000
    assert mux["version"] > stale, "the re-sliced pool superseded the client's view"

    replay = api.patch_channel_allocation(
        plant["ch1"]["id"],
        factories.allocation_patch_payload(stale, requested_bitrate_kbps=14000),
        plant["eng_headers"],
    )
    validate_error(replay, "ERR_STALE_MULTIPLEX_VERSION")
    assert fx.read_channel(plant["ch1"]["id"])["requested_bitrate_kbps"] == 12000

    channel_version = fx.read_channel(plant["ch1"]["id"])["version"]
    wrong_token = api.patch_channel_allocation(
        plant["ch1"]["id"],
        factories.allocation_patch_payload(channel_version,
                                           requested_bitrate_kbps=14000),
        plant["eng_headers"],
    )
    validate_error(wrong_token, "ERR_STALE_MULTIPLEX_VERSION")


def test_a_pin_up_to_the_free_space_is_accepted_and_one_kilobit_more_is_not(api):
    """The capacity gate is exact: the last legal pin is the one that just fits.

    PRD §3.2: "an explicit pin — `pin_allocated_kbps` on a demand change — or an
    admission that must be accepted as `ACTIVE` is refused with
    `ERR_MULTIPLEX_CAPACITY_EXCEEDED` when the resulting pinned total would
    exceed the multiplex's `effective_capacity_kbps`; a total exactly equal to
    the effective capacity is accepted."

    Design: Corner/endpoints/patch_allocation_is_a_true_partial_update_whose_occ_token_belongs_to_the_parent
    """
    plant = fx.setup_base_plant()
    mux = fx.read_multiplex(plant["multiplex"]["id"])
    assert mux["effective_capacity_kbps"] == 38000
    assert fx.read_channel(plant["ch2"]["id"])["floor_bitrate_kbps"] == 2000
    before = fx.read_channel(plant["ch1"]["id"])

    over = _patch_allocation(api, plant, plant["ch1"]["id"], pin_allocated_kbps=36001)
    validate_error(over, "ERR_MULTIPLEX_CAPACITY_EXCEEDED")

    after_refusal = fx.read_channel(plant["ch1"]["id"])
    assert after_refusal["version"] == before["version"], "a refused pin writes nothing"
    assert after_refusal.get("pin_allocated_kbps") is None
    assert fx.read_multiplex(plant["multiplex"]["id"])["version"] == mux["version"]

    pinned = validate_success(
        _patch_allocation(api, plant, plant["ch1"]["id"], pin_allocated_kbps=36000)
    )
    # PRD never declares pin_allocated_kbps as a channel response attribute; it
    # names it only as an input on the demand change. What the accepted pin is
    # observable through is the declared allocation figure: PRD 3.3 speaks of "a
    # channel whose allocation was pinned below its own floor", so the pin lands
    # in allocated_bitrate_kbps.
    assert pinned["allocated_bitrate_kbps"] == 36000, (
        "36000 for ch1 plus the 2000 ch2 must keep is exactly the 38000 pool"
    )
    assert_bandwidth_conservation(fx.read_multiplex(plant["multiplex"]["id"]))


def test_suspended_posture_outranks_the_capacity_gate_on_an_allocation_patch(api):
    """A patch that is both over capacity and aimed at a suspended channel says so.

    PRD §2.8: "**Suspended posture outranks capacity.** A request that is both
    blocked because the target channel's `posture` is `SUSPENDED` and over the
    multiplex's capacity receives `ERR_CHANNEL_SUSPENDED_POSTURE`, never
    `ERR_MULTIPLEX_CAPACITY_EXCEEDED`."

    Design: Corner/endpoints/patch_allocation_is_a_true_partial_update_whose_occ_token_belongs_to_the_parent
    """
    plant = fx.setup_base_plant()

    fx.change_power_state(plant, "OFF_AIR", reason="Antenna feedline replacement")
    dark = fx.read_channel(plant["ch1"]["id"])
    assert dark["posture"] == "SUSPENDED", "the off-air cascade suspends every channel"
    assert fx.read_multiplex(plant["multiplex"]["id"])["effective_capacity_kbps"] == 0

    blocked = _patch_allocation(api, plant, plant["ch1"]["id"],
                                pin_allocated_kbps=36001)
    validate_error(blocked, "ERR_CHANNEL_SUSPENDED_POSTURE")

    fx.change_power_state(plant, "FULL_POWER")
    lit = fx.read_channel(plant["ch1"]["id"])
    assert lit["posture"] != "SUSPENDED", "restoration recomputes the posture"
    assert fx.read_multiplex(plant["multiplex"]["id"])["effective_capacity_kbps"] == 38000

    over = _patch_allocation(api, plant, plant["ch1"]["id"],
                             pin_allocated_kbps=36001)
    validate_error(over, "ERR_MULTIPLEX_CAPACITY_EXCEEDED")


# ===========================================================================
# The rebalance
# ===========================================================================

# A subchannel that asks for a flat 20000 kbps and will not run below it fits
# inside the 38000 kbps pool at full licence — 8000 plus 20000 is 28000 — but not
# inside the 18600 kbps a halved derate leaves.
_HUNGRY_SUBCHANNEL = {"floor_bitrate_kbps": 20000, "requested_bitrate_kbps": 20000}


def test_a_derate_starves_the_channel_whose_floor_no_longer_fits(api):
    """The waterfall drops the last channel in rank order when the pool shrinks.

    PRD §3.2: "If the floor does not fit, the channel's `allocation_state`
    becomes `STARVED`, its `allocated_bitrate_kbps` is set to 0, and it is
    excluded from steps three through five entirely."

    Design: Corner/endpoints/rebalance_is_the_only_exit_from_starved_and_clear_pins_is_the_only_pin_eraser
    """
    plant = fx.setup_base_plant(ch2_overrides=_HUNGRY_SUBCHANNEL)
    full = fx.read_multiplex(plant["multiplex"]["id"])
    assert full["effective_capacity_kbps"] == 38000
    assert full["assigned_kbps"] == 36000, "16000 for ch1 and a flat 20000 for ch2"
    ch2_before = fx.read_channel(plant["ch2"]["id"])
    assert ch2_before["allocation_state"] == "ACTIVE"

    fx.change_power_state(plant, "REDUCED_POWER", power_pct=25)

    mux = validate_success(api.get_multiplex(plant["multiplex"]["id"], ADMIN))
    assert mux["effective_capacity_kbps"] == 18600, (
        "38800 halved truncates to 19400 and loses the 800 kbps pilot"
    )
    ch1 = fx.read_channel(plant["ch1"]["id"])
    ch2 = fx.read_channel(plant["ch2"]["id"])
    assert ch1["allocation_state"] == "ACTIVE"
    assert ch1["allocated_bitrate_kbps"] == 16000, (
        "its 8000 floor plus a share capped by its own 8000 weight"
    )
    assert ch2["allocation_state"] == "STARVED", (
        "8000 already granted plus the 20000 floor is 28000, past the 18600 pool"
    )
    assert ch2["allocated_bitrate_kbps"] == 0
    assert ch2["version"] > ch2_before["version"], (
        "a power change that starves a channel advances that channel's version"
    )
    assert mux["assigned_kbps"] == 16000
    assert mux["available_kbps"] == 2600, (
        "the 2600 kilobits no channel is still under its request for stay unassigned"
    )
    assert mux["starved_channel_count"] == 1
    assert_bandwidth_conservation(mux)


def test_only_a_re_run_of_the_waterfall_lets_a_starved_channel_recover(api):
    """A rebalance at unchanged capacity keeps it starved; restored power frees it.

    PRD §3.2: "**Rebalancing the multiplex is the only way a channel leaves
    `STARVED`** — starvation is never cleared by the channel itself, and a
    channel driven `STARVED` by a derate stays starved until either the
    multiplex is rebalanced or the transmitter's power is restored and the
    resulting cascade re-runs the waterfall."

    Design: Corner/endpoints/rebalance_is_the_only_exit_from_starved_and_clear_pins_is_the_only_pin_eraser
    """
    plant = fx.setup_base_plant(ch2_overrides=_HUNGRY_SUBCHANNEL)
    fx.change_power_state(plant, "REDUCED_POWER", power_pct=25)
    assert fx.read_channel(plant["ch2"]["id"])["allocation_state"] == "STARVED"

    version = fx.read_multiplex(plant["multiplex"]["id"])["version"]
    rebalanced = validate_success(
        api.rebalance_multiplex(plant["multiplex"]["id"],
                                {"expected_multiplex_version": version},
                                plant["eng_headers"])
    )
    assert_multiplex(rebalanced)
    assert rebalanced["effective_capacity_kbps"] == 18600, "the derate has not changed"
    assert rebalanced["starved_channel_count"] == 1, (
        "the starved channel re-enters the waterfall but its floor still does not fit"
    )
    assert fx.read_channel(plant["ch2"]["id"])["allocation_state"] == "STARVED"

    fx.change_power_state(plant, "FULL_POWER")
    ch2 = fx.read_channel(plant["ch2"]["id"])
    assert ch2["allocation_state"] == "ACTIVE", (
        "the restoration cascade re-runs the waterfall and the floor fits again"
    )
    assert ch2["allocated_bitrate_kbps"] == 20000, (
        "its floor equals its request, so it is an all-or-nothing claimant"
    )
    assert fx.read_channel(plant["ch1"]["id"])["allocated_bitrate_kbps"] == 16000
    restored = fx.read_multiplex(plant["multiplex"]["id"])
    assert restored["starved_channel_count"] == 0
    assert restored["assigned_kbps"] == 36000
    assert restored["available_kbps"] == 2000
    assert_bandwidth_conservation(restored)


def test_a_rebalance_states_the_multiplex_version_it_observed(api):
    """The rebalance token is the multiplex version, checked before anything else.

    PRD §2.6: "Re-running the bitrate waterfall across a multiplex requires
    `expected_multiplex_version` to equal that multiplex's current `version`. A
    rebalance legitimately supersedes the standing allocation set, so a
    stale-view writer would confirm an allocation it never observed. A mismatch
    is rejected with `ERR_STALE_MULTIPLEX_VERSION` and HTTP 412."

    Design: Corner/endpoints/rebalance_is_the_only_exit_from_starved_and_clear_pins_is_the_only_pin_eraser
    """
    plant = fx.setup_base_plant()
    stale = fx.read_multiplex(plant["multiplex"]["id"])["version"]

    validate_success(
        api.patch_channel_allocation(
            plant["ch1"]["id"],
            factories.allocation_patch_payload(stale, requested_bitrate_kbps=12000),
            plant["eng_headers"],
        )
    )
    current = fx.read_multiplex(plant["multiplex"]["id"])["version"]
    assert current != stale

    validate_error(
        api.rebalance_multiplex(plant["multiplex"]["id"],
                                {"expected_multiplex_version": stale},
                                plant["eng_headers"]),
        "ERR_STALE_MULTIPLEX_VERSION",
    )

    accepted = validate_success(
        api.rebalance_multiplex(plant["multiplex"]["id"],
                                {"expected_multiplex_version": current},
                                plant["eng_headers"])
    )
    assert accepted["assigned_kbps"] == 18000, "the standing demand is re-sliced as is"
    assert accepted["available_kbps"] == 20000
    assert_bandwidth_conservation(accepted)


def test_clear_pins_discards_the_pinned_allocation(api):
    """The rebalance's optional flag is what erases a pin.

    PRD §3.2: "Rebalancing is the blunter instrument: it supplies
    `expected_multiplex_version` and, optionally, `clear_pins` to discard any
    pinned allocations, and re-runs the waterfall across every channel on the
    multiplex."

    Design: Corner/endpoints/rebalance_is_the_only_exit_from_starved_and_clear_pins_is_the_only_pin_eraser
    """
    plant = fx.setup_base_plant()
    pinned = validate_success(
        _patch_allocation(api, plant, plant["ch1"]["id"], pin_allocated_kbps=36000)
    )
    assert pinned["allocated_bitrate_kbps"] == 36000

    version = fx.read_multiplex(plant["multiplex"]["id"])["version"]
    cleared = validate_success(
        api.rebalance_multiplex(
            plant["multiplex"]["id"],
            {"expected_multiplex_version": version, "clear_pins": True},
            plant["eng_headers"],
        )
    )

    ch1 = fx.read_channel(plant["ch1"]["id"])
    assert ch1.get("pin_allocated_kbps") is None, "clear_pins discards the pin itself"
    assert ch1["allocated_bitrate_kbps"] == 16000, (
        "with no pin left the waterfall returns ch1 to its whole request"
    )
    assert fx.read_channel(plant["ch2"]["id"])["allocated_bitrate_kbps"] == 6000
    assert cleared["assigned_kbps"] == 22000
    assert cleared["available_kbps"] == 16000
    assert_bandwidth_conservation(cleared)


# ===========================================================================
# Substitution
# ===========================================================================

def _rig_with_substitute_assets():
    """The canonical day on air, plus four graded assets held back as replacements.

    The replacements are registered and graded before the day goes to air so each
    one lands inside its own delivery window; only then is the clock moved up to
    one minute before the first element.
    """
    scn = fx.setup_playlist_scenario()
    scn["sub_ok"] = fx.setup_qc_passed_asset(scn, 60)
    scn["sub_sd"] = fx.setup_qc_passed_asset(
        scn, 60, asset_overrides={"required_resolution_class": "SD_480I"}
    )
    scn["sub_long"] = fx.setup_qc_passed_asset(scn, 100)
    scn["sub_spot"] = fx.setup_qc_passed_asset(scn, 30)
    return fx.drive_playlist_to_on_air(scn)


def test_a_replacement_of_the_wrong_delivered_resolution_is_refused(api):
    """The replacement must have been delivered in the resolution the slot needs.

    PRD §3.6: "The replacement asset's `delivered_resolution_class` must equal
    the outgoing element's asset's `required_resolution_class`, and the
    replacement's `measured_duration_seconds` must lie within the outgoing
    element's `max_trim_seconds` of the outgoing `scheduled_duration_seconds`;
    either failure is refused with `ERR_SUBSTITUTE_RESOLUTION_MISMATCH`."

    Design: Corner/endpoints/substitute_defaults_to_the_outgoing_duration_and_rule_57_swallows_the_duration_window
    """
    scn = _rig_with_substitute_assets()
    promo = item_by_sequence(scn["items"], 5)
    assert promo["max_trim_seconds"] == 30
    assert promo["scheduled_duration_seconds"] == 60

    resp = api.substitute_item(
        promo["id"],
        factories.substitute_payload(scn["sub_sd"]["id"]),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_SUBSTITUTE_RESOLUTION_MISMATCH")

    after = fx.read_item(promo["id"])
    assert after["playout_status"] == "SCHEDULED", "a refused substitution skips nothing"
    assert after["version"] == promo["version"]
    assert fx.list_item_as_run(promo["id"]) == [], "and appends no as-run entry"


def test_a_replacement_of_the_wrong_natural_length_reports_the_same_code(api):
    """A length outside the trim allowance is the same refusal as a resolution clash.

    PRD §3.6: "the replacement's `measured_duration_seconds` must lie within the
    outgoing element's `max_trim_seconds` of the outgoing
    `scheduled_duration_seconds`; either failure is refused with
    `ERR_SUBSTITUTE_RESOLUTION_MISMATCH`."

    Design: Corner/endpoints/substitute_defaults_to_the_outgoing_duration_and_rule_57_swallows_the_duration_window
    """
    scn = _rig_with_substitute_assets()
    promo = item_by_sequence(scn["items"], 5)
    assert scn["sub_long"]["expected_duration_seconds"] == 100, (
        "the long replacement was delivered and graded at its booked 100 seconds"
    )

    resp = api.substitute_item(
        promo["id"],
        factories.substitute_payload(scn["sub_long"]["id"]),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_SUBSTITUTE_RESOLUTION_MISMATCH")
    assert fx.read_item(promo["id"])["playout_status"] == "SCHEDULED"

    inside = validate_success(
        api.substitute_item(
            promo["id"],
            factories.substitute_payload(scn["sub_ok"]["id"]),
            scn["mco_headers"],
        ),
        201,
    )
    assert inside["asset_id"] == scn["sub_ok"]["id"], (
        "60 seconds is within 30 of the outgoing 60, so this one lands"
    )


def test_an_explicit_duration_beyond_the_trim_allowance_is_refused(api):
    """The trim the substitution applies is bounded by the element's own allowance.

    PRD §3.6: "Any trim the substitution applies must satisfy the element's own
    `trim_applied_seconds` not exceeding its `max_trim_seconds`, otherwise
    `ERR_TRIM_EXCEEDS_MAX`; **a trim exactly equal to `max_trim_seconds` is
    accepted**"

    Design: Corner/endpoints/substitute_defaults_to_the_outgoing_duration_and_rule_57_swallows_the_duration_window
    """
    scn = _rig_with_substitute_assets()
    promo = item_by_sequence(scn["items"], 5)

    resp = api.substitute_item(
        promo["id"],
        factories.substitute_payload(scn["sub_ok"]["id"],
                                     scheduled_duration_seconds=29),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_TRIM_EXCEEDS_MAX")
    assert fx.read_item(promo["id"])["playout_status"] == "SCHEDULED"


def test_a_trim_at_the_allowance_still_has_to_leave_a_contiguous_timeline(api):
    """The largest legal trim opens a hole the integrity pass then refuses.

    PRD §3.5: "if the next element's `scheduled_start_utc` is *after* that end
    there is a hole and the pass fails with `ERR_SCHEDULE_GAP_DETECTED` — **a
    one-second hole is a gap**"

    Design: Corner/endpoints/substitute_defaults_to_the_outgoing_duration_and_rule_57_swallows_the_duration_window
    """
    scn = _rig_with_substitute_assets()
    promo = item_by_sequence(scn["items"], 5)
    following = item_by_sequence(scn["items"], 6)
    assert following["scheduled_start_utc"] == "2026-08-01T12:37:00Z"

    resp = api.substitute_item(
        promo["id"],
        factories.substitute_payload(scn["sub_ok"]["id"],
                                     scheduled_duration_seconds=30),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_SCHEDULE_GAP_DETECTED")

    assert fx.read_item(promo["id"])["playout_status"] == "SCHEDULED", (
        "the failed integrity pass leaves the outgoing element in place"
    )
    assert len(fx.list_items(scn["playlist"]["id"], scn["mco_headers"])) == 7


def test_a_substitution_without_a_duration_keeps_the_outgoing_length(api):
    """Omitting the duration leaves the slot exactly as long as it was.

    PRD §3.6: "A `MasterControlOperator` or `ProgramDirector` may replace a
    scheduled or cued element with a different asset — a late delivery, a QC
    failure, a rights pull — by naming the `replacement_asset_id` and optionally
    a new `scheduled_duration_seconds` and a `reason`."

    Design: Corner/endpoints/substitute_defaults_to_the_outgoing_duration_and_rule_57_swallows_the_duration_window
    """
    scn = _rig_with_substitute_assets()
    promo = item_by_sequence(scn["items"], 5)

    resp = api.substitute_item(
        promo["id"],
        factories.substitute_payload(scn["sub_ok"]["id"], reason="Late delivery"),
        scn["mco_headers"],
    )
    created = validate_success(resp, 201)
    assert_playlist_item(created)
    assert created["scheduled_duration_seconds"] == 60, (
        "no new duration was named, so the outgoing 60 seconds stands"
    )
    assert created["scheduled_start_utc"] == "2026-08-01T12:36:00Z", (
        "the timeline pass that follows only succeeds if the slot is unmoved"
    )
    assert created["replaces_item_id"] == promo["id"]
    assert created["clearance_status"] == "CLEARED", (
        "the clearance comes from the QC_PASSED replacement"
    )
    assert created["asset_id"] == scn["sub_ok"]["id"]

    outgoing = fx.read_item(promo["id"])
    assert outgoing["playout_status"] == "SKIPPED"
    assert [row["event_kind"] for row in fx.list_item_as_run(promo["id"])] == ["SKIP"]

    day = fx.read_playlist(scn["playlist"]["id"])
    assert day["projected_end_variance_seconds"] == 0, (
        "the replacement fills exactly the seconds the outgoing element held"
    )


def test_a_commercial_element_carries_no_trim_allowance(api):
    """A commercial slot may be replaced but never shortened.

    PRD §3.6: "commercial elements always carry a `max_trim_seconds` of 0 so
    they are never trimmable."

    Design: Corner/endpoints/substitute_defaults_to_the_outgoing_duration_and_rule_57_swallows_the_duration_window
    """
    scn = _rig_with_substitute_assets()
    spot = item_by_sequence(scn["items"], 2)
    assert spot["element_kind"] == "COMMERCIAL"
    assert spot["max_trim_seconds"] == 0
    assert spot["scheduled_duration_seconds"] == 30

    validate_error(
        api.substitute_item(
            spot["id"],
            factories.substitute_payload(scn["sub_spot"]["id"],
                                         scheduled_duration_seconds=29),
            scn["mco_headers"],
        ),
        "ERR_TRIM_EXCEEDS_MAX",
    )

    created = validate_success(
        api.substitute_item(
            spot["id"],
            factories.substitute_payload(scn["sub_spot"]["id"]),
            scn["mco_headers"],
        ),
        201,
    )
    assert created["scheduled_duration_seconds"] == 30, (
        "a zero trim is the only trim a commercial accepts"
    )
    assert created["element_kind"] == "COMMERCIAL"
    assert fx.read_item(spot["id"])["playout_status"] == "SKIPPED"


# ===========================================================================
# The ops-run checkpoint
# ===========================================================================

_OPS_T0 = "2026-08-01T09:00:00Z"
_OPS_ADVANCE = "2026-08-02T12:00:01Z"


def _rig_for_the_checkpoint():
    """One bench carrying a ripe candidate for each of the five sweeps.

    At 09:00:00Z the plant reduces to 79 percent — below the 80 percent filing
    threshold, so a POWER_REDUCTION obligation falls due at 09:00:00Z the next
    day — and then goes off air, opening an outage epoch at the same instant. The
    bench also holds an asset still merely expected against a 10:00:00Z deadline,
    a MINOR fault detected at 09:00:00Z and an operator whose certification lapses
    at midnight.
    """
    plant = fx.setup_base_plant(with_subchannel=False, clock_utc=_OPS_T0)
    plant["short_cert"] = fx.create_operator(
        "MASTER_CONTROL", "NONE", "2026-08-02T00:00:00Z", full_name="Eve Nairn"
    )
    plant["asset"] = fx.create_asset(plant)
    plant["fault"] = fx.report_channel_fault(plant, "CAPTION_LOSS", "MINOR", _OPS_T0)
    fx.change_power_state(plant, "REDUCED_POWER", power_pct=79)
    plant["transmitter"] = fx.change_power_state(
        plant, "OFF_AIR", reason="Antenna feed line failure in the storm"
    )
    assert plant["transmitter"]["operational_state"] == "OFF_AIR"
    assert plant["transmitter"]["outage_started_utc"] == _OPS_T0
    return plant


def _notifications_by_kind(plant):
    rows = fx.list_notifications(plant["transmitter"]["id"])
    return {row["kind"]: row for row in rows}, rows


def test_nothing_expires_escalates_or_clears_until_the_clock_moves(api):
    """Every candidate sits untouched for as long as the clock stands still.

    PRD §2.4: "Advancing the clock is also the system's **ops-run checkpoint**,
    and it is the only mechanism by which anything expires. There are no
    background jobs."

    Design: Corner/endpoints/one_clock_advance_runs_checkpoints_a_to_e_in_the_pinned_order_and_nothing_else_ever_sweeps
    """
    plant = _rig_for_the_checkpoint()

    for _round in range(3):
        by_kind, rows = _notifications_by_kind(plant)
        assert list(by_kind) == ["POWER_REDUCTION"], (
            "sweep one has not run, so no OUTAGE obligation exists yet"
        )
        assert len(rows) == 1
        assert by_kind["POWER_REDUCTION"]["status"] == "PENDING"
        assert by_kind["POWER_REDUCTION"]["due_utc"] == "2026-08-02T09:00:00Z"
        assert by_kind["POWER_REDUCTION"]["observed_power_pct"] == 79
        assert by_kind["POWER_REDUCTION"]["outage_seconds"] is None

        assert fx.read_asset(plant["asset"]["id"])["status"] == "EXPECTED"
        assert fx.read_fault(plant["fault"]["id"])["state"] == "DETECTED"
        assert fx.read_operator(plant["short_cert"]["id"])["certification_state"] == "VALID"
        transmitter = fx.read_transmitter(plant["transmitter"]["id"])
        assert transmitter["notification_pending_count"] == 1
        assert transmitter["operational_state"] == "OFF_AIR"


def test_one_advance_runs_all_five_sweeps_in_the_same_call(api):
    """A single accepted advance files, escalates, expires, clears and re-derives.

    PRD §2.4: "When the advance is accepted, the checkpoint performs five sweeps
    in this pinned order, and the order matters because an earlier sweep can
    create rows that a later sweep then evaluates within the same call"

    Design: Corner/endpoints/one_clock_advance_runs_checkpoints_a_to_e_in_the_pinned_order_and_nothing_else_ever_sweeps
    """
    plant = _rig_for_the_checkpoint()
    far_cert = plant["mco"]["id"]

    validate_success(api.set_clock(_OPS_ADVANCE, ADMIN))

    by_kind, rows = _notifications_by_kind(plant)
    assert len(rows) == 2, "sweep one added the outage obligation to the power filing"

    outage = by_kind["OUTAGE"]
    assert_regulatory_notification(outage)
    assert outage["status"] == "PENDING", "the new obligation is born awaiting filing"
    assert outage["triggering_utc"] == _OPS_T0, "the epoch is keyed on the outage start"
    assert outage["due_utc"] == "2026-08-03T12:00:01Z", (
        "the outage filing falls due 24 hours after the new clock instant"
    )
    assert outage["observed_power_pct"] is None, "power percent is a POWER_REDUCTION field"
    assert outage["outage_seconds"] == 97201, (
        "the elapsed seconds observed at detection, 09:00:00Z to 12:00:01Z the next day"
    )

    assert by_kind["POWER_REDUCTION"]["status"] == "OVERDUE", (
        "sweep two moved the filing whose due instant is now in the past"
    )

    assert fx.read_transmitter(plant["transmitter"]["id"])["notification_pending_count"] == 2, (
        "PENDING and OVERDUE rows both count as pending filings"
    )

    assert fx.read_asset(plant["asset"]["id"])["status"] == "EXPIRED", (
        "sweep three expired the asset whose delivery grace has elapsed"
    )

    cleared = fx.read_fault(plant["fault"]["id"])
    assert cleared["state"] == "AUTO_CLEARED", (
        "sweep four aged out the unacknowledged MINOR fault"
    )
    assert cleared["cleared_utc"] == _OPS_ADVANCE, (
        "the auto-clear stamps the current logical time"
    )

    assert fx.read_operator(plant["short_cert"]["id"])["certification_state"] == "EXPIRED", (
        "sweep five re-derived the lapsed certification"
    )
    assert fx.read_operator(far_cert)["certification_state"] == "VALID", (
        "an operator certified beyond the new instant is untouched"
    )


def test_the_same_instant_cannot_be_replayed_and_a_later_one_repeats_nothing(api):
    """The clock only moves strictly forward and the outage epoch files once.

    PRD §2.4: "A clock advance must move strictly forward: a request whose
    `current_utc` equals or precedes the present clock value is rejected with
    `ERR_CLOCK_NOT_MONOTONIC`."

    PRD §3.1: "Exactly one `OUTAGE` row is ever created per outage epoch; the
    epoch is keyed on `outage_started_utc` and a second row for the same epoch is
    never created."

    Design: Corner/endpoints/one_clock_advance_runs_checkpoints_a_to_e_in_the_pinned_order_and_nothing_else_ever_sweeps
    """
    plant = _rig_for_the_checkpoint()
    validate_success(api.set_clock(_OPS_ADVANCE, ADMIN))
    first_pass, _rows = _notifications_by_kind(plant)
    fault_after_first = fx.read_fault(plant["fault"]["id"])

    validate_error(api.set_clock(_OPS_ADVANCE, ADMIN), "ERR_CLOCK_NOT_MONOTONIC")
    validate_error(api.set_clock(_OPS_T0, ADMIN), "ERR_CLOCK_NOT_MONOTONIC")

    validate_success(api.set_clock("2026-08-02T13:00:00Z", ADMIN))

    by_kind, rows = _notifications_by_kind(plant)
    assert len(rows) == 2, "the second advance opens no second row for the same epoch"
    assert by_kind["OUTAGE"]["id"] == first_pass["OUTAGE"]["id"]
    assert by_kind["OUTAGE"]["outage_seconds"] == first_pass["OUTAGE"]["outage_seconds"], (
        "the elapsed figure was frozen at detection"
    )
    assert by_kind["OUTAGE"]["due_utc"] == first_pass["OUTAGE"]["due_utc"]
    assert by_kind["POWER_REDUCTION"]["status"] == "OVERDUE"

    fault = fx.read_fault(plant["fault"]["id"])
    assert fault["state"] == "AUTO_CLEARED"
    assert fault["cleared_utc"] == fault_after_first["cleared_utc"], (
        "an already terminal fault is not re-cleared"
    )
    assert fault["version"] == fault_after_first["version"]


# ===========================================================================
# What a write returns
# ===========================================================================

def test_submitting_an_inspection_returns_the_report_not_the_asset(api):
    """The grading call answers with the new report and leaves the asset to be read.

    PRD §4: "Endpoints that create a new resource return HTTP 201; endpoints that
    modify, drive or read an existing resource return HTTP 200."

    Design: Corner/endpoints/writes_return_14_created_and_17_ok_and_five_of_them_return_a_different_entity_than_their_path
    """
    plant = fx.setup_base_plant(with_subchannel=False)
    asset = fx.create_asset(plant)
    delivered = fx.deliver_asset(plant, asset["id"])

    resp = api.submit_qc_report(
        asset["id"],
        factories.qc_report_payload(delivered["version"], plant["qc"]["id"]),
        plant["qc_headers"],
    )
    report = validate_success(resp, 201)
    assert_qc_report(report)
    assert report["asset_id"] == asset["id"]
    assert report["basis"] == "INGEST"
    assert report["verdict"] == "PASS"
    assert report["technical_score"] == 100
    assert "status" not in report, "the report is not the asset"

    graded = fx.read_asset(asset["id"])
    assert graded["status"] == "QC_PASSED", "the asset moved, but it is read separately"
    assert graded["version"] > delivered["version"]


def test_a_playout_event_returns_the_as_run_entry_not_the_element(api):
    """Reporting a cue answers with the log row it appended.

    PRD §4: "Note that a playout event, a substitution and a makegood each create
    a new resource — an as-run entry and playlist elements respectively — and
    therefore return 201 even though they read as commands rather than as
    registrations."

    Design: Corner/endpoints/writes_return_14_created_and_17_ok_and_five_of_them_return_a_different_entity_than_their_path
    """
    scn = fx.setup_on_air_playlist()
    item1 = item_by_sequence(scn["items"], 1)
    house_number = fx.read_asset(scn["assets"]["prog1"]["id"])["house_number"]
    fx.set_clock(_ITEM1_START)

    resp = api.post_playout_event(
        item1["id"],
        factories.playout_event_payload("CUE", _ITEM1_START),
        scn["mco_headers"],
    )
    entry = validate_success(resp, 201)
    assert_as_run_entry(entry)
    assert entry["playlist_item_id"] == item1["id"]
    assert entry["playlist_id"] == scn["playlist"]["id"]
    assert entry["event_kind"] == "CUE"
    assert entry["event_utc"] == _ITEM1_START
    assert entry["measured_duration_seconds"] == 0
    assert entry["source"] == "AUTOMATION"
    assert entry["sequence_number"] == 1, "the entry snapshots the element's number"
    assert entry["element_kind"] == "PROGRAM"
    assert entry["house_number"] == house_number
    assert entry["recorded_by_user_id"] == scn["mco"]["id"]
    assert "playout_status" not in entry, "the entry is not the element"

    cued = fx.read_item(item1["id"])
    assert cued["playout_status"] == "CUED", "the element moved, but it is read separately"

    per_item = fx.list_item_as_run(item1["id"])
    assert [row["id"] for row in per_item] == [entry["id"]]
    whole_day = fx.list_as_run(scn["playlist"]["id"])
    assert [row["id"] for row in whole_day] == [entry["id"]], (
        "both as-run readers see the one entry the event appended"
    )


def test_the_driving_endpoints_answer_with_the_resource_in_their_own_path(api):
    """Air state, playlist state, fault state and a waiver all return 200 and their own entity.

    PRD §4: "endpoints that modify, drive or read an existing resource return
    HTTP 200."

    Design: Corner/endpoints/writes_return_14_created_and_17_ok_and_five_of_them_return_a_different_entity_than_their_path
    """
    scn = fx.setup_playlist_scenario()

    channel = validate_success(
        api.change_channel_air_state(
            scn["ch1"]["id"], factories.air_state_payload("ON_AIR"), scn["mco_headers"]
        )
    )
    assert_channel(channel)
    assert channel["id"] == scn["ch1"]["id"]
    assert channel["air_status"] == "ON_AIR"

    playlist = validate_success(
        api.change_playlist_state(
            scn["playlist"]["id"], {"target_status": "VALIDATED"}, scn["pd_headers"]
        )
    )
    assert_playlist(playlist)
    assert playlist["id"] == scn["playlist"]["id"]
    assert playlist["status"] == "VALIDATED"

    reported = fx.report_channel_fault(scn, "AUDIO_LOSS", "MAJOR", "2026-08-01T09:00:00Z")
    fault = validate_success(
        api.change_fault_state(
            reported["id"], factories.fault_state_payload("ACKNOWLEDGED"),
            scn["mco_headers"],
        )
    )
    assert_technical_fault(fault)
    assert fault["id"] == reported["id"]
    assert fault["state"] == "ACKNOWLEDGED"

    failed = fx.setup_qc_failed_asset(scn, 600)
    assert failed["status"] == "QC_FAILED"
    waived = validate_success(
        api.sign_qc_waiver(
            failed["id"], factories.qc_waiver_payload(scn["pd"]["id"]), scn["pd_headers"]
        )
    )
    assert_asset(waived)
    assert waived["id"] == failed["id"]
    assert waived["status"] == "QC_WAIVED"


def test_placing_a_makegood_returns_the_new_element_not_the_order(api):
    """The compensating placement answers with the element it created.

    PRD §3.9: "A successful makegood creates a playlist element with
    `is_makegood` set to true, `element_kind` `COMMERCIAL`, and `replaces_item_id`
    pointing at the credited element, in `playout_status` `SCHEDULED`."

    Design: Corner/endpoints/writes_return_14_created_and_17_ok_and_five_of_them_return_a_different_entity_than_their_path
    """
    scn = fx.setup_on_air_playlist()
    spot = item_by_sequence(scn["items"], 2)
    fx.skip_item(scn, spot["id"], "2026-08-01T11:59:00Z")

    credited = fx.read_order(scn["order"]["id"])
    assert credited["credited_spots"] == 1
    assert credited["scheduled_spots"] == 1
    assert credited["credit_accrued_cents"] == 100000
    assert credited["status"] == "PARTIALLY_CREDITED"

    # The replacement lands in the next broadcast day rather than in the day the
    # skip left a hole in, because the placement "re-runs the timeline integrity
    # pass" over its target and the skipped element's slot in the on-air day is
    # unfillable at sequence 8. The tail of the second day takes it exactly.
    tail_programme = fx.setup_qc_passed_asset(scn, 1770)
    next_day = fx.ingest(
        scn,
        [{"sequence_number": 1, "element_kind": "PROGRAM",
          "asset_id": tail_programme["id"],
          "scheduled_start_utc": "2026-08-02T13:00:00Z",
          "scheduled_duration_seconds": 1770}],
        broadcast_day="2026-08-02",
        schedule_start_utc="2026-08-02T13:00:00Z",
        window_duration_seconds=1800,
    )
    resp = api.place_makegood(
        scn["order"]["id"],
        factories.makegood_payload(next_day["id"], next_day["version"], 2,
                                   "2026-08-02T13:29:30Z",
                                   scheduled_duration_seconds=30),
        TRAFFIC,
    )
    placed = validate_success(resp, 201)
    assert_playlist_item(placed)
    assert placed["is_makegood"] is True
    assert placed["element_kind"] == "COMMERCIAL"
    assert placed["replaces_item_id"] == spot["id"]
    assert placed["playout_status"] == "SCHEDULED"
    assert placed["sequence_number"] == 2
    assert placed["spot_order_id"] == scn["order"]["id"]
    assert "advertiser_name" not in placed, "the element is not the order"

    settled = fx.read_order(scn["order"]["id"])
    assert settled["credited_spots"] == 0, "one spot moved back out of credit"
    assert settled["scheduled_spots"] == 2
    assert settled["credit_accrued_cents"] == 0, (
        "exactly the credit that spot had accrued was subtracted"
    )
    assert settled["status"] == "OPEN", (
        "every credited spot now has a makegood, so the order moves back to OPEN"
    )
    assert settled["version"] > credited["version"]


# ===========================================================================
# The operator status patch
# ===========================================================================

_CERT_LAPSED = "2026-08-01T08:00:00Z"
_CERT_EXTENDED = "2026-08-01T18:00:00Z"


def test_an_extension_in_the_same_call_re_derives_a_live_certification(api):
    """The operator blocked one moment may act the next, with the clock unmoved.

    PRD §3.3: "A `StationAdmin` may later suspend or reinstate an operator, or
    extend their certification, by supplying any of `status`,
    `certification_expires_utc` or `override_authority`; each such change
    re-derives `certification_state`."

    Design: Corner/endpoints/operator_status_is_a_three_optional_field_patch_whose_certification_edit_bypasses_the_clock
    """
    plant = fx.setup_base_plant(with_subchannel=False)
    # The probe is the drop to BARS_AND_TONE, which PRD 3.3 declares reachable
    # from ON_AIR only, so the channel is lit first by an unimpaired operator.
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    lapsed = fx.create_operator("MASTER_CONTROL", "NONE", _CERT_LAPSED,
                               full_name="Fay Oduya")
    assert lapsed["certification_state"] == "EXPIRED", (
        "the clock already stands past this expiry, so the record is born expired"
    )
    headers = make_master_control_headers(lapsed["id"])
    bars = factories.air_state_payload("BARS_AND_TONE")

    validate_error(
        api.change_channel_air_state(plant["ch1"]["id"], bars, headers),
        "ERR_OPERATOR_CERTIFICATION_EXPIRED",
    )
    assert fx.read_channel(plant["ch1"]["id"])["air_status"] == "ON_AIR"

    extended = validate_success(
        api.update_operator_status(
            lapsed["id"], {"certification_expires_utc": _CERT_EXTENDED}, ADMIN
        )
    )
    assert_operator(extended)
    assert extended["certification_expires_utc"] == _CERT_EXTENDED
    assert extended["certification_state"] == "VALID", (
        "the edit re-derived the state without the clock moving"
    )
    assert extended["status"] == "ACTIVE", "an unsupplied field is left alone"
    assert extended["version"] == lapsed["version"] + 1

    channel = validate_success(
        api.change_channel_air_state(plant["ch1"]["id"], bars, headers)
    )
    assert channel["air_status"] == "BARS_AND_TONE", (
        "the same air-critical mutation now passes the certification gate"
    )


def test_a_status_only_edit_leaves_the_certification_where_it_was(api):
    """Suspending and reinstating touches neither the expiry nor the authority.

    PRD §2.1: "A suspended operator — one whose `status` is `SUSPENDED` rather
    than `ACTIVE` — is refused every mutating request with
    `ERR_OPERATOR_SUSPENDED`, while read endpoints remain available to them."

    Design: Corner/endpoints/operator_status_is_a_three_optional_field_patch_whose_certification_edit_bypasses_the_clock
    """
    plant = fx.setup_base_plant(with_subchannel=False)
    operator = fx.create_operator("MASTER_CONTROL", "CRAWL_ONLY", _CERT_EXTENDED,
                                  full_name="Gil Prasad")
    headers = make_master_control_headers(operator["id"])

    suspended = validate_success(
        api.update_operator_status(operator["id"], {"status": "SUSPENDED"}, ADMIN)
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["certification_expires_utc"] == _CERT_EXTENDED
    assert suspended["certification_state"] == "VALID", (
        "suspension is not expiry; the re-derivation reads the untouched expiry"
    )
    assert suspended["override_authority"] == "CRAWL_ONLY"
    assert suspended["version"] == operator["version"] + 1

    validate_error(
        api.change_channel_air_state(
            plant["ch1"]["id"], factories.air_state_payload("BARS_AND_TONE"), headers
        ),
        "ERR_OPERATOR_SUSPENDED",
    )
    assert validate_success(api.get_operator(operator["id"], headers))["id"] == operator["id"], (
        "reads stay open to a suspended operator"
    )

    reinstated = validate_success(
        api.update_operator_status(operator["id"], {"status": "ACTIVE"}, ADMIN)
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["certification_expires_utc"] == _CERT_EXTENDED
    assert reinstated["version"] == suspended["version"] + 1


def test_three_fields_supplied_at_once_advance_the_record_by_one(api):
    """One call carrying every optional field is still one mutation.

    PRD §2.5: "`version` starts at 1 when a record is created and increments by
    exactly one on every mutation of that record"

    Design: Corner/endpoints/operator_status_is_a_three_optional_field_patch_whose_certification_edit_bypasses_the_clock
    """
    fx.setup_base_plant(with_subchannel=False)
    operator = fx.create_operator("PROGRAM_DIRECTOR", "CRAWL_ONLY", _CERT_LAPSED,
                                  full_name="Hana Reyes")
    assert operator["version"] == 1
    assert operator["certification_state"] == "EXPIRED"

    amended = validate_success(
        api.update_operator_status(
            operator["id"],
            {
                "status": "SUSPENDED",
                "certification_expires_utc": _CERT_EXTENDED,
                "override_authority": "FULL",
            },
            ADMIN,
        )
    )
    assert amended["status"] == "SUSPENDED"
    assert amended["certification_expires_utc"] == _CERT_EXTENDED
    assert amended["override_authority"] == "FULL"
    assert amended["certification_state"] == "VALID"
    assert amended["version"] == 2, "three fields in one request is one increment"
    assert amended["full_name"] == "Hana Reyes", "the unsupplied fields are untouched"
    assert amended["role_class"] == "PROGRAM_DIRECTOR"


def test_backdating_the_expiry_expires_the_certification_on_the_spot(api):
    """The patch can retire a certification without the clock moving at all.

    PRD §3.3: "`certification_state` is never supplied: it reads `VALID` while the
    logical clock is at or before `certification_expires_utc` and `EXPIRED` once
    the clock has passed it, so **an expiry instant exactly equal to the current
    logical time is still valid and one second later is expired**."

    Design: Corner/endpoints/operator_status_is_a_three_optional_field_patch_whose_certification_edit_bypasses_the_clock
    """
    plant = fx.setup_base_plant(with_subchannel=False)
    operator = fx.create_operator("MASTER_CONTROL", "NONE", _CERT_EXTENDED,
                                  full_name="Ivo Lund")
    headers = make_master_control_headers(operator["id"])
    # Each probe is a different air-critical mutation, because PRD 3.3's reachable
    # moves carry no self-loop: DARK -> ON_AIR, then ON_AIR -> BARS_AND_TONE, then
    # the refused BARS_AND_TONE -> ON_AIR return.
    lighting = factories.air_state_payload("ON_AIR")
    bars = factories.air_state_payload("BARS_AND_TONE")

    assert validate_success(
        api.change_channel_air_state(plant["ch1"]["id"], lighting, headers)
    )["air_status"] == "ON_AIR"

    on_the_boundary = validate_success(
        api.update_operator_status(
            operator["id"], {"certification_expires_utc": "2026-08-01T09:00:00Z"}, ADMIN
        )
    )
    assert on_the_boundary["certification_state"] == "VALID", (
        "an expiry exactly at the current logical instant is still live"
    )
    assert validate_success(
        api.change_channel_air_state(plant["ch1"]["id"], bars, headers)
    )["air_status"] == "BARS_AND_TONE"

    backdated = validate_success(
        api.update_operator_status(
            operator["id"], {"certification_expires_utc": "2026-08-01T08:59:59Z"}, ADMIN
        )
    )
    assert backdated["certification_state"] == "EXPIRED", (
        "one second before the clock is expired, and no sweep was needed to say so"
    )
    validate_error(
        api.change_channel_air_state(plant["ch1"]["id"], lighting, headers),
        "ERR_OPERATOR_CERTIFICATION_EXPIRED",
    )
