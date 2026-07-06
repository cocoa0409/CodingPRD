"""Depth-of-behaviour tests (queue A).

Every test here translates one instance from the difficulty-design queue. Each
docstring ends with a Design: Difficulty/<rule_id>/<instance.name> line so the
completeness audit can map tests back to the design.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    make_client_headers,
    make_provider_staff_headers,
    setup_baseline,
    setup_baseline_with_service_in_progress_referral,
    setup_program_at_capacity_utilization,
    setup_program_closed_by_capacity,
    setup_four_accepted_started_referrals,
    setup_three_unmet_outcomes_for_report,
    set_clock,
    create_funder,
    create_provider,
    create_program,
    create_client,
    create_intake,
    screen_intake,
    create_consent_grant,
    create_referral,
    accept_referral,
    start_service,
    create_outcome_report,
    create_transport_plan,
    create_funder_report_payload,
    create_referral_payload,
    create_availability_window_payload,
    create_outcome_report_payload,
    DEFAULT_CLOCK,
)


ADMIN = TEST_USERS["platform_admin_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# =============================================================================
# Rule 1 — dual_variant_calc
# =============================================================================


class TestDualVariantCalc:
    """Rule 1 instances — same calc produces different values across entity domains
    or across nested-rounding variants."""

    # ---- Instance 1: service_cost provisional vs final ---------------------

    def test_service_cost_provisional_mirrors_unit_cost_at_referral_creation(self, api):
        """PRD §3.4: "The referral is also stamped with a provisional cost: `provisional_cost_cents` is set to the program's `unit_cost_cents` at the moment of creation, as a baseline estimate before any hours of service have been delivered."

        Design: Difficulty/dual_variant_calc/service_cost_provisional_vs_final_diverges_on_referral_and_outcome
        """
        b, r = setup_baseline_with_service_in_progress_referral(
            program_overrides={"unit_cost_cents": 10000, "capacity_slots_total": 5},
        )
        assert r["provisional_cost_cents"] == 10000, (
            f"provisional must equal unit_cost_cents=10000, got {r['provisional_cost_cents']}"
        )

    def test_service_cost_final_differs_from_provisional_on_partially_met(self, api):
        """PRD §3.7: "if the outcome is `PARTIALLY_MET` or `FULLY_MET` the raw ratio is 0.50 plus the delivered `service_hours` multiplied by 0.10, and no upper cap is applied. The raw ratio is then multiplied by the program's `unit_cost_cents`, and the resulting floating-point cents value is rounded half-up in a single step to whole cents to produce `service_cost_final_cents`."
        PRD §3.7: "Because the provisional cost was simply `unit_cost_cents`, the final can be strictly less than, equal to, or strictly greater than the provisional; the caseworker sees both figures on the referral and outcome respectively."

        Design: Difficulty/dual_variant_calc/service_cost_provisional_vs_final_diverges_on_referral_and_outcome
        """
        b, r = setup_baseline_with_service_in_progress_referral(
            program_overrides={"unit_cost_cents": 10000, "capacity_slots_total": 5},
        )
        o = create_outcome_report(r["id"], b.provider_id, outcome="PARTIALLY_MET",
                                  service_hours=2.5, follow_up_needed=False)
        # raw_ratio = 0.50 + 2.5*0.10 = 0.75; raw = 10000*0.75 = 7500.
        assert o["service_cost_final_cents"] == 7500, (
            f"expected 7500 for PARTIALLY_MET 2.5hrs, got {o['service_cost_final_cents']}"
        )
        assert o["service_cost_final_cents"] != r["provisional_cost_cents"], (
            "dual-variant divergence expected: final should differ from provisional"
        )

    # ---- Instance 2: funder_report rounding variants -----------------------

    def test_funder_report_per_referral_round_then_sum_gives_1503(self, api):
        """PRD §3.8: "Under `PER_REFERRAL_ROUND_THEN_SUM` the server sums the already-rounded per-outcome `service_cost_final_cents` values as they were stored on each outcome; each per-outcome rounding may introduce up to a 0.5-cent error that accumulates across the input set."
        PRD §3.7: "If the outcome is `UNMET` the raw ratio is exactly 0.50; if the outcome is `PARTIALLY_MET` or `FULLY_MET` the raw ratio is 0.50 plus the delivered `service_hours` multiplied by 0.10, and no upper cap is applied."

        Design: Difficulty/dual_variant_calc/funder_report_allocation_per_referral_round_vs_sum_then_round_differ
        """
        b, outcomes = setup_three_unmet_outcomes_for_report(unit_cost_cents=1001)
        # Per-outcome: round_half_up(1001*0.50) = round_half_up(500.5) = 501.
        for o in outcomes:
            assert o["service_cost_final_cents"] == 501
        payload = create_funder_report_payload(
            "2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z",
            rounding_variant="PER_REFERRAL_ROUND_THEN_SUM",
        )
        resp = api.create_funder_report(b.funder["id"], payload, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["total_disbursement_cents"] == 1503, (
            f"expected 1503 (501+501+501), got {data['total_disbursement_cents']}"
        )
        assert data["rounding_variant"] == "PER_REFERRAL_ROUND_THEN_SUM"

    def test_funder_report_sum_then_round_gives_1502_for_same_inputs(self, api):
        """PRD §3.8: "Under `SUM_THEN_ROUND` the server first sums the raw floating-point values across every outcome in the set, then applies round-half-up once at the end to produce whole cents. The two totals can and often will differ for the same input set — the difference between them can be as large as approximately half a cent per outcome contributing a fractional raw — which is why the caller must attest to a specific rounding variant on each report."

        Design: Difficulty/dual_variant_calc/funder_report_allocation_per_referral_round_vs_sum_then_round_differ
        """
        b, outcomes = setup_three_unmet_outcomes_for_report(unit_cost_cents=1001)
        # Sum of raws = 3 * 1001 * 0.50 = 1501.5 -> round_half_up -> 1502.
        payload = create_funder_report_payload(
            "2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z",
            rounding_variant="SUM_THEN_ROUND",
        )
        resp = api.create_funder_report(b.funder["id"], payload, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["total_disbursement_cents"] == 1502, (
            f"SUM_THEN_ROUND expected 1502 (round_half_up of 1501.5), got {data['total_disbursement_cents']}"
        )


# =============================================================================
# Rule 2 — combinatorial_formula
# =============================================================================


class TestCombinatorialFormula:
    """Rule 2 instances — 6-input weighted score, and nested-rounding variants."""

    # ---- Instance 1: eligibility score mode (a) ----------------------------

    def test_eligibility_score_computed_from_six_weighted_inputs(self, api):
        """PRD §3.4: "The five component scores are combined by weighted sum with the fixed weights 0.30 for income, 0.20 for age, 0.25 for category, 0.15 for language, and 0.10 for accessibility. The resulting weighted sum is then multiplied by an urgency multiplier drawn from the intake's `urgency` — 1.00 for `ROUTINE`, 1.20 for `PRIORITY`, 1.50 for `EMERGENCY` — and rounded half-up to 2 decimal places to produce the final score."
        PRD §3.4: "the accessibility match: 100.0 when every value in the client's `accessibility_needs` is also present in the provider's `accessibility_features` (that is, the client's needs are a subset of the provider's features), else 0.0."

        Design: Difficulty/combinatorial_formula/eligibility_score_six_input_nested_branch_formula_mode_a
        """
        # Configure inputs so eligibility_score computes to exactly 75.00:
        # income_ratio = 450000/500000 = 0.90 -> income_score=50
        # age match, category match, language match, accessibility MISMATCH -> 100/100/100/0
        # weighted = 50*0.30 + 100*0.20 + 100*0.25 + 100*0.15 + 0*0.10 = 15+20+25+15+0 = 75
        # urgency ROUTINE -> *1.00 -> 75.00
        b = setup_baseline(
            provider_overrides={"accessibility_features": ["WHEELCHAIR"], "languages_supported": ["EN"]},
            client_overrides={"monthly_income_cents": 450000, "accessibility_needs": ["LARGE_PRINT"]},
            intake_overrides={"presenting_needs": ["FOOD"], "urgency": "ROUTINE"},
        )
        r = create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        assert r["eligibility_score"] == pytest.approx(75.00, abs=0.001), (
            f"weighted score expected 75.00, got {r['eligibility_score']}"
        )

    def test_eligibility_score_urgency_multiplier_amplifies_weighted_sum(self, api):
        """PRD §3.4: "The resulting weighted sum is then multiplied by an urgency multiplier drawn from the intake's `urgency` — 1.00 for `ROUTINE`, 1.20 for `PRIORITY`, 1.50 for `EMERGENCY` — and rounded half-up to 2 decimal places to produce the final score."

        Design: Difficulty/combinatorial_formula/eligibility_score_six_input_nested_branch_formula_mode_a
        """
        # All 5 components at 100, EMERGENCY multiplier -> weighted 100, then *1.50 = 150.00.
        # (No cap in formula per PRD §3.4.)
        b = setup_baseline(
            provider_overrides={"accessibility_features": ["WHEELCHAIR"], "languages_supported": ["EN"]},
            client_overrides={"monthly_income_cents": 250000, "accessibility_needs": []},
            intake_overrides={"presenting_needs": ["FOOD"], "urgency": "EMERGENCY"},
        )
        r = create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        assert r["eligibility_score"] == pytest.approx(150.00, abs=0.001), (
            f"EMERGENCY should multiply weighted 100 by 1.50 to get 150.00, got {r['eligibility_score']}"
        )

    # ---- Instance 2: funder_report nested-rounding-order mode (b) ----------

    def test_funder_report_per_outcome_rounded_sum_1503(self, api):
        """PRD §3.8: "Under `PER_REFERRAL_ROUND_THEN_SUM` the server sums the already-rounded per-outcome `service_cost_final_cents` values as they were stored on each outcome; each per-outcome rounding may introduce up to a 0.5-cent error that accumulates across the input set."

        Design: Difficulty/combinatorial_formula/funder_report_nested_rounding_order_mode_b
        """
        b, outcomes = setup_three_unmet_outcomes_for_report(unit_cost_cents=1001)
        payload = create_funder_report_payload(
            "2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z",
            rounding_variant="PER_REFERRAL_ROUND_THEN_SUM",
        )
        resp = api.create_funder_report(b.funder["id"], payload, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["total_disbursement_cents"] == 1503

    def test_funder_report_sum_then_round_variant_selection_pinned_by_caller(self, api):
        """PRD §3.8: "The two totals can and often will differ for the same input set — the difference between them can be as large as approximately half a cent per outcome contributing a fractional raw — which is why the caller must attest to a specific rounding variant on each report."

        Design: Difficulty/combinatorial_formula/funder_report_nested_rounding_order_mode_b
        """
        b, outcomes = setup_three_unmet_outcomes_for_report(unit_cost_cents=1001)
        p_ptr = create_funder_report_payload(
            "2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z",
            rounding_variant="PER_REFERRAL_ROUND_THEN_SUM",
        )
        p_str = create_funder_report_payload(
            "2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z",
            rounding_variant="SUM_THEN_ROUND",
        )
        d_ptr = validate_success(api.create_funder_report(b.funder["id"], p_ptr, ADMIN), 201)
        d_str = validate_success(api.create_funder_report(b.funder["id"], p_str, ADMIN), 201)
        assert d_ptr["total_disbursement_cents"] == 1503
        assert d_str["total_disbursement_cents"] == 1502
        assert d_ptr["total_disbursement_cents"] - d_str["total_disbursement_cents"] == 1, (
            "nested-rounding order is observable: PER_REFERRAL total should exceed SUM_THEN_ROUND total by 1 cent"
        )


# =============================================================================
# Rule 3 — non_linear_state_machine
# =============================================================================


class TestNonLinearStateMachine:
    """Rule 3 instances — cyclic Intake lifecycle, parallel Program postures."""

    # ---- Instance 1: Intake DRAFT<->SCREENED cycle -------------------------

    def test_intake_draft_screened_draft_revision_cycle_bumps_version(self, api):
        """PRD §3.2: "On a successful screening the intake's `status` is set to `SCREENED`, `version` increments by 1, and `updated_at` refreshes."
        PRD §3.2: "the caseworker can reopen it, moving `SCREENED` back to `DRAFT` — this reopen path is only legal when the intake is currently `SCREENED` (otherwise `ERR_INTAKE_NOT_SCREENED`) and when no referral tied to this intake is currently `ACCEPTED` or `SERVICE_IN_PROGRESS`; a successful reopen sets `status` to `DRAFT`, increments `version` by 1, and refreshes `updated_at`, letting the caseworker edit and then re-screen."

        Design: Difficulty/non_linear_state_machine/intake_draft_screened_draft_revision_cycle
        """
        set_clock(DEFAULT_CLOCK)
        c = create_client()
        i = create_intake(c["id"])
        assert i["status"] == "DRAFT" and i["version"] == 1
        # Screen: DRAFT -> SCREENED.
        i2 = screen_intake(i["id"])
        assert i2["status"] == "SCREENED"
        assert i2["version"] == 2, f"after screen version should be 2, got {i2['version']}"
        # Reopen: SCREENED -> DRAFT.
        resp = api.reopen_intake(i["id"], CASEWORKER)
        i3 = validate_success(resp)
        assert i3["status"] == "DRAFT"
        assert i3["version"] == 3, f"after reopen version should be 3, got {i3['version']}"

    def test_intake_can_be_rescreened_after_reopen_confirming_cycle(self, api):
        """PRD §3.2: "a successful reopen sets `status` to `DRAFT`, increments `version` by 1, and refreshes `updated_at`, letting the caseworker edit and then re-screen."

        Design: Difficulty/non_linear_state_machine/intake_draft_screened_draft_revision_cycle
        """
        set_clock(DEFAULT_CLOCK)
        c = create_client()
        i = create_intake(c["id"])
        screen_intake(i["id"])
        get_success_data(api.reopen_intake(i["id"], CASEWORKER))
        # Re-screen after reopen — proves the graph is cyclic, not a fork.
        resp = api.screen_intake(i["id"], CASEWORKER)
        i_final = validate_success(resp)
        assert i_final["status"] == "SCREENED"
        assert i_final["version"] == 4, (
            f"after screen-reopen-screen version should be 4, got {i_final['version']}"
        )

    # ---- Instance 2: parallel Program postures -----------------------------

    def test_program_postures_start_open_and_move_independently(self, api):
        """PRD §2.7: "Each `Program` carries two enumerated postures that evolve on independent axes."
        PRD §2.7: "`funder_reporting_posture` starts at `OPEN` when the program is created."
        PRD §3.1: "At creation, the server initialises `capacity_slots_taken` to 0, `intake_posture` to `OPEN`, and `funder_reporting_posture` to `OPEN`."

        Design: Difficulty/non_linear_state_machine/program_parallel_intake_and_funder_reporting_dimensions_evolve_independently
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        assert prog["intake_posture"] == "OPEN"
        assert prog["funder_reporting_posture"] == "OPEN"

    def test_report_generation_locks_funder_reporting_but_not_intake_posture(self, api):
        """PRD §2.7: "The two postures move independently: a program can be `intake_posture` `CLOSED` while its `funder_reporting_posture` remains `OPEN`, and vice versa."
        PRD §3.8: "Every program that contributed at least one outcome to the report advances its `funder_reporting_posture` from `OPEN` to `LOCKED` and increments its `version` by 1."

        Design: Difficulty/non_linear_state_machine/program_parallel_intake_and_funder_reporting_dimensions_evolve_independently
        """
        b, r = setup_baseline_with_service_in_progress_referral(
            program_overrides={"capacity_slots_total": 5, "unit_cost_cents": 10000},
        )
        create_outcome_report(r["id"], b.provider_id, outcome="FULLY_MET",
                              service_hours=5.0, follow_up_needed=False)
        # Push utilization to 4/5 by creating 3 more PROPOSED referrals (r is 1 SIP -> already 1
        # taken; add 3 more to reach 4 taken -> 4/5 = 0.80 -> RESTRICTED).
        for _ in range(3):
            create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        # Generate report — locks funder_reporting_posture.
        payload = create_funder_report_payload(
            "2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z", rounding_variant="SUM_THEN_ROUND",
        )
        validate_success(api.create_funder_report(b.funder["id"], payload, ADMIN), 201)
        prog_after = get_success_data(api.get_program(b.program["id"], ADMIN))
        assert prog_after["funder_reporting_posture"] == "LOCKED", (
            "report generation should advance funder_reporting_posture OPEN->LOCKED"
        )
        assert prog_after["intake_posture"] == "RESTRICTED", (
            f"intake_posture should reflect 4/5 = 0.80 utilization = RESTRICTED, got {prog_after['intake_posture']}"
        )


