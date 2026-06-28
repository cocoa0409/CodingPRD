"""Collectibles Grading & Authentication API — entry point and routes.

Python + Flask. In-memory store (db.py). Boots empty; seeds nothing.
"""
import os

from flask import Flask, request

import db
import clock
import calculations as calc
import serializers as ser
import services as svc
from errors import ApiError, err
from middleware import get_identity, require_roles, parse_pagination, paginate
from response import success, list_response, error_response
import validation as v

app = Flask(__name__)
app.url_map.strict_slashes = False


# =============================================================================
# Error handling
# =============================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed.")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 400, str(e))


# =============================================================================
# Lookups with existence enforcement (PRD §2.5 — left-to-right, ERR_NOT_FOUND)
# =============================================================================
def must(store, _id):
    rec = store.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist.")
    return rec


# =============================================================================
# Customers
# =============================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    # Anonymous-permitted: no auth required (PRD §2.1).
    with db.lock:
        body = v.get_body()
        email = v.require_string(body, "email")
        full_name = v.require_string(body, "full_name")
        # Unique email across customers.
        for c in db.customers.values():
            if c["email"] == email:
                raise err("ERR_VALIDATION", "email must be unique.")
        rec = db.stamp_create(
            {
                "email": email,
                "full_name": full_name,
                "store_credit_cents": 0,
            }
        )
        db.customers[rec["id"]] = rec
        return success(ser.customer(rec), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = get_identity()
    require_roles(role, {"Customer", "LabAdmin"})
    rec = must(db.customers, cid)
    return success(ser.customer(rec), 200)


# =============================================================================
# Service Levels
# =============================================================================
@app.route("/service-levels", methods=["POST"])
def create_service_level():
    _, role = get_identity()
    require_roles(role, {"LabAdmin"})
    with db.lock:
        body = v.get_body()
        code = v.require_string(body, "code")
        turnaround = v.require_int(body, "turnaround_business_days")
        base_fee = v.require_int(body, "base_fee_cents")
        max_dv = v.require_int(body, "max_declared_value_cents")
        rate = v.require_int(body, "insurance_rate_bps")
        active = v.optional_bool(body, "active", default=True)

        if turnaround < 1:
            raise err("ERR_VALIDATION", "turnaround_business_days must be >= 1.")
        if base_fee < 0:
            raise err("ERR_VALIDATION", "base_fee_cents must be >= 0.")
        if max_dv < 1:
            raise err("ERR_VALIDATION", "max_declared_value_cents must be >= 1.")
        if rate < 0:
            raise err("ERR_VALIDATION", "insurance_rate_bps must be >= 0.")
        for sl in db.service_levels.values():
            if sl["code"] == code:
                raise err("ERR_VALIDATION", "code must be unique.")

        rec = db.stamp_create(
            {
                "code": code,
                "turnaround_business_days": turnaround,
                "base_fee_cents": base_fee,
                "max_declared_value_cents": max_dv,
                "insurance_rate_bps": rate,
                "active": active,
            }
        )
        db.service_levels[rec["id"]] = rec
        return success(ser.service_level(rec), 201)


@app.route("/service-levels/<sid>", methods=["GET"])
def get_service_level(sid):
    _, role = get_identity()
    require_roles(role, {"LabAdmin", "Customer"})
    rec = must(db.service_levels, sid)
    return success(ser.service_level(rec), 200)


@app.route("/service-levels", methods=["GET"])
def list_service_levels():
    _, role = get_identity()
    require_roles(role, {"LabAdmin", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.service_levels.values())
    active_filter = request.args.get("active")
    if active_filter is not None:
        want = active_filter.lower() == "true"
        items = [s for s in items if s["active"] == want]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.service_level(r) for r in page], limit, offset, total)


# =============================================================================
# Grading Standards
# =============================================================================
@app.route("/grading-standards", methods=["POST"])
def create_grading_standard():
    _, role = get_identity()
    require_roles(role, {"LabAdmin"})
    with db.lock:
        body = v.get_body()
        code = v.require_string(body, "code")
        max_grade = v.require_number(body, "max_grade")
        authentic_min = v.require_number(body, "authentic_min_grade")
        cW = v.require_int(body, "centering_weight_bps")
        coW = v.require_int(body, "corners_weight_bps")
        eW = v.require_int(body, "edges_weight_bps")
        sW = v.require_int(body, "surface_weight_bps")

        if max_grade <= 0:
            raise err("ERR_VALIDATION", "max_grade must be > 0.")
        if authentic_min <= 0 or authentic_min > max_grade:
            raise err("ERR_VALIDATION", "authentic_min_grade must be > 0 and <= max_grade.")
        if cW < 0 or coW < 0 or eW < 0 or sW < 0:
            raise err("ERR_VALIDATION", "weights must be >= 0.")
        for sl in db.grading_standards.values():
            if sl["code"] == code:
                raise err("ERR_VALIDATION", "code must be unique.")
        # Weight normalization (priority 10).
        if cW + coW + eW + sW != 10000:
            raise err("ERR_WEIGHTS_NOT_NORMALIZED", "Weights must sum to 10000 bps.")

        rec = db.stamp_create(
            {
                "code": code,
                "max_grade": max_grade,
                "authentic_min_grade": authentic_min,
                "centering_weight_bps": cW,
                "corners_weight_bps": coW,
                "edges_weight_bps": eW,
                "surface_weight_bps": sW,
            }
        )
        db.grading_standards[rec["id"]] = rec
        return success(ser.grading_standard(rec), 201)


