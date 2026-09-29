"""Title review, mortgagee consent and the right of first refusal (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint

import engine as E
import validate as V
from auth import principal
from db import db
from errors import fail
from response import created, ok, ok_list

bp = Blueprint("title", __name__)

REVIEW_STATUSES = ("ORDERED", "EXCEPTIONS_FOUND", "CLEARED", "FAILED")
CONSENT_STATUSES = ("NOT_REQUIRED", "PENDING_REQUEST", "REQUESTED", "GRANTED", "DENIED", "EXPIRED")
TITLE_ACTIONS = ("RECORD_FINDINGS", "CURE_EXCEPTION", "CLEAR", "FAIL", "REQUEST_CONSENT")
LENDER_ACTIONS = ("GRANT", "DENY")
ROFR_STATUSES = ("SERVED", "WAIVED", "EXERCISED", "EXPIRED")

TITLE_READ_ROLES = ("AcquisitionAnalyst", "TitleOfficer", "PortfolioManager",
                    "PlatformAdmin", "Lender")
ROFR_READ_ROLES = ("AcquisitionAnalyst", "PortfolioManager", "PlatformAdmin", "TowerCompanyAgent")


# ----------------------------------------------------------------- title reports

@bp.post("/deals/<did>/title-reports")
def order_title_report(did):
    principal("AcquisitionAnalyst", "TitleOfficer")
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")
    b = V.body()
    snda = V.opt_bool(b, "snda_required", default=False)

    report = E.new_entity(
        deal_id=deal["id"],
        review_status="ORDERED",
        consent_status="NOT_REQUIRED",
        mortgage_present=False,
        lender_name=None,
        exception_count=0,
        open_exception_count=0,
        consent_requested_at=None,
        consent_expires_at=None,
        snda_required=snda,
        consent_decided_by_user_id=None,
        ordered_at=E.now(),
    )
    db.title_reports[report["id"]] = report
    return created(E.title_json(report))


@bp.get("/deals/<did>/title-reports")
def list_title_reports(did):
    principal(*TITLE_READ_ROLES)
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")
    limit, offset = V.pagination()
    review = V.enum_filter("review_status", REVIEW_STATUSES)
    consent = V.enum_filter("consent_status", CONSENT_STATUSES)
    rows = E.title_reports_of(deal["id"])
    if review is not None:
        rows = [r for r in rows if r["review_status"] == review]
    if consent is not None:
        rows = [r for r in rows if r["consent_status"] == consent]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.title_json(r) for r in page], total, limit, offset)


@bp.get("/title-reports/<tid>")
def get_title_report(tid):
    principal(*TITLE_READ_ROLES)
    report = E.find("title_reports", tid, "ERR_TITLE_REPORT_NOT_FOUND")
    return ok(E.title_json(report))


def _kill_deal_on_title(deal):
    if deal is None:
        return
    if deal["stage"] in ("DILIGENCE", "CLEAR_TO_CLOSE"):
        E.kill_deal(deal, "DEAD", "LOST")


@bp.post("/title-reports/<tid>/transitions")
def title_transition(tid):
    principal("TitleOfficer")
    report = E.find("title_reports", tid, "ERR_TITLE_REPORT_NOT_FOUND")
    deal = db.deals.get(report["deal_id"])
    b = V.body()
    action = V.req_enum(b, "action", TITLE_ACTIONS + LENDER_ACTIONS)
    if action in LENDER_ACTIONS:
        fail("ERR_ACTION_ROLE_MISMATCH")

    if action == "RECORD_FINDINGS":
        exception_count = V.req_int(b, "exception_count", minimum=0)
        mortgage_present = V.opt_bool(b, "mortgage_present", default=False)
        lender_name = V.opt_str(b, "lender_name")

        if report["review_status"] == "ORDERED":
            pass
        elif report["review_status"] == "CLEARED":
            if deal is not None and deal["stage"] == "CLOSED":
                fail("ERR_INVALID_DEAL_STAGE")
            if exception_count <= 0:
                fail("ERR_INVALID_TITLE_STATE")
        else:
            fail("ERR_INVALID_TITLE_STATE")

        report["exception_count"] = exception_count
        report["open_exception_count"] = exception_count
        report["mortgage_present"] = mortgage_present
        report["lender_name"] = lender_name
        if mortgage_present:
            if report["consent_status"] == "NOT_REQUIRED":
                report["consent_status"] = "PENDING_REQUEST"
        else:
            report["consent_status"] = "NOT_REQUIRED"

        if exception_count > 0:
            was_cleared = report["review_status"] == "CLEARED"
            report["review_status"] = "EXCEPTIONS_FOUND"
            E.touch(report)
            if was_cleared:
                E.reopen_diligence(deal)
        else:
            report["review_status"] = "CLEARED"
            E.touch(report)
            E.evaluate_join(deal)

    elif action == "CURE_EXCEPTION":
        if report["review_status"] != "EXCEPTIONS_FOUND" or report["open_exception_count"] < 1:
            fail("ERR_INVALID_TITLE_STATE")
        report["open_exception_count"] -= 1
        if report["open_exception_count"] == 0:
            report["review_status"] = "CLEARED"
            E.touch(report)
            E.evaluate_join(deal)
        else:
            E.touch(report)

    elif action == "CLEAR":
        if report["review_status"] != "EXCEPTIONS_FOUND" or report["open_exception_count"] != 0:
            fail("ERR_INVALID_TITLE_STATE")
        report["review_status"] = "CLEARED"
        E.touch(report)
        E.evaluate_join(deal)

    elif action == "FAIL":
        if report["review_status"] != "EXCEPTIONS_FOUND":
            fail("ERR_INVALID_TITLE_STATE")
        report["review_status"] = "FAILED"
        E.touch(report)
        _kill_deal_on_title(deal)

    else:  # REQUEST_CONSENT
        if not report["mortgage_present"]:
            fail("ERR_MORTGAGE_CONSENT_NOT_REQUIRED")
        if report["consent_status"] not in ("PENDING_REQUEST", "EXPIRED", "DENIED"):
            fail("ERR_INVALID_TITLE_STATE")
        if report["consent_status"] == "EXPIRED":
            if deal is not None and deal["stage"] == "CLOSED":
                fail("ERR_INVALID_DEAL_STAGE")
        if report["consent_status"] == "DENIED":
            if deal is not None and deal["stage"] in ("CLOSED", "DEAD"):
                fail("ERR_INVALID_DEAL_STAGE")

        was_cleared_deal = deal is not None and deal["stage"] == "CLEAR_TO_CLOSE"
        report["consent_status"] = "REQUESTED"
        report["consent_requested_at"] = E.now()
        report["consent_expires_at"] = E.consent_window_end(E.now())
        E.touch(report)
        if was_cleared_deal:
            E.reopen_diligence(deal)

    return ok(E.title_json(report))


@bp.post("/title-reports/<tid>/consent-decision")
def consent_decision(tid):
    user_id, _role = principal("Lender")
    report = E.find("title_reports", tid, "ERR_TITLE_REPORT_NOT_FOUND")
    deal = db.deals.get(report["deal_id"])
    b = V.body()
    decision = V.req_enum(b, "decision", LENDER_ACTIONS)

    if not report["mortgage_present"]:
        fail("ERR_MORTGAGE_CONSENT_NOT_REQUIRED")
    if report["consent_status"] != "REQUESTED":
        fail("ERR_INVALID_TITLE_STATE")

    report["consent_decided_by_user_id"] = user_id
    if decision == "GRANT":
        report["consent_status"] = "GRANTED"
        E.touch(report)
        E.evaluate_join(deal)
    else:
        report["consent_status"] = "DENIED"
        E.touch(report)
        _kill_deal_on_title(deal)
    return ok(E.title_json(report))


# ------------------------------------------------------------------ rofr notices

@bp.post("/deals/<did>/rofr-notices")
def serve_notice(did):
    principal("AcquisitionAnalyst")
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")

    for existing in E.rofr_notices_of(deal["id"]):
        if existing["status"] == "SERVED" and E.now() < existing["window_end"]:
            fail("ERR_ROFR_WINDOW_OVERLAP")

    stream = db.lease_streams.get(deal["lease_stream_id"])
    company = E.tower_company_of_stream(stream) if stream else None
    window_days = company["rofr_window_days"] if company else 30
    served_at = E.now()
    notice = E.new_entity(
        deal_id=deal["id"],
        served_at=served_at,
        window_start=served_at,
        window_end=served_at + timedelta(days=window_days),
        window_days_snapshot=window_days,
        status="SERVED",
        responded_at=None,
        responded_by_user_id=None,
    )
    db.rofr_notices[notice["id"]] = notice
    if deal["rofr_state"] != "PENDING":
        deal["rofr_state"] = "PENDING"
        E.touch(deal)
    return created(E.rofr_json(notice))


@bp.get("/deals/<did>/rofr-notices")
def list_notices(did):
    principal(*ROFR_READ_ROLES)
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")
    limit, offset = V.pagination()
    status = V.enum_filter("status", ROFR_STATUSES)
    rows = E.rofr_notices_of(deal["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.rofr_json(r) for r in page], total, limit, offset)


@bp.post("/rofr-notices/<nid>/response")
def notice_response(nid):
    user_id, _role = principal("TowerCompanyAgent")
    notice = E.find("rofr_notices", nid, "ERR_ROFR_NOTICE_NOT_FOUND")
    deal = db.deals.get(notice["deal_id"])
    b = V.body()
    decision = V.req_enum(b, "decision", ("WAIVE", "EXERCISE"))

    stream = db.lease_streams.get(deal["lease_stream_id"]) if deal else None
    company = E.tower_company_of_stream(stream) if stream else None
    if company is None or company["id"] != user_id:
        fail("ERR_NOT_ROFR_HOLDER")

    if (notice["status"] != "SERVED"
            or E.now() < notice["window_start"]
            or E.now() >= notice["window_end"]):
        fail("ERR_INVALID_ROFR_STATE")

    notice["responded_at"] = E.now()
    notice["responded_by_user_id"] = user_id
    if decision == "WAIVE":
        notice["status"] = "WAIVED"
        E.touch(notice)
        if deal is not None:
            deal["rofr_state"] = "WAIVED"
            E.touch(deal)
            E.evaluate_join(deal)
    else:
        notice["status"] = "EXERCISED"
        E.touch(notice)
        if deal is not None:
            deal["rofr_state"] = "EXERCISED"
            E.kill_deal(deal, "ROFR_LOST", "LOST")
    return ok(E.rofr_json(notice))
