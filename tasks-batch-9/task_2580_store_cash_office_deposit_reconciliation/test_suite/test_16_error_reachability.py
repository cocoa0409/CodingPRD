"""Error reachability: the eleven entity-specific not-found codes, a second arming of
an armed safe, and research against a closed variance case."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    CLERK_1,
    CLERK_3,
    LP_1,
    MANAGER_1,
    NOT_FOUND_ERROR_IDS,
    TEST_USERS,
    append_attribution,
    arm_open_request,
    assign_till,
    blind_count,
    close_case,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    escalate_case,
    list_cases,
    make_manager_headers,
    parse_instant,
    read_case,
    read_safe,
    reconcile_till,
    set_clock,
    validate_error,
)

#: One authenticated read per record type, each with an identifier no record uses.
NOT_FOUND_PROBES = [
    (
        "get_store",
        "00000000-0000-4000-8000-000000000001",
        "treasury_headers",
        ApiErrorId.ERR_STORE_NOT_FOUND,
    ),
    (
        "get_cashier",
        "00000000-0000-4000-8000-000000000002",
        "manager_headers",
        ApiErrorId.ERR_CASHIER_NOT_FOUND,
    ),
    (
        "get_safe",
        "00000000-0000-4000-8000-000000000003",
        "clerk_headers",
        ApiErrorId.ERR_SAFE_NOT_FOUND,
    ),
    (
        "get_sales_journal",
        "00000000-0000-4000-8000-000000000004",
        "clerk_headers",
        ApiErrorId.ERR_SALES_JOURNAL_NOT_FOUND,
    ),
    (
        "get_till_session",
        "00000000-0000-4000-8000-000000000005",
        "clerk_headers",
        ApiErrorId.ERR_TILL_SESSION_NOT_FOUND,
    ),
    (
        "get_safe_transaction",
        "00000000-0000-4000-8000-000000000006",
        "clerk_headers",
        ApiErrorId.ERR_SAFE_TRANSACTION_NOT_FOUND,
    ),
    (
        "get_deposit",
        "00000000-0000-4000-8000-000000000007",
        "clerk_headers",
        ApiErrorId.ERR_DEPOSIT_NOT_FOUND,
    ),
    (
        "get_bank_credit_record",
        "00000000-0000-4000-8000-000000000008",
        "treasury_headers",
        ApiErrorId.ERR_BANK_CREDIT_RECORD_NOT_FOUND,
    ),
    (
        "get_card_settlement",
        "00000000-0000-4000-8000-000000000009",
        "treasury_headers",
        ApiErrorId.ERR_CARD_SETTLEMENT_NOT_FOUND,
    ),
    (
        "get_variance_case",
        "00000000-0000-4000-8000-000000000010",
        "investigator_headers",
        ApiErrorId.ERR_VARIANCE_CASE_NOT_FOUND,
    ),
    (
        "get_change_order",
        "00000000-0000-4000-8000-000000000011",
        "clerk_headers",
        ApiErrorId.ERR_CHANGE_ORDER_NOT_FOUND,
    ),
]


def test_every_not_found_error_is_reachable(api: ApiClient):
    """PRD §2.12: "Fourth, path resolution: every templated `{id}` segment must resolve, validated left to right, yielding the not-found error for the record type that failed — `ERR_STORE_NOT_FOUND`, `ERR_CASHIER_NOT_FOUND`, `ERR_SAFE_NOT_FOUND`, `ERR_SALES_JOURNAL_NOT_FOUND`, `ERR_TILL_SESSION_NOT_FOUND`, `ERR_SAFE_TRANSACTION_NOT_FOUND`, `ERR_DEPOSIT_NOT_FOUND`, `ERR_BANK_CREDIT_RECORD_NOT_FOUND`, `ERR_CARD_SETTLEMENT_NOT_FOUND`, `ERR_VARIANCE_CASE_NOT_FOUND` or `ERR_CHANGE_ORDER_NOT_FOUND`, all HTTP 404."

    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/every_not_found_error_is_reachable
    """
    set_clock("2026-08-03T08:00:00Z")

    observed = []
    for method_name, unused_id, headers_key, expected_error in NOT_FOUND_PROBES:
        response = getattr(api, method_name)(unused_id, TEST_USERS[headers_key])

        assert response.status_code == 404, (
            f"{method_name} on an unused identifier must answer HTTP 404, "
            f"got {response.status_code}"
        )
        error_data = validate_error(response, expected_error.value)
        assert error_data["message"].strip(), (
            f"{method_name} must carry a non-empty data.message"
        )
        body = response.json()
        assert isinstance(body["meta"].get("api_request_id"), str), (
            f"{method_name} must carry a meta.api_request_id, got {body['meta']}"
        )
        observed.append(error_data["error_id"])

    assert len(set(observed)) == 11, (
        "all eleven not-found codes are distinct and entity-specific, so eleven "
        f"different error_id values were expected, got {sorted(set(observed))}"
    )
    assert set(observed) == set(NOT_FOUND_ERROR_IDS), (
        "no endpoint may fall back to a generic code; expected "
        f"{sorted(NOT_FOUND_ERROR_IDS)}, got {sorted(set(observed))}"
    )


def test_second_open_request_on_an_armed_safe_returns_open_request_active(
    api: ApiClient, manager_headers
):
    """PRD §3.3: "Arming a safe that is already `OPEN_REQUESTED` or already `UNLOCKED` is refused with `ERR_SAFE_OPEN_REQUEST_ACTIVE`, and arming a frozen safe is refused with `ERR_SAFE_FROZEN`."

    PRD §3.3: "A `CashOfficeClerk` or `StoreManager` files an open request, optionally recording a `reason`; the safe moves from `LOCKED` to `OPEN_REQUESTED`, `open_requested_at` takes the current logical clock, `open_requested_by_user_id` takes the requester's `X-User-ID`, and the safe's `version` increments by 1."

    PRD §2.8: "Arming a request stamps `open_requested_at` with the logical clock and `open_requested_by_user_id` with the requester."

    Design: Corner/errors/second_open_request_on_an_armed_safe_returns_open_request_active
    """
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(store_code="S-1965", name="Store 1965", region_code="WEST")
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )

    arm_open_request(safe["id"], CLERK_1, reason="First arming")
    set_clock("2026-08-03T09:03:00Z")

    response = api.create_open_request(
        safe["id"], {"reason": "Impatient second arming"}, manager_headers
    )
    validate_error(response, ApiErrorId.ERR_SAFE_OPEN_REQUEST_ACTIVE.value)

    refreshed_safe = read_safe(safe["id"])
    assert refreshed_safe["open_state"] == "OPEN_REQUESTED", (
        f"expected open_state OPEN_REQUESTED, got {refreshed_safe['open_state']}"
    )
    assert parse_instant(refreshed_safe["open_requested_at"]) == parse_instant(
        "2026-08-03T09:00:00Z"
    ), (
        "the rejected arming does not restart the time-delay clock, so "
        f"open_requested_at must stay 2026-08-03T09:00:00Z, "
        f"got {refreshed_safe['open_requested_at']}"
    )
    assert refreshed_safe["open_requested_by_user_id"] == CLERK_1, (
        f"expected open_requested_by_user_id {CLERK_1}, "
        f"got {refreshed_safe['open_requested_by_user_id']}"
    )
    assert refreshed_safe["version"] == 2, (
        "the rejected arming wrote nothing, so version must stay at 2 "
        f"(1 on commissioning, +1 for the first arming), got {refreshed_safe['version']}"
    )


def test_attribution_on_a_closed_case_returns_variance_case_invalid_state(
    api: ApiClient, clerk_headers
):
    """PRD §3.8: "The case must be `OPEN` or `RESEARCHING`; a case in any other status answers `ERR_VARIANCE_CASE_INVALID_STATE`."

    PRD §2.12: "Last, the two optimistic-concurrency checks of §2.11 (`ERR_SAFE_VERSION_STALE` and `ERR_CASE_VERSION_STALE`, HTTP 412) run after every other rule has been satisfied."

    PRD §3.8: "A `SUBSTANTIATED` finding moves the case to `CLOSED_SUBSTANTIATED`, writes the confirmed loss off the ledger with one safe transaction of kind `VARIANCE_ADJUSTMENT` against the store's earliest-created safe — the one with the lowest `created_at` — carrying `declared_amount_cents` equal to the case's `unexplained_cents`, recomputes that safe's `balance_cents`, and leaves the cashier's `till_eligibility` at `BARRED`."

    Design: Corner/errors/attribution_on_a_closed_case_returns_variance_case_invalid_state
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1966", name="Store 1966", region_code="WEST")
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
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
        pos_cash_sales_cents=100000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(
        session["id"], [{"denomination_cents": 2000, "quantity": 30}], CLERK_3
    )
    reconcile_till(session["id"], CLERK_1)

    session_cases = list_cases(
        sales_journal_id=journal["id"], case_type="SESSION_VARIANCE"
    )
    assert len(session_cases) == 1, (
        f"the 60000 short must open exactly one SESSION_VARIANCE case, "
        f"got {len(session_cases)}"
    )
    case = session_cases[0]

    append_attribution(
        case["id"],
        "REGISTER",
        1000,
        case["version"],
        note="Void keyed as cash",
        headers=make_manager_headers(MANAGER_1),
    )
    escalate_case(case["id"], reason="60000 short", user_id=MANAGER_1, as_manager=True)
    closed = close_case(
        case["id"], "SUBSTANTIATED", closing_note="Confirmed theft", user_id=LP_1
    )
    closed_version = closed["version"]

    response = api.create_attribution(
        case["id"],
        {
            "bucket": "SAFE",
            "amount_cents": 500,
            "note": "Late finding",
            "expected_variance_case_version": closed_version,
        },
        clerk_headers,
    )
    validate_error(response, ApiErrorId.ERR_VARIANCE_CASE_INVALID_STATE.value)

    refreshed_case = read_case(case["id"])
    assert refreshed_case["status"] == "CLOSED_SUBSTANTIATED", (
        f"expected status CLOSED_SUBSTANTIATED, got {refreshed_case['status']}"
    )
    assert len(refreshed_case["attributions"]) == 1, (
        "the rejected entry appends nothing, so attributions must hold exactly the "
        f"one accepted entry, got {len(refreshed_case['attributions'])}"
    )
    assert refreshed_case["attributed_safe_cents"] == 0, (
        f"expected attributed_safe_cents 0, "
        f"got {refreshed_case['attributed_safe_cents']}"
    )
    assert refreshed_case["version"] == closed_version, (
        "the version supplied was current, so the rejection is a state rejection and "
        f"wrote nothing: expected version {closed_version}, "
        f"got {refreshed_case['version']}"
    )
