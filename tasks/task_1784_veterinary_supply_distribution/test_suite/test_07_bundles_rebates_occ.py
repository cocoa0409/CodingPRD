"""Bundle programs, rebate accrual variants, and optimistic concurrency
(PRD §3.8, §2.7)."""
from test_helpers import (
    ACCOUNT_MANAGER,
    ApiErrorId,
    accruals_for_order,
    assert_bundle_enrollment,
    assert_rebate_accrual,
    approve_order,
    create_active_clinic,
    create_active_program,
    create_approved_order,
    create_bundle_program,
    create_clinic,
    create_lot,
    create_order,
    create_product,
    create_stocked_product,
    enroll_clinic,
    get_accrual,
    get_clinic,
    get_enrollment,
    get_order,
    get_success_data,
    make_clinic_buyer_headers,
    order_line_spec,
    setup_enrolled_clinic,
    ship_and_deliver,
    sole_accrual_for_order,
    submit_order,
    validate_error,
    validate_success,
)

# Shared program shape for the rebate tests: ACME-VET / [CONSUMABLE], no
# discount, 200bp base, 500bp bonus at 1000000c quarter-to-date.
REBATE_PROGRAM = {
    "manufacturer_code": "ACME-VET",
    "qualifying_product_types": ["CONSUMABLE"],
    "min_distinct_categories": 1,
    "bundle_discount_pct": 0,
    "rebate_base_rate_bp": 200,
    "rebate_bonus_rate_bp": 500,
    "bonus_threshold_cents": 1000000,
}


def _setup_rebate_clinic(api, clinic_name, license_number, ship_to):
    """ACTIVE clinic enrolled (2026-Q3) in the shared ACTIVE ACME program,
    with a 10000c ACME CONSUMABLE product stocked 200 deep."""
    clinic, program, enrollment = setup_enrolled_clinic(
        program_overrides=dict(REBATE_PROGRAM),
        clinic_overrides={
            "clinic_name": clinic_name, "license_number": license_number,
            "ship_to_address": ship_to, "credit_limit_cents": 5000000,
            "minimum_order_value_cents": 50000,
            "free_freight_threshold_cents": 100000,
        })
    product, _lot = create_stocked_product(
        lot_qty=200,
        product_overrides={"manufacturer_code": "ACME-VET",
                           "product_type": "CONSUMABLE",
                           "unit_price_cents": 10000})
    return clinic, program, enrollment, product


def _approve_two_orders(api, clinic_id, product_id):
    """O1 qty 50 and O2 qty 60 on consecutive days, both approved.
    Net per unit 10000c with 0% discount -> O1 net 500000, O2 net 600000."""
    order1 = create_approved_order(
        clinic_id, product_id, 50,
        window_start="2026-08-05T13:00:00Z", window_end="2026-08-05T15:00:00Z")
    order2 = create_approved_order(
        clinic_id, product_id, 60,
        window_start="2026-08-06T13:00:00Z", window_end="2026-08-06T15:00:00Z")
    return order1, order2


