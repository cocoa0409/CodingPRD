"""LicenseProgram + QuestionItem routes (PRD §3.1)."""
from decimal import Decimal
from flask import Blueprint, request

from db import db, stamp_create, touch
from response import success, list_success
from middleware import get_auth, require_role, pagination_params, paginate
from services import validate as V
from services.serialize import public, public_list
from services.lookups import get_license_program
from errors import raise_err
import errors

bp = Blueprint("license_programs", __name__)


def _validate_domain_weights(value):
    if not isinstance(value, list) or len(value) < 1:
        raise_err(errors.ERR_INVALID_REQUEST, "domain_weights must be a non-empty array")
    cleaned = []
    total = Decimal("0")
    for entry in value:
        if not isinstance(entry, dict):
            raise_err(errors.ERR_INVALID_REQUEST, "domain_weights entry must be an object")
        dc = entry.get("domain_code")
        w = entry.get("weight")
        if not isinstance(dc, str) or dc == "":
            raise_err(errors.ERR_INVALID_REQUEST, "domain_code must be a non-empty string")
        if isinstance(w, bool) or not isinstance(w, (int, float)):
            raise_err(errors.ERR_INVALID_REQUEST, "weight must be a number")
        if w <= 0:
            raise_err(errors.ERR_INVALID_REQUEST, "weight must be strictly > 0")
        total += Decimal(str(w))
        cleaned.append({"domain_code": dc, "weight": w})
    # weights must sum to exactly 1.00 measured to two decimals.
    if total.quantize(Decimal("0.01")) != Decimal("1.00"):
        raise_err(errors.ERR_INVALID_REQUEST, "weights must sum to 1.00")
    return cleaned


@bp.post("/license-programs")
def create_program():
    _, role = get_auth()
    require_role(role, {"ContentAdmin"})
    data = V.body()
    license_code = V.as_str(V.require(data, "license_code"), "license_code")
    title = V.as_str(V.require(data, "title"), "title")
    passing = V.as_int(V.require(data, "passing_scaled_score"),
                       "passing_scaled_score", minimum=0, maximum=100)
    weights = _validate_domain_weights(V.require(data, "domain_weights"))
    # license_code unique among programs.
    for p in db.license_programs.values():
        if p["license_code"] == license_code:
            raise_err(errors.ERR_INVALID_REQUEST, "license_code must be unique")
    rec = {
        "license_code": license_code,
        "title": title,
        "passing_scaled_score": passing,
        "domain_weights": weights,
        "status": "DRAFT",
    }
    stamp_create(rec)
    db.license_programs[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/license-programs/<pid>")
def get_program(pid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner", "ExamProctor"})
    rec = get_license_program(pid)
    return success(public(rec))


@bp.get("/license-programs")
def list_programs():
    _, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner", "ExamProctor"})
    limit, offset = pagination_params()
    rows = list(db.license_programs.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


@bp.post("/license-programs/<pid>/items")
def add_item(pid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin"})
    program = get_license_program(pid)
    data = V.body()
    domain_code = V.as_str(V.require(data, "domain_code"), "domain_code")
    difficulty = V.as_enum(V.require(data, "difficulty"), "difficulty",
                           {"EASY", "MEDIUM", "HARD"})
    correct_choice = V.as_str(V.require(data, "correct_choice"), "correct_choice")
    # domain_code must be one of the program's blueprint codes (priority 8).
    blueprint_codes = {d["domain_code"] for d in program["domain_weights"]}
    if domain_code not in blueprint_codes:
        raise_err(errors.ERR_REFERENCE_INCOMPATIBLE, "domain_code not in program blueprint")
    rec = {
        "license_program_id": pid,
        "domain_code": domain_code,
        "difficulty": difficulty,
        "correct_choice": correct_choice,
    }
    # QuestionItem is immutable: id + created_at only (no updated_at / version).
    stamp_create(rec, with_version=False)
    db.question_items[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/license-programs/<pid>/items")
def list_items(pid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner", "ExamProctor"})
    get_license_program(pid)
    limit, offset = pagination_params()
    rows = [i for i in db.question_items.values() if i["license_program_id"] == pid]
    domain_code = request.args.get("domain_code")
    if domain_code is not None:
        rows = [r for r in rows if r["domain_code"] == domain_code]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


@bp.post("/license-programs/<pid>/publish")
def publish_program(pid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin"})
    program = get_license_program(pid)
    if program["status"] != "DRAFT":
        raise_err(errors.ERR_INVALID_STATE, "program not in DRAFT")
    # precondition: domain_weights non-empty and sum == 1.00
    weights = program["domain_weights"]
    total = Decimal("0")
    for d in weights:
        total += Decimal(str(d["weight"]))
    if not weights or total.quantize(Decimal("0.01")) != Decimal("1.00"):
        raise_err(errors.ERR_BLUEPRINT_WEIGHTS_INVALID, "blueprint weights invalid")
    # precondition: at least one QuestionItem exists
    has_item = any(i["license_program_id"] == pid for i in db.question_items.values())
    if not has_item:
        raise_err(errors.ERR_PROGRAM_HAS_NO_ITEMS, "program has no items")
    program["status"] = "PUBLISHED"
    touch(program)
    return success(public(program))


@bp.post("/license-programs/<pid>/retire")
def retire_program(pid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin"})
    program = get_license_program(pid)
    if program["status"] != "PUBLISHED":
        raise_err(errors.ERR_INVALID_STATE, "program not PUBLISHED")
    # precondition: no ACTIVE enrollment references this program
    for e in db.enrollments.values():
        if e["license_program_id"] == pid and e["status"] == "ACTIVE":
            raise_err(errors.ERR_PROGRAM_HAS_ACTIVE_ENROLLMENTS,
                      "program has active enrollments")
    program["status"] = "RETIRED"
    touch(program)
    return success(public(program))
