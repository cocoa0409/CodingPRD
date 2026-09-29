"""Composable setup helpers that build state only through declared endpoints.

Every helper drives the public API — there is no direct database access — and
every ownership or segregation check is fed the real stakeholder id of the
acting person, so identities are threaded rather than shared.

Two estates are provided:

* ``setup_two_application_estate`` builds a recovery group holding two agreed
  applications and two assets, chained by HARD edges into a 92-minute
  projection, behind a validated three-step runbook (readiness 100.00).
* ``setup_single_application_estate`` builds the smaller one-application,
  one-asset variant with an 80-minute projection and a single validated step.

Both accept a ``through`` argument so a test can stop the bootstrap at the
moment it needs; the module-level ``ESTATE_*`` and ``CORE_*`` constants name
those stopping points.
"""

from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_EPOCH
from .test_users import (
    PLATFORM_ADMIN_HEADERS,
    make_audit_liaison_headers,
    make_business_owner_headers,
    make_it_operator_headers,
    make_resilience_coordinator_headers,
    make_risk_approver_headers,
)

# Stopping points of the two-application bootstrap.
ESTATE_CLOCK_SET = 1
ESTATE_PEOPLE_REGISTERED = 6
ESTATE_SITES_REGISTERED = 8
ESTATE_GRAPH_LINKED = 22
ESTATE_RUNBOOK_OPENED = 25
ESTATE_RUNBOOK_VALIDATED = 33

# Stopping points of the single-application bootstrap.
CORE_CLOCK_SET = 1
CORE_PEOPLE_REGISTERED = 6
CORE_SITES_REGISTERED = 8
CORE_APPLICATION_PROPOSED = 10
CORE_APPLICATION_AGREED = 11
CORE_ASSET_REGISTERED = 12
CORE_GROUP_CREATED = 13
CORE_APPLICATION_ASSIGNED = 14
CORE_ASSET_ASSIGNED = 15
CORE_EDGE_CREATED = 16
CORE_GROUP_VERSION_READ = 17
CORE_RUNBOOK_OPENED = 18
CORE_STEP_ADDED = 19
CORE_RUNBOOK_IN_REVIEW = 20
CORE_STEP_VALIDATED = 21
CORE_RUNBOOK_VALIDATED = 22


# --- Primitives --------------------------------------------------------------


def set_logical_clock(api, instant: str) -> dict:
    """Move the server's logical clock; answers 200 and mutates no entity."""
    return get_success_data(api.set_clock(f.clock_payload(instant), PLATFORM_ADMIN_HEADERS))


def register_stakeholder(api, **kwargs) -> dict:
    return get_success_data(
        api.create_stakeholder(f.stakeholder_payload(**kwargs), PLATFORM_ADMIN_HEADERS)
    )


def register_site(api, **kwargs) -> dict:
    return get_success_data(api.create_site(f.site_payload(**kwargs), PLATFORM_ADMIN_HEADERS))


def register_application(api, coordinator_headers, **kwargs) -> dict:
    return get_success_data(
        api.create_application(f.application_payload(**kwargs), coordinator_headers)
    )


def agree_application_tier(
    api,
    coordinator_headers,
    owner_headers,
    application_id: str,
    proposed_tier: str = "TIER_1",
    proposed_rto_minutes: int = 60,
    proposed_rpo_minutes: int = 15,
) -> dict:
    """Propose a tier and have the owning business owner agree it."""
    get_success_data(
        api.propose_application_tier(
            application_id,
            f.tier_proposal_payload(
                proposed_tier=proposed_tier,
                proposed_rto_minutes=proposed_rto_minutes,
                proposed_rpo_minutes=proposed_rpo_minutes,
            ),
            coordinator_headers,
        )
    )
    return get_success_data(
        api.decide_application_tier(
            application_id,
            f.tier_decision_payload("AGREE", "Owner agrees the objectives"),
            owner_headers,
        )
    )


def register_asset(api, operator_headers, **kwargs) -> dict:
    return get_success_data(api.create_asset(f.asset_payload(**kwargs), operator_headers))


def record_replication_observation(
    api,
    operator_headers,
    asset_id: str,
    observed_at: str,
    replication_lag_seconds: int = 240,
    unreplicated_txn_count: int = 900,
) -> dict:
    return get_success_data(
        api.create_replication_observation(
            asset_id,
            f.replication_observation_payload(
                observed_at, replication_lag_seconds, unreplicated_txn_count
            ),
            operator_headers,
        )
    )


def create_recovery_group(api, coordinator_headers, **kwargs) -> dict:
    return get_success_data(
        api.create_recovery_group(f.recovery_group_payload(**kwargs), coordinator_headers)
    )


def assign_application(api, coordinator_headers, application_id: str, group_id: str) -> dict:
    return get_success_data(
        api.assign_application_to_group(
            application_id, f.group_assignment_payload(group_id), coordinator_headers
        )
    )


def assign_asset(api, coordinator_headers, asset_id: str, group_id: str) -> dict:
    return get_success_data(
        api.assign_asset_to_group(
            asset_id, f.group_assignment_payload(group_id), coordinator_headers
        )
    )


def create_dependency_edge(api, coordinator_headers, **kwargs) -> dict:
    return get_success_data(
        api.create_dependency_edge(f.dependency_edge_payload(**kwargs), coordinator_headers)
    )


def read_group(api, headers, group_id: str) -> dict:
    return get_success_data(api.get_recovery_group(group_id, headers))


def read_runbook(api, headers, runbook_id: str) -> dict:
    return get_success_data(api.get_runbook(runbook_id, headers))


def read_step(api, headers, step_id: str) -> dict:
    return get_success_data(api.get_runbook_step(step_id, headers))


def read_exercise(api, headers, exercise_id: str) -> dict:
    return get_success_data(api.get_exercise(exercise_id, headers))


def read_site(api, headers, site_id: str) -> dict:
    return get_success_data(api.get_site(site_id, headers))


def read_finding(api, headers, finding_id: str) -> dict:
    return get_success_data(api.get_finding(finding_id, headers))


