"""Resident lifecycle — registration, violation counter, GET shape."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    assert_resident,
    create_draft_eviction_case,
    create_park_with_lot_and_lease,
    create_resident,
    get_resident,
    make_park_manager_headers,
    sweep_evictions,
    validate_success,
)
from test_helpers.constants import VIOLATION_WINDOW_DAYS


# ===========================================================================
# Resident creation — PRD §3.1
# ===========================================================================
class TestResidentCreation:
    def test_resident_created_with_zero_violations(self, api):
        """PRD §3.1: 'The resident response surface always carries the
        computed violation_count_12mo.'

        Claim: a fresh Resident has violation_count_12mo == 0.
        """
        r = create_resident()
        assert_resident(r)
        assert r["violation_count_12mo"] == 0


# ===========================================================================
# Violation counter — PRD §3.1
# ===========================================================================
class TestViolationCountRolling:
    def test_violation_count_increments_after_terminated_eviction(self, api):
        """PRD §3.6 GRACE→TERMINATED cascade increments
        violation_count_12mo by one.

        PRD §3.1: 'The counter equals the number of EvictionCase rows
        against any lease whose resident_id is this resident's id that
        are in FINALIZED_FOR_CAUSE status and whose updated_at is
        within the last 365 days from the current logical clock.'

        Claim: after an ILLEGAL_USE eviction (which finalizes
        immediately on creation), the resident's violation_count_12mo
        equals 1.
        """
        park, lot, resident, lease = create_park_with_lot_and_lease()
        create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="ILLEGAL_USE",
        )
        refreshed = get_resident(resident["id"])
        assert refreshed["violation_count_12mo"] == 1, (
            "PRD §3.1 counter must increment on the FINALIZED_FOR_CAUSE "
            "cascade triggered by the ILLEGAL_USE eviction."
        )

    def test_violation_count_window_boundary_inclusive_at_365_days(self, api):
        """PRD §3.1: 'The window boundary is inclusive: a case whose
        updated_at is exactly 365 days ago is counted, while a case
        whose updated_at is 366 days ago is excluded.'

        Claim: after advancing the clock by exactly 365 days following
        a finalized-for-cause eviction, the counter still reads 1.
        """
        park, lot, resident, lease = create_park_with_lot_and_lease()
        create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="ILLEGAL_USE",
        )
        advance_clock(seconds=VIOLATION_WINDOW_DAYS * 24 * 3600)
        refreshed = get_resident(resident["id"])
        assert refreshed["violation_count_12mo"] == 1, (
            "Boundary is inclusive at exactly 365 days per PRD §3.1."
        )

    def test_violation_count_drops_to_zero_past_window(self, api):
        """PRD §3.1: 'a case whose updated_at is 366 days ago is
        excluded.'

        Claim: 366 days after the finalize, violation_count_12mo
        drops back to 0.
        """
        park, lot, resident, lease = create_park_with_lot_and_lease()
        create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="ILLEGAL_USE",
        )
        advance_clock(seconds=(VIOLATION_WINDOW_DAYS + 1) * 24 * 3600)
        refreshed = get_resident(resident["id"])
        assert refreshed["violation_count_12mo"] == 0, (
            "Boundary is exclusive at 366 days per PRD §3.1."
        )
