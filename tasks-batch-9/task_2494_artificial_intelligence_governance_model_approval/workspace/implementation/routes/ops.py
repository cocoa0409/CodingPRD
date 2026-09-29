"""Reconciliation read, the logical clock setter and the governance sweep."""
from decimal import Decimal

from flask import Blueprint

import clock
import constants
import db
import response
import validators as v
from middleware import authorize
from services import cascades

bp = Blueprint("ops", __name__)

_SYSTEM_ACTOR = "system"


# --- 48. GET /inventory-summary ----------------------------------------
@bp.get("/inventory-summary")
@authorize(constants.GOVERNANCE_OFFICER)
def inventory_summary():
    business_unit = v.query_str("business_unit")
    final_risk_tier = v.query_str("final_risk_tier")
    filtered = business_unit is not None or final_risk_tier is not None

    use_cases = db.all_of(db.use_cases)
    if business_unit is not None:
        use_cases = [u for u in use_cases if u["business_unit"] == business_unit]
    if final_risk_tier is not None:
        use_cases = [u for u in use_cases if u["final_risk_tier"] == final_risk_tier]
    scope = {u["id"] for u in use_cases}

    inventory = [u for u in use_cases if u["status"] in constants.INVENTORY_STATUSES]
    portfolio_reach = sum(u["deployed_headcount_reach"] for u in inventory)
    portfolio_reach_high = sum(
        u["deployed_headcount_reach"] for u in inventory if u["final_risk_tier"] == "HIGH"
    )

    gates = db.all_of(db.review_gates)
    entries = db.all_of(db.ledger_entries)
    incidents = db.all_of(db.monitoring_incidents)
    shadows = db.all_of(db.shadow_deployments)
    if filtered:
        # a filtered read is a slice of the portfolio: every quantity is scoped to
        # the same use-case set so the two conservation invariants still hold
        gates = [g for g in gates if g["use_case_id"] in scope]
        entries = [e for e in entries if e["use_case_id"] in scope]
        incidents = [i for i in incidents if i["use_case_id"] in scope]
        shadows = [s for s in shadows if s["claimed_use_case_id"] in scope]

    debt_total = sum(
        (g["control_debt_index"] for g in gates if g["status"] != "VOIDED"),
        Decimal("0.00"),
    )
    ledger_reach = sum(e["reach_delta"] for e in entries)
    ledger_debt = sum((e["debt_delta"] for e in entries), Decimal("0.00"))

    summary = {
        "inventory_count": len(inventory),
        "portfolio_approved_reach": portfolio_reach,
        "portfolio_approved_reach_high_tier": portfolio_reach_high,
        "control_debt_index_total": debt_total.quantize(Decimal("0.01")),
        "ledger_reach_balance": ledger_reach,
        "ledger_debt_balance": ledger_debt.quantize(Decimal("0.01")),
        "open_incident_count": sum(
            1 for i in incidents if i["status"] in ("OPEN", "ESCALATED")
        ),
        "unapproved_shadow_count": sum(
            1 for s in shadows if s["status"] in ("DISCOVERED", "GRACE_GRANTED")
        ),
    }
    return response.object_response(summary)


# --- 49. POST /_clock/set_current_utc ----------------------------------
@bp.post("/_clock/set_current_utc")
@authorize(*constants.ALL_ROLES)
def set_current_utc():
    body = v.get_body()
    current_utc = v.as_datetime(body, "current_utc", required=True)
    clock.set_now(current_utc)
    return response.object_response({"current_utc": clock.now()})


# --- 50. POST /_ops/governance-sweep ----------------------------------
@bp.post("/_ops/governance-sweep")
@authorize(constants.GOVERNANCE_OFFICER)
def governance_sweep():
    now = clock.now()
    reassessments_opened = 0
    approvals_suspended = 0
    shadows_enforced = 0
    assets_restricted = 0
    assessments_expired = 0

    # --- step 1: open due reassessments (at-or-after) ---
    for use_case in db.all_of(db.use_cases):
        due_at = use_case["reassessment_due_at"]
        if use_case["status"] != "APPROVED" or due_at is None:
            continue
        if now < due_at:
            continue
        use_case["status"] = "UNDER_REASSESSMENT"
        overdue_at = clock.plus_days(due_at, constants.OVERDUE_GRACE_DAYS)
        use_case["reassessment_status"] = "OVERDUE" if now > overdue_at else "IN_PROGRESS"
        db.touch(use_case)
        reassessments_opened += 1

    # --- step 2: suspend expired approvals (strictly after) ---
    for use_case in db.all_of(db.use_cases):
        expires_at = use_case["approval_expires_at"]
        if use_case["status"] not in ("APPROVED", "UNDER_REASSESSMENT"):
            continue
        if expires_at is None or now <= expires_at:
            continue
        cascades.suspend_use_case(
            use_case,
            _SYSTEM_ACTOR,
            "approval suspended by the governance sweep because it expired at %s"
            % clock.iso(expires_at),
        )
        approvals_suspended += 1

    # --- step 3: enforce elapsed shadow deployments (strictly after) ---
    for shadow in db.all_of(db.shadow_deployments):
        deadline = shadow["grace_deadline_at"]
        if shadow["status"] not in ("DISCOVERED", "GRACE_GRANTED"):
            continue
        if deadline is None or now <= deadline:
            continue
        # hop 1
        shadow["status"] = "ENFORCED_BLOCK"
        db.touch(shadow)
        shadows_enforced += 1
        ledger_use_case_id = shadow["claimed_use_case_id"]
        if ledger_use_case_id is not None and ledger_use_case_id in db.use_cases:
            cascades.append_ledger(
                ledger_use_case_id,
                "SHADOW_ENFORCED",
                _SYSTEM_ACTOR,
                "shadow deployment %s enforced after its grace deadline %s elapsed"
                % (shadow["id"], clock.iso(deadline)),
            )
        # hop 2 + hop 3
        asset = db.model_assets.get(shadow["model_asset_id"])
        if asset is not None:
            asset["enforced_shadow_count"] = asset["enforced_shadow_count"] + 1
            restricted, expired = cascades.restrict_asset(
                asset, ledger_use_case_id, _SYSTEM_ACTOR
            )
            if restricted:
                assets_restricted += 1
            assessments_expired += expired
            if not restricted:
                db.touch(asset)

    return response.object_response(
        {
            "reassessments_opened": reassessments_opened,
            "approvals_suspended": approvals_suspended,
            "shadows_enforced": shadows_enforced,
            "assets_restricted": assets_restricted,
            "assessments_expired": assessments_expired,
        }
    )
