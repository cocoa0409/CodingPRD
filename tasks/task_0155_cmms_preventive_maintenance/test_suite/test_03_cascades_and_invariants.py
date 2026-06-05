"""Cascade chains and conserved-quantity invariants: close -> commit -> release
-> stock debit; downtime resolve -> MTTR + asset restore; reserve/release
availability conservation; warranty approve/deny budget conservation; cancel
cascade; derived reserved_qty reconciliation; immediate consistency.

Covers Difficulty queue rules transitive_cascade and compensating_invariant
plus the Corner cross_cutting_complexity_layers and consistency_model sections.
"""
import pytest

from test_helpers import (
    fixtures as fx,
    validate_success,
    TEST_USERS,
    make_technician_headers,
)

PLANNER = TEST_USERS["planner_headers"]
MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]


# =========================================================================
# Rule 4 — transitive_cascade
# =========================================================================

class TestCloseCascade:
    def test_close_commits_release_and_debits_stock(self, api):
        """PRD §3.6: "If the parts status is COMMITTED, each committed
        reservation's qty is debited from its spare part's on_hand_qty, those
        reservations are set to RELEASED, and each affected part's reserved_qty
        is recomputed (the order's parts_status thereby becomes RELEASED)."

        Design: Difficulty/transitive_cascade/close_cascades_commit_to_release_to_stock_debit_depth3
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        asset, tech, part, wo, resv = fx.setup_committed_in_progress_wo(
            on_hand_qty=10, qty=3, unit_cost_cents=5000, sku="BRG-001"
        )
        closed = validate_success(
            api.close_work_order(wo["id"], {"actual_cost_cents": 15000},
                                 make_technician_headers(tech["id"]))
        )
        assert closed["parts_status"] == "RELEASED"
        resv_after = fx.get_reservation(resv["id"])
        assert resv_after["status"] == "RELEASED"
        part_after = fx.get_spare_part(part["id"])
        assert part_after["on_hand_qty"] == 7, "10 - committed qty 3"
        assert part_after["reserved_qty"] == 0

    def test_close_releases_committed_reservation_status(self, api):
        """PRD §3.7: "committed units still count toward reserved_qty until the
        close cascade debits stock".
        PRD §3.6: "those reservations are set to RELEASED, and each affected
        part's reserved_qty is recomputed (the order's parts_status thereby
        becomes RELEASED)."

        Design: Difficulty/transitive_cascade/close_cascades_commit_to_release_to_stock_debit_depth3
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        # Distinct geometry: on_hand 6, committed qty 2 -> on_hand debits to 4.
        asset, tech, part, wo, resv = fx.setup_committed_in_progress_wo(
            on_hand_qty=6, qty=2, unit_cost_cents=3000, sku="BRG-002"
        )
        # While COMMITTED but not yet closed, the units still count as reserved.
        part_mid = fx.get_spare_part(part["id"])
        assert part_mid["reserved_qty"] == 2, "COMMITTED still counts as reserved pre-close"
        fx.close(wo["id"], tech["id"], 6000)
        resv_after = fx.get_reservation(resv["id"])
        assert resv_after["status"] == "RELEASED"
        part_after = fx.get_spare_part(part["id"])
        assert part_after["on_hand_qty"] == 4, "6 - committed qty 2"
        assert part_after["reserved_qty"] == 0

    def test_close_charges_site_budget_when_no_warranty(self, api):
        """PRD §3.6: "if the order has no warranty_claim_id, the asset's site has
        its budget_spent_cents increased by the order's actual_cost_cents".

        Design: Corner/consistency_model/close_cascade_visible_in_same_response_immediate
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        site, asset, tech, closed = fx.setup_closed_work_order_full(
            actual_cost_cents=70_000,
            tech_overrides={"skill_level": "SENIOR"},
            wo_overrides={"severity": "MAJOR", "estimated_labor_hours": 2},
        )
        site_after = validate_success(api.get_site(site["id"], MANAGER))
        assert site_after["budget_spent_cents"] == 70_000, (
            "the just-closed work order's cost is immediately visible on the budget"
        )


class TestDowntimeResolveCascade:
    def test_resolve_recomputes_mttr_and_restores_asset(self, api):
        """PRD §3.8: "Resolving sets ended_at, marks the event RESOLVED, and sets
        duration_hours to the elapsed time in hours, computed as the difference
        between ended_at and started_at divided by 3600 seconds. If the reason
        code is a failure class, the asset's mttr_hours is recomputed. And if
        this was the asset's last open downtime, the asset transitions from
        DOWN back to OPERATIONAL."

        Design: Difficulty/transitive_cascade/downtime_resolve_cascades_mttr_then_asset_restore_depth2
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "HIGH", "acquisition_cost_cents": 900_000}
        )
        dt = fx.open_downtime(asset["id"], "MECHANICAL_FAILURE", "2026-05-01T00:00:00Z")
        resolved = validate_success(
            api.resolve_downtime_event(
                dt["id"], {"ended_at": "2026-05-01T04:00:00Z"},
                TEST_USERS["technician_headers"],
            )
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["duration_hours"] == pytest.approx(4, abs=0.01)
        asset_after = validate_success(api.get_asset(asset["id"], MANAGER))
        assert asset_after["status"] == "OPERATIONAL"
        assert asset_after["mttr_hours"] == pytest.approx(4, abs=0.01)

    def test_open_failure_downtime_drives_asset_down(self, api):
        """PRD §3.8: "Opening a downtime moves the asset to DOWN if it was
        OPERATIONAL, and if the reason code is a failure class it recomputes the
        asset's mtbf_hours."

        Design: Difficulty/transitive_cascade/downtime_resolve_cascades_mttr_then_asset_restore_depth2
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "HIGH", "acquisition_cost_cents": 900_000}
        )
        fx.open_downtime(asset["id"], "MECHANICAL_FAILURE", "2026-05-01T00:00:00Z")
        asset_after = validate_success(api.get_asset(asset["id"], MANAGER))
        assert asset_after["status"] == "DOWN", "an open downtime drives the asset DOWN"


# =========================================================================
# Rule 9 — compensating_invariant
# =========================================================================

class TestPartAvailabilityConservation:
    def test_reserve_then_release_conserves_availability(self, api):
        """PRD §3.7: "Releasing sets the reservation's status to RELEASED,
        recomputes the part's reserved_qty (freeing the units, with on_hand_qty
        unchanged)".

        Design: Difficulty/compensating_invariant/reserve_then_release_conserves_part_availability
        """
        site, asset, part, wo = fx.setup_unassigned_wo_with_part(
            on_hand_qty=8, unit_cost_cents=2000, sku="SEAL-100"
        )
        resv = fx.reserve(wo["id"], part["id"], 5, part["version"])
        released = validate_success(api.release_reservation(resv["id"], CLERK))
        assert released["status"] == "RELEASED"
        part_after = fx.get_spare_part(part["id"])
        assert part_after["on_hand_qty"] == 8, "on_hand never debited without a commit/close"
        assert part_after["reserved_qty"] == 0
        assert part_after["on_hand_qty"] - part_after["reserved_qty"] == 8, (
            "available units restored to the pre-reserve value"
        )

    def test_release_sets_work_order_parts_status_released(self, api):
        """PRD §3.7: "and — if this was the work order's last reservation that had
        not yet been released — sets the work order's parts_status to RELEASED."

        Design: Difficulty/compensating_invariant/reserve_then_release_conserves_part_availability
        """
        site, asset, part, wo = fx.setup_unassigned_wo_with_part(
            on_hand_qty=8, unit_cost_cents=2000, sku="SEAL-101"
        )
        resv = fx.reserve(wo["id"], part["id"], 5, part["version"])
        validate_success(api.release_reservation(resv["id"], CLERK))
        wo_after = validate_success(api.get_work_order(wo["id"], PLANNER))
        assert wo_after["parts_status"] == "RELEASED"


class TestSiteBudgetConservation:
    def test_approve_then_deny_path_conserves_budget(self, api):
        """PRD §3.1: "it is the sum of actual_cost_cents over every CLOSED work
        order whose asset belongs to the site and whose cost was not covered by
        an approved warranty claim."
        PRD §3.9: "reimburses the site by decreasing budget_spent_cents by the
        work order's actual_cost_cents".

        Design: Difficulty/compensating_invariant/warranty_approve_then_deny_path_conserves_site_budget
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        site, asset, tech = fx.setup_site_asset_tech(
            asset_overrides={"criticality": "LOW", "acquisition_cost_cents": 500_000,
                             "warranty_expires_at": "2027-01-01T00:00:00Z"},
            tech_overrides={"skill_level": "MASTER"},
        )
        wo1 = fx.setup_closed_work_order(asset["id"], tech["id"], 100_000)
        wo2 = fx.setup_closed_work_order(asset["id"], tech["id"], 100_000)
        claim1 = fx.submit_claim(asset["id"], wo1["id"], "REPAIR")
        claim2 = fx.submit_claim(asset["id"], wo2["id"], "REPAIR")
        fx.approve_claim(claim1["id"], "approved")
        fx.deny_claim(claim2["id"], "denied")
        site_after = validate_success(api.get_site(site["id"], MANAGER))
        assert site_after["budget_spent_cents"] == 100_000, (
            "only the denied work order's charge survives"
        )
        wo1_after = validate_success(api.get_work_order(wo1["id"], PLANNER))
        wo2_after = validate_success(api.get_work_order(wo2["id"], PLANNER))
        assert wo1_after["warranty_claim_id"] == claim1["id"]
        assert wo2_after["warranty_claim_id"] is None

    def test_approve_reimburses_budget_to_zero(self, api):
        """PRD §3.9: "the charge that was applied when the order closed is
        returned because warranty now covers it."

        Design: Difficulty/compensating_invariant/warranty_approve_then_deny_path_conserves_site_budget
        """
        site, asset, tech, closed, claim = fx.setup_warranted_closed_wo_with_claim(
            claim_type="REPAIR",
            actual_cost_cents=100_000,
            acquisition_cost_cents=500_000,
        )
        # Before approve: budget charged 100,000 at close.
        site_before = validate_success(api.get_site(site["id"], MANAGER))
        assert site_before["budget_spent_cents"] == 100_000
        fx.approve_claim(claim["id"], "approved")
        site_after = validate_success(api.get_site(site["id"], MANAGER))
        assert site_after["budget_spent_cents"] == 0, "approval reimburses the close-time charge"


