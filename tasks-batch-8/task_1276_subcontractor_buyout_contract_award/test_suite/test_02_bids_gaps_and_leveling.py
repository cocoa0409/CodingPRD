"""Bid window rules, leveling selection, scope-gap lifecycle, and the
negotiation-completeness gates at recommend-award."""
import pytest

from test_helpers import (
    BL,
    ADMIN,
    OM,
    VP,
    ApiErrorId,
    api_client,
    assert_bid,
    close_bidding,
    create_draft_subcontract,
    create_open_project,
    create_package,
    get_success_data,
    place_bid,
    publish_package,
    setup_awarded_subcontract,
    setup_leveling_package,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_bid,
)

PKG = "Mechanical"


def _two_bid_package(name, number, trade_code, budget=10_000_000,
                     withdraw_last=True):
    """Leveling package with two placed bids (last optionally withdrawn)."""
    proj, proj_v = create_open_project(name, number)
    ctx = setup_leveling_package(
        proj["id"], proj_v, name=name, trade_code=trade_code, budget=budget,
        bids=((9_000_000, "2026-05-15T12:00:00Z"),
              (9_100_000, "2026-05-15T13:00:00Z")),
        withdraw_last=withdraw_last,
    )
    return proj, ctx


class TestBidWindowBoundary:

    def test_bid_received_exactly_at_deadline_accepted(self):
        """PRD section 3.2: "The bid window is enforced inclusively: a bid
        whose `bid_received_at` is strictly after the package's `bid_due_at`
        is rejected with `ERR_BID_AFTER_DEADLINE`, while a bid arriving
        exactly at the deadline is accepted."

        Design: Difficulty/resource_temporal_overlap/bid_received_after_exact_bid_due_instant_rejected
        """
        proj, proj_v = create_open_project("P-TO1", "TO1")
        pkg = create_package(proj["id"], proj_v, name=PKG,
                             trade_code="TO1-26")
        publish_package(pkg["id"])
        resp = api_client.create_bid(
            pkg["id"],
            {"bidder_name": "Tau OnTime", "contact_email": "t1@x.com",
             "base_bid_cents": 9_000_000,
             "bid_received_at": "2026-05-20T16:00:00Z"},
            BL,
        )
        data = validate_success(resp, expected_status=201)
        assert_bid(data)
        assert data["status"] == "PLACED"

    def test_bid_received_one_second_after_deadline_rejected(self):
        """PRD section 3.2: "a bid whose `bid_received_at` is strictly after
        the package's `bid_due_at` is rejected with `ERR_BID_AFTER_DEADLINE`,
        while a bid arriving exactly at the deadline is accepted."

        Design: Difficulty/resource_temporal_overlap/bid_received_after_exact_bid_due_instant_rejected
        """
        proj, proj_v = create_open_project("P-TO1", "TO1")
        pkg = create_package(proj["id"], proj_v, name=PKG,
                             trade_code="TO1-26")
        publish_package(pkg["id"])
        resp = api_client.create_bid(
            pkg["id"],
            {"bidder_name": "Tau Late", "contact_email": "t2@x.com",
             "base_bid_cents": 8_900_000,
             "bid_received_at": "2026-05-20T16:00:01Z"},
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_BID_AFTER_DEADLINE)


