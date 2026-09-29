"""/batch-orders - scheduling, the production axis and QP certification.

A BatchOrder carries two independent state axes on one row: `production_status`
travels SCHEDULED -> SETUP -> FILLING -> FILLED (with SUSPENDED and CANCELLED
off to the side) while `quality_status` travels PENDING -> IN_PROCESS_REVIEW ->
BR_REVIEW -> QP_REVIEW -> RELEASED/REJECTED. Neither is a function of the
other; the single coupling is that starting the fill also moves the quality
axis PENDING -> IN_PROCESS_REVIEW.
"""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serialize
import services
from auth import acting_user, endpoint
from common import ApiError, clock_now, minutes_between
from listing import list_response, object_response
from store import (
    DB,
    LIVE_PRODUCTION,
    batches_of_project,
    by_created,
    decisions_of_batch,
    live_batches_of_suite,
    new_row,
    review_of_batch,
    set_raw,
    touch,
)
from validate import (
    QP_DECISIONS,
    bad_request,
    f_dt,
    f_enum,
    f_int,
    f_str,
    parse_body,
)

bp = Blueprint("batches", __name__)

BATCH_FIELDS = [
    f_str("client_project_id", 1, None),
    f_str("suite_id", 1, None),
    f_str("lead_operator_qualification_id", 1, None),
    f_str("batch_number", 1, 30),
    f_dt("planned_start"),
    f_dt("planned_end"),
    f_int("target_fill_units", 1),
    f_int("expected_suite_version"),
]


def _molecule_of_batch(batch):
    project = DB.projects.get(batch["client_project_id"])
    return project["molecule_name"] if project else None


def _operator_of_batch(batch):
    qual = DB.quals.get(batch["lead_operator_qualification_id"])
    return qual["operator_name"] if qual else None


@bp.post("/batch-orders")
@endpoint(["ProgramManager"])
def create_batch():
    body = parse_body(request.get_json(silent=True), BATCH_FIELDS)
    project = services.require("project", body["client_project_id"])
    suite = services.require("suite", body["suite_id"])
    qual = services.require("qualification", body["lead_operator_qualification_id"])

    if body["expected_suite_version"] != suite["version"]:
        raise ApiError(
            "ERR_STALE_SUITE_VERSION",
            412,
            "expected_suite_version does not match the suite's current version.",
        )

    if project["status"] != "ACTIVE":
        raise services.state_conflict(
            "ERR_PROJECT_STATE_INVALID", "Only an ACTIVE project may schedule batches."
        )

    planned_start = body["planned_start"]
    planned_end = body["planned_end"]

    if suite["media_fill_valid_until"] is None \
            or suite["media_fill_valid_until"] < planned_end:
        raise services.state_conflict(
            "ERR_MEDIA_FILL_QUALIFICATION_EXPIRED",
            "The suite's aseptic qualification does not cover the whole window.",
        )

    if (
        qual["qualification_type"] != "ASEPTIC_INTERVENTION"
        or qual["suite_id"] != suite["id"]
        or qual["status"] != "QUALIFIED"
        or qual["expires_on"] is None
        or qual["expires_on"] < clock_now()
    ):
        raise services.state_conflict(
            "ERR_OPERATOR_NOT_QUALIFIED",
            "The nominated lead operator is not effective for this suite.",
        )

    if planned_end <= planned_start:
        raise ApiError(
            "ERR_INVALID_WINDOW",
            422,
            "planned_end must be strictly after planned_start.",
        )

    molecule = project["molecule_name"]
    for other in live_batches_of_suite(suite["id"]):
        buffer_minutes = calc.applicable_buffer(
            suite, molecule, _molecule_of_batch(other)
        )
        buffer_delta = timedelta(minutes=buffer_minutes)
        if planned_start < other["planned_end"] + buffer_delta \
                and other["planned_start"] < planned_end + buffer_delta:
            raise services.state_conflict(
                "ERR_SUITE_CHANGEOVER_CONFLICT",
                "The window collides with a live batch once the changeover buffer "
                "is applied.",
            )

    operator_name = qual["operator_name"]
    for other in by_created(list(DB.batches.values())):
        if other["production_status"] not in LIVE_PRODUCTION:
            continue
        if _operator_of_batch(other) != operator_name:
            continue
        if planned_start <= other["planned_end"] and other["planned_start"] <= planned_end:
            raise services.state_conflict(
                "ERR_OPERATOR_DOUBLE_BOOKED",
                "That lead operator already leads a live batch across this window.",
            )

    for other in batches_of_project(project["id"]):
        if other["production_status"] == "CANCELLED":
            continue
        if other["batch_number"] == body["batch_number"]:
            raise services.state_conflict(
                "ERR_DUPLICATE_BATCH_NUMBER",
                "That batch_number is already used by a live batch of this project.",
            )

    changeover = calc.changeover_minutes_applied(suite, molecule, planned_start)
    demand = calc.component_demand_units(
        project["dosage_form"], body["target_fill_units"]
    )

    if calc.committed_demand_units(project["id"]) + demand > project["reserved_unit_budget"]:
        raise ApiError(
            "ERR_PROJECT_UNIT_BUDGET_EXCEEDED",
            402,
            "The project's reserved unit budget cannot absorb this batch.",
        )

    window = minutes_between(planned_start, planned_end)
    if calc.suite_committed_minutes(suite["id"]) + window + changeover \
            > suite["max_committed_minutes"]:
        raise ApiError(
            "ERR_SUITE_CAPACITY_EXCEEDED",
            402,
            "The suite's committed-minutes ceiling cannot absorb this batch.",
        )

    row = new_row(
        {
            "client_project_id": project["id"],
            "suite_id": suite["id"],
            "lead_operator_qualification_id": qual["id"],
            "batch_number": body["batch_number"],
            "planned_start": planned_start,
            "planned_end": planned_end,
            "target_fill_units": body["target_fill_units"],
            "component_demand_units": demand,
            "changeover_minutes_applied": changeover,
            "filled_unit_count": None,
            "quarantined_unit_count": 0,
            "production_status": "SCHEDULED",
            "quality_status": "PENDING",
            "provisional_releasable_units": None,
            "final_releasable_units": None,
            "release_fee_cents": None,
        }
    )
    set_raw(row, "planned_start", body["_raw_planned_start"])
    set_raw(row, "planned_end", body["_raw_planned_end"])
    DB.batches[row["id"]] = row
    touch(suite)  # the OCC token moves, so the next scheduler must re-read
    return object_response(serialize.batch_out(row), 201)


