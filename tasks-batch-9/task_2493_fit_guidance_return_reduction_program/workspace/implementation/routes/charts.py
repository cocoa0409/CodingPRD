"""Size charts: standardization and the retirement cascade (PRD 3.3)."""

from flask import Blueprint

import constants as C
import validate as V
from db import db, new_row, ordered, touch
from errors import ApiError
from lookup import get_chart
from middleware import authenticate
from numeric import floor_div
from response import object_response
from services.derive import (readiness_fall_to_unverified,
                             terminate_readiness_deployments)

bp = Blueprint("size_charts", __name__)


def _median_row_index(row_count):
    return floor_div(row_count - 1, 2) if row_count > 0 else 0


@bp.post("/fit-program/size-charts")
def create_chart():
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    body = V.get_body()

    chart_code = V.req_str(body, "chart_code", min_len=3, max_len=16)
    size_system = V.req_enum(body, "size_system", C.SIZE_SYSTEMS)
    category_code = V.req_enum(body, "category_code", C.CATEGORY_CODES)
    rows = V.validate_chart_rows(body)

    for existing in db.charts.values():
        if existing["chart_code"] == chart_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE_KEY",
                           "chart_code '%s' already exists." % chart_code)

    chart = new_row({
        "chart_code": chart_code,
        "size_system": size_system,
        "category_code": category_code,
        "status": "DRAFT",
        "rows": rows,
        "row_count": len(rows),
        "median_row_index": _median_row_index(len(rows)),
        "retire_reason_code": None,
    })
    db.charts[chart["id"]] = chart
    return object_response(chart, 201)


@bp.get("/fit-program/size-charts/<chart_id>")
def read_chart(chart_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_FIT_ANALYST)
    return object_response(get_chart(chart_id))


@bp.post("/fit-program/size-charts/<chart_id>/standardize")
def standardize_chart(chart_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    chart = get_chart(chart_id)
    if chart["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CHART_STATE",
                       "Only a DRAFT chart can be standardized; this one is %s."
                       % chart["status"])
    _check_row_integrity(chart["rows"])

    chart["status"] = "STANDARDIZED"
    chart["row_count"] = len(chart["rows"])
    chart["median_row_index"] = _median_row_index(chart["row_count"])
    touch(chart)
    return object_response(chart)


def _check_row_integrity(rows):
    """Rank 22: contiguity, chest monotonicity, conversion completeness."""
    def invalid(message):
        return ApiError("ERR_CHART_ROWS_INVALID", message)

    indexes = sorted(row["sort_index"] for row in rows)
    if indexes != list(range(len(rows))):
        raise invalid("Chart row sort_index values must be contiguous from 0.")

    in_order = sorted(rows, key=lambda row: row["sort_index"])
    previous = None
    for row in in_order:
        if row["body_chest_min_mm"] > row["body_chest_max_mm"]:
            raise invalid("Each row's body_chest_min_mm must not exceed its "
                          "body_chest_max_mm.")
        if previous is not None:
            if row["body_chest_min_mm"] <= previous["body_chest_max_mm"]:
                raise invalid("Body-chest ranges must be strictly increasing and "
                              "non-overlapping across consecutive rows.")
        for column in ("conversion_us_alpha", "conversion_us_numeric",
                       "conversion_eu", "conversion_uk"):
            value = row.get(column)
            if not isinstance(value, str) or value.strip() == "":
                raise invalid("Every row must carry a non-empty '%s'." % column)
        previous = row


@bp.post("/fit-program/size-charts/<chart_id>/retire")
def retire_chart(chart_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    chart = get_chart(chart_id)
    body = V.get_body()
    retire_reason_code = V.req_enum(body, "retire_reason_code",
                                    C.RETIRE_REASON_CODES)
    if chart["status"] != "STANDARDIZED":
        raise ApiError("ERR_INVALID_CHART_STATE",
                       "Only a STANDARDIZED chart can be retired; this one is %s."
                       % chart["status"])

    chart["status"] = "RETIRED"
    chart["retire_reason_code"] = retire_reason_code
    touch(chart)

    # four entities move on one request
    affected = ordered([m for m in db.mappings.values()
                        if m["chart_id"] == chart["id"] and m["status"] == "ACTIVE"])
    for mapping in affected:
        mapping["status"] = "SUPERSEDED"
        mapping["superseded_reason"] = "CHART_RETIRED"
        touch(mapping)
        item = db.items.get(mapping["item_id"])
        if item is None:
            continue
        if readiness_fall_to_unverified(item):
            terminate_readiness_deployments(item)

    return object_response(chart)
