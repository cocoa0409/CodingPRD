"""POS transactions and settlements."""
from flask import Blueprint

import serialize
from calc import compute_final, compute_provisional
from store import db
from util import (body_json, err, get_or_404, list_response, new_id, parse_dt,
                  req_int, req_str, require_role, stamp_new, success, touch)

bp = Blueprint("money", __name__)

TX_READ_ROLES = ("FestivalDirector", "VendorManager", "OperationsLead",
                 "FinanceLead", "Vendor")
SETTLEMENT_READ_ROLES = ("FestivalDirector", "VendorManager", "FinanceLead", "Vendor")


def _vendor_of_assignment(assignment):
    return db.applications[assignment["application_id"]]["vendor_id"]


def _settlement_for_assignment(assignment_id):
    return next((s for s in db.settlements.values()
                 if s["assignment_id"] == assignment_id), None)


# ---------------------------------------------------------------------------
# POS transactions
# ---------------------------------------------------------------------------

@bp.route("/pos-transactions", methods=["POST"])
def report_transaction():
    uid, role = require_role("Vendor", "FinanceLead")
    b = body_json()
    # (4) Body FK existence.
    assignment = None
    if b.get("assignment_id") is not None:
        assignment = get_or_404(db.assignments, b.get("assignment_id"),
                                "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")

    # (5) Entity-backed ownership for Vendor actors.
    if role == "Vendor" and assignment is not None:
        if _vendor_of_assignment(assignment) != uid:
            err("ERR_NOT_RESOURCE_OWNER", 403,
                "A vendor may only report sales for its own assignments")

    # Idempotent replay: a duplicate (assignment_id, idempotency_key) returns
    # HTTP 200 with the existing transaction and creates nothing.
    key = b.get("idempotency_key")
    if assignment is not None and isinstance(key, str) and key:
        existing = next(
            (t for t in db.transactions.values()
             if t["assignment_id"] == assignment["id"]
             and t["idempotency_key"] == key),
            None,
        )
        if existing is not None:
            return success(serialize.serialize_transaction(existing), 200)

    # (6) Festival posture gate.
    if assignment is not None:
        festival = db.festivals[assignment["festival_id"]]
        if festival["status"] != "LIVE":
            err("ERR_FESTIVAL_NOT_LIVE", 409, "Festival is not LIVE")

    # (8) State legality + request shape.
    if assignment is not None and assignment["status"] != "ACTIVE":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Assignment must be ACTIVE to report a sale")
    amount = req_int(b, "amount_cents")
    occurred_at = parse_dt(b.get("occurred_at"), "occurred_at")
    req_str(b, "idempotency_key")
    if assignment is None:
        get_or_404(db.assignments, b.get("assignment_id"),
                   "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")

    # (11) Temporal: occurred_at inside [event_start, event_end] inclusive.
    festival = db.festivals[assignment["festival_id"]]
    if not (festival["event_start"] <= occurred_at <= festival["event_end"]):
        err("ERR_TRANSACTION_OUT_OF_WINDOW", 400,
            "occurred_at must lie inside [event_start, event_end]")

    # (13) Fiscal: positive amount.
    if amount < 1:
        err("ERR_INVALID_AMOUNT", 400, "amount_cents must be >= 1")

    tx = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "assignment_id": assignment["id"],
        "festival_id": assignment["festival_id"],
        "amount_cents": amount,
        "occurred_at": occurred_at,
        "idempotency_key": key,
        "status": "REPORTED",
    })
    db.transactions[tx["id"]] = tx
    return success(serialize.serialize_transaction(tx), 201)


@bp.route("/pos-transactions", methods=["GET"])
def list_transactions():
    require_role(*TX_READ_ROLES)
    return list_response(list(db.transactions.values()),
                         serialize.serialize_transaction, {
                             "assignment_id": "assignment_id",
                             "festival_id": "festival_id",
                             "status": "status",
                             "idempotency_key": "idempotency_key",
                         })


@bp.route("/pos-transactions/<transactionId>", methods=["GET"])
def get_transaction(transactionId):
    require_role(*TX_READ_ROLES)
    tx = get_or_404(db.transactions, transactionId,
                    "ERR_TRANSACTION_NOT_FOUND", "Transaction")
    return success(serialize.serialize_transaction(tx))