@bp.get("/batch-orders/<batch_id>")
@endpoint(
    [
        "ProgramManager",
        "ProductionSupervisor",
        "QaReviewer",
        "QualifiedPerson",
        "MicrobiologyAnalyst",
        "ClientRepresentative",
    ],
    crep_scope="batch_path",
)
def read_batch(batch_id):
    row = services.require("batch", batch_id)
    return object_response(serialize.batch_out(row))


@bp.get("/batch-orders")
@endpoint(
    [
        "ProgramManager",
        "ProductionSupervisor",
        "QaReviewer",
        "QualifiedPerson",
        "MicrobiologyAnalyst",
    ]
)
def list_batches():
    rows = by_created(list(DB.batches.values()))
    return list_response(
        rows,
        serialize.batch_out,
        {
            "client_project_id": "client_project_id",
            "suite_id": "suite_id",
            "lead_operator_qualification_id": "lead_operator_qualification_id",
            "production_status": "production_status",
            "quality_status": "quality_status",
        },
    )


@bp.get("/batch-orders/<batch_id>/unit-accounting")
@endpoint(
    ["ProgramManager", "QaReviewer", "QualifiedPerson", "ClientRepresentative"],
    crep_scope="batch_path",
)
def unit_accounting(batch_id):
    batch = services.require("batch", batch_id)
    project = DB.projects.get(batch["client_project_id"])
    filled = batch["filled_unit_count"] or 0
    expected = calc.expected_reject_units(
        filled, project["historical_reject_rate_ppm"] if project else 0
    )
    provisional = batch["provisional_releasable_units"]
    final = batch["final_releasable_units"]
    data = {
        "batch_order_id": batch["id"],
        "filled_unit_count": filled,
        "expected_reject_units": expected,
        "actual_visual_reject_units": calc.actual_visual_reject_units(batch["id"]),
        "destructive_total_units": calc.destructive_total_units(batch["id"]),
        "quarantined_unit_count": batch["quarantined_unit_count"] or 0,
        "provisional_releasable_units": provisional or 0,
        "final_releasable_units": final or 0,
        "variant_delta_units": (provisional or 0) - (final or 0),
    }
    return object_response(data)


