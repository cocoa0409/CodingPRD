"""Entity -> JSON projections.  Field names come straight from the scaffold."""

from calc import number
from store import fmt_ts


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": fmt_ts(entity["created_at"]),
        "updated_at": fmt_ts(entity["updated_at"]),
        "version": entity["version"],
    }


def market_json(market, overrides=None):
    data = {
        "name": market["name"],
        "region_code": market["region_code"],
        "guarantee_exposure_limit_cents": market["guarantee_exposure_limit_cents"],
        "committed_guarantee_cents": market["committed_guarantee_cents"],
        "at_risk_guarantee_cents": market["at_risk_guarantee_cents"],
        "exposure_utilization_pct": number(market["exposure_utilization_pct"]),
        "risk_posture": market["risk_posture"],
        "settled_show_count": market["settled_show_count"],
        "performance_index": market["performance_index"],
    }
    if overrides:
        for key, value in overrides.items():
            data[key] = number(value)
    data.update(_common(market))
    return data


def artist_json(artist):
    data = {
        "name": artist["name"],
        "agency": artist["agency"],
        "tier": artist["tier"],
        "historical_sellthrough_pct": number(artist["historical_sellthrough_pct"]),
        "withholding_pct": number(artist["withholding_pct"]),
        "confirmed_show_count": artist["confirmed_show_count"],
    }
    data.update(_common(artist))
    return data


def venue_json(venue):
    data = {
        "market_id": venue["market_id"],
        "name": venue["name"],
        "gross_capacity": venue["gross_capacity"],
        "facility_fee_cents_per_ticket": venue["facility_fee_cents_per_ticket"],
        "ticket_tax_pct": number(venue["ticket_tax_pct"]),
    }
    data.update(_common(venue))
    return data


def show_json(show):
    data = {
        "artist_id": show["artist_id"],
        "venue_id": show["venue_id"],
        "market_id": show["market_id"],
        "rescheduled_from_show_id": show["rescheduled_from_show_id"],
        "event_at": fmt_ts(show["event_at"]),
        "load_in_at": fmt_ts(show["load_in_at"]),
        "load_out_at": fmt_ts(show["load_out_at"]),
        "announce_at": fmt_ts(show["announce_at"]),
        "show_status": show["show_status"],
        "sales_status": show["sales_status"],
        "venue_arrangement": show["venue_arrangement"],
        "rental_fee_cents": show["rental_fee_cents"],
        "copromote_venue_share_pct": number(show["copromote_venue_share_pct"]),
        "venue_expense_pct_production": number(show["venue_expense_pct_production"]),
        "venue_expense_pct_marketing": number(show["venue_expense_pct_marketing"]),
        "venue_expense_pct_staffing": number(show["venue_expense_pct_staffing"]),
        "venue_expense_pct_hospitality": number(show["venue_expense_pct_hospitality"]),
        "exposure_override_limit_cents": show["exposure_override_limit_cents"],
        "exposure_override_justification": show["exposure_override_justification"],
        "exposure_override_by_user_id": show["exposure_override_by_user_id"],
        "committed_guarantee_cents": show["committed_guarantee_cents"],
        "gross_sold_cents": show["gross_sold_cents"],
        "paid_tickets_sold": show["paid_tickets_sold"],
        "comp_tickets_issued": show["comp_tickets_issued"],
        "held_tickets": show["held_tickets"],
        "transferred_in_gross_cents": show["transferred_in_gross_cents"],
        "transferred_in_paid_tickets": show["transferred_in_paid_tickets"],
        "adjusted_gross_cents": show["adjusted_gross_cents"],
        "total_budgeted_expense_cents": show["total_budgeted_expense_cents"],
        "total_actual_expense_cents": show["total_actual_expense_cents"],
        "breakeven_cents": show["breakeven_cents"],
        "projected_adjusted_gross_cents": show["projected_adjusted_gross_cents"],
        "projected_promoter_net_cents": show["projected_promoter_net_cents"],
        "budget_posture": show["budget_posture"],
        "refund_liability_cents": show["refund_liability_cents"],
    }
    data.update(_common(show))
    return data


def offer_json(offer):
    data = {
        "show_id": offer["show_id"],
        "deal_structure": offer["deal_structure"],
        "guarantee_cents": offer["guarantee_cents"],
        "deposit_cents": offer["deposit_cents"],
        "expense_cap_cents": offer["expense_cap_cents"],
        "versus_pct": number(offer["versus_pct"]),
        "backend_split_artist_pct": number(offer["backend_split_artist_pct"]),
        "status": offer["status"],
        "round_index": offer["round_index"],
        "submitted_at": fmt_ts(offer["submitted_at"]),
        "expires_at": fmt_ts(offer["expires_at"]),
        "counter_guarantee_cents": offer["counter_guarantee_cents"],
        "counter_versus_pct": number(offer["counter_versus_pct"]),
        "counter_backend_split_artist_pct":
            number(offer["counter_backend_split_artist_pct"]),
        "counter_note": offer["counter_note"],
        "accepted_by_user_id": offer["accepted_by_user_id"],
    }
    data.update(_common(offer))
    return data


