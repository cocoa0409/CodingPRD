"""Serialisers: one per entity, emitting exactly the declared field set."""

import calc
import derive
import store
from util import num


def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def client(record):
    out = _common(record)
    out.update({
        "full_name": record["full_name"],
        "phone": record["phone"],
        "email": record["email"],
        "engagement_count": derive.engagement_count(record["id"]),
    })
    return out


def engagement(record):
    out = _common(record)
    out.update({
        "client_id": record["client_id"],
        "status": record["status"],
        "phase": derive.engagement_phase(record),
        "billing_mode": record["billing_mode"],
        "home_tier": record["home_tier"],
        "package_tier": record["package_tier"],
        "scheduled_move_start_utc": record["scheduled_move_start_utc"],
        "move_freeze_at_utc": record["move_freeze_at_utc"],
        "mileage_miles": num(record["mileage_miles"], 2),
        "origin_stairs_flights": record["origin_stairs_flights"],
        "origin_long_carry_feet": record["origin_long_carry_feet"],
        "accrued_labor_cents": derive.accrued_labor_cents(record["id"]),
        "billing_hours_total": num(derive.billing_hours_total(record["id"]), 2),
        "inventory_item_count": derive.inventory_item_count(record["id"]),
        "total_inventory_volume_cft": num(derive.total_inventory_volume_cft(record["id"]), 2),
        "keep_volume_cft": num(derive.keep_volume_cft(record["id"]), 2),
        "haul_volume_cft": num(derive.haul_volume_cft(record["id"]), 2),
        "consignment_credit_cents": derive.consignment_credit_cents(record["id"]),
        "billing_hold": derive.billing_hold(record),
        "hold_reason": record["hold_reason"],
        "hold_count": record["hold_count"],
        "cancel_reason": record["cancel_reason"],
        "closed_at_utc": record["closed_at_utc"],
        "ops_run_seq": record["ops_run_seq"],
    })
    return out


def portal_party(record):
    out = _common(record)
    out.update({
        "engagement_id": record["engagement_id"],
        "client_id": record["client_id"],
        "party_type": record["party_type"],
        "display_name": record["display_name"],
        "email": record["email"],
        "can_approve_dispositions": derive.party_can_approve_dispositions(record["id"]),
        "active_authority_ceiling_cents": derive.party_active_ceiling(record["id"]),
    })
    return out


def authority_record(record):
    out = _common(record)
    out.update({
        "engagement_id": record["engagement_id"],
        "holder_party_id": record["holder_party_id"],
        "authority_scope": record["authority_scope"],
        "approval_ceiling_cents": record["approval_ceiling_cents"],
        "status": record["status"],
        "effective_from_utc": record["effective_from_utc"],
        "effective_to_utc": record["effective_to_utc"],
        "suspend_count": record["suspend_count"],
        "revoked_reason": record["revoked_reason"],
    })
    return out


def destination_residence(record):
    out = _common(record)
    out.update({
        "engagement_id": record["engagement_id"],
        "name": record["name"],
        "unit_type": record["unit_type"],
        "address_line": record["address_line"],
        "placement_status": record["placement_status"],
        "placement_revision": record["placement_revision"],
        "approved_by_party_id": record["approved_by_party_id"],
        "approved_at_utc": record["approved_at_utc"],
        "room_count": derive.residence_room_count(record["id"]),
        "total_effective_capacity_linear_inches":
            num(derive.residence_total_capacity(record["id"]), 2),
    })
    return out


def destination_room(record):
    out = _common(record)
    out.update({
        "destination_residence_id": record["destination_residence_id"],
        "room_type": record["room_type"],
        "nominal_linear_inches": num(record["nominal_linear_inches"], 2),
        "nominal_volume_cft": num(record["nominal_volume_cft"], 2),
        "approved_addendum_linear_inches": num(record["approved_addendum_linear_inches"], 2),
        "effective_capacity_linear_inches": num(derive.room_effective_capacity(record), 2),
        "keep_load_linear_inches": num(derive.room_keep_load_linear(record["id"]), 2),
        "keep_load_volume_cft": num(derive.room_keep_load_volume(record["id"]), 2),
        "headroom_linear_inches": num(derive.room_headroom(record), 2),
        "assigned_item_count": derive.room_assigned_item_count(record["id"]),
    })
    return out


