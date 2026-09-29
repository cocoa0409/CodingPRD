"""Shift assignments (PRD 3.2): 6 endpoints."""

from flask import Blueprint

import calc
import clock
import common
import const
import rev
import store
from fields import q_enum, q_str, s_dt, s_enum, s_str
from pipeline import begin, fail, need, run_checks, same_unit
from store import S

bp = Blueprint("shifts", __name__)

READ_ROLES = ["ChargeNurse", "BedsideNurse", "ObstetricianAttending",
              "AnesthesiaLead", "PerinatalSafetyOfficer"]


def _credentialed(staff):
    return (staff["employment_status"] == "ACTIVE"
            and staff.get("credential_expires_at") is not None
            and staff["credential_expires_at"] > clock.now())


@bp.post("/shift-assignments")
def create_shift():
    ctx = begin(
        roles=["ChargeNurse", "AnesthesiaLead"],
        body_refs=[("unit_id", "unit"), ("staff_id", "staff")],
        specs=[s_str("unit_id", required=True), s_str("staff_id", required=True),
               s_enum("role_slot", const.ROLE_SLOTS, required=True),
               s_dt("shift_start_utc", required=True),
               s_dt("shift_end_utc", required=True)],
        scope=lambda c: same_unit(c, c.r["unit"]["id"], [c.r["staff"]]),
    )
    unit = ctx.r["unit"]
    staff = ctx.r["staff"]
    start = ctx.v["shift_start_utc"]
    end = ctx.v["shift_end_utc"]
    if end <= start:
        fail("ERR_INVALID_FIELD_VALUE", "shift_end_utc must be after shift_start_utc.")

    def credential():
        need(_credentialed(staff), "ERR_STAFF_CREDENTIAL_EXPIRED")

    def too_long():
        need(clock.whole_minutes_between(start, end) <= const.MAX_SHIFT_MINUTES,
             "ERR_SHIFT_WINDOW_TOO_LONG")

    def overlap():
        for other in calc.rows("shifts", staff_id=staff["id"]):
            if other["status"] not in ("SCHEDULED", "ACTIVE"):
                continue
            # half-open [start, end): touching endpoints do NOT collide
            if start < other["shift_end_utc"] and other["shift_start_utc"] < end:
                need(False, "ERR_SHIFT_WINDOW_OVERLAP")

    run_checks([(11.1, credential), (13.21, too_long), (13.22, overlap)])
    shift = store.new_record({
        "unit_id": unit["id"],
        "staff_id": staff["id"],
        "role_slot": ctx.v["role_slot"],
        "shift_start_utc": start,
        "shift_end_utc": end,
        "status": "SCHEDULED",
        "capacity_units_effective": None,
        "assigned_acuity_load_units": 0.0,
        "relieved_by_shift_id": None,
    })
    S.shifts[shift["id"]] = shift
    return common.created("shifts", shift)


@bp.get("/shift-assignments")
def list_shifts():
    begin(roles=READ_ROLES)
    unit_id = q_str("unit_id")
    staff_id = q_str("staff_id")
    role_slot = q_enum("role_slot", const.ROLE_SLOTS)
    status = q_enum("status", const.SHIFT_STATUSES)
    relieved_by = q_str("relieved_by_shift_id")
    found = [s for s in S.shifts.values()
             if common.match(s, "unit_id", unit_id)
             and common.match(s, "staff_id", staff_id)
             and common.match(s, "role_slot", role_slot)
             and common.match(s, "status", status)
             and common.match(s, "relieved_by_shift_id", relieved_by)]
    return common.listing("shifts", found,
                          [("shift_start_utc", "asc"), ("created_at", "asc")])


@bp.get("/shift-assignments/<shift_id>")
def read_shift(shift_id):
    ctx = begin(roles=READ_ROLES, path=[("shift", shift_id)])
    return common.single("shifts", ctx.p["shift"])


