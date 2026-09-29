"""Error conditions around billing lifecycle, participation guards, session
start timing, incident claims and identifier lookups.

Each test drives one rejection whose trigger condition the PRD states in prose,
and every scenario is arranged so that exactly one rule can fail.
"""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers import fixtures as scenarios
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import invoice_payload, participation_payload

ADMIN = TEST_USERS["operator_admin_headers"]


# ==========================================================================
# Private setup used by the participation-guard tests
# ==========================================================================
def _setup_employee_only_program() -> dict:
    """An ACTIVE contract, room, ready defibrillator, credentialed instructor and
    one ACTIVE offering whose eligible_member_classes is EMPLOYEE only, plus one
    ready EMPLOYEE member and one ready RETIREE member.

    Returns the scenario dict with `employee` and `retiree` added.
    """
    scenario = scenarios.setup_active_program(
        offering_overrides={
            "eligible_member_classes": ["EMPLOYEE"],
            "max_participants_per_session": 6,
            "participation_target": 8,
        }
    )
    scenario["employee"] = scenarios.setup_ready_member(
        scenario, full_name="Iris Okafor", employee_number="E-1001"
    )
    scenario["retiree"] = scenarios.setup_ready_member(
        scenario, member_class="RETIREE", full_name="Hal Brenner"
    )
    return scenario


def _file_and_review_unattributed_incident(scenario: dict) -> dict:
    """File a MODERATE / OTHER incident naming neither a member nor an asset and
    take it into review as the independent auditor."""
    incident = scenarios.file_incident(
        scenario,
        reported_by_staff_id=scenario["manager_id"],
        occurred_at_utc="2026-07-30T09:15:00Z",
        severity="MODERATE",
        cause_category="OTHER",
        narrative="Unattended spill reported by a passer-by; no member identified.",
    )
    scenarios.review_incident(
        scenario,
        incident["id"],
        headers=scenario["auditor_headers"],
        review_note="Opening review for the unattributed spill.",
    )
    return scenarios.read_incident(incident["id"])


