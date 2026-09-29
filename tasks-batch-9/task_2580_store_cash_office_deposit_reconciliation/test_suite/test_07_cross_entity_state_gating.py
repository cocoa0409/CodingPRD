"""Till issue gated by the cashier's two dimensions, and bank reconciliation gated by credit type."""

from test_helpers import (
    ApiErrorId,
    CARRIER_2,
    CLERK_1,
    CLERK_2,
    CLERK_3,
    acknowledge_coaching,
    arm_open_request,
    assign_till,
    blind_count,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    lines,
    open_safe,
    pickup_deposit,
    post_bank_credit_record,
    prepare_and_seal_deposit,
    read_cashier,
    read_deposit,
    read_journal,
    read_safe,
    reconcile_till,
    record_drop,
    schedule_pickup,
    set_clock,
    till_session_payload,
    validate_error,
    validate_success,
)

SESSION_C_PAYLOAD_KWARGS = {
    "register_number": 3,
    "shift_start_at": "2026-08-03T17:00:00Z",
    "shift_end_at": "2026-08-03T21:00:00Z",
    "starting_bank_cents": 20000,
}


def _run_session_to_reconciled(
    journal_id,
    cashier_id,
    safe_id,
    register_number,
    shift_start_at,
    shift_end_at,
    close_at,
    drop_amount_cents,
    pos_cash_sales_cents,
    counted_lines,
):
    """Assign, drop, close, blind-count and reconcile one till session.

    The counter is U-CLERK-3 and the reconciler U-CLERK-2, because under dual
    control the reconciling X-User-ID must differ from counted_by_user_id.
    """
    session = assign_till(
        journal_id,
        cashier_id,
        safe_id,
        register_number=register_number,
        shift_start_at=shift_start_at,
        shift_end_at=shift_end_at,
        starting_bank_cents=20000,
    )
    record_drop(session["id"], cashier_id, drop_amount_cents, txn_type="CLOSING_DROP")
    set_clock(close_at)
    close_till(
        session["id"],
        cashier_id=cashier_id,
        pos_cash_sales_cents=pos_cash_sales_cents,
        pos_card_sales_cents=40000,
        pos_paid_out_cents=0,
    )
    blind_count(session["id"], counted_lines, CLERK_3)
    return reconcile_till(session["id"], CLERK_2)


def _setup_restricted_and_coaching_due_cashier():
    """Cashier E-100 with two RECONCILED sessions of -3000 and -7000 variance.

    That makes rolling_absolute_variance_cents 10000, which is at the store's
    rolling_variance_threshold_cents, so till_eligibility is RESTRICTED, and each
    single-event breach leaves coaching_state at COACHING_DUE.
    """
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(
        store_code="S-1013",
        name="Store 1013",
        region_code="WEST",
        safe_time_delay_minutes=5,
        safe_open_window_minutes=10,
        dual_control_required=True,
        single_event_variance_threshold_cents=2500,
        rolling_variance_threshold_cents=10000,
        rolling_window_days=30,
    )
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    cashier = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    arm_open_request(safe["id"], CLERK_1, reason="Cash room open")
    set_clock("2026-08-03T09:05:00Z")
    open_safe(safe["id"], CLERK_2)

    _run_session_to_reconciled(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T13:00:00Z",
        close_at="2026-08-03T13:00:00Z",
        drop_amount_cents=100000,
        pos_cash_sales_cents=100000,
        counted_lines=lines((2000, 8), (1000, 1)),
    )
    _run_session_to_reconciled(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=2,
        shift_start_at="2026-08-03T13:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        close_at="2026-08-03T17:00:00Z",
        drop_amount_cents=150000,
        pos_cash_sales_cents=150000,
        counted_lines=lines((2000, 6), (1000, 1)),
    )
    return {"store": store, "safe": safe, "cashier": cashier, "journal": journal}


