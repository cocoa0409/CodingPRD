"""Health Department Food Safety Inspection API — Flask entry point.

In-memory store, fresh on every boot. Binds 0.0.0.0:$PORT (default 10000),
foreground. No seeding at startup.
"""
import os

from flask import Flask, request

import calculations as calc
import services
from db import stamp_new, store, touch
from errors import ApiError, err
from pagination import paginate
from response import array_response, object_response, error_response
from serialize import serialize, serialize_list
from validation import (
    auth,
    get_body,
    optional_bool,
    optional_int,
    optional_str,
    require_enum,
    require_field,
    require_int,
    require_str,
)

app = Flask(__name__)

ALL_ROLES = ["HealthDirector", "PermitClerk", "Inspector", "EnforcementOfficer"]


# =============================================================================
# Error handling
# =============================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_INVALID_REQUEST", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


# =============================================================================
# Lookup helpers (priority 3/4 existence checks)
# =============================================================================
_NOT_FOUND = {
    "establishments": "ERR_ESTABLISHMENT_NOT_FOUND",
    "plan_reviews": "ERR_PLAN_REVIEW_NOT_FOUND",
    "permits": "ERR_PERMIT_NOT_FOUND",
    "inspections": "ERR_INSPECTION_NOT_FOUND",
    "violations": "ERR_VIOLATION_NOT_FOUND",
    "fda_food_codes": "ERR_CODE_NOT_FOUND",
    "inspectors": "ERR_INSPECTOR_NOT_FOUND",
    "inspection_routes": "ERR_ROUTE_NOT_FOUND",
    "closure_orders": "ERR_CLOSURE_ORDER_NOT_FOUND",
    "complaints": "ERR_COMPLAINT_NOT_FOUND",
    "enforcement_cases": "ERR_CASE_NOT_FOUND",
}


def lookup(collection_name, rid):
    coll = getattr(store, collection_name)
    rec = coll.get(rid)
    if rec is None:
        raise err(_NOT_FOUND[collection_name])
    return rec


def filter_by(records, field, value):
    if value is None:
        return records
    return [r for r in records if r.get(field) == value]


# =============================================================================
# Clock
# =============================================================================
@app.route("/_clock/set_current_index", methods=["POST"])
def set_clock():
    auth(["HealthDirector"])
    body = get_body()
    to_index = require_int(body, "to_index", minimum=0)
    with store.lock:
        store.clock_index = to_index
    return object_response({"current_index": store.clock_index}, 200)


@app.route("/_clock", methods=["GET"])
def get_clock():
    auth(ALL_ROLES)
    return object_response({"current_index": store.clock_index}, 200)


# =============================================================================
# FDA Food Codes
# =============================================================================
@app.route("/fda-food-codes", methods=["POST"])
def create_code():
    auth(["HealthDirector"])
    body = get_body()
    code = require_str(body, "code")
    title = require_str(body, "title")
    classification = require_enum(body, "classification", {"CRITICAL", "NON_CRITICAL"})
    base = require_int(body, "base_demerit_points", minimum=1, maximum=40)
    surcharge = optional_int(body, "repeat_surcharge_points", default=0, minimum=0, maximum=20)
    with store.lock:
        rec = {
            "code": code,
            "title": title,
            "classification": classification,
            "base_demerit_points": base,
            "repeat_surcharge_points": surcharge,
            "is_active": True,
        }
        stamp_new(rec)
        store.fda_food_codes[rec["id"]] = rec
    return object_response(serialize(rec, "FdaFoodCode"), 201)


@app.route("/fda-food-codes", methods=["GET"])
def list_codes():
    auth(ALL_ROLES)
    records = list(store.fda_food_codes.values())
    records = filter_by(records, "classification", request.args.get("classification"))
    is_active = request.args.get("is_active")
    if is_active is not None:
        want = is_active.lower() == "true"
        records = [r for r in records if r["is_active"] == want]
    page, limit, offset, total = paginate(records)
    return array_response(serialize_list(page, "FdaFoodCode"), limit, offset, total)


@app.route("/fda-food-codes/<code_id>", methods=["GET"])
def get_code(code_id):
    auth(ALL_ROLES)
    rec = lookup("fda_food_codes", code_id)
    return object_response(serialize(rec, "FdaFoodCode"))


@app.route("/fda-food-codes/<code_id>/retire", methods=["POST"])
def retire_code(code_id):
    auth(["HealthDirector"])
    rec = lookup("fda_food_codes", code_id)
    with store.lock:
        rec["is_active"] = False
        touch(rec)
    return object_response(serialize(rec, "FdaFoodCode"))


# =============================================================================
# Inspectors
# =============================================================================
@app.route("/inspectors", methods=["POST"])
def create_inspector():
    auth(["HealthDirector"])
    body = get_body()
    full_name = require_str(body, "full_name")
    badge = require_str(body, "badge_number")
    cap = optional_int(body, "max_daily_route_stops", default=8, minimum=1, maximum=20)
    with store.lock:
        rec = {
            "full_name": full_name,
            "badge_number": badge,
            "max_daily_route_stops": cap,
            "is_active": True,
        }
        stamp_new(rec)
        store.inspectors[rec["id"]] = rec
    return object_response(serialize(rec, "Inspector"), 201)


