"""Investor transfer requests: buyer-onboarding gate, settlement conservation,
exceeds-funded guard, and OCC on subscription version."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_suitability,
    contribution_for,
    create_transfer_request_payload,
    fund_contribution,
    get_offering,
    get_subscription,
    issue_capital_call,
    make_accreditation_verified_subscription,
    make_active_syndication,
    make_draft_subscription,
    make_investor,
    make_investor_headers,
    make_open_offering,
    make_transfer_request,
    setup_funded_offering,
    submit_subscription,
    upload_and_review_documents,
    verify_accreditation,
    validate_error,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_operator_headers"]
AGENT = TEST_USERS["transfer_agent_headers"]


class TestBuyerOnboardingGate:
    def test_agent_approve_rejects_buyer_not_onboarded(self, api):
        """PRD §3.9: "The transfer agent then takes the second gate: the buyer
        must already be onboarded onto the same offering through a separate
        subscription that has reached `ACCREDITATION_VERIFIED` or beyond
        (`ERR_BUYER_NOT_ONBOARDED`)"."

        Design: Difficulty/cross_entity_state_dependency/transfer_approve_requires_buyer_onboarded
        """
        ctx = setup_funded_offering([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        seller_sub = ctx["subs"][0]
        buyer = make_investor(full_legal_name="Buyer NoSub")
        tr = make_transfer_request(syn_id, off_id, seller_sub, buyer["id"],
                                   1_000_000)
        assert tr["status"] == "PENDING_SPONSOR_REVIEW"
        approved = validate_success(api.sponsor_approve_transfer(
            syn_id, off_id, seller_sub["id"], tr["id"], SPONSOR))
        assert approved["status"] == "PENDING_TRANSFER_AGENT"

        resp = api.agent_approve_transfer(syn_id, off_id, seller_sub["id"],
                                          tr["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_BUYER_NOT_ONBOARDED, 422)

    def test_agent_approve_succeeds_for_onboarded_buyer(self, api):
        """PRD §3.9: "the buyer must already be onboarded onto the same
        offering through a separate subscription that has reached
        `ACCREDITATION_VERIFIED` or beyond (`ERR_BUYER_NOT_ONBOARDED`)" and
        "The agent's approval moves the request to `APPROVED`". A buyer whose
        own subscription on the offering is ACCREDITATION_VERIFIED clears the
        gate.

        Design: Difficulty/cross_entity_state_dependency/transfer_approve_requires_buyer_onboarded
        """
        ctx = setup_funded_offering([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        seller_sub = ctx["subs"][0]
        buyer = make_investor(full_legal_name="Buyer Onboarded")
        buyer_sub = make_accreditation_verified_subscription(
            ctx["off"], buyer, 2_000_000, syn_id)
        assert buyer_sub["status"] == "ACCREDITATION_VERIFIED"

        tr = make_transfer_request(syn_id, off_id, seller_sub, buyer["id"],
                                   1_000_000)
        validate_success(api.sponsor_approve_transfer(
            syn_id, off_id, seller_sub["id"], tr["id"], SPONSOR))
        approved = validate_success(api.agent_approve_transfer(
            syn_id, off_id, seller_sub["id"], tr["id"], AGENT))
        assert approved["status"] == "APPROVED"


class TestSettleConservation:
    def test_transfer_settle_conserves_total_funded(self, api):
        """PRD §3.9: "The source subscription's `funded_cents` falls by
        `transfer_cents`, and the buyer's `FUNDED` subscription on the same
        offering gains the same amount, leaving the offering's
        `total_funded_cents` unchanged."

        Design: Difficulty/compensating_invariant/transfer_settle_conserves_total_funded
        """
        ctx = setup_funded_offering([5_000_000, 3_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        seller_sub, buyer_sub = ctx["subs"]
        buyer = ctx["investors"][1]
        assert get_offering(syn_id, off_id)["total_funded_cents"] == 8_000_000

        tr = make_transfer_request(syn_id, off_id, seller_sub, buyer["id"],
                                   2_000_000)
        validate_success(api.sponsor_approve_transfer(
            syn_id, off_id, seller_sub["id"], tr["id"], SPONSOR))
        validate_success(api.agent_approve_transfer(
            syn_id, off_id, seller_sub["id"], tr["id"], AGENT))
        settled = validate_success(api.settle_transfer(
            syn_id, off_id, seller_sub["id"], tr["id"], AGENT))
        assert settled["status"] == "SETTLED"

        seller_now = get_subscription(syn_id, off_id, seller_sub["id"])
        buyer_now = get_subscription(syn_id, off_id, buyer_sub["id"])
        assert seller_now["funded_cents"] == 3_000_000, (
            f"seller funded must fall by transfer_cents: "
            f"{seller_now['funded_cents']}")
        assert buyer_now["funded_cents"] == 5_000_000, (
            f"buyer funded must gain transfer_cents: "
            f"{buyer_now['funded_cents']}")
        assert get_offering(syn_id, off_id)["total_funded_cents"] == 8_000_000, (
            "offering total_funded_cents must be unchanged by settlement")
        assert seller_now["status"] == "FUNDED", (
            "a partial transfer leaves the source subscription FUNDED")

    def test_full_transfer_drains_source_to_withdrawn(self, api):
        """PRD §3.9: "If the transfer drains the source subscription to zero,
        it transitions from `FUNDED` to `WITHDRAWN`, and `settled_at` stamps
        the settlement time." The buyer gains the full amount and the
        offering's `total_funded_cents` is unchanged (same section).

        Design: Difficulty/compensating_invariant/transfer_settle_conserves_total_funded
        """
        ctx = setup_funded_offering([5_000_000, 3_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        seller_sub, buyer_sub = ctx["subs"]
        buyer = ctx["investors"][1]

        tr = make_transfer_request(syn_id, off_id, seller_sub, buyer["id"],
                                   5_000_000)
        validate_success(api.sponsor_approve_transfer(
            syn_id, off_id, seller_sub["id"], tr["id"], SPONSOR))
        validate_success(api.agent_approve_transfer(
            syn_id, off_id, seller_sub["id"], tr["id"], AGENT))
        settled = validate_success(api.settle_transfer(
            syn_id, off_id, seller_sub["id"], tr["id"], AGENT))
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"], "settled_at must stamp the settlement time"

        seller_now = get_subscription(syn_id, off_id, seller_sub["id"])
        assert seller_now["funded_cents"] == 0
        assert seller_now["status"] == "WITHDRAWN"
        assert get_subscription(syn_id, off_id,
                                buyer_sub["id"])["funded_cents"] == 8_000_000
        assert get_offering(syn_id, off_id)["total_funded_cents"] == 8_000_000


class TestTransferGuards:
    def test_transfer_exceeds_funded_rejected(self, api):
        """PRD §3.9: "The sponsor can approve only if the source subscription
        is `FUNDED` (`ERR_SUBSCRIPTION_NOT_FUNDED`) and the requested
        `transfer_cents` is positive and does not exceed the source
        subscription's `funded_cents` (`ERR_TRANSFER_EXCEEDS_FUNDED`);
        approval moves the request to `PENDING_TRANSFER_AGENT`."

        Design: Corner/validations/transfer_exceeds_funded_rejected
        """
        ctx = setup_funded_offering([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        seller_sub = ctx["subs"][0]
        buyer = make_investor(full_legal_name="Tr Buyer")
        tr = make_transfer_request(syn_id, off_id, seller_sub, buyer["id"],
                                   6_000_000)
        assert tr["status"] == "PENDING_SPONSOR_REVIEW"

        resp = api.sponsor_approve_transfer(syn_id, off_id, seller_sub["id"],
                                            tr["id"], SPONSOR)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_EXCEEDS_FUNDED, 422)

    def test_transfer_create_stale_subscription_version(self, api):
        """PRD §2.7: "Creating a transfer request against a subscription
        requires the request body to carry `expected_subscription_version`,
        holding the value of the subscription's `version` the client last
        observed. If another writer has advanced that version in the meantime —
        most commonly because a prior transfer settled and legitimately reduced
        the subscription's `funded_cents` — the create is rejected with
        `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)"."

        Design: Corner/errors/error_stale_subscription_version_on_transfer_create
        """
        syn = make_active_syndication(syndication_name="OccSyn")
        off = make_open_offering(syn["id"], offering_name="Occ Off")
        seller = make_investor(full_legal_name="Occ Seller")
        sub = make_draft_subscription(off, seller, 5_000_000, syn["id"])
        stale_version = sub["version"]

        # Advance the subscription through the review and funding pipeline;
        # every transition moves its version past the observed one.
        upload_and_review_documents(syn["id"], off["id"], sub["id"],
                                    seller["id"])
        submit_subscription(syn["id"], off["id"], sub["id"], seller["id"])
        verify_accreditation(syn["id"], off["id"], sub["id"])
        approve_suitability(syn["id"], off["id"], sub["id"])
        call, contribs = issue_capital_call(syn["id"], off["id"], 5_000_000)
        fund_contribution(syn["id"], off["id"], call["id"],
                          contribution_for(contribs, sub["id"]), seller)
        assert get_subscription(syn["id"], off["id"], sub["id"])["status"] == \
            "FUNDED"

        buyer = make_investor(full_legal_name="Occ Buyer")
        resp = api.create_transfer_request(
            syn["id"], off["id"], sub["id"],
            create_transfer_request_payload(buyer["id"], 1_000_000,
                                            stale_version),
            make_investor_headers(seller["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION, 412)
