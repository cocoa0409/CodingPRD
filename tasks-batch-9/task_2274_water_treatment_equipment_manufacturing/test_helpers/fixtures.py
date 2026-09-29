"""Composite state builders for the water treatment delivery chain.

The workflow in this domain is long: a project must be scoped from accepted
laboratory data, its train selected, its packages priced and reviewed, an
or-equal submittal pre-approved, a bid posted and awarded, skids fabricated and
factory-tested, closeout deliverables accepted, a guarantee demonstration
certified, and only then can a service agreement hold a consumable reserve.
Each builder here drives one more link of that chain and returns a plain dict of
the rows it created, so a test can start from the state it actually needs.

Every builder uses ``get_success_data`` rather than a strict validator: setup is
not the thing under test, and a strict status assertion inside a fixture would
report a setup problem as a failure of the rule the test is really about.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import CONTROLS_SEQUENCE, MECHANICAL_SEQUENCE
from .test_users import (
    make_application_engineer_headers,
    make_commissioning_engineer_headers,
    make_contracts_administrator_headers,
    make_design_reviewer_headers,
    make_engineer_of_record_headers,
    make_fabrication_manager_headers,
    make_owner_representative_headers,
    make_platform_admin_headers,
    make_quality_engineer_headers,
)

# ---------------------------------------------------------------------------
# Tier 1: catalogs
# ---------------------------------------------------------------------------


def seed_material_spec(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create MAT-316L (or an override of it) in the global material catalog."""
    return get_success_data(
        api.create_material_spec(
            factories.material_spec_payload(**overrides), make_platform_admin_headers()
        )
    )


def seed_pvc_material_spec(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_material_spec(
            factories.pvc_material_spec_payload(**overrides),
            make_platform_admin_headers(),
        )
    )


def seed_filtration_technology(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_process_technology(
            factories.filtration_technology_payload(**overrides),
            make_platform_admin_headers(),
        )
    )


def seed_disinfection_technology(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_process_technology(
            factories.disinfection_technology_payload(**overrides),
            make_platform_admin_headers(),
        )
    )


def seed_test_bay(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_test_bay(
            factories.test_bay_payload(**overrides), make_platform_admin_headers()
        )
    )


def seed_catalog(api: ApiClient, with_disinfection: bool = False) -> Dict[str, Any]:
    """MAT-316L, TECH-FILT-A, BAY-1, and optionally TECH-DIS-A."""
    state: Dict[str, Any] = {
        "material_spec": seed_material_spec(api),
        "filtration_technology": seed_filtration_technology(api),
        "test_bay": seed_test_bay(api),
    }
    if with_disinfection:
        state["disinfection_technology"] = seed_disinfection_technology(api)
    return state


# ---------------------------------------------------------------------------
# Tier 2: project, laboratory data and the treatment train
# ---------------------------------------------------------------------------


def create_draft_project(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_project(
            factories.project_payload(**overrides),
            make_contracts_administrator_headers(),
        )
    )


def add_influent_profile(
    api: ApiClient, project_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_influent_profile(
            project_id,
            factories.influent_profile_payload(**overrides),
            make_application_engineer_headers(),
        )
    )


def decide_profile(
    api: ApiClient, profile_id: str, decision: str = "ACCEPT", **payload: Any
) -> Dict[str, Any]:
    body = {"decision": decision}
    body.update(payload)
    return get_success_data(
        api.decide_influent_profile_qa(
            profile_id, body, make_quality_engineer_headers()
        )
    )


def add_accepted_influent_profile(
    api: ApiClient, project_id: str, **overrides: Any
) -> Dict[str, Any]:
    profile = add_influent_profile(api, project_id, **overrides)
    decide_profile(api, profile["id"], "ACCEPT")
    return profile


def add_turbidity_objective(
    api: ApiClient, project_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_treatment_objective(
            project_id,
            factories.turbidity_objective_payload(**overrides),
            make_application_engineer_headers(),
        )
    )


def add_ecoli_objective(
    api: ApiClient, project_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_treatment_objective(
            project_id,
            factories.ecoli_objective_payload(**overrides),
            make_application_engineer_headers(),
        )
    )


def run_selection(api: ApiClient, project_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api.run_process_selection(project_id, make_application_engineer_headers())
    )


def scoped_single_stage_project(api: ApiClient) -> Dict[str, Any]:
    """Catalog seeded, one accepted 4.000 mgd profile, one turbidity objective,
    process selection run once, so exactly one SELECTED FILTRATION stage exists."""
    state = seed_catalog(api)
    project = create_draft_project(api)
    state["project"] = project
    state["influent_profile"] = add_accepted_influent_profile(api, project["id"])
    state["turbidity_objective"] = add_turbidity_objective(api, project["id"])
    stages = run_selection(api, project["id"])
    state["stages"] = stages
    state["filtration_stage"] = stages[0]
    return state


