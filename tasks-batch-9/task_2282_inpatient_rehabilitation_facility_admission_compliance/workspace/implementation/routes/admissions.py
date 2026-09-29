"""Admission lifecycle: opening, the admission gate, denial, discharge,
interrupted-stay consolidation and rescission (PRD §3.3, §3.4, §3.8)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import store
from errors import ApiError
from queryargs import enum_arg, matches, str_arg
from response import envelope, paged, pagination_params
from services import (CMG_TIER_BY_IGC, CMG_TIER_DEFAULT, DISCHARGE_DESTINATIONS,
                      INTERRUPTION_MAX_GAP_DAYS, SCREENING_WINDOW_HOURS, by_seq,
                      chain_fully_discharged, chain_head, invalidate_reviews_for,
                      price_chain, recompute_admission_derived, recompute_facility,
                      refresh_week_counters, require, stamp_new, touch, week_verdict,
                      weeks_of)
from util import Body, date_of, dt_of, iso, num2, round_half_up, serialize

bp = Blueprint("admissions", __name__)

STAY_STATUSES = ("PENDING", "ADMITTED", "DISCHARGED", "ADMISSION_DENIED")
PAYMENT_STATUSES = ("NOT_PRICED", "PRICED", "CONSOLIDATED", "REOPENED")
COMPLIANCE_CLASSES = ("PENDING_EVALUATION", "QUALIFYING", "NON_QUALIFYING", "EXCLUDED")


# --------------------------------------------------------------------- create ---
@bp.post("/admissions")
def create_admission():
    authenticate(("NurseCaseManager",))
    body = Body(request.get_json(silent=True))

    patient_id = body.id_field("patient_id")
    screening_id = body.id_field("screening_id")
    predecessor_id = body.id_field("predecessor_admission_id", required=False)

    # ladder rank 10 — body identifier existence
    patient = require(store.patients, patient_id)
    screening = require(store.screenings, screening_id)
    if predecessor_id is not None:
        require(store.admissions, predecessor_id)

    # ladder rank 11 — screening/patient coherence
    if screening["patient_id"] != patient_id:
        raise ApiError("ERR_SCREENING_PATIENT_MISMATCH")

    # ladder rank 22 — concurred screening
    if screening["status"] != "PHYSICIAN_CONCURRED":
        raise ApiError("ERR_SCREENING_NOT_CONCURRED")

    admission = stamp_new({
        "facility_id": patient["facility_id"],
        "patient_id": patient_id,
        "screening_id": screening_id,
        "predecessor_admission_id": predecessor_id,
        "payment_consolidated_into_admission_id": None,
        "stay_status": "PENDING",
        "payment_status": "NOT_PRICED",
        "documentation_status": "INCOMPLETE",
        "admitted_at": None,
        "discharged_at": None,
        "discharge_destination": None,
        "discharge_planned": None,
        "denial_reason": None,
        "interrupted_stay_flag": False,
        "interruption_gap_days": None,
        "cmg_tier": None,
        "effective_los_days": None,
        "total_payment_cents": 0,
        "qrp_penalty_pct_snapshot": 0.00,
        "screening_window_hours": None,
        "screening_compliant": False,
        "poc_signed_within_deadline": False,
        "therapy_weeks_satisfied": False,
        "conference_compliant": False,
        "total_credited_minutes": 0,
        "compliance_class": "PENDING_EVALUATION",
    })
    store.admissions[admission["id"]] = admission
    return envelope(serialize(admission), 201)


# ----------------------------------------------------------------------- reads ---
@bp.get("/admissions/<admission_id>")
def get_admission(admission_id):
    authenticate(ALL_ROLES)
    admission = require(store.admissions, admission_id)
    return envelope(serialize(admission), 200)


@bp.get("/admissions")
def list_admissions():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    filters = {
        "facility_id": str_arg("facility_id"),
        "patient_id": str_arg("patient_id"),
        "screening_id": str_arg("screening_id"),
        "predecessor_admission_id": str_arg("predecessor_admission_id"),
        "payment_consolidated_into_admission_id": str_arg("payment_consolidated_into_admission_id"),
        "stay_status": enum_arg("stay_status", STAY_STATUSES),
        "payment_status": enum_arg("payment_status", PAYMENT_STATUSES),
        "compliance_class": enum_arg("compliance_class", COMPLIANCE_CLASSES),
    }
    items = [a for a in by_seq(list(store.admissions.values())) if matches(a, filters)]
    page, pagination = paged(items, limit, offset)
    return envelope([serialize(a) for a in page], 200, pagination)


# ---------------------------------------------------------------------- admit ---
@bp.post("/admissions/<admission_id>/admit")
def admit(admission_id):
    authenticate(("NurseCaseManager",))
    body = Body(request.get_json(silent=True))
    admitted_at = body.dt_field("admitted_at")

    # ladder rank 5 — admitted_at may not be later than the logical clock
    if admitted_at > store.clock:
        raise ApiError("ERR_INVALID_REQUEST", "admitted_at may not be later than the logical clock")

    admission = require(store.admissions, admission_id)
    screening = store.screenings.get(admission["screening_id"])
    facility = store.facilities.get(admission["facility_id"])
    if screening is None or facility is None:
        raise ApiError("ERR_NOT_FOUND")

    conducted_at = dt_of(screening["conducted_at"])
    # ladder rank 5 (continued) — admitted_at may not precede the screening
    if admitted_at < conducted_at:
        raise ApiError("ERR_INVALID_REQUEST", "admitted_at may not precede the screening's conducted_at")

    predecessor = None
    if admission["predecessor_admission_id"]:
        predecessor = store.admissions.get(admission["predecessor_admission_id"])
        if predecessor is None:
            raise ApiError("ERR_NOT_FOUND")
        # ladder rank 11 — predecessor patient coherence
        if predecessor["patient_id"] != admission["patient_id"]:
            raise ApiError("ERR_SCREENING_PATIENT_MISMATCH")

    # ladder rank 16 — declared transition PENDING -> ADMITTED
    if admission["stay_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")

    # ladder rank 21 — admission gate
    if facility["posture"] not in ("OPEN", "THRESHOLD_WATCH"):
        raise ApiError("ERR_FACILITY_ADMISSION_FROZEN")

    # ladder rank 22 — concurred screening with reviewed_at at or before admitted_at
    reviewed_at = dt_of(screening["reviewed_at"])
    if screening["status"] != "PHYSICIAN_CONCURRED" or reviewed_at is None or reviewed_at > admitted_at:
        raise ApiError("ERR_SCREENING_NOT_CONCURRED")

    # ladder rank 23 — 48-hour screening window
    if (admitted_at - conducted_at) > timedelta(hours=SCREENING_WINDOW_HOURS):
        raise ApiError("ERR_SCREENING_WINDOW_EXPIRED")

    gap_days = None
    if predecessor is not None:
        # ladder rank 43 — predecessor discharged, gap within 0..3 days
        if predecessor["stay_status"] != "DISCHARGED" or predecessor["discharged_at"] is None:
            raise ApiError("ERR_INTERRUPTION_WINDOW_EXCEEDED")
        gap_days = (admitted_at.date() - date_of(predecessor["discharged_at"])).days
        if gap_days < 0 or gap_days > INTERRUPTION_MAX_GAP_DAYS:
            raise ApiError("ERR_INTERRUPTION_WINDOW_EXCEEDED")

        # ladder rank 44 — the predecessor may not already be continued
        for other in store.admissions.values():
            if other["id"] == admission["id"]:
                continue
            if other["predecessor_admission_id"] == predecessor["id"]:
                raise ApiError("ERR_PREDECESSOR_ALREADY_CONTINUED")
    else:
        # ladder rank 45 — linkage required when a recent discharge exists
        for other in store.admissions.values():
            if other["id"] == admission["id"]:
                continue
            if other["patient_id"] != admission["patient_id"]:
                continue
            if other["stay_status"] != "DISCHARGED" or other["discharged_at"] is None:
                continue
            recent_gap = (admitted_at.date() - date_of(other["discharged_at"])).days
            if 0 <= recent_gap <= INTERRUPTION_MAX_GAP_DAYS:
                raise ApiError("ERR_INTERRUPTED_STAY_LINK_REQUIRED")

    # ---- side effects ----
    patient = store.patients.get(admission["patient_id"])
    admission["stay_status"] = "ADMITTED"
    admission["admitted_at"] = iso(admitted_at)
    # exact rational seconds -> hours, then ROUND_HALF_UP to two decimals (PRD §2.6)
    elapsed = admitted_at - conducted_at
    elapsed_seconds = Decimal(elapsed.days) * 86400 + Decimal(elapsed.seconds) \
        + (Decimal(elapsed.microseconds) / Decimal(1000000))
    window_hours = round_half_up(elapsed_seconds / Decimal(3600), 2)
    admission["screening_window_hours"] = float(window_hours)
    admission["screening_compliant"] = bool(
        window_hours <= Decimal(SCREENING_WINDOW_HOURS)
        and screening["status"] == "PHYSICIAN_CONCURRED"
        and reviewed_at <= admitted_at
    )
    admission["qrp_penalty_pct_snapshot"] = num2(facility["active_qrp_penalty_pct"])
    admission["cmg_tier"] = CMG_TIER_BY_IGC.get(
        patient["impairment_group_code"] if patient else None, CMG_TIER_DEFAULT)

    facility_dirty = False
    if predecessor is not None:
        head = chain_head(predecessor)
        admission["interrupted_stay_flag"] = True
        admission["interruption_gap_days"] = gap_days
        admission["payment_consolidated_into_admission_id"] = head["id"]
        admission["payment_status"] = "CONSOLIDATED"
        admission["total_payment_cents"] = 0

        # cascade hop 2 — the chain head is reopened for reconsolidation
        if head["payment_status"] == "PRICED":
            head["payment_status"] = "REOPENED"
            head["total_payment_cents"] = 0
            head["effective_los_days"] = None
            touch(head)
            # cascade hop 4 — COMPUTED reviews covering the head go STALE
            invalidate_reviews_for(head, "INTERRUPTED_STAY_RECONSOLIDATION")
            facility_dirty = True

    recompute_admission_derived(admission)
    touch(admission)

    # cascade hop 3 — settled payment and facility version
    if facility_dirty:
        recompute_facility(facility, force_touch=True, recompute_settled=True)

    return envelope(serialize(admission), 200)


# ----------------------------------------------------------------------- deny ---
@bp.post("/admissions/<admission_id>/deny")
def deny(admission_id):
    authenticate(("RehabPhysician",))
    body = Body(request.get_json(silent=True))
    denial_reason = body.str_field("denial_reason", min_len=1)

    admission = require(store.admissions, admission_id)

    # ladder rank 16 — declared transition PENDING -> ADMISSION_DENIED
    if admission["stay_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")

    admission["stay_status"] = "ADMISSION_DENIED"
    admission["denial_reason"] = denial_reason
    recompute_admission_derived(admission)
    admission["compliance_class"] = "EXCLUDED"
    touch(admission)

    facility = store.facilities.get(admission["facility_id"])
    if facility is not None:
        recompute_facility(facility)

    return envelope(serialize(admission), 200)


# ------------------------------------------------------------------ discharge ---
@bp.post("/admissions/<admission_id>/discharge")
def discharge(admission_id):
    authenticate(("NurseCaseManager",))
    body = Body(request.get_json(silent=True))

    discharged_at = body.dt_field("discharged_at")
    destination = body.enum_field("discharge_destination", DISCHARGE_DESTINATIONS)
    planned = body.bool_field("discharge_planned")

    # ladder rank 5 — discharged_at may not be later than the logical clock
    if discharged_at > store.clock:
        raise ApiError("ERR_INVALID_REQUEST", "discharged_at may not be later than the logical clock")

    admission = require(store.admissions, admission_id)

    admitted_at = dt_of(admission["admitted_at"])
    if admitted_at is not None and discharged_at < admitted_at:
        raise ApiError("ERR_INVALID_REQUEST", "discharged_at may not precede admitted_at")

    # ladder rank 16 — declared transition ADMITTED -> DISCHARGED
    if admission["stay_status"] != "ADMITTED":
        raise ApiError("ERR_INVALID_STATE")

    admission["stay_status"] = "DISCHARGED"
    admission["discharged_at"] = iso(discharged_at)
    admission["discharge_destination"] = destination
    admission["discharge_planned"] = planned

    # cascade hop 1 — every still-OPEN therapy week is evaluated
    for week in weeks_of(admission["id"]):
        if week["status"] != "OPEN":
            continue
        refresh_week_counters(week)
        week["status"] = week_verdict(week)
        touch(week)

    # cascade hop 2 — the stay's verdict is finalised
    recompute_admission_derived(admission)

    # pricing (PRD §3.8)
    _price_after_discharge(admission)
    touch(admission)

    # cascade hops 3 and 4 — facility cohort, posture and screening propagation
    facility = store.facilities.get(admission["facility_id"])
    if facility is not None:
        recompute_facility(facility, force_touch=True, recompute_settled=True)

    return envelope(serialize(admission), 200)


def _price_after_discharge(admission):
    if admission["payment_status"] == "CONSOLIDATED":
        head = chain_head(admission)
        if head["id"] != admission["id"] and chain_fully_discharged(head):
            if head["payment_status"] in ("REOPENED", "NOT_PRICED"):
                los_days, total = price_chain(head)
                head["effective_los_days"] = los_days
                head["total_payment_cents"] = total
                head["payment_status"] = "PRICED"
                touch(head)
        return
    if admission["payment_status"] == "NOT_PRICED":
        head = chain_head(admission)
        if head["id"] == admission["id"]:
            los_days, total = price_chain(admission)
            admission["effective_los_days"] = los_days
            admission["total_payment_cents"] = total
            admission["payment_status"] = "PRICED"


# --------------------------------------------------------- rescind-interruption ---
@bp.post("/admissions/<admission_id>/rescind-interruption")
def rescind_interruption(admission_id):
    authenticate(("ComplianceOfficer",))
    body = Body(request.get_json(silent=True))
    body.str_field("rescind_reason", min_len=1)

    admission = require(store.admissions, admission_id)

    # ladder rank 20 — interruption must be present
    if not admission["interrupted_stay_flag"]:
        raise ApiError("ERR_NOT_INTERRUPTED_STAY")

    # a discharged continuation may not be unlinked (PRD §3.4)
    if admission["stay_status"] != "ADMITTED":
        raise ApiError("ERR_INVALID_STATE")

    head = chain_head(admission)
    if head["id"] == admission["id"]:
        head = None

    admission["interrupted_stay_flag"] = False
    admission["interruption_gap_days"] = None
    admission["payment_consolidated_into_admission_id"] = None
    admission["predecessor_admission_id"] = None
    admission["payment_status"] = "NOT_PRICED"
    admission["total_payment_cents"] = 0
    admission["effective_los_days"] = None
    touch(admission)

    if head is not None and head["payment_status"] == "REOPENED":
        los_days, total = price_chain(head)
        head["effective_los_days"] = los_days
        head["total_payment_cents"] = total
        head["payment_status"] = "PRICED"
        touch(head)

    facility = store.facilities.get(admission["facility_id"])
    if facility is not None:
        recompute_facility(facility, force_touch=True, recompute_settled=True)

    return envelope(serialize(admission), 200)
