"""Disposition service: create, amend, void, list, classify."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.errors import (
    APIError,
    err_disposition_date_out_of_range,
    err_invalid_disposition_state,
    err_not_found,
    err_not_owner,
    err_shares_exceed_balance,
    err_version_conflict,
)
from core.store import store
from core.utils import add_years, lock, new_id, parse_iso
from services.calculations import compute_disposition_tax_split
from services.timestamps import stamp_create, stamp_update


def get_disposition_or_404(disposition_id: str) -> dict:
    d = store.dispositions.get(disposition_id)
    if d is None:
        raise err_not_found(f"Disposition {disposition_id} not found.")
    return d


def _classify(disposition_date_str: str, *, grant_date_str: str, purchase_date_str: str) -> str:
    disp_dt = parse_iso(disposition_date_str)
    grant_dt = parse_iso(grant_date_str)
    purchase_dt = parse_iso(purchase_date_str)
    if disp_dt >= add_years(grant_dt, 2) and disp_dt >= add_years(purchase_dt, 1):
        return "QUALIFYING"
    return "DISQUALIFYING"


def _remaining_shares(purchase_id: str, *, exclude_disposition_id: Optional[str] = None) -> int:
    purchase = store.purchases[purchase_id]
    used = 0
    for d in store.dispositions.values():
        if d["purchase_id"] != purchase_id:
            continue
        if d["status"] == "VOIDED":
            continue
        if exclude_disposition_id is not None and d["id"] == exclude_disposition_id:
            continue
        used += d["shares_disposed"]
    return purchase["shares_purchased"] - used


def _apply_purchase_disposition_status(purchase_id: str) -> None:
    """Recompute the parent purchase's disposition_status from the latest set
    of non-voided dispositions."""
    purchase = store.purchases[purchase_id]
    active = [
        d
        for d in store.dispositions.values()
        if d["purchase_id"] == purchase_id and d["status"] != "VOIDED"
    ]
    if not active:
        previous = purchase["disposition_status"]
        if previous != "HELD":
            purchase["disposition_status"] = "HELD"
            stamp_update(purchase)
        return

    total_disposed = sum(d["shares_disposed"] for d in active)
    if total_disposed >= purchase["shares_purchased"]:
        # Use the classification of the most recent (created_at desc) active row.
        latest = max(active, key=lambda d: d["created_at"])
        new_status = (
            "DISPOSED_QUALIFYING"
            if latest["classification"] == "QUALIFYING"
            else "DISPOSED_DISQUALIFYING"
        )
        if purchase["disposition_status"] != new_status:
            purchase["disposition_status"] = new_status
            stamp_update(purchase)
    else:
        if purchase["disposition_status"] != "HELD":
            purchase["disposition_status"] = "HELD"
            stamp_update(purchase)


def create_disposition(
    *, acting_user_id: str, payload: Dict[str, Any]
) -> dict:
    from services.plan_service import get_plan_or_404
    from services.purchase_service import get_purchase_or_404

    purchase_id = payload.get("purchase_id")
    disposition_date = payload.get("disposition_date")
    shares_disposed = payload.get("shares_disposed")
    sale_price_per_share_cents = payload.get("sale_price_per_share_cents")

    if purchase_id is None:
        raise err_not_found("purchase_id is required.")

    with lock():
        purchase = get_purchase_or_404(purchase_id)

        # Ownership.
        if purchase["participant_id"] != acting_user_id:
            raise err_not_owner()

        # Field validation.
        if disposition_date is None:
            raise err_disposition_date_out_of_range("disposition_date is required.")
        try:
            disp_dt = parse_iso(disposition_date)
        except Exception:
            raise err_disposition_date_out_of_range("disposition_date must be ISO 8601.")

        if not isinstance(shares_disposed, int) or isinstance(shares_disposed, bool) or shares_disposed <= 0:
            raise APIError(
                "ERR_SHARES_EXCEED_BALANCE",
                "shares_disposed must be a positive integer.",
                422,
            )
        if not isinstance(sale_price_per_share_cents, int) or isinstance(sale_price_per_share_cents, bool) or sale_price_per_share_cents <= 0:
            raise APIError(
                "ERR_DISPOSITION_DATE_OUT_OF_RANGE",
                "sale_price_per_share_cents must be a positive integer.",
                422,
            )

        # Temporal window: disp_dt in [purchase_date, current_time].
        purchase_dt = parse_iso(purchase["purchase_date"])
        clock_dt = parse_iso(store.clock["current_time"])
        if disp_dt < purchase_dt or disp_dt > clock_dt:
            raise err_disposition_date_out_of_range()

        # Share-balance check.
        remaining = _remaining_shares(purchase_id)
        if shares_disposed > remaining:
            raise err_shares_exceed_balance()

        # Classification + tax split.
        owning_op = store.offering_periods.get(purchase["offering_period_id"])
        plan = get_plan_or_404(purchase["plan_id"])
        classification = _classify(
            disposition_date,
            grant_date_str=owning_op["start_date"],
            purchase_date_str=purchase["purchase_date"],
        )
        tax = compute_disposition_tax_split(
            classification=classification,
            shares_disposed=shares_disposed,
            sale_price_per_share_cents=sale_price_per_share_cents,
            purchase_price_cents=purchase["purchase_price_cents"],
            chosen_fmv_cents=purchase["chosen_fmv_cents"],
            purchase_date_fmv_cents=owning_op["purchase_date_fmv_cents"],
            discount_bp=plan["discount_bp"],
        )

        disposition = {
            "id": new_id(),
            "purchase_id": purchase_id,
            "participant_id": purchase["participant_id"],
            "disposition_date": disposition_date,
            "shares_disposed": shares_disposed,
            "sale_price_per_share_cents": sale_price_per_share_cents,
            "classification": classification,
            "ordinary_income_cents": tax["ordinary_income_cents"],
            "capital_gain_cents": tax["capital_gain_cents"],
            "status": "REPORTED",
        }
        stamp_create(disposition)
        store.dispositions[disposition["id"]] = disposition

        # Flip purchase.disposition_status if shares are exhausted.
        _apply_purchase_disposition_status(purchase_id)
    return disposition


def patch_disposition(
    *, disposition_id: str, acting_user_id: str, payload: Dict[str, Any]
) -> dict:
    from services.plan_service import get_plan_or_404
    from services.purchase_service import get_purchase_or_404

    with lock():
        d = get_disposition_or_404(disposition_id)
        if d["participant_id"] != acting_user_id:
            raise err_not_owner()
        if d["status"] != "REPORTED":
            raise err_invalid_disposition_state()

        # OCC.
        if "version" in payload and payload["version"] != d["version"]:
            raise err_version_conflict()

        purchase = get_purchase_or_404(d["purchase_id"])
        owning_op = store.offering_periods.get(purchase["offering_period_id"])
        plan = get_plan_or_404(purchase["plan_id"])

        new_date = payload.get("disposition_date", d["disposition_date"])
        new_shares = payload.get("shares_disposed", d["shares_disposed"])
        new_price = payload.get(
            "sale_price_per_share_cents", d["sale_price_per_share_cents"]
        )

        # Validate.
        try:
            disp_dt = parse_iso(new_date)
        except Exception:
            raise err_disposition_date_out_of_range("disposition_date must be ISO 8601.")
        purchase_dt = parse_iso(purchase["purchase_date"])
        clock_dt = parse_iso(store.clock["current_time"])
        if disp_dt < purchase_dt or disp_dt > clock_dt:
            raise err_disposition_date_out_of_range()
        if not isinstance(new_shares, int) or isinstance(new_shares, bool) or new_shares <= 0:
            raise APIError("ERR_SHARES_EXCEED_BALANCE", "shares_disposed must be a positive integer.", 422)
        if not isinstance(new_price, int) or isinstance(new_price, bool) or new_price <= 0:
            raise APIError("ERR_DISPOSITION_DATE_OUT_OF_RANGE", "sale_price_per_share_cents must be a positive integer.", 422)

        # Share-balance check (excluding this disposition).
        remaining = _remaining_shares(purchase["id"], exclude_disposition_id=d["id"])
        if new_shares > remaining:
            raise err_shares_exceed_balance()

        classification = _classify(
            new_date,
            grant_date_str=owning_op["start_date"],
            purchase_date_str=purchase["purchase_date"],
        )
        tax = compute_disposition_tax_split(
            classification=classification,
            shares_disposed=new_shares,
            sale_price_per_share_cents=new_price,
            purchase_price_cents=purchase["purchase_price_cents"],
            chosen_fmv_cents=purchase["chosen_fmv_cents"],
            purchase_date_fmv_cents=owning_op["purchase_date_fmv_cents"],
            discount_bp=plan["discount_bp"],
        )

        d["disposition_date"] = new_date
        d["shares_disposed"] = new_shares
        d["sale_price_per_share_cents"] = new_price
        d["classification"] = classification
        d["ordinary_income_cents"] = tax["ordinary_income_cents"]
        d["capital_gain_cents"] = tax["capital_gain_cents"]
        d["status"] = "AMENDED"
        stamp_update(d)

        _apply_purchase_disposition_status(purchase["id"])
    return d


def void_disposition(*, disposition_id: str, acting_user_id: str) -> None:
    with lock():
        d = get_disposition_or_404(disposition_id)
        if d["participant_id"] != acting_user_id:
            raise err_not_owner()
        if d["status"] not in ("REPORTED", "AMENDED"):
            raise err_invalid_disposition_state()

        d["status"] = "VOIDED"
        stamp_update(d)
        _apply_purchase_disposition_status(d["purchase_id"])


def list_dispositions_for_participant(
    participant_id: str,
    *,
    classification: Optional[str] = None,
    status: Optional[str] = None,
) -> list:
    items = [
        d for d in store.dispositions.values() if d["participant_id"] == participant_id
    ]
    if classification is not None:
        items = [d for d in items if d["classification"] == classification]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: d["created_at"])
    return items