@app.route("/grading-standards/<gid>", methods=["GET"])
def get_grading_standard(gid):
    _, role = get_identity()
    require_roles(role, {"LabAdmin", "Grader", "Customer"})
    rec = must(db.grading_standards, gid)
    return success(ser.grading_standard(rec), 200)


# =============================================================================
# Submissions
# =============================================================================
@app.route("/submissions", methods=["POST"])
def create_submission():
    uid, role = get_identity()
    require_roles(role, {"Customer"})
    with db.lock:
        body = v.get_body()
        customer_id = v.require_string(body, "customer_id")
        service_level_id = v.require_string(body, "service_level_id")
        # Existence (left to right): customer then service level.
        must(db.customers, customer_id)
        must(db.service_levels, service_level_id)
        # Ownership: a Customer creates submissions for themselves.
        if customer_id != uid:
            raise err("ERR_NOT_OWNER", "Customer may only create own submissions.")
        rec = db.stamp_create(
            {
                "customer_id": customer_id,
                "service_level_id": service_level_id,
                "status": "DRAFT",
                "item_count": 0,
                "total_estimated_fee_cents": 0,
                "total_final_fee_cents": 0,
            }
        )
        db.submissions[rec["id"]] = rec
        return success(ser.submission(rec), 201)


@app.route("/submissions/<sid>", methods=["GET"])
def get_submission(sid):
    _, role = get_identity()
    require_roles(role, {"Customer", "LabAdmin", "Receiver", "Grader", "Authenticator"})
    rec = must(db.submissions, sid)
    return success(ser.submission(rec), 200)


@app.route("/submissions", methods=["GET"])
def list_submissions():
    _, role = get_identity()
    require_roles(role, {"Customer", "LabAdmin"})
    limit, offset = parse_pagination()
    items = list(db.submissions.values())
    customer_id = request.args.get("customer_id")
    service_level_id = request.args.get("service_level_id")
    status = request.args.get("status")
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    if service_level_id is not None:
        items = [s for s in items if s["service_level_id"] == service_level_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.submission(r) for r in page], limit, offset, total)


@app.route("/submissions/<sid>/submit", methods=["POST"])
def submit_submission(sid):
    uid, role = get_identity()
    require_roles(role, {"Customer"})
    with db.lock:
        sub = must(db.submissions, sid)
        # Ownership (priority 4).
        if sub["customer_id"] != uid:
            raise err("ERR_NOT_OWNER", "Only the owning customer may submit.")
        # State (priority 5): must be DRAFT.
        if sub["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Submission is not in DRAFT.")
        items = svc.items_of_submission(sid)
        # Empty-submission check evaluated first (PRD §3.2).
        if len(items) < 1:
            raise err("ERR_EMPTY_SUBMISSION", "Submission has no items.")
        service_level = db.service_levels[sub["service_level_id"]]
        cap = service_level["max_declared_value_cents"]
        # Declared-value tier cap.
        for it in items:
            if it["declared_value_cents"] > cap:
                raise err(
                    "ERR_DECLARED_VALUE_EXCEEDS_TIER",
                    "Item declared value exceeds tier cap.",
                )
        # Advance DRAFT -> SUBMITTED; freeze items.
        # Pin per-item estimate then sum (ceil-then-sum) (PRD §3.8).
        total_est = 0
        for it in items:
            est = calc.estimate_item_fee(it["declared_value_cents"], service_level)
            it["estimated_fee_cents"] = est
            db.touch(it)
            total_est += est
        sub["status"] = "SUBMITTED"
        sub["total_estimated_fee_cents"] = total_est
        db.touch(sub)
        # Create InsurancePolicy (PRD §3.9).
        covered, premium = calc.covered_value(items, service_level)
        policy = db.stamp_create(
            {
                "submission_id": sid,
                "covered_value_cents": covered,
                "premium_cents": premium,
                "claim_status": "NONE",
                "payout_cents": 0,
            }
        )
        db.insurance_policies[policy["id"]] = policy
        return success(ser.submission(sub), 200)


@app.route("/submissions/<sid>/close", methods=["POST"])
def close_submission(sid):
    _, role = get_identity()
    require_roles(role, {"LabAdmin"})
    with db.lock:
        sub = must(db.submissions, sid)
        if sub["status"] != "SHIPPED":
            raise err("ERR_INVALID_STATE", "Submission is not SHIPPED.")
        # Closure requires the shipment to have reached DELIVERED.
        ships = [s for s in db.shipments.values() if s["submission_id"] == sid]
        if not any(s["status"] == "DELIVERED" for s in ships):
            raise err("ERR_INVALID_STATE", "Shipment has not been DELIVERED.")
        sub["status"] = "CLOSED"
        db.touch(sub)
        return success(ser.submission(sub), 200)