class TestRebateProvisionalVsFinal:
    def test_rebate_provisional_amounts_locked_at_approval(self, api):
        """PRD §3.8: "The rate is chosen by the enrollment's
        `qtd_qualifying_cents` before this order is counted: when that running
        total has already reached the program's `bonus_threshold_cents`, the
        `rebate_bonus_rate_bp` applies, otherwise the `rebate_base_rate_bp`;
        equality earns the bonus."
        PRD §3.8: "A RebateAccrual's `final_amount_cents` stays null until
        finalization..."

        Design: Difficulty/dual_variant_calc/rebate_provisional_vs_final_quarter_close
        """
        clinic, _program, enrollment, product = _setup_rebate_clinic(
            api, "Clinic R", "LIC-R1", "1 Clinic Way")
        order1, order2 = _approve_two_orders(api, clinic["id"], product["id"])
        ship_and_deliver(order1["id"])
        ship_and_deliver(order2["id"])

        acc1 = sole_accrual_for_order(order1["id"])
        acc2 = sole_accrual_for_order(order2["id"])
        assert_rebate_accrual(acc1)
        assert_rebate_accrual(acc2)
        # QTD-before O1 is 0 -> base 200bp: 500000 * 200/10000 = 10000.
        assert acc1["provisional_amount_cents"] == 10000
        # QTD-before O2 is 500000 < 1000000 -> base again: 12000.
        assert acc2["provisional_amount_cents"] == 12000
        assert acc1["status"] == "PROVISIONAL"
        assert acc2["status"] == "PROVISIONAL"
        assert acc1["final_amount_cents"] is None
        assert acc2["final_amount_cents"] is None

    def test_rebate_final_amounts_recomputed_retroactively_at_close(self, api):
        """PRD §3.8: "Closing computes, for every enrollment of the program, a
        final quarter-to-date figure over `DELIVERED` orders only, picks a
        single retroactive rate by comparing that final figure to
        `bonus_threshold_cents` — equality earns the bonus — and re-evaluates
        every `PROVISIONAL` accrual: an accrual whose order is `DELIVERED` moves
        to `FINALIZED` with its `final_amount_cents` set to the sum over that
        delivered order's qualifying lines of each net line amount multiplied by
        the final rate and divided by ten thousand, rounded half up per line..."
        PRD §3.8: "Every `ACTIVE` enrollment of the program moves to
        `FINALIZED`."
        PRD §3.8: "identical order data can yield different provisional and
        final amounts whenever the quarter crosses the bonus threshold..."

        Design: Difficulty/dual_variant_calc/rebate_provisional_vs_final_quarter_close
        """
        clinic, program, enrollment, product = _setup_rebate_clinic(
            api, "Clinic RC", "LIC-RC", "1 Clinic Way")
        order1, order2 = _approve_two_orders(api, clinic["id"], product["id"])
        ship_and_deliver(order1["id"])
        ship_and_deliver(order2["id"])

        get_success_data(api.close_bundle_program(program["id"], ACCOUNT_MANAGER))

        acc1 = get_accrual(sole_accrual_for_order(order1["id"])["id"])
        acc2 = get_accrual(sole_accrual_for_order(order2["id"])["id"])
        # Final QTD over DELIVERED orders = 1100000 >= 1000000 -> retroactive
        # 500bp: O1 500000 * 500/10000 = 25000; O2 600000 * 500/10000 = 30000.
        assert acc1["status"] == "FINALIZED"
        assert acc1["final_amount_cents"] == 25000
        assert acc2["status"] == "FINALIZED"
        assert acc2["final_amount_cents"] == 30000
        assert acc1["final_amount_cents"] != acc1["provisional_amount_cents"]
        assert acc2["final_amount_cents"] != acc2["provisional_amount_cents"]

        assert get_enrollment(enrollment["id"])["status"] == "FINALIZED"


class TestRebateTierLockedByQtdBefore:
    def test_rebate_tier_locked_by_qtd_before_order(self, api):
        """PRD §3.8: "The rate is chosen by the enrollment's
        `qtd_qualifying_cents` before this order is counted: when that running
        total has already reached the program's `bonus_threshold_cents`, the
        `rebate_bonus_rate_bp` applies, otherwise the `rebate_base_rate_bp`;
        equality earns the bonus."
        PRD §3.8: "The provisional tier is thus non-cumulative — each order's
        rate was locked by the running total before it..."

        Design: Difficulty/combinatorial_formula/rebate_tier_locked_by_qtd_before
        """
        clinic, _program, _enrollment, product = _setup_rebate_clinic(
            api, "Clinic T", "LIC-T1", "3 Barn Rd")
        order1, order2 = _approve_two_orders(api, clinic["id"], product["id"])

        # O2 CROSSES the 1000000 threshold (500000 + 600000) yet accrues at
        # the 200bp base rate because the tier is locked to QTD-before.
        acc2 = sole_accrual_for_order(order2["id"])
        assert acc2["provisional_amount_cents"] == 12000, (
            "600000 * 200/10000 — base rate locked by QTD-before 500000, "
            "NOT the 500bp bonus a cumulative misreading would yield")

    def test_rebate_qtd_accumulates_after_each_approval(self, api):
        """PRD §3.8: "The enrollment's `qtd_qualifying_cents` — the sum of net
        qualifying line amounts over the clinic's orders tagged to this
        enrollment in `APPROVED`, `BACKORDERED`, `SHIPPED`, or `DELIVERED`
        status — is then increased by this order's net qualifying amounts."

        Design: Difficulty/combinatorial_formula/rebate_tier_locked_by_qtd_before
        """
        clinic, _program, enrollment, product = _setup_rebate_clinic(
            api, "Clinic T2", "LIC-T2", "3 Barn Rd")
        order1, order2 = _approve_two_orders(api, clinic["id"], product["id"])

        acc1 = sole_accrual_for_order(order1["id"])
        assert acc1["provisional_amount_cents"] == 10000, (
            "QTD-before O1 is 0 -> base rate: 500000 * 200/10000")
        enr = get_enrollment(enrollment["id"])
        assert_bundle_enrollment(enr)
        assert enr["qtd_qualifying_cents"] == 1100000, (
            "500000 + 600000 — the threshold is crossed only after O2's rate "
            "has already locked")


