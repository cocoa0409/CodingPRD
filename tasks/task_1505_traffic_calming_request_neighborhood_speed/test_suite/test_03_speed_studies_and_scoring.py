"""Speed studies: aggregation variants, criteria scoring, lifecycle states,
recollection cycle, window buffering, and observation gates (PRD §3.3)."""
import pytest

from test_helpers import (
    TE,
    ApiErrorId,
    api_client,
    assert_observation,
    build_certified_request,
    commission_study,
    create_funding_cycle,
    create_speed_study_payload,
    file_request,
    get_request,
    get_speed_study,
    open_petition,
    set_clock,
    setup_petition_open,
    setup_study_collecting,
    sign_petition,
    validate_error,
    validate_success,
)


class TestProvisionalVsCertifiedVariants:
    """One study with three valid days (1500 / 35.0 / 28.0) and one excluded
    outlier day (9000 / 50.0 / 44.0, is_valid=false)."""

    def _setup(self):
        return setup_study_collecting(
            name="Maple Ave",
            household_count=10,
            resident_prefix="dv1",
            window=("2026-08-03", "2026-08-06"),
            observations=[
                ("2026-08-03", 1500, 35.0, 28.0),
                ("2026-08-04", 1500, 35.0, 28.0),
                ("2026-08-05", 1500, 35.0, 28.0),
                ("2026-08-06", 9000, 50.0, 44.0, False),
            ],
        )

    def test_provisional_variant_aggregates_over_all_observations(self):
        """PRD §3.3: "Analysis moves the study from `COLLECTING` to `ANALYZED` and computes the provisional aggregates over all observations, outliers included: `provisional_p85_mph` is the arithmetic mean of `p85_speed_mph` across every observation, rounded half-up to one decimal place; `provisional_mean_speed_mph` is the mean of `mean_speed_mph` over the same full set, also rounded half-up to one decimal place; `provisional_avg_daily_volume` is the mean of `vehicle_count` over the same set, rounded half-up to a whole number of vehicles; and `provisional_score` is the criteria score computed from those provisional aggregates."

        Design: Difficulty/dual_variant_calc/speed_score_provisional_vs_certified_input_filtering
        """
        ctx = self._setup()
        resp = api_client.analyze_study(ctx["study"]["id"], TE)
        study = validate_success(resp, expected_status=200)
        assert study["status"] == "ANALYZED"
        assert study["provisional_p85_mph"] == pytest.approx(38.8, abs=1e-6), (
            "mean of 35,35,35,50 = 38.75 -> half-up 1dp = 38.8, "
            f"got {study['provisional_p85_mph']}"
        )
        assert study["provisional_avg_daily_volume"] == 3375, (
            f"mean of 1500,1500,1500,9000 = 3375, "
            f"got {study['provisional_avg_daily_volume']}"
        )
        # excess 8.8 -> 30 speed points; adv 3375 -> 20 volume points.
        assert study["provisional_score"] == 50, (
            f"provisional_score must be 50, got {study['provisional_score']}"
        )

    def test_certified_variant_excludes_outliers_and_drives_fork(self):
        """PRD §3.3: "Certification moves the study from `ANALYZED` to its terminal `CERTIFIED` status and computes the certified aggregates over valid observations only"
        PRD §3.3: "a score below sixty moves it to `SCORE_INELIGIBLE`, a terminal stage. Either way, the request's own `certified_score` field is snapshotted from the study's."
        PRD §3.3: "Because the provisional variant includes outlier days that certification will exclude, provisional and certified figures can diverge even when no new data arrives between the two."

        Design: Difficulty/dual_variant_calc/speed_score_provisional_vs_certified_input_filtering
        """
        ctx = self._setup()
        api_client.analyze_study(ctx["study"]["id"], TE)
        resp = api_client.certify_study(ctx["study"]["id"], TE)
        study = validate_success(resp, expected_status=200)
        assert study["status"] == "CERTIFIED"
        assert study["certified_p85_mph"] == pytest.approx(35.0, abs=1e-6), (
            f"valid rows only: mean of 35,35,35 = 35.0, "
            f"got {study['certified_p85_mph']}"
        )
        assert study["certified_avg_daily_volume"] == 1500, (
            f"valid rows only: mean of 1500,1500,1500 = 1500, "
            f"got {study['certified_avg_daily_volume']}"
        )
        # excess 5.0 -> 20 speed points; adv 1500 -> 10 volume points.
        assert study["certified_score"] == 30, (
            f"certified_score must be 30, got {study['certified_score']}"
        )
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "SCORE_INELIGIBLE", (
            f"the certified 30 (< 60) must drive the fork, got {req['status']}"
        )
        assert req["certified_score"] == 30


