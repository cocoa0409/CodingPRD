"""Difficulty: cross_entity_state_dependency — inspection gate, fine gate, settlement gate."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_festival,
    api_client,
    issue_fine,
    mark_paid_settlement,
    move_to_settlement_phase,
    provision_assignment,
    record_inspection,
    respond_fine,
    set_clock,
    setup_confirmed_assignment,
    setup_finalized_settlement,
    setup_reconciled_settlement,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]
FIN1 = TEST_USERS["finance_headers"]


class TestActivateInspectionGate:
    def test_latest_preopen_fail_blocks_then_pass_unblocks(self, api):
        """PRD §3.4: "The latest `HEALTH_PREOPEN` inspection for the assignment —
        latest meaning the greatest `created_at` — must have `result` `PASS`; if
        no pre-open inspection exists, or the latest one is `CONDITIONAL_PASS` or
        `FAIL`, activation is rejected with `ERR_PREOPEN_INSPECTION_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/activate_requires_latest_preopen_pass
        """
        scen = setup_confirmed_assignment(name="Gate Fest")
        asg_id = scen["assignment"]["id"]
        provision_assignment(asg_id)
        record_inspection(asg_id, "HEALTH_PREOPEN", "FAIL")
        set_clock(scen["festival"]["event_start"])
        advance_festival(scen["festival"]["id"], "LIVE")

        resp = api.activate_assignment(asg_id, OPS)
        validate_error(resp, ApiErrorId.ERR_PREOPEN_INSPECTION_MISSING)

        record_inspection(asg_id, "HEALTH_PREOPEN", "PASS")  # later record supersedes
        data = validate_success(api.activate_assignment(asg_id, OPS))
        assert data["status"] == "ACTIVE", "latest-record semantics — the PASS supersedes the FAIL"

    def test_no_preopen_inspection_at_all_blocks_activation(self, api):
        """PRD §3.4: "if no pre-open inspection exists, or the latest one is
        `CONDITIONAL_PASS` or `FAIL`, activation is rejected with
        `ERR_PREOPEN_INSPECTION_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/activate_requires_latest_preopen_pass
        """
        scen = setup_confirmed_assignment(name="Gate Fest None")
        asg_id = scen["assignment"]["id"]
        provision_assignment(asg_id)
        record_inspection(asg_id, "FIRE_SAFETY", "PASS")  # not a HEALTH_PREOPEN
        set_clock(scen["festival"]["event_start"])
        advance_festival(scen["festival"]["id"], "LIVE")
        resp = api.activate_assignment(asg_id, OPS)
        validate_error(resp, ApiErrorId.ERR_PREOPEN_INSPECTION_MISSING)


class TestFinalizeFineGate:
    def test_issued_fine_blocks_finalize(self, api):
        """PRD §3.6: "No fine of the assignment may remain in `ISSUED` or
        `DISPUTED` — liability must be resolved first, otherwise
        `ERR_FINES_UNRESOLVED`".

        Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_issued_fine
        """
        scen = setup_reconciled_settlement(
            sale_amounts=[100000], fee_model="REVENUE_SHARE",
            terms={"revenue_share_pct_bp": 1000, "tier_mode": "MARGINAL"},
            name="Fine Gate Fest",
        )
        issue_fine(scen["assignment"]["id"], type="COMPOST_CONTAMINATION", amount_cents=10000)
        move_to_settlement_phase(scen)
        resp = api.finalize_settlement(scen["settlement"]["id"], TEST_USERS["finance2_headers"])
        validate_error(resp, ApiErrorId.ERR_FINES_UNRESOLVED)

    def test_acknowledged_fine_unblocks_and_deducts(self, api):
        """PRD §3.6: "fines in `ACKNOWLEDGED` are allowed and will be deducted."
        PRD §3.6: "`fine_deduction_cents` is the sum of `amount_cents` of the
        assignment's fines in `ACKNOWLEDGED` at finalize time".

        Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_issued_fine
        """
        scen = setup_reconciled_settlement(
            sale_amounts=[100000], fee_model="REVENUE_SHARE",
            terms={"revenue_share_pct_bp": 1000, "tier_mode": "MARGINAL"},
            name="Fine Gate Fest",
        )
        fine = issue_fine(scen["assignment"]["id"], type="COMPOST_CONTAMINATION", amount_cents=10000)
        respond_fine(fine["id"], scen["vendor"], "ACKNOWLEDGED")
        move_to_settlement_phase(scen)
        fin = validate_success(
            api.finalize_settlement(scen["settlement"]["id"], TEST_USERS["finance2_headers"])
        )
        assert fin["status"] == "FINALIZED"
        assert fin["fine_deduction_cents"] == 10000
        # gross 100000 - share 10000 - deduction 10000
        assert fin["vendor_payout_cents"] == 80000


class TestFestivalCloseGate:
    def test_finalized_settlement_is_not_enough_to_close(self, api):
        """PRD §3.6: "Closing the festival — advancing from `SETTLEMENT` to
        `CLOSED` — requires every settlement of the festival to be `PAID`,
        otherwise `ERR_SETTLEMENTS_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/festival_close_requires_all_settlements_paid
        """
        scen = setup_finalized_settlement(sale_amounts=[80000], name="Close Fest")
        assert scen["settlement"]["status"] == "FINALIZED"
        resp = api.advance_festival_status(scen["festival"]["id"], {"to_status": "CLOSED"},
                                           TEST_USERS["director_headers"])
        validate_error(resp, ApiErrorId.ERR_SETTLEMENTS_OPEN)

    def test_mark_paid_unblocks_festival_close(self, api):
        """PRD §3.6: "Once finalized, a `FinanceLead` marks the settlement
        `PAID`."
        PRD §3.6: "Closing the festival — advancing from `SETTLEMENT` to
        `CLOSED` — requires every settlement of the festival to be `PAID`,
        otherwise `ERR_SETTLEMENTS_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/festival_close_requires_all_settlements_paid
        """
        scen = setup_finalized_settlement(sale_amounts=[80000], name="Close Fest")
        mark_paid_settlement(scen["settlement"]["id"])
        data = advance_festival(scen["festival"]["id"], "CLOSED")
        assert data["status"] == "CLOSED"
