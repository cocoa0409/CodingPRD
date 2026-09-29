"""Procedure holds, nil-per-os and the missed-meal escalation (PRD section 3.8)."""

from flask import Blueprint

import api
import domain
import serialize
import store
from errors import ApiError

bp = Blueprint("procedure_holds", __name__, url_prefix="/nutrition/procedure-holds")

HOLD_STATUSES = ("SCHEDULED", "ACTIVE", "RELEASED", "CANCELLED")
NPO_KINDS = ("NPO_STRICT", "NPO_CLEAR_LIQUIDS")


@bp.post("")
@api.require("Physician")
def book_hold():
    body = api.body()
    patient_id = api.req_id(body, "patient_id")
    procedure_code = api.req_str(body, "procedure_code")
    npo_kind = api.req_enum(body, "npo_kind", NPO_KINDS)
    hold_start = api.req_dt(body, "hold_start_at")
    hold_end = api.req_dt(body, "hold_end_at")
    buffer_before = api.opt_int(body, "buffer_before_minutes", 0, lo=0, hi=720)
    buffer_after = api.opt_int(body, "buffer_after_minutes", 0, lo=0, hi=720)
    if buffer_before is None:
        buffer_before = 0
    if buffer_after is None:
        buffer_after = 0

    patient = store.get_patient(patient_id)

    if not hold_start < hold_end:
        raise ApiError("ERR_INVALID_WINDOW",
                       "hold_start_at must be strictly before hold_end_at.")
    if patient["status"] != "ADMITTED":
        raise ApiError("ERR_PATIENT_DISCHARGED", "The patient is DISCHARGED.")

    buffered_start = hold_start - store.minutes(buffer_before)
    buffered_end = hold_end + store.minutes(buffer_after)

    for other in store.procedure_holds.values():
        if other["patient_id"] != patient_id:
            continue
        if other["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if buffered_start < other["buffered_end_at"] and other["buffered_start_at"] < buffered_end:
            raise ApiError("ERR_PROCEDURE_HOLD_OVERLAP",
                           "The buffered interval collides with an existing hold.")

    hold = {
        "patient_id": patient_id,
        "procedure_code": procedure_code,
        "npo_kind": npo_kind,
        "hold_start_at": hold_start,
        "hold_end_at": hold_end,
        "buffer_before_minutes": buffer_before,
        "buffer_after_minutes": buffer_after,
        "buffered_start_at": buffered_start,
        "buffered_end_at": buffered_end,
        "status": "SCHEDULED",
        "requested_by_user_id": api.actor(),
        "released_at": None,
        "missed_meal_order_count": 0,
    }
    store.stamp_new(hold)
    store.procedure_holds[hold["id"]] = hold
    return api.created(serialize.procedure_hold(hold))


@bp.get("")
@api.require(*api.ALL_ROLES)
def list_holds():
    patient_id = api.q_str("patient_id")
    status = api.q_enum("status", HOLD_STATUSES)
    rows = api.filtered(list(store.procedure_holds.values()),
                        [(patient_id, "patient_id"), (status, "status")])
    return api.paged(rows, serialize.procedure_hold)


@bp.get("/<hold_id>")
@api.require(*api.ALL_ROLES)
def read_hold(hold_id):
    return api.ok(serialize.procedure_hold(store.get_procedure_hold(hold_id)))


@bp.post("/<hold_id>/activate")
@api.require("Physician")
def activate_hold(hold_id):
    hold = store.get_procedure_hold(hold_id)
    patient = store.patients[hold["patient_id"]]

    if patient["status"] != "ADMITTED":
        raise ApiError("ERR_PATIENT_DISCHARGED", "The patient is DISCHARGED.")
    if hold["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SCHEDULED procedure hold may be activated.")
    for other in store.procedure_holds.values():
        if (other["patient_id"] == hold["patient_id"] and other["status"] == "ACTIVE"
                and other["id"] != hold["id"]):
            raise ApiError("ERR_INVALID_STATE",
                           "Another procedure hold for this patient is already ACTIVE.")

    # Level one -- the patient falls under the hold's nil-per-os severity.
    hold["status"] = "ACTIVE"
    patient["npo_status"] = hold["npo_kind"]

    # Level two -- every covered open tray is voided.
    covered = []
    for tray in store.orders_of_patient(patient["id"]):
        if tray["fulfillment_status"] not in domain.OPEN_TRAY_STATES:
            continue
        period = store.meal_periods[tray["meal_period_id"]]
        if (period["window_start_at"] < hold["buffered_end_at"]
                and hold["buffered_start_at"] < period["window_end_at"]):
            covered.append(tray)

    touched_periods = []
    for tray in covered:
        was_committed = domain.mark_tray_missed(tray, "NPO_HOLD",
                                                bump_patient_version=False)
        if was_committed:
            touched_periods.append(tray["meal_period_id"])
    hold["missed_meal_order_count"] = len(covered)

    # Level three -- the periods that lost a committed tray are re-ledgered.
    domain.reledger_periods(touched_periods)

    store.touch(hold)
    store.touch(patient)
    return api.ok(serialize.procedure_hold(hold))


@bp.post("/<hold_id>/release")
@api.require("Physician")
def release_hold(hold_id):
    hold = store.get_procedure_hold(hold_id)
    if hold["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an ACTIVE procedure hold may be released.")
    patient = store.patients[hold["patient_id"]]
    hold["status"] = "RELEASED"
    hold["released_at"] = store.now()
    patient["npo_status"] = "NONE"
    store.touch(hold)
    store.touch(patient)
    return api.ok(serialize.procedure_hold(hold))


@bp.post("/<hold_id>/cancel")
@api.require("Physician")
def cancel_hold(hold_id):
    hold = store.get_procedure_hold(hold_id)
    if hold["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SCHEDULED procedure hold may be cancelled.")
    hold["status"] = "CANCELLED"
    store.touch(hold)
    return api.ok(serialize.procedure_hold(hold))
