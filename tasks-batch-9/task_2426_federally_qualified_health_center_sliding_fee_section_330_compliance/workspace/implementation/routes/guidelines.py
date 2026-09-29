"""The globally published federal poverty guideline table (immutable rows)."""

from flask import Blueprint

import db
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authorize
from response import object_response
from routes.common import listing, require
from validation import Field, pagination, parse_body

bp = Blueprint("guidelines", __name__)

CREATE_FIELDS = [
    Field("guideline_year", "integer", required=True, minimum=2000, maximum=2100),
    Field("base_amount_cents", "integer", required=True, exclusive_min=0),
    Field("increment_cents", "integer", required=True, exclusive_min=0),
]


@bp.post("/poverty-guidelines")
def create_guideline():
    authorize("PlatformAdmin")
    body = parse_body(CREATE_FIELDS)

    for row in db.db.poverty_guidelines.values():
        if row["guideline_year"] == body["guideline_year"]:
            raise ApiError("ERR_DUPLICATE_KEY")

    row = db.base_row(versioned=False)
    row.update(
        {
            "guideline_year": body["guideline_year"],
            "base_amount_cents": body["base_amount_cents"],
            "increment_cents": body["increment_cents"],
        }
    )
    db.db.poverty_guidelines[row["id"]] = row
    return object_response(serializers.poverty_guideline(row), 201)


@bp.get("/poverty-guidelines/<guideline_id>")
def read_guideline(guideline_id):
    authorize(*ALL_ROLES)
    return object_response(
        serializers.poverty_guideline(require("poverty_guidelines", guideline_id))
    )


@bp.get("/poverty-guidelines")
def list_guidelines():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    return listing(
        db.all_rows("poverty_guidelines"),
        serializers.poverty_guideline,
        limit,
        offset,
        specs=[("guideline_year", "guideline_year", "integer")],
    )
