"""CRUD and input validation across the major entity surfaces."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID,
    create_community, create_supplier, create_customer,
    create_active_leader, create_pending_leader,
    create_warehouse, create_pickup_point,
    create_community_payload, create_supplier_payload, create_customer_payload,
    create_group_leader_payload, create_warehouse_payload,
    create_pickup_point_payload, create_flash_campaign_payload,
    create_group_buy_campaign_payload, create_join_payload,
    assert_community, assert_group_leader, assert_customer,
    assert_supplier, assert_warehouse, assert_pickup_point,
    assert_flash_campaign, assert_group_buy_campaign,
    ADMIN, make_group_leader_headers,
)


class TestCommunityCrud:

    def test_create_community_returns_201_with_active_status(self, api):
        """PRD §3.1: "New communities open in ACTIVE status".

        Claim: creating a community returns the entity with status=ACTIVE
        and HTTP 201.
        """
        res = api.create_community(create_community_payload(name="C-CRUD-1", region_code="RC1"), ADMIN)
        community = validate_success(res, 201)
        assert_community(community)
        assert community["status"] == "ACTIVE"
        assert community["name"] == "C-CRUD-1"

    def test_create_community_ignores_client_supplied_id(self, api):
        """PRD §2.4: "Every resource carries an id, which is a server-minted
        UUID with no type prefix; clients must never propose ids on create."

        Claim: a client-supplied id field is ignored — the server mints its own.
        """
        payload = create_community_payload(name="C-CRUD-2", region_code="RC1")
        forged_id = "11111111-1111-1111-1111-111111111111"
        payload["id"] = forged_id
        community = validate_success(api.create_community(payload, ADMIN), 201)
        assert community["id"] != forged_id


class TestGroupLeaderCrud:

    def test_create_leader_pending_review_then_approve(self, api):
        """PRD §3.1: "Newly created leaders begin in PENDING_REVIEW; they
        enter ACTIVE through approval by a PlatformAdmin".

        Claim: a fresh leader is in PENDING_REVIEW and approve advances to ACTIVE.
        """
        community = create_community(name="C-LDR", region_code="RC1")
        leader_pending = create_pending_leader(community["id"], display_name="L1")
        assert leader_pending["status"] == "PENDING_REVIEW"
        leader_active = validate_success(api.approve_leader(leader_pending["id"], ADMIN), 200)
        assert leader_active["status"] == "ACTIVE"

    def test_tier_one_when_no_parent(self, api):
        """PRD §3.1: "a leader without a parent is tier 1".

        Claim: creating a leader without parent_leader_id sets tier=1.
        """
        community = create_community(name="C-LDR-T", region_code="RC1")
        leader = create_pending_leader(community["id"], display_name="LT1")
        assert leader["tier"] == 1

    def test_child_tier_is_parent_plus_one(self, api):
        """PRD §3.1: "a leader whose parent is in tier N is in tier N + 1".

        Claim: creating a leader with parent_leader_id pointing to a tier-1
        leader assigns tier=2.
        """
        community = create_community(name="C-LDR-T2", region_code="RC1")
        parent = create_active_leader(community["id"], display_name="LP")
        child = create_pending_leader(community["id"],
                                       parent_leader_id=parent["id"],
                                       display_name="LC")
        assert child["tier"] == parent["tier"] + 1

    def test_get_nonexistent_leader_returns_not_found(self, api):
        """PRD §2.4: "Each entity has a dedicated not-found code:
        ERR_GROUP_LEADER_NOT_FOUND".

        Claim: GET against a non-existent leader id returns
        ERR_GROUP_LEADER_NOT_FOUND.
        """
        res = api.get_group_leader(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, "ERR_GROUP_LEADER_NOT_FOUND")


class TestCustomerCrud:

    def test_create_customer_returns_active(self, api):
        """PRD §3.2: "New customers begin in ACTIVE status".

        Claim: a new customer is in ACTIVE status.
        """
        community = create_community(name="C-CUST", region_code="RC1")
        cust = create_customer(community["id"], display_name="Cust-CRUD")
        assert_customer(cust)
        assert cust["status"] == "ACTIVE"


class TestSupplierWarehouseCrud:

    def test_create_warehouse_defaults_to_active(self, api):
        """PRD §3.2: "At creation, the request may also include an
        initial_status that overrides the default; otherwise the warehouse
        opens in ACTIVE."

        Claim: omitting initial_status creates an ACTIVE warehouse.
        """
        supplier = create_supplier(name="S-CRUD")
        wh = create_warehouse(supplier["id"], region_code="RC1")
        assert_warehouse(wh)
        assert wh["status"] == "ACTIVE"

    def test_create_warehouse_with_initial_status_disabled(self, api):
        """PRD §3.2: "the request may also include an initial_status that
        overrides the default; otherwise the warehouse opens in ACTIVE."

        Claim: passing initial_status='DISABLED' creates a DISABLED warehouse.
        """
        supplier = create_supplier(name="S-CRUD-D")
        wh = create_warehouse(supplier["id"], region_code="RC1",
                                initial_status="DISABLED")
        assert wh["status"] == "DISABLED"


class TestPickupPointCrud:

    def test_create_pickup_point_returns_active_with_zero_held(self, api):
        """PRD §3.1: "A pickup point begins in ACTIVE status".

        Claim: a new pickup point has status=ACTIVE and held_package_count=0.
        """
        community = create_community(name="C-PP", region_code="RC1")
        pp = create_pickup_point(community["id"], capacity_packages=3, cold_storage_capable=True)
        assert_pickup_point(pp)
        assert pp["status"] == "ACTIVE"
        assert pp["held_package_count"] == 0
        assert pp["capacity_packages"] == 3


class TestFlashCampaignCrud:

    def test_create_flash_campaign_returns_inventory_invariant(self, api):
        """PRD §3.5: "remaining_units equals total_stock minus locked_units
        minus allocated_units."

        Claim: a fresh flash campaign satisfies the inventory invariant
        with locked=0, allocated=0, remaining=total_stock.
        """
        supplier = create_supplier(name="S-FLASH")
        create_warehouse(supplier["id"], region_code="RC1")
        fc = get_success_data(api.create_flash_campaign(
            supplier["id"],
            create_flash_campaign_payload(sku="FLA", total_stock=10),
            ADMIN,
        ))
        assert_flash_campaign(fc)
        assert fc["locked_units"] == 0
        assert fc["allocated_units"] == 0
        assert fc["remaining_units"] == 10


class TestGroupBuyCampaignCrud:

    def test_create_group_buy_campaign_starts_in_forming(self, api):
        """PRD §3.3: "The campaign begins in FORMING".

        Claim: a freshly created campaign has status=FORMING and
        extension_count=0.
        """
        community = create_community(name="C-GB", region_code="RC1")
        supplier = create_supplier(name="S-GB")
        leader = create_active_leader(community["id"], display_name="L-GB")
        campaign = get_success_data(api.create_group_buy_campaign(
            leader["id"],
            create_group_buy_campaign_payload(supplier["id"]),
            make_group_leader_headers(leader["id"]),
        ))
        assert_group_buy_campaign(campaign)
        assert campaign["status"] == "FORMING"
        assert campaign["extension_count"] == 0
        assert campaign["participant_count"] == 0


class TestOrderCreation:

    def test_join_order_starts_pending_pay_not_planned(self, api):
        """PRD §3.4: "The order begins with payment_status of PENDING_PAY
        and fulfillment_status of NOT_PLANNED."

        Claim: a join request creates an order with both fields at the
        documented initial values.
        """
        community = create_community(name="C-J", region_code="RC1")
        cust = create_customer(community["id"], display_name="C")
        supplier = create_supplier(name="S-J")
        leader = create_active_leader(community["id"], display_name="L")
        campaign = get_success_data(api.create_group_buy_campaign(
            leader["id"],
            create_group_buy_campaign_payload(supplier["id"], unit_price_cents=100),
            make_group_leader_headers(leader["id"]),
        ))
        from test_helpers import make_customer_headers
        order = get_success_data(api.join_group_buy(
            campaign["id"],
            create_join_payload(cust["id"], sku="SKUA", unit_price_cents=100, quantity=1),
            make_customer_headers(cust["id"]),
        ))
        assert order["payment_status"] == "PENDING_PAY"
        assert order["fulfillment_status"] == "NOT_PLANNED"
        assert order["campaign_kind"] == "GROUP_BUY"
        assert order["customer_id"] == cust["id"]
        # subtotal is 100*1 = 100
        assert order["subtotal_cents"] == 100

    def test_invalid_quantity_rejected(self, api):
        """PRD §3.4: "A non-positive quantity is rejected with ERR_INVALID_QUANTITY."

        Claim: a join request with quantity=0 is rejected with ERR_INVALID_QUANTITY.
        """
        community = create_community(name="C-IQ", region_code="RC1")
        cust = create_customer(community["id"], display_name="C")
        supplier = create_supplier(name="S-IQ")
        leader = create_active_leader(community["id"], display_name="L")
        campaign = get_success_data(api.create_group_buy_campaign(
            leader["id"],
            create_group_buy_campaign_payload(supplier["id"], unit_price_cents=100),
            make_group_leader_headers(leader["id"]),
        ))
        from test_helpers import make_customer_headers
        res = api.join_group_buy(
            campaign["id"],
            create_join_payload(cust["id"], sku="SKUA", unit_price_cents=100, quantity=0),
            make_customer_headers(cust["id"]),
        )
        validate_error(res, "ERR_INVALID_QUANTITY")
