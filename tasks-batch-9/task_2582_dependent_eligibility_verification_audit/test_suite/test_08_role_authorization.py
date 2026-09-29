"""Who may act, and on whose household.

The four operational personas of an eligibility audit are deliberately separated:
the administrator who governs the program, the analyst who reads documents, the
independent reviewer who hears appeals and the recovery agent who pursues paid
claims. Alongside them sits the subscriber under audit, who sees only their own
household. This module exercises the gates that keep them apart — the identity
headers every call must carry, the per-endpoint role lists, the ownership test on
a subscriber's own records, and the two identity rules that govern an appeal.
"""
from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_fields, assert_instant_equals
from test_helpers.constants import EMPLOYEE
from test_helpers.fixtures import (
    ANNOUNCE_INSTANT,
    ESCALATION_INSTANT,
    ORIGIN_INSTANT,
    RESPONSE_WINDOW_INSTANT,
    announced_wave,
)
from test_helpers.test_users import (
    DUAL_HAT_ANALYST,
    DUAL_HAT_REVIEWER,
    DUAL_HAT_USER_ID,
    MISSING_ROLE_HEADERS,
    MISSING_USER_HEADERS,
    NO_HEADERS,
    PROGRAM_ADMIN,
    RECOVERY_AGENT,
    REVIEWER,
    REVIEWER_ALT,
    REVIEWER_ALT_USER_ID,
    UNKNOWN_ROLE_HEADERS,
    employee_headers,
    headers_for_each_role,
)
from test_helpers.types import Ctx

# A working instant inside the amnesty window of a 2026-09-01 announcement.
AMNESTY_INSTANT = "2026-09-10T00:00:00Z"
# A working instant inside the 30-day appeal window of a 2026-10-17 notice.
APPEAL_FILING_INSTANT = "2026-10-20T00:00:00Z"
# The instant a mailed document is transcribed, inside the amnesty window.
SUBMISSION_INSTANT = "2026-09-05T00:00:00Z"


def _case_for(b, program_id: str, employee_id: str):
    """The audit case a program holds for one subscriber."""
    matches = [row for row in b.cases(program_id) if row["employee_id"] == employee_id]
    assert matches, f"no audit case for employee {employee_id}"
    return matches[0]


def _notice_of(b, dependent_id: str):
    """The termination notice standing against one dependent."""
    matches = [row for row in b.notices() if row["dependent_id"] == dependent_id]
    assert matches, f"no termination notice for dependent {dependent_id}"
    return matches[0]


def _draft_program_and_one_household(b):
    """One subscriber holding one enrolled dependent, plus a program in DRAFT."""
    b.set_clock(ORIGIN_INSTANT)
    employee = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    dependent = b.dependent(employee["id"], "SPOUSE")
    program = b.program()
    return employee, dependent, b.read_program(program["id"])


def _two_household_amnesty_wave(b) -> Ctx:
    """Two subscribers pulled into one FULL_CENSUS audit, both cases NOTIFIED."""
    b.set_clock(ORIGIN_INSTANT)
    subscriber = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    neighbour = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    dependent = b.dependent(subscriber["id"], "SPOUSE")
    neighbour_dependent = b.dependent(neighbour["id"], "SPOUSE")

    program = b.program()
    b.doc_rule(program["id"], "SPOUSE")
    b.scope(program["id"], "FULL_CENSUS")
    b.set_clock(ANNOUNCE_INSTANT)
    b.communicate(program["id"])
    b.set_clock(AMNESTY_INSTANT)

    return Ctx(
        program=b.read_program(program["id"]),
        employee=subscriber,
        dependent=dependent,
        case=_case_for(b, program["id"], subscriber["id"]),
        other_employee=neighbour,
        other_dependent=neighbour_dependent,
        other_case=_case_for(b, program["id"], neighbour["id"]),
    )


