"""Composite setup helpers.

Every test starts against an empty database, so each helper below builds the
state it needs from scratch through the endpoints PRD §4 declares -- there is no
direct database seeding anywhere.

The helpers are layered:

* **Primitives** -- one call each, returning the created resource.
* **Tier 1, state progression** -- drive one resource to a named state
  (a change through submit/approve/merge, a flag onto its ladder).
* **Tier 2, entity hierarchy** -- assemble the parent chains
  (train + release, release + environments, change + dependency edge).
* **Tier 3, full lifecycle shortcuts** -- cut a release, take it into
  stabilization behind a started deployment, ship it.
* **Tier 4, accumulation and threshold targeting** -- land a release on a
  specific ledger or index value (a packet whose ``base_index`` is 75, a flag
  swept into ``ENFORCED``, a train whose risk budget is nearly exhausted).
* **Tier 5, finalization and terminal states** -- publish notes, seal a packet,
  archive a flag, roll a release back.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CLOCK_ORIGIN,
    RELEASE_CUT_AT,
    RELEASE_FREEZE_AT,
)
from .test_users import (
    APPROVER_USER_ID,
    CHANGE_APPROVER,
    COMPLIANCE_OFFICER,
    ENGINEER,
    ENGINEER_USER_ID,
    PLATFORM_ADMIN,
    RELEASE_MANAGER,
    SECOND_CHANGE_APPROVER,
    SRE,
)
from .types import (
    ApprovalKind,
    Cohort,
    EvidenceItem,
    IncidentSeverity,
    NoteAudience,
    RiskClass,
    TrainFreezeAction,
)

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, instant: str) -> str:
    """Reposition the logical clock and return the reported ``current_utc``."""
    data = validate_success(api.set_clock(instant, PLATFORM_ADMIN), 200)
    return data["current_utc"]


def reset_clock(api: ApiClient) -> str:
    """Return the clock to its startup instant."""
    return set_clock(api, CLOCK_ORIGIN)


def create_train(api: ApiClient, headers=RELEASE_MANAGER, **overrides) -> Dict[str, Any]:
    payload = f.make_release_train_payload(**overrides)
    return validate_success(api.create_release_train(payload, headers), 201)


def create_tight_budget_train(
    api: ApiClient, risk_budget_points: int = 40, **overrides
) -> Dict[str, Any]:
    """A train whose risk budget is small enough that a second approval breaches it."""
    return create_train(api, risk_budget_points=risk_budget_points, **overrides)


def create_environment(api: ApiClient, headers=PLATFORM_ADMIN, **overrides) -> Dict[str, Any]:
    payload = f.make_environment_payload(**overrides)
    return validate_success(api.create_environment(payload, headers), 201)


def create_prod_environment(api: ApiClient, **overrides) -> Dict[str, Any]:
    """A PROD environment whose daily window is 02:00-06:00 UTC."""
    return create_environment(api, **overrides)


def create_staging_environment(api: ApiClient, **overrides) -> Dict[str, Any]:
    payload = f.make_staging_environment_payload(**overrides)
    return validate_success(api.create_environment(payload, PLATFORM_ADMIN), 201)


def create_regulated_environment(api: ApiClient, **overrides) -> Dict[str, Any]:
    """A PROD environment marked regulated, so shipping needs a sealed packet."""
    defaults = {"name": "prod-regulated", "requires_compliance_evidence": True}
    defaults.update(overrides)
    return create_environment(api, **defaults)


def create_release(
    api: ApiClient, train_id: str, headers=RELEASE_MANAGER, **overrides
) -> Dict[str, Any]:
    payload = f.make_release_payload(**overrides)
    return validate_success(api.create_release(train_id, payload, headers), 201)


def create_flag(api: ApiClient, headers=ENGINEER, **overrides) -> Dict[str, Any]:
    payload = f.make_feature_flag_payload(**overrides)
    return validate_success(api.create_feature_flag(payload, headers), 201)


def create_change(
    api: ApiClient,
    release_id: str,
    headers=ENGINEER,
    payload: Optional[Dict[str, Any]] = None,
    **overrides,
) -> Dict[str, Any]:
    body = payload if payload is not None else f.make_change_request_payload(**overrides)
    return validate_success(api.create_change_request(release_id, body, headers), 201)


def read_flag(api: ApiClient, flag_id: str) -> Dict[str, Any]:
    return validate_success(api.get_feature_flag(flag_id, ENGINEER), 200)


def read_release(api: ApiClient, release_id: str) -> Dict[str, Any]:
    return validate_success(api.get_release(release_id, RELEASE_MANAGER), 200)


def read_change(api: ApiClient, change_id: str) -> Dict[str, Any]:
    return validate_success(api.get_change_request(change_id, ENGINEER), 200)


def read_step(api: ApiClient, step_id: str) -> Dict[str, Any]:
    return validate_success(api.get_rollout_step(step_id, ENGINEER), 200)


def read_deployment(api: ApiClient, deployment_id: str) -> Dict[str, Any]:
    return validate_success(api.get_deployment(deployment_id, SRE), 200)


def read_environment(api: ApiClient, environment_id: str) -> Dict[str, Any]:
    return validate_success(api.get_environment(environment_id, SRE), 200)


def read_train(api: ApiClient, train_id: str) -> Dict[str, Any]:
    return validate_success(api.get_release_train(train_id, RELEASE_MANAGER), 200)


def read_incident(api: ApiClient, incident_id: str) -> Dict[str, Any]:
    return validate_success(api.get_incident(incident_id, SRE), 200)


def read_note(
    api: ApiClient, release_id: str, note_id: str, headers=RELEASE_MANAGER
) -> Dict[str, Any]:
    """Re-read one release-notes document off its release listing."""
    rows, _ = validate_paginated(api.list_release_notes(release_id, headers))
    return next(row for row in rows if row["id"] == note_id)


def read_packet(
    api: ApiClient, release_id: str, packet_id: str, headers=COMPLIANCE_OFFICER
) -> Dict[str, Any]:
    """Re-read one evidence packet off its release listing."""
    rows, _ = validate_paginated(api.list_evidence_packets(release_id, headers))
    return next(row for row in rows if row["id"] == packet_id)


def current_flag_version(api: ApiClient, flag_id: str) -> int:
    """Re-read the flag so the next rung carries a fresh OCC token (PRD §2.7)."""
    return read_flag(api, flag_id)["version"]


def current_release_version(api: ApiClient, release_id: str) -> int:
    """Re-read the release so packet assembly carries a fresh OCC token (PRD §2.7)."""
    return read_release(api, release_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1 -- state progression
# ---------------------------------------------------------------------------


def submit_change(api: ApiClient, change_id: str, headers=ENGINEER) -> Dict[str, Any]:
    return validate_success(api.submit_change_request(change_id, {}, headers), 200)


def record_approval(
    api: ApiClient,
    change_id: str,
    kind: str,
    headers=None,
    decision: str = "APPROVE",
    **overrides,
) -> Dict[str, Any]:
    """Record one lane decision, defaulting to the role that lane requires."""
    if headers is None:
        headers = COMPLIANCE_OFFICER if kind == ApprovalKind.COMPLIANCE else CHANGE_APPROVER
    payload = f.make_approval_payload(kind=kind, decision=decision, **overrides)
    return validate_success(api.create_approval(change_id, payload, headers), 201)


def approve_all_required_lanes(
    api: ApiClient, change_id: str, risk_class: str
) -> List[Dict[str, Any]]:
    """Record every lane the change's ``risk_class`` requires, in lane order.

    A ``CAB`` decision is recorded by a second approver, because the board may
    not rubber-stamp its own technical review.
    """
    approvals: List[Dict[str, Any]] = []
    if risk_class == RiskClass.LOW:
        return approvals
    approvals.append(record_approval(api, change_id, ApprovalKind.TECHNICAL))
    if risk_class in (RiskClass.HIGH, RiskClass.CRITICAL):
        approvals.append(record_approval(api, change_id, ApprovalKind.COMPLIANCE))
    if risk_class == RiskClass.CRITICAL:
        approvals.append(
            record_approval(
                api, change_id, ApprovalKind.CAB, headers=SECOND_CHANGE_APPROVER
            )
        )
    return approvals


def merge_change(api: ApiClient, change_id: str, headers=ENGINEER) -> Dict[str, Any]:
    return validate_success(api.merge_change_request(change_id, {}, headers), 200)


def withdraw_change(
    api: ApiClient, change_id: str, headers=ENGINEER, **overrides
) -> Dict[str, Any]:
    payload = f.make_withdraw_payload(**overrides)
    return validate_success(api.withdraw_change_request(change_id, payload, headers), 200)


def submitted_change(
    api: ApiClient, release_id: str, headers=ENGINEER, payload=None, **overrides
) -> Dict[str, Any]:
    """Author then submit a change; the returned body is the submit response."""
    change = create_change(api, release_id, headers=headers, payload=payload, **overrides)
    return submit_change(api, change["id"], headers)


def approved_change(
    api: ApiClient, release_id: str, headers=ENGINEER, payload=None, **overrides
) -> Dict[str, Any]:
    """Author, submit, and record whatever lanes the pinned risk class demands."""
    change = submitted_change(
        api, release_id, headers=headers, payload=payload, **overrides
    )
    approve_all_required_lanes(api, change["id"], change["risk_class"])
    return read_change(api, change["id"])


def merged_change(
    api: ApiClient, release_id: str, headers=ENGINEER, payload=None, **overrides
) -> Dict[str, Any]:
    """Take a change all the way to ``MERGED``."""
    change = approved_change(
        api, release_id, headers=headers, payload=payload, **overrides
    )
    return merge_change(api, change["id"], headers)


def merged_low_change(api: ApiClient, release_id: str, headers=ENGINEER, **overrides):
    """A LOW change, which auto-approves on submit and then merges."""
    payload = f.make_low_risk_change_payload(**overrides)
    return merged_change(api, release_id, headers=headers, payload=payload)


def plan_step(
    api: ApiClient,
    flag_id: str,
    target_pct: float = 5,
    soak_minutes: int = 30,
    deployment_id: Optional[str] = None,
    headers=ENGINEER,
    expected_feature_flag_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Plan one rung, reading the flag first for its current OCC token."""
    version = (
        expected_feature_flag_version
        if expected_feature_flag_version is not None
        else current_flag_version(api, flag_id)
    )
    payload = f.make_rollout_step_payload(
        expected_feature_flag_version=version,
        target_pct=target_pct,
        soak_minutes=soak_minutes,
        **({"deployment_id": deployment_id} if deployment_id is not None else {}),
    )
    return validate_success(api.create_rollout_step(flag_id, payload, headers), 201)


