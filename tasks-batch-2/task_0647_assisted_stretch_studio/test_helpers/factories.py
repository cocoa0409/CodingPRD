"""Payload factories — one per entity, input fields only."""


def create_location_payload(**overrides) -> dict:
    """Location create. Only `name` is required; everything else has a server default."""
    defaults = {"name": "Test Location"}
    defaults.update(overrides)
    return defaults


def create_flexologist_payload(location_id, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "full_name": "Test Flexologist",
        "certified_intro": True,
    }
    defaults.update(overrides)
    return defaults


def create_table_payload(location_id, **overrides) -> dict:
    defaults = {"location_id": location_id, "label": "T1"}
    defaults.update(overrides)
    return defaults


def create_service_payload(location_id, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "name": "50m Stretch",
        "kind": "ASSISTED_STRETCH",
        "duration_minutes": 50,
        "credit_cost": 1,
        "list_price_cents": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(home_location_id, **overrides) -> dict:
    defaults = {
        "home_location_id": home_location_id,
        "full_name": "Test Member",
        "email": "member@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(member_id, location_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "location_id": location_id,
        "tier": "PRO",
        "monthly_fee_cents": 12000,
        "included_credits": 8,
        "rollover_cap": 4,
    }
    defaults.update(overrides)
    return defaults


def create_credit_pack_payload(member_id, location_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "location_id": location_id,
        "pack_credits": 10,
        "base_unit_price_cents": 100,
        "expires_utc": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(member_id, location_id, service_id, flexologist_id,
                           table_id, session_start_utc, funding_source, funding_id,
                           **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "location_id": location_id,
        "service_id": service_id,
        "flexologist_id": flexologist_id,
        "table_id": table_id,
        "session_start_utc": session_start_utc,
        "funding_source": funding_source,
        "funding_id": funding_id,
    }
    defaults.update(overrides)
    return defaults


def create_recurring_series_payload(member_id, location_id, service_id, flexologist_id,
                                    table_id, funding_source, funding_id,
                                    first_start_utc, interval_days, occurrence_count,
                                    **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "location_id": location_id,
        "service_id": service_id,
        "flexologist_id": flexologist_id,
        "table_id": table_id,
        "funding_source": funding_source,
        "funding_id": funding_id,
        "first_start_utc": first_start_utc,
        "interval_days": interval_days,
        "occurrence_count": occurrence_count,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(**overrides) -> dict:
    defaults = {"kind": "PERCUSSION", "price_cents": 1500}
    defaults.update(overrides)
    return defaults


def freeze_payload(freeze_start_utc, freeze_end_utc, expected_membership_version, **overrides) -> dict:
    defaults = {
        "freeze_start_utc": freeze_start_utc,
        "freeze_end_utc": freeze_end_utc,
        "expected_membership_version": expected_membership_version,
    }
    defaults.update(overrides)
    return defaults


def intro_assessment_payload(shoulder=90, hip=85, spine=80, ankle=70, **overrides) -> dict:
    defaults = {
        "assessment_shoulder": shoulder,
        "assessment_hip": hip,
        "assessment_spine": spine,
        "assessment_ankle": ankle,
    }
    defaults.update(overrides)
    return defaults
