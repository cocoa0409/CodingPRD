"""Cross-entity cascade helpers (SCAFFOLD Table 2 side effects / PRD §3).

These functions implement the automatic order transitions, permit application
creation, order closure, and RTO contract creation that state changes trigger.
"""

import db
from services.common import new_id, latest_permit_app_for_order
from services.pricing import (
    compute_order_pricing,
    compute_permit_fee,
    compute_rto_schedule,
    compute_required_deposit_cents,
)
from services.pricing import round_half_up_cents, INSTALLMENT_INTERVAL_DAYS
from decimal import Decimal
from datetime import timedelta


def touch(entity: dict):
    entity["updated_at"] = db.now_iso()


def bump(entity: dict):
    entity["version"] += 1
    touch(entity)


def create_permit_application(order: dict) -> dict:
    """Created when an order enters PERMIT_REVIEW. Pins the jurisdiction's
    current version, snapshots area, computes required/fee. NOT_REQUIRED when
    no permit needed."""
    jurisdiction = db.jurisdictions[order["jurisdiction_id"]]
    permit_required, fee_cents = compute_permit_fee(order["area_sqft"], jurisdiction)
    now = db.now_iso()
    app = {
        "id": new_id(),
        "order_id": order["id"],
        "jurisdiction_id": order["jurisdiction_id"],
        "jurisdiction_version": jurisdiction["version"],
        "area_sqft": order["area_sqft"],
        "permit_required": permit_required,
        "fee_cents": fee_cents,
        "status": "SUBMITTED",
        "decision_note": None,
        "decided_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.permit_applications[app["id"]] = app
    return app


def advance_order_to_ready(order: dict):
    """PERMIT_REVIEW -> READY_TO_SCHEDULE (system)."""
    order["status"] = "READY_TO_SCHEDULE"
    bump(order)


def maybe_close_order(order: dict):
    """COMPLETED -> CLOSED when the order is fully settled (PRD §3.5):
    CASH: collected_cents - refunded_cents >= final_total_cents
    RTO: its RtoContract exists with status == ACTIVE.
    """
    if order["status"] != "COMPLETED":
        return
    if order["purchase_type"] == "CASH":
        if order["collected_cents"] - order["refunded_cents"] >= (order.get("final_total_cents") or 0):
            order["status"] = "CLOSED"
            bump(order)
    else:
        contract = None
        for r in db.rto_contracts.values():
            if r["order_id"] == order["id"]:
                contract = r
                break
        if contract is not None and contract["status"] == "ACTIVE":
            order["status"] = "CLOSED"
            bump(order)


def create_rto_contract(order: dict) -> dict:
    """Created at RTO order completion (PRD §3.7)."""
    total = order["final_total_cents"]
    term = order["rto_term_months"]
    monthly, final = compute_rto_schedule(total, term)
    completed_date = order["completed_at"][0:10]
    from services.pricing import db_parse_date
    first_due = (db_parse_date(completed_date) + timedelta(days=INSTALLMENT_INTERVAL_DAYS)).isoformat()
    now = db.now_iso()
    contract = {
        "id": new_id(),
        "order_id": order["id"],
        "term_months": term,
        "total_contract_cents": total,
        "monthly_payment_cents": monthly,
        "final_payment_cents": final,
        "amount_applied_cents": 0,
        "remaining_balance_cents": total,
        "accrued_late_fees_cents": 0,
        "written_off_cents": 0,
        "delinquency_episodes": 0,
        "first_due_date": first_due,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.rto_contracts[contract["id"]] = contract
    return contract
