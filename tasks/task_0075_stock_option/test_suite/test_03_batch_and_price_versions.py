"""Grant batches and exercise-price-version chain (PRD §3.2, §3.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_exercise_price_version,
    assert_grant_batch,
    create_and_activate_plan,
    create_and_open_batch,
    create_cash_dividend_payload,
    create_grant_batch_payload,
    create_option_plan_payload,
    create_restructuring,
    create_stock_split,
    get_tip_price_version,
    validate_error,
    validate_success,
)


def test_create_batch_in_draft(api, plan_admin_headers):
    """PRD §3.2: "The batch is created in DRAFT."""
    plan = create_and_activate_plan()
    res = api.create_grant_batch(
        plan["id"], create_grant_batch_payload(), plan_admin_headers,
    )
    batch = validate_success(res, expected_status=201)
    assert_grant_batch(batch)
    assert batch["status"] == "DRAFT"


def test_open_batch_requires_plan_active(api, plan_admin_headers):
    """PRD §3.2: "...the owning plan must be ACTIVE. The first two
    failures yield ERR_INVALID_REQUEST; the plan-state failure yields
    ERR_PLAN_NOT_ACTIVE."
    """
    plan_res = api.create_option_plan(
        create_option_plan_payload(), plan_admin_headers,
    )
    plan = validate_success(plan_res, expected_status=201)
    # Plan still DRAFT.
    batch_res = api.create_grant_batch(
        plan["id"], create_grant_batch_payload(), plan_admin_headers,
    )
    batch = validate_success(batch_res, expected_status=201)
    res = api.open_grant_batch(
        plan["id"], batch["id"], plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)


