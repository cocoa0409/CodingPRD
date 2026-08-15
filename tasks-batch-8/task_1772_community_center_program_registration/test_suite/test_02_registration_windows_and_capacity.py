"""Registration gauntlet: temporal windows, age eligibility, session-open gate,
seat-capacity boundary, immediate consistency, and OCC on create."""
from test_helpers import (
    PC,
    ApiErrorId,
    assert_instant_eq,
    create_class_session,
    create_household,
    create_instructor,
    create_participant_payload,
    create_published_season,
    create_program,
    get_registration,
    get_session,
    get_session_version,
    household_headers,
    register_participant,
    set_clock,
    setup_household_with_participants,
    setup_published_session,
    try_register,
    validate_error,
    validate_success,
    verify_residency,
)
from test_helpers import api_client as _api


def test_window_open_exact_admits_and_close_exact_rejects(api):
    """PRD §3.6: "During the resident-priority window — from
    `resident_opens_at` up to but not including `general_opens_at` — only
    households whose `residency_status` is `RESIDENT` may register;
    `NONRESIDENT` and still-`PENDING` households are turned away with
    `ERR_RESIDENT_PRIORITY_WINDOW`. Once now reaches `registration_closes_at`
    registration is over — equality means closed — and the attempt is rejected
    with `ERR_REGISTRATION_WINDOW_CLOSED`."
    PRD §3.6: "The base is the session's `fee_resident_cents` when the
    household's `residency_status` is `RESIDENT` at the creation instant, and
    `fee_nonresident_cents` otherwise, a still-`PENDING` household paying the
    non-resident rate; that basis is snapshotted onto the registration as
    `residency_at_registration`, `RESIDENT` if and only if the household was
    `RESIDENT` at that instant."

    Design: Corner/validations/window_boundaries_open_exact_and_closed_exact
    """
    ctx = setup_published_session(fee_resident_cents=5000, fee_nonresident_cents=7000,
                                  clock=None)
    session_id = ctx["session"]["id"]
    household, participants = setup_household_with_participants(count=2,
                                                                account_name="HL")

    # At general_opens_at exactly the general window is open.
    set_clock("2026-08-17T00:00:00Z")
    registration = register_participant(session_id, participants[0]["id"],
                                        household["id"])
    assert registration["enrollment_status"] == "ENROLLED"
    assert registration["fee_charged_cents"] == 7000
    assert registration["residency_at_registration"] == "NONRESIDENT"

    # At registration_closes_at exactly registration is over.
    set_clock("2026-09-15T00:00:00Z")
    resp = try_register(session_id, participants[1]["id"], household["id"],
                        get_session_version(session_id))
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED, 422)


def test_resident_window_priority_enforced(api):
    """PRD §3.6: "Before `resident_opens_at` nobody may register, and the
    attempt is rejected with `ERR_REGISTRATION_WINDOW_NOT_OPEN`. During the
    resident-priority window — from `resident_opens_at` up to but not
    including `general_opens_at` — only households whose `residency_status` is
    `RESIDENT` may register; `NONRESIDENT` and still-`PENDING` households are
    turned away with `ERR_RESIDENT_PRIORITY_WINDOW`."

    Design: Corner/validations/resident_window_priority_enforced
    """
    ctx = setup_published_session(fee_resident_cents=5000, fee_nonresident_cents=7000,
                                  clock=None)
    session_id = ctx["session"]["id"]
    resident, res_parts = setup_household_with_participants(
        count=1, residency="RESIDENT", account_name="HR", name_prefix="Lane R")
    nonresident, non_parts = setup_household_with_participants(
        count=1, residency="NONRESIDENT", account_name="HN", name_prefix="Lane N")

    # A resident household registers at resident_opens_at exactly.
    set_clock("2026-08-10T00:00:00Z")
    registration = register_participant(session_id, res_parts[0]["id"], resident["id"])
    assert registration["enrollment_status"] == "ENROLLED"
    assert registration["fee_charged_cents"] == 5000
    assert registration["residency_at_registration"] == "RESIDENT"

    # One second before the general opening a nonresident is turned away.
    set_clock("2026-08-16T23:59:59Z")
    resp = try_register(session_id, non_parts[0]["id"], nonresident["id"],
                        get_session_version(session_id))
    validate_error(resp, ApiErrorId.ERR_RESIDENT_PRIORITY_WINDOW, 422)


