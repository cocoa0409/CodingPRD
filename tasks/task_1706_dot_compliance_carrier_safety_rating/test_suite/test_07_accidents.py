"""The accident register: computed reportability and crash points,
preventability review with segregation of duties, and the CRASH_INDICATOR
measure input set."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_accident,
    create_accident_payload,
    determine_preventability,
    get_driver,
    list_snapshots,
    make_accident,
    make_carrier,
    make_carrier_with_driver,
    make_category,
    make_director_headers,
    make_driver,
    make_manager_headers,
    run_cycle,
    validate_error,
    validate_success,
)


class TestAccidentComputedFields:
    def test_accident_computed_reportable_and_points(self, api):
        """PRD §3.7: "`dot_reportable` is true when at least one fatality
        occurred, at least one injury occurred, or any vehicle was towed.
        `crash_points` sum the severity: four points when at least one fatality
        occurred, two more when at least one injury occurred, and one more when
        a vehicle was towed — a range of 0 to 7. The registrar's identity is
        stamped as `registered_by_user_id`, and the record enters
        `PENDING_REVIEW`."

        Design: Corner/entities/accident_computed_reportable_and_points
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2005"}
        )
        a1 = validate_success(
            api.create_accident(
                create_accident_payload(
                    carrier["id"], driver["id"],
                    occurred_at="2026-06-01T00:00:00Z",
                    fatalities=0, injuries=1, tow_away=True,
                ),
                # registrar identity recorded for the later SoD check
                make_manager_headers("sm-1"),
            ),
            201,
        )
        assert_accident(a1)
        assert a1["dot_reportable"] is True
        assert a1["crash_points"] == 3, "2 injury + 1 tow"
        assert a1["preventability_status"] == "PENDING_REVIEW"

        a2 = validate_success(
            api.create_accident(
                create_accident_payload(
                    carrier["id"], driver["id"],
                    occurred_at="2026-06-02T00:00:00Z",
                    fatalities=0, injuries=0, tow_away=False,
                ),
                make_manager_headers("sm-1"),
            ),
            201,
        )
        assert a2["dot_reportable"] is False
        assert a2["crash_points"] == 0
        assert a2["preventability_status"] == "PENDING_REVIEW"


class TestPreventabilityReview:
    def test_sod_preventability_same_user(self, api):
        """PRD §2.10: "the `SafetyDirector` who determines the preventability of
        an accident must not be the `SafetyManager` who registered it: when the
        determiner's `X-User-ID` equals the accident's `registered_by_user_id`,
        the determination is rejected with `ERR_SOD_PREVENTABILITY_SAME_USER`
        (HTTP 409)."

        Design: Corner/validations/sod_preventability_same_user
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2308"}
        )
        accident = make_accident(carrier["id"], driver["id"])

        same_user = api.determine_preventability(
            accident["id"], {"determination": "PREVENTABLE"},
            make_director_headers("sm-1"),
        )
        validate_error(same_user, ApiErrorId.ERR_SOD_PREVENTABILITY_SAME_USER)

        other = validate_success(
            api.determine_preventability(
                accident["id"], {"determination": "PREVENTABLE"},
                make_director_headers("sd-1"),
            ),
            200,
        )
        assert other["preventability_status"] == "PREVENTABLE"

    def test_preventability_second_determination_rejected(self, api):
        """PRD §3.7: "The record must still be in `PENDING_REVIEW` — a second
        determination is rejected with
        `ERR_PREVENTABILITY_ALREADY_DETERMINED`".

        Design: Corner/validations/preventability_second_determination_rejected
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2327"}
        )
        accident = make_accident(carrier["id"], driver["id"])
        first = determine_preventability(accident["id"], "NOT_PREVENTABLE")
        assert first["preventability_status"] == "NOT_PREVENTABLE"

        second = api.determine_preventability(
            accident["id"], {"determination": "PREVENTABLE"},
            make_director_headers("sd-2"),
        )
        validate_error(second, ApiErrorId.ERR_PREVENTABILITY_ALREADY_DETERMINED)


class TestCrashIndicatorMeasure:
    def test_crash_indicator_input_set_filtering(self, api):
        """PRD §3.10: "For the `CRASH_INDICATOR` category only, the sum
        additionally includes, for each of the carrier's DOT-reportable
        accidents, the accident's `crash_points` multiplied by the time weight
        of its `occurred_at`, regardless of preventability and identically in
        both variants because crashes cannot be challenged."
        PRD §3.2: the risk score counts "the sum of `crash_points` multiplied by
        the accident's time weight over the driver's accidents that are both
        `PREVENTABLE` and DOT-reportable and whose time weight is positive" — a
        NOT_PREVENTABLE crash never counts against the driver.

        Design: Corner/calculations/crash_indicator_input_set_filtering
        """
        carrier = make_carrier(dot_number="DOT-2202", fleet_size=5)
        category = make_category(
            category_code="CRASH_INDICATOR", display_name="Crash",
            intervention_threshold=65, benchmark_measure=10.0,
        )
        driver = make_driver(carrier["id"], hire_date="2024-01-01T00:00:00Z")
        a1 = make_accident(
            carrier["id"], driver["id"], occurred_at="2026-05-01T00:00:00Z",
            fatalities=0, injuries=1, tow_away=False,
        )
        make_accident(
            carrier["id"], driver["id"], occurred_at="2026-05-02T00:00:00Z",
            fatalities=0, injuries=0, tow_away=False,
        )
        determine_preventability(a1["id"], "NOT_PREVENTABLE")

        run_cycle(carrier["id"])
        snaps = list_snapshots(carrier_id=carrier["id"], category_id=category["id"])
        assert len(snaps) == 1
        # reportable crash: 2 crash points x time-weight 3 = 6; / 5 = 1.20
        assert snaps[0]["official_measure"] == pytest.approx(1.20, abs=0.001)
        assert snaps[0]["provisional_measure"] == pytest.approx(1.20, abs=0.001)
        assert get_driver(driver["id"])["risk_score"] == 0
