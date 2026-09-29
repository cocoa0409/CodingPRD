"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD endpoints only,
starting from an empty database and a logical clock that still reads its initial
value. Setup calls use the lenient success validator so a broken precondition
surfaces as a setup failure rather than as a confusing assertion.

Identity threading: the four entity-backed roles always act with the id of the
Operator row they were minted from (see test_users.make_*_headers).
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    activate_override_payload,
    air_state_payload,
    create_asset_payload,
    create_channel_payload,
    create_feed_window_payload,
    create_multiplex_payload,
    create_operator_payload,
    create_override_payload,
    create_spot_order_payload,
    create_subchannel_payload,
    create_transmitter_payload,
    delivery_payload,
    ingest_playlist_payload,
    playlist_state_payload,
    playout_event_payload,
    power_state_payload,
    qc_report_payload,
    qc_waiver_payload,
    report_fault_payload,
)
from .test_users import (
    make_admin_headers,
    make_compliance_headers,
    make_engineer_headers,
    make_master_control_headers,
    make_program_director_headers,
    make_qc_headers,
    make_traffic_headers,
)

ADMIN = make_admin_headers()
TRAFFIC = make_traffic_headers()
COMPLIANCE = make_compliance_headers()


# ===========================================================================
# Tier 0 — primitives
# ===========================================================================

def set_clock(current_utc: str, headers: Optional[dict] = None) -> dict:
    """Advance the server's logical clock and run the ops-run checkpoint."""
    resp = api_client.set_clock(current_utc, headers or ADMIN)
    return get_success_data(resp)


def create_operator(role_class: str, override_authority: str = "NONE",
                    certification_expires_utc: Optional[str] = None,
                    full_name: Optional[str] = None, **overrides) -> dict:
    payload = create_operator_payload(
        role_class,
        override_authority=override_authority,
        certification_expires_utc=certification_expires_utc
        or TEST_DEFAULTS["CERT_FAR_FUTURE"],
        **overrides,
    )
    if full_name:
        payload["full_name"] = full_name
    return get_success_data(api_client.create_operator(payload, ADMIN))


def suspend_operator(operator_id: str) -> dict:
    return get_success_data(
        api_client.update_operator_status(operator_id, {"status": "SUSPENDED"}, ADMIN)
    )


def create_transmitter(engineer_headers: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_transmitter(create_transmitter_payload(**overrides),
                                      engineer_headers)
    )


def create_multiplex(engineer_headers: dict, transmitter_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_multiplex(
            create_multiplex_payload(transmitter_id, **overrides), engineer_headers
        )
    )


def create_channel(engineer_headers: dict, multiplex_id: str,
                   expected_multiplex_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_channel(
            create_channel_payload(multiplex_id, expected_multiplex_version, **overrides),
            engineer_headers,
        )
    )


def create_subchannel(engineer_headers: dict, multiplex_id: str,
                      expected_multiplex_version: int, parent_channel_id: str,
                      **overrides) -> dict:
    return get_success_data(
        api_client.create_channel(
            create_subchannel_payload(multiplex_id, expected_multiplex_version,
                                      parent_channel_id, **overrides),
            engineer_headers,
        )
    )


# ---------------------------------------------------------------- read helpers

def read_transmitter(transmitter_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_transmitter(transmitter_id, headers or ADMIN))


def read_multiplex(multiplex_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_multiplex(multiplex_id, headers or ADMIN))


def read_channel(channel_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_channel(channel_id, headers or ADMIN))


def read_operator(operator_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_operator(operator_id, headers or ADMIN))


def read_asset(asset_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_asset(asset_id, headers or ADMIN))


def read_playlist(playlist_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_playlist(playlist_id, headers or ADMIN))


def read_item(item_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_playlist_item(item_id, headers or ADMIN))


def read_order(order_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_spot_order(order_id, headers or ADMIN))


def read_override(override_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_override(override_id, headers or ADMIN))


def read_fault(fault_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_fault(fault_id, headers or ADMIN))


def read_feed_window(window_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_feed_window(window_id, headers or ADMIN))


def read_notification(notification_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_notification(notification_id, headers or ADMIN))


def list_items(playlist_id: str, headers: Optional[dict] = None, params=None) -> List[dict]:
    return get_success_data(
        api_client.list_playlist_items(playlist_id, headers or ADMIN, params=params)
    )


