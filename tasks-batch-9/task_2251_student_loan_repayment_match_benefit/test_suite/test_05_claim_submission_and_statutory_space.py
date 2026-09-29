"""Submitting the annual claim: window, eligibility, statutory room and concurrency."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_instant_equals
from test_helpers.constants import DEFAULT_ANNUAL_DEFERRAL_LIMIT_CENTS
from test_helpers.test_users import ADMIN_HEADERS


# ---------------------------------------------------------------------------
# Rule precedence: a locked plan year outranks exhausted statutory space
# ---------------------------------------------------------------------------


def test_locked_plan_year_outranks_exhausted_statutory_space(client):
    """
    A submit that violates both the lock and the statutory room reports the lock.

    PRD: "Plan year must be `OPEN` — `ERR_PLAN_YEAR_LOCKED`, on
    `POST /loan-certifications`, `POST /loan-certifications/{certification_id}/lines`,
    `POST /loan-certifications/{certification_id}/submit`,
    `POST /loan-certifications/{certification_id}/decision`, and
    `POST /contribution-records`."

    PRD: "When several rules could reject the same request, the rule with the
    smallest ordinal below decides the response."

    Design: Difficulty/priority_pair_validation_conflict/locked_plan_year_beats_space_exhausted
    """
    scenario = fx.build_claim_scenario(
        client, compensation_cents=10_000_000, deferral_cents=2_300_000
    )
    employee = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(employee["remaining_qslp_space_cents"], 0, "remaining_qslp_space_cents")

    fx.lock_plan_year(client, scenario["plan_year_id"])

    response = client.submit_certification(
        scenario["certification_id"], None, scenario["employee_headers"]
    )
    validate_error(response, ApiErrorId.PLAN_YEAR_LOCKED.value, 409)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert claim["status"] == "DRAFT"
    assert claim["submitted_at"] is None


def test_exhausted_statutory_space_surfaces_once_the_plan_year_is_open(client):
    """
    With the plan year left open the same submit reports the exhausted statutory room.

    PRD: "a result of zero is rejected with `ERR_QSLP_SPACE_EXHAUSTED`."

    PRD: "Statutory space must remain — `ERR_QSLP_SPACE_EXHAUSTED`, on
    `POST /loan-certifications/{certification_id}/submit`."

    Design: Difficulty/priority_pair_validation_conflict/locked_plan_year_beats_space_exhausted
    """
    scenario = fx.build_claim_scenario(
        client, compensation_cents=10_000_000, deferral_cents=2_300_000
    )
    employee = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(employee["remaining_qslp_space_cents"], 0, "remaining_qslp_space_cents")

    response = client.submit_certification(
        scenario["certification_id"], None, scenario["employee_headers"]
    )
    validate_error(response, ApiErrorId.QSLP_SPACE_EXHAUSTED.value, 422)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert claim["status"] == "DRAFT"
    assert claim["submitted_at"] is None


# ---------------------------------------------------------------------------
# The empty-line-set boundary
# ---------------------------------------------------------------------------


def test_submit_with_zero_lines_is_rejected(client):
    """
    A claim carrying an empty set of certified lines cannot be submitted.

    PRD: "the claim to carry at least one line, otherwise `ERR_NO_CERTIFIED_LINES`".

    PRD: "Because `DRAFT`, `RETURNED`, `VOIDED`, and `SUPERSEDED` sit outside the
    reserved set, submitting a claim and then having it returned restores the
    pre-submission figure exactly."

    Design: Difficulty/boundary_precision_check/submit_with_zero_lines_empty_set
    """
    scenario = fx.setup_claim_without_lines(client)

    before = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(before["remaining_qslp_space_cents"], 2_280_000, "remaining space before")

    claim_before = fx.refresh_certification(client, scenario["certification_id"])
    assert_cents(claim_before["certified_total_cents"], 0, "certified_total_cents")

    response = client.submit_certification(
        scenario["certification_id"], None, scenario["employee_headers"]
    )
    validate_error(response, ApiErrorId.NO_CERTIFIED_LINES.value, 422)

    claim_after = fx.refresh_certification(client, scenario["certification_id"])
    assert claim_after["status"] == "DRAFT"
    assert claim_after["submitted_at"] is None

    after = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(after["remaining_qslp_space_cents"], 2_280_000, "remaining space after")


def test_submit_with_one_line_crosses_the_empty_set_boundary(client):
    """
    A single certified line is enough to satisfy the at-least-one-line rule.

    PRD: "A successful submission stamps `submitted_at` with the current logical
    clock, drops the employee's `remaining_qslp_space_cents` by the claim's
    `certified_total_cents` because the claim now counts in the reserved set, and
    increments both the employee's and the claim's `version` by one."

    Design: Difficulty/boundary_precision_check/submit_with_zero_lines_empty_set
    """
    scenario = fx.setup_claim_without_lines(client)

    empty = client.submit_certification(
        scenario["certification_id"], None, scenario["employee_headers"]
    )
    validate_error(empty, ApiErrorId.NO_CERTIFIED_LINES.value, 422)

    fx.add_certification_line(
        client,
        scenario["certification_id"],
        scenario["employee"],
        scenario["loan_account_id"],
        amount_cents=30_000,
    )

    submitted = validate_success(
        client.submit_certification(
            scenario["certification_id"], None, scenario["employee_headers"]
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"] is not None
    assert_cents(submitted["certified_total_cents"], 30_000, "certified_total_cents")

    after = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(after["remaining_qslp_space_cents"], 2_250_000, "remaining space after")


# ---------------------------------------------------------------------------
# Submission corners
# ---------------------------------------------------------------------------


def test_submit_after_certification_deadline_rejected(client):
    """
    A claim submitted after the plan year's certification deadline is refused.

    PRD: "the current logical clock to fall within the plan year's
    `certification_window_open` through `certification_deadline` window inclusive on
    both ends, otherwise `ERR_CERTIFICATION_WINDOW_CLOSED`".

    Design: Corner/validations/corner_submit_after_certification_deadline_rejected
    """
    scenario = fx.build_claim_scenario(
        client,
        plan_year_overrides={"certification_deadline": "2026-06-30T23:59:59Z"},
    )

    response = client.submit_certification(
        scenario["certification_id"], None, scenario["employee_headers"]
    )
    validate_error(response, ApiErrorId.CERTIFICATION_WINDOW_CLOSED.value, 422)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert claim["status"] == "DRAFT"
    assert_cents(claim["certified_total_cents"], 30_000, "certified_total_cents")

    employee = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(employee["remaining_qslp_space_cents"], 2_280_000, "remaining space")


def test_terminated_employee_cannot_submit(client):
    """
    A terminated participant may no longer submit the annual claim.

    PRD: "the participant not to be `TERMINATED`, otherwise
    `ERR_EMPLOYEE_NOT_ELIGIBLE`".

    PRD: "It sets `termination_date` to the supplied `effective_date` and then
    triggers the longest cascade in the system".

    Design: Corner/validations/corner_terminated_employee_cannot_submit
    """
    scenario = fx.build_claim_scenario(client)

    terminated = fx.terminate_employee(
        client, scenario["employee_id"], "2026-07-01T00:00:00Z"
    )
    assert terminated["employment_status"] == "TERMINATED"
    assert_instant_equals(
        terminated["termination_date"], "2026-07-01T00:00:00Z", "termination_date"
    )

    response = client.submit_certification(
        scenario["certification_id"], None, scenario["employee_headers"]
    )
    validate_error(response, ApiErrorId.EMPLOYEE_NOT_ELIGIBLE.value, 422)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert claim["status"] == "DRAFT"

    listing = client.list_forfeiture_records(
        ADMIN_HEADERS, {"employee_id": scenario["employee_id"]}
    )
    records, meta = validate_paginated(listing)
    assert len(records) == 0
    assert meta["total_count"] == 0


def test_stale_employee_version_then_reread_succeeds(client):
    """
    A claim opened from a stale employee snapshot is refused until the client re-reads.

    PRD: "If it does not equal that employee's current `version`, the create is
    rejected with `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412)."

    PRD: "or whenever a payroll line changes the employee's remaining statutory
    space, so a mismatch means the submitting client's view of eligibility is stale."

    Design: Corner/cross-cutting complexity layers/corner_occ_stale_employee_version_then_reread_succeeds
    """
    plan_year = fx.setup_open_plan_year(client)
    employee = fx.create_employee(client)
    first_period = fx.create_payroll_period(client, plan_year["id"], 1)
    fx.post_contribution_record(client, employee["id"], first_period["id"])

    stale = fx.refresh_employee(client, employee["id"])
    assert_cents(stale["remaining_qslp_space_cents"], 2_280_000, "remaining space before")
    stale_version = stale["version"]

    second_period = fx.create_payroll_period(client, plan_year["id"], 2)
    fx.post_contribution_record(
        client, employee["id"], second_period["id"], 1_000_000, 15_000
    )

    fresh = fx.refresh_employee(client, employee["id"])
    assert fresh["version"] > stale_version
    assert_cents(fresh["remaining_qslp_space_cents"], 2_265_000, "remaining space after")

    headers = fx.make_employee_headers(employee["id"])
    rejected = client.create_loan_certification(
        f.loan_certification_payload(employee["id"], plan_year["id"], stale_version), headers
    )
    validate_error(rejected, ApiErrorId.STALE_EMPLOYEE_VERSION.value, 412)

    accepted = client.create_loan_certification(
        f.loan_certification_payload(employee["id"], plan_year["id"], fresh["version"]),
        headers,
    )
    claim = validate_success(accepted, 201)
    assert claim["status"] == "DRAFT"

    listing = client.list_loan_certifications(ADMIN_HEADERS, {"employee_id": employee["id"]})
    claims, meta = validate_paginated(listing)
    assert len(claims) == 1
    assert meta["total_count"] == 1


def test_qslp_space_threshold_at_exact_statutory_exhaustion(client):
    """
    Exactly zero remaining space blocks a submit while a single cent lets it through.

    PRD: "floors the result at zero, and demands that it be strictly greater than
    zero; a result of zero is rejected with `ERR_QSLP_SPACE_EXHAUSTED`."

    PRD: "the remaining space is that plan year's `annual_deferral_limit_cents` less
    the employee's `ytd_deferral_cents` less the reserved amount, floored at zero."

    Design: Corner/cross-cutting complexity layers/corner_qslp_space_threshold_at_exact_statutory_exhaustion
    """
    plan_year = fx.setup_open_plan_year(client)
    assert_cents(
        plan_year["annual_deferral_limit_cents"],
        DEFAULT_ANNUAL_DEFERRAL_LIMIT_CENTS,
        "annual_deferral_limit_cents",
    )
    fx.setup_effective_amendment(client, plan_year["id"])
    period = fx.create_payroll_period(client, plan_year["id"], 3)

    exhausted = fx.create_employee(client, external_id="E-EXHAUSTED")
    one_cent_left = fx.create_employee(client, external_id="E-ONE-CENT")

    fx.post_contribution_record(
        client, exhausted["id"], period["id"], 10_000_000, 2_300_000
    )
    fx.post_contribution_record(
        client, one_cent_left["id"], period["id"], 10_000_000, 2_299_999
    )

    exhausted_account = fx.setup_verified_loan_account(client, exhausted)
    one_cent_account = fx.setup_verified_loan_account(client, one_cent_left)

    exhausted_claim = fx.open_certification(client, exhausted, plan_year["id"])
    fx.add_certification_line(
        client, exhausted_claim["id"], exhausted, exhausted_account["id"], amount_cents=30_000
    )
    one_cent_claim = fx.open_certification(client, one_cent_left, plan_year["id"])
    fx.add_certification_line(
        client,
        one_cent_claim["id"],
        one_cent_left,
        one_cent_account["id"],
        amount_cents=30_000,
    )

    assert_cents(
        fx.refresh_employee(client, exhausted["id"])["remaining_qslp_space_cents"],
        0,
        "exhausted remaining space",
    )
    assert_cents(
        fx.refresh_employee(client, one_cent_left["id"])["remaining_qslp_space_cents"],
        1,
        "one-cent remaining space",
    )

    refused = client.submit_certification(
        exhausted_claim["id"], None, fx.make_employee_headers(exhausted["id"])
    )
    validate_error(refused, ApiErrorId.QSLP_SPACE_EXHAUSTED.value, 422)
    assert fx.refresh_certification(client, exhausted_claim["id"])["status"] == "DRAFT"

    submitted = validate_success(
        client.submit_certification(
            one_cent_claim["id"], None, fx.make_employee_headers(one_cent_left["id"])
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert_cents(submitted["certified_total_cents"], 30_000, "certified_total_cents")
    assert_cents(
        fx.refresh_employee(client, one_cent_left["id"])["remaining_qslp_space_cents"],
        0,
        "one-cent remaining space after submit",
    )
