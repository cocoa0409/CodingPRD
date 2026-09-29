"""/filling-suites - registration, reads and cleaning validation."""

from flask import Blueprint, request

import calc
import serialize
import services
from auth import endpoint
from listing import list_response, object_response
from store import DB, batches_of_suite, by_created, new_row, touch
from validate import (
    SUITE_GRADES,
    bad_request,
    f_enum,
    f_int,
    f_num,
    f_str,
    parse_body,
)

bp = Blueprint("suites", __name__)

SUITE_FIELDS = [
    f_str("suite_code", 1, 20),
    f_enum("grade", SUITE_GRADES),
    f_int("changeover_minutes_same_product", 0),
    f_int("changeover_minutes_product_change", 0),
    f_int("max_committed_minutes", 1),
]


@bp.post("/filling-suites")
@endpoint(["ProgramManager"])
def create_suite():
    body = parse_body(request.get_json(silent=True), SUITE_FIELDS)
    if body["changeover_minutes_product_change"] < body["changeover_minutes_same_product"]:
        raise bad_request(
            "changeover_minutes_product_change must be at least "
            "changeover_minutes_same_product."
        )
    for existing in DB.suites.values():
        if existing["suite_code"] == body["suite_code"]:
            raise services.state_conflict(
                "ERR_DUPLICATE_SUITE_CODE", "That suite_code is already registered."
            )
    row = new_row(
        {
            "suite_code": body["suite_code"],
            "grade": body["grade"],
            "changeover_minutes_same_product": body["changeover_minutes_same_product"],
            "changeover_minutes_product_change": body["changeover_minutes_product_change"],
            "max_committed_minutes": body["max_committed_minutes"],
            "aseptic_qualification_status": "NOT_QUALIFIED",
            "media_fill_valid_until": None,
            "cleaning_validation_status": "NOT_VALIDATED",
            "last_cleaned_molecule": None,
            "_invalidated_read_at": None,
        }
    )
    DB.suites[row["id"]] = row
    return object_response(serialize.suite_out(row), 201)


@bp.get("/filling-suites/<suite_id>")
@endpoint(
    [
        "ProgramManager",
        "ProductionSupervisor",
        "MicrobiologyAnalyst",
        "QaReviewer",
        "QualifiedPerson",
    ]
)
def read_suite(suite_id):
    row = services.require("suite", suite_id)
    return object_response(serialize.suite_out(row))


@bp.get("/filling-suites")
@endpoint(
    ["ProgramManager", "ProductionSupervisor", "MicrobiologyAnalyst", "QaReviewer"]
)
def list_suites():
    rows = by_created(list(DB.suites.values()))
    args = request.args
    if "posture" in args:
        wanted = args.get("posture")
        rows = [r for r in rows if calc.suite_posture(r) == wanted]
    return list_response(rows, serialize.suite_out, {"grade": "grade"})


CLEANING_FIELDS = [
    f_str("molecule_name", 1, 80),
    f_num("residue_ug_per_swab"),
]


@bp.post("/filling-suites/<suite_id>/cleaning-validation")
@endpoint(["MicrobiologyAnalyst"])
def cleaning_validation(suite_id):
    suite = services.require("suite", suite_id)
    body = parse_body(request.get_json(silent=True), CLEANING_FIELDS)
    for batch in batches_of_suite(suite_id):
        if batch["production_status"] == "FILLING":
            raise services.state_conflict(
                "ERR_BATCH_PRODUCTION_STATE_INVALID",
                "A batch in this suite is FILLING; cleaning validation cannot run.",
            )
    if body["residue_ug_per_swab"] <= calc.CLEANING_RESIDUE_LIMIT_UG:
        suite["cleaning_validation_status"] = "VALIDATED"
        suite["last_cleaned_molecule"] = body["molecule_name"]
    else:
        suite["cleaning_validation_status"] = "FAILED"
    touch(suite)
    if calc.suite_posture(suite) == "FROZEN":
        services.suspend_suite_batches(suite)
    return object_response(serialize.suite_out(suite))
