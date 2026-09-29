"""Qualification submissions and the shipment-lot lifecycle."""

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import find
import store
import validate
from auth import (CUSTOMER_REPRESENTATIVE, DESIGN_ENGINEER, ENGINEERING_MANAGER,
                  PLANT_ADMIN, PROCESS_TECHNICIAN, PROGRAM_MANAGER,
                  QUALITY_INSPECTOR)
from errors import ApiError

bp = Blueprint("commercial", __name__)

SUBMISSION_READERS = (PROGRAM_MANAGER, ENGINEERING_MANAGER, DESIGN_ENGINEER,
                      QUALITY_INSPECTOR, PROCESS_TECHNICIAN, PLANT_ADMIN,
                      CUSTOMER_REPRESENTATIVE)
LOT_READERS = (PROGRAM_MANAGER, PROCESS_TECHNICIAN, QUALITY_INSPECTOR,
               ENGINEERING_MANAGER, DESIGN_ENGINEER, PLANT_ADMIN,
               CUSTOMER_REPRESENTATIVE)

OPEN_SUBMISSION_STATUSES = ("SUBMITTED", "INTERIM_APPROVED", "REVISION_REQUESTED")
GRANTED_STATUSES = ("APPROVED", "INTERIM_APPROVED")
RELEASED_STATES = ("PROTOTYPE_RELEASED", "PRODUCTION_RELEASED")


# ---------------------------------------------------------------------------
# QualificationSubmission
# ---------------------------------------------------------------------------
@bp.post("/qualification-submissions")
def create_submission():
    actor = auth.guard(PROGRAM_MANAGER)
    body = validate.body()
    program_id = validate.req_id(body, "program_id")
    design_id = validate.req_id(body, "design_id")
    ppap_level = validate.req_int(body, "ppap_level", minimum=1, maximum=5)

    program = find.program(program_id)
    design = find.design(design_id)

    if design["release_status"] != "PROTOTYPE_RELEASED":
        raise ApiError("ERR_DESIGN_INVALID_STATE",
                       "Only a PROTOTYPE_RELEASED design may be submitted.")
    if design["program_id"] != program["id"]:
        raise ApiError("ERR_PROGRAM_DESIGN_MISMATCH",
                       "The design belongs to a different program.")
    if ppap_level != program["ppap_level"]:
        raise ApiError("ERR_PPAP_LEVEL_MISMATCH",
                       "The claimed level differs from the program's ppap_level.")
    for existing in store.submissions.values():
        if existing["program_id"] == program["id"] and \
                existing["design_id"] == design["id"] and \
                existing["submission_status"] in OPEN_SUBMISSION_STATUSES:
            raise ApiError("ERR_OPEN_SUBMISSION_EXISTS",
                           "A submission for this pair is still in flight.")
    if not any(r["design_id"] == design["id"]
               and r["fai_disposition"] == "ACCEPTED"
               for r in store.runs.values()):
        raise ApiError("ERR_NO_QUALIFIED_RUN",
                       "No production run of this design has an ACCEPTED first "
                       "article.")

    row = store.base_row()
    row.update({
        "program_id": program["id"],
        "design_id": design["id"],
        "ppap_level": ppap_level,
        "round_no": 1,
        "submission_status": "SUBMITTED",
        "interim_piece_cap": None,
        "submitted_by_user_id": actor.user_id,
        "reviewed_by_program_id": None,
        "decided_at": None,
    })
    store.submissions[row["id"]] = row
    cascades.refresh_posture(program)
    return envelope.created(store.public(row))


@bp.get("/qualification-submissions/<submission_id>")
def read_submission(submission_id):
    actor = auth.guard(*SUBMISSION_READERS)
    submission = find.submission(submission_id)
    auth.own_program(actor, submission["program_id"])
    return envelope.ok(store.public(submission))