def read_evidence_package(api, headers, package_id: str) -> dict:
    return get_success_data(api.get_evidence_package(package_id, headers))


def open_runbook(api, coordinator_headers, group_id: str, author_id: str, **kwargs) -> dict:
    """Open a revision, reading the group's version first as the API demands."""
    group = read_group(api, coordinator_headers, group_id)
    return get_success_data(
        api.create_runbook(
            f.runbook_payload(group_id, author_id, group["version"], **kwargs),
            coordinator_headers,
        )
    )


def add_step(api, coordinator_headers, runbook_id: str, owner_id: str, **kwargs) -> dict:
    return get_success_data(
        api.create_runbook_step(
            f.runbook_step_payload(runbook_id, owner_id, **kwargs), coordinator_headers
        )
    )


def validate_step(api, operator_headers, step_id: str, note: Optional[str] = None) -> dict:
    return get_success_data(
        api.validate_runbook_step(step_id, f.step_validation_payload(note), operator_headers)
    )


def transition_runbook(api, coordinator_headers, runbook_id: str, action: str) -> dict:
    return get_success_data(
        api.transition_runbook(
            runbook_id, f.runbook_transition_payload(action), coordinator_headers
        )
    )


# --- Exercise lifecycle ------------------------------------------------------


def create_exercise(api, coordinator_headers, **kwargs) -> dict:
    return get_success_data(api.create_exercise(f.exercise_payload(**kwargs), coordinator_headers))


def scope_group(api, coordinator_headers, exercise_id: str, group_id: str) -> dict:
    """Bring a group into scope, re-reading the exercise version first."""
    exercise = read_exercise(api, coordinator_headers, exercise_id)
    return get_success_data(
        api.create_scope_item(
            exercise_id,
            f.scope_item_payload(group_id, exercise["version"]),
            coordinator_headers,
        )
    )


def submit_impact(api, coordinator_headers, exercise_id: str) -> dict:
    return get_success_data(api.submit_impact(exercise_id, {}, coordinator_headers))


def approve_impact(api, approver_headers, exercise_id: str, note: Optional[str] = None) -> dict:
    return get_success_data(
        api.decide_impact(
            exercise_id, f.impact_decision_payload("APPROVE", note), approver_headers
        )
    )


def schedule(api, coordinator_headers, exercise_id: str) -> dict:
    return get_success_data(api.schedule_exercise(exercise_id, {}, coordinator_headers))


def drive_execution(api, coordinator_headers, exercise_id: str, action: str) -> dict:
    return get_success_data(
        api.transition_execution(
            exercise_id, f.execution_transition_payload(action), coordinator_headers
        )
    )


def record_step_execution(
    api,
    recorder_headers,
    exercise_id: str,
    step_id: str,
    elapsed_seconds: int = 750,
    outcome: str = "PASSED",
    notes: Optional[str] = None,
) -> dict:
    return get_success_data(
        api.create_step_execution(
            exercise_id,
            f.step_execution_payload(step_id, outcome, elapsed_seconds, notes),
            recorder_headers,
        )
    )


def drive_data(api, operator_headers, exercise_id: str, action: str) -> dict:
    return get_success_data(
        api.transition_data(exercise_id, f.axis_transition_payload(action), operator_headers)
    )


def drive_failback(api, operator_headers, exercise_id: str, action: str) -> dict:
    return get_success_data(
        api.transition_failback(exercise_id, f.axis_transition_payload(action), operator_headers)
    )


def drive_both_axes_to_terminal(api, operator_headers, exercise_id: str) -> None:
    """Reach DATA_VERIFIED and FAILBACK_COMPLETE, the two closure preconditions."""
    drive_data(api, operator_headers, exercise_id, "BEGIN_VALIDATION")
    drive_data(api, operator_headers, exercise_id, "VERIFY")
    drive_failback(api, operator_headers, exercise_id, "PLAN")
    drive_failback(api, operator_headers, exercise_id, "START_SYNC")
    drive_failback(api, operator_headers, exercise_id, "COMPLETE")


def raise_finding(api, actor_headers, exercise_id: str, group_id: str, **kwargs) -> dict:
    return get_success_data(
        api.create_finding(f.finding_payload(exercise_id, group_id, **kwargs), actor_headers)
    )


def drive_finding(api, coordinator_headers, finding_id: str, action: str, **kwargs) -> dict:
    return get_success_data(
        api.transition_finding(
            finding_id, f.finding_transition_payload(action, **kwargs), coordinator_headers
        )
    )


def open_evidence_package(api, liaison_headers, exercise_id: str, prepared_by_id: str) -> dict:
    return get_success_data(
        api.create_evidence_package(
            f.evidence_package_payload(exercise_id, prepared_by_id), liaison_headers
        )
    )


def transition_evidence(api, actor_headers, package_id: str, action: str, **kwargs) -> dict:
    return get_success_data(
        api.transition_evidence_package(
            package_id, f.evidence_transition_payload(action, **kwargs), actor_headers
        )
    )


# --- People and sites --------------------------------------------------------


def _register_standard_people(api) -> dict:
    coordinator = register_stakeholder(
        api,
        full_name="Cora Lin",
        email="cora.lin@example.com",
        org_roles=["RESILIENCE_COORDINATOR"],
        approval_authority_level="LEVEL_1",
    )
    business_owner = register_stakeholder(
        api,
        full_name="Bea Owens",
        email="bea.owens@example.com",
        org_roles=["BUSINESS_OWNER"],
        approval_authority_level="LEVEL_1",
    )
    operator = register_stakeholder(
        api,
        full_name="Otto Pratt",
        email="otto.pratt@example.com",
        org_roles=["IT_OPERATOR"],
        approval_authority_level="LEVEL_1",
    )
    risk_approver = register_stakeholder(
        api,
        full_name="Rhea Adler",
        email="rhea.adler@example.com",
        org_roles=["RISK_APPROVER"],
        approval_authority_level="LEVEL_3",
    )
    audit_liaison = register_stakeholder(
        api,
        full_name="Ally Ito",
        email="ally.ito@example.com",
        org_roles=["AUDIT_LIAISON"],
        approval_authority_level="LEVEL_1",
    )
    return {
        "admin_headers": PLATFORM_ADMIN_HEADERS,
        "coordinator": coordinator,
        "business_owner": business_owner,
        "operator": operator,
        "risk_approver": risk_approver,
        "audit_liaison": audit_liaison,
        "coordinator_headers": make_resilience_coordinator_headers(coordinator["id"]),
        "owner_headers": make_business_owner_headers(business_owner["id"]),
        "operator_headers": make_it_operator_headers(operator["id"]),
        "approver_headers": make_risk_approver_headers(risk_approver["id"]),
        "liaison_headers": make_audit_liaison_headers(audit_liaison["id"]),
    }


