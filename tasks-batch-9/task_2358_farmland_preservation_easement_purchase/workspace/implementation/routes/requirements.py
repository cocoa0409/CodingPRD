"""ClosingRequirement endpoints (PRD 3.7)."""

from decimal import Decimal

from flask import Blueprint

from db import db, touch
from errors import ApiError
from middleware import authenticate
from response import ok
from services import cascade, lookup, serialize
from validation import Payload, raw_body

bp = Blueprint("requirements", __name__)

SURVEY_TOLERANCE = Decimal("0.50")
OPEN_CLOSING_STATES = ("PENDING_REQUIREMENTS", "BLOCKED", "CLEARED")


@bp.get("/closing-requirements/<requirement_id>")
def read_requirement(requirement_id):
    authenticate(("ProgramAdmin", "AcquisitionOfficer", "Landowner"))
    return ok(serialize.closing_requirement(lookup.get_requirement(requirement_id)))


@bp.post("/closing-requirements/<requirement_id>/submission")
def submit_requirement(requirement_id):
    user_id, _ = authenticate(("AcquisitionOfficer",))
    requirement = lookup.get_requirement(requirement_id)
    payload = Payload(
        raw_body(), ("lienholder_name", "exception_count", "surveyed_acres")
    )
    lienholder_name = payload.string(
        "lienholder_name", required=False, default=None, min_len=1, max_len=160
    )
    exception_count = payload.integer(
        "exception_count", required=False, default=0, minimum=0
    )
    surveyed_acres = payload.decimal(
        "surveyed_acres", required=False, default=None, exclusive_min=0, max_decimals=2
    )

    # rung 9 -- requirement dimension first, then the closing dimension.
    if requirement["status"] not in ("OUTSTANDING", "DEFICIENT", "SATISFIED"):
        raise ApiError(
            "ERR_INVALID_REQUIREMENT_STATE",
            "only an OUTSTANDING, DEFICIENT or SATISFIED requirement can be submitted",
        )
    app = db.applications[requirement["application_id"]]
    if app["closing_status"] not in OPEN_CLOSING_STATES:
        raise ApiError(
            "ERR_INVALID_CLOSING_STATE",
            "the closing file is not open for requirement submissions",
        )

    parcel = lookup.parcel_of_application(app)
    requirement_type = requirement["requirement_type"]

    # rung 15 -- the polymorphic payload rules.
    if requirement_type == "MORTGAGE_SUBORDINATION":
        if lienholder_name is None or lienholder_name != parcel["mortgage_lienholder_name"]:
            raise ApiError(
                "ERR_LIENHOLDER_REQUIRED",
                "lienholder_name must equal the parcel's mortgage_lienholder_name",
            )
    elif lienholder_name is not None:
        raise ApiError(
            "ERR_LIENHOLDER_REQUIRED",
            "lienholder_name is only accepted on a MORTGAGE_SUBORDINATION",
        )

    if requirement_type == "BOUNDARY_SURVEY":
        if surveyed_acres is None:
            raise ApiError(
                "ERR_SURVEY_ACREAGE_MISMATCH",
                "surveyed_acres is required on a BOUNDARY_SURVEY submission",
            )
        if abs(surveyed_acres - parcel["acres"]) > SURVEY_TOLERANCE:
            raise ApiError(
                "ERR_SURVEY_ACREAGE_MISMATCH",
                "surveyed_acres differs from the parcel acreage by more than 0.50 acres",
            )
    elif surveyed_acres is not None:
        raise ApiError(
            "ERR_SURVEY_ACREAGE_MISMATCH",
            "surveyed_acres is only accepted on a BOUNDARY_SURVEY",
        )

    requirement["status"] = "SUBMITTED"
    requirement["submitted_by_user_id"] = user_id
    requirement["deficiency_note"] = None
    if requirement_type == "TITLE_COMMITMENT":
        requirement["exception_count"] = exception_count
    if requirement_type == "BOUNDARY_SURVEY":
        requirement["surveyed_acres"] = surveyed_acres
    touch(requirement)
    cascade.bubble_closing_status(app)
    return ok(serialize.closing_requirement(requirement))


@bp.post("/closing-requirements/<requirement_id>/review")
def review_requirement(requirement_id):
    user_id, _ = authenticate(("ProgramAdmin",))
    requirement = lookup.get_requirement(requirement_id)
    payload = Payload(raw_body(), ("decision", "deficiency_note"))
    decision = payload.enum("decision", ("ACCEPT", "REJECT"))
    deficiency_note = payload.string(
        "deficiency_note", required=False, default=None, min_len=1, max_len=500
    )
    if decision == "REJECT" and deficiency_note is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "deficiency_note is mandatory on rejection"
        )

    if requirement["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_REQUIREMENT_STATE",
            "only a SUBMITTED requirement can be reviewed",
        )

    # rung 10 -- segregation of duties.
    if user_id == requirement["submitted_by_user_id"]:
        raise ApiError(
            "ERR_CLOSING_REVIEW_SOD",
            "the reviewer may not be the officer who submitted the requirement",
        )

    if (
        decision == "ACCEPT"
        and requirement["requirement_type"] == "TITLE_COMMITMENT"
        and int(requirement["exception_count"] or 0) > 0
    ):
        raise ApiError(
            "ERR_TITLE_EXCEPTIONS_OUTSTANDING",
            "a title commitment with outstanding exceptions cannot be accepted",
        )

    app = db.applications[requirement["application_id"]]
    requirement["reviewed_by_user_id"] = user_id
    if decision == "ACCEPT":
        requirement["status"] = "SATISFIED"
        requirement["deficiency_note"] = None
    else:
        requirement["status"] = "DEFICIENT"
        requirement["deficiency_note"] = deficiency_note
    touch(requirement)
    cascade.bubble_closing_status(app)
    return ok(serialize.closing_requirement(requirement))


@bp.post("/closing-requirements/<requirement_id>/waiver")
def waive_requirement(requirement_id):
    authenticate(("ProgramAdmin",))
    requirement = lookup.get_requirement(requirement_id)
    payload = Payload(raw_body(), ("waiver_reason",))
    waiver_reason = payload.string("waiver_reason", min_len=1, max_len=500)

    if requirement["status"] not in ("OUTSTANDING", "DEFICIENT"):
        raise ApiError(
            "ERR_INVALID_REQUIREMENT_STATE",
            "only an OUTSTANDING or DEFICIENT requirement can be waived",
        )
    if requirement["requirement_type"] != "BOUNDARY_SURVEY":
        raise ApiError(
            "ERR_REQUIREMENT_NOT_WAIVABLE",
            "only a BOUNDARY_SURVEY requirement is waivable",
        )

    app = db.applications[requirement["application_id"]]
    requirement["status"] = "WAIVED"
    requirement["waiver_reason"] = waiver_reason
    touch(requirement)
    cascade.bubble_closing_status(app)
    return ok(serialize.closing_requirement(requirement))
