"""Explicit per-entity serializers (internal keys never leak)."""

COMMON = ("created_at", "updated_at", "version")

FIELDS = {
    "species": ("id", "species_code", "common_name", "acceptance_class",
                "max_cabin_weight_kg", "min_age_weeks", "requires_veterinary_review",
                "breed_restriction_count", "status") + COMMON,
    "breed": ("id", "species_profile_id", "breed_name", "restriction_type",
              "max_weight_kg", "status") + COMMON,
    "dest_req": ("id", "species_profile_id", "destination_country_code", "document_type",
                 "max_age_days_at_arrival", "mandatory", "status") + COMMON,
    "container": ("id", "model_code", "interior_length_cm", "interior_width_cm",
                  "interior_height_cm", "tare_weight_kg", "ventilation_area_pct",
                  "ventilated_side_count", "wheels_removable", "cabin_eligible") + COMMON,
    "station": ("id", "iata_code", "country_code", "kennel_bay_count",
                "reserved_bay_count", "status") + COMMON,
    "embargo_rule": ("id", "station_id", "direction", "season_start_month_day",
                     "season_end_month_day", "forecast_high_limit_c",
                     "forecast_low_limit_c", "applies_to_routings", "status") + COMMON,
    "leg": ("id", "flight_number", "origin_station_id", "destination_station_id",
            "governing_embargo_rule_id", "scheduled_departure_utc",
            "scheduled_arrival_utc", "block_minutes", "forecast_high_c", "forecast_low_c",
            "cabin_animal_limit", "checked_animal_limit", "cargo_animal_limit",
            "booked_cabin_count", "booked_checked_count", "booked_cargo_count",
            "posture", "status") + COMMON,
    "reservation": ("id", "passenger_name", "contact_email", "routing_type",
                    "is_service_animal_booking", "booked_by_agent_id", "booking_status",
                    "compliance_status", "animal_count", "subtotal_amount",
                    "irops_fee_total", "loyalty_tier_pct", "loyalty_discount_amount",
                    "refunded_amount", "net_payable_amount") + COMMON,
    "animal": ("id", "reservation_id", "species_profile_id", "container_model_id",
               "animal_name", "breed_name", "animal_kind", "declared_weight_kg",
               "measured_weight_kg", "height_at_shoulder_cm", "length_nose_to_tail_cm",
               "age_weeks", "chargeable_weight_kg", "container_compliance_state",
               "deficiency_codes", "behavior_attestation_on_file", "status") + COMMON,
    "segment": ("id", "animal_record_id", "flight_leg_id", "routing_type",
                "sequence_index", "connection_minutes", "required_welfare_check_count",
                "completed_welfare_check_count", "segment_fee_amount", "fee_variant",
                "status") + COMMON,
    "document": ("id", "animal_record_id", "document_type", "issuing_country_code",
                 "issued_at", "expires_at", "revision_count", "reviewed_by_user_id",
                 "status") + COMMON,
    "allocation": ("id", "station_id", "animal_record_id", "bay_count",
                   "occupancy_start_utc", "occupancy_end_utc", "feeding_interval_minutes",
                   "status") + COMMON,
    "welfare_check": ("id", "segment_assignment_id", "check_type", "recorded_at_utc",
                      "performed_by_user_id", "outcome", "notes", "created_at"),
    "incident": ("id", "animal_record_id", "segment_assignment_id", "incident_type",
                 "discovered_at_utc", "veterinary_finding", "reported_by_user_id",
                 "investigated_by_user_id", "closed_by_user_id",
                 "preliminary_severity_score", "adjudicated_severity_score",
                 "disclosure_required", "disclosure_deadline_utc", "disclosed_at_utc",
                 "disclosure_on_time", "status") + COMMON,
}


def dump(entity, row):
    if row is None:
        return None
    return dict((name, row.get(name)) for name in FIELDS[entity])


def dump_all(entity, rows):
    return [dump(entity, row) for row in rows]
