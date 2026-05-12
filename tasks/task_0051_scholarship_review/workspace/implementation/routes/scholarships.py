"""Scholarship CRUD + state transitions + quota allocations."""
from flask import Blueprint, g

import db
from clock import parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.calculations import windows_half_open_overlap
from services.lookup import get_scholarship_or_404, check_version
from services.scholarship_lifecycle import transition_scholarship
from services.validation import get_body


bp = Blueprint("scholarships", __name__)


VALID_CATEGORIES = {"MERIT", "NEED", "RESEARCH", "SPECIAL_GROUP"}
VALID_MATERIALS = {"TRANSCRIPT", "AWARD_CERT", "POVERTY_PROOF", "ADVISOR_REC"}


def _validate_create_body(body: dict):
    required = [
        "code", "name", "category", "per_award_amount_cents", "total_quota",
        "gpa_threshold_x100", "eligible_majors", "eligible_grades",
        "required_materials", "application_window_start", "application_window_end",
        "announcement_window_end", "rubric_weights",
    ]
    for f in required:
        if f not in body:
            raise err("ERR_BAD_REQUEST", f"Missing required field: {f}")

    if not isinstance(body["code"], str) or not (3 <= len(body["code"]) <= 32):
        raise err("ERR_BAD_REQUEST", "code must be a 3-32 character string")
    if body["category"] not in VALID_CATEGORIES:
        raise err("ERR_BAD_REQUEST", "category must be MERIT|NEED|RESEARCH|SPECIAL_GROUP")
    if not isinstance(body["per_award_amount_cents"], int) or body["per_award_amount_cents"] < 1:
        raise err("ERR_BAD_REQUEST", "per_award_amount_cents must be integer >= 1")
    if not isinstance(body["total_quota"], int) or body["total_quota"] < 1:
        raise err("ERR_BAD_REQUEST", "total_quota must be integer >= 1")
    if not isinstance(body["gpa_threshold_x100"], int):
        raise err("ERR_BAD_REQUEST", "gpa_threshold_x100 must be integer")
    if not isinstance(body["eligible_majors"], list):
        raise err("ERR_BAD_REQUEST", "eligible_majors must be array")
    if not isinstance(body["eligible_grades"], list):
        raise err("ERR_BAD_REQUEST", "eligible_grades must be array")
    if not isinstance(body["required_materials"], list):
        raise err("ERR_BAD_REQUEST", "required_materials must be array")
    for m in body["required_materials"]:
        if m not in VALID_MATERIALS:
            raise err("ERR_BAD_REQUEST", f"unknown material code: {m}")
    if not isinstance(body["rubric_weights"], dict) or not body["rubric_weights"]:
        raise err("ERR_BAD_REQUEST", "rubric_weights must be a non-empty object")
    for k, v in body["rubric_weights"].items():
        if not isinstance(v, int) or v < 0:
            raise err("ERR_BAD_REQUEST", f"rubric_weights[{k}] must be non-negative integer")
    if body["category"] == "NEED":
        if body.get("family_income_ceiling_cents") is None or not isinstance(body["family_income_ceiling_cents"], int):
            raise err("ERR_BAD_REQUEST", "family_income_ceiling_cents required for NEED category")
    else:
        if body.get("family_income_ceiling_cents") is not None:
            raise err("ERR_BAD_REQUEST", "family_income_ceiling_cents must be null for non-NEED")

    # Window order checks
    try:
        ws = parse_iso(body["application_window_start"])
        we = parse_iso(body["application_window_end"])
        ae = parse_iso(body["announcement_window_end"])
    except ValueError as e:
        raise err("ERR_BAD_REQUEST", f"Invalid window timestamp: {e}")
    if not (ws < we):
        raise err("ERR_BAD_REQUEST", "application_window_end must be strictly after start")
    if not (we < ae):
        raise err("ERR_BAD_REQUEST", "announcement_window_end must be strictly after application_window_end")