# =============================================================================
# Submission Items
# =============================================================================
@app.route("/submissions/<sid>/items", methods=["POST"])
def add_item(sid):
    uid, role = get_identity()
    require_roles(role, {"Customer"})
    with db.lock:
        sub = must(db.submissions, sid)
        body = v.get_body()
        grading_standard_id = v.require_string(body, "grading_standard_id")
        title = v.require_string(body, "title")
        declared_value = v.require_int(body, "declared_value_cents")
        # Existence of FK referenced in body.
        must(db.grading_standards, grading_standard_id)
        # Ownership.
        if sub["customer_id"] != uid:
            raise err("ERR_NOT_OWNER", "Only the owning customer may add items.")
        # Frozen check: items only added while DRAFT.
        if sub["status"] != "DRAFT":
            raise err("ERR_SUBMISSION_FROZEN", "Submission is not in DRAFT.")
        if declared_value < 1:
            raise err("ERR_VALIDATION", "declared_value_cents must be >= 1.")
        rec = db.stamp_create(
            {
                "submission_id": sid,
                "grading_standard_id": grading_standard_id,
                "title": title,
                "declared_value_cents": declared_value,
                "status": "REGISTERED",
                "estimated_fee_cents": 0,
                "final_fee_cents": 0,
                "regrade_count": 0,
                "current_grade": None,
            }
        )
        db.submission_items[rec["id"]] = rec
        sub["item_count"] += 1
        db.touch(sub)
        return success(ser.submission_item(rec), 201)


@app.route("/submissions/<sid>/items", methods=["GET"])
def list_submission_items_of_sub(sid):
    _, role = get_identity()
    require_roles(role, {"Customer", "LabAdmin", "Receiver", "Grader", "Authenticator"})
    must(db.submissions, sid)
    limit, offset = parse_pagination()
    items = svc.items_of_submission(sid)
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.submission_item(r) for r in page], limit, offset, total)


@app.route("/submission-items", methods=["GET"])
def list_submission_items():
    _, role = get_identity()
    require_roles(role, {"Customer", "LabAdmin", "Receiver", "Grader", "Authenticator"})
    limit, offset = parse_pagination()
    items = list(db.submission_items.values())
    submission_id = request.args.get("submission_id")
    grading_standard_id = request.args.get("grading_standard_id")
    status = request.args.get("status")
    if submission_id is not None:
        items = [it for it in items if it["submission_id"] == submission_id]
    if grading_standard_id is not None:
        items = [it for it in items if it["grading_standard_id"] == grading_standard_id]
    if status is not None:
        items = [it for it in items if it["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.submission_item(r) for r in page], limit, offset, total)


@app.route("/submission-items/<iid>", methods=["GET"])
def get_submission_item(iid):
    _, role = get_identity()
    require_roles(role, {"Customer", "LabAdmin", "Receiver", "Grader", "Authenticator"})
    rec = must(db.submission_items, iid)
    return success(ser.submission_item(rec), 200)


@app.route("/submission-items/<iid>", methods=["DELETE"])
def delete_submission_item(iid):
    uid, role = get_identity()
    require_roles(role, {"Customer"})
    with db.lock:
        item = must(db.submission_items, iid)
        sub = db.submissions[item["submission_id"]]
        # Ownership.
        if sub["customer_id"] != uid:
            raise err("ERR_NOT_OWNER", "Only the owning customer may remove items.")
        # Frozen check: only while DRAFT.
        if sub["status"] != "DRAFT":
            raise err("ERR_SUBMISSION_FROZEN", "Submission is not in DRAFT.")
        del db.submission_items[iid]
        sub["item_count"] -= 1
        db.touch(sub)
        return success({}, 204)


# =============================================================================
# Intake
# =============================================================================
@app.route("/submission-items/<iid>/intake", methods=["POST"])
def log_intake(iid):
    uid, role = get_identity()
    require_roles(role, {"Receiver"})
    with db.lock:
        item = must(db.submission_items, iid)
        body = v.get_body()
        condition_note = v.require_string(body, "condition_note", allow_empty=True)
        matches = v.require_bool(body, "matches_declaration")
        sub = db.submissions[item["submission_id"]]
        # Duplicate intake guard: a second intake attempt on the same item is
        # specifically ERR_DUPLICATE_INTAKE (PRD §3.3), taking precedence over the
        # generic REGISTERED state guard since such an item is no longer REGISTERED.
        if svc.intake_for_item(iid):
            raise err("ERR_DUPLICATE_INTAKE", "Intake already logged for this item.")
        # State: parent submission in {SUBMITTED, RECEIVING}; item REGISTERED.
        if item["status"] != "REGISTERED":
            raise err("ERR_INVALID_STATE", "Item is not REGISTERED.")
        if sub["status"] not in ("SUBMITTED", "RECEIVING"):
            raise err("ERR_INVALID_STATE", "Submission not in SUBMITTED/RECEIVING.")
        rec = db.stamp_create(
            {
                "item_id": iid,
                "received_by_user_id": uid,
                "condition_note": condition_note,
                "matches_declaration": matches,
                "received_at": clock.now_iso(),
            }
        )
        db.intake_records[rec["id"]] = rec
        # REGISTERED -> INTAKE_LOGGED.
        item["status"] = "INTAKE_LOGGED"
        db.touch(item)
        # Bubble up parent posture.
        svc.recompute_submission_status(sub)
        return success(ser.intake_record(rec), 201)


@app.route("/submission-items/<iid>/intake", methods=["GET"])
def list_intake(iid):
    _, role = get_identity()
    require_roles(role, {"Receiver", "LabAdmin", "Customer"})
    must(db.submission_items, iid)
    records = svc.intake_for_item(iid)
    records.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser.intake_record(r) for r in records], 10, 0, len(records))


