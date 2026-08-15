"""Domain logic: constants, calculations, gates, cascades, getters, serializers."""

from datetime import timedelta
from decimal import Decimal

from db import store
from errors import (
    err,
    ERR_PRODUCTION_NOT_FOUND,
    ERR_SEQUENCE_NOT_FOUND,
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_PERFORMER_NOT_FOUND,
    ERR_CERTIFICATION_NOT_FOUND,
    ERR_REHEARSAL_NOT_FOUND,
    ERR_MEETING_NOT_FOUND,
    ERR_SIGNOFF_NOT_FOUND,
    ERR_EQUIPMENT_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_PERMIT_NOT_FOUND,
    ERR_ADJUSTMENT_NOT_FOUND,
    ERR_INCIDENT_NOT_FOUND,
    ERR_EXECUTION_NOT_FOUND,
    ERR_REVIEW_NOT_FOUND,
    ERR_PRODUCTION_NOT_ACTIVE,
    ERR_PRODUCTION_STOPPED,
    ERR_REHEARSAL_QUOTA_NOT_MET,
    ERR_MEDIC_STANDBY_NOT_CONFIRMED,
    ERR_MEETING_REQUIREMENT_UNSATISFIED,
    ERR_EQUIPMENT_NOT_READY,
    ERR_PERMIT_MISSING_OR_WINDOW_MISMATCH,
    ERR_INSURANCE_NOT_ACKNOWLEDGED,
)
from util import iso_z, dec, rhu

# ---------------------------------------------------------------------------
# Enum sets
# ---------------------------------------------------------------------------

HAZARD_CLASSES = {"FIRE", "HEIGHT", "VEHICLE", "WATER", "PYRO", "AERIAL", "FIGHT"}
RISK_CATEGORIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
UNION_STATUSES = {"SAG_AFTRA", "NON_UNION"}
CERT_LEVELS = {"BASIC", "ADVANCED", "MASTER"}
EQUIPMENT_TYPES = {"RIGGING", "PYRO_DEVICE", "VEHICLE", "HARNESS", "AIRBAG", "CRANE"}
INSPECTION_OUTCOMES = {"PASSED", "CONDITIONAL", "FAILED"}
PERMIT_TYPES = {"PYROTECHNICS", "CRANE_OPERATION", "AERIAL_WORK", "FIRE_EFFECTS", "WATER_WORK"}
ADJUSTMENT_TYPES = {"HAZARD_BUMP", "STUNT_DOUBLE"}
INCIDENT_SEVERITIES = {"NEAR_MISS", "MINOR", "SERIOUS", "CRITICAL"}
REVIEW_OUTCOMES = {"ACCEPTED_AS_SHOT", "RESHOOT_REQUIRED", "SAFETY_DEFICIENCY"}

# ---------------------------------------------------------------------------
# Calculation constants (scaffold 1.3)
# ---------------------------------------------------------------------------

HAZARD_WEIGHT = {"PYRO": 6, "FIRE": 5, "HEIGHT": 4, "VEHICLE": 4, "AERIAL": 4, "WATER": 3, "FIGHT": 2}
MITIGATION_CREDIT = -3
LOCK_THRESHOLD = 26

QUOTA_BY_CATEGORY = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

TAKE_BONUS_CENTS = 50000

CATEGORY_CAP_PCT = {"LOW": "0.15", "MEDIUM": "0.35", "HIGH": "0.60", "CRITICAL": "1.00"}
UNION_FLOOR_CENTS = 15000
SPECIAL_EQUIPMENT_CAP_SURCHARGE_CENTS = 25000
SPECIAL_EQUIPMENT_TYPES = {"PYRO_DEVICE", "CRANE"}

RESERVE_PCT = Decimal("0.10")

INSURANCE_TIER1_MAX = 100000000
INSURANCE_TIER2_MAX = 500000000

MEETING_FACILITY_BUFFER_SECONDS = 1800
MAX_NEGOTIATION_ROUNDS = 6
STOPPAGE_COOLDOWN_SECONDS = 86400

FAVORABLE_SIGNOFF = {"SIGNED", "SIGNED_WITH_CONDITIONS"}

