"""Size chart mappings: coverage, supersession and the readiness axis (PRD 3.3)."""

from flask import Blueprint

import constants as C
import validate as V
from db import db, new_row, touch
from errors import ApiError
from lookup import (ensure_not_delisted, filtered, get_chart, get_item,
                    get_mapping)
from middleware import authenticate
from numeric import floor_div
from response import array_response, object_response
from services.derive import active_mapping_of_item, verified_specs_of_item

bp = Blueprint("size_chart_mappings", __name__)


@bp.post("/fit-program/size-chart-mappings")
def create_mapping():
    authenticate(C.ROLE_FIT_ANALYST)
    body = V.get_body()

    item_id = V.req_str(body, "item_id", min_len=1)
    chart_id = V.req_str(body, "chart_id", min_len=1)
    pairs = V.validate_size_label_pairs(body)
    expected_item_version = V.req_int(body, "expected_item_version")

    item = get_item(item_id)
    chart = get_chart(chart_id)
    ensure_not_delisted(item)

    if expected_item_version != item["version"]:
        raise ApiError("ERR_STALE_ITEM_VERSION",
                       "The catalog item is at version %d, not %d."
                       % (item["version"], expected_item_version))

    verified = verified_specs_of_item(item["id"])
    if len(verified) != 1:
        raise ApiError("ERR_SPEC_NOT_VERIFIED",
                       "The item must have exactly one VERIFIED measurement "
                       "specification.")
    spec = verified[0]

    if (chart["status"] != "STANDARDIZED"
            or chart["category_code"] != item["category_code"]):
        raise ApiError("ERR_CHART_NOT_STANDARDIZED",
                       "The chart must be STANDARDIZED and share the item's "
                       "category_code.")

    spec_labels = {point["size_label"] for point in spec["size_points"]}
    chart_labels = {row["size_label"] for row in chart["rows"]}
    for pair in pairs:
        if pair["spec_size_label"] not in spec_labels:
            raise ApiError("ERR_SIZE_LABEL_NOT_IN_SPEC",
                           "spec_size_label '%s' is not among the verified "
                           "specification's size_points." % pair["spec_size_label"])
        if pair["chart_size_label"] not in chart_labels:
            raise ApiError("ERR_SIZE_LABEL_NOT_IN_SPEC",
                           "chart_size_label '%s' is not among the chart's rows."
                           % pair["chart_size_label"])

    mapped_row_count = len(pairs)
    spec_size_point_count = len(spec["size_points"])
    coverage_bp = (floor_div(mapped_row_count * 10000, spec_size_point_count)
                   if spec_size_point_count else 0)
    claimed = {pair["spec_size_label"] for pair in pairs}
    unmapped = [point["size_label"]
                for point in sorted(spec["size_points"],
                                    key=lambda p: p["sort_index"])
                if point["size_label"] not in claimed]

    mapping = new_row({
        "item_id": item["id"],
        "chart_id": chart["id"],
        "size_label_pairs": pairs,
        "mapped_row_count": mapped_row_count,
        "spec_size_point_count": spec_size_point_count,
        "coverage_bp": coverage_bp,
        "unmapped_size_labels": unmapped,
        "status": "ACTIVE",
        "superseded_reason": None,
    })

    previous = active_mapping_of_item(item["id"])
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        previous["superseded_reason"] = "NEW_MAPPING"
        touch(previous)

    db.mappings[mapping["id"]] = mapping

    # the readiness axis reacts; the storefront axis is untouched
    item["fit_readiness"] = "CHART_MAPPED"
    touch(item)

    return object_response(mapping, 201)


@bp.get("/fit-program/size-chart-mappings/<mapping_id>")
def read_mapping(mapping_id):
    authenticate(C.ROLE_FIT_ANALYST, C.ROLE_MERCH_OPS_ADMIN)
    return object_response(get_mapping(mapping_id))


@bp.get("/fit-program/size-chart-mappings")
def list_mappings():
    authenticate(C.ROLE_FIT_ANALYST, C.ROLE_MERCH_OPS_ADMIN)
    limit, offset = V.pagination_params()
    rows = filtered(db.mappings.values(), {
        "item_id": "item_id",
        "chart_id": "chart_id",
        "status": "status",
    })
    page, meta = V.paginate(rows, limit, offset)
    return array_response(page, meta)
