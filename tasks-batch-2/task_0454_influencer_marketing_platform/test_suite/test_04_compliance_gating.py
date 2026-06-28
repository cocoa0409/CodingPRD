"""Compliance and money gates: brand safety, FTC disclosure, W-9, budget,
exclusivity, priority conflicts, cross-entity state dependencies.

Queue A: cross_entity_state_dependency, priority_pair_validation_conflict.
Queue B: validations / errors corner instances for the same gates.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_admin_headers, make_compliance_headers, make_brand_headers, make_creator_headers,
    ApiErrorId,
    create_brand, create_creator, create_clean_creator, create_open_campaign, open_offer,
    accept_offer_by_creator, open_brand_safety_flag,
    setup_active_contract, setup_pending_payout,
    set_clock,
)

ADMIN = make_admin_headers()
COMPLIANCE = make_compliance_headers()


class TestBrandSafetyGate:
    def test_sign_blocked_by_blocked_creator(self, api):
        """PRD §3.5: "The brand-safety gate rejects a sign against a BLOCKED creator with
        ERR_BRAND_SAFETY_BLOCKED."

        Accepted offer for a creator with an OPEN HIGH flag (BLOCKED) -> sign rejected.

        Design: Difficulty/cross_entity_state_dependency/contract_sign_blocked_by_creator_brand_safety
        """
        brand = create_brand(budget_cents=1_000_000)
        creator = create_clean_creator()
        campaign, _ = create_open_campaign(brand["id"], base_rate_cents=60_000)
        offer = open_offer(brand["id"], campaign["id"], creator["id"], current_amount_cents=60_000)
        accepted = accept_offer_by_creator(offer, creator["id"])
        open_brand_safety_flag(creator["id"], severity="HIGH", reason_code="HATE_SPEECH")
        bh = make_brand_headers(brand["id"])
        resp = api.create_contract(
            {"offer_id": offer["id"], "expected_offer_version": accepted["version"]}, bh)
        validate_error(resp, ApiErrorId.ERR_BRAND_SAFETY_BLOCKED.value)

    def test_sign_allowed_once_blocking_flag_resolved(self, api):
        """PRD §3.5: "the creator must not be BLOCKED on brand safety".
        PRD §3.10: "resolving the last HIGH flag lifts a BLOCKED creator back to FLAGGED or
        CLEAR as the remaining open severities dictate."

        Same Contract->Creator dependency, complement direction: once the HIGH flag is resolved
        (creator no longer BLOCKED) the previously-blocked sign succeeds.

        Design: Difficulty/cross_entity_state_dependency/contract_sign_blocked_by_creator_brand_safety
        """
        brand = create_brand(budget_cents=1_000_000)
        creator = create_clean_creator()
        campaign, _ = create_open_campaign(brand["id"], base_rate_cents=60_000)
        offer = open_offer(brand["id"], campaign["id"], creator["id"], current_amount_cents=60_000)
        accepted = accept_offer_by_creator(offer, creator["id"])
        flag = open_brand_safety_flag(creator["id"], severity="HIGH", reason_code="HATE_SPEECH")
        bh = make_brand_headers(brand["id"])
        blocked = api.create_contract(
            {"offer_id": offer["id"], "expected_offer_version": accepted["version"]}, bh)
        validate_error(blocked, ApiErrorId.ERR_BRAND_SAFETY_BLOCKED.value)
        get_success_data(api.resolve_brand_safety_flag(flag["id"], COMPLIANCE))
        contract = validate_success(api.create_contract(
            {"offer_id": offer["id"], "expected_offer_version": accepted["version"]}, bh),
            expected_status=201)
        assert contract["status"] == "ACTIVE"


class TestCrossEntityStateDependency:
    def test_start_review_fails_after_contract_cancel_rejects_submission(self, api):
        """PRD §3.5: "every non-terminal content submission on the contract is forced to
        REJECTED."
        PRD §2.10: "a transition attempted from a state where it is not defined surfaces as
        ERR_INVALID_STATE before the concurrency and business checks run."

        Submission created while ACTIVE; contract cancelled (forces REJECTED); start-review on
        the now-REJECTED submission -> ERR_INVALID_STATE.

        Design: Difficulty/cross_entity_state_dependency/start_review_requires_contract_active
        """
        ctx = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000)
        bh = make_brand_headers(ctx["brand"]["id"])
        ch = make_creator_headers(ctx["creator"]["id"])
        sub = get_success_data(api.create_content_submission(
            {"deliverable_id": ctx["deliverable"]["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/n0", "caption": "x"}, ch))
        kv = get_success_data(api.get_contract(ctx["contract"]["id"], bh))["version"]
        get_success_data(api.cancel_contract(
            ctx["contract"]["id"], {"expected_contract_version": kv}, bh))
        sub_after = get_success_data(api.get_content_submission(sub["id"], COMPLIANCE))
        assert sub_after["status"] == "REJECTED"
        resp = api.start_review(sub["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_contract_cancel_forces_submission_rejected(self, api):
        """PRD §3.5: "every non-terminal content submission on the contract is forced to
        REJECTED."

        ContentSubmission->Contract dependency, isolating the cascade hop: cancelling the
        ACTIVE contract forces its SUBMITTED submission to terminal REJECTED.

        Design: Difficulty/cross_entity_state_dependency/start_review_requires_contract_active
        """
        ctx = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000)
        bh = make_brand_headers(ctx["brand"]["id"])
        ch = make_creator_headers(ctx["creator"]["id"])
        sub = get_success_data(api.create_content_submission(
            {"deliverable_id": ctx["deliverable"]["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/cx", "caption": "x"}, ch))
        assert sub["status"] == "SUBMITTED"
        kv = get_success_data(api.get_contract(ctx["contract"]["id"], bh))["version"]
        get_success_data(api.cancel_contract(
            ctx["contract"]["id"], {"expected_contract_version": kv}, bh))
        after = get_success_data(api.get_content_submission(sub["id"], COMPLIANCE))
        assert after["status"] == "REJECTED"


class TestValidationPriorityConflicts:
    def test_approve_invalid_state_beats_brand_safety(self, api):
        """PRD §2.10: "Only after all of those pass does the system evaluate state-machine
        legality (ERR_INVALID_STATE), then optimistic-concurrency version matching (the
        stale-version codes above), and finally the domain-specific business checks (turn
        order, round caps, brand safety, disclosure, exclusivity, budget, and the rest)".

        Approve on a SUBMITTED (not IN_REVIEW) submission while creator is BLOCKED ->
        ERR_INVALID_STATE wins over the later brand-safety business check.

        Design: Difficulty/priority_pair_validation_conflict/approve_invalid_state_beats_brand_safety_block
        """
        ctx = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000)
        ch = make_creator_headers(ctx["creator"]["id"])
        sub = get_success_data(api.create_content_submission(
            {"deliverable_id": ctx["deliverable"]["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/p1", "caption": "x"}, ch))
        open_brand_safety_flag(ctx["creator"]["id"], severity="HIGH", reason_code="FRAUD_SIGNAL")
        # Submission is still SUBMITTED (review never started).
        resp = api.approve_content(sub["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_approve_in_review_blocked_surfaces_brand_safety(self, api):
        """PRD §2.10: "Only after all of those pass does the system evaluate state-machine
        legality (ERR_INVALID_STATE) ... and finally the domain-specific business checks (turn
        order, round caps, brand safety, disclosure, exclusivity, budget, and the rest)".
        PRD §3.6: "The creator must not be BLOCKED on brand safety, or approval is rejected
        with ERR_BRAND_SAFETY_BLOCKED."

        Complement of the priority pair: once the state check passes (IN_REVIEW), the same
        BLOCKED creator surfaces the later business-safety check ERR_BRAND_SAFETY_BLOCKED.

        Design: Difficulty/priority_pair_validation_conflict/approve_invalid_state_beats_brand_safety_block
        """
        ctx = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000)
        ch = make_creator_headers(ctx["creator"]["id"])
        sub = get_success_data(api.create_content_submission(
            {"deliverable_id": ctx["deliverable"]["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/p2", "caption": "x"}, ch))
        get_success_data(api.start_review(sub["id"], COMPLIANCE))
        open_brand_safety_flag(ctx["creator"]["id"], severity="HIGH", reason_code="FRAUD_SIGNAL")
        resp = api.approve_content(sub["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_BRAND_SAFETY_BLOCKED.value)

    def test_sign_exclusivity_beats_budget(self, api):
        """PRD §2.10: "and finally the domain-specific business checks (turn order, round
        caps, brand safety, disclosure, exclusivity, budget, and the rest) described in §3."

        Second sign for same creator both overlaps an exclusivity window AND exceeds budget;
        exclusivity (priority 13) is checked before budget (18) -> ERR_EXCLUSIVITY_CONFLICT.

        Design: Difficulty/priority_pair_validation_conflict/sign_exclusivity_temporal_beats_budget_fiscal
        """
        set_clock("2026-02-01T00:00:00Z")
        brand = create_brand(budget_cents=100_000)
        creator = create_clean_creator()
        bh = make_brand_headers(brand["id"])
        ch = make_creator_headers(creator["id"])
        # First contract: 90000c with 30-day exclusivity, fully commits budget.
        camp1, _ = create_open_campaign(brand["id"], base_rate_cents=90_000,
                                        campaign_budget_cents=100_000, title="K1",
                                        starts_at="2026-02-01T00:00:00Z",
                                        ends_at="2026-02-20T00:00:00Z", content_type="STORY")
        off1 = open_offer(brand["id"], camp1["id"], creator["id"],
                          current_amount_cents=90_000, exclusivity_days=30)
        off1acc = accept_offer_by_creator(off1, creator["id"])
        get_success_data(api.create_contract(
            {"offer_id": off1["id"], "expected_offer_version": off1acc["version"]}, bh))
        # Second offer: same creator, 90000c (exceeds remaining 10000), overlapping exclusivity.
        camp2, _ = create_open_campaign(brand["id"], base_rate_cents=90_000,
                                        campaign_budget_cents=100_000, title="K2",
                                        starts_at="2026-04-01T00:00:00Z",
                                        ends_at="2026-04-20T00:00:00Z", content_type="STORY")
        off2 = open_offer(brand["id"], camp2["id"], creator["id"],
                          current_amount_cents=90_000, exclusivity_days=30)
        off2acc = accept_offer_by_creator(off2, creator["id"])
        resp = api.create_contract(
            {"offer_id": off2["id"], "expected_offer_version": off2acc["version"]}, bh)
        validate_error(resp, ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value)

    def test_sign_budget_only_surfaces_budget_when_no_exclusivity_overlap(self, api):
        """PRD §3.5: "The budget gate rejects a sign that would push the brand's commitments
        past its budget — that is, when available_budget_cents is less than the offer amount —
        with ERR_BUDGET_EXCEEDED".
        PRD §3.5: "a zero-length window (when exclusivity_days is 0, so start equals end) never
        conflicts with anything."

        Complement of the priority pair: with the exclusivity check satisfied (zero-length
        windows), the over-budget second sign surfaces the fiscal error ERR_BUDGET_EXCEEDED
        rather than an exclusivity error.

        Design: Difficulty/priority_pair_validation_conflict/sign_exclusivity_temporal_beats_budget_fiscal
        """
        brand = create_brand(budget_cents=100_000)
        creator = create_clean_creator()
        bh = make_brand_headers(brand["id"])
        # First contract: 90000c, exclusivity 0 (no window), commits most of budget.
        camp1, _ = create_open_campaign(brand["id"], base_rate_cents=90_000,
                                        campaign_budget_cents=100_000, title="BO1",
                                        starts_at="2026-02-01T00:00:00Z",
                                        ends_at="2026-02-20T00:00:00Z", content_type="STORY")
        off1 = open_offer(brand["id"], camp1["id"], creator["id"],
                          current_amount_cents=90_000, exclusivity_days=0)
        off1acc = accept_offer_by_creator(off1, creator["id"])
        get_success_data(api.create_contract(
            {"offer_id": off1["id"], "expected_offer_version": off1acc["version"]}, bh))
        # Second offer: 90000c (only 10000 remaining), exclusivity 0 -> no overlap possible.
        camp2, _ = create_open_campaign(brand["id"], base_rate_cents=90_000,
                                        campaign_budget_cents=100_000, title="BO2",
                                        starts_at="2026-04-01T00:00:00Z",
                                        ends_at="2026-04-20T00:00:00Z", content_type="STORY")
        off2 = open_offer(brand["id"], camp2["id"], creator["id"],
                          current_amount_cents=90_000, exclusivity_days=0)
        off2acc = accept_offer_by_creator(off2, creator["id"])
        resp = api.create_contract(
            {"offer_id": off2["id"], "expected_offer_version": off2acc["version"]}, bh)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)


class TestComplianceGatesCorner:
    def test_approve_without_ftc_disclosure_rejected(self, api):
        """PRD §3.6: "If the parent campaign's requires_ftc_disclosure is true, the
        submission's has_ftc_disclosure must be true, or approval is rejected with
        ERR_FTC_DISCLOSURE_MISSING."

        Design: Corner/validations/approve_without_ftc_disclosure_rejected
        """
        ctx = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000,
                                    requires_ftc_disclosure=True)
        ch = make_creator_headers(ctx["creator"]["id"])
        sub = get_success_data(api.create_content_submission(
            {"deliverable_id": ctx["deliverable"]["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/fm", "caption": "no tag here"}, ch))
        get_success_data(api.start_review(sub["id"], COMPLIANCE))
        resp = api.approve_content(sub["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_FTC_DISCLOSURE_MISSING.value)

    def test_release_payout_without_w9_rejected(self, api):
        """PRD §3.9: "the creator's tax_id_on_file must be true (otherwise ERR_W9_REQUIRED)".

        Design: Corner/errors/release_payout_without_w9_returns_w9_required
        """
        ctx = setup_pending_payout(offer_amount_cents=80_000, creator_tax_id_on_file=False,
                                   content_type="VIDEO")
        resp = api.release_payout(ctx["payout"]["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_W9_REQUIRED.value)

    def test_sign_over_budget_rejected(self, api):
        """PRD §3.5: "The budget gate rejects a sign that would push the brand's commitments
        past its budget — that is, when available_budget_cents is less than the offer amount —
        with ERR_BUDGET_EXCEEDED".

        Brand budget 50000c; an accepted 80000c offer (no exclusivity conflict) -> rejected.

        Design: Corner/errors/sign_over_budget_returns_budget_exceeded
        """
        brand = create_brand(budget_cents=50_000)
        creator = create_clean_creator()
        campaign, _ = create_open_campaign(brand["id"], base_rate_cents=80_000,
                                           campaign_budget_cents=90_000)
        offer = open_offer(brand["id"], campaign["id"], creator["id"], current_amount_cents=80_000)
        accepted = accept_offer_by_creator(offer, creator["id"])
        bh = make_brand_headers(brand["id"])
        resp = api.create_contract(
            {"offer_id": offer["id"], "expected_offer_version": accepted["version"]}, bh)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)

    def test_deliverable_contract_campaign_mismatch_rejected(self, api):
        """PRD §3.6: "The deliverable and the contract must belong to the same campaign — the
        deliverable's campaign must equal the contract's campaign — or the submission is
        rejected with ERR_DELIVERABLE_CONTRACT_MISMATCH."

        Contract on campaign A; submission tries a deliverable from campaign B -> rejected.

        Design: Corner/validations/deliverable_contract_campaign_mismatch_rejected
        """
        ctx = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000,
                                    campaign_budget_cents=200_000)
        bh = make_brand_headers(ctx["brand"]["id"])
        ch = make_creator_headers(ctx["creator"]["id"])
        # Campaign B (different campaign, same brand) with its own deliverable; no contract on B.
        campB, delB = create_open_campaign(
            ctx["brand"]["id"], base_rate_cents=60_000, title="B",
            starts_at="2026-05-01T00:00:00Z", ends_at="2026-05-20T00:00:00Z",
            content_type="REEL")
        resp = api.create_content_submission(
            {"deliverable_id": delB["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/mm", "caption": "x"}, ch)
        validate_error(resp, ApiErrorId.ERR_DELIVERABLE_CONTRACT_MISMATCH.value)

    def test_conversion_revenue_on_non_sale_rejected(self, api):
        """PRD §3.7: "Revenue may only be attached to a sale: revenue_cents must be 0 for any
        batch whose event_type is not SALE, and a positive revenue on a non-sale batch is
        rejected with ERR_REVENUE_ON_NON_SALE."

        Design: Corner/calculations/conversion_revenue_on_non_sale_rejected
        """
        ctx = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000)
        asset = create_attribution_asset = get_success_data(api.create_attribution_asset(
            {"contract_id": ctx["contract"]["id"], "asset_type": "TRACKING_LINK",
             "code_or_slug": "rv-link"}, make_brand_headers(ctx["brand"]["id"])))
        resp = api.create_conversion(
            asset["id"], {"event_type": "IMPRESSION", "count": 1000, "revenue_cents": 500}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REVENUE_ON_NON_SALE.value)

    def test_duplicate_enabled_promo_code_rejected(self, api):
        """PRD §3.7: "The code_or_slug must be non-empty and must be unique among all assets
        currently in ENABLED status; a collision is rejected with ERR_DUPLICATE_VALUE."

        Two ACTIVE contracts; the second reuses the first's ENABLED promo code -> rejected.

        Design: Corner/errors/duplicate_enabled_promo_code_returns_duplicate_value
        """
        ctx1 = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000)
        bh1 = make_brand_headers(ctx1["brand"]["id"])
        get_success_data(api.create_attribution_asset(
            {"contract_id": ctx1["contract"]["id"], "asset_type": "PROMO_CODE",
             "code_or_slug": "SAVE20"}, bh1))
        ctx2 = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000)
        bh2 = make_brand_headers(ctx2["brand"]["id"])
        resp = api.create_attribution_asset(
            {"contract_id": ctx2["contract"]["id"], "asset_type": "PROMO_CODE",
             "code_or_slug": "SAVE20"}, bh2)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VALUE.value)

    def test_duplicate_payout_rejected(self, api):
        """PRD §3.9: "Only one live payout may exist per contract: if a payout already exists
        for the contract in PENDING, RELEASED, or SETTLED status, the create is rejected with
        ERR_PAYOUT_ALREADY_EXISTS."

        Design: Corner/endpoints/duplicate_payout_returns_payout_already_exists
        """
        ctx = setup_pending_payout(offer_amount_cents=80_000, content_type="VIDEO")
        kv2 = get_success_data(api.get_contract(ctx["contract"]["id"], COMPLIANCE))["version"]
        resp = api.create_payout(
            {"contract_id": ctx["contract"]["id"], "expected_contract_version": kv2}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_PAYOUT_ALREADY_EXISTS.value)
