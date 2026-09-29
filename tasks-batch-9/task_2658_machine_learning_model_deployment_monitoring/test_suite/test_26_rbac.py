"""Who may call what, and the identity rules that outlive the role check."""

from prd_bench_local_runner.testing import (
    build_user_headers,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    assert_dataset_state,
    assert_deployment_state,
    assert_health_score,
    assert_skew_outcome,
    assert_sweep_counters,
    assert_version_state,
)
from test_helpers.api_errors import (
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_WINDOW_NOT_ENDED,
)
from test_helpers.constants import FLAT_BIN_PROPORTIONS, ROLE_PLATFORM_ADMIN
from test_helpers.factories import (
    build_clock_payload,
    build_dataset_decision_payload,
    build_deployment_payload,
    build_documentation_payload,
    build_incident_action_payload,
    build_incident_payload,
    build_model_payload,
    build_model_version_payload,
    build_monitoring_window_payload,
    build_revalidation_disposition_payload,
    build_rollout_action_payload,
    build_skew_check_payload,
    build_training_dataset_payload,
    build_version_decision_payload,
)
from test_helpers.fixtures import (
    build_stack,
    create_approved_dataset,
    create_approved_version,
    create_deployment,
    create_draft_dataset,
    create_model,
    create_serving_endpoint,
    ramp,
    read_endpoint_version,
    register_version,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_1,
    APPROVER_1,
    APPROVER_2,
    DUAL_AS_APPROVER,
    DUAL_AS_MLE,
    DUAL_AS_STEWARD,
    MLE_1,
    RELIABILITY_1,
    STEWARD_1,
    STEWARD_2,
    USER_APPR_1,
    USER_APPR_2,
    USER_DUAL_1,
    USER_STEW_2,
)

_SOUND_COUNTS = {
    "prediction_count": 1000,
    "labeled_prediction_count": 500,
    "correct_labeled_count": 400,
    "positive_rate": 0.30,
    "p95_latency_ms": 200,
}


# ─── The registration/approval split, in both directions ───


