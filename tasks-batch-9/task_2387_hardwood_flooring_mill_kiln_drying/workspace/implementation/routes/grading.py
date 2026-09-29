"""Grading, tally valuation and bundle lines (PRD 3.7)."""

from flask import Blueprint

from db import db, insert, ordered, touch
from errors import ApiError
from middleware import ALL_ROLES, GRADE_INSPECTOR, MILL_ADMIN, authorize
from response import array_response, object_response, paginate
from serializers import serialize, serialize_many
from services import calc, lookup
from services.calc import D
from validation import (body_json, pagination, query_enum, query_str, req_decimal,
                        req_enum, req_int, req_ref)

bp = Blueprint("grading", __name__)

RULESETS = ("NHLA", "MILL_CHARACTER")
RUN_STATUSES = ("DRAFT", "FINALIZED", "SUPERSEDED")
GRADE_CLASSES = ("CLEAR", "SELECT", "NO1_COMMON", "NO2_COMMON", "CHARACTER", "CABIN")
CHARACTER_CLASSES = ("CHARACTER", "CABIN")


def _run_bundles(run_id):
    return [b for b in ordered(db.grade_bundles) if b["grade_run_id"] == run_id]


@bp.post("/mill/grade-runs")
@authorize(GRADE_INSPECTOR)
def create_grade_run():
    body = body_json()
    flooring_lot_id = req_ref(body, "flooring_lot_id")
    inspector_ruleset = req_enum(body, "inspector_ruleset", RULESETS)
    expected_lot_version = req_int(body, "expected_lot_version")

    lot = lookup.flooring_lot(flooring_lot_id)

    if expected_lot_version != int(lot["version"]):
        raise ApiError("ERR_STALE_LOT_VERSION")
    if lot["status"] != "MILLED":
        raise ApiError("ERR_LOT_STATE_INVALID")

    record = insert(db.grade_runs, {
        "flooring_lot_id": flooring_lot_id,
        "inspector_ruleset": inspector_ruleset,
        "tally_board_feet": None,
        "tally_value_cents": None,
        "credited_board_feet": None,
        "superseded_by_run_id": None,
        "status": "DRAFT",
    })
    touch(lot)
    return object_response(serialize("grade_run", record), 201)


@bp.get("/mill/grade-runs/<grade_run_id>")
@authorize(*ALL_ROLES)
def get_grade_run(grade_run_id):
    return object_response(serialize("grade_run", lookup.grade_run(grade_run_id)))


