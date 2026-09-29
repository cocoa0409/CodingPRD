"""FinalReport and Appeal endpoints."""

from flask import Blueprint

import constants as C
import db
import middleware as mw
import response
import validation as v
from errors import ApiError
from routes import support as sup
from services import cascade, derive

bp = Blueprint("reports", __name__)

PO = (mw.PROGRAM_OFFICER,)
ARTIST_ONLY = (mw.ARTIST,)
APPEALS_ONLY = (mw.APPEALS,)
NO_PANELIST = sup.NO_PANELIST


def _report_narrative(data):
    return {
        "narrative": v.req_str(data, "narrative"),
        "public_value_statement": v.req_str(data, "public_value_statement"),
        "audience_reached_count": v.req_int(data, "audience_reached_count", minimum=0),
        "expenditure_summary": v.req_str(data, "expenditure_summary"),
    }


def _own(artist_id, user_id, role):
    if role == mw.ARTIST and artist_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# ========================================================= final reports


@bp.post("/grants/final-reports")
def create_report():
    user_id, role = mw.authorize(ARTIST_ONLY, entity_backed=True)
    data = v.body()
    award_id = v.req_id(data, "award_id")
    fields = _report_narrative(data)

    award = sup.resolve_fk("awards", award_id)
    _own(award["artist_id"], user_id, role)

    if award["reporting_status"] not in ("DUE", "RECEIVED", "DELINQUENT"):
        raise ApiError("ERR_FINAL_REPORT_NOT_DUE")
    if derive.report_of_award(award["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_FINAL_REPORT")

    report = db.insert(
        "final_reports",
        dict(
            fields,
            award_id=award["id"],
            status="SUBMITTED",
            revision_count=0,
            reviewed_by=None,
            revision_note=None,
            submitted_at=cascade.now_iso(),
            accepted_at=None,
        ),
    )
    cascade.clear_report_delinquency(award)
    return response.obj(db.public(report), 201)


@bp.get("/grants/final-reports/<final_report_id>")
def read_report(final_report_id):
    mw.authorize(NO_PANELIST)
    return response.obj(db.public(sup.resolve("final_reports", final_report_id)))


@bp.get("/grants/final-reports")
def list_reports():
    mw.authorize(NO_PANELIST)
    rows = db.rows("final_reports")
    rows = sup.eq(rows, "award_id", v.query_str("award_id"))
    rows = sup.eq(rows, "status", v.query_str("status"))
    return sup.listed(rows)


@bp.post("/grants/final-reports/<final_report_id>/review")
def review_report(final_report_id):
    user_id, _ = mw.authorize(PO)
    data = v.body()
    decision = v.req_enum(data, "decision", C.FINAL_REPORT_DECISIONS)
    note = v.opt_str(data, "revision_note")

    report = sup.resolve("final_reports", final_report_id)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_FINAL_REPORT_STATE_INVALID")

    award = db.get("awards", report["award_id"])

    if decision == "ACCEPT":
        if award is None or award["reporting_status"] != "RECEIVED":
            raise ApiError("ERR_AWARD_STATE_INVALID")
        derive.set_fields(
            report,
            status="ACCEPTED",
            reviewed_by=user_id,
            accepted_at=cascade.now_iso(),
        )
        derive.set_fields(award, reporting_status="ACCEPTED")
        cascade.complete_award(award)
    else:
        if int(report["revision_count"]) >= C.MAX_REPORT_REVISIONS:
            raise ApiError("ERR_MAX_REVISIONS_REACHED")
        if note is None or len(note.strip()) < 20:
            v.bad("revision_note must be at least 20 characters.")
        derive.set_fields(
            report,
            status="REVISION_REQUESTED",
            revision_count=int(report["revision_count"]) + 1,
            reviewed_by=user_id,
            revision_note=note,
        )
    return response.obj(db.public(report))


@bp.post("/grants/final-reports/<final_report_id>/resubmit")
def resubmit_report(final_report_id):
    user_id, role = mw.authorize(ARTIST_ONLY, entity_backed=True)
    data = v.body()
    fields = _report_narrative(data)

    report = sup.resolve("final_reports", final_report_id)
    award = db.get("awards", report["award_id"])
    _own(award["artist_id"] if award else None, user_id, role)

    if report["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_FINAL_REPORT_STATE_INVALID")

    derive.set_fields(
        report, status="SUBMITTED", submitted_at=cascade.now_iso(), **fields
    )
    return response.obj(db.public(report))


# =============================================================== appeals


@bp.post("/grants/appeals")
def create_appeal():
    user_id, role = mw.authorize(ARTIST_ONLY, entity_backed=True)
    data = v.body()
    application_id = v.req_id(data, "application_id")
    grounds = v.req_enum(data, "grounds_code", C.APPEAL_GROUNDS)
    statement = v.req_str(data, "statement")

    application = sup.resolve_fk("applications", application_id)
    _own(application["artist_id"], user_id, role)

    cycle = derive.cycle_of(application)
    notified = db.dt_of(application, "notified_at")
    moment = db.now()
    if notified is None:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")
    closes = db.plus_days(notified, int(cycle["appeal_window_days"]))
    if moment < notified or moment > closes:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")

    for other in db.rows(
        "appeals", lambda r, a=application["id"]: r["application_id"] == a
    ):
        if other["status"] != "DENIED":
            raise ApiError("ERR_DUPLICATE_APPEAL")

    appeal = db.insert(
        "appeals",
        {
            "application_id": application["id"],
            "filed_by_artist_id": application["artist_id"],
            "grounds_code": grounds,
            "statement": statement,
            "status": "FILED",
            "remedy_code": None,
            "screened_by": None,
            "decided_by": None,
            "filed_at": db.iso3(moment),
        },
    )
    return response.obj(db.public(appeal), 201)


@bp.get("/grants/appeals/<appeal_id>")
def read_appeal(appeal_id):
    mw.authorize(NO_PANELIST)
    return response.obj(db.public(sup.resolve("appeals", appeal_id)))


@bp.get("/grants/appeals")
def list_appeals():
    mw.authorize(NO_PANELIST)
    rows = db.rows("appeals")
    rows = sup.eq(rows, "application_id", v.query_str("application_id"))
    rows = sup.eq(rows, "filed_by_artist_id", v.query_str("filed_by_artist_id"))
    rows = sup.eq(rows, "status", v.query_str("status"))
    rows = sup.eq(rows, "grounds_code", v.query_str("grounds_code"))
    return sup.listed(rows)


@bp.post("/grants/appeals/<appeal_id>/screen")
def screen_appeal(appeal_id):
    user_id, _ = mw.authorize(APPEALS_ONLY)
    appeal = sup.resolve("appeals", appeal_id)
    if appeal["status"] != "FILED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")
    if appeal["grounds_code"] not in C.PROCEDURAL_GROUNDS:
        raise ApiError("ERR_NON_PROCEDURAL_APPEAL_GROUNDS")
    derive.set_fields(appeal, status="SCREENED", screened_by=user_id)
    return response.obj(db.public(appeal))


