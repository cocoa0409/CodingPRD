"""Trade ledger: signed adjustments, the exact-zero boundary, EXHAUSTED
auto-transitions, and DEBIT/REVERSAL conservation (PRD §3.3, §3.7)."""
from test_helpers import (
    BA,
    ApiErrorId,
    append_adjustment,
    book_spot_ok,
    create_active_order,
    create_locked_log,
    create_station,
    create_trade_agreement,
    get_success_data,
    import_as_run_ok,
    make_sales_rep_headers,
    setup_bookable_station,
    validate_error,
    validate_paginated,
)


def test_trade_adjustment_to_exact_zero_allowed(api):
    """PRD §3.3: "A hard invariant guards every write: `available_cents` may
    never go negative." and "when recomputation makes `available_cents` exactly
    zero on an `ACTIVE` agreement, the agreement flips to `EXHAUSTED`".

    Design: Difficulty/boundary_precision_check/trade_adjustment_to_exact_zero_allowed_then_exhausted
    """
    station = create_station()
    agreement = create_trade_agreement(
        station["id"], credit_limit_cents=50000, trade_ratio=1.0
    )
    entry = append_adjustment(agreement["id"], -50000, note="exact drain")
    assert entry["entry_kind"] == "ADJUSTMENT"

    after = get_success_data(api.get_trade_agreement(agreement["id"], BA))
    assert after["available_cents"] == 0, "available == 0 exactly is allowed"
    assert after["status"] == "EXHAUSTED", "auto-transition at exact zero"


def test_trade_adjustment_below_zero_rejected(api):
    """PRD §3.3: "Any write that would drive it below zero — a projected DEBIT
    at booking, a negative manual ADJUSTMENT, or an affidavit repricing delta —
    is rejected with `ERR_TRADE_CREDIT_EXCEEDED` (HTTP 402)."

    Design: Difficulty/boundary_precision_check/trade_adjustment_to_exact_zero_allowed_then_exhausted
    """
    station = create_station()
    agreement = create_trade_agreement(station["id"], credit_limit_cents=50000)
    append_adjustment(agreement["id"], -50000, note="exact drain")

    resp = api.append_ledger_entry(
        agreement["id"],
        {"entry_kind": "ADJUSTMENT", "amount_cents": -1, "note": "overdraft"},
        BA,
    )
    validate_error(resp, ApiErrorId.ERR_TRADE_CREDIT_EXCEEDED)
    assert resp.status_code == 402

    after = get_success_data(api.get_trade_agreement(agreement["id"], BA))
    assert after["available_cents"] == 0, "rejected adjustment leaves the balance at 0"


def test_trade_positive_adjustment_restores_available(api):
    """PRD §3.3: "an `entry_kind` (one of `DEBIT`, `REVERSAL`, `ADJUSTMENT`),
    `amount_cents` (positive for DEBIT and REVERSAL; signed for ADJUSTMENT,
    where a positive amount restores credit and a negative amount consumes
    it)" and "`available_cents` is `credit_limit_cents` minus `consumed_cents`
    plus `adjustments_cents`."

    Design: Corner/calculations/trade_positive_adjustment_restores_available
    """
    station = create_station()
    agreement = create_trade_agreement(
        station["id"], credit_limit_cents=10000, trade_ratio=1.0
    )
    append_adjustment(agreement["id"], 3000, note="bonus credit")

    after = get_success_data(api.get_trade_agreement(agreement["id"], BA))
    assert after["available_cents"] == 13000
    assert after["adjustments_cents"] == 3000
    assert after["status"] == "ACTIVE", "EXHAUSTED only flips at exactly 0"


# ---------------------------------------------------------------------------
# DEBIT + compensating REVERSAL conserve available credit
# ---------------------------------------------------------------------------

def _setup_missed_trade_spot():
    """TRADE order (1 unit), agreement limit 100000 ratio 1.0, one spot booked
    at 7000 then missed by an empty as-run import."""
    env = setup_bookable_station(
        weekday="TUE", daypart="MIDDAY", hour=10, base_rate_cents=7000, min_rate_cents=1000
    )
    agreement = create_trade_agreement(
        env["station"]["id"], credit_limit_cents=100000, trade_ratio=1.0
    )
    order = create_active_order(
        env["station"]["id"], rep_user_id="rep-1",
        order_kind="TRADE", trade_agreement_id=agreement["id"],
        daypart_targets=[{"daypart": "MIDDAY", "units": 1}],
    )
    log = create_locked_log(env["station"]["id"], log_date="2026-05-05")
    spot = book_spot_ok(
        order["id"], log["id"], daypart="MIDDAY", hour=10,
        headers=make_sales_rep_headers("rep-1"),
    )
    env.update({"agreement": agreement, "order": order, "log": log, "spot": spot})
    return env


def test_trade_debit_at_booking_draws_down_available(api):
    """PRD §3.3: "The agreement's computed fields are rebuilt by replaying its
    ledger in `entry_seq` order: `consumed_cents` is the sum of DEBIT amounts
    minus the sum of REVERSAL amounts; `adjustments_cents` is the signed sum of
    ADJUSTMENT amounts; `available_cents` is `credit_limit_cents` minus
    `consumed_cents` plus `adjustments_cents`." A 7000-cent DEBIT at booking
    moves available from 100000 to 93000.

    Design: Difficulty/compensating_invariant/trade_debit_reversal_conserves_available_credit
    """
    env = _setup_missed_trade_spot()
    assert env["spot"]["unit_rate_cents"] == 7000
    agreement = get_success_data(api.get_trade_agreement(env["agreement"]["id"], BA))
    assert agreement["available_cents"] == 93000, "DEBIT 7000 appended at booking"
    assert agreement["consumed_cents"] == 7000


def test_trade_reversal_on_miss_restores_available(api):
    """PRD §3.7: "Each TRADE spot transitioning to `MAKE_GOOD_PENDING` appends
    a REVERSAL ledger entry equal to its original DEBIT (possibly reviving an
    `EXHAUSTED` agreement)."

    Design: Difficulty/compensating_invariant/trade_debit_reversal_conserves_available_credit
    """
    env = _setup_missed_trade_spot()
    import_as_run_ok(env["log"]["id"])

    spot = get_success_data(api.get_spot(env["spot"]["id"], BA))
    assert spot["status"] == "MAKE_GOOD_PENDING"
    assert spot["make_good_reason"] == "MISSED", "obligation survives the credit reversal"

    entries, _meta = validate_paginated(
        api.list_agreement_ledger_entries(env["agreement"]["id"], BA)
    )
    assert [e["entry_kind"] for e in entries] == ["DEBIT", "REVERSAL"]
    assert entries[0]["amount_cents"] == 7000 and entries[1]["amount_cents"] == 7000, (
        "the ledger retains both entries (audit trail, no deletion)"
    )

    agreement = get_success_data(api.get_trade_agreement(env["agreement"]["id"], BA))
    assert agreement["available_cents"] == 100000, (
        "DEBIT + REVERSAL conserve the balance at exactly the pre-booking value"
    )
    assert agreement["consumed_cents"] == 0
