"""Quality rules and the hundred-point scorecard budget (PRD 3.3)."""

from flask import Blueprint

import db
import response
import validation as v
from auth import endpoint, entitle
from errors import fail

bp = Blueprint("quality_rules", __name__)

DIMENSIONS = ("COMPLETENESS", "VALIDITY", "UNIQUENESS", "TIMELINESS", "CONSISTENCY")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
STATUSES = ("ACTIVE", "RETIRED")
READERS = ("GovernanceAdmin", "DataOwner", "DataSteward", "Auditor")

WEIGHT_BUDGET = 100


def _budget_exceeded(domain_id, rule_id, weight_points):
    total = weight_points
    for rule in db.active_rules_of(domain_id):
        if rule["id"] == rule_id:
            continue
        total += rule["weight_points"]
    return total > WEIGHT_BUDGET


@bp.post("/mdm/quality-rules")
@endpoint("DataSteward", "DataOwner")
def create_rule():
    body = v.body()
    domain_id = v.req_str(body, "domain_id", 1)
    owner_steward_id = v.req_str(body, "owner_steward_id", 1)
    rule_code = v.req_str(body, "rule_code", 1, 20)
    dimension = v.req_enum(body, "dimension", DIMENSIONS)
    weight_points = v.req_int(body, "weight_points", 1, 100)
    threshold_pct = v.req_num(body, "threshold_pct", 0, 100)
    severity = v.req_enum(body, "severity", SEVERITIES)

    domain = db.resolve(db.store.domains, domain_id, "ERR_DOMAIN_NOT_FOUND")
    owner = db.resolve(db.store.stewards, owner_steward_id, "ERR_STEWARD_NOT_FOUND")

    entitle(domain)

    for rule in db.rules_of(domain_id):
        if rule["rule_code"] == rule_code:
            fail("ERR_DUPLICATE_RULE_CODE", "This rule_code is already used in the domain.")

    if severity == "CRITICAL" and owner["certification_level"] != "PRINCIPAL":
        fail("ERR_OWNER_NOT_PRINCIPAL",
             "Only a PRINCIPAL-certified steward may own a CRITICAL-severity rule.")

    if _budget_exceeded(domain_id, None, weight_points):
        fail("ERR_RULE_WEIGHT_BUDGET_EXCEEDED",
             "The domain's ACTIVE rules may not exceed 100 weight points in total.")

    rule = db.create("QualityRule", {
        "domain_id": domain["id"],
        "owner_steward_id": owner["id"],
        "rule_code": rule_code,
        "dimension": dimension,
        "weight_points": weight_points,
        "threshold_pct": threshold_pct,
        "severity": severity,
        "status": "ACTIVE",
    })
    db.store.quality_rules[rule["id"]] = rule
    return response.created(rule)


@bp.get("/mdm/quality-rules")
@endpoint(*READERS)
def list_rules():
    limit, offset = v.pagination()
    domain_id = v.str_filter("domain_id")
    owner_steward_id = v.str_filter("owner_steward_id")
    status = v.enum_filter("status", STATUSES)
    dimension = v.enum_filter("dimension", DIMENSIONS)

    rows = db.ordered(db.store.quality_rules)
    if domain_id is not None:
        rows = [r for r in rows if r["domain_id"] == domain_id]
    if owner_steward_id is not None:
        rows = [r for r in rows if r["owner_steward_id"] == owner_steward_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if dimension is not None:
        rows = [r for r in rows if r["dimension"] == dimension]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/quality-rules/<rule_id>")
@endpoint(*READERS)
def read_rule(rule_id):
    rule = db.resolve(db.store.quality_rules, rule_id, "ERR_QUALITY_RULE_NOT_FOUND")
    return response.entity(rule)


@bp.patch("/mdm/quality-rules/<rule_id>")
@endpoint("DataSteward", "DataOwner")
def patch_rule(rule_id):
    rule = db.resolve(db.store.quality_rules, rule_id, "ERR_QUALITY_RULE_NOT_FOUND")
    body = v.body()
    threshold_pct = v.opt_num(body, "threshold_pct", 0, 100)
    weight_points = v.opt_int(body, "weight_points", 1, 100)
    status = v.opt_enum(body, "status", STATUSES)

    domain = db.store.domains[rule["domain_id"]]
    entitle(domain)

    if status is not None and status != rule["status"]:
        if status == "RETIRED":
            if rule["status"] != "ACTIVE":
                fail("ERR_INVALID_STATE_TRANSITION",
                     "Retirement is only available from ACTIVE status.")
            for finding in db.findings_of_rule(rule["id"]):
                if finding["status"] in db.OPEN_FINDING_STATUSES:
                    fail("ERR_RULE_HAS_OPEN_FINDINGS",
                         "The rule still carries an OPEN or REMEDIATION_PLANNED finding.")
        else:
            fail("ERR_INVALID_STATE_TRANSITION", "A RETIRED rule cannot be reactivated.")

    effective_status = status or rule["status"]
    effective_weight = weight_points if weight_points is not None else rule["weight_points"]
    if effective_status == "ACTIVE" and _budget_exceeded(rule["domain_id"], rule["id"],
                                                         effective_weight):
        fail("ERR_RULE_WEIGHT_BUDGET_EXCEEDED",
             "The domain's ACTIVE rules may not exceed 100 weight points in total.")

    if threshold_pct is not None:
        rule["threshold_pct"] = threshold_pct
    if weight_points is not None:
        rule["weight_points"] = weight_points
    if status is not None:
        rule["status"] = status
    db.bump(rule)
    return response.entity(rule)