def budget_line_json(line):
    data = {
        "show_id": line["show_id"],
        "category": line["category"],
        "description": line["description"],
        "budgeted_cents": line["budgeted_cents"],
        "is_artist_deductible": line["is_artist_deductible"],
        "actual_cents": line["actual_cents"],
        "variance_cents": line["variance_cents"],
        "variance_pct": number(line["variance_pct"]),
        "variance_status": line["variance_status"],
        "required_approver_role": line["required_approver_role"],
        "approved_cap_cents": line["approved_cap_cents"],
        "variance_decided_by_user_id": line["variance_decided_by_user_id"],
        "variance_justification": line["variance_justification"],
        "settlement_expense_cents": line["settlement_expense_cents"],
        "status": line["status"],
    }
    data.update(_common(line))
    return data


def vendor_invoice_json(invoice):
    data = {
        "show_id": invoice["show_id"],
        "budget_line_id": invoice["budget_line_id"],
        "vendor_name": invoice["vendor_name"],
        "amount_cents": invoice["amount_cents"],
        "invoice_date": invoice["invoice_date"],
        "documentation_ref": invoice["documentation_ref"],
        "status": invoice["status"],
        "verified_by_user_id": invoice["verified_by_user_id"],
        "approved_by_user_id": invoice["approved_by_user_id"],
        "dispute_reason": invoice["dispute_reason"],
        "resubmit_count": invoice["resubmit_count"],
    }
    data.update(_common(invoice))
    return data


def ticket_tier_json(tier):
    data = {
        "show_id": tier["show_id"],
        "tier_name": tier["tier_name"],
        "price_cents": tier["price_cents"],
        "allocation_qty": tier["allocation_qty"],
        "sold_qty": tier["sold_qty"],
        "gross_sold_cents": tier["gross_sold_cents"],
        "comp_qty": tier["comp_qty"],
        "held_qty": tier["held_qty"],
        "available_qty": tier["available_qty"],
        "price_revision_count": tier["price_revision_count"],
        "last_price_cents": tier["last_price_cents"],
        "status": tier["status"],
    }
    data.update(_common(tier))
    return data


def ticket_hold_json(hold):
    data = {
        "ticket_tier_id": hold["ticket_tier_id"],
        "kind": hold["kind"],
        "qty": hold["qty"],
        "holder": hold["holder"],
        "expires_at": fmt_ts(hold["expires_at"]),
        "status": hold["status"],
        "released_by_user_id": hold["released_by_user_id"],
    }
    data.update(_common(hold))
    return data


SETTLEMENT_MONEY_FIELDS = (
    "gross_receipts_cents", "ticket_tax_cents", "facility_fee_cents",
    "credit_card_fee_cents", "adjusted_gross_cents",
    "total_settlement_expense_cents", "allowed_expense_cents",
    "venue_expense_reimbursement_cents", "promoter_borne_expense_cents",
    "breakeven_cents", "artist_base_earnings_cents",
    "artist_coop_contribution_cents", "artist_earnings_cents",
    "withholding_cents", "deposit_credit_cents", "payment_due_cents",
    "venue_share_cents", "promoter_net_cents",
)


def settlement_json(settlement):
    data = {
        "show_id": settlement["show_id"],
        "status": settlement["status"],
        "deal_structure_applied": settlement["deal_structure_applied"],
    }
    for field in SETTLEMENT_MONEY_FIELDS:
        data[field] = settlement[field]
    data.update({
        "calculated_by_user_id": settlement["calculated_by_user_id"],
        "signed_by_user_id": settlement["signed_by_user_id"],
        "paid_at": fmt_ts(settlement["paid_at"]),
        "payment_method": settlement["payment_method"],
        "payment_reference": settlement["payment_reference"],
        "dispute_reason": settlement["dispute_reason"],
        "reopen_count": settlement["reopen_count"],
        "reopen_reason": settlement["reopen_reason"],
    })
    data.update(_common(settlement))
    return data


def projection_json(show_id, figures):
    """settlement-projection: settlement-shaped, never persisted."""
    data = {
        "id": None,
        "created_at": None,
        "updated_at": None,
        "version": None,
        "show_id": show_id,
        "status": "DRAFT",
        "deal_structure_applied": figures.get("deal_structure_applied"),
    }
    for field in SETTLEMENT_MONEY_FIELDS:
        data[field] = figures.get(field, 0)
    data.update({
        "calculated_by_user_id": None,
        "signed_by_user_id": None,
        "paid_at": None,
        "payment_method": None,
        "payment_reference": None,
        "dispute_reason": None,
        "reopen_count": 0,
        "reopen_reason": None,
    })
    return data


def cancellation_event_json(event):
    data = {
        "show_id": event["show_id"],
        "replacement_show_id": event["replacement_show_id"],
        "kind": event["kind"],
        "reason": event["reason"],
        "status": event["status"],
        "occurred_at": fmt_ts(event["occurred_at"]),
        "refund_liability_cents": event["refund_liability_cents"],
        "refunded_ticket_count": event["refunded_ticket_count"],
        "unrecovered_cost_cents": event["unrecovered_cost_cents"],
        "claim_amount_cents": event["claim_amount_cents"],
        "covered_loss_cents": event["covered_loss_cents"],
        "insurance_recovery_cents": event["insurance_recovery_cents"],
        "claim_documentation_ref": event["claim_documentation_ref"],
        "insurer_reference": event["insurer_reference"],
        "filed_by_user_id": event["filed_by_user_id"],
    }
    data.update(_common(event))
    return data
