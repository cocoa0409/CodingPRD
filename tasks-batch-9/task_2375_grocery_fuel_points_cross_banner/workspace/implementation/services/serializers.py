"""Entity -> JSON projections. Computed fields are derived at read time."""
from decimal import Decimal

import clock
import db
from services import core

def _common(entity, payload):
    payload["id"] = entity["id"]
    payload["created_at"] = clock.fmt(entity["created_at"])
    payload["updated_at"] = clock.fmt(entity["updated_at"])
    payload["version"] = entity["version"]
    return payload


def banner(entity):
    out = {
        "banner_code": entity["banner_code"],
        "name": entity["name"],
        "status": entity["status"],
        "base_points_per_dollar": entity["base_points_per_dollar"],
        "gift_card_multiplier": entity["gift_card_multiplier"],
        "pharmacy_multiplier": entity["pharmacy_multiplier"],
        "pharmacy_points_per_script": entity["pharmacy_points_per_script"],
        "max_stacked_multiplier": entity["max_stacked_multiplier"],
        "max_stack_count": entity["max_stack_count"],
        "points_per_discount_block": entity["points_per_discount_block"],
        "cents_off_per_block": entity["cents_off_per_block"],
        "max_cents_off_per_gallon": entity["max_cents_off_per_gallon"],
        "owned_max_gallons_per_redemption": entity["owned_max_gallons_per_redemption"],
        "min_points_per_redemption": entity["min_points_per_redemption"],
        "rollover_cap_points": entity["rollover_cap_points"],
        "max_transfers_per_cycle": entity["max_transfers_per_cycle"],
        "expiry_basis": entity["expiry_basis"],
        "fraud_scoring_mode": entity["fraud_scoring_mode"],
        "freeze_threshold_score": entity["freeze_threshold_score"],
    }
    return _common(entity, out)


def site(entity):
    unbatched_gallons, unbatched_discount_cents = core.site_unbatched(entity["id"])
    out = {
        "banner_id": entity["banner_id"],
        "site_number": entity["site_number"],
        "site_type": entity["site_type"],
        "status": entity["status"],
        "partner_code": entity["partner_code"],
        "per_gallon_cap_cents": entity["per_gallon_cap_cents"],
        "max_gallons_per_redemption": entity["max_gallons_per_redemption"],
        "unbatched_gallons": unbatched_gallons,
        "unbatched_discount_cents": unbatched_discount_cents,
        "settlement_balance_cents": core.site_settlement_balance_cents(entity["id"]),
    }
    return _common(entity, out)


def household(entity):
    out = {
        "banner_id": entity["banner_id"],
        "household_code": entity["household_code"],
        "status": entity["status"],
        "frozen_reason": entity["frozen_reason"],
        "frozen_at": clock.fmt(entity["frozen_at"]),
        "linked_member_count": core.household_linked_member_count(entity["id"]),
        "aggregate_available_points": core.household_aggregate_available_points(entity["id"]),
        "cross_banner_member_ids": core.household_cross_banner_member_ids(entity),
        "fraud_score": core.household_fraud_score(entity),
    }
    return _common(entity, out)


def member(entity):
    out = {
        "banner_id": entity["banner_id"],
        "alt_id": entity["alt_id"],
        "card_number": entity["card_number"],
        "full_name": entity["full_name"],
        "available_points": core.available_points(entity["id"]),
        "lifetime_points": core.lifetime_points(entity["id"]),
    }
    return _common(entity, out)


def household_link(entity):
    out = {
        "household_id": entity["household_id"],
        "member_id": entity["member_id"],
        "link_role": entity["link_role"],
        "status": entity["status"],
        "is_cross_banner": core.link_is_cross_banner(entity),
        "activated_at": clock.fmt(entity["activated_at"]),
        "revoked_at": clock.fmt(entity["revoked_at"]),
    }
    return _common(entity, out)


def promo_event(entity):
    out = {
        "banner_id": entity["banner_id"],
        "promo_code": entity["promo_code"],
        "multiplier": entity["multiplier"],
        "applies_to_categories": list(entity["applies_to_categories"]),
        "starts_at": clock.fmt(entity["starts_at"]),
        "ends_at": clock.fmt(entity["ends_at"]),
        "stack_priority": entity["stack_priority"],
        "status": entity["status"],
    }
    return _common(entity, out)


def point_cycle(entity):
    out = {
        "banner_id": entity["banner_id"],
        "cycle_month": entity["cycle_month"],
        "opens_at": clock.fmt(entity["opens_at"]),
        "closes_at": clock.fmt(entity["closes_at"]),
        "status": entity["status"],
        "expired_points_total": entity["expired_points_total"],
        "rolled_over_points_total": entity["rolled_over_points_total"],
        "swept_member_count": entity["swept_member_count"],
        "closed_at": clock.fmt(entity["closed_at"]),
    }
    return _common(entity, out)


