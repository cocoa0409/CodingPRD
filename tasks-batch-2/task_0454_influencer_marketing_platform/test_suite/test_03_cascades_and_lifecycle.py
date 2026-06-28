"""Transitive cascades: settle -> contract/creator/1099, approve -> fulfill,
contract cancel compensation, campaign cancel cascade.

Queue A: transitive_cascade. Queue B: cascade/compensation corner instances,
contract payout listing endpoint.
"""
import pytest
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    make_admin_headers, make_compliance_headers, make_brand_headers, make_creator_headers,
    create_brand, create_creator, create_open_campaign, open_offer,
    setup_active_contract, setup_released_payout, setup_fulfilled_contract,
    create_attribution_asset,
)

ADMIN = make_admin_headers()
COMPLIANCE = make_compliance_headers()


class TestSettleCascade:
    def test_settle_cascades_contract_creator_campaign_and_1099(self, api):
        """PRD §3.9: "The settle propagates upward: the parent contract bubbles
        FULFILLED → SETTLED; the campaign's actual_spend_cents increases by the payout's
        net_amount_cents; and the creator's ytd_paid_cents increases by the same net amount."
        PRD §3.9: "if the creator's post-update ytd_paid_cents is at or above the 1099
        reporting threshold of $600.00 (60,000 cents) and the creator does not yet have a
        1099 form for the current tax year, a TaxForm1099 is auto-generated in GENERATED status."

        Depth-3 chain from settle: payout SETTLED -> contract SETTLED -> ytd 64000 (>=60000)
        -> 1099 generated; campaign actual_spend 64000.

        Design: Difficulty/transitive_cascade/settle_cascade_to_contract_creator_and_1099
        """
        ctx = setup_released_payout(offer_amount_cents=80_000, content_type="VIDEO")
        settled = validate_success(api.settle_payout(ctx["payout"]["id"], COMPLIANCE))
        assert settled["status"] == "SETTLED"

        contract = get_success_data(api.get_contract(ctx["contract"]["id"], COMPLIANCE))
        assert contract["status"] == "SETTLED"

        creator = get_success_data(api.get_creator(ctx["creator"]["id"], COMPLIANCE))
        assert creator["ytd_paid_cents"] == 64000

        campaign = get_success_data(api.get_campaign(ctx["campaign"]["id"], COMPLIANCE))
        assert campaign["actual_spend_cents"] == 64000

        forms = validate_success(api.list_creator_tax_forms(ctx["creator"]["id"], COMPLIANCE))
        assert len(forms) == 1
        assert forms[0]["total_reported_cents"] == 64000
        assert forms[0]["status"] == "GENERATED"

    def test_settle_bubbles_contract_to_settled(self, api):
        """PRD §3.9: "The settle propagates upward: the parent contract bubbles
        FULFILLED → SETTLED".

        Focused assertion on the first cascade hop: payout SETTLED forces contract SETTLED.

        Design: Difficulty/transitive_cascade/settle_cascade_to_contract_creator_and_1099
        """
        ctx = setup_released_payout(offer_amount_cents=80_000, content_type="VIDEO")
        validate_success(api.settle_payout(ctx["payout"]["id"], COMPLIANCE))
        contract = get_success_data(api.get_contract(ctx["contract"]["id"], COMPLIANCE))
        assert contract["status"] == "SETTLED"


