"""Sterilization-record routes — PRD §3.5."""

from flask import Blueprint

import config
import domain
import serialize
import store
import validate as V
from auth import authenticate, require_owns_establishment
from envelope import array_response, force, send
from errors import ApiError

bp = Blueprint("sterilization", __name__)

READ_ROLES = ["HealthOfficer", "Inspector", "RecordsClerk", "EstablishmentOperator"]


@bp.post("/body-art/sterilization-records")
def create_sterilization_record():
    caller = authenticate(["EstablishmentOperator"])
    data = V.body()
    establishment_id = V.req_id(data, "establishment_id")
    device_serial = V.req_string(data, "device_serial", 1, 40)
    cycle_completed_at = V.req_datetime(data, "cycle_completed_at")
    spore_test_result = V.req_enum(data, "spore_test_result", config.SPORE_TEST_RESULTS)
    supersedes_record_id = V.opt_id(data, "supersedes_record_id")

    est = V.get_establishment(establishment_id)
    superseded = None
    if supersedes_record_id is not None:
        superseded = V.get_sterilization_record(supersedes_record_id)
    require_owns_establishment(caller, establishment_id)

    if superseded is not None:
        if superseded["establishment_id"] != est["id"]:
            raise ApiError("ERR_STERILIZATION_SUPERSEDE_INVALID")
        already = any(
            r.get("supersedes_record_id") == superseded["id"]
            for r in store.sterilization_records.values()
        )
        if already:
            raise ApiError("ERR_STERILIZATION_SUPERSEDE_INVALID")

    if cycle_completed_at > store.now():
        raise ApiError("ERR_CYCLE_TIMESTAMP_FUTURE")

    rec = domain.new_record(
        {
            "establishment_id": est["id"],
            "device_serial": device_serial,
            "cycle_completed_at": cycle_completed_at,
            "spore_test_result": spore_test_result,
            "supersedes_record_id": supersedes_record_id,
            "recorded_by_user_id": caller.user_id,
        },
        versioned=False,
    )
    store.sterilization_records[rec["id"]] = rec

    force(est)
    domain.recompute_risk_and_posture(est)
    return send(lambda: serialize.sterilization_record(rec), 201)


@bp.get("/body-art/sterilization-records/<sterilization_record_id>")
def read_sterilization_record(sterilization_record_id):
    authenticate(READ_ROLES)
    rec = V.get_sterilization_record(sterilization_record_id)
    return send(lambda: serialize.sterilization_record(rec), 200)


@bp.get("/body-art/sterilization-records")
def list_sterilization_records():
    authenticate(READ_ROLES)
    limit, offset = V.pagination()
    establishment_id = V.filter_string("establishment_id")
    supersedes_record_id = V.filter_string("supersedes_record_id")
    spore_test_result = V.filter_enum("spore_test_result", config.SPORE_TEST_RESULTS)

    rows = store.sorted_rows(store.sterilization_records)
    if establishment_id is not None:
        rows = [r for r in rows if r["establishment_id"] == establishment_id]
    if supersedes_record_id is not None:
        rows = [r for r in rows if r["supersedes_record_id"] == supersedes_record_id]
    if spore_test_result is not None:
        rows = [r for r in rows if r["spore_test_result"] == spore_test_result]
    page, total = V.paginate(rows, limit, offset)
    return array_response(
        [serialize.sterilization_record(r) for r in page], limit, offset, total
    )
