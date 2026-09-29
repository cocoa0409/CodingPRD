"""Every single-resource read and every list endpoint."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from services import derive

bp = Blueprint("reads", __name__)

ALL_ROLES = (
    "ProgramAdmin",
    "StateTitleClerk",
    "InsurerAdjuster",
    "Rebuilder",
    "Inspector",
    "HearingOfficer",
    "FraudInvestigator",
)
PROGRAM_ROLES = (
    "ProgramAdmin",
    "StateTitleClerk",
    "Rebuilder",
    "Inspector",
    "HearingOfficer",
    "FraudInvestigator",
)
STATION_ROLES = ("ProgramAdmin", "StateTitleClerk", "Inspector")
REPORT_ROLES = ("ProgramAdmin", "StateTitleClerk", "InsurerAdjuster", "Inspector", "FraudInvestigator")
APPEAL_ROLES = ("ProgramAdmin", "StateTitleClerk", "Rebuilder", "Inspector", "HearingOfficer")
REFERRAL_ROLES = ("ProgramAdmin", "StateTitleClerk", "Inspector", "FraudInvestigator", "HearingOfficer")
RECOGNITION_ROLES = ("ProgramAdmin", "StateTitleClerk", "Rebuilder", "HearingOfficer")
TRANSFER_ROLES = ("ProgramAdmin", "StateTitleClerk", "Rebuilder", "FraudInvestigator", "HearingOfficer")


def fetch(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def listing(rows, serializer, filters):
    """Filter by equality, order by created_at ascending, then paginate."""
    limit, offset = mw.pagination()
    for field, value in filters.items():
        if value is None:
            continue
        rows = [row for row in rows if row.get(field) == value]
    rows = db.ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return response.collection([serializer(row) for row in page], limit, offset, total)


# ------------------------------------------------------------------- registry


@bp.get("/v1/vehicles/<row_id>")
def get_vehicle(row_id):
    mw.authenticate(*ALL_ROLES)
    row = fetch(db.db.vehicles, row_id, "ERR_VEHICLE_NOT_FOUND")
    return response.single(derive.vehicle_out(row))


@bp.get("/v1/rebuilders/<row_id>")
def get_rebuilder(row_id):
    mw.authenticate(*PROGRAM_ROLES)
    row = fetch(db.db.rebuilders, row_id, "ERR_REBUILDER_NOT_FOUND")
    return response.single(derive.rebuilder_out(row))


@bp.get("/v1/inspectors/<row_id>")
def get_inspector(row_id):
    mw.authenticate(*PROGRAM_ROLES)
    row = fetch(db.db.inspectors, row_id, "ERR_INSPECTOR_NOT_FOUND")
    return response.single(derive.inspector_out(row))


@bp.get("/v1/inspection-stations/<row_id>")
def get_station(row_id):
    mw.authenticate(*STATION_ROLES)
    row = fetch(db.db.stations, row_id, "ERR_STATION_NOT_FOUND")
    return response.single(derive.station_out(row))


# -------------------------------------------------------------- damage reports


@bp.get("/v1/damage-reports/<row_id>")
def get_damage_report(row_id):
    mw.authenticate(*REPORT_ROLES)
    row = fetch(db.db.damage_reports, row_id, "ERR_DAMAGE_REPORT_NOT_FOUND")
    return response.single(derive.damage_report_out(row))


@bp.get("/v1/damage-reports")
def list_damage_reports():
    mw.authenticate(*REPORT_ROLES)
    return listing(
        list(db.db.damage_reports.values()),
        derive.damage_report_out,
        {
            "vehicle_id": mw.filter_value("vehicle_id"),
            "damage_type": mw.filter_value("damage_type"),
        },
    )


# --------------------------------------------------------------- title records


@bp.get("/v1/title-records/<row_id>")
def get_title(row_id):
    mw.authenticate(*PROGRAM_ROLES)
    row = fetch(db.db.titles, row_id, "ERR_TITLE_NOT_FOUND")
    return response.single(derive.title_out(row))


@bp.get("/v1/title-records")
def list_titles():
    mw.authenticate(*PROGRAM_ROLES)
    rows = list(db.db.titles.values())
    for row in rows:
        derive.recompute_title(row)
    return listing(
        rows,
        derive.title_out,
        {
            "vehicle_id": mw.filter_value("vehicle_id"),
            "predecessor_title_id": mw.filter_value("predecessor_title_id"),
            "source_damage_report_id": mw.filter_value("source_damage_report_id"),
            "brand_code": mw.filter_value("brand_code"),
            "is_current": mw.bool_filter("is_current"),
            "status": mw.filter_value("status"),
        },
    )


# ---------------------------------------------------------------- applications


@bp.get("/v1/applications/<row_id>")
def get_application(row_id):
    mw.authenticate(*PROGRAM_ROLES)
    row = fetch(db.db.applications, row_id, "ERR_APPLICATION_NOT_FOUND")
    return response.single(derive.application_out(row))


@bp.get("/v1/applications")
def list_applications():
    mw.authenticate(*PROGRAM_ROLES)
    rows = list(db.db.applications.values())
    for row in rows:
        derive.recompute_application(row)
    return listing(
        rows,
        derive.application_out,
        {
            "vehicle_id": mw.filter_value("vehicle_id"),
            "rebuilder_id": mw.filter_value("rebuilder_id"),
            "salvage_title_id": mw.filter_value("salvage_title_id"),
            "status": mw.filter_value("status"),
        },
    )


# ------------------------------------------------------------- parts documents


@bp.get("/v1/parts-documents/<row_id>")
def get_parts_document(row_id):
    mw.authenticate(*PROGRAM_ROLES)
    row = fetch(db.db.parts_documents, row_id, "ERR_PARTS_DOCUMENT_NOT_FOUND")
    return response.single(derive.parts_document_out(row))


@bp.get("/v1/parts-documents")
def list_parts_documents():
    mw.authenticate(*PROGRAM_ROLES)
    return listing(
        list(db.db.parts_documents.values()),
        derive.parts_document_out,
        {
            "application_id": mw.filter_value("application_id"),
            "donor_title_id": mw.filter_value("donor_title_id"),
            "verified_by_inspector_id": mw.filter_value("verified_by_inspector_id"),
            "status": mw.filter_value("status"),
            "part_class": mw.filter_value("part_class"),
        },
    )


# ----------------------------------------------------------------- inspections


@bp.get("/v1/inspections/<row_id>")
def get_inspection(row_id):
    mw.authenticate(*PROGRAM_ROLES)
    row = fetch(db.db.inspections, row_id, "ERR_INSPECTION_NOT_FOUND")
    return response.single(derive.inspection_out(row))


@bp.get("/v1/inspections")
def list_inspections():
    mw.authenticate(*PROGRAM_ROLES)
    rows = list(db.db.inspections.values())
    for row in rows:
        derive.recompute_inspection(row)
    return listing(
        rows,
        derive.inspection_out,
        {
            "application_id": mw.filter_value("application_id"),
            "inspector_id": mw.filter_value("inspector_id"),
            "station_id": mw.filter_value("station_id"),
            "status": mw.filter_value("status"),
            "result": mw.filter_value("result"),
        },
    )


# -------------------------------------------------------------------- findings


@bp.get("/v1/findings/<row_id>")
def get_finding(row_id):
    mw.authenticate(*PROGRAM_ROLES)
    row = fetch(db.db.findings, row_id, "ERR_FINDING_NOT_FOUND")
    return response.single(derive.finding_out(row))


@bp.get("/v1/findings")
def list_findings():
    mw.authenticate(*PROGRAM_ROLES)
    return listing(
        list(db.db.findings.values()),
        derive.finding_out,
        {
            "inspection_id": mw.filter_value("inspection_id"),
            "parts_document_id": mw.filter_value("parts_document_id"),
            "category": mw.filter_value("category"),
            "severity": mw.filter_value("severity"),
        },
    )


# --------------------------------------------------------------------- appeals


@bp.get("/v1/appeals/<row_id>")
def get_appeal(row_id):
    mw.authenticate(*APPEAL_ROLES)
    row = fetch(db.db.appeals, row_id, "ERR_APPEAL_NOT_FOUND")
    return response.single(derive.appeal_out(row))


@bp.get("/v1/appeals")
def list_appeals():
    mw.authenticate(*APPEAL_ROLES)
    return listing(
        list(db.db.appeals.values()),
        derive.appeal_out,
        {
            "inspection_id": mw.filter_value("inspection_id"),
            "status": mw.filter_value("status"),
        },
    )


# ------------------------------------------------------------- fraud referrals


@bp.get("/v1/fraud-referrals/<row_id>")
def get_referral(row_id):
    mw.authenticate(*REFERRAL_ROLES)
    row = fetch(db.db.referrals, row_id, "ERR_REFERRAL_NOT_FOUND")
    return response.single(derive.referral_out(row))


@bp.get("/v1/fraud-referrals")
def list_referrals():
    mw.authenticate(*REFERRAL_ROLES)
    return listing(
        list(db.db.referrals.values()),
        derive.referral_out,
        {
            "vehicle_id": mw.filter_value("vehicle_id"),
            "application_id": mw.filter_value("application_id"),
            "inspection_id": mw.filter_value("inspection_id"),
            "referral_type": mw.filter_value("referral_type"),
            "status": mw.filter_value("status"),
        },
    )


# -------------------------------------------------------- recognition requests


@bp.get("/v1/recognition-requests/<row_id>")
def get_recognition(row_id):
    mw.authenticate(*RECOGNITION_ROLES)
    row = fetch(db.db.recognitions, row_id, "ERR_RECOGNITION_REQUEST_NOT_FOUND")
    return response.single(derive.recognition_out(row))


@bp.get("/v1/recognition-requests")
def list_recognitions():
    mw.authenticate(*RECOGNITION_ROLES)
    return listing(
        list(db.db.recognitions.values()),
        derive.recognition_out,
        {
            "title_record_id": mw.filter_value("title_record_id"),
            "requesting_state_code": mw.filter_value("requesting_state_code"),
            "status": mw.filter_value("status"),
        },
    )


# ------------------------------------------------------------- title transfers


@bp.get("/v1/title-transfers/<row_id>")
def get_transfer(row_id):
    mw.authenticate(*TRANSFER_ROLES)
    row = fetch(db.db.transfers, row_id, "ERR_TRANSFER_NOT_FOUND")
    return response.single(derive.transfer_out(row))


@bp.get("/v1/title-transfers")
def list_transfers():
    mw.authenticate(*TRANSFER_ROLES)
    return listing(
        list(db.db.transfers.values()),
        derive.transfer_out,
        {
            "from_title_id": mw.filter_value("from_title_id"),
            "to_title_id": mw.filter_value("to_title_id"),
            "odometer_flag": mw.filter_value("odometer_flag"),
        },
    )
