"""Uniqueness, occupancy and aggregate-capacity rejections in the cash office."""

from test_helpers import (
    CLERK_1,
    CLERK_2,
    CLERK_3,
    ApiErrorId,
    append_attribution,
    arm_open_request,
    assign_till,
    attribution_payload,
    blind_count,
    card_settlement_payload,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    list_cases,
    open_safe,
    parse_instant,
    pickup_deposit,
    post_bank_credit_record,
    post_card_settlement,
    post_tenders,
    prepare_deposit,
    read_case,
    read_cashier,
    read_deposit,
    read_journal,
    read_safe,
    reconcile_bank,
    reconcile_till,
    schedule_pickup,
    seal_deposit,
    set_clock,
    till_session_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

BAG_100000 = [{"denomination_cents": 2000, "quantity": 50}]
BAG_200000 = [{"denomination_cents": 2000, "quantity": 100}]
COUNT_67000 = [
    {"denomination_cents": 2000, "quantity": 33},
    {"denomination_cents": 1000, "quantity": 1},
]


def test_register_occupied_rejects_a_second_till_on_the_same_register(
    api, manager_headers
):
    """PRD §3.2: "Separately, no two sessions on the same journal may hold the same `register_number` with overlapping windows — an `ACTIVE` or `PENDING_COUNT` session already holding that register yields `ERR_REGISTER_OCCUPIED`."

    Design: Corner/validations/register_occupied_rejects_a_second_till_on_the_same_register
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1940", region_code="WEST")
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
    journal = create_sales_journal(store["id"], "2026-08-03")
    assign_till(
        journal["id"],
        cashier_a["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )

    resp = api.create_till_session(
        till_session_payload(
            journal["id"],
            cashier_b["id"],
            safe["id"],
            register_number=1,
            shift_start_at="2026-08-03T12:00:00Z",
            shift_end_at="2026-08-03T20:00:00Z",
            starting_bank_cents=20000,
        ),
        manager_headers,
    )
    # E-200 has no other session, so the shift-overlap rule cannot be the answer.
    validate_error(resp, ApiErrorId.ERR_REGISTER_OCCUPIED.value)

    journal_after = read_journal(journal["id"])
    assert journal_after["session_count"] == 1, (
        f"expected session_count 1, got {journal_after['session_count']}"
    )
    safe_after = read_safe(safe["id"])
    assert safe_after["balance_cents"] == 480000, (
        f"only one starting bank left the safe: expected 480000, "
        f"got {safe_after['balance_cents']}"
    )


def test_duplicate_journal_for_the_same_business_date_rejected(api, clerk_headers):
    """PRD §3.1: "Exactly one journal may exist per store and business date; a second attempt at the same pair is rejected with `ERR_DUPLICATE_BUSINESS_DATE`."

    Design: Corner/validations/duplicate_journal_for_the_same_business_date_rejected
    """
    set_clock("2026-08-03T08:00:00Z")
    store_a = create_store(store_code="S-1941", region_code="WEST")
    store_b = create_store(store_code="S-1942", region_code="EAST")
    create_sales_journal(store_a["id"], "2026-08-03")

    duplicate = api.create_sales_journal(
        {"store_id": store_a["id"], "business_date": "2026-08-03"}, clerk_headers
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_BUSINESS_DATE.value)

    other_store = api.create_sales_journal(
        {"store_id": store_b["id"], "business_date": "2026-08-03"}, clerk_headers
    )
    created = validate_success(other_store, 201)
    assert created["business_date"] == "2026-08-03", (
        "uniqueness is scoped to the store, not global: "
        f"got business_date {created['business_date']}"
    )

    _, meta = validate_paginated(
        api.list_sales_journals(
            clerk_headers,
            params={"store_id": store_a["id"], "business_date": "2026-08-03"},
        )
    )
    assert meta["total_count"] == 1, (
        f"expected total_count 1 for the store/date pair, got {meta['total_count']}"
    )


def test_post_tenders_twice_rejected(api, clerk_headers):
    """PRD §3.1: "Tenders are posted exactly once — a second attempt is refused with `ERR_TENDERS_ALREADY_POSTED`, which is also the answer whenever the journal's `status` is anything other than `OPEN`."

    Design: Corner/validations/post_tenders_twice_rejected
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1943", region_code="WEST")
    journal = create_sales_journal(store["id"], "2026-08-03")
    post_tenders(journal["id"], 100000, 50000)

    resp = api.post_tenders(
        journal["id"],
        {"journal_cash_sales_cents": 999999, "journal_card_sales_cents": 50000},
        clerk_headers,
    )
    validate_error(resp, ApiErrorId.ERR_TENDERS_ALREADY_POSTED.value)

    journal_after = read_journal(journal["id"])
    assert journal_after["journal_cash_sales_cents"] == 100000, (
        f"expected 100000, got {journal_after['journal_cash_sales_cents']}"
    )
    assert journal_after["journal_card_sales_cents"] == 50000, (
        f"expected 50000, got {journal_after['journal_card_sales_cents']}"
    )
    assert journal_after["status"] == "TENDERS_POSTED", (
        f"expected TENDERS_POSTED, got {journal_after['status']}"
    )


def test_second_settlement_for_the_same_network_rejected(api, treasury_headers):
    """PRD §3.7: "Only one settlement may exist per sales journal and network pair; a second answers `ERR_SETTLEMENT_ALREADY_POSTED`."

    Design: Corner/validations/second_settlement_for_the_same_network_rejected
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1944", region_code="WEST")
    journal = create_sales_journal(store["id"], "2026-08-03")
    first = post_card_settlement(
        journal["id"],
        gross_card_sales_cents=50000,
        txn_count=20,
        monthly_volume_cents=1000000,
        funded_amount_cents=48510,
        card_network="VISA_MC",
    )

    resp = api.create_card_settlement(
        card_settlement_payload(
            journal["id"],
            60000,
            25,
            1000000,
            58200,
            card_network="VISA_MC",
        ),
        treasury_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_ALREADY_POSTED.value)

    stored = validate_success(api.get_card_settlement(first["id"], treasury_headers))
    assert stored["gross_card_sales_cents"] == 50000, (
        f"the rejected advice must not touch the stored row: "
        f"expected 50000, got {stored['gross_card_sales_cents']}"
    )
    assert stored["expected_fee_cents"] == 1490, (
        f"expected expected_fee_cents 1490, got {stored['expected_fee_cents']}"
    )

    amex = validate_success(
        api.create_card_settlement(
            card_settlement_payload(
                journal["id"],
                100000,
                10,
                1000000,
                97030,
                card_network="AMEX",
            ),
            treasury_headers,
        ),
        201,
    )
    assert amex["expected_fee_cents"] == 2970, (
        f"expected expected_fee_cents 2970, got {amex['expected_fee_cents']}"
    )
    assert amex["settlement_status"] == "MATCHED", (
        f"expected MATCHED, got {amex['settlement_status']}"
    )

    journal_after = read_journal(journal["id"])
    assert journal_after["settlement_count"] == 2, (
        f"expected settlement_count 2, got {journal_after['settlement_count']}"
    )
    assert journal_after["settlement_variance_total_cents"] == 0, (
        f"expected settlement_variance_total_cents 0, "
        f"got {journal_after['settlement_variance_total_cents']}"
    )


def test_pickup_capacity_exceeded_by_two_disjoint_windows(api, clerk_headers):
    """PRD §3.6: "Second, the number of the store's deposits sharing this deposit's `business_date` and sitting in `SCHEDULED` or `IN_TRANSIT` must be strictly below the store's `max_daily_pickups`; at or above it the answer is `ERR_PICKUP_CAPACITY_EXCEEDED`."

    Design: Corner/validations/pickup_capacity_exceeded_by_two_disjoint_windows
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1945", region_code="WEST", max_daily_pickups=1)
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    arm_open_request(safe["id"], CLERK_1, reason="First bag")
    set_clock("2026-08-03T08:05:00Z")
    open_safe(safe["id"], CLERK_2)
    deposit_a = prepare_deposit(
        safe["id"],
        journal["id"],
        BAG_100000,
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
    )
    seal_deposit(deposit_a["id"], "SEAL-A", CLERK_2)

    arm_open_request(safe["id"], CLERK_1, reason="Second bag")
    set_clock("2026-08-03T08:15:00Z")
    open_safe(safe["id"], CLERK_2)
    deposit_b = prepare_deposit(
        safe["id"],
        journal["id"],
        BAG_100000,
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
    )
    seal_deposit(deposit_b["id"], "SEAL-B", CLERK_2)

    schedule_pickup(
        deposit_a["id"],
        "2026-08-03T09:00:00Z",
        "2026-08-03T09:30:00Z",
        carrier_reference="CAR-1945-A",
        user_id=CLERK_1,
    )

    resp = api.schedule_pickup(
        deposit_b["id"],
        {
            "pickup_window_start": "2026-08-03T14:00:00Z",
            "pickup_window_end": "2026-08-03T14:30:00Z",
            "carrier_reference": "CAR-1945-B",
        },
        clerk_headers,
    )
    # The buffered spans 08:30-10:00 and 13:30-15:00 do not intersect, so the
    # aggregate capacity limit is the only rule the request can breach.
    validate_error(resp, ApiErrorId.ERR_PICKUP_CAPACITY_EXCEEDED.value)

    dep_b = read_deposit(deposit_b["id"])
    assert dep_b["status"] == "SEALED", f"expected SEALED, got {dep_b['status']}"
    assert dep_b["pickup_window_start"] is None, (
        f"expected pickup_window_start null, got {dep_b['pickup_window_start']}"
    )
    assert dep_b["pickup_window_end"] is None, (
        f"expected pickup_window_end null, got {dep_b['pickup_window_end']}"
    )

    dep_a = read_deposit(deposit_a["id"])
    assert dep_a["status"] == "SCHEDULED", f"expected SCHEDULED, got {dep_a['status']}"
    assert parse_instant(dep_a["pickup_window_start"]) == parse_instant(
        "2026-08-03T09:00:00Z"
    ), (
        f"expected pickup_window_start 2026-08-03T09:00:00Z, "
        f"got {dep_a['pickup_window_start']}"
    )

    safe_after = read_safe(safe["id"])
    assert safe_after["balance_cents"] == 300000, (
        f"expected 500000 - 100000 - 100000 == 300000, "
        f"got {safe_after['balance_cents']}"
    )
    assert safe_after["open_state"] == "LOCKED", (
        f"expected LOCKED, got {safe_after['open_state']}"
    )


def test_attribution_beyond_the_case_total_rejected(api, clerk_headers):
    """PRD §3.8: "The entry may not push the research outside the case: the sum of `attributed_register_cents`, `attributed_safe_cents`, `attributed_bank_cents` and the new `amount_cents` must be at least zero and at most `total_variance_cents`, and an entry that would violate either bound is refused with `ERR_ATTRIBUTION_EXCEEDS_VARIANCE`."

    Design: Corner/validations/attribution_beyond_the_case_total_rejected
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1946", region_code="WEST")
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    cashier = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    journal = create_sales_journal(store["id"], "2026-08-03")
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
    after_first = append_attribution(
        case["id"], "REGISTER", 2000, case["version"], note="Refund keyed as cash"
    )

    resp = api.create_attribution(
        case["id"],
        attribution_payload(
            "SAFE",
            1500,
            after_first["version"],
            note="Suspected strap miscount in the safe",
        ),
        clerk_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ATTRIBUTION_EXCEEDS_VARIANCE.value)

    case_after = read_case(case["id"])
    assert case_after["total_variance_cents"] == 3000, (
        f"expected total_variance_cents 3000, got {case_after['total_variance_cents']}"
    )
    assert case_after["attributed_register_cents"] == 2000, (
        f"expected attributed_register_cents 2000, "
        f"got {case_after['attributed_register_cents']}"
    )
    assert case_after["attributed_safe_cents"] == 0, (
        f"expected attributed_safe_cents 0, got {case_after['attributed_safe_cents']}"
    )
    assert case_after["unexplained_cents"] == 1000, (
        f"expected unexplained_cents 1000, got {case_after['unexplained_cents']}"
    )
    assert len(case_after["attributions"]) == 1, (
        f"the rejected entry left no trace: expected 1 attribution, "
        f"got {len(case_after['attributions'])}"
    )
    assert case_after["version"] == after_first["version"], (
        f"expected version {after_first['version']}, got {case_after['version']}"
    )
    assert case_after["status"] == "RESEARCHING", (
        f"expected RESEARCHING, got {case_after['status']}"
    )

    journal_after = read_journal(journal["id"])
    assert journal_after["net_unexplained_cents"] == 1000, (
        f"expected net_unexplained_cents 1000, "
        f"got {journal_after['net_unexplained_cents']}"
    )


def test_escalation_below_threshold_without_pattern_rejected(api, manager_headers):
    """PRD §3.8: "It is gated on evidence: either the case's `total_variance_cents` is at or above the store's `theft_escalation_threshold_cents`, or the case's cashier has at least two other variance cases created within the preceding 90 days — the rolling-pattern route. Neither condition holding means `ERR_ESCALATION_THRESHOLD_NOT_MET`."

    Design: Corner/validations/escalation_below_threshold_without_pattern_rejected
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1947", region_code="WEST")
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    cashier = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    journal = create_sales_journal(store["id"], "2026-08-03")
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
    append_attribution(
        case["id"],
        "REGISTER",
        1000,
        case["version"],
        note="Partial explanation",
        headers=manager_headers,
    )

    resp = api.escalate_variance_case(
        case["id"], {"escalation_reason": "Manager suspects theft"}, manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_ESCALATION_THRESHOLD_NOT_MET.value)

    case_after = read_case(case["id"])
    assert case_after["status"] == "RESEARCHING", (
        f"expected RESEARCHING, got {case_after['status']}"
    )
    assert case_after["suspected_theft"] is False, (
        f"expected suspected_theft False, got {case_after['suspected_theft']}"
    )
    assert case_after["escalated_by_user_id"] is None, (
        f"expected escalated_by_user_id null, got {case_after['escalated_by_user_id']}"
    )

    cashier_after = read_cashier(cashier["id"])
    assert cashier_after["till_eligibility"] == "ELIGIBLE", (
        f"the failed escalation bars nobody: expected ELIGIBLE, "
        f"got {cashier_after['till_eligibility']}"
    )

    safe_after = read_safe(safe["id"])
    assert safe_after["posture"] == "OPEN", (
        f"no fan-out freeze from a rejected escalation: expected OPEN, "
        f"got {safe_after['posture']}"
    )


def test_already_matched_bank_record_resubmitted_rejected(api, treasury_headers):
    """PRD §3.7: "A record whose `credit_type` is `PROVISIONAL`, or one belonging to another store, is refused with `ERR_CREDIT_TYPE_INVALID`; a record whose `match_state` is already `MATCHED` is refused with `ERR_BANK_CREDIT_ALREADY_MATCHED`; an unknown identifier is refused with `ERR_BANK_CREDIT_RECORD_NOT_FOUND`."

    Design: Corner/validations/already_matched_bank_record_resubmitted_rejected
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1948", region_code="WEST")
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    arm_open_request(safe["id"], CLERK_1, reason="Deposit preparation")
    set_clock("2026-08-03T08:05:00Z")
    open_safe(safe["id"], CLERK_2)
    deposit = prepare_deposit(
        safe["id"],
        journal["id"],
        BAG_200000,
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
    )
    seal_deposit(deposit["id"], "SEAL-1", CLERK_2)
    schedule_pickup(
        deposit["id"],
        "2026-08-03T10:00:00Z",
        "2026-08-03T10:30:00Z",
        carrier_reference="CAR-1948-A",
        user_id=CLERK_1,
    )
    set_clock("2026-08-03T10:15:00Z")
    pickup_deposit(deposit["id"], "2026-08-03T10:15:00Z", carrier_signature="J.CARRIER")

    final_record = post_bank_credit_record(
        store["id"],
        198000,
        credit_type="FINAL",
        deposit_id=deposit["id"],
        value_date="2026-08-04",
        bank_reference="BR-1948-F",
    )
    reconcile_bank(deposit["id"], [final_record["id"]])

    cases = list_cases(deposit_id=deposit["id"])
    assert len(cases) == 1, f"expected one DEPOSIT_CREDIT case, got {len(cases)}"
    case = cases[0]
    append_attribution(
        case["id"],
        "BANK",
        730,
        case["version"],
        note="Carrier fee deducted twice by the bank",
    )
    adjustment = post_bank_credit_record(
        store["id"],
        730,
        credit_type="ADJUSTMENT",
        deposit_id=deposit["id"],
        value_date="2026-08-05",
        bank_reference="BR-1948-ADJ",
    )

    resp = api.reconcile_bank(
        deposit["id"],
        {"bank_credit_record_ids": [final_record["id"], adjustment["id"]]},
        treasury_headers,
    )
    validate_error(resp, ApiErrorId.ERR_BANK_CREDIT_ALREADY_MATCHED.value)

    deposit_after = read_deposit(deposit["id"])
    assert deposit_after["status"] == "DISCREPANT", (
        f"expected DISCREPANT, got {deposit_after['status']}"
    )
    assert deposit_after["credited_total_cents"] == 198000, (
        f"the adjustment must not be silently absorbed: expected 198000, "
        f"got {deposit_after['credited_total_cents']}"
    )
    assert deposit_after["credit_variance_cents"] == -730, (
        f"expected credit_variance_cents -730, "
        f"got {deposit_after['credit_variance_cents']}"
    )

    adj_after = validate_success(
        api.get_bank_credit_record(adjustment["id"], treasury_headers)
    )
    assert adj_after["match_state"] == "UNMATCHED", (
        f"the rejected call consumed nothing: expected UNMATCHED, "
        f"got {adj_after['match_state']}"
    )
    final_after = validate_success(
        api.get_bank_credit_record(final_record["id"], treasury_headers)
    )
    assert final_after["match_state"] == "MATCHED", (
        f"expected MATCHED, got {final_after['match_state']}"
    )

    case_after = read_case(case["id"])
    assert case_after["status"] == "EXPLAINED", (
        f"expected EXPLAINED, got {case_after['status']}"
    )
    assert case_after["unexplained_cents"] == 0, (
        f"expected unexplained_cents 0, got {case_after['unexplained_cents']}"
    )
