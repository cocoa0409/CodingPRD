"""/personnel-qualifications - the suite-scoped operator roster."""

from flask import Blueprint, request

import serialize
import services
from auth import endpoint
from common import ApiError, clock_now
from listing import list_response, object_response
from store import DB, by_created, new_row, set_raw, touch
from validate import (
    QUALIFICATION_TYPES,
    f_dt,
    f_enum,
    f_str,
    parse_body,
)

bp = Blueprint("personnel", __name__)

QUAL_FIELDS = [
    f_str("operator_name", 1, 40),
    f_str("suite_id", 1, None),
    f_enum("qualification_type", QUALIFICATION_TYPES),
    f_dt("expires_on"),
    f_str("media_fill_id", 1, None, required=False),
]


@bp.post("/personnel-qualifications")
@endpoint(["MicrobiologyAnalyst"])
def create_qualification():
    body = parse_body(request.get_json(silent=True), QUAL_FIELDS)
    suite = services.require("suite", body["suite_id"])
    media_fill = None
    if body["media_fill_id"] is not None:
        media_fill = services.require("media_fill", body["media_fill_id"])
    if body["expires_on"] <= clock_now():
        raise ApiError(
            "ERR_INVALID_WINDOW",
            422,
            "expires_on must be strictly later than the logical clock.",
        )
    row = new_row(
        {
            "operator_name": body["operator_name"],
            "suite_id": suite["id"],
            "media_fill_id": media_fill["id"] if media_fill else None,
            "qualification_type": body["qualification_type"],
            "expires_on": body["expires_on"],
            "status": "PENDING",
            "qualified_at": None,
        }
    )
    set_raw(row, "expires_on", body["_raw_expires_on"])
    DB.quals[row["id"]] = row
    return object_response(serialize.qualification_out(row), 201)


@bp.get("/personnel-qualifications/<qualification_id>")
@endpoint(
    ["MicrobiologyAnalyst", "ProductionSupervisor", "QaReviewer", "ProgramManager"]
)
def read_qualification(qualification_id):
    row = services.require("qualification", qualification_id)
    return object_response(serialize.qualification_out(row))


@bp.get("/personnel-qualifications")
@endpoint(
    ["MicrobiologyAnalyst", "ProductionSupervisor", "QaReviewer", "ProgramManager"]
)
def list_qualifications():
    rows = by_created(list(DB.quals.values()))
    return list_response(
        rows,
        serialize.qualification_out,
        {
            "suite_id": "suite_id",
            "media_fill_id": "media_fill_id",
            "status": "status",
            "operator_name": "operator_name",
        },
    )


@bp.post("/personnel-qualifications/<qualification_id>/qualify")
@endpoint(["MicrobiologyAnalyst"])
def qualify(qualification_id):
    qual = services.require("qualification", qualification_id)
    parse_body(request.get_json(silent=True), [])
    if qual["status"] != "PENDING":
        raise services.state_conflict(
            "ERR_QUALIFICATION_STATE_INVALID",
            "Only a PENDING qualification can be granted.",
        )
    if qual["qualification_type"] == "ASEPTIC_INTERVENTION":
        media_fill = (
            DB.media_fills.get(qual["media_fill_id"]) if qual["media_fill_id"] else None
        )
        if (
            media_fill is None
            or media_fill["status"] != "PASSED"
            or qual["operator_name"] not in media_fill["participating_operator_names"]
        ):
            raise services.state_conflict(
                "ERR_MEDIA_FILL_NOT_PASSED",
                "An ASEPTIC_INTERVENTION grant needs a PASSED simulation listing "
                "this operator.",
            )
    if qual["expires_on"] <= clock_now():
        raise ApiError(
            "ERR_INVALID_WINDOW",
            422,
            "expires_on is no longer later than the logical clock.",
        )
    qual["status"] = "QUALIFIED"
    qual["qualified_at"] = clock_now()
    touch(qual)
    return object_response(serialize.qualification_out(qual))


@bp.post("/personnel-qualifications/<qualification_id>/revoke")
@endpoint(["MicrobiologyAnalyst"])
def revoke(qualification_id):
    qual = services.require("qualification", qualification_id)
    parse_body(request.get_json(silent=True), [f_str("revoke_reason", 1, None)])
    if qual["status"] not in ("PENDING", "QUALIFIED", "LAPSED"):
        raise services.state_conflict(
            "ERR_QUALIFICATION_STATE_INVALID", "REVOKED is terminal."
        )
    qual["status"] = "REVOKED"
    touch(qual)
    return object_response(serialize.qualification_out(qual))
