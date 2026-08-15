"""Weather readings, effective wind limits, go/no-go evaluation verdicts and
lookback semantics, certification, and the certify-go gate."""
from test_helpers import (
    ApiErrorId,
    certify_evaluation,
    create_evaluation,
    create_show,
    create_site,
    create_weather_reading_payload,
    get_show,
    post_weather,
    set_clock,
    setup_authorized_show,
    setup_ready_show,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_safety_officer_headers

PLANNER = TEST_USERS["planner_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


class TestWeatherReadings:
    def test_gust_below_sustained_wind_rejected(self, api):
        """PRD: "plus `wind_speed_kt` and `gust_kt` (both non-negative, and the
        gust must be at least the sustained speed, else `ERR_VALIDATION`)"

        Design: Corner/entities/weather_reading_gust_below_wind_rejected
        """
        site = create_site()
        set_clock()
        resp = api.create_weather_reading(
            create_weather_reading_payload(site["id"],
                                           recorded_at="2026-07-31T23:00:00Z",
                                           wind_speed_kt=10, gust_kt=5),
            SAFETY)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_reading_in_future_rejected_now_allowed(self, api):
        """PRD: "Each reading carries its `recorded_at` timestamp — which must
        not be after the current logical-clock reading, else
        `ERR_READING_IN_FUTURE`"

        Design: Corner/validations/reading_in_future_rejected_now_allowed
        """
        site = create_site()
        set_clock("2026-08-01T12:00:00Z")
        resp = api.create_weather_reading(
            create_weather_reading_payload(site["id"],
                                           recorded_at="2026-08-01T12:00:01Z"),
            SAFETY)
        validate_error(resp, ApiErrorId.ERR_READING_IN_FUTURE)

        # "must not be after": a reading exactly at the clock reading is allowed.
        reading = validate_success(api.create_weather_reading(
            create_weather_reading_payload(site["id"],
                                           recorded_at="2026-08-01T12:00:00Z"),
            SAFETY), 201)
        assert reading["id"]


class TestEffectiveWindLimits:
    def _authorized_500ft_100_drone_show(self):
        return setup_authorized_show(
            show_overrides={"drone_count_planned": 100},
            design_overrides={"drone_count": 100, "max_altitude_ft": 500,
                              "duration_sec": 900},
            config_overrides={"geofence_radius_m": 400,
                              "altitude_hard_ceiling_ft": 500},
            auth_overrides={"altitude_ceiling_ft": 500,
                            "waiver_types": ["NIGHT_OPS"]})

    def test_nested_min_and_tier_interaction_no_go(self, api):
        """PRD: "The altitude factor is 1.0 when the pinned design's
        `max_altitude_ft` is at most 200 feet, 0.9 when it is above 200 but at
        most 400 feet, and 0.8 above 400 feet. The fleet factor is 1.0 when the
        design's `drone_count` is at most 100, 0.9 when above 100 but at most
        300, and 0.8 above 300. The `effective_wind_limit_kt` is the lesser of
        the venue's `site_max_wind_kt` and the 18-knot baseline multiplied by
        both factors, rounded half up to one decimal place. The
        `effective_gust_limit_kt` is the effective wind limit multiplied by 1.3,
        again rounded half up to one decimal place."
        PRD: "sustained wind strictly above the effective wind limit records
        `WIND_SUSTAINED_EXCEEDED`"

        Design: Difficulty/combinatorial_formula/wind_limit_nested_min_and_tier_interaction
        """
        ctx = self._authorized_500ft_100_drone_show()
        set_clock("2026-08-10T18:45:00Z")
        post_weather(ctx["site"]["id"], recorded_at="2026-08-10T18:30:00Z",
                     wind_speed_kt=14.5, gust_kt=15.0)
        evaluation = create_evaluation(ctx["show"]["id"])
        # min(20, 18 * 0.8 * 1.0) == 14.4; gust 14.4 * 1.3 == 18.7 (1 dp).
        assert evaluation["effective_wind_limit_kt"] == 14.4
        assert evaluation["effective_gust_limit_kt"] == 18.7
        assert evaluation["verdict"] == "NO_GO", "14.5 > 14.4 sustained"
        assert evaluation["reason_codes"] == ["WIND_SUSTAINED_EXCEEDED"]

    def test_nested_min_and_tier_interaction_boundary_go(self, api):
        """PRD: "sustained wind strictly above the effective wind limit records
        `WIND_SUSTAINED_EXCEEDED` (a reading exactly at the limit passes — the
        comparison is strictly-greater)"

        Design: Difficulty/combinatorial_formula/wind_limit_nested_min_and_tier_interaction
        """
        ctx = self._authorized_500ft_100_drone_show()
        set_clock("2026-08-10T18:45:00Z")
        post_weather(ctx["site"]["id"], recorded_at="2026-08-10T18:40:00Z",
                     wind_speed_kt=14.4, gust_kt=15.0)
        evaluation = create_evaluation(ctx["show"]["id"])
        assert evaluation["verdict"] == "GO", \
            "14.4 == 14.4 is at the limit, and at-limit passes"


class TestWindBoundary:
    def test_wind_and_gust_exactly_at_limit_go(self, api):
        """PRD: "a reading exactly at the limit passes — the comparison is
        strictly-greater" and "The `verdict` is `GO` exactly when `reason_codes`
        is empty, and `NO_GO` otherwise."

        Design: Difficulty/boundary_precision_check/wind_and_gust_exactly_at_limit_go
        """
        ctx = setup_authorized_show(design_overrides={"max_altitude_ft": 200})
        set_clock("2026-08-10T18:45:00Z")
        post_weather(ctx["site"]["id"], recorded_at="2026-08-10T18:30:00Z",
                     wind_speed_kt=18.0, gust_kt=23.4)
        evaluation = create_evaluation(ctx["show"]["id"])
        # 200 ft / 10 drones: min(20, 18 * 1.0 * 1.0) == 18.0; gust 18.0 * 1.3.
        assert evaluation["effective_wind_limit_kt"] == 18.0
        assert evaluation["effective_gust_limit_kt"] == 23.4
        assert evaluation["verdict"] == "GO"
        assert evaluation["reason_codes"] == []

    def test_wind_one_tenth_over_limit_no_go(self, api):
        """PRD: "sustained wind strictly above the effective wind limit records
        `WIND_SUSTAINED_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/wind_and_gust_exactly_at_limit_go
        """
        ctx = setup_authorized_show(design_overrides={"max_altitude_ft": 200})
        set_clock("2026-08-10T18:45:00Z")
        post_weather(ctx["site"]["id"], recorded_at="2026-08-10T18:40:00Z",
                     wind_speed_kt=18.1, gust_kt=20.0)
        evaluation = create_evaluation(ctx["show"]["id"])
        assert evaluation["verdict"] == "NO_GO"
        assert evaluation["reason_codes"] == ["WIND_SUSTAINED_EXCEEDED"]


class TestLookbackWindow:
    def test_empty_lookback_returns_no_weather_data(self, api):
        """PRD: "When the lookback window holds no readings at all, the verdict
        is `NO_GO` and `reason_codes` is the single entry `NO_WEATHER_DATA`."

        Design: Difficulty/boundary_precision_check/empty_weather_lookback_no_go_and_60min_inclusion
        """
        ctx = setup_authorized_show()
        set_clock("2026-08-10T18:45:00Z")
        evaluation = create_evaluation(ctx["show"]["id"])
        assert evaluation["verdict"] == "NO_GO"
        assert evaluation["reason_codes"] == ["NO_WEATHER_DATA"]

    def test_reading_exactly_60_minutes_old_included(self, api):
        """PRD: "The evaluation stamps `evaluated_at` from the logical clock and
        examines the weather readings at the show's site whose `recorded_at`
        falls within the 60-minute lookback up to and including `evaluated_at` —
        a reading exactly 60 minutes old is included."

        Design: Difficulty/boundary_precision_check/empty_weather_lookback_no_go_and_60min_inclusion
        """
        ctx = setup_authorized_show()
        set_clock("2026-08-10T18:45:00Z")
        # 17:45 is exactly 60 minutes before the 18:45 evaluation.
        post_weather(ctx["site"]["id"], recorded_at="2026-08-10T17:45:00Z",
                     wind_speed_kt=8, gust_kt=11)
        evaluation = create_evaluation(ctx["show"]["id"])
        assert evaluation["verdict"] == "GO"

    def test_evaluation_uses_latest_reading_in_lookback(self, api):
        """PRD: "The operative reading is the latest by `recorded_at`, with ties
        broken by `created_at`."
        PRD: "the system evaluates four checks in a fixed order, collecting
        every failed reason: sustained wind strictly above the effective wind
        limit records `WIND_SUSTAINED_EXCEEDED` (a reading exactly at the limit
        passes — the comparison is strictly-greater); gust strictly above the
        effective gust limit records `GUST_EXCEEDED`"

        Design: Corner/calculations/evaluation_uses_latest_reading_in_lookback
        """
        ctx = setup_authorized_show()  # 300 ft / 10 drones -> 16.2 / 21.1
        set_clock("2026-08-10T18:45:00Z")
        post_weather(ctx["site"]["id"], recorded_at="2026-08-10T18:20:00Z",
                     wind_speed_kt=30, gust_kt=35)
        post_weather(ctx["site"]["id"], recorded_at="2026-08-10T18:35:00Z",
                     wind_speed_kt=5, gust_kt=9)
        evaluation = create_evaluation(ctx["show"]["id"])
        assert evaluation["verdict"] == "GO", \
            "the later calm reading supersedes the over-limit one"

        post_weather(ctx["site"]["id"], recorded_at="2026-08-10T18:40:00Z",
                     wind_speed_kt=17, gust_kt=25)
        late = create_evaluation(ctx["show"]["id"])
        assert late["verdict"] == "NO_GO"
        # 17 > 16.2 and 25 > 21.1, in the pinned reason order.
        assert late["reason_codes"] == ["WIND_SUSTAINED_EXCEEDED", "GUST_EXCEEDED"]


class TestEvaluationCertification:
    def test_evaluation_on_planning_show_returns_invalid_state(self, api):
        """PRD: "A `SafetyOfficer` requests a **GoNoGoEvaluation** for a show by
        its `show_event_id`; the show must be `AUTHORIZED`, `READY`, or
        `GO_CERTIFIED` (else `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/evaluation_on_planning_show_returns_invalid_state
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        resp = api.create_go_no_go_evaluation({"show_event_id": show["id"]},
                                              SAFETY)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_certify_sod_against_config_approver(self, api):
        """PRD: "A `SafetyOfficer` certifying a go/no-go evaluation must not be
        the user who approved the show's pinned safety configuration: the caller
        must differ from that configuration's `approved_by_user_id`." — "Each
        violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD: "Certifying a `PROVISIONAL` evaluation (any other state is
        `ERR_INVALID_STATE`) moves it to `CERTIFIED` and stamps `certified_at`
        and `certified_by_user_id`."

        Design: Corner/validations/evaluation_certify_sod_against_config_approver
        """
        ctx = setup_authorized_show()  # config approved by so-1
        set_clock("2026-08-10T18:45:00Z")
        post_weather(ctx["site"]["id"])
        evaluation = create_evaluation(ctx["show"]["id"])

        resp = api.certify_go_no_go_evaluation(
            evaluation["id"], make_safety_officer_headers("so-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        certified = certify_evaluation(evaluation["id"], officer_user_id="so-2")
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == "so-2"

    def test_double_certify_evaluation_returns_invalid_state(self, api):
        """PRD: "Certifying a `PROVISIONAL` evaluation (any other state is
        `ERR_INVALID_STATE`) moves it to `CERTIFIED` and stamps `certified_at`
        and `certified_by_user_id`."

        Design: Corner/state_machines/double_certify_evaluation_returns_invalid_state
        """
        ctx = setup_authorized_show()
        set_clock("2026-08-10T18:45:00Z")
        post_weather(ctx["site"]["id"])
        evaluation = create_evaluation(ctx["show"]["id"])
        certify_evaluation(evaluation["id"], officer_user_id="so-2")

        resp = api.certify_go_no_go_evaluation(
            evaluation["id"], make_safety_officer_headers("so-2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCertifyGo:
    def _ready_show_with_evaluation(self, wind_speed_kt=8, gust_kt=11):
        ctx = setup_ready_show(
            show_overrides={"drone_count_planned": 3},
            design_overrides={"drone_count": 3})
        set_clock("2026-08-10T18:45:00Z")
        post_weather(ctx["site"]["id"], wind_speed_kt=wind_speed_kt,
                     gust_kt=gust_kt)
        evaluation = create_evaluation(ctx["show"]["id"])
        ctx["evaluation"] = evaluation
        return ctx

    def test_certify_go_with_provisional_evaluation_rejected(self, api):
        """PRD: "the request names an `evaluation_id` that must reference an
        evaluation belonging to this show (else `ERR_EVALUATION_NOT_FOUND`), in
        `CERTIFIED` status (else `ERR_EVALUATION_NOT_CERTIFIED`)"

        Design: Difficulty/cross_entity_state_dependency/certify_go_requires_certified_evaluation
        """
        ctx = self._ready_show_with_evaluation()
        assert ctx["evaluation"]["status"] == "PROVISIONAL"
        resp = api.certify_go(ctx["show"]["id"],
                              {"evaluation_id": ctx["evaluation"]["id"]},
                              make_safety_officer_headers("so-2"))
        validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_CERTIFIED)

    def test_certify_go_with_certified_go_succeeds(self, api):
        """PRD: "**Certify-go**, performed by a `SafetyOfficer`, moves a `READY`
        show to `GO_CERTIFIED`" and "Success sets the show's
        `readiness_posture` to `GO` outright and increments its version."

        Design: Difficulty/cross_entity_state_dependency/certify_go_requires_certified_evaluation
        """
        ctx = self._ready_show_with_evaluation()
        certify_evaluation(ctx["evaluation"]["id"], officer_user_id="so-2")
        show = validate_success(api.certify_go(
            ctx["show"]["id"], {"evaluation_id": ctx["evaluation"]["id"]},
            make_safety_officer_headers("so-2")))
        assert show["lifecycle_status"] == "GO_CERTIFIED"
        assert show["readiness_posture"] == "GO"

    def test_certify_go_with_certified_no_go_rejected(self, api):
        """PRD: "with a `GO` verdict (else `ERR_NO_GO_IN_EFFECT`)"

        Design: Corner/validations/certify_go_with_certified_no_go_rejected
        """
        ctx = self._ready_show_with_evaluation(wind_speed_kt=30, gust_kt=35)
        assert ctx["evaluation"]["verdict"] == "NO_GO", "30 kt exceeds 16.2"
        certify_evaluation(ctx["evaluation"]["id"], officer_user_id="so-2")
        resp = api.certify_go(ctx["show"]["id"],
                              {"evaluation_id": ctx["evaluation"]["id"]},
                              make_safety_officer_headers("so-2"))
        validate_error(resp, ApiErrorId.ERR_NO_GO_IN_EFFECT)
