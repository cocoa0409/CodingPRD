from datetime import timedelta

from flask import Blueprint, request

from db import store
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    f_id,
    f_enum,
    f_dt,
    ok,
    paginate,
    invalid,
)
from errors import ApiError
from services import (
    get_worker,
    get_incident,
    get_drugtest,
    new_entity,
    ser_drugtest,
    bump,
    cascade_positive_drug_test,
    POST_INCIDENT_WINDOW_HOURS,
)

bp = Blueprint("drugtests", __name__)

TEST_TYPES = {"PRE_EMPLOYMENT", "RANDOM", "POST_INCIDENT"}


@bp.route("/safety/drug-tests", methods=["POST"])
def create_drugtest():
    require_roles("SafetyManager")
    b = body()
    # priority 3: FK existence + same-project rule
    raw_wid = b.get("worker_id")
    worker = get_worker(raw_wid) if isinstance(raw_wid, str) else None
    raw_iid = b.get("incident_id")
    incident = None
    if isinstance(raw_iid, str):
        incident = get_incident(raw_iid)
        if worker is not None and incident["project_id"] != worker["project_id"]:
            raise ApiError("ERR_INCIDENT_NOT_FOUND", 404, "No Incident with the given id")
    # priority 4: shape + conditional rules
    reject_unknown(b, {"worker_id", "test_type", "incident_id", "collected_at"})
    worker_id = f_str(b, "worker_id")
    if worker is None:
        worker = get_worker(worker_id)
    test_type = f_enum(b, "test_type", TEST_TYPES)
    incident_id = f_id(b, "incident_id")
    if test_type == "POST_INCIDENT" and incident_id is None:
        invalid("incident_id is required when test_type is POST_INCIDENT")
    if test_type != "POST_INCIDENT" and incident_id is not None:
        invalid("incident_id must be null when test_type is not POST_INCIDENT")
    collected_at = f_dt(b, "collected_at")
    if incident_id is not None and incident is None:
        incident = get_incident(incident_id)
        if incident["project_id"] != worker["project_id"]:
            raise ApiError("ERR_INCIDENT_NOT_FOUND", 404, "No Incident with the given id")
    # priority 4 (conditional): POST_INCIDENT worker must match incident worker
    if (
        test_type == "POST_INCIDENT"
        and incident["worker_id"] is not None
        and worker_id != incident["worker_id"]
    ):
        invalid("POST_INCIDENT worker_id must equal the linked Incident.worker_id")
    # priority 8 (c): 32-hour collection window, both bounds inclusive
    window_compliant = None
    if test_type == "POST_INCIDENT":
        window_open = incident["occurred_at"]
        window_close = window_open + timedelta(hours=POST_INCIDENT_WINDOW_HOURS)
        if not (window_open <= collected_at <= window_close):
            raise ApiError(
                "ERR_DRUG_TEST_WINDOW_VIOLATION",
                422,
                "POST_INCIDENT collected_at outside [occurred_at, occurred_at + 32h]",
            )
        window_compliant = True
    d = new_entity()
    d.update(
        {
            "worker_id": worker_id,
            "test_type": test_type,
            "incident_id": incident_id,
            "collected_at": collected_at,
            "status": "PENDING_RESULT",
            "window_compliant": window_compliant,
        }
    )
    store.drugtests[d["id"]] = d
    return ok(ser_drugtest(d), 201)


@bp.route("/safety/drug-tests", methods=["GET"])
def list_drugtests():
    require_roles("SafetyManager", "ComplianceAuditor")
    records = list(store.drugtests.values())
    wid = request.args.get("worker_id")
    if wid is not None:
        records = [d for d in records if d["worker_id"] == wid]
    iid = request.args.get("incident_id")
    if iid is not None:
        records = [d for d in records if d["incident_id"] == iid]
    tt = request.args.get("test_type")
    if tt is not None:
        records = [d for d in records if d["test_type"] == tt]
    return paginate(records, ser_drugtest)


@bp.route("/safety/drug-tests/<drugTestId>", methods=["GET"])
def get_one_drugtest(drugTestId):
    require_roles("SafetyManager", "ComplianceAuditor")
    return ok(ser_drugtest(get_drugtest(drugTestId)))


@bp.route("/safety/drug-tests/<drugTestId>/record-result", methods=["POST"])
def record_result(drugTestId):
    require_roles("SafetyManager")
    record = get_drugtest(drugTestId)
    b = body()
    reject_unknown(b, {"result"})
    result = f_enum(b, "result", {"NEGATIVE", "POSITIVE"})
    if record["status"] != "PENDING_RESULT":
        raise ApiError(
            "ERR_DRUG_TEST_INVALID_STATE",
            409,
            "record-result requires status PENDING_RESULT",
        )
    record["status"] = result
    bump(record)
    if result == "POSITIVE":
        worker = store.workers.get(record["worker_id"])
        if worker is not None:
            cascade_positive_drug_test(worker)
    return ok(ser_drugtest(record))
