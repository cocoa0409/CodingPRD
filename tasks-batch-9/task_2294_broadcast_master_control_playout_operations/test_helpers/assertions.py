"""Entity assertions and domain invariant checkers."""
from typing import Dict, List

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --------------------------------------------------------------------------
# Housekeeping-field shapes (PRD §2.5)
# --------------------------------------------------------------------------

def assert_full_common_fields(data: dict):
    """Resources carrying id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_append_only_common_fields(data: dict):
    """Append-only records of fact carry id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "an append-only record must not carry updated_at"
    assert "version" not in data, "an append-only record must not carry version"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------

def assert_transmitter(data: dict) -> dict:
    assert_full_common_fields(data)
    assert isinstance(data["facility_id"], str) and 1 <= len(data["facility_id"]) <= 32
    assert isinstance(data["call_sign"], str)
    assert data["authorized_erp_kw"] > 0
    assert 0 <= data["current_power_pct"] <= 100
    assert data["operational_state"] in ["FULL_POWER", "REDUCED_POWER", "OFF_AIR"]
    assert float(data["derate_factor"]) in [1.00, 0.75, 0.50, 0.00]
    assert data["cumulative_outage_seconds"] >= 0
    assert data["notification_pending_count"] >= 0
    return data


def assert_multiplex(data: dict) -> dict:
    assert_full_common_fields(data)
    assert data["total_capacity_kbps"] >= 1000
    assert 0 <= data["pilot_reserved_kbps"] < data["total_capacity_kbps"]
    assert data["live_encoder_units_total"] >= 1
    assert data["effective_capacity_kbps"] >= 0
    assert data["assigned_kbps"] >= 0
    assert data["available_kbps"] >= 0
    assert data["starved_channel_count"] >= 0
    assert data["live_encoder_units_peak"] >= 0
    assert_bandwidth_conservation(data)
    return data


def assert_channel(data: dict) -> dict:
    assert_full_common_fields(data)
    assert data["service_class"] in ["PRIMARY", "SUBCHANNEL"]
    assert data["resolution_class"] in ["HD_1080I", "HD_720P", "SD_480I"]
    assert data["allocation_state"] in ["ACTIVE", "STANDBY", "STARVED"]
    assert data["air_status"] in ["DARK", "ON_AIR", "BARS_AND_TONE", "EAS_OVERRIDE"]
    assert data["posture"] in [
        "NORMAL", "DEGRADED", "DEGRADED_CRITICAL", "EMERGENCY", "SUSPENDED"
    ]
    assert data["priority_rank"] >= 1
    assert data["floor_bitrate_kbps"] >= 100
    assert data["floor_bitrate_kbps"] <= data["requested_bitrate_kbps"]
    assert data["allocated_bitrate_kbps"] >= 0
    assert data["open_fault_count"] >= 0
    if data["allocation_state"] == "STARVED":
        assert data["allocated_bitrate_kbps"] == 0, \
            "a starved channel contributes exactly 0 kbps"
    if data["service_class"] == "PRIMARY":
        assert data.get("parent_channel_id") is None
    return data


