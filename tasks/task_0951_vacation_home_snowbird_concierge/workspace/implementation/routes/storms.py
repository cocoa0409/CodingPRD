from flask import Blueprint

import calc
import core
import gates
import ops
import serialize
from core import fail, get, new_row, now, parse_iso, touch
from gates import check_state

bp = Blueprint("storms", __name__)

EVENT_READ_ROLES = ["StormCoordinator", "PlatformAdmin", "Dispatcher", "AccountManager",
                    "Auditor", "FieldTech"]
RESPONSE_READ_ROLES = ["StormCoordinator", "Dispatcher", "PlatformAdmin", "AccountManager",
                       "FieldTech", "Auditor", "Owner"]

ADVISORY_EDGES = {
    ("FORECAST", "WATCH"),
    ("WATCH", "WARNING"),
    ("WARNING", "WATCH"),
    ("WARNING", "IMMINENT"),
}


@bp.post("/property-care/storm-events")
def create_event():
    gates.begin(["StormCoordinator", "PlatformAdmin"])
    body = gates.body_json()
    gates.validate_payload(body, [
        ("name", "string", True),
        ("region_state_code", "string", True),
        ("landfall_eta_at", "datetime", True),
    ])
    eta = parse_iso(body["landfall_eta_at"])
    if eta <= now():
        fail("ERR_LANDFALL_ETA_IN_PAST", "The landfall ETA is already in the past.")
    event = new_row(
        "storm_events",
        name=body["name"], region_state_code=body["region_state_code"], landfall_eta_at=eta,
        status="FORECAST", landfall_recorded_at=None, all_clear_at=None, downgrade_count=0,
    )
    return core.ok(serialize.storm_event(event), 201)


@bp.get("/property-care/storm-events")
def list_events():
    gates.begin(EVENT_READ_ROLES)
    return gates.list_response("storm_events", ["region_state_code", "status"],
                               serialize.storm_event)


@bp.get("/property-care/storm-events/<eid>")
def read_event(eid):
    gates.begin(EVENT_READ_ROLES + ["Owner"])
    event = gates.fetch_path("storm_events", eid)
    return core.ok(serialize.storm_event(event))


@bp.post("/property-care/storm-events/<eid>/advisory")
def advisory(eid):
    gates.begin(["StormCoordinator"])
    event = gates.fetch_path("storm_events", eid)
    body = gates.body_json()
    to_status = gates.enum_discriminator(body, "to_status", core.STORM_EVENT_STATUSES)
    check_state("storm_event", event, ["FORECAST", "WATCH", "WARNING", "IMMINENT"])
    if (event["status"], to_status) not in ADVISORY_EDGES:
        fail("ERR_INVALID_STATE_TRANSITION",
             "Advisory '%s' cannot move to '%s'." % (event["status"], to_status))
    if not now() < event["landfall_eta_at"]:
        fail("ERR_INVALID_STATE_TRANSITION", "The landfall ETA has already passed.")
    if event["status"] == "WARNING" and to_status == "WATCH":
        event["downgrade_count"] += 1
    event["status"] = to_status
    touch(event)
    return core.ok(serialize.storm_event(event))


@bp.post("/property-care/storm-events/<eid>/landfall")
def landfall(eid):
    gates.begin(["StormCoordinator"])
    event = gates.fetch_path("storm_events", eid)
    check_state("storm_event", event, ["IMMINENT", "ALL_CLEAR"])
    secondary = event["status"] == "ALL_CLEAR"
    event["status"] = "LANDFALL"
    event["landfall_recorded_at"] = now()
    if secondary:
        event["all_clear_at"] = None
    else:
        for r in calc.children("storm_responses", "storm_event_id", event["id"]):
            if r["status"] == "SECURE_SWEEP_SCHEDULED" and r.get("secured_at") is None and \
                    r["secure_sweep_deadline_at"] is not None and \
                    r["secure_sweep_deadline_at"] < now():
                r["status"] = "MISSED_DEADLINE"
                touch(r)
        for r in calc.children("storm_responses", "storm_event_id", event["id"]):
            if r["status"] in ("SECURED", "SECURED_LATE", "MISSED_DEADLINE"):
                r["status"] = "AWAITING_ALL_CLEAR"
                touch(r)
    touch(event)
    return core.ok(serialize.storm_event(event))


