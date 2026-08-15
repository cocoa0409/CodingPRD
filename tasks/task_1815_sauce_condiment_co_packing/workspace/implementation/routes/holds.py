"""QualityHold endpoints: manual hold placement (run COMPLETED/ON_HOLD ->
ON_HOLD) and disposition (RELEASE | REWORK | DESTROY) with the statutory
destroy gate, disposition-owner routing, and segregation of duties."""
from flask import Blueprint, g, request

from db import STORE
from errors import (
    err,
    ERR_DISPOSITION_OWNER_MISMATCH,
    ERR_HOLD_NOT_FOUND,
    ERR_HOLD_NOT_OPEN,
    ERR_INVALID_REQUEST,
    ERR_RUN_NOT_COMPLETED,
    ERR_RUN_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STATUTORY_DESTROY_REQUIRED,
)
from middleware import check_customer_scope, require_roles
from response import paginate, success
from services.calc import active_letter_for, hold_deviation_metrics
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from services.run_ops import adjust_outstanding
from util import as_num, as_str, body_json, check_enum, opt, req

bp = Blueprint("holds", __name__)

REASON_CATEGORIES = ("PH_DEVIATION", "AW_DEVIATION", "FOREIGN_MATERIAL", "LABEL_MISMATCH")
DISPOSITIONS = ("RELEASE", "REWORK", "DESTROY")


def _run_chain(hold):
    run = STORE.runs.get(hold["production_run_id"])
    formula = STORE.formulas.get(run["formula_id"]) if run else None
    customer = STORE.customers.get(formula["customer_id"]) if formula else None
    return run, formula, customer


@bp.post("/copack/quality-holds")
def create_hold():
    require_roles("QAReviewer")
    body = body_json()
    raw_run_id = body.get("production_run_id")
    if isinstance(raw_run_id, str):
        find_or_404(STORE.runs, raw_run_id, ERR_RUN_NOT_FOUND, "production run")
    production_run_id = as_str(req(body, "production_run_id"), "production_run_id")
    run = find_or_404(STORE.runs, production_run_id, ERR_RUN_NOT_FOUND, "production run")
    reason_category = check_enum(
        as_str(req(body, "reason_category"), "reason_category"),
        REASON_CATEGORIES, "reason_category",
    )
    # The deviation reasons carry mandatory supporting evidence (PRD §3.7).
    measured_ph = body.get("measured_ph")
    measured_water_activity = body.get("measured_water_activity")
    if reason_category == "PH_DEVIATION":
        measured_ph = as_num(req(body, "measured_ph"), "measured_ph")
    elif measured_ph is not None:
        as_num(measured_ph, "measured_ph")
    if reason_category == "AW_DEVIATION":
        measured_water_activity = as_num(req(body, "measured_water_activity"), "measured_water_activity")
    elif measured_water_activity is not None:
        as_num(measured_water_activity, "measured_water_activity")
    # Stage 6: holds may only be placed on COMPLETED or ON_HOLD runs.
    if run["status"] not in ("COMPLETED", "ON_HOLD"):
        raise err(ERR_RUN_NOT_COMPLETED, 409, "holds may only be placed on COMPLETED or ON_HOLD runs")
    formula = STORE.formulas.get(run["formula_id"])
    customer = STORE.customers.get(formula["customer_id"])
    letter = active_letter_for(run["formula_id"])
    letter_deviation, statutory_margin = hold_deviation_metrics(
        reason_category, measured_ph, measured_water_activity, letter
    )
    rec = new_record({
        "production_run_id": production_run_id,
        "reason_category": reason_category,
        "measured_ph": measured_ph,
        "measured_water_activity": measured_water_activity,
        "letter_deviation": letter_deviation,
        "statutory_margin": statutory_margin,
        "disposition_owner": customer["default_disposition_owner"],
        "created_by_user_id": g.user_id,
        "disposition": None,
        "disposition_note": None,
        "status": "OPEN",
    })
    STORE.holds[rec["id"]] = rec
    # Placing the hold moves the run to ON_HOLD (a run already ON_HOLD stays).
    if run["status"] != "ON_HOLD":
        run["status"] = "ON_HOLD"
        touch(run)
    return success(serialize(rec), 201)