@bp.get("/qualification-submissions")
def list_submissions():
    actor = auth.guard(*SUBMISSION_READERS)
    program_id = auth.customer_program_filter(actor,
                                              validate.query_str("program_id"))
    design_id = validate.query_str("design_id")
    status = validate.query_enum("submission_status", calc.SUBMISSION_STATUSES)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.submissions.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if design_id is not None:
        rows = [r for r in rows if r["design_id"] == design_id]
    if status is not None:
        rows = [r for r in rows if r["submission_status"] == status]
    return envelope.listed(rows, limit, offset)


@bp.post("/qualification-submissions/<submission_id>/review")
def review_submission(submission_id):
    actor = auth.guard(CUSTOMER_REPRESENTATIVE)
    submission = find.submission(submission_id)
    auth.own_program(actor, submission["program_id"])
    body = validate.body()
    decision = validate.req_enum(body, "decision",
                                 ("APPROVE", "INTERIM_APPROVE",
                                  "REQUEST_REVISION", "REJECT_FINAL"))
    cap = None
    if decision == "INTERIM_APPROVE":
        cap = validate.req_int(body, "interim_piece_cap", gt=0)

    if submission["submission_status"] != "SUBMITTED":
        raise ApiError("ERR_SUBMISSION_INVALID_STATE",
                       "Only a SUBMITTED package may be decided.")

    program = store.programs.get(submission["program_id"])
    design = store.designs.get(submission["design_id"])

    submission["reviewed_by_program_id"] = actor.user_id
    submission["decided_at"] = store.clock_iso()

    if decision == "APPROVE":
        submission["submission_status"] = "APPROVED"
        store.touch(submission)
        if design is not None:
            if design["release_status"] == "PROTOTYPE_RELEASED":
                design["release_status"] = "PRODUCTION_RELEASED"
                store.touch(design)
            cascades.arm_tooling(design)
        if program is not None:
            program["quote_frozen"] = True
            store.touch_program(program)
    elif decision == "INTERIM_APPROVE":
        submission["submission_status"] = "INTERIM_APPROVED"
        submission["interim_piece_cap"] = cap
        store.touch(submission)
    elif decision == "REQUEST_REVISION":
        submission["submission_status"] = "REVISION_REQUESTED"
        store.touch(submission)
    else:
        submission["submission_status"] = "REJECTED_FINAL"
        store.touch(submission)
        if design is not None and design["release_status"] == "PROTOTYPE_RELEASED":
            design["release_status"] = "REJECTED"
            store.touch(design)

    cascades.refresh_posture(program)
    return envelope.ok(store.public(submission))


@bp.post("/qualification-submissions/<submission_id>/resubmit")
def resubmit_submission(submission_id):
    actor = auth.guard(PROGRAM_MANAGER)
    validate.body()
    submission = find.submission(submission_id)
    if submission["submission_status"] not in ("REVISION_REQUESTED",
                                               "INTERIM_APPROVED"):
        raise ApiError("ERR_SUBMISSION_INVALID_STATE",
                       "Only a REVISION_REQUESTED or INTERIM_APPROVED package "
                       "may be resubmitted.")
    if not submission["round_no"] < calc.MAX_SUBMISSION_ROUNDS:
        raise ApiError("ERR_MAX_SUBMISSION_ROUNDS_EXCEEDED",
                       "The package has exhausted its %d rounds."
                       % calc.MAX_SUBMISSION_ROUNDS)
    design = store.designs.get(submission["design_id"])
    if design is None or design["release_status"] != "PROTOTYPE_RELEASED":
        raise ApiError("ERR_DESIGN_INVALID_STATE",
                       "The design must still be PROTOTYPE_RELEASED.")

    submission["round_no"] += 1
    submission["submission_status"] = "SUBMITTED"
    submission["interim_piece_cap"] = None
    submission["reviewed_by_program_id"] = None
    submission["decided_at"] = None
    submission["submitted_by_user_id"] = actor.user_id
    store.touch(submission)
    cascades.refresh_posture(store.programs.get(submission["program_id"]))
    return envelope.ok(store.public(submission))


