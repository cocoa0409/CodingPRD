"""Declining price schedules, their markdown steps and consignment agreements."""

from flask import Blueprint

import auth
import envelope
import serializers as ser
import services
import store
import validation as v
from errors import fail
from store import db

bp = Blueprint("schedules", __name__)


# ---------------------------------------------------------------------------
# price schedules
# ---------------------------------------------------------------------------
@bp.post("/price-schedules")
def create_schedule():
    auth.require("GalleryManager")
    data = v.body()
    name = v.req_str(data, "name")
    unsold_trigger_day = v.req_int(data, "unsold_trigger_day", minimum=1)
    election_window_days = v.req_int(data, "election_window_days", minimum=1)
    row = store.new_row(
        db.price_schedules,
        {
            "name": name,
            "unsold_trigger_day": unsold_trigger_day,
            "election_window_days": election_window_days,
            "status": "ACTIVE",
        },
    )
    return envelope.created(ser.price_schedule(row))


@bp.get("/price-schedules/<schedule_id>")
def get_schedule(schedule_id):
    auth.require("GalleryManager", "FloorOperator", "SystemOperator")
    row = v.lookup(db.price_schedules, schedule_id, "ERR_SCHEDULE_NOT_FOUND")
    return envelope.ok(ser.price_schedule(row))


@bp.get("/price-schedules")
def list_schedules():
    auth.require("GalleryManager", "SystemOperator")
    limit, offset = v.pagination()
    status = v.q("status")
    rows = store.ordered(db.price_schedules)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.price_schedule, page), limit, offset, len(rows))


@bp.post("/price-schedule-steps")
def create_step():
    auth.require("GalleryManager")
    data = v.body()

    # ladder 5: body foreign keys, in input order
    raw_schedule = v.raw_fk(data, "schedule_id")
    if raw_schedule is not None and raw_schedule not in db.price_schedules:
        fail("ERR_SCHEDULE_NOT_FOUND")

    schedule_id = v.req_id(data, "schedule_id")
    sequence = v.req_int(data, "sequence", minimum=1)
    start_day_offset = v.req_int(data, "start_day_offset", minimum=0)
    markdown_pct = v.req_num(data, "markdown_pct", minimum=0.0, maximum=0.90)
    min_price_cents = v.req_int(data, "min_price_cents", minimum=0)

    schedule = db.price_schedules.get(schedule_id)
    if schedule is None:
        fail("ERR_SCHEDULE_NOT_FOUND")

    steps = services.steps_of_schedule(schedule_id)
    # ladder 24: appended in sequence at a strictly increasing day offset
    if sequence != len(steps) + 1:
        fail("ERR_SCHEDULE_STEP_OVERLAP")
    if steps:
        if start_day_offset <= steps[-1]["start_day_offset"]:
            fail("ERR_SCHEDULE_STEP_OVERLAP")
    elif start_day_offset != 0:
        fail("ERR_SCHEDULE_STEP_OVERLAP")

    row = store.new_row(
        db.price_schedule_steps,
        {
            "schedule_id": schedule_id,
            "sequence": sequence,
            "start_day_offset": start_day_offset,
            "markdown_pct": markdown_pct,
            "min_price_cents": min_price_cents,
        },
        versioned=False,
    )
    store.touch(schedule)
    return envelope.created(ser.price_schedule_step(row))


@bp.get("/price-schedules/<schedule_id>/steps")
def list_steps(schedule_id):
    auth.require("GalleryManager", "FloorOperator", "SystemOperator")
    v.lookup(db.price_schedules, schedule_id, "ERR_SCHEDULE_NOT_FOUND")
    limit, offset = v.pagination()
    rows = services.steps_of_schedule(schedule_id)
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.price_schedule_step, page), limit, offset, len(rows))


@bp.post("/price-schedules/<schedule_id>/retire")
def retire_schedule(schedule_id):
    auth.require("GalleryManager")
    row = v.lookup(db.price_schedules, schedule_id, "ERR_SCHEDULE_NOT_FOUND")
    if row["status"] == "RETIRED":
        fail("ERR_SCHEDULE_RETIRED")
    row["status"] = "RETIRED"
    store.touch(row)
    return envelope.ok(ser.price_schedule(row))