class TestRecollectionCycle:
    def _setup(self):
        return setup_study_collecting(
            name="Elm Dr",
            household_count=4,
            resident_prefix="nsm1",
            window=("2026-08-03", "2026-08-06"),
            observations=[
                ("2026-08-03", 1000, 32.0, 25.0),
                ("2026-08-04", 1000, 32.0, 25.0),
                ("2026-08-05", 1000, 32.0, 25.0),
            ],
        )

    def test_return_for_recollection_reopens_collection(self):
        """PRD §3.3: "If the collected data looks thin or compromised, returning the study for recollection moves it from `ANALYZED` back to `COLLECTING` — any other status fails with `ERR_STUDY_INVALID_STATE` — after which further observations may be added and a later analysis will recompute the provisional figures over the enlarged set."

        Design: Difficulty/non_linear_state_machine/speed_study_recollection_cycle
        """
        ctx = self._setup()
        study = validate_success(
            api_client.analyze_study(ctx["study"]["id"], TE), 200
        )
        # excess 2.0 -> 10 speed points; adv 1000 -> 10 volume points.
        assert study["provisional_score"] == 20, (
            f"first analysis must score 20, got {study['provisional_score']}"
        )
        returned = validate_success(
            api_client.return_study_for_recollection(ctx["study"]["id"], TE),
            200,
        )
        assert returned["status"] == "COLLECTING", (
            f"return-for-recollection must land in COLLECTING, "
            f"got {returned['status']}"
        )
        # The reopened study accepts a further observation (cycle leg).
        obs = validate_success(
            api_client.record_observation(
                ctx["study"]["id"],
                {
                    "observation_date": "2026-08-06",
                    "vehicle_count": 2000,
                    "p85_speed_mph": 44.0,
                    "mean_speed_mph": 36.0,
                },
                TE,
            ),
            201,
        )
        assert_observation(obs)

    def test_second_analysis_recomputes_over_enlarged_set(self):
        """PRD §3.3: "If the collected data looks thin or compromised, returning the study for recollection moves it from `ANALYZED` back to `COLLECTING` — any other status fails with `ERR_STUDY_INVALID_STATE` — after which further observations may be added and a later analysis will recompute the provisional figures over the enlarged set."
        PRD §3.3: "All four remain null until the first analysis, and every subsequent analysis recomputes them."

        Design: Difficulty/non_linear_state_machine/speed_study_recollection_cycle
        """
        ctx = self._setup()
        api_client.analyze_study(ctx["study"]["id"], TE)
        api_client.return_study_for_recollection(ctx["study"]["id"], TE)
        api_client.record_observation(
            ctx["study"]["id"],
            {
                "observation_date": "2026-08-06",
                "vehicle_count": 2000,
                "p85_speed_mph": 44.0,
                "mean_speed_mph": 36.0,
            },
            TE,
        )
        study = validate_success(
            api_client.analyze_study(ctx["study"]["id"], TE), 200
        )
        assert study["status"] == "ANALYZED"
        assert study["provisional_p85_mph"] == pytest.approx(35.0, abs=1e-6), (
            f"mean of 32,32,32,44 = 35.0, got {study['provisional_p85_mph']}"
        )
        # excess 5.0 -> 20 speed points; adv 1250 -> 10 volume points.
        assert study["provisional_score"] == 30, (
            f"second analysis must recompute to 30, "
            f"got {study['provisional_score']}"
        )


