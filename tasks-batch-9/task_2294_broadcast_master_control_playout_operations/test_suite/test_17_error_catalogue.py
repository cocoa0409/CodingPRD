"""The error catalogue of §5: one identifier per condition, at its pinned status.

PRD §5 pins an HTTP status against every error identifier and §2.8 fixes the
order in which the checks run. The tests below walk the catalogue family by
family — the authentication and authorisation seven, the shape and not-found
identifiers, the version and state identifiers, the air-safety identifiers, the
authority and waiver identifiers, the temporal identifiers, the air-window and
uniqueness identifiers, and the referential, inventory and arithmetic
identifiers — and provoke each one in a request where no other rule can fire, so
that a substituted identifier or a substituted status is visible as a failure.
"""
import pytest

from test_helpers import (
    ADMIN,
    COMPLIANCE,
    NON_EXISTENT_UUID,
    TRAFFIC,
    factories,
    fixtures as fx,
    make_master_control_headers,
    make_qc_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# PRD §2.4: the logical clock starts at 2026-08-01T00:00:00Z and only moves when
# a client asks it to; every scenario below pins it explicitly first.
_CLOCK = "2026-08-01T09:00:00Z"

# An identifier of correct shape that names no row anywhere in the station.
_DANGLING = NON_EXISTENT_UUID


# ===========================================================================
# The authentication and authorisation seven
# ===========================================================================

def test_a_user_id_naming_nobody_is_refused_with_401_operator_not_found(api):
    """An unresolvable X-User-ID under an entity-backed role is an authentication failure.

    PRD §2.1: "If `X-User-ID` does not resolve to an existing `Operator` row
    while one of those four roles is claimed, the request fails with
    `ERR_OPERATOR_NOT_FOUND`."

    Design: Corner/errors/the_seven_auth_ids_split_401_from_403_and_never_leak_existence
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    resp = api.change_channel_air_state(
        plant["ch2"]["id"],
        factories.air_state_payload("BARS_AND_TONE", reason="PROBE"),
        make_master_control_headers(_DANGLING),
    )
    validate_error(resp, "ERR_OPERATOR_NOT_FOUND", expected_status=401)
    assert fx.read_channel(plant["ch2"]["id"])["air_status"] == "DARK"


def test_a_real_operator_presenting_another_role_is_refused_with_403(api):
    """A row that exists but carries the wrong role_class stops at identity, not at 401.

    PRD §2.1: "If the row exists but its `role_class` does not correspond to the
    claimed role, the request fails with `ERR_ROLE_IDENTITY_MISMATCH`"

    Design: Corner/errors/the_seven_auth_ids_split_401_from_403_and_never_leak_existence
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    resp = api.change_channel_air_state(
        plant["ch2"]["id"],
        factories.air_state_payload("BARS_AND_TONE", reason="PROBE"),
        make_master_control_headers(plant["qc"]["id"]),
    )
    validate_error(resp, "ERR_ROLE_IDENTITY_MISMATCH", expected_status=403)
    assert fx.read_channel(plant["ch2"]["id"])["air_status"] == "DARK"


def test_a_qc_technician_may_not_drive_air_state_and_is_refused_with_403(api):
    """A genuine operator presenting their own role at an endpoint they do not own is a 403.

    PRD §2.1: "a recognised role attempting an operation it does not own is
    rejected with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/errors/the_seven_auth_ids_split_401_from_403_and_never_leak_existence
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    resp = api.change_channel_air_state(
        plant["ch2"]["id"],
        factories.air_state_payload("BARS_AND_TONE", reason="PROBE"),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED", expected_status=403)
    assert fx.read_channel(plant["ch2"]["id"])["air_status"] == "DARK"


def test_the_same_403_governs_a_read_the_role_does_not_own(api):
    """The permission check is not limited to mutations: a forbidden read is a 403 too.

    PRD §4: "The role names in the final column are the values `X-User-Role` may
    carry for that operation; any other recognised role receives
    `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/errors/the_seven_auth_ids_split_401_from_403_and_never_leak_existence
    """
    scn = fx.setup_playlist_scenario(fx.setup_base_plant(clock_utc=_CLOCK))

    resp = api.get_playlist_reconciliation(scn["playlist"]["id"], scn["mco_headers"])
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED", expected_status=403)

    permitted = validate_success(
        api.get_playlist_reconciliation(scn["playlist"]["id"], scn["pd_headers"])
    )
    assert permitted is not None, "the same read is available to a permitted role"


def test_no_headers_with_a_malformed_body_still_reports_the_missing_headers(api):
    """Header presence is checked before the body is parsed and before the path resolves.

    PRD §2.1: "A request that omits either header, or supplies either as an empty
    string, is rejected with `ERR_MISSING_AUTH_HEADERS` before the body is parsed
    at all, so a request that is both unauthenticated and malformed reports the
    missing headers rather than the malformed body."

    Design: Corner/errors/the_seven_auth_ids_split_401_from_403_and_never_leak_existence
    """
    resp = api.change_channel_air_state(
        _DANGLING, {"target_air_status": "NOT_AN_AIR_STATE"}, {}
    )
    validate_error(resp, "ERR_MISSING_AUTH_HEADERS", expected_status=401)


def test_an_empty_role_header_is_treated_as_a_missing_one(api):
    """An empty string is not a role value; it is an absent header.

    PRD §2.1: "A request that omits either header, or supplies either as an empty
    string, is rejected with `ERR_MISSING_AUTH_HEADERS` before the body is parsed
    at all"

    Design: Corner/errors/the_seven_auth_ids_split_401_from_403_and_never_leak_existence
    """
    resp = api.get_channel(_DANGLING, {"X-User-ID": "station-admin-1", "X-User-Role": ""})
    validate_error(resp, "ERR_MISSING_AUTH_HEADERS", expected_status=401)


def test_a_role_outside_the_seven_is_refused_with_401_unknown_role(api):
    """The role vocabulary is part of authentication, so an unknown role is a 401.

    PRD §2.1: "The value of `X-User-Role` is matched case-sensitively against
    exactly seven role names — `MasterControlOperator`, `QCTechnician`,
    `ProgramDirector`, `BroadcastEngineer`, `TrafficCoordinator`,
    `ComplianceOfficer` and `StationAdmin` — and anything outside that set is
    rejected with `ERR_UNKNOWN_ROLE`."

    Design: Corner/errors/the_seven_auth_ids_split_401_from_403_and_never_leak_existence
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    resp = api.change_channel_air_state(
        plant["ch2"]["id"],
        factories.air_state_payload("BARS_AND_TONE", reason="PROBE"),
        {"X-User-ID": _DANGLING, "X-User-Role": "NetworkOperator",
         "Content-Type": "application/json"},
    )
    validate_error(resp, "ERR_UNKNOWN_ROLE", expected_status=401)
    assert fx.read_channel(plant["ch2"]["id"])["air_status"] == "DARK"


def test_a_suspended_operator_is_refused_a_mutation_but_may_still_read(api):
    """Suspension closes the mutations and leaves the reads open.

    PRD §2.1: "A suspended operator — one whose `status` is `SUSPENDED` rather
    than `ACTIVE` — is refused every mutating request with
    `ERR_OPERATOR_SUSPENDED`, while read endpoints remain available to them."

    Design: Corner/errors/the_seven_auth_ids_split_401_from_403_and_never_leak_existence
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    suspended = fx.suspend_operator(plant["mco"]["id"])
    assert suspended["status"] == "SUSPENDED"

    resp = api.change_channel_air_state(
        plant["ch2"]["id"],
        factories.air_state_payload("BARS_AND_TONE", reason="PROBE"),
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_OPERATOR_SUSPENDED", expected_status=403)
    assert fx.read_channel(plant["ch2"]["id"])["air_status"] == "DARK"

    read_back = validate_success(
        api.get_channel(plant["ch2"]["id"], plant["mco_headers"])
    )
    assert read_back["id"] == plant["ch2"]["id"], "reads stay open to a suspended operator"


def test_an_expired_certification_is_refused_on_an_air_critical_mutation(api):
    """Certification is a gate on the acting operator, one second past the expiry instant.

    PRD §2.1: "`ERR_OPERATOR_CERTIFICATION_EXPIRED` is returned when the logical
    clock has passed `certification_expires_utc`."

    Design: Corner/errors/the_seven_auth_ids_split_401_from_403_and_never_leak_existence
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    stale = fx.create_operator("MASTER_CONTROL", "CRAWL_AND_CUTIN",
                               "2026-08-01T08:59:59Z", full_name="Eve Lapse")
    assert stale["certification_state"] == "EXPIRED"
    stale_headers = make_master_control_headers(stale["id"])

    resp = api.change_channel_air_state(
        plant["ch2"]["id"],
        factories.air_state_payload("BARS_AND_TONE", reason="PROBE"),
        stale_headers,
    )
    validate_error(resp, "ERR_OPERATOR_CERTIFICATION_EXPIRED", expected_status=403)
    assert fx.read_channel(plant["ch2"]["id"])["air_status"] == "DARK"

    read_back = validate_success(api.get_channel(plant["ch2"]["id"], stale_headers))
    assert read_back["id"] == plant["ch2"]["id"], "certification never gates a read"


def test_a_suspended_operator_presenting_the_wrong_role_reports_the_mismatch(api):
    """Identity verification runs ahead of the suspension gate, so the mismatch wins.

    PRD §2.1: "A genuine operator presenting the wrong role class is stopped at
    identity verification, not at authorisation."

    Design: Corner/errors/the_seven_auth_ids_split_401_from_403_and_never_leak_existence
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    suspended = fx.suspend_operator(plant["qc"]["id"])
    assert suspended["status"] == "SUSPENDED"

    resp = api.change_channel_air_state(
        plant["ch2"]["id"],
        factories.air_state_payload("BARS_AND_TONE", reason="PROBE"),
        make_master_control_headers(plant["qc"]["id"]),
    )
    validate_error(resp, "ERR_ROLE_IDENTITY_MISMATCH", expected_status=403)
    assert fx.read_channel(plant["ch2"]["id"])["air_status"] == "DARK"


def test_an_opaque_role_at_a_forbidden_endpoint_is_the_permission_403(api):
    """An opaque role carries no operator row, so only the permission gate can refuse it.

    PRD §2.1: "Once the role is recognised, the endpoint's own permitted-role list
    governs: a recognised role attempting an operation it does not own is rejected
    with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/errors/the_seven_auth_ids_split_401_from_403_and_never_leak_existence
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    resp = api.change_channel_air_state(
        plant["ch2"]["id"],
        factories.air_state_payload("BARS_AND_TONE", reason="PROBE"),
        COMPLIANCE,
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED", expected_status=403)
    assert fx.read_channel(plant["ch2"]["id"])["air_status"] == "DARK"


# ===========================================================================
# The three shape identifiers and the thirteen not-found identifiers
# ===========================================================================

def _received_asset(plant, duration_seconds=1800):
    """An asset registered and delivered but not yet graded, so a QC report is legal."""
    asset = fx.create_asset(plant, expected_duration_seconds=duration_seconds)
    delivered = fx.deliver_asset(plant, asset["id"],
                                 measured_duration_seconds=duration_seconds)
    assert fx.read_asset(asset["id"])["status"] == "RECEIVED"
    return asset, delivered["version"]


def test_a_dangling_channel_id_in_a_fault_body_names_the_channel(api):
    """The not-found identifier comes from the field that failed, not from the endpoint.

    PRD §2.7: "an unknown `channel_id` yields `ERR_CHANNEL_NOT_FOUND`"

    Design: Corner/errors/three_shape_ids_and_thirteen_not_found_ids_each_own_exactly_one_condition
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    resp = api.report_fault(
        factories.report_fault_payload("CAPTION_LOSS", "MINOR", _CLOCK,
                                       channel_id=_DANGLING),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_CHANNEL_NOT_FOUND", expected_status=404)

    faults, _meta = validate_paginated(api.list_faults(ADMIN))
    assert faults == [], "a refused report must not persist a fault row"


def test_a_dangling_playlist_item_id_in_a_fault_body_names_the_item(api):
    """The same endpoint with a good channel and a bad element names the element.

    PRD §2.7: "an unknown `playlist_item_id` or `replacement_asset_id` or
    `replaces_item_id` yields the corresponding item or asset code"

    Design: Corner/errors/three_shape_ids_and_thirteen_not_found_ids_each_own_exactly_one_condition
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    resp = api.report_fault(
        factories.report_fault_payload("CAPTION_LOSS", "MINOR", _CLOCK,
                                       channel_id=plant["ch1"]["id"],
                                       playlist_item_id=_DANGLING),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_PLAYLIST_ITEM_NOT_FOUND", expected_status=404)

    faults, _meta = validate_paginated(api.list_faults(ADMIN))
    assert faults == [], "a refused report must not persist a fault row"


def test_an_operator_reference_in_a_body_is_the_404_not_the_header_401(api):
    """One identifier yields two different codes depending on where it appears.

    PRD §3.4: "Any operator identifier supplied in a path or a body — inspector,
    requester, authorizer, waiver signer — that does not resolve to an existing
    operator yields `ERR_OPERATOR_REFERENCE_NOT_FOUND`."

    Design: Corner/errors/three_shape_ids_and_thirteen_not_found_ids_each_own_exactly_one_condition
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    asset, asset_version = _received_asset(plant)

    in_body = api.submit_qc_report(
        asset["id"],
        factories.qc_report_payload(asset_version, _DANGLING),
        plant["qc_headers"],
    )
    validate_error(in_body, "ERR_OPERATOR_REFERENCE_NOT_FOUND", expected_status=404)

    in_header = api.submit_qc_report(
        asset["id"],
        factories.qc_report_payload(asset_version, plant["qc"]["id"]),
        make_qc_headers(_DANGLING),
    )
    validate_error(in_header, "ERR_OPERATOR_NOT_FOUND", expected_status=401)

    assert fx.read_asset(asset["id"])["status"] == "RECEIVED"
    reports, _meta = validate_paginated(api.list_qc_reports(ADMIN, params={"asset_id": asset["id"]}))
    assert reports == [], "neither refusal may append a QC report"


def test_a_bad_enum_outranks_a_dangling_reference_in_the_same_body(api):
    """Enum validation runs at priority 9 and body references only at priority 12.

    PRD §2.8: "enum literals valid (`ERR_INVALID_ENUM_VALUE`), types and ranges
    valid (`ERR_INVALID_FIELD_VALUE`), path segments resolve (the per-segment 404
    codes of §2.7), body references resolve (the same 404 codes)"

    Design: Corner/errors/three_shape_ids_and_thirteen_not_found_ids_each_own_exactly_one_condition
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    resp = api.report_fault(
        factories.report_fault_payload("NOT_A_CODE", "MINOR", _CLOCK,
                                       channel_id=_DANGLING),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_INVALID_ENUM_VALUE", expected_status=422)


def test_a_missing_field_outranks_a_bad_enum_in_the_same_body(api):
    """Omission is checked at priority 8, ahead of the enum literals at priority 9.

    PRD §2.8: "required fields present (`ERR_MISSING_REQUIRED_FIELD`), enum
    literals valid (`ERR_INVALID_ENUM_VALUE`)"

    Design: Corner/errors/three_shape_ids_and_thirteen_not_found_ids_each_own_exactly_one_condition
    """
    fx.setup_base_plant(clock_utc=_CLOCK)

    payload = factories.create_asset_payload(source="NOT_A_SOURCE")
    payload.pop("house_number")

    resp = api.create_asset(payload, TRAFFIC)
    validate_error(resp, "ERR_MISSING_REQUIRED_FIELD", expected_status=422)

    assets, _meta = validate_paginated(api.list_assets(ADMIN))
    assert assets == [], "a refused registration must not persist an asset"


def test_a_non_positive_erp_is_the_range_422(api):
    """Range violations are their own identifier, distinct from omission and from enums.

    PRD §3.1: "its licensed `authorized_erp_kw`, the effective radiated power in
    kilowatts, which must be greater than zero"

    Design: Corner/errors/three_shape_ids_and_thirteen_not_found_ids_each_own_exactly_one_condition
    """
    plant = fx.bootstrap_operators(clock_utc=_CLOCK)

    resp = api.create_transmitter(
        factories.create_transmitter_payload(facility_id="FAC-70099",
                                             call_sign="WTST",
                                             authorized_erp_kw=-5),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_INVALID_FIELD_VALUE", expected_status=422)


def test_a_forbidden_role_on_a_non_existent_playlist_still_reports_the_role(api):
    """The 403 lands before the 404, so statuses cannot be used to enumerate rows.

    PRD §2.8: "endpoint authorisation (`ERR_ROLE_NOT_PERMITTED`) ... path segments
    resolve (the per-segment 404 codes of §2.7)"

    Design: Corner/errors/three_shape_ids_and_thirteen_not_found_ids_each_own_exactly_one_condition
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    resp = api.get_playlist_reconciliation(_DANGLING, plant["mco_headers"])
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED", expected_status=403)


def test_a_well_formed_id_of_the_wrong_kind_behaves_like_a_missing_one(api):
    """A path parameter identifies a row of the entity named by the preceding segment.

    PRD §2.7: "Every path parameter in this API is written `{id}` and identifies a
    row of the entity named by the segment preceding it."

    Design: Corner/errors/three_shape_ids_and_thirteen_not_found_ids_each_own_exactly_one_condition
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    resp = api.get_asset(plant["ch1"]["id"], ADMIN)
    validate_error(resp, "ERR_ASSET_NOT_FOUND", expected_status=404)


@pytest.mark.parametrize(
    "reader,error_id",
    [
        ("get_transmitter", "ERR_TRANSMITTER_NOT_FOUND"),
        ("get_multiplex", "ERR_MULTIPLEX_NOT_FOUND"),
        ("get_channel", "ERR_CHANNEL_NOT_FOUND"),
        ("get_asset", "ERR_ASSET_NOT_FOUND"),
        ("get_qc_report", "ERR_QC_REPORT_NOT_FOUND"),
        ("get_playlist", "ERR_PLAYLIST_NOT_FOUND"),
        ("get_playlist_item", "ERR_PLAYLIST_ITEM_NOT_FOUND"),
        ("get_spot_order", "ERR_SPOT_ORDER_NOT_FOUND"),
        ("get_feed_window", "ERR_FEED_WINDOW_NOT_FOUND"),
        ("get_override", "ERR_OVERRIDE_NOT_FOUND"),
        ("get_fault", "ERR_FAULT_NOT_FOUND"),
        ("get_notification", "ERR_NOTIFICATION_NOT_FOUND"),
    ],
)
def test_each_path_segment_owns_its_own_404(api, reader, error_id):
    """One not-found identifier per entity segment, every one of them an HTTP 404.

    PRD §2.7: "a transmitter segment yields `ERR_TRANSMITTER_NOT_FOUND`, a
    multiplex segment `ERR_MULTIPLEX_NOT_FOUND`, a channel segment
    `ERR_CHANNEL_NOT_FOUND`, an operator segment
    `ERR_OPERATOR_REFERENCE_NOT_FOUND`, an asset segment `ERR_ASSET_NOT_FOUND`, a
    QC-report segment `ERR_QC_REPORT_NOT_FOUND`, a playlist segment
    `ERR_PLAYLIST_NOT_FOUND`, a playlist-item segment
    `ERR_PLAYLIST_ITEM_NOT_FOUND`, a spot-order segment
    `ERR_SPOT_ORDER_NOT_FOUND`, a network-feed-window segment
    `ERR_FEED_WINDOW_NOT_FOUND`, an emergency-override segment
    `ERR_OVERRIDE_NOT_FOUND`, a technical-fault segment `ERR_FAULT_NOT_FOUND`,
    and a regulatory-notification segment `ERR_NOTIFICATION_NOT_FOUND`. All of
    these are HTTP 404."

    Design: Corner/errors/three_shape_ids_and_thirteen_not_found_ids_each_own_exactly_one_condition
    """
    resp = getattr(api, reader)(_DANGLING, ADMIN)
    validate_error(resp, error_id, expected_status=404)


# ===========================================================================
# The three version identifiers and the nine state identifiers
# ===========================================================================

def _on_air_day(clock_utc=_CLOCK):
    """The canonical seven-element day on air, with the ingest version remembered."""
    scn = fx.setup_playlist_scenario(fx.setup_base_plant(clock_utc=clock_utc))
    ingest_version = scn["playlist"]["version"]
    fx.drive_playlist_to_on_air(scn)
    assert scn["playlist"]["status"] == "ON_AIR"
    return scn, ingest_version


def _one_item_revision(scn, version):
    return factories.traffic_revision_payload(
        version,
        [{"sequence_number": 1, "element_kind": "PROGRAM",
          "asset_id": scn["assets"]["prog1"]["id"],
          "scheduled_start_utc": "2026-08-01T12:00:00Z",
          "scheduled_duration_seconds": 3600, "max_trim_seconds": 0}],
    )


def test_a_stale_playlist_token_answers_before_the_on_air_state_refusal(api):
    """The 412 is the whole answer; the state violation only surfaces once the token is fresh.

    PRD §2.6: "A mismatch is rejected with `ERR_STALE_PLAYLIST_VERSION` and HTTP
    412."

    PRD §3.5: "a revision against an `ON_AIR`, `CLOSED` or `ABANDONED` playlist is
    refused** with `ERR_PLAYLIST_INVALID_STATE`."

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    scn, ingest_version = _on_air_day()
    current = fx.read_playlist(scn["playlist"]["id"])["version"]
    assert current > ingest_version, "the air chain must have moved the version on"

    stale = api.apply_traffic_revision(
        scn["playlist"]["id"], _one_item_revision(scn, ingest_version), TRAFFIC
    )
    validate_error(stale, "ERR_STALE_PLAYLIST_VERSION", expected_status=412)

    fresh = api.apply_traffic_revision(
        scn["playlist"]["id"], _one_item_revision(scn, current), TRAFFIC
    )
    validate_error(fresh, "ERR_PLAYLIST_INVALID_STATE", expected_status=409)

    after = fx.read_playlist(scn["playlist"]["id"])
    assert after["version"] == current, "neither refusal may advance the version"
    assert len(fx.list_items(scn["playlist"]["id"], TRAFFIC)) == 7


def test_a_stale_asset_token_on_a_second_qc_report_is_the_412(api):
    """The asset token is its own identifier, distinct from the playlist and multiplex ones.

    PRD §2.6: "Submitting a QC report requires `expected_asset_version` to equal
    the target asset's current `version`. ... A mismatch is rejected with
    `ERR_STALE_ASSET_VERSION` and HTTP 412."

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    asset, delivered_version = _received_asset(plant)
    fx.submit_qc(plant, asset["id"], delivered_version, defect_codes=[])
    graded = fx.read_asset(asset["id"])
    assert graded["version"] > delivered_version

    resp = api.submit_qc_report(
        asset["id"],
        factories.qc_report_payload(delivered_version, plant["qc"]["id"]),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_STALE_ASSET_VERSION", expected_status=412)

    reports, _meta = validate_paginated(api.list_qc_reports(ADMIN, params={"asset_id": asset["id"]}))
    assert len(reports) == 1, "the refused report must not be appended"


def test_a_stale_multiplex_token_on_channel_creation_is_the_412(api):
    """The token names the capacity pool, not the row being written.

    PRD §2.6: "Creating a channel requires `expected_multiplex_version` to equal
    the parent multiplex's current `version`. ... A mismatch is rejected with
    `ERR_STALE_MULTIPLEX_VERSION` and HTTP 412."

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    plant = fx.bootstrap_operators(clock_utc=_CLOCK)
    engineer = plant["eng_headers"]
    transmitter = fx.create_transmitter(engineer)
    multiplex = fx.create_multiplex(engineer, transmitter["id"])
    at_creation = multiplex["version"]
    ch1 = fx.create_channel(engineer, multiplex["id"], at_creation)
    assert fx.read_multiplex(multiplex["id"])["version"] > at_creation

    resp = api.create_channel(
        factories.create_subchannel_payload(
            multiplex["id"], at_creation, ch1["id"],
            call_sign="WXYZ-DT3", channel_number="12.3",
            requested_bitrate_kbps=3000, floor_bitrate_kbps=2000, priority_rank=3,
        ),
        engineer,
    )
    validate_error(resp, "ERR_STALE_MULTIPLEX_VERSION", expected_status=412)

    channels, _meta = validate_paginated(api.list_channels(ADMIN))
    assert [c["id"] for c in channels] == [ch1["id"]], "no channel row may be written"


def test_a_backwards_playlist_move_is_the_playlist_state_409(api):
    """`ON_AIR` to `ARMED` is not a declared move.

    PRD §3.5: "The reachable moves are `IMPORTING` to `IMPORTED` or `ABANDONED`;
    `IMPORTED` to `VALIDATED`, back to `IMPORTING`, or `ABANDONED`; `VALIDATED` to
    `ARMED`, back to `IMPORTED`, or `ABANDONED`; `ARMED` to `ON_AIR`, back to
    `IMPORTED`, or `ABANDONED`; and `ON_AIR` to `CLOSED`. `CLOSED` and `ABANDONED`
    are terminal. Anything else is refused with `ERR_PLAYLIST_INVALID_STATE`."

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    scn, _ingest_version = _on_air_day()

    resp = api.change_playlist_state(
        scn["playlist"]["id"], factories.playlist_state_payload("ARMED"),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_PLAYLIST_INVALID_STATE", expected_status=409)
    assert fx.read_playlist(scn["playlist"]["id"])["status"] == "ON_AIR"


def test_full_power_to_full_power_is_the_transmitter_state_409(api):
    """A self-loop that the state machine does not declare is a refusal, not a no-op.

    PRD §3.1: "Notably, `FULL_POWER` to `FULL_POWER` is not a declared transition
    and is refused."

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    assert plant["transmitter"]["operational_state"] == "FULL_POWER"

    resp = api.change_transmitter_power_state(
        plant["transmitter"]["id"], factories.power_state_payload("FULL_POWER"),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_TRANSMITTER_INVALID_STATE", expected_status=409)

    after = fx.read_transmitter(plant["transmitter"]["id"])
    assert after["operational_state"] == "FULL_POWER"
    assert after["version"] == plant["transmitter"]["version"]


def test_asking_for_eas_override_through_the_air_state_endpoint_is_refused(api):
    """That state belongs to the override cascade and is unreachable from this endpoint.

    PRD §3.3: "`EAS_OVERRIDE` is never reachable through the air-state endpoint at
    all** — asking for it there is refused with the same code even when the channel
    is `ON_AIR`"

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    lit = fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    assert lit["air_status"] == "ON_AIR"

    resp = api.change_channel_air_state(
        plant["ch1"]["id"], factories.air_state_payload("EAS_OVERRIDE"),
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_CHANNEL_INVALID_AIR_STATE", expected_status=409)
    assert fx.read_channel(plant["ch1"]["id"])["air_status"] == "ON_AIR"


def test_a_qc_report_on_a_retracted_asset_is_the_asset_state_409(api):
    """An ingest report needs the asset in `RECEIVED`; a withdrawn asset is not.

    PRD §3.4: "An ingest-basis report requires the asset to be in `RECEIVED`; an
    air-check-basis report requires the asset to be in `QC_PASSED` or `QC_WAIVED`;
    either mismatch yields `ERR_ASSET_INVALID_STATE`."

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    asset, _delivered_version = _received_asset(plant)
    retracted = fx.retract(plant, asset["id"])
    assert retracted["status"] == "RETRACTED"

    resp = api.submit_qc_report(
        asset["id"],
        factories.qc_report_payload(retracted["version"], plant["qc"]["id"]),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_ASSET_INVALID_STATE", expected_status=409)

    reports, _meta = validate_paginated(api.list_qc_reports(ADMIN, params={"asset_id": asset["id"]}))
    assert reports == [], "the refused report must not be appended"


def test_a_second_cue_on_the_same_element_is_the_item_state_409(api):
    """A cue is legal only from `SCHEDULED`, so a cued element cannot be cued again.

    PRD §3.6: "An event is legal only for certain current `playout_status` values:
    `CUE` requires `SCHEDULED`, `START` requires `CUED`, `END` requires `PLAYING`,
    `TRUNCATION` requires `PLAYING`, and `SKIP` requires `SCHEDULED` or `CUED`."

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    scn, _ingest_version = _on_air_day()
    item1 = scn["items"][0]
    fx.cue_item(scn, item1["id"], "2026-08-01T11:59:00Z")
    assert fx.read_item(item1["id"])["playout_status"] == "CUED"

    resp = api.post_playout_event(
        item1["id"],
        factories.playout_event_payload("CUE", "2026-08-01T11:59:00Z", source="OPERATOR"),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_ITEM_INVALID_PLAYOUT_STATE", expected_status=409)

    entries = fx.list_item_as_run(item1["id"], scn["mco_headers"])
    assert len(entries) == 1, "the refused event must not be logged"


def test_a_breakaway_before_any_join_is_the_feed_window_state_409(api):
    """A window that was never joined cannot be broken away from.

    PRD §3.7: "A join or breakaway attempted from a state that does not allow it is
    refused with `ERR_FEED_WINDOW_INVALID_STATE`."

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    scn, _ingest_version = _on_air_day()
    window = fx.create_window(scn, "2026-08-01T12:31:00Z", "2026-08-01T12:36:00Z",
                              anchor_sequence_number=4, backtiming_mode="STRICT",
                              guard_seconds=30, live_encoder_units=1)
    opening_state = window["state"]

    resp = api.breakaway_feed_window(window["id"], {}, scn["mco_headers"])
    validate_error(resp, "ERR_FEED_WINDOW_INVALID_STATE", expected_status=409)
    assert fx.read_feed_window(window["id"])["state"] == opening_state


def test_activating_an_active_override_in_the_same_mode_is_the_override_state_409(api):
    """An already-active override must be asked for a mode different from the live one.

    PRD §3.8: "when the override is already active the requested `override_mode`
    must differ from the current `active_mode`**; anything else is refused with
    `ERR_OVERRIDE_INVALID_STATE`."

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    requested = fx.request_override(plant, "CRAWL")
    active = fx.activate_override(plant, requested["id"], "CRAWL")
    assert active["state"] == "ACTIVE_CRAWL"

    resp = api.activate_override(
        requested["id"],
        factories.activate_override_payload(plant["pd"]["id"], "CRAWL"),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_OVERRIDE_INVALID_STATE", expected_status=409)

    after = fx.read_override(requested["id"])
    assert after["state"] == "ACTIVE_CRAWL"
    assert after["version"] == active["version"]


def test_a_fault_self_loop_is_the_fault_state_409(api):
    """`DETECTED` to `DETECTED` is not among the reachable fault moves.

    PRD §3.3: "The reachable moves are `DETECTED` to `ACKNOWLEDGED` or to
    `AUTO_CLEARED`; `ACKNOWLEDGED` to `ESCALATED` or to `MITIGATED`; `ESCALATED` to
    `MITIGATED`; and `MITIGATED` to `RESOLVED` or back to `DETECTED`. ... Any
    unreachable move is refused with `ERR_FAULT_INVALID_STATE`."

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    fault = fx.report_channel_fault(plant, "CAPTION_LOSS", "MINOR", _CLOCK)
    assert fault["state"] == "DETECTED"

    resp = api.change_fault_state(
        fault["id"], factories.fault_state_payload("DETECTED"), plant["eng_headers"]
    )
    validate_error(resp, "ERR_FAULT_INVALID_STATE", expected_status=409)

    after = fx.read_fault(fault["id"])
    assert after["state"] == "DETECTED"
    assert after["version"] == fault["version"]


def test_filing_an_already_filed_notification_is_the_notification_state_409(api):
    """Filing is a once-only act; the second attempt is a state refusal.

    PRD §3.1: "Filing against a notification already `FILED` or `LATE_FILED` is
    refused with `ERR_NOTIFICATION_INVALID_STATE`."

    Design: Corner/errors/three_occ_ids_precede_nine_invalid_state_ids_and_each_entity_owns_its_own_409
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    fx.change_power_state(plant, "REDUCED_POWER", power_pct=79, reason="COOLING_FAULT")
    notifications = fx.list_notifications(plant["transmitter"]["id"], COMPLIANCE)
    assert len(notifications) == 1
    assert notifications[0]["status"] == "PENDING"

    filed = validate_success(
        api.file_notification(notifications[0]["id"],
                              factories.file_notification_payload(), COMPLIANCE)
    )
    assert filed["status"] == "FILED"

    resp = api.file_notification(notifications[0]["id"],
                                 factories.file_notification_payload(
                                     filed_reference="FCC-REF-0002"),
                                 COMPLIANCE)
    validate_error(resp, "ERR_NOTIFICATION_INVALID_STATE", expected_status=409)

    after = fx.read_notification(notifications[0]["id"])
    assert after["status"] == "FILED"
    assert after["filed_reference"] == "FCC-REF-0001"


# ===========================================================================
# The air-safety identifiers: cross-entity refusals
# ===========================================================================

def test_an_open_audio_fault_does_not_block_a_power_restoration(api):
    """The restore guard reads the fault code, not the severity.

    PRD §3.1: "A restoration to `FULL_POWER`, from either `REDUCED_POWER` or
    `OFF_AIR`, is refused with `ERR_RF_FAULT_BLOCKS_RESTORE` while any technical
    fault on that transmitter has `fault_code` `RF_POWER_FAULT` and a `state` of
    `DETECTED`, `ACKNOWLEDGED` or `ESCALATED`."

    Design: Corner/errors/the_eight_air_safety_ids_are_cross_entity_and_resolve_in_a_fixed_order
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    fx.change_power_state(plant, "REDUCED_POWER", power_pct=79, reason="COOLING_FAULT")
    audio = fx.report_channel_fault(plant, "AUDIO_LOSS", "MAJOR", _CLOCK)

    restored = validate_success(
        api.change_transmitter_power_state(
            plant["transmitter"]["id"], factories.power_state_payload("FULL_POWER"),
            plant["eng_headers"],
        )
    )
    assert restored["operational_state"] == "FULL_POWER"
    assert fx.read_fault(audio["id"])["state"] == "DETECTED"


def test_an_open_rf_power_fault_blocks_a_power_restoration(api):
    """An open RF fault on the transmitter pins it at reduced power.

    PRD §3.1: "A restoration to `FULL_POWER`, from either `REDUCED_POWER` or
    `OFF_AIR`, is refused with `ERR_RF_FAULT_BLOCKS_RESTORE` while any technical
    fault on that transmitter has `fault_code` `RF_POWER_FAULT` and a `state` of
    `DETECTED`, `ACKNOWLEDGED` or `ESCALATED`."

    Design: Corner/errors/the_eight_air_safety_ids_are_cross_entity_and_resolve_in_a_fixed_order
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    fx.change_power_state(plant, "REDUCED_POWER", power_pct=79, reason="COOLING_FAULT")
    fx.report_transmitter_fault(plant, "RF_POWER_FAULT", "MAJOR", _CLOCK)

    resp = api.change_transmitter_power_state(
        plant["transmitter"]["id"], factories.power_state_payload("FULL_POWER"),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_RF_FAULT_BLOCKS_RESTORE", expected_status=409)

    after = fx.read_transmitter(plant["transmitter"]["id"])
    assert after["operational_state"] == "REDUCED_POWER"
    assert after["current_power_pct"] == 79


def test_mitigating_the_rf_fault_reopens_the_restoration(api):
    """The guard names three states, so a mitigated fault no longer blocks the restore.

    PRD §3.1: "refused with `ERR_RF_FAULT_BLOCKS_RESTORE` while any technical fault
    on that transmitter has `fault_code` `RF_POWER_FAULT` and a `state` of
    `DETECTED`, `ACKNOWLEDGED` or `ESCALATED`."

    Design: Corner/errors/the_eight_air_safety_ids_are_cross_entity_and_resolve_in_a_fixed_order
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    fx.change_power_state(plant, "REDUCED_POWER", power_pct=79, reason="COOLING_FAULT")
    fault = fx.report_transmitter_fault(plant, "RF_POWER_FAULT", "MAJOR", _CLOCK)
    validate_error(
        api.change_transmitter_power_state(
            plant["transmitter"]["id"], factories.power_state_payload("FULL_POWER"),
            plant["eng_headers"]),
        "ERR_RF_FAULT_BLOCKS_RESTORE",
    )

    fx.advance_fault(plant, fault["id"], "ACKNOWLEDGED")
    mitigated = fx.advance_fault(plant, fault["id"], "MITIGATED",
                                 mitigation_code="SWITCH_TO_BACKUP")
    assert mitigated["state"] == "MITIGATED"

    restored = validate_success(
        api.change_transmitter_power_state(
            plant["transmitter"]["id"], factories.power_state_payload("FULL_POWER"),
            plant["eng_headers"],
        )
    )
    assert restored["operational_state"] == "FULL_POWER"


def test_a_channel_pinned_below_its_floor_cannot_be_lit(api):
    """Being under the floor starves the channel even while its state reads ACTIVE.

    PRD §3.3: "The channel's `allocation_state` must be `ACTIVE`, and its
    `allocated_bitrate_kbps` must be at least its `floor_bitrate_kbps`; either
    failure is reported as `ERR_CHANNEL_ALLOCATION_STARVED`, so a `STARVED` or
    `STANDBY` channel cannot be lit and a channel whose allocation was pinned below
    its own floor cannot be lit either."

    Design: Corner/errors/the_eight_air_safety_ids_are_cross_entity_and_resolve_in_a_fixed_order
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    multiplex = fx.read_multiplex(plant["multiplex"]["id"])
    pinned = validate_success(
        api.patch_channel_allocation(
            plant["ch1"]["id"],
            factories.allocation_patch_payload(multiplex["version"],
                                               pin_allocated_kbps=4000),
            plant["eng_headers"],
        )
    )
    assert pinned["allocated_bitrate_kbps"] == 4000
    assert pinned["allocated_bitrate_kbps"] < pinned["floor_bitrate_kbps"]
    assert pinned["posture"] != "SUSPENDED"

    resp = api.change_channel_air_state(
        plant["ch1"]["id"], factories.air_state_payload("ON_AIR"), plant["mco_headers"]
    )
    validate_error(resp, "ERR_CHANNEL_ALLOCATION_STARVED", expected_status=409)
    assert fx.read_channel(plant["ch1"]["id"])["air_status"] == "DARK"


def test_a_channel_under_its_floor_may_still_be_set_to_bars_and_tone(api):
    """Bars-and-tone is the unconditional safe fallback, so the starvation gate misses it.

    PRD §3.3: "Dropping to `BARS_AND_TONE` has no preconditions at all and can be
    commanded at any time, as it is the safe fallback."

    Design: Corner/errors/the_eight_air_safety_ids_are_cross_entity_and_resolve_in_a_fixed_order
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    lit = validate_success(
        api.change_channel_air_state(
            plant["ch1"]["id"], factories.air_state_payload("ON_AIR"),
            plant["mco_headers"],
        )
    )
    assert lit["air_status"] == "ON_AIR"

    multiplex = fx.read_multiplex(plant["multiplex"]["id"])
    starved = validate_success(
        api.patch_channel_allocation(
            plant["ch1"]["id"],
            factories.allocation_patch_payload(multiplex["version"],
                                               pin_allocated_kbps=4000),
            plant["eng_headers"],
        )
    )
    assert starved["allocated_bitrate_kbps"] < starved["floor_bitrate_kbps"]

    bars = validate_success(
        api.change_channel_air_state(
            plant["ch1"]["id"], factories.air_state_payload("BARS_AND_TONE"),
            plant["mco_headers"],
        )
    )
    assert bars["air_status"] == "BARS_AND_TONE"


def test_a_suspended_posture_channel_cannot_carry_an_alert(api):
    """The posture gate is checked on the alert itself, not only on the air-state move.

    PRD §3.8: "The channel's `posture` must not be `SUSPENDED`, otherwise
    `ERR_CHANNEL_SUSPENDED_POSTURE` — a channel whose transmitter is dark or whose
    allocation has starved cannot carry an alert."

    Design: Corner/errors/the_eight_air_safety_ids_are_cross_entity_and_resolve_in_a_fixed_order
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    requested = fx.request_override(plant, "CRAWL")
    assert requested["state"] == "PENDING"

    fx.change_power_state(plant, "OFF_AIR", reason="TOTAL_POWER_LOSS")
    assert fx.read_channel(plant["ch1"]["id"])["posture"] == "SUSPENDED"

    resp = api.activate_override(
        requested["id"],
        factories.activate_override_payload(plant["pd"]["id"], "CRAWL"),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_CHANNEL_SUSPENDED_POSTURE", expected_status=409)
    assert fx.read_override(requested["id"])["state"] == "PENDING"


def test_an_open_critical_fault_blocks_the_return_from_bars_to_air(api):
    """The extra gate belongs to the bars-and-tone return, and it names CRITICAL only.

    PRD §3.3: "there must be no technical fault on the channel whose `severity` is
    `CRITICAL` and whose `state` is `DETECTED`, `ACKNOWLEDGED` or `ESCALATED`,
    otherwise the restoration is refused with `ERR_CRITICAL_FAULT_OPEN`."

    Design: Corner/errors/the_eight_air_safety_ids_are_cross_entity_and_resolve_in_a_fixed_order
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    fx.set_air_status(plant, plant["ch1"]["id"], "BARS_AND_TONE")
    fault = fx.report_channel_fault(plant, "ENCODER_FAILURE", "CRITICAL", _CLOCK)
    assert fault["severity"] == "CRITICAL"

    resp = api.change_channel_air_state(
        plant["ch1"]["id"], factories.air_state_payload("ON_AIR"), plant["mco_headers"]
    )
    validate_error(resp, "ERR_CRITICAL_FAULT_OPEN", expected_status=409)
    assert fx.read_channel(plant["ch1"]["id"])["air_status"] == "BARS_AND_TONE"


def test_an_open_critical_fault_does_not_stop_a_dark_channel_being_lit(api):
    """The asymmetry between the two air-bound moves is deliberate.

    PRD §3.3: "A critical fault therefore pins a channel to bars-and-tone until it
    is mitigated, while it does not by itself prevent a dark channel being brought
    up — the asymmetry between the two ON_AIR-bound transitions is deliberate."

    Design: Corner/errors/the_eight_air_safety_ids_are_cross_entity_and_resolve_in_a_fixed_order
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    fault = fx.report_channel_fault(plant, "ENCODER_FAILURE", "CRITICAL", _CLOCK,
                                    channel_id=plant["ch2"]["id"])
    assert fault["state"] == "DETECTED"
    assert fx.read_channel(plant["ch2"]["id"])["air_status"] == "DARK"

    lit = validate_success(
        api.change_channel_air_state(
            plant["ch2"]["id"], factories.air_state_payload("ON_AIR"),
            plant["mco_headers"],
        )
    )
    assert lit["air_status"] == "ON_AIR"


def test_a_blocked_element_cannot_be_cued(api):
    """Clearance is read through the element to its asset at cue time.

    PRD §3.6: "for elements whose `element_kind` is `PROGRAM`, `COMMERCIAL`,
    `INTERSTITIAL` or `PROMO` the `clearance_status` must be `CLEARED`, otherwise
    `ERR_UNCLEARED_CONTENT_ON_AIR`, a dependency that reads from the element
    through to its asset"

    Design: Corner/errors/the_eight_air_safety_ids_are_cross_entity_and_resolve_in_a_fixed_order
    """
    scn, _ingest_version = _on_air_day()
    last = scn["items"][6]
    fx.retract(scn, scn["assets"]["prog2"]["id"])
    assert fx.read_item(last["id"])["clearance_status"] == "BLOCKED"
    assert fx.read_playlist(scn["playlist"]["id"])["status"] == "ON_AIR"

    resp = api.post_playout_event(
        last["id"],
        factories.playout_event_payload("CUE", "2026-08-01T11:59:00Z", source="OPERATOR"),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_UNCLEARED_CONTENT_ON_AIR", expected_status=409)

    assert fx.read_item(last["id"])["playout_status"] == "SCHEDULED"
    assert fx.list_item_as_run(last["id"], scn["mco_headers"]) == []


def test_a_waiver_on_an_uncaptioned_asset_is_refused(api):
    """A missing caption track is non-waivable however high the score.

    PRD §3.4: "an asset whose `captions_required` is true and whose
    `caption_present` is false **can never reach `QC_PASSED` or `QC_WAIVED` at
    all**: a missing caption track is a non-waivable defect and the waiver is
    refused with `ERR_CAPTION_REQUIREMENT_UNMET` regardless of how high the
    technical score is."

    Design: Corner/errors/the_eight_air_safety_ids_are_cross_entity_and_resolve_in_a_fixed_order
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    asset = fx.create_asset(plant, expected_duration_seconds=600,
                            captions_required=True)
    delivered = fx.deliver_asset(plant, asset["id"], measured_duration_seconds=600,
                                 caption_present=False)
    report = fx.submit_qc(plant, asset["id"], delivered["version"],
                          defect_codes=[], measured_duration_seconds=600)
    assert report["technical_score"] == 100
    assert report["verdict"] == "FAIL"
    assert fx.read_asset(asset["id"])["status"] == "QC_FAILED"

    resp = api.sign_qc_waiver(
        asset["id"], factories.qc_waiver_payload(plant["pd"]["id"]), plant["pd_headers"]
    )
    validate_error(resp, "ERR_CAPTION_REQUIREMENT_UNMET", expected_status=409)

    after = fx.read_asset(asset["id"])
    assert after["status"] == "QC_FAILED"
    assert after.get("waived_by_operator_id") is None


# ===========================================================================
# The authority and waiver identifiers: identity, not magnitude
# ===========================================================================

def test_a_waiver_below_the_score_floor_is_refused(api):
    """The waiver floor is read off the governing ingest score.

    PRD §3.4: "The governing non-superseded ingest score in
    `technical_score_ingest` must be at least 40 — **exactly 40 is waivable, 39 is
    not** — otherwise `ERR_QC_WAIVER_SCORE_TOO_LOW`."

    Design: Corner/errors/the_eleven_authority_and_waiver_ids_are_identity_tests_not_threshold_tests
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    asset, version = _received_asset(plant, duration_seconds=600)
    report = fx.submit_qc(
        plant, asset["id"], version, measured_duration_seconds=600,
        defect_codes=["AUDIO_LOSS", "FORMAT_MISMATCH", "CAPTION_MISSING",
                      "BLACK_FRAMES"],
    )
    assert report["defect_penalty_points"] == 78
    assert report["technical_score"] == 22
    graded = fx.read_asset(asset["id"])
    assert graded["status"] == "QC_FAILED"
    assert graded["captions_required"] is False

    resp = api.sign_qc_waiver(
        asset["id"], factories.qc_waiver_payload(plant["pd"]["id"]), plant["pd_headers"]
    )
    validate_error(resp, "ERR_QC_WAIVER_SCORE_TOO_LOW", expected_status=409)
    assert fx.read_asset(asset["id"])["status"] == "QC_FAILED"


def test_a_nineteen_character_justification_is_refused(api):
    """The justification length is a shape rule with a pinned boundary.

    PRD §3.4: "The `waiver_justification` must be at least 20 characters —
    **exactly 20 is accepted, 19 is not** — otherwise
    `ERR_WAIVER_JUSTIFICATION_REQUIRED`."

    Design: Corner/errors/the_eleven_authority_and_waiver_ids_are_identity_tests_not_threshold_tests
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    asset = fx.setup_qc_failed_asset(plant, 600)
    assert asset["status"] == "QC_FAILED"

    nineteen = "Airs tonight anyway"
    assert len(nineteen) == 19
    resp = api.sign_qc_waiver(
        asset["id"],
        factories.qc_waiver_payload(plant["pd"]["id"], waiver_justification=nineteen),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_WAIVER_JUSTIFICATION_REQUIRED", expected_status=422)
    assert fx.read_asset(asset["id"])["status"] == "QC_FAILED"


def test_an_operator_may_not_authorize_their_own_override_request(api):
    """Segregation of duties is a comparison of two identifiers.

    PRD §3.8: "Segregation of duties applies: the acting user must differ from the
    override's `requested_by_operator_id`, otherwise
    `ERR_SELF_AUTHORIZATION_FORBIDDEN`."

    Design: Corner/errors/the_eleven_authority_and_waiver_ids_are_identity_tests_not_threshold_tests
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    requested = fx.request_override(plant, "CRAWL")
    assert requested["requested_by_operator_id"] == plant["mco"]["id"]
    assert plant["mco"]["override_authority"] == "CRAWL_AND_CUTIN"

    resp = api.activate_override(
        requested["id"],
        factories.activate_override_payload(plant["mco"]["id"], "CRAWL"),
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_SELF_AUTHORIZATION_FORBIDDEN", expected_status=409)

    after = fx.read_override(requested["id"])
    assert after["state"] == "PENDING"
    assert after.get("authorized_by_operator_id") is None


def test_a_mandatory_alert_needs_full_authority_not_merely_cut_in_authority(api):
    """The alert class raises the ladder above the mode actually requested.

    PRD §3.8: "an `alert_class` of `EAS_MANDATORY` additionally requires `FULL`
    regardless of the mode requested. Insufficient authority is refused with
    `ERR_OVERRIDE_AUTHORITY_INSUFFICIENT`."

    Design: Corner/errors/the_eleven_authority_and_waiver_ids_are_identity_tests_not_threshold_tests
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    deputy = fx.create_operator("MASTER_CONTROL", override_authority="CRAWL_AND_CUTIN",
                                full_name="Ines Baral")
    deputy_headers = make_master_control_headers(deputy["id"])
    requested = fx.request_override(plant, "CRAWL", alert_class="EAS_MANDATORY")

    resp = api.activate_override(
        requested["id"],
        factories.activate_override_payload(deputy["id"], "CRAWL"),
        deputy_headers,
    )
    validate_error(resp, "ERR_OVERRIDE_AUTHORITY_INSUFFICIENT", expected_status=403)
    assert fx.read_override(requested["id"])["state"] == "PENDING"


def test_a_channel_carrying_an_active_crawl_may_not_be_taken_dark(api):
    """An operator cannot silence the alert by darkening the channel under it.

    PRD §3.3: "An operator may not take a channel `DARK` while an emergency
    override on that channel is in state `ACTIVE_CRAWL` or `ACTIVE_CUTIN`; the
    attempt is refused with `ERR_EAS_OVERRIDE_ACTIVE`."

    Design: Corner/errors/the_eleven_authority_and_waiver_ids_are_identity_tests_not_threshold_tests
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    active = fx.setup_active_override(plant, "CRAWL")
    assert active["state"] == "ACTIVE_CRAWL"

    resp = api.change_channel_air_state(
        plant["ch1"]["id"], factories.air_state_payload("DARK"), plant["mco_headers"]
    )
    validate_error(resp, "ERR_EAS_OVERRIDE_ACTIVE", expected_status=409)

    channel = fx.read_channel(plant["ch1"]["id"])
    assert channel["air_status"] == "ON_AIR"
    assert channel["posture"] == "EMERGENCY"


def test_a_crawl_activation_without_crawl_text_is_refused(api):
    """A crawl has nothing to display unless some text is on file for it.

    PRD §3.8: "And a crawl activation, whether from `PENDING` or as a relaxation
    from a cut-in, requires a non-null `crawl_text`, otherwise
    `ERR_CRAWL_TEXT_REQUIRED`."

    Design: Corner/errors/the_eleven_authority_and_waiver_ids_are_identity_tests_not_threshold_tests
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    requested = fx.request_override(plant, "CUT_IN")
    assert requested.get("crawl_text") is None

    resp = api.activate_override(
        requested["id"],
        factories.activate_override_payload(plant["pd"]["id"], "CRAWL",
                                            crawl_text=None),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_CRAWL_TEXT_REQUIRED", expected_status=422)
    assert fx.read_override(requested["id"])["state"] == "PENDING"


def test_a_mandatory_alert_cannot_be_released_before_two_minutes(api):
    """The minimum on-air dwell is measured from the activation instant.

    PRD §3.8: "when `alert_class` is `EAS_MANDATORY`, it requires the same minimum
    of 120 seconds on air since `activated_utc`, refused otherwise with
    `ERR_EAS_MINIMUM_DURATION_NOT_MET`."

    Design: Corner/errors/the_eleven_authority_and_waiver_ids_are_identity_tests_not_threshold_tests
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    active = fx.setup_active_override(plant, "CRAWL", alert_class="EAS_MANDATORY")
    assert active["state"] == "ACTIVE_CRAWL"
    assert active["activated_utc"] == _CLOCK

    resp = api.release_override(active["id"], {}, plant["pd_headers"])
    validate_error(resp, "ERR_EAS_MINIMUM_DURATION_NOT_MET", expected_status=409)

    after = fx.read_override(active["id"])
    assert after["state"] == "ACTIVE_CRAWL"
    assert after.get("released_utc") is None


def test_rejecting_a_pending_request_without_a_reason_is_refused(api):
    """A rejection has to say why, since it is the terminal answer to the request.

    PRD §3.8: "A `PENDING` request may instead be rejected by a `ProgramDirector`,
    which requires a `rejection_reason`, otherwise
    `ERR_REJECTION_REASON_REQUIRED`."

    Design: Corner/errors/the_eleven_authority_and_waiver_ids_are_identity_tests_not_threshold_tests
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    requested = fx.request_override(plant, "CRAWL")
    assert requested["state"] == "PENDING"

    resp = api.release_override(requested["id"], {}, plant["pd_headers"])
    validate_error(resp, "ERR_REJECTION_REASON_REQUIRED", expected_status=422)

    after = fx.read_override(requested["id"])
    assert after["state"] == "PENDING"
    assert after.get("rejection_reason") is None


def test_mitigating_a_fault_without_a_code_is_refused(api):
    """The mitigation code is mandatory from both source states.

    PRD §3.3: "Mitigating a fault, whether from `ACKNOWLEDGED` or from
    `ESCALATED`, requires a `mitigation_code`; its absence yields
    `ERR_MITIGATION_CODE_REQUIRED`."

    Design: Corner/errors/the_eleven_authority_and_waiver_ids_are_identity_tests_not_threshold_tests
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    fault = fx.report_channel_fault(plant, "BLACK_FRAME", "MAJOR", _CLOCK)
    acknowledged = fx.advance_fault(plant, fault["id"], "ACKNOWLEDGED")
    assert acknowledged["state"] == "ACKNOWLEDGED"

    resp = api.change_fault_state(
        fault["id"], {"target_state": "MITIGATED"}, plant["mco_headers"]
    )
    validate_error(resp, "ERR_MITIGATION_CODE_REQUIRED", expected_status=422)

    after = fx.read_fault(fault["id"])
    assert after["state"] == "ACKNOWLEDGED"
    assert after.get("mitigation_code") is None


def test_escalating_a_fresh_fault_is_too_early(api):
    """Escalation needs two minutes of standing duration behind it.

    PRD §3.3: "Escalating requires that `duration_seconds` has reached at least 120
    seconds; **at exactly 120 seconds escalation is permitted**, and below that it
    is refused with `ERR_FAULT_ESCALATION_TOO_EARLY`."

    Design: Corner/errors/the_eleven_authority_and_waiver_ids_are_identity_tests_not_threshold_tests
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    fault = fx.report_channel_fault(plant, "CAPTION_LOSS", "MINOR", _CLOCK)
    acknowledged = fx.advance_fault(plant, fault["id"], "ACKNOWLEDGED")
    assert acknowledged["duration_seconds"] == 0

    resp = api.change_fault_state(
        fault["id"], {"target_state": "ESCALATED"}, plant["mco_headers"]
    )
    validate_error(resp, "ERR_FAULT_ESCALATION_TOO_EARLY", expected_status=409)

    after = fx.read_fault(fault["id"])
    assert after["state"] == "ACKNOWLEDGED"
    assert after["severity"] == "MINOR"


def test_a_report_naming_a_director_as_its_inspector_is_refused(api):
    """The inspector reference is checked against the operator's own role class.

    PRD §3.4: "`inspected_by_operator_id` must reference an operator whose
    `role_class` is `QC` and whose `status` is `ACTIVE`; a wrong role class yields
    `ERR_OPERATOR_ROLE_CLASS_INVALID`."

    Design: Corner/errors/the_eleven_authority_and_waiver_ids_are_identity_tests_not_threshold_tests
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    asset, version = _received_asset(plant, duration_seconds=600)
    assert plant["pd"]["role_class"] == "PROGRAM_DIRECTOR"

    resp = api.submit_qc_report(
        asset["id"],
        factories.qc_report_payload(version, plant["pd"]["id"],
                                    measured_duration_seconds=600),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_OPERATOR_ROLE_CLASS_INVALID", expected_status=409)
    assert fx.read_asset(asset["id"])["status"] == "RECEIVED"


# ===========================================================================
# The temporal identifiers: one interval rule each
# ===========================================================================

def test_a_one_second_hole_between_elements_is_a_gap(api):
    """Adjacency is mandatory, so a single second of dead air is refused.

    PRD §3.5: "if the next element's `scheduled_start_utc` is *after* that end
    there is a hole and the pass fails with `ERR_SCHEDULE_GAP_DETECTED` — **a
    one-second hole is a gap**"

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    items = [
        factories.playlist_item(1, "FILLER", "2026-08-01T12:00:00Z", 1800),
        factories.playlist_item(2, "FILLER", "2026-08-01T12:30:01Z", 1800),
    ]

    resp = api.ingest_playlist(
        factories.ingest_playlist_payload(plant["ch1"]["id"], items),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_SCHEDULE_GAP_DETECTED", expected_status=409)

    playlists, _meta = validate_paginated(
        api.list_channel_playlists(plant["ch1"]["id"], plant["traffic_headers"])
    )
    assert playlists == [], "a refused ingest must not leave a playlist behind"


def test_elements_that_collide_report_the_overlap(api):
    """Moving the same element half a minute earlier turns the hole into a collision.

    PRD §3.5: "if it is *before* that end the elements collide and the pass fails
    with `ERR_SCHEDULE_OVERLAP_DETECTED`."

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    items = [
        factories.playlist_item(1, "FILLER", "2026-08-01T12:00:00Z", 1800),
        factories.playlist_item(2, "FILLER", "2026-08-01T12:29:30Z", 1800),
    ]

    resp = api.ingest_playlist(
        factories.ingest_playlist_payload(plant["ch1"]["id"], items),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_SCHEDULE_OVERLAP_DETECTED", expected_status=409)


def test_exactly_touching_elements_are_accepted(api):
    """Zero seconds between two elements is the normal case, not an anomaly.

    PRD §3.5: "**A difference of exactly zero seconds is contiguous and legal**;
    touching elements are the normal case."

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    items = [
        factories.playlist_item(1, "FILLER", "2026-08-01T12:00:00Z", 1800),
        factories.playlist_item(2, "FILLER", "2026-08-01T12:30:00Z", 1800),
    ]

    playlist = validate_success(
        api.ingest_playlist(
            factories.ingest_playlist_payload(plant["ch1"]["id"], items),
            plant["traffic_headers"],
        ),
        201,
    )
    assert playlist["status"] == "IMPORTED"
    assert playlist["scheduled_total_seconds"] == 3600


def test_a_window_whose_guarded_span_touches_another_is_refused(api):
    """Feed windows are compared on their guarded spans with closed endpoints.

    PRD §3.7: "a new window's span from `join_utc` less `guard_seconds` through
    `breakaway_utc` plus `guard_seconds`, endpoints included, must not intersect
    the equally guarded span of any other window on the same channel whose `state`
    is `PLANNED` or `JOINED`."

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    scn = fx.setup_on_air_playlist()
    first = fx.create_window(scn, "2026-08-01T12:31:00Z", "2026-08-01T12:36:00Z")
    assert first["state"] == "PLANNED"

    resp = api.create_feed_window(
        factories.create_feed_window_payload(
            scn["ch1"]["id"], 4, "2026-08-01T12:35:00Z", "2026-08-01T12:38:00Z"),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_FEED_WINDOW_OVERLAP", expected_status=409)

    windows, _meta = validate_paginated(
        api.list_channel_feed_windows(scn["ch1"]["id"], scn["mco_headers"])
    )
    assert [w["id"] for w in windows] == [first["id"]]


def test_a_join_before_the_guard_opens_is_premature(api):
    """The guard window opens only guard_seconds before the planned join.

    PRD §3.7: "The join must also be issued inside the guard window: the logical
    clock must be at or after `join_utc` less `guard_seconds` and at or before
    `join_utc` plus a late-join limit of 30 seconds. Earlier is premature and later
    forfeits the window; either failure is `ERR_JOIN_OUTSIDE_GUARD_WINDOW`"

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    scn = fx.setup_on_air_playlist()
    window = fx.create_window(scn, "2026-08-01T12:31:00Z", "2026-08-01T12:36:00Z")
    assert window["guard_seconds"] == 2

    resp = api.join_feed_window(window["id"], {}, scn["mco_headers"])
    validate_error(resp, "ERR_JOIN_OUTSIDE_GUARD_WINDOW", expected_status=409)
    assert fx.read_feed_window(window["id"])["state"] == "PLANNED"


def test_a_breakaway_before_the_guard_instant_is_too_early(api):
    """The breakaway has its own guard instant, measured back from breakaway_utc.

    PRD §3.7: "It requires that the logical clock has reached at least
    `breakaway_utc` less `guard_seconds`; **at exactly that instant the breakaway
    is permitted** and any earlier attempt is refused with
    `ERR_BREAKAWAY_TOO_EARLY`."

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    scn = fx.setup_on_air_playlist()
    window = fx.create_window(scn, "2026-08-01T12:31:00Z", "2026-08-01T12:36:00Z")
    fx.set_clock("2026-08-01T12:31:00Z")
    joined = fx.join_window(scn, window["id"])
    assert joined["state"] == "JOINED"

    resp = api.breakaway_feed_window(window["id"], {}, scn["mco_headers"])
    validate_error(resp, "ERR_BREAKAWAY_TOO_EARLY", expected_status=409)
    assert fx.read_feed_window(window["id"])["state"] == "JOINED"


def test_a_window_claiming_more_encoder_units_than_the_pool_is_refused(api):
    """Encoder units are a multiplex-level pool with a hard ceiling.

    PRD §3.7: "The proposed window is refused with
    `ERR_ENCODER_CAPACITY_EXCEEDED` when the resulting peak would **exceed**
    `live_encoder_units_total`; **a peak exactly equal to the total is accepted**,
    and a peak one unit above it is not."

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    scn = fx.setup_on_air_playlist()
    assert fx.read_multiplex(scn["multiplex"]["id"])["live_encoder_units_total"] == 2

    resp = api.create_feed_window(
        factories.create_feed_window_payload(
            scn["ch1"]["id"], 4, "2026-08-01T12:31:00Z", "2026-08-01T12:36:00Z",
            live_encoder_units=3),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_ENCODER_CAPACITY_EXCEEDED", expected_status=409)

    windows, _meta = validate_paginated(
        api.list_channel_feed_windows(scn["ch1"]["id"], scn["mco_headers"])
    )
    assert windows == []


def test_a_second_pending_override_on_the_same_channel_is_refused(api):
    """A pending request already occupies the channel's single override slot.

    PRD §3.8: "any override on the channel whose `state` is `PENDING`,
    `ACTIVE_CRAWL` or `ACTIVE_CUTIN` blocks a new request with
    `ERR_OVERRIDE_WINDOW_OVERLAP`; only `RELEASED` and `REJECTED` overrides, which
    are terminal, leave the channel free."

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    first = fx.request_override(plant, "CRAWL")
    assert first["state"] == "PENDING"

    resp = api.create_override(
        factories.create_override_payload(plant["ch1"]["id"], plant["mco"]["id"],
                                         "CRAWL"),
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_OVERRIDE_WINDOW_OVERLAP", expected_status=409)

    sibling = validate_success(
        api.create_override(
            factories.create_override_payload(plant["ch2"]["id"], plant["mco"]["id"],
                                             "CRAWL"),
            plant["mco_headers"],
        ),
        201,
    )
    assert sibling["state"] == "PENDING", "the slot is per channel, not per station"


def test_an_event_earlier_than_the_last_as_run_entry_is_out_of_order(api):
    """The as-run log is append-only in time order.

    PRD §3.6: "`event_utc` must be at or after the `event_utc` of the most recent
    as-run entry for the same playlist, because the log is append-only in time
    order; an out-of-order event is refused with
    `ERR_PLAYOUT_EVENT_OUT_OF_ORDER`."

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    scn = fx.setup_on_air_playlist()
    first = scn["items"][0]
    fx.cue_item(scn, first["id"], "2026-08-01T11:59:00Z")
    assert fx.read_item(first["id"])["playout_status"] == "CUED"

    resp = api.post_playout_event(
        first["id"],
        factories.playout_event_payload("START", "2026-08-01T11:58:30Z"),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_PLAYOUT_EVENT_OUT_OF_ORDER", expected_status=409)
    assert fx.read_item(first["id"])["playout_status"] == "CUED"


def test_an_event_after_the_logical_clock_is_refused(api):
    """No event may claim to have happened later than the station's own clock.

    PRD §3.6: "`event_utc` must also be at or before the logical clock; a
    future-dated event is refused with `ERR_EVENT_TIMESTAMP_IN_FUTURE`."

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    scn = fx.setup_on_air_playlist()
    first = scn["items"][0]

    resp = api.post_playout_event(
        first["id"],
        factories.playout_event_payload("CUE", "2026-08-01T12:05:00Z"),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_EVENT_TIMESTAMP_IN_FUTURE", expected_status=409)

    assert fx.read_item(first["id"])["playout_status"] == "SCHEDULED"
    assert fx.list_item_as_run(first["id"], scn["mco_headers"]) == []


def test_setting_the_clock_to_its_present_value_is_refused(api):
    """The clock is strictly monotonic, so standing still is an error.

    PRD §2.4: "A clock advance must move strictly forward: a request whose
    `current_utc` equals or precedes the present clock value is rejected with
    `ERR_CLOCK_NOT_MONOTONIC`."

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    fx.set_clock(_CLOCK)

    validate_error(api.set_clock(_CLOCK, ADMIN), "ERR_CLOCK_NOT_MONOTONIC",
                   expected_status=409)
    validate_error(api.set_clock("2026-08-01T08:59:59Z", ADMIN),
                   "ERR_CLOCK_NOT_MONOTONIC", expected_status=409)

    moved = validate_success(api.set_clock("2026-08-01T09:00:01Z", ADMIN))
    assert moved is not None, "one second forward is a legal advance"


def test_a_delivery_past_the_hour_of_grace_is_refused(api):
    """The grace hour is the last word on a late delivery.

    PRD §3.4: "A delivery attempted once the logical clock has moved beyond the
    deadline plus that one-hour grace is refused with
    `ERR_DELIVERY_DEADLINE_PASSED`, because by then the clock checkpoint will have
    swept the asset to `EXPIRED`"

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    asset = fx.create_asset(plant, expected_duration_seconds=600)
    assert asset["delivery_deadline_utc"] == "2026-08-01T10:00:00Z"

    fx.set_clock("2026-08-01T11:00:01Z")
    resp = api.record_asset_delivery(
        asset["id"],
        factories.delivery_payload(received_utc="2026-08-01T11:00:01Z",
                                   measured_duration_seconds=600),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_DELIVERY_DEADLINE_PASSED", expected_status=409)
    assert fx.read_asset(asset["id"])["status"] != "RECEIVED"


def test_a_makegood_past_the_order_deadline_is_refused(api):
    """The makegood deadline is the first of the four makegood conditions.

    PRD §3.9: "**a makegood placed exactly at the deadline instant is accepted and
    one second later is refused** with `ERR_MAKEGOOD_DEADLINE_PASSED`, and **the
    deadline is checked before the inventory and credit rules**."

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    order = fx.create_order(plant, makegood_deadline_utc="2026-08-01T08:59:59Z")
    playlist = fx.ingest(
        plant, [factories.playlist_item(1, "FILLER", "2026-08-01T12:00:00Z", 3600)]
    )
    assert order["credited_spots"] == 0, "the credit rule is live but must not answer"

    resp = api.place_makegood(
        order["id"],
        factories.makegood_payload(playlist["id"], playlist["version"], 2,
                                   "2026-08-01T12:30:00Z"),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_MAKEGOOD_DEADLINE_PASSED", expected_status=409)
    assert fx.read_order(order["id"])["credited_spots"] == 0


def test_a_day_thirty_one_seconds_long_cannot_be_armed(api):
    """The arming tolerance is plus or minus thirty seconds of projected variance.

    PRD §3.5: "the absolute value of `projected_end_variance_seconds` must not
    exceed 30 seconds — **exactly plus or minus 30 seconds arms successfully and 31
    does not** — otherwise `ERR_ARM_VARIANCE_EXCEEDED`."

    Design: Corner/errors/the_thirteen_temporal_ids_each_own_one_interval_rule_and_none_is_a_generic_timing_error
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    asset = fx.setup_qc_passed_asset(plant, 3631)
    playlist = fx.ingest(
        plant,
        [factories.playlist_item(1, "PROGRAM", "2026-08-01T12:00:00Z", 3631,
                                 asset_id=asset["id"])],
    )
    validated = fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    assert validated["projected_end_variance_seconds"] == 31

    resp = api.change_playlist_state(
        playlist["id"], factories.playlist_state_payload("ARMED"), plant["mco_headers"]
    )
    validate_error(resp, "ERR_ARM_VARIANCE_EXCEEDED", expected_status=409)

    after = fx.read_playlist(playlist["id"])
    assert after["status"] == "VALIDATED"
    assert after.get("armed_at_utc") is None


# ===========================================================================
# The air-window identifiers and the uniqueness and shape identifiers
# ===========================================================================

def _armed_canonical_day(light_the_channel=True):
    """The canonical day validated and armed, with the clock still at 09:00.

    Arming a dark channel is legal — the channel gate belongs to the on-air
    transition — so the same helper serves both the too-early probe and the
    channel-not-on-air probe.
    """
    scn = fx.setup_playlist_scenario(fx.setup_base_plant(clock_utc=_CLOCK))
    fx.validate_playlist(scn)
    if light_the_channel:
        fx.set_air_status(scn, scn["ch1"]["id"], "ON_AIR")
    armed = fx.arm_playlist(scn)
    assert armed["status"] == "ARMED"
    return scn


def test_a_day_taken_to_air_more_than_five_minutes_early_is_refused(api):
    """The preroll tolerance is exactly 300 seconds wide.

    PRD §3.5: "the logical clock must have reached at least the playlist's
    `schedule_start_utc` less a 300-second preroll tolerance, so **at exactly five
    minutes before the booked start the transition is permitted** and any earlier
    attempt is refused with `ERR_PLAYLIST_AIR_TOO_EARLY`"

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    scn = _armed_canonical_day()
    assert scn["playlist"]["schedule_start_utc"] == "2026-08-01T12:00:00Z"

    resp = api.change_playlist_state(
        scn["playlist"]["id"], factories.playlist_state_payload("ON_AIR"),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_PLAYLIST_AIR_TOO_EARLY", expected_status=409)
    assert fx.read_playlist(scn["playlist"]["id"])["status"] == "ARMED"


def test_a_day_cannot_go_to_air_on_a_dark_channel(api):
    """The channel carries the day, so it must already be radiating.

    PRD §3.5: "**Taking a playlist to air** requires three things: the channel's
    own `air_status` must already be `ON_AIR`, otherwise
    `ERR_CHANNEL_NOT_ON_AIR`"

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    scn = _armed_canonical_day(light_the_channel=False)
    fx.set_clock("2026-08-01T11:55:00Z")
    assert fx.read_channel(scn["ch1"]["id"])["air_status"] == "DARK"

    resp = api.change_playlist_state(
        scn["playlist"]["id"], factories.playlist_state_payload("ON_AIR"),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_CHANNEL_NOT_ON_AIR", expected_status=409)
    assert fx.read_playlist(scn["playlist"]["id"])["status"] == "ARMED"


def test_a_channel_carries_only_one_on_air_day_at_a_time(api):
    """A second armed day cannot join the first one on air.

    PRD §3.5: "no other playlist on the same channel may already be `ON_AIR`,
    otherwise `ERR_CHANNEL_PLAYLIST_ALREADY_ON_AIR`."

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    scn = fx.setup_on_air_playlist()
    asset = fx.setup_qc_passed_asset(
        scn, 3600,
        asset_overrides={"delivery_deadline_utc": "2026-08-01T13:00:00Z"},
        delivery_overrides={"received_utc": "2026-08-01T11:59:00Z"},
    )
    # Only one playlist may exist per channel per broadcast_day (PRD §3.5), so the
    # second armed day is a different day on the same channel.
    second = fx.ingest(
        scn,
        [factories.playlist_item(1, "PROGRAM", "2026-08-01T11:00:00Z", 3600,
                                 asset_id=asset["id"])],
        broadcast_day="2026-08-02",
        schedule_start_utc="2026-08-01T11:00:00Z",
    )
    fx.drive_playlist(scn, second["id"], "VALIDATED")
    fx.drive_playlist(scn, second["id"], "ARMED")

    resp = api.change_playlist_state(
        second["id"], factories.playlist_state_payload("ON_AIR"), scn["mco_headers"]
    )
    validate_error(resp, "ERR_CHANNEL_PLAYLIST_ALREADY_ON_AIR", expected_status=409)

    assert fx.read_playlist(second["id"])["status"] == "ARMED"
    assert fx.read_playlist(scn["playlist"]["id"])["status"] == "ON_AIR"


def test_an_element_of_an_armed_day_cannot_be_cued(api):
    """Cueing belongs to the on-air day, not to the armed one.

    PRD §3.6: "**Cueing** an element requires four things: the owning playlist's
    `status` must be `ON_AIR`, otherwise `ERR_PLAYLIST_NOT_ON_AIR`"

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    scn = _armed_canonical_day()
    first = scn["items"][0]
    assert fx.read_item(first["id"])["clearance_status"] == "CLEARED"

    resp = api.post_playout_event(
        first["id"], factories.playout_event_payload("CUE", _CLOCK), scn["mco_headers"]
    )
    validate_error(resp, "ERR_PLAYLIST_NOT_ON_AIR", expected_status=409)
    assert fx.read_item(first["id"])["playout_status"] == "SCHEDULED"


def test_a_day_with_an_element_still_playing_cannot_be_closed(api):
    """The close is refused while automation still has an element on air.

    PRD §3.5: "**Closing** an on-air playlist requires that no item is still
    `PLAYING`, otherwise `ERR_PLAYLIST_ITEM_STILL_PLAYING`"

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    scn = fx.setup_playing_item1()
    assert scn["item1"]["playout_status"] == "PLAYING"

    resp = api.change_playlist_state(
        scn["playlist"]["id"], factories.playlist_state_payload("CLOSED"),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_PLAYLIST_ITEM_STILL_PLAYING", expected_status=409)

    after = fx.read_playlist(scn["playlist"]["id"])
    assert after["status"] == "ON_AIR"
    assert after.get("closed_at_utc") is None


def test_a_second_channel_claiming_the_same_number_is_refused(api):
    """Virtual channel numbers are unique station-wide.

    PRD §3.2: "`channel_number` is unique across the entire station and across all
    multiplexes, so two subchannels can never both claim 5.2; a collision yields
    `ERR_DUPLICATE_CHANNEL_NUMBER`."

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    multiplex = fx.read_multiplex(plant["multiplex"]["id"])
    assert plant["ch2"]["channel_number"] == "12.2"

    resp = api.create_channel(
        factories.create_channel_payload(
            multiplex["id"], multiplex["version"], call_sign="WXYZ-DT3",
            channel_number="12.2", resolution_class="SD_480I",
            requested_bitrate_kbps=2000, floor_bitrate_kbps=2000, priority_rank=3),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_DUPLICATE_CHANNEL_NUMBER", expected_status=409)

    channels, _meta = validate_paginated(api.list_channels(ADMIN))
    assert len(channels) == 2, "the refused admission must not add a channel"


def test_a_second_asset_claiming_the_same_house_number_is_refused(api):
    """House numbers are never recycled, so a collision is refused outright.

    PRD §3.4: "`house_number` is unique across every asset ever registered
    **including retracted and expired ones — a house number is never recycled**,
    and a collision yields `ERR_DUPLICATE_HOUSE_NUMBER`."

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    first = fx.create_asset(plant, expected_duration_seconds=600)

    resp = api.create_asset(
        factories.create_asset_payload(house_number=first["house_number"],
                                       expected_duration_seconds=600),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_DUPLICATE_HOUSE_NUMBER", expected_status=409)
    assert fx.read_asset(first["id"])["house_number"] == first["house_number"]


def test_a_second_order_claiming_the_same_reference_is_refused(api):
    """The traffic system's order reference is the order's unique key.

    PRD §3.9: "`order_reference` is unique across all orders and a collision
    yields `ERR_DUPLICATE_ORDER_REFERENCE`."

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    first = fx.create_order(plant)

    resp = api.create_spot_order(
        factories.create_spot_order_payload(
            plant["ch1"]["id"], order_reference=first["order_reference"],
            advertiser_name="Rival Motors"),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_DUPLICATE_ORDER_REFERENCE", expected_status=409)


def test_a_subchannel_without_a_parent_is_refused(api):
    """The submitted service class selects which parentage rule applies.

    PRD §3.2: "A `service_class` of `SUBCHANNEL` submitted without a
    `parent_channel_id` yields `ERR_SUBCHANNEL_PARENT_REQUIRED`"

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    multiplex = fx.read_multiplex(plant["multiplex"]["id"])

    payload = factories.create_channel_payload(
        multiplex["id"], multiplex["version"], call_sign="WXYZ-DT4",
        channel_number="12.4", service_class="SUBCHANNEL",
        resolution_class="SD_480I", requested_bitrate_kbps=2000,
        floor_bitrate_kbps=2000, priority_rank=3)
    validate_error(api.create_channel(payload, plant["eng_headers"]),
                   "ERR_SUBCHANNEL_PARENT_REQUIRED", expected_status=422)


def test_a_primary_channel_naming_a_parent_is_refused(api):
    """A primary channel carries a null parent by definition.

    PRD §3.2: "a `service_class` of `PRIMARY` submitted *with* a
    `parent_channel_id` yields `ERR_PRIMARY_CHANNEL_PARENT_FORBIDDEN` — which of
    the two codes applies is selected by the submitted `service_class`."

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    multiplex = fx.read_multiplex(plant["multiplex"]["id"])

    payload = factories.create_channel_payload(
        multiplex["id"], multiplex["version"], call_sign="WXYZ-DT5",
        channel_number="12.5", service_class="PRIMARY",
        resolution_class="SD_480I", requested_bitrate_kbps=2000,
        floor_bitrate_kbps=2000, priority_rank=3,
        parent_channel_id=plant["ch1"]["id"])
    validate_error(api.create_channel(payload, plant["eng_headers"]),
                   "ERR_PRIMARY_CHANNEL_PARENT_FORBIDDEN", expected_status=422)


def test_a_subchannel_may_not_hang_off_another_subchannel(api):
    """The parent chain is exactly one level deep.

    PRD §3.2: "`parent_channel_id` must reference a channel whose own
    `service_class` is `PRIMARY`, so a subchannel may not parent another
    subchannel and no channel may reference itself; a violation yields
    `ERR_INVALID_CHANNEL_PARENT`."

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    multiplex = fx.read_multiplex(plant["multiplex"]["id"])
    assert plant["ch2"]["service_class"] == "SUBCHANNEL"

    payload = factories.create_subchannel_payload(
        multiplex["id"], multiplex["version"], plant["ch2"]["id"],
        call_sign="WXYZ-DT6", channel_number="12.6",
        requested_bitrate_kbps=2000, floor_bitrate_kbps=2000, priority_rank=3)
    validate_error(api.create_channel(payload, plant["eng_headers"]),
                   "ERR_INVALID_CHANNEL_PARENT", expected_status=409)


def test_a_subchannel_may_not_hang_off_another_transport_stream(api):
    """The parent must sit on the multiplex named in the body.

    PRD §3.2: "the parent must sit on the same multiplex as the `multiplex_id`
    supplied in the body, because a subchannel cannot hang off a primary carried by
    another transmitter's transport stream; a cross-stream parent yields
    `ERR_CROSS_MULTIPLEX_PARENT`."

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    other_tx = fx.create_transmitter(plant["eng_headers"], facility_id="FAC-70022",
                                     call_sign="WQRS")
    other_mux = fx.create_multiplex(plant["eng_headers"], other_tx["id"],
                                    name="MUX-B")

    payload = factories.create_subchannel_payload(
        other_mux["id"], other_mux["version"], plant["ch1"]["id"],
        call_sign="WQRS-DT2", channel_number="33.2",
        requested_bitrate_kbps=2000, floor_bitrate_kbps=2000, priority_rank=2)
    validate_error(api.create_channel(payload, plant["eng_headers"]),
                   "ERR_CROSS_MULTIPLEX_PARENT", expected_status=409)


def test_a_floor_above_the_request_is_refused(api):
    """A channel may not demand a floor it never asked to be funded to.

    PRD §3.2: "`floor_bitrate_kbps` may not exceed `requested_bitrate_kbps`;
    equality is legal and makes the channel an all-or-nothing claimant in the
    waterfall, while a floor above the request yields
    `ERR_BITRATE_FLOOR_EXCEEDS_REQUEST`."

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    multiplex = fx.read_multiplex(plant["multiplex"]["id"])

    payload = factories.create_channel_payload(
        multiplex["id"], multiplex["version"], call_sign="WXYZ-DT7",
        channel_number="12.7", resolution_class="HD_1080I",
        requested_bitrate_kbps=8000, floor_bitrate_kbps=9000, priority_rank=3)
    validate_error(api.create_channel(payload, plant["eng_headers"]),
                   "ERR_BITRATE_FLOOR_EXCEEDS_REQUEST", expected_status=422)


def test_a_floor_below_the_resolution_minimum_is_refused(api):
    """Each resolution class has a floor of its own that the request cannot undercut.

    PRD §3.2: "`floor_bitrate_kbps` must be at least the minimum for its
    `resolution_class` — 8000 for `HD_1080I`, 5000 for `HD_720P`, 2000 for
    `SD_480I` — where exactly the minimum is legal and one kilobit below it is
    not, yielding `ERR_BITRATE_FLOOR_BELOW_RESOLUTION_MINIMUM`."

    Design: Corner/errors/five_air_window_ids_and_nine_shape_uniqueness_ids_never_collapse_into_each_other
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    multiplex = fx.read_multiplex(plant["multiplex"]["id"])

    payload = factories.create_channel_payload(
        multiplex["id"], multiplex["version"], call_sign="WXYZ-DT8",
        channel_number="12.8", resolution_class="SD_480I",
        requested_bitrate_kbps=6000, floor_bitrate_kbps=1999, priority_rank=3)
    validate_error(api.create_channel(payload, plant["eng_headers"]),
                   "ERR_BITRATE_FLOOR_BELOW_RESOLUTION_MINIMUM", expected_status=422)


# ===========================================================================
# The referential, inventory and arithmetic identifiers
# ===========================================================================

def test_an_ingest_with_no_items_at_all_is_refused(api):
    """A broadcast day must arrive with something on it.

    PRD §3.5: "**At least one item must have been supplied**; an ingest with an
    empty `items` array is refused with `ERR_PLAYLIST_EMPTY_INGEST`."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    resp = api.ingest_playlist(
        factories.ingest_playlist_payload(plant["ch1"]["id"], []),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_PLAYLIST_EMPTY_INGEST", expected_status=422)

    playlists, _meta = validate_paginated(
        api.list_channel_playlists(plant["ch1"]["id"], plant["traffic_headers"])
    )
    assert playlists == []


def test_a_day_of_filler_alone_cannot_be_validated(api):
    """Validation insists on at least one programme element.

    PRD §3.5: "There must be at least one item and at least one item whose
    `element_kind` is `PROGRAM`, otherwise `ERR_PLAYLIST_NO_PROGRAM_CONTENT` — a
    list made entirely of commercials, promos and filler is not a broadcast day."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    playlist = fx.ingest(
        plant, [factories.playlist_item(1, "FILLER", "2026-08-01T12:00:00Z", 3600)]
    )
    assert playlist["status"] == "IMPORTED"

    resp = api.change_playlist_state(
        playlist["id"], factories.playlist_state_payload("VALIDATED"),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_PLAYLIST_NO_PROGRAM_CONTENT", expected_status=409)
    assert fx.read_playlist(playlist["id"])["status"] == "IMPORTED"


def test_a_revision_repeating_a_sequence_number_is_refused(api):
    """A revision's own items must form a dense run with no duplicates.

    PRD §3.5: "Within one playlist, `sequence_number` is unique and the submitted
    revision's items must form **a dense run from 1 to N with no duplicates and no
    holes**, otherwise `ERR_SEQUENCE_NUMBER_CONFLICT`."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    playlist = fx.ingest(
        plant, [factories.playlist_item(1, "FILLER", "2026-08-01T12:00:00Z", 3600)]
    )
    twice = [
        factories.playlist_item(1, "FILLER", "2026-08-01T12:00:00Z", 1800),
        factories.playlist_item(1, "FILLER", "2026-08-01T12:30:00Z", 1800),
    ]

    resp = api.apply_traffic_revision(
        playlist["id"],
        factories.traffic_revision_payload(playlist["version"], twice),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_SEQUENCE_NUMBER_CONFLICT", expected_status=409)

    after = fx.read_playlist(playlist["id"])
    assert after["version"] == playlist["version"]
    assert after["item_count"] == 1


def test_a_window_naming_an_anchor_that_does_not_exist_is_refused(api):
    """The anchor is resolved against the channel's own on-air day.

    PRD §3.7: "`anchor_sequence_number` must be at least 1 and must match an
    existing element's `sequence_number` in the channel's most recently armed or
    on-air playlist, and **that element's `element_kind` must be
    `NETWORK_JOIN`**; otherwise the plan is refused with
    `ERR_ANCHOR_ITEM_NOT_FOUND`."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    scn = fx.setup_on_air_playlist()
    assert len(scn["items"]) == 7, "no element carries sequence number 99"

    resp = api.create_feed_window(
        factories.create_feed_window_payload(
            scn["ch1"]["id"], 99, "2026-08-01T12:31:00Z", "2026-08-01T12:36:00Z"),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_ANCHOR_ITEM_NOT_FOUND", expected_status=409)


def test_a_substitute_of_the_wrong_resolution_is_refused(api):
    """The replacement must match the resolution the outgoing element required.

    PRD §3.6: "The replacement asset's `delivered_resolution_class` must equal the
    outgoing element's asset's `required_resolution_class`, and the replacement's
    `measured_duration_seconds` must lie within the outgoing element's
    `max_trim_seconds` of the outgoing `scheduled_duration_seconds`; either failure
    is refused with `ERR_SUBSTITUTE_RESOLUTION_MISMATCH`."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    scn = fx.setup_on_air_playlist()
    replacement = fx.setup_qc_passed_asset(
        scn, 1800,
        asset_overrides={"required_resolution_class": "SD_480I",
                         "delivery_deadline_utc": "2026-08-01T13:00:00Z"},
        delivery_overrides={"received_utc": "2026-08-01T11:59:00Z"},
    )
    assert replacement["delivered_resolution_class"] == "SD_480I"
    assert replacement["status"] == "QC_PASSED"
    first = scn["items"][0]

    resp = api.substitute_item(
        first["id"], factories.substitute_payload(replacement["id"]),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_SUBSTITUTE_RESOLUTION_MISMATCH", expected_status=409)
    assert fx.read_item(first["id"])["asset_id"] == first["asset_id"]


def test_a_substitute_already_placed_in_the_same_hour_is_refused(api):
    """The same media may not be double-booked inside one hour of the day.

    PRD §3.6: "The replacement must not already be placed as an unaired element in
    the same playlist hour, otherwise `ERR_ITEM_PLAYLIST_MISMATCH`."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    scn = fx.setup_on_air_playlist()
    spot_asset = scn["assets"]["spot"]
    second, third = scn["items"][1], scn["items"][2]
    assert second["asset_id"] == spot_asset["id"]
    assert fx.read_item(second["id"])["playout_status"] == "SCHEDULED"

    resp = api.substitute_item(
        third["id"], factories.substitute_payload(spot_asset["id"]),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_ITEM_PLAYLIST_MISMATCH", expected_status=409)


def test_a_filing_without_reference_or_narrative_is_refused(api):
    """The regulator's reference and the narrative are both mandatory.

    PRD §3.1: "A filing supplies `filed_reference`, the regulator-assigned
    reference, and `narrative`, the filing text; either being absent yields
    `ERR_FILING_DETAILS_REQUIRED`."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    fx.change_power_state(plant, "REDUCED_POWER", power_pct=79, reason="COOLING_FAULT")
    notification = fx.list_notifications(plant["transmitter"]["id"], COMPLIANCE)[0]
    assert notification["status"] == "PENDING"

    validate_error(api.file_notification(notification["id"], {}, COMPLIANCE),
                   "ERR_FILING_DETAILS_REQUIRED", expected_status=422)
    validate_error(
        api.file_notification(notification["id"],
                              {"filed_reference": "FCC-REF-0009"}, COMPLIANCE),
        "ERR_FILING_DETAILS_REQUIRED", expected_status=422)

    assert fx.read_notification(notification["id"])["status"] == "PENDING"


def test_an_element_booking_another_channel_s_order_is_refused(api):
    """A spot order is sold on one channel and can only be placed there.

    PRD §3.5: "an item's `spot_order_id` must reference a spot order whose own
    `channel_id` equals the playlist's `channel_id`, otherwise
    `ERR_SPOT_ORDER_CHANNEL_MISMATCH`."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    other_order = fx.create_order(plant, channel_id=plant["ch2"]["id"])
    assert other_order["channel_id"] == plant["ch2"]["id"]

    items = [
        factories.playlist_item(1, "FILLER", "2026-08-01T12:00:00Z", 3570),
        factories.playlist_item(2, "COMMERCIAL", "2026-08-01T12:59:30Z", 30,
                                spot_order_id=other_order["id"]),
    ]
    resp = api.ingest_playlist(
        factories.ingest_playlist_payload(plant["ch1"]["id"], items),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_SPOT_ORDER_CHANNEL_MISMATCH", expected_status=409)


def test_a_fault_aimed_at_the_wrong_kind_of_target_is_refused(api):
    """Plant conditions name a transmitter and service conditions name a channel.

    PRD §3.3: "a fault coded `RF_POWER_FAULT` or `LOSS_OF_SIGNAL` requires a
    `transmitter_id` because those conditions are properties of the plant rather
    than of a service; and a fault coded `AUDIO_LOSS`, `BLACK_FRAME` or
    `CAPTION_LOSS` requires a `channel_id` because those are observed on a service.
    Any of those mismatches yields `ERR_FAULT_TARGET_MISMATCH`."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)

    validate_error(
        api.report_fault(
            factories.report_fault_payload("AUDIO_LOSS", "MAJOR", _CLOCK,
                                          transmitter_id=plant["transmitter"]["id"]),
            plant["mco_headers"]),
        "ERR_FAULT_TARGET_MISMATCH", expected_status=409)

    validate_error(
        api.report_fault(
            factories.report_fault_payload("LOSS_OF_SIGNAL", "CRITICAL", _CLOCK,
                                          channel_id=plant["ch1"]["id"]),
            plant["mco_headers"]),
        "ERR_FAULT_TARGET_MISMATCH", expected_status=409)

    assert fx.read_channel(plant["ch1"]["id"])["open_fault_count"] == 0


def test_an_hour_carrying_961_seconds_of_commercials_is_refused(api):
    """The hourly commercial ceiling is 960 seconds exactly.

    PRD §3.5: "No hour may carry **more than 960 seconds — sixteen minutes — of
    commercial elements; exactly 960 is accepted and 961 is refused** with
    `ERR_COMMERCIAL_INVENTORY_EXCEEDED`."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    items = [
        factories.playlist_item(1, "COMMERCIAL", "2026-08-01T12:00:00Z", 961),
        factories.playlist_item(2, "FILLER", "2026-08-01T12:16:01Z", 2639),
    ]

    resp = api.ingest_playlist(
        factories.ingest_playlist_payload(plant["ch1"]["id"], items),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_COMMERCIAL_INVENTORY_EXCEEDED", expected_status=409)


def test_a_makegood_on_an_order_with_no_credit_is_refused(api):
    """There must be a credited spot to reverse before a makegood can be placed.

    PRD §3.9: "The order must have `credited_spots` of at least 1, because there
    must be a credited spot to reverse; **a `credited_spots` of 0 is refused with
    `ERR_NO_CREDITED_SPOT_TO_MAKEGOOD` even when the order is `PARTIALLY_CREDITED`
    for other reasons**"

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    order = fx.create_order(plant)
    assert order["credited_spots"] == 0
    assert order["makegood_deadline_utc"] == "2026-08-31T00:00:00Z"
    playlist = fx.ingest(
        plant, [factories.playlist_item(1, "FILLER", "2026-08-01T12:00:00Z", 3600)]
    )

    resp = api.place_makegood(
        order["id"],
        factories.makegood_payload(playlist["id"], playlist["version"], 2,
                                   "2026-08-01T12:30:00Z"),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_NO_CREDITED_SPOT_TO_MAKEGOOD", expected_status=409)
    assert fx.read_order(order["id"])["scheduled_spots"] == 0


def test_a_cut_in_may_not_preempt_a_guaranteed_spot_unforced(api):
    """Guaranteed inventory is preempted only when the request says so explicitly.

    PRD §3.8: "only spots whose order's `priority_class` is `PREEMPTIBLE` or
    `REMNANT` are eligible, and a `GUARANTEED` spot is preempted only when the
    activation carries `force_preempt_guaranteed` set to true, otherwise the
    activation is refused with `ERR_ORDER_NOT_PREEMPTIBLE`."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    assets = fx.setup_cleared_assets(plant)
    order = fx.create_order(plant, priority_class="GUARANTEED")
    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": assets["prog1"]["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1800},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": assets["spot"]["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T12:30:00Z",
         "scheduled_duration_seconds": 30},
        {"sequence_number": 3, "element_kind": "FILLER",
         "scheduled_start_utc": "2026-08-01T12:30:30Z",
         "scheduled_duration_seconds": 1770},
    ]
    playlist = fx.ingest(plant, items)
    fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    fx.drive_playlist(plant, playlist["id"], "ARMED")
    fx.set_clock("2026-08-01T11:59:00Z")
    on_air = fx.drive_playlist(plant, playlist["id"], "ON_AIR")
    assert on_air["status"] == "ON_AIR"

    requested = fx.request_override(plant, "CUT_IN", expected_duration_seconds=2400)
    resp = api.activate_override(
        requested["id"],
        factories.activate_override_payload(plant["pd"]["id"], "CUT_IN"),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_ORDER_NOT_PREEMPTIBLE", expected_status=409)

    assert fx.read_override(requested["id"])["state"] == "PENDING"
    assert fx.read_order(order["id"])["credited_spots"] == 0
    assert fx.read_channel(plant["ch1"]["id"])["air_status"] == "ON_AIR"


def test_an_admission_whose_floors_cannot_all_fit_is_refused(api):
    """Feasibility is judged on the sum of the floors that must be honoured.

    PRD §3.2: "If the sum of `floor_bitrate_kbps` over the channels that would have
    to be `ACTIVE` exceeds `effective_capacity_kbps`, no feasible allocation exists
    and the request is refused with `ERR_BITRATE_FLOOR_UNSATISFIABLE`"

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    multiplex = fx.read_multiplex(plant["multiplex"]["id"])
    assert multiplex["effective_capacity_kbps"] == 38000

    payload = factories.create_channel_payload(
        multiplex["id"], multiplex["version"], call_sign="WXYZ-DT9",
        channel_number="12.9", resolution_class="HD_1080I",
        requested_bitrate_kbps=29000, floor_bitrate_kbps=29000, priority_rank=3)
    validate_error(api.create_channel(payload, plant["eng_headers"]),
                   "ERR_BITRATE_FLOOR_UNSATISFIABLE", expected_status=409)

    assert fx.read_multiplex(multiplex["id"])["assigned_kbps"] == 22000


def test_a_pin_above_the_effective_capacity_is_refused(api):
    """The capacity gate is the last word in the whole ladder.

    PRD §3.2: "an explicit pin — `pin_allocated_kbps` on a demand change — or an
    admission that must be accepted as `ACTIVE` is refused with
    `ERR_MULTIPLEX_CAPACITY_EXCEEDED` when the resulting pinned total would exceed
    the multiplex's `effective_capacity_kbps`; a total exactly equal to the
    effective capacity is accepted."

    Design: Corner/errors/the_final_fifteen_ids_cover_referential_inventory_and_arithmetic_refusals
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    multiplex = fx.read_multiplex(plant["multiplex"]["id"])

    resp = api.patch_channel_allocation(
        plant["ch1"]["id"],
        factories.allocation_patch_payload(multiplex["version"],
                                           pin_allocated_kbps=38500),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_MULTIPLEX_CAPACITY_EXCEEDED", expected_status=409)

    after = fx.read_channel(plant["ch1"]["id"])
    assert after["allocated_bitrate_kbps"] == 16000
    assert fx.read_multiplex(multiplex["id"])["available_kbps"] == 16000
