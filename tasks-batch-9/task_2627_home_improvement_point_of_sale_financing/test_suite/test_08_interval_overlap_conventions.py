"""Two overlap rules in one program that use opposite endpoint conventions.

A `MerchantLicense` coverage period is half-open, so two periods that touch at
an endpoint are both legal and equal endpoints describe an empty interval the
schema band rejects.  A `MerchantPromotionEnrollment` window is closed, so two
windows that touch at an endpoint conflict and equal endpoints describe a legal
one-day window.  The same calendar geometry therefore produces opposite verdicts
depending only on which resource is being contended.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import assert_fields
from test_helpers.test_users import ADMIN_HEADERS, UNDERWRITER_HEADERS

#: Licence A, filed by the fixtures as ROOFING / TX and then VERIFIED.
LICENSE_A_FROM = C.CANONICAL_LICENSE["effective_from"]  # 2026-01-01
LICENSE_A_UNTIL = C.CANONICAL_LICENSE["expires_on"]  # 2027-06-30

#: Enrollment E1, created by the fixtures on plan DI12-ROOF.
E1_START = C.ENROLLMENT_WINDOW_START  # 2026-08-01
E1_END = C.ENROLLMENT_WINDOW_END  # 2026-12-31


def _merchant_with_verified_license(api):
    """A ROOFING / TX merchant holding one VERIFIED licence over [2026-01-01, 2027-06-30)."""
    scenario = S.program(api)
    scenario.merchant = S.register_merchant(api)
    scenario.license = S.file_license(api, scenario.merchant_id)
    S.verify_license(api, scenario.merchant_id, scenario.license["id"], "VERIFIED")
    return scenario


def _file_license(api, scenario, license_number, effective_from, expires_on, **overrides):
    """Post one licence filing and hand back the raw response for either arm."""
    return api.file_license(
        scenario.merchant_id,
        F.license_payload(
            license_number=license_number,
            effective_from=effective_from,
            expires_on=expires_on,
            **overrides,
        ),
        ADMIN_HEADERS,
    )


def _license_count(api, scenario):
    _rows, meta = validate_paginated(
        api.list_licenses(scenario.merchant_id, UNDERWRITER_HEADERS)
    )
    return meta["total_count"]


def _enrolled_merchant_with_second_plan(api):
    """An APPROVED merchant with ACTIVE enrollment E1 on plan one, plus a second eligible plan."""
    scenario = S.enrolled_merchant(api)
    scenario.second_plan = S.create_promotion_plan(api, **C.SECOND_PLAN)
    return scenario


def _enroll(api, scenario, window_start_date, window_end_date, plan_id=None,
            negotiated_discount_bps=C.NEGOTIATED_DISCOUNT_BPS):
    """Post one promotion-enrollment creation and hand back the raw response."""
    return api.create_promotion_enrollment(
        scenario.merchant_id,
        F.promotion_enrollment_payload(
            plan_id or scenario.plan_id,
            window_start_date=window_start_date,
            window_end_date=window_end_date,
            negotiated_discount_bps=negotiated_discount_bps,
        ),
        UNDERWRITER_HEADERS,
    )


def _enrollment_count(api, scenario):
    _rows, meta = validate_paginated(
        api.list_merchant_promotion_enrollments(scenario.merchant_id, UNDERWRITER_HEADERS)
    )
    return meta["total_count"]


def test_a_license_touching_the_right_endpoint_of_existing_coverage_is_accepted(api):
    """Filing [2027-06-30, 2028-06-30) beside coverage ending 2027-06-30 is legal because the interval is half-open.

    PRD: "Because the interval is half-open, two coverage periods conflict when the first begins strictly before the second ends and the second begins strictly before the first ends; periods that merely touch, where one's `expires_on` equals the other's `effective_from`, do not conflict."

    Design: Difficulty/resource_temporal_overlap/license_coverage_half_open_overlap_touching_allowed
    """
    scenario = _merchant_with_verified_license(api)

    filed = validate_success(
        _file_license(api, scenario, "TX-RCF-90001", LICENSE_A_UNTIL, "2028-06-30"), 201
    )

    assert_fields(
        filed,
        trade_type="ROOFING",
        state_code="TX",
        effective_from=LICENSE_A_UNTIL,
        expires_on="2028-06-30",
        verification_status="UNVERIFIED",
    )
    assert _license_count(api, scenario) == 2


def test_a_license_touching_the_left_endpoint_of_existing_coverage_is_accepted(api):
    """Filing [2025-06-01, 2026-01-01) below coverage starting 2026-01-01 is legal for the same reason.

    PRD: "Because the interval is half-open, two coverage periods conflict when the first begins strictly before the second ends and the second begins strictly before the first ends; periods that merely touch, where one's `expires_on` equals the other's `effective_from`, do not conflict."

    Design: Difficulty/resource_temporal_overlap/license_coverage_half_open_overlap_touching_allowed
    """
    scenario = _merchant_with_verified_license(api)

    filed = validate_success(
        _file_license(api, scenario, "TX-RCF-70000", "2025-06-01", LICENSE_A_FROM), 201
    )

    assert_fields(
        filed,
        effective_from="2025-06-01",
        expires_on=LICENSE_A_FROM,
        verification_status="UNVERIFIED",
    )
    assert _license_count(api, scenario) == 2


def test_a_license_overlapping_existing_coverage_by_one_day_is_refused(api):
    """Pulling the touching interval back a single day to [2027-06-29, 2028-06-29) creates a real conflict.

    PRD: "Licence coverage may not overlap for the same combination of merchant, `trade_type` and `state_code` among licences whose `verification_status` is `UNVERIFIED` or `VERIFIED`."

    Design: Difficulty/resource_temporal_overlap/license_coverage_half_open_overlap_touching_allowed
    """
    scenario = _merchant_with_verified_license(api)
    validate_success(
        _file_license(api, scenario, "TX-RCF-90001", LICENSE_A_UNTIL, "2028-06-30"), 201
    )

    response = _file_license(api, scenario, "TX-RCF-90002", "2027-06-29", "2028-06-29")

    validate_error(response, E.ERR_LICENSE_COVERAGE_OVERLAP)
    assert _license_count(api, scenario) == 2


def test_a_license_with_equal_endpoints_is_refused_as_an_empty_coverage_period(api):
    """Equal endpoints on a half-open licence interval fail the schema band, not the overlap band.

    PRD: "Date-range coherence inside a single payload: a licence must have `effective_from` strictly earlier than `expires_on`, because the interval is half-open and equal dates would describe an empty coverage period; an enrollment must have `window_start_date` earlier than or equal to `window_end_date`, because the interval is closed and equal dates describe a legitimate one-day window."

    Design: Difficulty/resource_temporal_overlap/license_coverage_half_open_overlap_touching_allowed
    """
    scenario = _merchant_with_verified_license(api)

    # 2026-06-01 also sits inside licence A, so the overlap rule at priority 35
    # would fire too; the earlier date-range check is the one that reports.
    response = _file_license(api, scenario, "TX-RCF-90003", "2026-06-01", "2026-06-01")

    validate_error(response, E.ERR_INVALID_DATE_RANGE)
    assert _license_count(api, scenario) == 1


def test_the_license_contention_key_includes_trade_type_and_state_code(api):
    """An interval nested wholly inside existing coverage is accepted under a different state or trade.

    PRD: "Licence coverage may not overlap for the same combination of merchant, `trade_type` and `state_code` among licences whose `verification_status` is `UNVERIFIED` or `VERIFIED`."

    Design: Difficulty/resource_temporal_overlap/license_coverage_half_open_overlap_touching_allowed
    """
    scenario = _merchant_with_verified_license(api)

    other_state = validate_success(
        _file_license(
            api, scenario, "CA-RCF-40011", "2026-06-01", "2027-06-01", state_code="CA"
        ),
        201,
    )
    other_trade = validate_success(
        _file_license(
            api, scenario, "TX-HVC-11223", "2026-06-01", "2027-06-01", trade_type="HVAC"
        ),
        201,
    )

    assert_fields(other_state, state_code="CA", trade_type="ROOFING")
    assert_fields(other_trade, state_code="TX", trade_type="HVAC")
    assert _license_count(api, scenario) == 3


def test_an_enrollment_window_touching_the_previous_window_conflicts(api):
    """A window starting on the day the live window ends conflicts, because the window is closed.

    PRD: "Because the interval is closed, two windows conflict when the first begins on or before the second ends and the second begins on or before the first ends; windows that merely touch, where one's `window_end_date` equals the other's `window_start_date`, do conflict — the opposite of the licence rule."

    Design: Difficulty/resource_temporal_overlap/enrollment_window_closed_overlap_touching_conflicts
    """
    scenario = _enrolled_merchant_with_second_plan(api)
    assert_fields(
        scenario.enrollment,
        status="ACTIVE",
        window_start_date=E1_START,
        window_end_date=E1_END,
    )

    response = _enroll(api, scenario, E1_END, "2027-06-30")

    validate_error(response, E.ERR_ENROLLMENT_WINDOW_OVERLAP)
    assert _enrollment_count(api, scenario) == 1


def test_touching_endpoints_diverge_between_license_and_enrollment_intervals(api):
    """The identical touch geometry is accepted for licence coverage and refused for an enrollment window.

    PRD: "Because the interval is closed, two windows conflict when the first begins on or before the second ends and the second begins on or before the first ends; windows that merely touch, where one's `window_end_date` equals the other's `window_start_date`, do conflict — the opposite of the licence rule."

    Design: Difficulty/resource_temporal_overlap/enrollment_window_closed_overlap_touching_conflicts
    """
    scenario = _enrolled_merchant_with_second_plan(api)

    # Half-open licence coverage: the new period starts on the day the old one ends.
    touching_license = validate_success(
        _file_license(api, scenario, "TX-RCF-90001", LICENSE_A_UNTIL, "2028-06-30"), 201
    )
    # Closed enrollment window: the new window starts on the day the old one ends.
    touching_window = _enroll(api, scenario, E1_END, "2027-06-30")

    assert_fields(touching_license, effective_from=LICENSE_A_UNTIL)
    validate_error(touching_window, E.ERR_ENROLLMENT_WINDOW_OVERLAP)
    assert _license_count(api, scenario) == 2
    assert _enrollment_count(api, scenario) == 1


def test_an_enrollment_window_starting_one_day_later_is_accepted(api):
    """One clear day of separation is exactly enough for a closed window to be free of conflict.

    PRD: "Enrollment windows may not overlap for the same combination of merchant and promotion plan among enrollments whose `status` is `ACTIVE` or `SUSPENDED`."

    Design: Difficulty/resource_temporal_overlap/enrollment_window_closed_overlap_touching_conflicts
    """
    scenario = _enrolled_merchant_with_second_plan(api)

    created = validate_success(_enroll(api, scenario, "2027-01-01", "2027-06-30"), 201)

    assert_fields(
        created,
        status="ACTIVE",
        window_start_date="2027-01-01",
        window_end_date="2027-06-30",
        negotiated_discount_bps=C.NEGOTIATED_DISCOUNT_BPS,
    )
    assert _enrollment_count(api, scenario) == 2


def test_an_enrollment_window_straddling_two_live_windows_conflicts(api):
    """A window that overlaps both neighbours by a day or more at each end is refused.

    PRD: "Enrollment windows may not overlap for the same combination of merchant and promotion plan among enrollments whose `status` is `ACTIVE` or `SUSPENDED`."

    Design: Difficulty/resource_temporal_overlap/enrollment_window_closed_overlap_touching_conflicts
    """
    scenario = _enrolled_merchant_with_second_plan(api)
    validate_success(_enroll(api, scenario, "2027-01-01", "2027-06-30"), 201)

    # [2026-12-30, 2027-01-05] meets E1 on 2026-12-30..2026-12-31 and E3 on
    # 2027-01-01..2027-01-05.
    response = _enroll(api, scenario, "2026-12-30", "2027-01-05")

    validate_error(response, E.ERR_ENROLLMENT_WINDOW_OVERLAP)
    assert _enrollment_count(api, scenario) == 2


def test_the_enrollment_contention_key_includes_the_promotion_plan(api):
    """The byte-identical window is accepted on a second plan because the key is merchant plus plan.

    PRD: "Enrollment windows may not overlap for the same combination of merchant and promotion plan among enrollments whose `status` is `ACTIVE` or `SUSPENDED`."

    Design: Difficulty/resource_temporal_overlap/enrollment_window_closed_overlap_touching_conflicts
    """
    scenario = _enrolled_merchant_with_second_plan(api)

    created = validate_success(
        _enroll(
            api,
            scenario,
            E1_START,
            E1_END,
            plan_id=scenario.second_plan["id"],
            negotiated_discount_bps=620,
        ),
        201,
    )

    assert_fields(
        created,
        status="ACTIVE",
        promotion_plan_id=scenario.second_plan["id"],
        window_start_date=E1_START,
        window_end_date=E1_END,
        negotiated_discount_bps=620,
    )
    assert _enrollment_count(api, scenario) == 2


def test_the_overlap_check_pre_empts_the_before_approval_check(api):
    """A window that both overlaps E1 and starts before approval reports the overlap error only.

    PRD: "The first check whose condition is violated wins: the request is rejected with that check's error identifier and status, no later check runs, and no side effect of any kind is written."

    Design: Difficulty/resource_temporal_overlap/enrollment_window_closed_overlap_touching_conflicts
    """
    scenario = _enrolled_merchant_with_second_plan(api)
    # The merchant was approved on 2026-08-01, so 2026-07-31 is before approval.
    assert scenario.merchant["approved_on"].startswith(C.DEFAULT_CLOCK_DATE)

    response = _enroll(api, scenario, "2026-07-31", "2026-08-05")

    validate_error(response, E.ERR_ENROLLMENT_WINDOW_OVERLAP)
    assert _enrollment_count(api, scenario) == 1


def test_the_before_approval_check_is_observable_when_nothing_overlaps(api):
    """A window entirely clear of E1 but starting before approval reports the temporal error.

    PRD: "An enrollment window may not begin before the merchant was approved: `window_start_date` must fall on or after the calendar date of the merchant's `approved_on` instant, otherwise `ERR_ENROLLMENT_WINDOW_BEFORE_APPROVAL`."

    Design: Difficulty/resource_temporal_overlap/enrollment_window_closed_overlap_touching_conflicts
    """
    scenario = _enrolled_merchant_with_second_plan(api)

    response = _enroll(api, scenario, "2026-07-01", "2026-07-15")

    validate_error(response, E.ERR_ENROLLMENT_WINDOW_BEFORE_APPROVAL)
    assert _enrollment_count(api, scenario) == 1


def test_equal_enrollment_endpoints_describe_a_legal_one_day_window(api):
    """The same endpoint equality that empties a half-open licence interval is a valid closed window.

    PRD: "Date-range coherence inside a single payload: a licence must have `effective_from` strictly earlier than `expires_on`, because the interval is half-open and equal dates would describe an empty coverage period; an enrollment must have `window_start_date` earlier than or equal to `window_end_date`, because the interval is closed and equal dates describe a legitimate one-day window."

    Design: Difficulty/resource_temporal_overlap/enrollment_window_closed_overlap_touching_conflicts
    """
    scenario = _enrolled_merchant_with_second_plan(api)

    created = validate_success(_enroll(api, scenario, "2027-07-01", "2027-07-01"), 201)

    assert_fields(
        created,
        status="ACTIVE",
        window_start_date="2027-07-01",
        window_end_date="2027-07-01",
    )
    assert _enrollment_count(api, scenario) == 2


def test_reversed_enrollment_endpoints_are_refused(api):
    """A window whose start falls after its end fails the date-range band.

    PRD: "Date-range coherence inside a single payload: a licence must have `effective_from` strictly earlier than `expires_on`, because the interval is half-open and equal dates would describe an empty coverage period; an enrollment must have `window_start_date` earlier than or equal to `window_end_date`, because the interval is closed and equal dates describe a legitimate one-day window."

    Design: Difficulty/resource_temporal_overlap/enrollment_window_closed_overlap_touching_conflicts
    """
    scenario = _enrolled_merchant_with_second_plan(api)

    response = _enroll(api, scenario, "2027-08-01", "2027-07-01")

    validate_error(response, E.ERR_INVALID_DATE_RANGE)
    assert _enrollment_count(api, scenario) == 1
