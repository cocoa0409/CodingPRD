"""FeeBillingRule create / patch with optimistic concurrency."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError,
    ERR_DUPLICATE_RULE_CODE,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    ERR_VERSION_CONFLICT,
)
from middleware import require_roles
from response import success
from services.audit import write_audit
from services.common import bump, snapshot, stamp_create
from utils import get_body, require_field, to_decimal

bp = Blueprint("fee_billing_rules", __name__)

VALID_KINDS = {"PER_SQM_MONTHLY", "FIXED_AMOUNT_MONTHLY"}


@bp.post("/fee-billing-rules")
@require_roles("PropertyManager")
def create_rule():
    body = get_body()
    rule_code = require_field(body, "rule_code")
    kind = require_field(body, "kind")
    rate = require_field(body, "rate")
    late_fee_daily_rate = body.get("late_fee_daily_rate", 0.0005)
    late_fee_cap_pct = body.get("late_fee_cap_pct", 0.30)

    if kind not in VALID_KINDS:
        raise APIError(ERR_VALIDATION, "kind must be PER_SQM_MONTHLY or FIXED_AMOUNT_MONTHLY.", 422)

    rate_d = to_decimal(rate)
    if rate_d < 0:
        raise APIError(ERR_VALIDATION, "rate must be >= 0.", 422)

    daily_d = to_decimal(late_fee_daily_rate)
    if daily_d < 0 or daily_d > to_decimal("0.01"):
        raise APIError(ERR_VALIDATION, "late_fee_daily_rate must be in [0, 0.01].", 422)

    cap_d = to_decimal(late_fee_cap_pct)
    if cap_d < 0 or cap_d > to_decimal("1"):
        raise APIError(ERR_VALIDATION, "late_fee_cap_pct must be in [0, 1].", 422)

    # Uniqueness across ACTIVE rules
    for existing in db.fee_billing_rules.values():
        if existing.get("rule_code") == rule_code and existing.get("rule_status") == "ACTIVE":
            raise APIError(
                ERR_DUPLICATE_RULE_CODE,
                f"Active rule with rule_code={rule_code} already exists.",
                409,
            )

    rule = {
        "rule_code": rule_code,
        "kind": kind,
        "rate": float(rate_d),
        "late_fee_daily_rate": float(daily_d),
        "late_fee_cap_pct": float(cap_d),
        "rule_status": "ACTIVE",
    }
    stamp_create(rule)
    db.fee_billing_rules[rule["id"]] = rule
    write_audit(
        subject_kind="FEE_BILLING_RULE",
        subject_id=rule["id"],
        action="RULE_CREATED",
        before={},
        after=snapshot(rule),
    )
    return success(rule, status=201)


@bp.patch("/fee-billing-rules/<rid>")
@require_roles("PropertyManager")
def patch_rule(rid):
    rule = db.fee_billing_rules.get(rid)
    if rule is None:
        raise APIError(ERR_NOT_FOUND, f"Rule {rid} not found.", 404)

    body = get_body()
    if "version" in body and body["version"] != rule.get("version"):
        raise APIError(
            ERR_VERSION_CONFLICT,
            f"Stale version (got {body['version']}, current {rule.get('version')}).",
            409,
        )

    before = snapshot(rule)
    if "rate" in body:
        rate_d = to_decimal(body["rate"])
        if rate_d < 0:
            raise APIError(ERR_VALIDATION, "rate must be >= 0.", 422)
        rule["rate"] = float(rate_d)
    if "late_fee_daily_rate" in body:
        d = to_decimal(body["late_fee_daily_rate"])
        if d < 0 or d > to_decimal("0.01"):
            raise APIError(ERR_VALIDATION, "late_fee_daily_rate out of range.", 422)
        rule["late_fee_daily_rate"] = float(d)
    if "late_fee_cap_pct" in body:
        d = to_decimal(body["late_fee_cap_pct"])
        if d < 0 or d > to_decimal("1"):
            raise APIError(ERR_VALIDATION, "late_fee_cap_pct out of range.", 422)
        rule["late_fee_cap_pct"] = float(d)

    bump(rule)
    write_audit(
        subject_kind="FEE_BILLING_RULE",
        subject_id=rule["id"],
        action="RATE_CHANGED",
        before=before,
        after=snapshot(rule),
    )
    return success(rule)
