from datetime import timedelta

from flask import Blueprint

import calc
import core
import gates
import ops
import serialize
from core import D, fail, get, new_row, now, parse_iso, rhu_cents, touch
from gates import check_state

bp = Blueprint("visits", __name__)

FILTERS = ["property_id", "checklist_template_id", "away_period_id", "storm_response_id",
           "rental_turnover_id", "billing_cycle_id", "status", "visit_type"]

CREATE_SPEC = [
    ("property_id", "string", True),
    ("checklist_template_id", "string", True),
    ("visit_type", "string", True),
    ("trigger_source", "string", True),
    ("scheduled_start_at", "datetime", True),
    ("scheduled_end_at", "datetime", True),
    ("away_period_id", "string", False),
    ("storm_response_id", "string", False),
    ("rental_turnover_id", "string", False),
]


def seasonal_gate(prop, visit_type):
    """G6 rungs 31-33."""
    if visit_type == "SEASONAL_CLOSE" and prop["seasonal_state"] != "CLOSING":
        fail("ERR_SEASONAL_STATE_FORBIDS_VISIT", "A seasonal close visit requires seasonal_state CLOSING.")
    if visit_type == "SEASONAL_OPEN" and prop["seasonal_state"] != "OPENING":
        fail("ERR_SEASONAL_STATE_FORBIDS_VISIT", "A seasonal open visit requires seasonal_state OPENING.")
    if visit_type == "TURNOVER_INSPECT" and prop["seasonal_state"] != "OPEN":
        fail("ERR_SEASONAL_STATE_FORBIDS_VISIT", "A turnover inspection requires seasonal_state OPEN.")


def occupancy_gate(prop, visit_type):
    """G7 rungs 38-40."""
    if visit_type == "ROUTINE_WATCH" and prop["occupancy_state"] != "VACANT":
        fail("ERR_OCCUPANCY_FORBIDS_VISIT", "A routine watch requires a VACANT property.")
    if visit_type == "TURNOVER_INSPECT" and prop["occupancy_state"] not in ("VACANT", "CONTRACTOR_ONSITE"):
        fail("ERR_OCCUPANCY_FORBIDS_VISIT", "A turnover inspection requires VACANT or CONTRACTOR_ONSITE.")
    if visit_type == "STORM_SECURE" and prop["occupancy_state"] == "RENTAL_OCCUPIED":
        fail("ERR_OCCUPANCY_FORBIDS_VISIT", "A storm secure sweep may not run while rental-occupied.")


@bp.post("/property-care/visits")
def create_visit():
    role, user_id = gates.begin(["Dispatcher", "AccountManager", "PlatformAdmin", "Owner",
                                 "StormCoordinator"])
    body = gates.body_json()
    # ---- G3 existence ----
    prop = None
    if isinstance(body.get("property_id"), str):
        prop = gates.fetch_body_fk("properties", body["property_id"], "ERR_PROPERTY_NOT_FOUND")
    template = None
    if isinstance(body.get("checklist_template_id"), str):
        template = gates.fetch_body_fk("checklist_templates", body["checklist_template_id"],
                                       "ERR_TEMPLATE_NOT_FOUND")
    if prop is not None:
        gates.owner_scope(role, user_id, prop["owner_id"])
    gates.resolve_optional_fks(body, ["away_period_id", "storm_response_id", "rental_turnover_id"])
    if prop is None or template is None:
        gates.validate_payload(body, CREATE_SPEC)
        prop = gates.fetch_body_fk("properties", body["property_id"], "ERR_PROPERTY_NOT_FOUND")
        template = gates.fetch_body_fk("checklist_templates", body["checklist_template_id"],
                                       "ERR_TEMPLATE_NOT_FOUND")

    visit_type = gates.enum_discriminator(body, "visit_type", core.VISIT_TYPES)
    # ---- G6 / G7 ----
    seasonal_gate(prop, visit_type)
    occupancy_gate(prop, visit_type)
    # ---- G9 ----
    sub = calc.property_subscription(prop["id"])
    if sub is None or sub["status"] == "CANCELLED":
        fail("ERR_NO_ACTIVE_SUBSCRIPTION", "The property has no active subscription.")
    if prop["travel_zone"] == "OUT_OF_AREA":
        fail("ERR_PROPERTY_OUT_OF_AREA", "The property is out of the service area.")
    # ---- G10 ----
    gates.validate_payload(body, CREATE_SPEC)
    gates.check_interval(body, "scheduled_start_at", "scheduled_end_at")
    start_at = parse_iso(body["scheduled_start_at"])
    end_at = parse_iso(body["scheduled_end_at"])
    if calc.any_turnover_overlap(prop["id"], start_at, end_at):
        fail("ERR_TURNOVER_WINDOW_OVERLAP", "The window collides with a padded rental turnover.")
    if template["visit_type"] != visit_type or template["status"] != "ACTIVE":
        fail("ERR_TEMPLATE_TYPE_MISMATCH", "The template does not match the submitted visit type.")

    visit = ops.create_visit(
        prop["id"], template["id"], visit_type, body["trigger_source"], start_at, end_at,
        away_period_id=body.get("away_period_id"),
        storm_response_id=body.get("storm_response_id"),
        rental_turnover_id=body.get("rental_turnover_id"),
    )
    return core.ok(serialize.visit(visit), 201)


