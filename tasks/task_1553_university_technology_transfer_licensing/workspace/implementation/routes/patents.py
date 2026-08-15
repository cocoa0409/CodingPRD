"""Patent applications and prosecution costs."""
from flask import Blueprint

from store import db, create_record, touch
from util import (ApiError, require, get_body, check_schema, v_nonempty_str,
                  v_enum, v_dt, v_int_min, ok_object, ok_list, paginate)
from serializers import ser_application, ser_cost
from services import recompute_disclosure_costs, abandon_cascade

bp = Blueprint("patents", __name__)


def _get_disclosure_or_404(disclosure_id):
    disc = db.disclosures.get(disclosure_id)
    if disc is None:
        raise ApiError("ERR_DISCLOSURE_NOT_FOUND", 404, "Disclosure id does not exist")
    return disc


def _get_application_or_404(application_id):
    app = db.applications.get(application_id)
    if app is None:
        raise ApiError("ERR_PATENT_APPLICATION_NOT_FOUND", 404, "PatentApplication id does not exist")
    return app


# ---------------------------------------------------------------------------
# Patent applications
# ---------------------------------------------------------------------------

@bp.route("/tlo/disclosures/<disclosureId>/patent-applications", methods=["POST"])
def create_application(disclosureId):
    require("TechTransferOfficer")
    disc = _get_disclosure_or_404(disclosureId)
    data = check_schema(get_body(), {
        "docket_number": (True, v_nonempty_str),
        "application_type": (True, v_enum("PROVISIONAL", "NON_PROVISIONAL", "PCT")),
        "filed_date": (True, v_dt),
    })
    if disc["status"] != "PATENT_PURSUED":
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE", 409,
                       "Patent applications require disclosure status PATENT_PURSUED")
    if (disc["funding_source"] in ("FEDERAL", "MIXED")
            and data["application_type"] in ("NON_PROVISIONAL", "PCT")):
        elected = any(
            r["disclosure_id"] == disc["id"]
            and r["report_type"] == "ELECTION_OF_TITLE"
            and r["status"] in ("SUBMITTED", "AGENCY_ACCEPTED")
            for r in db.compliance_reports.values()
        )
        if not elected:
            raise ApiError("ERR_TITLE_NOT_ELECTED", 409,
                           "NON_PROVISIONAL/PCT on FEDERAL/MIXED disclosure requires a SUBMITTED "
                           "or AGENCY_ACCEPTED ELECTION_OF_TITLE report")
    if disc["cost_writeoff_review_required"]:
        raise ApiError("ERR_COST_REVIEW_REQUIRED", 422,
                       "cost_writeoff_review_required is true; new patent applications blocked")
    app = create_record(db.applications, {
        "disclosure_id": disc["id"],
        "docket_number": data["docket_number"],
        "application_type": data["application_type"],
        "filed_date": data["filed_date"],
        "status": "FILED",
        "total_cost_cents": 0,
        "unreimbursed_cost_cents": 0,
    })
    return ok_object(ser_application(app), status=201)


@bp.route("/tlo/disclosures/<disclosureId>/patent-applications", methods=["GET"])
def list_applications(disclosureId):
    require()
    disc = _get_disclosure_or_404(disclosureId)
    records = [a for a in db.applications.values() if a["disclosure_id"] == disc["id"]]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_application(a) for a in page], limit, offset, total)


@bp.route("/tlo/patent-applications/<applicationId>", methods=["GET"])
def get_application(applicationId):
    require()
    return ok_object(ser_application(_get_application_or_404(applicationId)))


@bp.route("/tlo/patent-applications/<applicationId>/office-action", methods=["POST"])
def office_action(applicationId):
    require("TechTransferOfficer")
    app = _get_application_or_404(applicationId)
    check_schema(get_body(), {"received_date": (True, v_dt)})
    if app["status"] not in ("FILED", "RESPONSE_FILED"):
        raise ApiError("ERR_PATENT_INVALID_STATE", 409,
                       "Office action requires status FILED or RESPONSE_FILED")
    app["status"] = "OFFICE_ACTION_RECEIVED"
    touch(app)
    return ok_object(ser_application(app))


@bp.route("/tlo/patent-applications/<applicationId>/file-response", methods=["POST"])
def file_response(applicationId):
    require("TechTransferOfficer")
    app = _get_application_or_404(applicationId)
    check_schema(get_body(), {"response_date": (True, v_dt)})
    if app["status"] != "OFFICE_ACTION_RECEIVED":
        raise ApiError("ERR_PATENT_INVALID_STATE", 409,
                       "File-response requires status OFFICE_ACTION_RECEIVED")
    app["status"] = "RESPONSE_FILED"
    touch(app)
    return ok_object(ser_application(app))


@bp.route("/tlo/patent-applications/<applicationId>/grant", methods=["POST"])
def grant(applicationId):
    require("TechTransferOfficer")
    app = _get_application_or_404(applicationId)
    check_schema(get_body(), {"grant_date": (True, v_dt)})
    if app["status"] not in ("FILED", "RESPONSE_FILED"):
        raise ApiError("ERR_PATENT_INVALID_STATE", 409,
                       "Grant requires status FILED or RESPONSE_FILED")
    app["status"] = "GRANTED"
    touch(app)
    return ok_object(ser_application(app))


@bp.route("/tlo/patent-applications/<applicationId>/abandon", methods=["POST"])
def abandon(applicationId):
    require("TechTransferOfficer")
    app = _get_application_or_404(applicationId)
    check_schema(get_body(), {})
    if app["status"] not in ("FILED", "OFFICE_ACTION_RECEIVED", "RESPONSE_FILED"):
        raise ApiError("ERR_PATENT_INVALID_STATE", 409,
                       "Abandon requires status FILED, OFFICE_ACTION_RECEIVED, or RESPONSE_FILED")
    app["status"] = "ABANDONED"
    touch(app)
    disc = db.disclosures[app["disclosure_id"]]
    abandon_cascade(app, disc)
    return ok_object(ser_application(app))


# ---------------------------------------------------------------------------
# Patent costs
# ---------------------------------------------------------------------------

@bp.route("/tlo/patent-applications/<applicationId>/costs", methods=["POST"])
def create_cost(applicationId):
    require("TechTransferOfficer")
    app = _get_application_or_404(applicationId)
    data = check_schema(get_body(), {
        "cost_type": (True, v_enum("FILING_FEE", "ATTORNEY_FEE", "MAINTENANCE_FEE", "TRANSLATION_FEE")),
        "amount_cents": (True, v_int_min(1)),
        "incurred_date": (True, v_dt),
    })
    cost = create_record(db.costs, {
        "patent_application_id": app["id"],
        "cost_type": data["cost_type"],
        "amount_cents": data["amount_cents"],
        "incurred_date": data["incurred_date"],
        "reimbursed_amount_cents": 0,
        "reimbursement_status": "UNREIMBURSED",
    })
    disc = db.disclosures[app["disclosure_id"]]
    recompute_disclosure_costs(disc)
    return ok_object(ser_cost(cost), status=201)


@bp.route("/tlo/patent-applications/<applicationId>/costs", methods=["GET"])
def list_costs(applicationId):
    require()
    app = _get_application_or_404(applicationId)
    records = [c for c in db.costs.values() if c["patent_application_id"] == app["id"]]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_cost(c) for c in page], limit, offset, total)
