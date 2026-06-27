"""Temporal overlap rules, compensating invariants, optimistic concurrency,
and derived-field reconciliation.

Queue A: resource_temporal_overlap, compensating_invariant.
Queue B: cross_cutting_complexity_layers (OCC, derived field), consistency_model.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_admin_headers, make_compliance_headers, make_brand_headers, make_creator_headers,
    ApiErrorId,
    create_brand, create_creator, create_clean_creator, create_open_campaign, open_offer,
    accept_offer_by_creator, open_brand_safety_flag,
    setup_active_contract, setup_fulfilled_contract,
    set_clock,
)

ADMIN = make_admin_headers()
COMPLIANCE = make_compliance_headers()


class TestTemporalOverlap:
    def test_exclusivity_halfopen_overlap_rejected(self, api):
        """PRD §3.5: "exclusivity windows are half-open intervals [exclusivity_start,
        exclusivity_end), and two windows conflict only when the first starts before the
        second ends and the second starts before the first ends."
        PRD §3.5: "A conflict is rejected with ERR_EXCLUSIVITY_CONFLICT."

        First contract holds [2026-02-01, 2026-02-11) (10 days). A second signed at clock
        2026-02-05 with 10-day exclusivity -> [2026-02-05, 2026-02-15) overlaps -> rejected.

        Design: Difficulty/resource_temporal_overlap/creator_exclusivity_halfopen_overlap_adjacency_ok
        """
        set_clock("2026-02-01T00:00:00Z")
        brand = create_brand(budget_cents=1_000_000)
        creator = create_clean_creator()
        bh = make_brand_headers(brand["id"])
        camp1, _ = create_open_campaign(brand["id"], base_rate_cents=40_000,
                                        campaign_budget_cents=100_000, title="X1",
                                        starts_at="2026-02-01T00:00:00Z",
                                        ends_at="2026-02-28T00:00:00Z", content_type="STORY")
        off1 = open_offer(brand["id"], camp1["id"], creator["id"],
                          current_amount_cents=40_000, exclusivity_days=10)
        off1acc = accept_offer_by_creator(off1, creator["id"])
        con1 = get_success_data(api.create_contract(
            {"offer_id": off1["id"], "expected_offer_version": off1acc["version"]}, bh))
        assert con1["exclusivity_start"].startswith("2026-02-01T00:00:00")
        assert con1["exclusivity_end"].startswith("2026-02-11T00:00:00")

        camp2, _ = create_open_campaign(brand["id"], base_rate_cents=40_000,
                                        campaign_budget_cents=100_000, title="X2",
                                        starts_at="2026-05-01T00:00:00Z",
                                        ends_at="2026-05-28T00:00:00Z", content_type="STORY")
        off2 = open_offer(brand["id"], camp2["id"], creator["id"],
                          current_amount_cents=40_000, exclusivity_days=10)
        off2acc = accept_offer_by_creator(off2, creator["id"])
        set_clock("2026-02-05T00:00:00Z")
        resp = api.create_contract(
            {"offer_id": off2["id"], "expected_offer_version": off2acc["version"]}, bh)
        validate_error(resp, ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value)

    def test_exclusivity_zero_length_window_never_conflicts(self, api):
        """PRD §3.5: "a zero-length window (when exclusivity_days is 0, so start equals end)
        never conflicts with anything."
        PRD §3.5: "when the exclusivity-day count is 0 the end equals the start, producing an
        empty window."

        Two contracts for the same creator both with exclusivity_days 0 sign successfully —
        the empty window never collides.

        Design: Difficulty/resource_temporal_overlap/creator_exclusivity_halfopen_overlap_adjacency_ok
        """
        set_clock("2026-02-01T00:00:00Z")
        brand = create_brand(budget_cents=1_000_000)
        creator = create_clean_creator()
        bh = make_brand_headers(brand["id"])
        camp1, _ = create_open_campaign(brand["id"], base_rate_cents=40_000,
                                        campaign_budget_cents=100_000, title="Z1",
                                        starts_at="2026-02-01T00:00:00Z",
                                        ends_at="2026-02-28T00:00:00Z", content_type="STORY")
        off1 = open_offer(brand["id"], camp1["id"], creator["id"],
                          current_amount_cents=40_000, exclusivity_days=0)
        off1acc = accept_offer_by_creator(off1, creator["id"])
        con1 = get_success_data(api.create_contract(
            {"offer_id": off1["id"], "expected_offer_version": off1acc["version"]}, bh))
        assert con1["exclusivity_start"] == con1["exclusivity_end"]
        camp2, _ = create_open_campaign(brand["id"], base_rate_cents=40_000,
                                        campaign_budget_cents=100_000, title="Z2",
                                        starts_at="2026-05-01T00:00:00Z",
                                        ends_at="2026-05-28T00:00:00Z", content_type="STORY")
        off2 = open_offer(brand["id"], camp2["id"], creator["id"],
                          current_amount_cents=40_000, exclusivity_days=0)
        off2acc = accept_offer_by_creator(off2, creator["id"])
        con2 = validate_success(api.create_contract(
            {"offer_id": off2["id"], "expected_offer_version": off2acc["version"]}, bh),
            expected_status=201)
        assert con2["status"] == "ACTIVE"

    def test_campaign_window_buffer_overlap_rejected(self, api):
        """PRD §3.3: "expand each existing non-cancelled campaign's window by seven days on
        both ends, and reject the open if the new window intersects any expanded window —
        meaning bare adjacency is rejected and a gap of at least seven days is required between
        windows. A violation is rejected with ERR_CAMPAIGN_WINDOW_CONFLICT."

        First OPEN campaign [2026-02-01, 2026-02-15); a second [2026-02-18, 2026-03-01) is only
        3 days after (< 7-day buffer) -> opening rejected.

        Design: Difficulty/resource_temporal_overlap/campaign_window_buffer_overlap_adjacency_rejected
        """
        brand = create_brand(budget_cents=1_000_000)
        bh = make_brand_headers(brand["id"])
        camp1, _ = create_open_campaign(brand["id"], base_rate_cents=40_000,
                                        campaign_budget_cents=100_000, title="W1",
                                        starts_at="2026-02-01T00:00:00Z",
                                        ends_at="2026-02-15T00:00:00Z", content_type="STORY")
        # Second DRAFT campaign 3 days after the first's window end.
        from test_helpers import create_draft_campaign
        camp2, _ = create_draft_campaign(brand["id"], with_deliverable=True,
                                         campaign_budget_cents=100_000, title="W2",
                                         starts_at="2026-02-18T00:00:00Z",
                                         ends_at="2026-03-01T00:00:00Z", content_type="STORY",
                                         base_rate_cents=40_000)
        resp = api.open_campaign(
            camp2["id"], {"expected_campaign_version": camp2["version"]}, bh)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_CONFLICT.value)

    def test_campaign_window_with_seven_day_gap_opens(self, api):
        """PRD §3.3: "expand each existing non-cancelled campaign's window by seven days on
        both ends, and reject the open if the new window intersects any expanded window —
        meaning bare adjacency is rejected and a gap of at least seven days is required between
        windows."

        First OPEN campaign [2026-02-01, 2026-02-15); a second starting exactly 7 days later
        [2026-02-22, 2026-03-08) clears the buffer and opens successfully.

        Design: Difficulty/resource_temporal_overlap/campaign_window_buffer_overlap_adjacency_rejected
        """
        from test_helpers import create_draft_campaign
        brand = create_brand(budget_cents=1_000_000)
        bh = make_brand_headers(brand["id"])
        create_open_campaign(brand["id"], base_rate_cents=40_000,
                             campaign_budget_cents=100_000, title="G1",
                             starts_at="2026-02-01T00:00:00Z",
                             ends_at="2026-02-15T00:00:00Z", content_type="STORY")
        camp2, _ = create_draft_campaign(brand["id"], with_deliverable=True,
                                         campaign_budget_cents=100_000, title="G2",
                                         starts_at="2026-02-22T00:00:00Z",
                                         ends_at="2026-03-08T00:00:00Z", content_type="STORY",
                                         base_rate_cents=40_000)
        opened = validate_success(api.open_campaign(
            camp2["id"], {"expected_campaign_version": camp2["version"]}, bh))
        assert opened["status"] == "OPEN"


class TestCompensatingInvariants:
    def test_sign_then_cancel_conserves_brand_committed(self, api):
        """PRD §3.5: "Signing also debits budget: the brand's committed_cents increases by the
        contracted rate and its available_budget_cents is recomputed, and the campaign's
        committed_cents increases by the same amount."
        PRD §3.5: "the brand's and campaign's committed_cents are reduced by the contracted
        rate (and available_budget_cents recomputed)".

        Sign debits committed 70000 (available 30000); cancel credits it back to committed 0,
        available 100000, campaign committed 0 (no drift).

        Design: Difficulty/compensating_invariant/contract_sign_then_cancel_conserves_brand_committed
        """
        brand = create_brand(budget_cents=100_000)
        creator = create_clean_creator()
        campaign, _ = create_open_campaign(brand["id"], base_rate_cents=70_000,
                                           campaign_budget_cents=100_000)
        offer = open_offer(brand["id"], campaign["id"], creator["id"], current_amount_cents=70_000)
        accepted = accept_offer_by_creator(offer, creator["id"])
        bh = make_brand_headers(brand["id"])
        contract = get_success_data(api.create_contract(
            {"offer_id": offer["id"], "expected_offer_version": accepted["version"]}, bh))
        cancelled = validate_success(api.cancel_contract(
            contract["id"], {"expected_contract_version": contract["version"]}, bh))
        assert cancelled["status"] == "CANCELLED"
        brand_after = get_success_data(api.get_brand(brand["id"], bh))
        assert brand_after["committed_cents"] == 0
        assert brand_after["available_budget_cents"] == 100000
        camp_after = get_success_data(api.get_campaign(campaign["id"], bh))
        assert camp_after["committed_cents"] == 0

    def test_sign_then_cancel_restores_available_budget_for_resign(self, api):
        """PRD §3.5: "the brand's and campaign's committed_cents are reduced by the contracted
        rate (and available_budget_cents recomputed)".
        PRD §2.7: "its available_budget_cents is budget_cents minus committed_cents".

        After sign+cancel the available_budget_cents is fully restored to budget (100000),
        evidencing no residual commitment from the cancelled contract.

        Design: Difficulty/compensating_invariant/contract_sign_then_cancel_conserves_brand_committed
        """
        brand = create_brand(budget_cents=100_000)
        creator = create_clean_creator()
        campaign, _ = create_open_campaign(brand["id"], base_rate_cents=70_000,
                                           campaign_budget_cents=100_000)
        offer = open_offer(brand["id"], campaign["id"], creator["id"], current_amount_cents=70_000)
        accepted = accept_offer_by_creator(offer, creator["id"])
        bh = make_brand_headers(brand["id"])
        contract = get_success_data(api.create_contract(
            {"offer_id": offer["id"], "expected_offer_version": accepted["version"]}, bh))
        # Before cancel, available is debited.
        mid = get_success_data(api.get_brand(brand["id"], bh))
        assert mid["available_budget_cents"] == 30000
        validate_success(api.cancel_contract(
            contract["id"], {"expected_contract_version": contract["version"]}, bh))
        after = get_success_data(api.get_brand(brand["id"], bh))
        assert after["available_budget_cents"] == 100000

    def test_flag_open_then_resolve_conserves_posture(self, api):
        """PRD §3.10: "A new flag is OPEN, and opening it immediately recomputes the creator's
        brand_safety_status over all that creator's open flags — a single HIGH open flag forces
        BLOCKED".
        PRD §3.10: "Resolving an OPEN flag moves it OPEN → RESOLVED and recomputes the
        creator's brand_safety_status over the remaining open flags — resolving the last HIGH
        flag lifts a BLOCKED creator back to FLAGGED or CLEAR as the remaining open severities
        dictate."

        Open a HIGH flag (BLOCKED) then resolve it -> posture back to CLEAR (no drift).

        Design: Difficulty/compensating_invariant/brand_safety_flag_open_then_resolve_conserves_posture
        """
        creator = create_creator()
        flag = open_brand_safety_flag(creator["id"], severity="HIGH", reason_code="NSFW", note="temp")
        blocked = get_success_data(api.get_creator(creator["id"], COMPLIANCE))
        assert blocked["brand_safety_status"] == "BLOCKED"
        resolved = validate_success(api.resolve_brand_safety_flag(flag["id"], COMPLIANCE))
        assert resolved["status"] == "RESOLVED"
        creator_after = get_success_data(api.get_creator(creator["id"], COMPLIANCE))
        assert creator_after["brand_safety_status"] == "CLEAR"

    def test_resolve_last_high_flag_lifts_blocked_posture(self, api):
        """PRD §3.10: "resolving the last HIGH flag lifts a BLOCKED creator back to FLAGGED or
        CLEAR as the remaining open severities dictate."
        PRD §2.11: "BLOCKED when at least one OPEN flag has severity HIGH."

        A creator BLOCKED by a single HIGH flag is no longer BLOCKED after that flag resolves.

        Design: Difficulty/compensating_invariant/brand_safety_flag_open_then_resolve_conserves_posture
        """
        creator = create_creator()
        flag = open_brand_safety_flag(creator["id"], severity="HIGH", reason_code="MISINFORMATION")
        assert get_success_data(api.get_creator(creator["id"], COMPLIANCE))["brand_safety_status"] == "BLOCKED"
        validate_success(api.resolve_brand_safety_flag(flag["id"], COMPLIANCE))
        after = get_success_data(api.get_creator(creator["id"], COMPLIANCE))
        assert after["brand_safety_status"] != "BLOCKED"


class TestOptimisticConcurrency:
    def test_stale_offer_counter_rejected(self, api):
        """PRD §2.9: "Countering an offer must carry expected_offer_version, and it must match
        the target offer's current version."
        PRD §2.9: "If the opposite side has already advanced the offer (for instance by
        countering, which bumps the offer's version and flips whose turn it is) since the
        client last read it, the counter is rejected with ERR_STALE_OFFER_VERSION (HTTP 412)
        rather than silently appending a round on top of a board the actor never saw."

        After the creator counters (advancing the offer version), a brand counter carrying the
        pre-counter version is rejected.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_offer_counter_returns_412
        """
        brand = create_brand(budget_cents=1_000_000)
        creator = create_creator()
        campaign, _ = create_open_campaign(brand["id"], base_rate_cents=60_000,
                                           campaign_budget_cents=300_000)
        offer = open_offer(brand["id"], campaign["id"], creator["id"], current_amount_cents=60_000)
        ch = make_creator_headers(creator["id"])
        bh = make_brand_headers(brand["id"])
        o1 = validate_success(api.counter_offer(
            offer["id"], {"counter_amount_cents": 70000,
                          "expected_offer_version": offer["version"]}, ch))
        stale_version = o1["version"] - 1
        resp = api.counter_offer(
            offer["id"], {"counter_amount_cents": 65000,
                          "expected_offer_version": stale_version}, bh)
        validate_error(resp, ApiErrorId.ERR_STALE_OFFER_VERSION.value)

    def test_stale_contract_payout_rejected(self, api):
        """PRD §2.9: "Creating a payout must carry expected_contract_version, and it must match
        the target contract's current version."
        PRD §2.9: "a create that carries the pre-payout version is rejected with
        ERR_STALE_CONTRACT_VERSION (HTTP 412) so the second create cannot open a duplicate
        payout."

        A FULFILLED contract; a payout-create carrying one-less-than-current version is rejected.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_payout_returns_412
        """
        ctx = setup_fulfilled_contract(offer_amount_cents=80_000, content_type="VIDEO")
        stale_version = ctx["contract_version"] - 1
        resp = api.create_payout(
            {"contract_id": ctx["contract"]["id"], "expected_contract_version": stale_version},
            COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)


class TestDerivedFieldAndConsistency:
    def test_committed_recomputed_immediately_on_sign(self, api):
        """PRD §2.7: "A brand's committed_cents is the sum of contracted_rate_cents across that
        brand's contracts whose status is ACTIVE, FULFILLED, or SETTLED, and its
        available_budget_cents is budget_cents minus committed_cents; both are recomputed on
        contract signing and on contract cancellation."
        PRD §3.5: "if the parent campaign was OPEN, signing the first contract bubbles it up
        OPEN → ACTIVE."

        After signing a 70000c contract on a 100000c-budget brand: committed 70000,
        available 30000, campaign committed 70000, campaign ACTIVE.

        Design: Corner/cross_cutting_complexity_layers/brand_committed_recompute_on_sign_derived_field
        """
        brand = create_brand(budget_cents=100_000)
        creator = create_clean_creator()
        campaign, _ = create_open_campaign(brand["id"], base_rate_cents=70_000,
                                           campaign_budget_cents=100_000)
        offer = open_offer(brand["id"], campaign["id"], creator["id"], current_amount_cents=70_000)
        accepted = accept_offer_by_creator(offer, creator["id"])
        bh = make_brand_headers(brand["id"])
        get_success_data(api.create_contract(
            {"offer_id": offer["id"], "expected_offer_version": accepted["version"]}, bh))
        brand_after = get_success_data(api.get_brand(brand["id"], bh))
        assert brand_after["committed_cents"] == 70000
        assert brand_after["available_budget_cents"] == 30000
        camp_after = get_success_data(api.get_campaign(campaign["id"], bh))
        assert camp_after["committed_cents"] == 70000
        assert camp_after["status"] == "ACTIVE"

    def test_signed_contract_visible_in_same_response(self, api):
        """PRD §3.5: "On a successful sign, a contract is created in ACTIVE status with several
        frozen and stamped fields. Its contracted_rate_cents is frozen from the offer's
        current_amount_cents".

        POST /contracts returns the frozen contracted_rate_cents (60000) and ACTIVE status.

        Design: Corner/consistency_model/signed_contract_visible_in_same_response
        """
        brand = create_brand(budget_cents=1_000_000)
        creator = create_clean_creator()
        campaign, _ = create_open_campaign(brand["id"], base_rate_cents=60_000)
        offer = open_offer(brand["id"], campaign["id"], creator["id"], current_amount_cents=60_000)
        accepted = accept_offer_by_creator(offer, creator["id"])
        bh = make_brand_headers(brand["id"])
        resp = api.create_contract(
            {"offer_id": offer["id"], "expected_offer_version": accepted["version"]}, bh)
        contract = validate_success(resp, expected_status=201)
        assert contract["contracted_rate_cents"] == 60000
        assert contract["status"] == "ACTIVE"
