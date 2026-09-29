"""Two-variant money calculations: the till over/short drop basis and the two provisional-credit variants."""

from test_helpers import (
    CARRIER_1,
    CLERK_1,
    CLERK_2,
    CLERK_3,
    CLERK_4,
    assign_till,
    blind_count,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    insert_smart_deposit,
    list_cases,
    make_carrier_headers,
    make_clerk_headers,
    parse_instant,
    prepare_deposit,
    read_cashier,
    read_deposit,
    read_safe,
    read_session,
    record_drop,
    schedule_pickup,
    seal_deposit,
    set_clock,
    unlock_safe,
    validate_success,
)

# The cash office re-counted the closing drop bag at 146500 while the cashier had
# declared 147500, so the bag is over-declared by exactly 1000 cents.
DEPOSIT_BAG_LINES = [
    {"denomination_cents": 2000, "quantity": 70},
    {"denomination_cents": 1000, "quantity": 6},
    {"denomination_cents": 100, "quantity": 5},
]

# The blind count found nine twenty-dollar notes, that is 18000 cents.
TILL_COUNT_LINES = [{"denomination_cents": 2000, "quantity": 9}]

# One hundred twenty-dollar notes, four hundred one-dollar notes and eighty
# quarters: the identical physical bag offered to both credit pathways.
REFERENCE_BAG_LINES = [
    {"denomination_cents": 2000, "quantity": 100},
    {"denomination_cents": 100, "quantity": 400},
    {"denomination_cents": 25, "quantity": 80},
]


def _setup_counted_session(verify_drops: bool):
    """Drive one till session to COUNTED at a store whose single-event threshold is 2500.

    When `verify_drops` is true the cash office also prepares an armored deposit
    naming the session in verify_till_session_ids, which writes the 146500
    re-count onto the session's closing drop row and populates
    dropped_verified_cents. When it is false no deposit is prepared, so the drop
    rows stay unverified and dropped_verified_cents stays null.
    """
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(
        store_code="S-1001",
        name="Store 1001",
        region_code="WEST",
        safe_time_delay_minutes=5,
        safe_open_window_minutes=10,
        dual_control_required=True,
        single_event_variance_threshold_cents=2500,
        rolling_variance_threshold_cents=10000,
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
    # Arm at 16:50Z and open at 16:55Z so the closing drop lands in an open safe.
    unlock_safe(
        safe["id"],
        "2026-08-03T16:50:00Z",
        delay_minutes=5,
        requester_user_id=CLERK_1,
        opener_user_id=CLERK_2,
    )
    record_drop(
        session["id"],
        cashier["id"],
        147500,
        txn_type="CLOSING_DROP",
        memo="Closing drop register 1",
    )
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session["id"],
        cashier_id=cashier["id"],
        pos_cash_sales_cents=150000,
        pos_card_sales_cents=80000,
        pos_paid_out_cents=2500,
    )
    blind_count(session["id"], TILL_COUNT_LINES, counter_user_id=CLERK_3)
    deposit = None
    if verify_drops:
        deposit = prepare_deposit(
            safe["id"],
            journal["id"],
            DEPOSIT_BAG_LINES,
            business_date="2026-08-03",
            preparer_user_id=CLERK_1,
            verify_till_session_ids=[session["id"]],
        )
    return {
        "store": store,
        "safe": safe,
        "cashier": cashier,
        "journal": journal,
        "session": session,
        "deposit": deposit,
    }


def _reconcile(api, session_id):
    """Reconcile as U-CLERK-4, who differs from the counting U-CLERK-3."""
    return validate_success(
        api.reconcile_till_session(session_id, make_clerk_headers(CLERK_4))
    )


