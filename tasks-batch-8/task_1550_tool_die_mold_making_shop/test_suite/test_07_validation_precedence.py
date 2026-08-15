"""Validation precedence pairs: an earlier tier masks a later tier when both
checks would reject the same request (PRD §2.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_press_reservation_payload,
    drive_job_to_buyoff_passed,
    get_success_data,
    setup_booked_job,
    ship_tool_asset_payload,
    start_build,
    validate_error,
)

PM = TEST_USERS["project_manager_headers"]


def test_ship_reports_state_error_not_lien_error_when_both_fail(api):
    """PRD §3.8: "The state gate is evaluated first: the tool must be in
    `AWAITING_SHIPMENT` and the job must be in `READY_TO_SHIP`, with any
    violation rejected as `ERR_INVALID_STATE`. Only after the state gate
    passes does the fiscal gate run: the job's `outstanding_cents` must be
    less than or equal to the ship threshold — the floor of fifteen hundredths
    of `contract_value_cents` — or the ship is refused with
    `ERR_RETENTION_LIEN_BLOCK` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/ship_state_error_precedes_lien_fiscal_error
    """
    ctx = setup_booked_job(company_name="Prio Co", part_number="PN-8001")
    start_build(ctx["job"]["id"])
    # Job IN_BUILD, tool IN_BUILD, nothing billed or paid: the state gate AND
    # the lien gate (outstanding 10,500,000 > 1,575,000) both fail.
    res = api_client.ship_tool_asset(ctx["tool"]["id"], ship_tool_asset_payload(), PM)

    error = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert error["error_id"] != ApiErrorId.ERR_RETENTION_LIEN_BLOCK
    assert res.status_code == 409

    tool = get_success_data(api_client.get_tool_asset(ctx["tool"]["id"], PM))
    assert tool["physical_status"] == "IN_BUILD", (
        "a rejected ship must not mutate the tool"
    )


def test_ship_reports_state_error_when_job_not_ready_even_though_tool_awaits(api):
    """PRD §3.8: "The state gate is evaluated first: the tool must be in
    `AWAITING_SHIPMENT` and the job must be in `READY_TO_SHIP`, with any
    violation rejected as `ERR_INVALID_STATE`. Only after the state gate
    passes does the fiscal gate run: the job's `outstanding_cents` must be
    less than or equal to the ship threshold — the floor of fifteen hundredths
    of `contract_value_cents` — or the ship is refused with
    `ERR_RETENTION_LIEN_BLOCK` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/ship_state_error_precedes_lien_fiscal_error
    """
    ctx = setup_booked_job(company_name="Prio Co", part_number="PN-8001")
    drive_job_to_buyoff_passed(ctx)
    # Tool IS AWAITING_SHIPMENT but the job is BUYOFF_PASSED, not
    # READY_TO_SHIP — and with nothing invoiced the lien gate would also fail.
    job = get_success_data(api_client.get_build_job(ctx["job"]["id"], PM))
    assert job["status"] == "BUYOFF_PASSED"
    assert job["outstanding_cents"] == 10_500_000

    res = api_client.ship_tool_asset(ctx["tool"]["id"], ship_tool_asset_payload(), PM)

    error = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert error["error_id"] != ApiErrorId.ERR_RETENTION_LIEN_BLOCK
    assert res.status_code == 409


def test_invalid_press_window_reports_temporal_error_not_overlap(api):
    """PRD §2.7: "When several checks could reject the same request, the
    server evaluates them in a fixed order, and a failure in an earlier tier
    masks every later tier."
    PRD §2.9: "Every window requires `end_time` strictly after `start_time`
    and `start_time` at or after the current logical time, failing with
    `ERR_INVALID_TIME_WINDOW` otherwise."

    Design: Difficulty/priority_pair_validation_conflict/press_temporal_error_precedes_overlap_constraint
    """
    ctx = setup_booked_job(company_name="Prio2 Co", part_number="PN-8002")
    job_id = ctx["job"]["id"]
    existing = get_success_data(api_client.create_press_reservation(
        create_press_reservation_payload(
            job_id, press_id="PRESS_500T",
            start_time="2026-08-10T10:00:00Z", end_time="2026-08-10T14:00:00Z",
        ), PM))

    # end_time (12:00) <= start_time (13:00) — temporally invalid — AND the
    # window would overlap the existing RESERVED window.
    res = api_client.create_press_reservation(
        create_press_reservation_payload(
            job_id, press_id="PRESS_500T",
            start_time="2026-08-10T13:00:00Z", end_time="2026-08-10T12:00:00Z",
        ), PM)

    error = validate_error(res, ApiErrorId.ERR_INVALID_TIME_WINDOW)
    assert error["error_id"] != ApiErrorId.ERR_PRESS_DOUBLE_BOOKED
    assert res.status_code == 422

    untouched = get_success_data(api_client.get_press_reservation(existing["id"], PM))
    assert untouched["status"] == "RESERVED"


def test_past_start_press_window_reports_temporal_error_not_overlap(api):
    """PRD §2.7: "When several checks could reject the same request, the
    server evaluates them in a fixed order, and a failure in an earlier tier
    masks every later tier."
    PRD §2.9: "Every window requires `end_time` strictly after `start_time`
    and `start_time` at or after the current logical time, failing with
    `ERR_INVALID_TIME_WINDOW` otherwise."

    Design: Difficulty/priority_pair_validation_conflict/press_temporal_error_precedes_overlap_constraint
    """
    ctx = setup_booked_job(company_name="Prio2 Co", part_number="PN-8002")
    job_id = ctx["job"]["id"]
    existing = get_success_data(api_client.create_press_reservation(
        create_press_reservation_payload(
            job_id, press_id="PRESS_500T",
            start_time="2026-08-10T10:00:00Z", end_time="2026-08-10T14:00:00Z",
        ), PM))

    # start_time in the past (the logical clock starts 2026-08-01) — a
    # temporal violation — AND the window overlaps the existing one.
    res = api_client.create_press_reservation(
        create_press_reservation_payload(
            job_id, press_id="PRESS_500T",
            start_time="2026-07-15T10:00:00Z", end_time="2026-08-10T12:00:00Z",
        ), PM)

    error = validate_error(res, ApiErrorId.ERR_INVALID_TIME_WINDOW)
    assert error["error_id"] != ApiErrorId.ERR_PRESS_DOUBLE_BOOKED
    assert res.status_code == 422

    untouched = get_success_data(api_client.get_press_reservation(existing["id"], PM))
    assert untouched["status"] == "RESERVED"
