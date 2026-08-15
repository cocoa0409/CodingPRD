"""Tech rider checks and stop certification (PRD §3.3)."""
from test_helpers import (
    PRODUCER,
    TOUR_MANAGER,
    ApiErrorId,
    add_stop,
    advance_stop,
    contract_stop,
    create_tech_check,
    create_tour,
    create_venue,
    get_stop,
    record_check_actual,
    setup_advanced_stop,
    setup_ready_stop,
    validate_error,
    validate_success,
)


def test_certify_blocked_by_fail_check(api):
    """PRD §3.3: "Certification — the `TourManager`’s transition of the stop from `ADVANCED` to `READY` — requires `compliance_status` to be `COMPLIANT`; certifying against anything less is rejected with `ERR_STOP_NOT_COMPLIANT`."
    PRD §3.3: "`NON_COMPLIANT` whenever any check stands at `FAIL`"

    Design: Difficulty/cross_entity_state_dependency/stop_certify_requires_all_checks_compliant
    """
    ctx = setup_advanced_stop()
    stop = ctx["stop"]
    check = create_tech_check(stop["id"], item="STAGE_WIDTH_FT", required_value=40)
    record_check_actual(check["id"], 38)  # 38 < 40 -> FAIL

    resp = api.put_stop(stop["id"], {"status": "READY"}, TOUR_MANAGER)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_COMPLIANT)


def test_certify_blocked_with_zero_checks(api):
    """PRD §3.3: "it is `COMPLIANT` when at least one check exists and every
    check is `PASS` or `WAIVED`"
    PRD §3.3: "Certification — the `TourManager`’s transition of the stop from `ADVANCED` to `READY` — requires `compliance_status` to be `COMPLIANT`; certifying against anything less is rejected with `ERR_STOP_NOT_COMPLIANT`."

    Design: Difficulty/cross_entity_state_dependency/stop_certify_requires_all_checks_compliant
    """
    ctx = setup_advanced_stop()
    stop = ctx["stop"]
    assert stop["compliance_status"] == "PENDING"

    resp = api.put_stop(stop["id"], {"status": "READY"}, TOUR_MANAGER)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_COMPLIANT)


def test_parallel_dimensions_ready_blocked_until_compliant(api):
    """PRD §3.3: "`IN_PROGRESS` when checks exist, none has failed, and at least
    one remains `PENDING`."
    PRD §3.3: "Certification — the `TourManager`’s transition of the stop from `ADVANCED` to `READY` — requires `compliance_status` to be `COMPLIANT`; certifying against anything less is rejected with `ERR_STOP_NOT_COMPLIANT`."

    Design: Difficulty/non_linear_state_machine/stop_parallel_dimensions
    """
    ctx = setup_advanced_stop()
    stop = ctx["stop"]
    chk_a = create_tech_check(stop["id"], item="STAGE_WIDTH_FT", required_value=40)
    chk_b = create_tech_check(stop["id"], item="FLY_LINES", required_value=30)
    record_check_actual(chk_a["id"], 42)  # PASS; chk_b still PENDING

    # compliance IN_PROGRESS (one PASS, one PENDING) gates the booking transition.
    resp = api.put_stop(stop["id"], {"status": "READY"}, TOUR_MANAGER)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_COMPLIANT)

    record_check_actual(chk_b["id"], 30)  # PASS (== required passes)
    ready = validate_success(api.put_stop(stop["id"], {"status": "READY"}, TOUR_MANAGER))
    assert ready["booking_status"] == "READY"
    assert ready["compliance_status"] == "COMPLIANT"


def test_parallel_dimensions_late_fail_drags_booking(api):
    """PRD §3.3: "If any check on a `READY` stop flips to `FAIL` — through a fresh measurement or a re-measurement — the stop’s certification is revoked automatically: `compliance_status` becomes `NON_COMPLIANT` and `booking_status` reverts from `READY` to `ADVANCED`, blocking performance scheduling until the stop is re-certified."

    Design: Difficulty/non_linear_state_machine/stop_parallel_dimensions
    """
    ctx = setup_advanced_stop()
    stop = ctx["stop"]
    chk_a = create_tech_check(stop["id"], item="STAGE_WIDTH_FT", required_value=40)
    chk_b = create_tech_check(stop["id"], item="FLY_LINES", required_value=30)
    record_check_actual(chk_a["id"], 42)
    record_check_actual(chk_b["id"], 30)
    validate_success(api.put_stop(stop["id"], {"status": "READY"}, TOUR_MANAGER))

    record_check_actual(chk_a["id"], 38)  # re-measurement regresses PASS -> FAIL
    after = get_stop(stop["id"])
    assert after["compliance_status"] == "NON_COMPLIANT"
    assert after["booking_status"] == "ADVANCED", (
        "The compliance dimension drags booking READY->ADVANCED with no direct booking request"
    )


