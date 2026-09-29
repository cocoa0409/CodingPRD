"""Authentication, role exclusivity, ownership, computed reads and collection filters."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_audit_packet_shape, assert_cents
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANONYMOUS_HEADERS,
    AUDITOR_HEADERS,
    PAYROLL_HEADERS,
    RECORDKEEPER_HEADERS,
)

# Deliberately unresolvable identifiers, one per resource family.
MISSING_EMPLOYEE_ID = "00000000-0000-0000-0000-000000000001"
MISSING_PAYROLL_PERIOD_ID = "00000000-0000-0000-0000-000000000002"
MISSING_LOAN_ACCOUNT_ID = "00000000-0000-0000-0000-000000000003"
MISSING_CERTIFICATION_ID = "00000000-0000-0000-0000-000000000004"
MISSING_ALLOCATION_ID = "00000000-0000-0000-0000-000000000005"
MISSING_FUNDING_BATCH_ID = "00000000-0000-0000-0000-000000000006"
MISSING_AMENDMENT_ID = "00000000-0000-0000-0000-000000000007"
MISSING_TEST_ID = "00000000-0000-0000-0000-000000000008"
MISSING_PLAN_YEAR_ID = "00000000-0000-0000-0000-0000000000ff"
MISSING_CERTIFICATION_LINE_ID = "00000000-0000-0000-0000-0000000000aa"
UNRESOLVABLE_DECISION_TARGET = "00000000-0000-0000-0000-0000000000b1"
UNRESOLVABLE_TEST_PLAN_YEAR = "00000000-0000-0000-0000-0000000000b2"
UNRESOLVABLE_SETTLEMENT_TARGET = "00000000-0000-0000-0000-0000000000b3"
UNRESOLVABLE_SUBMIT_TARGET = "00000000-0000-0000-0000-0000000000b4"


# ---------------------------------------------------------------------------
# Authentication and role exclusivity
# ---------------------------------------------------------------------------


def test_missing_role_header_returns_unauthenticated(client):
    """
    A request with no identity headers is refused before any other rule is consulted.

    PRD: "If either header is missing or empty, or if `X-User-Role` does not name one
    of the five declared roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/corner_missing_role_header_returns_unauthenticated
    """
    response = client.list_plan_years(ANONYMOUS_HEADERS)
    validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)


def test_exclusive_operations_denied_to_peer_roles(client):
    """
    Role exclusivity is checked before the target identifier is even resolved.

    PRD: "If the header names a valid role that is not listed among the authorized
    roles for the requested endpoint (see the table in §4), the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD: "When several rules could reject the same request, the rule with the smallest
    ordinal below decides the response."

    Design: Corner/rbac/corner_exclusive_operations_denied_to_peer_roles
    """
    decision = client.decide_certification(
        UNRESOLVABLE_DECISION_TARGET, f.decision_payload("ACCEPT"), PAYROLL_HEADERS
    )
    validate_error(decision, ApiErrorId.FORBIDDEN_ROLE.value, 403)

    test_creation = client.create_nondiscrimination_test(
        f.nondiscrimination_test_payload(UNRESOLVABLE_TEST_PLAN_YEAR), ADMIN_HEADERS
    )
    validate_error(test_creation, ApiErrorId.FORBIDDEN_ROLE.value, 403)

    settlement = client.settle_funding_batch(
        UNRESOLVABLE_SETTLEMENT_TARGET, f.settlement_payload("SETTLED"), ADMIN_HEADERS
    )
    validate_error(settlement, ApiErrorId.FORBIDDEN_ROLE.value, 403)

    submit = client.submit_certification(UNRESOLVABLE_SUBMIT_TARGET, None, AUDITOR_HEADERS)
    validate_error(submit, ApiErrorId.FORBIDDEN_ROLE.value, 403)


def test_employee_cannot_read_another_employees_claim(client):
    """
    Ownership on a claim is decided by its own employee, not by the caller's role.

    PRD: "On the following operations the target resource's owning employee must equal
    `X-User-ID`, or the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)"

    PRD: "ownership checks on any resource that references an `Employee` compare the
    resource's `employee_id` (or, for a certification line, the `employee_id` of its
    parent claim) to `X-User-ID`."

    Design: Corner/rbac/corner_employee_cannot_read_another_employees_claim
    """
    plan_year = fx.setup_open_plan_year(client)
    owner = fx.create_employee(client, external_id="E-OWNER")
    other = fx.create_employee(client, external_id="E-OTHER")

    claim = fx.open_certification(client, owner, plan_year["id"])

    intruder = client.get_loan_certification(claim["id"], fx.make_employee_headers(other["id"]))
    validate_error(intruder, ApiErrorId.NOT_RESOURCE_OWNER.value, 403)

    own = validate_success(
        client.get_loan_certification(claim["id"], fx.make_employee_headers(owner["id"]))
    )
    assert own["id"] == claim["id"]
    assert own["status"] == "DRAFT"

    administrative = validate_success(
        client.get_loan_certification(claim["id"], ADMIN_HEADERS)
    )
    assert administrative["id"] == claim["id"]


# ---------------------------------------------------------------------------
# The not-found family
# ---------------------------------------------------------------------------


def test_get_plan_year_unknown_id_returns_not_found(client):
    """
    A well-formed identifier that resolves to nothing is a not-found, not a bad request.

    PRD: "`plan_year_id` resolution — `ERR_PLAN_YEAR_NOT_FOUND`, on
    `POST /plan-amendments`, `POST /payroll-periods`, `POST /loan-certifications`,
    `POST /nondiscrimination-tests`, `POST /plan-years/{plan_year_id}/status`,
    `POST /plan-years/{plan_year_id}/true-up`, `POST /funding-batches`, and
    `GET /plan-years/{plan_year_id}`."

    PRD: "All of these are HTTP 404."

    Design: Corner/entities/corner_get_plan_year_unknown_id_returns_not_found
    """
    response = client.get_plan_year(MISSING_PLAN_YEAR_ID, ADMIN_HEADERS)
    validate_error(response, ApiErrorId.PLAN_YEAR_NOT_FOUND.value, 404)


def test_get_certification_line_unknown_id_returns_record_not_found(client):
    """
    The certified payment line has its own generic not-found code.

    PRD: "The remaining single-row reads — those addressed by `leave_event_id`,
    `certification_line_id`, `contribution_record_id`, `correction_id`, or
    `forfeiture_id` — share one code, `ERR_RECORD_NOT_FOUND`."

    PRD: "Audit-row resolution — `ERR_RECORD_NOT_FOUND`, on
    `GET /leave-events/{leave_event_id}`,
    `GET /certification-lines/{certification_line_id}`,
    `GET /contribution-records/{contribution_record_id}`,
    `GET /correction-adjustments/{correction_id}`, and
    `GET /forfeiture-records/{forfeiture_id}`."

    Design: Corner/entities/corner_get_certification_line_unknown_id_returns_record_not_found
    """
    response = client.get_certification_line(MISSING_CERTIFICATION_LINE_ID, ADMIN_HEADERS)
    validate_error(response, ApiErrorId.RECORD_NOT_FOUND.value, 404)


def test_not_found_family_for_every_resource_id(client):
    """
    Each resource family reports its own dedicated not-found code.

    PRD: "Each identifier has its own dedicated 404: `plan_year_id` yields
    `ERR_PLAN_YEAR_NOT_FOUND`; `employee_id` yields `ERR_EMPLOYEE_NOT_FOUND`;
    `payroll_period_id` yields `ERR_PAYROLL_PERIOD_NOT_FOUND`; `loan_account_id` yields
    `ERR_LOAN_ACCOUNT_NOT_FOUND`; `certification_id` — and also
    `supersedes_certification_id` when supplied in a body — yields
    `ERR_CERTIFICATION_NOT_FOUND`; `allocation_id` yields `ERR_ALLOCATION_NOT_FOUND`;
    `funding_batch_id` yields `ERR_FUNDING_BATCH_NOT_FOUND`; `amendment_id` yields
    `ERR_AMENDMENT_NOT_FOUND`; `test_id` yields `ERR_TEST_NOT_FOUND`."

    PRD: "All of these are HTTP 404."

    Design: Corner/errors/corner_not_found_family_for_every_resource_id
    """
    validate_error(
        client.get_employee(MISSING_EMPLOYEE_ID, ADMIN_HEADERS),
        ApiErrorId.EMPLOYEE_NOT_FOUND.value,
        404,
    )
    validate_error(
        client.get_payroll_period(MISSING_PAYROLL_PERIOD_ID, ADMIN_HEADERS),
        ApiErrorId.PAYROLL_PERIOD_NOT_FOUND.value,
        404,
    )
    validate_error(
        client.get_loan_account(MISSING_LOAN_ACCOUNT_ID, ADMIN_HEADERS),
        ApiErrorId.LOAN_ACCOUNT_NOT_FOUND.value,
        404,
    )
    validate_error(
        client.get_loan_certification(MISSING_CERTIFICATION_ID, ADMIN_HEADERS),
        ApiErrorId.CERTIFICATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        client.get_match_allocation(MISSING_ALLOCATION_ID, ADMIN_HEADERS),
        ApiErrorId.ALLOCATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        client.get_funding_batch(MISSING_FUNDING_BATCH_ID, ADMIN_HEADERS),
        ApiErrorId.FUNDING_BATCH_NOT_FOUND.value,
        404,
    )
    validate_error(
        client.get_plan_amendment(MISSING_AMENDMENT_ID, ADMIN_HEADERS),
        ApiErrorId.AMENDMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        client.get_nondiscrimination_test(MISSING_TEST_ID, ADMIN_HEADERS),
        ApiErrorId.TEST_NOT_FOUND.value,
        404,
    )


# ---------------------------------------------------------------------------
# Listings and the computed audit packet
# ---------------------------------------------------------------------------


def test_list_employees_pagination_reports_total_and_has_more(client):
    """
    A paged listing reports the unpaged total and whether more elements remain.

    PRD: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside
    the `meta` object of the envelope described in §2.2."

    PRD: "`offset` is the number of items to skip; when omitted it defaults to 0, and
    its minimum accepted value is 0."

    Design: Corner/entities/corner_list_employees_pagination_reports_total_and_has_more
    """
    fx.setup_open_plan_year(client)
    fx.create_employee(client, external_id="E-P1")
    fx.create_employee(client, external_id="E-P2")
    fx.create_employee(client, external_id="E-P3")

    first_page, first_meta = validate_paginated(
        client.list_employees(ADMIN_HEADERS, {"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        client.list_employees(ADMIN_HEADERS, {"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    assert first_page[0]["id"] != second_page[0]["id"]


def test_every_collection_filters_by_its_declared_foreign_key(client):
    """
    Each collection is reachable through its own declared filters with exact totals.

    PRD: "Filter parameters on list endpoints are optional and combine conjunctively;
    `limit` and `offset` behave as described in §2.3."

    PRD: "Each merged span contributes the whole number of days between its own start
    and end, plus one for inclusivity, and `unpaid_leave_days_ytd` is the sum over
    merged spans."

    Design: Corner/entities/corner_every_collection_filters_by_its_declared_foreign_key
    """
    plan_year = fx.setup_open_plan_year(client)
    amendment = fx.create_amendment(client, plan_year["id"], document_ref="AMD-2026-LIST")
    employee = fx.create_employee(client, external_id="E-LISTING")

    first_period = fx.create_payroll_period(client, plan_year["id"], 1)
    second_period = fx.create_payroll_period(client, plan_year["id"], 2)
    first_record = fx.post_contribution_record(client, employee["id"], first_period["id"])
    fx.post_contribution_record(client, employee["id"], second_period["id"])

    loan_account = fx.setup_verified_loan_account(client, employee, evidence_ref="STMT-LIST")
    leave_event = fx.file_leave_event(
        client,
        employee["id"],
        "2026-06-01T00:00:00Z",
        "2026-06-10T00:00:00Z",
        leave_type="PAID_FMLA",
    )

    claim = fx.open_certification(client, employee, plan_year["id"])
    fx.add_certification_line(
        client,
        claim["id"],
        employee,
        loan_account["id"],
        payment_date="2026-03-15T00:00:00Z",
        amount_cents=30_000,
        covered_period_start="2026-03-01T00:00:00Z",
        covered_period_end="2026-04-01T00:00:00Z",
    )
    fx.add_certification_line(
        client,
        claim["id"],
        employee,
        loan_account["id"],
        payment_date="2026-04-15T00:00:00Z",
        amount_cents=30_000,
        covered_period_start="2026-04-01T00:00:00Z",
        covered_period_end="2026-05-01T00:00:00Z",
    )

    batch = fx.create_funding_batch(client, plan_year["id"], first_period["id"])
    test = fx.open_nondiscrimination_test(client, plan_year["id"])

    amendments, amendments_meta = validate_paginated(
        client.list_plan_amendments(ADMIN_HEADERS, {"plan_year_id": plan_year["id"]})
    )
    assert amendments[0]["id"] == amendment["id"]
    assert amendments_meta["total_count"] == 1

    periods, periods_meta = validate_paginated(
        client.list_payroll_periods(
            PAYROLL_HEADERS, {"plan_year_id": plan_year["id"], "status": "OPEN"}
        )
    )
    assert len(periods) == 2
    assert periods_meta["total_count"] == 2
    assert periods[0]["period_number"] == 1

    records, records_meta = validate_paginated(
        client.list_contribution_records(PAYROLL_HEADERS, {"employee_id": employee["id"]})
    )
    assert records[0]["id"] == first_record["id"]
    assert records_meta["total_count"] == 2

    read_record = validate_success(
        client.get_contribution_record(first_record["id"], PAYROLL_HEADERS)
    )
    assert read_record["id"] == first_record["id"]
    assert_cents(read_record["deferral_match_cents"], 20_000, "deferral_match_cents")

    accounts, accounts_meta = validate_paginated(
        client.list_loan_accounts(
            ADMIN_HEADERS, {"employee_id": employee["id"], "status": "VERIFIED"}
        )
    )
    assert accounts[0]["id"] == loan_account["id"]
    assert accounts_meta["total_count"] == 1

    claims, claims_meta = validate_paginated(
        client.list_loan_certifications(
            ADMIN_HEADERS,
            {
                "employee_id": employee["id"],
                "plan_year_id": plan_year["id"],
                "status": "DRAFT",
            },
        )
    )
    assert claims[0]["id"] == claim["id"]
    assert claims_meta["total_count"] == 1
    assert_cents(claims[0]["certified_total_cents"], 60_000, "certified_total_cents")

    sub_lines, sub_lines_meta = validate_paginated(
        client.list_certification_lines_of(claim["id"], ADMIN_HEADERS)
    )
    assert_cents(sub_lines[0]["amount_cents"], 30_000, "first line amount_cents")
    assert sub_lines_meta["total_count"] == 2

    paged_lines, paged_lines_meta = validate_paginated(
        client.list_certification_lines(
            ADMIN_HEADERS, {"certification_id": claim["id"], "limit": 1, "offset": 1}
        )
    )
    assert len(paged_lines) == 1
    assert_cents(paged_lines[0]["amount_cents"], 30_000, "paged line amount_cents")
    assert paged_lines_meta["total_count"] == 2
    assert paged_lines_meta["has_more"] is False

    batches, batches_meta = validate_paginated(
        client.list_funding_batches(
            RECORDKEEPER_HEADERS, {"plan_year_id": plan_year["id"], "status": "PENDING"}
        )
    )
    assert batches[0]["id"] == batch["id"]
    assert batches_meta["total_count"] == 1

    leaves, leaves_meta = validate_paginated(
        client.list_leave_events(
            ADMIN_HEADERS, {"employee_id": employee["id"], "leave_type": "PAID_FMLA"}
        )
    )
    assert leaves[0]["id"] == leave_event["id"]
    assert leaves_meta["total_count"] == 1

    read_leave = validate_success(client.get_leave_event(leave_event["id"], ADMIN_HEADERS))
    assert read_leave["id"] == leave_event["id"]
    assert read_leave["day_count"] == 10

    tests, tests_meta = validate_paginated(
        client.list_nondiscrimination_tests(AUDITOR_HEADERS, {"plan_year_id": plan_year["id"]})
    )
    assert tests[0]["id"] == test["id"]
    assert tests[0]["status"] == "PENDING"
    assert tests_meta["total_count"] == 1


def test_audit_packet_computed_read_matches_ledger(client):
    """
    The audit packet recomputes each participant figure from the live ledger.

    PRD: "`accepted_certified_cents` sums `eligible_total_cents` over the
    participant's claims in that plan year whose status is `ACCEPTED` or `AUDIT_HOLD`."

    PRD: "`deferral_match_cents` sums the participant's `deferral_match_cents` across
    that plan year's payroll lines, and `qslp_match_cents` sums `amount_cents` over the
    participant's allocations in that plan year whose `funding_status` is `SCHEDULED` or
    `FUNDED`."

    Design: Corner/endpoints/corner_audit_packet_computed_read_matches_ledger
    """
    scenario = fx.setup_accepted_claim(client)
    claim = scenario["certification"]

    assert_cents(claim["eligible_total_cents"], 30_000, "eligible_total_cents")
    assert_cents(claim["matched_total_cents"], 20_000, "matched_total_cents")

    packet = validate_success(
        client.get_audit_packet(scenario["employee_id"], AUDITOR_HEADERS)
    )
    assert_audit_packet_shape(packet)
    assert packet["plan_year_id"] == scenario["plan_year_id"]
    assert packet["certification_count"] == 1
    assert_cents(packet["accepted_certified_cents"], 30_000, "accepted_certified_cents")
    assert_cents(packet["deferral_match_cents"], 20_000, "deferral_match_cents")
    assert_cents(packet["qslp_match_cents"], 20_000, "qslp_match_cents")
    assert_cents(packet["forfeited_cents"], 0, "forfeited_cents")
    assert_cents(packet["correction_cents"], 0, "correction_cents")
    assert_cents(packet["remaining_space_cents"], 2_250_000, "remaining_space_cents")
