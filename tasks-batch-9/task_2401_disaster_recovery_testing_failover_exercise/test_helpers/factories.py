"""Request-payload factories carrying PRD-valid defaults.

Each factory returns only the fields the PRD declares for that endpoint;
optional fields are emitted only when the caller supplies them, so that a test
exercising a declared default can simply omit the argument.
"""

import itertools
from typing import Optional

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short suffix that keeps codes and emails unique inside one test."""
    return str(next(_counter))


# --- Stakeholders ------------------------------------------------------------


def stakeholder_payload(
    full_name: str = "Cora Lin",
    email: Optional[str] = None,
    org_roles: Optional[list] = None,
    approval_authority_level: Optional[str] = None,
    **extra,
) -> dict:
    payload = {
        "full_name": full_name,
        "email": email or f"person{unique_suffix()}@example.com",
        "org_roles": org_roles or ["RESILIENCE_COORDINATOR"],
    }
    if approval_authority_level is not None:
        payload["approval_authority_level"] = approval_authority_level
    payload.update(extra)
    return payload


# --- Sites -------------------------------------------------------------------


def site_payload(
    site_code: Optional[str] = None,
    name: str = "Recovery campus",
    role: str = "RECOVERY",
    usable_capacity_units: Optional[int] = 40,
    **extra,
) -> dict:
    payload = {
        "name": name,
        "site_code": site_code or f"SITE-{unique_suffix()}",
        "role": role,
    }
    if usable_capacity_units is not None:
        payload["usable_capacity_units"] = usable_capacity_units
    payload.update(extra)
    return payload


# --- Applications ------------------------------------------------------------


def application_payload(
    business_owner_id: str,
    primary_site_id: str,
    app_code: Optional[str] = None,
    name: str = "Core ledger",
    criticality_weight: int = 10,
    **extra,
) -> dict:
    payload = {
        "name": name,
        "app_code": app_code or f"APP-{unique_suffix()}",
        "business_owner_id": business_owner_id,
        "primary_site_id": primary_site_id,
        "criticality_weight": criticality_weight,
    }
    payload.update(extra)
    return payload


def tier_proposal_payload(
    proposed_tier: str = "TIER_1",
    proposed_rto_minutes: int = 60,
    proposed_rpo_minutes: int = 15,
    rationale: Optional[str] = "Regulated ledger",
) -> dict:
    payload = {
        "proposed_tier": proposed_tier,
        "proposed_rto_minutes": proposed_rto_minutes,
        "proposed_rpo_minutes": proposed_rpo_minutes,
    }
    if rationale is not None:
        payload["rationale"] = rationale
    return payload


def tier_decision_payload(action: str = "AGREE", decision_note: Optional[str] = None) -> dict:
    payload = {"action": action}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def group_assignment_payload(recovery_group_id: str) -> dict:
    return {"recovery_group_id": recovery_group_id}


# --- Assets ------------------------------------------------------------------


def asset_payload(
    site_id: str,
    asset_code: Optional[str] = None,
    name: str = "Ledger database",
    asset_kind: str = "DATA_STORE",
    replication_mode: str = "ASYNCHRONOUS",
    restore_minutes: int = 20,
    expected_txn_rate_per_minute: Optional[int] = None,
    **extra,
) -> dict:
    payload = {
        "name": name,
        "asset_code": asset_code or f"AST-{unique_suffix()}",
        "asset_kind": asset_kind,
        "site_id": site_id,
        "replication_mode": replication_mode,
        "restore_minutes": restore_minutes,
    }
    if expected_txn_rate_per_minute is not None:
        payload["expected_txn_rate_per_minute"] = expected_txn_rate_per_minute
    payload.update(extra)
    return payload


def replication_observation_payload(
    observed_at: str,
    replication_lag_seconds: int = 240,
    unreplicated_txn_count: int = 900,
) -> dict:
    return {
        "observed_at": observed_at,
        "replication_lag_seconds": replication_lag_seconds,
        "unreplicated_txn_count": unreplicated_txn_count,
    }


# --- Dependency edges --------------------------------------------------------


def dependency_edge_payload(
    from_node_kind: str,
    from_node_id: str,
    to_node_kind: str,
    to_node_id: str,
    edge_kind: str = "HARD",
) -> dict:
    return {
        "from_node_kind": from_node_kind,
        "from_node_id": from_node_id,
        "to_node_kind": to_node_kind,
        "to_node_id": to_node_id,
        "edge_kind": edge_kind,
    }


# --- Recovery groups ---------------------------------------------------------


def recovery_group_payload(
    recovery_site_id: str,
    lead_coordinator_id: str,
    group_code: Optional[str] = None,
    name: str = "Ledger recovery group",
    recovery_order: int = 1,
    **extra,
) -> dict:
    payload = {
        "name": name,
        "group_code": group_code or f"RG-{unique_suffix()}",
        "recovery_site_id": recovery_site_id,
        "lead_coordinator_id": lead_coordinator_id,
        "recovery_order": recovery_order,
    }
    payload.update(extra)
    return payload


def change_freeze_payload(change_freeze_start_at: str, change_freeze_end_at: str) -> dict:
    return {
        "change_freeze_start_at": change_freeze_start_at,
        "change_freeze_end_at": change_freeze_end_at,
    }


# --- Runbooks ----------------------------------------------------------------


def runbook_payload(
    recovery_group_id: str,
    author_id: str,
    expected_recovery_group_version: int,
    title: str = "Ledger failover runbook",
    validity_days: Optional[int] = None,
) -> dict:
    payload = {
        "recovery_group_id": recovery_group_id,
        "title": title,
        "author_id": author_id,
        "expected_recovery_group_version": expected_recovery_group_version,
    }
    if validity_days is not None:
        payload["validity_days"] = validity_days
    return payload


def runbook_transition_payload(action: str, note: Optional[str] = None) -> dict:
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    return payload


def runbook_step_payload(
    runbook_id: str,
    owner_id: str,
    step_number: int = 1,
    description: str = "Promote the ledger replica",
    expected_minutes: int = 15,
    weight: int = 10,
    covers_application_id: Optional[str] = None,
    covers_asset_id: Optional[str] = None,
) -> dict:
    payload = {
        "runbook_id": runbook_id,
        "step_number": step_number,
        "description": description,
        "owner_id": owner_id,
        "expected_minutes": expected_minutes,
        "weight": weight,
    }
    if covers_application_id is not None:
        payload["covers_application_id"] = covers_application_id
    if covers_asset_id is not None:
        payload["covers_asset_id"] = covers_asset_id
    return payload


def step_validation_payload(validation_note: Optional[str] = "Walked end to end") -> dict:
    payload = {}
    if validation_note is not None:
        payload["validation_note"] = validation_note
    return payload


# --- Exercises ---------------------------------------------------------------


def exercise_payload(
    recovery_site_id: str,
    coordinator_id: str,
    planned_start_at: str,
    planned_end_at: str,
    name: str = "Quarterly rehearsal",
    exercise_type: str = "COMPONENT_FAILOVER",
    **extra,
) -> dict:
    payload = {
        "name": name,
        "exercise_type": exercise_type,
        "recovery_site_id": recovery_site_id,
        "coordinator_id": coordinator_id,
        "planned_start_at": planned_start_at,
        "planned_end_at": planned_end_at,
    }
    payload.update(extra)
    return payload


def scope_item_payload(recovery_group_id: str, expected_exercise_version: int) -> dict:
    return {
        "recovery_group_id": recovery_group_id,
        "expected_exercise_version": expected_exercise_version,
    }


def impact_decision_payload(action: str = "APPROVE", decision_note: Optional[str] = None) -> dict:
    payload = {"action": action}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def execution_transition_payload(action: str, reason: Optional[str] = None) -> dict:
    payload = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    return payload


def axis_transition_payload(action: str, note: Optional[str] = None) -> dict:
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    return payload


def step_execution_payload(
    runbook_step_id: str,
    outcome: str = "PASSED",
    elapsed_seconds: int = 750,
    notes: Optional[str] = None,
) -> dict:
    payload = {
        "runbook_step_id": runbook_step_id,
        "outcome": outcome,
        "elapsed_seconds": elapsed_seconds,
    }
    if notes is not None:
        payload["notes"] = notes
    return payload


# --- Findings ----------------------------------------------------------------


def finding_payload(
    exercise_id: str,
    recovery_group_id: str,
    severity: str = "HIGH",
    title: str = "Replica promotion was manual",
    description: str = "The runbook step required an unscripted manual promotion.",
    due_at: Optional[str] = None,
) -> dict:
    payload = {
        "exercise_id": exercise_id,
        "recovery_group_id": recovery_group_id,
        "severity": severity,
        "title": title,
        "description": description,
    }
    if due_at is not None:
        payload["due_at"] = due_at
    return payload


def finding_transition_payload(
    action: str,
    owner_id: Optional[str] = None,
    retest_exercise_id: Optional[str] = None,
    retest_result: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    payload = {"action": action}
    if owner_id is not None:
        payload["owner_id"] = owner_id
    if retest_exercise_id is not None:
        payload["retest_exercise_id"] = retest_exercise_id
    if retest_result is not None:
        payload["retest_result"] = retest_result
    if note is not None:
        payload["note"] = note
    return payload


# --- Evidence packages ------------------------------------------------------


def evidence_package_payload(exercise_id: str, prepared_by_id: str) -> dict:
    return {"exercise_id": exercise_id, "prepared_by_id": prepared_by_id}


def evidence_transition_payload(action: str, note: Optional[str] = None) -> dict:
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    return payload


# --- Logical clock ----------------------------------------------------------


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