@app.route("/inspectors", methods=["GET"])
def list_inspectors():
    auth(ALL_ROLES)
    records = list(store.inspectors.values())
    is_active = request.args.get("is_active")
    if is_active is not None:
        want = is_active.lower() == "true"
        records = [r for r in records if r["is_active"] == want]
    page, limit, offset, total = paginate(records)
    return array_response(serialize_list(page, "Inspector"), limit, offset, total)


@app.route("/inspectors/<inspector_id>", methods=["GET"])
def get_inspector(inspector_id):
    auth(ALL_ROLES)
    rec = lookup("inspectors", inspector_id)
    return object_response(serialize(rec, "Inspector"))


# =============================================================================
# Establishments
# =============================================================================
def _apply_risk(est):
    cat, interval = calc.risk_category_assignment(
        est["seating_capacity"],
        est["serves_raw_animal_foods"],
        est["does_onsite_processing"],
    )
    est["risk_category"] = cat
    est["routine_interval_days"] = interval


@app.route("/establishments", methods=["POST"])
def create_establishment():
    auth(["PermitClerk"])
    body = get_body()
    name = require_str(body, "name")
    address = require_str(body, "address")
    cuisine = optional_str(body, "cuisine_type")
    seating = require_int(body, "seating_capacity", minimum=0)
    raw = optional_bool(body, "serves_raw_animal_foods", default=False)
    onsite = optional_bool(body, "does_onsite_processing", default=False)
    with store.lock:
        rec = {
            "name": name,
            "address": address,
            "cuisine_type": cuisine,
            "seating_capacity": seating,
            "serves_raw_animal_foods": raw,
            "does_onsite_processing": onsite,
            "status": "PRELICENSE",
            "current_score": None,
            "current_grade": None,
            "current_placard_color": None,
            "open_critical_count": 0,
            "next_reinspection_due_index": None,
            "active_closure_order_id": None,
        }
        _apply_risk(rec)
        stamp_new(rec)
        store.establishments[rec["id"]] = rec
    return object_response(serialize(rec, "Establishment"), 201)


@app.route("/establishments", methods=["GET"])
def list_establishments():
    auth(ALL_ROLES)
    records = list(store.establishments.values())
    records = filter_by(records, "status", request.args.get("status"))
    records = filter_by(records, "risk_category", request.args.get("risk_category"))
    page, limit, offset, total = paginate(records)
    return array_response(serialize_list(page, "Establishment"), limit, offset, total)


@app.route("/establishments/<establishment_id>", methods=["GET"])
def get_establishment(establishment_id):
    auth(ALL_ROLES)
    rec = lookup("establishments", establishment_id)
    return object_response(serialize(rec, "Establishment"))


@app.route("/establishments/<establishment_id>", methods=["PUT"])
def update_establishment(establishment_id):
    auth(["PermitClerk"])
    rec = lookup("establishments", establishment_id)
    body = get_body()
    with store.lock:
        if "name" in body and body["name"] is not None:
            rec["name"] = require_str(body, "name")
        if "address" in body and body["address"] is not None:
            rec["address"] = require_str(body, "address")
        if "cuisine_type" in body:
            rec["cuisine_type"] = optional_str(body, "cuisine_type", rec.get("cuisine_type"))
        if "seating_capacity" in body and body["seating_capacity"] is not None:
            rec["seating_capacity"] = require_int(body, "seating_capacity", minimum=0)
        if "serves_raw_animal_foods" in body and body["serves_raw_animal_foods"] is not None:
            rec["serves_raw_animal_foods"] = optional_bool(body, "serves_raw_animal_foods")
        if "does_onsite_processing" in body and body["does_onsite_processing"] is not None:
            rec["does_onsite_processing"] = optional_bool(body, "does_onsite_processing")
        _apply_risk(rec)
        touch(rec)
    return object_response(serialize(rec, "Establishment"))


@app.route("/establishments/<establishment_id>/revoke", methods=["POST"])
def revoke_establishment(establishment_id):
    auth(["HealthDirector"])
    rec = lookup("establishments", establishment_id)
    with store.lock:
        if rec["status"] not in ("PERMITTED", "SUSPENDED"):
            raise err("ERR_ESTABLISHMENT_NOT_REVOCABLE")
        rec["status"] = "REVOKED"
        touch(rec)
        for p in store.permits.values():
            if p["establishment_id"] == establishment_id and not p.get("_void"):
                if store.clock_index <= p["expires_index"]:
                    p["_void"] = True
                    touch(p)
                else:
                    # Already expired by clock; revoke still voids it.
                    p["_void"] = True
                    touch(p)
    return object_response(serialize(rec, "Establishment"))