def scoped_two_stage_project(api: ApiClient) -> Dict[str, Any]:
    """Turbidity plus E. coli objectives, so the train is FILTRATION then DISINFECTION."""
    state = seed_catalog(api, with_disinfection=True)
    project = create_draft_project(api)
    state["project"] = project
    state["influent_profile"] = add_accepted_influent_profile(api, project["id"])
    state["turbidity_objective"] = add_turbidity_objective(api, project["id"])
    state["ecoli_objective"] = add_ecoli_objective(api, project["id"])
    stages = run_selection(api, project["id"])
    state["stages"] = stages
    state["filtration_stage"] = stages[0]
    state["disinfection_stage"] = stages[1]
    return state


# ---------------------------------------------------------------------------
# Tier 3: equipment packages
# ---------------------------------------------------------------------------


def add_draft_package(
    api: ApiClient, stage_id: str, material_spec_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_equipment_package(
            stage_id,
            factories.equipment_package_payload(material_spec_id, **overrides),
            make_application_engineer_headers(),
        )
    )


def approve_package(api: ApiClient, package_id: str) -> Dict[str, Any]:
    """Drive one package DRAFT -> IN_REVIEW -> APPROVED, freezing its firm cost."""
    get_success_data(
        api.submit_package_for_review(package_id, make_application_engineer_headers())
    )
    return get_success_data(
        api.decide_package_review(
            package_id, {"decision": "APPROVE"}, make_design_reviewer_headers()
        )
    )


def project_with_approved_package(api: ApiClient) -> Dict[str, Any]:
    state = scoped_single_stage_project(api)
    package = add_draft_package(
        api, state["filtration_stage"]["id"], state["material_spec"]["id"]
    )
    state["package"] = approve_package(api, package["id"])
    return state


def two_stage_project_with_approved_packages(api: ApiClient) -> Dict[str, Any]:
    """Both stages priced and approved: F-100 at 150 psig and D-100 at 100 psig."""
    state = scoped_two_stage_project(api)
    filtration_package = add_draft_package(
        api,
        state["filtration_stage"]["id"],
        state["material_spec"]["id"],
        tag_number="F-100",
        design_pressure_psig=150,
    )
    state["filtration_package"] = approve_package(api, filtration_package["id"])
    disinfection_package = add_draft_package(
        api,
        state["disinfection_stage"]["id"],
        state["material_spec"]["id"],
        tag_number="D-100",
        design_pressure_psig=100,
    )
    state["disinfection_package"] = approve_package(api, disinfection_package["id"])
    return state


# ---------------------------------------------------------------------------
# Tier 4: or-equal submittals
# ---------------------------------------------------------------------------


def add_submittal(api: ApiClient, project_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_or_equal_submittal(
            factories.or_equal_submittal_payload(project_id, **overrides),
            make_application_engineer_headers(),
        )
    )


def add_deviation(
    api: ApiClient,
    submittal_id: str,
    severity: str = "MODERATE",
    **overrides: Any,
) -> Dict[str, Any]:
    """File one deviation, reading the submittal's current version for the OCC token."""
    submittal = get_success_data(
        api.get_or_equal_submittal(submittal_id, make_application_engineer_headers())
    )
    return get_success_data(
        api.create_spec_deviation(
            submittal_id,
            factories.spec_deviation_payload(
                submittal["version"], severity, **overrides
            ),
            make_application_engineer_headers(),
        )
    )


def submitted_submittal(
    api: ApiClient, project_id: str, severity: str = "MODERATE", **overrides: Any
) -> Dict[str, Any]:
    """One submittal carrying a single deviation, transmitted for engineer decision."""
    submittal = add_submittal(api, project_id, **overrides)
    deviation = add_deviation(api, submittal["id"], severity)
    get_success_data(
        api.submit_or_equal_submittal(
            submittal["id"], make_application_engineer_headers()
        )
    )
    return {"submittal": submittal, "deviation": deviation}


def preapproved_submittal(
    api: ApiClient, project_id: str, severity: str = "MODERATE", **overrides: Any
) -> Dict[str, Any]:
    filed = submitted_submittal(api, project_id, severity, **overrides)
    get_success_data(
        api.decide_or_equal_submittal(
            filed["submittal"]["id"],
            {"decision": "PRE_APPROVED"},
            make_engineer_of_record_headers(),
        )
    )
    return filed


