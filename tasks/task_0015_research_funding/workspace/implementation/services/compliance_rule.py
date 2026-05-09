"""ComplianceRule — admin-managed pre-screen rules."""

from common import (
    require_field,
    sort_by_created_at,
    stamp_create,
    stamp_update,
)
from db import db
from errors import (
    ERR_COMPLIANCE_RULE_NOT_FOUND,
    ERR_INVALID_INPUT,
    ERR_STALE_BUDGET_VERSION,
    raise_error,
)


VALID_FUNDING_OR_ALL = {"NATIONAL", "PROVINCIAL", "ENTERPRISE", "INTERNAL", "ALL"}
VALID_CATEGORY_OR_ALL = {"PERSONNEL", "EQUIPMENT", "MATERIALS", "TRAVEL", "CONFERENCE", "OUTSOURCING", "ALL"}
VALID_SEVERITY = {"BLOCK", "ESCALATE", "WARN"}


def get_rule_or_404(rule_id):
    r = db.compliance_rules.get(rule_id)
    if r is None:
        raise_error(ERR_COMPLIANCE_RULE_NOT_FOUND, f"compliance rule {rule_id} not found")
    return r


def serialize_rule(r):
    return {
        "id": r["id"],
        "rule_code": r["rule_code"],
        "applies_to_funding_source": r["applies_to_funding_source"],
        "applies_to_category": r["applies_to_category"],
        "parameters": r.get("parameters") or {},
        "severity": r["severity"],
        "active": r.get("active", True),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def create_rule(body):
    rule_code = require_field(body, "rule_code", str)
    applies_funding = require_field(body, "applies_to_funding_source", str)
    if applies_funding not in VALID_FUNDING_OR_ALL:
        raise_error(ERR_INVALID_INPUT, "invalid applies_to_funding_source")
    applies_category = require_field(body, "applies_to_category", str)
    if applies_category not in VALID_CATEGORY_OR_ALL:
        raise_error(ERR_INVALID_INPUT, "invalid applies_to_category")
    parameters = body.get("parameters", {})
    if parameters is not None and not isinstance(parameters, dict):
        raise_error(ERR_INVALID_INPUT, "parameters must be an object")
    severity = require_field(body, "severity", str)
    if severity not in VALID_SEVERITY:
        raise_error(ERR_INVALID_INPUT, "invalid severity")
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise_error(ERR_INVALID_INPUT, "active must be a boolean")

    rid = db.new_id()
    rule = {
        "id": rid,
        "rule_code": rule_code,
        "applies_to_funding_source": applies_funding,
        "applies_to_category": applies_category,
        "parameters": parameters or {},
        "severity": severity,
        "active": active,
    }
    stamp_create(rule)
    db.compliance_rules[rid] = rule
    return rule


def patch_rule(rule_id, body):
    r = get_rule_or_404(rule_id)
    # Optimistic concurrency
    body_version = body.get("version")
    if body_version is not None:
        if body_version != r["version"]:
            raise_error(ERR_STALE_BUDGET_VERSION, "version mismatch")
    if "active" in body:
        if not isinstance(body["active"], bool):
            raise_error(ERR_INVALID_INPUT, "active must be a boolean")
        r["active"] = body["active"]
    if "severity" in body:
        if body["severity"] not in VALID_SEVERITY:
            raise_error(ERR_INVALID_INPUT, "invalid severity")
        r["severity"] = body["severity"]
    if "parameters" in body:
        if body["parameters"] is not None and not isinstance(body["parameters"], dict):
            raise_error(ERR_INVALID_INPUT, "parameters must be an object")
        r["parameters"] = body["parameters"] or {}
    stamp_update(r)
    return r


def list_rules():
    return sort_by_created_at(list(db.compliance_rules.values()))


def find_active_rules(rule_code, funding_source, category):
    """Find active rules matching code, funding source, category."""
    matching = []
    for r in db.compliance_rules.values():
        if not r.get("active", True):
            continue
        if r["rule_code"] != rule_code:
            continue
        if r["applies_to_funding_source"] not in (funding_source, "ALL"):
            continue
        if r["applies_to_category"] not in (category, "ALL"):
            continue
        matching.append(r)
    return matching
