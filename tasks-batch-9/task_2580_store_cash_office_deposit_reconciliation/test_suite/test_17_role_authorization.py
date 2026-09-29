"""Who may touch the cash: endpoint role boundaries, cashier till ownership, and the bag's dual-control pair."""

from test_helpers import (
    ApiErrorId,
    CLERK_1,
    CLERK_2,
    CLERK_3,
    MANAGER_1,
    arm_open_request,
    assign_till,
    blind_count,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    escalate_case,
    list_cases,
    make_cashier_headers,
    open_safe,
    post_bank_credit_record,
    prepare_deposit,
    read_cashier,
    read_case,
    read_deposit,
    read_journal,
    read_safe,
    read_session,
    reconcile_till,
    schedule_pickup,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

BUSINESS_DATE = "2026-08-03"
SHIFT_START = "2026-08-03T09:00:00Z"
SHIFT_END = "2026-08-03T17:00:00Z"

#: A bag worth 100000 cents: fifty twenty-dollar notes.
BAG_LINES = [{"denomination_cents": 2000, "quantity": 50}]

#: A count worth 67000 cents: thirty-three twenties and one ten.
SHORT_COUNT_LINES = [
    {"denomination_cents": 2000, "quantity": 33},
    {"denomination_cents": 1000, "quantity": 1},
]


# --------------------------------------------------------------- setup recipes


def _open_the_cash_office(store_code, *, with_cashier=False, clock="2026-08-03T08:00:00Z"):
    """Register a store, commission its MANUAL safe and open the day's journal.

    Returns a dict with keys store, safe, journal and (optionally) cashier. The
    safe is left LOCKED with a 500000-cent opening balance.
    """
    set_clock(clock)
    store = create_store(
        store_code=store_code,
        name=f"Store {store_code[2:]}",
        region_code="WEST",
    )
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    ctx = {"store": store, "safe": safe}
    if with_cashier:
        ctx["cashier"] = create_cashier(
            store["id"], employee_code="E-100", display_name="Cashier 100"
        )
    ctx["journal"] = create_sales_journal(store["id"], BUSINESS_DATE)
    return ctx


def _unlock_the_safe(safe_id, *, armed_at="2026-08-03T08:00:00Z", opened_at="2026-08-03T08:05:00Z"):
    """Arm the time-delay device as U-CLERK-1 and open the safe as U-CLERK-2.

    The two identities differ, so the dual-control comparison on the open is
    satisfied, and the default five-minute delay has elapsed at `opened_at`.
    """
    set_clock(armed_at)
    arm_open_request(safe_id, CLERK_1, reason="Deposit preparation")
    set_clock(opened_at)
    return open_safe(safe_id, CLERK_2)


def _session_awaiting_a_count(ctx, *, closer_cashier_id=None, pos_cash_sales_cents=50000):
    """Assign register 1 to the store's cashier and close it at 17:00:00Z.

    Passing `closer_cashier_id` closes the register as that Cashier; leaving it
    out closes it as the StoreManager. Returns the PENDING_COUNT session id.
    """
    session = assign_till(
        ctx["journal"]["id"],
        ctx["cashier"]["id"],
        ctx["safe"]["id"],
        register_number=1,
        shift_start_at=SHIFT_START,
        shift_end_at=SHIFT_END,
        starting_bank_cents=20000,
    )
    set_clock(SHIFT_END)
    closed = close_till(
        session["id"],
        cashier_id=closer_cashier_id,
        pos_cash_sales_cents=pos_cash_sales_cents,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    assert closed["status"] == "PENDING_COUNT", (
        f"the close moves the session to PENDING_COUNT, got {closed['status']}"
    )
    return session["id"]


# ------------------------------------------------------------ endpoint denials


def test_cashier_cannot_blind_count_the_till_they_ran(api):
    """PRD §2.1: "A `CashOfficeClerk` runs the back-office cash room and is the only role that may open the day's journal, post POS tender totals, blind-count a till, order a recount, reconcile a till session, prepare an armored deposit, book a carrier pickup window, create a change order, or receive a change order into the safe; the clerk may not approve, void, or investigate anything."

    PRD §2.1: "A `Cashier` never sees the expected-cash figure and never counts their own till."
    PRD §2.1: "If the headers are well-formed but the named role does not appear on the endpoint's authorized-role list, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/cashier_cannot_blind_count_a_till
    """
    ctx = _open_the_cash_office("S-1970", with_cashier=True)
    cashier_id = ctx["cashier"]["id"]
    # The close itself is a shared Cashier/StoreManager operation and succeeds,
    # so the denial below is endpoint-specific rather than role-wide.
    session_id = _session_awaiting_a_count(ctx, closer_cashier_id=cashier_id)

    resp = api.blind_count(
        session_id,
        {"counted_lines": [{"denomination_cents": 2000, "quantity": 35}]},
        make_cashier_headers(cashier_id),
    )
    assert resp.status_code == 403, f"expected HTTP 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    session = read_session(session_id)
    assert session["status"] == "PENDING_COUNT", (
        f"the refused count leaves the session PENDING_COUNT, got {session['status']}"
    )
    assert session["counted_cash_cents"] is None, (
        f"counted_cash_cents must stay null, got {session['counted_cash_cents']}"
    )
    assert session["variance_cents"] is None, (
        f"variance_cents must stay null, got {session['variance_cents']}"
    )
    assert session["expected_cash_cents"] is None, (
        "the cashier never learns the expected figure, got "
        f"{session['expected_cash_cents']}"
    )


def test_cash_office_clerk_cannot_void_the_deposit_they_prepared(api, clerk_headers):
    """PRD §2.1: "A `StoreManager` is the accountable store officer and the only role that may enroll a cashier, void a deposit, or approve or reject a change order; the manager also supplies the second pair of hands for dual control and escalates suspected theft."

    PRD §3.6: "Voiding writes a compensating safe ledger row of kind `DEPOSIT_RETURN` linked to the deposit with `declared_amount_cents` equal to `declared_total_cents`, so that the recomputed `balance_cents` returns to its pre-preparation value — the removal row is never deleted, because the ledger is append-only."

    Design: Corner/rbac/cash_office_clerk_cannot_void_a_deposit
    """
    ctx = _open_the_cash_office("S-1971")
    safe_id = ctx["safe"]["id"]
    _unlock_the_safe(safe_id)
    deposit = prepare_deposit(
        safe_id,
        ctx["journal"]["id"],
        BAG_LINES,
        business_date=BUSINESS_DATE,
        preparer_user_id=CLERK_1,
    )
    assert deposit["declared_total_cents"] == 100000, (
        f"expected declared_total_cents 100000, got {deposit['declared_total_cents']}"
    )

    resp = api.void_deposit(
        deposit["id"], {"void_reason": "Miscount, want to redo the bag"}, clerk_headers
    )
    assert resp.status_code == 403, f"expected HTTP 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    after = read_deposit(deposit["id"])
    assert after["status"] == "PREPARING", (
        f"the refused void leaves the deposit PREPARING, got {after['status']}"
    )
    assert after["declared_total_cents"] == 100000, (
        f"expected declared_total_cents 100000, got {after['declared_total_cents']}"
    )

    safe = read_safe(safe_id)
    assert safe["balance_cents"] == 400000, (
        f"the 100000 stays withdrawn: expected balance_cents 400000, "
        f"got {safe['balance_cents']}"
    )
    rows, meta = validate_paginated(
        api.list_safe_transactions(
            clerk_headers, params={"safe_id": safe_id, "txn_type": "DEPOSIT_RETURN"}
        )
    )
    assert meta["total_count"] == 0, (
        f"no compensating DEPOSIT_RETURN row was written, got {meta['total_count']}"
    )


def test_treasury_analyst_cannot_prepare_an_armored_deposit(api, treasury_headers):
    """PRD §2.1: "A `TreasuryAnalyst` is central treasury and is alone able to register a store, commission a safe, post a bank credit record, post a card settlement, or reconcile a deposit against the bank; the analyst never touches physical cash and never counts a till."

    PRD §2.1: "If the headers are well-formed but the named role does not appear on the endpoint's authorized-role list, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/treasury_analyst_cannot_prepare_a_deposit
    """
    ctx = _open_the_cash_office("S-1972")
    safe_id = ctx["safe"]["id"]
    _unlock_the_safe(safe_id)
    # A valid, freshly read safe version in hand: the role check still fires
    # first, ahead of the optimistic-concurrency check on expected_safe_version.
    observed = read_safe(safe_id, treasury_headers)
    assert observed["open_state"] == "UNLOCKED", (
        f"the safe must be UNLOCKED before preparing, got {observed['open_state']}"
    )

    resp = api.create_deposit(
        {
            "safe_id": safe_id,
            "sales_journal_id": ctx["journal"]["id"],
            "business_date": BUSINESS_DATE,
            "counted_lines": BAG_LINES,
            "expected_safe_version": observed["version"],
        },
        treasury_headers,
    )
    assert resp.status_code == 403, f"expected HTTP 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    safe = read_safe(safe_id, treasury_headers)
    assert safe["balance_cents"] == 500000, (
        f"no cash left the safe: expected balance_cents 500000, got {safe['balance_cents']}"
    )
    assert safe["open_state"] == "UNLOCKED", (
        f"the refused preparation neither relocks the safe, got {safe['open_state']}"
    )
    assert safe["version"] == observed["version"], (
        f"nor mutates it: expected version {observed['version']}, got {safe['version']}"
    )
    deposits, meta = validate_paginated(
        api.list_deposits(
            treasury_headers, params={"sales_journal_id": ctx["journal"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no deposit was created on the journal, got {meta['total_count']}"
    )


def test_loss_prevention_cannot_reconcile_a_counted_till(api, investigator_headers):
    """PRD §2.1: "A `LossPreventionInvestigator` investigates suspected theft and is the only role that may restore a frozen safe's posture or close a variance case with a disposition."

    PRD §2.1: "A `CashOfficeClerk` runs the back-office cash room and is the only role that may open the day's journal, post POS tender totals, blind-count a till, order a recount, reconcile a till session, prepare an armored deposit, book a carrier pickup window, create a change order, or receive a change order into the safe; the clerk may not approve, void, or investigate anything."

    Design: Corner/rbac/loss_prevention_cannot_reconcile_a_till_session
    """
    ctx = _open_the_cash_office("S-1973", with_cashier=True)
    session_id = _session_awaiting_a_count(ctx)
    counted = blind_count(session_id, SHORT_COUNT_LINES, CLERK_3)
    assert counted["status"] == "COUNTED", (
        f"the blind count moves the session to COUNTED, got {counted['status']}"
    )
    assert counted["counted_cash_cents"] == 67000, (
        f"expected counted_cash_cents 67000, got {counted['counted_cash_cents']}"
    )

    resp = api.reconcile_till_session(session_id, investigator_headers)
    assert resp.status_code == 403, f"expected HTTP 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    session = read_session(session_id)
    assert session["status"] == "COUNTED", (
        f"the refused reconciliation leaves the session COUNTED, got {session['status']}"
    )
    assert session["counted_cash_cents"] == 67000, (
        f"expected counted_cash_cents 67000, got {session['counted_cash_cents']}"
    )
    assert session["expected_cash_cents"] is None, (
        f"expected_cash_cents stays masked, got {session['expected_cash_cents']}"
    )
    assert session["variance_cents"] is None, (
        f"variance_cents stays masked, got {session['variance_cents']}"
    )

    cases, meta = validate_paginated(
        api.list_variance_cases(
            investigator_headers, params={"sales_journal_id": ctx["journal"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no variance case was opened by the refused call, got {meta['total_count']}"
    )

    cashier = read_cashier(ctx["cashier"]["id"])
    assert cashier["rolling_absolute_variance_cents"] == 0, (
        "the rolling window was never recomputed: expected 0, got "
        f"{cashier['rolling_absolute_variance_cents']}"
    )
    assert cashier["reconciled_session_count"] == 0, (
        f"expected reconciled_session_count 0, got {cashier['reconciled_session_count']}"
    )
    assert cashier["coaching_state"] == "NONE", (
        f"expected coaching_state NONE, got {cashier['coaching_state']}"
    )


def test_store_manager_cannot_close_an_open_variance_case(api, manager_headers):
    """PRD §3.8: "Closing an escalated case belongs to the `LossPreventionInvestigator` alone, who records a `disposition` of either `SUBSTANTIATED` or `UNSUBSTANTIATED` and may attach a `closing_note`; a `closing_note`, when supplied, must be a non-empty string, and an empty one is refused with `ERR_INVALID_REQUEST`."

    PRD §2.12: "Second, role authorization: the acting role must appear on the endpoint's list, and additionally, when `X-User-Role` is `Cashier` the acting `X-User-ID` must equal the target till session's `cashier_id`; failure is `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/store_manager_cannot_close_a_variance_case
    """
    ctx = _open_the_cash_office("S-1974", with_cashier=True)
    session_id = _session_awaiting_a_count(ctx)
    blind_count(session_id, SHORT_COUNT_LINES, CLERK_3)
    session = reconcile_till(session_id, CLERK_1)
    assert session["variance_cents"] == -3000, (
        f"the till came up 3000 short: expected -3000, got {session['variance_cents']}"
    )

    cases = list_cases(
        sales_journal_id=ctx["journal"]["id"], case_type="SESSION_VARIANCE"
    )
    assert len(cases) == 1, f"expected exactly one SESSION_VARIANCE case, got {len(cases)}"
    case = cases[0]
    assert case["status"] == "OPEN", f"a new case has status OPEN, got {case['status']}"

    # Role authorization precedes the state check, so an OPEN case answers
    # ERR_UNAUTHORIZED rather than complaining about the transition.
    resp = api.close_variance_case(
        case["id"],
        {"disposition": "UNSUBSTANTIATED", "closing_note": "Manager wants to write it off"},
        manager_headers,
    )
    assert resp.status_code == 403, f"expected HTTP 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    after = read_case(case["id"])
    assert after["status"] == "OPEN", (
        f"the refused closure leaves the case OPEN, got {after['status']}"
    )
    assert after["disposition"] is None, (
        f"disposition must stay null, got {after['disposition']}"
    )
    assert after["closing_note"] is None, (
        f"closing_note must stay null, got {after['closing_note']}"
    )
    assert after["escalated_by_user_id"] is None, (
        f"escalated_by_user_id must stay null, got {after['escalated_by_user_id']}"
    )

    journal = read_journal(ctx["journal"]["id"])
    assert journal["open_case_count"] == 1, (
        f"the case still counts as open on the journal, got {journal['open_case_count']}"
    )


# ------------------------------------------------- ownership and dual control


def test_cashier_cannot_drop_into_another_cashiers_till(api, clerk_headers):
    """PRD §2.1: "Concretely, a `Cashier` acting on a till session whose `cashier_id` differs from `X-User-ID` is rejected with `ERR_UNAUTHORIZED`, and the same comparison governs reading a cashier record or acknowledging coaching."

    PRD §3.4: "During the shift, cash accumulates in the till and is periodically moved into the safe. Recording a drop is exclusive to the `Cashier`, who supplies the `txn_type` — either `MID_SHIFT_DROP` or `CLOSING_DROP` — the `declared_amount_cents` being dropped, and optionally a `memo`; when no memo is supplied the server authors a one-line provenance note of its own."

    Design: Corner/rbac/cashier_cannot_drop_into_another_cashiers_till
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1975", name="Store 1975", region_code="WEST")
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
        shift_start_at=SHIFT_START,
        shift_end_at=SHIFT_END,
        starting_bank_cents=20000,
    )
    session_b = assign_till(
        journal["id"],
        cashier_b["id"],
        safe["id"],
        register_number=2,
        shift_start_at=SHIFT_START,
        shift_end_at=SHIFT_END,
        starting_bank_cents=20000,
    )
    # A drop into a conventional safe requires that safe to be UNLOCKED, so the
    # positive control below turns only on ownership, never on the safe's state.
    _unlock_the_safe(safe["id"])
    set_clock("2026-08-03T13:00:00Z")

    drop_payload = {
        "txn_type": "MID_SHIFT_DROP",
        "declared_amount_cents": 30000,
        "memo": "Mid-shift drop into the wrong till",
    }
    resp = api.create_drop(
        session_a["id"], drop_payload, make_cashier_headers(cashier_b["id"])
    )
    assert resp.status_code == 403, f"expected HTTP 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    denied = read_session(session_a["id"])
    assert denied["dropped_declared_cents"] == 0, (
        f"no cash entered E-100's till total, got {denied['dropped_declared_cents']}"
    )
    assert denied["dropped_verified_cents"] is None, (
        f"dropped_verified_cents stays null, got {denied['dropped_verified_cents']}"
    )
    safe_after = read_safe(safe["id"])
    assert safe_after["balance_cents"] == 460000, (
        "two starting banks left 460000 in the safe and no drop row was written: got "
        f"{safe_after['balance_cents']}"
    )
    rows, meta = validate_paginated(
        api.list_safe_transactions(
            clerk_headers,
            params={"safe_id": safe["id"], "txn_type": "MID_SHIFT_DROP"},
        )
    )
    assert meta["total_count"] == 0, (
        f"no MID_SHIFT_DROP row was written, got {meta['total_count']}"
    )

    # The role itself is authorised: the identical call on her own session works.
    own = validate_success(
        api.create_drop(
            session_b["id"],
            {
                "txn_type": "MID_SHIFT_DROP",
                "declared_amount_cents": 30000,
                "memo": "Mid-shift drop BAG-2",
            },
            make_cashier_headers(cashier_b["id"]),
        ),
        201,
    )
    assert own["declared_amount_cents"] == 30000, (
        f"expected declared_amount_cents 30000, got {own['declared_amount_cents']}"
    )
    mine = read_session(session_b["id"])
    assert mine["dropped_declared_cents"] == 30000, (
        f"expected dropped_declared_cents 30000, got {mine['dropped_declared_cents']}"
    )


def test_the_preparer_of_a_bag_may_not_also_seal_it(api, clerk_headers, clerk_2_headers):
    """PRD §2.7: "Three separations of duty are enforced, and all three surface as `ERR_DUAL_CONTROL_VIOLATION` (HTTP 403)."

    PRD §2.7: "While a store's `dual_control_required` is true, the `X-User-ID` opening a safe must differ from the `open_requested_by_user_id` recorded on the pending request; the `X-User-ID` sealing a deposit must differ from the deposit's `prepared_by_user_id`; and the `X-User-ID` reconciling a till session must differ from that session's `counted_by_user_id`."

    PRD §3.6: "Sealing records `seal_number` and `sealed_by_user_id`, moves the deposit from `PREPARING` to `SEALED`, and ends the cash-office opening: the parent safe's `open_state` returns from `UNLOCKED` to `LOCKED` with `open_requested_at`, `open_requested_by_user_id` and `unlocked_at` all cleared, and the safe's `version` increments by 1 alongside the deposit's."

    Design: Corner/rbac/same_user_must_not_prepare_and_seal_the_same_deposit
    """
    ctx = _open_the_cash_office("S-1976")
    safe_id = ctx["safe"]["id"]
    assert ctx["store"]["dual_control_required"] is True, (
        "dual_control_required defaults to true, got "
        f"{ctx['store']['dual_control_required']}"
    )
    _unlock_the_safe(safe_id)
    deposit = prepare_deposit(
        safe_id,
        ctx["journal"]["id"],
        BAG_LINES,
        business_date=BUSINESS_DATE,
        preparer_user_id=CLERK_1,
    )
    assert deposit["prepared_by_user_id"] == CLERK_1, (
        f"expected prepared_by_user_id {CLERK_1}, got {deposit['prepared_by_user_id']}"
    )

    # U-CLERK-1 holds a role listed on the seal endpoint, so this is a
    # segregation-of-duties failure and not an authorization failure.
    resp = api.seal_deposit(deposit["id"], {"seal_number": "SEAL-SOLO"}, clerk_headers)
    assert resp.status_code == 403, f"expected HTTP 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_DUAL_CONTROL_VIOLATION.value)

    after = read_deposit(deposit["id"])
    assert after["status"] == "PREPARING", (
        f"the refused seal leaves the deposit PREPARING, got {after['status']}"
    )
    assert after["seal_number"] is None, (
        f"seal_number must stay null, got {after['seal_number']}"
    )
    assert after["sealed_by_user_id"] is None, (
        f"sealed_by_user_id must stay null, got {after['sealed_by_user_id']}"
    )
    assert after["prepared_by_user_id"] == CLERK_1, (
        f"expected prepared_by_user_id {CLERK_1}, got {after['prepared_by_user_id']}"
    )
    still_open = read_safe(safe_id)
    assert still_open["open_state"] == "UNLOCKED", (
        f"the failed seal did not relock the safe, got {still_open['open_state']}"
    )

    # A second pair of hands completes the pair.
    sealed = validate_success(
        api.seal_deposit(deposit["id"], {"seal_number": "SEAL-SOLO"}, clerk_2_headers)
    )
    assert sealed["status"] == "SEALED", (
        f"U-CLERK-2 may seal what U-CLERK-1 prepared, got {sealed['status']}"
    )
    assert sealed["sealed_by_user_id"] == CLERK_2, (
        f"expected sealed_by_user_id {CLERK_2}, got {sealed['sealed_by_user_id']}"
    )
    relocked = read_safe(safe_id)
    assert relocked["open_state"] == "LOCKED", (
        f"sealing ends the cash-office opening, got {relocked['open_state']}"
    )


# --------------------------------------------------- positive coverage sweep


def test_each_role_performs_its_own_exclusive_operation(
    api, treasury_headers, manager_headers, clerk_headers, carrier_headers, investigator_headers
):
    """PRD §2.1: "A `Cashier` operates a register till: takes the starting bank, makes mid-shift and closing drops, closes the register at shift end, and inserts sealed bags into a smart safe. Recording a till drop is exclusive to this role."

    PRD §2.1: "An `ArmoredCarrier` is external crew: it sees the deposits booked for pickup and signs for them, which is exclusive to the role."

    PRD §3.7: "When `credit_variance_cents` computes to zero, the deposit moves from `IN_TRANSIT` to `RECONCILED`: `credited_total_cents` and a zero `credit_variance_cents` are stored, the deposit leaves the provisional pool so the safe's `provisional_credit_balance_cents` is recomputed, the journal's compound derivation is re-evaluated, and **no** variance case is opened."

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operation
    """
    set_clock("2026-08-03T08:00:00Z")

    # TreasuryAnalyst: registering a store is treasury's alone.
    store = validate_success(
        api.create_store(
            {"store_code": "S-1977", "name": "Store 1977", "region_code": "WEST"},
            treasury_headers,
        ),
        201,
    )
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )

    # StoreManager: enrolling a cashier is the manager's alone.
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

    # CashOfficeClerk: opening the day's journal is the clerk's alone.
    journal = validate_success(
        api.create_sales_journal(
            {"store_id": store["id"], "business_date": BUSINESS_DATE}, clerk_headers
        ),
        201,
    )

    session = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at=SHIFT_START,
        shift_end_at=SHIFT_END,
        starting_bank_cents=20000,
    )
    _unlock_the_safe(safe["id"])
    set_clock("2026-08-03T13:00:00Z")

    # Cashier: recording a till drop is exclusive to this role.
    drop = validate_success(
        api.create_drop(
            session["id"],
            {
                "txn_type": "MID_SHIFT_DROP",
                "declared_amount_cents": 60000,
                "memo": "Mid-shift drop BAG-1",
            },
            make_cashier_headers(cashier["id"]),
        ),
        201,
    )
    assert drop["txn_type"] == "MID_SHIFT_DROP", (
        f"expected a MID_SHIFT_DROP row, got {drop['txn_type']}"
    )

    set_clock(SHIFT_END)
    close_till(
        session["id"],
        cashier_id=cashier["id"],
        pos_cash_sales_cents=160000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    # CashOfficeClerk: the blind count and the reconciliation are the clerk's
    # alone, and dual control keeps the counter apart from the reconciler.
    blind_count(session["id"], [{"denomination_cents": 2000, "quantity": 30}], CLERK_3)
    reconciled = reconcile_till(session["id"], CLERK_1)
    assert reconciled["variance_cents"] == -60000, (
        f"expected variance_cents -60000, got {reconciled['variance_cents']}"
    )

    cases = list_cases(sales_journal_id=journal["id"], case_type="SESSION_VARIANCE")
    assert len(cases) == 1, f"expected exactly one SESSION_VARIANCE case, got {len(cases)}"
    case = cases[0]
    escalate_case(
        case["id"],
        reason="Large short on a single till",
        user_id=MANAGER_1,
        as_manager=True,
    )

    # LossPreventionInvestigator: disposing of an escalated case is LP's alone.
    closed_case = validate_success(
        api.close_variance_case(
            case["id"],
            {
                "disposition": "UNSUBSTANTIATED",
                "closing_note": "Coin jam in the recycler, cash later found",
            },
            investigator_headers,
        )
    )
    assert closed_case["status"] == "CLOSED_UNSUBSTANTIATED", (
        f"expected CLOSED_UNSUBSTANTIATED, got {closed_case['status']}"
    )

    set_clock("2026-08-03T17:10:00Z")
    # CashOfficeClerk: preparing the armored bag is the clerk's alone. The safe
    # is still UNLOCKED from the drop, because preparing does not relock it and
    # the closure of the case restored every safe's posture to OPEN.
    observed = read_safe(safe["id"])
    assert observed["posture"] == "OPEN", (
        f"the closed case lifted the freeze, got posture {observed['posture']}"
    )
    deposit = prepare_deposit(
        safe["id"],
        journal["id"],
        BAG_LINES,
        business_date=BUSINESS_DATE,
        preparer_user_id=CLERK_1,
        expected_safe_version=observed["version"],
    )
    assert deposit["expected_credit_cents"] == 98765, (
        f"expected expected_credit_cents 98765, got {deposit['expected_credit_cents']}"
    )
    validate_success(
        api.seal_deposit(deposit["id"], {"seal_number": "SEAL-1977"}, manager_headers)
    )
    # CashOfficeClerk: booking the carrier pickup window is the clerk's alone.
    schedule_pickup(
        deposit["id"],
        "2026-08-04T09:00:00Z",
        "2026-08-04T09:30:00Z",
        carrier_reference="GUARDTRUST-1977",
        user_id=CLERK_1,
    )

    set_clock("2026-08-04T09:15:00Z")
    # ArmoredCarrier: signing for the bag is exclusive to the crew.
    in_transit = validate_success(
        api.pickup_deposit(
            deposit["id"],
            {
                "picked_up_at": "2026-08-04T09:15:00Z",
                "carrier_signature": "CREW-7 / MAN-1977",
            },
            carrier_headers,
        )
    )
    assert in_transit["status"] == "IN_TRANSIT", (
        f"expected IN_TRANSIT after the handover, got {in_transit['status']}"
    )

    record = post_bank_credit_record(
        store["id"],
        98765,
        credit_type="FINAL",
        deposit_id=deposit["id"],
        value_date="2026-08-05",
        bank_reference="BR-1977",
    )

    # TreasuryAnalyst: reconciling a deposit against the bank is treasury's alone.
    banked = validate_success(
        api.reconcile_bank(
            deposit["id"], {"bank_credit_record_ids": [record["id"]]}, treasury_headers
        )
    )
    assert banked["status"] == "RECONCILED", (
        f"expected RECONCILED, got {banked['status']}"
    )
    assert banked["credited_total_cents"] == 98765, (
        f"expected credited_total_cents 98765, got {banked['credited_total_cents']}"
    )
    assert banked["credit_variance_cents"] == 0, (
        f"expected credit_variance_cents 0, got {banked['credit_variance_cents']}"
    )

    final_session = read_session(session["id"])
    assert final_session["status"] == "RECONCILED", (
        f"expected the session RECONCILED, got {final_session['status']}"
    )
    assert final_session["variance_cents"] == -60000, (
        f"expected variance_cents -60000, got {final_session['variance_cents']}"
    )
    assert final_session["dropped_declared_cents"] == 60000, (
        f"expected dropped_declared_cents 60000, got "
        f"{final_session['dropped_declared_cents']}"
    )
    final_case = read_case(case["id"])
    assert final_case["status"] == "CLOSED_UNSUBSTANTIATED", (
        f"expected CLOSED_UNSUBSTANTIATED, got {final_case['status']}"
    )
    final_safe = read_safe(safe["id"])
    assert final_safe["posture"] == "OPEN", (
        f"expected posture OPEN, got {final_safe['posture']}"
    )
    assert final_safe["balance_cents"] == 440000, (
        "500000 opening less the 20000 starting bank plus the 60000 drop less the "
        f"100000 deposit is 440000, got {final_safe['balance_cents']}"
    )
