"""Taking deposits, pricing availability, and posting collection outcomes."""

from test_helpers import (
    ApiErrorId,
    assert_account_balances,
    assert_check_hold,
    assert_deposit_item,
    assert_same_instant,
    create_active_account,
    create_pending_funding_account,
    declare_funding_source,
    first_hold,
    read_account,
    set_clock,
    settle_item,
    submit_verification,
    take_deposit,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# A deposit is gated by the OTHER entity's lifecycle_status
# ===========================================================================
def test_deposit_into_a_pending_funding_account_is_refused(api, ops_admin_headers,
                                                           analyst_headers):
    """PRD §3.3: "Two gates guard the intake. The account named in the path must
    have `lifecycle_status` exactly `ACTIVE`, so a deposit into an account that is
    still `PENDING_FUNDING`, or that has been driven to `RESTRICTED`, `CLOSED`, or
    `CHARGED_OFF`, is refused with `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409)."
    PRD §3.1: "A new account starts with `lifecycle_status` `PENDING_FUNDING` and
    `access_posture` `NORMAL`, with `ledger_balance_cents`,
    `available_balance_cents`, `held_amount_cents`, `charged_off_amount_cents`,
    `ato_score`, and `step_up_failure_count` all zero, `ato_indicator_codes` an
    empty array, and `closure_scheduled_at` and `closure_reason` both null."

    Design: Difficulty/cross_entity_state_dependency/deposit_item_creation_gated_by_deposit_account_lifecycle_status
    """
    scenario = create_pending_funding_account(
        legal_name="Nadia Solberg", tin_last4="6262", kyc_tier="TIER_2", watchlist_hit=False
    )
    declare_funding_source(scenario["account_id"], routing_last4="3333")

    response = api.create_deposit_item(
        scenario["account_id"], {"item_type": "CHECK", "amount_cents": 30000}, ops_admin_headers
    )
    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)

    _rows, meta = validate_paginated(
        api.list_account_deposit_items(scenario["account_id"], analyst_headers)
    )
    assert meta["total_count"] == 0, "The refused deposit must have persisted nothing"

    account = read_account(scenario["account_id"], analyst_headers)
    assert_account_balances(account, ledger=0, available=0, held=0)


def test_the_same_deposit_succeeds_once_funding_verification_activates_the_account(
    api, ops_admin_headers, analyst_headers
):
    """PRD §3.3: "Two gates guard the intake. The account named in the path must
    have `lifecycle_status` exactly `ACTIVE`, so a deposit into an account that is
    still `PENDING_FUNDING`, or that has been driven to `RESTRICTED`, `CLOSED`, or
    `CHARGED_OFF`, is refused with `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409)."
    PRD §3.2: "Because a source has reached `VERIFIED`, the owning account
    transitions `PENDING_FUNDING → ACTIVE` — this transition fires only when the
    account is actually in `PENDING_FUNDING`, so a second source verifying later on
    an already-active account changes nothing about the lifecycle."
    PRD §3.3: "**Posting the deposit.** Balances move in a fixed order once
    availability is priced: the full `amount_cents` is added to the account's
    `ledger_balance_cents`, the `immediate_credit_cents` is added to
    `available_balance_cents`, and `held_amount_cents` is then recomputed as the
    live sum over the account's `ACTIVE` holds."

    Design: Difficulty/cross_entity_state_dependency/deposit_item_creation_gated_by_deposit_account_lifecycle_status
    """
    scenario = create_pending_funding_account(
        legal_name="Nadia Solberg", tin_last4="6262", kyc_tier="TIER_2", watchlist_hit=False
    )
    source = declare_funding_source(scenario["account_id"], routing_last4="3333")

    validate_error(
        api.create_deposit_item(
            scenario["account_id"], {"item_type": "CHECK", "amount_cents": 30000}, ops_admin_headers
        ),
        ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value,
    )

    submit_verification(source["id"], source["micro_deposit_cents"])

    item = validate_success(
        api.create_deposit_item(
            scenario["account_id"], {"item_type": "CHECK", "amount_cents": 30000}, ops_admin_headers
        ),
        201,
    )
    assert_deposit_item(item)
    assert item["status"] == "PENDING"
    assert item["immediate_credit_cents"] == 22500
    assert item["held_cents"] == 7500

    _rows, meta = validate_paginated(
        api.list_account_deposit_items(scenario["account_id"], analyst_headers)
    )
    assert meta["total_count"] == 1, "Only the accepted deposit exists"

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["lifecycle_status"] == "ACTIVE"
    assert_account_balances(account, ledger=30000, available=22500, held=7500)