# Required permit mapping: hazard class plus required equipment types.
HAZARD_PERMIT = {
    "PYRO": "PYROTECHNICS",
    "FIRE": "FIRE_EFFECTS",
    "WATER": "WATER_WORK",
    "AERIAL": "AERIAL_WORK",
}
EQUIPMENT_PERMIT = {
    "PYRO_DEVICE": "PYROTECHNICS",
    "CRANE": "CRANE_OPERATION",
}

BASE_SIGNOFF_DEPARTMENTS = ["CAMERA", "ELECTRIC", "GRIP", "STUNTS"]


# ---------------------------------------------------------------------------
# Entity getters with the correct 404 error ids
# ---------------------------------------------------------------------------


def _get(table, rid, error_id, label):
    entity = table.get(rid)
    if entity is None:
        raise err(error_id, f"No {label} with id {rid}", 404)
    return entity


def get_production(pid):
    return _get(store.productions, pid, ERR_PRODUCTION_NOT_FOUND, "Production")


def get_sequence(sid):
    return _get(store.sequences, sid, ERR_SEQUENCE_NOT_FOUND, "StuntSequence")


def get_assessment(aid):
    return _get(store.assessments, aid, ERR_ASSESSMENT_NOT_FOUND, "RiskAssessment")


def get_performer(pid):
    return _get(store.performers, pid, ERR_PERFORMER_NOT_FOUND, "StuntPerformer")


def get_certification(cid):
    return _get(store.certifications, cid, ERR_CERTIFICATION_NOT_FOUND, "Certification")


def get_rehearsal(rid):
    return _get(store.rehearsals, rid, ERR_REHEARSAL_NOT_FOUND, "Rehearsal")


def get_meeting(mid):
    return _get(store.meetings, mid, ERR_MEETING_NOT_FOUND, "SafetyMeeting")


def get_signoff(sid):
    return _get(store.signoffs, sid, ERR_SIGNOFF_NOT_FOUND, "DepartmentSignoff")


def get_equipment(eid):
    return _get(store.equipment, eid, ERR_EQUIPMENT_NOT_FOUND, "EquipmentItem")


def get_inspection(iid):
    return _get(store.inspections, iid, ERR_INSPECTION_NOT_FOUND, "Inspection")


def get_permit(pid):
    return _get(store.permits, pid, ERR_PERMIT_NOT_FOUND, "Permit")


def get_adjustment(aid):
    return _get(store.adjustments, aid, ERR_ADJUSTMENT_NOT_FOUND, "PayAdjustment")


def get_incident(iid):
    return _get(store.incidents, iid, ERR_INCIDENT_NOT_FOUND, "Incident")


def get_execution(eid):
    return _get(store.executions, eid, ERR_EXECUTION_NOT_FOUND, "StuntExecution")


def get_review(rid):
    return _get(store.reviews, rid, ERR_REVIEW_NOT_FOUND, "PostStuntReview")


# ---------------------------------------------------------------------------
# Mutation bookkeeping
# ---------------------------------------------------------------------------


def stamp_new(entity):
    now = store.now()
    entity["created_at"] = now
    entity["_seq"] = store.next_seq()
    return entity