@bp.route("/pos-transactions/<transactionId>/void", methods=["POST"])
def void_transaction(transactionId):
    require_role("FinanceLead")
    tx = get_or_404(db.transactions, transactionId,
                    "ERR_TRANSACTION_NOT_FOUND", "Transaction")
    b = body_json()
    # (4) A settlement must exist for the transaction's assignment.
    settlement = _settlement_for_assignment(tx["assignment_id"])
    if settlement is None:
        err("ERR_SETTLEMENT_NOT_FOUND", 404,
            "No settlement exists for the transaction's assignment")

    # (8) Request shape + state legality.
    expected_version = req_int(b, "expected_settlement_version")
    if tx["status"] != "REPORTED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"void is not permitted from {tx['status']}")
    if settlement["status"] not in ("OPEN", "RECONCILING", "DISPUTED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"Settlement in {settlement['status']} no longer accepts voids")

    # (13) Optimistic concurrency on the parent settlement.
    if expected_version != settlement["version"]:
        err("ERR_STALE_SETTLEMENT_VERSION", 412,
            "expected_settlement_version does not match the settlement's version")

    tx["status"] = "VOIDED"
    touch(tx)
    touch(settlement)  # every successful void advances settlement.version by 1
    if settlement["status"] == "RECONCILING":
        compute_provisional(settlement)
    return success(serialize.serialize_transaction(tx))


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------

@bp.route("/settlements", methods=["POST"])
def create_settlement():
    require_role("FinanceLead")
    b = body_json()
    # (4) Body FK existence.
    assignment = None
    if b.get("assignment_id") is not None:
        assignment = get_or_404(db.assignments, b.get("assignment_id"),
                                "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")

    # (6) Festival posture gate: LIVE or SETTLEMENT.
    if assignment is not None:
        festival = db.festivals[assignment["festival_id"]]
        if festival["status"] not in ("LIVE", "SETTLEMENT"):
            err("ERR_FESTIVAL_NOT_IN_SETTLEMENT", 409,
                "Festival is neither LIVE nor SETTLEMENT")

    req_str(b, "assignment_id")
    if assignment is None:
        get_or_404(db.assignments, b.get("assignment_id"),
                   "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")

    # (9) Exactly one settlement per assignment, ever.
    if _settlement_for_assignment(assignment["id"]) is not None:
        err("ERR_SETTLEMENT_EXISTS", 409,
            "A settlement already exists for this assignment")

    settlement = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "assignment_id": assignment["id"],
        "festival_id": assignment["festival_id"],
        "status": "OPEN",
        "provisional_gross_cents": None,
        "provisional_share_cents": None,
        "provisional_payout_cents": None,
        "gross_sales_cents": None,
        "festival_share_cents": None,
        "fine_deduction_cents": None,
        "vendor_payout_cents": None,
        "vendor_balance_due_cents": None,
        "reconciled_by_user_id": None,
        "finalized_by_user_id": None,
        "dispute_reason": None,
    })
    db.settlements[settlement["id"]] = settlement
    return success(serialize.serialize_settlement(settlement), 201)


@bp.route("/settlements", methods=["GET"])
def list_settlements():
    require_role(*SETTLEMENT_READ_ROLES)
    return list_response(list(db.settlements.values()),
                         serialize.serialize_settlement, {
                             "assignment_id": "assignment_id",
                             "festival_id": "festival_id",
                             "status": "status",
                         })


@bp.route("/settlements/<settlementId>", methods=["GET"])
def get_settlement(settlementId):
    require_role(*SETTLEMENT_READ_ROLES)
    settlement = get_or_404(db.settlements, settlementId,
                            "ERR_SETTLEMENT_NOT_FOUND", "Settlement")
    return success(serialize.serialize_settlement(settlement))