def test_restricted_and_coaching_due_cashier_refused_a_till(api, manager_headers):
    """PRD §3.2: "A cashier whose `till_eligibility` is `RESTRICTED` may be assigned only while `coaching_state` is `COACHING_ACKNOWLEDGED`; otherwise the answer is `ERR_CASHIER_RESTRICTED`."

    PRD §3.2: "The acknowledgement moves `coaching_state` from `COACHING_DUE` to `COACHING_ACKNOWLEDGED` and increments the cashier's `version`; it leaves `till_eligibility` exactly as it was."

    Design: Difficulty/cross_entity_state_dependency/till_assignment_gated_by_cashier_eligibility_and_coaching_dimensions
    """
    ctx = _setup_restricted_and_coaching_due_cashier()
    cashier = read_cashier(ctx["cashier"]["id"])
    assert cashier["till_eligibility"] == "RESTRICTED", (
        f"expected RESTRICTED, got {cashier['till_eligibility']}"
    )
    assert cashier["coaching_state"] == "COACHING_DUE", (
        f"expected COACHING_DUE, got {cashier['coaching_state']}"
    )
    assert cashier["rolling_absolute_variance_cents"] == 10000, (
        "expected 10000, got "
        f"{cashier['rolling_absolute_variance_cents']}"
    )

    refused = api.create_till_session(
        till_session_payload(
            ctx["journal"]["id"],
            ctx["cashier"]["id"],
            ctx["safe"]["id"],
            **SESSION_C_PAYLOAD_KWARGS,
        ),
        manager_headers,
    )
    validate_error(refused, ApiErrorId.ERR_CASHIER_RESTRICTED.value)

    acknowledged = acknowledge_coaching(
        ctx["cashier"]["id"],
        note="Coaching conversation held 2026-08-03",
        headers=manager_headers,
    )
    assert acknowledged["coaching_state"] == "COACHING_ACKNOWLEDGED", (
        f"expected COACHING_ACKNOWLEDGED, got {acknowledged['coaching_state']}"
    )
    assert acknowledged["till_eligibility"] == "RESTRICTED", (
        "acknowledging coaching leaves till_eligibility exactly as it was: "
        f"expected RESTRICTED, got {acknowledged['till_eligibility']}"
    )
    reread = read_cashier(ctx["cashier"]["id"])
    assert reread["coaching_state"] == "COACHING_ACKNOWLEDGED", (
        f"expected COACHING_ACKNOWLEDGED, got {reread['coaching_state']}"
    )
    assert reread["till_eligibility"] == "RESTRICTED", (
        f"expected RESTRICTED, got {reread['till_eligibility']}"
    )


def test_acknowledged_restricted_cashier_takes_the_till_on_retry(api, manager_headers):
    """PRD §3.2: "A `RESTRICTED` cashier becomes assignable again *only* through this acknowledgement — there is no override field on the assignment request that can substitute for it."

    PRD §3.2: "It writes one safe ledger row of kind `STARTING_BANK_ISSUE` against the supplied `safe_id`, linked to the new session, with `declared_amount_cents` equal to `starting_bank_cents`; the safe's `balance_cents` is recomputed (falling by the starting bank) and the safe's `version` increments by 1." "The journal's `session_count` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/till_assignment_gated_by_cashier_eligibility_and_coaching_dimensions
    """
    ctx = _setup_restricted_and_coaching_due_cashier()
    payload = till_session_payload(
        ctx["journal"]["id"],
        ctx["cashier"]["id"],
        ctx["safe"]["id"],
        **SESSION_C_PAYLOAD_KWARGS,
    )
    validate_error(
        api.create_till_session(payload, manager_headers),
        ApiErrorId.ERR_CASHIER_RESTRICTED.value,
    )

    acknowledge_coaching(
        ctx["cashier"]["id"],
        note="Coaching conversation held 2026-08-03",
        headers=manager_headers,
    )

    session_c = validate_success(api.create_till_session(payload, manager_headers), 201)
    assert session_c["status"] == "ACTIVE", (
        f"expected ACTIVE, got {session_c['status']}"
    )
    assert session_c["register_number"] == 3, (
        f"expected 3, got {session_c['register_number']}"
    )
    assert session_c["starting_bank_cents"] == 20000, (
        f"expected 20000, got {session_c['starting_bank_cents']}"
    )

    journal = read_journal(ctx["journal"]["id"])
    assert journal["session_count"] == 3, (
        f"expected 3, got {journal['session_count']}"
    )
    safe = read_safe(ctx["safe"]["id"])
    assert safe["balance_cents"] == 690000, (
        f"expected 690000, got {safe['balance_cents']}"
    )


def _setup_in_transit_deposit_with_two_credit_records():
    """A 200500 armored bag IN_TRANSIT, plus a PROVISIONAL and a FINAL row of 199195.

    The bag is priced at a carrier_fee_cents of 1305 and an expected_credit_cents
    of 199195, so both posted rows carry exactly the right amount.
    """
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(
        store_code="S-1014",
        name="Store 1014",
        region_code="EAST",
        safe_time_delay_minutes=5,
        safe_open_window_minutes=10,
        dual_control_required=True,
    )
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    arm_open_request(safe["id"], CLERK_1, reason="Prepare armored deposit")
    set_clock("2026-08-03T09:05:00Z")
    open_safe(safe["id"], CLERK_2)

    deposit = prepare_and_seal_deposit(
        safe["id"],
        journal["id"],
        lines((2000, 100), (100, 5)),
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
        sealer_user_id=CLERK_2,
        seal_number="SEAL-A-014",
    )
    schedule_pickup(
        deposit["id"],
        "2026-08-03T14:00:00Z",
        "2026-08-03T14:30:00Z",
        carrier_reference="CR-014",
        user_id=CLERK_1,
    )
    set_clock("2026-08-03T14:05:00Z")
    deposit = pickup_deposit(
        deposit["id"],
        "2026-08-03T14:05:00Z",
        carrier_signature="SIG-CARRIER-9",
        user_id=CARRIER_2,
    )

    set_clock("2026-08-05T09:00:00Z")
    provisional = post_bank_credit_record(
        store["id"],
        199195,
        credit_type="PROVISIONAL",
        value_date="2026-08-04",
        bank_reference="BR-PROV-014",
    )
    final = post_bank_credit_record(
        store["id"],
        199195,
        credit_type="FINAL",
        value_date="2026-08-05",
        bank_reference="BR-FINAL-014",
    )
    return {
        "store": store,
        "safe": safe,
        "journal": journal,
        "deposit": deposit,
        "provisional": provisional,
        "final": final,
    }