def test_verified_drop_basis_sets_expected_cash_and_variance(api):
    """PRD §3.5: "If `dropped_verified_cents` is non-null at the moment reconciliation runs, `variance_basis` is recorded as `VERIFIED_DROPS` and the drop total used is `dropped_verified_cents`; otherwise `variance_basis` is recorded as `DECLARED_DROPS` and the drop total used is `dropped_declared_cents`."

    PRD §3.5: "The expected till contents are then the session's `starting_bank_cents`, plus its `pos_cash_sales_cents`, minus its `pos_paid_out_cents`, minus the chosen drop total; the result is stored as `expected_cash_cents`."

    PRD §3.6: "A session's share of the re-count is the deposit's `declared_total_cents` apportioned across the listed sessions in proportion to each session's `dropped_declared_cents`, rounded half up to whole cents; when exactly one session is listed — the ordinary case — its share is simply the deposit's `declared_total_cents`."

    Design: Difficulty/dual_variant_calc/till_over_short_verified_drops_variant_flips_coaching_threshold
    """
    ctx = _setup_counted_session(verify_drops=True)
    reconciled = _reconcile(api, ctx["session"]["id"])

    assert reconciled["dropped_declared_cents"] == 147500, (
        f"expected dropped_declared_cents 147500, got {reconciled['dropped_declared_cents']}"
    )
    assert reconciled["dropped_verified_cents"] == 146500, (
        f"expected dropped_verified_cents 146500, got {reconciled['dropped_verified_cents']}"
    )
    assert reconciled["variance_basis"] == "VERIFIED_DROPS", (
        f"expected variance_basis VERIFIED_DROPS, got {reconciled['variance_basis']}"
    )
    assert reconciled["expected_cash_cents"] == 21000, (
        f"expected expected_cash_cents 21000, got {reconciled['expected_cash_cents']}"
    )
    assert reconciled["variance_cents"] == -3000, (
        f"expected variance_cents -3000, got {reconciled['variance_cents']}"
    )
    assert reconciled["status"] == "RECONCILED", (
        f"expected status RECONCILED, got {reconciled['status']}"
    )

    # The unmasked figures survive a subsequent read of the session.
    stored = read_session(ctx["session"]["id"])
    assert stored["expected_cash_cents"] == 21000, (
        f"expected expected_cash_cents 21000 on read, got {stored['expected_cash_cents']}"
    )
    assert stored["variance_cents"] == -3000, (
        f"expected variance_cents -3000 on read, got {stored['variance_cents']}"
    )


def test_verified_drop_basis_fires_coaching_and_opens_session_variance_case(api):
    """PRD §3.5: "In the same link, if the absolute value of the session's own `variance_cents` is at or above the store's `single_event_variance_threshold_cents` — twenty-five dollars by default — the cashier's `coaching_state` is set to `COACHING_DUE`, `coaching_due_at` is set to the current clock plus 72 hours, and a variance case is opened with `case_type` `SESSION_VARIANCE` naming this cashier and this sales journal."

    PRD §3.5: "From that set, `reconciled_session_count` becomes the number of sessions, `rolling_absolute_variance_cents` becomes the sum of the absolute values of their variances, and `rolling_net_variance_cents` becomes the signed sum of the same variances."

    PRD §3.8: "For a `SESSION_VARIANCE` case the `total_variance_cents` is the absolute value of the triggering session's `variance_cents`; for a `ROLLING_PATTERN` case it is the cashier's freshly recomputed `rolling_absolute_variance_cents`; for a `DEPOSIT_CREDIT` case it is the absolute value of the deposit's `credit_variance_cents`."

    Design: Difficulty/dual_variant_calc/till_over_short_verified_drops_variant_flips_coaching_threshold
    """
    ctx = _setup_counted_session(verify_drops=True)
    _reconcile(api, ctx["session"]["id"])

    cashier = read_cashier(ctx["cashier"]["id"])
    assert cashier["coaching_state"] == "COACHING_DUE", (
        f"expected coaching_state COACHING_DUE, got {cashier['coaching_state']}"
    )
    assert parse_instant(cashier["coaching_due_at"]) == parse_instant(
        "2026-08-06T17:00:00Z"
    ), (
        "expected coaching_due_at 2026-08-06T17:00:00Z, got "
        f"{cashier['coaching_due_at']}"
    )
    assert cashier["rolling_absolute_variance_cents"] == 3000, (
        "expected rolling_absolute_variance_cents 3000, got "
        f"{cashier['rolling_absolute_variance_cents']}"
    )
    assert cashier["rolling_net_variance_cents"] == -3000, (
        "expected rolling_net_variance_cents -3000, got "
        f"{cashier['rolling_net_variance_cents']}"
    )
    assert cashier["till_eligibility"] == "ELIGIBLE", (
        f"expected till_eligibility ELIGIBLE, got {cashier['till_eligibility']}"
    )

    cases = list_cases(sales_journal_id=ctx["journal"]["id"])
    assert len(cases) == 1, f"expected exactly 1 variance case, got {len(cases)}"
    assert cases[0]["case_type"] == "SESSION_VARIANCE", (
        f"expected case_type SESSION_VARIANCE, got {cases[0]['case_type']}"
    )
    assert cases[0]["total_variance_cents"] == 3000, (
        f"expected total_variance_cents 3000, got {cases[0]['total_variance_cents']}"
    )


