"""Payment routes."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..clock import now_iso_ms
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..services import payments as payment_svc
from ..store import common_fields_append_only, get_store
from ._helpers import created, get_borrower_or_404, get_json_body, list_ok, ok


VALID_SOURCES = {"BORROWER", "EMPLOYER", "ADMINISTRATIVE_WAGE_GARNISHMENT", "TREASURY_OFFSET"}


def register(app: Flask) -> None:
    @app.route("/borrowers/<borrower_id>/payments", methods=["POST"])
    @require_auth("Borrower", "ServicerAdmin", "CollectionsOfficer")
    def create_payment(borrower_id):
        b = get_borrower_or_404(borrower_id)
        body = get_json_body(allow_empty=False)
        # amount must be positive int cents
        try:
            amount = int(body.get("amount_cents"))
        except Exception:
            raise ApiError("ERR_AMOUNT_INVALID", "amount_cents must be an integer.")
        if amount <= 0:
            raise ApiError("ERR_AMOUNT_INVALID", "amount_cents must be > 0.")
        source = body.get("source", "BORROWER")
        if source not in VALID_SOURCES:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid source: {source}")
        # Role/source restrictions
        _, role = current_actor()
        if role == "Borrower" and source != "BORROWER":
            raise ApiError("ERR_FORBIDDEN", "Borrowers may only submit source=BORROWER.")
        if role == "CollectionsOfficer" and source not in (
            "ADMINISTRATIVE_WAGE_GARNISHMENT",
            "TREASURY_OFFSET",
        ):
            raise ApiError(
                "ERR_FORBIDDEN",
                "CollectionsOfficer may only submit garnishment/offset payments.",
            )
        received_at = body.get("received_at") or now_iso_ms()
        # build payment shell first so we have an id and can fill allocations
        payment = {
            **common_fields_append_only(),
            "borrower_id": borrower_id,
            "amount_cents": amount,
            "received_at": received_at,
            "source": source,
            "pslf_qualifying": False,
            "allocations": [],
        }
        allocations = payment_svc.allocate_payment(b, amount, source, received_at)
        payment["allocations"] = allocations
        # Set pslf_qualifying live for this single payment
        payment["pslf_qualifying"] = payment_svc.is_pslf_qualifying_for_payment(
            borrower_id, payment
        )
        get_store().payments[payment["id"]] = payment
        # Re-run PSLF history recount to update per-loan counts
        payment_svc.recount_pslf_for_borrower(borrower_id)
        return created(payment)

    @app.route("/borrowers/<borrower_id>/payments", methods=["GET"])
    @require_auth("Borrower", "ServicerAdmin", "CollectionsOfficer")
    def list_payments(borrower_id):
        get_borrower_or_404(borrower_id)
        limit, offset = parse_limit_offset()
        source = parse_optional_str("source")
        items = [p for p in get_store().payments.values() if p["borrower_id"] == borrower_id]
        if source:
            items = [p for p in items if p["source"] == source]
        items.sort(key=lambda p: p["created_at"])
        page = {
            "limit": limit,
            "offset": offset,
            "total_count": len(items),
            "has_more": offset + limit < len(items),
        }
        return list_ok(items[offset : offset + limit], page)

    @app.route("/borrowers/<borrower_id>/payments/<payment_id>", methods=["GET"])
    @require_auth("Borrower", "ServicerAdmin", "CollectionsOfficer")
    def get_payment(borrower_id, payment_id):
        get_borrower_or_404(borrower_id)
        p = get_store().payments.get(payment_id)
        if not p or p["borrower_id"] != borrower_id:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Payment {payment_id} not found.")
        return ok(p)