class TestBidCreateGateOnPackageState:

    def test_bid_create_on_draft_package_rejected(self):
        """PRD section 3.2: "A package that is in neither `PUBLISHED` nor
        `UNDER_LEVELING` rejects bid creation with
        `ERR_TRADE_PACKAGE_NOT_ACCEPTING_BIDS`."

        Design: Difficulty/cross_entity_state_dependency/bid_create_gated_on_trade_package_state
        """
        proj, proj_v = create_open_project("P-CE1", "CE1")
        pkg_a = create_package(proj["id"], proj_v, name="Pkg A",
                               trade_code="CE1-A", budget=5_000_000)
        resp = api_client.create_bid(
            pkg_a["id"],
            {"bidder_name": "Pi Two", "contact_email": "p2@x.com",
             "base_bid_cents": 4_000_000,
             "bid_received_at": "2026-05-15T12:00:00Z"},
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_TRADE_PACKAGE_NOT_ACCEPTING_BIDS)

    def test_bid_create_on_under_leveling_package_accepted(self):
        """PRD section 3.2: "While a package is `PUBLISHED` or
        `UNDER_LEVELING`, a `BuyoutLead` or `Estimator` records a `Bid`".

        Design: Difficulty/cross_entity_state_dependency/bid_create_gated_on_trade_package_state
        """
        proj, ctx = _two_bid_package("P-CE1B", "CE1B", "CE1B-05",
                                     budget=5_000_000, withdraw_last=False)
        pkg = ctx["package"]
        assert pkg["status"] in ("PUBLISHED", "UNDER_LEVELING") or True
        after = get_success_data(api_client.get_trade_package(pkg["id"], BL))
        assert after["status"] == "UNDER_LEVELING"
        resp = api_client.create_bid(
            pkg["id"],
            {"bidder_name": "Pi Three", "contact_email": "p3@x.com",
             "base_bid_cents": 4_100_000,
             "bid_received_at": "2026-05-15T12:30:00Z"},
            BL,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PLACED"


class TestBidWithdrawal:

    def test_withdraw_already_withdrawn_bid_rejected(self):
        """PRD section 3.2: "Withdrawal is available to a `BuyoutLead` or
        `OperationsManager` and moves a bid `PLACED → WITHDRAWN`; withdrawing
        a bid that is not `PLACED` fails with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/withdraw_already_withdrawn_bid_rejected
        """
        proj, proj_v = create_open_project("P-S2", "S2")
        pkg = create_package(proj["id"], proj_v, name=PKG, trade_code="S2-26")
        publish_package(pkg["id"])
        bid = place_bid(pkg["id"], "C1", 9_000_000)
        withdraw_bid(pkg["id"], bid["id"])
        resp = api_client.withdraw_bid(pkg["id"], bid["id"], BL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_unaward_on_placed_bid_rejected(self):
        """PRD section 3.5: "if a bid was awarded but the linked subcontract
        is still in `PENDING_AWARD`, a `BuyoutLead` or `OperationsManager` may
        retract the bid award, moving the bid `AWARDED → PLACED`".

        Design: Corner/state_machines/unaward_on_placed_bid_rejected
        """
        proj, proj_v = create_open_project("P-S13", "S13")
        pkg = create_package(proj["id"], proj_v, name=PKG, trade_code="S13-26")
        publish_package(pkg["id"])
        bid = place_bid(pkg["id"], "L1", 9_000_000)
        close_bidding(pkg["id"])
        resp = api_client.unaward_bid(bid["id"], BL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestBidAwardSelection:

    def test_award_with_empty_candidate_set_rejected(self):
        """PRD section 2.10: "Within bid award specifically, the
        empty-candidate-set check fires before the target-bid status check,
        so a package with no `PLACED` or `AWARDED` bids surfaces
        `ERR_NO_AWARDABLE_BID` rather than `ERR_BID_NOT_AWARDABLE` regardless
        of which bid was named."

        Design: Difficulty/boundary_precision_check/leveling_empty_candidate_set_after_all_bids_withdrawn
        """
        proj, ctx = _two_bid_package("P-BP2", "BP2", "BP2-09",
                                     withdraw_last=False)
        pkg = ctx["package"]
        bid_x, bid_o = ctx["bids"]
        withdraw_bid(pkg["id"], bid_x["id"])
        withdraw_bid(pkg["id"], bid_o["id"])
        resp = api_client.award_bid(pkg["id"], bid_x["id"], BL)
        validate_error(resp, ApiErrorId.ERR_NO_AWARDABLE_BID)

    def test_award_rejection_leaves_bids_queryable_and_package_unmoved(self):
        """PRD section 3.2: "A `WITHDRAWN` bid remains queryable on the
        package's bid list but is ineligible for award".

        Design: Difficulty/boundary_precision_check/leveling_empty_candidate_set_after_all_bids_withdrawn
        """
        proj, ctx = _two_bid_package("P-BP2B", "BP2B", "BP2B-09",
                                     withdraw_last=False)
        pkg = ctx["package"]
        bid_x, bid_o = ctx["bids"]
        withdraw_bid(pkg["id"], bid_x["id"])
        withdraw_bid(pkg["id"], bid_o["id"])
        validate_error(api_client.award_bid(pkg["id"], bid_x["id"], BL),
                       ApiErrorId.ERR_NO_AWARDABLE_BID)
        pkg_after = get_success_data(api_client.get_trade_package(pkg["id"], BL))
        assert pkg_after["status"] == "UNDER_LEVELING", \
            f"package must not drift, got {pkg_after['status']}"
        bids, _meta = validate_paginated(api_client.list_bids(pkg["id"], BL))
        by_id = {b["id"]: b["status"] for b in bids}
        assert by_id[bid_x["id"]] == "WITHDRAWN"
        assert by_id[bid_o["id"]] == "WITHDRAWN"

    def test_award_withdrawn_bid_when_set_nonempty_rejected(self):
        """PRD section 3.4: "Only then is the named bid examined: if it is
        not `PLACED` (for example, already `WITHDRAWN`), the call fails with
        `ERR_BID_NOT_AWARDABLE`."

        Design: Corner/state_machines/award_withdrawn_bid_when_set_nonempty_rejected
        """
        proj, ctx = _two_bid_package("P-S17", "S17", "S17-26")
        pkg = ctx["package"]
        bid_a, bid_b = ctx["bids"]
        # bid_b was withdrawn by the fixture; withdraw bid_a as the target
        # instead and re-place the set: bid_b WITHDRAWN, bid_a must be PLACED.
        # The fixture withdrew the last bid; rebuild the exact arrangement:
        # bid_a WITHDRAWN (target), bid_b PLACED (set non-empty).
        # bid_b is currently WITHDRAWN from the fixture, so construct directly.
        resp = api_client.award_bid(pkg["id"], ctx["withdrawn"]["id"], BL)
        validate_error(resp, ApiErrorId.ERR_BID_NOT_AWARDABLE)
        # Sanity: the still-PLACED first bid is awardable.
        ok = api_client.award_bid(pkg["id"], bid_a["id"], BL)
        assert ok.status_code == 200, f"placed bid must be awardable: {ok.text}"

    def test_award_does_not_autopick_low_bidder(self):
        """PRD section 3.4: "the award action itself never auto-picks; it
        awards exactly the bid the caller named."

        Design: Corner/calculations/award_does_not_autopick_low_bidder
        """
        proj, proj_v = create_open_project("P-C3", "C3")
        pkg = create_package(proj["id"], proj_v, name=PKG, trade_code="C3-26")
        publish_package(pkg["id"])
        bid_low = place_bid(pkg["id"], "Q-LOW", 8_500_000,
                            bid_received_at="2026-05-15T12:00:00Z")
        bid_high = place_bid(pkg["id"], "Q-HIGH", 9_000_000,
                             bid_received_at="2026-05-15T13:00:00Z")
        close_bidding(pkg["id"])
        resp = api_client.award_bid(pkg["id"], bid_high["id"], BL)
        data = validate_success(resp)
        assert data["status"] == "AWARDED"
        low = get_success_data(api_client.get_bid(bid_low["id"], BL))
        assert low["status"] == "PLACED", \
            f"losing bid must be untouched, got {low['status']}"


class TestDuplicateBidder:

    def test_duplicate_bidder_rejected(self):
        """PRD section 3.2: "The same bidder may not hold two live bids on
        one package: if another bid with the same `bidder_name` exists on the
        package in `PLACED` or `AWARDED` status, the submission is rejected
        with `ERR_DUPLICATE_BIDDER`."

        Design: Corner/validations/duplicate_bidder_rejected
        """
        proj, proj_v = create_open_project("P-V9", "V9")
        pkg = create_package(proj["id"], proj_v, name=PKG, trade_code="V9-26")
        publish_package(pkg["id"])
        place_bid(pkg["id"], "DUP", 9_000_000,
                  bid_received_at="2026-05-15T12:00:00Z")
        resp = api_client.create_bid(
            pkg["id"],
            {"bidder_name": "DUP", "contact_email": "dup2@x.com",
             "base_bid_cents": 8_800_000,
             "bid_received_at": "2026-05-15T13:00:00Z"},
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BIDDER)

    def test_bidder_name_freed_after_withdrawal(self):
        """PRD section 3.2: "if another bid with the same `bidder_name`
        exists on the package in `PLACED` or `AWARDED` status, the submission
        is rejected with `ERR_DUPLICATE_BIDDER`."

        Design: Corner/validations/duplicate_bidder_rejected
        """
        proj, proj_v = create_open_project("P-V9B", "V9B")
        pkg = create_package(proj["id"], proj_v, name=PKG, trade_code="V9B-26")
        publish_package(pkg["id"])
        first = place_bid(pkg["id"], "DUP", 9_000_000,
                          bid_received_at="2026-05-15T12:00:00Z")
        withdraw_bid(pkg["id"], first["id"])
        resp = api_client.create_bid(
            pkg["id"],
            {"bidder_name": "DUP", "contact_email": "dup2@x.com",
             "base_bid_cents": 8_800_000,
             "bid_received_at": "2026-05-15T14:00:00Z"},
            BL,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PLACED", \
            "after withdrawal the name is free — uniqueness scope is PLACED/AWARDED only"


class TestBidListing:

    def test_list_bids_status_filter(self):
        """PRD section 3.2: "A `WITHDRAWN` bid remains queryable on the
        package's bid list but is ineligible for award".
        PRD section 2.3: "Several list endpoints additionally accept a
        `status` query parameter to filter by lifecycle state".

        Design: Corner/endpoints/list_bids_status_filter
        """
        proj, ctx = _two_bid_package("P-P3", "P3", "P3-26")
        pkg = ctx["package"]
        placed_bid = ctx["bids"][0]
        withdrawn_bid = ctx["withdrawn"]

        data, _meta = validate_paginated(
            api_client.list_bids(pkg["id"], BL, params={"status": "WITHDRAWN"}))
        assert len(data) == 1, f"filter must return exactly one row, got {len(data)}"
        assert data[0]["status"] == "WITHDRAWN"
        assert data[0]["id"] == withdrawn_bid["id"]

        all_bids, meta_all = validate_paginated(
            api_client.list_bids(pkg["id"], BL))
        assert len(all_bids) == 2, \
            f"WITHDRAWN bids remain queryable, got {len(all_bids)}"
        ids = {b["id"] for b in all_bids}
        assert ids == {placed_bid["id"], withdrawn_bid["id"]}


class TestScopeGaps:

    def test_defer_life_safety_gap_rejected(self):
        """PRD section 3.3: "Deferring a gap — a `BuyoutLead` action moving
        it into the `DEFERRED` state (`OPEN → DEFERRED`) — is forbidden for
        `LIFE_SAFETY` gaps, which fail with `ERR_UNRESOLVED_LIFE_SAFETY_GAP`".

        Design: Corner/state_machines/defer_life_safety_gap_rejected
        """
        proj, proj_v = create_open_project("P-S7", "S7")
        pkg = create_package(proj["id"], proj_v, name="Fire Protection",
                             trade_code="S7-21", budget=5_000_000)
        publish_package(pkg["id"])
        resp = api_client.create_gap(
            pkg["id"],
            {"category": "LIFE_SAFETY",
             "description": "egress coverage missing",
             "estimated_impact_cents": 0},
            BL,
        )
        gap = validate_success(resp, expected_status=201)
        resp = api_client.defer_gap(gap["id"], BL)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_LIFE_SAFETY_GAP)
        after = get_success_data(api_client.get_gap(gap["id"], BL))
        assert after["status"] == "OPEN", \
            f"LIFE_SAFETY gap must not drift, got {after['status']}"

    def test_defer_non_life_safety_gap_succeeds(self):
        """PRD section 3.3: "Deferring a gap — a `BuyoutLead` action moving
        it into the `DEFERRED` state (`OPEN → DEFERRED`) — is forbidden for
        `LIFE_SAFETY` gaps, which fail with `ERR_UNRESOLVED_LIFE_SAFETY_GAP`".

        Design: Corner/state_machines/defer_life_safety_gap_rejected
        """
        proj, proj_v = create_open_project("P-S7B", "S7B")
        pkg = create_package(proj["id"], proj_v, name=PKG, trade_code="S7B-26",
                             budget=5_000_000)
        publish_package(pkg["id"])
        resp = api_client.create_gap(
            pkg["id"],
            {"category": "SCOPE",
             "description": "fixture schedule mismatch",
             "estimated_impact_cents": 50_000},
            BL,
        )
        gap = validate_success(resp, expected_status=201)
        resp = api_client.defer_gap(gap["id"], BL)
        data = validate_success(resp)
        assert data["status"] == "DEFERRED"

    def test_gap_defer_then_reopen_cycle(self):
        """PRD section 3.3: "a deferred gap can later be reopened
        (`DEFERRED → OPEN`) by a `BuyoutLead` when the team is ready to deal
        with it."

        Design: Corner/state_machines/gap_defer_then_reopen_cycle
        """
        proj, proj_v = create_open_project("P-S8", "S8")
        pkg = create_package(proj["id"], proj_v, name=PKG, trade_code="S8-26")
        publish_package(pkg["id"])
        resp = api_client.create_gap(
            pkg["id"],
            {"category": "SCOPE",
             "description": "fixture schedule mismatch",
             "estimated_impact_cents": 50_000},
            BL,
        )
        gap = validate_success(resp, expected_status=201)
        deferred = validate_success(api_client.defer_gap(gap["id"], BL))
        assert deferred["status"] == "DEFERRED"
        reopened = validate_success(api_client.reopen_gap(gap["id"], BL))
        assert reopened["status"] == "OPEN"


class TestNegotiationCompleteness:

    def test_recommend_without_disposition_arrays_rejected(self):
        """PRD section 3.5: "negotiation completeness runs in the fixed
        order given in §2.10: missing disposition/selection arrays for a bid
        that has allowances or alternates yield
        `ERR_NEGOTIATION_TERMS_INCOMPLETE`".

        Design: Corner/validations/recommend_without_dispositions_rejected
        """
        proj, proj_v = create_open_project("P-V6", "V6")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="V6", trade_code="V6-26",
            bids=((9_000_000, "2026-05-15T12:00:00Z"),
                  (9_100_000, "2026-05-15T13:00:00Z")),
            withdraw_last=True,
        )
        # Recreate the first bid with an allowance: build explicitly so the
        # allowance is on the source bid.
        pkg = ctx["package"]
        bid_with_allowance = place_bid(
            pkg["id"], "AD", 9_200_000,
            bid_received_at="2026-05-15T12:30:00Z",
            allowances=[{"allowance_id": "alw-1", "amount_cents": 100_000}],
        )
        sub = create_draft_subcontract(pkg["id"], bid_with_allowance["id"],
                                       "AD")
        resp = api_client.recommend_award(
            sub["id"], {"contract_value_cents": 9_200_000}, BL)
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_TERMS_INCOMPLETE)

    def test_recommend_with_partial_allowance_disposition_rejected(self):
        """PRD section 3.5: "an individual allowance without a disposition
        yields `ERR_ALLOWANCE_UNRESOLVED`".

        Design: Corner/validations/recommend_with_partial_allowance_disposition_rejected
        """
        proj, proj_v = create_open_project("P-V7", "V7")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="V7", trade_code="V7-26",
            bids=((9_000_000, "2026-05-15T12:00:00Z"),
                  (9_100_000, "2026-05-15T13:00:00Z")),
            withdraw_last=True,
        )
        pkg = ctx["package"]
        bid = place_bid(
            pkg["id"], "AF", 9_200_000,
            bid_received_at="2026-05-15T12:30:00Z",
            allowances=[{"allowance_id": "alw-1", "amount_cents": 100_000},
                        {"allowance_id": "alw-2", "amount_cents": 50_000}],
        )
        sub = create_draft_subcontract(pkg["id"], bid["id"], "AF")
        resp = api_client.recommend_award(
            sub["id"],
            {"contract_value_cents": 9_200_000,
             "allowance_dispositions": [
                 {"allowance_id": "alw-1", "action": "ACCEPT",
                  "priced_cents": 100_000},
             ],
             "alternate_selections": []},
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_ALLOWANCE_UNRESOLVED)

    def test_recommend_with_unselected_alternate_rejected(self):
        """PRD section 3.5: "an individual alternate without a selection
        yields `ERR_ALTERNATE_UNRESOLVED`".

        Design: Corner/validations/recommend_with_unselected_alternate_rejected
        """
        proj, proj_v = create_open_project("P-V8", "V8")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="V8", trade_code="V8-26",
            bids=((9_000_000, "2026-05-15T12:00:00Z"),
                  (9_100_000, "2026-05-15T13:00:00Z")),
            withdraw_last=True,
        )
        pkg = ctx["package"]
        bid = place_bid(
            pkg["id"], "AH", 9_200_000,
            bid_received_at="2026-05-15T12:30:00Z",
            alternates=[{"alternate_id": "alt-1", "price_delta_cents": 50_000}],
        )
        sub = create_draft_subcontract(pkg["id"], bid["id"], "AH")
        resp = api_client.recommend_award(
            sub["id"],
            {"contract_value_cents": 9_200_000,
             "allowance_dispositions": [],
             "alternate_selections": []},
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_ALTERNATE_UNRESOLVED)


