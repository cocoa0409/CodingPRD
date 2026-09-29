"""Boundary precision: the rolling-variance threshold one cent below the line, and the card settlement tier floor and half-cent rounding."""

from test_helpers import (
    CLERK_2,
    CLERK_3,
    TEST_USERS,
    assign_till,
    blind_count,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    make_clerk_headers,
    read_cashier,
    read_journal,
    read_session,
    record_drop,
    reconcile_till,
    set_clock,
    unlock_safe,
    validate_paginated,
    validate_success,
)

TREASURY = TEST_USERS["treasury_headers"]
CLERK = TEST_USERS["clerk_headers"]
BUSINESS_DATE = "2026-08-03"

#: Session A's blind count: eight twenty-dollar notes and one ten-dollar note.
SESSION_A_COUNTED_LINES = [
    {"denomination_cents": 2000, "quantity": 8},
    {"denomination_cents": 1000, "quantity": 1},
]

#: Session B's blind count, one cent shy of the 10000-cent rolling threshold.
SESSION_B_COUNTED_LINES_9999 = [
    {"denomination_cents": 2000, "quantity": 6},
    {"denomination_cents": 1000, "quantity": 1},
    {"denomination_cents": 1, "quantity": 1},
]

#: The same chain with that single cent absent, landing exactly on the threshold.
SESSION_B_COUNTED_LINES_10000 = [
    {"denomination_cents": 2000, "quantity": 6},
    {"denomination_cents": 1000, "quantity": 1},
]


# ------------------------------------------------------------------ recipe C


def _setup_rolling_chain(session_b_counted_lines):
    """Two sessions for one cashier at a store whose rolling threshold is 10000.

    Session A is already RECONCILED at a variance of -3000; session B is closed
    and blind-counted at the supplied lines but not yet reconciled. Returns a
    dict with keys store, safe, cashier, journal, session_a and session_b.
    """
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(
        store_code="S-1011",
        name="Store 1011",
        region_code="WEST",
        safe_time_delay_minutes=5,
        safe_open_window_minutes=10,
        dual_control_required=True,
        single_event_variance_threshold_cents=2500,
        rolling_variance_threshold_cents=10000,
        rolling_window_days=30,
    )
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    cashier = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    journal = create_sales_journal(store["id"], BUSINESS_DATE)

    # Arm at 09:00Z and open at 09:05Z; the safe is left UNLOCKED all day.
    unlock_safe(safe["id"], "2026-08-03T09:00:00Z", delay_minutes=5)

    session_a = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T13:00:00Z",
        starting_bank_cents=20000,
    )
    record_drop(session_a["id"], cashier["id"], 100000, txn_type="CLOSING_DROP")
    set_clock("2026-08-03T13:00:00Z")
    close_till(
        session_a["id"],
        cashier_id=cashier["id"],
        pos_cash_sales_cents=100000,
        pos_card_sales_cents=40000,
        pos_paid_out_cents=0,
    )
    blind_count(session_a["id"], SESSION_A_COUNTED_LINES, CLERK_3)
    # The reconciler must differ from the counter under dual control.
    session_a = reconcile_till(session_a["id"], CLERK_2)

    session_b = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=2,
        shift_start_at="2026-08-03T13:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )
    record_drop(session_b["id"], cashier["id"], 150000, txn_type="CLOSING_DROP")
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session_b["id"],
        cashier_id=cashier["id"],
        pos_cash_sales_cents=150000,
        pos_card_sales_cents=60000,
        pos_paid_out_cents=0,
    )
    blind_count(session_b["id"], session_b_counted_lines, CLERK_3)

    return {
        "store": store,
        "safe": safe,
        "cashier": cashier,
        "journal": journal,
        "session_a": session_a,
        "session_b": read_session(session_b["id"]),
    }


def _cases_of_type(api, journal_id, case_type):
    """List the journal's variance cases of one case_type, newest page included."""
    cases, meta = validate_paginated(
        api.list_variance_cases(
            CLERK,
            params={
                "sales_journal_id": journal_id,
                "case_type": case_type,
                "limit": 100,
            },
        )
    )
    return cases, meta


