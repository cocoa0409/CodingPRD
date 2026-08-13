"""Donor site lifecycle transitions and their preconditions (PRD §3.1)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_donor, create_offer, publish_offer,
    make_donor_coordinator_headers,
)

ADMIN = TEST_USERS["admin_headers"]


class TestDonorLifecycle:
    def test_pending_review_cannot_be_suspended(self, api):
        """PRD §3.1: "Approval moves the donor from `PENDING_REVIEW` to `ACTIVE`
        (any other source state is rejected with `ERR_INVALID_STATE_TRANSITION`)
        and increments the donor's `version`. Suspension moves an `ACTIVE` donor
        to `SUSPENDED`;"

        Design: Corner/state_machines/donor_invalid_transition_rejected
        """
        donor = create_donor(legal_name="IT Bistro", ein="100000004",
                             contact_email="it@bistro.example", activate=False)
        assert donor["status"] == "PENDING_REVIEW"
        created_version = donor["version"]

        resp = api.patch_donor_site_status(donor["id"], "SUSPENDED", ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        resp = api.get_donor_site(donor["id"], ADMIN)
        after = validate_success(resp)
        assert after["status"] == "PENDING_REVIEW"
        assert after["version"] == created_version, (
            "a rejected transition mutates nothing, so version is unchanged"
        )

    def test_deactivation_blocked_by_open_offer_then_allowed(self, api):
        """PRD §3.1: "Deactivation is terminal: a donor reaches `DEACTIVATED`
        from either `ACTIVE` or `SUSPENDED` only when none of its offers remains
        in `DRAFT`, `OPEN`, `MATCHED`, `SCHEDULED`, `PICKED_UP`, or `DELIVERED`,
        and the attempt is otherwise rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/donor_deactivate_with_open_offer_rejected
        """
        donor = create_donor(legal_name="Deact Bistro", ein="100000005",
                             contact_email="de@bistro.example")
        offer = create_offer(donor["id"], food_category="SHELF_STABLE",
                             estimated_weight_lbs=5, publish=True)
        assert offer["status"] == "OPEN"

        resp = api.patch_donor_site_status(donor["id"], "DEACTIVATED", ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        # Cancelling the last in-flight offer unblocks deactivation.
        resp = api.patch_donation_offer_status(
            offer["id"], "CANCELLED", make_donor_coordinator_headers(donor["id"]))
        validate_success(resp)
        resp = api.patch_donor_site_status(donor["id"], "DEACTIVATED", ADMIN)
        data = validate_success(resp)
        assert data["status"] == "DEACTIVATED"
