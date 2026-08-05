"""Custody transport: escort, lead time, half-open slots and trip outcomes."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import cascades
import money
import serializers
import store
from constants import (
    CANCEL_REASON, ESCORT_LEVEL, TRANSPORT_CANCEL_CUTOFF_MINUTES, TRANSPORT_OUTCOME,
)
from envelope import created, listing, ok, page_params
from errors import ApiError
from ladder import Ctx

bp = Blueprint("transport", __name__)

NOT_FOUND = "ERR_REFERRAL_RECORD_NOT_FOUND"


@bp.post("/transport-orders")
def create_trip():
    ctx = Ctx(roles=("CustodyOfficer",))

    def bind(row):
        ctx.inmate = store.inmates.get(row["inmate_id"])
    ctx.need_body_ref("referral", store.specialty_referrals, "referral_id", NOT_FOUND)
    ctx.at(4, lambda: bind(ctx.row("referral")) if ctx.row("referral") else None)
    ctx.freeze_gate()
    ctx.occ("expected_referral_version", lambda: ctx.row("referral"), "ERR_STALE_REFERRAL_VERSION")
    ctx.require("referral_id", "appointment_at", "expected_referral_version")
    ctx.check_type("referral_id", "string")
    ctx.check_type("appointment_at", "datetime")
    ctx.check_type("expected_referral_version", "integer")

    def referral_authorized():
        referral = ctx.row("referral")
        if referral is not None and referral["status"] != "AUTHORIZED":
            raise ApiError("ERR_REFERRAL_NOT_AUTHORIZED", "the parent referral is not AUTHORIZED")
    ctx.cross_state(referral_authorized)

    def lead_time():
        referral = ctx.row("referral")
        escort = calc.transport_escort_requirement(ctx.inmate)
        required = calc.transport_required_lead_minutes(referral, escort)
        lead = calc.transport_lead_minutes(ctx.dt_field("appointment_at"))
        if lead < required:
            raise ApiError("ERR_TRANSPORT_LEAD_TIME_TOO_SHORT",
                           "lead time of %d minutes is below the required %d" % (lead, required))
    ctx.temporal(lead_time)

    def slot_conflict():
        referral = ctx.row("referral")
        # The supersede step cancels this referral's DRAFT trips before the
        # calendar is consulted, so their slots are already free here.
        superseded = {t["id"] for t in cascades.trips_of(referral["id"], ("DRAFT",))}
        if calc.transport_slot_conflict(ctx.inmate["id"], ctx.dt_field("appointment_at"),
                                        exclude_ids=superseded):
            raise ApiError("ERR_SCHEDULE_CONFLICT", "the transport slot is already occupied")
    ctx.caps(slot_conflict)
    ctx.run()

    referral = ctx.row("referral")
    for draft in cascades.trips_of(referral["id"], ("DRAFT",)):
        draft["status"] = "CANCELLED"
        draft["cancel_reason"] = "CLINICAL_CHANGE"
        store.touch(draft)

    appointment_at = ctx.dt_field("appointment_at")
    row = store.base_row()
    row.update({
        "referral_id": referral["id"],
        "appointment_at": appointment_at,
        "required_escort_level": calc.transport_escort_requirement(ctx.inmate),
        "assigned_escort_level": None,
        "lead_minutes": calc.transport_lead_minutes(appointment_at),
        "status": "DRAFT",
        "cancel_reason": None,
    })
    store.transport_orders[row["id"]] = row
    store.touch(referral)
    return created(serializers.transport_order(row))


@bp.get("/specialty-referrals/<referral_id>/transport-orders")
def list_trips(referral_id):
    ctx = Ctx(roles=("CustodyOfficer", "Provider", "HealthServicesAdmin"))
    ctx.need("referral", store.specialty_referrals, referral_id, NOT_FOUND)
    ctx.run()

    limit, offset = page_params(request.args)
    rows = [t for t in store.transport_orders.values() if t["referral_id"] == referral_id]
    if request.args.get("status"):
        rows = [t for t in rows if t["status"] == request.args["status"]]
    rows = store.sort_rows(rows)
    return listing(serializers.many(serializers.transport_order, rows), limit, offset)


def _bind_trip(ctx, trip_id):
    def bind(row):
        referral = store.specialty_referrals.get(row["referral_id"])
        ctx.rows["referral"] = referral
        if referral is not None:
            ctx.inmate = store.inmates.get(referral["inmate_id"])
    ctx.need("trip", store.transport_orders, trip_id, NOT_FOUND, on_found=bind)


@bp.post("/transport-orders/<trip_id>/assign-escort")
def assign_escort(trip_id):
    ctx = Ctx(roles=("CustodyOfficer",))
    _bind_trip(ctx, trip_id)
    ctx.freeze_gate()
    ctx.require("escort_level")
    ctx.enum("escort_level", ESCORT_LEVEL)
    ctx.status_in(lambda: ctx.row("trip"), ("DRAFT",))

    def referral_authorized():
        referral = ctx.row("referral")
        if referral is not None and referral["status"] != "AUTHORIZED":
            raise ApiError("ERR_REFERRAL_NOT_AUTHORIZED", "the parent referral is not AUTHORIZED")
    ctx.cross_state(referral_authorized)

    def exact_level():
        trip = ctx.row("trip")
        if ctx.body.get("escort_level") != trip["required_escort_level"]:
            raise ApiError("ERR_ESCORT_LEVEL_MISMATCH",
                           "escort_level must equal required_escort_level exactly")
    ctx.caps(exact_level)
    ctx.run()

    trip = ctx.row("trip")
    referral = ctx.row("referral")
    trip["status"] = "ESCORT_ASSIGNED"
    trip["assigned_escort_level"] = ctx.body["escort_level"]
    referral["status"] = "SCHEDULED"
    store.touch(referral)
    store.touch(trip)
    return ok(serializers.transport_order(trip))


@bp.post("/transport-orders/<trip_id>/dispatch")
def dispatch(trip_id):
    ctx = Ctx(roles=("CustodyOfficer",))
    _bind_trip(ctx, trip_id)
    ctx.freeze_gate()
    ctx.custody_gate()
    ctx.status_in(lambda: ctx.row("trip"), ("ESCORT_ASSIGNED",))
    ctx.run()

    trip = ctx.row("trip")
    trip["status"] = "DISPATCHED"
    store.touch(trip)
    return ok(serializers.transport_order(trip))


@bp.post("/transport-orders/<trip_id>/outcome")
def trip_outcome(trip_id):
    ctx = Ctx(roles=("CustodyOfficer",))
    _bind_trip(ctx, trip_id)
    ctx.freeze_gate()
    ctx.require("outcome")
    ctx.enum("outcome", TRANSPORT_OUTCOME)
    ctx.status_in(lambda: ctx.row("trip"), ("DISPATCHED",))
    ctx.run()

    trip = ctx.row("trip")
    referral = ctx.row("referral")
    if ctx.body["outcome"] == "COMPLETED":
        trip["status"] = "COMPLETED"
        store.touch(trip)
        referral["status"] = "COMPLETED"
        store.touch(referral)
        _charge, entry = money.post_copay_charge(ctx.inmate, "SPECIALTY_OFFSITE")
        if entry is not None:
            store.touch(ctx.inmate)
    else:
        cascades.cascade_no_show(trip, referral)
    return ok(serializers.transport_order(trip))


@bp.post("/transport-orders/<trip_id>/cancel")
def cancel_trip(trip_id):
    ctx = Ctx(roles=("CustodyOfficer",))
    _bind_trip(ctx, trip_id)
    ctx.freeze_gate()
    ctx.require("cancel_reason")
    ctx.enum("cancel_reason", CANCEL_REASON)
    ctx.status_in(lambda: ctx.row("trip"), ("DRAFT", "ESCORT_ASSIGNED", "DISPATCHED"))

    def cutoff():
        trip = ctx.row("trip")
        limit = trip["appointment_at"].dt - timedelta(minutes=TRANSPORT_CANCEL_CUTOFF_MINUTES)
        if store.clock_dt() > limit:
            raise ApiError("ERR_CANCEL_CUTOFF_PASSED", "the cancellation cutoff has passed")
    ctx.temporal(cutoff)
    ctx.run()

    trip = ctx.row("trip")
    referral = ctx.row("referral")
    trip["status"] = "CANCELLED"
    trip["cancel_reason"] = ctx.body["cancel_reason"]
    store.touch(trip)
    if referral is not None and referral["status"] == "SCHEDULED":
        referral["status"] = "AUTHORIZED"      # no_show_count is NOT incremented
        store.touch(referral)
    return ok(serializers.transport_order(trip))
