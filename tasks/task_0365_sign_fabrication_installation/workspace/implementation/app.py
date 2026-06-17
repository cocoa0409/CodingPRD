"""Sign Fabrication & Installation API — Flask entry point.

In-memory storage only; nothing seeded at startup. Boots cleanly each invocation.
"""
import os
from flask import Flask, request, jsonify

from core import (
    db, err, ApiError, parse_iso,
    success_object, success_array, error_body,
)
from domain import (
    stamp_new, touch, serialize, price_estimate, equipment_class_required,
    reconcile_project, reconcile_estimate, reconcile_permit,
    MATERIAL_RATE, PERMIT_FEE, COVERAGE_DAYS, CREW_BUFFER_MIN,
    HANDS_MAX_FT, LADDER_MAX_FT, JURISDICTIONS, SIGN_TYPES, SUBSTRATES,
    PERMIT_KINDS, DEFECT_KINDS, EQUIPMENT_CLASSES,
)
import guards as G
from datetime import timedelta

app = Flask(__name__)


# ===========================================================================
# Error handling — uniform envelope
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed")), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return jsonify(error_body("ERR_INVALID_REQUEST", str(e))), 500


def reply(result):
    body, status = result
    return jsonify(body), status


# Helper: child resources of a project, sorted by creation order.
def children_of(collection, project_id):
    items = [e for e in collection.values() if e.get("sign_project_id") == project_id]
    items.sort(key=lambda x: x["_seq"])
    return items


def filtered_list(items, status=None):
    if status is not None:
        items = [e for e in items if e.get("status") == status]
    return items


def list_response(items, serializer=serialize):
    limit, offset = G.get_pagination()
    items = sorted(items, key=lambda x: x["_seq"])
    page, total = G.paginate(items, limit, offset)
    data = [serializer(e) for e in page]
    return reply(success_array(data, limit, offset, total))


# ===========================================================================
# Sign Projects
# ===========================================================================
@app.route("/sign-projects", methods=["POST"])
def create_project():
    G.require_role({"ShopManager"})
    body = G.get_body()
    customer_name = G.require_str(body, "customer_name")
    site_address = G.require_str(body, "site_address")
    jurisdiction = G.require_enum(body, "jurisdiction_code", JURISDICTIONS)
    sign_type = G.require_enum(body, "sign_type", SIGN_TYPES)
    fw = G.require_number(body, "face_width_in", positive=True)
    fh = G.require_number(body, "face_height_in", positive=True)
    ph = G.require_number(body, "placement_height_ft", non_negative=True)
    illuminated = G.optional_bool(body, "illuminated", False)
    rush = G.optional_bool(body, "rush", False)

    permit_required = (jurisdiction != "COUNTY_C") or illuminated

    p = {
        "customer_name": customer_name,
        "site_address": site_address,
        "jurisdiction_code": jurisdiction,
        "sign_type": sign_type,
        "face_width_in": fw,
        "face_height_in": fh,
        "placement_height_ft": ph,
        "illuminated": illuminated,
        "rush": rush,
        "phase": "DESIGN",
        "approved_estimate_id": None,
        "permit_required": permit_required,
        "contract_total_cents": 0,
    }
    stamp_new(p)
    db.sign_projects[p["id"]] = p
    return reply(success_object(serialize(p), 201))


@app.route("/sign-projects", methods=["GET"])
def list_projects():
    G.require_role({"ShopManager", "Designer", "Customer", "Surveyor", "PermitClerk"})
    phase = request.args.get("phase")
    approved_estimate_id = request.args.get("approved_estimate_id")
    items = list(db.sign_projects.values())
    for p in items:
        reconcile_project(p)
    if phase is not None:
        items = [p for p in items if p.get("phase") == phase]
    if approved_estimate_id is not None:
        items = [p for p in items if p.get("approved_estimate_id") == approved_estimate_id]
    return list_response(items)


@app.route("/sign-projects/<pid>", methods=["GET"])
def get_project_ep(pid):
    G.require_role({"ShopManager", "Designer", "Customer", "Surveyor", "PermitClerk"})
    p = G.get_project(pid)
    reconcile_project(p)
    return reply(success_object(serialize(p)))


