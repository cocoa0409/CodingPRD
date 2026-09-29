"""Record shapes, policy defaults, lookups and missing-record answers across the cash office."""

from test_helpers import (
    ApiErrorId,
    assert_cashier,
    assert_safe_transaction,
    assert_store,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    parse_instant,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

#: Syntactically valid identifiers that resolve to no record in an empty database.
UNKNOWN_TILL_SESSION_ID = "11111111-1111-1111-1111-111111111111"
UNKNOWN_SAFE_ID = "22222222-2222-2222-2222-222222222222"
UNKNOWN_SALES_JOURNAL_ID = "33333333-3333-3333-3333-333333333333"


def test_store_creation_returns_full_entity_and_response_envelope(api, treasury_headers):
    """PRD §4: "Creating a new record answers HTTP 201 with the created record in `data`."

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD §2.4: "Most record types additionally carry `updated_at`, refreshed on every
    mutation, and `version`, an integer that begins at 1 on creation and increases by
    exactly 1 on every server-accepted mutation of that record."

    Design: Corner/entities/store_creation_returns_full_entity_and_response_envelope
    """
    set_clock("2026-08-03T08:00:00Z", treasury_headers)

    resp = api.create_store(
        {
            "store_code": "S-1901",
            "name": "Store 1901",
            "region_code": "WEST",
            "safe_time_delay_minutes": 7,
            "safe_open_window_minutes": 12,
            "dual_control_required": True,
            "pickup_buffer_minutes": 45,
            "max_daily_pickups": 3,
            "single_event_variance_threshold_cents": 3000,
            "rolling_variance_threshold_cents": 12000,
            "rolling_window_days": 45,
            "theft_escalation_threshold_cents": 60000,
            "provisional_credit_cap_cents": 400000,
            "seasonal_profile": "HOLIDAY",
        },
        treasury_headers,
    )
    assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body["response_type"] == "object", (
        f"expected response_type object for a single resource, got {body['response_type']}"
    )
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        f"meta.api_request_id must be present and non-empty, got {meta.get('api_request_id')}"
    )
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']}"
    )
    assert (
        isinstance(meta.get("api_request_timestamp"), str) and meta["api_request_timestamp"]
    ), f"meta.api_request_timestamp must be present and non-empty, got {meta.get('api_request_timestamp')}"

    data = validate_success(resp, 201)
    assert_store(data)

    assert data["store_code"] == "S-1901", f"expected S-1901, got {data['store_code']}"
    assert data["name"] == "Store 1901", f"expected Store 1901, got {data['name']}"
    assert data["region_code"] == "WEST", f"expected WEST, got {data['region_code']}"

    assert data["safe_time_delay_minutes"] == 7, (
        f"expected 7, got {data['safe_time_delay_minutes']}"
    )
    assert data["safe_open_window_minutes"] == 12, (
        f"expected 12, got {data['safe_open_window_minutes']}"
    )
    assert data["dual_control_required"] is True, (
        f"expected True, got {data['dual_control_required']}"
    )
    assert data["pickup_buffer_minutes"] == 45, (
        f"expected 45, got {data['pickup_buffer_minutes']}"
    )
    assert data["max_daily_pickups"] == 3, f"expected 3, got {data['max_daily_pickups']}"

    assert data["single_event_variance_threshold_cents"] == 3000, (
        f"expected 3000, got {data['single_event_variance_threshold_cents']}"
    )
    assert data["rolling_variance_threshold_cents"] == 12000, (
        f"expected 12000, got {data['rolling_variance_threshold_cents']}"
    )
    assert data["rolling_window_days"] == 45, (
        f"expected 45, got {data['rolling_window_days']}"
    )
    assert data["theft_escalation_threshold_cents"] == 60000, (
        f"expected 60000, got {data['theft_escalation_threshold_cents']}"
    )
    assert data["provisional_credit_cap_cents"] == 400000, (
        f"expected 400000, got {data['provisional_credit_cap_cents']}"
    )
    assert data["seasonal_profile"] == "HOLIDAY", (
        f"expected HOLIDAY, got {data['seasonal_profile']}"
    )

    assert is_valid_uuid(data["id"]), f"id must be a server-minted UUID, got {data['id']}"
    assert data["version"] == 1, f"version begins at 1 on creation, got {data['version']}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be an ISO 8601 UTC instant, got {data['created_at']}"
    )
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC instant, got {data['updated_at']}"
    )


