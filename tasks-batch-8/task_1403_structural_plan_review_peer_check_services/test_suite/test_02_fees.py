"""Fee schedule: estimated vs final variants, tiered valuation, per-item
deferred rounding, minimum floor, and amendment pinning (PRD §2.7, §3.2, §3.7)."""
from test_helpers import (
    TEST_USERS,
    approve_cycle,
    assign_cycle,
    get_engagement,
    get_record_for_engagement,
    issue_comments,
    make_engagement,
    make_jurisdiction,
    make_reviewer,
    make_reviewer_headers,
    open_cycle,
    raise_comment,
    register_deferred,
    respond_to_comment,
    setup_approved_engagement,
    setup_in_review_cycle,
    setup_registered_engagement,
    submit_deferred,
    approve_deferred,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _seal(api, record_id, reviewer_id):
    return api.seal_record(record_id, make_reviewer_headers(reviewer_id))


class TestEstimatedVsFinalDivergence:
    def _setup_two_cycles_sealed(self, api):
        """Valuation 30000000, free_resubmittal_cycles=0; two cycles; sealed."""
        jur = make_jurisdiction(state_code="CA", fee_method="VALUATION",
                                turnaround_days=15, sla_mode="BUSINESS",
                                free_resubmittal_cycles=0)
        rev = make_reviewer(name="R One", state_code="CA",
                            max_concurrent_assignments=3)
        eng = make_engagement(jur, rev, project_name="Fee Divergence",
                              declared_valuation_cents=30_000_000,
                              floor_area_sqft=10_000, requested_expedite=False)
        cyc1 = open_cycle(eng["id"], documents_ref="s3://plans-v1")
        assign_cycle(cyc1, rev["id"])
        com1 = raise_comment(cyc1["id"], rev["id"],
                             code_section_ref="1604.3",
                             comment_text="Wind load calc incomplete")
        issue_comments(cyc1["id"], rev["id"])
        respond_to_comment(com1["id"], response_text="Calc revised, see sheet S2.1")
        cyc2 = open_cycle(eng["id"], documents_ref="s3://plans-v2")
        assign_cycle(cyc2, rev["id"])
        api.verify_comment(com1["id"], make_reviewer_headers(rev["id"]))
        approve_cycle(cyc2["id"], rev["id"])
        rec = get_record_for_engagement(eng["id"])
        resp = _seal(api, rec["id"], rev["id"])
        validate_success(resp, 200)
        return eng["id"]

    def test_estimated_fee_registration_variant_zero_resubmittal(self, api):
        """PRD §3.2: "The `estimated_fee_cents` recorded on the engagement is
        the scoped base plus the expedite component. Because registration
        implies zero cycles used and no deferred items, the resubmittal and
        deferred components described in §3.7 are always zero here."
        PRD §3.2: "Under the `VALUATION` fee method, the base fee tiers the
        declared valuation: the portion up to one hundred thousand dollars is
        priced at one percent; the portion above one hundred thousand dollars,
        up to a cumulative five hundred thousand dollars, at three-quarters of
        one percent; and any remainder above five hundred thousand dollars at
        one-half of one percent."

        Design: Difficulty/dual_variant_calc/fee_estimated_vs_final_diverge_on_extra_cycles
        """
        eng_id = self._setup_two_cycles_sealed(api)
        eng = get_engagement(eng_id)
        # base = 100000 + 30000000... tier math: 1e7*0.01 + 2e7*0.0075 = 250000
        assert eng["estimated_fee_cents"] == 250_000
        assert eng["cycle_count"] == 2

    def test_final_fee_includes_resubmittal_component(self, api):
        """PRD §3.7: "The resubmittal component charges seventy-five thousand
        cents for every cycle beyond the free allowance: the engagement's
        `cycle_count` minus its `pinned_free_resubmittal_cycles`, floored at
        zero, multiplied by 75,000."
        PRD §3.7: "It diverges from the estimate whenever cycles exceeded the
        free allowance, deferred items were approved, or the fee inputs were
        amended."

        Design: Difficulty/dual_variant_calc/fee_estimated_vs_final_diverge_on_extra_cycles
        """
        eng_id = self._setup_two_cycles_sealed(api)
        eng = get_engagement(eng_id)
        # 250000 scoped + 75000 * (2 - 0) resubmittal = 400000
        assert eng["final_fee_cents"] == 400_000
        assert eng["final_fee_cents"] != eng["estimated_fee_cents"]


class TestTierCrossingWithScopeAndExpedite:
    def _setup(self, api):
        jur = make_jurisdiction(state_code="NV", ibc_edition="IBC_2024",
                                fee_method="VALUATION", turnaround_days=15,
                                sla_mode="CALENDAR", free_resubmittal_cycles=2)
        rev = make_reviewer(name="R Three", state_code="NV", license_type="SE")
        eng = make_engagement(jur, rev, project_name="Tier Crossing",
                              building_type="ESSENTIAL_FACILITY",
                              risk_category="IV", scope="PEER_REVIEW",
                              declared_valuation_cents=100_000_000,
                              floor_area_sqft=20_000, requested_expedite=True)
        cyc = open_cycle(eng["id"], documents_ref="s3://peer-v1")
        assign_cycle(cyc, rev["id"])
        approve_cycle(cyc["id"], rev["id"])
        rec = get_record_for_engagement(eng["id"])
        validate_success(_seal(api, rec["id"], rev["id"]), 200)
        return eng["id"]

    def test_estimated_fee_crosses_all_tiers_with_scope_and_expedite(self, api):
        """PRD §3.2: "The scoped base is the base multiplied by the scope
        factor — full rate for `FULL_REVIEW`, sixty percent for `LATERAL_ONLY`,
        eighty percent for `PEER_REVIEW` — rounded half up to whole cents; this
        is the first of the two pinned rounding steps of §2.7. If expedited
        turnaround was requested, an expedite component of half the *rounded*
        scoped base is itself rounded half up to whole cents — the second
        pinned rounding step — and added; otherwise the expedite component is
        zero."

        Design: Difficulty/combinatorial_formula/fee_valuation_tier_crossing_with_scope_and_expedite
        """
        eng = get_engagement(self._setup(api))
        # base = 100000 + 300000 + 250000 = 650000; scoped = 650000*0.8 = 520000;
        # expedite = round(520000*0.5) = 260000
        assert eng["estimated_fee_cents"] == 780_000
        assert eng["status"] == "APPROVED"

    def test_final_fee_equals_estimate_when_within_free_cycles(self, api):
        """PRD §3.7: "The resubmittal component charges seventy-five thousand
        cents for every cycle beyond the free allowance: the engagement's
        `cycle_count` minus its `pinned_free_resubmittal_cycles`, floored at
        zero, multiplied by 75,000."

        Design: Difficulty/combinatorial_formula/fee_valuation_tier_crossing_with_scope_and_expedite
        """
        eng = get_engagement(self._setup(api))
        # cycle_count 1 <= free 2, no deferred items -> no extra components
        assert eng["final_fee_cents"] == 780_000


class TestDeferredPerItemRounding:
    def _setup(self, api):
        """Valuation chosen so scoped base is 333333 cents; two approved
        deferred items make the per-item-then-sum rounding order observable."""
        jur = make_jurisdiction(state_code="WA", asce7_edition="ASCE7_16",
                                fee_method="VALUATION", turnaround_days=15,
                                sla_mode="BUSINESS", free_resubmittal_cycles=2,
                                allows_deferred_submittals=True)
        rev = make_reviewer(name="R Four", state_code="WA")
        eng = make_engagement(jur, rev, project_name="Deferred Rounding",
                              scope="LATERAL_ONLY",
                              declared_valuation_cents=81_111_000,
                              floor_area_sqft=9_000, requested_expedite=False)
        cyc = open_cycle(eng["id"], documents_ref="s3://lat-v1")
        assign_cycle(cyc, rev["id"])
        approve_cycle(cyc["id"], rev["id"])
        d1 = register_deferred(eng["id"], item_type="TRUSS",
                               description="Roof truss package")
        d2 = register_deferred(eng["id"], item_type="ANCHOR",
                               description="Post-installed anchors")
        submit_deferred(d1["id"], documents_ref="s3://truss-calcs")
        submit_deferred(d2["id"], documents_ref="s3://anchor-calcs")
        approve_deferred(d1["id"], rev["id"])
        approve_deferred(d2["id"], rev["id"])
        rec = get_record_for_engagement(eng["id"])
        validate_success(_seal(api, rec["id"], rev["id"]), 200)
        return eng["id"]

    def test_estimated_fee_is_rounded_scoped_base(self, api):
        """PRD §3.2: "The scoped base is the base multiplied by the scope
        factor — full rate for `FULL_REVIEW`, sixty percent for `LATERAL_ONLY`,
        eighty percent for `PEER_REVIEW` — rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/deferred_fee_per_item_rounding_then_sum
        """
        eng = get_engagement(self._setup(api))
        # tiers: 100000 + 300000 + (81111000-50000000)*0.005 = 555555;
        # scoped = 555555 * 0.6 = 333333
        assert eng["estimated_fee_cents"] == 333_333
        assert eng["deferred_pending_count"] == 0

    def test_deferred_component_rounds_per_item_then_sums(self, api):
        """PRD §3.7: "The deferred component charges, for each deferred
        submittal of the engagement currently `APPROVED`, five percent of the
        rounded scoped base — each per-item fee rounded half up to whole cents
        *first*, and the rounded per-item fees then summed; this
        per-item-then-sum order is pinned and observable."

        Design: Difficulty/combinatorial_formula/deferred_fee_per_item_rounding_then_sum
        """
        eng = get_engagement(self._setup(api))
        # per item: round_half_up(333333 * 0.05) = 16667; two items -> 33334.
        # Sum-then-round would give 33333; the pinned order yields 366667.
        assert eng["final_fee_cents"] == 366_667


class TestMinimumFeeFloor:
    def test_sqft_fee_minimum_floor_applied(self, api):
        """PRD §3.2: "Either way, the base is then raised to a
        five-hundred-dollar minimum if it falls short."
        PRD §3.2: "Under the `SQUARE_FOOTAGE` method, the base fee is the gross
        floor area multiplied by the per-square-foot rate for the building type
        — 40 cents for `RESIDENTIAL`, 55 for `COMMERCIAL`, 45 for `INDUSTRIAL`,
        and 70 for `ESSENTIAL_FACILITY`."

        Design: Corner/calculations/sqft_fee_minimum_floor_applied
        """
        jur = make_jurisdiction(state_code="CA", fee_method="SQUARE_FOOTAGE",
                                turnaround_days=10, sla_mode="CALENDAR")
        rev = make_reviewer(state_code="CA")
        eng = make_engagement(jur, rev, project_name="Tiny",
                              building_type="RESIDENTIAL", risk_category="I",
                              declared_valuation_cents=100_000,
                              floor_area_sqft=500)
        # 500 sqft x 40 = 20000 < 50000 floor
        assert eng["estimated_fee_cents"] == 50_000


class TestEstimatedFeeSurvivesAmendment:
    def _setup(self, api):
        bundle = setup_registered_engagement(
            eng_overrides={"project_name": "Amend",
                           "declared_valuation_cents": 30_000_000})
        eng = bundle["engagement"]
        rev = bundle["reviewer"]
        resp = api.update_engagement(
            eng["id"], {"declared_valuation_cents": 50_000_000}, COORD)
        validate_success(resp, 200)
        cyc = open_cycle(eng["id"], documents_ref="s3://amend-v1")
        assign_cycle(cyc, rev["id"])
        approve_cycle(cyc["id"], rev["id"])
        rec = get_record_for_engagement(eng["id"])
        validate_success(_seal(api, rec["id"], rev["id"]), 200)
        return eng["id"]

    def test_estimated_fee_survives_amendment(self, api):
        """PRD §3.2: "Registration is also when the **estimated fee** is
        computed, and it is never recomputed afterwards, even if valuation,
        area, or expedite are later amended."
        PRD §3.2: "Amendments matter at seal time: the final fee of §3.7 reads
        the *current*, possibly amended, values — one of the two reasons the
        final fee can diverge from the estimate."

        Design: Corner/calculations/estimated_fee_survives_amendment
        """
        eng = get_engagement(self._setup(api))
        assert eng["estimated_fee_cents"] == 250_000
        # amended valuation 50000000 -> base 100000 + 300000 = 400000;
        # 1 cycle <= 2 free, no deferred items
        assert eng["final_fee_cents"] == 400_000
