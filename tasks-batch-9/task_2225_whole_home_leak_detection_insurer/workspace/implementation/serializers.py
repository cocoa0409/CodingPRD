"""Per-entity JSON projections.  Computed fields are derived on read."""
import db
from config import MITIGATION_WINDOW_MINUTES
from util import fmt_dt, num, rhu, to_dec


def _stamps(row, versioned=True):
    out = {"created_at": fmt_dt(row["created_at"])}
    if versioned:
        out["updated_at"] = fmt_dt(row.get("updated_at"))
        out["version"] = row.get("version")
    return out


# ---------------------------------------------------------------- Homeowner
def owned_property_count(homeowner_id):
    total = 0
    for p in db.properties.values():
        if p["homeowner_id"] == homeowner_id and p["property_state"] in (
            "ACTIVE",
            "TRANSFER_PENDING",
        ):
            total += 1
    return total


def homeowner(row):
    out = {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "phone_e164": row["phone_e164"],
        "notification_channel": row["notification_channel"],
        "account_state": row["account_state"],
        "deactivated_at": fmt_dt(row.get("deactivated_at")),
        "owned_property_count": owned_property_count(row["id"]),
    }
    out.update(_stamps(row))
    return out


def emergency_contact(row):
    out = {
        "id": row["id"],
        "homeowner_id": row["homeowner_id"],
        "full_name": row["full_name"],
        "phone_e164": row["phone_e164"],
        "priority_rank": row["priority_rank"],
        "verification_state": row["verification_state"],
        "status": row["status"],
        "last_notified_at": fmt_dt(row.get("last_notified_at")),
    }
    out.update(_stamps(row))
    return out


def property_row(row):
    out = {
        "id": row["id"],
        "homeowner_id": row["homeowner_id"],
        "address_line1": row["address_line1"],
        "city": row["city"],
        "state_code": row["state_code"],
        "postal_code": row["postal_code"],
        "year_built": row["year_built"],
        "irrigation_present": row["irrigation_present"],
        "property_state": row["property_state"],
        "archived_at": fmt_dt(row.get("archived_at")),
    }
    out.update(_stamps(row))
    return out


# ---------------------------------------------------------------- Device
def device(row):
    out = {
        "id": row["id"],
        "property_id": row["property_id"],
        "serial_number": row["serial_number"],
        "model_code": row["model_code"],
        "firmware_version": row["firmware_version"],
        "lifecycle_state": row["lifecycle_state"],
        "valve_state": row["valve_state"],
        "monitor_mode": row["monitor_mode"],
        "install_verified_by_user_id": row.get("install_verified_by_user_id"),
        "install_verified_at": fmt_dt(row.get("install_verified_at")),
        "installed_static_pressure_psi": num(row.get("installed_static_pressure_psi"), 1),
        "close_count": row["close_count"],
        "reopen_count": row["reopen_count"],
        "last_shutoff_at": fmt_dt(row.get("last_shutoff_at")),
        "last_reading_at": fmt_dt(row.get("last_reading_at")),
        "vacation_started_at": fmt_dt(row.get("vacation_started_at")),
        "vacation_ends_at": fmt_dt(row.get("vacation_ends_at")),
        "snooze_window_start_at": fmt_dt(row.get("snooze_window_start_at")),
        "snooze_window_end_at": fmt_dt(row.get("snooze_window_end_at")),
        "monitor_mode_updated_at": fmt_dt(row.get("monitor_mode_updated_at")),
        "baseline_ready": bool(row.get("baseline_ready")),
        "decommissioned_at": fmt_dt(row.get("decommissioned_at")),
    }
    out.update(_stamps(row))
    return out


def sample_count(profile):
    """Eligible readings of the current learning cycle."""
    started = profile.get("learning_started_at")
    total = 0
    for r in db.telemetry_readings.values():
        if r["device_id"] != profile["device_id"]:
            continue
        if not r.get("baseline_eligible"):
            continue
        if started is not None and r["reading_at"] < started:
            continue
        total += 1
    return total


