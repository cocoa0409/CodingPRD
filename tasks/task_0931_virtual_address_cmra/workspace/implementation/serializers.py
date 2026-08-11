"""JSON projections.  Every instant goes through util.render_instant, the single producer."""

import calc
import store
from util import num_out, render_date, render_instant


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = render_instant(row["created_at"])
    if "version" in row:
        out["updated_at"] = render_instant(row["updated_at"])
        out["version"] = row["version"]
    return out


def plan_tier(r):
    return _common(r, {
        "tier_code": r["tier_code"],
        "name": r["name"],
        "rank": r["rank"],
        "monthly_fee_cents": r["monthly_fee_cents"],
        "included_recipients": r["included_recipients"],
        "included_scan_pages": r["included_scan_pages"],
        "included_forwards": r["included_forwards"],
        "included_storage_days": r["included_storage_days"],
        "overage_scan_page_cents": r["overage_scan_page_cents"],
        "overage_forward_cents": r["overage_forward_cents"],
        "overage_storage_day_cents": r["overage_storage_day_cents"],
        "overage_recipient_cents": r["overage_recipient_cents"],
        "allows_overage": r["allows_overage"],
    })


def carrier_rule(r):
    return _common(r, {
        "carrier_code": r["carrier_code"],
        "dim_divisor": r["dim_divisor"],
        "max_length_plus_girth_in": r["max_length_plus_girth_in"],
        "max_actual_weight_lb": r["max_actual_weight_lb"],
        "accepts_signature_required": r["accepts_signature_required"],
        "acceptance_fee_cents": r["acceptance_fee_cents"],
        "base_rate_cents_per_lb": r["base_rate_cents_per_lb"],
    })


def release_gate_state(b):
    """PRD 2.8; evaluated fresh on every read and on every gated write."""
    if b["service_status"] == "SUSPENDED":
        return "GATED_SUSPENDED"
    if b["service_status"] in ("PENDING_SETUP", "CLOSED"):
        return "GATED_LIFECYCLE"
    return "OPEN"


def box(r):
    return _common(r, {
        "box_number": r["box_number"],
        "plan_tier_id": r["plan_tier_id"],
        "pending_plan_tier_id": r["pending_plan_tier_id"],
        "holder_name": r["holder_name"],
        "holder_email": r["holder_email"],
        "security_deposit_cents": r["security_deposit_cents"],
        "extra_recipient_slots": r["extra_recipient_slots"],
        "prepaid_balance_cents": r["prepaid_balance_cents"],
        "service_status": r["service_status"],
        "compliance_status": r["compliance_status"],
        "suspended_reason": r["suspended_reason"],
        "activated_at": render_instant(r["activated_at"]),
        "cycle_anchor_date": render_date(r["cycle_anchor_date"]),
        "outstanding_overage_cents": calc.outstanding_overage(r["id"]),
        "roster_authorized_count": sum(
            1 for x in store.recipients_of_box(r["id"]) if x["roster_status"] == "AUTHORIZED"),
        "release_gate_state": release_gate_state(r),
    })


def recipient(r):
    return _common(r, {
        "box_id": r["box_id"],
        "legal_name": r["legal_name"],
        "recipient_kind": r["recipient_kind"],
        "dba_aliases": list(r["dba_aliases"]),
        "guarantor_recipient_id": r["guarantor_recipient_id"],
        "signature_authorization_on_file": r["signature_authorization_on_file"],
        "roster_status": r["roster_status"],
        "release_eligibility": r["release_eligibility"],
        "blocked_reason": r["blocked_reason"],
        "form_1583_accepted_at": render_instant(r["form_1583_accepted_at"]),
    })


def form1583(r):
    return _common(r, {
        "recipient_id": r["recipient_id"],
        "home_address_line": r["home_address_line"],
        "status": r["status"],
        "notarized_at": render_instant(r["notarized_at"]),
        "notary_user_id": r["notary_user_id"],
        "accepted_on": render_date(r["accepted_on"]),
        "expires_on": render_date(r["expires_on"]),
        "accepted_by_user_id": r["accepted_by_user_id"],
        "rejection_reason": r["rejection_reason"],
    })


