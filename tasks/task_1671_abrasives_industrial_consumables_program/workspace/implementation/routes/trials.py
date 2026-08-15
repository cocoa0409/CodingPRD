"""Trial case endpoints (PRD 3.8): documentation, results, conversion (SoD),
rejection. Closed scheduling windows with a 1-day buffer."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_MACHINE_NOT_ACTIVE, ERR_PRODUCT_DISCONTINUED, ERR_SEPARATION_OF_DUTIES,
    ERR_TRIAL_WINDOW_CONFLICT,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from routes.usage_records import safety_gates
from services.calc import recompute_consumption_flag
from services.core import new_record, serialize, touch
from util import CLOCK, parse_date, round4
from validate import (
    get_body, opt_str, req_date, req_decimal, req_int, req_str, require_fk,
    require_path_resource,
)

bp = Blueprint("trials", __name__)

_ONE_DAY = timedelta(days=1)


@bp.post("/api/trials")
def create_trial():
    authorized(["AccountManager"])
    # Priority 3: shape — closed window, end on or after start.
    body = get_body()
    machine_id = req_str(body, "machine_id")
    product_id = req_str(body, "product_id")
    scheduled_start = req_date(body, "scheduled_start")
    scheduled_end = req_date(body, "scheduled_end")
    incumbent_id = opt_str(body, "incumbent_product_id", default=None)
    start_d = parse_date(scheduled_start)
    end_d = parse_date(scheduled_end)
    if end_d < start_d:
        raise_error(ERR_INVALID_REQUEST, "scheduled_end must be on or after scheduled_start")
    # Priority 4: body FK existence (machine, product, then optional incumbent).
    machine = require_fk("machines", machine_id, "machine")
    product = require_fk("products", product_id, "product")
    if incumbent_id is not None:
        require_fk("products", incumbent_id, "incumbent product")
    # Priority 6: machine must be ACTIVE.
    if machine["status"] != "ACTIVE":
        raise_error(ERR_MACHINE_NOT_ACTIVE, "machine is not ACTIVE")
    # Priority 7: safety gates on the candidate product (speed, then guard).
    safety_gates(product, machine)
    # Priority 8: candidate product ACTIVE, then the closed-window + 1-day
    # buffer conflict against ACTIVE|EVALUATION trials on the same machine.
    if product["status"] != "ACTIVE":
        raise_error(ERR_PRODUCT_DISCONTINUED, "trial product is not ACTIVE")
    for t in db["trials"].values():
        if t["machine_id"] != machine_id or t["status"] not in ("ACTIVE", "EVALUATION"):
            continue
        ex_start = parse_date(t["scheduled_start"])
        ex_end = parse_date(t["scheduled_end"])
        # No conflict requires a full calendar day of buffer on one side:
        # start >= ex_end + 2  OR  ex_start >= end + 2.
        if not (start_d >= ex_end + 2 * _ONE_DAY or ex_start >= end_d + 2 * _ONE_DAY):
            raise_error(
                ERR_TRIAL_WINDOW_CONFLICT,
                "trial window overlaps or lacks the required 1-day buffer on this machine",
            )
    rec = new_record("trials", {
        "machine_id": machine_id,
        "product_id": product_id,
        "incumbent_product_id": incumbent_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "results_submitted_by_user_id": None,
        "measured_removal_rate_g_per_min": None,
        "parts_per_unit_media": None,
        "cost_per_part_cents": None,
        "converted_standard_id": None,
        "rejection_reason": None,
        "status": "ACTIVE",
    })
    return success_object(serialize(rec), status=201)


@bp.get("/api/trials/<tid>")
def get_trial(tid):
    return get_one("trials", tid, "trial")


@bp.get("/api/trials")
def list_trials():
    return list_response("trials", {
        "machine_id": arg("machine_id"),
        "product_id": arg("product_id"),
        "incumbent_product_id": arg("incumbent_product_id"),
        "converted_standard_id": arg("converted_standard_id"),
        "status": arg("status"),
    })


@bp.post("/api/trials/<tid>/submit-results")
def submit_trial_results(tid):
    caller = authorized(["EHSOfficer"])
    # Priority 3: shape — three metrics; parts_per_unit_media strictly positive.
    body = get_body()
    removal = req_decimal(body, "measured_removal_rate_g_per_min")
    parts = req_decimal(body, "parts_per_unit_media", gt=Decimal("0"))
    cost = req_int(body, "cost_per_part_cents")
    # Priority 4: path existence. Priority 6: submission requires ACTIVE.
    trial = require_path_resource("trials", tid, "trial")
    if trial["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION, "results can only be submitted on an ACTIVE trial")
    trial["measured_removal_rate_g_per_min"] = removal
    trial["parts_per_unit_media"] = parts
    trial["cost_per_part_cents"] = cost
    trial["results_submitted_by_user_id"] = caller.user_id
    trial["status"] = "EVALUATION"
    touch(trial)
    return success_object(serialize(trial))


@bp.post("/api/trials/<tid>/convert")
def convert_trial(tid):
    caller = authorized(["ProgramAdmin"])
    trial = require_path_resource("trials", tid, "trial")
    if trial["status"] != "EVALUATION":
        raise_error(ERR_INVALID_STATE_TRANSITION, "only an EVALUATION trial can be converted")
    # Segregation of duties: the converting operator must differ from the
    # results submitter.
    if caller.user_id == trial["results_submitted_by_user_id"]:
        raise_error(ERR_SEPARATION_OF_DUTIES, "the results submitter may not approve conversion")

    machine_id, product_id = trial["machine_id"], trial["product_id"]
    # Retire the ACTIVE standard for (machine, product) if one exists.
    candidates = [
        s for s in db["standards"].values()
        if s["machine_id"] == machine_id and s["product_id"] == product_id and s["status"] == "ACTIVE"
    ]
    if candidates:
        today = CLOCK.today()
        covering = [
            s for s in candidates
            if parse_date(s["effective_from"]) <= today
            and (s["effective_to"] is None or today < parse_date(s["effective_to"]))
        ]
        pool = covering or candidates
        pool.sort(key=lambda s: (s["effective_from"], s["created_at"]), reverse=True)
        old = pool[0]
        old["status"] = "RETIRED"
        touch(old)
    # Create the converted standard.
    rate = round4(Decimal(1) / trial["parts_per_unit_media"])
    std = new_record("standards", {
        "machine_id": machine_id,
        "product_id": product_id,
        "operation_name": "TRIAL-CONVERSION",
        "standard_qty_per_part": rate,
        "effective_from": CLOCK.today().isoformat(),
        "effective_to": None,
        "needs_review": False,
        "status": "ACTIVE",
    })
    trial["converted_standard_id"] = std["id"]
    trial["status"] = "CONVERTED"
    touch(trial)
    machine = db["machines"].get(machine_id)
    if machine is not None and recompute_consumption_flag(machine):
        touch(machine)
    return success_object(serialize(trial))


@bp.post("/api/trials/<tid>/reject")
def reject_trial(tid):
    authorized(["ProgramAdmin"])
    # Priority 3: rejection must carry a rejection_reason.
    body = get_body()
    reason = req_str(body, "rejection_reason")
    trial = require_path_resource("trials", tid, "trial")
    if trial["status"] != "EVALUATION":
        raise_error(ERR_INVALID_STATE_TRANSITION, "only an EVALUATION trial can be rejected")
    trial["rejection_reason"] = reason
    trial["status"] = "REJECTED"
    touch(trial)
    return success_object(serialize(trial))