def list_as_run(playlist_id: str, headers: Optional[dict] = None, params=None) -> List[dict]:
    return get_success_data(
        api_client.get_playlist_as_run(playlist_id, headers or ADMIN, params=params)
    )


def list_item_as_run(item_id: str, headers: Optional[dict] = None, params=None) -> List[dict]:
    return get_success_data(
        api_client.get_item_as_run(item_id, headers or ADMIN, params=params)
    )


def list_notifications(transmitter_id: str, headers: Optional[dict] = None,
                       params=None) -> List[dict]:
    return get_success_data(
        api_client.list_transmitter_notifications(transmitter_id, headers or COMPLIANCE,
                                                 params=params)
    )


# ===========================================================================
# Tier 1 — the operator bench and the plant graph
# ===========================================================================

def bootstrap_operators(clock_utc: Optional[str] = None,
                        cert_expires: Optional[str] = None) -> dict:
    """Advance the clock off its initial value and mint the four operator identities.

    Returns a dict carrying every operator row plus ready-made headers.
    """
    set_clock(clock_utc or TEST_DEFAULTS["CLOCK_T0"])
    cert = cert_expires or TEST_DEFAULTS["CERT_FAR_FUTURE"]
    eng = create_operator("ENGINEER", "NONE", cert, full_name="Ada Rowe")
    mco = create_operator("MASTER_CONTROL", "CRAWL_AND_CUTIN", cert, full_name="Ben Ochs")
    qc = create_operator("QC", "NONE", cert, full_name="Cara Vale")
    pd = create_operator("PROGRAM_DIRECTOR", "FULL", cert, full_name="Dov Imre")
    return {
        "eng": eng, "mco": mco, "qc": qc, "pd": pd,
        "eng_headers": make_engineer_headers(eng["id"]),
        "mco_headers": make_master_control_headers(mco["id"]),
        "qc_headers": make_qc_headers(qc["id"]),
        "pd_headers": make_program_director_headers(pd["id"]),
        "admin_headers": ADMIN,
        "traffic_headers": TRAFFIC,
        "compliance_headers": COMPLIANCE,
    }


def setup_base_plant(with_subchannel: bool = True,
                     clock_utc: Optional[str] = None,
                     mux_overrides: Optional[dict] = None,
                     ch1_overrides: Optional[dict] = None,
                     ch2_overrides: Optional[dict] = None) -> dict:
    """Clock + four operators + one FULL_POWER transmitter + MUX-A + ch1 (+ ch2).

    Pinned arithmetic: MUX-A total 38800 with pilot 800 at derate 1.00 gives an
    effective pool of 38000 kbps. ch1 (rank 1, floor 8000, request 16000) and
    ch2 (rank 2, floor 2000, request 6000) end at 16000 and 6000 kbps, so the
    multiplex reports assigned 22000 and available 16000.
    """
    plant = bootstrap_operators(clock_utc=clock_utc)
    eng = plant["eng_headers"]
    plant["transmitter"] = create_transmitter(eng)
    plant["multiplex"] = create_multiplex(eng, plant["transmitter"]["id"],
                                          **(mux_overrides or {}))
    plant["ch1"] = create_channel(eng, plant["multiplex"]["id"],
                                  plant["multiplex"]["version"],
                                  **(ch1_overrides or {}))
    if with_subchannel:
        mux = read_multiplex(plant["multiplex"]["id"], eng)
        plant["ch2"] = create_subchannel(eng, plant["multiplex"]["id"], mux["version"],
                                         plant["ch1"]["id"], **(ch2_overrides or {}))
    plant["multiplex"] = read_multiplex(plant["multiplex"]["id"], eng)
    return plant


def change_power_state(plant: dict, target_state: str, **overrides) -> dict:
    return get_success_data(
        api_client.change_transmitter_power_state(
            plant["transmitter"]["id"],
            power_state_payload(target_state, **overrides),
            plant["eng_headers"],
        )
    )


def rebalance(plant: dict, expected_multiplex_version: int, **overrides) -> dict:
    payload = {"expected_multiplex_version": expected_multiplex_version}
    payload.update(overrides)
    return get_success_data(
        api_client.rebalance_multiplex(plant["multiplex"]["id"], payload,
                                       plant["eng_headers"])
    )


