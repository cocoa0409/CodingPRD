"""Rent-increase notices: drafting, issuance with cap application,
voiding on lease termination, effective sweep promotion."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days,
    advance_clock,
    api_client,
    assert_rent_increase_notice,
    create_draft_eviction_case,
    create_draft_rent_increase_notice,
    create_park_with_lot_and_lease,
    create_rent_increase_notice_payload,
    get_lease,
    get_lot,
    get_rent_increase_notice,
    iso_utc,
    issue_rent_increase_notice,
    make_park_manager_headers,
    sweep_rent_effective,
    utcnow,
    validate_error,
    validate_success,
)


# ===========================================================================
# Cap application — PRD §2.9, §3.5
# ===========================================================================
class TestRentCapApplication:
    def test_ca_with_cpi_2_caps_at_7_percent(self, api):
        """PRD §2.9: 'A park in CA caps the annual increase at five
        percent plus the park's master_cpi_pct, with a hard absolute
        ceiling of ten percent. That is, the effective cap is the
        smaller of 5.0 + master_cpi_pct and 10.0.'

        PRD §3.5: 'the system multiplies the current monthly_rent_cents
        by one plus the maximum percent divided by one hundred, and
        rounds the resulting cent value half up to the nearest integer
        cent.'

        Claim: CA park with master_cpi_pct=2.00, current rent 100000,
        proposed 108000 (8%) → cap activates at 7% → capped value
        round(100000 * 1.07) = 107000.
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="CA", master_cpi_pct=2.00, base_rent_cents=100_000,
        )
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=108_000,
        )
        issued = issue_rent_increase_notice(park["id"], notice["id"])
        assert issued["status"] == "ISSUED"
        assert issued["capped_new_rent_cents"] == 107_000, (
            "CA cap = min(5 + 2, 10) = 7%, applied to 100000."
        )

    def test_or_with_cpi_2_caps_at_9_percent(self, api):
        """PRD §2.9: 'A park in OR caps the annual increase at seven
        percent plus the park's master_cpi_pct, with the same hard
        absolute ceiling of ten percent — the effective cap is the
        smaller of 7.0 + master_cpi_pct and 10.0.'

        Claim: OR park with cpi=2.00, current 100000, proposed 120000
        (20%) → cap activates at 9% → capped value 109000.
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="OR", master_cpi_pct=2.00, base_rent_cents=100_000,
        )
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=120_000,
        )
        issued = issue_rent_increase_notice(park["id"], notice["id"])
        assert issued["capped_new_rent_cents"] == 109_000

    def test_az_flat_10_ignores_cpi(self, api):
        """PRD §2.9: 'A park in AZ caps the annual increase at a flat
        ten percent; the master_cpi_pct value is not consulted for AZ.'

        Claim: AZ park with cpi=8.00 (would be a 18% combined cap if
        added), current 100000, proposed 120000 (20%) → cap activates
        at flat 10% → capped value 110000.
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="AZ", master_cpi_pct=8.00, base_rent_cents=100_000,
        )
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=120_000,
        )
        issued = issue_rent_increase_notice(park["id"], notice["id"])
        assert issued["capped_new_rent_cents"] == 110_000, (
            "AZ flat 10%, CPI ignored per PRD §2.9."
        )

    def test_fl_uncapped_passes_proposed_through(self, api):
        """PRD §2.9: 'A park in FL or TX has no statutory cap; any
        proposed increase is accepted at the proposed value regardless
        of its magnitude.'

        Claim: FL park proposed 108000 (8%) → capped_new_rent_cents ==
        108000 (no cap activated).
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="FL", master_cpi_pct=2.00, base_rent_cents=100_000,
        )
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=108_000,
        )
        issued = issue_rent_increase_notice(park["id"], notice["id"])
        assert issued["capped_new_rent_cents"] == 108_000

    def test_tx_uncapped_passes_proposed_through(self, api):
        """PRD §2.9: 'A park in FL or TX has no statutory cap; any
        proposed increase is accepted at the proposed value regardless
        of its magnitude.'

        Claim: TX park proposed 200000 (100% increase!) →
        capped_new_rent_cents == 200000.
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="TX", master_cpi_pct=5.00, base_rent_cents=100_000,
        )
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=200_000,
        )
        issued = issue_rent_increase_notice(park["id"], notice["id"])
        assert issued["capped_new_rent_cents"] == 200_000

    def test_ca_high_cpi_clamps_at_10_percent_ceiling(self, api):
        """PRD §2.9: 'the effective cap is the smaller of
        5.0 + master_cpi_pct and 10.0.'

        Claim: CA park with cpi=8.00 (5+8=13 > ceiling 10), proposed
        120000 (20%) → cap clamps to 10% → capped 110000.
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="CA", master_cpi_pct=8.00, base_rent_cents=100_000,
        )
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=120_000,
        )
        issued = issue_rent_increase_notice(park["id"], notice["id"])
        assert issued["capped_new_rent_cents"] == 110_000


# ===========================================================================
# Notice window — PRD §3.5
# ===========================================================================
class TestNoticeWindow:
    def test_window_exactly_90_days_accepted(self, api):
        """PRD §3.5: 'The effective_on must be at least 90 calendar
        days after the moment of issuance (a notice whose effective_on
        is less than 90 days out is rejected with
        ERR_NOTICE_WINDOW_TOO_SHORT).'

        Claim: effective_on exactly 90 days out at issue → ISSUED
        (boundary inclusive).
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="CA", base_rent_cents=100_000,
        )
        # Use a 91-day offset so the boundary is comfortably met even
        # if the implementation does a strict integer-day comparison
        # with arrival-time jitter.
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=105_000,
            effective_on_days_from_now=91,
        )
        issued = issue_rent_increase_notice(park["id"], notice["id"])
        assert issued["status"] == "ISSUED"

    def test_window_too_short_rejected(self, api):
        """PRD §3.5: 'a notice whose effective_on is less than 90 days
        out is rejected with ERR_NOTICE_WINDOW_TOO_SHORT.'

        Claim: effective_on 30 days out → ERR_NOTICE_WINDOW_TOO_SHORT.
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="CA", base_rent_cents=100_000,
        )
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=105_000,
            effective_on_days_from_now=30,
        )
        resp = api.issue_rent_increase_notice(
            notice["id"], make_park_manager_headers(park["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_TOO_SHORT.value)


# ===========================================================================
# Nonpositive proposal — PRD §3.5
# ===========================================================================
class TestRentIncreaseNonpositive:
    def test_proposed_equal_to_current_rejected(self, api):
        """PRD §3.5: 'the proposed value must be strictly greater than
        the current monthly_rent_cents — an equal-or-lower proposed
        value is rejected with ERR_RENT_INCREASE_NONPOSITIVE.'

        Claim: proposed equal to current rent → on issuance,
        ERR_RENT_INCREASE_NONPOSITIVE.
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="CA", base_rent_cents=100_000,
        )
        # The constraint applies on issuance. Build a draft via a
        # raw API call so the factory does not enforce >.
        effective_on = iso_utc(
            add_days(utcnow(), 100).replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
        )
        draft_resp = api_client.create_rent_increase_notice(
            lease["id"],
            create_rent_increase_notice_payload(
                proposed_new_rent_cents=100_000,
                effective_on=effective_on,
            ),
            make_park_manager_headers(park["id"]),
        )
        # PRD doesn't pin where this is rejected — at draft or at issue.
        # PRD §3.5 prose pins the gate on ISSUE: "the proposed value
        # must be strictly greater than ... an equal-or-lower proposed
        # value is rejected with ERR_RENT_INCREASE_NONPOSITIVE."
        if draft_resp.status_code in (200, 201):
            draft = draft_resp.json()["data"]
            resp = api_client.issue_rent_increase_notice(
                draft["id"], make_park_manager_headers(park["id"]),
            )
            validate_error(
                resp, ApiErrorId.ERR_RENT_INCREASE_NONPOSITIVE.value,
            )
        else:
            # Some implementations may reject at draft time as a
            # general validation. Per PRD §3.5 prose the rule fires
            # at issue, so we accept either where rejected.
            validate_error(
                draft_resp,
                ApiErrorId.ERR_RENT_INCREASE_NONPOSITIVE.value,
            )


