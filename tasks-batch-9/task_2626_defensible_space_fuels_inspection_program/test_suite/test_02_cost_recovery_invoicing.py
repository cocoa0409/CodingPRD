"""Abatement cost recovery: the two recovery variants and the per-line overhead."""

from test_helpers import (
    PROGRAM_TYPE_CHIPPER,
    RECOVERY_BASIS_DISTRICT,
    RECOVERY_BASIS_VOLUNTARY,
    add_zones,
    advance_cycle,
    assert_allocation,
    assert_cents,
    assert_cost_recovery,
    assert_end_of_day,
    authorize_abatement,
    award_order,
    complete_inspection,
    complete_work,
    create_contractor,
    create_inspector,
    create_parcel,
    create_program,
    enroll,
    get_order,
    invoiced_world,
    notice_for_parcel,
    open_cycle,
    record_payment,
    schedule_inspection,
    serve_notice,
    set_clock,
    verify_completion,
)


def _voluntary_precompliance_world(client):
    """An invoiced order whose parcel joined a chipper day before its citation.

    The enrollment is created while the clock still reads 2026-08-01 and the
    citation is only issued on 2026-08-22, so the enrollment's created_at is
    strictly earlier than the notice's issued_at_utc.
    """
    cycle = open_cycle(client)
    program = create_program(
        client,
        cycle["id"],
        PROGRAM_TYPE_CHIPPER,
        budget_total_cents=0,
        capacity_slots=4,
        service_window_end_utc="2026-12-01T00:00:00Z",
    )
    parcel = create_parcel(client)
    enrollment = enroll(client, program["id"], parcel["id"], program["version"])

    inspector = create_inspector(client)
    verifier = create_inspector(client)
    contractor = create_contractor(client)

    inspection = schedule_inspection(
        client, parcel["id"], cycle["id"], inspector["id"]
    )
    serve_notice(client, inspection["id"])
    add_zones(client, inspection["id"], inspector["id"])

    set_clock(client, "2026-08-22T00:00:00Z")
    complete_inspection(
        client, inspection["id"], inspector["id"], "FAIL", "CERTIFIED_MAIL"
    )
    notice = notice_for_parcel(client, parcel["id"])

    set_clock(client, "2026-10-01T00:00:00Z")
    advance_cycle(client, cycle["id"])

    order = authorize_abatement(client, notice["id"], 200000)
    order = award_order(client, order["id"], contractor["id"])
    set_clock(client, order["work_start_utc"])
    order = complete_work(client, order["id"], contractor["id"])
    order = verify_completion(client, order["id"], verifier["id"])
    return {"enrollment": enrollment, "order": order, "parcel": parcel}


class TestRecoveryVariants:
    """District-contracted and voluntary-precompliance invoices diverge."""

    def test_district_contracted_variant_charges_full_overhead_and_looked_up_tier(
        self, client
    ):
        """With no earlier enrollment the invoice uses the tier as looked up.

        PRD: "Where no such earlier enrollment exists, the district-contracted
        variant applies: administrative overhead is charged in full per step 4
        and the subsidy tier is used exactly as looked up, with recovery_basis
        set to DISTRICT_CONTRACTED."

        PRD: "invoice_due_utc is the calendar date reached by adding the
        governing cycle's invoice_due_days to the logical clock, expressed at
        23:59:59 UTC on that date."

        Design: Difficulty/dual_variant_calc/cost_recovery_district_contracted_vs_voluntary_precompliance
        """
        world = invoiced_world(client)
        order = world["order"]

        # 12.5 h at 8600 cents, 3.25 t at 9200 cents, a 32000 cent mobilization
        # fee, 12.5 percent overhead per line, and a 0.20 tier on 190576.
        assert_cost_recovery(
            order,
            labor=107500,
            disposal=29900,
            mobilization=32000,
            overhead=21176,
            pre_subsidy_total=190576,
            subsidy_pct=0.20,
            subsidy=38115,
            total_recoverable=152461,
            recovery_basis=RECOVERY_BASIS_DISTRICT,
        )
        assert_end_of_day(order["invoice_due_utc"], "2026-11-20")

    def test_voluntary_precompliance_zeroes_overhead_and_steps_the_subsidy_ladder(
        self, client
    ):
        """An owner who joined a chipper day first pays strictly less.

        PRD: "Where at least one such earlier enrollment exists, the
        voluntary-precompliance variant applies: admin_overhead_cents is forced
        to 0, so pre_subsidy_total_cents equals just the three raw cost lines,
        and subsidy_pct is stepped exactly one position toward more generous
        along the ladder whose rungs are 0.10, then 0.20, then 0.30 - a job that
        would have drawn 0.10 draws 0.20 instead, one that would have drawn 0.20
        draws 0.30, and one already at 0.30 stays at 0.30 because the ladder
        saturates there."

        PRD: "The qualifying signal is a support enrollment on the same parcel
        whose status is APPROVED, COMPLETED or REIMBURSED and whose created_at
        is strictly earlier than the substantiating notice's issued_at_utc."

        Design: Difficulty/dual_variant_calc/cost_recovery_district_contracted_vs_voluntary_precompliance
        """
        world = _voluntary_precompliance_world(client)
        order = world["order"]

        assert world["enrollment"]["status"] == "APPROVED"
        assert_cost_recovery(
            order,
            labor=107500,
            disposal=29900,
            mobilization=32000,
            overhead=0,
            pre_subsidy_total=169400,
            subsidy_pct=0.30,
            subsidy=50820,
            total_recoverable=118580,
            recovery_basis=RECOVERY_BASIS_VOLUNTARY,
        )
        # 169400 still sits in the 0.20 tier, so the more generous 0.30 can only
        # come from stepping the ladder rather than from re-running the lookup.
        assert order["total_recoverable_cents"] != 135520
        # The same cost lines under the district-contracted variant recover
        # 152461 cents, so the variant is worth 33881 cents to the owner.
        assert 152461 - order["total_recoverable_cents"] == 33881
        assert_end_of_day(order["invoice_due_utc"], "2026-11-20")


