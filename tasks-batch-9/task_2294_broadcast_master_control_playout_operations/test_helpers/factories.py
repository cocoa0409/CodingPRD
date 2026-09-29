"""Payload factories — one per write endpoint, input fields only."""
from .constants import TEST_DEFAULTS

_SEQ = {"n": 0}


def unique_suffix() -> str:
    """Monotonic suffix for uniqueness-constrained fields inside one test."""
    _SEQ["n"] += 1
    return f"{_SEQ['n']:04d}"


# --------------------------------------------------------------- transmitter
def create_transmitter_payload(**overrides) -> dict:
    payload = {
        "facility_id": TEST_DEFAULTS["TX_FACILITY_ID"],
        "call_sign": TEST_DEFAULTS["TX_CALL_SIGN"],
        "authorized_erp_kw": TEST_DEFAULTS["TX_ERP_KW"],
    }
    payload.update(overrides)
    return payload


def power_state_payload(target_state, **overrides) -> dict:
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------- multiplex
def create_multiplex_payload(transmitter_id, **overrides) -> dict:
    payload = {
        "transmitter_id": transmitter_id,
        "name": TEST_DEFAULTS["MUX_NAME"],
        "total_capacity_kbps": TEST_DEFAULTS["MUX_TOTAL_CAPACITY_KBPS"],
        "pilot_reserved_kbps": TEST_DEFAULTS["MUX_PILOT_RESERVED_KBPS"],
        "live_encoder_units_total": TEST_DEFAULTS["MUX_LIVE_ENCODER_UNITS_TOTAL"],
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ operator
def create_operator_payload(role_class, **overrides) -> dict:
    payload = {
        "full_name": f"Operator {role_class}",
        "role_class": role_class,
        "override_authority": "NONE",
        "certification_expires_utc": TEST_DEFAULTS["CERT_FAR_FUTURE"],
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------- channel
def create_channel_payload(multiplex_id, expected_multiplex_version, **overrides) -> dict:
    payload = {
        "multiplex_id": multiplex_id,
        "expected_multiplex_version": expected_multiplex_version,
        "call_sign": TEST_DEFAULTS["CH1_CALL_SIGN"],
        "channel_number": TEST_DEFAULTS["CH1_NUMBER"],
        "service_class": "PRIMARY",
        "resolution_class": "HD_1080I",
        "requested_bitrate_kbps": TEST_DEFAULTS["CH1_REQUESTED_KBPS"],
        "floor_bitrate_kbps": TEST_DEFAULTS["CH1_FLOOR_KBPS"],
        "priority_rank": 1,
    }
    payload.update(overrides)
    return payload


def create_subchannel_payload(multiplex_id, expected_multiplex_version,
                              parent_channel_id, **overrides) -> dict:
    payload = {
        "multiplex_id": multiplex_id,
        "expected_multiplex_version": expected_multiplex_version,
        "call_sign": TEST_DEFAULTS["CH2_CALL_SIGN"],
        "channel_number": TEST_DEFAULTS["CH2_NUMBER"],
        "service_class": "SUBCHANNEL",
        "resolution_class": "SD_480I",
        "requested_bitrate_kbps": TEST_DEFAULTS["CH2_REQUESTED_KBPS"],
        "floor_bitrate_kbps": TEST_DEFAULTS["CH2_FLOOR_KBPS"],
        "priority_rank": 2,
        "parent_channel_id": parent_channel_id,
    }
    payload.update(overrides)
    return payload


def air_state_payload(target_air_status, **overrides) -> dict:
    payload = {"target_air_status": target_air_status}
    payload.update(overrides)
    return payload


def allocation_patch_payload(expected_multiplex_version, **overrides) -> dict:
    payload = {"expected_multiplex_version": expected_multiplex_version}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------- asset
def create_asset_payload(**overrides) -> dict:
    payload = {
        "house_number": f"HN-{unique_suffix()}",
        "title": "Test Programme",
        "source": "FILE_DELIVERY",
        "expected_duration_seconds": 1800,
        "delivery_deadline_utc": "2026-08-01T10:00:00Z",
        "required_resolution_class": "HD_1080I",
        "captions_required": False,
    }
    payload.update(overrides)
    return payload


def delivery_payload(**overrides) -> dict:
    payload = {
        "received_utc": "2026-08-01T09:00:00Z",
        "measured_duration_seconds": 1800,
        "video_codec": "H264",
        "delivered_resolution_class": "HD_1080I",
        "frame_rate": 29.97,
        "audio_loudness_lkfs": -24.0,
        "audio_channel_config": "STEREO_2_0",
        "caption_present": False,
    }
    payload.update(overrides)
    return payload


def qc_report_payload(expected_asset_version, inspected_by_operator_id, **overrides) -> dict:
    payload = {
        "expected_asset_version": expected_asset_version,
        "inspected_by_operator_id": inspected_by_operator_id,
        "basis": "INGEST",
        "defect_codes": [],
        "measured_duration_seconds": 1800,
    }
    payload.update(overrides)
    return payload


def qc_waiver_payload(waived_by_operator_id, **overrides) -> dict:
    payload = {
        "waived_by_operator_id": waived_by_operator_id,
        "waiver_justification": "Programme must air tonight; defect is cosmetic only.",
    }
    payload.update(overrides)
    return payload


def retract_payload(**overrides) -> dict:
    payload = {"reason": "Rights pull from the distributor"}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ playlist
def playlist_item(sequence_number, element_kind, scheduled_start_utc,
                  scheduled_duration_seconds, **overrides) -> dict:
    item = {
        "sequence_number": sequence_number,
        "element_kind": element_kind,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_duration_seconds": scheduled_duration_seconds,
    }
    item.update(overrides)
    return item


def ingest_playlist_payload(channel_id, items, **overrides) -> dict:
    payload = {
        "channel_id": channel_id,
        "broadcast_day": TEST_DEFAULTS["PLAYLIST_BROADCAST_DAY"],
        "schedule_start_utc": TEST_DEFAULTS["PLAYLIST_SCHEDULE_START_UTC"],
        "window_duration_seconds": TEST_DEFAULTS["PLAYLIST_WINDOW_SECONDS"],
        "items": items,
    }
    payload.update(overrides)
    return payload


def playlist_state_payload(target_status, **overrides) -> dict:
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


def traffic_revision_payload(expected_playlist_version, items, **overrides) -> dict:
    payload = {
        "expected_playlist_version": expected_playlist_version,
        "items": items,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------- playout event
def playout_event_payload(event_kind, event_utc, **overrides) -> dict:
    payload = {"event_kind": event_kind, "event_utc": event_utc}
    payload.update(overrides)
    return payload


def substitute_payload(replacement_asset_id, **overrides) -> dict:
    payload = {"replacement_asset_id": replacement_asset_id}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------- feed window
def create_feed_window_payload(channel_id, anchor_sequence_number,
                               join_utc, breakaway_utc, **overrides) -> dict:
    payload = {
        "channel_id": channel_id,
        "feed_source": "NETWORK_PRIMARY",
        "anchor_sequence_number": anchor_sequence_number,
        "join_utc": join_utc,
        "breakaway_utc": breakaway_utc,
        "backtiming_mode": "TOLERANT",
        "guard_seconds": 2,
        "live_encoder_units": 1,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ override
def create_override_payload(channel_id, requested_by_operator_id,
                            override_mode="CRAWL", **overrides) -> dict:
    payload = {
        "channel_id": channel_id,
        "requested_by_operator_id": requested_by_operator_id,
        "alert_class": "SEVERE_WEATHER",
        "override_mode": override_mode,
        "requested_start_utc": "2026-08-01T12:00:00Z",
        "expected_duration_seconds": 120,
    }
    if override_mode == "CRAWL":
        payload["crawl_text"] = "Severe thunderstorm warning for the viewing area."
    payload.update(overrides)
    return payload


def activate_override_payload(authorized_by_operator_id, override_mode, **overrides) -> dict:
    payload = {
        "authorized_by_operator_id": authorized_by_operator_id,
        "override_mode": override_mode,
    }
    if override_mode == "CRAWL":
        payload["crawl_text"] = "Severe thunderstorm warning for the viewing area."
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------- fault
def report_fault_payload(fault_code, severity, detected_utc, **overrides) -> dict:
    payload = {
        "fault_code": fault_code,
        "severity": severity,
        "detected_utc": detected_utc,
    }
    payload.update(overrides)
    return payload


def fault_state_payload(target_state, **overrides) -> dict:
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- spot order
def create_spot_order_payload(channel_id, **overrides) -> dict:
    payload = {
        "channel_id": channel_id,
        "advertiser_name": "Delta Motors",
        "order_reference": f"ORD-2026-{unique_suffix()}",
        "ordered_spots": TEST_DEFAULTS["ORD1_ORDERED_SPOTS"],
        "unit_duration_seconds": TEST_DEFAULTS["ORD1_UNIT_DURATION_SECONDS"],
        "rate_cents_total": TEST_DEFAULTS["ORD1_RATE_CENTS_TOTAL"],
        "daypart": "PRIME",
        "priority_class": "PREEMPTIBLE",
        "makegood_deadline_utc": TEST_DEFAULTS["MAKEGOOD_DEADLINE_UTC"],
    }
    payload.update(overrides)
    return payload


def makegood_payload(target_playlist_id, expected_playlist_version,
                     sequence_number, scheduled_start_utc, **overrides) -> dict:
    payload = {
        "target_playlist_id": target_playlist_id,
        "expected_playlist_version": expected_playlist_version,
        "sequence_number": sequence_number,
        "scheduled_start_utc": scheduled_start_utc,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------- filing
def file_notification_payload(**overrides) -> dict:
    payload = {
        "filed_reference": "FCC-REF-0001",
        "narrative": "Power reduced for antenna maintenance; filed within 24 hours.",
    }
    payload.update(overrides)
    return payload
