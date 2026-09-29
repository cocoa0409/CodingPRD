"""Fee rate schedules: propose, approve, activate, supersede."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import response
import services
from db import clock, db
from errors import ApiError
from middleware import ADMIN, AUDITOR, REGISTRANT, auth, get_program, get_schedule
from util import (F, apply_filters, base_record, ceil_int, dec, floor_int,
                  pagination, paginate, parse_dt, public, sort_records, touch,
                  validate_body)

bp = Blueprint("rate_schedules", __name__)

PROPOSE_SPEC = [
    F("state_program_id", "string"),
    F("unit_class", "enum", enum=["MATTRESS", "FOUNDATION"]),
    F("fee_cents_per_unit", "int", minimum=1),
    F("effective_from", "datetime"),
    F("effective_to", "datetime", required=False, nullable=True),
    F("expected_state_program_version", "int"),
]


@bp.post("/fee-rate-schedules")
def propose():
    auth([ADMIN])
    body = validate_body(PROPOSE_SPEC)
    eff_from = parse_dt(body["effective_from"])
    eff_to_raw = body.get("effective_to")
    eff_to = parse_dt(eff_to_raw) if eff_to_raw else None
    if eff_to is not None and not eff_to > eff_from:
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_to must be later than effective_from.")

    program = get_program(body["state_program_id"])

    # step 7 — optimistic concurrency on the program version
    if body["expected_state_program_version"] != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION")

    # step 12 — temporal: half-open interval non-overlap
    if calc.rate_period_overlaps(program["id"], body["unit_class"], eff_from, eff_to):
        raise ApiError("ERR_RATE_PERIOD_OVERLAP")

    snapshot = program["recommended_rate_cents"]
    band_low = floor_int(dec(snapshot) * calc.BAND_LOW_MULTIPLIER)
    band_high = ceil_int(dec(snapshot) * calc.BAND_HIGH_MULTIPLIER)

    # step 15 — fiscal: proposal inside the recommended band
    if not (band_low <= body["fee_cents_per_unit"] <= band_high):
        raise ApiError("ERR_RATE_OUTSIDE_RECOMMENDED_BAND")

    rec = base_record()
    rec.update({
        "state_program_id": program["id"],
        "unit_class": body["unit_class"],
        "fee_cents_per_unit": body["fee_cents_per_unit"],
        "effective_from": body["effective_from"],
        "effective_to": eff_to_raw if eff_to_raw else None,
        "status": "PROPOSED",
        "proposed_by_user_id": g.user_id,
        "approved_by_user_id": None,
        "recommended_rate_cents_at_proposal": snapshot,
        "band_low_cents": band_low,
        "band_high_cents": band_high,
    })
    db.fee_rate_schedules[rec["id"]] = rec
    services.refresh_program_and_touch(program)
    return response.obj(public(rec), 201)


@bp.get("/fee-rate-schedules/<schedule_id>")
def read(schedule_id):
    auth([ADMIN, AUDITOR, REGISTRANT])
    return response.obj(public(get_schedule(schedule_id)))


@bp.get("/fee-rate-schedules")
def listing():
    auth([ADMIN, AUDITOR, REGISTRANT])
    limit, offset = pagination()
    records = sort_records(list(db.fee_rate_schedules.values()))
    records = apply_filters(records, [
        ("state_program_id", "state_program_id"),
        ("unit_class", "unit_class"),
        ("status", "status"),
    ])
    window, total = paginate(records, limit, offset)
    return response.arr([public(r) for r in window], limit, offset, total)


@bp.post("/fee-rate-schedules/<schedule_id>/approve")
def approve(schedule_id):
    auth([ADMIN])
    schedule = get_schedule(schedule_id)

    # step 8 — segregation of duties precedes the record's own state
    if g.user_id == schedule["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The proposing administrator may not approve this schedule.")

    # step 9 — own lifecycle state
    if schedule["status"] != "PROPOSED":
        raise ApiError("ERR_RATE_SCHEDULE_NOT_APPROVABLE")

    program = db.state_programs[schedule["state_program_id"]]

    # step 15 — rate increase interlock against the reserve coverage ceiling
    active = _active_schedule(program["id"], schedule["unit_class"])
    if active is not None and schedule["fee_cents_per_unit"] > active["fee_cents_per_unit"]:
        coverage = dec(program["reserve_coverage_months"])
        if not coverage < calc.RATE_INCREASE_COVERAGE_CEILING_MONTHS:
            raise ApiError("ERR_RESERVE_ABOVE_INCREASE_CEILING")

    schedule["status"] = "APPROVED"
    schedule["approved_by_user_id"] = g.user_id
    touch(schedule)
    return response.obj(public(schedule))


@bp.post("/fee-rate-schedules/<schedule_id>/activate")
def activate(schedule_id):
    auth([ADMIN])
    schedule = get_schedule(schedule_id)

    if schedule["status"] != "APPROVED":
        raise ApiError("ERR_RATE_SCHEDULE_NOT_APPROVABLE")

    if clock.now() < parse_dt(schedule["effective_from"]):
        raise ApiError("ERR_RATE_NOT_YET_EFFECTIVE")

    program = db.state_programs[schedule["state_program_id"]]

    prior = _active_schedule(program["id"], schedule["unit_class"])
    if prior is not None and prior["id"] != schedule["id"]:
        prior["status"] = "SUPERSEDED"
        if prior["effective_to"] is None:
            prior["effective_to"] = schedule["effective_from"]
        touch(prior)

    schedule["status"] = "ACTIVE"
    touch(schedule)
    services.refresh_program_and_touch(program)
    return response.obj(public(schedule))


def _active_schedule(program_id, unit_class):
    for sched in db.fee_rate_schedules.values():
        if (sched["state_program_id"] == program_id
                and sched["unit_class"] == unit_class
                and sched["status"] == "ACTIVE"):
            return sched
    return None
