"""Rights windows, exclusivity grants, league preemption, contest/release."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_contract,
    activate_grant,
    activate_window,
    countersign_contract,
    create_active_sponsor,
    create_asset,
    create_draft_contract,
    create_grant,
    create_league_window,
    create_venue,
    get_success_data,
    list_contract_invoices,
    propose_contract,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, AM_SUBMITTER, FINANCE, SALES, am_headers


def _setup_active_contract_with_grant(api, grant_first=2026, grant_last=2028,
                                      term_last=2028):
    """Venue + ACTIVE sponsor + ACTIVE contract with an ACTIVE BEVERAGE grant."""
    venue = create_venue()
    sponsor = create_active_sponsor()
    contract = create_draft_contract(venue["id"], sponsor["id"],
                                     term_last_season=term_last)
    grant = create_grant(contract["id"], first_season=grant_first,
                         last_season=grant_last)
    proposed = propose_contract(contract["id"])
    countersign_contract(contract["id"], sponsor["id"], proposed["version"])
    activate_grant(grant["id"])
    active = activate_contract(contract["id"])
    return venue, sponsor, active, grant


class TestParallelRightsDimension:
    """Difficulty rule non_linear_state_machine (parallel rights half)."""

    def test_league_activate_contests_grant_while_contract_stays_active(self, api):
        """PRD §2.6: "Every contract therefore carries two independent
        dimensions: `contract_status`, its commercial lifecycle, and
        `rights_status`, which is `CLEAR` while the contract has no
        `CONFLICTED` grant and becomes `CONTESTED` the moment any grant of the
        contract is `CONFLICTED`."
        PRD §3.2: "Activating a window whose `holder` is `LEAGUE` succeeds even
        where venue-side exclusivity already exists: every `ACTIVE` grant with
        the same venue and category whose season span overlaps the league
        window's span flips to `CONFLICTED`, and each affected grant's contract
        flips its `rights_status` to `CONTESTED`."

        Design: Difficulty/non_linear_state_machine/contract_revision_cycle_and_parallel_rights_dimension
        """
        venue, sponsor, contract, grant = _setup_active_contract_with_grant(api)
        window = create_league_window(venue["id"], first_season=2027,
                                      last_season=2029)
        activate_window(window["id"])

        got_grant = validate_success(api.get_grant(grant["id"], ADMIN))
        assert got_grant["grant_status"] == "CONFLICTED"

        got_contract = validate_success(api.get_contract(contract["id"], SALES))
        assert got_contract["rights_status"] == "CONTESTED"
        assert got_contract["contract_status"] == "ACTIVE", (
            "rights_status moves independently of contract_status")

    def test_contested_contract_keeps_contract_status_transitions_available(self, api):
        """PRD §2.6: "A `CONTESTED` contract is barred from exactly three
        operations — creating deliverables, approving evidence, and issuing
        invoices, each rejected with `ERR_CONTRACT_RIGHTS_CONTESTED` — while
        its `contract_status` transitions remain otherwise available."

        Design: Difficulty/non_linear_state_machine/contract_revision_cycle_and_parallel_rights_dimension
        """
        venue, sponsor, contract, grant = _setup_active_contract_with_grant(api)
        window = create_league_window(venue["id"], first_season=2027,
                                      last_season=2029)
        activate_window(window["id"])

        # contract_status transition still available while CONTESTED
        suspended = get_success_data(api.transition_contract(
            contract["id"], {"action": "SUSPEND"}, SALES))
        assert suspended["contract_status"] == "SUSPENDED"
        assert suspended["rights_status"] == "CONTESTED"


class TestGrantActivateBlockedByLeagueWindow:
    """Difficulty rule cross_entity_state_dependency, grant->window pair."""

    def _setup_pending_grant_and_window(self, api):
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_draft_contract(venue["id"], sponsor["id"],
                                         term_last_season=2028)
        grant = create_grant(contract["id"], first_season=2026,
                             last_season=2028)
        proposed = propose_contract(contract["id"])
        countersign_contract(contract["id"], sponsor["id"], proposed["version"])
        window = create_league_window(venue["id"], first_season=2027,
                                      last_season=2029)
        return venue, sponsor, contract, grant, window

    def test_grant_activate_rejected_while_league_window_active(self, api):
        """PRD §3.2: "Second, the league check: no `ACTIVE` `LEAGUE` rights
        window may overlap the same venue and category over the same seasons,
        otherwise `ERR_RIGHTS_CONFLICT`."

        Design: Difficulty/cross_entity_state_dependency/grant_activate_blocked_by_league_window
        """
        venue, sponsor, contract, grant, window = (
            self._setup_pending_grant_and_window(api))
        # Grant activates fine while the window is only RESERVED... but we
        # want the gate path: activate the window first.
        activate_window(window["id"])
        resp = api.transition_grant(grant["id"], {"action": "ACTIVATE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_RIGHTS_CONFLICT, expected_status=409)
        got = validate_success(api.get_grant(grant["id"], ADMIN))
        assert got["grant_status"] == "PENDING"

    def test_grant_activate_succeeds_after_league_window_released(self, api):
        """PRD §3.2: "When that league window is later released or expires, the
        sweep runs in reverse: each `CONFLICTED` grant whose only blocking
        active league window is this one returns to `ACTIVE`, and a contract
        whose last `CONFLICTED` grant has cleared returns to `CLEAR`."

        Design: Difficulty/cross_entity_state_dependency/grant_activate_blocked_by_league_window
        """
        venue, sponsor, contract, grant, window = (
            self._setup_pending_grant_and_window(api))
        activate_window(window["id"])
        validate_error(api.transition_grant(grant["id"], {"action": "ACTIVATE"},
                                            ADMIN),
                       ApiErrorId.ERR_RIGHTS_CONFLICT, expected_status=409)

        get_success_data(api.transition_rights_window(
            window["id"], {"action": "RELEASE"}, ADMIN))
        ok = validate_success(api.transition_grant(
            grant["id"], {"action": "ACTIVATE"}, ADMIN))
        assert ok["grant_status"] == "ACTIVE"


class TestGrantSeasonOverlapBoundaries:
    """Difficulty rule resource_temporal_overlap, integer-season semantics."""

    def _setup_three_contracts(self, api):
        venue = create_venue()
        s1 = create_active_sponsor(legal_name="FizzCo Beverages LLC")
        s2 = create_active_sponsor(legal_name="SparkWater Inc",
                                   display_name="SparkWater")
        # C1 (S1) ACTIVE with ACTIVE grant G1 BEVERAGE [2026,2028]
        c1 = create_draft_contract(venue["id"], s1["id"], title="C1",
                                   term_last_season=2028,
                                   base_fee_cents=1_000_000)
        g1 = create_grant(c1["id"], first_season=2026, last_season=2028)
        p1 = propose_contract(c1["id"])
        countersign_contract(c1["id"], s1["id"], p1["version"])
        activate_grant(g1["id"])
        activate_contract(c1["id"])
        # C2 (S2) COUNTERSIGNED with PENDING grant [2028,2030] (overlaps 2028)
        c2 = create_draft_contract(venue["id"], s2["id"], title="C2",
                                   term_last_season=2031,
                                   base_fee_cents=2_000_000)
        g2 = create_grant(c2["id"], first_season=2028, last_season=2030)
        p2 = propose_contract(c2["id"])
        countersign_contract(c2["id"], s2["id"], p2["version"])
        # C3 (S2) COUNTERSIGNED with PENDING grant [2029,2031] (adjacent)
        c3 = create_draft_contract(venue["id"], s2["id"], title="C3",
                                   term_last_season=2031,
                                   base_fee_cents=3_000_000)
        g3 = create_grant(c3["id"], first_season=2029, last_season=2031)
        p3 = propose_contract(c3["id"])
        countersign_contract(c3["id"], s2["id"], p3["version"])
        return venue, s1, s2, c1, g1, c2, g2, c3, g3

    def test_shared_single_season_conflicts(self, api):
        """PRD §2.5: "Two season windows overlap when each window's first
        season is no later than the other window's last season — equivalently,
        when neither window ends strictly before the other begins."
        PRD §3.2: "Third, the exclusivity sweep: no other `ACTIVE` grant on the
        same venue and category may overlap the requested seasons, otherwise
        `ERR_CATEGORY_EXCLUSIVITY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/grant_season_overlap_shared_season_vs_adjacent
        """
        _v, _s1, _s2, _c1, _g1, _c2, g2, _c3, _g3 = (
            self._setup_three_contracts(api))
        resp = api.transition_grant(g2["id"], {"action": "ACTIVATE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CATEGORY_EXCLUSIVITY_CONFLICT,
                       expected_status=409)
        got = validate_success(api.get_grant(g2["id"], ADMIN))
        assert got["grant_status"] == "PENDING"

    def test_back_to_back_seasons_do_not_overlap(self, api):
        """PRD §2.5: "Two windows sitting back-to-back, where one window's
        first season is exactly one greater than the other's last season, do
        not overlap."

        Design: Difficulty/resource_temporal_overlap/grant_season_overlap_shared_season_vs_adjacent
        """
        _v, _s1, _s2, _c1, _g1, _c2, _g2, _c3, g3 = (
            self._setup_three_contracts(api))
        ok = validate_success(api.transition_grant(
            g3["id"], {"action": "ACTIVATE"}, ADMIN))
        assert ok["grant_status"] == "ACTIVE"


class TestSafetyBeatsExclusivityConstraint:
    """Difficulty rule priority_pair_validation_conflict (safety vs constraint)."""

    def _setup_double_conflict(self, api):
        """G2's activation would trip both the league-window check and the
        grant-vs-grant exclusivity sweep."""
        venue = create_venue()
        s1 = create_active_sponsor(legal_name="FizzCo Beverages LLC")
        s2 = create_active_sponsor(legal_name="SparkWater Inc",
                                   display_name="SparkWater")
        # G1 ACTIVE on BEVERAGE [2026,2027]
        c1 = create_draft_contract(venue["id"], s1["id"], title="C1",
                                   term_last_season=2027,
                                   base_fee_cents=1_000_000)
        g1 = create_grant(c1["id"], first_season=2026, last_season=2027)
        p1 = propose_contract(c1["id"])
        countersign_contract(c1["id"], s1["id"], p1["version"])
        activate_grant(g1["id"])
        activate_contract(c1["id"])
        # G2 PENDING on BEVERAGE [2026,2030]
        c2 = create_draft_contract(venue["id"], s2["id"], title="C2",
                                   term_last_season=2030,
                                   base_fee_cents=2_000_000)
        g2 = create_grant(c2["id"], first_season=2026, last_season=2030)
        p2 = propose_contract(c2["id"])
        countersign_contract(c2["id"], s2["id"], p2["version"])
        # League window overlaps G2 (2029-2030) but not G1 (2026-2027)
        window = create_league_window(venue["id"], first_season=2029,
                                      last_season=2030)
        activate_window(window["id"])
        return venue, s1, s2, c1, g1, c2, g2, window

    def test_rights_conflict_reported_over_exclusivity_conflict(self, api):
        """PRD §3.2: "Activation of a grant is a `VenueAdmin` action whose
        checks run in a fixed order. First, the grant's own state must permit
        activation and, for a `PENDING` grant, the owning contract must be
        `COUNTERSIGNED` — a violation is `ERR_INVALID_STATE`. Second, the
        league check: no `ACTIVE` `LEAGUE` rights window may overlap the same
        venue and category over the same seasons, otherwise
        `ERR_RIGHTS_CONFLICT`. Third, the exclusivity sweep: no other `ACTIVE`
        grant on the same venue and category may overlap the requested seasons,
        otherwise `ERR_CATEGORY_EXCLUSIVITY_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/grant_activate_safety_beats_exclusivity_constraint
        """
        _v, _s1, _s2, _c1, g1, _c2, g2, _w = self._setup_double_conflict(api)
        resp = api.transition_grant(g2["id"], {"action": "ACTIVATE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_RIGHTS_CONFLICT, expected_status=409)
        got_g2 = validate_success(api.get_grant(g2["id"], ADMIN))
        assert got_g2["grant_status"] == "PENDING"

    def test_non_overlapping_grant_untouched_by_league_activation(self, api):
        """PRD §3.2: "every `ACTIVE` grant with the same venue and category
        whose season span overlaps the league window's span flips to
        `CONFLICTED`" — a grant that does NOT overlap the league window's span
        is outside the sweep's input set and remains ACTIVE.

        Design: Difficulty/priority_pair_validation_conflict/grant_activate_safety_beats_exclusivity_constraint
        """
        _v, _s1, _s2, _c1, g1, _c2, g2, _w = self._setup_double_conflict(api)
        got_g1 = validate_success(api.get_grant(g1["id"], ADMIN))
        assert got_g1["grant_status"] == "ACTIVE"


class TestGrantCreateValidations:
    def test_grant_window_outside_term_rejected(self, api):
        """PRD §3.2: "Grants themselves are created by `SponsorshipSales`
        against a contract, with a `category` and an inclusive season span that
        must sit inside the contract's term — `first_season` no earlier than
        the contract's `term_first_season` and `last_season` no later than its
        `term_last_season`, otherwise `ERR_GRANT_OUTSIDE_TERM`."

        Design: Corner/validations/grant_window_outside_term_rejected
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_draft_contract(venue["id"], sponsor["id"],
                                         term_last_season=2028)
        resp = api.create_grant(
            {"contract_id": contract["id"], "category": "BEVERAGE",
             "first_season": 2026, "last_season": 2029}, SALES)
        validate_error(resp, ApiErrorId.ERR_GRANT_OUTSIDE_TERM,
                       expected_status=422)

    def test_duplicate_grant_category_rejected(self, api):
        """PRD §3.2: "A contract may hold at most one grant per category in
        `PENDING` or `ACTIVE` status; a second such grant for the same contract
        and category is rejected with `ERR_DUPLICATE_GRANT`."

        Design: Corner/validations/duplicate_grant_category_rejected
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_draft_contract(venue["id"], sponsor["id"],
                                         term_last_season=2028)
        create_grant(contract["id"], first_season=2026, last_season=2028)
        resp = api.create_grant(
            {"contract_id": contract["id"], "category": "BEVERAGE",
             "first_season": 2027, "last_season": 2028}, SALES)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_GRANT, expected_status=409)


class TestLeagueReleaseCompensation:
    def test_league_window_release_restores_grant_and_rights(self, api):
        """PRD §3.2: "When that league window is later released or expires, the
        sweep runs in reverse: each `CONFLICTED` grant whose only blocking
        active league window is this one returns to `ACTIVE`, and a contract
        whose last `CONFLICTED` grant has cleared returns to `CLEAR`."

        Design: Corner/state_machines/league_window_release_restores_grant_and_rights
        """
        venue, sponsor, contract, grant = _setup_active_contract_with_grant(api)
        window = create_league_window(venue["id"], first_season=2027,
                                      last_season=2029)
        activate_window(window["id"])
        # Sanity: contested before release
        mid = validate_success(api.get_contract(contract["id"], SALES))
        assert mid["rights_status"] == "CONTESTED"

        released = validate_success(api.transition_rights_window(
            window["id"], {"action": "RELEASE"}, ADMIN))
        assert released["window_status"] == "RELEASED"

        got_grant = validate_success(api.get_grant(grant["id"], ADMIN))
        assert got_grant["grant_status"] == "ACTIVE"
        got_contract = validate_success(api.get_contract(contract["id"], SALES))
        assert got_contract["rights_status"] == "CLEAR"


class TestContestedContractGates:
    def test_contested_contract_blocks_deliverable_and_invoice(self, api):
        """PRD §2.6: "A `CONTESTED` contract is barred from exactly three
        operations — creating deliverables, approving evidence, and issuing
        invoices, each rejected with `ERR_CONTRACT_RIGHTS_CONTESTED`"

        Design: Corner/validations/contested_contract_blocks_deliverable_and_invoice
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        asset = create_asset(venue["id"])
        contract = create_draft_contract(venue["id"], sponsor["id"],
                                         term_last_season=2028)
        grant = create_grant(contract["id"], first_season=2026,
                             last_season=2028)
        proposed = propose_contract(contract["id"])
        countersign_contract(contract["id"], sponsor["id"], proposed["version"])
        activate_grant(grant["id"])
        activate_contract(contract["id"])
        window = create_league_window(venue["id"], first_season=2027,
                                      last_season=2029)
        activate_window(window["id"])

        # Deliverable create blocked
        resp_d = api.create_deliverable(
            {"contract_id": contract["id"], "asset_id": asset["id"],
             "season": 2026, "unit_kind": "GAME_DISPLAY",
             "contracted_units": 10}, am_headers(AM_SUBMITTER))
        validate_error(resp_d, ApiErrorId.ERR_CONTRACT_RIGHTS_CONTESTED,
                       expected_status=409)

        # Invoice issue blocked
        invoices = list_contract_invoices(contract["id"])
        resp_i = api.transition_invoice(invoices[0]["id"], {"action": "ISSUE"},
                                        FINANCE)
        validate_error(resp_i, ApiErrorId.ERR_CONTRACT_RIGHTS_CONTESTED,
                       expected_status=409)
