"""Contesting a failed attempt: filing, review and the three decisions."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.reads import fetch
from services import calc, cascades, derive

bp = Blueprint("appeals", __name__)

LIVE_APPEAL = ("FILED", "UNDER_REVIEW", "REMANDED")


@bp.post("/v1/appeals")
def file_appeal():
    user_id, role = mw.authenticate("Rebuilder")
    data = mw.body()

    # 4. body foreign keys
    inspection_id = data.get("inspection_id")
    if not isinstance(inspection_id, str) or not inspection_id.strip():
        mw.bad("inspection_id", "is required")
    inspection = db.db.inspections.get(inspection_id)
    if inspection is None:
        raise ApiError("ERR_INSPECTION_NOT_FOUND")

    # 5. well-formedness
    grounds = mw.req_enum(data, "grounds", calc.APPEAL_GROUNDS)
    narrative = mw.req_str(data, "narrative")

    application = db.db.applications.get(inspection["application_id"])

    # 7. ownership
    if role == "Rebuilder" and (application is None or application["rebuilder_id"] != user_id):
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # 9. state-machine admissibility
    for existing in derive.appeals_of_inspection(inspection_id):
        if existing["status"] in LIVE_APPEAL:
            raise ApiError(
                "ERR_APPEAL_STATE_INVALID",
                "An appeal of this attempt is already in flight.",
            )

    # 13. temporal windows
    if inspection["status"] != "COMPLETED_FAIL":
        raise ApiError(
            "ERR_APPEAL_WINDOW_CLOSED", "Only a COMPLETED_FAIL attempt may be appealed."
        )
    completed_at = db.parse_dt(inspection["completed_at"])
    if completed_at is not None and db.now() > completed_at + db.days(calc.APPEAL_WINDOW_DAYS):
        raise ApiError(
            "ERR_APPEAL_WINDOW_CLOSED", "The 30-day appeal window on this attempt has closed."
        )

    row = db.new_row()
    row.update(
        {
            "inspection_id": inspection_id,
            "grounds": grounds,
            "narrative": narrative,
            "status": "FILED",
            "filed_at": db.now_iso(),
            "decided_at": None,
            "hearing_officer_user_id": None,
            "remand_count": 0,
            "decision_note": None,
        }
    )
    db.db.appeals[row["id"]] = row

    if application is not None and application["status"] == "FAILED":
        application["status"] = "APPEAL_PENDING"
        derive.recompute_application(application, touch_row=False)
        db.touch(application)
    return response.single(derive.appeal_out(row), 201)


@bp.post("/v1/appeals/<row_id>/review")
def review_appeal(row_id):
    user_id, _role = mw.authenticate("HearingOfficer")
    appeal = fetch(db.db.appeals, row_id, "ERR_APPEAL_NOT_FOUND")
    data = mw.body()
    mw.opt_str(data, "review_note")

    # 9. state-machine admissibility
    if appeal["status"] not in ("FILED", "REMANDED"):
        raise ApiError(
            "ERR_APPEAL_STATE_INVALID", "Only a FILED or REMANDED appeal may be taken up."
        )

    appeal["status"] = "UNDER_REVIEW"
    appeal["hearing_officer_user_id"] = user_id
    db.touch(appeal)
    return response.single(derive.appeal_out(appeal))


@bp.post("/v1/appeals/<row_id>/decide")
def decide_appeal(row_id):
    _user_id, _role = mw.authenticate("HearingOfficer")
    appeal = fetch(db.db.appeals, row_id, "ERR_APPEAL_NOT_FOUND")
    data = mw.body()
    decision = mw.req_enum(data, "decision", calc.APPEAL_DECISIONS)
    decision_note = mw.opt_str(data, "decision_note")

    # 9. state-machine admissibility
    if appeal["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_APPEAL_STATE_INVALID", "Only an UNDER_REVIEW appeal may be decided."
        )
    if decision == "REMAND" and appeal["remand_count"] >= 1:
        raise ApiError("ERR_APPEAL_STATE_INVALID", "An appeal may only be remanded once.")

    inspection = db.db.inspections.get(appeal["inspection_id"])
    application = None
    if inspection is not None:
        application = db.db.applications.get(inspection["application_id"])

    if decision == "GRANT":
        appeal["status"] = "GRANTED"
        appeal["decided_at"] = db.now_iso()
        appeal["decision_note"] = decision_note
        db.touch(appeal)
        if inspection is not None:
            for finding in derive.findings_of_inspection(inspection["id"]):
                finding["resolved"] = True
            # blocking_findings_count falls to 0; forced_fail stays latched for audit
            derive.recompute_inspection(inspection, touch_row=True)
        if application is not None:
            application["attempt_limit"] = application["attempt_limit"] + 1
            if application["status"] == "APPEAL_PENDING":
                application["status"] = "DOCS_ACCEPTED"
            derive.recompute_application(application, touch_row=False)
            db.touch(application)
    elif decision == "DENY":
        appeal["status"] = "DENIED"
        appeal["decided_at"] = db.now_iso()
        appeal["decision_note"] = decision_note
        db.touch(appeal)
        if application is not None:
            derive.recompute_application(application, touch_row=False)
            exhausted = application["attempts_completed"] >= application["attempt_limit"]
            if exhausted:
                rebuilder = db.db.rebuilders.get(application["rebuilder_id"])
                if rebuilder is not None:
                    cascades.capture_escrow(application, rebuilder)
                else:
                    application["fee_escrowed_cents"] = 0
                application["status"] = "DENIED_FINAL"
                application["terminal_at"] = db.now_iso()
                derive.recompute_application(application, touch_row=False)
                db.touch(application)
                if rebuilder is not None:
                    derive.recompute_rebuilder(rebuilder, touch_row=True)
                vehicle = db.db.vehicles.get(application["vehicle_id"])
                if vehicle is not None:
                    derive.recompute_vehicle(vehicle, touch_row=True)
            else:
                application["status"] = "FAILED"
                derive.recompute_application(application, touch_row=False)
                db.touch(application)
    else:
        appeal["status"] = "REMANDED"
        appeal["remand_count"] = appeal["remand_count"] + 1
        appeal["decision_note"] = decision_note
        db.touch(appeal)
    return response.single(derive.appeal_out(appeal))
