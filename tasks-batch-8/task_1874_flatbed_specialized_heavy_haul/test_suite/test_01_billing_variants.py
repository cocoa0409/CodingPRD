"""Dual-variant billing claims: provisional estimate vs final invoice, and
declared vs measured permit-fee weight basis."""
from test_helpers import (
    BILLING,
    DRIVER,
    assert_invoice,
    assert_invoice_arithmetic,
    assert_permit,
    book_escort,
    create_customer,
    create_filed_and_granted_permit,
    create_load_for_customer,
    create_permit_for_load,
    file_and_approve_securement,
    file_permit,
    grant_permit,
    issue_invoice,
    plan_load,
    record_scale_violation,
    schedule_both_cranes,
    set_clock,
    setup_ca_oversize_overweight_cleared,
    survey_load,
    validate_success,
)


class TestInvoiceProvisionalVsFinalDiverge:
    def test_provisional_estimate_excludes_standby_and_fines(self, api):
        """PRD §3.7: "It mirrors the final invoice structure line for line but
        prices the future: linehaul is `route_miles` multiplied by the trailer's
        catalog cost per mile; permits are summed over `FILED` and `GRANTED`
        permits at their current `fee_cents`; escorts are summed over
        `CONFIRMED` bookings with each booking's charge rounded half-up
        individually before summing; `standby_cents` and `fines_cents` are both
        zero; and the subtotal, fuel surcharge, and total follow the same
        pinned rules as the invoice (§3.9)."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_diverge
        """
        ctx = setup_ca_oversize_overweight_cleared(
            company_name="Acme Machines", route_miles=500,
        )
        est = validate_success(
            api.get_cost_estimate(ctx["load"]["id"], BILLING), 200
        )
        assert est["linehaul_cents"] == 350000  # 500 mi x 700 c/mi
        assert est["permits_cents"] == 42500    # 11500 + 31000
        assert est["escorts_cents"] == 48000    # 240 min x 12000 / 60
        assert est["standby_cents"] == 0
        assert est["fines_cents"] == 0
        assert est["subtotal_cents"] == 440500
        assert est["fuel_surcharge_cents"] == 35240  # 8% of 440500
        assert est["total_cents"] == 475740

    def test_final_invoice_includes_standby_and_diverges(self, api):
        """PRD §1: "the money is pinned down twice: once as a forward-looking
        provisional estimate that guards departure, and once as a final invoice
        snapshot taken after delivery, and the two may legitimately diverge as
        permits are refiled, escorts cancel, and fines accrue."
        PRD §3.7: "`billable_minutes` is the duration minus a 120-minute free
        allowance, floored at zero, for `CUSTOMER_DELAY` events, and zero for
        carrier delays and weather."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_diverge
        """
        ctx = setup_ca_oversize_overweight_cleared(
            company_name="Acme Machines", route_miles=500,
        )
        load_id = ctx["load"]["id"]
        est = validate_success(api.get_cost_estimate(load_id, BILLING), 200)
        set_clock("2026-08-12T10:00:00Z")
        validate_success(api.depart_load(load_id, DRIVER), 200)
        delay = validate_success(
            api.create_delay_event(
                load_id,
                {
                    "kind": "CUSTOMER_DELAY",
                    "started_at": "2026-08-12T11:00:00Z",
                    "ended_at": "2026-08-12T16:00:00Z",
                },
                DRIVER,
            ),
            201,
        )
        # 300 min delay - 120 free = 180 billable min x 17500/60 = 52500
        assert delay["billable_minutes"] == 180
        assert delay["standby_amount_cents"] == 52500
        validate_success(api.arrive_load(load_id, DRIVER), 200)
        inv = issue_invoice(load_id)
        assert_invoice(inv)
        assert_invoice_arithmetic(inv)
        assert inv["standby_cents"] == 52500
        assert inv["escorts_cents"] == 48000
        assert inv["subtotal_cents"] == 493000       # 440500 + 52500
        assert inv["fuel_surcharge_cents"] == 39440  # 8% of 493000
        assert inv["total_cents"] == 532440
        # Variants diverge on identical load configuration: standby plus its
        # fuel share (52500 + 4200).
        assert inv["total_cents"] - est["total_cents"] == 56700


