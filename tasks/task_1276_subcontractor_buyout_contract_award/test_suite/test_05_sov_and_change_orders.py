"""Schedule-of-values allocation and lifecycle, and change-order authority,
segregation of duties, and approve/void compensation."""
import pytest

from test_helpers import (
    BL,
    OM,
    ApiErrorId,
    api_client,
    assert_sov_lines_balance,
    award_sub,
    create_and_submit_co,
    create_draft_subcontract,
    create_open_project,
    execute_sub,
    get_success_data,
    issue_sub,
    make_buyout_lead_headers,
    make_project_manager_headers,
    recommend,
    register_compliant_cert,
    setup_awarded_subcontract,
    setup_executed_subcontract,
    setup_executed_with_approved_sov,
    setup_issued_subcontract,
    setup_leveling_package,
    validate_error,
    validate_success,
    withdraw_bid,
)

# Authority tiers used by the change-order scenarios: a bounded ProjectManager
# tier beneath an unlimited OperationsManager tier.
PM_LIMITED_TIERS = [
    {"max_value_cents": 2_500_000, "max_cumulative_pct": 0.10,
     "roles": ["ProjectManager"]},
    {"max_value_cents": -1, "max_cumulative_pct": -1,
     "roles": ["OperationsManager"]},
]


def _issued(name, number, trade_code, **kwargs):
    proj, proj_v = create_open_project(name, number)
    ctx = setup_issued_subcontract(
        proj["id"], proj_v, name=name, trade_code=trade_code, **kwargs)
    return proj, ctx


