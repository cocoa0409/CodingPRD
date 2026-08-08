"""Screenings and the referring-screening cascade (PRD 3.8)."""

from flask import Blueprint

import config
import envelope
import helpers
import store
from errors import ApiError
from fields import Field
from ladder import Op
from services import calc, cascades, serialize
from services.notifications import raise_notification

bp = Blueprint("screenings", __name__)


@bp.post("/sbhc/visits/<id>/screenings")
def record_screening(id):
    op = Op("POST /sbhc/visits/{id}/screenings", ["Clinician"])
    op.path_id("visit", "visits", id, "ERR_VISIT_NOT_FOUND")
    op.schema(
        [
            Field("instrument", "enum", required=True, values=config.SCREENING_INSTRUMENTS),
            Field("numeric_result", "number", required=True, minimum=0),
        ]
    )

    def _state(op):
        if op.get("visit")["clinical_status"] not in ("IN_PROGRESS", "COMPLETED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                "A screening needs an IN_PROGRESS or COMPLETED encounter.",
            )

    op.hook(17, _state)
    op.run()

    visit = op.get("visit")
    instrument = op.body["instrument"]
    outcome, band = calc.screening_outcome(instrument, op.body["numeric_result"])

    screening = store.new_row(
        "screenings",
        {
            "visit_id": visit["id"],
            "student_id": visit["student_id"],
            "instrument": instrument,
            "numeric_result": op.body["numeric_result"],
            "outcome": outcome,
            "band_label": band,
            "generated_referral_id": None,
            "status": "REFERRED" if outcome == "REFER" else "CLOSED_PASS",
        },
    )

    if outcome == "REFER":
        student = store.get("students", visit["student_id"])
        # Link 2 — the auto-created referral and its REFERRAL_CREATED notification.
        referral = store.new_row(
            "referrals",
            {
                "student_id": visit["student_id"],
                "source_screening_id": screening["id"],
                "source_visit_id": visit["id"],
                "requested_by_user_id": op.user_id,
                "specialty": config.INSTRUMENT_TO_SPECIALTY[instrument],
                "reason": "Screening outcome REFER for instrument %s." % instrument,
                "outreach_attempt_count": 0,
                "status": "OPEN",
                "report_received_date": None,
                "report_summary": None,
                "closed_by_user_id": None,
                "closure_note": None,
            },
        )
        screening["generated_referral_id"] = referral["id"]
        raise_notification("REFERRAL_CREATED", visit["student_id"], visit)
        # Links 3 and 4 — the clearance void and its CLEARANCE_VOIDED notification.
        cascades.void_clearances(student, "SCREENING_REFERRAL_RAISED")

    return envelope.created(serialize.dump(screening))


@bp.get("/sbhc/screenings/<id>")
def read_screening(id):
    op = Op("GET /sbhc/screenings/{id}", ["Clinician", "Registrar", "SbhcAdmin"])
    op.path_id("screening", "screenings", id, "ERR_RESOURCE_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("screening")))


@bp.get("/sbhc/screenings")
def list_screenings():
    op = Op("GET /sbhc/screenings", ["Clinician", "Registrar", "SbhcAdmin"])
    op.paginated()
    op.run()
    rows = store.all_rows("screenings")
    rows = helpers.filter_eq(
        rows,
        op.args,
        {
            "student_id": "student_id",
            "visit_id": "visit_id",
            "instrument": "instrument",
            "outcome": "outcome",
            "generated_referral_id": "generated_referral_id",
        },
    )
    return helpers.list_response(rows, op)