@bp.get("/batch-orders/<batch_id>/qp-release-decisions")
@endpoint(["QaReviewer", "QualifiedPerson", "ProgramManager"])
def list_qp_decisions(batch_id):
    services.require("batch", batch_id)
    rows = decisions_of_batch(batch_id)
    return list_response(rows, serialize.qp_decision_out)


# --------------------------------------------------------------------------
# Production axis transitions
# --------------------------------------------------------------------------


@bp.post("/batch-orders/<batch_id>/setup")
@endpoint(["ProductionSupervisor"])
def setup_batch(batch_id):
    batch = services.require("batch", batch_id)
    parse_body(request.get_json(silent=True), [])
    if batch["production_status"] != "SCHEDULED":
        raise services.state_conflict(
            "ERR_BATCH_PRODUCTION_STATE_INVALID",
            "Only a SCHEDULED batch can enter setup.",
        )
    project = DB.projects.get(batch["client_project_id"])
    if project is None or project["status"] != "ACTIVE":
        raise services.state_conflict(
            "ERR_PROJECT_STATE_INVALID", "The owning project is not ACTIVE."
        )
    suite = DB.suites.get(batch["suite_id"])
    if suite is not None and calc.suite_posture(suite) == "FROZEN":
        # Setup tolerates RESTRICTED; only a hard freeze blocks it.
        raise services.state_conflict(
            "ERR_SUITE_NOT_OPEN", "The suite is FROZEN."
        )
    batch["production_status"] = "SETUP"
    touch(batch)
    return object_response(serialize.batch_out(batch))


@bp.post("/batch-orders/<batch_id>/start-fill")
@endpoint(["ProductionSupervisor"])
def start_fill(batch_id):
    batch = services.require("batch", batch_id)
    parse_body(request.get_json(silent=True), [])
    if batch["production_status"] != "SETUP":
        raise services.state_conflict(
            "ERR_BATCH_PRODUCTION_STATE_INVALID",
            "Only a batch in SETUP can start filling.",
        )
    suite = DB.suites.get(batch["suite_id"])
    project = DB.projects.get(batch["client_project_id"])
    if suite is None or suite["media_fill_valid_until"] is None \
            or suite["media_fill_valid_until"] < clock_now():
        raise services.state_conflict(
            "ERR_MEDIA_FILL_QUALIFICATION_EXPIRED",
            "The suite's aseptic process simulation is no longer valid.",
        )
    if calc.suite_posture(suite) != "OPEN":
        raise services.state_conflict(
            "ERR_SUITE_NOT_OPEN",
            "Starting an aseptic fill requires a suite posture of exactly OPEN.",
        )
    if suite["cleaning_validation_status"] != "VALIDATED" \
            or project is None \
            or suite["last_cleaned_molecule"] != project["molecule_name"]:
        raise services.state_conflict(
            "ERR_CLEANING_VALIDATION_REQUIRED",
            "The suite was not cleaned down for this molecule.",
        )
    qual = DB.quals.get(batch["lead_operator_qualification_id"])
    if qual is None or qual["status"] != "QUALIFIED" or qual["expires_on"] is None \
            or qual["expires_on"] < clock_now():
        raise services.state_conflict(
            "ERR_OPERATOR_NOT_QUALIFIED",
            "The lead operator's qualification is no longer effective.",
        )
    if services.reserved_unit_total(batch["id"]) < batch["component_demand_units"]:
        raise services.state_conflict(
            "ERR_COMPONENTS_NOT_RESERVED",
            "The batch's reserved components do not cover its component demand.",
        )
    batch["production_status"] = "FILLING"
    if batch["quality_status"] == "PENDING":
        batch["quality_status"] = "IN_PROCESS_REVIEW"
    touch(batch)
    return object_response(serialize.batch_out(batch))


