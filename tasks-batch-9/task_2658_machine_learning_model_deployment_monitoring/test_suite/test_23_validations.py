"""Gates that read the clock, the neighbour row or the sibling rule before writing."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    assert_allocated_traffic,
    assert_dataset_state,
    assert_deployment_state,
    assert_skew_outcome,
    assert_sweep_counters,
    assert_version_state,
)
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_DUPLICATE_SEMVER,
    ERR_FALLBACK_NOT_CONFIGURED,
    ERR_MODEL_NOT_FOUND,
    ERR_PII_REVIEW_MISSING,
    ERR_SERVE_WINDOW_EXPIRED,
    ERR_SKEW_DEPLOYMENT_MISMATCH,
    ERR_VERSION_STILL_SERVING,
)
from test_helpers.constants import PROBE_UUID_E
from test_helpers.factories import (
    OMIT,
    build_deployment_payload,
    build_incident_action_payload,
    build_model_version_payload,
    build_rollout_action_payload,
    build_skew_check_payload,
    build_version_decision_payload,
)
from test_helpers.fixtures import (
    build_stack,
    create_approved_dataset,
    create_approved_version,
    create_draft_dataset,
    create_incident,
    create_model,
    create_skew_check,
    incident_action,
    ledger_rows,
    ramp,
    read_endpoint_version,
    register_version,
    rollout,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_1,
    APPROVER_1,
    MLE_1,
    RELIABILITY_1,
    USER_APPR_1,
)

# ─── A temporal gate re-evaluated on every request ───


def test_the_serve_window_gate_is_re_evaluated_on_every_ramp_and_resume(api):
    """Nothing about the deployment changed; the clock moved past its window.

    PRD 3.4 re-checks every ramp precondition "on every call", among them that
    "`serve_until` must be strictly after the logical clock's present value,
    rejecting with `ERR_SERVE_WINDOW_EXPIRED`". HOLD "moves `RAMPING → HELD` and
    does nothing else", carrying no gates at all, while RESUME "re-runs the safety
    and temporal gates before allowing it: ... and `serve_until` must still be in
    the future."

    Design: Corner/validations/ramp_and_resume_are_blocked_once_the_serve_window_has_expired
    """
    stack = build_stack(
        api,
        serve_from="2026-08-01T00:00:00Z",
        serve_until="2026-08-05T00:00:00Z",
    )
    inside_the_window = ramp(api, stack.deployment_id)
    assert_deployment_state(
        inside_the_window,
        rollout_state="RAMPING",
        traffic_pct=5.00,
        ramp_step_index=1,
    )

    set_clock(api, "2026-08-05T00:00:00Z")
    validate_error(
        api.ramp_deployment(stack.deployment_id, RELIABILITY_1),
        ERR_SERVE_WINDOW_EXPIRED,
    )

    held = rollout(api, stack.deployment_id, "HOLD")
    assert_deployment_state(
        held, rollout_state="HELD", traffic_pct=5.00, ramp_step_index=1
    )

    validate_error(
        api.rollout_action(
            stack.deployment_id,
            build_rollout_action_payload("RESUME"),
            RELIABILITY_1,
        ),
        ERR_SERVE_WINDOW_EXPIRED,
    )

    stuck = get_success_data(api.get_deployment(stack.deployment_id, RELIABILITY_1))
    assert_deployment_state(
        stuck, rollout_state="HELD", traffic_pct=5.00, ramp_step_index=1
    )
    assert len(ledger_rows(api, stack.deployment_id)) == 1
    endpoint = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint, 5.00)


# ─── A gate on the relationship between two valid rows ───


def test_a_skew_check_must_name_the_version_the_deployment_actually_serves(api):
    """Both rows exist; only the pairing between them is wrong.

    PRD 3.6: "The named deployment must serve exactly the submitted
    `model_version_id`, or the create is rejected with
    `ERR_SKEW_DEPLOYMENT_MISMATCH`", and on a successful create "the check copies
    `training_dataset_id` from the version". PRD 2.7 puts that among the referential
    cross-entity gates at 422 rather than among the 404 existence checks.

    Design: Corner/validations/skew_check_against_a_deployment_of_a_different_version_is_rejected
    """
    stack = build_stack(api, ramps=1)
    other_version = create_approved_version(
        api,
        stack.model_id,
        stack.dataset_id,
        MLE_1,
        APPROVER_1,
        semver="1.0.1",
        artifact_digest="sha256:bbb",
    )

    mismatched = api.create_skew_check(
        build_skew_check_payload(
            other_version["id"],
            stack.deployment_id,
            {"amount": {"mean": 1.0000}},
            {"amount": {"mean": 1.0000}},
        ),
        MLE_1,
    )
    validate_error(mismatched, ERR_SKEW_DEPLOYMENT_MISMATCH)

    _, empty = validate_paginated(
        api.list_skew_checks(MLE_1, {"model_version_id": other_version["id"]})
    )
    assert empty["total_count"] == 0

    accepted = create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        {"amount": {"mean": 1.0000}},
        {"amount": {"mean": 1.0000}},
    )
    assert_skew_outcome(
        accepted, max_skew_ratio=1.0000, status="PASS", missing_features=[]
    )
    assert accepted["training_dataset_id"] == stack.dataset_id
    assert accepted["deployment_id"] == stack.deployment_id


# ─── A uniqueness scope, and what outranks it ───


def test_a_semantic_version_is_unique_per_registry_entry_only(api):
    """The same string collides on one entry and is free on another.

    PRD 3.3: the `semver` "must be unique among the versions of the same registry
    entry; a collision is rejected with `ERR_DUPLICATE_SEMVER`". PRD 2.7 evaluates
    "path-identifier resolution, body foreign-key resolution" before the uniqueness
    and constraint band, so a duplicate string aimed at a registry entry that does
    not exist answers the existence code instead.

    Design: Corner/validations/duplicate_semver_is_scoped_to_the_model
    """
    first_entry = create_model(api)
    second_entry = create_model(api)
    dataset = create_approved_dataset(api)
    original = register_version(
        api,
        first_entry["id"],
        dataset["id"],
        semver="2.0.0",
        artifact_digest="sha256:zzz",
    )
    assert original["semver"] == "2.0.0"

    collision = api.create_model_version(
        build_model_version_payload(
            first_entry["id"],
            dataset["id"],
            semver="2.0.0",
            artifact_digest="sha256:yyy",
        ),
        MLE_1,
    )
    validate_error(collision, ERR_DUPLICATE_SEMVER)

    on_another_entry = register_version(
        api,
        second_entry["id"],
        dataset["id"],
        semver="2.0.0",
        artifact_digest="sha256:bbb",
    )
    assert on_another_entry["semver"] == "2.0.0"
    assert on_another_entry["model_id"] == second_entry["id"]

    unknown_entry = api.create_model_version(
        build_model_version_payload(
            PROBE_UUID_E,
            dataset["id"],
            semver="2.0.0",
            artifact_digest="sha256:ccc",
        ),
        MLE_1,
    )
    validate_error(unknown_entry, ERR_MODEL_NOT_FOUND)

    _, meta = validate_paginated(
        api.list_model_versions(MLE_1, {"model_id": first_entry["id"]})
    )
    assert meta["total_count"] == 1
    assert_dataset_state(
        get_success_data(api.get_training_dataset(dataset["id"], MLE_1)),
        dependent_version_count=2,
    )


# ─── A gate conditional on the target's own configuration ───


def _shadow_with_a_fallback(api: ApiClient, version_id: str, endpoint_id: str) -> dict:
    return get_success_data(
        api.create_deployment(
            build_deployment_payload(
                version_id,
                endpoint_id,
                read_endpoint_version(api, endpoint_id),
                pattern="SHADOW",
                fallback_strategy="PREVIOUS_CHAMPION",
            ),
            RELIABILITY_1,
        )
    )


def test_engaging_a_fallback_requires_the_deployment_to_declare_one(api):
    """Two incidents, one action, and only the configured deployment moves.

    PRD 3.4 gives a deployment an "optional `fallback_strategy`" that "defaults to
    `NONE`". PRD 3.8: ENGAGE_FALLBACK requires that "the deployment's
    `fallback_strategy` must be something other than `NONE`, or the request is
    rejected with `ERR_FALLBACK_NOT_CONFIGURED` — there is nothing to fall back to",
    and on success "`fallback_engaged` is set true and `fallback_strategy_used`
    captures the deployment's `fallback_strategy` as it stood at that instant ...
    no traffic moves."

    Design: Corner/validations/engage_fallback_requires_a_configured_fallback_strategy
    """
    stack = build_stack(api, fallback_strategy=OMIT, ramps=1)
    without_fallback = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert without_fallback["fallback_strategy"] == "NONE"

    with_fallback = _shadow_with_a_fallback(
        api, stack.version_id, stack.endpoint_id
    )
    assert with_fallback["fallback_strategy"] == "PREVIOUS_CHAMPION"
    assert_deployment_state(ramp(api, with_fallback["id"]), traffic_pct=10.00)

    unconfigured_incident = create_incident(api, stack.deployment_id)
    configured_incident = create_incident(api, with_fallback["id"])

    refused = api.incident_action(
        unconfigured_incident["id"],
        build_incident_action_payload("ENGAGE_FALLBACK"),
        RELIABILITY_1,
    )
    validate_error(refused, ERR_FALLBACK_NOT_CONFIGURED)

    untouched = get_success_data(
        api.get_prediction_incident(unconfigured_incident["id"], RELIABILITY_1)
    )
    assert untouched["status"] == "OPEN"
    assert untouched["fallback_engaged"] is False
    assert untouched["fallback_strategy_used"] is None

    engaged = incident_action(api, configured_incident["id"], "ENGAGE_FALLBACK")
    assert engaged["status"] == "MITIGATING"
    assert engaged["fallback_engaged"] is True
    assert engaged["fallback_strategy_used"] == "PREVIOUS_CHAMPION"

    assert_deployment_state(
        get_success_data(api.get_deployment(stack.deployment_id, RELIABILITY_1)),
        traffic_pct=5.00,
    )
    assert_deployment_state(
        get_success_data(api.get_deployment(with_fallback["id"], RELIABILITY_1)),
        traffic_pct=10.00,
    )
    assert_allocated_traffic(
        get_success_data(
            api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
        ),
        15.00,
    )


# ─── A block that lifts when a different entity changes state ───


def test_deprecation_waits_for_the_traffic_to_leave_the_serving_set(api):
    """The same call flips from refusal to success on the deployment's state alone.

    PRD 3.3: deprecation "is rejected with `ERR_VERSION_STILL_SERVING` while any
    deployment of the version has a `rollout_state` of `RAMPING`, `HELD`, `LIVE` or
    `DRAINING` — traffic must be drained first — and rejected with
    `ERR_CANNOT_DEPRECATE_CHAMPION` when the version is the one named by the registry
    entry's `champion_version_id`", and on success "it clears `revalidation_due_at`
    to null so no future sweep raises work for it". PRD 3.4 puts a rolled-back
    deployment outside that serving set.

    Design: Corner/validations/deprecation_is_blocked_while_the_version_still_serves_and_allowed_after_rollback
    """
    stack = build_stack(api, ramps=2)

    refused = api.deprecate_model_version(stack.version_id, APPROVER_1)
    validate_error(refused, ERR_VERSION_STILL_SERVING)

    untouched = get_success_data(
        api.get_model_version(stack.version_id, APPROVER_1)
    )
    assert_version_state(
        untouched,
        approval_state="APPROVED",
        revalidation_due_at="2026-10-30T00:00:00Z",
    )

    rolled_back = rollout(api, stack.deployment_id, "ROLLBACK")
    assert_deployment_state(
        rolled_back, rollout_state="ROLLED_BACK", traffic_pct=0.00
    )
    assert (
        get_success_data(api.get_model(stack.model_id, APPROVER_1))[
            "champion_version_id"
        ]
        is None
    )

    deprecated = get_success_data(
        api.deprecate_model_version(stack.version_id, APPROVER_1)
    )
    assert_version_state(
        deprecated, approval_state="DEPRECATED", revalidation_due_at=None
    )

    set_clock(api, "2026-11-01T00:00:00Z")
    sweep = get_success_data(api.run_revalidation_sweep(ADMIN_1))
    assert_sweep_counters(sweep, created_count=0)
    _, meta = validate_paginated(
        api.list_revalidation_tasks(
            APPROVER_1, {"model_version_id": stack.version_id}
        )
    )
    assert meta["total_count"] == 0


# ─── Two rules broken at once, and the band that answers ───


def test_the_pii_safety_gate_answers_before_the_snapshot_state_gate(api):
    """One APPROVE request violates two rules; the safety band names the error.

    PRD 3.3: APPROVE "requires the documentation and reproducibility gate to still
    hold, requires the snapshot's `pii_review_passed` to be true, and requires the
    snapshot named by `training_dataset_id` to be in `approval_state` `APPROVED`,
    rejecting with `ERR_DATASET_NOT_APPROVED` otherwise", while PRD 2.7 evaluates the
    safety band — which carries "the PII-review gate (`ERR_PII_REVIEW_MISSING`, 422)"
    — before the referential cross-entity gates. PRD 3.2 blocks the snapshot's own
    submit for the same reason, which is why APPROVED is out of reach.

    Design: Corner/validations/pii_gate_priority_31_outranks_dataset_approval_priority_40_on_version_approve
    """
    model = create_model(api)
    dataset = create_draft_dataset(api, pii_review_passed=OMIT)
    assert_dataset_state(
        dataset, approval_state="DRAFT", pii_review_passed=False
    )

    version = register_version(api, model["id"], dataset["id"])
    submitted = get_success_data(api.submit_version_for_review(version["id"], MLE_1))
    assert_version_state(submitted, approval_state="PENDING_REVIEW")
    assert submitted["doc_completeness_pct"] == 80.00
    assert submitted["reproducibility_score"] == 100.00

    validate_error(
        api.submit_training_dataset(dataset["id"], MLE_1), ERR_PII_REVIEW_MISSING
    )
    assert_dataset_state(
        get_success_data(api.get_training_dataset(dataset["id"], MLE_1)),
        approval_state="DRAFT",
    )

    both_violated = api.decide_model_version(
        version["id"], build_version_decision_payload("APPROVE"), APPROVER_1
    )
    validate_error(both_violated, ERR_PII_REVIEW_MISSING)

    after = get_success_data(api.get_model_version(version["id"], APPROVER_1))
    assert_version_state(
        after, approval_state="PENDING_REVIEW", revalidation_due_at=None
    )
    assert after["approved_at"] is None
    assert after["decided_by_user_id"] is None

    changes_requested = get_success_data(
        api.decide_model_version(
            version["id"],
            build_version_decision_payload(
                "REQUEST_CHANGES",
                note="attach the PII review before re-submitting",
            ),
            APPROVER_1,
        )
    )
    assert_version_state(changes_requested, approval_state="CHANGES_REQUESTED")
    assert changes_requested["decided_by_user_id"] == USER_APPR_1
