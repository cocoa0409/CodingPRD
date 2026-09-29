"""
The arithmetic corners: calendar-year retention, the exclusive rolling window,
the scope of the store's regulated aggregates, the statutory penalty cap, the
three late-filing brackets, exceedance counting across a closed event, and
half-up rounding of a repeating quotient.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_instant,
    assert_mass,
    assert_money,
    assert_penalty_exposure,
    assert_store_posture,
    assert_system_axes,
    assert_system_charge,
)
from test_helpers.test_users import (
    COMPLIANCE_MANAGER_HEADERS,
    REGULATOR_HEADERS,
    make_technician_headers,
)
from test_helpers.types import (
    APPLICABILITY_EXEMPT,
    APPLICABILITY_REGULATED,
    DETECTION_AUTOMATED_MONITORING,
    EVENT_OPEN,
    EVENT_VERIFIED_CLOSED,
    INSPECTION_OPEN,
    POSTURE_AT_RISK,
    POSTURE_COMPLIANT,
    REPORT_SUBMITTED,
    RESULT_PASS,
    SERVICE_ADD_REFRIGERANT,
    SEVERITY_MAJOR,
    STATE_CHRONIC_EXCEEDANCE,
    STATE_COMPLIANT,
    SYSTEM_ACTIVE,
    SYSTEM_RETIRED,
)


def test_retention_advances_three_calendar_years_and_clamps_a_leap_day(api):
    """
    §3.8 makes retention calendar arithmetic: a record performed on 29 February
    2028 retains until 28 February 2031, which day arithmetic (1095 days) and
    naive year substitution (an impossible 2031-02-29) both get wrong.

    Design: Corner/calculations/retention_until_uses_calendar_years_and_clamps_leap_day
    """
    X.set_clock(api, "2028-02-29T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    system = X.create_system(api, store["id"], rt404["id"])
    technician = X.create_technician(
        api, certification_expires_on="2029-12-31T00:00:00Z"
    )
    equipment = X.create_equipment(
        api,
        store["id"],
        technician["id"],
        last_verification_on="2028-01-15T00:00:00Z",
    )
    cylinder = X.create_cylinder(api, store["id"], rt404["id"])

    record = validate_success(
        api.create_service_record(
            F.service_record_payload(
                system["id"],
                technician["id"],
                equipment["id"],
                system["version"],
                cylinder_id=cylinder["id"],
                service_type=SERVICE_ADD_REFRIGERANT,
                refrigerant_added_lbs=5.0,
                performed_at="2028-02-29T00:00:00Z",
                duration_minutes=60,
            ),
            make_technician_headers(technician["id"]),
        ),
        expected_status=201,
    )

    assert_instant(record["retention_until"], "2031-02-28T00:00:00Z", "retention_until")
    assert_mass(record["system_charge_after_lbs"], 85.0, "system_charge_after_lbs")
    assert_mass(record["leak_rate_pct_after"], 5.0, "leak_rate_pct_after")

    assert_system_charge(
        X.get_system(api, system["id"]), current_charge_lbs=85.0, leak_rate_pct=5.0
    )
    assert X.list_leak_events(api, system_id=system["id"])["meta"]["total_count"] == 0


def test_the_rolling_window_drops_an_addition_older_than_three_hundred_sixty_five_days(
    api,
):
    """
    §3.4 makes the trailing window's lower bound exclusive at the clock minus 365
    days, so a top-up from a year and a day ago no longer feeds the leak rate even
    though the charge ledger — which has no window at all — still counts it.

    Design: Corner/calculations/rolling_window_excludes_an_addition_older_than_three_hundred_sixty_five_days
    """
    env = X.base_env(
        api,
        with_second_technician=False,
        system_overrides={"full_charge_lbs": 200.0, "initial_charge_lbs": 0.0},
        equipment_overrides={"last_verification_on": "2026-08-01T00:00:00Z"},
        cylinder_overrides={
            "nominal_capacity_lbs": 100.0,
            "initial_contents_lbs": 80.0,
        },
    )

    old_record = X.file_service_record(
        api,
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        service_type=SERVICE_ADD_REFRIGERANT,
        cylinder_id=env["cyl1_id"],
        refrigerant_added_lbs=30.0,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=60,
    )
    assert_mass(old_record["leak_rate_pct_after"], 15.0, "leak_rate_pct_after")

    X.set_clock(api, "2027-08-02T00:00:00Z")
    eq2 = X.create_equipment(
        api,
        env["store_id"],
        env["tech1_id"],
        equipment_serial="RM-9002",
        last_verification_on="2027-08-01T00:00:00Z",
    )

    new_record = validate_success(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech1_id"],
                eq2["id"],
                X.system_version(api, env["system_id"]),
                cylinder_id=env["cyl1_id"],
                service_type=SERVICE_ADD_REFRIGERANT,
                refrigerant_added_lbs=20.0,
                performed_at="2027-08-02T00:00:00Z",
                duration_minutes=60,
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        expected_status=201,
    )
    assert_mass(new_record["leak_rate_pct_after"], 10.0, "leak_rate_pct_after")

    assert_system_charge(
        X.get_system(api, env["system_id"]),
        current_charge_lbs=50.0,
        leak_rate_pct=10.0,
    )
    assert X.list_leak_events(api, system_id=env["system_id"])["meta"]["total_count"] == 0
    assert_store_posture(
        X.get_store(api, env["store_id"]), compliance_status=POSTURE_COMPLIANT
    )


def test_regulated_aggregates_exclude_the_exempt_and_the_retired_system(api):
    """
    §3.1 scopes the store's regulated aggregates to systems that are both ACTIVE
    and REGULATED, summing nameplate `full_charge_lbs`: the 40.0 lb exempt system
    never counts, and the 60.0 lb regulated one stops counting once it is retired.

    Design: Corner/calculations/store_regulated_aggregates_exclude_exempt_and_retired_systems
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    regulated = X.create_system(api, store["id"], rt404["id"])
    exempt = X.create_system(
        api, store["id"], rt404["id"], full_charge_lbs=40.0, initial_charge_lbs=20.0
    )
    to_retire = X.create_system(
        api, store["id"], rt404["id"], full_charge_lbs=60.0, initial_charge_lbs=0.0
    )

    assert regulated["applicability"] == APPLICABILITY_REGULATED
    assert exempt["applicability"] == APPLICABILITY_EXEMPT
    assert to_retire["applicability"] == APPLICABILITY_REGULATED
    assert_store_posture(
        X.get_store(api, store["id"]),
        regulated_system_count=2,
        total_regulated_charge_lbs=160.0,
    )

    retired = validate_success(
        api.retire_system(
            to_retire["id"],
            F.retirement_payload(retirement_reason_code="END_OF_LIFE"),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert_system_axes(retired, operational_status=SYSTEM_RETIRED)
    assert_system_axes(
        X.get_system(api, regulated["id"]), operational_status=SYSTEM_ACTIVE
    )

    assert_store_posture(
        X.get_store(api, store["id"]),
        compliance_status=POSTURE_COMPLIANT,
        regulated_system_count=1,
        total_regulated_charge_lbs=100.0,
        chronic_leaker_flag=False,
    )


def test_penalty_exposure_is_truncated_by_the_statutory_cap(api):
    """
    §3.9 prices one MAJOR citation of 60 violation days at 270000.00 on a COMPLIANT
    store and then applies the 250000.00 statutory cap as a hard ceiling, raising
    `capped`; the store's total inherits the capped figure, not the raw one.

    Design: Corner/calculations/penalty_exposure_hits_the_statutory_cap_and_sets_capped_flag
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)

    inspection = validate_success(
        api.create_inspection(
            F.inspection_payload(
                store["id"],
                citations=[F.citation("608-VENT", SEVERITY_MAJOR, 60)],
                inspector_name="Inspector Vale",
            ),
            REGULATOR_HEADERS,
        ),
        expected_status=201,
    )

    assert_penalty_exposure(
        inspection,
        penalty_exposure_usd=250000.00,
        chronic_multiplier_applied=1.00,
        capped=True,
    )
    assert inspection["status"] == INSPECTION_OPEN
    assert_store_posture(
        X.get_store(api, store["id"]),
        compliance_status=POSTURE_COMPLIANT,
        penalty_exposure_total_usd=250000.00,
    )


def test_late_filing_walks_all_three_surcharge_brackets(api):
    """
    §3.9 selects the surcharge rate from `base_assessment_usd` alone: the same
    period filed on time, ten days late and forty days late assesses 0.00, then
    1650.00 at 0.10, then 6600.00 at 0.18. Three stores keep the period-overlap
    rule out of the way.

    Design: Corner/calculations/late_filing_walks_all_three_surcharge_brackets
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store_a = X.create_store(api)
    store_b = X.create_second_store(api)
    store_c = X.create_store(
        api, name="Eastgate Market", store_code="EG-003", state_code="NV"
    )

    period = {
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-06-30T00:00:00Z",
    }
    reports = {}
    for key, store in (("a", store_a), ("b", store_b), ("c", store_c)):
        report = validate_success(
            api.create_regulatory_report(
                F.regulatory_report_payload(store["id"], **period),
                COMPLIANCE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        assert_instant(report["due_on"], "2026-08-29T00:00:00Z", "due_on")
        reports[key] = report["id"]

    X.set_clock(api, "2026-08-29T00:00:00Z")
    on_time = X.submit_report(api, reports["a"], submission_note="Filed on the due date.")
    assert on_time["status"] == REPORT_SUBMITTED
    assert on_time["days_late"] == 0
    assert_money(on_time["base_assessment_usd"], 0.00, "base_assessment_usd")
    assert_money(
        on_time["administrative_surcharge_usd"], 0.00, "administrative_surcharge_usd"
    )
    assert_money(
        on_time["late_filing_assessment_usd"], 0.00, "late_filing_assessment_usd"
    )

    X.set_clock(api, "2026-09-08T00:00:00Z")
    ten_days = X.submit_report(api, reports["b"], submission_note="Ten days late.")
    assert ten_days["days_late"] == 10
    assert_money(ten_days["base_assessment_usd"], 1650.00, "base_assessment_usd")
    assert_money(
        ten_days["administrative_surcharge_usd"], 165.00, "administrative_surcharge_usd"
    )
    assert_money(
        ten_days["late_filing_assessment_usd"], 1815.00, "late_filing_assessment_usd"
    )

    X.set_clock(api, "2026-10-08T00:00:00Z")
    forty_days = validate_success(
        api.submit_regulatory_report(
            reports["c"],
            F.report_submission_payload(submission_note="Forty days late."),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert forty_days["days_late"] == 40
    assert_money(forty_days["base_assessment_usd"], 6600.00, "base_assessment_usd")
    assert_money(
        forty_days["administrative_surcharge_usd"],
        1188.00,
        "administrative_surcharge_usd",
    )
    assert_money(
        forty_days["late_filing_assessment_usd"], 7788.00, "late_filing_assessment_usd"
    )

    for key in ("a", "b", "c"):
        stored = X.get_report(api, reports[key])
        assert_mass(stored["total_leaked_lbs"], 0.0, "total_leaked_lbs")
        assert stored["included_system_count"] == 0
        assert stored["submission_count"] == 1


def test_a_closed_event_still_counts_toward_the_twelve_month_exceedance_tally(api):
    """
    §3.5 counts every non-VOIDED leak event in the trailing year, VERIFIED_CLOSED
    ones included, so a second detection a week after the first was fully repaired
    takes the count to 2 and makes the system a chronic leaker.

    Design: Corner/calculations/second_leak_event_within_the_year_counts_even_though_the_first_closed
    """
    env = X.manual_event_env(api)

    X.set_clock(api, "2026-08-08T00:00:00Z")
    attempt = X.file_repair_attempt(
        api,
        env["event_id"],
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        "2026-08-05T09:00:00Z",
        repair_method_code="BRAZE_JOINT",
    )
    X.file_verification_test(
        api,
        env["event_id"],
        attempt["id"],
        env["tech2_id"],
        "2026-08-07T10:00:00Z",
        test_method_code="PRESSURE_DECAY",
        result=RESULT_PASS,
        measured_leak_rate_pct=2.0,
    )
    X.file_verification_test(
        api,
        env["event_id"],
        attempt["id"],
        env["tech2_id"],
        "2026-08-07T11:00:00Z",
        test_method_code="ELECTRONIC_DETECTOR",
        result=RESULT_PASS,
        measured_leak_rate_pct=1.0,
    )

    assert X.get_leak_event(api, env["event_id"])["status"] == EVENT_VERIFIED_CLOSED
    closed_system = X.get_system(api, env["system_id"])
    assert_system_axes(closed_system, compliance_state=STATE_COMPLIANT)
    assert_system_charge(closed_system, exceedance_count_12mo=1)

    second = validate_success(
        api.create_leak_event(
            F.leak_event_payload(
                env["system_id"],
                detected_at="2026-08-08T00:00:00Z",
                detection_method=DETECTION_AUTOMATED_MONITORING,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert second["status"] == EVENT_OPEN

    system = X.get_system(api, env["system_id"])
    assert_system_charge(system, exceedance_count_12mo=2)
    assert_system_axes(system, compliance_state=STATE_CHRONIC_EXCEEDANCE)

    assert_store_posture(
        X.get_store(api, env["store_id"]),
        compliance_status=POSTURE_AT_RISK,
        chronic_leaker_flag=True,
        open_leak_event_count=1,
        overdue_leak_event_count=0,
    )


def test_a_repeating_leak_rate_quotient_rounds_half_up_to_one_decimal(api):
    """
    §2.6 carries leak rates to one decimal rounded half up, so 15.0 lbs on a 90.0 lb
    nameplate reports 16.7 rather than a truncated 16.6 or a two-decimal 16.67 — and
    16.7 is still short of the 20.0 threshold, so no event may open.

    Design: Corner/calculations/leak_rate_rounds_half_up_to_one_decimal_on_a_repeating_quotient
    """
    env = X.base_env(
        api,
        with_second_technician=False,
        system_overrides={"full_charge_lbs": 90.0, "initial_charge_lbs": 60.0},
    )

    record = validate_success(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                env["system"]["version"],
                cylinder_id=env["cyl1_id"],
                service_type=SERVICE_ADD_REFRIGERANT,
                refrigerant_added_lbs=15.0,
                performed_at="2026-08-01T00:00:00Z",
                duration_minutes=60,
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        expected_status=201,
    )
    assert_mass(record["leak_rate_pct_after"], 16.7, "leak_rate_pct_after")
    assert_mass(record["system_charge_after_lbs"], 75.0, "system_charge_after_lbs")

    assert_mass(
        X.get_cylinder(api, env["cyl1_id"])["current_contents_lbs"],
        25.0,
        "current_contents_lbs",
    )

    system = X.get_system(api, env["system_id"])
    assert_system_charge(system, current_charge_lbs=75.0, leak_rate_pct=16.7)
    assert_system_axes(system, compliance_state=STATE_COMPLIANT)
    assert X.list_leak_events(api, system_id=env["system_id"])["meta"]["total_count"] == 0