def test_reconcile_bank_refuses_a_provisional_record_of_the_right_amount(
    api, treasury_headers
):
    """PRD §3.7: "A record whose `credit_type` is `PROVISIONAL`, or one belonging to another store, is refused with `ERR_CREDIT_TYPE_INVALID`; a record whose `match_state` is already `MATCHED` is refused with `ERR_BANK_CREDIT_ALREADY_MATCHED`; an unknown identifier is refused with `ERR_BANK_CREDIT_RECORD_NOT_FOUND`."

    PRD §3.7: "A record's `match_state` is `UNMATCHED` at creation **even when `deposit_id` is supplied at creation** — supplying the link is a hint, not a match, and the record only becomes `MATCHED` when a bank reconciliation consumes it."

    Design: Difficulty/cross_entity_state_dependency/bank_reconciliation_rejects_provisional_credit_record
    """
    ctx = _setup_in_transit_deposit_with_two_credit_records()
    assert ctx["deposit"]["expected_credit_cents"] == 199195, (
        f"expected 199195, got {ctx['deposit']['expected_credit_cents']}"
    )

    refused = api.reconcile_bank(
        ctx["deposit"]["id"],
        {"bank_credit_record_ids": [ctx["provisional"]["id"]]},
        treasury_headers,
    )
    validate_error(refused, ApiErrorId.ERR_CREDIT_TYPE_INVALID.value)

    deposit = read_deposit(ctx["deposit"]["id"])
    assert deposit["status"] == "IN_TRANSIT", (
        f"expected IN_TRANSIT, got {deposit['status']}"
    )
    assert deposit["credited_total_cents"] == 0, (
        f"expected 0, got {deposit['credited_total_cents']}"
    )
    record = validate_success(
        api.get_bank_credit_record(ctx["provisional"]["id"], treasury_headers)
    )
    assert record["match_state"] == "UNMATCHED", (
        f"expected UNMATCHED, got {record['match_state']}"
    )


def test_reconcile_bank_accepts_a_final_record_of_the_identical_amount(
    api, treasury_headers
):
    """PRD §3.7: "When `credit_variance_cents` computes to zero, the deposit moves from `IN_TRANSIT` to `RECONCILED`: `credited_total_cents` and a zero `credit_variance_cents` are stored, the deposit leaves the provisional pool so the safe's `provisional_credit_balance_cents` is recomputed, the journal's compound derivation is re-evaluated, and **no** variance case is opened."

    PRD §3.7: "Each supplied record then has its `match_state` set to `MATCHED` and its `deposit_id` set to this deposit."

    Design: Difficulty/cross_entity_state_dependency/bank_reconciliation_rejects_provisional_credit_record
    """
    ctx = _setup_in_transit_deposit_with_two_credit_records()
    validate_error(
        api.reconcile_bank(
            ctx["deposit"]["id"],
            {"bank_credit_record_ids": [ctx["provisional"]["id"]]},
            treasury_headers,
        ),
        ApiErrorId.ERR_CREDIT_TYPE_INVALID.value,
    )

    reconciled = validate_success(
        api.reconcile_bank(
            ctx["deposit"]["id"],
            {"bank_credit_record_ids": [ctx["final"]["id"]]},
            treasury_headers,
        )
    )
    assert reconciled["credited_total_cents"] == 199195, (
        f"expected 199195, got {reconciled['credited_total_cents']}"
    )
    assert reconciled["credit_variance_cents"] == 0, (
        f"expected 0, got {reconciled['credit_variance_cents']}"
    )
    assert reconciled["status"] == "RECONCILED", (
        f"expected RECONCILED, got {reconciled['status']}"
    )

    record = validate_success(
        api.get_bank_credit_record(ctx["final"]["id"], treasury_headers)
    )
    assert record["match_state"] == "MATCHED", (
        f"expected MATCHED, got {record['match_state']}"
    )
    assert record["deposit_id"] == ctx["deposit"]["id"], (
        f"expected {ctx['deposit']['id']}, got {record['deposit_id']}"
    )

    safe = read_safe(ctx["safe"]["id"])
    assert safe["provisional_credit_balance_cents"] == 0, (
        f"expected 0, got {safe['provisional_credit_balance_cents']}"
    )