# ---------------------------------------------------------------------------
# ShipmentLot
# ---------------------------------------------------------------------------
def _run_pieces_taken(run_id):
    total = 0
    for lot in store.lots.values():
        if lot["run_id"] == run_id and \
                lot["lot_status"] in ("ALLOCATED", "PACKED", "SHIPPED"):
            total += lot["piece_count"]
    return total


@bp.post("/shipment-lots")
def create_lot():
    auth.guard(PROGRAM_MANAGER)
    body = validate.body()
    run_id = validate.req_id(body, "run_id")
    program_id = validate.req_id(body, "program_id")
    piece_count = validate.req_int(body, "piece_count", gt=0)

    program = find.program(program_id)
    run = find.run(run_id)
    design = store.designs.get(run["design_id"])

    if run["process_status"] != "COMPLETE":
        raise ApiError("ERR_RUN_NOT_COMPLETE", "The run is not COMPLETE.")
    if run["quality_status"] not in ("OPEN", "DISPOSITIONED_ACCEPT"):
        raise ApiError("ERR_RUN_ON_SPC_HOLD",
                       "A held or scrapped run cannot be allocated from.")

    submission = cascades.newest_submission(program["id"], run["design_id"])
    if design is None or design["release_status"] not in RELEASED_STATES or \
            submission is None or \
            submission["submission_status"] not in GRANTED_STATUSES:
        raise ApiError("ERR_PPAP_NOT_APPROVED",
                       "No granted approval package is on file for this "
                       "program and design.")
    if run["heat_treat_state"] != "COMPLETE" or \
            (design["shot_peening_required"] and not run["peening_verified"]):
        raise ApiError("ERR_HEAT_TREAT_INCOMPLETE",
                       "Stress relief or shot peening is not complete.")
    if run["min_ppk_observed"] is None or \
            run["min_ppk_observed"] < program["required_ppk"]:
        raise ApiError("ERR_PPK_BELOW_PROGRAM_FLOOR",
                       "The run's observed Ppk is below the program floor.")
    if program["delivery_posture"] == "BLOCKED":
        raise ApiError("ERR_PROGRAM_POSTURE_BLOCKED",
                       "The program's delivery posture is BLOCKED.")
    if design["program_id"] != program["id"]:
        raise ApiError("ERR_PROGRAM_DESIGN_MISMATCH",
                       "The run's design belongs to a different program.")
    if piece_count < program["minimum_order_quantity"]:
        raise ApiError("ERR_BELOW_MINIMUM_ORDER_QUANTITY",
                       "piece_count is below the program's minimum order "
                       "quantity.")
    available = run["produced_pieces"] - _run_pieces_taken(run["id"])
    if piece_count > available:
        raise ApiError("ERR_RUN_PIECES_EXHAUSTED",
                       "The run has only %d unallocated pieces left." % available)
    if program["quoted_unit_price_cents"] is None:
        raise ApiError("ERR_PROGRAM_NOT_QUOTED", "The program has no quote on file.")
    if piece_count > program["open_commitment_pieces"]:
        raise ApiError("ERR_COMMITMENT_EXCEEDED",
                       "piece_count exceeds the program's open commitment.")
    if submission["submission_status"] == "INTERIM_APPROVED":
        cap = submission["interim_piece_cap"] or 0
        if program["allocated_pieces"] + program["shipped_pieces"] + piece_count > cap:
            raise ApiError("ERR_INTERIM_PIECE_CAP_EXCEEDED",
                           "The interim piece cap of %d would be exceeded." % cap)

    unit_price = program["quoted_unit_price_cents"]
    row = store.base_row()
    row.update({
        "run_id": run["id"],
        "program_id": program["id"],
        "piece_count": piece_count,
        "packaging_method": None,
        "lot_status": "ALLOCATED",
        "unit_price_cents": unit_price,
        "tooling_amort_per_piece_cents":
            program["quoted_tooling_amort_per_piece_cents"],
        "extended_price_cents": piece_count * unit_price,
        "tooling_recovery_cents": 0,
        "shipped_at": None,
        "quarantine_reason": None,
    })
    store.lots[row["id"]] = row

    program["open_commitment_pieces"] -= piece_count
    program["allocated_pieces"] += piece_count
    store.touch_program(program)
    cascades.refresh_posture(program)
    return envelope.created(store.public(row))


