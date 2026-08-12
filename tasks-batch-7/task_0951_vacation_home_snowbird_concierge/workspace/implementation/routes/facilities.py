"""Winterization records, rental turnovers and mail holds."""
from datetime import timedelta

from flask import Blueprint

import calc
import core
import gates
import serialize
from core import D, fail, get, new_row, now, parse_iso, rhu1, touch
from gates import check_state

bp = Blueprint("facilities", __name__)


# ---------------------------------------------------------------------------
# Winterization records
# ---------------------------------------------------------------------------
WINT_READ_ROLES = ["Dispatcher", "FieldTech", "PlatformAdmin", "Auditor", "Owner"]


def _recount(record):
    done = 0
    done += 1 if record["water_shutoff_done"] else 0
    done += 1 if record["lines_drained_done"] else 0
    if record["thermostat_set_f"] is not None and \
            D(record["thermostat_set_f"]) >= core.WINTERIZATION_MIN_THERMOSTAT_F:
        done += 1
    done += 1 if record["valve_tagged_done"] else 0
    record["completed_step_count"] = done
    record["completeness_pct"] = rhu1(
        D(100) * D(done) / D(core.WINTERIZATION_REQUIRED_STEP_COUNT))
    return done


@bp.post("/property-care/properties/<pid>/winterization-records")
def create_record(pid):
    gates.begin(["Dispatcher", "FieldTech", "PlatformAdmin"])
    prop = gates.fetch_path("properties", pid)
    body = gates.body_json()
    gates.resolve_optional_fks(body, ["visit_id"])
    gates.validate_payload(body, [("visit_id", "string", False)])
    record = new_row(
        "winterization_records",
        property_id=prop["id"], visit_id=body.get("visit_id"),
        water_shutoff_done=False, lines_drained_done=False, thermostat_set_f=None,
        valve_tagged_done=False, antifreeze_added_done=False,
        completed_step_count=0, completeness_pct=0.0,
        status="NOT_STARTED", completed_at=None, reopen_reason=None,
    )
    return core.ok(serialize.winterization_record(record), 201)


@bp.get("/property-care/winterization-records")
def list_records():
    gates.begin(WINT_READ_ROLES)
    return gates.list_response("winterization_records", ["property_id", "visit_id", "status"],
                               serialize.winterization_record)