def assert_operator(data: dict) -> dict:
    assert_full_common_fields(data)
    assert data["role_class"] in ["MASTER_CONTROL", "QC", "PROGRAM_DIRECTOR", "ENGINEER"]
    assert data["override_authority"] in ["NONE", "CRAWL_ONLY", "CRAWL_AND_CUTIN", "FULL"]
    assert data["certification_state"] in ["VALID", "EXPIRED"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    return data


def assert_asset(data: dict) -> dict:
    assert_full_common_fields(data)
    assert data["source"] in ["SATELLITE_FEED", "FILE_DELIVERY", "LIVE_LINE", "LOCAL_ARCHIVE"]
    assert data["status"] in [
        "EXPECTED", "RECEIVED", "QC_PASSED", "QC_FAILED", "QC_WAIVED",
        "EXPIRED", "RETRACTED",
    ]
    assert data["expected_duration_seconds"] >= 1
    assert data["required_resolution_class"] in ["HD_1080I", "HD_720P", "SD_480I"]
    assert isinstance(data["captions_required"], bool)
    if data.get("qc_verdict") is not None:
        assert data["qc_verdict"] in ["PASS", "PASS_WITH_EXCEPTION", "FAIL"]
    for score_field in ("technical_score_ingest", "technical_score_aircheck"):
        if data.get(score_field) is not None:
            assert 0 <= data[score_field] <= 100, f"{score_field} is clamped to 0..100"
    return data


def assert_qc_report(data: dict) -> dict:
    assert_append_only_common_fields(data)
    assert data["basis"] in ["INGEST", "AIR_CHECK"]
    assert data["verdict"] in ["PASS", "PASS_WITH_EXCEPTION", "FAIL"]
    assert 0 <= data["technical_score"] <= 100
    for field in (
        "defect_penalty_points", "duration_penalty_points",
        "loudness_penalty_points", "fault_penalty_points",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["defect_codes"], list)
    assert isinstance(data["superseded"], bool)
    return data


def assert_playlist(data: dict) -> dict:
    assert_full_common_fields(data)
    assert data["status"] in [
        "IMPORTING", "IMPORTED", "VALIDATED", "ARMED", "ON_AIR", "CLOSED", "ABANDONED",
    ]
    assert data["item_count"] >= 0
    assert data["blocked_item_count"] >= 0
    assert data["scheduled_total_seconds"] >= 0
    assert isinstance(data["projected_end_variance_seconds"], int)
    assert isinstance(data["asrun_end_variance_seconds"], int)
    assert isinstance(data["commercial_seconds_by_hour"], dict)
    assert data["traffic_revision"] >= 1
    assert data["window_duration_seconds"] >= 60
    return data


def assert_playlist_item(data: dict) -> dict:
    assert_full_common_fields(data)
    assert data["element_kind"] in [
        "PROGRAM", "COMMERCIAL", "INTERSTITIAL", "PROMO",
        "NETWORK_JOIN", "LIVE_EVENT", "FILLER",
    ]
    assert data["playout_status"] in [
        "SCHEDULED", "CUED", "PLAYING", "PLAYED", "TRUNCATED", "SKIPPED", "PREEMPTED",
    ]
    assert data["clearance_status"] in ["UNCLEARED", "CLEARED", "BLOCKED"]
    assert data["sequence_number"] >= 1
    assert data["scheduled_duration_seconds"] >= 1
    assert 0 <= data["max_trim_seconds"] <= data["scheduled_duration_seconds"] + data.get(
        "trim_applied_seconds", 0
    )
    assert isinstance(data["is_makegood"], bool)
    return data


def assert_spot_order(data: dict) -> dict:
    assert_full_common_fields(data)
    assert data["daypart"] in [
        "EARLY_MORNING", "DAYTIME", "EARLY_FRINGE", "PRIME", "LATE_NIGHT"
    ]
    assert data["priority_class"] in ["GUARANTEED", "PREEMPTIBLE", "REMNANT"]
    assert data["status"] in [
        "OPEN", "PARTIALLY_CREDITED", "FULLY_AIRED", "CLOSED_WITH_CREDIT"
    ]
    assert data["ordered_spots"] >= 1
    assert data["unit_duration_seconds"] >= 5
    assert data["rate_cents_total"] >= 1
    assert data["credit_accrued_cents"] >= 0
    assert_spot_count_conservation(data)
    return data


def assert_feed_window(data: dict) -> dict:
    assert_full_common_fields(data)
    assert data["feed_source"] in [
        "NETWORK_PRIMARY", "NETWORK_ALT", "SYNDICATED_LIVE", "LOCAL_LIVE_EVENT"
    ]
    assert data["backtiming_mode"] in ["STRICT", "TOLERANT"]
    assert data["plan_action"] in [
        "PAD_WITH_FILLER", "TRIM_TAIL", "SKIP_ELEMENTS", "HARD_CUT", "JOIN_IN_PROGRESS"
    ]
    assert data["state"] in ["PLANNED", "JOINED", "BROKEN_AWAY", "ABANDONED"]
    assert 0 <= data["guard_seconds"] <= 30
    assert data["live_encoder_units"] >= 1
    assert data["anchor_sequence_number"] >= 1
    assert isinstance(data["skipped_item_sequences"], list)
    for field in ("backtime_pad_seconds", "backtime_trim_seconds",
                  "residual_dead_air_seconds", "late_join_seconds"):
        assert data[field] >= 0
    return data


def assert_override(data: dict) -> dict:
    assert_full_common_fields(data)
    assert data["alert_class"] in [
        "EAS_MANDATORY", "SEVERE_WEATHER", "BREAKING_NEWS", "STATION_MESSAGE"
    ]
    assert data["override_mode"] in ["CRAWL", "CUT_IN"]
    assert data["state"] in [
        "PENDING", "ACTIVE_CRAWL", "ACTIVE_CUTIN", "RELEASED", "REJECTED"
    ]
    if data.get("active_mode") is not None:
        assert data["active_mode"] in ["CRAWL", "CUT_IN"]
    assert data["expected_duration_seconds"] >= 1
    assert data["truncated_item_count"] >= 0
    assert data["preempted_item_count"] >= 0
    return data


def assert_technical_fault(data: dict) -> dict:
    assert_full_common_fields(data)
    assert data["fault_code"] in [
        "AUDIO_LOSS", "BLACK_FRAME", "CAPTION_LOSS", "LOSS_OF_SIGNAL",
        "ENCODER_FAILURE", "RF_POWER_FAULT", "AUTOMATION_STALL",
    ]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert data["state"] in [
        "DETECTED", "ACKNOWLEDGED", "ESCALATED", "MITIGATED", "RESOLVED", "AUTO_CLEARED"
    ]
    if data.get("mitigation_code") is not None:
        assert data["mitigation_code"] in [
            "SWITCH_TO_BACKUP", "RESTART_ENCODER", "BARS_AND_TONE", "MANUAL_BYPASS"
        ]
    assert data["duration_seconds"] >= 0
    return data


def assert_as_run_entry(data: dict) -> dict:
    assert_append_only_common_fields(data)
    assert data["event_kind"] in [
        "CUE", "START", "END", "TRUNCATION", "SKIP", "PREEMPTION",
        "OVERRIDE_IN", "OVERRIDE_OUT", "FILLER_INSERT", "JOIN", "BREAKAWAY",
    ]
    assert data["source"] in ["AUTOMATION", "OPERATOR", "SYSTEM"]
    assert is_iso8601_timestamp(data["event_utc"]) or data["event_utc"].endswith("Z")
    assert data["measured_duration_seconds"] >= 0
    if data["event_kind"] not in ("END", "TRUNCATION"):
        assert data["measured_duration_seconds"] == 0, \
            "measured_duration_seconds is 0 for every event kind other than end and truncation"
    return data


def assert_regulatory_notification(data: dict) -> dict:
    assert_full_common_fields(data)
    assert data["kind"] in ["POWER_REDUCTION", "OUTAGE", "RESUMPTION"]
    assert data["status"] in ["PENDING", "OVERDUE", "FILED", "LATE_FILED"]
    if data["kind"] == "POWER_REDUCTION":
        assert data.get("observed_power_pct") is not None
        assert data.get("outage_seconds") is None
    else:
        assert data.get("observed_power_pct") is None
        assert data.get("outage_seconds") is not None
    return data


# --------------------------------------------------------------------------
# Conserved quantities (PRD §2.11) — exact integer equalities, no tolerance
# --------------------------------------------------------------------------

def assert_bandwidth_conservation(multiplex: dict):
    """available_kbps + assigned_kbps == effective_capacity_kbps."""
    assert multiplex["available_kbps"] + multiplex["assigned_kbps"] == \
        multiplex["effective_capacity_kbps"], (
            "available_kbps + assigned_kbps must equal effective_capacity_kbps, got "
            f"{multiplex['available_kbps']} + {multiplex['assigned_kbps']} != "
            f"{multiplex['effective_capacity_kbps']}"
        )


def assert_assigned_equals_channel_sum(multiplex: dict, channels: List[dict]):
    """assigned_kbps equals the sum of allocated_bitrate_kbps over ACTIVE/STANDBY channels."""
    expected = sum(
        c["allocated_bitrate_kbps"] for c in channels
        if c["allocation_state"] in ("ACTIVE", "STANDBY")
    )
    assert multiplex["assigned_kbps"] == expected, (
        f"assigned_kbps {multiplex['assigned_kbps']} must equal the granted channel sum {expected}"
    )


def assert_spot_count_conservation(order: dict):
    """ordered_spots == scheduled + aired + short_aired + credited + unplaced."""
    total = (
        order["scheduled_spots"] + order["aired_spots"] + order["short_aired_spots"]
        + order["credited_spots"] + order["unplaced_spots"]
    )
    assert order["ordered_spots"] == total, (
        "ordered_spots must equal the sum of the five spot counters, got "
        f"{order['ordered_spots']} != {total}"
    )


def assert_tail_seconds_conservation(pre_plan_tail_seconds: int,
                                    post_plan_tail_seconds: int,
                                    backtime_trim_seconds: int,
                                    skipped_seconds: int):
    """Pre-plan tail == post-plan tail + trim + skipped seconds."""
    assert pre_plan_tail_seconds == (
        post_plan_tail_seconds + backtime_trim_seconds + skipped_seconds
    ), (
        f"pre-plan tail {pre_plan_tail_seconds} must equal post-plan tail "
        f"{post_plan_tail_seconds} + trim {backtime_trim_seconds} + skipped {skipped_seconds}"
    )


# --------------------------------------------------------------------------
# Convenience helpers used across the suite
# --------------------------------------------------------------------------

def item_by_sequence(items: List[dict], sequence_number: int) -> dict:
    for item in items:
        if item["sequence_number"] == sequence_number:
            return item
    raise AssertionError(f"no element with sequence_number {sequence_number}")


def as_run_kinds(entries: List[dict]) -> List[str]:
    return [entry["event_kind"] for entry in entries]


def assert_envelope_meta(body: Dict):
    """Every response carries a server-generated request id and timestamp."""
    meta = body.get("meta", {})
    assert isinstance(meta.get("api_request_id"), str) and \
        meta["api_request_id"].startswith("req_"), \
        f"api_request_id must start with req_, got {meta.get('api_request_id')!r}"
    assert isinstance(meta.get("api_request_timestamp"), str), \
        "api_request_timestamp must be present"
    return body
