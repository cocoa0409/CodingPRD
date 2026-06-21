"""Domain layer: serializers, lookups, and the calculation rules (SCAFFOLD §1.3).

Serializers emit exactly the public field set from SCAFFOLD §1.1 (system fields
plus declared input/computed fields). The private bookkeeping key `_seq` is
never serialized.
"""

import math

from db import db
from errors import err
import helpers as h

# Enum domains (SCAFFOLD §1.1).
REQUESTED_MODALITIES = {"IN_LAB_PSG", "HSAT"}
STUDY_MODALITIES = {"IN_LAB_PSG", "HSAT", "IN_LAB_TITRATION"}
IN_LAB_MODALITIES = {"IN_LAB_PSG", "IN_LAB_TITRATION"}
DEVICE_TYPES = {"CPAP", "APAP", "BIPAP"}

# Adherence constants (SCAFFOLD §1.3 cpap_adherence).
MIN_WINDOW_DAYS = 30
MIN_NIGHTS = 21
ADHERENCE_PCT = 0.70
MIN_AVG_MINUTES = 240

# Severity-band constants (SCAFFOLD §1.3 severity_band).
MILD_MIN = 5
MODERATE_MIN = 15
SEVERE_MIN = 30


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(store, rid, not_found_error):
    """Path-id lookup. Raise the entity-specific not-found error if absent."""
    rec = store.get(rid)
    if rec is None:
        raise err(not_found_error, "Resource not found")
    return rec


# ---------------------------------------------------------------------------
# Serializers — public field projection per SCAFFOLD §1.1
# ---------------------------------------------------------------------------
def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_patient(r):
    o = _common(r)
    o.update({
        "full_name": r["full_name"],
        "date_of_birth": r["date_of_birth"],
        "insurance_payer": r["insurance_payer"],
        "baseline_epworth_score": r["baseline_epworth_score"],
    })
    return o


def ser_referral(r):
    o = _common(r)
    o.update({
        "patient_id": r["patient_id"],
        "referring_provider_npi": r["referring_provider_npi"],
        "requested_modality": r["requested_modality"],
        "clinical_indication": r["clinical_indication"],
        "prior_auth_required": r["prior_auth_required"],
        "prior_auth_number": r["prior_auth_number"],
        "prior_auth_expires_on": r["prior_auth_expires_on"],
        "status": r["status"],
    })
    return o


def ser_bed(r):
    o = _common(r)
    o.update({
        "bed_label": r["bed_label"],
        "turnover_buffer_minutes": r["turnover_buffer_minutes"],
        "status": r["status"],
    })
    return o


def ser_study(r):
    o = _common(r)
    o.update({
        "referral_id": r["referral_id"],
        "bed_id": r["bed_id"],
        "modality": r["modality"],
        "night_start_utc": r["night_start_utc"],
        "night_end_utc": r["night_end_utc"],
        "total_recording_minutes": r["total_recording_minutes"],
        "respiratory_event_count": r["respiratory_event_count"],
        "titration_optimal_cmh2o": r["titration_optimal_cmh2o"],
        "ahi": r["ahi"],
        "severity": r["severity"],
        "status": r["status"],
    })
    return o


def ser_scoring(r):
    o = _common(r)
    o.update({
        "study_order_id": r["study_order_id"],
        "scored_by_tech_id": r["scored_by_tech_id"],
        "ahi_snapshot": r["ahi_snapshot"],
        "severity_snapshot": r["severity_snapshot"],
        "interpretation_text": r["interpretation_text"],
        "physician_recommends_cpap": r["physician_recommends_cpap"],
        "status": r["status"],
    })
    return o


def ser_dme(r):
    o = _common(r)
    o.update({
        "study_order_id": r["study_order_id"],
        "supersedes_dme_order_id": r["supersedes_dme_order_id"],
        "device_type": r["device_type"],
        "prescribed_pressure_cmh2o": r["prescribed_pressure_cmh2o"],
        "resupply_cycle_number": r["resupply_cycle_number"],
        "status": r["status"],
    })
    return o


def ser_compliance(r):
    o = _common(r)
    o.update({
        "dme_order_id": r["dme_order_id"],
        "window_start_utc": r["window_start_utc"],
        "window_end_utc": r["window_end_utc"],
        "nights_used_4h_plus": r["nights_used_4h_plus"],
        "total_usage_minutes": r["total_usage_minutes"],
        "adherent": r["adherent"],
    })
    return o


def ser_followup(r):
    o = _common(r)
    o.update({
        "study_order_id": r["study_order_id"],
        "scheduled_for_utc": r["scheduled_for_utc"],
        "post_treatment_epworth_score": r["post_treatment_epworth_score"],
        "epworth_improvement": r["epworth_improvement"],
        "status": r["status"],
    })
    return o


