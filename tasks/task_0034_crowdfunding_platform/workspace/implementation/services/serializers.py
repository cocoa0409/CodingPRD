"""Serialize internal entity dicts into the API JSON shape."""

from db import iso


def _common_fields(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def _appendonly_fields(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec["created_at"]),
    }


def initiator_view(rec):
    return {
        **_common_fields(rec),
        "legal_name": rec.get("legal_name"),
        "kyc_status": rec.get("kyc_status"),
        "tax_id": rec.get("tax_id"),
        "bank_account_id": rec.get("bank_account_id"),
        "qualification_doc_uri": rec.get("qualification_doc_uri"),
    }


def backer_view(rec):
    return {
        **_common_fields(rec),
        "display_name": rec.get("display_name"),
        "email": rec.get("email"),
        "default_shipping_address": rec.get("default_shipping_address"),
    }


def project_view(rec):
    return {
        **_common_fields(rec),
        "initiator_id": rec.get("initiator_id"),
        "title": rec.get("title"),
        "category": rec.get("category"),
        "description_md": rec.get("description_md"),
        "media_uris": rec.get("media_uris", []),
        "risk_disclosure": rec.get("risk_disclosure"),
        "funding_model": rec.get("funding_model"),
        "funding_target_cents": rec.get("funding_target_cents"),
        "deadline": iso(rec.get("deadline")),
        "status": rec.get("status"),
        "provisional_raised_cents": rec.get("provisional_raised_cents", 0),
        "final_raised_cents": rec.get("final_raised_cents", 0),
        "rejection_reason": rec.get("rejection_reason"),
        "last_update_published_at": iso(rec.get("last_update_published_at")),
    }


def reward_view(rec):
    return {
        **_common_fields(rec),
        "project_id": rec.get("project_id"),
        "tier_label": rec.get("tier_label"),
        "pledge_amount_cents": rec.get("pledge_amount_cents"),
        "reward_type": rec.get("reward_type"),
        "inventory_limit": rec.get("inventory_limit"),
        "inventory_claimed": rec.get("inventory_claimed", 0),
        "estimated_delivery": iso(rec.get("estimated_delivery")),
    }


def addon_view(rec):
    return {
        **_common_fields(rec),
        "project_id": rec.get("project_id"),
        "name": rec.get("name"),
        "price_cents": rec.get("price_cents"),
        "requires_shipping": rec.get("requires_shipping", False),
        "inventory_limit": rec.get("inventory_limit"),
        "inventory_claimed": rec.get("inventory_claimed", 0),
    }


def order_view(rec):
    return {
        **_common_fields(rec),
        "project_id": rec.get("project_id"),
        "backer_id": rec.get("backer_id"),
        "reward_id": rec.get("reward_id"),
        "add_ons": rec.get("add_ons", []),
        "shipping_address": rec.get("shipping_address"),
        "payment_method_token": rec.get("payment_method_token"),
        "pledge_amount_cents": rec.get("pledge_amount_cents", 0),
        "add_ons_total_cents": rec.get("add_ons_total_cents", 0),
        "order_total_cents": rec.get("order_total_cents", 0),
        "payment_status": rec.get("payment_status"),
        "fulfillment_status": rec.get("fulfillment_status"),
        "charge_attempts": rec.get("charge_attempts", 0),
        "order_modification_locked_at": iso(rec.get("order_modification_locked_at")),
        "refundable_remainder_cents": rec.get("refundable_remainder_cents", 0),
    }


def progress_update_view(rec):
    return {
        **_appendonly_fields(rec),
        "project_id": rec.get("project_id"),
        "title": rec.get("title"),
        "body_md": rec.get("body_md"),
        "visibility": rec.get("visibility"),
        "milestone_label": rec.get("milestone_label"),
        "is_delay_notice": rec.get("is_delay_notice", False),
    }


def refund_view(rec):
    return {
        **_common_fields(rec),
        "order_id": rec.get("order_id"),
        "reason": rec.get("reason"),
        "requested_amount_cents": rec.get("requested_amount_cents"),
        "status": rec.get("status"),
        "approved_amount_cents": rec.get("approved_amount_cents"),
        "rejection_reason": rec.get("rejection_reason"),
        "triggered_by": rec.get("triggered_by"),
    }


def settlement_view(rec):
    return {
        **_common_fields(rec),
        "project_id": rec.get("project_id"),
        "period_start": iso(rec.get("period_start")),
        "period_end": iso(rec.get("period_end")),
        "gross_charged_cents": rec.get("gross_charged_cents", 0),
        "commission_cents": rec.get("commission_cents", 0),
        "channel_fee_cents": rec.get("channel_fee_cents", 0),
        "refund_reversal_cents": rec.get("refund_reversal_cents", 0),
        "tax_withheld_cents": rec.get("tax_withheld_cents", 0),
        "net_payout_cents": rec.get("net_payout_cents", 0),
        "status": rec.get("status"),
    }


def audit_view(rec):
    return {
        **_appendonly_fields(rec),
        "subject_type": rec.get("subject_type"),
        "subject_id": rec.get("subject_id"),
        "event_type": rec.get("event_type"),
        "payload": rec.get("payload", {}),
        "actor_role": rec.get("actor_role"),
        "actor_id": rec.get("actor_id"),
    }


def escrow_view(rec):
    return {
        **_appendonly_fields(rec),
        "project_id": rec.get("project_id"),
        "order_id": rec.get("order_id"),
        "entry_type": rec.get("entry_type"),
        "amount_cents": rec.get("amount_cents"),
        "external_ref": rec.get("external_ref"),
    }
