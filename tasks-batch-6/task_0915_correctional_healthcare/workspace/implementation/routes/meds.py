"""Medication orders, the MAR, dose recording, pill counts and adherence."""

from flask import Blueprint, request

import calc
import cascades
import serializers
import store
from constants import (
    ADMIN_OUTCOME_RECORDABLE, CONSECUTIVE_MISSED_ESCALATION, CONSECUTIVE_REFUSED_ESCALATION,
    DOSES_PER_DAY_MAX, DOSES_PER_DAY_MIN, DRUG_CLASS, ROUTE_MODE,
)
from envelope import created, listing, ok, page_params
from errors import ApiError
from ladder import Ctx
from routes.chronic import intake_gate
from timeutil import parse_dt

bp = Blueprint("meds", __name__)


@bp.post("/medication-orders")
def write_order():
    ctx = Ctx(roles=("Provider",))
    ctx.body_inmate("inmate_id")
    ctx.freeze_gate()
    ctx.custody_gate()
    ctx.occ("expected_inmate_version", lambda: ctx.inmate, "ERR_STALE_INMATE_VERSION")
    ctx.require("inmate_id", "drug_name", "drug_class", "route_mode", "doses_per_day",
                "start_date", "end_date", "expected_inmate_version")
    ctx.check_type("inmate_id", "string")
    ctx.check_type("drug_name", "nonempty_string")
    ctx.check_type("doses_per_day", "integer")
    ctx.check_type("expected_inmate_version", "integer")
    ctx.check_type("start_date", "datetime")
    ctx.check_type("end_date", "datetime")
    ctx.check_range("doses_per_day", DOSES_PER_DAY_MIN, DOSES_PER_DAY_MAX)

    def date_order():
        start = parse_dt(ctx.body.get("start_date"))
        end = parse_dt(ctx.body.get("end_date"))
        if start is not None and end is not None and end < start:
            raise ApiError("ERR_VALIDATION", "end_date must not precede start_date")
    ctx.custom_type(date_order)
    ctx.enum("drug_class", DRUG_CLASS)
    ctx.enum("route_mode", ROUTE_MODE)
    intake_gate(ctx)

    def overlap():
        # The supersede step retires same-drug_name ACTIVE orders, and the overlap
        # rule only ever considers a DIFFERENT drug_name, so evaluating the check
        # first is equivalent to the PRD's supersede-then-check order while
        # keeping the create atomic.
        if calc.medication_schedule_conflict(
                ctx.inmate["id"], ctx.body["drug_class"], ctx.body["drug_name"],
                ctx.dt_field("start_date"), ctx.dt_field("end_date")):
            raise ApiError("ERR_SCHEDULE_CONFLICT",
                           "an ACTIVE order of the same drug_class already spans these dates")
    ctx.caps(overlap)
    ctx.run()

    # Supersede: an ACTIVE order for the same inmate and drug_name is auto-discontinued.
    for existing in cascades.orders_of(ctx.inmate["id"], ("ACTIVE",)):
        if existing["drug_name"] == ctx.body["drug_name"]:
            cascades.retire_order(existing, "DISCONTINUED")

    row = store.base_row()
    row.update({
        "inmate_id": ctx.inmate["id"],
        "drug_name": ctx.body["drug_name"],
        "drug_class": ctx.body["drug_class"],
        "route_mode": ctx.body["route_mode"],
        "doses_per_day": ctx.body["doses_per_day"],
        "start_date": ctx.dt_field("start_date"),
        "end_date": ctx.dt_field("end_date"),
        "units_dispensed": 0,
        "units_returned": 0,
        "consecutive_missed_count": 0,
        "consecutive_refused_count": 0,
        "adherence_pct": 0.00,
        "escalated_to_prescriber": False,
        "forced_dot": False,
        "status": "ACTIVE",
        "prescriber_user_id": ctx.user_id,
    })
    store.medication_orders[row["id"]] = row
    store.touch(ctx.inmate)
    return created(serializers.medication_order(row))


