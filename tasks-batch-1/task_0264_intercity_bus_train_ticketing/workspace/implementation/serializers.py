"""Project internal records into public API output shapes (scaffold 1.1)."""


def operator_out(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "mode": r["mode"],
        "default_connection_buffer_min": r["default_connection_buffer_min"],
        "exchange_fee_cents": r["exchange_fee_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def fare_class_out(r):
    return {
        "id": r["id"],
        "operator_id": r["operator_id"],
        "code": r["code"],
        "seating_mode": r["seating_mode"],
        "surcharge_cents": r["surcharge_cents"],
        "refundable": r["refundable"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def route_out(r):
    return {
        "id": r["id"],
        "operator_id": r["operator_id"],
        "origin_code": r["origin_code"],
        "destination_code": r["destination_code"],
        "depart_minute_of_day": r["depart_minute_of_day"],
        "arrive_minute_of_day": r["arrive_minute_of_day"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def service_date_out(r):
    return {
        "id": r["id"],
        "route_id": r["route_id"],
        "departure_date": r["departure_date"],
        "seats_total": r["seats_total"],
        "base_fare_cents": r["base_fare_cents"],
        "seats_held": r["seats_held"],
        "seats_sold": r["seats_sold"],
        "seats_available": r["seats_available"],
        "load_factor": r["load_factor"],
        "lifecycle": r["lifecycle"],
        "sales": r["sales"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def passenger_out(r):
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "needs_accessibility": r["needs_accessibility"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def travel_pass_out(r):
    return {
        "id": r["id"],
        "passenger_id": r["passenger_id"],
        "operator_id": r["operator_id"],
        "rides_total": r["rides_total"],
        "rides_consumed": r["rides_consumed"],
        "rides_remaining": r["rides_remaining"],
        "status": r["status"],
        "expires_on": r["expires_on"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def booking_out(r):
    return {
        "id": r["id"],
        "passenger_id": r["passenger_id"],
        "booking_status": r["booking_status"],
        "payment_status": r["payment_status"],
        "funding_kind": r["funding_kind"],
        "pass_id": r.get("pass_id"),
        "total_fare_cents": r["total_fare_cents"],
        "total_paid_cents": r["total_paid_cents"],
        "hold_expires_at": r["hold_expires_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def booking_leg_out(r):
    return {
        "id": r["id"],
        "booking_id": r["booking_id"],
        "service_date_id": r["service_date_id"],
        "fare_class_id": r["fare_class_id"],
        "leg_order": r["leg_order"],
        "seat_number": r.get("seat_number"),
        "fare_cents": r["fare_cents"],
        "leg_state": r["leg_state"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ticket_out(r):
    return {
        "id": r["id"],
        "booking_id": r["booking_id"],
        "booking_leg_id": r["booking_leg_id"],
        "barcode": r["barcode"],
        "state": r["state"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def baggage_out(r):
    return {
        "id": r["id"],
        "booking_id": r["booking_id"],
        "weight_kg": r["weight_kg"],
        "fee_cents": r["fee_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def accessibility_out(r):
    return {
        "id": r["id"],
        "booking_leg_id": r["booking_leg_id"],
        "accommodation": r["accommodation"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def settlement_note_out(r):
    # Append-only/immutable: no updated_at, no version (PRD 2.4).
    return {
        "id": r["id"],
        "booking_id": r["booking_id"],
        "settlement_kind": r["settlement_kind"],
        "gross_cents": r["gross_cents"],
        "penalty_cents": r["penalty_cents"],
        "net_cents": r["net_cents"],
        "created_at": r["created_at"],
    }
