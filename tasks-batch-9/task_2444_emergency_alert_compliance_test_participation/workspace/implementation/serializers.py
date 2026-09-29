"""Entity -> JSON serializers.

Audit fields follow PRD 2.5: every row exposes id and created_at; all rows
except WirelessAlertNotice and TestLogEntry additionally expose updated_at and
version.  Every score/points/hours figure is emitted as a JSON number carrying
exactly two decimal places (PRD 2.6).
"""

from decimal import Decimal

import clock
from store import db


def n(value):
    """Decimal/number -> JSON number (None stays null)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _audit(row, versioned=True):
    out = {"created_at": clock.iso(row["created_at"])}
    if versioned:
        out["updated_at"] = clock.iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def state_plan(row):
    out = {
        "id": row["id"],
        "state_code": row["state_code"],
        "plan_version_label": row["plan_version_label"],
        "required_source_types": list(row["required_source_types"]),
        "mandatory_relay_event_codes": list(row["mandatory_relay_event_codes"]),
        "required_source_count": row["required_source_count"],
        "status": row["status"],
        "activated_at": clock.iso(row["activated_at"]),
        "superseded_at": clock.iso(row["superseded_at"]),
    }
    out.update(_audit(row))
    return out


def station(row):
    out = {
        "id": row["id"],
        "state_plan_id": row["state_plan_id"],
        "call_sign": row["call_sign"],
        "service_type": row["service_type"],
        "engineer_user_ids": list(row["engineer_user_ids"]),
        "certification_officer_user_id": row["certification_officer_user_id"],
        "compliance_posture": row["compliance_posture"],
        "compliance_score": n(row["compliance_score"]),
        "compliance_variant_applied": row["compliance_variant_applied"],
        "accessible_source_count": row["accessible_source_count"],
        "silent_assignment_count": row["silent_assignment_count"],
        "penalty_points_total": n(row["penalty_points_total"]),
        "plan_revalidation_required": row["plan_revalidation_required"],
        "public_file_document_count": row["public_file_document_count"],
        "last_log_review_at": clock.iso(row["last_log_review_at"]),
    }
    out.update(_audit(row))
    return out


def relay_rule(row):
    out = {
        "id": row["id"],
        "state_plan_id": row["state_plan_id"],
        "event_code": row["event_code"],
        "fips_codes": list(row["fips_codes"]),
        "relay_class": row["relay_class"],
        "priority": row["priority"],
        "forward_delay_seconds": row["forward_delay_seconds"],
        "specificity": row["specificity"],
        "status": row["status"],
    }
    out.update(_audit(row))
    return out


def device(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "model_code": row["model_code"],
        "device_role": row["device_role"],
        "firmware_version": row["firmware_version"],
        "status": row["status"],
        "readiness_check_passed": row["readiness_check_passed"],
        "last_readiness_check_at": clock.iso(row["last_readiness_check_at"]),
    }
    out.update(_audit(row))
    return out


def _counts_toward_required_sources(row):
    if row["status"] != "ACTIVE":
        return False
    st = db.stations.get(row["station_id"])
    if st is None:
        return False
    plan = db.state_plans.get(st["state_plan_id"])
    if plan is None:
        return False
    return row["source_type"] in plan["required_source_types"]


def assignment(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "device_id": row["device_id"],
        "source_type": row["source_type"],
        "source_call_sign": row["source_call_sign"],
        "status": row["status"],
        "counts_toward_required_sources": _counts_toward_required_sources(row),
        "last_receipt_at": clock.iso(row["last_receipt_at"]),
        "silence_flagged_at": clock.iso(row["silence_flagged_at"]),
        "superseded_assignment_id": row["superseded_assignment_id"],
    }
    out.update(_audit(row))
    return out


def outage(row):
    out = {
        "id": row["id"],
        "device_id": row["device_id"],
        "detected_at": clock.iso(row["detected_at"]),
        "failure_summary": row["failure_summary"],
        "notified_at": clock.iso(row["notified_at"]),
        "repair_started_at": clock.iso(row["repair_started_at"]),
        "restored_at": clock.iso(row["restored_at"]),
        "status": row["status"],
        "repair_cycle_count": row["repair_cycle_count"],
        "continuous_downtime_hours": n(row["continuous_downtime_hours"]),
        "obligation_downtime_hours": n(row["obligation_downtime_hours"]),
        "continuous_clock_breached": row["continuous_clock_breached"],
        "obligation_breached": row["obligation_breached"],
    }
    out.update(_audit(row))
    return out


def alert_event(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "event_code": row["event_code"],
        "originator_sequence": row["originator_sequence"],
        "fips_codes": list(row["fips_codes"]),
        "received_at": clock.iso(row["received_at"]),
        "relay_state": row["relay_state"],
        "accessibility_state": row["accessibility_state"],
        "matched_relay_rule_id": row["matched_relay_rule_id"],
        "relay_class_applied": row["relay_class_applied"],
        "forward_delay_seconds_applied": row["forward_delay_seconds_applied"],
        "suppression_reference_alert_id": row["suppression_reference_alert_id"],
        "suppression_source": row["suppression_source"],
        "visual_crawl_seconds": row["visual_crawl_seconds"],
        "audio_loudness_lufs": n(row["audio_loudness_lufs"]),
        "caption_interaction": row["caption_interaction"],
        "accessibility_deficiency_points": n(row["accessibility_deficiency_points"]),
    }
    out.update(_audit(row))
    return out


def wea_notice(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "originator_sequence": row["originator_sequence"],
        "event_code": row["event_code"],
        "wea_sent_at": clock.iso(row["wea_sent_at"]),
        "fips_codes": list(row["fips_codes"]),
    }
    out.update(_audit(row, versioned=False))
    return out


def test_event(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "test_type": row["test_type"],
        "window_start_at": clock.iso(row["window_start_at"]),
        "window_end_at": clock.iso(row["window_end_at"]),
        "status": row["status"],
        "readiness_score": n(row["readiness_score"]),
        "readiness_evaluated_at": clock.iso(row["readiness_evaluated_at"]),
        "filing_deadline_at": clock.iso(row["filing_deadline_at"]),
        "logged_entry_count": row["logged_entry_count"],
        "retention_until_max": clock.iso(row["retention_until_max"]),
    }
    out.update(_audit(row))
    return out


def log_entry(row):
    out = {
        "id": row["id"],
        "test_event_id": row["test_event_id"],
        "device_id": row["device_id"],
        "entry_kind": row["entry_kind"],
        "source_call_sign": row["source_call_sign"],
        "logged_at": clock.iso(row["logged_at"]),
        "logged_by_user_id": row["logged_by_user_id"],
        "retention_days_applied": row["retention_days_applied"],
        "retention_until": clock.iso(row["retention_until"]),
    }
    out.update(_audit(row, versioned=False))
    return out


def filing(row):
    out = {
        "id": row["id"],
        "test_event_id": row["test_event_id"],
        "attestation_note": row["attestation_note"],
        "filed_at": clock.iso(row["filed_at"]),
        "filed_by_user_id": row["filed_by_user_id"],
        "late_days": row["late_days"],
        "entry_subtotal_points": n(row["entry_subtotal_points"]),
        "lateness_points": n(row["lateness_points"]),
        "unconfirmed_relay_points": n(row["unconfirmed_relay_points"]),
        "penalty_points": n(row["penalty_points"]),
        "status": row["status"],
        "reversal_reason": row["reversal_reason"],
        "superseded_filing_id": row["superseded_filing_id"],
    }
    out.update(_audit(row))
    return out


def inspection(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "requested_document_kinds": list(row["requested_document_kinds"]),
        "provided_document_kinds": list(row["provided_document_kinds"]),
        "requested_at": clock.iso(row["requested_at"]),
        "response_due_at": clock.iso(row["response_due_at"]),
        "responded_at": clock.iso(row["responded_at"]),
        "completeness_score": n(row["completeness_score"]),
        "status": row["status"],
    }
    out.update(_audit(row))
    return out
