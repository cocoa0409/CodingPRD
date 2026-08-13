"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "VESSEL_NAME": "MV Test",
    "OWNER_NAME": "O T",
    "OWNER_USER_ID": "owner-1",
    "LOA_FT": 40,
    "BEAM_FT": 13,
    "HULL_TYPE": "POWER",
    "DISPLACEMENT_TONS": 20,
    "CERT_PROVIDER": "P",
    "CERT_POLICY_NO": "POL-1",
    "CERT_COVERAGE_CENTS": 200000000,
    "CERT_EFFECTIVE_DATE": "2026-01-01",
    "CERT_EXPIRY_DATE": "2027-06-01",
    "ROW_CODE": "A",
    "TOTAL_STANDS": 10,
    "STANDS_USED": 4,
    "STAND_START_DATE": "2026-08-02",
    "STAND_END_DATE": "2026-09-30",
    "WO_TYPE": "MECHANICAL",
    "WO_DESCRIPTION": "Engine service",
    "WO_QUOTED_HOURS": 10,
    "WO_QUOTED_RATE_CENTS": 8000,
    "WO_QUOTED_PARTS_CENTS": 5000,
    "LABOR_WORKER_TYPE": "YARD_CREW",
    "LABOR_HOURS": 5,
    "LABOR_RATE_CENTS": 8000,
    "PART_DESCRIPTION": "Filter",
    "PART_CATEGORY": "MECHANICAL",
    "PART_DECLARED_VALUE_CENTS": 50000,
    "EVENT_KIND": "SANDING",
    "EVENT_PPM": 150.0,
    "HOLD_KIND": "PAYMENT",
    "HOLD_NOTE": "Invoice dispute",
    "LEDGER_KIND": "DEPOSIT",
    "LEDGER_AMOUNT_CENTS": 21250,
}


def create_vessel_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VESSEL_NAME"],
        "owner_name": DEFAULTS["OWNER_NAME"],
        "owner_user_id": DEFAULTS["OWNER_USER_ID"],
        "loa_ft": DEFAULTS["LOA_FT"],
        "beam_ft": DEFAULTS["BEAM_FT"],
        "hull_type": DEFAULTS["HULL_TYPE"],
        "displacement_tons": DEFAULTS["DISPLACEMENT_TONS"],
    }
    defaults.update(overrides)
    return defaults


def create_insurance_certificate_payload(vessel_id, **overrides) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "provider": DEFAULTS["CERT_PROVIDER"],
        "policy_no": DEFAULTS["CERT_POLICY_NO"],
        "liability_coverage_cents": DEFAULTS["CERT_COVERAGE_CENTS"],
        "effective_date": DEFAULTS["CERT_EFFECTIVE_DATE"],
        "expiry_date": DEFAULTS["CERT_EXPIRY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_refit_job_payload(vessel_id, **overrides) -> dict:
    defaults = {"vessel_id": vessel_id}
    defaults.update(overrides)
    return defaults


def create_lift_slot_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "kind": "HAUL_OUT",
        "scheduled_start": "2026-08-02T08:00:00Z",
        "scheduled_end": "2026-08-02T09:00:00Z",
        "vessel_displacement_tons": DEFAULTS["DISPLACEMENT_TONS"],
    }
    defaults.update(overrides)
    return defaults


def create_yard_row_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["ROW_CODE"],
        "total_stands": DEFAULTS["TOTAL_STANDS"],
    }
    defaults.update(overrides)
    return defaults


def create_stand_assignment_payload(row_id, job_id,
                                    expected_yard_row_version,
                                    **overrides) -> dict:
    defaults = {
        "row_id": row_id,
        "job_id": job_id,
        "stands_used": DEFAULTS["STANDS_USED"],
        "start_date": DEFAULTS["STAND_START_DATE"],
        "end_date": DEFAULTS["STAND_END_DATE"],
        "expected_yard_row_version": expected_yard_row_version,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "type": DEFAULTS["WO_TYPE"],
        "description": DEFAULTS["WO_DESCRIPTION"],
        "quoted_hours": DEFAULTS["WO_QUOTED_HOURS"],
        "quoted_rate_cents": DEFAULTS["WO_QUOTED_RATE_CENTS"],
        "quoted_parts_cents": DEFAULTS["WO_QUOTED_PARTS_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_labor_entry_payload(work_order_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "worker_type": DEFAULTS["LABOR_WORKER_TYPE"],
        "hours": DEFAULTS["LABOR_HOURS"],
        "rate_cents": DEFAULTS["LABOR_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "description": DEFAULTS["PART_DESCRIPTION"],
        "category": DEFAULTS["PART_CATEGORY"],
        "owner_supplied": False,
        "declared_value_cents": DEFAULTS["PART_DECLARED_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_environmental_event_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "kind": DEFAULTS["EVENT_KIND"],
        "containment_used": True,
        "runoff_tss_ppm": DEFAULTS["EVENT_PPM"],
    }
    defaults.update(overrides)
    return defaults


def create_compliance_hold_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "kind": DEFAULTS["HOLD_KIND"],
        "note": DEFAULTS["HOLD_NOTE"],
    }
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "kind": DEFAULTS["LEDGER_KIND"],
        "amount_cents": DEFAULTS["LEDGER_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults
