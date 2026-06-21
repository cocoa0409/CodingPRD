"""Series/session/enrollment lifecycle transitions and preconditions.

Corner-design coverage for the `state_machines` section, the enrollment_progress
calculation, the cancel cascade, OCC, and immediate consistency.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, make_owner_headers, make_trainer_headers,
    create_owner, create_dog, vaccinate_fully, create_trainer, create_series_draft,
    create_session, open_series, get_series, enroll, set_clock, create_package,
    mark_attendance_payload, attendance_for_session, mark_present_and_complete,
    setup_enroll_ready_group, setup_enrollment_with_attended_sessions,
    create_enrollment_payload, create_class_series_payload,
)


# ─── state_machines section ─────────────────────────────────────────────────────
def test_open_series_before_sessions_exist_rejected(api):
    """PRD §3.4: "First, the series must already have at least `session_count` session rows
    defined; if fewer exist the request is rejected with `ERR_SESSIONS_INCOMPLETE`."

    Design: Corner/state_machines/open_series_before_sessions_exist_returns_sessions_incomplete
    """
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=2)
    res = api.open_class_series(series["id"], TEST_USERS["admin_manager_headers"])
    validate_error(res, "ERR_SESSIONS_INCOMPLETE", expected_status=422)


def test_open_series_trainer_level_mismatch_rejected(api):
    """PRD §3.4: "Second, every session of the series must be assigned to a trainer whose
    `certified_levels` includes the series' `level`; a session whose trainer lacks that level
    certification rejects the open with `ERR_TRAINER_LEVEL_MISMATCH`."

    Design: Corner/state_machines/open_series_trainer_level_mismatch
    """
    trainer = create_trainer(certified_levels=["BASIC"])  # not ADVANCED
    series = create_series_draft(level="ADVANCED", modality="GROUP", capacity=5,
                                 session_count=1, list_price_cents=20000, credit_cost=3)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    res = api.open_class_series(series["id"], TEST_USERS["admin_manager_headers"])
    validate_error(res, "ERR_TRAINER_LEVEL_MISMATCH", expected_status=422)


def test_open_private_series_capacity_not_one_rejected(api):
    """PRD §3.4: "if the series' `modality` is `PRIVATE`, its `capacity` must equal exactly 1;
    a private series with any other capacity is rejected with `ERR_INVALID_PRIVATE_CAPACITY`.
    (This private-capacity rule is also enforced earlier wherever a private series' `capacity`
    is set, so an invalid private capacity never reaches the catalog.)"

    Because the rule is enforced at the point the capacity is set, a PRIVATE series with
    capacity != 1 can never be created (and so can never reach the OPEN gate). We assert the
    create-time rejection, which is the reachable manifestation of this rule.

    Design: Corner/state_machines/open_private_series_capacity_not_one
    """
    res = api.create_class_series(
        create_class_series_payload(level="BASIC", modality="PRIVATE", capacity=3,
                                    session_count=1, list_price_cents=30000, credit_cost=4),
        TEST_USERS["admin_manager_headers"])
    validate_error(res, "ERR_INVALID_PRIVATE_CAPACITY", expected_status=422)


def test_start_session_when_series_not_open_rejected(api):
    """PRD §3.8: "Starting a session moves it `SCHEDULED → IN_PROGRESS`; it is permitted only
    when the owning series is `OPEN` (otherwise `ERR_SERIES_NOT_OPEN`)".

    Design: Corner/state_machines/start_session_when_series_not_open
    """
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    sess = create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    # Series left in DRAFT.
    res = api.start_class_session(sess["id"], make_trainer_headers(trainer["id"]))
    validate_error(res, "ERR_SERIES_NOT_OPEN", expected_status=409)


def test_complete_session_with_unmarked_attendance_rejected(api):
    """PRD §3.8: "Completing a session moves it `IN_PROGRESS → COMPLETED`, and it is blocked
    while any attendance record for the session is still `EXPECTED` (unmarked); such a request
    is rejected with `ERR_ATTENDANCE_UNMARKED`."

    Design: Corner/state_machines/complete_session_with_unmarked_attendance
    """
    bundle = setup_enroll_ready_group(session_count=1)
    sess, trainer = bundle["sessions"][0], bundle["trainer"]
    enroll(bundle["owner"], bundle["dog"], bundle["series"],
           series_version=bundle["series"]["version"])
    api.start_class_session(sess["id"], make_trainer_headers(trainer["id"]))
    # Do NOT mark attendance; the EXPECTED record blocks completion.
    res = api.complete_class_session(sess["id"], make_trainer_headers(trainer["id"]))
    validate_error(res, "ERR_ATTENDANCE_UNMARKED", expected_status=409)


def test_cancel_already_cancelled_session_rejected(api):
    """PRD §3.8: "An `AdminManager` may cancel a session from either `SCHEDULED` or
    `IN_PROGRESS`, moving it to the terminal `CANCELLED` state." PRD §2.9: "A `ClassSession`
    `status` is one of `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`."

    Re-cancelling a terminal CANCELLED session is not a legal transition; the uniform
    invalid-state error applies.

    Design: Corner/state_machines/cancel_already_cancelled_session_invalid_state
    """
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    sess = create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    api.cancel_class_session(sess["id"], TEST_USERS["admin_manager_headers"])
    res = api.cancel_class_session(sess["id"], TEST_USERS["admin_manager_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_graduate_not_eligible_rejected(api):
    """PRD §3.9: "Graduation requires `graduation_eligible` to be true — equivalently,
    `sessions_attended` at least `session_count` — or it is rejected with
    `ERR_NOT_GRADUATION_ELIGIBLE`."

    Design: Corner/state_machines/graduate_not_eligible_returns_error
    """
    bundle = setup_enroll_ready_group(session_count=2)
    enr = enroll(bundle["owner"], bundle["dog"], bundle["series"],
                 series_version=bundle["series"]["version"])
    assert enr["sessions_attended"] == 0
    res = api.graduate_enrollment(enr["id"], TEST_USERS["admin_manager_headers"])
    validate_error(res, "ERR_NOT_GRADUATION_ELIGIBLE", expected_status=409)


def test_archive_series_with_live_enrollment_rejected(api):
    """PRD §3.4: "Archiving is blocked while the series still has any enrollment in `ACTIVE`,
    `WAITLISTED`, or `SUSPENDED`; such a request is rejected with
    `ERR_SERIES_HAS_LIVE_ENROLLMENTS`."

    Design: Corner/state_machines/archive_series_with_live_enrollment_rejected
    """
    bundle = setup_enroll_ready_group(session_count=1)
    enroll(bundle["owner"], bundle["dog"], bundle["series"],
           series_version=bundle["series"]["version"])
    api.close_class_series(bundle["series"]["id"], TEST_USERS["admin_manager_headers"])
    res = api.archive_class_series(bundle["series"]["id"], TEST_USERS["admin_manager_headers"])
    validate_error(res, "ERR_SERIES_HAS_LIVE_ENROLLMENTS", expected_status=409)


def test_enrollment_starts_active_after_seat_claim(api):
    """PRD §3.6: "Once every gate passes, seat availability decides the outcome: if the series
    has at least one seat available the enrollment becomes `ACTIVE`". PRD §3.6: "a `CASH`
    enrollment sets `price_charged_cents` to the series' `list_price_cents` and debits no
    credits".

    Design: Corner/state_machines/enrollment_starts_in_active_after_seat_claim
    """
    bundle = setup_enroll_ready_group(session_count=1, list_price_cents=12000, capacity=5)
    res = api.create_enrollment(
        create_enrollment_payload(bundle["dog"]["id"], bundle["series"]["id"],
                                  bundle["series"]["version"]),
        make_owner_headers(bundle["owner"]["id"]))
    enr = validate_success(res, 201)
    assert enr["status"] == "ACTIVE"
    assert enr["price_charged_cents"] == 12000, "CASH path uses list_price_cents"


# ─── calculations section ───────────────────────────────────────────────────────
def test_enrollment_progress_counts_present_nonmakeup(api):
    """PRD §3.9: "The `sessions_attended` count is the number of `PRESENT` attendance records
    on non-makeup sessions plus the number of attendance records in `MAKEUP_DONE`." PRD §3.9:
    "The `sessions_remaining` figure is the series' `session_count` minus `sessions_attended`,
    floored at 0."

    Design: Corner/calculations/enrollment_progress_counts_only_present_nonmakeup
    """
    bundle = setup_enrollment_with_attended_sessions(session_count=2, attend_n=1)
    enr = bundle["enrollment"]
    fetched = validate_success(
        api.get_enrollment(enr["id"], make_owner_headers(bundle["owner"]["id"])), 200)
    assert fetched["sessions_attended"] == 1, "one PRESENT non-makeup session"
    assert fetched["sessions_remaining"] == 1, "2 - 1"


# ─── cross_cutting_complexity_layers section ────────────────────────────────────
def test_occ_stale_series_version_rejected(api):
    """PRD §2.6: "If a prior enrollment, withdrawal, promotion, or graduation has advanced
    that `version` since the client last read the series, the supplied value is stale — the
    seat count the client is acting on may no longer be accurate, and the seat it believes is
    free may already be claimed — and the request is rejected with `ERR_STALE_SERIES_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_series_version_on_enrollment
    """
    set_clock()
    owner = create_owner()
    dogA = create_dog(owner, name="OcA")
    dogB = create_dog(owner, name="OcB")
    vaccinate_fully(owner, dogA)
    vaccinate_fully(owner, dogB)
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)
    stale_version = series["version"]

    # First enroll bumps series.version, making stale_version out of date.
    enroll(owner, dogA, series, series_version=stale_version)
    res = api.create_enrollment(
        create_enrollment_payload(dogB["id"], series["id"], stale_version),
        make_owner_headers(owner["id"]))
    validate_error(res, "ERR_STALE_SERIES_VERSION", expected_status=412)


def test_series_version_increments_on_enrollment(api):
    """PRD §3.6: "the series `version` is incremented by one (the version bump every other
    client must observe before its own seat claim)." PRD §2.4: "a `version`, an integer that
    starts at 1 on creation and increments by exactly 1 on every mutation."

    Design: Corner/cross_cutting_complexity_layers/series_version_increments_on_enrollment
    """
    bundle = setup_enroll_ready_group(session_count=1, capacity=5)
    series = bundle["series"]
    version_before = series["version"]
    enroll(bundle["owner"], bundle["dog"], series, series_version=version_before)
    after = get_series(series["id"])
    assert after["version"] == version_before + 1, "version advanced by exactly 1 on the enroll"


def test_session_cancel_cascades_attendance_to_missed_provider(api):
    """PRD §3.8: "A provider cancellation cascades in three layers. First, every attendance
    record for the session whose `state` is `EXPECTED` or `MAKEUP_PENDING` is moved to
    `MISSED_PROVIDER`. Second, each such record thereby becomes `makeup_eligible` (the miss
    was provider-caused)."

    Design: Corner/cross_cutting_complexity_layers/session_cancel_cascade_attendance_to_missed_provider
    """
    bundle = setup_enroll_ready_group(session_count=2)
    sess1 = bundle["sessions"][0]
    enroll(bundle["owner"], bundle["dog"], bundle["series"],
           series_version=bundle["series"]["version"])
    api.cancel_class_session(sess1["id"], TEST_USERS["admin_manager_headers"])
    att = attendance_for_session(sess1, make_owner_headers(bundle["owner"]["id"]))
    assert att["state"] == "MISSED_PROVIDER"
    assert att["makeup_eligible"] is True


# ─── consistency_model section ──────────────────────────────────────────────────
def test_package_debit_visible_in_same_request_flow(api):
    """PRD §2.7: "after any request returns, these derived fields equal what their source
    records imply." PRD §3.6: "a `PACKAGE` enrollment charges 0 cents and instead records a
    `DEBIT` `PackageRedemption` for the series' `credit_cost` against the named package,
    raising the package's `credits_consumed` by that amount".

    Design: Corner/consistency_model/enrollment_cascades_visible_same_request
    """
    bundle = setup_enroll_ready_group(session_count=1, credit_cost=2)
    owner = bundle["owner"]
    pkg = create_package(owner, tier="VALUE")  # 9 credits
    enroll(owner, bundle["dog"], bundle["series"], payment_method="PACKAGE",
           package_id=pkg["id"], series_version=bundle["series"]["version"])
    fetched = validate_success(api.get_package(pkg["id"], make_owner_headers(owner["id"])), 200)
    assert fetched["credits_remaining"] == 7, "9 - 2 debited, visible immediately"