def test_open_batch_rejects_cliff_greater_than_total(api, plan_admin_headers):
    """PRD §3.2: "cliff_months must be less than or equal to
    vesting_total_months ... The first two failures yield
    ERR_INVALID_REQUEST."
    """
    plan = create_and_activate_plan()
    batch_res = api.create_grant_batch(
        plan["id"],
        create_grant_batch_payload(
            cliff_months=60, vesting_total_months=48,
        ),
        plan_admin_headers,
    )
    # Either creation rejects this directly, or /open does.
    if batch_res.status_code == 422:
        validate_error(batch_res, ApiErrorId.ERR_INVALID_REQUEST.value)
        return
    batch = validate_success(batch_res, expected_status=201)
    res = api.open_grant_batch(plan["id"], batch["id"], plan_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_open_batch_rejects_non_divisible_total(api, plan_admin_headers):
    """PRD §3.2: "vesting_total_months must be evenly divisible by
    vesting_period_months (the remainder of the division must be zero)."
    """
    plan = create_and_activate_plan()
    batch_res = api.create_grant_batch(
        plan["id"],
        create_grant_batch_payload(
            cliff_months=12,
            vesting_total_months=50,  # not divisible by 3
            vesting_period_months=3,
        ),
        plan_admin_headers,
    )
    if batch_res.status_code == 422:
        validate_error(batch_res, ApiErrorId.ERR_INVALID_REQUEST.value)
        return
    batch = validate_success(batch_res, expected_status=201)
    res = api.open_grant_batch(plan["id"], batch["id"], plan_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_open_batch_creates_initial_price_version(api, plan_admin_headers):
    """PRD §3.2: "the first ExercisePriceVersion for the batch is created
    with version_index 1, cause INITIAL, corporate_event_id null,
    parent_version_id null ... and price_per_option_cents taken from the
    staged input."
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(
        plan["id"], initial_price_per_option_cents=5000,
    )
    res = api.list_exercise_price_versions(
        batch["id"], plan_admin_headers,
    )
    body = res.json()
    versions = body["data"]
    assert len(versions) == 1
    v1 = versions[0]
    assert_exercise_price_version(v1)
    assert v1["version_index"] == 1
    assert v1["cause"] == "INITIAL"
    assert v1["corporate_event_id"] is None
    assert v1["parent_version_id"] is None
    assert v1["price_per_option_cents"] == 5000


def test_lock_batch_blocked_by_pending_grants(api, plan_admin_headers,
                                              board_secretary_headers):
    """PRD §3.2: "Locking the batch transitions it from OPEN_FOR_GRANTS
    to LOCKED and is rejected with ERR_PENDING_GRANTS_EXIST if any grant
    under the batch is still in DRAFT, BOARD_APPROVED, or SHAREHOLDER_APPROVED."
    """
    from test_helpers import create_grant_payload, register_grantee
    plan = create_and_activate_plan()
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant_res = api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    )
    validate_success(grant_res, expected_status=201)
    res = api.lock_grant_batch(plan["id"], batch["id"], plan_admin_headers)
    validate_error(res, ApiErrorId.ERR_PENDING_GRANTS_EXIST.value)


# ---------------------------------------------------------------------------
# Corporate event repricing math (PRD §3.7)
# ---------------------------------------------------------------------------
def test_stock_split_halves_price_floor(api, plan_admin_headers):
    """PRD §3.7: "For a stock split, the new per-option price is the
    floor of the parent version's price_per_option_cents multiplied by
    split_ratio_denominator, divided by split_ratio_numerator. A 2-for-1
    split (split_ratio_numerator is 2, split_ratio_denominator is 1)
    therefore halves the price..."
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(
        plan["id"], initial_price_per_option_cents=5000,
    )
    split = create_stock_split(
        plan["id"], plan["current_clock_ts"], numerator=2, denominator=1,
    )
    tip = get_tip_price_version(batch["id"])
    assert tip["version_index"] == 2
    assert tip["cause"] == "STOCK_SPLIT"
    assert tip["price_per_option_cents"] == 2500  # floor(5000*1/2)
    assert tip["corporate_event_id"] == split["id"]


def test_stock_split_zero_ratio_rejected(api, plan_admin_headers):
    """PRD §3.7: "both ratio fields must be at least 1 or the
    corporate-event creation is rejected with ERR_INVALID_REQUEST."
    """
    plan = create_and_activate_plan()
    create_and_open_batch(plan["id"])
    from test_helpers import create_stock_split_payload
    payload = create_stock_split_payload(
        plan["current_clock_ts"], numerator=0, denominator=1,
    )
    res = api.create_corporate_event(
        plan["id"], payload, plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_restructuring_multiply_first_round_last(api, plan_admin_headers):
    """PRD §3.7: "the new per-option price is computed by multiplying the
    parent's price_per_option_cents by restructure_factor_bps, then
    dividing by the basis-points divisor of 10000, with rounding half up
    performed only at the final step — multiplication first, division
    second, rounding last."

    Pinned-order check: 5000 * 8000 / 10000 = 4000 (multiply-then-divide).
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(
        plan["id"], initial_price_per_option_cents=5000,
    )
    create_restructuring(
        plan["id"], plan["current_clock_ts"],
        restructure_factor_bps=8000,
    )
    tip = get_tip_price_version(batch["id"])
    assert tip["cause"] == "RESTRUCTURING"
    assert tip["price_per_option_cents"] == 4000


def test_restructuring_factor_out_of_range_rejected(api, plan_admin_headers):
    """PRD §3.7: "restructure_factor_bps must lie between 100 and 100000
    inclusive or the creation is rejected with ERR_INVALID_REQUEST."
    """
    plan = create_and_activate_plan()
    create_and_open_batch(plan["id"])
    from test_helpers import create_restructuring_payload
    res = api.create_corporate_event(
        plan["id"],
        create_restructuring_payload(
            plan["current_clock_ts"], restructure_factor_bps=99,
        ),
        plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_cash_dividend_subtracts_with_min_floor(api, plan_admin_headers):
    """PRD §3.7: "For a cash dividend, the new per-option price is the
    parent version's price_per_option_cents minus dividend_amount_cents,
    clamped to a minimum of 1 cent..."
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(
        plan["id"], initial_price_per_option_cents=5000,
    )
    res = api.create_corporate_event(
        plan["id"],
        create_cash_dividend_payload(
            plan["current_clock_ts"], dividend_cents=100,
        ),
        plan_admin_headers,
    )
    validate_success(res, expected_status=201)
    tip = get_tip_price_version(batch["id"])
    assert tip["cause"] == "CASH_DIVIDEND"
    assert tip["price_per_option_cents"] == 4900


def test_cash_dividend_clamps_to_min_one_cent(api, plan_admin_headers):
    """PRD §3.7: "...clamped to a minimum of 1 cent (the constant
    MIN_PRICE_CENTS)."
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(
        plan["id"], initial_price_per_option_cents=50,
    )
    res = api.create_corporate_event(
        plan["id"],
        create_cash_dividend_payload(
            plan["current_clock_ts"], dividend_cents=10_000,
        ),
        plan_admin_headers,
    )
    validate_success(res, expected_status=201)
    tip = get_tip_price_version(batch["id"])
    assert tip["price_per_option_cents"] == 1


def test_repricing_cascade_appends_one_version_per_batch(api,
                                                         plan_admin_headers):
    """PRD §2.9: "Recording a corporate event of type STOCK_SPLIT,
    CASH_DIVIDEND, or RESTRUCTURING appends a new ExercisePriceVersion
    row for every GrantBatch under the plan, with cause set to the
    corporate-event type..."
    """
    plan = create_and_activate_plan()
    batch_a = create_and_open_batch(
        plan["id"], initial_price_per_option_cents=5000,
        batch_label="Batch-A",
    )
    batch_b = create_and_open_batch(
        plan["id"], initial_price_per_option_cents=6000,
        batch_label="Batch-B",
    )
    create_stock_split(
        plan["id"], plan["current_clock_ts"], numerator=2, denominator=1,
    )
    versions_a = api.list_exercise_price_versions(
        batch_a["id"], plan_admin_headers,
    ).json()["data"]
    versions_b = api.list_exercise_price_versions(
        batch_b["id"], plan_admin_headers,
    ).json()["data"]
    assert len(versions_a) == 2
    assert len(versions_b) == 2
    a_tip = max(versions_a, key=lambda v: v["version_index"])
    b_tip = max(versions_b, key=lambda v: v["version_index"])
    assert a_tip["price_per_option_cents"] == 2500
    assert b_tip["price_per_option_cents"] == 3000


def test_blackout_with_end_before_start_rejected(api, plan_admin_headers):
    """PRD §3.6: "blackout_end_ts (exclusive end, which must be strictly
    later than effective_ts, else ERR_INVALID_TIME_INTERVAL)."
    """
    plan = create_and_activate_plan()
    import datetime as _dt
    base = _dt.datetime.fromisoformat(
        plan["current_clock_ts"].replace("Z", "+00:00"),
    )
    effective_ts = base.isoformat().replace("+00:00", "Z")
    blackout_end_ts = base.isoformat().replace("+00:00", "Z")  # equal
    from test_helpers import create_blackout_event_payload
    res = api.create_corporate_event(
        plan["id"],
        create_blackout_event_payload(
            "EARNINGS_BLACKOUT", effective_ts, blackout_end_ts,
        ),
        plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_INTERVAL.value)
