"""Derived fields (PRD 2.11) and the wire serialisers for every entity.

Derived values are recomputed rather than stored by hand, so they are correct on
every read without anybody writing to the parent row.
"""

import clockmod
import db

LIVE_OFFERING_STATUSES = ("DRAFT", "OPEN", "EVALUATION", "AWARDED")
LIVE_BID_STATUSES = ("SUBMITTED", "QUALIFIED", "WINNING", "BACKUP")
IN_FLIGHT_APPRAISAL_STATUSES = ("ORDERED", "REPORTED", "CHALLENGED")


def _inst(record, field):
    raw = record.get("_raw", {}).get(field)
    if raw is not None:
        return raw
    value = record.get(field)
    if value is None:
        return None
    return clockmod.fmt(value)


def _common(record, out):
    out["id"] = record["id"]
    out["created_at"] = clockmod.fmt(record["created_at"])
    out["updated_at"] = clockmod.fmt(record["updated_at"])
    out["version"] = record["version"]
    return out


# --------------------------------------------------------------------------
# Derived counters
# --------------------------------------------------------------------------

def open_title_item_count(parcel_id):
    return len([t for t in db.all_rows("title_items")
                if t["parcel_id"] == parcel_id and t["status"] == "OPEN"])


def parcel_appraisals(parcel_id):
    return [a for a in db.all_rows("appraisals") if a["parcel_id"] == parcel_id]


def accepted_appraisal(parcel_id):
    """The single governing appraisal for the parcel, or None."""
    rows = [a for a in parcel_appraisals(parcel_id) if a["status"] == "ACCEPTED"]
    if not rows:
        return None
    return rows[-1]


def valuation_status(parcel):
    accepted = accepted_appraisal(parcel["id"])
    usable = accepted is not None and clockmod.now() < accepted["expires_on"]
    if usable and not parcel.get("_valuation_forced_stale"):
        return "CURRENT"
    ever = any(a.get("accepted_at") is not None for a in parcel_appraisals(parcel["id"]))
    if ever or parcel.get("_valuation_forced_stale"):
        return "STALE"
    return "UNVALUED"


def disposition_ready(parcel):
    return (parcel["ownership_status"] == "AGENCY_OWNED"
            and valuation_status(parcel) == "CURRENT"
            and open_title_item_count(parcel["id"]) == 0)


def declaration_offers(declaration_id):
    return [o for o in db.all_rows("preference_offers")
            if o["declaration_id"] == declaration_id]


def preference_offer_count(declaration_id):
    return len(declaration_offers(declaration_id))


def unresolved_preference_count(declaration_id):
    count = 0
    for offer in declaration_offers(declaration_id):
        if (offer["negotiation_status"] in ("OPEN", "IN_NEGOTIATION")
                or offer["good_faith_status"] in ("UNREVIEWED", "UNDER_REVIEW")):
            count += 1
    return count


def license_status(appraiser):
    return "ACTIVE" if clockmod.now() < appraiser["license_expires_on"] else "EXPIRED"


def active_engagement_count(appraiser_id):
    return len([a for a in db.all_rows("appraisals")
                if a["appraiser_id"] == appraiser_id
                and a["status"] in IN_FLIGHT_APPRAISAL_STATUSES])


def qualified_bid_count(offering_id):
    return len([b for b in db.all_rows("bids")
                if b["offering_id"] == offering_id and b["qualification_status"] == "QUALIFIED"])


def offer_rounds(offer_id):
    rows = [r for r in db.all_rows("negotiation_rounds") if r["offer_id"] == offer_id]
    rows.sort(key=lambda r: r["round_number"])
    return rows


def officer_round_count(offer_id):
    return len([r for r in offer_rounds(offer_id) if r["party"] == "CUSTODIAN_AGENCY"])


def entity_round_count(offer_id):
    return len([r for r in offer_rounds(offer_id) if r["party"] == "PREFERENCE_ENTITY"])


def timely_response_count(offer_id):
    return len([r for r in offer_rounds(offer_id)
                if r["party"] == "PREFERENCE_ENTITY" and r.get("is_timely") is True])


