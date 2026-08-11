from flask import Blueprint

import calc
import core
import gates
import serialize
from core import fail, new_row, now, touch

bp = Blueprint("properties", __name__)

CREATE_SPEC = [
    ("owner_id", "string", True),
    ("label", "string", True),
    ("address_line", "string", True),
    ("state_code", "string", True),
    ("travel_distance_miles", "number", True),
    ("freeze_setpoint_f", "number", False),
    ("rental_program_enrolled", "boolean", False),
]

PATCH_SPEC = [
    ("label", "string", False),
    ("travel_distance_miles", "number", False),
    ("freeze_setpoint_f", "number", False),
    ("rental_program_enrolled", "boolean", False),
]

FILTERS = ["owner_id", "state_code", "seasonal_state", "occupancy_state"]


@bp.post("/property-care/properties")
def create_property():
    gates.begin(["PlatformAdmin", "AccountManager"])
    body = gates.body_json()
    # G3 rung 8 - the body owner_id must resolve before the payload gate runs
    if isinstance(body.get("owner_id"), str):
        gates.fetch_body_fk("owners", body["owner_id"], "ERR_OWNER_NOT_FOUND")
    gates.validate_payload(body, CREATE_SPEC)
    gates.fetch_body_fk("owners", body["owner_id"], "ERR_OWNER_NOT_FOUND")
    prop = new_row(
        "properties",
        owner_id=body["owner_id"],
        label=body["label"],
        address_line=body["address_line"],
        state_code=body["state_code"],
        travel_distance_miles=body["travel_distance_miles"],
        travel_zone=calc.travel_zone_assignment(body["travel_distance_miles"]),
        seasonal_state="OPEN",
        occupancy_state="VACANT",
        freeze_setpoint_f=body.get("freeze_setpoint_f", core.FREEZE_SETPOINT_DEFAULT_F),
        last_interior_temp_f=None,
        last_temp_reading_at=None,
        freeze_risk_score=0.0,
        risk_posture="NORMAL",
        winterization_completeness_pct=0.0,
        false_alarm_count_window=0,
        open_critical_finding_count=0,
        storm_hold_flag=False,
        rental_program_enrolled=body.get("rental_program_enrolled", False),
    )
    # registration is declared to run both derivations (F11)
    calc.rederive_risk(prop)
    return core.ok(serialize.prop(prop), 201)


@bp.get("/property-care/properties")
def list_properties():
    gates.begin(["PlatformAdmin", "AccountManager", "Dispatcher", "FieldTech",
                 "StormCoordinator", "Auditor", "Owner"])
    return gates.list_response("properties", FILTERS, serialize.prop)


@bp.get("/property-care/properties/<pid>")
def read_property(pid):
    role, user_id = gates.begin(["PlatformAdmin", "AccountManager", "Dispatcher", "FieldTech",
                                 "StormCoordinator", "Auditor", "Owner", "Vendor"])
    prop = gates.fetch_path("properties", pid)
    gates.owner_scope(role, user_id, prop["owner_id"])
    return core.ok(serialize.prop(prop))


@bp.patch("/property-care/properties/<pid>")
def patch_property(pid):
    gates.begin(["PlatformAdmin", "AccountManager", "Dispatcher"])
    prop = gates.fetch_path("properties", pid)
    body = gates.body_json()
    gates.validate_payload(body, PATCH_SPEC)
    for field in ("label", "travel_distance_miles", "freeze_setpoint_f", "rental_program_enrolled"):
        if field in body:
            prop[field] = body[field]
    if "travel_distance_miles" in body:
        prop["travel_zone"] = calc.travel_zone_assignment(prop["travel_distance_miles"])
    calc.rederive_risk(prop)
    touch(prop)
    return core.ok(serialize.prop(prop))


