"""/in-process-checks and /em-samples - in-process controls and excursions."""

from flask import Blueprint, request

import calc
import serialize
import services
from auth import endpoint
from common import ApiError
from listing import list_response, object_response
from store import DB, by_created, deviations_of_sample, new_row, touch
from validate import (
    CHECK_TYPES,
    SAMPLE_TYPES,
    f_array,
    f_enum,
    f_int,
    f_str,
    parse_body,
)

bp = Blueprint("quality", __name__)

IPC_FIELDS = [
    f_str("batch_order_id", 1, None),
    f_enum("check_type", CHECK_TYPES),
    f_int("sample_size", 1),
    f_int("reject_unit_count", 0, required=False, default=0),
    f_int("destructive_sample_units", 0, required=False, default=0),
    f_array("measured_fill_weights_mg", item="num", required=False),
]


@bp.post("/in-process-checks")
@endpoint(["ProductionSupervisor", "QaReviewer"])
def create_in_process_check():
    body = parse_body(request.get_json(silent=True), IPC_FIELDS)
    batch = services.require("batch", body["batch_order_id"])
    check_type = body["check_type"]
    weights = body["measured_fill_weights_mg"] or []
    if check_type == "FILL_WEIGHT" and len(weights) == 0:
        raise ApiError(
            "ERR_IPC_PAYLOAD_INCONSISTENT",
            422,
            "measured_fill_weights_mg is required and non-empty for FILL_WEIGHT.",
        )
    if check_type != "FILL_WEIGHT" and len(weights) > 0:
        raise ApiError(
            "ERR_IPC_PAYLOAD_INCONSISTENT",
            422,
            "measured_fill_weights_mg must be empty for %s." % check_type,
        )
    if body["reject_unit_count"] > body["sample_size"]:
        raise ApiError(
            "ERR_IPC_PAYLOAD_INCONSISTENT",
            422,
            "reject_unit_count must be at most sample_size.",
        )
    project = DB.projects.get(batch["client_project_id"])
    target = project["target_fill_weight_mg"] if project else 1
    result, pct = calc.in_process_check_result(
        check_type, body["sample_size"], body["reject_unit_count"], weights, target
    )
    row = new_row(
        {
            "batch_order_id": batch["id"],
            "check_type": check_type,
            "sample_size": body["sample_size"],
            "reject_unit_count": body["reject_unit_count"],
            "destructive_sample_units": body["destructive_sample_units"],
            "measured_fill_weights_mg": list(weights),
            "result": result,
            "max_absolute_deviation_pct": pct,
        }
    )
    DB.ipcs[row["id"]] = row
    return object_response(serialize.ipc_out(row), 201)


@bp.get("/in-process-checks/<check_id>")
@endpoint(
    ["ProductionSupervisor", "QaReviewer", "QualifiedPerson", "ProgramManager"]
)
def read_in_process_check(check_id):
    row = services.require("ipc", check_id)
    return object_response(serialize.ipc_out(row))


@bp.get("/in-process-checks")
@endpoint(
    ["ProductionSupervisor", "QaReviewer", "QualifiedPerson", "ProgramManager"]
)
def list_in_process_checks():
    rows = by_created(list(DB.ipcs.values()))
    return list_response(
        rows,
        serialize.ipc_out,
        {
            "batch_order_id": "batch_order_id",
            "check_type": "check_type",
            "result": "result",
        },
    )


# --------------------------------------------------------------------------
# Environmental monitoring
# --------------------------------------------------------------------------

EM_FIELDS = [
    f_str("suite_id", 1, None),
    f_enum("sample_type", SAMPLE_TYPES),
    f_int("cfu_count", 0),
    f_str("batch_order_id", 1, None, required=False),
]


