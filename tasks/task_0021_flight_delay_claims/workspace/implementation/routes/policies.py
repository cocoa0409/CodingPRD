"""Policy routes."""

from __future__ import annotations

from flask import Blueprint, jsonify

from db import db, gen_id, now_iso_z
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    raise_api_error,
)
from middleware import require_roles
from response import success_response
from services.common import (
    append_audit,
    check_version,
    get_insurer_or_404,
    get_json_body,
    get_policy_or_404,
    optional_field,
    require_field,
    require_int,
)
from services.reserve import (
    recompute_pessimistic_reserve,
)

bp = Blueprint("policies", __name__)


VALID_DELAY_BASIS = {"DEPARTURE", "ARRIVAL"}
VALID_PAYOUT_MODES = {"FIXED", "ACTUAL_LOSS"}
VALID_CAUSES = {"WEATHER", "ATC", "SECURITY", "AIRLINE", "OTHER"}


def _serialize_policy(p: dict) -> dict:
    return dict(p)


@bp.post("/insurers/<insurer_id>/policies")
@require_roles("PolicyAdmin", "ClaimsAdmin")
def create_policy(insurer_id: str):
    get_insurer_or_404(insurer_id)
    body = get_json_body()

    holder_name = require_field(body, "policy_holder_name", type_=str)
    holder_doc_id = require_field(body, "policy_holder_doc_id", type_=str)
    eff_from = require_int(body, "effective_from_epoch_ms", allow_negative=False)
    eff_to = require_int(body, "effective_to_epoch_ms", allow_negative=False)
    if eff_to <= eff_from:
        raise_api_error(ERR_INVALID_REQUEST,
                        "effective_to_epoch_ms must be > effective_from_epoch_ms.")
    waiting_period = require_int(body, "waiting_period_ms", required=False, default=0)
    if waiting_period is None:
        waiting_period = 0

    delay_basis = require_field(body, "delay_basis", type_=str)
    if delay_basis not in VALID_DELAY_BASIS:
        raise_api_error(ERR_INVALID_REQUEST, "delay_basis must be DEPARTURE or ARRIVAL.")

    payout_mode = require_field(body, "payout_mode", type_=str)
    if payout_mode not in VALID_PAYOUT_MODES:
        raise_api_error(ERR_INVALID_REQUEST, "payout_mode must be FIXED or ACTUAL_LOSS.")

    reimbursement_rate_bps = require_int(body, "reimbursement_rate_bps",
                                         required=False, default=0)
    if reimbursement_rate_bps is None:
        reimbursement_rate_bps = 0

    deductible = require_int(body, "deductible_cents", required=False, default=0)
    if deductible is None:
        deductible = 0

    policy_limit = require_int(body, "policy_limit_cents", allow_negative=False)
    quota_total = require_int(body, "claim_quota_total_cents", allow_negative=False)

    excluded_causes = optional_field(body, "excluded_delay_causes", default=[], type_=list)
    if excluded_causes is None:
        excluded_causes = []
    for c in excluded_causes:
        if c not in VALID_CAUSES:
            raise_api_error(ERR_INVALID_REQUEST, f"Invalid excluded_delay_cause: {c}")

    pol = {
        "id": gen_id(),
        "insurer_id": insurer_id,
        "policy_holder_name": holder_name,
        "policy_holder_doc_id": holder_doc_id,
        "effective_from_epoch_ms": eff_from,
        "effective_to_epoch_ms": eff_to,
        "waiting_period_ms": waiting_period,
        "delay_basis": delay_basis,
        "payout_mode": payout_mode,
        "reimbursement_rate_bps": reimbursement_rate_bps,
        "deductible_cents": deductible,
        "policy_limit_cents": policy_limit,
        "claim_quota_total_cents": quota_total,
        "claim_quota_used_cents": 0,
        "reserve_balance_cents": 0,
        "excluded_delay_causes": list(excluded_causes),
        "status": "ACTIVE",
    }
    db.stamp_create(pol)
    db.policies[pol["id"]] = pol
    return jsonify(success_response(_serialize_policy(pol))), 201


@bp.get("/insurers/<insurer_id>/policies/<policy_id>")
@require_roles("Any")
def get_policy(insurer_id: str, policy_id: str):
    get_insurer_or_404(insurer_id)
    pol = get_policy_or_404(insurer_id, policy_id)
    return jsonify(success_response(_serialize_policy(pol))), 200


@bp.get("/insurers/<insurer_id>/policies/<policy_id>/risk_view")
@require_roles("PolicyAdmin", "ClaimsAdmin", "Auditor")
def policy_risk_view(insurer_id: str, policy_id: str):
    get_insurer_or_404(insurer_id)
    pol = get_policy_or_404(insurer_id, policy_id)
    optimistic = pol.get("reserve_balance_cents", 0) or 0
    pessimistic = recompute_pessimistic_reserve(pol)
    quota_remaining = (pol.get("claim_quota_total_cents", 0) or 0) - (pol.get("claim_quota_used_cents", 0) or 0)
    return jsonify(success_response({
        "optimistic_reserve_cents": optimistic,
        "pessimistic_reserve_cents": pessimistic,
        "claim_quota_remaining_cents": quota_remaining,
    })), 200


@bp.post("/insurers/<insurer_id>/policies/<policy_id>/suspend")
@require_roles("PolicyAdmin")
def suspend_policy(insurer_id: str, policy_id: str):
    get_insurer_or_404(insurer_id)
    pol = get_policy_or_404(insurer_id, policy_id)
    body = get_json_body()
    check_version(body, pol)
    require_field(body, "reason", type_=str)

    if pol["status"] != "ACTIVE":
        raise_api_error(ERR_INVALID_STATE, f"Policy is in status {pol['status']}; cannot suspend.")
    prev = pol["status"]
    pol["status"] = "SUSPENDED"
    db.stamp_update(pol)
    append_audit(insurer_id, "POLICY", pol["id"], "STATUS_CHANGE",
                 {"from": prev, "to": "SUSPENDED", "reason": body["reason"]})
    return jsonify(success_response(_serialize_policy(pol))), 200


@bp.post("/insurers/<insurer_id>/policies/<policy_id>/terminate")
@require_roles("PolicyAdmin")
def terminate_policy(insurer_id: str, policy_id: str):
    get_insurer_or_404(insurer_id)
    pol = get_policy_or_404(insurer_id, policy_id)
    body = get_json_body()
    check_version(body, pol)

    if pol["status"] == "TERMINATED":
        raise_api_error(ERR_INVALID_STATE, "Policy already TERMINATED.")
    prev = pol["status"]
    pol["status"] = "TERMINATED"
    db.stamp_update(pol)
    append_audit(insurer_id, "POLICY", pol["id"], "STATUS_CHANGE",
                 {"from": prev, "to": "TERMINATED"})
    return jsonify(success_response(_serialize_policy(pol))), 200
