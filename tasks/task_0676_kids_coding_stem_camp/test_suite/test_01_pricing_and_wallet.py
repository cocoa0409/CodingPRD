"""Drop-in pricing engine, wallet credit application, camp block quote, and the
money-conservation invariant on refundable cancellation.

Covers difficulty queue rules dual_variant_calc, combinatorial_formula, and the
money branch of compensating_invariant.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_session_payload, create_enrollment_payload, create_quote_payload,
    create_member_payload,
    setup_catalogue, create_guardian, credit_wallet, create_member,
    create_open_session, enroll_drop_in, current_session_version,
    make_guardian_headers, TEST_USERS,
)

ADMIN = TEST_USERS["center_admin_headers"]


# ─── dual_variant_calc / drop_in_price_full_vs_credit_offset_on_enrollment ─
def test_drop_in_full_price_when_wallet_zero(api):
    """PRD §3.6: "When the guardian's wallet credit is 0, `wallet_applied_cents` is 0
    and `price_cents` equals the discounted amount; when the wallet credit is positive,
    `wallet_applied_cents` is the smaller of the credit and the discounted amount, the
    price is reduced accordingly, and the wallet is debited."

    Design: Difficulty/dual_variant_calc/drop_in_price_full_vs_credit_offset_on_enrollment
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=5000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"], birth_date="2016-01-01")
    session, _ = create_open_session(center["id"], program["id"], format="AFTER_SCHOOL",
                                     week_count=1, assigned_instructor_count=2)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"], sibling_index=1)
    assert enrollment["price_cents"] == 5000
    assert enrollment["wallet_applied_cents"] == 0


def test_drop_in_credit_offset_when_wallet_positive(api):
    """PRD §3.6: "when the wallet credit is positive, `wallet_applied_cents` is the
    smaller of the credit and the discounted amount, the price is reduced accordingly,
    and the wallet is debited."

    Design: Difficulty/dual_variant_calc/drop_in_price_full_vs_credit_offset_on_enrollment
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=5000)
    guardian = create_guardian()
    credit_wallet(guardian["id"], 2000, reason="promo")
    member = create_member(guardian["id"], program["id"], birth_date="2016-01-01")
    session, _ = create_open_session(center["id"], program["id"], format="AFTER_SCHOOL",
                                     week_count=1, assigned_instructor_count=2)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"], sibling_index=1)
    assert enrollment["price_cents"] == 3000
    assert enrollment["wallet_applied_cents"] == 2000
    guardian_after = get_success_data(api.get_guardian(guardian["id"], ADMIN))
    assert guardian_after["wallet_credit_cents"] == 0


# ─── combinatorial_formula / drop_in_price_circular_wallet_dependency_mode_c ─
def test_camp_sibling_circular_wallet_dependency_price(api):
    """PRD §3.6: "if the session's format is `CAMP` and its `week_count` is at least 2,
    the week factor is the `week_count` multiplied by the quantity one minus 0.10 (the
    multi-week discount of ten percent)"
    PRD §3.6: "if the enrollment's `sibling_index` is at least 2, the discounted amount
    is the gross multiplied by the quantity one minus 0.15 (the sibling discount of
    fifteen percent), rounded half up to whole cents"
    PRD §3.6: "Performing the steps in this order — compute the discounted amount, derive
    the wallet application from it, then debit — makes the otherwise circular dependency
    between price and wallet well-defined."

    Design: Difficulty/combinatorial_formula/drop_in_price_circular_wallet_dependency_mode_c
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member_a = create_member(guardian["id"], program["id"])
    member_b = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(
        center["id"], program["id"], format="CAMP", week_count=2,
        starts_at="2026-06-01T09:00:00Z", ends_at="2026-06-12T15:00:00Z",
        assigned_instructor_count=5,
    )
    # Sibling A at index 1: gross = round(4000 * 2 * 0.9) = 7200, no sibling discount.
    enroll_a = enroll_drop_in(guardian["id"], session["id"], member_a["id"], sibling_index=1)
    assert enroll_a["price_cents"] == 7200
    # Credit lands AFTER A's enrollment, so it applies to B (index 2).
    credit_wallet(guardian["id"], 1000, reason="promo")
    enroll_b = enroll_drop_in(guardian["id"], session["id"], member_b["id"], sibling_index=2)
    # discounted = round(7200 * 0.85) = 6120; wallet_applied = min(1000, 6120) = 1000;
    # price = 6120 - 1000 = 5120.
    assert enroll_b["wallet_applied_cents"] == 1000
    assert enroll_b["price_cents"] == 5120


