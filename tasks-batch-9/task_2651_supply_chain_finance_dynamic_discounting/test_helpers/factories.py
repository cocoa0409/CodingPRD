"""Request-payload factories.

Every factory returns a plain dict whose money fields are Python ``int`` cents
and whose rate fields are Python ``int`` basis points — never strings, never
floats. Percentages are the one exception: ``concentration_cap_pct`` is a
2-decimal number. Keyword arguments override any default.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_CONCENTRATION_CAP_PCT,
    DEFAULT_MIN_DAYS_EARLY,
)

# ─── Unique-value generators ──────────────────────────
# tax_id must be exactly nine digits and unique across buyers.
_tax_id_counter = itertools.count(1)
_supplier_counter = itertools.count(1)
_funder_counter = itertools.count(1)
_file_counter = itertools.count(1)
_invoice_counter = itertools.count(1)


def next_tax_id() -> str:
    """A fresh nine-digit buyer tax identifier."""
    return "5{:08d}".format(next(_tax_id_counter))


def next_invoice_number(prefix: str = "INV") -> str:
    return "{}-{:05d}".format(prefix, next(_invoice_counter))


def next_filename(prefix: str = "AP") -> str:
    return "{}-{:04d}.csv".format(prefix, next(_file_counter))


# ─── Buyer ────────────────────────────────────────────
def buyer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Acme Manufacturing Holdings",
        "tax_id": next_tax_id(),
        "credit_limit_cents": 100_000_000,
    }
    payload.update(overrides)
    return payload


# ─── Buyer programme ──────────────────────────────────
def program_payload(buyer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "buyer_id": buyer_id,
        "name": "Q3 Dynamic Discounting Programme",
        "program_type": "SUPPLIER_NAMED",
        "max_acceptable_apr_bps": 1200,
        "min_days_early": DEFAULT_MIN_DAYS_EARLY,
        "concentration_cap_pct": 100.00,
        "funding_policy": "SELF_ONLY",
    }
    payload.update(overrides)
    return payload


def minimal_program_payload(buyer_id: str, **overrides: Any) -> Dict[str, Any]:
    """Only the mandatory fields, so every optional default is exercised."""
    payload: Dict[str, Any] = {
        "buyer_id": buyer_id,
        "name": "Defaults Only Programme",
        "program_type": "SUPPLIER_NAMED",
        "max_acceptable_apr_bps": 1200,
    }
    payload.update(overrides)
    return payload


def program_status_payload(action: str) -> Dict[str, Any]:
    return {"action": action}


# ─── Auction session ──────────────────────────────────
def session_payload(
    program_id: str,
    opens_at: str = "2026-08-02T00:00:00Z",
    closes_at: str = "2026-08-31T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "opens_at": opens_at,
        "closes_at": closes_at,
    }
    payload.update(overrides)
    return payload


def session_close_payload(mode: str = "SETTLE") -> Dict[str, Any]:
    return {"mode": mode}


# ─── Supplier ─────────────────────────────────────────
def supplier_payload(**overrides: Any) -> Dict[str, Any]:
    n = next(_supplier_counter)
    payload: Dict[str, Any] = {
        "legal_name": "Precision Components Supply {}".format(n),
        "tax_id_last4": "{:04d}".format(1000 + (n % 9000)),
        "remittance_email": "ar{}@supplier.example".format(n),
    }
    payload.update(overrides)
    return payload


def idv_payload(decision: str = "PASSED", identity_score: Optional[int] = 90) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if identity_score is not None:
        payload["identity_score"] = identity_score
    return payload


def sanctions_hold_payload(hold: bool) -> Dict[str, Any]:
    return {"hold": hold}


def bank_account_payload(
    routing_number: str = "021000021",
    account_last4: str = "4321",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "routing_number": routing_number,
        "account_last4": account_last4,
    }
    payload.update(overrides)
    return payload


def expected_micro_deposit_code(routing_number: str, account_last4: str) -> str:
    """The code is the last three digits of the routing number followed by the
    first three digits of ``account_last4``."""
    return routing_number[-3:] + account_last4[:3]


def micro_deposit_payload(code: str) -> Dict[str, Any]:
    return {"code": code}


# ─── Payable file ─────────────────────────────────────
def invoice_line(line_no: int, line_amount_cents: int, tax_rate_bps: int = 0) -> Dict[str, Any]:
    return {
        "line_no": line_no,
        "line_amount_cents": line_amount_cents,
        "tax_rate_bps": tax_rate_bps,
    }


def payable_row(
    supplier_id: str,
    invoice_number: Optional[str] = None,
    approval_date: str = "2026-07-20T00:00:00Z",
    net_due_date: str = "2026-09-30T00:00:00Z",
    lines: Optional[List[Dict[str, Any]]] = None,
    line_amount_cents: int = 100_000,
    tax_rate_bps: int = 0,
    suppression_flag: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "invoice_number": invoice_number or next_invoice_number(),
        "approval_date": approval_date,
        "net_due_date": net_due_date,
        "supplier_id": supplier_id,
        "lines": lines
        if lines is not None
        else [invoice_line(1, line_amount_cents, tax_rate_bps)],
    }
    if suppression_flag is not None:
        row["suppression_flag"] = suppression_flag
    row.update(overrides)
    return row


def row_face_cents(row: Dict[str, Any]) -> int:
    """Face of one row: each line's tax is rounded half up before summing."""
    total = 0
    for line in row["lines"]:
        amount = line["line_amount_cents"]
        tax = round_half_up_div(amount * line["tax_rate_bps"], 10_000)
        total += amount + tax
    return total