def test_rolling_variance_one_cent_below_threshold_keeps_cashier_eligible(api):
    """PRD §3.5: "**Link three** fires because link two recomputed `rolling_absolute_variance_cents`: if that recomputed figure is at or above the store's `rolling_variance_threshold_cents` — one hundred dollars by default — the cashier's `till_eligibility` is set to `RESTRICTED` and a second variance case is opened with `case_type` `ROLLING_PATTERN`, again naming this cashier and this sales journal."

    PRD §3.5: "From that set, `reconciled_session_count` becomes the number of sessions, `rolling_absolute_variance_cents` becomes the sum of the absolute values of their variances, and `rolling_net_variance_cents` becomes the signed sum of the same variances."

    Design: Difficulty/boundary_precision_check/rolling_variance_one_cent_below_threshold_keeps_cashier_eligible
    """
    ctx = _setup_rolling_chain(SESSION_B_COUNTED_LINES_9999)

    session_b = validate_success(
        api.reconcile_till_session(ctx["session_b"]["id"], make_clerk_headers(CLERK_2))
    )

    assert session_b["counted_cash_cents"] == 13001, (
        f"expected counted_cash_cents 13001, got {session_b['counted_cash_cents']}"
    )
    assert session_b["expected_cash_cents"] == 20000, (
        f"expected expected_cash_cents 20000, got {session_b['expected_cash_cents']}"
    )
    assert session_b["variance_cents"] == -6999, (
        f"expected variance_cents -6999, got {session_b['variance_cents']}"
    )

    cashier = read_cashier(ctx["cashier"]["id"])
    assert cashier["rolling_absolute_variance_cents"] == 9999, (
        "expected rolling_absolute_variance_cents 9999, got "
        f"{cashier['rolling_absolute_variance_cents']}"
    )
    assert cashier["rolling_net_variance_cents"] == -9999, (
        "expected rolling_net_variance_cents -9999, got "
        f"{cashier['rolling_net_variance_cents']}"
    )
    assert cashier["till_eligibility"] == "ELIGIBLE", (
        "one cent below the threshold leaves till_eligibility ELIGIBLE, got "
        f"{cashier['till_eligibility']}"
    )

    rolling_cases, rolling_meta = _cases_of_type(
        api, ctx["journal"]["id"], "ROLLING_PATTERN"
    )
    assert rolling_meta["total_count"] == 0, (
        f"no ROLLING_PATTERN case may open, got {rolling_meta['total_count']}"
    )
    assert rolling_cases == [], f"expected no ROLLING_PATTERN cases, got {rolling_cases}"


def test_rolling_chain_below_threshold_still_opens_both_session_variance_cases(api):
    """PRD §3.8: "For a `SESSION_VARIANCE` case the `total_variance_cents` is the absolute value of the triggering session's `variance_cents`; for a `ROLLING_PATTERN` case it is the cashier's freshly recomputed `rolling_absolute_variance_cents`; for a `DEPOSIT_CREDIT` case it is the absolute value of the deposit's `credit_variance_cents`."

    PRD §3.2: "A cashier's `open_case_count` is the number of variance cases naming that cashier whose `status` is `OPEN`, `RESEARCHING` or `ESCALATED`."

    Design: Difficulty/boundary_precision_check/rolling_variance_one_cent_below_threshold_keeps_cashier_eligible
    """
    ctx = _setup_rolling_chain(SESSION_B_COUNTED_LINES_9999)

    validate_success(
        api.reconcile_till_session(ctx["session_b"]["id"], make_clerk_headers(CLERK_2))
    )

    session_cases, session_meta = _cases_of_type(
        api, ctx["journal"]["id"], "SESSION_VARIANCE"
    )
    assert session_meta["total_count"] == 2, (
        f"expected exactly 2 SESSION_VARIANCE cases, got {session_meta['total_count']}"
    )
    totals = sorted(case["total_variance_cents"] for case in session_cases)
    assert totals == [3000, 6999], (
        f"expected SESSION_VARIANCE totals 3000 and 6999, got {totals}"
    )
    for case in session_cases:
        assert case["cashier_id"] == ctx["cashier"]["id"], (
            f"each case names the cashier, got {case['cashier_id']}"
        )

    cashier = read_cashier(ctx["cashier"]["id"])
    assert cashier["open_case_count"] == 2, (
        f"expected open_case_count 2, got {cashier['open_case_count']}"
    )


