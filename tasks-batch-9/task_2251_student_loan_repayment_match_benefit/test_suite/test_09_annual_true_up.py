"""The annual true-up: the second answer to the match question, and its pinned order."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_allocation_shape, assert_cents
from test_helpers.test_users import ADMIN_HEADERS


def _three_period_claim(client):
    """An accepted 30000-cent claim over three identical periods, batched on period one."""
    return fx.setup_accepted_claim(
        client,
        period_numbers=(1, 2, 3),
        batch_period_numbers=(1,),
    )


# ---------------------------------------------------------------------------
# The two variants of the same match question
# ---------------------------------------------------------------------------


def test_mirror_and_true_up_variants_diverge_on_identical_certified_dollars(client):
    """
    The same certified dollars pay 20000 period by period and 30000 on annual totals.

    PRD: "The eligible dollars are then poured into the leftover tier space period by
    period — the `PAY_PERIOD_MIRROR` variant, so named because it mirrors the
    elective-deferral match period by period rather than settling the year as a whole."

    PRD: "It ignores period boundaries entirely, recomputes the combined annual
    entitlement on annual compensation and annual contributions, and pays or recoups
    the difference against what the mirror variant already funded — which is how
    certified dollars stranded by period-level fluctuation are recovered."

    Design: Difficulty/dual_variant_calc/qslp_mirror_vs_annual_true_up_divergence
    """
    scenario = _three_period_claim(client)
    claim = scenario["certification"]

    assert_cents(claim["eligible_total_cents"], 30_000, "eligible_total_cents")
    assert_cents(claim["matched_total_cents"], 20_000, "matched_total_cents")

    mirror = scenario["allocation"]
    assert mirror["allocation_type"] == "MIRROR"
    assert_cents(mirror["amount_cents"], 20_000, "mirror amount_cents")
    assert_cents(mirror["tier1_applied_cents"], 10_000, "mirror tier1_applied_cents")
    assert_cents(mirror["tier2_applied_cents"], 20_000, "mirror tier2_applied_cents")

    fx.lock_plan_year(client, scenario["plan_year_id"])
    summary = validate_success(
        client.run_true_up(
            scenario["plan_year_id"], {"employee_id": scenario["employee_id"]}, ADMIN_HEADERS
        )
    )

    assert summary["true_up_allocation_count"] == 1
    assert_cents(summary["total_true_up_cents"], 10_000, "total_true_up_cents")
    assert summary["recoupment_count"] == 0

    plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year["total_qslp_match_funded_cents"], 30_000, "plan year qslp total")
    assert plan_year["true_up_completed"] is True


def test_true_up_allocation_belongs_to_no_claim_and_no_period(client):
    """
    The true-up row is a distinct allocation variant carrying neither claim nor period.

    PRD: "When the delta is strictly positive, the run creates a match allocation with
    `allocation_type` `TRUE_UP`, `amount_cents` equal to the delta, and both
    `certification_id` and `payroll_period_id` null, because a true-up allocation
    belongs to no single claim and no single period; its `tier1_applied_cents` and
    `tier2_applied_cents` are zero."

    Design: Difficulty/dual_variant_calc/qslp_mirror_vs_annual_true_up_divergence
    """
    scenario = _three_period_claim(client)
    fx.lock_plan_year(client, scenario["plan_year_id"])
    validate_success(
        client.run_true_up(
            scenario["plan_year_id"], {"employee_id": scenario["employee_id"]}, ADMIN_HEADERS
        )
    )

    allocations = fx.allocations_of_plan_year(client, scenario["plan_year_id"])
    by_type = {row["allocation_type"]: row for row in allocations}
    assert len(allocations) == 2
    assert set(by_type) == {"MIRROR", "TRUE_UP"}

    true_up = by_type["TRUE_UP"]
    assert_allocation_shape(true_up)
    assert_cents(true_up["amount_cents"], 10_000, "true-up amount_cents")
    assert true_up["certification_id"] is None
    assert true_up["payroll_period_id"] is None
    assert_cents(true_up["tier1_applied_cents"], 0, "true-up tier1_applied_cents")
    assert_cents(true_up["tier2_applied_cents"], 0, "true-up tier2_applied_cents")


# ---------------------------------------------------------------------------
# The pinned evaluation order of the run
# ---------------------------------------------------------------------------


def test_true_up_snapshot_excludes_the_row_it_is_about_to_write(client):
    """
    The delta is measured against the pre-run funded match, not against its own output.

    PRD: "The funded QSLP match is the sum of `amount_cents` over the participant's
    match allocations in this plan year whose `funding_status` is `SCHEDULED` or
    `FUNDED` **and** whose `created_at` is strictly earlier than the run's start
    instant — which excludes reversed allocations and also excludes any row this very
    run is about to write."

    PRD: "The run captures the current logical clock as its start instant and then,
    for each participant, executes four steps in exactly this order."

    Design: Difficulty/combinatorial_formula/true_up_evaluation_order_pinned
    """
    scenario = _three_period_claim(client)

    before = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(before["total_qslp_match_funded_cents"], 20_000, "funded before the run")
    assert before["true_up_completed"] is False

    fx.lock_plan_year(client, scenario["plan_year_id"])
    summary = validate_success(
        client.run_true_up(
            scenario["plan_year_id"], {"employee_id": scenario["employee_id"]}, ADMIN_HEADERS
        )
    )

    assert_cents(summary["total_true_up_cents"], 10_000, "total_true_up_cents")
    assert summary["true_up_allocation_count"] == 1
    assert summary["recoupment_count"] == 0

    after = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(after["total_qslp_match_funded_cents"], 30_000, "funded after the run")
    assert after["true_up_completed"] is True


def test_second_true_up_run_is_refused_and_writes_nothing(client):
    """
    The completion flag makes the run idempotent by refusal, not by repetition.

    PRD: "The run is refused with `ERR_PLAN_YEAR_NOT_LOCKED` unless the plan year is
    `LOCKED`, and with `ERR_TRUE_UP_ALREADY_RUN` when `true_up_completed` is already
    true."

    PRD: "Completing the run sets `true_up_completed` to true, recomputes the plan
    year's `total_qslp_match_funded_cents`, moves every nondiscrimination test of the
    plan year standing in `PASSED` or `FAILED` to `STALE`, increments the plan year's
    `version` by one, and increments the `version` of each processed employee by one."

    Design: Difficulty/combinatorial_formula/true_up_evaluation_order_pinned
    """
    scenario = _three_period_claim(client)
    fx.lock_plan_year(client, scenario["plan_year_id"])

    first = validate_success(
        client.run_true_up(
            scenario["plan_year_id"], {"employee_id": scenario["employee_id"]}, ADMIN_HEADERS
        )
    )
    assert first["true_up_allocation_count"] == 1

    second = client.run_true_up(
        scenario["plan_year_id"], {"employee_id": scenario["employee_id"]}, ADMIN_HEADERS
    )
    validate_error(second, ApiErrorId.TRUE_UP_ALREADY_RUN.value, 409)

    allocations = fx.allocations_of_plan_year(client, scenario["plan_year_id"])
    true_ups = [row for row in allocations if row["allocation_type"] == "TRUE_UP"]
    assert len(true_ups) == 1
    assert_cents(true_ups[0]["amount_cents"], 10_000, "true-up amount_cents")

    plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year["total_qslp_match_funded_cents"], 30_000, "plan year qslp total")


# ---------------------------------------------------------------------------
# The lock precondition
# ---------------------------------------------------------------------------


def test_true_up_requires_locked_plan_year(client):
    """
    The annual true-up is unavailable while the plan year is still open.

    PRD: "Once the plan year is `LOCKED`, the `BenefitsAdministrator` runs the annual
    true-up — the `ANNUAL_TRUE_UP` variant of the match, and the second and final
    answer to how much QSLP match each participant is owed."

    PRD: "The run is refused with `ERR_PLAN_YEAR_NOT_LOCKED` unless the plan year is
    `LOCKED`, and with `ERR_TRUE_UP_ALREADY_RUN` when `true_up_completed` is already
    true."

    Design: Corner/endpoints/corner_true_up_requires_locked_plan_year
    """
    plan_year = fx.setup_open_plan_year(client)
    assert plan_year["status"] == "OPEN"

    employee = fx.create_employee(client, external_id="E-TUGATE")
    period = fx.create_payroll_period(client, plan_year["id"], 1)
    fx.post_contribution_record(client, employee["id"], period["id"])

    response = client.run_true_up(
        plan_year["id"], {"employee_id": employee["id"]}, ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.PLAN_YEAR_NOT_LOCKED.value, 409)

    after = fx.refresh_plan_year(client, plan_year["id"])
    assert after["true_up_completed"] is False

    allocations = fx.allocations_of_plan_year(client, plan_year["id"])
    assert len(allocations) == 0
