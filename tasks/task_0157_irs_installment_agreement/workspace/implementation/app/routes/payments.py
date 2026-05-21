"""Generic payment endpoint (LUMP_SUM, OIC_DEPOSIT, OIC_INSTALLMENT, INSTALLMENT)."""
from __future__ import annotations

from flask import Blueprint

from app.auth import enforce_taxpayer_ownership, require_roles
from app.envelope import success
from app.errors import (
    ERR_CSED_EXPIRED,
    ERR_INVALID_STATE,
    ERR_LIABILITY_NOT_OWNED,
    ERR_NOT_FOUND,
    ERR_OVERPAYMENT,
    ERR_VALIDATION,
    raise_error,
)
from app.services.common import bump_version, init_common_fields
from app.services.liabilities import set_status
from app.services.liens import release_check
from app.services.payment_allocation import allocate, settle_to_paid_if_zero
from app.services.taxpayers import refresh_taxpayer_aggregates
from app.store import STORE, new_id
from app.timeutil import CLOCK, parse_iso
from app.util import (
    get_json_body,
    require_enum,
    require_fields,
    require_int,
    require_str,
)


bp = Blueprint("payments", __name__, url_prefix="/collections/payments")


PAYMENT_KINDS = ("INSTALLMENT", "OIC_DEPOSIT", "OIC_INSTALLMENT", "LUMP_SUM")


def _serialize(p: dict) -> dict:
    return {
        "id": p["id"],
        "agreement_id": p.get("agreement_id"),
        "oic_id": p.get("oic_id"),
        "taxpayer_id": p["taxpayer_id"],
        "amount_cents": p["amount_cents"],
        "received_at": p["received_at"],
        "payment_kind": p["payment_kind"],
        "allocation": list(p.get("allocation", [])),
        "created_at": p["created_at"],
    }


