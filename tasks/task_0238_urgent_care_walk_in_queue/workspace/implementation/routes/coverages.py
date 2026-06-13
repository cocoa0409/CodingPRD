"""Coverage endpoints (PRD §3.4)."""
from flask import Blueprint, request

import clock
import serialize
from db import db, stamp_create, touch
from errors import err
from middleware import authorize
from response import ok_object, ok_array
from validation import get_json_body, parse_pagination, paginate
from routes.lookup import get_path, get_fk

bp = Blueprint("coverages", __name__)

READ_ROLES = ["ClinicManager", "FrontDeskClerk", "Provider"]
COVERAGE_TYPES = {"INSURANCE", "SELF_PAY"}
VERIFY_OUTCOMES = {"ELIGIBLE", "INELIGIBLE"}


@bp.route("/coverages", methods=["POST"])
def create_coverage():
    authorize(["FrontDeskClerk"])
    body = get_json_body()

    patient_id = body.get("patient_id")
    if patient_id is None:
        raise err("ERR_INVALID_REQUEST", "patient_id required")
    patient = get_fk("patient", patient_id)

    coverage_type = body.get("coverage_type")
    if coverage_type not in COVERAGE_TYPES:
        raise err("ERR_INVALID_REQUEST", "invalid coverage_type")

    copay = body.get("copay_cents", 0)
    if not isinstance(copay, int) or isinstance(copay, bool) or copay < 0:
        raise err("ERR_INVALID_REQUEST", "copay_cents must be an integer >= 0")

    payer_name = body.get("payer_name")
    member_id = body.get("member_id")

    if coverage_type == "INSURANCE":
        if not payer_name or not member_id:
            raise err("ERR_COVERAGE_TYPE_MISMATCH",
                      "INSURANCE coverage requires payer_name and member_id")
    else:
        # SELF_PAY ignores payer/member/copay.
        payer_name = None
        member_id = None
        copay = 0

    coverage = stamp_create({
        "patient_id": patient["id"],
        "coverage_type": coverage_type,
        "payer_name": payer_name,
        "member_id": member_id,
        "copay_cents": copay,
        "eligibility_status": "UNVERIFIED",
        "verified_at": None,
    })
    db.coverages[coverage["id"]] = coverage
    return ok_object(serialize.coverage(coverage), 201)


@bp.route("/coverages", methods=["GET"])
def list_coverages():
    authorize(READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.coverages.values())
    patient_id = request.args.get("patient_id")
    if patient_id is not None:
        items = [c for c in items if c["patient_id"] == patient_id]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.coverage(c) for c in page], limit, offset, len(items))


@bp.route("/coverages/<coverage_id>", methods=["GET"])
def get_coverage(coverage_id):
    authorize(READ_ROLES)
    coverage = get_path("coverage", coverage_id)
    return ok_object(serialize.coverage(coverage))


@bp.route("/coverages/<coverage_id>/verify", methods=["POST"])
def verify_coverage(coverage_id):
    authorize(["FrontDeskClerk"])
    coverage = get_path("coverage", coverage_id)
    body = get_json_body()
    outcome = body.get("outcome")
    if outcome not in VERIFY_OUTCOMES:
        raise err("ERR_INVALID_REQUEST", "outcome must be ELIGIBLE or INELIGIBLE")

    # Verification is defined only from UNVERIFIED and only for INSURANCE.
    # A SELF_PAY coverage (or one already resolved) has no verify transition.
    if coverage["eligibility_status"] != "UNVERIFIED" or coverage["coverage_type"] != "INSURANCE":
        raise err("ERR_INVALID_STATE", "verify not defined for this coverage")

    coverage["eligibility_status"] = "ELIGIBLE" if outcome == "ELIGIBLE" else "INELIGIBLE"
    coverage["verified_at"] = clock.now()
    touch(coverage)
    return ok_object(serialize.coverage(coverage))
