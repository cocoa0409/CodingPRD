"""Production lots: reservation, production, QA hold, release/rework, cancel."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import store, new_resource, touch, by_creation, logical_date
from errors import ApiError, err_invalid_state
from middleware import auth, ALL_ROLES
from response import ok_object, ok_list
from services import (
    as_datetime,
    as_int,
    create_lab_test,
    get_body,
    get_or_404,
    line_free_units,
    lot_json,
    raise_shape,
)

bp = Blueprint("lots", __name__)

PL = ["ProductionLead"]


@bp.post("/api/bottling-lines/<line_id>/production-lots")
@auth(PL)
def create_lot(line_id):
    # Rung 3 — existence: path line, then body FK treatment_run_id.
    line = get_or_404(store.lines, line_id, "bottling line")
    body = get_body()
    run_id = body.get("treatment_run_id")
    run = None
    if isinstance(run_id, str):
        run = store.treatment_runs.get(run_id)
    if run_id is not None and run is None:
        raise ApiError("ERR_NOT_FOUND", "treatment_run_id does not reference an existing treatment run", 404)

    # Rung 4 — OCC on the line.
    expected, ok_exp = as_int(body.get("expected_line_version"))
    if ok_exp and expected != line["version"]:
        raise ApiError(
            "ERR_STALE_LINE_VERSION",
            "expected_line_version does not match the line's current version",
            412,
        )

    # Parse fields.
    label = body.get("label_classification")
    planned, ok_planned = as_int(body.get("planned_units"))
    start, ok_s = as_datetime(body.get("scheduled_start"))
    end, ok_e = as_datetime(body.get("scheduled_end"))

    # Rung 6 — label eligibility against the run's source classification.
    if run is not None and label in ("SPRING", "PURIFIED"):
        permit = store.permits.get(run["source_permit_id"])
        src_class = permit["source_classification"] if permit else None
        if (label == "SPRING") != (src_class == "SPRING"):
            raise ApiError(
                "ERR_LABEL_CLASSIFICATION_MISMATCH",
                "a SPRING label requires a spring source; a PURIFIED label requires a non-spring source",
                409,
            )

    # Rung 7 — half-open line window overlap against non-CANCELLED lots.
    if ok_s and ok_e:
        for other in store.lots.values():
            if other["line_id"] != line["id"] or other["status"] == "CANCELLED":
                continue
            if start < other["_end"] and other["_start"] < end:
                raise ApiError(
                    "ERR_LINE_WINDOW_CONFLICT",
                    "the lot's window overlaps another lot on this line",
                    409,
                )

    # Rung 8 — cross-plant, then run assignment.
    if run is not None and run["plant_id"] != line["plant_id"]:
        raise ApiError(
            "ERR_CROSS_PLANT_REFERENCE",
            "the treatment run belongs to a different plant than the line",
            409,
        )
    if run is not None:
        for other in store.lots.values():
            if (
                other["treatment_run_id"] == run["id"]
                and other["status"] != "CANCELLED"
            ):
                raise ApiError(
                    "ERR_RUN_ALREADY_ASSIGNED",
                    "the treatment run is already referenced by another live lot",
                    409,
                )

    # Rung 9 — preform reservation capacity.
    if ok_planned and planned > 0 and planned > line_free_units(line):
        raise ApiError(
            "ERR_PREFORM_INSUFFICIENT",
            "planned_units exceed the line's free preform balance",
            409,
        )

    # Rung 11 — input shape.
    errs = []
    if run is None:
        errs.append("treatment_run_id is required")
    if label not in ("SPRING", "PURIFIED"):
        errs.append("label_classification must be SPRING or PURIFIED")
    if not ok_planned or planned <= 0:
        errs.append("planned_units must be a positive integer")
    if not ok_s:
        errs.append("scheduled_start must be a valid ISO 8601 datetime")
    if not ok_e:
        errs.append("scheduled_end must be a valid ISO 8601 datetime")
    if ok_s and ok_e and end <= start:
        errs.append("scheduled_end must fall after scheduled_start")
    if not ok_exp:
        errs.append("expected_line_version is required")
    raise_shape(errs)

    lot = new_resource(
        {
            "line_id": line["id"],
            "treatment_run_id": run_id,
            "label_classification": label,
            "planned_units": planned,
            "produced_units": None,
            "scheduled_start": body.get("scheduled_start"),
            "scheduled_end": body.get("scheduled_end"),
            "status": "PLANNED",
            "rework_count": 0,
            "recall_id": None,
            "completed_by_user_id": None,
            "released_by_user_id": None,
        }
    )
    lot["_start"] = start
    lot["_end"] = end
    store.lots[lot["id"]] = lot
    line["preform_reserved_units"] += planned
    touch(line)
    return ok_object(lot_json(lot), 201)


@bp.get("/api/production-lots")
@auth(ALL_ROLES)
def list_lots():
    items = list(store.lots.values())
    for qp in ("line_id", "treatment_run_id", "recall_id", "status"):
        val = request.args.get(qp)
        if val is not None:
            items = [l for l in items if l.get(qp) == val]
    return ok_list([lot_json(l) for l in by_creation(items)])


@bp.get("/api/production-lots/<lot_id>")
@auth(ALL_ROLES)
def get_lot(lot_id):
    lot = get_or_404(store.lots, lot_id, "production lot")
    return ok_object(lot_json(lot))


@bp.post("/api/production-lots/<lot_id>/start")
@auth(PL)
def start_lot(lot_id):
    lot = get_or_404(store.lots, lot_id, "production lot")
    if lot["status"] != "PLANNED":
        raise err_invalid_state("only a PLANNED lot can be started")
    line = store.lines.get(lot["line_id"])
    plant = store.plants.get(line["plant_id"]) if line else None
    if plant is not None and plant["compliance_posture"] == "BREACH":
        raise ApiError(
            "ERR_POSTURE_BREACH",
            "production cannot start while the plant posture is BREACH",
            409,
        )
    lot["status"] = "IN_PRODUCTION"
    touch(lot)
    return ok_object(lot_json(lot))


@bp.post("/api/production-lots/<lot_id>/complete")
@auth(PL)
def complete_lot(lot_id):
    lot = get_or_404(store.lots, lot_id, "production lot")
    if lot["status"] != "IN_PRODUCTION":
        raise err_invalid_state("only an IN_PRODUCTION lot can be completed")
    body = get_body()
    produced, ok = as_int(body.get("produced_units"))

    # Rung 10 — overproduction guard.
    if ok and produced > lot["planned_units"]:
        raise ApiError(
            "ERR_OVERPRODUCTION",
            "produced_units may not exceed planned_units",
            422,
        )
    # Rung 11 — positivity.
    if not ok or produced <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "produced_units must be a positive integer", 400)

    lot["produced_units"] = produced
    lot["completed_by_user_id"] = g.user_id
    lot["status"] = "QA_HOLD"
    touch(lot)
    line = store.lines.get(lot["line_id"])
    if line is not None:
        line["preform_on_hand_units"] -= produced
        line["preform_reserved_units"] -= lot["planned_units"]
        touch(line)
    create_lab_test(
        line["plant_id"] if line else None,
        "FINISHED_PRODUCT",
        "subject_lot_id",
        lot["id"],
        logical_date() + timedelta(days=2),
        "AUTO",
    )
    return ok_object(lot_json(lot))


@bp.post("/api/production-lots/<lot_id>/release")
@auth(["QAOfficer", "ProductionLead"])
def release_lot(lot_id):
    lot = get_or_404(store.lots, lot_id, "production lot")
    if lot["status"] != "QA_HOLD":
        raise err_invalid_state("only a lot in QA_HOLD can be released")
    # Safety gates in the ladder's fixed sub-order: SoD, treatment, product test.
    if lot.get("completed_by_user_id") is not None and g.user_id == lot["completed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the operator who completed the lot may not release it",
            409,
        )
    run = store.treatment_runs.get(lot["treatment_run_id"])
    if run is None or run["status"] != "VALIDATED":
        raise ApiError(
            "ERR_TREATMENT_NOT_VALIDATED",
            "the lot's treatment run is not VALIDATED",
            409,
        )
    passed = any(
        t["test_type"] == "FINISHED_PRODUCT"
        and t.get("subject_lot_id") == lot["id"]
        and t["status"] == "COMPLETED_PASS"
        for t in store.lab_tests.values()
    )
    if not passed:
        raise ApiError(
            "ERR_PRODUCT_TEST_NOT_PASSED",
            "no COMPLETED_PASS finished-product test exists for the lot",
            409,
        )
    lot["status"] = "RELEASED"
    lot["released_by_user_id"] = g.user_id
    touch(lot)
    return ok_object(lot_json(lot))


@bp.post("/api/production-lots/<lot_id>/reject")
@auth(["QAOfficer"])
def reject_lot(lot_id):
    lot = get_or_404(store.lots, lot_id, "production lot")
    if lot["status"] != "QA_HOLD":
        raise err_invalid_state("only a lot in QA_HOLD can be rejected")
    lot["status"] = "REWORK"
    lot["rework_count"] += 1
    touch(lot)
    return ok_object(lot_json(lot))


@bp.post("/api/production-lots/<lot_id>/rework-complete")
@auth(PL)
def rework_complete(lot_id):
    lot = get_or_404(store.lots, lot_id, "production lot")
    if lot["status"] != "REWORK":
        raise err_invalid_state("only a REWORK lot can return to QA_HOLD")
    lot["status"] = "QA_HOLD"
    touch(lot)
    return ok_object(lot_json(lot))


@bp.post("/api/production-lots/<lot_id>/cancel")
@auth(PL)
def cancel_lot(lot_id):
    lot = get_or_404(store.lots, lot_id, "production lot")
    if lot["status"] != "PLANNED":
        raise err_invalid_state("only a PLANNED lot can be cancelled")
    lot["status"] = "CANCELLED"
    touch(lot)
    line = store.lines.get(lot["line_id"])
    if line is not None:
        line["preform_reserved_units"] -= lot["planned_units"]
        touch(line)
    return ok_object(lot_json(lot))
