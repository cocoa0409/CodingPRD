"""Packaging runs: sourcing, the fan-in join, yield and the emitted lot."""

from decimal import Decimal
from flask import Blueprint, g

from . import constants as C
from . import lookup
from .auth import authorize
from .calc import (
    abv_class_for,
    lot_best_by_date,
    lot_code,
    packaging_gross_liters,
    packaging_yield,
)
from .cascades import abort_packaging_run, batches_of_run
from .envelope import list_response, object_response
from .errors import ApiError
from .routes_recipes import require_id
from .store import base_record, collection_sorted, db, touch
from .util import dec, round2
from .validate import (
    body_dict,
    field,
    pagination,
    paginate,
    parse_body,
    query_enum,
    query_string,
)

bp = Blueprint("packaging", __name__)

READ_ROLES = ("ProductionOperator", "QaManager", "ComplianceOfficer", "PlatformAdmin")
RUN_STATUSES = (
    "DRAFT",
    "SOURCED",
    "IN_PROGRESS",
    "COMPLETED",
    "ABORTED",
    "RECALL_FLAGGED",
)


@bp.post("/packaging-runs")
def open_run():
    authorize("ProductionOperator", "PlatformAdmin")
    payload = body_dict()
    recipe = lookup.recipe(require_id(payload, "recipe_id"))
    approval = lookup.label_approval(require_id(payload, "label_approval_id"))
    data = parse_body(
        payload,
        [
            field("run_code", "string", required=True),
            field("recipe_id", "string", required=True),
            field("label_approval_id", "string", required=True),
            field("format", "enum", required=True, members=C.PACKAGING_FORMATS),
            field("pasteurized", "boolean", required=True),
            field("max_units_requested", "integer", required=True),
        ],
    )
    if approval["recipe_id"] != recipe["id"]:
        raise ApiError(
            "ERR_VALIDATION",
            "The label revision is drawn against a different recipe.",
        )
    if recipe["pasteurization_required"] and not data["pasteurized"]:
        raise ApiError(
            "ERR_LABEL_CLASS_MISMATCH",
            "The recipe requires every packaging run to be pasteurised.",
        )

    record = base_record()
    record.update(
        {
            "run_code": data["run_code"],
            "recipe_id": recipe["id"],
            "label_approval_id": approval["id"],
            "format": data["format"],
            "pasteurized": bool(data["pasteurized"]),
            "max_units_requested": int(data["max_units_requested"]),
            "source_draws": [],
            "source_batch_count": 0,
            "gross_liters": Decimal("0.00"),
            "net_liters": Decimal("0.00"),
            "units_produced": 0,
            "status": "DRAFT",
            "created_by_user_id": g.user_id,
            "started_by_user_id": None,
            "finished_lot_id": None,
        }
    )
    db.packaging_runs[record["id"]] = record
    return object_response(record, 201)


@bp.post("/packaging-runs/<id>/sources")
def add_source_draw(id):
    authorize("ProductionOperator", "PlatformAdmin")
    run = lookup.packaging_run(id)
    payload = body_dict()
    batch = lookup.batch(require_id(payload, "batch_id"))
    data = parse_body(
        payload,
        [
            field("batch_id", "string", required=True),
            field("liters_drawn", "number", required=True, positive=True),
            field("expected_batch_version", "integer", required=True),
        ],
    )

    if run["status"] not in ("DRAFT", "SOURCED"):
        raise ApiError(
            "ERR_INVALID_STATE", "Only a DRAFT or SOURCED run may take a draw."
        )
    if int(data["expected_batch_version"]) != int(batch["version"]):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_batch_version does not match the batch's current version.",
        )
    if batch["ferment_stage"] != "READY_TO_PACKAGE" or batch["qa_disposition"] == "NONCONFORMING":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a READY_TO_PACKAGE batch that is not NONCONFORMING may be drawn from.",
        )
    if batch["recipe_id"] != run["recipe_id"]:
        raise ApiError(
            "ERR_VALIDATION", "The batch belongs to a different recipe than the run."
        )
    liters = round2(data["liters_drawn"])
    if (
        int(run["source_batch_count"]) >= C.BLEND_MAX_SOURCE_BATCHES
        or liters < C.BLEND_MIN_DRAW_LITERS
    ):
        raise ApiError(
            "ERR_BLEND_RULE_VIOLATION",
            "A run holds at most %d draws and each draw is at or above %s liters."
            % (C.BLEND_MAX_SOURCE_BATCHES, C.BLEND_MIN_DRAW_LITERS),
        )
    if liters > dec(batch["remaining_liters"]):
        raise ApiError(
            "ERR_INSUFFICIENT_BATCH_VOLUME",
            "liters_drawn exceeds the batch's remaining_liters.",
        )

    run["source_draws"].append(
        {"batch_id": batch["id"], "liters_drawn": liters, "drawn_at": db.clock}
    )
    run["source_batch_count"] = len(run["source_draws"])
    run["gross_liters"] = packaging_gross_liters(run["source_draws"])
    run["status"] = "SOURCED"
    touch(run)

    batch["drawn_liters"] = round2(dec(batch["drawn_liters"]) + liters)
    batch["remaining_liters"] = round2(dec(batch["remaining_liters"]) - liters)
    touch(batch)

    return object_response(run)


