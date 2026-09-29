"""Set jobs, marriage joints and anchoring certifications (PRD 3.6-3.8)."""
from flask import Blueprint

import calc
import domain
from envelope import object_response
from errors import fail
from guards import (
    ANY_ROLE,
    actor_id,
    apply_filters,
    filters,
    lookup,
    lookup_ref,
    roles,
    validate,
)
from routes_partners import list_response
from store import base_row, db, mark, parse_day

bp = Blueprint("setjobs", __name__)


def _require_job_owner(job):
    if actor_id() != job["set_crew_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")


# ---------------------------------------------------------------------------
# SetJob
# ---------------------------------------------------------------------------
@bp.post("/installations/set-jobs")
@roles("NetworkAdmin")
def create_set_job():
    body = validate(
        [
            {"name": "order_id", "type": "string", "required": True},
            {"name": "set_crew_id", "type": "string", "required": True},
            {"name": "scheduled_start_date", "type": "date", "required": True},
            {"name": "scheduled_end_date", "type": "date", "required": True},
            {"name": "labor_base_cents", "type": "integer", "required": True, "min": 0},
            {"name": "expected_order_version", "type": "integer", "required": True},
        ]
    )
    order = lookup_ref("orders", body["order_id"], "ERR_ORDER_NOT_FOUND")
    crew = lookup_ref("set_crews", body["set_crew_id"], "ERR_SET_CREW_NOT_FOUND")
    if order["posture"] == "CLOSED":
        fail("ERR_ORDER_POSTURE_BLOCKED")
    if body["expected_order_version"] != order["version"]:
        fail("ERR_STALE_ORDER_VERSION")

    start_day = parse_day(body["scheduled_start_date"])
    end_day = parse_day(body["scheduled_end_date"])
    if end_day < start_day:
        fail("ERR_INVALID_WINDOW")
    if domain.day_capacity_exceeded(crew, start_day, end_day):
        fail("ERR_SET_CREW_CAPACITY_EXCEEDED")

    row = base_row()
    row.update(
        {
            "order_id": order["id"],
            "set_crew_id": crew["id"],
            "scheduled_start_date": body["scheduled_start_date"],
            "scheduled_end_date": body["scheduled_end_date"],
            "labor_base_cents": body["labor_base_cents"],
            "progress_status": "SCHEDULED",
            "scope_status": "SCOPE_PENDING",
            "skirting_owner": None,
            "steps_owner": None,
            "skirting_fee_cents": 0,
            "steps_fee_cents": 0,
            "crossover_count": 0,
            "crossover_fee_cents": 0,
            "crossover_recorded": False,
            "closure_score": None,
            "closure_status": "NOT_ASSESSED",
            "invoice_total_cents": None,
            "final_inspector_user_id": None,
            "final_result": "PENDING",
        }
    )
    for other in domain.set_jobs_of_order(order["id"]):
        if other["progress_status"] == "SCHEDULED":
            other["progress_status"] = "SUPERSEDED"
            mark(other)
    db.set_jobs[row["id"]] = row
    mark(order)
    domain.recompute_posture(order)
    return object_response(domain.pub_set_job(row), 201)


@bp.get("/installations/set-jobs/<row_id>")
@roles(*ANY_ROLE)
def read_set_job(row_id):
    row = lookup("set_jobs", row_id, "ERR_SET_JOB_NOT_FOUND")
    return object_response(domain.pub_set_job(row))


@bp.get("/installations/set-jobs")
@roles(*ANY_ROLE)
def list_set_jobs():
    active = filters(
        {
            "order_id": None,
            "set_crew_id": None,
            "progress_status": [
                "SCHEDULED",
                "DISPATCHED",
                "SET_COMPLETE",
                "CLOSED",
                "SUPERSEDED",
            ],
            "scope_status": ["SCOPE_PENDING", "SCOPE_SPLIT", "SCOPE_DELIVERED"],
        }
    )
    rows = apply_filters(list(db.set_jobs.values()), active)
    return list_response(rows, domain.pub_set_job)


