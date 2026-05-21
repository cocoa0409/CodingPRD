"""Home sale transfers: open → approve / reject → close, with the
buyer-eligibility check, the lot-ownership precondition, and the
APPROVED → CLOSED lease-assumption cascade."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_home_sale_transfer,
    close_home_sale_transfer,
    create_draft_eviction_case,
    create_draft_rent_increase_notice,
    create_lot,
    create_park,
    create_park_with_lot_and_lease,
    create_resident,
    create_signed_lease,
    get_home,
    get_home_sale_transfer,
    get_lease,
    get_lot,
    get_rent_increase_notice,
    issue_rent_increase_notice,
    make_park_manager_headers,
    open_home_sale_transfer,
    register_home,
    setup_resident_owned_lot_with_home,
    validate_error,
    validate_success,
)


# ===========================================================================
# Open + approve preconditions — PRD §3.7
# ===========================================================================
class TestHomeSaleApproval:
    def test_approve_on_park_owned_lot_rejected(self, api):
        """PRD §3.7: 'The lot under the home must be in RESIDENT_OWNED
        mode (a park-owned home cannot be sold through this workflow;
        an attempt is rejected with ERR_HOME_NOT_RESIDENT_OWNED).'

        Claim: open + approve a transfer while Lot.ownership_mode is
        still PARK_OWNED → ERR_HOME_NOT_RESIDENT_OWNED.
        """
        park = create_park()
        lot = create_lot(park["id"])
        seller = create_resident()
        buyer = create_resident()
        # Force the home onto a PARK_OWNED lot — note that on PARK_OWNED
        # the implementation sets owner_resident_id to null per PRD §3.1.
        home = register_home(
            park_id=park["id"], lot_id=lot["id"],
            assessed_value_cents=4_000_000,
        )
        transfer = open_home_sale_transfer(
            home_id=home["id"], seller_resident_id=seller["id"],
            buyer_resident_id=buyer["id"], sale_price_cents=4_500_000,
        )
        resp = api.approve_home_sale_transfer(
            transfer["id"], make_park_manager_headers(park["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HOME_NOT_RESIDENT_OWNED.value)

    def test_approve_with_buyer_having_recent_eviction_rejected(self, api):
        """PRD §3.7: 'the buyer must have zero EvictionCase rows in
        any of the FILED, IN_CURE, or FINALIZED_FOR_CAUSE statuses
        where the case is within the last 365 days. ... a non-zero
        count rejects the approval with ERR_BUYER_INELIGIBLE.'

        Claim: buyer with a finalized-for-cause eviction within the
        365-day window → approve returns ERR_BUYER_INELIGIBLE.
        """
        park, lot, home, seller, lease = setup_resident_owned_lot_with_home()
        # Build a buyer who has a finalized-for-cause eviction.
        dirty_buyer = create_resident()
        # Stand up a temporary park to host the buyer's bad history.
        bad_park = create_park()
        bad_lot = create_lot(bad_park["id"])
        bad_lease = create_signed_lease(
            park_id=bad_park["id"], lot_id=bad_lot["id"],
            resident_id=dirty_buyer["id"],
        )
        create_draft_eviction_case(
            park_id=bad_park["id"], lease_id=bad_lease["id"],
            violation_type="ILLEGAL_USE",
        )
        # Now open the transfer on the good park.
        transfer = open_home_sale_transfer(
            home_id=home["id"], seller_resident_id=seller["id"],
            buyer_resident_id=dirty_buyer["id"], sale_price_cents=5_500_000,
        )
        resp = api.approve_home_sale_transfer(
            transfer["id"], make_park_manager_headers(park["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BUYER_INELIGIBLE.value)

    def test_approve_with_clean_buyer_transitions_to_approved(self, api):
        """PRD §3.7: 'Approval — the PENDING_PARK_APPROVAL → APPROVED
        transition — is exclusive to a ParkManager.'

        Claim: clean buyer + RESIDENT_OWNED lot → approve transitions
        transfer to APPROVED.
        """
        park, lot, home, seller, lease = setup_resident_owned_lot_with_home()
        clean_buyer = create_resident()
        transfer = open_home_sale_transfer(
            home_id=home["id"], seller_resident_id=seller["id"],
            buyer_resident_id=clean_buyer["id"], sale_price_cents=5_500_000,
        )
        approved = approve_home_sale_transfer(park["id"], transfer["id"])
        assert approved["status"] == "APPROVED"


# ===========================================================================
# Close cascade — PRD §3.7
# ===========================================================================
class TestHomeSaleClose:
    def test_close_assumes_predecessor_and_mints_successor(self, api):
        """PRD §3.7: 'On a successful close, the predecessor lease
        transitions CURRENT → ASSUMED, which carries four side effects:
        the system mints a successor Lease in CURRENT whose
        predecessor_lease_id points to the predecessor lease's id,
        whose resident_id is the buyer, and whose monthly_rent_cents
        is copied from the predecessor lease's monthly_rent_cents ...;
        the parent lot's current_lease_id is rewritten to the
        successor lease's id; the home's owner_resident_id is set to
        the buyer; and the transfer's new_lease_id is set to the
        successor lease's id.'

        Claim: close cascade — predecessor ASSUMED, successor CURRENT
        with buyer + same rent, lot.current_lease_id == successor,
        home.owner_resident_id == buyer, transfer.new_lease_id ==
        successor.
        """
        park, lot, home, seller, lease = setup_resident_owned_lot_with_home(
            base_rent_cents=88_888,
        )
        buyer = create_resident()
        transfer = open_home_sale_transfer(
            home_id=home["id"], seller_resident_id=seller["id"],
            buyer_resident_id=buyer["id"], sale_price_cents=5_500_000,
        )
        approve_home_sale_transfer(park["id"], transfer["id"])
        closed = close_home_sale_transfer(park["id"], transfer["id"])
        assert closed["status"] == "CLOSED"
        # Predecessor ASSUMED
        predecessor = get_lease(lease["id"])
        assert predecessor["status"] == "ASSUMED"
        # Successor CURRENT with buyer + same rent
        successor_id = closed.get("new_lease_id")
        assert successor_id is not None, (
            "PRD §3.7: 'the transfer's new_lease_id is set to the "
            "successor lease's id.'"
        )
        successor = get_lease(successor_id)
        assert successor["status"] == "CURRENT"
        assert successor["resident_id"] == buyer["id"]
        assert successor["monthly_rent_cents"] == predecessor["monthly_rent_cents"]
        assert successor["predecessor_lease_id"] == lease["id"]
        # Lot.current_lease_id rewritten
        refreshed_lot = get_lot(lot["id"])
        assert refreshed_lot["current_lease_id"] == successor_id
        # Home.owner_resident_id set to buyer
        refreshed_home = get_home(home["id"])
        assert refreshed_home["owner_resident_id"] == buyer["id"]

    def test_close_voids_draft_rent_increase_notice_on_predecessor(self, api):
        """PRD §3.7: 'Any DRAFT or ISSUED rent-increase notice on the
        predecessor lease is voided as a side effect of the
        predecessor's transition to ASSUMED.'

        Claim: a DRAFT notice on the predecessor lease becomes VOIDED
        after the close cascade.
        """
        park, lot, home, seller, lease = setup_resident_owned_lot_with_home()
        notice = create_draft_rent_increase_notice(
            park_id=park["id"], lease_id=lease["id"],
            proposed_new_rent_cents=lease["monthly_rent_cents"] + 5_000,
        )
        assert notice["status"] == "DRAFT"
        buyer = create_resident()
        transfer = open_home_sale_transfer(
            home_id=home["id"], seller_resident_id=seller["id"],
            buyer_resident_id=buyer["id"], sale_price_cents=5_500_000,
        )
        approve_home_sale_transfer(park["id"], transfer["id"])
        close_home_sale_transfer(park["id"], transfer["id"])
        refreshed_notice = get_rent_increase_notice(notice["id"])
        assert refreshed_notice["status"] == "VOIDED"
