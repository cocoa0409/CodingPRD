"""HAP ledger operations + the monthly sweep."""

from __future__ import annotations

import re
from typing import List, Optional

from app import clock, store
from app.errors import APIError, validation
from app.util import new_id


_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_month(month: str) -> str:
    if not isinstance(month, str) or not _MONTH_RE.match(month):
        raise validation("pay_period_month must be YYYY-MM")
    return month


def list_payments(*, tenancy_id: Optional[str], pay_period_month: Optional[str], status: Optional[str], landlord_id_filter: Optional[str]):
    out = []
    for h in store.hap_payments.values():
        if tenancy_id and h.get("tenancy_id") != tenancy_id:
            continue
        if pay_period_month and h.get("pay_period_month") != pay_period_month:
            continue
        if status and h.get("status") != status:
            continue
        if landlord_id_filter:
            tn = store.tenancies.get(h["tenancy_id"])
            if tn is None:
                continue
            unit = store.units.get(tn["unit_id"])
            if unit is None or unit.get("landlord_id") != landlord_id_filter:
                continue
        out.append(h)
    return out


def run_monthly_sweep(payload: dict) -> List[str]:
    payload = payload or {}
    month = _validate_month(payload.get("pay_period_month"))
    sweep_run_id = new_id()
    created: List[str] = []
    now = clock.now()
    for tn in list(store.tenancies.values()):
        if tn.get("status") not in ("ACTIVE", "ABATED"):
            continue
        voucher = store.vouchers.get(tn["voucher_id"])
        if voucher is None:
            continue
        if voucher.get("administering_pha_id") != store.DEFAULT_PHA:
            continue
        if tn["status"] == "ABATED":
            amount = 0
            row_status = "ABATED_SUSPENDED"
        else:
            amount = tn.get("current_hap_cents") or 0
            row_status = "PAID"
        row = _insert(
            tenancy_id=tn["id"],
            pay_period_month=month,
            amount_cents=amount,
            status=row_status,
            event_ref_type="SCHEDULED_MONTHLY",
            event_ref_id=sweep_run_id,
            created_at=now,
        )
        created.append(row["id"])
    return created


def emit_abatement_row(tenancy: dict, *, source_inspection_id: str) -> dict:
    now = clock.now()
    month = now.strftime("%Y-%m")
    return _insert(
        tenancy_id=tenancy["id"],
        pay_period_month=month,
        amount_cents=0,
        status="ABATED_SUSPENDED",
        event_ref_type="ABATEMENT",
        event_ref_id=source_inspection_id,
        created_at=now,
    )


def emit_portability_closeout(tenancy: dict, *, source_request_id: str) -> None:
    """Void any future-month prebooked HAP rows for this tenancy."""
    now = clock.now()
    month = now.strftime("%Y-%m")
    _insert(
        tenancy_id=tenancy["id"],
        pay_period_month=month,
        amount_cents=0,
        status="VOIDED_RETROACTIVE",
        event_ref_type="PORTABILITY_CLOSEOUT",
        event_ref_id=source_request_id,
        created_at=now,
    )


def _insert(*, tenancy_id, pay_period_month, amount_cents, status, event_ref_type, event_ref_id, created_at) -> dict:
    row_id = new_id()
    record = {
        "id": row_id,
        "created_at": created_at,
        "tenancy_id": tenancy_id,
        "pay_period_month": pay_period_month,
        "amount_cents": amount_cents,
        "status": status,
        "event_ref_type": event_ref_type,
        "event_ref_id": event_ref_id,
    }
    store.hap_payments[row_id] = record
    return record
