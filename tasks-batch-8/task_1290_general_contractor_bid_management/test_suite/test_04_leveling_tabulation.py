"""Leveling adjustments and their pinned rounding, the leveling lock
lifecycle, tabulation compliance disqualifications, and low-bid ranking."""
from test_helpers import (
    LEAD,
    ApiErrorId,
    acknowledge_addendum,
    add_leveling_adjustment,
    advance_clock,
    approve_application,
    assert_leveling_adjustment,
    close_bidding,
    create_bid_package,
    draft_recommendation,
    get_bid,
    get_leveling_sheet,
    get_package,
    invite,
    issue_addendum,
    publish_package,
    register_subcontractor,
    respond_bidding,
    setup_closed_package_with_bids,
    setup_published_with_bidders,
    submit_bid,
    submit_prequal_application,
    submit_recommendation,
    tabulate,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

AFTER_DUE = "2026-08-10T15:00:00Z"


class TestPerAdjustmentRoundingOrder:

    def test_pct_adjustments_rounded_individually_then_summed(self):
        """PRD §3.7: "When `pct_of_base` is given, the resolved figure is the
        product of the bid's current `base_bid_cents` and `pct_of_base`,
        rounded half-up to integer cents — and this per-adjustment rounding
        happens before any summation."
        PRD §3.7: "Sum-then-round — totaling fractional products and rounding
        once — is explicitly rejected; each percentage adjustment is rounded to
        integer cents individually and only then summed."

        Design: Difficulty/combinatorial_formula/leveled_amount_per_adjustment_rounding_order
        """
        ctx = setup_closed_package_with_bids((101,), name="Rounding Package")
        bid = ctx["bids"][0]
        # Bond for base 101: round_half_up(101 * 0.05) = 5, covered by fixture.
        adj_1 = add_leveling_adjustment(bid["id"], treatment="GC_ALLOWANCE",
                                        pct_of_base=0.025,
                                        description="allowance A1")
        adj_2 = add_leveling_adjustment(bid["id"], treatment="SUB_QUOTE",
                                        pct_of_base=0.025,
                                        description="sub quote A2")
        # round_half_up(101 * 0.025) = round_half_up(2.525) = 3, each.
        assert adj_1["resolved_amount_cents"] == 3
        assert adj_2["resolved_amount_cents"] == 3

        sheet = validate_success(api_client.get_leveling_sheet(bid["id"], LEAD))
        # 101 + 3 + 3 = 107; sum-then-round would give 106.
        assert sheet["leveled_amount_cents"] == 107
        assert sheet["leveled_amount_cents"] != 106

    def test_excluded_scope_contributes_zero_but_sets_flag(self):
        """PRD §3.7: "An adjustment whose `treatment` is `EXCLUDED_SCOPE`
        always contributes 0 to the leveled total regardless of its price
        fields, but its presence matters: it sets the leveling sheet's
        exclusion flag."
        PRD §3.7: "The **leveled amount** of a bid is then the bid's
        `base_bid_cents` plus the sum of the `resolved_amount_cents` of every
        adjustment on the bid whose treatment is `GC_ALLOWANCE` or
        `SUB_QUOTE`."

        Design: Difficulty/combinatorial_formula/leveled_amount_per_adjustment_rounding_order
        """
        ctx = setup_closed_package_with_bids((101,), name="Rounding Package")
        bid = ctx["bids"][0]
        add_leveling_adjustment(bid["id"], treatment="GC_ALLOWANCE",
                                pct_of_base=0.025, description="allowance A1")
        add_leveling_adjustment(bid["id"], treatment="SUB_QUOTE",
                                pct_of_base=0.025, description="sub quote A2")
        adj_3 = add_leveling_adjustment(bid["id"], treatment="EXCLUDED_SCOPE",
                                        amount_cents=999_999,
                                        description="excluded scope line")

        sheet = validate_success(api_client.get_leveling_sheet(bid["id"], LEAD))
        assert sheet["leveled_amount_cents"] == 107, \
            "the 999,999-cent EXCLUDED_SCOPE line contributes 0 to the total"
        assert sheet["has_exclusions"] is True, \
            "its presence still sets the exclusion flag"


class TestLevelingTotalConservation:

    def test_add_adjustment_moves_leveled_total(self):
        """PRD §3.7: "When `amount_cents` is given, `resolved_amount_cents` is
        that figure verbatim."
        PRD §3.7: "Creating an adjustment computes its
        `resolved_amount_cents`; editing one (any of `description`,
        `treatment`, `amount_cents`, `pct_of_base`) recomputes it; deleting one
        restores the bid's leveled total by removal."

        Design: Difficulty/compensating_invariant/leveling_adjustment_add_delete_conserves_leveled_total
        """
        ctx = setup_closed_package_with_bids((1_000_000,),
                                             name="Leveling Package")
        bid = ctx["bids"][0]
        baseline = get_leveling_sheet(bid["id"])
        assert baseline["leveled_amount_cents"] == 1_000_000

        adj = add_leveling_adjustment(bid["id"], treatment="GC_ALLOWANCE",
                                      amount_cents=50_000,
                                      description="temp bracing allowance")
        assert_leveling_adjustment(adj)
        assert adj["resolved_amount_cents"] == 50_000
        after_add = get_leveling_sheet(bid["id"])
        assert after_add["leveled_amount_cents"] == 1_050_000

    def test_add_then_delete_restores_leveled_total_exactly(self):
        """PRD §3.7: "The **leveled amount** of a bid is then the bid's
        `base_bid_cents` plus the sum of the `resolved_amount_cents` of every
        adjustment on the bid whose treatment is `GC_ALLOWANCE` or
        `SUB_QUOTE`."
        PRD §3.7: "Creating an adjustment computes its
        `resolved_amount_cents`; editing one (any of `description`,
        `treatment`, `amount_cents`, `pct_of_base`) recomputes it; deleting one
        restores the bid's leveled total by removal."

        Design: Difficulty/compensating_invariant/leveling_adjustment_add_delete_conserves_leveled_total
        """
        ctx = setup_closed_package_with_bids((1_000_000,),
                                             name="Leveling Package")
        bid = ctx["bids"][0]
        adj = add_leveling_adjustment(bid["id"], treatment="GC_ALLOWANCE",
                                      amount_cents=50_000,
                                      description="temp bracing allowance")
        assert get_leveling_sheet(bid["id"])["leveled_amount_cents"] == 1_050_000

        resp = api_client.delete_leveling_adjustment(adj["id"], LEAD)
        assert resp.status_code == 204, \
            f"deletion returns 204, got {resp.status_code}"
        after = get_leveling_sheet(bid["id"])
        assert after["leveled_amount_cents"] == 1_000_000, \
            "add + delete must conserve the leveled total with no drift"
        rows, meta = validate_paginated(
            api_client.list_bid_leveling_adjustments(bid["id"], LEAD))
        assert rows == [] and meta["total_count"] == 0


class TestApparentVsLeveledDivergence:

    def _setup_divergent_pair(self):
        """X base 1.0M (+250k allowance), Y base 1.1M; bidding closed."""
        ctx = setup_closed_package_with_bids((1_000_000, 1_100_000),
                                             name="Tower A — Structural Steel")
        bid_x, bid_y = ctx["bids"]
        add_leveling_adjustment(
            bid_x["id"], treatment="GC_ALLOWANCE", amount_cents=250_000,
            description="X excludes temporary bracing — GC allowance")
        return ctx, bid_x, bid_y

    def test_apparent_low_ignores_leveling(self):
        """PRD §3.8: "The apparent low bidder is the compliant bid with the
        smallest `base_bid_cents` — the raw bid-day number, ignoring leveling
        entirely."
        PRD §3.8: "The sweep writes `compliant_bid_count` and both
        `apparent_low_bid_id` and `leveled_low_bid_id` onto the package and
        moves it `BIDDING_CLOSED → TABULATED`."

        Design: Difficulty/dual_variant_calc/apparent_vs_leveled_low_bid_divergence
        """
        ctx, bid_x, bid_y = self._setup_divergent_pair()
        pkg = tabulate(ctx["package"]["id"])
        assert pkg["status"] == "TABULATED"
        assert pkg["compliant_bid_count"] == 2
        assert pkg["apparent_low_bid_id"] == bid_x["id"], \
            "raw bases 1,000,000 < 1,100,000: X is the apparent low"

    def test_leveled_low_differs_from_apparent_low(self):
        """PRD §3.8: "The leveled low bidder is the compliant bid with the
        smallest leveled amount as computed in §3.7 — and because leveling
        moves numbers, the leveled low bidder may be a different firm than the
        apparent low bidder on the identical bid set."

        Design: Difficulty/dual_variant_calc/apparent_vs_leveled_low_bid_divergence
        """
        ctx, bid_x, bid_y = self._setup_divergent_pair()
        pkg = tabulate(ctx["package"]["id"])
        assert pkg["leveled_low_bid_id"] == bid_y["id"], \
            "leveled 1,100,000 < 1,250,000: Y is the leveled low"
        assert pkg["apparent_low_bid_id"] != pkg["leveled_low_bid_id"]
        # The per-bid leveled totals behind the ranking.
        assert get_leveling_sheet(bid_x["id"])["leveled_amount_cents"] == 1_250_000
        assert get_leveling_sheet(bid_y["id"])["leveled_amount_cents"] == 1_100_000


class TestRankingTieBreak:

    def test_identical_amounts_break_tie_by_earliest_submission(self):
        """PRD §3.8: "Both orderings break ties identically: the earlier
        `submitted_at` wins; a further tie is broken by the earlier
        `created_at`."

        Design: Corner/calculations/ranking_tie_break_by_earliest_submission
        """
        ctx = setup_published_with_bidders(n=2, name="Tie Package")
        pkg = ctx["package"]
        sub_x = ctx["bidders"][0]["subcontractor"]
        sub_y = ctx["bidders"][1]["subcontractor"]

        advance_clock("2026-08-05T10:00:00Z")
        bid_x = submit_bid(pkg["id"], sub_x["id"], 1_000_000)
        advance_clock("2026-08-05T11:00:00Z")
        bid_y = submit_bid(pkg["id"], sub_y["id"], 1_000_000)

        advance_clock(AFTER_DUE)
        close_bidding(pkg["id"])
        pkg = tabulate(pkg["id"])
        assert pkg["compliant_bid_count"] == 2
        assert pkg["apparent_low_bid_id"] == bid_x["id"], \
            "tie on base: earlier submitted_at (10:00 < 11:00) wins"
        assert pkg["leveled_low_bid_id"] == bid_x["id"]


class TestTabulationDisqualifications:

    def test_missing_addendum_ack_disqualifies_bid(self):
        """PRD §3.8: "Each bid is checked against two disqualifiers, in a
        pinned order: first the addendum-acknowledgment check — if any
        `PENDING` acknowledgment exists for the pairing of the package and the
        bid's subcontractor, the bid is disqualified with
        `disqualification_reason` set to `MISSING_ADDENDUM_ACK`; ..."
        PRD §3.8: "The sweep writes `compliant_bid_count` and both
        `apparent_low_bid_id` and `leveled_low_bid_id` onto the package and
        moves it `BIDDING_CLOSED → TABULATED`."

        Design: Corner/state_machines/tabulation_disqualifies_missing_addendum_ack
        """
        ctx = setup_published_with_bidders(n=2, name="DQ Package")
        pkg = ctx["package"]
        sub_x = ctx["bidders"][0]["subcontractor"]
        sub_y = ctx["bidders"][1]["subcontractor"]
        bid_x = submit_bid(pkg["id"], sub_x["id"], 1_000_000)
        bid_y = submit_bid(pkg["id"], sub_y["id"], 900_000)

        add1 = issue_addendum(pkg["id"], "Addendum 1: revised embeds")
        acknowledge_addendum(add1["id"], sub_x["id"])  # Y never acknowledges

        advance_clock(AFTER_DUE)
        close_bidding(pkg["id"])
        pkg = tabulate(pkg["id"])

        bid_y_now = get_bid(bid_y["id"])
        assert bid_y_now["status"] == "DISQUALIFIED"
        assert bid_y_now["disqualification_reason"] == "MISSING_ADDENDUM_ACK"
        assert get_bid(bid_x["id"])["status"] == "SUBMITTED"
        assert pkg["compliant_bid_count"] == 1
        assert pkg["apparent_low_bid_id"] == bid_x["id"], \
            "Y's lower base 900,000 is excluded by disqualification"
        assert pkg["leveled_low_bid_id"] == bid_x["id"]

    def test_lapsed_prequal_disqualifies_bid(self):
        """PRD §3.8: "Each bid is checked against two disqualifiers, in a
        pinned order: ... second the prequalification check — if the bid's
        subcontractor holds no application `APPROVED` with `expires_at` in the
        future (lazy expiry applied), the bid is disqualified with
        `disqualification_reason` `PREQUAL_LAPSED`."
        PRD §3.2: "An application whose `expires_at` has been reached
        transitions `APPROVED → EXPIRED` lazily: the transition is applied
        whenever the application is read or consulted for a prequalification
        check and the logical now is at or past `expires_at`, and the firm's
        `current_prequal_status` is recomputed at that moment."

        Design: Corner/state_machines/tabulation_disqualifies_lapsed_prequal
        """
        # X approved 2026-08-01 (window ends 2027-08-01).
        sub_x = register_subcontractor(legal_name="X Lapse LLC",
                                       license_number="LIC-X-2005")
        app_x = submit_prequal_application(sub_x["id"])
        approve_application(app_x["id"])
        # Z approved 2026-09-01 (window ends 2027-09-01).
        advance_clock("2026-09-01T00:00:00Z")
        sub_z = register_subcontractor(legal_name="Z Lapse LLC",
                                       license_number="LIC-Z-2005")
        app_z = submit_prequal_application(sub_z["id"])
        approve_application(app_z["id"])

        pkg = create_bid_package(name="Lapse Package",
                                 bid_due_at="2027-08-20T14:00:00Z")
        inv_x = invite(pkg["id"], sub_x["id"])
        inv_z = invite(pkg["id"], sub_z["id"])
        respond_bidding(inv_x["id"], sub_x["id"])
        respond_bidding(inv_z["id"], sub_z["id"])
        publish_package(pkg["id"])

        advance_clock("2026-09-02T00:00:00Z")
        bid_x = submit_bid(pkg["id"], sub_x["id"], 1_000_000)
        bid_z = submit_bid(pkg["id"], sub_z["id"], 1_100_000)

        advance_clock("2027-08-20T15:00:00Z")  # X's window closed 2027-08-01
        close_bidding(pkg["id"])
        pkg = tabulate(pkg["id"])

        app_x_now = validate_success(
            api_client.get_prequal_application(app_x["id"], LEAD))
        assert app_x_now["status"] == "EXPIRED"
        bid_x_now = get_bid(bid_x["id"])
        assert bid_x_now["status"] == "DISQUALIFIED"
        assert bid_x_now["disqualification_reason"] == "PREQUAL_LAPSED"
        assert get_bid(bid_z["id"])["status"] == "SUBMITTED"
        assert pkg["compliant_bid_count"] == 1
        assert pkg["apparent_low_bid_id"] == bid_z["id"]

    def test_zero_compliant_bids_fails_tabulation_atomically(self):
        """PRD §3.8: "If the compliant set after the sweep is empty, the entire
        tabulate call fails with `ERR_NO_COMPLIANT_BIDS` (HTTP 422) and no
        state changes are applied — no disqualifications persist, no counters
        move, the package stays put."

        Design: Corner/validations/tabulate_with_zero_compliant_bids_rejected
        """
        ctx = setup_published_with_bidders(n=1, name="Zero Package")
        pkg = ctx["package"]
        sub = ctx["bidders"][0]["subcontractor"]
        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)
        issue_addendum(pkg["id"], "Addendum 1 (never acknowledged)")

        advance_clock(AFTER_DUE)
        close_bidding(pkg["id"])
        resp = api_client.tabulate_bid_package(pkg["id"], LEAD)
        validate_error(resp, ApiErrorId.ERR_NO_COMPLIANT_BIDS)

        pkg_now = get_package(pkg["id"])
        assert pkg_now["status"] == "BIDDING_CLOSED", \
            "the failed tabulation leaves the package in place"
        assert pkg_now["compliant_bid_count"] is None
        assert get_bid(bid["id"])["status"] == "SUBMITTED", \
            "no disqualification persists on the atomic failure"



