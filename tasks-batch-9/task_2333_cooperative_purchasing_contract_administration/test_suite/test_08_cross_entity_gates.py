"""Whether a member may buy depends on other entities' dimensions."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN_REVIEW,
    ApiErrorId,
    assert_cents,
    assert_score,
    make_member_headers,
)
from test_helpers.constants import (
    CLOCK_NOV_01,
    CLOCK_OCT_01,
    PRIMER_QTY_FOR_25500000,
    SEP_PERIOD_END,
    SEP_PERIOD_START,
    SKU_ADJUSTMENT,
    SKU_DISPENSER,
)
from test_helpers.factories import ADJUSTMENT_LINE, DISPENSER_LINE, contract_usage_payload
from test_helpers.fixtures import (
    accept_report,
    open_report,
    read_analysis,
    read_contract,
    read_member,
    read_report,
    read_supplier,
    record_confirmed_usage,
    remit_fee,
    run_compliance_sweep,
    set_clock,
    setup_active_contract,
    setup_active_member,
    setup_authorised_member,
    setup_determined_analysis,
    submit_report,
)

BIG_BEND = dict(
    legal_name="Big Bend Regional Water District",
    state_code="TX",
    member_category="SPECIAL_DISTRICT",
    annual_spend_ceiling_cents=30000000,
    governing_body_resolution_number="RES-BB-2026-021",
)
RIVERSIDE = dict(
    legal_name="Riverside Unified School District",
    state_code="CA",
    member_category="K12_DISTRICT",
    governing_body_resolution_number="RES-2026-114",
)


def _amount_branch_world(api):
    """One delinquent report carrying exactly the amount-branch threshold outstanding."""
    world = setup_active_contract(api, lines=(DISPENSER_LINE, ADJUSTMENT_LINE))
    member, analysis = setup_authorised_member(api, world, **BIG_BEND)
    world["member"] = member
    world["analysis"] = analysis
    world["primer"] = record_confirmed_usage(
        api,
        world["contract"]["id"],
        member["id"],
        world["lines"][SKU_ADJUSTMENT]["id"],
        analysis["id"],
        quantity=PRIMER_QTY_FOR_25500000,
    )
    world["report"] = open_report(
        api, world, period_start=SEP_PERIOD_START, period_end=SEP_PERIOD_END
    )
    set_clock(api, CLOCK_OCT_01)
    submit_report(api, world, world["report"]["id"])
    accept_report(api, world["report"]["id"])
    set_clock(api, CLOCK_NOV_01)
    run_compliance_sweep(api, world["contract"]["id"], note="monthly delinquency pass")
    return world


def _suspended_member_world(api):
    """A verified member suspended after its authority opinion was determined."""
    world = setup_active_contract(api)
    member = setup_active_member(api, **RIVERSIDE)
    world["member"] = member
    world["analysis"] = setup_determined_analysis(api, member["id"], world["contract"]["id"])
    world["member"] = validate_success(
        api.member_registration(
            member["id"],
            {"action": "SUSPEND", "note": "resolution lapsed pending board renewal"},
            ADMIN_REVIEW,
        )
    )
    return world


def _order(api, world, quantity=1, analysis=None):
    return api.create_contract_usage(
        contract_usage_payload(
            world["contract"]["id"],
            world["member"]["id"],
            world["lines"][SKU_DISPENSER]["id"],
            (analysis or world["analysis"])["id"],
            quantity=quantity,
        ),
        make_member_headers(world["member"]["id"]),
    )


class TestPostureAmountBranch:
    def test_01_the_amount_branch_fires_on_one_report_and_skips_watch(self, api):
        """PRD §3.7: "Both tests are inclusive: exactly two delinquent reports is
        `DELINQUENT`, and exactly 500,000 cents outstanding on a single report is
        `DELINQUENT`."

        Design: Difficulty/cross_entity_state_dependency/usage_gated_by_amount_branch_posture_while_the_contract_stays_active
        """
        world = _amount_branch_world(api)

        report = read_report(api, world["report"]["id"])
        assert_cents(report["reported_fee_cents"], 500000, "reported_fee_cents")
        assert report["fee_status"] == "DELINQUENT"
        contract = read_contract(api, world["contract"]["id"])
        assert contract["delinquent_report_count"] == 1
        assert_cents(contract["fee_outstanding_cents"], 500000, "fee_outstanding_cents")
        assert contract["compliance_posture"] == "DELINQUENT"

    def test_02_the_amount_branch_leaves_the_contract_active_and_voids_nothing(self, api):
        """PRD §3.7: "A move to `DELINQUENT` reached on the amount test alone with a single
        delinquent report leaves the contract `ACTIVE` and voids nothing: new orders are
        blocked by the posture gate `ERR_CONTRACT_POSTURE_DELINQUENT` rather than by the
        status gate `ERR_CONTRACT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/usage_gated_by_amount_branch_posture_while_the_contract_stays_active
        """
        world = _amount_branch_world(api)

        assert read_contract(api, world["contract"]["id"])["status"] == "ACTIVE"
        assert read_analysis(api, world["analysis"]["id"])["status"] == "DETERMINED"
        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_score(supplier["performance_score"], 97.00, "performance_score")
        assert supplier["performance_tier"] == "PREFERRED"

    def test_03_the_posture_of_another_entity_refuses_the_order(self, api):
        """PRD §2.9: "The contract's `compliance_posture` is `COMPLIANT` or `WATCH` —
        `ERR_CONTRACT_POSTURE_DELINQUENT`, 409, on `POST /coop/contract-usages`."

        Design: Difficulty/cross_entity_state_dependency/usage_gated_by_amount_branch_posture_while_the_contract_stays_active
        """
        world = _amount_branch_world(api)

        response = _order(api, world, quantity=1)

        validate_error(response, ApiErrorId.ERR_CONTRACT_POSTURE_DELINQUENT, 409)

    def test_04_settling_the_delinquent_fee_undoes_the_sweep_exactly(self, api):
        """PRD §3.7: "A remittance from `DELINQUENT` is the compensating action of the
        delinquency sweep and must undo it exactly: on top of the same ledger work it
        decrements both the contract's and the supplier's `delinquent_report_count` by 1,
        re-runs the contract's compliance posture with the reduced count, and subtracts the
        three delinquency points from the supplier's `deduction_points_total`, which
        re-runs `performance_score` and `performance_tier`."

        Design: Difficulty/cross_entity_state_dependency/usage_gated_by_amount_branch_posture_while_the_contract_stays_active
        """
        world = _amount_branch_world(api)

        remitted = remit_fee(api, world, world["report"]["id"], 500000)

        assert remitted["fee_status"] == "PAID"
        assert_cents(remitted["remitted_cents"], 500000, "remitted_cents")
        contract = read_contract(api, world["contract"]["id"])
        assert contract["delinquent_report_count"] == 0
        assert contract["compliance_posture"] == "COMPLIANT"
        assert_cents(contract["fee_outstanding_cents"], 0, "fee_outstanding_cents")
        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_score(supplier["deduction_points_total"], 0.00, "deduction_points_total")
        assert_score(supplier["performance_score"], 100.00, "performance_score")

    def test_05_the_recovered_posture_lets_the_member_buy_again_at_its_earned_tier(self, api):
        """PRD §3.6: "Record that entry's `tier_index` as the order's
        `discount_tier_index` and take its `discount_pct` as the base discount."

        Design: Difficulty/cross_entity_state_dependency/usage_gated_by_amount_branch_posture_while_the_contract_stays_active
        """
        world = _amount_branch_world(api)
        remit_fee(api, world, world["report"]["id"], 500000)

        order = validate_success(_order(api, world, quantity=1), 201)

        assert order["status"] == "RECORDED"
        assert order["discount_tier_index"] == 2
        assert_cents(order["net_unit_price_cents"], 10250, "net_unit_price_cents")
        assert order["effective_fee_rate_bps"] == 150
        assert_cents(order["admin_fee_cents"], 154, "admin_fee_cents")
        assert_cents(order["total_cents"], 10404, "total_cents")
        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            25510404,
            "committed_spend_cents",
        )


class TestMemberSuspensionGate:
    def test_06_suspending_the_member_voids_the_opinion_it_had_earned(self, api):
        """PRD §3.4: "`SUSPEND` moves `ACTIVE → SUSPENDED` and voids every
        `PiggybackAnalysis` of this member whose `status` is `DETERMINED`, setting
        `voided_reason` to `MEMBER_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/member_suspension_gate_precedes_the_authority_gate_and_needs_a_fresh_analysis
        """
        world = _suspended_member_world(api)

        assert world["member"]["registration_status"] == "SUSPENDED"
        analysis = read_analysis(api, world["analysis"]["id"])
        assert analysis["status"] == "VOIDED"
        assert analysis["voided_reason"] == "MEMBER_SUSPENDED"

    def test_07_the_member_gate_answers_before_the_authority_gate(self, api):
        """PRD §2.9: "The `MemberAgency` is `ACTIVE` where the operation demands it, or is
        in a from-state permitting the requested registration action —
        `ERR_MEMBER_NOT_ACTIVE` or `ERR_MEMBER_INVALID_STATE`, 409, on `POST
        /coop/contract-usages`, `POST /coop/piggyback-analyses/{id}/determination` and
        `POST /coop/member-agencies/{id}/registration`."

        Design: Difficulty/cross_entity_state_dependency/member_suspension_gate_precedes_the_authority_gate_and_needs_a_fresh_analysis
        """
        world = _suspended_member_world(api)

        response = _order(api, world, quantity=10)

        validate_error(response, ApiErrorId.ERR_MEMBER_NOT_ACTIVE, 409)

    def test_08_reinstatement_clears_the_member_gate_but_not_the_authority_gate(self, api):
        """PRD §3.4: "`REINSTATE` moves `SUSPENDED → ACTIVE` and does not revive the voided
        opinions — a fresh analysis is required before the member may buy again."

        Design: Difficulty/cross_entity_state_dependency/member_suspension_gate_precedes_the_authority_gate_and_needs_a_fresh_analysis
        """
        world = _suspended_member_world(api)

        reinstated = validate_success(
            api.member_registration(
                world["member"]["id"],
                {"action": "REINSTATE", "note": "board resolution renewed"},
                ADMIN_REVIEW,
            )
        )

        assert reinstated["registration_status"] == "ACTIVE"
        analysis = read_analysis(api, world["analysis"]["id"])
        assert analysis["status"] == "VOIDED"
        assert analysis["voided_reason"] == "MEMBER_SUSPENDED"
        validate_error(
            _order(api, world, quantity=10), ApiErrorId.ERR_PIGGYBACK_NOT_AUTHORIZED, 409
        )

    def test_09_a_freshly_minted_opinion_restores_the_right_to_buy(self, api):
        """PRD §3.6: "The cited opinion must be `DETERMINED` with a `determination` of
        `AUTHORIZED` or `CONDITIONAL` — a `DENIED`, `PENDING` or `VOIDED` opinion is
        `ERR_PIGGYBACK_NOT_AUTHORIZED`"

        Design: Difficulty/cross_entity_state_dependency/member_suspension_gate_precedes_the_authority_gate_and_needs_a_fresh_analysis
        """
        world = _suspended_member_world(api)
        validate_success(
            api.member_registration(
                world["member"]["id"], {"action": "REINSTATE"}, ADMIN_REVIEW
            )
        )

        fresh = setup_determined_analysis(
            api, world["member"]["id"], world["contract"]["id"]
        )

        assert fresh["status"] == "DETERMINED"
        assert fresh["doctrine_applied"] == "STATUTORY_STRICT"
        assert_score(fresh["authority_score"], 70.00, "authority_score")
        assert fresh["determination"] == "CONDITIONAL"
        order = validate_success(_order(api, world, quantity=10, analysis=fresh), 201)
        assert order["status"] == "RECORDED"
        assert order["discount_tier_index"] == 0
        assert_cents(order["total_cents"], 127500, "total_cents")
        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            127500,
            "committed_spend_cents",
        )