def test_store_policy_defaults_applied_when_omitted(api, treasury_headers):
    """PRD §2.5: "Every remaining parameter is optional on creation and takes a chain default when omitted."

    PRD §2.5: "`safe_time_delay_minutes` is the time-delay device setting — the number of
    minutes that must elapse between an open request and the open — and defaults to 5, with
    an accepted range from 0 through 120 inclusive."
    PRD §2.5: "`safe_open_window_minutes` is how long after the delay elapses the request
    stays executable; it defaults to 10 and ranges from 1 through 240 inclusive."
    PRD §2.5: "`dual_control_required` defaults to true and, when true, forces safe opens
    and deposit seals to be performed by a second, different `X-User-ID`."
    PRD §2.5: "`pickup_buffer_minutes` defaults to 30 and ranges from 0 through 240
    inclusive; it is applied to both sides of an already-scheduled armored pickup window
    before overlap testing."
    PRD §2.5: "`max_daily_pickups` defaults to 2 and ranges from 1 through 6 inclusive."
    PRD §2.5: "`single_event_variance_threshold_cents` defaults to 2500 — twenty-five
    dollars — and is the absolute per-session over/short at or above which the cashier is
    flagged for coaching; it must be zero or greater."
    PRD §2.5: "`rolling_variance_threshold_cents` defaults to 10000 and is the rolling
    absolute over/short at or above which the cashier is restricted and investigated."
    PRD §2.5: "`rolling_window_days` defaults to 30 and ranges from 1 through 365 inclusive."
    PRD §2.5: "`theft_escalation_threshold_cents` defaults to 50000 — five hundred dollars —
    and is the case total at or above which a variance case is marked as suspected theft."
    PRD §2.5: "`provisional_credit_cap_cents` defaults to 500000 and is the per-deposit
    ceiling on provisional credit, applied identically to the smart-safe and the carrier
    variants."
    PRD §2.5: "`seasonal_profile` defaults to `BASELINE` and may otherwise be
    `BACK_TO_SCHOOL` or `HOLIDAY`; it is the default seasonal demand profile used by
    change-order forecasting."

    Design: Corner/entities/store_policy_defaults_applied_when_omitted
    """
    set_clock("2026-08-03T08:00:00Z", treasury_headers)

    data = validate_success(
        api.create_store(
            {"store_code": "S-1902", "name": "Store 1902", "region_code": "EAST"},
            treasury_headers,
        ),
        201,
    )

    assert data["safe_time_delay_minutes"] == 5, (
        f"expected the chain default 5, got {data['safe_time_delay_minutes']}"
    )
    assert data["safe_open_window_minutes"] == 10, (
        f"expected the chain default 10, got {data['safe_open_window_minutes']}"
    )
    assert data["dual_control_required"] is True, (
        f"expected the chain default True, got {data['dual_control_required']}"
    )
    assert data["pickup_buffer_minutes"] == 30, (
        f"expected the chain default 30, got {data['pickup_buffer_minutes']}"
    )
    assert data["max_daily_pickups"] == 2, (
        f"expected the chain default 2, got {data['max_daily_pickups']}"
    )
    assert data["single_event_variance_threshold_cents"] == 2500, (
        f"expected the chain default 2500, got {data['single_event_variance_threshold_cents']}"
    )
    assert data["rolling_variance_threshold_cents"] == 10000, (
        f"expected the chain default 10000, got {data['rolling_variance_threshold_cents']}"
    )
    assert data["rolling_window_days"] == 30, (
        f"expected the chain default 30, got {data['rolling_window_days']}"
    )
    assert data["theft_escalation_threshold_cents"] == 50000, (
        f"expected the chain default 50000, got {data['theft_escalation_threshold_cents']}"
    )
    assert data["provisional_credit_cap_cents"] == 500000, (
        f"expected the chain default 500000, got {data['provisional_credit_cap_cents']}"
    )
    assert data["seasonal_profile"] == "BASELINE", (
        f"expected the chain default BASELINE, got {data['seasonal_profile']}"
    )


