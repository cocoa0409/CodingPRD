"""Order lifecycle: structural trade reference, from-state legality, flight
window at activation, and the depth-3 cancel cascade (PRD §2.9, §3.3, §3.4)."""
from test_helpers import (
    BA,
    TD,
    ApiErrorId,
    advance_order,
    book_spot_ok,
    create_active_order,
    create_locked_log,
    create_order,
    create_order_payload,
    create_station,
    create_trade_agreement,
    get_success_data,
    make_billing_admin_headers,
    make_headers,
    make_sales_rep_headers,
    set_clock,
    setup_bookable_station,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_trade_order_requires_agreement_reference(api):
    """PRD §3.4: "A TRADE order must reference a `trade_agreement_id`; a CASH
    order must not carry one — violations are rejected with
    `ERR_TRADE_AGREEMENT_REQUIRED`."

    Design: Corner/validations/trade_order_requires_agreement_reference
    """
    station = create_station()
    payload = create_order_payload(station["id"], order_kind="TRADE")
    assert "trade_agreement_id" not in payload
    resp = api.create_order(payload, make_sales_rep_headers("rep-1"))
    validate_error(resp, ApiErrorId.ERR_TRADE_AGREEMENT_REQUIRED)


def test_order_approve_from_draft_returns_invalid_state(api):
    """PRD §3.4: "Approval (`SUBMITTED → APPROVED`) requires a `SalesManager`
    whose `X-User-ID` differs from `created_by_user_id`" — approve is declared
    only from SUBMITTED. PRD §2.8: "then generic from-state legality
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/order_approve_from_draft_returns_invalid_state
    """
    station = create_station()
    order = create_order(station["id"], rep_user_id="rep-1")
    assert order["status"] == "DRAFT"

    resp = api.approve_order(order["id"], make_headers("SalesManager", "mgr-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_success_data(api.get_order(order["id"], make_sales_rep_headers("rep-1")))
    assert after["status"] == "DRAFT"
    assert after["version"] == order["version"], "no version bump on a rejected transition"


def test_order_activate_outside_flight_rejected(api):
    """PRD §3.4: "Activation (`APPROVED → ACTIVE`) requires the logical clock's
    current date to fall inside the flight window — `flight_start` on or before
    today, and today on or before `flight_end` — else
    `ERR_FLIGHT_WINDOW_INVALID`."

    Design: Corner/validations/order_activate_outside_flight_rejected
    """
    station = create_station()
    order = create_order(
        station["id"], rep_user_id="rep-1",
        flight_start="2026-05-01", flight_end="2026-05-31",
    )
    advance_order(order["id"], "APPROVED", rep_user_id="rep-1", mgr_user_id="mgr-1")
    set_clock("2026-06-15T00:00:00Z")

    resp = api.activate_order(order["id"], make_headers("SalesManager", "mgr-1"))
    validate_error(resp, ApiErrorId.ERR_FLIGHT_WINDOW_INVALID)

    after = get_success_data(api.get_order(order["id"], make_sales_rep_headers("rep-1")))
    assert after["status"] == "APPROVED", "Order stays APPROVED"


# ---------------------------------------------------------------------------
# Depth-3 cascade: order cancel -> spots -> ledger REVERSALs -> agreement
# ---------------------------------------------------------------------------

def _setup_exhausted_trade_order():
    """TRADE order with two booked spots whose DEBITs exactly consume the
    agreement (limit 12000, ratio 1.0) -> agreement EXHAUSTED."""
    env = setup_bookable_station(
        weekday="TUE", daypart="MIDDAY", hour=10, base_rate_cents=6000, min_rate_cents=1000
    )
    agreement = create_trade_agreement(
        env["station"]["id"], credit_limit_cents=12000, trade_ratio=1.0
    )
    order = create_active_order(
        env["station"]["id"], rep_user_id="rep-1",
        order_kind="TRADE", trade_agreement_id=agreement["id"],
        daypart_targets=[{"daypart": "MIDDAY", "units": 2}],
    )
    log = create_locked_log(env["station"]["id"], log_date="2026-05-05")
    s1 = book_spot_ok(order["id"], log["id"], daypart="MIDDAY", hour=10,
                      headers=make_sales_rep_headers("rep-1"))
    s2 = book_spot_ok(order["id"], log["id"], daypart="MIDDAY", hour=10,
                      headers=make_sales_rep_headers("rep-1"))
    env.update({"agreement": agreement, "order": order, "log": log, "spots": (s1, s2)})
    return env


def test_order_cancel_cascade_spots_cancelled(api):
    """PRD §2.9: "Cancelling an Order cascades its `SCHEDULED` and
    `MAKE_GOOD_PENDING` spots to `CANCELLED`". PRD §3.3: "when recomputation
    makes `available_cents` exactly zero on an `ACTIVE` agreement, the
    agreement flips to `EXHAUSTED`".

    Design: Difficulty/transitive_cascade/order_cancel_cascade_spots_ledger_agreement
    """
    env = _setup_exhausted_trade_order()
    agreement = get_success_data(api.get_trade_agreement(env["agreement"]["id"], BA))
    assert agreement["status"] == "EXHAUSTED", (
        "two DEBITs of 6000 exactly consumed the 12000 limit"
    )

    cancelled = get_success_data(
        api.cancel_order(env["order"]["id"], make_sales_rep_headers("rep-1"))
    )
    assert cancelled["status"] == "CANCELLED"

    for spot in env["spots"]:
        after = get_success_data(api.get_spot(spot["id"], TD))
        assert after["status"] == "CANCELLED", "hop 1: SCHEDULED spots cancelled"


def test_order_cancel_cascade_reversals_revive_agreement(api):
    """PRD §2.9: "for each cancelled TRADE spot appends a REVERSAL ledger entry
    equal to that spot's original DEBIT — which in turn recomputes the
    TradeAgreement's available credit and may flip an `EXHAUSTED` agreement
    back to `ACTIVE`."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_spots_ledger_agreement
    """
    env = _setup_exhausted_trade_order()
    get_success_data(api.cancel_order(env["order"]["id"], make_sales_rep_headers("rep-1")))

    entries, _meta = validate_paginated(
        api.list_agreement_ledger_entries(env["agreement"]["id"], BA)
    )
    assert [e["entry_kind"] for e in entries] == ["DEBIT", "DEBIT", "REVERSAL", "REVERSAL"]
    assert entries[2]["amount_cents"] == 6000 and entries[3]["amount_cents"] == 6000, (
        "hop 2: one REVERSAL per cancelled trade spot, equal to its original DEBIT"
    )

    agreement = get_success_data(api.get_trade_agreement(env["agreement"]["id"], BA))
    assert agreement["status"] == "ACTIVE", (
        "hop 3: EXHAUSTED -> ACTIVE auto-transition when credit is freed"
    )
    assert agreement["available_cents"] == 12000
    assert agreement["consumed_cents"] == 0