def test_approval_roles_cannot_reach_each_others_exclusive_operations(api):
    """The engineer may not decide, the approver may not author, the admin is no superuser.

    PRD 4 gives `POST /model-versions/{version_id}/decision` to `ModelApprover`
    alone, `POST /model-versions`, `PATCH /model-versions/{version_id}/documentation`
    and `POST /model-versions/{version_id}/submit-for-review` to `MLEngineer` alone,
    and `POST /deployments` and `POST /deployments/{deployment_id}/ramp` to
    `ReliabilityEngineer` alone. PRD 2.1 adds that a caller whose role is declared
    but not authorised for the endpoint "is rejected with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)", and PRD 2.7 places that check second, before any state or business
    rule, so a refusal mutates nothing.

    Design: Corner/rbac/approval_roles_cannot_reach_each_others_exclusive_operations
    """
    entry = create_model(api)
    dataset = create_approved_dataset(api)
    awaiting_decision = register_version(api, entry["id"], dataset["id"])
    get_success_data(api.submit_version_for_review(awaiting_decision["id"], MLE_1))
    approved = create_approved_version(
        api,
        entry["id"],
        dataset["id"],
        MLE_1,
        APPROVER_1,
        semver="1.1.0",
        artifact_digest="sha256:bbb",
    )
    endpoint = create_serving_endpoint(api)
    deployment = create_deployment(api, approved["id"], endpoint["id"])

    validate_error(
        api.decide_model_version(
            awaiting_decision["id"], build_version_decision_payload("APPROVE"), MLE_1
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_model_version(
            build_model_version_payload(
                entry["id"],
                dataset["id"],
                semver="2.0.0",
                artifact_digest="sha256:ccc",
            ),
            APPROVER_1,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.update_version_documentation(
            awaiting_decision["id"], build_documentation_payload(), APPROVER_1
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.submit_version_for_review(awaiting_decision["id"], ADMIN_1),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_deployment(
            build_deployment_payload(
                approved["id"],
                endpoint["id"],
                read_endpoint_version(api, endpoint["id"]),
                pattern="SHADOW",
            ),
            ADMIN_1,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.ramp_deployment(deployment["id"], ADMIN_1), ERR_ROLE_NOT_PERMITTED, 403
    )

    still_pending = get_success_data(
        api.get_model_version(awaiting_decision["id"], MLE_1)
    )
    assert_version_state(still_pending, approval_state="PENDING_REVIEW")
    assert still_pending["decided_by_user_id"] is None
    assert_deployment_state(
        get_success_data(api.get_deployment(deployment["id"], RELIABILITY_1)),
        rollout_state="PENDING",
        traffic_pct=0.00,
    )

    decided = get_success_data(
        api.decide_model_version(
            awaiting_decision["id"],
            build_version_decision_payload("APPROVE"),
            APPROVER_1,
        )
    )
    assert_version_state(decided, approval_state="APPROVED")
    assert decided["decided_by_user_id"] == USER_APPR_1

    ramped = ramp(api, deployment["id"])
    assert_deployment_state(
        ramped, rollout_state="RAMPING", traffic_pct=5.00, ramp_step_index=1
    )
    _, meta = validate_paginated(
        api.list_model_versions(MLE_1, {"model_id": entry["id"]})
    )
    assert meta["total_count"] == 2, "no refused registration may have created a row"


# ─── Four peer roles, each walled off from the others' lifecycle ───


def test_peer_roles_cannot_operate_another_role_s_lifecycle(api):
    """The refusal lands before the business rule, on an otherwise valid request.

    PRD 4 restricts `POST /deployments/{deployment_id}/ramp` to
    `ReliabilityEngineer`, `POST /training-datasets/{dataset_id}/decision` to
    `DataSteward`, `POST /models/{model_id}/archive`, `POST /_clock/set_current_utc`
    and `POST /_ops/revalidation-sweep` to `PlatformAdmin`, noting that "Endpoints in
    the underscore-prefixed operational namespace exist to drive the logical clock
    and the periodic sweep and are restricted to `PlatformAdmin`". PRD 2.7 evaluates
    the role check before the clock's own monotonicity rule, and PRD 2.4 fixes the
    startup value at "exactly `2026-08-01T00:00:00Z`", so a refused set leaves
    `previous_utc` at that instant.

    Design: Corner/rbac/peer_roles_cannot_operate_the_platform_or_data_lifecycle_of_another_role
    """
    stack = build_stack(api)
    awaiting_steward = create_draft_dataset(api)
    submitted = get_success_data(
        api.submit_training_dataset(awaiting_steward["id"], MLE_1)
    )
    assert_dataset_state(submitted, approval_state="SUBMITTED")

    validate_error(
        api.ramp_deployment(stack.deployment_id, STEWARD_1),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.decide_training_dataset(
            awaiting_steward["id"], build_dataset_decision_payload("APPROVE"),
            RELIABILITY_1,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.set_clock(build_clock_payload("2026-08-02T00:00:00Z"), MLE_1),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.run_revalidation_sweep(STEWARD_1), ERR_ROLE_NOT_PERMITTED, 403
    )
    validate_error(
        api.archive_model(stack.model_id, APPROVER_1), ERR_ROLE_NOT_PERMITTED, 403
    )

    moved = get_success_data(
        api.set_clock(build_clock_payload("2026-08-02T00:00:00Z"), ADMIN_1)
    )
    assert moved["previous_utc"] == "2026-08-01T00:00:00Z", (
        "the engineer's refused set must not have advanced the clock"
    )
    assert moved["current_utc"] == "2026-08-02T00:00:00Z"

    entry = get_success_data(api.get_model(stack.model_id, MLE_1))
    assert entry["registry_status"] == "ACTIVE"
    assert_deployment_state(
        get_success_data(api.get_deployment(stack.deployment_id, RELIABILITY_1)),
        rollout_state="PENDING",
        traffic_pct=0.00,
    )

    approved = get_success_data(
        api.decide_training_dataset(
            awaiting_steward["id"], build_dataset_decision_payload("APPROVE"),
            STEWARD_2,
        )
    )
    assert_dataset_state(approved, approval_state="APPROVED")
    assert approved["decided_by_user_id"] == USER_STEW_2


# ─── The mirror image: every declared holder is accepted ───


def test_shared_operations_are_accepted_from_every_declared_holder(api):
    """Each shared endpoint is exercised by two different roles with identical semantics.

    PRD 4 names more than one authorised role on the shared write endpoints:
    `POST /models` for `MLEngineer` and `PlatformAdmin`; `POST /training-datasets`
    and its submit for `MLEngineer` and `DataSteward`; `POST /monitoring-windows`,
    `POST /monitoring-windows/{window_id}/close` and `POST /skew-checks` for
    `MLEngineer` and `ReliabilityEngineer`; `POST /prediction-incidents` for
    `ReliabilityEngineer`, `MLEngineer` and `PlatformAdmin`;
    `POST /prediction-incidents/{incident_id}/actions` and
    `POST /deployments/{deployment_id}/rollout-action` for `ReliabilityEngineer` and
    `PlatformAdmin`. PRD 3.8 notes that "`MONITORING` is deliberately **not** in that
    blocking set", so a monitored incident does not block the resume.

    Design: Corner/rbac/shared_operations_are_accepted_from_every_declared_holder
    """
    stack = build_stack(api, ramps=1)

    admin_entry = get_success_data(
        api.create_model(
            build_model_payload(name="risk-ranker", task_type="RANKING"), ADMIN_1
        )
    )
    assert admin_entry["registry_status"] == "ACTIVE"
    assert admin_entry["task_type"] == "RANKING"

    steward_snapshot = get_success_data(
        api.create_training_dataset(build_training_dataset_payload(), STEWARD_1)
    )
    assert_dataset_state(steward_snapshot, approval_state="DRAFT")
    assert_dataset_state(
        get_success_data(
            api.submit_training_dataset(steward_snapshot["id"], STEWARD_1)
        ),
        approval_state="SUBMITTED",
    )

    performance = get_success_data(
        api.create_monitoring_window(
            build_monitoring_window_payload(
                stack.deployment_id,
                stack.version_id,
                window_kind="PERFORMANCE",
                observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
                **_SOUND_COUNTS,
            ),
            MLE_1,
        )
    )
    assert_health_score(
        performance, health_score=91.00, variant="PROVISIONAL", baseline_delta_pct=9.00
    )

    latency = get_success_data(
        api.create_monitoring_window(
            build_monitoring_window_payload(
                stack.deployment_id,
                stack.version_id,
                window_kind="LATENCY",
                observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
                **_SOUND_COUNTS,
            ),
            RELIABILITY_1,
        )
    )
    assert latency["window_kind"] == "LATENCY"
    assert latency["status"] == "OPEN"

    from_reliability = get_success_data(
        api.create_skew_check(
            build_skew_check_payload(
                stack.version_id,
                stack.deployment_id,
                {"amount": {"mean": 1.0000}},
                {"amount": {"mean": 1.0000}},
            ),
            RELIABILITY_1,
        )
    )
    assert_skew_outcome(
        from_reliability, max_skew_ratio=1.0000, status="PASS", missing_features=[]
    )

    incident = get_success_data(
        api.create_prediction_incident(
            build_incident_payload(
                stack.deployment_id, summary="engineer-reported anomaly"
            ),
            MLE_1,
        )
    )
    assert incident["status"] == "OPEN"

    mitigating = get_success_data(
        api.incident_action(
            incident["id"],
            build_incident_action_payload("ENGAGE_FALLBACK"),
            RELIABILITY_1,
        )
    )
    assert mitigating["status"] == "MITIGATING"
    monitoring = get_success_data(
        api.incident_action(
            incident["id"], build_incident_action_payload("MONITOR"), ADMIN_1
        )
    )
    assert monitoring["status"] == "MONITORING"

    held = get_success_data(
        api.rollout_action(
            stack.deployment_id, build_rollout_action_payload("HOLD"), ADMIN_1
        )
    )
    assert_deployment_state(held, rollout_state="HELD", traffic_pct=5.00)
    resumed = get_success_data(
        api.rollout_action(
            stack.deployment_id, build_rollout_action_payload("RESUME"), RELIABILITY_1
        )
    )
    assert_deployment_state(resumed, rollout_state="RAMPING", traffic_pct=5.00)

    validate_error(
        api.close_monitoring_window(performance["id"], MLE_1),
        ERR_WINDOW_NOT_ENDED,
        409,
    )


# ─── Two identity rules that survive a legitimately dual-hatted operator ───


def test_segregation_of_duties_blocks_the_registrar_and_the_submitter(api):
    """The role is right and the request is refused anyway, on the identifier alone.

    PRD 2.10: "The operator deciding a training-data snapshot must not be the
    operator who registered it — the acting `X-User-ID` must differ from that
    snapshot's `registered_by_user_id`. The operator deciding an artifact version
    must not be the operator who submitted it for review — the acting `X-User-ID`
    must differ from that version's `submitted_by_user_id`, and this holds even when
    the submitter genuinely holds the `ModelApprover` role." PRD 2.1 adds that "a
    mismatch requirement failing yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)", and
    PRD 2.7 places segregation after the role check, so the refusal is not about the
    role at all.

    Design: Corner/rbac/segregation_of_duties_blocks_the_registrar_and_the_submitter
    """
    entry = create_model(api)
    snapshot = create_draft_dataset(api, DUAL_AS_MLE)
    assert snapshot["registered_by_user_id"] == USER_DUAL_1
    assert_dataset_state(
        get_success_data(api.submit_training_dataset(snapshot["id"], DUAL_AS_MLE)),
        approval_state="SUBMITTED",
    )

    validate_error(
        api.decide_training_dataset(
            snapshot["id"], build_dataset_decision_payload("APPROVE"), DUAL_AS_STEWARD
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    approved_snapshot = get_success_data(
        api.decide_training_dataset(
            snapshot["id"], build_dataset_decision_payload("APPROVE"), STEWARD_2
        )
    )
    assert_dataset_state(approved_snapshot, approval_state="APPROVED")
    assert approved_snapshot["decided_by_user_id"] == USER_STEW_2

    version = register_version(api, entry["id"], snapshot["id"], DUAL_AS_MLE)
    submitted = get_success_data(
        api.submit_version_for_review(version["id"], DUAL_AS_MLE)
    )
    assert submitted["submitted_by_user_id"] == USER_DUAL_1
    assert_version_state(submitted, approval_state="PENDING_REVIEW")

    validate_error(
        api.decide_model_version(
            version["id"], build_version_decision_payload("APPROVE"), DUAL_AS_APPROVER
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        api.decide_model_version(
            version["id"],
            build_version_decision_payload(
                "REQUEST_CHANGES", note="submitter cannot self-review"
            ),
            DUAL_AS_APPROVER,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert_version_state(
        get_success_data(api.get_model_version(version["id"], MLE_1)),
        approval_state="PENDING_REVIEW",
    )

    decided = get_success_data(
        api.decide_model_version(
            version["id"], build_version_decision_payload("APPROVE"), APPROVER_2
        )
    )
    assert_version_state(decided, approval_state="APPROVED")
    assert decided["decided_by_user_id"] == USER_APPR_2


# ─── The identity rule that reaches across an entity hop ───


def test_revalidation_review_cannot_be_taken_by_the_deciding_approver(api):
    """The compared identifier lives on the version, not on the task being dispositioned.

    PRD 3.9: `START_REVIEW` "carries the service's third segregation-of-duties rule:
    the acting operator must differ from the version's `decided_by_user_id`, or the
    request is rejected with `ERR_SEGREGATION_OF_DUTIES`", and `PASS` and `FAIL`
    "both require the acting `X-User-ID` to equal the `reviewer_user_id` recorded at
    `START_REVIEW` — rejected with `ERR_SEGREGATION_OF_DUTIES` otherwise, so a review
    may not be handed off mid-flight". On the pass anchor `revalidation_due_at` is
    "the logical clock's **present value at disposition time** plus the interval",
    and "the version stays `APPROVED` and its deployments keep serving". PRD 2.1
    makes `X-User-ID` an opaque identity, so presenting the other permitted role
    changes nothing.

    Design: Corner/rbac/revalidation_review_cannot_be_taken_by_the_approver_who_decided_the_version
    """
    entry = create_model(api)
    dataset = create_approved_dataset(api)
    version = create_approved_version(
        api, entry["id"], dataset["id"], MLE_1, APPROVER_1
    )
    assert version["decided_by_user_id"] == USER_APPR_1
    assert_version_state(version, revalidation_due_at="2026-10-30T00:00:00Z")

    set_clock(api, "2026-10-30T00:00:00Z")
    sweep = get_success_data(api.run_revalidation_sweep(ADMIN_1))
    assert_sweep_counters(sweep, created_count=1, skipped_existing_count=0)

    tasks, meta = validate_paginated(
        api.list_revalidation_tasks(APPROVER_1, {"model_version_id": version["id"]})
    )
    assert meta["total_count"] == 1
    task = tasks[0]
    assert task["status"] == "DUE"
    assert task["due_at"] == "2026-10-30T00:00:00Z"
    assert task["swept_at"] == "2026-10-30T00:00:00Z"

    start_review = build_revalidation_disposition_payload("START_REVIEW")
    validate_error(
        api.disposition_revalidation_task(task["id"], start_review, APPROVER_1),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    same_person_as_admin = build_user_headers(USER_APPR_1, ROLE_PLATFORM_ADMIN)
    validate_error(
        api.disposition_revalidation_task(
            task["id"], start_review, same_person_as_admin
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    in_review = get_success_data(
        api.disposition_revalidation_task(task["id"], start_review, APPROVER_2)
    )
    assert in_review["status"] == "IN_REVIEW"
    assert in_review["reviewer_user_id"] == USER_APPR_2

    findings = "metrics stable, documentation current"
    validate_error(
        api.disposition_revalidation_task(
            task["id"],
            build_revalidation_disposition_payload("PASS", findings=findings),
            APPROVER_1,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    passed = get_success_data(
        api.disposition_revalidation_task(
            task["id"],
            build_revalidation_disposition_payload("PASS", findings=findings),
            APPROVER_2,
        )
    )
    assert passed["status"] == "PASSED"
    assert passed["decided_at"] == "2026-10-30T00:00:00Z"

    re_dated = get_success_data(api.get_model_version(version["id"], APPROVER_1))
    assert_version_state(
        re_dated,
        approval_state="APPROVED",
        revalidation_due_at="2027-01-28T00:00:00Z",
    )

    any_role = get_success_data(api.get_revalidation_task(task["id"], MLE_1))
    assert any_role["status"] == "PASSED"
    assert any_role["reviewer_user_id"] == USER_APPR_2
    assert any_role["findings"] == findings
