"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test starts against an empty database. Setup calls
go through get_success_data() so a broken precondition reads as a setup failure
rather than a confusing assertion failure.

Clock discipline: the logical clock reads exactly 2026-08-01T00:00:00Z at
startup and may only move forward, so helpers accept explicit ISO instants and
never move the clock backwards.
"""

from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    CARRIER_1,
    CLERK_1,
    CLERK_2,
    CLERK_3,
    LP_1,
    MANAGER_1,
    TEST_USERS,
    make_cashier_headers,
    make_carrier_headers,
    make_clerk_headers,
    make_investigator_headers,
    make_manager_headers,
)

TREASURY = TEST_USERS["treasury_headers"]
CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]
CARRIER = TEST_USERS["carrier_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


# --------------------------------------------------------------------- clock


def iso(instant: datetime) -> str:
    """Render a datetime as the ISO 8601 UTC form the API uses."""
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_instant(text: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and fractions."""
    cleaned = text.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned).astimezone(timezone.utc)


def shift_instant(text: str, **delta) -> str:
    """Return an instant offset from `text` by the given timedelta keywords."""
    return iso(parse_instant(text) + timedelta(**delta))


def set_clock(current_utc: str, headers=None) -> dict:
    """Advance the logical clock to `current_utc`. Any role may do this."""
    return get_success_data(
        api_client.set_clock(current_utc, headers or TREASURY)
    )


# ------------------------------------------------------------ tier 1 records


def create_store(**overrides) -> dict:
    """Register a store with its cash-office policy parameters."""
    return get_success_data(
        api_client.create_store(f.store_payload(**overrides), TREASURY)
    )


def create_safe(store_id: str, **overrides) -> dict:
    """Commission a safe at a store and seed its opening balance."""
    return get_success_data(
        api_client.create_safe(f.safe_payload(store_id, **overrides), TREASURY)
    )


def create_cashier(store_id: str, **overrides) -> dict:
    """Enroll a cashier at a store."""
    return get_success_data(
        api_client.create_cashier(f.cashier_payload(store_id, **overrides), MANAGER)
    )


def create_sales_journal(store_id: str, business_date=None) -> dict:
    """Open the daily sales journal for a store and business date."""
    payload = f.sales_journal_payload(store_id)
    if business_date is not None:
        payload["business_date"] = business_date
    return get_success_data(api_client.create_sales_journal(payload, CLERK))


def read_safe(safe_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_safe(safe_id, headers or CLERK))


def read_cashier(cashier_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_cashier(cashier_id, headers or MANAGER))


def read_journal(journal_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_sales_journal(journal_id, headers or CLERK))


def read_session(session_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_till_session(session_id, headers or CLERK))


def read_deposit(deposit_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_deposit(deposit_id, headers or CLERK))


def read_case(case_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_variance_case(case_id, headers or CLERK))


def read_change_order(order_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_change_order(order_id, headers or CLERK))


def list_ledger(safe_id: str, headers=None, **params) -> list:
    """List a safe's ledger rows in created_at ascending order."""
    query = {"safe_id": safe_id, "limit": 100}
    query.update(params)
    body = get_success_data(
        api_client.list_safe_transactions(headers or CLERK, params=query)
    )
    return body if isinstance(body, list) else body.get("data", [])


def list_cases(headers=None, **params) -> list:
    query = {"limit": 100}
    query.update(params)
    body = get_success_data(api_client.list_variance_cases(headers or CLERK, params=query))
    return body if isinstance(body, list) else body.get("data", [])


# ---------------------------------------------------- tier 1 safe open cycle


def arm_open_request(safe_id: str, requester_user_id=CLERK_1, reason="Cash room visit"):
    """File an open request, arming the time-delay device on a conventional safe."""
    return get_success_data(
        api_client.create_open_request(
            safe_id, {"reason": reason}, make_clerk_headers(requester_user_id)
        )
    )


