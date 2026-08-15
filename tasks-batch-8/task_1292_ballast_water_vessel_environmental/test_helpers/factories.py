"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "IMO_NUMBER": "9000001",
    "VESSEL_NAME": "MV Test Vessel",
    "BWMS_TYPE": "TREATMENT_USCG_TYPE_APPROVED",
    "BWMS_INSTALLATION_DATE": "2025-01-15T00:00:00Z",
    "GROSS_TONNAGE": 40000,
    "KEEL_LAID_DATE": "2010-10-01T00:00:00Z",
    "BALLAST_CAPACITY_M3": 30000,
    "PLAN_REVISION": 1,
    "APPROVAL_AUTHORITY": "USCG",
    "PLAN_APPROVED_AT": "2025-02-01T00:00:00Z",
    "EXCHANGE_DISTANCE_NM": 200,
    "VOYAGE_NUMBER": "V1001",
    "DEPARTURE_PORT": "USNYC",
    "ARRIVAL_PORT": "USLAX",
    "DEPARTED_AT": "2026-07-28T00:00:00Z",
    "TANK_ID": "T1",
    "EVENT_OCCURRED_AT": "2026-07-28T06:00:00Z",
    "VOLUME_M3": 500,
    "SALINITY_PPT": 32.0,
    "SOURCE_PORT_LOCODE": "USNYC",
    "DISCHARGE_LAT": 35.0,
    "DISCHARGE_LON": -140.0,
    "DISCHARGE_DISTANCE_NM": 250,
    "SAMPLED_AT": "2026-07-29T00:00:00Z",
    "ORGANISM_CONCENTRATION": 12.0,
    "TSS_MG_PER_L": 10.0,
    "FUEL_TYPE": "VLSFO",
    "SULFUR_CONTENT_PCT": 0.08,
    "CONSUMED_VOLUME_MT": 600,
    "INSIDE_ECA_HOURS": 10,
    "OUTSIDE_ECA_HOURS": 20,
    "DRILL_SCHEDULED_FOR": "2026-08-20T00:00:00Z",
    "ENTRY_OCCURRED_AT": "2026-07-30T00:00:00Z",
    "ENTRY_QUANTITY": 10,
    "SIGNED_BY": "CREW:Chief",
}


def create_vessel_payload(**overrides) -> dict:
    """Vessel registration payload. Pass bwms_installation_date=None to omit it
    (it is required if and only if bwms_type is not NONE)."""
    defaults = {
        "imo_number": DEFAULTS["IMO_NUMBER"],
        "vessel_name": DEFAULTS["VESSEL_NAME"],
        "bwms_type": DEFAULTS["BWMS_TYPE"],
        "bwms_installation_date": DEFAULTS["BWMS_INSTALLATION_DATE"],
        "gross_tonnage": DEFAULTS["GROSS_TONNAGE"],
        "keel_laid_date": DEFAULTS["KEEL_LAID_DATE"],
        "ballast_capacity_m3": DEFAULTS["BALLAST_CAPACITY_M3"],
    }
    defaults.update(overrides)
    if defaults.get("bwms_installation_date") is None:
        defaults.pop("bwms_installation_date")
    return defaults


def create_plan_payload(expected_vessel_version, **overrides) -> dict:
    defaults = {
        "plan_revision": DEFAULTS["PLAN_REVISION"],
        "approval_authority": DEFAULTS["APPROVAL_AUTHORITY"],
        "approved_at": DEFAULTS["PLAN_APPROVED_AT"],
        "exchange_distance_nm": DEFAULTS["EXCHANGE_DISTANCE_NM"],
        "sediment_management_included": True,
        "expected_vessel_version": expected_vessel_version,
    }
    defaults.update(overrides)
    return defaults


def create_voyage_payload(**overrides) -> dict:
    """Voyage creation payload. arrived_at is optional; pass arrived_at=None to omit."""
    defaults = {
        "voyage_number": DEFAULTS["VOYAGE_NUMBER"],
        "departure_port": DEFAULTS["DEPARTURE_PORT"],
        "arrival_port": DEFAULTS["ARRIVAL_PORT"],
        "departed_at": DEFAULTS["DEPARTED_AT"],
        "crosses_captain_of_port_zones": True,
        "enters_us_eez": True,
    }
    defaults.update(overrides)
    if defaults.get("arrived_at") is None:
        defaults.pop("arrived_at", None)
    return defaults


