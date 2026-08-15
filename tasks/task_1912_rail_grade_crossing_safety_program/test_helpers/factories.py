"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

_DOT_SERIAL = [100000]


def next_dot_number() -> str:
    """Unique federally assigned crossing inventory number per call."""
    _DOT_SERIAL[0] += 1
    return f"DOT-{_DOT_SERIAL[0]:06d}"


def create_locality_payload(**overrides) -> dict:
    defaults = {
        "locality_name": "Test City",
        "state_code": "KS",
        "contact_email": "pw@test.gov",
    }
    defaults.update(overrides)
    return defaults


def create_diagnostic_team_payload(**overrides) -> dict:
    defaults = {
        "team_name": "Test Team",
        "lead_agency": "DOT",
    }
    defaults.update(overrides)
    return defaults


def create_crossing_payload(**overrides) -> dict:
    defaults = {
        "dot_crossing_number": next_dot_number(),
        "railroad_code": "BNSF",
        "road_authority_locality_id": None,  # must be supplied
        "highway_functional_class": "LOCAL",
        "annual_train_count": 365,
        "train_speed_max_mph": 25,
        "aadt": 5000,
        "sight_distance_rating": 3,
        "warning_device_class": "GATES",
    }
    defaults.update(overrides)
    return defaults


def create_diagnostic_review_payload(**overrides) -> dict:
    defaults = {
        "crossing_id": None,  # must be supplied
        "team_id": None,      # must be supplied
        "scheduled_date": "2026-09-10",
    }
    defaults.update(overrides)
    return defaults


def create_incident_report_payload(**overrides) -> dict:
    defaults = {
        "crossing_id": None,  # must be supplied
        "occurred_at": "2026-06-01T10:00:00Z",
        "severity": "NEAR_MISS",
    }
    defaults.update(overrides)
    return defaults


def create_funding_program_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year": 2100,
        "apportionment_cents": 1_000_000,
        "allocation_method": "WATERFALL_BY_RANK",
    }
    defaults.update(overrides)
    return defaults


def create_upgrade_project_payload(**overrides) -> dict:
    defaults = {
        "crossing_id": None,  # must be supplied
        "program_id": None,   # must be supplied
        "target_device_class": "FOUR_QUADRANT_GATES",
        "estimated_cost_cents": 300_000,
    }
    defaults.update(overrides)
    return defaults


def create_closure_agreement_payload(**overrides) -> dict:
    defaults = {
        "crossing_id": None,  # must be supplied
        "locality_id": None,  # must be supplied
        "closure_type": "CLOSURE",
    }
    defaults.update(overrides)
    return defaults


def create_quiet_zone_application_payload(**overrides) -> dict:
    defaults = {
        "locality_id": None,  # must be supplied
    }
    defaults.update(overrides)
    return defaults


def create_quiet_zone_member_payload(**overrides) -> dict:
    defaults = {
        "crossing_id": None,  # must be supplied
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_assignment_payload(**overrides) -> dict:
    defaults = {
        "crossing_id": None,  # must be supplied
        "category": "SIGNAL",
        "responsible_party": "RAILROAD",
        "effective_from": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_work_order_payload(**overrides) -> dict:
    defaults = {
        "crossing_id": None,  # must be supplied
        "category": "SIGNAL",
        "window_start": "2026-09-01T08:00:00Z",
        "window_end": "2026-09-01T12:00:00Z",
        "fouls_track": False,
    }
    defaults.update(overrides)
    return defaults


def create_preemption_interconnection_payload(**overrides) -> dict:
    defaults = {
        "crossing_id": None,  # must be supplied
        "traffic_signal_ref": "SIG-100",
        "track_approach_distance_ft": 1500,
        "design_train_speed_mph": 40,
        "clear_storage_distance_ft": 75,
        "advance_preemption_seconds": 0,
        "track_clearance_green_seconds": 5,
    }
    defaults.update(overrides)
    return defaults
