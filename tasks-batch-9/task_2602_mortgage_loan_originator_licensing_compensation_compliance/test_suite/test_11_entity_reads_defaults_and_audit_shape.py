"""Server-stamped fields, declared input shapes, and the shape of the audit trail.

Every test builds its own preconditions: the runner restarts the server with an
empty store before each test, and the logical compliance clock reads
2026-08-01T00:00:00Z until a test moves it.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_audit_event, assert_compensation_plan
from test_helpers.test_users import (
    analyst_headers,
    designer_headers,
    examiner_headers,
    make_originator_headers,
    officer_headers,
)

DRAFTING_DESIGNER_USER_ID = "user-compensation-designer-09"


def test_compensation_plan_stamps_drafted_by_user_id_from_header(api):
    """PRD §3.3: "A new plan starts in `DRAFT` with `prohibited_variable_count` at `0`,
    `approved_by_user_id` null, and its assignment fields `assigned_originator_id`,
    `assignment_effective_from` and `assignment_effective_to` all null. The system stamps
    `drafted_by_user_id` with the drafting designer's `X-User-ID`; that value is the anchor for
    the segregation-of-duties check at approval time."
    PRD §3.3: "`salary_cents_per_period` is the fixed, non-loan-dependent salary component paid
    per reporting period, defaulting to `0` and never negative; it is recorded for examination
    purposes and does not enter the per-loan commission arithmetic at all."
    PRD §3.3: "`volume_tier_enabled`, false by default, decides whether the volume-tier
    basis-point adder described in §3.5 contributes anything — when it is false the adder is
    fixed at zero."
    PRD §3.3: "`concession_absorption_enabled`, also false by default, decides whether an
    approved pricing concession reduces the originator's commission — when it is false a
    concession never touches commission and the exception's `comp_impact_cents` stays at `0`
    permanently."

    Design: Corner/entities/compensation_plan_stamps_drafted_by_user_id_from_header
    """
    response = api.create_compensation_plan(
        {
            "plan_name": "Retail Base 2026",
            "base_basis_points": 105,
            "min_fee_cents": 0,
            "max_fee_cents": 5_000_000,
        },
        designer_headers(DRAFTING_DESIGNER_USER_ID),
    )
    plan = validate_success(response, 201)

    assert_compensation_plan(plan)
    assert plan["drafted_by_user_id"] == DRAFTING_DESIGNER_USER_ID, (
        "drafted_by_user_id is stamped from the drafting designer's X-User-ID: "
        f"{plan['drafted_by_user_id']}"
    )
    assert plan["approved_by_user_id"] is None
    assert plan["status"] == "DRAFT"
    assert plan["prohibited_variable_count"] == 0
    assert plan["assigned_originator_id"] is None
    assert plan["assignment_effective_from"] is None
    assert plan["assignment_effective_to"] is None
    assert plan["salary_cents_per_period"] == 0
    assert plan["volume_tier_enabled"] is False
    assert plan["concession_absorption_enabled"] is False
    assert plan["version"] == 1
    assert plan["plan_name"] == "Retail Base 2026"
    assert plan["base_basis_points"] == 105


def test_draft_advertisement_with_unknown_medium_rejected(api):
    """PRD §3.8: "An `Originator` drafts an advertisement by supplying its own `originator_id`,
    the `medium` it will be distributed through — one of `WEB`, `PRINT`, `SOCIAL`,
    `DIRECT_MAIL` or `RADIO` — the full `content_text` of the copy, between ten and four
    thousand characters, and the `target_state_codes` it will be distributed in, a required
    list of between one and ten uppercase two-letter codes."
    PRD §2.9: "The request body conforms to the endpoint's declared input shape: required
    fields present, types correct, enum members recognised, numeric ranges honoured, ISO 8601
    timestamps parseable, array element formats correct — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_advertisement_with_unknown_medium_enum_rejected
    """
    originator = fixtures.create_originator(api, nmls_unique_id="2200001")

    response = api.create_advertisement(
        {
            "originator_id": originator["id"],
            "medium": "BILLBOARD",
            "content_text": "Refinance with Avery Lane today and lock a great rate.",
            "target_state_codes": ["CA"],
        },
        make_originator_headers(originator["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, meta = validate_paginated(
        api.list_advertisements(officer_headers(), params={"originator_id": originator["id"]})
    )
    assert meta["total_count"] == 0, f"the rejected draft must persist no advertisement: {rows}"


def test_file_license_with_expiration_before_issue_date_rejected(api):
    """PRD §3.1: "`expiration_date` must fall strictly after `issue_date`, and
    `renewal_window_opens_at` must fall strictly before `expiration_date`."
    PRD §2.9: "The request body conforms to the endpoint's declared input shape: required
    fields present, types correct, enum members recognised, numeric ranges honoured, ISO 8601
    timestamps parseable, array element formats correct — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/license_expiration_before_issue_date_rejected
    """
    originator = fixtures.create_originator(api, nmls_unique_id="2200001")

    response = api.create_license_registration(
        {
            "originator_id": originator["id"],
            "state_code": "CA",
            "license_number": "CA-DFPI-70001",
            "issue_date": "2026-01-02T00:00:00Z",
            "expiration_date": "2025-12-01T00:00:00Z",
            "renewal_window_opens_at": "2025-11-01T00:00:00Z",
            "ce_reporting_year": 2026,
        },
        analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, meta = validate_paginated(
        api.list_license_registrations(
            analyst_headers(), params={"originator_id": originator["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"an already-lapsed licence must not be created: {rows}"
    )


def test_license_activation_appends_one_append_only_audit_entry(api):
    """PRD §2.5: "An `AuditEvent` is append-only and is never modified after it is written, so
    an audit entry carries only `id` and `created_at`: it has **no** `updated_at` and **no**
    `version` field at all. Its ordering key is `sequence_no`, a strictly increasing counter
    that starts at `1` for the first entry the system ever writes and advances by one for each
    subsequent entry, globally across all entity types and all requests."
    PRD §3.1: "On activation the system stamps `authority_effective_at` from the logical clock,
    recomputes the originator's `authorized_state_codes`, and appends an audit entry of type
    `LICENSE_STATUS_CHANGED` with `subject_type` `LicenseRegistration`."
    PRD §2.1: "Audit entries record the role that caused them in `actor_role`."
    PRD §2.1: "The server records it where a workflow demands an accountability trail — as
    `drafted_by_user_id` and `approved_by_user_id` on a compensation plan, as
    `decided_by_user_id` and `second_decided_by_user_id` on a pricing exception, as
    `reviewed_by_user_id` on an advertisement, as `finding_by_user_id` on an investigation, and
    as `actor_user_id` on every audit entry — but it never compares that value to any entity's
    `id`."

    Design: Corner/entities/audit_events_are_append_only_with_no_version_field
    """
    originator = fixtures.create_originator(api, nmls_unique_id="2200001")
    licence = fixtures.file_license(
        api,
        originator["id"],
        state_code="CA",
        license_number="CA-DFPI-70001",
        issue_date="2026-01-02T00:00:00Z",
        expiration_date="2027-01-31T00:00:00Z",
        renewal_window_opens_at="2026-11-01T00:00:00Z",
        ce_reporting_year=2026,
    )
    activating_analyst = "user-licensing-analyst-77"
    validate_success(
        api.activate_license_registration(licence["id"], analyst_headers(activating_analyst))
    )

    events, meta = validate_paginated(
        api.list_audit_events(
            examiner_headers(),
            params={
                "subject_type": "LicenseRegistration",
                "event_type": "LICENSE_STATUS_CHANGED",
            },
        )
    )

    assert meta["total_count"] == 1, (
        f"activation appends exactly one LICENSE_STATUS_CHANGED entry: {events}"
    )
    entry = events[0]
    assert_audit_event(entry)
    assert entry["event_type"] == "LICENSE_STATUS_CHANGED"
    assert entry["subject_type"] == "LicenseRegistration"
    assert entry["subject_ref"] == licence["id"]
    assert entry["actor_role"] == "LicensingAnalyst"
    assert entry["actor_user_id"] == activating_analyst
    assert entry["sequence_no"] == 1, (
        "the activation entry is the first entry the system ever writes, so its "
        f"sequence_no is 1: {entry['sequence_no']}"
    )
    assert "updated_at" not in entry, "an audit entry carries no updated_at at all"
    assert "version" not in entry, "an audit entry carries no version at all"


def test_declare_variable_under_unknown_plan_reports_the_missing_plan(api):
    """PRD §2.10: "Path identifiers are resolved strictly **left to right**, and the first
    identifier that does not resolve produces `ERR_RESOURCE_NOT_FOUND` (HTTP 404). A
    pay-variable declaration against a plan id that does not exist therefore reports the
    missing plan, and the body is never examined."

    Design: Corner/entities/create_compensation_variable_under_unknown_plan_returns_not_found
    """
    plan = fixtures.draft_plan(
        api,
        plan_name="Retail Base 2026",
        base_basis_points=105,
        min_fee_cents=0,
        max_fee_cents=5_000_000,
    )

    response = api.create_compensation_variable(
        NON_EXISTENT_UUID,
        {
            "variable_type": "HOURS_WORKED",
            "weight_pct": 100,
            "justification_text": (
                "Hours worked on the file is a permissible compensation variable."
            ),
        },
        designer_headers(),
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    variables, meta = validate_paginated(
        api.list_compensation_variables(plan["id"], officer_headers())
    )
    assert meta["total_count"] == 0, (
        f"nothing may be attached to the real plan by the failed call: {variables}"
    )


def test_file_license_with_unknown_originator_id_rejected(api):
    """PRD §2.9: "Every foreign-key id in the request body — `originator_id`, `ce_course_id`,
    `compensation_plan_id`, `loan_application_id` — resolves to an existing row, otherwise
    `ERR_REFERENCED_RESOURCE_NOT_FOUND`. This applies when filing a licence, filing a CE
    credit, taking an application, drafting an advertisement, recording an examination inquiry,
    assigning a compensation plan, and opening an investigation manually."

    Design: Corner/entities/create_license_registration_with_unknown_originator_id_rejected
    """
    response = api.create_license_registration(
        {
            "originator_id": NON_EXISTENT_UUID,
            "state_code": "CA",
            "license_number": "CA-DFPI-70001",
            "issue_date": "2026-01-02T00:00:00Z",
            "expiration_date": "2027-01-31T00:00:00Z",
            "renewal_window_opens_at": "2026-11-01T00:00:00Z",
            "ce_reporting_year": 2026,
        },
        analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value)

    rows, meta = validate_paginated(api.list_license_registrations(analyst_headers()))
    assert meta["total_count"] == 0, f"no licence may be filed against a missing originator: {rows}"
