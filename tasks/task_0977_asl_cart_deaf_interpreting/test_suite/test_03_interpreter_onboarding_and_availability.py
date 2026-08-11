"""Interpreter onboarding fields/versioning, availability half-open interval rules,
and the offer-time coverage gate."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_interpreter_headers,
    assert_interpreter,
    assert_strike_record,
    assert_instant_equal,
    set_clock,
    create_org,
    create_standard_rate_card,
    create_active_interpreter,
    create_manual_strike,
    add_availability,
    create_submitted_request,
    offer_to,
    get_request_version,
    create_offer_payload,
    create_interpreter_payload,
    create_certification_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_interpreter_system_fields_on_create_and_version_increments():
    """PRD §3.2: "A new interpreter starts `PENDING_ONBOARD` with both quality scores
    at 100 and an `active_strike_count` of zero."
    PRD §2.5: "The `version` field is an integer that increments by one on every
    mutation and anchors the optimistic-concurrency rules of §2.7."

    Design: Corner/entities/interpreter_system_fields_on_create_and_version_increments
    """
    set_clock("2026-05-01T00:00:00Z")
    interp = get_success_data(api_client.create_interpreter(
        create_interpreter_payload(), ADMIN))
    assert_interpreter(interp)
    assert interp["status"] == "PENDING_ONBOARD"
    assert interp["quality_score"] == 100
    assert interp["quality_score_provisional"] == 100
    assert interp["active_strike_count"] == 0
    v_create = interp["version"]

    cert = get_success_data(api_client.create_certification(
        interp["id"], create_certification_payload(), ADMIN))
    get_success_data(api_client.verify_certification(interp["id"], cert["id"], ADMIN))

    activated = get_success_data(api_client.activate_interpreter(interp["id"], ADMIN))
    assert activated["version"] == v_create + 1, "activate increments version by exactly 1"

    suspended = get_success_data(api_client.suspend_interpreter(interp["id"], ADMIN))
    assert suspended["version"] == v_create + 2, "suspend increments version by exactly 1"

    reinstated = get_success_data(api_client.reinstate_interpreter(interp["id"], ADMIN))
    assert reinstated["version"] == v_create + 3, "reinstate increments version by exactly 1"
    assert reinstated["status"] == "ACTIVE"


def test_strike_record_has_no_version_field():
    """PRD §2.5: "One entity is deliberately lighter: a StrikeRecord carries only `id`
    and `created_at`; both `updated_at` and `version` are absent from it, because a
    strike is created once and thereafter only its `status` moves to a terminal value."
    PRD §3.6: "a `PlatformAdmin` may document an external no-show by creating a strike
    with an `interpreter_id`, an `occurred_at` that must not lie in the future (else
    `ERR_INVALID_REQUEST`), and an optional `assignment_id` left null for external
    events."

    Design: Corner/entities/strike_record_has_no_version_field
    """
    set_clock("2026-05-01T00:00:00Z")
    interp = get_success_data(api_client.create_interpreter(
        create_interpreter_payload(), ADMIN))
    strike = create_manual_strike(interp["id"], "2026-04-01T09:00:00Z")
    assert_strike_record(strike)
    assert strike["status"] == "ACTIVE"
    assert_instant_equal(strike["occurred_at"], "2026-04-01T09:00:00Z", "occurred_at")
    rows = get_success_data(api_client.list_interpreter_strikes(interp["id"], ADMIN))
    assert len(rows) == 1
    assert_strike_record(rows[0])


# ─── Difficulty: resource_temporal_overlap / half-open adjacency ────

def _setup_interpreter_with_morning_window():
    set_clock("2026-05-01T00:00:00Z")
    interp = get_success_data(api_client.create_interpreter(
        create_interpreter_payload(), ADMIN))
    w1 = add_availability(
        interp["id"], "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z")
    return interp, w1


def test_availability_window_touching_endpoint_accepted():
    """PRD §3.2: "Windows are half-open intervals: they cover from `start_at` up to
    but not including `end_at`. A new window that overlaps any existing window of the
    same interpreter is rejected with `ERR_AVAILABILITY_WINDOW_OVERLAP` (HTTP 409),
    though windows whose endpoints merely touch are allowed."

    Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
    """
    interp, _w1 = _setup_interpreter_with_morning_window()
    resp = api_client.create_availability_window(
        interp["id"],
        {"start_at": "2026-06-01T12:00:00Z", "end_at": "2026-06-01T15:00:00Z",
         "modalities": ["ASL_ONSITE"]},
        make_interpreter_headers(interp["id"]),
    )
    data = validate_success(resp, 201)
    assert data["id"], "adjacent window (touching at 12:00) must be accepted"
    rows = get_success_data(api_client.list_availability_windows(interp["id"], ADMIN))
    assert len(rows) == 2


def test_availability_window_one_minute_overlap_rejected():
    """PRD §3.2: "Windows are half-open intervals: they cover from `start_at` up to
    but not including `end_at`. A new window that overlaps any existing window of the
    same interpreter is rejected with `ERR_AVAILABILITY_WINDOW_OVERLAP` (HTTP 409),
    though windows whose endpoints merely touch are allowed."

    Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
    """
    interp, _w1 = _setup_interpreter_with_morning_window()
    # First add the legal adjacent window, then try one minute of real overlap.
    get_success_data(api_client.create_availability_window(
        interp["id"],
        {"start_at": "2026-06-01T12:00:00Z", "end_at": "2026-06-01T15:00:00Z",
         "modalities": ["ASL_ONSITE"]},
        make_interpreter_headers(interp["id"]),
    ))
    resp = api_client.create_availability_window(
        interp["id"],
        {"start_at": "2026-06-01T11:59:00Z", "end_at": "2026-06-01T13:00:00Z",
         "modalities": ["ASL_ONSITE"]},
        make_interpreter_headers(interp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AVAILABILITY_WINDOW_OVERLAP)
    rows = get_success_data(api_client.list_availability_windows(interp["id"], ADMIN))
    assert len(rows) == 2, "the rejected overlapping window must not persist"


def test_offer_without_availability_coverage_returns_error():
    """PRD §3.4: "Coverage comes next: the interpreter's availability windows whose
    `modalities` include the request modality are merged as half-open intervals, and
    their union must fully cover the span from `scheduled_start` up to but not
    including `scheduled_end` — a window ending exactly at the scheduled start does
    not help, while one ending exactly at the scheduled end does cover the tail.
    Any gap rejects the offer with `ERR_NO_AVAILABILITY_COVERAGE` (HTTP 422)."

    Design: Corner/validations/offer_without_availability_coverage_returns_error
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    create_standard_rate_card()
    interp = create_active_interpreter()
    # Partial coverage only: 12:00-15:00 against a 14:00-16:30 engagement.
    add_availability(interp["id"], "2026-06-10T12:00:00Z", "2026-06-10T15:00:00Z")
    req = create_submitted_request(org["id"])
    resp = api_client.create_offer(
        req["id"],
        create_offer_payload(interp["id"], get_request_version(req["id"])),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NO_AVAILABILITY_COVERAGE)
    # Adjacent second window merges to full 12:00-17:00 coverage (touching allowed).
    add_availability(interp["id"], "2026-06-10T15:00:00Z", "2026-06-10T17:00:00Z")
    assignment = offer_to(req["id"], interp["id"])
    assert assignment["status"] == "OFFERED", (
        "with the gap closed the offer succeeds and the assignment is OFFERED"
    )