@app.route("/submission-items/<iid>/reject", methods=["POST"])
def reject_item(iid):
    _, role = get_identity()
    require_roles(role, {"Receiver"})
    with db.lock:
        item = must(db.submission_items, iid)
        sub = db.submissions[item["submission_id"]]
        # State: must be INTAKE_LOGGED.
        if item["status"] != "INTAKE_LOGGED":
            raise err("ERR_INVALID_STATE", "Item is not INTAKE_LOGGED.")
        # Intake record exists and matches_declaration == false.
        records = svc.intake_for_item(iid)
        if not records or records[0]["matches_declaration"] is not False:
            raise err("ERR_INVALID_STATE", "Item declaration matches; cannot reject.")
        item["status"] = "REJECTED_RETURNED"
        db.touch(item)
        # Recompute insurance covered value to drop this item.
        service_level = db.service_levels[sub["service_level_id"]]
        svc.recompute_covered_value(sub, service_level)
        # Bubble up posture.
        svc.recompute_submission_status(sub)
        return success(ser.submission_item(item), 200)


# =============================================================================
# Grading
# =============================================================================
@app.route("/submission-items/<iid>/grade-assessments", methods=["POST"])
def create_grade_assessment(iid):
    _, role = get_identity()
    require_roles(role, {"Grader"})
    with db.lock:
        item = must(db.submission_items, iid)
        body = v.get_body()
        grading_standard_id = v.require_string(body, "grading_standard_id")
        centering = v.require_number(body, "centering_subgrade")
        corners = v.require_number(body, "corners_subgrade")
        edges = v.require_number(body, "edges_subgrade")
        surface = v.require_number(body, "surface_subgrade")
        std = must(db.grading_standards, grading_standard_id)
        sub = db.submissions[item["submission_id"]]
        # State: INTAKE_LOGGED (first grade) or CRACK_PENDING (regrade re-entry).
        if item["status"] not in ("INTAKE_LOGGED", "CRACK_PENDING"):
            raise err("ERR_INVALID_STATE", "Item not gradeable in current state.")
        if item["status"] == "INTAKE_LOGGED":
            records = svc.intake_for_item(iid)
            if not records or records[0]["matches_declaration"] is not True:
                raise err("ERR_INVALID_STATE", "Item intake does not match declaration.")
        regrade = None
        if item["status"] == "CRACK_PENDING":
            opens = svc.open_regrades_for_item(iid)
            if not opens:
                raise err("ERR_INVALID_STATE", "No open regrade request.")
            regrade = opens[0]
        # Subgrade range check.
        max_grade = std["max_grade"]
        for sg in (centering, corners, edges, surface):
            if sg < 0 or sg > max_grade:
                raise err("ERR_SUBGRADE_OUT_OF_RANGE", "Subgrade out of [0, max_grade].")
        provisional = calc.provisional_overall_grade(centering, corners, edges, surface, std)
        rec = db.stamp_create(
            {
                "item_id": iid,
                "grading_standard_id": grading_standard_id,
                "centering_subgrade": centering,
                "corners_subgrade": corners,
                "edges_subgrade": edges,
                "surface_subgrade": surface,
                "provisional_overall": provisional,
                "final_overall": None,
                "superseded": False,
            }
        )
        db.grade_assessments[rec["id"]] = rec
        # Item -> GRADING.
        item["status"] = "GRADING"
        # Regrade re-entry: complete the request, bump regrade_count.
        if regrade is not None:
            regrade["status"] = "COMPLETED"
            db.touch(regrade)
            item["regrade_count"] += 1
        db.touch(item)
        svc.recompute_submission_status(sub)
        return success(ser.grade_assessment(rec), 201)


@app.route("/submission-items/<iid>/grade-assessments", methods=["GET"])
def list_item_grade_assessments(iid):
    _, role = get_identity()
    require_roles(role, {"Grader", "Authenticator", "LabAdmin", "Customer"})
    must(db.submission_items, iid)
    limit, offset = parse_pagination()
    items = svc.assessments_for_item(iid)
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.grade_assessment(r) for r in page], limit, offset, total)


@app.route("/grade-assessments", methods=["GET"])
def list_grade_assessments():
    _, role = get_identity()
    require_roles(role, {"Grader", "Authenticator", "LabAdmin", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.grade_assessments.values())
    item_id = request.args.get("item_id")
    grading_standard_id = request.args.get("grading_standard_id")
    if item_id is not None:
        items = [a for a in items if a["item_id"] == item_id]
    if grading_standard_id is not None:
        items = [a for a in items if a["grading_standard_id"] == grading_standard_id]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.grade_assessment(r) for r in page], limit, offset, total)