def test_camp_sibling_wallet_debited_to_zero(api):
    """PRD §3.6: "the guardian's `wallet_credit_cents` is then reduced by
    `wallet_applied_cents` (the debit happens only after the price has been pinned)."

    Design: Difficulty/combinatorial_formula/drop_in_price_circular_wallet_dependency_mode_c
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member_a = create_member(guardian["id"], program["id"])
    member_b = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(
        center["id"], program["id"], format="CAMP", week_count=2,
        starts_at="2026-06-01T09:00:00Z", ends_at="2026-06-12T15:00:00Z",
        assigned_instructor_count=5,
    )
    enroll_drop_in(guardian["id"], session["id"], member_a["id"], sibling_index=1)
    credit_wallet(guardian["id"], 1000, reason="promo")
    enroll_drop_in(guardian["id"], session["id"], member_b["id"], sibling_index=2)
    guardian_after = get_success_data(api.get_guardian(guardian["id"], ADMIN))
    assert guardian_after["wallet_credit_cents"] == 0


# ─── combinatorial_formula / camp_block_quote_round_per_seat_then_sum_mode_b ─
def test_camp_block_quote_block_total_round_per_seat_then_sum(api):
    """PRD §3.6: "The order of rounding versus summing is pinned to
    round-per-seat-then-sum: each per-seat price is computed and rounded by its own
    pinned steps first, and the block total is the sum of those already-rounded per-seat
    prices. The sum is exact integer cents and is not re-rounded"

    Design: Difficulty/combinatorial_formula/camp_block_quote_round_per_seat_then_sum_mode_b
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=3001)
    guardian = create_guardian()
    m1 = create_member(guardian["id"], program["id"])
    m2 = create_member(guardian["id"], program["id"])
    m3 = create_member(guardian["id"], program["id"])
    created = get_success_data(api.create_session(
        create_session_payload(center["id"], program["id"], format="CAMP", week_count=3,
                               starts_at="2026-07-06T09:00:00Z",
                               ends_at="2026-07-24T15:00:00Z", assigned_instructor_count=5),
        ADMIN,
    ))
    res = api.get_session_quote(
        created["id"], create_quote_payload([m1["id"], m2["id"], m3["id"]]),
        make_guardian_headers(guardian["id"]),
    )
    data = validate_success(res, 200)
    assert data["block_total_cents"] == 21879


# ─── compensating_invariant / drop_in_charge_then_refund_conserves_total_money ─
def test_refundable_drop_in_cancel_restores_wallet(api):
    """PRD §3.5: "if the time from "now" until the session's `starts_at` is at least 24
    hours, the cancel is refundable: `billing_status` becomes `REFUNDED` and the guardian's
    `wallet_credit_cents` is increased by the sum of the enrollment's `price_cents` and
    `wallet_applied_cents`, restoring both the cash paid and the wallet credit originally
    consumed so that total money is conserved."

    Design: Difficulty/compensating_invariant/drop_in_charge_then_refund_conserves_total_money
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    credit_wallet(guardian["id"], 4000, reason="seed")
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    # discounted 4000, wallet_applied 4000, price_cents 0, wallet -> 0.
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    assert enrollment["price_cents"] == 0
    assert enrollment["wallet_applied_cents"] == 4000
    # Clock at default 2026-04-01, session starts 2026-05-01 => well beyond 24h.
    cancelled = get_success_data(
        api.cancel_enrollment(enrollment["id"], make_guardian_headers(guardian["id"]))
    )
    assert cancelled["attendance_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "REFUNDED"
    guardian_after = get_success_data(api.get_guardian(guardian["id"], ADMIN))
    assert guardian_after["wallet_credit_cents"] == 4000


def test_refundable_drop_in_cancel_sets_refunded_billing(api):
    """PRD §3.5: "From a `RESERVED` attendance state the cancel sets `attendance_status`
    to `CANCELLED`, and the billing outcome depends on coverage and the refund window."

    Design: Difficulty/compensating_invariant/drop_in_charge_then_refund_conserves_total_money
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    credit_wallet(guardian["id"], 4000, reason="seed")
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    cancelled = get_success_data(
        api.cancel_enrollment(enrollment["id"], make_guardian_headers(guardian["id"]))
    )
    assert cancelled["attendance_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "REFUNDED"
