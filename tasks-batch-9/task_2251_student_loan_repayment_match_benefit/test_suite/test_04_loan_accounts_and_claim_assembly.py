"""Registering loans, opening the annual claim, and the certified payment lines."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_append_only_row,
    assert_cents,
    assert_certification_line_shape,
    assert_certification_shape,
)
from test_helpers.test_users import ADMIN_HEADERS


# ---------------------------------------------------------------------------
# Half-open covered windows
# ---------------------------------------------------------------------------


def test_touching_covered_windows_are_both_accepted(client):
    """
    Two certified windows that merely touch do not intersect and are both accepted.

    PRD: "Because the windows are half-open, two lines that merely touch — where
    the earlier window's end instant equals the later window's start instant — do
    not intersect and are both accepted."

    Design: Difficulty/resource_temporal_overlap/covered_period_half_open_adjacent_ok_overlap_rejected
    """
    scenario = fx.build_claim_scenario(
        client,
        line_specs=[
            {
                "payment_date": "2026-03-15T00:00:00Z",
                "amount_cents": 10_000,
                "covered_period_start": "2026-03-01T00:00:00Z",
                "covered_period_end": "2026-04-01T00:00:00Z",
            }
        ],
    )

    adjacent = fx.add_certification_line(
        client,
        scenario["certification_id"],
        scenario["employee"],
        scenario["loan_account_id"],
        payment_date="2026-04-15T00:00:00Z",
        amount_cents=10_000,
        covered_period_start="2026-04-01T00:00:00Z",
        covered_period_end="2026-05-01T00:00:00Z",
    )
    assert_certification_line_shape(adjacent)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert_cents(claim["certified_total_cents"], 20_000, "certified_total_cents")

    listing = client.list_certification_lines_of(
        scenario["certification_id"], scenario["employee_headers"]
    )
    lines, meta = validate_paginated(listing)
    assert len(lines) == 2
    assert meta["total_count"] == 2


def test_intersecting_covered_window_is_rejected(client):
    """
    A window that genuinely intersects an already certified window is refused.

    PRD: "the new line's half-open window must not intersect the window of any
    existing line on the *same* `loan_account_id` belonging to a certification whose
    status is `DRAFT`, `SUBMITTED`, `ACCEPTED`, or `AUDIT_HOLD`, and an intersection
    is rejected with `ERR_COVERED_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/covered_period_half_open_adjacent_ok_overlap_rejected
    """
    scenario = fx.build_claim_scenario(
        client,
        line_specs=[
            {
                "payment_date": "2026-03-15T00:00:00Z",
                "amount_cents": 10_000,
                "covered_period_start": "2026-03-01T00:00:00Z",
                "covered_period_end": "2026-04-01T00:00:00Z",
            },
            {
                "payment_date": "2026-04-15T00:00:00Z",
                "amount_cents": 10_000,
                "covered_period_start": "2026-04-01T00:00:00Z",
                "covered_period_end": "2026-05-01T00:00:00Z",
            },
        ],
    )

    response = client.add_certification_line(
        scenario["certification_id"],
        f.certification_line_payload(
            scenario["loan_account_id"],
            payment_date="2026-04-05T00:00:00Z",
            amount_cents=10_000,
            covered_period_start="2026-03-25T00:00:00Z",
            covered_period_end="2026-04-10T00:00:00Z",
        ),
        scenario["employee_headers"],
    )
    validate_error(response, ApiErrorId.COVERED_PERIOD_OVERLAP.value, 409)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert_cents(claim["certified_total_cents"], 20_000, "certified_total_cents")

    listing = client.list_certification_lines_of(
        scenario["certification_id"], scenario["employee_headers"]
    )
    lines, meta = validate_paginated(listing)
    assert len(lines) == 2
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Line rule precedence: payment date outranks window overlap
# ---------------------------------------------------------------------------


def test_payment_date_outside_plan_year_outranks_covered_period_overlap(client):
    """
    A line that is both dated outside the plan year and overlapping reports the date fault.

    PRD: "When several rules could reject the same request, the rule with the
    smallest ordinal below decides the response."

    PRD: "Payment date must fall inside the plan year — `ERR_PAYMENT_DATE_OUTSIDE_PLAN_YEAR`,
    on `POST /loan-certifications/{certification_id}/lines`."

    Design: Difficulty/priority_pair_validation_conflict/payment_date_outside_year_beats_period_overlap
    """
    scenario = fx.build_claim_scenario(
        client,
        line_specs=[
            {
                "payment_date": "2026-03-15T00:00:00Z",
                "amount_cents": 30_000,
                "covered_period_start": "2026-03-01T00:00:00Z",
                "covered_period_end": "2026-04-01T00:00:00Z",
            }
        ],
    )

    response = client.add_certification_line(
        scenario["certification_id"],
        f.certification_line_payload(
            scenario["loan_account_id"],
            payment_date="2025-12-15T00:00:00Z",
            amount_cents=10_000,
            covered_period_start="2026-03-10T00:00:00Z",
            covered_period_end="2026-03-20T00:00:00Z",
        ),
        scenario["employee_headers"],
    )
    validate_error(response, ApiErrorId.PAYMENT_DATE_OUTSIDE_PLAN_YEAR.value, 422)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert_cents(claim["certified_total_cents"], 30_000, "certified_total_cents")

    listing = client.list_certification_lines_of(
        scenario["certification_id"], scenario["employee_headers"]
    )
    lines, meta = validate_paginated(listing)
    assert len(lines) == 1
    assert meta["total_count"] == 1


def test_same_overlapping_window_reports_overlap_once_the_date_is_valid(client):
    """
    With the payment date repaired the very same window reports the overlap conflict.

    PRD: "Covered windows must not overlap — `ERR_COVERED_PERIOD_OVERLAP`, on
    `POST /loan-certifications/{certification_id}/lines`."

    PRD: "and it must be at or before the current logical clock, or the line is
    rejected with `ERR_PAYMENT_DATE_IN_FUTURE`."

    Design: Difficulty/priority_pair_validation_conflict/payment_date_outside_year_beats_period_overlap
    """
    scenario = fx.build_claim_scenario(
        client,
        line_specs=[
            {
                "payment_date": "2026-03-15T00:00:00Z",
                "amount_cents": 30_000,
                "covered_period_start": "2026-03-01T00:00:00Z",
                "covered_period_end": "2026-04-01T00:00:00Z",
            }
        ],
    )

    outside = client.add_certification_line(
        scenario["certification_id"],
        f.certification_line_payload(
            scenario["loan_account_id"],
            payment_date="2025-12-15T00:00:00Z",
            amount_cents=10_000,
            covered_period_start="2026-03-10T00:00:00Z",
            covered_period_end="2026-03-20T00:00:00Z",
        ),
        scenario["employee_headers"],
    )
    validate_error(outside, ApiErrorId.PAYMENT_DATE_OUTSIDE_PLAN_YEAR.value, 422)

    inside = client.add_certification_line(
        scenario["certification_id"],
        f.certification_line_payload(
            scenario["loan_account_id"],
            payment_date="2026-03-18T00:00:00Z",
            amount_cents=10_000,
            covered_period_start="2026-03-10T00:00:00Z",
            covered_period_end="2026-03-20T00:00:00Z",
        ),
        scenario["employee_headers"],
    )
    validate_error(inside, ApiErrorId.COVERED_PERIOD_OVERLAP.value, 409)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert_cents(claim["certified_total_cents"], 30_000, "certified_total_cents")


# ---------------------------------------------------------------------------
# Loan account and claim corners
# ---------------------------------------------------------------------------


def test_create_loan_account_last4_type_constraint_rejected(client):
    """
    A loan account whose last four are not four digits is not well formed.

    PRD: "`account_last4` must be exactly four digits".

    Design: Corner/entities/corner_create_loan_account_last4_type_constraint_rejected
    """
    fx.setup_open_plan_year(client)
    employee = fx.create_employee(client)
    headers = fx.make_employee_headers(employee["id"])

    response = client.create_loan_account(
        f.loan_account_payload(employee["id"], account_last4="12A"), headers
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

    listing = client.list_loan_accounts(ADMIN_HEADERS, {"employee_id": employee["id"]})
    accounts, meta = validate_paginated(listing)
    assert len(accounts) == 0
    assert meta["total_count"] == 0


def test_certification_line_is_immutable_and_versionless(client):
    """
    A certified payment line is an audit row without a version or an update stamp.

    PRD: "Four collections are append-only audit rows and are deliberately leaner:
    leave events, certification lines, forfeiture records, and correction
    adjustments carry only `id` and `created_at`."

    PRD: "For these four, `updated_at` and `version` are absent from the resource
    entirely — not null, not zero, simply not present."

    Design: Corner/entities/corner_certification_line_is_immutable_and_versionless
    """
    scenario = fx.build_claim_scenario(
        client, line_specs=[{"amount_cents": 10_000}]
    )
    created = scenario["lines"][0]
    assert_append_only_row(created, "CertificationLine")

    read_back = validate_success(
        client.get_certification_line(created["id"], scenario["employee_headers"])
    )
    assert_certification_line_shape(read_back)
    assert read_back["id"] == created["id"]
    assert_cents(read_back["amount_cents"], 10_000, "amount_cents")
    assert "version" not in read_back
    assert "updated_at" not in read_back


def test_new_certification_starts_in_draft(client):
    """
    A freshly opened annual claim carries no decision, no money and no returns.

    PRD: "A new claim begins in `DRAFT` with `submitted_at`, `decided_at`, and
    `accepted_by_user_id` all null, `return_count` at zero,
    `certified_total_cents`, `eligible_total_cents`, `matched_total_cents`, and
    `unmatched_eligible_cents` all zero, `capped_by_statutory_room` false, and
    `audit_hold_reason` and `void_reason` null."

    Design: Corner/state_machines/corner_new_certification_starts_in_draft
    """
    plan_year = fx.setup_open_plan_year(client)
    fx.setup_effective_amendment(client, plan_year["id"])
    employee = fx.create_employee(client)
    headers = fx.make_employee_headers(employee["id"])

    response = client.create_loan_certification(
        f.loan_certification_payload(employee["id"], plan_year["id"], employee["version"]),
        headers,
    )
    claim = validate_success(response, 201)

    assert_certification_shape(claim)
    assert claim["status"] == "DRAFT"
    assert_cents(claim["certified_total_cents"], 0, "certified_total_cents")
    assert_cents(claim["eligible_total_cents"], 0, "eligible_total_cents")
    assert_cents(claim["matched_total_cents"], 0, "matched_total_cents")
    assert_cents(claim["unmatched_eligible_cents"], 0, "unmatched_eligible_cents")
    assert claim["return_count"] == 0
    assert claim["submitted_at"] is None
    assert claim["decided_at"] is None
    assert claim["accepted_by_user_id"] is None
    assert claim["capped_by_statutory_room"] is False
    assert claim["audit_hold_reason"] is None
    assert claim["void_reason"] is None


def test_duplicate_open_certification_rejected(client):
    """
    A participant may not hold two open claims for the same plan year.

    PRD: "no other certification of the same employee and plan year may stand in
    `DRAFT` or `SUBMITTED`, and when `supersedes_certification_id` is supplied it
    must name a certification of the same employee and plan year whose status is
    `ACCEPTED`. Either failure is reported as `ERR_DUPLICATE_OPEN_CERTIFICATION`."

    Design: Corner/validations/corner_duplicate_open_certification_rejected
    """
    scenario = fx.build_claim_scenario(client, line_specs=[])
    employee = fx.refresh_employee(client, scenario["employee_id"])

    response = client.create_loan_certification(
        f.loan_certification_payload(
            scenario["employee_id"], scenario["plan_year_id"], employee["version"]
        ),
        scenario["employee_headers"],
    )
    validate_error(response, ApiErrorId.DUPLICATE_OPEN_CERTIFICATION.value, 409)

    listing = client.list_loan_certifications(
        ADMIN_HEADERS, {"employee_id": scenario["employee_id"]}
    )
    claims, meta = validate_paginated(listing)
    assert len(claims) == 1
    assert meta["total_count"] == 1
    assert claims[0]["status"] == "DRAFT"


def test_certified_payment_date_in_future_rejected(client):
    """
    A payment dated after the logical clock cannot be certified yet.

    PRD: "and it must be at or before the current logical clock, or the line is
    rejected with `ERR_PAYMENT_DATE_IN_FUTURE`."

    PRD: "Before any client sets it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/validations/corner_certified_payment_date_in_future_rejected
    """
    scenario = fx.build_claim_scenario(client, line_specs=[])

    response = client.add_certification_line(
        scenario["certification_id"],
        f.certification_line_payload(
            scenario["loan_account_id"],
            payment_date="2026-09-15T00:00:00Z",
            amount_cents=30_000,
            covered_period_start="2026-09-01T00:00:00Z",
            covered_period_end="2026-10-01T00:00:00Z",
        ),
        scenario["employee_headers"],
    )
    validate_error(response, ApiErrorId.PAYMENT_DATE_IN_FUTURE.value, 422)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert_cents(claim["certified_total_cents"], 0, "certified_total_cents")

    listing = client.list_certification_lines_of(
        scenario["certification_id"], scenario["employee_headers"]
    )
    lines, meta = validate_paginated(listing)
    assert len(lines) == 0
    assert meta["total_count"] == 0


def test_line_referencing_unverified_loan_rejected(client):
    """
    A payment against a loan account that was never verified cannot be certified.

    PRD: "The referenced loan account must be `VERIFIED`, or the line is rejected
    with `ERR_LOAN_NOT_VERIFIED`."

    PRD: "The account is created with `status` `UNVERIFIED` and `evidence_ref` null."

    Design: Corner/errors/corner_line_referencing_unverified_loan_rejected
    """
    scenario = fx.build_claim_scenario(client, loan_status="UNVERIFIED", line_specs=[])
    assert scenario["loan_account"]["status"] == "UNVERIFIED"

    response = client.add_certification_line(
        scenario["certification_id"],
        f.certification_line_payload(scenario["loan_account_id"]),
        scenario["employee_headers"],
    )
    validate_error(response, ApiErrorId.LOAN_NOT_VERIFIED.value, 422)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert_cents(claim["certified_total_cents"], 0, "certified_total_cents")

    listing = client.list_certification_lines_of(
        scenario["certification_id"], scenario["employee_headers"]
    )
    lines, meta = validate_paginated(listing)
    assert len(lines) == 0
    assert meta["total_count"] == 0