def open_safe(safe_id: str, opener_user_id=CLERK_2) -> dict:
    """Open the safe; the opener must differ from the requester under dual control."""
    return get_success_data(
        api_client.open_safe(safe_id, make_clerk_headers(opener_user_id))
    )


def unlock_safe(
    safe_id: str,
    armed_at: str,
    delay_minutes: int = 5,
    requester_user_id=CLERK_1,
    opener_user_id=CLERK_2,
) -> dict:
    """Arm at `armed_at`, advance the clock by the store's delay, then open.

    The open is permitted once the clock has reached open_requested_at plus
    safe_time_delay_minutes, the boundary instant itself being permitted.
    """
    set_clock(armed_at)
    arm_open_request(safe_id, requester_user_id)
    set_clock(shift_instant(armed_at, minutes=delay_minutes))
    return open_safe(safe_id, opener_user_id)


# ------------------------------------------------------- tier 2 cash office


def setup_store_with_safe(
    opening_balance_cents=500000, safe_type="MANUAL", store_overrides=None, **safe_kwargs
):
    """Register a store and commission one safe. Returns (store, safe)."""
    store = create_store(**(store_overrides or {}))
    safe = create_safe(
        store["id"],
        safe_type=safe_type,
        opening_balance_cents=opening_balance_cents,
        **safe_kwargs,
    )
    return store, safe


def setup_cash_office(
    clock="2026-08-03T09:00:00Z",
    opening_balance_cents=500000,
    safe_type="MANUAL",
    business_date="2026-08-03",
    store_overrides=None,
    with_cashier=True,
):
    """Store + safe + journal (+ cashier), the preamble every workflow shares.

    Returns a dict with keys store, safe, journal and cashier.
    """
    set_clock(clock)
    store = create_store(**(store_overrides or {}))
    safe = create_safe(
        store["id"], safe_type=safe_type, opening_balance_cents=opening_balance_cents
    )
    journal = create_sales_journal(store["id"], business_date)
    cashier = create_cashier(store["id"]) if with_cashier else None
    return {"store": store, "safe": safe, "journal": journal, "cashier": cashier}


def setup_unlocked_cash_office(
    clock="2026-08-03T09:00:00Z",
    delay_minutes=5,
    opening_balance_cents=500000,
    business_date="2026-08-03",
    store_overrides=None,
    with_cashier=True,
):
    """Store + MANUAL safe + journal (+ cashier) with the safe already UNLOCKED.

    Returns the setup_cash_office dict plus the instant the safe was opened at.
    """
    overrides = dict(store_overrides or {})
    overrides.setdefault("safe_time_delay_minutes", delay_minutes)
    overrides.setdefault("safe_open_window_minutes", 10)
    overrides.setdefault("dual_control_required", True)
    ctx = setup_cash_office(
        clock=clock,
        opening_balance_cents=opening_balance_cents,
        business_date=business_date,
        store_overrides=overrides,
        with_cashier=with_cashier,
    )
    ctx["safe"] = unlock_safe(
        ctx["safe"]["id"], clock, delay_minutes=ctx["store"]["safe_time_delay_minutes"]
    )
    ctx["unlocked_at"] = shift_instant(
        clock, minutes=ctx["store"]["safe_time_delay_minutes"]
    )
    return ctx


# --------------------------------------------- tier 3 till session lifecycle


def assign_till(
    journal_id: str,
    cashier_id: str,
    safe_id: str,
    register_number=1,
    shift_start_at="2026-08-03T09:00:00Z",
    shift_end_at="2026-08-03T17:00:00Z",
    starting_bank_cents=20000,
    headers=None,
    **overrides,
) -> dict:
    """Assign a register till and issue the starting bank out of the safe."""
    payload = f.till_session_payload(
        journal_id,
        cashier_id,
        safe_id,
        register_number=register_number,
        shift_start_at=shift_start_at,
        shift_end_at=shift_end_at,
        starting_bank_cents=starting_bank_cents,
        **overrides,
    )
    return get_success_data(
        api_client.create_till_session(payload, headers or MANAGER)
    )