def _appeal_awaiting_a_reviewer(b) -> Ctx:
    """A rejected document, an escalated case, and an appeal not yet taken.

    The document is rejected by an operator who later returns wearing the
    reviewer's hat, which is the identity the segregation-of-duties comparison is
    written against.
    """
    ctx = announced_wave(b)
    b.set_clock(SUBMISSION_INSTANT)
    submission = b.submit_proof(ctx.case["id"], ctx.dep["id"], ctx.employee["id"])

    b.set_clock(RESPONSE_WINDOW_INSTANT)
    b.sweep(ctx.program["id"])
    ctx.submission = b.reject_proof(submission["id"], DUAL_HAT_ANALYST)

    b.set_clock(ESCALATION_INSTANT)
    b.sweep(ctx.program["id"])

    b.set_clock(APPEAL_FILING_INSTANT)
    ctx.appeal = b.appeal(
        ctx.case["id"], ctx.dep["id"], ctx.employee["id"], "ADMINISTRATIVE_ERROR"
    )
    ctx.case = b.read_case(ctx.case["id"])
    ctx.notice = _notice_of(b, ctx.dep["id"])
    return ctx


# --------------------------------------------------------------- header authentication
UNIDENTIFIED_CALLERS = (
    pytest.param(NO_HEADERS, id="neither_header_present"),
    pytest.param(MISSING_ROLE_HEADERS, id="role_header_omitted"),
    pytest.param(MISSING_USER_HEADERS, id="user_header_omitted"),
    pytest.param(UNKNOWN_ROLE_HEADERS, id="role_outside_the_five_declared_names"),
)


@pytest.mark.parametrize("headers", UNIDENTIFIED_CALLERS)
def test_a_call_whose_identity_headers_are_absent_or_undeclared_is_refused_as_unauthenticated(
    b, client, headers
):
    """Every request — reads included — must carry two headers. ... If either header
    is absent, or if `X-User-Role` is not one of the five declared role names, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

    Design: Corner/rbac/corner_missing_or_unknown_role_header_is_unauthenticated_before_anything_else
    """
    b.set_clock(ORIGIN_INSTANT)

    response = client.list_programs(headers, params={"limit": 10, "offset": 0})

    validate_error(response, E.ERR_UNAUTHENTICATED, expected_status=401)


def test_registering_a_subscriber_without_an_acting_user_identifier_records_nobody(
    b, client
):
    """If either header is absent, or if `X-User-Role` is not one of the five
    declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401). ... `work_email` unique across all employees

    Design: Corner/rbac/corner_missing_or_unknown_role_header_is_unauthenticated_before_anything_else
    """
    b.set_clock(ORIGIN_INSTANT)
    payload = f.employee_payload(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )

    response = client.create_employee(payload, MISSING_USER_HEADERS)

    validate_error(response, E.ERR_UNAUTHENTICATED, expected_status=401)

    # The rejected call registered nobody, so the notification address it carried
    # is still free for the identical payload sent by an identified administrator.
    registered = validate_success(
        client.create_employee(payload, PROGRAM_ADMIN), expected_status=201
    )
    assert registered["work_email"] == payload["work_email"], registered


# ------------------------------------------------------------- endpoint role lists
OPERATIONS_RESERVED_TO_ANOTHER_ROLE = (
    pytest.param(
        lambda client, employee, dependent, program: client.create_program(
            f.program_payload(program_name="Shadow Program"),
            employee_headers(employee["id"]),
        ),
        id="subscriber_creating_an_audit_program",
    ),
    pytest.param(
        lambda client, employee, dependent, program: client.run_scope(
            program["id"],
            f.scope_payload(program["version"], "FULL_CENSUS"),
            RECOVERY_AGENT,
        ),
        id="recovery_agent_deciding_audit_scope",
    ),
    pytest.param(
        lambda client, employee, dependent, program: client.decide_proof_submission(
            NON_EXISTENT_UUID,
            f.decision_payload("ACCEPT", "VERIFIED_MATCH"),
            PROGRAM_ADMIN,
        ),
        id="administrator_deciding_a_proof_submission",
    ),
    pytest.param(
        lambda client, employee, dependent, program: client.create_claim_recovery(
            f.claim_recovery_payload(
                dependent["id"], NON_EXISTENT_UUID, dependent["version"]
            ),
            REVIEWER,
        ),
        id="appeal_reviewer_opening_a_claims_recovery",
    ),
)


