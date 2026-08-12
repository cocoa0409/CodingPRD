"""Listing agreements: creation, activation gating, termination, expiration, and
the broker recommendation selector."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_property,
    create_property_with_certified_appraisal,
    create_marketed_property,
    create_broker,
    create_listing_agreement,
    activate_listing,
    get_property,
    get_listing,
    set_clock,
    create_appraiser,
    create_draft_appraisal,
    submit_appraisal,
    certify_appraisal,
)

ADMIN = TEST_USERS["oreo_admin_headers"]
PM = TEST_USERS["property_manager_headers"]
SPEC = TEST_USERS["oreo_specialist_headers"]


class TestListingOverlap:
    def test_listing_agreement_interior_overlap_rejected(self, api):
        """PRD §3.4: "Half-open mandate intervals on the same property must not
        overlap across agreements whose status is DRAFT or ACTIVE; adjacency —
        one agreement's end_date equal to the next's start_date — is allowed,
        and a genuine overlap is rejected with ERR_LISTING_OVERLAP (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/listing_agreement_half_open_adjacency
        """
        prop = create_property()
        broker = create_broker()
        create_listing_agreement(
            prop["id"],
            broker["id"],
            start_date="2026-06-05",
            end_date="2026-12-05",
            listing_price=450000.00,
        )
        # interior-overlapping second listing [2026-08-01, 2027-02-01)
        resp = api.create_listing_agreement(
            {
                "property_id": prop["id"],
                "broker_id": broker["id"],
                "start_date": "2026-08-01",
                "end_date": "2027-02-01",
                "listing_price": 440000.00,
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_LISTING_OVERLAP)

    def test_listing_agreement_adjacency_accepted(self, api):
        """PRD §3.4: "adjacency — one agreement's end_date equal to the next's
        start_date — is allowed".

        Design: Difficulty/resource_temporal_overlap/listing_agreement_half_open_adjacency
        """
        prop = create_property()
        broker = create_broker()
        create_listing_agreement(
            prop["id"],
            broker["id"],
            start_date="2026-06-05",
            end_date="2026-12-05",
            listing_price=450000.00,
        )
        # adjacent at the boundary: [2026-12-05, 2027-06-05)
        resp = api.create_listing_agreement(
            {
                "property_id": prop["id"],
                "broker_id": broker["id"],
                "start_date": "2026-12-05",
                "end_date": "2027-06-05",
                "listing_price": 440000.00,
            },
            PM,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"


class TestListingActivation:
    def test_activate_listing_moves_property_to_marketed(self, api):
        """PRD §3.4: "When all gates pass, the listing moves to ACTIVE, the
        property moves to MARKETED, active_listing_count is recomputed (now at
        least one), and property.version increments."

        Design: Difficulty/compensating_invariant/activate_then_terminate_preserves_marketing_invariant
        """
        ctx = create_marketed_property()
        prop = ctx["property"]
        listing = ctx["listing"]
        assert prop["lifecycle_status"] == "MARKETED"
        assert prop["active_listing_count"] == 1
        assert listing["status"] == "ACTIVE"

    def test_terminate_restores_pre_action_marketing_posture(self, api):
        """PRD §3.4: "After any of these, active_listing_count is recomputed,
        and if the count reaches zero while the property is MARKETED, the
        property reverts to HELD; both transitions increment property.version."
        Also: "An OREOSpecialist may terminate it manually, which moves it to
        TERMINATED with termination_reason MANUAL."

        Design: Difficulty/compensating_invariant/activate_then_terminate_preserves_marketing_invariant
        """
        prop, appraiser, _a = create_property_with_certified_appraisal()
        broker = create_broker()
        listing = create_listing_agreement(prop["id"], broker["id"])

        # activate
        activate_listing(listing["id"])
        mid = get_property(prop["id"])
        assert mid["lifecycle_status"] == "MARKETED"
        assert mid["active_listing_count"] == 1

        # terminate (compensating action)
        term_resp = api.terminate_listing(listing["id"], SPEC)
        terminated = validate_success(term_resp, expected_status=200)
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_reason"] == "MANUAL"

        end = get_property(prop["id"])
        assert end["lifecycle_status"] == "HELD"
        assert end["active_listing_count"] == 0
        # no monetary drift
        assert end["carrying_value"] == 368000.00

    def test_terminate_draft_listing_returns_invalid_state(self, api):
        """PRD §3.4: "Attempting activation on an agreement that is not in DRAFT
        raises ERR_LISTING_NOT_ACTIVE." Only ACTIVE listings can be terminated;
        per §5, ERR_LISTING_NOT_ACTIVE (409) covers terminate attempted on a
        non-ACTIVE listing.

        Design: Corner/state_machines/terminate_draft_listing_returns_invalid_state
        """
        prop = create_property()
        broker = create_broker()
        listing = create_listing_agreement(prop["id"], broker["id"])
        resp = api.terminate_listing(listing["id"], SPEC)
        validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE)
        # unchanged
        after = get_listing(listing["id"])
        assert after["status"] == "DRAFT"
        assert get_property(prop["id"])["lifecycle_status"] == "HELD"


class TestListingExpiry:
    def test_clock_past_listing_end_expires_agreement_and_reverts_property(self, api):
        """PRD §3.4: "The clock sweep expires it when the clock advances
        strictly beyond end_date, moving it to EXPIRED." and "if the count
        reaches zero while the property is MARKETED, the property reverts to
        HELD".
        PRD §2.9: "every ACTIVE listing whose end_date is strictly before the
        new clock transitions to EXPIRED, which may revert a MARKETED property
        with no remaining active listings back to HELD".

        Design: Corner/state_machines/clock_past_listing_end_expires_agreement_and_reverts_property
        """
        ctx = create_marketed_property(
            listing_start="2026-06-05", listing_end="2026-12-05"
        )
        prop = ctx["property"]
        listing = ctx["listing"]
        # advance past end_date
        set_clock("2026-12-06T00:00:00Z")
        l_after = get_listing(listing["id"])
        assert l_after["status"] == "EXPIRED"
        p_after = get_property(prop["id"])
        assert p_after["lifecycle_status"] == "HELD"
        assert p_after["active_listing_count"] == 0
        # 2026-12-06 <= 2026-06-01 + 335 = 2027-05-02 -> CURRENT
        assert p_after["appraisal_status"] == "CURRENT"


class TestBrokerEligibilityAndRecommendation:
    def test_listing_with_out_of_state_broker_returns_422(self, api):
        """PRD §3.4: "The broker named must be eligible: status ACTIVE and the
        property's state_code present in the broker's coverage_states, else
        ERR_BROKER_NOT_ELIGIBLE (HTTP 422)."

        Design: Corner/validations/listing_with_out_of_state_broker_returns_422
        """
        prop = create_property(state_code="CA")
        broker = create_broker(
            name="Desert Brokers", license_number="LIC-B9", coverage_states=["NV"]
        )
        resp = api.create_listing_agreement(
            {
                "property_id": prop["id"],
                "broker_id": broker["id"],
                "start_date": "2026-06-05",
                "end_date": "2026-12-05",
                "listing_price": 450000.00,
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_BROKER_NOT_ELIGIBLE)

    def test_broker_suspend_blocks_new_listing(self, api):
        """PRD §3.4: "flipping status from ACTIVE to SUSPENDED makes the broker
        ineligible for new listings but leaves its existing ACTIVE listings
        untouched". Combined with the eligibility rule: "else
        ERR_BROKER_NOT_ELIGIBLE (HTTP 422)".

        Design: Corner/state_machines/broker_suspend_blocks_new_listing
        """
        prop = create_property()
        broker = create_broker()
        # suspend the broker
        suspend = api.patch_broker(broker["id"], {"status": "SUSPENDED"}, ADMIN)
        validate_success(suspend, expected_status=200)
        # now a new listing must fail
        resp = api.create_listing_agreement(
            {
                "property_id": prop["id"],
                "broker_id": broker["id"],
                "start_date": "2026-06-05",
                "end_date": "2026-12-05",
                "listing_price": 450000.00,
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_BROKER_NOT_ELIGIBLE)

    def test_broker_recommendation_ranks_eligible_brokers(self, api):
        """PRD §3.4: "The broker-recommendation selector supports listing
        assignment: given a property, it returns the eligible broker pool —
        status ACTIVE and coverage_states including the property's state_code —
        ranked by performance_score descending with nulls last, tie-broken by
        created_at ascending."

        Design: Corner/endpoints/broker_recommendation_ranks_eligible_brokers
        """
        prop = create_property(state_code="CA")
        b1 = create_broker(
            name="Bay Brokers", license_number="LIC-B1", coverage_states=["CA"]
        )
        b2 = create_broker(
            name="Coast Brokers", license_number="LIC-B2", coverage_states=["CA", "OR"]
        )
        b3 = create_broker(
            name="Desert Brokers", license_number="LIC-B3", coverage_states=["NV"]
        )
        resp = api.broker_recommendation(prop["id"], SPEC)
        data = validate_success(resp, expected_status=200)
        # data is a list of brokers (null scores -> tie-break by created_at ASC)
        ids = [b["id"] for b in data]
        assert ids == [b1["id"], b2["id"]]
        assert b3["id"] not in ids

    def test_broker_recommendation_empty_pool_returns_no_eligible(self, api):
        """PRD §3.4: "An empty candidate pool is rejected with
        `ERR_NO_ELIGIBLE_BROKER` (HTTP 422)."

        Design: Corner/endpoints/broker_recommendation_empty_pool_returns_no_eligible
        """
        prop = create_property(
            address="9 Sagebrush Way",
            state_code="NV",
            county="Clark",
            property_type="LAND",
            bpo_value=150000.00,
            foreclosure_debt=148000.00,
        )
        create_broker(coverage_states=["CA"])  # CA-only broker
        resp = api.broker_recommendation(prop["id"], SPEC)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_BROKER)


class TestBrokerReadRole:
    def test_broker_reads_own_listings(self, api):
        """PRD §2.1: "When X-User-Role is Broker, X-User-ID is the id of the
        acting Broker entity; broker reads are scoped to their own record and
        the listings and offers attached to it."
        PRD §3.12: "Every role, including the external Broker, may read."

        Design: Corner/rbac/broker_reads_own_listings
        """
        from test_helpers import make_broker_headers

        ctx = create_marketed_property()
        broker = ctx["broker"]
        listing = ctx["listing"]

        broker_headers = make_broker_headers(broker["id"])
        list_resp = api.list_listing_agreements(
            broker_headers, params={"broker_id": broker["id"]}
        )
        data, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 1
        assert data[0]["id"] == listing["id"]
        assert data[0]["status"] == "ACTIVE"

        # self-read broker record
        self_resp = api.get_broker(broker["id"], broker_headers)
        b = validate_success(self_resp, expected_status=200)
        assert b["license_number"] == "LIC-B1"
