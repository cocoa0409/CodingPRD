"""Dual-variant billing: the provisional visit estimate vs. the final invoice,
and the two LTC reimbursement variants (indemnity vs. reimbursement)."""
from test_helpers import (
    setup_completed_visit,
    setup_finalized_invoice,
    setup_assigned_visit,
    attach_ltc_policy,
    validate_success,
    TEST_USERS,
)

BILLING = TEST_USERS["billing_headers"]
COORD = TEST_USERS["coordinator_headers"]


def _diverging_completed_visit(api):
    """3h scheduled visit @3000c/hr, 75c/mile, worked 3.5h with 10 miles and one
    approved 1500c MEAL_PREP add-on."""
    return setup_completed_visit(
        api,
        client_overrides={"hourly_rate_cents": 3000, "mileage_rate_cents_per_mile": 75},
        scheduled_start="2026-03-05T09:00:00Z",
        scheduled_end="2026-03-05T12:00:00Z",
        actual_start="2026-03-05T09:00:00Z",
        actual_end="2026-03-05T12:30:00Z",
        mileage_miles=10,
        approved_addons=[("MEAL_PREP", 1500)],
    )


class TestEstimateVsFinal:
    def test_provisional_estimate_uses_scheduled_duration(self, api):
        """PRD §3.5: "When a caregiver is matched to a visit, the system sets
        estimated_cost_cents as a provisional labor estimate: it runs the same labor
        computation but using the scheduled duration (scheduled_end minus
        scheduled_start) in place of actual minutes, assumes zero mileage and no
        add-ons, and rounds the raw labor to whole cents half-up."

        Design: Difficulty/dual_variant_calc/visit_estimate_vs_final_invoice_diverge
        """
        ctx = _diverging_completed_visit(api)
        visit = validate_success(api.get_visit(ctx["visit"]["id"], COORD))
        # scheduled 3h @ 3000 = 9000, zero mileage, no add-ons.
        assert visit["estimated_cost_cents"] == 9000, (
            f"expected provisional estimate 9000, got {visit['estimated_cost_cents']}"
        )

    def test_final_invoice_uses_actual_duration_mileage_addons(self, api):
        """PRD §3.5: "When the visit is clocked out, the final invoice is assembled
        from the visit's actual figures. The invoice's labor_cents is the raw labor
        (computed from the actual worked minutes) rounded to whole cents half-up."

        Design: Difficulty/dual_variant_calc/visit_estimate_vs_final_invoice_diverge
        """
        ctx = _diverging_completed_visit(api)
        inv = ctx["invoice"]
        # actual 3.5h @ 3000 = 10500 labor; 10mi*75 = 750; add-on 1500; total 12750.
        assert inv["labor_cents"] == 10500, f"expected labor 10500, got {inv['labor_cents']}"
        assert inv["total_cents"] == 12750, f"expected total 12750, got {inv['total_cents']}"

    def test_estimate_diverges_from_final_total(self, api):
        """PRD §3.5: "so later edits to the client never retroactively reprice an
        existing visit."
        PRD §3.5: "it runs the same labor computation but using the scheduled
        duration (scheduled_end minus scheduled_start) in place of actual minutes,
        assumes zero mileage and no add-ons, and rounds the raw labor to whole cents
        half-up."

        Design: Difficulty/dual_variant_calc/visit_estimate_vs_final_invoice_diverge
        """
        ctx = _diverging_completed_visit(api)
        visit = validate_success(api.get_visit(ctx["visit"]["id"], COORD))
        assert visit["estimated_cost_cents"] != ctx["invoice"]["total_cents"], (
            "provisional estimate (scheduled-only) must diverge from the final actual total"
        )