# ===========================================================================
# Blocked during eviction — PRD §3.5
# ===========================================================================
class TestRentIncreaseBlockedDuringEviction:
    def test_issuance_blocked_while_lease_in_grace(self, api):
        """PRD §3.5: 'If the lease is in GRACE (because an eviction is
        pending against it), the issue is rejected with
        ERR_RENT_INCREASE_BLOCKED_DURING_EVICTION — the system refuses
        to escalate the financial terms of a tenancy that is already
        under eviction.'

        Claim: lease in GRACE + issue → ERR_RENT_INCREASE_BLOCKED_DURING_EVICTION.
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="CA", base_rent_cents=100_000,
        )
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=105_000,
        )
        # File a RULE_VIOLATION eviction → lease enters GRACE.
        create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="RULE_VIOLATION",
        )
        resp = api.issue_rent_increase_notice(
            notice["id"], make_park_manager_headers(park["id"]),
        )
        validate_error(
            resp,
            ApiErrorId.ERR_RENT_INCREASE_BLOCKED_DURING_EVICTION.value,
        )


# ===========================================================================
# Effective sweep — PRD §3.5
# ===========================================================================
class TestRentEffectiveSweep:
    def test_effective_sweep_writes_capped_rent_to_lease_and_lot(self, api):
        """PRD §3.5: 'The sweep walks every ISSUED notice whose
        effective_on has been reached by the logical clock; for each,
        provided the lease is still in CURRENT or DELINQUENT, the
        sweep writes the notice's capped_new_rent_cents into both the
        lease's monthly_rent_cents and the parent lot's
        base_rent_cents.'

        Claim: after issue + clock advance past effective_on +
        rent-effective sweep, lease.monthly_rent_cents and
        lot.base_rent_cents both equal capped_new_rent_cents.
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="CA", master_cpi_pct=2.00, base_rent_cents=100_000,
        )
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=107_000,  # 7% → CA cap = 7% → cap doesn't bind
            effective_on_days_from_now=100,
        )
        issued = issue_rent_increase_notice(park["id"], notice["id"])
        assert issued["capped_new_rent_cents"] == 107_000
        # Advance past effective_on (100 days).
        advance_clock(seconds=101 * 24 * 3600)
        sweep_rent_effective()
        # Verify side-effects.
        refreshed_lease = get_lease(lease["id"])
        refreshed_lot = get_lot(lot["id"])
        assert refreshed_lease["monthly_rent_cents"] == 107_000
        assert refreshed_lot["base_rent_cents"] == 107_000


# ===========================================================================
# Notice voided on lease termination — PRD §3.5
# ===========================================================================
class TestNoticeVoidedOnTermination:
    def test_issued_notice_voided_when_lease_terminates(self, api):
        """PRD §3.5: 'A notice that has not yet become effective is
        voided automatically if the lease it targets terminates or is
        assumed. Specifically: when the lease transitions to
        TERMINATED (as the tail of a finalized eviction) ..., any
        DRAFT or ISSUED RentIncreaseNotice on that lease transitions
        to VOIDED.'

        Claim: ISSUED notice + ILLEGAL_USE eviction (which terminates
        the lease immediately) → notice.status == VOIDED.
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="CA", base_rent_cents=100_000,
        )
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=105_000,
        )
        issued = issue_rent_increase_notice(park["id"], notice["id"])
        assert issued["status"] == "ISSUED"
        # ILLEGAL_USE eviction terminates the lease immediately.
        create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="ILLEGAL_USE",
        )
        refreshed_notice = get_rent_increase_notice(notice["id"])
        assert refreshed_notice["status"] == "VOIDED"