def test_store_read_returns_stored_policy_fields(api, treasury_headers, clerk_headers):
    """PRD §2.4: "Most record types additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that begins at 1 on creation and increases by exactly 1 on every server-accepted mutation of that record."

    PRD §2.5: "`theft_escalation_threshold_cents` defaults to 50000 — five hundred dollars —
    and is the case total at or above which a variance case is marked as suspected theft."
    PRD §2.5: "`seasonal_profile` defaults to `BASELINE` and may otherwise be
    `BACK_TO_SCHOOL` or `HOLIDAY`; it is the default seasonal demand profile used by
    change-order forecasting."

    Design: Corner/entities/store_read_returns_stored_policy_fields
    """
    set_clock("2026-08-03T08:00:00Z", treasury_headers)

    created = validate_success(
        api.create_store(
            {
                "store_code": "S-1903",
                "name": "Store 1903",
                "region_code": "WEST",
                "theft_escalation_threshold_cents": 75000,
                "seasonal_profile": "BACK_TO_SCHOOL",
            },
            treasury_headers,
        ),
        201,
    )
    store_id = created["id"]

    resp = api.get_store(store_id, clerk_headers)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["response_type"] == "object", (
        f"expected response_type object, got {resp.json()['response_type']}"
    )
    data = validate_success(resp)
    assert_store(data)

    assert data["id"] == store_id, f"expected {store_id}, got {data['id']}"
    assert data["store_code"] == "S-1903", f"expected S-1903, got {data['store_code']}"
    assert data["theft_escalation_threshold_cents"] == 75000, (
        f"expected 75000 to survive the round trip, got "
        f"{data['theft_escalation_threshold_cents']}"
    )
    assert data["seasonal_profile"] == "BACK_TO_SCHOOL", (
        f"expected BACK_TO_SCHOOL to survive the round trip, got {data['seasonal_profile']}"
    )
    assert data["version"] == 1, (
        f"a read performs no mutation, so version stays 1, got {data['version']}"
    )


def test_cashier_listing_filters_by_store_id(api, treasury_headers, manager_headers):
    """PRD §3.2: "Cashiers may be listed with `store_id`, `till_eligibility` and `coaching_state` filters."

    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` — the number of records matching the filters before pagination is
    applied — and `has_more`, which is true exactly when records matching the filters
    remain beyond the current page."
    PRD §2.3: "`limit` caps the number of records returned; it defaults to 10, may be no
    smaller than 1, and may be no larger than 100."
    PRD §3.2: "A new cashier record starts with `till_eligibility` `ELIGIBLE` when the
    enrolment leaves that field out, `coaching_state` `NONE`,
    `rolling_absolute_variance_cents` zero, `rolling_net_variance_cents` zero,
    `reconciled_session_count` zero and `open_case_count` zero, and its `coaching_due_at`
    is null while `coaching_state` remains `NONE`."

    Design: Corner/entities/cashier_listing_filters_by_store_id
    """
    set_clock("2026-08-03T08:00:00Z", treasury_headers)

    store_a = validate_success(
        api.create_store(
            {"store_code": "S-1904", "name": "Store 1904", "region_code": "WEST"},
            treasury_headers,
        ),
        201,
    )
    store_b = validate_success(
        api.create_store(
            {"store_code": "S-1905", "name": "Store 1905", "region_code": "EAST"},
            treasury_headers,
        ),
        201,
    )

    cashier_a1 = validate_success(
        api.create_cashier(
            {
                "store_id": store_a["id"],
                "employee_code": "E-100",
                "display_name": "Cashier 100",
            },
            manager_headers,
        ),
        201,
    )
    cashier_a2 = validate_success(
        api.create_cashier(
            {
                "store_id": store_a["id"],
                "employee_code": "E-200",
                "display_name": "Cashier 200",
            },
            manager_headers,
        ),
        201,
    )
    cashier_b1 = validate_success(
        api.create_cashier(
            {
                "store_id": store_b["id"],
                "employee_code": "E-300",
                "display_name": "Cashier 300",
            },
            manager_headers,
        ),
        201,
    )

    resp = api.list_cashiers(manager_headers, params={"store_id": store_a["id"]})
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["response_type"] == "array", (
        f"expected response_type array for a list, got {resp.json()['response_type']}"
    )
    rows, meta = validate_paginated(resp)

    assert meta["total_count"] == 2, (
        f"two cashiers match the S-1904 filter, got total_count {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"no records remain beyond the page, got has_more {meta['has_more']}"
    )
    assert meta["limit"] == 10, f"limit defaults to 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"offset defaults to 0, got {meta['offset']}"

    returned_ids = {row["id"] for row in rows}
    assert returned_ids == {cashier_a1["id"], cashier_a2["id"]}, (
        f"expected exactly the two S-1904 cashiers, got {sorted(returned_ids)}"
    )
    assert cashier_b1["id"] not in returned_ids, (
        "the S-1905 cashier E-300 must be absent from the S-1904 filter"
    )

    for row in rows:
        assert_cashier(row)
        assert row["till_eligibility"] == "ELIGIBLE", (
            f"a new cashier starts ELIGIBLE, got {row['till_eligibility']}"
        )
        assert row["coaching_state"] == "NONE", (
            f"a new cashier starts with coaching_state NONE, got {row['coaching_state']}"
        )


