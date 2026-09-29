"""What a stored row looks like the moment it exists, and how it reads back."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    assert_append_only_fields,
    assert_common_fields,
    assert_dataset_state,
    assert_drift_outcome,
    assert_envelope_meta,
    assert_pct,
    assert_ramp_step_row,
    assert_skew_outcome,
    assert_version_state,
    ids_of,
)
from test_helpers.api_errors import (
    ERR_DEPLOYMENT_NOT_FOUND,
    ERR_INVALID_BIN_PROPORTIONS,
    ERR_INVALID_REQUEST,
    ERR_MODEL_NOT_FOUND,
    ERR_TRAINING_DATASET_NOT_FOUND,
)
from test_helpers.constants import FLAT_BIN_PROPORTIONS, PROBE_UUID_A
from test_helpers.factories import (
    OMIT,
    build_deployment_payload,
    build_documentation_payload,
    build_model_payload,
    build_model_version_payload,
    build_serving_endpoint_payload,
    build_training_dataset_payload,
)
from test_helpers.fixtures import (
    build_stack,
    close_window,
    create_approved_dataset,
    create_drift_report,
    create_model,
    create_serving_endpoint,
    create_skew_check,
    read_endpoint_version,
    record_window,
    register_version,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_1,
    MLE_1,
    RELIABILITY_1,
    STEWARD_1,
    USER_MLE_1,
    USER_STEW_1,
)

# ─── A freshly registered registry entry ───


def test_registering_an_entry_returns_its_declared_fields_and_defaults(api):
    """Creation answers 201 with every declared field on the row.

    PRD 3.1: an entry is registered with "a `name`, a `task_type` and an
    `owner_team`", `revalidation_interval_days` "defaults to 90 when omitted", and
    "a fresh entry starts with `registry_status` of `ACTIVE`, a null
    `champion_version_id`, a null `champion_promoted_at` and an
    `open_retraining_trigger_count` of 0", with `registered_by_user_id` stamped
    "from the caller's `X-User-ID`". PRD 2.2 wraps the object in a `data` / `meta`
    envelope and PRD 2.4 gives it the system-field quartet.

    Design: Corner/entities/create_model_returns_declared_fields_defaults_and_success_envelope
    """
    response = api.create_model(
        build_model_payload(
            name="fraud-scorer",
            task_type="CLASSIFICATION",
            owner_team="risk-ml",
            revalidation_interval_days=OMIT,
        ),
        MLE_1,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["response_type"] == "object"
    assert_envelope_meta(body)

    model = body["data"]
    assert_common_fields(model)
    assert model["name"] == "fraud-scorer"
    assert model["task_type"] == "CLASSIFICATION"
    assert model["owner_team"] == "risk-ml"
    assert model["revalidation_interval_days"] == 90
    assert model["registry_status"] == "ACTIVE"
    assert model["champion_version_id"] is None
    assert model["champion_promoted_at"] is None
    assert model["open_retraining_trigger_count"] == 0
    assert model["registered_by_user_id"] == USER_MLE_1
    assert model["created_at"] == "2026-08-01T00:00:00Z"
    assert model["updated_at"] == model["created_at"]
    assert model["version"] == 1


def test_reading_an_entry_back_returns_exactly_the_stored_row(api):
    """A read is not a write: the concurrency token does not move.

    PRD 3.1: "reading a single entry returns all of the above", and PRD 2.4 says
    `version` "starts at 1 and increments by exactly 1 on every successful
    mutation", so a read leaves it where the creation left it. The supplied
    cadence is echoed back because PRD 3.1 makes it "immutable once the entry
    exists".

    Design: Corner/entities/get_model_by_id_returns_the_stored_row
    """
    created = create_model(
        api, MLE_1, name="ranker-a", task_type="RANKING", revalidation_interval_days=45
    )

    read_back = get_success_data(api.get_model(created["id"], MLE_1))

    assert read_back["id"] == created["id"]
    assert read_back["name"] == "ranker-a"
    assert read_back["task_type"] == "RANKING"
    assert read_back["revalidation_interval_days"] == 45
    assert read_back["registry_status"] == "ACTIVE"
    assert read_back["champion_version_id"] is None
    assert read_back["version"] == 1
    assert read_back["created_at"] == read_back["updated_at"]
    assert read_back == created


def test_the_version_list_pages_with_a_total_count_and_a_has_more_flag(api):
    """Two pages of a three-row collection, disjoint and correctly flagged.

    PRD 2.3: for a list response the meta block carries `limit`, `offset`,
    `total_count` and `has_more`, where "`total_count` is the number of rows
    matching the filters before pagination is applied, and `has_more` is true when
    rows remain beyond the current page". PRD 3.3 defaults `doc_sections` to an
    empty array, whose derived `doc_completeness_pct` is therefore 0.00.

    Design: Corner/entities/list_model_versions_paginates_with_total_count_and_has_more
    """
    model = create_model(api)
    dataset = create_approved_dataset(api)
    for semver, digest in (
        ("1.0.0", "sha256:aaa"),
        ("1.1.0", "sha256:bbb"),
        ("1.2.0", "sha256:ccc"),
    ):
        register_version(
            api,
            model["id"],
            dataset["id"],
            MLE_1,
            semver=semver,
            artifact_digest=digest,
            doc_sections=OMIT,
            repro_artifacts=OMIT,
        )

    first_page, first_meta = validate_paginated(
        api.list_model_versions(MLE_1, {"model_id": model["id"], "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api.list_model_versions(MLE_1, {"model_id": model["id"], "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    assert not set(ids_of(first_page)) & set(ids_of(second_page))
    for row in first_page + second_page:
        assert_version_state(row, approval_state="DRAFT")
        assert_pct(row["doc_completeness_pct"], 0.00, "doc_completeness_pct")
        assert_pct(row["reproducibility_score"], 0.00, "reproducibility_score")


# ─── Reads and writes that never reach a stored row ───


def test_an_unknown_deployment_id_answers_a_typed_not_found_error(api):
    """A well-formed identifier that matches nothing is a 404, not a 500.

    PRD 2.7 puts resource existence at HTTP 404 with a family-specific error, and
    PRD 2.2 shapes the error body as `response_type` "error" carrying an
    `error_id` that is "a unique, machine-readable string" and a `message` that
    "provides a human-readable explanation of what went wrong", over a meta block
    holding only the two request fields.

    Design: Corner/entities/get_deployment_with_unknown_id_returns_not_found
    """
    response = api.get_deployment(PROBE_UUID_A, RELIABILITY_1)

    validate_error(response, ERR_DEPLOYMENT_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == ERR_DEPLOYMENT_NOT_FOUND
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip() != ""
    assert_envelope_meta(body)


def test_a_snapshot_missing_a_required_field_is_rejected_and_stores_nothing(api):
    """The absent field is a shape violation, so nothing is persisted.

    PRD 3.2 requires a snapshot registration to carry a `snapshot_uri` "between 1
    and 400 characters naming the immutable storage location of the frozen data",
    and PRD 2.7 puts request-shape violations first at HTTP 400 with
    ERR_INVALID_REQUEST. A request that stops in the
    validation band never reaches the write.

    Design: Corner/entities/create_training_dataset_missing_required_field_returns_invalid_request
    """
    response = api.create_training_dataset(
        build_training_dataset_payload(
            name="snap-2026-07", snapshot_uri=OMIT, pii_review_passed=OMIT
        ),
        MLE_1,
    )
    validate_error(response, ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api.list_training_datasets(MLE_1))
    assert meta["total_count"] == 0


def test_an_unknown_enum_member_and_a_bad_bin_array_are_each_refused(api):
    """A shape violation and a domain violation answer with different codes.

    PRD 3.4 declares `pattern` as "one of `BATCH`, `REALTIME` or `SHADOW`", so
    anything else is the ERR_INVALID_REQUEST of PRD 2.7's shape band. PRD 3.2
    instead singles out the bin array: it "must contain exactly five numbers, each
    between 0.0 and 1.0, whose sum is within 0.0001 of 1.0; anything else is
    rejected with ERR_INVALID_BIN_PROPORTIONS".

    Design: Corner/entities/invalid_enum_and_malformed_array_inputs_are_rejected
    """
    dataset = create_approved_dataset(api)
    model = create_model(api)
    version = register_version(api, model["id"], dataset["id"])
    endpoint = get_success_data(
        api.create_serving_endpoint(build_serving_endpoint_payload(), ADMIN_1)
    )

    bad_enum = api.create_deployment(
        build_deployment_payload(
            version["id"],
            endpoint["id"],
            read_endpoint_version(api, endpoint["id"]),
            pattern="CANARY",
        ),
        RELIABILITY_1,
    )
    validate_error(bad_enum, ERR_INVALID_REQUEST, 400)
    _, deployment_meta = validate_paginated(
        api.list_deployments(RELIABILITY_1, {"serving_endpoint_id": endpoint["id"]})
    )
    assert deployment_meta["total_count"] == 0

    bad_bins = api.create_training_dataset(
        build_training_dataset_payload(
            baseline_bin_proportions=[0.20, 0.20, 0.20, 0.20, 0.10]
        ),
        MLE_1,
    )
    validate_error(bad_bins, ERR_INVALID_BIN_PROPORTIONS)


def test_registering_a_version_resolves_its_two_references_in_order(api):
    """The registry entry is resolved before the snapshot.

    PRD 3.3 registers a version against "the `model_id` of the owning registry
    entry" and "the `training_dataset_id` of the snapshot", and PRD 2.7 resolves
    "path and body resource references, in the order the endpoint declares them"
    at HTTP 404. A successful registration "recomputes the snapshot's
    `dependent_version_count` and increments the snapshot's `version` by 1".

    Design: Corner/entities/create_model_version_with_unknown_foreign_keys_returns_not_found
    """
    model = create_model(api)
    dataset = create_approved_dataset(api)

    both_unknown = api.create_model_version(
        build_model_version_payload(PROBE_UUID_A, PROBE_UUID_A), MLE_1
    )
    validate_error(both_unknown, ERR_MODEL_NOT_FOUND, 404)

    dataset_unknown = api.create_model_version(
        build_model_version_payload(model["id"], PROBE_UUID_A), MLE_1
    )
    validate_error(dataset_unknown, ERR_TRAINING_DATASET_NOT_FOUND, 404)

    created = get_success_data(
        api.create_model_version(
            build_model_version_payload(model["id"], dataset["id"]), MLE_1
        )
    )
    assert_version_state(created, approval_state="DRAFT")
    assert created["model_id"] == model["id"]
    assert created["training_dataset_id"] == dataset["id"]

    snapshot = get_success_data(api.get_training_dataset(dataset["id"], MLE_1))
    assert_dataset_state(snapshot, dependent_version_count=1)
    assert snapshot["version"] == dataset["version"] + 1


# ─── Fields the client does not get to write ───


def test_every_omitted_optional_input_takes_its_declared_default(api):
    """Four families, each read back on the defaults the PRD names.

    PRD 3.2 defaults `pii_review_passed` to false and starts `approval_state` at
    DRAFT; PRD 3.3 defaults `evaluation_sample_quota` to 50,000 with
    `evaluation_sample_budget` starting "equal to the quota" and defaults both
    paper-trail arrays to empty; PRD 3.4 defaults `max_traffic_pct` to 100.00 and
    `deploy_cooldown_minutes` to 30 with a new cluster starting at
    `allocated_traffic_pct` 0.00 and `operational_state` OPEN; PRD 3.1 defaults
    `revalidation_interval_days` to 90.

    Design: Corner/entities/omitted_optional_inputs_apply_declared_defaults
    """
    dataset = get_success_data(
        api.create_training_dataset(
            build_training_dataset_payload(pii_review_passed=OMIT), MLE_1
        )
    )
    assert_dataset_state(dataset, approval_state="DRAFT", pii_review_passed=False)

    model = get_success_data(
        api.create_model(build_model_payload(revalidation_interval_days=OMIT), MLE_1)
    )
    assert model["revalidation_interval_days"] == 90

    version = get_success_data(
        api.create_model_version(
            build_model_version_payload(
                model["id"],
                dataset["id"],
                evaluation_sample_quota=OMIT,
                doc_sections=OMIT,
                repro_artifacts=OMIT,
            ),
            MLE_1,
        )
    )
    assert version["evaluation_sample_quota"] == 50000
    assert_version_state(version, evaluation_sample_budget=50000)
    assert version["doc_sections"] == []
    assert version["repro_artifacts"] == []
    assert_pct(version["doc_completeness_pct"], 0.00, "doc_completeness_pct")
    assert_pct(version["reproducibility_score"], 0.00, "reproducibility_score")

    endpoint = get_success_data(
        api.create_serving_endpoint(
            build_serving_endpoint_payload(
                max_traffic_pct=OMIT, deploy_cooldown_minutes=OMIT
            ),
            ADMIN_1,
        )
    )
    assert_pct(endpoint["max_traffic_pct"], 100.00, "max_traffic_pct")
    assert endpoint["deploy_cooldown_minutes"] == 30
    assert_pct(endpoint["allocated_traffic_pct"], 0.00, "allocated_traffic_pct")
    assert endpoint["operational_state"] == "OPEN"


def test_the_two_paper_trail_percentages_are_derived_from_the_arrays(api):
    """Replacing the arrays wholesale moves both derived percentages.

    PRD 3.3 derives `doc_completeness_pct` as "100 multiplied by the number of the
    five required documentation keys that appear in `doc_sections`, divided by 5"
    and `reproducibility_score` as "100 multiplied by the number of the four
    required reproducibility keys that appear in `repro_artifacts`, divided by 4",
    and the documentation update "replaces both arrays wholesale — there is no
    merge", leaves `approval_state` alone in DRAFT and increments the version's
    `version` by 1.

    Design: Corner/entities/computed_documentation_scores_derive_from_arrays_not_from_client_input
    """
    model = create_model(api)
    dataset = create_approved_dataset(api)
    version = register_version(api, model["id"], dataset["id"])
    assert_pct(version["doc_completeness_pct"], 80.00, "doc_completeness_pct")
    assert_pct(version["reproducibility_score"], 100.00, "reproducibility_score")
    assert "LIMITATIONS" in version["doc_sections"]
    assert version["version"] == 1

    patched = get_success_data(
        api.update_version_documentation(
            version["id"],
            build_documentation_payload(
                doc_sections=["INTENDED_USE", "TRAINING_DATA", "EVALUATION"],
                repro_artifacts=[
                    "TRAINING_CODE_COMMIT",
                    "ENV_LOCKFILE_DIGEST",
                    "RANDOM_SEED",
                ],
            ),
            MLE_1,
        )
    )
    assert_pct(patched["doc_completeness_pct"], 60.00, "doc_completeness_pct")
    assert_pct(patched["reproducibility_score"], 75.00, "reproducibility_score")
    assert "LIMITATIONS" not in patched["doc_sections"]
    assert "FEATURE_SPEC_HASH" not in patched["repro_artifacts"]
    assert_version_state(patched, approval_state="DRAFT")
    assert patched["version"] == 2


def test_the_snapshot_s_own_system_fields_are_stamped_by_the_server(api):
    """The caller supplies inputs; the server supplies identity and state.

    PRD 3.2: `registered_by_user_id` "is stamped from the caller's `X-User-ID`",
    `dependent_version_count` "is initialised to 0", and `approval_state` "starts
    at `DRAFT`" — no create input can place a snapshot anywhere else on its ladder.
    PRD 2.4 stamps `created_at` and `updated_at` from the logical clock, whose
    startup default PRD 2.4 pins at 2026-08-01T00:00:00Z, and starts `version` at 1.

    Design: Corner/entities/system_fields_are_server_generated_and_client_values_are_ignored
    """
    created = get_success_data(
        api.create_training_dataset(
            build_training_dataset_payload(pii_review_passed=True), STEWARD_1
        )
    )

    assert_common_fields(created)
    assert_dataset_state(
        created,
        approval_state="DRAFT",
        dependent_version_count=0,
        pii_review_passed=True,
    )
    assert created["registered_by_user_id"] == USER_STEW_1
    assert created["decided_by_user_id"] is None
    assert created["decided_at"] is None
    assert created["revocation_reason"] is None
    assert created["created_at"] == "2026-08-01T00:00:00Z"
    assert created["updated_at"] == "2026-08-01T00:00:00Z"
    assert created["version"] == 1


# ─── An append-only ledger row and the two channels every row reads back on ───


def test_a_ledger_row_is_immutable_and_carries_no_concurrency_token(api):
    """The ramp ledger sits outside the families that carry version.

    PRD 3.4: each ramp writes one row recording "a `step_index` equal to the
    deployment's `ramp_step_index` **before** any advance, `from_traffic_pct` and
    `to_traffic_pct` bracketing the move, a `delta_pct` equal to the granted delta,
    a `reason` of `RAMP_STEP`, a `health_state_at_step` equal to the `health_state`
    observed when the step was computed, and a `clock_at_step` stamped from the
    logical clock". PRD 2.4 gives `updated_at` and `version` only to mutable rows,
    and PRD 2.3 orders this ledger by `created_at` ascending through both channels.

    Design: Corner/entities/traffic_ramp_step_is_immutable_and_carries_no_version_field
    """
    stack = build_stack(api, ramps=2)

    nested, nested_meta = validate_paginated(
        api.list_deployment_ramp_steps(stack.deployment_id, RELIABILITY_1)
    )
    assert nested_meta["total_count"] == 2

    flat, flat_meta = validate_paginated(
        api.list_traffic_ramp_steps(
            RELIABILITY_1,
            {"deployment_id": stack.deployment_id, "reason": "RAMP_STEP"},
        )
    )
    assert flat_meta["total_count"] == 2
    assert ids_of(flat) == ids_of(nested)

    first = nested[0]
    assert first["deployment_id"] == stack.deployment_id
    assert_ramp_step_row(
        first,
        step_index=0,
        from_traffic_pct=0.00,
        to_traffic_pct=5.00,
        delta_pct=5.00,
        reason="RAMP_STEP",
        health_state_at_step="HEALTHY",
    )
    assert first["clock_at_step"] == "2026-08-01T00:00:00Z"
    assert_append_only_fields(first)

    singleton = get_success_data(
        api.get_traffic_ramp_step(first["id"], RELIABILITY_1)
    )
    assert singleton == first
    assert_append_only_fields(singleton)


def test_each_observation_row_agrees_across_its_singleton_and_list_channels(api):
    """Filters narrow to exactly the intended row, and the two reads agree.

    PRD 3.4 narrows cluster lists by `region` and recomputes
    `allocated_traffic_pct` on every ramp; PRD 3.5 narrows window lists by
    `deployment_id` and `window_kind` and closes a window to `CLOSED` with a
    `FINAL` score; PRD 3.6 has a skew check derive its training statistics from the
    version's snapshot and a drift report copy `model_version_id` from the window,
    set `windows_used_count` to 0 under `TRAINING_BASELINE`, and stay in `status`
    `COMPUTED` with `severity` `NONE`, which "produces no transition at all".

    Design: Corner/entities/every_observation_row_reads_back_through_both_its_singleton_and_its_list_channel
    """
    stack = build_stack(api, ramps=1)
    create_serving_endpoint(api, ADMIN_1, region="eu-west-1")

    clusters, cluster_meta = validate_paginated(
        api.list_serving_endpoints(ADMIN_1, {"region": "us-east-1"})
    )
    assert cluster_meta["total_count"] == 1
    assert cluster_meta["has_more"] is False
    assert clusters[0]["id"] == stack.endpoint_id
    assert_pct(clusters[0]["allocated_traffic_pct"], 5.00, "allocated_traffic_pct")

    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
        observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
    )
    record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="LATENCY",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )

    windows, window_meta = validate_paginated(
        api.list_monitoring_windows(
            MLE_1,
            {"deployment_id": stack.deployment_id, "window_kind": "PERFORMANCE"},
        )
    )
    assert window_meta["total_count"] == 1
    assert windows[0]["id"] == window["id"]
    assert windows[0]["status"] == "OPEN"
    assert get_success_data(api.get_monitoring_window(window["id"], MLE_1)) == windows[0]

    check = create_skew_check(api, stack.version_id, stack.deployment_id)
    read_check = get_success_data(api.get_skew_check(check["id"], MLE_1))
    assert_skew_outcome(
        read_check, max_skew_ratio=1.0000, status="PASS", missing_features=[]
    )
    assert read_check["training_dataset_id"] == stack.dataset_id

    set_clock(api, "2026-08-02T00:00:00Z")
    closed = close_window(api, window["id"])
    assert closed["status"] == "CLOSED"
    assert closed["health_score_variant"] == "FINAL"

    report = create_drift_report(api, window["id"], MLE_1)
    assert_drift_outcome(
        report,
        drift_index=0.0000,
        severity="NONE",
        status="COMPUTED",
        effective_baseline_mode="TRAINING_BASELINE",
        windows_used_count=0,
        expected_bin_proportions=list(FLAT_BIN_PROPORTIONS),
    )
    assert report["model_version_id"] == stack.version_id
    assert report["baseline_dataset_id"] == stack.dataset_id
    assert get_success_data(api.get_drift_report(report["id"], MLE_1)) == report

    quiet, quiet_meta = validate_paginated(
        api.list_drift_reports(MLE_1, {"severity": "NONE"})
    )
    assert quiet_meta["total_count"] == 1
    assert quiet[0]["id"] == report["id"]

    response = api.list_drift_reports(MLE_1, {"severity": "CRITICAL"})
    validate_success(response)
    empty, empty_meta = validate_paginated(response)
    assert empty == []
    assert empty_meta["total_count"] == 0
