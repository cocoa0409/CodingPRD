"""Beds (PRD 3.5 bed lifecycle): 6 endpoints."""

from flask import Blueprint

import calc
import common
import const
import rev
import store
from fields import q_enum, q_str, s_enum, s_str
from pipeline import begin, need, run_checks
from store import S

bp = Blueprint("beds", __name__)

ALL = const.ALL_ROLES


def _filtered(records):
    bed_type = q_enum("bed_type", const.BED_TYPES)
    status = q_enum("status", const.BED_STATUSES)
    encounter_id = q_str("current_encounter_id")
    booking_id = q_str("held_booking_id")
    return [b for b in records
            if common.match(b, "bed_type", bed_type)
            and common.match(b, "status", status)
            and common.match(b, "current_encounter_id", encounter_id)
            and common.match(b, "held_booking_id", booking_id)]


@bp.post("/obstetric-units/<unit_id>/beds")
def create_bed(unit_id):
    ctx = begin(
        roles=["PerinatalSafetyOfficer", "ChargeNurse"],
        path=[("unit", unit_id)],
        specs=[s_str("bed_label", required=True, min_len=1, max_len=40),
               s_enum("bed_type", const.BED_TYPES, required=True)],
    )
    unit = ctx.p["unit"]

    def unique_label():
        for other in calc.rows("beds", unit_id=unit["id"]):
            if other["status"] != "CLOSED" and other["bed_label"] == ctx.v["bed_label"]:
                need(False, "ERR_DUPLICATE_BED_LABEL")

    run_checks([(13.1, unique_label)])
    bed = store.new_record({
        "unit_id": unit["id"],
        "bed_label": ctx.v["bed_label"],
        "bed_type": ctx.v["bed_type"],
        "status": "AVAILABLE",
        "current_encounter_id": None,
        "held_booking_id": None,
        "turnover_clear_at": None,
    })
    S.beds[bed["id"]] = bed
    calc.rederive_unit(unit)          # the first AVAILABLE LDR bed can lift a divert
    return common.created("beds", bed)


@bp.get("/obstetric-units/<unit_id>/beds")
def list_unit_beds(unit_id):
    ctx = begin(roles=ALL, path=[("unit", unit_id)])
    found = _filtered(calc.rows("beds", unit_id=ctx.p["unit"]["id"]))
    return common.listing("beds", found, [("bed_label", "asc")])


@bp.get("/beds")
def list_beds():
    begin(roles=ALL)
    unit_id = q_str("unit_id")
    found = _filtered([b for b in S.beds.values() if common.match(b, "unit_id", unit_id)])
    return common.listing("beds", found, [("bed_label", "asc"), ("created_at", "asc")])


@bp.get("/beds/<bed_id>")
def read_bed(bed_id):
    ctx = begin(roles=ALL, path=[("bed", bed_id)])
    return common.single("beds", ctx.p["bed"])


@bp.patch("/beds/<bed_id>")
def patch_bed(bed_id):
    ctx = begin(roles=["ChargeNurse"], path=[("bed", bed_id)],
                specs=[s_enum("status", ("AVAILABLE", "BLOCKED"), required=True)])
    bed = ctx.p["bed"]
    target = ctx.v["status"]

    def declared():
        # The only declared edges are AVAILABLE -> BLOCKED and BLOCKED -> AVAILABLE.
        if bed["status"] in ("AVAILABLE", "BLOCKED"):
            need(bed["status"] != target, "ERR_INVALID_STATE_TRANSITION")
        else:
            need(bed["status"] != "CLOSED", "ERR_INVALID_STATE_TRANSITION")

    def releasable():
        need(bed["status"] not in ("HELD", "OCCUPIED", "TURNOVER"),
             "ERR_BED_NOT_RELEASABLE")

    run_checks([(8, declared), (8.07, releasable)])
    bed["status"] = target
    rev.touch(bed)
    calc.rederive_unit(S.units.get(bed["unit_id"]))
    return common.single("beds", bed)


@bp.delete("/beds/<bed_id>")
def retire_bed(bed_id):
    ctx = begin(roles=["PerinatalSafetyOfficer"], path=[("bed", bed_id)])
    bed = ctx.p["bed"]

    def declared():
        need(bed["status"] != "CLOSED", "ERR_INVALID_STATE_TRANSITION")

    def bed_lifecycle():
        # A booking in CAPACITY_HELD or CONFIRMED always leaves its bed HELD, so
        # the future-holds guard has to answer before the AVAILABLE/BLOCKED
        # source guard or it could never be reached at all.
        for booking in S.bookings.values():
            if (booking.get("bed_id") == bed["id"]
                    and booking["status"] in ("CAPACITY_HELD", "CONFIRMED")):
                need(False, "ERR_BED_HAS_FUTURE_HOLDS")
        need(bed["status"] in ("AVAILABLE", "BLOCKED"), "ERR_BED_NOT_RELEASABLE")

    run_checks([(8, declared), (8.07, bed_lifecycle)])
    bed["status"] = "CLOSED"
    bed["current_encounter_id"] = None
    bed["held_booking_id"] = None
    bed["turnover_clear_at"] = None
    rev.touch(bed)
    calc.rederive_unit(S.units.get(bed["unit_id"]))
    return common.single("beds", bed)