class TestPermitFeeDeclaredVsMeasuredBasis:
    def _setup_nv_load_with_granted_overweight(self, api):
        customer = create_customer("Basin Steel", 100_000_000)
        load = create_load_for_customer(
            customer["id"],
            cargo_description="Boiler", gross_weight_lbs=96000,
            width_in=150, height_in=100, length_in=400,
            origin="Reno NV", destination="Elko NV",
        )
        plan_load(
            load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
            trailer_axle_count=6, driver_name="B. Okafor",
            driver_oversize_endorsed=True,
        )
        surveyed = survey_load(
            load["id"], route_miles=300, states_crossed=["NV"],
            min_bridge_clearance_in=200, max_bridge_weight_lbs=120000,
        )
        # Width 150in makes the load oversize as well as overweight, so the
        # readiness gate requires BOTH OVERSIZE and OVERWEIGHT NV permits
        # (PRD §3.7 condition 2). File and grant the OVERSIZE permit first so
        # that the load can later reach CLEARED for the scale-ticket leg.
        create_filed_and_granted_permit(load["id"], "NV", "OVERSIZE")
        permit = create_permit_for_load(
            load["id"], "NV", "OVERWEIGHT",
            expected_load_version=None,
        )
        return customer, load, permit

    def test_declared_basis_fee_at_first_filing(self, api):
        """PRD §3.5: "The fee's **weight basis** is declared-versus-measured:
        when no scale ticket exists for the load, `weight_basis_lbs` is the
        shipper-declared `gross_weight_lbs`; once at least one scale ticket
        exists (typical for a refile after revocation), `weight_basis_lbs` is
        the `measured_gross_lbs` of the most recently created ticket, so
        identical dimensions produce a different fee whenever measured and
        declared weights differ."
        PRD §3.5: "For `OVERWEIGHT` they are 15,000 / 12,000 / 13,000 / 16,000
        / 14,000 cents across CA, NV, AZ, TX, OR respectively."

        Design: Difficulty/dual_variant_calc/permit_fee_declared_vs_measured_basis
        """
        _, _, permit = self._setup_nv_load_with_granted_overweight(api)
        filed = file_permit(permit["id"])
        assert_permit(filed)
        # Declared variant: NV base 12000 + excess 16000 lbs x 1 cent.
        assert filed["status"] == "FILED"
        assert filed["weight_basis_lbs"] == 96000
        assert filed["fee_cents"] == 28000

    def test_measured_basis_fee_at_refile_after_revocation(self, api):
        """PRD §3.5: "once at least one scale ticket exists (typical for a
        refile after revocation), `weight_basis_lbs` is the `measured_gross_lbs`
        of the most recently created ticket, so identical dimensions produce a
        different fee whenever measured and declared weights differ."
        PRD §3.8: "Second, every `GRANTED` `OVERWEIGHT` or `SUPERLOAD` permit
        of the load flips to `REVOKED`; `OVERSIZE` permits are unaffected."

        Design: Difficulty/dual_variant_calc/permit_fee_declared_vs_measured_basis
        """
        customer, load, permit = self._setup_nv_load_with_granted_overweight(api)
        filed1 = file_permit(permit["id"])
        grant_permit(permit["id"])
        # Complete the readiness gate so the load reaches CLEARED, making the
        # scale ticket legal (PRD §3.8 allows CLEARED/IN_TRANSIT/ON_HOLD).
        book_escort(load["id"], provider_name="High Desert Pilots",
                    position="REAR")
        schedule_both_cranes(load["id"])
        file_and_approve_securement(load["id"])
        # Violating ticket: 100000*100 > 96000*103 -> revocation cascade.
        record_scale_violation(
            load["id"], measured_gross_lbs=100000,
            weighed_at="2026-08-12T07:30:00Z",
        )
        filed2 = file_permit(permit["id"])
        assert filed2["status"] == "FILED"
        # Measured variant: latest scale ticket drives the basis.
        assert filed2["weight_basis_lbs"] == 100000
        # NV base 12000 + excess 20000 lbs x 1 cent.
        assert filed2["fee_cents"] == 32000
        # Load dimensions never changed; only the weight-basis variant switched.
        assert filed2["fee_cents"] != filed1["fee_cents"]