# =========================================================================
# Corner — cross_cutting_complexity_layers
# =========================================================================

class TestDerivedFieldsAndCascades:
    def test_occ_correct_version_retire_bumps_version(self, api):
        """PRD §2.4: "The version field is an integer that starts at its initial
        value and increments by one on every mutation of the resource".
        PRD §3.2: "A successful retire moves the asset to the terminal RETIRED
        status, increments its version".

        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_retire_succeeds_and_bumps
        """
        site, asset = fx.setup_site_and_asset()
        assert asset["version"] == 1
        retired = validate_success(
            api.retire_asset(asset["id"], {"expected_asset_version": asset["version"]}, MANAGER)
        )
        assert retired["status"] == "RETIRED"
        assert retired["version"] == 2, "version incremented by exactly 1 from create version 1"

    def test_reserved_qty_reconciled_after_release(self, api):
        """PRD §3.1: "The part's reserved_qty is computed: it begins at 0 and
        equals the sum of qty over reservations on that part whose status is
        RESERVED or COMMITTED, recomputed on every reservation create, commit,
        and release."

        Design: Corner/cross_cutting_complexity_layers/derived_reserved_qty_reconciled_after_release
        """
        site, asset, part, wo = fx.setup_unassigned_wo_with_part(
            on_hand_qty=10, unit_cost_cents=100, sku="DF-1"
        )
        r1 = fx.reserve(wo["id"], part["id"], 3, part["version"])
        part_v1 = fx.get_spare_part(part["id"])
        fx.reserve(wo["id"], part["id"], 2, part_v1["version"])
        # reserved_qty now 5; release the 3-unit reservation.
        validate_success(api.release_reservation(r1["id"], CLERK))
        part_after = fx.get_spare_part(part["id"])
        assert part_after["reserved_qty"] == 2, "reconciled to the surviving 2-unit reservation"
        assert part_after["on_hand_qty"] == 10, "still no debit"

    def test_cancel_releases_reserved_parts_cascade(self, api):
        """PRD §3.5: "the cascade releases every reservation on the order whose
        status is RESERVED by setting it to RELEASED and recomputing the
        affected spare part's reserved_qty; because committed reservations
        cannot exist before a work order reaches IN_PROGRESS, no stock is
        debited by a cancel."

        Design: Corner/cross_cutting_complexity_layers/cancel_work_order_releases_reserved_parts_cascade
        """
        site, asset, part, wo = fx.setup_unassigned_wo_with_part(
            on_hand_qty=10, unit_cost_cents=100, sku="CX-1"
        )
        fx.reserve(wo["id"], part["id"], 4, part["version"])
        cancelled = validate_success(api.cancel_work_order(wo["id"], PLANNER))
        assert cancelled["execution_status"] == "CANCELLED"
        part_after = fx.get_spare_part(part["id"])
        assert part_after["reserved_qty"] == 0
        assert part_after["on_hand_qty"] == 10