# ==========================================================================
# One live billed invoice per contract period
# ==========================================================================
def test_second_august_draft_after_issue_rejected_with_period_conflict(api):
    """PRD §3.9: "A period may accumulate any number of `DRAFT` and `SUPERSEDED`
    invoices, but only one live billed one: if another invoice for the same
    contract and period is already `ISSUED`, `DISPUTED`, or `PAID`, drafting is
    refused with `ERR_INVOICE_PERIOD_CONFLICT`."

    PRD §3.9: "**Issuing** moves the invoice `DRAFT → ISSUED`, stamps
    `issued_at`, and adds `net_amount_cents` to the contract's
    `ytd_billed_cents`."

    Design: Corner/errors/invoice_period_conflict_rejected
    """
    scenario = scenarios.setup_active_contract()
    august = scenarios.draft_invoice(scenario, period_month="2026-08")
    scenarios.issue_invoice(august["id"])

    response = api.create_monthly_invoice(
        invoice_payload(
            scenario["contract_id"],
            scenarios.contract_version(scenario["contract_id"]),
            period_month="2026-08",
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVOICE_PERIOD_CONFLICT.value)

    untouched = scenarios.read_invoice(august["id"])
    assert untouched["status"] == "ISSUED", (
        f"expected the issued 2026-08 invoice to stay ISSUED, got "
        f"{untouched['status']} after the rejected re-draft"
    )
    items, meta = validate_paginated(
        api.list_monthly_invoices(ADMIN, params={"contract_id": scenario["contract_id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected 1 invoice on the contract, got {meta['total_count']}; the "
        f"rejected draft must not have been persisted"
    )


def test_september_draft_after_august_issue_succeeds(api):
    """PRD §3.9: "A period may accumulate any number of `DRAFT` and `SUPERSEDED`
    invoices, but only one live billed one: if another invoice for the same
    contract and period is already `ISSUED`, `DISPUTED`, or `PAID`, drafting is
    refused with `ERR_INVOICE_PERIOD_CONFLICT`."

    PRD §3.9: "A new invoice lands in `DRAFT` with `rebill_count` at 0 and
    `issued_at`, `disputed_at`, `paid_at`, and `dispute_reason` all null."

    Design: Corner/errors/invoice_period_conflict_rejected
    """
    scenario = scenarios.setup_active_contract()
    august = scenarios.draft_invoice(scenario, period_month="2026-08")
    scenarios.issue_invoice(august["id"])

    response = api.create_monthly_invoice(
        invoice_payload(
            scenario["contract_id"],
            scenarios.contract_version(scenario["contract_id"]),
            period_month="2026-09",
        ),
        ADMIN,
    )
    september = validate_success(response, 201)
    assert september["period_month"] == "2026-09", (
        f"expected the new draft to bill 2026-09, got {september['period_month']}"
    )
    assert september["status"] == "DRAFT", (
        f"expected a freshly drafted invoice in DRAFT, got {september['status']}"
    )

    items, meta = validate_paginated(
        api.list_monthly_invoices(ADMIN, params={"contract_id": scenario["contract_id"]})
    )
    assert meta["total_count"] == 2, (
        f"expected 2 invoices (2026-08 issued and 2026-09 drafted), got "
        f"{meta['total_count']}"
    )


# ==========================================================================
# A clean billing position is required at termination
# ==========================================================================
def test_terminate_with_draft_invoice_open_rejected(api):
    """PRD §3.1: "**Termination** is available from `ACTIVE` and from
    `SUSPENDED`, and it demands a clean billing position: if any invoice of the
    contract is in `DRAFT` or `DISPUTED` status, termination is refused with
    `ERR_OPEN_INVOICES`."

    Design: Corner/errors/open_invoices_block_terminate_rejected
    """
    scenario = scenarios.setup_active_contract()
    scenarios.draft_invoice(scenario, period_month="2026-08")

    response = api.service_status(
        scenario["contract_id"],
        {"action": "TERMINATE", "reason": "Client exited the program"},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_OPEN_INVOICES.value)

    contract = scenarios.read_contract(scenario["contract_id"])
    assert contract["status"] == "ACTIVE", (
        f"expected the contract to stay ACTIVE after the refused termination, "
        f"got {contract['status']}"
    )


def test_terminate_succeeds_once_open_invoice_is_paid(api):
    """PRD §3.1: "**Termination** is available from `ACTIVE` and from
    `SUSPENDED`, and it demands a clean billing position: if any invoice of the
    contract is in `DRAFT` or `DISPUTED` status, termination is refused with
    `ERR_OPEN_INVOICES`."

    PRD §3.1: "Terminating from `ACTIVE` runs the same four-link cascade as
    suspension — offerings paused, open sessions cancelled as
    `CANCELLED_CLIENT` with `cancel_reason` of `CLIENT_REQUEST`, assignments
    released, committed minutes returned and provisional attainment recomputed
    — and closes every room, and then goes further: every member of the
    contract moves `eligibility_status` to `TERMINATED` and `access_status` to
    `REVOKED`, every signed liability waiver of those members moves to
    `REVOKED` with the member's `current_waiver_id` cleared to null, and every
    staff member of the contract moves `duty_status` to `OFFBOARDED`."

    Design: Corner/errors/open_invoices_block_terminate_rejected
    """
    scenario = scenarios.setup_active_contract()
    invoice = scenarios.draft_invoice(scenario, period_month="2026-08")
    scenarios.issue_invoice(invoice["id"])
    validate_success(
        api.pay_invoice(
            invoice["id"], {"payment_reference": "ACH-90002"}, scenario["sponsor_headers"]
        )
    )
    paid = scenarios.read_invoice(invoice["id"])
    assert paid["status"] == "PAID", (
        f"expected the invoice to be PAID before terminating, got {paid['status']}"
    )

    validate_success(
        api.service_status(
            scenario["contract_id"],
            {"action": "TERMINATE", "reason": "Client exited the program"},
            ADMIN,
        )
    )

    contract = scenarios.read_contract(scenario["contract_id"])
    assert contract["status"] == "TERMINATED", (
        f"expected TERMINATED once no DRAFT or DISPUTED invoice remains, got "
        f"{contract['status']}"
    )
    manager = scenarios.read_staff(scenario["manager_id"])
    assert manager["duty_status"] == "OFFBOARDED", (
        f"expected the site manager to be OFFBOARDED by termination, got "
        f"{manager['duty_status']}"
    )


# ==========================================================================
# The check-in guards
# ==========================================================================
def test_repeat_check_in_for_same_member_and_session_rejected(api):
    """PRD §3.7: "And the member must not already hold a `COUNTED` record for
    that same session, a repeat being refused with `ERR_DUPLICATE_CHECK_IN`; a
    previously voided record does not block a replacement check-in."

    Design: Corner/errors/participation_guard_errors_rejected
    """
    scenario = _setup_employee_only_program()
    member_id = scenario["employee"]["id"]
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
    )
    scenarios.staff_session(scenario, session["id"])
    scenarios.start_session(scenario, session["id"], clock_at="2026-08-05T12:00:00Z")
    scenarios.check_in(scenario, member_id, session["id"])

    response = api.create_participation_record(
        participation_payload(member_id, session["id"]), scenario["instructor_headers"]
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_CHECK_IN.value)

    items, meta = validate_paginated(
        api.list_participation_records(ADMIN, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected the single original check-in to survive, got "
        f"{meta['total_count']} participation records on the session"
    )
    refreshed = scenarios.read_session(session["id"])
    assert refreshed["actual_attendance"] == 1, (
        f"expected actual_attendance 1 after the refused repeat, got "
        f"{refreshed['actual_attendance']}"
    )


def test_retiree_check_in_on_employee_only_offering_rejected(api):
    """PRD §3.7: "The member's `member_class` must appear in the offering's
    `eligible_member_classes` list — some programmes are employee-only while
    others admit dependents and retirees — and a mismatch is refused with
    `ERR_MEMBER_CLASS_NOT_ELIGIBLE`."

    Design: Corner/errors/participation_guard_errors_rejected
    """
    scenario = _setup_employee_only_program()
    retiree_id = scenario["retiree"]["id"]
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
    )
    scenarios.staff_session(scenario, session["id"])
    scenarios.start_session(scenario, session["id"], clock_at="2026-08-05T12:00:00Z")

    response = api.create_participation_record(
        participation_payload(retiree_id, session["id"]), scenario["instructor_headers"]
    )
    validate_error(response, ApiErrorId.ERR_MEMBER_CLASS_NOT_ELIGIBLE.value)

    items, meta = validate_paginated(
        api.list_participation_records(ADMIN, params={"member_id": retiree_id})
    )
    assert meta["total_count"] == 0, (
        f"expected no participation record for the ineligible member class, got "
        f"{meta['total_count']}"
    )


def test_check_in_against_scheduled_session_rejected(api):
    """PRD §3.7: "The session must be in `IN_PROGRESS`; a check-in against a
    session in any other status, including one that has already been completed,
    is refused with `ERR_SESSION_NOT_IN_PROGRESS`."

    Design: Corner/errors/participation_guard_errors_rejected
    """
    scenario = _setup_employee_only_program()
    member_id = scenario["employee"]["id"]
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-06T12:00:00Z",
        scheduled_end_utc="2026-08-06T12:55:00Z",
        forecast_attendance=2,
    )
    assert scenarios.read_session(session["id"])["status"] == "SCHEDULED", (
        "the session under test must still be SCHEDULED"
    )

    response = api.create_participation_record(
        participation_payload(member_id, session["id"]), scenario["instructor_headers"]
    )
    validate_error(response, ApiErrorId.ERR_SESSION_NOT_IN_PROGRESS.value)

    items, meta = validate_paginated(
        api.list_participation_records(ADMIN, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected no participation record against a session that never started, "
        f"got {meta['total_count']}"
    )


# ==========================================================================
# The session-start grace window
# ==========================================================================
def test_session_start_one_hour_early_rejected(api):
    """PRD §3.5: "**Starting** moves the session `STAFFED → IN_PROGRESS` and
    stamps `started_at`, and it is gated four ways: the session must be in
    `STAFFED` (else `ERR_SESSION_NOT_STAFFED`), the contract must be `ACTIVE`
    (else `ERR_CONTRACT_NOT_ACTIVE`), the room must be `OPEN` (else
    `ERR_ROOM_NOT_OPEN`), the site must have at least one `READY` defibrillator
    (else `ERR_AED_NOT_READY`), and the clock must have reached at most 15
    minutes before `scheduled_start_utc` — a start attempted earlier than that
    grace window is refused with `ERR_SESSION_START_TOO_EARLY`."

    Design: Corner/errors/session_start_too_early_rejected
    """
    scenario, session, assignment = scenarios.setup_staffed_session(
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
    )
    scenarios.set_clock("2026-08-05T11:00:00Z")

    response = api.session_status_change(
        session["id"], {"action": "START"}, scenario["manager_headers"]
    )
    validate_error(response, ApiErrorId.ERR_SESSION_START_TOO_EARLY.value)

    refreshed = scenarios.read_session(session["id"])
    assert refreshed["status"] == "STAFFED", (
        f"expected the session to stay STAFFED after the refused start, got "
        f"{refreshed['status']}"
    )
    assert refreshed["started_at"] is None, (
        f"expected started_at to stay null after the refused start, got "
        f"{refreshed['started_at']!r}"
    )
    lead = scenarios.read_assignment(assignment["id"])
    assert lead["status"] == "CONFIRMED", (
        f"expected the lead assignment to stay CONFIRMED, got {lead['status']}"
    )


def test_session_start_exactly_fifteen_minutes_early_allowed(api):
    """PRD §3.5: "**Starting** moves the session `STAFFED → IN_PROGRESS` and
    stamps `started_at`, and it is gated four ways: the session must be in
    `STAFFED` (else `ERR_SESSION_NOT_STAFFED`), the contract must be `ACTIVE`
    (else `ERR_CONTRACT_NOT_ACTIVE`), the room must be `OPEN` (else
    `ERR_ROOM_NOT_OPEN`), the site must have at least one `READY` defibrillator
    (else `ERR_AED_NOT_READY`), and the clock must have reached at most 15
    minutes before `scheduled_start_utc` — a start attempted earlier than that
    grace window is refused with `ERR_SESSION_START_TOO_EARLY`."

    Design: Corner/errors/session_start_too_early_rejected
    """
    scenario, session, assignment = scenarios.setup_staffed_session(
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
    )
    scenarios.set_clock("2026-08-05T11:45:00Z")

    started = validate_success(
        api.session_status_change(
            session["id"], {"action": "START"}, scenario["manager_headers"]
        )
    )
    assert started["status"] == "IN_PROGRESS", (
        f"expected IN_PROGRESS when starting exactly 15 minutes early, got "
        f"{started['status']}"
    )
    assert started["started_at"] is not None and started["started_at"].startswith(
        "2026-08-05T11:45:00"
    ), (
        f"expected started_at stamped at the 11:45Z logical instant, got "
        f"{started['started_at']!r}"
    )


# ==========================================================================
# Voiding an identifier that resolves to nothing
# ==========================================================================
def test_void_unknown_participation_record_returns_participation_not_found(api):
    """PRD §3.7: "Records can be listed filtered by `member_id`, by
    `session_id`, by `status`, and by a check-in window expressed as
    `checked_in_after` and `checked_in_before`; a record identifier that
    resolves to nothing yields `ERR_PARTICIPATION_NOT_FOUND`, and a member
    identifier that resolves to nothing yields `ERR_MEMBER_NOT_FOUND`."

    Design: Corner/errors/void_unknown_participation_record_not_found
    """
    scenario = scenarios.setup_active_contract()

    response = api.void_participation_record(
        NON_EXISTENT_UUID,
        {"void_reason": "Recorded against the wrong member"},
        scenario["manager_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PARTICIPATION_NOT_FOUND.value)

    items, meta = validate_paginated(api.list_participation_records(ADMIN))
    assert meta["total_count"] == 0, (
        f"expected the refused void to create nothing, got {meta['total_count']} "
        f"participation records"
    )


# ==========================================================================
# A liability claim needs a subject member
# ==========================================================================
def test_file_claim_without_subject_member_rejected(api):
    """PRD §3.8: "A report with no `member_id`, or one whose subject member has
    never signed anything, is refused with `ERR_CLAIM_SUBJECT_REQUIRED`."

    Design: Corner/errors/claim_subject_required_on_file_claim_rejected
    """
    scenario = scenarios.setup_active_contract()
    incident = _file_and_review_unattributed_incident(scenario)
    assert incident["status"] == "UNDER_REVIEW", (
        f"the incident must be UNDER_REVIEW before filing a claim, got "
        f"{incident['status']}"
    )
    assert incident["member_id"] is None, (
        f"the incident under test must name no member, got {incident['member_id']!r}"
    )

    response = api.file_claim(
        incident["id"], {"claim_reference": "CLM-0002"}, scenario["auditor_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_SUBJECT_REQUIRED.value)

    refreshed = scenarios.read_incident(incident["id"])
    assert refreshed["status"] == "UNDER_REVIEW", (
        f"expected the incident to stay UNDER_REVIEW after the refused claim, got "
        f"{refreshed['status']}"
    )
    assert refreshed["claim_reference"] is None, (
        f"expected claim_reference to stay null after the refused claim, got "
        f"{refreshed['claim_reference']!r}"
    )


def test_reviewed_incident_without_subject_can_close_without_claim(api):
    """PRD §3.8: "**Closing without a claim** moves it `UNDER_REVIEW →
    CLOSED_NO_CLAIM` and stores the mandatory `closure_note`, leaving
    `claim_reference` null forever."

    Design: Corner/errors/claim_subject_required_on_file_claim_rejected
    """
    scenario = scenarios.setup_active_contract()
    incident = _file_and_review_unattributed_incident(scenario)

    closed = validate_success(
        api.close_incident(
            incident["id"],
            {"closure_note": "No identifiable subject; closed without a claim."},
            scenario["auditor_headers"],
        )
    )
    assert closed["status"] == "CLOSED_NO_CLAIM", (
        f"expected CLOSED_NO_CLAIM for an incident closed without a claim, got "
        f"{closed['status']}"
    )
    assert closed["closure_note"] == "No identifiable subject; closed without a claim.", (
        f"expected the supplied closure_note to be stored, got "
        f"{closed['closure_note']!r}"
    )
    assert closed["claim_reference"] is None, (
        f"expected claim_reference to stay null forever, got "
        f"{closed['claim_reference']!r}"
    )


# ==========================================================================
# Existence failures name the entity that failed to resolve
# ==========================================================================
_UNKNOWN_ID_LOOKUPS = [
    ("staff_credential", "get_staff_credential", ApiErrorId.ERR_CREDENTIAL_NOT_FOUND),
    ("facility_asset", "get_facility_asset", ApiErrorId.ERR_ASSET_NOT_FOUND),
    ("program_session", "get_program_session", ApiErrorId.ERR_SESSION_NOT_FOUND),
    ("staff_assignment", "get_staff_assignment", ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
    ("member", "get_member", ApiErrorId.ERR_MEMBER_NOT_FOUND),
    ("liability_waiver", "get_liability_waiver", ApiErrorId.ERR_WAIVER_NOT_FOUND),
    ("incident_report", "get_incident_report", ApiErrorId.ERR_INCIDENT_NOT_FOUND),
    ("monthly_invoice", "get_monthly_invoice", ApiErrorId.ERR_INVOICE_NOT_FOUND),
]


@pytest.mark.parametrize(
    "accessor, expected_error_id",
    [(accessor, error_id) for _, accessor, error_id in _UNKNOWN_ID_LOOKUPS],
    ids=[label for label, _, _ in _UNKNOWN_ID_LOOKUPS],
)
def test_unknown_identifier_returns_entity_specific_not_found(
    api, clock, compliance_auditor_headers, accessor, expected_error_id
):
    """PRD §2.6: "Existence failures always name the entity type that failed to
    resolve, whether the identifier came from the URL or from the request body:
    `ERR_CONTRACT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`,
    `ERR_ROOM_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
    `ERR_WAIVER_NOT_FOUND`, `ERR_PARTICIPATION_NOT_FOUND`,
    `ERR_INCIDENT_NOT_FOUND`, and `ERR_INVOICE_NOT_FOUND` — all HTTP 404."

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/unknown_ids_return_entity_specific_not_found
    """
    response = getattr(api, accessor)(NON_EXISTENT_UUID, compliance_auditor_headers)
    validate_error(response, expected_error_id.value)

    body = response.json()
    assert body["response_type"] == "error", (
        f"expected response_type 'error', got {body['response_type']!r}"
    )
    assert body["meta"].get("api_request_id"), (
        f"expected a meta.api_request_id on the 404 envelope, got "
        f"{body['meta'].get('api_request_id')!r}"
    )
    assert body["data"]["message"].strip(), (
        "expected a non-empty human-readable message on the 404 envelope"
    )
