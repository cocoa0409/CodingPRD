"""Intake: client & report creation, validation, listing, and the response
deadline SLA. Translations of SCAFFOLD_CORNER_DESIGN queue-B instances."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_report_payload, create_account_payload,
    assert_report, assert_account,
)
from test_helpers import fixtures as fx

INTAKE = TEST_USERS["intake_worker_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def test_report_creation_returns_201_with_fields(api):
    """PRD §3.1: "A freshly filed report has its `status` set to `RECEIVED`".
    PRD §2.4: "The `version` field is an integer that starts at 1 on creation
    and increments by one on every mutation of the resource."

    Design: Corner/entities/report_creation_returns_201_with_fields
    """
    client = fx.new_client()
    resp = api.create_report(
        create_report_payload(client["id"], reporter_type="MANDATORY",
                              allegation_types=["NEGLECT"], priority="ROUTINE", narrative="n"),
        INTAKE,
    )
    data = validate_success(resp, expected_status=201)
    assert_report(data)
    assert data["status"] == "RECEIVED"
    assert data["client_id"] == client["id"]
    assert data["version"] == 1


def test_report_not_found_returns_404(api):
    """PRD §2.6: "Each entity type has its own not-found error:
    `ERR_REPORT_NOT_FOUND` ... each HTTP 404."

    Design: Corner/entities/report_not_found_returns_404
    """
    resp = api.get_report(NON_EXISTENT_UUID, INTAKE)
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FOUND.value)


def test_report_missing_required_narrative_returns_validation(api):
    """PRD §2.6: "a write whose body omits a required field or supplies a value
    of the wrong JSON type is rejected with `ERR_VALIDATION` (400)."

    Design: Corner/entities/report_missing_required_narrative_returns_validation
    """
    client = fx.new_client()
    payload = {
        "client_id": client["id"],
        "reporter_type": "MANDATORY",
        "allegation_types": ["NEGLECT"],
        "priority": "ROUTINE",
        # narrative omitted
    }
    resp = api.create_report(payload, INTAKE)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_invalid_enum_priority_returns_422(api):
    """PRD §2.6: "an enum-typed field carrying a value outside its declared set
    — this includes `reporter_type`, `priority`, `decision`, `disposition`,
    `assessment_type`, and `determination` — or an `allegation_types` array
    that is empty, is rejected with `ERR_INVALID_ENUM` (422)."

    Design: Corner/entities/invalid_enum_priority_returns_422
    """
    client = fx.new_client()
    resp = api.create_report(
        create_report_payload(client["id"], priority="URGENT", allegation_types=["NEGLECT"], narrative="n"),
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_reports_list_paginated_envelope(api):
    """PRD §2.3: "Each list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope, where `total_count` is
    the number of matching resources before pagination and `has_more` indicates
    whether any matching resources remain beyond the returned page."

    Design: Corner/entities/reports_list_paginated_envelope
    """
    client = fx.new_client()
    fx.new_report(client["id"], reporter_type="MANDATORY", allegation_types=["NEGLECT"], narrative="a")
    fx.new_report(client["id"], reporter_type="VOLUNTARY", allegation_types=["SELF_NEGLECT"], narrative="b")
    resp = api.list_reports(SUPERVISOR, params={"client_id": client["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "expected has_more True with limit=1 over 2 items"
    assert len(data) == 1, f"expected 1 item on the page, got {len(data)}"


def test_account_available_balance_computed_on_create(api):
    """PRD §3.5: "A new account is `ACTIVE`, its `available_balance_cents` equal
    to its `total_balance_cents`, and its `frozen_amount_cents`,
    `flagged_amount_cents`, and `restitution_cents` all zero."

    Design: Corner/entities/account_available_balance_computed_on_create
    """
    client = fx.new_client()
    resp = api.create_account(create_account_payload(client["id"], total_balance_cents=750000), INTAKE)
    data = validate_success(resp, expected_status=201)
    assert_account(data)
    assert data["available_balance_cents"] == 750000
    assert data["frozen_amount_cents"] == 0
    assert data["status"] == "ACTIVE"


def test_response_deadline_emergency_24h(api):
    """PRD §3.1: "the system computes `response_due_at` as the report's
    `created_at` plus a fixed service-level allowance: 24 hours (one day) for an
    `EMERGENCY` report".

    Design: Corner/calculations/response_deadline_emergency_24h
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    client = fx.new_client()
    resp = api.create_report(
        create_report_payload(client["id"], allegation_types=["PHYSICAL_ABUSE"],
                              priority="EMERGENCY", narrative="urgent"),
        INTAKE,
    )
    data = validate_success(resp, expected_status=201)
    assert data["response_due_at"] == "2026-06-02T00:00:00.000Z", (
        f"EMERGENCY report at 2026-06-01T00:00:00Z should be due +24h; got {data['response_due_at']}"
    )
