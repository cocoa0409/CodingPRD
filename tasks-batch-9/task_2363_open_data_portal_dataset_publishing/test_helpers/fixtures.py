"""
Composite setup helpers.

Every test starts against an empty database, so all preconditions are built from
scratch through the API. These helpers implement the ladder the PRD's publishing
workflow implies — register a department, fund it, define a licence, inventory a
dataset, screen it, land its metadata and privacy artefacts, mark it ready,
publish it, configure and arm a pipeline, schedule and start a run — and each rung
accepts `**overrides` so a test can perturb exactly one input.

Setup calls use `get_success_data()`: a setup step that fails raises immediately
with the API's own error identifier instead of surfacing as a confusing assertion
several calls later. All returned values are the API's own response bodies, so
tests read PRD-exact field names off them.

`ctx` dictionaries returned by the composite helpers carry the identifiers and the
last-seen bodies of everything the ladder built, plus the per-department coordinator
headers a dataset-scoped write needs.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient, api_client
from .constants import CLOCK_START
from .test_users import (
    ANONYMOUS_HEADERS,
    PORTAL_ADMIN_HEADERS,
    PRIVACY_ASSESSOR_HEADERS,
    PRIVACY_DECIDER_HEADERS,
    make_community_member_headers,
    make_data_coordinator_headers,
)


def _api(api: Optional[ApiClient]) -> ApiClient:
    return api or api_client


# ─── The logical clock ────────────────────────────────────────────────


def set_clock(to_iso8601: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    """Advance the logical clock, which every temporal rule reads."""
    return get_success_data(
        _api(api).set_clock(factories.clock_payload(to_iso8601), PORTAL_ADMIN_HEADERS)
    )


def reset_clock_to_start(api: Optional[ApiClient] = None) -> Dict[str, Any]:
    """Pin the logical clock at its documented starting instant."""
    return set_clock(CLOCK_START, api=api)


# ─── Registries ───────────────────────────────────────────────────────


def register_department(api: Optional[ApiClient] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        _api(api).create_department(factories.department_payload(**overrides), PORTAL_ADMIN_HEADERS)
    )


def grant_credits(
    department_id: str, credit_units: float = 100.00, api: Optional[ApiClient] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).grant_department_credits(
            department_id,
            factories.credit_grant_payload(credit_units=credit_units, **overrides),
            PORTAL_ADMIN_HEADERS,
        )
    )


def create_license(api: Optional[ApiClient] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        _api(api).create_license(factories.license_payload(**overrides), PORTAL_ADMIN_HEADERS)
    )


def retire_license(license_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).retire_license(license_id, PORTAL_ADMIN_HEADERS))


def create_ingest_runner(api: Optional[ApiClient] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        _api(api).create_ingest_runner(factories.ingest_runner_payload(**overrides), PORTAL_ADMIN_HEADERS)
    )


def update_ingest_runner(
    runner_id: str, api: Optional[ApiClient] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).update_ingest_runner(
            runner_id, factories.runner_update_payload(**overrides), PORTAL_ADMIN_HEADERS
        )
    )


# ─── Datasets ─────────────────────────────────────────────────────────


def inventory_dataset(department_id: str, api: Optional[ApiClient] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        _api(api).create_dataset(
            factories.dataset_payload(department_id, **overrides),
            make_data_coordinator_headers(department_id),
        )
    )


def screen_dataset(dataset_id: str, department_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).screen_dataset(dataset_id, make_data_coordinator_headers(department_id))
    )


def set_aggregation(
    dataset_id: str, department_id: str, aggregation_geography: str, api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).set_dataset_aggregation(
            dataset_id,
            factories.aggregation_payload(aggregation_geography),
            make_data_coordinator_headers(department_id),
        )
    )


def mark_ready(dataset_id: str, department_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).mark_dataset_ready(dataset_id, make_data_coordinator_headers(department_id))
    )


def publish_dataset(
    dataset_id: str,
    department_id: str,
    initial_row_count: int = 50000,
    api: Optional[ApiClient] = None,
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).publish_dataset(
            dataset_id,
            factories.publish_payload(initial_row_count=initial_row_count),
            make_data_coordinator_headers(department_id),
        )
    )


def report_usage_epoch(
    dataset_id: str,
    epoch_index: int,
    api_call_count: int,
    download_count: int,
    api: Optional[ApiClient] = None,
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).report_dataset_usage(
            dataset_id,
            factories.usage_report_payload(epoch_index, api_call_count, download_count),
            PORTAL_ADMIN_HEADERS,
        )
    )


def report_usage_epochs(
    dataset_id: str, epochs: List[Dict[str, int]], api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    """Record several usage epochs in the order supplied.

    Each item carries `epoch_index`, `api_call_count` and `download_count`.
    """
    dataset: Dict[str, Any] = {}
    for epoch in epochs:
        dataset = report_usage_epoch(
            dataset_id,
            epoch["epoch_index"],
            epoch["api_call_count"],
            epoch["download_count"],
            api=api,
        )
    return dataset


def commit_high_value(dataset_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).commit_high_value(dataset_id, PORTAL_ADMIN_HEADERS))


def read_dataset(dataset_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).get_dataset(dataset_id, ANONYMOUS_HEADERS))


def current_dataset_version(dataset_id: str, api: Optional[ApiClient] = None) -> int:
    """Read the dataset's current `version` for use as an optimistic-concurrency token."""
    return int(read_dataset(dataset_id, api=api)["version"])