def test_declared_drop_basis_reports_smaller_short_and_no_coaching(api):
    """PRD §3.5: "The two branches are not cosmetic: relative to the declared branch, the verified branch raises `expected_cash_cents` by the amount by which the declared drops exceeded the verified drops, and moves the reported variance by that same amount — which can push the absolute variance across the store's single-event threshold on an otherwise identical reconciliation."

    PRD §3.5: "Put the other way, a drop bag that was over-declared reports a *smaller* short under the declared branch than under the verified branch."

    Design: Difficulty/dual_variant_calc/till_over_short_verified_drops_variant_flips_coaching_threshold
    """
    ctx = _setup_counted_session(verify_drops=False)
    reconciled = _reconcile(api, ctx["session"]["id"])

    assert reconciled["variance_basis"] == "DECLARED_DROPS", (
        f"expected variance_basis DECLARED_DROPS, got {reconciled['variance_basis']}"
    )
    assert reconciled["dropped_declared_cents"] == 147500, (
        f"expected dropped_declared_cents 147500, got {reconciled['dropped_declared_cents']}"
    )
    assert reconciled["dropped_verified_cents"] is None, (
        "dropped_verified_cents stays null while any drop row is unverified, got "
        f"{reconciled['dropped_verified_cents']}"
    )
    assert reconciled["expected_cash_cents"] == 20000, (
        f"expected expected_cash_cents 20000, got {reconciled['expected_cash_cents']}"
    )
    assert reconciled["variance_cents"] == -2000, (
        f"expected variance_cents -2000, got {reconciled['variance_cents']}"
    )
    assert reconciled["status"] == "RECONCILED", (
        f"expected status RECONCILED, got {reconciled['status']}"
    )

    # -2000 sits below the store's 2500 single-event threshold, so no coaching
    # obligation and no SESSION_VARIANCE case arise on the identical counted cash.
    cashier = read_cashier(ctx["cashier"]["id"])
    assert cashier["coaching_state"] == "NONE", (
        f"expected coaching_state NONE, got {cashier['coaching_state']}"
    )
    assert cashier["coaching_due_at"] is None, (
        f"expected coaching_due_at null, got {cashier['coaching_due_at']}"
    )
    cases = list_cases(sales_journal_id=ctx["journal"]["id"])
    assert len(cases) == 0, f"expected no variance case below threshold, got {len(cases)}"


