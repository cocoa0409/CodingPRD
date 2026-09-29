"""
Request-payload factories.

Each factory returns a valid request body for one endpoint, with PRD-exact field
names and sensible defaults, and accepts `**overrides` so a test can perturb one
field at a time. Fields the PRD declares optional are omitted unless supplied.
"""

from typing import Any, Dict, Optional

# ─── Registries ───────────────────────────────────────────────────────


def department_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": "City Transportation Department",
        "code": "DOT",
        "contact_email": "opendata@dot.city.gov",
    }
    payload.update(overrides)
    return payload


def credit_grant_payload(credit_units: float = 100.00, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "credit_units": credit_units,
        "memo": "FY27 publication credits",
    }
    payload.update(overrides)
    return payload


def license_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "code": "CC-BY-4.0",
        "name": "Creative Commons Attribution 4.0",
        "attribution_required": True,
        "commercial_use_allowed": True,
        "share_alike": False,
        "attribution_text_template": "Source: City of Example, {dataset_title}",
    }
    payload.update(overrides)
    return payload


def ingest_runner_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"name": "ingest-runner-a", "cooldown_minutes": 15}
    payload.update(overrides)
    return payload


def runner_update_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ─── Datasets ─────────────────────────────────────────────────────────


def dataset_payload(department_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_id": department_id,
        "title": "Weekly Traffic Counts",
        "slug": "weekly-traffic-counts",
        "description": "Signalised intersection volumes aggregated weekly.",
        "update_frequency": "WEEKLY",
        "column_count": 9,
        "sensitivity_class": "PUBLIC",
        "public_demand_score": 92,
        "policy_value_score": 96,
    }
    payload.update(overrides)
    return payload


def aggregation_payload(aggregation_geography: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"aggregation_geography": aggregation_geography}
    payload.update(overrides)
    return payload


def publish_payload(initial_row_count: int = 50000, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"initial_row_count": initial_row_count}
    payload.update(overrides)
    return payload


def usage_report_payload(
    epoch_index: int, api_call_count: int, download_count: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "epoch_index": epoch_index,
        "api_call_count": api_call_count,
        "download_count": download_count,
    }
    payload.update(overrides)
    return payload


def showcase_app_payload(label: str, submitter_member_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "label": label,
        "name": "Transit Delay Explorer",
        "url": "https://apps.civic.example/transit-delay-explorer",
        "submitter_member_id": submitter_member_id,
    }
    payload.update(overrides)
    return payload


def decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ─── Metadata records ─────────────────────────────────────────────────


def metadata_record_payload(dataset_id: str, license_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dataset_id": dataset_id,
        "license_id": license_id,
        "data_dictionary_field_count": 9,
        "provenance_detail_lines": 24,
        "contact_email": "datasets@dot.city.gov",
        "declared_update_frequency": "WEEKLY",
        "attribution_element_count": 6,
    }
    payload.update(overrides)
    return payload


def metadata_revision_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ─── Privacy assessments ──────────────────────────────────────────────


def privacy_assessment_payload(dataset_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dataset_id": dataset_id,
        "declared_quasi_identifier_count": 2,
        "declared_smallest_cell_size": 20,
        "population_size": 100000,
    }
    payload.update(overrides)
    return payload


def assessment_revision_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def block_decision_payload(block_reason: str = "RISK_TOO_HIGH", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": "BLOCK", "block_reason": block_reason}
    payload.update(overrides)
    return payload


# ─── Pipelines and runs ───────────────────────────────────────────────


def pipeline_payload(
    dataset_id: str,
    runner_id: str,
    expected_dataset_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dataset_id": dataset_id,
        "runner_id": runner_id,
        "cadence": "WEEKLY",
        "window_start_minute": 540,
        "window_duration_minutes": 120,
        "alert_email": "pipeline-alerts@dot.city.gov",
        "expected_dataset_version": expected_dataset_version,
    }
    payload.update(overrides)
    return payload


def pipeline_run_payload(pipeline_id: str, scheduled_for_utc: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "pipeline_id": pipeline_id,
        "scheduled_for_utc": scheduled_for_utc,
    }
    payload.update(overrides)
    return payload


def run_success_payload(rows_ingested: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rows_ingested": rows_ingested}
    payload.update(overrides)
    return payload


def run_failure_payload(failure_code: str = "TIMEOUT", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"failure_code": failure_code}
    payload.update(overrides)
    return payload


def requeue_payload(scheduled_for_utc: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"scheduled_for_utc": scheduled_for_utc}
    payload.update(overrides)
    return payload


# ─── Dataset versions ─────────────────────────────────────────────────


def dataset_version_payload(
    dataset_id: str,
    change_type: str,
    row_count: int,
    expected_dataset_version: int,
    correction_issue_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dataset_id": dataset_id,
        "change_type": change_type,
        "row_count": row_count,
        "expected_dataset_version": expected_dataset_version,
    }
    if correction_issue_id is not None:
        payload["correction_issue_id"] = correction_issue_id
    payload.update(overrides)
    return payload


# ─── Community ────────────────────────────────────────────────────────


def member_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "email": "ana@civic.example",
        "display_name": "Ana Reuser",
        "organization": "Civic Data Lab",
    }
    payload.update(overrides)
    return payload


def quality_issue_payload(
    dataset_id: str,
    reporter_member_id: str,
    severity: str = "CRITICAL",
    category: str = "PRIVACY",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dataset_id": dataset_id,
        "reporter_member_id": reporter_member_id,
        "severity": severity,
        "category": category,
        "description": "Rows leak a direct identifier in the operator column.",
    }
    payload.update(overrides)
    return payload


def reject_issue_payload(reject_reason: str = "NOT_REPRODUCIBLE", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": "REJECT", "reject_reason": reject_reason}
    payload.update(overrides)
    return payload


def link_correction_payload(dataset_version_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"dataset_version_id": dataset_version_id}
    payload.update(overrides)
    return payload


def dataset_request_payload(requester_member_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requester_member_id": requester_member_id,
        "title": "Curb regulation inventory",
        "rationale": "Needed to model loading-zone demand across the downtown grid.",
    }
    payload.update(overrides)
    return payload


def vote_payload(member_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"member_id": member_id}
    payload.update(overrides)
    return payload


def request_decision_payload(
    decision: str, decision_note: str = "Adjudicated by the programme office.", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "decision_note": decision_note}
    payload.update(overrides)
    return payload


def fulfill_payload(dataset_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"dataset_id": dataset_id}
    payload.update(overrides)
    return payload


# ─── Clock ────────────────────────────────────────────────────────────


def clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
