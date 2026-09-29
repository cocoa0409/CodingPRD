"""/media-fills - aseptic process simulations and their outcome branches."""

from flask import Blueprint, request

import calc
import serialize
import services
from auth import endpoint
from common import ApiError, clock_now
from listing import list_response, object_response
from store import DB, batches_of_suite, by_created, new_row, set_raw, touch
from validate import (
    MEDIA_FILL_OUTCOMES,
    bad_request,
    f_array,
    f_dt,
    f_enum,
    f_int,
    f_str,
    parse_body,
)

bp = Blueprint("mediafills", __name__)


@bp.post("/media-fills")
@endpoint(["MicrobiologyAnalyst"])
def create_media_fill():
    body = parse_body(
        request.get_json(silent=True),
        [f_str("suite_id", 1, None), f_dt("scheduled_run_date")],
    )
    suite = services.require("suite", body["suite_id"])
    row = new_row(
        {
            "suite_id": suite["id"],
            "scheduled_run_date": body["scheduled_run_date"],
            "units_filled": None,
            "contaminated_units": None,
            "participating_operator_names": [],
            "status": "SCHEDULED",
            "read_at": None,
            "outcome_reason": None,
        }
    )
    set_raw(row, "scheduled_run_date", body["_raw_scheduled_run_date"])
    DB.media_fills[row["id"]] = row
    return object_response(serialize.media_fill_out(row), 201)


@bp.get("/media-fills/<media_fill_id>")
@endpoint(
    ["MicrobiologyAnalyst", "QaReviewer", "QualifiedPerson", "ProgramManager"]
)
def read_media_fill(media_fill_id):
    row = services.require("media_fill", media_fill_id)
    return object_response(serialize.media_fill_out(row))


@bp.get("/media-fills")
@endpoint(
    ["MicrobiologyAnalyst", "QaReviewer", "QualifiedPerson", "ProgramManager"]
)
def list_media_fills():
    rows = by_created(list(DB.media_fills.values()))
    return list_response(
        rows, serialize.media_fill_out, {"suite_id": "suite_id", "status": "status"}
    )


def _no_filling_batch(suite_id):
    for batch in batches_of_suite(suite_id):
        if batch["production_status"] == "FILLING":
            raise services.state_conflict(
                "ERR_BATCH_PRODUCTION_STATE_INVALID",
                "A batch in this suite is FILLING.",
            )


@bp.post("/media-fills/<media_fill_id>/execute")
@endpoint(["MicrobiologyAnalyst"])
def execute_media_fill(media_fill_id):
    media_fill = services.require("media_fill", media_fill_id)
    body = parse_body(
        request.get_json(silent=True),
        [
            f_int("units_filled", 0),
            f_array("participating_operator_names", item="str", min_items=1),
        ],
    )
    _no_filling_batch(media_fill["suite_id"])
    if media_fill["status"] != "SCHEDULED":
        raise services.state_conflict(
            "ERR_MEDIA_FILL_STATE_INVALID",
            "Only a SCHEDULED simulation can be executed.",
        )
    if body["units_filled"] < calc.MEDIA_FILL_MIN_UNITS:
        raise ApiError(
            "ERR_MEDIA_FILL_UNDERSIZED",
            422,
            "An aseptic process simulation must fill at least 5000 units.",
        )
    media_fill["units_filled"] = body["units_filled"]
    media_fill["participating_operator_names"] = list(
        body["participating_operator_names"]
    )
    media_fill["status"] = "INCUBATING"
    touch(media_fill)
    return object_response(serialize.media_fill_out(media_fill))


def _apply_pass(media_fill, suite, reason):
    media_fill["status"] = "PASSED"
    media_fill["outcome_reason"] = reason
    touch(media_fill)
    services.qualify_suite_from_media_fill(media_fill, suite)


def _apply_fail(media_fill, suite, reason):
    media_fill["status"] = "FAILED"
    media_fill["outcome_reason"] = reason
    touch(media_fill)
    services.fail_suite_from_media_fill(media_fill, suite)


@bp.post("/media-fills/<media_fill_id>/read")
@endpoint(["MicrobiologyAnalyst"])
def read_out_media_fill(media_fill_id):
    media_fill = services.require("media_fill", media_fill_id)
    body = parse_body(request.get_json(silent=True), [f_int("contaminated_units", 0)])
    if media_fill["status"] != "INCUBATING":
        raise services.state_conflict(
            "ERR_MEDIA_FILL_STATE_INVALID",
            "Only an INCUBATING simulation can be read out.",
        )
    if (media_fill["units_filled"] or 0) < calc.MEDIA_FILL_MIN_UNITS:
        raise ApiError(
            "ERR_MEDIA_FILL_UNDERSIZED",
            422,
            "The recorded run is below the 5000-unit minimum.",
        )
    suite = DB.suites.get(media_fill["suite_id"])
    contaminated = body["contaminated_units"]
    media_fill["contaminated_units"] = contaminated
    media_fill["read_at"] = clock_now()
    if contaminated == 0:
        _apply_pass(media_fill, suite, "ZERO_CONTAMINANT_PASS")
    elif contaminated == 1:
        media_fill["status"] = "INVESTIGATION_REQUIRED"
        media_fill["outcome_reason"] = "SINGLE_UNIT_INVESTIGATION"
        touch(media_fill)
    else:
        _apply_fail(media_fill, suite, "MULTI_UNIT_FAILURE")
    return object_response(serialize.media_fill_out(media_fill))


@bp.post("/media-fills/<media_fill_id>/adjudicate")
@endpoint(["QaReviewer"])
def adjudicate_media_fill(media_fill_id):
    media_fill = services.require("media_fill", media_fill_id)
    body = parse_body(
        request.get_json(silent=True),
        [
            f_enum("outcome", MEDIA_FILL_OUTCOMES),
            f_str("adjudication_rationale", 1, None),
        ],
    )
    if media_fill["status"] != "INVESTIGATION_REQUIRED":
        raise services.state_conflict(
            "ERR_MEDIA_FILL_STATE_INVALID",
            "Only an INVESTIGATION_REQUIRED simulation can be adjudicated.",
        )
    suite = DB.suites.get(media_fill["suite_id"])
    if body["outcome"] == "PASSED":
        _apply_pass(media_fill, suite, "ADJUDICATED_PASS")
    else:
        _apply_fail(media_fill, suite, "ADJUDICATED_FAILURE")
    return object_response(serialize.media_fill_out(media_fill))
