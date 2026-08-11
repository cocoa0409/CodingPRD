from flask import Blueprint, request

import serializers
import validation as V
from envelope import object_response, paginate
from errors import ApiError
from lookups import path_row, require_record_state
from store import db

bp = Blueprint("fee_assessments", __name__)


@bp.get("/livescan/fee-assessments/<id>")
def read_assessment(id):
    return object_response(serializers.assessment(path_row("assessments", id)))


@bp.get("/livescan/fee-assessments")
def list_assessments():
    rows = list(db.assessments.values())
    for field in (
        "agency_id",
        "submission_id",
        "appointment_id",
        "invoice_id",
        "assessment_kind",
        "status",
    ):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(rows, serializers.assessment)


@bp.post("/livescan/fee-assessments/<id>/payments")
def pay_assessment(id):
    assessment = path_row("assessments", id)
    data = V.body()
    amount_cents = V.req_int(data, "amount_cents", minimum=1)

    require_record_state(assessment["status"] == "ASSESSED", "assessment is %s" % assessment["status"])
    if assessment["payer_regime"] != "APPLICANT_PAID":
        raise ApiError(
            "ERR_PAYER_REGIME_MISMATCH", "only APPLICANT_PAID assessments settle at the counter"
        )
    if amount_cents != assessment["total_cents"] - assessment["paid_cents"]:
        raise ApiError("ERR_INVALID_REQUEST", "the payment must equal the outstanding balance")

    assessment["paid_cents"] = assessment["total_cents"]
    assessment["status"] = "PAID"
    db.touch(assessment)
    return object_response(serializers.assessment(assessment))
