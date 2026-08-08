"""Coverage records, verification and the sliding-fee determination."""

from flask import Blueprint

import calc
import clock
import serializers
import store
import validation as v
from constants import ENUM_PAYER_TYPE
from envelope import array_response, object_response
from errors import ApiError

bp = Blueprint("coverage", __name__)


@bp.route("/mobile-dentistry/coverages", methods=["POST"])
def create_coverage():
    v.authenticate(["BillingSpecialist", "SiteCoordinator", "ProgramAdmin"])
    body = v.body()
    patient = v.fk_row(body, "patient_id", "patients")

    v.need(body, "patient_id")
    if not isinstance(body.get("patient_id"), str):
        raise ApiError("ERR_VALIDATION", "Field 'patient_id' must be a string.")
    v.enum_type_check(body, "payer_type", required=True)
    payer_name = v.opt_string(body, "payer_name")
    member_id = v.opt_string(body, "member_id")

    supplied_type = body.get("payer_type")
    if supplied_type in ENUM_PAYER_TYPE and supplied_type != "UNINSURED" and not member_id:
        raise ApiError("ERR_VALIDATION", "member_id is required unless payer_type is UNINSURED.")

    payer_type = v.check_enum(body, "payer_type", ENUM_PAYER_TYPE)

    row = store.insert("coverages", {
        "patient_id": patient["id"],
        "payer_type": payer_type,
        "payer_name": payer_name,
        "member_id": member_id,
        "verification_status": "UNVERIFIED",
        "verified_through_date": None,
        "verified_at": None,
        "fpl_percent": None,
        "sliding_fee_band": None,
        "determination_date": None,
    })
    v.mark_minted(row)
    return object_response(serializers.coverage(row), 201)


@bp.route("/mobile-dentistry/coverages", methods=["GET"])
def list_coverages():
    v.authenticate(["ProgramAdmin", "SiteCoordinator", "BillingSpecialist"])
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all_rows("coverages"), {
        "patient_id": "patient_id",
        "payer_type": "payer_type",
        "verification_status": "verification_status",
    })
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.coverage, page), limit, offset, total)


@bp.route("/mobile-dentistry/coverages/<coverage_id>", methods=["GET"])
def read_coverage(coverage_id):
    v.authenticate(["ProgramAdmin", "SiteCoordinator", "BillingSpecialist"])
    row = v.path_row("coverages", coverage_id)
    return object_response(serializers.coverage(row), 200)


@bp.route("/mobile-dentistry/coverages/<coverage_id>/verify", methods=["POST"])
def verify_coverage(coverage_id):
    v.authenticate(["BillingSpecialist"])
    row = v.path_row("coverages", coverage_id)
    body = v.body()
    verified_through_date = v.req_date(body, "verified_through_date")
    if verified_through_date < clock.today():
        raise ApiError("ERR_VALIDATION", "verified_through_date must not be earlier than today.")

    if row["verification_status"] not in ("UNVERIFIED", "EXPIRED"):
        raise ApiError("ERR_INVALID_STATE")

    patient = store.get("patients", row["patient_id"])
    if row["payer_type"] == "UNINSURED" and patient.get("annual_household_income_cents") is None:
        raise ApiError("ERR_SLIDING_FEE_MISSING")

    row["verification_status"] = "VERIFIED"
    row["verified_through_date"] = verified_through_date
    row["verified_at"] = clock.now()
    if row["payer_type"] == "UNINSURED":
        percent, band = calc.sliding_fee(
            patient["household_size"], patient["annual_household_income_cents"]
        )
        row["fpl_percent"] = percent
        row["sliding_fee_band"] = band
        row["determination_date"] = clock.today()
    v.touch(row)
    return object_response(serializers.coverage(row), 200)
