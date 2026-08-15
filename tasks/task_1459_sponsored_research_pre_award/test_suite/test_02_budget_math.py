"""Budget construction, finalization math, and rate selection (PRD §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    add_budget_line,
    assert_budget_line,
    assert_budget_snapshot,
    assert_proposal,
    assert_proposal_invariants,
    create_budget_line_payload,
    create_proposal_payload,
    finalize_budget,
    get_proposal,
    get_success_data,
    get_version,
    make_context,
    make_locked_proposal,
    make_opportunity,
    make_org,
    make_pi,
    make_pi_headers,
    make_proposal,
    make_rate_agreement,
    make_sub_commitment,
    reset_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]


def _draft_with_ctx(ctx, **overrides):
    return make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], **overrides)


class TestDualVariantMtdcVsTdc:
    """Same five lines, same 54% rate; MTDC and TDC diverge (PRD §3.3)."""

    def _setup_pair(self, api):
        reset_clock()
        ctx = make_context()
        org = make_org(legal_name="Sub U", uei="UEI-AAA1")
        lines = [
            dict(category="PERSONNEL", description="salary", fiscal_year=2027,
                 amount_cents=10_000_000),
            dict(category="EQUIPMENT", description="scope", fiscal_year=2027,
                 amount_cents=4_000_000),
            dict(category="SUBAWARD", description="sub yr1", fiscal_year=2027,
                 amount_cents=3_000_000),
            dict(category="SUBAWARD", description="sub yr2", fiscal_year=2028,
                 amount_cents=1_000_000),
            dict(category="TRAVEL", description="travel", fiscal_year=2027,
                 amount_cents=500_000),
        ]
        snaps = {}
        for tag, base, start, end, fy_shift in (
            ("A", "MTDC", "2026-09-01", "2027-08-31", 0),
            ("B", "TDC", "2027-09-01", "2028-08-31", 1),
        ):
            prop = make_proposal(
                ctx["opp"]["id"], ctx["pi"]["id"], title=tag,
                project_start_on=start, project_end_on=end, fa_base_type=base,
            )
            comm = make_sub_commitment(
                prop["id"], org["id"], subaward_amount_cents=4_000_000,
            )
            for spec in lines:
                payload = dict(spec)
                payload["fiscal_year"] = spec["fiscal_year"] + fy_shift
                if payload["category"] == "SUBAWARD":
                    payload["subrecipient_commitment_id"] = comm["id"]
                add_budget_line(prop["id"], **payload)
            snaps[tag] = finalize_budget(prop["id"])
        return snaps

    def test_mtdc_variant_totals(self, api):
        """PRD §3.3: "Under the `MTDC` variant, lines in `EQUIPMENT`, `TUITION`,
        or `PARTICIPANT_SUPPORT` contribute a base portion of zero; each
        `SUBAWARD` line contributes the lesser of its own `amount_cents` and the
        remaining MTDC allowance of its `subrecipient_commitment_id`, where each
        commitment's allowance is the first $25,000 (2500000 cents) of cumulative
        subaward amounts consumed in processing order; every other category
        contributes its full `amount_cents`."

        Design: Difficulty/dual_variant_calc/indirect_cost_mtdc_vs_tdc
        """
        snap_a = self._setup_pair(api)["A"]
        assert_budget_snapshot(snap_a)
        assert snap_a["mtdc_base_cents"] == 13_000_000
        assert snap_a["total_direct_cents"] == 18_500_000
        assert snap_a["total_indirect_cents"] == 7_020_000
        assert snap_a["total_request_cents"] == 25_520_000

    def test_tdc_variant_totals(self, api):
        """PRD §3.3: "Under the `TDC` variant every non-cost-share line
        contributes its full `amount_cents` — no exclusions, no subaward cap."
        and "the `mtdc_base_cents` eligible base, which under `TDC` simply equals
        `total_direct_cents`".

        Design: Difficulty/dual_variant_calc/indirect_cost_mtdc_vs_tdc
        """
        snaps = self._setup_pair(api)
        snap_b = snaps["B"]
        assert snap_b["mtdc_base_cents"] == 18_500_000
        assert snap_b["total_indirect_cents"] == 9_990_000
        assert snap_b["total_request_cents"] == 28_490_000
        # Identical line amounts, different variant -> different indirect
        assert snaps["A"]["total_indirect_cents"] != snap_b["total_indirect_cents"]


class TestPerLineRounding:
    def _finalize_two_penny_lines(self, api):
        reset_clock()
        opp = make_opportunity(
            sponsor_code="DOE", title="OR",
            activity_codes_allowed=["OTHER_SPONSORED"],
        )
        pi = make_pi(full_name="P Two", department_code="PHY")
        make_rate_agreement(rate_type="OTHER_SPONSORED", rate_pct=50.00)
        prop = make_proposal(
            opp["id"], pi["id"], title="R", activity_code="OTHER_SPONSORED",
            pi_effort_pct=10.00, fa_base_type="TDC",
        )
        add_budget_line(prop["id"], category="OTHER_DIRECT", description="a",
                        amount_cents=1)
        add_budget_line(prop["id"], category="OTHER_DIRECT", description="b",
                        amount_cents=1)
        return finalize_budget(prop["id"])

    def test_total_indirect_rounds_per_line_then_sums(self, api):
        """PRD §2.6: "Indirect cost is rounded half up to whole cents **per
        budget line first**, and only then are the per-line results summed into
        the proposal's indirect total; summing unrounded products and rounding
        once at the end yields a different number and is not the specification."

        Design: Difficulty/combinatorial_formula/indirect_cost_per_line_rounding
        """
        snap = self._finalize_two_penny_lines(api)
        assert snap["total_direct_cents"] == 2
        # round_half_up(1 * 50/100) = 1 per line, twice -> 2 (sum-then-round = 1)
        assert snap["total_indirect_cents"] == 2
        assert snap["total_request_cents"] == 4

    def test_per_line_indirect_entries(self, api):
        """PRD §3.3: "`per_line_indirect`, an array of entries each naming a
        `budget_line_id`, its `base_portion_cents`, and its `indirect_cents`,
        recorded in the pinned processing order." PRD §2.6: "Indirect cost is
        rounded half up to whole cents **per budget line first**, and only then
        are the per-line results summed".

        Design: Difficulty/combinatorial_formula/indirect_cost_per_line_rounding
        """
        snap = self._finalize_two_penny_lines(api)
        entries = snap["per_line_indirect"]
        assert len(entries) == 2
        for entry in entries:
            assert entry["base_portion_cents"] == 1
            assert entry["indirect_cents"] == 1
        assert sum(e["indirect_cents"] for e in entries) == snap["total_indirect_cents"]


class TestSubawardAllowanceBoundary:
    def _finalize_single_subaward(self, api, ctx, org, amount, title):
        prop = make_proposal(
            ctx["opp"]["id"], ctx["pi"]["id"], title=title,
            pi_effort_pct=10.00, fa_base_type="MTDC",
        )
        comm = make_sub_commitment(
            prop["id"], org["id"], subaward_amount_cents=amount,
        )
        add_budget_line(
            prop["id"], category="SUBAWARD", description="sub",
            amount_cents=amount, subrecipient_commitment_id=comm["id"],
        )
        return finalize_budget(prop["id"])

    def test_allowance_exact_amount_counts_in_full(self, api):
        """PRD §3.3: "each `SUBAWARD` line contributes the lesser of its own
        `amount_cents` and the remaining MTDC allowance of its
        `subrecipient_commitment_id`, where each commitment's allowance is the
        first $25,000 (2500000 cents) of cumulative subaward amounts consumed in
        processing order".

        Design: Corner/calculations/subaward_mtdc_allowance_exact_boundary
        """
        reset_clock()
        ctx = make_context()
        org = make_org(legal_name="Cap", uei="UEI-CAP1")
        snap = self._finalize_single_subaward(api, ctx, org, 2_500_000, "X")
        assert snap["mtdc_base_cents"] == 2_500_000
        assert snap["total_indirect_cents"] == 1_350_000
        assert snap["total_direct_cents"] == 2_500_000

    def test_one_cent_over_allowance_capped(self, api):
        """PRD §3.3: "each `SUBAWARD` line contributes the lesser of its own
        `amount_cents` and the remaining MTDC allowance of its
        `subrecipient_commitment_id`, where each commitment's allowance is the
        first $25,000 (2500000 cents) of cumulative subaward amounts consumed in
        processing order".

        Design: Corner/calculations/subaward_mtdc_allowance_exact_boundary
        """
        reset_clock()
        ctx = make_context()
        org = make_org(legal_name="Cap", uei="UEI-CAP2")
        snap = self._finalize_single_subaward(api, ctx, org, 2_500_001, "Y")
        # Allowance caps the IDC base at exactly 2500000; direct total is untouched
        assert snap["mtdc_base_cents"] == 2_500_000
        assert snap["total_indirect_cents"] == 1_350_000
        assert snap["total_direct_cents"] == 2_500_001


class TestCostShareLineExclusion:
    def test_cost_share_lines_excluded_from_totals(self, api):
        """PRD §3.3: "A line flagged `is_cost_share` (default false) is
        institutional contribution rather than sponsor request: such lines are
        excluded from the direct-cost totals and from the indirect-cost base."

        Design: Corner/calculations/cost_share_lines_excluded_from_request_totals
        """
        reset_clock()
        ctx = make_context()
        prop = _draft_with_ctx(ctx, title="Excl", pi_effort_pct=10.00)
        add_budget_line(prop["id"], amount_cents=10_000_000)
        add_budget_line(prop["id"], category="MATERIALS",
                        description="institutional share", amount_cents=5_000_000,
                        is_cost_share=True)
        snap = finalize_budget(prop["id"])
        assert snap["total_direct_cents"] == 10_000_000
        assert snap["total_indirect_cents"] == 5_400_000
        assert snap["total_request_cents"] == 15_400_000


class TestRateSelection:
    def test_final_preferred_over_provisional(self, api):
        """PRD §3.2: "At budget-finalization time (the provisional basis), the
        server prefers a `FINAL` agreement of the resolved type whose window
        contains `project_start_on`, falling back to a `PROVISIONAL` one".

        Design: Corner/calculations/rate_selection_prefers_final_over_provisional
        """
        reset_clock()
        opp = make_opportunity()
        pi = make_pi()
        make_rate_agreement(rate_pct=50.00)  # PROVISIONAL
        make_rate_agreement(rate_pct=54.00, initial_status="FINAL")
        prop = make_proposal(opp["id"], pi["id"], title="Pref", pi_effort_pct=10.00)
        add_budget_line(prop["id"], amount_cents=10_000_000)
        snap = finalize_budget(prop["id"])
        assert snap["applied_rate_pct"] == 54.0
        assert snap["rate_source"] == "FINAL_RATE"
        assert snap["total_indirect_cents"] == 5_400_000

    def test_no_applicable_rate_rejected(self, api):
        """PRD §3.2: "when neither covers the start date, finalization fails with
        `ERR_NO_APPLICABLE_RATE` (HTTP 422)."

        Design: Corner/calculations/no_applicable_rate_rejected
        """
        reset_clock()
        ctx = make_context()
        prop = make_proposal(
            ctx["opp"]["id"], ctx["pi"]["id"], title="NoRate",
            project_start_on="2030-01-01", project_end_on="2030-12-31",
            pi_effort_pct=10.00,
        )
        add_budget_line(prop["id"], fiscal_year=2030, amount_cents=10_000_000)
        resp = api.create_budget_finalization(
            prop["id"], {"expected_proposal_version": get_version(prop["id"])},
            TEST_USERS["analyst_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_APPLICABLE_RATE.value)


class TestRateCap:
    def _finalize_off_campus(self, api, opp_id, pi_id, rate_pct, window,
                             start, end, title, fy):
        prop = make_proposal(
            opp_id, pi_id, title=title, activity_code="RESEARCH_OFF_CAMPUS",
            project_start_on=start, project_end_on=end, fa_base_type="TDC",
        )
        add_budget_line(prop["id"], fiscal_year=fy, amount_cents=10_000_000)
        return finalize_budget(prop["id"])

    def test_selected_rate_clamped_at_cap(self, api):
        """PRD §3.2: "once a rate is selected the applied rate is the lesser of
        the selected rate and the opportunity's `fa_rate_cap_pct` when a cap is
        set — a selected rate exactly equal to the cap is allowed — and is simply
        the selected rate when the opportunity is uncapped."

        Design: Difficulty/boundary_precision_check/fa_rate_cap_boundary
        """
        reset_clock()
        opp = make_opportunity(
            title="C1", activity_codes_allowed=["RESEARCH_OFF_CAMPUS"],
            fa_rate_cap_pct=54.00,
        )
        pi = make_pi(full_name="P Thirteen", department_code="GEOL")
        make_rate_agreement(
            rate_type="OFF_CAMPUS_RESEARCH", rate_pct=56.50,
            effective_start_on="2026-01-01", effective_end_on="2027-01-01",
            initial_status="FINAL",
        )
        snap = self._finalize_off_campus(
            api, opp["id"], pi["id"], 56.50, None,
            "2026-09-01", "2027-08-31", "CapOver", 2027,
        )
        assert snap["selected_rate_pct"] == 56.5
        assert snap["applied_rate_pct"] == 54.0
        assert snap["total_indirect_cents"] == 5_400_000

    def test_selected_rate_equal_to_cap_allowed(self, api):
        """PRD §3.2: "a selected rate exactly equal to the cap is allowed".

        Design: Difficulty/boundary_precision_check/fa_rate_cap_boundary
        """
        reset_clock()
        opp = make_opportunity(
            title="C1", activity_codes_allowed=["RESEARCH_OFF_CAMPUS"],
            fa_rate_cap_pct=54.00,
        )
        pi = make_pi(full_name="P Thirteen", department_code="GEOL")
        make_rate_agreement(
            rate_type="OFF_CAMPUS_RESEARCH", rate_pct=54.00,
            effective_start_on="2027-01-01", effective_end_on="2029-01-01",
            initial_status="FINAL",
        )
        snap = self._finalize_off_campus(
            api, opp["id"], pi["id"], 54.00, None,
            "2027-02-01", "2028-01-31", "CapExact", 2028,
        )
        assert snap["applied_rate_pct"] == 54.0
        assert snap["total_indirect_cents"] == 5_400_000


class TestRequestCap:
    def _setup(self, api):
        reset_clock()
        opp = make_opportunity(
            sponsor_code="DOE", title="Cap",
            activity_codes_allowed=["RESEARCH_OFF_CAMPUS"],
            max_request_cents=10_000_000,
        )
        pi = make_pi(department_code="GEOL")
        make_rate_agreement(rate_type="OFF_CAMPUS_RESEARCH", rate_pct=25.00)
        return opp, pi

    def _proposal_with_line(self, opp_id, pi_id, title, amount):
        prop = make_proposal(
            opp_id, pi_id, title=title, activity_code="RESEARCH_OFF_CAMPUS",
            pi_effort_pct=10.00,
        )
        add_budget_line(prop["id"], amount_cents=amount)
        return prop

    def test_one_cent_over_cap_rejected(self, api):
        """PRD §3.3: "a resulting `total_request_cents` that does not exceed the
        opportunity's `max_request_cents` when one is set
        (`ERR_REQUEST_EXCEEDS_CAP`, 422)".

        Design: Corner/validations/request_cap_boundary
        """
        opp, pi = self._setup(api)
        prop = self._proposal_with_line(opp["id"], pi["id"], "Over", 8_000_001)
        resp = api.create_budget_finalization(
            prop["id"], {"expected_proposal_version": get_version(prop["id"])},
            TEST_USERS["analyst_headers"],
        )
        # request = 8000001 + round_half_up(8000001*25/100)=2000000 -> 10000001 > cap
        validate_error(resp, ApiErrorId.ERR_REQUEST_EXCEEDS_CAP.value)

    def test_request_exactly_at_cap_admitted(self, api):
        """PRD §3.3: "a resulting `total_request_cents` that does not exceed the
        opportunity's `max_request_cents` when one is set
        (`ERR_REQUEST_EXCEEDS_CAP`, 422)" — a request equal to the cap does not
        exceed it and is admitted.

        Design: Corner/validations/request_cap_boundary
        """
        opp, pi = self._setup(api)
        prop = self._proposal_with_line(opp["id"], pi["id"], "Exact", 8_000_000)
        snap = finalize_budget(prop["id"])
        # 8000000 + 25% = 10000000 == cap -> admitted
        assert snap["total_request_cents"] == 10_000_000
        assert snap["status"] == "CURRENT"


class TestEmptyBudget:
    def test_finalize_without_lines_rejected(self, api):
        """PRD §3.3: "Finalization requires at least one non-cost-share line
        (`ERR_EMPTY_BUDGET`, 422)".

        Design: Corner/validations/empty_budget_rejected
        """
        reset_clock()
        ctx = make_context()
        prop = _draft_with_ctx(ctx, title="Empty", pi_effort_pct=10.00)
        resp = api.create_budget_finalization(
            prop["id"], {"expected_proposal_version": prop["version"]},
            TEST_USERS["analyst_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EMPTY_BUDGET.value)

    def test_cost_share_only_budget_still_empty(self, api):
        """PRD §3.3: "Finalization requires at least one non-cost-share line
        (`ERR_EMPTY_BUDGET`, 422)" and "such lines are excluded from the
        direct-cost totals and from the indirect-cost base."

        Design: Corner/validations/empty_budget_rejected
        """
        reset_clock()
        ctx = make_context()
        prop = _draft_with_ctx(ctx, title="EmptyCS", pi_effort_pct=10.00)
        add_budget_line(prop["id"], category="MATERIALS",
                        description="institutional", amount_cents=5_000_000,
                        is_cost_share=True)
        resp = api.create_budget_finalization(
            prop["id"], {"expected_proposal_version": get_version(prop["id"])},
            TEST_USERS["analyst_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EMPTY_BUDGET.value)


class TestBudgetLineRules:
    def test_mtdc_flag_computed_per_category(self, api):
        """PRD §3.3: "Each line's `counts_toward_mtdc` is computed — false for
        `EQUIPMENT`, `TUITION`, and `PARTICIPANT_SUPPORT`; for `SUBAWARD`, true
        only while its commitment's cumulative allowance remains; true for every
        other category."

        Design: Corner/entities/budget_line_mtdc_flag_computed
        """
        ctx = make_context()
        prop = _draft_with_ctx(ctx, title="M", pi_effort_pct=10.00,
                               fa_base_type="MTDC")
        eq = validate_success(
            api.create_budget_line(
                prop["id"],
                create_budget_line_payload(category="EQUIPMENT",
                                           description="scope",
                                           amount_cents=4_000_000),
                TEST_USERS["analyst_headers"],
            ),
            201,
        )
        assert_budget_line(eq)
        assert eq["counts_toward_mtdc"] is False
        pers = validate_success(
            api.create_budget_line(
                prop["id"],
                create_budget_line_payload(description="salary",
                                           amount_cents=1_000_000),
                TEST_USERS["analyst_headers"],
            ),
            201,
        )
        assert pers["counts_toward_mtdc"] is True

    def test_subaward_line_requires_commitment(self, api):
        """PRD §3.3: "A `SUBAWARD` line must name its
        `subrecipient_commitment_id`, tying it to a verified subrecipient plan;
        omitting it is malformed." PRD §2.8: "structurally malformed payloads —
        ... or a `SUBAWARD` line without its `subrecipient_commitment_id` — are
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/subaward_line_without_commitment_rejected
        """
        ctx = make_context()
        prop = _draft_with_ctx(ctx, title="Sub", pi_effort_pct=10.00,
                               fa_base_type="MTDC")
        resp = api.create_budget_line(
            prop["id"],
            create_budget_line_payload(category="SUBAWARD", description="orphan",
                                       amount_cents=1_000_000),
            TEST_USERS["analyst_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_zero_amount_rejected_one_cent_allowed(self, api):
        """PRD §3.3: "an `amount_cents` strictly greater than zero".
        PRD §2.8: "Independently of this ladder, structurally malformed payloads
        — a missing required field, a type mismatch, an unknown enum member, a
        non-positive `amount_cents`, an end date earlier than its start date, or
        a `SUBAWARD` line without its `subrecipient_commitment_id` — are rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/invalid_amount_rejected
        """
        ctx = make_context()
        prop = _draft_with_ctx(ctx, title="Amt", pi_effort_pct=10.00)
        bad = api.create_budget_line(
            prop["id"],
            create_budget_line_payload(category="TRAVEL", description="zero",
                                       amount_cents=0),
            TEST_USERS["analyst_headers"],
        )
        validate_error(bad, ApiErrorId.ERR_INVALID_REQUEST.value)
        ok = api.create_budget_line(
            prop["id"],
            create_budget_line_payload(category="TRAVEL", description="one cent",
                                       amount_cents=1),
            TEST_USERS["analyst_headers"],
        )
        line = validate_success(ok, 201)
        assert line["amount_cents"] == 1


class TestFinalizeSideEffects:
    def test_first_finalize_snapshot_and_proposal(self, api):
        """PRD §3.3: "The snapshot captures everything needed to reproduce the
        numbers: a per-proposal `snapshot_index` ascending from 1; ... Exactly
        one snapshot per proposal is `CURRENT` ... and the proposal copies the
        snapshot's totals onto itself ... From `DRAFT` the proposal becomes
        `BUDGET_LOCKED`".

        Design: Corner/state_machines/finalize_happy_path_side_effects
        """
        reset_clock()
        env = make_locked_proposal()
        snap = env["snapshot"]
        assert_budget_snapshot(snap)
        assert snap["snapshot_index"] == 1
        assert snap["status"] == "CURRENT"
        assert snap["total_request_cents"] == 15_400_000
        prop = env["proposal"]
        assert_proposal(prop)
        assert_proposal_invariants(prop)
        assert prop["status"] == "BUDGET_LOCKED"
        assert prop["total_request_cents"] == 15_400_000
        assert prop["current_snapshot_id"] == snap["id"]

    def test_finalize_response_matches_immediate_reread(self, api):
        """PRD §3.3: "the proposal copies the snapshot's totals onto itself:
        `total_direct_cents`, `total_indirect_cents`, `total_request_cents`,
        `fa_rate_pct_applied`, `applied_rate_source`, and `current_snapshot_id`."

        Design: Corner/consistency_model/finalize_response_matches_immediate_reread
        """
        reset_clock()
        ctx = make_context()
        prop = _draft_with_ctx(ctx, title="Cons")
        add_budget_line(prop["id"], amount_cents=10_000_000)
        add_budget_line(prop["id"], category="TRAVEL", description="t",
                        amount_cents=500_000)
        snap = finalize_budget(prop["id"])
        assert snap["total_direct_cents"] == 10_500_000
        assert snap["total_indirect_cents"] == 5_670_000
        assert snap["total_request_cents"] == 16_170_000
        reread = get_proposal(prop["id"])
        assert reread["total_direct_cents"] == snap["total_direct_cents"]
        assert reread["total_indirect_cents"] == snap["total_indirect_cents"]
        assert reread["total_request_cents"] == snap["total_request_cents"]
        assert reread["current_snapshot_id"] == snap["id"]


class TestAddDeleteConservation:
    def test_line_add_on_locked_drops_to_draft(self, api):
        """PRD §3.3: "adding or deleting a line while `BUDGET_LOCKED` supersedes
        the `CURRENT` snapshot, nulls `current_snapshot_id`, and drops the
        proposal automatically back to `DRAFT`".

        Design: Difficulty/compensating_invariant/budget_line_add_delete_conservation
        """
        reset_clock()
        env = make_locked_proposal()
        prop_id = env["proposal"]["id"]
        line = add_budget_line(prop_id, category="TRAVEL", description="t",
                               amount_cents=500_000)
        assert line["id"]
        mid = get_proposal(prop_id)
        assert mid["status"] == "DRAFT"
        snaps = get_success_data(api.list_budget_snapshots(prop_id, DIRECTOR))
        assert snaps[0]["status"] == "SUPERSEDED"

    def test_add_delete_pair_conserves_totals(self, api):
        """PRD §3.3: "adding or deleting a line while `BUDGET_LOCKED` supersedes
        the `CURRENT` snapshot, nulls `current_snapshot_id`, and drops the
        proposal automatically back to `DRAFT`" and "Finalization freezes the
        budget into an immutable **BudgetSnapshot** ... a per-proposal
        `snapshot_index` ascending from 1".

        Design: Difficulty/compensating_invariant/budget_line_add_delete_conservation
        """
        reset_clock()
        env = make_locked_proposal()
        prop_id = env["proposal"]["id"]
        s1 = env["snapshot"]
        line = add_budget_line(prop_id, category="TRAVEL", description="t",
                               amount_cents=500_000)
        # Undo the mutation, then re-finalize from the auto-DRAFT state
        resp = api.delete_budget_line(line["id"], TEST_USERS["analyst_headers"])
        assert resp.status_code == 204
        s2 = finalize_budget(prop_id)
        assert s2["status"] == "CURRENT"
        assert s2["snapshot_index"] == 2
        assert s2["total_request_cents"] == s1["total_request_cents"] == 15_400_000
        assert s2["total_indirect_cents"] == s1["total_indirect_cents"] == 5_400_000
