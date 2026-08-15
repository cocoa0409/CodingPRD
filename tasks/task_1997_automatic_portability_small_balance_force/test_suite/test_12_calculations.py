"""Queue B corner tests: calculation rules (fee cap, duplicate fee period, stale boundary,
batch totals)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_participant_headers,
    make_provider_ops_headers,
    create_active_recordkeeper,
    create_plan,
    create_participant,
    create_open_batch,
    create_case,
    send_force_out_notice_and_deliver,
    submit_election,
    setup_ira_with_fee_disclosure,
    setup_established_ira,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


def test_fee_capped_at_zero_balance_floor():
    """PRD §3.6: "The posted `amount_cents` is the lesser of the computed fee and the IRA's
    `balance_cents` at assessment, so a fee never drives the balance below zero."
    PRD §3.6: "an August-1-to-September-1 period bills 510 cents under `ACTUAL_365`
    (thirty-one days)"

    Design: Corner/calculations/fee_capped_at_zero_balance_floor
    """
    ctx = setup_ira_with_fee_disclosure(balance=300)
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", OPS))
    fee = validate_success(api_client.assess_ira_fee(ctx["ira"]["id"], OPS), 201)
    # Computed fee 510 exceeds the 300-cent balance; only 300 posts.
    assert fee["amount_cents"] == 300
    ira = get_success_data(api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
    assert ira["balance_cents"] == 0
    assert ira["total_fees_cents"] == 300


def test_duplicate_fee_period_same_month():
    """PRD §3.6: "Only one assessment may post per IRA per UTC calendar month, measured by
    `period_end`; a second attempt in the same month is rejected with
    `ERR_DUPLICATE_FEE_PERIOD`."
    PRD §3.6: "Under `ACTUAL_365`, `days_in_period` is the count of calendar days in the
    period and the fee is 6,000 cents times the day count divided by 365."
    PRD §3.6: "the anchor is `last_fee_assessed_at` once any assessment exists and
    `opened_at` before the first."

    Design: Corner/calculations/duplicate_fee_period_same_month
    """
    ctx = setup_ira_with_fee_disclosure(balance=300000)
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", OPS))
    fee1 = validate_success(api_client.assess_ira_fee(ctx["ira"]["id"], OPS), 201)
    assert fee1["amount_cents"] == 510

    # Same UTC month: rejected.
    res = api_client.assess_ira_fee(ctx["ira"]["id"], OPS)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_FEE_PERIOD, 409)

    # Next month: succeeds. Period 2026-09-01 -> 2026-10-01 is 30 days ACTUAL_365:
    # round_half_up(6000 * 30 / 365) = 493.
    get_success_data(api_client.set_clock("2026-10-01T00:00:00Z", OPS))
    fee2 = validate_success(api_client.assess_ira_fee(ctx["ira"]["id"], OPS), 201)
    assert fee2["amount_cents"] == 493
    ira = get_success_data(api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
    assert ira["total_fees_cents"] == 1003


def test_check_cashable_at_exact_stale_boundary():
    """PRD §3.8: "A check is stale once the current instant passes its `stale_after` — the
    boundary is exclusive for the holder: recording the check as cashed at exactly
    `stale_after` still succeeds, and one instant later it fails with `ERR_CHECK_STALE`."
    PRD §3.5: "computes `stale_after` as one hundred eighty days after issuance"

    Design: Corner/calculations/check_cashable_at_exact_stale_boundary
    """
    rk = create_active_recordkeeper()
    plan = create_plan(rk["id"])
    p_a = create_participant(ssn_hash="hash-a", full_name="Ann A")
    p_b = create_participant(ssn_hash="hash-b", full_name="Bob B")
    batch = create_open_batch(plan["id"])
    c_a = create_case(batch["id"], plan["id"], p_a["id"],
                      separation_date_balance_cents=100000,
                      processing_date_balance_cents=100000)
    c_b = create_case(batch["id"], plan["id"], p_b["id"],
                      separation_date_balance_cents=90000,
                      processing_date_balance_cents=90000)
    get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
    send_force_out_notice_and_deliver(c_a["id"])
    send_force_out_notice_and_deliver(c_b["id"])
    submit_election(c_a["id"], p_a["id"], "LUMP_SUM_CASH")
    submit_election(c_b["id"], p_b["id"], "LUMP_SUM_CASH")
    get_success_data(api_client.execute_distribution_batch(
        batch["id"], make_provider_ops_headers("ops_exec_1")))
    chk1 = get_success_data(api_client.create_check(
        {"distribution_case_id": c_a["id"]}, OPS))
    chk2 = get_success_data(api_client.create_check(
        {"distribution_case_id": c_b["id"]}, OPS))
    # Checks issued at 2026-08-01T00:00:00Z; stale_after = 2027-01-28T00:00:00Z.
    assert chk1["stale_after"] == "2027-01-28T00:00:00.000Z"

    # At exactly stale_after: cashable.
    get_success_data(api_client.set_clock("2027-01-28T00:00:00Z", OPS))
    cashed = validate_success(api_client.record_check_cashed(chk1["id"], OPS))
    assert cashed["check_status"] == "CASHED"

    # One second past: stale.
    get_success_data(api_client.set_clock("2027-01-28T00:00:01Z", OPS))
    res = api_client.record_check_cashed(chk2["id"], OPS)
    validate_error(res, ApiErrorId.ERR_CHECK_STALE, 422)
    chk2_after = get_success_data(api_client.get_check(chk2["id"], OPS))
    assert chk2_after["check_status"] == "ISSUED"


def test_batch_totals_after_mixed_execution():
    """PRD §3.9: "`case_count` counts every case attached to the batch;
    `settled_case_count` counts those in exactly `SETTLED`, `ESCHEATED`, or `CANCELLED`;
    and `total_forced_out_cents` sums `vested_balance_cents` over the cases whose
    `executed_path` is one of `CHECK_CASH_OUT`, `SAFE_HARBOR_IRA`, or `DIRECT_NEW_PLAN`."
    PRD §3.8: "settles the underlying case from `EXECUTED` to `SETTLED` and recomputes the
    batch's `settled_case_count`."

    Design: Corner/calculations/batch_totals_after_mixed_execution
    """
    rk = create_active_recordkeeper()
    plan = create_plan(rk["id"])
    p_a = create_participant(ssn_hash="hash-a", full_name="Ann A")
    p_b = create_participant(ssn_hash="hash-b", full_name="Bob B")
    batch = create_open_batch(plan["id"])
    c_a = create_case(batch["id"], plan["id"], p_a["id"],
                      separation_date_balance_cents=100000,
                      processing_date_balance_cents=100000)
    c_b = create_case(batch["id"], plan["id"], p_b["id"],
                      separation_date_balance_cents=300000,
                      processing_date_balance_cents=300000)
    get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
    send_force_out_notice_and_deliver(c_a["id"])
    send_force_out_notice_and_deliver(c_b["id"])
    submit_election(c_a["id"], p_a["id"], "LUMP_SUM_CASH")
    submit_election(c_b["id"], p_b["id"], "SAFE_HARBOR_IRA")
    get_success_data(api_client.execute_distribution_batch(
        batch["id"], make_provider_ops_headers("ops_exec_1")))

    chk = get_success_data(api_client.create_check(
        {"distribution_case_id": c_a["id"]}, OPS))
    get_success_data(api_client.create_safe_harbor_ira(
        {"distribution_case_id": c_b["id"]}, OPS))

    batch = get_success_data(api_client.get_distribution_batch(batch["id"], OPS))
    assert batch["total_forced_out_cents"] == 400000
    assert batch["case_count"] == 2
    # IRA case is SETTLED immediately; cash case is EXECUTED until the check clears.
    assert batch["settled_case_count"] == 1

    validate_success(api_client.record_check_cashed(chk["id"], OPS))
    batch = get_success_data(api_client.get_distribution_batch(batch["id"], OPS))
    assert batch["settled_case_count"] == 2
