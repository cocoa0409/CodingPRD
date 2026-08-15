"""Expense-cap testing, waiver ledger entries, and recoupment rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_money,
    assert_waiver_ledger_entry,
    cap_breach_kit,
    create_fund,
    create_manual_accrual,
    create_nav,
    create_security,
    create_share_class,
    create_waiver_agreement,
    finalize_nav,
    get_agreement,
    open_position,
    set_logical_clock,
    submit_price,
    approve_price,
    subscribe_shares,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

CTRL = TEST_USERS["fund_controller_headers"]


def _circular_setup():
    """Class with qty 3650 @ 100.00 and a 10 bps cap agreement; day 1
    (2026-08-04) finalized at exact cap equality; day 2 (2026-08-05) carries an
    extra manual OTHER accrual. Returns dict of the moving parts."""
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    subscribe_shares(share_class["id"], 10000)
    security = create_security()
    open_position(share_class["id"], security["id"], quantity=3650,
                  cost_basis_total=365000)
    px1 = submit_price(security["id"], price_date="2026-08-04", price=100.00)
    approve_price(px1["id"])
    agreement = create_waiver_agreement(share_class["id"], cap_bps=10)
    nav1 = create_nav(share_class["id"], accounting_date="2026-08-04")
    nav1 = finalize_nav(nav1["id"], expected_version=nav1["version"])
    balance_day1 = get_agreement(agreement["id"])["recoverable_balance"]

    set_logical_clock("2026-08-05T00:00:00Z")
    px2 = submit_price(security["id"], price_date="2026-08-05", price=100.00)
    approve_price(px2["id"])
    nav2 = create_nav(share_class["id"], accounting_date="2026-08-05")
    manual = create_manual_accrual(share_class["id"], "2026-08-05",
                                   category="OTHER", annual_rate_bps=0.1)
    return {
        "fund": fund, "share_class": share_class, "security": security,
        "agreement": agreement, "nav1": nav1, "balance_day1": balance_day1,
        "nav2": nav2, "manual_accrual": manual,
    }


def test_cap_exact_equality_on_first_day_no_waiver(api):
    """PRD §3.5: "The ratio is compared against the covering `ACTIVE`
    agreement's `cap_bps`, and a breach exists only when the ratio is strictly
    greater than the cap — a ratio exactly equal to the cap is not a breach."
    PRD §3.5: "With `A` as the record's `expense_accrual_total` and `B` as the
    accrual base (`base_net_assets`, shared by all of the class's rows on that
    date), the annualized expense ratio in basis points is `A` multiplied by
    365, divided by `B`, multiplied by ten thousand, rounded to four decimal
    places half-up."

    Design: Difficulty/combinatorial_formula/expense_cap_circular_evaluation_order
    """
    s = _circular_setup()
    # Day 1: ratio round4(1.00 x 365 / 365000.00 x 10000) == 10.0000 == cap.
    assert s["nav1"]["status"] == "FINAL"
    assert_money(s["nav1"]["expense_accrual_total"], 1.00,
                 "day-1 expense_accrual_total")
    assert_money(s["balance_day1"], 0.00, "recoverable_balance after day 1")


def test_cap_breach_books_waiver_off_record(api):
    """PRD §3.5: "Booking the entry updates the agreement's
    `recoverable_balance`, but the waiver lives on the agreement ledger only —
    it does not change the triggering record's `total_net_assets`."
    PRD §3.5: "its `expires_at` is the entry date advanced by the agreement's
    `recovery_window_months` (keeping the same day-of-month, clamped to the
    month end when the target month is shorter), and its `remaining_amount`
    starts equal to its `amount`."

    Design: Difficulty/combinatorial_formula/expense_cap_circular_evaluation_order
    """
    s = _circular_setup()
    assert_money(s["manual_accrual"]["accrued_amount"], 0.01,
                 "manual OTHER accrual on base 364999.00 at 0.1 bps")
    nav2 = finalize_nav(s["nav2"]["id"])
    # Day 2: ratio round4(1.01 x 365 / 364999.00 x 10000) = 10.1000 > 10.
    entries, meta = validate_paginated(
        api.list_waiver_ledger(s["agreement"]["id"], CTRL)
    )
    assert meta["total_count"] == 1
    entry = entries[0]
    assert entry["entry_type"] == "WAIVER"
    assert_money(entry["amount"], 0.01, "waiver amount")
    assert entry["entry_date"] == "2026-08-05"
    assert entry["expires_at"] == "2026-11-05"
    assert_money(entry["remaining_amount"], 0.01, "remaining_amount")
    assert_money(get_agreement(s["agreement"]["id"])["recoverable_balance"],
                 0.01, "recoverable_balance")
    # Waiver does not mutate the triggering record's TNA.
    nav2_after = validate_success(api.get_nav_record(nav2["id"], CTRL), 200)
    assert_money(nav2_after["total_net_assets"], 364998.99,
                 "day-2 total_net_assets")


def test_cap_exact_equality_no_waiver(api):
    """PRD §3.5: "The ratio is compared against the covering `ACTIVE`
    agreement's `cap_bps`, and a breach exists only when the ratio is strictly
    greater than the cap — a ratio exactly equal to the cap is not a breach."

    Design: Difficulty/boundary_precision_check/expense_cap_exact_equality_no_waiver
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    subscribe_shares(share_class["id"], 10000)
    security = create_security()
    open_position(share_class["id"], security["id"], quantity=3650,
                  cost_basis_total=365000)
    px = submit_price(security["id"], price=100.00)
    approve_price(px["id"])
    agreement = create_waiver_agreement(share_class["id"], cap_bps=10)
    nav = create_nav(share_class["id"], accounting_date="2026-08-04")
    fin = finalize_nav(nav["id"], expected_version=nav["version"])
    assert fin["status"] == "FINAL"
    assert_money(fin["expense_accrual_total"], 1.00, "expense_accrual_total")
    # Ratio == cap exactly: not a breach.
    assert_money(get_agreement(agreement["id"])["recoverable_balance"], 0.00,
                 "recoverable_balance")