class TestRebateInputSetFiltering:
    def test_rebate_input_set_excludes_non_qualifying_lines(self, api):
        """PRD §3.8: "...the order's qualifying lines — those whose product
        matches the program's `manufacturer_code` and whose `product_type` lies
        within the program's `qualifying_product_types`..."
        PRD §3.8: "The accrual's `provisional_amount_cents` is then the sum over
        the order's qualifying lines of each net line amount multiplied by the
        chosen rate in basis points and divided by ten thousand, rounded half up
        per line before summation."

        Design: Corner/calculations/rebate_input_set_excludes_non_qualifying_lines
        """
        clinic, _program, enrollment, _p = _setup_rebate_clinic(
            api, "Clinic ISF", "LIC-ISF", "42 Filter Ford")
        p_acme = create_product(sku="CONS-ISF1", product_name="ACME Wrap",
                                manufacturer_code="ACME-VET",
                                product_type="CONSUMABLE", unit_price_cents=10000)
        p_other = create_product(sku="CONS-ISF2", product_name="Other Wrap",
                                 manufacturer_code="OTHER",
                                 product_type="CONSUMABLE", unit_price_cents=2500)
        create_lot(p_acme["id"], qty_on_hand=50)
        create_lot(p_other["id"], qty_on_hand=50)

        order = create_order(
            clinic["id"],
            [order_line_spec(p_acme["id"], 10), order_line_spec(p_other["id"], 20)],
            window_start="2026-08-03T13:00:00Z",
            window_end="2026-08-03T15:00:00Z")
        submit_order(order["id"], clinic["id"])
        approve_order(order["id"])

        accrual = sole_accrual_for_order(order["id"])
        # Only the ACME line qualifies: 100000 * 200/10000 = 2000.
        assert accrual["provisional_amount_cents"] == 2000
        enr = get_enrollment(enrollment["id"])
        assert enr["qtd_qualifying_cents"] == 100000, (
            "The OTHER-manufacturer line's 50000c contributes nothing to QTD")


