"""Composable setup builders.

Each individual test starts against an empty store, so every scenario must be
built from scratch through the endpoints the PRD declares. The builders below
compose the recurring prefixes:

* tier 1 - reference data: the logical clock, a jurisdiction, an open ring,
  a landlord;
* tier 2 - a candidate, optionally engaged with its landlord and RF-qualified;
* tier 3 - an executed ground lease;
* tier 4 - structural, environmental, zoning and permit clearance;
* tier 5 - a build-ready candidate selected onto its ring, and the on-air
  scheduling objects that hang off it.

Setup calls use the lenient success reader so that a broken precondition
surfaces as a plain assertion naming the failing step.
"""

from typing import Any, Dict, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import ApiClient
from .constants import iso
from .test_users import (
    AGENT_OWNER,
    ANALYST,
    CERTIFIER,
    CONSTRUCTION_MANAGER,
    DESIGNER,
    DIRECTOR,
    ENV_REVIEWER,
    PLANNER,
    RF_ENGINEER,
    make_construction_manager_headers,
    make_environmental_reviewer_headers,
    make_program_director_headers,
    make_rf_engineer_headers,
    make_site_acquisition_agent_headers,
    make_structural_engineer_headers,
    make_zoning_planner_headers,
)

Chain = Dict[str, Any]


# ===========================================================================
# Actors - short header builders for the seven roles
# ===========================================================================
def agent(user_id: str = AGENT_OWNER) -> Dict[str, str]:
    """The `SiteAcquisitionAgent` who owns the candidates these builders create."""
    return make_site_acquisition_agent_headers(user_id)


def director(user_id: str = DIRECTOR) -> Dict[str, str]:
    return make_program_director_headers(user_id)


def planner(user_id: str = PLANNER) -> Dict[str, str]:
    return make_zoning_planner_headers(user_id)


def rf(user_id: str = RF_ENGINEER) -> Dict[str, str]:
    return make_rf_engineer_headers(user_id)


def analyst(user_id: str = ANALYST) -> Dict[str, str]:
    """The `StructuralEngineer` who performs analyses."""
    return make_structural_engineer_headers(user_id)


def designer(user_id: str = DESIGNER) -> Dict[str, str]:
    """The `StructuralEngineer` who authors modification designs."""
    return make_structural_engineer_headers(user_id)


def certifier(user_id: str = CERTIFIER) -> Dict[str, str]:
    """The `StructuralEngineer` who certifies someone else's design."""
    return make_structural_engineer_headers(user_id)


def reviewer(user_id: str = ENV_REVIEWER) -> Dict[str, str]:
    return make_environmental_reviewer_headers(user_id)


def cm(user_id: str = CONSTRUCTION_MANAGER) -> Dict[str, str]:
    return make_construction_manager_headers(user_id)


# ===========================================================================
# Tier 1 - reference data
# ===========================================================================
def set_clock(api: ApiClient, to_iso8601: str) -> None:
    get_success_data(api.set_clock(to_iso8601, headers=make_program_director_headers()))


def reset_clock(api: ApiClient) -> None:
    """Pin the logical clock at the PRD's startup default."""
    set_clock(api, C.CLOCK_DEFAULT)


def create_jurisdiction(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_jurisdiction(
            F.jurisdiction_payload(**overrides), headers=make_zoning_planner_headers()
        )
    )


