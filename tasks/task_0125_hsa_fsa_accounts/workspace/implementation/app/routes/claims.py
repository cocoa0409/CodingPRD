"""Claim endpoints — create, submit, approve, pay, deny, reverse + retrieval."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..clock import parse_iso, to_date
from ..errors import ApiError
from ..helpers import (
    get_json_body, parse_iso_field, require_fields, require_positive_int, require_string,
    serialize_claim, sort_key_created_then_id,
)
from ..responses import build_list_envelope, build_success_envelope, paginate, parse_pagination
from ..services.audit import emit_audit_event, find_claim_submitted_event_actor
from ..services.occ import check_version
from ..services.plan_year_resolver import resolve_plan_year
from ..store import store


bp = Blueprint("claims", __name__)


def _get_account_scoped(account_id: str) -> dict:
    a = store.accounts.get(account_id)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Account not found.")
    if g.role == "AccountHolder" and a["account_holder_id"] != g.user_id:
        raise ApiError("ERR_NOT_FOUND", "Account not found.")
    return a


def _get_claim_scoped(claim_id: str) -> dict:
    cl = store.claims.get(claim_id)
    if cl is None:
        raise ApiError("ERR_NOT_FOUND", "Claim not found.")
    if g.role == "AccountHolder":
        a = store.accounts.get(cl["account_id"])
        if a is None or a["account_holder_id"] != g.user_id:
            raise ApiError("ERR_NOT_FOUND", "Claim not found.")
    return cl


def _validate_expense_eligibility(*, account: dict, expense_code: str,
                                  dependent_id: str | None, check_dependent_status: bool) -> dict:
    """Run the QualifiedExpense + dependent-required checks. Returns the matching expense row.

    Raises ERR_EXPENSE_NOT_ELIGIBLE / ERR_DEPENDENT_REQUIRED / ERR_DEPENDENT_INACTIVE
    in scaffold priority order.
    """
    expense = store.qualified_expenses_by_code.get(expense_code)
    if expense is None or account["account_type"] not in expense["eligible_account_types"]:
        raise ApiError("ERR_EXPENSE_NOT_ELIGIBLE", "Expense code not eligible for this account.")

    if expense["requires_dependent"]:
        if dependent_id is None:
            raise ApiError("ERR_DEPENDENT_REQUIRED", "Dependent is required for this expense code.")
        dep = store.dependents.get(dependent_id)
        if dep is None or dep["account_holder_id"] != account["account_holder_id"]:
            raise ApiError(
                "ERR_DEPENDENT_REQUIRED",
                "Dependent does not belong to the account holder.",
            )
        if check_dependent_status and dep["status"] != "ACTIVE":
            raise ApiError("ERR_DEPENDENT_INACTIVE", "Dependent is not ACTIVE.")
    return expense


# ----- Create draft claim ----- #

@bp.route("/accounts/<account_id>/claims", methods=["POST"])
@require_auth(["AccountHolder"])
def create_claim(account_id: str):
    a = _get_account_scoped(account_id)

    if a["status"] != "OPEN":
        raise ApiError("ERR_ACCOUNT_NOT_OPEN", "Account is not OPEN.")

    body = get_json_body(allow_empty=False)
    require_fields(body, ["service_date", "expense_code", "amount_cents"])
    service_date = parse_iso_field(body["service_date"], "service_date")
    expense_code = require_string(body["expense_code"], "expense_code")
    amount = require_positive_int(body["amount_cents"], "amount_cents", min_value=1)
    dependent_id = body.get("dependent_id")
    if dependent_id is not None and not isinstance(dependent_id, str):
        raise ApiError("ERR_BAD_REQUEST", "dependent_id must be a string or null.")

    # Per PRD §3.5: expense-eligibility and dependent-required checks also run at create time.
    _validate_expense_eligibility(
        account=a, expense_code=expense_code,
        dependent_id=dependent_id, check_dependent_status=True,
    )

    with store.lock:
        now = store.clock.now()
        row = {
            "id": store.new_id(),
            "_seq": store.next_seq(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "account_id": a["id"],
            "plan_year_id": None,
            "service_date": service_date,
            "expense_code": expense_code,
            "amount_cents": amount,
            "dependent_id": dependent_id,
            "status": "DRAFT",
            "denial_reason": None,
            "paid_amount_cents": None,
            "reversed_from_id": None,
        }
        store.claims[row["id"]] = row

    return jsonify(build_success_envelope(serialize_claim(row))), 201


# ----- Submit ----- #

@bp.route("/claims/<claim_id>/submit", methods=["POST"])
@require_auth(["AccountHolder"])
def submit_claim(claim_id: str):
    cl = _get_claim_scoped(claim_id)
    body = get_json_body()

    with store.lock:
        check_version(body, cl["version"])
        if cl["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Claim is not in DRAFT.")
        a = store.accounts.get(cl["account_id"])
        if a is None:
            raise ApiError("ERR_NOT_FOUND", "Owning account not found.")
        if a["status"] != "OPEN":
            raise ApiError("ERR_ACCOUNT_NOT_OPEN", "Account is not OPEN.")

        # Re-validate expense + dependent (priority 8, 9, 9.5)
        _validate_expense_eligibility(
            account=a, expense_code=cl["expense_code"],
            dependent_id=cl.get("dependent_id"), check_dependent_status=True,
        )

        # service_date must be <= clock_now and resolve to a plan year.
        if cl["service_date"] > store.clock.now():
            raise ApiError("ERR_NO_ELIGIBLE_PLAN_YEAR", "service_date is in the future.")
        py = resolve_plan_year(a, cl["service_date"])
        if py is None:
            raise ApiError("ERR_NO_ELIGIBLE_PLAN_YEAR", "No eligible plan year for service_date.")

        if py["status"] not in ("ACTIVE", "GRACE_PERIOD", "CARRYOVER_PENDING"):
            raise ApiError("ERR_PLAN_YEAR_NOT_CLAIMABLE", "Plan year is not claimable.")

        now = store.clock.now()
        cl["plan_year_id"] = py["id"]
        cl["status"] = "SUBMITTED"
        cl["version"] += 1
        cl["updated_at"] = now
        emit_audit_event(
            event_type="CLAIM_SUBMITTED",
            subject_entity="CLAIM", subject_id=cl["id"],
            account_id=a["id"], plan_year_id=py["id"], cents_delta=0,
        )

    return jsonify(build_success_envelope(serialize_claim(cl))), 200


# ----- Approve ----- #

@bp.route("/claims/<claim_id>/approve", methods=["POST"])
@require_auth(["ClaimAdjudicator"])
def approve_claim(claim_id: str):
    cl = store.claims.get(claim_id)
    if cl is None:
        raise ApiError("ERR_NOT_FOUND", "Claim not found.")
    body = get_json_body()

    with store.lock:
        check_version(body, cl["version"])
        if cl["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Claim is not SUBMITTED.")
        a = store.accounts.get(cl["account_id"])
        if a is None or a["status"] != "OPEN":
            raise ApiError("ERR_ACCOUNT_NOT_OPEN", "Account is not OPEN.")
        py = store.plan_years.get(cl["plan_year_id"]) if cl.get("plan_year_id") else None
        if py is None or py["status"] not in ("ACTIVE", "GRACE_PERIOD", "CARRYOVER_PENDING"):
            raise ApiError("ERR_PLAN_YEAR_NOT_CLAIMABLE", "Plan year is not claimable.")

        # Segregation of duties
        submitter = find_claim_submitted_event_actor(cl["id"])
        if submitter is not None and submitter == g.user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "Adjudicator cannot approve a claim they submitted.",
            )

        now = store.clock.now()
        cl["status"] = "APPROVED"
        cl["version"] += 1
        cl["updated_at"] = now
        emit_audit_event(
            event_type="CLAIM_APPROVED",
            subject_entity="CLAIM", subject_id=cl["id"],
            account_id=a["id"], plan_year_id=py["id"], cents_delta=0,
        )

    return jsonify(build_success_envelope(serialize_claim(cl))), 200


# ----- Pay ----- #

@bp.route("/claims/<claim_id>/pay", methods=["POST"])
@require_auth(["ClaimAdjudicator"])
def pay_claim(claim_id: str):
    cl = store.claims.get(claim_id)
    if cl is None:
        raise ApiError("ERR_NOT_FOUND", "Claim not found.")
    body = get_json_body()

    with store.lock:
        check_version(body, cl["version"])
        if cl["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Claim is not APPROVED.")
        a = store.accounts.get(cl["account_id"])
        if a is None or a["status"] != "OPEN":
            raise ApiError("ERR_ACCOUNT_NOT_OPEN", "Account is not OPEN.")
        py = store.plan_years.get(cl["plan_year_id"]) if cl.get("plan_year_id") else None
        if py is None or py["status"] not in ("ACTIVE", "GRACE_PERIOD", "CARRYOVER_PENDING"):
            raise ApiError("ERR_PLAN_YEAR_NOT_CLAIMABLE", "Plan year is not claimable.")

        # Available balance check
        available_balance = (
            py["contributions_ytd_cents"] + py["carryover_in_cents"]
            - py["claims_paid_ytd_cents"]
        )
        if cl["amount_cents"] > available_balance:
            raise ApiError("ERR_INSUFFICIENT_BALANCE", "Insufficient balance for payment.")

        # Drawdown waterfall — draw current-year first, then carryover.
        new_payment = cl["amount_cents"]
        current_year_available = max(
            0,
            py["contributions_ytd_cents"]
            - (py["claims_paid_ytd_cents"] - py["carryover_consumed_cents"]),
        )
        drawn_from_current = min(new_payment, current_year_available)
        drawn_from_carryover = new_payment - drawn_from_current

        now = store.clock.now()
        cl["status"] = "PAID"
        cl["paid_amount_cents"] = new_payment
        cl["version"] += 1
        cl["updated_at"] = now

        py["claims_paid_ytd_cents"] += new_payment
        py["carryover_consumed_cents"] += drawn_from_carryover
        py["provisional_balance_cents"] = (
            py["contributions_ytd_cents"] + py["carryover_in_cents"]
            - py["claims_paid_ytd_cents"]
        )
        py["version"] += 1
        py["updated_at"] = now

        emit_audit_event(
            event_type="CLAIM_PAID",
            subject_entity="CLAIM", subject_id=cl["id"],
            account_id=a["id"], plan_year_id=py["id"],
            cents_delta=-new_payment,
        )

    return jsonify(build_success_envelope(serialize_claim(cl))), 200


# ----- Deny ----- #

@bp.route("/claims/<claim_id>/deny", methods=["POST"])
@require_auth(["ClaimAdjudicator"])
def deny_claim(claim_id: str):
    cl = store.claims.get(claim_id)
    if cl is None:
        raise ApiError("ERR_NOT_FOUND", "Claim not found.")
    body = get_json_body(allow_empty=False)

    with store.lock:
        check_version(body, cl["version"])
        if cl["status"] not in ("SUBMITTED", "APPROVED"):
            raise ApiError("ERR_INVALID_STATE", "Claim cannot be denied from its current state.")
        a = store.accounts.get(cl["account_id"])
        if a is None:
            raise ApiError("ERR_NOT_FOUND", "Owning account not found.")

        # Segregation of duties only on SUBMITTED→DENIED
        if cl["status"] == "SUBMITTED":
            submitter = find_claim_submitted_event_actor(cl["id"])
            if submitter is not None and submitter == g.user_id:
                raise ApiError(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "Adjudicator cannot deny a claim they submitted.",
                )

        denial_reason = body.get("denial_reason")
        if not isinstance(denial_reason, str) or not denial_reason.strip():
            raise ApiError("ERR_DENIAL_REASON_REQUIRED", "denial_reason is required.")

        now = store.clock.now()
        cl["status"] = "DENIED"
        cl["denial_reason"] = denial_reason
        cl["version"] += 1
        cl["updated_at"] = now

        emit_audit_event(
            event_type="CLAIM_DENIED",
            subject_entity="CLAIM", subject_id=cl["id"],
            account_id=a["id"], plan_year_id=cl.get("plan_year_id"),
            cents_delta=0,
        )

    return jsonify(build_success_envelope(serialize_claim(cl))), 200


# ----- Reverse ----- #

@bp.route("/claims/<claim_id>/reverse", methods=["POST"])
@require_auth(["ClaimAdjudicator"])
def reverse_claim(claim_id: str):
    cl = store.claims.get(claim_id)
    if cl is None:
        raise ApiError("ERR_NOT_FOUND", "Claim not found.")
    body = get_json_body()

    with store.lock:
        check_version(body, cl["version"])
        if cl["status"] != "PAID":
            raise ApiError("ERR_INVALID_STATE", "Claim is not PAID.")
        if cl.get("reversed_from_id"):
            # Twin row can't be reversed itself
            raise ApiError("ERR_INVALID_STATE", "Cannot reverse an audit-twin row.")
        a = store.accounts.get(cl["account_id"])
        if a is None:
            raise ApiError("ERR_NOT_FOUND", "Owning account not found.")
        py = store.plan_years.get(cl["plan_year_id"]) if cl.get("plan_year_id") else None
        if py is None or py["status"] == "CLOSED":
            raise ApiError("ERR_PLAN_YEAR_NOT_CLAIMABLE", "Plan year is closed.")

        paid = cl["paid_amount_cents"] or 0
        # LIFO undo per PRD §3.6: restore current-year credit first, then carryover.
        # current_year_paid = claims_paid_ytd_cents - carryover_consumed_cents (lower-bound 0).
        current_year_paid = max(0, py["claims_paid_ytd_cents"] - py["carryover_consumed_cents"])
        undo_from_current = min(paid, current_year_paid)
        undo_from_carryover = paid - undo_from_current

        now = store.clock.now()
        cl["status"] = "REVERSED"
        cl["version"] += 1
        cl["updated_at"] = now

        py["claims_paid_ytd_cents"] -= paid
        py["carryover_consumed_cents"] -= undo_from_carryover
        if py["carryover_consumed_cents"] < 0:
            py["carryover_consumed_cents"] = 0
        py["provisional_balance_cents"] = (
            py["contributions_ytd_cents"] + py["carryover_in_cents"]
            - py["claims_paid_ytd_cents"]
        )
        py["version"] += 1
        py["updated_at"] = now

        # Audit twin
        twin = {
            "id": store.new_id(),
            "_seq": store.next_seq(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "account_id": a["id"],
            "plan_year_id": py["id"],
            "service_date": cl["service_date"],
            "expense_code": cl["expense_code"],
            "amount_cents": cl["amount_cents"],
            "dependent_id": cl.get("dependent_id"),
            "status": "REVERSED",
            "denial_reason": None,
            "paid_amount_cents": None,
            "reversed_from_id": cl["id"],
        }
        store.claims[twin["id"]] = twin

        emit_audit_event(
            event_type="CLAIM_REVERSED",
            subject_entity="CLAIM", subject_id=cl["id"],
            account_id=a["id"], plan_year_id=py["id"],
            cents_delta=paid,
        )

    return jsonify(build_success_envelope(serialize_claim(cl))), 200


# ----- Read endpoints ----- #

@bp.route("/claims/<claim_id>", methods=["GET"])
@require_auth(["AccountHolder", "PlanAdministrator", "ClaimAdjudicator", "Auditor"])
def get_claim(claim_id: str):
    cl = _get_claim_scoped(claim_id)
    return jsonify(build_success_envelope(serialize_claim(cl))), 200


@bp.route("/accounts/<account_id>/claims", methods=["GET"])
@require_auth(["AccountHolder", "PlanAdministrator", "ClaimAdjudicator", "Auditor"])
def list_claims(account_id: str):
    a = _get_account_scoped(account_id)
    limit, offset = parse_pagination()

    f_status = request.args.get("status")
    f_py = request.args.get("plan_year_id")
    f_from = request.args.get("service_date_from")
    f_to = request.args.get("service_date_to")
    from_dt = parse_iso(f_from) if f_from else None
    to_dt = parse_iso(f_to) if f_to else None

    rows = [c for c in store.claims.values() if c["account_id"] == a["id"]]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    if f_py is not None:
        rows = [r for r in rows if r.get("plan_year_id") == f_py]
    if from_dt is not None:
        rows = [r for r in rows if r["service_date"] >= from_dt]
    if to_dt is not None:
        rows = [r for r in rows if r["service_date"] <= to_dt]

    rows.sort(key=sort_key_created_then_id)
    page, total = paginate(rows, limit, offset)
    return jsonify(build_list_envelope(
        [serialize_claim(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )), 200
