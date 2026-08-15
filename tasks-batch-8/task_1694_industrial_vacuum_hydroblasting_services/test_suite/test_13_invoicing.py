"""Invoice generation: dual-variant pricing, rounding order, volume discount,
minimum charge, corrective lines, void cascade, and job closure."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_field_work,
    create_confirmed_equipment_assignment,
    create_confirmed_operator_assignment,
    create_downtime_payload,
    create_equipment_unit,
    create_job,
    create_job_field_complete,
    create_job_in_progress,
    create_operator,
    create_site_with_active_schedule,
    create_submit_approve_jha,
    get_success_data,
    open_and_close_downtime,
    schedule_and_mobilize,
    validate_error,
    validate_success,
    verify_containment,
)

PM = TEST_USERS["project_manager_headers"]
AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
PA = TEST_USERS["platform_admin_headers"]


def _generate(api, job_id):
    resp = api.generate_invoice(job_id, PM)
    return validate_success(resp, expected_status=201)


def _walk_to_mobilized(api, site, job, assignments):
    for asg in assignments:
        get_success_data(api.confirm_assignment(asg["id"], PM))
    schedule_and_mobilize(job["id"])


def _finish(api, job, gallons, feet):
    create_submit_approve_jha(job["id"])
    get_success_data(api.start_work(job["id"], PM))
    verify_containment(job["id"])
    return complete_field_work(job["id"], gallons=gallons, feet=feet)


def _combined_field_complete(api, pricing_mode):
    """COMBINED job: 1 COMBO unit 8h + 1 hydroblast-certified operator 8h, both
    CONFIRMED; approved 5000-psi JHA; containment verified; FIELD_COMPLETE with
    4000 gal / 120 ft."""
    return create_job_field_complete(
        job_overrides={"pricing_mode": pricing_mode, "job_type": "COMBINED",
                       "description": "dual variant"},
        pressure_plan=True,
        gallons=4000,
        feet=120,
        crew="both",
    )


class TestDualVariantInvoice:
    def test_unit_rate_invoice_bills_measured_outputs(self, api):
        """PRD §3.7: "Under `UNIT_RATE`, measured outputs are billed: a `VACUUM`
        line for `VACUUM` and `COMBINED` jobs bills `gallons_removed` at the
        pinned schedule's `vacuum_per_gallon_cents`, and a `HYDRO` line for
        `HYDROBLAST` and `COMBINED` jobs bills `feet_cleaned` at
        `hydroblast_per_foot_cents`. ... Under `UNIT_RATE`, no labor or
        equipment window lines appear at all."

        Design: Difficulty/dual_variant_calc/unit_rate_vs_tm_invoice_same_inputs
        """
        ctx = _combined_field_complete(api, "UNIT_RATE")
        invoice = _generate(api, ctx["job"]["id"])
        kinds = [line["kind"] for line in invoice["lines"]]
        assert "VACUUM" in kinds and "HYDRO" in kinds
        assert "LABOR_REG" not in kinds and "EQUIPMENT" not in kinds
        # VACUUM 4000*250=1000000, HYDRO 120*1800=216000 -> subtotal 1216000;
        # 3% tier discount 36480; env fee round_half_up(1179520*0.02)=23590.
        assert invoice["subtotal_cents"] == 1216000
        assert invoice["discount_cents"] == 36480
        assert invoice["environmental_fee_cents"] == 23590
        assert invoice["total_cents"] == 1203110

    def test_tm_invoice_bills_crew_windows_and_diverges(self, api):
        """PRD §3.7: "Under `TIME_AND_MATERIALS`, crew windows are billed
        instead, and the measured gallons and feet never appear as lines."
        PRD §3.2: "the commercial `pricing_mode` (`UNIT_RATE` or
        `TIME_AND_MATERIALS`) that selects the invoice variant at billing time".

        Design: Difficulty/dual_variant_calc/unit_rate_vs_tm_invoice_same_inputs
        """
        ctx_u = _combined_field_complete(api, "UNIT_RATE")
        inv_u = _generate(api, ctx_u["job"]["id"])
        ctx_t = _combined_field_complete(api, "TIME_AND_MATERIALS")
        inv_t = _generate(api, ctx_t["job"]["id"])

        kinds_t = [line["kind"] for line in inv_t["lines"]]
        assert "LABOR_REG" in kinds_t and "EQUIPMENT" in kinds_t
        assert "VACUUM" not in kinds_t and "HYDRO" not in kinds_t
        # LABOR_REG 8h*14500=116000 + EQUIPMENT 8h*22000=176000 -> 292000;
        # discount 0; env fee 5840.
        assert inv_t["subtotal_cents"] == 292000
        assert inv_t["discount_cents"] == 0
        assert inv_t["environmental_fee_cents"] == 5840
        assert inv_t["total_cents"] == 297840
        assert inv_u["total_cents"] != inv_t["total_cents"]


class TestPerLineRoundingOrder:
    def _build_two_ot_operators_job(self, api):
        """T&M VACUUM job on labor 12995c/h (OT 1.5), minimum 0; two operators
        each CONFIRMED 9h (06:00-15:00); FIELD_COMPLETE with 0/0."""
        site, _ = create_site_with_active_schedule(
            schedule_overrides={
                "labor_rate_cents_per_hour": 12995,
                "minimum_invoice_cents": 0,
                "label": "S-B",
            }
        )
        op1 = create_operator(full_name="Ann A", employee_ref="E-201")
        op2 = create_operator(full_name="Bob B", employee_ref="E-202")
        job = create_job(site["id"], pricing_mode="TIME_AND_MATERIALS",
                         description="Pit pump-out T&M")
        from test_helpers import create_operator_assignment_payload
        a1 = get_success_data(
            api.create_assignment(
                create_operator_assignment_payload(
                    job["id"], op1["id"],
                    window_start="2026-08-01T06:00:00Z",
                    window_end="2026-08-01T15:00:00Z",
                ),
                PM,
            )
        )
        a2 = get_success_data(
            api.create_assignment(
                create_operator_assignment_payload(
                    job["id"], op2["id"],
                    window_start="2026-08-01T06:00:00Z",
                    window_end="2026-08-01T15:00:00Z",
                ),
                PM,
            )
        )
        _walk_to_mobilized(api, site, job, [a1, a2])
        _finish(api, job, gallons=0, feet=0)
        return job

    def test_per_line_rounding_amounts(self, api):
        """PRD §2.6: "Invoice construction pins the rounding order: each line's
        `amount_cents` is rounded half up to whole cents first, and the invoice
        `subtotal_cents` is then the exact integer sum of the already-rounded
        line amounts. ... Consider two overtime lines of 1.0 hour each at a
        labor rate of 12995 cents with a multiplier of 1.5: rounding per line
        first yields 19493 + 19493 = 38986 cents, while rounding only at the end
        would wrongly yield 38985."

        Design: Difficulty/combinatorial_formula/tm_invoice_per_line_rounding_beats_sum_rounding
        """
        job = self._build_two_ot_operators_job(api)
        invoice = _generate(api, job["id"])
        ot_lines = [l for l in invoice["lines"] if l["kind"] == "LABOR_OT"]
        reg_lines = [l for l in invoice["lines"] if l["kind"] == "LABOR_REG"]
        assert len(ot_lines) == 2
        for line in ot_lines:
            assert line["amount_cents"] == 19493
        assert len(reg_lines) == 2
        for line in reg_lines:
            assert line["amount_cents"] == 103960

    def test_invoice_totals_reflect_per_line_order(self, api):
        """PRD §2.6: "The alternative order — summing exact fractional amounts
        and rounding once at the end — is forbidden, because the two orders
        diverge whenever two or more lines carry a fractional half cent."
        PRD §3.7: "`total_cents` is `subtotal_cents` minus `discount_cents`
        plus `environmental_fee_cents`."

        Design: Difficulty/combinatorial_formula/tm_invoice_per_line_rounding_beats_sum_rounding
        """
        job = self._build_two_ot_operators_job(api)
        invoice = _generate(api, job["id"])
        # subtotal = 2*103960 + 2*19493 = 246906 (per-line order).
        assert invoice["subtotal_cents"] == 246906
        assert invoice["discount_cents"] == 0
        assert invoice["environmental_fee_cents"] == 4938
        assert invoice["total_cents"] == 251844


class TestVolumeDiscountTier:
    def test_exactly_500k_discountable_earns_three_percent(self, api):
        """PRD §3.7: "The volume-discount tier is selected on that pre-discount
        discountable subtotal: at least two million cents earns 7 percent; at
        least five hundred thousand cents earns 3 percent — a discountable
        subtotal of exactly five hundred thousand cents qualifies; anything
        below earns nothing."

        Design: Difficulty/combinatorial_formula/volume_discount_tier_keyed_on_prediscount_subtotal
        """
        ctx = create_job_field_complete(gallons=2000, feet=0)
        invoice = _generate(api, ctx["job"]["id"])
        assert invoice["subtotal_cents"] == 500000
        assert invoice["discount_cents"] == 15000
        assert invoice["environmental_fee_cents"] == 9700
        assert invoice["total_cents"] == 494700

    def test_tier_keyed_on_prediscount_not_postdiscount(self, api):
        """PRD §3.7: "Keying the tier on the post-discount remainder is
        forbidden: a discountable subtotal of exactly five hundred thousand
        cents, when it constitutes the entire subtotal, must produce a
        `total_cents` of 494700, where the post-discount reading would wrongly
        produce 510000."

        Design: Difficulty/combinatorial_formula/volume_discount_tier_keyed_on_prediscount_subtotal
        """
        ctx = create_job_field_complete(gallons=2000, feet=0)
        invoice = _generate(api, ctx["job"]["id"])
        assert invoice["total_cents"] == 494700
        # Under the forbidden post-discount reading the total would be 510000.
        assert invoice["total_cents"] != 510000


class TestMinimumChargeAdjustment:
    def test_minimum_charge_appends_adjustment_line(self, api):
        """PRD §3.7: "When the work lines sum below the schedule's
        `minimum_invoice_cents` — and the minimum is not zero — an `ADJUSTMENT`
        line with `origin` `AUTO_MINIMUM` and `discountable` false is appended
        for exactly the shortfall, bringing the work total up to the floor."

        Design: Corner/calculations/unit_rate_minimum_charge_adjustment_line
        """
        ctx = create_job_field_complete(gallons=100, feet=0)
        invoice = _generate(api, ctx["job"]["id"])
        assert invoice["lines"][0]["kind"] == "VACUUM"
        assert invoice["lines"][0]["amount_cents"] == 25000
        assert invoice["lines"][0]["discountable"] is True
        adj = invoice["lines"][1]
        assert adj["kind"] == "ADJUSTMENT"
        assert adj["origin"] == "AUTO_MINIMUM"
        assert adj["amount_cents"] == 50000
        assert adj["discountable"] is False
        assert invoice["subtotal_cents"] == 75000
        assert invoice["discount_cents"] == 0
        assert invoice["environmental_fee_cents"] == 1500
        assert invoice["total_cents"] == 76500


class TestTmInputSetFiltering:
    def test_unconfirmed_assignment_excluded_from_invoice(self, api):
        """PRD §3.7: "The engine walks the job's assignments in `CONFIRMED` or
        `RELEASED` status — `SCHEDULED` and `CANCELLED` are excluded — in
        creation order."

        Design: Corner/calculations/tm_invoice_excludes_unconfirmed_assignments
        """
        site, _ = create_site_with_active_schedule()
        op1 = create_operator(full_name="Ann A", employee_ref="E-201")
        op2 = create_operator(full_name="Bob B", employee_ref="E-202")
        job = create_job(site["id"], pricing_mode="TIME_AND_MATERIALS",
                         description="input set probe")
        from test_helpers import create_operator_assignment_payload
        a1 = get_success_data(
            api.create_assignment(
                create_operator_assignment_payload(job["id"], op1["id"]), PM
            )
        )
        # op2 stays SCHEDULED (never confirmed).
        get_success_data(
            api.create_assignment(
                create_operator_assignment_payload(job["id"], op2["id"]), PM
            )
        )
        get_success_data(api.confirm_assignment(a1["id"], PM))
        schedule_and_mobilize(job["id"])
        _finish(api, job, gallons=900, feet=0)
        invoice = _generate(api, job["id"])
        reg_lines = [l for l in invoice["lines"] if l["kind"] == "LABOR_REG"]
        assert len(reg_lines) == 1
        assert reg_lines[0]["amount_cents"] == 116000
        assert invoice["subtotal_cents"] == 116000
        assert invoice["discount_cents"] == 0
        assert invoice["environmental_fee_cents"] == 2320
        assert invoice["total_cents"] == 118320


class TestGenerateInvoiceGate:
    def test_generate_invoice_requires_reconciled_manifests(self, api):
        """PRD §3.7: "Two gates guard generation: every manifest of the job must
        be `RECONCILED` or `VOIDED` (`ERR_MANIFEST_UNRECONCILED` otherwise)".

        Design: Difficulty/cross_entity_state_dependency/generate_invoice_requires_reconciled_manifests
        """
        from test_helpers import (
            create_facility_and_approved_profile,
            create_issued_manifest,
        )
        ctx = create_job_in_progress()
        facility, profile = create_facility_and_approved_profile(ctx["site"]["id"])
        manifest = create_issued_manifest(ctx["job"]["id"], profile["id"], 1000)
        get_success_data(api.depart_manifest(manifest["id"], PM))
        verify_containment(ctx["job"]["id"])
        complete_field_work(ctx["job"]["id"], gallons=1000, feet=0)
        resp = api.generate_invoice(ctx["job"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_MANIFEST_UNRECONCILED.value)
        assert resp.status_code == 422
        job_after = get_success_data(api.get_job(ctx["job"]["id"], PM))
        assert job_after["execution_status"] == "FIELD_COMPLETE"

    def test_generate_invoice_after_reconcile_succeeds(self, api):
        """PRD §3.7: "Invoice generation (`FIELD_COMPLETE` → `INVOICED`, by a
        `ProjectManager`) is the pricing engine's moment."
        PRD §3.7: "every manifest of the job must be `RECONCILED` or `VOIDED`
        (`ERR_MANIFEST_UNRECONCILED` otherwise)".

        Design: Difficulty/cross_entity_state_dependency/generate_invoice_requires_reconciled_manifests
        """
        from test_helpers import (
            create_facility_and_approved_profile,
            create_issued_manifest,
        )
        ctx = create_job_in_progress()
        facility, profile = create_facility_and_approved_profile(ctx["site"]["id"])
        manifest = create_issued_manifest(ctx["job"]["id"], profile["id"], 2500)
        get_success_data(api.depart_manifest(manifest["id"], PM))
        get_success_data(api.receive_manifest(manifest["id"], {"received_tons": 10.0}, PM))
        get_success_data(api.reconcile_manifest(manifest["id"], PM))
        verify_containment(ctx["job"]["id"])
        complete_field_work(ctx["job"]["id"], gallons=1000, feet=0)
        invoice = _generate(api, ctx["job"]["id"])
        assert invoice["status"] == "DRAFT"
        job_after = get_success_data(api.get_job(ctx["job"]["id"], PM))
        assert job_after["execution_status"] == "INVOICED"


class TestGenerateInvoiceActionEndpoint:
    def test_generate_invoice_returns_full_invoice_with_lines(self, api):
        """PRD §3.7: "Every line object carries a `line_id` of the form L<n>
        assigned one-based in append order, plus `kind`, `description`,
        `quantity`, `unit`, `rate_cents`, `amount_cents`, `discountable`,
        `voided` (false at generation) and `origin`".
        PRD §3.7: "The new invoice enters as `DRAFT`, takes an `invoice_number`
        of the form INV-<job creation sequence>-<regeneration count>".

        Design: Corner/endpoints/generate_invoice_is_action_endpoint_returning_invoice
        """
        ctx = create_job_field_complete(gallons=1000, feet=0)
        resp = api.generate_invoice(ctx["job"]["id"], PM)
        assert resp.status_code == 201
        invoice = validate_success(resp, expected_status=201)
        assert invoice["status"] == "DRAFT"
        assert isinstance(invoice["invoice_number"], str)
        assert len(invoice["invoice_number"]) > 0
        first = invoice["lines"][0]
        assert first["line_id"] == "L1"
        assert first["kind"] == "VACUUM"
        assert first["quantity"] == 1000
        assert first["rate_cents"] == 250
        assert first["amount_cents"] == 250000
        assert first["discountable"] is True
        assert first["voided"] is False
        job_after = get_success_data(api.get_job(ctx["job"]["id"], PM))
        assert job_after["execution_status"] == "INVOICED"


class TestInvoiceVoidCascade:
    def _setup_billed_job(self, api):
        """VACUUM UNIT_RATE job IN_PROGRESS; 100-min CUSTOMER_DELAY event closed
        (70 billable -> 15000c); FIELD_COMPLETE at 1000 gal; invoice generated
        (total 270300); downtime BILLED."""
        ctx = create_job_in_progress()
        job_id = ctx["job"]["id"]
        event = open_and_close_downtime(job_id, "2026-08-01T01:40:00Z")
        assert event["billed_amount_cents"] == 15000
        verify_containment(job_id)
        complete_field_work(job_id, gallons=1000, feet=0)
        invoice = _generate(api, job_id)
        assert invoice["total_cents"] == 270300
        ctx["invoice"] = invoice
        ctx["event_id"] = event["id"]
        return ctx

    def test_void_reverts_job_to_field_complete(self, api):
        """PRD §3.7: "Voiding cascades in two links: the owning job reverts
        `INVOICED` → `FIELD_COMPLETE`, and every downtime event that was swept
        `BILLED` through this invoice reverts to `CLOSED` with its `invoice_id`
        cleared".

        Design: Difficulty/transitive_cascade/invoice_void_cascade_reverts_job_and_unbills_downtime
        """
        ctx = self._setup_billed_job(api)
        inv_id = ctx["invoice"]["id"]
        billed = get_success_data(api.get_downtime_event(ctx["event_id"], PM))
        assert billed["status"] == "BILLED"
        assert billed["invoice_id"] == inv_id

        get_success_data(api.void_invoice(inv_id, AM))
        job_after = get_success_data(api.get_job(ctx["job"]["id"], PM))
        assert job_after["execution_status"] == "FIELD_COMPLETE"
        invoice_after = get_success_data(api.get_invoice(inv_id, AM))
        assert invoice_after["status"] == "VOID"

    def test_void_unbills_downtime_and_clears_invoice_id(self, api):
        """PRD §3.7: "Voiding an invoice reverts exactly those events `BILLED` →
        `CLOSED`, clearing `invoice_id`, so the standby can be re-billed on the
        corrected invoice."
        PRD §3.5: "Voiding an invoice reverts exactly those events `BILLED` →
        `CLOSED`, clearing `invoice_id`".

        Design: Difficulty/transitive_cascade/invoice_void_cascade_reverts_job_and_unbills_downtime
        """
        ctx = self._setup_billed_job(api)
        inv_id = ctx["invoice"]["id"]
        get_success_data(api.void_invoice(inv_id, AM))
        event_after = get_success_data(api.get_downtime_event(ctx["event_id"], PM))
        assert event_after["status"] == "CLOSED"
        assert event_after["invoice_id"] is None


class TestInvoiceLineAdjustmentInvariant:
    def _setup_draft_invoice(self, api):
        ctx = create_job_field_complete(gallons=1000, feet=0)
        invoice = _generate(api, ctx["job"]["id"])
        assert invoice["total_cents"] == 255000
        return ctx, invoice

    def test_adding_adjustment_line_recomputes_totals(self, api):
        """PRD §3.7: "While an invoice is `DRAFT`, an `AccountManager` may
        append a corrective line by supplying a `description` and an
        `amount_cents`; the new line takes the next `line_id` in sequence, is an
        `ADJUSTMENT` kind with `origin` `MANUAL` and `discountable` false, and
        the invoice's `subtotal_cents`, `environmental_fee_cents` and
        `total_cents` recompute while the discount base is unchanged, since
        adjustments are not discountable."

        Design: Difficulty/compensating_invariant/invoice_total_invariant_under_line_add_then_void
        """
        _, invoice = self._setup_draft_invoice(api)
        updated = get_success_data(
            api.add_invoice_line(
                invoice["id"],
                {"description": "Disposal underestimate correction",
                 "amount_cents": 40000},
                AM,
            )
        )
        new_line = updated["lines"][-1]
        assert new_line["line_id"] == "L2"
        assert new_line["kind"] == "ADJUSTMENT"
        assert new_line["origin"] == "MANUAL"
        assert new_line["discountable"] is False
        assert updated["subtotal_cents"] == 290000
        assert updated["environmental_fee_cents"] == 5800
        assert updated["total_cents"] == 295800

    def test_add_then_void_line_restores_original_total(self, api):
        """PRD §3.7: "Voiding a single line of a `DRAFT` invoice sets that
        line's `voided` flag true and recomputes the totals".

        Design: Difficulty/compensating_invariant/invoice_total_invariant_under_line_add_then_void
        """
        _, invoice = self._setup_draft_invoice(api)
        original_total = invoice["total_cents"]
        updated = get_success_data(
            api.add_invoice_line(
                invoice["id"], {"description": "correction", "amount_cents": 40000}, AM
            )
        )
        restored = get_success_data(
            api.void_invoice_line(invoice["id"], "L2", AM)
        )
        assert restored["total_cents"] == original_total == 255000
        line_l2 = [l for l in restored["lines"] if l["line_id"] == "L2"][0]
        assert line_l2["voided"] is True


class TestInvoiceTerminalAndCloseGate:
    def test_paid_invoice_cannot_be_voided(self, api):
        """PRD §3.7: "voiding from either `DRAFT` or `ISSUED` lands in `VOID`,
        and `PAID` and `VOID` are terminal."
        PRD §2.8: "terminal states accept no further transitions, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/invoice_paid_terminal_cannot_be_voided
        """
        from test_helpers import create_invoiced_job
        ctx = create_invoiced_job()
        inv_id = ctx["invoice"]["id"]
        get_success_data(api.issue_invoice(inv_id, AM))
        get_success_data(api.mark_invoice_paid(inv_id, AM))
        resp = api.void_invoice(inv_id, AM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = get_success_data(api.get_invoice(inv_id, AM))
        assert after["status"] == "PAID"

    def test_job_close_blocked_until_invoice_paid(self, api):
        """PRD §3.7: "Closing (`INVOICED` → `CLOSED`, by a `ProjectManager`)
        requires the job's non-`VOID` invoice to be `PAID`, failing with
        `ERR_INVOICE_NOT_PAID` otherwise."

        Design: Corner/validations/job_close_requires_paid_invoice
        """
        from test_helpers import create_invoiced_job
        ctx = create_invoiced_job()
        inv_id = ctx["invoice"]["id"]
        get_success_data(api.issue_invoice(inv_id, AM))
        resp = api.close_job(ctx["job"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAID.value)
        assert resp.status_code == 422

    def test_job_close_after_mark_paid_succeeds(self, api):
        """PRD §3.7: "Closing (`INVOICED` → `CLOSED`, by a `ProjectManager`)
        requires the job's non-`VOID` invoice to be `PAID`, failing with
        `ERR_INVOICE_NOT_PAID` otherwise."

        Design: Corner/validations/job_close_requires_paid_invoice
        """
        from test_helpers import create_invoiced_job
        ctx = create_invoiced_job()
        inv_id = ctx["invoice"]["id"]
        get_success_data(api.issue_invoice(inv_id, AM))
        get_success_data(api.mark_invoice_paid(inv_id, AM))
        closed = get_success_data(api.close_job(ctx["job"]["id"], PM))
        assert closed["execution_status"] == "CLOSED"


class TestCreditHoldGate:
    def test_credit_hold_blocks_start_work_when_all_else_valid(self, api):
        """PRD §3.4: "The site's `credit_status` must be `GOOD_STANDING`, else
        `ERR_SITE_CREDIT_HOLD`."

        Design: Corner/validations/credit_hold_blocks_start_work_when_all_else_valid
        """
        from test_helpers import create_confirmed_equipment_assignment
        site, _ = create_site_with_active_schedule()
        unit = create_equipment_unit()
        job = create_job(site["id"], description="credit hold")
        create_confirmed_equipment_assignment(job["id"], unit["id"])
        schedule_and_mobilize(job["id"])
        create_submit_approve_jha(job["id"])
        get_success_data(
            api.update_site(site["id"], {"credit_status": "CREDIT_HOLD"}, AM)
        )
        resp = api.start_work(job["id"], PM)
        validate_error(resp, ApiErrorId.ERR_SITE_CREDIT_HOLD.value)
        assert resp.status_code == 422
        job_after = get_success_data(api.get_job(job["id"], PM))
        assert job_after["execution_status"] == "MOBILIZED"


class TestPressureRatingGate:
    def test_pressure_rating_insufficient_blocks_start_work(self, api):
        """PRD §3.4: "For `HYDROBLAST` and `COMBINED` jobs, every equipment
        assignment in `SCHEDULED`, `CONFIRMED` or `RELEASED` whose unit is
        hydroblast-capable (`HYDROBLASTER` or `COMBO`) must carry a
        `max_pressure_psi` of at least the approved analysis's
        `max_operating_pressure_psi` — and at least one such hydroblast-capable
        assignment must exist — else `ERR_PRESSURE_RATING_INSUFFICIENT`."

        Design: Corner/validations/pressure_rating_insufficient_blocks_start_work
        """
        site, _ = create_site_with_active_schedule()
        unit = create_equipment_unit(
            unit_code="HYD-LOW", unit_type="COMBO", max_pressure_psi=3000
        )
        job = create_job(site["id"], job_type="HYDROBLAST", description="pressure gate")
        create_confirmed_equipment_assignment(job["id"], unit["id"])
        schedule_and_mobilize(job["id"])
        create_submit_approve_jha(job["id"], pressure_plan=True)
        resp = api.start_work(job["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PRESSURE_RATING_INSUFFICIENT.value)
        assert resp.status_code == 422
        job_after = get_success_data(api.get_job(job["id"], PM))
        assert job_after["execution_status"] == "MOBILIZED"


class TestNoActiveScheduleGate:
    def test_job_create_without_active_schedule_rejected(self, api):
        """PRD §3.2: "when the site has no active schedule the create is
        rejected with `ERR_NO_ACTIVE_RATE_SCHEDULE`."

        Design: Corner/validations/job_create_without_active_schedule_rejected
        """
        from test_helpers import (
            create_rate_schedule_payload,
            create_site_payload,
        )
        site = get_success_data(api.create_site(create_site_payload(), AM))
        # Schedule exists but is left DRAFT (never activated).
        get_success_data(
            api.create_rate_schedule(create_rate_schedule_payload(site["id"]), AM)
        )
        resp = api.create_job(
            {"site_id": site["id"], "job_type": "VACUUM",
             "pricing_mode": "UNIT_RATE", "description": "no schedule"},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RATE_SCHEDULE.value)
        assert resp.status_code == 422
