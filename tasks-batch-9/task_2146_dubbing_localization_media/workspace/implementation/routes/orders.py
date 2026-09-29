"""Localization orders: raise, read, list, invoice, deliver, recall, cancel."""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, auth
from domain import (get_cut, get_order, get_spec, newest_mix_job, newest_review,
                    rows_where)
from errors import ApiError
from responses import created, ok, paged
from store import TERRITORIES, db, new_row, serialize, touch
from validate import body, v_enum, v_int, v_object, v_string

bp = Blueprint("orders", __name__)

PRIORITY_TIERS = ("STANDARD", "EXPEDITED", "RUSH")
CANCELLABLE = ("DRAFT", "SCRIPT_IN_PROGRESS", "CASTING", "RECORDING", "MIXING", "QC")


@bp.post("/localization-orders")
@auth("ProductionCoordinator")
def create_order():
    data = body()
    cut = get_cut(data.get("cut_id"))                       # rung 7 (declaration order)
    spec = get_spec(data.get("platform_spec_id"))
    target_language = v_string(data, "target_language")     # rung 8
    territory = v_enum(data, "territory", TERRITORIES)
    budget_cap_cents = v_int(data, "budget_cap_cents", minimum=0)
    priority_tier = v_enum(data, "priority_tier", PRIORITY_TIERS, required=False, default="STANDARD")

    title = db.titles.get(cut["title_id"])
    if title is not None and target_language == title["source_language"]:   # rung 18
        raise ApiError("ERR_SAME_LANGUAGE")
    if cut["status"] != "LOCKED":                                           # rung 22
        raise ApiError("ERR_CUT_NOT_LOCKED")

    row = new_row({
        "cut_id": cut["id"],
        "platform_spec_id": spec["id"],
        "target_language": target_language,
        "territory": territory,
        "priority_tier": priority_tier,
        "budget_cap_cents": budget_cap_cents,
        "status": "DRAFT",
        "committed_cents": 0,
        "released_cents": 0,
        "gross_accrued_cents": 0,
        "retake_cycles": 0,
        "metadata_locale_fields": {},
        "delivered_at": None,
    })
    db.orders[row["id"]] = row
    return created(serialize(row))


@bp.get("/localization-orders/<order_id>")
@auth(*ALL_ROLES)
def read_order(order_id):
    return ok(serialize(get_order(order_id)))


@bp.get("/localization-orders")
@auth(*ALL_ROLES)
def list_orders():
    rows = list(db.orders.values())
    for key in ("cut_id", "platform_spec_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paged(rows, serialize)


@bp.get("/localization-orders/<order_id>/invoice")
@auth("ProductionCoordinator", "PlatformAdmin")
def order_invoice(order_id):
    order = get_order(order_id)
    costs = [s["session_cost_cents"] for s in rows_where(db.sessions, order_id=order["id"])
             if s["status"] == "COMPLETED"]
    return ok(calc.invoice(order["id"], costs, order["priority_tier"]))


@bp.post("/localization-orders/<order_id>/deliver")
@auth("ProductionCoordinator")
def deliver_order(order_id):
    order = get_order(order_id)
    data = body()
    metadata = v_object(data, "metadata_locale_fields")     # rung 8

    if order["status"] != "QC":                             # rung 11
        raise ApiError("ERR_INVALID_STATE")
    review = newest_review(order["id"])
    if review is None or review["status"] != "PASSED":
        raise ApiError("ERR_INVALID_STATE")

    spec = db.platform_specs.get(order["platform_spec_id"])  # rung 36
    required = spec["metadata_fields_required"] if spec else []
    for key in required:
        value = metadata.get(key)
        if value is None:
            raise ApiError("ERR_METADATA_INCOMPLETE")
        if isinstance(value, str) and value.strip() == "":
            raise ApiError("ERR_METADATA_INCOMPLETE")
        if isinstance(value, (list, dict)) and len(value) == 0:
            raise ApiError("ERR_METADATA_INCOMPLETE")

    order["metadata_locale_fields"] = dict(metadata)
    order["delivered_at"] = db.clock
    order["status"] = "DELIVERED"
    touch(order)
    return ok(serialize(order))


@bp.post("/localization-orders/<order_id>/recall")
@auth("ProductionCoordinator")
def recall_order(order_id):
    order = get_order(order_id)
    data = body()
    v_string(data, "reason", required=False, default=None, non_empty=False)

    if order["status"] != "DELIVERED":                      # rung 11
        raise ApiError("ERR_INVALID_STATE")

    order["released_cents"] = order["released_cents"] + order["committed_cents"]
    order["committed_cents"] = 0
    order["status"] = "RECALLED"
    touch(order)

    job = newest_mix_job(order["id"])
    if job is not None and job["status"] == "CONFORMED":
        job["status"] = "SUPERSEDED"
        touch(job)
    return ok(serialize(order))


@bp.post("/localization-orders/<order_id>/cancel")
@auth("ProductionCoordinator")
def cancel_order(order_id):
    order = get_order(order_id)
    data = body()
    v_string(data, "reason", required=False, default=None, non_empty=False)

    if order["status"] not in CANCELLABLE:
        raise ApiError("ERR_ORDER_LOCKED")

    from domain import add_studio_minutes, add_talent_held
    for session in rows_where(db.sessions, order_id=order["id"]):
        if session["status"] not in ("WAITLISTED", "SCHEDULED", "CONFIRMED"):
            continue
        was_holding = session["status"] in ("SCHEDULED", "CONFIRMED")
        session["status"] = "CANCELLED"
        touch(session)
        if was_holding:
            studio = db.studios.get(session["studio_id"])
            assignment = db.assignments.get(session["casting_assignment_id"])
            if studio is not None:
                add_studio_minutes(studio, -session["duration_minutes"])
            if assignment is not None:
                talent = db.voice_talents.get(assignment["talent_id"])
                if talent is not None:
                    add_talent_held(talent, -session["duration_minutes"])

    order["released_cents"] = order["released_cents"] + order["committed_cents"]
    order["committed_cents"] = 0
    order["status"] = "CANCELLED"
    touch(order)
    return ok(serialize(order))