@bp.get("/medication-orders")
def list_orders():
    ctx = Ctx(roles=("Provider", "Nurse", "HealthServicesAdmin"))
    ctx.run()

    limit, offset = page_params(request.args)
    rows = list(store.medication_orders.values())
    for field in ("inmate_id", "status", "route_mode", "drug_class"):
        wanted = request.args.get(field)
        if wanted:
            rows = [o for o in rows if o[field] == wanted]
    rows = store.sort_rows(rows)
    return listing(serializers.many(serializers.medication_order, rows), limit, offset)


@bp.get("/medication-orders/<order_id>")
def read_order(order_id):
    ctx = Ctx(roles=("Provider", "Nurse", "HealthServicesAdmin"))
    ctx.need("order", store.medication_orders, order_id, "ERR_RECORD_NOT_FOUND")
    ctx.run()
    return ok(serializers.medication_order(ctx.row("order")))


def _bind_order(ctx, order_id):
    def bind(row):
        ctx.inmate = store.inmates.get(row["inmate_id"])
    ctx.need("order", store.medication_orders, order_id, "ERR_RECORD_NOT_FOUND", on_found=bind)


@bp.post("/medication-orders/<order_id>/hold-status")
def hold_status(order_id):
    ctx = Ctx(roles=("Provider",))
    _bind_order(ctx, order_id)
    ctx.freeze_gate()

    def custody_on_resume():
        # PRD 3.4: only the resume direction additionally requires IN_CUSTODY.
        if ctx.body.get("held") is False and ctx.inmate is not None \
                and ctx.inmate["custody_status"] != "IN_CUSTODY":
            raise ApiError("ERR_INMATE_NOT_IN_CUSTODY", "inmate is no longer in custody")
    ctx.at(6, custody_on_resume)
    ctx.require("held")
    ctx.check_type("held", "boolean")

    def target_state():
        row = ctx.row("order")
        held = ctx.body.get("held")
        wanted = "ACTIVE" if held is True else "HELD"
        if row["status"] != wanted:
            raise ApiError("ERR_INVALID_STATE",
                           "status %s does not permit this transition" % row["status"])
    ctx.state(target_state)
    ctx.run()

    row = ctx.row("order")
    row["status"] = "HELD" if ctx.body["held"] else "ACTIVE"
    store.touch(row)
    return ok(serializers.medication_order(row))


@bp.post("/medication-orders/<order_id>/discontinue")
def discontinue(order_id):
    ctx = Ctx(roles=("Provider",))
    _bind_order(ctx, order_id)
    ctx.freeze_gate()
    ctx.status_in(lambda: ctx.row("order"), ("ACTIVE", "HELD"))
    ctx.run()

    row = cascades.retire_order(ctx.row("order"), "DISCONTINUED")
    return ok(serializers.medication_order(row))


@bp.post("/medication-orders/<order_id>/pill-count")
def pill_count(order_id):
    ctx = Ctx(roles=("Nurse",))
    _bind_order(ctx, order_id)
    ctx.freeze_gate()
    ctx.require("units_dispensed_delta", "units_returned_delta")
    ctx.check_type("units_dispensed_delta", "integer")
    ctx.check_type("units_returned_delta", "integer")
    ctx.run()

    row = ctx.row("order")
    row["units_dispensed"] += ctx.body["units_dispensed_delta"]
    row["units_returned"] += ctx.body["units_returned_delta"]
    calc.recompute_adherence(row)
    store.touch(row)
    return ok(serializers.medication_order(row))


@bp.post("/medication-orders/<order_id>/administrations")
def schedule_dose(order_id):
    ctx = Ctx(roles=("Nurse",))
    _bind_order(ctx, order_id)
    ctx.freeze_gate()
    ctx.require("scheduled_at")
    ctx.check_type("scheduled_at", "datetime")
    ctx.run()

    row = store.base_row()
    row.update({
        "order_id": order_id,
        "scheduled_at": ctx.dt_field("scheduled_at"),
        "acted_at": None,
        "outcome": "SCHEDULED",
        "observed_swallow": None,
        "diversion_observed": False,
        "timing_class": None,
        "administered_by_user_id": None,
    })
    store.medication_administrations[row["id"]] = row
    return created(serializers.medication_administration(row))


