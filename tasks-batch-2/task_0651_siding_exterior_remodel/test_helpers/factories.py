"""Payload factories — one per entity, input fields only.

Each factory builds a sensible default payload and accepts **overrides so a
test can control exactly the fields it cares about.
"""
import itertools

_email_counter = itertools.count(1)


def _unique_email(prefix: str) -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


# ---- HomeownerClient ----
def create_client_payload(**overrides) -> dict:
    defaults = {
        "email": _unique_email("client"),
        "full_name": "Test Homeowner",
        "annual_income_cents": 12_000_000,
        "monthly_debt_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


# ---- StaffMember ----
def create_staff_payload(role_code="PROJECT_MANAGER", **overrides) -> dict:
    defaults = {
        "email": _unique_email("staff"),
        "full_name": "Test Staff",
        "role_code": role_code,
    }
    defaults.update(overrides)
    return defaults


# ---- Project ----
def create_project_payload(client_id, project_manager_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "project_manager_id": project_manager_id,
        "property_address": "1 Hardie Way",
    }
    defaults.update(overrides)
    return defaults


# ---- Measurement ----
def create_measurement_payload(estimator_id, **overrides) -> dict:
    defaults = {
        "estimator_id": estimator_id,
        "gross_wall_sqft": 1100,
        "opening_sqft": 100,
        "linear_trim_ft": 300,
        "color_code": "ARCTIC_WHITE_HZ10",
    }
    defaults.update(overrides)
    return defaults


# ---- Estimate ----
def create_estimate_payload(project_id, measurement_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "measurement_id": measurement_id,
        "waste_factor_pct": 0.10,
    }
    defaults.update(overrides)
    return defaults


# ---- EstimateLineItem ----
def create_line_item_payload(scope_kind="SIDING", quantity=1000, unit_price_cents=1000, **overrides) -> dict:
    defaults = {
        "scope_kind": scope_kind,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
    }
    defaults.update(overrides)
    return defaults


# ---- Permit ----
def create_permit_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "jurisdiction": "Austin",
    }
    defaults.update(overrides)
    return defaults


# ---- HOAApproval ----
def create_hoa_approval_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "reviewed_color_code": "ARCTIC_WHITE_HZ10",
    }
    defaults.update(overrides)
    return defaults


# ---- MaterialOrder ----
def create_material_order_payload(project_id, estimate_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "estimate_id": estimate_id,
    }
    defaults.update(overrides)
    return defaults


# ---- ChangeOrder ----
def create_change_order_payload(project_id, target_line_item_id, delta_cents=20000, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "target_line_item_id": target_line_item_id,
        "delta_cents": delta_cents,
    }
    defaults.update(overrides)
    return defaults


# ---- Crew ----
def create_crew_payload(name="Test Crew", **overrides) -> dict:
    defaults = {
        "name": name,
    }
    defaults.update(overrides)
    return defaults


# ---- WorkSchedule ----
def create_work_schedule_payload(crew_id, milestone="WRAP_INSTALL",
                                 window_start_iso="2026-04-20T08:00:00Z",
                                 window_end_iso="2026-04-20T17:00:00Z",
                                 forecast_wind_mph=10, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "milestone": milestone,
        "window_start_iso": window_start_iso,
        "window_end_iso": window_end_iso,
        "forecast_wind_mph": forecast_wind_mph,
    }
    defaults.update(overrides)
    return defaults


# ---- ProgressDraw ----
def create_progress_draw_payload(work_schedule_id, milestone_pct=0.30, **overrides) -> dict:
    defaults = {
        "work_schedule_id": work_schedule_id,
        "milestone_pct": milestone_pct,
    }
    defaults.update(overrides)
    return defaults


# ---- FinancingApplication ----
def create_financing_application_payload(project_id, client_id,
                                        requested_amount_cents=1_000_000,
                                        term_months=120, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "client_id": client_id,
        "requested_amount_cents": requested_amount_cents,
        "term_months": term_months,
    }
    defaults.update(overrides)
    return defaults
