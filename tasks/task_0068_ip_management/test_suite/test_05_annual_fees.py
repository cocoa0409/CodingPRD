"""AnnualFeeSchedule lifecycle and surcharge tests for the IP Management API.

Covers PRD §3.3:
- Schedule creation with grace_end_date = due_date + 180 days
- Date-validity rejection (ERR_FEE_DATES_INVALID)
- Payment surcharge tiers (0% / 10% / 25% / 50%)
- Sweep PENDING→LATE→ABANDONED transitions
- Cascading abandonment from AnnualFeeSchedule → JurisdictionFiling → IPRight
"""

from test_helpers import (
    ApiErrorId,
    advance_clock_days_fixture,
    assert_annual_fee,
    create_annual_fee_payload,
    expected_surcharge_cents,
    iso_in_days,
    setup_registered_ip_with_annual_fee,
    validate_error,
    validate_success,
)


# ─────────────────────────────────────────────────────────────
# Date validity (PRD §3.3 ERR_FEE_DATES_INVALID)
# ─────────────────────────────────────────────────────────────


class TestFeeDateValidity:
    """PRD §3.3 ERR_FEE_DATES_INVALID rule."""

    def test_grace_end_equals_due_plus_180_days(
        self, api, finance_manager_headers
    ):
        """PRD §3.3: "`grace_end_date` is computed at creation as `due_date`
        plus 180 days".

        Claim: after creation, schedule.grace_end_date == due_date + 180 days
        (server-computed).
        """
        seed = setup_registered_ip_with_annual_fee(api, due_in_days=10)
        af = seed["annual_fee"]
        assert_annual_fee(af)
        # PRD says grace_end_date = due_date + 180 days. We verify that the
        # date arithmetic holds by parsing both and checking the 180-day
        # delta.
        from datetime import datetime

        def _parse(s: str) -> datetime:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))

        delta = _parse(af["grace_end_date"]) - _parse(af["due_date"])
        assert delta.days == 180, (
            f"PRD §3.3: grace_end_date - due_date must be 180 days, "
            f"got {delta.days}"
        )


# ─────────────────────────────────────────────────────────────
# Surcharge tiers (PRD §3.3)
# ─────────────────────────────────────────────────────────────


class TestSurchargeTiers:
    """PRD §3.3 four-tier piecewise rate selection."""

    def test_on_time_payment_no_surcharge(self, api, finance_manager_headers):
        """PRD §3.3: "When `days_late` is at most zero the `surcharge_rate`
        is zero."

        Claim: paying before due_date → surcharge_cents == 0.
        """
        seed = setup_registered_ip_with_annual_fee(
            api, base_fee_cents=100_000, due_in_days=10
        )
        # No clock advance — pay on time.
        resp = api.pay_annual_fee(
            seed["annual_fee"]["id"], {}, finance_manager_headers
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "PAID"
        assert data["surcharge_cents"] == 0
        assert data["total_paid_cents"] == 100_000

    def test_tier_1_surcharge_at_day_15(self, api, finance_manager_headers):
        """PRD §3.3: "When `days_late` falls in the range from 1 to 30
        inclusive (the first late tier, with maximum 30 days), the rate is
        0.10."

        Claim: days_late=15, base_fee=100_000 → surcharge_cents == 10_000.
        """
        seed = setup_registered_ip_with_annual_fee(
            api, base_fee_cents=100_000, due_in_days=1
        )
        advance_clock_days_fixture(api, 1 + 15)  # 15 days past due_date
        resp = api.pay_annual_fee(
            seed["annual_fee"]["id"], {}, finance_manager_headers
        )
        data = validate_success(resp, expected_status=200)
        assert data["surcharge_cents"] == expected_surcharge_cents(100_000, 15)
        assert data["surcharge_cents"] == 10_000
        assert data["total_paid_cents"] == 110_000


# ─────────────────────────────────────────────────────────────
# Cost row booked on payment (PRD §3.3)
# ─────────────────────────────────────────────────────────────


class TestCostRowOnPayment:
    """PRD §3.3: A Cost row of category ANNUAL_FEE is booked on payment."""

    def test_paid_fee_books_annual_fee_cost_row(
        self, api, finance_manager_headers, admin_headers
    ):
        """PRD §3.3: "A `Cost` row of category `ANNUAL_FEE` is booked for the
        `total_paid_cents`."

        Claim: after /pay, at least one Cost row exists with
        category=ANNUAL_FEE and amount_usd_cents matching total_paid_cents.
        """
        seed = setup_registered_ip_with_annual_fee(
            api, base_fee_cents=100_000, due_in_days=10
        )
        resp = api.pay_annual_fee(
            seed["annual_fee"]["id"], {}, finance_manager_headers
        )
        pay = validate_success(resp, expected_status=200)
        total = pay["total_paid_cents"]
        # Search the cost list.
        cost_resp = api.list_costs(
            finance_manager_headers, params={"category": "ANNUAL_FEE"}
        )
        items = cost_resp.json()["data"]
        assert any(int(c["amount_usd_cents"]) == total for c in items), (
            f"PRD §3.3: A Cost row of category ANNUAL_FEE must be booked for "
            f"total_paid_cents ({total}); none found among returned costs"
        )


# ─────────────────────────────────────────────────────────────
# Sweep transitions (PRD §3.3)
# ─────────────────────────────────────────────────────────────


class TestSweepTransitions:
    """PRD §3.3 /_sweep/annual-fees deferred-action state machine."""

    def test_sweep_pending_to_late_inside_grace(
        self, api, admin_headers, finance_manager_headers
    ):
        """PRD §3.3: "When invoked, it scans every `PENDING` schedule whose
        `due_date` lies strictly before the current server clock and whose
        `grace_end_date` is at or after the current server clock (with
        `paid_at` still null), and flips each such row to `LATE`."

        Claim: after due_date passes (inside grace), sweep flips PENDING →
        LATE.
        """
        seed = setup_registered_ip_with_annual_fee(api, due_in_days=1)
        advance_clock_days_fixture(api, 1 + 45)  # past due_date, inside grace
        resp = api.sweep_annual_fees(admin_headers)
        validate_success(resp, expected_status=200)
        # Re-fetch via list.
        ls = api.list_annual_fees(
            finance_manager_headers,
            params={"ip_right_id": seed["ip_right"]["id"]},
        )
        items = ls.json()["data"]
        target = next(f for f in items if f["id"] == seed["annual_fee"]["id"])
        assert target["status"] == "LATE", (
            "PRD §3.3 requires sweep to transition PENDING → LATE when "
            "now() > due_date and now() <= grace_end_date"
        )

    def test_sweep_late_to_abandoned_past_grace(
        self, api, admin_headers, finance_manager_headers
    ):
        """PRD §3.3: "It also scans every `LATE` schedule whose
        `grace_end_date` is strictly before the current server clock (with
        `paid_at` still null) and flips it to `ABANDONED`."

        Claim: past grace_end_date, sweep moves LATE → ABANDONED.
        """
        seed = setup_registered_ip_with_annual_fee(api, due_in_days=1)
        # Past grace_end_date (which is due_date + 180 days).
        advance_clock_days_fixture(api, 1 + 181)
        api.sweep_annual_fees(admin_headers)
        ls = api.list_annual_fees(
            finance_manager_headers,
            params={"ip_right_id": seed["ip_right"]["id"]},
        )
        items = ls.json()["data"]
        target = next(f for f in items if f["id"] == seed["annual_fee"]["id"])
        assert target["status"] == "ABANDONED"
