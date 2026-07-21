"""Raffle entry, draw, claim, settlement — validations, state machine, and
unit-conservation / precedence difficulty cases."""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId, TEST_USERS,
    create_sku, create_account, create_release_payload,
    setup_open_release, enter_raffle, run_draw, raffle_claim, setup_drawn_single_winner,
    advance_clock, make_buyer_headers,
    assert_release_unit_conservation,
    DEFAULT_ENTRY_OPENS, DEFAULT_ENTRY_CLOSES, DEFAULT_PURCHASE_OPENS, DEFAULT_PURCHASE_CLOSES,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# Entry-time validations (Corner/validations)
# --------------------------------------------------------------------------- #
def test_enter_unverified_account_rejected(api):
    """PRD §3.2: "the acting account must be `VERIFIED` or the attempt is
    rejected with `ERR_ACCOUNT_NOT_VERIFIED`".

    Design: Corner/validations/enter_unverified_account_rejected
    """
    sku = create_sku(api, release_category="LIMITED")
    acct = create_account(api, verified=False, full_name="Unverified")
    release = get_success_data(api.create_release(create_release_payload(sku_id=sku["id"]), ADMIN))
    advance_clock(api, DEFAULT_ENTRY_OPENS)
    get_success_data(api.open_release(release["id"], ADMIN))
    resp = api.enter_release(release["id"], make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_VERIFIED.value)


def test_enter_young_account_bot_flagged(api):
    """PRD §3.2: "the account's tenure — the number of whole days between its
    `created_at` and the current logical clock — must be at least 3 days or the
    attempt is rejected with `ERR_BOT_FLAGGED` as a bot heuristic".

    Design: Corner/validations/enter_young_account_bot_flagged
    """
    sku = create_sku(api, release_category="LIMITED")
    release = get_success_data(api.create_release(create_release_payload(sku_id=sku["id"]), ADMIN))
    advance_clock(api, DEFAULT_ENTRY_OPENS)
    # Account created AFTER the clock reaches entry-open -> tenure 0 days.
    acct = create_account(api, full_name="Young Bot")
    get_success_data(api.open_release(release["id"], ADMIN))
    resp = api.enter_release(release["id"], make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_BOT_FLAGGED.value)


def test_duplicate_entry_same_account_rejected(api):
    """PRD §3.2: "the account must not already hold an entry for this release or
    the attempt is rejected with `ERR_DUPLICATE_ENTRY`".

    Design: Corner/validations/duplicate_entry_same_account_rejected
    """
    ctx = setup_open_release(api, allocated_quantity=1, num_accounts=1)
    acct = ctx["accounts"][0]
    enter_raffle(api, ctx["release"]["id"], acct["id"])
    resp = api.enter_release(ctx["release"]["id"], make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENTRY.value)


def test_enter_after_entry_window_closed_rejected(api):
    """PRD §3.2: "the logical clock must fall within the entry window, at or
    after `entry_opens_at` and strictly before `entry_closes_at`, or the attempt
    is rejected with `ERR_ENTRY_WINDOW_CLOSED`".

    Design: Corner/validations/enter_after_window_closed_rejected
    """
    ctx = setup_open_release(api, allocated_quantity=1, num_accounts=1)
    advance_clock(api, DEFAULT_PURCHASE_OPENS)  # past entry_closes_at
    resp = api.enter_release(ctx["release"]["id"], make_buyer_headers(ctx["accounts"][0]["id"]))
    validate_error(resp, ApiErrorId.ERR_ENTRY_WINDOW_CLOSED.value)


