"""Care gap lifecycle, pharmacy adherence interventions, member disenrollment
cascade, and measure-population conservation."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    close_gap,
    create_member,
    disenroll_member,
    get_cycle,
    get_gap,
    get_performance,
    intervene,
    open_gap,
    reopen_gap,
    report_performance,
    setup_collecting_measure,
    setup_gap_scenario,
    setup_locked_performance_scenario,
    transition_gap,
    validate_error,
    validate_performance,
    validate_success,
)


class TestCareGapCreation:
    def test_care_gap_get_not_found_returns_404(self, api, quality_ops_headers):
        """PRD §2.10: "Path identifiers are validated left to right: a URL naming
        a cycle and then a subordinate resource fails on the cycle first when the
        cycle does not exist, with the entity-specific not-found error
        (`ERR_CYCLE_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`,
        `ERR_CUTPOINT_SET_NOT_FOUND`, `ERR_PERFORMANCE_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND`, `ERR_CARE_GAP_NOT_FOUND`,
        `ERR_PROVIDER_GROUP_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_WAVE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_FORECAST_NOT_FOUND`)."

        Design: Corner/entities/care_gap_get_not_found_returns_404
        """
        resp = api.get_care_gap(NON_EXISTENT_UUID, quality_ops_headers)
        validate_error(resp, ApiErrorId.ERR_CARE_GAP_NOT_FOUND)

    def test_care_gap_initial_state_open(self, api, quality_ops_headers):
        """PRD §3.5: "Opening the gap sets it `OPEN` and immediately credits the
        linked performance: the performance's `denominator` increases by 1,
        `raw_value` and both stars recompute, and the cycle's
        `live_weighted_stars` refreshes."
        PRD §3.5: "The gap's `intervention_count` starts at 0 and increases by 1
        with each recorded intervention; `last_intervention_channel` records the
        channel used, staying null until the first."

        Design: Corner/state_machines/care_gap_initial_state_open
        """
        sc = setup_collecting_measure(10, 20)
        member = create_member("MBR-1")
        resp = api.create_care_gap(
            {"member_id": member["id"], "measure_id": sc["measure"]["id"],
             "gap_type": "SCREENING"},
            quality_ops_headers,
        )
        gap = validate_success(resp, 201)
        assert gap["status"] == "OPEN", "A new gap is born OPEN"
        assert gap["intervention_count"] == 0
        assert gap["last_intervention_channel"] is None
        perf = validate_success(api.get_measure_performance(
            sc["performance"]["id"], quality_ops_headers))
        assert perf["denominator"] == 21, (
            f"Opening the gap credits the denominator +1 (20 -> 21), got "
            f"{perf['denominator']}"
        )

    def test_duplicate_performance_and_gap_rejected(self, api, quality_ops_headers):
        """PRD §3.2: "The measure must belong to the named cycle — otherwise
        `ERR_MEASURE_CYCLE_MISMATCH` — and only one performance may exist per
        measure within a cycle; a second report for the same pair is rejected with
        `ERR_DUPLICATE_PERFORMANCE`."
        PRD §3.5: "The member must be `ENROLLED` — otherwise
        `ERR_MEMBER_NOT_ENROLLED` — and there must not already be an `OPEN` or
        `REOPENED` gap for the same member and measure, else
        `ERR_DUPLICATE_OPEN_GAP`."

        Design: Corner/validations/duplicate_performance_and_gap_rejected
        """
        sc = setup_gap_scenario(5, 10)
        cycle_id = sc["cycle"]["id"]

        resp = api.create_measure_performance(
            {"rating_cycle_id": cycle_id, "measure_id": sc["measure"]["id"],
             "numerator": 6, "denominator": 10},
            quality_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERFORMANCE)

        resp = api.create_care_gap(
            {"member_id": sc["member"]["id"], "measure_id": sc["measure"]["id"],
             "gap_type": "SCREENING"},
            quality_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_GAP)

    def test_gap_type_measure_mismatch_rejected(self, api, quality_ops_headers):
        """PRD §2.10: "Gap-type alignment also applies: a `PHARMACY_ADHERENCE` gap
        may only be opened against a `PHARMACY_PDE` measure, and a gap of any other
        type may not be opened against a `PHARMACY_PDE` measure — violations are
        rejected with `ERR_GAP_TYPE_MEASURE_MISMATCH`."

        Design: Corner/validations/gap_type_measure_mismatch_rejected
        """
        sc = setup_collecting_measure(5, 10)
        member = create_member("MBR-1")
        resp = api.create_care_gap(
            {"member_id": member["id"], "measure_id": sc["measure"]["id"],
             "gap_type": "PHARMACY_ADHERENCE"},
            quality_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_GAP_TYPE_MEASURE_MISMATCH)
        perf = validate_success(api.get_measure_performance(
            sc["performance"]["id"], quality_ops_headers))
        assert perf["denominator"] == 10, (
            "A rejected gap opening applies no denominator delta"
        )


class TestCareGapCycle:
    def test_gap_close_reopen_close_status_cycle(self, api, quality_ops_headers):
        """PRD §3.5: "Closing a gap — from either `OPEN` or `REOPENED`; any other
        from-state is `ERR_GAP_NOT_OPEN` — is the moment the plan gets credit."
        PRD §3.5: "Reopening is the compensation path: a `CLOSED` gap (any other
        from-state is `ERR_GAP_NOT_CLOSED`) returns to `REOPENED`, provided the
        owning cycle is in `DATA_COLLECTION` (`ERR_CYCLE_NOT_COLLECTING`) and the
        linked performance is not `LOCKED` (`ERR_PERFORMANCE_LOCKED`)."

        The gap walks OPEN -> CLOSED -> REOPENED -> CLOSED.

        Design: Difficulty/non_linear_state_machine/caregap_reopen_cycle_oscillation
        """
        sc = setup_gap_scenario(10, 20)
        gap_id = sc["gap"]["id"]

        closed = transition_gap(gap_id, "CLOSED")
        assert closed["status"] == "CLOSED"
        reopened = transition_gap(gap_id, "REOPENED")
        assert reopened["status"] == "REOPENED"
        reclosed = transition_gap(gap_id, "CLOSED")
        assert reclosed["status"] == "CLOSED", (
            "A REOPENED gap closes again — the machine is cyclic"
        )
        fetched = validate_success(api.get_care_gap(gap_id, quality_ops_headers))
        assert fetched["status"] == "CLOSED"

    def test_performance_numerator_oscillates_with_gap_cycle(
            self, api, quality_ops_headers):
        """PRD §3.5: "On a successful close, the linked performance's `numerator`
        increases by 1, `raw_value` and both stars recompute, the cycle's
        `live_weighted_stars` refreshes, and the gap's `version` increments by 1."
        PRD §3.5: "The reopen decrements the linked performance's `numerator` by 1,
        recomputes `raw_value` and both stars, refreshes live stars, and bumps the
        gap's `version` by 1."

        The numerator oscillates 10 -> 11 -> 10 -> 11 while the denominator holds
        at 21 (the gap's own opening credit).

        Design: Difficulty/non_linear_state_machine/caregap_reopen_cycle_oscillation
        """
        sc = setup_gap_scenario(10, 20)
        gap_id = sc["gap"]["id"]
        perf_id = sc["performance"]["id"]
        assert get_performance(perf_id)["denominator"] == 21

        close_gap(gap_id)
        assert get_performance(perf_id)["numerator"] == 11
        reopen_gap(gap_id)
        assert get_performance(perf_id)["numerator"] == 10
        close_gap(gap_id)
        perf = validate_success(api.get_measure_performance(perf_id,
                                                            quality_ops_headers))
        assert perf["numerator"] == 11
        assert perf["denominator"] == 21


class TestGapCloseGuards:
    def test_close_gap_with_locked_performance_rejected(self, api,
                                                        quality_ops_headers):
        """PRD §3.5: "Four guards apply, and a violation surfaces as its own error:
        the member must be `ENROLLED` (`ERR_MEMBER_NOT_ENROLLED`); the cycle that
        owns the gap's measure must be in `DATA_COLLECTION`
        (`ERR_CYCLE_NOT_COLLECTING`); the linked performance must exist and must
        not be `LOCKED` (`ERR_PERFORMANCE_LOCKED`)."

        Design: Difficulty/cross_entity_state_dependency/gap_close_blocked_by_locked_performance
        """
        sc = setup_locked_performance_scenario(5, 10, with_open_gap=True)
        assert sc["performance"]["status"] == "LOCKED"

        resp = api.transition_care_gap(sc["gap"]["id"], "CLOSED", quality_ops_headers)
        validate_error(resp, ApiErrorId.ERR_PERFORMANCE_LOCKED)
        gap = validate_success(api.get_care_gap(sc["gap"]["id"], quality_ops_headers))
        assert gap["status"] == "OPEN", "The rejected close leaves the gap OPEN"

    def test_locked_performance_unchanged_by_rejected_close(
            self, api, quality_ops_headers):
        """PRD §3.5: "Four guards apply, and a violation surfaces as its own error:
        the member must be `ENROLLED` (`ERR_MEMBER_NOT_ENROLLED`); the cycle that
        owns the gap's measure must be in `DATA_COLLECTION`
        (`ERR_CYCLE_NOT_COLLECTING`); the linked performance must exist and must
        not be `LOCKED` (`ERR_PERFORMANCE_LOCKED`)."

        The LOCKED performance's counts are untouched by the rejected close.

        Design: Difficulty/cross_entity_state_dependency/gap_close_blocked_by_locked_performance
        """
        sc = setup_locked_performance_scenario(5, 10, with_open_gap=True)
        perf_id = sc["performance"]["id"]
        denominator_after_gap_open = get_performance(perf_id)["denominator"]

        resp = api.transition_care_gap(sc["gap"]["id"], "CLOSED", quality_ops_headers)
        validate_error(resp, ApiErrorId.ERR_PERFORMANCE_LOCKED)
        perf = validate_success(api.get_measure_performance(perf_id,
                                                            quality_ops_headers))
        assert perf["numerator"] == 5, "No numerator credit from a rejected close"
        assert perf["denominator"] == denominator_after_gap_open


class TestPopulationConservation:
    def test_close_increments_numerator_only(self, api, quality_ops_headers):
        """PRD §3.5: "On a successful close, the linked performance's `numerator`
        increases by 1, `raw_value` and both stars recompute, the cycle's
        `live_weighted_stars` refreshes, and the gap's `version` increments by 1."

        The close moves the numerator 2123 -> 2124 and leaves the denominator at
        2501 (2500 plus the gap's own opening credit).

        Design: Difficulty/compensating_invariant/population_conservation_close_then_reopen
        """
        sc = setup_gap_scenario(2123, 2500)
        perf_id = sc["performance"]["id"]
        pre = get_performance(perf_id)
        assert pre["numerator"] == 2123
        assert pre["denominator"] == 2501

        close_gap(sc["gap"]["id"])
        post = validate_success(api.get_measure_performance(perf_id,
                                                            quality_ops_headers))
        assert post["numerator"] == 2124
        assert post["denominator"] == 2501, "Close never touches the denominator"

    def test_reopen_after_close_restores_numerator(self, api, quality_ops_headers):
        """PRD §3.5: "The reopen decrements the linked performance's `numerator` by
        1, recomputes `raw_value` and both stars, refreshes live stars, and bumps
        the gap's `version` by 1."

        The close/reopen pair is compensating: numerator returns to 2123 and the
        denominator is unchanged at 2501 across the whole pair.

        Design: Difficulty/compensating_invariant/population_conservation_close_then_reopen
        """
        sc = setup_gap_scenario(2123, 2500)
        perf_id = sc["performance"]["id"]

        close_gap(sc["gap"]["id"])
        reopen_gap(sc["gap"]["id"])
        perf = validate_success(api.get_measure_performance(perf_id,
                                                            quality_ops_headers))
        assert perf["numerator"] == 2123, (
            "Reopen compensates the close: numerator restored to 2123"
        )
        assert perf["denominator"] == 2501, (
            "The close/reopen pair leaves the denominator untouched"
        )


class TestDisenrollmentCascade:
    def _setup_cascade_scenario(self):
        """Cycle in DATA_COLLECTION; OUTCOME (weight 3) HIGHER_BETTER measure
        ACTIVE; DRAFT set floors 0.50/0.60/0.70/0.80; performance 12/20
        VALIDATED; one ENROLLED member with one OPEN gap (denominator 21)."""
        sc = setup_collecting_measure(
            12, 20,
            measure_kwargs={"code": "BCS", "title": "Breast Cancer Screening",
                            "measure_type": "OUTCOME"},
            floors=(0.50, 0.60, 0.70, 0.80))
        validate_performance(sc["performance"]["id"])
        member = create_member("MBR-1")
        gap = open_gap(member["id"], sc["measure"]["id"], "SCREENING")
        sc["member"] = member
        sc["gap"] = gap
        return sc

    def test_disenrollment_excludes_gaps_and_shrinks_denominator(
            self, api, quality_ops_headers):
        """PRD §3.4: "Every care gap of this member in `OPEN` or `REOPENED` status
        is moved to `EXCLUDED` (the system-driven exclusion does not require the
        gap checks that a manual exclusion does)."
        PRD §3.4: "Each such exclusion decrements the linked performance's
        `denominator` by 1 — provided that performance is not `LOCKED`, in which
        case the denominator is left alone — and recomputes the performance's
        `raw_value`, `published_star`, and `draft_star`."

        The exclusion moves the denominator 21 -> 20, so raw_value recomputes to
        0.60 and the draft star rises 2 -> 3.

        Design: Difficulty/transitive_cascade/disenrollment_cascade_depth3
        """
        sc = self._setup_cascade_scenario()
        disenroll_member(sc["member"]["id"])

        gap = validate_success(api.get_care_gap(sc["gap"]["id"], quality_ops_headers))
        assert gap["status"] == "EXCLUDED", (
            "Disenrollment moves the member's OPEN gap to EXCLUDED"
        )
        perf = validate_success(api.get_measure_performance(
            sc["performance"]["id"], quality_ops_headers))
        assert perf["denominator"] == 20
        assert perf["raw_value"] == pytest.approx(0.6)
        assert perf["draft_star"] == 3, (
            f"0.60 clears floors 0.50 and 0.60 for star 3, got {perf['draft_star']}"
        )

    def test_disenrollment_refreshes_live_weighted_stars(self, api,
                                                         quality_ops_headers):
        """PRD §3.4: "Each star recompute refreshes the owning cycle's
        `live_weighted_stars`."
        PRD §2.7: "The cycle's `live_weighted_stars` is the continuously refreshed
        preview of the overall rating: a weighted mean over the cycle's `ACTIVE`
        measures whose performance status is `VALIDATED` or `LOCKED` and whose
        basis star is non-null, using the best-available basis — the
        `published_star` when the cycle has a `PUBLISHED` set, otherwise the
        `draft_star`."

        The single VALIDATED performance's draft star moves 2 -> 3 through the
        cascade, so the live preview moves 2.0 -> 3.0.

        Design: Difficulty/transitive_cascade/disenrollment_cascade_depth3
        """
        sc = self._setup_cascade_scenario()
        live_pre = get_cycle(sc["cycle"]["id"])["live_weighted_stars"]
        assert live_pre == pytest.approx(2.0), (
            f"With the gap open the raw is 0.57 (star 2); got {live_pre}"
        )

        disenroll_member(sc["member"]["id"])
        live_post = validate_success(api.get_rating_cycle(sc["cycle"]["id"],
                                                          quality_ops_headers))
        assert live_post["live_weighted_stars"] == pytest.approx(3.0), (
            "The star recompute from the exclusion refreshes live_weighted_stars "
            "to 3.0"
        )


class TestPharmacyInterventions:
    def test_intervene_on_non_pharmacy_gap_rejected(self, api, quality_ops_headers):
        """PRD §3.5: "Against an `OPEN` or `REOPENED` gap (otherwise
        `ERR_GAP_NOT_OPEN`) whose `gap_type` is `PHARMACY_ADHERENCE` — intervention
        against any other gap type is rejected with
        `ERR_INTERVENTION_GAP_TYPE_MISMATCH` (HTTP 400) — a `QualityOps` specialist
        records an outreach intervention by naming a `channel` of `CALL`, `MAIL`,
        `SMS`, or `PHARMACIST_CONSULT`."

        Design: Corner/validations/intervene_on_non_pharmacy_gap_rejected
        """
        sc = setup_gap_scenario(5, 10, gap_type="SCREENING")
        resp = api.intervene_care_gap(sc["gap"]["id"], "CALL", quality_ops_headers)
        validate_error(resp, ApiErrorId.ERR_INTERVENTION_GAP_TYPE_MISMATCH)
        gap = validate_success(api.get_care_gap(sc["gap"]["id"], quality_ops_headers))
        assert gap["intervention_count"] == 0

    def test_intervention_cap_enforced(self, api, quality_ops_headers):
        """PRD §3.5: "The gap's `intervention_count` starts at 0 and increases by 1
        with each recorded intervention; `last_intervention_channel` records the
        channel used, staying null until the first."
        PRD §3.5: "A gap caps at 3 interventions — recording a fourth is rejected
        with `ERR_INTERVENTION_LIMIT_REACHED` — and each recorded intervention bumps
        the gap's `version` by 1."

        Design: Corner/validations/intervention_cap_enforced
        """
        sc = setup_gap_scenario(
            0, 0, gap_type="PHARMACY_ADHERENCE",
            measure_kwargs={"code": "SPD", "title": "Statin Adherence",
                            "domain": "DRUG_SAFETY", "measure_type": "OUTCOME",
                            "data_source": "PHARMACY_PDE"})
        gap_id = sc["gap"]["id"]

        intervene(gap_id, "CALL")
        intervene(gap_id, "MAIL")
        third = intervene(gap_id, "SMS")
        assert third["intervention_count"] == 3
        assert third["last_intervention_channel"] == "SMS"

        resp = api.intervene_care_gap(gap_id, "PHARMACIST_CONSULT", quality_ops_headers)
        validate_error(resp, ApiErrorId.ERR_INTERVENTION_LIMIT_REACHED)
        gap = validate_success(api.get_care_gap(gap_id, quality_ops_headers))
        assert gap["intervention_count"] == 3, "The cap holds at 3 interventions"
        assert gap["last_intervention_channel"] == "SMS"
