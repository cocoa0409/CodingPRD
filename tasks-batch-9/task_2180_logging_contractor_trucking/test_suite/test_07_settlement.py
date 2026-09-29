"""Compiling, submitting, approving, disputing, revising and paying a statement."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_statement,
    arrive_load,
    assert_settlement_statement,
    assert_statement_money_rollup,
    build_network,
    certify_ticket,
    compile_statement,
    create_haul_contractor,
    depart_load,
    deliver_load,
    dispatch_load,
    dispute_statement,
    file_all_coverages,
    load_at_mill,
    make_accountant_headers,
    pay_statement,
    read_haul_contractor,
    read_load,
    read_settlement_statement,
    record_finding,
    reject_ticket,
    revise_statement,
    set_clock,
    submit_statement,
    validate_error,
    validate_success,
    write_ticket,
)


def _two_certified_loads(scn):
    """Load 1 waits 50 minutes on the scale, load 2 is certified with no wait."""
    first = dispatch_load(
        scn,
        estimated_net_tons=26.5,
        scheduled_depart_at="2026-08-03T08:00:00Z",
        scheduled_arrive_at="2026-08-03T10:00:00Z",
    )
    depart_load(scn, first["id"])
    set_clock("2026-08-03T15:10:00Z")
    arrive_load(scn, first["id"])
    set_clock("2026-08-03T16:00:00Z")
    first_ticket = write_ticket(
        scn, first["id"], gross_weight_lbs=90000, defect_deduction_pct=0.04
    )
    certify_ticket(scn, first_ticket["id"])

    second = dispatch_load(
        scn,
        estimated_net_tons=20.0,
        scheduled_depart_at="2026-08-04T08:00:00Z",
        scheduled_arrive_at="2026-08-04T10:00:00Z",
    )
    depart_load(scn, second["id"])
    arrive_load(scn, second["id"])
    second_ticket = write_ticket(
        scn, second["id"], gross_weight_lbs=71060, defect_deduction_pct=0.0
    )
    certify_ticket(scn, second_ticket["id"])
    return first, first_ticket, second, second_ticket


class TestFuelSurchargeRoundingOrder:
    def test_each_load_carries_its_own_already_rounded_fuel_surcharge(self, api):
        """PRD §3.6: "A fuel surcharge of 7.5 percent of that line-haul figure is
        computed and rounded half-up to whole cents on this single load, before any
        aggregate ever sums it."
        PRD §2.5: "First, a rounding step that this document places on a single load's
        figure happens on that load, before any aggregate sums it — summing unrounded
        quantities and rounding the aggregate is a different and incorrect answer."

        Design: Difficulty/combinatorial_formula/fuel_surcharge_rounded_per_load_before_the_statement_sums_it
        """
        scn = build_network()
        first, first_ticket, second, second_ticket = _two_certified_loads(scn)

        assert read_load(first["id"])["line_haul_cents"] == 32_398
        assert read_load(first["id"])["fuel_surcharge_cents"] == 2_430
        assert read_load(first["id"])["demurrage_cents"] == 750
        assert read_load(second["id"])["line_haul_cents"] == 22_914
        assert read_load(second["id"])["fuel_surcharge_cents"] == 1_719
        assert read_load(second["id"])["demurrage_cents"] == 0

    def test_the_statement_sums_the_per_load_figures_rather_than_the_aggregate(
        self, api
    ):
        """PRD §3.9: "`gross_pay_cents` is the sum of the amounts over every `HAUL`,
        `FUEL_SURCHARGE` and `DEMURRAGE` line."
        PRD §3.9: "The fuel surcharge is never recomputed at this level: each load's
        already-rounded whole-cent figure is summed as-is, and summing unrounded
        ton-miles to take 7.5 percent of the aggregate is forbidden because it produces
        a different total."
        PRD §3.9: "A `holdback_pct` is selected from that frozen score: nothing at all
        when the score is 90 or above, 2 percent when it is at least 80 but below 90, 5
        percent when it is at least 70 but below 80, and 10 percent below 70."

        Design: Difficulty/combinatorial_formula/fuel_surcharge_rounded_per_load_before_the_statement_sums_it
        """
        scn = build_network()
        first, first_ticket, second, second_ticket = _two_certified_loads(scn)

        statement = compile_statement(scn)

        assert_settlement_statement(statement)
        assert statement["compliance_score_at_compile"] == 100
        assert statement["holdback_pct"] == pytest.approx(0.00)
        assert statement["holdback_cents"] == 0
        assert len(statement["lines"]) == 6
        assert statement["gross_pay_cents"] == 60_211
        assert statement["gross_pay_cents"] != 60_210
        assert statement["net_pay_cents"] == 60_211


class TestInsuranceHoldbackBase:
    def test_a_rejected_load_with_no_alternate_accrues_for_a_reject_deduction(
        self, api
    ):
        """PRD §3.8: "Hop two: because the ticket was rejected, the load advances
        `AT_MILL → REJECTED` and its `rejected_on` is set to the logical clock's
        calendar date."
        PRD §3.8: "When no candidate survives the filter, the original load's
        `rehaul_status` becomes `NO_ALTERNATE`, its `settlement_event_on` is set to its
        `rejected_on`, and its `settlement_status` moves `UNSETTLED → ACCRUED` so that
        a reject deduction can accrue against the carrier at settlement time."
        PRD §3.2: "A `MAJOR` finding recorded against a carrier that is `COMPLIANT`
        moves it to `WARNED` — dispatch remains permitted while the score holds at 70
        or above."

        Design: Difficulty/combinatorial_formula/insurance_holdback_base_is_settleable_base_not_gross_pay
        """
        scn = build_network()
        delivered = dispatch_load(
            scn,
            estimated_net_tons=26.5,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T10:00:00Z",
        )
        depart_load(scn, delivered["id"])
        set_clock("2026-08-03T15:10:00Z")
        arrive_load(scn, delivered["id"])
        set_clock("2026-08-03T16:00:00Z")
        delivered_ticket = write_ticket(
            scn, delivered["id"], gross_weight_lbs=90000, defect_deduction_pct=0.04
        )
        certify_ticket(scn, delivered_ticket["id"])

        record_finding(
            scn,
            severity="MAJOR",
            points=15,
            occurred_on="2026-08-02",
            note="chain binder defect",
        )

        rejected = load_at_mill(
            scn,
            estimated_net_tons=20.0,
            scheduled_depart_at="2026-08-05T08:00:00Z",
            scheduled_arrive_at="2026-08-05T10:00:00Z",
        )
        rejected_ticket = write_ticket(
            scn, rejected["id"], gross_weight_lbs=88000, defect_deduction_pct=0.02
        )
        reject_ticket(scn, rejected_ticket["id"], reject_reason="EXCESS_DEFECT")

        rejected_row = read_load(rejected["id"])
        assert rejected_row["dispatch_status"] == "REJECTED"
        assert rejected_row["rehaul_status"] == "NO_ALTERNATE"
        assert rejected_row["settlement_status"] == "ACCRUED"
        assert rejected_row["provisional_haul_pay_cents"] == 24_596
        assert read_haul_contractor(scn["hc_id"])["compliance_status"] == "WARNED"

    def test_the_holdback_applies_to_the_settleable_base_not_to_gross_pay(self, api):
        """PRD §3.9: "The base the percentage applies to is pinned to the **settleable
        base** — gross pay less the reject deduction — computed before the holdback
        exists, so there is no fixed point to solve. `holdback_cents` is that
        settleable base multiplied by the holdback fraction, rounded half-up to whole
        cents, and it is emitted as a single `INSURANCE_HOLDBACK` line carrying the
        negative of that amount, always as the last line of the array. Finally
        `deduction_cents` is the reject deduction plus the holdback, and
        `net_pay_cents` is gross pay less that total deduction."
        PRD §3.9: "For a load that reached `REJECTED` with `rehaul_status` of
        `NO_ALTERNATE`, the system instead emits a single `REJECT_DEDUCTION` line whose
        amount is the negative of 35 percent of that load's
        `provisional_haul_pay_cents`, the percentage rounded half-up to whole cents
        before the sign is applied."

        Design: Difficulty/combinatorial_formula/insurance_holdback_base_is_settleable_base_not_gross_pay
        """
        scn = build_network()
        delivered = dispatch_load(
            scn,
            estimated_net_tons=26.5,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T10:00:00Z",
        )
        depart_load(scn, delivered["id"])
        set_clock("2026-08-03T15:10:00Z")
        arrive_load(scn, delivered["id"])
        set_clock("2026-08-03T16:00:00Z")
        delivered_ticket = write_ticket(
            scn, delivered["id"], gross_weight_lbs=90000, defect_deduction_pct=0.04
        )
        certify_ticket(scn, delivered_ticket["id"])

        record_finding(
            scn,
            severity="MAJOR",
            points=15,
            occurred_on="2026-08-02",
            note="chain binder defect",
        )

        rejected = load_at_mill(
            scn,
            estimated_net_tons=20.0,
            scheduled_depart_at="2026-08-05T08:00:00Z",
            scheduled_arrive_at="2026-08-05T10:00:00Z",
        )
        rejected_ticket = write_ticket(
            scn, rejected["id"], gross_weight_lbs=88000, defect_deduction_pct=0.02
        )
        reject_ticket(scn, rejected_ticket["id"], reject_reason="EXCESS_DEFECT")

        statement = compile_statement(scn)

        assert_statement_money_rollup(statement)
        assert statement["compliance_score_at_compile"] == 82
        assert statement["holdback_pct"] == pytest.approx(0.02)
        assert statement["gross_pay_cents"] == 35_578
        assert statement["reject_deduction_cents"] == 8_609
        assert statement["holdback_cents"] == 539
        assert statement["holdback_cents"] != 712, (
            "keying the holdback on gross pay instead of the settleable base is wrong"
        )
        assert statement["deduction_cents"] == 9_148
        assert statement["net_pay_cents"] == 26_430
        assert len(statement["lines"]) == 5


class TestTheTwoStatusAxes:
    def test_the_money_axis_walks_to_paid_while_the_wood_stays_delivered(self, api):
        """PRD §3.7: "The `dispatch_status` axis tracks the physical wood:
        `DISPATCHED`, `IN_TRANSIT`, `AT_MILL`, and then one of the terminal values
        `DELIVERED`, `REJECTED` or `CANCELLED`. The `settlement_status` axis tracks the
        money: `UNSETTLED`, `ACCRUED`, `STATEMENTED` and the terminal `PAID`. They
        advance on different triggers and never gate one another."
        PRD §3.9: "**Paying** moves an `APPROVED` statement to the terminal `PAID`,
        storing the supplied `payment_reference`. Every attached load moves
        `STATEMENTED → PAID` on its settlement axis, and the carrier's
        `lifetime_settled_cents` increases by this statement's `net_pay_cents`."

        Design: Difficulty/non_linear_state_machine/load_dispatch_axis_and_settlement_axis_advance_independently
        """
        scn = build_network()
        load, ticket = deliver_load(scn)
        statement = compile_statement(scn)

        submit_statement(statement["id"], user_id="acct-1")
        approve_statement(statement["id"], user_id="acct-2")
        pay_statement(
            statement["id"], payment_reference="ACH-2026-08-0001", user_id="acct-1"
        )

        load_row = read_load(load["id"])
        assert load_row["dispatch_status"] == "DELIVERED"
        assert load_row["settlement_status"] == "PAID"
        assert load_row["final_haul_pay_cents"] == 34_828

    def test_payment_records_the_reference_and_lifts_lifetime_settled_cents(self, api):
        """PRD §3.9: "**Approving** moves a `SUBMITTED` statement to `APPROVED` and
        records the approver's `X-User-ID` as `approved_by_user_id`, subject to the
        segregation-of-duties rule of §2.1."
        PRD §3.9: "**Paying** moves an `APPROVED` statement to the terminal `PAID`,
        storing the supplied `payment_reference`. Every attached load moves
        `STATEMENTED → PAID` on its settlement axis, and the carrier's
        `lifetime_settled_cents` increases by this statement's `net_pay_cents`."

        Design: Difficulty/non_linear_state_machine/load_dispatch_axis_and_settlement_axis_advance_independently
        """
        scn = build_network()
        load, ticket = deliver_load(scn)
        statement = compile_statement(scn)

        submit_statement(statement["id"], user_id="acct-1")
        approve_statement(statement["id"], user_id="acct-2")
        pay_statement(
            statement["id"], payment_reference="ACH-2026-08-0001", user_id="acct-1"
        )

        final = read_settlement_statement(statement["id"])
        assert final["status"] == "PAID"
        assert final["gross_pay_cents"] == 34_828
        assert final["net_pay_cents"] == 34_828
        assert final["approved_by_user_id"] == "acct-2"
        assert final["payment_reference"] == "ACH-2026-08-0001"
        assert read_haul_contractor(scn["hc_id"])["lifetime_settled_cents"] == 34_828


class TestTheNegotiationLoop:
    def test_disputing_an_approved_statement_clears_the_approver(self, api):
        """PRD §3.9: "**Disputing** may be raised against a statement that is
        `SUBMITTED` or `APPROVED`, by an accountant or by the carrier itself — and when
        the caller is the carrier, its `X-User-ID` must equal the statement's
        `haul_contractor_id`. A dispute stores the supplied `dispute_reason`, clears
        `approved_by_user_id` back to null, and leaves the attached loads at
        `STATEMENTED` until the statement is actually revised."
        PRD §3.9: "**Revising** moves a `DISPUTED` statement to `REVISED`, optionally
        recording a `note`."

        Design: Difficulty/non_linear_state_machine/settlement_statement_approved_disputed_revised_resubmitted_cycle
        """
        scn = build_network()
        load, ticket = deliver_load(scn)
        statement = compile_statement(scn)
        submit_statement(statement["id"], user_id="acct-1")
        approve_statement(statement["id"], user_id="acct-2")

        dispute_statement(
            statement["id"],
            scn["carrier_headers"],
            dispute_reason="demurrage minutes disputed",
        )
        revise_statement(statement["id"], note="recompiled after dispute")
        submit_statement(statement["id"], user_id="acct-1")

        final = read_settlement_statement(statement["id"])
        assert final["status"] == "SUBMITTED"
        assert final.get("approved_by_user_id") is None
        assert final["dispute_reason"] == "demurrage minutes disputed"

    def test_the_resubmitted_statement_carries_the_same_money_and_loads(self, api):
        """PRD §3.9: "A `REVISED` statement may then be submitted again, moving its
        loads `ACCRUED → STATEMENTED` once more — that is the negotiation loop, and it
        may run as many times as the carrier and the accountant need."
        PRD §3.9: "On submission every load referenced by a `HAUL`, `FUEL_SURCHARGE`,
        `DEMURRAGE` or `REJECT_DEDUCTION` line moves `ACCRUED → STATEMENTED` on its
        settlement axis, with its `dispatch_status` untouched."

        Design: Difficulty/non_linear_state_machine/settlement_statement_approved_disputed_revised_resubmitted_cycle
        """
        scn = build_network()
        load, ticket = deliver_load(scn)
        statement = compile_statement(scn)
        submit_statement(statement["id"], user_id="acct-1")
        approve_statement(statement["id"], user_id="acct-2")

        dispute_statement(
            statement["id"],
            scn["carrier_headers"],
            dispute_reason="demurrage minutes disputed",
        )
        revise_statement(statement["id"], note="recompiled after dispute")
        submit_statement(statement["id"], user_id="acct-1")

        assert read_settlement_statement(statement["id"])["gross_pay_cents"] == 34_828
        load_row = read_load(load["id"])
        assert load_row["settlement_status"] == "STATEMENTED"
        assert load_row["dispatch_status"] == "DELIVERED"


class TestEmptyStatement:
    def test_a_carrier_with_no_eligible_loads_still_compiles_a_draft(self, api):
        """PRD §3.9: "Eligibility for a statement is an explicit filter with no
        discretion in it. A load is eligible when its `haul_contractor_id` is the
        statement's carrier, its `settlement_status` is `ACCRUED`, its
        `dispatch_status` is `DELIVERED` or `REJECTED`, its `settlement_event_on` is
        not null, and that date falls on or after `period_start` and on or before
        `period_end`."
        PRD §3.2: "A newly registered carrier starts with `compliance_status` of
        `COMPLIANT` and a `compliance_score` of 25, because at the moment of
        registration all three required insurance coverages are missing and each
        missing coverage costs 25 points against a base of 100."

        Design: Difficulty/boundary_precision_check/settlement_submit_on_empty_line_array_boundary
        """
        carrier = create_haul_contractor()
        file_all_coverages(carrier["id"])
        scn = {"hc_id": carrier["id"]}

        statement = compile_statement(scn)

        assert statement["status"] == "DRAFT"
        assert len(statement["lines"]) == 0
        assert statement["gross_pay_cents"] == 0
        assert statement["net_pay_cents"] == 0
        assert read_haul_contractor(carrier["id"])["compliance_score"] == 100

    def test_submitting_an_empty_statement_is_refused(self, api):
        """PRD §3.9: "**Submitting** moves a statement from `DRAFT` or `REVISED` to
        `SUBMITTED`; it requires at least one line, and submitting a statement whose
        `lines` array is empty is refused with `ERR_NO_SETTLEABLE_LOADS`."

        Design: Difficulty/boundary_precision_check/settlement_submit_on_empty_line_array_boundary
        """
        carrier = create_haul_contractor()
        file_all_coverages(carrier["id"])
        statement = compile_statement({"hc_id": carrier["id"]})

        response = api.submit_settlement_statement(
            statement["id"], make_accountant_headers("acct-1")
        )
        validate_error(response, ApiErrorId.ERR_NO_SETTLEABLE_LOADS.value, 422)

        final = read_settlement_statement(statement["id"])
        assert final["status"] == "DRAFT"
        assert len(final["lines"]) == 0
        assert final["gross_pay_cents"] == 0
        assert final["net_pay_cents"] == 0


class TestStatementLinesAndPeriods:
    def test_lines_follow_load_created_at_with_the_holdback_line_last(self, api):
        """PRD §3.9: "The eligible loads are then ordered by their `created_at`
        ascending — never by `id`."
        PRD §3.9: "For a load that reached `DELIVERED`, the system emits a `HAUL` line
        whose amount is that load's `line_haul_cents` plus its `incentive_cents` less
        its `regrade_adjustment_cents`; then a `FUEL_SURCHARGE` line whose amount is
        that load's already-rounded `fuel_surcharge_cents`; then, **only when that
        load's `demurrage_cents` is greater than zero**, a `DEMURRAGE` line for that
        amount."
        PRD §3.9: "`holdback_cents` is that settleable base multiplied by the holdback
        fraction, rounded half-up to whole cents, and it is emitted as a single
        `INSURANCE_HOLDBACK` line carrying the negative of that amount, always as the
        last line of the array."

        Design: Corner/calculations/statement_lines_are_ordered_by_load_created_at_ascending
        """
        scn = build_network()
        first, first_ticket = deliver_load(
            scn,
            estimated_net_tons=26.5,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T10:00:00Z",
        )
        second, second_ticket = deliver_load(
            scn,
            ticket={"gross_weight_lbs": 71060, "defect_deduction_pct": 0.0},
            estimated_net_tons=20.0,
            scheduled_depart_at="2026-08-04T08:00:00Z",
            scheduled_arrive_at="2026-08-04T10:00:00Z",
        )

        statement = compile_statement(scn)
        lines = statement["lines"]

        assert len(lines) == 5
        assert lines[0]["line_type"] == "HAUL"
        assert lines[0]["load_id"] == first["id"]
        assert lines[0]["amount_cents"] == 32_398
        assert lines[1]["line_type"] == "FUEL_SURCHARGE"
        assert lines[1]["amount_cents"] == 2_430
        assert lines[2]["line_type"] == "HAUL"
        assert lines[2]["load_id"] == second["id"]
        assert lines[2]["amount_cents"] == 22_914
        assert lines[3]["line_type"] == "FUEL_SURCHARGE"
        assert lines[3]["amount_cents"] == 1_719
        assert lines[4]["line_type"] == "INSURANCE_HOLDBACK"
        assert lines[4]["amount_cents"] == 0
        assert statement["gross_pay_cents"] == 59_461
        assert statement["net_pay_cents"] == 59_461

    def test_paying_a_statement_that_was_never_approved_is_refused(self, api):
        """PRD §3.9: "**Paying** moves an `APPROVED` statement to the terminal `PAID`,
        storing the supplied `payment_reference`."
        PRD §3.9: "Any of submit, approve, dispute, revise or pay attempted from a
        status that does not admit it is refused with `ERR_INVALID_STATEMENT_STATE`."

        Design: Corner/state_machines/paying_a_submitted_statement_before_approval_returns_invalid_statement_state
        """
        scn = build_network()
        load, ticket = deliver_load(scn)
        statement = compile_statement(scn)
        submit_statement(statement["id"], user_id="acct-1")

        response = api.pay_settlement_statement(
            statement["id"],
            {"payment_reference": "ACH-2026-08-9999"},
            make_accountant_headers("acct-1"),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATEMENT_STATE.value, 409)

        final = read_settlement_statement(statement["id"])
        assert final["status"] == "SUBMITTED"
        assert final.get("payment_reference") is None
        assert read_load(load["id"])["settlement_status"] == "STATEMENTED"
        assert read_haul_contractor(scn["hc_id"])["lifetime_settled_cents"] == 0

    def test_a_period_intersecting_a_submitted_statement_is_refused(self, api):
        """PRD §3.9: "Before compiling, the system checks for period collisions: if any
        other statement for the same carrier whose `status` is anything other than
        `DRAFT` or `VOID` covers a period intersecting the requested closed interval,
        the compile is refused with `ERR_PERIOD_OVERLAP`."

        Design: Corner/validations/a_second_statement_overlapping_a_submitted_period_is_rejected
        """
        scn = build_network()
        load, ticket = deliver_load(scn)
        first = compile_statement(scn, period_start="2026-08-01", period_end="2026-08-31")
        submit_statement(first["id"], user_id="acct-1")

        carrier_version = read_haul_contractor(scn["hc_id"])["version"]
        response = api.create_settlement_statement(
            {
                "haul_contractor_id": scn["hc_id"],
                "period_start": "2026-08-15",
                "period_end": "2026-09-15",
                "expected_haul_contractor_version": carrier_version,
            },
            make_accountant_headers("acct-1"),
        )
        validate_error(response, ApiErrorId.ERR_PERIOD_OVERLAP.value, 409)

        final = read_settlement_statement(first["id"])
        assert final["status"] == "SUBMITTED"
        assert final["gross_pay_cents"] == 34_828
        assert read_load(load["id"])["settlement_status"] == "STATEMENTED"
