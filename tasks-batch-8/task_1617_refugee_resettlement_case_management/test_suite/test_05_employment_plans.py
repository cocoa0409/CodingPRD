"""Employment plans (PRD §2.6, §3.5): the dual-variant self-sufficiency
determination, the tiered threshold boundary, OCC on plan creation, the
supersede-on-create rule, and immediate read-after-write.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    date_part,
    setup_arrived_case, get_case, set_clock,
    make_employment_plan, patch_employment_plan, certify_employment_plan,
    list_employment_plans,
)
from test_helpers.fixtures import ES


def _arrived_case_with_plan(case_number, household_size=1, members=(),
                            monthly_income_cents=None,
                            trailing_3m_income_cents=None,
                            employed_members_count=None):
    """Arrived case + ACTIVE employment plan (OCC-satisfied), optionally
    patched with income figures."""
    ctx = setup_arrived_case(case_number=case_number,
                             household_size=household_size, members=members)
    plan = make_employment_plan(ctx["case"]["id"])
    patch = {}
    if monthly_income_cents is not None:
        patch["monthly_income_cents"] = monthly_income_cents
    if trailing_3m_income_cents is not None:
        patch["trailing_3m_income_cents"] = trailing_3m_income_cents
    if employed_members_count is not None:
        patch["employed_members_count"] = employed_members_count
    if patch:
        plan = patch_employment_plan(plan["id"], **patch)
    return ctx, plan


_WORK_ELIGIBLE_ADULT = [{"full_name": "Adult", "date_of_birth": "1990-01-01",
                         "relationship": "PRINCIPAL", "work_eligible": True}]


class TestSelfSufficiencyVariantDivergence:
    def test_monthly_passes_at_same_income_where_annualized_fails(self, api):
        """PRD §3.5: "The two variants can legitimately disagree: a recently
        hired household may pass `MONTHLY` while failing `ANNUALIZED`, and a
        household whose income has just collapsed may show the reverse." and
        "When the determination passes, the plan moves `ACTIVE → CERTIFIED`
        with `self_sufficient` true, the used variant recorded in
        `determination_variant`, and `certified_on` stamped from the logical
        clock". (MONTHLY: 200000 - 20000 = 180000 >= 130000 + 45000 =
        175000; ANNUALIZED: 400000 - 60000 = 340000 < 3 * 175000 = 525000.)

        Design: Difficulty/dual_variant_calc/self_sufficiency_variant_divergence
        """
        set_clock("2026-08-15T09:00:00Z")
        ctx_a, plan_a = _arrived_case_with_plan(
            "CASE-DV2A", household_size=2, members=_WORK_ELIGIBLE_ADULT,
            monthly_income_cents=200000, trailing_3m_income_cents=400000,
            employed_members_count=1)
        ctx_b, plan_b = _arrived_case_with_plan(
            "CASE-DV2B", household_size=2, members=_WORK_ELIGIBLE_ADULT,
            monthly_income_cents=200000, trailing_3m_income_cents=400000,
            employed_members_count=1)
        result_a = certify_employment_plan(plan_a["id"], "MONTHLY")
        result_b = certify_employment_plan(plan_b["id"], "ANNUALIZED")
        assert result_a["self_sufficient"] is True
        assert result_a["status"] == "CERTIFIED"
        assert result_b["self_sufficient"] is False
        assert result_b["status"] == "ACTIVE"

    def test_certify_records_variant_and_certified_on(self, api):
        """PRD §3.5: "When the determination passes, the plan moves `ACTIVE →
        CERTIFIED` with `self_sufficient` true, the used variant recorded in
        `determination_variant`, and `certified_on` stamped from the logical
        clock; `CERTIFIED` is terminal. When it fails, the plan remains
        `ACTIVE` with `self_sufficient` false and `determination_variant`
        still recorded".

        Design: Difficulty/dual_variant_calc/self_sufficiency_variant_divergence
        """
        set_clock("2026-08-15T09:00:00Z")
        _, plan_a = _arrived_case_with_plan(
            "CASE-DV2C", household_size=2, members=_WORK_ELIGIBLE_ADULT,
            monthly_income_cents=200000, trailing_3m_income_cents=400000,
            employed_members_count=1)
        _, plan_b = _arrived_case_with_plan(
            "CASE-DV2D", household_size=2, members=_WORK_ELIGIBLE_ADULT,
            monthly_income_cents=200000, trailing_3m_income_cents=400000,
            employed_members_count=1)
        passed = certify_employment_plan(plan_a["id"], "MONTHLY")
        assert passed["determination_variant"] == "MONTHLY"
        assert date_part(passed["certified_on"]) == "2026-08-15"
        failed = certify_employment_plan(plan_b["id"], "ANNUALIZED")
        assert failed["determination_variant"] == "ANNUALIZED"
        assert failed["certified_on"] is None


class TestSelfSufficiencyTieredThresholdBoundary:
    def test_effective_income_exactly_at_threshold_passes(self, api):
        """PRD §3.5: "The threshold depends on the case's `household_size`:
        the monthly threshold in cents is a base of 130000 (that is,
        $1,300.00) plus 45000 ($450.00) for each household member beyond the
        first." and "All comparisons are integer cents with an inclusive
        boundary — exactly at threshold passes." (Size 4: threshold
        130000 + 3 * 45000 = 265000; effective 285000 - 20000 = 265000.)

        Design: Difficulty/combinatorial_formula/self_sufficiency_tiered_threshold_boundary
        """
        _, plan = _arrived_case_with_plan(
            "CASE-CF1P", household_size=4, members=_WORK_ELIGIBLE_ADULT,
            monthly_income_cents=285000, employed_members_count=1)
        result = certify_employment_plan(plan["id"], "MONTHLY")
        assert result["self_sufficient"] is True
        assert result["status"] == "CERTIFIED"

    def test_effective_income_below_threshold_fails(self, api):
        """PRD §3.5: "Under the `MONTHLY` variant — the current-month
        run-rate test — the earned-income disregard of 20000 cents ($200.00)
        is applied to `monthly_income_cents`: the effective income is the
        monthly income minus the smaller of the monthly income itself and the
        disregard, and the household is self-sufficient when that effective
        income is at least the monthly threshold." (Effective
        270000 - 20000 = 250000 < 265000.)

        Design: Difficulty/combinatorial_formula/self_sufficiency_tiered_threshold_boundary
        """
        _, plan = _arrived_case_with_plan(
            "CASE-CF1Q", household_size=4, members=_WORK_ELIGIBLE_ADULT,
            monthly_income_cents=270000, employed_members_count=1)
        result = certify_employment_plan(plan["id"], "MONTHLY")
        assert result["self_sufficient"] is False
        assert result["status"] == "ACTIVE"


class TestPlanCreateOptimisticConcurrency:
    def test_stale_expected_case_version_rejected(self, api):
        """PRD §2.6: "Creating an employment plan requires the request to
        carry `expected_case_version`, a non-optional integer holding the
        `version` of the target case as the client last observed it. If the
        case's current `version` has advanced past that value — for example
        because another writer has just created a plan (which legitimately
        supersedes the prior `ACTIVE` plan) or recorded the arrival — the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/complexity_layers/plan_create_stale_version_rejected
        """
        ctx = setup_arrived_case(case_number="CASE-CL1", household_size=1)
        case_id = ctx["case"]["id"]
        observed = get_case(case_id, headers=ES)["version"]
        first = validate_success(api.create_employment_plan(
            {"case_id": case_id, "expected_case_version": observed}, ES), 201)
        assert first["status"] == "ACTIVE"
        resp = api.create_employment_plan(
            {"case_id": case_id, "expected_case_version": observed}, ES)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestPlanCreateSupersedesActive:
    def test_second_create_supersedes_first(self, api):
        """PRD §3.5: "it supersedes any existing `ACTIVE` plan for the same
        case — the prior plan moves `ACTIVE` → `SUPERSEDED` automatically, so
        at most one plan is ever `ACTIVE` per case."

        Design: Corner/complexity_layers/plan_create_supersedes_active
        """
        ctx = setup_arrived_case(case_number="CASE-CL2", household_size=1)
        case_id = ctx["case"]["id"]
        v0 = get_case(case_id, headers=ES)["version"]
        plan_a = validate_success(api.create_employment_plan(
            {"case_id": case_id, "expected_case_version": v0}, ES), 201)
        v1 = get_case(case_id, headers=ES)["version"]
        plan_b = validate_success(api.create_employment_plan(
            {"case_id": case_id, "expected_case_version": v1}, ES), 201)
        assert plan_b["status"] == "ACTIVE"
        plans = list_employment_plans(case_id, headers=ES)
        by_id = {p["id"]: p for p in plans}
        assert by_id[plan_a["id"]]["status"] == "SUPERSEDED"
        assert by_id[plan_b["id"]]["status"] == "ACTIVE"

    def test_each_plan_create_increments_case_version(self, api):
        """PRD §3.5: "Creation also increments the case's `version` by 1,
        which is precisely why the OCC check exists: two specialists working
        from the same stale case read must not both create plans."

        Design: Corner/complexity_layers/plan_create_supersedes_active
        """
        ctx = setup_arrived_case(case_number="CASE-CL2B", household_size=1)
        case_id = ctx["case"]["id"]
        v0 = get_case(case_id, headers=ES)["version"]
        validate_success(api.create_employment_plan(
            {"case_id": case_id, "expected_case_version": v0}, ES), 201)
        v1 = get_case(case_id, headers=ES)["version"]
        validate_success(api.create_employment_plan(
            {"case_id": case_id, "expected_case_version": v1}, ES), 201)
        assert get_case(case_id, headers=ES)["version"] == v0 + 2


class TestPlanPatchImmediateConsistency:
    def test_patch_visible_in_response(self, api):
        """PRD §3.5: "The specialist maintains the income picture on the
        `ACTIVE` plan by patching any subset of `monthly_income_cents` (gross
        monthly household earned income in cents, zero or more)". PRD §2.2:
        "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/plan_patch_immediately_visible
        """
        _, plan = _arrived_case_with_plan("CASE-CM1", household_size=1)
        patched = validate_success(api.patch_employment_plan(
            plan["id"], {"monthly_income_cents": 150000,
                         "employed_members_count": 1}, ES))
        assert patched["monthly_income_cents"] == 150000

    def test_patch_visible_in_subsequent_list_read(self, api):
        """PRD §2.8: "derived fields track the world as it is now; snapshot
        fields remember the world as it was at generation." PRD §3.5: "The
        specialist maintains the income picture on the `ACTIVE` plan by
        patching any subset of `monthly_income_cents` (gross monthly
        household earned income in cents, zero or more)".

        Design: Corner/consistency_model/plan_patch_immediately_visible
        """
        ctx, plan = _arrived_case_with_plan("CASE-CM1B", household_size=1)
        patch_employment_plan(plan["id"], monthly_income_cents=150000,
                              employed_members_count=1)
        plans = list_employment_plans(ctx["case"]["id"], headers=ES)
        target = [p for p in plans if p["id"] == plan["id"]][0]
        assert target["monthly_income_cents"] == 150000
