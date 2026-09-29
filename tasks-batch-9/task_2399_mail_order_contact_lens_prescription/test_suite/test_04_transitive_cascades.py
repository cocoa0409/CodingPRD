"""Multi-level cascades: one call that has to reach four entity types.

Each scenario walks the chain the PRD declares — prescription, hold, schedule,
order, claim and the customer's derived ledgers — and checks that every level
moved before the response came back.
"""

from test_helpers import (
    CO_ALPHA,
    assert_ledger_values,
    new_auto_reorder_schedule,
    new_order,
    set_clock,
    setup_dispute_upheld_cascade,
    setup_verified_prescription,
    validate_paginated,
    validate_success,
)

EXPIRY_DATE = "2026-09-10"
CLOCK_BEFORE_EXPIRY = "2026-09-08T10:00:00Z"
CLOCK_ON_EXPIRY_DATE = "2026-09-10T09:00:00Z"


def _expiring_prescription_with_order_and_schedule():
    """A verified prescription expiring 2026-09-10 that carries a PENDING order
    and an ACTIVE schedule, with the clock moved onto the expiry date so the
    sweep has work to do."""
    scenario = setup_verified_prescription(
        clock=CLOCK_BEFORE_EXPIRY,
        prescription_overrides={"expiry_date": EXPIRY_DATE},
    )
    scenario["order"] = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        1,
        1,
    )
    scenario["schedule"] = new_auto_reorder_schedule(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        boxes_per_run=3,
        anchor_date="2026-09-08",
    )
    set_clock(CLOCK_ON_EXPIRY_DATE)
    return scenario


