"""PFOF disclosures: tier variants, band splitting, draft recompute, submit
coverage, staleness on publish, and the OCC-guarded revision chain
(PRD §2.6, §3.4)."""
from test_helpers import (
    ApiErrorId,
    make_disclosure,
    make_order,
    make_published_disclosure,
    set_clock,
    setup_venue_with_active_arrangement,
    transition_disclosure,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CA = TEST_USERS["compliance_admin_headers"]
OPS = TEST_USERS["ops_admin_headers"]
FO = TEST_USERS["filing_officer_headers"]
SA = TEST_USERS["surveillance_analyst_headers"]

TWO_BAND_TIERS = [
    {"min_monthly_shares": 0, "rate_cents_per_share": 0.10},
    {"min_monthly_shares": 100000, "rate_cents_per_share": 0.25},
]


def _three_executed_50k(arrangement_id, refs, exec_times, price=10000):
    for ref, at in zip(refs, exec_times):
        # PRD §3.2 execution window: executed_at must lie in [created_at, now].
        set_clock(at)
        make_order(client_ref=ref, symbol="BETA", side="BUY", quantity=50000,
                   order_type="MARKET", arrival_nbbo_bid_cents=9990,
                   arrival_nbbo_ask_cents=10010, arrangement_id=arrangement_id,
                   execute={"price_cents": price, "executed_at": at})


def _setup_tier_variant_quarters():
    """ARCA with the two-band tier table; 3 x 50000 shares executed in August
    (Q3) and 3 x 50000 in October (Q4); a MARGINAL draft for Q3 and a
    RETROACTIVE draft for Q4 (PRD §3.4)."""
    set_clock("2026-08-12T12:00:00Z")
    venue, arrangement = setup_venue_with_active_arrangement(
        venue_code="ARCA", name="NYSE Arca",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
        pfof_tiers=TWO_BAND_TIERS,
    )
    _three_executed_50k(arrangement["id"], ("P1", "P2", "P3"), (
        "2026-08-12T12:30:00Z", "2026-08-12T12:35:00Z", "2026-08-12T12:40:00Z"))
    d3 = make_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL")
    set_clock("2026-10-05T12:00:00Z")
    _three_executed_50k(arrangement["id"], ("P4", "P5", "P6"), (
        "2026-10-05T12:30:00Z", "2026-10-05T12:35:00Z", "2026-10-05T12:40:00Z"))
    d4 = make_disclosure(quarter="2026-Q4", pricing_variant="RETROACTIVE")
    return venue, arrangement, d3, d4


class TestPricingVariants:
    def test_pfof_marginal_variant_accrual(self, api):
        """PRD §3.4: "Under `MARGINAL`, each tier band covers only the shares
        between its own threshold and the next tier's threshold — the band's
        share count is the greater of zero and the lesser of S and the next
        threshold minus the band's threshold, with the final band uncapped —
        and each band's shares are multiplied by that band's rate, rounded
        half up to whole integer cents, then summed."

        Design: Difficulty/dual_variant_calc/pfof_tier_variants_diverge
        """
        _venue, _arr, d3, _d4 = _setup_tier_variant_quarters()
        data = validate_success(api.get_disclosure(d3["id"], FO))
        assert data["venue_lines"][0]["total_shares"] == 150000
        # 100000*0.10 + 50000*0.25 = 10000 + 12500.
        assert data["venue_lines"][0]["pfof_cents"] == 22500
        assert data["total_pfof_cents"] == 22500

    def test_pfof_retroactive_variant_accrual(self, api):
        """PRD §3.4: "Under `RETROACTIVE`, the single rate of the highest tier
        whose threshold does not exceed S applies to all S shares, and the
        product is rounded half up to whole integer cents; for any group whose
        shares cross a tier boundary the two variants produce different
        totals."

        Design: Difficulty/dual_variant_calc/pfof_tier_variants_diverge
        """
        _venue, _arr, d3, d4 = _setup_tier_variant_quarters()
        data = validate_success(api.get_disclosure(d4["id"], FO))
        assert data["venue_lines"][0]["total_shares"] == 150000
        assert data["venue_lines"][0]["pfof_cents"] == 37500, "150000 shares all at 0.25"
        assert data["total_pfof_cents"] == 37500
        d3_data = validate_success(api.get_disclosure(d3["id"], FO))
        assert d3_data["total_pfof_cents"] != data["total_pfof_cents"], (
            "identical volume and tier table: variant alone decides the accrual")


class TestMarginalBandSplit:
    def _setup_band_split(self):
        """Orders 99999 + 50001 shares in August; MARGINAL disclosure for
        2026-Q3 submitted (PRD §3.4). Returns (venue, arrangement, disclosure)."""
        set_clock("2026-08-12T12:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(
            venue_code="BATS", name="Cboe BZX", pfof_tiers=TWO_BAND_TIERS)
        # PRD §3.2 execution window: executed_at must lie in [created_at, now],
        # so the clock rides along with each execution instant.
        set_clock("2026-08-12T12:30:00Z")
        make_order(client_ref="B1", symbol="GAMA", side="BUY", quantity=99999,
                   order_type="MARKET", arrival_nbbo_bid_cents=9990,
                   arrival_nbbo_ask_cents=10010, arrangement_id=arrangement["id"],
                   execute={"price_cents": 10000, "executed_at": "2026-08-12T12:30:00Z"})
        set_clock("2026-08-12T12:35:00Z")
        make_order(client_ref="B2", symbol="GAMA", side="BUY", quantity=50001,
                   order_type="MARKET", arrival_nbbo_bid_cents=9990,
                   arrival_nbbo_ask_cents=10010, arrangement_id=arrangement["id"],
                   execute={"price_cents": 10000, "executed_at": "2026-08-12T12:35:00Z"})
        disclosure = make_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL")
        disclosure = transition_disclosure(disclosure["id"], "PENDING_APPROVAL")
        return venue, arrangement, disclosure

    def test_pfof_marginal_band_split_totals(self, api):
        """PRD §3.4: "each band's shares are multiplied by that band's rate,
        rounded half up to whole integer cents, then summed" and
        "`total_pfof_cents` is the sum of the per-line `pfof_cents`."

        Design: Difficulty/combinatorial_formula/pfof_marginal_band_split_multi_input
        """
        _venue, arrangement, disclosure = self._setup_band_split()
        data = validate_success(api.get_disclosure(disclosure["id"], FO))
        line = data["venue_lines"][0]
        assert line["total_shares"] == 150000
        # Band split is exactly 100000/50000: 100000*0.10 + 50000*0.25.
        assert line["pfof_cents"] == 22500
        assert data["total_pfof_cents"] == 22500

    def test_pfof_submit_pins_arrangement_identity(self, api):
        """PRD §3.4: "On success the lines are computed once, frozen, and
        pinned as above" where "The line pins the `arrangement_id` and
        `arrangement_version` of the arrangement covering the venue-month
        group". PRD §2.5: "The `version` is an integer that increments by
        exactly one on every mutation of the resource".

        Design: Difficulty/combinatorial_formula/pfof_marginal_band_split_multi_input
        """
        _venue, arrangement, disclosure = self._setup_band_split()
        data = validate_success(api.get_disclosure(disclosure["id"], FO))
        line = data["venue_lines"][0]
        assert line["arrangement_id"] == arrangement["id"]
        # create = 1, activation mutation = 2; no other mutation intervened.
        assert arrangement["version"] == 2
        assert line["arrangement_version"] == arrangement["version"], (
            "submit pins the covering arrangement's version at submit time")


class TestDisclosureLifecycle:
    def test_duplicate_disclosure_quarter_rejected(self, api):
        """PRD §3.4: "At most one non-superseded disclosure may exist per
        quarter; creating a second while one lives in `DRAFT`,
        `PENDING_APPROVAL`, or `PUBLISHED` is rejected with
        `ERR_DUPLICATE_DISCLOSURE` (HTTP 409), and the correct tool is the
        revision flow below."

        Design: Corner/entities/duplicate_disclosure_quarter_rejected
        """
        make_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL")
        resp = api.create_disclosure(
            {"quarter": "2026-Q3", "pricing_variant": "RETROACTIVE"}, FO)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DISCLOSURE)

    def test_disclosure_publish_from_draft_rejected(self, api):
        """PRD §3.4: "Publishing moves the disclosure from `PENDING_APPROVAL`
        to `PUBLISHED`". PRD §2.10: "then state admissibility of the requested
        transition including terminal lockdown (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/disclosure_publish_from_draft_rejected
        """
        disclosure = make_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL")
        resp = api.disclosure_transition(disclosure["id"], {"to_status": "PUBLISHED"}, FO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_analyst_cannot_submit_disclosure_returns_403(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint — or, for transition endpoints, not permitted for
        the requested transition target — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)." PRD §4: POST
        /surveillance/pfof-disclosures/{id}/transition is FilingOfficer-only.

        Design: Corner/rbac/analyst_cannot_submit_disclosure_returns_403
        """
        disclosure = make_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL")
        resp = api.disclosure_transition(
            disclosure["id"], {"to_status": "PENDING_APPROVAL"}, SA)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_draft_disclosure_recomputes_lines_on_read(self, api):
        """PRD §3.4: "While the disclosure is in `DRAFT`, the lines are
        computed on every read; submitting freezes them."

        Design: Corner/complexity_layers/draft_disclosure_recomputes_lines_on_read
        """
        set_clock("2026-08-10T14:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        make_order(client_ref="DD1", symbol="ACME", side="BUY", quantity=100,
                   order_type="MARKET", arrangement_id=arrangement["id"],
                   execute={"price_cents": 10000, "executed_at": "2026-08-10T14:00:00Z"})
        disclosure = make_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL")

        first = validate_success(api.get_disclosure(disclosure["id"], FO))
        assert first["total_pfof_cents"] == 10, "100 shares x 0.10 cents/share"

        make_order(client_ref="DD2", symbol="ACME", side="BUY", quantity=200,
                   order_type="MARKET", arrangement_id=arrangement["id"],
                   execute={"price_cents": 10000, "executed_at": "2026-08-10T14:00:00Z"})
        second = validate_success(api.get_disclosure(disclosure["id"], FO))
        assert second["total_pfof_cents"] == 30, "draft read reconciles to 300 shares x 0.10"

        frozen = transition_disclosure(disclosure["id"], "PENDING_APPROVAL")
        assert frozen["total_pfof_cents"] == 30
        assert frozen["submitted_at"] is not None, "submit stamps submitted_at with the logical now"

    def test_disclosure_stale_then_withdraw_recovers_publish(self, api):
        """PRD §3.4: "for every venue line, the pinned arrangement must still
        exist and its current `version` must still equal the pinned
        `arrangement_version` — any arrangement amended since submission
        breaks the match and the publish is rejected with
        `ERR_DISCLOSURE_STALE` (HTTP 409)." PRD §3.4: "withdrawal clears the
        frozen lines (they recompute on the next read) and nulls
        `submitted_at`".

        Design: Corner/state_machines/disclosure_stale_then_withdraw_recovers_publish
        """
        set_clock("2026-08-10T14:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        make_order(client_ref="ST1", symbol="ACME", side="BUY", quantity=1000,
                   order_type="MARKET", arrangement_id=arrangement["id"],
                   execute={"price_cents": 10000, "executed_at": "2026-08-10T14:00:00Z"})
        disclosure = make_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL")
        transition_disclosure(disclosure["id"], "PENDING_APPROVAL")

        amended = validate_success(api.amend_arrangement(
            arrangement["id"],
            {"expected_arrangement_version": arrangement["version"], "routing_fee_bps": 3},
            CA,
        ))
        assert amended["version"] == arrangement["version"] + 1, (
            "a successful amendment bumps the arrangement's version by one")

        resp = api.disclosure_transition(disclosure["id"], {"to_status": "PUBLISHED"}, FO)
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_STALE)

        withdrawn = transition_disclosure(disclosure["id"], "DRAFT")
        assert withdrawn["status"] == "DRAFT"
        assert withdrawn["submitted_at"] is None, "withdrawal nulls submitted_at"
        resubmitted = transition_disclosure(disclosure["id"], "PENDING_APPROVAL")
        assert resubmitted["status"] == "PENDING_APPROVAL"
        published = transition_disclosure(disclosure["id"], "PUBLISHED")
        assert published["status"] == "PUBLISHED"
        assert published["venue_lines"][0]["arrangement_version"] == amended["version"], (
            "resubmit repins the arrangement's current version")


class TestUncoveredVolume:
    def test_disclosure_submit_blocked_by_uncovered_volume(self, api):
        """PRD §3.4: "every `EXECUTED` order in the quarter must have a
        covering arrangement at its execution instant, or the submit is
        rejected with `ERR_UNCOVERED_VOLUME` (HTTP 409)."

        Design: Corner/validations/disclosure_submit_blocked_by_uncovered_volume
        """
        set_clock("2026-08-19T12:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(
            venue_code="NYSE",
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-08-20T00:00:00Z",
        )
        order = make_order(client_ref="UC1", symbol="ACME", side="BUY", quantity=100,
                           order_type="MARKET", arrangement_id=arrangement["id"])
        set_clock("2026-08-21T12:00:00Z")
        executed = validate_success(api.order_transition(order["id"], {
            "to_status": "EXECUTED", "executed_price_cents": 10000,
            "executed_at": "2026-08-21T10:00:00Z"}, OPS))
        assert executed["status"] == "EXECUTED"

        disclosure = make_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL")
        resp = api.disclosure_transition(disclosure["id"], {"to_status": "PENDING_APPROVAL"}, FO)
        validate_error(resp, ApiErrorId.ERR_UNCOVERED_VOLUME)


class TestRevisionChain:
    def test_occ_disclosure_revise_chain_and_stale_rejected(self, api):
        """PRD §3.4: "The revise action — the second OCC-guarded write of
        §2.6 — applies to a `PUBLISHED` disclosure, requires
        `expected_disclosure_version` matching the source's current `version`
        (else `ERR_STALE_VERSION`), and creates a brand-new `DRAFT` disclosure
        for the same quarter whose `revision_number` is one greater than the
        source's and whose `supersedes_id` points at the source. The source
        disclosure's `has_pending_revision` is set to true and its `version`
        increments by one." PRD §3.4: "When a publishing disclosure carries a
        `supersedes_id`, the superseded disclosure moves from `PUBLISHED` to
        `SUPERSEDED` in the same breath".

        Design: Corner/complexity_layers/occ_disclosure_revise_chain_and_stale_rejected
        """
        d1 = make_published_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL")
        observed_version = d1["version"]

        d2 = validate_success(api.revise_disclosure(
            d1["id"], {"expected_disclosure_version": observed_version}, FO),
            expected_status=201)
        assert d2["revision_number"] == 2
        assert d2["supersedes_id"] == d1["id"]
        assert d2["status"] == "DRAFT"

        stale = api.revise_disclosure(
            d1["id"], {"expected_disclosure_version": observed_version}, FO)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        source = validate_success(api.get_disclosure(d1["id"], FO))
        assert source["has_pending_revision"] is True
        assert source["version"] == observed_version + 1, (
            "revise increments the source disclosure's version by one")

        transition_disclosure(d2["id"], "PENDING_APPROVAL")
        transition_disclosure(d2["id"], "PUBLISHED")
        source = validate_success(api.get_disclosure(d1["id"], FO))
        assert source["status"] == "SUPERSEDED", "publishing the revision supersedes the source"
