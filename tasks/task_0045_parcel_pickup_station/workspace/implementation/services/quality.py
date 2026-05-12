"""Quality assessment service."""
from datetime import datetime, timezone, timedelta
from clock import now
from db import store, GLOBAL_LOCK
from errors import E, raise_error
from services.common import stamp_create, bump, write_audit
from services.pricing import quality_composite, round_rate4
from services.billing import _parse_period

SLA_MINUTES = 15


def create_or_fetch_assessment(station_id, body):
    from services.station import get_station
    get_station(station_id, allow_not_found=False)
    period_yyyymm = (body or {}).get("period_yyyymm")
    _parse_period(period_yyyymm)  # validates
    with GLOBAL_LOCK:
        key = (station_id, period_yyyymm)
        if key in store.quality_assessment_by_key:
            return store.quality_assessments[store.quality_assessment_by_key[key]], False
        row = stamp_create({
            "station_id": station_id,
            "period_yyyymm": period_yyyymm,
            "mis_shelving_rate": 0,
            "lost_parcel_rate": 0,
            "complaint_rate": 0,
            "response_timeliness_score": 1.0,
            "composite_score": 1.0,
            "status": "DRAFT",
            "closed_at": None,
        })
        store.quality_assessments[row["id"]] = row
        store.quality_assessment_by_key[key] = row["id"]
        return row, True


def get_assessment(station_id, period_yyyymm, allow_not_found=False):
    key = (station_id, period_yyyymm)
    aid = store.quality_assessment_by_key.get(key)
    if aid is None:
        if allow_not_found:
            return None
        raise_error(E.RESOURCE_NOT_FOUND, "QualityAssessment not found")
    return store.quality_assessments[aid]


def _within(dt, lo, hi):
    if dt is None:
        return False
    return lo <= dt < hi


def _count_period_parcels_inbound(station_id, lo, hi):
    n = 0
    for p in store.parcels.values():
        if p["station_id"] != station_id:
            continue
        # "Inbound in period" = the parcel was created in the period
        if _within(p.get("created_at"), lo, hi):
            n += 1
    return n


def _count_period_parcels_shelved(station_id, lo, hi):
    n = 0
    for p in store.parcels.values():
        if p["station_id"] != station_id:
            continue
        if _within(p.get("shelved_at"), lo, hi):
            n += 1
    return n


def _count_parcels_with_shelf_reassign(station_id, lo, hi):
    """A parcel with at least one SHELF_REASSIGNED audit event in the period."""
    # Map parcel_id -> bool
    flagged = set()
    for evt in store.audit_events.values():
        if evt["subject_kind"] != "Parcel":
            continue
        if evt["action"] != "SHELF_REASSIGNED":
            continue
        if not _within(evt.get("created_at"), lo, hi):
            continue
        pid = evt["subject_id"]
        p = store.parcels.get(pid)
        if p is None or p["station_id"] != station_id:
            continue
        flagged.add(pid)
    return len(flagged)


def _count_lost_parcels(station_id, lo, hi):
    n = 0
    for p in store.parcels.values():
        if p["station_id"] != station_id:
            continue
        if p["status"] == "REJECTED" and p.get("exception_type") == "WRONG_DELIVERY":
            if _within(p.get("created_at"), lo, hi):
                n += 1
    return n


def _bill_action_counts(station_id, lo, hi):
    """Count (bills_issued_in_period, bills_disputed_in_period)."""
    period_ids = set()
    for bp in store.billing_periods.values():
        if bp["station_id"] != station_id:
            continue
        # Periods overlapping [lo, hi) — use the same period exactly
        # but the assessment is for a specific period_yyyymm; rely on caller.
        if _within(bp.get("period_start"), lo, hi):
            period_ids.add(bp["id"])
    issued = 0
    disputed = 0
    for evt in store.audit_events.values():
        if evt["subject_kind"] != "Bill":
            continue
        if not _within(evt.get("created_at"), lo, hi):
            continue
        if evt["action"] == "BILL_ISSUED":
            issued += 1
        elif evt["action"] == "BILL_DISPUTED":
            disputed += 1
    return issued, disputed


def _reminder_score(station_id, lo, hi):
    """Average of (1 - clamp((delay_minutes - 15)/15, 0, 1)) over reminders in period."""
    deltas = []
    for r in store.reminders.values():
        p = store.parcels.get(r["parcel_id"])
        if p is None or p["station_id"] != station_id:
            continue
        sent_at = r["sent_at"]
        if not _within(sent_at, lo, hi):
            continue
        # Delay: we treat it as the difference between sent_at and the relevant trigger.
        # PRD: for T1_INITIAL, trigger is INBOUND (shelved_at).
        # For T2_FOLLOWUP, trigger is free_storage_deadline.
        # For T3_ESCALATION, trigger is free_storage_deadline + 24h.
        # For T4_RETURN_CONFIRM, trigger is shelved_at + 168h.
        trigger_time = None
        if r["tier"] == "T1_INITIAL":
            trigger_time = p.get("shelved_at")
        elif r["tier"] == "T2_FOLLOWUP":
            trigger_time = p.get("free_storage_deadline")
        elif r["tier"] == "T3_ESCALATION":
            fsd = p.get("free_storage_deadline")
            trigger_time = (fsd + timedelta(hours=24)) if fsd else None
        elif r["tier"] == "T4_RETURN_CONFIRM":
            sa = p.get("shelved_at")
            trigger_time = (sa + timedelta(hours=168)) if sa else None
        if trigger_time is None:
            continue
        delay_minutes = max(0.0, (sent_at - trigger_time).total_seconds() / 60.0)
        clamped = max(0.0, min((delay_minutes - SLA_MINUTES) / SLA_MINUTES, 1.0))
        deltas.append(1.0 - clamped)
    if not deltas:
        return 1.0
    return sum(deltas) / len(deltas)


def close_assessment(station_id, period_yyyymm, actor_role, actor_id):
    qa = get_assessment(station_id, period_yyyymm)
    with GLOBAL_LOCK:
        if qa["status"] != "DRAFT":
            raise_error(E.INVALID_BILL_STATE, "Assessment not DRAFT")
        period_start, period_end = _parse_period(period_yyyymm)

        # Component rates
        shelved_count = _count_period_parcels_shelved(station_id, period_start, period_end)
        mis_count = _count_parcels_with_shelf_reassign(station_id, period_start, period_end)
        mis_rate = (mis_count / shelved_count) if shelved_count > 0 else 0.0

        inbound_count = _count_period_parcels_inbound(station_id, period_start, period_end)
        lost_count = _count_lost_parcels(station_id, period_start, period_end)
        lost_rate = (lost_count / inbound_count) if inbound_count > 0 else 0.0

        issued, disputed = _bill_action_counts(station_id, period_start, period_end)
        complaint_rate = (disputed / issued) if issued > 0 else 0.0

        timeliness = _reminder_score(station_id, period_start, period_end)

        qa["mis_shelving_rate"] = round_rate4(mis_rate)
        qa["lost_parcel_rate"] = round_rate4(lost_rate)
        qa["complaint_rate"] = round_rate4(complaint_rate)
        qa["response_timeliness_score"] = round_rate4(timeliness)
        qa["composite_score"] = quality_composite(
            qa["mis_shelving_rate"], qa["lost_parcel_rate"],
            qa["complaint_rate"], qa["response_timeliness_score"])
        qa["status"] = "CLOSED"
        qa["closed_at"] = now()
        bump(qa)

        # Refresh station.quality_score with latest
        station = store.stations.get(station_id)
        if station is not None:
            station["quality_score"] = qa["composite_score"]
            bump(station)

        return qa
