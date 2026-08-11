"""Resource serializers. Every row carries id, created_at, updated_at, version."""

import derive
from timeutil import render_instant as ts


def _base(row, body):
    body["id"] = row["id"]
    body["created_at"] = ts(row["created_at"])
    body["updated_at"] = ts(row["updated_at"])
    body["version"] = row["version"]
    return body


def plan(row):
    return _base(row, {
        "tier": row["tier"],
        "slots_per_box": row["slots_per_box"],
        "swaps_per_cycle": row["swaps_per_cycle"],
        "monthly_fee_cents": row["monthly_fee_cents"],
        "protection_available": row["protection_available"],
        "proration_basis": row["proration_basis"],
        "late_fee_mode": row["late_fee_mode"],
        "capsule_quota_per_wave": row["capsule_quota_per_wave"],
        "discount_pct": row["discount_pct"],
        "status": row["status"],
    })


def member(row):
    mid = row["id"]
    lifetime = derive.pause_days_used_lifetime(mid)
    return _base(row, {
        "plan_id": row["plan_id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "child_size_code": row["child_size_code"],
        "size_effective_at": ts(row["size_effective_at"]),
        "status": row["status"],
        "protection_enrolled": row["protection_enrolled"],
        "auto_apply_credit": row["auto_apply_credit"],
        "credit_balance_cents": derive.member_credit_balance(mid),
        "outstanding_balance_cents": derive.member_outstanding_balance(mid),
        "permanent_slots_consumed": row["permanent_slots_consumed"],
        "pause_days_used_period": derive.pause_days_used_period(mid),
        "pause_days_used_lifetime": lifetime,
        "completed_cycles": derive.completed_cycles(mid),
        "total_paused_days": lifetime,
    })


def cycle(row):
    cid = row["id"]
    return _base(row, {
        "member_id": row["member_id"],
        "cycle_index": row["cycle_index"],
        "start_at": ts(row["start_at"]),
        "swap_by_at": ts(row["swap_by_at"]),
        "return_due_at": ts(row["return_due_at"]),
        "grace_ends_at": ts(row["grace_ends_at"]),
        "status": row["status"],
        "swaps_used": derive.cycle_swaps_used(cid),
        "slots_occupied": derive.cycle_slots_occupied(cid),
        "paused_days": derive.cycle_paused_days(row),
        "plan_charge_cents": row["plan_charge_cents"],
        "proration_credit_cents": row["proration_credit_cents"],
        "discount_cents": row["discount_cents"],
        "protection_fee_cents": row["protection_fee_cents"],
        "protection_waiver_used_cents": row["protection_waiver_used_cents"],
        "late_fee_cents": row["late_fee_cents"],
        "damage_fee_cents": derive.cycle_damage_fee(cid),
        "credit_applied_cents": derive.cycle_credit_applied(cid),
        "surcharge_cents": row["surcharge_cents"],
        "invoice_total_cents": row["invoice_total_cents"],
    })


def style(row):
    return _base(row, {
        "sku": row["sku"],
        "name": row["name"],
        "brand_tier": row["brand_tier"],
        "retail_price_cents": row["retail_price_cents"],
        "size_code": row["size_code"],
        "season": row["season"],
        "category": row["category"],
        "demand_band": row["demand_band"],
        "units_ever_acquired": row["units_ever_acquired"],
        "status": row["status"],
    })


def unit(row):
    return _base(row, {
        "style_id": row["style_id"],
        "capsule_id": row["capsule_id"],
        "state": row["state"],
        "acquisition_source": row["acquisition_source"],
        "acquired_at": ts(row["acquired_at"]),
        "cycles_completed": row["cycles_completed"],
        "cumulative_cleaning_cost_cents": row["cumulative_cleaning_cost_cents"],
        "current_grade": row["current_grade"],
        "retired_reason": row["retired_reason"],
        "retirement_eligible": row["retirement_eligible"],
    })


def box(row):
    return _base(row, {
        "cycle_id": row["cycle_id"],
        "member_id": row["member_id"],
        "outbound_shipment_id": row["outbound_shipment_id"],
        "status": row["status"],
        "slot_capacity": row["slot_capacity"],
        "slots_free": derive.box_slots_free(row),
    })


def box_item(row):
    return _base(row, {
        "box_id": row["box_id"],
        "unit_id": row["unit_id"],
        "return_shipment_id": row["return_shipment_id"],
        "fulfillment_status": row["fulfillment_status"],
        "settlement_status": row["settlement_status"],
        "slot_index": row["slot_index"],
        "is_capsule_item": row["is_capsule_item"],
        "embargo_until": ts(row["embargo_until"]),
        "days_late": row["days_late"],
        "late_fee_cents": row["late_fee_cents"],
        "damage_fee_cents": row["damage_fee_cents"],
        "assessed_grade": row["assessed_grade"],
    })


def swap_request(row):
    return _base(row, {
        "cycle_id": row["cycle_id"],
        "member_id": row["member_id"],
        "status": row["status"],
        "return_box_item_ids": list(row["return_box_item_ids"]),
        "requested_style_ids": list(row["requested_style_ids"]),
        "allocated_unit_ids": list(row["allocated_unit_ids"]),
        "slot_delta": row["slot_delta"],
        "rejection_reason": row["rejection_reason"],
    })


def shipment(row):
    return _base(row, {
        "member_id": row["member_id"],
        "label_id": row["label_id"],
        "direction": row["direction"],
        "status": row["status"],
        "item_count": row["item_count"],
        "shipped_at": ts(row["shipped_at"]),
        "delivered_at": ts(row["delivered_at"]),
        "ever_scanned": row["ever_scanned"],
    })


def label(row):
    return _base(row, {
        "member_id": row["member_id"],
        "replaces_label_id": row["replaces_label_id"],
        "direction": row["direction"],
        "status": row["status"],
        "issued_at": ts(row["issued_at"]),
        "expires_at": ts(row["expires_at"]),
        "reissue_count": row["reissue_count"],
        "tracking_code": row["tracking_code"],
    })


def assessment(row):
    return _base(row, {
        "unit_id": row["unit_id"],
        "trade_in_item_id": row["trade_in_item_id"],
        "pipeline": row["pipeline"],
        "status": row["status"],
        "grade": row["grade"],
        "defect_codes": list(row["defect_codes"]),
        "regrade_count": row["regrade_count"],
        "graded_by_user_id": row["graded_by_user_id"],
        "confirmed_by_user_id": row["confirmed_by_user_id"],
        "dispute_reason": row["dispute_reason"],
    })


def job(row):
    return _base(row, {
        "assessment_id": row["assessment_id"],
        "unit_id": row["unit_id"],
        "route": row["route"],
        "status": row["status"],
        "attempt_count": row["attempt_count"],
        "cost_cents": row["cost_cents"],
        "post_repair_grade": row["post_repair_grade"],
    })


def submission(row):
    return _base(row, {
        "member_id": row["member_id"],
        "inbound_shipment_id": row["inbound_shipment_id"],
        "status": row["status"],
        "declared_item_count": row["declared_item_count"],
        "credited_total_cents": row["credited_total_cents"],
        "uncapped_total_cents": row["uncapped_total_cents"],
        "election_deadline_at": ts(row["election_deadline_at"]),
    })


def trade_in_item(row):
    return _base(row, {
        "submission_id": row["submission_id"],
        "absorbed_unit_id": row["absorbed_unit_id"],
        "declared_brand_tier": row["declared_brand_tier"],
        "declared_size_code": row["declared_size_code"],
        "grading_status": row["grading_status"],
        "disposition_status": row["disposition_status"],
        "assessed_grade": row["assessed_grade"],
        "demand_band": row["demand_band"],
        "credit_cents": row["credit_cents"],
        "granted_credit_cents": row["granted_credit_cents"],
    })


def credit_entry(row):
    return _base(row, {
        "member_id": row["member_id"],
        "source_submission_id": row["source_submission_id"],
        "amount_cents": row["amount_cents"],
        "remaining_cents": row["remaining_cents"],
        "status": row["status"],
        "granted_at": ts(row["granted_at"]),
        "expires_at": ts(row["expires_at"]),
        "paused_days_extension": row["paused_days_extension"],
        "revoke_reason": row["revoke_reason"],
    })


def charge_entry(row):
    return _base(row, {
        "member_id": row["member_id"],
        "cycle_id": row["cycle_id"],
        "charge_type": row["charge_type"],
        "amount_cents": row["amount_cents"],
        "credit_applied_cents": row["credit_applied_cents"],
        "net_due_cents": row["net_due_cents"],
        "status": row["status"],
        "waive_reason": row["waive_reason"],
    })


def buyout_order(row):
    return _base(row, {
        "box_item_id": row["box_item_id"],
        "member_id": row["member_id"],
        "status": row["status"],
        "quote_variant": row["quote_variant"],
        "quoted_price_cents": row["quoted_price_cents"],
        "late_surcharge_cents": row["late_surcharge_cents"],
        "final_price_cents": row["final_price_cents"],
        "quoted_at": ts(row["quoted_at"]),
        "quote_expires_at": ts(row["quote_expires_at"]),
    })


def capsule(row):
    return _base(row, {
        "season": row["season"],
        "name": row["name"],
        "release_at": ts(row["release_at"]),
        "close_at": ts(row["close_at"]),
        "embargo_until": ts(row["embargo_until"]),
        "status": row["status"],
        "quota_per_member": row["quota_per_member"],
    })


def capsule_allocation(row):
    return _base(row, {
        "capsule_id": row["capsule_id"],
        "member_id": row["member_id"],
        "units_allocated": row["units_allocated"],
        "status": row["status"],
    })


def pause_request(row):
    return _base(row, {
        "member_id": row["member_id"],
        "status": row["status"],
        "start_at": ts(row["start_at"]),
        "days_requested": row["days_requested"],
        "end_at": ts(row["end_at"]),
        "proration_credit_cents": row["proration_credit_cents"],
        "denial_reason": row["denial_reason"],
    })


def claim(row):
    return _base(row, {
        "shipment_id": row["shipment_id"],
        "member_id": row["member_id"],
        "status": row["status"],
        "variant": row["variant"],
        "assessed_value_cents": row["assessed_value_cents"],
        "member_liability_pct": row["member_liability_pct"],
        "member_liability_cents": row["member_liability_cents"],
        "filed_at": ts(row["filed_at"]),
        "deadline_at": ts(row["deadline_at"]),
        "info_note": row["info_note"],
        "denial_reason": row["denial_reason"],
    })


SERIALIZERS = {
    "plans": plan,
    "members": member,
    "cycles": cycle,
    "styles": style,
    "units": unit,
    "boxes": box,
    "box_items": box_item,
    "swap_requests": swap_request,
    "shipments": shipment,
    "labels": label,
    "assessments": assessment,
    "jobs": job,
    "submissions": submission,
    "trade_in_items": trade_in_item,
    "credit_entries": credit_entry,
    "charge_entries": charge_entry,
    "buyout_orders": buyout_order,
    "capsules": capsule,
    "capsule_allocations": capsule_allocation,
    "pause_requests": pause_request,
    "claims": claim,
}


def of(table):
    return SERIALIZERS[table]