class TestRebateReversalInvariant:
    def _setup_approved_rebate_order(self, api):
        clinic, _program, enrollment, product = _setup_rebate_clinic(
            api, "Clinic I2", "LIC-I2", "20 Colt Cir")
        order = create_approved_order(
            clinic["id"], product["id"], 10,
            window_start="2026-08-03T13:00:00Z",
            window_end="2026-08-03T15:00:00Z")
        accrual = sole_accrual_for_order(order["id"])
        return clinic, enrollment, order, accrual

    def test_rebate_accrual_reversed_on_order_cancel(self, api):
        """PRD §3.6: "...its `PROVISIONAL` RebateAccruals move to `REVERSED` and
        the enrollment's `qtd_qualifying_cents` is decremented accordingly..."
        PRD §3.8: "...a `PROVISIONAL` accrual reverses on exactly three events:
        its order is cancelled, its enrollment is superseded, or its program
        closes with the order undelivered."

        Design: Difficulty/compensating_invariant/rebate_accrual_reversal_invariant
        """
        _clinic, enrollment, order, accrual = self._setup_approved_rebate_order(api)
        # 100000 net at 200bp base -> 2000 provisional.
        assert accrual["status"] == "PROVISIONAL"
        assert accrual["provisional_amount_cents"] == 2000

        get_success_data(api.cancel_order(order["id"], ACCOUNT_MANAGER))

        after = get_accrual(accrual["id"])
        assert after["status"] == "REVERSED"
        assert get_enrollment(enrollment["id"])["qtd_qualifying_cents"] == 0

    def test_rebate_qtd_conserved_after_approve_cancel_pair(self, api):
        """PRD §3.6: "...its `PROVISIONAL` RebateAccruals move to `REVERSED` and
        the enrollment's `qtd_qualifying_cents` is decremented accordingly..."
        PRD §3.8: "The enrollment's `qtd_qualifying_cents` — the sum of net
        qualifying line amounts over the clinic's orders tagged to this
        enrollment in `APPROVED`, `BACKORDERED`, `SHIPPED`, or `DELIVERED`
        status — is then increased by this order's net qualifying amounts."

        Design: Difficulty/compensating_invariant/rebate_accrual_reversal_invariant
        """
        _clinic, enrollment, order, accrual = self._setup_approved_rebate_order(api)
        enr_mid = get_enrollment(enrollment["id"])
        assert enr_mid["qtd_qualifying_cents"] == 100000, (
            "The approval added the order's net qualifying amount")

        get_success_data(api.cancel_order(order["id"], ACCOUNT_MANAGER))

        enr_end = get_enrollment(enrollment["id"])
        assert enr_end["qtd_qualifying_cents"] == 0, (
            "100000 accrued then reversed — the payable surface is conserved")

        live = [a for a in accruals_for_order(order["id"])
                if a["status"] in ("PROVISIONAL", "FINALIZED")]
        assert sum(a["provisional_amount_cents"] for a in live) == 0, (
            "No live accrual amount may survive the cancel")


class TestEnrollmentGates:
    def test_enrollment_requires_active_program(self, api):
        """PRD §3.8: "Enrollment requires the clinic `ACTIVE`
        (`ERR_CLINIC_NOT_ACTIVE`) and the program `ACTIVE`
        (`ERR_PROGRAM_NOT_ACTIVE`)..."

        Design: Corner/validations/enrollment_requires_active_program
        """
        clinic = create_active_clinic(clinic_name="Clinic EP",
                                      license_number="LIC-EP")
        program = create_bundle_program(program_name="Draft Prog",
                                        manufacturer_code="GEN")
        assert program["status"] == "DRAFT"

        fresh_version = get_clinic(clinic["id"])["version"]
        resp = api.create_bundle_enrollment(
            clinic["id"],
            {"program_id": program["id"], "quarter": "2026-Q3",
             "expected_clinic_version": fresh_version},
            make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)

    def test_enrollment_supersede_requires_fresh_version(self, api):
        """PRD §2.7: "If the clinic's current `version` differs from
        `expected_clinic_version` — because another writer has advanced the
        record since the client read it — the request is rejected with
        `ERR_STALE_CLINIC_VERSION` (HTTP 412), and the client must re-read the
        clinic before re-applying its change."
        PRD §3.8: "Only one enrollment per clinic and quarter may be live:
        creating a new BundleEnrollment for a clinic and quarter that already
        has an `ACTIVE` one moves the prior enrollment to `SUPERSEDED` and
        reverses its `PROVISIONAL` accruals — each such RebateAccrual moves to
        `REVERSED`. The new enrollment starts `ACTIVE` with
        `qtd_qualifying_cents` at zero."

        Design: Corner/cross_cutting_complexity_layers/enrollment_supersede_requires_fresh_version
        """
        clinic = create_active_clinic(clinic_name="Clinic OCC2",
                                      license_number="LIC-OC2")
        stale_version = clinic["version"]  # version 2 after activation
        p1 = create_active_program(program_name="P1", manufacturer_code="GEN")
        p2 = create_active_program(program_name="P2", manufacturer_code="GEN",
                                   bundle_discount_pct=5,
                                   rebate_base_rate_bp=150,
                                   rebate_bonus_rate_bp=300)

        e1 = enroll_clinic(clinic["id"], p1["id"])
        assert e1["status"] == "ACTIVE"
        # E1's creation bumped the clinic's version, so replaying the pre-E1
        # version is stale.
        resp = api.create_bundle_enrollment(
            clinic["id"],
            {"program_id": p2["id"], "quarter": "2026-Q3",
             "expected_clinic_version": stale_version},
            make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_CLINIC_VERSION)

        # Re-based on the fresh version, the enrollment succeeds and supersedes.
        fresh_version = get_clinic(clinic["id"])["version"]
        e2 = validate_success(api.create_bundle_enrollment(
            clinic["id"],
            {"program_id": p2["id"], "quarter": "2026-Q3",
             "expected_clinic_version": fresh_version},
            make_clinic_buyer_headers(clinic["id"])), 201)
        assert e2["status"] == "ACTIVE"
        assert e2["qtd_qualifying_cents"] == 0
        assert get_enrollment(e1["id"])["status"] == "SUPERSEDED"


