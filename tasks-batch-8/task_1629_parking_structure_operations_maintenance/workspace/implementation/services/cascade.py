"""Cascades and the close-of-business ops-run checkpoint (PRD 3.1, 3.6, 3.9)."""
from datetime import timedelta

import db
from db import parse_iso
from errors import (
    err_posture_blocked, err_structural_critical,
)
from services.fees import pool_counts, recompute_charger_utilization


# ---------------------------------------------------------------------------
# Monthly waitlist promotion (PRD 3.4): created_at ASC, application_seq ASC tie-break
# ---------------------------------------------------------------------------

def promote_waitlist(facility):
    promoted = 0
    while True:
        allocated, approved = pool_counts(facility["id"])
        committed = allocated + approved
        if committed >= facility["monthly_capacity"]:
            break
        candidates = [
            a for a in db.monthly_agreements.values()
            if a["facility_id"] == facility["id"] and a["agreement_status"] == "WAITLISTED"
        ]
        if not candidates:
            break
        candidates.sort(key=lambda a: (a["created_at"], a["application_seq"]))
        top = candidates[0]
        top["agreement_status"] = "APPROVED"
        db.touch(top)
        promoted += 1
    return promoted


# ---------------------------------------------------------------------------
# CRITICAL inspection demotion cascade (PRD 3.6, cascade links 1-3)
# ---------------------------------------------------------------------------

def run_demotion_cascade(facility):
    """While committed > effective capacity, demote newest APPROVED (application_seq DESC)."""
    effective_capacity = min(
        facility["monthly_capacity"],
        facility["total_spaces"] - facility["closed_spaces"],
    )
    while True:
        allocated, approved = pool_counts(facility["id"])
        committed = allocated + approved
        if committed <= effective_capacity:
            break
        approved_rows = [
            a for a in db.monthly_agreements.values()
            if a["facility_id"] == facility["id"] and a["agreement_status"] == "APPROVED"
        ]
        if not approved_rows:
            break
        approved_rows.sort(key=lambda a: a["application_seq"], reverse=True)
        victim = approved_rows[0]
        victim["agreement_status"] = "WAITLISTED"
        db.touch(victim)
        # cascade link 3: revoke the demoted agreement's ACTIVE credentials
        for cred in db.credentials.values():
            if cred["agreement_id"] == victim["id"] and cred["credential_status"] == "ACTIVE":
                cred["credential_status"] = "REVOKED"
                db.touch(cred)
                facility["deposit_liability_cents"] -= cred["deposit_cents"]


def critical_report_cascade(facility, closed_space_count):
    """Link 1: posture -> RESTRICTED (from NORMAL), closed_spaces += count, version +1."""
    if facility["posture"] == "NORMAL":
        facility["posture"] = "RESTRICTED"
    facility["closed_spaces"] += closed_space_count
    db.touch(facility)
    # link 2 + 3
    run_demotion_cascade(facility)


# ---------------------------------------------------------------------------
# Manual posture transition guards (PRD 3.1)
# ---------------------------------------------------------------------------

def check_release_guards(facility):
    """Release to NORMAL guards: structural CRITICAL first, then CRITICAL incidents."""
    for insp in db.inspections.values():
        if (insp["facility_id"] == facility["id"]
                and insp["inspection_status"] == "REPORTED"
                and insp["condition_class"] == "CRITICAL"):
            raise err_structural_critical()
    for inc in db.incidents.values():
        if (inc["facility_id"] == facility["id"]
                and inc["severity"] == "CRITICAL"
                and inc["incident_status"] in ("OPEN", "INVESTIGATING")):
            raise err_posture_blocked("release blocked by unresolved CRITICAL incident")


def check_decommission_guards(facility):
    fid = facility["id"]
    for s in db.parking_sessions.values():
        if s["facility_id"] == fid and s["occupancy_state"] == "PARKED":
            raise err_posture_blocked("decommission blocked by PARKED sessions")
    for a in db.monthly_agreements.values():
        if a["facility_id"] == fid and a["agreement_status"] in ("APPROVED", "ACTIVE", "SUSPENDED"):
            raise err_posture_blocked("decommission blocked by live agreements")
    for p in db.repair_projects.values():
        if p["facility_id"] == fid and p["project_status"] in (
                "PROPOSED", "FUNDED", "SCHEDULED", "IN_PROGRESS", "DEFERRED"):
            raise err_posture_blocked("decommission blocked by open repair projects")
    for e in db.event_bookings.values():
        if e["facility_id"] == fid and e["booking_status"] in ("CONFIRMED", "ACTIVE"):
            raise err_posture_blocked("decommission blocked by live events")


# ---------------------------------------------------------------------------
# Event surge cascade (PRD 3.9)
# ---------------------------------------------------------------------------

def event_surge_on_activate(facility):
    """NORMAL -> EVENT_SURGE (+1 version), ONLINE devices flip to EVENT mode."""
    if facility["posture"] == "NORMAL":
        facility["posture"] = "EVENT_SURGE"
        db.touch(facility)
        for dev in db.access_devices.values():
            if (dev["facility_id"] == facility["id"]
                    and dev["device_status"] == "ONLINE"
                    and dev["device_mode"] == "STANDARD"):
                dev["device_mode"] = "EVENT"
                db.touch(dev)


def event_surge_on_complete(facility, completing_event):
    """Reverse the surge when no other ACTIVE event remains and posture is EVENT_SURGE."""
    others_active = any(
        e["facility_id"] == facility["id"]
        and e["id"] != completing_event["id"]
        and e["booking_status"] == "ACTIVE"
        for e in db.event_bookings.values()
    )
    if not others_active and facility["posture"] == "EVENT_SURGE":
        facility["posture"] = "NORMAL"
        db.touch_ledger(facility)
        for dev in db.access_devices.values():
            if dev["facility_id"] == facility["id"] and dev["device_mode"] == "EVENT":
                dev["device_mode"] = "STANDARD"
                db.touch(dev)