# =============================================================================
# Plan Reviews
# =============================================================================
@app.route("/plan-reviews", methods=["POST"])
def create_plan_review():
    auth(["PermitClerk"])
    body = get_body()
    est_id = require_str(body, "establishment_id")
    lookup("establishments", est_id)
    sqft = require_int(body, "submitted_layout_sqft", minimum=1)
    equip = require_int(body, "equipment_count", minimum=0)
    with store.lock:
        rec = {
            "establishment_id": est_id,
            "submitted_layout_sqft": sqft,
            "equipment_count": equip,
            "plan_fee_cents": calc.plan_review_fee(sqft, equip),
            "rejection_reason": None,
            "revision_round": 0,
            "status": "SUBMITTED",
        }
        stamp_new(rec)
        store.plan_reviews[rec["id"]] = rec
    return object_response(serialize(rec, "PlanReview"), 201)


@app.route("/plan-reviews", methods=["GET"])
def list_plan_reviews():
    auth(ALL_ROLES)
    records = list(store.plan_reviews.values())
    records = filter_by(records, "establishment_id", request.args.get("establishment_id"))
    records = filter_by(records, "status", request.args.get("status"))
    page, limit, offset, total = paginate(records)
    return array_response(serialize_list(page, "PlanReview"), limit, offset, total)


@app.route("/plan-reviews/<plan_review_id>", methods=["GET"])
def get_plan_review(plan_review_id):
    auth(ALL_ROLES)
    rec = lookup("plan_reviews", plan_review_id)
    return object_response(serialize(rec, "PlanReview"))


@app.route("/plan-reviews/<plan_review_id>/approve", methods=["POST"])
def approve_plan_review(plan_review_id):
    auth(["PermitClerk"])
    rec = lookup("plan_reviews", plan_review_id)
    with store.lock:
        if rec["status"] != "SUBMITTED":
            raise err("ERR_PLAN_REVIEW_NOT_SUBMITTED")
        est = store.establishments.get(rec["establishment_id"])
        if est is None or est["status"] != "PRELICENSE":
            raise err("ERR_ESTABLISHMENT_NOT_PRELICENSE")
        rec["status"] = "APPROVED"
        touch(rec)
    return object_response(serialize(rec, "PlanReview"))


@app.route("/plan-reviews/<plan_review_id>/reject", methods=["POST"])
def reject_plan_review(plan_review_id):
    auth(["PermitClerk"])
    rec = lookup("plan_reviews", plan_review_id)
    body = get_body()
    with store.lock:
        if rec["status"] != "SUBMITTED":
            raise err("ERR_PLAN_REVIEW_NOT_SUBMITTED")
        reason = body.get("rejection_reason")
        if not isinstance(reason, str) or reason.strip() == "":
            raise err("ERR_MISSING_REJECTION_REASON")
        rec["status"] = "REJECTED"
        rec["rejection_reason"] = reason
        touch(rec)
    return object_response(serialize(rec, "PlanReview"))


@app.route("/plan-reviews/<plan_review_id>/resubmit", methods=["POST"])
def resubmit_plan_review(plan_review_id):
    auth(["PermitClerk"])
    rec = lookup("plan_reviews", plan_review_id)
    body = get_body()
    with store.lock:
        if rec["status"] != "REJECTED":
            raise err("ERR_PLAN_REVIEW_NOT_REJECTED")
        if "submitted_layout_sqft" in body and body["submitted_layout_sqft"] is not None:
            rec["submitted_layout_sqft"] = require_int(body, "submitted_layout_sqft", minimum=1)
        if "equipment_count" in body and body["equipment_count"] is not None:
            rec["equipment_count"] = require_int(body, "equipment_count", minimum=0)
        rec["revision_round"] += 1
        rec["plan_fee_cents"] = calc.plan_review_fee(
            rec["submitted_layout_sqft"], rec["equipment_count"]
        )
        rec["rejection_reason"] = None
        rec["status"] = "SUBMITTED"
        touch(rec)
    return object_response(serialize(rec, "PlanReview"))


# =============================================================================
# Permits
# =============================================================================
@app.route("/permits", methods=["POST"])
def create_permit():
    auth(["PermitClerk"])
    body = get_body()
    est_id = require_str(body, "establishment_id")
    pr_id = require_str(body, "plan_review_id")
    est = lookup("establishments", est_id)
    pr = lookup("plan_reviews", pr_id)
    with store.lock:
        if est["status"] != "PRELICENSE":
            raise err("ERR_ESTABLISHMENT_NOT_PRELICENSE")
        if pr["establishment_id"] != est_id or pr["status"] != "APPROVED":
            raise err("ERR_PLAN_REVIEW_NOT_APPROVED")
        clock = store.clock_index
        permit = {
            "establishment_id": est_id,
            "plan_review_id": pr_id,
            "issued_index": clock,
            "expires_index": clock + calc.PERMIT_TERM_DAYS,
            "annual_fee_cents": calc.permit_fee(est["risk_category"]),
            "_void": False,
        }
        stamp_new(permit)
        store.permits[permit["id"]] = permit
        est["status"] = "PERMITTED"
        est["next_reinspection_due_index"] = clock + est["routine_interval_days"]
        touch(est)
    return object_response(serialize(permit, "Permit"), 201)


