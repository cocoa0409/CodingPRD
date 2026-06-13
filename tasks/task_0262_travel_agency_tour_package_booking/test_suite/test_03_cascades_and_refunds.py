"""Cancellation cascades, payment reversal, refund destinations, and conserved-quantity
invariants.

Covers difficulty rules: transitive_cascade (mandatory reject reopens booking, cancel
refunds payments), dual_variant_calc (cancellation refund ORIGINAL vs WALLET),
compensating_invariant (payment ledger conserved, customer money split); plus the
corner cascading_side_effects claim.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_payment_payload, reserve_payload, confirm_payload, cancel_payload,
)
from test_helpers.fixtures import (
    create_agency, create_customer, create_supplier, create_published_package,
    open_draft_booking, add_travelers, attach_insurance, request_component,
    setup_reserved_booking, setup_reserved_deposit_settled, setup_confirmed_booking,
    setup_reserved_manual_component, setup_reserved_paid_in_full,
    get_milestone_id, get_booking, _booking_version, pay_milestone,
    supplier_reject_component, AGENT, ADMIN,
)
from test_helpers import api_client


# ─── transitive_cascade: mandatory reject reopens booking ────────────────
def test_mandatory_reject_reopens_booking_and_waives_milestones(api):
    """PRD §3.6: "When a supplier rejects a component that is `is_mandatory` while its
    parent booking is `RESERVED`, a bubble-up revision cascade fires: the parent booking
    is forced back `RESERVED → DRAFT` for re-sourcing, all of its `OPEN` payment milestones
    are moved to `WAIVED`, its `payment_status` is recomputed (with no open or settled
    milestones remaining, it lands at `UNPAID`), and the booking's `version` increments."

    Design: Difficulty/transitive_cascade/tc_mandatory_reject_reopens_booking_waives_milestones
    """
    ctx = setup_reserved_manual_component(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    supplier_reject_component(ctx["supplier"]["id"], ctx["component_id"])

    booking = get_booking(ctx["booking_id"])
    assert booking["status"] == "DRAFT"
    assert booking["payment_status"] == "UNPAID"
    deposit = validate_success(api.get_milestone(ctx["deposit_ms_id"], AGENT), 200)
    assert deposit["status"] == "WAIVED"


def test_mandatory_reject_waives_balance_milestone_too(api):
    """PRD §3.6: "all of its `OPEN` payment milestones are moved to `WAIVED`".

    Design: Difficulty/transitive_cascade/tc_mandatory_reject_reopens_booking_waives_milestones
    """
    ctx = setup_reserved_manual_component(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    supplier_reject_component(ctx["supplier"]["id"], ctx["component_id"])
    balance = validate_success(api.get_milestone(ctx["balance_ms_id"], AGENT), 200)
    assert balance["status"] == "WAIVED"


# ─── transitive_cascade: cancel refunds payments, reverts settlement ─────
def test_cancel_refunds_payments_and_reverts_settlement(api):
    """PRD §3.7: "Every `APPLIED` payment on the booking is moved to `REFUNDED` (and each
    refund reverses its allocation against its milestone's `settled_amount_cents`); every
    `OPEN` payment milestone is moved to `WAIVED`; the booking's `paid_cents` is recomputed
    to 0".

    CONFIRMED booking with deposit 20000 settled, cancelled (TIER_FREE): paid_cents -> 0,
    deposit.settled_amount_cents -> 0.

    Design: Difficulty/transitive_cascade/tc_cancel_refunds_payments_and_reverts_settlement
    """
    ctx = setup_confirmed_booking(
        num_travelers=1, deposit_amount=20000, clock="2026-01-01T00:00:00.000Z",
        departure_date="2026-06-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    version = _booking_version(ctx["booking_id"])
    cancelled = validate_success(api.cancel_booking(
        ctx["booking_id"], cancel_payload(version, refund_destination="ORIGINAL"), AGENT), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["paid_cents"] == 0
    deposit = validate_success(api.get_milestone(ctx["deposit_ms_id"], AGENT), 200)
    assert deposit["settled_amount_cents"] == 0


def test_cancel_marks_applied_payment_refunded(api):
    """PRD §3.9: "When a booking cancellation refunds an `APPLIED` payment, that payment
    moves `APPLIED → REFUNDED` and the reversal flows through the ledger".

    Design: Difficulty/transitive_cascade/tc_cancel_refunds_payments_and_reverts_settlement
    """
    ctx = setup_confirmed_booking(
        num_travelers=1, deposit_amount=20000, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    payments_before = api.list_payments(AGENT, params={"booking_id": ctx["booking_id"]}).json()["data"]
    payment_id = payments_before[0]["id"]
    version = _booking_version(ctx["booking_id"])
    validate_success(api.cancel_booking(
        ctx["booking_id"], cancel_payload(version, refund_destination="ORIGINAL"), AGENT), 200)
    payment = validate_success(api.get_payment(payment_id, AGENT), 200)
    assert payment["status"] == "REFUNDED"


# ─── dual_variant_calc + compensating_invariant: refund ORIGINAL vs WALLET ─
def test_cancellation_refund_credits_wallet(api):
    """PRD §3.7: "If the `refund_destination` is `WALLET`, the customer's
    `wallet_credit_cents` is increased by `refund_cents`".
    PRD §3.7: "The `penalty_cents` is the `refundable_base_cents` multiplied by the
    chosen `penalty_pct`, divided by one hundred, rounded half-up to whole cents."
    PRD §3.7: "if they are at least 30 but fewer than 60, the tier is `TIER_LOW` with a
    `penalty_pct` of 25".

    grand 495000, paid 495000, 30 days out (TIER_LOW 25%), PREMIUM refundable so
    refundable_base = 495000, penalty = 123750, refund = 371250 -> wallet.

    Design: Difficulty/dual_variant_calc/dvc_cancellation_refund_original_vs_wallet
    """
    ctx = setup_reserved_paid_in_full(
        num_travelers=5, deposit_amount=99000, balance_amount=396000,
        clock="2026-01-01T00:00:00.000Z", departure_date="2026-01-31T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20,
                       "min_group_size_for_discount": 5})
    version = _booking_version(ctx["booking_id"])
    validate_success(api.cancel_booking(
        ctx["booking_id"], cancel_payload(version, refund_destination="WALLET"), AGENT), 200)

    records = api.list_cancellation_records(AGENT, params={"booking_id": ctx["booking_id"]}).json()["data"]
    record = records[0]
    assert record["penalty_cents"] == 123750
    assert record["refund_cents"] == 371250

    customer = validate_success(api.get_customer(ctx["customer"]["id"], AGENT), 200)
    assert customer["wallet_credit_cents"] == 371250


def test_cancellation_refund_to_original_leaves_wallet_untouched(api):
    """PRD §3.7: "if it is `ORIGINAL`, the `refund_cents` is reported on the
    `CancellationRecord` and the customer's wallet is left untouched."
    PRD §3.7: "The `refund_cents` is the booking's `paid_cents` (measured before this
    cancellation reverses any payments) minus the `penalty_cents`, floored at zero".

    Same money basis, ORIGINAL destination: refund 371250 on the record, wallet stays 0.

    Design: Difficulty/dual_variant_calc/dvc_cancellation_refund_original_vs_wallet
    """
    ctx = setup_reserved_paid_in_full(
        num_travelers=5, deposit_amount=99000, balance_amount=396000,
        clock="2026-01-01T00:00:00.000Z", departure_date="2026-01-31T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20,
                       "min_group_size_for_discount": 5})
    version = _booking_version(ctx["booking_id"])
    validate_success(api.cancel_booking(
        ctx["booking_id"], cancel_payload(version, refund_destination="ORIGINAL"), AGENT), 200)

    records = api.list_cancellation_records(AGENT, params={"booking_id": ctx["booking_id"]}).json()["data"]
    assert records[0]["refund_cents"] == 371250
    customer = validate_success(api.get_customer(ctx["customer"]["id"], AGENT), 200)
    assert customer["wallet_credit_cents"] == 0


# ─── compensating_invariant: payment ledger conserved on cancel ──────────
def test_payment_ledger_conserved_on_cancel(api):
    """PRD §3.9: "it is how `paid_cents` lands at 0 after a cancel even when payments had
    previously settled milestones."
    PRD §3.7: "the booking's `paid_cents` is recomputed to 0".

    CONFIRMED booking, deposit 20000 settled, TIER_FREE cancel: paid_cents 0,
    deposit.settled 0, wallet untouched (ORIGINAL).

    Design: Difficulty/compensating_invariant/ci_payment_ledger_conserved_on_cancel
    """
    ctx = setup_confirmed_booking(
        num_travelers=1, deposit_amount=20000, clock="2026-01-01T00:00:00.000Z",
        departure_date="2026-06-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    version = _booking_version(ctx["booking_id"])
    cancelled = validate_success(api.cancel_booking(
        ctx["booking_id"], cancel_payload(version, refund_destination="ORIGINAL"), AGENT), 200)
    assert cancelled["paid_cents"] == 0
    deposit = validate_success(api.get_milestone(ctx["deposit_ms_id"], AGENT), 200)
    assert deposit["settled_amount_cents"] == 0
    customer = validate_success(api.get_customer(ctx["customer"]["id"], AGENT), 200)
    assert customer["wallet_credit_cents"] == 0


def test_payment_ledger_identity_paid_equals_settled_after_cancel(api):
    """PRD §3.7: "the booking's `paid_cents` is recomputed to 0".
    PRD §3.9: "the affected milestone's `settled_amount_cents` decreases by the payment's
    `amount_cents`, which may flip that milestone back from `SETTLED` to `OPEN` (after
    which the cancel sweep waives it), and the booking's `paid_cents` is recomputed."

    After a TIER_FREE cancel of a deposit-settled booking, paid_cents equals the sum of
    milestone settled_amount_cents (both 0) — the ledger identity holds with no drift.

    Design: Difficulty/compensating_invariant/ci_payment_ledger_conserved_on_cancel
    """
    ctx = setup_confirmed_booking(
        num_travelers=1, deposit_amount=20000, clock="2026-01-01T00:00:00.000Z",
        departure_date="2026-06-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    version = _booking_version(ctx["booking_id"])
    cancelled = validate_success(api.cancel_booking(
        ctx["booking_id"], cancel_payload(version, refund_destination="ORIGINAL"), AGENT), 200)
    milestones = api.list_milestones(AGENT, params={"booking_id": ctx["booking_id"]}).json()["data"]
    total_settled = sum(m["settled_amount_cents"] for m in milestones)
    assert cancelled["paid_cents"] == total_settled == 0


def test_customer_money_split_refund_plus_penalty(api):
    """PRD §3.7: "The `penalty_cents` is the `refundable_base_cents` multiplied by the
    chosen `penalty_pct`, divided by one hundred, rounded half-up to whole cents. The
    `refund_cents` is the booking's `paid_cents` (measured before this cancellation
    reverses any payments) minus the `penalty_cents`, floored at zero".
    PRD §3.7: "If the `refund_destination` is `WALLET`, the customer's `wallet_credit_cents`
    is increased by `refund_cents`".

    paid 495000 == refund 371250 (to wallet) + penalty 123750 retained; no leakage.

    Design: Difficulty/compensating_invariant/ci_customer_money_split_refund_plus_penalty
    """
    ctx = setup_reserved_paid_in_full(
        num_travelers=5, deposit_amount=99000, balance_amount=396000,
        clock="2026-01-01T00:00:00.000Z", departure_date="2026-01-31T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20,
                       "min_group_size_for_discount": 5})
    version = _booking_version(ctx["booking_id"])
    validate_success(api.cancel_booking(
        ctx["booking_id"], cancel_payload(version, refund_destination="WALLET"), AGENT), 200)
    records = api.list_cancellation_records(AGENT, params={"booking_id": ctx["booking_id"]}).json()["data"]
    record = records[0]
    assert record["penalty_cents"] == 123750
    assert record["refund_cents"] == 371250
    assert record["refund_cents"] + record["penalty_cents"] == 495000
    customer = validate_success(api.get_customer(ctx["customer"]["id"], AGENT), 200)
    assert customer["wallet_credit_cents"] == 371250


def test_refundable_base_includes_full_grand_total_for_premium_only(api):
    """PRD §3.7: "the `refundable_base_cents` is `grand_total_cents` minus the sum of the
    `premium_cents` of every `ACTIVE` insurance policy on the booking whose `refundable`
    flag is false — that is, the non-refundable `BASIC` premiums are carved out of the
    base before the penalty is taken, while refundable `PREMIUM` premiums stay in the
    base."

    With only a refundable PREMIUM policy, refundable_base == grand_total 495000 and the
    TIER_LOW penalty 123750 + refund 371250 conserve the full paid amount.

    Design: Difficulty/compensating_invariant/ci_customer_money_split_refund_plus_penalty
    """
    ctx = setup_reserved_paid_in_full(
        num_travelers=5, deposit_amount=99000, balance_amount=396000,
        clock="2026-01-01T00:00:00.000Z", departure_date="2026-01-31T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20,
                       "min_group_size_for_discount": 5})
    version = _booking_version(ctx["booking_id"])
    validate_success(api.cancel_booking(
        ctx["booking_id"], cancel_payload(version, refund_destination="WALLET"), AGENT), 200)
    records = api.list_cancellation_records(AGENT, params={"booking_id": ctx["booking_id"]}).json()["data"]
    record = records[0]
    assert record["refundable_base_cents"] == 495000
    assert record["penalty_cents"] + record["refund_cents"] == 495000


# ─── Corner cascade claim ────────────────────────────────────────────────
def test_cancel_releases_components_and_voids_insurance(api):
    """PRD §3.7: "every `ACTIVE` insurance policy is moved to `VOIDED`; and every component
    not already `RELEASED` is moved to `RELEASED` (a confirmed, requested, or rejected
    component all land at `RELEASED`)."

    Cancelling a RESERVED booking RELEASES its CONFIRMED component and VOIDS its ACTIVE
    PREMIUM insurance policy.

    Design: Corner/cross_cutting_complexity_layers/cascade_cancel_releases_components_and_voids_insurance
    """
    agency = create_agency(clock="2026-01-01T00:00:00.000Z")
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="FLIGHT", auto_confirm=True)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000,
                                       deposit_pct=20)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    add_travelers(booking["id"], 1, booking["version"])
    policy = attach_insurance(booking["id"], "PREMIUM")
    component = request_component(booking["id"], supplier["id"], kind="FLIGHT",
                                  starts_at="2026-06-01T08:00:00.000Z",
                                  ends_at="2026-06-01T12:00:00.000Z")
    version = _booking_version(booking["id"])
    reserved = validate_success(api.reserve_booking(booking["id"], reserve_payload(version), AGENT), 200)
    cancelled = validate_success(api.cancel_booking(
        booking["id"], cancel_payload(reserved["version"], refund_destination="ORIGINAL"), AGENT), 200)
    assert cancelled["status"] == "CANCELLED"

    component_after = validate_success(api.get_component(component["id"], AGENT), 200)
    assert component_after["status"] == "RELEASED"
    policy_after = validate_success(api.get_insurance_policy(policy["id"], AGENT), 200)
    assert policy_after["status"] == "VOIDED"