def baseline_profile(row):
    out = {
        "id": row["id"],
        "device_id": row["device_id"],
        "learning_state": row["learning_state"],
        "learning_started_at": fmt_dt(row.get("learning_started_at")),
        "learning_cycle_no": row["learning_cycle_no"],
        "sample_count": sample_count(row),
        "baseline_static_pressure_psi": num(row.get("baseline_static_pressure_psi"), 1),
        "baseline_peak_flow_gpm": num(row.get("baseline_peak_flow_gpm"), 2),
        "drip_threshold_gpm": num(row.get("drip_threshold_gpm"), 2),
        "baseline_version": row["baseline_version"],
        "false_positive_count": row["false_positive_count"],
        "last_false_positive_at": fmt_dt(row.get("last_false_positive_at")),
        "invalidated_reason": row.get("invalidated_reason"),
        "completed_at": fmt_dt(row.get("completed_at")),
    }
    out.update(_stamps(row))
    return out


def telemetry_reading(row):
    # Immutable: only id and created_at, no updated_at and no version.
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "reading_at": fmt_dt(row["reading_at"]),
        "static_pressure_psi": num(row["static_pressure_psi"], 1),
        "flow_gpm": num(row["flow_gpm"], 2),
        "duration_minutes": num(row["duration_minutes"], 1),
        "total_gallons": num(row["total_gallons"], 2),
        "reading_source": row["reading_source"],
        "classification_at_ingest": row["classification_at_ingest"],
        "suppressed_by_irrigation": bool(row["suppressed_by_irrigation"]),
        "baseline_eligible": bool(row["baseline_eligible"]),
        "coverage_minutes": row["coverage_minutes"],
        "anomaly_event_created": bool(row["anomaly_event_created"]),
        "created_at": fmt_dt(row["created_at"]),
    }


def mitigation_credited(row):
    if not row.get("auto_shutoff_executed"):
        return False
    latency = row.get("shutoff_latency_minutes")
    if latency is None:
        return False
    if to_dec(latency) > MITIGATION_WINDOW_MINUTES:
        return False
    return row.get("override_reopen_at") is None


def anomaly_event(row):
    out = {
        "id": row["id"],
        "device_id": row["device_id"],
        "telemetry_reading_id": row["telemetry_reading_id"],
        "classification": row["classification"],
        "severity_score": num(row.get("severity_score"), 3),
        "event_state": row["event_state"],
        "detected_at": fmt_dt(row["detected_at"]),
        "suppression_reason": row.get("suppression_reason"),
        "auto_shutoff_executed": bool(row.get("auto_shutoff_executed")),
        "shutoff_latency_minutes": num(row.get("shutoff_latency_minutes"), 1),
        "override_reopen_at": fmt_dt(row.get("override_reopen_at")),
        "mitigation_credited": mitigation_credited(row),
        "observed_flow_gpm": num(row.get("observed_flow_gpm"), 2),
        "observed_duration_minutes": num(row.get("observed_duration_minutes"), 1),
        "observed_gallons": num(row.get("observed_gallons"), 2),
        "baseline_version_used": row.get("baseline_version_used"),
        "resolved_at": fmt_dt(row.get("resolved_at")),
        "resolution_note": row.get("resolution_note"),
        "feedback_label": row.get("feedback_label"),
    }
    out.update(_stamps(row))
    return out


def escalation_ticket(row):
    out = {
        "id": row["id"],
        "anomaly_event_id": row["anomaly_event_id"],
        "notified_contact_id": row.get("notified_contact_id"),
        "stage": row["stage"],
        "homeowner_deadline_at": fmt_dt(row.get("homeowner_deadline_at")),
        "contact_deadline_at": fmt_dt(row.get("contact_deadline_at")),
        "escalated_at": fmt_dt(row.get("escalated_at")),
        "acknowledged_at": fmt_dt(row.get("acknowledged_at")),
        "acknowledged_by_user_id": row.get("acknowledged_by_user_id"),
        "expiry_reason": row.get("expiry_reason"),
        "notification_attempt_count": row["notification_attempt_count"],
    }
    out.update(_stamps(row))
    return out


def irrigation_window(row):
    out = {
        "id": row["id"],
        "property_id": row["property_id"],
        "label": row["label"],
        "start_at": fmt_dt(row["start_at"]),
        "end_at": fmt_dt(row["end_at"]),
        "expected_max_flow_gpm": num(row["expected_max_flow_gpm"], 2),
        "status": row["status"],
        "suspended_at": fmt_dt(row.get("suspended_at")),
    }
    out.update(_stamps(row))
    return out