def record_drop(
    session_id: str,
    cashier_id: str,
    declared_amount_cents: int,
    txn_type="CLOSING_DROP",
    memo=None,
) -> dict:
    """Record a mid-shift or closing drop; the acting user is the session's cashier."""
    payload = {"txn_type": txn_type, "declared_amount_cents": declared_amount_cents}
    if memo is not None:
        payload["memo"] = memo
    return get_success_data(
        api_client.create_drop(session_id, payload, make_cashier_headers(cashier_id))
    )


def close_till(
    session_id: str,
    cashier_id=None,
    pos_cash_sales_cents=0,
    pos_card_sales_cents=0,
    pos_paid_out_cents=None,
    headers=None,
    **overrides,
) -> dict:
    """Close the register at shift end and freeze the POS tender totals."""
    payload = {
        "pos_cash_sales_cents": pos_cash_sales_cents,
        "pos_card_sales_cents": pos_card_sales_cents,
    }
    if pos_paid_out_cents is not None:
        payload["pos_paid_out_cents"] = pos_paid_out_cents
    payload.update(overrides)
    if headers is None:
        headers = make_cashier_headers(cashier_id) if cashier_id else MANAGER
    return get_success_data(api_client.close_till_session(session_id, payload, headers))


def blind_count(session_id: str, counted_lines, counter_user_id=CLERK_3) -> dict:
    """Record the cash office's blind count of the till."""
    return get_success_data(
        api_client.blind_count(
            session_id,
            {"counted_lines": list(counted_lines)},
            make_clerk_headers(counter_user_id),
        )
    )


def order_recount(session_id: str, reason="Count looks wrong", user_id=CLERK_3) -> dict:
    """Send a counted till back for a second blind count."""
    return get_success_data(
        api_client.recount(
            session_id, {"recount_reason": reason}, make_clerk_headers(user_id)
        )
    )


def reconcile_till(session_id: str, reconciler_user_id=CLERK_2) -> dict:
    """Reconcile the counted till; the reconciler must differ from the counter."""
    return get_success_data(
        api_client.reconcile_till_session(
            session_id, make_clerk_headers(reconciler_user_id)
        )
    )


def run_session_to_counted(
    journal_id: str,
    cashier_id: str,
    safe_id: str,
    starting_bank_cents=20000,
    drop_amount_cents=100000,
    pos_cash_sales_cents=100000,
    pos_card_sales_cents=40000,
    pos_paid_out_cents=None,
    counted_lines=None,
    counted_cash_cents=None,
    register_number=1,
    shift_start_at="2026-08-03T09:00:00Z",
    shift_end_at="2026-08-03T17:00:00Z",
    close_at=None,
    counter_user_id=CLERK_3,
):
    """Assign a till, drop, close and blind-count it. Returns the session.

    Either pass explicit `counted_lines` or a `counted_cash_cents` amount, which
    is expressed as one-cent lines only when it cannot be built from notes.
    """
    session = assign_till(
        journal_id,
        cashier_id,
        safe_id,
        register_number=register_number,
        shift_start_at=shift_start_at,
        shift_end_at=shift_end_at,
        starting_bank_cents=starting_bank_cents,
    )
    if drop_amount_cents:
        record_drop(session["id"], cashier_id, drop_amount_cents)
    if close_at is not None:
        set_clock(close_at)
    close_till(
        session["id"],
        cashier_id=cashier_id,
        pos_cash_sales_cents=pos_cash_sales_cents,
        pos_card_sales_cents=pos_card_sales_cents,
        pos_paid_out_cents=pos_paid_out_cents,
    )
    if counted_lines is None:
        counted_lines = lines_for_amount(counted_cash_cents or 0)
    blind_count(session["id"], counted_lines, counter_user_id)
    return read_session(session["id"])