@app.route("/grade-assessments/<aid>", methods=["GET"])
def get_grade_assessment(aid):
    _, role = get_identity()
    require_roles(role, {"Grader", "Authenticator", "LabAdmin", "Customer"})
    rec = must(db.grade_assessments, aid)
    return success(ser.grade_assessment(rec), 200)


@app.route("/grade-assessments/<aid>/finalize", methods=["POST"])
def finalize_grade_assessment(aid):
    _, role = get_identity()
    require_roles(role, {"Grader"})
    with db.lock:
        rec = must(db.grade_assessments, aid)
        std = db.grading_standards[rec["grading_standard_id"]]
        final = calc.final_overall_grade(
            rec["centering_subgrade"],
            rec["corners_subgrade"],
            rec["edges_subgrade"],
            rec["surface_subgrade"],
            std,
        )
        rec["final_overall"] = final
        db.touch(rec)
        # Update the item's current_grade to the latest finalized active grade.
        item = db.submission_items.get(rec["item_id"])
        if item is not None and not rec["superseded"]:
            item["current_grade"] = final
            db.touch(item)
        return success(ser.grade_assessment(rec), 200)


# =============================================================================
# Authentication
# =============================================================================
@app.route("/submission-items/<iid>/authentication", methods=["POST"])
def run_authentication(iid):
    uid, role = get_identity()
    require_roles(role, {"Authenticator"})
    with db.lock:
        item = must(db.submission_items, iid)
        body = v.get_body()
        verdict = v.require_enum(body, "verdict", {"GENUINE", "ALTERED", "COUNTERFEIT"})
        alteration_note = v.optional_string(body, "alteration_note", default=None)
        # State: GRADING with an unsuperseded assessment whose final_overall is set.
        if item["status"] != "GRADING":
            raise err("ERR_INVALID_STATE", "Item is not in GRADING.")
        assessment = svc.active_assessment(iid)
        if assessment is None or assessment["final_overall"] is None:
            raise err("ERR_INVALID_STATE", "No finalized active assessment.")
        # Alteration note required for ALTERED/COUNTERFEIT.
        if verdict in ("ALTERED", "COUNTERFEIT"):
            if alteration_note is None or alteration_note.strip() == "":
                raise err(
                    "ERR_ALTERATION_NOTE_REQUIRED",
                    "alteration_note required for ALTERED/COUNTERFEIT.",
                )
        else:
            alteration_note = None
        rec = db.stamp_create(
            {
                "item_id": iid,
                "authenticator_user_id": uid,
                "verdict": verdict,
                "alteration_note": alteration_note,
            }
        )
        db.authentication_checks[rec["id"]] = rec
        # GRADING -> AUTHENTICATED.
        item["status"] = "AUTHENTICATED"
        db.touch(item)
        return success(ser.authentication_check(rec), 201)


@app.route("/submission-items/<iid>/authentication", methods=["GET"])
def list_authentication(iid):
    _, role = get_identity()
    require_roles(role, {"Authenticator", "LabAdmin", "Customer"})
    must(db.submission_items, iid)
    records = svc.auth_checks_for_item(iid)
    records.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response(
        [ser.authentication_check(r) for r in records], 10, 0, len(records)
    )


# =============================================================================
# Encapsulation / Slabs
# =============================================================================
@app.route("/submission-items/<iid>/encapsulate", methods=["POST"])
def encapsulate(iid):
    _, role = get_identity()
    require_roles(role, {"Authenticator"})
    with db.lock:
        item = must(db.submission_items, iid)
        body = v.get_body()
        assessment_id = v.require_string(body, "assessment_id")
        assessment = must(db.grade_assessments, assessment_id)
        sub = db.submissions[item["submission_id"]]
        std = db.grading_standards[item["grading_standard_id"]]
        # State: AUTHENTICATED with an authentication check.
        if item["status"] != "AUTHENTICATED":
            raise err("ERR_INVALID_STATE", "Item is not AUTHENTICATED.")
        auth = svc.latest_auth_check(iid)
        if auth is None:
            raise err("ERR_INVALID_STATE", "No authentication check exists.")
        # Counterfeit cannot be encapsulated (priority 8).
        if auth["verdict"] == "COUNTERFEIT":
            raise err(
                "ERR_COUNTERFEIT_NOT_ENCAPSULATABLE",
                "Counterfeit item cannot be encapsulated.",
            )
        # Only one active slab per item (priority 11).
        if svc.active_slab(iid) is not None:
            raise err("ERR_ACTIVE_SLAB_EXISTS", "An active slab already exists.")
        # Compute label grade text from final_overall + verdict + authentic_min_grade.
        final_overall = assessment["final_overall"]
        authentic_min = std["authentic_min_grade"]
        label_text = calc.label_grade_text(final_overall, auth["verdict"], authentic_min)
        grade_value = calc.grade_value_for_bucket(
            final_overall, auth["verdict"], authentic_min
        )
        slab = db.stamp_create(
            {
                "item_id": iid,
                "cert_number": db.next_cert_number(),
                "assessment_id": assessment_id,
                "label_grade_text": label_text,
                "active": True,
            }
        )
        db.slabs[slab["id"]] = slab
        # Population census bump.
        title_key = calc.normalize_title_key(item["title"])
        svc.population_bump(item["grading_standard_id"], title_key, grade_value)
        # Finalize item fee.
        service_level = db.service_levels[sub["service_level_id"]]
        final_fee = calc.finalize_item_fee(
            item["declared_value_cents"], item["regrade_count"], service_level
        )
        item["final_fee_cents"] = final_fee
        item["status"] = "ENCAPSULATED"
        db.touch(item)
        # Add to submission total_final_fee_cents.
        sub["total_final_fee_cents"] += final_fee
        db.touch(sub)
        # Bubble up posture (may move to READY_TO_SHIP, recomputing final total).
        svc.recompute_submission_status(sub)
        return success(ser.slab(slab), 201)


