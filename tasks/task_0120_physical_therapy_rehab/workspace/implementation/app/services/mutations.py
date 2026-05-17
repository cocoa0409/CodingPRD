"""Core state-machine mutations.

This is the bulk of the business logic — every state transition, with its
preconditions, side effects, and cascade rules.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..clock import iso_format, now
from ..errors import (
    err_cap_exceeded,
    err_cert_period_too_long,
    err_clinician_double_booked,
    err_episode_not_active,
    err_insufficient_units,
    err_invalid_mips_exception,
    err_invalid_state,
    err_out_of_auth_window,
    err_patient_double_booked,
    err_poc_visit_limit,
    err_reeval_due,
    err_reference_not_found,
    err_segregation_of_duties,
    err_therapist_not_licensed,
    err_validation,
    err_va_reference_mismatch,
    err_va_referral_exhausted,
    err_veteran_referral_required,
)
from ..helpers import new_uuid
from ..store import store
from .calculations import (
    billed_units_eight_minute_rule,
    capped_poc_projection,
    mips_quality_score,
    visit_charge_cents,
)
from .constants import CAP_HARD_CENTS, KX_THRESHOLD_CENTS
from .lookups import (
    get_authorization_ref,
    get_evaluation_ref,
    get_poc_ref,
    get_therapist_ref,
)


# ---------- helpers ---------------------------------------------------------

def _bump(row: dict[str, Any], current: datetime) -> None:
    row["updated_at"] = current
    row["version"] = row.get("version", 1) + 1


def _new_common(current: datetime) -> dict[str, Any]:
    return {
        "id": new_uuid(),
        "created_at": current,
        "updated_at": current,
        "version": 1,
    }


def _new_append_only(current: datetime) -> dict[str, Any]:
    return {
        "id": new_uuid(),
        "created_at": current,
    }


def _parse_iso(s: str | datetime) -> datetime:
    if isinstance(s, datetime):
        if s.tzinfo is None:
            return s.replace(tzinfo=timezone.utc)
        return s.astimezone(timezone.utc)
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _latest_finalized_eval(episode_id: str) -> dict | None:
    db = store()
    candidates = [
        e for e in db.evaluations.values()
        if e["episode_id"] == episode_id and e.get("status") in ("FINALIZED", "AMENDED")
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda e: e.get("finalized_at") or datetime.min.replace(tzinfo=timezone.utc),
    )


def recompute_episode_units(ep: dict) -> None:
    db = store()
    eid = ep["id"]
    ep["total_authorized_units"] = sum(
        a["unit_quota"] for a in db.authorizations.values()
        if a["episode_id"] == eid and a.get("status") == "APPROVED"
    )
    ep["total_reserved_units"] = sum(
        v["units_planned"] for v in db.visits.values()
        if v["episode_id"] == eid and v.get("status") in ("SCHEDULED", "IN_SESSION")
    )
    ep["total_committed_units"] = sum(
        v.get("units_billed", 0) for v in db.visits.values()
        if v["episode_id"] == eid and v.get("status") in ("SIGNED", "BILLED")
    )


# ---------- Therapist creation ----------------------------------------------

def create_therapist(full_name: str, npi: str, credential: str) -> dict[str, Any]:
    current = now()
    db = store()
    row = _new_common(current)
    row.update({
        "full_name": full_name,
        "npi": npi,
        "credential": credential,
        "can_evaluate": credential in ("PT", "DPT"),
        "status": "ACTIVE",
    })
    db.therapists[row["id"]] = row
    db.npi_index[npi] = row["id"]
    return row


# ---------- Patient creation ------------------------------------------------

def create_patient(
    full_name: str,
    date_of_birth: str,
    insurance_type: str,
    medicare_beneficiary_id: str | None,
    va_referral_id: str | None,
) -> dict[str, Any]:
    current = now()
    db = store()
    row = _new_common(current)
    row.update({
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "insurance_type": insurance_type,
        "medicare_beneficiary_id": medicare_beneficiary_id,
        "va_referral_id": va_referral_id,
        "ytd_capped_amount_cents": 0,
        "status": "ACTIVE",
    })
    db.patients[row["id"]] = row
    return row


# ---------- VeteranReferral -------------------------------------------------

def create_veteran_referral(
    patient_id: str,
    referring_va_facility_code: str,
    authorized_units: int,
    valid_from: str,
    valid_through: str,
) -> dict[str, Any]:
    current = now()
    db = store()
    row = _new_append_only(current)
    row.update({
        "patient_id": patient_id,
        "referring_va_facility_code": referring_va_facility_code,
        "authorized_units": authorized_units,
        "valid_from": valid_from,
        "valid_through": valid_through,
        "status": "ACTIVE",
    })
    db.veteran_referrals[row["id"]] = row
    return row


# ---------- Episode ---------------------------------------------------------

def create_episode(patient_id: str, referring_provider_npi: str, body_region: str) -> dict[str, Any]:
    current = now()
    db = store()
    row = _new_common(current)
    row.update({
        "patient_id": patient_id,
        "referring_provider_npi": referring_provider_npi,
        "body_region": body_region,
        "status": "DRAFT",
        "cap_policy": None,
        "kx_modifier_required": False,
        "total_authorized_units": 0,
        "total_committed_units": 0,
        "total_reserved_units": 0,
        "discharge_outcome": None,
    })
    db.episodes.setdefault(row["id"], row)
    return row


def cancel_draft_episode(episode: dict[str, Any]) -> None:
    if episode.get("status") != "DRAFT":
        raise err_invalid_state(f"Episode must be in DRAFT to cancel; current is {episode.get('status')}")
    current = now()
    episode["status"] = "CANCELLED"
    _bump(episode, current)


# ---------- Evaluation ------------------------------------------------------

def create_evaluation(
    episode: dict[str, Any],
    evaluation_type: str,
    clinician_id: str,
    complexity: str,
    functional_baseline_score: int,
) -> dict[str, Any]:
    current = now()
    db = store()
    # clinician_id reference check
    get_therapist_ref(clinician_id)
    row = _new_common(current)
    row.update({
        "episode_id": episode["id"],
        "evaluation_type": evaluation_type,
        "clinician_id": clinician_id,
        "complexity": complexity,
        "functional_baseline_score": functional_baseline_score,
        "status": "DRAFT",
        "finalized_at": None,
    })
    db.evaluations[row["id"]] = row
    return row


def finalize_evaluation(evaluation: dict[str, Any], caller_id: str) -> dict[str, Any]:
    db = store()
    current = now()
    # State precondition
    if evaluation.get("status") != "DRAFT":
        raise err_invalid_state(f"Evaluation must be in DRAFT; current is {evaluation.get('status')}")
    # Authentication / capability: acting therapist must be can_evaluate=true
    therapist = db.therapists.get(caller_id)
    if not therapist or not therapist.get("can_evaluate"):
        raise err_therapist_not_licensed()
    # Score range
    score = evaluation.get("functional_baseline_score")
    if not isinstance(score, int) or score < 0 or score > 100:
        raise err_validation("functional_baseline_score must be in [0,100]")
    # Apply finalize
    evaluation["status"] = "FINALIZED"
    evaluation["finalized_at"] = current
    _bump(evaluation, current)

    # Cascade Episode
    episode = db.episodes.get(evaluation["episode_id"])
    if not episode:
        return evaluation

    if evaluation["evaluation_type"] == "INITIAL" and episode.get("status") == "DRAFT":
        episode["status"] = "EVALUATED"
        # cap_policy stamped from patient.insurance_type
        patient = db.patients.get(episode["patient_id"])
        if patient and patient.get("insurance_type") == "MEDICARE_PART_B":
            episode["cap_policy"] = "CAPPED"
        else:
            episode["cap_policy"] = "UNCAPPED"
        _bump(episode, current)
    elif evaluation["evaluation_type"] == "REEVAL" and episode.get("status") == "REEVAL_DUE":
        episode["status"] = "ACTIVE"
        _bump(episode, current)

    return evaluation


def amend_evaluation(
    evaluation: dict[str, Any],
    caller_id: str,
    new_score: int | None,
    new_complexity: str | None,
) -> dict[str, Any]:
    db = store()
    current = now()
    if evaluation.get("status") != "FINALIZED":
        raise err_invalid_state(f"Evaluation must be FINALIZED to amend; current is {evaluation.get('status')}")
    # caller capability check
    therapist = db.therapists.get(caller_id)
    if not therapist or not therapist.get("can_evaluate"):
        raise err_therapist_not_licensed()
    if evaluation["clinician_id"] != caller_id:
        # PRD: "Same clinician_id as the FINALIZED evaluation"
        raise err_invalid_state("Amend must be performed by the same clinician who finalized")
    episode = db.episodes.get(evaluation["episode_id"])
    if episode and episode.get("status") in ("DISCHARGED", "CANCELLED"):
        raise err_invalid_state("Episode is terminal; amend not allowed")

    if new_score is not None:
        if not isinstance(new_score, int) or new_score < 0 or new_score > 100:
            raise err_validation("functional_baseline_score must be in [0,100]")
        evaluation["functional_baseline_score"] = new_score
    if new_complexity is not None:
        evaluation["complexity"] = new_complexity
    evaluation["status"] = "AMENDED"
    _bump(evaluation, current)

    # Re-run capped projection on any non-terminal PlanOfCare referencing this evaluation
    for poc in db.plan_of_cares.values():
        if poc["evaluation_id"] == evaluation["id"] and poc.get("status") in ("DRAFT", "CERTIFIED", "ACTIVE"):
            poc["capped_projection_cents"] = capped_poc_projection(
                poc["planned_visit_count"], poc["planned_units_per_visit"], evaluation["complexity"],
            )
            _bump(poc, current)
            if episode and episode.get("cap_policy") == "CAPPED":
                patient = db.patients.get(episode["patient_id"])
                if patient:
                    projected_total = patient.get("ytd_capped_amount_cents", 0) + poc["capped_projection_cents"]
                    if projected_total > KX_THRESHOLD_CENTS:
                        if not episode.get("kx_modifier_required"):
                            episode["kx_modifier_required"] = True
                            _bump(episode, current)

    return evaluation


# ---------- PlanOfCare ------------------------------------------------------

def create_plan_of_care(
    episode: dict[str, Any],
    evaluation_id: str,
    certifying_physician_npi: str,
    planned_visit_count: int,
    planned_units_per_visit: int,
    cert_period_start: str,
    cert_period_end: str,
) -> dict[str, Any]:
    current = now()
    db = store()
    # evaluation reference check
    evaluation = get_evaluation_ref(evaluation_id)
    if evaluation["episode_id"] != episode["id"]:
        raise err_reference_not_found("evaluation does not belong to this episode")
    # cert window validation
    _validate_cert_window(cert_period_start, cert_period_end)
    row = _new_common(current)
    row.update({
        "episode_id": episode["id"],
        "evaluation_id": evaluation_id,
        "certifying_physician_npi": certifying_physician_npi,
        "planned_visit_count": planned_visit_count,
        "planned_units_per_visit": planned_units_per_visit,
        "cert_period_start": cert_period_start,
        "cert_period_end": cert_period_end,
        "status": "DRAFT",
        "capped_projection_cents": None,
    })
    db.plan_of_cares[row["id"]] = row
    return row


def _validate_cert_window(cert_start: str, cert_end: str) -> None:
    start = _parse_iso(cert_start)
    end = _parse_iso(cert_end)
    if end <= start:
        raise err_cert_period_too_long("cert_period_end must be after cert_period_start")
    diff_days = (end - start).total_seconds() / 86400
    if diff_days > 90:
        raise err_cert_period_too_long("cert window must not exceed 90 days")


def certify_plan_of_care(poc: dict[str, Any]) -> dict[str, Any]:
    db = store()
    current = now()
    if poc.get("status") != "DRAFT":
        raise err_invalid_state(f"PlanOfCare must be in DRAFT to certify; current is {poc.get('status')}")
    evaluation = db.evaluations.get(poc["evaluation_id"])
    if not evaluation or evaluation.get("status") not in ("FINALIZED", "AMENDED"):
        raise err_invalid_state("PlanOfCare's anchoring evaluation must be FINALIZED or AMENDED")
    _validate_cert_window(poc["cert_period_start"], poc["cert_period_end"])

    # Compute capped projection
    poc["capped_projection_cents"] = capped_poc_projection(
        poc["planned_visit_count"], poc["planned_units_per_visit"], evaluation["complexity"],
    )

    # Look for an APPROVED authorization with sufficient unit_quota whose window covers cert_period_start
    cert_start_dt = _parse_iso(poc["cert_period_start"])
    needed_units = poc["planned_visit_count"] * poc["planned_units_per_visit"]
    has_coverage = False
    for auth in db.authorizations.values():
        if auth["episode_id"] != poc["episode_id"]:
            continue
        if auth.get("status") != "APPROVED":
            continue
        if auth["unit_quota"] < needed_units:
            continue
        valid_from = _parse_iso(auth["valid_from"])
        valid_through = _parse_iso(auth["valid_through"])
        # inclusive end-of-day for valid_through if it's a midnight date
        vt_end = valid_through.replace(hour=23, minute=59, second=59, microsecond=999999) \
            if valid_through.hour == 0 and valid_through.minute == 0 else valid_through
        if valid_from <= cert_start_dt <= vt_end:
            has_coverage = True
            break
    if not has_coverage:
        raise err_invalid_state("No APPROVED authorization with sufficient unit coverage spanning cert_period_start")

    # DRAFT -> CERTIFIED -> ACTIVE in same request
    poc["status"] = "ACTIVE"
    _bump(poc, current)

    # Cascade episode and KX
    episode = db.episodes.get(poc["episode_id"])
    if episode:
        if episode.get("status") == "EVALUATED":
            episode["status"] = "ACTIVE"
            _bump(episode, current)
        if episode.get("cap_policy") == "CAPPED":
            patient = db.patients.get(episode["patient_id"])
            if patient:
                projected_total = patient.get("ytd_capped_amount_cents", 0) + poc["capped_projection_cents"]
                if projected_total > KX_THRESHOLD_CENTS:
                    if not episode.get("kx_modifier_required"):
                        episode["kx_modifier_required"] = True
                        _bump(episode, current)
    return poc


def revoke_plan_of_care(poc: dict[str, Any], caller_id: str) -> dict[str, Any]:
    db = store()
    current = now()
    if poc.get("status") != "ACTIVE":
        raise err_invalid_state(f"PlanOfCare must be ACTIVE to revoke; current is {poc.get('status')}")
    therapist = db.therapists.get(caller_id)
    if not therapist or not therapist.get("can_evaluate"):
        raise err_therapist_not_licensed()
    poc["status"] = "REVOKED"
    _bump(poc, current)
    # Cancel SCHEDULED visits on this plan; release reservations
    episode = db.episodes.get(poc["episode_id"])
    for v in list(db.visits.values()):
        if v["plan_of_care_id"] == poc["id"] and v.get("status") == "SCHEDULED":
            v["status"] = "CANCELLED"
            _bump(v, current)
    if episode:
        recompute_episode_units(episode)
        _bump(episode, current)
    return poc


# ---------- Authorization ---------------------------------------------------

def create_authorization(
    episode: dict[str, Any],
    plan_of_care_id: str,
    source: str,
    external_reference: str,
    unit_quota: int,
    valid_from: str,
    valid_through: str,
) -> dict[str, Any]:
    current = now()
    db = store()
    poc = get_poc_ref(plan_of_care_id)
    if poc["episode_id"] != episode["id"]:
        raise err_reference_not_found("plan_of_care does not belong to this episode")

    # VA referral linkage validation
    if source == "VA_REFERRAL":
        patient = db.patients.get(episode["patient_id"])
        # external_reference must equal an ACTIVE VeteranReferral.id AND Patient.va_referral_id
        ref = db.veteran_referrals.get(external_reference)
        if (not ref) or ref.get("status") != "ACTIVE":
            raise err_va_reference_mismatch("VA referral not found or not ACTIVE")
        if not patient:
            raise err_va_reference_mismatch("Patient missing")
        # PRD §3.4: "external_reference must equal ... the va_referral_id
        # recorded on the patient ... The platform mirrors the referral
        # id onto Patient.va_referral_id when a VA-sourced authorization
        # is created."  The mirror is the mechanism the PRD uses to keep
        # the two values in agreement. We enforce the mismatch error
        # only when the patient is already pinned to a DIFFERENT VA
        # referral by a prior VA-sourced authorization on the same
        # patient; the bootstrap case (no prior VA auth) mirrors.
        prior_va_auth_ref = None
        for a in db.authorizations.values():
            if a.get("source") != "VA_REFERRAL":
                continue
            ep = db.episodes.get(a["episode_id"])
            if not ep or ep.get("patient_id") != patient["id"]:
                continue
            prior_va_auth_ref = a.get("external_reference")
            break
        if prior_va_auth_ref is not None and prior_va_auth_ref != external_reference:
            raise err_va_reference_mismatch("Patient.va_referral_id mismatch")
        # Mirror: stamp external_reference onto Patient.va_referral_id.
        if patient.get("va_referral_id") != external_reference:
            patient["va_referral_id"] = external_reference
            _bump(patient, current)
        # Combined unit_quota across all APPROVED VA_REFERRAL auths linked to this referral
        # must not exceed referral.authorized_units
        existing_sum = 0
        for a in db.authorizations.values():
            if a.get("source") == "VA_REFERRAL" and a.get("external_reference") == external_reference \
               and a.get("status") == "APPROVED":
                existing_sum += a["unit_quota"]
        if existing_sum + unit_quota > ref["authorized_units"]:
            raise err_va_referral_exhausted()
        # If fully consumed, the referral transitions to CONSUMED (after this auth lands)
        will_total = existing_sum + unit_quota
        if will_total >= ref["authorized_units"]:
            ref["status"] = "CONSUMED"

    row = _new_common(current)
    row.update({
        "episode_id": episode["id"],
        "plan_of_care_id": plan_of_care_id,
        "source": source,
        "external_reference": external_reference,
        "unit_quota": unit_quota,
        "valid_from": valid_from,
        "valid_through": valid_through,
        "status": "APPROVED",
    })
    db.authorizations[row["id"]] = row
    # Recompute episode rollup
    recompute_episode_units(episode)
    _bump(episode, current)
    return row


# ---------- Visit -----------------------------------------------------------

def create_visit(
    episode: dict[str, Any],
    plan_of_care_id: str,
    authorization_id: str,
    clinician_id: str,
    scheduled_start: datetime,
    scheduled_end: datetime,
    units_planned: int,
) -> dict[str, Any]:
    """Schedule a visit on episode. Order of validation matches §2.6."""
    db = store()
    current = now()
    # Episode state checks
    if episode.get("status") == "REEVAL_DUE":
        raise err_reeval_due()
    if episode.get("status") != "ACTIVE":
        raise err_episode_not_active()

    # Body references
    poc = get_poc_ref(plan_of_care_id)
    if poc.get("status") != "ACTIVE":
        raise err_invalid_state(f"PlanOfCare must be ACTIVE; current is {poc.get('status')}")
    if poc["episode_id"] != episode["id"]:
        raise err_reference_not_found("plan_of_care does not belong to this episode")
    auth = get_authorization_ref(authorization_id)
    if auth["episode_id"] != episode["id"]:
        raise err_reference_not_found("authorization does not belong to this episode")
    therapist = get_therapist_ref(clinician_id)

    if auth.get("status") != "APPROVED":
        raise err_invalid_state(f"Authorization must be APPROVED; current is {auth.get('status')}")

    # Veteran referral requirement (priority 10)
    patient = db.patients.get(episode["patient_id"])
    if patient and patient.get("insurance_type") == "VA":
        has_va_auth = False
        for a in db.authorizations.values():
            if a["episode_id"] == episode["id"] and a.get("source") == "VA_REFERRAL":
                ref = db.veteran_referrals.get(a.get("external_reference"))
                if ref and ref.get("status") == "ACTIVE":
                    has_va_auth = True
                    break
                # Note: ref may have become CONSUMED but auths are still APPROVED
                if ref and ref.get("status") in ("CONSUMED",) and a.get("status") == "APPROVED":
                    has_va_auth = True
                    break
        if not has_va_auth:
            raise err_veteran_referral_required()

    # Cert window / auth window
    poc_start = _parse_iso(poc["cert_period_start"])
    poc_end = _parse_iso(poc["cert_period_end"])
    poc_end_inc = poc_end.replace(hour=23, minute=59, second=59, microsecond=999999) \
        if poc_end.hour == 0 and poc_end.minute == 0 else poc_end
    auth_from = _parse_iso(auth["valid_from"])
    auth_through = _parse_iso(auth["valid_through"])
    auth_through_inc = auth_through.replace(hour=23, minute=59, second=59, microsecond=999999) \
        if auth_through.hour == 0 and auth_through.minute == 0 else auth_through

    if scheduled_end <= scheduled_start:
        raise err_validation("scheduled_end must be strictly after scheduled_start")

    if not (auth_from <= scheduled_start <= auth_through_inc):
        raise err_out_of_auth_window("Visit scheduled_start outside authorization window")
    if not (poc_start <= scheduled_start <= poc_end_inc):
        raise err_out_of_auth_window("Visit scheduled_start outside plan certification window")

    # POC visit limit
    poc_visit_count = sum(
        1 for v in db.visits.values()
        if v["plan_of_care_id"] == poc["id"] and v.get("status") in ("SCHEDULED", "IN_SESSION", "SIGNED", "BILLED")
    )
    if poc_visit_count + 1 > poc["planned_visit_count"]:
        raise err_poc_visit_limit()

    # Insufficient units
    recompute_episode_units(episode)
    if episode["total_reserved_units"] + episode["total_committed_units"] + units_planned > episode["total_authorized_units"]:
        raise err_insufficient_units()

    # Double-booking — clinician (half-open)
    for other in db.visits.values():
        if other.get("status") not in ("SCHEDULED", "IN_SESSION", "SIGNED"):
            continue
        if other["clinician_id"] != clinician_id:
            continue
        o_start = _parse_iso(other["scheduled_start"])
        o_end = _parse_iso(other["scheduled_end"])
        # half-open [start, end): overlap iff start < o_end AND o_start < end
        if scheduled_start < o_end and o_start < scheduled_end:
            raise err_clinician_double_booked()

    # Double-booking — patient (closed)
    for other in db.visits.values():
        if other.get("status") not in ("SCHEDULED", "IN_SESSION", "SIGNED"):
            continue
        other_episode = db.episodes.get(other["episode_id"])
        if not other_episode or other_episode["patient_id"] != episode["patient_id"]:
            continue
        o_start = _parse_iso(other["scheduled_start"])
        o_end = _parse_iso(other["scheduled_end"])
        # closed [start, end]: overlap iff start <= o_end AND o_start <= end
        if scheduled_start <= o_end and o_start <= scheduled_end:
            raise err_patient_double_booked()

    row = _new_common(current)
    row.update({
        "episode_id": episode["id"],
        "plan_of_care_id": plan_of_care_id,
        "authorization_id": authorization_id,
        "clinician_id": clinician_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "units_planned": units_planned,
        "timed_minutes": 0,
        "units_billed": 0,
        "charge_cents": 0,
        "kx_applied": False,
        "status": "SCHEDULED",
    })
    db.visits[row["id"]] = row
    recompute_episode_units(episode)
    _bump(episode, current)
    return row


def start_visit(visit: dict[str, Any]) -> dict[str, Any]:
    db = store()
    current = now()
    if visit.get("status") != "SCHEDULED":
        raise err_invalid_state(f"Visit must be SCHEDULED; current is {visit.get('status')}")
    episode = db.episodes.get(visit["episode_id"])
    if not episode:
        raise err_reference_not_found("episode missing")
    if episode.get("status") != "ACTIVE":
        raise err_episode_not_active()
    poc = db.plan_of_cares.get(visit["plan_of_care_id"])
    if not poc or poc.get("status") != "ACTIVE":
        raise err_invalid_state("PlanOfCare must be ACTIVE")
    auth = db.authorizations.get(visit["authorization_id"])
    if not auth or auth.get("status") != "APPROVED":
        raise err_invalid_state("Authorization must be APPROVED")
    auth_through = _parse_iso(auth["valid_through"])
    auth_through_inc = auth_through.replace(hour=23, minute=59, second=59, microsecond=999999) \
        if auth_through.hour == 0 and auth_through.minute == 0 else auth_through
    if auth_through_inc < _parse_iso(visit["scheduled_start"]):
        raise err_invalid_state("Authorization no longer covers scheduled_start")
    recompute_episode_units(episode)
    if episode["total_reserved_units"] + episode["total_committed_units"] > episode["total_authorized_units"]:
        raise err_insufficient_units()
    visit["status"] = "IN_SESSION"
    _bump(visit, current)
    return visit


def sign_visit(visit: dict[str, Any], timed_minutes: int, caller_id: str) -> dict[str, Any]:
    db = store()
    current = now()
    if visit.get("status") != "IN_SESSION":
        raise err_invalid_state(f"Visit must be IN_SESSION; current is {visit.get('status')}")
    # PRD §3.5: "timed_minutes ... must be at least 8 to count for any
    # units. The platform computes units_billed under the CMS 8-Minute
    # Rule: when timed_minutes is strictly less than 8 the billed units
    # are 0." Non-integer or negative values remain validation errors;
    # 0..7 is a valid input that yields units_billed=0.
    if not isinstance(timed_minutes, int) or timed_minutes < 0:
        raise err_validation("timed_minutes must be a non-negative integer")
    episode = db.episodes.get(visit["episode_id"])
    if not episode:
        raise err_reference_not_found("episode missing")

    # Compute units_billed and charge
    units_billed = billed_units_eight_minute_rule(timed_minutes)
    clinician = db.therapists.get(visit["clinician_id"])
    credential = clinician["credential"] if clinician else "PT"

    # Check for an evaluation whose finalized_at falls within visit window
    eval_complexity_in_window: str | None = None
    v_start = _parse_iso(visit["scheduled_start"])
    v_end = _parse_iso(visit["scheduled_end"])
    for e in db.evaluations.values():
        if e["episode_id"] != episode["id"]:
            continue
        if e.get("status") not in ("FINALIZED", "AMENDED"):
            continue
        fa = e.get("finalized_at")
        if fa and v_start <= fa <= v_end:
            eval_complexity_in_window = e["complexity"]
            break

    charge_cents = visit_charge_cents(units_billed, credential, eval_complexity_in_window)

    # Cap policy enforcement
    patient = db.patients.get(episode["patient_id"])
    kx_applied = False
    if episode.get("cap_policy") == "CAPPED" and patient is not None:
        new_ytd = patient.get("ytd_capped_amount_cents", 0) + charge_cents
        if new_ytd > CAP_HARD_CENTS:
            raise err_cap_exceeded()
        # Apply
        patient["ytd_capped_amount_cents"] = new_ytd
        _bump(patient, current)
        if new_ytd > KX_THRESHOLD_CENTS:
            if not episode.get("kx_modifier_required"):
                episode["kx_modifier_required"] = True
            kx_applied = True

    visit["timed_minutes"] = timed_minutes
    visit["units_billed"] = units_billed
    visit["charge_cents"] = charge_cents
    visit["kx_applied"] = kx_applied
    visit["status"] = "SIGNED"
    _bump(visit, current)

    recompute_episode_units(episode)
    _bump(episode, current)
    return visit


def cancel_visit(visit: dict[str, Any]) -> dict[str, Any]:
    db = store()
    current = now()
    if visit.get("status") not in ("SCHEDULED", "IN_SESSION"):
        raise err_invalid_state(f"Visit must be SCHEDULED or IN_SESSION; current is {visit.get('status')}")
    visit["status"] = "CANCELLED"
    _bump(visit, current)
    episode = db.episodes.get(visit["episode_id"])
    if episode:
        recompute_episode_units(episode)
        _bump(episode, current)
    return visit


def submit_claim(visit: dict[str, Any]) -> dict[str, Any]:
    db = store()
    current = now()
    if visit.get("status") != "SIGNED":
        raise err_invalid_state(f"Visit must be SIGNED; current is {visit.get('status')}")
    episode = db.episodes.get(visit["episode_id"])
    patient = db.patients.get(episode["patient_id"]) if episode else None
    if episode and episode.get("cap_policy") == "CAPPED" and patient is not None:
        # At sign time, if ytd_capped > threshold, kx_applied must be true
        if patient.get("ytd_capped_amount_cents", 0) > KX_THRESHOLD_CENTS and not visit.get("kx_applied"):
            raise err_invalid_state("Visit must carry kx_applied=true for cap-tripping submission")
    visit["status"] = "BILLED"
    _bump(visit, current)
    return visit


# ---------- HomeExerciseProgram ---------------------------------------------

def create_hep(
    episode: dict[str, Any],
    plan_of_care_id: str,
    prescribing_clinician_id: str,
    exercise_items: list[dict[str, Any]],
) -> dict[str, Any]:
    db = store()
    current = now()
    if episode.get("status") != "ACTIVE":
        raise err_episode_not_active()
    poc = get_poc_ref(plan_of_care_id)
    if poc["episode_id"] != episode["id"]:
        raise err_reference_not_found("plan_of_care does not belong to this episode")
    if poc.get("status") != "ACTIVE":
        raise err_invalid_state("PlanOfCare must be ACTIVE")
    get_therapist_ref(prescribing_clinician_id)
    if not isinstance(exercise_items, list) or len(exercise_items) == 0:
        raise err_validation("exercise_items must be a non-empty array")
    row = _new_common(current)
    row.update({
        "episode_id": episode["id"],
        "plan_of_care_id": plan_of_care_id,
        "prescribing_clinician_id": prescribing_clinician_id,
        "exercise_items": exercise_items,
        "patient_acknowledged_at": None,
        "status": "DRAFT",
    })
    db.home_exercise_programs[row["id"]] = row
    return row


def issue_hep(hep: dict[str, Any]) -> dict[str, Any]:
    db = store()
    current = now()
    if hep.get("status") != "DRAFT":
        raise err_invalid_state(f"HEP must be DRAFT to issue; current is {hep.get('status')}")
    poc = db.plan_of_cares.get(hep["plan_of_care_id"])
    if not poc or poc.get("status") != "ACTIVE":
        raise err_invalid_state("PlanOfCare must be ACTIVE")
    if not hep.get("exercise_items"):
        raise err_validation("exercise_items must be non-empty")
    # Supersede prior ISSUED/ACKNOWLEDGED on same Episode
    for other in db.home_exercise_programs.values():
        if other["id"] == hep["id"]:
            continue
        if other["episode_id"] != hep["episode_id"]:
            continue
        if other.get("status") in ("ISSUED", "ACKNOWLEDGED"):
            other["status"] = "SUPERSEDED"
            _bump(other, current)
    hep["status"] = "ISSUED"
    _bump(hep, current)
    return hep


def acknowledge_hep(hep: dict[str, Any], caller_id: str) -> dict[str, Any]:
    db = store()
    current = now()
    if hep.get("status") != "ISSUED":
        raise err_invalid_state(f"HEP must be ISSUED to acknowledge; current is {hep.get('status')}")
    # Caller must be the owning patient (X-User-Role=Patient and X-User-ID == episode.patient_id)
    episode = db.episodes.get(hep["episode_id"])
    if not episode or episode["patient_id"] != caller_id:
        raise err_invalid_state("Only the owning patient may acknowledge this HEP")
    hep["status"] = "ACKNOWLEDGED"
    hep["patient_acknowledged_at"] = current
    _bump(hep, current)
    return hep


# ---------- MIPS ------------------------------------------------------------

def create_mips_measure(
    episode: dict[str, Any],
    measure_code: str,
    visit_id: str,
    numerator_met: bool,
    exception_reason: str,
) -> dict[str, Any]:
    db = store()
    current = now()
    visit = db.visits.get(visit_id)
    if not visit:
        raise err_reference_not_found(f"visit {visit_id} not found")
    if visit["episode_id"] != episode["id"]:
        raise err_reference_not_found("visit does not belong to this episode")
    # Invalid: numerator_met=true with exception != NONE
    if numerator_met is True and exception_reason != "NONE":
        raise err_invalid_mips_exception()
    row = _new_append_only(current)
    row.update({
        "episode_id": episode["id"],
        "measure_code": measure_code,
        "visit_id": visit_id,
        "numerator_met": numerator_met,
        "exception_reason": exception_reason,
        "scored_at": current,
    })
    db.mips_measures[row["id"]] = row
    return row


# ---------- DischargeAssessment ---------------------------------------------

def create_discharge_assessment(
    episode: dict[str, Any],
    discharging_clinician_id: str,
    discharge_outcome: str,
    final_functional_score: int,
) -> dict[str, Any]:
    db = store()
    current = now()
    if episode.get("status") not in ("ACTIVE", "REEVAL_DUE"):
        raise err_invalid_state(f"Episode must be ACTIVE or REEVAL_DUE to start discharge; current is {episode.get('status')}")
    # No SCHEDULED/IN_SESSION visits
    for v in db.visits.values():
        if v["episode_id"] == episode["id"] and v.get("status") in ("SCHEDULED", "IN_SESSION"):
            raise err_invalid_state("Episode has unfinished visits; cannot start discharge")
    # Uniqueness — one discharge per episode
    for d in db.discharge_assessments.values():
        if d["episode_id"] == episode["id"]:
            raise err_invalid_state("DischargeAssessment already exists on this episode")
    get_therapist_ref(discharging_clinician_id)
    if not isinstance(final_functional_score, int) or final_functional_score < 0 or final_functional_score > 100:
        raise err_validation("final_functional_score must be in [0,100]")
    row = _new_common(current)
    row.update({
        "episode_id": episode["id"],
        "discharging_clinician_id": discharging_clinician_id,
        "discharge_outcome": discharge_outcome,
        "final_functional_score": final_functional_score,
        "functional_delta": None,
        "mips_quality_score": None,
        "status": "DRAFT",
    })
    db.discharge_assessments[row["id"]] = row
    # Cascade episode -> DISCHARGE_PENDING
    episode["status"] = "DISCHARGE_PENDING"
    _bump(episode, current)
    return row


def sign_discharge(discharge: dict[str, Any], caller_id: str) -> dict[str, Any]:
    db = store()
    current = now()
    if discharge.get("status") != "DRAFT":
        raise err_invalid_state(f"DischargeAssessment must be DRAFT; current is {discharge.get('status')}")
    therapist = db.therapists.get(caller_id)
    if not therapist or not therapist.get("can_evaluate"):
        raise err_therapist_not_licensed()
    episode = db.episodes.get(discharge["episode_id"])
    if not episode or episode.get("status") != "DISCHARGE_PENDING":
        raise err_invalid_state("Episode must be in DISCHARGE_PENDING")
    # Segregation of duties: discharging_clinician_id != latest evaluation's clinician_id
    latest = _latest_finalized_eval(episode["id"])
    if latest and latest["clinician_id"] == discharge["discharging_clinician_id"]:
        raise err_segregation_of_duties()

    # Compute functional_delta
    baseline = latest["functional_baseline_score"] if latest else 0
    discharge["functional_delta"] = discharge["final_functional_score"] - baseline

    # MIPS score
    rows = [m for m in db.mips_measures.values() if m["episode_id"] == episode["id"]]
    discharge["mips_quality_score"] = mips_quality_score(rows)

    discharge["status"] = "SIGNED"
    _bump(discharge, current)

    # Cascade episode -> DISCHARGED, outcome stamped
    episode["status"] = "DISCHARGED"
    episode["discharge_outcome"] = discharge["discharge_outcome"]
    _bump(episode, current)

    # Expire APPROVED authorizations
    for a in db.authorizations.values():
        if a["episode_id"] == episode["id"] and a.get("status") == "APPROVED":
            a["status"] = "EXPIRED"
            _bump(a, current)

    # Supersede ISSUED/ACKNOWLEDGED HEPs
    for h in db.home_exercise_programs.values():
        if h["episode_id"] == episode["id"] and h.get("status") in ("ISSUED", "ACKNOWLEDGED"):
            h["status"] = "SUPERSEDED"
            _bump(h, current)

    return discharge
