"""Race-condition tests for the explicit concurrency guarantees pinned
in PRD §2.8.

PRD §2.8 is unusually explicit about both the winner-and-loser outcome
AND the loser's error_id, so these tests assert specific error_ids
rather than using the looser exactly-one-succeeds shortcut alone.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_home_sale_transfer,
    assert_race_outcome,
    create_draft_rent_increase_notice,
    create_park_with_lot_and_lease,
    create_resident,
    make_park_manager_headers,
    make_resident_headers,
    open_home_sale_transfer,
    run_race,
    setup_lease_in_delinquent,
    setup_resident_owned_lot_with_home,
    validate_error,
    validate_error_is_one_of,
)


class TestHomeSaleApproveRace:
    def test_two_concurrent_approves_have_exactly_one_winner_with_invalid_state(self, api):
        """PRD §2.8: 'Two simultaneous approvals of the same
        HomeSaleTransfer serialize on the transfer's status field;
        exactly one wins the PENDING_PARK_APPROVAL → APPROVED
        transition and the loser receives ERR_INVALID_STATE.'

        Claim: 2x concurrent approve → exactly one 2xx, the other
        ERR_INVALID_STATE.
        """
        park, lot, home, seller, lease = setup_resident_owned_lot_with_home()
        buyer = create_resident()
        transfer = open_home_sale_transfer(
            home_id=home["id"], seller_resident_id=seller["id"],
            buyer_resident_id=buyer["id"], sale_price_cents=5_500_000,
        )
        headers = make_park_manager_headers(park["id"])
        results = run_race(
            lambda: api_client.approve_home_sale_transfer(transfer["id"], headers),
            lambda: api_client.approve_home_sale_transfer(transfer["id"], headers),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


class TestRentIncreaseIssueRace:
    def test_two_concurrent_issues_have_exactly_one_winner_with_invalid_state(self, api):
        """PRD §2.8: 'Two concurrent issue requests on the same draft
        RentIncreaseNotice serialize on its status; one issues and
        the other is rejected with ERR_INVALID_STATE.'

        Claim: 2x concurrent issue → exactly one 2xx, the other
        ERR_INVALID_STATE.
        """
        park, lot, r, lease = create_park_with_lot_and_lease(
            state_code="CA", base_rent_cents=100_000,
        )
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=105_000,
        )
        headers = make_park_manager_headers(park["id"])
        results = run_race(
            lambda: api_client.issue_rent_increase_notice(notice["id"], headers),
            lambda: api_client.issue_rent_increase_notice(notice["id"], headers),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


class TestLeasePayRace:
    def test_two_concurrent_pays_have_exactly_one_winner_with_invalid_state(self, api):
        """PRD §2.8: 'Two simultaneous pay actions on the same
        delinquent lease serialize on the drop of
        Lease.outstanding_balance_cents to zero; one succeeds in
        marking the bills paid and the duplicate is rejected with
        ERR_INVALID_STATE.'

        Claim: 2x concurrent pay on the same DELINQUENT lease →
        exactly one 2xx, the other ERR_INVALID_STATE.
        """
        park, lot, resident, lease, bills = setup_lease_in_delinquent(
            master_total_cents=5000,
        )
        headers = make_resident_headers(resident["id"])
        results = run_race(
            lambda: api_client.pay_lease(lease["id"], headers),
            lambda: api_client.pay_lease(lease["id"], headers),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)