def test_age_boundary_inclusive(api):
    """PRD §3.6: "Then age eligibility: the participant's age is the whole
    years completed between `birth_date` and the season's `start_date`, a
    birthday falling exactly on `start_date` counting as reached, and the age
    must be at least the program's `min_age` and at most its `max_age`, both
    bounds inclusive, else `ERR_AGE_INELIGIBLE`."

    Design: Corner/validations/age_boundary_inclusive
    """
    ctx = setup_published_session(
        program_overrides={"name": "Junior Hoops", "min_age": 6, "max_age": 12},
    )
    session_id = ctx["session"]["id"]
    household, participants = setup_household_with_participants(
        count=2, account_name="HK", name_prefix="Born",
        birth_dates=("2020-09-01T00:00:00Z", "2020-09-02T00:00:00Z"),
    )

    # Born exactly on the season start six years earlier: age 6, eligible.
    registration = register_participant(session_id, participants[0]["id"],
                                        household["id"])
    assert registration["enrollment_status"] == "ENROLLED"

    # Born one day later: still 5 at season start, ineligible.
    resp = try_register(session_id, participants[1]["id"], household["id"],
                        get_session_version(session_id))
    validate_error(resp, ApiErrorId.ERR_AGE_INELIGIBLE, 422)


def test_registration_into_draft_session_rejected(api):
    """PRD §3.6: "after the generic rungs of §2.8 and the stale-version check
    of §2.7, the season gates fire first — a season still `DRAFT` rejects with
    `ERR_SEASON_NOT_PUBLISHED`, a season already `CLOSED` with
    `ERR_SEASON_CLOSED` — then the session itself must be `PUBLISHED` or
    `ACTIVE`, else `ERR_SESSION_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/registration_requires_session_open
    """
    season = create_published_season()
    program = create_program(season["id"], name="Drama", category="Arts")
    instructor = create_instructor()
    session = create_class_session(program["id"], instructor["id"], title="Drama")
    household, participants = setup_household_with_participants(count=1,
                                                                account_name="HW")
    set_clock("2026-08-17T00:00:00Z")

    resp = try_register(session["id"], participants[0]["id"], household["id"],
                        session["version"])
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN, 409)


def test_registration_after_publish_succeeds(api):
    """PRD §3.6: "then the session itself must be `PUBLISHED` or `ACTIVE`,
    else `ERR_SESSION_NOT_OPEN`."
    PRD §3.6: "A registration that clears the gauntlet lands in one of two
    places. If the session's `enrolled_count` has already reached `capacity`,
    the newcomer is `WAITLISTED` and its `waitlisted_at` records the instant;
    otherwise it is `ENROLLED`."

    Design: Difficulty/cross_entity_state_dependency/registration_requires_session_open
    """
    ctx = setup_published_session()
    household, participants = setup_household_with_participants(count=1,
                                                                account_name="HW")
    registration = register_participant(ctx["session"]["id"], participants[0]["id"],
                                        household["id"])
    assert registration["enrollment_status"] == "ENROLLED"


def test_state_error_beats_window_closed(api):
    """PRD §3.6: "the season gates fire first — a season still `DRAFT` rejects
    with `ERR_SEASON_NOT_PUBLISHED`, a season already `CLOSED` with
    `ERR_SEASON_CLOSED` — then the session itself must be `PUBLISHED` or
    `ACTIVE`, else `ERR_SESSION_NOT_OPEN`. Next come the temporal windows in
    their chronological logic." and "Once now reaches
    `registration_closes_at` registration is over — equality means closed —
    and the attempt is rejected with `ERR_REGISTRATION_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/state_over_temporal_on_register
    """
    season = create_published_season()
    program = create_program(season["id"], name="Zumba", category="Fitness")
    instructor = create_instructor()
    session = create_class_session(program["id"], instructor["id"], title="Zumba PM")
    household, participants = setup_household_with_participants(count=1,
                                                                account_name="HZ")
    set_clock("2026-09-15T00:00:00Z")

    # Session still DRAFT while the window is also closed: the session-open
    # gate is evaluated before the temporal windows.
    resp = try_register(session["id"], participants[0]["id"], household["id"],
                        session["version"])
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN, 409)


def test_window_closed_fires_when_session_open(api):
    """PRD §3.6: "then the session itself must be `PUBLISHED` or `ACTIVE`,
    else `ERR_SESSION_NOT_OPEN`. Next come the temporal windows in their
    chronological logic." and "Once now reaches `registration_closes_at`
    registration is over — equality means closed — and the attempt is rejected
    with `ERR_REGISTRATION_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/state_over_temporal_on_register
    """
    ctx = setup_published_session(clock=None)
    household, participants = setup_household_with_participants(count=1,
                                                                account_name="HZ")
    set_clock("2026-09-15T00:00:00Z")

    resp = try_register(ctx["session"]["id"], participants[0]["id"], household["id"],
                        get_session_version(ctx["session"]["id"]))
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED, 422)


