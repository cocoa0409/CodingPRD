"""Public field projection for each entity.

Each function returns a plain dict matching the entity's documented fields plus the
common system fields (id, created_at, updated_at, version). ChainOfCustodyEvent is
the exception (id + created_at only). Records are already stored in public shape, so
serialization mostly returns a shallow copy to avoid leaking internal references.
"""


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def panel(rec):
    out = _common(rec)
    out.update({
        "panel_code": rec["panel_code"],
        "name": rec["name"],
        "required_tube_count": rec["required_tube_count"],
        "base_lab_fee_cents": rec["base_lab_fee_cents"],
        "fasting_required": rec["fasting_required"],
        "status": rec["status"],
    })
    return out


def partner(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "courier_sla_hours": rec["courier_sla_hours"],
        "accepted_panel_codes": list(rec["accepted_panel_codes"]),
        "stat_surcharge_cents": rec["stat_surcharge_cents"],
        "status": rec["status"],
    })
    return out


def phlebotomist(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "territory_code": rec["territory_code"],
        "certification_active": rec["certification_active"],
        "redraw_strike_count": rec["redraw_strike_count"],
        "status": rec["status"],
    })
    return out


def route_day(rec):
    out = _common(rec)
    out.update({
        "phlebotomist_id": rec["phlebotomist_id"],
        "territory_code": rec["territory_code"],
        "service_date": rec["service_date"],
        "shift_start_utc": rec["shift_start_utc"],
        "shift_end_utc": rec["shift_end_utc"],
        "stop_capacity": rec["stop_capacity"],
        "booked_stop_count": rec["booked_stop_count"],
        "status": rec["status"],
    })
    return out


def lab_order(rec):
    out = _common(rec)
    out.update({
        "ordering_provider_id": rec["ordering_provider_id"],
        "patient_full_name": rec["patient_full_name"],
        "patient_territory_code": rec["patient_territory_code"],
        "panel_code": rec["panel_code"],
        "lab_partner_id": rec["lab_partner_id"],
        "priority": rec["priority"],
        "billing_mode": rec["billing_mode"],
        "insurance_member_id": rec["insurance_member_id"],
        "appointment_id": rec["appointment_id"],
        "specimens_required_count": rec["specimens_required_count"],
        "specimens_accessioned_count": rec["specimens_accessioned_count"],
        "redraw_count": rec["redraw_count"],
        "total_due_cents": rec["total_due_cents"],
        "status": rec["status"],
    })
    return out


def appointment(rec):
    out = _common(rec)
    out.update({
        "lab_order_id": rec["lab_order_id"],
        "route_day_id": rec["route_day_id"],
        "phlebotomist_id": rec["phlebotomist_id"],
        "window_start_utc": rec["window_start_utc"],
        "window_end_utc": rec["window_end_utc"],
        "status": rec["status"],
    })
    return out


def draw_kit(rec):
    out = _common(rec)
    out.update({
        "appointment_id": rec["appointment_id"],
        "kit_lot_number": rec["kit_lot_number"],
        "tube_count": rec["tube_count"],
        "status": rec["status"],
    })
    return out


def specimen(rec):
    out = _common(rec)
    out.update({
        "lab_order_id": rec["lab_order_id"],
        "appointment_id": rec["appointment_id"],
        "tube_label": rec["tube_label"],
        "collected_at_utc": rec["collected_at_utc"],
        "courier_manifest_id": rec["courier_manifest_id"],
        "status": rec["status"],
    })
    return out


def custody_event(rec):
    # PRD 2.4: id and created_at only — immutable, no updated_at / version.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "specimen_id": rec["specimen_id"],
        "prior_event_id": rec["prior_event_id"],
        "event_type": rec["event_type"],
        "actor_role": rec["actor_role"],
        "actor_user_id": rec["actor_user_id"],
        "sequence_index": rec["sequence_index"],
    }


def manifest(rec):
    out = _common(rec)
    out.update({
        "lab_partner_id": rec["lab_partner_id"],
        "territory_code": rec["territory_code"],
        "picked_up_at_utc": rec["picked_up_at_utc"],
        "accession_due_utc": rec["accession_due_utc"],
        "specimen_count": rec["specimen_count"],
        "status": rec["status"],
    })
    return out


def lab_result(rec):
    out = _common(rec)
    out.update({
        "lab_order_id": rec["lab_order_id"],
        "lab_partner_id": rec["lab_partner_id"],
        "result_value": rec["result_value"],
        "released_to_provider": rec["released_to_provider"],
        "released_to_portal": rec["released_to_portal"],
        "status": rec["status"],
    })
    return out


def invoice(rec):
    out = _common(rec)
    out.update({
        "lab_order_id": rec["lab_order_id"],
        "billing_mode": rec["billing_mode"],
        "lab_fee_cents": rec["lab_fee_cents"],
        "convenience_fee_cents": rec["convenience_fee_cents"],
        "redraw_waiver_cents": rec["redraw_waiver_cents"],
        "total_cents": rec["total_cents"],
        "status": rec["status"],
    })
    return out