@bp.get("/medication-orders/<order_id>/administrations")
def list_doses(order_id):
    ctx = Ctx(roles=("Nurse", "Provider", "HealthServicesAdmin"))
    ctx.need("order", store.medication_orders, order_id, "ERR_RECORD_NOT_FOUND")
    ctx.run()

    limit, offset = page_params(request.args)
    rows = [a for a in store.medication_administrations.values() if a["order_id"] == order_id]
    if request.args.get("outcome"):
        rows = [a for a in rows if a["outcome"] == request.args["outcome"]]
    rows = store.sort_rows(rows, key="scheduled_at")
    return listing(serializers.many(serializers.medication_administration, rows), limit, offset)


@bp.post("/medication-administrations/<administration_id>/record")
def record_dose(administration_id):
    ctx = Ctx(roles=("Nurse",))

    def bind(row):
        order = store.medication_orders.get(row["order_id"])
        ctx.rows["order"] = order
        if order is not None:
            ctx.inmate = store.inmates.get(order["inmate_id"])
    ctx.need("administration", store.medication_administrations, administration_id,
             "ERR_RECORD_NOT_FOUND", on_found=bind)
    ctx.freeze_gate()
    ctx.require("outcome")
    ctx.check_type("observed_swallow", "boolean")
    ctx.check_type("diversion_observed", "boolean")
    ctx.enum("outcome", ADMIN_OUTCOME_RECORDABLE)
    ctx.status_in(lambda: ctx.row("administration"), ("SCHEDULED",), field="outcome")

    def order_active():
        order = ctx.row("order")
        if order is not None and order["status"] != "ACTIVE":
            raise ApiError("ERR_ORDER_NOT_ACTIVE", "the parent order is not ACTIVE")
    ctx.cross_state(order_active)

    def observation_discipline():
        order = ctx.row("order")
        if order is None:
            return
        supplied = ctx.body.get("observed_swallow") is not None
        if order["route_mode"] == "DOT":
            if ctx.body.get("outcome") == "ADMINISTERED" and not supplied:
                raise ApiError("ERR_DOT_OBSERVATION_REQUIRED",
                               "observed_swallow is required on a DOT administration")
        else:
            if supplied:
                raise ApiError("ERR_KOP_OBSERVATION_FORBIDDEN",
                               "observed_swallow is forbidden on a KOP order")
    ctx.safety(observation_discipline)

    def not_prescriber():
        order = ctx.row("order")
        if order is not None and ctx.user_id == order.get("prescriber_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the prescriber may not record the administration")
    ctx.segregation(not_prescriber)
    ctx.run()

    row = ctx.row("administration")
    order = ctx.row("order")
    outcome = ctx.body["outcome"]
    acted_at = store.now()
    row["outcome"] = outcome
    row["acted_at"] = acted_at
    row["administered_by_user_id"] = ctx.user_id
    if ctx.body.get("observed_swallow") is not None:
        row["observed_swallow"] = ctx.body["observed_swallow"]
    diversion = ctx.body.get("diversion_observed")
    row["diversion_observed"] = bool(diversion) if diversion is not None else False

    if outcome == "ADMINISTERED":
        row["timing_class"] = calc.dose_timing_class(acted_at, row["scheduled_at"])
        order["consecutive_missed_count"] = 0
        order["consecutive_refused_count"] = 0
    elif outcome == "REFUSED":
        row["timing_class"] = None
        order["consecutive_refused_count"] += 1
        if order["consecutive_refused_count"] >= CONSECUTIVE_REFUSED_ESCALATION:
            order["escalated_to_prescriber"] = True
    else:  # MISSED -- forced, without consulting the window arithmetic
        row["timing_class"] = "MISSED_WINDOW"
        order["consecutive_missed_count"] += 1
        if order["consecutive_missed_count"] >= CONSECUTIVE_MISSED_ESCALATION:
            order["escalated_to_prescriber"] = True

    # Cascade C: a witnessed diversion on a KOP administration forces DOT.
    if outcome == "ADMINISTERED" and row["diversion_observed"] and order["route_mode"] == "KOP":
        order["route_mode"] = "DOT"
        order["forced_dot"] = True

    calc.recompute_adherence(order)
    store.touch(row)
    store.touch(order)
    return ok(serializers.medication_administration(row))
