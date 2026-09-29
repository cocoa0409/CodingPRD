"""Who may write what: each endpoint admits only the role that owns it, and the two
entity-backed roles are narrowed further to the row their `X-User-ID` names."""

from test_helpers import (
    CLOCK_SETUP,
    COUNTY_PRIMARY,
    OPS_CLOSER,
    TEST_USERS,
    add_lot,
    api_client,
    close_lot,
    create_asset_listing_payload,
    create_auction_event_payload,
    create_bidder_payload,
    create_event,
    create_exclusion_payload,
    create_listing,
    create_seller,
    create_seller_payload,
    create_trustee_sale,
    create_trustee_sale_payload,
    disclosed_asset,
    disclosures_payload,
    eligibility_assessment,
    fund_deposit_payload,
    funded_bidder,
    identity_verification_payload,
    live_lot,
    make_bidder_headers,
    make_seller_headers,
    open_event,
    place_bid,
    place_bid_payload,
    read_bidder,
    read_listing,
    read_lot,
    read_sale,
    register_bidder,
    relist_payload,
    reserve_price_payload,
    set_clock,
    title_clearance_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify_bidder,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["auction_ops_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
TITLE_OFFICER = TEST_USERS["title_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]

EVENT_START = "2026-09-15T17:00:00Z"
EVENT_END = "2026-09-15T19:00:00Z"
WINDOW_START = "2026-09-15T17:00:00Z"
WINDOW_END = "2026-09-15T18:00:00Z"


class TestIntakeWritesAreRoleExclusive:
    def test_each_intake_write_admits_only_the_role_that_owns_it(self):
        """Onboarding, listing, disclosing, title work and the county notice each belong to
        exactly one role, and every cross-role attempt is refused without leaving a row or
        overwriting a field.

        PRD: "`ERR_FORBIDDEN_ROLE` (403) — the acting role appears in the called endpoint's
        authorized-role list. Applies to every endpoint."
        PRD: "`PlatformAdmin` is the marketplace operator. It onboards sellers, drives the
        logical clock, and may read everything."
        PRD: "`Seller` is a servicer, bank, government-sponsored enterprise or private
        seller. It owns its own asset listings, files their disclosures, and relists them."
        PRD: "`Trustee` is the foreclosure trustee for the county-sale leg: it notices
        statutory sales and confirms, postpones or cancels them."
        PRD: "`TitleOfficer` is a title company officer whose only write capability is
        recording the outcome of a title search — the finding that gates contract execution."

        Design: Corner/rbac/intake_write_endpoints_admit_only_their_owning_role
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            occupancy_status="TENANT_OCCUPIED",
            title_condition="JUNIOR_LIENS",
            org_name="Role Intake Bank",
            seller_type="BANK",
            contact_email="reo@roleintake.example",
            settlement_account_ref="ACH-ROLE-1",
            street_address="1 Roleintake Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        assert bundle.seller["seller_type"] == "BANK"
        assert bundle.listing["listing_status"] == "DISCLOSURE_READY"

        cleared = validate_success(
            api_client.record_title_clearance(
                bundle.listing_id,
                title_clearance_payload(
                    "CLEARED", "JUNIOR_LIENS", title_report_reference="TR-ROLE-1"
                ),
                TITLE_OFFICER,
            )
        )
        assert cleared["title_clearance_status"] == "CLEARED"
        sale = create_trustee_sale(bundle.listing_id, "2026-09-15T18:00:00Z")

        validate_error(
            api_client.create_seller(
                create_seller_payload(
                    org_name="Ops Cannot Onboard",
                    contact_email="ops@roleintake.example",
                    settlement_account_ref="ACH-ROLE-X",
                ),
                OPS,
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.create_asset_listing(
                create_asset_listing_payload(
                    bundle.seller_id,
                    street_address="9 Roleintake Rd",
                    city="Oakland",
                    estimated_value_cents=26000000,
                ),
                ADMIN,
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.file_disclosures(
                bundle.listing_id, disclosures_payload("VACANT", "CLEAR"), OPS
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.record_title_clearance(
                bundle.listing_id,
                title_clearance_payload(
                    "DEFECTIVE", "CLOUDED", title_report_reference="TR-ROLE-BAD"
                ),
                TRUSTEE,
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.confirm_trustee_sale(sale["id"], {}, TITLE_OFFICER),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.create_trustee_sale(
                create_trustee_sale_payload(bundle.listing_id, "2026-09-16T18:00:00Z"),
                ANONYMOUS,
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )

        _, listings_meta = validate_paginated(
            api_client.list_asset_listings(ADMIN, params={"seller_id": bundle.seller_id})
        )
        assert listings_meta["total_count"] == 1

        untouched = read_listing(bundle.listing_id)
        assert untouched["occupancy_status"] == "TENANT_OCCUPIED"
        assert untouched["title_clearance_status"] == "CLEARED"

        _, sales_meta = validate_paginated(
            api_client.list_asset_listing_trustee_sales(bundle.listing_id, TRUSTEE)
        )
        assert sales_meta["total_count"] == 1
        assert read_sale(sale["id"])["status"] == "PENDING"

    def test_scheduling_and_compliance_are_separate_authorities(self):
        """Auction operations owns the calendar and the reserves but not identity or
        exclusions, compliance owns the reverse, and self-registration is the one write the
        public visitor holds alone.

        PRD: "`ERR_FORBIDDEN_ROLE` (403) — the acting role appears in the called endpoint's
        authorized-role list. Applies to every endpoint."
        PRD: "`ComplianceOfficer` owns know-your-customer and eligibility control: it records
        identity-verification decisions and creates and lifts eligibility exclusions."
        PRD: "`AuctionOps` is auction operations: it schedules events, builds lots, revises
        reserves, opens and closes bidding, executes purchase contracts, records escrow
        closings and fallout, and issues second-chance offers."
        PRD: "`Anonymous` is an unauthenticated public visitor. It may register itself as a
        bidder and read the public auction catalogue, including the title and eviction-risk
        disclosures published for each asset."

        Design: Corner/rbac/auction_and_compliance_writes_are_closed_to_the_other_operator_roles
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            org_name="Role Ops Bank",
            seller_type="BANK",
            contact_email="reo@roleops.example",
            settlement_account_ref="ACH-ROPS-1",
            street_address="1 Roleops Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        event = create_event(
            title="Role Ops Event",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )
        lot = add_lot(
            event["id"],
            bundle.listing_id,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        bidder = register_bidder(
            legal_name="Role Ops Bidder LLC",
            email="bid@roleops.example",
            mailing_address="2 Roleops Rd, Oakland CA",
        )
        verified = verify_bidder(bidder["id"], "VERIFIED", "KYC-ROPS-1")
        assert verified["identity_verification_status"] == "VERIFIED"

        validate_error(
            api_client.create_auction_event(
                create_auction_event_payload(
                    title="Compliance Cannot Schedule",
                    starts_at="2026-09-16T17:00:00Z",
                    ends_at="2026-09-16T19:00:00Z",
                ),
                COMPLIANCE,
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.update_reserve_price(
                lot["id"],
                reserve_price_payload(24000000, lot["version"]),
                make_seller_headers(bundle.seller_id),
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.record_identity_verification(
                bidder["id"],
                identity_verification_payload("REJECTED", document_reference="KYC-ROPS-2"),
                OPS,
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.create_eligibility_exclusion(
                create_exclusion_payload(
                    bidder["id"], "SANCTIONS_LIST", "2026-09-01T00:00:00Z"
                ),
                OPS,
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.create_bidder(
                create_bidder_payload(
                    legal_name="Admin Cannot Register LLC",
                    email="admin@roleops.example",
                    mailing_address="3 Roleops Rd, Oakland CA",
                ),
                ADMIN,
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )

        _, events_meta = validate_paginated(
            api_client.list_auction_events(OPS, params={"county_code": COUNTY_PRIMARY})
        )
        assert events_meta["total_count"] == 1

        unchanged = read_lot(lot["id"])
        assert unchanged["reserve_price_cents"] == 20000000
        assert unchanged["version"] == lot["version"]

        standing = read_bidder(bidder["id"])
        assert standing["identity_verification_status"] == "VERIFIED"
        assert standing["registration_status"] == "REGISTERED"

        _, exclusions_meta = validate_paginated(
            api_client.list_bidder_exclusions(bidder["id"], COMPLIANCE)
        )
        assert exclusions_meta["total_count"] == 0


class TestEntityBackedOwnership:
    def test_a_bidder_may_only_act_for_itself(self):
        """A peer bidder holds the right role and is still refused on the wallet, on the bid
        and on the assessment, while a role with no bidder identity at all is stopped one
        band earlier.

        PRD: "When `X-User-Role` is `Bidder`, `X-User-ID` is the `id` of the acting `Bidder`
        row. Funding a deposit requires `X-User-ID` to equal the bidder id addressed in the
        path; placing a bid requires it to equal the `bidder_id` in the request body;
        responding to a second-chance offer requires it to equal that offer's
        `offered_bidder_id`; and reading an eligibility assessment for another bidder is
        refused. Each of these mismatches is also `ERR_NOT_RESOURCE_OWNER`."
        PRD: "A `PlatformAdmin` or `ComplianceOfficer` may assess any bidder; a `Bidder` may
        assess only itself."
        PRD: "The deposit penalty applies only when the assessment has been given a specific
        lot to reason about, and then only when the bidder's `deposit_available_cents` is
        strictly less than that lot's `required_deposit_cents`; with no lot in context the
        deposit penalty is never applied."
        PRD: "The new bid is written with a `bid_status` of `ACTIVE` and a `placed_at`
        stamped from the logical clock."

        Design: Corner/rbac/bidder_writes_are_scoped_to_the_acting_bidder_id
        """
        scenario = live_lot(
            org_name="Scope Bank",
            seller_type="BANK",
            contact_email="reo@scope.example",
            settlement_account_ref="ACH-SCOP-1",
            street_address="1 Scope Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Scope Event",
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        assert read_lot(scenario.lot_id)["required_deposit_cents"] == 1000000

        first = funded_bidder(
            1000000,
            legal_name="Scope Bidder A LLC",
            email="a@scope.example",
            mailing_address="2 Scope Rd, Oakland CA",
            document_reference="KYC-SCOP-A",
            funding_reference="WIRE-SCOP-A",
        )
        peer = funded_bidder(
            1000000,
            legal_name="Scope Bidder B LLC",
            email="b@scope.example",
            mailing_address="3 Scope Rd, Oakland CA",
            document_reference="KYC-SCOP-B",
            funding_reference="WIRE-SCOP-B",
        )
        assert first["deposit_funded_cents"] == 1000000

        set_clock("2026-09-15T17:10:00Z")
        peer_headers = make_bidder_headers(peer["id"])
        validate_error(
            api_client.fund_deposit(
                first["id"],
                fund_deposit_payload(500000, funding_reference="WIRE-SCOP-X"),
                peer_headers,
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.place_bid(
                scenario.lot_id, place_bid_payload(first["id"], 20000000), peer_headers
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.get_eligibility_assessment(
                first["id"], peer_headers, params={"mode": "SCREEN"}
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.get_eligibility_assessment(
                first["id"], TRUSTEE, params={"mode": "SCREEN"}
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )

        own = eligibility_assessment(
            first["id"], mode="SCREEN", headers=make_bidder_headers(first["id"])
        )
        assert own["mode"] == "SCREEN"
        assert own["risk_score"] == 0

        accepted = place_bid(scenario.lot_id, first["id"], 20000000)
        assert accepted["bid_status"] == "ACTIVE"

        assert read_bidder(first["id"])["deposit_funded_cents"] == 1000000
        assert read_bidder(peer["id"])["deposit_available_cents"] == 1000000

        bids, bids_meta = validate_paginated(
            api_client.list_bids(OPS, params={"auction_lot_id": scenario.lot_id})
        )
        assert bids_meta["total_count"] == 1
        assert bids[0]["bidder_id"] == first["id"]

    def test_two_sellers_holding_one_role_stay_isolated_by_ownership(self):
        """A second seller is refused on the first seller's disclosures, on its relist and on
        a listing created under its id, and then the owner's identical relist is accepted.

        PRD: "When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`
        row. Ownership checks compare `X-User-ID` against the `seller_id` of the
        `AssetListing` being acted on — and, on asset intake, against the `seller_id`
        supplied in the request body. A mismatch is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD: "Its `listing_status` begins at `INTAKE` and its `title_clearance_status` at
        `PENDING`; `occupancy_status` and `title_condition` both begin at `UNKNOWN`;
        `relist_count` is 0 and `second_chance_eligible` is false; and `disclosure_ack_at` —
        the instant the seller acknowledged the disclosures — is not yet set."
        PRD: "Relisting is the seller's reset. It takes an asset whose `listing_status` is
        `UNSOLD` or `RELIST_PENDING` back to `DISCLOSURE_READY`, increments `relist_count` by
        1, resets `second_chance_eligible` to false, and resets `title_clearance_status` to
        `PENDING` so a fresh title search can run — the title axis loops with the marketplace
        axis rather than remaining pinned to a stale finding."

        Design: Corner/rbac/sellers_cannot_reach_each_others_listings
        """
        set_clock(CLOCK_SETUP)
        owner_bundle = disclosed_asset(
            org_name="Peer Owner Bank",
            seller_type="BANK",
            contact_email="reo@peerowner.example",
            settlement_account_ref="ACH-PEER-1",
            street_address="1 Peer Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        intake_listing = create_listing(
            owner_bundle.seller,
            street_address="2 Peer Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        assert intake_listing["listing_status"] == "INTAKE"

        stranger = create_seller(
            org_name="Peer Stranger Bank",
            seller_type="BANK",
            contact_email="reo@peerstranger.example",
            settlement_account_ref="ACH-PEER-2",
        )

        event = create_event(
            title="Peer Event",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )
        lot = add_lot(
            event["id"],
            owner_bundle.listing_id,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        set_clock("2026-09-15T17:05:00Z")
        open_event(event["id"])
        set_clock("2026-09-15T18:05:00Z")
        unsold = close_lot(lot["id"], OPS_CLOSER)
        assert unsold["lot_status"] == "CLOSED_NO_SALE"
        assert read_listing(owner_bundle.listing_id)["listing_status"] == "UNSOLD"

        stranger_headers = make_seller_headers(stranger["id"])
        validate_error(
            api_client.file_disclosures(
                intake_listing["id"],
                disclosures_payload("OWNER_OCCUPIED", "CLOUDED"),
                stranger_headers,
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.relist_asset_listing(
                owner_bundle.listing_id, relist_payload(), stranger_headers
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.create_asset_listing(
                create_asset_listing_payload(
                    owner_bundle.seller_id,
                    street_address="3 Peer Rd",
                    city="Oakland",
                    estimated_value_cents=26000000,
                ),
                stranger_headers,
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )

        still_raw = read_listing(intake_listing["id"])
        assert still_raw["listing_status"] == "INTAKE"
        assert still_raw["occupancy_status"] == "UNKNOWN"

        relisted = validate_success(
            api_client.relist_asset_listing(
                owner_bundle.listing_id,
                relist_payload(),
                make_seller_headers(owner_bundle.seller_id),
            )
        )
        assert relisted["listing_status"] == "DISCLOSURE_READY"

        _, stranger_meta = validate_paginated(
            api_client.list_seller_asset_listings(stranger["id"], ADMIN)
        )
        assert stranger_meta["total_count"] == 0

        _, owner_meta = validate_paginated(
            api_client.list_seller_asset_listings(owner_bundle.seller_id, ADMIN)
        )
        assert owner_meta["total_count"] == 2
