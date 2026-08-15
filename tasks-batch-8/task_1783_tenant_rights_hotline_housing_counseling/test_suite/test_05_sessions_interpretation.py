"""Call sessions: assignment, start gates, and the parallel interpretation
dimension (PRD §3.5, §2.9, §2.10)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_call_session,
    create_caller,
    create_counselor,
    create_interpreter,
    create_jurisdiction,
    get_session,
    intake_session,
    make_counselor_headers,
    set_clock,
    setup_hotline,
    validate_error,
    validate_success,
)

WINDOW_1 = ("2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
WINDOW_OVERLAP = ("2026-08-02T11:05:00Z", "2026-08-02T12:00:00Z")
WINDOW_FREE = ("2026-08-02T12:00:00Z", "2026-08-02T13:00:00Z")
WINDOW_ONE_BUFFER = ("2026-08-02T11:10:00Z", "2026-08-02T12:00:00Z")


def _minimal_roster(api, interpreter_language="es"):
    """Jurisdiction + worker counselor + interpreter — no script chain needed for
    interpretation-dimension calls from QUEUED sessions."""
    jur = create_jurisdiction()
    worker = create_counselor(display_name="Worker W")
    interp = create_interpreter(display_name="Interp", language_code=interpreter_language)
    return jur, worker, interp


def _queued_session(api, jur, language="es"):
    caller = create_caller(preferred_language=language)
    session = validate_success(api.create_session(
        {"caller_id": caller["id"], "jurisdiction_id": jur["id"],
         "issue_category": "EVICTION"},
        TEST_USERS["anonymous_headers"],
    ), expected_status=201)
    assert session["session_status"] == "QUEUED"
    assert session["interpretation_status"] == "NOT_REQUIRED"
    return caller, session


def _request(api, session_id, interpreter_id, window, headers):
    return api.transition_interpretation(
        session_id,
        {"to_status": "REQUESTED", "interpreter_id": interpreter_id,
         "scheduled_start_at": window[0], "scheduled_end_at": window[1]},
        headers,
    )


def test_session_assign_action_endpoint(api):
    """PRD §3.5: "Assignment moves the session `QUEUED` → `ASSIGNED` under a
    `Counselor` or `HotlineSupervisor`, naming the target counselor in the payload's
    `counselor_id`."
    PRD §3.5: "The session is born with `session_status` `QUEUED` and
    `interpretation_status` `NOT_REQUIRED`: two independent dimensions carried on
    one row, and the session may not go active while an interpreter request is in
    flight."

    Design: Corner/endpoints/session_assign_action_endpoint
    """
    bundle = setup_hotline()
    caller = create_caller()
    session = intake_session(bundle, caller)

    assigned = validate_success(api.transition_session(
        session["id"],
        {"to_status": "ASSIGNED", "counselor_id": bundle["worker"]["id"]},
        bundle["worker_headers"],
    ))
    assert_call_session(assigned)
    assert assigned["session_status"] == "ASSIGNED"
    assert assigned["counselor_id"] == bundle["worker"]["id"]
    assert assigned["interpretation_status"] == "NOT_REQUIRED", (
        "a plain assignment leaves the parallel interpretation dimension untouched"
    )


def test_queue_wait_seconds_computed(api):
    """PRD §3.5: "On a successful start, `actual_start_at` is stamped from the
    logical clock, `queue_wait_seconds` is computed as the whole-second difference
    between `actual_start_at` and `created_at` (sessions that never reach `ACTIVE`
    report 0), and `pinned_script_id` is set to the current published script for the
    pair per the §3.2 selector."

    Design: Corner/calculations/queue_wait_seconds_computed
    """
    bundle = setup_hotline()
    caller = create_caller()
    session = intake_session(bundle, caller)
    validate_success(api.transition_session(
        session["id"],
        {"to_status": "ASSIGNED", "counselor_id": bundle["worker"]["id"]},
        bundle["worker_headers"],
    ))
    set_clock("2026-08-01T00:02:30Z")  # 150 seconds after intake
    started = validate_success(api.transition_session(
        session["id"], {"to_status": "ACTIVE"}, bundle["worker_headers"]
    ))
    assert started["queue_wait_seconds"] == 150, (
        f"created 2026-08-01T00:00:00Z, started 2026-08-01T00:02:30Z; "
        f"got {started['queue_wait_seconds']}"
    )


def test_start_rejected_while_interpretation_requested(api):
    """PRD §3.5: "Starting the session (`ASSIGNED` → `ACTIVE`) re-evaluates the live
    gates: the interpretation dimension must not be `REQUESTED` (`ERR_INVALID_STATE`
    — a session cannot start while awaiting an interpreter); the assigned counselor
    must be `ACTIVE` at this moment (`ERR_COUNSELOR_INACTIVE`) with unexpired
    certification (`ERR_CERTIFICATION_EXPIRED`); and the language rule fires —
    either the counselor's `languages` contain the caller's `preferred_language`, or
    the interpretation dimension stands at `CONNECTED`, failing which the start is
    rejected with `ERR_LANGUAGE_UNSUPPORTED`."

    Design: Difficulty/non_linear_state_machine/session_parallel_dimensions
    """
    bundle = setup_hotline()  # worker speaks en only
    interp = create_interpreter(display_name="Interp I", language_code="es")
    caller = create_caller(alias="caller-es", phone="+15550002",
                           preferred_language="es")
    session = intake_session(bundle, caller)
    validate_success(api.transition_session(
        session["id"],
        {"to_status": "ASSIGNED", "counselor_id": bundle["worker"]["id"]},
        bundle["worker_headers"],
    ))

    requested = validate_success(_request(
        api, session["id"], interp["id"], WINDOW_1, bundle["worker_headers"]
    ))
    assert requested["interpretation_status"] == "REQUESTED"
    assert requested["session_status"] == "ASSIGNED", (
        "the interpretation dimension advances independently of session_status"
    )

    blocked = api.transition_session(
        session["id"], {"to_status": "ACTIVE"}, bundle["worker_headers"]
    )
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)
    current = get_session(bundle, session["id"])
    assert current["session_status"] == "ASSIGNED"
    assert current["interpretation_status"] == "REQUESTED"


def test_start_with_connected_interpreter_pins_script(api):
    """PRD §3.5: "On a successful start, `actual_start_at` is stamped from the
    logical clock, `queue_wait_seconds` is computed as the whole-second difference
    between `actual_start_at` and `created_at` (sessions that never reach `ACTIVE`
    report 0), and `pinned_script_id` is set to the current published script for the
    pair per the §3.2 selector."
    PRD §3.5: "Once requested, the bridge either connects — `REQUESTED` →
    `CONNECTED` — or fails."

    Design: Difficulty/non_linear_state_machine/session_parallel_dimensions
    """
    bundle = setup_hotline()  # worker speaks en only; caller prefers es
    interp = create_interpreter(display_name="Interp I", language_code="es")
    caller = create_caller(alias="caller-es", phone="+15550002",
                           preferred_language="es")
    session = intake_session(bundle, caller)
    validate_success(api.transition_session(
        session["id"],
        {"to_status": "ASSIGNED", "counselor_id": bundle["worker"]["id"]},
        bundle["worker_headers"],
    ))
    validate_success(_request(
        api, session["id"], interp["id"], WINDOW_1, bundle["worker_headers"]
    ))
    connected = validate_success(api.transition_interpretation(
        session["id"], {"to_status": "CONNECTED"}, bundle["worker_headers"]
    ))
    assert connected["interpretation_status"] == "CONNECTED"

    started = validate_success(api.transition_session(
        session["id"], {"to_status": "ACTIVE"}, bundle["worker_headers"]
    ))
    assert started["session_status"] == "ACTIVE"
    assert started["interpretation_status"] == "CONNECTED"
    assert started["pinned_script_id"] == bundle["script"]["id"], (
        "the current PUBLISHED script is pinned at ACTIVE time"
    )
    assert started["queue_wait_seconds"] == 0, (
        "created and started at the same logical instant"
    )


def test_start_language_unsupported_rejected(api):
    """PRD §3.5: "Starting the session (`ASSIGNED` → `ACTIVE`) re-evaluates the live
    gates: the interpretation dimension must not be `REQUESTED` (`ERR_INVALID_STATE`
    — a session cannot start while awaiting an interpreter); the assigned counselor
    must be `ACTIVE` at this moment (`ERR_COUNSELOR_INACTIVE`) with unexpired
    certification (`ERR_CERTIFICATION_EXPIRED`); and the language rule fires —
    either the counselor's `languages` contain the caller's `preferred_language`, or
    the interpretation dimension stands at `CONNECTED`, failing which the start is
    rejected with `ERR_LANGUAGE_UNSUPPORTED`."

    Design: Corner/state_machines/start_language_unsupported_rejected
    """
    bundle = setup_hotline()  # worker languages ["en"]
    caller = create_caller(alias="caller-es", phone="+15550002",
                           preferred_language="es")
    session = intake_session(bundle, caller)
    validate_success(api.transition_session(
        session["id"],
        {"to_status": "ASSIGNED", "counselor_id": bundle["worker"]["id"]},
        bundle["worker_headers"],
    ))

    resp = api.transition_session(
        session["id"], {"to_status": "ACTIVE"}, bundle["worker_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_LANGUAGE_UNSUPPORTED)
    current = get_session(bundle, session["id"])
    assert current["session_status"] == "ASSIGNED"
    assert current.get("pinned_script_id") is None


def test_interpreter_failed_retry_same_rejected(api):
    """PRD §3.5: "A failure (`REQUESTED` → `FAILED`) appends the interpreter to the
    session's `failed_interpreter_ids` and clears the booked window. A retry
    (`FAILED` → `REQUESTED`) must name an interpreter absent from
    `failed_interpreter_ids` (`ERR_INTERPRETER_PREVIOUSLY_FAILED`) and passes the
    same language, window, and overlap checks as the initial request."

    Design: Corner/state_machines/interpreter_failed_retry_same_rejected
    """
    jur, worker, interp = _minimal_roster(api, interpreter_language="es")
    caller, session = _queued_session(api, jur, language="es")
    headers = TEST_USERS["supervisor_headers"]

    validate_success(_request(api, session["id"], interp["id"], WINDOW_1, headers))
    failed = validate_success(api.transition_interpretation(
        session["id"], {"to_status": "FAILED"}, headers
    ))
    assert failed["interpretation_status"] == "FAILED"
    assert failed["failed_interpreter_ids"] == [interp["id"]]

    retry = _request(api, session["id"], interp["id"], WINDOW_FREE, headers)
    validate_error(retry, ApiErrorId.ERR_INTERPRETER_PREVIOUSLY_FAILED)


def test_interpreter_overlap_rejected_within_buffer(api):
    """PRD §3.5: "Windows are half-open, and a ten-minute buffer is added to each
    end: a conflict exists when the new window's start is earlier than an existing
    window's end plus ten minutes and the existing window's start is earlier than
    the new window's end plus ten minutes. Consequently a back-to-back booking
    conflicts, while one starting exactly ten minutes after an existing window's end
    does not; a conflict is rejected with `ERR_INTERPRETER_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/interpreter_buffer_overlap
    """
    jur, worker, interp = _minimal_roster(api, interpreter_language="es")
    headers = TEST_USERS["supervisor_headers"]
    _, s1 = _queued_session(api, jur, language="es")
    _, s2 = _queued_session(api, jur, language="es")

    first = _request(api, s1["id"], interp["id"], WINDOW_1, headers)
    assert validate_success(first)["interpretation_status"] == "REQUESTED"

    # 11:05 is earlier than 11:00 + 10 minutes — inside the buffer.
    conflict = _request(api, s2["id"], interp["id"], WINDOW_OVERLAP, headers)
    validate_error(conflict, ApiErrorId.ERR_INTERPRETER_OVERLAP)


def test_interpreter_booking_exactly_one_buffer_apart_accepted(api):
    """PRD §3.5: "Windows are half-open, and a ten-minute buffer is added to each
    end: a conflict exists when the new window's start is earlier than an existing
    window's end plus ten minutes and the existing window's start is earlier than
    the new window's end plus ten minutes. Consequently a back-to-back booking
    conflicts, while one starting exactly ten minutes after an existing window's end
    does not; a conflict is rejected with `ERR_INTERPRETER_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/interpreter_buffer_overlap
    """
    jur, worker, interp = _minimal_roster(api, interpreter_language="es")
    headers = TEST_USERS["supervisor_headers"]
    _, s1 = _queued_session(api, jur, language="es")
    _, s3 = _queued_session(api, jur, language="es")

    validate_success(_request(api, s1["id"], interp["id"], WINDOW_1, headers))
    # 11:10 is exactly one ten-minute buffer after the 11:00 end — no conflict.
    accepted = _request(api, s3["id"], interp["id"], WINDOW_ONE_BUFFER, headers)
    assert validate_success(accepted)["interpretation_status"] == "REQUESTED"


def test_interpreter_language_mismatch_beats_overlap(api):
    """PRD §2.10: "When several checks could reject the same request, the server
    evaluates them in a fixed priority order and the first failing check determines
    the error returned; ordering matters because an early rejection masks later
    ones."
    PRD §2.10: "**Safety and compliance gates**, evaluated in this order: an
    anonymous caller receiving a follow-up or granting follow-up consent
    (`ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN`); an action on a caller whose PII has been
    purged (`ERR_CALLER_PII_PURGED`); a counselor who is not active
    (`ERR_COUNSELOR_INACTIVE`); an expired counselor certification
    (`ERR_CERTIFICATION_EXPIRED`); counselor training not current on the published
    script (`ERR_TRAINING_NOT_CURRENT`); a counselor/caller language gap without a
    connected interpreter (`ERR_LANGUAGE_UNSUPPORTED`); and an interpreter whose
    language does not match the caller's (`ERR_INTERPRETER_LANGUAGE_MISMATCH`)."
    PRD §2.10: "Buffered interpreter overlap (`ERR_INTERPRETER_OVERLAP`), a
    previously failed interpreter (`ERR_INTERPRETER_PREVIOUSLY_FAILED`), exhausted
    weekly organization capacity (`ERR_ORG_CAPACITY_FULL`), a duplicate published
    script for the pair (`ERR_DUPLICATE_PUBLISHED_SCRIPT`), and a broken
    supersession chain (`ERR_SCRIPT_VERSION_CHAIN_BROKEN`)."

    Design: Difficulty/priority_pair_validation_conflict/interpreter_language_mismatch_beats_overlap
    """
    jur, worker, interp = _minimal_roster(api, interpreter_language="fr")
    headers = TEST_USERS["supervisor_headers"]
    _, s1 = _queued_session(api, jur, language="fr")
    _, s2 = _queued_session(api, jur, language="es")

    # Book the fr interpreter 10:00-11:00 for the fr caller (languages match).
    validate_success(_request(api, s1["id"], interp["id"], WINDOW_1, headers))

    # The es caller's session requests the fr interpreter on an overlapping
    # window: language mismatch (safety) must beat overlap (constraint).
    conflict = _request(api, s2["id"], interp["id"], WINDOW_OVERLAP, headers)
    validate_error(conflict, ApiErrorId.ERR_INTERPRETER_LANGUAGE_MISMATCH)


def test_interpreter_language_mismatch_alone_on_free_window(api):
    """PRD §3.5: "The interpreter's `language_code` must equal the caller's
    `preferred_language` (`ERR_INTERPRETER_LANGUAGE_MISMATCH`); the window's end
    must be strictly after its start (`ERR_INVALID_REQUEST`); and the window must
    survive the buffered-overlap check against the interpreter's existing book —
    every other session of the same interpreter whose interpretation stands at
    `REQUESTED` or `CONNECTED` while the session itself is `QUEUED`, `ASSIGNED`, or
    `ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/interpreter_language_mismatch_beats_overlap
    """
    jur, worker, interp = _minimal_roster(api, interpreter_language="fr")
    headers = TEST_USERS["supervisor_headers"]
    _, s1 = _queued_session(api, jur, language="fr")
    _, s2 = _queued_session(api, jur, language="es")
    validate_success(_request(api, s1["id"], interp["id"], WINDOW_1, headers))

    # Same mismatched language pair on a window that does NOT overlap: the
    # language rule fires alone.
    mismatch = _request(api, s2["id"], interp["id"], WINDOW_FREE, headers)
    validate_error(mismatch, ApiErrorId.ERR_INTERPRETER_LANGUAGE_MISMATCH)
    current = validate_success(api.get_session(s2["id"], headers))
    assert current["interpretation_status"] == "NOT_REQUIRED", (
        "the rejected request leaves the interpretation dimension untouched"
    )


def test_session_abandoned_lockdown(api):
    """PRD §3.5: "`WRAPPED_UP`, `DROPPED`, and `ABANDONED` are terminal, and
    reaching any of them freezes both status dimensions."
    PRD §2.9: "Terminal states are absolute: a resource in a terminal state rejects
    every further transition, and a call session reaching a terminal state freezes
    both of its status dimensions."
    PRD §3.5: "While the session is `QUEUED` or `ASSIGNED` (otherwise
    `ERR_INVALID_STATE`), an interpretation request moves it `NOT_REQUIRED` →
    `REQUESTED`, naming an `interpreter_id` and a booking window from
    `scheduled_start_at` to `scheduled_end_at`."

    Design: Corner/state_machines/session_abandoned_lockdown
    """
    jur, worker, interp = _minimal_roster(api, interpreter_language="es")
    caller, session = _queued_session(api, jur, language="es")
    headers = TEST_USERS["supervisor_headers"]
    worker_headers = make_counselor_headers(worker["id"])

    abandoned = validate_success(api.transition_session(
        session["id"], {"to_status": "ABANDONED"}, worker_headers,
    ))
    assert abandoned["session_status"] == "ABANDONED"

    assign = api.transition_session(
        session["id"],
        {"to_status": "ASSIGNED", "counselor_id": worker["id"]},
        worker_headers,
    )
    validate_error(assign, ApiErrorId.ERR_INVALID_STATE)

    interp_req = _request(api, session["id"], interp["id"], WINDOW_1, headers)
    validate_error(interp_req, ApiErrorId.ERR_INVALID_STATE)
