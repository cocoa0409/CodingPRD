"""RepossessionOrder / RepossessionAssignment routes (PRD 3.9)."""
from flask import Blueprint

import db
import lookups
import calculations as calc
import device_service
from clock import get_now
from errors import err
from middleware import authenticate, require_role
from response import success, list_success
from serialize import public
from timeutil import iso_now, parse_iso, add_days
from validate import get_body, require_str, require_int, parse_pagination, paginate

bp = Blueprint("repossession", __name__)


def _sorted_public(entities):
    rows = sorted(entities, key=lambda e: e["_seq"])
    return [public(e) for e in rows]


# ---------------------------------------------------------------------------
# Open a repossession order directly (PRD 3.9)
# ---------------------------------------------------------------------------
@bp.route("/atl/repossession-orders", methods=["POST"])
def create_order():
    _, role = authenticate()
    require_role(role, {"RecoveryManager"})
    body = get_body()

    loan_id = require_str(body, "loan_id")
    loan = lookups.get_or_404(db.loans, loan_id)

    # Cross-entity guard (priority 8): loan must be in DEFAULT (PRD 3.9).
    if loan["delinquency_status"] != "DEFAULT":
        raise err("ERR_LOAN_NOT_IN_DEFAULT", "loan not in DEFAULT")

    # No non-terminal repossession order may already exist (PRD 3.9).
    if lookups.active_repo_for_loan(loan_id) is not None:
        raise err("ERR_ACTIVE_REPO_EXISTS", "an active repossession order already exists")

    order = db.common_fields(with_version=True)
    order.update({
        "loan_id": loan["id"],
        "vehicle_id": loan["vehicle_id"],
        "recovered_at": None,
        "redemption_deadline": None,
        "sale_proceeds_cents": None,
        "deficiency_cents": None,
        "status": "ORDERED",
    })
    db.repossession_orders[order["id"]] = order

    # Issue STARTER_DISABLE to the vehicle's device (PRD 3.9).
    device = lookups.device_for_vehicle(loan["vehicle_id"])
    device_service.cascade_starter_disable(device)

    return success(public(order), status=201)


@bp.route("/atl/repossession-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    _, role = authenticate()
    require_role(role, {"RecoveryManager", "LoanServicer", "ComplianceAdmin"})
    order = lookups.get_or_404(db.repossession_orders, order_id)
    return success(public(order), status=200)


@bp.route("/atl/loans/<loan_id>/repossession-orders", methods=["GET"])
def list_loan_orders(loan_id):
    _, role = authenticate()
    require_role(role, {"RecoveryManager", "LoanServicer", "ComplianceAdmin"})
    lookups.get_or_404(db.loans, loan_id)
    limit, offset = parse_pagination()
    rows = [o for o in db.repossession_orders.values() if o["loan_id"] == loan_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))