def _register_standard_sites(api, estate: dict) -> None:
    estate["site_primary"] = register_site(
        api,
        site_code="SITE-P",
        name="Primary campus",
        role="PRIMARY",
        usable_capacity_units=0,
    )
    estate["site_recovery"] = register_site(
        api,
        site_code="SITE-R",
        name="Recovery campus",
        role="RECOVERY",
        usable_capacity_units=40,
    )


# --- The two-application estate ---------------------------------------------


def setup_two_application_estate(api, through: int = ESTATE_RUNBOOK_VALIDATED) -> dict:
    """Build the estate whose group projects 92 minutes behind a 100.00 runbook."""
    estate = {}
    estate["clock"] = CLOCK_EPOCH
    set_logical_clock(api, CLOCK_EPOCH)
    if through <= ESTATE_CLOCK_SET:
        return estate

    estate.update(_register_standard_people(api))
    if through <= ESTATE_PEOPLE_REGISTERED:
        return estate

    _register_standard_sites(api, estate)
    if through <= ESTATE_SITES_REGISTERED:
        return estate

    coordinator_headers = estate["coordinator_headers"]
    owner_headers = estate["owner_headers"]
    operator_headers = estate["operator_headers"]

    estate["app_core"] = register_application(
        api,
        coordinator_headers,
        business_owner_id=estate["business_owner"]["id"],
        primary_site_id=estate["site_primary"]["id"],
        app_code="APP-CORE",
        name="Core ledger",
        criticality_weight=10,
    )
    estate["app_core"] = agree_application_tier(
        api,
        coordinator_headers,
        owner_headers,
        estate["app_core"]["id"],
        proposed_tier="TIER_1",
        proposed_rto_minutes=60,
        proposed_rpo_minutes=15,
    )
    estate["app_edge"] = register_application(
        api,
        coordinator_headers,
        business_owner_id=estate["business_owner"]["id"],
        primary_site_id=estate["site_primary"]["id"],
        app_code="APP-EDGE",
        name="Edge portal",
        criticality_weight=8,
    )
    estate["app_edge"] = agree_application_tier(
        api,
        coordinator_headers,
        owner_headers,
        estate["app_edge"]["id"],
        proposed_tier="TIER_2",
        proposed_rto_minutes=45,
        proposed_rpo_minutes=60,
    )
    estate["asset_db"] = register_asset(
        api,
        operator_headers,
        site_id=estate["site_primary"]["id"],
        asset_code="AST-DB1",
        name="Ledger database",
        asset_kind="DATA_STORE",
        replication_mode="ASYNCHRONOUS",
        restore_minutes=20,
        expected_txn_rate_per_minute=150,
    )
    estate["asset_net"] = register_asset(
        api,
        operator_headers,
        site_id=estate["site_primary"]["id"],
        asset_code="AST-NET1",
        name="Core switch",
        asset_kind="INFRA_COMPONENT",
        replication_mode="SYNCHRONOUS",
        restore_minutes=12,
    )
    estate["group"] = create_recovery_group(
        api,
        coordinator_headers,
        recovery_site_id=estate["site_recovery"]["id"],
        lead_coordinator_id=estate["coordinator"]["id"],
        group_code="RG-1",
        name="Tier one group",
        recovery_order=1,
    )
    group_id = estate["group"]["id"]
    assign_application(api, coordinator_headers, estate["app_core"]["id"], group_id)
    assign_application(api, coordinator_headers, estate["app_edge"]["id"], group_id)
    assign_asset(api, coordinator_headers, estate["asset_db"]["id"], group_id)
    assign_asset(api, coordinator_headers, estate["asset_net"]["id"], group_id)
    estate["edge_core_db"] = create_dependency_edge(
        api,
        coordinator_headers,
        from_node_kind="APPLICATION",
        from_node_id=estate["app_core"]["id"],
        to_node_kind="ASSET",
        to_node_id=estate["asset_db"]["id"],
        edge_kind="HARD",
    )
    if through <= ESTATE_GRAPH_LINKED:
        return estate

    estate["edge_db_net"] = create_dependency_edge(
        api,
        coordinator_headers,
        from_node_kind="ASSET",
        from_node_id=estate["asset_db"]["id"],
        to_node_kind="ASSET",
        to_node_id=estate["asset_net"]["id"],
        edge_kind="HARD",
    )
    estate["runbook"] = open_runbook(
        api,
        coordinator_headers,
        group_id,
        estate["coordinator"]["id"],
        title="Ledger failover runbook",
        validity_days=180,
    )
    if through <= ESTATE_RUNBOOK_OPENED:
        return estate

    runbook_id = estate["runbook"]["id"]
    operator_id = estate["operator"]["id"]
    estate["step_core"] = add_step(
        api,
        coordinator_headers,
        runbook_id,
        operator_id,
        step_number=1,
        description="Promote the ledger replica",
        expected_minutes=15,
        weight=10,
        covers_application_id=estate["app_core"]["id"],
    )
    estate["step_db"] = add_step(
        api,
        coordinator_headers,
        runbook_id,
        operator_id,
        step_number=2,
        description="Open the database at the recovery site",
        expected_minutes=20,
        weight=10,
        covers_asset_id=estate["asset_db"]["id"],
    )
    estate["step_net"] = add_step(
        api,
        coordinator_headers,
        runbook_id,
        operator_id,
        step_number=3,
        description="Reroute the core switch",
        expected_minutes=12,
        weight=20,
        covers_asset_id=estate["asset_net"]["id"],
    )
    transition_runbook(api, coordinator_headers, runbook_id, "SUBMIT_FOR_REVIEW")
    for key in ("step_core", "step_db", "step_net"):
        estate[key] = validate_step(api, operator_headers, estate[key]["id"])
    estate["runbook"] = transition_runbook(api, coordinator_headers, runbook_id, "VALIDATE")
    estate["group"] = read_group(api, coordinator_headers, group_id)
    return estate


