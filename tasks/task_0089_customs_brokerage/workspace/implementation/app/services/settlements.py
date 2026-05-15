"""Settlement service: creation cascade, advance, reimbursement."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from ..audit import emit_audit
from ..auth import current_actor
from ..calculations import (
    compute_broker_fee,
    compute_consumption_tax,
    compute_late_interest,
    compute_penalty_in_settlement,
    compute_tariff,
    compute_vat,
    to_float2,
)
from ..clock import add_days, now_dt, now_iso_ms, parse_iso
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store
from .validation import occ_check


def _has_inspection_case(declaration_id: str) -> bool:
    store = get_store()
    return any(
        ic.get("filing_id")
        and store.filings.get(ic["filing_id"], {}).get("declaration_id") == declaration_id
        for ic in store.inspection_cases.values()
    )


def cascade_create_settlement(
    declaration: dict[str, Any], penalty_in_declared: float = 0
) -> dict[str, Any]:
    """Create a Settlement directly in FINAL status as a cascade side-effect
    of Declaration→RELEASED (post-filing release or post-inspection release)
    or Declaration→REJECTED with PENALTY outcome.
    """
    store = get_store()
    agreement = store.agreements.get(declaration["agreement_id"])
    if not agreement:
        raise ApiError("ERR_NOT_FOUND", "Parent agreement not found for settlement cascade.")
    client = store.clients.get(agreement.get("client_id"))
    if not client:
        raise ApiError("ERR_NOT_FOUND", "Parent client not found for settlement cascade.")

    settlement_currency = client["default_settlement_currency"]
    fx = declaration.get("fx_rate_to_settlement") or 1

    # Tariff -> VAT -> CT pipeline (strict order, per-step round)
    tariff = compute_tariff(declaration)
    vat = compute_vat(declaration, tariff)
    ct = compute_consumption_tax(declaration, tariff)

    penalty = (
        compute_penalty_in_settlement(penalty_in_declared, fx)
        if penalty_in_declared
        else Decimal("0.00")
    )

    has_insp = _has_inspection_case(declaration["id"])
    # advance not yet paid → broker_fee excludes TARIFF_ADVANCE for now;
    # PRD §3.9: "TARIFF_ADVANCE is added when advance_paid_amount is strictly positive
    # (always the case for FINAL settlements that proceed to advance)".
    # Interpretation: include TARIFF_ADVANCE for FINAL settlements that will be advanced.
    # We include it whenever the bill is > 0 (i.e. when an advance is possible).
    bill_total = tariff + vat + ct + penalty
    will_advance = bill_total > 0
    broker_fee = compute_broker_fee(
        declaration, agreement, has_inspection_case=has_insp, has_advance=will_advance
    )

    record = common_fields_create()
    record.update(
        {
            "declaration_id": declaration["id"],
            "tariff_amount": float(tariff),
            "vat_amount": float(vat),
            "consumption_tax_amount": float(ct),
            "penalty_amount": float(penalty),
            "broker_fee_amount": float(broker_fee),
            "settlement_currency": settlement_currency,
            "advance_paid_amount": 0,
            "advance_paid_at": None,
            "reimbursement_due_at": None,
            "reimbursed_at": None,
            "late_interest_amount": 0,
            "voucher_uri": None,
            "status": "FINAL",
        }
    )
    store.settlements[record["id"]] = record

    user_id, role = current_actor()
    emit_audit(
        "SETTLEMENT",
        record["id"],
        "STATE_TRANSITION",
        role,
        user_id,
        {"from": "PROVISIONAL", "to": "FINAL"},
    )
    return record


def get_settlement(settlement_id: str) -> dict[str, Any]:
    s = get_store().settlements.get(settlement_id)
    if not s:
        raise ApiError("ERR_NOT_FOUND", f"Settlement {settlement_id!r} not found.")
    return s


def list_settlements(
    status: Optional[str],
    declaration_id: Optional[str],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    store = get_store()
    items = list(store.settlements.values())
    if status is not None:
        items = [s for s in items if s.get("status") == status]
    if declaration_id is not None:
        items = [s for s in items if s.get("declaration_id") == declaration_id]
    user_id, role = current_actor()
    if role == "ClientUser":
        # restrict to settlements whose declaration->agreement->client_id == user_id
        items = [
            s
            for s in items
            if (
                (decl := store.declarations.get(s.get("declaration_id")))
                and (agree := store.agreements.get(decl.get("agreement_id")))
                and agree.get("client_id") == user_id
            )
        ]
    items.sort(key=lambda s: s.get("created_at") or "")
    return items


def advance_settlement(settlement_id: str, body: dict[str, Any]) -> dict[str, Any]:
    settlement = get_settlement(settlement_id)
    occ_check(settlement, body.get("version"))

    # Priority 40/ERR_INVALID_STATE — already advanced?
    if settlement.get("status") in {"ADVANCED", "REIMBURSED"}:
        raise ApiError(
            "ERR_SETTLEMENT_ALREADY_ADVANCED",
            f"Settlement already in {settlement['status']!r}.",
        )
    if settlement.get("status") != "FINAL":
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Settlement in {settlement.get('status')!r}; expected FINAL.",
        )

    store = get_store()
    declaration = store.declarations.get(settlement.get("declaration_id"))
    if not declaration:
        raise ApiError("ERR_NOT_FOUND", "Parent declaration not found.")

    # Priority 42: V-SET-ADV-WITHDRAWN — declaration must not be WITHDRAWN
    if declaration.get("status") == "WITHDRAWN":
        raise ApiError(
            "ERR_INVALID_STATE", "Cannot advance: parent declaration is WITHDRAWN."
        )

    # SoD (priority 71): SettlementOfficer != FilingOfficer
    user_id, role = current_actor()
    file_actor_id = store.file_actor.get(declaration["id"])
    if file_actor_id and file_actor_id == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "SettlementOfficer must differ from the FilingOfficer.",
        )

    # Priority 150: V-SET-ADV-AMOUNT — sum > 0
    bill = (
        Decimal(str(settlement.get("tariff_amount") or 0))
        + Decimal(str(settlement.get("vat_amount") or 0))
        + Decimal(str(settlement.get("consumption_tax_amount") or 0))
        + Decimal(str(settlement.get("penalty_amount") or 0))
    )
    if bill <= 0:
        raise ApiError("ERR_SETTLEMENT_ZERO_AMOUNT", "Settlement total is zero.")

    settlement["advance_paid_amount"] = float(bill.quantize(Decimal("0.01")))
    settlement["advance_paid_at"] = now_iso_ms()
    settlement["reimbursement_due_at"] = (
        now_iso_ms()
        if False
        else _iso_plus_days(7)
    )
    settlement["status"] = "ADVANCED"
    bump_version(settlement)

    emit_audit(
        "SETTLEMENT",
        settlement_id,
        "STATE_TRANSITION",
        role,
        user_id,
        {"from": "FINAL", "to": "ADVANCED"},
    )
    emit_audit(
        "SETTLEMENT",
        settlement_id,
        "ADVANCE_PAID",
        role,
        user_id,
        {
            "amount": settlement["advance_paid_amount"],
            "currency": settlement["settlement_currency"],
        },
    )
    return settlement


def _iso_plus_days(days: int) -> str:
    from ..clock import format_iso, now_dt

    return format_iso(add_days(now_dt(), days))  # type: ignore[return-value]


def process_bank_debit(
    settlement: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """BANK_DEBIT_CONFIRMED → ADVANCED → REIMBURSED."""
    if settlement.get("status") != "ADVANCED":
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Settlement in {settlement.get('status')!r}; expected ADVANCED.",
        )

    amount = payload.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ApiError("ERR_INVALID_INPUT", "payload.amount must be numeric.")

    # Recompute current late_interest
    store = get_store()
    declaration = store.declarations.get(settlement.get("declaration_id"))
    if not declaration:
        raise ApiError("ERR_NOT_FOUND", "Parent declaration not found.")
    agreement = store.agreements.get(declaration.get("agreement_id"))
    if not agreement:
        raise ApiError("ERR_NOT_FOUND", "Parent agreement not found.")

    bps = int(agreement.get("late_interest_daily_rate_bps") or 0)
    late = compute_late_interest(
        settlement.get("advance_paid_amount") or 0,
        settlement.get("reimbursement_due_at"),
        now_iso_ms(),
        bps,
    )
    expected = Decimal(str(settlement.get("advance_paid_amount") or 0)) + late
    if Decimal(str(amount)).quantize(Decimal("0.01")) != expected.quantize(Decimal("0.01")):
        raise ApiError(
            "ERR_BANK_AMOUNT_MISMATCH",
            f"Bank debit amount mismatch: expected {float(expected)}, got {amount}.",
        )

    settlement["reimbursed_at"] = now_iso_ms()
    settlement["late_interest_amount"] = float(late)
    settlement["voucher_uri"] = f"voucher://{settlement['id']}"
    settlement["status"] = "REIMBURSED"
    bump_version(settlement)

    actor_id = "system"
    emit_audit(
        "SETTLEMENT",
        settlement["id"],
        "STATE_TRANSITION",
        "system",
        actor_id,
        {"from": "ADVANCED", "to": "REIMBURSED"},
    )
    emit_audit(
        "SETTLEMENT",
        settlement["id"],
        "REIMBURSED",
        "system",
        actor_id,
        {
            "amount": float(expected),
            "currency": settlement["settlement_currency"],
        },
    )
    emit_audit(
        "SETTLEMENT",
        settlement["id"],
        "VOUCHER_DELIVERED",
        "system",
        actor_id,
        {"voucher_uri": settlement["voucher_uri"]},
    )
    return settlement
