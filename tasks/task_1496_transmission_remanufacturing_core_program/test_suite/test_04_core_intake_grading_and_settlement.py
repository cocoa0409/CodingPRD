"""Core intake at the dock, completeness grading, lateness tiers, and the
settlement cascade onto the invoice and the order."""
import pytest

from test_helpers import (
    ANY_H,
    CLERK,
    INSPECTOR,
    ApiErrorId,
    assert_core_deposit_invoice,
    assert_core_unit,
    assert_deposit_invariant,
    create_core_unit_payload,
    create_inspection_payload,
    create_min_model,
    drive_order_to_shipped,
    get_invoice,
    get_invoice_for_order,
    get_order,
    inspect_core,
    register_core,
    set_clock,
    setup_graded_core,
    setup_registered_core,
    api_client,
    validate_error,
    validate_success,
)


class TestGradeBoundaries:

    def test_grade_boundary_score_30_grade_c(self):
        """PRD §3.6: "The `deduction_score` sums the finding weights: a missing torque converter costs 20 points, a missing valve body 25, a missing sensor harness 10, a damaged bell housing 15, and a missing pan 5."
        PRD §3.6: "otherwise a `deduction_score` of at most 5 earns grade `A`, at most 15 earns `B`, at most 30 earns `C`, and anything higher is `REJECTED`."

        Design: Corner/calculations/inspection_grade_boundary_30_vs_35
        """
        _m, _o, invoice, core = setup_registered_core()
        resp = api_client.inspect_core_unit(
            core["id"],
            create_inspection_payload(
                False, ["TORQUE_CONVERTER_MISSING", "SENSOR_HARNESS_MISSING"]),
            INSPECTOR,
        )
        graded = validate_success(resp)
        assert graded["deduction_score"] == 30, "20 + 10 = 30"
        assert graded["grade"] == "C", "30 is the last score still earning C"
        assert graded["status"] == "GRADED"

        settled = get_invoice(invoice["id"])
        assert settled["final_credit_cents"] == 25000, \
            "grade C on-time pays 50000 * 0.5 * 1.0 = 25000"
        assert settled["forfeited_cents"] == 25000
        assert settled["status"] == "SETTLED_PARTIAL"
        assert_deposit_invariant(settled)

    def test_grade_boundary_score_35_rejected(self):
        """PRD §3.6: "otherwise a `deduction_score` of at most 5 earns grade `A`, at most 15 earns `B`, at most 30 earns `C`, and anything higher is `REJECTED`."
        PRD §3.6: "When the grade is `REJECTED` or the core arrived more than 45 days late, the outcome is harsh: `final_credit_cents` becomes 0, `forfeited_cents` becomes the full `deposit_cents`, the invoice moves `AWAITING_GRADE` → `FORFEITED`, and the core's status records `REJECTED`."

        Design: Corner/calculations/inspection_grade_boundary_30_vs_35
        """
        _m, _o, invoice, core = setup_registered_core()
        resp = api_client.inspect_core_unit(
            core["id"],
            create_inspection_payload(
                False, ["TORQUE_CONVERTER_MISSING", "BELL_HOUSING_DAMAGED"]),
            INSPECTOR,
        )
        graded = validate_success(resp)
        assert graded["deduction_score"] == 35, "20 + 15 = 35"
        assert graded["grade"] == "REJECTED", "35 is above the C ceiling of 30"
        assert graded["status"] == "REJECTED"

        settled = get_invoice(invoice["id"])
        assert settled["final_credit_cents"] == 0
        assert settled["forfeited_cents"] == 50000
        assert settled["status"] == "FORFEITED"
        assert_deposit_invariant(settled)


class TestLateness:

    def test_core_over_45_days_forfeits(self):
        """PRD §3.6: "A core received at most 30 days after the invoice was issued earns the full late factor of 1.0; from 31 through 45 days the factor drops to 0.75; beyond 45 days the credit is forfeited outright."
        PRD §3.6: "`days_late` is computed as the whole days between the invoice's `issued_at` and `received_at` — the elapsed seconds divided by 86400 and rounded down."

        Design: Corner/calculations/core_return_over_45_days_forfeits
        """
        _m, _o, invoice = drive_order_to_shipped()
        set_clock("2026-09-16T00:00:00Z")  # 46 days after issuance
        core = register_core(invoice["id"], "DOCK-1",
                             "2026-09-16T10:00:00Z", "2026-09-16T11:00:00Z")
        assert core["days_late"] == 46

        graded = inspect_core(core["id"], findings=[])
        settled = get_invoice(invoice["id"])
        assert settled["final_credit_cents"] == 0, \
            "even a spotless core forfeits the deposit beyond 45 days"
        assert settled["forfeited_cents"] == 50000
        assert settled["status"] == "FORFEITED"
        assert_deposit_invariant(settled)

    def test_case_cracked_forces_rejection(self):
        """PRD §3.6: "The `grade` — null until the first inspection — is forced to `REJECTED` whenever the case is cracked; otherwise a `deduction_score` of at most 5 earns grade `A`".

        Design: Corner/calculations/case_cracked_forces_rejection
        """
        _m, _o, invoice, core = setup_registered_core()
        graded = inspect_core(core["id"], case_cracked=True, findings=[])
        assert graded["deduction_score"] == 0
        assert graded["grade"] == "REJECTED", \
            "a cracked case short-circuits the deduction ladder"
        assert graded["status"] == "REJECTED"

        settled = get_invoice(invoice["id"])
        assert settled["final_credit_cents"] == 0
        assert settled["status"] == "FORFEITED"


