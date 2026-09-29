"""Explicit resource serializers.  Computed fields are derived at render time so
that a response always shows the current derived truth."""

import calc


def event_out(event):
    derived = calc.derived_event(event)
    return {
        "id": event["id"],
        "created_at": event["created_at"],
        "updated_at": event["updated_at"],
        "version": event["version"],
        "name": event["name"],
        "code": event["code"],
        "event_start_date": event["event_start_date"],
        "event_end_date": event["event_end_date"],
        "cutoff_date": event["cutoff_date"],
        "attrition_deadline_date": event["attrition_deadline_date"],
        "standard_commission_pct": event["standard_commission_pct"],
        "standard_rebate_per_room_night_cents": event["standard_rebate_per_room_night_cents"],
        "night_count": event["night_count"],
        "housing_posture": derived["housing_posture"],
        "total_contracted_room_nights": derived["total_contracted_room_nights"],
        "total_confirmed_room_nights": derived["total_confirmed_room_nights"],
        "commission_collected_cents": derived["commission_collected_cents"],
    }


def hotel_out(hotel):
    return {
        "id": hotel["id"],
        "created_at": hotel["created_at"],
        "updated_at": hotel["updated_at"],
        "version": hotel["version"],
        "name": hotel["name"],
        "distance_to_venue_miles": hotel["distance_to_venue_miles"],
        "room_tax_pct": hotel["room_tax_pct"],
        "total_rooms": hotel["total_rooms"],
        "standing": hotel["standing"],
    }


def block_out(block):
    return {
        "id": block["id"],
        "created_at": block["created_at"],
        "updated_at": block["updated_at"],
        "version": block["version"],
        "event_id": block["event_id"],
        "hotel_id": block["hotel_id"],
        "status": block["status"],
        "revision_round": block["revision_round"],
        "negotiated_nightly_rate_cents": block["negotiated_nightly_rate_cents"],
        "commission_pct": block["commission_pct"],
        "rebate_per_room_night_cents": block["rebate_per_room_night_cents"],
        "cutoff_date": block["cutoff_date"],
        "reduction_rights_pct": block["reduction_rights_pct"],
        "contracted_rooms_per_night": block["contracted_rooms_per_night"],
        "original_contracted_rooms_per_night": block["original_contracted_rooms_per_night"],
        "unassigned_rooms_per_night": block["unassigned_rooms_per_night"],
        "released_rooms_per_night": block["released_rooms_per_night"],
        "contracted_room_nights": calc.block_contracted_room_nights(block),
        "attrition_liability_cents": block["attrition_liability_cents"],
        "confirmation_number": block["confirmation_number"],
    }


def sub_block_out(sub_block):
    committed, available, inventory_status = calc.derived_sub_block(sub_block)
    return {
        "id": sub_block["id"],
        "created_at": sub_block["created_at"],
        "updated_at": sub_block["updated_at"],
        "version": sub_block["version"],
        "hotel_block_id": sub_block["hotel_block_id"],
        "parent_sub_block_id": sub_block["parent_sub_block_id"],
        "segment": sub_block["segment"],
        "allotted_rooms": sub_block["allotted_rooms"],
        "eligibility_code": sub_block["eligibility_code"],
        "approval_status": sub_block["approval_status"],
        "carve_seq": sub_block["carve_seq"],
        "requested_by_user_id": sub_block["requested_by_user_id"],
        "approved_by_user_id": sub_block["approved_by_user_id"],
        "committed_rooms": committed,
        "available_rooms": available,
        "released_rooms": sub_block["released_rooms"],
        "inventory_status": inventory_status,
    }


def attendee_out(attendee):
    return {
        "id": attendee["id"],
        "created_at": attendee["created_at"],
        "updated_at": attendee["updated_at"],
        "version": attendee["version"],
        "event_id": attendee["event_id"],
        "email": attendee["email"],
        "full_name": attendee["full_name"],
        "registration_id": attendee["registration_id"],
        "attendee_type": attendee["attendee_type"],
        "eligibility_codes": list(attendee["eligibility_codes"]),
        "warning_count": attendee["warning_count"],
        "housing_risk_flag": attendee["housing_risk_flag"],
        "no_show_strikes": attendee["no_show_strikes"],
    }


