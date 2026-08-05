"""Plan-review routes — PRD §3.1."""

from flask import Blueprint

import config
import domain
import serialize
import store
import validate as V
from auth import authenticate, require_owns_establishment
from envelope import array_response, force, send, watch
from errors import ApiError

bp = Blueprint("plan_reviews", __name__)


@bp.post("/body-art/plan-reviews")
def create_plan_review():
    caller = authenticate(["EstablishmentOperator"])
    data = V.body()
    establishment_id = V.req_id(data, "establishment_id")
    floor_plan_reference = V.req_string(data, "floor_plan_reference", 1, 80)
    sterilization_area_sqft = V.req_number(data, "sterilization_area_sqft", gt=0)
    procedure_station_count = V.req_int(data, "procedure_station_count", minimum=1)
    has_handwash_sink = V.req_bool(data, "has_handwash_sink")
    est = V.get_establishment(establishment_id)
    require_owns_establishment(caller, establishment_id)

    for existing in domain.rows_for(store.plan_reviews, establishment_id=est["id"]):
        if existing["status"] in ("SUBMITTED", "CORRECTIONS_REQUIRED"):
            raise ApiError("ERR_DUPLICATE_OPEN_PLAN_REVIEW")

    rec = domain.new_record(
        {
            "establishment_id": est["id"],
            "status": "SUBMITTED",
            "floor_plan_reference": floor_plan_reference,
            "sterilization_area_sqft": sterilization_area_sqft,
            "procedure_station_count": procedure_station_count,
            "has_handwash_sink": has_handwash_sink,
            "cycle_count": 1,
            "decision_notes": None,
            "decided_by_user_id": None,
        }
    )
    store.plan_reviews[rec["id"]] = rec
    return send(lambda: serialize.plan_review(rec), 201)


@bp.get("/body-art/plan-reviews/<plan_review_id>")
def read_plan_review(plan_review_id):
    authenticate(["HealthOfficer", "PlanReviewer", "EstablishmentOperator"])
    rec = V.get_plan_review(plan_review_id)
    return send(lambda: serialize.plan_review(rec), 200)


@bp.get("/body-art/plan-reviews")
def list_plan_reviews():
    authenticate(["HealthOfficer", "PlanReviewer", "EstablishmentOperator"])
    limit, offset = V.pagination()
    establishment_id = V.filter_string("establishment_id")
    status = V.filter_enum("status", config.PLAN_REVIEW_STATUSES)

    rows = store.sorted_rows(store.plan_reviews)
    if establishment_id is not None:
        rows = [r for r in rows if r["establishment_id"] == establishment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return array_response(
        [serialize.plan_review(r) for r in page], limit, offset, total
    )


@bp.post("/body-art/plan-reviews/<plan_review_id>/decision")
def decide_plan_review(plan_review_id):
    caller = authenticate(["PlanReviewer"])
    rec = V.get_plan_review(plan_review_id)
    data = V.body()
    decision = V.req_enum(data, "decision", config.PLAN_REVIEW_DECISIONS)
    decision_notes = V.opt_string(data, "decision_notes", 0, None)

    if decision == "APPROVE":
        if rec["status"] != "SUBMITTED":
            raise ApiError("ERR_PLAN_REVIEW_STATE_INVALID")
        if not rec["has_handwash_sink"] or (
            rec["sterilization_area_sqft"] < config.MIN_STERILIZATION_AREA_SQFT
        ):
            raise ApiError("ERR_PLAN_REVIEW_REQUIREMENTS_NOT_MET")
        watch(rec)
        rec["status"] = "APPROVED"
    elif decision == "REQUEST_CORRECTIONS":
        if rec["status"] != "SUBMITTED":
            raise ApiError("ERR_PLAN_REVIEW_STATE_INVALID")
        watch(rec)
        rec["status"] = "CORRECTIONS_REQUIRED"
    else:  # DENY
        if rec["status"] not in ("SUBMITTED", "CORRECTIONS_REQUIRED"):
            raise ApiError("ERR_PLAN_REVIEW_STATE_INVALID")
        watch(rec)
        rec["status"] = "DENIED"

    rec["decided_by_user_id"] = caller.user_id
    rec["decision_notes"] = decision_notes

    if decision == "APPROVE":
        est = store.establishments.get(rec["establishment_id"])
        if est is not None and est["permit_status"] == "PENDING_PLAN_REVIEW":
            force(est)
            est["permit_status"] = "PENDING_INSPECTION"
            domain.recompute_posture(est)
    return send(lambda: serialize.plan_review(rec), 200)


@bp.post("/body-art/plan-reviews/<plan_review_id>/resubmit")
def resubmit_plan_review(plan_review_id):
    caller = authenticate(["EstablishmentOperator"])
    rec = V.get_plan_review(plan_review_id)
    data = V.body()
    floor_plan_reference = V.req_string(data, "floor_plan_reference", 1, 80)
    sterilization_area_sqft = V.req_number(data, "sterilization_area_sqft", gt=0)
    procedure_station_count = V.req_int(data, "procedure_station_count", minimum=1)
    has_handwash_sink = V.req_bool(data, "has_handwash_sink")
    require_owns_establishment(caller, rec["establishment_id"])

    if rec["status"] != "CORRECTIONS_REQUIRED":
        raise ApiError("ERR_PLAN_REVIEW_STATE_INVALID")
    if rec["cycle_count"] >= config.PLAN_REVIEW_MAX_CYCLES:
        raise ApiError("ERR_PLAN_REVIEW_CYCLE_LIMIT")

    watch(rec)
    rec["status"] = "SUBMITTED"
    rec["cycle_count"] += 1
    rec["decision_notes"] = None
    rec["floor_plan_reference"] = floor_plan_reference
    rec["sterilization_area_sqft"] = sterilization_area_sqft
    rec["procedure_station_count"] = procedure_station_count
    rec["has_handwash_sink"] = has_handwash_sink

    est = store.establishments.get(rec["establishment_id"])
    if est is not None:
        watch(est)
        est["plan_review_cycles_used"] = rec["cycle_count"]
    return send(lambda: serialize.plan_review(rec), 200)
