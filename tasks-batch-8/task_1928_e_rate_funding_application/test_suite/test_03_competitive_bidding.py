"""Competitive bidding: weighted scoring, candidate-pool rules, window edges,
posting lifecycle (PRD §2.4, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    award_posting,
    close_window,
    create_bid_payload,
    get_bid,
    get_posting,
    make_vendor_headers,
    new_posting,
    new_provider_with_headers,
    publish_posting,
    qualify_bid,
    run_select_winner,
    set_clock,
    setup_applicant_base,
    submit_bid,
    validate_error,
    validate_success,
)

CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"  # PRD §2.4 startup instant
FACTOR_WEIGHTS = [
    {"factor_name": "LOCAL_SUPPORT", "weight_pct": 20},
    {"factor_name": "EXPERIENCE", "weight_pct": 20},
]


def _setup_two_bid_award(scores1, scores2, price1=50000, price2=40000):
    """Posting (price weight 60, LOCAL_SUPPORT 20, EXPERIENCE 20) awarded after
    two QUALIFIED bids: B1 from VendorOne, then B2 from VendorTwo."""
    ctx = setup_applicant_base(with_snapshot=False)
    sp1, _ = new_provider_with_headers("VendorOne", "SPIN-001")
    sp2, _ = new_provider_with_headers("VendorTwo", "SPIN-002")
    posting = new_posting(ctx, category="CATEGORY_ONE", description="Internet access",
                          price_weight_pct=60, other_factor_weights=FACTOR_WEIGHTS)
    publish_posting(ctx, posting)
    bids = award_posting(ctx, posting, [
        {"provider": sp1, "price": price1, "scores": scores1},
        {"provider": sp2, "price": price2, "scores": scores2},
    ])
    return ctx, posting, bids


class TestWinningBidScore:
    """Queue A: combinatorial_formula/bid_scoring_weighted_price_primary."""

    def test_weighted_scoring_computes_exact_total_scores(self, api):
        """PRD §3.3: "Each candidate's **price points** are that lowest price
        divided by the candidate's own `eligible_price_cents`, multiplied by the
        posting's `price_weight_pct`, and rounded half up to two decimal places."
        PRD §3.3: "The bid's `total_score` is the sum of price points and factor
        points, rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/bid_scoring_weighted_price_primary
        """
        _, _, (b1, b2) = _setup_two_bid_award(
            [{"factor_name": "LOCAL_SUPPORT", "score": 80},
             {"factor_name": "EXPERIENCE", "score": 90}],
            [{"factor_name": "LOCAL_SUPPORT", "score": 60},
             {"factor_name": "EXPERIENCE", "score": 60}],
        )
        b1, b2 = get_bid(b1["id"]), get_bid(b2["id"])
        # B1: round_half_up(40000/50000*60, 2)=48.00 + 20*80/100=16.00 + 20*90/100=18.00
        assert b1["total_score"] == pytest.approx(82.0, abs=1e-9), (
            f"B1 total_score must be 82.00, got {b1['total_score']}"
        )
        # B2: price_points 60.00 + 12.00 + 12.00
        assert b2["total_score"] == pytest.approx(84.0, abs=1e-9), (
            f"B2 total_score must be 84.00, got {b2['total_score']}"
        )

    def test_lower_priced_bid_wins_despite_weaker_factor_scores(self, api):
        """PRD §3.3: "The winner is the highest `total_score`; ties break to the
        lower `eligible_price_cents`, and further ties to the earlier bid
        `created_at`."
        PRD §3.3: "the winning bid becomes `SELECTED`, every other `QUALIFIED` bid
        becomes `NOT_SELECTED`, and `SUBMITTED` or `DISQUALIFIED` bids are
        untouched."
        PRD §3.3: "Because the price weight must be at least every other factor's
        weight and price points fall away quadratically with relative price,
        non-price factors can only break near-ties — price is structurally
        primary."

        Design: Difficulty/combinatorial_formula/bid_scoring_weighted_price_primary
        """
        ctx, posting, (b1, b2) = _setup_two_bid_award(
            [{"factor_name": "LOCAL_SUPPORT", "score": 80},
             {"factor_name": "EXPERIENCE", "score": 90}],
            [{"factor_name": "LOCAL_SUPPORT", "score": 60},
             {"factor_name": "EXPERIENCE", "score": 60}],
        )
        awarded = get_posting(posting["id"])
        assert awarded["status"] == "AWARDED"
        assert awarded["selected_bid_id"] == b2["id"], (
            "B2 (84.00, price 40000) must beat B1 (82.00, factors 80/90): "
            "the price ratio outweighs stronger qualitative factors"
        )
        assert get_bid(b2["id"])["status"] == "SELECTED"
        assert get_bid(b1["id"])["status"] == "NOT_SELECTED"


class TestEmptyQualifiedPool:
    """Queue A: boundary_precision_check/select_winner_empty_qualified_pool."""

    def test_select_winner_with_only_submitted_bids_rejected(self, api):
        """PRD §3.3: "It requires at least one `QUALIFIED` bid; an empty candidate
        pool is rejected with `ERR_NO_QUALIFIED_BIDS`. Evaluation runs only over
        `QUALIFIED` bids (`SUBMITTED` and `DISQUALIFIED` bids are excluded from
        the candidate set and from the price floor)."

        Design: Difficulty/boundary_precision_check/select_winner_empty_qualified_pool
        """
        ctx = setup_applicant_base(with_snapshot=False)
        sp1, _ = new_provider_with_headers()
        posting = new_posting(ctx, price_weight_pct=100)
        publish_posting(ctx, posting)
        set_clock("2026-08-05T00:00:00Z")
        submit_bid(ctx, posting, sp1, 50000)  # stays SUBMITTED — never qualified
        set_clock("2026-08-29T00:00:00Z")
        close_window(ctx, posting)

        resp = api.select_winner(posting["id"], ctx["coord_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_QUALIFIED_BIDS)
        assert get_posting(posting["id"])["status"] == "WINDOW_CLOSED", (
            "failed selection must not move the posting out of WINDOW_CLOSED"
        )

    def test_sole_qualified_bid_scores_full_price_points(self, api):
        """PRD §3.3: "First the lowest `eligible_price_cents` among the candidates
        is found. Each candidate's **price points** are that lowest price divided
        by the candidate's own `eligible_price_cents`, multiplied by the posting's
        `price_weight_pct`, and rounded half up to two decimal places."
        PRD §3.3: "Winner selection — available to either an `ApplicantCoordinator`
        or an `ApplicantCertifier` — moves the posting from `WINDOW_CLOSED` to
        `AWARDED`."

        Design: Difficulty/boundary_precision_check/select_winner_empty_qualified_pool
        """
        ctx = setup_applicant_base(with_snapshot=False)
        sp1, _ = new_provider_with_headers()
        posting = new_posting(ctx, price_weight_pct=100)
        publish_posting(ctx, posting)
        set_clock("2026-08-05T00:00:00Z")
        bid = qualify_bid(ctx, submit_bid(ctx, posting, sp1, 50000))
        set_clock("2026-08-29T00:00:00Z")
        close_window(ctx, posting)

        awarded = run_select_winner(ctx, posting)
        assert awarded["status"] == "AWARDED"
        assert awarded["selected_bid_id"] == bid["id"]
        bid = get_bid(bid["id"])
        assert bid["status"] == "SELECTED"
        # Sole candidate: price floor is its own price -> 50000/50000*100 = 100.00
        assert bid["total_score"] == pytest.approx(100.0, abs=1e-9), (
            f"sole QUALIFIED candidate must score 100.00, got {bid['total_score']}"
        )


class TestBidTiebreak:
    def test_bid_tiebreak_earliest_created_at(self, api):
        """PRD §3.3: "The winner is the highest `total_score`; ties break to the
        lower `eligible_price_cents`, and further ties to the earlier bid
        `created_at`."

        Design: Corner/calculations/bid_tiebreak_earliest_created_at
        """
        identical = [{"factor_name": "LOCAL_SUPPORT", "score": 60},
                     {"factor_name": "EXPERIENCE", "score": 60}]
        _, posting, (b1, b2) = _setup_two_bid_award(identical, identical,
                                                    price1=40000, price2=40000)
        # Double tie: both score 84.00 at the same price; created_at decides.
        assert get_bid(b1["id"])["total_score"] == pytest.approx(84.0, abs=1e-9)
        assert get_bid(b2["id"])["total_score"] == pytest.approx(84.0, abs=1e-9)
        awarded = get_posting(posting["id"])
        assert awarded["selected_bid_id"] == b1["id"], (
            "identical scores and prices must resolve to the earlier-created bid"
        )
        assert get_bid(b1["id"])["status"] == "SELECTED"
        assert get_bid(b2["id"])["status"] == "NOT_SELECTED"


class TestPostingLifecycle:
    def test_publish_from_posted_rejected(self, api):
        """PRD §3.3: "Publishing transitions the posting from `DRAFT` to `POSTED`:
        `posted_at` is stamped from the logical clock, `window_close_at` is
        computed as exactly 28 days later, and the posting's `version` increments."
        PRD §2.10: "**State gates** — the target resource must be in a from-state
        of the invoked transition, or satisfy the state gate of a state-gated
        create" and "Violations yield `ERR_INVALID_STATE_TRANSITION`, or the more
        specific `ERR_CONTRACT_NOT_CERTIFIED`, `ERR_LINE_NOT_COMMITTED`, or
        `ERR_SERVICES_NOT_STARTED` where those named gates apply."
        PRD §2.4: "At startup, before any call has been made, the logical clock
        stands at exactly `2026-08-01T00:00:00Z`, and it never falls back to
        wall-clock time thereafter."

        Design: Corner/state_machines/publish_from_posted_rejected
        """
        ctx = setup_applicant_base(with_snapshot=False)
        posting = new_posting(ctx)
        published = publish_posting(ctx, posting)
        assert published["posted_at"] == CLOCK_STARTUP_DEFAULT

        set_clock("2026-08-10T00:00:00Z")
        resp = api.publish_posting(posting["id"], ctx["coord_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_posting(posting["id"])["posted_at"] == CLOCK_STARTUP_DEFAULT, (
            "the failed second publish must not restamp posted_at"
        )

    def test_cancel_posted_posting_cascades_bids(self, api):
        """PRD §3.3: "A coordinator may also cancel a posting while it is `DRAFT`
        or `POSTED`, moving it to `CANCELLED`; cancelling a `POSTED` posting
        cascades downward, driving every `SUBMITTED` and `QUALIFIED` bid on it to
        `DISQUALIFIED`, while the posting's own `version` increments."

        Design: Corner/state_machines/cancel_posted_posting_cascades_bids
        """
        ctx = setup_applicant_base(with_snapshot=False)
        sp1, _ = new_provider_with_headers("VendorOne", "SPIN-001")
        sp2, _ = new_provider_with_headers("VendorTwo", "SPIN-002")
        posting = new_posting(ctx)
        publish_posting(ctx, posting)
        set_clock("2026-08-05T00:00:00Z")
        b1 = submit_bid(ctx, posting, sp1, 50000)                      # SUBMITTED
        b2 = qualify_bid(ctx, submit_bid(ctx, posting, sp2, 45000))    # QUALIFIED

        cancelled = validate_success(
            api.cancel_posting(posting["id"], ctx["coord_headers"]), 200
        )
        assert cancelled["status"] == "CANCELLED"
        assert get_bid(b1["id"])["status"] == "DISQUALIFIED"
        assert get_bid(b2["id"])["status"] == "DISQUALIFIED"

    def test_publish_response_reflects_mutation_immediately(self, api):
        """PRD §3.3: "Publishing transitions the posting from `DRAFT` to `POSTED`:
        `posted_at` is stamped from the logical clock, `window_close_at` is
        computed as exactly 28 days later, and the posting's `version` increments."
        PRD §2.5: "`version` — a system-managed integer that increments by
        exactly 1 on every mutation of the resource, including mutations the
        server applies as cascade side effects on a related resource"
        PRD §2.4: "At startup, before any call has been made, the logical clock
        stands at exactly `2026-08-01T00:00:00Z`, and it never falls back to
        wall-clock time thereafter."

        Design: Corner/consistency_model/publish_response_reflects_mutation_immediately
        """
        ctx = setup_applicant_base(with_snapshot=False)
        posting = new_posting(ctx)
        published = publish_posting(ctx, posting)
        # Everything observable in the mutation's own response — no re-read.
        assert published["status"] == "POSTED"
        assert published["posted_at"] == CLOCK_STARTUP_DEFAULT
        assert published["window_close_at"] == "2026-08-29T00:00:00Z", (
            "window_close_at must be posted_at + 28 days in the publish response"
        )
        assert published["version"] == posting["version"] + 1


class TestPostingValidationAndRoles:
    def test_price_not_primary_rejected(self, api):
        """PRD §3.3: "Price must be the primary factor: `price_weight_pct` is an
        integer greater than zero and at most 100, and it must be at least the
        `weight_pct` of every entry in `other_factor_weights` (an optional list of
        `{ factor_name, weight_pct }` records that defaults to an empty list)."
        PRD §3.3: "A posting whose price weight falls below any other factor's
        weight is rejected with `ERR_PRICE_NOT_PRIMARY`."

        Design: Corner/validations/price_not_primary_rejected
        """
        ctx = setup_applicant_base(with_snapshot=False)
        payload = {
            "applicant_id": ctx["applicant"]["id"],
            "funding_cycle_id": ctx["cycle"]["id"],
            "category": "CATEGORY_ONE",
            "description": "Internet access",
            "price_weight_pct": 30,
            "other_factor_weights": [{"factor_name": "LOCAL_SUPPORT", "weight_pct": 40}],
        }
        resp = api.create_procurement_posting(payload, ctx["coord_headers"])
        validate_error(resp, ApiErrorId.ERR_PRICE_NOT_PRIMARY)

    def test_vendor_cannot_qualify_own_bid(self, api):
        """PRD §2.1: "When the caller's role is not in the endpoint's authorized
        list, the rejection is `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/erate/bids/{id}/qualify` | Mark a submitted bid as
        qualified | ApplicantCoordinator |".

        Design: Corner/rbac/vendor_cannot_qualify_own_bid
        """
        ctx = setup_applicant_base(with_snapshot=False)
        sp1, vendor_headers = new_provider_with_headers()
        posting = new_posting(ctx)
        publish_posting(ctx, posting)
        set_clock("2026-08-05T00:00:00Z")
        bid = submit_bid(ctx, posting, sp1, 50000)

        resp = api.qualify_bid(bid["id"], vendor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestBidWindowEdges:
    def test_bid_window_exact_close_is_late(self, api):
        """PRD §2.4: "The **bid window** on a published posting is the half-open
        interval from `posted_at` up to but not including `window_close_at`, which
        is exactly 28 days after `posted_at`. A bid submitted at exactly
        `window_close_at` is already late and is rejected with
        `ERR_BID_WINDOW_CLOSED`."
        PRD §2.4: "The **window-closure gate**: closing the bidding early is
        impossible — the operation requires the clock to be at or beyond
        `window_close_at`, and otherwise fails with `ERR_BID_WINDOW_STILL_OPEN`."

        Design: Corner/cross_cutting_complexity_layers/bid_window_exact_close_is_late
        """
        ctx = setup_applicant_base(with_snapshot=False)
        sp1, _ = new_provider_with_headers()
        posting = new_posting(ctx)
        published = publish_posting(ctx, posting)  # at the startup-default clock
        assert published["posted_at"] == CLOCK_STARTUP_DEFAULT
        assert published["window_close_at"] == "2026-08-29T00:00:00Z"

        # One second short of full elapse: the window cannot be closed yet.
        set_clock("2026-08-28T12:00:00Z")
        resp = api.close_posting_window(posting["id"], ctx["coord_headers"])
        validate_error(resp, ApiErrorId.ERR_BID_WINDOW_STILL_OPEN)

        # One second inside the half-open window: the bid is on time.
        set_clock("2026-08-28T23:59:59Z")
        bid = submit_bid(ctx, posting, sp1, 50000)
        assert bid["status"] == "SUBMITTED"

        # Exactly at window_close_at: already late.
        set_clock("2026-08-29T00:00:00Z")
        resp = api.create_bid(
            create_bid_payload(posting_id=posting["id"], eligible_price_cents=48000,
                               factor_scores=[]),
            make_vendor_headers(sp1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BID_WINDOW_CLOSED)

        closed = close_window(ctx, posting)
        assert closed["status"] == "WINDOW_CLOSED"