def set_air_status(plant: dict, channel_id: str, target_air_status: str,
                   **overrides) -> dict:
    return get_success_data(
        api_client.change_channel_air_state(
            channel_id, air_state_payload(target_air_status, **overrides),
            plant["mco_headers"],
        )
    )


# ===========================================================================
# Tier 2 — assets, delivery and the quality-control chain
# ===========================================================================

def create_asset(plant: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_asset(create_asset_payload(**overrides),
                               plant["traffic_headers"])
    )


def deliver_asset(plant: dict, asset_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.record_asset_delivery(asset_id, delivery_payload(**overrides),
                                        plant["traffic_headers"])
    )


def submit_qc(plant: dict, asset_id: str, expected_asset_version: int,
              inspected_by_operator_id: Optional[str] = None, **overrides) -> dict:
    return get_success_data(
        api_client.submit_qc_report(
            asset_id,
            qc_report_payload(expected_asset_version,
                              inspected_by_operator_id or plant["qc"]["id"],
                              **overrides),
            plant["qc_headers"],
        )
    )


def sign_waiver(plant: dict, asset_id: str,
                waived_by_operator_id: Optional[str] = None, **overrides) -> dict:
    return get_success_data(
        api_client.sign_qc_waiver(
            asset_id,
            qc_waiver_payload(waived_by_operator_id or plant["pd"]["id"], **overrides),
            plant["pd_headers"],
        )
    )


def retract(plant: dict, asset_id: str, reason: str = "Rights pull from the distributor") -> dict:
    return get_success_data(
        api_client.retract_asset(asset_id, {"reason": reason}, plant["pd_headers"])
    )


def setup_qc_passed_asset(plant: dict, duration_seconds: int = 1800,
                          asset_overrides: Optional[dict] = None,
                          delivery_overrides: Optional[dict] = None,
                          qc_overrides: Optional[dict] = None) -> dict:
    """Register, deliver and pass an asset so it reaches QC_PASSED.

    With measured duration equal to expected, loudness exactly on target, no
    defect codes and the delivered resolution matching the requirement, the
    score is a clean 100 and the verdict is PASS.
    """
    a_over = {"expected_duration_seconds": duration_seconds}
    a_over.update(asset_overrides or {})
    # This helper is also called by scenarios whose logical clock has already been
    # driven well past the canonical broadcast hour. PRD §3.4 refuses a delivery
    # once the clock is beyond the deadline plus the one-hour grace, so the default
    # deadline has to sit far enough ahead to keep the delivery legal from any of
    # them; callers that are testing the deadline itself override it.
    a_over.setdefault("delivery_deadline_utc", TEST_DEFAULTS["ASSET_DEADLINE_FAR_FUTURE"])
    asset = create_asset(plant, **a_over)

    d_over = {"measured_duration_seconds": duration_seconds}
    if "required_resolution_class" in a_over:
        d_over["delivered_resolution_class"] = a_over["required_resolution_class"]
    if a_over.get("captions_required"):
        d_over["caption_present"] = True
        d_over["caption_language"] = "en"
    d_over.update(delivery_overrides or {})
    delivered = deliver_asset(plant, asset["id"], **d_over)

    q_over = {"measured_duration_seconds": duration_seconds}
    q_over.update(qc_overrides or {})
    submit_qc(plant, asset["id"], delivered["version"], **q_over)
    return read_asset(asset["id"], plant["qc_headers"])


def setup_qc_failed_asset(plant: dict, duration_seconds: int = 1800,
                          defect_codes: Optional[List[str]] = None,
                          asset_overrides: Optional[dict] = None,
                          delivery_overrides: Optional[dict] = None,
                          qc_overrides: Optional[dict] = None) -> dict:
    """Drive an asset to QC_FAILED through a failing ingest report."""
    q_over = {"defect_codes": defect_codes if defect_codes is not None else ["AUDIO_LOSS"]}
    q_over.update(qc_overrides or {})
    return setup_qc_passed_asset(
        plant, duration_seconds,
        asset_overrides=asset_overrides,
        delivery_overrides=delivery_overrides,
        qc_overrides=q_over,
    )


# ===========================================================================
# Tier 3 — spot orders and the canonical broadcast day
# ===========================================================================

