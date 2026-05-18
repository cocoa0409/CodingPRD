"""Late-fee accrual, payment waterfall, and write-off — PRD §3.3.

The interesting test cases here observe the Member-level overdue
aggregate (PRD §2.8) — which the PRD declares is recomputed whenever
charges, violations, or payments mutate — because PRD provides no
list-charges endpoint. Per-charge details are observed via
GET /hoa/assessment-charges/{id} when the test holds the id from a
prior payload echo. Tests that need a charge id walk the structure
the implementation echoes back from /issue.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    LATE_FEE_FLAT_CENTS,
    advance_clock_by_days,
    advance_clock_to,
    create_payment_payload,
    current_clock,
    get_member,
    make_member_headers,
    parse_iso,
    setup_issued_cycle,
    setup_single_unit_roster,
    tender_payment,
    validate_error,
    validate_success,
)


class TestPaymentAmountValidation:

    def test_payment_amount_zero_returns_amount_invalid(self, api):
        """PRD §3.3: "non-positive amounts are rejected with
        ERR_AMOUNT_INVALID (HTTP 422)."

        Claim: POST /hoa/payments with amount_cents=0 →
        ERR_AMOUNT_INVALID.
        """
        member = create_paying_member()
        resp = api.create_payment(
            create_payment_payload(member_id=member["id"], amount_cents=0),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMOUNT_INVALID.value)

    def test_payment_amount_negative_returns_amount_invalid(self, api):
        """PRD §3.3: "non-positive amounts are rejected with
        ERR_AMOUNT_INVALID (HTTP 422)."

        Claim: amount_cents=-1 → ERR_AMOUNT_INVALID.
        """
        member = create_paying_member()
        resp = api.create_payment(
            create_payment_payload(member_id=member["id"], amount_cents=-1),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMOUNT_INVALID.value)


def create_paying_member():
    """Create a single Member who owns one unit at share_factor 1.0000,
    so payments have a target context. Returns the Member dict."""
    member, _unit = setup_single_unit_roster()
    return member


class TestOverdueRecomputeOnPayment:

    def test_paying_off_overdue_zeroes_member_total_overdue(self, api):
        """PRD §2.8: "Lien release demands it be exactly zero." and
        PRD §3.3: "On the slow path, if the recomputation drives the
        owner's total_overdue_amount_cents to zero ...".

        Claim: after a full payment that covers principal + late_fee on
        an OVERDUE charge, the owner's total_overdue_amount_cents is 0.
        """
        member, unit, cycle = setup_issued_cycle(total_levy_cents=100_000)
        # Advance past due_date by 1 day → charge becomes OVERDUE with
        # one accrual period.
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=1, seconds=1))
        # Read member's overdue — must be principal + late_fee.
        # PRD §3.3: per_period_fee = max(2500, round(100000*0.015)=1500)
        # = 2500. periods_missed = floor(1/90)+1 = 1.
        m_after = get_member(member["id"])
        expected = 100_000 + LATE_FEE_FLAT_CENTS  # 102500
        assert m_after["total_overdue_amount_cents"] == expected, (
            f"after due+1d expected overdue {expected}, got "
            f"{m_after['total_overdue_amount_cents']}"
        )
        # Tender exactly enough to cover.
        tender_payment(member_id=member["id"], amount_cents=expected)
        m_final = get_member(member["id"])
        assert m_final["total_overdue_amount_cents"] == 0, (
            f"after full payment expected 0, got "
            f"{m_final['total_overdue_amount_cents']}"
        )


class TestPaymentOwnershipGate:

    def test_payment_with_mismatched_member_id_rejected(
        self, api, president_role_headers,
    ):
        """PRD §3.3: "A Member posts a Payment carrying their member_id
        (which MUST equal X-User-ID)".

        Claim: a payment where member_id != X-User-ID is rejected. The
        rejection is auth/RBAC-flavoured; PRD does not name a specific
        error_id for the mismatch beyond §2.1's general identity rule
        ('treated as forbidden'), so we accept ERR_FORBIDDEN as the
        canonical outcome.
        """
        member_a, _ = setup_single_unit_roster()
        # Try to post as a different X-User-ID (use the president's
        # bootstrap id — any id other than member_a["id"] suffices).
        wrong_headers = make_member_headers("someone-else-1234")
        resp = api.create_payment(
            create_payment_payload(
                member_id=member_a["id"], amount_cents=100,
            ),
            wrong_headers,
        )
        # PRD §2.1 says identity mismatch on entity_backed roles is
        # treated as forbidden. We assert ERR_FORBIDDEN.
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestLateFeeAccrualBoundary:

    def test_charge_at_exactly_89_days_overdue_accrues_one_period(self, api):
        """PRD §3.3: "Concretely, a REGULAR charge that is 89 days past
        due has accrued one period; the same charge at 91 days past due
        has accrued two".

        Claim: at exactly 89 days past due_date on a REGULAR cycle, the
        member's total_overdue reflects principal + 1 * per_period_fee
        (= max(2500, round(100000*0.015)=1500) = 2500).
        """
        member, _unit, cycle = setup_issued_cycle(total_levy_cents=100_000)
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=89))
        m = get_member(member["id"])
        expected = 100_000 + LATE_FEE_FLAT_CENTS  # 102500
        assert m["total_overdue_amount_cents"] == expected, (
            f"at due+89d expected {expected} (1 period), got "
            f"{m['total_overdue_amount_cents']}"
        )

    def test_charge_at_91_days_overdue_accrues_two_periods(self, api):
        """PRD §3.3: "the same charge at 91 days past due has accrued
        two".

        Claim: at 91 days past due on a REGULAR cycle, total_overdue
        reflects principal + 2 * per_period_fee = 100000 + 2*2500 =
        105000.
        """
        member, _unit, cycle = setup_issued_cycle(total_levy_cents=100_000)
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=91))
        m = get_member(member["id"])
        expected = 100_000 + 2 * LATE_FEE_FLAT_CENTS  # 105000
        assert m["total_overdue_amount_cents"] == expected, (
            f"at due+91d expected {expected} (2 periods), got "
            f"{m['total_overdue_amount_cents']}"
        )
