"""Unwinding money: opening, approving, rejecting and settling refunds."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_refund_request,
    setup_onsale_event, setup_paid_order, setup_refund_request,
    setup_approved_refund, approve_refund, settle_refund, open_refund_request,
    create_buyer, set_clock, read_order, read_organizer, read_refund_request,
    read_ticket_type,
)

GATE = TEST_USERS["gate_staff_headers"]


def _pass_on_event_with_two_paid_orders():
    """One buyer, two byte-identical paid orders of two 5000-cent tickets each."""
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Summer Session", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z", "fee_mode": "PASS_ON",
                         "refund_policy": "FEE_RETAINED"})
    buyer = create_buyer(email="bea@example.com", display_name="Bea")
    ctx["paid_a"] = setup_paid_order(ctx, buyer=buyer, quantity=2)
    ctx["paid_b"] = setup_paid_order(ctx, buyer=buyer, quantity=2)
    return ctx


def test_fee_retained_refund_returns_face_only_and_the_platform_keeps_its_fee():
    """PRD §3.8: "Under `FEE_RETAINED`, `refund_amount_cents` is the refunded face
    minus the prorated discount, `platform_retained_cents` is the whole refunded fee,
    and `organizer_charged_cents` is the refunded face minus the prorated discount."

    Design: Difficulty/dual_variant_calc/refund_policy_fee_retained_vs_fee_included_on_order_money
    """
    ctx = _pass_on_event_with_two_paid_orders()
    request = setup_refund_request(ctx["paid_a"], quantity=2, policy="FEE_RETAINED",
                                   reason="cannot attend")

    approved = approve_refund(ctx, request["id"])

    assert_refund_request(approved)
    assert approved["status"] == "APPROVED"
    assert approved["refund_amount_cents"] == 10000, (
        "The refunded face is 5000 * 2 with no discount to prorate, got "
        f"{approved['refund_amount_cents']}")
    assert approved["platform_retained_cents"] == 728, \
        f"The whole refunded fee stays with the platform, got {approved['platform_retained_cents']}"
    assert approved["organizer_charged_cents"] == 10000


def test_fee_included_refund_hands_the_platform_fee_back_to_the_buyer():
    """PRD §3.8: "Under `FEE_INCLUDED`, `refund_amount_cents` is the refunded face
    minus the prorated discount plus the refunded fee, `platform_retained_cents` is 0,
    and `organizer_charged_cents` is the refunded face minus the prorated discount
    plus the refunded fee."
    PRD §3.8: "The practical difference under a pass-on event is that a
    `FEE_INCLUDED` refund returns strictly more to the buyer than a `FEE_RETAINED`
    refund would for identical inputs, because the platform hands its own fee back."

    Design: Difficulty/dual_variant_calc/refund_policy_fee_retained_vs_fee_included_on_order_money
    """
    ctx = _pass_on_event_with_two_paid_orders()
    retained_request = setup_refund_request(ctx["paid_a"], quantity=2,
                                            policy="FEE_RETAINED")
    included_request = setup_refund_request(ctx["paid_b"], quantity=2,
                                            policy="FEE_INCLUDED")

    retained = approve_refund(ctx, retained_request["id"])
    included = approve_refund(ctx, included_request["id"])

    assert included["refund_amount_cents"] == 10728, \
        f"Expected face 10000 plus the 728-cent fee, got {included['refund_amount_cents']}"
    assert included["platform_retained_cents"] == 0
    assert included["organizer_charged_cents"] == 10728
    assert included["refund_amount_cents"] - retained["refund_amount_cents"] == 728, (
        "The two variants differ by exactly the retained platform fee on identical "
        f"inputs, got {included['refund_amount_cents'] - retained['refund_amount_cents']}")


def test_organizer_lifetime_counters_cancel_out_after_a_full_refund():
    """PRD §3.1: "Two lifetime money counters are opened at zero on that record and
    never edited directly: `lifetime_gross_cents` accumulates the organiser-credited
    amount of every order that reaches paid status across every event the organiser
    owns, and `lifetime_refunds_cents` accumulates the organiser-charged amount of
    every refund that reaches settlement across the same events."
    PRD §3.8: "The same hop voids every admission named by `item_refunds`, releasing
    their seats by decrementing the relevant seat blocks' `seats_taken` and the
    relevant tiers' `sold_count`, and increases the organiser's
    `lifetime_refunds_cents` by the request's `organizer_charged_cents` while
    incrementing that organiser's `version` by 1."

    Design: Difficulty/compensating_invariant/organizer_net_receivable_conserved_across_pay_then_full_refund
    """
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Ledger Night", "starts_at": "2026-09-05T18:00:00Z",
                         "ends_at": "2026-09-05T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="uma@example.com",
                                                    display_name="Uma"), quantity=2)
    assert read_organizer(ctx["org_id"])["lifetime_gross_cents"] == 10000
    approved = setup_approved_refund(ctx, paid, quantity=2, policy="FEE_RETAINED")
    assert approved["refund_amount_cents"] == 10000
    assert approved["platform_retained_cents"] == 728

    settle_refund(approved["id"])

    organizer = read_organizer(ctx["org_id"])
    assert organizer["lifetime_gross_cents"] == 10000
    assert organizer["lifetime_refunds_cents"] == 10000
    assert organizer["lifetime_gross_cents"] - organizer["lifetime_refunds_cents"] == 0, (
        "The organiser's net receivable returns to zero once the charge cancels the "
        "credit")


def test_settled_refund_partially_refunds_the_order_and_frees_the_tier():
    """PRD §3.8: "The second hop, caused by the first, increases the order's
    `refunded_cents` by the request's `refund_amount_cents` and advances the order's
    payment dimension: when the accumulated `refunded_cents` now equals the order's
    `buyer_total_cents` the order becomes `REFUNDED`, and otherwise it becomes
    `PARTIALLY_REFUNDED`; an order that reaches `REFUNDED` from `PAID` additionally
    has its `fulfillment_status` set to `VOIDED`, and an order sitting in
    `REFUND_PENDING` likewise reaches `REFUNDED` only on the settlement that brings
    `refunded_cents` up to `buyer_total_cents` exactly."

    Design: Difficulty/compensating_invariant/organizer_net_receivable_conserved_across_pay_then_full_refund
    """
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Ledger Night", "starts_at": "2026-09-05T18:00:00Z",
                         "ends_at": "2026-09-05T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="uma2@example.com",
                                                    display_name="Uma Two"), quantity=2)
    approved = setup_approved_refund(ctx, paid, quantity=2, policy="FEE_RETAINED")

    settle_refund(approved["id"])

    order = read_order(paid["order_id"], paid["buyer"])
    assert order["refunded_cents"] == 10000
    assert order["payment_status"] == "PARTIALLY_REFUNDED", (
        "10000 refunded against a 10728-cent buyer total leaves the order partially "
        f"refunded, got {order['payment_status']}")
    assert read_ticket_type(ctx["tt_id"])["sold_count"] == 0, \
        "Voiding the refunded admissions releases the tier's inventory"


def test_rejecting_a_refund_zeroes_its_money_fields():
    """PRD §3.8: "It moves the request `REQUESTED → REJECTED`, accepts an optional
    `reason`, requires the request to be in `REQUESTED`, and sets
    `refund_amount_cents`, `platform_retained_cents` and `organizer_charged_cents` all
    to 0."

    Design: Corner/state_machines/corner_refund_reject_zeroes_money_fields
    """
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Reject Night", "starts_at": "2026-09-28T18:00:00Z",
                         "ends_at": "2026-09-28T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="hana@example.com",
                                                    display_name="Hana"), quantity=1)
    request = setup_refund_request(paid, quantity=1, policy="FEE_RETAINED",
                                   reason="changed mind")

    rejected = validate_success(api_client.reject_refund_request(
        request["id"], ctx["org_headers"], {"reason": "outside organizer policy"}), 200)

    assert rejected["status"] == "REJECTED"
    assert rejected["refund_amount_cents"] == 0
    assert rejected["platform_retained_cents"] == 0
    assert rejected["organizer_charged_cents"] == 0

    order = read_order(paid["order_id"], paid["buyer"])
    assert order["payment_status"] == "PAID", \
        f"A rejected refund leaves the payment untouched, got {order['payment_status']}"
    assert order["refunded_cents"] == 0


def test_refund_opened_after_the_show_has_started_is_rejected():
    """PRD §3.8: "The refund window must be open: the current time must be strictly
    before thirty days after the order's `paid_at`, **and** strictly before the
    event's `starts_at` — a refund cannot be opened once the show has begun, however
    recent the purchase. A failure of either condition is `ERR_REFUND_WINDOW_CLOSED`."

    Design: Corner/validations/corner_refund_after_event_start_returns_refund_window_closed
    """
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Late Night", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="tia@example.com",
                                                    display_name="Tia"), quantity=1)

    # Well inside the thirty-day post-payment window, but the show has begun.
    set_clock("2026-08-01T19:00:00Z")

    resp = open_refund_request(paid, quantity=1, policy="FEE_RETAINED",
                               reason="missed the show")
    validate_error(resp, ApiErrorId.ERR_REFUND_WINDOW_CLOSED.value, 409)

    rows, meta = validate_paginated(api_client.list_refund_requests(
        ctx["org_headers"], params={"order_id": paid["order_id"]}))
    assert meta["total_count"] == 0, \
        f"A refused request persists nothing, got total_count {meta['total_count']}"


def test_gate_staff_cannot_settle_a_refund():
    """PRD §2.1: "A `FinanceOfficer` settles refunds and administers payouts and the
    rolling reserve but cannot originate or approve a refund request on the
    organiser's behalf. `GateStaff` operates the door and nothing else."
    PRD §2.1: "Once authenticated, if the acting role is not among the roles the
    target endpoint permits, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/corner_gate_staff_cannot_settle_a_refund
    """
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Peer Night", "starts_at": "2026-10-20T18:00:00Z",
                         "ends_at": "2026-10-20T22:00:00Z"})
    paid = setup_paid_order(ctx, buyer=create_buyer(email="jax@example.com",
                                                    display_name="Jax"), quantity=1)
    approved = setup_approved_refund(ctx, paid, quantity=1, policy="FEE_RETAINED")

    resp = api_client.settle_refund_request(approved["id"], GATE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert read_refund_request(approved["id"])["status"] == "APPROVED"
    assert read_order(paid["order_id"], paid["buyer"])["refunded_cents"] == 0