@bp.get("/mill/grade-runs")
@authorize(*ALL_ROLES)
def list_grade_runs():
    limit, offset = pagination()
    rows = lookup.filtered(db.grade_runs, [
        ("flooring_lot_id", query_str("flooring_lot_id")),
        ("superseded_by_run_id", query_str("superseded_by_run_id")),
        ("status", query_enum("status", RUN_STATUSES)),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("grade_run", page), limit, offset, total)


@bp.post("/mill/grade-runs/<grade_run_id>/bundles")
@authorize(GRADE_INSPECTOR)
def create_grade_bundle(grade_run_id):
    body = body_json()
    grade_class = req_enum(body, "grade_class", GRADE_CLASSES)
    bundle_board_feet = req_decimal(body, "bundle_board_feet")
    average_length_in = req_decimal(body, "average_length_in")

    run = lookup.grade_run(grade_run_id)
    if run["status"] != "DRAFT":
        raise ApiError("ERR_GRADE_RUN_STATE_INVALID")

    if grade_class in CHARACTER_CLASSES and run["inspector_ruleset"] != "MILL_CHARACTER":
        raise ApiError("ERR_CHARACTER_GRADE_NOT_PERMITTED")

    lot = db.flooring_lots[run["flooring_lot_id"]]
    tallied = sum((D(b["bundle_board_feet"]) for b in _run_bundles(run["id"])), D(0))
    if tallied + bundle_board_feet > D(lot["net_flooring_bf"]):
        raise ApiError("ERR_BUNDLE_BF_EXCEEDS_LOT")

    factor, credit, value_cents = calc.bundle_valuation(
        grade_class, bundle_board_feet, average_length_in)

    record = insert(db.grade_bundles, {
        "grade_run_id": run["id"],
        "grade_class": grade_class,
        "bundle_board_feet": bundle_board_feet,
        "average_length_in": average_length_in,
        "length_factor": factor,
        "credit_factor": credit,
        "tally_value_cents": value_cents,
    })
    return object_response(serialize("grade_bundle", record), 201)


@bp.get("/mill/grade-runs/<grade_run_id>/bundles")
@authorize(*ALL_ROLES)
def list_run_bundles(grade_run_id):
    limit, offset = pagination()
    run = lookup.grade_run(grade_run_id)
    rows = lookup.filtered(db.grade_bundles, [
        ("grade_run_id", run["id"]),
        ("grade_class", query_enum("grade_class", GRADE_CLASSES)),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("grade_bundle", page), limit, offset, total)


@bp.get("/mill/grade-bundles/<grade_bundle_id>")
@authorize(*ALL_ROLES)
def get_grade_bundle(grade_bundle_id):
    return object_response(serialize("grade_bundle", lookup.grade_bundle(grade_bundle_id)))


@bp.get("/mill/grade-bundles")
@authorize(*ALL_ROLES)
def list_grade_bundles():
    limit, offset = pagination()
    rows = lookup.filtered(db.grade_bundles, [
        ("grade_run_id", query_str("grade_run_id")),
        ("grade_class", query_enum("grade_class", GRADE_CLASSES)),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("grade_bundle", page), limit, offset, total)


@bp.post("/mill/grade-runs/<grade_run_id>/finalize")
@authorize(GRADE_INSPECTOR)
def finalize_grade_run(grade_run_id):
    body_json()
    run = lookup.grade_run(grade_run_id)
    if run["status"] != "DRAFT":
        raise ApiError("ERR_GRADE_RUN_STATE_INVALID")

    bundles = _run_bundles(run["id"])

    if any(b["grade_class"] in CHARACTER_CLASSES for b in bundles) and \
            run["inspector_ruleset"] != "MILL_CHARACTER":
        raise ApiError("ERR_CHARACTER_GRADE_NOT_PERMITTED")
    if not bundles:
        raise ApiError("ERR_NO_GRADE_BUNDLES")

    lot = db.flooring_lots[run["flooring_lot_id"]]
    tally_board_feet, credited, tally_value_cents = calc.run_tally(bundles)
    if tally_board_feet > D(lot["net_flooring_bf"]):
        raise ApiError("ERR_BUNDLE_BF_EXCEEDS_LOT")

    run["tally_board_feet"] = tally_board_feet
    run["credited_board_feet"] = credited
    run["tally_value_cents"] = tally_value_cents
    run["status"] = "FINALIZED"
    touch(run)
    return object_response(serialize("grade_run", run))


@bp.post("/mill/grade-runs/<grade_run_id>/supersede")
@authorize(GRADE_INSPECTOR, MILL_ADMIN)
def supersede_grade_run(grade_run_id):
    body = body_json()
    replacement_grade_run_id = req_ref(body, "replacement_grade_run_id")

    run = lookup.grade_run(grade_run_id)
    replacement = lookup.grade_run(replacement_grade_run_id)

    if run["status"] != "FINALIZED":
        raise ApiError("ERR_GRADE_RUN_STATE_INVALID")

    lot = db.flooring_lots[run["flooring_lot_id"]]
    if lot.get("final_grade_run_id") == run["id"]:
        raise ApiError("ERR_GRADE_RUN_STATE_INVALID")
    if replacement["status"] != "FINALIZED":
        raise ApiError("ERR_GRADE_RUN_STATE_INVALID")
    if replacement["flooring_lot_id"] != run["flooring_lot_id"]:
        raise ApiError("ERR_GRADE_RUN_LOT_MISMATCH")

    run["superseded_by_run_id"] = replacement["id"]
    run["status"] = "SUPERSEDED"
    touch(run)
    return object_response(serialize("grade_run", run))
