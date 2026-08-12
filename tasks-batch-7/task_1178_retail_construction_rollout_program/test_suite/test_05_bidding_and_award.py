"""Bid evaluation modes and responsiveness, award cascades onto wave sites,
bid-window temporal gates, contractor gates, identity ownership, and RBAC."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    award_open_package,
    create_bid_package,
    create_contractor,
    create_market,
    create_site,
    make_gc_vendor_headers,
    open_bid_package,
    open_market_bidding,
    read_bid,
    read_bid_package,
    read_market,
    read_site,
    set_clock,
    setup_program_with_market,
    submit_bid,
    submit_bid_ok,
    validate_error,
    validate_success,
)


def _open_package_ctx(api, evaluation_mode="LOWEST_PRICE",
                      bid_open_at="2026-05-01T00:00:00Z",
                      bid_close_at="2026-05-10T00:00:00Z",
                      max_duration_days=120):
    """Program ACTIVE + market BIDDING + one OPEN package."""
    ctx = setup_program_with_market()
    open_market_bidding(ctx["market"]["id"])
    pkg = create_bid_package(ctx["market"]["id"], evaluation_mode=evaluation_mode,
                             bid_open_at=bid_open_at, bid_close_at=bid_close_at,
                             max_duration_days=max_duration_days)
    open_bid_package(pkg["id"])
    ctx["pkg"] = pkg
    return ctx


class TestBidEvaluationModes:
    def test_bid_evaluation_mode_divergence_same_bids_different_winner(self, api):
        """PRD §3.4: "Under `LOWEST_PRICE`, candidates rank by ascending
        `amount_cents`, ties breaking toward the shorter `duration_days` and
        then the earlier `submitted_at`, and every bid's `evaluation_score`
        stays null. Under `BEST_VALUE`, each candidate's `evaluation_score`
        combines a price component — the lowest candidate amount divided by
        this bid's amount, multiplied by 100, weighted at 70% — with a
        technical component — the bid's `tech_score` weighted at 30% — the sum
        rounded half up to two decimal places; candidates rank by descending
        score, ties breaking toward the lower amount and then the earlier
        submission, so a higher-priced bid with a superior technical score can
        win."

        Design: Difficulty/dual_variant_calc/bid_evaluation_mode_divergence_same_bids_different_winner
        """
        ctx = setup_program_with_market()
        market2 = create_market(ctx["program"]["id"], name="Houston")
        open_market_bidding(ctx["market"]["id"])
        open_market_bidding(market2["id"])
        pkg1 = create_bid_package(ctx["market"]["id"], evaluation_mode="LOWEST_PRICE")
        pkg2 = create_bid_package(market2["id"], evaluation_mode="BEST_VALUE")
        open_bid_package(pkg1["id"])
        open_bid_package(pkg2["id"])
        gc1 = create_contractor()
        gc2 = create_contractor(legal_name="GC Two LLC", license_no="GC-200")

        bid_a1 = submit_bid_ok(pkg1["id"], gc1["id"], amount_cents=8_000_000,
                               duration_days=90, tech_score=60)
        submit_bid_ok(pkg1["id"], gc2["id"], amount_cents=8_500_000,
                      duration_days=80, tech_score=100)
        bid_a2 = submit_bid_ok(pkg2["id"], gc1["id"], amount_cents=8_000_000,
                               duration_days=90, tech_score=60)
        bid_b2 = submit_bid_ok(pkg2["id"], gc2["id"], amount_cents=8_500_000,
                               duration_days=80, tech_score=100)

        pkg1 = award_open_package(pkg1["id"])
        pkg2 = award_open_package(pkg2["id"])

        assert pkg1["awarded_bid_id"] == bid_a1["id"], (
            "LOWEST_PRICE must award the 8000000-cent bid")
        assert pkg2["awarded_bid_id"] == bid_b2["id"], (
            "BEST_VALUE must award the 8500000-cent tech-100 bid")
        # 0.7*(8000000/8000000)*100 + 0.3*60 = 88.00
        assert read_bid(bid_a2["id"])["evaluation_score"] == pytest.approx(88.00, abs=0.005)
        # 0.7*(8000000/8500000)*100 + 0.3*100 = 95.8823... -> 95.88
        assert read_bid(bid_b2["id"])["evaluation_score"] == pytest.approx(95.88, abs=0.005)

    def test_lowest_price_leaves_evaluation_score_null_and_rejects_losers(self, api):
        """PRD §3.4: "Under `LOWEST_PRICE`, candidates rank by ascending
        `amount_cents`, ties breaking toward the shorter `duration_days` and
        then the earlier `submitted_at`, and every bid's `evaluation_score`
        stays null."
        PRD §3.4: "The winning bid moves to `AWARDED` and the package's
        `awarded_bid_id` is pinned to it; every other `SUBMITTED` bid moves to
        `REJECTED`"

        Design: Difficulty/dual_variant_calc/bid_evaluation_mode_divergence_same_bids_different_winner
        """
        ctx = _open_package_ctx(api, evaluation_mode="LOWEST_PRICE")
        gc1 = create_contractor()
        gc2 = create_contractor(legal_name="GC Two LLC", license_no="GC-200")
        bid_win = submit_bid_ok(ctx["pkg"]["id"], gc1["id"], amount_cents=8_000_000,
                                duration_days=90, tech_score=60)
        bid_lose = submit_bid_ok(ctx["pkg"]["id"], gc2["id"], amount_cents=8_500_000,
                                 duration_days=80, tech_score=100)

        award_open_package(ctx["pkg"]["id"])

        bid_win = read_bid(bid_win["id"])
        bid_lose = read_bid(bid_lose["id"])
        assert bid_win["status"] == "AWARDED"
        assert bid_win["evaluation_score"] is None, (
            "LOWEST_PRICE leaves every evaluation_score null")
        assert bid_lose["status"] == "REJECTED"
        assert bid_lose["evaluation_score"] is None


class TestBestValueResponsivenessFilter:
    def test_best_value_responsiveness_filter_nested_min(self, api):
        """PRD §3.4: "The server computes `is_responsive` on each bid: the
        amount must be positive, and the duration must be positive and no
        greater than the package's `max_duration_days`."
        PRD §3.4: "Awarding a closed package requires at least one responsive
        `SUBMITTED` bid, failing with `ERR_NO_RESPONSIVE_BIDS` otherwise."

        Design: Difficulty/combinatorial_formula/best_value_responsiveness_filter_nested_min
        """
        ctx = _open_package_ctx(api, evaluation_mode="BEST_VALUE", max_duration_days=120)
        gc1 = create_contractor()
        gc2 = create_contractor(legal_name="GC Two LLC", license_no="GC-200")
        gc3 = create_contractor(legal_name="GC Three LLC", license_no="GC-300")
        bid_a = submit_bid_ok(ctx["pkg"]["id"], gc1["id"], amount_cents=8_000_000,
                              duration_days=90, tech_score=60)
        bid_c = submit_bid_ok(ctx["pkg"]["id"], gc3["id"], amount_cents=7_500_000,
                              duration_days=150, tech_score=90)
        bid_b = submit_bid_ok(ctx["pkg"]["id"], gc2["id"], amount_cents=8_500_000,
                              duration_days=80, tech_score=100)

        pkg = award_open_package(ctx["pkg"]["id"])

        bid_c = read_bid(bid_c["id"])
        assert bid_c["is_responsive"] is False, "duration 150 exceeds the 120-day cap"
        assert bid_c["status"] == "REJECTED"
        assert pkg["awarded_bid_id"] == bid_b["id"], (
            "the 7500000-cent bid is excluded, so min amount stays 8000000 and the "
            "tech-100 bid wins 95.88")
        assert read_bid(bid_b["id"])["evaluation_score"] == pytest.approx(95.88, abs=0.005)
        assert read_bid(bid_a["id"])["status"] == "REJECTED"

    def test_best_value_min_amount_computed_over_responsive_set_only(self, api):
        """PRD §3.4: "Under `BEST_VALUE`, each candidate's `evaluation_score`
        combines a price component — the lowest candidate amount divided by
        this bid's amount, multiplied by 100, weighted at 70% — with a
        technical component — the bid's `tech_score` weighted at 30% — the sum
        rounded half up to two decimal places"

        Design: Difficulty/combinatorial_formula/best_value_responsiveness_filter_nested_min
        """
        ctx = _open_package_ctx(api, evaluation_mode="BEST_VALUE", max_duration_days=120)
        gc1 = create_contractor()
        gc2 = create_contractor(legal_name="GC Two LLC", license_no="GC-200")
        gc3 = create_contractor(legal_name="GC Three LLC", license_no="GC-300")
        bid_a = submit_bid_ok(ctx["pkg"]["id"], gc1["id"], amount_cents=8_000_000,
                              duration_days=90, tech_score=60)
        submit_bid_ok(ctx["pkg"]["id"], gc3["id"], amount_cents=7_500_000,
                      duration_days=150, tech_score=90)
        submit_bid_ok(ctx["pkg"]["id"], gc2["id"], amount_cents=8_500_000,
                      duration_days=80, tech_score=100)

        award_open_package(ctx["pkg"]["id"])

        # With the non-responsive 7500000-cent bid excluded, min amount is
        # 8000000 and bid A scores 0.7*(8000000/8000000)*100 + 0.3*60 = 88.00.
        # A nested min over ALL bids would score A at 83.63 instead.
        assert read_bid(bid_a["id"])["evaluation_score"] == pytest.approx(88.00, abs=0.005)


class TestAwardCascade:
    def test_award_sets_base_contract_matching_wave_only(self, api):
        """PRD §3.4: "every site whose `market_id` and `phase_wave` match the
        package and which is not yet `OPEN` or `REMOVED` has its
        `base_contract_cents` set to the winning per-store amount"

        Design: Corner/endpoints/c_award_sets_base_contract_matching_wave_only
        """
        ctx = _open_package_ctx(api)
        site1 = create_site(ctx["program"]["id"], ctx["market"]["id"], phase_wave=1)
        site2 = create_site(ctx["program"]["id"], ctx["market"]["id"], phase_wave=2,
                            address="200 Elm St", square_footage=3500,
                            budget_allocation_cents=9_000_000,
                            target_open_date="2026-10-01")
        gc1 = create_contractor()
        submit_bid_ok(ctx["pkg"]["id"], gc1["id"], amount_cents=9_000_000)

        award_open_package(ctx["pkg"]["id"])

        assert read_site(site1["id"])["base_contract_cents"] == 9_000_000
        assert read_site(site2["id"])["base_contract_cents"] == 0, (
            "wave-2 site is untouched by a wave-1 award")

    def test_award_with_no_responsive_bids_rejected(self, api,
                                                    procurement_lead_headers):
        """PRD §3.4: "Awarding a closed package requires at least one
        responsive `SUBMITTED` bid, failing with `ERR_NO_RESPONSIVE_BIDS`
        otherwise."

        Design: Corner/errors/c_award_with_no_responsive_bids_rejected
        """
        ctx = _open_package_ctx(api)
        gc1 = create_contractor()
        submit_bid_ok(ctx["pkg"]["id"], gc1["id"], amount_cents=9_000_000,
                      duration_days=150)
        set_clock("2026-05-10T00:00:00Z")
        validate_success(api.close_bid_package(ctx["pkg"]["id"],
                                               headers=procurement_lead_headers))

        resp = api.award_bid_package(ctx["pkg"]["id"], headers=procurement_lead_headers)
        validate_error(resp, ApiErrorId.ERR_NO_RESPONSIVE_BIDS)
        assert read_bid_package(ctx["pkg"]["id"])["status"] == "CLOSED"


class TestBidSubmissionGates:
    def test_duplicate_bid_same_contractor_rejected(self, api):
        """PRD §3.4: "a contractor may hold only one `SUBMITTED` bid per
        package (`ERR_DUPLICATE_BID`)"

        Design: Corner/validations/c_duplicate_bid_same_contractor_rejected
        """
        ctx = _open_package_ctx(api)
        gc1 = create_contractor()
        submit_bid_ok(ctx["pkg"]["id"], gc1["id"])

        resp = submit_bid(ctx["pkg"]["id"], gc1["id"], amount_cents=8_800_000,
                          duration_days=85, tech_score=85)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BID)

    def test_bid_submit_after_window_closed_rejected(self, api):
        """PRD §3.4: "a submission at or after `bid_close_at` is refused with
        `ERR_BID_WINDOW_CLOSED` even if the package was never formally closed"

        Design: Corner/validations/c_bid_submit_after_window_closed_rejected
        """
        ctx = _open_package_ctx(api)
        gc1 = create_contractor()
        set_clock("2026-05-11T00:00:00Z")

        resp = submit_bid(ctx["pkg"]["id"], gc1["id"])
        validate_error(resp, ApiErrorId.ERR_BID_WINDOW_CLOSED)

    def test_bid_submit_package_not_open_rejected(self, api):
        """PRD §3.4: "the package must be `OPEN` (`ERR_BID_PACKAGE_NOT_OPEN`)"

        Design: Corner/errors/c_bid_submit_package_not_open_rejected
        """
        ctx = setup_program_with_market()
        open_market_bidding(ctx["market"]["id"])
        pkg = create_bid_package(ctx["market"]["id"])  # stays DRAFT
        gc1 = create_contractor()

        resp = submit_bid(pkg["id"], gc1["id"])
        validate_error(resp, ApiErrorId.ERR_BID_PACKAGE_NOT_OPEN)

    def test_suspended_contractor_bid_rejected(self, api, procurement_lead_headers):
        """PRD §3.4: "Suspension moves a contractor from `PREQUALIFIED` to
        `SUSPENDED`, and suspended contractors cannot bid."
        PRD §3.4: "the contractor must be `PREQUALIFIED`
        (`ERR_CONTRACTOR_NOT_PREQUALIFIED`)"

        Design: Corner/errors/c_suspended_contractor_bid_rejected
        """
        ctx = _open_package_ctx(api)
        gc1 = create_contractor()
        validate_success(api.suspend_contractor(gc1["id"],
                                                headers=procurement_lead_headers))

        resp = submit_bid(ctx["pkg"]["id"], gc1["id"])
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_NOT_PREQUALIFIED)

    def test_bid_submit_identity_forbidden(self, api):
        """PRD §3.4: "The `contractor_id` must equal the caller's `X-User-ID`
        (`ERR_FORBIDDEN_IDENTITY`)"

        Design: Corner/errors/c_bid_submit_identity_forbidden
        """
        ctx = _open_package_ctx(api)
        gc1 = create_contractor()
        gc2 = create_contractor(legal_name="GC Two LLC", license_no="GC-200")

        # Caller is gc1 but names gc2's contractor id.
        resp = api.create_bid(
            {"bid_package_id": ctx["pkg"]["id"], "contractor_id": gc2["id"],
             "amount_cents": 9_000_000, "duration_days": 90, "tech_score": 80},
            headers=make_gc_vendor_headers(gc1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_IDENTITY)


class TestPackageWindowGates:
    def test_package_open_before_window_rejected(self, api,
                                                 procurement_lead_headers):
        """PRD §3.4: "Opening it moves `DRAFT` to `OPEN` and requires the
        market to be `BIDDING`, failing with `ERR_MARKET_NOT_BIDDING`
        otherwise, and the clock to have reached `bid_open_at`, failing with
        `ERR_BID_WINDOW_NOT_OPEN` otherwise."

        Design: Corner/errors/c_package_open_before_window_rejected
        """
        ctx = setup_program_with_market()
        open_market_bidding(ctx["market"]["id"])
        pkg = create_bid_package(ctx["market"]["id"],
                                 bid_open_at="2026-05-05T00:00:00Z")

        resp = api.open_bid_package(pkg["id"], headers=procurement_lead_headers)
        validate_error(resp, ApiErrorId.ERR_BID_WINDOW_NOT_OPEN)
        assert read_bid_package(pkg["id"])["status"] == "DRAFT"

    def test_package_open_market_not_bidding_rejected(self, api,
                                                      procurement_lead_headers):
        """PRD §3.4: "Opening it moves `DRAFT` to `OPEN` and requires the
        market to be `BIDDING`, failing with `ERR_MARKET_NOT_BIDDING`
        otherwise, and the clock to have reached `bid_open_at`, failing with
        `ERR_BID_WINDOW_NOT_OPEN` otherwise."

        Design: Corner/errors/c_package_open_market_not_bidding_rejected
        """
        ctx = setup_program_with_market()
        pkg = create_bid_package(ctx["market"]["id"])  # market still REGISTERED

        resp = api.open_bid_package(pkg["id"], headers=procurement_lead_headers)
        validate_error(resp, ApiErrorId.ERR_MARKET_NOT_BIDDING)
        assert read_bid_package(pkg["id"])["status"] == "DRAFT"
        assert read_market(ctx["market"]["id"])["status"] == "REGISTERED"

    def test_package_close_before_window_end_rejected(self, api,
                                                      procurement_lead_headers):
        """PRD §3.4: "Closing moves `OPEN` to `CLOSED` and requires the clock
        to have reached `bid_close_at` (`ERR_BID_WINDOW_STILL_OPEN`)."

        Design: Corner/validations/c_package_close_before_window_end_rejected
        """
        ctx = _open_package_ctx(api)

        resp = api.close_bid_package(ctx["pkg"]["id"], headers=procurement_lead_headers)
        validate_error(resp, ApiErrorId.ERR_BID_WINDOW_STILL_OPEN)
        assert read_bid_package(ctx["pkg"]["id"])["status"] == "OPEN"

    def test_gc_vendor_cannot_award_package(self, api):
        """PRD §2.1: "A request whose role is well-formed but not permitted
        for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: package award is authorized for ProcurementLead.

        Design: Corner/rbac/c_gc_vendor_cannot_award_package
        """
        ctx = _open_package_ctx(api)
        gc1 = create_contractor()
        submit_bid_ok(ctx["pkg"]["id"], gc1["id"])
        set_clock("2026-05-10T00:00:00Z")
        validate_success(api.close_bid_package(
            ctx["pkg"]["id"], headers=TEST_USERS["procurement_lead_headers"]))

        resp = api.award_bid_package(ctx["pkg"]["id"],
                                     headers=make_gc_vendor_headers(gc1["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert read_bid_package(ctx["pkg"]["id"])["status"] == "CLOSED"