# ---------------------------------------------------------------------------
# Tier 5: bidding, award and fabrication release
# ---------------------------------------------------------------------------


def bid_ready_single_stage_project(api: ApiClient) -> Dict[str, Any]:
    """Every stage priced and approved plus one PRE_APPROVED submittal, so the
    project has cleared the bid readiness gate."""
    state = project_with_approved_package(api)
    state.update(preapproved_submittal(api, state["project"]["id"]))
    return state


def bid_ready_two_stage_project(api: ApiClient) -> Dict[str, Any]:
    state = two_stage_project_with_approved_packages(api)
    state.update(preapproved_submittal(api, state["project"]["id"]))
    return state


def post_bid(
    api: ApiClient, project_id: str, offered_price_cents: int
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_bid(
            project_id,
            {"offered_price_cents": offered_price_cents},
            make_contracts_administrator_headers(),
        )
    )


def record_award(
    api: ApiClient, project_id: str, award_decision: str = "AWARDED"
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_award(
            project_id,
            {"award_decision": award_decision},
            make_contracts_administrator_headers(),
        )
    )


def awarded_single_stage_project(
    api: ApiClient, offered_price_cents: int = 400000000
) -> Dict[str, Any]:
    state = bid_ready_single_stage_project(api)
    post_bid(api, state["project"]["id"], offered_price_cents)
    record_award(api, state["project"]["id"], "AWARDED")
    return state


def awarded_two_stage_project(
    api: ApiClient, offered_price_cents: int = 500000000
) -> Dict[str, Any]:
    state = bid_ready_two_stage_project(api)
    post_bid(api, state["project"]["id"], offered_price_cents)
    record_award(api, state["project"]["id"], "AWARDED")
    return state


def release_package(api: ApiClient, package_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.release_package_for_fabrication(
            package_id, make_fabrication_manager_headers()
        )
    )


def skid_of_package(api: ApiClient, package_id: str) -> Dict[str, Any]:
    rows = get_success_data(
        api.list_skids(
            make_fabrication_manager_headers(),
            {"equipment_package_id": package_id},
        )
    )
    return rows[0]


def released_single_stage_project(api: ApiClient) -> Dict[str, Any]:
    """Awarded project with F-100 released, so exactly one Skid has been minted
    and the project sits in fabrication."""
    state = awarded_single_stage_project(api)
    release_package(api, state["package"]["id"])
    state["skid"] = skid_of_package(api, state["package"]["id"])
    return state


def released_two_stage_project(api: ApiClient) -> Dict[str, Any]:
    state = awarded_two_stage_project(api)
    release_package(api, state["filtration_package"]["id"])
    release_package(api, state["disinfection_package"]["id"])
    state["filtration_skid"] = skid_of_package(api, state["filtration_package"]["id"])
    state["disinfection_skid"] = skid_of_package(
        api, state["disinfection_package"]["id"]
    )
    return state


def advance_dimension(
    api: ApiClient, skid_id: str, dimension: str, sequence, up_to: Optional[str] = None
) -> Dict[str, Any]:
    """Walk one skid dimension through its declared successors in order."""
    latest: Dict[str, Any] = {}
    for state_name in sequence[1:]:
        latest = get_success_data(
            api.record_skid_milestone(
                skid_id,
                factories.milestone_payload(dimension, state_name),
                make_fabrication_manager_headers(),
            )
        )
        if up_to is not None and state_name == up_to:
            break
    return latest


def drive_skid_mechanically_complete(api: ApiClient, skid_id: str) -> Dict[str, Any]:
    return advance_dimension(api, skid_id, "MECHANICAL", MECHANICAL_SEQUENCE)


def drive_skid_fat_ready(api: ApiClient, skid_id: str) -> Dict[str, Any]:
    """Both dimensions complete, which with a released package reads READY."""
    advance_dimension(api, skid_id, "MECHANICAL", MECHANICAL_SEQUENCE)
    return advance_dimension(api, skid_id, "CONTROLS", CONTROLS_SEQUENCE)


def fat_ready_single_stage_project(api: ApiClient) -> Dict[str, Any]:
    state = released_single_stage_project(api)
    state["skid"] = drive_skid_fat_ready(api, state["skid"]["id"])
    return state


def fat_ready_two_stage_project(api: ApiClient) -> Dict[str, Any]:
    state = released_two_stage_project(api)
    state["filtration_skid"] = drive_skid_fat_ready(
        api, state["filtration_skid"]["id"]
    )
    state["disinfection_skid"] = drive_skid_fat_ready(
        api, state["disinfection_skid"]["id"]
    )
    return state


def current_skid(api: ApiClient, skid_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_skid(skid_id, make_fabrication_manager_headers())
    )


