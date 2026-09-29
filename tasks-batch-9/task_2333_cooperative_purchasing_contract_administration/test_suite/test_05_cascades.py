"""Single calls whose effects have to travel several hops across entities."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN_ADJUDICATOR,
    ADMIN_ADJUDICATOR_ID,
    ADMIN_INVESTIGATOR,
    ADMIN_REVIEW,
    ApiErrorId,
    assert_cents,
    assert_instant,
    assert_score,
    make_member_headers,
)
from test_helpers.constants import (
    CLOCK_DEC_02,
    CLOCK_NOV_01,
    CLOCK_OCT_01,
    OCT_PERIOD_END,
    OCT_PERIOD_START,
    SEP_PERIOD_END,
    SEP_PERIOD_START,
    SKU_DISPENSER,
    SKU_LINER,
)
from test_helpers.factories import LINER_LINE, contract_usage_payload
from test_helpers.fixtures import (
    accept_report,
    file_complaint,
    open_investigation,
    open_report,
    read_analysis,
    read_contract,
    read_report,
    read_supplier,
    read_usage,
    record_confirmed_usage,
    retract_usage,
    run_compliance_sweep,
    set_clock,
    setup_active_contract,
    setup_authorised_member,
    setup_confirmed_usage_world,
    setup_substantiated_complaint,
    submit_report,
    substantiate_complaint,
)


def _complaint_world(api):
    """One critical complaint already substantiated and a second under investigation."""
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
    second = file_complaint(
        api,
        world["contract"]["id"],
        member["id"],
        severity="CRITICAL",
        category="DELIVERY",
        narrative="Second consecutive quarter of undelivered committed volume",
    )
    world["second"] = open_investigation(api, second["id"], ADMIN_INVESTIGATOR)
    return world


def _substantiate_second(api, world):
    return substantiate_complaint(api, world["second"]["id"], ADMIN_ADJUDICATOR)


def _delinquency_world(api):
    """Two accepted reports, each with an unpaid fee whose due date has passed."""
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
    return world


def _retraction_world(api):
    """Three confirmed orders already claimed by a submitted, unaccepted report."""
    world = setup_confirmed_usage_world(api, order_count=3)
    world["report"] = open_report(
        api, world, period_start=SEP_PERIOD_START, period_end=SEP_PERIOD_END
    )
    set_clock(api, CLOCK_OCT_01)
    world["report"] = submit_report(api, world, world["report"]["id"])
    return world


class TestSubstantiationCascade:
    def test_01_the_first_substantiation_of_the_same_severity_travels_only_two_hops(self, api):
        """PRD §3.9: "`performance_tier` bands the score with two inclusive thresholds:
        85.00 or more is `PREFERRED`, 70.00 or more but below 85.00 is `STANDARD`, and
        below 70.00 is `PROBATION` — so exactly 85.00 is `PREFERRED` and exactly 70.00 is
        `STANDARD`."

        Design: Difficulty/transitive_cascade/substantiated_complaint_cascades_five_hops_to_voided_piggyback_authority
        """
        world = _complaint_world(api)

        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_score(supplier["deduction_points_total"], 20.00, "deduction_points_total")
        assert_score(supplier["performance_score"], 80.00, "performance_score")
        assert supplier["performance_tier"] == "STANDARD"
        assert supplier["qualification_status"] == "QUALIFIED"
        assert read_contract(api, world["contract"]["id"])["status"] == "ACTIVE"
        assert read_analysis(api, world["analysis"]["id"])["status"] == "DETERMINED"

    def test_02_substantiation_prices_the_severity_and_opens_the_appeal_window(self, api):
        """PRD §3.9: "`SUBSTANTIATE` moves `UNDER_INVESTIGATION → SUBSTANTIATED` and
        additionally requires the contract's supplier not to be `DEBARRED`
        (`ERR_SUPPLIER_DEBARRED`); it stamps `substantiated_at` with the current logical
        instant, sets `appeal_deadline_at` to fourteen days after `substantiated_at`, and
        writes `deduction_points` from the asserted `severity` — 2.50 points for `MINOR`,
        7.50 for `MAJOR`, and 20.00 for `CRITICAL`."

        Design: Difficulty/transitive_cascade/substantiated_complaint_cascades_five_hops_to_voided_piggyback_authority
        """
        world = _complaint_world(api)

        decided = _substantiate_second(api, world)

        assert decided["status"] == "SUBSTANTIATED"
        assert_score(decided["deduction_points"], 20.00, "deduction_points")
        assert decided["adjudicator_user_id"] == ADMIN_ADJUDICATOR_ID
        assert_instant(decided["substantiated_at"], "2026-09-01T00:00:00Z", "substantiated_at")
        assert_instant(decided["appeal_deadline_at"], "2026-09-15T00:00:00Z", "appeal_deadline_at")

    def test_03_the_second_substantiation_drops_the_supplier_into_probation(self, api):
        """PRD §3.9: "First, `deduction_points` is added to the supplier's
        `deduction_points_total` and its `substantiated_complaint_count` increments."

        Design: Difficulty/transitive_cascade/substantiated_complaint_cascades_five_hops_to_voided_piggyback_authority
        """
        world = _complaint_world(api)

        _substantiate_second(api, world)

        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_score(supplier["deduction_points_total"], 40.00, "deduction_points_total")
        assert supplier["substantiated_complaint_count"] == 2
        assert_score(supplier["performance_score"], 60.00, "performance_score")
        assert supplier["performance_tier"] == "PROBATION"

    def test_04_probation_suspends_the_standing_and_then_the_contract(self, api):
        """PRD §3.9: "Third, a `performance_tier` of `PROBATION` drives the supplier's
        standing `QUALIFIED → SUSPENDED`. Fourth, that suspension sets every `ACTIVE`
        master contract of the supplier to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/substantiated_complaint_cascades_five_hops_to_voided_piggyback_authority
        """
        world = _complaint_world(api)

        _substantiate_second(api, world)

        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert supplier["qualification_status"] == "SUSPENDED"
        assert read_contract(api, world["contract"]["id"])["status"] == "SUSPENDED"

    def test_05_the_contract_suspension_voids_the_authority_it_carried(self, api):
        """PRD §3.9: "Fifth, each of those contract suspensions voids that contract's
        `DETERMINED` authority opinions with `voided_reason` `CONTRACT_SUSPENDED`."

        Design: Difficulty/transitive_cascade/substantiated_complaint_cascades_five_hops_to_voided_piggyback_authority
        """
        world = _complaint_world(api)

        _substantiate_second(api, world)

        analysis = read_analysis(api, world["analysis"]["id"])
        assert analysis["status"] == "VOIDED"
        assert analysis["voided_reason"] == "CONTRACT_SUSPENDED"

    def test_06_a_member_that_could_buy_a_moment_ago_is_now_refused(self, api):
        """PRD §2.9: "The `MasterContract` the operation depends on is `ACTIVE` —
        `ERR_CONTRACT_NOT_ACTIVE`, 409, on `POST /coop/contract-usages`, `POST
        /coop/piggyback-analyses/{id}/determination`, `POST /coop/contract-amendments` and
        `POST /coop/contract-amendments/{id}/decision`."

        Design: Difficulty/transitive_cascade/substantiated_complaint_cascades_five_hops_to_voided_piggyback_authority
        """
        world = _complaint_world(api)
        _substantiate_second(api, world)

        response = api.create_contract_usage(
            contract_usage_payload(
                world["contract"]["id"],
                world["member"]["id"],
                world["lines"][SKU_DISPENSER]["id"],
                world["analysis"]["id"],
                quantity=1,
            ),
            make_member_headers(world["member"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409)
        member = validate_success(api.get_member_agency(world["member"]["id"], ADMIN_REVIEW))
        assert_cents(member["committed_spend_cents"], 0, "committed_spend_cents")


class TestDelinquencySweepCascade:
    def test_07_one_sweep_moves_every_overdue_fee_to_delinquent(self, api):
        """PRD §3.7: "Every report on that contract whose `fee_status` is `DUE` and whose
        `fee_due_at` is strictly before the logical clock moves `DUE → DELINQUENT`, and
        the sweep then cascades four hops."

        Design: Difficulty/transitive_cascade/delinquency_sweep_cascades_from_report_fee_status_to_voided_authority
        """
        world = _delinquency_world(api)

        sweep = run_compliance_sweep(api, world["contract"]["id"], note="monthly delinquency pass")

        assert sweep["swept_report_count"] == 2
        assert sorted(sweep["newly_delinquent_report_ids"]) == sorted(
            [world["sep"]["id"], world["oct"]["id"]]
        )
        assert read_report(api, world["sep"]["id"])["fee_status"] == "DELINQUENT"
        assert read_report(api, world["oct"]["id"])["fee_status"] == "DELINQUENT"

    def test_08_the_count_trigger_takes_the_posture_delinquent_and_suspends_the_contract(
        self, api
    ):
        """PRD §3.7: "If the count reaches two or more, **or** the outstanding delinquent
        amount reaches 5,000.00 dollars (500,000 cents) or more, the posture is
        `DELINQUENT`."

        Design: Difficulty/transitive_cascade/delinquency_sweep_cascades_from_report_fee_status_to_voided_authority
        """
        world = _delinquency_world(api)

        sweep = run_compliance_sweep(api, world["contract"]["id"])

        assert sweep["delinquent_report_count"] == 2
        assert sweep["compliance_posture"] == "DELINQUENT"
        assert sweep["contract_status"] == "SUSPENDED"
        contract = read_contract(api, world["contract"]["id"])
        assert contract["delinquent_report_count"] == 2
        assert contract["compliance_posture"] == "DELINQUENT"
        assert contract["status"] == "SUSPENDED"
        assert_cents(contract["fee_outstanding_cents"], 360, "fee_outstanding_cents")

    def test_09_the_delinquency_points_are_charged_without_touching_the_standing(self, api):
        """PRD §3.7: "Independently, three performance points are charged per newly
        delinquent report against the supplier's `deduction_points_total`, which re-runs
        its `performance_score` and `performance_tier`."

        Design: Difficulty/transitive_cascade/delinquency_sweep_cascades_from_report_fee_status_to_voided_authority
        """
        world = _delinquency_world(api)

        sweep = run_compliance_sweep(api, world["contract"]["id"])

        assert_score(sweep["supplier_performance_score"], 94.00, "supplier_performance_score")
        assert sweep["supplier_performance_tier"] == "PREFERRED"
        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert supplier["delinquent_report_count"] == 2
        assert_score(supplier["deduction_points_total"], 6.00, "deduction_points_total")
        assert_score(supplier["performance_score"], 94.00, "performance_score")
        assert supplier["qualification_status"] == "QUALIFIED"

    def test_10_the_suspension_reached_through_the_sweep_voids_the_authority(self, api):
        """PRD §3.7: "Fourth, that suspension voids every `DETERMINED` opinion on the
        contract with `voided_reason` `CONTRACT_SUSPENDED`."

        Design: Difficulty/transitive_cascade/delinquency_sweep_cascades_from_report_fee_status_to_voided_authority
        """
        world = _delinquency_world(api)

        run_compliance_sweep(api, world["contract"]["id"])

        analysis = read_analysis(api, world["analysis"]["id"])
        assert analysis["status"] == "VOIDED"
        assert analysis["voided_reason"] == "CONTRACT_SUSPENDED"


class TestRetractionCascade:
    def test_11_the_submitted_report_claims_all_three_orders_before_the_retraction(self, api):
        """PRD §3.7: "Submission gathers the orders the report covers: every order on the
        report's own `contract_id` whose `status` is `CONFIRMED`, whose `ordered_at` lies
        inside the closed period with both endpoints inclusive, and whose
        `usage_report_id` is either null or already this report's own id."

        Design: Difficulty/transitive_cascade/usage_retraction_cascades_into_report_resweep_and_ledger_restatement
        """
        world = _retraction_world(api)

        report = read_report(api, world["report"]["id"])
        assert report["swept_usage_count"] == 3
        assert_cents(report["reported_chargeable_cents"], 27045, "reported_chargeable_cents")
        assert_cents(report["reported_fee_cents"], 541, "reported_fee_cents")
        member = validate_success(api.get_member_agency(world["member"]["id"], ADMIN_REVIEW))
        assert_cents(member["committed_spend_cents"], 27585, "committed_spend_cents")
        contract = read_contract(api, world["contract"]["id"])
        assert_cents(
            contract["usage_chargeable_cents_total"], 27045, "usage_chargeable_cents_total"
        )

    def test_12_retraction_debits_both_ledgers_back_and_releases_the_order(self, api):
        """PRD §3.6: "First it subtracts `total_cents` from the member's
        `committed_spend_cents` and `chargeable_base_cents` from the contract's
        `usage_chargeable_cents_total`, and stamps `retracted_at`."

        Design: Difficulty/transitive_cascade/usage_retraction_cascades_into_report_resweep_and_ledger_restatement
        """
        world = _retraction_world(api)

        retracted = retract_usage(api, world["usages"][0])

        assert retracted["status"] == "RETRACTED"
        assert_instant(retracted["retracted_at"], "2026-10-01T00:00:00Z", "retracted_at")
        assert retracted["usage_report_id"] is None
        member = validate_success(api.get_member_agency(world["member"]["id"], ADMIN_REVIEW))
        assert_cents(member["committed_spend_cents"], 18390, "committed_spend_cents")
        contract = read_contract(api, world["contract"]["id"])
        assert_cents(
            contract["usage_chargeable_cents_total"], 18030, "usage_chargeable_cents_total"
        )

    def test_13_the_report_is_re_swept_and_its_reported_fee_is_rounded_afresh(self, api):
        """PRD §3.6: "Second, if the order had been swept, that debit reversal re-runs the
        sweep of the report named by `usage_report_id`, recomputing `swept_usage_count`,
        `reported_chargeable_cents`, `reported_usage_cents` and `reported_fee_cents`, and
        clears the order's own `usage_report_id`."

        Design: Difficulty/transitive_cascade/usage_retraction_cascades_into_report_resweep_and_ledger_restatement
        """
        world = _retraction_world(api)

        retract_usage(api, world["usages"][0])

        report = read_report(api, world["report"]["id"])
        assert report["swept_usage_count"] == 2
        assert_cents(report["reported_chargeable_cents"], 18030, "reported_chargeable_cents")
        assert_cents(report["reported_usage_cents"], 18390, "reported_usage_cents")
        assert_cents(report["reported_fee_cents"], 361, "reported_fee_cents")
        assert report["status"] == "SUBMITTED"

    def test_14_the_posture_is_re_derived_and_the_surviving_orders_are_untouched(self, api):
        """PRD §3.6: "Third, the recomputed report figures re-run the contract's
        compliance posture."

        Design: Difficulty/transitive_cascade/usage_retraction_cascades_into_report_resweep_and_ledger_restatement
        """
        world = _retraction_world(api)

        retract_usage(api, world["usages"][0])

        assert read_contract(api, world["contract"]["id"])["compliance_posture"] == "COMPLIANT"
        assert read_usage(api, world["usages"][1]["id"])["status"] == "CONFIRMED"
        assert read_usage(api, world["usages"][2]["id"])["status"] == "CONFIRMED"

    def test_15_an_order_released_by_retraction_cannot_be_swept_a_second_time(self, api):
        """PRD §3.6: "Afterwards the committed-spend arithmetic must balance exactly: the
        member's `committed_spend_cents` equals the sum of `total_cents` over its
        `RECORDED` and `CONFIRMED` orders and nothing else."

        Design: Difficulty/transitive_cascade/usage_retraction_cascades_into_report_resweep_and_ledger_restatement
        """
        world = _retraction_world(api)

        retract_usage(api, world["usages"][0])

        survivors = [read_usage(api, row["id"]) for row in world["usages"][1:]]
        member = validate_success(api.get_member_agency(world["member"]["id"], ADMIN_REVIEW))
        assert_cents(
            member["committed_spend_cents"],
            sum(row["total_cents"] for row in survivors),
            "committed_spend_cents",
        )
        assert all(row["usage_report_id"] == world["report"]["id"] for row in survivors)