# --- The single-application estate ------------------------------------------


def setup_single_application_estate(api, through: int = CORE_RUNBOOK_VALIDATED) -> dict:
    """Build the smaller estate whose group projects 80 minutes behind a 100.00 runbook."""
    estate = {}
    estate["clock"] = CLOCK_EPOCH
    set_logical_clock(api, CLOCK_EPOCH)
    if through <= CORE_CLOCK_SET:
        return estate

    estate.update(_register_standard_people(api))
    if through <= CORE_PEOPLE_REGISTERED:
        return estate

    _register_standard_sites(api, estate)
    if through <= CORE_SITES_REGISTERED:
        return estate

    coordinator_headers = estate["coordinator_headers"]
    owner_headers = estate["owner_headers"]
    operator_headers = estate["operator_headers"]

    estate["app_core"] = register_application(
        api,
        coordinator_headers,
        business_owner_id=estate["business_owner"]["id"],
        primary_site_id=estate["site_primary"]["id"],
        app_code="APP-CORE",
        name="Core ledger",
        criticality_weight=10,
    )
    get_success_data(
        api.propose_application_tier(
            estate["app_core"]["id"],
            f.tier_proposal_payload("TIER_1", 60, 15, "Regulated ledger"),
            coordinator_headers,
        )
    )
    if through <= CORE_APPLICATION_PROPOSED:
        return estate

    estate["app_core"] = get_success_data(
        api.decide_application_tier(
            estate["app_core"]["id"],
            f.tier_decision_payload("AGREE", "Owner agrees the objectives"),
            owner_headers,
        )
    )
    if through <= CORE_APPLICATION_AGREED:
        return estate

    estate["asset_db"] = register_asset(
        api,
        operator_headers,
        site_id=estate["site_primary"]["id"],
        asset_code="AST-DB1",
        name="Ledger database",
        asset_kind="DATA_STORE",
        replication_mode="ASYNCHRONOUS",
        restore_minutes=20,
        expected_txn_rate_per_minute=150,
    )
    if through <= CORE_ASSET_REGISTERED:
        return estate

    estate["group"] = create_recovery_group(
        api,
        coordinator_headers,
        recovery_site_id=estate["site_recovery"]["id"],
        lead_coordinator_id=estate["coordinator"]["id"],
        group_code="RG-1",
        name="Ledger recovery group",
        recovery_order=1,
    )
    group_id = estate["group"]["id"]
    if through <= CORE_GROUP_CREATED:
        return estate

    assign_application(api, coordinator_headers, estate["app_core"]["id"], group_id)
    if through <= CORE_APPLICATION_ASSIGNED:
        return estate

    assign_asset(api, coordinator_headers, estate["asset_db"]["id"], group_id)
    if through <= CORE_ASSET_ASSIGNED:
        return estate

    estate["edge_core_db"] = create_dependency_edge(
        api,
        coordinator_headers,
        from_node_kind="APPLICATION",
        from_node_id=estate["app_core"]["id"],
        to_node_kind="ASSET",
        to_node_id=estate["asset_db"]["id"],
        edge_kind="HARD",
    )
    if through <= CORE_EDGE_CREATED:
        return estate

    estate["group"] = read_group(api, coordinator_headers, group_id)
    estate["group_version"] = estate["group"]["version"]
    if through <= CORE_GROUP_VERSION_READ:
        return estate

    estate["runbook"] = get_success_data(
        api.create_runbook(
            f.runbook_payload(
                group_id,
                estate["coordinator"]["id"],
                estate["group_version"],
                title="Ledger failover runbook",
                validity_days=180,
            ),
            coordinator_headers,
        )
    )
    if through <= CORE_RUNBOOK_OPENED:
        return estate

    estate["step_core"] = add_step(
        api,
        coordinator_headers,
        estate["runbook"]["id"],
        estate["operator"]["id"],
        step_number=1,
        description="Promote the ledger replica",
        expected_minutes=15,
        weight=10,
        covers_application_id=estate["app_core"]["id"],
    )
    if through <= CORE_STEP_ADDED:
        return estate

    transition_runbook(api, coordinator_headers, estate["runbook"]["id"], "SUBMIT_FOR_REVIEW")
    if through <= CORE_RUNBOOK_IN_REVIEW:
        return estate

    estate["step_core"] = validate_step(api, operator_headers, estate["step_core"]["id"])
    if through <= CORE_STEP_VALIDATED:
        return estate

    estate["runbook"] = transition_runbook(
        api, coordinator_headers, estate["runbook"]["id"], "VALIDATE"
    )
    estate["group"] = read_group(api, coordinator_headers, group_id)
    return estate


# --- Reusable group builder --------------------------------------------------