@bp.post("/packaging-runs/<id>/start")
def start_run(id):
    authorize("ProductionOperator", "PlatformAdmin")
    run = lookup.packaging_run(id)
    body_dict()

    if run["status"] not in ("DRAFT", "SOURCED"):
        raise ApiError(
            "ERR_INVALID_STATE", "Only a DRAFT or SOURCED run may be started."
        )
    if int(run["source_batch_count"]) < 1:
        raise ApiError(
            "ERR_BLEND_RULE_VIOLATION", "A run with no source draws may not be started."
        )
    sources = batches_of_run(run)
    for batch in sources:
        if batch["ferment_stage"] != "READY_TO_PACKAGE":
            raise ApiError(
                "ERR_INVALID_STATE",
                "Every source batch must be READY_TO_PACKAGE.",
            )
    for batch in sources:
        if batch["qa_disposition"] != "CONFORMING":
            raise ApiError(
                "ERR_INVALID_STATE",
                "Every source batch must be CONFORMING (the fan-in join).",
            )

    approval = db.label_approvals.get(run["label_approval_id"])
    recipe = db.recipes.get(run["recipe_id"])
    if approval is None:
        raise ApiError("ERR_INVALID_STATE", "The run has no label revision.")
    if approval["status"] != "APPROVED":
        if approval["status"] == "STALE":
            raise ApiError("ERR_LABEL_STALE", "The label revision has gone stale.")
        raise ApiError(
            "ERR_INVALID_STATE", "The label revision has not been approved yet."
        )
    if int(approval["approved_recipe_version_number"] or 0) != int(
        recipe["recipe_version_number"]
    ):
        raise ApiError(
            "ERR_LABEL_STALE",
            "The label revision was approved against an older recipe revision.",
        )
    if bool(approval["pasteurized"]) != bool(run["pasteurized"]):
        raise ApiError(
            "ERR_LABEL_CLASS_MISMATCH",
            "The label's pasteurisation statement does not match the run.",
        )

    net_liters, units = packaging_yield(
        run["gross_liters"], run["format"], run["max_units_requested"]
    )
    run["net_liters"] = net_liters
    run["units_produced"] = units
    run["status"] = "IN_PROGRESS"
    run["started_by_user_id"] = g.user_id
    touch(run)
    return object_response(run)


