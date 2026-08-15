from decimal import Decimal

from flask import Blueprint, request

import db
from calc import (PRODUCT_WARRANTY_YEARS, add_years, quality_scores,
                  SUSPEND_THRESHOLD, parse_date)
from errors import ApiError
from middleware import authenticate, require_role, locked
from response import ok, ok_list
from serializers import ser_treatment
from validators import (body, req_field, as_str, as_int, as_enum,
                        as_date_str, pagination, apply_filters)

bp = Blueprint("treatments", __name__)

PRODUCT_CODES = ["CCA_WRAP", "PENTA_GEL", "COPPER_NAPHTHENATE"]


def _get_treatment(tid):
    o = db.treatments.get(tid)
    if o is None:
        raise ApiError("ERR_TREATMENT_NOT_FOUND", 404,
                       "treatment order id does not resolve")
    return o


@bp.post("/pole-program/treatment-work-orders")
@locked
def create_treatment():
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    pole_id = as_str(req_field(d, "pole_id"), "pole_id")
    product_code = as_enum(req_field(d, "product_code"), "product_code",
                           PRODUCT_CODES)
    cost_cents = as_int(req_field(d, "cost_cents"), "cost_cents", 0)
    pole = db.poles.get(pole_id)
    if pole is None:
        raise ApiError("ERR_POLE_NOT_FOUND", 404, "pole_id does not resolve")
    if pole["status"] == "REPLACED":
        raise ApiError("ERR_POLE_REPLACED", 409,
                       "Operation targets a pole whose status == REPLACED")
    rec = db.new_record()
    rec.update(pole_id=pole_id, product_code=product_code, crew_id=None,
               work_start_date=None, work_end_date=None, cost_cents=cost_cents,
               is_warranty_retreat=False, source_claim_id=None,
               status="CREATED", applied_at=None, applied_by_crew_id=None,
               warranty_years=None, warranty_end_date=None, qa_fail_events=0,
               _verified_dt=None)
    db.treatments[rec["id"]] = rec
    pole["open_treatment_count"] += 1
    db.touch(pole)
    return ok(ser_treatment(rec), 201)


@bp.get("/pole-program/treatment-work-orders")
def list_treatments():
    authenticate()
    limit, offset = pagination()
    items = apply_filters(db.treatments.values(), [
        ("pole_id", request.args.get("pole_id")),
        ("crew_id", request.args.get("crew_id")),
        ("status", request.args.get("status")),
        ("source_claim_id", request.args.get("source_claim_id")),
    ])
    page = items[offset:offset + limit]
    return ok_list([ser_treatment(o) for o in page], len(items), limit, offset)


@bp.get("/pole-program/treatment-work-orders/<tid>")
def get_treatment(tid):
    authenticate()
    return ok(ser_treatment(_get_treatment(tid)), 200)


@bp.post("/pole-program/treatment-work-orders/<tid>/schedule")
@locked
def schedule_treatment(tid):
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    crew_id = as_str(req_field(d, "crew_id"), "crew_id")
    ws = as_date_str(req_field(d, "work_start_date"), "work_start_date")
    we = as_date_str(req_field(d, "work_end_date"), "work_end_date")
    order = _get_treatment(tid)
    crew = db.crews.get(crew_id)
    if crew is None:
        raise ApiError("ERR_CREW_NOT_FOUND", 404, "crew_id does not resolve")
    if order["status"] not in ("CREATED", "FAILED_QA"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "schedule requires order.status in {CREATED, FAILED_QA}")
    if crew["status"] != "ACTIVE":
        raise ApiError("ERR_CREW_SUSPENDED", 409,
                       "schedule requires crew.status == ACTIVE")
    d1 = parse_date(ws)
    d2 = parse_date(we)
    # Half-open [start, end) overlap against other SCHEDULED orders of the crew;
    # adjacency (start == other end) is allowed.
    for o2 in db.treatments.values():
        if o2["id"] == order["id"] or o2["crew_id"] != crew_id \
                or o2["status"] != "SCHEDULED":
            continue
        s2 = parse_date(o2["work_start_date"])
        e2 = parse_date(o2["work_end_date"])
        if d1 < e2 and s2 < d2:
            raise ApiError("ERR_CREW_SCHEDULE_CONFLICT", 409,
                           "Half-open crew window overlaps another SCHEDULED "
                           "order for the crew")
    if not (d2 > d1):
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "work_end_date must be strictly after work_start_date")
    if order["status"] == "FAILED_QA":
        # Retreatment loop erases the failed application.
        order["applied_at"] = None
        order["applied_by_crew_id"] = None
        order["warranty_years"] = None
        order["warranty_end_date"] = None
    order["crew_id"] = crew_id
    order["work_start_date"] = ws
    order["work_end_date"] = we
    order["status"] = "SCHEDULED"
    db.touch(order)
    return ok(ser_treatment(order), 200)


@bp.post("/pole-program/treatment-work-orders/<tid>/apply")
@locked
def apply_treatment(tid):
    uid, role = authenticate()
    require_role(role, "Contractor")
    order = _get_treatment(tid)
    if order["crew_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Contractor X-User-ID != order.crew_id")
    if order["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "apply requires order.status == SCHEDULED")
    n = db.clock_now()
    order["applied_at"] = n
    order["applied_by_crew_id"] = uid
    order["warranty_years"] = PRODUCT_WARRANTY_YEARS[order["product_code"]]
    order["warranty_end_date"] = add_years(n, order["warranty_years"])
    order["status"] = "APPLIED"
    db.touch(order)
    return ok(ser_treatment(order), 200)


@bp.post("/pole-program/treatment-work-orders/<tid>/qa-review")
@locked
def qa_review_treatment(tid):
    uid, role = authenticate()
    require_role(role, "QAReviewer")
    d = body()
    decision = as_enum(req_field(d, "decision"), "decision", ["PASS", "FAIL"])
    order = _get_treatment(tid)
    if order["status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "treatment qa-review requires order.status == APPLIED")
    crew = db.crews.get(order["crew_id"])
    n = db.clock_now()
    crew["qa_event_log"].append({"decision": decision, "decided_at": n,
                                 "order_id": order["id"], "_seq": db.next_seq()})
    if decision == "PASS":
        crew["qa_pass_count"] += 1
    else:
        crew["qa_fail_count"] += 1
    lifetime, rolling = quality_scores(crew)
    crew["quality_score_lifetime"] = lifetime
    crew["quality_score_rolling"] = rolling
    if decision == "PASS":
        order["status"] = "VERIFIED"
        order["_verified_dt"] = n
        # Reinstatement cascade: rolling back to >= 70.00 reactivates.
        if crew["status"] == "SUSPENDED" and rolling >= SUSPEND_THRESHOLD:
            crew["status"] = "ACTIVE"
        pole = db.poles[order["pole_id"]]
        pole["last_treatment_date"] = order["applied_at"]
        if pole["status"] == "MONITOR":
            pole["status"] = "IN_SERVICE"
        pole["open_treatment_count"] -= 1
        db.touch(pole)
    else:
        order["status"] = "FAILED_QA"
        order["qa_fail_events"] += 1
        # Suspension cascade consults the rolling score only.
        if crew["status"] == "ACTIVE" and rolling < SUSPEND_THRESHOLD:
            crew["status"] = "SUSPENDED"
    db.touch(crew)
    db.touch(order)
    return ok(ser_treatment(order), 200)
