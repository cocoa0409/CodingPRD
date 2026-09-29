"""Two-variant computations that diverge on the same subject at the same instant.

The month billed twice diverges in four invoice components, and one crew base
reports two different shortfalls from the same three headcounts.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_BASE_UNDERSTAFFED
from test_helpers.assertions import (
    assert_block_hours,
    assert_money,
    assert_staffing_picture,
    assert_status,
)
from test_helpers.factories import (
    make_agreement_payload,
    make_completion_payload,
    make_invoice_payload,
)
from test_helpers.fixtures import (
    add_leg,
    advance_clock,
    advance_pilot_to,
    attrite_pilot,
    build_active_agreement,
    build_open_cycle,
    cancel_leg,
    close_cycle,
    complete_leg,
    cycle_version,
    file_pass_through_actual,
    hire_pilot,
    induct_aircraft,
    open_pass_through,
    raise_invoice,
    read_aircraft,
    read_crew_base,
    read_cycle,
    read_invoice,
    reconcile_pass_through,
    register_aircraft,
)
from test_helpers.test_users import ADMIN_HEADERS, OPS_HEADERS

FIXED_COMPONENT_USD = 312000.00


def _build_september_month(api):
    """A September month with three completed legs, one cancellation and three
    reconciled cost categories, already billed once on the planned basis."""
    advance_clock(api, "2026-09-01T00:00:00Z")
    scenario = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="ORD",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=4,
        line_qualified_pilots=1,
        tail_numbers=["N101RG"],
        cycle_month="2026-09",
        published_departures=100,
    )
    leg_one = add_leg(
        api,
        scenario,
        flight_number="SM4101",
        origin="ORD",
        destination="DSM",
        scheduled_departure_utc="2026-09-02T08:00:00Z",
        scheduled_arrival_utc="2026-09-02T09:12:00Z",
        planned_block_hours=1.200,
    )
    leg_two = add_leg(
        api,
        scenario,
        flight_number="SM4102",
        origin="ORD",
        destination="MSP",
        scheduled_departure_utc="2026-09-04T08:00:00Z",
        scheduled_arrival_utc="2026-09-04T10:00:00Z",
        planned_block_hours=2.000,
    )
    leg_three = add_leg(
        api,
        scenario,
        flight_number="SM4103",
        origin="ORD",
        destination="SBN",
        scheduled_departure_utc="2026-09-06T08:00:00Z",
        scheduled_arrival_utc="2026-09-06T08:42:00Z",
        planned_block_hours=0.700,
    )
    leg_four = add_leg(
        api,
        scenario,
        flight_number="SM4104",
        origin="ORD",
        destination="GRR",
        scheduled_departure_utc="2026-09-08T08:00:00Z",
        scheduled_arrival_utc="2026-09-08T09:30:00Z",
        planned_block_hours=1.500,
    )
    complete_leg(
        api,
        leg_one["id"],
        make_completion_payload(
            actual_block_hours=1.155,
            actual_arrival_utc="2026-09-02T09:26:00Z",
            enplaned_bags=120,
            mishandled_bags=0,
        ),
    )
    complete_leg(
        api,
        leg_two["id"],
        make_completion_payload(
            actual_block_hours=2.007,
            actual_arrival_utc="2026-09-04T10:14:00Z",
            enplaned_bags=100,
            mishandled_bags=0,
        ),
    )
    complete_leg(
        api,
        leg_three["id"],
        make_completion_payload(
            actual_block_hours=0.616,
            actual_arrival_utc="2026-09-06T08:40:00Z",
            enplaned_bags=80,
            mishandled_bags=0,
        ),
    )
    cancel_leg(api, leg_four["id"], cause_code="CREW_UNAVAILABLE")

    for category, estimate, actual, doc_ref in (
        ("FUEL", 85000.00, 88500.00, "FUEL-SEP-INV-01"),
        ("AIRPORT_FEES", 8000.00, 9200.00, "FEES-SEP-INV-01"),
        ("INSURANCE", 2000.00, 1700.00, "INS-SEP-INV-01"),
    ):
        claim = open_pass_through(
            api, scenario.cycle_id, category=category, estimated_amount_usd=estimate
        )
        file_pass_through_actual(api, claim["id"], actual, supporting_doc_ref=doc_ref)
        reconcile_pass_through(api, claim["id"])

    provisional = raise_invoice(api, scenario.cycle_id, "PROVISIONAL")
    close_cycle(api, scenario.cycle_id)
    return scenario, provisional


def _raise_final_invoice(api, cycle_id):
    """Bill the closed month on the actual basis and return the created invoice."""
    response = api.create_invoice(
        cycle_id,
        make_invoice_payload("FINAL", cycle_version(api, cycle_id)),
        headers=ADMIN_HEADERS,
    )
    return validate_success(response, 201)


class TestInvoiceVariantDivergence:
    """The same settlement month billed on the provisional and on the final basis."""

    def test_final_invoice_diverges_from_the_provisional_in_four_components(self, api):
        """Every component the variant governs differs between the two bills.

        PRD 3.8: "On a `FINAL` invoice the included legs are the month's `COMPLETED`
        legs and the hours used are each leg's `actual_block_hours` — the same actual
        basis that `leg_variable_payment_usd` already stores on each leg. On a
        `PROVISIONAL` invoice the included legs are the month's legs whose status is
        `SCHEDULED` or `COMPLETED` and the hours used are each leg's
        `planned_block_hours`, so still-open flying is paid for in advance on its
        published plan."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_component_divergence
        """
        scenario, provisional = _build_september_month(api)

        final = _raise_final_invoice(api, scenario.cycle_id)

        assert_money(
            provisional["variable_component_usd"], 6617.93, "provisional variable component"
        )
        assert_money(final["variable_component_usd"], 6440.94, "final variable component")
        assert_money(
            provisional["passthrough_component_usd"],
            95000.00,
            "provisional pass-through component",
        )
        assert_money(
            final["passthrough_component_usd"], 101970.00, "final pass-through component"
        )
        assert_money(
            provisional["incentive_component_usd"], 0.00, "provisional incentive component"
        )
        assert_money(final["incentive_component_usd"], 15922.05, "final incentive component")
        assert_money(provisional["total_usd"], 413617.93, "provisional total")
        assert_money(final["total_usd"], 436332.99, "final total")

    def test_the_fixed_component_agrees_and_the_standing_provisional_draft_survives(self, api):
        """The variant-independent figures match and the earlier draft is left alone.

        PRD 3.8: "Raising a newer invoice for the same month and the same `variant`
        supersedes the older one: the standing `DRAFT` moves to `VOIDED` with
        `void_reason` set to `AUTO_SUPERSEDED`."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_component_divergence
        """
        scenario, provisional = _build_september_month(api)

        final = _raise_final_invoice(api, scenario.cycle_id)

        assert_money(
            provisional["fixed_component_usd"], FIXED_COMPONENT_USD, "provisional fixed component"
        )
        assert_money(final["fixed_component_usd"], FIXED_COMPONENT_USD, "final fixed component")
        assert provisional["ownership_aircraft_count"] == 1, (
            "the one regional-owned tail in service should be counted on the provisional bill"
        )
        assert final["ownership_aircraft_count"] == 1, (
            "the one regional-owned tail in service should be counted on the final bill"
        )

        assert_status(read_invoice(api, provisional["id"]), "DRAFT")
        assert_block_hours(
            read_cycle(api, scenario.cycle_id)["credited_block_hours"],
            3.778,
            "credited block hours",
        )


def _build_two_basis_base(api):
    """One tail in service, one line-qualified pilot left and two pilots in training."""
    scenario = build_active_agreement(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="DTW",
        pilots_required_per_aircraft=2,
        aircraft_allocation_cap=2,
    )
    base_id = scenario.crew_base_id
    first = hire_pilot(api, base_id, "EMP-2001", seat="CAPTAIN", hire_class_date="2026-05-01")
    second = hire_pilot(
        api, base_id, "EMP-2002", seat="FIRST_OFFICER", hire_class_date="2026-05-01"
    )
    for pilot in (first, second):
        advance_pilot_to(api, pilot["id"], base_id, "IN_TRAINING")
        advance_pilot_to(api, pilot["id"], base_id, "LINE_QUALIFIED")

    first_tail = register_aircraft(api, scenario.agreement_id, base_id, tail_number="N201RG")
    induct_aircraft(api, first_tail["id"])

    third = hire_pilot(
        api, base_id, "EMP-2003", seat="FIRST_OFFICER", hire_class_date="2026-07-01"
    )
    fourth = hire_pilot(
        api, base_id, "EMP-2004", seat="FIRST_OFFICER", hire_class_date="2026-07-01"
    )
    advance_pilot_to(api, third["id"], base_id, "IN_TRAINING")
    advance_pilot_to(api, fourth["id"], base_id, "IN_TRAINING")

    attrite_pilot(api, second["id"], base_id, destination="MAINLINE")

    second_tail = register_aircraft(api, scenario.agreement_id, base_id, tail_number="N202RG")
    return scenario, first_tail, second_tail


class TestStaffingBasisDivergence:
    """One base, three headcounts and two deliberately different shortfall bases."""

    def test_headcount_basis_blocks_the_induction_the_pipeline_basis_would_allow(self, api):
        """Induction is gated on line pilots alone, so the two trainees do not help.

        PRD 3.3: "The staffing test asks whether the base would still be crewed after
        the induction: the number of tails it would then hold, one more than the
        current `assigned_aircraft_count`, multiplied by `pilots_required_per_aircraft`,
        must be no greater than `line_qualified_pilot_count`."

        Design: Difficulty/dual_variant_calc/crew_staffing_headcount_vs_pipeline_divergence
        """
        scenario, _first_tail, second_tail = _build_two_basis_base(api)

        response = api.induct_aircraft(second_tail["id"], headers=OPS_HEADERS)
        validate_error(response, ERR_BASE_UNDERSTAFFED, 409)

        base = read_crew_base(api, scenario.crew_base_id)
        assert_staffing_picture(
            base,
            line_qualified=1,
            in_training=2,
            required_pilots=2,
            headcount_shortfall=1,
            posture="SHORT",
            assigned_aircraft=1,
        )
        assert_status(read_aircraft(api, second_tail["id"]), "PENDING_INDUCTION")

    def test_pipeline_basis_keeps_the_allocation_so_the_serving_tail_is_not_grounded(self, api):
        """The pipeline credit holds the allocatable figure up and spares the tail.

        PRD 3.2: "The **pipeline basis** additionally credits the training pipeline net
        of expected attrition: each pilot in training counts as sixty-five hundredths of
        a line pilot — thirty-five hundredths of the pipeline is discounted for the
        attrition the base expects before qualification — and the credited contribution
        is floored to a whole pilot before being added to `line_qualified_pilot_count`."

        Design: Difficulty/dual_variant_calc/crew_staffing_headcount_vs_pipeline_divergence
        """
        scenario, first_tail, second_tail = _build_two_basis_base(api)

        validate_error(
            api.induct_aircraft(second_tail["id"], headers=OPS_HEADERS),
            ERR_BASE_UNDERSTAFFED,
            409,
        )

        base = read_crew_base(api, scenario.crew_base_id)
        assert_staffing_picture(base, pipeline_shortfall=0, allocatable_aircraft=1)
        assert_status(read_aircraft(api, first_tail["id"]), "IN_SERVICE")
