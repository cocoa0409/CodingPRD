"""Curing a conditional standing: improvement plans, variances, audit findings."""
from flask import Blueprint

import auth
import calc
import derive
import response
import serialize
import store
import validators as V
from errors import fail
from store import S, insert, now, sort_created, touch

bp = Blueprint("cure", __name__)


@bp.route("/prequalifications/<prequalification_id>/improvement-plans", methods=["POST"])
def create_improvement_plan(prequalification_id):
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    body = V.parse_body(
        [
            ("prequalification_id", "string", False),
            ("due_date", "string", True),
            ("milestone_count", "integer", True),
            ("expected_prequalification_version", "integer", True),
        ]
    )
    due_date = V.parse_instant("due_date", body["due_date"])
    milestone_count = V.check_int_range("milestone_count", body["milestone_count"], lo=1, hi=20)
    if due_date <= now():
        fail("ERR_INVALID_FIELD_VALUE", "due_date must be strictly after the logical clock.")

    preq = V.get_prequalification(prequalification_id)
    auth.check_owner(role, user_id, client_id=preq["client_id"])

    if body["expected_prequalification_version"] != preq["version"]:
        fail(
            "ERR_STALE_VERSION",
            "expected_prequalification_version does not match the prequalification.",
        )
    if preq["status"] != "CONDITIONAL":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only a CONDITIONAL prequalification may be cured.")
    if preq["conditional_expires_at"] is not None and due_date > preq["conditional_expires_at"]:
        fail("ERR_INVALID_FIELD_VALUE", "due_date may not outlive conditional_expires_at.")

    for plan in sort_created(derive.plans_of(preq["id"])):
        if plan["status"] in ("OPEN", "SUBMITTED"):
            plan["status"] = "REJECTED"
            plan["closed_at"] = now()
            touch(plan)

    row = store.base_row()
    row.update(
        {
            "prequalification_id": preq["id"],
            "due_date": due_date,
            "milestone_count": milestone_count,
            "deficiency_codes": list(preq["deficiency_codes"]),
            "evidence_ref": None,
            "status": "OPEN",
            "decided_by_user_id": None,
            "closed_at": None,
        }
    )
    insert(S.improvement_plans, row)
    touch(preq)
    return response.created(serialize.improvement_plan(row))


@bp.route("/improvement-plans/<plan_id>/submit", methods=["POST"])
def submit_improvement_plan(plan_id):
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    body = V.parse_body([("evidence_ref", "string", True)])
    evidence_ref = V.check_str_len("evidence_ref", body["evidence_ref"], 1, 120)

    row = V.get_plan(plan_id)
    preq = S.prequalifications[row["prequalification_id"]]
    auth.check_owner(role, user_id, contractor_id=preq["contractor_id"])

    if row["status"] != "OPEN":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only an OPEN plan may receive evidence.")
    if not now() < row["due_date"]:
        fail("ERR_TRANSITION_NOT_ALLOWED", "Evidence tendered on or after the deadline is refused.")

    row["evidence_ref"] = evidence_ref
    row["status"] = "SUBMITTED"
    touch(row)
    return response.ok(serialize.improvement_plan(row))


@bp.route("/improvement-plans/<plan_id>/decision", methods=["POST"])
def decide_improvement_plan(plan_id):
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    body = V.parse_body([("decision", "string", True)])
    decision = V.check_enum("decision", body["decision"], ("ACCEPT", "REJECT"))

    row = V.get_plan(plan_id)
    preq = S.prequalifications[row["prequalification_id"]]
    auth.check_owner(role, user_id, client_id=preq["client_id"])

    if row["status"] != "SUBMITTED":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only a SUBMITTED plan may be decided.")

    if decision == "REJECT":
        row["status"] = "OPEN"
        row["evidence_ref"] = None
        row["decided_by_user_id"] = user_id
        touch(row)
        return response.ok(serialize.improvement_plan(row))

    row["status"] = "ACCEPTED"
    row["closed_at"] = now()
    row["decided_by_user_id"] = user_id
    touch(row)

    preq["status"] = "UNDER_REVIEW"
    preq["deficiency_codes"] = []
    preq["conditional_expires_at"] = None
    preq["grade"] = None
    preq["final_composite_score"] = None
    preq["effective_thresholds"] = None
    touch(preq)
    derive.recompute_open_deficiency_count(S.contractors[preq["contractor_id"]])
    derive.recompute_flow_down(preq["id"])
    return response.ok(serialize.improvement_plan(row))


