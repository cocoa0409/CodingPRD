"""Request-payload builders.

Each builder produces a valid body for one endpoint using the PRD's field names,
and accepts keyword overrides so a test can perturb exactly one field. Optional
fields are omitted unless supplied, so default-value tests can observe the
server applying the PRD's stated defaults.
"""

from typing import Optional


def _merge(payload: dict, overrides: dict) -> dict:
    """Apply overrides; a value of ``None`` removes the key entirely."""
    out = dict(payload)
    for key, value in overrides.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


# ─── MachineModel ─────────────────────────────────────────────────────────
def machine_model_payload(
    model_code: str = "OPL-60-A",
    product_line: str = "ON_PREMISES",
    capacity_rating_lb: int = 60,
    rated_water_gal_per_cwt: float = 1.10,
    rated_kwh_per_cwt: float = 0.42,
    drum_alloy_grade: str = "AISI_304",
    payment_module_options: Optional[list] = None,
    list_price_cents: int = 1250000,
    **overrides,
) -> dict:
    """A model registration body. max_rework_cycles and min_first_pass_yield_pct
    are optional and are only sent when passed as overrides."""
    payload = {
        "model_code": model_code,
        "product_line": product_line,
        "capacity_rating_lb": capacity_rating_lb,
        "rated_water_gal_per_cwt": rated_water_gal_per_cwt,
        "rated_kwh_per_cwt": rated_kwh_per_cwt,
        "drum_alloy_grade": drum_alloy_grade,
        "payment_module_options": (
            [] if payment_module_options is None else payment_module_options
        ),
        "list_price_cents": list_price_cents,
    }
    return _merge(payload, overrides)


def vended_model_payload(**overrides) -> dict:
    """VENDED models must offer at least one payment module."""
    base = machine_model_payload(
        model_code="VND-40-C",
        product_line="VENDED",
        capacity_rating_lb=40,
        rated_water_gal_per_cwt=0.95,
        rated_kwh_per_cwt=0.38,
        drum_alloy_grade="AISI_316",
        payment_module_options=["COIN", "CARD", "MOBILE"],
        list_price_cents=780000,
    )
    return _merge(base, overrides)


def tunnel_model_payload(**overrides) -> dict:
    base = machine_model_payload(
        model_code="TNL-350-T",
        product_line="INDUSTRIAL_TUNNEL",
        capacity_rating_lb=350,
        rated_water_gal_per_cwt=0.90,
        rated_kwh_per_cwt=0.35,
        drum_alloy_grade="DUPLEX_2205",
        payment_module_options=[],
        list_price_cents=9800000,
    )
    return _merge(base, overrides)


def lifecycle_action_payload(action: str = "RELEASE", **overrides) -> dict:
    return _merge({"action": action}, overrides)