@app.route("/permits", methods=["GET"])
def list_permits():
    auth(ALL_ROLES)
    records = list(store.permits.values())
    records = filter_by(records, "establishment_id", request.args.get("establishment_id"))
    records = filter_by(records, "plan_review_id", request.args.get("plan_review_id"))
    status_q = request.args.get("status")
    if status_q is not None:
        records = [r for r in records if serialize(r, "Permit")["status"] == status_q]
    page, limit, offset, total = paginate(records)
    return array_response(serialize_list(page, "Permit"), limit, offset, total)


@app.route("/permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    auth(ALL_ROLES)
    rec = lookup("permits", permit_id)
    return object_response(serialize(rec, "Permit"))


# =============================================================================
# Inspection Routes
# =============================================================================
@app.route("/inspection-routes", methods=["POST"])
def create_route():
    auth(["PermitClerk", "Inspector"])
    body = get_body()
    inspector_id = require_str(body, "inspector_id")
    lookup("inspectors", inspector_id)
    route_date = require_int(body, "route_date_index", minimum=0)
    with store.lock:
        rec = {
            "inspector_id": inspector_id,
            "route_date_index": route_date,
            "planned_stop_count": 0,
            "status": "PLANNED",
        }
        stamp_new(rec)
        store.inspection_routes[rec["id"]] = rec
    return object_response(serialize(rec, "InspectionRoute"), 201)


@app.route("/inspection-routes", methods=["GET"])
def list_routes():
    auth(ALL_ROLES)
    records = list(store.inspection_routes.values())
    records = filter_by(records, "inspector_id", request.args.get("inspector_id"))
    records = filter_by(records, "status", request.args.get("status"))
    page, limit, offset, total = paginate(records)
    return array_response(serialize_list(page, "InspectionRoute"), limit, offset, total)


@app.route("/inspection-routes/<route_id>", methods=["GET"])
def get_route(route_id):
    auth(ALL_ROLES)
    rec = lookup("inspection_routes", route_id)
    return object_response(serialize(rec, "InspectionRoute"))


@app.route("/inspection-routes/<route_id>/dispatch", methods=["POST"])
def dispatch_route(route_id):
    auth(["Inspector"])
    rec = lookup("inspection_routes", route_id)
    with store.lock:
        if rec["status"] != "PLANNED":
            raise err("ERR_ROUTE_NOT_PLANNED")
        if rec["route_date_index"] < store.clock_index:
            raise err("ERR_ROUTE_DATE_IN_PAST")
        inspector = store.inspectors.get(rec["inspector_id"])
        cap = inspector["max_daily_route_stops"] if inspector else 0
        if rec["planned_stop_count"] > cap:
            raise err("ERR_ROUTE_CAPACITY_EXCEEDED")
        rec["status"] = "DISPATCHED"
        touch(rec)
    return object_response(serialize(rec, "InspectionRoute"))


@app.route("/inspection-routes/<route_id>/close", methods=["POST"])
def close_route(route_id):
    auth(["Inspector"])
    rec = lookup("inspection_routes", route_id)
    with store.lock:
        if rec["status"] != "DISPATCHED":
            raise err("ERR_ROUTE_NOT_DISPATCHED")
        rec["status"] = "COMPLETED"
        touch(rec)
    return object_response(serialize(rec, "InspectionRoute"))


# =============================================================================
# Inspections
# =============================================================================
_NON_TERMINAL_INSPECTION = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "AMENDING"}


@app.route("/inspections", methods=["POST"])
def create_inspection():
    auth(["PermitClerk", "Inspector"])
    body = get_body()
    est_id = require_str(body, "establishment_id")
    inspector_id = require_str(body, "inspector_id")
    insp_type = require_enum(body, "inspection_type", {"ROUTINE", "REINSPECTION", "COMPLAINT"})
    scheduled_index = require_int(body, "scheduled_index", minimum=0)
    route_id = optional_str(body, "route_id")
    reinspection_of_id = optional_str(body, "reinspection_of_id")

    # Body FK existence (priority 4).
    lookup("establishments", est_id)
    lookup("inspectors", inspector_id)
    if route_id is not None:
        lookup("inspection_routes", route_id)
    if reinspection_of_id is not None:
        lookup("inspections", reinspection_of_id)

    with store.lock:
        # Business: reinspection target must be a prior FINALIZED inspection of
        # the same establishment.
        if insp_type == "REINSPECTION":
            if reinspection_of_id is None:
                raise err("ERR_INVALID_REINSPECTION_TARGET")
            target = store.inspections.get(reinspection_of_id)
            if (
                target is None
                or target["status"] != "FINALIZED"
                or target["establishment_id"] != est_id
            ):
                raise err("ERR_INVALID_REINSPECTION_TARGET")

        # Double-booking: same inspector on same scheduled_index with another
        # non-terminal inspection.
        for other in store.inspections.values():
            if (
                other["inspector_id"] == inspector_id
                and other["scheduled_index"] == scheduled_index
                and other["status"] in _NON_TERMINAL_INSPECTION
            ):
                raise err("ERR_INSPECTOR_DOUBLE_BOOKED")

        rec = {
            "establishment_id": est_id,
            "route_id": route_id,
            "inspector_id": inspector_id,
            "inspection_type": insp_type,
            "reinspection_of_id": reinspection_of_id,
            "scheduled_index": scheduled_index,
            "as_observed_score": None,
            "final_score": None,
            "grade": None,
            "placard_color": None,
            "critical_count": 0,
            "status": "SCHEDULED",
        }
        stamp_new(rec)
        store.inspections[rec["id"]] = rec
        if route_id is not None:
            route = store.inspection_routes[route_id]
            route["planned_stop_count"] += 1
            touch(route)
    return object_response(serialize(rec, "Inspection"), 201)


