"""Cost-cap policies: the underwriting quote and the bind."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import actor_id, endpoint
from routes.common import apply_filter, fetch, party_or_404, require_party_type
from services import calc, derive
from services.constants import MIN_LIMIT_CENTS, POLICY_STATUS
from services.serialize import dump_policy

bp = Blueprint("policies", __name__)

READ_ROLES = ["Insurer", "StateAgencyReviewer", "Redeveloper", "Lender",
              "EnvironmentalConsultant"]


@bp.post("/cost-cap-policies")
@endpoint(["Insurer"])
def create_policy():
    body = V.json_body()
    plan_id = V.id_field(body, "remedial_action_plan_id", True)
    insurer_party_id = V.id_field(body, "insurer_party_id", True)
    policy_reference = V.string_field(body, "policy_reference", True, 1, 64)
    term_years = V.int_field(body, "term_years", True, 1, 10)
    expected_version = V.int_field(body, "expected_remedial_action_plan_version",
                                   True, minimum=0)

    plan = fetch("remedial_action_plans", plan_id)
    insurer = party_or_404(insurer_party_id)
    if actor_id() != insurer_party_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The quoting insurer must be the acting user.")
    require_party_type(insurer, "INSURER")
    site = db.get("sites", plan["site_id"])
    if site is not None:
        derive.assert_not_frozen(site)
    if int(plan["version"]) != int(expected_version):
        raise ApiError("ERR_STALE_PLAN_VERSION",
                       "Expected plan version %s but found %s."
                       % (expected_version, plan["version"]))

    underwriting = derive.underwriting_estimate_for_plan(plan)
    terms = calc.cost_cap_terms(underwriting)
    row = db.insert("cost_cap_policies", {
        "remedial_action_plan_id": plan["id"],
        "insurer_party_id": insurer_party_id,
        "policy_reference": policy_reference,
        "term_years": term_years,
        "underwriting_estimate_cents": terms["underwriting_estimate_cents"],
        "attachment_point_cents": terms["attachment_point_cents"],
        "buffer_layer_cents": terms["buffer_layer_cents"],
        "limit_cents": terms["limit_cents"],
        "rate_applied": terms["rate_applied"],
        "premium_cents": terms["premium_cents"],
        "status": "QUOTED",
        "bound_at": None,
    })

    for policy in db.ordered(db.all_rows("cost_cap_policies")):
        if (policy["id"] != row["id"]
                and policy["remedial_action_plan_id"] == plan["id"]
                and policy["status"] == "QUOTED"):
            policy["status"] = "SUPERSEDED"
            db.touch(policy)
    db.touch(plan)
    return response.created(dump_policy(row))


@bp.get("/cost-cap-policies")
@endpoint(READ_ROLES)
def list_policies():
    rows = db.ordered(db.all_rows("cost_cap_policies"))
    rows = apply_filter(rows, "remedial_action_plan_id",
                        V.query_string("remedial_action_plan_id"))
    rows = apply_filter(rows, "insurer_party_id",
                        V.query_string("insurer_party_id"))
    rows = apply_filter(rows, "status", V.query_enum("status", POLICY_STATUS))
    return response.list_response(rows, dump_policy)


@bp.get("/cost-cap-policies/<policy_id>")
@endpoint(READ_ROLES)
def get_policy(policy_id):
    return response.object_response(
        dump_policy(fetch("cost_cap_policies", policy_id)))


@bp.post("/cost-cap-policies/<policy_id>/bind")
@endpoint(["Insurer"])
def bind_policy(policy_id):
    policy = fetch("cost_cap_policies", policy_id)
    plan = db.get("remedial_action_plans", policy["remedial_action_plan_id"])
    site = db.get("sites", plan["site_id"]) if plan is not None else None
    if actor_id() != policy["insurer_party_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the quoting insurer may bind the policy.")
    if site is not None:
        derive.assert_not_frozen(site)
    if policy["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_POLICY_STATE",
                       "Only a QUOTED policy may be bound.")
    if plan is None or plan["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "The parent plan must be APPROVED before binding.")

    floor = calc.bind_attachment_floor(plan["total_estimate_cents"])
    if int(policy["attachment_point_cents"]) < floor:
        raise ApiError("ERR_ATTACHMENT_POINT_TOO_LOW",
                       "The attachment point must be at least %d cents." % floor)
    if int(policy["limit_cents"]) < MIN_LIMIT_CENTS:
        raise ApiError("ERR_LIMIT_BELOW_MINIMUM",
                       "The limit must be at least %d cents." % MIN_LIMIT_CENTS)

    policy["status"] = "BOUND"
    policy["bound_at"] = db.now_ts()
    db.touch(policy)

    bound_premiums = 0
    for other in db.all_rows("cost_cap_policies"):
        if (other["remedial_action_plan_id"] == plan["id"]
                and other["status"] == "BOUND"):
            bound_premiums += int(other["premium_cents"])
    plan["total_funding_need_cents"] = (int(plan["total_estimate_cents"])
                                       + bound_premiums)
    db.touch(plan)
    if site is not None:
        derive.rederive_funding(site)
    return response.object_response(dump_policy(policy))
