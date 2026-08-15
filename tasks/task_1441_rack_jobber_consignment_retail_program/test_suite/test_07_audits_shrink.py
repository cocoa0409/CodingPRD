"""Shrink audits: lifecycle gates, segregation of duties, OCC on certify, the
unit-side freeze (variance/allowance/chargeable), valuation variants, and the
certify -> balance -> ratio -> suspension -> visit-cancellation cascade."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    audit_counted_line,
    certify_audit,
    create_price_directive_payload,
    get_agreement,
    get_audit,
    get_balance,
    get_visit,
    list_balances,
    make_field_auditor_headers,
    make_jobber_admin_headers,
    make_retailer_manager_headers,
    new_active_agreement,
    new_audit,
    new_price_directive,
    new_product,
    new_program,
    new_route,
    new_service_visit,
    new_store,
    post_matched_sale,
    run_restock_visit,
    set_clock,
    setup_shop,
    setup_stocked_shop,
    setup_submitted_audit,
    start_audit,
    submit_audit,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["jobber_admin_headers"]
AUDITOR = TEST_USERS["field_auditor_headers"]


class TestAuditLifecycleGates:
    def test_submit_before_start_rejected(self, api):
        """PRD section 3.7: "The audit is born `SCHEDULED`. A `FieldAuditor`
        starts it — `SCHEDULED` to `IN_PROGRESS`, requiring an `ACTIVE`
        agreement (`ERR_AGREEMENT_NOT_ACTIVE` otherwise) — and later submits it
        with a `counted_lines` payload of `product_id` and `counted_units`
        pairs."
        PRD section 2.8: "From-state validity: the target resource must be in a
        state from which the requested transition exists, failing with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/audit_submit_before_start_rejected
        """
        ctx = setup_shop(with_product=False)
        audit = new_audit(ctx["agreement"]["id"])
        res = api.submit_audit_count(audit["id"], {"counted_lines": []},
                                     AUDITOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_audit(audit["id"])["status"] == "SCHEDULED"

    def test_certify_before_submit_rejected(self, api):
        """PRD section 3.7: "Certification moves `SUBMITTED` to `CERTIFIED`,
        stamps `certified_at` and `certified_by_user_id`, and prices the
        variance."
        PRD section 2.8: "From-state validity: the target resource must be in a
        state from which the requested transition exists, failing with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/validations/audit_certify_before_submit_rejected
        """
        ctx = setup_shop(with_product=False)
        audit = new_audit(ctx["agreement"]["id"])
        start_audit(audit["id"])
        fresh = get_audit(audit["id"])
        res = api.certify_audit_count(
            audit["id"], {"expected_audit_count_version": fresh["version"]},
            make_jobber_admin_headers("admin-1"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_audit(audit["id"])["status"] == "IN_PROGRESS"


class TestAuditRbacAndSod:
    def test_field_auditor_cannot_certify(self, api):
        """PRD section 2.9: "The role assignments themselves enforce the first
        half of the separation: a `FieldAuditor` can start and submit audits
        but holds no certification right anywhere in the API, and a
        `JobberFinance` operator can generate, finalize, revise, and pay
        statements but holds no approval right."
        PRD section 4: POST /audit-counts/{id}/certify lists JobberAdmin as its
        only authorized role.

        Design: Corner/rbac/rbac_field_auditor_cannot_certify_audit
        """
        ctx = setup_shop(with_product=False)
        audit = setup_submitted_audit(ctx["agreement"]["id"], [])
        res = api.certify_audit_count(
            audit["id"],
            {"expected_audit_count_version": audit["version"]},
            make_field_auditor_headers("aud-2"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_audit(audit["id"])["status"] == "SUBMITTED"

    def test_certifier_cannot_be_counter(self, api):
        """PRD section 2.9: "An audit count records the auditor who submitted
        it as `counted_by_user_id`; certification must come from a
        `JobberAdmin` whose `X-User-ID` differs from `counted_by_user_id`,
        failing with `ERR_SOD_CERTIFIER_IS_COUNTER` (HTTP 403)."

        Design: Corner/rbac/sod_certifier_cannot_be_counter
        """
        ctx = setup_shop(with_product=False)
        audit = setup_submitted_audit(ctx["agreement"]["id"], [],
                                      auditor_id="aud-7")
        res = api.certify_audit_count(
            audit["id"],
            {"expected_audit_count_version": audit["version"]},
            make_jobber_admin_headers("aud-7"))
        validate_error(res, ApiErrorId.ERR_SOD_CERTIFIER_IS_COUNTER)
        assert get_audit(audit["id"])["status"] == "SUBMITTED"


class TestAuditCertifyOcc:
    def test_stale_version_after_recount_cycle_rejected(self, api):
        """PRD section 3.7: "The certifying `JobberAdmin` must carry
        `expected_audit_count_version` equal to the audit's current `version` —
        a stale value means a dispute-and-recount cycle replaced the frozen
        counts since the certifier last read them, and the request is rejected
        with `ERR_STALE_VERSION`".

        Design: Corner/cross_cutting_complexity/occ_audit_certify_stale_rejected
        """
        ctx = setup_shop(with_product=False)
        audit = new_audit(ctx["agreement"]["id"])
        start_audit(audit["id"], "aud-1")
        submitted = submit_audit(audit["id"], [], "aud-1")
        stale_version = submitted["version"]
        validate_success(api.dispute_audit_count(
            audit["id"], {"reason": "recount requested"},
            make_retailer_manager_headers(ctx["store"]["id"])), 200)
        validate_success(api.order_recount_audit_count(audit["id"], ADMIN),
                         200)
        resubmitted = submit_audit(audit["id"], [], "aud-1")
        assert resubmitted["version"] > stale_version, (
            "the dispute/recount/resubmit loop advanced the audit version")
        res = api.certify_audit_count(
            audit["id"], {"expected_audit_count_version": stale_version},
            make_jobber_admin_headers("admin-1"))
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        after = get_audit(audit["id"])
        assert after["status"] == "SUBMITTED"
        assert list_balances(ctx["agreement"]["id"]) == [], (
            "no shrink is posted to any InventoryBalance")


class TestShrinkUnitFreeze:
    def test_free_allowance_rounds_half_up(self, api):
        """PRD section 3.7: "`free_allowance_units` is
        `scanned_units_since_last_audit` multiplied by the agreement's
        `free_allowance_pct`, rounded half-up to a whole unit — ordinary
        handling loss the jobber forgives. `chargeable_units` is the variance
        minus the free allowance, floored at zero."

        Design: Corner/calculations/free_allowance_rounding_half_up
        """
        ctx = setup_stocked_shop(restock_units=60)
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 50, "2026-08-01T10:00:00Z",
                          client_event_id="al-1")
        set_clock("2026-08-02T00:00:00Z")
        audit = setup_submitted_audit(
            ctx["agreement"]["id"],
            [audit_counted_line(ctx["product"]["id"], 9)])
        assert audit["scanned_units_since_last_audit"] == 50
        assert audit["free_allowance_units"] == 1, "round_half_up(50 * 0.01) "
        "rounds 0.5 up"
        assert audit["variance_units"] == 1, "book 10 minus counted 9"
        assert audit["chargeable_units"] == 0
        certified = certify_audit(audit["id"])
        assert certified["retailer_charge_cents"] == 0
        agreement = get_agreement(ctx["agreement"]["id"])
        assert agreement["status"] == "ACTIVE", (
            "cumulative ratio 1/60 is below the 0.02 suspension threshold")
        assert agreement["cumulative_shrink_ratio"] == pytest.approx(1 / 60)

    def test_overstock_negative_variance_no_charge(self, api):
        """PRD section 3.7: "`variance_units` is the sum over counted lines of
        book on-hand at submit minus counted units, so a positive value is
        shrink; products absent from `counted_lines` are never varianced."
        PRD section 3.7: "`chargeable_units` is the variance minus the free
        allowance, floored at zero."
        PRD section 3.7: "each counted line rewrites its inventory balance:
        `on_hand_units` is set to the counted figure and
        `lifetime_shrink_units` grows by the book-minus-counted difference,
        floored at zero."

        Design: Corner/calculations/overstock_negative_variance_no_charge
        """
        ctx = setup_stocked_shop(restock_units=50)
        audit = setup_submitted_audit(
            ctx["agreement"]["id"],
            [audit_counted_line(ctx["product"]["id"], 55)])
        assert audit["variance_units"] == -5, "overstock: counted above book"
        assert audit["chargeable_units"] == 0
        certified = certify_audit(audit["id"])
        assert certified["retailer_charge_cents"] == 0
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["on_hand_units"] == 55, (
            "the book resets to the physical count, including upward")


class TestAuditValuationVariants:
    def _two_mode_scenario(self, api):
        """One program, two stores, two ACTIVE agreements differing only in
        shrink_valuation_mode; identical restock 100 and audit counted 90."""
        set_clock()
        program = new_program(name="HomeEssentials")
        store1 = new_store(name="Store North", store_code="STN",
                           total_facings=80)
        store2 = new_store(name="Store South", store_code="STS",
                           total_facings=80)
        agr1 = new_active_agreement(
            program["id"], store1["id"], shrink_suspend_ratio=0.5,
            restock_value_cap_cents=50000,
            shrink_valuation_mode="JOBBER_COST")
        agr2 = new_active_agreement(
            program["id"], store2["id"], shrink_suspend_ratio=0.5,
            restock_value_cap_cents=50000,
            shrink_valuation_mode="BLENDED_RETAIL")
        product = new_product(program["id"], sku="MOP-001", name="Spray Mop",
                              jobber_cost_cents=100, min_retail_cents=150,
                              units_per_facing=10)
        route = new_route(program["id"])
        for agr, store in ((agr1, store1), (agr2, store2)):
            new_price_directive(agr["id"], product["id"], price_cents=200)
            run_restock_visit(route["id"], agr["id"], store["id"],
                              product["id"], 100)
        audit1 = setup_submitted_audit(
            agr1["id"], [audit_counted_line(product["id"], 90)])
        audit2 = setup_submitted_audit(
            agr2["id"], [audit_counted_line(product["id"], 90)])
        return agr1, agr2, audit1, audit2

    def test_jobber_cost_variant_valuation(self, api):
        """PRD section 3.7: "The valuation variant is selected by the
        agreement's `shrink_valuation_mode`: under `JOBBER_COST`,
        `valuation_unit_cents` is simply the product's `jobber_cost_cents`;
        under `BLENDED_RETAIL`, it is sixty percent of the jobber cost plus
        forty percent of the effective directive price for the agreement and
        product at certify time, rounded half-up to a whole cent — strictly
        higher whenever retail exceeds cost, so a cost of 100 cents with a
        directive price of 200 cents values at 100 under one variant and 140
        under the other."

        Design: Difficulty/dual_variant_calc/audit_valuation_jobber_cost_vs_blended_retail
        """
        _, _, audit1, _ = self._two_mode_scenario(api)
        certified = certify_audit(audit1["id"])
        assert certified["valuation_unit_cents"] == 100
        assert certified["variance_value_cents"] == 1000, (
            "chargeable 10 * cost 100")
        assert certified["retailer_charge_cents"] == 500, (
            "round_half_up(1000 * 0.5)")

    def test_blended_retail_variant_valuation(self, api):
        """PRD section 3.7: "The valuation variant is selected by the
        agreement's `shrink_valuation_mode`: under `JOBBER_COST`,
        `valuation_unit_cents` is simply the product's `jobber_cost_cents`;
        under `BLENDED_RETAIL`, it is sixty percent of the jobber cost plus
        forty percent of the effective directive price for the agreement and
        product at certify time, rounded half-up to a whole cent — strictly
        higher whenever retail exceeds cost, so a cost of 100 cents with a
        directive price of 200 cents values at 100 under one variant and 140
        under the other."
        PRD section 3.7: "`variance_value_cents` is `chargeable_units`
        multiplied by `valuation_unit_cents`, and `retailer_charge_cents` is
        that value multiplied by the agreement's `shrink_retailer_share_pct`,
        rounded half-up; the jobber absorbs the remainder."

        Design: Difficulty/dual_variant_calc/audit_valuation_jobber_cost_vs_blended_retail
        """
        _, _, audit1, audit2 = self._two_mode_scenario(api)
        certified1 = certify_audit(audit1["id"])
        certified2 = certify_audit(audit2["id"])
        assert certified2["valuation_unit_cents"] == 140, (
            "round_half_up(0.6 * 100 + 0.4 * 200)")
        assert certified2["variance_value_cents"] == 1400
        assert certified2["retailer_charge_cents"] == 700
        assert certified1["retailer_charge_cents"] == 500
        assert certified1["retailer_charge_cents"] != \
            certified2["retailer_charge_cents"], (
            "identical counts, different valuation variants")


class TestShrinkSuspensionBoundary:
    def _ratio_scenario(self, api, counted_units, store_name, store_code):
        """ACTIVE agreement with 1000 confirmed restock units and a submitted
        audit counting `counted_units` (zero scans, so free allowance is 0)."""
        set_clock()
        program = new_program(name="RatioTest")
        product = new_product(program["id"], sku="CHIP-100",
                              name="Potato Chips")
        route = new_route(program["id"])
        store = new_store(name=store_name, store_code=store_code,
                          total_facings=120)
        agreement = new_active_agreement(
            program["id"], store["id"], restock_value_cap_cents=150000)
        new_price_directive(agreement["id"], product["id"], price_cents=200)
        run_restock_visit(route["id"], agreement["id"], store["id"],
                          product["id"], 1000)
        audit = setup_submitted_audit(
            agreement["id"], [audit_counted_line(product["id"], counted_units)])
        return agreement, audit

    def test_ratio_exactly_at_threshold_suspends(self, api):
        """PRD section 3.7: "Third, the suspension posture evaluates: when an
        `ACTIVE` agreement's recomputed ratio meets or exceeds its
        `shrink_suspend_ratio` — exactly equal suspends — the agreement moves
        from `ACTIVE` to `SUSPENDED`, which in turn cancels every
        still-`SCHEDULED` service visit."

        Design: Difficulty/boundary_precision_check/shrink_ratio_exact_threshold_suspends
        """
        agreement, audit = self._ratio_scenario(api, 980, "Store D1", "SD1")
        certified = certify_audit(audit["id"])
        assert certified["chargeable_units"] == 20
        after = get_agreement(agreement["id"])
        assert after["cumulative_shrink_units"] == 20
        assert after["cumulative_shrink_ratio"] == pytest.approx(0.02)
        assert after["status"] == "SUSPENDED", (
            "20/1000 == 0.02 meets the threshold exactly; >= applies")

    def test_ratio_one_unit_below_threshold_stays_active(self, api):
        """PRD section 3.7: "Third, the suspension posture evaluates: when an
        `ACTIVE` agreement's recomputed ratio meets or exceeds its
        `shrink_suspend_ratio` — exactly equal suspends — the agreement moves
        from `ACTIVE` to `SUSPENDED`, which in turn cancels every
        still-`SCHEDULED` service visit."
        PRD section 3.1: "`cumulative_shrink_ratio`, the shrink units divided
        by the delivered units, defined as 0.0 while nothing has been
        delivered."

        Design: Difficulty/boundary_precision_check/shrink_ratio_exact_threshold_suspends
        """
        agreement, audit = self._ratio_scenario(api, 981, "Store D2", "SD2")
        certified = certify_audit(audit["id"])
        assert certified["chargeable_units"] == 19
        after = get_agreement(agreement["id"])
        assert after["cumulative_shrink_units"] == 19
        assert after["cumulative_shrink_ratio"] == pytest.approx(0.019)
        assert after["status"] == "ACTIVE", (
            "19/1000 is one unit of shrink below the threshold")


class TestCertifyCascade:
    def _cascade_scenario(self, api):
        ctx = setup_stocked_shop(restock_units=1000, with_route=True,
                                 agreement_overrides={
                                     "restock_value_cap_cents": 150000})
        future_visit = new_service_visit(
            ctx["route"]["id"], ctx["agreement"]["id"],
            scheduled_date="2026-08-02")
        audit = setup_submitted_audit(
            ctx["agreement"]["id"],
            [audit_counted_line(ctx["product"]["id"], 980)])
        return ctx, future_visit, audit

    def test_certify_posts_shrink_and_suspends(self, api):
        """PRD section 3.7: "Certification then cascades, atomically. First,
        each counted line rewrites its inventory balance: `on_hand_units` is
        set to the counted figure and `lifetime_shrink_units` grows by the
        book-minus-counted difference, floored at zero. Second, the agreement
        accumulates: `cumulative_shrink_units` grows by the audit's
        `variance_units`, floored at zero, `cumulative_shrink_ratio` is
        recomputed, and the agreement's `version` advances. Third, the
        suspension posture evaluates: when an `ACTIVE` agreement's recomputed
        ratio meets or exceeds its `shrink_suspend_ratio` — exactly equal
        suspends — the agreement moves from `ACTIVE` to `SUSPENDED`, which in
        turn cancels every still-`SCHEDULED` service visit."

        Design: Difficulty/transitive_cascade/audit_certify_shrink_suspension_cascade
        """
        ctx, _, audit = self._cascade_scenario(api)
        certified = certify_audit(audit["id"])
        assert certified["retailer_charge_cents"] == 1000, (
            "chargeable 20 * 100 * 0.5")
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["on_hand_units"] == 980, "link 1: balance posted"
        assert balance["lifetime_shrink_units"] == 20
        agreement = get_agreement(ctx["agreement"]["id"])
        assert agreement["cumulative_shrink_units"] == 20, (
            "link 2: ratio recomputed from the posting")
        assert agreement["cumulative_shrink_ratio"] == pytest.approx(0.02)
        assert agreement["status"] == "SUSPENDED", (
            "link 3: 0.02 >= 0.02 threshold breach")

    def test_suspension_cancels_visits_and_gates_directives(self, api):
        """PRD section 3.7: "when an `ACTIVE` agreement's recomputed ratio
        meets or exceeds its `shrink_suspend_ratio` — exactly equal suspends —
        the agreement moves from `ACTIVE` to `SUSPENDED`, which in turn cancels
        every still-`SCHEDULED` service visit."
        PRD section 3.2: "Beyond concurrency, creation requires the agreement
        to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise), the product to
        belong to the agreement's program (`ERR_PRODUCT_NOT_IN_PROGRAM`
        otherwise), the product to still be `ACTIVE`
        (`ERR_PRODUCT_DISCONTINUED` otherwise), and the price to meet or exceed
        the product's `min_retail_cents` (`ERR_PRICE_BELOW_FLOOR` otherwise)."

        Design: Difficulty/transitive_cascade/audit_certify_shrink_suspension_cascade
        """
        ctx, future_visit, audit = self._cascade_scenario(api)
        certify_audit(audit["id"])
        assert get_visit(future_visit["id"])["status"] == "CANCELLED", (
            "link 4: suspension cancels SCHEDULED visits")
        fresh_version = get_agreement(ctx["agreement"]["id"])["version"]
        res = api.create_price_directive(
            create_price_directive_payload(
                ctx["agreement"]["id"], ctx["product"]["id"], fresh_version,
                price_cents=210, effective_from="2026-08-01T12:00:00Z"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
