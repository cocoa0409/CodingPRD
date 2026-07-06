"""Monthly reimbursement claims: estimate/final, recall cycle, OCC, and rate lookup."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_site, create_funded_student, setup_prepared_lunch_site,
    setup_three_category_claim, create_claim, record_reimbursable_lunch,
    create_reimbursement_rate_payload,
    make_director_headers, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["pos_clerk_headers"]


# ==========================================================================
# Combinatorial formula: tiered per-category rate + conditional performance addon
# ==========================================================================
class TestTieredEstimateWithPerformanceAddon:
    def test_estimate_sums_tiered_rates_plus_addon(self, api):
        """PRD §3.7: "The amount is `free_count` multiplied by the free rate plus its add-on, plus `reduced_count` multiplied by the reduced rate plus its add-on, plus `paid_count` multiplied by the paid rate plus its add-on, all in whole cents."
        PRD §3.7: "the add-on is the row's `performance_addon_cents` when the site is performance-based certified and 0 otherwise."

        One FREE, one REDUCED, one PAID at a performance-certified site:
        1*(425+8) + 1*(385+8) + 1*(55+8) = 889.

        Design: Difficulty/combinatorial_formula/reimbursement_amount_tiered_conditional_addon
        """
        scenario = setup_three_category_claim(api, performance_certified=True)
        resp = api.submit_claim(scenario["claim_id"], make_director_headers("dir_submit"),
                                {"expected_claim_version": scenario["claim_version"]})
        data = validate_success(resp, 200)
        assert data["estimated_reimbursement_cents"] == 889, f"got {data['estimated_reimbursement_cents']}"

    def test_claim_counts_reflect_one_meal_per_category(self, api):
        """PRD §3.7: "The counts are `free_count`, `reduced_count`, and `paid_count` — respectively the number of reimbursable, non-voided meal transactions in the claim month whose `claim_category` is `FREE`, `REDUCED`, or `PAID`."

        Design: Difficulty/combinatorial_formula/reimbursement_amount_tiered_conditional_addon
        """
        scenario = setup_three_category_claim(api, performance_certified=True)
        resp = api.submit_claim(scenario["claim_id"], make_director_headers("dir_submit"),
                                {"expected_claim_version": scenario["claim_version"]})
        data = validate_success(resp, 200)
        assert data["free_count"] == 1, f"got {data['free_count']}"
        assert data["reduced_count"] == 1, f"got {data['reduced_count']}"
        assert data["paid_count"] == 1, f"got {data['paid_count']}"


# ==========================================================================
# Dual-variant calc: estimated (snapshot at submit) vs final (recomputed at pay)
# ==========================================================================
class TestEstimatedVersusFinalReimbursement:
    def _submit_void_paid_then_mark_paid(self, api):
        scenario = setup_three_category_claim(api, performance_certified=True)
        submit = validate_success(
            api.submit_claim(scenario["claim_id"], make_director_headers("dir_submit"),
                             {"expected_claim_version": scenario["claim_version"]}), 200)
        # Void the PAID meal AFTER submit -> lowers the count that mark-paid will read.
        validate_success(api.void_meal_transaction(scenario["meal_ids"]["PAID"], CLERK), 200)
        paid = validate_success(api.mark_paid_claim(scenario["claim_id"], ADMIN), 200)
        return submit, paid

    def test_final_reimbursement_excludes_meal_voided_after_submit(self, api):
        """PRD §3.7: "Finally, a `PlatformAdmin` marks a submitted claim paid, advancing it from `SUBMITTED` to the terminal `PAID` state; this computes the **final** reimbursement into `final_reimbursement_cents` from the counts as of payment time and increments `version` by one."
        PRD §3.7: "Because meals voided after submission lower the counts, the final figure is at most the earlier estimate — the `final_reimbursement_cents` remains null until the claim is `PAID`."

        After voiding the PAID meal: 1*(425+8) + 1*(385+8) + 0*(55+8) = 826.

        Design: Difficulty/dual_variant_calc/estimated_vs_final_reimbursement_on_claim
        """
        _submit, paid = self._submit_void_paid_then_mark_paid(api)
        assert paid["final_reimbursement_cents"] == 826, f"got {paid['final_reimbursement_cents']}"

    def test_estimate_and_final_diverge_across_the_void(self, api):
        """PRD §3.7: "On success the server records the submitter in `submitted_by_user_id`, computes the **estimated** reimbursement into `estimated_reimbursement_cents` from the counts as of submission time, and increments the claim's `version` by one."
        PRD §3.7: "Because meals voided after submission lower the counts, the final figure is at most the earlier estimate".

        Design: Difficulty/dual_variant_calc/estimated_vs_final_reimbursement_on_claim
        """
        submit, paid = self._submit_void_paid_then_mark_paid(api)
        assert submit["estimated_reimbursement_cents"] == 889
        assert paid["final_reimbursement_cents"] == 826
        assert submit["estimated_reimbursement_cents"] != paid["final_reimbursement_cents"]


# ==========================================================================
# Non-linear state machine: the SUBMITTED -> DRAFT recall cycle
# ==========================================================================
class TestClaimRecallCycle:
    def test_submit_advances_draft_claim_to_submitted(self, api):
        """PRD §3.7: "Submitting a claim advances it from `DRAFT` to `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/reimbursement_claim_recall_cycle
        """
        site = create_site(api)
        claim = create_claim(api, site["id"], claim_month="2026-04", creator_user_id="dir_create")
        resp = api.submit_claim(claim["id"], make_director_headers("dir_submit"),
                                {"expected_claim_version": claim["version"]})
        data = validate_success(resp, 200)
        assert data["status"] == "SUBMITTED", f"got {data['status']}"

    def test_recall_reverts_submitted_claim_to_draft_and_clears_submitter(self, api):
        """PRD §3.7: "A submitted claim may be recalled by a `NutritionDirector`, reverting it from `SUBMITTED` back to `DRAFT`; recall clears `submitted_by_user_id` and increments `version` by one, reopening the claim so that late meals can be captured before it is resubmitted."

        Design: Difficulty/non_linear_state_machine/reimbursement_claim_recall_cycle
        """
        site = create_site(api)
        claim = create_claim(api, site["id"], claim_month="2026-04", creator_user_id="dir_create")
        submitted = validate_success(
            api.submit_claim(claim["id"], make_director_headers("dir_submit"),
                             {"expected_claim_version": claim["version"]}), 200)
        resp = api.recall_claim(claim["id"], make_director_headers("dir_submit"))
        data = validate_success(resp, 200)
        assert data["status"] == "DRAFT", f"got {data['status']}"
        assert data.get("submitted_by_user_id") in (None, ""), (
            f"submitted_by_user_id must be cleared on recall, got {data.get('submitted_by_user_id')!r}")
        assert submitted["status"] == "SUBMITTED"


# ==========================================================================
# Corner: claim breadth claims
# ==========================================================================
def test_stale_claim_version_submit_rejected(api):
    """PRD §2.7: "If `expected_claim_version` does not equal the claim's current `version`, the submission is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412)."
    PRD §2.7: "a late meal transaction or a void for the same site and month legitimately recomputes the claim's free, reduced, and paid counts and increments the claim's `version` as a side effect, so a submit still carrying the pre-recompute `expected_claim_version` is working from counts that have since moved and must be refused."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_claim_version_conflict
    """
    scenario = setup_prepared_lunch_site(api, site_overrides={"negative_balance_allowed": True})
    api.create_reimbursement_rate(
        create_reimbursement_rate_payload(program="NSLP", category="PAID", rate_cents=55,
                                          effective_date="2025-07-01"), ADMIN)
    student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
    claim = create_claim(api, scenario["site_id"], claim_month="2026-04", creator_user_id="dir_create")
    stale_version = claim["version"]
    # A late reimbursable meal for the same month bumps the DRAFT claim's version.
    record_reimbursable_lunch(api, scenario, student["id"])

    resp = api.submit_claim(claim["id"], make_director_headers("dir_submit"),
                            {"expected_claim_version": stale_version})
    validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION.value)


def test_submit_claim_without_applicable_rate_returns_rate_not_found(api):
    """PRD §3.7: "If no applicable rate row exists for a needed program-and-category pairing, the computation is refused with `ERR_RATE_NOT_FOUND` (409)."

    Design: Corner/errors/submit_claim_missing_rate_returns_rate_not_found
    """
    # No reimbursement rates are ever seeded in this scenario.
    scenario = setup_prepared_lunch_site(api, site_overrides={"negative_balance_allowed": True})
    student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
    record_reimbursable_lunch(api, scenario, student["id"])  # one reimbursable PAID lunch
    claim = create_claim(api, scenario["site_id"], claim_month="2026-04", creator_user_id="dir_create")

    resp = api.submit_claim(claim["id"], make_director_headers("dir_submit"),
                            {"expected_claim_version": claim["version"]})
    validate_error(resp, ApiErrorId.ERR_RATE_NOT_FOUND.value)


def test_duplicate_claim_same_month_rejected(api):
    """PRD §3.7: "At most one claim may exist per site and month; a duplicate is refused with `ERR_CLAIM_ALREADY_EXISTS` (409)."

    Design: Corner/validations/duplicate_claim_same_month_rejected
    """
    site = create_site(api)
    create_claim(api, site["id"], claim_month="2026-04", creator_user_id="dir_create")
    resp = api.create_reimbursement_claim(
        {"site_id": site["id"], "claim_month": "2026-04"}, make_director_headers("dir_create"))
    validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_EXISTS.value)