@app.route("/inspections", methods=["GET"])
def list_inspections():
    auth(ALL_ROLES)
    records = list(store.inspections.values())
    records = filter_by(records, "establishment_id", request.args.get("establishment_id"))
    records = filter_by(records, "inspector_id", request.args.get("inspector_id"))
    records = filter_by(records, "route_id", request.args.get("route_id"))
    records = filter_by(records, "reinspection_of_id", request.args.get("reinspection_of_id"))
    records = filter_by(records, "inspection_type", request.args.get("inspection_type"))
    records = filter_by(records, "status", request.args.get("status"))
    page, limit, offset, total = paginate(records)
    return array_response(serialize_list(page, "Inspection"), limit, offset, total)


@app.route("/inspections/<inspection_id>", methods=["GET"])
def get_inspection(inspection_id):
    auth(ALL_ROLES)
    rec = lookup("inspections", inspection_id)
    return object_response(serialize(rec, "Inspection"))


@app.route("/inspections/<inspection_id>/start", methods=["POST"])
def start_inspection(inspection_id):
    user_id, role = auth(["Inspector"])
    rec = lookup("inspections", inspection_id)
    with store.lock:
        if rec["status"] != "SCHEDULED":
            raise err("ERR_INSPECTION_NOT_SCHEDULED")
        if rec["inspector_id"] != user_id:
            raise err("ERR_NOT_ASSIGNED_INSPECTOR")
        est = store.establishments.get(rec["establishment_id"])
        if est is not None and est["status"] == "REVOKED":
            raise err("ERR_ESTABLISHMENT_REVOKED")
        rec["status"] = "IN_PROGRESS"
        touch(rec)
    return object_response(serialize(rec, "Inspection"))


@app.route("/inspections/<inspection_id>/complete", methods=["POST"])
def complete_inspection(inspection_id):
    auth(["Inspector"])
    rec = lookup("inspections", inspection_id)
    with store.lock:
        if rec["status"] not in ("IN_PROGRESS", "AMENDING"):
            # Distinguish which error per current state.
            if rec["status"] == "AMENDING":
                raise err("ERR_INSPECTION_NOT_AMENDING")
            raise err("ERR_INSPECTION_NOT_IN_PROGRESS")
        services.recompute_inspection_scores(rec)
        rec["status"] = "COMPLETED"
        touch(rec)
    return object_response(serialize(rec, "Inspection"))


@app.route("/inspections/<inspection_id>/reopen", methods=["POST"])
def reopen_inspection(inspection_id):
    auth(["Inspector"])
    rec = lookup("inspections", inspection_id)
    with store.lock:
        if rec["status"] != "COMPLETED":
            raise err("ERR_INSPECTION_NOT_COMPLETED")
        rec["status"] = "AMENDING"
        touch(rec)
    return object_response(serialize(rec, "Inspection"))


@app.route("/inspections/<inspection_id>/finalize", methods=["POST"])
def finalize_inspection(inspection_id):
    auth(["Inspector"])
    rec = lookup("inspections", inspection_id)
    body = get_body()
    # OCC field is non-optional.
    expected = require_int(body, "expected_inspection_version")
    with store.lock:
        # Priority 5: OCC before business logic.
        if expected != rec["version"]:
            raise err("ERR_STALE_INSPECTION_VERSION")
        # Priority 6: state legality.
        if rec["status"] != "COMPLETED":
            raise err("ERR_INSPECTION_NOT_COMPLETED")
        # Priority 9: not on a revoked establishment.
        est = store.establishments.get(rec["establishment_id"])
        if est is not None and est["status"] == "REVOKED":
            raise err("ERR_ESTABLISHMENT_REVOKED")

        # Recompute final scores to be safe, then finalize.
        services.recompute_inspection_scores(rec)
        rec["status"] = "FINALIZED"
        touch(rec)  # version increments by 1 on finalize

        services.finalize_cascade(rec, est)
    return object_response(serialize(rec, "Inspection"))


