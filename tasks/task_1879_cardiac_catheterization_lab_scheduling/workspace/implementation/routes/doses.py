"""DoseRecord endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import STORE
from errors import (
    ApiError,
    ERR_CASE_INVALID_STATE,
    ERR_CASE_NOT_FOUND,
    ERR_CONTRAST_LIMIT_EXCEEDED,
    ERR_DOSE_RECORD_ALREADY_VOIDED,
    ERR_DOSE_RECORD_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from helpers import (
    RECORD_TYPES,
    get_payload,
    new_id,
    opt_num,
    paginate,
    req_enum,
)
from middleware import ALL_ROLES, require_roles
from response import success
from services import (
    D,
    dose_record_out,
    new_entity,
    recompute_case_doses,
    round1,
    round2,
    touch,
)

bp = Blueprint("doses", __name__)


@bp.route("/cath-lab/cases/<case_id>/dose-records", methods=["POST"])
@require_roles("CathLabTechnologist")
def create_dose_record(case_id):
    case = STORE["cases"].get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, "No CathCase with the given id", 404)
    data = get_payload()
    # Priority 4: shape — per-record-type required fields, and fields supplied
    # out of place are rejected.
    record_type = req_enum(data, "record_type", RECORD_TYPES)
    contrast_ml = None
    fluoroscopy_mgy = None
    cine_mgy = None
    if record_type == "CONTRAST":
        if data.get("contrast_ml") is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "contrast_ml is required for a CONTRAST record",
                400,
            )
        contrast_ml = opt_num(data, "contrast_ml", ge=0)
        if data.get("fluoroscopy_mgy") is not None or data.get("cine_mgy") is not None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "fluoroscopy_mgy and cine_mgy are not accepted on a CONTRAST record",
                400,
            )
        contrast_ml = round1(contrast_ml)
    else:
        if data.get("fluoroscopy_mgy") is None or data.get("cine_mgy") is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "fluoroscopy_mgy and cine_mgy are required for a RADIATION record",
                400,
            )
        if data.get("contrast_ml") is not None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "contrast_ml is not accepted on a RADIATION record",
                400,
            )
        fluoroscopy_mgy = opt_num(data, "fluoroscopy_mgy", ge=0)
        cine_mgy = opt_num(data, "cine_mgy", ge=0)
    # Priority 5: parent case state gate.
    if case["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_CASE_INVALID_STATE,
            "Dose records may only be recorded on an IN_PROGRESS case",
            409,
        )
    # Priority 6: contrast ceiling (projected == limit is allowed).
    if record_type == "CONTRAST":
        projected = D(case["cumulative_contrast_ml"]) + contrast_ml
        if projected > D(case["contrast_limit_ml"]):
            raise ApiError(
                ERR_CONTRAST_LIMIT_EXCEEDED,
                "Projected cumulative contrast exceeds the patient's contrast limit",
                422,
            )

    record = new_entity()
    record["id"] = new_id()
    if record_type == "CONTRAST":
        record_total = Decimal("0")
    else:
        record_total = round2(D(fluoroscopy_mgy) + D(cine_mgy))
    record.update(
        {
            "case_id": case_id,
            "record_type": record_type,
            "contrast_ml": contrast_ml,
            "fluoroscopy_mgy": fluoroscopy_mgy,
            "cine_mgy": cine_mgy,
            "record_total_mgy": record_total,
            "status": "ACTIVE",
        }
    )
    STORE["dose_records"][record["id"]] = record
    # Recompute case cumulative totals and latch the radiation alert; each
    # creation advances the case version by one (PRD 3.6).
    recompute_case_doses(case)
    return success(dose_record_out(record), 201)


@bp.route("/cath-lab/cases/<case_id>/dose-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_dose_records(case_id):
    case = STORE["cases"].get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, "No CathCase with the given id", 404)
    record_type = request.args.get("record_type")
    status = request.args.get("status")
    items = []
    for r in STORE["dose_records"].values():
        if r["case_id"] != case_id:
            continue
        if record_type is not None and r["record_type"] != record_type:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    items.sort(key=lambda r: r["_seq"])
    page, pg = paginate(items)
    return success([dose_record_out(r) for r in page], 200, is_list=True, pagination=pg)


@bp.route("/cath-lab/dose-records/<record_id>/void", methods=["POST"])
@require_roles("CathLabTechnologist")
def void_dose_record(record_id):
    record = STORE["dose_records"].get(record_id)
    if record is None:
        raise ApiError(ERR_DOSE_RECORD_NOT_FOUND, "No DoseRecord with the given id", 404)
    case = STORE["cases"].get(record["case_id"])
    if case is None or case["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_CASE_INVALID_STATE,
            "Voiding requires the parent case to be IN_PROGRESS",
            409,
        )
    if record["status"] != "ACTIVE":
        raise ApiError(
            ERR_DOSE_RECORD_ALREADY_VOIDED,
            "Dose record is already VOIDED",
            409,
        )
    record["status"] = "VOIDED"
    touch(record)
    # Compensating action: recompute both cumulative totals over the remaining
    # ACTIVE records. radiation_alert stays latched even if the recomputed
    # total drops below the threshold.
    recompute_case_doses(case)
    return success(dose_record_out(record), 200)
