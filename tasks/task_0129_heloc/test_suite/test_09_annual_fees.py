"""Annual-fee sweep: first-year waiver, suppression in DEFAULT/CLOSED,
idempotency.

Covers PRD §3.8 (anniversary indexing, waiver behavior on n==1,
ASSESSED on later anniversaries, suppression on DEFAULT/CLOSED).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ANNIVERSARY_DAYS,
    advance_clock_days,
    api_client,
    assert_fee,
    create_borrower,
    create_property,
    create_senior_lien,
    create_heloc,
    activate_heloc,
    make_borrower_headers,
    post_bankruptcy_event,
    run_annual_fees_sweep,
    setup_active_heloc,
    setup_pending_heloc,
    TEST_USERS,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §3.8 First anniversary with waiver = false → ASSESSED at annual_fee_cents
# ===========================================================================
class TestFirstAnniversaryNoWaiver:

    def test_first_anniversary_records_assessed_fee_when_no_waiver(
        self, api,
    ):
        """PRD §3.8: "on the very first anniversary (anniversary index
        equal to 1), the behavior depends on annual_fee_waived_first_year:
        when that flag is true, a Fee is created with fee_type of
        ANNUAL, amount_cents of zero, and status of WAIVED; otherwise,
        and on every subsequent anniversary regardless of the flag,
        the Fee is created with fee_type of ANNUAL, amount_cents equal
        to the HELOC's configured annual_fee_cents, and status of
        ASSESSED."
        """
        borrower, _, _, heloc = setup_active_heloc(
            annual_fee_cents=5_000,
            annual_fee_waived_first_year=False,
        )
        advance_clock_days(days=ANNIVERSARY_DAYS)
        run_annual_fees_sweep()
        resp = api.list_fees(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        fees, _ = validate_paginated(resp)
        annual_fees = [
            f for f in fees if f.get("fee_type") == "ANNUAL"
        ]
        assert len(annual_fees) == 1, (
            f"expected 1 ANNUAL fee, got {len(annual_fees)}"
        )
        f = annual_fees[0]
        assert_fee(f)
        assert f["amount_cents"] == 5_000
        assert f["status"] == "ASSESSED"
        assert f["heloc_id"] == heloc["id"]


# ===========================================================================
# §3.8 First anniversary with waiver = true → WAIVED, amount 0
# ===========================================================================
class TestFirstAnniversaryWaived:

    def test_first_anniversary_records_waived_fee_when_flag_true(
        self, api,
    ):
        """PRD §3.8: "when that flag is true, a Fee is created with
        fee_type of ANNUAL, amount_cents of zero, and status of
        WAIVED".
        """
        borrower, _, _, heloc = setup_active_heloc(
            annual_fee_cents=5_000,
            annual_fee_waived_first_year=True,
        )
        advance_clock_days(days=ANNIVERSARY_DAYS)
        run_annual_fees_sweep()
        resp = api.list_fees(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        fees, _ = validate_paginated(resp)
        annual_fees = [
            f for f in fees if f.get("fee_type") == "ANNUAL"
        ]
        assert len(annual_fees) == 1
        f = annual_fees[0]
        assert f["amount_cents"] == 0
        assert f["status"] == "WAIVED"


# ===========================================================================
# §3.8 Suppression on DEFAULT/CLOSED
# ===========================================================================
class TestAnnualFeeSuppression:

    def test_no_annual_fee_assessed_when_heloc_in_default(self, api):
        """PRD §3.8: "For each candidate assessment, if the HELOC's
        status is DEFAULT or CLOSED, the assessment is suppressed and
        no Fee is written at all."
        """
        borrower, _, _, heloc = setup_active_heloc(
            annual_fee_cents=5_000,
            annual_fee_waived_first_year=False,
        )
        # Drive the HELOC to DEFAULT BEFORE the anniversary clock
        # advance, so that at sweep time status is DEFAULT.
        post_bankruptcy_event(borrower["id"])
        advance_clock_days(days=ANNIVERSARY_DAYS)
        run_annual_fees_sweep()
        resp = api.list_fees(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        fees, _ = validate_paginated(resp)
        annual_fees = [
            f for f in fees if f.get("fee_type") == "ANNUAL"
        ]
        assert len(annual_fees) == 0, (
            f"PRD §3.8 suppression: DEFAULT HELOC must produce ZERO "
            f"ANNUAL fees; got {len(annual_fees)}"
        )


# ===========================================================================
# §3.8 Idempotency
# ===========================================================================
class TestAnnualFeeIdempotency:

    def test_double_sweep_within_same_window_produces_one_fee(self, api):
        """PRD §3.8: "The annual-fee sweep is idempotent per
        (heloc_id, anniversary_index): for each HELOC, if the current
        clock time has reached or passed origination_date plus 365
        days times the anniversary index, and no Fee record with
        fee_type of ANNUAL has yet been written for that
        (heloc_id, anniversary_index) pair, the sweep inserts one."
        """
        borrower, _, _, heloc = setup_active_heloc(
            annual_fee_cents=5_000,
            annual_fee_waived_first_year=False,
        )
        advance_clock_days(days=ANNIVERSARY_DAYS)
        run_annual_fees_sweep()
        # Second sweep within same window.
        run_annual_fees_sweep()
        resp = api.list_fees(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        fees, _ = validate_paginated(resp)
        annual_fees = [
            f for f in fees if f.get("fee_type") == "ANNUAL"
        ]
        assert len(annual_fees) == 1


# ===========================================================================
# §3.8 No fee before anniversary
# ===========================================================================
class TestAnnualFeeBeforeAnniversary:

    def test_no_fee_before_anniversary(self, api):
        """PRD §3.8: "for each HELOC, if the current clock time has
        reached or passed origination_date plus 365 days times the
        anniversary index, and no Fee record with fee_type of ANNUAL
        has yet been written for that (heloc_id, anniversary_index)
        pair, the sweep inserts one."

        Before 365 days, no fee yet.
        """
        borrower, _, _, heloc = setup_active_heloc(
            annual_fee_cents=5_000,
        )
        # Advance only 200 days — short of anniversary.
        advance_clock_days(days=200)
        run_annual_fees_sweep()
        resp = api.list_fees(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        fees, _ = validate_paginated(resp)
        annual_fees = [
            f for f in fees if f.get("fee_type") == "ANNUAL"
        ]
        assert len(annual_fees) == 0