# ===========================================================================
# The availability split and the account's derived held total
# ===========================================================================
def test_check_deposit_splits_into_immediate_credit_and_held_cents(api, ops_admin_headers,
                                                                   analyst_headers):
    """PRD §3.3: "For every other instrument, `immediate_credit_cents` is the
    smaller of `amount_cents` and 22,500 cents — the first $225.00 of any deposited
    item is always released at once — and `held_cents` is `amount_cents` less that
    immediate credit."
    PRD §3.3: "The server stamps `deposit_at` from the logical clock and records
    the item with `status` `PENDING`, `settled_at` null, and `return_reason` null."
    PRD §2.8: "An account's `held_amount_cents` is always the live sum of
    `held_amount_cents` over every `CheckHold` in `ACTIVE` status whose parent
    deposited item belongs to that account."

    Design: Corner/entities/deposit_item_computed_credit_split_and_account_held_amount_agree
    """
    scenario = create_active_account(legal_name="Split Depositor", tin_last4="0006")

    item = validate_success(
        api.create_deposit_item(
            scenario["account_id"], {"item_type": "CHECK", "amount_cents": 30000}, ops_admin_headers
        ),
        201,
    )
    assert item["immediate_credit_cents"] == 22500
    assert item["held_cents"] == 7500
    assert item["status"] == "PENDING"

    reread = validate_success(api.get_deposit_item(item["id"], analyst_headers))
    assert reread["settled_at"] is None
    assert reread["return_reason"] is None

    account = read_account(scenario["account_id"], analyst_headers)
    assert_account_balances(account, ledger=30000, available=22500, held=7500)

    holds, holds_meta = validate_paginated(api.list_item_holds(item["id"], analyst_headers))
    assert holds_meta["total_count"] == 1
    assert_check_hold(holds[0])
    assert holds[0]["status"] == "ACTIVE"
    assert holds[0]["held_amount_cents"] == 7500


# ===========================================================================
# The availability ladder, top to bottom
# ===========================================================================
def test_new_account_exception_outranks_the_large_deposit_exception(api, ops_admin_headers,
                                                                    analyst_headers):
    """PRD §3.3: "2. Otherwise, if the account's age in whole days is *less than*
    30, the hold is `EXCEPTION_NEW_ACCOUNT`. Age is computed by taking the elapsed
    time from the account's `opened_at` to the logical clock and flooring it to
    whole calendar days in UTC. The comparison is strict: an account that is
    exactly 30 days old is no longer new."
    PRD §3.3: "Because the ladder is ordered, a nine-day hold on a young account
    wins over the seven-day hold the same item would have attracted on a mature
    one. The `hold_release_at` is the item's `deposit_at` advanced by the number of
    calendar days the chosen class carries: two days for `STANDARD`, five for
    `EXCEPTION_RISK`, seven for `EXCEPTION_LARGE_DEPOSIT`, and nine for
    `EXCEPTION_NEW_ACCOUNT`."
    PRD §3.3: "When `held_cents` is greater than zero, a hold is minted in `ACTIVE`
    status with its `held_amount_cents` set to the item's `held_cents`, its
    `hold_start_at` equal to the item's `deposit_at`, and its `deposit_item_id`
    naming the parent item."

    Design: Corner/calculations/new_account_hold_exception_outranks_the_large_deposit_exception
    """
    scenario = create_active_account(legal_name="Young Account Depositor", tin_last4="0018")

    item = validate_success(
        api.create_deposit_item(
            scenario["account_id"], {"item_type": "CHECK", "amount_cents": 600000}, ops_admin_headers
        ),
        201,
    )
    assert item["held_cents"] == 577500, "600000 less the 22500 immediate credit"

    hold = first_hold(item["id"], analyst_headers)
    assert hold["hold_type"] == "EXCEPTION_NEW_ACCOUNT", (
        "The zero-day-old account trips branch 2 before the large-deposit branch 3"
    )
    assert hold["held_amount_cents"] == 577500
    assert_same_instant(hold["hold_start_at"], "2026-08-01T00:00:00Z", "hold_start_at")
    assert_same_instant(hold["hold_release_at"], "2026-08-10T00:00:00Z", "hold_release_at")


