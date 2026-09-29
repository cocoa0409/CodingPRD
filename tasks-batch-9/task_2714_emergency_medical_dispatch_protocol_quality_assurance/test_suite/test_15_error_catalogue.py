"""Refusals across the error catalogue of the EMD protocol QA API.

Covers not-found resolution on the action routes, the two uniqueness scopes,
determinant-code shape, programme threshold coherence, inverted time windows,
pagination bounds, the sampling-mode gate, empty aggregate source sets,
protocol-version pinning at selection, certification and go-live state guards,
the clinical record's ordering and cardinality guards, the coaching plan and
retraining session state guards, and the terminality of report filing.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import approx1, approx2, assert_instant_equals
from test_helpers.test_users import ADMIN, DIRECTOR, OFFICER, REVIEWER, SUPERVISOR

WORKING_CLOCK = "2026-08-20T00:00:00Z"
AUGUST_START = "2026-08-01T00:00:00Z"
SEPTEMBER_START = "2026-09-01T00:00:00Z"


# --------------------------------------------------------------- local setups
def _program_with_two_dispatchers(api):
    """A programme carrying exactly two enrolled dispatchers."""
    program = fx.new_program(api)
    fx.new_dispatcher(api, program["id"], employee_code="EMD-001", full_name="Ada Rune")
    fx.new_dispatcher(api, program["id"], employee_code="EMD-002", full_name="Bo Vance")
    return program


def _two_mode_periods(api):
    """One eligible CHEST_PAIN call with a TARGETED and a RANDOM period over it."""
    env = fx.enrolled_dispatcher_env(api, clock=WORKING_CLOCK)
    call = fx.ingest_call(api, env["dispatcher_id"], received_at="2026-08-05T09:00:00Z")
    targeted = fx.new_period(
        api, env["program_id"], sampling_mode="TARGETED", target_sample_count=1
    )
    random_period = fx.new_period(
        api, env["program_id"], sampling_mode="RANDOM", target_sample_count=1
    )
    env.update(
        {
            "call": call,
            "call_id": call["id"],
            "targeted_id": targeted["id"],
            "random_id": random_period["id"],
        }
    )
    return env


def _pending_high_risk_env(api):
    """A confirmed cardiac-arrest review whose clinical record is still PENDING."""
    env = fx.enrolled_dispatcher_env(api, clock=WORKING_CLOCK)
    call = fx.ingest_cardiac_arrest_call(
        api, env["dispatcher_id"], received_at="2026-08-05T09:00:00Z"
    )
    period = fx.new_period(
        api, env["program_id"], call_type="CARDIAC_ARREST", target_sample_count=1
    )
    review = fx.target(api, period["id"], call["id"], "HIGH_RISK_OUTCOME")
    record = fx.new_high_risk_review(api, review["id"], "ROSC_FIELD")
    env.update(
        {
            "call_id": call["id"],
            "period_id": period["id"],
            "review": review,
            "review_id": review["id"],
            "record": record,
            "record_id": record["id"],
        }
    )
    return env


def _verified_plan_env(api):
    """An ADVISORY plan whose single two-hour session has been completed."""
    program = fx.new_program(api, hours_owed_restriction_threshold=6.0)
    curriculum = fx.new_approved_version(
        api, program["id"], protocol_family="LOCAL_CARDSET", version_label="LOCAL-1.0"
    )
    dispatcher = fx.new_dispatcher(api, program["id"])
    fx.set_clock(api, WORKING_CLOCK)
    plan = fx.new_coaching_plan(
        api, dispatcher["id"], severity="ADVISORY", focus_area="DACPR"
    )
    session = fx.new_session(
        api,
        plan["id"],
        curriculum["id"],
        starts_at="2026-08-25T09:00:00Z",
        ends_at="2026-08-25T11:00:00Z",
    )
    fx.set_clock(api, "2026-08-26T00:00:00Z")
    completed = fx.complete_session(api, session["id"])
    return {
        "program_id": program["id"],
        "curriculum_id": curriculum["id"],
        "dispatcher_id": dispatcher["id"],
        "plan_id": plan["id"],
        "session_id": session["id"],
        "completed": completed,
    }


# ------------------------------------------- unknown identifiers on the actions
UNKNOWN_ACTION_ROUTES = [
    pytest.param(
        "close_sampling_period",
        {"closing_note": "closing an unknown period"},
        SUPERVISOR,
        err.ERR_SAMPLING_PERIOD_NOT_FOUND,
        id="close_period",
    ),
    pytest.param(
        "go_live",
        {"golive_note": "cutover on an unknown rollout"},
        ADMIN,
        err.ERR_ROLLOUT_NOT_FOUND,
        id="go_live",
    ),
    pytest.param(
        "sign_off_high_risk_review",
        {"classification": "COACHING_ONLY"},
        DIRECTOR,
        err.ERR_HIGH_RISK_REVIEW_NOT_FOUND,
        id="sign_off",
    ),
    pytest.param(
        "decide_rebuttal",
        {"decision": "REJECTED"},
        SUPERVISOR,
        err.ERR_REBUTTAL_NOT_FOUND,
        id="decide_rebuttal",
    ),
    pytest.param(
        "complete_retraining_session",
        {"attendance_confirmed": True},
        SUPERVISOR,
        err.ERR_SESSION_NOT_FOUND,
        id="complete_session",
    ),
]


@pytest.mark.parametrize("method,payload,headers,expected_error", UNKNOWN_ACTION_ROUTES)
def test_unknown_identifier_on_an_action_route_returns_its_own_not_found(
    api, method, payload, headers, expected_error
):
    """PRD §2.5: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not resolve determines the error:
    `ERR_PROGRAM_NOT_FOUND`, `ERR_PROTOCOL_VERSION_NOT_FOUND`,
    `ERR_ROLLOUT_NOT_FOUND`, `ERR_DISPATCHER_NOT_FOUND`,
    `ERR_SAMPLING_PERIOD_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_REBUTTAL_NOT_FOUND`, `ERR_HIGH_RISK_REVIEW_NOT_FOUND`,
    `ERR_COACHING_PLAN_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, or
    `ERR_REPORT_NOT_FOUND`, each at HTTP 404."
    PRD §2.9: "**Path existence**, left to right, then **body-reference
    existence** — the 404 family."

    Design: Corner/errors/unknown_ids_on_the_action_routes_return_not_found
    """
    response = getattr(api, method)(NON_EXISTENT_UUID, payload, headers)
    validate_error(response, expected_error)


def test_unknown_report_submit_is_not_found_and_writes_nothing(api):
    """PRD §2.5: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not resolve determines the error:
    `ERR_PROGRAM_NOT_FOUND`, `ERR_PROTOCOL_VERSION_NOT_FOUND`,
    `ERR_ROLLOUT_NOT_FOUND`, `ERR_DISPATCHER_NOT_FOUND`,
    `ERR_SAMPLING_PERIOD_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_REBUTTAL_NOT_FOUND`, `ERR_HIGH_RISK_REVIEW_NOT_FOUND`,
    `ERR_COACHING_PLAN_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, or
    `ERR_REPORT_NOT_FOUND`, each at HTTP 404."
    PRD §3.1: "`submitted_report_count` starts at 0 and `sentinel_event_count`
    starts at 0."

    Design: Corner/errors/unknown_ids_on_the_action_routes_return_not_found
    """
    program = fx.new_program(api)

    response = api.submit_accreditation_report(
        NON_EXISTENT_UUID, {"submitted_to": "MEDICAL_DIRECTOR"}, OFFICER
    )
    validate_error(response, err.ERR_REPORT_NOT_FOUND)

    reread = fx.get_program(api, program["id"])
    assert reread["submitted_report_count"] == 0, (
        "a submit against an unknown report must write nothing"
    )
    assert reread["accreditation_status"] == "SETUP"


# ------------------------------------------------------------------ uniqueness
def test_duplicate_employee_code_within_one_programme_is_rejected(api):
    """PRD §3.1: "The employee code must be unique within its programme, and a
    collision is rejected with `ERR_DUPLICATE_EMPLOYEE_CODE`."

    Design: Corner/errors/duplicate_employee_code_and_call_reference_are_rejected
    """
    program = fx.new_program(api)
    fx.new_dispatcher(api, program["id"], employee_code="EMD-001", full_name="Ada Rune")

    response = api.create_dispatcher(
        f.dispatcher_payload(program["id"], employee_code="EMD-001", full_name="Bo Vance"),
        ADMIN,
    )
    validate_error(response, err.ERR_DUPLICATE_EMPLOYEE_CODE)

    rows, meta = validate_paginated(
        api.list_dispatchers(SUPERVISOR, {"program_id": program["id"], "limit": 100})
    )
    assert meta["total_count"] == 1, "the refused enrollment must not have been written"


def test_same_employee_code_is_accepted_in_a_second_programme(api):
    """PRD §3.1: "The employee code must be unique within its programme, and a
    collision is rejected with `ERR_DUPLICATE_EMPLOYEE_CODE`."

    Design: Corner/errors/duplicate_employee_code_and_call_reference_are_rejected
    """
    program_a = fx.new_program(api)
    program_b = fx.new_program(api)
    fx.new_dispatcher(api, program_a["id"], employee_code="EMD-001", full_name="Ada Rune")

    response = api.create_dispatcher(
        f.dispatcher_payload(program_b["id"], employee_code="EMD-001", full_name="Bo Vance"),
        ADMIN,
    )
    created = validate_success(response, 201)
    assert created["employee_code"] == "EMD-001"
    assert created["program_id"] == program_b["id"]


def test_call_reference_collides_across_programmes_and_dispatchers(api):
    """PRD §3.1: "Ingestion carries a `call_reference` — the CAD incident
    reference, which must be globally unique across the whole service and which
    doubles as the deterministic tie-break key when samples are drawn; a repeat
    is rejected with `ERR_DUPLICATE_CALL_REFERENCE`."

    Design: Corner/errors/duplicate_employee_code_and_call_reference_are_rejected
    """
    program_a = fx.new_program(api)
    program_b = fx.new_program(api)
    dispatcher_a = fx.new_dispatcher(api, program_a["id"], employee_code="EMD-001")
    dispatcher_b = fx.new_dispatcher(api, program_b["id"], employee_code="EMD-001")
    fx.set_clock(api, WORKING_CLOCK)
    fx.ingest_call(
        api,
        dispatcher_a["id"],
        call_reference="C-0001",
        call_type="CHEST_PAIN",
        received_at="2026-08-05T09:00:00Z",
        dispatched_determinant_code="10-C-4",
    )

    response = api.create_call_record(
        dispatcher_b["id"],
        f.call_record_payload(
            call_reference="C-0001",
            call_type="TRAUMA",
            received_at="2026-08-06T09:00:00Z",
            dispatched_determinant_code="30-B-1",
        ),
        ADMIN,
    )
    validate_error(response, err.ERR_DUPLICATE_CALL_REFERENCE)

    rows, meta = validate_paginated(
        api.list_call_records(dispatcher_b["id"], ADMIN, {"limit": 100})
    )
    assert meta["total_count"] == 0, "the duplicated reference must not have been ingested"


# ------------------------------------------------------- determinant code shape
@pytest.mark.parametrize(
    "bad_code",
    [
        pytest.param("10C4", id="no_separators"),
        pytest.param("10-F-4", id="level_letter_outside_the_set"),
    ],
)
def test_malformed_dispatched_determinant_code_is_rejected(api, bad_code):
    """PRD §2.10: "Structurally, a valid code is one or two decimal digits, then
    a hyphen, then exactly one uppercase letter drawn from `O`, `A`, `B`, `C`,
    `D`, `E`, then a hyphen, then one or two decimal digits, with nothing before
    or after."
    PRD §2.10: "A two-part code, a lowercase level letter, a level letter
    outside that set, or a three-digit component is invalid, and any endpoint
    that accepts a code rejects it with `ERR_INVALID_DETERMINANT_CODE` (HTTP
    422)."

    Design: Corner/errors/malformed_determinant_codes_are_rejected
    """
    program = fx.new_program(api)
    dispatcher = fx.new_dispatcher(api, program["id"])
    fx.set_clock(api, WORKING_CLOCK)

    response = api.create_call_record(
        dispatcher["id"],
        f.call_record_payload(
            call_reference="C-0002",
            call_type="CHEST_PAIN",
            received_at="2026-08-06T09:00:00Z",
            dispatched_determinant_code=bad_code,
        ),
        ADMIN,
    )
    validate_error(response, err.ERR_INVALID_DETERMINANT_CODE)

    rows, meta = validate_paginated(
        api.list_call_records(dispatcher["id"], ADMIN, {"limit": 100})
    )
    assert meta["total_count"] == 0, "a malformed code must not produce a call record"


def test_malformed_reviewer_determinant_code_is_rejected_at_scoring(api):
    """PRD §2.10: "A two-part code, a lowercase level letter, a level letter
    outside that set, or a three-digit component is invalid, and any endpoint
    that accepts a code rejects it with `ERR_INVALID_DETERMINANT_CODE` (HTTP
    422)."
    PRD §2.10: "Two endpoints accept codes: call ingestion, which takes
    `dispatched_determinant_code`, and score-sheet submission, which takes
    `reviewer_determinant_code`."

    Design: Corner/errors/malformed_determinant_codes_are_rejected
    """
    env = fx.selected_review_env(api)
    review_version = env["review"]["version"]

    response = api.submit_scores(
        env["review_id"],
        f.score_payload(review_version, reviewer_determinant_code="10-C-100"),
        REVIEWER,
    )
    validate_error(response, err.ERR_INVALID_DETERMINANT_CODE)

    sheets, sheet_meta = validate_paginated(
        api.list_score_sheets(env["review_id"], SUPERVISOR, {"limit": 100})
    )
    assert sheet_meta["total_count"] == 0, "the refused sheet must not be appended"
    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "SELECTED"
    assert review["version"] == review_version, "a refused score must not bump the version"


def test_shortest_legal_determinant_code_is_accepted_and_decoded(api):
    """PRD §2.10: "The letter maps to a numeric priority rank ordering codes by
    clinical acuity: `O` is rank 1, `A` is rank 2, `B` is rank 3, `C` is rank 4,
    `D` is rank 5, and `E` — the ECHO level, the most acute — is rank 6."
    PRD §2.10: "The response mode is `HOT` when the level letter is `D` or `E`,
    and `COLD` for every other letter."

    Design: Corner/errors/malformed_determinant_codes_are_rejected
    """
    program = fx.new_program(api)
    dispatcher = fx.new_dispatcher(api, program["id"])
    fx.set_clock(api, WORKING_CLOCK)

    response = api.create_call_record(
        dispatcher["id"],
        f.call_record_payload(
            call_reference="C-0001",
            call_type="CHEST_PAIN",
            received_at="2026-08-05T09:00:00Z",
            dispatched_determinant_code="9-O-1",
        ),
        ADMIN,
    )
    call = validate_success(response, 201)
    assert call["dispatched_priority_rank"] == 1
    assert call["response_mode_assigned"] == "COLD"


# --------------------------------------------------- programme threshold ranges
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"target_compliance_pct": 90.0, "watch_floor_pct": 90.0},
            id="watch_floor_equal_to_target",
        ),
        pytest.param(
            {"target_compliance_pct": 100.1, "watch_floor_pct": 80.0},
            id="target_above_one_hundred",
        ),
        pytest.param({"high_risk_target_pct": 0.0}, id="zero_high_risk_target"),
    ],
)
def test_incoherent_threshold_configuration_is_rejected(api, overrides):
    """PRD §3.1: "The three must be mutually coherent: `watch_floor_pct` must be
    greater than 0.0 and strictly less than `target_compliance_pct`,
    `target_compliance_pct` must not exceed 100.0, and `high_risk_target_pct`
    must be greater than 0.0 and not exceed 100.0. A configuration that violates
    any of those relations is rejected with `ERR_INVALID_THRESHOLD_CONFIG`."

    Design: Corner/errors/threshold_configuration_outside_its_range_is_rejected
    """
    response = api.create_audit_program(f.audit_program_payload(**overrides), ADMIN)
    validate_error(response, err.ERR_INVALID_THRESHOLD_CONFIG)


def test_target_compliance_of_exactly_one_hundred_is_accepted(api):
    """PRD §3.1: "The three must be mutually coherent: `watch_floor_pct` must be
    greater than 0.0 and strictly less than `target_compliance_pct`,
    `target_compliance_pct` must not exceed 100.0, and `high_risk_target_pct`
    must be greater than 0.0 and not exceed 100.0. A configuration that violates
    any of those relations is rejected with `ERR_INVALID_THRESHOLD_CONFIG`."
    PRD §3.1: "`accreditation_status` reads `SETUP` from the moment the
    programme is created and stays there until the first accreditation report is
    filed, after which it is either `ACCREDITED` or `AT_RISK`."

    Design: Corner/errors/threshold_configuration_outside_its_range_is_rejected
    """
    response = api.create_audit_program(
        f.audit_program_payload(
            target_compliance_pct=100.0, watch_floor_pct=99.9, high_risk_target_pct=100.0
        ),
        ADMIN,
    )
    program = validate_success(response, 201)

    reread = fx.get_program(api, program["id"])
    assert reread["target_compliance_pct"] == approx1(100.0)
    assert reread["watch_floor_pct"] == approx1(99.9)
    assert reread["high_risk_target_pct"] == approx1(100.0)
    assert reread["accreditation_status"] == "SETUP"


# ------------------------------------------------- inverted / zero-length windows
def test_protocol_version_effective_to_equal_to_effective_from_is_rejected(api):
    """PRD §3.2: "An `effective_to` that is not strictly after `effective_from`
    is rejected with `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/errors/inverted_and_zero_length_windows_are_rejected
    """
    program = fx.new_program(api)

    response = api.create_protocol_version(
        program["id"],
        f.protocol_version_payload(
            protocol_family="LOCAL_CARDSET",
            version_label="LOCAL-1.0",
            effective_from=SEPTEMBER_START,
            effective_to=SEPTEMBER_START,
        ),
        ADMIN,
    )
    validate_error(response, err.ERR_INVALID_TIME_WINDOW)

    rows, meta = validate_paginated(
        api.list_protocol_versions(program["id"], ADMIN, {"limit": 100})
    )
    assert meta["total_count"] == 0, "the refused version must not have been registered"


def test_sampling_period_end_before_its_start_is_rejected(api):
    """PRD §3.4: "the window is half-open, so a call answered exactly at
    `period_start` is inside it and a call answered exactly at `period_end` is
    not, and a `period_end` that is not strictly after `period_start` is rejected
    with `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/errors/inverted_and_zero_length_windows_are_rejected
    """
    program = fx.new_program(api)

    response = api.create_sampling_period(
        program["id"],
        f.sampling_period_payload(
            period_start=SEPTEMBER_START, period_end=AUGUST_START
        ),
        SUPERVISOR,
    )
    validate_error(response, err.ERR_INVALID_TIME_WINDOW)

    rows, meta = validate_paginated(
        api.list_sampling_periods(program["id"], SUPERVISOR, {"limit": 100})
    )
    assert meta["total_count"] == 0, "the refused period must not have been opened"


def test_retraining_session_ends_at_equal_to_starts_at_is_rejected(api):
    """PRD §3.8: "A `QaSupervisor` schedules a retraining session against a plan,
    supplying the `protocol_version_id` of the curriculum to be taught, a
    `starts_at`, an `ends_at` that must be strictly after it (otherwise
    `ERR_INVALID_TIME_WINDOW`), and a `modality` of `CLASSROOM`, `SIMULATION`,
    `ONLINE`, or `ONE_ON_ONE`."

    Design: Corner/errors/inverted_and_zero_length_windows_are_rejected
    """
    env = fx.enrolled_dispatcher_env(api, clock=WORKING_CLOCK)
    plan = fx.new_coaching_plan(
        api, env["dispatcher_id"], severity="ADVISORY", focus_area="CASE_ENTRY"
    )

    response = api.create_retraining_session(
        plan["id"],
        f.retraining_session_payload(
            env["version_id"],
            starts_at="2026-08-25T09:00:00Z",
            ends_at="2026-08-25T09:00:00Z",
        ),
        SUPERVISOR,
    )
    validate_error(response, err.ERR_INVALID_TIME_WINDOW)

    reread = fx.get_plan(api, plan["id"])
    assert reread["status"] == "ASSIGNED", "the refused session must not open the plan"
    assert reread["credited_hours"] == approx2(0.00)
    sessions, session_meta = validate_paginated(
        api.list_retraining_sessions(plan["id"], SUPERVISOR, {"limit": 100})
    )
    assert session_meta["total_count"] == 0


def test_report_window_end_equal_to_window_start_uses_its_own_error(api):
    """PRD §3.9: "A report is built as a draft over a finalization window:
    `window_start` is the inclusive lower bound and `window_end` the exclusive
    upper bound on the review's `finalized_at`, and a `window_end` that is not
    strictly after `window_start` is refused with `ERR_REPORT_WINDOW_INVALID`."

    Design: Corner/errors/inverted_and_zero_length_windows_are_rejected
    """
    program = fx.new_program(api)

    response = api.create_accreditation_report(
        program["id"],
        f.accreditation_report_payload(
            window_start=SEPTEMBER_START, window_end=SEPTEMBER_START
        ),
        OFFICER,
    )
    validate_error(response, err.ERR_REPORT_WINDOW_INVALID)


# ------------------------------------------------------------ pagination bounds
@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"limit": 0}, id="limit_below_one"),
        pytest.param({"limit": 101}, id="limit_above_one_hundred"),
        pytest.param({"limit": 10, "offset": -1}, id="negative_offset"),
    ],
)
def test_pagination_arguments_outside_the_allowed_range_are_rejected(api, params):
    """PRD §2.3: "`limit` caps the number of items returned; when omitted it
    defaults to 10, its minimum accepted value is 1 and its maximum accepted
    value is 100."
    PRD §2.3: "A supplied `limit` that is not an integer, is below 1 or above
    100, or a supplied `offset` that is not an integer or is negative, is
    rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/errors/pagination_arguments_outside_the_allowed_range_are_rejected
    """
    program = _program_with_two_dispatchers(api)
    query = {"program_id": program["id"]}
    query.update(params)

    response = api.list_dispatchers(SUPERVISOR, query)
    validate_error(response, err.ERR_INVALID_PAGINATION)


def test_maximum_limit_with_an_offset_past_the_end_returns_an_empty_page(api):
    """PRD §2.3: "`limit` caps the number of items returned; when omitted it
    defaults to 10, its minimum accepted value is 1 and its maximum accepted
    value is 100."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is
    the number of rows matching the filters before the page window is applied
    and `has_more` indicates whether rows remain beyond it."

    Design: Corner/errors/pagination_arguments_outside_the_allowed_range_are_rejected
    """
    program = _program_with_two_dispatchers(api)

    rows, meta = validate_paginated(
        api.list_dispatchers(SUPERVISOR, {"program_id": program["id"], "limit": 100, "offset": 50})
    )
    assert rows == [], "an offset past the end yields an empty page, not an error"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 100
    assert meta["offset"] == 50


# ----------------------------------------------------------- sampling-mode gate
def test_random_draw_against_a_targeted_only_period_is_rejected(api):
    """PRD §3.4: "The period's `sampling_mode` decides which of the two selection
    routes it will accept: `RANDOM` accepts only the systematic random draw,
    `TARGETED` accepts only the case-by-case targeted selection, and `MIXED`
    accepts both. Attempting the wrong route for the mode — a random draw against
    a targeted-only period, or a targeted selection against a random-only period
    — is refused with `ERR_SAMPLING_MODE_MISMATCH`."

    Design: Corner/errors/sampling_mode_mismatch_in_both_directions_is_rejected
    """
    env = _two_mode_periods(api)

    response = api.draw_random_sample(env["targeted_id"], {"requested_count": 1}, SUPERVISOR)
    validate_error(response, err.ERR_SAMPLING_MODE_MISMATCH)

    reviews, meta = validate_paginated(
        api.list_reviews(SUPERVISOR, {"sampling_period_id": env["targeted_id"], "limit": 100})
    )
    assert meta["total_count"] == 0, "the eligible call must not have been drawn"


def test_targeted_selection_against_a_random_only_period_is_rejected(api):
    """PRD §3.4: "The period's `sampling_mode` decides which of the two selection
    routes it will accept: `RANDOM` accepts only the systematic random draw,
    `TARGETED` accepts only the case-by-case targeted selection, and `MIXED`
    accepts both. Attempting the wrong route for the mode — a random draw against
    a targeted-only period, or a targeted selection against a random-only period
    — is refused with `ERR_SAMPLING_MODE_MISMATCH`."

    Design: Corner/errors/sampling_mode_mismatch_in_both_directions_is_rejected
    """
    env = _two_mode_periods(api)

    response = api.target_review(
        env["random_id"], f.target_review_payload(env["call_id"]), SUPERVISOR
    )
    validate_error(response, err.ERR_SAMPLING_MODE_MISMATCH)

    reviews, meta = validate_paginated(
        api.list_reviews(SUPERVISOR, {"sampling_period_id": env["random_id"], "limit": 100})
    )
    assert meta["total_count"] == 0


def test_targeted_selection_against_a_targeted_period_is_accepted(api):
    """PRD §3.4: "The period's `sampling_mode` decides which of the two selection
    routes it will accept: `RANDOM` accepts only the systematic random draw,
    `TARGETED` accepts only the case-by-case targeted selection, and `MIXED`
    accepts both."
    PRD §3.4: "A successful targeted selection creates one review with
    `selection_mode` of `TARGETED`, moves the call to `SELECTED`, and increments
    the period's `selected_review_count` by one."

    Design: Corner/errors/sampling_mode_mismatch_in_both_directions_is_rejected
    """
    env = _two_mode_periods(api)

    response = api.target_review(
        env["targeted_id"], f.target_review_payload(env["call_id"]), SUPERVISOR
    )
    review = validate_success(response, 201)
    assert review["status"] == "SELECTED"
    assert review["selection_mode"] == "TARGETED"


# -------------------------------------------------- empty aggregate source sets
def test_random_draw_against_an_empty_candidate_pool_is_rejected(api):
    """PRD §3.4: "If that pool is empty, the draw is refused with
    `ERR_NO_ELIGIBLE_CALLS`."

    Design: Corner/errors/an_empty_pool_and_a_window_without_finalized_reviews_are_rejected
    """
    env = fx.program_with_version(api, clock="2026-09-05T00:00:00Z")
    fx.new_dispatcher(api, env["program_id"])
    period = fx.new_period(
        api, env["program_id"], sampling_mode="RANDOM", target_sample_count=2
    )

    response = api.draw_random_sample(period["id"], {"requested_count": 2}, SUPERVISOR)
    validate_error(response, err.ERR_NO_ELIGIBLE_CALLS)

    reread = fx.get_period(api, env["program_id"], period["id"])
    assert reread["status"] == "OPEN"
    assert reread["selected_review_count"] == 0


def test_report_over_a_window_without_finalized_reviews_is_rejected(api):
    """PRD §3.9: "If the pool is empty the report is refused outright with
    `ERR_NO_FINALIZED_REVIEWS_IN_WINDOW` — the system will not file an empty
    attestation."

    Design: Corner/errors/an_empty_pool_and_a_window_without_finalized_reviews_are_rejected
    """
    env = fx.program_with_version(api, clock="2026-09-05T00:00:00Z")
    fx.new_dispatcher(api, env["program_id"])

    response = api.create_accreditation_report(
        env["program_id"],
        f.accreditation_report_payload(
            window_start=AUGUST_START, window_end=SEPTEMBER_START
        ),
        OFFICER,
    )
    validate_error(response, err.ERR_NO_FINALIZED_REVIEWS_IN_WINDOW)

    reports, meta = validate_paginated(
        api.list_accreditation_reports(env["program_id"], OFFICER, {"limit": 100})
    )
    assert meta["total_count"] == 0
    program = fx.get_program(api, env["program_id"])
    assert program["latest_compliance_pct"] is None
    assert program["accreditation_status"] == "SETUP"


# ------------------------------------------ no protocol version in force at all
def test_selecting_a_call_before_every_effective_window_is_rejected(api):
    """PRD §3.4: "Each new review resolves `protocol_version_id` by searching the
    `MPDS_CARDSET` family of the period's programme for the single version whose
    `status` is `APPROVED`, `ACTIVE` or `SUPERSEDED` and whose governing interval
    contains the call's `received_at` — `effective_from` at or before the instant
    and `effective_to` either null or strictly after it."
    PRD §3.4: "the search either finds exactly one row or none; when it finds
    none, the whole selection is refused with `ERR_NO_PROTOCOL_VERSION_IN_FORCE`."

    Design: Corner/errors/selecting_a_call_with_no_version_in_force_is_rejected
    """
    program = fx.new_program(api)
    fx.new_approved_version(api, program["id"], effective_from="2026-08-10T00:00:00Z")
    dispatcher = fx.new_dispatcher(api, program["id"])
    fx.set_clock(api, WORKING_CLOCK)
    early = fx.ingest_call(
        api, dispatcher["id"], call_reference="C-0001", received_at="2026-08-05T09:00:00Z"
    )
    period = fx.new_period(api, program["id"], target_sample_count=2)

    response = api.target_review(
        period["id"], f.target_review_payload(early["id"]), SUPERVISOR
    )
    validate_error(response, err.ERR_NO_PROTOCOL_VERSION_IN_FORCE)

    calls, _ = validate_paginated(
        api.list_call_records(dispatcher["id"], ADMIN, {"limit": 100})
    )
    assert calls[0]["status"] == "INGESTED", "a refused selection leaves the call ingested"
    reread = fx.get_period(api, program["id"], period["id"])
    assert reread["selected_review_count"] == 0, "the refused selection consumed no quota"


def test_selecting_a_call_inside_the_effective_window_pins_that_version(api):
    """PRD §3.4: "Each new review resolves `protocol_version_id` by searching the
    `MPDS_CARDSET` family of the period's programme for the single version whose
    `status` is `APPROVED`, `ACTIVE` or `SUPERSEDED` and whose governing interval
    contains the call's `received_at` — `effective_from` at or before the instant
    and `effective_to` either null or strictly after it."

    Design: Corner/errors/selecting_a_call_with_no_version_in_force_is_rejected
    """
    program = fx.new_program(api)
    version = fx.new_approved_version(
        api, program["id"], effective_from="2026-08-10T00:00:00Z"
    )
    dispatcher = fx.new_dispatcher(api, program["id"])
    fx.set_clock(api, WORKING_CLOCK)
    early = fx.ingest_call(
        api, dispatcher["id"], call_reference="C-0001", received_at="2026-08-05T09:00:00Z"
    )
    late = fx.ingest_call(
        api, dispatcher["id"], call_reference="C-0002", received_at="2026-08-12T09:00:00Z"
    )
    period = fx.new_period(api, program["id"], target_sample_count=2)

    response = api.target_review(
        period["id"], f.target_review_payload(late["id"]), SUPERVISOR
    )
    review = validate_success(response, 201)
    assert review["protocol_version_id"] == version["id"]

    calls, _ = validate_paginated(
        api.list_call_records(dispatcher["id"], ADMIN, {"limit": 100})
    )
    by_id = {row["id"]: row for row in calls}
    assert by_id[early["id"]]["status"] == "INGESTED"
    assert by_id[late["id"]]["status"] == "SELECTED"
    reread = fx.get_period(api, program["id"], period["id"])
    assert reread["selected_review_count"] == 1


# ------------------------------------------- certification and go-live guards
def _live_rollout_with_draft_successor(api):
    """An ACTIVE version whose rollout is already LIVE, plus a DRAFT successor."""
    program = fx.new_program(api)
    v1 = fx.new_version(
        api,
        program["id"],
        version_label="MPDS-13.0",
        effective_from="2026-07-01T00:00:00Z",
        effective_to=SEPTEMBER_START,
    )
    fx.approve_version(api, v1["id"])
    draft = fx.new_version(
        api, program["id"], version_label="MPDS-14.0", effective_from=SEPTEMBER_START
    )
    dispatcher = fx.new_dispatcher(api, program["id"])
    rollout = fx.new_rollout(
        api, v1["id"], scheduled_golive_at="2026-08-15T00:00:00Z", target_dispatcher_count=1
    )
    fx.set_clock(api, WORKING_CLOCK)
    fx.certify(api, dispatcher["id"], v1["id"])
    live = fx.go_live(api, rollout["id"], "cutover complete")
    return {
        "program_id": program["id"],
        "v1_id": v1["id"],
        "draft_id": draft["id"],
        "dispatcher_id": dispatcher["id"],
        "rollout_id": rollout["id"],
        "live": live,
    }


def test_certifying_a_dispatcher_on_a_draft_version_is_rejected(api):
    """PRD §3.3: "The target version's `status` must be `APPROVED` or `ACTIVE`, and
    a draft or superseded version is refused with `ERR_VERSION_NOT_CERTIFIABLE`;
    the version must also belong to the dispatcher's own programme, or the request
    is refused for programme scope."

    Design: Corner/errors/certifying_on_a_draft_version_and_a_second_go_live_are_rejected
    """
    env = _live_rollout_with_draft_successor(api)

    response = api.certify_dispatcher(
        env["dispatcher_id"], {"protocol_version_id": env["draft_id"]}, ADMIN
    )
    validate_error(response, err.ERR_VERSION_NOT_CERTIFIABLE)

    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["certification_status"] == "CERTIFIED"
    assert dispatcher["certified_protocol_version_id"] == env["v1_id"], (
        "the refused certification must leave the earlier certification intact"
    )
    assert fx.get_version(api, env["draft_id"])["status"] == "DRAFT"


def test_second_go_live_on_an_already_live_rollout_is_rejected(api):
    """PRD §3.3: "The rollout's `golive_status` must still be `SCHEDULED` and its
    version must still be `APPROVED`, or the request is refused with
    `ERR_ROLLOUT_NOT_LIVEABLE`."

    Design: Corner/errors/certifying_on_a_draft_version_and_a_second_go_live_are_rejected
    """
    env = _live_rollout_with_draft_successor(api)
    assert env["live"]["golive_status"] == "LIVE"

    response = api.go_live(env["rollout_id"], {"golive_note": "second attempt"}, ADMIN)
    validate_error(response, err.ERR_ROLLOUT_NOT_LIVEABLE)

    rollout = fx.get_rollout(api, env["v1_id"], env["rollout_id"])
    assert rollout["golive_status"] == "LIVE"
    assert_instant_equals(rollout["went_live_at"], WORKING_CLOCK)
    assert fx.get_version(api, env["v1_id"])["status"] == "ACTIVE"


# ------------------------------------ high-risk clinical record ordering guards
def test_signing_off_a_pending_clinical_record_is_rejected(api):
    """PRD §3.6: "Sign-off belongs exclusively to the `MedicalDirector`, is
    permitted only while the record is in `DACPR_SCORED` — otherwise it is refused
    with `ERR_HRCR_NOT_SIGNABLE` — and carries a `classification` of either
    `SENTINEL_EVENT` or `COACHING_ONLY` plus optional `director_notes`."
    PRD §3.6: "Whichever branch is taken, the record's `classification`,
    `signed_off_by_user_id` and `signed_off_at` are written."

    Design: Corner/errors/high_risk_actions_out_of_state_are_rejected
    """
    env = _pending_high_risk_env(api)
    assert env["record"]["status"] == "PENDING"

    response = api.sign_off_high_risk_review(
        env["record_id"], f.sign_off_payload("COACHING_ONLY"), DIRECTOR
    )
    validate_error(response, err.ERR_HRCR_NOT_SIGNABLE)

    record = fx.get_high_risk_review(api, env["review_id"], env["record_id"])
    assert record["status"] == "PENDING"
    assert record["signed_off_by_user_id"] is None
    assert record["classification"] is None


def test_a_second_clinical_record_on_one_review_is_rejected(api):
    """PRD §3.6: "The record is linked by `review_id`, and at most one such record
    may exist per review; a second attempt is refused with
    `ERR_DUPLICATE_HIGH_RISK_REVIEW`."

    Design: Corner/errors/high_risk_actions_out_of_state_are_rejected
    """
    env = _pending_high_risk_env(api)

    response = api.create_high_risk_review(
        env["review_id"], f.high_risk_review_payload(outcome_category="NO_ROSC"), REVIEWER
    )
    validate_error(response, err.ERR_DUPLICATE_HIGH_RISK_REVIEW)

    records, meta = validate_paginated(
        api.list_high_risk_reviews(env["review_id"], REVIEWER, {"limit": 100})
    )
    assert meta["total_count"] == 1
    assert records[0]["outcome_category"] == "ROSC_FIELD", (
        "the refused duplicate must not overwrite the first record"
    )


def test_scoring_an_already_scored_clinical_record_is_rejected(api):
    """PRD §3.6: "Grading the resuscitation performance is a second `QaReviewer`
    step, permitted only while the record is `PENDING` — otherwise it is refused
    with `ERR_HRCR_NOT_SCORABLE` — and only while the parent review is in
    `SELECTED` or `SCORED`."

    Design: Corner/errors/high_risk_actions_out_of_state_are_rejected
    """
    env = _pending_high_risk_env(api)
    scored = fx.score_dacpr(
        api, env["record_id"], recognition_time_sec=40, time_to_first_compression_sec=100
    )
    assert scored["status"] == "DACPR_SCORED"
    assert scored["version"] == env["record"]["version"] + 1

    response = api.score_dacpr(
        env["record_id"],
        f.dacpr_payload(recognition_time_sec=5, time_to_first_compression_sec=20),
        REVIEWER,
    )
    validate_error(response, err.ERR_HRCR_NOT_SCORABLE)

    record = fx.get_high_risk_review(api, env["review_id"], env["record_id"])
    assert record["status"] == "DACPR_SCORED"
    assert record["recognition_time_sec"] == 40, "the refused rescore must not overwrite"
    assert record["time_to_first_compression_sec"] == 100
    assert record["version"] == scored["version"]


# ------------------------------ coaching plan and retraining session state guards
def test_scheduling_against_a_verified_plan_is_rejected(api):
    """PRD §3.8: "The plan itself must be open: scheduling against a plan in
    `VERIFIED`, `SUSPENDED` or `CANCELLED` is refused with `ERR_PLAN_NOT_OPEN`."

    Design: Corner/errors/coaching_plan_and_session_state_guards_are_rejected
    """
    env = _verified_plan_env(api)
    assert fx.get_plan(api, env["plan_id"])["status"] == "VERIFIED"

    response = api.create_retraining_session(
        env["plan_id"],
        f.retraining_session_payload(
            env["curriculum_id"],
            starts_at="2026-09-01T09:00:00Z",
            ends_at="2026-09-01T11:00:00Z",
            modality="ONLINE",
        ),
        SUPERVISOR,
    )
    validate_error(response, err.ERR_PLAN_NOT_OPEN)

    sessions, meta = validate_paginated(
        api.list_retraining_sessions(env["plan_id"], SUPERVISOR, {"limit": 100})
    )
    assert meta["total_count"] == 1, "the refused schedule must not create a session"


def test_cancelling_a_completed_session_returns_the_plan_to_in_progress(api):
    """PRD §3.8: "A session in `SCHEDULED` may be cancelled, in which case
    `credited_hours` never changed and no ledger moves at all; a session already
    in `COMPLETED` may also be cancelled, which is a genuine compensating action:
    `completed_at` is cleared to null and `credited_hours` is recomputed over the
    remaining completed sessions, returning it to exactly its pre-completion
    value."
    PRD §3.8: "If that drops `credited_hours` back below `required_hours` on a
    plan that had reached `VERIFIED`, the plan cycles `VERIFIED → IN_PROGRESS` and
    its `verified_at` is cleared to null."
    PRD §3.8: "For each open plan the shortfall is the plan's `required_hours`
    less its `credited_hours`, floored at 0.00 so that over-delivery on one plan
    can never offset another plan's shortfall; `remediation_hours_owed` is the sum
    of those per-plan shortfalls, rounded half up to 2 decimal places."

    Design: Corner/errors/coaching_plan_and_session_state_guards_are_rejected
    """
    env = _verified_plan_env(api)

    cancelled = get_success_data(
        api.cancel_retraining_session(
            env["session_id"], {"cancel_reason": "trainer unavailable"}, SUPERVISOR
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["completed_at"] is None

    plan = fx.get_plan(api, env["plan_id"])
    assert plan["status"] == "IN_PROGRESS"
    assert plan["credited_hours"] == approx2(0.00)
    assert plan["verified_at"] is None
    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["remediation_hours_owed"] == approx2(2.00)
    assert dispatcher["dispatch_privilege"] == "FULL"


def test_completing_a_cancelled_session_is_rejected(api):
    """PRD §3.8: "The session must still be in `SCHEDULED`, or the request is
    refused with `ERR_SESSION_NOT_COMPLETABLE`; its plan must be in `ASSIGNED` or
    `IN_PROGRESS`; and the logical clock must be at or after the session's
    `ends_at`, since a class that has not finished cannot be attested."

    Design: Corner/errors/coaching_plan_and_session_state_guards_are_rejected
    """
    env = _verified_plan_env(api)
    fx.cancel_session(api, env["session_id"], "trainer unavailable")
    assert fx.get_plan(api, env["plan_id"])["status"] == "IN_PROGRESS", (
        "the plan is open again, so only the session's own state can refuse this"
    )

    response = api.complete_retraining_session(
        env["session_id"], {"attendance_confirmed": True}, SUPERVISOR
    )
    validate_error(response, err.ERR_SESSION_NOT_COMPLETABLE)

    session = fx.get_session(api, env["plan_id"], env["session_id"])
    assert session["status"] == "CANCELLED"
    assert session["completed_at"] is None
    plan = fx.get_plan(api, env["plan_id"])
    assert plan["credited_hours"] == approx2(0.00)
    assert plan["status"] == "IN_PROGRESS"


def test_cancelling_an_already_cancelled_session_is_rejected(api):
    """PRD §3.8: "Cancelling a session already in `CANCELLED` is refused with
    `ERR_SESSION_NOT_CANCELLABLE`."

    Design: Corner/errors/coaching_plan_and_session_state_guards_are_rejected
    """
    env = _verified_plan_env(api)
    fx.cancel_session(api, env["session_id"], "trainer unavailable")

    response = api.cancel_retraining_session(
        env["session_id"], {"cancel_reason": "cancelled twice by mistake"}, SUPERVISOR
    )
    validate_error(response, err.ERR_SESSION_NOT_CANCELLABLE)

    session = fx.get_session(api, env["plan_id"], env["session_id"])
    assert session["status"] == "CANCELLED"
    plan = fx.get_plan(api, env["plan_id"])
    assert plan["credited_hours"] == approx2(0.00)
    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["remediation_hours_owed"] == approx2(2.00)


# ------------------------------ a manual plan colliding with an automatic key
def test_manual_plan_on_a_review_that_already_has_an_automatic_plan_is_rejected(api):
    """PRD §3.8: "One collision is refused rather than absorbed: if a
    `source_review_id` is supplied and an automatic plan already exists on that
    same dispatcher-and-review pairing, the create is refused with
    `ERR_DUPLICATE_COACHING_PLAN`."
    PRD §3.8: "The automatic path is an **upsert keyed on the pairing of
    `dispatcher_id` and `source_review_id`**, and at most one automatic plan
    exists per such pairing."

    Design: Corner/errors/a_manual_plan_colliding_with_an_auto_plan_key_is_rejected
    """
    env = fx.scored_review_env(
        api,
        sections={
            "case_entry": (18, 20),
            "key_questions": (26, 30),
            "pre_arrival": (2, 3),
            "final_coding": (5, 7),
        },
        reviewer_determinant_code="10-C-2",
        program_overrides={
            "target_compliance_pct": 90.0,
            "watch_floor_pct": 80.0,
            "hours_owed_restriction_threshold": 6.0,
        },
    )
    finalized = fx.finalize(api, env["review_id"], "minor miscode, weak pre-arrival")
    assert finalized["final_composite_score"] == approx1(77.1)
    dispatcher_before = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher_before["compliance_posture"] == "PROBATION"

    response = api.create_coaching_plan(
        f.coaching_plan_payload(
            env["dispatcher_id"],
            dispatcher_before["version"],
            severity="CRITICAL",
            focus_area="DACPR",
            source_review_id=env["review_id"],
        ),
        SUPERVISOR,
    )
    validate_error(response, err.ERR_DUPLICATE_COACHING_PLAN)

    plans, meta = validate_paginated(
        api.list_coaching_plans(
            SUPERVISOR, {"dispatcher_id": env["dispatcher_id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, "the refused manual create must add no plan"
    plan = plans[0]
    assert plan["origin"] == "AUTO"
    assert plan["status"] == "ASSIGNED", "the automatic plan must not be superseded"
    assert plan["severity"] == "STANDARD"
    assert plan["focus_area"] == "PRE_ARRIVAL_INSTRUCTIONS"
    assert plan["required_hours"] == approx1(4.0)
    assert plan["credited_hours"] == approx2(0.00)

    dispatcher_after = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher_after["version"] == dispatcher_before["version"], (
        "a refused manual create must not increment the dispatcher's version"
    )
    assert dispatcher_after["remediation_hours_owed"] == approx2(4.00)
    assert dispatcher_after["dispatch_privilege"] == "FULL"


def test_a_manual_plan_without_a_source_review_cannot_collide(api):
    """PRD §3.8: "Supplying no `source_review_id` leaves the field null and cannot
    collide."
    PRD §3.8: "A manual create is a deliberate reset of the dispatcher's coaching:
    **every other open plan of that dispatcher is cancelled**, moving from
    `ASSIGNED`, `IN_PROGRESS` or `SUSPENDED` to `CANCELLED` with `closure_reason`
    set to `SUPERSEDED`."

    Design: Corner/errors/a_manual_plan_colliding_with_an_auto_plan_key_is_rejected
    """
    env = fx.scored_review_env(
        api,
        sections={
            "case_entry": (18, 20),
            "key_questions": (26, 30),
            "pre_arrival": (2, 3),
            "final_coding": (5, 7),
        },
        reviewer_determinant_code="10-C-2",
        program_overrides={
            "target_compliance_pct": 90.0,
            "watch_floor_pct": 80.0,
            "hours_owed_restriction_threshold": 6.0,
        },
    )
    fx.finalize(api, env["review_id"], "minor miscode, weak pre-arrival")
    dispatcher_before = fx.get_dispatcher(api, env["dispatcher_id"])

    response = api.create_coaching_plan(
        f.coaching_plan_payload(
            env["dispatcher_id"],
            dispatcher_before["version"],
            severity="CRITICAL",
            focus_area="DACPR",
        ),
        SUPERVISOR,
    )
    manual = validate_success(response, 201)
    assert manual["origin"] == "MANUAL"
    assert manual["source_review_id"] is None

    plans, meta = validate_paginated(
        api.list_coaching_plans(
            SUPERVISOR, {"dispatcher_id": env["dispatcher_id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    by_origin = {row["origin"]: row for row in plans}
    assert by_origin["AUTO"]["status"] == "CANCELLED"
    assert by_origin["AUTO"]["closure_reason"] == "SUPERSEDED"
    assert by_origin["MANUAL"]["status"] == "ASSIGNED"


# -------------------------------------------- terminality of the report filing
def test_filing_the_same_report_twice_is_rejected(api):
    """PRD §3.9: "The officer supplies `submitted_to`, naming either
    `MEDICAL_DIRECTOR` or `OVERSIGHT_COMMITTEE`; the report must still be in
    `DRAFT`, and a second filing is refused with `ERR_REPORT_ALREADY_SUBMITTED`."

    Design: Corner/errors/submitting_the_same_report_twice_is_rejected
    """
    env = fx.locked_period_env(api)

    first = get_success_data(
        api.submit_accreditation_report(
            env["report_id"], {"submitted_to": "MEDICAL_DIRECTOR"}, OFFICER
        )
    )
    assert first["status"] == "SUBMITTED"
    assert first["submitted_to"] == "MEDICAL_DIRECTOR"
    assert_instant_equals(first["submitted_at"], WORKING_CLOCK)

    response = api.submit_accreditation_report(
        env["report_id"], {"submitted_to": "OVERSIGHT_COMMITTEE"}, OFFICER
    )
    validate_error(response, err.ERR_REPORT_ALREADY_SUBMITTED)

    report = fx.get_report(api, env["program_id"], env["report_id"])
    assert report["status"] == "SUBMITTED"
    assert report["submitted_to"] == "MEDICAL_DIRECTOR", (
        "the refused second filing must not change the recipient"
    )
    assert_instant_equals(report["submitted_at"], WORKING_CLOCK)


def test_a_refused_second_filing_does_not_run_the_lock_cascade_again(api):
    """PRD §3.9: "`submitted_report_count` is recomputed as the number of the
    programme's reports in `SUBMITTED`; draft reports never count."
    PRD §3.9: "Every sampling period of the programme that is in `CLOSED` and whose
    half-open window overlaps the report's half-open window transitions
    `CLOSED → LOCKED`, stamping `locked_at` from the logical clock."

    Design: Corner/errors/submitting_the_same_report_twice_is_rejected
    """
    env = fx.locked_period_env(api)
    fx.submit_report(api, env["report_id"], "MEDICAL_DIRECTOR")
    fx.set_clock(api, "2026-08-21T00:00:00Z")

    response = api.submit_accreditation_report(
        env["report_id"], {"submitted_to": "MEDICAL_DIRECTOR"}, OFFICER
    )
    validate_error(response, err.ERR_REPORT_ALREADY_SUBMITTED)

    program = fx.get_program(api, env["program_id"])
    assert program["submitted_report_count"] == 1, "the filing must count exactly once"
    assert program["accreditation_status"] == "ACCREDITED"
    period = fx.get_period(api, env["program_id"], env["period_id"])
    assert period["status"] == "LOCKED"
    assert_instant_equals(period["locked_at"], WORKING_CLOCK)
