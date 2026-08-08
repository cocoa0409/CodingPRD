"""Referrals, the outreach loop and loop closure (PRD 3.8)."""

from flask import Blueprint

import clock
import config
import envelope
import helpers
import store
from errors import ApiError
from fields import Field
from ladder import Op
from services import serialize
from services.notifications import raise_notification

bp = Blueprint("referrals", __name__)


@bp.post("/sbhc/students/<id>/referrals")
def create_referral(id):
    op = Op("POST /sbhc/students/{id}/referrals", ["Clinician"])
    op.path_id("student", "students", id, "ERR_STUDENT_NOT_FOUND")
    op.schema(
        [
            Field("specialty", "enum", required=True, values=config.REFERRAL_SPECIALTIES),
            Field("reason", "string", required=True, min_len=1),
            Field("source_visit_id", "string"),
        ]
    )

    def _enrollment(op):
        if helpers.active_enrollment(id, None, clock.current_school_year()) is None:
            raise ApiError(
                "ERR_ENROLLMENT_NOT_ACTIVE",
                "The student holds no ACTIVE enrollment for the current school year.",
            )

    op.hook(15, _enrollment)
    op.run()

    source_visit_id = op.field("source_visit_id", None)
    referral = store.new_row(
        "referrals",
        {
            "student_id": id,
            "source_screening_id": None,
            "source_visit_id": source_visit_id,
            "requested_by_user_id": op.user_id,
            "specialty": op.body["specialty"],
            "reason": op.body["reason"],
            "outreach_attempt_count": 0,
            "status": "OPEN",
            "report_received_date": None,
            "report_summary": None,
            "closed_by_user_id": None,
            "closure_note": None,
        },
    )
    visit = store.get("visits", source_visit_id) if source_visit_id else None
    raise_notification("REFERRAL_CREATED", id, visit)
    return envelope.created(serialize.dump(referral))


@bp.get("/sbhc/referrals/<id>")
def read_referral(id):
    op = Op("GET /sbhc/referrals/{id}", ["Clinician", "CareCoordinator", "SbhcAdmin"])
    op.path_id("referral", "referrals", id, "ERR_REFERRAL_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("referral")))


@bp.get("/sbhc/referrals")
def list_referrals():
    op = Op("GET /sbhc/referrals", ["Clinician", "CareCoordinator", "SbhcAdmin"])
    op.paginated()
    op.run()
    rows = store.all_rows("referrals")
    rows = helpers.filter_eq(
        rows,
        op.args,
        {
            "student_id": "student_id",
            "source_screening_id": "source_screening_id",
            "source_visit_id": "source_visit_id",
            "requested_by_user_id": "requested_by_user_id",
            "status": "status",
        },
    )
    return helpers.list_response(rows, op)


@bp.post("/sbhc/referrals/<id>/outreach-attempts")
def outreach_attempt(id):
    op = Op("POST /sbhc/referrals/{id}/outreach-attempts", ["CareCoordinator"])
    op.path_id("referral", "referrals", id, "ERR_REFERRAL_NOT_FOUND")
    op.schema([Field("outcome", "enum", required=True, values=config.OUTREACH_OUTCOMES)])

    def _cap(op):
        # Rung 16 sits ABOVE the state check so the cap error stays observable
        # on a referral already LOST_TO_FOLLOW_UP (PRD 2.6).
        if op.get("referral")["outreach_attempt_count"] >= config.MAX_OUTREACH_ATTEMPTS:
            raise ApiError(
                "ERR_OUTREACH_LIMIT_EXCEEDED",
                "All three outreach attempts have been used.",
            )

    def _state(op):
        if op.get("referral")["status"] not in ("OPEN", "OUTREACH_IN_PROGRESS"):
            raise ApiError(
                "ERR_INVALID_STATE", "This referral is not open to outreach attempts."
            )

    op.hook(16, _cap)
    op.hook(17, _state)
    op.run()

    referral = op.get("referral")
    referral["outreach_attempt_count"] = referral["outreach_attempt_count"] + 1
    if op.body["outcome"] == "REACHED":
        referral["status"] = "SCHEDULED"
    else:
        if referral["outreach_attempt_count"] >= config.MAX_OUTREACH_ATTEMPTS:
            referral["status"] = "LOST_TO_FOLLOW_UP"
        else:
            referral["status"] = "OUTREACH_IN_PROGRESS"
    store.touch(referral)
    return envelope.ok(serialize.dump(referral))


@bp.post("/sbhc/referrals/<id>/report-back")
def report_back(id):
    op = Op("POST /sbhc/referrals/{id}/report-back", ["CareCoordinator"])
    op.path_id("referral", "referrals", id, "ERR_REFERRAL_NOT_FOUND")
    op.schema(
        [
            Field("report_summary", "string", required=True, min_len=1),
            Field("report_received_date", "date", required=True),
        ]
    )

    def _state(op):
        if op.get("referral")["status"] != "SCHEDULED":
            raise ApiError(
                "ERR_INVALID_STATE", "Only a SCHEDULED referral may record a report-back."
            )

    def _not_future(op):
        if clock.parse_date(op.body["report_received_date"]) > clock.now_date():
            raise ApiError(
                "ERR_VALIDATION",
                "report_received_date must not be after the current clock date.",
            )

    op.hook(17, _state)
    op.hook(24, _not_future)
    op.run()

    referral = op.get("referral")
    referral["report_summary"] = op.body["report_summary"]
    referral["report_received_date"] = op.body["report_received_date"]
    referral["status"] = "REPORT_RECEIVED"
    store.touch(referral)
    return envelope.ok(serialize.dump(referral))


@bp.post("/sbhc/referrals/<id>/close")
def close_referral(id):
    op = Op("POST /sbhc/referrals/{id}/close", ["CareCoordinator", "Clinician"])
    op.path_id("referral", "referrals", id, "ERR_REFERRAL_NOT_FOUND")
    op.schema([Field("closure_note", "string", required=True)])

    def _segregation(op):
        # Rung 13 sits above rung 17: a wrong-state close attempted by the
        # requester still reports ERR_SEGREGATION_OF_DUTIES (PRD 2.6).
        if op.user_id == op.get("referral")["requested_by_user_id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The requester of a referral may not close it.",
            )

    def _state(op):
        if op.get("referral")["status"] != "REPORT_RECEIVED":
            raise ApiError(
                "ERR_INVALID_STATE", "Only a REPORT_RECEIVED referral may be closed."
            )

    op.hook(13, _segregation)
    op.hook(17, _state)
    op.run()

    referral = op.get("referral")
    referral["status"] = "CLOSED"
    referral["closed_by_user_id"] = op.user_id
    referral["closure_note"] = op.body["closure_note"]
    store.touch(referral)
    return envelope.ok(serialize.dump(referral))
