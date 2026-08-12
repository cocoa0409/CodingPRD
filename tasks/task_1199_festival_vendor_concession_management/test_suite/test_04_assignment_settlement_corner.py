"""Corner: booth-assignment and settlement transition rules."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_festival,
    api_client,
    confirm_assignment,
    create_settlement,
    provision_assignment,
    record_inspection,
    release_assignment,
    report_sale,
    set_clock,
    setup_active_assignment,
    setup_confirmed_assignment,
    setup_curated_with_booth,
    setup_reconciled_settlement,
    setup_reserved_assignment,
    validate_error,
    validate_success,
    get_booth,
    make_vendor_headers,
    reconcile_settlement,
)

OPS = TEST_USERS["ops_headers"]
FIN1 = TEST_USERS["finance_headers"]


class TestConfirmFeeSnapshot:
    def test_assignment_confirm_pins_fee_snapshot(self, api):
        """PRD §3.3: "Confirming the assignment moves it from `RESERVED` to
        `CONFIRMED` and pins a fee-terms snapshot from the application's curated
        terms onto the assignment's `fee_model`, `flat_fee_cents`,
        `revenue_share_pct_bp`, `tier_mode`, `minimum_guarantee_cents`, and
        `free_allowance_cents`; the booth moves from `RESERVED` to `ASSIGNED`."

        Design: Corner/state_machines/assignment_confirm_pins_fee_snapshot
        """
        scen = setup_reserved_assignment(
            name="Pin Fest", fee_model="HYBRID",
            terms={"flat_fee_cents": 80000, "revenue_share_pct_bp": 1200,
                   "minimum_guarantee_cents": 100000, "free_allowance_cents": 150000},
            proposed_flat_fee_cents=80000, proposed_revenue_share_pct_bp=1200,
        )
        data = confirm_assignment(scen["assignment"]["id"])
        assert data["fee_model"] == "HYBRID"
        assert data["flat_fee_cents"] == 80000
        assert data["revenue_share_pct_bp"] == 1200
        assert data["minimum_guarantee_cents"] == 100000
        assert data["free_allowance_cents"] == 150000
        booth = get_booth(scen["booth"]["id"])
        assert booth["status"] == "ASSIGNED"


class TestReleaseFromConfirmed:
    def test_assignment_release_from_confirmed_frees_booth(self, api):
        """PRD §3.3: "Releasing an assignment from `RESERVED` or `CONFIRMED` moves
        it to `RELEASED`, returns the booth to `AVAILABLE`, decrements the zone's
        reserved totals, and runs a waitlist promotion pass for the festival and
        freed zone (§3.5)."

        Design: Corner/state_machines/assignment_release_from_confirmed_frees_booth
        """
        scen = setup_confirmed_assignment(name="Free Fest")
        data = release_assignment(scen["assignment"]["id"])
        assert data["status"] == "RELEASED"
        booth = get_booth(scen["booth"]["id"])
        assert booth["status"] == "AVAILABLE", "booth freed from ASSIGNED on release"


class TestActivateUtilityGate:
    def test_assignment_activate_without_provisioning_rejected(self, api):
        """PRD §3.4: "Utilities must already be provisioned — `utility_status`
        `PENDING` yields `ERR_UTILITIES_NOT_PROVISIONED`."

        Design: Corner/state_machines/assignment_activate_without_provisioning_rejected
        """
        scen = setup_confirmed_assignment(name="Util Fest")
        asg_id = scen["assignment"]["id"]
        record_inspection(asg_id, "HEALTH_PREOPEN", "PASS")
        set_clock(scen["festival"]["event_start"])
        advance_festival(scen["festival"]["id"], "LIVE")
        resp = api.activate_assignment(asg_id, OPS)
        validate_error(resp, ApiErrorId.ERR_UTILITIES_NOT_PROVISIONED)


class TestPosAssignmentGate:
    def test_pos_report_on_non_active_assignment_rejected(self, api):
        """PRD §3.6: "the assignment must be `ACTIVE`, otherwise
        `ERR_INVALID_STATE_TRANSITION`".

        Design: Corner/state_machines/pos_report_on_non_active_assignment_rejected
        """
        scen = setup_confirmed_assignment(name="Pos Gate Fest")
        asg_id = scen["assignment"]["id"]
        provision_assignment(asg_id)
        record_inspection(asg_id, "HEALTH_PREOPEN", "PASS")
        set_clock(scen["festival"]["event_start"])
        advance_festival(scen["festival"]["id"], "LIVE")
        resp = api.create_transaction(
            {"assignment_id": asg_id, "amount_cents": 1000,
             "occurred_at": "2026-07-10T14:00:00Z", "idempotency_key": "pg-early"},
            make_vendor_headers(scen["vendor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestSettlementMarkPaidGate:
    def test_settlement_markpaid_before_finalize_rejected(self, api):
        """PRD §3.6: "Once finalized, a `FinanceLead` marks the settlement
        `PAID`."
        PRD §2.10: "Eighth, state-machine legality of the requested transition,
        including terminal-state lockdown, together with request-shape validity —
        missing required fields, malformed values, and enum violations surface as
        `ERR_INVALID_REQUEST` (HTTP 400), while an illegal transition surfaces as
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409) (8)."

        Design: Corner/state_machines/settlement_markpaid_before_finalize_rejected
        """
        scen = setup_reconciled_settlement(sale_amounts=[50000], name="SkipPay Fest")
        assert scen["settlement"]["status"] == "RECONCILING"
        resp = api.mark_paid_settlement(scen["settlement"]["id"], FIN1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
