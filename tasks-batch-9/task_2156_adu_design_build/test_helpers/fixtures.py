"""Composite setup helpers.

Every test starts against an empty database, so each helper builds the whole
precondition chain from scratch through PRD-declared endpoints only. All setup
calls use the lenient get_success_data() validator so a broken precondition
surfaces as a clear setup failure rather than a confusing assertion.

Identity threading: the Homeowner acts with X-User-ID equal to the parcel id and
the BuildingInspector with X-User-ID equal to the inspector id, so ownership-gated
calls always go through make_homeowner_headers() / make_building_inspector_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    jurisdiction_payload, snvl_jurisdiction_payload, inspector_payload,
    property_payload, occupied_property_payload, adu_project_payload,
    large_adu_project_payload, feasibility_screening_payload, utility_connection_payload,
    permit_submittal_payload, financing_scenario_payload, change_order_payload,
    construction_phase_payload, inspection_appointment_payload,
)
from .test_users import (
    PLATFORM_ADMIN, DESIGN_LEAD, PLAN_CHECKER, PROJECT_MANAGER, FINANCE_ADVISOR,
    make_homeowner_headers, make_building_inspector_headers,
)


# ---------------------------------------------------------------------------
# Tier 0 — single-call primitives
# ---------------------------------------------------------------------------

def register_jurisdiction(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_jurisdiction(jurisdiction_payload(**overrides), PLATFORM_ADMIN))


def register_snvl_jurisdiction(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_jurisdiction(snvl_jurisdiction_payload(**overrides), PLATFORM_ADMIN))


def register_inspector(api, jurisdiction_id, **overrides) -> dict:
    return get_success_data(
        api.create_inspector(inspector_payload(jurisdiction_id, **overrides), PLATFORM_ADMIN))


def register_property(api, jurisdiction_id, **overrides) -> dict:
    return get_success_data(
        api.create_property(property_payload(jurisdiction_id, **overrides), DESIGN_LEAD))


def register_occupied_property(api, jurisdiction_id, **overrides) -> dict:
    return get_success_data(
        api.create_property(occupied_property_payload(jurisdiction_id, **overrides), DESIGN_LEAD))


def current_property_version(api, property_id) -> int:
    return get_success_data(api.get_property(property_id, DESIGN_LEAD))["version"]


def current_project_version(api, project_id) -> int:
    return get_success_data(api.get_adu_project(project_id, DESIGN_LEAD))["version"]


def read_project(api, project_id) -> dict:
    return get_success_data(api.get_adu_project(project_id, DESIGN_LEAD))


def open_project(api, property_id, **overrides) -> dict:
    version = current_property_version(api, property_id)
    return get_success_data(
        api.create_adu_project(adu_project_payload(property_id, version, **overrides), DESIGN_LEAD))


def open_large_project(api, property_id, **overrides) -> dict:
    version = current_property_version(api, property_id)
    return get_success_data(
        api.create_adu_project(
            large_adu_project_payload(property_id, version, **overrides), DESIGN_LEAD))


def run_screening(api, project_id, pathway="LOCAL_ORDINANCE") -> dict:
    return get_success_data(
        api.create_feasibility_screening(project_id, feasibility_screening_payload(pathway), DESIGN_LEAD))


def lock_pathway(api, project_id, screening_id) -> dict:
    return get_success_data(
        api.select_pathway(project_id, {"screening_id": screening_id}, DESIGN_LEAD))


def add_utility_connection(api, project_id, service_type="ELECTRIC") -> dict:
    return get_success_data(
        api.create_utility_connection(project_id, utility_connection_payload(service_type), DESIGN_LEAD))


def decide_utility_connection(api, utility_connection_id, override_decision=None) -> dict:
    payload = {} if override_decision is None else {"override_decision": override_decision}
    return get_success_data(api.decide_utility_connection(utility_connection_id, payload, DESIGN_LEAD))


def energize_utility_connection(api, utility_connection_id) -> dict:
    return get_success_data(api.energize_utility_connection(utility_connection_id, PROJECT_MANAGER))


def prepare_submittal(api, project_id, **overrides) -> dict:
    return get_success_data(
        api.create_permit_submittal(project_id, permit_submittal_payload(**overrides), DESIGN_LEAD))


def file_submittal(api, submittal_id) -> dict:
    return get_success_data(api.submit_permit_submittal(submittal_id, DESIGN_LEAD))


def approve_plan_check(api, submittal_id) -> dict:
    return get_success_data(
        api.record_plan_check_result(submittal_id, {"outcome": "APPROVED"}, PLAN_CHECKER))


def issue_corrections_letter(api, submittal_id, correction_items) -> dict:
    return get_success_data(api.record_plan_check_result(
        submittal_id,
        {"outcome": "CORRECTIONS_REQUIRED", "correction_items": correction_items},
        PLAN_CHECKER))


def list_corrections(api, submittal_id, params=None) -> list:
    return get_success_data(api.list_correction_items(submittal_id, DESIGN_LEAD, params))


def resolve_correction(api, correction_item_id) -> dict:
    return get_success_data(api.resolve_correction_item(correction_item_id, DESIGN_LEAD))


def move_clock(api, to_iso8601) -> dict:
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, PLATFORM_ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2 — project state progression
# ---------------------------------------------------------------------------

def setup_intake_project(api, jurisdiction_overrides=None, property_overrides=None,
                         project_overrides=None) -> dict:
    """Palmdale jurisdiction + unoccupied parcel P2 + project B in INTAKE."""
    jurisdiction = register_jurisdiction(api, **(jurisdiction_overrides or {}))
    parcel = register_property(api, jurisdiction["id"], **(property_overrides or {}))
    project = open_project(api, parcel["id"], **(project_overrides or {}))
    return {
        "jurisdiction": jurisdiction,
        "property": parcel,
        "project": project,
        "homeowner_headers": make_homeowner_headers(parcel["id"]),
    }


def setup_intake_project_on_occupied_parcel(api, jurisdiction_overrides=None,
                                            property_overrides=None,
                                            project_overrides=None) -> dict:
    """Sunnyvale jurisdiction + occupied parcel P1 + the 800 sqft project A in INTAKE."""
    jurisdiction = register_snvl_jurisdiction(api, **(jurisdiction_overrides or {}))
    parcel = register_occupied_property(api, jurisdiction["id"], **(property_overrides or {}))
    project = open_large_project(api, parcel["id"], **(project_overrides or {}))
    return {
        "jurisdiction": jurisdiction,
        "property": parcel,
        "project": project,
        "homeowner_headers": make_homeowner_headers(parcel["id"]),
    }


def setup_feasibility_cleared_project(api, pathway="LOCAL_ORDINANCE", occupied_parcel=False,
                                      jurisdiction_overrides=None, property_overrides=None,
                                      project_overrides=None) -> dict:
    """Project screened under `pathway` and locked onto it: status FEASIBILITY_CLEARED."""
    if occupied_parcel:
        ctx = setup_intake_project_on_occupied_parcel(
            api, jurisdiction_overrides, property_overrides, project_overrides)
    else:
        ctx = setup_intake_project(
            api, jurisdiction_overrides, property_overrides, project_overrides)
    screening = run_screening(api, ctx["project"]["id"], pathway)
    ctx["screening"] = screening
    ctx["project"] = lock_pathway(api, ctx["project"]["id"], screening["id"])
    return ctx


def setup_under_plan_check_project(api, pathway="LOCAL_ORDINANCE", occupied_parcel=False,
                                   service_type="ELECTRIC", submittal_overrides=None,
                                   **kwargs) -> dict:
    """Project with one decided utility record and a filed submittal: the submittal
    is UNDER_PLAN_CHECK and the project is PERMITTING."""
    ctx = setup_feasibility_cleared_project(
        api, pathway=pathway, occupied_parcel=occupied_parcel, **kwargs)
    if service_type:
        utility = add_utility_connection(api, ctx["project"]["id"], service_type)
        ctx["utility"] = decide_utility_connection(api, utility["id"])
    submittal = prepare_submittal(api, ctx["project"]["id"], **(submittal_overrides or {}))
    ctx["submittal"] = file_submittal(api, submittal["id"])
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return ctx


def setup_permitted_project(api, pathway="LOCAL_ORDINANCE", occupied_parcel=False,
                            service_type="ELECTRIC", submittal_overrides=None, **kwargs) -> dict:
    """Full design path through an APPROVED permit: project status PERMITTED."""
    ctx = setup_under_plan_check_project(
        api, pathway=pathway, occupied_parcel=occupied_parcel,
        service_type=service_type, submittal_overrides=submittal_overrides, **kwargs)
    ctx["submittal"] = approve_plan_check(api, ctx["submittal"]["id"])
    ctx["project"] = read_project(api, ctx["project"]["id"])
    if service_type:
        ctx["utility"] = get_success_data(
            api.list_utility_connections(ctx["project"]["id"], DESIGN_LEAD))[0]
    return ctx


def setup_corrections_round(api, correction_items=None, pathway="LOCAL_ORDINANCE",
                            service_type="ELECTRIC", **kwargs) -> dict:
    """Submittal bounced back with a corrections letter: the submittal is
    CORRECTIONS_REQUIRED and the project is DESIGN_REVISION."""
    items = correction_items or [
        {"discipline": "STRUCTURAL", "severity": "BLOCKING",
         "description": "Shear wall schedule missing on sheet S2"},
    ]
    ctx = setup_under_plan_check_project(
        api, pathway=pathway, service_type=service_type, **kwargs)
    ctx["submittal"] = issue_corrections_letter(api, ctx["submittal"]["id"], items)
    ctx["corrections"] = list_corrections(api, ctx["submittal"]["id"])
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — construction phases and inspections
# ---------------------------------------------------------------------------

def add_phase(api, project_id, **overrides) -> dict:
    return get_success_data(
        api.create_construction_phase(project_id, construction_phase_payload(**overrides),
                                      PROJECT_MANAGER))


def schedule_phase(api, phase_id, window_start_date="2026-09-01",
                   window_end_date="2026-09-05") -> dict:
    return get_success_data(api.schedule_construction_phase(
        phase_id,
        {"window_start_date": window_start_date, "window_end_date": window_end_date},
        PROJECT_MANAGER))


def start_phase(api, phase_id) -> dict:
    return get_success_data(api.start_construction_phase(phase_id, PROJECT_MANAGER))


def complete_phase(api, phase_id) -> dict:
    return get_success_data(api.complete_construction_phase(phase_id, PROJECT_MANAGER))


def setup_scheduled_phase(api, ctx, window_start_date="2026-09-01",
                          window_end_date="2026-09-05", **phase_overrides) -> dict:
    """Add a phase to a PERMITTED project and book its disruption window."""
    phase = add_phase(api, ctx["project"]["id"], **phase_overrides)
    return schedule_phase(api, phase["id"], window_start_date, window_end_date)


def setup_started_phase(api, ctx, window_start_date="2026-09-01",
                        window_end_date="2026-09-05", **phase_overrides) -> dict:
    """Phase scheduled and started, moving the project to UNDER_CONSTRUCTION."""
    phase = setup_scheduled_phase(api, ctx, window_start_date, window_end_date, **phase_overrides)
    return start_phase(api, phase["id"])


def book_inspection(api, phase_id, inspector_id, **overrides) -> dict:
    return get_success_data(api.create_inspection_appointment(
        phase_id, inspection_appointment_payload(inspector_id, **overrides), PROJECT_MANAGER))


def record_result(api, appointment_id, inspector_id, outcome="PASS", result_notes="Verified") -> dict:
    return get_success_data(api.record_inspection_result(
        appointment_id, {"outcome": outcome, "result_notes": result_notes},
        make_building_inspector_headers(inspector_id)))


def availability(api, inspector_id, slot_date, headers=PROJECT_MANAGER) -> dict:
    return get_success_data(api.get_inspector_availability(inspector_id, slot_date, headers))


# ---------------------------------------------------------------------------
# Tier 4 — financing and the contract ledger
# ---------------------------------------------------------------------------

def price_financing_scenario(api, project_id, **overrides) -> dict:
    version = current_project_version(api, project_id)
    return get_success_data(api.create_financing_scenario(
        project_id, financing_scenario_payload(version, **overrides), FINANCE_ADVISOR))


def commit_scenario(api, scenario_id) -> dict:
    return get_success_data(api.commit_financing_scenario(scenario_id, FINANCE_ADVISOR))


def setup_committed_income_scenario(api, ctx, **overrides) -> dict:
    """Price an INCOME_CAPITALIZATION scenario with a zero funding gap and commit it,
    driving financing_state to COMMITTED."""
    payload = {"product_type": "CONSTRUCTION_LOAN",
               "appraisal_approach": "INCOME_CAPITALIZATION"}
    payload.update(overrides)
    scenario = price_financing_scenario(api, ctx["project"]["id"], **payload)
    committed = commit_scenario(api, scenario["id"])
    ctx["scenario"] = committed
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return committed


def raise_change_order(api, ctx, **overrides) -> dict:
    """Homeowner raises a change order with a freshly read project version."""
    version = current_project_version(api, ctx["project"]["id"])
    return get_success_data(api.create_change_order(
        ctx["project"]["id"], change_order_payload(version, **overrides),
        ctx["homeowner_headers"]))


def send_change_order(api, ctx, change_order_id) -> dict:
    return get_success_data(api.submit_change_order(change_order_id, ctx["homeowner_headers"]))


def decide_change_order(api, change_order_id, decision="APPROVE", headers=PROJECT_MANAGER) -> dict:
    return get_success_data(
        api.decide_change_order(change_order_id, {"decision": decision}, headers))


def setup_submitted_change_order(api, ctx, **overrides) -> dict:
    """Raise a change order and send it for decision: status SUBMITTED."""
    change_order = raise_change_order(api, ctx, **overrides)
    return send_change_order(api, ctx, change_order["id"])


def setup_approved_change_order(api, ctx, **overrides) -> dict:
    """Raise, send and approve a change order, running the funding cascade."""
    change_order = setup_submitted_change_order(api, ctx, **overrides)
    approved = decide_change_order(api, change_order["id"], "APPROVE")
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return approved


def read_change_orders(api, project_id, headers=PROJECT_MANAGER) -> list:
    return get_success_data(api.list_change_orders(headers, {"adu_project_id": project_id}))


# ---------------------------------------------------------------------------
# Tier 5 — certificate-ready projects
# ---------------------------------------------------------------------------

def setup_certificate_ready_project(api, jurisdiction_overrides=None, property_overrides=None,
                                    project_overrides=None, energize=True,
                                    pathway="LOCAL_ORDINANCE", service_type="ELECTRIC") -> dict:
    """Everything the certificate of occupancy needs: an approved permit, an
    ENERGIZED utility record, one COMPLETE phase and a PASSED FINAL inspection.

    Set energize=False to leave the utility record short of ENERGIZED.
    """
    ctx = setup_permitted_project(
        api, pathway=pathway, service_type=service_type,
        jurisdiction_overrides=jurisdiction_overrides,
        property_overrides=property_overrides,
        project_overrides=project_overrides)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"])
    ctx["inspector"] = inspector
    if energize and service_type:
        ctx["utility"] = energize_utility_connection(api, ctx["utility"]["id"])
    phase = setup_started_phase(
        api, ctx, phase_code="FINISHES", disruption_class="NON_INVASIVE", sequence_index=6)
    appointment = book_inspection(
        api, phase["id"], inspector["id"], inspection_type="FINAL",
        slot_date="2026-09-05", slot_start="2026-09-05T09:00:00Z",
        slot_end="2026-09-05T10:00:00Z")
    ctx["final_appointment"] = record_result(
        api, appointment["id"], inspector["id"], "PASS", "Final signed off")
    ctx["phase"] = complete_phase(api, phase["id"])
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return ctx


def issue_certificate(api, project_id) -> dict:
    return get_success_data(api.issue_occupancy_certificate(project_id, PLAN_CHECKER))
