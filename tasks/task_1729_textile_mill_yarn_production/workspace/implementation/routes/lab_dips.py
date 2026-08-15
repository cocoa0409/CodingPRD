"""LabDip endpoints.

Approval requires PENDING and measured_delta_e <= ShadeBand.delta_e_tolerance;
a dip whose measured difference exceeds tolerance -> ERR_SHADE_OUT_OF_BAND.
"""

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import (
    err_invalid_state,
    err_not_found,
    err_reference_not_found,
    err_shade_out_of_band,
)
from middleware import get_user_id, require_roles
from response import success_list, success_object
from serializers import serialize_lab_dip
from services.workflows import touch
from validators import (
    apply_filters,
    get_json_body,
    get_pagination,
    req_decimal,
    req_string,
    round3,
    sort_and_paginate,
)

bp = Blueprint("lab_dips", __name__)

READ_ROLES = ("DyeHouseOperator", "CustomerServiceRep", "QualityInspector")


def _get_dip_or_404(did):
    record = db.lab_dips.get(did)
    if record is None:
        raise err_not_found("Lab dip not found")
    return record


@bp.post("/mill/lab-dips")
def create_lab_dip():
    require_roles("DyeHouseOperator")
    body = get_json_body()
    shade_band_id = req_string(body, "shade_band_id")
    measured_delta_e = req_decimal(body, "measured_delta_e", min_value=0)

    band = db.shade_bands.get(shade_band_id)
    if band is None:
        raise err_reference_not_found("shade_band_id does not resolve to an existing shade band")

    ts = now_iso()
    record = {
        "id": new_id(),
        "shade_band_id": band["id"],
        "submitted_by_operator_id": get_user_id(),
        "measured_delta_e": round3(measured_delta_e),
        "status": "PENDING",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.lab_dips[record["id"]] = record
    return success_object(serialize_lab_dip(record), 201)


@bp.get("/mill/lab-dips")
def list_lab_dips():
    require_roles(*READ_ROLES)
    limit, offset = get_pagination()
    items = apply_filters(
        list(db.lab_dips.values()),
        {"shade_band_id": request.args.get("shade_band_id"), "status": request.args.get("status")},
    )
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([serialize_lab_dip(r) for r in page], limit, offset, total)


@bp.get("/mill/lab-dips/<did>")
def get_lab_dip(did):
    require_roles(*READ_ROLES)
    return success_object(serialize_lab_dip(_get_dip_or_404(did)))


@bp.post("/mill/lab-dips/<did>/approve")
def approve_lab_dip(did):
    require_roles("CustomerServiceRep")
    record = _get_dip_or_404(did)
    if record["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING lab dip can be approved")
    band = db.shade_bands.get(record["shade_band_id"])
    if band is not None and record["measured_delta_e"] > band["delta_e_tolerance"]:
        raise err_shade_out_of_band("LabDip measured_delta_e exceeds ShadeBand tolerance")
    record["status"] = "APPROVED"
    touch(record)
    return success_object(serialize_lab_dip(record))


@bp.post("/mill/lab-dips/<did>/reject")
def reject_lab_dip(did):
    require_roles("CustomerServiceRep")
    record = _get_dip_or_404(did)
    if record["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING lab dip can be rejected")
    record["status"] = "REJECTED"
    touch(record)
    return success_object(serialize_lab_dip(record))