# ---------------------------------------------------------------------------
# Calculation: ahi_index (SCAFFOLD §1.3 / PRD §3.6)
# ---------------------------------------------------------------------------
def compute_ahi(total_recording_minutes, respiratory_event_count):
    """events per hour, to 1 decimal place, round-half-up.

    Pinned evaluation order: recording_hours = minutes / 60 (exact), then
    ahi = events / recording_hours rounded to 1 decimal.
    """
    recording_hours = total_recording_minutes / 60.0
    raw = respiratory_event_count / recording_hours
    return h.round_half_up(raw, 1)


# ---------------------------------------------------------------------------
# Calculation: severity_band (SCAFFOLD §1.3 / PRD §3.6)
# Inclusive lower edge: boundary lands in the higher band.
# ---------------------------------------------------------------------------
def compute_severity(ahi):
    if ahi < MILD_MIN:
        return "NONE"
    if ahi < MODERATE_MIN:
        return "MILD"
    if ahi < SEVERE_MIN:
        return "MODERATE"
    return "SEVERE"


# ---------------------------------------------------------------------------
# Calculation: cpap_adherence (SCAFFOLD §1.3 / PRD §3.10)
# ---------------------------------------------------------------------------
def compute_adherence(window_start_dt, window_end_dt, nights_used_4h_plus,
                      total_usage_minutes):
    seconds = (window_end_dt - window_start_dt).total_seconds()
    window_days = int(math.floor(seconds / 86400.0))
    # Window-length gate FIRST; short-circuit if too short.
    if window_days < MIN_WINDOW_DAYS:
        return False
    avg_used_minutes = (total_usage_minutes / nights_used_4h_plus
                        if nights_used_4h_plus > 0 else 0)
    pct = nights_used_4h_plus / window_days
    return (nights_used_4h_plus >= MIN_NIGHTS
            and pct >= ADHERENCE_PCT
            and avg_used_minutes >= MIN_AVG_MINUTES)


# ---------------------------------------------------------------------------
# Calculation: resupply_cycle_number (SCAFFOLD §1.3 / PRD §3.9)
# ---------------------------------------------------------------------------
def compute_resupply_cycle(supersedes_dme_order_id):
    if supersedes_dme_order_id is None:
        return 1
    prior = db.dme_orders[supersedes_dme_order_id]
    return prior["resupply_cycle_number"] + 1


# ---------------------------------------------------------------------------
# Calculation: epworth_delta (SCAFFOLD §1.3 / PRD §3.11)
# baseline - post-treatment, walking FollowUp -> StudyOrder -> Referral ->
# Patient.
# ---------------------------------------------------------------------------
def compute_epworth_delta(followup, post_treatment_epworth_score):
    study = db.study_orders[followup["study_order_id"]]
    referral = db.referrals[study["referral_id"]]
    patient = db.patients[referral["patient_id"]]
    return patient["baseline_epworth_score"] - post_treatment_epworth_score


# ---------------------------------------------------------------------------
# Bed collision (PRD §3.5): a new night conflicts when it overlaps an existing
# booked night directly OR begins within the turnover buffer that trails an
# existing night on the same bed. The new night's own [start, end + buffer)
# block must not overlap any existing block.
# ---------------------------------------------------------------------------
def _active_bed_holders(bed_id):
    """StudyOrders currently holding a night on this bed (SCHEDULED / running /
    scored / interpreted — i.e. not ORDERED/CANCELLED, which hold no booking)."""
    held = []
    for s in db.study_orders.values():
        if s["bed_id"] != bed_id:
            continue
        if s["status"] in ("SCHEDULED", "IN_PROGRESS", "SCORED", "INTERPRETED"):
            if s["night_start_utc"] and s["night_end_utc"]:
                held.append(s)
    return held


def bed_night_collides(bed, new_start_dt, new_end_dt):
    buffer_ms = bed["turnover_buffer_minutes"] * 60000.0
    new_start_ms = h.epoch_ms(new_start_dt)
    new_end_ms = h.epoch_ms(new_end_dt)
    new_block_end = new_end_ms + buffer_ms
    for s in _active_bed_holders(bed["id"]):
        ex_start = h.epoch_ms(h.parse_iso(s["night_start_utc"]))
        ex_end = h.epoch_ms(h.parse_iso(s["night_end_utc"]))
        ex_block_end = ex_end + buffer_ms
        # Half-open block overlap: [new_start, new_block_end) vs
        # [ex_start, ex_block_end).
        if new_start_ms < ex_block_end and ex_start < new_block_end:
            return True
    return False
