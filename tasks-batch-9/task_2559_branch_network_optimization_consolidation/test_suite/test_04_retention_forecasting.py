"""Deposit-retention modelling: the two instruments, supersession and the share guard."""

from test_helpers import (
    STRATEGIST,
    ApiErrorId,
    api_client,
    assert_retention_forecast,
    branch_payload,
    consolidation_case_payload,
    read_case,
    read_forecast,
    receiving_branch_payload,
    retention_forecast_payload,
    setup_draft_case,
    setup_market,
    validate_error,
    validate_paginated,
    validate_success,
)

RIVERBEND = {
    "name": "Riverbend North",
    "region_code": "MW-04",
    "population": 120000,
    "median_household_income_cents": 8500000,
    "deposit_market_total_cents": 240000000000,
    "competitor_branch_count": 24,
    "household_growth_pct_bps": 350,
    "digital_penetration_bps": 5200,
}

SEGMENT_SHARES = {
    "retail_share_bps": 6000,
    "small_business_share_bps": 2500,
    "wealth_share_bps": 1500,
}


def _riverbend_case() -> dict:
    """Riverbend North pair with a DRAFT case closing RB-101 into RB-102."""
    market = setup_market(**RIVERBEND)
    closing = validate_success(
        api_client.create_branch(
            branch_payload(
                market["id"],
                monthly_transaction_count=3600,
                annual_revenue_cents=140000000,
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    receiving = validate_success(
        api_client.create_branch(
            receiving_branch_payload(
                market["id"],
                monthly_transaction_count=7200,
                digital_adoption_bps=6800,
                annual_noninterest_expense_cents=118000000,
                annual_revenue_cents=305000000,
                opened_on="1998-06-15",
                onboarding_capacity_households_per_day=60,
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    case = validate_success(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                closing["id"],
                closing["version"],
                planned_closure_date="2026-11-15",
                receiving_branch_id=receiving["id"],
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    return {"market": market, "closing_branch": closing,
            "receiving_branch": receiving, "case": case}


def test_01_the_distance_decay_instrument_consumes_the_mileage_downwards():
    """At 3.4 miles the decay instrument floors the distance to three miles, applies the capped
    digital uplift and splits the frozen baseline without creating or losing a cent.

    PRD: "Under `DISTANCE_DECAY`, distance is consumed by rounding **down** to a whole mile: subtract 1 from the floored mileage, take the larger of that and zero, and multiply by 400 basis points to obtain the decay."
    PRD: "Then add a digital uplift equal to 1500 basis points of the frozen `digital_adoption_bps` — that is, the adoption share multiplied by 1500 and divided by 10000, rounded half up — capped at 800 basis points."
    PRD: "Creation copies two figures off the closing branch and freezes them on the forecast: `baseline_deposits_cents` from the branch's `deposit_balance_cents`, and `digital_adoption_bps` from the branch's digital-channel share."
    Design: Difficulty/dual_variant_calc/retention_forecast_distance_decay_vs_segment_mix_divergence
    """
    ctx = _riverbend_case()

    forecast = validate_success(
        api_client.create_retention_forecast(
            retention_forecast_payload(
                ctx["case"]["id"],
                ctx["case"]["version"],
                model_variant="DISTANCE_DECAY",
                distance_miles=3.4,
                **SEGMENT_SHARES,
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )

    assert_retention_forecast(forecast)
    assert forecast["retention_bps"] == 9200
    assert forecast["retained_deposits_cents"] == 4416000000
    assert forecast["runoff_cents"] == 384000000
    assert forecast["baseline_deposits_cents"] == 4800000000
    assert forecast["digital_adoption_bps"] == 5400
    assert forecast["status"] == "ACTIVE"

    case = read_case(ctx["case"]["id"])
    assert case["forecast_retention_bps"] == 9200
    assert case["forecast_retained_deposits_cents"] == 4416000000
    assert case["forecast_runoff_cents"] == 384000000


def test_02_the_segment_mix_instrument_consumes_the_same_mileage_upwards():
    """Filing a segment-mix model over the same 3.4 miles ceils the distance into a
    multiplicative penalty on a share-weighted base, lands 1768 basis points lower, supersedes
    the earlier model and rewrites the case's mirrored figures.

    PRD: "Under `SEGMENT_MIX`, the segment shares drive a weighted base: multiply `retail_share_bps` by 8200, `small_business_share_bps` by 7000 and `wealth_share_bps` by 9100, add the three products, divide by 10000 and round half up."
    PRD: "Distance then applies as a multiplicative penalty and is consumed by rounding **up** to a whole mile: subtract 1 from the ceiled mileage, take the larger of that and zero, multiply by 250 basis points, and cap the penalty at 2500 basis points."
    PRD: "The three figures are mirrored onto the case as `forecast_retention_bps`, `forecast_retained_deposits_cents` and `forecast_runoff_cents`, the case's savings chain is recomputed, and the case's `version` increments by one."
    Design: Difficulty/dual_variant_calc/retention_forecast_distance_decay_vs_segment_mix_divergence
    """
    ctx = _riverbend_case()
    decay = validate_success(
        api_client.create_retention_forecast(
            retention_forecast_payload(
                ctx["case"]["id"],
                ctx["case"]["version"],
                model_variant="DISTANCE_DECAY",
                distance_miles=3.4,
                **SEGMENT_SHARES,
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    reread = read_case(ctx["case"]["id"])

    mix = validate_success(
        api_client.create_retention_forecast(
            retention_forecast_payload(
                ctx["case"]["id"],
                reread["version"],
                model_variant="SEGMENT_MIX",
                distance_miles=3.4,
                **SEGMENT_SHARES,
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )

    assert mix["retention_bps"] == 7432
    assert mix["retained_deposits_cents"] == 3567360000
    assert mix["runoff_cents"] == 1232640000
    assert decay["retention_bps"] - mix["retention_bps"] == 1768
    assert mix["status"] == "ACTIVE"
    assert read_forecast(decay["id"])["status"] == "SUPERSEDED"

    case = read_case(ctx["case"]["id"])
    assert case["forecast_retention_bps"] == 7432
    assert case["forecast_retained_deposits_cents"] == 3567360000
    assert case["forecast_runoff_cents"] == 1232640000


def test_03_a_second_model_supersedes_the_first_and_both_stay_on_the_case_file():
    """Re-modelling the same case at a longer drive distance writes a new active model, demotes
    the earlier one, rewrites the case's mirrored split, and leaves both models readable on the
    case's own model list with their frozen baselines intact.

    PRD: "The new forecast is written in `ACTIVE` status, and the case's prior `ACTIVE` forecast, if any, transitions to `SUPERSEDED`; only the single `ACTIVE` forecast ever feeds the case's fields."
    PRD: "`runoff_cents` is `baseline_deposits_cents` minus `retained_deposits_cents` — the exact complement, computed by subtraction and never rounded independently, so that no cent is created or lost in the split."
    PRD: "Forecasts may be listed per case newest first, filtered by `status`, or across cases filtered by `consolidation_case_id`, `model_variant` and `status`, and any single forecast may be read on its own."
    Design: Corner/endpoints/a_second_retention_forecast_supersedes_the_first_and_both_remain_listable
    """
    ctx = setup_draft_case()

    first = validate_success(
        api_client.create_retention_forecast(
            retention_forecast_payload(
                ctx["case"]["id"], ctx["case"]["version"], distance_miles=3.0
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    assert first["retention_bps"] == 9200
    assert first["retained_deposits_cents"] == 4416000000
    assert read_case(ctx["case"]["id"])["forecast_retention_bps"] == 9200

    pinned = read_case(ctx["case"]["id"])["version"]
    second = validate_success(
        api_client.create_retention_forecast(
            retention_forecast_payload(ctx["case"]["id"], pinned, distance_miles=6.0),
            STRATEGIST,
        ),
        expected_status=201,
    )
    assert second["retention_bps"] == 8000
    assert second["retained_deposits_cents"] == 3840000000
    assert second["runoff_cents"] == 960000000

    rows, meta = validate_paginated(
        api_client.list_case_retention_forecasts(ctx["case"]["id"], STRATEGIST)
    )
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == "SUPERSEDED"
    assert by_id[second["id"]]["status"] == "ACTIVE"
    for row in rows:
        assert row["baseline_deposits_cents"] == 4800000000
        assert row["digital_adoption_bps"] == 5400

    case = read_case(ctx["case"]["id"])
    assert case["forecast_retention_bps"] == 8000
    assert case["forecast_retained_deposits_cents"] == 3840000000
    assert case["forecast_runoff_cents"] == 960000000


def test_04_segment_shares_one_basis_point_short_of_the_whole_are_refused():
    """Shares totalling 9999 basis points are rejected even under the decay instrument, which
    never reads them, and nothing is written: the case keeps an empty model list and its
    untouched zero split.

    PRD: "A sum other than exactly 10000 is rejected with `ERR_SEGMENT_MIX_INVALID`."
    PRD: "The same strategist creates a **RetentionForecast** naming the `consolidation_case_id`, a `model_variant` of `DISTANCE_DECAY` or `SEGMENT_MIX`, the driving `distance_miles` from the closing branch to the receiving branch, and the three customer-segment shares — `retail_share_bps`, `small_business_share_bps` and `wealth_share_bps` — each from 0 through 10000 basis points and together summing to exactly 10000."
    Design: Corner/validations/segment_shares_summing_to_9999_rejected_with_segment_mix_invalid
    """
    ctx = setup_draft_case()
    opening_version = ctx["case"]["version"]

    validate_error(
        api_client.create_retention_forecast(
            retention_forecast_payload(
                ctx["case"]["id"],
                opening_version,
                model_variant="DISTANCE_DECAY",
                distance_miles=3.0,
                retail_share_bps=8000,
                small_business_share_bps=1500,
                wealth_share_bps=499,
            ),
            STRATEGIST,
        ),
        ApiErrorId.ERR_SEGMENT_MIX_INVALID.value,
        expected_status=422,
    )

    _, meta = validate_paginated(
        api_client.list_case_retention_forecasts(ctx["case"]["id"], STRATEGIST)
    )
    assert meta["total_count"] == 0

    case = read_case(ctx["case"]["id"])
    assert case["forecast_retention_bps"] == 0
    assert case["forecast_retained_deposits_cents"] == 0
    assert case["forecast_runoff_cents"] == 0
    assert case["version"] == opening_version
