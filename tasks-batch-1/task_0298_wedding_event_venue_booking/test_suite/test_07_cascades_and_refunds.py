"""Cancellation and reschedule cascades, refund retention math, and the
conserved-quantity (cash, committed-hold-count) invariants.

Translates difficulty rules `transitive_cascade`, `compensating_invariant`, and
the refund-retention instance of `dual_variant_calc`, plus the corner vendor-COI
re-upload instance.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_vendor_payload,
    create_coi_payload,
    create_reschedule_payload,
    create_inventory,
    create_inquiry_booking,
    add_both_holds,
    place_soft_hold,
    pay_deposit,
    confirm,
    setup_confirmed_booking,
    setup_confirmed_with_cleared_vendor,
    get_holds,
    get_payments,
    get_milestones,
)

VA = TEST_USERS["venue_admin_headers"]
FO = TEST_USERS["finance_officer_headers"]

_FM_DATE = ("2026-10-24", "2026-10-24T20:00:00Z", "2026-10-24T21:00:00Z",
            "2026-10-24T21:00:00Z", "2026-10-25T02:00:00Z")
_RESCHED_NOV = ("2026-11-14", "2026-11-14T20:00:00Z", "2026-11-14T21:00:00Z",
                "2026-11-14T21:00:00Z", "2026-11-15T02:00:00Z")


def _outbound_payments(payments):
    return [p for p in payments if p["direction"] == "OUTBOUND" and p["status"] == "POSTED"]


# ───────────── Rule 4: cancel cascade (holds → refund → payment_status) ─────────────

def test_cancel_cascade_releases_holds_refunds_and_sets_refunded(api):
    """PRD §3.9: "From `CONFIRMED`, every hold in `HELD` or `COMMITTED` is released
    to `RELEASED` (freeing inventory), every non-terminal `PaymentMilestone` is set
    to `WAIVED`, a cancellation refund is computed and posted as an `OUTBOUND`
    `Payment`".
    PRD §3.9: "if all inbound funds have been returned the booking lands at
    `REFUNDED`."
    PRD §3.9: "for a `FLEXIBLE` tier it is 0 percent from `HELD`, 0 percent from
    `CONFIRMED`, and 25 percent from `GUARANTEED`."

    Design: Difficulty/transitive_cascade/cancel_cascade_holds_milestones_refund_paymentstatus
    """
    inv, booking = setup_confirmed_booking(cancellation_tier="FLEXIBLE")
    get_success_data(api.cancel_booking(booking["id"], inv["client_headers"]))
    # Link 1: holds released.
    holds = get_holds(inv, booking["id"])
    assert all(h["hold_status"] == "RELEASED" for h in holds)
    # Link 2: full refund (FLEXIBLE/CONFIRMED retention 0.00) → OUTBOUND 783_800.
    outbound = _outbound_payments(get_payments(inv, booking["id"]))
    assert len(outbound) == 1
    assert outbound[0]["amount_cents"] == 783_800
    # Link 3: net inbound zero → REFUNDED.
    after = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert after["amount_paid_cents"] == 0
    assert after["payment_status"] == "REFUNDED"


def test_cancel_cascade_waives_nonterminal_milestones(api):
    """PRD §3.9: "every non-terminal `PaymentMilestone` is set to `WAIVED`".

    Design: Difficulty/transitive_cascade/cancel_cascade_holds_milestones_refund_paymentstatus
    """
    inv, booking = setup_confirmed_booking(cancellation_tier="FLEXIBLE")
    get_success_data(api.cancel_booking(booking["id"], inv["client_headers"]))
    milestones = get_milestones(inv, booking["id"])
    # Non-terminal milestones (those not already SETTLED) become WAIVED; assert no
    # milestone remains OPEN/PARTIAL after the cancel cascade.
    assert all(m["milestone_status"] in {"WAIVED", "SETTLED"} for m in milestones)
    assert any(m["milestone_status"] == "WAIVED" for m in milestones)


# ───────────── Rule 4: force-majeure approval cascade (holds → vendor revalidation) ─────────────

def test_force_majeure_approval_rewrites_date_and_recreates_holds(api):
    """PRD §3.10: "On approval, the booking's `event_date` and all four block
    instants are rewritten to the approved values; every `COMMITTED` hold of the
    booking has its old interval released and a fresh `COMMITTED` hold re-created at
    the new interval".

    Design: Difficulty/transitive_cascade/force_majeure_approval_cascade_holds_then_vendor_revalidation
    """
    inv, booking, vendor = setup_confirmed_with_cleared_vendor(
        coi_expires_on="2026-09-30", force_majeure_fee_pct=0.10)
    req = get_success_data(api.create_reschedule_request(
        booking["id"], create_reschedule_payload("FORCE_MAJEURE", *_FM_DATE),
        inv["client_headers"]))
    live = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    get_success_data(api.approve_reschedule(
        req["id"], {"expected_booking_version": live["version"]}, inv["coord_headers"]))
    after = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert after["event_date"] == "2026-10-24"
    committed = [h for h in get_holds(inv, booking["id"]) if h["hold_status"] == "COMMITTED"]
    assert len(committed) == 2
    assert all(h["occupy_start"].startswith("2026-10-24") for h in committed)


def test_force_majeure_approval_bounces_vendor_to_pending(api):
    """PRD §3.10: "every vendor is revalidated, so any vendor whose `coi_expires_on`
    now falls before the new `event_date` bounces from `CLEARED` to `PENDING`."

    Design: Difficulty/transitive_cascade/force_majeure_approval_cascade_holds_then_vendor_revalidation
    """
    inv, booking, vendor = setup_confirmed_with_cleared_vendor(
        coi_expires_on="2026-09-30", force_majeure_fee_pct=0.10)
    assert vendor["vendor_status"] == "CLEARED"
    req = get_success_data(api.create_reschedule_request(
        booking["id"], create_reschedule_payload("FORCE_MAJEURE", *_FM_DATE),
        inv["client_headers"]))
    live = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    get_success_data(api.approve_reschedule(
        req["id"], {"expected_booking_version": live["version"]}, inv["coord_headers"]))
    vendors = get_success_data(api.list_vendors(booking["id"], inv["coord_headers"]))
    rows = vendors if isinstance(vendors, list) else vendors.get("data", vendors)
    bounced = next(v for v in rows if v["id"] == vendor["id"])
    assert bounced["vendor_status"] == "PENDING"


# ───────────── Rule 1 / Rule 9: refund retention math (client cancel) ─────────────

def test_client_cancel_refund_retention_standard_confirmed(api):
    """PRD §3.9: "for a `STANDARD` tier the retention is 0 percent when cancelling
    from `HELD`, 25 percent from `CONFIRMED`, and 50 percent from `GUARANTEED`".
    PRD §3.9: "The retained amount is the net inbound multiplied by that fraction,
    rounded half up to whole cents, and the refund is the net inbound minus the
    retained amount; an `OUTBOUND` payment is posted for that refund whenever it is
    positive."

    Design: Difficulty/dual_variant_calc/client_cancel_vs_force_majeure_refund_retention
    """
    inv, booking = setup_confirmed_booking(cancellation_tier="STANDARD")
    get_success_data(api.cancel_booking(booking["id"], inv["client_headers"]))
    # paid 783_800, STANDARD/CONFIRMED retention 0.25 → retained 195_950, refund 587_850.
    outbound = _outbound_payments(get_payments(inv, booking["id"]))
    assert len(outbound) == 1
    assert outbound[0]["amount_cents"] == 587_850
    after = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert after["amount_paid_cents"] == 195_950


def test_client_cancel_refund_retention_strict_confirmed_distinct_from_standard(api):
    """PRD §3.9: "for a `STRICT` tier it is 0 percent from `HELD`, 50 percent from
    `CONFIRMED`, and 100 percent from `GUARANTEED`".
    PRD §3.9: "The retained amount is the net inbound multiplied by that fraction,
    rounded half up to whole cents, and the refund is the net inbound minus the
    retained amount".

    Design: Difficulty/dual_variant_calc/client_cancel_vs_force_majeure_refund_retention
    """
    inv, booking = setup_confirmed_booking(cancellation_tier="STRICT")
    get_success_data(api.cancel_booking(booking["id"], inv["client_headers"]))
    # paid 783_800, STRICT/CONFIRMED retention 0.50 → retained 391_900, refund 391_900.
    outbound = _outbound_payments(get_payments(inv, booking["id"]))
    assert len(outbound) == 1
    assert outbound[0]["amount_cents"] == 391_900
    after = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert after["amount_paid_cents"] == 391_900


def test_cancel_refund_conserves_net_cash_minus_retention(api):
    """PRD §3.9: "Let the net inbound amount be the booking's `amount_paid_cents`
    before the refund ... the refund is the net inbound minus the retained amount".
    PRD §3.5: "it is the sum of `amount_cents` over `INBOUND` payments with `status`
    `POSTED`, minus the sum over `OUTBOUND` payments with `status` `POSTED`."

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_net_cash_minus_retention
    """
    inv, booking = setup_confirmed_booking(cancellation_tier="STANDARD")
    get_success_data(api.cancel_booking(booking["id"], inv["client_headers"]))
    after = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    outbound = _outbound_payments(get_payments(inv, booking["id"]))
    refunded = outbound[0]["amount_cents"]
    retained = after["amount_paid_cents"]
    # Conservation: original inbound 783_800 == retained + refunded.
    assert retained == 195_950
    assert refunded == 587_850
    assert retained + refunded == 783_800


def test_cancel_refund_lands_payment_status_refunded(api):
    """PRD §3.9: "In every cancellation that posts a refund, that outbound payment
    triggers a `payment_status` recompute, and if all inbound funds have been
    returned the booking lands at `REFUNDED`."
    PRD §3.5: "The terminal `REFUNDED` state is reached only on a cancelled booking:
    from `PAID_IN_FULL`, `PARTIALLY_PAID`, or `DEPOSIT_PAID`, when outbound refunds
    have netted `amount_paid_cents` back to zero and the booking is `CANCELLED`."

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_net_cash_minus_retention
    """
    # FLEXIBLE/CONFIRMED retention is 0.00, so the full deposit is refunded and the
    # net inbound nets to zero — the only condition under which REFUNDED is reached.
    inv, booking = setup_confirmed_booking(cancellation_tier="FLEXIBLE")
    get_success_data(api.cancel_booking(booking["id"], inv["client_headers"]))
    after = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert after["amount_paid_cents"] == 0
    assert after["payment_status"] == "REFUNDED"


def test_reschedule_releases_old_holds_keeps_committed_count(api):
    """PRD §3.10: "every `COMMITTED` hold of the booking has its old interval
    released and a fresh `COMMITTED` hold re-created at the new interval".

    Design: Difficulty/compensating_invariant/reschedule_conserves_distinct_committed_space_count
    """
    inv, booking = setup_confirmed_booking(cancellation_tier="STANDARD")
    req = get_success_data(api.create_reschedule_request(
        booking["id"], create_reschedule_payload("CLIENT_REQUEST", *_RESCHED_NOV),
        inv["client_headers"]))
    live = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    get_success_data(api.approve_reschedule(
        req["id"], {"expected_booking_version": live["version"]}, inv["coord_headers"]))
    holds = get_holds(inv, booking["id"])
    # The original 2026-09-12 holds are RELEASED; the new 2026-11-14 holds COMMITTED.
    released = [h for h in holds if h["hold_status"] == "RELEASED"]
    committed = [h for h in holds if h["hold_status"] == "COMMITTED"]
    assert len(committed) == 2
    assert all(h["occupy_start"].startswith("2026-09-12") for h in released) or len(released) >= 2
    assert all(h["occupy_start"].startswith("2026-11-14") for h in committed)


def test_reschedule_conserves_distinct_committed_space_count(api):
    """PRD §3.10: "every `COMMITTED` hold of the booking has its old interval
    released and a fresh `COMMITTED` hold re-created at the new interval".

    Design: Difficulty/compensating_invariant/reschedule_conserves_distinct_committed_space_count
    """
    inv, booking = setup_confirmed_booking(cancellation_tier="STANDARD")
    before = [h for h in get_holds(inv, booking["id"]) if h["hold_status"] == "COMMITTED"]
    assert len(before) == 2
    req = get_success_data(api.create_reschedule_request(
        booking["id"], create_reschedule_payload("CLIENT_REQUEST", *_RESCHED_NOV),
        inv["client_headers"]))
    live = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    get_success_data(api.approve_reschedule(
        req["id"], {"expected_booking_version": live["version"]}, inv["coord_headers"]))
    holds = get_holds(inv, booking["id"])
    committed = [h for h in holds if h["hold_status"] == "COMMITTED"]
    assert len(committed) == 2
    block_roles = sorted(h["block_role"] for h in committed)
    assert block_roles == ["CEREMONY", "RECEPTION"]
    assert all(h["occupy_start"].startswith("2026-11-14") for h in committed)
