"""Percent-complete basis variants (WEIGHT vs COUNT) and the billing
approve/void booking invariant on the job aggregates."""
import pytest

from test_helpers import (
    ADMIN,
    GC_PM,
    ApiErrorId,
    api_client,
    approve_billing,
    create_billing,
    pay_billing,
    setup_job_with_pieces,
    submit_billing,
    validate_error,
    validate_success,
)

# Physically identical progress: pieces of 100/200/700 lbs with only the
# 700-lb piece standing.
IDENTICAL_PROGRESS = [("P1", 100, False), ("P2", 200, False), ("P3", 700, True)]


def _full_price_billing_submitted():
    """Job with its single 1000-lb piece standing (pct 1.0000) and one
    billing created and submitted."""
    ctx = setup_job_with_pieces("Job J", "WEIGHT", [("J-P1", 1000, True)])
    billing = create_billing(ctx["job"]["id"], "2026-08")
    submit_billing(billing["id"])
    return ctx, billing


class TestPercentCompleteVariants:

    def test_weight_basis_percent_complete(self):
        """PRD section 3.9: "For a `WEIGHT` job, percent complete is the job's
        `erected_weight_lbs` divided by its `total_weight_lbs` — every piece
        counts toward the denominator whatever its status, while only `ERECTED`
        pieces count toward the numerator."
        PRD section 3.9: "The figure is carried to exactly four decimal places
        with half-up rounding."

        Design: Difficulty/dual_variant_calc/percent_complete_weight_vs_count_basis
        """
        ctx = setup_job_with_pieces("Job W", "WEIGHT", IDENTICAL_PROGRESS)
        job = validate_success(api_client.get_job(ctx["job"]["id"], ADMIN))
        assert job["total_weight_lbs"] == 1000
        assert job["erected_weight_lbs"] == 700
        assert job["pct_complete"] == pytest.approx(0.7, abs=1e-9), (
            f"WEIGHT basis must weight by pounds: 700/1000 = 0.7000, "
            f"got {job['pct_complete']}"
        )

    def test_count_basis_percent_complete(self):
        """PRD section 3.9: "For a `COUNT` job, percent complete is the number
        of the job's pieces in `ERECTED` divided by the total number of its
        pieces, weighting every piece equally regardless of size."
        PRD section 3.9: "The figure is carried to exactly four decimal places
        with half-up rounding."

        Design: Difficulty/dual_variant_calc/percent_complete_weight_vs_count_basis
        """
        ctx = setup_job_with_pieces("Job C", "COUNT", IDENTICAL_PROGRESS)
        job = validate_success(api_client.get_job(ctx["job"]["id"], ADMIN))
        assert job["total_weight_lbs"] == 1000
        assert job["erected_weight_lbs"] == 700
        assert job["pct_complete"] == pytest.approx(0.3333, abs=1e-9), (
            f"COUNT basis must weight every piece equally: 1/3 rounds to "
            f"0.3333 at four decimals, got {job['pct_complete']}"
        )


class TestBillingBookingInvariant:

    def test_approve_books_net_and_retainage(self):
        """PRD section 3.9: "The `GC_PM` then approves, moving it from
        `SUBMITTED` to `APPROVED` and booking the money onto the job:
        `billed_to_date_cents` rises by `net_due_cents`, `retainage_held_cents`
        rises by `retainage_booked_cents`, and the job's `version` increments."

        Design: Difficulty/compensating_invariant/billing_approve_void_currency_invariant
        """
        ctx, billing = _full_price_billing_submitted()
        # pct 1.0000 -> earned 10000000; 5% retainage -> 500000; net 9500000.
        assert billing["net_due_cents"] == 9500000
        assert billing["retainage_booked_cents"] == 500000

        approved = approve_billing(billing["id"])
        assert approved["status"] == "APPROVED"
        job = validate_success(api_client.get_job(ctx["job"]["id"], ADMIN))
        assert job["billed_to_date_cents"] == 9500000, (
            f"approve must book net_due onto the job, "
            f"got {job['billed_to_date_cents']}"
        )
        assert job["retainage_held_cents"] == 500000, (
            f"approve must book retainage onto the job, "
            f"got {job['retainage_held_cents']}"
        )

    def test_void_exactly_reverses_the_booking(self):
        """PRD section 3.9: "Voiding — also from `APPROVED` alone — moves the
        billing to `VOIDED` and exactly reverses the booking:
        `billed_to_date_cents` falls by the billing's `net_due_cents`,
        `retainage_held_cents` falls by its `retainage_booked_cents`, the job's
        `version` increments, and the compound completion check runs."

        Design: Difficulty/compensating_invariant/billing_approve_void_currency_invariant
        """
        ctx, billing = _full_price_billing_submitted()
        approve_billing(billing["id"])
        voided = validate_success(api_client.void_billing(billing["id"], GC_PM))
        assert voided["status"] == "VOIDED"
        job = validate_success(api_client.get_job(ctx["job"]["id"], ADMIN))
        assert job["billed_to_date_cents"] == 0, (
            f"void must exactly reverse the booked net, "
            f"got {job['billed_to_date_cents']}"
        )
        assert job["retainage_held_cents"] == 0, (
            f"void must exactly reverse the booked retainage, "
            f"got {job['retainage_held_cents']}"
        )


class TestPaidTerminalLockdown:

    def test_billing_paid_terminal_lockdown(self):
        """PRD section 3.9: "Voiding — also from `APPROVED` alone — moves the
        billing to `VOIDED` and exactly reverses the booking:
        `billed_to_date_cents` falls by the billing's `net_due_cents`,
        `retainage_held_cents` falls by its `retainage_booked_cents`, the job's
        `version` increments, and the compound completion check runs. Both
        `PAID` and `VOIDED` are terminal."
        PRD section 2.8: "The target entity must be in a valid from-state for
        the requested transition — including a mill order placed only against a
        job that is not `ESTIMATING`, load line edits only while the load is
        `STAGING` or `LOADING`, and a field fix reported only on a `SHIPPED` or
        `ERECTED` piece — failing as `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/billing_paid_terminal_lockdown
        """
        ctx, billing = _full_price_billing_submitted()
        approve_billing(billing["id"])
        pay_billing(billing["id"])
        resp = api_client.void_billing(billing["id"], GC_PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(
            api_client.get_progress_billing(billing["id"], ADMIN)
        )
        assert after["status"] == "PAID", \
            "a rejected void must leave the billing PAID"