def allocated_proceeds_cents(conveyance_id):
    return sum(a["amount_cents"] for a in db.all_rows("proceeds_allocations")
               if a.get("conveyance_id") == conveyance_id and a["status"] == "POSTED")


def cured_cost_total(parcel_id):
    """Sum of actual_cure_cost_cents over CURED title items only (PRD 3.2)."""
    total = 0
    for item in db.all_rows("title_items"):
        if item["parcel_id"] == parcel_id and item["status"] == "CURED":
            total += item.get("actual_cure_cost_cents") or 0
    return total


def reserved_easement_count(parcel_id):
    return len([t for t in db.all_rows("title_items")
                if t["parcel_id"] == parcel_id and t["status"] == "RESERVED_AS_EASEMENT"])


# --------------------------------------------------------------------------
# Serialisers
# --------------------------------------------------------------------------

def agency_out(row):
    out = {
        "name": row["name"],
        "agency_type": row["agency_type"],
        "is_preference_entity": row["is_preference_entity"],
        "preference_category": row["preference_category"],
        "contact_email": row["contact_email"],
        "notice_registry_status": row["notice_registry_status"],
    }
    return _common(row, out)


def parcel_out(row):
    out = {
        "apn": row["apn"],
        "address": row["address"],
        "acreage": row["acreage"],
        "zoning_code": row["zoning_code"],
        "book_value_cents": row["book_value_cents"],
        "custodian_agency_id": row["custodian_agency_id"],
        "ownership_status": row["ownership_status"],
        "valuation_status": valuation_status(row),
        "open_title_item_count": open_title_item_count(row["id"]),
        "disposition_ready": disposition_ready(row),
    }
    return _common(row, out)


def declaration_out(row):
    out = {
        "parcel_id": row["parcel_id"],
        "justification": row["justification"],
        "intended_use_restriction": row.get("intended_use_restriction"),
        "status": row["status"],
        "resolution_number": row.get("resolution_number"),
        "adopted_by_user_id": row.get("adopted_by_user_id"),
        "adopted_at": _inst(row, "adopted_at"),
        "notice_issued_at": _inst(row, "notice_issued_at"),
        "notice_response_window_days": row.get("notice_response_window_days"),
        "notice_response_deadline_at": _inst(row, "notice_response_deadline_at"),
        "authorized_disposition_type": row.get("authorized_disposition_type"),
        "authority_findings": row.get("authority_findings"),
        "reoffer_count": row["reoffer_count"],
        "reoffer_eligible_at": _inst(row, "reoffer_eligible_at"),
        "preference_offer_count": preference_offer_count(row["id"]),
        "unresolved_preference_count": unresolved_preference_count(row["id"]),
        "withdrawn_reason": row.get("withdrawn_reason"),
    }
    return _common(row, out)


def notice_out(row):
    out = {
        "declaration_id": row["declaration_id"],
        "recipient_agency_id": row["recipient_agency_id"],
        "notice_round": row["notice_round"],
        "issued_at": _inst(row, "issued_at"),
        "response_window_days": row["response_window_days"],
        "response_deadline_at": _inst(row, "response_deadline_at"),
        "status": row["status"],
        "responded_at": _inst(row, "responded_at"),
        "response_type": row.get("response_type"),
        "claimed_preference_category": row.get("claimed_preference_category"),
        "intended_use": row.get("intended_use"),
    }
    return _common(row, out)


def offer_out(row):
    out = {
        "declaration_id": row["declaration_id"],
        "notice_id": row["notice_id"],
        "offeror_agency_id": row["offeror_agency_id"],
        "preference_category": row["preference_category"],
        "negotiation_status": row["negotiation_status"],
        "good_faith_status": row["good_faith_status"],
        "negotiation_opened_at": _inst(row, "negotiation_opened_at"),
        "negotiation_deadline_at": _inst(row, "negotiation_deadline_at"),
        "ah_minimum_price_cents": row.get("ah_minimum_price_cents"),
        "agreed_price_cents": row.get("agreed_price_cents"),
        "officer_round_count": officer_round_count(row["id"]),
        "entity_round_count": entity_round_count(row["id"]),
        "timely_response_count": timely_response_count(row["id"]),
        "interim_good_faith_score": row.get("interim_good_faith_score"),
        "final_good_faith_score": row.get("final_good_faith_score"),
        "remediation_note": row.get("remediation_note"),
    }
    return _common(row, out)