@pytest.mark.parametrize("attempt", OPERATIONS_RESERVED_TO_ANOTHER_ROLE)
def test_a_role_outside_an_endpoints_permitted_set_is_refused_before_any_lookup_runs(
    b, client, attempt
):
    """If the headers are well formed but the declared role is not among the roles
    authorised for the addressed endpoint, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403). ... Role authorisation against the endpoint's
    permitted roles — `ERR_UNAUTHORIZED` (403).

    Design: Corner/rbac/corner_each_role_is_locked_out_of_the_other_roles_exclusive_operations
    """
    employee, dependent, program = _draft_program_and_one_household(b)

    response = attempt(client, employee, dependent, program)

    # Two of these attempts address an identifier that resolves to nothing, so a
    # 403 here also fixes the role screen ahead of the existence screen.
    validate_error(response, E.ERR_UNAUTHORIZED, expected_status=403)

    assert_fields(b.read_program(program["id"]), status="DRAFT", version=1)
    _rows, meta = validate_paginated(
        client.list_programs(PROGRAM_ADMIN, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1, meta


def test_the_program_catalogue_is_shared_by_every_operator_role_and_closed_to_subscribers(
    b, client
):
    """If the headers are well formed but the declared role is not among the roles
    authorised for the addressed endpoint, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403). ... The five roles are `ProgramAdmin`,
    `VerificationAnalyst`, `AppealReviewer`, `RecoveryAgent`, and `Employee`.

    Design: Corner/rbac/corner_each_role_is_locked_out_of_the_other_roles_exclusive_operations
    """
    employee, _dependent, program = _draft_program_and_one_household(b)

    for role, headers in headers_for_each_role(employee["id"]).items():
        response = client.list_programs(headers, params={"limit": 10, "offset": 0})
        if role == EMPLOYEE:
            validate_error(response, E.ERR_UNAUTHORIZED, expected_status=403)
            continue
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1, (role, meta)
        assert rows[0]["id"] == program["id"], (role, rows)


# --------------------------------------------------------------- household ownership
ANSWERS_ADDRESSED_TO_ANOTHER_HOUSEHOLD = (
    pytest.param(
        lambda client, ctx: client.create_amnesty_removal(
            f.amnesty_removal_payload(
                ctx.dependent["id"], ctx.case["id"], reason_code="DIVORCE_FINALIZED"
            ),
            employee_headers(ctx.other_employee["id"]),
        ),
        id="recording_an_amnesty_removal",
    ),
    pytest.param(
        lambda client, ctx: client.create_proof_submission(
            f.proof_submission_payload(
                ctx.case["id"], ctx.dependent["id"], "MARRIAGE_CERTIFICATE"
            ),
            employee_headers(ctx.other_employee["id"]),
        ),
        id="submitting_a_proof_document",
    ),
)


@pytest.mark.parametrize("attempt", ANSWERS_ADDRESSED_TO_ANOTHER_HOUSEHOLD)
def test_a_subscriber_cannot_answer_the_audit_of_a_household_that_is_not_theirs(
    b, client, attempt
):
    """Ownership resolves transitively: a dependent belongs to the employee named by
    its `employee_id`, an audit case belongs to the employee named by its
    `employee_id`, and a proof submission, an amnesty removal, an appeal, or a
    termination notice belongs to whichever employee owns the dependent or case it
    points at. ... An `Employee` caller who addresses a resource that does not
    resolve to their own employee record is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403).

    Design: Corner/rbac/corner_an_employee_cannot_answer_another_employees_case
    """
    ctx = _two_household_amnesty_wave(b)

    response = attempt(client, ctx)

    validate_error(response, E.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    assert_fields(
        b.read_case(ctx.case["id"]),
        status="NOTIFIED",
        proof_submission_count=0,
        employee_id=ctx.employee["id"],
    )
    assert_fields(
        b.read_dependent(ctx.dependent["id"]), coverage_status="PENDING_VERIFICATION"
    )
    assert_fields(
        b.read_dependent(ctx.other_dependent["id"]),
        coverage_status="PENDING_VERIFICATION",
    )


def test_the_owning_subscriber_may_lodge_the_document_the_other_household_was_refused(
    b, client
):
    """Either the `Employee` or a `VerificationAnalyst` transcribing a mailed packet
    may lodge a submission, naming the `case_id` it answers ... the first response of
    any kind on a notified case moves it `NOTIFIED → IN_PROGRESS`

    Design: Corner/rbac/corner_an_employee_cannot_answer_another_employees_case
    """
    ctx = _two_household_amnesty_wave(b)

    response = client.create_proof_submission(
        f.proof_submission_payload(
            ctx.case["id"], ctx.dependent["id"], "MARRIAGE_CERTIFICATE"
        ),
        employee_headers(ctx.employee["id"]),
    )
    submission = validate_success(response, expected_status=201)

    assert_fields(submission, review_status="SUBMITTED", dependent_id=ctx.dependent["id"])
    assert_fields(
        b.read_case(ctx.case["id"]),
        status="IN_PROGRESS",
        proof_submission_count=1,
        employee_id=ctx.employee["id"],
    )
    # The neighbouring household was never part of this exchange.
    assert_fields(b.read_case(ctx.other_case["id"]), status="NOTIFIED", proof_submission_count=0)
    assert_fields(
        b.read_dependent(ctx.other_dependent["id"]),
        coverage_status="PENDING_VERIFICATION",
    )


# ------------------------------------------------------------------ appeal identity
def test_the_operator_who_judged_the_documents_may_not_take_the_resulting_appeal(
    b, client
):
    """First, **segregation of duties**: the `X-User-ID` that appears as
    `reviewed_by_user_id` on any proof submission belonging to a dependent may never
    take that dependent's appeal; an attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

    Design: Corner/rbac/corner_appeal_review_enforces_segregation_of_duties_and_reviewer_binding
    """
    ctx = _appeal_awaiting_a_reviewer(b)
    assert ctx.submission["reviewed_by_user_id"] == DUAL_HAT_USER_ID, ctx.submission

    response = client.assign_appeal(ctx.appeal["id"], {}, DUAL_HAT_REVIEWER)

    validate_error(response, E.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    assert_fields(
        b.read_appeal(ctx.appeal["id"]),
        status="SUBMITTED",
        round_number=1,
        reviewer_user_id=None,
        assigned_at=None,
        decided_at=None,
    )


def test_only_the_reviewer_who_took_the_appeal_may_decide_it(b, client):
    """An `AppealReviewer` takes the appeal, which moves it `SUBMITTED →
    UNDER_REVIEW` and stamps `reviewer_user_id` with the acting `X-User-ID` and
    `assigned_at` with the current clock instant. ... Second, **reviewer
    exclusivity**: once an appeal has been taken, only the `AppealReviewer` whose
    identifier is stored in `reviewer_user_id` may decide it, and any other user
    attempting a decision is rejected with `ERR_APPEAL_REVIEWER_MISMATCH` (HTTP 403).

    Design: Corner/rbac/corner_appeal_review_enforces_segregation_of_duties_and_reviewer_binding
    """
    ctx = _appeal_awaiting_a_reviewer(b)

    taken = validate_success(client.assign_appeal(ctx.appeal["id"], {}, REVIEWER_ALT))
    assert_fields(taken, status="UNDER_REVIEW", reviewer_user_id=REVIEWER_ALT_USER_ID)
    assert_instant_equals(taken["assigned_at"], APPEAL_FILING_INSTANT)

    refused = client.decide_appeal(
        ctx.appeal["id"],
        f.appeal_decision_payload("DENY"),
        REVIEWER,
    )
    validate_error(refused, E.ERR_APPEAL_REVIEWER_MISMATCH, expected_status=403)
    assert_fields(b.read_appeal(ctx.appeal["id"]), status="UNDER_REVIEW", decided_at=None)

    decided = validate_success(
        client.decide_appeal(
            ctx.appeal["id"], f.appeal_decision_payload("DENY"), REVIEWER_ALT
        )
    )
    assert_fields(decided, status="DENIED", reviewer_user_id=REVIEWER_ALT_USER_ID)
    assert_instant_equals(decided["decided_at"], APPEAL_FILING_INSTANT)

    # A denial leaves the termination it contested standing.
    assert_fields(
        b.read_dependent(ctx.dep["id"]), coverage_status="TERMINATION_PENDING"
    )
    assert_fields(b.read_notice(ctx.notice["id"]), status="ISSUED")