class TestLtcReimbursementVariants:
    def _finalized_ctx(self, api):
        """Finalized invoice with labor 10500, add-on 1500, mileage 750
        (total 12750, eligible base 12000)."""
        return setup_finalized_invoice(
            api,
            client_overrides={"hourly_rate_cents": 3000, "mileage_rate_cents_per_mile": 75},
            scheduled_start="2026-03-05T09:00:00Z",
            scheduled_end="2026-03-05T12:00:00Z",
            actual_start="2026-03-05T09:00:00Z",
            actual_end="2026-03-05T12:30:00Z",
            mileage_miles=10,
            approved_addons=[("MEAL_PREP", 1500)],
        )

    def test_indemnity_reimburses_flat_benefit_capped_at_eligible(self, api):
        """PRD §3.7: "Under an INDEMNITY policy, the reimbursement is the smaller of
        the policy's daily_benefit_cents and the eligible base — a flat daily benefit
        capped at what is actually eligible, ignoring the reimbursement rate and
        daily cap."

        Design: Difficulty/dual_variant_calc/ltc_indemnity_vs_reimbursement_diverge
        """
        ctx = self._finalized_ctx(api)
        pol = attach_ltc_policy(
            api, ctx["client"]["id"], payer_name="IndemCo",
            benefit_type="INDEMNITY", lifetime_max_cents=1_000_000, daily_benefit_cents=10_000,
        )
        claim = validate_success(
            api.create_claim(ctx["invoice"]["id"], {"ltc_policy_id": pol["id"]}, BILLING), 201
        )
        # min(10000, eligible 12000) = 10000.
        assert claim["reimbursed_cents"] == 10000, f"expected 10000, got {claim['reimbursed_cents']}"

    def test_reimbursement_pays_rate_times_eligible_capped(self, api):
        """PRD §3.7: "Under a REIMBURSEMENT policy, the reimbursement is the smaller
        of two quantities: the policy's reimbursement_rate multiplied by the eligible
        base and then rounded to whole cents half-up, and the policy's daily_cap_cents
        per-claim ceiling — ignoring the daily benefit."

        Design: Difficulty/dual_variant_calc/ltc_indemnity_vs_reimbursement_diverge
        """
        ctx = self._finalized_ctx(api)
        pol = attach_ltc_policy(
            api, ctx["client"]["id"], payer_name="ReimbCo",
            benefit_type="REIMBURSEMENT", lifetime_max_cents=1_000_000,
            reimbursement_rate=0.8, daily_cap_cents=12_000,
        )
        claim = validate_success(
            api.create_claim(ctx["invoice"]["id"], {"ltc_policy_id": pol["id"]}, BILLING), 201
        )
        # min(round(0.8*12000)=9600, cap 12000) = 9600.
        assert claim["reimbursed_cents"] == 9600, f"expected 9600, got {claim['reimbursed_cents']}"

    def test_two_variants_diverge_on_same_eligible_base(self, api):
        """PRD §3.7: "The reimbursed_cents the payer covers depends on the snapshot
        benefit type."

        Design: Difficulty/dual_variant_calc/ltc_indemnity_vs_reimbursement_diverge
        """
        ctx = self._finalized_ctx(api)
        pol_ind = attach_ltc_policy(
            api, ctx["client"]["id"], payer_name="IndemCo",
            benefit_type="INDEMNITY", lifetime_max_cents=1_000_000, daily_benefit_cents=10_000,
        )
        pol_reimb = attach_ltc_policy(
            api, ctx["client"]["id"], payer_name="ReimbCo",
            benefit_type="REIMBURSEMENT", lifetime_max_cents=1_000_000,
            reimbursement_rate=0.8, daily_cap_cents=12_000,
        )
        claim_ind = validate_success(
            api.create_claim(ctx["invoice"]["id"], {"ltc_policy_id": pol_ind["id"]}, BILLING), 201
        )
        claim_reimb = validate_success(
            api.create_claim(ctx["invoice"]["id"], {"ltc_policy_id": pol_reimb["id"]}, BILLING), 201
        )
        assert claim_ind["reimbursed_cents"] != claim_reimb["reimbursed_cents"], (
            f"variants must diverge: indemnity {claim_ind['reimbursed_cents']} "
            f"vs reimbursement {claim_reimb['reimbursed_cents']}"
        )


def test_assignment_estimate_visible_immediately(api):
    """PRD §3.4: "the visit's estimated_cost_cents is set to the provisional labor
    estimate described in §3.5"

    Design: Corner/consistency_model/assignment_estimate_visible_immediately
    """
    ctx = setup_assigned_visit(
        api,
        client_overrides={"hourly_rate_cents": 3000},
        scheduled_start="2026-03-05T09:00:00Z",
        scheduled_end="2026-03-05T12:00:00Z",
    )
    visit = validate_success(api.get_visit(ctx["visit"]["id"], COORD))
    assert visit["estimated_cost_cents"] == 9000, (
        f"provisional estimate must be visible immediately, got {visit['estimated_cost_cents']}"
    )
