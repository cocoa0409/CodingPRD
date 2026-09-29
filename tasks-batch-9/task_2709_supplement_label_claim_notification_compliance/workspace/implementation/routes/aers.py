"""Adverse event reports: intake, triage and agency filing (PRD 3.6)."""

from flask import Blueprint

import auth
import calc
import cascade
import db
import errors
import response
import serialize
import validate
from errors import fail
from routes.helpers import PREFIX, fk_row, listing, path_row

bp = Blueprint("adverse_event_reports", __name__)

READ_ROLES = (
    auth.ROLE_QA,
    auth.ROLE_SPECIALIST,
    auth.ROLE_APPROVAL,
    auth.ROLE_AUDITOR,
)


@bp.route(PREFIX + "/adverse-event-reports", methods=["POST"])
@auth.endpoint([auth.ROLE_QA, auth.ROLE_SPECIALIST])
def create_aer():
    body = validate.body()
    product_id = validate.req_str(body, "product_id")
    reporter_type = validate.req_enum(body, "reporter_type", calc.REPORTER_TYPES)
    received_date = validate.req_date(body, "received_date")
    narrative = validate.req_str(body, "narrative")
    outcome_codes = validate.req_str_array(body, "outcome_codes")
    for code in outcome_codes:
        if code not in calc.OUTCOME_CODES:
            fail(errors.ERR_VALIDATION, "outcome_codes contains an unknown code: %s." % code)

    fk_row("products", product_id, errors.ERR_PRODUCT_NOT_FOUND)

    row = db.base_fields()
    row.update(
        {
            "product_id": product_id,
            "reporter_type": reporter_type,
            "received_date": received_date,
            "narrative": narrative,
            "outcome_codes": list(outcome_codes),
            "is_serious": False,
            "aer_status": "RECEIVED",
            "submission_due_date": None,
            "submitted_at": None,
            "submission_timeliness": None,
            "submission_reference": None,
            # The six-year recordkeeping horizon is minted at intake, not at triage.
            "retention_until": calc.retention_date(received_date),
            "triaged_at": None,
        }
    )
    db.insert("aers", row)
    return response.object_response(serialize.aer(row), 201)


@bp.route(PREFIX + "/adverse-event-reports/<row_id>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def get_aer(row_id):
    row = path_row("aers", row_id, errors.ERR_AER_NOT_FOUND)
    return response.object_response(serialize.aer(row))


@bp.route(PREFIX + "/adverse-event-reports", methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_aers():
    return listing(
        "aers",
        serialize.aer,
        filters=("product_id", "aer_status"),
        bool_filters=("is_serious",),
    )


@bp.route(PREFIX + "/adverse-event-reports/<row_id>/triage", methods=["POST"])
@auth.endpoint([auth.ROLE_QA])
def triage_aer(row_id):
    row = path_row("aers", row_id, errors.ERR_AER_NOT_FOUND)
    body = validate.body()
    override = validate.opt_bool(body, "serious_override", default=False)

    if row["aer_status"] != "RECEIVED":
        fail(errors.ERR_AER_STATE_INVALID, "Only a RECEIVED report may be triaged.")

    intersects = any(code in calc.SERIOUS_OUTCOME_CODES for code in row["outcome_codes"])
    serious = bool(intersects or override is True)

    row["triaged_at"] = db.now()
    row["is_serious"] = serious
    if serious:
        row["aer_status"] = "TRIAGED_SERIOUS"
        row["submission_due_date"] = calc.business_day_due_date(row["received_date"])
    else:
        row["aer_status"] = "TRIAGED_NONSERIOUS"
        row["submission_due_date"] = None
    row["retention_until"] = calc.retention_date(row["received_date"])
    db.touch(row)

    product = db.get("products", row["product_id"])
    if product is not None:
        if serious:
            product["serious_ae_count"] += 1
        else:
            product["nonserious_ae_count"] += 1
        db.touch(product)
        cascade.recompute_risk_index(product)

    return response.object_response(serialize.aer(row))


@bp.route(PREFIX + "/adverse-event-reports/<row_id>/submit-to-fda", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def submit_aer(row_id):
    row = path_row("aers", row_id, errors.ERR_AER_NOT_FOUND)
    body = validate.body()
    reference = validate.req_str(body, "submission_reference")

    if row["aer_status"] != "TRIAGED_SERIOUS":
        fail(
            errors.ERR_AER_STATE_INVALID,
            "Only a report triaged serious may be filed with the agency.",
        )

    now = db.now()
    late = now.date() > row["submission_due_date"]
    row["aer_status"] = "SUBMITTED_TO_FDA"
    row["submitted_at"] = now
    row["submission_reference"] = reference
    row["submission_timeliness"] = "LATE" if late else "TIMELY"
    db.touch(row)

    if late:
        product = db.get("products", row["product_id"])
        if product is not None:
            product["late_notification_count"] += 1
            db.touch(product)
            cascade.recompute_risk_index(product)

    return response.object_response(serialize.aer(row))
