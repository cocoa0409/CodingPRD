"""Cross-entity state dependencies: order routing reads the stall's posture, and
lease activation reads the stall's latest health-permit status.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    open_stall, create_food_hall, create_active_vendor, create_stall,
    create_pending_permit, create_draft_lease, create_order_payload,
    TEST_USERS,
)

HM = TEST_USERS["hall_manager_headers"]
HI = TEST_USERS["health_inspector_headers"]
POS = TEST_USERS["pos_operator_headers"]


class TestOrderRoutingRequiresPosture:
    """cross_entity_state_dependency / order_routing_requires_stall_posture."""

    def test_suspended_stall_rejects_order(self, api):
        """PRD §3.5: "The stall's `operational_posture` must not be `SUSPENDED`,
        otherwise it is rejected with `ERR_STALL_SUSPENDED`; a `RESTRICTED` or `OPEN`
        stall accepts orders."

        Design: Difficulty/cross_entity_state_dependency/order_routing_requires_stall_posture
        """
        ctx = open_stall(clock="2026-06-15T18:00:00Z")
        validate_success(api.revoke_permit(ctx["permit_id"], HI), 200)  # -> SUSPENDED
        res = api.create_order(
            create_order_payload(ctx["food_hall_id"], ctx["stall_id"]), POS)
        validate_error(res, "ERR_STALL_SUSPENDED")

    def test_open_stall_routes_order(self, api):
        """PRD §3.5: "The stall's `operational_posture` must not be `SUSPENDED`,
        otherwise it is rejected with `ERR_STALL_SUSPENDED`; a `RESTRICTED` or `OPEN`
        stall accepts orders."

        Design: Difficulty/cross_entity_state_dependency/order_routing_requires_stall_posture
        """
        ctx = open_stall(clock="2026-06-15T18:00:00Z")
        data = validate_success(api.create_order(
            create_order_payload(ctx["food_hall_id"], ctx["stall_id"]), POS), 201)
        assert data["status"] == "ROUTED"


class TestLeaseActivateRequiresPermit:
    """cross_entity_state_dependency / lease_activate_requires_permit_issued."""

    def test_pending_permit_blocks_activation(self, api):
        """PRD §3.2: "Activation is permitted only when the lease is in `DRAFT`; it
        further requires that the leasing vendor is currently `ACTIVE` (otherwise
        `ERR_VENDOR_NOT_ACTIVE`), that the stall's latest health permit is `ISSUED`
        (otherwise `ERR_PERMIT_NOT_ISSUED`), that no other lease on the same stall is
        already `ACTIVE` (otherwise `ERR_STALL_ALREADY_LEASED`), and that no other
        `ACTIVE` lease on that stall has a term overlapping the interval from
        `start_date` to `end_date` (otherwise `ERR_LEASE_TERM_CONFLICT`)."

        Design: Difficulty/cross_entity_state_dependency/lease_activate_requires_permit_issued
        """
        hall = create_food_hall()
        vendor = create_active_vendor()
        stall = create_stall(hall["id"])
        create_pending_permit(stall["id"])  # never issued
        lease = create_draft_lease(stall["id"], vendor["id"])
        res = api.activate_lease(lease["id"], HM)
        validate_error(res, "ERR_PERMIT_NOT_ISSUED")

    def test_issued_permit_allows_activation(self, api):
        """PRD §3.2: "Activating a lease moves it from `DRAFT` to `ACTIVE` and is the
        moment a vendor takes possession of a stall."

        Design: Difficulty/cross_entity_state_dependency/lease_activate_requires_permit_issued
        """
        hall = create_food_hall()
        vendor = create_active_vendor()
        stall = create_stall(hall["id"])
        permit = create_pending_permit(stall["id"])
        validate_success(api.issue_permit(permit["id"], HI), 200)
        lease = create_draft_lease(stall["id"], vendor["id"])
        data = validate_success(api.activate_lease(lease["id"], HM), 200)
        assert data["status"] == "ACTIVE"
