"""Domain logic: lookups, calculations, posture derivation, serialization.

All calculation rules follow SCAFFOLD §1.3 / PRD §2.7, §3.5-3.7.
"""

from db import db
from errors import err
from helpers import round2, parse_iso, epoch_ms, EPOCH, iso_from_dt

# Calculation constants (SCAFFOLD §1.3)
EGFR_MIN = 30
STAT_MULTIPLIER = 1.5
CONTRAST_ADDON = 0.75
AMEND_FACTOR = 0.5

STAT_TARGET_MIN = {"MRI": 60, "CT": 45, "XRAY": 30, "US": 45}
ROUTINE_TARGET_MIN = {"MRI": 1440, "CT": 720, "XRAY": 240, "US": 480}

MODALITY_TYPES = {"MRI", "CT", "XRAY", "US"}
REJECT_REASONS = {"MOTION", "POSITIONING", "EXPOSURE", "ARTIFACT", "EQUIPMENT"}


# ---------------------------------------------------------------------------
# Lookups (priority 3 existence — ERR_NOT_FOUND for path ids)
# ---------------------------------------------------------------------------
def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found: %s" % rid)
    return rec


def get_ref_or_404(collection, rid):
    """FK body field existence (priority 4 — ERR_REFERENCE_NOT_FOUND)."""
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced resource not found: %s" % rid)
    return rec


# ---------------------------------------------------------------------------
# Center clock helpers
# ---------------------------------------------------------------------------
def center_now_dt(center):
    return parse_iso(center["now_utc"], "now_utc")


# ---------------------------------------------------------------------------
# Repeat/reject rate aggregate (SCAFFOLD calc repeat_reject_rate, PRD §3.5)
# ---------------------------------------------------------------------------
def recompute_rate(center):
    acquired = center["total_acquired_series"]
    rr = center["total_repeat_reject_series"]
    if acquired == 0:
        center["repeat_reject_rate_pct"] = 0.0
    else:
        center["repeat_reject_rate_pct"] = round2(100.0 * rr / acquired)


# ---------------------------------------------------------------------------
# SLA re-evaluation for a single critical result (calc critical_ack_sla)
# ---------------------------------------------------------------------------
def recompute_critical_sla(cr, center):
    sla = center["critical_ack_sla_minutes"]
    raised = parse_iso(cr["raised_at_utc"], "raised_at_utc")
    if cr["status"] == "ACKNOWLEDGED":
        # minutes_to_ack already computed at acknowledge time; breach is fixed
        # on the acknowledged comparison.
        if cr["minutes_to_ack"] is not None:
            cr["sla_breached"] = cr["minutes_to_ack"] > sla
    else:
        # Still UNACKNOWLEDGED: elapsed from raised to current center clock.
        now = center_now_dt(center)
        elapsed = (epoch_ms(now) - epoch_ms(raised)) / 60000.0
        cr["sla_breached"] = elapsed > sla


def recompute_all_critical_sla(center):
    cid = center["id"]
    for cr in db.critical_results.values():
        if cr["imaging_center_id"] == cid:
            recompute_critical_sla(cr, center)


# ---------------------------------------------------------------------------
# Posture derivation (calc posture_derivation, PRD §2.8)
# ---------------------------------------------------------------------------
def derive_posture(center):
    if center["admin_locked"]:
        center["posture"] = "LOCKED"
        return
    rate = center["repeat_reject_rate_pct"]
    threshold = center["repeat_rate_threshold_pct"]
    breached = False
    cid = center["id"]
    for cr in db.critical_results.values():
        if cr["imaging_center_id"] == cid and cr.get("sla_breached"):
            breached = True
            break
    if rate >= threshold or breached:
        center["posture"] = "QUALITY_HOLD"
    else:
        center["posture"] = "OPEN"


# ---------------------------------------------------------------------------
# Screening decision (calc screening_decision, PRD §3.3)
# ---------------------------------------------------------------------------
def screening_decision(screening, order, modality):
    requires_contrast = order["requires_contrast"]
    modality_type = modality["modality_type"]
    # 1. Pregnancy
    if screening["is_pregnant"] and (requires_contrast or modality_type == "CT"):
        return "BLOCKED", "PREGNANCY"
    # 2. Metal implant (MRI only)
    if modality_type == "MRI" and screening["metal_implant_unsafe"]:
        return "BLOCKED", "METAL_IMPLANT"
    # 3. Contrast allergy
    if requires_contrast and screening["has_contrast_allergy"]:
        return "BLOCKED", "CONTRAST_ALLERGY"
    # 4. Renal function
    if requires_contrast and screening["egfr_value"] < EGFR_MIN:
        return "BLOCKED", "RENAL_FUNCTION"
    return "CLEARED", None


