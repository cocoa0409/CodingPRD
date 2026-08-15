"""Campus composite index and system dashboard projection (PRD §3.1, §3.3)."""
import pytest

from test_helpers import (
    create_system,
    finalize_rating,
    get_success_data,
    setup_self_study_term,
    submit_and_finalize,
    submit_rating,
    validate_success,
)

TWO_STANDARD_MATRIX = [("L1", "Leadership 1", "LEADERSHIP", 30, 0),
                       ("T1", "Teaching 1", "LEARNING", 50, 0)]
TWO_CAMPUS_LIST = [("Campus A", 500), ("Campus B", 300)]


def _setup_two_campus_two_standard(ratings):
    """Dual-campus context in SELF_STUDY with all four ratings then finalized."""
    ctx = setup_self_study_term(
        system_name="Dual County Schools", system_type="DISTRICT",
        campuses=TWO_CAMPUS_LIST, standards=TWO_STANDARD_MATRIX,
        rating_values=ratings)
    for key in sorted(ctx["ratings"].keys()):
        submit_and_finalize(ctx["ratings"][key]["id"])
    return ctx


class TestCampusScopedVsSystemProjected:
    def test_campus_persisted_composite_and_dashboard_projection(self, api,
                                                                 officer_headers):
        """PRD §3.3: "Otherwise, take each such rating's `rating` multiplied by
        its standard's `weight_pct`, sum those products into a numerator, and
        sum the participating standards' `weight_pct` values into a denominator;
        divide the numerator by the denominator, multiply by 100 divided by the
        rubric maximum of 4, and round the result half-up to 2 decimal places."
        PRD §3.1: "A read-only dashboard projection aggregates a system's
        progress on demand: it reports `projected_index_pct`,
        `campus_count_in_scope`, and `finalized_rating_count`, computed across
        every campus with `campus_status` of `IN_SCOPE` using the same
        weighted-index rule as the per-campus composite (§3.3)."

        Design: Difficulty/dual_variant_calc/campus_index_campus_scoped_vs_system_projected
        """
        ctx = _setup_two_campus_two_standard(
            {(0, 0): 4, (0, 1): 3, (1, 0): 2, (1, 1): 1})

        campus_a = get_success_data(
            api.get_campus(ctx["campuses"][0]["id"], officer_headers))
        # (4*30 + 3*50) / (30+50) * 25 = 270/80*25 = 84.375 -> 84.38
        assert campus_a["composite_index_pct"] == pytest.approx(84.38, abs=0.001)

        dashboard = validate_dashboard(api, ctx, officer_headers)
        # (270 + 110) / 160 * 25 = 59.375 -> 59.38
        assert dashboard["projected_index_pct"] == pytest.approx(59.38, abs=0.001)
        assert dashboard["campus_count_in_scope"] == 2
        assert dashboard["finalized_rating_count"] == 4
        assert dashboard["projected_index_pct"] != pytest.approx(
            campus_a["composite_index_pct"], abs=0.001), \
            "per-campus persisted composite and system projection are distinct variants"

    def test_second_campus_composite_uses_own_ratings_only(self, api,
                                                           officer_headers):
        """PRD §3.3: "Otherwise, take each such rating's `rating` multiplied by
        its standard's `weight_pct`, sum those products into a numerator, and
        sum the participating standards' `weight_pct` values into a denominator;
        divide the numerator by the denominator, multiply by 100 divided by the
        rubric maximum of 4, and round the result half-up to 2 decimal places."
        PRD §3.3: "any finalize or reopen on one of the campus's ratings
        triggers recomputation for that campus."

        Design: Difficulty/dual_variant_calc/campus_index_campus_scoped_vs_system_projected
        """
        ctx = _setup_two_campus_two_standard(
            {(0, 0): 4, (0, 1): 3, (1, 0): 2, (1, 1): 1})

        campus_b = get_success_data(
            api.get_campus(ctx["campuses"][1]["id"], officer_headers))
        # (2*30 + 1*50) / 80 * 25 = 110/80*25 = 34.375 -> 34.38
        assert campus_b["composite_index_pct"] == pytest.approx(34.38, abs=0.001)

        dashboard = validate_dashboard(api, ctx, officer_headers)
        assert dashboard["projected_index_pct"] == pytest.approx(59.38, abs=0.001)
        assert dashboard["finalized_rating_count"] == 4