# =============================================================================
# Violations
# =============================================================================
@app.route("/violations", methods=["POST"])
def create_violation():
    auth(["Inspector"])
    body = get_body()
    inspection_id = require_str(body, "inspection_id")
    fda_code_id = require_str(body, "fda_code_id")
    corrected = optional_bool(body, "corrected_on_site", default=False)
    inspection = lookup("inspections", inspection_id)
    code = lookup("fda_food_codes", fda_code_id)
    with store.lock:
        # State legality: editable only IN_PROGRESS / AMENDING.
        if inspection["status"] not in ("IN_PROGRESS", "AMENDING"):
            raise err("ERR_INSPECTION_NOT_EDITABLE")
        # Business: cited code must be active.
        if not code["is_active"]:
            raise err("ERR_CODE_RETIRED")
        repeat = services.is_repeat_offense(inspection["establishment_id"], fda_code_id)
        observed, final = calc.violation_points(
            code["base_demerit_points"],
            code.get("repeat_surcharge_points", 0),
            repeat,
            corrected,
        )
        rec = {
            "inspection_id": inspection_id,
            "fda_code_id": fda_code_id,
            "classification": code["classification"],
            "corrected_on_site": corrected,
            "repeat_offense": repeat,
            "demerit_points_observed": observed,
            "demerit_points_final": final,
            "resolution_status": "OPEN",
        }
        stamp_new(rec)
        store.violations[rec["id"]] = rec
    return object_response(serialize(rec, "Violation"), 201)


@app.route("/violations", methods=["GET"])
def list_violations():
    auth(ALL_ROLES)
    records = list(store.violations.values())
    records = filter_by(records, "inspection_id", request.args.get("inspection_id"))
    records = filter_by(records, "fda_code_id", request.args.get("fda_code_id"))
    records = filter_by(records, "classification", request.args.get("classification"))
    records = filter_by(records, "resolution_status", request.args.get("resolution_status"))
    page, limit, offset, total = paginate(records)
    return array_response(serialize_list(page, "Violation"), limit, offset, total)


@app.route("/violations/<violation_id>", methods=["GET"])
def get_violation(violation_id):
    auth(ALL_ROLES)
    rec = lookup("violations", violation_id)
    return object_response(serialize(rec, "Violation"))


@app.route("/violations/<violation_id>", methods=["DELETE"])
def delete_violation(violation_id):
    auth(["Inspector"])
    rec = lookup("violations", violation_id)
    with store.lock:
        inspection = store.inspections.get(rec["inspection_id"])
        if inspection is None or inspection["status"] not in ("IN_PROGRESS", "AMENDING"):
            raise err("ERR_INSPECTION_NOT_EDITABLE")
        del store.violations[violation_id]
    return ("", 204)


# =============================================================================
# Closure Orders
# =============================================================================
@app.route("/closure-orders", methods=["POST"])
def create_closure_order():
    auth(["EnforcementOfficer", "HealthDirector"])
    body = get_body()
    est_id = require_str(body, "establishment_id")
    trig_id = require_str(body, "triggering_inspection_id")
    reason = require_enum(
        body, "reason_code",
        {"GRADE_C_AUTOCLOSE", "CRITICAL_THRESHOLD", "IMMINENT_HEALTH_HAZARD"},
    )
    est = lookup("establishments", est_id)
    lookup("inspections", trig_id)
    with store.lock:
        if est["status"] != "PERMITTED":
            raise err("ERR_ESTABLISHMENT_NOT_PERMITTED")
        clock = store.clock_index
        order = {
            "establishment_id": est_id,
            "triggering_inspection_id": trig_id,
            "reason_code": reason,
            "issued_index": clock,
            "status": "ACTIVE",
        }
        stamp_new(order)
        store.closure_orders[order["id"]] = order
        est["status"] = "SUSPENDED"
        est["active_closure_order_id"] = order["id"]
        est["next_reinspection_due_index"] = clock + calc.REINSPECTION_GRACE_DAYS
        touch(est)
    return object_response(serialize(order, "ClosureOrder"), 201)


@app.route("/closure-orders", methods=["GET"])
def list_closure_orders():
    auth(ALL_ROLES)
    records = list(store.closure_orders.values())
    records = filter_by(records, "establishment_id", request.args.get("establishment_id"))
    records = filter_by(records, "triggering_inspection_id", request.args.get("triggering_inspection_id"))
    records = filter_by(records, "status", request.args.get("status"))
    page, limit, offset, total = paginate(records)
    return array_response(serialize_list(page, "ClosureOrder"), limit, offset, total)


@app.route("/closure-orders/<closure_order_id>", methods=["GET"])
def get_closure_order(closure_order_id):
    auth(ALL_ROLES)
    rec = lookup("closure_orders", closure_order_id)
    return object_response(serialize(rec, "ClosureOrder"))


@app.route("/closure-orders/<closure_order_id>/lift", methods=["POST"])
def lift_closure_order(closure_order_id):
    auth(["EnforcementOfficer", "HealthDirector"])
    rec = lookup("closure_orders", closure_order_id)
    with store.lock:
        est = store.establishments.get(rec["establishment_id"])
        if est is None or est["status"] != "SUSPENDED":
            raise err("ERR_ESTABLISHMENT_NOT_SUSPENDED")
        if rec["status"] != "ACTIVE":
            raise err("ERR_CLOSURE_ORDER_NOT_ACTIVE")
        rec["status"] = "LIFTED"
        touch(rec)
        est["status"] = "PERMITTED"
        est["active_closure_order_id"] = None
        touch(est)
    return object_response(serialize(rec, "ClosureOrder"))


