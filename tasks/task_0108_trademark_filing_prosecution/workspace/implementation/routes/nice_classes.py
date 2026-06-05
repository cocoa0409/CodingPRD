"""Nice class routes (PRD §3.1). NiceClass is an immutable reference record."""

from flask import Blueprint

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services import models
from services.body import get_json_body, require_int, require_nonempty_string
from services.pagination import parse_pagination, slice_sorted

bp = Blueprint("nice_classes", __name__)


@bp.post("/nice-classes")
@require_roles("Examiner")
def create_nice_class(_user_id, _role):
    body = get_json_body()
    class_number = require_int(body, "class_number")
    title = require_nonempty_string(body, "title")
    if class_number < 1 or class_number > 45:
        raise_api("ERR_VALIDATION", "class_number must be an integer 1..45")

    for nc in db.nice_classes.values():
        if nc["class_number"] == class_number:
            raise_api("ERR_DUPLICATE_NICE_CLASS", "class_number already seeded")

    # NiceClass carries only id + created_at (no updated_at/version).
    rec = models.make_record(
        {"class_number": class_number, "title": title}, common=False
    )
    db.nice_classes[rec["id"]] = rec
    return success(models.ser_nice_class(rec), 201)


@bp.get("/nice-classes/<rid>")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def get_nice_class(rid, _user_id, _role):
    rec = models.get_or_404(db.nice_classes, rid, "NiceClass")
    return success(models.ser_nice_class(rec), 200)


@bp.get("/nice-classes/<rid>/goods-services")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def list_nice_class_goods(rid, _user_id, _role):
    models.get_or_404(db.nice_classes, rid, "NiceClass")
    limit, offset = parse_pagination()
    items = [
        gs for gs in db.goods_services.values() if gs["nice_class_id"] == rid
    ]
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [models.ser_goods_services(g) for g in page], limit, offset, total
    )