@bp.post("/property-care/storm-events/<eid>/all-clear")
def all_clear(eid):
    gates.begin(["StormCoordinator"])
    event = gates.fetch_path("storm_events", eid)
    check_state("storm_event", event, ["LANDFALL"])
    event["status"] = "ALL_CLEAR"
    event["all_clear_at"] = now()
    deadline = calc.response_deadline_post_storm(event)
    for r in calc.children("storm_responses", "storm_event_id", event["id"]):
        if r["status"] == "AWAITING_ALL_CLEAR":
            r["status"] = "ASSESSMENT_DUE"
            r["assessment_deadline_at"] = deadline
            touch(r)
    touch(event)
    return core.ok(serialize.storm_event(event))


@bp.post("/property-care/storm-events/<eid>/close")
def close_event(eid):
    gates.begin(["StormCoordinator"])
    event = gates.fetch_path("storm_events", eid)
    check_state("storm_event", event, ["ALL_CLEAR"])
    responses = calc.children("storm_responses", "storm_event_id", event["id"])
    for r in responses:
        if r["status"] not in ("ASSESSED", "CLOSED"):
            fail("ERR_STORM_RESPONSES_OPEN", "A storm response is still open.")
    event["status"] = "CLOSED"
    touch(event)
    for r in responses:
        if r["status"] == "ASSESSED":
            r["status"] = "CLOSED"
            touch(r)
    for r in responses:
        prop = get("properties", r["property_id"])
        if prop is None:
            continue
        before = prop["storm_hold_flag"]
        calc.rederive_storm_hold(prop)
        if prop["storm_hold_flag"] != before:
            touch(prop)
    return core.ok(serialize.storm_event(event))


# ---------------------------------------------------------------------------
# Storm responses
# ---------------------------------------------------------------------------
@bp.post("/property-care/storm-events/<eid>/responses")
def create_response(eid):
    gates.begin(["StormCoordinator", "Dispatcher"])
    event = gates.fetch_path("storm_events", eid)
    body = gates.body_json()
    if isinstance(body.get("property_id"), str):
        gates.fetch_body_fk("properties", body["property_id"], "ERR_PROPERTY_NOT_FOUND")
    gates.validate_payload(body, [("property_id", "string", True)])
    prop = gates.fetch_body_fk("properties", body["property_id"], "ERR_PROPERTY_NOT_FOUND")
    sub = None
    for candidate in calc.children("subscriptions", "property_id", prop["id"]):
        if candidate["status"] in ("ACTIVE", "PAUSED", "DELINQUENT"):
            sub = candidate
    response = new_row(
        "storm_responses",
        storm_event_id=event["id"], property_id=prop["id"],
        subscription_id=sub["id"] if sub else None,
        secure_sweep_deadline_at=None, secure_sweep_visit_id=None, secured_at=None,
        sweep_on_time=False, guarantee_credit_cents=0, assessment_deadline_at=None,
        assessed_at=None, swept_by_user_id=None, assessed_by_user_id=None, damage_level=None,
        surcharge_pct_at_dispatch=0.0, status="PENDING",
    )
    return core.ok(serialize.storm_response(response), 201)


@bp.get("/property-care/storm-responses")
def list_responses():
    gates.begin(RESPONSE_READ_ROLES)
    return gates.list_response("storm_responses",
                               ["storm_event_id", "property_id", "subscription_id", "status"],
                               serialize.storm_response)


