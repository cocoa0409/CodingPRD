"""Sublicense approval gates, blackout intersection asymmetry, revocation
conflict logging, and exclusivity half-open window geometry."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_winning_bid,
    advance_clock,
    create_accredited_broadcaster,
    create_blackout_window,
    create_package,
    create_rights_asset,
    file_bid,
    file_sublicense_request,
    get_sublicense,
    list_conflicts,
    lock_asset_packages,
    setup_active_deal,
    setup_executed_deal,
    setup_shortlisted_bid,
    submit_bid,
    validate_error,
    validate_success,
    walk_bid_to_shortlisted,
    pay_milestone_on_time,
    get_milestone,
)

RM = TEST_USERS["rights_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestSublicenseApprovalDealGates:
    def test_approve_on_executed_not_active_deal_rejected(self, api):
        """PRD §3.8: "the request must be `PENDING`, the deal must be
        `ACTIVE` (`ERR_DEAL_NOT_ACTIVE`), and the deal's `posture` must not
        be `FROZEN` (`ERR_DEAL_FROZEN`)."

        Design: Difficulty/cross_entity_state_dependency/sublicense_approve_requires_deal_active_and_unfrozen
        """
        bundle = setup_executed_deal()
        deal = bundle["deal"]
        assert deal["status"] == "EXECUTED"
        sub = file_sublicense_request(deal["id"], bundle["broadcaster"]["id"])
        res = api.approve_sublicense(deal["id"], sub["id"], RM)
        validate_error(res, "ERR_DEAL_NOT_ACTIVE", expected_status=409)

    def test_approve_on_frozen_deal_rejected(self, api):
        """PRD §3.8: "the deal's `posture` must not be `FROZEN`
        (`ERR_DEAL_FROZEN`)."
        PRD §2.10: "A deal is `FROZEN` when any of its payment milestones is
        `DEFAULTED`, or its `payment_delinquency_count` has reached the
        breach threshold of 3, or any of its production obligations has sat
        in `SHORTFALL_DECLARED` for more than thirty days."

        Design: Difficulty/cross_entity_state_dependency/sublicense_approve_requires_deal_active_and_unfrozen
        """
        bundle = setup_executed_deal(
            milestone_specs=[
                (1, 1, "2026-09-01T00:00:00Z", 0.25),
                (1, 2, "2026-09-01T00:00:00Z", 0.25),
                (1, 3, "2026-09-01T00:00:00Z", 0.25),
                (1, 4, "2026-12-01T00:00:00Z", 0.25),
            ]
        )
        deal_id = bundle["deal"]["id"]
        # Invoice the three September milestones only — invoicing requires
        # SCHEDULED (§3.5), and pay_milestone_on_time below invoices the
        # December milestone itself before paying it.
        for m in bundle["milestones"][:3]:
            validate_success(api.invoice_milestone(deal_id, m["id"], FC), 200)
        # Pay the December milestone on time so the deal reaches ACTIVE.
        pay_milestone_on_time(deal_id, bundle["milestones"][3]["id"])
        # Clock past the September due date: three milestones go OVERDUE,
        # delinquency reaches the breach threshold of 3, posture FROZEN.
        advance_clock("2026-09-02T00:00:00Z")

        deal = validate_success(api.get_deal(deal_id, RM), 200)
        assert deal["status"] == "ACTIVE"
        assert deal["posture"] == "FROZEN"

        sub = file_sublicense_request(deal_id, bundle["broadcaster"]["id"])
        res = api.approve_sublicense(deal_id, sub["id"], RM)
        validate_error(res, "ERR_DEAL_FROZEN", expected_status=409)


class TestBlackoutIntersectionAsymmetry:
    def test_window_end_at_blackout_start_does_not_intersect(self, api):
        """PRD §2.9: "a sublicense window whose end exactly equals the
        blackout's start does not intersect it, while a sublicense window
        whose start exactly equals the blackout's end does intersect."

        S1 [2026-03-01, 2026-03-15T00:00:00Z) ends exactly at the blackout's
        closed start: approval succeeds.

        Design: Difficulty/resource_temporal_overlap/sublicense_blackout_overlap_closed_vs_half_open
        """
        bundle = setup_active_deal()
        deal_id = bundle["deal"]["id"]
        create_blackout_window(
            bundle["asset"]["id"],
            blackout_start="2026-03-15T00:00:00Z",
            blackout_end="2026-03-15T23:59:59Z",
        )
        s1 = file_sublicense_request(
            deal_id,
            bundle["broadcaster"]["id"],
            requested_window_start="2026-03-01T00:00:00Z",
            requested_window_end="2026-03-15T00:00:00Z",
        )
        approved = validate_success(
            api.approve_sublicense(deal_id, s1["id"], RM), 200
        )
        assert approved["status"] == "APPROVED"

    def test_window_start_at_blackout_end_intersects(self, api):
        """PRD §2.9: "a sublicense window whose end exactly equals the
        blackout's start does not intersect it, while a sublicense window
        whose start exactly equals the blackout's end does intersect."
        PRD §3.8: "if the requested window intersects any blackout window
        matching the request's territory and platform class under the
        intersection rule of §2.9, approval is rejected with
        `ERR_BLACKOUT_VIOLATION`."

        S2 [2026-03-15T23:59:59Z, 2026-04-01T00:00:00Z) starts exactly at the
        blackout's closed end: approval is rejected.

        Design: Difficulty/resource_temporal_overlap/sublicense_blackout_overlap_closed_vs_half_open
        """
        bundle = setup_active_deal()
        deal_id = bundle["deal"]["id"]
        create_blackout_window(
            bundle["asset"]["id"],
            blackout_start="2026-03-15T00:00:00Z",
            blackout_end="2026-03-15T23:59:59Z",
        )
        s2 = file_sublicense_request(
            deal_id,
            bundle["broadcaster"]["id"],
            requested_window_start="2026-03-15T23:59:59Z",
            requested_window_end="2026-04-01T00:00:00Z",
        )
        res = api.approve_sublicense(deal_id, s2["id"], RM)
        validate_error(res, "ERR_BLACKOUT_VIOLATION", expected_status=409)
        assert get_sublicense(deal_id, s2["id"])["status"] == "PENDING"


class TestRevocationConflictLog:
    def test_blackout_revocation_writes_rights_conflict_row(self, api):
        """PRD §3.8: "Only an `APPROVED` sublicense can be revoked, and only
        for cause: either the parent deal has transitioned to a terminated
        state, or a newly created blackout window has come to cover the
        sublicense's territory, platform, and window".
        PRD §3.8: "Revocation records the cause in the request's
        `revoked_reason`, and when the cause is a blackout, the system also
        writes a `RightsConflict` row with `conflict_type`
        `BLACKOUT_VIOLATION` into the monitor log of §2.11."

        Design: Corner/endpoints/sublicense_revoke_writes_rights_conflict_on_blackout
        """
        bundle = setup_active_deal()
        deal_id = bundle["deal"]["id"]
        sub = file_sublicense_request(
            deal_id,
            bundle["broadcaster"]["id"],
            requested_window_start="2026-03-01T00:00:00Z",
            requested_window_end="2026-04-01T00:00:00Z",
        )
        validate_success(api.approve_sublicense(deal_id, sub["id"], RM), 200)

        # A newly created blackout window covering the sublicense's
        # territory, platform, and window supplies the cause for revocation.
        create_blackout_window(
            bundle["asset"]["id"],
            blackout_start="2026-02-15T00:00:00Z",
            blackout_end="2026-04-15T23:59:59Z",
        )
        revoked = validate_success(
            api.revoke_sublicense(deal_id, sub["id"], {"reason": "BLACKOUT_VIOLATION"}, CO),
            200,
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_reason"] == "BLACKOUT_VIOLATION"

        rows = list_conflicts(params={"conflict_type": "BLACKOUT_VIOLATION"})
        assert any(
            sub["id"] in (row["left_entity_id"], row["right_entity_id"])
            for row in rows
        ), "expected a BLACKOUT_VIOLATION conflict row naming the sublicense"


class TestExclusivityHalfOpenGeometry:
    def _two_packages_and_award_first(self, api, p2_window_start, p2_window_end):
        asset = create_rights_asset(total_package_pool=3)
        p1 = create_package(
            asset["id"],
            package_code="P1",
            window_start="2026-01-01T00:00:00Z",
            window_end="2026-06-30T00:00:00Z",
        )
        p2 = create_package(
            asset["id"],
            package_code="P2",
            window_start=p2_window_start,
            window_end=p2_window_end,
        )
        lock_asset_packages(asset["id"])
        broadcaster = create_accredited_broadcaster()
        bid = file_bid(p1["id"], broadcaster["id"])
        submit_bid(p1["id"], bid["id"], broadcaster["id"])
        walk_bid_to_shortlisted(p1["id"], bid["id"])
        # Awarding a package runs the exclusivity scan of PRD §2.9.
        accept_winning_bid(p1["id"], bid["id"])
        return asset, p1, p2

    def test_adjacent_windows_do_not_conflict(self, api):
        """PRD §2.9: "Under half-open semantics, two windows that merely
        touch, where one package's `window_end` equals the other's
        `window_start`, do not overlap and never conflict."

        P1 [2026-01-01, 2026-06-30) and P2 [2026-06-30, 2026-12-31) share
        only the boundary instant.

        Design: Difficulty/resource_temporal_overlap/exclusivity_overlap_half_open_semantics
        """
        asset, p1, p2 = self._two_packages_and_award_first(
            api, "2026-06-30T00:00:00Z", "2026-12-31T23:59:59Z"
        )
        rows = list_conflicts(
            params={"conflict_type": "EXCLUSIVITY_OVERLAP", "asset_id": asset["id"]}
        )
        assert rows == [], (
            f"adjacent half-open windows must not conflict, got {rows}"
        )

    def test_overlapping_windows_record_conflict_row(self, api):
        """PRD §2.9: "The scan runs whenever a package is created or updated
        and whenever a package is awarded, it considers only packages in
        `OPEN_FOR_BIDS`, `UNDER_NEGOTIATION`, or `AWARDED` status, and each
        detected pair is recorded as a `RightsConflict` row with
        `conflict_type` `EXCLUSIVITY_OVERLAP`."

        P2 [2026-06-01, 2026-12-31) genuinely overlaps P1
        [2026-01-01, 2026-06-30).

        Design: Difficulty/resource_temporal_overlap/exclusivity_overlap_half_open_semantics
        """
        asset, p1, p2 = self._two_packages_and_award_first(
            api, "2026-06-01T00:00:00Z", "2026-12-31T23:59:59Z"
        )
        rows = list_conflicts(
            params={"conflict_type": "EXCLUSIVITY_OVERLAP", "asset_id": asset["id"]}
        )
        pair = {p1["id"], p2["id"]}
        assert any(
            {row["left_entity_id"], row["right_entity_id"]} == pair for row in rows
        ), f"expected an EXCLUSIVITY_OVERLAP row for the package pair, got {rows}"