class TestPerLineOverheadRounding:
    """Overhead is rounded per line, and the waterfall is capped per share."""

    def test_overhead_rounds_each_line_before_summing(self, client):
        """A rate card with two half-cent lines exposes the rounding order.

        PRD: "Administrative overhead is charged at 12.5 percent, and it is
        charged per line and then summed: the labour line times 0.125 rounded
        half up to a whole cent, plus the disposal line times 0.125 rounded half
        up to a whole cent, plus the mobilization line times 0.125 rounded half
        up to a whole cent. The total is stored as admin_overhead_cents.
        Applying 12.5 percent to the combined lines and rounding once is a
        different number and is incorrect."

        Design: Difficulty/combinatorial_formula/admin_overhead_per_line_rounding_not_sum_then_round
        """
        world = invoiced_world(
            client, contractor_overrides={"mobilization_fee_cents": 32004}
        )
        order = world["order"]

        # 13438 + 3738 + 4001 = 21177; rounding the combined 169404 once would
        # have given 21176 and a recoverable of 152464.
        assert_cost_recovery(
            order,
            labor=107500,
            disposal=29900,
            mobilization=32004,
            overhead=21177,
            pre_subsidy_total=190581,
            subsidy_pct=0.20,
            subsidy=38116,
            total_recoverable=152465,
        )
        assert order["admin_overhead_cents"] != 21176
        assert order["total_recoverable_cents"] != 152464

    def test_waterfall_caps_each_bucket_by_its_recoverable_share(self, client):
        """A single full payment fills the buckets in the pinned order.

        PRD: "The bucket order is ADMIN_OVERHEAD first, then MOBILIZATION, then
        DISPOSAL, and LABOR last, and each bucket's capacity is the
        corresponding line amount - admin_overhead_cents,
        mobilization_line_cents, disposal_line_cents and labor_line_cents
        respectively."

        PRD: "because total_recoverable_cents is smaller than the sum of the
        caps by exactly the subsidy, the subsidy shortfall lands entirely in the
        last bucket, LABOR."

        Design: Difficulty/combinatorial_formula/admin_overhead_per_line_rounding_not_sum_then_round
        """
        world = invoiced_world(
            client, contractor_overrides={"mobilization_fee_cents": 32004}
        )
        order = world["order"]

        payment = record_payment(client, order["id"], 152465)
        assert_allocation(
            payment,
            admin_overhead=21177,
            mobilization=32004,
            disposal=29900,
            labor=69384,
        )
        assert sum(payment["allocation"].values()) == 152465
        # The labour bucket absorbs the whole 38116 cent subsidy shortfall and
        # so stays well below its 107500 cent raw line.
        assert payment["allocation"]["LABOR"] < order["labor_line_cents"]
        assert_cents(payment["outstanding_after_cents"], 0)
        assert get_order(client, order["id"])["status"] == "PAID"
