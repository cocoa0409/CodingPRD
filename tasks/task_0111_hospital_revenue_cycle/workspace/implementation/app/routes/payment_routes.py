"""Patient payment endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..calculations import outstanding_balance_calc
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..response import paginate
from ..services.serializers import serialize_payment
from ..services.validation import get_encounter_or_404, require_int, require_str
from ..store import LOCK, append_only_fields_create, bump_version, get_store, now_iso
from ._helpers import created, get_json_body, list_ok


VALID_METHODS = {"CASH", "CARD", "CHECK", "REFUND"}


def register(app: Flask) -> None:
    @app.route("/encounters/<encounter_id>/payments", methods=["POST"])
    @require_auth("Biller")
    def create_payment(encounter_id):
        enc = get_encounter_or_404(encounter_id)
        body = get_json_body()
        amount = require_int(body, "amount_cents")
        method = require_str(body, "method")
        if method not in VALID_METHODS:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid payment method: {method!r}")

        # State guard: encounter must be BILLED.
        if enc["status"] != "BILLED":
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Encounter must be BILLED to post payment; is {enc['status']}.",
            )

        # business_fiscal: amount >= 1, and for non-REFUND <= current outstanding.
        if amount < 1:
            raise ApiError(
                "ERR_PAYMENT_AMOUNT_INVALID",
                "amount_cents must be >= 1.",
            )

        store = get_store()
        with LOCK:
            current_outstanding = outstanding_balance_calc(enc)["outstanding_balance_cents"]
            if method != "REFUND" and amount > current_outstanding:
                raise ApiError(
                    "ERR_PAYMENT_AMOUNT_INVALID",
                    f"amount_cents {amount} exceeds outstanding balance {current_outstanding}.",
                )

            base = append_only_fields_create()
            payment = {
                **base,
                "encounter_id": encounter_id,
                "amount_cents": amount,
                "method": method,
                "posted_at": now_iso(),
            }
            store.payments[payment["id"]] = payment

            # Re-derive outstanding balance after this payment.
            bal_after = outstanding_balance_calc(enc)["outstanding_balance_cents"]
            # Bump version on the parent encounter since derived totals are visible there.
            bump_version(enc)

            # If non-REFUND and balance reached exactly 0, transition to RESOLVED.
            if method != "REFUND" and bal_after == 0:
                enc["status"] = "RESOLVED"
                bump_version(enc)

        return created(serialize_payment(payment))

    @app.route("/encounters/<encounter_id>/payments", methods=["GET"])
    @require_auth("Biller")
    def list_payments(encounter_id):
        get_encounter_or_404(encounter_id)
        limit, offset = parse_limit_offset()
        store = get_store()
        items = [p for p in store.payments.values() if p["encounter_id"] == encounter_id]
        items.sort(key=lambda p: p["created_at"])
        sliced, pag = paginate(items, limit, offset)
        return list_ok([serialize_payment(p) for p in sliced], pag)
