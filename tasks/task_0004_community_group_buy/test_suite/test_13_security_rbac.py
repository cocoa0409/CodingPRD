"""Security: auth header presence, role recognition, ownership."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    build_user_headers,
    create_community, create_supplier, create_customer, create_active_leader,
    create_group_buy_campaign, join_campaign,
    setup_paid_succeeded_order,
    create_community_payload,
    create_join_payload,
    ADMIN, make_customer_headers, make_group_leader_headers,
)


class TestAuthHeaderPresence:

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: X-User-ID and
        X-User-Role. If either header is missing, empty, or carries an
        unrecognised role string, the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER and HTTP 400."

        Claim: a request with X-User-Role only (no X-User-ID) is rejected
        with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        res = api.create_community(create_community_payload(name="X", region_code="RC1"),
                                     {"X-User-Role": "PlatformAdmin"})
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_unrecognised_role_rejected(self, api):
        """PRD §2.1: "If either header is missing, empty, or carries an
        unrecognised role string, the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER and HTTP 400."

        Claim: a request with a bogus X-User-Role value is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        res = api.create_community(
            create_community_payload(name="Y", region_code="RC1"),
            build_user_headers("anybody", "BogusRole"),
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


class TestRBAC:

    def test_non_admin_cannot_create_community(self, api):
        """PRD §4: POST /communities authorised role: PlatformAdmin.
        PRD §2.1: "If the header values are well-formed but resolve to a
        non-existent entity for an entity-backed role, or if the role is
        not permitted to invoke the requested endpoint per §4 ..., the
        request is rejected with ERR_FORBIDDEN".

        Claim: a Customer attempting to create a community is rejected
        with ERR_FORBIDDEN.
        """
        res = api.create_community(
            create_community_payload(name="C-RBAC", region_code="RC1"),
            build_user_headers("some-cust-id", "Customer"),
        )
        validate_error(res, "ERR_FORBIDDEN")


class TestOwnership:

    def test_customer_cannot_pay_others_order(self, api):
        """PRD §2.1: "When the role is permitted but the acting X-User-ID
        does not match the resource's owner foreign key (for example, a
        Customer paying for an Order whose customer_id is a different
        value, or a GroupLeader extending a campaign whose leader_id is
        outside their subtree), the rejection is ERR_OWNERSHIP_VIOLATION".

        Claim: a Customer trying to pay another customer's order is
        rejected with ERR_OWNERSHIP_VIOLATION.
        """
        community = create_community(name="C-OWN", region_code="RC1")
        cust_owner = create_customer(community["id"], display_name="OwnerCust")
        cust_intruder = create_customer(community["id"], display_name="IntruderCust")
        supplier = create_supplier(name="S")
        leader = create_active_leader(community["id"], display_name="L")
        campaign = create_group_buy_campaign(leader["id"], supplier["id"],
                                                unit_price_cents=100,
                                                discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                                                opens_at_period=0, deadline_period=100)
        order = join_campaign(campaign["id"], cust_owner["id"],
                              line_items=[{"sku": "SKUA", "unit_price_cents": 100, "quantity": 1}])
        # The intruder tries to pay the owner's order
        res = api.pay_order(order["id"], make_customer_headers(cust_intruder["id"]))
        validate_error(res, "ERR_OWNERSHIP_VIOLATION")


class TestEntityBackedRoleResolution:

    def test_unresolvable_customer_id_returns_forbidden(self, api):
        """PRD §2.1: "If the header values are well-formed but resolve to a
        non-existent entity for an entity-backed role ... the request is
        rejected with ERR_FORBIDDEN".

        Claim: a Customer header whose X-User-ID is a UUID that resolves to
        no Customer entity is rejected with ERR_FORBIDDEN.
        """
        community = create_community(name="C-UNK", region_code="RC1")
        supplier = create_supplier(name="S")
        leader = create_active_leader(community["id"], display_name="L")
        campaign = create_group_buy_campaign(leader["id"], supplier["id"],
                                                unit_price_cents=100,
                                                discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                                                opens_at_period=0, deadline_period=100)
        # Forge a Customer header with a non-existent UUID
        from prd_bench_local_runner.testing import NON_EXISTENT_UUID
        res = api.join_group_buy(
            campaign["id"],
            create_join_payload(NON_EXISTENT_UUID, sku="SKUA", unit_price_cents=100, quantity=1),
            build_user_headers(NON_EXISTENT_UUID, "Customer"),
        )
        validate_error(res, "ERR_FORBIDDEN")
