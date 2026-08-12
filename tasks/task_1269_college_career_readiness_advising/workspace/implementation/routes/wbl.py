"""Certifications, placement sites, work-based learning placements (PRD §3.6)."""

from flask import Blueprint, g, request

from store import stores, mint, bump, now
from util import (
    ok_object, paginate, fail, get_body, validate_schema, require_role,
    parse_datetime,
    ERR_VALIDATION, ERR_INVALID_TERM, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_DUPLICATE_CODE, ERR_STUDENT_NOT_ENROLLED, ERR_TERM_NOT_STARTED,
    ERR_PLACEMENT_OVERLAP, ERR_SITE_CAPACITY_EXCEEDED,
)
from computed import (
    ser_certification, ser_site, ser_placement, site_overlap_max,
)
from cascades import autoflag_certified_audits, terminate_placement, site_capacity_reduction
from routes.students import get_student_or_404, student_ownership

bp = Blueprint("wbl", __name__)

CERT_STATUSES = ("REGISTERED", "EXAM_SCHEDULED", "PASSED", "FAILED", "CANCELLED")
SITE_STATUSES = ("ACTIVE", "SUSPENDED")
PLACEMENT_STATUSES = ("OFFERED", "CONFIRMED", "ACTIVE", "COMPLETED", "DECLINED", "TERMINATED")


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------

@bp.post("/ccr/students/<sid>/certifications")
def cert_create(sid):
    body = get_body()
    validate_schema(body, {"cert_code": {"kind": "str", "required": True}})
    require_role(g.user_role, "WblCoordinator")
    student = get_student_or_404(sid)
    if student["status"] != "ENROLLED":
        fail(ERR_STUDENT_NOT_ENROLLED, 409, "Student is not ENROLLED")
    rec = mint("certifications")
    rec.update({
        "student_id": sid,
        "cert_code": body["cert_code"],
        "status": "REGISTERED",
        "exam_at": None,
        "earned_at": None,
        "retake_count": 0,
    })
    stores["certifications"][rec["id"]] = rec
    return ok_object(ser_certification(rec), 201)


