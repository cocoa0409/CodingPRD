"""Attendance recordkeeping: dual-variant progress, thresholds, locking, and
validation-priority ordering."""
from test_helpers import (
    ApiErrorId,
    assert_enrollment,
    create_attendance_entry_payload,
    create_open_year,
    get_success_data,
    log_attendance,
    set_clock,
    setup_active_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


def _setup_active_with_clock(api, clock_iso, grade_level=4, family_name="Fam Att",
                             district_code="D-01"):
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], grade_level, family_name=family_name,
                                  district_code=district_code)
    set_clock(clock_iso)
    return ctx


def test_attendance_provisional_counts_recorded_and_verified(api):
    """PRD §3.4: "The **provisional** variant draws from both `RECORDED` and
    `VERIFIED` entries and lands on `provisional_days_counted` and
    `provisional_minutes_credited`; it powers the mid-year probation check of
    §3.9."
    PRD §2.9: "A calendar day qualifies as an instructional day once its recorded
    total reaches 240 minutes (four hours), and no single day ever contributes
    more than 600 minutes (ten hours) of credited time, however much was logged."

    Design: Difficulty/dual_variant_calc/attendance_provisional_vs_certified_progress
    """
    ctx = _setup_active_with_clock(api, "2026-09-04T00:00:00Z", family_name="Family Att",
                                   district_code="D-01")
    eid, parent = ctx["enrollment"]["id"], ctx["parent_headers"]
    a1 = log_attendance(ctx["enrollment"], ctx["family"], "2026-09-01", 300)
    log_attendance(ctx["enrollment"], ctx["family"], "2026-09-02", 240)  # stays RECORDED
    a3 = log_attendance(ctx["enrollment"], ctx["family"], "2026-09-03", 700)
    get_success_data(api.verify_attendance_entry(a1["id"], REVIEWER))
    get_success_data(api.verify_attendance_entry(a3["id"], REVIEWER))

    enrollment = validate_success(api.get_enrollment(eid, REGISTRAR))
    assert_enrollment(enrollment)
    assert enrollment["provisional_days_counted"] == 3
    # 300 + 240 + min(700, 600)
    assert enrollment["provisional_minutes_credited"] == 1140


def test_attendance_certified_counts_verified_only(api):
    """PRD §3.4: "The **certified** variant draws from `VERIFIED` entries only
    and lands on `certified_days_counted` and `certified_minutes_credited`; it
    powers the year-end noncompliance findings."
    PRD §3.4: "Identical raw logs therefore yield smaller certified totals
    whenever any entry remains unverified — verification is what converts
    provisional evidence into certified evidence."

    Design: Difficulty/dual_variant_calc/attendance_provisional_vs_certified_progress
    """
    ctx = _setup_active_with_clock(api, "2026-09-04T00:00:00Z", family_name="Family Att",
                                   district_code="D-01")
    eid = ctx["enrollment"]["id"]
    a1 = log_attendance(ctx["enrollment"], ctx["family"], "2026-09-01", 300)
    log_attendance(ctx["enrollment"], ctx["family"], "2026-09-02", 240)  # unverified
    a3 = log_attendance(ctx["enrollment"], ctx["family"], "2026-09-03", 700)
    get_success_data(api.verify_attendance_entry(a1["id"], REVIEWER))
    get_success_data(api.verify_attendance_entry(a3["id"], REVIEWER))

    enrollment = validate_success(api.get_enrollment(eid, REGISTRAR))
    assert enrollment["certified_days_counted"] == 2
    # 300 + 600; the unverified 240-minute day is excluded
    assert enrollment["certified_minutes_credited"] == 900
    assert enrollment["certified_minutes_credited"] != enrollment["provisional_minutes_credited"]


def test_day_qualifying_threshold_239_vs_240(api):
    """PRD §2.9: "A calendar day qualifies as an instructional day once its
    recorded total reaches 240 minutes (four hours), and no single day ever
    contributes more than 600 minutes (ten hours) of credited time, however much
    was logged."
    PRD §2.9: "Progress counters are exact integers — days and minutes, with no
    rounding of any kind."

    Design: Corner/cross_cutting_complexity_layers/day_qualifying_threshold_239_vs_240
    """
    ctx = _setup_active_with_clock(api, "2026-09-03T00:00:00Z", family_name="Fam Th",
                                   district_code="D-84")
    log_attendance(ctx["enrollment"], ctx["family"], "2026-09-01", 239)
    log_attendance(ctx["enrollment"], ctx["family"], "2026-09-02", 240)

    enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["provisional_days_counted"] == 1, "only the 240-minute date qualifies"
    assert enrollment["provisional_minutes_credited"] == 479, "239 + 240 both credit minutes"
    assert enrollment["certified_days_counted"] == 0, "nothing verified"


