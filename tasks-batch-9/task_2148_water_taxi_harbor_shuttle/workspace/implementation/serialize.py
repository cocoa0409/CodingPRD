"""Resource representations.  Internal keys (prefixed with _) never leak."""

import calc

COMMON = ("id", "created_at", "updated_at", "version")


def _base(row, fields, versioned=True):
    out = {"id": row["id"]}
    for name in fields:
        out[name] = row.get(name)
    out["created_at"] = row["created_at"]
    if versioned:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


DOCK_FIELDS = ("name", "berth_count", "min_turnaround_minutes",
               "landing_fee_per_pax_cents", "berth_minute_rate_cents",
               "monthly_fee_cap_cents", "shared_operator_count",
               "accrued_fee_cents", "fee_status")

STOP_FIELDS = ("dock_id", "name", "zone_index", "charted_depth_m")

VESSEL_FIELDS = ("name", "seat_capacity", "draft_m", "hull_class",
                 "required_endorsement", "layup_start_date", "layup_end_date")

INSPECTION_FIELDS = ("vessel_id", "inspection_type", "result", "deficiency_count",
                     "performed_on", "expires_on", "inspector_user_id")

CREW_FIELDS = ("name", "endorsement_class", "cert_expires_on", "medical_expires_on",
               "status", "trips_mastered_count")

DAY_FIELDS = ("service_date", "wind_knots", "wave_height_m", "low_water_m",
              "manual_suspension", "event_name", "expected_attendance",
              "posture", "surge_tier", "surge_multiplier_bp", "planned_extra_vessels")

TRIP_FIELDS = ("service_day_id", "vessel_id", "master_crew_id", "origin_stop_id",
               "destination_stop_id", "service_mode", "scheduled_departure_utc",
               "scheduled_arrival_utc", "actual_departure_utc", "actual_arrival_utc",
               "seats_committed", "booked_pax", "boarded_pax", "operational_status",
               "settlement_status", "provisional_fee_cents", "final_fee_cents",
               "cancellation_reason")

SLOT_FIELDS = ("dock_id", "trip_id", "purpose", "start_utc", "end_utc", "status",
               "pax_basis", "berth_minutes", "rebate_bp", "projected_fee_cents",
               "landing_fee_cents")

PASS_FIELDS = ("rider_user_id", "zone_tier", "rides_purchased", "purchase_price_cents",
               "valid_until", "rides_remaining", "status", "refund_basis",
               "refund_amount_cents")

BOOKING_FIELDS = ("rider_user_id", "trip_id", "ride_pass_id", "origin_stop_id",
                  "destination_stop_id", "requested_date", "service_mode", "party_size",
                  "offer_round", "declined_trip_ids", "status", "redemption_status",
                  "interrupted_from_status", "fare_quoted_cents", "fare_charged_cents",
                  "fare_refunded_cents", "credit_refunded_cents")

INTERRUPTION_FIELDS = ("service_day_id", "cause", "declared_by_user_id", "status",
                       "affected_booking_count", "total_provisional_refund_cents")

CLAIM_FIELDS = ("booking_id", "service_interruption_id", "declarer_user_id",
                "approver_user_id", "entitlement_cents", "cash_refund_cents",
                "credit_refund_cents", "ride_restored", "status")


def dock(row):
    return _base(row, DOCK_FIELDS)


def stop(row):
    return _base(row, STOP_FIELDS)


def vessel(row):
    out = _base(row, VESSEL_FIELDS)
    out["service_state"] = calc.vessel_service_state(row)
    out["annual_inspection_expires_on"] = calc.vessel_annual_expires_on(row)
    return out


def inspection(row):
    return _base(row, INSPECTION_FIELDS, versioned=False)


def crew_member(row):
    return _base(row, CREW_FIELDS)


def service_day(row):
    return _base(row, DAY_FIELDS)


def trip(row):
    out = _base(row, TRIP_FIELDS)
    out["effective_capacity"] = calc.trip_effective_capacity(row)
    return out


def dock_slot(row):
    return _base(row, SLOT_FIELDS)


def ride_pass(row):
    out = _base(row, PASS_FIELDS)
    out["rides_consumed"] = calc.rides_consumed(row)
    return out


def booking(row):
    out = _base(row, BOOKING_FIELDS)
    out["declined_trip_ids"] = list(row.get("declined_trip_ids") or [])
    return out


def interruption(row):
    return _base(row, INTERRUPTION_FIELDS)


def refund_claim(row):
    return _base(row, CLAIM_FIELDS)
