"""Verification policies: drafting, publication and reads (PRD 3.1)."""
from flask import Blueprint

import auth
import clock
import db
import response
import schema
import views
from errors import fail
from schema import Field
from . import support

bp = Blueprint("policies", __name__)

LADDER_METHOD_CODES = ("DOCUMENT_SCAN", "DATABASE_CHECK", "BIOMETRIC_COMPARISON", "KNOWLEDGE_BASED")
POLICY_STATES = ("DRAFT", "PUBLISHED", "RETIRED")

POLICY_FIELDS = (
    Field("client_id", "string", required=True),
    Field("policy_version", "int", required=True, minimum=1),
    Field("allowed_method_codes", "array", required=True, non_empty=True,
          item_type="string", item_enum=LADDER_METHOD_CODES, distinct=True),
    Field("min_assurance_score", "int", required=True, minimum=1, maximum=100),
    Field("doc_authenticity_floor_bps", "int", default=8000, minimum=5001, maximum=10000),
    Field("pad_threshold_bps", "int", default=7500, minimum=1000, maximum=9500),
    Field("required_min_age_years", "int", default=0, minimum=0, maximum=25),
    Field("age_buffer_multiplier_bps", "int", default=15000, minimum=10000, maximum=30000),
    Field("step_up_max_rounds", "int", default=2, minimum=0, maximum=5),
    Field("alternative_pathway_enabled", "bool", default=True),
)

PUBLISH_FIELDS = (
    Field("expected_client_version", "int", required=True, minimum=0),
)


@bp.post("/idv/verification-policies")
def create_policy():
    caller = auth.authenticate((auth.CLIENT_INTEGRATOR, auth.COMPLIANCE_OFFICER))
    support.scope_check_body_client(caller)
    values = schema.validate(schema.read_body(), POLICY_FIELDS)
    client = db.get(db.CLIENTS, values["client_id"])
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    for existing in db.POLICIES.values():
        if (existing["client_id"] == values["client_id"]
                and existing["policy_version"] == values["policy_version"]):
            fail("ERR_POLICY_VERSION_DUPLICATE")
    record = {
        "client_id": values["client_id"],
        "policy_version": values["policy_version"],
        "state": "DRAFT",
        "allowed_method_codes": list(values["allowed_method_codes"]),
        "min_assurance_score": values["min_assurance_score"],
        "doc_authenticity_floor_bps": values["doc_authenticity_floor_bps"],
        "pad_threshold_bps": values["pad_threshold_bps"],
        "required_min_age_years": values["required_min_age_years"],
        "age_buffer_multiplier_bps": values["age_buffer_multiplier_bps"],
        "step_up_max_rounds": values["step_up_max_rounds"],
        "alternative_pathway_enabled": values["alternative_pathway_enabled"],
        "published_at": None,
        "retired_at": None,
    }
    db.insert(db.POLICIES, record)
    return response.object_response(views.policy_view(record), 201)


@bp.post("/idv/verification-policies/<policy_id>/publish")
def publish_policy(policy_id):
    auth.authenticate((auth.COMPLIANCE_OFFICER,))
    policy = db.get(db.POLICIES, policy_id)
    if policy is None:
        fail("ERR_POLICY_NOT_FOUND")
    values = schema.validate(schema.read_body(), PUBLISH_FIELDS)
    if policy["state"] != "DRAFT":
        fail("ERR_POLICY_STATE_INVALID")
    client = db.get(db.CLIENTS, policy["client_id"])
    current_version = client["version"] if client is not None else None
    if values["expected_client_version"] != current_version:
        fail("ERR_STALE_CLIENT_VERSION")
    if client is None or client["integration_state"] == "SUSPENDED":
        fail("ERR_CLIENT_NOT_LIVE")

    now = clock.now()
    for other in db.all_of(db.POLICIES):
        if (other["client_id"] == policy["client_id"] and other["id"] != policy["id"]
                and other["state"] == "PUBLISHED"):
            other["state"] = "RETIRED"
            other["retired_at"] = now
            db.touch(other)
    policy["state"] = "PUBLISHED"
    policy["published_at"] = now
    db.touch(policy)
    db.touch(client)
    return response.object_response(views.policy_view(policy))


@bp.get("/idv/verification-policies/<policy_id>")
def read_policy(policy_id):
    caller = auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER, auth.CLIENT_INTEGRATOR))
    policy = db.get(db.POLICIES, policy_id)
    if policy is None:
        fail("ERR_POLICY_NOT_FOUND")
    auth.require_own_client(caller, policy["client_id"])
    return response.object_response(views.policy_view(policy))


@bp.get("/idv/verification-policies")
def list_policies():
    caller = auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER, auth.CLIENT_INTEGRATOR))
    client_id = support.string_filter("client_id")
    if caller.is_client_integrator:
        if client_id is not None and client_id != caller.user_id:
            fail("ERR_CLIENT_SCOPE_VIOLATION")
        client_id = caller.user_id
    state = support.enum_filter("state", POLICY_STATES)
    records = db.all_of(db.POLICIES)
    if client_id is not None:
        records = [p for p in records if p["client_id"] == client_id]
    if state is not None:
        records = [p for p in records if p["state"] == state]
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.policy_view(p) for p in page], limit, offset, total)
