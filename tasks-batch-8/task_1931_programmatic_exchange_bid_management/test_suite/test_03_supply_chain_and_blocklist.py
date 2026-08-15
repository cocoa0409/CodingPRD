"""Supply-path chain invariants and brand-safety blocklist enforcement."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_supply_hop,
    assert_blocklist_entry,
    assert_outcome,
    assert_supply_chain_node,
    create_blocklist_entry_payload,
    create_deal_for,
    create_package_for,
    create_partner,
    create_publisher,
    fill_auction,
    make_publisher_manager_headers,
    run_auction,
    setup_active_deal,
    submit_and_approve_deal,
    validate_error,
    validate_paginated,
    validate_success,
    make_bid,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["exchange_admin_headers"]


class TestSupplyChain:
    def test_supply_chain_node_hop_index_and_tail_flag(self, api):
        """PRD §3.2: "The first hop omits `parent_node_id` and receives
        `hop_index` zero. Every subsequent append must name the chain's current
        tail in `parent_node_id`: a node of the same package whose `is_tail` is
        still true. ... and the append atomically flips the parent's `is_tail`
        to false while the new node takes `hop_index` one greater than its
        parent's."

        Design: Corner/entities/supply_chain_node_hop_index_and_tail_flag
        """
        pub = create_publisher()
        pkg = create_package_for(pub["id"])
        n0 = add_supply_hop(pkg["id"], pub["id"], "ssp1.com", 1000)
        assert_supply_chain_node(n0)
        assert n0["hop_index"] == 0, "The first hop takes hop_index zero"
        assert n0["is_tail"] is True

        n1 = add_supply_hop(pkg["id"], pub["id"], "ssp2.com", 500,
                            parent_node_id=n0["id"])
        assert_supply_chain_node(n1)
        assert n1["hop_index"] == 1, "The child takes the parent's hop_index + 1"
        assert n1["is_tail"] is True

        items, meta = validate_paginated(
            api.list_supply_chain_nodes(ADMIN, params={"package_id": pkg["id"]}))
        assert meta["total_count"] == 2
        by_id = {n["id"]: n for n in items}
        assert by_id[n0["id"]]["is_tail"] is False, (
            "Appending flips the parent's is_tail to false")
        assert by_id[n1["id"]]["is_tail"] is True

    def test_supply_chain_append_to_non_tail_rejected(self, api):
        """PRD §3.2: "Naming anything else — a mid-chain node, a node of another
        package, a node that is already a parent — is rejected with
        `ERR_SUPPLY_CHAIN_NOT_TAIL`"

        Design: Corner/validations/supply_chain_append_to_non_tail_rejected
        """
        pub = create_publisher()
        pkg = create_package_for(pub["id"])
        n0 = add_supply_hop(pkg["id"], pub["id"], "ssp1.com", 1000)
        add_supply_hop(pkg["id"], pub["id"], "ssp2.com", 500,
                       parent_node_id=n0["id"])
        mgr = make_publisher_manager_headers(pub["id"])
        resp = api.create_supply_chain_node(
            {"package_id": pkg["id"], "seller_domain": "ssp3.com",
             "fee_bps": 100, "parent_node_id": n0["id"]},
            mgr)
        validate_error(resp, ApiErrorId.ERR_SUPPLY_CHAIN_NOT_TAIL)
        _items, meta = validate_paginated(
            api.list_supply_chain_nodes(ADMIN, params={"package_id": pkg["id"]}))
        assert meta["total_count"] == 2, "The chain is unchanged by the rejected append"


class TestBlocklist:
    def test_blocklist_double_lift_rejected(self, api):
        """PRD §3.4: "A lifted entry can never return to `ACTIVE`; attempting to
        lift it again is rejected with `ERR_ENTRY_ALREADY_LIFTED`, and
        reinstating the rule means creating a fresh entry."

        Design: Corner/state_machines/blocklist_double_lift_rejected
        """
        entry = validate_success(
            api.create_blocklist_entry(
                create_blocklist_entry_payload("EXCHANGE", "ADVERTISER_DOMAIN",
                                               "evil.com"),
                ADMIN), 201)
        assert_blocklist_entry(entry)
        assert entry["status"] == "ACTIVE"

        lifted = validate_success(api.lift_blocklist_entry(entry["id"], ADMIN))
        assert lifted["status"] == "LIFTED"

        resp = api.lift_blocklist_entry(entry["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ENTRY_ALREADY_LIFTED)
        after = validate_success(api.get_blocklist_entry(entry["id"], ADMIN))
        assert after["status"] == "LIFTED"

    def test_existence_check_beats_blocklist_scope_safety(self, api):
        """PRD §2.8: "Every request passes through a fixed validation pipeline,
        and the request fails at the first check that does not pass — later
        checks never mask earlier ones."
        PRD §2.8: "5. Existence: every path identifier and every body foreign key
        resolves, validated left to right — a deal before its report, a batch
        before its line — else `ERR_NOT_FOUND`."
        (Pipeline stage 5, existence, fires before stage 8, blocklist scope
        consistency.)

        Design: Corner/validations/existence_check_beats_blocklist_scope_safety
        """
        pub = create_publisher()
        resp = api.create_blocklist_entry(
            create_blocklist_entry_payload("DEAL", "ADVERTISER_DOMAIN", "evil.com",
                                           publisher_id=pub["id"],
                                           deal_id=NON_EXISTENT_UUID),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_brand_safety_domain_drop_promotes_next_highest_bid(self, api):
        """PRD §3.5: "First, brand safety drops every bid whose `creative_domain`
        is blocked for this deal by any `ACTIVE` `ADVERTISER_DOMAIN` entry at
        exchange, publisher, or deal scope; dropped bids produce no errors and
        simply do not compete."
        PRD §3.5: "a `FIRST_PRICE` deal clears at exactly the winning bid"

        Design: Corner/calculations/brand_safety_domain_drop_promotes_next_highest_bid
        """
        sc = setup_active_deal()
        validate_success(
            api.create_blocklist_entry(
                create_blocklist_entry_payload("EXCHANGE", "ADVERTISER_DOMAIN",
                                               "evil.com"),
                ADMIN), 201)
        data = run_auction(sc["pub"]["id"], [
            make_bid(3000000, 1000, "evil.com"),
            make_bid(2000000, 1000, "good.com"),
        ])
        assert_outcome(data, "FILL")
        record = data["auction_record"]
        assert record["creative_domain"] == "good.com", (
            "The blocked 3,000,000 bid was dropped before ranking")
        assert record["winning_bid_cpm_micros"] == 2000000
        assert record["clearing_cpm_micros"] == 2000000, (
            "FIRST_PRICE pays the surviving winning bid")

    def test_category_blocklist_excludes_deal_from_selection(self, api):
        """PRD §3.4: "`CATEGORY` entries gate deal eligibility during selection:
        a deal is ineligible while any `ACTIVE` category entry's `value` appears
        among its package's `category_tags` at a matching scope."
        PRD §3.5: "Eligible deals are ranked exclusive-first — `is_exclusive`
        deals ahead of non-exclusive ones — then by higher
        `approved_floor_cpm_micros`"

        Design: Corner/calculations/category_blocklist_excludes_deal_from_selection
        """
        pub = create_publisher()
        partner = create_partner()
        pkg1 = create_package_for(pub["id"], name="Pkg1",
                                  category_tags=("IAB_ALC",))
        pkg2 = create_package_for(pub["id"], name="Pkg2",
                                  category_tags=("IAB_NEWS",))
        d1 = submit_and_approve_deal(
            create_deal_for(pub["id"], pkg1["id"], partner["id"],
                            floor_cpm_micros=2000000)["id"], pub["id"])
        d2 = submit_and_approve_deal(
            create_deal_for(pub["id"], pkg2["id"], partner["id"],
                            floor_cpm_micros=1000000)["id"], pub["id"])
        validate_success(
            api.create_blocklist_entry(
                create_blocklist_entry_payload("EXCHANGE", "CATEGORY", "IAB_ALC"),
                ADMIN), 201)

        data = run_auction(pub["id"], [make_bid(3000000, 1000, "a.com")])
        assert_outcome(data, "FILL")
        record = data["auction_record"]
        assert record["deal_id"] == d2["id"], (
            "D1 is excluded by the CATEGORY rule despite ranking first on "
            "approved floor")
        assert record["clearing_cpm_micros"] == 3000000
