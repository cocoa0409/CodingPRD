"""Standing up a dependent eligibility audit.

The workflow this module exercises is the front of the audit: a benefits
administrator loads the subscriber census, enrols each household's dependents
against the published monthly cost schedule, and creates the audit program whose
cadence parameters govern every deadline that follows. The reads and the
malformed requests that guard those writes are covered alongside them.
"""
from __future__ import annotations

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_evidence_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_mutable_common_fields,
    assert_page_meta,
    assert_program_starts_at_zero,
    ids_of,
)
from test_helpers.constants import MONTHLY_COST_CENTS
from test_helpers.fixtures import ANNOUNCE_INSTANT, ORIGIN_INSTANT, announced_wave
from test_helpers.test_users import ANALYST, PROGRAM_ADMIN, employee_headers


def _case_for(b, program_id: str, employee_id: str):
    """The audit case a program holds for one subscriber."""
    matches = [row for row in b.cases(program_id) if row["employee_id"] == employee_id]
    assert matches, f"no audit case for employee {employee_id}"
    return matches[0]


def test_registering_an_employee_returns_the_created_row_with_no_enrolled_dependents(
    b, client, clock
):
    """A newly registered employee starts with `enrolled_dependent_count` at zero
    ... Endpoints that bring a brand-new resource into existence respond with HTTP
    201

    Design: Corner/entities/corner_create_employee_returns_201_with_success_envelope_and_zero_dependent_count
    """
    payload = f.employee_payload(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )

    response = client.create_employee(payload, PROGRAM_ADMIN)
    employee = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object", body
    assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]

    assert_mutable_common_fields(employee)
    assert_fields(
        employee,
        full_name=payload["full_name"],
        work_email=payload["work_email"],
        coverage_tier="EMPLOYEE_SPOUSE",
        employer_monthly_premium_cents=121000,
        hire_date=payload["hire_date"],
        enrolled_dependent_count=0,
        version=1,
    )
    assert_instant_equals(employee["created_at"], ORIGIN_INSTANT)


def test_reading_a_dependent_reports_the_server_stamped_enrollment_date_and_schedule_cost(
    b, client
):
    """The dependent's `enrolled_at` is likewise server-controlled: it is the
    calendar-date portion of the logical clock at the moment of creation ... the
    dependent is simply created with `coverage_status` `ENROLLED`,
    `poe_program_id` null, and `poe_deadline_at` null

    Design: Corner/entities/corner_get_dependent_returns_stored_row_with_system_and_computed_fields
    """
    b.set_clock("2026-08-05T00:00:00Z")
    employee = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    created = b.dependent(employee["id"], "SPOUSE")

    dependent = validate_success(client.get_dependent(created["id"], PROGRAM_ADMIN))

    assert_mutable_common_fields(dependent)
    assert_fields(
        dependent,
        id=created["id"],
        employee_id=employee["id"],
        relationship_type="SPOUSE",
        coverage_status="ENROLLED",
        enrolled_at="2026-08-05",
        monthly_cost_cents=MONTHLY_COST_CENTS["SPOUSE"],
        poe_program_id=None,
        poe_deadline_at=None,
        accepted_proof_type_count=0,
        documentation_complete=False,
        paid_claims_total_cents=0,
        recovery_revision=0,
        coverage_end_date=None,
        reinstated_at=None,
    )