def id_document(r):
    # expires_on is CALLER-supplied and echoed back byte-for-byte (PRD 2.4).
    return _common(r, {
        "recipient_id": r["recipient_id"],
        "doc_class": r["doc_class"],
        "doc_type": r["doc_type"],
        "expires_on": r["expires_on"],
        "status": r["status"],
        "verified_at": render_instant(r["verified_at"]),
    })


def mail_item(r):
    free, billable = calc.storage_counters(r)
    return _common(r, {
        "box_id": r["box_id"],
        "addressee_name": r["addressee_name"],
        "matched_recipient_id": r["matched_recipient_id"],
        "item_class": r["item_class"],
        "carrier_rule_id": r["carrier_rule_id"],
        "signature_required": r["signature_required"],
        "actual_weight_lb": r["actual_weight_lb"],
        "length_in": r["length_in"],
        "width_in": r["width_in"],
        "height_in": r["height_in"],
        "received_at": render_instant(r["received_at"]),
        "accepted_at": render_instant(r["accepted_at"]),
        "released_at": render_instant(r["released_at"]),
        "handling_status": r["handling_status"],
        "storage_status": r["storage_status"],
        "billing_status": r["billing_status"],
        "notification_status": r["notification_status"],
        "notification_due_at": render_instant(r["notification_due_at"]),
        "notified_at": render_instant(r["notified_at"]),
        "interior_scan_consent": r["interior_scan_consent"],
        "forward_shipment_id": r["forward_shipment_id"],
        "billable_weight_lb": num_out(r["billable_weight_lb"]),
        "package_acceptance_fee_cents": r["package_acceptance_fee_cents"],
        "free_storage_days_used": free,
        "billable_storage_days": billable,
        "refusal_reason": r["refusal_reason"],
    })


def scan_job(r):
    return _common(r, {
        "mail_item_id": r["mail_item_id"],
        "scan_tier": r["scan_tier"],
        "requested_pages": r["requested_pages"],
        "split_index": r["split_index"],
        "split_group_size": r["split_group_size"],
        "page_count": r["page_count"],
        "status": r["status"],
        "retry_count": r["retry_count"],
        "billed_pages_in_tier": r["billed_pages_in_tier"],
        "billed_pages_overage": r["billed_pages_overage"],
        "charge_cents": r["charge_cents"],
    })


def disposition(r):
    return _common(r, {
        "mail_item_id": r["mail_item_id"],
        "disposition_type": r["disposition_type"],
        "precedence_rank": r["precedence_rank"],
        "status": r["status"],
        "resolution_reason": r["resolution_reason"],
        "executed_at": render_instant(r["executed_at"]),
    })


def forward_shipment(r):
    return _common(r, {
        "box_id": r["box_id"],
        "service_level": r["service_level"],
        "destination_address": r["destination_address"],
        "status": r["status"],
        "item_count": r["item_count"],
        "excluded_item_count": r["excluded_item_count"],
        "total_weight_lb": num_out(r["total_weight_lb"]),
        "base_price_cents": r["base_price_cents"],
        "consolidation_discount_cents": r["consolidation_discount_cents"],
        "total_price_cents": r["total_price_cents"],
        "shipped_at": render_instant(r["shipped_at"]),
    })


def check_deposit(r):
    return _common(r, {
        "mail_item_id": r["mail_item_id"],
        "deposit_batch_id": r["deposit_batch_id"],
        "matched_recipient_id": r["matched_recipient_id"],
        "payee_name_on_check": r["payee_name_on_check"],
        "amount_cents": r["amount_cents"],
        "endorsed": r["endorsed"],
        "match_mode": r["match_mode"],
        "status": r["status"],
        "hold_reason": r["hold_reason"],
    })