@bp.post("/shift-assignments/<shift_id>/activate")
def activate_shift(shift_id):
    ctx = begin(roles=["ChargeNurse"], path=[("shift", shift_id)])
    shift = ctx.p["shift"]
    staff = S.staff.get(shift["staff_id"])

    def declared():
        need(shift["status"] == "SCHEDULED", "ERR_INVALID_STATE_TRANSITION")

    def window():
        instant = clock.now()
        need(shift["shift_start_utc"] <= instant < shift["shift_end_utc"],
             "ERR_SHIFT_WINDOW_NOT_CURRENT")

    def credential():
        need(staff is not None and _credentialed(staff), "ERR_STAFF_CREDENTIAL_EXPIRED")

    def standby():
        if shift["role_slot"] == "OR_STANDBY":
            need(staff.get("or_circulating_qualified") is True
                 and staff.get("drill_currency_state") == "CURRENT",
                 "ERR_OR_STANDBY_NOT_QUALIFIED")

    run_checks([(8, declared), (8.08, window), (11.1, credential), (11.2, standby)])
    shift["status"] = "ACTIVE"
    shift["capacity_units_effective"] = calc.staff_capacity_units(
        staff, shift["role_slot"], shift)
    rev.touch(shift)
    calc.recompute_staff_capacity(staff)
    calc.rederive_unit(S.units.get(shift["unit_id"]))
    return common.single("shifts", shift)


@bp.post("/shift-assignments/<shift_id>/relieve")
def relieve_shift(shift_id):
    ctx = begin(roles=["ChargeNurse"], path=[("shift", shift_id)],
                body_refs=[("relieved_by_shift_id", "shift", "relief")],
                specs=[s_str("relieved_by_shift_id", required=True)])
    shift = ctx.p["shift"]
    relief = ctx.r["relief"]
    relief_staff = S.staff.get(relief["staff_id"])

    def declared():
        need(shift["status"] == "ACTIVE", "ERR_INVALID_STATE_TRANSITION")

    def eligible():
        need(relief["id"] != shift["id"]
             and relief["status"] == "ACTIVE"
             and relief["unit_id"] == shift["unit_id"]
             and relief["role_slot"] == shift["role_slot"]
             and relief["staff_id"] != shift["staff_id"],
             "ERR_RELIEVING_SHIFT_INELIGIBLE")

    def credential():
        need(relief_staff is not None and _credentialed(relief_staff),
             "ERR_STAFF_CREDENTIAL_EXPIRED")

    moving = calc.sort_rows(calc.active_care_on_shift(shift["id"]),
                            [("created_at", "asc")])

    def capacity():
        total = 0.0
        for row in moving:
            total += row["acuity_units_consumed"] or 0.0
        projected = clock.one_dp((relief.get("assigned_acuity_load_units") or 0.0)
                                 + total)
        need(projected <= (relief.get("capacity_units_effective") or 0.0),
             "ERR_STAFF_ACUITY_CAPACITY_EXCEEDED")

    run_checks([(8, declared), (8.08, eligible), (11.1, credential), (15, capacity)])

    touched = []
    for row in moving:
        amount = row["acuity_units_consumed"] or 0.0
        calc.move_load(shift, credit=amount)
        calc.move_load(relief, debit=amount)
        row["shift_assignment_id"] = relief["id"]
        row["staff_id"] = relief["staff_id"]
        rev.touch(row)
        enc = S.encounters.get(row["encounter_id"])
        if enc is not None and enc not in touched:
            touched.append(enc)
    shift["status"] = "RELIEVED"
    shift["relieved_by_shift_id"] = relief["id"]
    rev.touch(shift)
    calc.recompute_staff_capacity(relief_staff)
    calc.recompute_staff_capacity(S.staff.get(shift["staff_id"]))
    for enc in touched:
        calc.rederive_encounter(enc)
    calc.rederive_unit(S.units.get(shift["unit_id"]))
    return common.single("shifts", shift)


@bp.post("/shift-assignments/<shift_id>/cancel")
def cancel_shift(shift_id):
    ctx = begin(roles=["ChargeNurse"], path=[("shift", shift_id)])
    shift = ctx.p["shift"]

    def guards():
        # A care assignment can only be ACTIVE on an ACTIVE entry, so the named
        # coverage guard answers before the generic source-state guard; once the
        # row is released the same call falls back to the generic refusal.
        need(not calc.active_care_on_shift(shift["id"]),
             "ERR_SHIFT_HAS_ACTIVE_COVERAGE")
        need(shift["status"] == "SCHEDULED", "ERR_INVALID_STATE_TRANSITION")

    run_checks([(8, guards)])
    shift["status"] = "CANCELLED"
    rev.touch(shift)
    calc.recompute_staff_capacity(S.staff.get(shift["staff_id"]))
    calc.rederive_unit(S.units.get(shift["unit_id"]))
    return common.single("shifts", shift)