@bp.get("/shipment-lots/<lot_id>")
def read_lot(lot_id):
    actor = auth.guard(*LOT_READERS)
    lot = find.lot(lot_id)
    auth.own_program(actor, lot["program_id"])
    return envelope.ok(store.public(lot))


@bp.get("/shipment-lots")
def list_lots():
    actor = auth.guard(*LOT_READERS)
    program_id = auth.customer_program_filter(actor,
                                              validate.query_str("program_id"))
    run_id = validate.query_str("run_id")
    status = validate.query_enum("lot_status", calc.LOT_STATUSES)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.lots.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if run_id is not None:
        rows = [r for r in rows if r["run_id"] == run_id]
    if status is not None:
        rows = [r for r in rows if r["lot_status"] == status]
    return envelope.listed(rows, limit, offset)


@bp.post("/shipment-lots/<lot_id>/pack")
def pack_lot(lot_id):
    auth.guard(PROCESS_TECHNICIAN)
    body = validate.body()
    method = validate.req_enum(body, "packaging_method", calc.PACKAGING_METHODS)
    lot = find.lot(lot_id)
    if lot["lot_status"] != "ALLOCATED":
        raise ApiError("ERR_LOT_INVALID_STATE", "Only an ALLOCATED lot may be packed.")

    program = store.programs.get(lot["program_id"])
    run = store.runs.get(lot["run_id"])
    design = store.designs.get(run["design_id"]) if run else None

    permitted = calc.PACKAGING_PERMITTED.get(program["application_class"], ())
    if method not in permitted:
        raise ApiError("ERR_PACKAGING_NOT_PERMITTED",
                       "%s is not permitted for %s programs."
                       % (method, program["application_class"]))
    if design is not None and design["tangle_risk_class"] == "HIGH" and \
            method in ("BULK_BOX", "BAG_AND_TAG"):
        raise ApiError("ERR_TANGLE_RISK_PACKAGING",
                       "A HIGH tangle-risk design may not use %s." % method)

    lot["packaging_method"] = method
    lot["lot_status"] = "PACKED"
    store.touch(lot)
    return envelope.ok(store.public(lot))


@bp.post("/shipment-lots/<lot_id>/ship")
def ship_lot(lot_id):
    auth.guard(PROGRAM_MANAGER)
    validate.body()
    lot = find.lot(lot_id)
    if lot["lot_status"] != "PACKED":
        raise ApiError("ERR_LOT_INVALID_STATE", "Only a PACKED lot may ship.")

    program = store.programs.get(lot["program_id"])
    run = store.runs.get(lot["run_id"])
    if run is not None and run["quality_status"] == "SPC_HOLD":
        raise ApiError("ERR_RUN_ON_SPC_HOLD",
                       "The lot's run is on an SPC hold.")
    if program["delivery_posture"] == "BLOCKED":
        raise ApiError("ERR_PROGRAM_POSTURE_BLOCKED",
                       "The program's delivery posture is BLOCKED.")
    tooling = cascades.newest_tooling(run["design_id"]) if run else None
    if tooling is None or tooling["amortization_status"] not in ("AMORTIZING",
                                                                "FULLY_AMORTIZED"):
        raise ApiError("ERR_TOOLING_NOT_AMORTIZING",
                       "The design's newest tooling asset is not amortizing.")

    recovery = calc.recovery(program, tooling, lot["piece_count"],
                             program["open_commitment_pieces"])
    tooling["recovered_cents"] += recovery
    tooling["unamortized_cents"] -= recovery
    if tooling["unamortized_cents"] == 0 and \
            tooling["amortization_status"] == "AMORTIZING":
        tooling["amortization_status"] = "FULLY_AMORTIZED"
    store.touch(tooling)

    program["allocated_pieces"] -= lot["piece_count"]
    program["shipped_pieces"] += lot["piece_count"]
    store.touch_program(program)

    lot["tooling_recovery_cents"] = recovery
    lot["lot_status"] = "SHIPPED"
    lot["shipped_at"] = store.clock_iso()
    store.touch(lot)
    cascades.refresh_posture(program)
    return envelope.ok(store.public(lot))


@bp.post("/shipment-lots/<lot_id>/return")
def return_lot(lot_id):
    auth.guard(PROGRAM_MANAGER)
    validate.body()
    lot = find.lot(lot_id)
    if lot["lot_status"] != "SHIPPED":
        raise ApiError("ERR_LOT_INVALID_STATE", "Only a SHIPPED lot may be returned.")

    program = store.programs.get(lot["program_id"])
    run = store.runs.get(lot["run_id"])
    tooling = cascades.newest_tooling(run["design_id"]) if run else None
    posted = lot["tooling_recovery_cents"] or 0
    if tooling is not None and posted:
        tooling["recovered_cents"] -= posted
        tooling["unamortized_cents"] += posted
        if tooling["amortization_status"] == "FULLY_AMORTIZED" and \
                tooling["unamortized_cents"] > 0:
            tooling["amortization_status"] = "AMORTIZING"
        store.touch(tooling)

    program["shipped_pieces"] -= lot["piece_count"]
    program["open_commitment_pieces"] += lot["piece_count"]
    store.touch_program(program)

    lot["lot_status"] = "RETURNED"
    lot["shipped_at"] = None
    store.touch(lot)
    cascades.refresh_posture(program)
    return envelope.ok(store.public(lot))


@bp.post("/shipment-lots/<lot_id>/quarantine")
def quarantine_lot_endpoint(lot_id):
    auth.guard(QUALITY_INSPECTOR)
    body = validate.body()
    reason = validate.req_enum(body, "quarantine_reason", calc.QUARANTINE_REASONS)
    lot = find.lot(lot_id)
    if lot["lot_status"] not in ("ALLOCATED", "PACKED"):
        raise ApiError("ERR_LOT_INVALID_STATE",
                       "Only an ALLOCATED or PACKED lot may be quarantined.")
    program = cascades.quarantine_lot(lot, reason, keep_packaging=True)
    cascades.refresh_posture(program)
    return envelope.ok(store.public(lot))


@bp.post("/shipment-lots/<lot_id>/release-from-quarantine")
def release_lot(lot_id):
    auth.guard(QUALITY_INSPECTOR)
    validate.body()
    lot = find.lot(lot_id)
    if lot["lot_status"] != "QUARANTINED":
        raise ApiError("ERR_LOT_INVALID_STATE",
                       "Only a QUARANTINED lot may be released.")
    run = store.runs.get(lot["run_id"])
    if run is not None and run["quality_status"] not in ("OPEN",
                                                         "DISPOSITIONED_ACCEPT"):
        raise ApiError("ERR_RUN_ON_SPC_HOLD",
                       "The lot's run is still held or scrapped.")
    program = store.programs.get(lot["program_id"])
    if program is not None and lot["piece_count"] > program["open_commitment_pieces"]:
        raise ApiError("ERR_COMMITMENT_EXCEEDED",
                       "The program's open commitment cannot absorb this lot.")

    lot["lot_status"] = "ALLOCATED"
    lot["quarantine_reason"] = None
    lot["packaging_method"] = None
    store.touch(lot)
    if program is not None:
        program["quarantined_lot_count"] -= 1
        program["allocated_pieces"] += lot["piece_count"]
        program["open_commitment_pieces"] -= lot["piece_count"]
        store.touch_program(program)
        cascades.refresh_posture(program)
    return envelope.ok(store.public(lot))