class TestSovAllocationRounding:

    def _executed_at_100000(self):
        proj, proj_v = create_open_project("P-CF1", "CF1")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="CF1", trade_code="CF1-05",
            budget=200_000,
            bids=((100_000, "2026-05-15T12:00:00Z"),
                  (110_000, "2026-05-15T13:00:00Z")),
        )
        sub = create_draft_subcontract(
            ctx["package"]["id"], ctx["bids"][0]["id"], "Delta Plumb")
        recommend(sub["id"], 100_000)
        award_sub(sub["id"])
        register_compliant_cert(sub["id"], certificate_number="CERT-CF1")
        issue_sub(sub["id"])
        execute_sub(sub["id"])
        return sub

    def test_sov_cumulative_difference_rounding_per_line(self):
        """PRD section 3.8: "Otherwise the allocation proceeds by cumulative
        difference: for every line except the last, compute the cumulative
        weight through that line, multiply the subcontract's
        `contract_value_cents` by that cumulative weight divided by W, and
        round half-up to integer cents; each such line's
        `allocated_amount_cents` is the difference between its own cumulative
        rounded figure and the previous line's cumulative rounded figure (the
        first line's previous cumulative figure is 0). The final line absorbs
        the remainder: its `allocated_amount_cents` is the
        `contract_value_cents` minus the last computed cumulative rounded
        figure."

        Design: Difficulty/combinatorial_formula/sov_line_rounding_per_line_then_sum_vs_sum_then_round
        """
        sub = self._executed_at_100000()
        resp = api_client.create_sov(
            sub["id"],
            {"lines": [
                {"wbs_code": "01", "description": "Mobilization",
                 "weight_numerator": 10},
                {"wbs_code": "02", "description": "Labor",
                 "weight_numerator": 10},
                {"wbs_code": "03", "description": "Material",
                 "weight_numerator": 10},
            ]},
            BL,
        )
        data = validate_success(resp, expected_status=201)
        lines = data["lines"]
        # cum_round_1 = round_half_up(100000*10/30) = 33333
        assert lines[0]["allocated_amount_cents"] == 33_333
        # cum_round_2 = round_half_up(100000*20/30) = 66667; 66667-33333
        assert lines[1]["allocated_amount_cents"] == 33_334
        # last line absorbs the remainder: 100000 - 66667
        assert lines[2]["allocated_amount_cents"] == 33_333

    def test_sov_allocation_balances_exactly_and_lands_balanced(self):
        """PRD section 3.8: "Rounding each line's share independently and
        summing is expressly forbidden — that order drifts below the contract
        value on indivisible cent counts. When the allocation balances, the
        schedule transitions `DRAFT → BALANCED` on submission".

        Design: Difficulty/combinatorial_formula/sov_line_rounding_per_line_then_sum_vs_sum_then_round
        """
        sub = self._executed_at_100000()
        resp = api_client.create_sov(
            sub["id"],
            {"lines": [
                {"wbs_code": "01", "description": "Mobilization",
                 "weight_numerator": 10},
                {"wbs_code": "02", "description": "Labor",
                 "weight_numerator": 10},
                {"wbs_code": "03", "description": "Material",
                 "weight_numerator": 10},
            ]},
            BL,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "BALANCED"
        assert_sov_lines_balance(data, 100_000)

    def test_sov_zero_weight_rejected(self):
        """PRD section 3.8: "The submission is rejected with
        `ERR_SOV_IMBALANCE` when W is zero or negative, or when any line's
        `weight_numerator` is less than 1."

        Design: Corner/calculations/sov_zero_weight_rejected
        """
        _proj, ctx = _issued("P-C6", "C6", "C6-26")
        resp = api_client.create_sov(
            ctx["subcontract"]["id"],
            {"lines": [
                {"wbs_code": "01", "description": "Zero weight",
                 "weight_numerator": 0},
                {"wbs_code": "02", "description": "Rest",
                 "weight_numerator": 1},
            ]},
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_SOV_IMBALANCE)


class TestSovLifecycle:

    def _executed_with_rejected_sov(self):
        proj, proj_v = create_open_project("P-NL2", "NL2")
        ctx = setup_executed_subcontract(
            proj["id"], proj_v, name="NL2", trade_code="NL2-09")
        sub_id = ctx["subcontract"]["id"]
        sov = validate_success(api_client.create_sov(
            sub_id,
            {"lines": [
                {"wbs_code": "01", "description": "Gear",
                 "weight_numerator": 50},
                {"wbs_code": "02", "description": "Labor",
                 "weight_numerator": 50},
            ]},
            BL,
        ), expected_status=201)
        validate_success(api_client.reject_sov(
            sov["id"], {"reason": "front-loaded mobilization"}, OM))
        return proj, sub_id, sov

    def test_sov_revision_cycle_increments_revision_and_rebalances(self):
        """PRD section 3.8: "A `BuyoutLead` then revises it, moving it into
        the `REVISED` state (`REJECTED → REVISED`) and incrementing
        `revision_number` by 1 — and the revised submission re-runs the
        allocation, landing back in `BALANCED` with `sov_status` restored."

        Design: Difficulty/non_linear_state_machine/sov_revision_cycle_balanced_rejected_revised_balanced_reapprove
        """
        _proj, _sub_id, sov = self._executed_with_rejected_sov()
        resp = api_client.revise_sov(
            sov["id"],
            {"lines": [
                {"wbs_code": "01", "description": "Gear",
                 "weight_numerator": 40},
                {"wbs_code": "02", "description": "Labor",
                 "weight_numerator": 60},
            ]},
            BL,
        )
        data = validate_success(resp)
        assert data["revision_number"] == 1, \
            "REVISED hop incremented revision_number"
        assert data["status"] == "BALANCED", \
            "revise re-ran the allocation and landed BALANCED"

    def test_sov_approve_stamps_clock_and_bubbles_to_subcontract(self):
        """PRD section 3.8: "Approval moves `BALANCED → APPROVED`, stamps
        `approved_at` from the project logical clock, and sets `sov_status`
        to `APPROVED`."

        Design: Difficulty/non_linear_state_machine/sov_revision_cycle_balanced_rejected_revised_balanced_reapprove
        """
        proj, sub_id, sov = self._executed_with_rejected_sov()
        validate_success(api_client.revise_sov(
            sov["id"],
            {"lines": [
                {"wbs_code": "01", "description": "Gear",
                 "weight_numerator": 40},
                {"wbs_code": "02", "description": "Labor",
                 "weight_numerator": 60},
            ]},
            BL,
        ))
        approved = validate_success(api_client.approve_sov(sov["id"], OM))
        assert approved["status"] == "APPROVED"
        proj_after = get_success_data(api_client.get_project(proj["id"], BL))
        assert approved["approved_at"] == proj_after["current_time_utc"], \
            "approved_at is stamped from the project logical clock"
        sub = get_success_data(api_client.get_subcontract(sub_id, BL))
        assert sub["sov_status"] == "APPROVED", \
            "approval bubbles up onto the parent subcontract"

    def test_sov_approve_from_rejected_rejected(self):
        """PRD section 3.8: "Rejecting a balanced schedule moves it
        `BALANCED → REJECTED` (with a mandatory `reason`)" and "Approval
        moves `BALANCED → APPROVED`".

        Design: Corner/state_machines/sov_approve_from_rejected_rejected
        """
        _proj, _sub_id, sov = self._executed_with_rejected_sov()
        resp = api_client.approve_sov(sov["id"], OM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_sov_blocked_when_source_bid_withdrawn(self):
        """PRD section 3.8: "Submission is refused when the source bid has
        been `WITHDRAWN` (`ERR_BID_WITHDRAWN_SOV_BLOCKED`)".

        Design: Corner/validations/sov_blocked_when_source_bid_withdrawn
        """
        proj, proj_v = create_open_project("P-V14", "V14")
        ctx = setup_issued_subcontract(
            proj["id"], proj_v, name="V14", trade_code="V14-26")
        pkg = ctx["package"]
        bid = ctx["bid"]
        withdraw_bid(pkg["id"], bid["id"])
        resp = api_client.create_sov(
            ctx["subcontract"]["id"],
            {"lines": [{"wbs_code": "01", "description": "All",
                        "weight_numerator": 1}]},
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_BID_WITHDRAWN_SOV_BLOCKED)

    def test_sov_status_mirrors_schedule_lifecycle(self):
        """PRD section 3.8: "When the allocation balances, the schedule
        transitions `DRAFT → BALANCED` on submission (or `REVISED →
        BALANCED` on a revise) and the subcontract's `sov_status` becomes
        `BALANCED`."
        PRD section 3.8: "Approval moves `BALANCED → APPROVED`, stamps
        `approved_at` from the project logical clock, and sets `sov_status`
        to `APPROVED`."

        Design: Corner/cross_cutting_layers/layer_derived_field_reconciliation_sov_status
        """
        proj, proj_v = create_open_project("P-L1", "L1")
        ctx = setup_executed_subcontract(
            proj["id"], proj_v, name="L1", trade_code="L1-26")
        sub_id = ctx["subcontract"]["id"]
        pre = get_success_data(api_client.get_subcontract(sub_id, BL))
        assert pre["sov_status"] == "DRAFT", "no SOV yet"
        sov = validate_success(api_client.create_sov(
            sub_id,
            {"lines": [{"wbs_code": "01", "description": "All",
                        "weight_numerator": 1}]},
            BL,
        ), expected_status=201)
        mid = get_success_data(api_client.get_subcontract(sub_id, BL))
        assert mid["sov_status"] == "BALANCED", \
            "derived field updated by submit"
        validate_success(api_client.approve_sov(sov["id"], OM))
        post = get_success_data(api_client.get_subcontract(sub_id, BL))
        assert post["sov_status"] == "APPROVED", \
            "derived field updated by approve"


class TestChangeOrderGates:

    def test_change_order_create_on_issued_subcontract_rejected(self):
        """PRD section 3.8: "A change order is created — by a `BuyoutLead`,
        a `ProjectManager`, or a `SupplierDiversity` officer — against an
        `EXECUTED` subcontract (else `ERR_INVALID_STATE_TRANSITION`)".

        Design: Difficulty/cross_entity_state_dependency/change_order_create_gated_on_subcontract_executed_and_sov_approved
        """
        _proj, ctx = _issued("P-CE2", "CE2", "CE2-26")
        resp = api_client.create_change_order(
            ctx["subcontract"]["id"],
            {"description": "CO on ISSUED sub", "amount_cents": 100_000},
            make_buyout_lead_headers("bl-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_change_order_create_without_approved_sov_rejected(self):
        """PRD section 3.8: "Only an `APPROVED` schedule unlocks change-order
        work: creating a change order against a subcontract whose
        `sov_status` is anything else is rejected with
        `ERR_SOV_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/change_order_create_gated_on_subcontract_executed_and_sov_approved
        """
        proj, proj_v = create_open_project("P-CE2B", "CE2B")
        ctx = setup_executed_subcontract(
            proj["id"], proj_v, name="CE2B", trade_code="CE2B-26")
        resp = api_client.create_change_order(
            ctx["subcontract"]["id"],
            {"description": "CO on EXECUTED sub without SOV",
             "amount_cents": 100_000},
            make_buyout_lead_headers("bl-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SOV_NOT_APPROVED)

    def test_co_approve_from_draft_rejected(self):
        """PRD section 3.8: "A `BuyoutLead` submits it, moving the order
        into the `PENDING_APPROVAL` state (`DRAFT → PENDING_APPROVAL`)" and
        "On approval, the order moves `PENDING_APPROVAL → APPROVED`".

        Design: Corner/state_machines/co_approve_from_draft_rejected
        """
        proj, proj_v = create_open_project("P-S12", "S12")
        ctx = setup_executed_with_approved_sov(
            proj["id"], proj_v, name="S12", trade_code="S12-26",
            change_authority_limits=PM_LIMITED_TIERS)
        resp = api_client.create_change_order(
            ctx["subcontract"]["id"],
            {"description": "CO left in draft", "amount_cents": 100_000},
            make_buyout_lead_headers("bl-1"),
        )
        co = validate_success(resp, expected_status=201)
        resp = api_client.approve_change_order(
            co["id"], make_project_manager_headers("pm-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_co_approve_over_per_co_tier_rejected(self):
        """PRD section 3.8: "The per-order check follows: if the best tier's
        `max_value_cents` is not -1 and the order's `amount_cents` exceeds
        it, the rejection is `ERR_CO_AUTHORITY_EXCEEDED`."

        Design: Corner/validations/co_approve_over_per_co_tier_rejected
        """
        proj, proj_v = create_open_project("P-V12", "V12")
        ctx = setup_executed_with_approved_sov(
            proj["id"], proj_v, name="V12", trade_code="V12-26",
            budget=12_000_000, bid_amount=10_000_000,
            contract_value_cents=10_000_000,
            change_authority_limits=PM_LIMITED_TIERS)
        co = create_and_submit_co(
            ctx["subcontract"]["id"], 3_000_000,
            make_buyout_lead_headers("bl-1"), description="over PM tier")
        resp = api_client.approve_change_order(
            co["id"], make_project_manager_headers("pm-1"))
        validate_error(resp, ApiErrorId.ERR_CO_AUTHORITY_EXCEEDED)
        after = get_success_data(api_client.get_change_order(co["id"], BL))
        assert after["status"] == "PENDING_APPROVAL", "no drift"

    def test_co_approve_by_creator_rejected(self):
        """PRD section 3.8: "At approval time the server first checks
        segregation of duties: if the approver's `X-User-ID` equals the
        order's `created_by_user_id`, the approval is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/co_approve_by_creator_rejected
        """
        proj, proj_v = create_open_project("P-V13", "V13")
        ctx = setup_executed_with_approved_sov(
            proj["id"], proj_v, name="V13", trade_code="V13-26",
            budget=12_000_000, bid_amount=10_000_000,
            contract_value_cents=10_000_000,
            change_authority_limits=PM_LIMITED_TIERS)
        resp = api_client.create_change_order(
            ctx["subcontract"]["id"],
            {"description": "self-approval probe", "amount_cents": 100_000},
            make_project_manager_headers("pm-1"),
        )
        co = validate_success(resp, expected_status=201)
        validate_success(api_client.submit_change_order(co["id"], BL))
        resp = api_client.approve_change_order(
            co["id"], make_project_manager_headers("pm-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_success_data(api_client.get_change_order(co["id"], BL))
        assert after["status"] == "PENDING_APPROVAL", "no drift"


class TestCumulativeAuthorityBoundary:

    def _boundary_setup(self):
        """EXECUTED subcontract at 10_000_000, SOV APPROVED, PM tier
        {max_value 2_500_000, max_cumulative_pct 0.10} + unlimited OM tier."""
        proj, proj_v = create_open_project("P-BP1", "BP1")
        ctx = setup_executed_with_approved_sov(
            proj["id"], proj_v, name="BP1", trade_code="BP1-26",
            budget=12_000_000, bid_amount=10_000_000,
            contract_value_cents=10_000_000,
            change_authority_limits=PM_LIMITED_TIERS)
        return ctx

    def test_cumulative_ratio_exactly_at_ten_percent_passes(self):
        """PRD section 3.8: "if the best tier's `max_cumulative_pct` is not
        -1 and the ratio of the subcontract's `cumulative_co_cents` plus this
        order's `amount_cents` to its `contract_value_cents` exceeds the
        tier's `max_cumulative_pct` — compared in exact rational arithmetic,
        with a ratio exactly equal to the limit passing — the rejection is
        `ERR_CO_CUMULATIVE_LIMIT`."

        Design: Difficulty/boundary_precision_check/authority_cumulative_ratio_exactly_at_ten_percent_boundary
        """
        ctx = self._boundary_setup()
        sub_id = ctx["subcontract"]["id"]
        co1 = create_and_submit_co(sub_id, 1_000_000,
                                   make_buyout_lead_headers("bl-1"),
                                   description="CO-1 at the boundary")
        approved = validate_success(api_client.approve_change_order(
            co1["id"], make_project_manager_headers("pm-1")))
        assert approved["status"] == "APPROVED", (
            "cumulative ratio (0+1000000)/10000000 == 0.10 exactly — "
            "boundary is inclusive"
        )
        co2 = create_and_submit_co(sub_id, 100_000,
                                   make_buyout_lead_headers("bl-1"),
                                   description="CO-2 still at the boundary")
        approved2 = validate_success(api_client.approve_change_order(
            co2["id"], make_project_manager_headers("pm-1")))
        assert approved2["status"] == "APPROVED", (
            "ratio (1000000+100000)/11000000 == 0.10 exactly — the moving "
            "denominator keeps the boundary reachable"
        )
        sub = get_success_data(api_client.get_subcontract(sub_id, BL))
        assert sub["cumulative_co_cents"] == 1_100_000
        # PRD 3.8: each approval increases contract_value_cents by
        # amount_cents — 10_000_000 + 1_000_000 + 100_000.
        assert sub["contract_value_cents"] == 11_100_000

    def test_one_cent_over_cumulative_boundary_rejected(self):
        """PRD section 3.8: "if the best tier's `max_cumulative_pct` is not
        -1 and the ratio of the subcontract's `cumulative_co_cents` plus this
        order's `amount_cents` to its `contract_value_cents` exceeds the
        tier's `max_cumulative_pct` — compared in exact rational arithmetic,
        with a ratio exactly equal to the limit passing — the rejection is
        `ERR_CO_CUMULATIVE_LIMIT`."

        Design: Difficulty/boundary_precision_check/authority_cumulative_ratio_exactly_at_ten_percent_boundary
        """
        ctx = self._boundary_setup()
        sub_id = ctx["subcontract"]["id"]
        co1 = create_and_submit_co(sub_id, 1_000_000,
                                   make_buyout_lead_headers("bl-1"),
                                   description="CO-1 at the boundary")
        validate_success(api_client.approve_change_order(
            co1["id"], make_project_manager_headers("pm-1")))
        co2 = create_and_submit_co(sub_id, 100_000,
                                   make_buyout_lead_headers("bl-1"),
                                   description="CO-2 still at the boundary")
        validate_success(api_client.approve_change_order(
            co2["id"], make_project_manager_headers("pm-1")))

        co3 = create_and_submit_co(sub_id, 100_001,
                                   make_buyout_lead_headers("bl-1"),
                                   description="CO-3 one unit over cumulative")
        resp = api_client.approve_change_order(
            co3["id"], make_project_manager_headers("pm-1"))
        validate_error(resp, ApiErrorId.ERR_CO_CUMULATIVE_LIMIT)
        after = get_success_data(api_client.get_change_order(co3["id"], BL))
        assert after["status"] == "PENDING_APPROVAL", (
            "rejected approval leaves the CO pending; no contract-value "
            "mutation"
        )


class TestApproveVoidCompensation:

    def _void_setup(self):
        proj, proj_v = create_open_project("P-CI2", "CI2")
        ctx = setup_executed_with_approved_sov(
            proj["id"], proj_v, name="CI2", trade_code="CI2-09",
            budget=12_000_000, bid_amount=10_000_000,
            contract_value_cents=10_000_000,
            change_authority_limits=PM_LIMITED_TIERS)
        sub_id = ctx["subcontract"]["id"]
        co = create_and_submit_co(sub_id, 400_000,
                                  make_buyout_lead_headers("bl-1"),
                                  description="CO then void")
        validate_success(api_client.approve_change_order(
            co["id"], make_project_manager_headers("pm-1")))
        mid = get_success_data(api_client.get_subcontract(sub_id, BL))
        return sub_id, co, mid

    def test_void_restores_contract_value_and_cumulative(self):
        """PRD section 3.8: "Voiding is the compensating action, reserved
        for the `OperationsManager`: an `APPROVED` order moves to `VOIDED`
        (`APPROVED → VOIDED`) with an optional `reason`, and the
        subcontract's `cumulative_co_cents` and `contract_value_cents` each
        decrease by the order's `amount_cents`, unwinding the approval's
        arithmetic."

        Design: Difficulty/compensating_invariant/co_approve_then_void_preserves_cumulative_and_contract_value
        """
        sub_id, co, mid = self._void_setup()
        assert mid["contract_value_cents"] == 10_400_000
        assert mid["cumulative_co_cents"] == 400_000, \
            "forward action applied"

        resp = api_client.void_change_order(co["id"], {}, OM)
        data = validate_success(resp)
        assert data["status"] == "VOIDED"
        post = get_success_data(api_client.get_subcontract(sub_id, BL))
        assert post["contract_value_cents"] == 10_000_000
        assert post["cumulative_co_cents"] == 0, \
            "conserved money quantities restored — no drift"

    def test_post_void_authority_observes_compensated_cumulative(self):
        """PRD section 3.8: "the subcontract's `cumulative_co_cents` and
        `contract_value_cents` each decrease by the order's `amount_cents`,
        unwinding the approval's arithmetic."
        PRD section 3.8: "with a ratio exactly equal to the limit passing".

        Design: Difficulty/compensating_invariant/co_approve_then_void_preserves_cumulative_and_contract_value
        """
        sub_id, co, _mid = self._void_setup()
        validate_success(api_client.void_change_order(co["id"], {}, OM))
        co2 = create_and_submit_co(sub_id, 500_000,
                                   make_buyout_lead_headers("bl-1"),
                                   description="post-void authority probe")
        approved = validate_success(api_client.approve_change_order(
            co2["id"], make_project_manager_headers("pm-1")))
        assert approved["status"] == "APPROVED", (
            "post-void cumulative_ratio == (0 + 500000) / 10000000 == 0.05 "
            "<= 0.10 — the voided 400000 does NOT count in the authority "
            "ledger"
        )
