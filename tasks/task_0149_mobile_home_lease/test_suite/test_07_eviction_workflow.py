"""Eviction case lifecycle: filing, automatic FILED→IN_CURE for
NONPAYMENT/RULE_VIOLATION, direct FILED→FINALIZED_FOR_CAUSE for
ILLEGAL_USE, cure, dismiss, and the cure-window expiration sweep."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_eviction_case,
    create_draft_eviction_case,
    create_park_with_lot_and_lease,
    create_resident,
    cure_eviction_case,
    dismiss_eviction_case,
    get_eviction_case,
    get_lease,
    get_lot,
    get_resident,
    make_park_manager_headers,
    make_resident_headers,
    pay_lease,
    setup_grace_lease_positive_balance,
    setup_grace_lease_zero_balance,
    setup_lease_in_delinquent,
    sweep_evictions,
    validate_error,
)
from test_helpers.constants import (
    CURE_WINDOW_DAYS_NONPAYMENT,
    CURE_WINDOW_DAYS_RULE_VIOLATION,
)


# ===========================================================================
# Filing — PRD §3.6
# ===========================================================================
class TestEvictionFiling:
    def test_rule_violation_auto_transitions_to_in_cure_and_lease_to_grace(self, api):
        """PRD §3.6: 'When the violation type is NONPAYMENT or
        RULE_VIOLATION (the cure deadline is non-null), the case
        transitions FILED → IN_CURE and the affected lease transitions
        to GRACE: a CURRENT lease becomes GRACE.'

        Claim: filing a RULE_VIOLATION eviction → case IN_CURE, lease
        GRACE.
        """
        park, lot, r, lease = create_park_with_lot_and_lease()
        case = create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="RULE_VIOLATION",
        )
        assert_eviction_case(case)
        assert case["status"] == "IN_CURE"
        assert case["cure_deadline"] is not None
        refreshed_lease = get_lease(lease["id"])
        assert refreshed_lease["status"] == "GRACE"

    def test_illegal_use_finalizes_immediately(self, api):
        """PRD §3.6: 'When the violation type is ILLEGAL_USE (the cure
        deadline is null), the case transitions directly
        FILED → FINALIZED_FOR_CAUSE, which immediately drives the
        lease through the GRACE → TERMINATED cascade described below.'

        Claim: filing an ILLEGAL_USE eviction → case
        FINALIZED_FOR_CAUSE immediately, cure_deadline null.
        """
        park, lot, r, lease = create_park_with_lot_and_lease()
        case = create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="ILLEGAL_USE",
        )
        assert case["status"] == "FINALIZED_FOR_CAUSE"
        assert case["cure_deadline"] is None, (
            "PRD §3.6: 'In the ILLEGAL_USE case the cure deadline is "
            "null — no cure window exists at all.'"
        )

    def test_illegal_use_terminates_lease_and_nulls_lot_pointer(self, api):
        """PRD §3.6: 'The GRACE → TERMINATED cascade has four side
        effects: the lot's current_lease_id is nulled, every DRAFT or
        ISSUED RentIncreaseNotice on the affected lease transitions to
        VOIDED, the affected resident's violation_count_12mo is
        incremented by one, and the lease itself records its terminal
        state.'

        Claim: ILLEGAL_USE finalize cascades lease to TERMINATED,
        Lot.current_lease_id back to null, Resident.violation_count_12mo
        incremented by 1.
        """
        park, lot, resident, lease = create_park_with_lot_and_lease()
        baseline = get_resident(resident["id"])["violation_count_12mo"]
        create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="ILLEGAL_USE",
        )
        refreshed_lease = get_lease(lease["id"])
        refreshed_lot = get_lot(lot["id"])
        refreshed_resident = get_resident(resident["id"])
        assert refreshed_lease["status"] == "TERMINATED"
        assert refreshed_lot["current_lease_id"] is None
        assert refreshed_resident["violation_count_12mo"] == baseline + 1


# ===========================================================================
# Cure — PRD §3.6
# ===========================================================================
class TestEvictionCure:
    def test_rule_violation_cure_returns_lease_to_current(self, api):
        """PRD §3.6: 'On a successful cure, the case becomes CURED and
        the lease cascades out of GRACE: if outstanding_balance_cents
        is zero the lease returns to CURRENT, otherwise it falls back
        to DELINQUENT.'

        Claim: RULE_VIOLATION cure with zero balance → case CURED,
        lease CURRENT.
        """
        park, lot, resident, lease, case = setup_grace_lease_zero_balance()
        cured = cure_eviction_case(resident["id"], case["id"])
        assert cured["status"] == "CURED"
        refreshed_lease = get_lease(lease["id"])
        assert refreshed_lease["status"] == "CURRENT"

    def test_cure_on_illegal_use_rejected(self, api):
        """PRD §3.6: 'A cure attempt on a case whose violation type is
        ILLEGAL_USE is impossible by construction (the case never
        enters IN_CURE); the system rejects such an attempt with
        ERR_NO_CURE_PERMITTED.'

        Claim: POST /eviction-cases/{ILLEGAL_USE_case}/cure →
        ERR_NO_CURE_PERMITTED.
        """
        park, lot, resident, lease = create_park_with_lot_and_lease()
        case = create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="ILLEGAL_USE",
        )
        # ILLEGAL_USE finalizes immediately, but the cure endpoint
        # must still surface ERR_NO_CURE_PERMITTED per PRD §3.6.
        resp = api.cure_eviction_case(
            case["id"], make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_CURE_PERMITTED.value)

    def test_nonpayment_cure_requires_zero_balance(self, api):
        """PRD §3.6: 'For a NONPAYMENT case specifically, the cure
        additionally requires that the lease's outstanding_balance_cents
        equal zero at the moment of cure — a resident must have paid
        the bills in question before invoking the cure, otherwise the
        request is rejected with ERR_BALANCE_NOT_ZERO.'

        Claim: NONPAYMENT cure while balance > 0 → ERR_BALANCE_NOT_ZERO.
        """
        park, lot, resident, lease, bills = setup_lease_in_delinquent(
            master_total_cents=5000,
        )
        case = create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="NONPAYMENT",
        )
        resp = api.cure_eviction_case(
            case["id"], make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BALANCE_NOT_ZERO.value)

    def test_nonpayment_cure_succeeds_after_payment(self, api):
        """PRD §3.6: 'a resident must have paid the bills in question
        before invoking the cure.'

        Claim: after pay → balance zero → cure succeeds, case CURED.
        """
        park, lot, resident, lease, bills = setup_lease_in_delinquent(
            master_total_cents=5000,
        )
        case = create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="NONPAYMENT",
        )
        pay_lease(resident["id"], lease["id"])
        cured = cure_eviction_case(resident["id"], case["id"])
        assert cured["status"] == "CURED"

    def test_cure_after_deadline_rejected(self, api):
        """PRD §3.6: 'The cure is gated by the cure window — the
        current logical clock must be strictly before cure_deadline,
        otherwise the request is rejected with ERR_CURE_WINDOW_EXPIRED.'

        Claim: cure at or after cure_deadline →
        ERR_CURE_WINDOW_EXPIRED.
        """
        park, lot, resident, lease = create_park_with_lot_and_lease()
        case = create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="RULE_VIOLATION",
        )
        # Advance past the 14-day cure window.
        advance_clock(seconds=(CURE_WINDOW_DAYS_RULE_VIOLATION + 1) * 24 * 3600)
        resp = api.cure_eviction_case(
            case["id"], make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CURE_WINDOW_EXPIRED.value)


# ===========================================================================
# Dismiss — PRD §3.6
# ===========================================================================
class TestEvictionDismiss:
    def test_dismiss_in_cure_returns_lease_to_current_when_balance_zero(self, api):
        """PRD §3.6: 'A dismissal from IN_CURE transitions to DISMISSED
        and cascades the lease out of GRACE (back to CURRENT if
        outstanding_balance_cents is zero, otherwise to DELINQUENT).'

        Claim: dismiss IN_CURE with zero balance → case DISMISSED,
        lease CURRENT.
        """
        park, lot, resident, lease, case = setup_grace_lease_zero_balance()
        dismissed = dismiss_eviction_case(park["id"], case["id"])
        assert dismissed["status"] == "DISMISSED"
        refreshed_lease = get_lease(lease["id"])
        assert refreshed_lease["status"] == "CURRENT"

    def test_dismiss_in_cure_returns_lease_to_delinquent_when_balance_positive(self, api):
        """PRD §3.6: 'A dismissal from IN_CURE transitions to DISMISSED
        and cascades the lease out of GRACE (back to CURRENT if
        outstanding_balance_cents is zero, otherwise to DELINQUENT).'

        Claim: dismiss IN_CURE with balance > 0 → case DISMISSED,
        lease DELINQUENT.
        """
        park, lot, resident, lease, case = setup_grace_lease_positive_balance()
        dismissed = dismiss_eviction_case(park["id"], case["id"])
        assert dismissed["status"] == "DISMISSED"
        refreshed_lease = get_lease(lease["id"])
        assert refreshed_lease["status"] == "DELINQUENT"


# ===========================================================================
# Sweep — PRD §3.6
# ===========================================================================
class TestEvictionSweep:
    def test_sweep_finalizes_unresolved_in_cure_past_deadline(self, api):
        """PRD §3.6: 'The eviction sweep, run by a PlatformAdmin,
        finalizes any IN_CURE case whose cure_deadline has been
        reached without a cure (the logical clock is at or past
        cure_deadline). For each such case, the sweep transitions
        IN_CURE → FINALIZED_FOR_CAUSE and cascades the lease through
        GRACE → TERMINATED.'

        Claim: advance clock past cure_deadline, run sweep → case
        FINALIZED_FOR_CAUSE, lease TERMINATED.
        """
        park, lot, resident, lease = create_park_with_lot_and_lease()
        case = create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="RULE_VIOLATION",
        )
        advance_clock(seconds=(CURE_WINDOW_DAYS_RULE_VIOLATION + 1) * 24 * 3600)
        sweep_evictions()
        refreshed_case = get_eviction_case(case["id"])
        refreshed_lease = get_lease(lease["id"])
        assert refreshed_case["status"] == "FINALIZED_FOR_CAUSE"
        assert refreshed_lease["status"] == "TERMINATED"