class TestCriteriaScoreTiers:
    def _setup(self):
        return setup_study_collecting(
            name="Pine Ln",
            household_count=4,
            resident_prefix="cfa",
            crash_count_3yr=2,
            pedestrian_generator_count=1,
            observations=[
                ("2026-08-03", 2500, 37.5, 30.0),
                ("2026-08-04", 2500, 37.5, 30.0),
                ("2026-08-05", 2500, 37.5, 30.0),
            ],
        )

    def test_tiered_components_sum_to_certified_score(self):
        """PRD §3.3: "Speed points follow the excess: at least 10 mph earns 40 points; at least 7 but less than 10 earns 30; at least 4 but less than 7 earns 20; at least 1 but less than 4 earns 10; and an excess below 1 mph earns nothing. Volume points follow the average daily volume: at least 3000 vehicles earns 20 points; at least 2000 but fewer than 3000 earns 15; at least 1000 but fewer than 2000 earns 10; below 1000 earns nothing. Crash history contributes the segment's `crash_count_3yr`, capped at three crashes, multiplied by five points. Pedestrian exposure contributes the segment's `pedestrian_generator_count`, capped at two generators, multiplied by ten points."

        Design: Difficulty/combinatorial_formula/criteria_score_tiered_multi_input_mode_a
        """
        ctx = self._setup()
        api_client.analyze_study(ctx["study"]["id"], TE)
        study = validate_success(
            api_client.certify_study(ctx["study"]["id"], TE), 200
        )
        # excess 7.5 -> 30; adv 2500 -> 15; min(3,2)*5 -> 10; min(2,1)*10 -> 10.
        assert study["certified_score"] == 65, (
            f"certified_score must be 30 + 15 + 10 + 10 = 65, "
            f"got {study['certified_score']}"
        )

    def test_score_65_routes_request_to_ranking_eligible(self):
        """PRD §3.3: "A `certified_score` of at least sixty points — the boundary is inclusive — moves the request from `STUDY_IN_PROGRESS` to `RANKING_ELIGIBLE`; a score below sixty moves it to `SCORE_INELIGIBLE`, a terminal stage. Either way, the request's own `certified_score` field is snapshotted from the study's."

        Design: Difficulty/combinatorial_formula/criteria_score_tiered_multi_input_mode_a
        """
        ctx = self._setup()
        api_client.analyze_study(ctx["study"]["id"], TE)
        api_client.certify_study(ctx["study"]["id"], TE)
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "RANKING_ELIGIBLE", (
            f"65 >= 60 must route to RANKING_ELIGIBLE, got {req['status']}"
        )
        assert req["certified_score"] == 65


class TestStudyWindowBuffer:
    def _setup_two_requests(self):
        """Request 1 certified at score 20 (SCORE_INELIGIBLE, terminal, freeing
        the segment); request 2 petition-met on the same segment."""
        ctx1 = build_certified_request(
            name="Laurel Ln", resident_prefix="rto2a",
            obs_recipe=(1000, 32.0, 25.0),
        )
        assert ctx1["request"]["status"] == "SCORE_INELIGIBLE"
        seg = ctx1["segment"]
        residents = ctx1["residents"]
        req2 = file_request(seg["id"], residents[1]["id"],
                            title="Calm Laurel (R2)",
                            requested_budget_cents=50000)
        open_petition(req2["id"])
        for r in residents:
            sign_petition(req2["id"], r["id"])
        return ctx1, req2

    def test_window_starting_exactly_seven_days_after_conflicts(self):
        """PRD §3.3: "The buffer is inclusive: a gap of exactly seven days between the two windows is still a conflict, so the earliest permissible start date for a new study is eight days after the existing study's `window_end_date` — and symmetrically, a new study that ends eight days before an existing study's `window_start_date` is clear of it. A violation is rejected with `ERR_STUDY_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/study_window_buffer_inclusive_on_segment
        """
        set_clock("2026-08-01T00:00:00Z")
        _, req2 = self._setup_two_requests()
        resp = api_client.create_speed_study(
            req2["id"],
            create_speed_study_payload(
                study_type="INITIAL",
                window_start_date="2026-08-12",
                window_end_date="2026-08-14",
            ),
            TE,
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_WINDOW_CONFLICT)

    def test_window_starting_eight_days_after_is_clear(self):
        """PRD §3.3: "The buffer is inclusive: a gap of exactly seven days between the two windows is still a conflict, so the earliest permissible start date for a new study is eight days after the existing study's `window_end_date` — and symmetrically, a new study that ends eight days before an existing study's `window_start_date` is clear of it. A violation is rejected with `ERR_STUDY_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/study_window_buffer_inclusive_on_segment
        """
        set_clock("2026-08-01T00:00:00Z")
        _, req2 = self._setup_two_requests()
        resp = api_client.create_speed_study(
            req2["id"],
            create_speed_study_payload(
                study_type="INITIAL",
                window_start_date="2026-08-13",
                window_end_date="2026-08-15",
            ),
            TE,
        )
        study = validate_success(resp, expected_status=201)
        assert study["status"] == "COLLECTING"


