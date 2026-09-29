"""Request-body builders.

Each builder returns a fresh dict of the fields the endpoint declares, with
canonical values chosen so the defaults alone produce a valid row. Keyword
overrides replace a field; passing ``OMIT`` deletes it, which is how a test
exercises an absent optional or an absent required field.
"""

from .types import (
    CaseDecision,
    ComplexityTier,
    ConditionStatus,
    DrawingDecision,
    FinishGrade,
    InteractiveKind,
    MaterialClass,
    MaterialDecision,
    OddyResult,
    PackageStage,
    Phase,
    SecurityTier,
    UsedIn,
    WindowDecision,
    WorkClass,
    Severity,
)

OMIT = object()

OBJECTIVE_PRIMARY = "OBJ-RIVER"
OBJECTIVE_SECONDARY = "OBJ-STRATA"


def _merge(base, overrides):
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not OMIT}


def project_payload(**overrides):
    return _merge(
        {
            "name": "Delta Waters Permanent Gallery",
            "museum_name": "Riverbend Museum of Natural History",
            "storyline_title": "Where the River Remembers",
            "objective_codes": [OBJECTIVE_PRIMARY, OBJECTIVE_SECONDARY],
            "target_open_date": "2027-03-01T09:00:00Z",
            "contract_value_cents": 9000000,
        },
        overrides,
    )


def advance_phase_payload(to_phase=Phase.SCHEMATIC, **overrides):
    return _merge({"to_phase": to_phase}, overrides)


def closeout_payload(**overrides):
    return _merge(
        {
            "docent_kit_url": "https://files.riverbend.example/docent-kit.pdf",
            "maintenance_manual_url": "https://files.riverbend.example/maintenance.pdf",
            "parts_commitment_years": 10,
        },
        overrides,
    )


def design_package_payload(expected_project_version, **overrides):
    return _merge(
        {
            "expected_project_version": expected_project_version,
            "stage": PackageStage.SCHEMATIC,
            "egress_clear_width_cm": 120.0,
            "wheelchair_turning_radius_cm": 90.0,
            "peak_visitors_per_hour": 200,
            "circulation_area_sqm": 130.0,
        },
        overrides,
    )


def review_round_payload(panel_roles=None, decision_deadline_at="2026-08-20T08:00:00Z", **overrides):
    if panel_roles is None:
        panel_roles = ["Curator", "Conservator", "FabricationLead"]
    return _merge(
        {"panel_roles": list(panel_roles), "decision_deadline_at": decision_deadline_at},
        overrides,
    )


def vote_payload(decision, **overrides):
    return _merge({"decision": decision}, overrides)


def gallery_zone_payload(**overrides):
    return _merge(
        {
            "zone_code": "Z-A",
            "visitor_route_order": 1,
            "max_noise_dba": 85.0,
            "case_slot_capacity": 2,
        },
        overrides,
    )


def artifact_payload(**overrides):
    return _merge(
        {
            "accession_number": "2019.14.3",
            "material_class": MaterialClass.ORGANIC,
            "required_rh_min_pct": 45.0,
            "required_rh_max_pct": 55.0,
            "max_lux": 50.0,
            "security_class": SecurityTier.BASIC,
            "condition_status": ConditionStatus.STABLE,
        },
        overrides,
    )


def artifact_case_payload(zone_id, **overrides):
    return _merge(
        {
            "zone_id": zone_id,
            "case_code": "C-01",
            "objective_code": OBJECTIVE_PRIMARY,
            "security_tier": SecurityTier.ENHANCED,
            "target_rh_pct": 50.0,
            "rh_tolerance_pct": 5.0,
            "target_lux": 50.0,
            "uv_microwatt_per_lumen": 40.0,
            "interior_l_cm": 120.0,
            "interior_w_cm": 60.0,
            "interior_h_cm": 90.0,
            "air_exchanges_per_day": 0.4,
        },
        overrides,
    )


def placement_payload(artifact_id, expected_case_version, **overrides):
    return _merge(
        {"expected_case_version": expected_case_version, "artifact_id": artifact_id},
        overrides,
    )


def case_decision_payload(decision=CaseDecision.APPROVE, **overrides):
    return _merge({"decision": decision}, overrides)


def mount_advance_payload(to_mount_status, **overrides):
    return _merge({"to_mount_status": to_mount_status}, overrides)


def interactive_payload(**overrides):
    return _merge(
        {
            "code": "INT-STRATA",
            "kind": InteractiveKind.TOUCHSCREEN,
            "objective_code": OBJECTIVE_SECONDARY,
            "expected_daily_uses": 100,
            "duty_hours_per_day": 6.0,
            "mtbf_cycles": 800000,
            "parts_availability_years": 10,
            "warranty_months": 24,
        },
        overrides,
    )


def prototype_payload(measured_daily_uses=60, measured_mtbf_cycles=1500000, **overrides):
    return _merge(
        {
            "measured_daily_uses": measured_daily_uses,
            "measured_mtbf_cycles": measured_mtbf_cycles,
        },
        overrides,
    )


def prototype_decision_payload(decision, **overrides):
    return _merge({"decision": decision}, overrides)


def commission_payload(**overrides):
    return _merge({}, overrides)


def material_spec_payload(**overrides):
    return _merge(
        {
            "material_name": "Marmoleum Conservation Board",
            "used_in": UsedIn.CASE_INTERIOR,
            "oddy_test_result": OddyResult.PASS,
            "voc_mg_per_m2_day": 0.02,
            "formaldehyde_ppm": 0.01,
            "cure_days": 30,
        },
        overrides,
    )


def material_decision_payload(decision=MaterialDecision.APPROVE, **overrides):
    return _merge({"decision": decision}, overrides)


def shop_drawing_payload(project_id, material_spec_id, **overrides):
    return _merge(
        {
            "project_id": project_id,
            "material_spec_id": material_spec_id,
            "drawing_number": "SD-601",
            "complexity_tier": ComplexityTier.STANDARD,
            "shop_hours": 10.0,
            "material_area_m2": 1.0,
            "finish_grade": FinishGrade.MILL,
        },
        overrides,
    )


def drawing_decision_payload(decision=DrawingDecision.APPROVE, **overrides):
    base = {"decision": decision}
    if decision in (DrawingDecision.APPROVE, DrawingDecision.APPROVE_AS_NOTED):
        base["actual_shop_hours"] = 10.0
        base["actual_waste_factor"] = 1.20
    return _merge(base, overrides)


def void_payload(void_reason="Sheet withdrawn by the fabrication lead", **overrides):
    return _merge({"void_reason": void_reason}, overrides)


def install_window_payload(project_id, zone_id, **overrides):
    return _merge(
        {
            "project_id": project_id,
            "zone_id": zone_id,
            "work_class": WorkClass.QUIET,
            "noise_dba": 50.0,
            "starts_at": "2026-09-10T09:00:00Z",
            "ends_at": "2026-09-10T12:00:00Z",
        },
        overrides,
    )


def window_decision_payload(decision=WindowDecision.APPROVE, **overrides):
    return _merge({"decision": decision}, overrides)


def punch_item_payload(**overrides):
    return _merge(
        {"severity": Severity.MAJOR, "description": "Graphic panel edge lifting"},
        overrides,
    )


def verify_payload(verification_note="Edge re-bonded and inspected", **overrides):
    return _merge({"verification_note": verification_note}, overrides)


def waive_payload(waiver_reason="Cosmetic only; accepted by the museum", **overrides):
    return _merge({"waiver_reason": waiver_reason}, overrides)
