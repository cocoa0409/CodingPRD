from datetime import timedelta

from flask import Blueprint

import db
from db import LOCK, STORE
from errors import ApiError
from middleware import auth, require_owner
from response import ok_list, ok_object
from services import serialize as ser
from services.resolution import get_report, get_tenancy
from utils import body_json, pagination, v_enum

bp = Blueprint("reports", __name__)

REPORT_TYPES = {"FILING", "JUDGMENT", "SATISFACTION", "CORRECTION"}
REPORT_WINDOW_DAYS = 30


def _cases_of_tenancy(tenancy_id):
    return [c for c in STORE.cases.values() if c["tenancy_id"] == tenancy_id]


def _event_at_for(report_type, tenancy_id, reference):
    """Resolve the anchor event timestamp; raises the referential errors."""
    if report_type == "FILING":
        case_ids = {c["id"] for c in _cases_of_tenancy(tenancy_id)}
        accepted = [
            p
            for p in STORE.packages.values()
            if p["case_id"] in case_ids and p["status"] == "ACCEPTED"
        ]
        if not accepted:
            raise ApiError(
                "ERR_REPORT_EVENT_MISSING",
                422,
                "FILING requires an ACCEPTED package on a case of this tenancy",
            )
        return min(p["accepted_at"] for p in accepted)
    if report_type == "JUDGMENT":
        case_ids = {c["id"] for c in _cases_of_tenancy(tenancy_id)}
        judgments = [j for j in STORE.judgments.values() if j["case_id"] in case_ids]
        if not judgments:
            raise ApiError(
                "ERR_REPORT_EVENT_MISSING",
                422,
                "JUDGMENT requires a judgment on a case of this tenancy",
            )
        return max(j["entered_at"] for j in judgments)
    if report_type == "SATISFACTION":
        case_ids = {c["id"] for c in _cases_of_tenancy(tenancy_id)}
        satisfied = [
            j
            for j in STORE.judgments.values()
            if j["case_id"] in case_ids and j["status"] == "SATISFIED"
        ]
        if not satisfied:
            raise ApiError(
                "ERR_REPORT_EVENT_MISSING",
                422,
                "SATISFACTION requires a SATISFIED judgment on a case of this tenancy",
            )
        return max(j["satisfied_at"] for j in satisfied)
    # CORRECTION
    if (
        reference is None
        or reference["tenancy_id"] != tenancy_id
        or reference["report_type"] == "CORRECTION"
        or reference["superseded"]
    ):
        raise ApiError(
            "ERR_CORRECTION_TARGET_INVALID",
            422,
            "Correction reference missing, cross-tenancy, itself a correction, or already superseded",
        )
    return reference["event_at"]


@bp.post("/api/tenancies/<tid>/rental-history-reports")
@auth({"Landlord"})
def create_report(tid, _uid, _role):
    with LOCK:
        tenancy = get_tenancy(tid)
        unit = STORE.units[tenancy["unit_id"]]
        require_owner(_uid, unit["landlord_id"])
        b = body_json()
        report_type = v_enum(b, "report_type", REPORT_TYPES)
        reference_report_id = b.get("reference_report_id")
        if report_type == "CORRECTION":
            if not isinstance(reference_report_id, str) or reference_report_id == "":
                raise ApiError(
                    "ERR_VALIDATION",
                    400,
                    "reference_report_id is required for CORRECTION",
                )
        else:
            if reference_report_id is not None:
                raise ApiError(
                    "ERR_VALIDATION",
                    400,
                    "reference_report_id is only allowed for CORRECTION",
                )
        reference = None
        if report_type == "CORRECTION":
            reference = STORE.reports.get(reference_report_id)
        event_at = _event_at_for(report_type, tid, reference)
        if report_type != "CORRECTION":
            if db.now() > event_at + timedelta(days=REPORT_WINDOW_DAYS):
                raise ApiError(
                    "ERR_REPORT_WINDOW_LAPSED",
                    422,
                    "Report filed more than 30 days after its trigger event",
                )
        STORE.report_seq += 1
        r = db.new_record(
            {
                "tenancy_id": tid,
                "landlord_id": unit["landlord_id"],
                "report_type": report_type,
                "reference_report_id": reference_report_id if report_type == "CORRECTION" else None,
                "event_at": event_at,
                "superseded": False,
                "bureau_reference": f"RHR-{STORE.report_seq}",
            }
        )
        STORE.reports[r["id"]] = r
        if reference is not None:
            reference["superseded"] = True
            db.bump(reference)
        return ok_object(ser.report(r), 201)


@bp.get("/api/rental-history-reports/<rid>")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def read_report(rid, _uid, _role):
    with LOCK:
        return ok_object(ser.report(get_report(rid)))


@bp.get("/api/tenancies/<tid>/rental-history-reports")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def list_tenancy_reports(tid, _uid, _role):
    with LOCK:
        get_tenancy(tid)
        limit, offset = pagination()
        items = [r for r in db.sorted_items(STORE.reports) if r["tenancy_id"] == tid]
        page = items[offset : offset + limit]
        return ok_list([ser.report(r) for r in page], len(items), limit, offset)


@bp.get("/api/rental-history-reports/<rid>/corrections")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def list_report_corrections(rid, _uid, _role):
    with LOCK:
        get_report(rid)
        limit, offset = pagination()
        items = [
            r
            for r in db.sorted_items(STORE.reports)
            if r["reference_report_id"] == rid
        ]
        page = items[offset : offset + limit]
        return ok_list([ser.report(r) for r in page], len(items), limit, offset)
