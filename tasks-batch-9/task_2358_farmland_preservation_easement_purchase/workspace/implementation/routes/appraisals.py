"""Appraisal endpoints (PRD 3.4)."""

from datetime import timedelta

from flask import Blueprint, request

from db import base_row, db, touch
from errors import ApiError
from middleware import authenticate, require_owner
from response import created, listing, ok, pagination
from services import calc, lookup, serialize
from validation import Payload, raw_body

bp = Blueprint("appraisals", __name__)

METHODS = ("PAIRED_SALES", "INCOME_CAPITALIZATION")
APPRAISAL_STATUSES = ("ASSIGNED", "SUBMITTED", "CERTIFIED", "REJECTED")
OCCUPYING_STATUSES = ("ASSIGNED", "SUBMITTED", "CERTIFIED")
READ_ROLES = ("ProgramAdmin", "AcquisitionOfficer", "AppraisalReviewer", "Appraiser")


@bp.post("/applications/<application_id>/appraisals")
def engage_appraiser(application_id):
    user_id, _ = authenticate(("AcquisitionOfficer",))
    app = lookup.get_application(application_id)
    payload = Payload(
        raw_body(),
        (
            "appraiser_user_id",
            "appraiser_firm",
            "engagement_start",
            "engagement_end",
            "method",
        ),
    )
    appraiser_user_id = payload.string("appraiser_user_id", min_len=1, max_len=64)
    firm = payload.string("appraiser_firm", min_len=1, max_len=160)
    start = payload.instant("engagement_start")
    end = payload.instant("engagement_end")
    method = payload.enum("method", METHODS)
    if end < start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "engagement_end must be at or after engagement_start"
        )

    if app["status"] not in ("RECEIVED", "RANKED", "OFFER_ISSUED", "COUNTERED"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "appraisals may only be engaged before acceptance",
        )

    program = lookup.program_of_application(app)
    buffer_days = timedelta(days=int(program["appraisal_engagement_buffer_days"]))
    for existing in lookup.appraisals_of(app["id"]):
        if existing["status"] not in OCCUPYING_STATUSES:
            continue
        if start <= existing["engagement_end"] + buffer_days and (
            existing["engagement_start"] <= end + buffer_days
        ):
            raise ApiError(
                "ERR_APPRAISAL_ENGAGEMENT_CONFLICT",
                "the engagement interval conflicts with an existing engagement",
            )

    row = base_row()
    row.update(
        {
            "application_id": app["id"],
            "appraiser_user_id": appraiser_user_id,
            "appraiser_firm": firm,
            "engagement_start": start,
            "engagement_end": end,
            "method": method,
            "unrestricted_value_cents": None,
            "restricted_value_cents": None,
            "easement_value_cents": None,
            "basis": "CERTIFIED_APPRAISAL_BASIS",
            "status": "ASSIGNED",
            "engaged_by_user_id": user_id,
            "certified_by_user_id": None,
            "review_note": None,
            "submission_count": 0,
        }
    )
    db.appraisals[row["id"]] = row
    return created(serialize.appraisal(row))


@bp.get("/applications/<application_id>/appraisals")
def list_application_appraisals(application_id):
    authenticate(READ_ROLES)
    app = lookup.get_application(application_id)
    limit, offset = pagination(request.args)
    status = request.args.get("status")
    if status is not None and status not in APPRAISAL_STATUSES:
        raise ApiError("ERR_INVALID_REQUEST", "status filter is not valid")
    rows = lookup.appraisals_of(app["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return listing(rows, limit, offset, serialize.appraisal)


@bp.get("/appraisals/<appraisal_id>")
def read_appraisal(appraisal_id):
    authenticate(READ_ROLES)
    return ok(serialize.appraisal(lookup.get_appraisal(appraisal_id)))


@bp.post("/appraisals/<appraisal_id>/submission")
def submit_appraisal(appraisal_id):
    authenticate(("Appraiser",))
    appraisal = lookup.get_appraisal(appraisal_id)
    payload = Payload(raw_body(), ("unrestricted_value_cents", "restricted_value_cents"))
    unrestricted = payload.integer("unrestricted_value_cents", minimum=1)
    restricted = payload.integer("restricted_value_cents", minimum=0)
    if restricted >= unrestricted:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "restricted_value_cents must be strictly below unrestricted_value_cents",
        )

    require_owner(appraisal["appraiser_user_id"])

    if appraisal["status"] not in ("ASSIGNED", "REJECTED"):
        raise ApiError(
            "ERR_INVALID_APPRAISAL_STATE",
            "submission requires the appraisal to be ASSIGNED or REJECTED",
        )

    app = db.applications[appraisal["application_id"]]
    parcel = lookup.parcel_of_application(app)
    appraisal["unrestricted_value_cents"] = unrestricted
    appraisal["restricted_value_cents"] = restricted
    appraisal["easement_value_cents"] = calc.certified_easement_value_cents(
        unrestricted, restricted, parcel["acres"]
    )
    appraisal["status"] = "SUBMITTED"
    appraisal["review_note"] = None
    appraisal["submission_count"] = int(appraisal["submission_count"]) + 1
    touch(appraisal)
    return ok(serialize.appraisal(appraisal))


@bp.post("/appraisals/<appraisal_id>/review")
def review_appraisal(appraisal_id):
    user_id, _ = authenticate(("AppraisalReviewer",))
    appraisal = lookup.get_appraisal(appraisal_id)
    payload = Payload(raw_body(), ("decision", "review_note"))
    decision = payload.enum("decision", ("CERTIFY", "REJECT"))
    review_note = payload.string(
        "review_note", required=False, default=None, min_len=1, max_len=500
    )
    if decision == "REJECT" and review_note is None:
        raise ApiError("ERR_INVALID_REQUEST", "review_note is mandatory on rejection")

    if appraisal["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_APPRAISAL_STATE", "only a SUBMITTED appraisal can be reviewed"
        )

    if user_id == appraisal["engaged_by_user_id"] or user_id == appraisal["appraiser_user_id"]:
        raise ApiError(
            "ERR_APPRAISAL_REVIEW_SOD",
            "the reviewer may be neither the engaging officer nor the appraiser",
        )

    app = db.applications[appraisal["application_id"]]
    if decision == "CERTIFY":
        appraisal["status"] = "CERTIFIED"
        appraisal["certified_by_user_id"] = user_id
        app["certified_easement_value_cents"] = appraisal["easement_value_cents"]
        touch(app)
    else:
        appraisal["status"] = "REJECTED"
        appraisal["review_note"] = review_note
        appraisal["easement_value_cents"] = None
    touch(appraisal)
    return ok(serialize.appraisal(appraisal))