@app.route("/submission-items/<iid>/slabs", methods=["GET"])
def list_item_slabs(iid):
    _, role = get_identity()
    require_roles(role, {"Authenticator", "LabAdmin", "Customer"})
    must(db.submission_items, iid)
    limit, offset = parse_pagination()
    items = svc.slabs_for_item(iid)
    active_filter = request.args.get("active")
    if active_filter is not None:
        want = active_filter.lower() == "true"
        items = [s for s in items if s["active"] == want]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.slab(r) for r in page], limit, offset, total)


@app.route("/slabs", methods=["GET"])
def list_slabs():
    _, role = get_identity()
    require_roles(role, {"Authenticator", "LabAdmin", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.slabs.values())
    item_id = request.args.get("item_id")
    assessment_id = request.args.get("assessment_id")
    active_filter = request.args.get("active")
    if item_id is not None:
        items = [s for s in items if s["item_id"] == item_id]
    if assessment_id is not None:
        items = [s for s in items if s["assessment_id"] == assessment_id]
    if active_filter is not None:
        want = active_filter.lower() == "true"
        items = [s for s in items if s["active"] == want]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.slab(r) for r in page], limit, offset, total)


@app.route("/slabs/<slid>", methods=["GET"])
def get_slab(slid):
    _, role = get_identity()
    require_roles(role, {"Authenticator", "LabAdmin", "Customer"})
    rec = must(db.slabs, slid)
    return success(ser.slab(rec), 200)


# =============================================================================
# Labels
# =============================================================================
@app.route("/slabs/<slid>/label", methods=["POST"])
def print_label(slid):
    _, role = get_identity()
    require_roles(role, {"Authenticator", "LabAdmin"})
    with db.lock:
        slab = must(db.slabs, slid)
        body = v.get_body()
        population_report_id = v.require_string(body, "population_report_id")
        bucket = must(db.population_reports, population_report_id)
        rec = {
            "id": db.new_id(),
            "created_at": clock.now_iso(),
            "slab_id": slid,
            "population_report_id": population_report_id,
            "printed_pop_count": bucket["pop_count"],
            "printed_at": clock.now_iso(),
        }
        db.labels[rec["id"]] = rec
        return success(ser.label(rec), 201)


@app.route("/slabs/<slid>/label", methods=["GET"])
def list_slab_labels(slid):
    _, role = get_identity()
    require_roles(role, {"Authenticator", "LabAdmin", "Customer"})
    must(db.slabs, slid)
    records = [l for l in db.labels.values() if l["slab_id"] == slid]
    records.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser.label(r) for r in records], 10, 0, len(records))


@app.route("/labels", methods=["GET"])
def list_labels():
    _, role = get_identity()
    require_roles(role, {"Authenticator", "LabAdmin", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.labels.values())
    slab_id = request.args.get("slab_id")
    population_report_id = request.args.get("population_report_id")
    if slab_id is not None:
        items = [l for l in items if l["slab_id"] == slab_id]
    if population_report_id is not None:
        items = [l for l in items if l["population_report_id"] == population_report_id]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.label(r) for r in page], limit, offset, total)


@app.route("/labels/<lid>", methods=["GET"])
def get_label(lid):
    _, role = get_identity()
    require_roles(role, {"Authenticator", "LabAdmin", "Customer"})
    rec = must(db.labels, lid)
    return success(ser.label(rec), 200)


# =============================================================================
# Population Reports
# =============================================================================
@app.route("/population-reports", methods=["GET"])
def list_population_reports():
    _, role = get_identity()
    require_roles(role, {"LabAdmin", "Customer", "Authenticator"})
    limit, offset = parse_pagination()
    items = list(db.population_reports.values())
    grading_standard_id = request.args.get("grading_standard_id")
    title_key = request.args.get("title_key")
    grade_value = request.args.get("grade_value")
    if grading_standard_id is not None:
        items = [b for b in items if b["grading_standard_id"] == grading_standard_id]
    if title_key is not None:
        items = [b for b in items if b["title_key"] == title_key]
    if grade_value is not None:
        try:
            gv = float(grade_value)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "grade_value must be numeric.")
        items = [b for b in items if float(b["grade_value"]) == gv]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.population_report(r) for r in page], limit, offset, total)


@app.route("/population-reports/<pid>", methods=["GET"])
def get_population_report(pid):
    _, role = get_identity()
    require_roles(role, {"LabAdmin", "Customer", "Authenticator"})
    rec = must(db.population_reports, pid)
    return success(ser.population_report(rec), 200)


