"""Submission category endpoints."""

from decimal import Decimal

from flask import Blueprint

from db import db, new_row
from errors import fail
from middleware import (ROLE_ADMIN, ROLE_AUTHOR, ROLE_CHAIR, ROLE_PRESS,
                        ROLE_REVIEWER, endpoint)
from response import created, ok, ok_list
from routes.helpers import filtered, lookup, resolve_fk
from services import derive
from validators import (body_json, paginate, q_bool, q_str, v_bool, v_decimal,
                        v_int, v_str_list, v_string)

bp = Blueprint("categories", __name__)

FORMATS = ("ORAL", "POSTER", "WORKSHOP")


@bp.post("/categories")
@endpoint(ROLE_ADMIN)
def create_category(actor):
    body = body_json()
    conference = resolve_fk(body, "conference_id")
    code = v_string(body, "code", required=True, min_len=2, max_len=16)
    name = v_string(body, "name", required=True, min_len=1, max_len=200)
    max_word_count = v_int(body, "max_word_count", required=True, minimum=100, maximum=600)
    requires_structured_body = v_bool(body, "requires_structured_body", default=False)
    allowed_formats = v_str_list(body, "allowed_formats", required=True, min_items=1,
                                 max_items=3, unique=True, allowed=FORMATS)
    min_reviews_required = v_int(body, "min_reviews_required", minimum=2, maximum=5, default=3)
    threshold = v_decimal(body, "discrepancy_threshold", minimum=Decimal("0.50"),
                          maximum=Decimal("4.00"), default=Decimal("2.50"))
    cme_eligible = v_bool(body, "cme_eligible", default=False)
    if conference is None:
        fail("ERR_VALIDATION", "conference_id is required.")
    if threshold.as_tuple().exponent < -2:
        fail("ERR_VALIDATION", "discrepancy_threshold supports at most two decimal places.")
    threshold = threshold.quantize(Decimal("0.01"))

    for existing in db.categories.values():
        if existing["conference_id"] == conference["id"] and existing["code"] == code:
            fail("ERR_VALIDATION", "code must be unique within the conference.")

    row = new_row({
        "conference_id": conference["id"],
        "code": code,
        "name": name,
        "max_word_count": max_word_count,
        "requires_structured_body": requires_structured_body,
        "allowed_formats": allowed_formats,
        "min_reviews_required": min_reviews_required,
        "discrepancy_threshold": threshold,
        "cme_eligible": cme_eligible,
    })
    db.categories[row["id"]] = row
    return created(derive.category_out(row))


@bp.get("/categories")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR, ROLE_PRESS)
def list_categories(actor):
    rows = filtered(db.categories.values(), {
        "conference_id": q_str("conference_id"),
        "cme_eligible": q_bool("cme_eligible"),
    })
    page, meta = paginate(rows)
    return ok_list([derive.category_out(r) for r in page], meta)


@bp.get("/categories/<category_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR, ROLE_PRESS)
def get_category(actor, category_id):
    row = lookup("categories", category_id, "ERR_CATEGORY_NOT_FOUND")
    return ok(derive.category_out(row))
