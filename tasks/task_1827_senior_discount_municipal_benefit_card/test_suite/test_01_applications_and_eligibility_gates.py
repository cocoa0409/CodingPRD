"""Application submission: initial state, request shape, and the age/income
eligibility gates evaluated at submission (PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    assert_benefit_application,
    create_application_payload,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_success,
)


def test_application_creation_sets_initial_state(api, applicant_headers):
    """PRD §3.1: "Every new application enters `SUBMITTED` status, with
    `reviewed_by_user_id`, `info_request_reason`, `denial_reason`, and
    `decided_by_user_id` all empty until the corresponding workflow events
    occur."
    PRD §2.5: "`id` (string): a unique, server-generated identifier formatted
    as a UUID, with no type prefix."

    Design: Corner/entities/application_creation_sets_initial_state
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.create_application(
        create_application_payload(applicant_full_name="Init State",
                                   residency_address="20 Start St"),
        applicant_headers)
    app = validate_success(res, 201)
    assert_benefit_application(app)
    assert app["status"] == "SUBMITTED", "a new application enters SUBMITTED"
    assert app["reviewed_by_user_id"] is None
    assert app["info_request_reason"] is None
    assert app["denial_reason"] is None
    assert app["decided_by_user_id"] is None
    assert app["cardholder_id"] is None, (
        "for an initial application the cardholder linkage is populated only "
        "when and if the application is approved")


def test_application_missing_date_of_birth_rejected(api, applicant_headers):
    """PRD §3.1: "Both gates apply identically to `INITIAL` and
    `RECERTIFICATION` submissions, and malformed payloads — missing fields,
    wrong types, negative income, an invalid `kind` — are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400) before any gate runs."

    Design: Corner/entities/application_missing_required_field_returns_invalid_request
    """
    set_clock("2026-08-01T00:00:00Z")
    payload = create_application_payload(applicant_full_name="No Dob",
                                         residency_address="21 Gap St")
    del payload["date_of_birth"]
    res = api.create_application(payload, applicant_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_application_invalid_kind_rejected(api, applicant_headers):
    """PRD §3.1: "Both gates apply identically to `INITIAL` and
    `RECERTIFICATION` submissions, and malformed payloads — missing fields,
    wrong types, negative income, an invalid `kind` — are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400) before any gate runs."

    Design: Corner/entities/application_invalid_enum_kind_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    payload = create_application_payload(kind="RENEWAL",
                                         applicant_full_name="Bad Enum",
                                         residency_address="22 Enum Ave")
    res = api.create_application(payload, applicant_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_client_supplied_system_fields_ignored(api, applicant_headers):
    """PRD §2.5: "`id` (string): a unique, server-generated identifier
    formatted as a UUID, with no type prefix."
    PRD §2.5: "`version` (integer): a system-managed integer that increments
    with every modification to the resource and serves as the basis for
    optimistic concurrency control."
    A client-injected id is not a server-generated UUID and a client-injected
    version is not system-managed, so neither may be honored.

    Design: Corner/entities/system_fields_client_input_ignored
    """
    set_clock("2026-08-01T00:00:00Z")
    payload = create_application_payload(applicant_full_name="Inject Fields",
                                         residency_address="25 Forge St")
    payload["id"] = "client-injected-id"
    payload["version"] = 99
    res = api.create_application(payload, applicant_headers)
    app = validate_success(res, 201)
    assert app["id"] != "client-injected-id", (
        "the server mints the id; the client-supplied value must not be honored")
    assert is_valid_uuid(app["id"]), "id must be a server-generated UUID"
    assert app["version"] != 99, (
        "version is system-managed; the client-supplied 99 must not be honored")


def test_income_exactly_at_limit_accepted(api, applicant_headers):
    """PRD §3.1: "The income gate requires `annual_income_cents` to be at or
    below the program limit of $24,000 per year; an income that exceeds the
    limit by even one cent is rejected with `ERR_ELIGIBILITY_INCOME_EXCEEDED`
    (HTTP 422), while an income exactly at the limit qualifies."

    Design: Corner/calculations/income_limit_exact_boundary
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.create_application(
        create_application_payload(applicant_full_name="Exact Income",
                                   annual_income_cents=2400000,
                                   residency_address="38 Edge St"),
        applicant_headers)
    app = validate_success(res, 201)
    assert app["status"] == "SUBMITTED", (
        "income of exactly $24,000 (2400000 cents) qualifies")


def test_income_one_cent_over_limit_rejected(api, applicant_headers):
    """PRD §3.1: "The income gate requires `annual_income_cents` to be at or
    below the program limit of $24,000 per year; an income that exceeds the
    limit by even one cent is rejected with `ERR_ELIGIBILITY_INCOME_EXCEEDED`
    (HTTP 422), while an income exactly at the limit qualifies."

    Design: Corner/calculations/income_limit_exact_boundary
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.create_application(
        create_application_payload(applicant_full_name="Over Income",
                                   annual_income_cents=2400001,
                                   residency_address="38 Edge St"),
        applicant_headers)
    validate_error(res, ApiErrorId.ERR_ELIGIBILITY_INCOME_EXCEEDED)


def test_age_exactly_65_accepted(api, applicant_headers):
    """PRD §3.1: "The age gate computes the applicant's age in whole years
    between `date_of_birth` and the clock date, incrementing on the birthday
    itself — a person born on 1961-08-01 is exactly sixty-five on 2026-08-01 —
    and requires the result to be at least sixty-five; a younger applicant is
    rejected with `ERR_ELIGIBILITY_AGE_NOT_MET` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/age_exactly_65_boundary
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.create_application(
        create_application_payload(applicant_full_name="Sixty Five",
                                   date_of_birth="1961-08-01",
                                   annual_income_cents=1000000,
                                   residency_address="12 Boundary Ln"),
        applicant_headers)
    app = validate_success(res, 201)
    assert app["status"] == "SUBMITTED", (
        "age == 65 exactly satisfies the at-least-sixty-five gate (inclusive)")


def test_age_one_day_short_rejected(api, applicant_headers):
    """PRD §3.1: "The age gate computes the applicant's age in whole years
    between `date_of_birth` and the clock date, incrementing on the birthday
    itself — a person born on 1961-08-01 is exactly sixty-five on 2026-08-01 —
    and requires the result to be at least sixty-five; a younger applicant is
    rejected with `ERR_ELIGIBILITY_AGE_NOT_MET` (HTTP 422)."
    Born 1961-08-02, the applicant is 64 years and 364 days at the 2026-08-01
    clock — one day short of the boundary.

    Design: Difficulty/boundary_precision_check/age_exactly_65_boundary
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.create_application(
        create_application_payload(applicant_full_name="One Day Young",
                                   date_of_birth="1961-08-02",
                                   annual_income_cents=1000000,
                                   residency_address="12 Boundary Ln"),
        applicant_headers)
    validate_error(res, ApiErrorId.ERR_ELIGIBILITY_AGE_NOT_MET)
