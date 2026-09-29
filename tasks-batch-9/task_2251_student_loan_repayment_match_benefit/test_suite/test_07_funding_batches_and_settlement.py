"""Funding batches: transmission guards, the settlement answer and the retransmit loop."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_batch_net_identity,
    assert_cents,
    assert_funding_batch_shape,
    assert_instant_equals,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import PAYROLL_HEADERS, RECORDKEEPER_HEADERS


# ---------------------------------------------------------------------------
# Transmission requires a closed payroll period
# ---------------------------------------------------------------------------


def test_transmit_with_open_payroll_period_rejected(client):
    """
    A batch whose payroll period is still open cannot be transmitted.

    PRD: "Transmission is a `PayrollOperator` action and is guarded three ways: the
    batch must be `PENDING`, otherwise `ERR_BATCH_STATE_INVALID`; the batch's payroll
    period must be `CLOSED`, otherwise `ERR_PERIOD_NOT_CLOSED`; and
    `allocation_count` must be at least 1, otherwise `ERR_BATCH_EMPTY`."

    Design: Difficulty/cross_entity_state_dependency/transmit_requires_period_closed
    """
    scenario = fx.setup_accepted_claim(client)

    period = validate_success(
        client.get_payroll_period(scenario["payroll_period_id"], PAYROLL_HEADERS)
    )
    assert period["status"] == "OPEN"

    response = client.transmit_funding_batch(
        scenario["funding_batch_id"], None, PAYROLL_HEADERS
    )
    validate_error(response, ApiErrorId.PERIOD_NOT_CLOSED.value, 409)

    batch = fx.refresh_funding_batch(client, scenario["funding_batch_id"])
    assert batch["status"] == "PENDING"
    assert batch["transmitted_at"] is None


def test_transmit_succeeds_once_the_payroll_period_is_closed(client):
    """
    Closing the period is what makes its funding batch transmittable.

    PRD: "After the close no further payroll line may be created for the period, and
    the period's funding batch becomes transmittable."

    PRD: "Transmission stamps `transmitted_at` from the logical clock, freezes
    `forfeiture_offset_cents` at its pending value, and increments the batch's
    `version` by one."

    Design: Difficulty/cross_entity_state_dependency/transmit_requires_period_closed
    """
    scenario = fx.setup_accepted_claim(client)

    blocked = client.transmit_funding_batch(
        scenario["funding_batch_id"], None, PAYROLL_HEADERS
    )
    validate_error(blocked, ApiErrorId.PERIOD_NOT_CLOSED.value, 409)

    closed = fx.close_payroll_period(client, scenario["payroll_period_id"])
    assert closed["status"] == "CLOSED"

    transmitted = validate_success(
        client.transmit_funding_batch(scenario["funding_batch_id"], None, PAYROLL_HEADERS)
    )
    assert_funding_batch_shape(transmitted)
    assert transmitted["status"] == "TRANSMITTED"
    assert transmitted["transmitted_at"] is not None
    assert transmitted["allocation_count"] == 1
    assert_cents(transmitted["total_allocated_cents"], 20_000, "total_allocated_cents")


# ---------------------------------------------------------------------------
# Transmission and settlement state guards
# ---------------------------------------------------------------------------


def test_transmit_empty_batch_rejected(client):
    """
    A closed period with no scheduled allocation still has nothing to transmit.

    PRD: "and `allocation_count` must be at least 1, otherwise `ERR_BATCH_EMPTY`."

    PRD: "`total_allocated_cents` is the sum of `amount_cents` over the allocations
    bearing this batch's identifier whose `funding_status` is anything other than
    `REVERSED`, and `allocation_count` is how many such allocations there are".

    Design: Corner/endpoints/corner_transmit_empty_batch_rejected
    """
    plan_year = fx.setup_open_plan_year(client)
    period = fx.create_payroll_period(client, plan_year["id"], 3)
    batch = fx.create_funding_batch(client, plan_year["id"], period["id"])

    assert batch["allocation_count"] == 0
    assert_cents(batch["total_allocated_cents"], 0, "total_allocated_cents")

    closed = fx.close_payroll_period(client, period["id"])
    assert closed["status"] == "CLOSED"

    response = client.transmit_funding_batch(batch["id"], None, PAYROLL_HEADERS)
    validate_error(response, ApiErrorId.BATCH_EMPTY.value, 422)

    after = fx.refresh_funding_batch(client, batch["id"])
    assert after["status"] == "PENDING"
    assert after["transmitted_at"] is None


def test_settlement_from_pending_batch_rejected(client):
    """
    The recordkeeper cannot answer a batch that was never transmitted.

    PRD: "The `Recordkeeper` answers with a settlement `outcome` of either `SETTLED`
    or `REJECTED`, and either answer requires the batch to be `TRANSMITTED`,
    otherwise `ERR_BATCH_STATE_INVALID`."

    Design: Corner/state_machines/corner_settlement_from_pending_batch_rejected
    """
    scenario = fx.setup_accepted_claim(client)

    batch_before = fx.refresh_funding_batch(client, scenario["funding_batch_id"])
    assert batch_before["status"] == "PENDING"

    response = client.settle_funding_batch(
        scenario["funding_batch_id"], f.settlement_payload("SETTLED"), RECORDKEEPER_HEADERS
    )
    validate_error(response, ApiErrorId.BATCH_STATE_INVALID.value, 409)

    batch_after = fx.refresh_funding_batch(client, scenario["funding_batch_id"])
    assert batch_after["status"] == "PENDING"
    assert batch_after["settled_at"] is None

    period = validate_success(
        client.get_payroll_period(scenario["payroll_period_id"], PAYROLL_HEADERS)
    )
    assert period["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Settlement and the retransmit loop
# ---------------------------------------------------------------------------


def test_settlement_funds_allocations_and_period(client):
    """
    A settled batch funds every scheduled allocation and its payroll period.

    PRD: "`TRANSMITTED` → `SETTLED` stamps `settled_at` from the logical clock, moves
    every allocation of the batch `SCHEDULED` → `FUNDED` on the funding dimension,
    moves the batch's payroll period `CLOSED` → `FUNDED`, and increments the batch's
    `version` by one."

    PRD: "The move from `CLOSED` to `FUNDED` is not client-driven at all: it happens
    when a funding batch of that period reaches `SETTLED`."

    Design: Corner/state_machines/corner_settlement_funds_allocations_and_period
    """
    scenario = fx.setup_transmitted_batch(client)

    allocation_before = fx.refresh_allocation(client, scenario["allocation_id"])
    assert allocation_before["funding_status"] == "SCHEDULED"

    settled = fx.settle_batch(client, scenario["funding_batch_id"])
    assert settled["status"] == "SETTLED"
    assert_instant_equals(settled["settled_at"], DEFAULT_CLOCK_UTC, "settled_at")
    assert_cents(settled["total_allocated_cents"], 20_000, "total_allocated_cents")
    assert_batch_net_identity(settled)

    allocation_after = fx.refresh_allocation(client, scenario["allocation_id"])
    assert allocation_after["funding_status"] == "FUNDED"

    period = validate_success(
        client.get_payroll_period(scenario["payroll_period_id"], PAYROLL_HEADERS)
    )
    assert period["status"] == "FUNDED"

    plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year["total_qslp_match_funded_cents"], 20_000, "plan year qslp total")


def test_retransmit_after_rejection_increments_retransmit_count(client):
    """
    A rejected batch is retried through the same transmission operation.

    PRD: "`TRANSMITTED` → `REJECTED` requires a `rejection_code` in the body,
    rejected with `ERR_INVALID_REQUEST` when omitted, stores that code, leaves every
    allocation of the batch in `SCHEDULED`, and increments the batch's `version` by
    one."

    PRD: "from `REJECTED` the batch re-enters `PENDING`, `retransmit_count` increases
    by one, `rejection_code` is cleared, and the batch immediately re-enters
    `TRANSMITTED` within the same request"

    Design: Corner/state_machines/corner_retransmit_after_rejection_increments_retransmit_count
    """
    scenario = fx.setup_transmitted_batch(client)

    rejected = fx.reject_batch(client, scenario["funding_batch_id"], "RK-101")
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_code"] == "RK-101"
    assert rejected["retransmit_count"] == 0

    retransmitted = fx.transmit_batch(client, scenario["funding_batch_id"])
    assert retransmitted["status"] == "TRANSMITTED"
    assert retransmitted["retransmit_count"] == 1
    assert retransmitted["rejection_code"] is None

    allocation = fx.refresh_allocation(client, scenario["allocation_id"])
    assert allocation["funding_status"] == "SCHEDULED"

    period = validate_success(
        client.get_payroll_period(scenario["payroll_period_id"], PAYROLL_HEADERS)
    )
    assert period["status"] == "CLOSED"


def test_reopen_period_with_transmitted_batch_rejected(client):
    """
    A period whose money is already in flight may not be reopened for corrections.

    PRD: "Reopening a period, `CLOSED` → `OPEN`, is refused with
    `ERR_PERIOD_HAS_SETTLED_FUNDING` when any funding batch of that period stands in
    `TRANSMITTED` or `SETTLED`; when it succeeds it increments `reopen_count` by one."

    Design: Corner/errors/corner_reopen_period_with_transmitted_batch_rejected
    """
    scenario = fx.setup_transmitted_batch(client)

    batch = fx.refresh_funding_batch(client, scenario["funding_batch_id"])
    assert batch["status"] == "TRANSMITTED"

    response = client.set_payroll_period_status(
        scenario["payroll_period_id"], f.payroll_period_status_payload("OPEN"), PAYROLL_HEADERS
    )
    validate_error(response, ApiErrorId.PERIOD_HAS_SETTLED_FUNDING.value, 409)

    period = validate_success(
        client.get_payroll_period(scenario["payroll_period_id"], PAYROLL_HEADERS)
    )
    assert period["status"] == "CLOSED"
    assert period["reopen_count"] == 0