def setup_group_with_validated_runbook(
    api,
    estate: dict,
    site_id: str,
    group_code: str,
    name: str,
    recovery_order: int = 1,
    weight: int = 10,
    validity_days: Optional[int] = 180,
    step_description: str = "Bring the site online",
    expected_minutes: int = 30,
) -> dict:
    """Create a group whose runbook is VALIDATED through one coverless step."""
    coordinator_headers = estate["coordinator_headers"]
    group = create_recovery_group(
        api,
        coordinator_headers,
        recovery_site_id=site_id,
        lead_coordinator_id=estate["coordinator"]["id"],
        group_code=group_code,
        name=name,
        recovery_order=recovery_order,
    )
    runbook = open_runbook(
        api,
        coordinator_headers,
        group["id"],
        estate["coordinator"]["id"],
        title=f"{name} runbook",
        validity_days=validity_days,
    )
    step = add_step(
        api,
        coordinator_headers,
        runbook["id"],
        estate["operator"]["id"],
        step_number=1,
        description=step_description,
        expected_minutes=expected_minutes,
        weight=weight,
    )
    transition_runbook(api, coordinator_headers, runbook["id"], "SUBMIT_FOR_REVIEW")
    step = validate_step(api, estate["operator_headers"], step["id"])
    runbook = transition_runbook(api, coordinator_headers, runbook["id"], "VALIDATE")
    return {
        "group": read_group(api, coordinator_headers, group["id"]),
        "runbook": runbook,
        "step": step,
    }


# --- Composite exercise builders --------------------------------------------


def setup_scoped_exercise(
    api,
    estate: dict,
    name: str,
    planned_start_at: str,
    planned_end_at: str,
    exercise_type: str = "COMPONENT_FAILOVER",
    group_id: Optional[str] = None,
    site_id: Optional[str] = None,
) -> dict:
    """Create an exercise and bring one group into its scope."""
    exercise = create_exercise(
        api,
        estate["coordinator_headers"],
        recovery_site_id=site_id or estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at=planned_start_at,
        planned_end_at=planned_end_at,
        name=name,
        exercise_type=exercise_type,
    )
    scope_group(
        api,
        estate["coordinator_headers"],
        exercise["id"],
        group_id or estate["group"]["id"],
    )
    return read_exercise(api, estate["coordinator_headers"], exercise["id"])


def setup_approved_exercise(api, estate: dict, **kwargs) -> dict:
    """Take an exercise through scoping, impact submission and approval."""
    exercise = setup_scoped_exercise(api, estate, **kwargs)
    submit_impact(api, estate["coordinator_headers"], exercise["id"])
    approve_impact(api, estate["approver_headers"], exercise["id"])
    return read_exercise(api, estate["coordinator_headers"], exercise["id"])


def setup_scheduled_exercise(api, estate: dict, **kwargs) -> dict:
    exercise = setup_approved_exercise(api, estate, **kwargs)
    schedule(api, estate["coordinator_headers"], exercise["id"])
    return read_exercise(api, estate["coordinator_headers"], exercise["id"])


def setup_exercise_in_execution(api, estate: dict, **kwargs) -> dict:
    exercise = setup_scheduled_exercise(api, estate, **kwargs)
    drive_execution(api, estate["coordinator_headers"], exercise["id"], "START")
    return read_exercise(api, estate["coordinator_headers"], exercise["id"])


def setup_exercise_at_failover_complete(
    api,
    estate: dict,
    observation_at: str = CLOCK_EPOCH,
    elapsed_seconds: int = 750,
    **kwargs,
) -> dict:
    """Drive an exercise to FAILOVER_COMPLETE with one timed step and one observation."""
    record_replication_observation(
        api, estate["operator_headers"], estate["asset_db"]["id"], observation_at
    )
    exercise = setup_exercise_in_execution(api, estate, **kwargs)
    record_step_execution(
        api,
        estate["coordinator_headers"],
        exercise["id"],
        estate["step_core"]["id"],
        elapsed_seconds=elapsed_seconds,
        outcome="PASSED",
    )
    drive_execution(api, estate["coordinator_headers"], exercise["id"], "COMPLETE_FAILOVER")
    return read_exercise(api, estate["coordinator_headers"], exercise["id"])


# --- Scenario builders -------------------------------------------------------


def setup_recovery_time_variant_scenario(api) -> dict:
    """Two exercises with identical step rows and identical 80-minute wall spans."""
    estate = setup_two_application_estate(api)
    coordinator_headers = estate["coordinator_headers"]
    set_logical_clock(api, "2026-09-10T00:00:00Z")
    record_replication_observation(
        api,
        estate["operator_headers"],
        estate["asset_db"]["id"],
        "2026-09-09T23:55:00Z",
        replication_lag_seconds=240,
        unreplicated_txn_count=900,
    )
    rows = (
        (estate["step_core"]["id"], 750, "PASSED"),
        (estate["step_db"]["id"], 1230, "PASSED_WITH_ISSUE"),
        (estate["step_net"]["id"], 600, "SKIPPED"),
    )

    component = setup_scheduled_exercise(
        api,
        estate,
        name="DB tier component failover",
        exercise_type="COMPONENT_FAILOVER",
        planned_start_at="2026-09-10T02:00:00Z",
        planned_end_at="2026-09-10T08:00:00Z",
    )
    set_logical_clock(api, "2026-09-10T02:00:00Z")
    drive_execution(api, coordinator_headers, component["id"], "START")
    for step_id, seconds, outcome in rows:
        record_step_execution(
            api, coordinator_headers, component["id"], step_id, seconds, outcome
        )
    set_logical_clock(api, "2026-09-10T03:20:00Z")
    drive_execution(api, coordinator_headers, component["id"], "COMPLETE_FAILOVER")

    full_site = setup_scheduled_exercise(
        api,
        estate,
        name="Whole site failover rehearsal",
        exercise_type="FULL_SITE_FAILOVER",
        planned_start_at="2026-09-11T00:00:00Z",
        planned_end_at="2026-09-11T06:00:00Z",
    )
    set_logical_clock(api, "2026-09-11T00:00:00Z")
    drive_execution(api, coordinator_headers, full_site["id"], "START")
    for step_id, seconds, outcome in rows:
        record_step_execution(
            api, coordinator_headers, full_site["id"], step_id, seconds, outcome
        )
    set_logical_clock(api, "2026-09-11T01:20:00Z")

    estate["component_exercise"] = read_exercise(api, coordinator_headers, component["id"])
    estate["full_site_exercise"] = read_exercise(api, coordinator_headers, full_site["id"])
    return estate


