"""CreditLibraryEntry endpoints (PRD 3.2)."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth_headers, require_role
from response import ok, ok_list
from services import get_entry, ser_entry, sorted_created, stamp
from util import (
    CREDIT_CATEGORIES,
    PHASE_ELIGIBILITY,
    as_enum,
    as_int,
    as_bool,
    body,
    bool_filter,
    pagination_args,
    required,
    as_str,
)

bp = Blueprint("credit_library", __name__)


@bp.post("/credit-library-entries")
def create_entry():
    _user_id, role = auth_headers()
    data = body()
    credit_code = as_str(required(data, "credit_code"), "credit_code")
    title = as_str(required(data, "title"), "title")
    category = as_enum(required(data, "category"), CREDIT_CATEGORIES, "category")
    points_possible = as_int(required(data, "points_possible"), "points_possible")
    if points_possible < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "points_possible must be >= 0")
    is_prerequisite = as_bool(required(data, "is_prerequisite"), "is_prerequisite")
    phase_eligibility = as_enum(
        required(data, "phase_eligibility"), PHASE_ELIGIBILITY, "phase_eligibility"
    )
    requires_energy_model = as_bool(
        required(data, "requires_energy_model"), "requires_energy_model"
    )
    require_role(role, {"ProgramAdmin"})
    for e in DB["credit_library_entries"].values():
        if e["credit_code"] == credit_code:
            raise ApiError("ERR_INVALID_REQUEST", 400, "credit_code must be unique")
    rec = stamp(
        {
            "credit_code": credit_code,
            "title": title,
            "category": category,
            "points_possible": points_possible,
            "is_prerequisite": is_prerequisite,
            "phase_eligibility": phase_eligibility,
            "requires_energy_model": requires_energy_model,
        }
    )
    DB["credit_library_entries"][rec["id"]] = rec
    return ok(ser_entry(rec), status=201)


@bp.get("/credit-library-entries")
def list_entries():
    auth_headers()
    category = request.args.get("category")
    phase_eligibility = request.args.get("phase_eligibility")
    is_prerequisite = bool_filter(request.args.get("is_prerequisite"))
    items = list(DB["credit_library_entries"].values())
    if category is not None:
        items = [e for e in items if e["category"] == category]
    if phase_eligibility is not None:
        items = [e for e in items if e["phase_eligibility"] == phase_eligibility]
    if is_prerequisite is not None:
        items = [e for e in items if e["is_prerequisite"] == is_prerequisite]
    items = sorted_created(items)
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_entry(e) for e in page], total, limit, offset)


@bp.get("/credit-library-entries/<entry_id>")
def get_one_entry(entry_id):
    auth_headers()
    return ok(ser_entry(get_entry(entry_id)))