def inventory_item(record):
    out = _common(record)
    out.update({
        "engagement_id": record["engagement_id"],
        "assigned_room_id": record["assigned_room_id"],
        "consignment_lot_id": record["consignment_lot_id"],
        "unpack_session_id": record["unpack_session_id"],
        "label": record["label"],
        "category": record["category"],
        "footprint_linear_inches": num(record["footprint_linear_inches"], 2),
        "volume_cft": num(record["volume_cft"], 2),
        "appraised_value_cents": record["appraised_value_cents"],
        "appraisal_source": record["appraisal_source"],
        "disposition": record["disposition"],
        "disposition_locked": record["disposition_locked"],
        "handling_state": record["handling_state"],
        "hold_state": derive.item_hold_state(record),
        "redesignation_count": record["redesignation_count"],
        "donation_receipt_cents": derive.item_donation_receipt(record),
    })
    return out


def family_hold(record):
    out = _common(record)
    out.update({
        "inventory_item_id": record["inventory_item_id"],
        "raised_by_party_id": record["raised_by_party_id"],
        "resolved_by_party_id": record["resolved_by_party_id"],
        "status": record["status"],
        "reason": record["reason"],
        "resolution_note": record["resolution_note"],
        "escalation_count": record["escalation_count"],
        "remand_count": record["remand_count"],
    })
    return out


def sort_plan(record):
    out = _common(record)
    locked = len([i for i in derive.items_of(record["engagement_id"]) if i["disposition_locked"]])
    out.update({
        "engagement_id": record["engagement_id"],
        "approved_by_party_id": record["approved_by_party_id"],
        "status": record["status"],
        "notes": record["notes"],
        "rejected_reason": record["rejected_reason"],
        "reopen_count": record["reopen_count"],
        "undecided_count_at_submit": record["undecided_count_at_submit"],
        "locked_item_count": locked,
        "frozen_at_utc": record["frozen_at_utc"],
    })
    return out


def move_day_plan(record):
    out = _common(record)
    actual_volume = record["actual_loaded_volume_cft"]
    out.update({
        "engagement_id": record["engagement_id"],
        "status": record["status"],
        "scheduled_start_utc": record["scheduled_start_utc"],
        "freeze_at_utc": record["freeze_at_utc"],
        "truck_capacity_cft": num(record["truck_capacity_cft"], 2),
        "truck_count": record["truck_count"],
        "planned_trip_count": record["planned_trip_count"],
        "actual_trip_count": record["actual_trip_count"],
        "actual_loaded_volume_cft": None if actual_volume is None else num(actual_volume, 2),
        "crew_confirmed_count": derive.crew_confirmed_count(record),
        "crew_min_required": derive.crew_min_required(record),
        "reschedule_count": record["reschedule_count"],
        "started_at_utc": record["started_at_utc"],
        "completed_at_utc": record["completed_at_utc"],
    })
    return out


def crew_member(record):
    out = _common(record)
    out.update({
        "full_name": record["full_name"],
        "crew_role": record["crew_role"],
        "hourly_rate_cents": record["hourly_rate_cents"],
        "assignment_count": derive.crew_member_assignment_count(record["id"]),
    })
    return out


def crew_assignment(record):
    out = _common(record)
    money = derive.assignment_money(record)
    out.update({
        "move_day_plan_id": record["move_day_plan_id"],
        "crew_member_id": record["crew_member_id"],
        "replaces_assignment_id": record["replaces_assignment_id"],
        "status": record["status"],
        "checked_in_at_utc": record["checked_in_at_utc"],
        "checked_out_at_utc": record["checked_out_at_utc"],
        "portal_hours": num(money["portal_hours"], 2),
        "billing_hours": num(money["billing_hours"], 2),
        "applied_hours": num(money["applied_hours"], 2),
        "overtime_hours": num(money["overtime_hours"], 2),
        "labor_cents": money["labor_cents"],
        "no_show_note": record["no_show_note"],
    })
    return out


def time_entry(record):
    out = _common(record)
    out.update({
        "crew_assignment_id": record["crew_assignment_id"],
        "entry_kind": record["entry_kind"],
        "started_at_utc": record["started_at_utc"],
        "ended_at_utc": record["ended_at_utc"],
        "raw_hours": num(record["raw_hours"], 4),
        "rounded_hours": num(record["rounded_hours"], 2),
        "voided": record["voided"],
        "void_reason": record["void_reason"],
    })
    return out


def vendor(record):
    out = _common(record)
    out.update({
        "name": record["name"],
        "vendor_type": record["vendor_type"],
        "coi_expires_on": record["coi_expires_on"],
        "daily_capacity": record["daily_capacity"],
        "holdback_pct": float(record["holdback_pct"]),
        "coi_renewal_count": record["coi_renewal_count"],
        "blocked_assignment_count": derive.vendor_blocked_assignment_count(record["id"]),
    })
    return out