def reservation_out(reservation):
    return {
        "id": reservation["id"],
        "created_at": reservation["created_at"],
        "updated_at": reservation["updated_at"],
        "version": reservation["version"],
        "sub_block_id": reservation["sub_block_id"],
        "attendee_id": reservation["attendee_id"],
        "check_in_date": reservation["check_in_date"],
        "check_out_date": reservation["check_out_date"],
        "occupants": reservation["occupants"],
        "intake_seq": reservation["intake_seq"],
        "room_nights": reservation["room_nights"],
        "quoted_nightly_rate_cents": reservation["quoted_nightly_rate_cents"],
        "room_tax_pct_snapshot": reservation["room_tax_pct_snapshot"],
        "total_room_charge_cents": reservation["total_room_charge_cents"],
        "reservation_status": reservation["reservation_status"],
        "transmission_status": reservation["transmission_status"],
        "eligibility_review_required": reservation["eligibility_review_required"],
        "no_show_billed_cents": reservation["no_show_billed_cents"],
    }


def transmission_out(batch):
    # Append-only ledger of fact: only id and created_at, no updated_at/version.
    return {
        "id": batch["id"],
        "created_at": batch["created_at"],
        "hotel_block_id": batch["hotel_block_id"],
        "transmission_type": batch["transmission_type"],
        "batch_seq": batch["batch_seq"],
        "reservation_count": batch["reservation_count"],
        "transmitted_at": batch["transmitted_at"],
        "included_reservation_ids": list(batch["included_reservation_ids"]),
    }


def pickup_report_out(report):
    # Append-only ledger of fact: only id and created_at, no updated_at/version.
    return {
        "id": report["id"],
        "created_at": report["created_at"],
        "hotel_block_id": report["hotel_block_id"],
        "as_of_date": report["as_of_date"],
        "reported_rooms_picked_up": report["reported_rooms_picked_up"],
        "reported_room_nights": report["reported_room_nights"],
        "reported_gross_revenue_cents": report["reported_gross_revenue_cents"],
        "source": report["source"],
    }


def reduction_out(reduction):
    return {
        "id": reduction["id"],
        "created_at": reduction["created_at"],
        "updated_at": reduction["updated_at"],
        "version": reduction["version"],
        "hotel_block_id": reduction["hotel_block_id"],
        "requested_reduction_rooms": reduction["requested_reduction_rooms"],
        "effective_date": reduction["effective_date"],
        "justification_code": reduction["justification_code"],
        "status": reduction["status"],
        "requested_by_user_id": reduction["requested_by_user_id"],
        "approved_by_user_id": reduction["approved_by_user_id"],
        "rooms_absorbed_from_unassigned": reduction["rooms_absorbed_from_unassigned"],
        "rooms_absorbed_from_sub_blocks": reduction["rooms_absorbed_from_sub_blocks"],
        "penalty_avoided_cents": reduction["penalty_avoided_cents"],
    }


def vendor_out(vendor):
    score, verified_count = calc.vendor_derived(vendor)
    return {
        "id": vendor["id"],
        "created_at": vendor["created_at"],
        "updated_at": vendor["updated_at"],
        "version": vendor["version"],
        "event_id": vendor["event_id"],
        "name": vendor["name"],
        "contact_domain": vendor["contact_domain"],
        "detection_source": vendor["detection_source"],
        "status": vendor["status"],
        "risk_score": score,
        "verified_incident_count": verified_count,
        "warning_issued_count": vendor["warning_issued_count"],
    }


def incident_out(incident):
    return {
        "id": incident["id"],
        "created_at": incident["created_at"],
        "updated_at": incident["updated_at"],
        "version": incident["version"],
        "rogue_vendor_id": incident["rogue_vendor_id"],
        "attendee_id": incident["attendee_id"],
        "contact_channel": incident["contact_channel"],
        "occurred_at": incident["occurred_at"],
        "verified": incident["verified"],
        "solicited_payment": incident["solicited_payment"],
        "status": incident["status"],
        "warning_issued_at": incident["warning_issued_at"],
        "warning_severity": incident["warning_severity"],
    }


def invoice_out(invoice):
    return {
        "id": invoice["id"],
        "created_at": invoice["created_at"],
        "updated_at": invoice["updated_at"],
        "version": invoice["version"],
        "hotel_block_id": invoice["hotel_block_id"],
        "basis": invoice["basis"],
        "bureau_confirmed_commission_cents": invoice["bureau_confirmed_commission_cents"],
        "hotel_reported_commission_cents": invoice["hotel_reported_commission_cents"],
        "commission_due_cents": invoice["commission_due_cents"],
        "rebate_due_cents": invoice["rebate_due_cents"],
        "billable_room_nights": invoice["billable_room_nights"],
        "variance_cents": invoice["variance_cents"],
        "paid_cents": invoice["paid_cents"],
        "written_off_cents": invoice["written_off_cents"],
        "outstanding_cents": calc.invoice_outstanding(invoice),
        "status": invoice["status"],
    }