def create_order(plant: dict, channel_id: Optional[str] = None, **overrides) -> dict:
    payload = create_spot_order_payload(channel_id or plant["ch1"]["id"], **overrides)
    payload.setdefault("order_reference", TEST_DEFAULTS["ORD1_REFERENCE"])
    return get_success_data(
        api_client.create_spot_order(payload, plant["traffic_headers"])
    )


def ingest(plant: dict, items: List[dict], channel_id: Optional[str] = None,
           **overrides) -> dict:
    return get_success_data(
        api_client.ingest_playlist(
            ingest_playlist_payload(channel_id or plant["ch1"]["id"], items, **overrides),
            plant["traffic_headers"],
        )
    )


def canonical_day_items(assets: dict, order_id: str) -> List[dict]:
    """The pinned seven-element broadcast day.

    Durations 1800 + 30 + 30 + 300 + 60 + 60 + 1320 sum to exactly 3600, which
    equals the window, so the projected end variance is 0 and the playlist arms.
    Only the two COMMERCIAL elements count as inventory, 60 seconds in hour 0.
    """
    return [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": assets["prog1"]["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1800},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": assets["spot"]["id"], "spot_order_id": order_id,
         "scheduled_start_utc": "2026-08-01T12:30:00Z",
         "scheduled_duration_seconds": 30},
        {"sequence_number": 3, "element_kind": "COMMERCIAL",
         "asset_id": assets["spot"]["id"], "spot_order_id": order_id,
         "scheduled_start_utc": "2026-08-01T12:30:30Z",
         "scheduled_duration_seconds": 30},
        {"sequence_number": 4, "element_kind": "NETWORK_JOIN",
         "scheduled_start_utc": "2026-08-01T12:31:00Z",
         "scheduled_duration_seconds": 300},
        {"sequence_number": 5, "element_kind": "PROMO",
         "asset_id": assets["short"]["id"],
         "scheduled_start_utc": "2026-08-01T12:36:00Z",
         "scheduled_duration_seconds": 60, "max_trim_seconds": 30},
        {"sequence_number": 6, "element_kind": "INTERSTITIAL",
         "asset_id": assets["short"]["id"],
         "scheduled_start_utc": "2026-08-01T12:37:00Z",
         "scheduled_duration_seconds": 60, "max_trim_seconds": 20},
        {"sequence_number": 7, "element_kind": "PROGRAM",
         "asset_id": assets["prog2"]["id"],
         "scheduled_start_utc": "2026-08-01T12:38:00Z",
         "scheduled_duration_seconds": 1320},
    ]


def setup_cleared_assets(plant: dict) -> dict:
    """The four passed assets the canonical day references."""
    return {
        "prog1": setup_qc_passed_asset(plant, 1800),
        "spot": setup_qc_passed_asset(plant, 30),
        "short": setup_qc_passed_asset(plant, 60),
        "prog2": setup_qc_passed_asset(plant, 1320),
    }


def setup_playlist_scenario(plant: Optional[dict] = None) -> dict:
    """Base plant + four cleared assets + one spot order + the canonical day.

    The returned scenario dict carries every plant key plus `assets`, `order`,
    `playlist` and `items` (the persisted elements in sequence order).
    """
    scn = plant or setup_base_plant()
    scn["assets"] = setup_cleared_assets(scn)
    scn["order"] = create_order(scn)
    scn["playlist"] = ingest(scn, canonical_day_items(scn["assets"], scn["order"]["id"]))
    scn["items"] = list_items(scn["playlist"]["id"], scn["traffic_headers"])
    return scn


# ===========================================================================
# Tier 4 — driving the air chain
# ===========================================================================

def drive_playlist(plant: dict, playlist_id: str, target_status: str,
                   headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.change_playlist_state(
            playlist_id, playlist_state_payload(target_status, **overrides),
            headers or plant["pd_headers"],
        )
    )


def validate_playlist(scn: dict) -> dict:
    return drive_playlist(scn, scn["playlist"]["id"], "VALIDATED")


def arm_playlist(scn: dict) -> dict:
    return drive_playlist(scn, scn["playlist"]["id"], "ARMED")