def read_scorecard(department_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).get_department_scorecard(department_id, PORTAL_ADMIN_HEADERS))


def read_department(department_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).get_department(department_id, ANONYMOUS_HEADERS))


def read_analytics(dataset_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).get_dataset_analytics(dataset_id, ANONYMOUS_HEADERS))


def list_all_dataset_versions(api: Optional[ApiClient] = None) -> List[Dict[str, Any]]:
    """Every version row, read through the version-history listing."""
    data = get_success_data(_api(api).list_dataset_versions(ANONYMOUS_HEADERS, params={"limit": 100}))
    return list(data)


def versions_of_dataset(dataset_id: str, api: Optional[ApiClient] = None) -> List[Dict[str, Any]]:
    """The version rows belonging to one dataset, in listing order."""
    return [row for row in list_all_dataset_versions(api=api) if row.get("dataset_id") == dataset_id]


# ─── Metadata records ─────────────────────────────────────────────────


def draft_metadata_record(
    dataset_id: str,
    license_id: str,
    department_id: str,
    api: Optional[ApiClient] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).create_metadata_record(
            factories.metadata_record_payload(dataset_id, license_id, **overrides),
            make_data_coordinator_headers(department_id),
        )
    )


def revise_metadata_record(
    metadata_record_id: str, department_id: str, api: Optional[ApiClient] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).revise_metadata_record(
            metadata_record_id,
            factories.metadata_revision_payload(**overrides),
            make_data_coordinator_headers(department_id),
        )
    )


def submit_metadata_record(
    metadata_record_id: str, department_id: str, api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).submit_metadata_record(
            metadata_record_id, make_data_coordinator_headers(department_id)
        )
    )


def accept_metadata_record(metadata_record_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).decide_metadata_record(
            metadata_record_id, factories.decision_payload("ACCEPT"), PORTAL_ADMIN_HEADERS
        )
    )


def return_metadata_record(
    metadata_record_id: str, returned_reason: str, api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).decide_metadata_record(
            metadata_record_id,
            factories.decision_payload("RETURN", returned_reason=returned_reason),
            PORTAL_ADMIN_HEADERS,
        )
    )


