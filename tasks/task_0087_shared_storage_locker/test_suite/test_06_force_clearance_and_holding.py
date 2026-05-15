"""Force-clearance, holding, and claim-window tests (PRD §3.5)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    make_renter_headers,
    return_rental_payload,
    run_sweep,
    setup_basic_rental,
    setup_force_cleared_rental,
    setup_overdue_rental,
    validate_error,
    validate_success,
)


# ===========================================================================
# Force-clearance happy path (PRD §3.5)
# ===========================================================================
class TestForceClearanceHappyPath:

    def test_force_clearance_terminates_rental(self, api):
        """PRD §3.5: "When the sweep observes that the logical clock has
        reached or passed current_expires_at plus
        forced_clearance_hours_snapshot hours on a rental whose status
        is OVERDUE, force-clearance fires. The rental's status advances
        to FORCE_CLEARED, ended_at is set to the transition time."

        Claim: an OVERDUE rental crossed past
        current_expires_at + forced_clearance_hours becomes FORCE_CLEARED.
        """
        ctx = setup_force_cleared_rental(renter_id="renter-fc-1")
        assert ctx["rental"]["status"] == "FORCE_CLEARED"
        assert ctx["rental"]["ended_at"] is not None

    def test_force_clearance_forfeits_full_deposit(self, api):
        """PRD §3.5: "deposit_forfeited_cents is set to the full
        deposit_cents_snapshot regardless of how the overdue fee
        compares to the deposit."

        Claim: after force-clearance, deposit_forfeited_cents ==
        deposit_cents_snapshot and deposit_refunded_cents == 0.
        """
        ctx = setup_force_cleared_rental(renter_id="renter-fc-2")
        r = ctx["rental"]
        assert r["deposit_forfeited_cents"] == r["deposit_cents_snapshot"]
        assert r["deposit_refunded_cents"] == 0

    def test_force_clearance_cascades_compartment_to_holding(self, api,
                                                            operator_headers):
        """PRD §3.5: "The housing compartment cascades to occupancy_status
        = HOLDING, its active_rental_id is cleared, holding_item_description
        is populated with a free-text description of where the item has
        been moved, and holding_claim_deadline is set to the transition
        time plus the system-wide holding claim window."

        Claim: housing compartment is HOLDING with cleared active_rental_id
        and a non-null holding_claim_deadline.
        """
        ctx = setup_force_cleared_rental(renter_id="renter-fc-3")
        comp = validate_success(api.get_compartment(
            ctx["cabinet"]["id"], ctx["compartment"]["id"], operator_headers,
        ))
        assert comp["occupancy_status"] == "HOLDING"
        assert comp.get("active_rental_id") in (None,)
        assert comp.get("holding_claim_deadline") is not None

    def test_force_clearance_emits_audit_event(self, api, operator_headers):
        """PRD §3.5: "An AuditEvent of event_kind FORCE_CLEARANCE is
        emitted whose detail includes the destination locker and the
        forfeited deposit amount."

        Claim: GET /audit-events?event_kind=FORCE_CLEARANCE returns at
        least one row for this rental's compartment.
        """
        ctx = setup_force_cleared_rental(renter_id="renter-fc-4")
        rows = api.list_audit_events(operator_headers, params={
            "event_kind": "FORCE_CLEARANCE",
        }).json()["data"]
        assert len(rows) >= 1
        # the FORCE_CLEARANCE row may reference the Rental or the Compartment
        subj_ids = {r["subject_id"] for r in rows}
        assert ctx["rental"]["id"] in subj_ids or ctx["compartment"]["id"] in subj_ids, (
            "Expected FORCE_CLEARANCE row to reference the rental or the compartment"
        )


# ===========================================================================
# Holding claim window (PRD §3.5)
# ===========================================================================
class TestHoldingClaim:

    def test_owner_can_claim_within_window(self, api, operator_headers):
        """PRD §3.5: "After force-clearance, the renter retains the right
        to retrieve the held item for the duration of the claim window.
        The holding-claim request is authenticated against the most-recent
        force-cleared rental that landed on that compartment — the
        requesting Renter's X-User-ID must equal that rental's
        renter_id."

        Claim: owner of the force-cleared rental can claim-holding;
        compartment returns to IDLE.
        """
        ctx = setup_force_cleared_rental(renter_id="renter-fc-owner")
        resp = api.claim_holding(
            ctx["compartment"]["id"],
            make_renter_headers(ctx["renter_id"]),
        )
        validate_success(resp)
        comp = validate_success(api.get_compartment(
            ctx["cabinet"]["id"], ctx["compartment"]["id"], operator_headers,
        ))
        assert comp["occupancy_status"] == "IDLE"

    def test_non_owner_cannot_claim_holding(self, api):
        """PRD §3.5: "the requesting Renter's X-User-ID must equal that
        rental's renter_id."

        Claim: a different Renter attempting claim-holding →
        ERR_FORBIDDEN.
        """
        ctx = setup_force_cleared_rental(renter_id="renter-fc-owner-a")
        resp = api.claim_holding(
            ctx["compartment"]["id"],
            make_renter_headers("renter-impostor"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