# =============================================================================
# Complaints
# =============================================================================
@app.route("/complaints", methods=["POST"])
def create_complaint():
    auth(ALL_ROLES)
    body = get_body()
    est_id = require_str(body, "establishment_id")
    ctype = require_enum(body, "complaint_type", {"FOODBORNE_ILLNESS", "SANITATION", "OTHER"})
    ill = optional_int(body, "reported_ill_count", default=0, minimum=0)
    lookup("establishments", est_id)
    with store.lock:
        rec = {
            "establishment_id": est_id,
            "complaint_type": ctype,
            "reported_ill_count": ill,
            "severity_score": None,
            "priority": None,
            "linked_inspection_id": None,
            "status": "RECEIVED",
        }
        stamp_new(rec)
        store.complaints[rec["id"]] = rec
    return object_response(serialize(rec, "Complaint"), 201)


@app.route("/complaints", methods=["GET"])
def list_complaints():
    auth(ALL_ROLES)
    records = list(store.complaints.values())
    records = filter_by(records, "establishment_id", request.args.get("establishment_id"))
    records = filter_by(records, "linked_inspection_id", request.args.get("linked_inspection_id"))
    records = filter_by(records, "status", request.args.get("status"))
    records = filter_by(records, "priority", request.args.get("priority"))
    page, limit, offset, total = paginate(records)
    return array_response(serialize_list(page, "Complaint"), limit, offset, total)


@app.route("/complaints/<complaint_id>", methods=["GET"])
def get_complaint(complaint_id):
    auth(ALL_ROLES)
    rec = lookup("complaints", complaint_id)
    return object_response(serialize(rec, "Complaint"))


@app.route("/complaints/<complaint_id>/triage", methods=["POST"])
def triage_complaint(complaint_id):
    auth(["PermitClerk"])
    rec = lookup("complaints", complaint_id)
    with store.lock:
        if rec["status"] != "RECEIVED":
            raise err("ERR_COMPLAINT_NOT_RECEIVED")
        est = store.establishments.get(rec["establishment_id"])
        risk = est["risk_category"] if est else "CATEGORY_1"
        severity, priority = calc.complaint_severity(
            rec["complaint_type"], rec["reported_ill_count"], risk
        )
        rec["severity_score"] = severity
        rec["priority"] = priority
        rec["status"] = "TRIAGED"
        touch(rec)
    return object_response(serialize(rec, "Complaint"))


@app.route("/complaints/<complaint_id>/dispatch", methods=["POST"])
def dispatch_complaint(complaint_id):
    user_id, role = auth(["Inspector"])
    rec = lookup("complaints", complaint_id)
    body = get_body()
    inspector_id = require_str(body, "inspector_id")
    lookup("inspectors", inspector_id)
    with store.lock:
        if rec["status"] != "TRIAGED":
            raise err("ERR_COMPLAINT_NOT_TRIAGED")
        est = store.establishments.get(rec["establishment_id"])
        if est is not None and est["status"] == "REVOKED":
            raise err("ERR_ESTABLISHMENT_REVOKED")
        clock = store.clock_index
        inspection = {
            "establishment_id": rec["establishment_id"],
            "route_id": None,
            "inspector_id": inspector_id,
            "inspection_type": "COMPLAINT",
            "reinspection_of_id": None,
            "scheduled_index": clock,
            "as_observed_score": None,
            "final_score": None,
            "grade": None,
            "placard_color": None,
            "critical_count": 0,
            "status": "SCHEDULED",
        }
        stamp_new(inspection)
        store.inspections[inspection["id"]] = inspection
        rec["linked_inspection_id"] = inspection["id"]
        rec["status"] = "DISPATCHED"
        touch(rec)
    return object_response(serialize(rec, "Complaint"))


@app.route("/complaints/<complaint_id>/close", methods=["POST"])
def close_complaint(complaint_id):
    auth(["PermitClerk"])
    rec = lookup("complaints", complaint_id)
    with store.lock:
        if rec["status"] != "DISPATCHED":
            raise err("ERR_COMPLAINT_NOT_DISPATCHED")
        linked = store.inspections.get(rec.get("linked_inspection_id"))
        if linked is None or linked["status"] != "FINALIZED":
            raise err("ERR_COMPLAINT_INSPECTION_OPEN")
        rec["status"] = "CLOSED"
        touch(rec)
    return object_response(serialize(rec, "Complaint"))