# =============================================================================
# Insurance
# =============================================================================
@app.route("/submissions/<sid>/insurance-policy", methods=["GET"])
def get_insurance_policy(sid):
    _, role = get_identity()
    require_roles(role, {"Customer", "LabAdmin"})
    must(db.submissions, sid)
    policies = [p for p in db.insurance_policies.values() if p["submission_id"] == sid]
    policies.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response(
        [ser.insurance_policy(r) for r in policies], 10, 0, len(policies)
    )


# =============================================================================
# Regrade Requests (crack-and-regrade, OCC)
# =============================================================================
@app.route("/submission-items/<iid>/regrade-requests", methods=["POST"])
def create_regrade_request(iid):
    uid, role = get_identity()
    require_roles(role, {"Customer"})
    with db.lock:
        item = must(db.submission_items, iid)
        body = v.get_body()
        prior_slab_id = v.require_string(body, "prior_slab_id")
        expected_item_version = v.require_int(body, "expected_item_version")
        reason = v.require_string(body, "reason", allow_empty=True)
        # Existence of body FK.
        slab = must(db.slabs, prior_slab_id)
        sub = db.submissions[item["submission_id"]]
        # Ownership (priority 4).
        if sub["customer_id"] != uid:
            raise err("ERR_NOT_OWNER", "Only the owning customer may regrade.")
        # State (priority 5): item ENCAPSULATED with an active slab.
        if item["status"] != "ENCAPSULATED":
            raise err("ERR_INVALID_STATE", "Item is not ENCAPSULATED.")
        active = svc.active_slab(iid)
        if active is None or active["id"] != prior_slab_id or not slab["active"]:
            raise err("ERR_INVALID_STATE", "prior_slab_id is not the item's active slab.")
        # OCC (priority 6).
        if expected_item_version != item["version"]:
            raise err("ERR_STALE_ITEM_VERSION", "Stale item version.")
        # Temporal (priority 12): not after shipped.
        if sub["status"] in ("SHIPPED", "CLOSED"):
            raise err("ERR_SUBMISSION_ALREADY_SHIPPED", "Submission already shipped.")
        # Create request OPEN.
        rec = db.stamp_create(
            {
                "item_id": iid,
                "prior_slab_id": prior_slab_id,
                "expected_item_version": expected_item_version,
                "reason": reason,
                "status": "OPEN",
            }
        )
        db.regrade_requests[rec["id"]] = rec
        # Crack the prior slab.
        slab["active"] = False
        db.touch(slab)
        rec["status"] = "CRACKED"
        db.touch(rec)
        # Population decrement for the cracked slab's bucket.
        title_key = calc.normalize_title_key(item["title"])
        cracked_assessment = db.grade_assessments.get(slab["assessment_id"])
        if cracked_assessment is not None:
            auth = svc.latest_auth_check(iid)
            verdict = auth["verdict"] if auth else "GENUINE"
            std = db.grading_standards[item["grading_standard_id"]]
            grade_value = calc.grade_value_for_bucket(
                cracked_assessment["final_overall"], verdict, std["authentic_min_grade"]
            )
            svc.population_decrement(item["grading_standard_id"], title_key, grade_value)
        # Supersede the prior active assessment.
        prior = svc.active_assessment(iid)
        if prior is not None:
            prior["superseded"] = True
            db.touch(prior)
        # Increment item version, move to CRACK_PENDING.
        item["status"] = "CRACK_PENDING"
        db.touch(item)  # touch bumps version by 1
        # Bubble up posture back to IN_GRADING.
        svc.recompute_submission_status(sub)
        return success(ser.regrade_request(rec), 201)


@app.route("/submission-items/<iid>/regrade-requests", methods=["GET"])
def list_item_regrade_requests(iid):
    _, role = get_identity()
    require_roles(role, {"Customer", "LabAdmin", "Grader"})
    must(db.submission_items, iid)
    limit, offset = parse_pagination()
    items = [r for r in db.regrade_requests.values() if r["item_id"] == iid]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.regrade_request(r) for r in page], limit, offset, total)


@app.route("/regrade-requests", methods=["GET"])
def list_regrade_requests():
    _, role = get_identity()
    require_roles(role, {"Customer", "LabAdmin", "Grader"})
    limit, offset = parse_pagination()
    items = list(db.regrade_requests.values())
    item_id = request.args.get("item_id")
    prior_slab_id = request.args.get("prior_slab_id")
    if item_id is not None:
        items = [r for r in items if r["item_id"] == item_id]
    if prior_slab_id is not None:
        items = [r for r in items if r["prior_slab_id"] == prior_slab_id]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.regrade_request(r) for r in page], limit, offset, total)


@app.route("/regrade-requests/<rid>", methods=["GET"])
def get_regrade_request(rid):
    _, role = get_identity()
    require_roles(role, {"Customer", "LabAdmin", "Grader"})
    rec = must(db.regrade_requests, rid)
    return success(ser.regrade_request(rec), 200)