@bp.route("", methods=["POST"])
@require_roles("Taxpayer", "IRSOfficer")
def create_payment(identity):
    body = get_json_body()
    require_fields(body, ["taxpayer_id", "amount_cents", "received_at", "payment_kind"])
    taxpayer_id = require_str(body, "taxpayer_id")
    amount = require_int(body, "amount_cents", minimum=1)
    received_at = require_str(body, "received_at")
    try:
        parse_iso(received_at)
    except ValueError:
        raise_error(ERR_VALIDATION, "received_at must be ISO 8601 UTC.")
    kind = require_enum(body, "payment_kind", PAYMENT_KINDS)
    agreement_id = body.get("agreement_id")
    oic_id = body.get("oic_id")
    liability_ids_in = body.get("liability_ids")

    with STORE.lock:
        tp = STORE.taxpayers.get(taxpayer_id)
        if tp is None:
            raise_error(ERR_NOT_FOUND, f"Taxpayer {taxpayer_id!r} not found.")
        enforce_taxpayer_ownership(identity, taxpayer_id)

        allocation_rows = []
        now_dt = CLOCK.now()

        if kind == "INSTALLMENT":
            if not agreement_id:
                raise_error(ERR_VALIDATION, "agreement_id is required for INSTALLMENT payments.")
            ia = STORE.installment_agreements.get(agreement_id)
            if ia is None or ia["taxpayer_id"] != taxpayer_id:
                raise_error(ERR_NOT_FOUND, f"InstallmentAgreement {agreement_id!r} not found.")
            if ia["status"] != "ACTIVE":
                raise_error(ERR_INVALID_STATE, f"Agreement is in status {ia['status']}.")
            # CSED check
            for lid in ia["liability_ids"]:
                liab = STORE.tax_liabilities[lid]
                if parse_iso(liab["csed_effective_date"]) <= now_dt:
                    raise_error(ERR_CSED_EXPIRED, f"Liability {lid!r} has expired.")
            total = sum(STORE.tax_liabilities[lid]["current_balance_cents"] for lid in ia["liability_ids"])
            if amount > total:
                raise_error(ERR_OVERPAYMENT, "Installment payment exceeds total balance.")
            rows, remaining = allocate(amount, ia["liability_ids"])
            allocation_rows = rows

        elif kind == "OIC_INSTALLMENT":
            if not oic_id:
                raise_error(ERR_VALIDATION, "oic_id is required for OIC_INSTALLMENT payments.")
            oic = STORE.offers.get(oic_id)
            if oic is None or oic["taxpayer_id"] != taxpayer_id:
                raise_error(ERR_NOT_FOUND, f"Offer {oic_id!r} not found.")
            if oic["status"] != "ACCEPTED":
                raise_error(ERR_INVALID_STATE, "OIC must be ACCEPTED for installment payments.")
            # Track cumulative OIC_INSTALLMENT amounts for this OIC
            existing = [p for p in STORE.payments.values()
                        if p.get("oic_id") == oic_id and p["payment_kind"] == "OIC_INSTALLMENT"]
            cumulative = sum(p["amount_cents"] for p in existing) + amount
            offer_target = oic["offer_amount_cents"]
            already_paid = cumulative - amount
            remaining_to_target = offer_target - already_paid
            if amount > remaining_to_target:
                raise_error(ERR_OVERPAYMENT, "OIC_INSTALLMENT exceeds remaining offer balance.")

            # Allocate proportionally — but for OIC the amount is recorded against the offer;
            # liability balances are settled to 0 only on full payoff.
            allocation_rows = []
            for lid in oic["liability_ids"]:
                allocation_rows.append({"liability_id": lid, "applied_cents": 0})
            # When cumulative >= offer_target, settle all covered liabilities
            if cumulative >= offer_target:
                for lid in oic["liability_ids"]:
                    liab = STORE.tax_liabilities[lid]
                    # Settle balance: applied_cents = current_balance_cents so balance := 0
                    bal = liab["current_balance_cents"]
                    if bal > 0:
                        liab["payments_applied_cents"] = liab.get("payments_applied_cents", 0) + bal
                        liab["current_balance_cents"] = 0
                        bump_version(liab)
                    if liab["status"] == "IN_COMPROMISE":
                        set_status(liab, "PAID")
                # Distribute allocation evenly for record-keeping; sum = amount
                # Simple even split adjusted with remainder
                num = len(oic["liability_ids"])
                base_share = amount // num
                rem = amount - base_share * num
                allocation_rows = []
                for i, lid in enumerate(oic["liability_ids"]):
                    extra = 1 if i < rem else 0
                    allocation_rows.append({"liability_id": lid, "applied_cents": base_share + extra})
                release_check(dominant_cause="OIC_ACCEPTED")

        elif kind == "OIC_DEPOSIT":
            if not oic_id:
                raise_error(ERR_VALIDATION, "oic_id is required for OIC_DEPOSIT payments.")
            oic = STORE.offers.get(oic_id)
            if oic is None or oic["taxpayer_id"] != taxpayer_id:
                raise_error(ERR_NOT_FOUND, f"Offer {oic_id!r} not found.")
            # No allocation at submission — held against parent OIC
            allocation_rows = [{"liability_id": lid, "applied_cents": 0} for lid in oic["liability_ids"]]
            oic["deposit_paid_cents"] = oic.get("deposit_paid_cents", 0) + amount
            bump_version(oic)

        elif kind == "LUMP_SUM":
            target_ids = liability_ids_in
            if not target_ids:
                # Apply against all of the taxpayer's open liabilities in the pinned order
                target_ids = [l["id"] for l in STORE.tax_liabilities.values()
                              if l["taxpayer_id"] == taxpayer_id and l["status"] in ("OPEN", "IN_AGREEMENT", "CNC")]
            if not target_ids:
                raise_error(ERR_VALIDATION, "No eligible liabilities for LUMP_SUM payment.")
            # Validate ownership
            for lid in target_ids:
                liab = STORE.tax_liabilities.get(lid)
                if liab is None or liab["taxpayer_id"] != taxpayer_id:
                    raise_error(ERR_LIABILITY_NOT_OWNED, f"Liability {lid!r} not owned by taxpayer.")
            # CSED expiration check
            for lid in target_ids:
                liab = STORE.tax_liabilities[lid]
                if parse_iso(liab["csed_effective_date"]) <= now_dt and liab["status"] != "EXPIRED":
                    raise_error(ERR_CSED_EXPIRED, f"Liability {lid!r} has expired.")
            rows, remaining = allocate(amount, target_ids)
            allocation_rows = rows
            # Surplus is accepted (recorded as overpayment); no error.

        payment = {
            "id": new_id(),
            "agreement_id": agreement_id,
            "oic_id": oic_id,
            "taxpayer_id": taxpayer_id,
            "amount_cents": amount,
            "received_at": received_at,
            "payment_kind": kind,
            "allocation": allocation_rows,
        }
        init_common_fields(payment, with_version=False)
        STORE.payments[payment["id"]] = payment

        # Post-allocation: handle COMPLETED-IA cascade for INSTALLMENT
        if kind == "INSTALLMENT":
            settle_to_paid_if_zero(STORE.installment_agreements[agreement_id]["liability_ids"])
            ia = STORE.installment_agreements[agreement_id]
            if all(STORE.tax_liabilities[lid]["current_balance_cents"] == 0 for lid in ia["liability_ids"]):
                ia["status"] = "COMPLETED"
                bump_version(ia)
                release_check(dominant_cause="PAID_IN_FULL")

        if kind == "LUMP_SUM":
            settle_to_paid_if_zero([row["liability_id"] for row in allocation_rows])
            release_check(dominant_cause="PAID_IN_FULL")

        refresh_taxpayer_aggregates(taxpayer_id)
        return success(_serialize(payment), status=201)


@bp.route("/<p_id>", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer", "Taxpayer")
def get_payment(identity, p_id):
    with STORE.lock:
        p = STORE.payments.get(p_id)
        if p is None:
            raise_error(ERR_NOT_FOUND, f"Payment {p_id!r} not found.")
        enforce_taxpayer_ownership(identity, p["taxpayer_id"])
        return success(_serialize(p))