def lines_for_amount(amount_cents: int) -> list:
    """Build denomination lines worth exactly `amount_cents` from permitted
    denominations, largest first."""
    remaining = int(amount_cents)
    built = []
    for denom in (2000, 1000, 500, 100, 25, 10, 5, 1):
        qty, remaining = divmod(remaining, denom)
        if qty:
            built.append({"denomination_cents": denom, "quantity": qty})
    assert remaining == 0, f"cannot build {amount_cents} from permitted denominations"
    return built


# ------------------------------------------------- tier 3 deposit lifecycle


def prepare_deposit(
    safe_id: str,
    journal_id: str,
    counted_lines,
    business_date="2026-08-03",
    preparer_user_id=CLERK_1,
    expected_safe_version=None,
    **overrides,
) -> dict:
    """Prepare an armored deposit out of the open safe, reading the safe's
    current version for expected_safe_version unless one is supplied."""
    if expected_safe_version is None:
        expected_safe_version = read_safe(safe_id)["version"]
    payload = f.deposit_payload(
        safe_id,
        journal_id,
        counted_lines,
        expected_safe_version,
        business_date=business_date,
        **overrides,
    )
    return get_success_data(
        api_client.create_deposit(payload, make_clerk_headers(preparer_user_id))
    )


def seal_deposit(deposit_id: str, seal_number=None, sealer_user_id=CLERK_2) -> dict:
    """Seal the prepared bag under dual control; this relocks the parent safe."""
    payload = {"seal_number": seal_number or f.unique_seal_number()}
    return get_success_data(
        api_client.seal_deposit(deposit_id, payload, make_clerk_headers(sealer_user_id))
    )


def void_deposit(deposit_id: str, reason="Carrier route cancelled", user_id=MANAGER_1):
    """Void a deposit that has not left the store, returning the cash to the safe."""
    return get_success_data(
        api_client.void_deposit(
            deposit_id, {"void_reason": reason}, make_manager_headers(user_id)
        )
    )


def schedule_pickup(
    deposit_id: str,
    window_start: str,
    window_end: str,
    carrier_reference="CR-0001",
    user_id=CLERK_1,
) -> dict:
    """Book the sealed deposit onto an armored carrier pickup window."""
    payload = {
        "pickup_window_start": window_start,
        "pickup_window_end": window_end,
        "carrier_reference": carrier_reference,
    }
    return get_success_data(
        api_client.schedule_pickup(deposit_id, payload, make_clerk_headers(user_id))
    )


def pickup_deposit(
    deposit_id: str,
    picked_up_at: str,
    carrier_signature="J. CARRIER",
    user_id=CARRIER_1,
) -> dict:
    """Record the carrier signing for the bag, granting carrier provisional credit."""
    payload = {"picked_up_at": picked_up_at, "carrier_signature": carrier_signature}
    return get_success_data(
        api_client.pickup_deposit(deposit_id, payload, make_carrier_headers(user_id))
    )


def prepare_and_seal_deposit(
    safe_id: str,
    journal_id: str,
    counted_lines,
    business_date="2026-08-03",
    preparer_user_id=CLERK_1,
    sealer_user_id=CLERK_2,
    seal_number=None,
    **overrides,
):
    """Prepare then seal one armored bag. Returns the sealed deposit."""
    deposit = prepare_deposit(
        safe_id,
        journal_id,
        counted_lines,
        business_date=business_date,
        preparer_user_id=preparer_user_id,
        **overrides,
    )
    return seal_deposit(deposit["id"], seal_number, sealer_user_id)


def deposit_in_transit(
    safe_id: str,
    journal_id: str,
    counted_lines,
    window_start="2026-08-03T10:00:00Z",
    window_end="2026-08-03T10:30:00Z",
    picked_up_at="2026-08-03T10:15:00Z",
    business_date="2026-08-03",
    **overrides,
):
    """Prepare, seal, schedule and hand over one armored bag. Returns the deposit."""
    deposit = prepare_and_seal_deposit(
        safe_id, journal_id, counted_lines, business_date=business_date, **overrides
    )
    schedule_pickup(deposit["id"], window_start, window_end)
    return pickup_deposit(deposit["id"], picked_up_at)


