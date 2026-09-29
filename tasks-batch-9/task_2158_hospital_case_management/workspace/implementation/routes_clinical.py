"""Risk screenings and barriers (PRD 3.2, 3.3)."""

from flask import Blueprint

import calc
import cascade
import derive
from envelope import created, filter_eq, list_response, ok
from errors import ApiError
from store import base_row, db, touch
from validate import (BARRIER_CODES, BARRIER_STATUSES, DELAY_REASON_CODES,
                      SCREENING_TYPES, SEVERITIES, actor, body, opt_str,
                      req_enum, req_int, require_roles, role)

bp = Blueprint("clinical", __name__)

BARRIER_TRANSITIONS = {
    "OPEN": {"MITIGATING", "RESOLVED", "WAIVED"},
    "MITIGATING": {"RESOLVED", "WAIVED"},
    "RESOLVED": {"OPEN"},
    "WAIVED": set(),
}


# --------------------------------------------------------------------------
# screenings
# --------------------------------------------------------------------------
@bp.post("/episodes/<eid>/screenings")
def create_screening(eid):
    require_roles("CaseManager")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    b = body()
    screening_type = req_enum(b, "screening_type", SCREENING_TYPES)
    functional = req_int(b, "functional_score", minimum=0, maximum=10)
    cognitive = req_int(b, "cognitive_score", minimum=0, maximum=10)
    social = req_int(b, "social_support_score", minimum=0, maximum=10)
    medication_count = req_int(b, "medication_count", minimum=0)
    patient = derive.get_patient(episode["patient_id"])
    row = base_row()
    row.update({
        "episode_id": episode["id"],
        "screening_type": screening_type,
        "functional_score": functional,
        "cognitive_score": cognitive,
        "social_support_score": social,
        "medication_count": medication_count,
        "prior_admissions_snapshot": patient["prior_admissions_180d"],
        "lives_alone_snapshot": patient["lives_alone"],
        "has_pcp_snapshot": patient["has_pcp"],
        "variant_applied": None,
        "composite_risk_score": 0,
        "risk_band": "LOW",
        "status": "DRAFT",
        "submitted_at": None,
        "submitted_by_user_id": None,
    })
    db.screenings[row["id"]] = row
    return created(derive.ser_screening(row))


@bp.post("/screenings/<sid>/submit")
def submit_screening(sid):
    require_roles("CaseManager")
    screening = derive.get_screening(sid)
    episode = derive.get_episode(screening["episode_id"])
    derive.sweep_episode(episode)

    if screening["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SCREENING_STATE", "screening is not DRAFT")
    if episode["case_status"] not in ("ADMITTED", "SCREENED", "PLANNING"):
        raise ApiError("ERR_INVALID_EPISODE_STATE",
                       "the episode does not admit a screening submission")
    if screening["screening_type"] == "ADMISSION":
        for other in derive.screenings_of(episode["id"]):
            if (other["id"] != screening["id"] and other["status"] == "SUBMITTED"
                    and other["screening_type"] == "ADMISSION"):
                raise ApiError("ERR_INVALID_SCREENING_STATE",
                               "an admission screening has already been submitted")

    variant = ("ADMISSION_VARIANT" if screening["screening_type"] == "ADMISSION"
               else "PREDISCHARGE_VARIANT")
    score, band = calc.composite_risk(
        screening, variant,
        derive.barriers_ever_opened_count(episode),
        derive.has_institutional_placement(episode),
    )
    for other in derive.screenings_of(episode["id"]):
        if other["id"] != screening["id"] and other["status"] == "SUBMITTED":
            other["status"] = "SUPERSEDED"
            touch(other)
    screening["variant_applied"] = variant
    screening["composite_risk_score"] = score
    screening["risk_band"] = band
    screening["status"] = "SUBMITTED"
    screening["submitted_at"] = db.now_iso()
    screening["submitted_by_user_id"] = actor()
    touch(screening)

    if episode["case_status"] == "ADMITTED" and screening["screening_type"] == "ADMISSION":
        episode["case_status"] = "SCREENED"
        touch(episode)

    # Barrier derivation, evaluated in rule order (PRD 3.3).
    if band in ("HIGH", "VERY_HIGH") and not screening["has_pcp_snapshot"]:
        if not derive.has_open_barrier(episode["id"], "PHYSICIAN_ORDER"):
            derive.make_barrier(episode, "PHYSICIAN_ORDER", "MEDIUM",
                                "AWAITING_PHYSICIAN", "SCREENING_AUTO", "system")
    if screening["lives_alone_snapshot"] and screening["functional_score"] <= 5:
        if not derive.has_open_barrier(episode["id"], "HOUSING"):
            derive.make_barrier(episode, "HOUSING", "HIGH", "AWAITING_FAMILY",
                                "SCREENING_AUTO", "system")
    return ok(derive.ser_screening(screening))


@bp.get("/episodes/<eid>/screenings")
def list_screenings(eid):
    require_roles("CaseManager", "UtilizationReviewNurse", "PlatformAdmin")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    return list_response(derive.screenings_of(episode["id"]), derive.ser_screening)


# --------------------------------------------------------------------------
# barriers
# --------------------------------------------------------------------------
@bp.post("/episodes/<eid>/barriers")
def create_barrier(eid):
    require_roles("CaseManager", "UtilizationReviewNurse")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    b = body()
    barrier_code = req_enum(b, "barrier_code", BARRIER_CODES)
    severity = req_enum(b, "severity", SEVERITIES)
    delay_reason_code = req_enum(b, "delay_reason_code", DELAY_REASON_CODES)
    row = derive.make_barrier(episode, barrier_code, severity, delay_reason_code,
                              "MANUAL", actor())
    return created(derive.ser_barrier(row))


@bp.post("/barriers/<bid>/status")
def barrier_status(bid):
    require_roles("CaseManager", "UtilizationReviewNurse")
    barrier = derive.get_barrier(bid)
    episode = derive.get_episode(barrier["episode_id"])
    derive.sweep_episode(episode)
    b = body()
    to_status = req_enum(b, "to_status", BARRIER_STATUSES)
    opt_str(b, "note", None)

    if to_status not in BARRIER_TRANSITIONS.get(barrier["status"], set()):
        raise ApiError("ERR_INVALID_BARRIER_STATE",
                       "%s is not reachable from %s" % (to_status, barrier["status"]))
    if to_status == "WAIVED":
        if role() != "UtilizationReviewNurse":
            raise ApiError("ERR_WAIVER_ROLE_REQUIRED",
                           "only a UtilizationReviewNurse may waive a barrier")
        if actor() == barrier.get("opened_by_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "a barrier may not be waived by the operator that opened it")

    if to_status == "MITIGATING":
        barrier["status"] = "MITIGATING"
        touch(barrier)
    elif to_status in ("RESOLVED", "WAIVED"):
        derive.close_barrier(barrier, to_status)
    elif to_status == "OPEN":
        cascade.reopen_barrier(barrier)
        if episode["case_status"] == "READY_FOR_DISCHARGE":
            cascade.revert_to_planning(episode, reason_code=None)
    return ok(derive.ser_barrier(barrier))


@bp.get("/episodes/<eid>/barriers")
def list_barriers(eid):
    require_roles("CaseManager", "UtilizationReviewNurse", "PlatformAdmin",
                  "DischargeCoordinator")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    rows = filter_eq(derive.barriers_of(episode["id"]), "status", "status")
    return list_response(rows, derive.ser_barrier)
