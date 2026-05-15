"""Commission calculations: gross commission, tax withholding, clawback."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

from clock import iso_now
from store import append_audit, init_no_common_fields, store


BPS_DENOMINATOR = Decimal(10000)
FIRST_SLICE_CAP_CENTS = Decimal(10000000)
REMAINDER_DISCOUNT_FACTOR = Decimal("0.5")
BONUS_SHARE_FACTOR = Decimal("0.25")


def _round_half_up(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_gross_commission(
    base_salary_cents: int, sign_on_bonus_cents: int, contract: Dict[str, Any]
) -> int:
    fee_model = contract["fee_model"]
    pct_bps = Decimal(int(contract.get("success_fee_pct_bps") or 0))
    retainer = Decimal(int(contract.get("retainer_amount_cents") or 0))
    base = Decimal(int(base_salary_cents))
    bonus = Decimal(int(sign_on_bonus_cents))

    if fee_model == "SUCCESS_FEE":
        first_slice = min(base, FIRST_SLICE_CAP_CENTS) * pct_bps / BPS_DENOMINATOR
        remainder = (
            max(Decimal(0), base - FIRST_SLICE_CAP_CENTS)
            * pct_bps
            / BPS_DENOMINATOR
            * REMAINDER_DISCOUNT_FACTOR
        )
        bonus_share = bonus * pct_bps / BPS_DENOMINATOR * BONUS_SHARE_FACTOR
        retainer_part = Decimal(0)
    elif fee_model == "RETAINER":
        first_slice = Decimal(0)
        remainder = Decimal(0)
        bonus_share = Decimal(0)
        retainer_part = retainer
    else:  # HYBRID
        first_slice = min(base, FIRST_SLICE_CAP_CENTS) * pct_bps / BPS_DENOMINATOR
        remainder = (
            max(Decimal(0), base - FIRST_SLICE_CAP_CENTS)
            * pct_bps
            / BPS_DENOMINATOR
            * REMAINDER_DISCOUNT_FACTOR
        )
        bonus_share = bonus * pct_bps / BPS_DENOMINATOR * BONUS_SHARE_FACTOR
        retainer_part = retainer

    raw_total = first_slice + remainder + bonus_share + retainer_part
    return _round_half_up(raw_total)


def compute_tax_withheld(gross: int, contract: Dict[str, Any]) -> int:
    pct_bps = Decimal(int(contract.get("tax_withholding_pct_bps") or 0))
    raw = Decimal(gross) * pct_bps / BPS_DENOMINATOR
    return _round_half_up(raw)


def create_commission_record(
    *,
    contract: Dict[str, Any],
    application: Dict[str, Any],
    offer: Dict[str, Any],
    trigger_kind: str,
    actor_role: str,
    actor_user_id: str,
) -> Dict[str, Any]:
    gross = compute_gross_commission(
        int(offer["base_salary_cents"]),
        int(offer.get("sign_on_bonus_cents") or 0),
        contract,
    )
    tax = compute_tax_withheld(gross, contract)
    row = init_no_common_fields(
        {
            "headhunter_contract_id": contract["id"],
            "application_id": application["id"],
            "gross_commission_cents": gross,
            "tax_withheld_cents": tax,
            "net_settlement_cents": 0,
            "settlement_status": "ACCRUED",
            "trigger_kind": trigger_kind,
            "settled_at": None,
            "clawback_amount_cents": 0,
        }
    )
    store.commission_records[row["id"]] = row
    append_audit(
        subject_entity="CommissionRecord",
        subject_id=row["id"],
        event_kind="COMMISSION_ACCRUED",
        from_state=None,
        to_state=None,
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
    return row


def maybe_create_for_trigger(
    *,
    application: Dict[str, Any],
    offer: Dict[str, Any],
    expected_trigger: str,
    actor_role: str,
    actor_user_id: str,
) -> Optional[Dict[str, Any]]:
    """Create a CommissionRecord if the application's source is HEADHUNTER and
    the contract's trigger_event matches expected_trigger."""
    if application.get("source_channel") != "HEADHUNTER":
        return None
    contract_id = application.get("headhunter_contract_id")
    if not contract_id:
        return None
    contract = store.headhunter_contracts.get(contract_id)
    if contract is None:
        return None
    if contract.get("trigger_event") != expected_trigger:
        return None
    return create_commission_record(
        contract=contract,
        application=application,
        offer=offer,
        trigger_kind=expected_trigger,
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )


def clawback_record(record: Dict[str, Any], actor_role: str, actor_user_id: str) -> None:
    record["settlement_status"] = "CLAWED_BACK"
    record["clawback_amount_cents"] = int(record["gross_commission_cents"]) - int(
        record["tax_withheld_cents"]
    )
    record["net_settlement_cents"] = 0
    append_audit(
        subject_entity="CommissionRecord",
        subject_id=record["id"],
        event_kind="COMMISSION_CLAWBACK",
        from_state=None,
        to_state=None,
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )


def project_view(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a serializable view. While ACCRUED, the read surfaces a
    forward-looking projected net (gross - tax) via net_settlement_cents
    per PRD §3.8."""
    out = dict(record)
    if record.get("settlement_status") == "ACCRUED":
        projected = int(record["gross_commission_cents"]) - int(record["tax_withheld_cents"])
        projected = max(0, projected)
        out["net_settlement_cents"] = projected
        out["projected_net_settlement_cents"] = projected
    return out