class TestCompositeRoundingOrder:
    def test_half_up_rounding_84375_becomes_8438(self, api, officer_headers):
        """PRD §2.7: "The campus composite index (`composite_index_pct`) and
        goal attainment (`attainment_pct`) are each rounded half-up to exactly
        2 decimal places."
        PRD §3.3: "divide the numerator by the denominator, multiply by 100
        divided by the rubric maximum of 4, and round the result half-up to 2
        decimal places."

        Design: Difficulty/combinatorial_formula/composite_index_nested_rounding_order
        """
        ctx = setup_self_study_term(
            system_name="Rounding County", standards=TWO_STANDARD_MATRIX,
            rating_values={(0, 0): 4, (0, 1): 3})
        for key in sorted(ctx["ratings"].keys()):
            submit_and_finalize(ctx["ratings"][key]["id"])
        campus = get_success_data(
            api.get_campus(ctx["campuses"][0]["id"], officer_headers))
        # (4*30 + 3*50)/80 * 25 = 84.375 -> single final round half-up -> 84.38
        assert campus["composite_index_pct"] == pytest.approx(84.38, abs=0.001)

    def test_half_up_rounding_90625_becomes_9063(self, api, officer_headers):
        """PRD §2.7: "The campus composite index (`composite_index_pct`) and
        goal attainment (`attainment_pct`) are each rounded half-up to exactly
        2 decimal places."

        Design: Difficulty/combinatorial_formula/composite_index_nested_rounding_order
        """
        ctx = setup_self_study_term(
            system_name="Rounding County B", standards=TWO_STANDARD_MATRIX,
            rating_values={(0, 0): 3, (0, 1): 4})
        for key in sorted(ctx["ratings"].keys()):
            submit_and_finalize(ctx["ratings"][key]["id"])
        campus = get_success_data(
            api.get_campus(ctx["campuses"][0]["id"], officer_headers))
        # (3*30 + 4*50)/80 * 25 = 290/80*25 = 90.625 -> 90.63
        assert campus["composite_index_pct"] == pytest.approx(90.63, abs=0.001)


class TestFinalizeCascade:
    def test_finalize_updates_composite_campus_version_and_dashboard(
            self, api, officer_headers):
        """PRD §3.3: "On finalization the server stamps `finalized_at` with the
        current instant, increments the rating's `version`, and recomputes the
        campus composite index — which itself increments the campus's `version`."
        PRD §3.1: "A read-only dashboard projection aggregates a system's
        progress on demand: it reports `projected_index_pct`,
        `campus_count_in_scope`, and `finalized_rating_count`, computed across
        every campus with `campus_status` of `IN_SCOPE` using the same
        weighted-index rule as the per-campus composite (§3.3)."

        Design: Difficulty/transitive_cascade/finalize_cascade_rating_campus_dashboard
        """
        ctx = setup_self_study_term(system_name="Cascade School")
        rating_id = ctx["ratings"][(0, 0)]["id"]
        campus_id = ctx["campuses"][0]["id"]
        campus_before = get_success_data(api.get_campus(campus_id, officer_headers))

        submitted = submit_rating(rating_id)
        finalized = validate_finalized(api, rating_id, officer_headers)
        assert finalized["status"] == "FINALIZED"

        campus_after = get_success_data(api.get_campus(campus_id, officer_headers))
        # rating 3, weight 100 -> 3*100/100*25 = 75.00
        assert campus_after["composite_index_pct"] == pytest.approx(75.00, abs=0.001)
        assert campus_after["version"] == campus_before["version"] + 1, \
            "the composite recompute increments the campus's version exactly once"
        assert finalized["version"] == submitted["version"] + 1

        dashboard = validate_dashboard(api, ctx, officer_headers)
        assert dashboard["projected_index_pct"] == pytest.approx(75.00, abs=0.001)
        assert dashboard["campus_count_in_scope"] == 1
        assert dashboard["finalized_rating_count"] == 1

    def test_finalize_stamps_finalized_at_and_dashboard_counts(
            self, api, officer_headers):
        """PRD §3.3: "On finalization the server stamps `finalized_at` with the
        current instant, increments the rating's `version`, and recomputes the
        campus composite index — which itself increments the campus's `version`."

        Design: Difficulty/transitive_cascade/finalize_cascade_rating_campus_dashboard
        """
        ctx = setup_self_study_term(system_name="Cascade School B")
        rating = ctx["ratings"][(0, 0)]
        assert rating["finalized_at"] is None

        submit_rating(rating["id"])
        finalized = validate_finalized(api, rating["id"], officer_headers)
        assert finalized["finalized_at"] is not None
        assert finalized["version"] >= rating["version"] + 2, \
            "submit and finalize each increment the rating's version"

        dashboard = validate_dashboard(api, ctx, officer_headers)
        assert dashboard["finalized_rating_count"] == 1
        assert dashboard["campus_count_in_scope"] == 1