@bp.get("/property-care/visits")
def list_visits():
    gates.begin(["Dispatcher", "AccountManager", "PlatformAdmin", "FieldTech", "Owner",
                 "StormCoordinator", "Auditor"])
    return gates.list_response("visits", FILTERS, serialize.visit)


@bp.get("/property-care/visits/<vid>")
def read_visit(vid):
    role, user_id = gates.begin(["Dispatcher", "AccountManager", "PlatformAdmin", "FieldTech",
                                 "Owner", "StormCoordinator", "Auditor"])
    visit = gates.fetch_path("visits", vid)
    prop = get("properties", visit["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    return core.ok(serialize.visit(visit))


@bp.post("/property-care/visits/<vid>/depart")
def depart(vid):
    role, user_id = gates.begin(["FieldTech", "Dispatcher"])
    visit = gates.fetch_path("visits", vid)
    check_state("visit", visit, ["SCHEDULED"])
    prop = get("properties", visit["property_id"])
    seasonal_gate(prop, visit["visit_type"])
    occupancy_gate(prop, visit["visit_type"])
    visit["departed_at"] = now()
    visit["tech_user_id"] = user_id
    visit["status"] = "EN_ROUTE"
    touch(visit)
    return core.ok(serialize.visit(visit))


@bp.post("/property-care/visits/<vid>/arrive")
def arrive(vid):
    gates.begin(["FieldTech"])
    visit = gates.fetch_path("visits", vid)
    check_state("visit", visit, ["EN_ROUTE"])
    visit["arrived_at"] = now()
    visit["after_hours_flag"] = calc.after_hours_flag(visit["arrived_at"])
    visit["status"] = "IN_PROGRESS"
    touch(visit)
    return core.ok(serialize.visit(visit))


COMPLETE_SPEC = [
    ("completed_item_codes", "string_array", True),
    ("failed_item_codes", "string_array", True),
    ("interior_temp_f", "number", False),
]


@bp.post("/property-care/visits/<vid>/complete")
def complete(vid):
    role, user_id = gates.begin(["FieldTech"])
    visit = gates.fetch_path("visits", vid)
    # ---- G5 ----
    check_state("visit", visit, ["IN_PROGRESS"])
    if visit.get("departed_at") is None or visit.get("arrived_at") is None:
        fail("ERR_VISIT_NOT_ARRIVED", "The visit has not both departed and arrived.")
    # ---- G10 ----
    body = gates.body_json()
    gates.validate_payload(body, COMPLETE_SPEC)
    template = get("checklist_templates", visit["checklist_template_id"])
    completed = body["completed_item_codes"]
    failed = body["failed_item_codes"]
    item_codes = (template or {}).get("item_codes") or []
    required = (template or {}).get("required_item_count") or 0
    if set(completed) & set(failed):
        fail("ERR_CHECKLIST_MISMATCH", "The checklist arrays overlap.")
    for code in list(completed) + list(failed):
        if code not in item_codes:
            fail("ERR_CHECKLIST_MISMATCH", "Unknown checklist item code '%s'." % code)
    if len(completed) + len(failed) != required:
        fail("ERR_CHECKLIST_MISMATCH", "The checklist arrays do not cover every required item.")

    prop = get("properties", visit["property_id"])
    # ---- hop 1 ----
    visit["completed_item_codes"] = completed
    visit["failed_item_codes"] = failed
    visit["interior_temp_f"] = body.get("interior_temp_f")
    visit["status"] = "COMPLETED"
    visit["completed_at"] = now()
    visit["checklist_completion_pct"] = calc.checklist_completion_pct(visit, template)
    sub = calc.property_subscription(prop["id"])
    cycle = calc.open_cycle(sub)
    visit["billing_cycle_id"] = cycle["id"] if cycle is not None else None

    # ---- the entitlement decision, before any pricing ----
    plan = calc.in_force_plan(sub)
    if calc.entitlement_consumption(visit, cycle, sub, plan):
        visit["entitlement_applied"] = True
        cycle["entitlement_consumed_units"] += 1
        cycle["entitlement_remaining_units"] -= 1
        touch(cycle)
    else:
        visit["entitlement_applied"] = False

    # ---- the price ----
    visit["billable_amount_cents"] = calc.visit_billable_amount(visit, prop)
    touch(visit)

    # ---- hop 2: auto findings from failed critical items ----
    critical = (template or {}).get("critical_item_codes") or []
    auto_findings = []
    for code in item_codes:
        if code in failed and code in critical:
            finding = ops.create_finding(
                prop["id"], visit["id"], code, "CRITICAL",
                (template or {}).get("default_finding_category", "OTHER"),
                "Auto-created from failed critical checklist item " + code,
            )
            auto_findings.append(finding)

    # ---- hops 3-8: the storm-assessment continuation ----
    if visit["visit_type"] == "STORM_ASSESS":
        response = get("storm_responses", visit.get("storm_response_id"))
        storm_event_id = (response or {}).get("storm_event_id")
        for finding in auto_findings:
            finding["status"] = "TRIAGED"
            finding["triaged_at"] = now()
            finding["escalation_score"] = calc.finding_escalation_score(finding, prop)
            wo = ops.create_work_order(
                finding, "STORM_MITIGATION", core.AUTO_STORM_WO_LABOUR_HOURS,
                core.AUTO_STORM_WO_PARTS_CENTS, user_id, storm_event_id=storm_event_id)
            finding["status"] = "WORK_ORDERED"
            ops.submit_work_order(wo, allow_auto_approve=False)
            if calc.pipeline_of(wo) == "STORM" and \
                    wo["total_cents"] <= core.STORM_EMERGENCY_APPROVAL_CEILING_CENTS:
                wo["status"] = "APPROVED"
                wo["approved_by_user_id"] = "system"
                ops.perform_dispatch(wo, now(), now() + timedelta(hours=core.AUTO_DISPATCH_WINDOW_HOURS),
                                     raise_on_empty=False)

    # ---- the remaining completion effects ----
    if visit["interior_temp_f"] is not None:
        prop["last_interior_temp_f"] = visit["interior_temp_f"]
        prop["last_temp_reading_at"] = now()
        calc.rederive_risk(prop)
        touch(prop)
        if calc.temp_breach_detection(visit["interior_temp_f"], prop):
            new_row(
                "security_incidents",
                property_id=prop["id"], visit_id=visit["id"], incident_type="FREEZE_ALARM",
                reported_at=now(), severity="HIGH", status="REPORTED", escalation_count=0,
                false_alarm_sequence=None, false_alarm_fee_cents=0,
                triggered_visit_id=None, resolution_note=None,
            )

    if visit["visit_type"] == "STORM_SECURE":
        ops.settle_storm_sweep(visit, user_id)
        before = prop["storm_hold_flag"]
        calc.rederive_storm_hold(prop)
        if prop["storm_hold_flag"] != before:
            touch(prop)

    if visit["visit_type"] == "SEASONAL_CLOSE":
        for rec in calc.children("winterization_records", "property_id", prop["id"]):
            if rec["status"] in ("NOT_STARTED", "PARTIAL", "REOPENED"):
                rec["visit_id"] = visit["id"]
                touch(rec)
                break

    return core.ok(serialize.visit(visit))


@bp.post("/property-care/visits/<vid>/defer")
def defer(vid):
    gates.begin(["Dispatcher", "AccountManager"])
    visit = gates.fetch_path("visits", vid)
    check_state("visit", visit, ["SCHEDULED"])
    body = gates.body_json()
    gates.validate_payload(body, [("defer_reason", "string", True)])
    visit["status"] = "DEFERRED"
    visit["defer_reason"] = body["defer_reason"]
    visit["deferral_count"] += 1
    touch(visit)
    return core.ok(serialize.visit(visit))


@bp.post("/property-care/visits/<vid>/reschedule")
def reschedule(vid):
    gates.begin(["Dispatcher", "AccountManager"])
    visit = gates.fetch_path("visits", vid)
    check_state("visit", visit, ["DEFERRED"])
    body = gates.body_json()
    gates.validate_payload(body, [
        ("scheduled_start_at", "datetime", True),
        ("scheduled_end_at", "datetime", True),
    ])
    gates.check_interval(body, "scheduled_start_at", "scheduled_end_at")
    start_at = parse_iso(body["scheduled_start_at"])
    end_at = parse_iso(body["scheduled_end_at"])
    if calc.any_turnover_overlap(visit["property_id"], start_at, end_at):
        fail("ERR_TURNOVER_WINDOW_OVERLAP", "The window collides with a padded rental turnover.")
    visit["scheduled_start_at"] = start_at
    visit["scheduled_end_at"] = end_at
    visit["defer_reason"] = None
    visit["status"] = "SCHEDULED"
    touch(visit)
    return core.ok(serialize.visit(visit))


@bp.post("/property-care/visits/<vid>/convert-to-turnover")
def convert_to_turnover(vid):
    gates.begin(["Dispatcher"])
    visit = gates.fetch_path("visits", vid)
    body = gates.body_json()
    turnover = None
    if isinstance(body.get("rental_turnover_id"), str):
        turnover = gates.fetch_optional_fk("rental_turnovers", body["rental_turnover_id"])
    check_state("visit", visit, ["SCHEDULED"])
    if turnover is not None:
        if turnover["status"] not in ("CLEANING", "INSPECTION"):
            fail("ERR_INVALID_STATE_TRANSITION", "The turnover is not in CLEANING or INSPECTION.")
        if not calc.turnover_overlap(visit["scheduled_start_at"], visit["scheduled_end_at"], turnover):
            fail("ERR_NO_TURNOVER_OVERLAP", "The visit window does not overlap the padded turnover window.")
    gates.validate_payload(body, [("rental_turnover_id", "string", True)])
    turnover = gates.fetch_optional_fk("rental_turnovers", body["rental_turnover_id"])

    visit["rental_turnover_id"] = turnover["id"]
    visit["entitlement_applied"] = False
    visit["billable_amount_cents"] = rhu_cents(
        D(core.VISIT_BASE_FEE_SCHEDULED_CENTS) * core.TURNOVER_ABSORPTION_CREDIT_PCT)
    visit["status"] = "CONVERTED"
    touch(visit)
    turnover["absorbed_visit_id"] = visit["id"]
    touch(turnover)
    return core.ok(serialize.visit(visit))


@bp.post("/property-care/visits/<vid>/abort")
def abort(vid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    visit = gates.fetch_path("visits", vid)
    check_state("visit", visit, ["SCHEDULED", "EN_ROUTE", "IN_PROGRESS"])
    visit["status"] = "ABORTED"
    touch(visit)
    return core.ok(serialize.visit(visit))


@bp.post("/property-care/visits/<vid>/findings")
def record_finding(vid):
    gates.begin(["FieldTech", "Dispatcher"])
    visit = gates.fetch_path("visits", vid)
    body = gates.body_json()
    gates.validate_payload(body, [
        ("item_code", "string", True),
        ("severity", "string", True),
        ("category", "string", True),
        ("description", "string", True),
    ])
    finding = ops.create_finding(visit["property_id"], visit["id"], body["item_code"],
                                 body["severity"], body["category"], body["description"])
    return core.ok(serialize.finding(finding), 201)
