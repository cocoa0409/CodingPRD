"""The fleet: hulls, damage reports, repair bays and condemnation."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import helpers
import response
import validate
from errors import fail

bp = Blueprint("fleet", __name__)

OPEN_REPORT_STATUSES = ("REPORTED", "TRIAGED", "REPAIR_SCHEDULED")


def _touch_shell(shell):
    """Both condition indices are derived, so any report change mutates the hull."""
    db.touch(shell)


def _return_shell_if_clean(shell):
    """DAMAGED -> AVAILABLE once no open report remains on the hull."""
    if shell["status"] != "DAMAGED":
        return
    for report in db.reports.values():
        if report["shell_id"] == shell["id"] and report["status"] in OPEN_REPORT_STATUSES:
            return
    shell["status"] = "AVAILABLE"
    db.touch(shell)


# --------------------------------------------------------------------------- #
# Shells                                                                      #
# --------------------------------------------------------------------------- #
@bp.post("/shells")
@auth.require("EquipmentManager", "ClubAdmin")
def create_shell():
    data = validate.body()
    hull_name = validate.string(data, "hull_name")
    boat_class = validate.enum(data, "boat_class", calc.BOAT_CLASSES)
    hull_weight = validate.number(data, "hull_weight_kg", one_dp=True)
    home_bay = validate.string(data, "home_bay")
    restriction = validate.enum(data, "tier_restriction", calc.TIER_RESTRICTIONS,
                                required=False, default="ANY")
    serviced, serviced_raw = validate.datetime_field(data, "last_serviced_at",
                                                     required=False, nullable=True)

    shell = db.base_record()
    shell["hull_name"] = hull_name
    shell["boat_class"] = boat_class
    shell["hull_weight_kg"] = hull_weight
    shell["tier_restriction"] = restriction
    shell["home_bay"] = home_bay
    db.set_dt(shell, "last_serviced_at", serviced, serviced_raw)
    shell["slot_units"] = calc.CLASS_SLOT_UNITS[boat_class]
    shell["status"] = "AVAILABLE"
    shell["condition_index_conservative"] = calc.INDEX_CEILING
    shell["condition_index_optimistic"] = calc.INDEX_CEILING
    db.shells[shell["id"]] = shell
    return response.created(derive.shell_out(shell))


@bp.get("/shells/<ident>")
@auth.require("ClubAdmin", "Member", "Coach", "SafetyOfficer", "EquipmentManager",
              "RaceOfficial")
def get_shell(ident):
    shell = helpers.load("shell", ident)
    return response.ok(derive.shell_out(shell))


@bp.get("/shells")
@auth.require("ClubAdmin", "Coach", "SafetyOfficer", "EquipmentManager")
def list_shells():
    wanted = response.filters("status", "boat_class")
    rows = db.ordered(db.shells, lambda s: response.matches(s, wanted))
    return response.paginate(rows, derive.shell_out)


@bp.post("/shells/<ident>/retire")
@auth.require("EquipmentManager")
def retire_shell(ident):
    shell = helpers.load("shell", ident)
    data = validate.body()
    validate.string(data, "reason")

    helpers.not_terminal("shell", shell)
    if shell["status"] != "AVAILABLE":
        helpers.invalid_transition(
            "Only an AVAILABLE hull may be retired; this one is %s." % shell["status"])
    for sess in db.sessions.values():
        if sess["shell_id"] == shell["id"] and sess["status"] in ("PLANNED", "CLEARED", "LAUNCHED"):
            helpers.invalid_transition("A live water session still references this hull.")
    for entry in db.entries.values():
        if entry["shell_id"] == shell["id"] and entry["status"] in ("DRAFT",) + cascade.LIVE_ENTRY_STATUSES:
            helpers.invalid_transition("A live regatta entry still races this hull.")

    shell["status"] = "RETIRED"
    db.touch(shell)
    return response.ok(derive.shell_out(shell))


# --------------------------------------------------------------------------- #
# Damage reports                                                              #
# --------------------------------------------------------------------------- #
@bp.post("/damage-reports")
@auth.require("Member", "Coach", "EquipmentManager")
def file_report():
    data = validate.body()
    helpers.check_fk("shell", data, "shell_id")
    helpers.check_fk("member", data, "reported_by_member_id")
    shell_id = validate.string(data, "shell_id")
    reporter_id = validate.string(data, "reported_by_member_id")
    severity = validate.enum(data, "severity", calc.SEVERITIES)
    narrative = validate.string(data, "narrative")

    shell = db.shells[shell_id]
    helpers.not_terminal("shell", shell)

    report = db.base_record()
    report["shell_id"] = shell_id
    report["reported_by_member_id"] = reporter_id
    report["severity"] = severity
    report["narrative"] = narrative
    db.set_dt(report, "reported_at", clock.now())
    report["triaged_by_user_id"] = None
    report["verified_by_user_id"] = None
    report["assigned_repair_bay"] = None
    db.set_dt(report, "repair_window_start_at", None)
    db.set_dt(report, "repair_window_end_at", None)
    report["status"] = "REPORTED"
    db.reports[report["id"]] = report

    if severity in ("MAJOR", "STRUCTURAL") and shell["status"] in ("AVAILABLE", "ASSIGNED"):
        was_assigned = shell["status"] == "ASSIGNED"
        shell["status"] = "DAMAGED"
        db.touch(shell)
        if was_assigned:
            cascade.cancel_sessions_for_shell(shell["id"])
    else:
        _touch_shell(shell)
    return response.created(derive.report_out(report))


@bp.get("/damage-reports/<ident>")
@auth.require("ClubAdmin", "Member", "Coach", "EquipmentManager")
def get_report(ident):
    report = helpers.load("report", ident)
    return response.ok(derive.report_out(report))


@bp.get("/damage-reports")
@auth.require("ClubAdmin", "Member", "Coach", "EquipmentManager")
def list_reports():
    wanted = response.filters("shell_id", "reported_by_member_id", "status", "severity")
    rows = db.ordered(db.reports, lambda r: response.matches(r, wanted))
    return response.paginate(rows, derive.report_out)


@bp.post("/damage-reports/<ident>/triage")
@auth.require("EquipmentManager")
def triage_report(ident):
    report = helpers.load("report", ident)
    data = validate.body()
    disposition = validate.enum(data, "disposition", calc.DISPOSITIONS)

    helpers.not_terminal("report", report)
    if auth.actor_id() == report["reported_by_member_id"]:
        fail("ERR_SELF_TRIAGE_FORBIDDEN",
             "The member who filed this report may not triage it.")

    shell = db.shells.get(report["shell_id"])
    current = report["status"]
    if current == "REPORTED" and disposition == "REPAIR":
        report["status"] = "TRIAGED"
        report["triaged_by_user_id"] = auth.actor_id()
        db.touch(report)
        _touch_shell(shell)
    elif current == "REPORTED" and disposition == "CLOSE_NO_ACTION":
        report["status"] = "CLOSED_NO_ACTION"
        report["triaged_by_user_id"] = auth.actor_id()
        db.touch(report)
        _touch_shell(shell)
        _return_shell_if_clean(shell)
    elif current == "REPAIR_SCHEDULED" and disposition == "REPAIR":
        window_end = db.dt(report, "repair_window_end_at")
        if window_end is not None and clock.now() >= window_end:
            helpers.invalid_transition(
                "The reserved repair window has already elapsed.")
        report["status"] = "TRIAGED"
        report["triaged_by_user_id"] = auth.actor_id()
        report["assigned_repair_bay"] = None
        db.set_dt(report, "repair_window_start_at", None)
        db.set_dt(report, "repair_window_end_at", None)
        db.touch(report)
        if shell is not None and shell["status"] == "IN_REPAIR":
            shell["status"] = "DAMAGED"
            db.touch(shell)
        else:
            _touch_shell(shell)
    else:
        helpers.invalid_transition(
            "A %s report cannot be triaged with disposition %s." % (current, disposition))
    return response.ok(derive.report_out(report))


@bp.post("/damage-reports/<ident>/schedule-repair")
@auth.require("EquipmentManager")
def schedule_repair(ident):
    report = helpers.load("report", ident)
    data = validate.body()
    bay = validate.string(data, "assigned_repair_bay")
    start, start_raw = validate.datetime_field(data, "repair_window_start_at")
    end, end_raw = validate.datetime_field(data, "repair_window_end_at")

    helpers.not_terminal("report", report)
    if report["status"] != "TRIAGED":
        fail("ERR_REPORT_NOT_TRIAGED",
             "Report %s is %s, not TRIAGED." % (report["id"], report["status"]))

    for other in db.reports.values():
        if other["id"] == report["id"] or other["status"] != "REPAIR_SCHEDULED":
            continue
        if other["assigned_repair_bay"] != bay:
            continue
        other_start = db.dt(other, "repair_window_start_at")
        other_end = db.dt(other, "repair_window_end_at")
        if other_start is None or other_end is None:
            continue
        # Closed windows: touching endpoints DO conflict.
        if start <= other_end and other_start <= end:
            fail("ERR_REPAIR_BAY_CONFLICT",
                 "Repair bay %s is already reserved over that window." % bay)

    report["assigned_repair_bay"] = bay
    db.set_dt(report, "repair_window_start_at", start, start_raw)
    db.set_dt(report, "repair_window_end_at", end, end_raw)
    report["status"] = "REPAIR_SCHEDULED"
    db.touch(report)

    shell = db.shells.get(report["shell_id"])
    if shell is not None and shell["status"] == "DAMAGED":
        shell["status"] = "IN_REPAIR"
        db.touch(shell)
    else:
        _touch_shell(shell)
    return response.ok(derive.report_out(report))


@bp.post("/damage-reports/<ident>/verify-repair")
@auth.require("EquipmentManager")
def verify_repair(ident):
    report = helpers.load("report", ident)
    data = validate.body()
    validate.string(data, "note", required=False, nullable=True)

    helpers.not_terminal("report", report)
    if report["status"] != "REPAIR_SCHEDULED":
        fail("ERR_REPORT_NOT_SCHEDULED",
             "Report %s is %s, not REPAIR_SCHEDULED." % (report["id"], report["status"]))
    if auth.actor_id() == report["reported_by_member_id"]:
        fail("ERR_SELF_TRIAGE_FORBIDDEN",
             "The member who filed this report may not verify its repair.")
    window_end = db.dt(report, "repair_window_end_at")
    if window_end is not None and clock.now() < window_end:
        helpers.invalid_transition(
            "The reserved repair window has not yet elapsed.")

    report["status"] = "VERIFIED"
    report["verified_by_user_id"] = auth.actor_id()
    db.touch(report)

    shell = db.shells.get(report["shell_id"])
    if shell is not None and shell["status"] == "IN_REPAIR":
        shell["status"] = "AVAILABLE"
        db.touch(shell)
    else:
        _touch_shell(shell)
    return response.ok(derive.report_out(report))


@bp.post("/damage-reports/<ident>/condemn")
@auth.require("EquipmentManager")
def condemn_report(ident):
    report = helpers.load("report", ident)
    data = validate.body()
    validate.string(data, "reason")

    helpers.not_terminal("report", report)
    if report["status"] not in ("TRIAGED", "REPAIR_SCHEDULED"):
        helpers.invalid_transition(
            "Only a TRIAGED or REPAIR_SCHEDULED report may be condemned; this one is %s."
            % report["status"])
    if report["severity"] != "STRUCTURAL":
        helpers.invalid_transition(
            "Only a STRUCTURAL report may condemn a hull.")

    from_scheduled = report["status"] == "REPAIR_SCHEDULED"
    report["status"] = "CONDEMNED"
    if from_scheduled:
        report["assigned_repair_bay"] = None
        db.set_dt(report, "repair_window_start_at", None)
        db.set_dt(report, "repair_window_end_at", None)
    db.touch(report)

    shell = db.shells.get(report["shell_id"])
    if shell is not None:
        cascade.condemn_shell(shell)
    return response.ok(derive.report_out(report))
