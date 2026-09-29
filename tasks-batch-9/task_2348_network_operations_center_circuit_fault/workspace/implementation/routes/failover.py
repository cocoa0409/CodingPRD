"""Failover verification tests (PRD 3.7)."""

from flask import Blueprint, g

import db
import derive
import lookup
from consts import LEG_GROUPS
from calc import intervals_overlap
from db import base_record, now, touch
from errors import fail
from middleware import authenticate
from routes._common import body_ref, send
from valid import body, opt_int, req_enum, req_ts

bp = Blueprint("failover", __name__)

LEAD_ROLES = ("NocShiftLead", "PlatformAdmin")
START_ROLES = ("NocAnalyst", "NocShiftLead", "PlatformAdmin")

OUTCOMES = ("PASSED", "FAILED", "ABORTED")
RESERVED_STATES = ("SCHEDULED", "IN_PROGRESS")


def _path_circuit_ids(path_id):
    ids = []
    for segment in derive.active_segments(path_id):
        circuit_id = segment.get("circuit_id")
        if circuit_id and circuit_id not in ids:
            ids.append(circuit_id)
    return ids


def _carrier_id_set(path_id):
    carriers = []
    for circuit_id in _path_circuit_ids(path_id):
        circuit = db.db.circuits.get(circuit_id)
        if circuit is None:
            continue
        if circuit["carrier_id"] not in carriers:
            carriers.append(circuit["carrier_id"])
    return carriers


@bp.post("/failover-tests")
def schedule_test():
    authenticate(LEAD_ROLES)
    payload = body()
    path = body_ref(payload, "application_path_id", lookup.path)
    if path is None:
        fail("ERR_INVALID_REQUEST", "application_path_id is required.")
    tested_leg_group = req_enum(payload, "tested_leg_group", LEG_GROUPS)
    scheduled_start = req_ts(payload, "scheduled_start")
    scheduled_end = req_ts(payload, "scheduled_end")

    if not scheduled_end > scheduled_start:
        fail("ERR_TIMESTAMP_RANGE_INVALID")

    segments = derive.active_segments(path["id"])
    if tested_leg_group not in derive.leg_groups_present(segments):
        fail("ERR_LEG_NOT_FOUND")

    carrier_id_set = _carrier_id_set(path["id"])

    for other in db.db.failover_tests.values():
        if other["state"] not in RESERVED_STATES:
            continue
        if not intervals_overlap(
            scheduled_start, scheduled_end, other["scheduled_start"], other["scheduled_end"]
        ):
            continue
        if set(other["carrier_id_set"]) & set(carrier_id_set):
            fail("ERR_FAILOVER_TEST_CONFLICT")

    test = base_record()
    test.update(
        {
            "application_path_id": path["id"],
            "tested_leg_group": tested_leg_group,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "carrier_id_set": carrier_id_set,
            "state": "SCHEDULED",
            "surviving_leg_count": None,
            "scheduled_by_user_id": g.user_id,
            "attested_by_user_id": None,
        }
    )
    db.db.failover_tests[test["id"]] = test
    return send(test, 201)


@bp.post("/failover-tests/<id>/start")
def start_test(id):
    authenticate(START_ROLES)
    test = lookup.failover_test(id)
    body()

    if test["state"] != "SCHEDULED":
        fail("ERR_TEST_STATE_INVALID")

    path = db.db.paths.get(test["application_path_id"])
    if path is None or path["posture"] != "PROTECTED":
        fail("ERR_PATH_NOT_PROTECTED")

    instant = now()
    circuit_ids = set(_path_circuit_ids(path["id"]))
    for window in db.db.windows.values():
        if window["circuit_id"] not in circuit_ids:
            continue
        if window["state"] not in ("APPROVED", "IN_PROGRESS"):
            continue
        if window["window_start"] <= instant < window["window_end"]:
            fail("ERR_MAINTENANCE_IN_EFFECT")

    if instant < test["scheduled_start"] or instant >= test["scheduled_end"]:
        fail("ERR_TEST_WINDOW_NOT_IN_EFFECT")

    test["state"] = "IN_PROGRESS"
    touch(test)
    derive.recompute_topology()
    touch(path)
    return send(test)


@bp.post("/failover-tests/<id>/record-result")
def record_result(id):
    authenticate(LEAD_ROLES)
    test = lookup.failover_test(id)
    payload = body()
    outcome = req_enum(payload, "outcome", OUTCOMES)
    surviving_leg_count = opt_int(payload, "surviving_leg_count", None, 0)

    if outcome == "ABORTED":
        if test["state"] not in RESERVED_STATES:
            fail("ERR_TEST_STATE_INVALID")
    elif test["state"] != "IN_PROGRESS":
        fail("ERR_TEST_STATE_INVALID")

    path = db.db.paths.get(test["application_path_id"])
    minimum = path["min_surviving_legs"] if path is not None else 1

    if outcome in ("PASSED", "FAILED"):
        if surviving_leg_count is None:
            fail("ERR_FAILOVER_RESULT_INCONSISTENT")
        if outcome == "PASSED" and surviving_leg_count < minimum:
            fail("ERR_FAILOVER_RESULT_INCONSISTENT")
        if outcome == "FAILED" and surviving_leg_count >= minimum:
            fail("ERR_FAILOVER_RESULT_INCONSISTENT")

    test["state"] = outcome
    test["attested_by_user_id"] = g.user_id
    test["surviving_leg_count"] = None if outcome == "ABORTED" else surviving_leg_count
    touch(test)

    derive.recompute_topology()

    if outcome == "FAILED" and path is not None:
        for segment in derive.active_segments(path["id"]):
            if segment["leg_group"] == test["tested_leg_group"]:
                continue
            circuit = db.db.circuits.get(segment.get("circuit_id"))
            if circuit is None:
                continue
            if not circuit["spof_flag"]:
                circuit["spof_flag"] = True
            touch(circuit)
    if path is not None:
        touch(path)
    return send(test)