def insert_smart_deposit(
    safe_id: str,
    journal_id: str,
    counted_lines,
    business_date="2026-08-03",
    suspect_note_cents=None,
    headers=None,
    **overrides,
) -> dict:
    """Insert a sealed bag through a smart safe's note validator."""
    payload = f.smart_deposit_payload(
        journal_id, counted_lines, business_date=business_date, **overrides
    )
    if suspect_note_cents is not None:
        payload["suspect_note_cents"] = suspect_note_cents
    return get_success_data(
        api_client.create_smart_deposit(safe_id, payload, headers or CLERK)
    )


# ------------------------------------------------ tier 3 bank and card tieout


def post_bank_credit_record(
    store_id: str,
    amount_cents: int,
    credit_type="FINAL",
    deposit_id=None,
    value_date="2026-08-03",
    bank_reference=None,
    headers=None,
) -> dict:
    """Post a credit line from the bank statement."""
    payload = f.bank_credit_record_payload(
        store_id,
        amount_cents,
        credit_type=credit_type,
        value_date=value_date,
    )
    if bank_reference is not None:
        payload["bank_reference"] = bank_reference
    if deposit_id is not None:
        payload["deposit_id"] = deposit_id
    return get_success_data(
        api_client.create_bank_credit_record(payload, headers or TREASURY)
    )


def reconcile_bank(deposit_id: str, record_ids, headers=None) -> dict:
    """Consume bank credit records against a deposit."""
    return get_success_data(
        api_client.reconcile_bank(
            deposit_id, {"bank_credit_record_ids": list(record_ids)}, headers or TREASURY
        )
    )


def post_card_settlement(
    journal_id: str,
    gross_card_sales_cents: int,
    txn_count: int,
    monthly_volume_cents: int,
    funded_amount_cents: int,
    card_network="VISA_MC",
    chargeback_cents=None,
    headers=None,
) -> dict:
    """Record an acquirer settlement advice for one network and day."""
    payload = f.card_settlement_payload(
        journal_id,
        gross_card_sales_cents,
        txn_count,
        monthly_volume_cents,
        funded_amount_cents,
        card_network=card_network,
    )
    if chargeback_cents is not None:
        payload["chargeback_cents"] = chargeback_cents
    return get_success_data(
        api_client.create_card_settlement(payload, headers or TREASURY)
    )


def post_tenders(journal_id: str, cash_cents: int, card_cents: int, headers=None) -> dict:
    """Post the store-level tender totals onto the journal."""
    return get_success_data(
        api_client.post_tenders(
            journal_id,
            f.post_tenders_payload(cash_cents, card_cents),
            headers or CLERK,
        )
    )


# ------------------------------------------- tier 4 variance-case accumulation


def reconcile_and_collect_cases(
    session_id: str, journal_id: str, reconciler_user_id=CLERK_2
):
    """Reconcile a counted session and return (session, cases_on_journal)."""
    session = reconcile_till(session_id, reconciler_user_id)
    cases = list_cases(sales_journal_id=journal_id)
    return session, cases


def setup_session_variance_case(
    variance_cents: int,
    clock="2026-08-03T09:00:00Z",
    store_overrides=None,
    starting_bank_cents=20000,
    drop_amount_cents=100000,
    pos_cash_sales_cents=100000,
    close_at="2026-08-03T13:00:00Z",
    opening_balance_cents=500000,
):
    """Drive one till session to a chosen variance and return the opened case.

    The variance is the counted cash minus the expected cash, so the blind count
    is built at expected + variance_cents.

    Returns a dict with keys store, safe, journal, cashier, session and case.
    """
    ctx = setup_unlocked_cash_office(
        clock=clock,
        opening_balance_cents=opening_balance_cents,
        store_overrides=store_overrides,
    )
    expected = starting_bank_cents + pos_cash_sales_cents - drop_amount_cents
    session = run_session_to_counted(
        ctx["journal"]["id"],
        ctx["cashier"]["id"],
        ctx["safe"]["id"],
        starting_bank_cents=starting_bank_cents,
        drop_amount_cents=drop_amount_cents,
        pos_cash_sales_cents=pos_cash_sales_cents,
        counted_cash_cents=expected + variance_cents,
        close_at=close_at,
    )
    session = reconcile_till(session["id"])
    cases = list_cases(sales_journal_id=ctx["journal"]["id"])
    ctx["session"] = session
    ctx["cases"] = cases
    ctx["case"] = cases[0] if cases else None
    ctx["expected_cash_cents"] = expected
    return ctx