def _check_window_overlap(category: str, ws: str, we: str, exclude_id: str = None):
    for s in db.scholarships.values():
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        if s["category"] != category:
            continue
        if s["status"] == "DISBURSED":
            continue
        if windows_half_open_overlap(ws, we, s["application_window_start"], s["application_window_end"]):
            raise err("ERR_SCHOLARSHIP_WINDOW_OVERLAP",
                      "application_window overlaps existing scholarship of same category")


def _check_rubric_sum(rw: dict):
    if rw is None:
        return
    total = sum(int(v) for v in rw.values())
    if total != 100:
        raise err("ERR_RUBRIC_WEIGHT_INVALID", "rubric_weights values must sum to exactly 100")


@bp.route("/scholarships", methods=["POST"])
@require_auth(roles={"SchoolAdmin"})
def create_scholarship():
    body = get_body()
    _validate_create_body(body)

    rw = body["rubric_weights"]
    _check_rubric_sum(rw)

    # Code uniqueness
    for s in db.scholarships.values():
        if s["code"] == body["code"]:
            raise err("ERR_BAD_REQUEST", f"code {body['code']} already exists")

    _check_window_overlap(body["category"], body["application_window_start"], body["application_window_end"])

    entity = {
        "code": body["code"],
        "name": body["name"],
        "category": body["category"],
        "per_award_amount_cents": body["per_award_amount_cents"],
        "total_quota": body["total_quota"],
        "gpa_threshold_x100": body["gpa_threshold_x100"],
        "eligible_majors": list(body["eligible_majors"]),
        "eligible_grades": list(body["eligible_grades"]),
        "family_income_ceiling_cents": body.get("family_income_ceiling_cents"),
        "required_materials": list(body["required_materials"]),
        "application_window_start": body["application_window_start"],
        "application_window_end": body["application_window_end"],
        "announcement_window_end": body["announcement_window_end"],
        "status": "DRAFT",
        "rubric_weights": dict(rw),
        "outlier_z_threshold_x100": int(body.get("outlier_z_threshold_x100", 200)),
    }
    db.stamp_create(entity, common_fields=True)
    db.scholarships[entity["id"]] = entity
    return success(db.public(entity), 201)


@bp.route("/scholarships/<scholarship_id>", methods=["GET"])
@require_auth(roles={"SchoolAdmin", "DeptOfficer", "FinanceOfficer", "Student", "Reviewer"})
def get_scholarship(scholarship_id):
    s = get_scholarship_or_404(scholarship_id)
    return success(db.public(s), 200)


@bp.route("/scholarships/<scholarship_id>", methods=["PATCH"])
@require_auth(roles={"SchoolAdmin"})
def update_scholarship(scholarship_id):
    s = get_scholarship_or_404(scholarship_id)
    body = get_body()
    check_version(s, body)
    if s["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Scholarship must be DRAFT to update")

    rubric_changed = False
    window_changed = False
    new_window_start = s["application_window_start"]
    new_window_end = s["application_window_end"]

    for k in ("name", "per_award_amount_cents", "required_materials", "outlier_z_threshold_x100"):
        if k in body:
            s[k] = body[k]

    if "rubric_weights" in body:
        rw = body["rubric_weights"]
        if not isinstance(rw, dict):
            raise err("ERR_BAD_REQUEST", "rubric_weights must be object")
        s["rubric_weights"] = dict(rw)
        rubric_changed = True

    if "application_window_start" in body or "application_window_end" in body:
        window_changed = True
        if "application_window_start" in body:
            new_window_start = body["application_window_start"]
            s["application_window_start"] = new_window_start
        if "application_window_end" in body:
            new_window_end = body["application_window_end"]
            s["application_window_end"] = new_window_end

    if rubric_changed:
        _check_rubric_sum(s["rubric_weights"])

    if window_changed:
        _check_window_overlap(s["category"], new_window_start, new_window_end, exclude_id=s["id"])

    db.stamp_update(s)
    return success(db.public(s), 200)