def test_listing_audit_programs_pages_the_catalogue_and_filters_it_by_status(
    b, client, clock
):
    """The four pagination fields reported in `meta` are `limit` (the effective page
    size applied), `offset` (the effective skip applied), `total_count` (the number
    of records matching the request's filters before pagination), and `has_more`
    (true when records remain beyond the current page)

    Design: Corner/entities/corner_list_audit_programs_paginates_and_filters_by_status
    """
    for program_name in (
        "PY2026 Census Audit",
        "PY2026 New Dependent Audit",
        "PY2026 Targeted Audit",
    ):
        b.program(program_name=program_name, plan_year=2026)

    response = client.list_programs(PROGRAM_ADMIN, params={"limit": 2, "offset": 0})
    first_page, first_meta = validate_paginated(response)
    assert response.json()["response_type"] == "array", response.json()
    assert len(first_page) == 2, first_page
    assert_page_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)

    second_page, second_meta = validate_paginated(
        client.list_programs(PROGRAM_ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, second_page
    assert_page_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
    assert second_page[0]["id"] not in ids_of(first_page)

    drafts, draft_meta = validate_paginated(
        client.list_programs(
            PROGRAM_ADMIN, params={"status": "DRAFT", "limit": 10, "offset": 0}
        )
    )
    assert len(drafts) == 3, drafts
    assert_page_meta(draft_meta, limit=10, offset=0, total_count=3, has_more=False)


def test_reading_an_audit_program_that_does_not_exist_reports_the_program_lookup_failure(
    b, client, clock
):
    """A missing program yields `ERR_PROGRAM_NOT_FOUND`

    Design: Corner/entities/corner_get_audit_program_unknown_id_returns_program_not_found
    """
    response = client.get_program(NON_EXISTENT_UUID, PROGRAM_ADMIN)

    validate_error(response, E.ERR_PROGRAM_NOT_FOUND, expected_status=404)
    assert response.json()["response_type"] == "error", response.json()


def test_registering_an_employee_without_a_work_email_is_a_malformed_request(
    b, client, clock
):
    """Request body shape: required fields present, enum values drawn from the
    declared member sets

    Design: Corner/entities/corner_create_employee_missing_work_email_returns_invalid_request
    """
    payload = f.employee_payload(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    payload.pop("work_email")

    response = client.create_employee(payload, PROGRAM_ADMIN)

    validate_error(response, E.ERR_INVALID_REQUEST, expected_status=400)


def test_creating_an_audit_program_without_cadence_parameters_applies_the_declared_defaults(
    b, client, clock
):
    """`amnesty_days` defaults to 21 and must be between 0 and 90; `response_days`
    defaults to 45 and must be between 7 and 180; `reminder_min_gap_days` defaults
    to 7 and must be between 1 and 60; `max_reminders` defaults to 3 and must be
    between 1 and 10. `poe_verification_enabled` defaults to true.

    Design: Corner/entities/corner_create_audit_program_omitting_optionals_applies_declared_defaults
    """
    response = client.create_program(
        {"program_name": "PY2026 Census Audit", "plan_year": 2026}, PROGRAM_ADMIN
    )
    program = validate_success(response, expected_status=201)

    assert_mutable_common_fields(program)
    assert_fields(
        program,
        amnesty_days=21,
        response_days=45,
        reminder_min_gap_days=7,
        max_reminders=3,
        poe_verification_enabled=True,
        status="DRAFT",
        scope_type=None,
        announcement_at=None,
        amnesty_end_at=None,
        response_deadline_at=None,
        last_savings_variant=None,
        sweep_epoch=0,
    )
    assert_program_starts_at_zero(program)


def test_enrolling_a_child_stores_the_schedule_cost_rather_than_the_figure_supplied(
    b, client, clock
):
    """Although the enrollment payload nominally carries `monthly_cost_cents`, the
    stored value is always the schedule figure for the declared relationship class
    described in §2.7; a client-supplied figure is never persisted. ... A
    `CHILD_BIOLOGICAL`, a `STEPCHILD`, an `ADOPTED_CHILD`, and a
    `LEGAL_GUARDIANSHIP` dependent each cost 30,500 cents per month.

    Design: Corner/entities/corner_dependent_monthly_cost_is_derived_from_relationship_type_not_from_the_request
    """
    employee = b.employee()

    response = client.create_dependent(
        employee["id"],
        f.dependent_payload("CHILD_BIOLOGICAL", monthly_cost_cents=999),
        PROGRAM_ADMIN,
    )
    dependent = validate_success(response, expected_status=201)

    assert dependent["monthly_cost_cents"] == 30500, dependent
    assert dependent["monthly_cost_cents"] != 999, dependent

    assert b.read_employee(employee["id"])["enrolled_dependent_count"] == 1


def test_enrolling_a_dependent_under_an_undeclared_relationship_class_is_a_malformed_request(
    b, client, clock
):
    """A dependent joins a household with a declared `relationship_type` — one of
    `SPOUSE`, `DOMESTIC_PARTNER`, `CHILD_BIOLOGICAL`, `STEPCHILD`, `ADOPTED_CHILD`,
    `DISABLED_ADULT_CHILD`, or `LEGAL_GUARDIANSHIP`

    Design: Corner/entities/corner_create_dependent_with_unknown_relationship_type_returns_invalid_request
    """
    employee = b.employee()

    payload = f.dependent_payload("CHILD_BIOLOGICAL")
    payload["relationship_type"] = "NEPHEW"

    response = client.create_dependent(employee["id"], payload, PROGRAM_ADMIN)

    validate_error(response, E.ERR_INVALID_REQUEST, expected_status=400)
    assert b.read_employee(employee["id"])["enrolled_dependent_count"] == 0


def test_listing_a_households_dependents_beyond_the_maximum_page_size_is_a_malformed_request(
    b, client, clock
):
    """A `limit` outside the inclusive range 1 through 100, or a negative `offset`,
    is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

    Design: Corner/entities/corner_list_dependents_with_limit_above_one_hundred_returns_invalid_request
    """
    employee = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    b.dependent(employee["id"], "SPOUSE")

    response = client.list_employee_dependents(
        employee["id"], PROGRAM_ADMIN, params={"limit": 101, "offset": 0}
    )

    validate_error(response, E.ERR_INVALID_REQUEST, expected_status=400)


def test_a_recorded_amnesty_removal_carries_no_version_and_no_update_stamp(b, client):
    """Three record types are append-only historical evidence and therefore
    deliberately carry **only** `id` and `created_at` — for `AmnestyRemoval`,
    `PaidClaimLine`, and `CommunicationEvent`, both `updated_at` and `version` are
    absent from the resource entirely.

    Design: Corner/entities/corner_amnesty_removal_row_is_immutable_and_carries_no_version_field
    """
    ctx = announced_wave(b, relationships=("SPOUSE", "CHILD_BIOLOGICAL"))
    b.set_clock("2026-09-10T00:00:00Z")

    response = client.create_amnesty_removal(
        f.amnesty_removal_payload(
            ctx.dep2["id"], ctx.case["id"], reason_code="AGE_LIMIT_EXCEEDED"
        ),
        employee_headers(ctx.employee["id"]),
    )
    removal = validate_success(response, expected_status=201)

    assert_evidence_common_fields(removal)


def test_an_amnesty_removal_fixes_its_month_end_coverage_date_and_prorated_saving_at_creation(
    b, client
):
    """Its `coverage_end_date` is the last calendar day of the month containing that
    instant ... Its `audited_savings_contribution_cents` is the dependent's
    `monthly_cost_cents` multiplied by twelve minus the calendar month number of the
    removal's `coverage_end_date`

    Design: Corner/entities/corner_amnesty_removal_row_is_immutable_and_carries_no_version_field
    """
    ctx = announced_wave(b, relationships=("SPOUSE", "CHILD_BIOLOGICAL"))
    b.set_clock("2026-09-10T00:00:00Z")

    response = client.create_amnesty_removal(
        f.amnesty_removal_payload(
            ctx.dep2["id"], ctx.case["id"], reason_code="AGE_LIMIT_EXCEEDED"
        ),
        employee_headers(ctx.employee["id"]),
    )
    removal = validate_success(response, expected_status=201)

    assert_instant_equals(removal["recorded_at"], "2026-09-10T00:00:00Z")
    assert_fields(
        removal,
        dependent_id=ctx.dep2["id"],
        case_id=ctx.case["id"],
        reason_code="AGE_LIMIT_EXCEEDED",
        coverage_end_date="2026-09-30",
        penalty_waived=True,
        claims_recovery_waived=True,
        audited_savings_contribution_cents=(
            MONTHLY_COST_CENTS["CHILD_BIOLOGICAL"] * (12 - 9)
        ),
    )

    rows, meta = b.dependent_removals(ctx.dep2["id"], limit=10, offset=0)
    assert meta["total_count"] == 1, meta
    assert rows[0]["reason_code"] == "AGE_LIMIT_EXCEEDED", rows[0]


def test_enrolling_a_dependent_under_an_unknown_subscriber_reports_the_employee_lookup_failure(
    b, client, clock
):
    """Path parameters are resolved strictly left to right, and the first segment
    that fails to resolve determines the error. ... a missing employee
    `ERR_EMPLOYEE_NOT_FOUND`

    Design: Corner/entities/corner_create_dependent_under_unknown_employee_returns_employee_not_found
    """
    response = client.create_dependent(
        NON_EXISTENT_UUID, f.dependent_payload("SPOUSE"), PROGRAM_ADMIN
    )

    validate_error(response, E.ERR_EMPLOYEE_NOT_FOUND, expected_status=404)


def test_offering_proof_for_a_dependent_outside_the_addressed_cases_frozen_scope_is_refused(
    b, client
):
    """the dependent's `coverage_status` must be exactly `PENDING_VERIFICATION` and
    its identifier must appear in the case's `in_scope_dependent_ids`, since a
    submission for someone outside the frozen scope set is meaningless

    Design: Corner/entities/corner_proof_submission_naming_a_dependent_outside_the_addressed_case_is_rejected
    """
    b.set_clock(ORIGIN_INSTANT)
    subscriber = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    other_subscriber = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    b.dependent(subscriber["id"], "SPOUSE")
    other_dependent = b.dependent(other_subscriber["id"], "SPOUSE")

    program = b.program()
    b.doc_rule(program["id"], "SPOUSE")
    b.scope(program["id"], "FULL_CENSUS")
    b.set_clock(ANNOUNCE_INSTANT)
    b.communicate(program["id"])

    case = _case_for(b, program["id"], subscriber["id"])
    assert other_dependent["id"] not in case["in_scope_dependent_ids"], case

    response = client.create_proof_submission(
        f.proof_submission_payload(
            case["id"], other_dependent["id"], "MARRIAGE_CERTIFICATE"
        ),
        ANALYST,
    )

    validate_error(response, E.ERR_DEPENDENT_STATE_INVALID, expected_status=409)
    _rows, meta = b.submissions(dependent_id=other_dependent["id"])
    assert meta["total_count"] == 0, meta