@bp.route("/settlements/<settlementId>/reconcile", methods=["POST"])
def reconcile_settlement(settlementId):
    uid, _ = require_role("FinanceLead")
    settlement = get_or_404(db.settlements, settlementId,
                            "ERR_SETTLEMENT_NOT_FOUND", "Settlement")
    if settlement["status"] not in ("OPEN", "DISPUTED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"reconcile is not permitted from {settlement['status']}")
    compute_provisional(settlement)
    settlement["reconciled_by_user_id"] = uid
    settlement["status"] = "RECONCILING"
    touch(settlement)
    return success(serialize.serialize_settlement(settlement))


@bp.route("/settlements/<settlementId>/dispute", methods=["POST"])
def dispute_settlement(settlementId):
    uid, _ = require_role("Vendor")
    settlement = get_or_404(db.settlements, settlementId,
                            "ERR_SETTLEMENT_NOT_FOUND", "Settlement")
    assignment = db.assignments[settlement["assignment_id"]]
    if _vendor_of_assignment(assignment) != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "A vendor may only dispute its own settlement")
    b = body_json()
    if settlement["status"] != "RECONCILING":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"dispute is not permitted from {settlement['status']}")
    reason = req_str(b, "reason")
    settlement["status"] = "DISPUTED"
    settlement["dispute_reason"] = reason
    touch(settlement)
    return success(serialize.serialize_settlement(settlement))


@bp.route("/settlements/<settlementId>/finalize", methods=["POST"])
def finalize_settlement(settlementId):
    uid, _ = require_role("FinanceLead")
    settlement = get_or_404(db.settlements, settlementId,
                            "ERR_SETTLEMENT_NOT_FOUND", "Settlement")
    # (3) Segregation of duties: finalizer != reconciler.
    if (settlement["reconciled_by_user_id"] is not None
            and uid == settlement["reconciled_by_user_id"]):
        err("ERR_SOD_SETTLEMENT_FINALIZE", 403,
            "The reconciler may not finalize the same settlement")

    # (8) State legality.
    if settlement["status"] != "RECONCILING":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"finalize is not permitted from {settlement['status']}")

    assignment = db.assignments[settlement["assignment_id"]]
    # (9) Fine-resolution gate.
    if any(f["assignment_id"] == assignment["id"]
           and f["status"] in ("ISSUED", "DISPUTED")
           for f in db.fines.values()):
        err("ERR_FINES_UNRESOLVED", 409,
            "Fines in ISSUED or DISPUTED block finalization")

    # (11) Temporal: strictly past event_end.
    festival = db.festivals[assignment["festival_id"]]
    if not db.clock > festival["event_end"]:
        err("ERR_FESTIVAL_NOT_ENDED", 409,
            "Logical clock is not past event_end")

    compute_final(settlement)
    settlement["finalized_by_user_id"] = uid
    settlement["status"] = "FINALIZED"
    touch(settlement)

    # Sweep remaining REPORTED transactions to SETTLED.
    for tx in db.transactions.values():
        if tx["assignment_id"] == assignment["id"] and tx["status"] == "REPORTED":
            tx["status"] = "SETTLED"
            touch(tx)

    # Auto-create the performance review (PENDING) if none exists.
    if not any(r["assignment_id"] == assignment["id"] for r in db.reviews.values()):
        review = stamp_new({
            "id": new_id(),
            "_seq": db.next_seq(),
            "assignment_id": assignment["id"],
            "festival_id": assignment["festival_id"],
            "vendor_id": _vendor_of_assignment(assignment),
            "status": "PENDING",
            "sales_percentile": None,
            "compliance_component": None,
            "operations_component": None,
            "official_score": None,
            "strict_score": None,
        })
        db.reviews[review["id"]] = review

    return success(serialize.serialize_settlement(settlement))


@bp.route("/settlements/<settlementId>/mark-paid", methods=["POST"])
def mark_settlement_paid(settlementId):
    require_role("FinanceLead")
    settlement = get_or_404(db.settlements, settlementId,
                            "ERR_SETTLEMENT_NOT_FOUND", "Settlement")
    if settlement["status"] != "FINALIZED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"mark-paid is not permitted from {settlement['status']}")
    settlement["status"] = "PAID"
    touch(settlement)
    return success(serialize.serialize_settlement(settlement))
