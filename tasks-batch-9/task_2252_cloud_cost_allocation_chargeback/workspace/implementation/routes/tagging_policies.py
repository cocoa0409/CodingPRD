"""Tagging governance (PRD 3.2)."""
from flask import Blueprint

from db import base_fields, db, touch
from errors import fail
from middleware import authorize, user_id
from routes.common import lookup, serve, serve_list
from services import derived
from services.calc import ALLOWED_DIMENSIONS
from validation import body, opt_enum, req_enum, req_int, req_str, req_str_list

bp = Blueprint("tagging_policies", __name__)

MODES = ("ADVISORY", "BLOCKING")


def _dimensions(data):
    dims = req_str_list(data, "mandatory_dimensions")
    if not dims:
        fail("ERR_INVALID_REQUEST", "mandatory_dimensions must be non-empty.")
    seen = []
    for dim in dims:
        if dim not in ALLOWED_DIMENSIONS:
            fail(
                "ERR_INVALID_REQUEST",
                "mandatory_dimensions must be a subset of team, environment, application.",
            )
        if dim in seen:
            fail("ERR_INVALID_REQUEST", "mandatory_dimensions may not repeat a dimension.")
        seen.append(dim)
    return dims


@bp.route("/finops/tagging-policies", methods=["POST"])
@authorize("FinOpsAnalyst", "FinOpsController")
def draft_policy():
    data = body()
    name = req_str(data, "name")
    dims = _dimensions(data)
    mode = opt_enum(data, "enforcement_mode", MODES, "ADVISORY")

    policy = base_fields()
    policy.update(
        {
            "name": name,
            "mandatory_dimensions": dims,
            "enforcement_mode": mode,
            "status": "DRAFT",
            "created_by_user_id": user_id(),
            "activated_by_user_id": None,
            "rejection_count": 0,
        }
    )
    db.tagging_policies[policy["id"]] = policy
    return serve(policy, 201)


@bp.route("/finops/tagging-policies", methods=["GET"])
@authorize("FinOpsAnalyst", "FinOpsController", "PlatformAdmin")
def list_policies():
    for policy in list(db.tagging_policies.values()):
        derived.policy_sync(policy, bump=False)
    return serve_list(db.tagging_policies.values(), {"status": "status"})


@bp.route("/finops/tagging-policies/<policy_id>", methods=["GET"])
@authorize("FinOpsAnalyst", "FinOpsController", "PlatformAdmin")
def get_policy(policy_id):
    policy = lookup("tagging_policies", policy_id)
    derived.policy_sync(policy, bump=False)
    return serve(policy)


@bp.route("/finops/tagging-policies/<policy_id>", methods=["PUT"])
@authorize("FinOpsAnalyst", "FinOpsController")
def amend_policy(policy_id):
    policy = lookup("tagging_policies", policy_id)
    data = body()
    expected = req_int(data, "expected_tagging_policy_version")
    dims = _dimensions(data)
    mode = req_enum(data, "enforcement_mode", MODES)

    if expected != policy["version"]:
        fail(
            "ERR_STALE_VERSION",
            "expected_tagging_policy_version %s does not match the policy version %s."
            % (expected, policy["version"]),
        )
    if policy["status"] != "DRAFT":
        fail("ERR_POLICY_STATE_INVALID", "Only a DRAFT policy may be amended.")

    policy["mandatory_dimensions"] = dims
    policy["enforcement_mode"] = mode
    touch(policy)
    return serve(policy)


@bp.route("/finops/tagging-policies/<policy_id>/activate", methods=["POST"])
@authorize("FinOpsController")
def activate_policy(policy_id):
    policy = lookup("tagging_policies", policy_id)
    if policy["status"] != "DRAFT":
        fail("ERR_POLICY_STATE_INVALID", "Only a DRAFT policy may be activated.")
    if user_id() == policy["created_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The activating user must differ from the drafting user.",
        )
    policy["status"] = "ACTIVE"
    policy["activated_by_user_id"] = user_id()
    touch(policy)
    return serve(policy)


@bp.route("/finops/tagging-policies/<policy_id>/retire", methods=["POST"])
@authorize("FinOpsController")
def retire_policy(policy_id):
    policy = lookup("tagging_policies", policy_id)
    if policy["status"] != "ACTIVE":
        fail("ERR_POLICY_STATE_INVALID", "Only an ACTIVE policy may be retired.")
    policy["status"] = "RETIRED"
    touch(policy)
    return serve(policy)