class TestReopenConservation:
    def test_reopen_refinalize_cycle_conserves_composite(self, api, officer_headers):
        """PRD §3.3: "the rating's `finalized_at` returns to null and the
        composite index is recomputed with this rating now excluded, again
        incrementing both versions."
        PRD §3.3: "Otherwise, take each such rating's `rating` multiplied by its
        standard's `weight_pct`, sum those products into a numerator, and sum
        the participating standards' `weight_pct` values into a denominator;
        divide the numerator by the denominator, multiply by 100 divided by the
        rubric maximum of 4, and round the result half-up to 2 decimal places."

        Design: Difficulty/compensating_invariant/reopen_finalize_conserves_composite_index
        """
        ctx = setup_self_study_term(system_name="Invariant School")
        rating_id = ctx["ratings"][(0, 0)]["id"]
        campus_id = ctx["campuses"][0]["id"]
        submit_and_finalize(rating_id)
        campus = get_success_data(api.get_campus(campus_id, officer_headers))
        assert campus["composite_index_pct"] == pytest.approx(75.00, abs=0.001)

        # Compensating pair: reopen -> resubmit -> refinalize with unchanged rating.
        get_success_data(api.reopen_rating(rating_id, officer_headers))
        submit_rating(rating_id)
        finalize_rating(rating_id)
        campus = get_success_data(api.get_campus(campus_id, officer_headers))
        assert campus["composite_index_pct"] == pytest.approx(75.00, abs=0.001), \
            "the forward+compensating cycle must restore the exact composite value"

    def test_multi_rating_reopen_refinalize_conserves_composite(
            self, api, officer_headers):
        """PRD §3.3: "the rating's `finalized_at` returns to null and the
        composite index is recomputed with this rating now excluded, again
        incrementing both versions."

        Design: Difficulty/compensating_invariant/reopen_finalize_conserves_composite_index
        """
        ctx = setup_self_study_term(
            system_name="Invariant School B", standards=TWO_STANDARD_MATRIX,
            rating_values={(0, 0): 4, (0, 1): 2})
        campus_id = ctx["campuses"][0]["id"]
        for key in sorted(ctx["ratings"].keys()):
            submit_and_finalize(ctx["ratings"][key]["id"])
        campus = get_success_data(api.get_campus(campus_id, officer_headers))
        # (4*30 + 2*50)/80 * 25 = 220/80*25 = 68.75
        assert campus["composite_index_pct"] == pytest.approx(68.75, abs=0.001)

        t1 = ctx["ratings"][(0, 1)]["id"]
        get_success_data(api.reopen_rating(t1, officer_headers))
        campus = get_success_data(api.get_campus(campus_id, officer_headers))
        # only L1=4 (weight 30) remains FINALIZED -> 4*30/30*25 = 100.00
        assert campus["composite_index_pct"] == pytest.approx(100.00, abs=0.001)

        submit_rating(t1)
        finalize_rating(t1)
        campus = get_success_data(api.get_campus(campus_id, officer_headers))
        assert campus["composite_index_pct"] == pytest.approx(68.75, abs=0.001)