# =============================================================================
# Enforcement Cases
# =============================================================================
@app.route("/enforcement-cases", methods=["POST"])
def create_case():
    auth(["EnforcementOfficer"])
    body = get_body()
    est_id = require_str(body, "establishment_id")
    alleged = require_int(body, "alleged_penalty_cents", minimum=0)
    closure_order_id = optional_str(body, "closure_order_id")
    lookup("establishments", est_id)
    if closure_order_id is not None:
        lookup("closure_orders", closure_order_id)
    with store.lock:
        rec = {
            "establishment_id": est_id,
            "closure_order_id": closure_order_id,
            "alleged_penalty_cents": alleged,
            "assessed_penalty_cents": None,
            "hearing_index": None,
            "ruling": None,
            "status": "OPENED",
        }
        stamp_new(rec)
        store.enforcement_cases[rec["id"]] = rec
    return object_response(serialize(rec, "EnforcementCase"), 201)


@app.route("/enforcement-cases", methods=["GET"])
def list_cases():
    auth(ALL_ROLES)
    records = list(store.enforcement_cases.values())
    records = filter_by(records, "establishment_id", request.args.get("establishment_id"))
    records = filter_by(records, "closure_order_id", request.args.get("closure_order_id"))
    records = filter_by(records, "status", request.args.get("status"))
    page, limit, offset, total = paginate(records)
    return array_response(serialize_list(page, "EnforcementCase"), limit, offset, total)


@app.route("/enforcement-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    auth(ALL_ROLES)
    rec = lookup("enforcement_cases", case_id)
    return object_response(serialize(rec, "EnforcementCase"))


@app.route("/enforcement-cases/<case_id>/schedule-hearing", methods=["POST"])
def schedule_hearing(case_id):
    auth(["EnforcementOfficer"])
    rec = lookup("enforcement_cases", case_id)
    body = get_body()
    hearing_index = require_int(body, "hearing_index", minimum=0)
    with store.lock:
        if rec["status"] != "OPENED":
            raise err("ERR_CASE_NOT_OPENED")
        if hearing_index < store.clock_index:
            raise err("ERR_HEARING_IN_PAST")
        rec["hearing_index"] = hearing_index
        rec["status"] = "HEARING_SCHEDULED"
        touch(rec)
    return object_response(serialize(rec, "EnforcementCase"))


@app.route("/enforcement-cases/<case_id>/rule", methods=["POST"])
def rule_case(case_id):
    auth(["HealthDirector"])
    rec = lookup("enforcement_cases", case_id)
    body = get_body()
    ruling = require_field(body, "ruling")
    with store.lock:
        if rec["status"] != "HEARING_SCHEDULED":
            raise err("ERR_CASE_NOT_SCHEDULED")
        if store.clock_index < rec["hearing_index"]:
            raise err("ERR_HEARING_NOT_REACHED")
        if ruling not in ("UPHELD", "REDUCED", "DISMISSED"):
            raise err("ERR_INVALID_RULING")
        rec["ruling"] = ruling
        rec["assessed_penalty_cents"] = calc.penalty_assessment(ruling, rec["alleged_penalty_cents"])
        rec["status"] = "HEARD"
        touch(rec)
        # DISMISSED + contested closure -> VACATE and possibly reinstate.
        if ruling == "DISMISSED" and rec.get("closure_order_id"):
            order = store.closure_orders.get(rec["closure_order_id"])
            if order is not None and order["status"] == "ACTIVE":
                order["status"] = "VACATED"
                touch(order)
                est = store.establishments.get(rec["establishment_id"])
                if est is not None and est["status"] == "SUSPENDED":
                    other_active = any(
                        o["establishment_id"] == est["id"]
                        and o["status"] == "ACTIVE"
                        and o["id"] != order["id"]
                        for o in store.closure_orders.values()
                    )
                    if not other_active:
                        if est.get("active_closure_order_id") == order["id"]:
                            est["active_closure_order_id"] = None
                        est["status"] = "PERMITTED"
                        touch(est)
    return object_response(serialize(rec, "EnforcementCase"))


@app.route("/enforcement-cases/<case_id>/settle", methods=["POST"])
def settle_case(case_id):
    auth(["EnforcementOfficer"])
    rec = lookup("enforcement_cases", case_id)
    with store.lock:
        if rec["status"] != "OPENED":
            raise err("ERR_CASE_NOT_OPENED")
        rec["assessed_penalty_cents"] = rec["alleged_penalty_cents"]
        rec["status"] = "CLOSED"
        touch(rec)
    return object_response(serialize(rec, "EnforcementCase"))


@app.route("/enforcement-cases/<case_id>/close", methods=["POST"])
def close_case(case_id):
    auth(["EnforcementOfficer"])
    rec = lookup("enforcement_cases", case_id)
    with store.lock:
        if rec["status"] != "HEARD":
            raise err("ERR_CASE_NOT_HEARD")
        rec["status"] = "CLOSED"
        touch(rec)
    return object_response(serialize(rec, "EnforcementCase"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress (a production WSGI server) when available. The Werkzeug
    # dev server drops connections / fails to bind cleanly when many servers are
    # rebooted concurrently (8 parallel rounds x per-test restart), surfacing as
    # ConnectionResetError / "could not be restarted". waitress handles concurrent
    # connections and clean startup far more reliably. Fall back to app.run if
    # waitress is not installed. No behavior/endpoint/response change either way.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
