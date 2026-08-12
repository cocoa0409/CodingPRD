"""Firefighter roster, live-fire currency, staffing-supported index."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_firefighter_payload,
    create_training_record_payload,
    get_firefighter,
    get_success_data,
    record_training,
    set_clock,
    setup_compliant_index_c_airport,
    setup_profile_only,
    validate_error,
    validate_success,
)

AM = TEST_USERS["airport_manager_headers"]
AC = TEST_USERS["arff_chief_headers"]


class TestFirefighterDeployableCompound:
    def test_deployable_and_of_status_and_currency(self, api):
        """PRD §3.4: "`is_deployable` is `true` exactly when `status` is
        `ACTIVE` and `is_training_current` is `true`."

        Design: Corner/entities/ent_firefighter_deployable_compound
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        resp = api.create_firefighter(
            create_firefighter_payload(employee_no="FF-101",
                                       full_name="Ann Lee"),
            AC,
        )
        ff = validate_success(resp, expected_status=201)
        assert ff["is_deployable"] is False
        assert ff["is_training_current"] is False

        # FAIL record confers nothing
        record_training(ff["id"], completed_on="2026-04-01",
                        drill_type="AIRCRAFT", result="FAIL")
        f = get_firefighter(ff["id"])
        assert f["is_deployable"] is False
        assert f["last_live_fire_completed_on"] is None

        # PASS record confers currency
        record_training(ff["id"], completed_on="2026-04-10",
                        drill_type="STRUCTURAL", result="PASS")
        f = get_firefighter(ff["id"])
        assert f["is_deployable"] is True
        assert f["last_live_fire_completed_on"] == "2026-04-10"

        # Suspension dominates
        resp = api.suspend_firefighter(ff["id"], AC)
        f = validate_success(resp)
        assert f["is_deployable"] is False
        assert f["status"] == "SUSPENDED"


class TestLastLiveFireMax:
    def test_last_live_fire_completed_on_max_semantics(self, api):
        """PRD §3.4: "`last_live_fire_completed_on` is the ISO date of the
        most recent `PASS` record by `completed_on` (ties broken by the
        record's `created_at` descending); it is null when no `PASS` record
        exists."

        Design: Corner/cross_cutting_complexity_layers/x_derived_field_last_live_fire_max_semantics
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        ff = validate_success(
            api.create_firefighter(
                create_firefighter_payload(employee_no="FF-101",
                                           full_name="Ann Lee"),
                AC,
            ),
            expected_status=201,
        )
        record_training(ff["id"], completed_on="2026-01-10",
                        drill_type="AIRCRAFT", result="PASS")
        f = get_firefighter(ff["id"])
        assert f["last_live_fire_completed_on"] == "2026-01-10"

        # Older record does not regress the anchor
        record_training(ff["id"], completed_on="2025-12-01",
                        drill_type="STRUCTURAL", result="PASS")
        f = get_firefighter(ff["id"])
        assert f["last_live_fire_completed_on"] == "2026-01-10"

        # Newer record advances it
        record_training(ff["id"], completed_on="2026-02-01",
                        drill_type="AIRCRAFT", result="PASS")
        f = get_firefighter(ff["id"])
        assert f["last_live_fire_completed_on"] == "2026-02-01"


class TestTrainingFailExcludedFromCurrency:
    def test_training_fail_records_excluded_from_currency(self, api):
        """PRD §3.4: "Only `PASS` records feed currency."

        Design: Corner/calculations/calc_training_fail_records_excluded_from_currency
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        ff = validate_success(
            api.create_firefighter(
                create_firefighter_payload(employee_no="FF-101",
                                           full_name="Ann Lee"),
                AC,
            ),
            expected_status=201,
        )
        record_training(ff["id"], completed_on="2026-03-10",
                        drill_type="AIRCRAFT", result="PASS")
        # Later FAIL record must not move or clear the anchor
        record_training(ff["id"], completed_on="2026-04-20",
                        drill_type="STRUCTURAL", result="FAIL")
        f = get_firefighter(ff["id"])
        assert f["last_live_fire_completed_on"] == "2026-03-10"
        assert f["is_training_current"] is True


class TestTrainingDateInFuture:
    def test_training_completed_on_future_date_rejected(self, api):
        """PRD §3.4: "The `completed_on` may not be later than the current
        logical date — a future date is rejected with
        `ERR_TRAINING_DATE_IN_FUTURE`."

        Design: Corner/validations/val_training_date_in_future_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        ff = validate_success(
            api.create_firefighter(
                create_firefighter_payload(employee_no="FF-101",
                                           full_name="Ann Lee"),
                AC,
            ),
            expected_status=201,
        )
        resp = api.create_training_record(
            create_training_record_payload(
                ff["id"], completed_on="2026-06-01",
                drill_type="AIRCRAFT", result="PASS",
            ),
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_TRAINING_DATE_IN_FUTURE)


class TestTrainingCurrencyTwelveMonthBoundary:
    def test_training_currency_diff_12_passes(self, api):
        """PRD §3.4: "A firefighter's `is_training_current` is `true` exactly
        when a `PASS` record exists and `month_index` of today minus
        `month_index` of `last_live_fire_completed_on` is at most twelve. So
        training completed in month M confers currency through the end of
        month M+12."

        Design: Difficulty/boundary_precision_check/bp_training_currency_twelve_month_boundary
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        ff = validate_success(
            api.create_firefighter(
                create_firefighter_payload(employee_no="FF-101",
                                           full_name="Ann Lee"),
                AC,
            ),
            expected_status=201,
        )
        record_training(ff["id"], completed_on="2025-06-15",
                        drill_type="AIRCRAFT", result="PASS")
        # June 2026: month diff = 12 -> still current
        set_clock("2026-06-30T23:59:00Z")
        f = get_firefighter(ff["id"])
        assert f["is_training_current"] is True

    def test_training_currency_diff_13_lapses(self, api):
        """PRD §3.4: "A firefighter's `is_training_current` is `true` exactly
        when a `PASS` record exists and `month_index` of today minus
        `month_index` of `last_live_fire_completed_on` is at most twelve. So
        training completed in month M confers currency through the end of
        month M+12."

        Design: Difficulty/boundary_precision_check/bp_training_currency_twelve_month_boundary
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        ff = validate_success(
            api.create_firefighter(
                create_firefighter_payload(employee_no="FF-101",
                                           full_name="Ann Lee"),
                AC,
            ),
            expected_status=201,
        )
        record_training(ff["id"], completed_on="2025-06-15",
                        drill_type="AIRCRAFT", result="PASS")
        # July 2026: month diff = 13 -> lapsed
        set_clock("2026-07-01T00:00:00Z")
        f = get_firefighter(ff["id"])
        assert f["is_training_current"] is False


class TestEffectiveIndexMinSemantics:
    def test_effective_index_is_min_across_inputs(self, api):
        """PRD §3.5: "`effective_index` is the minimum of `certificated_index`,
        `supported_index_by_equipment`, and `supported_index_by_staffing`,
        under the ordering `NONE < A < B < C < D < E` — `NONE` dominates any
        minimum."

        Design: Corner/calculations/calc_effective_index_min_semantics
        """
        # Build airport with equipment C but staffing A (only 2 current ff)
        set_clock("2026-05-01T00:00:00Z")
        setup_compliant_index_c_airport(num_firefighters=2)
        profile = get_success_data(api.get_profile(AM))
        assert profile["supported_index_by_equipment"] == "C"
        assert profile["supported_index_by_staffing"] == "A"
        assert profile["effective_index"] == "A"
        assert profile["index_compliance_status"] == "NONCOMPLIANT"