def test_cashier_creation_missing_display_name_returns_invalid_request(
    api, treasury_headers, manager_headers
):
    """PRD §3.2: "A `StoreManager` enrolls a cashier by supplying the `store_id` of the employing store, an `employee_code` that must be unique within that store, and a `display_name`; the enrolment may optionally set `till_eligibility` directly."

    PRD §2.12: "Third, request-body shape: required fields present, enum members valid,
    integer cents fields integral and non-negative subject to the two exceptions in §2.10,
    denomination lines drawn from the permitted set with non-negative quantities,
    `shift_end_at` strictly after `shift_start_at`, `pickup_window_end` strictly after
    `pickup_window_start`, `days_covered` between 1 and 14 inclusive, and `growth_pct`
    between -0.50 and 2.00 inclusive."

    Design: Corner/entities/cashier_creation_missing_display_name_returns_invalid_request
    """
    set_clock("2026-08-03T08:00:00Z", treasury_headers)

    store = validate_success(
        api.create_store(
            {"store_code": "S-1906", "name": "Store 1906", "region_code": "WEST"},
            treasury_headers,
        ),
        201,
    )

    resp = api.create_cashier(
        {"store_id": store["id"], "employee_code": "E-400"}, manager_headers
    )
    assert resp.json()["response_type"] == "error", (
        f"expected response_type error, got {resp.json()['response_type']}"
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, meta = validate_paginated(
        api.list_cashiers(manager_headers, params={"store_id": store["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no partial Cashier row may be persisted, got total_count {meta['total_count']}"
    )
    assert rows == [], f"expected no cashier rows, got {rows}"


def test_store_creation_invalid_seasonal_profile_returns_invalid_request(
    api, treasury_headers
):
    """PRD §2.5: "`seasonal_profile` defaults to `BASELINE` and may otherwise be `BACK_TO_SCHOOL` or `HOLIDAY`; it is the default seasonal demand profile used by change-order forecasting."

    PRD §2.12: "Third, request-body shape: required fields present, enum members valid,
    integer cents fields integral and non-negative subject to the two exceptions in §2.10,
    denomination lines drawn from the permitted set with non-negative quantities,
    `shift_end_at` strictly after `shift_start_at`, `pickup_window_end` strictly after
    `pickup_window_start`, `days_covered` between 1 and 14 inclusive, and `growth_pct`
    between -0.50 and 2.00 inclusive."

    Design: Corner/entities/store_creation_invalid_seasonal_profile_returns_invalid_request
    """
    set_clock("2026-08-03T08:00:00Z", treasury_headers)

    resp = api.create_store(
        {
            "store_code": "S-1907",
            "name": "Store 1907",
            "region_code": "WEST",
            "seasonal_profile": "SUMMER_RUSH",
        },
        treasury_headers,
    )
    assert resp.json()["response_type"] == "error", (
        f"expected response_type error, got {resp.json()['response_type']}"
    )
    error = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert error["error_id"] == "ERR_INVALID_REQUEST", (
        f"expected ERR_INVALID_REQUEST, got {error['error_id']}"
    )


def test_safe_transaction_is_immutable_and_carries_no_version(
    api, treasury_headers, clerk_headers, manager_headers
):
    """PRD §2.4: "Safe ledger rows are the exception: a safe transaction is immutable once written, so it carries only `id` and `created_at` — it has no `updated_at` and no `version` field at all."

    PRD §2.4: "Its own timing information lives in `occurred_at`, the logical-clock reading
    at which the row was written, alongside `actor_user_id` and a `memo` line."
    PRD §2.6: "The row's `effective_amount_cents` is that basis carried with the sign its
    `txn_type` implies."
    PRD §2.6: "Nine transaction kinds exist, and their signs are fixed: `OPENING_BALANCE`,
    `MID_SHIFT_DROP`, `CLOSING_DROP`, `SMART_DEPOSIT`, `DEPOSIT_RETURN` and
    `CHANGE_ORDER_RECEIPT` add to the safe; `STARTING_BANK_ISSUE`, `DEPOSIT_REMOVAL` and
    `VARIANCE_ADJUSTMENT` subtract from it."
    PRD §2.6: "`till_session_id` is populated only on `STARTING_BANK_ISSUE`,
    `MID_SHIFT_DROP` and `CLOSING_DROP` rows; `deposit_id` only on `SMART_DEPOSIT`,
    `DEPOSIT_REMOVAL` and `DEPOSIT_RETURN` rows; `change_order_id` only on
    `CHANGE_ORDER_RECEIPT` rows."
    PRD §2.6: "`actor_user_id` records the `X-User-ID` of the request that produced the
    row, or the literal string `system` for rows produced by a cascade rather than by a
    direct request."
    PRD §3.3: "Commissioning writes the safe's first ledger row, of kind `OPENING_BALANCE`
    with `declared_amount_cents` equal to `opening_balance_cents`, and recomputes
    `balance_cents` from it."
    PRD §3.2: "It writes one safe ledger row of kind `STARTING_BANK_ISSUE` against the
    supplied `safe_id`, linked to the new session, with `declared_amount_cents` equal to
    `starting_bank_cents`; the safe's `balance_cents` is recomputed (falling by the starting
    bank) and the safe's `version` increments by 1."

    Design: Corner/entities/safe_transaction_is_immutable_and_carries_no_version
    """
    set_clock("2026-08-03T08:00:00Z", treasury_headers)

    store = validate_success(
        api.create_store(
            {"store_code": "S-1908", "name": "Store 1908", "region_code": "WEST"},
            treasury_headers,
        ),
        201,
    )
    safe = validate_success(
        api.create_safe(
            {
                "store_id": store["id"],
                "safe_code": "SAFE-A",
                "safe_type": "MANUAL",
                "opening_balance_cents": 500000,
            },
            treasury_headers,
        ),
        201,
    )
    cashier = validate_success(
        api.create_cashier(
            {
                "store_id": store["id"],
                "employee_code": "E-100",
                "display_name": "Cashier 100",
            },
            manager_headers,
        ),
        201,
    )
    journal = validate_success(
        api.create_sales_journal(
            {"store_id": store["id"], "business_date": "2026-08-03"}, clerk_headers
        ),
        201,
    )
    session = validate_success(
        api.create_till_session(
            {
                "sales_journal_id": journal["id"],
                "cashier_id": cashier["id"],
                "safe_id": safe["id"],
                "register_number": 1,
                "shift_start_at": "2026-08-03T09:00:00Z",
                "shift_end_at": "2026-08-03T17:00:00Z",
                "starting_bank_cents": 20000,
            },
            manager_headers,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_safe_transactions(clerk_headers, params={"safe_id": safe["id"]})
    )
    assert meta["total_count"] == 2, (
        f"commissioning and the starting bank write two ledger rows, got "
        f"{meta['total_count']}"
    )

    for row in rows:
        assert_safe_transaction(row)
        assert "version" not in row, (
            f"a safe transaction has no version field at all, got {sorted(row.keys())}"
        )
        assert "updated_at" not in row, (
            f"a safe transaction has no updated_at, got {sorted(row.keys())}"
        )

    by_type = {row["txn_type"]: row for row in rows}
    assert set(by_type) == {"OPENING_BALANCE", "STARTING_BANK_ISSUE"}, (
        f"expected an OPENING_BALANCE and a STARTING_BANK_ISSUE row, got {sorted(by_type)}"
    )

    opening = by_type["OPENING_BALANCE"]
    assert opening["declared_amount_cents"] == 500000, (
        f"expected 500000, got {opening['declared_amount_cents']}"
    )
    assert opening["verified_amount_cents"] is None, (
        f"expected verified_amount_cents null, got {opening['verified_amount_cents']}"
    )
    assert opening["effective_amount_cents"] == 500000, (
        f"OPENING_BALANCE adds to the safe: expected 500000, got "
        f"{opening['effective_amount_cents']}"
    )

    issue = by_type["STARTING_BANK_ISSUE"]
    assert issue["declared_amount_cents"] == 20000, (
        f"expected 20000, got {issue['declared_amount_cents']}"
    )
    assert issue["effective_amount_cents"] == -20000, (
        f"STARTING_BANK_ISSUE subtracts from the safe: expected -20000, got "
        f"{issue['effective_amount_cents']}"
    )
    assert issue["till_session_id"] == session["id"], (
        f"expected till_session_id {session['id']}, got {issue['till_session_id']}"
    )
    assert issue["deposit_id"] is None, (
        f"deposit_id must be null on a STARTING_BANK_ISSUE row, got {issue['deposit_id']}"
    )
    assert issue["change_order_id"] is None, (
        f"change_order_id must be null on a STARTING_BANK_ISSUE row, got "
        f"{issue['change_order_id']}"
    )
    assert issue["actor_user_id"] == "U-MGR-1", (
        f"actor_user_id records the acting X-User-ID: expected U-MGR-1, got "
        f"{issue['actor_user_id']}"
    )
    assert parse_instant(issue["occurred_at"]) == parse_instant("2026-08-03T08:00:00Z"), (
        f"occurred_at is the logical-clock reading 2026-08-03T08:00:00Z, got "
        f"{issue['occurred_at']}"
    )

    read_back = validate_success(api.get_safe_transaction(rows[0]["id"], clerk_headers))
    assert read_back["id"] == rows[0]["id"], (
        f"expected {rows[0]['id']}, got {read_back['id']}"
    )
    assert "version" not in read_back, (
        f"the single-row read carries no version either, got {sorted(read_back.keys())}"
    )
    assert "updated_at" not in read_back, (
        f"the single-row read carries no updated_at either, got {sorted(read_back.keys())}"
    )

    safe_after = validate_success(api.get_safe(safe["id"], clerk_headers))
    assert safe_after["balance_cents"] == 480000, (
        f"balance_cents is the ledger sum 500000 - 20000 = 480000, got "
        f"{safe_after['balance_cents']}"
    )


def test_till_session_not_found_returns_404(api, treasury_headers, clerk_headers):
    """PRD §2.12: "Fourth, path resolution: every templated `{id}` segment must resolve, validated left to right, yielding the not-found error for the record type that failed — `ERR_STORE_NOT_FOUND`, `ERR_CASHIER_NOT_FOUND`, `ERR_SAFE_NOT_FOUND`, `ERR_SALES_JOURNAL_NOT_FOUND`, `ERR_TILL_SESSION_NOT_FOUND`, `ERR_SAFE_TRANSACTION_NOT_FOUND`, `ERR_DEPOSIT_NOT_FOUND`, `ERR_BANK_CREDIT_RECORD_NOT_FOUND`, `ERR_CARD_SETTLEMENT_NOT_FOUND`, `ERR_VARIANCE_CASE_NOT_FOUND` or `ERR_CHANGE_ORDER_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/till_session_not_found_returns_404
    """
    set_clock("2026-08-03T08:00:00Z", treasury_headers)

    resp = api.get_till_session(UNKNOWN_TILL_SESSION_ID, clerk_headers)
    assert resp.status_code == 404, (
        f"an unknown till session must answer 404, got {resp.status_code}: {resp.text}"
    )
    assert resp.json()["response_type"] == "error", (
        f"expected response_type error, got {resp.json()['response_type']}"
    )
    error = validate_error(resp, ApiErrorId.ERR_TILL_SESSION_NOT_FOUND.value)
    assert error["error_id"] == "ERR_TILL_SESSION_NOT_FOUND", (
        f"expected ERR_TILL_SESSION_NOT_FOUND, got {error['error_id']}"
    )


def test_deposit_creation_with_unknown_safe_id_returns_safe_not_found(
    api, treasury_headers, clerk_headers, clerk_2_headers
):
    """PRD §2.12: "Fifth, foreign keys carried in the request body must resolve — `store_id`, `safe_id`, `cashier_id`, `sales_journal_id`, `till_session_id`, `deposit_id`, `change_order_id` — again with the matching not-found error."

    PRD §2.12: "Last, the two optimistic-concurrency checks of §2.11
    (`ERR_SAFE_VERSION_STALE` and `ERR_CASE_VERSION_STALE`, HTTP 412) run after every other
    rule has been satisfied."

    Design: Corner/entities/deposit_creation_with_unknown_safe_id_returns_safe_not_found
    """
    set_clock("2026-08-03T08:00:00Z", treasury_headers)

    store = validate_success(
        api.create_store(
            {"store_code": "S-1909", "name": "Store 1909", "region_code": "WEST"},
            treasury_headers,
        ),
        201,
    )
    safe = validate_success(
        api.create_safe(
            {
                "store_id": store["id"],
                "safe_code": "SAFE-A",
                "safe_type": "MANUAL",
                "opening_balance_cents": 500000,
            },
            treasury_headers,
        ),
        201,
    )
    journal = validate_success(
        api.create_sales_journal(
            {"store_id": store["id"], "business_date": "2026-08-03"}, clerk_headers
        ),
        201,
    )

    get_success_data(
        api.create_open_request(
            safe["id"], {"reason": "Deposit preparation"}, clerk_headers
        )
    )
    set_clock("2026-08-03T08:10:00Z", treasury_headers)
    validate_success(api.open_safe(safe["id"], clerk_2_headers))

    observed_safe = validate_success(api.get_safe(safe["id"], clerk_headers))
    safe_version = observed_safe["version"]
    assert observed_safe["open_state"] == "UNLOCKED", (
        f"the safe must be UNLOCKED before preparation, got {observed_safe['open_state']}"
    )

    resp = api.create_deposit(
        {
            "safe_id": UNKNOWN_SAFE_ID,
            "sales_journal_id": journal["id"],
            "business_date": "2026-08-03",
            "counted_lines": [{"denomination_cents": 2000, "quantity": 50}],
            "expected_safe_version": safe_version,
        },
        clerk_headers,
    )
    assert resp.status_code == 404, (
        f"an unresolvable body safe_id must answer 404, got {resp.status_code}: {resp.text}"
    )
    error = validate_error(resp, ApiErrorId.ERR_SAFE_NOT_FOUND.value)
    assert error["error_id"] == "ERR_SAFE_NOT_FOUND", (
        f"expected ERR_SAFE_NOT_FOUND rather than ERR_SAFE_VERSION_STALE, got "
        f"{error['error_id']}"
    )

    rows, meta = validate_paginated(
        api.list_deposits(clerk_headers, params={"safe_id": safe["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no deposit may be created, got total_count {meta['total_count']}"
    )
    assert rows == [], f"expected no deposit rows, got {rows}"

    safe_after = validate_success(api.get_safe(safe["id"], clerk_headers))
    assert safe_after["balance_cents"] == 500000, (
        f"the rejected preparation removes no cash: expected 500000, got "
        f"{safe_after['balance_cents']}"
    )
    assert safe_after["version"] == safe_version, (
        f"the safe's version is unchanged: expected {safe_version}, got "
        f"{safe_after['version']}"
    )


def test_card_settlement_with_unknown_sales_journal_returns_not_found(
    api, treasury_headers
):
    """PRD §2.12: "Fifth, foreign keys carried in the request body must resolve — `store_id`, `safe_id`, `cashier_id`, `sales_journal_id`, `till_session_id`, `deposit_id`, `change_order_id` — again with the matching not-found error."

    Design: Corner/entities/card_settlement_with_unknown_sales_journal_returns_not_found
    """
    set_clock("2026-08-03T08:00:00Z", treasury_headers)

    validate_success(
        api.create_store(
            {"store_code": "S-1910", "name": "Store 1910", "region_code": "WEST"},
            treasury_headers,
        ),
        201,
    )

    resp = api.create_card_settlement(
        {
            "sales_journal_id": UNKNOWN_SALES_JOURNAL_ID,
            "card_network": "VISA_MC",
            "gross_card_sales_cents": 50000,
            "txn_count": 20,
            "monthly_volume_cents": 1000000,
            "funded_amount_cents": 48510,
        },
        treasury_headers,
    )
    assert resp.status_code == 404, (
        f"an unresolvable body sales_journal_id must answer 404, got "
        f"{resp.status_code}: {resp.text}"
    )
    error = validate_error(resp, ApiErrorId.ERR_SALES_JOURNAL_NOT_FOUND.value)
    assert error["error_id"] == "ERR_SALES_JOURNAL_NOT_FOUND", (
        f"expected ERR_SALES_JOURNAL_NOT_FOUND, got {error['error_id']}"
    )

    rows, meta = validate_paginated(api.list_card_settlements(treasury_headers))
    assert meta["total_count"] == 0, (
        f"no settlement row may be created, got total_count {meta['total_count']}"
    )
    assert rows == [], f"expected no card settlement rows, got {rows}"