class TestProvisionalVersusFinalCredit:

    def test_provisional_credit_at_issuance(self):
        """PRD §3.5: "`provisional_credit_cents` is 80% of the deposit, rounded half-up to whole cents, on the assumption of a complete, grade-`A`-equivalent return and with no inspection input."
        PRD §3.5: "That estimate is superseded by `final_credit_cents` at grading; both `final_credit_cents` and `forfeited_cents` stay null until the first settlement."

        Design: Difficulty/dual_variant_calc/core_credit_provisional_vs_graded_final
        """
        _m, order, invoice = drive_order_to_shipped()
        assert_core_deposit_invoice(invoice)
        assert invoice["reman_order_id"] == order["id"]
        assert invoice["buyer_ref"] == "BUYER-1"
        assert invoice["deposit_cents"] == 50000
        assert invoice["provisional_credit_cents"] == 40000, \
            f"80% of 50000 rounds to 40000, got {invoice['provisional_credit_cents']}"
        assert invoice["final_credit_cents"] is None
        assert invoice["forfeited_cents"] is None
        assert invoice["status"] == "OPEN"

    def test_final_credit_supersedes_provisional(self):
        """PRD §3.5: "That estimate is superseded by `final_credit_cents` at grading".
        PRD §3.6: "the invoice settles `AWAITING_GRADE` → `SETTLED_FULL` when the credit exactly equals the deposit and `AWAITING_GRADE` → `SETTLED_PARTIAL` when it falls short".

        Design: Difficulty/dual_variant_calc/core_credit_provisional_vs_graded_final
        """
        _m, _o, invoice, core = setup_registered_core()
        inspect_core(core["id"], findings=[])  # grade A, on-time

        settled = get_invoice(invoice["id"])
        assert settled["provisional_credit_cents"] == 40000, \
            "the provisional estimate remains recorded on the invoice"
        assert settled["final_credit_cents"] == 50000, \
            "a clean grade-A on-time return credits the full deposit"
        assert settled["provisional_credit_cents"] != settled["final_credit_cents"], \
            "the two variants diverge on the same deposit"
        assert settled["forfeited_cents"] == 0
        assert settled["status"] == "SETTLED_FULL"
        assert_deposit_invariant(settled)


class TestGradeLateComposition:

    def test_grade_b_late_composition(self):
        """PRD §3.6: "Otherwise the final credit is the deposit multiplied by the grade multiplier — 1.0 for `A`, 0.75 for `B`, 0.5 for `C` — and then by the late factor, rounded half-up to whole cents".
        PRD §3.6: "from 31 through 45 days the factor drops to 0.75".

        Design: Difficulty/combinatorial_formula/core_credit_grade_late_branch_composition
        """
        _m, _o, invoice = drive_order_to_shipped()
        set_clock("2026-09-05T00:00:00Z")  # 35 days after issuance
        core = register_core(invoice["id"], "DOCK-1",
                             "2026-09-05T10:00:00Z", "2026-09-05T11:00:00Z")
        graded = inspect_core(core["id"], findings=["SENSOR_HARNESS_MISSING"])
        assert graded["deduction_score"] == 10
        assert graded["grade"] == "B"
        assert graded["days_late"] == 35

        settled = get_invoice(invoice["id"])
        assert settled["final_credit_cents"] == 28125, \
            "50000 * 0.75 (grade B) * 0.75 (late) = 28125"
        assert settled["forfeited_cents"] == 21875
        assert settled["status"] == "SETTLED_PARTIAL"
        assert_deposit_invariant(settled)

    def test_grade_b_on_time_no_late_factor(self):
        """PRD §3.6: "A core received at most 30 days after the invoice was issued earns the full late factor of 1.0".
        PRD §3.6: "Otherwise the final credit is the deposit multiplied by the grade multiplier — 1.0 for `A`, 0.75 for `B`, 0.5 for `C` — and then by the late factor, rounded half-up to whole cents".

        Design: Difficulty/combinatorial_formula/core_credit_grade_late_branch_composition
        """
        _m, _o, invoice, core = setup_registered_core()
        graded = inspect_core(core["id"], findings=["SENSOR_HARNESS_MISSING"])
        assert graded["grade"] == "B"
        assert graded["days_late"] == 0

        settled = get_invoice(invoice["id"])
        assert settled["final_credit_cents"] == 37500, \
            "50000 * 0.75 * 1.0 = 37500 with no lateness discount"
        assert settled["forfeited_cents"] == 12500
        assert settled["status"] == "SETTLED_PARTIAL"
        assert_deposit_invariant(settled)