def round_out(row):
    return {
        "id": row["id"],
        "offer_id": row["offer_id"],
        "round_number": row["round_number"],
        "party": row["party"],
        "price_offered_cents": row["price_offered_cents"],
        "terms_summary": row.get("terms_summary"),
        "responded_to_round_number": row.get("responded_to_round_number"),
        "responded_within_days": row.get("responded_within_days"),
        "is_timely": row.get("is_timely"),
        "created_at": clockmod.fmt(row["created_at"]),
    }


def appraiser_out(row):
    out = {
        "name": row["name"],
        "license_number": row["license_number"],
        "license_expires_on": _inst(row, "license_expires_on"),
        "license_status": license_status(row),
        "active_engagement_count": active_engagement_count(row["id"]),
    }
    return _common(row, out)


def appraisal_out(row):
    out = {
        "parcel_id": row["parcel_id"],
        "appraiser_id": row["appraiser_id"],
        "method": row["method"],
        "engagement_start_on": _inst(row, "engagement_start_on"),
        "engagement_end_on": _inst(row, "engagement_end_on"),
        "status": row["status"],
        "appraised_value_cents": row.get("appraised_value_cents"),
        "effective_date": _inst(row, "effective_date"),
        "narrative": row.get("narrative"),
        "reported_at": _inst(row, "reported_at"),
        "expires_on": _inst(row, "expires_on"),
        "challenge_count": row["challenge_count"],
        "revaluation_required": row["revaluation_required"],
        "accepted_at": _inst(row, "accepted_at"),
    }
    return _common(row, out)


def challenge_out(row):
    out = {
        "appraisal_id": row["appraisal_id"],
        "challenger_agency_id": row["challenger_agency_id"],
        "asserted_value_cents": row["asserted_value_cents"],
        "grounds": row.get("grounds"),
        "required_deposit_cents": row["required_deposit_cents"],
        "deposit_paid_cents": row["deposit_paid_cents"],
        "status": row["status"],
        "determined_by_user_id": row.get("determined_by_user_id"),
        "revised_value_cents": row.get("revised_value_cents"),
        "deposit_refunded_cents": row["deposit_refunded_cents"],
        "deposit_forfeited_cents": row["deposit_forfeited_cents"],
    }
    return _common(row, out)


def env_review_out(row):
    out = {
        "declaration_id": row["declaration_id"],
        "determination_class": row["determination_class"],
        "circulation_start_on": _inst(row, "circulation_start_on"),
        "circulation_end_on": _inst(row, "circulation_end_on"),
        "circulation_round": row["circulation_round"],
        "status": row["status"],
        "certified_at": _inst(row, "certified_at"),
        "recirculation_reason": row.get("recirculation_reason"),
    }
    return _common(row, out)


def title_item_out(row):
    out = {
        "parcel_id": row["parcel_id"],
        "item_type": row["item_type"],
        "description": row.get("description"),
        "cure_cost_estimate_cents": row["cure_cost_estimate_cents"],
        "status": row["status"],
        "actual_cure_cost_cents": row.get("actual_cure_cost_cents"),
        "easement_purpose": row.get("easement_purpose"),
        "easement_area_sqft": row.get("easement_area_sqft"),
        "resolved_at": _inst(row, "resolved_at"),
    }
    return _common(row, out)


