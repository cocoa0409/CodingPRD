"""Payment schedule generation per payment_terms_type (PRD §3.7)."""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    assert_payment_schedule,
    setup_executed_contract,
    validate_success,
)


def _list_schedule(api, po_id):
    raw = validate_success(
        api.get_payment_schedule(po_id, TEST_USERS["finance_headers"]), 200
    )
    if isinstance(raw, dict):
        raw = raw.get("payment_schedule") or raw.get("data") or raw.get("entries") or []
    return raw


# ===========================================================================
# ADVANCE terms (PRD §3.7)
# ===========================================================================
class TestPaymentScheduleAdvance:
    def test_advance_one_row_full_total(self, api):
        """PRD §3.7: "For payment_terms_type of ADVANCE, exactly one row
        is generated: installment_no 1, amount_cents equal to total,
        due_date equal to the schedule's now."

        Claim: ADVANCE produces one row with amount_cents = PO total,
        installment_no = 1.
        """
        setup = setup_executed_contract(
            payment_terms_type="ADVANCE", quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)]
        )
        schedule = _list_schedule(api, setup["po"]["id"])
        assert len(schedule) == 1
        row = schedule[0]
        assert_payment_schedule(row)
        assert row["installment_no"] == 1
        assert row["amount_cents"] == setup["po"]["total_amount_cents"]


# ===========================================================================
# ON_DELIVERY terms (PRD §3.7)
# ===========================================================================
class TestPaymentScheduleOnDelivery:
    def test_on_delivery_one_row_due_at_expected_delivery_date(self, api):
        """PRD §3.7: "For ON_DELIVERY, one row: installment_no 1,
        amount_cents equal to total, due_date equal to the requirement's
        expected_delivery_date."

        Claim: ON_DELIVERY produces one row whose due_date equals the
        requirement's expected_delivery_date.
        """
        setup = setup_executed_contract(
            payment_terms_type="ON_DELIVERY"
        )
        schedule = _list_schedule(api, setup["po"]["id"])
        assert len(schedule) == 1
        row = schedule[0]
        assert row["installment_no"] == 1
        # Compare ISO-strings up to the date portion (PRD does not pin time-of-day).
        req_due = setup["requirement"]["expected_delivery_date"]
        assert row["due_date"][:10] == req_due[:10]


# ===========================================================================
# NET_N_DAYS terms (PRD §3.7)
# ===========================================================================
class TestPaymentScheduleNetNDays:
    def test_net_30_days_due_at_expected_plus_30(self, api):
        """PRD §3.7: "For NET_N_DAYS, the payment_terms_params.net_days
        value is read; one row is generated with installment_no 1,
        amount_cents equal to total, and due_date equal to the
        requirement's expected_delivery_date plus that many days."

        Claim: NET_30 produces a single row with due_date =
        expected_delivery_date + 30 days.
        """
        from datetime import timedelta
        from test_helpers import iso_z, parse_iso
        setup = setup_executed_contract(
            payment_terms_type="NET_N_DAYS",
            payment_terms_params={"net_days": 30},
        )
        schedule = _list_schedule(api, setup["po"]["id"])
        assert len(schedule) == 1
        expected = parse_iso(setup["requirement"]["expected_delivery_date"]) + timedelta(days=30)
        # Compare just the date portion to avoid timezone noise.
        assert schedule[0]["due_date"][:10] == iso_z(expected)[:10]


# ===========================================================================
# INSTALLMENT terms (PRD §3.7) — cents remainder pinned to last
# ===========================================================================
class TestPaymentScheduleInstallment:
    def test_installment_30_70_clean_split(self, api):
        """PRD §3.7: "For INSTALLMENT, the payment_terms_params.schedule
        array provides a list of items with percent and offset_days; the
        percentages must sum to exactly 100. The system walks the array
        in declared order; for every item except the last, the
        installment's amount_cents is the integer floor of total
        multiplied by percent divided by 100; for the last item, the
        installment's amount_cents is total minus the running sum of
        the prior allocations".

        Claim: total=10,000 with [30%, 70%] yields amounts [3,000, 7,000].
        """
        # PO total: 10,000 cents = 100 * 100. quantity=100, awarded_unit_price=100.
        setup = setup_executed_contract(
            payment_terms_type="INSTALLMENT",
            payment_terms_params={
                "schedule": [
                    {"percent": 30, "offset_days": 0},
                    {"percent": 70, "offset_days": 30},
                ]
            },
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=100,
        )
        schedule = _list_schedule(api, setup["po"]["id"])
        assert len(schedule) == 2
        # Sort by installment_no.
        rows = sorted(schedule, key=lambda r: r["installment_no"])
        assert rows[0]["amount_cents"] == 3_000
        assert rows[1]["amount_cents"] == 7_000
        assert rows[0]["amount_cents"] + rows[1]["amount_cents"] == setup["po"]["total_amount_cents"]

    def test_installment_remainder_lands_on_last(self, api):
        """PRD §3.7: "for the last item, the installment's amount_cents
        is total minus the running sum of the prior allocations, so the
        cents remainder lands on the last installment. Each installment's
        due_date is the schedule's now plus the item's offset_days. The
        post-condition is that the sum of amount_cents over the generated
        schedule equals total exactly — no installment-level rounding can
        leak cents."

        Claim: total=10,001 with [30%, 70%] yields amounts [3,000, 7,001];
        sum equals 10,001.
        """
        # quantity=10001, unit_price=1 -> total=10001
        setup = setup_executed_contract(
            payment_terms_type="INSTALLMENT",
            payment_terms_params={
                "schedule": [
                    {"percent": 30, "offset_days": 0},
                    {"percent": 70, "offset_days": 30},
                ]
            },
            quote_specs=[(1, 90.0), (2, 80.0), (3, 70.0)],
            quantity=10_001,
        )
        schedule = _list_schedule(api, setup["po"]["id"])
        assert len(schedule) == 2
        rows = sorted(schedule, key=lambda r: r["installment_no"])
        assert rows[0]["amount_cents"] == 3_000  # floor(10001 * 30 / 100)
        assert rows[1]["amount_cents"] == 7_001  # remainder
        assert sum(r["amount_cents"] for r in rows) == 10_001