@bp.get("/property-care/winterization-records/<rid>")
def read_record(rid):
    role, user_id = gates.begin(WINT_READ_ROLES)
    record = gates.fetch_path("winterization_records", rid)
    prop = get("properties", record["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    return core.ok(serialize.winterization_record(record))


STEP_FLAGS = {
    "WATER_SHUTOFF": "water_shutoff_done",
    "LINES_DRAINED": "lines_drained_done",
    "VALVE_TAGGED": "valve_tagged_done",
    "ANTIFREEZE_ADDED": "antifreeze_added_done",
}


@bp.post("/property-care/winterization-records/<rid>/steps")
def record_step(rid):
    gates.begin(["FieldTech", "Dispatcher"])
    record = gates.fetch_path("winterization_records", rid)
    body = gates.body_json()
    step = body.get("step_code")
    if step is None:
        fail("ERR_MISSING_REQUIRED_FIELD", "Field 'step_code' is required.")
    if not isinstance(step, str):
        fail("ERR_INVALID_FIELD_TYPE", "Field 'step_code' has the wrong type.")
    if step not in core.WINTERIZATION_STEP_CODES:
        fail("ERR_WINTERIZATION_STEP_INVALID", "Unknown winterization step code.")

    # ---- G5 ----
    if step == "ALL_REQUIRED":
        check_state("winterization_record", record, ["NOT_STARTED"])
    else:
        check_state("winterization_record", record, ["NOT_STARTED", "PARTIAL", "REOPENED"])
        if step == "THERMOSTAT_SET":
            already = record["thermostat_set_f"] is not None and \
                D(record["thermostat_set_f"]) >= core.WINTERIZATION_MIN_THERMOSTAT_F
        else:
            already = bool(record[STEP_FLAGS[step]])
        if already:
            fail("ERR_STEP_ALREADY_RECORDED", "That step is already recorded as done.")

    # ---- G10 ----
    gates.validate_payload(body, [("step_code", "string", True), ("thermostat_f", "number", False)])
    thermostat = body.get("thermostat_f")
    if step in ("THERMOSTAT_SET", "ALL_REQUIRED") and thermostat is None:
        fail("ERR_WINTERIZATION_STEP_INVALID", "A thermostat step must supply thermostat_f.")
    if step == "ALL_REQUIRED" and D(thermostat) < core.WINTERIZATION_MIN_THERMOSTAT_F:
        fail("ERR_THERMOSTAT_BELOW_MINIMUM", "The thermostat setting is below the minimum.")

    if step == "ALL_REQUIRED":
        record["water_shutoff_done"] = True
        record["lines_drained_done"] = True
        record["valve_tagged_done"] = True
        record["thermostat_set_f"] = thermostat
        _recount(record)
        record["completeness_pct"] = 100.0
        record["status"] = "COMPLETE"
        record["completed_at"] = now()
    else:
        if step == "THERMOSTAT_SET":
            record["thermostat_set_f"] = thermostat
        else:
            record[STEP_FLAGS[step]] = True
        done = _recount(record)
        if done >= core.WINTERIZATION_REQUIRED_STEP_COUNT:
            record["status"] = "COMPLETE"
            record["completeness_pct"] = 100.0
            record["completed_at"] = now()
        elif done >= 1:
            record["status"] = "PARTIAL"
    touch(record)

    prop = get("properties", record["property_id"])
    if prop is not None:
        calc.rederive_winterization_pct(prop)
        calc.rederive_risk(prop)
        touch(prop)
    return core.ok(serialize.winterization_record(record))


@bp.post("/property-care/winterization-records/<rid>/reopen")
def reopen_record(rid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    record = gates.fetch_path("winterization_records", rid)
    check_state("winterization_record", record, ["COMPLETE"])
    body = gates.body_json()
    gates.validate_payload(body, [("reopen_reason", "string", True)])
    record["status"] = "REOPENED"
    record["reopen_reason"] = body["reopen_reason"]
    record["water_shutoff_done"] = False
    record["lines_drained_done"] = False
    record["valve_tagged_done"] = False
    record["thermostat_set_f"] = None
    record["completed_at"] = None
    record["completed_step_count"] = 0
    record["completeness_pct"] = 0.0
    touch(record)
    prop = get("properties", record["property_id"])
    if prop is not None:
        calc.rederive_winterization_pct(prop)
        calc.rederive_risk(prop)
        touch(prop)
    return core.ok(serialize.winterization_record(record))


# ---------------------------------------------------------------------------
# Rental turnovers
# ---------------------------------------------------------------------------
TURNOVER_READ_ROLES = ["Dispatcher", "AccountManager", "PlatformAdmin", "FieldTech", "Auditor", "Owner"]

TURNOVER_SUCCESSORS = {
    "BOOKED": ["CHECKOUT", "CANCELLED"],
    "CHECKOUT": ["CLEANING"],
    "CLEANING": ["INSPECTION"],
    "INSPECTION": ["READY"],
    "READY": ["CHECKIN"],
}


@bp.post("/property-care/properties/<pid>/rental-turnovers")
def create_turnover(pid):
    gates.begin(["Dispatcher", "AccountManager", "PlatformAdmin"])
    prop = gates.fetch_path("properties", pid)
    body = gates.body_json()
    gates.validate_payload(body, [
        ("checkout_at", "datetime", True),
        ("checkin_at", "datetime", True),
        ("guest_reference", "string", True),
    ])
    gates.check_interval(body, "checkout_at", "checkin_at")
    turnover = new_row(
        "rental_turnovers",
        property_id=prop["id"],
        checkout_at=parse_iso(body["checkout_at"]),
        checkin_at=parse_iso(body["checkin_at"]),
        clean_started_at=None, inspect_started_at=None, ready_at=None,
        status="BOOKED", reclean_attempt_count=0, absorbed_visit_id=None,
        guest_reference=body["guest_reference"],
    )
    return core.ok(serialize.rental_turnover(turnover), 201)


@bp.get("/property-care/rental-turnovers")
def list_turnovers():
    gates.begin(TURNOVER_READ_ROLES)
    return gates.list_response("rental_turnovers", ["property_id", "status"],
                               serialize.rental_turnover)


@bp.get("/property-care/rental-turnovers/<tid>")
def read_turnover(tid):
    role, user_id = gates.begin(TURNOVER_READ_ROLES)
    turnover = gates.fetch_path("rental_turnovers", tid)
    prop = get("properties", turnover["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    return core.ok(serialize.rental_turnover(turnover))


@bp.post("/property-care/rental-turnovers/<tid>/advance")
def advance_turnover(tid):
    gates.begin(["Dispatcher", "FieldTech", "PlatformAdmin"])
    turnover = gates.fetch_path("rental_turnovers", tid)
    body = gates.body_json()
    to_status = gates.enum_discriminator(body, "to_status", core.TURNOVER_STATUSES)
    if turnover["status"] in core.TERMINAL_STATES["rental_turnover"]:
        fail("ERR_ALREADY_TERMINAL", "The turnover is already terminal.")
    if to_status not in TURNOVER_SUCCESSORS.get(turnover["status"], []):
        fail("ERR_TURNOVER_STAGE_INVALID", "That stage is not the declared successor.")
    prop = get("properties", turnover["property_id"])
    if to_status == "CHECKOUT" and now() < turnover["checkout_at"]:
        fail("ERR_INVALID_STATE_TRANSITION", "The checkout instant has not been reached.")
    if to_status == "CHECKIN" and now() < turnover["checkin_at"]:
        fail("ERR_INVALID_STATE_TRANSITION", "The check-in instant has not been reached.")

    turnover["status"] = to_status
    if to_status == "CHECKOUT":
        if prop is not None and prop["occupancy_state"] == "RENTAL_OCCUPIED":
            prop["occupancy_state"] = "VACANT"
            calc.rederive_risk(prop)
            touch(prop)
    elif to_status == "CLEANING":
        turnover["clean_started_at"] = now()
    elif to_status == "INSPECTION":
        turnover["inspect_started_at"] = now()
    elif to_status == "READY":
        turnover["ready_at"] = now()
    elif to_status == "CHECKIN":
        if prop is not None and prop["occupancy_state"] == "VACANT":
            prop["occupancy_state"] = "RENTAL_OCCUPIED"
            touch(prop)
    elif to_status == "CANCELLED":
        for v in calc.children("visits", "rental_turnover_id", turnover["id"]):
            if v["status"] == "SCHEDULED":
                v["rental_turnover_id"] = None
                touch(v)
    touch(turnover)
    return core.ok(serialize.rental_turnover(turnover))


@bp.post("/property-care/rental-turnovers/<tid>/fail-inspection")
def fail_inspection(tid):
    gates.begin(["FieldTech", "Dispatcher"])
    turnover = gates.fetch_path("rental_turnovers", tid)
    check_state("rental_turnover", turnover, ["INSPECTION"])
    if turnover["reclean_attempt_count"] >= core.TURNOVER_MAX_RECLEAN_ATTEMPTS:
        fail("ERR_RECLEAN_ATTEMPTS_EXHAUSTED", "The re-clean attempt cap has been reached.")
    turnover["status"] = "CLEANING"
    turnover["reclean_attempt_count"] += 1
    turnover["inspect_started_at"] = None
    touch(turnover)
    return core.ok(serialize.rental_turnover(turnover))


# ---------------------------------------------------------------------------
# Mail holds
# ---------------------------------------------------------------------------
MAIL_READ_ROLES = ["Dispatcher", "AccountManager", "Owner", "PlatformAdmin", "FieldTech", "Auditor"]


@bp.post("/property-care/properties/<pid>/mail-holds")
def create_mail_hold(pid):
    role, user_id = gates.begin(["Dispatcher", "AccountManager", "Owner", "PlatformAdmin"])
    prop = gates.fetch_path("properties", pid)
    gates.owner_scope(role, user_id, prop["owner_id"])
    body = gates.body_json()
    gates.validate_payload(body, [
        ("start_on", "datetime", True),
        ("end_on", "datetime", True),
        ("forwarding_address", "string", False),
    ])
    gates.check_interval(body, "start_on", "end_on")
    start_on = parse_iso(body["start_on"])
    end_on = parse_iso(body["end_on"])
    hold_days = calc.whole_days((end_on - start_on).total_seconds())
    if hold_days > core.MAIL_HOLD_MAX_DAYS:
        fail("ERR_HOLD_TOO_LONG", "The hold exceeds the maximum length.")
    hold = new_row(
        "mail_holds",
        property_id=prop["id"], start_on=start_on, end_on=end_on, hold_days=hold_days,
        extension_count=0, package_count=0, overflow_events=0, status="REQUESTED",
        forwarding_address=body.get("forwarding_address"), disposition_fee_cents=0,
    )
    return core.ok(serialize.mail_hold(hold), 201)


@bp.get("/property-care/mail-holds")
def list_mail_holds():
    gates.begin(MAIL_READ_ROLES)
    return gates.list_response("mail_holds", ["property_id", "status"], serialize.mail_hold)


@bp.get("/property-care/mail-holds/<hid>")
def read_mail_hold(hid):
    role, user_id = gates.begin(MAIL_READ_ROLES)
    hold = gates.fetch_path("mail_holds", hid)
    prop = get("properties", hold["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    return core.ok(serialize.mail_hold(hold))


@bp.post("/property-care/mail-holds/<hid>/log-packages")
def log_packages(hid):
    gates.begin(["FieldTech", "Dispatcher"])
    hold = gates.fetch_path("mail_holds", hid)
    check_state("mail_hold", hold, ["REQUESTED", "ACTIVE", "OVERFLOW"])
    body = gates.body_json()
    if now() < hold["start_on"]:
        fail("ERR_MAIL_HOLD_NOT_STARTED", "The hold has not started yet.")
    delta = body.get("package_delta")
    if hold["status"] == "REQUESTED" and isinstance(delta, int) and not isinstance(delta, bool) \
            and delta != 0:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A requested hold is activated by a package_delta of exactly zero.")
    gates.validate_payload(body, [("package_delta", "integer", True)])
    delta = body["package_delta"]

    new_count = max(0, hold["package_count"] + delta)
    hold["package_count"] = new_count
    if hold["status"] == "REQUESTED":
        hold["status"] = "ACTIVE"
    elif new_count >= core.PACKAGE_OVERFLOW_THRESHOLD_COUNT:
        if hold["status"] == "ACTIVE":
            hold["status"] = "OVERFLOW"
            hold["overflow_events"] += 1
    else:
        hold["status"] = "ACTIVE"
    touch(hold)
    return core.ok(serialize.mail_hold(hold))


@bp.post("/property-care/mail-holds/<hid>/forward")
def forward_hold(hid):
    gates.begin(["Dispatcher", "AccountManager"])
    hold = gates.fetch_path("mail_holds", hid)
    check_state("mail_hold", hold, ["ACTIVE", "OVERFLOW"])
    if hold.get("forwarding_address") is None:
        fail("ERR_FORWARDING_ADDRESS_MISSING", "The hold has no forwarding address.")
    source = hold["status"]
    hold["disposition_fee_cents"] = calc.mail_disposition_fee_forward(hold)
    hold["status"] = "FORWARDED"
    touch(hold)
    if source == "ACTIVE":
        invoice = calc.property_draft_invoice(hold["property_id"])
        if invoice is not None:
            calc.append_invoice_line(invoice, "MAIL_DISPOSITION", "Mail forwarding",
                                     hold["disposition_fee_cents"], taxable=True,
                                     mail_hold_id=hold["id"])
    return core.ok(serialize.mail_hold(hold))


@bp.post("/property-care/mail-holds/<hid>/extend")
def extend_hold(hid):
    role, user_id = gates.begin(["Dispatcher", "AccountManager", "Owner"])
    hold = gates.fetch_path("mail_holds", hid)
    prop = get("properties", hold["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    if hold["status"] in core.TERMINAL_STATES["mail_hold"]:
        fail("ERR_ALREADY_TERMINAL", "The mail hold is already terminal.")
    if hold["extension_count"] >= core.MAIL_HOLD_MAX_EXTENSIONS:
        fail("ERR_HOLD_EXTENSIONS_EXHAUSTED", "The extension cap has been reached.")
    new_end = hold["end_on"] + timedelta(days=core.MAIL_HOLD_EXTENSION_DAYS)
    new_days = calc.whole_days((new_end - hold["start_on"]).total_seconds())
    if new_days > core.MAIL_HOLD_ABSOLUTE_MAX_DAYS:
        fail("ERR_HOLD_TOO_LONG", "The extension would exceed the absolute maximum length.")
    hold["end_on"] = new_end
    hold["hold_days"] = new_days
    hold["extension_count"] += 1
    hold["disposition_fee_cents"] = calc.mail_disposition_fee_extension(hold)
    touch(hold)
    return core.ok(serialize.mail_hold(hold))


@bp.post("/property-care/mail-holds/<hid>/release")
def release_hold(hid):
    role, user_id = gates.begin(["Dispatcher", "AccountManager", "Owner"])
    hold = gates.fetch_path("mail_holds", hid)
    prop = get("properties", hold["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    check_state("mail_hold", hold, ["ACTIVE"])
    if hold["package_count"] != 0:
        fail("ERR_PACKAGES_OUTSTANDING", "Packages are still outstanding.")
    hold["status"] = "RELEASED"
    touch(hold)
    return core.ok(serialize.mail_hold(hold))