def stamp_mutable(entity):
    entity["updated_at"] = store.now()
    entity["version"] = 1
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD 2.4)."""
    if "version" in entity:
        entity["updated_at"] = store.now()
        entity["version"] += 1


# ---------------------------------------------------------------------------
# Posture gates (validation tier 5)
# ---------------------------------------------------------------------------


def gate_posture_setup_or_active(prod):
    """Design-side operations allowed in SETUP or ACTIVE posture."""
    if prod["posture"] not in ("SETUP", "ACTIVE"):
        raise err(
            ERR_PRODUCTION_NOT_ACTIVE,
            "Operation requires production posture SETUP or ACTIVE",
            409,
        )


def gate_posture_active(prod):
    """Set-operations require ACTIVE; STOPPED gets its own error id."""
    if prod["posture"] == "STOPPED":
        raise err(ERR_PRODUCTION_STOPPED, "Operation blocked while production is STOPPED", 409)
    if prod["posture"] != "ACTIVE":
        raise err(ERR_PRODUCTION_NOT_ACTIVE, "Operation requires production posture ACTIVE", 409)


def gate_posture_incident_report(prod):
    if prod["posture"] not in ("ACTIVE", "STOPPED"):
        raise err(
            ERR_PRODUCTION_NOT_ACTIVE,
            "Incident reporting requires posture ACTIVE or STOPPED",
            409,
        )


# ---------------------------------------------------------------------------
# Risk scoring (calculation: risk_score)
# ---------------------------------------------------------------------------


def screening_score_of(severity, likelihood):
    return severity * likelihood


def board_score_of(assessment, hazard_class):
    score = assessment["severity_rating"] * assessment["likelihood_rating"]
    score += HAZARD_WEIGHT[hazard_class]
    if assessment.get("mitigation_notes"):
        score += MITIGATION_CREDIT
    return score


def screening_band(score):
    if score <= 5:
        return "LOW"
    if score <= 11:
        return "MEDIUM"
    if score <= 19:
        return "HIGH"
    return "CRITICAL"


def latest_approved_assessment(sequence_id):
    approved = [
        a for a in store.assessments.values()
        if a["sequence_id"] == sequence_id and a["status"] == "APPROVED"
    ]
    if not approved:
        return None
    # most recently created (created_at ASC ordering tie-broken by creation order)
    return max(approved, key=lambda a: (a["created_at"], a["_seq"]))


# ---------------------------------------------------------------------------
# Certifications / performer effective status (performer_certification_validity)
# ---------------------------------------------------------------------------


def cert_valid(cert, instant):
    return (not cert["revoked"]) and cert["expires_at"] > instant


def performer_has_valid_cert(performer_id, instant):
    return any(
        c["performer_id"] == performer_id and cert_valid(c, instant)
        for c in store.certifications.values()
    )


def performer_effective_status(performer):
    if performer["status"] == "SUSPENDED":
        return "SUSPENDED"
    if performer_has_valid_cert(performer["id"], store.now()):
        return "QUALIFIED"
    return "REGISTERED"


# ---------------------------------------------------------------------------
# Equipment / inspections (inspection_currency)
# ---------------------------------------------------------------------------


def inspection_current(item):
    last = item["last_passed_inspection_at"]
    if last is None:
        return False
    expires = last + timedelta(hours=item["inspection_interval_hours"])
    return expires > store.now()


def has_special_equipment(seq):
    for eid in seq["required_equipment_ids"]:
        item = store.equipment.get(eid)
        if item is not None and item["equipment_type"] in SPECIAL_EQUIPMENT_TYPES:
            return True
    return False


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------


def required_permit_types(seq):
    types = set()
    hp = HAZARD_PERMIT.get(seq["hazard_class"])
    if hp:
        types.add(hp)
    for eid in seq["required_equipment_ids"]:
        item = store.equipment.get(eid)
        if item is not None:
            ep = EQUIPMENT_PERMIT.get(item["equipment_type"])
            if ep:
                types.add(ep)
    return types


# ---------------------------------------------------------------------------
# Hazard pay (adjustment_payout, hazard_bump_bounds, budget_authority_check,
# production_cost_rollup)
# ---------------------------------------------------------------------------


def adjustment_line_cents(base_amount_cents, pct):
    """Per-line round-half-up of base * (1 + pct), then integer cents."""
    return rhu(Decimal(base_amount_cents) * (Decimal(1) + dec(pct)))


def provisional_estimate_cents(base_amount_cents, requested_pct):
    return (
        base_amount_cents
        + rhu(Decimal(base_amount_cents) * dec(requested_pct))
        + TAKE_BONUS_CENTS * 1
    )


def final_amount_cents_of(base_amount_cents, current_pct):
    return base_amount_cents + rhu(Decimal(base_amount_cents) * dec(current_pct))


def bump_in_bounds(base_amount_cents, pct, performer, seq):
    bump = rhu(Decimal(base_amount_cents) * dec(pct))
    if performer["union_status"] == "SAG_AFTRA":
        floor = max(rhu(Decimal(base_amount_cents) * Decimal("0.10")), UNION_FLOOR_CENTS)
    else:
        floor = 0
    cap = rhu(Decimal(base_amount_cents) * Decimal(CATEGORY_CAP_PCT[seq["risk_category"]]))
    if has_special_equipment(seq):
        cap += SPECIAL_EQUIPMENT_CAP_SURCHARGE_CENTS
    return floor <= bump <= cap


def budget_authority_ok(prod, adj):
    committed_pre = prod["committed_pay_cents"]
    reserve = rhu(Decimal(prod["total_budget_cents"] - committed_pre) * RESERVE_PCT)
    available = prod["total_budget_cents"] - committed_pre - reserve
    new_line = adjustment_line_cents(adj["base_amount_cents"], adj["current_pct"])
    return new_line <= available


def production_rollup(prod):
    committed = 0
    open_exposure = 0
    for adj in store.adjustments.values():
        if adj["production_id"] != prod["id"]:
            continue
        line = adjustment_line_cents(adj["base_amount_cents"], adj["current_pct"])
        if adj["status"] == "AGREED":
            committed += line
        elif adj["status"] in ("PROPOSED", "COUNTERED"):
            open_exposure += line
    premium = prod["endorsement_premium_cents"] or 0
    return {
        "committed_pay_cents": committed,
        "open_negotiation_exposure_cents": open_exposure,
        "endorsement_premium_cents": premium,
        "estimated_total_cost_cents": committed + open_exposure + premium,
    }


# ---------------------------------------------------------------------------
# Rehearsal / meeting overlap (overlap_checks)
# ---------------------------------------------------------------------------


def rehearsal_conflict(production_id, performer_id, new_start, new_end):
    for r in store.rehearsals.values():
        if r["production_id"] != production_id or r["performer_id"] != performer_id:
            continue
        if r["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if new_start < r["scheduled_end"] and r["scheduled_start"] < new_end:
            return True
    return False


def facility_conflict(production_id, facility, new_start, new_end):
    buffer = timedelta(seconds=MEETING_FACILITY_BUFFER_SECONDS)
    for m in store.meetings.values():
        if m["production_id"] != production_id or m["facility"] != facility:
            continue
        if m["status"] not in ("SCHEDULED", "IN_SESSION"):
            continue
        if new_start < m["scheduled_end"] + buffer and m["scheduled_start"] < new_end + buffer:
            return True
    return False


# ---------------------------------------------------------------------------
# Readiness gate (mark-ready / reverify-readiness), fixed evaluation order
# ---------------------------------------------------------------------------


def meeting_signoffs(meeting_id):
    return [s for s in store.signoffs.values() if s["meeting_id"] == meeting_id]


def readiness_gates(seq, prod):
    # 1. rehearsal quota (exact equality passes)
    required = seq["required_rehearsal_count"] or 0
    if seq["completed_rehearsal_count"] < required:
        raise err(
            ERR_REHEARSAL_QUOTA_NOT_MET,
            "Completed rehearsal count is below the required quota",
            422,
        )
    candidates = [
        m for m in store.meetings.values()
        if m["sequence_id"] == seq["id"]
        and m["status"] == "COMPLETED"
        and m["design_revision"] == seq["design_revision"]
    ]
    # 2. medic standby (evaluated before the meeting-satisfaction gate)
    if seq["medic_standby_required"]:
        medic_ok = any(
            s["department"] == "MEDIC" and s["status"] in FAVORABLE_SIGNOFF
            for m in candidates
            for s in meeting_signoffs(m["id"])
        )
        if not medic_ok:
            raise err(
                ERR_MEDIC_STANDBY_NOT_CONFIRMED,
                "Medic standby is required but no qualifying completed meeting has a "
                "favorable MEDIC signoff",
                422,
            )
    # 3. meeting satisfaction: COMPLETED at current revision, all signoffs favorable
    qualifying = [
        m for m in candidates
        if all(s["status"] in FAVORABLE_SIGNOFF for s in meeting_signoffs(m["id"]))
    ]
    if not qualifying:
        raise err(
            ERR_MEETING_REQUIREMENT_UNSATISFIED,
            "No completed safety meeting at the current design revision with all "
            "department signoffs favorable",
            422,
        )
    # 4. equipment readiness
    for eid in seq["required_equipment_ids"]:
        item = store.equipment.get(eid)
        if item is None or item["status"] != "IN_SERVICE" or not inspection_current(item):
            raise err(
                ERR_EQUIPMENT_NOT_READY,
                "A required equipment item is not IN_SERVICE with a current inspection",
                422,
            )
    # 5. permit coverage of the scheduled execution window
    for pt in required_permit_types(seq):
        covered = any(
            p["production_id"] == prod["id"]
            and p["permit_type"] == pt
            and p["status"] == "GRANTED"
            and p["valid_from"] <= seq["scheduled_execution_start"]
            and p["valid_until"] >= seq["scheduled_execution_end"]
            for p in store.permits.values()
        )
        if not covered:
            raise err(
                ERR_PERMIT_MISSING_OR_WINDOW_MISMATCH,
                f"No GRANTED {pt} permit covers the scheduled execution window",
                422,
            )
    # 6. insurance acknowledgement for HIGH / CRITICAL
    if seq["risk_category"] in ("HIGH", "CRITICAL") and prod["insurance_status"] != "ACKNOWLEDGED":
        raise err(
            ERR_INSURANCE_NOT_ACKNOWLEDGED,
            "HIGH/CRITICAL sequences require acknowledged insurance",
            422,
        )


# ---------------------------------------------------------------------------
# Cascades (PRD 2.8)
# ---------------------------------------------------------------------------


def hold_sequence(seq, cancel_rehearsals, adjourn_meetings):
    seq["status"] = "SAFETY_HOLD"
    touch(seq)
    if cancel_rehearsals:
        for r in store.rehearsals.values():
            if r["sequence_id"] == seq["id"] and r["status"] == "SCHEDULED":
                r["status"] = "CANCELLED"
                touch(r)
    if adjourn_meetings:
        for m in store.meetings.values():
            if m["sequence_id"] == seq["id"] and m["status"] in ("SCHEDULED", "IN_SESSION"):
                m["status"] = "ADJOURNED"
                touch(m)


def stop_production(prod, reason):
    """ACTIVE -> STOPPED with the full two-link cascade."""
    prod["posture"] = "STOPPED"
    prod["stopped_at"] = store.now()
    prod["stop_reason"] = reason
    touch(prod)
    for seq in list(store.sequences.values()):
        if seq["production_id"] == prod["id"] and seq["status"] == "READY":
            hold_sequence(seq, cancel_rehearsals=True, adjourn_meetings=True)


def cascade_equipment_unavailable(item):
    """Quarantine/retire: READY sequences requiring the item -> SAFETY_HOLD,
    with rehearsal cancellation only (no meeting adjournment)."""
    for seq in list(store.sequences.values()):
        if seq["status"] == "READY" and item["id"] in seq["required_equipment_ids"]:
            hold_sequence(seq, cancel_rehearsals=True, adjourn_meetings=False)


def cascade_permit_revoked(permit):
    """READY sequences of this production requiring the permit type -> SAFETY_HOLD
    with both rehearsal cancellation and meeting adjournment."""
    for seq in list(store.sequences.values()):
        if seq["production_id"] != permit["production_id"]:
            continue
        if seq["status"] != "READY":
            continue
        if permit["permit_type"] in required_permit_types(seq):
            hold_sequence(seq, cancel_rehearsals=True, adjourn_meetings=True)


# ---------------------------------------------------------------------------
# Serializers (explicit whitelists; internal keys never leak)
# ---------------------------------------------------------------------------


def _dt(value):
    return iso_z(value) if value is not None else None


def serialize_production(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "total_budget_cents": p["total_budget_cents"],
        "posture": p["posture"],
        "insurance_status": p["insurance_status"],
        "declared_exposure_cents": p["declared_exposure_cents"],
        "endorsement_premium_cents": p["endorsement_premium_cents"],
        "committed_pay_cents": p["committed_pay_cents"],
        "stopped_at": _dt(p["stopped_at"]),
        "stop_reason": p["stop_reason"],
        "created_at": _dt(p["created_at"]),
        "updated_at": _dt(p["updated_at"]),
        "version": p["version"],
    }


def serialize_sequence(s):
    return {
        "id": s["id"],
        "production_id": s["production_id"],
        "name": s["name"],
        "hazard_class": s["hazard_class"],
        "risk_category": s["risk_category"],
        "status": s["status"],
        "coordinator_user_id": s["coordinator_user_id"],
        "scheduled_execution_start": _dt(s["scheduled_execution_start"]),
        "scheduled_execution_end": _dt(s["scheduled_execution_end"]),
        "required_equipment_ids": list(s["required_equipment_ids"]),
        "required_rehearsal_count": s["required_rehearsal_count"],
        "completed_rehearsal_count": s["completed_rehearsal_count"],
        "completed_rehearsal_minutes": s["completed_rehearsal_minutes"],
        "current_assessment_id": s["current_assessment_id"],
        "board_score": s["board_score"],
        "design_revision": s["design_revision"],
        "medic_standby_required": s["medic_standby_required"],
        "created_at": _dt(s["created_at"]),
        "updated_at": _dt(s["updated_at"]),
        "version": s["version"],
    }


def serialize_assessment(a):
    return {
        "id": a["id"],
        "production_id": a["production_id"],
        "sequence_id": a["sequence_id"],
        "assessor_user_id": a["assessor_user_id"],
        "severity_rating": a["severity_rating"],
        "likelihood_rating": a["likelihood_rating"],
        "mitigation_notes": a["mitigation_notes"],
        "screening_score": a["screening_score"],
        "status": a["status"],
        "supersedes_assessment_id": a["supersedes_assessment_id"],
        "rejection_reason": a["rejection_reason"],
        "created_at": _dt(a["created_at"]),
        "updated_at": _dt(a["updated_at"]),
        "version": a["version"],
    }


def serialize_performer(p):
    return {
        "id": p["id"],
        "production_id": p["production_id"],
        "first_name": p["first_name"],
        "last_name": p["last_name"],
        "base_day_rate_cents": p["base_day_rate_cents"],
        "union_status": p["union_status"],
        "status": performer_effective_status(p),
        "completed_rehearsal_minutes": p["completed_rehearsal_minutes"],
        "created_at": _dt(p["created_at"]),
        "updated_at": _dt(p["updated_at"]),
        "version": p["version"],
    }


def serialize_certification(c):
    return {
        "id": c["id"],
        "performer_id": c["performer_id"],
        "discipline": c["discipline"],
        "level": c["level"],
        "issued_at": _dt(c["issued_at"]),
        "expires_at": _dt(c["expires_at"]),
        "revoked": c["revoked"],
        "created_at": _dt(c["created_at"]),
    }


def serialize_rehearsal(r):
    return {
        "id": r["id"],
        "production_id": r["production_id"],
        "sequence_id": r["sequence_id"],
        "performer_id": r["performer_id"],
        "facility": r["facility"],
        "scheduled_start": _dt(r["scheduled_start"]),
        "scheduled_end": _dt(r["scheduled_end"]),
        "duration_minutes": r["duration_minutes"],
        "status": r["status"],
        "void_reason": r["void_reason"],
        "created_at": _dt(r["created_at"]),
        "updated_at": _dt(r["updated_at"]),
        "version": r["version"],
    }


def serialize_meeting(m):
    return {
        "id": m["id"],
        "production_id": m["production_id"],
        "sequence_id": m["sequence_id"],
        "facility": m["facility"],
        "scheduled_start": _dt(m["scheduled_start"]),
        "scheduled_end": _dt(m["scheduled_end"]),
        "status": m["status"],
        "design_revision": m["design_revision"],
        "chair_user_id": m["chair_user_id"],
        "created_at": _dt(m["created_at"]),
        "updated_at": _dt(m["updated_at"]),
        "version": m["version"],
    }


def serialize_signoff(s):
    return {
        "id": s["id"],
        "meeting_id": s["meeting_id"],
        "department": s["department"],
        "status": s["status"],
        "signer_user_id": s["signer_user_id"],
        "conditions": s["conditions"],
        "refusal_reason": s["refusal_reason"],
        "decided_at": _dt(s["decided_at"]),
        "created_at": _dt(s["created_at"]),
        "updated_at": _dt(s["updated_at"]),
        "version": s["version"],
    }


def serialize_equipment(e):
    return {
        "id": e["id"],
        "production_id": e["production_id"],
        "name": e["name"],
        "equipment_type": e["equipment_type"],
        "serial_number": e["serial_number"],
        "inspection_interval_hours": e["inspection_interval_hours"],
        "status": e["status"],
        "registered_by_user_id": e["registered_by_user_id"],
        "last_passed_inspection_at": _dt(e["last_passed_inspection_at"]),
        "inspection_current": inspection_current(e),
        "created_at": _dt(e["created_at"]),
        "updated_at": _dt(e["updated_at"]),
        "version": e["version"],
    }


def serialize_inspection(i):
    return {
        "id": i["id"],
        "equipment_id": i["equipment_id"],
        "inspector_user_id": i["inspector_user_id"],
        "outcome": i["outcome"],
        "notes": i["notes"],
        "inspected_at": _dt(i["inspected_at"]),
        "created_at": _dt(i["created_at"]),
    }


def serialize_permit(p):
    return {
        "id": p["id"],
        "production_id": p["production_id"],
        "permit_type": p["permit_type"],
        "jurisdiction": p["jurisdiction"],
        "valid_from": _dt(p["valid_from"]),
        "valid_until": _dt(p["valid_until"]),
        "status": p["status"],
        "created_at": _dt(p["created_at"]),
        "updated_at": _dt(p["updated_at"]),
        "version": p["version"],
    }


def serialize_adjustment(a):
    return {
        "id": a["id"],
        "production_id": a["production_id"],
        "sequence_id": a["sequence_id"],
        "performer_id": a["performer_id"],
        "adjustment_type": a["adjustment_type"],
        "base_amount_cents": a["base_amount_cents"],
        "requested_pct": a["requested_pct"],
        "current_pct": a["current_pct"],
        "proposer_by": a["proposer_by"],
        "last_offer_by": a["last_offer_by"],
        "round_count": a["round_count"],
        "status": a["status"],
        "provisional_estimate_cents": a["provisional_estimate_cents"],
        "final_amount_cents": a["final_amount_cents"],
        "payable_amount_cents": a["payable_amount_cents"],
        "created_at": _dt(a["created_at"]),
        "updated_at": _dt(a["updated_at"]),
        "version": a["version"],
    }


def serialize_incident(i):
    return {
        "id": i["id"],
        "production_id": i["production_id"],
        "sequence_id": i["sequence_id"],
        "severity": i["severity"],
        "occurred_at": _dt(i["occurred_at"]),
        "description": i["description"],
        "reporter_user_id": i["reporter_user_id"],
        "status": i["status"],
        "corrective_action": i["corrective_action"],
        "created_at": _dt(i["created_at"]),
        "updated_at": _dt(i["updated_at"]),
        "version": i["version"],
    }


def serialize_execution(e):
    return {
        "id": e["id"],
        "production_id": e["production_id"],
        "sequence_id": e["sequence_id"],
        "take_number": e["take_number"],
        "status": e["status"],
        "executed_at": _dt(e["executed_at"]),
        "abort_reason": e["abort_reason"],
        "safety_related": e["safety_related"],
        "created_at": _dt(e["created_at"]),
        "updated_at": _dt(e["updated_at"]),
        "version": e["version"],
    }


def serialize_review(r):
    return {
        "id": r["id"],
        "production_id": r["production_id"],
        "sequence_id": r["sequence_id"],
        "reviewer_user_id": r["reviewer_user_id"],
        "status": r["status"],
        "outcome": r["outcome"],
        "findings": r["findings"],
        "created_at": _dt(r["created_at"]),
        "updated_at": _dt(r["updated_at"]),
        "version": r["version"],
    }


def default_sort_key(entity):
    return (entity["created_at"], entity["_seq"])