def drive_playlist_to_on_air(scn: dict, air_clock_utc: str = "2026-08-01T11:59:00Z") -> dict:
    """Validate, light the channel, arm, then take the day to air.

    Taking a playlist to air needs the channel already ON_AIR and the clock at
    or past the booked start less the 300-second preroll tolerance.
    """
    validate_playlist(scn)
    set_air_status(scn, scn["ch1"]["id"], "ON_AIR")
    arm_playlist(scn)
    set_clock(air_clock_utc)
    scn["playlist"] = drive_playlist(scn, scn["playlist"]["id"], "ON_AIR")
    scn["items"] = list_items(scn["playlist"]["id"], scn["traffic_headers"])
    return scn


def setup_on_air_playlist(plant: Optional[dict] = None) -> dict:
    """The canonical day, on air, with the clock one minute before element one."""
    scn = setup_playlist_scenario(plant)
    return drive_playlist_to_on_air(scn)


# ------------------------------------------------------------- playout events

def post_event(plant: dict, item_id: str, event_kind: str, event_utc: str,
               headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.post_playout_event(
            item_id, playout_event_payload(event_kind, event_utc, **overrides),
            headers or plant["mco_headers"],
        )
    )


def cue_item(plant: dict, item_id: str, event_utc: str, **overrides) -> dict:
    return post_event(plant, item_id, "CUE", event_utc, **overrides)


def start_item(plant: dict, item_id: str, event_utc: str, **overrides) -> dict:
    return post_event(plant, item_id, "START", event_utc, **overrides)


def end_item(plant: dict, item_id: str, event_utc: str,
             measured_duration_seconds: int, **overrides) -> dict:
    return post_event(plant, item_id, "END", event_utc,
                      measured_duration_seconds=measured_duration_seconds, **overrides)


def truncate_item(plant: dict, item_id: str, event_utc: str, **overrides) -> dict:
    return post_event(plant, item_id, "TRUNCATION", event_utc, **overrides)


def skip_item(plant: dict, item_id: str, event_utc: str, **overrides) -> dict:
    return post_event(plant, item_id, "SKIP", event_utc, **overrides)


def air_item(plant: dict, item: dict, start_utc: str, end_utc: str,
             measured_duration_seconds: int) -> dict:
    """Cue, start and end one element, advancing the clock to each instant."""
    set_clock(start_utc)
    cue_item(plant, item["id"], start_utc)
    start_item(plant, item["id"], start_utc)
    set_clock(end_utc)
    return end_item(plant, item["id"], end_utc, measured_duration_seconds)


def setup_playing_item1(plant: Optional[dict] = None) -> dict:
    """The canonical day on air with element one cued, started and playing."""
    scn = setup_on_air_playlist(plant)
    item1 = scn["items"][0]
    set_clock("2026-08-01T12:00:00Z")
    cue_item(scn, item1["id"], "2026-08-01T12:00:00Z")
    start_item(scn, item1["id"], "2026-08-01T12:00:00Z")
    scn["item1"] = read_item(item1["id"], scn["mco_headers"])
    return scn


def substitute(plant: dict, item_id: str, replacement_asset_id: str,
               headers: Optional[dict] = None, **overrides) -> dict:
    payload = {"replacement_asset_id": replacement_asset_id}
    payload.update(overrides)
    return get_success_data(
        api_client.substitute_item(item_id, payload, headers or plant["mco_headers"])
    )


# ===========================================================================
# Tier 5 — feed windows, overrides, faults, credits and filings
# ===========================================================================

def create_window(plant: dict, join_utc: str, breakaway_utc: str,
                  channel_id: Optional[str] = None,
                  anchor_sequence_number: int = 4, **overrides) -> dict:
    return get_success_data(
        api_client.create_feed_window(
            create_feed_window_payload(channel_id or plant["ch1"]["id"],
                                      anchor_sequence_number, join_utc,
                                      breakaway_utc, **overrides),
            plant["mco_headers"],
        )
    )


def join_window(plant: dict, window_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.join_feed_window(window_id, dict(overrides), plant["mco_headers"])
    )


def breakaway_window(plant: dict, window_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.breakaway_feed_window(window_id, dict(overrides), plant["mco_headers"])
    )


# ------------------------------------------------------------------ overrides

