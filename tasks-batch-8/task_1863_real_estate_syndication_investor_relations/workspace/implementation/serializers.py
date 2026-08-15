"""Entity -> wire dict. Internal fields (leading '_') never leak."""
from db import db
from services import domain


def _lifecycle(o):
    return {
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_syndication(o):
    d = {
        "id": o["id"],
        "syndication_name": o["syndication_name"],
        "sponsor_legal_entity": o["sponsor_legal_entity"],
        "preferred_return_pct_annual": o["preferred_return_pct_annual"],
        "carried_interest_pct": o["carried_interest_pct"],
        "status": o["status"],
    }
    d.update(_lifecycle(o))
    return d


def ser_investor(o):
    d = {
        "id": o["id"],
        "full_legal_name": o["full_legal_name"],
        "tax_id_last4": o["tax_id_last4"],
        "email": o["email"],
        "investor_class": o["investor_class"],
        "portal_access_status": o["portal_access_status"],
        "accreditation_expires_on": o["accreditation_expires_on"],
    }
    d.update(_lifecycle(o))
    return d


def ser_property(o):
    d = {
        "id": o["id"],
        "property_legal_name": o["property_legal_name"],
        "street_address": o["street_address"],
        "acquisition_price_cents": o["acquisition_price_cents"],
        "status": o["status"],
    }
    d.update(_lifecycle(o))
    return d


def ser_offering(o):
    d = {
        "id": o["id"],
        "syndication_id": o["syndication_id"],
        "property_id": o["property_id"],
        "offering_name": o["offering_name"],
        "target_raise_cents": o["target_raise_cents"],
        "min_subscription_cents": o["min_subscription_cents"],
        "max_non_accredited_count": o["max_non_accredited_count"],
        "preferred_return_pct_annual": o["preferred_return_pct_annual"],
        "carried_interest_pct": o["carried_interest_pct"],
        "total_committed_cents": domain.offering_total_committed(o["id"]),
        "total_funded_cents": domain.offering_total_funded(o["id"]),
        "total_distributed_cents": o["total_distributed_cents"],
        "unreturned_capital_cents": domain.offering_unreturned_capital(o["id"]),
        "status": o["status"],
    }
    d.update(_lifecycle(o))
    return d


def ser_subscription(o):
    offering = db["offerings"].get(o["offering_id"])
    total_funded = domain.offering_total_funded(o["offering_id"])
    d = {
        "id": o["id"],
        "offering_id": o["offering_id"],
        "investor_id": o["investor_id"],
        "committed_cents": o["committed_cents"],
        "funded_cents": o["funded_cents"],
        "unreturned_capital_cents": o["unreturned_capital_cents"],
        "accrued_pref_cents": domain.current_accrued_pref(o, offering),
        "ownership_pct": (o["funded_cents"] / total_funded) if total_funded else 0,
        "suitability_verified_by": o["suitability_verified_by"],
        "accreditation_verified_by": o["accreditation_verified_by"],
        "accreditation_verified_at": o["accreditation_verified_at"],
        "funded_at": o["funded_at"],
        "status": o["status"],
    }
    d.update(_lifecycle(o))
    return d


def ser_document(o):
    return {
        "id": o["id"],
        "subscription_id": o["subscription_id"],
        "doc_type": o["doc_type"],
        "file_uri": o["file_uri"],
        "received_at": o["received_at"],
        "review_status": o["review_status"],
        "reviewed_by": o["reviewed_by"],
        "created_at": o["created_at"],
    }


def ser_capital_call(o):
    d = {
        "id": o["id"],
        "offering_id": o["offering_id"],
        "call_index": o["call_index"],
        "total_call_cents": o["total_call_cents"],
        "due_date": o["due_date"],
        "escrow_released_cents": o["escrow_released_cents"],
        "status": o["status"],
    }
    d.update(_lifecycle(o))
    return d


def ser_contribution(o):
    d = {
        "id": o["id"],
        "capital_call_id": o["capital_call_id"],
        "subscription_id": o["subscription_id"],
        "amount_due_cents": o["amount_due_cents"],
        "amount_received_cents": o["amount_received_cents"],
        "received_at": o["received_at"],
        "status": o["status"],
    }
    d.update(_lifecycle(o))
    return d


def ser_quarterly_report(o):
    d = {
        "id": o["id"],
        "offering_id": o["offering_id"],
        "report_year": o["report_year"],
        "report_quarter": o["report_quarter"],
        "noi_cents": o["noi_cents"],
        "occupancy_pct": o["occupancy_pct"],
        "distributable_cash_cents": o["distributable_cash_cents"],
        "status": o["status"],
        "published_at": o["published_at"],
    }
    d.update(_lifecycle(o))
    return d


def ser_distribution(o):
    d = {
        "id": o["id"],
        "offering_id": o["offering_id"],
        "quarterly_report_id": o["quarterly_report_id"],
        "capital_event_id": o["capital_event_id"],
        "distribution_kind": o["distribution_kind"],
        "total_distributable_cents": o["total_distributable_cents"],
        "status": o["status"],
        "calculated_at": o["calculated_at"],
    }
    d.update(_lifecycle(o))
    return d


def ser_distribution_line(o):
    return {
        "id": o["id"],
        "distribution_id": o["distribution_id"],
        "subscription_id": o["subscription_id"],
        "return_of_capital_cents": o["return_of_capital_cents"],
        "preferred_return_cents": o["preferred_return_cents"],
        "profit_split_lp_cents": o["profit_split_lp_cents"],
        "profit_split_gp_cents": o["profit_split_gp_cents"],
        "total_cents": o["total_cents"],
        "paid_at": o["paid_at"],
        "created_at": o["created_at"],
    }


def ser_capital_event(o):
    d = {
        "id": o["id"],
        "property_id": o["property_id"],
        "event_kind": o["event_kind"],
        "gross_proceeds_cents": o["gross_proceeds_cents"],
        "debt_payoff_cents": o["debt_payoff_cents"],
        "net_distributable_cents": o["net_distributable_cents"],
        "status": o["status"],
        "executed_at": o["executed_at"],
    }
    d.update(_lifecycle(o))
    return d


def ser_k1_package(o):
    d = {
        "id": o["id"],
        "offering_id": o["offering_id"],
        "tax_year": o["tax_year"],
        "preparer_firm": o["preparer_firm"],
        "draft_k1_cents_by_subscription": o["draft_k1_cents_by_subscription"],
        "final_k1_cents_by_subscription": o["final_k1_cents_by_subscription"],
        "status": o["status"],
    }
    d.update(_lifecycle(o))
    return d


def ser_transfer_request(o):
    d = {
        "id": o["id"],
        "from_subscription_id": o["from_subscription_id"],
        "to_investor_id": o["to_investor_id"],
        "transfer_cents": o["transfer_cents"],
        "status": o["status"],
        "settled_at": o["settled_at"],
    }
    d.update(_lifecycle(o))
    return d


def ser_portal_session(o):
    return {
        "id": o["id"],
        "investor_id": o["investor_id"],
        "session_token": o["session_token"],
        "issued_at": o["issued_at"],
        "expires_at": o["expires_at"],
        "last_accessed_at": o["last_accessed_at"],
    }
