"""Stale-version rejection on the two guarded writes, the safe's version walk, and the single-event coaching threshold at the cent."""

from test_helpers import (
    CLERK_1,
    CLERK_2,
    CLERK_3,
    ApiErrorId,
    append_attribution,
    arm_open_request,
    assign_till,
    blind_count,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    list_cases,
    open_safe,
    parse_instant,
    read_case,
    read_cashier,
    read_journal,
    read_safe,
    reconcile_till,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

BUSINESS_DATE = "2026-08-03"

#: Fifty twenty-dollar notes — a bag worth 100000 cents.
BAG_100000 = [{"denomination_cents": 2000, "quantity": 50}]

#: Thirty-three twenty-dollar notes and one ten-dollar note: 67000 cents.
COUNT_67000 = [
    {"denomination_cents": 2000, "quantity": 33},
    {"denomination_cents": 1000, "quantity": 1},
]

#: Seventeen ten-dollar notes and one five-dollar note: exactly 17500 cents.
COUNT_17500 = [
    {"denomination_cents": 1000, "quantity": 17},
    {"denomination_cents": 500, "quantity": 1},
]

#: The same drawer plus a single cent: 17501 cents.
COUNT_17501 = [
    {"denomination_cents": 1000, "quantity": 17},
    {"denomination_cents": 500, "quantity": 1},
    {"denomination_cents": 1, "quantity": 1},
]


def test_deposit_prepare_with_a_stale_safe_version_returns_412(api, clerk_headers):
    """PRD §2.11: "Preparing an armored deposit through `POST /cash-ops/deposits` requires `expected_safe_version` as a non-optional field of the request body, carrying the `version` of the target `Safe` that the clerk last observed."

    PRD §2.11: "If the safe's current `version` has advanced past `expected_safe_version` since the client read it, the preparation is rejected with `ERR_SAFE_VERSION_STALE` (HTTP 412)."

    PRD §3.6: "It deliberately does **not** relock the safe."

    Design: Corner/cross_cutting_complexity_layers/deposit_prepare_with_a_stale_safe_version_returns_412
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1980", name="Store 1980", region_code="WEST")
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    journal = create_sales_journal(store["id"], BUSINESS_DATE)
    arm_open_request(safe["id"], CLERK_1, reason="Two bags")
    set_clock("2026-08-03T08:05:00Z")
    stale_v = open_safe(safe["id"], CLERK_2)["version"]

    payload = {
        "safe_id": safe["id"],
        "sales_journal_id": journal["id"],
        "business_date": BUSINESS_DATE,
        "counted_lines": BAG_100000,
        "expected_safe_version": stale_v,
    }
    deposit_a = validate_success(api.create_deposit(payload, clerk_headers), 201)
    assert deposit_a["declared_total_cents"] == 100000, (
        f"the first bag is worth 100000, got {deposit_a['declared_total_cents']}"
    )

    replay = api.create_deposit(payload, clerk_headers)
    validate_error(replay, ApiErrorId.ERR_SAFE_VERSION_STALE.value)

    safe_after = read_safe(safe["id"])
    assert safe_after["balance_cents"] == 400000, (
        "the second bag removed nothing: expected balance_cents 400000, "
        f"got {safe_after['balance_cents']}"
    )
    assert safe_after["open_state"] == "UNLOCKED", (
        f"preparing a bag does not relock the safe, got {safe_after['open_state']}"
    )
    assert safe_after["version"] == stale_v + 1, (
        f"expected version {stale_v + 1}, got {safe_after['version']}"
    )

    deposits, meta = validate_paginated(
        api.list_deposits(clerk_headers, params={"sales_journal_id": journal["id"]})
    )
    assert meta["total_count"] == 1, (
        f"only the first bag exists: expected total_count 1, got {meta['total_count']}"
    )
    assert [row["id"] for row in deposits] == [deposit_a["id"]], (
        f"expected only {deposit_a['id']}, got {[row['id'] for row in deposits]}"
    )

    fresh_payload = dict(payload, expected_safe_version=safe_after["version"])
    deposit_b = validate_success(api.create_deposit(fresh_payload, clerk_headers), 201)
    assert deposit_b["status"] == "PREPARING", (
        "the rejection was purely version-based: expected PREPARING, "
        f"got {deposit_b['status']}"
    )
    assert deposit_b["declared_total_cents"] == 100000, (
        f"expected declared_total_cents 100000, got {deposit_b['declared_total_cents']}"
    )


def test_attribution_with_a_stale_case_version_returns_412(
    api, clerk_headers, manager_headers
):
    """PRD §2.11: "Appending a research attribution through `POST /cash-ops/variance-cases/{id}/attributions` requires `expected_variance_case_version` as a non-optional field of the request body, carrying the `version` of the target `VarianceCase` the researcher last observed."

    PRD §2.11: "Attributions legitimately accumulate, so a later entry observing the same status would itself succeed; if the case's current `version` no longer equals `expected_variance_case_version`, the append is rejected with `ERR_CASE_VERSION_STALE` (HTTP 412)."

    PRD §3.8: "An accepted entry appends an object carrying its `bucket`, `amount_cents`, `note` and a `recorded_at` stamp taken from the logical clock onto the case's `attributions` list, recomputes the three bucket totals from that list, and recomputes `unexplained_cents` as `total_variance_cents` less the sum of the three bucket totals."

    Design: Corner/cross_cutting_complexity_layers/attribution_with_a_stale_case_version_returns_412
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1981", name="Store 1981", region_code="WEST")
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
    session = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session["id"],
        pos_cash_sales_cents=50000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(session["id"], COUNT_67000, CLERK_3)
    reconcile_till(session["id"], CLERK_1)

    cases = list_cases(sales_journal_id=journal["id"], case_type="SESSION_VARIANCE")
    assert len(cases) == 1, f"expected one SESSION_VARIANCE case, got {len(cases)}"
    case = cases[0]
    assert case["total_variance_cents"] == 3000, (
        "the 3000-short reconcile fixes the case magnitude: expected 3000, "
        f"got {case['total_variance_cents']}"
    )
    stale_case_v = case["version"]

    append_attribution(
        case["id"], "REGISTER", 1000, stale_case_v, note="Refund keyed as cash"
    )

    resp = api.create_attribution(
        case["id"],
        {
            "bucket": "SAFE",
            "amount_cents": 500,
            "note": "Drop bag off by five dollars",
            "expected_variance_case_version": stale_case_v,
        },
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_VERSION_STALE.value)

    after = read_case(case["id"])
    assert len(after["attributions"]) == 1, (
        f"expected exactly 1 attribution entry, got {len(after['attributions'])}"
    )
    assert after["attributed_register_cents"] == 1000, (
        f"expected attributed_register_cents 1000, "
        f"got {after['attributed_register_cents']}"
    )
    assert after["attributed_safe_cents"] == 0, (
        f"the refused 500 never landed, got {after['attributed_safe_cents']}"
    )
    assert after["unexplained_cents"] == 2000, (
        f"expected unexplained_cents 2000, got {after['unexplained_cents']}"
    )
    assert after["total_variance_cents"] == 3000, (
        f"expected total_variance_cents 3000, got {after['total_variance_cents']}"
    )

    append_attribution(
        case["id"],
        "SAFE",
        500,
        after["version"],
        note="Drop bag off by five dollars",
        headers=manager_headers,
    )
    refreshed = read_case(case["id"])
    assert refreshed["attributed_safe_cents"] == 500, (
        "the same entry with the refreshed version succeeds: expected 500, "
        f"got {refreshed['attributed_safe_cents']}"
    )
    assert refreshed["unexplained_cents"] == 1500, (
        f"expected unexplained_cents 1500, got {refreshed['unexplained_cents']}"
    )


def test_safe_version_increments_on_every_write_and_never_on_a_read(
    api, clerk_headers, clerk_2_headers
):
    """PRD §2.4: "Most record types additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that begins at 1 on creation and increases by exactly 1 on every server-accepted mutation of that record."

    PRD §3.3: "A `CashOfficeClerk` or `StoreManager` files an open request, optionally recording a `reason`; the safe moves from `LOCKED` to `OPEN_REQUESTED`, `open_requested_at` takes the current logical clock, `open_requested_by_user_id` takes the requester's `X-User-ID`, and the safe's `version` increments by 1."

    PRD §3.6: "Sealing records `seal_number` and `sealed_by_user_id`, moves the deposit from `PREPARING` to `SEALED`, and ends the cash-office opening: the parent safe's `open_state` returns from `UNLOCKED` to `LOCKED` with `open_requested_at`, `open_requested_by_user_id` and `unlocked_at` all cleared, and the safe's `version` increments by 1 alongside the deposit's."

    Design: Corner/cross_cutting_complexity_layers/safe_version_increments_on_every_write_and_never_on_a_read
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1982", name="Store 1982", region_code="WEST")
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    journal = create_sales_journal(store["id"], BUSINESS_DATE)
    v_create = safe["version"]

    v_read_1 = validate_success(api.get_safe(safe["id"], clerk_headers))["version"]
    assert v_create == 1, f"version begins at 1 on creation, got {v_create}"
    assert v_read_1 == 1, f"the read did not advance the version, got {v_read_1}"

    v_arm = arm_open_request(safe["id"], CLERK_1, reason="Version walk")["version"]
    set_clock("2026-08-03T08:05:00Z")
    v_open = open_safe(safe["id"], CLERK_2)["version"]

    deposit = validate_success(
        api.create_deposit(
            {
                "safe_id": safe["id"],
                "sales_journal_id": journal["id"],
                "business_date": BUSINESS_DATE,
                "counted_lines": BAG_100000,
                "expected_safe_version": v_open,
            },
            clerk_headers,
        ),
        201,
    )
    assert deposit["version"] == 1, (
        f"a freshly prepared deposit is at version 1, got {deposit['version']}"
    )
    v_prepare = validate_success(api.get_safe(safe["id"], clerk_headers))["version"]

    sealed = validate_success(
        api.seal_deposit(deposit["id"], {"seal_number": "SEAL-1982"}, clerk_2_headers)
    )
    safe_sealed = validate_success(api.get_safe(safe["id"], clerk_headers))
    v_seal = safe_sealed["version"]

    assert v_arm == 2, f"arming is a write: expected version 2, got {v_arm}"
    assert v_open == 3, f"opening is a write: expected version 3, got {v_open}"
    assert v_prepare == 4, f"preparing is a write: expected version 4, got {v_prepare}"
    assert v_seal == 5, f"sealing is a write: expected version 5, got {v_seal}"

    assert sealed["status"] == "SEALED", (
        f"expected the sealed deposit's status SEALED, got {sealed['status']}"
    )
    assert sealed["version"] == 2, (
        "Deposit and Safe versions advance independently: expected deposit version 2 "
        f"(create, seal), got {sealed['version']}"
    )

    assert safe_sealed["open_state"] == "LOCKED", (
        f"sealing ends the opening, got {safe_sealed['open_state']}"
    )
    assert safe_sealed["balance_cents"] == 400000, (
        f"expected balance_cents 400000, got {safe_sealed['balance_cents']}"
    )
    assert safe_sealed["open_requested_at"] is None, (
        f"expected open_requested_at null, got {safe_sealed['open_requested_at']}"
    )

    v_read_2 = validate_success(api.get_safe(safe["id"], clerk_headers))["version"]
    assert v_read_2 == 5, (
        f"another interleaved read leaves the version untouched, got {v_read_2}"
    )


def test_single_event_threshold_fires_at_exactly_the_threshold_and_not_one_cent_below(
    api, clerk_headers
):
    """PRD §2.5: "`single_event_variance_threshold_cents` defaults to 2500 — twenty-five dollars — and is the absolute per-session over/short at or above which the cashier is flagged for coaching; it must be zero or greater."

    PRD §3.5: "In the same link, if the absolute value of the session's own `variance_cents` is at or above the store's `single_event_variance_threshold_cents` — twenty-five dollars by default — the cashier's `coaching_state` is set to `COACHING_DUE`, `coaching_due_at` is set to the current clock plus 72 hours, and a variance case is opened with `case_type` `SESSION_VARIANCE` naming this cashier and this sales journal."

    PRD §3.8: "For a `SESSION_VARIANCE` case the `total_variance_cents` is the absolute value of the triggering session's `variance_cents`; for a `ROLLING_PATTERN` case it is the cashier's freshly recomputed `rolling_absolute_variance_cents`; for a `DEPOSIT_CREDIT` case it is the absolute value of the deposit's `credit_variance_cents`."

    Design: Corner/cross_cutting_complexity_layers/single_event_threshold_fires_at_exactly_the_threshold_and_not_one_cent_below
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1983", name="Store 1983", region_code="WEST")
    assert store["single_event_variance_threshold_cents"] == 2500, (
        "the chain default is 2500, got "
        f"{store['single_event_variance_threshold_cents']}"
    )
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    cashier_a = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    cashier_b = create_cashier(
        store["id"], employee_code="E-200", display_name="Cashier 200"
    )
    journal = create_sales_journal(store["id"], BUSINESS_DATE)
    session_a = assign_till(
        journal["id"],
        cashier_a["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )
    session_b = assign_till(
        journal["id"],
        cashier_b["id"],
        safe["id"],
        register_number=2,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )

    set_clock("2026-08-03T17:00:00Z")
    for session in (session_a, session_b):
        close_till(
            session["id"],
            pos_cash_sales_cents=0,
            pos_card_sales_cents=0,
            pos_paid_out_cents=0,
        )
    blind_count(session_a["id"], COUNT_17500, CLERK_3)
    blind_count(session_b["id"], COUNT_17501, CLERK_3)

    reconciled_b = validate_success(
        api.reconcile_till_session(session_b["id"], clerk_headers)
    )
    assert reconciled_b["variance_cents"] == -2499, (
        f"17501 counted against 20000 expected is -2499, "
        f"got {reconciled_b['variance_cents']}"
    )
    cashier_b_after = read_cashier(cashier_b["id"])
    assert cashier_b_after["coaching_state"] == "NONE", (
        "one cent below the threshold leaves the cashier untouched, got "
        f"{cashier_b_after['coaching_state']}"
    )
    assert cashier_b_after["till_eligibility"] == "ELIGIBLE", (
        f"expected till_eligibility ELIGIBLE, "
        f"got {cashier_b_after['till_eligibility']}"
    )
    assert cashier_b_after["coaching_due_at"] is None, (
        f"expected coaching_due_at null, got {cashier_b_after['coaching_due_at']}"
    )

    reconciled_a = validate_success(
        api.reconcile_till_session(session_a["id"], clerk_headers)
    )
    assert reconciled_a["expected_cash_cents"] == 20000, (
        f"expected expected_cash_cents 20000, "
        f"got {reconciled_a['expected_cash_cents']}"
    )
    assert reconciled_a["variance_cents"] == -2500, (
        f"17500 counted against 20000 expected is exactly -2500, "
        f"got {reconciled_a['variance_cents']}"
    )
    assert reconciled_a["variance_basis"] == "DECLARED_DROPS", (
        f"no bag was ever re-counted, got {reconciled_a['variance_basis']}"
    )

    cashier_a_after = read_cashier(cashier_a["id"])
    assert cashier_a_after["coaching_state"] == "COACHING_DUE", (
        "the boundary itself fires coaching, got "
        f"{cashier_a_after['coaching_state']}"
    )
    assert parse_instant(cashier_a_after["coaching_due_at"]) == parse_instant(
        "2026-08-06T17:00:00Z"
    ), (
        "coaching_due_at is the clock plus 72 grace hours, expected "
        f"2026-08-06T17:00:00Z, got {cashier_a_after['coaching_due_at']}"
    )
    assert cashier_a_after["till_eligibility"] == "ELIGIBLE", (
        "a single-event breach does not restrict, got "
        f"{cashier_a_after['till_eligibility']}"
    )

    cases = list_cases(sales_journal_id=journal["id"])
    assert len(cases) == 1, (
        f"exactly one SESSION_VARIANCE case exists for the journal, got {len(cases)}"
    )
    case = cases[0]
    assert case["case_type"] == "SESSION_VARIANCE", (
        f"expected case_type SESSION_VARIANCE, got {case['case_type']}"
    )
    assert case["cashier_id"] == cashier_a["id"], (
        f"the case names {cashier_a['id']}, got {case['cashier_id']}"
    )
    assert case["total_variance_cents"] == 2500, (
        f"expected total_variance_cents 2500, got {case['total_variance_cents']}"
    )
    assert case["suspected_theft"] is False, (
        f"2500 is below the 50000 theft threshold, got {case['suspected_theft']}"
    )

    journal_after = read_journal(journal["id"])
    assert journal_after["open_case_count"] == 1, (
        f"expected open_case_count 1, got {journal_after['open_case_count']}"
    )
    assert journal_after["reconciled_session_count"] == 2, (
        f"expected reconciled_session_count 2, "
        f"got {journal_after['reconciled_session_count']}"
    )
    assert journal_after["net_unexplained_cents"] == 2500, (
        f"expected net_unexplained_cents 2500, "
        f"got {journal_after['net_unexplained_cents']}"
    )

    assert cashier_a_after["rolling_absolute_variance_cents"] == 2500, (
        "expected rolling_absolute_variance_cents 2500, got "
        f"{cashier_a_after['rolling_absolute_variance_cents']}"
    )
    assert cashier_b_after["rolling_absolute_variance_cents"] == 2499, (
        "expected rolling_absolute_variance_cents 2499, got "
        f"{cashier_b_after['rolling_absolute_variance_cents']}"
    )
    for label, record in (("A", cashier_a_after), ("B", cashier_b_after)):
        assert record["rolling_absolute_variance_cents"] < 10000, (
            f"cashier {label} stays below the 10000 rolling threshold, got "
            f"{record['rolling_absolute_variance_cents']}"
        )
        assert record["till_eligibility"] != "RESTRICTED", (
            f"cashier {label} must not be RESTRICTED, "
            f"got {record['till_eligibility']}"
        )