class TestExpirySweepCascade:
    """Expiry reaches the prescription, a fresh hold, the schedule, the order and
    the customer's counters inside a single sweep."""

    def test_expiry_sweep_expires_the_prescription_and_opens_a_system_hold(
        self, api, compliance_headers
    ):
        """PRD §3.4: "Every prescription then in `VERIFIED_ACTIVE` whose
        `expiry_date` is at or before the current logical date moves to the
        terminal `EXPIRED`."
        PRD §3.4: "A reorder hold is opened with `reason` `PRESCRIPTION_EXPIRED`
        in `OPEN` status and `opened_by_user_id` set to `system`."
        PRD §3.4: "The sweep returns a summary rather than a resource:
        `promoted_prescription_ids` lists the prescriptions promoted in step one,
        `timed_out_request_ids` the verification requests that timed out,
        `expired_prescription_ids` the prescriptions expired in step two, and
        `holds_opened_count` and `schedules_paused_count` the totals across both
        steps."

        Design: Difficulty/transitive_cascade/expiry_sweep_cascades_through_hold_schedule_and_customer_ledger
        """
        scenario = _expiring_prescription_with_order_and_schedule()

        summary = validate_success(api.run_verification_sweep(compliance_headers))

        assert scenario["prescription"]["id"] in summary["expired_prescription_ids"]
        assert summary["holds_opened_count"] == 1
        assert summary["schedules_paused_count"] == 1

        prescription = validate_success(
            api.get_prescription(scenario["prescription"]["id"], compliance_headers)
        )
        assert prescription["status"] == "EXPIRED"

        holds, meta = validate_paginated(
            api.list_reorder_holds(
                compliance_headers,
                params={"customer_id": scenario["customer"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert holds[0]["reason"] == "PRESCRIPTION_EXPIRED"
        assert holds[0]["status"] == "OPEN"
        assert holds[0]["opened_by_user_id"] == "system"

    def test_expiry_sweep_pauses_the_schedule_blocks_the_order_and_reconciles_the_ledger(
        self, api, compliance_headers
    ):
        """PRD §3.4: "Every `ACTIVE` schedule on that prescription moves to
        `PAUSED` with `pause_reason` `HOLD_OPEN`."
        PRD §3.4: "Every order against that prescription whose
        `verification_state` is `RX_CLEARED` and whose `fulfillment_state` is
        `PENDING` moves to `RX_BLOCKED`, appending an `ORDER_BLOCKED` compliance
        event carrying the detail `prescription expired`."
        PRD §3.4: "An `RX_EXPIRED` compliance event is appended."
        PRD §3.4: "The affected customers' `open_hold_count`,
        `active_schedule_count` and `auto_reorder_enabled` are then reconciled."

        Design: Difficulty/transitive_cascade/expiry_sweep_cascades_through_hold_schedule_and_customer_ledger
        """
        scenario = _expiring_prescription_with_order_and_schedule()

        validate_success(api.run_verification_sweep(compliance_headers))

        schedule = validate_success(
            api.get_auto_reorder_schedule(scenario["schedule"]["id"], compliance_headers)
        )
        assert schedule["status"] == "PAUSED"
        assert schedule["pause_reason"] == "HOLD_OPEN"

        order = validate_success(
            api.get_order(scenario["order"]["id"], compliance_headers)
        )
        assert order["verification_state"] == "RX_BLOCKED"
        assert order["fulfillment_state"] == "PENDING"

        ledger = validate_success(
            api.get_customer_ledger(scenario["customer"]["id"], compliance_headers)
        )
        assert_ledger_values(
            ledger,
            open_hold_count=1,
            active_schedule_count=0,
        )
        assert ledger["auto_reorder_enabled"] is False

        events, _ = validate_paginated(
            api.list_compliance_events_for_prescription(
                scenario["prescription"]["id"],
                compliance_headers,
                params={"limit": 100},
            )
        )
        event_types = [event["event_type"] for event in events]
        assert "RX_EXPIRED" in event_types
        blocked = [event for event in events if event["event_type"] == "ORDER_BLOCKED"]
        assert len(blocked) == 1
        assert blocked[0]["detail"] == "prescription expired"


class TestDisputeUpheldCascade:
    """Upholding a dispute invalidates the prescription, splits pending orders
    from shipped ones, voids the paperwork and settles every ledger."""

    def test_upheld_dispute_invalidates_prescription_and_sorts_orders_by_fulfillment(
        self, api, compliance_headers
    ):
        """PRD §3.9: "Both branches set the dispute's `resolution` and
        `resolved_by_user_id` and append a `DISPUTE_RESOLVED` compliance event,
        and both are declared only from `OPEN`."
        PRD §3.9: "The prescription is driven from `VERIFIED_ACTIVE` to the
        terminal `INVALIDATED` and an `RX_INVALIDATED` compliance event is
        appended."
        PRD §3.9: "Every order against that prescription whose
        `fulfillment_state` is `PENDING` is cancelled with `cancellation_reason`
        `DISPUTE_UPHELD`, processed in `created_at` ascending order, and each such
        cancellation applies the same compensating ledger work as a
        patient-initiated cancellation: the prescription's `boxes_consumed` is
        reduced by that order's boxes and the customer's charge and cash figures
        are reconciled."
        PRD §3.9: "Every order against that prescription whose
        `fulfillment_state` is `SHIPPED` or `DELIVERED` cannot be cancelled — the
        lenses are already in the post — so instead its `recall_flagged` flag is
        set to true, marking it for physical recall."

        Design: Difficulty/transitive_cascade/dispute_upheld_cascades_into_cancellation_and_claim_void
        """
        scenario = setup_dispute_upheld_cascade()

        dispute = validate_success(
            api.resolve_prescriber_dispute(
                scenario["dispute"]["id"], {"resolution": "UPHELD"}, compliance_headers
            )
        )
        assert dispute["status"] == "UPHELD"
        assert dispute["resolution"] == "UPHELD"
        assert dispute["resolved_by_user_id"] == CO_ALPHA

        prescription = validate_success(
            api.get_prescription(scenario["prescription"]["id"], compliance_headers)
        )
        assert prescription["status"] == "INVALIDATED"
        assert prescription["boxes_consumed"] == 2

        pending_order = validate_success(
            api.get_order(scenario["pending_order"]["id"], compliance_headers)
        )
        assert pending_order["fulfillment_state"] == "CANCELLED"
        assert pending_order["cancellation_reason"] == "DISPUTE_UPHELD"
        assert pending_order["recall_flagged"] is False

        delivered_order = validate_success(
            api.get_order(scenario["delivered_order"]["id"], compliance_headers)
        )
        assert delivered_order["fulfillment_state"] == "DELIVERED"
        assert delivered_order["recall_flagged"] is True

    def test_upheld_dispute_voids_the_generated_claim_and_releases_the_allowance(
        self, api, compliance_headers
    ):
        """PRD §3.9: "Every reimbursement claim on those cancelled or
        recall-flagged orders whose `status` is `DRAFT`, `GENERATED` or
        `SUBMITTED` is voided with `voided_reason` `DISPUTE_UPHELD`, each
        releasing its `applied_allowance_cents` back to the allowance ledger and
        appending a `CLAIM_VOIDED` compliance event."
        PRD §3.9: "Finally the affected customer's `allowance_used_cents`,
        `lifetime_charged_cents` and `net_cash_position_cents` are all
        reconciled, so that INV_MONEY, INV_ALLOWANCE and INV_BOXES all hold again
        the instant the response is returned."
        PRD §2.7: "`allowance_remaining_cents` is the plan's
        `annual_allowance_cents` less `allowance_used_cents`, floored at zero; for
        a self-pay customer who carries no `insurance_plan_id` it is zero."

        Design: Difficulty/transitive_cascade/dispute_upheld_cascades_into_cancellation_and_claim_void
        """
        scenario = setup_dispute_upheld_cascade()
        assert scenario["claim"]["applied_allowance_cents"] == 6400

        validate_success(
            api.resolve_prescriber_dispute(
                scenario["dispute"]["id"], {"resolution": "UPHELD"}, compliance_headers
            )
        )

        claim = validate_success(
            api.get_reimbursement_claim(scenario["claim"]["id"], compliance_headers)
        )
        assert claim["status"] == "VOIDED"
        assert claim["voided_reason"] == "DISPUTE_UPHELD"
        assert claim["applied_allowance_cents"] == 6400

        ledger = validate_success(
            api.get_customer_ledger(scenario["customer"]["id"], compliance_headers)
        )
        assert_ledger_values(
            ledger,
            lifetime_charged_cents=6400,
            net_cash_position_cents=6400,
            allowance_used_cents=0,
            allowance_remaining_cents=15000,
        )