# ---------------------------------------------------------------------------
# Close-of-business ops-run checkpoint (PRD 3.1)
# ---------------------------------------------------------------------------

def close_of_business(facility, now):
    fid = facility["id"]
    business_date = now.date()

    # 1. Force-close shifts still OPEN
    shifts_force_closed = 0
    for shift in db.shifts.values():
        if shift["facility_id"] == fid and shift["shift_status"] == "OPEN":
            shift["shift_status"] = "FORCE_CLOSED"
            shift["closed_at"] = db.now_iso()
            from services.fees import refresh_shift_expected
            refresh_shift_expected(shift)
            db.touch(shift)
            shifts_force_closed += 1

    # 2. DRAFT reconciliations for CLOSED/FORCE_CLOSED shifts lacking a non-terminal record
    reconciliations_created = 0
    for shift in db.shifts.values():
        if shift["facility_id"] != fid:
            continue
        if shift["shift_status"] not in ("CLOSED", "FORCE_CLOSED"):
            continue
        has_open_record = any(
            r["shift_id"] == shift["id"]
            and r["reconciliation_status"] in ("DRAFT", "SUBMITTED", "VARIANCE_REVIEW")
            for r in db.reconciliations.values()
        )
        if not has_open_record:
            rec = {
                "id": db.new_id(),
                "shift_id": shift["id"],
                "auditor_user_id": None,
                "reconciliation_status": "DRAFT",
                "variance_cents": None,
            }
            db.stamp_new(rec)
            db.reconciliations[rec["id"]] = rec
            reconciliations_created += 1

    # 3. Waitlist promotion
    agreements_promoted = promote_waitlist(facility)

    # 4. Maintenance windows past their end -> MISSED
    windows_marked_missed = 0
    for w in db.maintenance_windows.values():
        if (w["facility_id"] == fid
                and w["window_status"] in ("SCHEDULED", "IN_PROGRESS")
                and parse_iso(w["end_at"]) < now):
            w["window_status"] = "MISSED"
            db.touch(w)
            windows_marked_missed += 1

    # 5. Patrol rounds past their scheduled start -> MISSED
    patrols_marked_missed = 0
    for p in db.patrol_rounds.values():
        if (p["facility_id"] == fid
                and p["patrol_status"] == "SCHEDULED"
                and parse_iso(p["scheduled_start"]) < now):
            p["patrol_status"] = "MISSED"
            db.touch(p)
            patrols_marked_missed += 1

    # 6. Heartbeat-stale devices -> OFFLINE
    devices_marked_offline = 0
    staleness_cutoff = now - timedelta(hours=24)
    for dev in db.access_devices.values():
        if dev["facility_id"] != fid:
            continue
        if dev["device_status"] not in ("ONLINE", "DEGRADED"):
            continue
        hb = dev.get("last_heartbeat_at")
        if hb is None or parse_iso(hb) < staleness_cutoff:
            dev["device_status"] = "OFFLINE"
            db.touch(dev)
            devices_marked_offline += 1

    # 7. EV utilization recompute (chargers with commissioned_at set, not DECOMMISSIONED)
    for ch in db.ev_chargers.values():
        if ch["facility_id"] != fid:
            continue
        if ch.get("commissioned_at") is None:
            continue
        if ch["charger_status"] not in ("COMMISSIONED", "OUT_OF_SERVICE"):
            continue
        recompute_charger_utilization(ch, now, business_date)
    chargers_flagged = sum(
        1 for ch in db.ev_chargers.values()
        if ch["facility_id"] == fid and ch.get("utilization_review_flag")
    )

    # 8. CRITICAL incident escalation: NORMAL -> RESTRICTED
    if facility["posture"] == "NORMAL":
        has_critical = any(
            inc["facility_id"] == fid
            and inc["severity"] == "CRITICAL"
            and inc["incident_status"] in ("OPEN", "INVESTIGATING")
            for inc in db.incidents.values()
        )
        if has_critical:
            facility["posture"] = "RESTRICTED"

    # 9. Capital levy (pinned order: gross, levy, reserve += levy; net derived after)
    from decimal import Decimal
    from services.fees import round_half_up_int
    gross = 0
    for s in db.parking_sessions.values():
        if s["facility_id"] != fid:
            continue
        settled_at = s.get("_settled_at")
        if settled_at is not None and parse_iso(settled_at).date() == business_date:
            gross += s.get("settled_fee_cents") or 0
        if s.get("refunded_at") is not None and parse_iso(s["refunded_at"]).date() == business_date:
            gross -= s.get("refunded_cents") or 0
    levy = round_half_up_int(Decimal(max(0, gross)) * Decimal(str(facility["levy_pct"])))
    facility["capital_reserve_cents"] += levy

    # 10. Book the close
    facility["last_close_date"] = business_date.isoformat()
    db.touch(facility)  # single version bump for the whole run

    return {
        "business_date": business_date.isoformat(),
        "shifts_force_closed": shifts_force_closed,
        "reconciliations_created": reconciliations_created,
        "agreements_promoted": agreements_promoted,
        "windows_marked_missed": windows_marked_missed,
        "patrols_marked_missed": patrols_marked_missed,
        "devices_marked_offline": devices_marked_offline,
        "levy_credited_cents": levy,
        "chargers_flagged": chargers_flagged,
    }