def test_cap_exact_equality_leaves_ledger_empty(api):
    """PRD §3.5: "When that waiver amount is positive, the system books a
    `WAIVER` ledger entry on the agreement"
    PRD §3.5: "a breach exists only when the ratio is strictly greater than the
    cap — a ratio exactly equal to the cap is not a breach."

    Design: Difficulty/boundary_precision_check/expense_cap_exact_equality_no_waiver
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    subscribe_shares(share_class["id"], 10000)
    security = create_security()
    open_position(share_class["id"], security["id"], quantity=3650,
                  cost_basis_total=365000)
    px = submit_price(security["id"], price=100.00)
    approve_price(px["id"])
    agreement = create_waiver_agreement(share_class["id"], cap_bps=10)
    nav = create_nav(share_class["id"], accounting_date="2026-08-04")
    finalize_nav(nav["id"], expected_version=nav["version"])
    entries, meta = validate_paginated(
        api.list_waiver_ledger(agreement["id"], CTRL)
    )
    assert entries == [] and meta["total_count"] == 0


def test_recoup_on_exact_expiry_day_succeeds(api):
    """PRD §3.5: "Eligible funding sources are the agreement's `WAIVER` ledger
    entries whose `remaining_amount` exceeds zero and whose `expires_at` falls
    on or after the `recoup_date` — the window is inclusive, so a recoupment
    dated exactly on an entry's `expires_at` may still draw from it."

    Design: Difficulty/boundary_precision_check/recoup_window_last_day_inclusive
    """
    kit = cap_breach_kit(other_rate_bps=0.2)  # WAIVER 0.02, expires 2026-11-04
    set_logical_clock("2026-11-04T00:00:00Z")
    resp = api.post_recoupment(
        kit["agreement"]["id"],
        {"amount": 0.01, "recoup_date": "2026-11-04"},
        CTRL,
    )
    entry = validate_success(resp, 201)
    assert entry["entry_type"] == "RECOUPMENT"
    assert entry["entry_date"] == "2026-11-04"
    assert entry["expires_at"] is None
    assert_money(entry["remaining_amount"], 0.00, "RECOUPMENT remaining_amount")
    assert_money(get_agreement(kit["agreement"]["id"])["recoverable_balance"],
                 0.01, "recoverable_balance after partial recoupment")


def test_recoup_one_day_past_expiry_rejected(api):
    """PRD §3.5: "When no entry is eligible, the request fails with
    `ERR_RECOUP_WINDOW_EXPIRED` (HTTP 422)"
    PRD §3.5: "the window is inclusive, so a recoupment dated exactly on an
    entry's `expires_at` may still draw from it."

    Design: Difficulty/boundary_precision_check/recoup_window_last_day_inclusive
    """
    kit = cap_breach_kit(other_rate_bps=0.2)  # WAIVER 0.02, expires 2026-11-04
    set_logical_clock("2026-11-05T00:00:00Z")
    resp = api.post_recoupment(
        kit["agreement"]["id"],
        {"amount": 0.01, "recoup_date": "2026-11-05"},
        CTRL,
    )
    validate_error(resp, ApiErrorId.ERR_RECOUP_WINDOW_EXPIRED, 422)


def test_waiver_agreement_adjacent_start_rejected(api):
    """PRD §3.5: "a new agreement whose interval overlaps another `ACTIVE`
    agreement of the class — and a shared endpoint day counts as overlap — is
    rejected with `ERR_CAP_AGREEMENT_OVERLAP` (HTTP 409), so at most one
    agreement covers a class on any given day."

    Design: Difficulty/resource_temporal_overlap/waiver_agreement_closed_interval_adjacency_rejected
    """
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    create_waiver_agreement(share_class["id"], cap_bps=10,
                            effective_from="2026-08-01",
                            effective_to="2026-10-31")
    resp = api.create_waiver_agreement(
        {"share_class_id": share_class["id"], "cap_bps": 12,
         "effective_from": "2026-10-31", "effective_to": "2026-11-30",
         "recovery_window_months": 3},
        CTRL,
    )
    validate_error(resp, ApiErrorId.ERR_CAP_AGREEMENT_OVERLAP, 409)


def test_waiver_agreement_next_day_start_accepted(api):
    """PRD §3.5: "the interval is closed — both endpoint days are covered"
    PRD §3.5: "a new agreement whose interval overlaps another `ACTIVE`
    agreement of the class — and a shared endpoint day counts as overlap — is
    rejected with `ERR_CAP_AGREEMENT_OVERLAP` (HTTP 409), so at most one
    agreement covers a class on any given day."

    Design: Difficulty/resource_temporal_overlap/waiver_agreement_closed_interval_adjacency_rejected
    """
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    create_waiver_agreement(share_class["id"], cap_bps=10,
                            effective_from="2026-08-01",
                            effective_to="2026-10-31")
    resp = api.create_waiver_agreement(
        {"share_class_id": share_class["id"], "cap_bps": 12,
         "effective_from": "2026-11-01", "effective_to": "2026-12-31",
         "recovery_window_months": 3},
        CTRL,
    )
    agreement = validate_success(resp, 201)
    assert is_valid_uuid(agreement["id"])


def test_recoup_exceeds_balance_rejected(api):
    """PRD §3.5: "when the requested `amount` exceeds the sum of eligible
    remaining balances, it fails with `ERR_RECOUP_AMOUNT_EXCEEDS_BALANCE`
    (HTTP 422)."

    Design: Corner/validations/recoup_exceeds_balance_rejected
    """
    kit = cap_breach_kit(other_rate_bps=0.1)  # WAIVER 0.01 outstanding
    set_logical_clock("2026-08-10T00:00:00Z")
    too_much = api.post_recoupment(
        kit["agreement"]["id"],
        {"amount": 0.02, "recoup_date": "2026-08-10"},
        CTRL,
    )
    validate_error(too_much, ApiErrorId.ERR_RECOUP_AMOUNT_EXCEEDS_BALANCE, 422)

    full = api.post_recoupment(
        kit["agreement"]["id"],
        {"amount": 0.01, "recoup_date": "2026-08-10"},
        CTRL,
    )
    entry = validate_success(full, 201)
    assert entry["entry_type"] == "RECOUPMENT"


def test_recoup_on_expired_agreement_rejected(api):
    """PRD §3.5: "The agreement's derived status must be `ACTIVE`; recouping
    from an expired agreement is rejected with `ERR_AGREEMENT_NOT_ACTIVE`
    (HTTP 409)."
    PRD §2.10: "a waiver agreement's `status`, which reads `ACTIVE` while the
    logical clock date is on or before the agreement's last covered day and
    `EXPIRED` thereafter"

    Design: Corner/validations/recoup_on_expired_agreement_rejected
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    agreement = create_waiver_agreement(
        share_class["id"], cap_bps=10, effective_from="2026-08-01",
        effective_to="2026-09-01",
    )
    set_logical_clock("2026-09-02T00:00:00Z")
    assert get_agreement(agreement["id"])["status"] == "EXPIRED"
    resp = api.post_recoupment(
        agreement["id"], {"amount": 1.00, "recoup_date": "2026-09-02"}, CTRL
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)


def test_waiver_ledger_entry_immutability(api):
    """PRD §2.5: "Waiver ledger entries are the single exception to this
    convention: a ledger entry carries only `id` and `created_at`; both
    `updated_at` and `version` are absent, because ledger entries are immutable
    once booked."

    Design: Corner/entities/waiver_ledger_entry_immutability
    """
    kit = cap_breach_kit(other_rate_bps=0.1)  # books WAIVER 0.01 on finalize
    entries, meta = validate_paginated(
        api.list_waiver_ledger(kit["agreement"]["id"], CTRL)
    )
    assert meta["total_count"] == 1
    entry = entries[0]
    assert entry["entry_type"] == "WAIVER"
    assert_waiver_ledger_entry(entry)