def purchase_transaction(entity):
    out = {
        "member_id": entity["member_id"],
        "site_id": entity["site_id"],
        "transacted_at": clock.fmt(entity["transacted_at"]),
        "lines": [dict(line) for line in entity["lines"]],
        "subtotal_cents": entity["subtotal_cents"],
        "posting_status": entity["posting_status"],
        "accrual_status": entity["accrual_status"],
        "gross_points_awarded": entity["gross_points_awarded"],
        "line_points_breakdown": [dict(row) for row in entity["line_points_breakdown"]],
        "applied_promo_event_ids": list(entity["applied_promo_event_ids"]),
        "posted_at": clock.fmt(entity["posted_at"]),
        "voided_at": clock.fmt(entity["voided_at"]),
    }
    return _common(entity, out)


def ledger_entry(entity):
    return {
        "id": entity["id"],
        "member_id": entity["member_id"],
        "point_cycle_id": entity["point_cycle_id"],
        "entry_type": entity["entry_type"],
        "points_delta": entity["points_delta"],
        "lot_expires_at": clock.fmt(entity["lot_expires_at"]),
        "source_kind": entity["source_kind"],
        "source_ref_id": entity["source_ref_id"],
        "memo": entity["memo"],
        "created_at": clock.fmt(entity["created_at"]),
    }


def fuel_redemption(entity):
    out = {
        "member_id": entity["member_id"],
        "site_id": entity["site_id"],
        "settlement_batch_id": entity["settlement_batch_id"],
        "alt_id_presented": entity["alt_id_presented"],
        "points_committed": entity["points_committed"],
        "blocks_effective": entity["blocks_effective"],
        "cents_off_per_gallon": entity["cents_off_per_gallon"],
        "points_debited_at_auth": entity["points_debited_at_auth"],
        "gallons_authorized": entity["gallons_authorized"],
        "gallons_dispensed": entity["gallons_dispensed"],
        "discount_amount_cents": entity["discount_amount_cents"],
        "authorization_status": entity["authorization_status"],
        "settlement_status": entity["settlement_status"],
        "authorized_at": clock.fmt(entity["authorized_at"]),
        "dispensed_at": clock.fmt(entity["dispensed_at"]),
    }
    return _common(entity, out)


def settlement_batch(entity):
    out = {
        "site_id": entity["site_id"],
        "period_start": clock.fmt(entity["period_start"]),
        "period_end": clock.fmt(entity["period_end"]),
        "status": entity["status"],
        "redemption_count": entity["redemption_count"],
        "gallons_total": entity["gallons_total"],
        "gross_discount_cents": entity["gross_discount_cents"],
        "tier_rate_pct": entity["tier_rate_pct"],
        "pre_fee_reimbursement_cents": entity["pre_fee_reimbursement_cents"],
        "admin_fee_cents": entity["admin_fee_cents"],
        "reimbursement_cents": entity["reimbursement_cents"],
        "submitted_by_user_id": entity["submitted_by_user_id"],
        "approved_by_user_id": entity["approved_by_user_id"],
        "submitted_at": clock.fmt(entity["submitted_at"]),
        "decided_at": clock.fmt(entity["decided_at"]),
    }
    return _common(entity, out)


def point_dispute(entity):
    out = {
        "member_id": entity["member_id"],
        "disputed_ledger_entry_id": entity["disputed_ledger_entry_id"],
        "supersedes_dispute_id": entity["supersedes_dispute_id"],
        "applied_ledger_entry_id": entity["applied_ledger_entry_id"],
        "claimed_points": entity["claimed_points"],
        "reason_code": entity["reason_code"],
        "status": entity["status"],
        "proposed_points_delta": entity["proposed_points_delta"],
        "authority_tier": entity["authority_tier"],
        "proposed_by_user_id": entity["proposed_by_user_id"],
        "approved_by_user_id": entity["approved_by_user_id"],
        "resolved_at": clock.fmt(entity["resolved_at"]),
    }
    return _common(entity, out)


def fraud_signal(entity):
    out = {
        "household_id": entity["household_id"],
        "signal_type": entity["signal_type"],
        "severity_weight": entity["severity_weight"],
        "status": entity["status"],
        "source": entity["source"],
        "detected_at": clock.fmt(entity["detected_at"]),
        "cleared_at": clock.fmt(entity["cleared_at"]),
        "cleared_by_user_id": entity["cleared_by_user_id"],
    }
    return _common(entity, out)