def test_draw_with_no_eligible_entries_rejected(api):
    """PRD §3.3: "If no eligible entry exists the draw is rejected with
    `ERR_NO_ELIGIBLE_ENTRIES`."

    Design: Corner/validations/draw_with_no_eligible_entries_rejected
    """
    ctx = setup_open_release(api, allocated_quantity=1, num_accounts=0)
    advance_clock(api, DEFAULT_ENTRY_CLOSES)
    rel = get_success_data(api.get_release(ctx["release"]["id"], ADMIN))
    resp = api.draw_release(ctx["release"]["id"], {"expected_release_version": rel["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ENTRIES.value)


# --------------------------------------------------------------------------- #
# Raffle state-machine invalid transitions (Corner/state_machines)
# --------------------------------------------------------------------------- #
def test_enter_before_open_returns_release_not_open(api):
    """PRD §3.2: "the release must be `OPEN` or the attempt is rejected with
    `ERR_RELEASE_NOT_OPEN`".

    Design: Corner/state_machines/enter_before_open_returns_release_not_open
    """
    sku = create_sku(api, release_category="LIMITED")
    acct = create_account(api, full_name="Early Bird")
    release = get_success_data(api.create_release(create_release_payload(sku_id=sku["id"]), ADMIN))
    advance_clock(api, DEFAULT_ENTRY_OPENS)  # inside entry window, but not opened
    resp = api.enter_release(release["id"], make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_OPEN.value)


def test_claim_before_draw_returns_release_not_drawn(api):
    """PRD §3.4: "A claim requires that the parent release is in `DRAWN` status
    — otherwise `ERR_RELEASE_NOT_DRAWN`".

    Design: Corner/state_machines/claim_before_draw_returns_release_not_drawn
    """
    ctx = setup_open_release(api, allocated_quantity=1, num_accounts=1)
    acct = ctx["accounts"][0]
    entry = enter_raffle(api, ctx["release"]["id"], acct["id"])
    resp = api.claim_entry(entry["id"], make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_DRAWN.value)


def test_claim_after_purchase_window_closed_rejected(api):
    """PRD §3.4: "The logical clock must fall inside the purchase window, at or
    after `purchase_opens_at` and strictly before `purchase_closes_at`, or the
    claim is rejected with `ERR_PURCHASE_WINDOW_CLOSED`".

    Design: Corner/state_machines/claim_after_purchase_window_closed_returns_window_closed
    """
    ctx = setup_drawn_single_winner(api)
    acct = ctx["accounts"][0]
    advance_clock(api, DEFAULT_PURCHASE_CLOSES)  # past purchase_closes_at
    resp = api.claim_entry(ctx["entry"]["id"], make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_PURCHASE_WINDOW_CLOSED.value)


def test_claim_twice_returns_entry_already_claimed(api):
    """PRD §3.4: "The entry must not already have been claimed: a `claim_status`
    other than `NONE` is rejected with `ERR_ENTRY_ALREADY_CLAIMED`".

    Design: Corner/state_machines/claim_twice_returns_entry_already_claimed
    """
    ctx = setup_drawn_single_winner(api)
    acct = ctx["accounts"][0]
    advance_clock(api, DEFAULT_PURCHASE_OPENS)  # inside purchase window
    raffle_claim(api, ctx["entry"]["id"], acct["id"])
    resp = api.claim_entry(ctx["entry"]["id"], make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_ENTRY_ALREADY_CLAIMED.value)


# --------------------------------------------------------------------------- #
# Precedence: state check outranks temporal check (Difficulty)
# --------------------------------------------------------------------------- #
def _lost_entry_past_purchase_window(api):
    """Allocated-1 release with earliest entrant A (WON) and later B (LOST);
    clock advanced past purchase_closes_at. Returns (entry_b, account_b)."""
    ctx = setup_open_release(api, allocated_quantity=1, num_accounts=2)
    a, b = ctx["accounts"]
    enter_raffle(api, ctx["release"]["id"], a["id"])          # earliest -> WON
    entry_b = enter_raffle(api, ctx["release"]["id"], b["id"])  # later -> LOST
    run_draw(api, ctx["release"]["id"], clock=DEFAULT_ENTRY_CLOSES)
    advance_clock(api, DEFAULT_PURCHASE_CLOSES)               # also past purchase window
    return entry_b, b


def test_claim_lost_entry_reports_state_error_over_window(api):
    """PRD §2.8: "After body validation come the optimistic-concurrency check
    (`ERR_STALE_VERSION`, 412) where applicable, then state and status checks
    (HTTP 409), then business-safety checks such as account verification and
    self-dealing (HTTP 403), then temporal-window checks, referential checks,
    quota constraints, and finally fiscal checks. In every case the earliest
    failing check in this ladder is the one reported."
    PRD §3.4: "claiming an entry whose `result` is not `WON` is rejected with
    `ERR_ENTRY_NOT_WON`".

    Design: Difficulty/priority_pair_validation_conflict/claim_state_not_won_beats_temporal_window_closed
    """
    entry_b, acct_b = _lost_entry_past_purchase_window(api)
    resp = api.claim_entry(entry_b["id"], make_buyer_headers(acct_b["id"]))
    validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_WON.value)


def test_claim_lost_entry_status_is_state_conflict_not_temporal(api):
    """PRD §2.8: "After body validation come the optimistic-concurrency check
    (`ERR_STALE_VERSION`, 412) where applicable, then state and status checks
    (HTTP 409), then business-safety checks such as account verification and
    self-dealing (HTTP 403), then temporal-window checks, referential checks,
    quota constraints, and finally fiscal checks."
    PRD §3.4: "claiming an entry whose `result` is not `WON` is rejected with
    `ERR_ENTRY_NOT_WON`".

    Design: Difficulty/priority_pair_validation_conflict/claim_state_not_won_beats_temporal_window_closed
    """
    entry_b, acct_b = _lost_entry_past_purchase_window(api)
    resp = api.claim_entry(entry_b["id"], make_buyer_headers(acct_b["id"]))
    # 409 = the state check (ERR_ENTRY_NOT_WON); 422 would be the temporal window.
    assert resp.status_code == 409, f"expected 409 state conflict, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_WON.value)


# --------------------------------------------------------------------------- #
# Unit conservation across claim + expiry (Difficulty)
# --------------------------------------------------------------------------- #
def _release_two_winners_one_claim_then_settle(api):
    """Allocated-2 release, both entrants win, one claims, then settle after the
    purchase window closes. Returns the settled release."""
    ctx = setup_open_release(api, allocated_quantity=2, num_accounts=2)
    w1, w2 = ctx["accounts"]
    entry1 = enter_raffle(api, ctx["release"]["id"], w1["id"])
    enter_raffle(api, ctx["release"]["id"], w2["id"])
    run_draw(api, ctx["release"]["id"], clock=DEFAULT_ENTRY_CLOSES)
    advance_clock(api, DEFAULT_PURCHASE_OPENS)
    raffle_claim(api, entry1["id"], w1["id"])
    advance_clock(api, DEFAULT_PURCHASE_CLOSES)
    return get_success_data(api.settle_release(ctx["release"]["id"], ADMIN))


def test_allocation_units_pools_after_settle(api):
    """PRD §3.4: "Claiming also moves one unit from the reserved pool to the sold
    pool: the release's `reserved_units` is decreased by one and its `sold_units`
    is increased by one".
    PRD §3.3: "The release's `reserved_units` is decreased by the number of
    expired winners, and those freed units return to `available_units`,
    preserving the unit-conservation identity."

    Design: Difficulty/compensating_invariant/allocation_units_conserved_across_claim_and_expiry
    """
    release = _release_two_winners_one_claim_then_settle(api)
    assert release["sold_units"] == 1
    assert release["reserved_units"] == 0
    assert release["available_units"] == 1


def test_allocation_units_conservation_identity_holds(api):
    """PRD §2.9: "Its `available_units` is always exactly its `allocated_quantity`
    minus its `reserved_units` minus its `sold_units`; this equality is an
    invariant that every release-affecting operation must preserve."

    Design: Difficulty/compensating_invariant/allocation_units_conserved_across_claim_and_expiry
    """
    release = _release_two_winners_one_claim_then_settle(api)
    assert_release_unit_conservation(release)
    assert (release["available_units"] + release["reserved_units"]
            + release["sold_units"]) == release["allocated_quantity"] == 2