@bp.post("/packaging-runs/<id>/complete")
def complete_run(id):
    authorize("ProductionOperator", "PlatformAdmin")
    run = lookup.packaging_run(id)
    body_dict()

    if run["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an IN_PROGRESS run may be completed."
        )
    sources = batches_of_run(run)
    for batch in sources:
        if batch.get("packaging_abv_pct") is None:
            raise ApiError(
                "ERR_VALIDATION",
                "Every source batch needs a PACKAGING QA reading before completion.",
            )

    measured = round2(max(dec(b["packaging_abv_pct"]) for b in sources))
    projections = [
        dec(b["projected_abv_pct"])
        for b in sources
        if b.get("projected_abv_pct") is not None
    ]
    if projections:
        if measured - max(projections) > C.ABV_DIVERGENCE_TOLERANCE_PCT:
            raise ApiError(
                "ERR_ABV_CLASS_DIVERGENCE",
                "The measured ABV has run away from the projection.",
            )

    approval = db.label_approvals.get(run["label_approval_id"])
    recipe = db.recipes.get(run["recipe_id"])
    measured_class = abv_class_for(measured)
    if approval is not None and measured_class != approval["abv_class"]:
        raise ApiError(
            "ERR_LABEL_CLASS_MISMATCH",
            "The measured abv_class does not match the approved label.",
        )

    packaged_at = db.clock
    container_liters = C.CONTAINER_LITERS_BY_FORMAT[run["format"]]
    ordered_sources = sorted(
        sources,
        key=lambda b: (
            min(
                d["drawn_at"]
                for d in run["source_draws"]
                if d["batch_id"] == b["id"]
            ),
            b["created_at"],
            b["_seq"],
        ),
    )
    lot = base_record()
    lot.update(
        {
            "lot_code": lot_code(recipe["style"], packaged_at, run["run_code"]),
            "packaging_run_id": run["id"],
            "recipe_id": run["recipe_id"],
            "format": run["format"],
            "pasteurized": bool(run["pasteurized"]),
            "container_liters": container_liters,
            "units_produced": int(run["units_produced"]),
            "on_hand_units": int(run["units_produced"]),
            "reserved_units": 0,
            "shipped_units": 0,
            "poured_units": 0,
            "destroyed_units": 0,
            "measured_abv_pct": measured,
            "abv_class": measured_class,
            "packaged_at": packaged_at,
            "best_by_date": lot_best_by_date(
                bool(run["pasteurized"]),
                int(run["source_batch_count"]),
                packaged_at,
                ordered_sources,
            ),
            "cold_chain_max_c": (
                C.COLD_CHAIN_MAX_C_PASTEURIZED
                if run["pasteurized"]
                else C.COLD_CHAIN_MAX_C_RAW
            ),
            "status": "HELD",
            "pre_quarantine_status": None,
            "quarantine_clearance_count": 0,
            "released_by_user_id": None,
            "released_at": None,
        }
    )
    db.finished_lots[lot["id"]] = lot

    run["status"] = "COMPLETED"
    run["finished_lot_id"] = lot["id"]
    touch(run)

    for batch in sources:
        if dec(batch["remaining_liters"]) == Decimal("0.00") and batch[
            "ferment_stage"
        ] == "READY_TO_PACKAGE":
            batch["ferment_stage"] = "PACKAGED"
            touch(batch)

    return object_response(run)


@bp.post("/packaging-runs/<id>/abort")
def abort_run(id):
    authorize("ProductionOperator", "PlatformAdmin")
    run = lookup.packaging_run(id)
    payload = body_dict()
    parse_body(payload, [field("reason", "string")])
    if run["status"] not in ("DRAFT", "SOURCED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "This run may no longer be aborted.")
    abort_packaging_run(run)
    return object_response(run)


@bp.get("/packaging-runs/<id>")
def read_run(id):
    authorize(*READ_ROLES)
    return object_response(lookup.packaging_run(id))


@bp.get("/packaging-runs")
def list_runs():
    authorize(*READ_ROLES)
    recipe_id = query_string("recipe_id")
    label_approval_id = query_string("label_approval_id")
    status = query_enum("status", RUN_STATUSES)
    source_batch_id = query_string("source_batch_id")
    limit, offset = pagination()

    def keep(run):
        if recipe_id is not None and run["recipe_id"] != recipe_id:
            return False
        if label_approval_id is not None and run["label_approval_id"] != label_approval_id:
            return False
        if status is not None and run["status"] != status:
            return False
        if source_batch_id is not None and not any(
            d["batch_id"] == source_batch_id for d in run["source_draws"]
        ):
            return False
        return True

    rows = collection_sorted(db.packaging_runs, keep)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)
