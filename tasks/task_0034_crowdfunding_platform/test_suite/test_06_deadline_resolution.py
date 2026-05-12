"""Deadline resolution: SUCCEEDED vs FAILED, project cancel cascade,
and the basic charge wave.

PRD references:
  - §3.5 Deadline Resolution
  - §3.6 The Charge Wave
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_seconds,
    advance_clock,
    drive_clock_past_deadline,
    emit_payment,
    get_order,
    get_project,
    make_initiator_headers,
    place_order,
    setup_live_project,
    setup_live_with_order,
    setup_succeeded_with_authorized_order,
    setup_zero_orders_at_deadline_aon,
    validate_success,
)


class TestDeadlineSucceededBranch:
    def test_aon_funding_target_met_transitions_to_succeeded(self, api):
        """PRD §3.5: 'If the project's funding_model is KEEP_IT_ALL, or if
        it is ALL_OR_NOTHING and provisional_raised_cents is at least
        funding_target_cents, the project transitions from LIVE to
        SUCCEEDED.'

        Claim: ALL_OR_NOTHING with provisional >= target → SUCCEEDED at
        deadline+1s.
        """
        ctx = setup_succeeded_with_authorized_order(
            funding_target_cents=5_000,
            reward_pledge_cents=10_000,
            deadline_hours_from_now=24.5,
        )
        drive_clock_past_deadline(project=ctx["project"], past_seconds=1)
        proj = get_project(ctx["project"]["id"])
        assert proj["status"] == "SUCCEEDED"

    def test_succeeded_transitions_orders_to_charge_pending(self, api):
        """PRD §3.5: 'The success transition opens the charge wave: for
        every order whose payment_status is AUTHORIZED on this project, a
        charge is enqueued and the order's payment_status is set to
        CHARGE_PENDING.'

        Claim: after SUCCEEDED transition, the previously-AUTHORIZED order
        is now CHARGE_PENDING.
        """
        ctx = setup_succeeded_with_authorized_order(
            funding_target_cents=5_000,
            reward_pledge_cents=10_000,
            deadline_hours_from_now=24.5,
        )
        drive_clock_past_deadline(project=ctx["project"], past_seconds=1)
        order = get_order(ctx["order"]["id"])
        assert order["payment_status"] == "CHARGE_PENDING"

    def test_keep_it_all_succeeds_even_below_target(self, api):
        """PRD §3.5: 'If the project's funding_model is KEEP_IT_ALL ... the
        project transitions from LIVE to SUCCEEDED.'

        Claim: KEEP_IT_ALL with provisional < target still SUCCEEDS at
        deadline+1s.
        """
        _, project, reward = setup_live_project(
            funding_model="KEEP_IT_ALL",
            funding_target_cents=1_000_000,
            reward_pledge_cents=1_000,
            reward_type="DIGITAL",
            deadline_hours_from_now=24.5,
        )
        # No orders placed; provisional == 0 < target.
        drive_clock_past_deadline(project=project, past_seconds=1)
        proj = get_project(project["id"])
        assert proj["status"] == "SUCCEEDED"


class TestDeadlineFailedBranch:
    def test_aon_below_target_transitions_to_failed(self, api):
        """PRD §3.5: 'If instead the project's funding_model is
        ALL_OR_NOTHING and provisional_raised_cents is strictly less than
        funding_target_cents, the project transitions from LIVE to
        FAILED.'

        Claim: ALL_OR_NOTHING with no orders at deadline → FAILED.
        """
        ctx = setup_zero_orders_at_deadline_aon()
        drive_clock_past_deadline(project=ctx["project"], past_seconds=1)
        proj = get_project(ctx["project"]["id"])
        assert proj["status"] == "FAILED"

    def test_failed_voids_authorized_orders(self, api):
        """PRD §3.5: 'The failure transition voids the entire authorized
        order pool: every order with payment_status AUTHORIZED on this
        project has its authorization voided and its payment_status set
        to VOIDED.'

        Claim: AUTHORIZED order on a project that fails → VOIDED.
        """
        _, project, reward = setup_live_project(
            funding_model="ALL_OR_NOTHING",
            funding_target_cents=10_000_000,  # very high; below-target failure
            reward_pledge_cents=1_000,
            reward_type="DIGITAL",
            deadline_hours_from_now=24.5,
        )
        from test_helpers import create_backer, place_order
        backer = create_backer()
        order = place_order(project=project, reward=reward, backer=backer)
        drive_clock_past_deadline(project=project, past_seconds=1)
        proj = get_project(project["id"])
        assert proj["status"] == "FAILED"
        order_now = get_order(order["id"])
        assert order_now["payment_status"] == "VOIDED"


class TestChargeWave:
    def test_charge_pending_to_charged_on_success(self, api):
        """PRD §3.6: 'From CHARGE_PENDING, a result of SUCCESS transitions
        the order to CHARGED'.

        Claim: payment SUCCESS on CHARGE_PENDING order → CHARGED.
        """
        ctx = setup_succeeded_with_authorized_order(
            funding_target_cents=5_000,
            reward_pledge_cents=10_000,
            deadline_hours_from_now=24.5,
        )
        drive_clock_past_deadline(project=ctx["project"], past_seconds=1)
        emit_payment(ctx["order"]["id"], "SUCCESS")
        o = get_order(ctx["order"]["id"])
        assert o["payment_status"] == "CHARGED"

    def test_charged_sets_refundable_remainder_to_order_total(self, api):
        """PRD §3.6: 'the order's refundable_remainder_cents is set to its
        order_total_cents (the entire order is refundable until any
        shipment)'.

        Claim: after CHARGE_CAPTURE finalizes, refundable_remainder_cents
        equals order_total_cents.
        """
        ctx = setup_succeeded_with_authorized_order(
            funding_target_cents=5_000,
            reward_pledge_cents=10_000,
            deadline_hours_from_now=24.5,
        )
        drive_clock_past_deadline(project=ctx["project"], past_seconds=1)
        emit_payment(ctx["order"]["id"], "SUCCESS")
        o = get_order(ctx["order"]["id"])
        assert o["refundable_remainder_cents"] == o["order_total_cents"]


class TestInitiatorCancel:
    def test_initiator_cancel_live_project_to_cancelled(self, api):
        """PRD §3.5: 'The initiator may also voluntarily cancel a LIVE
        project before its deadline by supplying an optional reason.
        Cancellation moves the project to terminal CANCELLED'.

        Claim: POST /projects/{id}/cancel on LIVE → CANCELLED.
        """
        initiator, project, _ = setup_live_project(
            category="TECH", reward_pledge_cents=1_000,
            reward_type="DIGITAL",
            funding_target_cents=10_000_000,
            deadline_hours_from_now=240.0,
        )
        res = api.cancel_project(
            project["id"], make_initiator_headers(initiator["id"]),
            {"reason": "Decided not to proceed"},
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CANCELLED"

    def test_cancel_voids_authorized_orders(self, api):
        """PRD §3.5: 'Cancellation moves the project to terminal CANCELLED
        and triggers a two-hop cascade: every AUTHORIZED order is voided'.

        Claim: AUTHORIZED order on cancelled project → VOIDED.
        """
        initiator, project, reward = setup_live_project(
            category="TECH", reward_pledge_cents=2_000,
            reward_type="DIGITAL", funding_target_cents=10_000_000,
            deadline_hours_from_now=240.0,
        )
        from test_helpers import create_backer
        backer = create_backer()
        order = place_order(project=project, reward=reward, backer=backer)
        api.cancel_project(
            project["id"], make_initiator_headers(initiator["id"])
        )
        o = get_order(order["id"])
        assert o["payment_status"] == "VOIDED"