class TestApproveCascade:
    def test_approve_last_deliverable_fulfills_contract(self, api):
        """PRD §3.6: "On a successful approval, if every deliverable of the campaign now has
        an APPROVED submission tied to this contract, the parent contract bubbles up
        ACTIVE → FULFILLED as a side effect".

        Single-deliverable campaign: approving the one submission fulfills the contract.

        Design: Difficulty/transitive_cascade/approve_cascade_last_deliverable_fulfills_contract
        """
        ctx = setup_active_contract(offer_amount_cents=70_000, base_rate_cents=70_000,
                                    requires_ftc_disclosure=True)
        ch = make_creator_headers(ctx["creator"]["id"])
        sub = get_success_data(api.create_content_submission(
            {"deliverable_id": ctx["deliverable"]["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/f0", "caption": "great #ad"}, ch))
        get_success_data(api.start_review(sub["id"], COMPLIANCE))
        approved = validate_success(api.approve_content(sub["id"], COMPLIANCE))
        assert approved["status"] == "APPROVED"
        contract = get_success_data(api.get_contract(ctx["contract"]["id"], COMPLIANCE))
        assert contract["status"] == "FULFILLED"

    def test_approve_sets_submission_approved(self, api):
        """PRD §3.6: "Approval moves a submission IN_REVIEW → APPROVED and is the gate where
        both compliance checks bite."

        The approved submission reaches terminal APPROVED status.

        Design: Difficulty/transitive_cascade/approve_cascade_last_deliverable_fulfills_contract
        """
        ctx = setup_active_contract(offer_amount_cents=70_000, base_rate_cents=70_000,
                                    requires_ftc_disclosure=True)
        ch = make_creator_headers(ctx["creator"]["id"])
        sub = get_success_data(api.create_content_submission(
            {"deliverable_id": ctx["deliverable"]["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/f1", "caption": "great #ad"}, ch))
        get_success_data(api.start_review(sub["id"], COMPLIANCE))
        approved = validate_success(api.approve_content(sub["id"], COMPLIANCE))
        assert approved["status"] == "APPROVED"


class TestCampaignCancelCascade:
    def test_cancel_open_campaign_expires_outstanding_offers(self, api):
        """PRD §3.3: "the transition OPEN → CANCELLED then also cascades down by expiring
        every still-live offer on the campaign — each offer in OFFERED or COUNTERED status
        moves to EXPIRED."

        Cancelling an OPEN campaign with one OFFERED offer -> campaign CANCELLED, offer EXPIRED.

        Design: Corner/state_machines/campaign_cancel_cascades_offers_to_expired
        """
        brand = create_brand(budget_cents=1_000_000)
        creator = create_creator()
        campaign, _ = create_open_campaign(brand["id"], base_rate_cents=60_000)
        offer = open_offer(brand["id"], campaign["id"], creator["id"], current_amount_cents=60_000)
        bh = make_brand_headers(brand["id"])
        cancelled = validate_success(api.cancel_campaign(
            campaign["id"], {"expected_campaign_version": campaign["version"]}, bh))
        assert cancelled["status"] == "CANCELLED"
        offer_after = get_success_data(api.get_offer(offer["id"], bh))
        assert offer_after["status"] == "EXPIRED"


class TestContractCancelCompensation:
    def test_cancel_active_contract_disables_assets_and_rejects_content(self, api):
        """PRD §3.5: "Cancellation transitions the contract ACTIVE → CANCELLED and runs a
        compensating cascade: the brand's and campaign's committed_cents are reduced by the
        contracted rate (and available_budget_cents recomputed), every attribution asset on
        the contract moves from ENABLED to DISABLED, and every non-terminal content submission
        on the contract is forced to REJECTED."

        Design: Corner/state_machines/contract_cancel_disables_attribution_and_rejects_content
        """
        ctx = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000)
        bh = make_brand_headers(ctx["brand"]["id"])
        ch = make_creator_headers(ctx["creator"]["id"])
        asset = create_attribution_asset(ctx["brand"]["id"], ctx["contract"]["id"],
                                         asset_type="PROMO_CODE", code_or_slug="CD10")
        sub = get_success_data(api.create_content_submission(
            {"deliverable_id": ctx["deliverable"]["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/cd0", "caption": "x"}, ch))
        kv = get_success_data(api.get_contract(ctx["contract"]["id"], bh))["version"]
        cancelled = validate_success(api.cancel_contract(
            ctx["contract"]["id"], {"expected_contract_version": kv}, bh))
        assert cancelled["status"] == "CANCELLED"
        asset_after = get_success_data(api.get_attribution_asset(asset["id"], bh))
        assert asset_after["status"] == "DISABLED"
        sub_after = get_success_data(api.get_content_submission(sub["id"], COMPLIANCE))
        assert sub_after["status"] == "REJECTED"


class TestContractPayoutListing:
    def test_list_contract_payouts_returns_created_payout(self, api):
        """PRD §3.9: "Payouts can be fetched and listed per contract."
        PRD §2.8: "Listing children of a parent returns only the rows whose foreign key
        points at that parent."

        A FULFILLED contract's single created payout appears in GET /contracts/{id}/payouts.

        Design: Corner/endpoints/list_contract_payouts_reverse_reachability
        """
        ctx = setup_fulfilled_contract(offer_amount_cents=80_000, content_type="VIDEO")
        payout = get_success_data(api.create_payout(
            {"contract_id": ctx["contract"]["id"],
             "expected_contract_version": ctx["contract_version"]}, COMPLIANCE))
        data, meta = validate_paginated(api.list_contract_payouts(ctx["contract"]["id"], COMPLIANCE))
        assert len(data) == 1
        assert data[0]["id"] == payout["id"]
        assert data[0]["gross_amount_cents"] == 80000
