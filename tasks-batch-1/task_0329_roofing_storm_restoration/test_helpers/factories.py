"""Payload factories — one per entity, input fields only.

Each factory returns a dict of client-supplied (source: input) fields with
sensible PRD-consistent defaults. Pass **overrides to control specific values.
Computed and system fields are never included.
"""


def create_estimator_payload(**overrides) -> dict:
    defaults = {"name": "Ann Est", "license_no": "TX-1001"}
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    # name required; max_squares_per_day and active are optional (PRD §3.6).
    defaults = {"name": "Crew Alpha"}
    defaults.update(overrides)
    return defaults


def create_job_payload(**overrides) -> dict:
    # insurance_carrier and retainage_pct optional (PRD §3.1, §2.6).
    defaults = {
        "customer_name": "Homer R",
        "property_address": "1 Oak St",
        "peril": "HAIL",
        "assigned_estimator_id": None,  # caller must supply a real estimator id
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    # permit_id required only for PERMIT_FINAL (PRD §3.1).
    defaults = {
        "job_id": None,
        "kind": "DAMAGE_ASSESSMENT",
        "scheduled_start": "2026-03-01T08:00:00Z",
        "scheduled_end": "2026-03-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_inspection_payload(**overrides) -> dict:
    # outcome required; damage_severity required only for DAMAGE_ASSESSMENT PASS.
    defaults = {"outcome": "PASS"}
    defaults.update(overrides)
    return defaults


def create_estimate_payload(**overrides) -> dict:
    # aerial_contingency_pct optional (PRD §3.2).
    defaults = {"job_id": None, "source_kind": "FIELD"}
    defaults.update(overrides)
    return defaults


def create_line_item_payload(**overrides) -> dict:
    # waste_factor_pct and expected_estimate_version optional (PRD §3.2).
    defaults = {
        "trade": "SHINGLE",
        "squares": 10,
        "unit_price_cents": 10_000,
    }
    defaults.update(overrides)
    return defaults


def create_material_order_payload(**overrides) -> dict:
    defaults = {"job_id": None}
    defaults.update(overrides)
    return defaults


def deliver_material_order_payload(**overrides) -> dict:
    # delivered_short optional (PRD §3.4).
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(**overrides) -> dict:
    defaults = {
        "job_id": None,
        "crew_id": None,
        "window_start": "2026-07-01T08:00:00Z",
        "window_end": "2026-07-01T16:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {"job_id": None, "municipality": "Dallas"}
    defaults.update(overrides)
    return defaults


def issue_permit_payload(**overrides) -> dict:
    defaults = {"permit_number": "P-0001"}
    defaults.update(overrides)
    return defaults


def create_draw_payload(**overrides) -> dict:
    defaults = {
        "job_id": None,
        "cumulative_pct": 0.5,
        "expected_job_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(**overrides) -> dict:
    # extra_shingle_squares optional, defaults to 0 (PRD §3.8).
    defaults = {"job_id": None, "reason": "scope change", "delta_cents": 50_000}
    defaults.update(overrides)
    return defaults


def apply_change_order_payload(**overrides) -> dict:
    defaults = {"expected_job_version": None}
    defaults.update(overrides)
    return defaults


def create_warranty_payload(**overrides) -> dict:
    # term_months optional, defaults to 120 (PRD §3.10).
    defaults = {"job_id": None, "premium_cents": 120_000}
    defaults.update(overrides)
    return defaults


def cancel_warranty_payload(**overrides) -> dict:
    defaults = {"cancel_basis": "PRORATED"}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