@bp.get("/copack/quality-holds")
def list_holds():
    require_roles("OpsAdmin", "QAReviewer", "Customer")
    production_run_id = request.args.get("production_run_id")
    status = request.args.get("status")
    items = []
    for h in sorted_created(STORE.holds.values()):
        if g.user_role == "Customer":
            _, formula, _ = _run_chain(h)
            if formula is None or formula["customer_id"] != g.user_id:
                continue
        if production_run_id is not None and h["production_run_id"] != production_run_id:
            continue
        if status is not None and h["status"] != status:
            continue
        items.append(serialize(h))
    return paginate(items)


@bp.get("/copack/quality-holds/<hid>")
def get_hold(hid):
    require_roles("OpsAdmin", "QAReviewer", "Customer")
    rec = find_or_404(STORE.holds, hid, ERR_HOLD_NOT_FOUND, "quality hold")
    _, formula, _ = _run_chain(rec)
    if formula is not None:
        check_customer_scope(formula["customer_id"])
    return success(serialize(rec))


@bp.post("/copack/quality-holds/<hid>/disposition")
def disposition_hold(hid):
    require_roles("QAReviewer", "Customer")
    rec = find_or_404(STORE.holds, hid, ERR_HOLD_NOT_FOUND, "quality hold")
    run, formula, customer = _run_chain(rec)
    if formula is not None:
        check_customer_scope(formula["customer_id"])
    body = body_json()
    disposition = check_enum(
        as_str(req(body, "disposition"), "disposition"),
        DISPOSITIONS, "disposition",
    )
    disposition_note = opt(body, "disposition_note")
    if disposition_note is not None:
        as_str(disposition_note, "disposition_note")
    # Stage 6: the hold must be OPEN.
    if rec["status"] != "OPEN":
        raise err(ERR_HOLD_NOT_OPEN, 409, "hold has already been dispositioned")
    # Stage 7 (statutory safety) is evaluated before any actor check: RELEASE
    # and REWORK require a strictly positive statutory_margin on deviation
    # holds; without it only DESTROY is permitted.
    if disposition in ("RELEASE", "REWORK") and rec["reason_category"] in ("PH_DEVIATION", "AW_DEVIATION"):
        margin = rec["statutory_margin"]
        if margin is None or margin <= 0:
            raise err(ERR_STATUTORY_DESTROY_REQUIRED, 409, "statutory ceiling breached; only DESTROY is permitted")
    # Stage 8 actor rules: disposition-owner routing, then segregation of duties.
    if rec["disposition_owner"] == "CUSTOMER":
        if g.user_role != "Customer":
            raise err(ERR_DISPOSITION_OWNER_MISMATCH, 403, "this hold routes disposition to the owning Customer")
    else:  # COPACKER
        if g.user_role != "QAReviewer":
            raise err(ERR_DISPOSITION_OWNER_MISMATCH, 403, "this hold routes disposition to a QAReviewer")
    if g.user_id == rec["created_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, 403, "the hold's creator may not disposition it")
    rec["disposition"] = disposition
    rec["disposition_note"] = disposition_note
    rec["status"] = "DISPOSITIONED"
    touch(rec)
    if run is not None:
        if disposition == "RELEASE":
            # RELEASE frees the run only once no other OPEN holds remain on it.
            siblings_open = any(
                h["production_run_id"] == run["id"] and h["status"] == "OPEN"
                for h in STORE.holds.values()
            )
            if not siblings_open and run["status"] == "ON_HOLD":
                run["status"] = "COMPLETED"
                touch(run)
        elif disposition == "REWORK":
            if run["status"] == "ON_HOLD":
                run["status"] = "REWORK"
                touch(run)
        else:  # DESTROY
            # Sweep every other OPEN hold on the run into DISPOSITIONED(DESTROY).
            for h in STORE.holds.values():
                if h["production_run_id"] == run["id"] and h["status"] == "OPEN":
                    h["disposition"] = "DESTROY"
                    h["status"] = "DISPOSITIONED"
                    touch(h)
            # Destroyed goods are not billable: reverse the final charge.
            if customer is not None and run["final_charge_cents"]:
                adjust_outstanding(customer, -run["final_charge_cents"])
            if run["status"] in ("ON_HOLD", "REWORK", "COMPLETED"):
                run["status"] = "DESTROYED"
                touch(run)
    return success(serialize(rec))