def land_accepted_metadata(
    dataset_id: str,
    license_id: str,
    department_id: str,
    api: Optional[ApiClient] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft, submit and accept a metadata record for a dataset in screening."""
    record = draft_metadata_record(dataset_id, license_id, department_id, api=api, **overrides)
    submit_metadata_record(record["id"], department_id, api=api)
    return accept_metadata_record(record["id"], api=api)


# ─── Privacy assessments ──────────────────────────────────────────────


def open_privacy_assessment(
    dataset_id: str, api: Optional[ApiClient] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).create_privacy_assessment(
            factories.privacy_assessment_payload(dataset_id, **overrides), PRIVACY_ASSESSOR_HEADERS
        )
    )


def revise_privacy_assessment(
    assessment_id: str, api: Optional[ApiClient] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).revise_privacy_assessment(
            assessment_id, factories.assessment_revision_payload(**overrides), PRIVACY_ASSESSOR_HEADERS
        )
    )


def submit_privacy_assessment(assessment_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).submit_privacy_assessment(assessment_id, PRIVACY_ASSESSOR_HEADERS)
    )


def clear_privacy_assessment(assessment_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).decide_privacy_assessment(
            assessment_id, factories.decision_payload("CLEAR"), PRIVACY_DECIDER_HEADERS
        )
    )


def block_privacy_assessment(
    assessment_id: str, block_reason: str = "RISK_TOO_HIGH", api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).decide_privacy_assessment(
            assessment_id, factories.block_decision_payload(block_reason), PRIVACY_DECIDER_HEADERS
        )
    )


def reopen_privacy_assessment(assessment_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).reopen_privacy_assessment(assessment_id, PRIVACY_ASSESSOR_HEADERS)
    )


def land_cleared_assessment(
    dataset_id: str,
    api: Optional[ApiClient] = None,
    verified_smallest_cell_size: int = 20,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open, measure, submit and clear a privacy assessment for a screening dataset."""
    assessment = open_privacy_assessment(dataset_id, api=api, **overrides)
    revise_privacy_assessment(
        assessment["id"], api=api, verified_smallest_cell_size=verified_smallest_cell_size
    )
    submit_privacy_assessment(assessment["id"], api=api)
    return clear_privacy_assessment(assessment["id"], api=api)


# ─── Pipelines ────────────────────────────────────────────────────────


def configure_pipeline(
    dataset_id: str,
    runner_id: str,
    department_id: str,
    api: Optional[ApiClient] = None,
    expected_dataset_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Configure a pipeline, reading the dataset's current `version` as the token."""
    token = (
        expected_dataset_version
        if expected_dataset_version is not None
        else current_dataset_version(dataset_id, api=api)
    )
    return get_success_data(
        _api(api).create_publication_pipeline(
            factories.pipeline_payload(dataset_id, runner_id, token, **overrides),
            make_data_coordinator_headers(department_id),
        )
    )


def arm_pipeline(pipeline_id: str, department_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).arm_pipeline(pipeline_id, make_data_coordinator_headers(department_id))
    )


def suspend_pipeline(
    pipeline_id: str, department_id: str, api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).suspend_pipeline(pipeline_id, make_data_coordinator_headers(department_id))
    )


def resume_pipeline(pipeline_id: str, department_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).resume_pipeline(pipeline_id, make_data_coordinator_headers(department_id))
    )


def decommission_pipeline(
    pipeline_id: str, department_id: str, api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).decommission_pipeline(pipeline_id, make_data_coordinator_headers(department_id))
    )


def read_pipeline(pipeline_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).get_publication_pipeline(pipeline_id, PORTAL_ADMIN_HEADERS))


# ─── Runs ─────────────────────────────────────────────────────────────


def schedule_run(
    pipeline_id: str, scheduled_for_utc: str, api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).create_pipeline_run(
            factories.pipeline_run_payload(pipeline_id, scheduled_for_utc), PORTAL_ADMIN_HEADERS
        )
    )


def start_run(run_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).start_run(run_id, PORTAL_ADMIN_HEADERS))


def report_success(run_id: str, rows_ingested: int, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).report_run_success(
            run_id, factories.run_success_payload(rows_ingested), PORTAL_ADMIN_HEADERS
        )
    )


def report_failure(
    run_id: str, failure_code: str = "TIMEOUT", api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).report_run_failure(
            run_id, factories.run_failure_payload(failure_code), PORTAL_ADMIN_HEADERS
        )
    )


def requeue_run(run_id: str, scheduled_for_utc: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).requeue_run(run_id, factories.requeue_payload(scheduled_for_utc), PORTAL_ADMIN_HEADERS)
    )


def read_run(run_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).get_pipeline_run(run_id, PORTAL_ADMIN_HEADERS))