def setup_recovery_point_variant_scenario(api) -> dict:
    """One lag-measured exercise, then a BATCH_SNAPSHOT store joins the same group."""
    estate = setup_two_application_estate(api)
    coordinator_headers = estate["coordinator_headers"]
    operator_headers = estate["operator_headers"]
    set_logical_clock(api, "2026-09-10T00:00:00Z")
    record_replication_observation(
        api,
        operator_headers,
        estate["asset_db"]["id"],
        "2026-09-09T23:55:00Z",
        replication_lag_seconds=240,
        unreplicated_txn_count=900,
    )

    lag_exercise = setup_scheduled_exercise(
        api,
        estate,
        name="Lag-measured component failover",
        planned_start_at="2026-09-10T02:00:00Z",
        planned_end_at="2026-09-10T08:00:00Z",
    )
    set_logical_clock(api, "2026-09-10T02:00:00Z")
    drive_execution(api, coordinator_headers, lag_exercise["id"], "START")
    record_step_execution(
        api, coordinator_headers, lag_exercise["id"], estate["step_core"]["id"], 750, "PASSED"
    )
    set_logical_clock(api, "2026-09-10T03:00:00Z")
    drive_execution(api, coordinator_headers, lag_exercise["id"], "COMPLETE_FAILOVER")

    estate["asset_snapshot"] = register_asset(
        api,
        operator_headers,
        site_id=estate["site_primary"]["id"],
        asset_code="AST-DB2",
        name="Batch warehouse",
        asset_kind="DATA_STORE",
        replication_mode="BATCH_SNAPSHOT",
        restore_minutes=25,
        expected_txn_rate_per_minute=150,
    )
    assign_asset(
        api, coordinator_headers, estate["asset_snapshot"]["id"], estate["group"]["id"]
    )
    # An observation may not be dated after the logical clock, so the clock moves
    # to the instant the batch store is observed before the row is appended.
    set_logical_clock(api, "2026-09-10T03:05:00Z")
    record_replication_observation(
        api,
        operator_headers,
        estate["asset_snapshot"]["id"],
        "2026-09-10T03:05:00Z",
        replication_lag_seconds=240,
        unreplicated_txn_count=900,
    )

    gap_exercise = setup_scheduled_exercise(
        api,
        estate,
        name="Gap-measured component failover",
        planned_start_at="2026-09-11T00:00:00Z",
        planned_end_at="2026-09-11T06:00:00Z",
    )
    set_logical_clock(api, "2026-09-11T00:00:00Z")
    drive_execution(api, coordinator_headers, gap_exercise["id"], "START")
    record_step_execution(
        api, coordinator_headers, gap_exercise["id"], estate["step_core"]["id"], 750, "PASSED"
    )
    set_logical_clock(api, "2026-09-11T00:20:00Z")

    estate["lag_exercise"] = read_exercise(api, coordinator_headers, lag_exercise["id"])
    estate["gap_exercise"] = read_exercise(api, coordinator_headers, gap_exercise["id"])
    return estate


def setup_three_equally_weighted_validated_steps(api) -> dict:
    """A runbook holding three weight-10 steps, all validated at the epoch."""
    estate = setup_two_application_estate(api, through=ESTATE_RUNBOOK_OPENED)
    coordinator_headers = estate["coordinator_headers"]
    runbook_id = estate["runbook"]["id"]
    operator_id = estate["operator"]["id"]
    estate["step_core"] = add_step(
        api,
        coordinator_headers,
        runbook_id,
        operator_id,
        step_number=1,
        description="Promote the ledger replica",
        expected_minutes=15,
        weight=10,
        covers_application_id=estate["app_core"]["id"],
    )
    estate["step_db"] = add_step(
        api,
        coordinator_headers,
        runbook_id,
        operator_id,
        step_number=2,
        description="Open the database at the recovery site",
        expected_minutes=20,
        weight=10,
        covers_asset_id=estate["asset_db"]["id"],
    )
    estate["step_net"] = add_step(
        api,
        coordinator_headers,
        runbook_id,
        operator_id,
        step_number=3,
        description="Reroute the core switch",
        expected_minutes=12,
        weight=10,
        covers_asset_id=estate["asset_net"]["id"],
    )
    transition_runbook(api, coordinator_headers, runbook_id, "SUBMIT_FOR_REVIEW")
    for key in ("step_core", "step_db", "step_net"):
        estate[key] = validate_step(api, estate["operator_headers"], estate[key]["id"])
    return estate


def setup_soft_edge_graph(api) -> dict:
    """The linked estate plus a SOFT edge that must never enter the projection."""
    estate = setup_two_application_estate(api, through=ESTATE_GRAPH_LINKED)
    estate["soft_edge"] = create_dependency_edge(
        api,
        estate["coordinator_headers"],
        from_node_kind="APPLICATION",
        from_node_id=estate["app_edge"]["id"],
        to_node_kind="APPLICATION",
        to_node_id=estate["app_core"]["id"],
        edge_kind="SOFT",
    )
    return estate


