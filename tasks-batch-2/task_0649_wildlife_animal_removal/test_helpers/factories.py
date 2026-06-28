"""Payload factories — one per entity, input fields only."""


def create_species_profile_payload(**overrides) -> dict:
    """SpeciesProfile inputs. common_name, code, base_trap_fee_cents required;
    is_regulated/relocation_min/relocation_max/humane_check_interval_hours/risk_weight optional."""
    defaults = {
        "common_name": "Eastern Gray Squirrel",
        "code": "GRAY_SQUIRREL",
        "base_trap_fee_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    """Technician inputs. full_name, kit_trap_capacity required; license_tier optional (default BASIC)."""
    defaults = {
        "full_name": "Test Technician",
        "kit_trap_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_service_account_payload(**overrides) -> dict:
    defaults = {
        "account_name": "Test Account",
        "contact_email": "owner@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(account_id: str, **overrides) -> dict:
    """Property inputs. account_id, latitude, longitude required."""
    defaults = {
        "account_id": account_id,
        "latitude": 40.0,
        "longitude": -75.0,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    """Inspection inputs. scheduled_for required; is_emergency optional (default false)."""
    defaults = {
        "scheduled_for": "2026-04-02T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_entry_point_payload(species_id: str, **overrides) -> dict:
    """EntryPoint inputs. species_id, location_label, estimated_individuals required;
    severity optional (default MODERATE)."""
    defaults = {
        "species_id": species_id,
        "location_label": "NE soffit gap",
        "estimated_individuals": 1,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(inspection_id: str, expected_inspection_version: int, **overrides) -> dict:
    """Quote inputs. inspection_id, expected_inspection_version required."""
    defaults = {
        "inspection_id": inspection_id,
        "expected_inspection_version": expected_inspection_version,
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(species_id: str, **overrides) -> dict:
    """QuoteLineItem inputs. species_id, line_type, quantity, unit_price_cents required."""
    defaults = {
        "species_id": species_id,
        "line_type": "TRAP",
        "quantity": 1,
        "unit_price_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_accept_payload(assigned_technician_id: str, **overrides) -> dict:
    """Quote accept body. assigned_technician_id required."""
    defaults = {
        "assigned_technician_id": assigned_technician_id,
    }
    defaults.update(overrides)
    return defaults


def create_trap_placement_payload(species_id: str, technician_id: str, **overrides) -> dict:
    """TrapPlacement inputs. species_id, technician_id, window_start, window_end required."""
    defaults = {
        "species_id": species_id,
        "technician_id": technician_id,
        "window_start": "2026-04-03T09:00:00Z",
        "window_end": "2026-04-03T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_capture_payload(**overrides) -> dict:
    """CaptureEvent inputs. captured_at, release_latitude, release_longitude required."""
    defaults = {
        "captured_at": "2026-04-03T12:00:00Z",
        "release_latitude": 40.145,
        "release_longitude": -75.0,
    }
    defaults.update(overrides)
    return defaults


def create_exclusion_repair_payload(entry_point_id: str, **overrides) -> dict:
    """ExclusionRepair inputs. entry_point_id required; sanitation_included optional (default false)."""
    defaults = {
        "entry_point_id": entry_point_id,
    }
    defaults.update(overrides)
    return defaults


def create_monitoring_visit_payload(**overrides) -> dict:
    """MonitoringVisit inputs. visit_start, visit_end required; traps_reset optional (default 0)."""
    defaults = {
        "visit_start": "2026-05-01T09:00:00Z",
        "visit_end": "2026-05-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    """WarrantyClaim inputs. reported_at, description required."""
    defaults = {
        "reported_at": "2026-05-15T00:00:00Z",
        "description": "Recurrence reported",
    }
    defaults.update(overrides)
    return defaults


def create_permit_approve_payload(**overrides) -> dict:
    """Permit approve body. permit_number required at approval (PRD §3.5)."""
    defaults = {
        "permit_number": "REG-2026-001",
    }
    defaults.update(overrides)
    return defaults
