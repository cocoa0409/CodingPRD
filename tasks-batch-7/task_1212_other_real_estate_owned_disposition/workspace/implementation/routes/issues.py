"""IssueCase endpoints: open, remediate, resolve, waive."""
import db
import domain
from domain import issue_json, sort_entities, TERMINAL_LIFECYCLE
from envelope import success
from errors import ApiError
from routes.common import (require_roles, body, req_str, req_enum, paginate, get_or_404)
from routes.properties import ALL_ROLES, request_arg

ISSUE_TYPES = ("ENVIRONMENTAL", "TITLE")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")


def create_issue():
    require_roles("PropertyManager")
    d = body()
    property_id = req_str(d, "property_id")
    issue_type = req_enum(d, "issue_type", ISSUE_TYPES)
    severity = req_enum(d, "severity", SEVERITIES)
    description = req_str(d, "description")
    p = get_or_404(db.properties, property_id, "Property")
    if p["lifecycle_status"] in TERMINAL_LIFECYCLE:
        raise ApiError("ERR_PROPERTY_ALREADY_TERMINAL", 409,
                       "Cannot open an issue on a terminal property")
    i = domain.base_entity()
    i.update({
        "property_id": property_id,
        "issue_type": issue_type,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "resolution_notes": None,
    })
    db.issues[i["id"]] = i
    domain.bump(p)
    return success(issue_json(i), 201)


def list_issues():
    require_roles(*ALL_ROLES)
    pid = request_arg("property_id")
    itype = request_arg("issue_type")
    status = request_arg("status")
    items = [i for i in db.issues.values()
             if (pid is None or i["property_id"] == pid)
             and (itype is None or i["issue_type"] == itype)
             and (status is None or i["status"] == status)]
    return paginate(sort_entities(items), issue_json)


def get_issue(entity_id):
    require_roles(*ALL_ROLES)
    return success(issue_json(get_or_404(db.issues, entity_id, "Issue")))


def start_remediation(entity_id):
    require_roles("PropertyManager")
    i = get_or_404(db.issues, entity_id, "Issue")
    if i["status"] != "OPEN":
        raise ApiError("ERR_ISSUE_INVALID_STATE", 409, "Only an OPEN issue can start remediation")
    i["status"] = "IN_REMEDIATION"
    domain.bump(i)  # counts unchanged: IN_REMEDIATION still counts as open
    return success(issue_json(i), 200)


def resolve_issue(entity_id):
    require_roles("PropertyManager")
    d = body()
    resolution_notes = req_str(d, "resolution_notes")
    i = get_or_404(db.issues, entity_id, "Issue")
    if i["status"] != "IN_REMEDIATION":
        raise ApiError("ERR_ISSUE_INVALID_STATE", 409, "Only an IN_REMEDIATION issue can be resolved")
    i["status"] = "RESOLVED"
    i["resolution_notes"] = resolution_notes
    domain.bump(i)
    domain.bump(db.properties[i["property_id"]])
    return success(issue_json(i), 200)


def waive_issue(entity_id):
    require_roles("OREOCommittee")
    i = get_or_404(db.issues, entity_id, "Issue")
    if i["status"] != "OPEN":
        raise ApiError("ERR_ISSUE_INVALID_STATE", 409, "Only an OPEN issue can be waived")
    if i["issue_type"] == "ENVIRONMENTAL":
        raise ApiError("ERR_ENVIRONMENTAL_NOT_WAIVABLE", 422,
                       "Environmental issues are never waivable")
    i["status"] = "WAIVED"
    domain.bump(i)
    domain.bump(db.properties[i["property_id"]])
    return success(issue_json(i), 200)
