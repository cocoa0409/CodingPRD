"""Composite fixtures and setup helpers.

The harness restarts the server before every test, so every test begins with an
empty database and the logical clock at its startup default. Nothing here is
shared between tests.

The helpers below are deliberately thin: each one performs one setup call, checks
it succeeded with a clear message, and returns the created row so the caller can
capture identifiers exactly as the scenario requires. Composite helpers chain
them into the states most scenarios start from.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import INITIAL_CLOCK
from .test_users import (
    CLERK_HEADERS,
    SUPERVISOR_HEADERS,
    make_counsel_headers,
    make_requester_headers,
    make_reviewer_headers,
    make_technician_headers,
)


# ------------------------------------------------------------ tier 1: client
@pytest.fixture
def api() -> ApiClient:
    """Raw client against the API under test."""
    return ApiClient()


@pytest.fixture
def clerk() -> Dict[str, str]:
    return dict(CLERK_HEADERS)


@pytest.fixture
def supervisor() -> Dict[str, str]:
    return dict(SUPERVISOR_HEADERS)


# --------------------------------------------------------------- the clock
def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock; this call mutates no entity."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), SUPERVISOR_HEADERS))


# ------------------------------------------------- tier 2: single entities
def create_staff(
    api: ApiClient, full_name: str, role_type: str, level: int = 3
) -> Dict[str, Any]:
    return get_success_data(
        api.create_staff(f.staff_payload(full_name, role_type, level), SUPERVISOR_HEADERS)
    )


def create_requester(
    api: ApiClient,
    full_name: str = "Pat Public",
    email: str = "pat@example.org",
    requester_type: str = "GENERAL_PUBLIC",
    **extra: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_requester(
            f.requester_payload(full_name, email, requester_type, **extra), CLERK_HEADERS
        )
    )


def create_asset(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_video_asset(f.video_asset_payload(**overrides), CLERK_HEADERS))


def create_depicted_individual(
    api: ApiClient, asset_id: str, display_label: str, relationship: str
) -> Dict[str, Any]:
    return get_success_data(
        api.create_depicted_individual(
            asset_id, f.depicted_individual_payload(display_label, relationship), CLERK_HEADERS
        )
    )


def create_request(api: ApiClient, requester_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_request(f.request_payload(requester_id, **overrides), CLERK_HEADERS)
    )


# --------------------------------------------------- request-side helpers
def request_version(api: ApiClient, request_id: str) -> int:
    """Read the request's current version, as an optimistic-concurrency caller must."""
    return get_request(api, request_id)["version"]


def clarify_scope(api: ApiClient, request_id: str, **overrides: Any) -> Dict[str, Any]:
    """Clarify scope with a freshly read version, moving INTAKE -> SCOPING."""
    version = overrides.pop("expected_request_version", None)
    if version is None:
        version = request_version(api, request_id)
    return get_success_data(
        api.clarify_scope(
            request_id, f.scope_clarification_payload(version, **overrides), CLERK_HEADERS
        )
    )


def attach_record(api: ApiClient, request_id: str, asset_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.attach_responsive_record(request_id, f.responsive_record_payload(asset_id), CLERK_HEADERS)
    )


def rule_inclusion(api: ApiClient, record_id: str, inclusion_status: str = "RESPONSIVE") -> Dict[str, Any]:
    return get_success_data(
        api.rule_inclusion(record_id, f.inclusion_payload(inclusion_status), CLERK_HEADERS)
    )


def assert_claim(
    api: ApiClient,
    record_id: str,
    counsel_id: str,
    exemption_code: str = "PERSONAL_PRIVACY",
    asserted_scope: str = "PARTIAL_REDACT",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.assert_exemption_claim(
            record_id,
            f.exemption_claim_payload(exemption_code, asserted_scope, **overrides),
            make_counsel_headers(counsel_id),
        )
    )


def adjudicate(
    api: ApiClient, claim_id: str, counsel_id: str, disposition: str = "SUSTAINED", **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.adjudicate_claim(
            claim_id, f.adjudication_payload(disposition, **overrides), make_counsel_headers(counsel_id)
        )
    )


def open_task(
    api: ApiClient,
    record_id: str,
    technician_id: str,
    target_type: str = "FACE",
    clip_start_ms: int = 0,
    clip_end_ms: int = 30000,
    exemption_claim_id: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_redaction_task(
            record_id,
            f.redaction_task_payload(
                technician_id, target_type, clip_start_ms, clip_end_ms, exemption_claim_id
            ),
            make_technician_headers(technician_id),
        )
    )


def submit_for_qa(
    api: ApiClient,
    task_id: str,
    technician_id: str,
    reviewer_id: str,
    logged_labor_minutes: int = 5,
    qa_window_start_at: str = "2026-08-01T13:00:00Z",
    qa_window_end_at: str = "2026-08-01T14:00:00Z",
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_qa(
            task_id,
            f.submit_qa_payload(
                reviewer_id, logged_labor_minutes, qa_window_start_at, qa_window_end_at
            ),
            make_technician_headers(technician_id),
        )
    )