@bp.get("/property-care/properties/<pid>/risk-posture")
def risk_posture(pid):
    role, user_id = gates.begin(["PlatformAdmin", "AccountManager", "Dispatcher", "FieldTech",
                                 "StormCoordinator", "Auditor", "Owner"])
    prop = gates.fetch_path("properties", pid)
    gates.owner_scope(role, user_id, prop["owner_id"])
    return core.ok({
        "freeze_risk_score": prop["freeze_risk_score"],
        "risk_posture": prop["risk_posture"],
        "winterization_completeness_pct": prop["winterization_completeness_pct"],
        "open_critical_finding_count": calc.open_critical_finding_count(prop["id"]),
        "false_alarm_count_window": calc.false_alarm_count_window(prop["id"]),
        "last_interior_temp_f": prop["last_interior_temp_f"],
    })


SEASONAL_EDGES = {
    "BEGIN_CLOSE": ("OPEN", "CLOSING"),
    "ABORT_CLOSE": ("CLOSING", "OPEN"),
    "COMPLETE_WINTERIZATION": ("CLOSING", "WINTERIZED"),
    "BEGIN_OPEN": ("WINTERIZED", "OPENING"),
    "COMPLETE_OPEN": ("OPENING", "OPEN"),
}


@bp.post("/property-care/properties/<pid>/seasonal-transitions")
def seasonal_transition(pid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    prop = gates.fetch_path("properties", pid)
    body = gates.body_json()
    action = gates.enum_discriminator(body, "action", core.SEASONAL_ACTIONS)

    source, target = SEASONAL_EDGES[action]
    # ---- G5 target state (the seasonal axis has no terminal state) ----
    if prop["seasonal_state"] != source:
        fail("ERR_INVALID_STATE_TRANSITION",
             "Seasonal state '%s' does not permit %s." % (prop["seasonal_state"], action))
    if action in ("BEGIN_CLOSE", "COMPLETE_WINTERIZATION") and prop["occupancy_state"] != "VACANT":
        fail("ERR_INVALID_STATE_TRANSITION", "The property must be VACANT for %s." % action)
    newest = calc.newest_winterization_record(pid)
    if action == "ABORT_CLOSE":
        if newest is None or newest["status"] not in ("NOT_STARTED", "PARTIAL"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The newest winterization record must be NOT_STARTED or PARTIAL.")

    # ---- G6 seasonal band ----
    if prop["storm_hold_flag"]:
        fail("ERR_PROPERTY_HAS_OPEN_STORM_HOLD", "An open storm response holds this property.")
    if action == "BEGIN_CLOSE":
        blocking = {"CHECKOUT", "CLEANING", "INSPECTION", "READY"}
        if any(t["status"] in blocking for t in calc.children("rental_turnovers", "property_id", pid)):
            fail("ERR_TURNOVER_IN_FLIGHT", "A rental turnover is still in flight.")
    if action == "COMPLETE_WINTERIZATION":
        if newest is None or newest["status"] != "COMPLETE":
            fail("ERR_WINTERIZATION_INCOMPLETE", "The newest winterization record is not COMPLETE.")
    if action == "BEGIN_OPEN":
        for key in calc.children("key_assets", "property_id", pid):
            for issuance in calc.children("key_issuances", "key_asset_id", key["id"]):
                if issuance["status"] in ("OVERDUE", "LOST"):
                    fail("ERR_KEY_CUSTODY_BLOCKS_OPEN", "A key issuance is OVERDUE or LOST.")
    if action == "COMPLETE_OPEN":
        anchor = newest["created_at"] if newest else None
        qualifies = False
        for v in calc.children("visits", "property_id", pid):
            if v["visit_type"] == "SEASONAL_OPEN" and v["status"] == "COMPLETED" and \
                    v["completed_at"] is not None and (anchor is None or v["completed_at"] >= anchor):
                qualifies = True
                break
        if not qualifies:
            fail("ERR_NO_SEASONAL_OPEN_VISIT", "No qualifying completed SEASONAL_OPEN visit exists.")

    # ---- effects ----
    prop["seasonal_state"] = target
    if action == "BEGIN_CLOSE":
        new_row(
            "winterization_records",
            property_id=pid, visit_id=None,
            water_shutoff_done=False, lines_drained_done=False, thermostat_set_f=None,
            valve_tagged_done=False, antifreeze_added_done=False,
            completed_step_count=0, completeness_pct=0.0,
            status="NOT_STARTED", completed_at=None, reopen_reason=None,
        )
    elif action == "ABORT_CLOSE":
        newest["status"] = "REOPENED"
        newest["reopen_reason"] = "SPRING_OPEN"
        touch(newest)
        calc.rederive_winterization_pct(prop)
    elif action == "COMPLETE_WINTERIZATION":
        prop["winterization_completeness_pct"] = 100.0
        calc.rederive_risk(prop)
    elif action == "BEGIN_OPEN":
        if newest is not None and newest["status"] == "COMPLETE":
            newest["status"] = "REOPENED"
            newest["reopen_reason"] = "SPRING_OPEN"
            newest["water_shutoff_done"] = False
            newest["lines_drained_done"] = False
            newest["valve_tagged_done"] = False
            newest["thermostat_set_f"] = None
            newest["completed_at"] = None
            newest["completed_step_count"] = 0
            newest["completeness_pct"] = 0.0
            touch(newest)
        calc.rederive_winterization_pct(prop)
        calc.rederive_risk(prop)
    touch(prop)
    return core.ok(serialize.prop(prop))


OCCUPANCY_EDGES = {
    ("VACANT", "OWNER_IN_RESIDENCE"),
    ("OWNER_IN_RESIDENCE", "VACANT"),
    ("VACANT", "RENTAL_OCCUPIED"),
    ("RENTAL_OCCUPIED", "VACANT"),
}


@bp.post("/property-care/properties/<pid>/occupancy-transitions")
def occupancy_transition(pid):
    role, user_id = gates.begin(["Owner", "Dispatcher", "PlatformAdmin"])
    prop = gates.fetch_path("properties", pid)
    gates.owner_scope(role, user_id, prop["owner_id"])
    body = gates.body_json()
    to_state = gates.enum_discriminator(body, "to_state", core.OCCUPANCY_STATES)

    # ---- G5 ----
    if (prop["occupancy_state"], to_state) not in OCCUPANCY_EDGES:
        fail("ERR_INVALID_STATE_TRANSITION",
             "Occupancy '%s' cannot move to '%s'." % (prop["occupancy_state"], to_state))
    # ---- G7 ----
    if to_state == "RENTAL_OCCUPIED":
        if not prop["rental_program_enrolled"] or prop["seasonal_state"] != "OPEN":
            fail("ERR_RENTAL_NOT_ENROLLED",
                 "The property is not enrolled in the rental programme or is not seasonally OPEN.")
    if to_state == "OWNER_IN_RESIDENCE":
        if prop["seasonal_state"] not in ("OPEN", "OPENING"):
            fail("ERR_SEASONAL_STATE_FORBIDS_OCCUPANCY",
                 "Seasonal state '%s' forbids owner residence." % prop["seasonal_state"])

    previous = prop["occupancy_state"]
    prop["occupancy_state"] = to_state
    if to_state == "OWNER_IN_RESIDENCE":
        for v in calc.children("visits", "property_id", pid):
            if v["status"] == "SCHEDULED" and v["visit_type"] == "ROUTINE_WATCH":
                v["status"] = "DEFERRED"
                v["defer_reason"] = "OWNER_IN_RESIDENCE"
                v["deferral_count"] += 1
                touch(v)
    if to_state == "VACANT" and previous in ("OWNER_IN_RESIDENCE", "RENTAL_OCCUPIED"):
        calc.rederive_risk(prop)
    touch(prop)
    return core.ok(serialize.prop(prop))
