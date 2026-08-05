"""Pricing and take-rate calculations: SLA credits, invoice amounts, grant
reimbursement, FPL eligibility, and milestone take-rate boundaries.

Covers Difficulty queue rules: dual_variant_calc, combinatorial_formula,
boundary_precision_check.
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS, make_analyst_headers, make_officer_headers,
    fixtures as fx,
)

NOC = TEST_USERS["noc_operator_headers"]
ANY_READER = TEST_USERS["program_admin_headers"]


# =====================================================================
# Rule 1 — dual_variant_calc / sla_credit_provisional_vs_final
# =====================================================================
class TestSlaCreditProvisionalVsFinal:
    def _setup_open_outage(self, api):
        fx.set_clock(api, "2026-06-01T12:00:00Z")
        ctx = fx.setup_active_subscription(api, homes_passed=100, price=6000,
                                           install_start="2026-06-01T09:00:00Z")
        # An ISSUED invoice must exist so the final credit can be APPLIED to it
        # at resolution (PRD §3.6 level 2).
        ctx["invoice"] = fx.generate_invoice(api, ctx["subscription"]["id"])
        outage = fx.report_outage(api, ctx["area"]["id"], "2026-06-01T00:00:00Z", severity="FULL")
        return ctx, outage

    def test_provisional_credit_uses_clock_now_minus_started(self, api):
        """PRD §3.6: "The **provisional** variant is computed at report time while
        the outage is `OPEN`: downtime in minutes is now minus `started_at`, and
        each affected subscription's provisional credit is summed into the outage's
        `estimated_credit_total_cents`."
        PRD §3.6: "An SLA credit for one subscription and one outage is
        `round_half_up(subscription.monthly_price_cents * downtime_minutes / 43200)`,
        where 43,200 is the number of minutes in the standard monthly billing period."

        Design: Difficulty/dual_variant_calc/sla_credit_provisional_vs_final
        """
        _, outage = self._setup_open_outage(api)
        assert outage["estimated_credit_total_cents"] == 100, \
            f"provisional (720 min) should be 100, got {outage['estimated_credit_total_cents']}"

    def test_final_credit_uses_ended_minus_started(self, api):
        """PRD §3.6: "The **final** variant is computed at resolution: downtime in
        minutes is `ended_at` minus `started_at`."
        PRD §3.6: "the server creates an SLA credit in `PENDING` whose
        `downtime_minutes` is the final whole-minute downtime and whose `credit_cents`
        is the final-variant amount ... Each new credit is then `APPLIED` to that
        subscription's latest `ISSUED` invoice"

        Design: Difficulty/dual_variant_calc/sla_credit_provisional_vs_final
        """
        ctx, outage = self._setup_open_outage(api)
        resolved = validate_success(
            api.resolve_outage(outage["id"], {"ended_at": "2026-06-01T06:00:00Z"}, NOC)
        )
        assert resolved["final_credit_total_cents"] == 50, \
            f"final (360 min) should be 50, got {resolved['final_credit_total_cents']}"
        credits, _ = _list(api.list_sla_credits(ANY_READER, params={"outage_id": outage["id"]}))
        subject = [c for c in credits if c["subscription_id"] == ctx["subscription"]["id"]]
        assert len(subject) == 1, "exactly one SLA credit for the affected subscription"
        assert subject[0]["credit_cents"] == 50
        assert subject[0]["status"] == "APPLIED"
        assert resolved["final_credit_total_cents"] != outage["estimated_credit_total_cents"]


# =====================================================================
# Rule 1 — dual_variant_calc / take_rate_reported_vs_verified
# =====================================================================
class TestTakeRateReportedVsVerified:
    def _setup(self, api):
        grant = fx.create_grant(api)
        area = fx.create_serviceable_area(api, grant["id"], name="Area 4",
                                          census_block_group="010010001004", homes_passed=4)
        plan = fx.create_plan(api, monthly_price_cents=6000)
        tech = fx.create_technician(api)
        # subscription A -> ACTIVE
        subA = fx.create_subscriber(api, area["id"], full_name="Sub A", email="a@x.com")
        subscriptionA = fx.create_pending_subscription(api, subA["id"], plan["id"], area["id"])
        ioA = fx.schedule_install(api, subscriptionA["id"], tech["id"], "2026-06-01T09:00:00Z")
        fx.complete_install(api, ioA["id"], tech["id"])
        fx.activate_subscription(api, subscriptionA["id"])
        # subscription B -> stays PENDING_INSTALL
        subB = fx.create_subscriber(api, area["id"], full_name="Sub B", email="b@x.com")
        fx.create_pending_subscription(api, subB["id"], plan["id"], area["id"])
        return area

    def test_reported_counts_pending_and_active(self, api):
        """PRD §2.9: "it counts subscriptions in the area whose `service_status` is
        either `PENDING_INSTALL` or `ACTIVE`, divides by `homes_passed`, multiplies
        by 100, and rounds half-up to two decimal places; it is exposed as
        `reported_take_rate_pct` on the service area."

        Design: Difficulty/dual_variant_calc/take_rate_reported_vs_verified
        """
        area = self._setup(api)
        fetched = validate_success(api.get_service_area(area["id"], ANY_READER))
        assert fetched["reported_take_rate_pct"] == 50.0, \
            f"2 of 4 homes = 50.0, got {fetched['reported_take_rate_pct']}"

    def test_verified_counts_active_only(self, api):
        """PRD §2.9: "The **verified** take-rate counts only subscriptions whose
        `service_status` is `ACTIVE`, applies the same division, multiplication, and
        rounding, and is exposed as `verified_take_rate_pct`."

        Design: Difficulty/dual_variant_calc/take_rate_reported_vs_verified
        """
        area = self._setup(api)
        fetched = validate_success(api.get_service_area(area["id"], ANY_READER))
        assert fetched["verified_take_rate_pct"] == 25.0, \
            f"1 of 4 homes = 25.0, got {fetched['verified_take_rate_pct']}"


# =====================================================================
# Rule 2 — combinatorial_formula / invoice_amount_nested_min_conditional_mode_a
# =====================================================================
class TestInvoiceAmountSubsidyThenSla:
    def _setup_invoice(self, api):
        grant = fx.create_grant(api)
        area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
        plan = fx.create_plan(api, monthly_price_cents=6000)
        subsidy = fx.create_subsidy_program(api, monthly_discount_cents=3000)
        subscriber = fx.create_subscriber(api, area["id"])
        subscription = fx.create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
        tech = fx.create_technician(api)
        io = fx.schedule_install(api, subscription["id"], tech["id"], "2026-06-01T09:00:00Z")
        fx.complete_install(api, io["id"], tech["id"])
        fx.activate_subscription(api, subscription["id"])
        fx.create_active_enrollment(api, subscriber["id"], subsidy["id"],
                                    household_size=2, annual_income_cents=3_000_000)
        return fx.generate_invoice(api, subscription["id"])

    def test_subsidy_discount_is_min_of_discount_and_base(self, api):
        """PRD §3.5: "The `subsidy_discount_cents` is the subsidy first: if the
        subscriber has an `ACTIVE` enrollment, it is the smaller of that enrollment's
        subsidy program `monthly_discount_cents` and the base amount; if there is no
        `ACTIVE` enrollment it is 0."

        Design: Difficulty/combinatorial_formula/invoice_amount_nested_min_conditional_mode_a
        """
        invoice = self._setup_invoice(api)
        assert invoice["base_amount_cents"] == 6000
        assert invoice["subsidy_discount_cents"] == 3000, \
            f"min(3000, 6000) should be 3000, got {invoice['subsidy_discount_cents']}"

    def test_total_due_is_base_minus_subsidy_minus_sla(self, api):
        """PRD §3.5: "Finally `total_due_cents` is the base amount minus the subsidy
        discount minus the applied SLA credit — subsidy first, then SLA credit on the
        post-subsidy net."

        Design: Difficulty/combinatorial_formula/invoice_amount_nested_min_conditional_mode_a
        """
        invoice = self._setup_invoice(api)
        assert invoice["sla_credit_cents"] == 0
        assert invoice["total_due_cents"] == 3000, \
            f"6000 - 3000 - 0 should be 3000, got {invoice['total_due_cents']}"


# =====================================================================
# Rule 2 — combinatorial_formula / grant_claim_reimbursement_round_then_sum_mode_b
# =====================================================================
class TestGrantClaimRoundThenSum:
    def _setup_claim(self, api):
        grant = fx.create_grant(api)
        g_v = grant["version"]
        area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
        plan = fx.create_plan(api, monthly_price_cents=6000)
        subsidy = fx.create_subsidy_program(api, monthly_discount_cents=3000)
        tech = fx.create_technician(api)
        starts = ["2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z", "2026-06-01T15:00:00Z"]
        for i, start in enumerate(starts):
            subscriber = fx.create_subscriber(api, area["id"], full_name=f"S{i+1}",
                                              email=f"s{i+1}@x.com", service_address=f"{i+1} A St")
            subscription = fx.create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
            io = fx.schedule_install(api, subscription["id"], tech["id"], start)
            fx.complete_install(api, io["id"], tech["id"])
            fx.activate_subscription(api, subscription["id"])
            fx.create_active_enrollment(api, subscriber["id"], subsidy["id"],
                                        household_size=2, annual_income_cents=3_000_000)
        return fx.create_claim(api, grant["id"], [area["id"]], g_v)

    def test_subsidized_subscriber_count(self, api):
        """PRD §3.7: "The claim also records `subsidized_subscriber_count` as the
        count of those qualifying subscribers."

        Design: Difficulty/combinatorial_formula/grant_claim_reimbursement_round_then_sum_mode_b
        """
        claim = self._setup_claim(api)
        assert claim["subsidized_subscriber_count"] == 3, \
            f"3 qualifying subscribers, got {claim['subsidized_subscriber_count']}"

    def test_amount_claimed_rounds_each_share_then_sums(self, api):
        """PRD §3.7: "The rounding order is pinned: round each subscriber's share to
        whole cents first, then sum the rounded shares into `amount_claimed_cents` —
        summing raw shares and rounding once at the end is not used and would produce
        a different figure."

        Design: Difficulty/combinatorial_formula/grant_claim_reimbursement_round_then_sum_mode_b
        """
        claim = self._setup_claim(api)
        # round(3000 * 0.3334) = round(1000.2) = 1000 per subscriber; 3 * 1000 = 3000.
        # sum-then-round would give round(3000.6) = 3001.
        assert claim["amount_claimed_cents"] == 3000, \
            f"round-then-sum should be 3000 (not 3001), got {claim['amount_claimed_cents']}"


# =====================================================================
# Rule 6 — boundary_precision_check / fpl_eligibility_inclusive_boundary
# =====================================================================
class TestFplEligibilityInclusiveBoundary:
    def _submitted_enrollment_at_boundary(self, api):
        grant = fx.create_grant(api)
        area = fx.create_area(api, grant["id"], homes_passed=100)
        subsidy = fx.create_subsidy_program(api, eligibility_fpl_pct=200)
        subscriber = fx.create_subscriber(api, area["id"])
        return subsidy, fx.create_enrollment(api, subscriber["id"], subsidy["id"],
                                              household_size=2, annual_income_cents=4_068_000)

    def test_fpl_pct_computed_exactly_at_ceiling(self, api):
        """PRD §3.4: "On creation the server computes the applicant's
        Federal-Poverty-Level ratio, `fpl_pct`: it divides `annual_income_cents` by
        the annual FPL base for the given household size, multiplies by 100, and
        rounds half-up to two decimal places."

        Design: Difficulty/boundary_precision_check/fpl_eligibility_inclusive_boundary
        """
        _, enrollment = self._submitted_enrollment_at_boundary(api)
        assert enrollment["fpl_pct"] == 200.0, \
            f"4068000 / 2034000 * 100 = 200.00, got {enrollment['fpl_pct']}"

    def test_verify_at_inclusive_boundary_activates(self, api):
        """PRD §3.4: "The applicant is eligible when the computed `fpl_pct` is at or
        below the subsidy program's `eligibility_fpl_pct` ceiling — the boundary is
        inclusive."
        PRD §3.4: "when it succeeds, the enrollment moves `SUBMITTED` to `ACTIVE`, its
        `certification_expires_at` is set to now plus 365 days, and the subscriber's
        subsequent invoices begin receiving the subsidy discount."

        Design: Difficulty/boundary_precision_check/fpl_eligibility_inclusive_boundary
        """
        _, enrollment = self._submitted_enrollment_at_boundary(api)
        verified = validate_success(api.verify_enrollment(enrollment["id"],
                                                          TEST_USERS["eligibility_worker_headers"]))
        assert verified["status"] == "ACTIVE", \
            f"fpl 200.00 <= ceiling 200 is eligible, got {verified['status']}"


# =====================================================================
# Rule 6 — boundary_precision_check / take_rate_milestone_ge_boundary
# =====================================================================
class TestTakeRateMilestoneBoundary:
    def _submitted_claim_two_active_over_five(self, api):
        grant = fx.create_grant(api, take_rate_milestone_pct=40)
        g_v = grant["version"]
        area = fx.create_serviceable_area(api, grant["id"], name="Area 5",
                                          census_block_group="010010001005", homes_passed=5)
        plan = fx.create_plan(api, monthly_price_cents=6000)
        tech = fx.create_technician(api)
        for i, start in enumerate(["2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z"]):
            fx.add_active_subscription_to_area(
                api, area, plan, tech, start,
                subscriber_overrides={"full_name": f"S{i+1}", "email": f"s{i+1}@x.com",
                                      "service_address": f"{i+1} A St"})
        claim = fx.create_claim(api, grant["id"], [area["id"]], g_v)
        fx.submit_claim(api, claim["id"], analyst_user_id="analyst-1")
        return grant, claim

    def test_claim_approved_at_milestone_boundary(self, api):
        """PRD §3.7: "the aggregate verified take-rate over the covered areas is the
        sum of their active-subscription counts divided by the sum of their
        `homes_passed`, times 100, rounded half-up to two decimal places; if that
        aggregate is at or above the grant's `take_rate_milestone_pct`, the grant
        moves to `MILESTONE_MET`."
        PRD §3.7: "Approval moves the claim to the terminal `APPROVED` and disburses"

        Design: Difficulty/boundary_precision_check/take_rate_milestone_ge_boundary
        """
        _, claim = self._submitted_claim_two_active_over_five(api)
        approved = validate_success(api.approve_grant_claim(claim["id"], make_officer_headers("officer-1")))
        assert approved["status"] == "APPROVED"

    def test_grant_reaches_milestone_at_ge_boundary(self, api):
        """PRD §3.7: "if that aggregate is at or above the grant's
        `take_rate_milestone_pct`, the grant moves to `MILESTONE_MET`."

        Design: Difficulty/boundary_precision_check/take_rate_milestone_ge_boundary
        """
        grant, claim = self._submitted_claim_two_active_over_five(api)
        validate_success(api.approve_grant_claim(claim["id"], make_officer_headers("officer-1")))
        fetched = validate_success(api.get_grant(grant["id"], ANY_READER))
        assert fetched["status"] == "MILESTONE_MET", \
            f"2/5 = 40.00 >= 40 milestone, expected MILESTONE_MET, got {fetched['status']}"


def _list(response):
    """Helper: unpack a paginated list response into (data, meta)."""
    from test_helpers import validate_paginated
    return validate_paginated(response)
