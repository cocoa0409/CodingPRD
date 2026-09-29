"""Termination: the vesting cliff, forfeiture records and the offset waterfall."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_append_only_row,
    assert_batch_net_identity,
    assert_cents,
    assert_forfeiture_record_shape,
    assert_ratio_4dp,
)
from test_helpers.constants import UNVESTED_SERVICE_MONTHS
from test_helpers.test_users import PAYROLL_HEADERS


# ---------------------------------------------------------------------------
# The two independent dimensions of an allocation
# ---------------------------------------------------------------------------


def test_funding_dimension_advances_without_touching_vesting(client):
    """
    Scheduling and then funding an allocation leaves its vesting dimension alone.

    PRD: "Every MIRROR allocation is created with `funding_status` `UNFUNDED` and
    `vesting_status` `UNVESTED`, and `vested_cents` and `forfeited_cents` at zero."

    PRD: "Funding leaves `vesting_status` entirely untouched — the two dimensions of
    an allocation evolve independently and neither gates the other."

    Design: Difficulty/non_linear_state_machine/allocation_parallel_funding_and_vesting_dimensions
    """
    scenario = fx.setup_accepted_claim(
        client,
        employee_overrides={"vesting_service_months": UNVESTED_SERVICE_MONTHS},
    )

    at_accept = fx.refresh_allocation(client, scenario["allocation_id"])
    assert at_accept["funding_status"] == "SCHEDULED"
    assert at_accept["vesting_status"] == "UNVESTED"
    assert_cents(at_accept["amount_cents"], 20_000, "amount_cents")
    assert_cents(at_accept["vested_cents"], 0, "vested_cents")
    assert_cents(at_accept["forfeited_cents"], 0, "forfeited_cents")

    fx.close_payroll_period(client, scenario["payroll_period_id"])
    fx.transmit_batch(client, scenario["funding_batch_id"])
    settled = fx.settle_batch(client, scenario["funding_batch_id"])
    assert settled["status"] == "SETTLED"

    after_settle = fx.refresh_allocation(client, scenario["allocation_id"])
    assert after_settle["funding_status"] == "FUNDED"
    assert after_settle["vesting_status"] == "UNVESTED"
    assert_cents(after_settle["vested_cents"], 0, "vested_cents after settle")

    period = validate_success(
        client.get_payroll_period(scenario["payroll_period_id"], PAYROLL_HEADERS)
    )
    assert period["status"] == "FUNDED"


def test_vesting_dimension_advances_without_disturbing_funding(client):
    """
    Terminating the participant forfeits a funded allocation without unfunding it.

    PRD: "The resulting `vesting_status` is `FULLY_VESTED` when `forfeited_cents` is
    zero, `FORFEITED` when `vested_cents` is zero, and `PARTIALLY_VESTED` otherwise."

    PRD: "`vested_pct` is 0.00 below 24 months, 0.40 from 24 through 35 months, 0.60
    from 36 through 47 months, 0.80 from 48 through 59 months, and 1.00 at 60 months
    or more."

    Design: Difficulty/non_linear_state_machine/allocation_parallel_funding_and_vesting_dimensions
    """
    scenario = fx.setup_settled_batch(
        client,
        employee_overrides={"vesting_service_months": UNVESTED_SERVICE_MONTHS},
    )

    before_termination = fx.refresh_allocation(client, scenario["allocation_id"])
    assert before_termination["funding_status"] == "FUNDED"
    assert before_termination["vesting_status"] == "UNVESTED"

    terminated = fx.terminate_employee(client, scenario["employee_id"])
    assert terminated["employment_status"] == "TERMINATED"
    assert_ratio_4dp(terminated["vested_pct"], 0.00, "vested_pct")

    after_termination = fx.refresh_allocation(client, scenario["allocation_id"])
    assert after_termination["funding_status"] == "FUNDED"
    assert after_termination["vesting_status"] == "FORFEITED"
    assert_cents(after_termination["vested_cents"], 0, "vested_cents")
    assert_cents(after_termination["forfeited_cents"], 20_000, "forfeited_cents")

    period = validate_success(
        client.get_payroll_period(scenario["payroll_period_id"], PAYROLL_HEADERS)
    )
    assert period["status"] == "FUNDED"


# ---------------------------------------------------------------------------
# The termination cascade
# ---------------------------------------------------------------------------


def test_terminate_employee_writes_the_forfeiture_record(client):
    """
    A wholly unvested allocation produces one forfeiture record naming its cause.

    PRD: "Whenever `forfeited_cents` is strictly greater than zero the system writes
    a **forfeiture record** carrying the `match_allocation_id`, the `employee_id`, the
    `plan_year_id` whose pool receives the money, the forfeited `amount_cents`, and a
    `reason_code` of `TERMINATION_UNVESTED` when `vested_cents` is zero or
    `TERMINATION_PARTIAL_VESTING` when some portion vested."

    Design: Difficulty/transitive_cascade/terminate_employee_forfeiture_cascade_depth4
    """
    scenario = fx.setup_accepted_claim(
        client,
        employee_overrides={"vesting_service_months": UNVESTED_SERVICE_MONTHS},
    )
    assert_cents(scenario["allocation"]["amount_cents"], 20_000, "allocation amount")

    terminated = fx.terminate_employee(client, scenario["employee_id"])
    assert terminated["employment_status"] == "TERMINATED"
    assert_ratio_4dp(terminated["vested_pct"], 0.00, "vested_pct")

    allocation = fx.refresh_allocation(client, scenario["allocation_id"])
    assert allocation["vesting_status"] == "FORFEITED"
    assert_cents(allocation["vested_cents"], 0, "vested_cents")
    assert_cents(allocation["forfeited_cents"], 20_000, "forfeited_cents")

    records = fx.forfeitures_of_employee(client, scenario["employee_id"])
    assert len(records) == 1
    record = records[0]
    assert_forfeiture_record_shape(record)
    assert_append_only_row(record, "ForfeitureRecord")
    assert_cents(record["amount_cents"], 20_000, "forfeiture amount")
    assert record["reason_code"] == "TERMINATION_UNVESTED"
    assert record["match_allocation_id"] == scenario["allocation_id"]
    assert record["plan_year_id"] == scenario["plan_year_id"]


def test_terminate_employee_reruns_the_forfeiture_offset_waterfall(client):
    """
    The forfeited money offsets the pending batch instead of being paid in cash.

    PRD: "the plan year's `forfeiture_balance_cents` is recomputed from those new
    records, and the offset waterfall re-runs over every `PENDING` funding batch of
    the plan year, rewriting each batch's `forfeiture_offset_cents` and
    `net_funding_cents`."

    PRD: "The system walks the plan year's `PENDING` batches in `created_at`
    ascending order and, for each, sets `forfeiture_offset_cents` to the lesser of the
    pool still unapplied and that batch's `total_allocated_cents`, reduces the
    unapplied pool by that offset, and sets `net_funding_cents` to
    `total_allocated_cents` less the offset."

    Design: Difficulty/transitive_cascade/terminate_employee_forfeiture_cascade_depth4
    """
    scenario = fx.setup_accepted_claim(
        client,
        employee_overrides={"vesting_service_months": UNVESTED_SERVICE_MONTHS},
    )

    batch_before = fx.refresh_funding_batch(client, scenario["funding_batch_id"])
    assert batch_before["status"] == "PENDING"
    assert_cents(batch_before["total_allocated_cents"], 20_000, "batch total before")
    assert_cents(batch_before["forfeiture_offset_cents"], 0, "batch offset before")
    assert_cents(batch_before["net_funding_cents"], 20_000, "batch net before")

    plan_year_before = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year_before["forfeiture_balance_cents"], 0, "forfeiture balance before")

    fx.terminate_employee(client, scenario["employee_id"])

    batch_after = fx.refresh_funding_batch(client, scenario["funding_batch_id"])
    assert_cents(batch_after["total_allocated_cents"], 20_000, "batch total after")
    assert_cents(batch_after["forfeiture_offset_cents"], 20_000, "batch offset after")
    assert_cents(batch_after["net_funding_cents"], 0, "batch net after")
    assert_batch_net_identity(batch_after)

    plan_year_after = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year_after["forfeiture_balance_cents"], 0, "forfeiture balance after")


# ---------------------------------------------------------------------------
# The cliff boundary
# ---------------------------------------------------------------------------


def test_vesting_cliff_boundary_at_36_months(client):
    """
    The vesting ladder steps at the stated month counts, not between them.

    PRD: "Vesting is a cliff schedule read off `vesting_service_months`: `vested_pct`
    is 0.00 below 24 months, 0.40 from 24 through 35 months, 0.60 from 36 through 47
    months, 0.80 from 48 through 59 months, and 1.00 at 60 months or more."

    PRD: "A new employee is created with `employment_status` `ACTIVE`,
    `termination_date` and `rehire_date` both null, and both the highly-compensated
    flag and the vested percentage computed immediately."

    Design: Corner/calculations/corner_vesting_cliff_boundary_at_36_months
    """
    fx.setup_open_plan_year(client)

    below_first_step = fx.create_employee(
        client, external_id="E-M23", vesting_service_months=23
    )
    last_of_second_step = fx.create_employee(
        client, external_id="E-M35", vesting_service_months=35
    )
    first_of_third_step = fx.create_employee(
        client, external_id="E-M36", vesting_service_months=36
    )

    assert_ratio_4dp(below_first_step["vested_pct"], 0.00, "vested_pct at 23 months")
    assert_ratio_4dp(last_of_second_step["vested_pct"], 0.40, "vested_pct at 35 months")
    assert_ratio_4dp(first_of_third_step["vested_pct"], 0.60, "vested_pct at 36 months")