def record_verdict(
    api: ApiClient,
    task_id: str,
    reviewer_id: str,
    outcome: str = "PASS",
    defect_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_qa_outcome(
            task_id, f.qa_outcome_payload(outcome, defect_codes), make_reviewer_headers(reviewer_id)
        )
    )


def issue_notice(api: ApiClient, individual_id: str, notice_method: str = "FIRST_CLASS_MAIL") -> Dict[str, Any]:
    return get_success_data(
        api.issue_notification(individual_id, f.notification_payload(notice_method), CLERK_HEADERS)
    )


def create_estimate(
    api: ApiClient,
    request_id: str,
    basis: str = "PRESUMPTIVE",
    media_type: str = "DIGITAL_DOWNLOAD",
    expected_request_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        expected_request_version
        if expected_request_version is not None
        else request_version(api, request_id)
    )
    return get_success_data(
        api.create_fee_estimate(
            request_id, f.fee_estimate_payload(version, basis, media_type), CLERK_HEADERS
        )
    )


def post_payment(api: ApiClient, request_id: str, requester_id: str, amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.post_payment(
            request_id, f.payment_payload(amount_cents), make_requester_headers(requester_id)
        )
    )


def issue_invoice(api: ApiClient, request_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.issue_invoice(request_id, f.invoice_payload(**overrides), SUPERVISOR_HEADERS)
    )


def produce_release(api: ApiClient, request_id: str, media_type: str = "DIGITAL_DOWNLOAD") -> Dict[str, Any]:
    return get_success_data(
        api.create_release_package(request_id, f.release_package_payload(media_type), CLERK_HEADERS)
    )


def place_hold(api: ApiClient, counsel_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_litigation_hold(f.litigation_hold_payload(**overrides), make_counsel_headers(counsel_id))
    )


# --------------------------------------------------------------- readbacks
def get_request(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_request(request_id, CLERK_HEADERS))


def get_record(api: ApiClient, record_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_responsive_record(record_id, CLERK_HEADERS))


def get_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_exemption_claim(claim_id, CLERK_HEADERS))


def get_task(api: ApiClient, task_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_redaction_task(task_id, CLERK_HEADERS))


def get_staff(api: ApiClient, staff_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_staff(staff_id, CLERK_HEADERS))


def get_requester(api: ApiClient, requester_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_requester(requester_id, CLERK_HEADERS))


def get_asset(api: ApiClient, asset_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_video_asset(asset_id, CLERK_HEADERS))


def get_individual(api: ApiClient, individual_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_depicted_individual(individual_id, CLERK_HEADERS))


def get_hold(api: ApiClient, hold_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_litigation_hold(hold_id, CLERK_HEADERS))


def get_letter(api: ApiClient, letter_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_denial_letter(letter_id, CLERK_HEADERS))


def get_ledger_entry(api: ApiClient, entry_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_ledger_entry(entry_id, SUPERVISOR_HEADERS))


# ------------------------------------------------- tier 3: composite state
@pytest.fixture
def unit_staff(api: ApiClient) -> Dict[str, str]:
    """The four staff members almost every scenario needs, all at level 3.

    Two attorneys are registered because segregation of duties forbids the
    attorney who asserted a claim from adjudicating it.
    """
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Ray Counsel", "COUNSEL", 3)
    technician = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    return {
        "counsel_a_id": counsel_a["id"],
        "counsel_b_id": counsel_b["id"],
        "tech_id": technician["id"],
        "reviewer_id": reviewer["id"],
    }


def scoped_request_with_records(
    api: ApiClient,
    requester_id: str,
    asset_ids: List[str],
    incident_number: str = "INC-2026-0001",
    inclusion_status: str = "RESPONSIVE",
    **request_overrides: Any,
) -> Dict[str, Any]:
    """Intake, clarify scope, attach each recording and rule on each one.

    Returns the request id together with the record ids in attachment order.
    A request whose first record is ruled RESPONSIVE has reached
    EXEMPTION_REVIEW by the time this returns.
    """
    request = create_request(
        api,
        requester_id,
        subject_incident_number=incident_number,
        **request_overrides,
    )
    clarify_scope(api, request["id"])
    record_ids = []
    for asset_id in asset_ids:
        record = attach_record(api, request["id"], asset_id)
        if inclusion_status is not None:
            rule_inclusion(api, record["id"], inclusion_status)
        record_ids.append(record["id"])
    return {"request_id": request["id"], "record_ids": record_ids}


@pytest.fixture
def baseline_scenario(api: ApiClient, unit_staff: Dict[str, str]) -> Dict[str, Any]:
    """A scope-clarified request over one ten-minute ROUTINE recording.

    The single record is RESPONSIVE and carries no exemption claim, so its
    release posture is OPEN and the request sits at EXEMPTION_REVIEW.
    """
    requester = create_requester(api)
    asset = create_asset(api, incident_number="INC-2026-0001", duration_ms=600000)
    scoped = scoped_request_with_records(api, requester["id"], [asset["id"]])
    return {
        "requester_id": requester["id"],
        "asset_id": asset["id"],
        "request_id": scoped["request_id"],
        "record_id": scoped["record_ids"][0],
        **unit_staff,
    }


CLOCK_START = INITIAL_CLOCK