def setup_retest_scheduled_finding(api, severity: str = "HIGH") -> dict:
    """A finding scheduled for re-test on a second exercise scoping the same group."""
    estate = setup_two_application_estate(api)
    estate["source_exercise"] = setup_scoped_exercise(
        api,
        estate,
        name="Finding source exercise",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    estate["retest_exercise"] = setup_scoped_exercise(
        api,
        estate,
        name="Re-test vehicle exercise",
        planned_start_at="2026-09-20T00:00:00Z",
        planned_end_at="2026-09-20T06:00:00Z",
    )
    finding = raise_finding(
        api,
        estate["coordinator_headers"],
        estate["source_exercise"]["id"],
        estate["group"]["id"],
        severity=severity,
        title="Switch reroute needed manual intervention",
        description="Step 3 could not be automated.",
        due_at="2026-09-15T00:00:00Z",
    )
    coordinator_headers = estate["coordinator_headers"]
    drive_finding(
        api, coordinator_headers, finding["id"], "ASSIGN", owner_id=estate["operator"]["id"]
    )
    drive_finding(api, coordinator_headers, finding["id"], "REMEDIATE", note="Automation added")
    estate["finding"] = drive_finding(
        api,
        coordinator_headers,
        finding["id"],
        "SCHEDULE_RETEST",
        retest_exercise_id=estate["retest_exercise"]["id"],
    )
    return estate


def setup_cascade_a_scenario(api) -> dict:
    """A scheduled exercise standing on the group whose application is about to be re-tiered."""
    estate = setup_two_application_estate(api)
    estate["scheduled_exercise"] = setup_scheduled_exercise(
        api,
        estate,
        name="Cascade subject exercise",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    return estate


def setup_cascade_b_scenario(api) -> dict:
    """A CRITICAL finding that has already failed one re-test, plus three live exercises."""
    estate = setup_two_application_estate(api)
    coordinator_headers = estate["coordinator_headers"]
    estate["source_exercise"] = setup_scoped_exercise(
        api,
        estate,
        name="Freeze source exercise",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    estate["retest_exercise"] = setup_scoped_exercise(
        api,
        estate,
        name="Freeze retest vehicle",
        planned_start_at="2026-09-20T00:00:00Z",
        planned_end_at="2026-09-20T06:00:00Z",
    )
    estate["scheduled_exercise"] = setup_scheduled_exercise(
        api,
        estate,
        name="Scheduled site failover",
        exercise_type="FULL_SITE_FAILOVER",
        planned_start_at="2026-10-20T00:00:00Z",
        planned_end_at="2026-10-20T06:00:00Z",
    )
    finding = raise_finding(
        api,
        coordinator_headers,
        estate["source_exercise"]["id"],
        estate["group"]["id"],
        severity="CRITICAL",
        title="Database promotion lost committed transactions",
        description="Reconciliation found 900 missing rows.",
        due_at="2026-09-15T00:00:00Z",
    )
    operator_id = estate["operator"]["id"]
    retest_id = estate["retest_exercise"]["id"]
    drive_finding(api, coordinator_headers, finding["id"], "ASSIGN", owner_id=operator_id)
    drive_finding(api, coordinator_headers, finding["id"], "REMEDIATE", note="Synchronous commit")
    drive_finding(
        api, coordinator_headers, finding["id"], "SCHEDULE_RETEST", retest_exercise_id=retest_id
    )
    drive_finding(
        api,
        coordinator_headers,
        finding["id"],
        "RECORD_RETEST_RESULT",
        retest_result="FAILED",
        note="First re-test still lost rows",
    )
    drive_finding(api, coordinator_headers, finding["id"], "ASSIGN", owner_id=operator_id)
    drive_finding(api, coordinator_headers, finding["id"], "REMEDIATE", note="Quorum writes")
    estate["finding"] = drive_finding(
        api, coordinator_headers, finding["id"], "SCHEDULE_RETEST", retest_exercise_id=retest_id
    )
    return estate


def setup_frozen_group_with_control_group(api) -> dict:
    """Freeze the main group, then add an unfrozen group at another site's expense."""
    estate = setup_two_application_estate(api)
    coordinator_headers = estate["coordinator_headers"]
    source = setup_scoped_exercise(
        api,
        estate,
        name="Freeze source exercise",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    finding = raise_finding(
        api,
        coordinator_headers,
        source["id"],
        estate["group"]["id"],
        severity="CRITICAL",
        title="Recovery site network unusable under load",
        description="Core switch saturated at 40 percent of traffic.",
    )
    operator_id = estate["operator"]["id"]
    for note in ("Added a second uplink", "Replaced the switch"):
        drive_finding(api, coordinator_headers, finding["id"], "ASSIGN", owner_id=operator_id)
        drive_finding(api, coordinator_headers, finding["id"], "REMEDIATE", note=note)
        drive_finding(
            api,
            coordinator_headers,
            finding["id"],
            "SCHEDULE_RETEST",
            retest_exercise_id=source["id"],
        )
        drive_finding(
            api,
            coordinator_headers,
            finding["id"],
            "RECORD_RETEST_RESULT",
            retest_result="FAILED",
            note="Still saturated",
        )
    estate["finding"] = read_finding(api, coordinator_headers, finding["id"])
    estate["site_tertiary"] = register_site(
        api,
        site_code="SITE-T",
        name="Tertiary site",
        role="RECOVERY",
        usable_capacity_units=30,
    )
    control = setup_group_with_validated_runbook(
        api,
        estate,
        estate["site_recovery"]["id"],
        "RG-2",
        "Control group",
        recovery_order=2,
        step_description="Confirm control site paperwork",
        expected_minutes=10,
    )
    estate["control_group"] = control["group"]
    estate["control_runbook"] = control["runbook"]
    estate["tertiary_exercise"] = create_exercise(
        api,
        coordinator_headers,
        recovery_site_id=estate["site_tertiary"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-09-25T00:00:00Z",
        planned_end_at="2026-09-25T06:00:00Z",
        name="Tertiary-site rehearsal",
    )
    return estate


def setup_small_site_capacity_scenario(api) -> dict:
    """A six-unit recovery site with one six-unit and one two-unit approved exercise."""
    estate = setup_two_application_estate(api, through=ESTATE_PEOPLE_REGISTERED)
    estate["site_small"] = register_site(
        api,
        site_code="SITE-S",
        name="Small recovery site",
        role="RECOVERY",
        usable_capacity_units=6,
    )
    built = setup_group_with_validated_runbook(
        api,
        estate,
        estate["site_small"]["id"],
        "RG-S",
        "Small-site group",
        step_description="Bring the small site online",
    )
    estate["group"] = built["group"]
    estate["runbook"] = built["runbook"]
    estate["site_recovery"] = estate["site_small"]
    estate["big_exercise"] = setup_approved_exercise(
        api,
        estate,
        name="Full site at the small site",
        exercise_type="FULL_SITE_FAILOVER",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    estate["small_exercise"] = setup_approved_exercise(
        api,
        estate,
        name="One unit too many",
        exercise_type="COMPONENT_FAILOVER",
        planned_start_at="2026-08-21T00:00:00Z",
        planned_end_at="2026-08-21T04:00:00Z",
    )
    return estate


def setup_empty_group_baseline_scenario(api) -> dict:
    """A scheduled exercise on a group holding no member applications at all."""
    estate = setup_two_application_estate(api, through=ESTATE_SITES_REGISTERED)
    coordinator_headers = estate["coordinator_headers"]
    solo = register_application(
        api,
        coordinator_headers,
        business_owner_id=estate["business_owner"]["id"],
        primary_site_id=estate["site_primary"]["id"],
        app_code="APP-SOLO",
        name="Solo application",
        criticality_weight=5,
    )
    estate["solo_application"] = agree_application_tier(
        api,
        coordinator_headers,
        estate["owner_headers"],
        solo["id"],
        proposed_tier="TIER_2",
        proposed_rto_minutes=45,
        proposed_rpo_minutes=60,
    )
    built = setup_group_with_validated_runbook(
        api,
        estate,
        estate["site_recovery"]["id"],
        "RG-E",
        "Empty group",
        step_description="Announce the exercise bridge",
        expected_minutes=5,
    )
    estate["group"] = built["group"]
    estate["runbook"] = built["runbook"]
    estate["exercise"] = setup_scheduled_exercise(
        api,
        estate,
        name="Baseline boundary rehearsal",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    return estate


def setup_unagreed_coverage_scenario(api) -> dict:
    """A step covering an application whose tier proposal has not been agreed."""
    estate = setup_two_application_estate(api, through=ESTATE_SITES_REGISTERED)
    coordinator_headers = estate["coordinator_headers"]
    estate["negotiating_application"] = register_application(
        api,
        coordinator_headers,
        business_owner_id=estate["business_owner"]["id"],
        primary_site_id=estate["site_primary"]["id"],
        app_code="APP-NEG",
        name="Under negotiation",
        criticality_weight=7,
    )
    get_success_data(
        api.propose_application_tier(
            estate["negotiating_application"]["id"],
            f.tier_proposal_payload("TIER_1", 60, 15, "Proposed, not yet agreed"),
            coordinator_headers,
        )
    )
    estate["group"] = create_recovery_group(
        api,
        coordinator_headers,
        recovery_site_id=estate["site_recovery"]["id"],
        lead_coordinator_id=estate["coordinator"]["id"],
        group_code="RG-N",
        name="Negotiation group",
        recovery_order=1,
    )
    assign_application(
        api,
        coordinator_headers,
        estate["negotiating_application"]["id"],
        estate["group"]["id"],
    )
    estate["runbook"] = open_runbook(
        api,
        coordinator_headers,
        estate["group"]["id"],
        estate["coordinator"]["id"],
        title="Negotiation runbook",
        validity_days=180,
    )
    estate["step"] = add_step(
        api,
        coordinator_headers,
        estate["runbook"]["id"],
        estate["operator"]["id"],
        step_number=1,
        description="Fail over the application under negotiation",
        expected_minutes=25,
        weight=10,
        covers_application_id=estate["negotiating_application"]["id"],
    )
    transition_runbook(api, coordinator_headers, estate["runbook"]["id"], "SUBMIT_FOR_REVIEW")
    return estate


def setup_touching_windows_scenario(api) -> dict:
    """One scheduled window, one that touches its end and one that overlaps by a minute."""
    estate = setup_two_application_estate(api)
    estate["first_exercise"] = setup_scheduled_exercise(
        api,
        estate,
        name="First window",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    estate["touching_exercise"] = setup_approved_exercise(
        api,
        estate,
        name="Touching window",
        planned_start_at="2026-08-20T06:00:00Z",
        planned_end_at="2026-08-20T12:00:00Z",
    )
    estate["overlapping_exercise"] = setup_approved_exercise(
        api,
        estate,
        name="One minute of overlap",
        planned_start_at="2026-08-20T05:59:00Z",
        planned_end_at="2026-08-20T11:00:00Z",
    )
    return estate


def setup_change_freeze_scenario(api) -> dict:
    """A closed change freeze with one exercise touching its start and one clear of it."""
    estate = setup_two_application_estate(api)
    coordinator_headers = estate["coordinator_headers"]
    estate["group"] = get_success_data(
        api.set_change_freeze(
            estate["group"]["id"],
            f.change_freeze_payload("2026-08-20T06:00:00Z", "2026-08-25T00:00:00Z"),
            coordinator_headers,
        )
    )
    estate["touching_exercise"] = create_exercise(
        api,
        coordinator_headers,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
        name="Ends at the freeze boundary",
    )
    estate["clear_exercise"] = create_exercise(
        api,
        coordinator_headers,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T05:59:00Z",
        name="Ends a minute before the freeze",
    )
    return estate


def setup_two_approved_reservations(api) -> dict:
    """A six-unit and a two-unit exercise, both approved and awaiting scheduling."""
    estate = setup_two_application_estate(api)
    estate["big_exercise"] = setup_approved_exercise(
        api,
        estate,
        name="Big reservation",
        exercise_type="FULL_SITE_FAILOVER",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    estate["small_exercise"] = setup_approved_exercise(
        api,
        estate,
        name="Small reservation",
        exercise_type="COMPONENT_FAILOVER",
        planned_start_at="2026-08-21T00:00:00Z",
        planned_end_at="2026-08-21T04:00:00Z",
    )
    return estate


def setup_evidence_scenario(api) -> dict:
    """An exercise at FAILOVER_COMPLETE with a DRAFT evidence package against it."""
    estate = setup_two_application_estate(api)
    estate["exercise"] = setup_exercise_at_failover_complete(
        api,
        estate,
        elapsed_seconds=780,
        name="Evidence subject exercise",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    estate["package"] = open_evidence_package(
        api,
        estate["liaison_headers"],
        estate["exercise"]["id"],
        estate["audit_liaison"]["id"],
    )
    return estate
