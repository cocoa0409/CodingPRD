"""Equipment classes: create and list."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import ok, created, paginate
from services import domain
from validation import validate_body

bp = Blueprint("classes", __name__)


@bp.post("/equipment-classes")
def create_class():
    uid, role = get_context()
    require_roles(["BranchManager"])
    body = validate_body({
        "class_code": ("string", True),
        "category": ("enum", True, {"values": ["AERIAL_LIFT", "SCAFFOLD"]}),
        "max_working_height_ft": ("integer", True, {"min_exclusive": 0}),
        "min_rental_days": ("integer", True, {"min": 1}),
        "daily_rate_cents": ("integer", True, {"min": 0}),
        "weekly_rate_cents": ("integer", True, {"min": 0}),
        "monthly_rate_cents": ("integer", True, {"min": 0}),
        "replacement_value_cents": ("integer", True, {"min": 0}),
        "requires_familiarization": ("boolean", False, {"default": False}),
        "requires_engineering": ("boolean", False, {"default": False}),
    })
    for existing in store.classes.values():
        if existing["class_code"] == body["class_code"]:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "class_code must be unique across all equipment classes")
    cls = db.new_common({
        "id": db.new_id(),
        "class_code": body["class_code"],
        "category": body["category"],
        "max_working_height_ft": body["max_working_height_ft"],
        "min_rental_days": body["min_rental_days"],
        "daily_rate_cents": body["daily_rate_cents"],
        "weekly_rate_cents": body["weekly_rate_cents"],
        "monthly_rate_cents": body["monthly_rate_cents"],
        "replacement_value_cents": body["replacement_value_cents"],
        "requires_familiarization": body["requires_familiarization"],
        "requires_engineering": body["requires_engineering"],
    })
    store.classes[cls["id"]] = cls
    return created(domain.view_class(cls))


@bp.get("/equipment-classes")
def list_classes():
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "Customer"])
    rows = [domain.view_class(c) for c in store.classes.values()]
    return ok(paginate(rows), rtype="array", pagination=paginate)