def vendor_assignment(record):
    out = _common(record)
    out.update({
        "engagement_id": record["engagement_id"],
        "vendor_id": record["vendor_id"],
        "signed_off_by_party_id": record["signed_off_by_party_id"],
        "service_kind": record["service_kind"],
        "service_date": record["service_date"],
        "status": record["status"],
        "quoted_cents": record["quoted_cents"],
        "holdback_cents": record["holdback_cents"],
        "paid_cents": record["paid_cents"],
        "holdback_released": record["holdback_released"],
        "performed_at_utc": record["performed_at_utc"],
        "cancel_reason": record["cancel_reason"],
    })
    return out


def consignment_lot(record):
    out = _common(record)
    out.update({
        "engagement_id": record["engagement_id"],
        "vendor_id": record["vendor_id"],
        "status": record["status"],
        "list_price_cents": record["list_price_cents"],
        "current_price_cents": record["current_price_cents"],
        "markdown_round": record["markdown_round"],
        "listed_on": record["listed_on"],
        "sold_on": record["sold_on"],
        "gross_sale_price_cents": record["gross_sale_price_cents"],
        "commission_cents": record["commission_cents"],
        "fees_cents": record["fees_cents"],
        "net_proceeds_cents": record["net_proceeds_cents"],
        "item_count": len(derive.lot_items(record["id"])),
        "credited": record["credited"],
        "reversed": record["reversed"],
        "disposal_fee_cents": record["disposal_fee_cents"],
    })
    return out


def invoice(record):
    out = _common(record)
    out.update({
        "engagement_id": record["engagement_id"],
        "status": record["status"],
        "subtotal_cents": derive.invoice_subtotal(record),
        "credits_cents": derive.invoice_credits(record),
        "coordination_fee_cents": record["coordination_fee_cents"],
        "total_cents": derive.invoice_total(record),
        "payments_cents": record["payments_cents"],
        "balance_due_cents": derive.invoice_balance_due(record),
        "recall_count": record["recall_count"],
        "dispute_count": record["dispute_count"],
        "dispute_reason": record["dispute_reason"],
        "issued_at_utc": record["issued_at_utc"],
        "finalized_at_utc": record["finalized_at_utc"],
    })
    return out


def invoice_line(record):
    # PRD 2.4: a ledger line is immutable - it carries only id and created_at,
    # and has neither updated_at nor version.
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "invoice_id": record["invoice_id"],
        "source_consignment_lot_id": record["source_consignment_lot_id"],
        "line_type": record["line_type"],
        "amount_cents": record["amount_cents"],
        "memo": record["memo"],
        "created_by_role": record["created_by_role"],
    }


def milestone(record):
    engagement_row = store.get("engagements", record["engagement_id"])
    out = _common(record)
    out.update({
        "engagement_id": record["engagement_id"],
        "completed_by_party_id": record["completed_by_party_id"],
        "milestone_key": record["milestone_key"],
        "sequence_index": record["sequence_index"],
        "status": record["status"],
        "overdue_status": record["overdue_status"],
        "due_on": calc.milestone_due_on(engagement_row["scheduled_move_start_utc"],
                                        record["milestone_key"]),
        "completed_at_utc": record["completed_at_utc"],
        "reopen_count": record["reopen_count"],
    })
    return out


def unpack_session(record):
    out = _common(record)
    out.update({
        "engagement_id": record["engagement_id"],
        "priority": record["priority"],
        "status": record["status"],
        "scheduled_start_utc": record["scheduled_start_utc"],
        "items_unpacked_count": derive.session_items_unpacked_count(record["id"]),
        "reopen_count": record["reopen_count"],
        "started_at_utc": record["started_at_utc"],
    })
    return out


def punch_list_item(record):
    out = _common(record)
    out.update({
        "engagement_id": record["engagement_id"],
        "unpack_session_id": record["unpack_session_id"],
        "severity": record["severity"],
        "status": record["status"],
        "description": record["description"],
        "resolution_note": record["resolution_note"],
        "due_at_utc": calc.punch_due_at(record["created_at"], record["severity"]),
        "breached_sla": derive.punch_breached_sla(record),
        "reopen_count": record["reopen_count"],
    })
    return out


SERIALISERS = {
    "clients": client,
    "engagements": engagement,
    "portal_parties": portal_party,
    "authority_records": authority_record,
    "destination_residences": destination_residence,
    "destination_rooms": destination_room,
    "inventory_items": inventory_item,
    "family_holds": family_hold,
    "sort_plans": sort_plan,
    "move_day_plans": move_day_plan,
    "crew_members": crew_member,
    "crew_assignments": crew_assignment,
    "time_entries": time_entry,
    "vendors": vendor,
    "vendor_assignments": vendor_assignment,
    "consignment_lots": consignment_lot,
    "invoices": invoice,
    "invoice_lines": invoice_line,
    "milestones": milestone,
    "unpack_sessions": unpack_session,
    "punch_list_items": punch_list_item,
}


def dump(collection, record):
    return SERIALISERS[collection](record)