class TestProgramLifecycle:
    def test_program_close_terminal_lockdown(self, api):
        """PRD §3.8: "A program starts `DRAFT`, moves to `ACTIVE` on activation,
        and to terminal `CLOSED` on close; activation or close from the wrong
        state fails with `ERR_PROGRAM_INVALID_STATE`."

        Design: Corner/state_machines/program_close_terminal_lockdown
        """
        program = create_active_program(program_name="Close Test",
                                        manufacturer_code="GEN",
                                        rebate_base_rate_bp=100,
                                        rebate_bonus_rate_bp=200,
                                        bonus_threshold_cents=500000)
        closed = get_success_data(
            api.close_bundle_program(program["id"], ACCOUNT_MANAGER))
        assert closed["status"] == "CLOSED"

        resp = api.close_bundle_program(program["id"], ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_INVALID_STATE)
        assert get_success_data(api.get_bundle_program(
            program["id"], ACCOUNT_MANAGER))["status"] == "CLOSED"


class TestClinicPatchOcc:
    def test_clinic_patch_stale_version_rejected(self, api):
        """PRD §2.7: "Two write operations guard the Clinic aggregate with
        optimistic concurrency control: the clinic commercial-terms update
        (`PATCH /vet/clinics/{id}`) and the bundle-enrollment creation (`POST
        /vet/clinics/{clinicId}/bundle-enrollments`). ... If the clinic's
        current `version` differs from `expected_clinic_version` — because
        another writer has advanced the record since the client read it — the
        request is rejected with `ERR_STALE_CLINIC_VERSION` (HTTP 412), and the
        client must re-read the clinic before re-applying its change. A
        successful guarded update or enrollment creation increments the Clinic's
        `version` by one."

        Design: Corner/cross_cutting_complexity_layers/clinic_patch_stale_version_rejected
        """
        clinic = create_clinic(clinic_name="Clinic OCC", license_number="LIC-OCC")
        observed_version = clinic["version"]  # 1 at creation

        first = validate_success(api.patch_clinic(
            clinic["id"],
            {"expected_clinic_version": observed_version,
             "credit_limit_cents": 2000000},
            ACCOUNT_MANAGER))
        assert first["version"] == observed_version + 1
        assert first["credit_limit_cents"] == 2000000

        # Replaying the same stale version is rejected and mutates nothing.
        resp = api.patch_clinic(
            clinic["id"],
            {"expected_clinic_version": observed_version,
             "credit_limit_cents": 3000000},
            ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_STALE_CLINIC_VERSION)

        after = get_clinic(clinic["id"])
        assert after["credit_limit_cents"] == 2000000
        assert after["version"] == observed_version + 1
