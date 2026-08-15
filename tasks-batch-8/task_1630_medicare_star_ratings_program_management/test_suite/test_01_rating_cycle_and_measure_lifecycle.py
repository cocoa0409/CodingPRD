"""Rating cycle lifecycle, measure inventory lifecycle, and official publication."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_measure,
    create_cycle,
    create_measure,
    get_cycle,
    setup_collecting_measure,
    setup_cycle_in_cutpoint_review,
    setup_four_measure_review_cycle,
    transition_cycle,
    transition_measure,
    validate_error,
    validate_success,
)


class TestCycleCreation:
    def test_cycle_year_order_constraint_rejected(self, api, stars_admin_headers):
        """PRD §3.1: "A `StarsAdmin` opens a rating cycle by supplying the
        `measurement_year` (the calendar year the data describes, for example 2026),
        the `rating_year` (the year CMS publishes the stars, which must be strictly
        greater than the `measurement_year`), and the `benchmark_pmpm` — the
        benchmark payment per member per month in dollars, which must be greater
        than zero and serves as the rebate base."
        PRD §2.11: "`rating_year` strictly greater than `measurement_year`.
        Violations are `ERR_INVALID_REQUEST` (HTTP 400) on all write endpoints."

        Design: Corner/entities/cycle_year_order_constraint_rejected
        """
        resp = api.create_rating_cycle(
            {"measurement_year": 2028, "rating_year": 2027, "benchmark_pmpm": 950.0},
            stars_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCycleTransitions:
    def test_cycle_skip_transition_invalid(self, api, stars_admin_headers):
        """PRD §3.9: "When every performance of the cycle is `LOCKED`, the
        administrator moves the cycle from `DATA_COLLECTION` to `CUTPOINT_REVIEW`;
        the cycle must currently be `DATA_COLLECTION` (else
        `ERR_INVALID_STATE_TRANSITION`), and any performance still `REPORTED` or
        `VALIDATED` blocks the move with `ERR_PERFORMANCES_NOT_LOCKED` (vacuously
        satisfied when the cycle has no performances)."

        Design: Corner/state_machines/cycle_skip_transition_invalid
        """
        cycle = create_cycle()
        resp = api.transition_rating_cycle(cycle["id"], "CUTPOINT_REVIEW",
                                           stars_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        fetched = validate_success(api.get_rating_cycle(cycle["id"], stars_admin_headers))
        assert fetched["status"] == "SETUP", "Rejected skip leaves the cycle in SETUP"

    def test_begin_review_requires_all_locked(self, api, stars_admin_headers):
        """PRD §2.5: "Entering `CUTPOINT_REVIEW` requires that every measure
        performance recorded for the cycle has reached `LOCKED`; the check is
        vacuously true when the cycle has no performances yet."
        PRD §2.5: "A cycle that still has `REPORTED` or `VALIDATED` performances
        cannot enter review and the transition is rejected with
        `ERR_PERFORMANCES_NOT_LOCKED`."

        Design: Corner/state_machines/begin_review_requires_all_locked
        """
        sc = setup_collecting_measure(numerator=5, denominator=10)
        cycle_id = sc["cycle"]["id"]
        assert sc["performance"]["status"] == "REPORTED"

        resp = api.transition_rating_cycle(cycle_id, "CUTPOINT_REVIEW",
                                           stars_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PERFORMANCES_NOT_LOCKED)
        fetched = validate_success(api.get_rating_cycle(cycle_id, stars_admin_headers))
        assert fetched["status"] == "DATA_COLLECTION", (
            "Rejected review entry leaves the cycle in DATA_COLLECTION"
        )

    def test_reopen_reverts_locked_performances(self, api, stars_admin_headers,
                                                stars_analyst_headers):
        """PRD §2.5: "Reopening from `CUTPOINT_REVIEW` back to `DATA_COLLECTION`
        reverts every `LOCKED` performance of the cycle to `VALIDATED` — data
        collection may be reopened after review begins, and previously published
        cut point sets are **not** unpublished by the reopen."

        Design: Corner/state_machines/reopen_reverts_locked_performances
        """
        sc = setup_cycle_in_cutpoint_review(numerator=5, denominator=10)
        cycle_id = sc["cycle"]["id"]
        perf_id = sc["performance"]["id"]
        assert sc["performance"]["status"] == "LOCKED"

        cycle = transition_cycle(cycle_id, "DATA_COLLECTION")
        assert cycle["status"] == "DATA_COLLECTION"
        perf = validate_success(api.get_measure_performance(perf_id, stars_analyst_headers))
        assert perf["status"] == "VALIDATED", (
            "Reopening data collection reverts the LOCKED performance to VALIDATED"
        )


class TestOfficialPublication:
    def test_publish_official_computes_official_rating(self, api, stars_admin_headers):
        """PRD §3.9: "On success the cycle's `official_overall_stars` is computed as
        the weighted overall stars over `LOCKED` performances on the published
        basis, including the improvement pseudo-measure when computable;
        `official_improvement_star` records the improvement star on the published
        basis (null when the eligible set is empty); and `official_rebate_amount`
        is the rebate projection at the official stars per the tier rule below."
        PRD §3.9: "From `OFFICIAL_PUBLISHED`, the administrator finally closes the
        cycle to `CLOSED`, terminal, with the usual from-state check and a version
        increment."

        Fixture arithmetic (published basis): stars 3/3/3/3 on weights 1/3/4/3 give
        33/11; eligible measures tie (3 vs 3) and decline (3 vs 4), so the
        improvement score -0.5 bands to star 1; (33 + 5) / (11 + 5) = 2.375 snaps
        to 2.5 on the half-star grid; 2.5 is below 3.5 so the tier rate is 0.0.

        Design: Corner/state_machines/publish_official_computes_official_rating
        """
        sc = setup_four_measure_review_cycle(with_draft_set=True, publish=True)
        cycle_id = sc["cycle"]["id"]

        cycle = transition_cycle(cycle_id, "OFFICIAL_PUBLISHED")
        assert cycle["status"] == "OFFICIAL_PUBLISHED"

        fetched = validate_success(api.get_rating_cycle(cycle_id, stars_admin_headers))
        assert fetched["official_overall_stars"] == pytest.approx(2.5), (
            f"official_overall_stars must be 2.5, got {fetched['official_overall_stars']}"
        )
        assert fetched["official_improvement_star"] == 1, (
            f"official_improvement_star must be 1, got {fetched['official_improvement_star']}"
        )
        assert fetched["official_rebate_amount"] == pytest.approx(0.0), (
            "2.5 stars is below the 3.5 tier floor, so the official rebate is 0.00"
        )

        closed = transition_cycle(cycle_id, "CLOSED")
        assert closed["status"] == "CLOSED"

        resp = api.transition_rating_cycle(cycle_id, "DATA_COLLECTION",
                                           stars_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        fetched = validate_success(api.get_rating_cycle(cycle_id, stars_admin_headers))
        assert fetched["status"] == "CLOSED", "CLOSED is terminal"


class TestMeasureInventory:
    def test_measure_creation_computes_weight_and_initial_state(
            self, api, stars_admin_headers, stars_analyst_headers):
        """PRD §2.6: "The `measure_type` is `PROCESS`, `OUTCOME`, or
        `PATIENT_EXPERIENCE`, and it determines the measure's computed `weight`: a
        `PROCESS` measure weighs 1, an `OUTCOME` measure weighs 3, and a
        `PATIENT_EXPERIENCE` measure weighs 4."
        PRD §3.1: "A newly registered measure is `DRAFT` with its `weight` derived
        from its `measure_type` as specified in §2.6."

        Design: Corner/entities/measure_creation_computes_weight_and_initial_state
        """
        cycle = create_cycle()
        cases = [
            ("BCS", "STAYING_HEALTHY", "PROCESS", "HEDIS", 1),
            ("CBP", "CHRONIC_CARE", "OUTCOME", "HEDIS", 3),
            ("CNC", "MEMBER_EXPERIENCE", "PATIENT_EXPERIENCE", "CAHPS", 4),
        ]
        for code, domain, measure_type, data_source, expected_weight in cases:
            measure = create_measure(cycle["id"], code=code, domain=domain,
                                     measure_type=measure_type, data_source=data_source)
            assert measure["weight"] == expected_weight, (
                f"{measure_type} must weigh {expected_weight}, got {measure['weight']}"
            )
            assert measure["status"] == "DRAFT", "A newly registered measure is DRAFT"
            assert isinstance(measure["version"], int)

    def test_measure_retire_terminal_lockdown(self, api, stars_analyst_headers):
        """PRD §3.1: "Retirement moves an `ACTIVE` measure to `RETIRED` and is
        forbidden once the owning cycle is `OFFICIAL_PUBLISHED` or `CLOSED`; a
        retired measure drops out of every future weighted and improvement input
        set, though historical performances remain on record."
        PRD §2.11: "6. **Generic transition from-state** — a transition request
        whose target does not match a legal transition out of the entity's current
        state is `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/measure_retire_terminal_lockdown
        """
        cycle = create_cycle()
        measure = create_active_measure(cycle["id"])

        retired = transition_measure(measure["id"], "RETIRED")
        assert retired["status"] == "RETIRED"

        resp = api.transition_measure(measure["id"], "RETIRED", stars_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        fetched = validate_success(api.get_measure(measure["id"], stars_analyst_headers))
        assert fetched["status"] == "RETIRED", "RETIRED is terminal for a measure"