@bp.post("/installations/set-jobs/<row_id>/dispatch")
@roles("NetworkAdmin")
def dispatch_set_job(row_id):
    job = lookup("set_jobs", row_id, "ERR_SET_JOB_NOT_FOUND")
    if job["progress_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    order = db.orders.get(job["order_id"])
    site = domain.site_of_order(job["order_id"])
    if site is None:
        fail("ERR_SITE_NOT_FOUND", "The order has no destination site.")
    if site["readiness_status"] != "READY":
        fail("ERR_SITE_NOT_READY")
    if order["posture"] in ("TRANSPORT_BLOCKED", "CLOSED"):
        fail("ERR_ORDER_POSTURE_BLOCKED")
    crew = db.set_crews.get(job["set_crew_id"])
    if crew is None or domain.set_crew_status(crew) != "ACTIVE":
        fail("ERR_INSTALLER_LICENSE_INVALID")
    sections = domain.sections_of_order(order["id"])
    if len(sections) != int(order["section_count"]):
        fail("ERR_SECTION_COUNT_MISMATCH")
    for section in sections:
        if section["transit_status"] != "DELIVERED":
            fail("ERR_SECTIONS_NOT_DELIVERED")

    job["progress_status"] = "DISPATCHED"
    mark(job)
    domain.recompute_posture(order)
    return object_response(domain.pub_set_job(job))


@bp.post("/installations/set-jobs/<row_id>/scope-split")
@roles("SetCrewLead")
def scope_split(row_id):
    body = validate(
        [
            {
                "name": "skirting_owner",
                "type": "enum",
                "required": True,
                "values": ["DEALER", "INSTALLER"],
            },
            {
                "name": "steps_owner",
                "type": "enum",
                "required": True,
                "values": ["DEALER", "INSTALLER"],
            },
            {"name": "skirting_linear_ft", "type": "number", "required": True},
            {"name": "steps_count", "type": "integer", "required": True},
        ]
    )
    job = lookup("set_jobs", row_id, "ERR_SET_JOB_NOT_FOUND")
    _require_job_owner(job)
    if job["scope_status"] != "SCOPE_PENDING":
        fail("ERR_INVALID_STATE")
    if job["progress_status"] not in ("SCHEDULED", "DISPATCHED", "SET_COMPLETE"):
        fail("ERR_INVALID_STATE")

    job["skirting_owner"] = body["skirting_owner"]
    job["steps_owner"] = body["steps_owner"]
    job["_skirting_linear_ft"] = body["skirting_linear_ft"]
    job["_steps_count"] = body["steps_count"]
    job["skirting_fee_cents"] = calc.skirting_fee(
        body["skirting_owner"], body["skirting_linear_ft"]
    )
    job["steps_fee_cents"] = calc.steps_fee(body["steps_owner"], body["steps_count"])
    job["scope_status"] = "SCOPE_SPLIT"
    mark(job)
    return object_response(domain.pub_set_job(job))


@bp.post("/installations/set-jobs/<row_id>/utility-crossover")
@roles("SetCrewLead")
def utility_crossover(row_id):
    body = validate(
        [{"name": "crossover_count", "type": "integer", "required": True, "min": 0}]
    )
    job = lookup("set_jobs", row_id, "ERR_SET_JOB_NOT_FOUND")
    _require_job_owner(job)
    if job["scope_status"] != "SCOPE_SPLIT":
        fail("ERR_INVALID_STATE")
    if job["progress_status"] not in ("DISPATCHED", "SET_COMPLETE"):
        fail("ERR_INVALID_STATE")

    job["crossover_count"] = body["crossover_count"]
    job["crossover_fee_cents"] = calc.crossover_fee(body["crossover_count"])
    job["crossover_recorded"] = True
    job["scope_status"] = "SCOPE_DELIVERED"
    mark(job)
    return object_response(domain.pub_set_job(job))


@bp.post("/installations/set-jobs/<row_id>/close-marriage-line")
@roles("SetCrewLead")
def close_marriage_line(row_id):
    job = lookup("set_jobs", row_id, "ERR_SET_JOB_NOT_FOUND")
    _require_job_owner(job)
    if job["progress_status"] != "DISPATCHED":
        fail("ERR_INVALID_STATE")
    order = db.orders.get(job["order_id"])
    joints = domain.joints_of_job(job["id"])
    required = max(0, int(order["section_count"]) - 1)
    if len(joints) != required:
        fail("ERR_MARRIAGE_JOINT_COUNT_MISMATCH")

    score, status = calc.closure_score_and_status(joints)
    if status == "FAIL":
        fail("ERR_MARRIAGE_LINE_NOT_CLOSED")
    job["closure_score"] = float(score)
    job["closure_status"] = status
    job["progress_status"] = "SET_COMPLETE"
    mark(job)
    domain.recompute_posture(order)
    return object_response(domain.pub_set_job(job))


@bp.post("/installations/set-jobs/<row_id>/final-inspection")
@roles("InstallationInspector")
def final_inspection(row_id):
    body = validate(
        [
            {
                "name": "punch_item_count",
                "type": "integer",
                "required": True,
                "min": 0,
            },
            {"name": "notes", "type": "string", "required": True},
        ]
    )
    job = lookup("set_jobs", row_id, "ERR_SET_JOB_NOT_FOUND")
    if job["progress_status"] != "SET_COMPLETE":
        fail("ERR_INVALID_STATE")
    order = db.orders.get(job["order_id"])
    if order["posture"] == "TRANSPORT_BLOCKED":
        fail("ERR_ORDER_POSTURE_BLOCKED")
    site = domain.site_of_order(order["id"])
    if site is not None and site["last_inspector_user_id"] == actor_id():
        fail("ERR_SEGREGATION_OF_DUTIES")
    certified = [c for c in domain.certs_of_job(job["id"]) if c["status"] == "CERTIFIED"]
    if not certified:
        fail("ERR_ANCHOR_NOT_CERTIFIED")
    if job["closure_status"] not in ("PASS", "NOT_APPLICABLE"):
        fail("ERR_MARRIAGE_LINE_NOT_CLOSED")
    if job["scope_status"] == "SCOPE_PENDING":
        fail("ERR_SCOPE_SPLIT_INCOMPLETE")
    if not job["crossover_recorded"]:
        fail("ERR_UTILITY_CROSSOVER_INCOMPLETE")

    job["final_inspector_user_id"] = actor_id()
    if int(body["punch_item_count"]) == 0:
        job["final_result"] = "PASS"
        job["progress_status"] = "CLOSED"
        job["invoice_total_cents"] = domain.assemble_invoice(job)
        mark(job)
        order["invoice_total_cents"] = job["invoice_total_cents"]
        order["warranty_start_date"] = db.clock_date().isoformat()
        mark(order)
        domain.recompute_posture(order)
    else:
        job["final_result"] = "PUNCH_LIST"
        mark(job)
        mark(order)
        domain.recompute_posture(order)
    return object_response(domain.pub_set_job(job))


# ---------------------------------------------------------------------------
# MarriageJoint -- append-only event row: id and created_at only (PRD 2.4)
# ---------------------------------------------------------------------------
@bp.post("/installations/marriage-joints")
@roles("SetCrewLead")
def create_marriage_joint():
    body = validate(
        [
            {"name": "set_job_id", "type": "string", "required": True},
            {
                "name": "joint_index",
                "type": "integer",
                "required": True,
                "min": 1,
                "max": 3,
            },
            {"name": "gap_in", "type": "number", "required": True, "min": 0, "max": 4},
            {
                "name": "vertical_offset_in",
                "type": "number",
                "required": True,
                "min": -4,
                "max": 4,
            },
            {
                "name": "ridge_beam_shim_in",
                "type": "number",
                "required": True,
                "min": 0,
                "max": 2,
            },
        ]
    )
    job = lookup_ref("set_jobs", body["set_job_id"], "ERR_SET_JOB_NOT_FOUND")
    _require_job_owner(job)
    for other in domain.joints_of_job(job["id"]):
        if other["joint_index"] == body["joint_index"]:
            fail("ERR_DUPLICATE_JOINT_INDEX")

    row = base_row(with_version=False)
    row.update(
        {
            "set_job_id": job["id"],
            "joint_index": body["joint_index"],
            "gap_in": body["gap_in"],
            "vertical_offset_in": body["vertical_offset_in"],
            "ridge_beam_shim_in": body["ridge_beam_shim_in"],
            "deviation_score": float(
                calc.joint_deviation_score(
                    body["gap_in"],
                    body["vertical_offset_in"],
                    body["ridge_beam_shim_in"],
                )
            ),
        }
    )
    db.marriage_joints[row["id"]] = row
    return object_response(domain.pub_joint(row), 201)


@bp.get("/installations/marriage-joints/<row_id>")
@roles(*ANY_ROLE)
def read_marriage_joint(row_id):
    row = lookup("marriage_joints", row_id, "ERR_MARRIAGE_JOINT_NOT_FOUND")
    return object_response(domain.pub_joint(row))


@bp.get("/installations/marriage-joints")
@roles(*ANY_ROLE)
def list_marriage_joints():
    active = filters({"set_job_id": None})
    rows = apply_filters(list(db.marriage_joints.values()), active)
    return list_response(rows, domain.pub_joint)


# ---------------------------------------------------------------------------
# AnchorCertification
# ---------------------------------------------------------------------------
def _evaluate_cert(cert, job):
    order = db.orders.get(job["order_id"])
    hud_pass, state_pass = calc.anchor_certification_evaluation(cert, order)
    cert["hud_pass"] = hud_pass
    cert["state_pass"] = state_pass


@bp.post("/installations/anchor-certifications")
@roles("SetCrewLead")
def create_anchor_certification():
    body = validate(
        [
            {"name": "set_job_id", "type": "string", "required": True},
            {"name": "anchor_count", "type": "integer", "required": True, "min": 0},
            {"name": "avg_torque_ft_lb", "type": "number", "required": True, "min": 0},
            {"name": "strap_count", "type": "integer", "required": True, "min": 0},
            {"name": "pier_count", "type": "integer", "required": True, "min": 0},
        ]
    )
    job = lookup_ref("set_jobs", body["set_job_id"], "ERR_SET_JOB_NOT_FOUND")
    _require_job_owner(job)
    crew = db.set_crews.get(job["set_crew_id"])
    if crew is None or domain.set_crew_status(crew) != "ACTIVE":
        fail("ERR_INSTALLER_LICENSE_INVALID")
    for other in domain.certs_of_job(job["id"]):
        if other["status"] != "FAILED":
            fail("ERR_DUPLICATE_ANCHOR_CERT")

    row = base_row()
    row.update(
        {
            "set_job_id": job["id"],
            "anchor_count": body["anchor_count"],
            "avg_torque_ft_lb": body["avg_torque_ft_lb"],
            "strap_count": body["strap_count"],
            "pier_count": body["pier_count"],
            "revision_round": 1,
            "hud_pass": False,
            "state_pass": False,
            "certifier_user_id": None,
            "status": "SUBMITTED",
        }
    )
    _evaluate_cert(row, job)
    db.anchor_certs[row["id"]] = row
    return object_response(domain.pub_cert(row), 201)


@bp.get("/installations/anchor-certifications/<row_id>")
@roles(*ANY_ROLE)
def read_anchor_certification(row_id):
    row = lookup("anchor_certs", row_id, "ERR_ANCHOR_CERT_NOT_FOUND")
    return object_response(domain.pub_cert(row))


@bp.get("/installations/anchor-certifications")
@roles(*ANY_ROLE)
def list_anchor_certifications():
    active = filters(
        {
            "set_job_id": None,
            "status": ["SUBMITTED", "CHANGES_REQUIRED", "CERTIFIED", "FAILED"],
        }
    )
    rows = apply_filters(list(db.anchor_certs.values()), active)
    return list_response(rows, domain.pub_cert)


@bp.post("/installations/anchor-certifications/<row_id>/review")
@roles("InstallationInspector")
def review_anchor_certification(row_id):
    body = validate(
        [
            {
                "name": "decision",
                "type": "enum",
                "required": True,
                "values": ["CERTIFY", "REQUEST_CHANGES", "FAIL"],
            },
            {"name": "findings", "type": "string", "required": True},
        ]
    )
    cert = lookup("anchor_certs", row_id, "ERR_ANCHOR_CERT_NOT_FOUND")
    if cert["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    decision = body["decision"]
    if decision == "CERTIFY":
        if not (cert["hud_pass"] and cert["state_pass"]):
            fail("ERR_ANCHOR_COMPLIANCE_FAILED")
        cert["status"] = "CERTIFIED"
    elif decision == "REQUEST_CHANGES":
        cert["status"] = "CHANGES_REQUIRED"
    else:
        cert["status"] = "FAILED"
    cert["certifier_user_id"] = actor_id()
    mark(cert)
    return object_response(domain.pub_cert(cert))


@bp.post("/installations/anchor-certifications/<row_id>/resubmit")
@roles("SetCrewLead")
def resubmit_anchor_certification(row_id):
    body = validate(
        [
            {"name": "anchor_count", "type": "integer", "required": True, "min": 0},
            {"name": "avg_torque_ft_lb", "type": "number", "required": True, "min": 0},
            {"name": "strap_count", "type": "integer", "required": True, "min": 0},
            {"name": "pier_count", "type": "integer", "required": True, "min": 0},
        ]
    )
    cert = lookup("anchor_certs", row_id, "ERR_ANCHOR_CERT_NOT_FOUND")
    job = db.set_jobs.get(cert["set_job_id"])
    if job is None or actor_id() != job["set_crew_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if cert["status"] != "CHANGES_REQUIRED":
        fail("ERR_INVALID_STATE")
    if int(cert["revision_round"]) >= calc.MAX_ANCHOR_REVISIONS:
        fail("ERR_ANCHOR_REVISION_LIMIT")

    cert["anchor_count"] = body["anchor_count"]
    cert["avg_torque_ft_lb"] = body["avg_torque_ft_lb"]
    cert["strap_count"] = body["strap_count"]
    cert["pier_count"] = body["pier_count"]
    cert["revision_round"] = int(cert["revision_round"]) + 1
    cert["status"] = "SUBMITTED"
    _evaluate_cert(cert, job)
    mark(cert)
    return object_response(domain.pub_cert(cert))
