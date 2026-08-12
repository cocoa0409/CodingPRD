"""Daily reconciliation: baselines, variance threshold, recount loop (PRD §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    count_session,
    create_priced_site,
    create_site,
    open_session,
    register_customer_cylinder,
    register_fleet_cylinders,
    setup_single_swap_day,
    swap_completed,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK1 = TEST_USERS["site_clerk_headers"]
CLERK2 = TEST_USERS["site_clerk_2_headers"]


def _day1_swap_with_overage(site, clerk):
    """One swap-with-return (total 2705) + session counted 23000 (+295 over): BALANCED."""
    customer = register_customer_cylinder(fill="EMPTY", clerk_headers=clerk)
    swap_completed(site["id"], clerk, returned_cylinder_id=customer["id"])
    session = open_session(site["id"], "2026-05-01", clerk)
    counted = count_session(session["id"], 23000, 0, 1, clerk)
    assert counted["status"] == "BALANCED", "Setup failed: +295 is under the 500 tolerance"
    return counted


class TestOpeningBaselineVariants:
    def test_reconciliation_opening_baseline_book_vs_physical(self, api):
        """PRD §3.8: "The opening baseline depends on that variant: under `BOOK` the `opening_baseline_cents` is the site's declared `opening_float_cents`; under `PHYSICAL` it is the `counted_cash_cents` of the site's most recent prior session — the one with the largest `business_date` strictly before the session's date — in `BALANCED` or `RESOLVED` status, falling back to `opening_float_cents` when no such prior session exists, so a physical-baseline site carries yesterday's counted over- or short-position into today while a book-baseline site does not."

        Design: Difficulty/dual_variant_calc/reconciliation_opening_baseline_book_vs_physical
        """
        # Two sites with identical floats, sales, and counts; only recon_basis differs.
        site_b, _ = create_priced_site()  # BOOK (default)
        register_fleet_cylinders(site_id=site_b["id"], count=1, fill="FULL", serial_prefix="FB")
        _day1_swap_with_overage(site_b, CLERK1)
        site_p, _ = create_priced_site(site_overrides={"recon_basis": "PHYSICAL"})
        register_fleet_cylinders(site_id=site_p["id"], count=1, fill="FULL", serial_prefix="FP")
        _day1_swap_with_overage(site_p, CLERK2)

        advance_clock("2026-05-02T00:00:00Z")  # day 2: no sales
        rsb2 = open_session(site_b["id"], "2026-05-02", CLERK1)
        rsp2 = open_session(site_p["id"], "2026-05-02", CLERK2)

        counted_b = count_session(rsb2["id"], 23000, 0, 1, CLERK1)
        assert rsb2["opening_baseline_cents"] == 20000, "BOOK re-bases on the declared float"
        assert counted_b["expected_cash_cents"] == 20000
        assert counted_b["cash_variance_cents"] == 3000
        assert counted_b["status"] == "VARIANCE_FLAGGED"

        counted_p = count_session(rsp2["id"], 23000, 0, 1, CLERK2)
        assert rsp2["opening_baseline_cents"] == 23000, "PHYSICAL carries the prior counted close"
        assert counted_p["expected_cash_cents"] == 23000
        assert counted_p["cash_variance_cents"] == 0
        assert counted_p["status"] == "BALANCED"

    def test_physical_baseline_falls_back_to_opening_float(self, api):
        """PRD §3.8: "under `PHYSICAL` it is the `counted_cash_cents` of the site's most recent prior session — the one with the largest `business_date` strictly before the session's date — in `BALANCED` or `RESOLVED` status, falling back to `opening_float_cents` when no such prior session exists"

        Design: Difficulty/dual_variant_calc/reconciliation_opening_baseline_book_vs_physical
        """
        site, _ = create_priced_site(site_overrides={"recon_basis": "PHYSICAL"})
        session = open_session(site["id"], "2026-05-01", CLERK1)
        assert session["basis"] == "PHYSICAL"
        assert session["opening_baseline_cents"] == 20000, "no prior session -> declared float"
        assert session["expected_cash_cents"] == 20000


class TestVarianceThreshold:
    def test_cash_variance_exactly_500_flags(self, api):
        """PRD §3.8: "The balance rule is strict: when the absolute cash variance is under 500 cents and both cylinder variances are exactly zero, the session transitions from `OPEN` to `BALANCED`; otherwise it transitions to `VARIANCE_FLAGGED`. The cash threshold is inclusive on the flag side — an absolute variance of exactly 500 cents flags the session."

        Design: Difficulty/boundary_precision_check/cash_variance_exactly_500_flags
        """
        # After one swap-with-return: expected cash 22705, expected cage 0 full / 1 empty.
        site, _customer, _order = setup_single_swap_day()
        session = open_session(site["id"], "2026-05-01", CLERK1)
        counted = count_session(session["id"], 23205, 0, 1, CLERK1)
        assert counted["cash_variance_cents"] == 500
        assert counted["status"] == "VARIANCE_FLAGGED", "exactly 500 flags (inclusive)"

    def test_cash_variance_499_balances(self, api):
        """PRD §3.8: "The balance rule is strict: when the absolute cash variance is under 500 cents and both cylinder variances are exactly zero, the session transitions from `OPEN` to `BALANCED`; otherwise it transitions to `VARIANCE_FLAGGED`."

        Design: Difficulty/boundary_precision_check/cash_variance_exactly_500_flags
        """
        site, _customer, _order = setup_single_swap_day()
        session = open_session(site["id"], "2026-05-01", CLERK1)
        counted = count_session(session["id"], 23204, 0, 1, CLERK1)
        assert counted["cash_variance_cents"] == 499
        assert counted["status"] == "BALANCED", "under 500 balances"


class TestRecountLoop:
    def test_reconciliation_recount_revert_loop(self, api):
        """PRD §3.8: "A recount returns it from `VARIANCE_FLAGGED` to `OPEN`, resetting `counted_cash_cents`, `counted_full_cylinders`, `counted_empty_cylinders`, and all three variance fields to null for a fresh count; this flag–recount loop may repeat as often as needed."
        PRD §3.8: "The balance rule is strict: when the absolute cash variance is under 500 cents and both cylinder variances are exactly zero, the session transitions from `OPEN` to `BALANCED`; otherwise it transitions to `VARIANCE_FLAGGED`."

        Design: Difficulty/non_linear_state_machine/reconciliation_recount_revert_loop
        """
        site, _customer, _order = setup_single_swap_day()
        session = open_session(site["id"], "2026-05-01", CLERK1)
        # First count: cash exact, but one phantom full cylinder -> count variance alone flags.
        first = count_session(session["id"], 22705, 1, 1, CLERK1)
        assert first["status"] == "VARIANCE_FLAGGED"
        assert first["cash_variance_cents"] == 0
        assert first["full_variance"] == 1
        # Recount resets the counted fields and reopens the session.
        reopened = validate_success(api.recount_reconciliation_session(session["id"], CLERK1), 200)
        assert reopened["status"] == "OPEN"
        assert reopened["counted_cash_cents"] is None
        assert reopened["counted_full_cylinders"] is None
        assert reopened["counted_empty_cylinders"] is None
        assert reopened["cash_variance_cents"] is None
        # Fresh count matching expectations lands BALANCED.
        second = count_session(session["id"], 22705, 0, 1, CLERK1)
        assert second["status"] == "BALANCED"

    def test_recount_loop_may_repeat(self, api):
        """PRD §3.8: "this flag–recount loop may repeat as often as needed."

        Design: Difficulty/non_linear_state_machine/reconciliation_recount_revert_loop
        """
        site, _customer, _order = setup_single_swap_day()
        session = open_session(site["id"], "2026-05-01", CLERK1)
        # First pass: flagged on cash (600 over), recount, flagged on cylinders, recount.
        flagged1 = count_session(session["id"], 23305, 0, 1, CLERK1)
        assert flagged1["status"] == "VARIANCE_FLAGGED"
        open1 = validate_success(api.recount_reconciliation_session(session["id"], CLERK1), 200)
        assert open1["status"] == "OPEN"
        flagged2 = count_session(session["id"], 22705, 2, 1, CLERK1)
        assert flagged2["status"] == "VARIANCE_FLAGGED"
        open2 = validate_success(api.recount_reconciliation_session(session["id"], CLERK1), 200)
        assert open2["status"] == "OPEN"
        final = count_session(session["id"], 22705, 0, 1, CLERK1)
        assert final["status"] == "BALANCED"


class TestSessionUniqueness:
    def test_duplicate_session_rejected(self, api):
        """PRD §3.8: "A `SiteClerk` opens a reconciliation session for a `site_id` and a `business_date`, optionally carrying an `idempotency_key` per §2.9; the pair of site and business date is unique, and a duplicate open is rejected with `ERR_SESSION_EXISTS`."

        Design: Corner/validations/duplicate_session_rejected
        """
        site = create_site(name="Dup Session Site")
        open_session(site["id"], "2026-05-01", CLERK1)
        res = api.create_reconciliation_session(
            {"site_id": site["id"], "business_date": "2026-05-01"}, CLERK1)
        validate_error(res, ApiErrorId.ERR_SESSION_EXISTS, expected_status=409)
