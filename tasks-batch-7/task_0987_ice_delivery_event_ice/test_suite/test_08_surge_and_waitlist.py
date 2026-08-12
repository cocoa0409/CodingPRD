"""Surge admission control, waitlist fork/promotion, and the cancel cascade
(PRD §3.5, §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    agent,
    api_client,
    confirm,
    full_book_payload,
    get_depot,
    get_order,
    make_active_book,
    make_customer,
    make_depot,
    make_surge_window,
    mini_book_payload,
    order_line,
    quoted_order,
    run_ops,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _setup(customer_name, depot_name, capacity=10, limit=500000, book="mini"):
    depot = make_depot(capacity, depot_name)
    set_logical_clock()
    make_active_book(mini_book_payload() if book == "mini" else full_book_payload())
    cust = make_customer(
        account_name=customer_name, kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=limit,
    )
    return depot, cust


def _waitlist_entry_id(order_id):
    """The order holds at most one QUEUED entry (PRD §3.5)."""
    entries, _meta = validate_paginated(
        api_client.list_order_waitlist_entries(order_id, ADMIN)
    )
    assert len(entries) == 1
    return entries[0]["id"], entries[0]["status"]


def test_surge_closed_rejects_confirm(api):
    """PRD §3.5: "A `CLOSED` policy rejects outright with
    `ERR_SURGE_ADMISSION_CLOSED`."

    Design: Corner/validations/surge_closed_rejects_confirm
    """
    depot, cust = _setup("V34", "Depot V34", limit=200000)
    make_surge_window(depot["id"], "2026-05-01", "2026-05-20", "CLOSED")
    order = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    resp = api.confirm_order(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_SURGE_ADMISSION_CLOSED)


def test_waitlist_expiry_sweep_cancels_order(api):
    """PRD §3.9: "Sixth, waitlist expiry: `QUEUED` entries whose order's
    `event_date` is on or before the current logical date become `EXPIRED`,
    cancelling the linked order and releasing any retained slot reservation."

    Design: Corner/state_machines/waitlist_expiry_sweep_cancels_order
    """
    depot, cust = _setup("S15", "Depot S15")
    make_surge_window(
        depot["id"], "2026-05-01", "2026-05-10", "RATIONED", daily_pallet_cap=1
    )
    order_a = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-05",
        window_start="10:00", window_end="12:00",
    )
    confirm(order_a["id"], cust["id"])

    order_b = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-05",
        window_start="14:00", window_end="16:00",
    )
    forked = validate_success(api.confirm_order(order_b["id"], agent(cust["id"])))
    assert forked["fulfillment_status"] == "WAITLISTED", (
        "committed 1 + 1 > cap 1: rationing forks to the waitlist"
    )
    entry_b, status = _waitlist_entry_id(order_b["id"])
    assert status == "QUEUED"

    set_logical_clock("2026-05-05T09:00:00Z")
    ops = run_ops(depot["id"])
    assert entry_b in ops["expired_entry_ids"], (
        "event_date 2026-05-05 is on the current logical date"
    )
    order_b_after = get_order(order_b["id"], ADMIN)
    assert order_b_after["fulfillment_status"] == "CANCELLED"


def test_promotion_tiebreak_earliest_queued_first(api):
    """PRD §3.6: "They rank by the owning customer's `tier`, `PRIORITY` before
    `STANDARD`; ties break by earliest `queued_at`, then earliest order
    `event_date`, then earliest order `created_at`; the entry `id` is never
    consulted."
    PRD §3.6: "Promotion walks that ranking greedily while headroom permits".

    Design: Corner/calculations/promotion_tiebreak_created_at
    """
    depot = make_depot(10, "Depot C30")
    set_logical_clock()
    make_active_book(mini_book_payload())
    make_surge_window(
        depot["id"], "2026-05-01", "2026-05-20", "RATIONED", daily_pallet_cap=1
    )
    cust_a = make_customer(account_name="C30 A", kind="EVENT_ORGANIZER",
                           tier="STANDARD", credit_terms="NET_30", credit_limit_cents=500000)
    cust_b = make_customer(account_name="C30 B", kind="EVENT_ORGANIZER",
                           tier="STANDARD", credit_terms="NET_30", credit_limit_cents=500000)
    cust_c = make_customer(account_name="C30 C", kind="EVENT_ORGANIZER",
                           tier="STANDARD", credit_terms="NET_30", credit_limit_cents=500000)

    order_a = quoted_order(
        cust_a["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    confirm(order_a["id"], cust_a["id"])

    order_b = quoted_order(
        cust_b["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="14:00", window_end="16:00",
    )
    forked_b = validate_success(api.confirm_order(order_b["id"], agent(cust_b["id"])))
    assert forked_b["fulfillment_status"] == "WAITLISTED"
    entry_b, _ = _waitlist_entry_id(order_b["id"])

    # Advance the clock so B's queueing instant is strictly earlier than C's:
    # the earliest-queued_at tie-break then decides the rank deterministically.
    set_logical_clock("2026-05-02T09:00:00Z")

    order_c = quoted_order(
        cust_c["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="17:00", window_end="19:00",
    )
    forked_c = validate_success(api.confirm_order(order_c["id"], agent(cust_c["id"])))
    assert forked_c["fulfillment_status"] == "WAITLISTED"
    entry_c, _ = _waitlist_entry_id(order_c["id"])

    validate_success(api.cancel_order(order_a["id"], agent(cust_a["id"])))
    ops = run_ops(depot["id"])
    assert ops["promoted_entry_ids"] == [entry_b], (
        "same tier, same event date: the earlier-queued entry wins the single "
        "pallet of headroom"
    )
    assert get_order(order_b["id"], ADMIN)["fulfillment_status"] == "CONFIRMED"
    assert get_order(order_c["id"], ADMIN)["fulfillment_status"] == "WAITLISTED"


# ----------------- difficulty: cancel -> release -> posture -> promotion --------

def test_cancel_confirmed_cascade_promotes_waitlisted_order(api):
    """PRD §3.6: "Cancellation from `CONFIRMED` is the platform's deepest
    cascade, four hops long."
    PRD §3.6: "Hop three: posture having left `FROZEN` triggers the waitlist
    promotion selection, and the top-ranked `QUEUED` entry becomes `PROMOTED`."
    PRD §3.6: "Hop four: the promoted order moves from `WAITLISTED` to
    `CONFIRMED` with `FINAL` pricing, a stamped `confirmed_at`, and a fresh
    `RESERVED` hold — after which the depot's aggregates and posture are
    recomputed once more."

    Design: Difficulty/transitive_cascade/cancel_releases_hold_posture_promotes_waitlist
    """
    depot = make_depot(2, "Depot TC1")
    set_logical_clock()
    make_active_book(full_book_payload())
    make_surge_window(
        depot["id"], "2026-05-01", "2026-05-20", "RATIONED", daily_pallet_cap=2
    )
    cust_a = make_customer(account_name="TC1 A", kind="EVENT_ORGANIZER",
                           tier="STANDARD", credit_terms="NET_30", credit_limit_cents=200000)
    cust_b = make_customer(account_name="TC1 B", kind="EVENT_ORGANIZER",
                           tier="PRIORITY", credit_terms="NET_30", credit_limit_cents=200000)

    order_a = quoted_order(
        cust_a["id"], depot["id"], [order_line("BLOCK", "PALLET", 2)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    confirmed_a = confirm(order_a["id"], cust_a["id"])
    assert confirmed_a["fulfillment_status"] == "CONFIRMED", "committed 2 <= cap 2"
    depot_before = get_depot(depot["id"])
    assert depot_before["posture"] == "FROZEN"
    assert depot_before["freezer_free_pallets"] == 0, "reserved 2 of cap 2"

    # B's general-freezer interval [13:00,20:00) is half-open disjoint from
    # A's [06:00,13:00); the RATIONED surge check forks B to the waitlist.
    order_b = quoted_order(
        cust_b["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="17:00", window_end="19:00",
    )
    forked_b = validate_success(api.confirm_order(order_b["id"], agent(cust_b["id"])))
    assert forked_b["fulfillment_status"] == "WAITLISTED", "committed 2 + 1 > cap 2"
    entry_b, status_b = _waitlist_entry_id(order_b["id"])
    assert status_b == "QUEUED"

    validate_success(api.cancel_order(order_a["id"], agent(cust_a["id"])))

    entries_after, _meta = validate_paginated(
        api_client.list_order_waitlist_entries(order_b["id"], ADMIN)
    )
    assert entries_after[0]["status"] == "PROMOTED"
    b_after = get_order(order_b["id"], agent(cust_b["id"]))
    assert b_after["fulfillment_status"] == "CONFIRMED"
    assert b_after["pricing_mode"] == "FINAL"
    assert b_after["total_cents"] == 25650, (
        "FINAL at promotion: merch 21000, discount 0, surcharge "
        "round_half_up(21000*0.15)=3150 (window ACTIVE), deposit 1500"
    )

    depot_after = get_depot(depot["id"])
    assert depot_after["freezer_free_pallets"] == 1, (
        "B's fresh RESERVED hold consumed the freed pallet"
    )
    assert depot_after["posture"] == "SURGE_CONSTRAINED", (
        "free 1 <= ceil(2 * 20%)"
    )


def test_cancel_confirmed_without_waitlist_restores_open_posture(api):
    """PRD §3.6: "Hop one: the order's `RESERVED` hold moves to `RELEASED` and
    its pallets leave the depot's reserved total."
    PRD §3.6: "Hop two: the depot's posture is recomputed from the newly freed
    space — a depot may move from `FROZEN` back to `OPEN` here."
    PRD §3.6: "An empty candidate set or exhausted headroom is a silent no-op,
    never an error."

    Design: Difficulty/transitive_cascade/cancel_releases_hold_posture_promotes_waitlist
    """
    depot = make_depot(2, "Depot TC1b")
    set_logical_clock()
    make_active_book(full_book_payload())
    make_surge_window(
        depot["id"], "2026-05-01", "2026-05-20", "RATIONED", daily_pallet_cap=2
    )
    cust_a = make_customer(account_name="TC1b A", kind="EVENT_ORGANIZER",
                           tier="STANDARD", credit_terms="NET_30", credit_limit_cents=200000)
    order_a = quoted_order(
        cust_a["id"], depot["id"], [order_line("BLOCK", "PALLET", 2)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    confirm(order_a["id"], cust_a["id"])
    assert get_depot(depot["id"])["posture"] == "FROZEN"

    cancelled = validate_success(api.cancel_order(order_a["id"], agent(cust_a["id"])))
    assert cancelled["fulfillment_status"] == "CANCELLED"

    depot_after = get_depot(depot["id"])
    assert depot_after["freezer_reserved_pallets"] == 0
    assert depot_after["freezer_free_pallets"] == 2
    assert depot_after["posture"] == "OPEN", (
        "with no QUEUED entry the promotion step is a silent no-op and the "
        "freed space simply reopens the depot"
    )