def test_tech_fail_revokes_certification_compliance_flip(api):
    """PRD §3.3: "The system computes the outcome: if the recorded value is at
    least the required value the check becomes `PASS`; below the requirement it
    becomes `FAIL`."
    PRD §3.3: "If any check on a `READY` stop flips to `FAIL` — through a fresh
    measurement or a re-measurement — the stop’s certification is revoked
    automatically: `compliance_status` becomes `NON_COMPLIANT` and
    `booking_status` reverts from `READY` to `ADVANCED`"

    Design: Difficulty/transitive_cascade/tech_fail_certification_revocation_cascade
    """
    ctx = setup_ready_stop()
    stop = ctx["stop"]
    check_id = ctx["check"]["id"]

    failed = record_check_actual(check_id, 38)  # 38 < 40
    assert failed["status"] == "FAIL"

    after = get_stop(stop["id"])
    assert after["compliance_status"] == "NON_COMPLIANT", (
        "Link 1: the check failure recomputes the derived compliance dimension"
    )


def test_tech_fail_revokes_certification_booking_revert(api):
    """PRD §3.3: "If any check on a `READY` stop flips to `FAIL` — through a fresh measurement or a re-measurement — the stop’s certification is revoked automatically: `compliance_status` becomes `NON_COMPLIANT` and `booking_status` reverts from `READY` to `ADVANCED`, blocking performance scheduling until the stop is re-certified."

    Design: Difficulty/transitive_cascade/tech_fail_certification_revocation_cascade
    """
    ctx = setup_ready_stop()
    stop = ctx["stop"]
    check_id = ctx["check"]["id"]

    record_check_actual(check_id, 38)
    after = get_stop(stop["id"])
    assert after["booking_status"] == "ADVANCED", (
        "Link 2: certification revoked; booking reverts READY->ADVANCED"
    )

    # Scheduling is blocked until re-certification.
    resp = api.create_performance(
        stop["id"],
        {"perf_date": "2026-09-08", "curtain_time": "19:30", "duration_minutes": 150},
        TOUR_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_SCHEDULABLE)


def test_check_waived_is_terminal_and_waive_only_from_fail(api):
    """PRD §3.3: "Recording a measurement on a `WAIVED` check is rejected with
    `ERR_CHECK_INVALID_STATE`, because `WAIVED` is terminal."
    PRD §3.3: "A `Producer` may waive a check that currently stands at `FAIL` by
    supplying a `waiver_note`; the note is mandatory, its absence draws
    `ERR_WAIVER_NOTE_REQUIRED`, and waiving a check not in `FAIL` draws
    `ERR_CHECK_INVALID_STATE`."

    Design: Corner/state_machines/check_waived_is_terminal_and_waive_only_from_fail
    """
    ctx = setup_advanced_stop()
    stop = ctx["stop"]
    chk_a = create_tech_check(stop["id"], item="STAGE_WIDTH_FT", required_value=40)
    chk_b = create_tech_check(stop["id"], item="POWER_AMPS", required_value=400)
    record_check_actual(chk_a["id"], 42)   # PASS
    record_check_actual(chk_b["id"], 350)  # FAIL
    waived = validate_success(
        api.put_tech_check(chk_b["id"], {"status": "WAIVED",
                                         "waiver_note": "producer accepts dimmer rack"},
                           PRODUCER))
    assert waived["status"] == "WAIVED"

    # Waiving a PASS check is rejected (waive is legal only from FAIL).
    resp1 = api.put_tech_check(chk_a["id"], {"status": "WAIVED", "waiver_note": "n/a"},
                               PRODUCER)
    validate_error(resp1, ApiErrorId.ERR_CHECK_INVALID_STATE)

    # Re-measurement on a WAIVED check is rejected (WAIVED is terminal).
    resp2 = api.put_tech_check(chk_b["id"], {"actual_value": 410}, TOUR_MANAGER)
    validate_error(resp2, ApiErrorId.ERR_CHECK_INVALID_STATE)


def test_waive_without_note_returns_waiver_required(api):
    """PRD §3.3: "A `Producer` may waive a check that currently stands at `FAIL`
    by supplying a `waiver_note`; the note is mandatory, its absence draws
    `ERR_WAIVER_NOTE_REQUIRED`"

    Design: Corner/validations/waive_without_note_returns_waiver_required
    """
    ctx = setup_advanced_stop()
    stop = ctx["stop"]
    chk = create_tech_check(stop["id"], item="POWER_AMPS", required_value=400)
    record_check_actual(chk["id"], 350)  # FAIL

    resp = api.put_tech_check(chk["id"], {"status": "WAIVED"}, PRODUCER)
    validate_error(resp, ApiErrorId.ERR_WAIVER_NOTE_REQUIRED)
