"""Two multi-link cascades that fire entirely inside one request."""

import pytest

from test_helpers import (
    AUTO_CANCEL_REASON,
    approved_proof,
    approve_all_stages,
    approved_version,
    current_route,
    new_plate_order,
    new_printer,
    new_proof,
    new_version,
    raise_recovery_claim,
    read_asset,
    read_plate_order,
    read_printer,
    read_proof,
    read_route,
    read_version,
    released_version,
    new_escape,
    assign_root_cause,
    settle_escape,
    submit,
    verify,
)


class TestApprovalCascadeSupersedesThePredecessor:
    """One decision completes a pass, approves, repoints, obsoletes and cancels."""

    def _setup(self):
        _brief, asset, v1 = approved_version()
        printer = new_printer()
        proof = approved_proof(v1["id"], printer)
        order = new_plate_order(v1["id"], printer, proof, plate_set_count=6)
        assert order["cost_cents"] == 163000
        assert order["status"] == "ORDERED"
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 163000

        v2 = new_version(
            asset["id"],
            supersedes_version_id=v1["id"],
            reason_for_change_code="ERROR_CORRECTION",
            change_description="Second revision replacing the launch artwork.",
        )
        verify(v2["id"])
        submit(v2["id"])
        return asset, v1, v2, order

    def test_final_stage_approval_repoints_the_asset_and_obsoletes_the_predecessor(self):
        """The pass, the version, the asset and the predecessor all move at once.

        PRD §2.9: "The **approval cascade** has four links: a review decision
        resolves the final stage of a routing pass, which completes the routing
        pass, which approves the artwork version, which repoints the owning asset's
        `current_approved_version_id` and (when that pointer was already populated)
        moves the asset into `SUPERSEDE_PENDING`, which in turn obsoletes the
        previously approved version and auto-cancels its outstanding plate orders."

        Design: Difficulty/transitive_cascade/approval_cascade_supersedes_prior_version_and_autocancels_plate_orders
        """
        asset, v1, v2, _order = self._setup()
        route = current_route(v2["id"])

        approve_all_stages(v2["id"])

        completed = read_route(route["id"])
        assert completed["status"] == "COMPLETE_APPROVED"
        assert completed["current_stage_no"] == 3

        approved = read_version(v2["id"])
        assert approved["state"] == "APPROVED"
        assert approved["approved_at"].startswith("2026-08-01T00:00:00")
        assert approved["requires_reverification"] is False

        after_asset = read_asset(asset["id"])
        assert after_asset["current_approved_version_id"] == v2["id"]
        assert after_asset["obsolescence_state"] == "SUPERSEDE_PENDING"
        assert read_version(v1["id"])["state"] == "OBSOLETE_PENDING"

    def test_auto_cancellation_debits_the_ledger_without_rewriting_the_cost(self):
        """The predecessor's ordered plates are cancelled by the cascade itself.

        PRD §3.5: "As that predecessor is obsoleted, every plate order of it whose
        `status` is `ORDERED` moves `ORDERED → CANCELLED` with `auto_cancelled` set
        true, `cancel_reason` set to the literal `SUPERSEDED_BY_NEW_ARTWORK` and
        `cancelled_at` stamped from the logical clock; orders that were already
        `CANCELLED` are left entirely untouched."

        Design: Difficulty/transitive_cascade/approval_cascade_supersedes_prior_version_and_autocancels_plate_orders
        """
        asset, _v1, v2, order = self._setup()

        approve_all_stages(v2["id"])

        cancelled = read_plate_order(order["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["auto_cancelled"] is True
        assert cancelled["cancel_reason"] == AUTO_CANCEL_REASON
        assert cancelled["cancelled_at"] is not None
        assert cancelled["cost_cents"] == 163000
        assert cancelled["plate_subtotal_cents"] == 103000
        assert cancelled["setup_fee_cents"] == 60000

        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 0


class TestSettlementCascadeDrivesProbation:
    """Settling an escape credits, penalises, demotes and flags for re-check."""

    def _setup(self):
        _brief, asset, version, printer, approved = released_version()
        open_proof = new_proof(version["id"], printer)
        assert open_proof["proof_no"] == 2
        assert open_proof["proof_state"] == "PROOF_IN_REVIEW"
        assert open_proof["requires_recheck"] is False

        escape = new_escape(
            version["id"], printer, discovered_stage="MARKET", units_affected=12500
        )
        escape = assign_root_cause(escape["id"], "SHARED", 0.65)
        escape = raise_recovery_claim(escape)
        assert escape["provisional_recovery_cents"] == 495625
        assert escape["state"] == "RECOVERY_CLAIMED"
        return asset, version, printer, approved, open_proof, escape

    def test_penalty_points_drive_the_score_below_the_probation_floor(self):
        """The unit penalty and the stage penalty combine, then cap and floor.

        PRD §3.9: "Second, `performance_penalty_points` is computed and subtracted
        from the vendor's `performance_score`: the raw penalty is 2.0 points for
        every thousand units affected — `units_affected` divided by 1000, multiplied
        by 2.0, without any intermediate rounding — plus a stage penalty of 2.0
        points when `discovered_stage` is `PRESS`, 4.0 when it is `PACKING`, 8.0
        when it is `DISTRIBUTION` and 10.0 when it is `MARKET`; that raw figure is
        rounded half up to one decimal place and then capped at 40.0 points."

        Design: Difficulty/transitive_cascade/settlement_cascade_drives_printer_probation_and_conditional_proof_recheck
        """
        _asset, _version, printer, _approved, _open_proof, escape = self._setup()

        settled = settle_escape(
            escape["id"],
            "SETTLED",
            actual_reprint_cost_cents=800010,
            actual_scrap_cost_cents=100010,
            actual_expedite_freight_cents=60010,
        )

        assert settled["state"] == "SETTLED"
        assert settled["resolution"] == "SETTLED"
        assert settled["final_recovery_cents"] == 721521

        vendor = read_printer(printer["id"])
        assert vendor["recovery_balance_cents"] == 721521
        assert vendor["performance_score"] == pytest.approx(65.0, abs=0.01)
        assert vendor["certification_status"] == "PROBATION"

    def test_probation_flags_only_the_proofs_that_are_not_yet_approved(self):
        """The fourth link of the cascade leaves approved proofs alone.

        PRD §3.9: "Fourth, that probation transition sets `requires_recheck` to true
        on every proof of that vendor whose `proof_state` is not `PROOF_APPROVED` —
        already-approved proofs are left alone."

        Design: Difficulty/transitive_cascade/settlement_cascade_drives_printer_probation_and_conditional_proof_recheck
        """
        _asset, _version, printer, approved, open_proof, escape = self._setup()

        settle_escape(
            escape["id"],
            "SETTLED",
            actual_reprint_cost_cents=800010,
            actual_scrap_cost_cents=100010,
            actual_expedite_freight_cents=60010,
        )

        assert read_printer(printer["id"])["certification_status"] == "PROBATION"

        flagged = read_proof(open_proof["id"])
        assert flagged["requires_recheck"] is True
        assert flagged["proof_state"] == "PROOF_IN_REVIEW"

        untouched = read_proof(approved["id"])
        assert untouched["requires_recheck"] is False
        assert untouched["proof_state"] == "PROOF_APPROVED"