class TestDayCountBoundary:

    def _two_shipped_orders(self):
        model = create_min_model()
        _m1, o1, inv1 = drive_order_to_shipped(model=model, buyer_ref="BUYER-1",
                                               cell="DYNO-1")
        _m2, o2, inv2 = drive_order_to_shipped(model=model, buyer_ref="BUYER-2",
                                               cell="DYNO-2")
        return inv1, inv2

    def test_day_30_on_time_full_credit(self):
        """PRD §3.6: "A core received at most 30 days after the invoice was issued earns the full late factor of 1.0".
        PRD §3.6: "the invoice settles `AWAITING_GRADE` → `SETTLED_FULL` when the credit exactly equals the deposit".

        Design: Difficulty/boundary_precision_check/core_return_day_30_ontime_day_31_late
        """
        inv1, _inv2 = self._two_shipped_orders()
        set_clock("2026-08-31T00:00:00Z")  # exactly 30 days after issuance
        core = register_core(inv1["id"], "DOCK-1",
                             "2026-08-31T10:00:00Z", "2026-08-31T11:00:00Z")
        graded = inspect_core(core["id"], findings=[])
        assert graded["days_late"] == 30
        assert graded["grade"] == "A"

        settled = get_invoice(inv1["id"])
        assert settled["final_credit_cents"] == 50000, \
            "day 30 is still on-time: full credit, no late factor"
        assert settled["status"] == "SETTLED_FULL"

    def test_day_31_late_factor_applies(self):
        """PRD §3.6: "from 31 through 45 days the factor drops to 0.75".
        PRD §3.6: "`days_late` is computed as the whole days between the invoice's `issued_at` and `received_at` — the elapsed seconds divided by 86400 and rounded down."

        Design: Difficulty/boundary_precision_check/core_return_day_30_ontime_day_31_late
        """
        inv1, inv2 = self._two_shipped_orders()
        set_clock("2026-08-31T00:00:00Z")
        core1 = register_core(inv1["id"], "DOCK-1",
                              "2026-08-31T10:00:00Z", "2026-08-31T11:00:00Z")
        inspect_core(core1["id"], findings=[])

        set_clock("2026-09-01T00:00:00Z")  # 31 days after issuance
        core2 = register_core(inv2["id"], "DOCK-1",
                              "2026-09-01T12:00:00Z", "2026-09-01T13:00:00Z")
        graded2 = inspect_core(core2["id"], findings=[])
        assert graded2["days_late"] == 31
        assert graded2["grade"] == "A"

        settled2 = get_invoice(inv2["id"])
        assert settled2["final_credit_cents"] == 37500, \
            "50000 * 1.0 * 0.75 = 37500 once the core is late"
        assert settled2["status"] == "SETTLED_PARTIAL"
        assert_deposit_invariant(settled2)