class TestInitialStates:
    def test_new_entities_start_in_initial_states(self):
        """PRD §3.2: "the request is born in `SUBMITTED`."
        PRD §3.3: "The study is created in `COLLECTING`, and the request advances from `PETITION_MET` to `STUDY_IN_PROGRESS`."
        PRD §3.4: "The cycle is born `OPEN`, with `budget_committed_cents` starting at zero."

        Design: Corner/state_machines/initial_states_on_creation
        """
        ctx = setup_petition_open(
            name="Init Ave", household_count=4, resident_prefix="ini",
            requested_budget_cents=5000, signatures=0,
        )
        assert ctx["request"]["status"] == "SUBMITTED", (
            f"a new request must be born SUBMITTED, "
            f"got {ctx['request']['status']}"
        )
        for resident in ctx["residents"]:
            sign_petition(ctx["request"]["id"], resident["id"])

        study = commission_study(ctx["request"]["id"], "INITIAL",
                                 "2026-08-03", "2026-08-05")
        assert study["status"] == "COLLECTING", (
            f"a new study must be born COLLECTING, got {study['status']}"
        )
        cycle = create_funding_cycle(2027, 9000)
        assert cycle["status"] == "OPEN"
        assert cycle["budget_committed_cents"] == 0
        assert cycle["budget_available_cents"] == 9000


class TestStudyLifecycleGates:
    def test_certify_from_collecting_rejected(self):
        """PRD §3.3: "Certifying requires the study to be `ANALYZED` (otherwise `ERR_STUDY_INVALID_STATE`) and to hold at least three valid observations"

        Design: Corner/state_machines/certify_from_collecting_rejected
        """
        ctx = setup_study_collecting(
            name="Cert Ave", resident_prefix="cer",
            observations=[
                ("2026-08-03", 3000, 40.0, 33.0),
                ("2026-08-04", 3000, 40.0, 33.0),
                ("2026-08-05", 3000, 40.0, 33.0),
            ],
        )
        resp = api_client.certify_study(ctx["study"]["id"], TE)
        validate_error(resp, ApiErrorId.ERR_STUDY_INVALID_STATE)
        study = get_speed_study(ctx["study"]["id"])
        assert study["status"] == "COLLECTING", (
            f"the rejected certify must not move the study, "
            f"got {study['status']}"
        )

    def test_analyze_with_too_few_observations_rejected(self):
        """PRD §3.3: "Analyzing a study requires it to be `COLLECTING` (otherwise `ERR_STUDY_INVALID_STATE`) and to hold at least three observations — fewer is rejected with `ERR_INSUFFICIENT_OBSERVATION_DAYS`."

        Design: Corner/validations/analyze_with_too_few_observations_rejected
        """
        ctx = setup_study_collecting(
            name="Few Ave", resident_prefix="few",
            observations=[
                ("2026-08-03", 1000, 32.0, 25.0),
                ("2026-08-04", 1000, 32.0, 25.0),
            ],
        )
        resp = api_client.analyze_study(ctx["study"]["id"], TE)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_OBSERVATION_DAYS)
        assert get_speed_study(ctx["study"]["id"])["status"] == "COLLECTING"

    def test_certify_with_too_few_valid_observations_rejected(self):
        """PRD §3.3: "Certifying requires the study to be `ANALYZED` (otherwise `ERR_STUDY_INVALID_STATE`) and to hold at least three valid observations — a study whose `valid_observation_count` is below three is rejected with `ERR_INSUFFICIENT_OBSERVATION_DAYS`, even if plenty of outlier days exist."

        Design: Corner/validations/certify_with_too_few_valid_observations_rejected
        """
        ctx = setup_study_collecting(
            name="Valid Ave", resident_prefix="val",
            observations=[
                ("2026-08-03", 3000, 40.0, 33.0),
                ("2026-08-04", 3000, 40.0, 33.0),
                ("2026-08-05", 3000, 40.0, 33.0, False),
            ],
        )
        validate_success(api_client.analyze_study(ctx["study"]["id"], TE), 200)
        resp = api_client.certify_study(ctx["study"]["id"], TE)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_OBSERVATION_DAYS)
        assert get_speed_study(ctx["study"]["id"])["status"] == "ANALYZED"