def create_ballast_event_payload(expected_voyage_version, **overrides) -> dict:
    defaults = {
        "event_kind": "UPTAKE",
        "occurred_at": DEFAULTS["EVENT_OCCURRED_AT"],
        "tank_id": DEFAULTS["TANK_ID"],
        "volume_m3": DEFAULTS["VOLUME_M3"],
        "expected_voyage_version": expected_voyage_version,
    }
    defaults.update(overrides)
    # Drop optional keys explicitly set to None.
    return {k: v for k, v in defaults.items() if v is not None}


def uptake_event_payload(expected_voyage_version, **overrides) -> dict:
    defaults = {
        "event_kind": "UPTAKE",
        "salinity_ppt": DEFAULTS["SALINITY_PPT"],
        "source_port_locode": DEFAULTS["SOURCE_PORT_LOCODE"],
    }
    defaults.update(overrides)
    return create_ballast_event_payload(expected_voyage_version, **defaults)


def discharge_event_payload(expected_voyage_version, **overrides) -> dict:
    defaults = {
        "event_kind": "DISCHARGE",
        "latitude": DEFAULTS["DISCHARGE_LAT"],
        "longitude": DEFAULTS["DISCHARGE_LON"],
        "distance_from_shore_nm": DEFAULTS["DISCHARGE_DISTANCE_NM"],
    }
    defaults.update(overrides)
    return create_ballast_event_payload(expected_voyage_version, **defaults)


def exchange_complete_event_payload(expected_voyage_version, **overrides) -> dict:
    defaults = {
        "event_kind": "EXCHANGE_COMPLETE",
        "latitude": 30.0,
        "longitude": -150.0,
        "distance_from_shore_nm": 200.0,
    }
    defaults.update(overrides)
    return create_ballast_event_payload(expected_voyage_version, **defaults)


def treatment_complete_event_payload(expected_voyage_version, **overrides) -> dict:
    defaults = {"event_kind": "TREATMENT_COMPLETE"}
    defaults.update(overrides)
    return create_ballast_event_payload(expected_voyage_version, **defaults)


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspection_kind": "PORT_STATE_CONTROL",
        "sampled_at": DEFAULTS["SAMPLED_AT"],
        "sampled_by_role": "PSC_OFFICER",
        "indicator_organism_concentration": DEFAULTS["ORGANISM_CONCENTRATION"],
        "tss_mg_per_l": DEFAULTS["TSS_MG_PER_L"],
        "findings": [],
    }
    defaults.update(overrides)
    return defaults


def create_emissions_payload(**overrides) -> dict:
    defaults = {
        "fuel_type": DEFAULTS["FUEL_TYPE"],
        "sulfur_content_pct": DEFAULTS["SULFUR_CONTENT_PCT"],
        "consumed_volume_mt": DEFAULTS["CONSUMED_VOLUME_MT"],
        "inside_eca_hours": DEFAULTS["INSIDE_ECA_HOURS"],
        "outside_eca_hours": DEFAULTS["OUTSIDE_ECA_HOURS"],
        "scrubber_installed": False,
    }
    defaults.update(overrides)
    return defaults


def create_drill_payload(**overrides) -> dict:
    defaults = {
        "drill_kind": "MARPOL_AWARENESS",
        "scheduled_for": DEFAULTS["DRILL_SCHEDULED_FOR"],
        "attendees": ["CREW:Able", "CREW:Baker"],
    }
    defaults.update(overrides)
    return defaults


def create_record_book_payload(**overrides) -> dict:
    defaults = {"book_kind": "GARBAGE"}
    defaults.update(overrides)
    if defaults.get("voyage_id") is None:
        defaults.pop("voyage_id", None)
    return defaults


def create_record_book_entry_payload(**overrides) -> dict:
    defaults = {
        "entry_kind": "DISCHARGE_RECEPTION",
        "occurred_at": DEFAULTS["ENTRY_OCCURRED_AT"],
        "quantity": DEFAULTS["ENTRY_QUANTITY"],
        "signed_by": DEFAULTS["SIGNED_BY"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}
