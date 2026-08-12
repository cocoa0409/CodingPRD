"""Policy endpoints: reads, premium-mode change, dividend-option change,
billing cycles, premium payments (PRD §3.4, §2.10)."""
from flask import Blueprint, request

import domain
import errors
from db import store
from middleware import (
    require_auth, parse_pagination, json_body, require_fields, require_int,
    ALL_ROLES,
)
from response import ok_object, ok_list
from services import calculations as calc
from services import engine

bp = Blueprint("policies", __name__)


def get_policy_or_404(policy_id):
    policy = store.policies.get(policy_id)
    if policy is None:
        raise errors.not_found(errors.ERR_POLICY_NOT_FOUND, "policy")
    return policy


def check_policyholder_ownership(ctx, policy):
    """For Policyholder-role writes, X-User-ID is the InsuredPerson id and must
    match the policy's insured-person reference (PRD §2.1)."""
    if ctx.role == "Policyholder" and policy["insured_person_id"] != ctx.user_id:
        raise errors.insufficient_permissions()


def _paged(records, serializer):
    limit, offset = parse_pagination()
    ordered = domain.sorted_by_creation(records)
    return ok_list([serializer(r) for r in ordered[offset:offset + limit]],
                   limit, offset, len(ordered))


@bp.route("/policies", methods=["GET"])
def list_policies():
    require_auth(ALL_ROLES)
    records = list(store.policies.values())
    filters = {
        "insured_person_id": request.args.get("insured_person_id"),
        "form_status": request.args.get("form_status"),
        "premium_payment_status": request.args.get("premium_payment_status"),
        "application_id": request.args.get("application_id"),
        "product_template_id": request.args.get("product_template_id"),
    }
    for field, value in filters.items():
        if value is not None:
            records = [p for p in records if p.get(field) == value]
    return _paged(records, domain.serialize_policy)


@bp.route("/policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    require_auth(ALL_ROLES)
    return ok_object(domain.serialize_policy(get_policy_or_404(policy_id)))


@bp.route("/policies/<policy_id>/mode-change", methods=["POST"])
def mode_change(policy_id):
    require_auth(["Agent"])
    policy = get_policy_or_404(policy_id)
    if policy["form_status"] in domain.POLICY_FORM_TERMINAL:
        raise errors.already_terminal("Policy is in a terminal form state")
    body = json_body(required=True)
    require_fields(body, ["premium_mode", "expected_policy_version"])
    new_mode = body["premium_mode"]
    if new_mode not in domain.PREMIUM_MODES:
        raise errors.invalid_request("invalid premium_mode")
    expected = body["expected_policy_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_policy_version must be an integer")
    # OCC is the final check (priority 13)
    if expected != policy["version"]:
        raise errors.stale_version()

    template = domain.template_of(policy)
    policy["premium_mode"] = new_mode
    policy["modal_premium_cents"] = calc.modal_premium(
        policy["face_amount_cents"],
        template["base_monthly_premium_rate_per_thousand_cents"],
        policy["underwriting_class"],
        policy.get("_substandard_extra_pct_bps", 0),
        new_mode)
    # Apply the new modal premium to future (unpaid) cycles
    for cycle in engine.policy_cycles(policy):
        if cycle["status"] in ("OPEN", "PARTIALLY_PAID"):
            cycle["due_amount_cents"] = policy["modal_premium_cents"]
            if cycle["paid_amount_cents"] >= cycle["due_amount_cents"]:
                cycle["status"] = "PAID"
            domain.touch(cycle)
    paid_ends = [c["period_end_date"] for c in engine.policy_cycles(policy)
                 if c["status"] == "PAID"]
    if paid_ends:
        policy["paid_to_date"] = max(paid_ends)
    domain.touch_policy(policy)
    return ok_object(domain.serialize_policy(policy))


@bp.route("/policies/<policy_id>/dividend-option", methods=["POST"])
def dividend_option(policy_id):
    ctx = require_auth(["Policyholder"])
    policy = get_policy_or_404(policy_id)
    if policy["form_status"] in domain.POLICY_FORM_TERMINAL:
        raise errors.already_terminal("Policy is in a terminal form state")
    check_policyholder_ownership(ctx, policy)
    body = json_body(required=True)
    require_fields(body, ["dividend_option", "expected_policy_version"])
    option = body["dividend_option"]
    if option not in domain.DIVIDEND_OPTIONS:
        raise errors.invalid_request("invalid dividend_option")
    expected = body["expected_policy_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_policy_version must be an integer")
    if expected != policy["version"]:
        raise errors.stale_version()
    policy["dividend_option"] = option
    domain.touch_policy(policy)
    return ok_object(domain.serialize_policy(policy))


@bp.route("/policies/<policy_id>/billing-cycles", methods=["GET"])
def list_billing_cycles(policy_id):
    require_auth(ALL_ROLES)
    policy = get_policy_or_404(policy_id)
    cycles = [c for c in store.billing_cycles.values() if c["policy_id"] == policy["id"]]
    limit, offset = parse_pagination()
    ordered = sorted(cycles, key=lambda c: c["cycle_index"])
    return ok_list([domain.serialize_cycle(c) for c in ordered[offset:offset + limit]],
                   limit, offset, len(ordered))


@bp.route("/policies/<policy_id>/premium-payments", methods=["POST"])
def premium_payment(policy_id):
    require_auth(["Agent"])
    policy = get_policy_or_404(policy_id)
    body = json_body(required=True)
    amount = require_int(body, "amount_cents", minimum=1)
    engine.record_premium_payment(policy, amount)
    return ok_object(domain.serialize_policy(policy))