class TestLevelingLockLifecycle:

    def test_leveling_locked_before_close_and_after_recommendation_submit(self):
        """PRD §3.7: "Adjustments may be created, edited, or deleted only while
        the package is `BIDDING_CLOSED` or `TABULATED`; a leveling write while
        the package is `RECOMMENDATION_PENDING` or `AWARDED` — or not yet
        `BIDDING_CLOSED` — is rejected with `ERR_LEVELING_LOCKED` (HTTP 409)."
        PRD §3.9: "Submitting the draft moves the recommendation `DRAFT →
        SUBMITTED` and, in the same motion, moves the package `TABULATED →
        RECOMMENDATION_PENDING`. That package transition locks leveling: from
        this moment, adjustment writes on the package's bids are rejected with
        `ERR_LEVELING_LOCKED`, freezing the numbers the decision will rest on."

        Design: Corner/validations/leveling_locked_before_close_and_after_recommendation
        """
        ctx = setup_published_with_bidders(n=1, name="Level Lock Package")
        pkg = ctx["package"]
        sub = ctx["bidders"][0]["subcontractor"]
        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)

        # While PUBLISHED (not yet BIDDING_CLOSED) leveling is locked.
        resp = api_client.create_leveling_adjustment(
            {"bid_id": bid["id"], "description": "too early",
             "treatment": "GC_ALLOWANCE", "amount_cents": 1_000}, LEAD)
        validate_error(resp, ApiErrorId.ERR_LEVELING_LOCKED)

        advance_clock(AFTER_DUE)
        close_bidding(pkg["id"])
        tabulate(pkg["id"])
        rec, _ = draft_recommendation(pkg["id"], bid["id"],
                                      rationale="only bid")
        submit_recommendation(rec["id"])

        # While RECOMMENDATION_PENDING leveling is locked again.
        resp = api_client.create_leveling_adjustment(
            {"bid_id": bid["id"], "description": "too late",
             "treatment": "GC_ALLOWANCE", "amount_cents": 2_000}, LEAD)
        validate_error(resp, ApiErrorId.ERR_LEVELING_LOCKED)

        rows, _ = validate_paginated(
            api_client.list_bid_leveling_adjustments(bid["id"], LEAD))
        assert rows == [], "no adjustment may persist through either lock"