@bp.post("/batch-orders/<batch_id>/complete-fill")
@endpoint(["ProductionSupervisor"])
def complete_fill(batch_id):
    batch = services.require("batch", batch_id)
    body = parse_body(
        request.get_json(silent=True), [f_int("filled_unit_count", 1)]
    )
    if body["filled_unit_count"] > batch["target_fill_units"]:
        raise bad_request("filled_unit_count must not exceed target_fill_units.")
    if batch["production_status"] != "FILLING":
        raise services.state_conflict(
            "ERR_BATCH_PRODUCTION_STATE_INVALID",
            "Only a FILLING batch can be closed out.",
        )
    project = DB.projects.get(batch["client_project_id"])
    batch["production_status"] = "FILLED"
    batch["filled_unit_count"] = body["filled_unit_count"]
    batch["provisional_releasable_units"] = calc.provisional_releasable_units(
        batch, project
    )
    touch(batch)
    services.consume_reservations(batch)
    return object_response(serialize.batch_out(batch))


@bp.post("/batch-orders/<batch_id>/cancel")
@endpoint(["ProgramManager"])
def cancel_batch(batch_id):
    batch = services.require("batch", batch_id)
    parse_body(request.get_json(silent=True), [f_str("cancellation_reason", 1, None)])
    if batch["production_status"] not in ("SCHEDULED", "SETUP", "SUSPENDED"):
        raise services.state_conflict(
            "ERR_BATCH_PRODUCTION_STATE_INVALID",
            "A batch that is FILLING, FILLED or already CANCELLED cannot be cancelled.",
        )
    batch["production_status"] = "CANCELLED"
    if batch["quality_status"] not in ("RELEASED", "REJECTED"):
        batch["quality_status"] = "REJECTED"
    touch(batch)
    services.release_reservations(batch, "BATCH_CANCELLED")
    return object_response(serialize.batch_out(batch))


# --------------------------------------------------------------------------
# Qualified-Person certification
# --------------------------------------------------------------------------


@bp.post("/batch-orders/<batch_id>/qp-release")
@endpoint(["QualifiedPerson"])
def qp_release(batch_id):
    batch = services.require("batch", batch_id)
    body = parse_body(
        request.get_json(silent=True),
        [f_enum("decision", QP_DECISIONS), f_str("rationale", 1, 300)],
    )
    review = review_of_batch(batch["id"])
    if review is None or review["status"] != "CLOSED" or review["open_findings_count"] != 0:
        raise services.state_conflict(
            "ERR_BR_REVIEW_NOT_CLOSED",
            "The batch record review is not closed with zero findings.",
        )
    if body["decision"] == "RELEASE" and batch["production_status"] != "FILLED":
        raise services.state_conflict(
            "ERR_BATCH_PRODUCTION_STATE_INVALID",
            "A release can only be signed against a FILLED batch.",
        )
    if batch["quality_status"] != "QP_REVIEW":
        raise services.state_conflict(
            "ERR_BATCH_QUALITY_STATE_INVALID",
            "Certification requires a quality_status of QP_REVIEW.",
        )
    for dev in services.deviations_of_batch(batch["id"]):
        if dev["classification"] == "CRITICAL" and dev["status"] != "CLOSED":
            raise services.state_conflict(
                "ERR_OPEN_CRITICAL_DEVIATION",
                "An open CRITICAL deviation blocks certification.",
            )
    if acting_user() == review["reviewer_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The signing user must differ from the batch record reviewer.",
        )

    decision = body["decision"]
    released_units = 0
    fee = 0
    if decision == "RELEASE":
        final_units = batch["final_releasable_units"] or 0
        fee = calc.qp_release_fee_cents(
            final_units, calc.max_open_deviation_class(batch["id"])
        )
        batch["quality_status"] = "RELEASED"
        batch["release_fee_cents"] = fee
        released_units = final_units
    elif decision == "REJECT":
        batch["quality_status"] = "REJECTED"
    else:
        batch["quality_status"] = "QUARANTINED"
    touch(batch)

    row = new_row(
        {
            "batch_order_id": batch["id"],
            "qp_user_id": acting_user(),
            "decision": decision,
            "rationale": body["rationale"],
            "released_unit_count": released_units,
            "fee_cents": fee,
        },
        versioned=False,
    )
    DB.qp_decisions[row["id"]] = row
    return object_response(serialize.qp_decision_out(row), 201)