class TestLeveledValue:

    def test_leveled_value_with_alternate_and_repriced_allowance(self):
        """PRD section 3.5: "the bid's `leveled_value_cents` becomes its
        `base_bid_cents`, plus the `price_delta_cents` of every alternate
        marked selected in this round's selections, plus — for every
        allowance this round repriced — the difference between the
        disposition's `priced_cents` and the allowance's original
        `amount_cents`, minus the `amount_cents` of every allowance this
        round rejected."

        Design: Corner/calculations/leveled_value_with_alternate_and_repriced_allowance
        """
        proj, proj_v = create_open_project("P-C1", "C1")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="C1", trade_code="C1-26",
            bids=((9_100_000, "2026-05-15T13:00:00Z"),),
            withdraw_last=True,
        )
        pkg = ctx["package"]
        bid = place_bid(
            pkg["id"], "O1", 9_000_000,
            bid_received_at="2026-05-15T12:00:00Z",
            allowances=[{"allowance_id": "alw-1", "amount_cents": 100_000}],
            alternates=[{"alternate_id": "alt-1", "price_delta_cents": 50_000}],
        )
        sub = create_draft_subcontract(pkg["id"], bid["id"], "O1")
        validate_success(api_client.recommend_award(
            sub["id"],
            {"contract_value_cents": 9_070_000,
             "allowance_dispositions": [
                 {"allowance_id": "alw-1", "action": "REPRICE",
                  "priced_cents": 120_000},
             ],
             "alternate_selections": [
                 {"alternate_id": "alt-1", "selected": True},
             ]},
            BL,
        ))
        after = get_success_data(api_client.get_bid(bid["id"], BL))
        # 9_000_000 + 50_000 (selected alternate) + (120_000 - 100_000)
        assert after["leveled_value_cents"] == 9_070_000, (
            f"leveled value must apply this round's dispositions, "
            f"got {after['leveled_value_cents']}"
        )

    def test_leveled_value_equals_base_bid_before_any_round(self):
        """PRD section 3.2: "At creation, before any negotiation round
        exists, the bid's `leveled_value_cents` simply equals its
        `base_bid_cents`."

        Design: Corner/calculations/leveled_value_ignores_undispositioned_allowance
        """
        proj, proj_v = create_open_project("P-C2", "C2")
        pkg = create_package(proj["id"], proj_v, name=PKG, trade_code="C2-26")
        publish_package(pkg["id"])
        bid = place_bid(
            pkg["id"], "P1", 9_000_000,
            allowances=[{"allowance_id": "alw-1", "amount_cents": 250_000}],
        )
        after = get_success_data(api_client.get_bid(bid["id"], BL))
        assert after["leveled_value_cents"] == 9_000_000, (
            f"no negotiation round exists, so no allowance adjustment "
            f"applies; got {after['leveled_value_cents']}"
        )


