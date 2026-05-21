"""Purchase batch + Form 3922 issuance + holding-period sweep."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.errors import (
    APIError,
    err_annual_accrual_cap_exceeded,
    err_invalid_period_state,
    err_not_found,
    err_period_not_open,
    err_plan_not_active,
    err_sod_violation,
)
from core.store import store
from core.utils import add_years, format_iso, lock, new_id, parse_iso
from services.calculations import compute_purchase_settlement
from services.contribution_service import has_period_posters_overlap
from services.timestamps import stamp_create, stamp_update


def get_purchase_or_404(purchase_id: str) -> dict:
    p = store.purchases.get(purchase_id)
    if p is None:
        raise err_not_found(f"Purchase {purchase_id} not found.")
    return p


def run_purchase_batch(*, offering_period_id: str, acting_user_id: str) -> dict:
    from services.offering_period_service import (
        _create_offering_period_internal,
        get_offering_period_or_404,
    )
    from services.plan_service import get_plan_or_404

    with lock():
        op = get_offering_period_or_404(offering_period_id)
        plan = get_plan_or_404(op["plan_id"])

        if plan["status"] != "ACTIVE":
            raise err_plan_not_active()

        # State: period must be CLOSED.
        if op["status"] != "CLOSED":
            if op["status"] == "PURCHASED":
                raise APIError(
                    "ERR_INVALID_PERIOD_STATE",
                    "OfferingPeriod is already PURCHASED.",
                    409,
                )
            raise APIError(
                "ERR_INVALID_PERIOD_STATE",
                f"OfferingPeriod status is {op['status']}, must be CLOSED.",
                409,
            )

        # Segregation of duties.
        if has_period_posters_overlap(
            offering_period_id=offering_period_id, candidate_user_id=acting_user_id
        ):
            raise err_sod_violation()

        # Process each ACTIVE enrollment.
        purchases_created: List[dict] = []
        forms_created: List[dict] = []

        enrollments = [
            e
            for e in store.enrollments.values()
            if e["offering_period_id"] == offering_period_id
            and e["status"] == "ACTIVE"
        ]
        enrollments.sort(key=lambda e: e["id"])

        for enrollment in enrollments:
            posted_contribs = [
                c
                for c in store.contributions.values()
                if c["enrollment_id"] == enrollment["id"] and c["status"] == "POSTED"
            ]
            total_posted = sum(c["amount_cents"] for c in posted_contribs)

            settlement = compute_purchase_settlement(
                grant_date_fmv_cents=op["grant_date_fmv_cents"],
                purchase_date_fmv_cents=op["purchase_date_fmv_cents"],
                lookback_enabled=plan["lookback_enabled"],
                discount_bp=plan["discount_bp"],
                posted_contribution_cents=total_posted,
                annual_accrual_cap_cents=plan["annual_accrual_cap_cents"],
                ytd_accrual_cents=enrollment["ytd_accrual_cents"],
            )

            # Defensive accrual check post-step-F.
            projected_total = enrollment["ytd_accrual_cents"] + settlement["accrual_charge_cents"]
            if projected_total > plan["annual_accrual_cap_cents"]:
                raise err_annual_accrual_cap_exceeded()

            purchase = {
                "id": new_id(),
                "plan_id": plan["id"],
                "offering_period_id": op["id"],
                "enrollment_id": enrollment["id"],
                "participant_id": enrollment["participant_id"],
                "purchase_date": op["end_date"],
                "contributions_used_cents": settlement["contributions_used_cents"],
                "chosen_fmv_cents": settlement["chosen_fmv_cents"],
                "purchase_price_cents": settlement["purchase_price_cents"],
                "shares_purchased": settlement["shares_purchased"],
                "refund_cents": settlement["refund_cents"],
                "holding_period_status": "WITHIN_BOTH",
                "disposition_status": "HELD",
            }
            stamp_create(purchase)
            store.purchases[purchase["id"]] = purchase
            purchases_created.append(purchase)

            # Flip contributions to CONSUMED.
            for c in posted_contribs:
                c["status"] = "CONSUMED"

            # Update enrollment accrual + status.
            enrollment["ytd_accrual_cents"] += settlement["accrual_charge_cents"]
            enrollment["status"] = "COMPLETED"
            stamp_update(enrollment)

            # Issue immutable Form 3922.
            form = {
                "id": new_id(),
                "purchase_id": purchase["id"],
                "participant_id": purchase["participant_id"],
                "grant_date": op["start_date"],
                "purchase_date": op["end_date"],
                "fmv_grant_date_cents": op["grant_date_fmv_cents"],
                "fmv_purchase_date_cents": op["purchase_date_fmv_cents"],
                "exercise_price_per_share_cents": purchase["purchase_price_cents"],
                "shares_transferred": purchase["shares_purchased"],
                "legal_title_date": op["end_date"],
            }
            # Form has only id + created_at; we also store issuance_timestamp.
            stamp_create(form, with_updated=False, with_version=False)
            form["issuance_timestamp"] = form["created_at"]
            store.form_3922s[form["id"]] = form
            forms_created.append(form)

        # Transition the period.
        op["status"] = "PURCHASED"
        stamp_update(op)

        # Create the next OfferingPeriod.
        next_seq = op["sequence_number"] + 1
        next_op = _create_offering_period_internal(
            plan=plan, sequence_number=next_seq, start_date=op["end_date"]
        )

    return {
        "offering_period_id": offering_period_id,
        "purchases": purchases_created,
        "form_3922s": forms_created,
        "next_offering_period_id": next_op["id"],
    }


def run_sweep() -> dict:
    """Maturation sweep — drives OP OPEN->CLOSED and Purchase holding-period
    transitions. Also stamps last_sweep_at on the clock.
    """
    from services.clock_service import get_clock_snapshot, _set_last_sweep

    with lock():
        clock = store.clock
        current_time_str = clock["current_time"]
        current_time = parse_iso(current_time_str)

        op_transitions: List[str] = []
        for op in store.offering_periods.values():
            if op["status"] != "OPEN":
                continue
            end_dt = parse_iso(op["end_date"])
            if current_time >= end_dt and op["purchase_date_fmv_cents"] is not None:
                op["status"] = "CLOSED"
                stamp_update(op)
                op_transitions.append(op["id"])

        purchase_transitions: List[Dict[str, str]] = []
        for purchase in store.purchases.values():
            if purchase["disposition_status"] != "HELD":
                continue
            grant_dt = parse_iso(purchase["purchase_date"])  # placeholder
            # We need grant_date from the owning offering period for the 2-year
            # threshold; fetch it.
            owning_op = store.offering_periods.get(purchase["offering_period_id"])
            if owning_op is None:
                continue
            grant_dt = parse_iso(owning_op["start_date"])
            purchase_dt = parse_iso(purchase["purchase_date"])
            one_year_from_purchase = add_years(purchase_dt, 1)
            two_years_from_grant = add_years(grant_dt, 2)

            previous = purchase["holding_period_status"]
            new_status = previous
            if previous == "WITHIN_BOTH":
                if current_time >= two_years_from_grant and current_time >= one_year_from_purchase:
                    new_status = "QUALIFYING_MATURE"
                elif current_time >= one_year_from_purchase and current_time < two_years_from_grant:
                    new_status = "PAST_ONE_YEAR_FROM_PURCHASE"
            elif previous == "PAST_ONE_YEAR_FROM_PURCHASE":
                if current_time >= two_years_from_grant:
                    new_status = "QUALIFYING_MATURE"

            if new_status != previous:
                purchase["holding_period_status"] = new_status
                stamp_update(purchase)
                purchase_transitions.append(
                    {"purchase_id": purchase["id"], "from": previous, "to": new_status}
                )

        _set_last_sweep(format_iso(current_time))

    return {
        "swept_at": store.clock["last_sweep_at"],
        "offering_periods_closed": op_transitions,
        "purchase_holding_transitions": purchase_transitions,
    }


def list_purchases_for_participant(
    participant_id: str,
    *,
    holding_period_status: Optional[str] = None,
    disposition_status: Optional[str] = None,
) -> list:
    items = [
        p for p in store.purchases.values() if p["participant_id"] == participant_id
    ]
    if holding_period_status is not None:
        items = [p for p in items if p["holding_period_status"] == holding_period_status]
    if disposition_status is not None:
        items = [p for p in items if p["disposition_status"] == disposition_status]
    items.sort(key=lambda p: p["created_at"])
    return items