def _setup_both_credit_pathways():
    """Offer the identical reference bag to a smart safe and to an armored carrier.

    Both bags carry 4000 cents of suspect notes and both are banked against the
    same sales journal at a store whose provisional_credit_cap_cents is 500000,
    so the cap binds on neither pathway and only the validator's own exclusions
    can separate the two credited figures.
    """
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(
        store_code="S-1002",
        name="Store 1002",
        region_code="WEST",
        safe_time_delay_minutes=5,
        safe_open_window_minutes=10,
        dual_control_required=True,
        provisional_credit_cap_cents=500000,
    )
    smart_safe = create_safe(
        store["id"],
        safe_code="SAFE-S",
        safe_type="SMART",
        opening_balance_cents=0,
    )
    manual_safe = create_safe(
        store["id"],
        safe_code="SAFE-M",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    smart_deposit = insert_smart_deposit(
        smart_safe["id"],
        journal["id"],
        REFERENCE_BAG_LINES,
        business_date="2026-08-03",
        suspect_note_cents=4000,
        headers=make_clerk_headers(CLERK_1),
    )

    # The armored pathway needs the conventional safe physically open.
    unlock_safe(
        manual_safe["id"],
        "2026-08-03T09:00:00Z",
        delay_minutes=5,
        requester_user_id=CLERK_1,
        opener_user_id=CLERK_2,
    )
    manual_deposit = prepare_deposit(
        manual_safe["id"],
        journal["id"],
        REFERENCE_BAG_LINES,
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
        suspect_note_cents=4000,
    )
    seal_deposit(manual_deposit["id"], "SEAL-M-001", sealer_user_id=CLERK_2)
    schedule_pickup(
        manual_deposit["id"],
        "2026-08-03T14:00:00Z",
        "2026-08-03T14:30:00Z",
        carrier_reference="CR-M-001",
        user_id=CLERK_1,
    )
    set_clock("2026-08-03T14:05:00Z")
    return {
        "store": store,
        "smart_safe": smart_safe,
        "manual_safe": manual_safe,
        "journal": journal,
        "smart_deposit": smart_deposit,
        "manual_deposit": manual_deposit,
    }


def _sign_for_bag(api, deposit_id):
    """The carrier signs for the sealed bag, which grants carrier provisional credit."""
    return validate_success(
        api.pickup_deposit(
            deposit_id,
            {
                "picked_up_at": "2026-08-03T14:05:00Z",
                "carrier_signature": "SIG-CARRIER-7",
            },
            make_carrier_headers(CARRIER_1),
        )
    )


def test_smart_validator_and_carrier_receipt_credit_the_same_bag_differently(api):
    """PRD §3.6: "Only denominations the validator can read earn credit: the validated value is the sum, over every line whose `denomination_cents` is at least 500, of `denomination_cents` multiplied by `quantity`."

    PRD §3.6: "From that the deposit's `suspect_note_cents` is subtracted — the notes the validator rejected — and the result is capped, so `provisional_credit_cents` is the smaller of that net validated figure and the store's `provisional_credit_cap_cents`."

    PRD §3.6: "Signing for the bag starts the provisional-credit clock: the carrier variant of the provisional-credit rule sets `provisional_credit_cents` to the smaller of `declared_total_cents` and the store's `provisional_credit_cap_cents`."

    Design: Difficulty/dual_variant_calc/provisional_credit_smart_validator_versus_carrier_receipt_divergence
    """
    ctx = _setup_both_credit_pathways()
    picked_up = _sign_for_bag(api, ctx["manual_deposit"]["id"])

    smart = read_deposit(ctx["smart_deposit"]["id"])
    assert smart["declared_total_cents"] == 242000, (
        f"expected declared_total_cents 242000, got {smart['declared_total_cents']}"
    )
    assert smart["credit_basis"] == "SMART_PROVISIONAL", (
        f"expected credit_basis SMART_PROVISIONAL, got {smart['credit_basis']}"
    )
    assert smart["provisional_credit_cents"] == 196000, (
        "expected provisional_credit_cents 196000 through the validator, got "
        f"{smart['provisional_credit_cents']}"
    )

    assert picked_up["declared_total_cents"] == 242000, (
        f"expected declared_total_cents 242000, got {picked_up['declared_total_cents']}"
    )
    assert picked_up["credit_basis"] == "CARRIER_PROVISIONAL", (
        f"expected credit_basis CARRIER_PROVISIONAL, got {picked_up['credit_basis']}"
    )
    assert picked_up["provisional_credit_cents"] == 242000, (
        "expected provisional_credit_cents 242000 on the carrier receipt, got "
        f"{picked_up['provisional_credit_cents']}"
    )
    assert picked_up["status"] == "IN_TRANSIT", (
        f"expected status IN_TRANSIT, got {picked_up['status']}"
    )


def test_credit_basis_divergence_carries_into_the_safe_provisional_balances(api):
    """PRD §3.6: "The two variants can diverge sharply on identical physical cash: a bag of one hundred twenty-dollar notes, four hundred one-dollar notes and eighty quarters, with forty dollars of notes rejected as suspect, earns 196000 cents on insertion into a smart safe but 242000 cents when the same bag is signed for by a carrier — a 46000-cent divergence."

    PRD §2.6: "`provisional_credit_balance_cents` is the sum of the amounts of provisional bank credit records belonging to this safe's deposits that have not yet reached the reconciled state — the float the bank has advanced and may still reverse."

    PRD §2.6: "`suspect_note_cents` is the sum of the suspect-note values across this safe's smart-safe deposits that are not yet reconciled."

    Design: Difficulty/dual_variant_calc/provisional_credit_smart_validator_versus_carrier_receipt_divergence
    """
    ctx = _setup_both_credit_pathways()
    _sign_for_bag(api, ctx["manual_deposit"]["id"])

    smart = read_deposit(ctx["smart_deposit"]["id"])
    manual = read_deposit(ctx["manual_deposit"]["id"])
    divergence = manual["provisional_credit_cents"] - smart["provisional_credit_cents"]
    assert divergence == 46000, (
        f"expected a 46000-cent divergence on identical cash, got {divergence}"
    )

    smart_safe = read_safe(ctx["smart_safe"]["id"])
    assert smart_safe["provisional_credit_balance_cents"] == 196000, (
        "expected the smart safe's provisional_credit_balance_cents 196000, got "
        f"{smart_safe['provisional_credit_balance_cents']}"
    )
    assert smart_safe["suspect_note_cents"] == 4000, (
        "expected the smart safe's suspect_note_cents 4000, got "
        f"{smart_safe['suspect_note_cents']}"
    )

    manual_safe = read_safe(ctx["manual_safe"]["id"])
    assert manual_safe["provisional_credit_balance_cents"] == 242000, (
        "expected the manual safe's provisional_credit_balance_cents 242000, got "
        f"{manual_safe['provisional_credit_balance_cents']}"
    )
