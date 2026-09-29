"""Standing up a plan year, amending the plan document, and the period calendar."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_instant_equals,
    assert_plan_year_shape,
    assert_ratio_4dp,
)
from test_helpers.constants import (
    DEFAULT_ANNUAL_DEFERRAL_LIMIT_CENTS,
    DEFAULT_COMPENSATION_CAP_CENTS,
    DEFAULT_HCE_PRIOR_COMP_THRESHOLD_CENTS,
    DEFAULT_LEAVE_MERGE_BUFFER_DAYS,
    DEFAULT_TIER1_MATCH_RATE,
    DEFAULT_TIER1_PCT,
    DEFAULT_TIER2_MATCH_RATE,
    DEFAULT_TIER2_PCT,
    DEFAULT_UNPAID_LEAVE_DAY_CAP,
)
from test_helpers.test_users import ADMIN_HEADERS, PAYROLL_HEADERS


def test_create_plan_year_applies_declared_defaults(client):
    """
    A plan year created with only its window fields falls back to every declared default.

    PRD: "The economic parameters `compensation_cap_cents`,
    `annual_deferral_limit_cents`, `hce_prior_comp_threshold_cents`, `tier1_pct`,
    `tier1_match_rate`, `tier2_pct`, and `tier2_match_rate` are all optional and
    fall back to the defaults given in §2.6."

    PRD: "A newly created plan year is in `DRAFT` with `version` 1,
    `true_up_completed` false, `reopened_count` zero, and all four derived
    rollups at zero."

    Design: Corner/entities/corner_create_plan_year_applies_declared_defaults
    """
    response = client.create_plan_year(f.plan_year_payload(), ADMIN_HEADERS)
    plan_year = validate_success(response, 201)

    assert_plan_year_shape(plan_year)
    assert plan_year["status"] == "DRAFT"
    assert plan_year["version"] == 1

    assert_cents(
        plan_year["compensation_cap_cents"],
        DEFAULT_COMPENSATION_CAP_CENTS,
        "compensation_cap_cents",
    )
    assert_cents(
        plan_year["annual_deferral_limit_cents"],
        DEFAULT_ANNUAL_DEFERRAL_LIMIT_CENTS,
        "annual_deferral_limit_cents",
    )
    assert_cents(
        plan_year["hce_prior_comp_threshold_cents"],
        DEFAULT_HCE_PRIOR_COMP_THRESHOLD_CENTS,
        "hce_prior_comp_threshold_cents",
    )
    assert float(plan_year["tier1_pct"]) == DEFAULT_TIER1_PCT
    assert float(plan_year["tier1_match_rate"]) == DEFAULT_TIER1_MATCH_RATE
    assert float(plan_year["tier2_pct"]) == DEFAULT_TIER2_PCT
    assert float(plan_year["tier2_match_rate"]) == DEFAULT_TIER2_MATCH_RATE

    assert plan_year["nondiscrimination_test_method"] == "CURRENT_YEAR"
    assert_ratio_4dp(plan_year["prior_year_nhce_acp"], 0.0000, "prior_year_nhce_acp")
    assert plan_year["unpaid_leave_day_cap"] == DEFAULT_UNPAID_LEAVE_DAY_CAP
    assert plan_year["leave_merge_buffer_days"] == DEFAULT_LEAVE_MERGE_BUFFER_DAYS

    assert plan_year["true_up_completed"] is False
    assert plan_year["reopened_count"] == 0
    assert_cents(plan_year["total_deferral_match_funded_cents"], 0, "deferral rollup")
    assert_cents(plan_year["total_qslp_match_funded_cents"], 0, "qslp rollup")
    assert_cents(plan_year["forfeiture_balance_cents"], 0, "forfeiture balance")
    assert plan_year["accepted_certification_count"] == 0


def test_second_open_plan_year_rejected(client):
    """
    Opening a second plan year while one is already open is refused.

    PRD: "No other plan year may already be in `OPEN`, or the transition is
    rejected with `ERR_MULTIPLE_OPEN_PLAN_YEARS`".

    Design: Corner/validations/corner_second_open_plan_year_rejected
    """
    fx.setup_open_plan_year(client, year=2026)
    later = fx.create_plan_year(
        client,
        year=2027,
        period_start="2027-01-01T00:00:00Z",
        period_end="2027-12-31T23:59:59Z",
        certification_window_open="2027-01-01T00:00:00Z",
        certification_deadline="2027-12-31T23:59:59Z",
    )

    response = client.set_plan_year_status(
        later["id"], f.plan_year_status_payload("OPEN"), ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.MULTIPLE_OPEN_PLAN_YEARS.value, 409)

    unchanged = fx.refresh_plan_year(client, later["id"])
    assert unchanged["status"] == "DRAFT"


def test_amendment_notice_sent_directly_from_drafted_rejected(client):
    """
    An amendment cannot skip adoption on the way to participant notice.

    PRD: "The amendment begins in `DRAFTED` and its `status` moves through
    `ADOPTED`, `NOTICE_SENT`, and finally `EFFECTIVE`".

    PRD: "a destination that does not match the amendment's current state is
    rejected with `ERR_AMENDMENT_STATE_INVALID`".

    Design: Corner/state_machines/corner_amendment_notice_sent_directly_from_drafted_rejected
    """
    plan_year = fx.setup_open_plan_year(client)
    amendment = fx.create_amendment(client, plan_year["id"])
    assert amendment["status"] == "DRAFTED"

    response = client.set_amendment_status(
        amendment["id"], f.amendment_status_payload("NOTICE_SENT"), ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.AMENDMENT_STATE_INVALID.value, 409)

    unchanged = validate_success(client.get_plan_amendment(amendment["id"], ADMIN_HEADERS))
    assert unchanged["status"] == "DRAFTED"
    assert unchanged["notice_sent_at"] is None
    assert unchanged["adopted_at"] is None


def test_amendment_effective_before_effective_date_rejected(client):
    """
    An amendment may not be declared effective before its effective date arrives.

    PRD: "`NOTICE_SENT` → `EFFECTIVE` requires the current logical clock to be at
    or after the amendment's `effective_date`, and is rejected with
    `ERR_AMENDMENT_EFFECTIVE_DATE_FUTURE` when the date has not yet arrived".

    PRD: "It stamps `effective_at`, which is null before it, and it is the event
    that unblocks claim acceptance for that plan year."

    Design: Corner/state_machines/corner_amendment_effective_before_effective_date_rejected
    """
    plan_year = fx.setup_open_plan_year(client)
    amendment = fx.setup_amendment_at(
        client, plan_year["id"], "NOTICE_SENT", effective_date="2026-12-01T00:00:00Z"
    )
    assert amendment["status"] == "NOTICE_SENT"
    assert amendment["effective_at"] is None

    early = client.set_amendment_status(
        amendment["id"], f.amendment_status_payload("EFFECTIVE"), ADMIN_HEADERS
    )
    validate_error(early, ApiErrorId.AMENDMENT_EFFECTIVE_DATE_FUTURE.value, 422)

    fx.set_clock(client, "2026-12-02T00:00:00Z")
    later = client.set_amendment_status(
        amendment["id"], f.amendment_status_payload("EFFECTIVE"), ADMIN_HEADERS
    )
    effective = validate_success(later)
    assert effective["status"] == "EFFECTIVE"
    assert_instant_equals(effective["effective_at"], "2026-12-02T00:00:00Z", "effective_at")


def test_duplicate_period_number_rejected(client):
    """
    Two payroll periods of one plan year cannot share an ordinal.

    PRD: "A duplicate ordinal inside the same plan year is rejected with
    `ERR_DUPLICATE_PERIOD_RESOURCE`."

    Design: Corner/errors/corner_duplicate_period_number_rejected
    """
    plan_year = fx.setup_open_plan_year(client)
    fx.create_payroll_period(client, plan_year["id"], 3)

    response = client.create_payroll_period(
        f.payroll_period_payload(plan_year["id"], 3), PAYROLL_HEADERS
    )
    validate_error(response, ApiErrorId.DUPLICATE_PERIOD_RESOURCE.value, 409)

    listing = client.list_payroll_periods(PAYROLL_HEADERS, {"plan_year_id": plan_year["id"]})
    periods, meta = validate_paginated(listing)
    assert len(periods) == 1
    assert meta["total_count"] == 1


def test_payroll_line_to_closed_period_rejected(client):
    """
    A payroll line cannot be posted into a period that is no longer open.

    PRD: "an attempt is rejected with `ERR_PERIOD_ALREADY_FUNDED` — the same code
    that rejects a payroll line posted to a period that is not `OPEN`."

    PRD: "After the close no further payroll line may be created for the period,
    and the period's funding batch becomes transmittable."

    Design: Corner/errors/corner_payroll_line_to_closed_period_rejected
    """
    plan_year = fx.setup_open_plan_year(client)
    employee = fx.create_employee(client)
    period = fx.create_payroll_period(client, plan_year["id"], 3)
    closed = fx.close_payroll_period(client, period["id"])
    assert closed["status"] == "CLOSED"

    response = client.create_contribution_record(
        f.contribution_record_payload(employee["id"], period["id"]), PAYROLL_HEADERS
    )
    validate_error(response, ApiErrorId.PERIOD_ALREADY_FUNDED.value, 409)

    after = validate_success(client.get_payroll_period(period["id"], PAYROLL_HEADERS))
    assert_cents(after["total_eligible_compensation_cents"], 0, "period compensation")
    assert_cents(after["total_deferral_match_cents"], 0, "period deferral match")

    employee_after = fx.refresh_employee(client, employee["id"])
    assert_cents(employee_after["ytd_deferral_cents"], 0, "ytd_deferral_cents")