# =============================================================================
# Shipments
# =============================================================================
@app.route("/submissions/<sid>/shipments", methods=["POST"])
def create_shipment(sid):
    _, role = get_identity()
    require_roles(role, {"LabAdmin"})
    with db.lock:
        sub = must(db.submissions, sid)
        body = v.get_body()
        carrier = v.require_enum(body, "carrier", {"UPS", "FEDEX", "USPS"})
        tracking_number = v.require_string(body, "tracking_number", allow_empty=True)
        # State: parent must be READY_TO_SHIP.
        if sub["status"] != "READY_TO_SHIP":
            raise err("ERR_INVALID_STATE", "Submission is not READY_TO_SHIP.")
        policy = svc.policy_for_submission(sid)
        covered = policy["covered_value_cents"] if policy else 0
        rec = db.stamp_create(
            {
                "submission_id": sid,
                "carrier": carrier,
                "tracking_number": tracking_number,
                "insured_value_cents": covered,
                "status": "LABEL_CREATED",
            }
        )
        db.shipments[rec["id"]] = rec
        return success(ser.shipment(rec), 201)


@app.route("/submissions/<sid>/shipments", methods=["GET"])
def list_shipments(sid):
    _, role = get_identity()
    require_roles(role, {"LabAdmin", "Customer"})
    must(db.submissions, sid)
    limit, offset = parse_pagination()
    items = [s for s in db.shipments.values() if s["submission_id"] == sid]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([ser.shipment(r) for r in page], limit, offset, total)


@app.route("/shipments/<shid>", methods=["GET"])
def get_shipment(shid):
    _, role = get_identity()
    require_roles(role, {"LabAdmin", "Customer"})
    rec = must(db.shipments, shid)
    return success(ser.shipment(rec), 200)


@app.route("/shipments/<shid>/dispatch", methods=["POST"])
def dispatch_shipment(shid):
    _, role = get_identity()
    require_roles(role, {"LabAdmin"})
    with db.lock:
        ship = must(db.shipments, shid)
        sub = db.submissions[ship["submission_id"]]
        # State: shipment LABEL_CREATED; submission READY_TO_SHIP.
        if ship["status"] != "LABEL_CREATED":
            raise err("ERR_INVALID_STATE", "Shipment is not LABEL_CREATED.")
        if sub["status"] != "READY_TO_SHIP":
            raise err("ERR_INVALID_STATE", "Submission is not READY_TO_SHIP.")
        ship["status"] = "IN_TRANSIT"
        # Re-copy insured_value from policy covered value.
        policy = svc.policy_for_submission(sub["id"])
        if policy is not None:
            ship["insured_value_cents"] = policy["covered_value_cents"]
        db.touch(ship)
        # Submission -> SHIPPED, all covered items -> SHIPPED.
        sub["status"] = "SHIPPED"
        db.touch(sub)
        for it in svc.items_of_submission(sub["id"]):
            if it["status"] in ("ENCAPSULATED", "REJECTED_RETURNED"):
                it["status"] = "SHIPPED"
                db.touch(it)
        return success(ser.shipment(ship), 200)


@app.route("/shipments/<shid>/deliver", methods=["POST"])
def deliver_shipment(shid):
    _, role = get_identity()
    require_roles(role, {"LabAdmin"})
    with db.lock:
        ship = must(db.shipments, shid)
        if ship["status"] != "IN_TRANSIT":
            raise err("ERR_INVALID_STATE", "Shipment is not IN_TRANSIT.")
        ship["status"] = "DELIVERED"
        db.touch(ship)
        return success(ser.shipment(ship), 200)


@app.route("/shipments/<shid>/report-lost", methods=["POST"])
def report_lost(shid):
    _, role = get_identity()
    require_roles(role, {"LabAdmin"})
    with db.lock:
        ship = must(db.shipments, shid)
        sub = db.submissions[ship["submission_id"]]
        if ship["status"] != "IN_TRANSIT":
            raise err("ERR_INVALID_STATE", "Shipment is not IN_TRANSIT.")
        ship["status"] = "LOST"
        db.touch(ship)
        # Insurance loss cascade (PRD §3.9).
        policy = svc.policy_for_submission(sub["id"])
        if policy is not None:
            policy["claim_status"] = "FILED"
            payout = policy["covered_value_cents"]
            policy["payout_cents"] = payout
            policy["claim_status"] = "PAID"
            db.touch(policy)
            customer = db.customers.get(sub["customer_id"])
            if customer is not None:
                customer["store_credit_cents"] += payout
                db.touch(customer)
        return success(ser.shipment(ship), 200)


# =============================================================================
# Logical clock (test-driving)
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # LabAdmin or Anonymous; may be exercised without authentication (PRD §3.12).
    role = request.headers.get("X-User-Role")
    if role is not None and role not in ("LabAdmin", "Anonymous"):
        # If headers present, they must name an allowed role.
        uid = request.headers.get("X-User-ID")
        if not uid:
            raise err("ERR_UNAUTHENTICATED", "Missing headers.")
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted to set the clock.")
    body = v.get_body()
    to_iso = v.require_string(body, "to_iso8601")
    try:
        clock.set_now(to_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Invalid to_iso8601 value.")
    return success({}, 200)


# =============================================================================
# Boot
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
