from datetime import timedelta

from flask import Blueprint

import calc
import core
import gates
import ops
import serialize
from core import fail, get, new_row, now, parse_iso, rows, touch
from gates import check_state

bp = Blueprint("incidents", __name__)

READ_ROLES = ["Dispatcher", "FieldTech", "Owner", "PlatformAdmin", "AccountManager", "Auditor"]


@bp.post("/property-care/properties/<pid>/security-incidents")
def create_incident(pid):
    role, user_id = gates.begin(["Dispatcher", "FieldTech", "Owner", "PlatformAdmin"])
    prop = gates.fetch_path("properties", pid)
    gates.owner_scope(role, user_id, prop["owner_id"])
    body = gates.body_json()
    gates.resolve_optional_fks(body, ["visit_id"])
    gates.validate_payload(body, [
        ("incident_type", "string", True),
        ("severity", "string", True),
        ("visit_id", "string", False),
    ])
    incident = new_row(
        "security_incidents",
        property_id=prop["id"], visit_id=body.get("visit_id"),
        incident_type=body["incident_type"], reported_at=now(), severity=body["severity"],
        status="REPORTED", escalation_count=0, false_alarm_sequence=None,
        false_alarm_fee_cents=0, triggered_visit_id=None, resolution_note=None,
    )
    return core.ok(serialize.security_incident(incident), 201)


@bp.get("/property-care/security-incidents")
def list_incidents():
    gates.begin(READ_ROLES)
    return gates.list_response("security_incidents",
                               ["property_id", "visit_id", "status", "incident_type"],
                               serialize.security_incident)


@bp.get("/property-care/security-incidents/<iid>")
def read_incident(iid):
    role, user_id = gates.begin(READ_ROLES)
    incident = gates.fetch_path("security_incidents", iid)
    prop = get("properties", incident["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    return core.ok(serialize.security_incident(incident))


@bp.post("/property-care/security-incidents/<iid>/acknowledge")
def acknowledge(iid):
    gates.begin(["Dispatcher"])
    incident = gates.fetch_path("security_incidents", iid)
    check_state("security_incident", incident, ["REPORTED"])
    incident["status"] = "ACKNOWLEDGED"
    touch(incident)
    return core.ok(serialize.security_incident(incident))


@bp.post("/property-care/security-incidents/<iid>/investigate")
def investigate(iid):
    gates.begin(["Dispatcher"])
    incident = gates.fetch_path("security_incidents", iid)
    body = gates.body_json()
    if body.get("checklist_template_id") is not None:
        if not isinstance(body["checklist_template_id"], str) or \
                get("checklist_templates", body["checklist_template_id"]) is None:
            fail("ERR_LINKED_RESOURCE_NOT_FOUND", "The checklist template does not exist.")
    check_state("security_incident", incident, ["ACKNOWLEDGED", "ESCALATED"])
    gates.validate_payload(body, [
        ("checklist_template_id", "string", False),
        ("scheduled_start_at", "datetime", False),
        ("scheduled_end_at", "datetime", False),
    ])
    first_pass = incident["status"] == "ACKNOWLEDGED"
    incident["status"] = "INVESTIGATING"
    if first_pass and incident["incident_type"] in core.FORCED_VISIT_INCIDENT_TYPES:
        template = get("checklist_templates", body.get("checklist_template_id"))
        if template is None:
            for tpl in rows("checklist_templates"):
                if tpl["visit_type"] == "ALARM_RESPONSE" and tpl["status"] == "ACTIVE":
                    template = tpl
                    break
        if template is not None:
            start_at = parse_iso(body["scheduled_start_at"]) if body.get("scheduled_start_at") else now()
            end_at = (parse_iso(body["scheduled_end_at"]) if body.get("scheduled_end_at")
                      else start_at + timedelta(hours=core.AUTO_DISPATCH_WINDOW_HOURS))
            visit = ops.create_visit(incident["property_id"], template["id"], "ALARM_RESPONSE",
                                     "ALARM_TRIGGERED", start_at, end_at)
            incident["triggered_visit_id"] = visit["id"]
    touch(incident)
    return core.ok(serialize.security_incident(incident))


@bp.post("/property-care/security-incidents/<iid>/escalate")
def escalate(iid):
    gates.begin(["Dispatcher", "StormCoordinator"])
    incident = gates.fetch_path("security_incidents", iid)
    check_state("security_incident", incident, ["INVESTIGATING"])
    if incident["severity"] not in ("HIGH", "CRITICAL"):
        fail("ERR_SEVERITY_TOO_LOW_TO_ESCALATE", "Only HIGH or CRITICAL incidents may escalate.")
    incident["status"] = "ESCALATED"
    incident["escalation_count"] += 1
    touch(incident)
    return core.ok(serialize.security_incident(incident))


@bp.post("/property-care/security-incidents/<iid>/resolve")
def resolve(iid):
    gates.begin(["Dispatcher"])
    incident = gates.fetch_path("security_incidents", iid)
    check_state("security_incident", incident, ["INVESTIGATING", "ESCALATED"])
    body = gates.body_json()
    gates.validate_payload(body, [("resolution_note", "string", True)])
    incident["status"] = "RESOLVED"
    incident["resolution_note"] = body["resolution_note"]
    touch(incident)
    return core.ok(serialize.security_incident(incident))


@bp.post("/property-care/security-incidents/<iid>/reclassify-false-alarm")
def reclassify(iid):
    gates.begin(["Dispatcher", "AccountManager"])
    incident = gates.fetch_path("security_incidents", iid)
    check_state("security_incident", incident, ["INVESTIGATING", "ESCALATED"])
    if incident["incident_type"] not in core.ALARM_CLASS_TYPES:
        fail("ERR_INCIDENT_NOT_ALARM_CLASS", "That incident type is not of the alarm class.")
    body = gates.body_json()
    gates.validate_payload(body, [("resolution_note", "string", False)])
    if body.get("resolution_note") is not None:
        incident["resolution_note"] = body["resolution_note"]
    incident["status"] = "FALSE_ALARM"
    incident["false_alarm_sequence"] = calc.false_alarm_sequence(incident)
    incident["false_alarm_fee_cents"] = calc.false_alarm_fee(incident["false_alarm_sequence"])
    touch(incident)
    if incident["false_alarm_fee_cents"] > 0:
        invoice = calc.property_draft_invoice(incident["property_id"])
        if invoice is not None:
            calc.append_invoice_line(invoice, "FALSE_ALARM_FEE", "Municipal false-alarm fee",
                                     incident["false_alarm_fee_cents"], taxable=True,
                                     security_incident_id=incident["id"])
    return core.ok(serialize.security_incident(incident))