def offering_out(row):
    out = {
        "declaration_id": row["declaration_id"],
        "offering_type": row["offering_type"],
        "counterparty_bidder_id": row.get("counterparty_bidder_id"),
        "counterparty_agency_id": row.get("counterparty_agency_id"),
        "bid_open_at": _inst(row, "bid_open_at"),
        "bid_close_at": _inst(row, "bid_close_at"),
        "minimum_price_cents": row["minimum_price_cents"],
        "minimum_price_variant": row["minimum_price_variant"],
        "required_deposit_cents": row["required_deposit_cents"],
        "status": row["status"],
        "qualified_bid_count": qualified_bid_count(row["id"]),
        "winning_bid_amount_cents": row.get("winning_bid_amount_cents"),
        "awarded_at": _inst(row, "awarded_at"),
        "awarded_by_user_id": row.get("awarded_by_user_id"),
        "rescind_count": row["rescind_count"],
        "cancellation_reason": row.get("cancellation_reason"),
    }
    return _common(row, out)


def bidder_out(row):
    out = {
        "legal_name": row["legal_name"],
        "entity_type": row["entity_type"],
        "contact_email": row["contact_email"],
        "debarment_status": row["debarment_status"],
        "debarment_reason": row.get("debarment_reason"),
        "available_funds_cents": row["available_funds_cents"],
        "escrow_held_cents": row["escrow_held_cents"],
        "lifetime_deposits_cents": row["lifetime_deposits_cents"],
    }
    return _common(row, out)


def bid_out(row):
    out = {
        "offering_id": row["offering_id"],
        "bidder_id": row["bidder_id"],
        "amount_cents": row["amount_cents"],
        "deposit_amount_cents": row["deposit_amount_cents"],
        "intended_use": row.get("intended_use"),
        "submitted_at": _inst(row, "submitted_at"),
        "qualification_status": row["qualification_status"],
        "deposit_status": row["deposit_status"],
        "award_rank": row.get("award_rank"),
        "disqualification_reason": row.get("disqualification_reason"),
    }
    return _common(row, out)


def conveyance_out(row):
    out = {
        "offering_id": row["offering_id"],
        "parcel_id": row["parcel_id"],
        "grantee_kind": row["grantee_kind"],
        "grantee_bidder_id": row.get("grantee_bidder_id"),
        "grantee_agency_id": row.get("grantee_agency_id"),
        "sale_price_cents": row["sale_price_cents"],
        "closing_costs_cents": row["closing_costs_cents"],
        "broker_fee_cents": row["broker_fee_cents"],
        "recoverable_curative_cost_cents": row["recoverable_curative_cost_cents"],
        "net_proceeds_cents": row["net_proceeds_cents"],
        "deed_restrictions": list(row["deed_restrictions"]),
        "reverter_condition": row.get("reverter_condition"),
        "reverter_cure_period_days": row["reverter_cure_period_days"],
        "recording_status": row["recording_status"],
        "compliance_status": row["compliance_status"],
        "recorded_instrument_number": row.get("recorded_instrument_number"),
        "recorded_at": _inst(row, "recorded_at"),
        "violation_noticed_at": _inst(row, "violation_noticed_at"),
        "cure_deadline_at": _inst(row, "cure_deadline_at"),
        "violation_description": row.get("violation_description"),
        "cure_note": row.get("cure_note"),
        "reverted_at": _inst(row, "reverted_at"),
        "allocated_proceeds_cents": allocated_proceeds_cents(row["id"]),
    }
    return _common(row, out)


def fund_out(row):
    out = {
        "name": row["name"],
        "fund_code": row["fund_code"],
        "priority_rank": row["priority_rank"],
        "allocation_pct": row["allocation_pct"],
        "fixed_reserve_cents": row["fixed_reserve_cents"],
        "balance_cents": row["balance_cents"],
        "lifetime_credits_cents": row["lifetime_credits_cents"],
        "lifetime_debits_cents": row["lifetime_debits_cents"],
    }
    return _common(row, out)


def allocation_out(row):
    return {
        "id": row["id"],
        "conveyance_id": row.get("conveyance_id"),
        "fund_id": row["fund_id"],
        "amount_cents": row["amount_cents"],
        "allocation_basis": row["allocation_basis"],
        "residual_included_cents": row["residual_included_cents"],
        "status": row["status"],
        "reversed_at": _inst(row, "reversed_at"),
        "created_at": clockmod.fmt(row["created_at"]),
    }