def create_historic_jurisdiction(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A historic-district jurisdiction in the secondary market."""
    return create_jurisdiction(
        api,
        name=C.HISTORIC_JURISDICTION_NAME,
        market_code=C.OTHER_MARKET_CODE,
        requires_visual_simulation=False,
        historic_district_flag=True,
        historical_delay_factor=C.HISTORIC_DELAY_FACTOR,
        **overrides,
    )


def create_search_ring(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_search_ring(
            F.search_ring_payload(**overrides), headers=make_rf_engineer_headers()
        )
    )


def open_ring(api: ApiClient, ring_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.open_search_ring(ring_id, headers=make_rf_engineer_headers())
    )


def create_open_ring(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    ring = create_search_ring(api, **overrides)
    return open_ring(api, ring["id"])


def create_landlord(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_landlord(
            F.landlord_payload(**overrides),
            headers=make_site_acquisition_agent_headers(AGENT_OWNER),
        )
    )


def create_tribal_landlord(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_landlord(
            F.tribal_landlord_payload(**overrides),
            headers=make_site_acquisition_agent_headers(AGENT_OWNER),
        )
    )


def set_standing(
    api: ApiClient, landlord_id: str, standing: str, reason: str
) -> Dict[str, Any]:
    return get_success_data(
        api.set_landlord_standing(
            landlord_id,
            {"standing": standing, "reason": reason},
            headers=make_program_director_headers(),
        )
    )


def base_reference_data(api: ApiClient, **ring_overrides: Any) -> Chain:
    """Clock, jurisdiction, open ring and landlord."""
    reset_clock(api)
    jurisdiction = create_jurisdiction(api)
    ring = create_open_ring(api, **ring_overrides)
    landlord = create_landlord(api)
    return {
        "jurisdiction": jurisdiction,
        "jur_id": jurisdiction["id"],
        "ring": ring,
        "ring_id": ring["id"],
        "landlord": landlord,
        "ll_id": landlord["id"],
    }


# ===========================================================================
# Tier 2 - candidates
# ===========================================================================
def create_candidate(
    api: ApiClient, ring_id: str, ll_id: str, jur_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_candidate(
            F.candidate_payload(ring_id, ll_id, jur_id, **overrides),
            headers=make_site_acquisition_agent_headers(AGENT_OWNER),
        )
    )


def outreach(api: ApiClient, candidate_id: str, event_type: str) -> Dict[str, Any]:
    return get_success_data(
        api.add_outreach_event(
            candidate_id,
            {"event_type": event_type},
            headers=make_site_acquisition_agent_headers(AGENT_OWNER),
        )
    )


def engage_landlord(api: ApiClient, candidate_id: str) -> Dict[str, Any]:
    """Walk the acquisition dimension to `LANDLORD_ENGAGED`."""
    outreach(api, candidate_id, "OUTREACH_SENT")
    return outreach(api, candidate_id, "LANDLORD_REPLY")


def rf_qualify(api: ApiClient, candidate_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.rf_qualify(candidate_id, headers=make_rf_engineer_headers())
    )


def candidate_version(api: ApiClient, candidate_id: str) -> int:
    data = get_success_data(
        api.get_candidate(candidate_id, headers=make_structural_engineer_headers(ANALYST))
    )
    return data["version"]


def engaged_candidate(api: ApiClient, **ring_overrides: Any) -> Chain:
    """Reference data plus one candidate whose landlord has replied."""
    chain = base_reference_data(api, **ring_overrides)
    candidate = create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    engage_landlord(api, candidate["id"])
    chain["candidate"] = candidate
    chain["cand_id"] = candidate["id"]
    return chain


def qualified_candidate(api: ApiClient, **ring_overrides: Any) -> Chain:
    chain = engaged_candidate(api, **ring_overrides)
    chain["candidate"] = rf_qualify(api, chain["cand_id"])
    return chain


# ===========================================================================
# Tier 3 - leases
# ===========================================================================
def create_lease(
    api: ApiClient, candidate_id: str, landlord_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_lease(
            F.lease_payload(candidate_id, landlord_id, **overrides),
            headers=make_site_acquisition_agent_headers(AGENT_OWNER),
        )
    )


def lease_round(
    api: ApiClient, lease_id: str, action: str, counter_rent_usd: Optional[float] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if counter_rent_usd is not None:
        payload["counter_rent_usd"] = counter_rent_usd
    return get_success_data(
        api.add_lease_round(
            lease_id, payload, headers=make_site_acquisition_agent_headers(AGENT_OWNER)
        )
    )


def accept_lease(
    api: ApiClient, lease_id: str, opening_counter: float = C.LEASE_BASE_RENT_USD
) -> Dict[str, Any]:
    lease_round(api, lease_id, "SUBMIT", opening_counter)
    return lease_round(api, lease_id, "ACCEPT")


def execute_lease(
    api: ApiClient, lease_id: str, execution_date: str = C.CLOCK_DEFAULT
) -> Dict[str, Any]:
    return get_success_data(
        api.execute_lease(
            lease_id,
            {"execution_date": execution_date},
            headers=make_program_director_headers(),
        )
    )


def executed_lease_chain(api: ApiClient, **ring_overrides: Any) -> Chain:
    """Reference data, an RF-qualified candidate and an executed lease."""
    chain = qualified_candidate(api, **ring_overrides)
    lease = create_lease(api, chain["cand_id"], chain["ll_id"])
    accept_lease(api, lease["id"])
    chain["lease"] = execute_lease(api, lease["id"])
    chain["lease_id"] = lease["id"]
    return chain


# ===========================================================================
# Tier 4 - feasibility clearance
# ===========================================================================
def create_analysis(api: ApiClient, candidate_id: str, **overrides: Any) -> Dict[str, Any]:
    version = candidate_version(api, candidate_id)
    return get_success_data(
        api.create_structural_analysis(
            F.structural_analysis_payload(candidate_id, version, **overrides),
            headers=make_structural_engineer_headers(ANALYST),
        )
    )


def complete_analysis(api: ApiClient, sa_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.complete_structural_analysis(
            sa_id, headers=make_structural_engineer_headers(ANALYST)
        )
    )


def run_analysis(api: ApiClient, candidate_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create an analysis and complete it, returning the completed row."""
    analysis = create_analysis(api, candidate_id, **overrides)
    return complete_analysis(api, analysis["id"])


def create_design(
    api: ApiClient, sa_id: str, estimated_cost_usd: float, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_modification_design(
            F.modification_design_payload(sa_id, estimated_cost_usd, **overrides),
            headers=make_structural_engineer_headers(DESIGNER),
        )
    )


def submit_design(api: ApiClient, md_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.peer_review(
            md_id,
            {"action": "SUBMIT"},
            headers=make_structural_engineer_headers(DESIGNER),
        )
    )


def certify_design(api: ApiClient, md_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.peer_review(
            md_id,
            {"action": "CERTIFY"},
            headers=make_structural_engineer_headers(CERTIFIER),
        )
    )


def create_environmental_review(
    api: ApiClient, candidate_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_environmental_review(
            F.environmental_review_payload(candidate_id, **overrides),
            headers=make_environmental_reviewer_headers(),
        )
    )


def screen_review(api: ApiClient, er_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.screen_environmental_review(er_id, headers=make_environmental_reviewer_headers())
    )


def complete_branch(
    api: ApiClient, er_id: str, branch: str, finding: str = "NO_ADVERSE_EFFECT"
) -> Dict[str, Any]:
    return get_success_data(
        api.complete_branch(
            er_id,
            {"branch": branch, "finding": finding},
            headers=make_environmental_reviewer_headers(),
        )
    )


def clear_environmental(api: ApiClient, candidate_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create a categorical-exclusion review, screen it and close the notice branch."""
    review = create_environmental_review(api, candidate_id, **overrides)
    screen_review(api, review["id"])
    cleared = complete_branch(api, review["id"], "PUBLIC_NOTICE")
    cleared["id"] = review["id"]
    return cleared


def create_zoning_application(
    api: ApiClient, candidate_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_zoning_application(
            F.zoning_application_payload(candidate_id, **overrides),
            headers=make_zoning_planner_headers(),
        )
    )


def add_visual_simulations(api: ApiClient, za_id: str, count: int = 2) -> None:
    shots = [(0, "sim-north"), (180, "sim-south"), (90, "sim-east"), (270, "sim-west")]
    for angle, reference in shots[:count]:
        get_success_data(
            api.add_visual_simulation(
                za_id,
                F.visual_simulation_payload(angle, reference),
                headers=make_zoning_planner_headers(),
            )
        )


def submit_zoning_application(api: ApiClient, za_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.submit_zoning_application(za_id, headers=make_zoning_planner_headers())
    )


def set_completeness(api: ApiClient, za_id: str, outcome: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_completeness(
            za_id, {"outcome": outcome}, headers=make_zoning_planner_headers()
        )
    )


def hearing_action(
    api: ApiClient, za_id: str, action: str, **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(extra)
    return get_success_data(
        api.hearing_action(za_id, payload, headers=make_zoning_planner_headers())
    )


def decide_zoning(
    api: ApiClient, za_id: str, outcome: str, decision_date: str
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_zoning_application(
            za_id,
            {"outcome": outcome, "decision_date": decision_date},
            headers=make_zoning_planner_headers(),
        )
    )


def approve_zoning(
    api: ApiClient,
    candidate_id: str,
    hearing_date: str = iso("2026-10-01"),
    simulation_count: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    """Take a conditional-use application all the way to `APPROVED`.

    Leaves the logical clock standing on ``hearing_date``, because the hearing
    can only be held once the clock has reached the scheduled date.
    """
    application = create_zoning_application(api, candidate_id, **overrides)
    za_id = application["id"]
    add_visual_simulations(api, za_id, simulation_count)
    submit_zoning_application(api, za_id)
    set_completeness(api, za_id, "COMPLETE")
    hearing_action(api, za_id, "SCHEDULE", hearing_date=hearing_date)
    set_clock(api, hearing_date)
    hearing_action(api, za_id, "HOLD")
    approved = decide_zoning(api, za_id, "APPROVED", hearing_date)
    approved["id"] = za_id
    return approved


def create_permit(api: ApiClient, candidate_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_permit(
            F.permit_payload(candidate_id, **overrides),
            headers=make_construction_manager_headers(),
        )
    )


def issue_permit(api: ApiClient, permit_id: str, issued_date: str) -> Dict[str, Any]:
    return get_success_data(
        api.issue_permit(
            permit_id,
            {"issued_date": issued_date},
            headers=make_construction_manager_headers(),
        )
    )


def revoke_permit(api: ApiClient, permit_id: str, reason: str) -> Dict[str, Any]:
    return get_success_data(
        api.revoke_permit(
            permit_id,
            {"revocation_reason": reason},
            headers=make_construction_manager_headers(),
        )
    )


def mark_build_ready(api: ApiClient, candidate_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.mark_build_ready(candidate_id, headers=make_construction_manager_headers())
    )


# ===========================================================================
# Tier 5 - selection and scheduling
# ===========================================================================
def ring_version(api: ApiClient, ring_id: str) -> int:
    data = get_success_data(
        api.get_search_ring(ring_id, headers=make_program_director_headers())
    )
    return data["version"]


def select_site(api: ApiClient, ring_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.select_site(
            ring_id,
            {"expected_search_ring_version": ring_version(api, ring_id)},
            headers=make_program_director_headers(),
        )
    )


def build_ready_chain(
    api: ApiClient,
    hearing_date: str = iso("2026-10-01"),
    **ring_overrides: Any,
) -> Chain:
    """Everything through `mark-build-ready` for a single candidate.

    The chain leaves the logical clock on ``hearing_date``.
    """
    chain = executed_lease_chain(api, **ring_overrides)
    analysis = run_analysis(api, chain["cand_id"])
    review = clear_environmental(api, chain["cand_id"])
    application = approve_zoning(api, chain["cand_id"], hearing_date=hearing_date)
    permit = create_permit(api, chain["cand_id"])
    issue_permit(api, permit["id"], hearing_date)
    chain.update(
        {
            "analysis": analysis,
            "sa_id": analysis["id"],
            "review": review,
            "er_id": review["id"],
            "application": application,
            "za_id": application["id"],
            "permit": permit,
            "cp_id": permit["id"],
            "candidate": mark_build_ready(api, chain["cand_id"]),
            "clock": hearing_date,
        }
    )
    return chain


def build_selected_chain(
    api: ApiClient, hearing_date: str = iso("2026-10-01"), **ring_overrides: Any
) -> Chain:
    """A build-ready candidate selected onto its ring."""
    chain = build_ready_chain(api, hearing_date=hearing_date, **ring_overrides)
    chain["ring"] = select_site(api, chain["ring_id"])
    return chain


def create_provider(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_utility_provider(
            F.utility_provider_payload(**overrides),
            headers=make_construction_manager_headers(),
        )
    )


def create_order(
    api: ApiClient,
    candidate_id: str,
    provider_id: str,
    order_type: str,
    window_start: str,
    window_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_backhaul_order(
            F.backhaul_order_payload(
                candidate_id,
                provider_id,
                order_type,
                window_start,
                window_end,
                **overrides,
            ),
            headers=make_construction_manager_headers(),
        )
    )


def order_action(api: ApiClient, order_id: str, action: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(extra)
    return get_success_data(
        api.order_status_action(
            order_id, payload, headers=make_construction_manager_headers()
        )
    )


def create_plan(
    api: ApiClient, ring_id: str, target_on_air_date: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_on_air_plan(
            F.on_air_plan_payload(ring_id, target_on_air_date, **overrides),
            headers=make_program_director_headers(),
        )
    )


# ===========================================================================
# pytest fixtures
# ===========================================================================
@pytest.fixture()
def clock(api: ApiClient) -> str:
    """Pin the logical clock at the PRD's startup default."""
    reset_clock(api)
    return C.CLOCK_DEFAULT


@pytest.fixture()
def reference_data(api: ApiClient) -> Chain:
    return base_reference_data(api)


@pytest.fixture()
def engaged(api: ApiClient) -> Chain:
    return engaged_candidate(api)


@pytest.fixture()
def qualified(api: ApiClient) -> Chain:
    return qualified_candidate(api)


@pytest.fixture()
def leased(api: ApiClient) -> Chain:
    return executed_lease_chain(api)


@pytest.fixture()
def build_ready(api: ApiClient) -> Chain:
    return build_ready_chain(api)


@pytest.fixture()
def selected(api: ApiClient) -> Chain:
    return build_selected_chain(api)