def test_rolling_variance_exactly_at_threshold_restricts_the_cashier(api):
    """PRD §2.5: "`rolling_variance_threshold_cents` defaults to 10000 and is the rolling absolute over/short at or above which the cashier is restricted and investigated."

    PRD §3.5: "**Link three** fires because link two recomputed `rolling_absolute_variance_cents`: if that recomputed figure is at or above the store's `rolling_variance_threshold_cents` — one hundred dollars by default — the cashier's `till_eligibility` is set to `RESTRICTED` and a second variance case is opened with `case_type` `ROLLING_PATTERN`, again naming this cashier and this sales journal."

    Design: Difficulty/boundary_precision_check/rolling_variance_one_cent_below_threshold_keeps_cashier_eligible
    """
    ctx = _setup_rolling_chain(SESSION_B_COUNTED_LINES_10000)

    session_b = validate_success(
        api.reconcile_till_session(ctx["session_b"]["id"], make_clerk_headers(CLERK_2))
    )
    assert session_b["counted_cash_cents"] == 13000, (
        "the same chain with that single cent absent counts 13000, got "
        f"{session_b['counted_cash_cents']}"
    )

    cashier = read_cashier(ctx["cashier"]["id"])
    assert cashier["rolling_absolute_variance_cents"] == 10000, (
        "expected rolling_absolute_variance_cents 10000, got "
        f"{cashier['rolling_absolute_variance_cents']}"
    )
    assert cashier["till_eligibility"] == "RESTRICTED", (
        "at the threshold the cashier is restricted, got "
        f"{cashier['till_eligibility']}"
    )

    rolling_cases, rolling_meta = _cases_of_type(
        api, ctx["journal"]["id"], "ROLLING_PATTERN"
    )
    assert rolling_meta["total_count"] == 1, (
        f"expected exactly 1 ROLLING_PATTERN case, got {rolling_meta['total_count']}"
    )
    assert rolling_cases[0]["total_variance_cents"] == 10000, (
        "a ROLLING_PATTERN case's magnitude is the freshly recomputed rolling "
        f"absolute variance, got {rolling_cases[0]['total_variance_cents']}"
    )


# ------------------------------------------------------------------ recipe D


def _setup_three_journals():
    """Store S-1012 with three OPEN sales journals and no settlements posted.

    Returns (store, journal_1, journal_2, journal_3) for 2026-08-03, 2026-08-04
    and 2026-08-05, with the logical clock at 2026-08-06T09:00:00Z.
    """
    set_clock("2026-08-06T09:00:00Z")
    store = create_store(store_code="S-1012", name="Store 1012", region_code="NORTH")
    journal_1 = create_sales_journal(store["id"], "2026-08-03")
    journal_2 = create_sales_journal(store["id"], "2026-08-04")
    journal_3 = create_sales_journal(store["id"], "2026-08-05")
    return store, journal_1, journal_2, journal_3


def _settlement_payload(
    journal_id,
    gross_card_sales_cents,
    txn_count,
    monthly_volume_cents,
    funded_amount_cents,
    chargeback_cents,
):
    return {
        "sales_journal_id": journal_id,
        "card_network": "VISA_MC",
        "gross_card_sales_cents": gross_card_sales_cents,
        "txn_count": txn_count,
        "monthly_volume_cents": monthly_volume_cents,
        "funded_amount_cents": funded_amount_cents,
        "chargeback_cents": chargeback_cents,
    }