# ─── RebateProgram ────────────────────────────────────────────────────────
def rebate_program_payload(
    program_code: str = "UTIL-A-W1",
    utility_code: str = "UTIL-A",
    program_class: str = "COMBINED",
    eligible_product_lines: Optional[list] = None,
    max_water_gal_per_cwt: float = 1.05,
    max_kwh_per_cwt: float = 0.45,
    min_capacity_rating_lb: int = 40,
    rebate_base_cents: int = 60000,
    capacity_bonus_cents_per_10lb: int = 5000,
    rebate_cap_cents: int = 90000,
    effective_from: str = "2026-07-01T00:00:00Z",
    effective_to: str = "2026-12-31T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "program_code": program_code,
        "utility_code": utility_code,
        "program_class": program_class,
        "eligible_product_lines": (
            ["ON_PREMISES", "VENDED", "INDUSTRIAL_TUNNEL"]
            if eligible_product_lines is None
            else eligible_product_lines
        ),
        "max_water_gal_per_cwt": max_water_gal_per_cwt,
        "max_kwh_per_cwt": max_kwh_per_cwt,
        "min_capacity_rating_lb": min_capacity_rating_lb,
        "rebate_base_cents": rebate_base_cents,
        "capacity_bonus_cents_per_10lb": capacity_bonus_cents_per_10lb,
        "rebate_cap_cents": rebate_cap_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    return _merge(payload, overrides)


# ─── CertificationDossier ─────────────────────────────────────────────────
def dossier_payload(
    measured_water_gal_per_cwt: float = 1.05,
    measured_kwh_per_cwt: float = 0.40,
    test_cycle_count: int = 120,
    **overrides,
) -> dict:
    payload = {
        "measured_water_gal_per_cwt": measured_water_gal_per_cwt,
        "measured_kwh_per_cwt": measured_kwh_per_cwt,
        "test_cycle_count": test_cycle_count,
    }
    return _merge(payload, overrides)


def review_payload(dimension: str, decision: str = "APPROVE", **overrides) -> dict:
    return _merge({"dimension": dimension, "decision": decision}, overrides)


def resurvey_payload(
    measured_water_gal_per_cwt: float = 1.02,
    measured_kwh_per_cwt: float = 0.38,
    test_cycle_count: int = 150,
    **overrides,
) -> dict:
    payload = {
        "measured_water_gal_per_cwt": measured_water_gal_per_cwt,
        "measured_kwh_per_cwt": measured_kwh_per_cwt,
        "test_cycle_count": test_cycle_count,
    }
    return _merge(payload, overrides)


# ─── ServicePart ──────────────────────────────────────────────────────────
def service_part_payload(
    part_number: str = "BRG-2040",
    component_class: str = "BEARING",
    fits_product_lines: Optional[list] = None,
    fits_min_capacity_lb: int = 20,
    fits_max_capacity_lb: int = 80,
    rated_duty_cycles: int = 30000,
    warranty_months: int = 36,
    unit_price_cents: int = 42000,
    requires_cert_scope: str = "DIAGNOSTICS_TOOL",
    reorder_point_qty: int = 2,
    **overrides,
) -> dict:
    payload = {
        "part_number": part_number,
        "component_class": component_class,
        "fits_product_lines": (
            ["ON_PREMISES", "VENDED"]
            if fits_product_lines is None
            else fits_product_lines
        ),
        "fits_min_capacity_lb": fits_min_capacity_lb,
        "fits_max_capacity_lb": fits_max_capacity_lb,
        "rated_duty_cycles": rated_duty_cycles,
        "warranty_months": warranty_months,
        "unit_price_cents": unit_price_cents,
        "requires_cert_scope": requires_cert_scope,
        "reorder_point_qty": reorder_point_qty,
    }
    return _merge(payload, overrides)


def stock_adjustment_payload(delta_qty: int, reason: str = "RECEIPT", **overrides) -> dict:
    return _merge({"delta_qty": delta_qty, "reason": reason}, overrides)


# ─── AssemblyStation ──────────────────────────────────────────────────────
def assembly_station_payload(
    station_code: str = "DRUM-01",
    station_type: str = "DRUM_FAB",
    parallel_capacity: int = 1,
    changeover_buffer_minutes: int = 30,
    supported_product_lines: Optional[list] = None,
    **overrides,
) -> dict:
    """station_state is optional and defaults to OPEN when omitted."""
    payload = {
        "station_code": station_code,
        "station_type": station_type,
        "parallel_capacity": parallel_capacity,
        "changeover_buffer_minutes": changeover_buffer_minutes,
        "supported_product_lines": (
            ["ON_PREMISES", "VENDED"]
            if supported_product_lines is None
            else supported_product_lines
        ),
    }
    return _merge(payload, overrides)


# ─── Technician ───────────────────────────────────────────────────────────
def technician_payload(
    employee_code: str = "T-100",
    full_name: str = "Ann Ito",
    employer: str = "FACTORY",
    **overrides,
) -> dict:
    """distributor_id is required when employer is DISTRIBUTOR and must be
    absent when employer is FACTORY, so it is only sent as an override."""
    payload = {
        "employee_code": employee_code,
        "full_name": full_name,
        "employer": employer,
    }
    return _merge(payload, overrides)


def grant_payload(
    scopes: Optional[list] = None,
    expires_on: str = "2027-06-30T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "action": "GRANT",
        "scopes": ["DRUM_FAB"] if scopes is None else scopes,
        "expires_on": expires_on,
    }
    return _merge(payload, overrides)


def renew_payload(
    scopes: Optional[list] = None,
    expires_on: str = "2028-06-30T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "action": "RENEW",
        "scopes": ["DRUM_FAB"] if scopes is None else scopes,
        "expires_on": expires_on,
    }
    return _merge(payload, overrides)


def revoke_payload(reason: str = "CALIBRATION_AUDIT_FAILURE", **overrides) -> dict:
    return _merge({"action": "REVOKE", "reason": reason}, overrides)


# ─── BuildOrder and StationLog ────────────────────────────────────────────
def build_order_payload(
    model_id: str,
    serial_number: str = "SN-0001",
    planned_start_at: str = "2026-08-01T07:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "model_id": model_id,
        "serial_number": serial_number,
        "planned_start_at": planned_start_at,
    }
    return _merge(payload, overrides)


def station_log_payload(
    station_id: str,
    station_type: str,
    started_at: str,
    completed_at: str,
    outcome: str = "PASS",
    **overrides,
) -> dict:
    """bearing_preload_micron is required for BEARING_INSTALL and must be absent
    otherwise; defect_code is required when outcome is FAIL. Both are overrides."""
    payload = {
        "station_id": station_id,
        "station_type": station_type,
        "started_at": started_at,
        "completed_at": completed_at,
        "outcome": outcome,
    }
    return _merge(payload, overrides)


def qa_signoff_payload(decision: str = "APPROVE", **overrides) -> dict:
    """defect_code is required for REJECT."""
    return _merge({"decision": decision}, overrides)


# ─── Distributor ──────────────────────────────────────────────────────────
def distributor_payload(
    distributor_code: str = "D-01",
    legal_name: str = "Bay Laundry Supply",
    territory_code: str = "TX-CENTRAL",
    territory_exclusive: bool = True,
    **overrides,
) -> dict:
    payload = {
        "distributor_code": distributor_code,
        "legal_name": legal_name,
        "territory_code": territory_code,
        "territory_exclusive": territory_exclusive,
    }
    return _merge(payload, overrides)


def training_completion_payload(
    technician_id: str,
    training_module: str = "INSTALLATION",
    completed_on: str = "2026-07-20",
    **overrides,
) -> dict:
    payload = {
        "technician_id": technician_id,
        "training_module": training_module,
        "completed_on": completed_on,
    }
    return _merge(payload, overrides)


def status_action_payload(action: str, **overrides) -> dict:
    """reason is required for PROBATION and TERMINATE."""
    return _merge({"action": action}, overrides)


# ─── PackageQuote and QuoteLine ───────────────────────────────────────────
def quote_payload(
    distributor_id: str,
    customer_name: str = "Sudz Express",
    laundromat_site_code: str = "SITE-77",
    stated_credit_score: int = 715,
    financing_program: str = "TERM_60",
    down_payment_cents: int = 0,
    package_discount_pct: float = 0.00,
    freight_cents: int = 0,
    **overrides,
) -> dict:
    payload = {
        "distributor_id": distributor_id,
        "customer_name": customer_name,
        "laundromat_site_code": laundromat_site_code,
        "stated_credit_score": stated_credit_score,
        "financing_program": financing_program,
        "down_payment_cents": down_payment_cents,
        "package_discount_pct": package_discount_pct,
        "freight_cents": freight_cents,
    }
    return _merge(payload, overrides)


def quote_line_payload(
    model_id: str,
    expected_quote_version,
    quantity: int = 1,
    payment_module: str = "NONE",
    line_discount_pct: float = 0.00,
    **overrides,
) -> dict:
    payload = {
        "model_id": model_id,
        "quantity": quantity,
        "payment_module": payment_module,
        "line_discount_pct": line_discount_pct,
        "expected_quote_version": expected_quote_version,
    }
    return _merge(payload, overrides)


def quote_decision_payload(decision: str, **overrides) -> dict:
    """verified_credit_score is required for APPROVE."""
    return _merge({"decision": decision}, overrides)


# ─── WarrantyClaim ────────────────────────────────────────────────────────
def warranty_claim_payload(
    build_order_id: str,
    part_id: str,
    distributor_id: str,
    reported_by_technician_id: str,
    failure_cycle_count: int = 8000,
    in_service_months: int = 8,
    duty_cycle_class: str = "STANDARD",
    diagnostics_code: str = "DX-BRG-07",
    **overrides,
) -> dict:
    payload = {
        "build_order_id": build_order_id,
        "part_id": part_id,
        "distributor_id": distributor_id,
        "reported_by_technician_id": reported_by_technician_id,
        "failure_cycle_count": failure_cycle_count,
        "in_service_months": in_service_months,
        "duty_cycle_class": duty_cycle_class,
        "diagnostics_code": diagnostics_code,
    }
    return _merge(payload, overrides)


def adjudicate_payload(
    expected_part_version, decision: str = "APPROVE", **overrides
) -> dict:
    """denial_reason is required for DENY."""
    payload = {"decision": decision, "expected_part_version": expected_part_version}
    return _merge(payload, overrides)


def void_payload(reason: str = "CUSTOMER_WITHDREW", **overrides) -> dict:
    return _merge({"reason": reason}, overrides)