def start_soak(api: ApiClient, step_id: str, headers=ENGINEER) -> Dict[str, Any]:
    return validate_success(api.start_soak(step_id, {}, headers), 200)


def apply_step(api: ApiClient, step_id: str, headers=ENGINEER) -> Dict[str, Any]:
    return validate_success(api.apply_step(step_id, {}, headers), 200)


def link_flag(
    api: ApiClient,
    change_id: str,
    flag_id: str,
    guard_kind: str = "PARTIAL",
    headers=ENGINEER,
) -> Dict[str, Any]:
    payload = f.make_flag_link_payload(flag_id, guard_kind=guard_kind)
    return validate_success(api.create_flag_link(change_id, payload, headers), 201)


def declare_dependency(
    api: ApiClient, change_id: str, prerequisite_id: str, headers=ENGINEER, **overrides
) -> Dict[str, Any]:
    payload = f.make_dependency_payload(prerequisite_id, **overrides)
    return validate_success(api.create_dependency(change_id, payload, headers), 201)


def soaking_flag(
    api: ApiClient,
    target_pct: float = 5,
    soak_minutes: int = 30,
    deployment_id: Optional[str] = None,
    **flag_overrides,
) -> Dict[str, Any]:
    """A flag whose first rung is ``SOAKING``; the flag is ``ACTIVE_ROLLING_OUT``.

    Returns ``{"flag": ..., "step": ...}`` with both bodies freshly read.
    """
    flag = create_flag(api, **flag_overrides)
    step = plan_step(
        api,
        flag["id"],
        target_pct=target_pct,
        soak_minutes=soak_minutes,
        deployment_id=deployment_id,
    )
    step = start_soak(api, step["id"])
    return {"flag": read_flag(api, flag["id"]), "step": step}


def flag_at_exposure(
    api: ApiClient,
    target_pct: float = 5,
    soak_minutes: int = 30,
    soak_end_instant: str = "2026-08-01T00:30:00Z",
    **flag_overrides,
) -> Dict[str, Any]:
    """A flag whose first rung has been applied, so its exposure equals ``target_pct``.

    The clock is advanced to ``soak_end_instant`` so the soak has elapsed; a step
    may be applied at exactly the instant its soak ends.
    """
    built = soaking_flag(
        api, target_pct=target_pct, soak_minutes=soak_minutes, **flag_overrides
    )
    set_clock(api, soak_end_instant)
    step = apply_step(api, built["step"]["id"])
    return {"flag": read_flag(api, built["flag"]["id"]), "step": step}


# ---------------------------------------------------------------------------
# Tier 2 -- entity hierarchy
# ---------------------------------------------------------------------------