@bp.route("/prequalifications/<prequalification_id>/variances", methods=["POST"])
def create_variance(prequalification_id):
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    body = V.parse_body(
        [
            ("prequalification_id", "string", False),
            ("requirement_code", "string", True),
            ("requested_value", "number", True),
            ("justification", "string", True),
        ]
    )
    requirement_code = V.check_enum(
        "requirement_code", body["requirement_code"], calc.REQUIREMENT_CODES
    )
    requested_value = V.check_num_range(
        "requested_value", body["requested_value"], lo=0, lo_strict=True
    )
    justification = V.check_str_len("justification", body["justification"], 1, 500)

    preq = V.get_prequalification(prequalification_id)
    auth.check_owner(role, user_id, contractor_id=preq["contractor_id"])

    if preq["status"] not in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "CONDITIONAL"):
        fail("ERR_TRANSITION_NOT_ALLOWED", "A variance may not be requested from this status.")
    for existing in derive.variances_of(preq["id"]):
        if existing["requirement_code"] == requirement_code and existing["status"] in (
            "REQUESTED",
            "APPROVED",
        ):
            fail("ERR_TRANSITION_NOT_ALLOWED", "A live variance already covers that requirement.")

    row = store.base_row()
    row.update(
        {
            "prequalification_id": preq["id"],
            "requirement_code": requirement_code,
            "requested_value": requested_value,
            "justification": justification,
            "status": "REQUESTED",
            "expires_at": None,
            "decided_by_user_id": None,
        }
    )
    insert(S.variances, row)
    return response.created(serialize.variance(row))


@bp.route("/variances/<variance_id>/decision", methods=["POST"])
def decide_variance(variance_id):
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    body = V.parse_body(
        [("decision", "string", True), ("expires_at", "string", False)]
    )
    decision = V.check_enum("decision", body["decision"], ("APPROVE", "DENY"))
    expires_at = None
    if decision == "APPROVE":
        if body["expires_at"] is None:
            fail("ERR_INVALID_FIELD_VALUE", "expires_at is required when approving a variance.")
        expires_at = V.parse_instant("expires_at", body["expires_at"])
        if expires_at <= now():
            fail("ERR_INVALID_FIELD_VALUE", "expires_at must be strictly after the logical clock.")
    elif body["expires_at"] is not None:
        V.parse_instant("expires_at", body["expires_at"])

    row = V.get_leaf(S.variances, variance_id)
    preq = S.prequalifications[row["prequalification_id"]]
    auth.check_owner(role, user_id, client_id=preq["client_id"])

    if row["status"] != "REQUESTED":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only a REQUESTED variance may be decided.")

    if decision == "APPROVE":
        row["status"] = "APPROVED"
        row["expires_at"] = expires_at
    else:
        row["status"] = "DENIED"
        row["expires_at"] = None
    row["decided_by_user_id"] = user_id
    touch(row)
    return response.ok(serialize.variance(row))


@bp.route("/prequalifications/<prequalification_id>/audit-findings", methods=["POST"])
def record_audit_findings(prequalification_id):
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    body = V.parse_body([("findings_count", "integer", True)])
    findings_count = V.check_int_range("findings_count", body["findings_count"], lo=0)

    preq = V.get_prequalification(prequalification_id)
    auth.check_owner(role, user_id, client_id=preq["client_id"])

    if preq["audit_state"] != "SELECTED":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only a SELECTED row may record audit findings.")

    preq["audit_findings_count"] = findings_count
    if findings_count == 0:
        preq["audit_state"] = "PASSED"
    else:
        preq["audit_state"] = "FAILED"
        if "AUDIT_SAMPLING" not in preq["deficiency_codes"]:
            preq["deficiency_codes"] = list(preq["deficiency_codes"]) + ["AUDIT_SAMPLING"]
    touch(preq)
    derive.recompute_open_deficiency_count(S.contractors[preq["contractor_id"]])
    return response.ok(serialize.prequalification(preq))