# ---------------------------------------------------------------------------
# Assignments (PRD 3.9) — half-open windows
# ---------------------------------------------------------------------------
def _overlaps_half_open(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: adjacency at an endpoint does NOT overlap."""
    return a_start < b_end and b_start < a_end


@bp.route("/atl/repossession-orders/<order_id>/assignments", methods=["POST"])
def create_assignment(order_id):
    _, role = authenticate()
    require_role(role, {"RecoveryManager"})
    order = lookups.get_or_404(db.repossession_orders, order_id)
    body = get_body()

    agent_name = require_str(body, "agent_name")
    window_start = require_str(body, "window_start")
    window_end = require_str(body, "window_end")

    ws = parse_iso(window_start)
    we = parse_iso(window_end)

    # Range check (PRD 2.6 step 6): window_end strictly after window_start.
    if not (we > ws):
        raise err("ERR_VALIDATION_RANGE", "window_end must be after window_start")

    # Overlap with another assignment on the same order (half-open) (PRD 3.9).
    for existing in lookups.assignments_for_order(order_id):
        es = parse_iso(existing["window_start"])
        ee = parse_iso(existing["window_end"])
        if _overlaps_half_open(ws, we, es, ee):
            raise err("ERR_ASSIGNMENT_WINDOW_OVERLAP", "assignment window overlaps an existing window")

    assignment = db.common_fields(with_version=True)
    assignment.update({
        "repossession_order_id": order["id"],
        "agent_name": agent_name,
        "window_start": iso_now(ws),
        "window_end": iso_now(we),
    })
    db.assignments[assignment["id"]] = assignment
    return success(public(assignment), status=201)


@bp.route("/atl/repossession-orders/<order_id>/assignments", methods=["GET"])
def list_assignments(order_id):
    _, role = authenticate()
    require_role(role, {"RecoveryManager", "ComplianceAdmin"})
    lookups.get_or_404(db.repossession_orders, order_id)
    limit, offset = parse_pagination()
    rows = [a for a in db.assignments.values() if a["repossession_order_id"] == order_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))


# ---------------------------------------------------------------------------
# Order lifecycle (PRD 3.9)
# ---------------------------------------------------------------------------
@bp.route("/atl/repossession-orders/<order_id>/assign", methods=["POST"])
def assign_order(order_id):
    _, role = authenticate()
    require_role(role, {"RecoveryManager"})
    order = lookups.get_or_404(db.repossession_orders, order_id)

    # State legality (priority 6) before the cross-entity DEFAULT guard (priority 8).
    if order["status"] != "ORDERED":
        raise err("ERR_INVALID_STATE", "order not in ORDERED")

    loan = db.loans.get(order["loan_id"])
    if loan is None or loan["delinquency_status"] != "DEFAULT":
        raise err("ERR_LOAN_NOT_IN_DEFAULT", "loan not in DEFAULT")

    # At least one assignment must exist (PRD 3.9).
    if not lookups.assignments_for_order(order_id):
        raise err("ERR_INVALID_STATE", "no assignment exists for this order")

    order["status"] = "ASSIGNED"
    db.touch(order)
    return success(public(order), status=200)


@bp.route("/atl/repossession-orders/<order_id>/recover", methods=["POST"])
def recover_order(order_id):
    _, role = authenticate()
    require_role(role, {"RecoveryManager"})
    order = lookups.get_or_404(db.repossession_orders, order_id)

    if order["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "order not in ASSIGNED")

    loan = db.loans.get(order["loan_id"])
    if loan is None or loan["delinquency_status"] != "DEFAULT":
        raise err("ERR_LOAN_NOT_IN_DEFAULT", "loan not in DEFAULT")

    now = get_now()
    borrower = db.borrowers.get(loan["borrower_id"])
    prof = lookups.borrower_regulatory_profile(borrower) if borrower else None
    grace_days = prof["redemption_grace_days"] if prof else 0

    order["recovered_at"] = iso_now(now)
    order["redemption_deadline"] = iso_now(add_days(now, grace_days))
    order["status"] = "RECOVERED"
    db.touch(order)
    return success(public(order), status=200)


@bp.route("/atl/repossession-orders/<order_id>/sell", methods=["POST"])
def sell_order(order_id):
    _, role = authenticate()
    require_role(role, {"RecoveryManager"})
    order = lookups.get_or_404(db.repossession_orders, order_id)
    body = get_body()

    sale_proceeds_cents = require_int(body, "sale_proceeds_cents")
    if sale_proceeds_cents < 0:
        raise err("ERR_VALIDATION_RANGE", "sale_proceeds_cents must be >= 0")

    # State legality (priority 6).
    if order["status"] != "RECOVERED":
        raise err("ERR_INVALID_STATE", "order not in RECOVERED")

    # Redemption grace must have elapsed (priority 14).
    now = get_now()
    deadline = parse_iso(order["redemption_deadline"])
    if now < deadline:
        raise err("ERR_REDEMPTION_GRACE_ACTIVE", "redemption grace not yet elapsed")

    loan = db.loans.get(order["loan_id"])

    deficiency = calc.deficiency_balance(
        loan["principal_balance_cents"], loan["accrued_interest_cents"],
        loan["fees_balance_cents"], sale_proceeds_cents)

    order["sale_proceeds_cents"] = sale_proceeds_cents
    order["deficiency_cents"] = deficiency
    order["status"] = "SOLD"
    db.touch(order)

    # Cascade: Loan OUTSTANDING -> CHARGED_OFF (PRD 3.9).
    if loan["payoff_status"] == "OUTSTANDING":
        loan["payoff_status"] = "CHARGED_OFF"
        # TitleLien FILED -> RELEASED; vehicle CLEAR.
        import loan_service
        loan_service.release_lien_cascade(loan)
        # Borrower -> BARRED.
        borrower = db.borrowers.get(loan["borrower_id"])
        if borrower is not None:
            borrower["status"] = "BARRED"
            db.touch(borrower)
        db.touch(loan)

    return success(public(order), status=200)
