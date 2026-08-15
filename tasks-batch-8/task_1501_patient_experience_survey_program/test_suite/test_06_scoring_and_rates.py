"""Response-rate denominator filtering, independent composite computation, the
RAW vs MODE_ADJUSTED divergence, and the star-rating minimum-N guard
(PRD §3.6)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_scored_snapshot,
    create_response_import_payload,
    get_cycle,
    get_success_data,
    import_responses,
    make_vendor_headers,
    record_response,
    set_clock,
    setup_cycle_in_state,
    setup_program,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestResponseRateDenominatorFiltering:
    def test_response_rate_denominator_state_filtering(self, api):
        """PRD §3.6: "The `eligible_denominator` counts the cycle's cases in
        `IN_FIELD`, `RESPONDED`, or `NONRESPONSE` — excluding `SAMPLED`,
        `UNDELIVERABLE`, `EXCLUDED_POST_SAMPLE`, and `VOIDED` cases. The
        `completed_responses` counts the cycle's cases in `RESPONDED` whose
        non-voided response is `ACCEPTED` or `INCLUDED`. The `response_rate`
        is 100 times the completed count divided by the denominator, rounded
        half-up to two decimal places, and is null while the denominator is
        zero."

        Design: Corner/calculations/response_rate_denominator_state_filtering
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CA1"), "FIELDING", discharge_count=30)
        case_ids = ctx["case_ids"]
        get_success_data(api.mark_undeliverable(
            case_ids[0], make_vendor_headers(ctx["vendor"]["id"])))
        import_responses(case_ids[1:26], ctx["vendor"]["id"], mode_used="MAIL",
                         score=4)

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["eligible_denominator"] == 29
        assert cycle["completed_responses"] == 25
        assert cycle["response_rate"] == pytest.approx(86.21, abs=0.001)
        assert cycle["sampled_count"] == 30

    def test_undeliverable_case_drops_out_of_denominator(self, api):
        """PRD §3.4: "The case's `billing_status` flips from `CHARGED` to
        `CREDITED`, its postage is credited back to the vendor's remaining
        budget, and the cycle's `eligible_denominator` and `response_rate` are
        recomputed — an undeliverable case no longer counts toward the
        denominator."
        PRD §3.6: "The `response_rate` is 100 times the completed count divided
        by the denominator, rounded half-up to two decimal places"

        Design: Corner/calculations/response_rate_denominator_state_filtering
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CA1B"), "FIELDING", discharge_count=2)
        case_ids = ctx["case_ids"]
        before = get_cycle(ctx["cycle"]["id"])
        assert before["eligible_denominator"] == 2

        get_success_data(api.mark_undeliverable(
            case_ids[0], make_vendor_headers(ctx["vendor"]["id"])))
        mid = get_cycle(ctx["cycle"]["id"])
        assert mid["eligible_denominator"] == 1

        record_response(case_ids[1], ctx["vendor"]["id"])
        after = get_cycle(ctx["cycle"]["id"])
        assert after["eligible_denominator"] == 1
        assert after["completed_responses"] == 1
        assert after["response_rate"] == pytest.approx(100.0, abs=0.001)


class TestTopBoxCompositesIndependent:
    def test_topbox_composites_computed_independently(self, api):
        """PRD §3.6: "For each composite, the **raw** view counts a response as
        top-box when its raw composite score equals 4. The **mode-adjusted**
        view first shifts each response's composite score by the coefficient of
        its `mode_used` — 0.0 for `MAIL`, negative 0.5 for `PHONE` — and counts
        it as top-box when the adjusted score is at least 3.75."
        PRD §3.6: "Each percentage is the count of top-box responses divided by
        the completed-responses count, multiplied by 100, rounded half-up to
        two decimal places"

        Design: Corner/calculations/topbox_composites_computed_independently
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CA2"), "FIELDING", discharge_count=25)
        # nurse 4 / doctor 3 / cleanliness 4 / overall 3 for all 25 MAIL
        # responses: raw top-box per composite is 100/0/100/0.
        payload = create_response_import_payload(
            ctx["case_ids"], mode_used="MAIL",
            nurse_comm_score=4, doctor_comm_score=3, cleanliness_score=4,
            overall_rating_score=3)
        get_success_data(api.import_responses(
            payload, make_vendor_headers(ctx["vendor"]["id"])))
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        get_success_data(api.begin_scoring(ctx["cycle"]["id"], ADMIN))

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["scored_raw_composite_pcts"] == {
            "nurse_comm": pytest.approx(100.0, abs=0.001),
            "doctor_comm": pytest.approx(0.0, abs=0.001),
            "cleanliness": pytest.approx(100.0, abs=0.001),
            "overall_rating": pytest.approx(0.0, abs=0.001),
        }
        # MAIL coefficient is 0.0, so the adjusted view equals the raw view.
        assert cycle["scored_adjusted_composite_pcts"] == {
            "nurse_comm": pytest.approx(100.0, abs=0.001),
            "doctor_comm": pytest.approx(0.0, abs=0.001),
            "cleanliness": pytest.approx(100.0, abs=0.001),
            "overall_rating": pytest.approx(0.0, abs=0.001),
        }

    def test_topbox_per_composite_split(self, api):
        """PRD §3.6: "For each composite, the **raw** view counts a response as
        top-box when its raw composite score equals 4."
        PRD §3.6: "Each percentage is the count of top-box responses divided by
        the completed-responses count, multiplied by 100, rounded half-up to
        two decimal places; when the completed count is zero the percentage is
        null."

        Design: Corner/calculations/topbox_composites_computed_independently
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CA2B"), "FIELDING", discharge_count=25)
        # nurse 4 / doctor 3 / cleanliness 4 / overall 3 for all 25 responses.
        payload = create_response_import_payload(
            ctx["case_ids"], mode_used="MAIL",
            nurse_comm_score=4, doctor_comm_score=3, cleanliness_score=4,
            overall_rating_score=3)
        get_success_data(api.import_responses(
            payload, make_vendor_headers(ctx["vendor"]["id"])))
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        get_success_data(api.begin_scoring(ctx["cycle"]["id"], ADMIN))

        cycle = get_cycle(ctx["cycle"]["id"])
        assert_scored_snapshot(cycle)
        expected = {
            "nurse_comm": 100.0,
            "doctor_comm": 0.0,
            "cleanliness": 100.0,
            "overall_rating": 0.0,
        }
        for key, pct in expected.items():
            assert cycle["scored_raw_composite_pcts"][key] == pytest.approx(
                pct, abs=0.001), f"raw {key}"
        # MAIL coefficient is 0.0, so the adjusted view equals the raw view.
        for key, pct in expected.items():
            assert cycle["scored_adjusted_composite_pcts"][key] == (
                pytest.approx(pct, abs=0.001)), f"adjusted {key}"


class TestRawVsModeAdjustedDivergence:
    def _mixed_mode_scored_cycle(self, api, name):
        """25 responses, all raw-4: 10 MAIL + 15 PHONE (PRD §3.6 fixtures)."""
        ctx = setup_cycle_in_state(
            setup_program(name=name, admin_mode="MIXED_MODE"),
            "FIELDING", discharge_count=25, mode_assigned="MAIL",
            target_sample_size=300)
        import_responses(ctx["case_ids"][0:10], ctx["vendor"]["id"],
                         mode_used="MAIL", score=4)
        import_responses(ctx["case_ids"][10:25], ctx["vendor"]["id"],
                         mode_used="PHONE", score=4)
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        get_success_data(api.begin_scoring(ctx["cycle"]["id"], ADMIN))
        return get_cycle(ctx["cycle"]["id"]), ctx

    def test_topbox_raw_vs_mode_adjusted_on_cycle(self, api):
        """PRD §3.6: "For each composite, the **raw** view counts a response as
        top-box when its raw composite score equals 4. The **mode-adjusted**
        view first shifts each response's composite score by the coefficient of
        its `mode_used` — 0.0 for `MAIL`, negative 0.5 for `PHONE` — and counts
        it as top-box when the adjusted score is at least 3.75. A `PHONE`
        response with a raw 4 therefore adjusts to 3.5 and does not count, so
        whenever any top-box phone response exists, the adjusted percentages
        sit strictly below the raw ones."

        Design: Difficulty/dual_variant_calc/topbox_raw_vs_mode_adjusted_on_cycle
        """
        cycle, _ctx = self._mixed_mode_scored_cycle(api, "P-DV1")
        assert cycle["scored_raw_composite_pcts"]["overall_rating"] == (
            pytest.approx(100.0, abs=0.001))
        assert cycle["scored_adjusted_composite_pcts"]["overall_rating"] == (
            pytest.approx(40.0, abs=0.001))

    def test_identical_data_yields_distinct_raw_and_adjusted(self, api):
        """PRD §3.6: "A `PHONE` response with a raw 4 therefore adjusts to 3.5
        and does not count, so whenever any top-box phone response exists, the
        adjusted percentages sit strictly below the raw ones."
        PRD §3.6: "Beginning scoring freezes the analytical snapshot:
        `scored_raw_composite_pcts` and `scored_adjusted_composite_pcts` hold
        the raw and mode-adjusted top-box percentages for the four composites
        keyed `nurse_comm`, `doctor_comm`, `cleanliness`, and
        `overall_rating`"

        Design: Difficulty/dual_variant_calc/topbox_raw_vs_mode_adjusted_on_cycle
        """
        cycle, _ctx = self._mixed_mode_scored_cycle(api, "P-DV1B")
        assert_scored_snapshot(cycle)
        # Identical response data drives all four composites identically.
        for key in ("nurse_comm", "doctor_comm", "cleanliness",
                    "overall_rating"):
            assert cycle["scored_raw_composite_pcts"][key] == pytest.approx(
                100.0, abs=0.001), f"raw {key}"
            assert cycle["scored_adjusted_composite_pcts"][key] == (
                pytest.approx(40.0, abs=0.001)), f"adjusted {key}"
        assert cycle["scored_completed_responses"] == 25
        assert cycle["scored_response_rate"] == pytest.approx(100.0, abs=0.001)


class TestStarRatingMinimumCount:
    def test_star_rating_not_rated_below_min_count(self, api):
        """PRD §3.6: "A cycle whose `scored_completed_responses` is below 25 is
        not ratable: its `stars` are null, `rating_status` is `NOT_RATED`, and
        `capped` is false."

        Design: Corner/calculations/star_rating_not_rated_below_min_count
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CA4"), "FIELDING", discharge_count=24)
        import_responses(ctx["case_ids"], ctx["vendor"]["id"],
                         mode_used="MAIL", score=4)
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        get_success_data(api.begin_scoring(ctx["cycle"]["id"], ADMIN))

        rating = validate_success(
            api.get_star_rating(ctx["cycle"]["id"], ADMIN), 200)
        assert rating["rating_status"] == "NOT_RATED"
        assert rating["stars"] is None
        assert rating["capped"] is False

    def test_perfect_percentage_still_not_rated_at_24(self, api):
        """PRD §3.6: "A cycle whose `scored_completed_responses` is below 25 is
        not ratable: its `stars` are null, `rating_status` is `NOT_RATED`, and
        `capped` is false. Otherwise the rating reads the adjusted
        `overall_rating` percentage from the snapshot: at least 90.0 earns 5
        stars"

        Design: Corner/calculations/star_rating_not_rated_below_min_count
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-CA4B"), "FIELDING", discharge_count=24)
        import_responses(ctx["case_ids"], ctx["vendor"]["id"],
                         mode_used="MAIL", score=4)
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        get_success_data(api.begin_scoring(ctx["cycle"]["id"], ADMIN))
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["scored_completed_responses"] == 24
        assert cycle["scored_adjusted_composite_pcts"]["overall_rating"] == (
            pytest.approx(100.0, abs=0.001))

        rating = validate_success(
            api.get_star_rating(ctx["cycle"]["id"], ADMIN), 200)
        assert rating["rating_status"] == "NOT_RATED"
        assert rating["stars"] is None
        assert rating["capped"] is False
        assert rating["completed_responses"] == 24