def append_attribution(
    case_id: str,
    bucket: str,
    amount_cents: int,
    expected_variance_case_version: int,
    note="Research note",
    headers=None,
) -> dict:
    """Record where a slice of the variance was found."""
    payload = f.attribution_payload(
        bucket, amount_cents, expected_variance_case_version, note=note
    )
    return get_success_data(
        api_client.create_attribution(case_id, payload, headers or CLERK)
    )


def escalate_case(
    case_id: str, reason="Suspected theft", user_id=LP_1, as_manager=False
) -> dict:
    """Escalate a case as suspected theft, freezing the safes and barring the cashier."""
    headers = (
        make_manager_headers(user_id) if as_manager else make_investigator_headers(user_id)
    )
    return get_success_data(
        api_client.escalate_variance_case(
            case_id, {"escalation_reason": reason}, headers
        )
    )


def close_case(
    case_id: str, disposition: str, closing_note=None, user_id=LP_1
) -> dict:
    """Close an escalated case with a disposition."""
    payload = {"disposition": disposition}
    if closing_note is not None:
        payload["closing_note"] = closing_note
    return get_success_data(
        api_client.close_variance_case(
            case_id, payload, make_investigator_headers(user_id)
        )
    )


def restore_posture(safe_id: str, note=None, user_id=LP_1) -> dict:
    """Lift an investigation freeze on the store's safes."""
    payload = {}
    if note is not None:
        payload["investigation_note"] = note
    return get_success_data(
        api_client.restore_posture(safe_id, payload, make_investigator_headers(user_id))
    )


def acknowledge_coaching(cashier_id: str, note=None, headers=None) -> dict:
    """Record that the cashier has sat the coaching conversation."""
    payload = {}
    if note is not None:
        payload["acknowledgement_note"] = note
    return get_success_data(
        api_client.acknowledge_coaching(
            cashier_id, payload, headers or make_cashier_headers(cashier_id)
        )
    )


# --------------------------------------------------- tier 5 change orders


def create_change_order(store_id: str, headers=None, **overrides) -> dict:
    """File a change order, forecasting demand and planning the denomination mix."""
    return get_success_data(
        api_client.create_change_order(
            f.change_order_payload(store_id, **overrides), headers or CLERK
        )
    )


def approve_change_order(order_id: str, note=None, user_id=MANAGER_1) -> dict:
    payload = {}
    if note is not None:
        payload["approval_note"] = note
    return get_success_data(
        api_client.approve_change_order(order_id, payload, make_manager_headers(user_id))
    )


def reject_change_order(order_id: str, reason="Not needed", user_id=MANAGER_1) -> dict:
    return get_success_data(
        api_client.reject_change_order(
            order_id, {"rejection_reason": reason}, make_manager_headers(user_id)
        )
    )


def receive_change_order(order_id: str, received_amount_cents: int, headers=None) -> dict:
    return get_success_data(
        api_client.receive_change_order(
            order_id, {"received_amount_cents": received_amount_cents}, headers or CLERK
        )
    )


def create_approved_change_order(store_id: str, **overrides) -> dict:
    """File and approve one change order. Returns the APPROVED order."""
    order = create_change_order(store_id, **overrides)
    return approve_change_order(order["id"])