def test_seasoned_account_ladder_walks_large_deposit_then_standard_then_ach(api, ops_admin_headers,
                                                                            analyst_headers):
    """PRD §3.3: "1. An `ACH` item is always `STANDARD`, whatever the account's
    age, the amount, or the risk band. This short-circuit is tested first."
    PRD §3.3: "3. Otherwise, if `amount_cents` is *strictly greater than* 552,500
    cents — that is, more than $5,525.00 — the hold is `EXCEPTION_LARGE_DEPOSIT`.
    This edge is strict too: an item of exactly 552,500 cents is not large."
    PRD §3.3: "The `hold_release_at` is the item's `deposit_at` advanced by the
    number of calendar days the chosen class carries: two days for `STANDARD`, five
    for `EXCEPTION_RISK`, seven for `EXCEPTION_LARGE_DEPOSIT`, and nine for
    `EXCEPTION_NEW_ACCOUNT`."
    PRD §2.5: "An `OperationsAdmin` may move the clock by supplying a `to_iso8601`
    instant; the response reports the clock's new value as `current_utc`."

    Design: Corner/calculations/seasoned_account_hold_ladder_walks_large_deposit_then_standard_then_ach
    """
    scenario = create_active_account(legal_name="Seasoned Account Depositor", tin_last4="0019")
    set_clock("2026-09-15T00:00:00Z")  # the account is now 45 days old

    large = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=600001)
    large_hold = first_hold(large["id"], analyst_headers)
    assert large_hold["hold_type"] == "EXCEPTION_LARGE_DEPOSIT"
    assert large_hold["held_amount_cents"] == 577501
    assert_same_instant(large_hold["hold_release_at"], "2026-09-22T00:00:00Z", "hold_release_at")

    at_edge = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=552500)
    edge_hold = first_hold(at_edge["id"], analyst_headers)
    assert edge_hold["hold_type"] == "STANDARD", (
        "552500 is not strictly greater than 552500, so the large-deposit branch does not fire"
    )
    assert edge_hold["held_amount_cents"] == 530000
    assert_same_instant(edge_hold["hold_release_at"], "2026-09-17T00:00:00Z", "hold_release_at")

    ach = take_deposit(scenario["account_id"], item_type="ACH", amount_cents=600000)
    ach_hold = first_hold(ach["id"], analyst_headers)
    assert ach_hold["hold_type"] == "STANDARD", "The ACH short-circuit precedes every exception"
    assert_same_instant(ach_hold["hold_release_at"], "2026-09-17T00:00:00Z", "hold_release_at")


def test_cash_deposit_creates_no_hold_and_credits_the_whole_amount(api, ops_admin_headers,
                                                                    analyst_headers):
    """PRD §3.3: "Cash is special-cased first: a `CASH` item makes its whole
    `amount_cents` available at once, so `immediate_credit_cents` equals
    `amount_cents`, `held_cents` is zero, and no hold row is created at all."
    PRD §3.3: "**Posting the deposit.** Balances move in a fixed order once
    availability is priced: the full `amount_cents` is added to the account's
    `ledger_balance_cents`, the `immediate_credit_cents` is added to
    `available_balance_cents`, and `held_amount_cents` is then recomputed as the
    live sum over the account's `ACTIVE` holds."

    Design: Corner/calculations/cash_deposit_creates_no_check_hold_and_credits_the_full_amount
    """
    scenario = create_active_account(legal_name="Cash Depositor", tin_last4="0020")

    item = validate_success(
        api.create_deposit_item(
            scenario["account_id"], {"item_type": "CASH", "amount_cents": 90000}, ops_admin_headers
        ),
        201,
    )
    assert item["immediate_credit_cents"] == 90000
    assert item["held_cents"] == 0

    holds, meta = validate_paginated(api.list_item_holds(item["id"], analyst_headers))
    assert meta["total_count"] == 0, "A cash item mints no hold row at all"
    assert holds == []

    account = read_account(scenario["account_id"], analyst_headers)
    assert_account_balances(account, ledger=90000, available=90000, held=0)


