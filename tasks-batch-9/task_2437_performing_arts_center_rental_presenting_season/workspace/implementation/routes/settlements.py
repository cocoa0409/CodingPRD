"""Settlement, reconciliation and season close (PRD section 3.8)."""

from flask import Blueprint

import calc
import derive
from envelope import array_response, object_response
from errors import ApiError
from helpers import auth, body, page, req_int
from lookup import find_engagement, find_settlement
from store import public, stamp, store, touch

bp = Blueprint("settlements", __name__)


@bp.post("/engagements/<engagement_id>/settlements")
def open_settlement(engagement_id):
    auth("FinanceController")
    engagement = find_engagement(engagement_id)

    if derive.engagement_settlements(engagement["id"]):
        raise ApiError("ERR_DUPLICATE_SETTLEMENT")
    if engagement["lifecycle_status"] != "CONFIRMED":
        raise ApiError("ERR_PERFORMANCE_NOT_COMPLETE")
    if store.clock_dt < engagement["_performance_end"]:
        raise ApiError("ERR_PERFORMANCE_NOT_COMPLETE")

    # The booking advances to PERFORMED and the box office closes.
    engagement["lifecycle_status"] = "PERFORMED"
    engagement["ticketing_status"] = "CLOSED"
    for tier in derive.engagement_tiers(engagement["id"]):
        if tier["status"] == "ACTIVE":
            derive.apply_changes(tier, {"status": "CLOSED"})
    derive.recompute_realized_gross(engagement)
    touch(engagement)

    tiers = derive.engagement_tiers(engagement["id"])
    sold_sales = [s for s in derive.engagement_sales(engagement["id"]) if s["status"] == "SOLD"]
    single_gross = sum(s["gross_cents"] for s in sold_sales)
    subscription_revenue = sum(t["subscription_revenue_cents"] for t in tiers)
    box_office_gross = single_gross + subscription_revenue
    restoration = sum(s["restoration_fee_cents"] for s in sold_sales)
    actual_labor = sum(
        c["actual_cost_cents"]
        for c in derive.engagement_calls(engagement["id"])
        if c["status"] == "WORKED"
    )

    record = {
        "engagement_id": engagement["id"],
        "status": "DRAFT",
        "box_office_gross_cents": box_office_gross,
        "restoration_fees_cents": restoration,
        "adjusted_gross_cents": box_office_gross - restoration,
        "guarantee_cents": engagement["negotiated_fee_cents"],
        "actual_labor_cents": actual_labor,
        "actual_equipment_cents": engagement["additional_equipment_cost_cents"],
        "actual_marketing_cents": 0,
        "reimbursable_expense_cap_cents": 0,
        "reimbursable_expenses_cents": 0,
        "artist_share_cents": 0,
        "net_to_center_cents": 0,
        "reserve_contribution_cents": 0,
        "amount_payable_to_artist_cents": 0,
        "balance_due_from_client_cents": 0,
        "finalized_by_user_id": None,
    }
    stamp(record)
    store.settlements[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/engagements/<engagement_id>/settlements")
def list_settlements(engagement_id):
    auth("FinanceController", "ProgrammingDirector", "RentalManager", "RentalClientContact")
    engagement = find_engagement(engagement_id)
    window, meta = page(derive.engagement_settlements(engagement["id"]))
    return array_response([public(s) for s in window], meta)


@bp.post("/settlements/<settlement_id>/reconcile-expenses")
def reconcile_expenses(settlement_id):
    auth("FinanceController")
    settlement = find_settlement(settlement_id)
    data = body()
    actual_marketing = req_int(data, "actual_marketing_cents", minimum=0)

    if settlement["status"] != "DRAFT":
        raise ApiError("ERR_SETTLEMENT_INVALID_STATE")
    engagement = store.engagements.get(settlement["engagement_id"])
    calls = derive.engagement_calls(settlement["engagement_id"])
    if any(c["status"] == "ESTIMATED" for c in calls):
        raise ApiError(
            "ERR_SETTLEMENT_INVALID_STATE",
            "Every labor call must have reported hours or been cancelled.",
        )

    settlement["actual_marketing_cents"] = actual_marketing
    settlement["actual_labor_cents"] = sum(
        c["actual_cost_cents"] for c in calls if c["status"] == "WORKED"
    )
    if engagement["engagement_type"] == "PRESENTED":
        outputs = calc.settlement_presented(settlement, engagement["artist_share_pct"])
    else:
        outputs = calc.settlement_rental(
            settlement, engagement["facility_fee_cents"], engagement["deposit_paid_cents"]
        )
    settlement.update(outputs)
    settlement["status"] = "EXPENSES_RECONCILED"
    touch(settlement)
    return object_response(public(settlement))


@bp.post("/settlements/<settlement_id>/finalize")
def finalize_settlement(settlement_id):
    user_id, _role = auth("FinanceController")
    settlement = find_settlement(settlement_id)
    engagement = store.engagements.get(settlement["engagement_id"])

    if (
        engagement is not None
        and engagement["fee_accepted_by_user_id"] is not None
        and engagement["fee_accepted_by_user_id"] == user_id
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if settlement["status"] != "EXPENSES_RECONCILED":
        raise ApiError("ERR_SETTLEMENT_INVALID_STATE")
    if engagement["lifecycle_status"] != "PERFORMED":
        raise ApiError("ERR_PERFORMANCE_NOT_COMPLETE")

    settlement["finalized_by_user_id"] = user_id
    settlement["status"] = "FINALIZED"

    realized_gross = derive.recompute_realized_gross(engagement)
    engagement["realized_margin_cents"] = realized_gross - (
        settlement["guarantee_cents"]
        + settlement["artist_share_cents"]
        + settlement["actual_labor_cents"]
        + settlement["actual_equipment_cents"]
        + settlement["actual_marketing_cents"]
    )

    for call in derive.engagement_calls(engagement["id"]):
        if call["status"] == "WORKED":
            call["status"] = "RECONCILED"
            touch(call)

    derive.append_ledger(
        "SETTLEMENT_CONTRIBUTION",
        settlement["reserve_contribution_cents"],
        "Settlement contribution swept to the capital reserve.",
        engagement["id"],
    )

    if engagement["engagement_type"] == "PRESENTED":
        artist = store.artists.get(engagement["artist_id"])
        if artist is not None:
            artist["lifetime_guarantee_paid_cents"] += settlement[
                "amount_payable_to_artist_cents"
            ]
            touch(artist)
    else:
        client = store.clients.get(engagement["rental_client_id"])
        if client is not None:
            client["outstanding_balance_cents"] += settlement[
                "balance_due_from_client_cents"
            ]
            touch(client)

    engagement["lifecycle_status"] = "SETTLED"
    touch(engagement)
    touch(settlement)
    return object_response(public(settlement))