class TestAggregationPrecision:
    def test_rounding_is_half_up_at_one_decimal(self):
        """PRD §2.6: "Measured speeds are rounded half-up to one decimal place, daily traffic volumes are rounded half-up to whole vehicles, and post-installation speed reductions are rounded half-up to one decimal place."

        Design: Corner/calculations/study_aggregation_rounding_precision
        """
        ctx = setup_study_collecting(
            name="Round Ave", resident_prefix="rnd",
            observations=[
                ("2026-08-03", 1001, 35.04, 28.0),
                ("2026-08-04", 1002, 35.05, 28.0),
                ("2026-08-05", 1003, 35.06, 28.0),
            ],
        )
        study = validate_success(
            api_client.analyze_study(ctx["study"]["id"], TE), 200
        )
        assert study["provisional_p85_mph"] == pytest.approx(35.1, abs=1e-6), (
            f"mean 35.05 must round half-up to 35.1, "
            f"got {study['provisional_p85_mph']}"
        )
        assert study["provisional_avg_daily_volume"] == 1002, (
            f"mean of 1001,1002,1003 = 1002, "
            f"got {study['provisional_avg_daily_volume']}"
        )


class TestScoreEligibilityBoundary:
    def test_score_below_sixty_marks_request_ineligible(self):
        """PRD §3.3: "A `certified_score` of at least sixty points — the boundary is inclusive — moves the request from `STUDY_IN_PROGRESS` to `RANKING_ELIGIBLE`; a score below sixty moves it to `SCORE_INELIGIBLE`, a terminal stage. Either way, the request's own `certified_score` field is snapshotted from the study's."

        Design: Corner/calculations/score_below_threshold_marks_ineligible
        """
        ctx = setup_study_collecting(
            name="Below Ave", resident_prefix="bel",
            pedestrian_generator_count=1,
            observations=[
                ("2026-08-03", 2500, 37.5, 30.0),
                ("2026-08-04", 2500, 37.5, 30.0),
                ("2026-08-05", 2500, 37.5, 30.0),
            ],
        )
        api_client.analyze_study(ctx["study"]["id"], TE)
        study = validate_success(
            api_client.certify_study(ctx["study"]["id"], TE), 200
        )
        # excess 7.5 -> 30; adv 2500 -> 15; crash 0 -> 0; ped min(2,1)*10 -> 10.
        assert study["certified_score"] == 55, (
            f"certified_score must be 55, got {study['certified_score']}"
        )
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "SCORE_INELIGIBLE", (
            f"55 < 60 must route to SCORE_INELIGIBLE, got {req['status']}"
        )
        assert req["certified_score"] == 55


class TestObservationGates:
    def test_observation_outside_window_rejected_boundary_inclusive(self):
        """PRD §3.3: "the `observation_date` must lie inside the collection window with both endpoints inclusive (otherwise `ERR_OBSERVATION_OUTSIDE_WINDOW`)"

        Design: Corner/validations/observation_outside_window_rejected
        """
        ctx = setup_study_collecting(name="Win Ave", resident_prefix="win")
        # One day past the window end (2026-08-05) is rejected.
        resp = api_client.record_observation(
            ctx["study"]["id"],
            {
                "observation_date": "2026-08-06",
                "vehicle_count": 1000,
                "p85_speed_mph": 32.0,
                "mean_speed_mph": 25.0,
            },
            TE,
        )
        validate_error(resp, ApiErrorId.ERR_OBSERVATION_OUTSIDE_WINDOW)
        # The exact window end is inclusive and passes.
        ok = api_client.record_observation(
            ctx["study"]["id"],
            {
                "observation_date": "2026-08-05",
                "vehicle_count": 1000,
                "p85_speed_mph": 32.0,
                "mean_speed_mph": 25.0,
            },
            TE,
        )
        assert_observation(validate_success(ok, expected_status=201))

    def test_duplicate_observation_date_rejected(self):
        """PRD §3.3: "each date may appear only once within a study (otherwise `ERR_DUPLICATE_OBSERVATION_DATE`)"

        Design: Corner/validations/duplicate_observation_date_rejected
        """
        ctx = setup_study_collecting(
            name="Dup Obs Ave", resident_prefix="dob",
            observations=[("2026-08-03", 1000, 32.0, 25.0)],
        )
        resp = api_client.record_observation(
            ctx["study"]["id"],
            {
                "observation_date": "2026-08-03",
                "vehicle_count": 9999,
                "p85_speed_mph": 55.0,
                "mean_speed_mph": 44.0,
            },
            TE,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OBSERVATION_DATE)