@bp.post("/em-samples")
@endpoint(["MicrobiologyAnalyst"])
def create_em_sample():
    body = parse_body(request.get_json(silent=True), EM_FIELDS)
    suite = services.require("suite", body["suite_id"])
    batch = None
    if body["batch_order_id"] is not None:
        batch = services.require("batch", body["batch_order_id"])
        if batch["suite_id"] != suite["id"]:
            raise services.state_conflict(
                "ERR_EM_SAMPLE_SUITE_MISMATCH",
                "The named batch does not run in this suite.",
            )
    alert_limit, action_limit = calc.em_limits(suite["grade"], body["sample_type"])
    classification = calc.em_classification(body["cfu_count"], alert_limit, action_limit)
    batch_exposed = batch is not None and batch["production_status"] == "FILLING"
    risk_index = calc.em_risk_index(
        classification,
        body["cfu_count"],
        action_limit,
        suite["grade"],
        body["sample_type"],
        batch_exposed,
    )
    row = new_row(
        {
            "suite_id": suite["id"],
            "batch_order_id": batch["id"] if batch else None,
            "sample_type": body["sample_type"],
            "cfu_count": body["cfu_count"],
            "alert_limit": alert_limit,
            "action_limit": action_limit,
            "classification": classification,
            "risk_index": risk_index,
            "investigation_status": (
                "NOT_REQUIRED" if classification == "WITHIN_LIMIT" else "OPEN"
            ),
            "root_cause": None,
        }
    )
    DB.em_samples[row["id"]] = row
    if classification == "ACTION":
        touch(suite)  # the excursion count moved, so the suite row moved
        services.demote_qp_review_batches(suite)
    return object_response(serialize.em_sample_out(row), 201)


@bp.get("/em-samples/<sample_id>")
@endpoint(
    ["MicrobiologyAnalyst", "QaReviewer", "QualifiedPerson", "ProductionSupervisor"]
)
def read_em_sample(sample_id):
    row = services.require("em_sample", sample_id)
    return object_response(serialize.em_sample_out(row))


@bp.get("/em-samples")
@endpoint(
    ["MicrobiologyAnalyst", "QaReviewer", "QualifiedPerson", "ProductionSupervisor"]
)
def list_em_samples():
    rows = by_created(list(DB.em_samples.values()))
    return list_response(
        rows,
        serialize.em_sample_out,
        {
            "suite_id": "suite_id",
            "batch_order_id": "batch_order_id",
            "classification": "classification",
            "investigation_status": "investigation_status",
            "sample_type": "sample_type",
        },
    )


@bp.post("/em-samples/<sample_id>/investigate")
@endpoint(["MicrobiologyAnalyst"])
def investigate_em_sample(sample_id):
    sample = services.require("em_sample", sample_id)
    parse_body(request.get_json(silent=True), [f_str("investigator_note", 1, None)])
    if sample["investigation_status"] != "OPEN":
        raise services.state_conflict(
            "ERR_EXCURSION_STATE_INVALID",
            "Only an OPEN excursion can be moved to INVESTIGATING.",
        )
    sample["investigation_status"] = "INVESTIGATING"
    touch(sample)
    return object_response(serialize.em_sample_out(sample))


@bp.post("/em-samples/<sample_id>/close-investigation")
@endpoint(["MicrobiologyAnalyst"])
def close_em_investigation(sample_id):
    sample = services.require("em_sample", sample_id)
    body = parse_body(request.get_json(silent=True), [f_str("root_cause", 1, None)])
    if sample["investigation_status"] != "INVESTIGATING":
        raise services.state_conflict(
            "ERR_EXCURSION_STATE_INVALID",
            "Only an INVESTIGATING excursion can be closed.",
        )
    if sample["classification"] == "ACTION":
        for dev in deviations_of_sample(sample["id"]):
            if dev["status"] != "CLOSED":
                raise services.state_conflict(
                    "ERR_DEVIATION_STATE_INVALID",
                    "Every deviation linked to this excursion must be CLOSED first.",
                )
    sample["investigation_status"] = "CLOSED"
    sample["root_cause"] = body["root_cause"]
    touch(sample)
    suite = DB.suites.get(sample["suite_id"])
    if suite is not None:
        touch(suite)  # the excursion count moved, so the posture may have too
    return object_response(serialize.em_sample_out(sample))
