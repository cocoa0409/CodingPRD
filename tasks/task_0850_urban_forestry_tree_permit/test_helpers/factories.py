"""Payload factories — one per input-bearing entity, input fields only."""

DEFAULTS = {
    "ZONE_NAME": "Test Zone",
    "TARGET_CANOPY_PCT": 30.0,
    "AREA_SQM": 100,
    "SPECIES_NAME": "Oak",
    "MATURE_CANOPY_SQM": 50.0,
    "BASE_REPLACEMENT_VALUE_DOLLARS": 187.50,
    "BASE_APPRAISAL_VALUE_PER_SQIN": 27.00,
    "MIN_SPACING_M": 5.0,
    "DBH_INCHES": 20.0,
    "CANOPY_RADIUS_M": 6.0,
    "LATITUDE": 40.0,
    "LONGITUDE": -83.0,
    "CONDITION_CLASS": "GOOD",
    "LICENSE_EXPIRY": "2027-01-01T00:00:00Z",
}


def create_zone_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ZONE_NAME"],
        "target_canopy_pct": DEFAULTS["TARGET_CANOPY_PCT"],
        "area_sqm": DEFAULTS["AREA_SQM"],
    }
    payload.update(overrides)
    return payload


def create_species_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SPECIES_NAME"],
        "is_protected_species": False,
        "is_native": True,
        "mature_canopy_sqm": DEFAULTS["MATURE_CANOPY_SQM"],
        "base_replacement_value_dollars": DEFAULTS["BASE_REPLACEMENT_VALUE_DOLLARS"],
        "base_appraisal_value_per_sqin": DEFAULTS["BASE_APPRAISAL_VALUE_PER_SQIN"],
        "min_spacing_m": DEFAULTS["MIN_SPACING_M"],
    }
    payload.update(overrides)
    return payload


def create_tree_payload(zone_id: str, species_id: str, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "species_id": species_id,
        "dbh_inches": DEFAULTS["DBH_INCHES"],
        "canopy_radius_m": DEFAULTS["CANOPY_RADIUS_M"],
        "latitude": DEFAULTS["LATITUDE"],
        "longitude": DEFAULTS["LONGITUDE"],
        "condition_class": DEFAULTS["CONDITION_CLASS"],
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(expected_tree_version: int, **overrides) -> dict:
    payload = {
        "expected_tree_version": expected_tree_version,
        "inspection_type": "RISK",
        "likelihood_score": 1,
        "consequence_score": 1,
        "target_rating": 1,
    }
    payload.update(overrides)
    return payload


def create_permit_payload(tree_id: str, **overrides) -> dict:
    payload = {
        "tree_id": tree_id,
        "permit_type": "REMOVAL",
        "reason": "decay",
    }
    payload.update(overrides)
    return payload


def create_contractor_payload(**overrides) -> dict:
    payload = {
        "name": "Acme Tree",
        "license_number": "L-1",
        "license_expiry": DEFAULTS["LICENSE_EXPIRY"],
        "is_certified_arborist": True,
    }
    payload.update(overrides)
    return payload


def create_storm_event_payload(affected_zone_id: str, **overrides) -> dict:
    payload = {
        "affected_zone_id": affected_zone_id,
        "severity": "MAJOR",
        "window_start": "2026-02-15T00:00:00Z",
        "window_end": "2026-04-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(tree_id: str, contractor_id: str, work_type: str,
                              scheduled_start: str, scheduled_end: str,
                              permit_id: str = None, **overrides) -> dict:
    payload = {
        "tree_id": tree_id,
        "contractor_id": contractor_id,
        "work_type": work_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    if permit_id is not None:
        payload["permit_id"] = permit_id
    payload.update(overrides)
    return payload


def create_dig_ticket_payload(**overrides) -> dict:
    payload = {
        "ticket_number": "811-1",
        "valid_from": "2026-03-01T00:00:00Z",
        "valid_to": "2026-03-02T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def review_payload(decision: str, mitigation_method: str = None,
                   review_notes: str = "ok") -> dict:
    payload = {"decision": decision, "review_notes": review_notes}
    if mitigation_method is not None:
        payload["mitigation_method"] = mitigation_method
    return payload


def pay_fee_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}