def round_half_up_div(numerator: int, denominator: int) -> int:
    """Integer division rounding halves away from zero (half up)."""
    if numerator < 0:
        return -((-numerator * 2 + denominator) // (2 * denominator))
    return (numerator * 2 + denominator) // (2 * denominator)


def payable_file_payload(
    program_id: str,
    rows: List[Dict[str, Any]],
    filename: Optional[str] = None,
    declared_row_count: Optional[int] = None,
    declared_total_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "filename": filename or next_filename(),
        "declared_row_count": (
            declared_row_count if declared_row_count is not None else len(rows)
        ),
        "declared_total_cents": (
            declared_total_cents
            if declared_total_cents is not None
            else sum(row_face_cents(r) for r in rows)
        ),
        "rows": rows,
    }
    payload.update(overrides)
    return payload


# ─── Disputes ─────────────────────────────────────────
def dispute_payload(
    disputed_amount_cents: int,
    reason_code: str = "SHORT_SHIPMENT",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reason_code": reason_code,
        "disputed_amount_cents": disputed_amount_cents,
    }
    payload.update(overrides)
    return payload


def dispute_resolution_payload(
    resolution: str, resolution_note: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"resolution": resolution}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return payload


# ─── Discount offers ──────────────────────────────────
def offer_payload(
    invoice_id: str,
    session_id: str,
    expected_invoice_version: int,
    offered_apr_bps: int = 900,
    requested_pay_date: str = "2026-08-05T00:00:00Z",
    acceptance_deadline: str = "2026-08-20T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "invoice_id": invoice_id,
        "session_id": session_id,
        "offered_apr_bps": offered_apr_bps,
        "requested_pay_date": requested_pay_date,
        "acceptance_deadline": acceptance_deadline,
        "expected_invoice_version": expected_invoice_version,
    }
    payload.update(overrides)
    return payload


def counter_payload(counter_apr_bps: int) -> Dict[str, Any]:
    return {"counter_apr_bps": counter_apr_bps}


def rename_payload(
    offered_apr_bps: int, requested_pay_date: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"offered_apr_bps": offered_apr_bps}
    if requested_pay_date is not None:
        payload["requested_pay_date"] = requested_pay_date
    return payload


# ─── Funders ──────────────────────────────────────────
def funder_payload(**overrides: Any) -> Dict[str, Any]:
    n = next(_funder_counter)
    payload: Dict[str, Any] = {
        "legal_name": "Receivables Capital Partners {}".format(n),
        "capital_limit_cents": 60_000_000,
        "min_apr_bps": 500,
        "fee_spread_bps": 0,
        "max_single_invoice_cents": 5_000_000,
    }
    payload.update(overrides)
    return payload


def commitment_payload(
    committed_amount_cents: int = 60_000_000,
    effective_from: str = "2026-08-01T00:00:00Z",
    effective_to: str = "2026-12-31T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "committed_amount_cents": committed_amount_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return payload


def funder_participation_payload(action: str) -> Dict[str, Any]:
    return {"action": action}


# ─── Early payments ───────────────────────────────────
def early_payment_payload(
    offer_id: str, expected_offer_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "offer_id": offer_id,
        "expected_offer_version": expected_offer_version,
    }
    payload.update(overrides)
    return payload


def settlement_failure_payload(
    failure_reason: str = "Beneficiary bank returned the credit transfer",
) -> Dict[str, Any]:
    return {"failure_reason": failure_reason}


def classification_payload(
    classification: str, override_reason: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"classification": classification}
    if override_reason is not None:
        payload["override_reason"] = override_reason
    return payload


# ─── Derived expectations ─────────────────────────────
def expected_discount_cents(face_cents: int, apr_bps: int, days_early: int) -> int:
    """face * apr_bps * days_early / (10000 * 360), rounded half up."""
    return round_half_up_div(face_cents * apr_bps * days_early, 10_000 * 360)


def expected_fee_bps(pre_fee_net_cents: int, fee_spread_bps: int = 0) -> int:
    """The tier is keyed on the pre-fee net, then the funder's spread is added."""
    if pre_fee_net_cents < 5_000_000:
        tier = 45
    elif pre_fee_net_cents < 25_000_000:
        tier = 30
    else:
        tier = 18
    return tier + fee_spread_bps


def expected_funder_fee_cents(pre_fee_net_cents: int, fee_spread_bps: int = 0) -> int:
    """Fee is the tier-plus-spread rate applied to the pre-fee net, half up."""
    bps = expected_fee_bps(pre_fee_net_cents, fee_spread_bps)
    return round_half_up_div(pre_fee_net_cents * bps, 10_000)
