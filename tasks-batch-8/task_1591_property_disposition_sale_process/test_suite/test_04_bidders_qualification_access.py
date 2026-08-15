"""Bidder registration, the 25% proof-of-funds threshold, role exclusivity on
qualification, and half-open data-room access windows."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_asset,
    pipeline_through_offers,
    register_bidder,
    register_qualified_bidder,
    validate_error,
    validate_success,
)

DM = TEST_USERS["dm_headers"]
BROKER = TEST_USERS["broker_headers"]


class TestProofOfFundsThreshold:
    def test_proof_of_funds_exact_threshold_qualifies(self, api):
        """PRD: "The threshold test asks whether the bidder's proof covers at
        least twenty-five percent of the asset's `guidance_price_cents`,
        evaluated with integer cross-multiplication and an inclusive boundary:
        one hundred times `proof_of_funds_cents` must be greater than or equal
        to twenty-five times `guidance_price_cents`, and exact equality
        qualifies. A passing bidder becomes `QUALIFIED`."

        Design: Difficulty/boundary_precision_check/proof_of_funds_exact_threshold
        """
        asset = create_asset()  # guidance_price_cents 5,000,000,000
        bidder = register_bidder(asset["id"], 1_250_000_000)
        decided = validate_success(api.qualify_bidder(bidder["id"], DM))
        assert decided["qualification_status"] == "QUALIFIED", \
            "exact 25% of guidance qualifies (inclusive boundary)"

    def test_proof_of_funds_one_cent_below_disqualifies(self, api):
        """PRD: "A failing bidder does not merely stay pending — the
        registration is moved to `DISQUALIFIED`, and the caller receives
        `ERR_INSUFFICIENT_PROOF_OF_FUNDS` (HTTP 422) with the rejection."

        Design: Difficulty/boundary_precision_check/proof_of_funds_exact_threshold
        """
        asset = create_asset()  # guidance_price_cents 5,000,000,000
        bidder = register_bidder(asset["id"], 1_249_999_999)
        validate_error(api.qualify_bidder(bidder["id"], DM),
                       ApiErrorId.ERR_INSUFFICIENT_PROOF_OF_FUNDS)
        bidders = validate_success(api.list_asset_bidders(asset["id"], DM))
        assert bidders[0]["qualification_status"] == "DISQUALIFIED"


class TestQualificationRbac:
    def test_rbac_manager_exclusive_qualify(self, api):
        """PRD: "A request whose role is not authorized for the targeted
        operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD: "Qualification is a `DispositionManager` decision backed by a hard
        arithmetic threshold."

        Design: Corner/rbac/rbac_manager_exclusive_qualify
        """
        asset = create_asset()
        bidder = register_bidder(asset["id"], 600_000_000)
        validate_error(api.qualify_bidder(bidder["id"], BROKER),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)
        fetched = validate_success(api.get_bidder(bidder["id"], DM))
        assert fetched["qualification_status"] == "PENDING"


class TestAccessWindows:
    def test_access_window_adjacent_grant_allowed(self, api):
        """PRD: "Windows on the same bidder may not overlap under half-open
        semantics — the interval includes its start and excludes its end — and
        a grant that overlaps an existing `ACTIVE` window is rejected with
        `ERR_ACCESS_WINDOW_OVERLAP`; adjacency is permitted, so a new window
        whose start equals a prior window's end is allowed."

        Design: Difficulty/resource_temporal_overlap/access_window_half_open_adjacency
        """
        ws = pipeline_through_offers()
        bidder = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000)
        first = validate_success(api.grant_access(
            bidder["id"], "2026-08-20T00:00:00Z", "2026-09-10T00:00:00Z", BROKER))
        assert len(first["access_windows"]) == 1

        adjacent = validate_success(api.grant_access(
            bidder["id"], "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z", BROKER))
        assert len(adjacent["access_windows"]) == 2, \
            "half-open adjacency (start == prior end) is allowed"

    def test_access_window_interior_overlap_rejected(self, api):
        """PRD: "a grant that overlaps an existing `ACTIVE` window is rejected
        with `ERR_ACCESS_WINDOW_OVERLAP`; adjacency is permitted, so a new
        window whose start equals a prior window's end is allowed."

        Design: Difficulty/resource_temporal_overlap/access_window_half_open_adjacency
        """
        ws = pipeline_through_offers()
        bidder = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000)
        validate_success(api.grant_access(
            bidder["id"], "2026-08-20T00:00:00Z", "2026-09-10T00:00:00Z", BROKER))
        validate_success(api.grant_access(
            bidder["id"], "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z", BROKER))
        # Interior overlap with the first window (2026-09-05..2026-09-12
        # intersects 2026-08-20..2026-09-10).
        validate_error(api.grant_access(
            bidder["id"], "2026-09-05T00:00:00Z", "2026-09-12T00:00:00Z", BROKER),
            ApiErrorId.ERR_ACCESS_WINDOW_OVERLAP)