def request_override(plant: dict, override_mode: str = "CRAWL",
                     channel_id: Optional[str] = None,
                     requested_by_operator_id: Optional[str] = None,
                     **overrides) -> dict:
    """The requester is the master-control operator; only another operator may authorize."""
    return get_success_data(
        api_client.create_override(
            create_override_payload(channel_id or plant["ch1"]["id"],
                                    requested_by_operator_id or plant["mco"]["id"],
                                    override_mode, **overrides),
            plant["mco_headers"],
        )
    )


def activate_override(plant: dict, override_id: str, override_mode: str = "CRAWL",
                      authorized_by_operator_id: Optional[str] = None,
                      headers: Optional[dict] = None, **overrides) -> dict:
    """Authorized by the programme director, whose override_authority is FULL."""
    return get_success_data(
        api_client.activate_override(
            override_id,
            activate_override_payload(authorized_by_operator_id or plant["pd"]["id"],
                                      override_mode, **overrides),
            headers or plant["pd_headers"],
        )
    )


def release_override(plant: dict, override_id: str, headers: Optional[dict] = None,
                     **overrides) -> dict:
    return get_success_data(
        api_client.release_override(override_id, dict(overrides),
                                    headers or plant["pd_headers"])
    )


def setup_active_override(plant: dict, override_mode: str = "CRAWL",
                          channel_id: Optional[str] = None, **overrides) -> dict:
    requested = request_override(plant, override_mode, channel_id, **overrides)
    return activate_override(plant, requested["id"], override_mode)


# --------------------------------------------------------------------- faults

def report_fault(plant: dict, fault_code: str, severity: str, detected_utc: str,
                 headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.report_fault(
            report_fault_payload(fault_code, severity, detected_utc, **overrides),
            headers or plant["mco_headers"],
        )
    )


def report_channel_fault(plant: dict, fault_code: str, severity: str,
                         detected_utc: str, channel_id: Optional[str] = None,
                         **overrides) -> dict:
    return report_fault(plant, fault_code, severity, detected_utc,
                        channel_id=channel_id or plant["ch1"]["id"], **overrides)


def report_transmitter_fault(plant: dict, fault_code: str, severity: str,
                             detected_utc: str, **overrides) -> dict:
    return report_fault(plant, fault_code, severity, detected_utc,
                        transmitter_id=plant["transmitter"]["id"], **overrides)


def advance_fault(plant: dict, fault_id: str, target_state: str,
                  headers: Optional[dict] = None, **overrides) -> dict:
    payload = {"target_state": target_state}
    payload.update(overrides)
    return get_success_data(
        api_client.change_fault_state(fault_id, payload,
                                      headers or plant["mco_headers"])
    )


def setup_resolved_item_fault(plant: dict, item_id: str, fault_code: str,
                              severity: str, detected_utc: str,
                              mitigation_code: str = "SWITCH_TO_BACKUP") -> dict:
    """Report a fault against one element and drive it to RESOLVED.

    A resolved fault linked to an element that aired is what an air-check
    report's fault penalty is summed over.
    """
    fault = report_fault(plant, fault_code, severity, detected_utc,
                         channel_id=plant["ch1"]["id"], playlist_item_id=item_id)
    advance_fault(plant, fault["id"], "ACKNOWLEDGED")
    advance_fault(plant, fault["id"], "MITIGATED", mitigation_code=mitigation_code)
    return advance_fault(plant, fault["id"], "RESOLVED")


# ---------------------------------------------------------- credits and filings

def place_makegood(plant: dict, order_id: str, playlist_id: str,
                   expected_playlist_version: int, sequence_number: int,
                   scheduled_start_utc: str, headers: Optional[dict] = None,
                   **overrides) -> dict:
    payload = {
        "target_playlist_id": playlist_id,
        "expected_playlist_version": expected_playlist_version,
        "sequence_number": sequence_number,
        "scheduled_start_utc": scheduled_start_utc,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.place_makegood(order_id, payload, headers or plant["traffic_headers"])
    )


def file_notification(plant: dict, notification_id: str, **overrides) -> dict:
    payload = {
        "filed_reference": "FCC-REF-0001",
        "narrative": "Power reduced for antenna maintenance; filed within the deadline.",
    }
    payload.update(overrides)
    return get_success_data(
        api_client.file_notification(notification_id, payload, plant["compliance_headers"])
    )