# ---------------------------------------------------------------------------
# RVU credit (calc rvu_credit, PRD §3.6)
# ---------------------------------------------------------------------------
def compute_rvu(modality, order, amended):
    base = modality["base_rvu"]
    stat_factor = STAT_MULTIPLIER if order["priority"] == "STAT" else 1.0
    contrast_add = CONTRAST_ADDON if order["requires_contrast"] else 0.0
    amend_factor = AMEND_FACTOR if amended else 1.0
    raw = (base * stat_factor + contrast_add) * amend_factor
    return round2(raw)


# ---------------------------------------------------------------------------
# Report turnaround + target (calc report_turnaround / turnaround_target)
# ---------------------------------------------------------------------------
def compute_turnaround(exam):
    acquired = parse_iso(exam["acquired_at_utc"], "acquired_at_utc")
    signed = parse_iso(exam["signed_off_at_utc"], "signed_off_at_utc")
    minutes = (epoch_ms(signed) - epoch_ms(acquired)) / 60000.0
    return round2(minutes)


def turnaround_target(order, modality):
    mt = modality["modality_type"]
    if order["priority"] == "STAT":
        return STAT_TARGET_MIN[mt]
    return ROUTINE_TARGET_MIN[mt]


# ---------------------------------------------------------------------------
# Serializers — strip internals, surface only PRD-declared fields.
# ---------------------------------------------------------------------------
_COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(rec, fields):
    out = {}
    for f in _COMMON:
        out[f] = rec[f]
    for f in fields:
        out[f] = rec.get(f)
    return out


def ser_center(c):
    return _pick(c, [
        "name", "time_zone", "now_utc", "critical_ack_sla_minutes",
        "repeat_rate_threshold_pct", "admin_locked", "posture",
        "total_acquired_series", "total_repeat_reject_series",
        "repeat_reject_rate_pct",
    ])


def ser_modality(m):
    return _pick(m, [
        "imaging_center_id", "modality_type", "name", "base_rvu",
        "requires_contrast_screening", "requires_prior_auth",
    ])


def ser_room(r):
    return _pick(r, [
        "imaging_center_id", "modality_id", "name",
        "cleanup_buffer_minutes", "status",
    ])


def ser_staff(s):
    return _pick(s, [
        "imaging_center_id", "staff_role", "full_name",
        "credentialed_modalities", "signed_rvu_total",
    ])


def ser_order(o):
    return _pick(o, [
        "imaging_center_id", "modality_id", "patient_mrn",
        "ordering_provider_npi", "priority", "requires_contrast", "status",
        "report_turnaround_minutes", "turnaround_met",
    ])


def ser_prior_auth(p):
    return _pick(p, [
        "imaging_order_id", "payer_name", "requested_units",
        "authorized_units", "benefit_copay_cents", "status",
    ])


def ser_screening(s):
    return _pick(s, [
        "imaging_order_id", "egfr_value", "has_contrast_allergy",
        "is_pregnant", "metal_implant_unsafe", "outcome", "blocking_reason",
    ])


def ser_exam(e):
    return _pick(e, [
        "imaging_order_id", "room_id", "technologist_id", "radiologist_id",
        "scheduled_start_utc", "scheduled_end_utc", "acquired_at_utc",
        "signed_off_at_utc", "status",
    ])


def ser_series(s):
    return _pick(s, [
        "imaging_exam_id", "imaging_center_id", "series_label",
        "outcome", "reject_reason",
    ])


def ser_report(r):
    return _pick(r, [
        "imaging_exam_id", "radiologist_id", "findings_text",
        "has_critical_finding", "rvu_credited", "addendum_count", "status",
    ])


def ser_critical(c):
    return _pick(c, [
        "radiology_report_id", "imaging_center_id", "notified_party_role",
        "raised_at_utc", "acknowledged_at_utc", "minutes_to_ack",
        "sla_breached", "status",
    ])