def test_duplicate_attendance_date_rejected(api):
    """PRD §3.4: "At most one non-voided entry may exist for an enrollment on a
    given date; a duplicate is rejected with `ERR_ATTENDANCE_DUPLICATE_DATE`."

    Design: Corner/validations/duplicate_attendance_date_rejected
    """
    ctx = _setup_active_with_clock(api, "2026-09-02T00:00:00Z", family_name="Fam Du",
                                   district_code="D-53")
    log_attendance(ctx["enrollment"], ctx["family"], "2026-09-01", 300)
    resp = api.create_attendance_entry(
        ctx["enrollment"]["id"],
        create_attendance_entry_payload(entry_date="2026-09-01", minutes=120),
        ctx["parent_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ATTENDANCE_DUPLICATE_DATE)


def test_attendance_future_date_uses_default_clock(api):
    """PRD §2.4: "At server startup the clock reads exactly
    `2026-08-01T00:00:00Z`; until it is explicitly advanced, every request
    observes that exact instant."
    PRD §3.4: "The date must fall within the academic year's `start_date` and
    `end_date` inclusive and must not lie in the future of the logical clock,
    else the entry is refused with `ERR_ATTENDANCE_DATE_OUT_OF_RANGE`."

    Design: Corner/validations/attendance_future_date_uses_default_clock
    """
    # Clock never set: every request observes 2026-08-01T00:00:00Z.
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Fu",
                                  district_code="D-54")
    entry = validate_success(
        api.create_attendance_entry(
            ctx["enrollment"]["id"],
            create_attendance_entry_payload(entry_date="2026-08-01", minutes=300),
            ctx["parent_headers"],
        ),
        201,
    )
    assert entry["entry_date"] == "2026-08-01", "equal to the clock date is not future"

    resp = api.create_attendance_entry(
        ctx["enrollment"]["id"],
        create_attendance_entry_payload(entry_date="2026-08-02", minutes=300),
        ctx["parent_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ATTENDANCE_DATE_OUT_OF_RANGE)


def test_attendance_verified_entry_locked(api):
    """PRD §3.4: "While an entry is `RECORDED`, the parent may correct its
    `minutes`; once it has left that state, corrections are locked and fail with
    `ERR_ATTENDANCE_ENTRY_LOCKED`."
    PRD §3.4: "Voiding is shared: the parent may void a `RECORDED` entry, while
    only a `Registrar` may void a `VERIFIED` one — a parent's attempt to void a
    verified entry meets `ERR_ATTENDANCE_ENTRY_LOCKED`."

    Design: Corner/errors/attendance_verified_entry_locked
    """
    ctx = _setup_active_with_clock(api, "2026-09-02T00:00:00Z", family_name="Fam Lk",
                                   district_code="D-71")
    entry = log_attendance(ctx["enrollment"], ctx["family"], "2026-09-01", 300)
    get_success_data(api.verify_attendance_entry(entry["id"], REVIEWER))

    resp_patch = api.patch_attendance_entry(entry["id"], {"minutes": 400}, ctx["parent_headers"])
    validate_error(resp_patch, ApiErrorId.ERR_ATTENDANCE_ENTRY_LOCKED)

    resp_void = api.void_attendance_entry(entry["id"], ctx["parent_headers"])
    validate_error(resp_void, ApiErrorId.ERR_ATTENDANCE_ENTRY_LOCKED)

    voided = validate_success(api.void_attendance_entry(entry["id"], REGISTRAR))
    assert voided["status"] == "VOIDED"

    enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["provisional_days_counted"] == 0
    assert enrollment["provisional_minutes_credited"] == 0
    assert enrollment["certified_days_counted"] == 0
    assert enrollment["certified_minutes_credited"] == 0


def test_attendance_state_error_precedes_temporal_error(api):
    """PRD §2.8: "Every request is evaluated against a fixed pipeline of checks,
    and the order is part of the contract — when several problems coexist, the
    earliest check in the pipeline determines the error the caller sees."
    PRD §2.8 item 6: "State feasibility: the target resource's current state must
    permit the operation."
    PRD §2.8 item 9: "Temporal windows: `ERR_ATTENDANCE_DATE_OUT_OF_RANGE`,
    `ERR_PORTFOLIO_WINDOW_CLOSED`, and
    `ERR_EXAM_REGISTRATION_DEADLINE_PASSED`."
    PRD §3.4: "A `Parent` logs an instructional day for an `ACTIVE` enrollment —
    attempts against an enrollment in any other status fail with
    `ERR_ENROLLMENT_NOT_ACTIVE`"

    Design: Difficulty/priority_pair_validation_conflict/attendance_state_before_temporal_priority
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Pri",
                                  district_code="D-14")
    withdrawn = validate_success(
        api.withdraw_enrollment(
            ctx["enrollment"]["id"], {"reason": "moving out of state"}, ctx["parent_headers"]
        )
    )
    assert withdrawn["enrollment_status"] == "WITHDRAWN"

    # One request violating both state (not ACTIVE) and temporal (2026-07-01 is
    # before the year's 2026-08-01 start) must surface the state error.
    resp = api.create_attendance_entry(
        ctx["enrollment"]["id"],
        create_attendance_entry_payload(entry_date="2026-07-01", minutes=300),
        ctx["parent_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)


def test_attendance_dual_failure_creates_no_entry(api):
    """PRD §3.4: "A `Parent` logs an instructional day for an `ACTIVE`
    enrollment — attempts against an enrollment in any other status fail with
    `ERR_ENROLLMENT_NOT_ACTIVE`"
    PRD §2.8: "Every request is evaluated against a fixed pipeline of checks,
    and the order is part of the contract — when several problems coexist, the
    earliest check in the pipeline determines the error the caller sees."

    Design: Difficulty/priority_pair_validation_conflict/attendance_state_before_temporal_priority
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Pri",
                                  district_code="D-14")
    get_success_data(
        api.withdraw_enrollment(
            ctx["enrollment"]["id"], {"reason": "moving out of state"}, ctx["parent_headers"]
        )
    )
    resp = api.create_attendance_entry(
        ctx["enrollment"]["id"],
        create_attendance_entry_payload(entry_date="2026-07-01", minutes=300),
        ctx["parent_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)
    entries, meta = validate_paginated(
        api.list_enrollment_attendance_entries(ctx["enrollment"]["id"], REGISTRAR)
    )
    assert meta["total_count"] == 0
    assert entries == []
