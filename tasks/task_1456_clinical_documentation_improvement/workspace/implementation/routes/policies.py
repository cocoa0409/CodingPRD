"""Escalation policy endpoints."""
from flask import Blueprint, request

import db
from errors import raise_error
from helpers import (
    body_ref,
    get_or_404,
    list_page,
    make_record,
    require_program_active,
    touch,
)
from middleware import (
    check_known_fields,
    get_json_body,
    require_fields,
    require_roles,
    validate_bool,
    validate_int_range,
    validate_string,
)
from response import success_list, success_object
from serializers import policy_out

bp = Blueprint("policies", __name__)

ROLES = {"CDIManager", "CDISpecialist", "HIMCoder", "ComplianceAuditor"}
UPDATABLE = {
    "name",
    "response_due_periods",
    "escalation_stage_periods",
    "max_escalation_stage",
    "is_default",
}


def _validate_windows(body, policy=None):
    """Validate the numeric windows for create (all required) or update."""
    def get(field):
        if policy is not None and field not in body:
            return policy[field]
        return body.get(field)

    for field, lo, hi in (
        ("response_due_periods", 1, None),
        ("escalation_stage_periods", 1, None),
        ("max_escalation_stage", 1, 5),
    ):
        if policy is not None and field not in body:
            continue
        require_fields(body, [field])
        hi = hi if hi is not None else 2**31
        validate_int_range(body[field], field, lo, hi)
    return get


def _check_name_unique(program_id, name, exclude_id=None):
    for p in db.policies.values():
        if (
            p["cdi_program_id"] == program_id
            and p["name"] == name
            and p["id"] != exclude_id
        ):
            raise_error(
                "ERR_INVALID_REQUEST",
                f"Policy name {name!r} already exists in this program",
            )


def _clear_sibling_defaults(policy):
    for p in db.policies.values():
        if (
            p["cdi_program_id"] == policy["cdi_program_id"]
            and p["id"] != policy["id"]
            and p["is_default"]
        ):
            p["is_default"] = False
            touch(p)


@bp.route("/api/escalation-policies", methods=["POST"])
def create_policy():
    require_roles({"CDIManager"})
    body = get_json_body()
    check_known_fields(body, {
        "cdi_program_id", "name", "response_due_periods",
        "escalation_stage_periods", "max_escalation_stage", "is_default",
    })
    require_fields(body, [
        "cdi_program_id", "name", "response_due_periods",
        "escalation_stage_periods", "max_escalation_stage",
    ])
    program = body_ref(body, "cdi_program_id", db.programs, "program")
    name = validate_string(body["name"], "name")
    _validate_windows(body)
    is_default = body.get("is_default", False)
    validate_bool(is_default, "is_default")
    require_program_active(program)
    _check_name_unique(program["id"], name)
    policy = make_record(db.policies, {
        "cdi_program_id": program["id"],
        "name": name,
        "response_due_periods": body["response_due_periods"],
        "escalation_stage_periods": body["escalation_stage_periods"],
        "max_escalation_stage": body["max_escalation_stage"],
        "is_default": is_default,
    })
    if is_default:
        _clear_sibling_defaults(policy)
    return success_object(policy_out(policy), status=201)


@bp.route("/api/escalation-policies", methods=["GET"])
def list_policies():
    require_roles(ROLES)
    program_id = request.args.get("cdi_program_id")
    items = list(db.policies.values())
    if program_id is not None:
        items = [p for p in items if p["cdi_program_id"] == program_id]
    page, limit, offset, total = list_page(items)
    return success_list([policy_out(p) for p in page], limit, offset, total)


@bp.route("/api/escalation-policies/<policyId>", methods=["GET"])
def get_policy(policyId):
    require_roles(ROLES)
    policy = get_or_404(db.policies, policyId, "escalation policy")
    return success_object(policy_out(policy))


@bp.route("/api/escalation-policies/<policyId>", methods=["PUT"])
def update_policy(policyId):
    require_roles({"CDIManager"})
    policy = get_or_404(db.policies, policyId, "escalation policy")
    body = get_json_body()
    check_known_fields(body, UPDATABLE)
    program = db.programs.get(policy["cdi_program_id"])
    require_program_active(program)
    if "name" in body:
        name = validate_string(body["name"], "name")
        _check_name_unique(policy["cdi_program_id"], name, exclude_id=policy["id"])
        policy["name"] = name
    if "response_due_periods" in body:
        policy["response_due_periods"] = validate_int_range(
            body["response_due_periods"], "response_due_periods", 1, 2**31
        )
    if "escalation_stage_periods" in body:
        policy["escalation_stage_periods"] = validate_int_range(
            body["escalation_stage_periods"], "escalation_stage_periods", 1, 2**31
        )
    if "max_escalation_stage" in body:
        policy["max_escalation_stage"] = validate_int_range(
            body["max_escalation_stage"], "max_escalation_stage", 1, 5
        )
    if "is_default" in body:
        is_default = validate_bool(body["is_default"], "is_default")
        if is_default and not policy["is_default"]:
            policy["is_default"] = True
            _clear_sibling_defaults(policy)
        elif not is_default and policy["is_default"]:
            # Clearing the program's default would leave it with none.
            raise_error(
                "ERR_DEFAULT_POLICY_CONFLICT",
                "Cannot clear the default escalation policy of a program",
            )
    touch(policy)
    return success_object(policy_out(policy))