@app.route("/sign-projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    G.require_role({"ShopManager"})
    p = G.get_project(pid)
    if p["phase"] not in ("DESIGN", "ESTIMATING", "PERMITTING"):
        raise err("ERR_INVALID_STATE", "Project cannot be cancelled from this phase")
    p["phase"] = "CANCELLED"
    touch(p)
    for proof in children_of(db.art_proofs, pid):
        if proof["status"] in ("DRAFT", "SUBMITTED"):
            proof["status"] = "SUPERSEDED"
            touch(proof)
    for est in children_of(db.estimates, pid):
        if est["status"] in ("DRAFT", "SENT"):
            est["status"] = "SUPERSEDED"
            touch(est)
    return reply(success_object(serialize(p)))


@app.route("/sign-projects/<pid>/close", methods=["POST"])
def close_project(pid):
    G.require_role({"ShopManager"})
    p = G.get_project(pid)
    if p["phase"] != "WARRANTY":
        raise err("ERR_INVALID_STATE", "Project can only be closed from WARRANTY")
    for claim in children_of(db.warranty_claims, pid):
        if claim["status"] in ("OPEN", "APPROVED"):
            raise err("ERR_OPEN_CLAIM", "Outstanding warranty claim prevents closing")
    p["phase"] = "CLOSED"
    touch(p)
    return reply(success_object(serialize(p)))


# ===========================================================================
# Art Proofs
# ===========================================================================
@app.route("/sign-projects/<pid>/art-proofs", methods=["POST"])
def create_proof(pid):
    G.require_role({"Designer"})
    p = G.get_project(pid)
    body = G.get_body()
    artwork_uri = G.require_str(body, "artwork_uri")
    color_count = G.require_int(body, "color_count", minimum=1)

    existing = children_of(db.art_proofs, pid)
    revision_no = (max([pr["revision_no"] for pr in existing]) + 1) if existing else 1

    proof = {
        "sign_project_id": pid,
        "revision_no": revision_no,
        "artwork_uri": artwork_uri,
        "color_count": color_count,
        "status": "DRAFT",
        "reject_reason": None,
    }
    stamp_new(proof)
    db.art_proofs[proof["id"]] = proof
    # A new revision supersedes any REJECTED proof of this project.
    for pr in existing:
        if pr["status"] == "REJECTED":
            pr["status"] = "SUPERSEDED"
            touch(pr)
    return reply(success_object(serialize(proof), 201))


@app.route("/sign-projects/<pid>/art-proofs", methods=["GET"])
def list_proofs(pid):
    G.require_role({"ShopManager", "Designer", "Customer"})
    G.get_project(pid)
    status = request.args.get("status")
    return list_response(filtered_list(children_of(db.art_proofs, pid), status))


@app.route("/sign-projects/<pid>/art-proofs/<proof_id>/submit", methods=["POST"])
def submit_proof(pid, proof_id):
    G.require_role({"Designer"})
    p = G.get_project(pid)
    proof = G.get_child(db.art_proofs, proof_id, pid)
    if proof["status"] != "DRAFT" or p["phase"] != "DESIGN":
        raise err("ERR_INVALID_STATE", "Proof not in DRAFT or project not in DESIGN")
    proof["status"] = "SUBMITTED"
    touch(proof)
    return reply(success_object(serialize(proof)))


@app.route("/sign-projects/<pid>/art-proofs/<proof_id>/decision", methods=["POST"])
def decide_proof(pid, proof_id):
    G.require_role({"Customer"})
    p = G.get_project(pid)
    proof = G.get_child(db.art_proofs, proof_id, pid)
    body = G.get_body()
    decision = G.require_enum(body, "decision", {"APPROVE", "REJECT"})
    if proof["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Proof is not SUBMITTED")
    if decision == "APPROVE":
        for pr in children_of(db.art_proofs, pid):
            if pr["id"] != proof_id and pr["status"] == "APPROVED":
                raise err("ERR_PROOF_ALREADY_APPROVED", "Another proof is already approved")
        proof["status"] = "APPROVED"
        touch(proof)
        if p["phase"] == "DESIGN":
            p["phase"] = "ESTIMATING"
            touch(p)
    else:
        reject_reason = body.get("reject_reason")
        if reject_reason is not None and not isinstance(reject_reason, str):
            G.invalid("reject_reason must be a string")
        proof["status"] = "REJECTED"
        proof["reject_reason"] = reject_reason
        touch(proof)
    return reply(success_object(serialize(proof)))


# ===========================================================================
# Estimates
# ===========================================================================
@app.route("/sign-projects/<pid>/estimates", methods=["POST"])
def create_estimate(pid):
    G.require_role({"ShopManager"})
    p = G.get_project(pid)
    body = G.get_body()
    art_proof_id = G.require_str(body, "art_proof_id")
    substrate = G.require_enum(body, "substrate", SUBSTRATES)
    valid_until = G.require_datetime(body, "valid_until_iso")

    # referential eligibility: the referenced proof must be an APPROVED proof of this project
    proof = db.art_proofs.get(art_proof_id)
    if proof is None or proof.get("sign_project_id") != pid or proof.get("status") != "APPROVED":
        raise err("ERR_REFERENCE_NOT_ELIGIBLE", "Referenced art proof is not an APPROVED proof of this project")

    priced = price_estimate(
        p["face_width_in"], p["face_height_in"], substrate,
        proof["color_count"], p["illuminated"], p["rush"],
    )
    est = {
        "sign_project_id": pid,
        "art_proof_id": art_proof_id,
        "substrate": substrate,
        "valid_until_iso": valid_until,
        "status": "DRAFT",
    }
    est.update(priced)
    stamp_new(est)
    db.estimates[est["id"]] = est
    return reply(success_object(serialize(est), 201))


@app.route("/sign-projects/<pid>/estimates", methods=["GET"])
def list_estimates(pid):
    G.require_role({"ShopManager", "Customer"})
    G.get_project(pid)
    items = children_of(db.estimates, pid)
    for est in items:
        reconcile_estimate(est)
    status = request.args.get("status")
    return list_response(filtered_list(items, status))


@app.route("/sign-projects/<pid>/estimates/<eid>/send", methods=["POST"])
def send_estimate(pid, eid):
    G.require_role({"ShopManager"})
    G.get_project(pid)
    est = G.get_child(db.estimates, eid, pid)
    if est["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Estimate is not DRAFT")
    est["status"] = "SENT"
    touch(est)
    return reply(success_object(serialize(est)))


@app.route("/sign-projects/<pid>/estimates/<eid>/accept", methods=["POST"])
def accept_estimate(pid, eid):
    G.require_role({"Customer"})
    p = G.get_project(pid)
    est = G.get_child(db.estimates, eid, pid)
    body = G.get_body()
    # expected_sign_project_version is mandatory
    expected = body.get("expected_sign_project_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        G.invalid("expected_sign_project_version is required")

    # lazy-expire before the state check
    reconcile_estimate(est)
    if est["status"] not in ("SENT", "EXPIRED"):
        raise err("ERR_INVALID_STATE", "Estimate is not SENT")
    # business: expiry check
    vu = parse_iso(est.get("valid_until_iso"))
    if est["status"] == "EXPIRED" or (vu is not None and db.now() >= vu):
        if est["status"] == "SENT":
            est["status"] = "EXPIRED"
            touch(est)
        raise err("ERR_ESTIMATE_EXPIRED", "Estimate has expired")
    # already-accepted check
    for other in children_of(db.estimates, pid):
        if other["id"] != eid and other["status"] == "ACCEPTED":
            raise err("ERR_ESTIMATE_ALREADY_ACCEPTED", "Another estimate is already accepted")
    # OCC last
    if expected != p["version"]:
        raise err("ERR_STALE_VERSION", "Project version is stale")

    est["status"] = "ACCEPTED"
    touch(est)
    # supersede other SENT/DRAFT estimates
    for other in children_of(db.estimates, pid):
        if other["id"] != eid and other["status"] in ("SENT", "DRAFT"):
            other["status"] = "SUPERSEDED"
            touch(other)
    p["approved_estimate_id"] = eid
    p["contract_total_cents"] = est["total_cents"]
    if p["phase"] == "ESTIMATING":
        p["phase"] = "PERMITTING"
    touch(p)
    return reply(success_object(serialize(est)))


@app.route("/sign-projects/<pid>/estimates/<eid>/decline", methods=["POST"])
def decline_estimate(pid, eid):
    G.require_role({"Customer"})
    G.get_project(pid)
    est = G.get_child(db.estimates, eid, pid)
    reconcile_estimate(est)
    if est["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Estimate is not SENT")
    est["status"] = "DECLINED"
    touch(est)
    return reply(success_object(serialize(est)))


# ===========================================================================
# Site Surveys
# ===========================================================================
@app.route("/sign-projects/<pid>/site-surveys", methods=["POST"])
def create_survey(pid):
    G.require_role({"Surveyor"})
    G.get_project(pid)
    body = G.get_body()
    clearance = G.require_number(body, "measured_clearance_ft", non_negative=True)
    overhead = G.require_bool(body, "overhead_obstruction")
    ground_ok = G.require_bool(body, "ground_bearing_ok")
    survey = {
        "sign_project_id": pid,
        "measured_clearance_ft": clearance,
        "overhead_obstruction": overhead,
        "ground_bearing_ok": ground_ok,
        "status": "PENDING",
    }
    stamp_new(survey)
    db.site_surveys[survey["id"]] = survey
    return reply(success_object(serialize(survey), 201))


@app.route("/sign-projects/<pid>/site-surveys", methods=["GET"])
def list_surveys(pid):
    G.require_role({"ShopManager", "Surveyor"})
    G.get_project(pid)
    status = request.args.get("status")
    return list_response(filtered_list(children_of(db.site_surveys, pid), status))


@app.route("/sign-projects/<pid>/site-surveys/<sid>/decide", methods=["POST"])
def decide_survey(pid, sid):
    G.require_role({"Surveyor"})
    p = G.get_project(pid)
    survey = G.get_child(db.site_surveys, sid, pid)
    body = G.get_body()
    result = G.require_enum(body, "result", {"PASS", "FAIL"})
    if survey["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Survey is not PENDING")
    if result == "PASS":
        if survey["measured_clearance_ft"] < p["placement_height_ft"]:
            raise err("ERR_CLEARANCE_INSUFFICIENT", "Measured clearance below placement height")
        if p["sign_type"] in ("MONUMENT", "PYLON") and not survey["ground_bearing_ok"]:
            raise err("ERR_GROUND_BEARING_FAILED", "Ground bearing not confirmed for MONUMENT/PYLON")
        survey["status"] = "PASSED"
    else:
        survey["status"] = "FAILED"
    touch(survey)
    return reply(success_object(serialize(survey)))


# ===========================================================================
# Permits
# ===========================================================================
@app.route("/sign-projects/<pid>/permits", methods=["POST"])
def create_permit(pid):
    G.require_role({"PermitClerk"})
    p = G.get_project(pid)
    body = G.get_body()
    permit_kind = G.require_enum(body, "permit_kind", PERMIT_KINDS)
    expires_iso = G.optional_datetime(body, "expires_iso")
    fee = PERMIT_FEE[p["jurisdiction_code"]][permit_kind]
    permit = {
        "sign_project_id": pid,
        "permit_kind": permit_kind,
        "fee_cents": fee,
        "status": "DRAFT",
        "expires_iso": expires_iso,
    }
    stamp_new(permit)
    db.permits[permit["id"]] = permit
    return reply(success_object(serialize(permit), 201))


@app.route("/sign-projects/<pid>/permits", methods=["GET"])
def list_permits(pid):
    G.require_role({"ShopManager", "PermitClerk"})
    G.get_project(pid)
    items = children_of(db.permits, pid)
    for permit in items:
        reconcile_permit(permit)
    status = request.args.get("status")
    return list_response(filtered_list(items, status))


@app.route("/sign-projects/<pid>/permits/<permit_id>/submit", methods=["POST"])
def submit_permit(pid, permit_id):
    G.require_role({"PermitClerk"})
    p = G.get_project(pid)
    permit = G.get_child(db.permits, permit_id, pid)
    if permit["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Permit is not DRAFT")
    if not p["permit_required"]:
        raise err("ERR_PERMIT_NOT_REQUIRED", "Project does not require permits")
    permit["status"] = "SUBMITTED"
    touch(permit)
    return reply(success_object(serialize(permit)))


@app.route("/sign-projects/<pid>/permits/<permit_id>/decide", methods=["POST"])
def decide_permit(pid, permit_id):
    G.require_role({"PermitClerk"})
    G.get_project(pid)
    permit = G.get_child(db.permits, permit_id, pid)
    body = G.get_body()
    decision = G.require_enum(body, "decision", {"APPROVE", "DENY"})
    if permit["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Permit is not SUBMITTED")
    permit["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    touch(permit)
    return reply(success_object(serialize(permit)))


# ===========================================================================
# Fabrication Work Orders
# ===========================================================================
def _required_permit_kinds(p):
    """Which permit kinds must be APPROVED for release."""
    kinds = set()
    if p["jurisdiction_code"] != "COUNTY_C":
        kinds.add("STRUCTURAL")
    if p["illuminated"]:
        kinds.add("ELECTRICAL")
    # If permit_required but no structural needed (illuminated COUNTY_C), at least ELECTRICAL.
    return kinds


@app.route("/sign-projects/<pid>/fabrication-work-orders", methods=["POST"])
def release_work_order(pid):
    G.require_role({"ShopManager"})
    p = G.get_project(pid)
    if p["phase"] != "PERMITTING":
        raise err("ERR_INVALID_STATE", "Project is not in PERMITTING")
    # survey gate
    surveys = children_of(db.site_surveys, pid)
    if not any(s["status"] == "PASSED" for s in surveys):
        raise err("ERR_SURVEY_NOT_PASSED", "No passed site survey for project")
    # permit gate
    if p["permit_required"]:
        permits = children_of(db.permits, pid)
        for permit in permits:
            reconcile_permit(permit)
        required = _required_permit_kinds(p)
        for kind in required:
            ok = any(pm["permit_kind"] == kind and pm["status"] == "APPROVED" for pm in permits)
            if not ok:
                raise err("ERR_PERMIT_NOT_APPROVED", "Required permit %s is not approved" % kind)

    est_id = p["approved_estimate_id"]
    est = db.estimates.get(est_id)
    wo = {
        "sign_project_id": pid,
        "estimate_id": est_id,
        "snapshot_total_cents": est["total_cents"] if est else 0,
        "status": "RELEASED",
        "qc_pass": None,
    }
    stamp_new(wo)
    db.work_orders[wo["id"]] = wo
    p["phase"] = "FABRICATION"
    touch(p)
    return reply(success_object(serialize(wo), 201))


@app.route("/sign-projects/<pid>/fabrication-work-orders", methods=["GET"])
def list_work_orders(pid):
    G.require_role({"ShopManager"})
    G.get_project(pid)
    status = request.args.get("status")
    return list_response(filtered_list(children_of(db.work_orders, pid), status))


@app.route("/sign-projects/<pid>/fabrication-work-orders/<wid>/start", methods=["POST"])
def start_work_order(pid, wid):
    G.require_role({"ShopManager"})
    G.get_project(pid)
    wo = G.get_child(db.work_orders, wid, pid)
    if wo["status"] != "RELEASED":
        raise err("ERR_INVALID_STATE", "Work order is not RELEASED")
    wo["status"] = "IN_PRODUCTION"
    touch(wo)
    return reply(success_object(serialize(wo)))


@app.route("/sign-projects/<pid>/fabrication-work-orders/<wid>/qc-hold", methods=["POST"])
def qc_hold_work_order(pid, wid):
    G.require_role({"ShopManager"})
    G.get_project(pid)
    wo = G.get_child(db.work_orders, wid, pid)
    if wo["status"] != "IN_PRODUCTION":
        raise err("ERR_INVALID_STATE", "Work order is not IN_PRODUCTION")
    wo["status"] = "QC_HOLD"
    touch(wo)
    return reply(success_object(serialize(wo)))


@app.route("/sign-projects/<pid>/fabrication-work-orders/<wid>/qc-decide", methods=["POST"])
def qc_decide_work_order(pid, wid):
    G.require_role({"ShopManager"})
    p = G.get_project(pid)
    wo = G.get_child(db.work_orders, wid, pid)
    body = G.get_body()
    qc_pass = G.require_bool(body, "qc_pass")
    if wo["status"] != "QC_HOLD":
        raise err("ERR_INVALID_STATE", "Work order is not on QC_HOLD")
    wo["qc_pass"] = qc_pass
    if qc_pass:
        wo["status"] = "READY_FOR_INSTALL"
        touch(wo)
        if p["phase"] == "FABRICATION":
            p["phase"] = "INSTALL"
            touch(p)
    else:
        wo["status"] = "IN_PRODUCTION"
        touch(wo)
    return reply(success_object(serialize(wo)))


@app.route("/sign-projects/<pid>/fabrication-work-orders/<wid>/cancel", methods=["POST"])
def cancel_work_order(pid, wid):
    G.require_role({"ShopManager"})
    p = G.get_project(pid)
    wo = G.get_child(db.work_orders, wid, pid)
    if wo["status"] not in ("RELEASED", "IN_PRODUCTION", "QC_HOLD"):
        raise err("ERR_INVALID_STATE", "Work order cannot be cancelled from this state")
    wo["status"] = "CANCELLED"
    touch(wo)
    if p["phase"] == "FABRICATION":
        p["phase"] = "CANCELLED"
        touch(p)
    return reply(success_object(serialize(wo)))


# ===========================================================================
# Crews & Equipment
# ===========================================================================
@app.route("/crews", methods=["POST"])
def create_crew():
    G.require_role({"ShopManager"})
    body = G.get_body()
    name = G.require_str(body, "name")
    certified = G.optional_bool(body, "certified_aerial", False)
    active = G.optional_bool(body, "active", True)
    crew = {"name": name, "certified_aerial": certified, "active": active}
    stamp_new(crew)
    db.crews[crew["id"]] = crew
    return reply(success_object(serialize(crew), 201))


@app.route("/crews/<cid>", methods=["GET"])
def get_crew(cid):
    G.require_role({"ShopManager"})
    crew = db.crews.get(cid)
    if crew is None:
        raise err("ERR_NOT_FOUND", "Crew not found")
    return reply(success_object(serialize(crew)))


@app.route("/crews/<cid>", methods=["PATCH"])
def update_crew(cid):
    G.require_role({"ShopManager"})
    crew = db.crews.get(cid)
    if crew is None:
        raise err("ERR_NOT_FOUND", "Crew not found")
    body = G.get_body()
    if "certified_aerial" in body:
        crew["certified_aerial"] = G.require_bool(body, "certified_aerial")
    if "active" in body:
        crew["active"] = G.require_bool(body, "active")
    touch(crew)
    return reply(success_object(serialize(crew)))


@app.route("/equipment", methods=["POST"])
def create_equipment():
    G.require_role({"ShopManager"})
    body = G.get_body()
    asset_tag = G.require_str(body, "asset_tag")
    equipment_class = G.require_enum(body, "equipment_class", EQUIPMENT_CLASSES)
    max_reach = G.require_number(body, "max_reach_ft", positive=True)
    in_service = G.optional_bool(body, "in_service", True)
    eq = {
        "asset_tag": asset_tag,
        "equipment_class": equipment_class,
        "max_reach_ft": max_reach,
        "in_service": in_service,
    }
    stamp_new(eq)
    db.equipment[eq["id"]] = eq
    return reply(success_object(serialize(eq), 201))


@app.route("/equipment/<eqid>", methods=["GET"])
def get_equipment(eqid):
    G.require_role({"ShopManager"})
    eq = db.equipment.get(eqid)
    if eq is None:
        raise err("ERR_NOT_FOUND", "Equipment not found")
    return reply(success_object(serialize(eq)))


# ===========================================================================
# Install Jobs
# ===========================================================================
def _active_install_jobs():
    return [j for j in db.install_jobs.values() if j["status"] in ("SCHEDULED", "DISPATCHED")]


def _intervals_overlap_halfopen(a_start, a_end, b_start, b_end):
    # [start, end) overlap
    return a_start < b_end and b_start < a_end


def _crew_conflict(existing, new_start, new_end):
    """Same-day buffered closed-interval conflict for crews."""
    # same day in UTC
    if existing["_win_start"].date() != new_start.date():
        return False
    buffer = timedelta(minutes=CREW_BUFFER_MIN)
    e_start = existing["_win_start"]
    e_end = existing["_win_end"]
    # Conflict unless the new window sits entirely before or after the existing
    # window with at least the buffer gap between adjacent jobs.
    # Allowed (no conflict) iff: new_end + buffer <= e_start  OR  e_end + buffer <= new_start
    if new_end + buffer <= e_start:
        return False
    if e_end + buffer <= new_start:
        return False
    return True


@app.route("/sign-projects/<pid>/install-jobs", methods=["POST"])
def schedule_install(pid):
    G.require_role({"ShopManager"})
    p = G.get_project(pid)
    body = G.get_body()
    work_order_id = G.require_str(body, "work_order_id")
    crew_id = G.require_str(body, "crew_id")
    equipment_id = body.get("equipment_id")
    if equipment_id is not None and not isinstance(equipment_id, str):
        G.invalid("equipment_id must be a string")
    window_start = G.require_datetime(body, "window_start_iso")
    window_end = G.require_datetime(body, "window_end_iso")

    ws = parse_iso(window_start)
    we = parse_iso(window_end)
    if not (we > ws):
        G.invalid("window_end_iso must be strictly later than window_start_iso")

    # referential eligibility: WO must be READY_FOR_INSTALL of this project
    wo = db.work_orders.get(work_order_id)
    if wo is None or wo.get("sign_project_id") != pid or wo.get("status") != "READY_FOR_INSTALL":
        raise err("ERR_REFERENCE_NOT_ELIGIBLE", "Work order is not READY_FOR_INSTALL for this project")

    # crew existence (referenced FK) — treat missing as reference not eligible
    crew = db.crews.get(crew_id)
    if crew is None:
        raise err("ERR_REFERENCE_NOT_ELIGIBLE", "Crew does not exist")

    # derive required equipment class from latest PASSED survey obstruction
    overhead = _latest_passed_survey_obstruction(pid)
    required_class = equipment_class_required(p["placement_height_ft"], overhead)

    equipment = None
    if required_class != "NONE":
        if not equipment_id:
            raise err("ERR_EQUIPMENT_REQUIRED", "equipment_id is required for this job")
        equipment = db.equipment.get(equipment_id)
        if equipment is None:
            raise err("ERR_EQUIPMENT_REQUIRED", "Equipment does not exist")
        if required_class == "BUCKET_TRUCK":
            if equipment["equipment_class"] != "BUCKET_TRUCK" or equipment["max_reach_ft"] < p["placement_height_ft"]:
                raise err("ERR_EQUIPMENT_REQUIRED", "Equipment class/reach insufficient")
        elif required_class == "LADDER":
            if equipment["max_reach_ft"] < p["placement_height_ft"]:
                raise err("ERR_EQUIPMENT_REQUIRED", "Equipment reach insufficient")
    else:
        if equipment_id:
            equipment = db.equipment.get(equipment_id)
            if equipment is None:
                raise err("ERR_EQUIPMENT_REQUIRED", "Equipment does not exist")

    # equipment double-booking (priority 9): half-open overlap on active jobs
    if equipment is not None:
        for j in _active_install_jobs():
            if j.get("equipment_id") == equipment["id"]:
                if _intervals_overlap_halfopen(ws, we, j["_win_start"], j["_win_end"]):
                    raise err("ERR_EQUIPMENT_DOUBLE_BOOKED", "Equipment already booked for an overlapping window")

    # crew double-booking (priority 10): same-day buffered conflict on active jobs
    for j in _active_install_jobs():
        if j.get("crew_id") == crew_id:
            if _crew_conflict(j, ws, we):
                raise err("ERR_CREW_DOUBLE_BOOKED", "Crew already booked too close to this window")

    job = {
        "sign_project_id": pid,
        "work_order_id": work_order_id,
        "crew_id": crew_id,
        "equipment_id": equipment_id if equipment_id else None,
        "required_equipment_class": required_class,
        "window_start_iso": window_start,
        "window_end_iso": window_end,
        "status": "SCHEDULED",
    }
    stamp_new(job)
    job["_win_start"] = ws
    job["_win_end"] = we
    db.install_jobs[job["id"]] = job
    return reply(success_object(serialize(job), 201))


def _latest_passed_survey_obstruction(pid):
    passed = [s for s in children_of(db.site_surveys, pid) if s["status"] == "PASSED"]
    if not passed:
        return False
    latest = max(passed, key=lambda s: s["_seq"])
    return latest["overhead_obstruction"]


@app.route("/sign-projects/<pid>/install-jobs", methods=["GET"])
def list_install_jobs(pid):
    G.require_role({"ShopManager"})
    G.get_project(pid)
    items = children_of(db.install_jobs, pid)
    crew_id = request.args.get("crew_id")
    work_order_id = request.args.get("work_order_id")
    status = request.args.get("status")
    if crew_id is not None:
        items = [j for j in items if j.get("crew_id") == crew_id]
    if work_order_id is not None:
        items = [j for j in items if j.get("work_order_id") == work_order_id]
    items = filtered_list(items, status)
    return list_response(items)


@app.route("/sign-projects/<pid>/install-jobs/<jid>/dispatch", methods=["POST"])
def dispatch_install(pid, jid):
    G.require_role({"ShopManager"})
    G.get_project(pid)
    job = G.get_child(db.install_jobs, jid, pid)
    if job["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Install job is not SCHEDULED")
    crew = db.crews.get(job["crew_id"])
    if crew is None or not crew["active"]:
        raise err("ERR_CREW_UNAVAILABLE", "Crew is not active")
    if job["required_equipment_class"] == "BUCKET_TRUCK" and not crew["certified_aerial"]:
        raise err("ERR_CREW_NOT_CERTIFIED", "Crew not certified for aerial equipment")
    job["status"] = "DISPATCHED"
    touch(job)
    return reply(success_object(serialize(job)))


@app.route("/sign-projects/<pid>/install-jobs/<jid>/complete", methods=["POST"])
def complete_install(pid, jid):
    G.require_role({"ShopManager"})
    p = G.get_project(pid)
    job = G.get_child(db.install_jobs, jid, pid)
    if job["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Install job is not DISPATCHED")
    job["status"] = "INSTALLED"
    job["_installed_at"] = db.now()
    touch(job)
    if p["phase"] == "INSTALL":
        p["phase"] = "WARRANTY"
        touch(p)
    return reply(success_object(serialize(job)))


@app.route("/sign-projects/<pid>/install-jobs/<jid>/fail", methods=["POST"])
def fail_install(pid, jid):
    G.require_role({"ShopManager"})
    G.get_project(pid)
    job = G.get_child(db.install_jobs, jid, pid)
    if job["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Install job is not DISPATCHED")
    job["status"] = "FAILED"
    touch(job)
    return reply(success_object(serialize(job)))


@app.route("/sign-projects/<pid>/install-jobs/<jid>/cancel", methods=["POST"])
def cancel_install(pid, jid):
    G.require_role({"ShopManager"})
    G.get_project(pid)
    job = G.get_child(db.install_jobs, jid, pid)
    if job["status"] not in ("SCHEDULED", "DISPATCHED"):
        raise err("ERR_INVALID_STATE", "Install job cannot be cancelled from this state")
    job["status"] = "CANCELLED"
    touch(job)
    return reply(success_object(serialize(job)))


# ===========================================================================
# Change Orders
# ===========================================================================
def _accepted_estimate(p):
    eid = p.get("approved_estimate_id")
    if eid is None:
        return None
    return db.estimates.get(eid)


@app.route("/sign-projects/<pid>/change-orders", methods=["POST"])
def create_change_order(pid):
    G.require_role({"ShopManager"})
    p = G.get_project(pid)
    body = G.get_body()
    reason = G.require_str(body, "reason")
    new_w = body.get("new_face_width_in")
    new_h = body.get("new_face_height_in")
    new_sub = body.get("new_substrate")
    if new_w is not None:
        new_w = G.require_number({"new_face_width_in": new_w}, "new_face_width_in", positive=True)
    if new_h is not None:
        new_h = G.require_number({"new_face_height_in": new_h}, "new_face_height_in", positive=True)
    if new_sub is not None:
        new_sub = G.require_enum({"new_substrate": new_sub}, "new_substrate", SUBSTRATES)

    accepted = _accepted_estimate(p)
    delta = 0
    if accepted is not None:
        proof = db.art_proofs.get(accepted["art_proof_id"])
        color_count = proof["color_count"] if proof else 1
        eff_w = new_w if new_w is not None else p["face_width_in"]
        eff_h = new_h if new_h is not None else p["face_height_in"]
        eff_sub = new_sub if new_sub is not None else accepted["substrate"]
        rescope = price_estimate(eff_w, eff_h, eff_sub, color_count, p["illuminated"], p["rush"])
        delta = rescope["total_cents"] - accepted["total_cents"]

    co = {
        "sign_project_id": pid,
        "reason": reason,
        "new_face_width_in": new_w,
        "new_face_height_in": new_h,
        "new_substrate": new_sub,
        "delta_total_cents": delta,
        "status": "PROPOSED",
    }
    stamp_new(co)
    db.change_orders[co["id"]] = co
    return reply(success_object(serialize(co), 201))


@app.route("/sign-projects/<pid>/change-orders", methods=["GET"])
def list_change_orders(pid):
    G.require_role({"ShopManager", "Customer"})
    G.get_project(pid)
    status = request.args.get("status")
    return list_response(filtered_list(children_of(db.change_orders, pid), status))


@app.route("/sign-projects/<pid>/change-orders/<coid>/approve", methods=["POST"])
def approve_change_order(pid, coid):
    G.require_role({"Customer"})
    p = G.get_project(pid)
    co = G.get_child(db.change_orders, coid, pid)
    if co["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Change order is not PROPOSED")
    if p["phase"] not in ("PERMITTING", "FABRICATION"):
        raise err("ERR_CHANGE_WINDOW_CLOSED", "Change window is closed")
    co["status"] = "APPROVED"
    touch(co)
    return reply(success_object(serialize(co)))


@app.route("/sign-projects/<pid>/change-orders/<coid>/apply", methods=["POST"])
def apply_change_order(pid, coid):
    G.require_role({"ShopManager"})
    p = G.get_project(pid)
    co = G.get_child(db.change_orders, coid, pid)
    body = G.get_body()
    expected = body.get("expected_sign_project_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        G.invalid("expected_sign_project_version is required")
    if co["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Change order is not APPROVED")
    if p["phase"] not in ("PERMITTING", "FABRICATION"):
        raise err("ERR_CHANGE_WINDOW_CLOSED", "Change window is closed")
    # OCC last
    if expected != p["version"]:
        raise err("ERR_STALE_VERSION", "Project version is stale")

    co["status"] = "APPLIED"
    touch(co)
    # update project scope
    if co["new_face_width_in"] is not None:
        p["face_width_in"] = co["new_face_width_in"]
    if co["new_face_height_in"] is not None:
        p["face_height_in"] = co["new_face_height_in"]
    # substrate lives on the estimate; update accepted estimate substrate snapshot if changed
    if co["new_substrate"] is not None:
        accepted = _accepted_estimate(p)
        if accepted is not None:
            accepted["substrate"] = co["new_substrate"]
            touch(accepted)
    # ledger sync
    p["contract_total_cents"] = p["contract_total_cents"] + co["delta_total_cents"]
    # cascade: in-flight WO IN_PRODUCTION/QC_HOLD -> CANCELLED + new RELEASED WO
    in_flight = [w for w in children_of(db.work_orders, pid)
                 if w["status"] in ("IN_PRODUCTION", "QC_HOLD")]
    if in_flight:
        for w in in_flight:
            w["status"] = "CANCELLED"
            touch(w)
        est = _accepted_estimate(p)
        new_wo = {
            "sign_project_id": pid,
            "estimate_id": p.get("approved_estimate_id"),
            "snapshot_total_cents": est["total_cents"] if est else 0,
            "status": "RELEASED",
            "qc_pass": None,
        }
        stamp_new(new_wo)
        db.work_orders[new_wo["id"]] = new_wo
        if p["phase"] != "FABRICATION":
            p["phase"] = "FABRICATION"
    touch(p)
    return reply(success_object(serialize(co)))


@app.route("/sign-projects/<pid>/change-orders/<coid>/reject", methods=["POST"])
def reject_change_order(pid, coid):
    G.require_role({"Customer"})
    G.get_project(pid)
    co = G.get_child(db.change_orders, coid, pid)
    if co["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Change order is not PROPOSED")
    co["status"] = "REJECTED"
    touch(co)
    return reply(success_object(serialize(co)))


# ===========================================================================
# Warranty Claims
# ===========================================================================
@app.route("/sign-projects/<pid>/warranty-claims", methods=["POST"])
def create_warranty_claim(pid):
    G.require_role({"Customer", "ShopManager"})
    G.get_project(pid)
    body = G.get_body()
    install_job_id = G.require_str(body, "install_job_id")
    defect_kind = G.require_enum(body, "defect_kind", DEFECT_KINDS)
    reported_iso = G.require_datetime(body, "reported_iso")

    job = db.install_jobs.get(install_job_id)
    if job is None or job.get("sign_project_id") != pid or job.get("status") != "INSTALLED":
        raise err("ERR_REFERENCE_NOT_ELIGIBLE", "Install job is not an INSTALLED job of this project")

    install_date = job.get("_installed_at")
    coverage = COVERAGE_DAYS[defect_kind]
    reported = parse_iso(reported_iso)
    covered = False
    if install_date is not None and reported is not None:
        boundary = install_date + timedelta(days=coverage)
        covered = reported < boundary

    claim = {
        "sign_project_id": pid,
        "install_job_id": install_job_id,
        "defect_kind": defect_kind,
        "reported_iso": reported_iso,
        "covered": covered,
        "status": "OPEN",
    }
    stamp_new(claim)
    db.warranty_claims[claim["id"]] = claim
    return reply(success_object(serialize(claim), 201))


@app.route("/sign-projects/<pid>/warranty-claims", methods=["GET"])
def list_warranty_claims(pid):
    G.require_role({"ShopManager", "Customer"})
    G.get_project(pid)
    status = request.args.get("status")
    return list_response(filtered_list(children_of(db.warranty_claims, pid), status))


@app.route("/sign-projects/<pid>/warranty-claims/<claim_id>/decide", methods=["POST"])
def decide_warranty_claim(pid, claim_id):
    G.require_role({"ShopManager"})
    G.get_project(pid)
    claim = G.get_child(db.warranty_claims, claim_id, pid)
    body = G.get_body()
    decision = G.require_enum(body, "decision", {"APPROVE", "DENY"})
    if claim["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Claim is not OPEN")
    if decision == "APPROVE":
        if not claim["covered"]:
            raise err("ERR_OUT_OF_WARRANTY", "Claim is not covered")
        claim["status"] = "APPROVED"
    else:
        claim["status"] = "DENIED"
    touch(claim)
    return reply(success_object(serialize(claim)))


@app.route("/sign-projects/<pid>/warranty-claims/<claim_id>/resolve", methods=["POST"])
def resolve_warranty_claim(pid, claim_id):
    G.require_role({"ShopManager"})
    G.get_project(pid)
    claim = G.get_child(db.warranty_claims, claim_id, pid)
    if claim["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Claim is not APPROVED")
    claim["status"] = "RESOLVED"
    touch(claim)
    return reply(success_object(serialize(claim)))


# ===========================================================================
# Reorders
# ===========================================================================
@app.route("/sign-projects/<pid>/reorders", methods=["POST"])
def create_reorder(pid):
    G.require_role({"ShopManager", "Customer"})
    G.get_project(pid)
    body = G.get_body()
    quantity = G.require_int(body, "quantity", minimum=1)
    reprice = G.optional_bool(body, "reprice", True)
    reorder = {
        "sign_project_id": pid,
        "reorder_project_id": None,
        "quantity": quantity,
        "reprice": reprice,
        "status": "REQUESTED",
    }
    stamp_new(reorder)
    db.reorders[reorder["id"]] = reorder
    return reply(success_object(serialize(reorder), 201))


@app.route("/sign-projects/<pid>/reorders", methods=["GET"])
def list_reorders(pid):
    G.require_role({"ShopManager", "Customer"})
    G.get_project(pid)
    status = request.args.get("status")
    return list_response(filtered_list(children_of(db.reorders, pid), status))


@app.route("/sign-projects/<pid>/reorders/<rid>/confirm", methods=["POST"])
def confirm_reorder(pid, rid):
    G.require_role({"ShopManager"})
    source = G.get_project(pid)
    reorder = G.get_child(db.reorders, rid, pid)
    if reorder["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Reorder is not REQUESTED")
    if source["phase"] != "CLOSED":
        raise err("ERR_SOURCE_NOT_CLOSED", "Source project is not CLOSED")

    clone = {
        "customer_name": source["customer_name"],
        "site_address": source["site_address"],
        "jurisdiction_code": source["jurisdiction_code"],
        "sign_type": source["sign_type"],
        "face_width_in": source["face_width_in"],
        "face_height_in": source["face_height_in"],
        "placement_height_ft": source["placement_height_ft"],
        "illuminated": source["illuminated"],
        "rush": source["rush"],
        "phase": "DESIGN",
        "approved_estimate_id": None,
        "permit_required": source["permit_required"],
        "contract_total_cents": 0 if reorder["reprice"] else source["contract_total_cents"],
    }
    stamp_new(clone)
    db.sign_projects[clone["id"]] = clone

    reorder["status"] = "CONFIRMED"
    reorder["reorder_project_id"] = clone["id"]
    touch(reorder)
    return reply(success_object(serialize(reorder)))


@app.route("/sign-projects/<pid>/reorders/<rid>/cancel", methods=["POST"])
def cancel_reorder(pid, rid):
    G.require_role({"ShopManager"})
    G.get_project(pid)
    reorder = G.get_child(db.reorders, rid, pid)
    if reorder["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Reorder is not REQUESTED")
    reorder["status"] = "CANCELLED"
    touch(reorder)
    return reply(success_object(serialize(reorder)))


# ===========================================================================
# Cross-aggregate direct fetch + filtered lists
# ===========================================================================
@app.route("/estimates/<eid>", methods=["GET"])
def get_estimate(eid):
    G.require_role({"ShopManager", "Customer"})
    est = db.estimates.get(eid)
    if est is None:
        raise err("ERR_NOT_FOUND", "Estimate not found")
    reconcile_estimate(est)
    return reply(success_object(serialize(est)))


@app.route("/estimates", methods=["GET"])
def list_estimates_global():
    G.require_role({"ShopManager", "Customer"})
    items = list(db.estimates.values())
    for est in items:
        reconcile_estimate(est)
    art_proof_id = request.args.get("art_proof_id")
    sign_project_id = request.args.get("sign_project_id")
    status = request.args.get("status")
    if art_proof_id is not None:
        items = [e for e in items if e.get("art_proof_id") == art_proof_id]
    if sign_project_id is not None:
        items = [e for e in items if e.get("sign_project_id") == sign_project_id]
    items = filtered_list(items, status)
    return list_response(items)


@app.route("/fabrication-work-orders/<wid>", methods=["GET"])
def get_work_order(wid):
    G.require_role({"ShopManager"})
    wo = db.work_orders.get(wid)
    if wo is None:
        raise err("ERR_NOT_FOUND", "Work order not found")
    return reply(success_object(serialize(wo)))


@app.route("/fabrication-work-orders", methods=["GET"])
def list_work_orders_global():
    G.require_role({"ShopManager"})
    items = list(db.work_orders.values())
    estimate_id = request.args.get("estimate_id")
    sign_project_id = request.args.get("sign_project_id")
    status = request.args.get("status")
    if estimate_id is not None:
        items = [w for w in items if w.get("estimate_id") == estimate_id]
    if sign_project_id is not None:
        items = [w for w in items if w.get("sign_project_id") == sign_project_id]
    items = filtered_list(items, status)
    return list_response(items)


@app.route("/install-jobs/<jid>", methods=["GET"])
def get_install_job(jid):
    G.require_role({"ShopManager"})
    job = db.install_jobs.get(jid)
    if job is None:
        raise err("ERR_NOT_FOUND", "Install job not found")
    return reply(success_object(serialize(job)))


@app.route("/install-jobs", methods=["GET"])
def list_install_jobs_global():
    G.require_role({"ShopManager"})
    items = list(db.install_jobs.values())
    for key in ("work_order_id", "crew_id", "equipment_id", "sign_project_id"):
        val = request.args.get(key)
        if val is not None:
            items = [j for j in items if j.get(key) == val]
    status = request.args.get("status")
    items = filtered_list(items, status)
    return list_response(items)


@app.route("/warranty-claims/<claim_id>", methods=["GET"])
def get_warranty_claim(claim_id):
    G.require_role({"ShopManager", "Customer"})
    claim = db.warranty_claims.get(claim_id)
    if claim is None:
        raise err("ERR_NOT_FOUND", "Warranty claim not found")
    return reply(success_object(serialize(claim)))


@app.route("/warranty-claims", methods=["GET"])
def list_warranty_claims_global():
    G.require_role({"ShopManager", "Customer"})
    items = list(db.warranty_claims.values())
    install_job_id = request.args.get("install_job_id")
    sign_project_id = request.args.get("sign_project_id")
    status = request.args.get("status")
    if install_job_id is not None:
        items = [c for c in items if c.get("install_job_id") == install_job_id]
    if sign_project_id is not None:
        items = [c for c in items if c.get("sign_project_id") == sign_project_id]
    items = filtered_list(items, status)
    return list_response(items)


# ===========================================================================
# Test clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    G.require_role({"ShopManager"})
    body = G.get_body()
    to_iso = G.require_datetime(body, "to_iso8601")
    db.set_clock(parse_iso(to_iso))
    return reply(success_object({}))


# ===========================================================================
# Entry point
# ===========================================================================
def _serve():
    import time as _time
    import socket as _socket
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress (a production-grade WSGI server) rather than Flask's
    # built-in dev server. Under the benchmark's concurrent per-test-server
    # restarts the dev server can drop connections (empty replies surface to
    # the client as BadStatusLine); waitress handles concurrent connections
    # reliably. Behavior of every route is unchanged.
    try:
        from waitress import serve
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
        return

    def _make_listening_socket():
        # Pre-create the listening socket with SO_REUSEADDR (+ SO_REUSEPORT
        # where available) so a port still in TIME_WAIT from the previous
        # per-test server can be rebound immediately, instead of the boot
        # failing with "Address already in use" (which the runner reports as
        # "could not be restarted").
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        if hasattr(_socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        s.bind(("0.0.0.0", port))
        s.listen(128)
        s.setblocking(False)
        return s

    # The runner restarts this server before every test and polls ~15s for it
    # to come up. If the port is momentarily still held, retry the bind for a
    # short window (well under the runner's budget) rather than letting the
    # process exit prematurely. channel_timeout reaps idle keep-alive channels
    # promptly so a stale pooled client connection cannot wedge a channel.
    last_err = None
    for _ in range(40):  # ~6s of retries at 0.15s, comfortably under the 15s poll
        try:
            lsock = _make_listening_socket()
        except OSError as e:
            last_err = e
            _time.sleep(0.15)
            continue
        serve(
            app,
            sockets=[lsock],
            threads=4,
            channel_timeout=20,
            cleanup_interval=5,
        )
        return
    if last_err is not None:
        raise last_err


if __name__ == "__main__":
    _serve()