def test_first_registration_lands_enrolled_with_72h_deadline(api):
    """PRD §3.6: "If the session's `enrolled_count` has already reached
    `capacity`, the newcomer is `WAITLISTED` and its `waitlisted_at` records
    the instant; otherwise it is `ENROLLED`."
    PRD §3.6: "A registration landing `ENROLLED` with a fee greater than zero
    is born with `payment_status` `PENDING` and a `payment_due_at` deadline
    seventy-two hours — three days — after its creation."

    Design: Difficulty/boundary_precision_check/capacity_boundary_enrolled_vs_waitlisted
    """
    ctx = setup_published_session(capacity=1, fee_resident_cents=5000,
                                  fee_nonresident_cents=5000)
    session_id = ctx["session"]["id"]
    household, participants = setup_household_with_participants(count=1,
                                                                account_name="HA")

    registration = register_participant(session_id, participants[0]["id"],
                                        household["id"])
    # Created while enrolled_count 0 < capacity 1 at clock 2026-08-17T00:00:00Z.
    assert registration["enrollment_status"] == "ENROLLED"
    assert registration["payment_status"] == "PENDING"
    assert_instant_eq(registration["payment_due_at"], "2026-08-20T00:00:00Z")
    assert get_session(session_id)["enrolled_count"] == 1


def test_registration_at_full_capacity_waitlists(api):
    """PRD §3.6: "If the session's `enrolled_count` has already reached
    `capacity`, the newcomer is `WAITLISTED` and its `waitlisted_at` records
    the instant; otherwise it is `ENROLLED`. Either way the session's
    corresponding counter increases by one and the session's `version` bumps —
    which is precisely why the create carries the OCC token."
    PRD §3.6: "A `WAITLISTED` registration keeps `payment_status` `PENDING`
    with `payment_due_at` null while it waits."

    Design: Difficulty/boundary_precision_check/capacity_boundary_enrolled_vs_waitlisted
    """
    ctx = setup_published_session(capacity=1, fee_resident_cents=5000,
                                  fee_nonresident_cents=5000)
    session_id = ctx["session"]["id"]
    household_a, parts_a = setup_household_with_participants(count=1, account_name="HA")
    household_b, parts_b = setup_household_with_participants(count=1, account_name="HB")

    register_participant(session_id, parts_a[0]["id"], household_a["id"])
    waitlisted = register_participant(session_id, parts_b[0]["id"], household_b["id"])

    # enrolled_count == capacity exactly means full — the newcomer waits.
    assert waitlisted["enrollment_status"] == "WAITLISTED"
    assert waitlisted["payment_status"] == "PENDING"
    assert waitlisted["payment_due_at"] is None
    assert_instant_eq(waitlisted["waitlisted_at"], "2026-08-17T00:00:00Z")
    session = get_session(session_id)
    assert session["enrolled_count"] == 1
    assert session["waitlist_count"] == 1


def test_immediate_consistency_read_after_write(api):
    """PRD §3.6: "Either way the session's corresponding counter increases by
    one and the session's `version` bumps — which is precisely why the create
    carries the OCC token."
    PRD §2.10: "the server reconciles the dependents inside the same
    operation, without requiring separate client calls."

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    ctx = setup_published_session()
    session_id = ctx["session"]["id"]
    household, participants = setup_household_with_participants(count=1,
                                                                account_name="HW")

    registration = register_participant(session_id, participants[0]["id"],
                                        household["id"])
    assert registration["enrollment_status"] == "ENROLLED"
    assert registration["fee_charged_cents"] == 5000

    session = get_session(session_id)
    assert session["enrolled_count"] == 1
    assert session["version"] == ctx["session_version"] + 1


def test_occ_stale_version_on_registration_create(api):
    """PRD §2.7: "Creating a registration requires a non-optional
    `expected_class_session_version` field carrying the current `version` of
    the target session as the client last observed it. If the session's
    version has advanced since that observation — for example, because another
    registration has legitimately consumed a seat or a waitlist position in
    the meantime, which itself bumps the session's version — the client's view
    of seat availability is stale, and the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_registration_create
    """
    ctx = setup_published_session()
    session_id = ctx["session"]["id"]
    stale_version = ctx["session_version"]
    household, participants = setup_household_with_participants(count=2,
                                                                account_name="HT")

    first = try_register(session_id, participants[0]["id"], household["id"],
                         stale_version)
    validate_success(first, 201)

    resp = try_register(session_id, participants[1]["id"], household["id"],
                        stale_version)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
