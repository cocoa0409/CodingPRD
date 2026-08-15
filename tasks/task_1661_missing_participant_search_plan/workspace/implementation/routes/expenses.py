"""ExpenseAllocation endpoints (PRD section 3.7): pinned rounding order --
round each share first, reconcile the remainder second."""

import db
import services
from errors import (
    ApiError,
    ERR_CASE_INVALID_STATE,
    ERR_EXPENSE_EXCEEDS_PARTICIPANT_BALANCE,
    ERR_INSUFFICIENT_REMAINING_BALANCE,
    ERR_NO_ELIGIBLE_PARTICIPANTS,
    ERR_PAYOUTS_ALREADY_COMMITTED,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import public_expense, public_case
from util import (
    body_fk,
    body_json,
    check_shape,
    paginate,
    pagination_params,
    path_entity,
    rhu,
)

bp = make_blueprint("expenses")

EXPENSE_CASE_STATUSES = {
    "TERMINATION_EFFECTIVE",
    "DISTRIBUTION_IN_PROGRESS",
    "FINAL_RECONCILIATION",
}

ELIGIBLE_STATES = {"PENDING_ELECTION", "ELECTION_SUBMITTED", "RESTORED"}


@bp.post("/expense-allocations")
def create_expense_allocation():
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {
        "termination_case_id": {"type": "string", "required": True},
        "method": {
            "type": "enum",
            "values": {"PRO_RATA_BY_BALANCE", "EQUAL_PER_CAPITA"},
            "required": True,
        },
        "total_expense_cents": {"type": "integer", "min": 1, "required": True},
        "description": {"type": "string", "required": True},
    })
    case = body_fk(body, "termination_case_id", "cases", "termination case")
    # Priority 6: case-status gate.
    if case["status"] not in EXPENSE_CASE_STATUSES:
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "expense allocation requires TERMINATION_EFFECTIVE, "
            "DISTRIBUTION_IN_PROGRESS, or FINAL_RECONCILIATION",
        )
    participants = services.case_participants(case["id"])
    # Priority 9: structural constraints.
    if any(p["distribution_status"] == "ELECTION_ACCEPTED" for p in participants):
        raise ApiError(
            ERR_PAYOUTS_ALREADY_COMMITTED, 409,
            "payout amounts are already committed (a participant is "
            "ELECTION_ACCEPTED)",
        )
    eligible = [
        p for p in participants if p["distribution_status"] in ELIGIBLE_STATES
    ]
    if not eligible:
        raise ApiError(
            ERR_NO_ELIGIBLE_PARTICIPANTS, 409,
            "the eligible participant set is empty",
        )
    # Priority 12, fiscal rule one: the total must fit the remaining ledger.
    total = body["total_expense_cents"]
    if total > public_case(case)["remaining_undistributed_cents"]:
        raise ApiError(
            ERR_INSUFFICIENT_REMAINING_BALANCE, 402,
            "the expense exceeds the case's remaining undistributed balance",
        )
    # Pinned rounding order: round each participant's share FIRST.
    if body["method"] == "PRO_RATA_BY_BALANCE":
        sum_vested = sum(services.vested_balance(p) for p in eligible)
        shares = {
            p["id"]: (
                rhu(total * services.vested_balance(p), sum_vested)
                if sum_vested > 0
                else 0
            )
            for p in eligible
        }
    else:  # EQUAL_PER_CAPITA
        shares = {p["id"]: rhu(total, len(eligible)) for p in eligible}
    # Reconcile the remainder SECOND: it lands on the eligible participant
    # with the largest vested_balance_cents, ties broken by earliest
    # created_at.
    remainder = total - sum(shares.values())
    recipient = sorted(
        eligible,
        key=lambda p: (-services.vested_balance(p), p["created_at"], p["_seq"]),
    )[0]
    shares[recipient["id"]] += remainder
    # Priority 12, fiscal rule two: no share may exceed its participant's
    # vested balance. (Checked before any mutation: the allocation is atomic.)
    for p in eligible:
        if shares[p["id"]] > services.vested_balance(p):
            raise ApiError(
                ERR_EXPENSE_EXCEEDS_PARTICIPANT_BALANCE, 422,
                "a computed share exceeds its participant's vested balance",
            )
    for p in eligible:
        p["_expense_share_cents"] += shares[p["id"]]
    allocation = db.new_entity("expenses", {
        "termination_case_id": case["id"],
        "method": body["method"],
        "total_expense_cents": total,
        "description": body["description"],
        "eligible_participant_count": len(eligible),
        "remainder_recipient_participant_id": recipient["id"],
    })
    return success_obj(public_expense(allocation), 201)


@bp.get("/termination-cases/<case_id>/expense-allocations")
def list_expense_allocations(case_id):
    authenticate(ALL_ROLES)
    case = path_entity("cases", case_id, "termination case")
    limit, offset = pagination_params()
    items = [
        x for x in db.all_of("expenses")
        if x["termination_case_id"] == case["id"]
    ]
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_expense(x) for x in page], limit, offset, total, has_more
    )