@bp.route("/scholarships/<scholarship_id>/state", methods=["POST"])
@require_auth(roles={"SchoolAdmin", "FinanceOfficer"})
def transition_state(scholarship_id):
    s = get_scholarship_or_404(scholarship_id)
    body = get_body()
    check_version(s, body)
    to_status = body.get("to_status")
    if to_status is None:
        raise err("ERR_BAD_REQUEST", "to_status required")

    # RBAC further refinement: FINALIZED→DISBURSED is FinanceOfficer only; all others SchoolAdmin only.
    role = g.user_role
    if to_status == "DISBURSED":
        if role != "FinanceOfficer":
            raise err("ERR_FORBIDDEN", "Only FinanceOfficer may transition to DISBURSED")
    else:
        if role != "SchoolAdmin":
            raise err("ERR_FORBIDDEN", "Only SchoolAdmin may transition to this status")

    # Step-wise transitions must be one step forward.
    from services.scholarship_lifecycle import ALL_STATUSES
    try:
        cur_idx = ALL_STATUSES.index(s["status"])
    except ValueError:
        raise err("ERR_INVALID_STATE", "Unknown current status")
    try:
        next_idx = ALL_STATUSES.index(to_status)
    except ValueError:
        raise err("ERR_INVALID_STATE", f"Unknown to_status {to_status}")
    if next_idx != cur_idx + 1:
        raise err("ERR_INVALID_STATE",
                  f"Cannot transition from {s['status']} to {to_status}")

    transition_scholarship(s, to_status, actor_role=g.user_role, actor_id=g.user_id)
    return success(db.public(s), 200)


# ---- QuotaAllocation -------------------------------------------------------

VALID_SPECIAL_GROUPS = {"NONE", "GENDER_FEMALE", "GENDER_MALE", "ETHNIC_MINORITY", "DISABILITY"}


@bp.route("/scholarships/<scholarship_id>/quota-allocations", methods=["POST"])
@require_auth(roles={"SchoolAdmin"})
def create_quota_allocation(scholarship_id):
    s = get_scholarship_or_404(scholarship_id)
    if s["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Scholarship must be DRAFT to add quota allocation")

    body = get_body()
    for f in ("department_code", "grade", "initial_slots"):
        if f not in body:
            raise err("ERR_BAD_REQUEST", f"Missing required field: {f}")
    if not isinstance(body["initial_slots"], int) or body["initial_slots"] < 0:
        raise err("ERR_BAD_REQUEST", "initial_slots must be non-negative integer")
    if not isinstance(body["grade"], int):
        raise err("ERR_BAD_REQUEST", "grade must be integer")
    sg = body.get("special_group", "NONE")
    if sg not in VALID_SPECIAL_GROUPS:
        raise err("ERR_BAD_REQUEST", f"unknown special_group: {sg}")

    entity = {
        "scholarship_id": s["id"],
        "department_code": body["department_code"],
        "grade": body["grade"],
        "special_group": sg,
        "initial_slots": body["initial_slots"],
        "current_slots": body["initial_slots"],
        "filled_slots": 0,
        "reallocated_from_ids": [],
    }
    db.stamp_create(entity, common_fields=True)
    db.quota_allocations[entity["id"]] = entity
    return success(db.public(entity), 201)


@bp.route("/scholarships/<scholarship_id>/quota-allocations", methods=["GET"])
@require_auth(roles={"SchoolAdmin", "DeptOfficer"})
def list_quota_allocations(scholarship_id):
    get_scholarship_or_404(scholarship_id)
    limit, offset = get_pagination()
    rows = [q for q in db.quota_allocations.values() if q["scholarship_id"] == scholarship_id]
    rows.sort(key=lambda q: q["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(q) for q in page], limit, offset, total)
