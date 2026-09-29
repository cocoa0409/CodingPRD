"""Reversals that must restore their own arithmetic and nothing else."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN_ADJUDICATOR,
    ADMIN_APPEAL,
    ADMIN_INVESTIGATOR,
    ADMIN_REVIEW,
    ApiErrorId,
    assert_cents,
    assert_instant,
    assert_score,
    make_member_headers,
    make_supplier_headers,
)
from test_helpers.constants import (
    CLOCK_DEC_02,
    CLOCK_NOV_01,
    CLOCK_OCT_01,
    OCT_PERIOD_END,
    OCT_PERIOD_START,
    PRIMER_QTY_FOR_5000000,
    SEP_PERIOD_END,
    SEP_PERIOD_START,
    SKU_DISPENSER,
    SKU_LINER,
)
from test_helpers.factories import (
    ADJUSTMENT_LINE,
    DISPENSER_LINE,
    LINER_LINE,
    contract_usage_payload,
)
from test_helpers.fixtures import (
    accept_report,
    open_report,
    prime_committed_spend,
    read_analysis,
    read_complaint,
    read_contract,
    read_member,
    read_report,
    read_supplier,
    read_usage,
    record_confirmed_usage,
    record_usage,
    remit_fee,
    retract_usage,
    run_compliance_sweep,
    set_clock,
    setup_active_contract,
    setup_authorised_member,
    setup_substantiated_complaint,
    submit_report,
)

RIO_PLANO = dict(
    legal_name="Rio Plano Regional Utility District",
    state_code="TX",
    member_category="SPECIAL_DISTRICT",
    annual_spend_ceiling_cents=10000000,
    governing_body_resolution_number="RES-RP-2026-031",
)


def _order(api, world, sku, quantity=1):
    return api.create_contract_usage(
        contract_usage_payload(
            world["contract"]["id"],
            world["member"]["id"],
            world["lines"][sku]["id"],
            world["analysis"]["id"],
            quantity=quantity,
        ),
        make_member_headers(world["member"]["id"]),
    )


def _appealed_world(api):
    """Two critical substantiations, the second of them under appeal."""
    world = setup_active_contract(api)
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["analysis"] = analysis
    world["first"] = setup_substantiated_complaint(
        api,
        world["contract"]["id"],
        member["id"],
        severity="CRITICAL",
        category="PRODUCT_QUALITY",
        narrative="Dispensers arrived cracked on two campuses",
        investigator=ADMIN_INVESTIGATOR,
        adjudicator=ADMIN_ADJUDICATOR,
    )
    world["second"] = setup_substantiated_complaint(
        api,
        world["contract"]["id"],
        member["id"],
        severity="CRITICAL",
        category="DELIVERY",
        narrative="Committed volume undelivered for a second consecutive quarter",
        investigator=ADMIN_INVESTIGATOR,
        adjudicator=ADMIN_ADJUDICATOR,
    )
    world["second"] = validate_success(
        api.complaint_appeal(
            world["second"]["id"],
            {"action": "FILE_APPEAL"},
            make_supplier_headers(world["contract"]["supplier_id"]),
        )
    )
    return world


def _overturn(api, world):
    return validate_success(
        api.complaint_appeal_decision(
            world["second"]["id"],
            {"action": "OVERTURN", "note": "partial shipment receipts accepted on review"},
            ADMIN_APPEAL,
        )
    )


def _reinstate_supplier(api, world):
    return validate_success(
        api.supplier_qualification(
            world["contract"]["supplier_id"],
            {"action": "REINSTATE", "note": "tier restored after the overturn"},
            ADMIN_REVIEW,
        )
    )


def _reinstate_contract(api, world):
    return validate_success(
        api.contract_award_status(
            world["contract"]["id"],
            {"action": "REINSTATE", "note": "supplier requalified"},
            ADMIN_REVIEW,
        )
    )


def _frozen_pricing_world(api):
    """A primer order lifting the snapshot into tier 1, and one order priced there."""
    world = setup_active_contract(api, lines=(DISPENSER_LINE, ADJUSTMENT_LINE))
    member, analysis = setup_authorised_member(api, world, **RIO_PLANO)
    world["member"] = member
    world["analysis"] = analysis
    world["primer"] = prime_committed_spend(
        api, world, member, analysis, PRIMER_QTY_FOR_5000000
    )
    world["frozen"] = record_usage(
        api,
        world["contract"]["id"],
        member["id"],
        world["lines"][SKU_DISPENSER]["id"],
        analysis["id"],
        quantity=10,
    )
    return world


def _delinquent_pair_world(api):
    """Two accepted fees swept into delinquency, taking the contract down with them."""
    world = setup_active_contract(api, lines=(LINER_LINE,))
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["analysis"] = analysis
    line_id = world["lines"][SKU_LINER]["id"]
    contract_id = world["contract"]["id"]
    record_confirmed_usage(api, contract_id, member["id"], line_id, analysis["id"], quantity=1)
    world["sep"] = open_report(
        api, world, period_start=SEP_PERIOD_START, period_end=SEP_PERIOD_END
    )
    set_clock(api, CLOCK_OCT_01)
    record_confirmed_usage(api, contract_id, member["id"], line_id, analysis["id"], quantity=1)
    submit_report(api, world, world["sep"]["id"])
    accept_report(api, world["sep"]["id"])
    set_clock(api, CLOCK_NOV_01)
    world["oct"] = open_report(
        api, world, period_start=OCT_PERIOD_START, period_end=OCT_PERIOD_END
    )
    submit_report(api, world, world["oct"]["id"])
    accept_report(api, world["oct"]["id"])
    set_clock(api, CLOCK_DEC_02)
    run_compliance_sweep(api, contract_id, note="monthly delinquency pass")
    return world


class TestOverturnedAppeal:
    def test_01_the_overturn_reverses_the_points_it_charged_and_keeps_the_record(self, api):
        """PRD §3.9: "`OVERTURN` moves `APPEALED → OVERTURNED` and is the exact compensating
        action of substantiation: it subtracts `deduction_points` from the supplier's
        `deduction_points_total`, sets `points_reversed` to true, decrements the supplier's
        `substantiated_complaint_count`, and re-runs the score so that `performance_score`
        and `performance_tier` are restored exactly."

        Design: Difficulty/compensating_invariant/overturned_appeal_reverses_points_exactly_without_reviving_suspensions
        """
        world = _appealed_world(api)

        overturned = _overturn(api, world)

        assert overturned["status"] == "OVERTURNED"
        assert overturned["points_reversed"] is True
        assert_score(overturned["deduction_points"], 20.00, "deduction_points")
        first = read_complaint(api, world["first"]["id"])
        assert first["status"] == "SUBSTANTIATED"
        assert first["points_reversed"] is False

    def test_02_the_supplier_lands_back_on_the_figures_it_had_after_one_complaint(self, api):
        """PRD §3.9: "First, the severity points of every complaint on any of this supplier's
        contracts whose `status` is `SUBSTANTIATED`, `APPEALED` or `CLOSED` and whose
        `points_reversed` is false — complaints in `INTAKE` or `UNDER_INVESTIGATION`,
        complaints that were `DISMISSED`, and complaints that were `OVERTURNED` all
        contribute nothing."

        Design: Difficulty/compensating_invariant/overturned_appeal_reverses_points_exactly_without_reviving_suspensions
        """
        world = _appealed_world(api)

        _overturn(api, world)

        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_score(supplier["deduction_points_total"], 20.00, "deduction_points_total")
        assert supplier["substantiated_complaint_count"] == 1
        assert_score(supplier["performance_score"], 80.00, "performance_score")
        assert supplier["performance_tier"] == "STANDARD"

    def test_03_the_overturn_compensates_nothing_downstream_of_the_points(self, api):
        """PRD §3.9: "What `OVERTURN` deliberately does *not* do is reinstate
        `qualification_status`: a supplier suspended by the substantiation stays `SUSPENDED`
        until an administrator reinstates it explicitly."

        Design: Difficulty/compensating_invariant/overturned_appeal_reverses_points_exactly_without_reviving_suspensions
        """
        world = _appealed_world(api)

        _overturn(api, world)

        assert read_supplier(api, world["contract"]["supplier_id"])["qualification_status"] == (
            "SUSPENDED"
        )
        assert read_contract(api, world["contract"]["id"])["status"] == "SUSPENDED"
        assert read_analysis(api, world["analysis"]["id"])["status"] == "VOIDED"
        validate_error(
            _order(api, world, SKU_DISPENSER), ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409
        )

    def test_04_requalifying_the_supplier_leaves_its_contracts_where_they_are(self, api):
        """PRD §3.1: "`REINSTATE` moves `SUSPENDED → QUALIFIED` and is refused while
        `performance_tier` is `PROBATION`; it deliberately leaves the contracts `SUSPENDED` —
        each must be reinstated explicitly on its own execution dimension — and it does not
        revive the voided opinions."

        Design: Difficulty/compensating_invariant/overturned_appeal_reverses_points_exactly_without_reviving_suspensions
        """
        world = _appealed_world(api)
        _overturn(api, world)

        supplier = _reinstate_supplier(api, world)

        assert supplier["qualification_status"] == "QUALIFIED"
        assert read_contract(api, world["contract"]["id"])["status"] == "SUSPENDED"
        validate_error(
            _order(api, world, SKU_DISPENSER), ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409
        )

    def test_05_even_both_reinstatements_leave_the_voided_authority_dead(self, api):
        """PRD §3.3: "`REINSTATE` moves `SUSPENDED → ACTIVE` and requires
        `compliance_posture` other than `DELINQUENT`, a `QUALIFIED` supplier, and a logical
        clock strictly before `current_term_end`; it does not revive voided opinions."

        Design: Difficulty/compensating_invariant/overturned_appeal_reverses_points_exactly_without_reviving_suspensions
        """
        world = _appealed_world(api)
        _overturn(api, world)
        _reinstate_supplier(api, world)

        contract = _reinstate_contract(api, world)

        assert contract["status"] == "ACTIVE"
        analysis = read_analysis(api, world["analysis"]["id"])
        assert analysis["status"] == "VOIDED"
        assert analysis["voided_reason"] == "CONTRACT_SUSPENDED"
        validate_error(
            _order(api, world, SKU_DISPENSER), ApiErrorId.ERR_PIGGYBACK_NOT_AUTHORIZED, 409
        )
        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            0,
            "committed_spend_cents",
        )


class TestRetractionLeavesPricingFrozen:
    def test_06_the_second_order_was_priced_off_the_primer_snapshot(self, api):
        """PRD §3.6: "Read the member's `committed_spend_cents` as it stands **before** this
        order is added; that snapshot is the `spend_basis_cents`."

        Design: Difficulty/compensating_invariant/retraction_restores_the_ledger_exactly_without_repricing_the_frozen_usage
        """
        world = _frozen_pricing_world(api)

        assert_cents(world["frozen"]["spend_basis_cents"], 5000000, "spend_basis_cents")
        assert world["frozen"]["discount_tier_index"] == 1
        assert_cents(world["frozen"]["total_cents"], 120888, "total_cents")
        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            5120888,
            "committed_spend_cents",
        )
        assert_cents(
            read_contract(api, world["contract"]["id"])["usage_chargeable_cents_total"],
            5020711,
            "usage_chargeable_cents_total",
        )

    def test_07_retracting_the_primer_restores_both_ledgers_exactly(self, api):
        """PRD §3.6: "Afterwards the committed-spend arithmetic must balance exactly: the
        member's `committed_spend_cents` equals the sum of `total_cents` over its `RECORDED`
        and `CONFIRMED` orders and nothing else."

        Design: Difficulty/compensating_invariant/retraction_restores_the_ledger_exactly_without_repricing_the_frozen_usage
        """
        world = _frozen_pricing_world(api)

        retracted = retract_usage(api, world["primer"])

        assert retracted["status"] == "RETRACTED"
        assert_instant(retracted["retracted_at"], "2026-09-01T00:00:00Z", "retracted_at")
        assert retracted["usage_report_id"] is None
        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            120888,
            "committed_spend_cents",
        )
        assert_cents(
            read_contract(api, world["contract"]["id"])["usage_chargeable_cents_total"],
            118750,
            "usage_chargeable_cents_total",
        )

    def test_08_the_already_priced_order_is_not_repriced_by_the_retraction(self, api):
        """PRD §3.6: "Retraction cascades three hops."

        Design: Difficulty/compensating_invariant/retraction_restores_the_ledger_exactly_without_repricing_the_frozen_usage
        """
        world = _frozen_pricing_world(api)

        retract_usage(api, world["primer"])

        frozen = read_usage(api, world["frozen"]["id"])
        assert frozen["status"] == "RECORDED"
        assert frozen["discount_tier_index"] == 1
        assert_cents(frozen["net_unit_price_cents"], 11875, "net_unit_price_cents")
        assert frozen["effective_fee_rate_bps"] == 180
        assert_cents(frozen["admin_fee_cents"], 2138, "admin_fee_cents")
        assert_cents(frozen["total_cents"], 120888, "total_cents")

    def test_09_the_same_request_now_prices_off_the_restored_snapshot(self, api):
        """PRD §3.6: "The consequence is worth stating plainly: two identical orders placed
        back to back can carry different `net_unit_price_cents`, because the first order's
        step-nine debit moves the second order's step-one snapshot across a tier threshold."

        Design: Difficulty/compensating_invariant/retraction_restores_the_ledger_exactly_without_repricing_the_frozen_usage
        """
        world = _frozen_pricing_world(api)
        retract_usage(api, world["primer"])

        repeat = validate_success(_order(api, world, SKU_DISPENSER, quantity=10), 201)

        assert repeat["discount_tier_index"] == 0
        assert_cents(repeat["net_unit_price_cents"], 12500, "net_unit_price_cents")
        assert repeat["effective_fee_rate_bps"] == 200
        assert_cents(repeat["admin_fee_cents"], 2500, "admin_fee_cents")
        assert_cents(repeat["total_cents"], 127500, "total_cents")
        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            248388,
            "committed_spend_cents",
        )
        assert_cents(
            read_contract(api, world["contract"]["id"])["usage_chargeable_cents_total"],
            243750,
            "usage_chargeable_cents_total",
        )


class TestRemittanceRestoresPostureOnly:
    def test_10_the_first_settlement_takes_the_posture_back_to_watch(self, api):
        """PRD §3.7: "Recovery runs the other way as remittances land: `DELINQUENT → WATCH`
        when the count falls back to exactly one with an outstanding amount strictly below the
        threshold, `DELINQUENT → COMPLIANT` and `WATCH → COMPLIANT` when the count reaches
        zero."

        Design: Difficulty/compensating_invariant/remitting_every_delinquent_fee_restores_posture_and_points_but_not_the_suspension
        """
        world = _delinquent_pair_world(api)

        settled = remit_fee(api, world, world["sep"]["id"], 180)

        assert settled["fee_status"] == "PAID"
        assert_cents(settled["remitted_cents"], 180, "remitted_cents")
        contract = read_contract(api, world["contract"]["id"])
        assert contract["delinquent_report_count"] == 1
        assert contract["compliance_posture"] == "WATCH"
        assert_cents(contract["fee_outstanding_cents"], 180, "fee_outstanding_cents")
        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_score(supplier["deduction_points_total"], 3.00, "deduction_points_total")
        assert_score(supplier["performance_score"], 97.00, "performance_score")

    def test_11_the_second_settlement_returns_the_points_to_where_they_started(self, api):
        """PRD §3.9: "Every point charged anywhere in the system is a conserved quantity:
        `deduction_points_total` must always equal the sum of the three charges above, and no
        compensating action may leave it drifted."

        Design: Difficulty/compensating_invariant/remitting_every_delinquent_fee_restores_posture_and_points_but_not_the_suspension
        """
        world = _delinquent_pair_world(api)
        remit_fee(api, world, world["sep"]["id"], 180)

        settled = remit_fee(api, world, world["oct"]["id"], 180)

        assert settled["fee_status"] == "PAID"
        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert supplier["delinquent_report_count"] == 0
        assert_score(supplier["deduction_points_total"], 0.00, "deduction_points_total")
        assert_score(supplier["performance_score"], 100.00, "performance_score")
        assert supplier["performance_tier"] == "PREFERRED"
        assert_cents(supplier["fee_remitted_cents_total"], 360, "fee_remitted_cents_total")

    def test_12_the_ledger_closes_flat_while_the_suspension_stands(self, api):
        """PRD §3.7: "What the compensation does *not* do is reinstate a contract that the
        count trigger suspended, or revive an opinion that suspension voided."

        Design: Difficulty/compensating_invariant/remitting_every_delinquent_fee_restores_posture_and_points_but_not_the_suspension
        """
        world = _delinquent_pair_world(api)
        remit_fee(api, world, world["sep"]["id"], 180)
        remit_fee(api, world, world["oct"]["id"], 180)

        contract = read_contract(api, world["contract"]["id"])

        assert contract["delinquent_report_count"] == 0
        assert contract["compliance_posture"] == "COMPLIANT"
        assert_cents(contract["fee_assessed_cents_total"], 360, "fee_assessed_cents_total")
        assert_cents(contract["fee_remitted_cents_total"], 360, "fee_remitted_cents_total")
        assert_cents(contract["fee_outstanding_cents"], 0, "fee_outstanding_cents")
        assert contract["status"] == "SUSPENDED"
        validate_error(_order(api, world, SKU_LINER), ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409)

    def test_13_the_reinstatement_the_settlement_earned_still_needs_a_new_opinion(self, api):
        """PRD §2.10: "Reinstating a member or a contract does not revive a voided
        `PiggybackAnalysis`; the member must request a fresh analysis."

        Design: Difficulty/compensating_invariant/remitting_every_delinquent_fee_restores_posture_and_points_but_not_the_suspension
        """
        world = _delinquent_pair_world(api)
        remit_fee(api, world, world["sep"]["id"], 180)
        remit_fee(api, world, world["oct"]["id"], 180)

        contract = _reinstate_contract(api, world)

        assert contract["status"] == "ACTIVE"
        assert read_analysis(api, world["analysis"]["id"])["status"] == "VOIDED"
        assert read_report(api, world["sep"]["id"])["fee_status"] == "PAID"
        validate_error(
            _order(api, world, SKU_LINER), ApiErrorId.ERR_PIGGYBACK_NOT_AUTHORIZED, 409
        )
