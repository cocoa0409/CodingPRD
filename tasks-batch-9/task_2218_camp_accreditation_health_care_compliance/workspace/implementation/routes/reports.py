"""Annual reports and incident disclosures."""

from flask import Blueprint

import clock
import db
import domain
import helpers
import response
import validators
from errors import api_error
from middleware import authenticate

bp = Blueprint("reports", __name__)


@bp.get("/accreditation/annual-reports/<report_id>")
def get_report(report_id):
    ident = authenticate(("CampDirector", "AccreditationOfficer", "StateLicensingAgent"))
    report = helpers.report_or_404(report_id)
    helpers.scope(ident, report["camp_id"])
    return response.ok(helpers.public(report))


@bp.get("/accreditation/annual-reports")
def list_reports():
    authenticate(("CampDirector", "AccreditationOfficer", "StateLicensingAgent"))
    return helpers.collection_response(db.annual_reports, helpers.REPORT_FILTERS)


@bp.post("/accreditation/annual-reports")
def open_report():
    ident = authenticate(("CampDirector",))
    data = validators.body()
    camp_id = validators.require(data, "camp_id")
    if not isinstance(camp_id, str):
        raise api_error("ERR_INVALID_REQUEST", "Field 'camp_id' must be a string.")
    report_year = validators.req_int(data, "report_year", 2000, 2100)

    camp = helpers.camp_or_404(camp_id)
    helpers.scope(ident, camp["id"])
    for existing in domain.camp_reports(camp_id):
        if existing["report_year"] == report_year:
            raise api_error(
                "ERR_DUPLICATE_CYCLE_YEAR",
                "An annual report already exists for that camp and year.",
            )

    report = db.common_fields()
    report.update(
        {
            "camp_id": camp_id,
            "report_year": report_year,
            "due_date": "%04d-03-01" % (report_year + 1),
            "status": "DRAFT",
            "declared_incident_count": 0,
            "disclosed_incident_count": 0,
            "submitted_at": None,
            "attested_by_user_id": None,
            "reopen_count": 0,
            "reviewer_note": None,
        }
    )
    db.annual_reports[report["id"]] = report
    return response.created(helpers.public(report))


@bp.post("/accreditation/annual-reports/<report_id>/submit")
def submit_report(report_id):
    ident = authenticate(("CampDirector",))
    data = validators.body()
    declared = validators.req_int(data, "declared_incident_count", 0)

    report = helpers.report_or_404(report_id)
    helpers.scope(ident, report["camp_id"])

    if report["status"] not in ("DRAFT", "REJECTED", "REOPENED"):
        raise api_error(
            "ERR_ANNUAL_REPORT_INVALID_STATE",
            "The report is not in a fileable status.",
        )
    if declared < report["disclosed_incident_count"]:
        raise api_error(
            "ERR_DECLARED_COUNT_BELOW_DISCLOSED",
            "The declared incident count is below the disclosed count.",
        )

    report["declared_incident_count"] = declared
    report["status"] = (
        "SUBMITTED" if clock.today().isoformat() <= report["due_date"] else "LATE"
    )
    report["submitted_at"] = clock.now_iso()
    report["attested_by_user_id"] = ident.user_id
    db.touch(report)
    return response.ok(helpers.public(report))


@bp.post("/accreditation/annual-reports/<report_id>/review")
def review_report(report_id):
    ident = authenticate(("AccreditationOfficer",))
    data = validators.body()
    decision = validators.req_enum(data, "decision", ("ACCEPT", "REJECT"))
    note = validators.opt_str(data, "reviewer_note", 0, 2000)

    report = helpers.report_or_404(report_id)
    if report["status"] not in ("SUBMITTED", "LATE"):
        raise api_error(
            "ERR_ANNUAL_REPORT_INVALID_STATE", "The report is not awaiting review."
        )

    report["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    if note is not None:
        report["reviewer_note"] = note
    db.touch(report)
    return response.ok(helpers.public(report))


@bp.get("/accreditation/incident-disclosures/<disclosure_id>")
def get_disclosure(disclosure_id):
    ident = authenticate(("CampDirector", "AccreditationOfficer", "StateLicensingAgent"))
    disclosure = helpers.disclosure_or_404(disclosure_id)
    helpers.scope(ident, helpers.camp_id_of_disclosure(disclosure))
    return response.ok(helpers.public(disclosure))


@bp.get("/accreditation/incident-disclosures")
def list_disclosures():
    authenticate(("CampDirector", "AccreditationOfficer", "StateLicensingAgent"))
    return helpers.collection_response(db.disclosures, helpers.DISCLOSURE_FILTERS)


@bp.post("/accreditation/incident-disclosures")
def disclose_incident():
    ident = authenticate(("CampDirector",))
    data = validators.body()
    report_id = validators.require(data, "annual_report_id")
    if not isinstance(report_id, str):
        raise api_error(
            "ERR_INVALID_REQUEST", "Field 'annual_report_id' must be a string."
        )
    incident_type = validators.req_enum(data, "incident_type", domain.INCIDENT_TYPES)
    occurred_at = validators.req_datetime(data, "occurred_at")

    report = helpers.report_or_404(report_id)
    helpers.scope(ident, report["camp_id"])
    camp = db.camps.get(report["camp_id"])

    if report["status"] == "ARCHIVED":
        raise api_error(
            "ERR_ANNUAL_REPORT_INVALID_STATE",
            "An archived report accepts no further disclosures.",
        )
    if occurred_at.year != report["report_year"]:
        raise api_error(
            "ERR_INCIDENT_OUTSIDE_REPORT_YEAR",
            "The incident did not occur in the report year.",
        )

    late = report["status"] == "ACCEPTED"
    disclosure = db.common_fields()
    disclosure.update(
        {
            "annual_report_id": report_id,
            "incident_type": incident_type,
            "occurred_at": clock.iso(occurred_at),
            "disclosed_at": clock.now_iso(),
            "severity_weight": domain.INCIDENT_WEIGHT[incident_type],
            "state_notification_required": bool(
                incident_type in domain.STATE_NOTIFIABLE_INCIDENTS
                and camp is not None
                and camp["state_license_status"] in ("ACTIVE", "PROBATION")
            ),
            "status": "LATE_DISCLOSED" if late else "REPORTED",
        }
    )
    db.disclosures[disclosure["id"]] = disclosure

    if late:
        report["status"] = "REOPENED"
        report["reopen_count"] = report["reopen_count"] + 1
    domain.recompute_disclosed_count(report)
    if camp is not None:
        domain.recompute_risk_index(camp)
    return response.created(helpers.public(disclosure))