@bp.get("/ccr/students/<sid>/certifications")
def cert_list(sid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student", "WblCoordinator")
    get_student_or_404(sid)
    student_ownership(sid)
    items = [c for c in stores["certifications"].values() if c["student_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate(items, ser_certification)


def get_cert_or_404(cid):
    c = stores["certifications"].get(cid)
    if c is None:
        fail(ERR_NOT_FOUND, 404, "Certification not found")
    return c


@bp.get("/ccr/certifications/<cid>")
def cert_get(cid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student", "WblCoordinator")
    cert = get_cert_or_404(cid)
    if g.user_role == "Student":
        student_ownership(cert["student_id"])
    return ok_object(ser_certification(cert), 200)


_CERT_TRANSITIONS = {
    "EXAM_SCHEDULED": ("REGISTERED", "FAILED"),   # FAILED->EXAM_SCHEDULED = retake
    "PASSED": ("EXAM_SCHEDULED",),
    "FAILED": ("EXAM_SCHEDULED",),
    "CANCELLED": ("REGISTERED", "EXAM_SCHEDULED"),
    "REGISTERED": (),
}


@bp.post("/ccr/certifications/<cid>/transition")
def cert_transition(cid):
    body = get_body()
    validate_schema(body, {
        "to_status": {"kind": "str", "required": True, "choices": CERT_STATUSES},
        "exam_at": {"kind": "datetime", "required": False},
    })
    # Stage 2 schema: scheduling requires exam_at present and strictly future
    # (a missing or past exam_at is a schema failure, PRD §3.6 / §2.6).
    if body["to_status"] == "EXAM_SCHEDULED":
        exam_at = parse_datetime(body.get("exam_at")) if body.get("exam_at") is not None else None
        if exam_at is None or exam_at <= now():
            fail(ERR_VALIDATION, 400, "exam_at must be present and in the future")
    require_role(g.user_role, "WblCoordinator")
    cert = get_cert_or_404(cid)
    target = body["to_status"]
    if cert["status"] not in _CERT_TRANSITIONS[target]:
        fail(ERR_INVALID_STATE, 409,
             f"Cannot move certification from {cert['status']} to {target}")
    prior = cert["status"]
    cert["status"] = target
    if target == "EXAM_SCHEDULED":
        cert["exam_at"] = parse_datetime(body["exam_at"])
        if prior == "FAILED":
            cert["retake_count"] += 1
    elif target == "PASSED":
        cert["earned_at"] = now()
    bump(cert)
    if target == "PASSED":
        autoflag_certified_audits(cert["student_id"])
    return ok_object(ser_certification(cert), 200)


# ---------------------------------------------------------------------------
# Placement sites
# ---------------------------------------------------------------------------

@bp.post("/ccr/placement-sites")
def site_create():
    body = get_body()
    validate_schema(body, {
        "site_code": {"kind": "str", "required": True},
        "name": {"kind": "str", "required": True},
        "max_concurrent_placements": {"kind": "int", "required": True, "min": 1},
    })
    require_role(g.user_role, "DistrictAdmin")
    if any(s["site_code"] == body["site_code"] for s in stores["sites"].values()):
        fail(ERR_DUPLICATE_CODE, 409, "site_code already in use")
    rec = mint("sites")
    rec.update({
        "site_code": body["site_code"],
        "name": body["name"],
        "max_concurrent_placements": body["max_concurrent_placements"],
        "status": "ACTIVE",
    })
    stores["sites"][rec["id"]] = rec
    return ok_object(ser_site(rec), 201)


def get_site_or_404(sid):
    s = stores["sites"].get(sid)
    if s is None:
        fail(ERR_NOT_FOUND, 404, "Placement site not found")
    return s


@bp.get("/ccr/placement-sites/<sid>")
def site_get(sid):
    require_role(g.user_role, "DistrictAdmin", "WblCoordinator")
    return ok_object(ser_site(get_site_or_404(sid)), 200)


@bp.patch("/ccr/placement-sites/<sid>")
def site_patch(sid):
    body = get_body()
    validate_schema(body, {
        "name": {"kind": "str", "required": False},
        "max_concurrent_placements": {"kind": "int", "required": False, "min": 1},
        "status": {"kind": "str", "required": False, "choices": SITE_STATUSES},
    })
    require_role(g.user_role, "DistrictAdmin")
    site = get_site_or_404(sid)
    new_max = body.get("max_concurrent_placements")
    if "name" in body and body["name"] is not None:
        site["name"] = body["name"]
    if "status" in body and body["status"] is not None:
        site["status"] = body["status"]
    if new_max is not None:
        # Capacity reduction below the current overlap maximum force-terminates
        # the excess (created_at ASC survivors) with SITE_CAPACITY_REDUCTION.
        if new_max < site["max_concurrent_placements"]:
            site_capacity_reduction(site, new_max)
        site["max_concurrent_placements"] = new_max
    bump(site)
    return ok_object(ser_site(site), 200)


@bp.get("/ccr/placement-sites/<sid>/placements")
def site_placements(sid):
    require_role(g.user_role, "DistrictAdmin", "WblCoordinator")
    get_site_or_404(sid)
    items = [p for p in stores["placements"].values() if p["site_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items, ser_placement)


# ---------------------------------------------------------------------------
# Placements
# ---------------------------------------------------------------------------

@bp.post("/ccr/students/<sid>/placements")
def placement_create(sid):
    body = get_body()
    validate_schema(body, {
        "site_id": {"kind": "str", "required": True},
        "term_start": {"kind": "datetime", "required": True},
        "term_end": {"kind": "datetime", "required": True},
        "hours_per_week": {"kind": "num", "required": True, "gt": 0},
    })
    # Stage 2.5: interval shape is checked after schema but ahead of role and
    # existence (PRD §2.6).
    term_start = parse_datetime(body["term_start"])
    term_end = parse_datetime(body["term_end"])
    if term_end <= term_start:
        fail(ERR_INVALID_TERM, 422, "term_end must be strictly after term_start")
    require_role(g.user_role, "WblCoordinator")
    student = get_student_or_404(sid)
    site = stores["sites"].get(body["site_id"])
    if site is None:
        fail(ERR_NOT_FOUND, 404, "Placement site not found")
    if student["status"] != "ENROLLED":
        fail(ERR_STUDENT_NOT_ENROLLED, 409, "Student is not ENROLLED")
    if site["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, 409, "Site is not ACTIVE")
    rec = mint("placements")
    rec.update({
        "student_id": sid,
        "site_id": site["id"],
        "term_start": term_start,
        "term_end": term_end,
        "hours_per_week": body["hours_per_week"],
        "status": "OFFERED",
        "hours_logged": 0,
        "terminated_reason": None,
    })
    stores["placements"][rec["id"]] = rec
    return ok_object(ser_placement(rec), 201)


@bp.get("/ccr/students/<sid>/placements")
def placement_list(sid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student", "WblCoordinator")
    get_student_or_404(sid)
    student_ownership(sid)
    items = [p for p in stores["placements"].values() if p["student_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items, ser_placement)


def get_placement_or_404(pid):
    p = stores["placements"].get(pid)
    if p is None:
        fail(ERR_NOT_FOUND, 404, "Placement not found")
    return p


@bp.get("/ccr/placements/<pid>")
def placement_get(pid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student", "WblCoordinator")
    p = get_placement_or_404(pid)
    if g.user_role == "Student":
        student_ownership(p["student_id"])
    return ok_object(ser_placement(p), 200)


_PLACEMENT_TRANSITIONS = {
    "CONFIRMED": ("OFFERED",),
    "ACTIVE": ("CONFIRMED",),
    "COMPLETED": ("ACTIVE",),
    "DECLINED": ("OFFERED",),
    "TERMINATED": ("CONFIRMED", "ACTIVE"),
    "OFFERED": (),
}


@bp.post("/ccr/placements/<pid>/transition")
def placement_transition(pid):
    body = get_body()
    validate_schema(body, {
        "to_status": {"kind": "str", "required": True, "choices": PLACEMENT_STATUSES},
        "hours_logged": {"kind": "num", "required": False},
    })
    # Stage 2 schema: COMPLETED requires hours_logged present and >= 0.
    if body["to_status"] == "COMPLETED":
        if body.get("hours_logged") is None or body["hours_logged"] < 0:
            fail(ERR_VALIDATION, 400, "hours_logged must be present and >= 0")
    require_role(g.user_role, "WblCoordinator")
    p = get_placement_or_404(pid)
    target = body["to_status"]
    if p["status"] not in _PLACEMENT_TRANSITIONS[target]:
        fail(ERR_INVALID_STATE, 409,
             f"Cannot move placement from {p['status']} to {target}")
    if target == "CONFIRMED":
        site = stores["sites"][p["site_id"]]
        # Gates in pipeline order (PRD §3.6): site state, pairwise overlap,
        # aggregate interval capacity.
        if site["status"] != "ACTIVE":
            fail(ERR_INVALID_STATE, 409, "Site is not ACTIVE")
        for other in stores["placements"].values():
            if other["id"] == p["id"] or other["student_id"] != p["student_id"]:
                continue
            if other["status"] not in ("CONFIRMED", "ACTIVE"):
                continue
            # Half-open intervals: adjacency (end == start) is not overlap.
            if other["term_start"] < p["term_end"] and p["term_start"] < other["term_end"]:
                fail(ERR_PLACEMENT_OVERLAP, 409,
                     "Placement overlaps another CONFIRMED/ACTIVE placement of the student")
        max_overlap = site_overlap_max(site["id"], p["term_start"], p["term_end"], exclude_id=p["id"])
        if max_overlap + 1 > site["max_concurrent_placements"]:
            fail(ERR_SITE_CAPACITY_EXCEEDED, 409, "Site aggregate capacity exceeded")
    if target == "ACTIVE" and now() < p["term_start"]:
        fail(ERR_TERM_NOT_STARTED, 409, "Placement term has not started")
    p["status"] = target
    if target == "COMPLETED":
        p["hours_logged"] = body["hours_logged"]
    if target == "TERMINATED":
        p["terminated_reason"] = "MANUAL"  # hours_logged stays 0 (PRD §3.6)
    bump(p)
    if target == "COMPLETED":
        # Completion changes audited work-hours input -> AUTO_DRIFT (PRD §3.6).
        autoflag_certified_audits(p["student_id"])
    return ok_object(ser_placement(p), 200)