def run_one_failed_cycle(
    pipeline_id: str,
    scheduled_for_utc: str,
    failure_code: str = "TIMEOUT",
    api: Optional[ApiClient] = None,
) -> Dict[str, Any]:
    """Schedule, start and fail one run of an armed pipeline."""
    run = schedule_run(pipeline_id, scheduled_for_utc, api=api)
    start_run(run["id"], api=api)
    return report_failure(run["id"], failure_code, api=api)


# ─── Manual versions ──────────────────────────────────────────────────


def publish_version(
    dataset_id: str,
    department_id: str,
    change_type: str,
    row_count: int,
    api: Optional[ApiClient] = None,
    correction_issue_id: Optional[str] = None,
    expected_dataset_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    token = (
        expected_dataset_version
        if expected_dataset_version is not None
        else current_dataset_version(dataset_id, api=api)
    )
    return get_success_data(
        _api(api).create_dataset_version(
            factories.dataset_version_payload(
                dataset_id,
                change_type,
                row_count,
                token,
                correction_issue_id=correction_issue_id,
                **overrides,
            ),
            make_data_coordinator_headers(department_id),
        )
    )


# ─── Community ────────────────────────────────────────────────────────


def register_member(api: Optional[ApiClient] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        _api(api).register_member(factories.member_payload(**overrides), ANONYMOUS_HEADERS)
    )


def read_member(member_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).get_member(member_id, PORTAL_ADMIN_HEADERS))


def file_quality_issue(
    dataset_id: str,
    member_id: str,
    severity: str = "CRITICAL",
    category: str = "PRIVACY",
    api: Optional[ApiClient] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).create_quality_issue(
            factories.quality_issue_payload(
                dataset_id, member_id, severity=severity, category=category, **overrides
            ),
            make_community_member_headers(member_id),
        )
    )


def triage_quality_issue(
    issue_id: str, department_id: str, api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).triage_quality_issue(issue_id, make_data_coordinator_headers(department_id))
    )


def accept_quality_issue(
    issue_id: str, department_id: str, api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).decide_quality_issue(
            issue_id, factories.decision_payload("ACCEPT"), make_data_coordinator_headers(department_id)
        )
    )


def reject_quality_issue(
    issue_id: str,
    department_id: str,
    reject_reason: str = "NOT_REPRODUCIBLE",
    api: Optional[ApiClient] = None,
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).decide_quality_issue(
            issue_id,
            factories.reject_issue_payload(reject_reason),
            make_data_coordinator_headers(department_id),
        )
    )


def link_correction(
    issue_id: str, department_id: str, dataset_version_id: str, api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).link_correction(
            issue_id,
            factories.link_correction_payload(dataset_version_id),
            make_data_coordinator_headers(department_id),
        )
    )


