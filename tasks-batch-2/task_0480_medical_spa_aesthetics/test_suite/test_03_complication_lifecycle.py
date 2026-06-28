"""Complication-case lifecycle tests (§3.7).

`ComplicationCase` is the cyclic entity: `OPEN` -> `IN_TOUCHUP` -> `OPEN`, bounded by a
round cap of 2. `SEVERE` cases are refund-only. Opening a case forks the session
to `COMPLICATION_OPEN` and blocks resolution.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    make_provider_headers,
    setup_committed_session,
    setup_open_complication,
    open_complication,
)


def test_complication_cycles_open_touchup_open_touchup(api):
    """PRD §3.7: "Opening a touch-up advances the case from `OPEN` to `IN_TOUCHUP` ...
    Opening a touch-up increments the case's `touchup_rounds` by 1." PRD §3.7: "If
    the touch-up does not succeed, the case is looped back from `IN_TOUCHUP` to
    `OPEN` ... making it eligible for another round, up to the cap, or for refund
    resolution."

    `OPEN` -> `IN_TOUCHUP` (rounds 0->1) -> `OPEN` (touchup-failed) -> `IN_TOUCHUP`
    (rounds 1->2) ends at `IN_TOUCHUP` with `touchup_rounds`==2.

    Design: Difficulty/non_linear_state_machine/complication_case_cycle_open_touchup_open
    """
    sc = setup_open_complication(severity="MODERATE")
    hdr = make_provider_headers(sc.injector_id)
    validate_success(api.open_touchup(sc.case_id, hdr))
    validate_success(api.touchup_failed(sc.case_id, hdr))
    data = validate_success(api.open_touchup(sc.case_id, hdr))
    assert data["status"] == "IN_TOUCHUP", (
        f"case should be IN_TOUCHUP after second open-touchup, got {data['status']}")
    assert data["touchup_rounds"] == 2, (
        f"touchup_rounds should be 2 after two rounds, got {data['touchup_rounds']}")


def test_touchup_rounds_increment_on_each_open(api):
    """PRD §3.7: "Opening a touch-up advances the case from `OPEN` to `IN_TOUCHUP` ...
    Opening a touch-up increments the case's `touchup_rounds` by 1."

    The first open-touchup moves `OPEN` -> `IN_TOUCHUP` and sets `touchup_rounds` to 1.

    Design: Difficulty/non_linear_state_machine/complication_case_cycle_open_touchup_open
    """
    sc = setup_open_complication(severity="MODERATE")
    hdr = make_provider_headers(sc.injector_id)
    data = validate_success(api.open_touchup(sc.case_id, hdr))
    assert data["status"] == "IN_TOUCHUP"
    assert data["touchup_rounds"] == 1, (
        f"touchup_rounds should be 1 after first round, got {data['touchup_rounds']}")


def test_open_complication_forks_session_to_complication_open(api):
    """PRD §3.7: "Opening a case moves the session from `COMMITTED` to
    `COMPLICATION_OPEN`, creates the case in `OPEN` with `touchup_rounds` and
    `refund_cents` at 0, copies the originating session's injector into the case's
    `injector_provider_id` for provider risk scoring, and recomputes that
    provider's `open_complication_count`."

    Design: Difficulty/non_linear_state_machine/treatment_session_branch_committed_to_complication_open
    """
    sc = setup_committed_session(add_after=True, planned_units=20, max_units_authorized=30)
    hdr = make_provider_headers(sc.injector_id)
    case = open_complication(sc.session_id, sc.injector_id, severity="MINOR")
    session = validate_success(api.get_treatment_session(sc.session_id, hdr))
    assert session["status"] == "COMPLICATION_OPEN", (
        f"session should be COMPLICATION_OPEN, got {session['status']}")
    provider = validate_success(api.get_provider(sc.injector_id, hdr))
    assert provider["open_complication_count"] == 1, (
        f"open_complication_count should be 1, got {provider['open_complication_count']}")


def test_resolve_blocked_while_complication_open(api):
    """PRD §3.7: "Resolution advances the session from `COMMITTED` to `RESOLVED` and
    is permitted only when the session is `COMMITTED` (otherwise
    `ERR_SESSION_NOT_COMMITTED`), when an `AFTER` photo tied to the session exists
    (otherwise `ERR_AFTER_PHOTO_REQUIRED`), and when no `ComplicationCase` for the
    session is in `OPEN` or `IN_TOUCHUP` (otherwise `ERR_COMPLICATION_OPEN`)."

    With an `AFTER` photo on file but an open complication, resolve is rejected.
    The PRD lists the source-state check (`ERR_SESSION_NOT_COMMITTED`) ahead of
    the complication guard (`ERR_COMPLICATION_OPEN`), and once a complication
    opens the session has already left `COMMITTED` for `COMPLICATION_OPEN`; a
    faithful reader could return either, so both are accepted.

    Design: Difficulty/non_linear_state_machine/treatment_session_branch_committed_to_complication_open
    """
    sc = setup_committed_session(add_after=True, planned_units=20, max_units_authorized=30)
    hdr = make_provider_headers(sc.injector_id)
    open_complication(sc.session_id, sc.injector_id, severity="MINOR")
    resp = api.resolve_session(sc.session_id, hdr)
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_COMPLICATION_OPEN.value,
         ApiErrorId.ERR_SESSION_NOT_COMMITTED.value])


def test_severe_complication_cannot_open_touchup(api):
    """PRD §3.7: "Opening a touch-up advances the case from `OPEN` to `IN_TOUCHUP` and
    is permitted only when the case is `OPEN` ..., when the severity is `MINOR` or
    `MODERATE` — a `SEVERE` complication is refund-only and may never open a touch-up
    (otherwise `ERR_SEVERE_NO_TOUCHUP`)."

    Design: Corner/state_machines/severe_complication_open_touchup_returns_severe_no_touchup
    """
    sc = setup_open_complication(severity="SEVERE")
    resp = api.open_touchup(sc.case_id, make_provider_headers(sc.injector_id))
    validate_error(resp, ApiErrorId.ERR_SEVERE_NO_TOUCHUP.value)


def test_touchup_limit_reached_after_two_rounds(api):
    """PRD §3.7: "Opening a touch-up advances the case from `OPEN` to `IN_TOUCHUP` and
    is permitted only when ... `touchup_rounds` is strictly less than the round cap
    of 2 (otherwise `ERR_TOUCHUP_LIMIT_REACHED`)."

    After two completed rounds (`touchup_rounds`==2), a third open-touchup is
    rejected `ERR_TOUCHUP_LIMIT_REACHED`.

    Design: Corner/state_machines/touchup_limit_reached_after_two_rounds
    """
    sc = setup_open_complication(severity="MODERATE")
    hdr = make_provider_headers(sc.injector_id)
    validate_success(api.open_touchup(sc.case_id, hdr))
    validate_success(api.touchup_failed(sc.case_id, hdr))
    validate_success(api.open_touchup(sc.case_id, hdr))
    validate_success(api.touchup_failed(sc.case_id, hdr))
    case = validate_success(api.get_complication_case(sc.case_id, hdr))
    assert case["touchup_rounds"] == 2, (
        f"touchup_rounds should be 2, got {case['touchup_rounds']}")
    resp = api.open_touchup(sc.case_id, hdr)
    validate_error(resp, ApiErrorId.ERR_TOUCHUP_LIMIT_REACHED.value)


def test_resolve_without_after_photo_rejected(api):
    """PRD §3.7: "Resolution advances the session from `COMMITTED` to `RESOLVED` and
    is permitted only when the session is `COMMITTED` (otherwise
    `ERR_SESSION_NOT_COMMITTED`), when an `AFTER` photo tied to the session exists
    (otherwise `ERR_AFTER_PHOTO_REQUIRED`) ..."

    A `COMMITTED` session with a `BEFORE` photo but no `AFTER` photo cannot resolve.

    Design: Corner/state_machines/resolve_session_without_after_photo_returns_after_photo_required
    """
    sc = setup_committed_session(add_after=False, planned_units=20, max_units_authorized=30)
    resp = api.resolve_session(sc.session_id, make_provider_headers(sc.injector_id))
    validate_error(resp, ApiErrorId.ERR_AFTER_PHOTO_REQUIRED.value)