def schedule_fat_run(
    api: ApiClient,
    skid: Dict[str, Any],
    test_bay_id: str,
    start_at: str = "2026-08-10T08:00:00.000Z",
    end_at: str = "2026-08-10T16:00:00.000Z",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_fat_run(
            factories.fat_run_payload(
                skid["id"], test_bay_id, skid["version"], start_at, end_at
            ),
            make_fabrication_manager_headers(),
        )
    )


def scheduled_fat_run_project(api: ApiClient) -> Dict[str, Any]:
    """One READY skid holding a booking of 5400 sf for 480 minutes in BAY-1."""
    state = fat_ready_single_stage_project(api)
    state["fat_run"] = schedule_fat_run(
        api, state["skid"], state["test_bay"]["id"]
    )
    return state


def witness_run(
    api: ApiClient, run_id: str, result: str = "PASS", punchlist_item_count: int = 0
) -> Dict[str, Any]:
    return get_success_data(
        api.witness_fat_run(
            run_id,
            {"result": result, "punchlist_item_count": punchlist_item_count},
            make_quality_engineer_headers(),
        )
    )


# ---------------------------------------------------------------------------
# Tier 6: commissioning, guarantee and long-term service
# ---------------------------------------------------------------------------


def commissioning_project(api: ApiClient) -> Dict[str, Any]:
    """Single-stage project whose only factory test has passed, so the package is
    FAT_PASSED and the project has bubbled to COMMISSIONING."""
    state = scheduled_fat_run_project(api)
    witness_run(api, state["fat_run"]["id"], "PASS", 0)
    return state


def accept_all_deliverables(api: ApiClient, project_id: str) -> Dict[str, Any]:
    latest: Dict[str, Any] = {}
    for deliverable_type in ("OM_MANUAL", "OPERATOR_TRAINING", "SPARE_PARTS_LIST"):
        latest = get_success_data(
            api.accept_deliverable(
                project_id,
                {"deliverable_type": deliverable_type, "decision": "ACCEPT"},
                make_owner_representative_headers(),
            )
        )
    return latest


def record_demo(
    api: ApiClient,
    project_id: str,
    skid_id: str,
    readings: Optional[List[Dict[str, Any]]] = None,
    start_at: str = "2026-08-20T00:00:00.000Z",
    end_at: str = "2026-08-27T00:00:00.000Z",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_performance_demo(
            factories.performance_demo_payload(
                project_id, skid_id, readings, start_at, end_at
            ),
            make_commissioning_engineer_headers(),
        )
    )


def certify_demo(
    api: ApiClient, demo_id: str, certification: str = "PASS"
) -> Dict[str, Any]:
    return get_success_data(
        api.certify_performance_demo(
            demo_id, {"certification": certification}, make_quality_engineer_headers()
        )
    )


def guaranteed_project(
    api: ApiClient, measured_value: float = 0.250
) -> Dict[str, Any]:
    """Deliverables accepted and a first demonstration certified PASS, so the
    guarantee is MET and the project rests in GUARANTEED awaiting a service
    agreement."""
    state = commissioning_project(api)
    accept_all_deliverables(api, state["project"]["id"])
    state["demo"] = record_demo(
        api,
        state["project"]["id"],
        state["skid"]["id"],
        [{"parameter": "TURBIDITY_NTU", "measured_value": measured_value}],
    )
    certify_demo(api, state["demo"]["id"], "PASS")
    return state


def open_service_agreement(
    api: ApiClient, project_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_service_agreement(
            project_id,
            factories.service_agreement_payload(**overrides),
            make_contracts_administrator_headers(),
        )
    )


def service_active_project(api: ApiClient, **agreement_overrides: Any) -> Dict[str, Any]:
    """The whole chain: a guaranteed project with one ACTIVE service agreement
    holding its full reserve, which puts the project in SERVICE_ACTIVE."""
    state = guaranteed_project(api)
    state["agreement"] = open_service_agreement(
        api, state["project"]["id"], **agreement_overrides
    )
    return state


def current_agreement(api: ApiClient, agreement_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_service_agreement(
            agreement_id, make_contracts_administrator_headers()
        )
    )


def post_draw(
    api: ApiClient, agreement_id: str, **draw_overrides: Any
) -> Dict[str, Any]:
    """Post one draw, always reading the agreement's live version first so the
    OCC token is fresh and the test exercises the rule it means to."""
    agreement = current_agreement(api, agreement_id)
    return get_success_data(
        api.create_consumable_draw(
            agreement_id,
            factories.consumable_draw_payload(agreement["version"], **draw_overrides),
            make_contracts_administrator_headers(),
        )
    )