def test_card_settlement_tier_floor_is_inclusive_at_the_lower_edge(api):
    """PRD §3.7: "The month-to-date volume selects a discount tier: the rate is 0.0250 while `monthly_volume_cents` is below 5000000, 0.0220 from 5000000 up to but not including 20000000, and 0.0195 at or above 20000000."

    PRD §3.7: "Tier boundaries are inclusive at the lower edge, so a `monthly_volume_cents` of exactly 5000000 selects 0.0220 and one of exactly 20000000 selects 0.0195."

    PRD §3.7: "Posting a settlement increments the journal's `settlement_count`, folds the absolute value of the settlement's variance into the journal's `settlement_variance_total_cents`, increments the journal's `version` by 1, and re-derives the journal's balanced clause."

    Design: Difficulty/boundary_precision_check/card_settlement_tier_floor_and_round_half_up_boundaries
    """
    store, journal_1, journal_2, journal_3 = _setup_three_journals()

    at_floor = validate_success(
        api.create_card_settlement(
            _settlement_payload(journal_1["id"], 300000, 120, 5000000, 291960, 0),
            TREASURY,
        ),
        201,
    )
    below_floor = validate_success(
        api.create_card_settlement(
            _settlement_payload(journal_2["id"], 300000, 120, 4999999, 291960, 0),
            TREASURY,
        ),
        201,
    )

    assert at_floor["expected_fee_cents"] == 8040, (
        "monthly_volume_cents 5000000 charges 0.0220: expected expected_fee_cents "
        f"8040, got {at_floor['expected_fee_cents']}"
    )
    assert at_floor["expected_funded_cents"] == 291960, (
        f"expected expected_funded_cents 291960, got {at_floor['expected_funded_cents']}"
    )
    assert at_floor["settlement_variance_cents"] == 0, (
        "expected settlement_variance_cents 0, got "
        f"{at_floor['settlement_variance_cents']}"
    )
    assert at_floor["settlement_status"] == "MATCHED", (
        f"expected settlement_status MATCHED, got {at_floor['settlement_status']}"
    )

    assert below_floor["expected_fee_cents"] == 8940, (
        "monthly_volume_cents 4999999 charges 0.0250: expected expected_fee_cents "
        f"8940, got {below_floor['expected_fee_cents']}"
    )
    assert below_floor["expected_funded_cents"] == 291060, (
        "expected expected_funded_cents 291060, got "
        f"{below_floor['expected_funded_cents']}"
    )
    assert below_floor["settlement_variance_cents"] == 900, (
        "expected settlement_variance_cents 900, got "
        f"{below_floor['settlement_variance_cents']}"
    )
    assert below_floor["settlement_status"] == "VARIANCE", (
        f"expected settlement_status VARIANCE, got {below_floor['settlement_status']}"
    )

    journal_2_after = read_journal(journal_2["id"])
    assert journal_2_after["settlement_variance_total_cents"] == 900, (
        "expected settlement_variance_total_cents 900, got "
        f"{journal_2_after['settlement_variance_total_cents']}"
    )
    journal_1_after = read_journal(journal_1["id"])
    assert journal_1_after["settlement_count"] == 1, (
        f"expected settlement_count 1, got {journal_1_after['settlement_count']}"
    )


def test_card_settlement_fee_rounds_half_up_on_the_percentage_component(api):
    """PRD §3.7: "`expected_fee_cents` is the product of `gross_card_sales_cents` and the sum of the tier rate and the network adder, rounded half up to whole cents, **plus** twelve cents for each transaction in `txn_count`."

    PRD §3.7: "The rounding happens on the percentage component alone and before the per-transaction component is added; rounding the combined figure instead changes the cents on many batches."

    PRD §3.7: "`expected_funded_cents` is `gross_card_sales_cents` minus `expected_fee_cents` minus `chargeback_cents`, and `settlement_variance_cents` is `funded_amount_cents` minus `expected_funded_cents`."

    Design: Difficulty/boundary_precision_check/card_settlement_tier_floor_and_round_half_up_boundaries
    """
    store, journal_1, journal_2, journal_3 = _setup_three_journals()

    half_cent = validate_success(
        api.create_card_settlement(
            _settlement_payload(journal_3["id"], 412750, 143, 21000000, 401485, 1500),
            TREASURY,
        ),
        201,
    )

    assert half_cent["expected_fee_cents"] == 9765, (
        "412750 at 0.0195 rounds half up to 8049 before the per-transaction "
        f"component: expected expected_fee_cents 9765, got {half_cent['expected_fee_cents']}"
    )
    assert half_cent["expected_fee_cents"] != 9764, (
        "truncating the half cent would give 9764, got "
        f"{half_cent['expected_fee_cents']}"
    )
    assert half_cent["expected_funded_cents"] == 401485, (
        "expected expected_funded_cents 401485, got "
        f"{half_cent['expected_funded_cents']}"
    )
    assert half_cent["settlement_variance_cents"] == 0, (
        "expected settlement_variance_cents 0, got "
        f"{half_cent['settlement_variance_cents']}"
    )
    assert half_cent["settlement_status"] == "MATCHED", (
        f"expected settlement_status MATCHED, got {half_cent['settlement_status']}"
    )