class TestDashboardInputSetAndShape:
    def test_out_of_scope_campus_excluded_from_projection(self, api,
                                                          officer_headers):
        """PRD §3.1: "A read-only dashboard projection aggregates a system's
        progress on demand: it reports `projected_index_pct`,
        `campus_count_in_scope`, and `finalized_rating_count`, computed across
        every campus with `campus_status` of `IN_SCOPE` using the same
        weighted-index rule as the per-campus composite (§3.3)."
        PRD §3.1: "A campus with `campus_status` of `OUT_OF_SCOPE` or
        `WITHDRAWN` is excluded from composite and billing counts."

        Design: Corner/calculations/survey_input_set_excludes_out_of_scope_campus
        """
        ctx = setup_self_study_term(
            system_name="Filter County", system_type="DISTRICT",
            campuses=[("A", 100), ("B", 200)],
            rating_values={(0, 0): 4, (1, 0): 1})
        submit_and_finalize(ctx["ratings"][(0, 0)]["id"])
        submit_rating(ctx["ratings"][(1, 0)]["id"])
        # Campus B has no FINALIZED rating, so scope-out is admissible.
        get_success_data(api.scope_out_campus(ctx["campuses"][1]["id"],
                                              officer_headers))

        dashboard = validate_dashboard(api, ctx, officer_headers)
        # only campus A's FINALIZED rating 4 (weight 100) counts: 100.00
        assert dashboard["projected_index_pct"] == pytest.approx(100.00, abs=0.001)
        assert dashboard["campus_count_in_scope"] == 1
        assert dashboard["finalized_rating_count"] == 1

    def test_dashboard_shape_for_empty_system(self, api, officer_headers):
        """PRD §3.1: "A read-only dashboard projection aggregates a system's
        progress on demand: it reports `projected_index_pct`,
        `campus_count_in_scope`, and `finalized_rating_count`".
        PRD §3.3: "If that set is empty, `composite_index_pct` is null."

        Design: Corner/endpoints/computed_read_dashboard_shape
        """
        system = create_system(name="Empty County", system_type="DISTRICT")
        resp = api.get_system_dashboard(system["id"], officer_headers)
        dashboard = get_success_data(resp)
        assert dashboard["campus_count_in_scope"] == 0
        assert dashboard["finalized_rating_count"] == 0
        assert dashboard["projected_index_pct"] is None, \
            "with no finalized ratings the index set is empty and therefore null"

    def test_composite_visible_immediately_after_finalize(self, api,
                                                          officer_headers):
        """PRD §3.3: "On finalization the server stamps `finalized_at` with the
        current instant, increments the rating's `version`, and recomputes the
        campus composite index — which itself increments the campus's `version`."

        Design: Corner/consistency_model/immediate_consistency_composite_visible_in_same_request
        """
        ctx = setup_self_study_term(system_name="Immediate School",
                                    rating_values={(0, 0): 4})
        submit_and_finalize(ctx["ratings"][(0, 0)]["id"])
        campus = get_success_data(
            api.get_campus(ctx["campuses"][0]["id"], officer_headers))
        # rating 4, weight 100 -> 4*100/100*25 = 100.00, visible with no lag
        assert campus["composite_index_pct"] == pytest.approx(100.00, abs=0.001)


# ---------------------------------------------------------------------------
# Module-local helpers
# ---------------------------------------------------------------------------

def validate_dashboard(api, ctx, headers):
    resp = api.get_system_dashboard(ctx["system"]["id"], headers)
    assert resp.status_code == 200, f"dashboard read failed: {resp.text}"
    body = resp.json()
    assert body["response_type"] == "object"
    dashboard = body["data"]
    for field in ("projected_index_pct", "campus_count_in_scope",
                  "finalized_rating_count"):
        assert field in dashboard, f"dashboard must report {field}"
    return dashboard


def validate_finalized(api, rating_id, headers):
    return validate_success(api.finalize_rating(rating_id, headers))
