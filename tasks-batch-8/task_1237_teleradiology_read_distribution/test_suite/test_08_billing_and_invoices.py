"""Billing periods and invoice generation: volume-pricing variants, tier
boundaries, pinned rounding order, penalty cap/floor, OCC, and supersede."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_assignment,
    assign_study,
    create_active_hospital,
    create_billing_period_payload,
    create_draft_report,
    create_routing_policy,
    create_routing_policy_payload,
    create_routed_study,
    generate_invoice,
    get_success_data,
    make_hospital_user_headers,
    make_radiologist_headers,
    seed_studies,
    setup_assignment_ready,
    setup_billing_period,
    setup_credentialed_radiologist,
    setup_invoiced_period,
    sign_report,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCH = TEST_USERS["dispatch_headers"]


class TestPricingVariants:
    def _make_pair(self, api):
        hosp_a = create_active_hospital(name="Hosp Marginal", state_code="CA")
        hosp_b = create_active_hospital(name="Hosp Flat", state_code="TX",
                                        pricing_mode="FLAT_TIER")
        for hosp in (hosp_a, hosp_b):
            seed_studies(hosp["id"], 1200, "2026-05-04T10:00:00Z",
                         "2026-05-04T12:00:00Z")
        per_a = setup_billing_period(hosp_a["id"])
        inv_a = generate_invoice(per_a["id"])
        per_b = setup_billing_period(hosp_b["id"])
        inv_b = generate_invoice(per_b["id"])
        return inv_a, inv_b

    def test_marginal_variant_bills_each_unit_at_its_own_tier(self, api):
        """PRD section 3.9: "Volume pricing uses three tiers. Units 1 through
        1000 bill at 901 cents each, units 1001 through 5000 at 801 cents, and
        units 5001 and beyond at 701 cents. The two pricing variants diverge
        here: under `MARGINAL`, each unit is billed at the rate of the tier
        containing its own index; under `FLAT_TIER`, every unit is billed at the
        single rate of the highest tier reached by `billable_study_count`, so
        identical volume yields a different total under the two variants."
        PRD section 3.9: "Generation pins the hospital's current `pricing_mode`
        into the invoice's `pricing_mode_snapshot` at generation time..."

        Design: Difficulty/dual_variant_calc/invoice_pricing_marginal_vs_flat_tier
        """
        inv_a, _inv_b = self._make_pair(api)
        assert inv_a["pricing_mode_snapshot"] == "MARGINAL"
        assert inv_a["billable_study_count"] == 1200
        # 1000*901 + 200*801 = 1061200; no penalties, no add-ons.
        assert inv_a["gross_cents"] == 1061200
        assert inv_a["total_cents"] == 1061200

    def test_flat_tier_variant_bills_all_units_at_highest_tier(self, api):
        """PRD section 3.9: "...under `FLAT_TIER`, every unit is billed at the
        single rate of the highest tier reached by `billable_study_count`, so
        identical volume yields a different total under the two variants."

        Design: Difficulty/dual_variant_calc/invoice_pricing_marginal_vs_flat_tier
        """
        _inv_a, inv_b = self._make_pair(api)
        assert inv_b["pricing_mode_snapshot"] == "FLAT_TIER"
        assert inv_b["billable_study_count"] == 1200
        # All 1200 units at the tier-2 rate: 1200*801 = 961200.
        assert inv_b["gross_cents"] == 961200
        assert inv_b["total_cents"] == 961200


class TestTierStraddleCombination:
    def _make_combo_invoice(self, api):
        hosp = create_active_hospital(name="Hosp Combo", state_code="CA")
        # Batch order matters for unit indices: identical first_final_signed_at
        # breaks ties by created_at ascending. created_at is stamped from the
        # logical clock (PRD section 2.5), so the clock is advanced between
        # batches to make the created_at ordering match the seed order.
        seed_studies(hosp["id"], 300, "2026-05-03T23:00:00Z",
                     "2026-05-04T12:00:00Z")          # after-hours units 1-300
        set_clock("2026-05-01T00:01:00Z")
        seed_studies(hosp["id"], 899, "2026-05-04T10:00:00Z",
                     "2026-05-04T12:00:00Z")          # regular units 301-1199
        set_clock("2026-05-01T00:02:00Z")
        seed_studies(hosp["id"], 1, "2026-05-04T10:30:00Z",
                     "2026-05-04T12:00:00Z",
                     critical_finding=True)           # critical unit 1200
        per = setup_billing_period(hosp["id"])
        return generate_invoice(per["id"])

    def test_tier_straddle_line_items_and_critical_addon(self, api):
        """PRD section 3.9: "Billable studies are ordered by
        `first_final_signed_at` ascending, ties broken by `created_at`
        ascending, and numbered from 1; `billable_study_count` records how many
        were found." and "Units are then aggregated into `line_items`, one line
        per combination of `hour_class` (`REGULAR` or `AFTER_HOURS`) and
        `tier_index`, each line carrying its `units`, the per-unit `rate_cents`,
        and the line `amount_cents` equal to units times unit price..." and
        "On top of the lines, the invoice adds a critical finding add-on: 250
        cents per billable study whose signed final report had
        `critical_finding` true, accumulated in `critical_addon_cents`."

        Design: Difficulty/combinatorial_formula/invoice_pricing_tier_straddle_multi_input
        """
        inv = self._make_combo_invoice(api)
        assert inv["billable_study_count"] == 1200
        lines = {(l["hour_class"], l["tier_index"]): l for l in inv["line_items"]}
        # Units 1-300 are after-hours tier1 at round_half_up(901*1.5) = 1352.
        assert lines[("AFTER_HOURS", 1)]["units"] == 300
        assert lines[("AFTER_HOURS", 1)]["rate_cents"] == 1352
        assert lines[("AFTER_HOURS", 1)]["amount_cents"] == 405600
        # Units 301-1000 regular tier1; 1001-1200 regular tier2.
        assert lines[("REGULAR", 1)]["units"] == 700
        assert lines[("REGULAR", 1)]["amount_cents"] == 700 * 901
        assert lines[("REGULAR", 2)]["units"] == 200
        assert lines[("REGULAR", 2)]["amount_cents"] == 200 * 801
        assert inv["critical_addon_cents"] == 250

    def test_tier_straddle_gross_and_total(self, api):
        """PRD section 3.9: "The invoice's `gross_cents` is the sum of all line
        amounts plus the critical add-on. ... The invoice's `total_cents` is
        `gross_cents` minus `penalty_credits_cents`, floored at zero so a
        heavily penalized period never bills negative."

        Design: Difficulty/combinatorial_formula/invoice_pricing_tier_straddle_multi_input
        """
        inv = self._make_combo_invoice(api)
        # 405600 + 630700 + 160200 + 250 = 1196750; on-time studies -> 0 penalty.
        assert inv["gross_cents"] == 1196750
        assert inv["penalty_credits_cents"] == 0
        assert inv["total_cents"] == 1196750


class TestAfterHoursRoundingOrder:
    def test_after_hours_per_unit_rounding_pinned(self, api):
        """PRD section 3.9: "Rounding is pinned and order-sensitive: each
        after-hours unit's price is rounded half-up to whole cents individually,
        before any aggregation, and no other rounding occurs anywhere in invoice
        composition. To make the order concrete, three after-hours tier-1 units
        bill as three times the half-up rounding of 901 times 1.5 — three times
        1352, totalling 4056 cents; summing the unrounded products first
        (4054.5 cents) and rounding once to 4055 is a forbidden
        interpretation."

        Design: Difficulty/combinatorial_formula/invoice_after_hours_per_unit_rounding_order
        """
        hosp = create_active_hospital(name="Hosp Round", state_code="CA")
        seed_studies(hosp["id"], 3, "2026-05-03T23:00:00Z", "2026-05-04T12:00:00Z")
        per = setup_billing_period(hosp["id"])
        inv = generate_invoice(per["id"])
        assert inv["gross_cents"] == 4056
        assert inv["gross_cents"] != 4055

    def test_after_hours_total_equals_gross_without_penalties(self, api):
        """PRD section 3.9: "The invoice's `total_cents` is `gross_cents` minus
        `penalty_credits_cents`, floored at zero so a heavily penalized period
        never bills negative."

        Design: Difficulty/combinatorial_formula/invoice_after_hours_per_unit_rounding_order
        """
        hosp = create_active_hospital(name="Hosp Round 2", state_code="CA")
        seed_studies(hosp["id"], 3, "2026-05-03T23:00:00Z", "2026-05-04T12:00:00Z")
        per = setup_billing_period(hosp["id"])
        inv = generate_invoice(per["id"])
        assert inv["penalty_credits_cents"] == 0
        assert inv["total_cents"] == 4056


class TestVolumeTierBoundary:
    def _invoice_for(self, api, hosp_id, count, received, signed, pstart, pend):
        seed_studies(hosp_id, count, received, signed)
        per = setup_billing_period(hosp_id, pstart, pend)
        return generate_invoice(per["id"])

    def test_1000_units_price_entirely_at_tier1(self, api):
        """PRD section 3.9: "Volume pricing uses three tiers. Units 1 through
        1000 bill at 901 cents each, units 1001 through 5000 at 801 cents, and
        units 5001 and beyond at 701 cents."

        Design: Corner/calculations/volume_tier_boundary_1000_vs_1001
        """
        hosp = create_active_hospital(name="Hosp Tier A", state_code="CA")
        inv = self._invoice_for(api, hosp["id"], 1000,
                                "2026-05-04T10:00:00Z", "2026-05-04T12:00:00Z",
                                "2026-05-01", "2026-05-31")
        assert inv["billable_study_count"] == 1000
        assert inv["gross_cents"] == 901000

    def test_1001st_unit_prices_at_tier2(self, api):
        """PRD section 3.9: "Volume pricing uses three tiers. Units 1 through
        1000 bill at 901 cents each, units 1001 through 5000 at 801 cents, and
        units 5001 and beyond at 701 cents."

        Design: Corner/calculations/volume_tier_boundary_1000_vs_1001
        """
        hosp = create_active_hospital(name="Hosp Tier B", state_code="CA")
        inv = self._invoice_for(api, hosp["id"], 1001,
                                "2026-06-04T10:00:00Z", "2026-06-04T12:00:00Z",
                                "2026-06-01", "2026-06-30")
        assert inv["billable_study_count"] == 1001
        assert inv["gross_cents"] == 901000 + 801


class TestPenaltyCapAndTotalFloor:
    def test_breach_minutes_computed_by_floor(self, api):
        """PRD section 3.6: "When breached, `breach_minutes` is the number of
        whole minutes of lateness, computed by taking the signed-to-due
        difference in seconds and discarding any partial minute; when on time,
        `breach_minutes` is 0."
        PRD section 3.9 (seeding): "...creates that many studies directly in
        `FINAL_SIGNED` status — each with `due_at`, `tat_breached`, and
        `breach_minutes` computed by the normal rules..."

        Design: Corner/calculations/breach_penalty_capped_and_total_floored
        """
        hosp = create_active_hospital(name="Hosp Cap", state_code="CA")
        # Received 2026-05-01T00:00:00Z; ROUTINE default 1440min -> due
        # 2026-05-02T00:00:00Z; signed 2026-05-05T09:00:00Z -> 4860 min late.
        seed = seed_studies(hosp["id"], 1, "2026-05-01T00:00:00Z",
                            "2026-05-05T09:00:00Z", priority="ROUTINE")
        sid = seed["study_ids"][0]
        study = get_success_data(api.get_study(sid, ADMIN))
        assert study["tat_breached"] is True
        assert study["breach_minutes"] == 4860

    def test_penalty_capped_and_total_floored_at_zero(self, api):
        """PRD section 3.9: "Penalty credits then give money back for lateness:
        `penalty_credits_cents` sums, over every breached billable study, the
        lesser of that study's `breach_minutes` multiplied by the hospital's
        `penalty_per_breach_minute_cents` and the hospital's
        `breach_penalty_cap_cents` — the cap applies per study. The invoice's
        `total_cents` is `gross_cents` minus `penalty_credits_cents`, floored at
        zero so a heavily penalized period never bills negative."

        Design: Corner/calculations/breach_penalty_capped_and_total_floored
        """
        hosp = create_active_hospital(name="Hosp Cap 2", state_code="CA")
        seed_studies(hosp["id"], 1, "2026-05-01T00:00:00Z",
                     "2026-05-05T09:00:00Z", priority="ROUTINE")
        per = setup_billing_period(hosp["id"])
        inv = generate_invoice(per["id"])
        # min(4860 * 50, 20000) = 20000 — the cap binds.
        assert inv["penalty_credits_cents"] == 20000
        # received_at 00:00 UTC is before 07:00, inside the after-hours window
        # (PRD sections 2.5/3.9): one after-hours tier-1 unit bills at
        # round_half_up(901 * 1.5) = 1352.
        assert inv["gross_cents"] == 1352
        # max(0, 1352 - 20000) = 0 — the floor binds.
        assert inv["total_cents"] == 0


class TestInvoiceComputedRead:
    def test_invoice_computed_read_matches_line_items(self, api):
        """PRD section 3.9: "Units are then aggregated into `line_items`, one
        line per combination of `hour_class` (`REGULAR` or `AFTER_HOURS`) and
        `tier_index`, each line carrying its `units`, the per-unit `rate_cents`,
        and the line `amount_cents` equal to units times unit price; regular-
        hour units need no rounding since tier rates are already whole cents."
        and "The invoice's `gross_cents` is the sum of all line amounts plus the
        critical add-on."

        Design: Corner/endpoints/invoice_computed_read_matches_line_items
        """
        hosp = create_active_hospital(name="Hosp CR", state_code="CA")
        seed_studies(hosp["id"], 1, "2026-05-04T10:00:00Z", "2026-05-04T12:00:00Z")
        per = setup_billing_period(hosp["id"])
        gen = generate_invoice(per["id"])
        inv = get_success_data(api.get_invoice(gen["id"], ADMIN))
        assert inv["line_items"] == [{
            "hour_class": "REGULAR", "tier_index": 1,
            "units": 1, "rate_cents": 901, "amount_cents": 901,
        }]
        assert inv["gross_cents"] == 901
        assert inv["penalty_credits_cents"] == 0
        assert inv["total_cents"] == 901
        assert inv["billable_study_count"] == 1


class TestBillingPeriodReopenGrace:
    def test_reopen_within_grace_window_allowed(self, api):
        """PRD section 3.9: "A closed period may be reopened within a grace
        window: reopening moves `CLOSED → OPEN` provided the current logical day
        is on or before seven days after `period_end`, counting inclusively — a
        period ending 2026-05-31 may be reopened through 2026-06-07 and rejects
        on 2026-06-08 with `ERR_REOPEN_WINDOW_EXPIRED`."

        Design: Corner/validations/reopen_after_grace_window_rejected
        """
        hosp = create_active_hospital(name="Hosp RO", state_code="CA")
        per = setup_billing_period(hosp["id"], "2026-05-01", "2026-05-31",
                                   close=True)
        set_clock("2026-06-07T12:00:00Z")  # period_end + 6 days: within grace
        data = validate_success(api.reopen_billing_period(per["id"], ADMIN), 200)
        assert data["status"] == "OPEN"

    def test_reopen_after_grace_window_rejected(self, api):
        """PRD section 3.9: "...a period ending 2026-05-31 may be reopened
        through 2026-06-07 and rejects on 2026-06-08 with
        `ERR_REOPEN_WINDOW_EXPIRED`."

        Design: Corner/validations/reopen_after_grace_window_rejected
        """
        hosp = create_active_hospital(name="Hosp RO 2", state_code="CA")
        per = setup_billing_period(hosp["id"], "2026-05-01", "2026-05-31",
                                   close=True)
        set_clock("2026-06-08T00:00:00Z")  # period_end + 8 days: grace expired
        resp = api.reopen_billing_period(per["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED, 422)


class TestBillingPeriodOverlap:
    def test_billing_period_overlap_rejected(self, api):
        """PRD section 3.9: "Periods for the same hospital follow inclusive-day
        semantics: a new period may not share even one calendar day with an
        existing period of that hospital in `OPEN`, `CLOSED`, or `INVOICED`
        status, else `ERR_PERIOD_OVERLAP`."

        Design: Corner/validations/billing_period_overlap_rejected
        """
        hosp = create_active_hospital(name="Hosp PO", state_code="CA")
        validate_success(api.create_billing_period(create_billing_period_payload(
            hosp["id"], period_start="2026-05-01", period_end="2026-05-31"),
            ADMIN), 201)
        resp = api.create_billing_period(create_billing_period_payload(
            hosp["id"], period_start="2026-05-15", period_end="2026-06-15"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP, 409)
        ok = validate_success(api.create_billing_period(
            create_billing_period_payload(hosp["id"], period_start="2026-06-01",
                                          period_end="2026-06-30"), ADMIN), 201)
        assert ok["status"] == "OPEN"


class TestOptimisticConcurrency:
    def test_routing_policy_create_stale_version_rejected(self, api):
        """PRD section 2.7: "A request to `POST /telerad/routing-policies` must
        carry `expected_hospital_version` equal to the target hospital's current
        `version`; creating a policy retires any same-key active policy, so a
        writer holding a stale hospital version would base its routing decision
        on a retired policy set. ... In all three cases, a mismatch between the
        supplied value and the parent entity's current `version` is rejected
        with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read
        before writing."

        Design: Corner/cross_cutting_layers/routing_policy_create_stale_version_rejected
        """
        hosp = create_active_hospital(name="Hosp OCC", state_code="CA")
        # First policy create bumps hospital.version from 2 to 3.
        create_routing_policy(hosp["id"])
        stale_version = 2  # pre-policy-create version
        resp = api.create_routing_policy(create_routing_policy_payload(
            hosp["id"], stale_version, required_subspecialty="BODY",
            prelim_required=True), ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_fresh_policy_create_retires_same_key_predecessor(self, api):
        """PRD section 3.4: "Creation is concurrency-guarded by
        `expected_hospital_version` as described in §2.7, and it carries two
        side effects beyond the new row: the hospital's `version` increments by
        1, and any existing `ACTIVE` policy sharing the same four-part key
        transitions `ACTIVE → RETIRED` — the superseded policy's `version`
        increments, it lands in the terminal `RETIRED` status, and it no longer
        resolves at route time, leaving exactly one `ACTIVE` policy per key."

        Design: Corner/cross_cutting_layers/routing_policy_create_stale_version_rejected
        """
        hosp = create_active_hospital(name="Hosp OCC 2", state_code="CA")
        pol1 = create_routing_policy(hosp["id"])
        pol2 = create_routing_policy(hosp["id"], required_subspecialty="BODY",
                                     prelim_required=True)
        p1 = get_success_data(api.get_routing_policy(pol1["id"], ADMIN))
        p2 = get_success_data(api.get_routing_policy(pol2["id"], ADMIN))
        assert p1["status"] == "RETIRED"
        assert p2["status"] == "ACTIVE"
        # create(1) + activate(2) + P1 create(3) + P2 create(4).
        assert get_success_data(api.get_hospital(hosp["id"], ADMIN))["version"] == 4

    def test_invoice_generate_stale_version_rejected(self, api):
        """PRD section 2.7: "A request to
        `POST /telerad/billing-periods/{id}/generate-invoice` must carry
        `expected_billing_period_version` equal to the period's current
        `version`; regenerating an invoice voids the prior current invoice, so a
        stale generate would void an invoice the caller never saw. ... In all
        three cases, a mismatch between the supplied value and the parent
        entity's current `version` is rejected with `ERR_STALE_VERSION`
        (HTTP 412), forcing the client to re-read before writing."

        Design: Corner/cross_cutting_layers/invoice_generate_stale_version_rejected_and_regenerate_supersedes
        """
        hosp = create_active_hospital(name="Hosp OI", state_code="CA")
        seed_studies(hosp["id"], 1, "2026-05-04T10:00:00Z", "2026-05-04T12:00:00Z")
        per = setup_billing_period(hosp["id"])
        stale_version = per["version"]
        generate_invoice(per["id"])  # first generate bumps the period version
        resp = api.generate_invoice(
            per["id"], {"expected_billing_period_version": stale_version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_regenerate_supersedes_prior_invoice_with_identical_totals(self, api):
        """PRD section 3.9: "Regenerating an already-`INVOICED` period
        supersedes the previous invoice: the prior `CURRENT` invoice transitions
        to the terminal `VOID` state with its `version` incremented, the fresh
        invoice becomes the `CURRENT` one, and the period's `version`
        increments."
        PRD section 3.9: "Invoice generation is available from `CLOSED` (first
        generation) and from `INVOICED` (regeneration), moves the period to
        `INVOICED`..."

        Design: Corner/cross_cutting_layers/invoice_generate_stale_version_rejected_and_regenerate_supersedes
        """
        hosp = create_active_hospital(name="Hosp OI 2", state_code="CA")
        seed_studies(hosp["id"], 1, "2026-05-04T10:00:00Z", "2026-05-04T12:00:00Z")
        per = setup_billing_period(hosp["id"])
        inv1 = generate_invoice(per["id"])
        inv2 = generate_invoice(per["id"])  # regenerate from INVOICED
        assert get_success_data(api.get_invoice(inv1["id"], ADMIN))["status"] == "VOID"
        assert inv2["status"] == "CURRENT"
        # Unchanged input set -> identical totals.
        assert inv2["gross_cents"] == 901


class TestBillableConservationAcrossAddendumAndRegenerate:
    def _setup_invoiced_then_addendum(self, api):
        """One seeded FINAL_SIGNED study invoiced once, then driven through the
        addendum cycle and regenerated."""
        ctx = setup_assignment_ready(hospital_name="Hosp InvB")
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        seed = seed_studies(hosp["id"], 1, "2026-05-04T10:00:00Z",
                            "2026-05-04T12:00:00Z")
        sid = seed["study_ids"][0]
        per = setup_billing_period(hosp["id"])
        inv1 = generate_invoice(per["id"])
        return hosp, rad, sid, per, inv1

    def test_addendum_cycle_does_not_rebill_study(self, api):
        """PRD section 3.9: "...builds the **billable set**: the hospital's
        studies whose `first_final_signed_at` falls inside the billable window
        and whose status is `FINAL_SIGNED` or `AMENDMENT_PENDING`." and
        "`billable_study_count` records how many were found."
        PRD section 3.6: "On signature the study returns to `FINAL_SIGNED`,
        `addendum_count` increases by 1, `first_final_signed_at` is left
        untouched..."

        Design: Difficulty/compensating_invariant/billable_count_gross_conserved_across_addendum_and_regenerate
        """
        hosp, rad, sid, per, inv1 = self._setup_invoiced_then_addendum(api)
        assert inv1["billable_study_count"] == 1
        assert inv1["gross_cents"] == 901

        # Run the addendum cycle on the seeded FINAL_SIGNED study.
        validate_success(api.request_addendum(
            sid, make_hospital_user_headers(hosp["id"])), 200)
        asg = assign_study(sid, rad["id"])
        accept_assignment(asg)
        rep = create_draft_report(asg["id"], rad["id"], "ADDENDUM")
        sign_report(rep["id"], rad["id"])

        study = get_success_data(api.get_study(sid, DISPATCH))
        assert study["status"] == "FINAL_SIGNED"
        assert study["addendum_count"] == 1

        inv2 = generate_invoice(per["id"])
        # Conserved across the forward/compensating pair.
        assert inv2["billable_study_count"] == 1
        assert inv2["gross_cents"] == 901

    def test_regenerate_voids_prior_invoice_after_addendum(self, api):
        """PRD section 3.9: "Regenerating an already-`INVOICED` period
        supersedes the previous invoice: the prior `CURRENT` invoice transitions
        to the terminal `VOID` state with its `version` incremented, the fresh
        invoice becomes the `CURRENT` one, and the period's `version`
        increments."

        Design: Difficulty/compensating_invariant/billable_count_gross_conserved_across_addendum_and_regenerate
        """
        hosp, rad, sid, per, inv1 = self._setup_invoiced_then_addendum(api)
        validate_success(api.request_addendum(
            sid, make_hospital_user_headers(hosp["id"])), 200)
        asg = assign_study(sid, rad["id"])
        accept_assignment(asg)
        rep = create_draft_report(asg["id"], rad["id"], "ADDENDUM")
        sign_report(rep["id"], rad["id"])

        inv2 = generate_invoice(per["id"])
        assert get_success_data(api.get_invoice(inv1["id"], ADMIN))["status"] == "VOID"
        assert inv2["status"] == "CURRENT"
        assert inv2["gross_cents"] == 901
