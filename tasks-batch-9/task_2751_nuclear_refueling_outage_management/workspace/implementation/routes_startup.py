"""Startup testing and reactivity management (PRD 3.9)."""
from flask import Blueprint, request

import calc
import lookup
import projections
from auth import ALL_ROLES, authorize, current_user_id
from calc import dec
from db import create_row, store, touch
from errors import api_error
from response import ok, paginated, parse_pagination
from serializers import serialize
from validators import F, body

bp = Blueprint("startup", __name__)

HOLD_POINT_TYPES = ("REGULATORY", "STATION", "NONE")


@bp.route("/outages/<outage_id>/startup-tests", methods=["POST"])
@authorize("ReactorEngineer", "RegulatoryAffairs")
def create_startup_test(outage_id):
    outage = lookup.outage(outage_id)
    payload = body([
        F("test_code", "str", min_len=1, max_len=32),
        F("sequence_index", "int", ge=1),
        F("hold_point_type", "str", enum=HOLD_POINT_TYPES),
        F("predicted_reactivity_pcm", "num"),
    ])
    for existing in projections.startup_tests_of_outage(outage["id"]):
        if existing["sequence_index"] == payload["sequence_index"]:
            raise api_error("ERR_STARTUP_SEQUENCE_DUPLICATE",
                            "That sequence_index is already used in this outage.")

    test = create_row(store.startup_tests, {
        "outage_id": outage["id"],
        "test_code": payload["test_code"],
        "sequence_index": payload["sequence_index"],
        "hold_point_type": payload["hold_point_type"],
        "predicted_reactivity_pcm": calc.q2(payload["predicted_reactivity_pcm"]),
        "measured_reactivity_pcm": None,
        "reactivity_deviation_pcm": None,
        "nrc_release_reference": None,
        "status": "PENDING",
        "created_by_user_id": current_user_id(),
        "satisfied_by_user_id": None,
    })
    return ok(serialize(test), 201)


@bp.route("/startup-tests/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_startup_test(row_id):
    return ok(serialize(lookup.startup_test(row_id)))


@bp.route("/outages/<outage_id>/startup-tests", methods=["GET"])
@authorize(*ALL_ROLES)
def list_startup_tests(outage_id):
    outage = lookup.outage(outage_id)
    limit, offset = parse_pagination(request.args)
    rows = projections.startup_tests_of_outage(outage["id"])
    wanted = request.args.get("status")
    if wanted is not None:
        rows = [r for r in rows if r["status"] == wanted]
    rows = sorted(rows, key=lambda r: r["sequence_index"])
    return paginated(rows, limit, offset, serialize)


@bp.route("/startup-tests/<row_id>/satisfy", methods=["POST"])
@authorize("RegulatoryAffairs")
def satisfy_startup_test(row_id):
    test = lookup.startup_test(row_id)
    payload = body([
        F("measured_reactivity_pcm", "num"),
        F("nrc_release_reference", "str", required=False, default=None,
          nullable=True, min_len=1, max_len=64),
    ])
    if test["status"] not in ("PENDING", "FAILED"):
        raise api_error("ERR_STARTUP_TEST_STATE_INVALID",
                        "A SATISFIED startup test cannot be re-measured.")
    outage = store.outages[test["outage_id"]]
    if outage["status"] != "STARTUP":
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "Satisfying a startup test requires the outage to be in STARTUP.")
    regulatory = test["hold_point_type"] == "REGULATORY"
    if regulatory and payload["nrc_release_reference"] is None:
        raise api_error("ERR_REGULATORY_HOLD_POINT_NOT_RELEASED",
                        "A REGULATORY hold point requires an NRC release reference.")
    siblings = projections.startup_tests_of_outage(outage["id"])
    for other in siblings:
        if other["id"] == test["id"]:
            continue
        if other["sequence_index"] < test["sequence_index"] and other["status"] != "SATISFIED":
            raise api_error("ERR_STARTUP_SEQUENCE_OUT_OF_ORDER",
                            "A lower-indexed startup test is not yet satisfied.")
    if regulatory and current_user_id() == test["created_by_user_id"]:
        raise api_error("ERR_SEGREGATION_OF_DUTIES",
                        "A REGULATORY hold point cannot be satisfied by its author.")

    deviation = calc.reactivity_deviation(payload["measured_reactivity_pcm"],
                                          test["predicted_reactivity_pcm"])
    test["measured_reactivity_pcm"] = calc.q2(payload["measured_reactivity_pcm"])
    test["reactivity_deviation_pcm"] = deviation

    if deviation <= calc.REACTIVITY_TOLERANCE_PCM:
        test["status"] = "SATISFIED"
        if payload["nrc_release_reference"] is not None:
            test["nrc_release_reference"] = payload["nrc_release_reference"]
        test["satisfied_by_user_id"] = current_user_id()
        touch(test)
        if all(t["status"] == "SATISFIED"
               for t in projections.startup_tests_of_outage(outage["id"])):
            outage["status"] = "ONLINE"
            touch(outage)
    else:
        test["status"] = "FAILED"
        touch(test)
        outage["schedule_posture"] = "RECOVERY_REQUIRED"
        touch(outage)
    return ok(serialize(test))