@bp.get("/property-care/storm-responses/<rid>")
def read_response(rid):
    role, user_id = gates.begin(RESPONSE_READ_ROLES)
    response = gates.fetch_path("storm_responses", rid)
    prop = get("properties", response["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    return core.ok(serialize.storm_response(response))


@bp.post("/property-care/storm-responses/<rid>/schedule-sweep")
def schedule_sweep(rid):
    gates.begin(["StormCoordinator", "Dispatcher"])
    response = gates.fetch_path("storm_responses", rid)
    body = gates.body_json()
    template = None
    if isinstance(body.get("checklist_template_id"), str):
        template = gates.fetch_body_fk("checklist_templates", body["checklist_template_id"],
                                       "ERR_TEMPLATE_NOT_FOUND")
    # ---- G5 ----
    check_state("storm_response", response, ["PENDING"])
    event = get("storm_events", response["storm_event_id"])
    if event is None or event["status"] not in ("WATCH", "WARNING", "IMMINENT"):
        fail("ERR_INVALID_STATE_TRANSITION", "The storm event is not in an advisory state.")
    prop = get("properties", response["property_id"])
    if prop["state_code"] != event["region_state_code"]:
        fail("ERR_STORM_REGION_MISMATCH", "The property lies outside the storm region.")
    # ---- G6 / G7 for the STORM_SECURE visit this creates ----
    from routes.visits import occupancy_gate, seasonal_gate
    seasonal_gate(prop, "STORM_SECURE")
    occupancy_gate(prop, "STORM_SECURE")
    # ---- G10 ----
    gates.validate_payload(body, [
        ("checklist_template_id", "string", True),
        ("scheduled_start_at", "datetime", True),
    ])
    template = gates.fetch_body_fk("checklist_templates", body["checklist_template_id"],
                                   "ERR_TEMPLATE_NOT_FOUND")

    deadline = calc.response_deadline_pre_storm(event)
    response["secure_sweep_deadline_at"] = deadline
    visit = ops.create_visit(prop["id"], template["id"], "STORM_SECURE", "STORM",
                             parse_iso(body["scheduled_start_at"]), deadline,
                             storm_response_id=response["id"])
    response["secure_sweep_visit_id"] = visit["id"]
    response["status"] = "SECURE_SWEEP_SCHEDULED"
    touch(response)
    if not prop["storm_hold_flag"]:
        prop["storm_hold_flag"] = True
        touch(prop)
    return core.ok(serialize.storm_response(response))


@bp.post("/property-care/storm-responses/<rid>/assessments")
def assessment(rid):
    role, user_id = gates.begin(["FieldTech", "StormCoordinator"])
    response = gates.fetch_path("storm_responses", rid)
    # ---- G2 rung 6 segregation of duties ----
    if response.get("swept_by_user_id") is not None and user_id == response["swept_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The assessment signer must differ from the secure-sweep technician.")
    body = gates.body_json()
    # ---- G4 (F1: no catalogue code exists; the parallel 412 identifier is used) ----
    expected = body.get("expected_storm_response_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != response["version"]:
            fail("ERR_STALE_STORM_RESPONSE_VERSION", "The storm response has been modified.")
    # ---- G5 ----
    check_state("storm_response", response, ["ASSESSMENT_DUE"])
    event = get("storm_events", response["storm_event_id"])
    if event is None or event["status"] != "ALL_CLEAR":
        fail("ERR_STORM_NOT_ALL_CLEAR", "The storm event is not in ALL_CLEAR.")
    # ---- G10 ----
    gates.validate_payload(body, [
        ("damage_level", "string", True),
        ("expected_storm_response_version", "integer", True),
    ])
    response["status"] = "ASSESSED"
    response["assessed_at"] = now()
    response["assessed_by_user_id"] = user_id
    response["damage_level"] = body["damage_level"]
    touch(response)
    return core.ok(serialize.storm_response(response))


@bp.post("/property-care/storm-responses/<rid>/close")
def close_response(rid):
    gates.begin(["StormCoordinator"])
    response = gates.fetch_path("storm_responses", rid)
    check_state("storm_response", response, ["ASSESSED"])
    response["status"] = "CLOSED"
    touch(response)
    prop = get("properties", response["property_id"])
    if prop is not None:
        before = prop["storm_hold_flag"]
        calc.rederive_storm_hold(prop)
        if prop["storm_hold_flag"] != before:
            touch(prop)
    return core.ok(serialize.storm_response(response))
