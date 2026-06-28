"""Payload factories — one per entity, input fields only.

Only source: input fields appear here. System / computed fields (status,
posture, result_pci_l, quote_*_cents, version, ...) are server-managed and
never sent in a create payload.
"""

DEFAULTS = {
    "ADDRESS": "Test Radon Way",
    "FOUNDATION": "SLAB",
    "FLOOR_AREA_SQFT": 1400,
    "INSPECTOR_NAME": "Test Inspector",
    "CREW_NAME": "Test Crew",
}


def create_property_payload(**overrides) -> dict:
    """POST /properties. Required: address_line, foundation_type, floor_area_sqft.
    Optional: is_real_estate_transaction (default false), closing_deadline_utc."""
    defaults = {
        "address_line": DEFAULTS["ADDRESS"],
        "foundation_type": DEFAULTS["FOUNDATION"],
        "floor_area_sqft": DEFAULTS["FLOOR_AREA_SQFT"],
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    """POST /inspectors. Required: full_name, nrpp_license_id."""
    defaults = {
        "full_name": DEFAULTS["INSPECTOR_NAME"],
        "nrpp_license_id": "NRPP-DEFAULT",
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    """POST /crews. Required: crew_name. Optional: max_jobs_per_day (default 2)."""
    defaults = {
        "crew_name": DEFAULTS["CREW_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_radon_test_payload(property_id: str, inspector_id: str,
                              test_kind: str = "SHORT_TERM_48HR",
                              **overrides) -> dict:
    """POST /radon-tests. Required: property_id, inspector_id, test_kind.
    Optional: purpose (default INITIAL), mitigation_job_id, placement_window_hours
    (default 48), warmup_hours_dropped (default 4)."""
    defaults = {
        "property_id": property_id,
        "inspector_id": inspector_id,
        "test_kind": test_kind,
        "purpose": "INITIAL",
        "placement_window_hours": 48,
    }
    defaults.update(overrides)
    return defaults


def retrieve_short_term_payload(lab_integrated_pci_l: float) -> dict:
    """POST /radon-tests/{id}/retrieve for a SHORT_TERM_48HR test."""
    return {"lab_integrated_pci_l": lab_integrated_pci_l}


def retrieve_continuous_payload(hourly_readings: list) -> dict:
    """POST /radon-tests/{id}/retrieve for a CONTINUOUS_MONITOR test."""
    return {"hourly_readings": hourly_readings}


def create_mitigation_job_payload(property_id: str, triggering_test_id: str,
                                  **overrides) -> dict:
    """POST /mitigation-jobs. Required: property_id, triggering_test_id.
    Optional: system_design, num_suction_points (default 1), has_sump_pump
    (default false), is_rush (default false), warranty_term_days (default 1825),
    warranty_guarantee_ceiling_pci_l (default 2.0), warranty_refund_method
    (default STRAIGHT_LINE), retest_interval_days (default 730)."""
    defaults = {
        "property_id": property_id,
        "triggering_test_id": triggering_test_id,
    }
    defaults.update(overrides)
    return defaults


def schedule_payload(crew_id: str, install_start_utc: str, install_end_utc: str,
                     expected_property_version: int) -> dict:
    """POST /mitigation-jobs/{id}/schedule."""
    return {
        "crew_id": crew_id,
        "install_start_utc": install_start_utc,
        "install_end_utc": install_end_utc,
        "expected_property_version": expected_property_version,
    }


def create_payment_payload(mitigation_job_id: str, kind: str,
                           amount_cents: int) -> dict:
    """POST /payment-records. Required: mitigation_job_id, kind, amount_cents."""
    return {
        "mitigation_job_id": mitigation_job_id,
        "kind": kind,
        "amount_cents": amount_cents,
    }


def create_permit_payload(mitigation_job_id: str, jurisdiction_code: str,
                          permit_number: str) -> dict:
    """POST /permits. Required: mitigation_job_id, jurisdiction_code, permit_number."""
    return {
        "mitigation_job_id": mitigation_job_id,
        "jurisdiction_code": jurisdiction_code,
        "permit_number": permit_number,
    }


def cancel_warranty_payload(expected_warranty_version: int) -> dict:
    """POST /warranties/{id}/cancel."""
    return {"expected_warranty_version": expected_warranty_version}