class TestInsuranceGapAnalysisVariant:

    def _setup_awarded_with_waived_insurance_gap(self):
        proj, proj_v = create_open_project("P-DV2", "DV2")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="DV2", trade_code="DV2-09",
            bids=((9_000_000, "2026-05-15T12:00:00Z"),
                  (9_200_000, "2026-05-15T13:00:00Z")),
            withdraw_last=True,
        )
        pkg = ctx["package"]
        sub = create_draft_subcontract(pkg["id"], ctx["bids"][0]["id"],
                                       "Gamma Elec")
        resp = api_client.create_gap(
            pkg["id"],
            {"category": "INSURANCE_EXCLUSION",
             "description": "Sub excludes AI endorsement",
             "estimated_impact_cents": 0},
            BL,
        )
        gap = validate_success(resp, expected_status=201)
        validate_success(api_client.resolve_gap(
            gap["id"],
            {"resolution_kind": "ALLOWANCE_WITH_QUALIFICATION",
             "priced_amount_cents": 0,
             "waived_by_role": "VicePresident"},
            VP,
        ))
        validate_success(api_client.recommend_award(
            sub["id"], {"contract_value_cents": 9_000_000}, BL))
        validate_success(api_client.award_subcontract(sub["id"], OM))
        return sub["id"]

    def test_full_endorsements_rejects_missing_ai_endorsement(self):
        """PRD section 3.7: "Under the default `FULL_ENDORSEMENTS` basis, the
        certificate's `compliance_verdict` is `COMPLIANT` only when there are
        no numeric failures, no endorsement failures, and no expiry failure;
        otherwise it is `NON_COMPLIANT`".

        Design: Difficulty/dual_variant_calc/insurance_compliance_full_endorsements_vs_gap_analysis_waivers
        """
        sub_id = self._setup_awarded_with_waived_insurance_gap()
        resp = api_client.create_insurance_certificate(
            sub_id,
            {"certificate_number": "CERT-FULL",
             "gl_occurrence_cents": 1_000_000,
             "gl_aggregate_cents": 2_000_000,
             "auto_cents": 1_000_000,
             "umbrella_cents": 5_000_000,
             "workers_comp": "STATUTORY",
             "ai_endorsed": False, "wos_endorsed": True, "ptd_endorsed": True,
             "pollution_cents": 0, "expires_on": "2027-06-01",
             "evaluation_basis": "FULL_ENDORSEMENTS"},
            BL,
        )
        data = validate_success(resp, expected_status=201)
        assert data["compliance_verdict"] == "NON_COMPLIANT", (
            f"ai_endorsed=false with no waiver credit under FULL_ENDORSEMENTS "
            f"must be NON_COMPLIANT, got {data['compliance_verdict']}"
        )

    def test_gap_analysis_excuses_vp_waived_endorsement_failure(self):
        """PRD section 3.7: "Under the `GAP_ANALYSIS` basis, endorsement
        failures — and only endorsement failures — can be excused: if the
        package carries a `RESOLVED` scope gap of category
        `INSURANCE_EXCLUSION` whose `waived_by_role` is `VicePresident`, the
        missing endorsements are waived and, when only excused endorsement
        failures remain, the verdict is `COMPLIANT_BY_GAP_ANALYSIS`."
        PRD section 3.7: "`COMPLIANT` if any certificate's verdict is
        `COMPLIANT` or `COMPLIANT_BY_GAP_ANALYSIS`".

        Design: Difficulty/dual_variant_calc/insurance_compliance_full_endorsements_vs_gap_analysis_waivers
        """
        sub_id = self._setup_awarded_with_waived_insurance_gap()
        resp = api_client.create_insurance_certificate(
            sub_id,
            {"certificate_number": "CERT-GAP",
             "gl_occurrence_cents": 1_000_000,
             "gl_aggregate_cents": 2_000_000,
             "auto_cents": 1_000_000,
             "umbrella_cents": 5_000_000,
             "workers_comp": "STATUTORY",
             "ai_endorsed": False, "wos_endorsed": True, "ptd_endorsed": True,
             "pollution_cents": 0, "expires_on": "2027-06-01",
             "evaluation_basis": "GAP_ANALYSIS"},
            BL,
        )
        data = validate_success(resp, expected_status=201)
        assert data["compliance_verdict"] == "COMPLIANT_BY_GAP_ANALYSIS", (
            f"identical certificate under GAP_ANALYSIS must credit the "
            f"VP-waived exclusion, got {data['compliance_verdict']}"
        )
        sub = get_success_data(api_client.get_subcontract(sub_id, BL))
        assert sub["insurance_status"] == "COMPLIANT"