# ---------------------------------------------------------------------------
# consignment agreements
# ---------------------------------------------------------------------------
@bp.post("/consignment-agreements")
def create_agreement():
    auth.require("GalleryManager")
    data = v.body()

    raw_consignor = v.raw_fk(data, "consignor_id")
    if raw_consignor is not None and raw_consignor not in db.consignors:
        fail("ERR_CONSIGNOR_NOT_FOUND")
    raw_schedule = v.raw_fk(data, "price_schedule_id")
    if raw_schedule is not None and raw_schedule not in db.price_schedules:
        fail("ERR_SCHEDULE_NOT_FOUND")

    consignor_id = v.req_id(data, "consignor_id")
    price_schedule_id = v.req_id(data, "price_schedule_id")
    term_days = v.req_int(data, "term_days", minimum=1)

    consignor = db.consignors.get(consignor_id)
    if consignor is None:
        fail("ERR_CONSIGNOR_NOT_FOUND")
    schedule = db.price_schedules.get(price_schedule_id)
    if schedule is None:
        fail("ERR_SCHEDULE_NOT_FOUND")

    if consignor["escheat_state"] == "ESCHEATED":
        fail("ERR_CONSIGNOR_ESCHEATED")
    if consignor["status"] != "ACTIVE":
        fail("ERR_CONSIGNOR_SUSPENDED")
    if schedule["status"] != "ACTIVE":
        fail("ERR_SCHEDULE_RETIRED")

    row = store.new_row(
        db.agreements,
        {
            "consignor_id": consignor_id,
            "price_schedule_id": price_schedule_id,
            "term_days": term_days,
            "status": "DRAFT",
            "effective_at": None,
            "expires_at": None,
            "approved_by_user_id": None,
        },
    )
    return envelope.created(ser.agreement(row))


@bp.get("/consignment-agreements/<agreement_id>")
def get_agreement(agreement_id):
    user_id, role = auth.require(
        "GalleryManager", "IntakeAppraiser", "FloorOperator", "Consignor", "SystemOperator"
    )
    row = v.lookup(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    auth.scope_consignor(role, user_id, row["consignor_id"])
    return envelope.ok(ser.agreement(row))


@bp.get("/consignment-agreements")
def list_agreements():
    auth.require("GalleryManager", "IntakeAppraiser", "SystemOperator")
    limit, offset = v.pagination()
    consignor_id = v.q("consignor_id")
    price_schedule_id = v.q("price_schedule_id")
    status = v.q("status")
    rows = store.ordered(db.agreements)
    if consignor_id is not None:
        rows = [r for r in rows if r["consignor_id"] == consignor_id]
    if price_schedule_id is not None:
        rows = [r for r in rows if r["price_schedule_id"] == price_schedule_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.agreement, page), limit, offset, len(rows))


@bp.post("/consignment-agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    user_id, role = auth.require("GalleryManager")
    row = v.lookup(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")

    if row["status"] != "DRAFT":
        fail("ERR_AGREEMENT_STATE_INVALID")
    consignor = db.consignors.get(row["consignor_id"])
    if consignor is not None and consignor["status"] != "ACTIVE":
        fail("ERR_CONSIGNOR_SUSPENDED")
    schedule = db.price_schedules.get(row["price_schedule_id"])
    if schedule is None or schedule["status"] != "ACTIVE":
        fail("ERR_SCHEDULE_RETIRED")
    if services.step_count(schedule["id"]) < 1:
        fail("ERR_SCHEDULE_RETIRED")

    row["status"] = "ACTIVE"
    row["effective_at"] = store.now()
    row["expires_at"] = store.add_days(row["effective_at"], row["term_days"])
    row["approved_by_user_id"] = user_id
    store.touch(row)
    return envelope.ok(ser.agreement(row))