def deposit_batch(r):
    checks = store.checks_of_batch(r["id"])
    received = sum(c["amount_cents"] for c in checks)
    deposited = sum(c["amount_cents"] for c in checks if c["status"] == "DEPOSITED")
    returned = sum(c["amount_cents"] for c in checks if c["status"] == "RETURNED")
    held = sum(c["amount_cents"] for c in checks
               if c["status"] in ("RECEIVED", "MATCHED", "HELD"))
    # business_date is CALLER-supplied and echoed back byte-for-byte (PRD 2.4).
    return _common(r, {
        "box_id": r["box_id"],
        "business_date": r["business_date"],
        "closed": r["closed"],
        "closed_at": render_instant(r["closed_at"]),
        "status": "CLOSED" if r["closed"] else "OPEN",
        "check_count": len(checks),
        "received_amount_cents": received,
        "deposited_amount_cents": deposited,
        "returned_amount_cents": returned,
        "held_amount_cents": held,
    })


def registered_agent(r):
    return _common(r, {
        "box_id": r["box_id"],
        "jurisdiction_code": r["jurisdiction_code"],
        "retention_days": r["retention_days"],
        "active": r["active"],
        "deactivated_at": render_instant(r["deactivated_at"]),
        "sop_count": sum(1 for m in store.mail_items_of_box(r["box_id"])
                         if m["item_class"] == "SOP"),
    })


def compliance_review(r):
    return _common(r, {
        "box_id": r["box_id"],
        "reason": r["reason"],
        "status": r["status"],
        "opened_by_user_id": r["opened_by_user_id"],
        "resolved_by_user_id": r["resolved_by_user_id"],
        "resolution": r["resolution"],
        "resolved_at": render_instant(r["resolved_at"]),
    })


def billing_cycle(r):
    return _common(r, {
        "box_id": r["box_id"],
        "cycle_index": r["cycle_index"],
        "period_start": render_date(r["period_start"]),
        "period_end": render_date(r["period_end"]),
        "status": r["status"],
        "plan_tier_id_at_close": r["plan_tier_id_at_close"],
        "scan_pages_consumed": r["scan_pages_consumed"],
        "forwards_consumed": r["forwards_consumed"],
        "storage_days_consumed": r["storage_days_consumed"],
        "recipients_consumed": r["recipients_consumed"],
        "base_fee_cents": r["base_fee_cents"],
        "overage_total_cents": r["overage_total_cents"],
        "proration_charge_cents": r["proration_charge_cents"],
        "proration_credit_cents": r["proration_credit_cents"],
        "loyalty_discount_cents": r["loyalty_discount_cents"],
        "total_charge_cents": r["total_charge_cents"],
    })


def usage_entry(r):
    return _common(r, {
        "billing_cycle_id": r["billing_cycle_id"],
        "mail_item_id": r["mail_item_id"],
        "unit_type": r["unit_type"],
        "tranche": r["tranche"],
        "quantity": r["quantity"],
        "unit_rate_cents": r["unit_rate_cents"],
        "amount_cents": r["amount_cents"],
        "source_event": r["source_event"],
    })


def cancellation(r):
    return _common(r, {
        "box_id": r["box_id"],
        "forwarding_address": r["forwarding_address"],
        "requested_on": render_date(r["requested_on"]),
        "notice_end_date": render_date(r["notice_end_date"]),
        "final_forward_deadline": render_date(r["final_forward_deadline"]),
        "abandonment_date": render_date(r["abandonment_date"]),
        "destruction_eligible_on": render_date(r["destruction_eligible_on"]),
        "status": r["status"],
        "prepaid_at_request_cents": r["prepaid_at_request_cents"],
        "deposit_held_cents": r["deposit_held_cents"],
        "applied_to_overage_cents": r["applied_to_overage_cents"],
        "refund_total_cents": r["refund_total_cents"],
        "forfeited_cents": r["forfeited_cents"],
    })
