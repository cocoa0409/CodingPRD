"""Collections action routes."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..clock import now_iso_ms
from ..errors import ApiError
from ..services import loans as loan_svc
from ..services import payments as payment_svc
from ..services.borrowers import recompute_aggregates
from ..store import (
    bump_version,
    common_fields_append_only,
    get_store,
)
from ._helpers import created, get_borrower_or_404, get_json_body, ok


VALID_KINDS = {
    "DEFAULT_DECLARATION",
    "REHAB_AGREEMENT_OPEN",
    "REHAB_PAYMENT_RECORDED",
    "REHAB_COMPLETED",
    "WAGE_GARNISHMENT_ORDER",
    "TREASURY_OFFSET_APPLIED",
}


def register(app: Flask) -> None:
    @app.route("/borrowers/<borrower_id>/loans/<loan_id>/collections", methods=["POST"])
    @require_auth("CollectionsOfficer")
    def add_collection(borrower_id, loan_id):
        b = get_borrower_or_404(borrower_id)
        loan = get_store().loans.get(loan_id)
        if not loan or loan.get("borrower_id") != borrower_id:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Loan {loan_id} not found.")
        body = get_json_body(allow_empty=False)
        kind = body.get("kind")
        if kind not in VALID_KINDS:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid kind: {kind}")
        amount = int(body.get("amount_cents", 0) or 0)
        if amount < 0:
            raise ApiError("ERR_AMOUNT_INVALID", "amount_cents must be >= 0.")
        occurred_at = body.get("occurred_at") or now_iso_ms()
        user_id, _ = current_actor()

        # Apply state-machine side effects based on kind.
        if kind == "REHAB_AGREEMENT_OPEN":
            if loan["status"] != "DEFAULT":
                raise ApiError("ERR_INVALID_STATE", "Loan must be DEFAULT to open rehab.")
            # one rehab per lifetime
            for a in get_store().collections_actions.values():
                if a.get("loan_id") == loan_id and a.get("kind") == "REHAB_COMPLETED":
                    raise ApiError(
                        "ERR_REHAB_ALREADY_USED",
                        "Loan has already completed a rehab cycle.",
                    )
            loan_svc.set_status(loan, "REHABILITATION")
        elif kind == "REHAB_PAYMENT_RECORDED":
            # Must be in REHABILITATION
            if loan["status"] != "REHABILITATION":
                raise ApiError("ERR_INVALID_STATE", "Loan must be REHABILITATION for rehab payment.")
            # Record action and create implicit Payment if amount > 0
            if amount > 0:
                _create_implicit_payment(borrower_id, amount, "BORROWER", occurred_at)
        elif kind in ("WAGE_GARNISHMENT_ORDER", "TREASURY_OFFSET_APPLIED"):
            # Create implicit Payment with matching source.
            source = (
                "ADMINISTRATIVE_WAGE_GARNISHMENT"
                if kind == "WAGE_GARNISHMENT_ORDER"
                else "TREASURY_OFFSET"
            )
            if amount > 0:
                _create_implicit_payment(borrower_id, amount, source, occurred_at)
        elif kind == "DEFAULT_DECLARATION":
            # Manual default declaration: must be DELINQUENT
            if loan["status"] != "DELINQUENT":
                raise ApiError("ERR_INVALID_STATE", "Loan must be DELINQUENT for default declaration.")
            from ..services import clock_advance as ca
            ca._declare_default(loan)
        elif kind == "REHAB_COMPLETED":
            # Generally system-driven; allow manual append.
            pass

        action = {
            **common_fields_append_only(),
            "borrower_id": borrower_id,
            "loan_id": loan_id,
            "kind": kind,
            "amount_cents": amount,
            "occurred_at": occurred_at,
            "recorded_by": user_id,
        }
        get_store().collections_actions[action["id"]] = action
        recompute_aggregates(b)
        return created(action)


def _create_implicit_payment(borrower_id: str, amount: int, source: str, received_at: str) -> None:
    b = get_store().borrowers.get(borrower_id)
    if not b:
        return
    payment = {
        **common_fields_append_only(),
        "borrower_id": borrower_id,
        "amount_cents": int(amount),
        "received_at": received_at,
        "source": source,
        "pslf_qualifying": False,
        "allocations": [],
    }
    allocations = payment_svc.allocate_payment(b, amount, source, received_at)
    payment["allocations"] = allocations
    payment["pslf_qualifying"] = payment_svc.is_pslf_qualifying_for_payment(borrower_id, payment)
    get_store().payments[payment["id"]] = payment
    payment_svc.recount_pslf_for_borrower(borrower_id)