def file_and_triage_issue(
    dataset_id: str,
    member_id: str,
    department_id: str,
    severity: str = "CRITICAL",
    category: str = "PRIVACY",
    api: Optional[ApiClient] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File a quality issue and move it to `TRIAGED`, ready for a decision."""
    issue = file_quality_issue(
        dataset_id, member_id, severity=severity, category=category, api=api, **overrides
    )
    return triage_quality_issue(issue["id"], department_id, api=api)


def open_dataset_request(member_id: str, api: Optional[ApiClient] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        _api(api).create_dataset_request(
            factories.dataset_request_payload(member_id, **overrides),
            make_community_member_headers(member_id),
        )
    )


def cast_vote(request_id: str, member_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).cast_request_vote(
            request_id, factories.vote_payload(member_id), make_community_member_headers(member_id)
        )
    )


def review_request(request_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).review_dataset_request(request_id, PORTAL_ADMIN_HEADERS))


def decide_request(
    request_id: str,
    decision: str,
    api: Optional[ApiClient] = None,
    decision_note: str = "Adjudicated by the programme office.",
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).decide_dataset_request(
            request_id,
            factories.request_decision_payload(decision, decision_note=decision_note),
            PORTAL_ADMIN_HEADERS,
        )
    )


def fulfill_request(request_id: str, dataset_id: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(
        _api(api).fulfill_dataset_request(
            request_id, factories.fulfill_payload(dataset_id), PORTAL_ADMIN_HEADERS
        )
    )


def submit_showcase_app(
    dataset_id: str, member_id: str, label: str, api: Optional[ApiClient] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).submit_showcase_app(
            dataset_id,
            factories.showcase_app_payload(label, member_id, **overrides),
            make_community_member_headers(member_id),
        )
    )


def decide_showcase_app(
    dataset_id: str, label: str, decision: str, api: Optional[ApiClient] = None
) -> Dict[str, Any]:
    return get_success_data(
        _api(api).decide_showcase_app(
            dataset_id, label, factories.decision_payload(decision), PORTAL_ADMIN_HEADERS
        )
    )


# ─── Operational sweep ────────────────────────────────────────────────


def run_sweep(api: Optional[ApiClient] = None) -> Dict[str, Any]:
    return get_success_data(_api(api).run_ops_sweep(PORTAL_ADMIN_HEADERS))


def advance_clock_and_sweep(to_iso8601: str, api: Optional[ApiClient] = None) -> Dict[str, Any]:
    """Move the logical clock and then run the portal sweep, which is what
    materialises staleness and service-level breaches."""
    set_clock(to_iso8601, api=api)
    return run_sweep(api=api)


# ─── Composite ladders ────────────────────────────────────────────────


def setup_funded_department(
    api: Optional[ApiClient] = None,
    credit_units: float = 100.00,
    department_overrides: Optional[Dict[str, Any]] = None,
    license_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Clock at its starting instant, one funded department, one licence."""
    reset_clock_to_start(api=api)
    department = register_department(api=api, **(department_overrides or {}))
    if credit_units > 0:
        department = grant_credits(department["id"], credit_units=credit_units, api=api)
    license_term = create_license(api=api, **(license_overrides or {}))
    return {
        "department": department,
        "department_id": department["id"],
        "coordinator_headers": make_data_coordinator_headers(department["id"]),
        "license": license_term,
        "license_id": license_term["id"],
    }


def setup_screening_dataset(
    api: Optional[ApiClient] = None,
    credit_units: float = 100.00,
    department_overrides: Optional[Dict[str, Any]] = None,
    license_overrides: Optional[Dict[str, Any]] = None,
    dataset_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A funded department whose dataset has been moved `INVENTORIED → SCREENING`."""
    ctx = setup_funded_department(
        api=api,
        credit_units=credit_units,
        department_overrides=department_overrides,
        license_overrides=license_overrides,
    )
    dataset = inventory_dataset(ctx["department_id"], api=api, **(dataset_overrides or {}))
    dataset = screen_dataset(dataset["id"], ctx["department_id"], api=api)
    ctx["dataset"] = dataset
    ctx["dataset_id"] = dataset["id"]
    return ctx


def setup_ready_dataset(
    api: Optional[ApiClient] = None,
    credit_units: float = 100.00,
    department_overrides: Optional[Dict[str, Any]] = None,
    license_overrides: Optional[Dict[str, Any]] = None,
    dataset_overrides: Optional[Dict[str, Any]] = None,
    metadata_overrides: Optional[Dict[str, Any]] = None,
    assessment_overrides: Optional[Dict[str, Any]] = None,
    verified_smallest_cell_size: int = 20,
    aggregation_geography: Optional[str] = None,
) -> Dict[str, Any]:
    """A screening dataset with an `ACCEPTED` metadata record and a `CLEARED`
    privacy assessment, marked `READY`."""
    ctx = setup_screening_dataset(
        api=api,
        credit_units=credit_units,
        department_overrides=department_overrides,
        license_overrides=license_overrides,
        dataset_overrides=dataset_overrides,
    )
    ctx["metadata_record"] = land_accepted_metadata(
        ctx["dataset_id"], ctx["license_id"], ctx["department_id"], api=api, **(metadata_overrides or {})
    )
    ctx["metadata_record_id"] = ctx["metadata_record"]["id"]
    ctx["assessment"] = land_cleared_assessment(
        ctx["dataset_id"],
        api=api,
        verified_smallest_cell_size=verified_smallest_cell_size,
        **(assessment_overrides or {}),
    )
    ctx["assessment_id"] = ctx["assessment"]["id"]
    if aggregation_geography is not None:
        set_aggregation(ctx["dataset_id"], ctx["department_id"], aggregation_geography, api=api)
    ctx["dataset"] = mark_ready(ctx["dataset_id"], ctx["department_id"], api=api)
    return ctx


def setup_published_dataset(
    api: Optional[ApiClient] = None,
    credit_units: float = 100.00,
    department_overrides: Optional[Dict[str, Any]] = None,
    license_overrides: Optional[Dict[str, Any]] = None,
    dataset_overrides: Optional[Dict[str, Any]] = None,
    metadata_overrides: Optional[Dict[str, Any]] = None,
    assessment_overrides: Optional[Dict[str, Any]] = None,
    verified_smallest_cell_size: int = 20,
    aggregation_geography: Optional[str] = None,
    initial_row_count: int = 50000,
) -> Dict[str, Any]:
    """A dataset carried all the way to `PUBLISHED` with its first `LIVE` version."""
    ctx = setup_ready_dataset(
        api=api,
        credit_units=credit_units,
        department_overrides=department_overrides,
        license_overrides=license_overrides,
        dataset_overrides=dataset_overrides,
        metadata_overrides=metadata_overrides,
        assessment_overrides=assessment_overrides,
        verified_smallest_cell_size=verified_smallest_cell_size,
        aggregation_geography=aggregation_geography,
    )
    ctx["dataset"] = publish_dataset(
        ctx["dataset_id"], ctx["department_id"], initial_row_count=initial_row_count, api=api
    )
    return ctx


def setup_armed_pipeline(
    api: Optional[ApiClient] = None,
    credit_units: float = 100.00,
    department_overrides: Optional[Dict[str, Any]] = None,
    license_overrides: Optional[Dict[str, Any]] = None,
    dataset_overrides: Optional[Dict[str, Any]] = None,
    metadata_overrides: Optional[Dict[str, Any]] = None,
    assessment_overrides: Optional[Dict[str, Any]] = None,
    verified_smallest_cell_size: int = 20,
    aggregation_geography: Optional[str] = None,
    initial_row_count: int = 50000,
    runner_overrides: Optional[Dict[str, Any]] = None,
    pipeline_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A published dataset with an `ARMED` pipeline on a fresh `ACTIVE` runner."""
    ctx = setup_published_dataset(
        api=api,
        credit_units=credit_units,
        department_overrides=department_overrides,
        license_overrides=license_overrides,
        dataset_overrides=dataset_overrides,
        metadata_overrides=metadata_overrides,
        assessment_overrides=assessment_overrides,
        verified_smallest_cell_size=verified_smallest_cell_size,
        aggregation_geography=aggregation_geography,
        initial_row_count=initial_row_count,
    )
    runner = create_ingest_runner(api=api, **(runner_overrides or {}))
    pipeline = configure_pipeline(
        ctx["dataset_id"], runner["id"], ctx["department_id"], api=api, **(pipeline_overrides or {})
    )
    pipeline = arm_pipeline(pipeline["id"], ctx["department_id"], api=api)
    ctx["runner"] = runner
    ctx["runner_id"] = runner["id"]
    ctx["pipeline"] = pipeline
    ctx["pipeline_id"] = pipeline["id"]
    return ctx


def setup_running_run(
    api: Optional[ApiClient] = None,
    scheduled_for_utc: str = "2026-08-01T09:00:00Z",
    **kwargs: Any,
) -> Dict[str, Any]:
    """An armed pipeline with one run started, the clock standing at its slot."""
    ctx = setup_armed_pipeline(api=api, **kwargs)
    set_clock(scheduled_for_utc, api=api)
    run = schedule_run(ctx["pipeline_id"], scheduled_for_utc, api=api)
    run = start_run(run["id"], api=api)
    ctx["run"] = run
    ctx["run_id"] = run["id"]
    return ctx


def setup_member(api: Optional[ApiClient] = None, **overrides: Any) -> Dict[str, Any]:
    """Register one community member and return the member plus its headers."""
    member = register_member(api=api, **overrides)
    return {
        "member": member,
        "member_id": member["id"],
        "member_headers": make_community_member_headers(member["id"]),
    }