# ---------------------------------------------------------------- insurance
def _finalized(policy_id):
    return [
        a
        for a in db.attestations.values()
        if a["policy_id"] == policy_id
        and a["status"] in ("FINALIZED_AWARDED", "FINALIZED_DENIED")
    ]


def finalized_period_count(policy_id):
    return len(_finalized(policy_id))


def avg_uptime_pct(policy_id):
    rows = [a for a in _finalized(policy_id) if a.get("uptime_pct") is not None]
    if not rows:
        return None
    total = to_dec("0")
    for a in rows:
        total += to_dec(a["uptime_pct"])
    return rhu(total / len(rows), 2)


def policy(row):
    out = {
        "id": row["id"],
        "property_id": row["property_id"],
        "insurer_code": row["insurer_code"],
        "policy_number": row["policy_number"],
        "annual_premium_cents": row["annual_premium_cents"],
        "deductible_cents": row["deductible_cents"],
        "policy_year_start_at": fmt_dt(row["policy_year_start_at"]),
        "credit_state": row["credit_state"],
        "current_credit_tier_pct": num(row.get("current_credit_tier_pct") or 0, 2),
        "credited_cents_total": row["credited_cents_total"],
        "clawback_cents_total": row["clawback_cents_total"],
        "true_up_cents": row["true_up_cents"],
        "paid_payout_cents_total": row["paid_payout_cents_total"],
        "finalized_period_count": finalized_period_count(row["id"]),
        "avg_uptime_pct": num(avg_uptime_pct(row["id"]), 2),
        "last_attestation_end_at": fmt_dt(row.get("last_attestation_end_at")),
        "suspended_reason": row.get("suspended_reason"),
    }
    out.update(_stamps(row))
    return out


def attestation(row):
    out = {
        "id": row["id"],
        "policy_id": row["policy_id"],
        "period_start_at": fmt_dt(row["period_start_at"]),
        "period_end_at": fmt_dt(row["period_end_at"]),
        "status": row["status"],
        "period_minutes": row["period_minutes"],
        "covered_minutes": row.get("covered_minutes"),
        "uptime_pct": num(row.get("uptime_pct"), 2),
        "offline_gap_count": row.get("offline_gap_count"),
        "tier_pct": num(row.get("tier_pct"), 2) if row.get("tier_pct") is not None else None,
        "credit_cents_awarded": row["credit_cents_awarded"],
        "true_up_cents": row["true_up_cents"],
        "is_policy_year_close": bool(row["is_policy_year_close"]),
        "device_snapshot_lifecycle_state": row.get("device_snapshot_lifecycle_state"),
        "denial_reason": row.get("denial_reason"),
        "finalized_at": fmt_dt(row.get("finalized_at")),
    }
    out.update(_stamps(row))
    return out


def claim(row):
    out = {
        "id": row["id"],
        "policy_id": row["policy_id"],
        "device_id": row["device_id"],
        "anomaly_event_id": row.get("anomaly_event_id"),
        "claim_type": row["claim_type"],
        "documented_loss_cents": row["documented_loss_cents"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "status": row["status"],
        "payout_variant": row.get("payout_variant"),
        "approved_payout_cents": row["approved_payout_cents"],
        "deductible_applied_cents": row["deductible_applied_cents"],
        "info_request_count": row["info_request_count"],
        "decided_by_user_id": row.get("decided_by_user_id"),
        "decided_at": fmt_dt(row.get("decided_at")),
        "denial_reason": row.get("denial_reason"),
        "paid_at": fmt_dt(row.get("paid_at")),
    }
    out.update(_stamps(row))
    return out


def transfer(row):
    out = {
        "id": row["id"],
        "device_id": row["device_id"],
        "from_homeowner_id": row["from_homeowner_id"],
        "to_homeowner_id": row["to_homeowner_id"],
        "status": row["status"],
        "initiated_at": fmt_dt(row["initiated_at"]),
        "expires_at": fmt_dt(row["expires_at"]),
        "accepted_at": fmt_dt(row.get("accepted_at")),
        "accepted_by_user_id": row.get("accepted_by_user_id"),
        "cancel_reason": row.get("cancel_reason"),
        "transfer_note": row.get("transfer_note"),
    }
    out.update(_stamps(row))
    return out