class TestSettlementCascade:

    def test_full_settlement_values(self):
        """PRD §3.6: "the invoice settles `AWAITING_GRADE` → `SETTLED_FULL` when the credit exactly equals the deposit and `AWAITING_GRADE` → `SETTLED_PARTIAL` when it falls short; and the core's status records `GRADED`."

        Design: Difficulty/transitive_cascade/core_grade_settles_invoice_closes_order
        """
        _m, _o, invoice, core = setup_registered_core()
        graded = inspect_core(core["id"], findings=[])
        assert graded["grade"] == "A"
        assert graded["status"] == "GRADED"

        settled = get_invoice(invoice["id"])
        assert settled["status"] == "SETTLED_FULL"
        assert settled["final_credit_cents"] == 50000
        assert settled["forfeited_cents"] == 0

    def test_full_settlement_closes_order_partial_does_not(self):
        """PRD §3.6: "Whenever an invoice reaches `SETTLED_FULL`, the linked order's `core_settlement_status` flips from `PENDING` to `CLOSED`, completing the deposit lifecycle for that build."

        Design: Difficulty/transitive_cascade/core_grade_settles_invoice_closes_order
        """
        # One shared model (PRD §3.1: model_code is unique across all models);
        # distinct dyno cells (§3.4) and distinct docks (§3.6) so the two
        # builds' bookings and registrations never conflict.
        model = create_min_model()
        # Order 1: grade A -> SETTLED_FULL -> order closes.
        _m1, o1, inv1, c1 = setup_registered_core(model=model, buyer_ref="BUYER-1",
                                                  dock_code="DOCK-1",
                                                  cell="DYNO-1")
        inspect_core(c1["id"], findings=[])
        after1 = get_order(o1["id"])
        assert after1["core_settlement_status"] == "CLOSED", \
            "full settlement must close the order's core settlement"

        # Order 2: grade B -> SETTLED_PARTIAL -> order stays open.
        _m2, o2, inv2, c2 = setup_registered_core(model=model, buyer_ref="BUYER-2",
                                                  dock_code="DOCK-2",
                                                  cell="DYNO-2")
        inspect_core(c2["id"], findings=["SENSOR_HARNESS_MISSING"])
        inv2_after = get_invoice(inv2["id"])
        assert inv2_after["status"] == "SETTLED_PARTIAL"
        after2 = get_order(o2["id"])
        assert after2["core_settlement_status"] == "PENDING", \
            "only SETTLED_FULL (or SETTLED_ADJUSTED) closes the order"


class TestDockBufferGeometry:

    def _two_invoices(self):
        model = create_min_model()
        _m1, o1, inv1 = drive_order_to_shipped(model=model, buyer_ref="BUYER-1",
                                               cell="DYNO-1")
        _m2, o2, inv2 = drive_order_to_shipped(model=model, buyer_ref="BUYER-2",
                                               cell="DYNO-2")
        return inv1, inv2

    def test_dock_start_at_prior_end_rejected(self):
        """PRD §3.6: "Dock appointments occupy closed intervals, and each appointment carries a 30-minute turnaround buffer appended after its end; a new appointment whose closed interval conflicts with an existing appointment's buffer-padded occupancy on the same dock is rejected with `ERR_DOCK_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/core_dock_closed_interval_with_buffer
        """
        inv1, inv2 = self._two_invoices()
        register_core(inv1["id"], "DOCK-9",
                      "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")

        resp = api_client.create_core_unit(
            create_core_unit_payload(inv2["id"], "DOCK-9",
                                     "2026-08-01T11:00:00Z",
                                     "2026-08-01T12:00:00Z"),
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_DOCK_OVERLAP)

    def test_dock_start_after_buffer_accepted(self):
        """PRD §3.6: "a new appointment whose closed interval conflicts with an existing appointment's buffer-padded occupancy on the same dock is rejected with `ERR_DOCK_OVERLAP`."
        PRD §3.6: "registration atomically flips the invoice `OPEN` → `AWAITING_GRADE`".

        Design: Difficulty/resource_temporal_overlap/core_dock_closed_interval_with_buffer
        """
        inv1, inv2 = self._two_invoices()
        register_core(inv1["id"], "DOCK-9",
                      "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")

        # Start strictly clear of the prior appointment's buffer-padded
        # occupancy (prior end 11:00 + 30-minute buffer): accepted.
        resp = api_client.create_core_unit(
            create_core_unit_payload(inv2["id"], "DOCK-9",
                                     "2026-08-01T12:00:00Z",
                                     "2026-08-01T13:00:00Z"),
            CLERK,
        )
        core = validate_success(resp, expected_status=201)
        assert_core_unit(core)
        assert core["status"] == "RECEIVED", \
            "a start clear of the prior appointment's 30-minute buffer is accepted"
        invoice = get_invoice(inv2["id"])
        assert invoice["status"] == "AWAITING_GRADE"


class TestInspectGate:

    def test_double_inspect_rejected(self):
        """PRD §3.6: "A `CoreInspector` then grades the core, permitted while it is `RECEIVED` or in `RE_INSPECTION` (`ERR_CORE_NOT_INSPECTABLE` otherwise)."

        Design: Corner/errors/double_inspect_rejected
        """
        _m, _o, _invoice, core = setup_graded_core(findings=[])
        assert core["grade"] == "A"
        resp = api_client.inspect_core_unit(
            core["id"], create_inspection_payload(False, ["PAN_MISSING"]),
            INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_CORE_NOT_INSPECTABLE)

        after = validate_success(api_client.get_core_unit(core["id"], ANY_H))
        assert after["grade"] == "A", "a rejected re-inspection must not re-grade"
        assert after["deduction_score"] == 0