def train_with_release(
    api: ApiClient,
    train_overrides: Optional[Dict[str, Any]] = None,
    release_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The standard cadence container plus one ``OPEN`` release on it."""
    train = create_train(api, **(train_overrides or {}))
    release = create_release(api, train["id"], **(release_overrides or {}))
    return {"train": train, "release": release}


def train_release_and_environments(
    api: ApiClient,
    train_overrides: Optional[Dict[str, Any]] = None,
    release_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Train, release, one PROD environment and one STAGING environment."""
    built = train_with_release(api, train_overrides, release_overrides)
    built["prod_env"] = create_prod_environment(api)
    built["staging_env"] = create_staging_environment(api)
    return built


def release_with_merged_low_change(
    api: ApiClient,
    train_overrides: Optional[Dict[str, Any]] = None,
    release_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A release carrying exactly one merged LOW change, merged before ``freeze_at``."""
    built = train_with_release(api, train_overrides, release_overrides)
    built["change"] = merged_low_change(api, built["release"]["id"])
    built["release"] = read_release(api, built["release"]["id"])
    return built


def change_with_prerequisite(
    api: ApiClient, release_id: str, headers=ENGINEER
) -> Dict[str, Any]:
    """Two changes on one release joined by a dependency edge.

    ``dependent`` names ``prerequisite`` as its prerequisite, so the dependent's
    ``dependency_depth`` becomes 1.
    """
    prerequisite = create_change(
        api, release_id, headers=headers, payload=f.make_low_risk_change_payload()
    )
    dependent = create_change(api, release_id, headers=headers)
    edge = declare_dependency(api, dependent["id"], prerequisite["id"], headers=headers)
    return {
        "prerequisite": read_change(api, prerequisite["id"]),
        "dependent": read_change(api, dependent["id"]),
        "edge": edge,
    }


# ---------------------------------------------------------------------------
# Tier 3 -- full lifecycle shortcuts
# ---------------------------------------------------------------------------


def cut_release_at_freeze(
    api: ApiClient, release_id: str, freeze_instant: str = RELEASE_FREEZE_AT
) -> Dict[str, Any]:
    """Advance the clock to the release's ``freeze_at`` and cut it there.

    A release may be cut at exactly its ``freeze_at``.
    """
    set_clock(api, freeze_instant)
    return validate_success(api.cut_release(release_id, {}, RELEASE_MANAGER), 200)


def cut_release_with_merged_low_change(
    api: ApiClient,
    train_overrides: Optional[Dict[str, Any]] = None,
    release_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Train, release, one merged LOW change, and the release cut at its ``freeze_at``."""
    built = release_with_merged_low_change(api, train_overrides, release_overrides)
    built["cut_response"] = cut_release_at_freeze(api, built["release"]["id"])
    built["release"] = read_release(api, built["release"]["id"])
    built["train"] = read_train(api, built["train"]["id"])
    return built


def cut_release_with_customer_facing_change(
    api: ApiClient,
    train_overrides: Optional[Dict[str, Any]] = None,
    release_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A cut release whose single merged LOW change qualifies for customer notes.

    The change is ``customer_facing`` **and** carries non-empty
    ``summary_customer_facing`` copy, so a ``CUSTOMER`` document generated from
    this release includes it.
    """
    reset_clock(api)
    built = train_with_release(api, train_overrides, release_overrides)
    built["change"] = merged_low_change(
        api,
        built["release"]["id"],
        title="Faster checkout",
        summary_internal="Internal detail of the checkout speedup.",
        customer_facing=True,
        summary_customer_facing="Checkout is now faster",
    )
    built["cut_response"] = cut_release_at_freeze(api, built["release"]["id"])
    built["release"] = read_release(api, built["release"]["id"])
    return built


def reserve_deployment(
    api: ApiClient,
    release_id: str,
    environment_id: str,
    window_start_at: str = "2026-08-11T02:00:00Z",
    window_end_at: str = "2026-08-11T04:00:00Z",
    canary: bool = False,
    headers=SRE,
    **overrides,
) -> Dict[str, Any]:
    maker = f.make_canary_deployment_payload if canary else f.make_deployment_payload
    payload = maker(
        environment_id,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        **overrides,
    )
    return validate_success(api.create_deployment(release_id, payload, headers), 201)


def start_deployment(
    api: ApiClient, deployment_id: str, start_instant: Optional[str] = None, headers=SRE
) -> Dict[str, Any]:
    """Start a scheduled deployment, optionally moving the clock into its window first."""
    if start_instant is not None:
        set_clock(api, start_instant)
    return validate_success(api.start_deployment(deployment_id, {}, headers), 200)


def ingest_signal(
    api: ApiClient,
    deployment_id: str,
    observed_at: str,
    request_count: int,
    error_count: int,
    latency_p95_ms: int,
    cohort: str = Cohort.CANARY,
    headers=SRE,
) -> Dict[str, Any]:
    payload = f.make_health_signal_payload(
        observed_at=observed_at,
        request_count=request_count,
        error_count=error_count,
        latency_p95_ms=latency_p95_ms,
        cohort=cohort,
    )
    return validate_success(api.create_health_signal(deployment_id, payload, headers), 201)


def run_canary_evaluation(
    api: ApiClient,
    deployment_id: str,
    window_start_at: str,
    window_end_at: str,
    headers=SRE,
) -> Dict[str, Any]:
    payload = f.make_canary_evaluation_payload(window_start_at, window_end_at)
    return validate_success(
        api.create_canary_evaluation(deployment_id, payload, headers), 201
    )


def complete_deployment(
    api: ApiClient, deployment_id: str, headers=SRE, **overrides
) -> Dict[str, Any]:
    payload = f.make_complete_payload(**overrides)
    return validate_success(api.complete_deployment(deployment_id, payload, headers), 200)


def stabilizing_release_with_deployment(
    api: ApiClient,
    start_instant: str = "2026-08-11T02:05:00Z",
    canary: bool = False,
    train_overrides: Optional[Dict[str, Any]] = None,
    release_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Cut a release, reserve a PROD window on it, and start the deployment.

    Starting a deployment is the only way a release enters stabilization, so the
    release comes back in ``phase`` ``STABILIZING``.
    """
    built = cut_release_with_merged_low_change(api, train_overrides, release_overrides)
    built["prod_env"] = create_prod_environment(api)
    deployment = reserve_deployment(
        api, built["release"]["id"], built["prod_env"]["id"], canary=canary
    )
    built["deployment"] = start_deployment(api, deployment["id"], start_instant)
    built["release"] = read_release(api, built["release"]["id"])
    return built


def released_release(
    api: ApiClient,
    start_instant: str = "2026-08-11T02:05:00Z",
    train_overrides: Optional[Dict[str, Any]] = None,
    release_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The whole happy path: cut, deploy, complete, and declare the release shipped.

    Its merged LOW change ends up ``DEPLOYED`` with ``deployment_verified`` true.
    """
    built = stabilizing_release_with_deployment(
        api,
        start_instant=start_instant,
        train_overrides=train_overrides,
        release_overrides=release_overrides,
    )
    complete_deployment(api, built["deployment"]["id"])
    built["ship_response"] = validate_success(
        api.ship_release(built["release"]["id"], {}, RELEASE_MANAGER), 200
    )
    built["release"] = read_release(api, built["release"]["id"])
    built["change"] = read_change(api, built["change"]["id"])
    built["deployment"] = read_deployment(api, built["deployment"]["id"])
    return built


def canary_deployment_in_soak(
    api: ApiClient,
    start_instant: str = "2026-08-11T02:00:00Z",
    first_sample_at: str = "2026-08-11T02:05:00Z",
    train_overrides: Optional[Dict[str, Any]] = None,
    release_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A CANARY deployment moved into ``CANARY_SOAK`` by its first canary sample."""
    built = stabilizing_release_with_deployment(
        api,
        start_instant=start_instant,
        canary=True,
        train_overrides=train_overrides,
        release_overrides=release_overrides,
    )
    built["first_signal"] = ingest_signal(
        api,
        built["deployment"]["id"],
        observed_at=first_sample_at,
        request_count=1,
        error_count=0,
        latency_p95_ms=100,
    )
    built["deployment"] = read_deployment(api, built["deployment"]["id"])
    return built


# ---------------------------------------------------------------------------
# Tier 4 -- accumulation and threshold targeting
# ---------------------------------------------------------------------------


def evidence_packet_at_base_index_75(
    api: ApiClient,
    train_overrides: Optional[Dict[str, Any]] = None,
    release_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A DRAFT packet whose ``base_index`` is 75.

    The release carries one merged LOW change, so ``approvals_complete`` (25),
    ``rollback_plans`` (20), ``freeze_discipline`` (15) and ``flag_hygiene`` (15)
    are satisfied while ``canary_pass`` and ``release_notes`` are not.
    """
    built = cut_release_with_merged_low_change(api, train_overrides, release_overrides)
    built["packet"] = assemble_packet(api, built["release"]["id"])
    built["release"] = read_release(api, built["release"]["id"])
    return built


def assemble_packet(api: ApiClient, release_id: str, headers=COMPLIANCE_OFFICER):
    """Assemble a packet, reading the release first for a current OCC token."""
    payload = f.make_evidence_packet_payload(current_release_version(api, release_id))
    return validate_success(api.create_evidence_packet(release_id, payload, headers), 201)


def waive_item(
    api: ApiClient, packet_id: str, item_code: str, headers=COMPLIANCE_OFFICER
) -> Dict[str, Any]:
    payload = f.make_waiver_payload(item_code)
    return validate_success(api.create_waiver(packet_id, payload, headers), 200)


def run_cleanup_sweep(api: ApiClient, headers=COMPLIANCE_OFFICER) -> Dict[str, Any]:
    return validate_success(api.create_cleanup_sweep({}, headers), 200)


def stale_flag_swept_to_enforced(
    api: ApiClient,
    key: str = "legacy-toggle",
    expires_at: str = "2026-07-17T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """An orphan flag 15 whole days past its deadline, swept into ``ENFORCED``.

    Fifteen whole days overdue is 45 points, plus 15 points for having no
    change-to-flag links at all, which is 60 -- and exactly 60 points is
    ``ENFORCED``.
    """
    flag = create_flag(api, key=key, expires_at=expires_at, **overrides)
    summary = run_cleanup_sweep(api)
    return {"flag": read_flag(api, flag["id"]), "sweep": summary}


def frozen_train_with_blocked_dependent(
    api: ApiClient,
    train_overrides: Optional[Dict[str, Any]] = None,
    release_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A release whose in-flight change is deferred and whose dependent is blocked.

    Before the freeze: ``prerequisite`` sits in ``RISK_CLASSIFIED`` and
    ``dependent`` is ``APPROVED`` with its ledger contribution charged.  After
    the ``FREEZE`` the prerequisite is ``DEFERRED`` and the dependent is
    ``BLOCKED_BY_DEPENDENCY`` with the ledger compensated.
    """
    built = train_with_release(api, train_overrides, release_overrides)
    release_id = built["release"]["id"]

    prerequisite = submitted_change(
        api, release_id, payload=f.make_change_request_payload(title="Prerequisite work")
    )
    dependent = create_change(api, release_id, title="Dependent work")
    declare_dependency(api, dependent["id"], prerequisite["id"])
    dependent = submit_change(api, dependent["id"])
    approve_all_required_lanes(api, dependent["id"], dependent["risk_class"])

    built["prerequisite"] = read_change(api, prerequisite["id"])
    built["dependent"] = read_change(api, dependent["id"])
    built["release"] = read_release(api, release_id)
    return built


def freeze_train(api: ApiClient, train_id: str, headers=RELEASE_MANAGER):
    payload = f.make_freeze_state_payload(TrainFreezeAction.FREEZE)
    return validate_success(api.set_train_freeze_state(train_id, payload, headers), 200)


def unfreeze_train(api: ApiClient, train_id: str, headers=RELEASE_MANAGER):
    payload = f.make_freeze_state_payload(TrainFreezeAction.UNFREEZE)
    return validate_success(api.set_train_freeze_state(train_id, payload, headers), 200)


# ---------------------------------------------------------------------------
# Tier 5 -- finalization and terminal states
# ---------------------------------------------------------------------------


def generate_notes(
    api: ApiClient,
    release_id: str,
    audience: str = NoteAudience.CUSTOMER,
    headers=RELEASE_MANAGER,
) -> Dict[str, Any]:
    payload = f.make_release_notes_payload(audience)
    return validate_success(api.create_release_notes(release_id, payload, headers), 201)


def publish_notes(api: ApiClient, note_id: str, headers=RELEASE_MANAGER) -> Dict[str, Any]:
    return validate_success(api.publish_release_notes(note_id, {}, headers), 200)


def published_customer_notes(
    api: ApiClient, release_id: str, headers=RELEASE_MANAGER
) -> Dict[str, Any]:
    """Generate and publish CUSTOMER notes, which is itself an evidence item."""
    note = generate_notes(api, release_id, NoteAudience.CUSTOMER, headers)
    return publish_notes(api, note["id"], headers)


def seal_packet(api: ApiClient, packet_id: str, headers=COMPLIANCE_OFFICER):
    return validate_success(api.seal_evidence_packet(packet_id, {}, headers), 200)


def archive_flag(api: ApiClient, flag_id: str, headers=ENGINEER) -> Dict[str, Any]:
    return validate_success(api.archive_flag(flag_id, {}, headers), 200)


def pause_flag(api: ApiClient, flag_id: str, headers=ENGINEER, **overrides):
    payload = f.make_pause_payload(**overrides)
    return validate_success(api.pause_flag(flag_id, payload, headers), 200)


def resume_flag(api: ApiClient, flag_id: str, headers=ENGINEER, **overrides):
    payload = f.make_pause_payload(**overrides)
    return validate_success(api.resume_flag(flag_id, payload, headers), 200)


def report_incident(
    api: ApiClient, train_id: str, detected_at: str, headers=SRE, **overrides
) -> Dict[str, Any]:
    payload = f.make_incident_payload(train_id, detected_at, **overrides)
    return validate_success(api.create_incident(payload, headers), 201)


def decide_incident(
    api: ApiClient, incident_id: str, decision: str, headers=SRE, **overrides
) -> Dict[str, Any]:
    payload = f.make_incident_decision_payload(decision, **overrides)
    return validate_success(api.decide_incident(incident_id, payload, headers), 200)


def rollback_deployment(api: ApiClient, deployment_id: str, headers=SRE, **overrides):
    payload = f.make_complete_payload(**overrides)
    return validate_success(api.rollback_deployment(deployment_id, payload, headers), 200)


# ---------------------------------------------------------------------------
# Lenient readers, for setup steps whose exact status is not the point
# ---------------------------------------------------------------------------


def data_of(response) -> Dict[str, Any]:
    """Extract ``data`` without asserting a status code."""
    return get_success_data(response)


#: Convenience re-export so tests can reference the pinned scenario instants.
SCENARIO = {
    "clock_origin": CLOCK_ORIGIN,
    "cut_at": RELEASE_CUT_AT,
    "freeze_at": RELEASE_FREEZE_AT,
}

#: Opaque operator ids the composite helpers thread through ownership checks.
DEFAULT_AUTHOR_USER_ID = ENGINEER_USER_ID
DEFAULT_FLAG_OWNER_USER_ID = ENGINEER_USER_ID
DEFAULT_APPROVER_USER_ID = APPROVER_USER_ID
DEFAULT_EVIDENCE_ITEMS = EvidenceItem.ALL


# ---------------------------------------------------------------------------
# Tier 6 -- pinned multi-hop scenarios
#
# Each builder assembles one named situation exactly once, in the order the PRD
# pins for the operations involved, and returns every resource plus the
# intermediate readings a caller needs to compare "before" against "after".
# The builders stop short of the act under test so the caller performs it.
# ---------------------------------------------------------------------------


def scenario_change_pair_awaiting_dependency_depth(api: ApiClient) -> Dict[str, Any]:
    """A submitted HIGH change that only afterwards gains a prerequisite.

    ``change_a`` is submitted first, so its preliminary score is pinned with a
    prerequisite depth of zero; the dependency edge onto ``change_b`` is declared
    afterwards, which is what makes the final score diverge at approval time.
    """
    reset_clock(api)
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    change_a = create_change(
        api,
        release["id"],
        payload=f.make_high_risk_change_payload(
            title="Shard the write path",
            summary_internal="Split primary writes across two shards",
        ),
    )
    change_b = create_change(
        api,
        release["id"],
        payload=f.make_low_risk_change_payload(
            title="Raise default page size",
            summary_internal="Config-only default bump",
        ),
    )
    submitted_a = submit_change(api, change_a["id"])
    submit_change(api, change_b["id"])
    declare_dependency(
        api,
        change_a["id"],
        change_b["id"],
        note="needs the new page-size default first",
    )
    return {
        "train": train,
        "release": release,
        "change_a": change_a,
        "change_b": change_b,
        "preliminary_score_a": submitted_a["risk_score_preliminary"],
    }


def scenario_release_ready_to_cut_with_deferrable_change(api: ApiClient) -> Dict[str, Any]:
    """One LOW change merged before ``freeze_at`` and one MEDIUM change still in flight.

    The clock is left standing exactly on the release's ``freeze_at`` so the cut
    precondition holds, and the projected score is captured before the cut.
    """
    reset_clock(api)
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    change_low = create_change(
        api,
        release["id"],
        payload=f.make_low_risk_change_payload(
            title="Copy tweak", summary_internal="Trivial copy change"
        ),
    )
    change_medium = create_change(
        api,
        release["id"],
        payload=f.make_change_request_payload(
            title="Retry policy rewrite",
            summary_internal="New backoff policy across two subsystems",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        ),
    )
    submit_change(api, change_low["id"])
    # Return the *submitted* medium change: the create response is still DRAFT
    # with a null risk_score_preliminary, and submission is what pins the score
    # and the tier.
    submitted_medium = submit_change(api, change_medium["id"])
    merge_change(api, change_low["id"])
    before_cut = read_release(api, release["id"])
    set_clock(api, RELEASE_FREEZE_AT)
    return {
        "train": train,
        "release": release,
        "change_low": change_low,
        "change_medium": submitted_medium,
        "projected_before_cut": before_cut["readiness_score_projected"],
    }


def scenario_canary_deployment_with_mixed_cohort_samples(api: ApiClient) -> Dict[str, Any]:
    """A running PROD canary carrying three canary samples and one baseline sample.

    Two canary samples sit inside the analysis window, the baseline sample sits
    inside it but is excluded from every term, and the third canary sample sits
    exactly on the window's exclusive end instant.
    """
    reset_clock(api)
    environment = create_prod_environment(
        api, cooldown_minutes=30, requires_compliance_evidence=False
    )
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    cut_release_at_freeze(api, release["id"])
    deployment = reserve_deployment(
        api,
        release["id"],
        environment["id"],
        window_start_at="2026-08-10T02:00:00Z",
        window_end_at="2026-08-10T04:00:00Z",
        canary=True,
        abort_error_rate_pct=25.0,
        abort_latency_p95_ms=800,
        canary_pct=10,
        min_sample_count=5,
    )
    start_deployment(api, deployment["id"], "2026-08-10T02:05:00Z")
    ingest_signal(api, deployment["id"], "2026-08-10T02:10:00Z", 6, 1, 300)
    ingest_signal(
        api,
        deployment["id"],
        "2026-08-10T02:15:00Z",
        100,
        0,
        100,
        cohort=Cohort.BASELINE,
    )
    ingest_signal(api, deployment["id"], "2026-08-10T02:20:00Z", 3, 1, 420)
    ingest_signal(api, deployment["id"], "2026-08-10T02:30:00Z", 10, 10, 900)
    set_clock(api, "2026-08-10T02:31:00Z")
    return {
        "environment": environment,
        "train": train,
        "release": release,
        "deployment": deployment,
    }


def scenario_draft_packet_on_open_release(api: ApiClient) -> Dict[str, Any]:
    """A DRAFT evidence packet on a release carrying one merged LOW change.

    No production deployment exists and no customer notes are published, so the
    packet's satisfied items are approvals, rollback plans, freeze discipline and
    flag hygiene.
    """
    reset_clock(api)
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    change = create_change(
        api,
        release["id"],
        payload=f.make_low_risk_change_payload(
            title="Tighten log redaction", summary_internal="Small redaction fix"
        ),
    )
    submit_change(api, change["id"])
    merge_change(api, change["id"])
    packet = assemble_packet(api, release["id"])
    return {
        "train": train,
        "release": release,
        "change": change,
        "packet": packet,
    }


def scenario_critical_and_low_changes_authored(api: ApiClient) -> Dict[str, Any]:
    """Two unsubmitted changes on one release, one scoring CRITICAL and one LOW."""
    reset_clock(api)
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    change_critical = create_change(
        api,
        release["id"],
        payload=f.make_critical_risk_change_payload(
            title="Global billing engine swap",
            summary_internal="Replace the billing engine across six subsystems",
            rollback_plan="RB-77 dual-write rollback",
            rollback_tested=True,
        ),
    )
    change_low = create_change(
        api,
        release["id"],
        payload=f.make_low_risk_change_payload(
            title="Fix typo in admin nav", summary_internal="One-line label fix"
        ),
    )
    return {
        "train": train,
        "release": release,
        "change_critical": change_critical,
        "change_low": change_low,
    }


def scenario_released_release_with_rolling_flag_and_open_incident(
    api: ApiClient,
) -> Dict[str, Any]:
    """A shipped release, a completed PROD deployment, a laddering flag, and a SEV1.

    The flag guards the release's deployed change; its first rung is applied, its
    second rung is soaking and its third rung is still planned, which is exactly
    the shape a release rollback has to clean up.
    """
    reset_clock(api)
    environment = create_prod_environment(
        api, cooldown_minutes=30, requires_compliance_evidence=False
    )
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    change = create_change(
        api,
        release["id"],
        payload=f.make_low_risk_change_payload(
            title="Search reranker rollout",
            summary_internal="Ship the reranker behind a flag",
            customer_facing=True,
            summary_customer_facing="Smarter search results",
        ),
    )
    submit_change(api, change["id"])
    merge_change(api, change["id"])
    cut_release_at_freeze(api, release["id"])
    deployment = reserve_deployment(
        api,
        release["id"],
        environment["id"],
        window_start_at="2026-08-10T02:00:00Z",
        window_end_at="2026-08-10T04:00:00Z",
        abort_error_rate_pct=25.0,
        abort_latency_p95_ms=800,
    )
    start_deployment(api, deployment["id"], "2026-08-10T02:05:00Z")
    complete_deployment(api, deployment["id"])
    validate_success(api.ship_release(release["id"], {}, RELEASE_MANAGER), 200)

    flag = create_flag(api, key="search-rerank")
    link_flag(api, change["id"], flag["id"], guard_kind="GATES_ENTIRE_CHANGE")
    step_one = plan_step(api, flag["id"], target_pct=5, soak_minutes=30)
    start_soak(api, step_one["id"])
    set_clock(api, "2026-08-10T02:35:00Z")
    apply_step(api, step_one["id"])
    step_two = plan_step(api, flag["id"], target_pct=15, soak_minutes=60)
    start_soak(api, step_two["id"])
    step_three = plan_step(api, flag["id"], target_pct=15, soak_minutes=60)

    set_clock(api, "2026-08-10T03:00:00Z")
    incident = report_incident(api, train["id"], "2026-08-10T03:00:00Z")
    return {
        "environment": environment,
        "train": train,
        "release": release,
        "change": change,
        "deployment": deployment,
        "flag": flag,
        "step_one": step_one,
        "step_two": step_two,
        "step_three": step_three,
        "incident": incident,
    }


def scenario_train_with_approved_dependent_before_freeze(api: ApiClient) -> Dict[str, Any]:
    """An in-flight prerequisite and an APPROVED dependent whose ledger is charged.

    The dependent's final score already includes the five points its one level of
    prerequisite depth adds, so the compensation the freeze performs is visible.
    """
    reset_clock(api)
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    prerequisite = create_change(
        api,
        release["id"],
        payload=f.make_change_request_payload(
            title="Introduce shared cache client",
            summary_internal="Prerequisite library extraction",
            lines_changed=200,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        ),
    )
    dependent = create_change(
        api,
        release["id"],
        payload=f.make_change_request_payload(
            title="Adopt shared cache client",
            summary_internal="Consumer migration onto the new client",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        ),
    )
    submit_change(api, prerequisite["id"])
    submit_change(api, dependent["id"])
    declare_dependency(
        api,
        dependent["id"],
        prerequisite["id"],
        note="must land after the library extraction",
    )
    record_approval(api, dependent["id"], ApprovalKind.TECHNICAL)
    before = read_release(api, release["id"])
    return {
        "train": train,
        "release": release,
        "prerequisite": prerequisite,
        "dependent": dependent,
        "budget_before": before["risk_budget_consumed_points"],
        "committed_before": before["committed_change_count"],
    }


def scenario_two_reserved_windows_one_running(api: ApiClient) -> Dict[str, Any]:
    """One IN_PROGRESS deployment and one still SCHEDULED, with the clock past both windows.

    The second window begins exactly where the first window's cooldown-extended
    occupancy ends, which is why reserving it was accepted.
    """
    reset_clock(api)
    environment = create_prod_environment(
        api, cooldown_minutes=30, requires_compliance_evidence=False
    )
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    cut_release_at_freeze(api, release["id"])
    running = reserve_deployment(
        api,
        release["id"],
        environment["id"],
        window_start_at="2026-08-10T02:00:00Z",
        window_end_at="2026-08-10T04:00:00Z",
        abort_error_rate_pct=25.0,
        abort_latency_p95_ms=800,
    )
    scheduled = reserve_deployment(
        api,
        release["id"],
        environment["id"],
        window_start_at="2026-08-10T04:30:00Z",
        window_end_at="2026-08-10T05:30:00Z",
        abort_error_rate_pct=25.0,
        abort_latency_p95_ms=800,
    )
    start_deployment(api, running["id"], "2026-08-10T02:05:00Z")
    set_clock(api, "2026-08-10T05:45:00Z")
    return {
        "environment": environment,
        "release": release,
        "running_deployment": running,
        "scheduled_deployment": scheduled,
    }


def scenario_medium_change_authored_by_dual_role_operator(api: ApiClient) -> Dict[str, Any]:
    """A MEDIUM change whose author also holds the approver role.

    The same opaque operator id authored the change, so any approval that id
    records is a self-approval regardless of which lane it names.
    """
    from .test_users import DUAL_ROLE_ENGINEER

    reset_clock(api)
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    change = create_change(
        api,
        release["id"],
        headers=DUAL_ROLE_ENGINEER,
        payload=f.make_change_request_payload(
            title="Queue consumer refactor",
            summary_internal="Refactor the two queue consumers",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        ),
    )
    submit_change(api, change["id"], headers=DUAL_ROLE_ENGINEER)
    return {"train": train, "release": release, "change": change}


def scenario_boundary_risk_change_pair(api: ApiClient) -> Dict[str, Any]:
    """Two unsubmitted schema migrations differing only in subsystem breadth.

    Five subsystems put the raw total on the HIGH boundary exactly; four leave it
    one band lower.
    """
    reset_clock(api)
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    change_on_boundary = create_change(
        api,
        release["id"],
        payload=f.make_change_request_payload(
            title="Migrate five subsystems to the new schema",
            summary_internal="Schema migration touching five subsystems",
            lines_changed=100,
            touched_subsystem_count=5,
            has_schema_migration=True,
            declared_blast_radius="INTERNAL",
        ),
    )
    change_below_boundary = create_change(
        api,
        release["id"],
        payload=f.make_change_request_payload(
            title="Migrate four subsystems to the new schema",
            summary_internal="Schema migration touching four subsystems",
            lines_changed=100,
            touched_subsystem_count=4,
            has_schema_migration=True,
            declared_blast_radius="INTERNAL",
        ),
    )
    return {
        "train": train,
        "release": release,
        "change_on_boundary": change_on_boundary,
        "change_below_boundary": change_below_boundary,
    }


def scenario_staging_canary_with_sample_outside_window(api: ApiClient) -> Dict[str, Any]:
    """A STAGING canary whose only canary sample lies outside the analysis window."""
    reset_clock(api)
    environment = create_staging_environment(api)
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    cut_release_at_freeze(api, release["id"])
    deployment = reserve_deployment(
        api,
        release["id"],
        environment["id"],
        window_start_at="2026-08-10T02:00:00Z",
        window_end_at="2026-08-10T04:00:00Z",
        canary=True,
        abort_error_rate_pct=25.0,
        abort_latency_p95_ms=800,
        canary_pct=10,
        min_sample_count=5,
    )
    start_deployment(api, deployment["id"], "2026-08-10T02:05:00Z")
    ingest_signal(api, deployment["id"], "2026-08-10T03:00:00Z", 10, 0, 200)
    set_clock(api, "2026-08-10T03:05:00Z")
    return {
        "environment": environment,
        "release": release,
        "deployment": deployment,
    }


def scenario_staging_canary_with_one_healthy_sample(api: ApiClient) -> Dict[str, Any]:
    """A STAGING canary carrying one flawless canary sample at ``2026-08-10T02:40Z``.

    Ten requests with no errors and a p95 of 200 ms sit inside the second of two
    analysis windows: the window ``02:00``--``02:30`` sees no sample at all while
    the window ``02:30``--``02:45`` sees all ten requests.
    """
    reset_clock(api)
    environment = create_staging_environment(api)
    train = create_train(api)
    release = create_release(api, train["id"])
    cut_release_at_freeze(api, release["id"])
    reserved = reserve_deployment(
        api,
        release["id"],
        environment["id"],
        window_start_at="2026-08-10T02:00:00Z",
        window_end_at="2026-08-10T04:00:00Z",
        canary=True,
        abort_error_rate_pct=25.0,
        abort_latency_p95_ms=800,
        canary_pct=10,
        min_sample_count=5,
    )
    start_deployment(api, reserved["id"], "2026-08-10T02:05:00Z")
    ingest_signal(api, reserved["id"], "2026-08-10T02:40:00Z", 10, 0, 200)
    set_clock(api, "2026-08-10T02:45:00Z")
    return {
        "environment": environment,
        "release": release,
        "reserved": reserved,
        "deployment": read_deployment(api, reserved["id"]),
    }


def scenario_open_release_and_environment(api: ApiClient) -> Dict[str, Any]:
    """A registered PROD environment and a release still in ``phase`` ``OPEN``.

    The clock stands before the release's ``freeze_at``, so the release cannot yet
    be cut.
    """
    reset_clock(api)
    environment = create_prod_environment(
        api, cooldown_minutes=30, requires_compliance_evidence=False
    )
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    return {"environment": environment, "train": train, "release": release}


def scenario_flag_guarding_merged_change(api: ApiClient) -> Dict[str, Any]:
    """A planned rung on a flag whose only guarded change is merely ``MERGED``."""
    reset_clock(api)
    environment = create_prod_environment(
        api, cooldown_minutes=30, requires_compliance_evidence=False
    )
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    change = create_change(
        api,
        release["id"],
        payload=f.make_low_risk_change_payload(
            title="Search reranker rollout",
            summary_internal="Ship the reranker behind a flag",
        ),
    )
    submit_change(api, change["id"])
    merge_change(api, change["id"])
    flag = create_flag(api, key="search-rerank")
    link_flag(api, change["id"], flag["id"], guard_kind="GATES_ENTIRE_CHANGE")
    step = plan_step(api, flag["id"], target_pct=5, soak_minutes=30)
    return {
        "environment": environment,
        "train": train,
        "release": release,
        "change": change,
        "flag": flag,
        "step": step,
    }


def ship_the_release_through_production(
    api: ApiClient,
    release_id: str,
    environment_id: str,
    window_start_at: str = "2026-08-10T02:00:00Z",
    window_end_at: str = "2026-08-10T04:00:00Z",
    start_instant: str = "2026-08-10T02:05:00Z",
) -> Dict[str, Any]:
    """Cut, deploy, complete and ship one release, returning the deployment used."""
    cut_release_at_freeze(api, release_id)
    deployment = reserve_deployment(
        api,
        release_id,
        environment_id,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        abort_error_rate_pct=25.0,
        abort_latency_p95_ms=800,
    )
    start_deployment(api, deployment["id"], start_instant)
    complete_deployment(api, deployment["id"])
    ship = validate_success(api.ship_release(release_id, {}, RELEASE_MANAGER), 200)
    return {"deployment": deployment, "ship_response": ship}


def scenario_cut_release_with_reserved_window(api: ApiClient) -> Dict[str, Any]:
    """A cut release holding one SCHEDULED window on a PROD environment."""
    reset_clock(api)
    environment = create_prod_environment(
        api, cooldown_minutes=30, requires_compliance_evidence=False
    )
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    cut_release_at_freeze(api, release["id"])
    reserved = reserve_deployment(
        api,
        release["id"],
        environment["id"],
        window_start_at="2026-08-10T02:00:00Z",
        window_end_at="2026-08-10T04:00:00Z",
        abort_error_rate_pct=25.0,
        abort_latency_p95_ms=800,
    )
    return {
        "environment": environment,
        "release": release,
        "reserved_deployment": reserved,
    }


def scenario_three_releases_contending_for_one_slot(api: ApiClient) -> Dict[str, Any]:
    """Three releases on a train that admits one stabilizing release at a time.

    The first is cut; the second's stabilization span begins exactly where the
    first's ends; the third's begins one second later.
    """
    reset_clock(api)
    train = create_train(api, max_concurrent_stabilizing=1)
    first = create_release(
        api, train["id"], version_label="2026.08.1", cut_at="2026-08-10T00:00:00Z"
    )
    touching = create_release(
        api, train["id"], version_label="2026.08.2", cut_at="2026-08-13T00:00:00Z"
    )
    clear = create_release(
        api, train["id"], version_label="2026.08.3", cut_at="2026-08-13T00:00:01Z"
    )
    set_clock(api, "2026-08-13T00:00:01Z")
    cut_response = validate_success(api.cut_release(first["id"], {}, RELEASE_MANAGER), 200)
    return {
        "train": train,
        "first_release": first,
        "touching_release": touching,
        "clear_release": clear,
        "first_cut_response": cut_response,
    }


def scenario_canary_gated_second_rung_soaking(api: ApiClient) -> Dict[str, Any]:
    """A flag at five percent whose canary-gated second rung is soaking.

    One canary sample carrying a four-in-ten error rate has been ingested, which
    is enough for the next analysis to breach the abort criteria.
    """
    reset_clock(api)
    environment = create_prod_environment(
        api, cooldown_minutes=30, requires_compliance_evidence=False
    )
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    cut_release_at_freeze(api, release["id"])
    deployment = reserve_deployment(
        api,
        release["id"],
        environment["id"],
        window_start_at="2026-08-10T02:00:00Z",
        window_end_at="2026-08-10T04:00:00Z",
        canary=True,
        abort_error_rate_pct=25.0,
        abort_latency_p95_ms=800,
        canary_pct=10,
        min_sample_count=5,
    )
    start_deployment(api, deployment["id"], "2026-08-10T02:05:00Z")

    flag = create_flag(api, key="search-rerank")
    step_one = plan_step(api, flag["id"], target_pct=5, soak_minutes=30)
    start_soak(api, step_one["id"])
    set_clock(api, "2026-08-10T02:35:00Z")
    apply_step(api, step_one["id"])
    flag_after_first_rung = read_flag(api, flag["id"])
    step_two = plan_step(
        api, flag["id"], target_pct=15, soak_minutes=60, deployment_id=deployment["id"]
    )
    soaking_step_two = start_soak(api, step_two["id"])
    ingest_signal(api, deployment["id"], "2026-08-10T02:40:00Z", 10, 4, 300)
    set_clock(api, "2026-08-10T02:45:00Z")
    return {
        "environment": environment,
        "release": release,
        "deployment": deployment,
        "flag": flag,
        "step_one": step_one,
        "step_two": step_two,
        "exposure_before_abort": flag_after_first_rung["current_exposure_pct"],
        "step_two_previous_exposure_pct": soaking_step_two["previous_exposure_pct"],
    }


def scenario_two_approved_changes_with_dependency(api: ApiClient) -> Dict[str, Any]:
    """Two APPROVED MEDIUM changes on one release, the second depending on the first."""
    reset_clock(api)
    train = create_train(api, max_concurrent_stabilizing=1)
    release = create_release(api, train["id"])
    prerequisite = create_change(
        api,
        release["id"],
        payload=f.make_change_request_payload(
            title="Extract retry helper",
            summary_internal="Prerequisite helper extraction",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        ),
    )
    dependent = create_change(
        api,
        release["id"],
        payload=f.make_change_request_payload(
            title="Adopt retry helper",
            summary_internal="Consumer migration onto the helper",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        ),
    )
    submit_change(api, prerequisite["id"])
    submit_change(api, dependent["id"])
    declare_dependency(api, dependent["id"], prerequisite["id"])
    record_approval(api, prerequisite["id"], ApprovalKind.TECHNICAL)
    record_approval(api, dependent["id"], ApprovalKind.TECHNICAL)
    before = read_release(api, release["id"])
    return {
        "train": train,
        "release": release,
        "prerequisite": prerequisite,
        "dependent": dependent,
        "budget_before": before["risk_budget_consumed_points"],
        "committed_before": before["committed_change_count"],
        "projected_before": before["readiness_score_projected"],
    }


def scenario_cut_release_with_three_merged_changes(api: ApiClient) -> Dict[str, Any]:
    """Three merged LOW changes that differ only in their customer-facing declaration.

    ``customer_ready`` is flagged customer-facing and carries copy;
    ``no_customer_copy`` is flagged but the copy was never written; and
    ``internal_only`` has copy but was never flagged.  All three merge at the
    clock origin, well before the release is cut.
    """
    reset_clock(api)
    built = train_with_release(api)
    release_id = built["release"]["id"]
    built["customer_ready"] = merged_low_change(
        api,
        release_id,
        title="Faster checkout",
        summary_internal="Internal notes for the checkout speedup.",
        customer_facing=True,
        summary_customer_facing="Checkout is now faster",
    )
    built["no_customer_copy"] = merged_low_change(
        api,
        release_id,
        title="Marked customer facing but unwritten",
        summary_internal="Internal notes with no customer copy.",
        customer_facing=True,
    )
    built["internal_only"] = merged_low_change(
        api,
        release_id,
        title="Internal refactor with a blurb",
        summary_internal="Internal notes for the refactor.",
        summary_customer_facing="Reliability improvements",
    )
    built["cut_response"] = cut_release_at_freeze(api, release_id)
    built["release"] = read_release(api, release_id)
    return built


def scenario_cut_release_with_deferred_medium_and_merged_low(
    api: ApiClient,
) -> Dict[str, Any]:
    """A cut release holding one merged LOW change and one change the cut deferred.

    Both changes are customer-facing with copy written, so only the lifecycle
    state distinguishes them.
    """
    reset_clock(api)
    built = train_with_release(api)
    release_id = built["release"]["id"]
    medium = submitted_change(
        api,
        release_id,
        payload=f.make_change_request_payload(
            title="Retry policy rewrite",
            summary_internal="Rewrite the retry policy across two subsystems.",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
            customer_facing=True,
            summary_customer_facing="Fewer transient failures",
        ),
    )
    low = merged_low_change(
        api,
        release_id,
        title="Faster checkout",
        summary_internal="Internal notes for the checkout speedup.",
        customer_facing=True,
        summary_customer_facing="Checkout is now faster",
    )
    built["cut_response"] = cut_release_at_freeze(api, release_id)
    built["deferred_medium"] = read_change(api, medium["id"])
    built["merged_low"] = read_change(api, low["id"])
    built["release"] = read_release(api, release_id)
    return built


def scenario_four_orphan_flags_across_debt_bands(api: ApiClient) -> Dict[str, Any]:
    """Four link-free flags whose deadlines place them in four different tiers.

    Measured from the clock origin the deadlines are 15, 5 and 4 whole days past,
    and the fourth flag is ``permanent`` so its debt short-circuits to zero.
    """
    reset_clock(api)
    enforced = create_flag(api, key="flag-enforced", expires_at="2026-07-17T00:00:00Z")
    overdue = create_flag(api, key="flag-overdue", expires_at="2026-07-27T00:00:00Z")
    warning = create_flag(api, key="flag-warning", expires_at="2026-07-28T00:00:00Z")
    permanent = create_flag(
        api, key="flag-permanent", expires_at="2026-07-17T00:00:00Z", permanent=True
    )
    sweep = run_cleanup_sweep(api)
    return {
        "sweep": sweep,
        "enforced": read_flag(api, enforced["id"]),
        "overdue": read_flag(api, overdue["id"]),
        "warning": read_flag(api, warning["id"]),
        "permanent": read_flag(api, permanent["id"]),
    }


def scenario_two_cut_releases_ranked_by_cut_at(api: ApiClient) -> Dict[str, Any]:
    """Two cut releases on one train whose creation order reverses their cut order.

    ``late_release`` is created first but is cut later, so a linkage that ranks by
    ``cut_at`` descending must prefer it over ``early_release``.
    """
    reset_clock(api)
    train = create_train(api, max_concurrent_stabilizing=2)
    late_release = create_release(
        api, train["id"], version_label="2026.08.2", cut_at="2026-08-11T00:00:00Z"
    )
    early_release = create_release(
        api, train["id"], version_label="2026.08.1", cut_at="2026-08-10T00:00:00Z"
    )
    early_cut = cut_release_at_freeze(api, early_release["id"], "2026-08-08T00:00:00Z")
    late_cut = cut_release_at_freeze(api, late_release["id"], "2026-08-09T00:00:00Z")
    return {
        "train": train,
        "late_release": late_cut,
        "early_release": early_cut,
    }


def grant_freeze_exception(
    api: ApiClient, release_id: str, headers=COMPLIANCE_OFFICER, **overrides
) -> Dict[str, Any]:
    """Record a compliance-approved freeze exception on one release."""
    payload = f.make_freeze_exception_payload(**overrides)
    return validate_success(api.create_freeze_exception(release_id, payload, headers), 200)


def scenario_blackout_environment_with_two_reserved_windows(
    api: ApiClient,
) -> Dict[str, Any]:
    """A cut release holding two windows on an environment with a midnight blackout.

    The blackout runs ``2026-08-10T02:00Z``--``2026-08-10T05:00Z``.  ``early`` is
    reserved wholly inside it and ``late`` wholly after it, and both reservations
    are taken while the clock still sits at the freeze instant.
    """
    reset_clock(api)
    environment = create_environment(
        api,
        name="prod-blackout",
        cooldown_minutes=30,
        blackout_start_at="2026-08-10T02:00:00Z",
        blackout_end_at="2026-08-10T05:00:00Z",
    )
    built = train_with_release(api)
    release_id = built["release"]["id"]
    cut_release_at_freeze(api, release_id)
    built["environment"] = environment
    built["early"] = reserve_deployment(
        api,
        release_id,
        environment["id"],
        window_start_at="2026-08-10T02:00:00Z",
        window_end_at="2026-08-10T04:00:00Z",
    )
    built["late"] = reserve_deployment(
        api,
        release_id,
        environment["id"],
        window_start_at="2026-08-10T05:00:00Z",
        window_end_at="2026-08-10T06:00:00Z",
    )
    return built


def scenario_high_change_with_one_technical_approval(api: ApiClient) -> Dict[str, Any]:
    """A HIGH change still short of its COMPLIANCE lane after one TECHNICAL approval."""
    reset_clock(api)
    built = train_with_release(api)
    change = submitted_change(
        api, built["release"]["id"], payload=f.make_high_risk_change_payload()
    )
    built["submitted"] = change
    built["first_approval"] = record_approval(api, change["id"], ApprovalKind.TECHNICAL)
    built["change"] = read_change(api, change["id"])
    return built


def scenario_high_change_without_a_rollback_plan(api: ApiClient) -> Dict[str, Any]:
    """A submitted HIGH change whose author never supplied a rollback plan."""
    reset_clock(api)
    built = train_with_release(api)
    built["change"] = submitted_change(
        api, built["release"]["id"], payload=f.make_high_risk_change_payload()
    )
    return built


def scenario_stale_and_fresh_flags_after_one_sweep(api: ApiClient) -> Dict[str, Any]:
    """One sweep over two orphan flags, only one of which is past its deadline."""
    reset_clock(api)
    stale = create_flag(api, key="legacy-pricing", expires_at="2026-07-17T00:00:00Z")
    fresh = create_flag(api, key="checkout-v2", expires_at="2026-12-01T00:00:00Z")
    sweep = run_cleanup_sweep(api)
    return {
        "sweep": sweep,
        "stale": read_flag(api, stale["id"]),
        "fresh": read_flag(api, fresh["id"]),
    }


def scenario_approved_low_change_at_the_freeze_boundary(api: ApiClient) -> Dict[str, Any]:
    """An auto-approved LOW change sitting on a release whose freeze instant has arrived.

    The clock is left at exactly ``freeze_at``, which is already too late to merge.
    """
    reset_clock(api)
    built = train_with_release(api)
    built["change"] = submitted_change(
        api,
        built["release"]["id"],
        payload=f.make_low_risk_change_payload(title="Small fix"),
    )
    set_clock(api, RELEASE_FREEZE_AT)
    return built


def scenario_tight_budget_train_with_one_approved_medium(
    api: ApiClient,
) -> Dict[str, Any]:
    """Two identical 33-point changes on a 40-point train, the first already approved."""
    reset_clock(api)
    train = create_tight_budget_train(api, risk_budget_points=40, name="tight-train")
    release = create_release(api, train["id"])
    first = submitted_change(
        api,
        release["id"],
        payload=f.make_change_request_payload(
            title="Retry policy rewrite",
            summary_internal="First medium change of the release.",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        ),
    )
    second = submitted_change(
        api,
        release["id"],
        payload=f.make_change_request_payload(
            title="Timeout policy rewrite",
            summary_internal="Second medium change of the release.",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        ),
    )
    record_approval(api, first["id"], ApprovalKind.TECHNICAL)
    return {
        "train": train,
        "release": read_release(api, release["id"]),
        "first": read_change(api, first["id"]),
        "second": read_change(api, second["id"]),
    }


def scenario_two_stabilizing_releases_regulated_and_open(api: ApiClient) -> Dict[str, Any]:
    """Two stabilizing releases whose only difference is the environment they landed on.

    ``regulated`` completed its production deployment on an environment whose
    ``requires_compliance_evidence`` is true; ``unregulated`` completed an
    otherwise identical deployment on one where it is false.  Neither release has
    a sealed evidence packet.
    """
    reset_clock(api)
    regulated_env = create_regulated_environment(api)
    open_env = create_environment(api, name="prod-open")
    train = create_train(api, max_concurrent_stabilizing=2)
    regulated = create_release(api, train["id"], version_label="2026.08.1")
    unregulated = create_release(
        api, train["id"], version_label="2026.08.2", cut_at="2026-08-11T00:00:00Z"
    )
    merged_low_change(api, regulated["id"], title="Regulated fix")
    open_change = merged_low_change(api, unregulated["id"], title="Unregulated fix")
    cut_release_at_freeze(api, regulated["id"], "2026-08-08T00:00:00Z")
    cut_release_at_freeze(api, unregulated["id"], "2026-08-09T00:00:00Z")
    regulated_deployment = reserve_deployment(
        api,
        regulated["id"],
        regulated_env["id"],
        window_start_at="2026-08-10T02:00:00Z",
        window_end_at="2026-08-10T04:00:00Z",
    )
    open_deployment = reserve_deployment(
        api,
        unregulated["id"],
        open_env["id"],
        window_start_at="2026-08-11T02:00:00Z",
        window_end_at="2026-08-11T04:00:00Z",
    )
    start_deployment(api, regulated_deployment["id"], "2026-08-10T02:05:00Z")
    complete_deployment(api, regulated_deployment["id"])
    start_deployment(api, open_deployment["id"], "2026-08-11T02:05:00Z")
    complete_deployment(api, open_deployment["id"])
    return {
        "train": train,
        "regulated": read_release(api, regulated["id"]),
        "unregulated": read_release(api, unregulated["id"]),
        "open_change": open_change,
    }


def scenario_two_soaking_flags_one_past_its_deadline(api: ApiClient) -> Dict[str, Any]:
    """Two rolling-out flags, only one of which has overrun its removal deadline.

    ``stale`` carries a ``SOAKING`` first rung and a ``PLANNED`` second rung and is
    fifteen whole days past ``expires_at`` with no links, so its debt is 60.
    ``fresh`` carries a single ``SOAKING`` rung and owes nothing.
    """
    reset_clock(api)
    stale = soaking_flag(api, key="legacy-pricing", expires_at="2026-07-17T00:00:00Z")
    planned = plan_step(api, stale["flag"]["id"], target_pct=5, soak_minutes=30)
    fresh = soaking_flag(api, key="checkout-v2", expires_at="2026-12-01T00:00:00Z")
    return {
        "stale_flag": read_flag(api, stale["flag"]["id"]),
        "soaking_step": stale["step"],
        "planned_step": planned,
        "fresh_flag": read_flag(api, fresh["flag"]["id"]),
        "fresh_step": fresh["step"],
    }


def scenario_three_changes_across_risk_bands(api: ApiClient) -> Dict[str, Any]:
    """One release holding a 9-point LOW, a 33-point MEDIUM and a 62-point HIGH change.

    The LOW change auto-approves at submission and therefore leaves
    ``RISK_CLASSIFIED`` immediately, while the other two wait there.
    """
    reset_clock(api)
    built = train_with_release(api)
    release_id = built["release"]["id"]
    built["low"] = submitted_change(
        api, release_id, payload=f.make_low_risk_change_payload()
    )
    built["medium"] = submitted_change(
        api,
        release_id,
        payload=f.make_change_request_payload(
            title="Retry policy rewrite",
            summary_internal="Rewrite the retry policy across two subsystems.",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        ),
    )
    built["high"] = submitted_change(
        api, release_id, payload=f.make_high_risk_change_payload()
    )
    return built


def scenario_flag_and_two_trains_sharing_a_version_label(api: ApiClient) -> Dict[str, Any]:
    """One registered flag plus two trains, only one of which owns ``2026.08.1``.

    A flag ``key`` is unique across the whole inventory, while a
    ``version_label`` is unique only among the releases of one train -- so the
    second train is still free to open its own ``2026.08.1``.
    """
    reset_clock(api)
    flag = create_flag(api, key="checkout-v2")
    first_train = create_train(api, name="core-train")
    second_train = create_train(api, name="edge-train")
    release = create_release(api, first_train["id"], version_label="2026.08.1")
    return {
        "flag": flag,
        "first_train": first_train,
        "second_train": second_train,
        "release": release,
    }


def scenario_flag_with_two_planned_rungs(api: ApiClient) -> Dict[str, Any]:
    """A ``DRAFT`` flag carrying two ``PLANNED`` rungs of 5 percent for 30 minutes.

    Both rungs are admissible against an exposure of 0, and they take
    ``step_index`` 1 and 2, so the ladder can be driven out of order on purpose.
    """
    reset_clock(api)
    flag = create_flag(api)
    first = plan_step(api, flag["id"], target_pct=5, soak_minutes=30)
    second = plan_step(api, flag["id"], target_pct=5, soak_minutes=30)
    return {
        "flag": read_flag(api, flag["id"]),
        "first": first,
        "second": second,
    }


def scenario_superseded_and_live_evidence_packets(api: ApiClient) -> Dict[str, Any]:
    """Two packets on one cut release: the first superseded by the second.

    Both compute a ``base_index`` of 75 with ``canary_pass`` and
    ``release_notes`` unsatisfied, so a waiver would otherwise be permitted on
    either of them.
    """
    reset_clock(api)
    built = cut_release_with_merged_low_change(api)
    release_id = built["release"]["id"]
    superseded = assemble_packet(api, release_id)
    built["live"] = assemble_packet(api, release_id)
    built["superseded"] = read_packet(api, release_id, superseded["id"])
    built["release"] = read_release(api, release_id)
    return built


def scenario_open_sev3_incident_without_linkage(api: ApiClient) -> Dict[str, Any]:
    """An ``OPEN`` SEV3 incident on a train that has never cut a release.

    With no candidate release at all, linkage resolves to null, which makes a
    ``ROLLBACK`` decision inadmissible while ``NO_ACTION`` stays available.
    """
    reset_clock(api)
    train = create_train(api)
    incident = report_incident(
        api,
        train["id"],
        CLOCK_ORIGIN,
        severity=IncidentSeverity.SEV3,
        title="Slow background jobs",
    )
    return {"train": train, "incident": incident}


def scenario_published_internal_notes_then_clock_advance(api: ApiClient) -> Dict[str, Any]:
    """A ``PUBLISHED`` INTERNAL notes document, after which the clock moves on.

    The document was published at the release's freeze instant; the clock is
    then repositioned a day later so a second publication attempt would stamp a
    visibly different instant if it were honoured.
    """
    reset_clock(api)
    built = cut_release_with_merged_low_change(api)
    note = generate_notes(api, built["release"]["id"], NoteAudience.INTERNAL)
    built["note"] = publish_notes(api, note["id"])
    built["clock_after_publication"] = set_clock(api, "2026-08-09T00:00:00Z")
    return built


def scenario_submitted_medium_change_awaiting_technical(api: ApiClient) -> Dict[str, Any]:
    """A submitted 33-point MEDIUM change, which requires only a TECHNICAL lane."""
    reset_clock(api)
    built = train_with_release(api)
    built["change"] = submitted_change(
        api,
        built["release"]["id"],
        payload=f.make_change_request_payload(
            title="Retry policy rewrite",
            summary_internal="Rewrite the retry policy across two subsystems.",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        ),
    )
    return built


def scenario_two_low_changes_joined_by_one_edge(api: ApiClient) -> Dict[str, Any]:
    """Two LOW changes on one release, the dependent naming the other first.

    Both score 9 preliminarily -- prerequisite depth is treated as
    unconditionally zero at submission -- so both auto-approve and wait in
    ``APPROVED`` with neither of them merged.
    """
    reset_clock(api)
    built = train_with_release(api)
    release_id = built["release"]["id"]
    prerequisite = create_change(
        api,
        release_id,
        payload=f.make_low_risk_change_payload(title="Fix confirmation typo"),
    )
    dependent = create_change(
        api,
        release_id,
        payload=f.make_low_risk_change_payload(title="Reword confirmation screen"),
    )
    built["edge"] = declare_dependency(api, dependent["id"], prerequisite["id"])
    built["prerequisite"] = submit_change(api, prerequisite["id"])
    built["dependent"] = submit_change(api, dependent["id"])
    return built


def scenario_cut_release_and_production_environment(api: ApiClient) -> Dict[str, Any]:
    """A cut release and an unoccupied PROD environment whose window is 02:00-06:00.

    Nothing has been reserved yet, so window geometry is the only rule a first
    reservation can trip over.
    """
    reset_clock(api)
    built = train_with_release(api)
    built["prod_env"] = create_prod_environment(api)
    built["cut_response"] = cut_release_at_freeze(api, built["release"]["id"])
    built["release"] = read_release(api, built["release"]["id"])
    return built


def scenario_stabilizing_release_with_four_deferred_mediums(
    api: ApiClient,
) -> Dict[str, Any]:
    """A release whose cut deferred four MEDIUM changes, then deployed anyway.

    Nothing landed before the freeze, so the narrow attested set is empty and
    four unlanded changes cost six points each: the attested score is 76.  The
    production deployment nevertheless reached ``COMPLETED`` on an unregulated
    environment.
    """
    reset_clock(api)
    built = train_with_release(api)
    release_id = built["release"]["id"]
    built["prod_env"] = create_prod_environment(api)
    built["changes"] = [
        submitted_change(
            api,
            release_id,
            payload=f.make_change_request_payload(
                title=f"Retry policy rewrite {index}",
                summary_internal="Rewrite the retry policy across two subsystems.",
                lines_changed=300,
                touched_subsystem_count=2,
                declared_blast_radius="SINGLE_TENANT",
            ),
        )
        for index in range(1, 5)
    ]
    built["cut_response"] = cut_release_at_freeze(api, release_id)
    deployment = reserve_deployment(
        api,
        release_id,
        built["prod_env"]["id"],
        window_start_at="2026-08-10T02:00:00Z",
        window_end_at="2026-08-10T04:00:00Z",
    )
    start_deployment(api, deployment["id"], "2026-08-10T02:05:00Z")
    built["deployment"] = complete_deployment(api, deployment["id"])
    built["release"] = read_release(api, release_id)
    return built


def scenario_cut_release_and_one_overdue_orphan_flag(api: ApiClient) -> Dict[str, Any]:
    """A cut release plus one unlinked flag twelve whole days past its deadline.

    The flag guards nothing, so it is an orphan: twelve days of overdue debt is
    36 points and the orphan penalty adds 15, which is 51 -- past the 30-point
    ``OVERDUE`` threshold but short of enforcement.
    """
    reset_clock(api)
    built = cut_release_with_merged_low_change(api)
    built["orphan"] = create_flag(
        api, key="legacy-toggle", expires_at="2026-07-27T00:00:00Z"
    )
    return built


def scenario_cut_release_and_the_version_read_at_its_creation(
    api: ApiClient,
) -> Dict[str, Any]:
    """A cut release plus the ``version`` a client read when the release was created.

    The row moves twice after that read -- once when its LOW change merges and once
    when the release is cut -- so the captured token no longer matches.
    """
    reset_clock(api)
    built = train_with_release(api)
    built["stale_version"] = built["release"]["version"]
    built["change"] = merged_low_change(api, built["release"]["id"])
    built["cut_response"] = cut_release_at_freeze(api, built["release"]["id"])
    built["release"] = read_release(api, built["release"]["id"])
    return built


def scenario_staging_canary_with_two_samples_bracketing_the_abort_rate(
    api: ApiClient,
) -> Dict[str, Any]:
    """A STAGING canary carrying one sample at 25.0 pct and one at 24.9 pct.

    The deployment aborts at ``abort_error_rate_pct`` 25.0 with
    ``abort_latency_p95_ms`` 800 and ``min_sample_count`` 5. Its first canary
    sample, at ``02:10``, reports 2 errors over 8 requests -- exactly 25.0 percent
    -- and the second, at ``02:40``, reports 249 errors over 1000 requests, one
    tenth of a point below. Both report a p95 of 300 ms, far under the latency
    trigger, so only the error term can move the verdict. The two samples sit in
    disjoint half-open windows: ``02:00``--``02:30`` holds the first and
    ``02:30``--``02:45`` holds the second.
    """
    reset_clock(api)
    environment = create_staging_environment(api)
    train = create_train(api)
    release = create_release(api, train["id"])
    cut_release_at_freeze(api, release["id"])
    reserved = reserve_deployment(
        api,
        release["id"],
        environment["id"],
        window_start_at="2026-08-10T02:00:00Z",
        window_end_at="2026-08-10T04:00:00Z",
        canary=True,
        abort_error_rate_pct=25.0,
        abort_latency_p95_ms=800,
        canary_pct=10,
        min_sample_count=5,
    )
    start_deployment(api, reserved["id"], "2026-08-10T02:05:00Z")
    at_threshold = ingest_signal(
        api, reserved["id"], "2026-08-10T02:10:00Z", 8, 2, 300
    )
    below_threshold = ingest_signal(
        api, reserved["id"], "2026-08-10T02:40:00Z", 1000, 249, 300
    )
    set_clock(api, "2026-08-10T02:45:00Z")
    return {
        "environment": environment,
        "release": release,
        "deployment": read_deployment(api, reserved["id"]),
        "at_threshold_sample": at_threshold,
        "below_threshold_sample": below_threshold,
    }