# ===========================================================================
# Settlement
# ===========================================================================
def test_clearing_an_on_us_item_releases_the_hold_and_debits_the_drawee(api, ops_admin_headers,
                                                                        analyst_headers):
    """PRD §3.3: "A **cleared** item transitions `PENDING → CLEARED`. Every hold on
    that item still in `ACTIVE` transitions `ACTIVE → RELEASED` with `released_at`
    stamped. Because those holds left `ACTIVE`, the depositing account's
    `available_balance_cents` rises by the total `held_amount_cents` just released
    and its `held_amount_cents` is recomputed; `ledger_balance_cents` is unchanged,
    because the money was already on the ledger. If the item named a
    `drawee_account_id`, the drawn-on account now pays: both its
    `ledger_balance_cents` and its `available_balance_cents` fall by the item's
    `amount_cents`."
    PRD §3.3: "One detail of the deposit listing on an account is worth stating
    plainly: an item is returned there when *either* its `account_id` or its
    `drawee_account_id` names that account, so the drawn-on side of an on-us check
    is discoverable from the drawee's own listing."

    Design: Corner/state_machines/cleared_on_us_item_debits_the_drawee_account_and_releases_the_hold
    """
    drawer = create_active_account(legal_name="On Us Pair Depositor", tin_last4="0014")
    depositor = create_active_account(legal_name="On Us Pair Receiver", tin_last4="0114")

    item = take_deposit(
        depositor["account_id"],
        item_type="CHECK",
        amount_cents=40000,
        drawee_account_id=drawer["account_id"],
    )

    settled = validate_success(
        api.settle_deposit_item(item["id"], {"outcome": "CLEARED"}, ops_admin_headers)
    )
    assert settled["status"] == "CLEARED"

    depositing_account = read_account(depositor["account_id"], analyst_headers)
    assert_account_balances(depositing_account, ledger=40000, available=40000, held=0)

    drawee_account = read_account(drawer["account_id"], analyst_headers)
    assert_account_balances(drawee_account, ledger=-40000, available=-40000, held=0)

    holds, holds_meta = validate_paginated(api.list_item_holds(item["id"], analyst_headers))
    assert holds_meta["total_count"] == 1
    assert holds[0]["status"] == "RELEASED"

    drawee_items, drawee_meta = validate_paginated(
        api.list_account_deposit_items(drawer["account_id"], analyst_headers)
    )
    assert drawee_meta["total_count"] == 1, (
        "The item is reachable from the drawn-on account's own listing"
    )
    assert drawee_items[0]["id"] == item["id"]


def test_return_without_a_reason_is_rejected_and_a_settled_item_cannot_settle_again(
    api, ops_admin_headers, analyst_headers
):
    """PRD §3.3: "**Settlement.** An `OperationsAdmin` posts the collection outcome
    by supplying an `outcome` of either `CLEARED` or `RETURNED`, together with a
    `return_reason` — one of `NSF`, `ACCOUNT_CLOSED`, `UNCOLLECTED_FUNDS`, or
    `STOP_PAYMENT` — which is mandatory on a return and rejected as a malformed
    body when missing. The item must be in `PENDING`; a second settlement of the
    same item is refused with `ERR_ITEM_ALREADY_SETTLED` (HTTP 409)."

    Design: Corner/validations/settling_returned_without_a_reason_is_rejected_and_settling_twice_is_rejected
    """
    scenario = create_active_account(legal_name="Settle Guard Depositor", tin_last4="0027")
    item = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=30000)

    validate_error(
        api.settle_deposit_item(item["id"], {"outcome": "RETURNED"}, ops_admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    cleared = validate_success(
        api.settle_deposit_item(item["id"], {"outcome": "CLEARED"}, ops_admin_headers)
    )
    assert cleared["status"] == "CLEARED"

    validate_error(
        api.settle_deposit_item(
            item["id"], {"outcome": "RETURNED", "return_reason": "NSF"}, ops_admin_headers
        ),
        ApiErrorId.ERR_ITEM_ALREADY_SETTLED.value,
    )

    account = read_account(scenario["account_id"], analyst_headers)
    assert_account_balances(account, ledger=30000, available=30000, held=0)


def test_deposit_listing_filters_by_settlement_status(api, analyst_headers):
    """PRD §2.3: "Several listings accept an additional optional filter, and each
    filter narrows the result set before pagination and before `total_count` is
    computed."
    PRD §2.3: "Deposits taken into an account may be filtered by `status` and,
    additionally, by `account_role`, which selects whether the account is being
    considered as the depositing side or the drawn-on side of the item."
    PRD §2.3: "Every list endpoint accepts two optional query parameters. `limit`
    defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0
    and has a minimum of 0."

    Design: Corner/endpoints/deposit_item_listing_filters_by_settlement_status
    """
    scenario = create_active_account(legal_name="Listing Filter Depositor", tin_last4="0036")
    first = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=30000)
    second = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=30000)
    third = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=30000)
    settle_item(second["id"], "CLEARED")

    pending_rows, pending_meta = validate_paginated(
        api.list_account_deposit_items(
            scenario["account_id"], analyst_headers, params={"status": "PENDING"}
        )
    )
    assert pending_meta["total_count"] == 2
    assert {row["id"] for row in pending_rows} == {first["id"], third["id"]}

    cleared_rows, cleared_meta = validate_paginated(
        api.list_account_deposit_items(
            scenario["account_id"], analyst_headers, params={"status": "CLEARED"}
        )
    )
    assert cleared_meta["total_count"] == 1
    assert [row["id"] for row in cleared_rows] == [second["id"]]

    _all_rows, all_meta = validate_paginated(
        api.list_account_deposit_items(scenario["account_id"], analyst_headers)
    )
    assert all_meta["total_count"] == 3
    assert all_meta["limit"] == 10, "limit defaults to 10"
    assert all_meta["offset"] == 0, "offset defaults to 0"
    assert all_meta["has_more"] is False
