"""Payment plans: the schedule-minting rounding order, the prompt-pay tier keyed
on the pre-discount subtotal, the delinquency sweep and its compensating actions."""

from test_helpers import (
    assert_installment,
    assert_money,
    assert_payment_plan,
    assert_payment_plan_conserved,
    assert_same_instant,
    create_payment_plan_payload,
    fixtures as fx,
    sorted_by_sequence,
    validate_paginated,
    validate_success,
)


def _case_past_exam(name, dob, phone, arch_position="MAXILLARY"):
    return fx.setup_case_past_exam(
        arch_position=arch_position,
        patient_overrides={"full_name": name, "date_of_birth": dob, "phone": phone},
    )


class TestScheduleMinting:
    def test_the_rounding_residual_lands_on_the_final_installment(self, api, front_office_headers):
        """PRD §3.9: "**Minting the schedule** follows a rounding order that is easy to
        get wrong. The per-installment base is `principal_amount` divided by
        `installment_count`, rounded half up to two decimal places. Every installment
        from the first up to the second-to-last carries exactly that base as its
        `amount`. The final installment — the one whose `sequence_number` equals
        `installment_count` — carries `principal_amount` minus the base multiplied by
        one less than `installment_count`, rounded half up to two decimal places, and it
        is the only row whose `is_residual_installment` is true."
        PRD §2.7: "2. **Round the unit, then place the residual.** Where a principal is
        divided into equal installments, the per-installment base is rounded first and
        the whole residual is placed on the final installment. Summing first and
        rounding once is specifically wrong here and will produce a different schedule."

        Design: Difficulty/combinatorial_formula/installment_rounding_residual_lands_on_final_row
        """
        ctx = _case_past_exam("Dilys Marchetti", "1955-04-18", "555-0244")

        plan = validate_success(
            api.create_payment_plan(
                create_payment_plan_payload(
                    ctx["patient"]["id"],
                    ctx["case"]["id"],
                    fx.case_version(ctx["case"]["id"]),
                    installment_count=7,
                    down_payment_amount=240.00,
                    first_due_date="2026-06-01T00:00:00Z",
                    frequency="MONTHLY",
                    pay_in_full=False,
                ),
                front_office_headers,
            ),
            201,
        )

        assert_payment_plan(plan)
        assert_money(plan["principal_amount"], 960.00, "PaymentPlan.principal_amount")

        rows = fx.installments_of(plan["id"])
        assert len(rows) == 7
        for row in rows[:6]:
            assert_installment(row)
            assert_money(row["amount"], 137.14, f"Installment {row['sequence_number']} amount")
            assert row["is_residual_installment"] is False
        assert_money(rows[6]["amount"], 137.16, "Installment 7 amount")
        assert rows[6]["is_residual_installment"] is True
        assert_money(sum(row["amount"] for row in rows), 960.00, "sum of Installment.amount")

    def test_the_plan_is_born_active_with_monthly_thirty_day_spacing(self, api, front_office_headers):
        """PRD §3.9: "Due dates are struck from `first_due_date`: installment number
        *k* falls due at `first_due_date` plus one less than *k* multiplied by the
        spacing, where the spacing is 30 days for a `MONTHLY` plan and 14 days for a
        `BIWEEKLY` plan. Each installment is born in `SCHEDULED` with `paid_at` null."
        PRD §3.9: "The plan itself is born in `ACTIVE` with `paid_amount` at 0.00,
        `outstanding_amount` equal to `principal_amount`, `missed_count` at zero,
        `applied_lab_credit_amount` at 0.00, and `superseded_by_plan_id` null."

        Design: Difficulty/combinatorial_formula/installment_rounding_residual_lands_on_final_row
        """
        ctx = _case_past_exam("Dilys Marchetti", "1955-04-18", "555-0244")
        plan = fx.open_payment_plan(
            ctx["patient"]["id"], ctx["case"]["id"], installment_count=7,
            down_payment_amount=240.00, first_due_date="2026-06-01T00:00:00Z",
        )

        assert plan["plan_status"] == "ACTIVE"
        assert_money(plan["outstanding_amount"], 960.00, "PaymentPlan.outstanding_amount")
        assert_money(plan["paid_amount"], 0.00, "PaymentPlan.paid_amount")
        assert_payment_plan_conserved(plan)

        rows, meta = validate_paginated(
            api.list_installments(
                front_office_headers,
                params={"payment_plan_id": plan["id"], "limit": 100, "offset": 0},
            )
        )
        assert meta["total_count"] == 7
        ordered = sorted_by_sequence(rows)
        assert_same_instant(
            ordered[0]["due_date"], "2026-06-01T00:00:00.000Z", "Installment 1 due_date"
        )
        assert_same_instant(
            ordered[6]["due_date"], "2026-11-28T00:00:00.000Z", "Installment 7 due_date"
        )
        for row in ordered:
            assert row["installment_status"] == "SCHEDULED"
            assert row["paid_at"] is None

    def test_biweekly_spacing_is_fourteen_days_and_divides_without_a_residual(self, api, front_office_headers):
        """PRD §3.9: "Due dates are struck from `first_due_date`: installment number
        *k* falls due at `first_due_date` plus one less than *k* multiplied by the
        spacing, where the spacing is 30 days for a `MONTHLY` plan and 14 days for a
        `BIWEEKLY` plan."
        PRD §3.9: "The final installment — the one whose `sequence_number` equals
        `installment_count` — carries `principal_amount` minus the base multiplied by
        one less than `installment_count`, rounded half up to two decimal places, and it
        is the only row whose `is_residual_installment` is true."

        Design: Corner/calculations/biweekly_installment_spacing_is_fourteen_days
        """
        ctx = _case_past_exam("Xenia Radu", "1955-01-25", "555-1022")

        plan = validate_success(
            api.create_payment_plan(
                create_payment_plan_payload(
                    ctx["patient"]["id"],
                    ctx["case"]["id"],
                    fx.case_version(ctx["case"]["id"]),
                    installment_count=4,
                    down_payment_amount=240.00,
                    first_due_date="2026-06-01T00:00:00Z",
                    frequency="BIWEEKLY",
                    pay_in_full=False,
                ),
                front_office_headers,
            ),
            201,
        )

        assert_money(plan["principal_amount"], 960.00, "PaymentPlan.principal_amount")
        rows = fx.installments_of(plan["id"])
        assert len(rows) == 4
        for row in rows:
            assert_money(row["amount"], 240.00, f"Installment {row['sequence_number']} amount")
        expected_due = [
            "2026-06-01T00:00:00.000Z",
            "2026-06-15T00:00:00.000Z",
            "2026-06-29T00:00:00.000Z",
            "2026-07-13T00:00:00.000Z",
        ]
        for row, expected in zip(rows, expected_due):
            assert_same_instant(row["due_date"], expected, f"Installment {row['sequence_number']}")
        assert rows[3]["is_residual_installment"] is True, (
            "the last row is the residual row even when its amount equals the others"
        )

    def test_installments_are_discoverable_only_through_the_filtered_list(self, api, front_office_headers):
        """PRD §3.9: "Plans can be listed and filtered by `patient_id`, by `case_id`, by
        `superseded_by_plan_id`, and by `plan_status`; installments by
        `payment_plan_id` and by `installment_status`."
        PRD §2.3: "The `meta` block of a list response carries `limit` and `offset`
        echoing the effective values actually applied, `total_count` giving the number
        of rows matching the filters *before* the limit and offset window is applied,
        and `has_more`, which is true exactly when `offset` plus the number of returned
        rows is strictly less than `total_count`."

        Design: Corner/entities/installments_are_only_discoverable_through_the_reverse_reachability_list
        """
        ctx = _case_past_exam("Fabien Rusu", "1953-07-07", "555-1004")
        plan = fx.open_payment_plan(ctx["patient"]["id"], ctx["case"]["id"])

        first_page, first_meta = validate_paginated(
            api.list_installments(
                front_office_headers,
                params={"payment_plan_id": plan["id"], "limit": 2, "offset": 0},
            )
        )
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert len(first_page) == 2
        for row in first_page:
            assert row["payment_plan_id"] == plan["id"]
            assert_money(row["amount"], 320.00, "Installment.amount")

        second_page, second_meta = validate_paginated(
            api.list_installments(
                front_office_headers,
                params={"payment_plan_id": plan["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(second_page) == 1
        assert second_meta["has_more"] is False


def _immediate_denture_with_a_rush_dispatch(name, dob, phone):
    """An immediate-denture case whose rush fee lifts billed_amount to exactly 2500.00."""
    fx.set_clock("2026-05-01T00:00:00Z")
    patient = fx.register_patient(full_name=name, date_of_birth=dob, phone=phone)
    lab = fx.register_lab()
    coverage = fx.enrol_coverage(
        patient["id"],
        carrier_name="Meridian Dental",
        rank="PRIMARY",
        effective_date="2024-01-01T00:00:00Z",
        annual_maximum_amount=1500.00,
        coinsurance_major_rate=0.50,
    )
    case = fx.open_case(patient["id"], "IMMEDIATE_DENTURE")
    arch = fx.add_arch(case["id"], "MAXILLARY")
    case = fx.complete_exam(case["id"])
    fx.approved_predetermination(case["id"], coverage["id"])
    fx.start_fabrication(arch["id"])
    fx.accepted_impression(arch["id"], "DIGITAL_SCAN", 88)
    lab_case = fx.draft_lab_case(
        arch["id"], lab["id"], turnaround_class="RUSH", unit_count=8
    )
    lab_case = fx.dispatch_lab_case(lab_case["id"])
    return {
        "patient": patient,
        "lab": lab,
        "case": fx.read_case(case["id"]),
        "arch": arch,
        "lab_case": lab_case,
    }


class TestPromptPayTier:
    def test_the_discount_tier_is_keyed_on_the_pre_discount_subtotal(self, api, front_office_headers):
        """PRD §3.9: "The order matters most at step 7, where a discount tier is
        chosen: **the tier is keyed on the responsibility figure computed at step 6,
        before any discount is struck, and it is never re-derived from the post-discount
        total.**"
        PRD §3.9: "7. The **discount rate** is chosen from the pre-discount
        responsibility of step 6 alone, with both tier boundaries inclusive on their
        lower edge: 0.05 when it is at or above 2500.00; 0.03 when it is at or above
        1000.00 but below 2500.00; and 0.00 below 1000.00."
        PRD §3.9: "8. `prompt_pay_discount_amount` is the pre-discount responsibility
        multiplied by that rate, rounded half up to two decimal places — **but only when
        the case has a payment plan whose `plan_status` is `ACTIVE` or `DELINQUENT` and
        whose `pay_in_full` is true.** In every other situation it is 0.00."
        PRD §3.5: "`rush_fee_amount` is 0.00 for a standard case; for a rush case it is
        120.00 plus 35.00 multiplied by the case's `unit_count`, rounded half up to two
        decimal places — so a rush case of three units carries a rush fee of 225.00."

        Design: Difficulty/combinatorial_formula/prompt_pay_discount_tier_keyed_on_pre_discount_subtotal
        """
        ctx = _immediate_denture_with_a_rush_dispatch("Eero Balogun", "1944-12-05", "555-0255")
        assert_money(ctx["lab_case"]["rush_fee_amount"], 400.00, "LabCase.rush_fee_amount")
        assert_same_instant(
            ctx["lab_case"]["promised_due_at"],
            "2026-05-05T00:00:00.000Z",
            "LabCase.promised_due_at",
        )
        assert_money(ctx["case"]["billed_amount"], 2500.00, "ProsthesisCase.billed_amount")
        assert_money(
            ctx["case"]["insurance_paid_amount"], 0.00, "ProsthesisCase.insurance_paid_amount"
        )

        validate_success(
            api.create_payment_plan(
                create_payment_plan_payload(
                    ctx["patient"]["id"],
                    ctx["case"]["id"],
                    fx.case_version(ctx["case"]["id"]),
                    installment_count=5,
                    down_payment_amount=500.00,
                    first_due_date="2026-06-01T00:00:00Z",
                    frequency="MONTHLY",
                    pay_in_full=True,
                ),
                front_office_headers,
            ),
            201,
        )

        case = fx.read_case(ctx["case"]["id"])
        assert_money(
            case["prompt_pay_discount_amount"],
            125.00,
            "ProsthesisCase.prompt_pay_discount_amount at the 0.05 tier",
        )
        assert_money(
            case["patient_responsibility_amount"],
            2375.00,
            "ProsthesisCase.patient_responsibility_amount",
        )

    def test_the_principal_is_struck_after_the_discount_and_divides_evenly(self, api):
        """PRD §3.9: "The floor is checked **first**, and it is checked against the
        **pre-discount** responsibility: `down_payment_amount` must be at least 0.20
        times the case's `patient_responsibility_amount` as it stands before any
        prompt-pay discount is struck, and a smaller down payment is a rung 7 failure
        carrying `ERR_VALIDATION`. Only once that check has passed is the prompt-pay
        discount applied to the case — steps 7 and 8 above, which now see a live plan
        with `pay_in_full` true — and only then is the plan's `principal_amount` struck
        as the resulting `patient_responsibility_amount` minus `down_payment_amount`,
        rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/prompt_pay_discount_tier_keyed_on_pre_discount_subtotal
        """
        ctx = _immediate_denture_with_a_rush_dispatch("Eero Balogun", "1944-12-05", "555-0255")

        plan = fx.open_payment_plan(
            ctx["patient"]["id"],
            ctx["case"]["id"],
            installment_count=5,
            down_payment_amount=500.00,
            first_due_date="2026-06-01T00:00:00Z",
            pay_in_full=True,
        )

        assert_money(plan["principal_amount"], 1875.00, "PaymentPlan.principal_amount")
        rows = fx.installments_of(plan["id"])
        assert len(rows) == 5
        for row in rows:
            assert_money(row["amount"], 375.00, f"Installment {row['sequence_number']} amount")


class TestDelinquencySweep:
    def _plan_due_on_the_fifth(self, name, dob, phone):
        ctx = _case_past_exam(name, dob, phone, arch_position="MANDIBULAR")
        plan = fx.open_payment_plan(
            ctx["patient"]["id"], ctx["case"]["id"], first_due_date="2026-05-05T00:00:00Z"
        )
        ctx["plan"] = plan
        return ctx

    def test_at_exactly_ten_days_past_due_the_installment_is_still_on_time(self, api, platform_admin_headers):
        """PRD §3.9: "It walks that plan's installments in `SCHEDULED` only — rows in
        `PAID` and `WAIVED` are never swept — and moves to `MISSED` every row whose
        `due_date` plus 10 days is **strictly before** the logical clock. The grace
        boundary is strict on that side: an installment observed at exactly 10 days
        after its `due_date` is still on time and is not swept."
        PRD §3.9: "at zero the plan's status is left exactly as it was."

        Design: Difficulty/boundary_precision_check/installment_grace_boundary_exactly_ten_days_is_still_on_time
        """
        ctx = self._plan_due_on_the_fifth("Piet Vandenberg", "1960-01-25", "555-0377")

        fx.set_clock("2026-05-15T00:00:00Z")
        swept = validate_success(
            api.assess_delinquency(ctx["plan"]["id"], platform_admin_headers), 200
        )

        assert swept["plan_status"] == "ACTIVE"
        assert swept["missed_count"] == 0
        assert fx.read_patient(ctx["patient"]["id"])["write_gate_active"] is False
        for row in fx.installments_of(ctx["plan"]["id"]):
            assert row["installment_status"] == "SCHEDULED"

    def test_one_second_past_the_grace_boundary_the_row_is_missed_and_the_gate_rises(self, api, platform_admin_headers):
        """PRD §3.9: "The plan's `missed_count` is then re-derived as the count of its
        installments sitting in `MISSED`, and the plan's status follows from it: at 3 or
        more the plan is `DEFAULTED`; at 1 or 2 it is `DELINQUENT`; at zero the plan's
        status is left exactly as it was. A sweep that leaves the plan `DELINQUENT` or
        `DEFAULTED` sets the patient's `write_gate_active` to true."
        PRD §2.11: "The mirror of the gate is carried on the patient row as
        `write_gate_active`, a computed boolean that is true exactly when the patient
        owns at least one delinquent or defaulted plan."

        Design: Difficulty/boundary_precision_check/installment_grace_boundary_exactly_ten_days_is_still_on_time
        """
        ctx = self._plan_due_on_the_fifth("Piet Vandenberg", "1960-01-25", "555-0377")
        fx.set_clock("2026-05-15T00:00:00Z")
        fx.assess_delinquency(ctx["plan"]["id"])

        fx.set_clock("2026-05-15T00:00:01Z")
        swept = validate_success(
            api.assess_delinquency(ctx["plan"]["id"], platform_admin_headers), 200
        )

        assert swept["plan_status"] == "DELINQUENT"
        assert swept["missed_count"] == 1
        assert fx.read_patient(ctx["patient"]["id"])["write_gate_active"] is True

        rows = fx.installments_of(ctx["plan"]["id"])
        assert rows[0]["installment_status"] == "MISSED"
        assert rows[1]["installment_status"] == "SCHEDULED"
        assert rows[2]["installment_status"] == "SCHEDULED"


class TestPaymentConservation:
    def test_paying_an_installment_moves_its_amount_from_outstanding_to_paid(self, api, front_office_headers):
        """PRD §2.13: "**Payment plan balance.** On any payment plan, `paid_amount`
        plus `outstanding_amount` always equals `principal_amount`. Paying an
        installment moves the installment's `amount` from outstanding to paid;
        reversing that payment moves it back."
        PRD §3.9: "A payment moves the row `SCHEDULED → PAID` or `MISSED → PAID`,
        stamps `paid_at`, raises the plan's `paid_amount` by the installment's `amount`,
        lowers its `outstanding_amount` by the same, and increments the installment's
        `version` by 1."

        Design: Difficulty/compensating_invariant/payment_plan_principal_conserved_across_pay_and_reverse_payment
        """
        ctx = _case_past_exam("Wren Kilcoyne", "1962-02-28", "555-0455")
        plan = fx.open_payment_plan(ctx["patient"]["id"], ctx["case"]["id"])
        assert_money(plan["paid_amount"], 0.00, "PaymentPlan.paid_amount before")
        assert_money(plan["outstanding_amount"], 960.00, "PaymentPlan.outstanding_amount before")
        assert_payment_plan_conserved(plan)

        first = fx.installments_of(plan["id"], "SCHEDULED")[0]
        paid = validate_success(
            api.pay_installment(first["id"], {"amount_paid": 320.00}, front_office_headers), 200
        )

        assert paid["installment_status"] == "PAID"
        after = fx.read_payment_plan(plan["id"])
        assert_money(after["paid_amount"], 320.00, "PaymentPlan.paid_amount after the pay")
        assert_money(
            after["outstanding_amount"], 640.00, "PaymentPlan.outstanding_amount after the pay"
        )
        assert_payment_plan_conserved(after)
        assert after["plan_status"] == "ACTIVE"

    def test_reversing_the_payment_puts_the_amount_back_and_clears_paid_at(self, api, front_office_headers):
        """PRD §3.9: "It is available from `PAID`, and the destination is decided by
        where the logical clock sits relative to the grace boundary rather than by
        anything the caller says: when the clock is **at or before** the installment's
        `due_date` plus 10 days the row returns to `SCHEDULED`, and when the clock is
        **strictly after** that instant the row goes to `MISSED` instead and the plan's
        `missed_count` rises by one, which will re-raise the write gate through the
        plan's delinquency transition at the next sweep. Either way the plan's
        `paid_amount` falls by the installment's `amount`, its `outstanding_amount`
        rises by the same, `paid_at` is cleared back to null, and the installment's
        `version` increments by 1."

        Design: Difficulty/compensating_invariant/payment_plan_principal_conserved_across_pay_and_reverse_payment
        """
        ctx = _case_past_exam("Wren Kilcoyne", "1962-02-28", "555-0455")
        plan = fx.open_payment_plan(ctx["patient"]["id"], ctx["case"]["id"])
        first = fx.installments_of(plan["id"], "SCHEDULED")[0]
        fx.pay_installment(first["id"], 320.00)

        reversed_row = validate_success(
            api.reverse_installment_payment(first["id"], front_office_headers), 200
        )

        assert reversed_row["installment_status"] == "SCHEDULED", (
            "the logical clock is at or before the installment's due_date plus 10 days"
        )
        assert reversed_row["paid_at"] is None
        after = fx.read_payment_plan(plan["id"])
        assert_money(after["paid_amount"], 0.00, "PaymentPlan.paid_amount after the reversal")
        assert_money(
            after["outstanding_amount"], 960.00, "PaymentPlan.outstanding_amount after the reversal"
        )
        assert_payment_plan_conserved(after)
        assert after["plan_status"] == "ACTIVE"


class TestPlanSupersedeAndCure:
    def test_a_new_plan_supersedes_the_old_one_and_waives_its_open_schedule(self, api, front_office_headers):
        """PRD §3.9: "Creating a plan also **supersedes**. Any existing plan on the same
        case whose `plan_status` is `ACTIVE` or `DELINQUENT` moves to `SUPERSEDED`, has
        its `superseded_by_plan_id` set to the new plan's identifier, and has every one
        of its own installments still sitting in `SCHEDULED` or `MISSED` moved to
        `WAIVED`"
        PRD §3.9: "Plans can be listed and filtered by `patient_id`, by `case_id`, by
        `superseded_by_plan_id`, and by `plan_status`; installments by `payment_plan_id`
        and by `installment_status`."

        Design: Corner/cross_cutting_layers/payment_plan_supersede_waives_the_previous_schedule
        """
        ctx = _case_past_exam("Ulla Mattila", "1949-12-16", "555-1044")
        first_plan = fx.open_payment_plan(ctx["patient"]["id"], ctx["case"]["id"])

        second_plan = validate_success(
            api.create_payment_plan(
                create_payment_plan_payload(
                    ctx["patient"]["id"],
                    ctx["case"]["id"],
                    fx.case_version(ctx["case"]["id"]),
                    installment_count=6,
                    down_payment_amount=240.00,
                    first_due_date="2026-06-01T00:00:00Z",
                    frequency="MONTHLY",
                    pay_in_full=False,
                ),
                front_office_headers,
            ),
            201,
        )

        superseded = fx.read_payment_plan(first_plan["id"])
        assert superseded["plan_status"] == "SUPERSEDED"
        assert superseded["superseded_by_plan_id"] == second_plan["id"]
        for row in fx.installments_of(first_plan["id"]):
            assert row["installment_status"] == "WAIVED"

        assert second_plan["plan_status"] == "ACTIVE"
        assert_money(second_plan["principal_amount"], 960.00, "PaymentPlan.principal_amount")
        new_rows = fx.installments_of(second_plan["id"])
        assert len(new_rows) == 6
        for row in new_rows:
            assert_money(row["amount"], 160.00, f"Installment {row['sequence_number']} amount")

        rows, meta = validate_paginated(
            api.list_payment_plans(
                front_office_headers,
                params={
                    "superseded_by_plan_id": second_plan["id"], "limit": 10, "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first_plan["id"]

    def test_the_patient_pays_their_own_missed_installment_and_lowers_the_gate(self, api):
        """PRD §3.9: "Paying a row that was `MISSED` additionally lowers the plan's
        `missed_count` by one, and when `missed_count` reaches zero the plan **cures**
        back from `DELINQUENT` or `DEFAULTED` to `ACTIVE` — which sets the patient's
        `write_gate_active` to false unless another plan of that patient is still
        delinquent or defaulted, lowering the global write gate."
        PRD §2.11: "- `POST /prosthetics/installments/{installment_id}/pay`. Paying is
        the cure; gating the cure makes the gate unrecoverable."

        Design: Corner/rbac/patient_pays_own_installment_and_cures_the_write_gate
        """
        ctx = _case_past_exam("Riina Kallio", "1957-09-13", "555-1041")
        plan = fx.open_payment_plan(
            ctx["patient"]["id"], ctx["case"]["id"], first_due_date="2026-05-05T00:00:00Z"
        )
        fx.set_clock("2026-05-20T00:00:00Z")
        plan = fx.assess_delinquency(plan["id"])

        assert plan["plan_status"] == "DELINQUENT"
        assert plan["missed_count"] == 1
        assert fx.read_patient(ctx["patient"]["id"])["write_gate_active"] is True

        missed = fx.installments_of(plan["id"], "MISSED")[0]
        paid = validate_success(
            api.pay_installment(
                missed["id"],
                {"amount_paid": 320.00},
                fx.make_patient_headers(ctx["patient"]["id"]),
            ),
            200,
        )

        assert paid["installment_status"] == "PAID"
        assert_same_instant(paid["paid_at"], "2026-05-20T00:00:00.000Z", "Installment.paid_at")
        cured = fx.read_payment_plan(plan["id"])
        assert cured["plan_status"] == "ACTIVE"
        assert cured["missed_count"] == 0
        assert_money(cured["paid_amount"], 320.00, "PaymentPlan.paid_amount")
        assert_money(cured["outstanding_amount"], 640.00, "PaymentPlan.outstanding_amount")
        assert fx.read_patient(ctx["patient"]["id"])["write_gate_active"] is False