# =============================================================================
# Rule 4 — transitive_cascade
# =============================================================================


class TestTransitiveCascade:
    """Rule 4 instances — depth-3 cascades from two different triggers."""

    # ---- Instance 1: consent revoke -> withdraw -> transport cancel --------

    def test_consent_revoke_cascades_referral_withdraw_and_transport_cancel(self, api):
        """PRD §3.3: "On a successful revoke, the grant's `status` is set to `REVOKED`, its `version` increments by 1, its `updated_at` refreshes, and every referral that was created under this consent and whose `status` is currently `PROPOSED`, `ACCEPTED`, or `SERVICE_IN_PROGRESS` is cascaded through the same withdraw path that a client-initiated withdrawal takes — each cascaded referral transitions to `WITHDRAWN`, decrements the target program's `capacity_slots_taken` by 1, may recompute `intake_posture`, cancels any `SCHEDULED` transport plan on that referral, and may bubble the parent intake to `CLOSED` when this referral was the last non-terminal one."

        Design: Difficulty/transitive_cascade/consent_revoke_cascades_referral_withdraw_and_transport_cancel_depth_3
        """
        # Referral is ACCEPTED (not SERVICE_IN_PROGRESS) with a SCHEDULED transport plan so the
        # revoke cascade visits ACCEPTED -> WITHDRAWN and the transport cancel side-effect fires.
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        cl = create_client()
        i = create_intake(cl["id"])
        i = screen_intake(i["id"])
        cg = create_consent_grant(cl["id"], p["id"])
        ref = create_referral(i["id"], prog["id"], cg["id"], transport_mode="AGENCY_SHUTTLE")
        ref = accept_referral(ref["id"], p["id"])
        tp = create_transport_plan(ref["id"], "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z",
                                    mode="AGENCY_SHUTTLE", cost_cents=500)
        # Revoke consent.
        resp = api.revoke_consent_grant(cg["id"], make_client_headers(cl["id"]))
        cg_after = validate_success(resp)
        assert cg_after["status"] == "REVOKED"
        # Link 2: referral now WITHDRAWN.
        ref_after = get_success_data(api.get_referral(ref["id"], CASEWORKER))
        assert ref_after["status"] == "WITHDRAWN", (
            f"referral should cascade to WITHDRAWN, got {ref_after['status']}"
        )
        # Link 3: transport plan now CANCELLED.
        tps = get_success_data(api.list_transport_plans(ref["id"], CASEWORKER))
        # list_transport_plans returns the paginated envelope's data array
        # (data is a list per PRD §2.2 array response_type).
        found = [x for x in tps if x["id"] == tp["id"]]
        assert len(found) == 1
        assert found[0]["status"] == "CANCELLED", (
            f"scheduled transport plan should cascade to CANCELLED, got {found[0]['status']}"
        )

    def test_consent_revoke_cascade_decrements_program_capacity(self, api):
        """PRD §3.3: "each cascaded referral transitions to `WITHDRAWN`, decrements the target program's `capacity_slots_taken` by 1, may recompute `intake_posture`"
        PRD §3.4: "As a side effect of creation, the program's `capacity_slots_taken` is incremented by 1"

        Design: Difficulty/transitive_cascade/consent_revoke_cascades_referral_withdraw_and_transport_cancel_depth_3
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        cl = create_client()
        i = create_intake(cl["id"])
        i = screen_intake(i["id"])
        cg = create_consent_grant(cl["id"], p["id"])
        ref = create_referral(i["id"], prog["id"], cg["id"])
        ref = accept_referral(ref["id"], p["id"])
        prog_before = get_success_data(api.get_program(prog["id"], ADMIN))
        assert prog_before["capacity_slots_taken"] == 1
        # Revoke -> cascade withdraw -> decrement capacity.
        validate_success(api.revoke_consent_grant(cg["id"], make_client_headers(cl["id"])))
        prog_after = get_success_data(api.get_program(prog["id"], ADMIN))
        assert prog_after["capacity_slots_taken"] == 0, (
            f"cascaded withdraw should decrement to 0, got {prog_after['capacity_slots_taken']}"
        )

    # ---- Instance 2: complete -> capacity decrement -> posture recompute ---

    def test_complete_referral_decrements_capacity_and_recomputes_posture(self, api):
        """PRD §3.5: "Either way, the referral's `version` increments by 1, the program's `capacity_slots_taken` decrements by 1 with the same posture-recomputation cascade as decline, and if every referral on the parent intake is now terminal the intake auto-bubbles `SCREENED → CLOSED`."
        PRD §3.5: "`CLOSED → RESTRICTED` when utilisation drops strictly below 1.00 while still being at least 0.80, and `RESTRICTED → OPEN` when utilisation drops strictly below 0.80."

        Design: Difficulty/transitive_cascade/complete_referral_cascades_capacity_decrement_and_posture_recompute_depth_3
        """
        b, refs = setup_four_accepted_started_referrals(program_capacity=5)
        # Confirm RESTRICTED at 4/5 = 0.80.
        prog_before = get_success_data(api.get_program(b.program["id"], ADMIN))
        assert prog_before["capacity_slots_taken"] == 4
        assert prog_before["intake_posture"] == "RESTRICTED"
        # Complete one referral SUCCESS -> capacity 3 -> 3/5 = 0.60 -> OPEN.
        r0 = refs[0]
        validate_success(api.complete_referral(r0["id"], "SUCCESS", make_provider_staff_headers(b.provider_id)))
        prog_after = get_success_data(api.get_program(b.program["id"], ADMIN))
        assert prog_after["capacity_slots_taken"] == 3, (
            f"capacity_slots_taken should decrement to 3, got {prog_after['capacity_slots_taken']}"
        )
        assert prog_after["intake_posture"] == "OPEN", (
            f"posture should recompute to OPEN (3/5 < 0.80), got {prog_after['intake_posture']}"
        )
        # Verify link 1: referral itself is terminal.
        r0_after = get_success_data(api.get_referral(r0["id"], CASEWORKER))
        assert r0_after["status"] == "COMPLETED_SUCCESS"

    def test_complete_unsuccessful_triggers_same_cascade_shape(self, api):
        """PRD §3.5: "A `SUCCESS` completion sets `status` to `COMPLETED_SUCCESS`; an `UNSUCCESSFUL` completion sets `status` to `COMPLETED_UNSUCCESSFUL`. Either way, the referral's `version` increments by 1, the program's `capacity_slots_taken` decrements by 1 with the same posture-recomputation cascade as decline"

        Design: Difficulty/transitive_cascade/complete_referral_cascades_capacity_decrement_and_posture_recompute_depth_3
        """
        b, refs = setup_four_accepted_started_referrals(program_capacity=5)
        validate_success(api.complete_referral(refs[0]["id"], "UNSUCCESSFUL",
                                                make_provider_staff_headers(b.provider_id)))
        r0_after = get_success_data(api.get_referral(refs[0]["id"], CASEWORKER))
        assert r0_after["status"] == "COMPLETED_UNSUCCESSFUL"
        prog_after = get_success_data(api.get_program(b.program["id"], ADMIN))
        assert prog_after["capacity_slots_taken"] == 3
        assert prog_after["intake_posture"] == "OPEN"


# =============================================================================
# Rule 5 — priority_pair_validation_conflict
# =============================================================================


class TestPriorityPairValidationConflict:
    """Rule 5 instances — highest-priority applicable rule wins on simultaneous violations."""

    # ---- Instance 1: state (18) beats business_safety (20) -----------------

    def test_program_closed_wins_over_consent_provider_mismatch(self, api):
        """PRD §2.10: "Only after these gates have passed does the server evaluate state preconditions (the endpoint-specific `ERR_*_INVALID_STATE`, `ERR_INTAKE_NOT_DRAFT`, `ERR_INTAKE_NOT_SCREENED`, `ERR_REFERRAL_INVALID_STATE`, `ERR_CONSENT_ALREADY_TERMINAL`, `ERR_OUTCOME_ALREADY_REVERSED`, `ERR_PROGRAM_CLOSED_TO_INTAKE`), then the domain-specific business rules described throughout §3"
        PRD §2.10: "When a referral would fail multiple rules at once, the highest-priority applicable rule wins."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_program_closed_over_consent_provider_mismatch
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p_correct = create_provider(legal_name="P_correct")
        p_wrong = create_provider(legal_name="P_wrong")
        prog = create_program(p_correct["id"], f["id"], capacity_slots_total=1)
        # First client fills the program to capacity so intake_posture becomes CLOSED.
        c_seed = create_client(full_name="Seeder")
        i_seed = screen_intake(create_intake(c_seed["id"])["id"])
        cg_seed = create_consent_grant(c_seed["id"], p_correct["id"])
        create_referral(i_seed["id"], prog["id"], cg_seed["id"])
        # Second client with a WRONG-PROVIDER consent.
        c2 = create_client(full_name="Second")
        i2 = screen_intake(create_intake(c2["id"])["id"])
        cg2 = create_consent_grant(c2["id"], p_wrong["id"])
        # Try referral: BOTH ERR_PROGRAM_CLOSED_TO_INTAKE (state, priority 18) and
        # ERR_CONSENT_PROVIDER_MISMATCH (business_safety, priority 20) apply.
        payload = create_referral_payload(prog["id"], cg2["id"], transport_mode="CAR")
        resp = api.create_referral(i2["id"], payload, CASEWORKER)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED_TO_INTAKE, expected_status=409)

    def test_program_closed_wins_over_consent_provider_mismatch_status_is_409(self, api):
        """PRD §5 (Error Code Catalogue): "`ERR_PROGRAM_CLOSED_TO_INTAKE` | 409"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_program_closed_over_consent_provider_mismatch
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p_correct = create_provider(legal_name="Pa")
        p_wrong = create_provider(legal_name="Pb")
        prog = create_program(p_correct["id"], f["id"], capacity_slots_total=1)
        c_seed = create_client(full_name="Seed2")
        i_seed = screen_intake(create_intake(c_seed["id"])["id"])
        cg_seed = create_consent_grant(c_seed["id"], p_correct["id"])
        create_referral(i_seed["id"], prog["id"], cg_seed["id"])
        c2 = create_client(full_name="Second2")
        i2 = screen_intake(create_intake(c2["id"])["id"])
        cg2 = create_consent_grant(c2["id"], p_wrong["id"])
        resp = api.create_referral(i2["id"], create_referral_payload(prog["id"], cg2["id"]), CASEWORKER)
        assert resp.status_code == 409, f"expected HTTP 409, got {resp.status_code}"

    # ---- Instance 2: business_referential (21) beats business_constraint (23) ----

    def test_category_mismatch_wins_over_age_ineligible(self, api):
        """PRD §2.10: "category mismatch surfaces before the eligibility-score threshold (`ERR_ELIGIBILITY_BELOW_THRESHOLD`); the score check surfaces before age (`ERR_AGE_INELIGIBLE`), income (`ERR_INCOME_INELIGIBLE`), and program-full (`ERR_CAPACITY_EXHAUSTED`) checks in that same priority order."
        PRD §3.4: "the program's `category` must be one of the categories in the intake's `presenting_needs`; if the client is not presenting for a need this program addresses, the referral is rejected with `ERR_PROGRAM_CATEGORY_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_beats_business_constraint_category_over_age
        """
        # Program category FOOD, narrow age band 18-25; client age 30, presenting HOUSING only.
        # Both mismatch AND age_ineligible fire. Category (priority 21) wins.
        b = setup_baseline(
            program_overrides={"category": "FOOD", "eligibility_age_min": 18,
                               "eligibility_age_max": 25, "capacity_slots_total": 5},
            client_overrides={"date_of_birth": "1996-01-15", "monthly_income_cents": 400_000},
            intake_overrides={"presenting_needs": ["HOUSING"]},
        )
        payload = create_referral_payload(b.program["id"], b.consent["id"])
        resp = api.create_referral(b.intake["id"], payload, CASEWORKER)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CATEGORY_MISMATCH, expected_status=422)

    def test_category_mismatch_wins_over_age_ineligible_status_is_422(self, api):
        """PRD §5: "`ERR_PROGRAM_CATEGORY_MISMATCH` | 422"

        Design: Difficulty/priority_pair_validation_conflict/business_referential_beats_business_constraint_category_over_age
        """
        b = setup_baseline(
            program_overrides={"category": "FOOD", "eligibility_age_min": 18,
                               "eligibility_age_max": 25, "capacity_slots_total": 5},
            client_overrides={"date_of_birth": "1996-01-15"},
            intake_overrides={"presenting_needs": ["HOUSING"]},
        )
        resp = api.create_referral(b.intake["id"], create_referral_payload(b.program["id"], b.consent["id"]),
                                    CASEWORKER)
        assert resp.status_code == 422


# =============================================================================
# Rule 6 — boundary_precision_check
# =============================================================================


class TestBoundaryPrecision:
    """Rule 6 instances — exact numeric threshold and strict-future temporal boundary."""

    # ---- Instance 1: eligibility score 75.00 exactly passes ----------------

    def test_eligibility_score_75_exactly_passes_threshold(self, api):
        """PRD §3.4: "That final value is what is written to the referral's `eligibility_score` field, and if it is strictly less than 75.0 the referral is rejected with `ERR_ELIGIBILITY_BELOW_THRESHOLD`; a score of exactly 75.00 passes."

        Design: Difficulty/boundary_precision_check/eligibility_score_inclusive_boundary_at_75_exactly_passes_on_referral_create
        """
        # Same setup as combinatorial mode a — score = 75.00 exactly.
        b = setup_baseline(
            provider_overrides={"accessibility_features": ["WHEELCHAIR"], "languages_supported": ["EN"]},
            client_overrides={"monthly_income_cents": 450000, "accessibility_needs": ["LARGE_PRINT"]},
            intake_overrides={"presenting_needs": ["FOOD"], "urgency": "ROUTINE"},
        )
        r = create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        assert r["eligibility_score"] == pytest.approx(75.00, abs=0.001)
        assert r["status"] == "PROPOSED", (
            f"score of exactly 75.00 must pass and produce PROPOSED referral, got {r['status']}"
        )

    def test_eligibility_score_74_99_rejects_below_threshold(self, api):
        """PRD §3.4: "if it is strictly less than 75.0 the referral is rejected with `ERR_ELIGIBILITY_BELOW_THRESHOLD`; a score of exactly 75.00 passes."

        Design: Difficulty/boundary_precision_check/eligibility_score_inclusive_boundary_at_75_exactly_passes_on_referral_create
        """
        # Push the score just below 75.00. Weighted = 50*0.30 + 100*0.20 + 100*0.25 + 50*0.15 + 0*0.10
        # = 15+20+25+7.5+0 = 67.5 * 1.00 (ROUTINE) = 67.50.
        # income_ratio 0.90 -> income 50; language match FALSE (client ES, provider EN only) -> 50;
        # accessibility mismatch -> 0.
        b = setup_baseline(
            provider_overrides={"accessibility_features": ["WHEELCHAIR"], "languages_supported": ["EN"]},
            client_overrides={"monthly_income_cents": 450000, "accessibility_needs": ["LARGE_PRINT"],
                              "preferred_language": "ES"},
            intake_overrides={"presenting_needs": ["FOOD"], "urgency": "ROUTINE"},
        )
        payload = create_referral_payload(b.program["id"], b.consent["id"])
        resp = api.create_referral(b.intake["id"], payload, CASEWORKER)
        validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_BELOW_THRESHOLD, expected_status=422)

    # ---- Instance 2: availability window start_ts == clock rejects ---------

    def test_availability_window_start_ts_equal_to_clock_rejects(self, api):
        """PRD §3.1: "When adding a window, `start_ts` must be strictly greater than the current logical clock — a `start_ts` exactly equal to the clock is rejected as being in the past with `ERR_WINDOW_IN_PAST`."

        Design: Difficulty/boundary_precision_check/availability_window_strict_future_boundary_start_ts_equal_to_clock_rejects
        """
        set_clock("2026-06-01T00:00:00Z")
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        payload = create_availability_window_payload(
            "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z", max_slots=3,
        )
        resp = api.create_availability_window(prog["id"], payload, make_provider_staff_headers(p["id"]))
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST, expected_status=422)

    def test_availability_window_start_ts_after_clock_by_one_second_passes(self, api):
        """PRD §3.1: "`start_ts` must be strictly greater than the current logical clock — a `start_ts` exactly equal to the clock is rejected as being in the past with `ERR_WINDOW_IN_PAST`."

        Design: Difficulty/boundary_precision_check/availability_window_strict_future_boundary_start_ts_equal_to_clock_rejects
        """
        set_clock("2026-06-01T00:00:00Z")
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        payload = create_availability_window_payload(
            "2026-06-01T00:00:01Z", "2026-06-02T00:00:00Z", max_slots=3,
        )
        resp = api.create_availability_window(prog["id"], payload, make_provider_staff_headers(p["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["start_ts"].startswith("2026-06-01T00:00:01")


# =============================================================================
# Rule 7 — cross_entity_state_dependency
# =============================================================================


class TestCrossEntityStateDependency:
    """Rule 7 instances — Referral<->ConsentGrant and Referral<->Program dependencies."""

    # ---- Instance 1: accept requires ConsentGrant == GRANTED ----------------

    def test_accept_referral_with_expired_consent_returns_consent_not_granted(self, api):
        """PRD §3.5: "Acceptance requires the referral to currently be `PROPOSED` (otherwise `ERR_REFERRAL_INVALID_STATE`), the linked consent grant's `status` to be `GRANTED` — not `REVOKED` and not `EXPIRED` — (otherwise `ERR_CONSENT_NOT_GRANTED`)"
        PRD §3.3: "when the logical clock advances to a moment at or after a `GRANTED` grant's `expires_at`, the grant is automatically transitioned to `EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/referral_accept_requires_consent_granted_referral_consentgrant_pair
        """
        # Consent created at 2026-06-01 expires at 2026-08-30. Advance clock to 2026-09-01
        # to expire the consent while the referral is still PROPOSED.
        set_clock("2026-06-01T00:00:00Z")
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        cl = create_client()
        i = create_intake(cl["id"])
        i = screen_intake(i["id"])
        cg = create_consent_grant(cl["id"], p["id"])
        ref = create_referral(i["id"], prog["id"], cg["id"])
        # Advance clock past expires_at.
        set_clock("2026-09-01T00:00:00Z")
        # Verify consent expired.
        cg_after = get_success_data(api.get_consent_grant(cg["id"], CASEWORKER))
        assert cg_after["status"] == "EXPIRED"
        # Attempt accept -> ERR_CONSENT_NOT_GRANTED.
        resp = api.accept_referral(ref["id"], make_provider_staff_headers(p["id"]))
        validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_GRANTED, expected_status=422)

    def test_start_service_with_expired_consent_returns_consent_not_granted(self, api):
        """PRD §3.5: "This requires the referral to currently be `ACCEPTED` (otherwise `ERR_REFERRAL_INVALID_STATE`) and the linked consent grant to currently be `GRANTED` (otherwise `ERR_CONSENT_NOT_GRANTED`); a consent that has expired between accept and start-service will block start-service even though the accept succeeded."

        Design: Difficulty/cross_entity_state_dependency/referral_accept_requires_consent_granted_referral_consentgrant_pair
        """
        # Use consent EXPIRY (not REVOKE) so the ACCEPTED referral survives: PRD §3.3 says
        # expiry does not cascade in-flight referrals, but revoke would.
        set_clock("2026-06-01T00:00:00Z")
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        cl = create_client()
        i = create_intake(cl["id"])
        i = screen_intake(i["id"])
        cg = create_consent_grant(cl["id"], p["id"])
        ref = create_referral(i["id"], prog["id"], cg["id"])
        ref = accept_referral(ref["id"], p["id"])
        # Advance clock -> consent EXPIRED but referral remains ACCEPTED (no cascade on expiry).
        set_clock("2026-09-01T00:00:00Z")
        ref_after = get_success_data(api.get_referral(ref["id"], CASEWORKER))
        assert ref_after["status"] == "ACCEPTED"
        resp = api.start_service(ref["id"], make_provider_staff_headers(p["id"]))
        validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_GRANTED, expected_status=422)

    # ---- Instance 2: accept requires Program.intake_posture != CLOSED ------

    def test_accept_referral_when_program_closed_returns_program_closed(self, api):
        """PRD §3.5: "Acceptance requires the referral to currently be `PROPOSED` (otherwise `ERR_REFERRAL_INVALID_STATE`), the linked consent grant's `status` to be `GRANTED` — not `REVOKED` and not `EXPIRED` — (otherwise `ERR_CONSENT_NOT_GRANTED`), and the program's `intake_posture` to not be `CLOSED` (otherwise `ERR_PROGRAM_CLOSED_TO_INTAKE`)."

        Design: Difficulty/cross_entity_state_dependency/referral_accept_requires_program_not_closed_referral_program_pair
        """
        # capacity=2, create two PROPOSED referrals -> capacity=2/2 -> CLOSED. Then accept fails.
        b, refs = setup_program_at_capacity_utilization(n_referrals=2, program_capacity=2)
        prog = get_success_data(api.get_program(b.program["id"], ADMIN))
        assert prog["intake_posture"] == "CLOSED", (
            f"program should be CLOSED at 2/2 utilization, got {prog['intake_posture']}"
        )
        resp = api.accept_referral(refs[0]["id"], make_provider_staff_headers(b.provider_id))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED_TO_INTAKE, expected_status=409)

    def test_accept_referral_when_program_closed_status_is_409(self, api):
        """PRD §5: "`ERR_PROGRAM_CLOSED_TO_INTAKE` | 409"

        Design: Difficulty/cross_entity_state_dependency/referral_accept_requires_program_not_closed_referral_program_pair
        """
        b, refs = setup_program_at_capacity_utilization(n_referrals=2, program_capacity=2)
        resp = api.accept_referral(refs[0]["id"], make_provider_staff_headers(b.provider_id))
        assert resp.status_code == 409


# =============================================================================
# Rule 8 — resource_temporal_overlap
# =============================================================================


class TestResourceTemporalOverlap:
    """Rule 8 instances — half-open availability windows and closed-closed transport plans."""

    # ---- Instance 1: half-open availability window overlap -----------------

    def test_availability_window_adjacent_ok_overlapping_rejects(self, api):
        """PRD §2.9: "Availability windows on a program use a half-open interval `[start_ts, end_ts)` — the start is inclusive, the end is exclusive — so two windows overlap when the first window's start is strictly before the second window's end and the second window's start is strictly before the first window's end; two adjacent windows where one window's `end_ts` equals the next window's `start_ts` do not overlap."
        PRD §3.1: "The new window's half-open interval `[start_ts, end_ts)` must not overlap any existing window on the same program under the half-open semantics of §2.9; a violation is rejected with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacent_ok_overlap_rejects
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=10)
        ps_headers = make_provider_staff_headers(p["id"])
        # First window: [10:00, 12:00).
        w1 = validate_success(
            api.create_availability_window(prog["id"],
                create_availability_window_payload("2026-08-01T10:00:00Z", "2026-08-01T12:00:00Z", 3),
                ps_headers), 201)
        # Adjacent window: [12:00, 14:00) — SHOULD succeed under half-open.
        w2 = validate_success(
            api.create_availability_window(prog["id"],
                create_availability_window_payload("2026-08-01T12:00:00Z", "2026-08-01T14:00:00Z", 3),
                ps_headers), 201)
        assert w1["id"] != w2["id"]
        # Overlapping window: [11:00, 13:00) — MUST reject.
        resp = api.create_availability_window(prog["id"],
            create_availability_window_payload("2026-08-01T11:00:00Z", "2026-08-01T13:00:00Z", 3),
            ps_headers)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP, expected_status=409)

    def test_availability_window_overlap_returns_409(self, api):
        """PRD §5: "`ERR_WINDOW_OVERLAP` | 409"

        Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacent_ok_overlap_rejects
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=10)
        ps = make_provider_staff_headers(p["id"])
        validate_success(api.create_availability_window(prog["id"],
            create_availability_window_payload("2026-08-01T10:00:00Z", "2026-08-01T12:00:00Z", 3),
            ps), 201)
        resp = api.create_availability_window(prog["id"],
            create_availability_window_payload("2026-08-01T11:00:00Z", "2026-08-01T13:00:00Z", 3),
            ps)
        assert resp.status_code == 409

    # ---- Instance 2: transport plan 30-minute buffer ----------------------

    def test_transport_plan_gap_29_min_rejects_overlap(self, api):
        """PRD §3.6: "Two plans conflict when the smaller of the two temporal gaps between them — the gap measured in seconds between the closing endpoint of one interval and the opening endpoint of the other — is strictly less than 30 minutes. A conflict is rejected with `ERR_TRANSPORT_OVERLAP`; a gap of exactly 30 minutes is permitted."

        Design: Difficulty/resource_temporal_overlap/transport_plan_closed_closed_with_30_minute_buffer_rejects_29min_gap
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        cl = create_client()
        i = screen_intake(create_intake(cl["id"])["id"])
        cg = create_consent_grant(cl["id"], p["id"])
        ra = accept_referral(
            create_referral(i["id"], prog["id"], cg["id"], transport_mode="AGENCY_SHUTTLE")["id"],
            p["id"],
        )
        rb = accept_referral(
            create_referral(i["id"], prog["id"], cg["id"], transport_mode="AGENCY_SHUTTLE")["id"],
            p["id"],
        )
        # First plan [09:00, 10:00].
        create_transport_plan(ra["id"], "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
        # Second plan [10:29, 11:00] — gap = 29 minutes -> reject.
        resp = api.create_transport_plan(rb["id"],
            {"pickup_start_ts": "2026-06-10T10:29:00Z", "pickup_end_ts": "2026-06-10T11:00:00Z",
             "mode": "AGENCY_SHUTTLE", "cost_cents": 500},
            CASEWORKER)
        validate_error(resp, ApiErrorId.ERR_TRANSPORT_OVERLAP, expected_status=409)

    def test_transport_plan_gap_29_min_rejects_status_is_409(self, api):
        """PRD §5: "`ERR_TRANSPORT_OVERLAP` | 409"

        Design: Difficulty/resource_temporal_overlap/transport_plan_closed_closed_with_30_minute_buffer_rejects_29min_gap
        """
        set_clock(DEFAULT_CLOCK)
        f = create_funder()
        p = create_provider()
        prog = create_program(p["id"], f["id"], capacity_slots_total=5)
        cl = create_client()
        i = screen_intake(create_intake(cl["id"])["id"])
        cg = create_consent_grant(cl["id"], p["id"])
        ra = accept_referral(
            create_referral(i["id"], prog["id"], cg["id"], transport_mode="AGENCY_SHUTTLE")["id"], p["id"])
        rb = accept_referral(
            create_referral(i["id"], prog["id"], cg["id"], transport_mode="AGENCY_SHUTTLE")["id"], p["id"])
        create_transport_plan(ra["id"], "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
        resp = api.create_transport_plan(rb["id"],
            {"pickup_start_ts": "2026-06-10T10:29:00Z", "pickup_end_ts": "2026-06-10T11:00:00Z",
             "mode": "AGENCY_SHUTTLE", "cost_cents": 500}, CASEWORKER)
        assert resp.status_code == 409


# =============================================================================
# Rule 9 — compensating_invariant
# =============================================================================


class TestCompensatingInvariant:
    """Rule 9 instances — reverse restores grant balance; withdraw restores capacity."""

    # ---- Instance 1: outcome reverse restores funder.grant_cents_remaining ----

    def test_outcome_report_reverse_restores_grant_cents_remaining_to_pre_create(self, api):
        """PRD §2.8: "Filing a new outcome report debits `grant_cents_remaining` by the newly computed `service_cost_final_cents`; reversing an active outcome report credits `grant_cents_remaining` by exactly the same integer-cents value. The invariant is that, after any (create, reverse) pair on the same outcome report, `grant_cents_remaining` returns to the exact integer-cents value it held before the create."
        PRD §3.7: "so a (create, reverse) pair on the same outcome returns `grant_cents_remaining` to the exact integer-cents value it held before the create."

        Design: Difficulty/compensating_invariant/outcome_report_create_then_reverse_leaves_funder_grant_remaining_unchanged
        """
        b, r = setup_baseline_with_service_in_progress_referral(
            program_overrides={"unit_cost_cents": 10000, "capacity_slots_total": 5},
        )
        pre = get_success_data(api.get_funder(b.funder["id"], ADMIN))["grant_cents_remaining"]
        assert pre == 100_000_000
        o = create_outcome_report(r["id"], b.provider_id, outcome="UNMET",
                                  service_hours=0.0, follow_up_needed=False)
        # UNMET raw = unit_cost * 0.5 = 5000.
        assert o["service_cost_final_cents"] == 5000
        after_debit = get_success_data(api.get_funder(b.funder["id"], ADMIN))["grant_cents_remaining"]
        assert after_debit == pre - 5000
        # Reverse.
        validate_success(api.reverse_outcome_report(o["id"], ADMIN))
        after_reverse = get_success_data(api.get_funder(b.funder["id"], ADMIN))["grant_cents_remaining"]
        assert after_reverse == pre, (
            f"invariant: post-reverse grant_cents_remaining must equal pre-create ({pre}), got {after_reverse}"
        )

    def test_outcome_report_status_transitions_active_to_reversed(self, api):
        """PRD §3.7: "On success the outcome's `status` is set to `REVERSED`, its `version` increments by 1, its `updated_at` refreshes, and the funder's `grant_cents_remaining` is credited by exactly the same `service_cost_final_cents` that was debited at outcome creation"

        Design: Difficulty/compensating_invariant/outcome_report_create_then_reverse_leaves_funder_grant_remaining_unchanged
        """
        b, r = setup_baseline_with_service_in_progress_referral(
            program_overrides={"unit_cost_cents": 10000, "capacity_slots_total": 5},
        )
        o = create_outcome_report(r["id"], b.provider_id, outcome="UNMET", service_hours=0.0)
        assert o["status"] == "ACTIVE"
        o_after = validate_success(api.reverse_outcome_report(o["id"], ADMIN))
        assert o_after["status"] == "REVERSED"

    # ---- Instance 2: withdraw restores capacity_slots_taken ---------------

    def test_referral_create_then_withdraw_restores_capacity_slots_taken(self, api):
        """PRD §3.4: "As a side effect of creation, the program's `capacity_slots_taken` is incremented by 1"
        PRD §3.5: "Withdrawal sets `status` to `WITHDRAWN`, increments `version` by 1, and refreshes `updated_at`. It decrements the program's `capacity_slots_taken` by 1"

        Design: Difficulty/compensating_invariant/referral_create_then_withdraw_leaves_program_capacity_slots_taken_unchanged
        """
        b = setup_baseline(program_overrides={"capacity_slots_total": 5})
        pre = get_success_data(api.get_program(b.program["id"], ADMIN))["capacity_slots_taken"]
        assert pre == 0
        r = create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        after_create = get_success_data(api.get_program(b.program["id"], ADMIN))["capacity_slots_taken"]
        assert after_create == 1
        # Withdraw.
        validate_success(api.withdraw_referral(r["id"], make_client_headers(b.client_id)))
        after_withdraw = get_success_data(api.get_program(b.program["id"], ADMIN))["capacity_slots_taken"]
        assert after_withdraw == 0, (
            f"capacity_slots_taken should return to pre-create value 0, got {after_withdraw}"
        )

    def test_referral_withdraw_sets_status_to_withdrawn(self, api):
        """PRD §3.5: "A client (or a caseworker or `PlatformAdmin` acting on the client's behalf) can withdraw a referral from any non-terminal state — `PROPOSED`, `ACCEPTED`, or `SERVICE_IN_PROGRESS`."
        PRD §3.5: "Withdrawal sets `status` to `WITHDRAWN`, increments `version` by 1, and refreshes `updated_at`."

        Design: Difficulty/compensating_invariant/referral_create_then_withdraw_leaves_program_capacity_slots_taken_unchanged
        """
        b = setup_baseline(program_overrides={"capacity_slots_total": 5})
        r = create_referral(b.intake["id"], b.program["id"], b.consent["id"])
        after = validate_success(api.withdraw_referral(r["id"], make_client_headers(b.client_id)))
        assert after["status"] == "WITHDRAWN"
        assert after["version"] == r["version"] + 1, (
            f"withdraw should increment version by 1: was {r['version']}, now {after['version']}"
        )