@bp.post("/grants/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    user_id, _ = mw.authorize(APPEALS_ONLY)
    data = v.body()
    decision = v.req_enum(data, "decision", C.APPEAL_DECISIONS)
    remedy = v.opt_enum(data, "remedy_code", C.REMEDY_CODES)

    appeal = sup.resolve("appeals", appeal_id)
    application = db.get("applications", appeal["application_id"])

    # P55 segregation of duties.
    if (
        application is not None
        and application["eligibility_determined_by"] is not None
        and application["eligibility_determined_by"] == user_id
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    status = appeal["status"]
    if decision == "DENY":
        substantive_direct = (
            status == "FILED"
            and appeal["grounds_code"] == "SUBSTANTIVE_SCORE_DISAGREEMENT"
        )
        if status != "SCREENED" and not substantive_direct:
            raise ApiError("ERR_APPEAL_STATE_INVALID")
        derive.set_fields(appeal, status="DENIED", decided_by=user_id)
        return response.obj(db.public(appeal))

    if status != "SCREENED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")

    cycle = derive.cycle_of(application) if application else None
    if cycle is None or cycle["status"] not in ("PANEL_REVIEW", "BOARD_REVIEW"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    permitted = C.REMEDY_PERMITTED.get(appeal["grounds_code"], ())
    if remedy is None or remedy not in permitted:
        raise ApiError("ERR_REMEDY_NOT_PERMITTED_FOR_GROUNDS")

    if remedy == "REISSUE_SLATE" and cycle["status"] != "BOARD_REVIEW":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if remedy == "RESCORE_BY_NEW_PANEL":
        panel = db.get("panels", application.get("assigned_panel_id"))
        if panel is not None and int(panel["round_number"]) >= int(
            cycle["max_review_rounds"]
        ):
            raise ApiError("ERR_SCORE_SPREAD_REQUIRES_ANOTHER_ROUND")

    derive.set_fields(appeal, status="UPHELD", decided_by=user_id, remedy_code=remedy)
    if remedy == "REINSTATE_ELIGIBILITY":
        cascade.remedy_reinstate_eligibility(application)
    elif remedy == "RESCORE_BY_NEW_PANEL":
        cascade.remedy_rescore_by_new_panel(application)
    else:
        cascade.remedy_reissue_slate(application)
    return response.obj(db.public(appeal))
