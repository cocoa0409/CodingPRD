"""Calculation rules (scaffold §1.3, PRD §3.8 / §3.9 / §3.10)."""
from __future__ import annotations

import math
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from .clock import parse_iso
from .constants import (
    AGREEMENT_FX_TABLE,
    CONSUMPTION_TAX_TABLE,
    CORE_DOC_TYPES,
    FTA_RATE_TABLE,
    MFN_RATE_TABLE,
    REFERENCE_PRICE_TABLE,
    VAT_RATE_TABLE,
)


def _to_dec(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def _round2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_float2(v: Decimal | float | int | None) -> Optional[float]:
    """Serialise a Decimal to float with 2dp precision for JSON output."""
    if v is None:
        return None
    if not isinstance(v, Decimal):
        v = Decimal(str(v))
    return float(_round2(v))


# ---------------------------------------------------------------------------
# compute_tariff
# ---------------------------------------------------------------------------
def _select_duty_rate(
    trade_agreement_code: str,
    jurisdiction_code: str,
    hs_code_first_4: str,
) -> Decimal:
    """Pick MFN or FTA rate per scaffold §1.3."""
    if trade_agreement_code and trade_agreement_code != "NONE":
        fta_juris = FTA_RATE_TABLE.get(trade_agreement_code, {}).get(jurisdiction_code)
        if fta_juris is not None:
            return fta_juris.get(hs_code_first_4, fta_juris["default"])
        # falls through to MFN when origin not eligible
    juris = MFN_RATE_TABLE.get(jurisdiction_code, MFN_RATE_TABLE["CN"])
    return juris.get(hs_code_first_4, juris["default"])


def _tier_factor(base_value: Decimal) -> Decimal:
    if base_value <= Decimal("10000"):
        return Decimal("1.00")
    if base_value <= Decimal("50000"):
        return Decimal("1.05")
    return Decimal("1.10")


def compute_base_value(declared_value_amount, fx_rate_to_settlement) -> Decimal:
    """base_value = round(declared_value_amount * fx_rate_to_settlement, 2)."""
    return _round2(_to_dec(declared_value_amount) * _to_dec(fx_rate_to_settlement))


def compute_tariff(declaration: dict[str, Any]) -> Decimal:
    base_value = compute_base_value(
        declaration["declared_value_amount"], declaration["fx_rate_to_settlement"]
    )
    hs_first_4 = declaration["hs_code"][:4]
    rate = _select_duty_rate(
        declaration.get("trade_agreement_code") or "NONE",
        declaration["jurisdiction_code"],
        hs_first_4,
    )
    factor = _tier_factor(base_value)
    return _round2(base_value * rate * factor)


def compute_vat(declaration: dict[str, Any], tariff_amount: Decimal) -> Decimal:
    base_value = compute_base_value(
        declaration["declared_value_amount"], declaration["fx_rate_to_settlement"]
    )
    rate = VAT_RATE_TABLE.get(declaration["jurisdiction_code"], Decimal("0"))
    return _round2((base_value + _to_dec(tariff_amount)) * rate)


def compute_consumption_tax(
    declaration: dict[str, Any],
    tariff_amount: Decimal,
) -> Decimal:
    base_value = compute_base_value(
        declaration["declared_value_amount"], declaration["fx_rate_to_settlement"]
    )
    hs_first_4 = declaration["hs_code"][:4]
    rate = CONSUMPTION_TAX_TABLE.get((declaration["jurisdiction_code"], hs_first_4))
    if rate is None:
        return Decimal("0.00")
    ct_base = base_value + _to_dec(tariff_amount)
    if ct_base < Decimal("100"):
        return Decimal("0.00")
    return _round2(ct_base * rate)


def compute_penalty_in_settlement(
    penalty_in_declared: Decimal | float | int,
    fx_rate_to_settlement: Decimal | float | int,
) -> Decimal:
    return _round2(_to_dec(penalty_in_declared) * _to_dec(fx_rate_to_settlement))


# ---------------------------------------------------------------------------
# compute_broker_fee (scaffold §1.3 / PRD §3.9)
# ---------------------------------------------------------------------------
def compute_broker_fee(
    declaration: dict[str, Any],
    agreement: dict[str, Any],
    has_inspection_case: bool,
    has_advance: bool,
) -> Decimal:
    services_consumed: list[str] = ["DECLARATION"]
    if has_inspection_case:
        services_consumed.append("INSPECTION")
    if has_advance:
        services_consumed.append("TARIFF_ADVANCE")
    if int(declaration.get("amendment_count", 0) or 0) > 0:
        services_consumed.append("AMENDMENT")

    fee_schedule = agreement.get("fee_schedule") or {}
    raw_total = Decimal("0")
    for svc in services_consumed:
        if svc in fee_schedule:
            raw_total += _to_dec(fee_schedule[svc])

    agreement_currency = agreement["agreement_currency"]
    declared_currency = declaration["declared_currency"]
    fx_agree_to_decl = AGREEMENT_FX_TABLE.get(
        (agreement_currency, declared_currency), Decimal("1")
    )
    fx_to_settle = _to_dec(declaration.get("fx_rate_to_settlement") or 1)
    return _round2(raw_total * fx_agree_to_decl * fx_to_settle)


# ---------------------------------------------------------------------------
# compute_late_interest (scaffold §1.3 / PRD §3.10)
# ---------------------------------------------------------------------------
def compute_late_interest(
    advance_paid_amount,
    reimbursement_due_at: Optional[str],
    now_iso: str,
    daily_rate_bps: int,
) -> Decimal:
    if not reimbursement_due_at:
        return Decimal("0.00")
    now = parse_iso(now_iso)
    due = parse_iso(reimbursement_due_at)
    if now <= due:
        return Decimal("0.00")
    elapsed = (now - due).total_seconds()
    days_late = math.ceil(elapsed / 86400)
    if days_late <= 0:
        return Decimal("0.00")
    rate_per_day = _to_dec(daily_rate_bps) / Decimal("10000")
    return _round2(_to_dec(advance_paid_amount) * rate_per_day * Decimal(days_late))


# ---------------------------------------------------------------------------
# compute_authenticity_score (scaffold §1.3 / PRD §3.4)
# ---------------------------------------------------------------------------
_URI_PATTERN = re.compile(r"^[a-z]+://.+$")


def compute_authenticity_score(
    this_doc: dict[str, Any],
    sibling_docs: list[dict[str, Any]],
    declaration_currency: str,
) -> tuple[Decimal, str]:
    # signal 1: total-match against partner doc type (INVOICE <-> PACKING_LIST).
    # Only applies to invoice/packing-list documents that carry a numeric total.
    # For documents that do not carry a numeric total (BoL, Contract, etc.),
    # this signal is not applicable — score as 1.0 (neutral / pass).
    doc_type = this_doc.get("doc_type")
    this_total = this_doc.get("declared_total_value")
    if doc_type not in {"COMMERCIAL_INVOICE", "PACKING_LIST"} or this_total is None:
        signal_total_match = Decimal("1")
    else:
        signal_total_match = Decimal("0")
        partner = "PACKING_LIST" if doc_type == "COMMERCIAL_INVOICE" else "COMMERCIAL_INVOICE"
        this_val = _to_dec(this_total)
        for sib in sibling_docs:
            if sib.get("id") == this_doc.get("id"):
                continue
            if sib.get("doc_type") != partner:
                continue
            sib_total = sib.get("declared_total_value")
            if sib_total is None:
                continue
            sib_val = _to_dec(sib_total)
            larger = max(this_val, sib_val)
            if larger == 0:
                continue
            diff = abs(this_val - sib_val)
            if diff <= larger * Decimal("0.005"):
                signal_total_match = Decimal("1")
                break

    # signal 2: currency consistency (spec: 1.0 iff declared_total_currency matches).
    # When the doc carries no declared_total_currency (e.g. BoL / Contract), the
    # signal is not applicable — score as 1.0 (neutral / pass).
    decl_curr = this_doc.get("declared_total_currency")
    if decl_curr is None:
        signal_currency = Decimal("1")
    else:
        signal_currency = (
            Decimal("1") if decl_curr == declaration_currency else Decimal("0")
        )

    # signal 3: URI format
    storage_uri = this_doc.get("storage_uri") or ""
    signal_uri = Decimal("1") if _URI_PATTERN.match(storage_uri) else Decimal("0.5")

    score = _round2(
        Decimal("0.5") * signal_total_match
        + Decimal("0.3") * signal_currency
        + Decimal("0.2") * signal_uri
    )
    status = "ACCEPTED" if score >= Decimal("0.70") else "FLAGGED"
    return score, status


# ---------------------------------------------------------------------------
# compute_declared_value_review (scaffold §1.3 / PRD §3.3)
# ---------------------------------------------------------------------------
def compute_declared_value_review(declaration: dict[str, Any]) -> str:
    hs_first_4 = (declaration.get("hs_code") or "")[:4]
    juris = declaration.get("jurisdiction_code")
    ref_price = REFERENCE_PRICE_TABLE.get((juris, hs_first_4))
    if ref_price is None:
        return "ACCEPTED"
    fx = declaration.get("fx_rate_to_settlement")
    if fx is None:
        fx_dec = Decimal("1")
    else:
        fx_dec = _to_dec(fx)
    base_value = _round2(_to_dec(declaration["declared_value_amount"]) * fx_dec)
    if ref_price == 0:
        return "ACCEPTED"
    deviation = abs(base_value - ref_price) / ref_price
    if deviation <= Decimal("0.25"):
        return "ACCEPTED"
    return "FLAGGED"


def fmt_amount(v: Decimal | float | int | None) -> Optional[float]:
    """Public helper — same as to_float2; alias for clarity."""
    return to_float2(v)
