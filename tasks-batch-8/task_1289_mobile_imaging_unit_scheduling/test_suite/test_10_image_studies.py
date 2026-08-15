"""Image studies: deterministic transfer budget, retry cycle, acknowledge SLA,
and mutation-response immediacy."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_appointment,
    book_and_complete_appointment,
    complete_appointment_flow,
    create_image_study_payload,
    get_success_data,
    make_facility_coordinator_headers,
    make_technologist_headers,
    record_checklist_item,
    register_and_transmit_study,
    set_clock,
    setup_in_service_day,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["operations_director_headers"]
RADIOLOGIST = TEST_USERS["reading_radiologist_headers"]


def _setup_completed_appointment_with_study(api, size_mb, uplink_mbps=100):
    """PER_SCAN day IN_SERVICE with uplink `uplink_mbps` (transfer budget
    floor(uplink * 7.5) MB); one COMPLETED appointment with a QUEUED study of
    `size_mb`."""
    bundle = setup_in_service_day(billing_model="PER_SCAN", uplink_mbps=uplink_mbps)
    appt = book_and_complete_appointment(bundle, "P-001", scheduled_start="09:00")
    tech_headers = make_technologist_headers(bundle["technologist"]["id"])
    study = get_success_data(
        api.create_image_study(
            create_image_study_payload(appt["id"], "1.2.3.4", size_mb), tech_headers
        )
    )
    return bundle, appt, study


def test_oversize_study_fails_then_retry_requeues(api):
    """PRD §3.8: "When a `Technologist` transmits a `QUEUED` study (any other
    state answers `ERR_STUDY_NOT_TRANSFERRABLE`), the system computes the
    transfer budget as sixty seconds of transfer at the measured uplink: the
    floor of the site day checklist's `measured_uplink_mbps` multiplied by 7.5,
    in megabytes. A study whose `size_mb` is within the budget — the boundary
    is inclusive — passes through `TRANSMITTING` inside the call and lands
    `DELIVERED`, with `delivered_at` stamped from the logical clock; a study
    over budget lands `TRANSFER_FAILED`. Either way `transfer_attempts`
    increments by one. A failed study is not dead: a `Technologist` may retry
    it, returning `TRANSFER_FAILED` → `QUEUED`".

    Design: Difficulty/non_linear_state_machine/image_study_transmit_fail_retry_cycle
    """
    bundle, _appt, study = _setup_completed_appointment_with_study(api, size_mb=800)
    tech_headers = make_technologist_headers(bundle["technologist"]["id"])

    # 800 > floor(100 * 7.5) = 750 -> over budget.
    tx1 = validate_success(api.transmit_image_study(study["id"], tech_headers))
    assert tx1["status"] == "TRANSFER_FAILED", (
        f"800 MB over the 750 MB budget must fail, got {tx1['status']}"
    )
    assert tx1["transfer_attempts"] == 1

    retry = validate_success(api.retry_image_study(study["id"], tech_headers))
    assert retry["status"] == "QUEUED", (
        f"Retry must return the study to QUEUED, got {retry['status']}"
    )


def test_transmit_after_uplink_improvement_delivers(api):
    """PRD §3.8: "When a `Technologist` transmits a `QUEUED` study (any other
    state answers `ERR_STUDY_NOT_TRANSFERRABLE`), the system computes the
    transfer budget as sixty seconds of transfer at the measured uplink: the
    floor of the site day checklist's `measured_uplink_mbps` multiplied by 7.5,
    in megabytes."
    PRD §3.4: "Failed items are not fatal — a `Technologist` re-records a
    single item by naming its `item_key`, the new `passed` value, and, where
    applicable, a `measured_value` that overwrites `measured_amps` for the
    `POWER_VERIFY` item or `measured_uplink_mbps` for the `NETWORK_LINK` item".

    Design: Difficulty/non_linear_state_machine/image_study_transmit_fail_retry_cycle
    """
    bundle, _appt, study = _setup_completed_appointment_with_study(api, size_mb=800)
    tech = bundle["technologist"]
    tech_headers = make_technologist_headers(tech["id"])

    tx1 = validate_success(api.transmit_image_study(study["id"], tech_headers))
    assert tx1["status"] == "TRANSFER_FAILED"
    get_success_data(api.retry_image_study(study["id"], tech_headers))

    # Re-record the uplink at 200 Mbps: budget floor(200 * 7.5) = 1500 >= 800.
    record_checklist_item(
        bundle["checklist"]["id"], tech["id"], "NETWORK_LINK", True, measured_value=200
    )
    tx2 = validate_success(api.transmit_image_study(study["id"], tech_headers))
    assert tx2["status"] == "DELIVERED", (
        f"Within the enlarged budget the retry must deliver, got {tx2['status']}"
    )
    assert tx2["transfer_attempts"] == 2


def test_transmit_delivered_study_again_rejected(api):
    """PRD §3.8: "When a `Technologist` transmits a `QUEUED` study (any other
    state answers `ERR_STUDY_NOT_TRANSFERRABLE`)".

    Design: Corner/errors/transmit_delivered_study_again_rejected
    """
    bundle, _appt, study = _setup_completed_appointment_with_study(api, size_mb=500)
    tech_headers = make_technologist_headers(bundle["technologist"]["id"])
    delivered = validate_success(api.transmit_image_study(study["id"], tech_headers))
    assert delivered["status"] == "DELIVERED"

    resp = api.transmit_image_study(study["id"], tech_headers)
    validate_error(resp, ApiErrorId.ERR_STUDY_NOT_TRANSFERRABLE)


def test_acknowledge_transfer_failed_study_returns_invalid_state(api):
    """PRD §3.8: "The loop closes when a `ReadingRadiologist` acknowledges a
    `DELIVERED` study (`ERR_INVALID_STATE` from any other state), optionally
    attaching `reader_notes`."

    Design: Corner/state_machines/acknowledge_transfer_failed_study_returns_invalid_state
    """
    bundle, _appt, study = _setup_completed_appointment_with_study(api, size_mb=800)
    tech_headers = make_technologist_headers(bundle["technologist"]["id"])
    failed = validate_success(api.transmit_image_study(study["id"], tech_headers))
    assert failed["status"] == "TRANSFER_FAILED"

    resp = api.acknowledge_image_study(study["id"], {"reader_notes": "n/a"}, RADIOLOGIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_sla_breach_strictly_greater_than_120_minutes(api):
    """PRD §3.8: "Acknowledgement stamps `acknowledged_at` from the logical
    clock and computes the turnaround flag: `sla_breached` is true exactly when
    the elapsed time from the appointment's `completed_at` to
    `acknowledged_at` is strictly greater than 120 minutes."

    Design: Corner/calculations/sla_breach_strictly_greater_than_120_minutes
    """
    bundle = setup_in_service_day(billing_model="PER_SCAN", uplink_mbps=100)
    day = bundle["site_day"]
    ap1 = book_appointment(day["id"], bundle["facility"]["id"], "P-001", scheduled_start="09:00")
    ap2 = book_appointment(day["id"], bundle["facility"]["id"], "P-002", scheduled_start="09:40")

    set_clock("2026-08-04T10:00:00Z")
    complete_appointment_flow(bundle, ap1)  # completed_at == 10:00
    complete_appointment_flow(bundle, ap2)  # completed_at == 10:00
    st1 = register_and_transmit_study(bundle, ap1["id"], "1.1.1.1", 500)
    st2 = register_and_transmit_study(bundle, ap2["id"], "2.2.2.2", 500)

    set_clock("2026-08-04T12:00:00Z")  # exactly +120 minutes
    ack1 = validate_success(api.acknowledge_image_study(st1["id"], {}, RADIOLOGIST))
    assert ack1["sla_breached"] is False, (
        "Acknowledged exactly 120 minutes after completed_at must not breach"
    )

    set_clock("2026-08-04T12:01:00Z")  # +121 minutes
    ack2 = validate_success(api.acknowledge_image_study(st2["id"], {}, RADIOLOGIST))
    assert ack2["sla_breached"] is True, (
        "Acknowledged 121 minutes after completed_at must breach"
    )


def test_technologist_cannot_acknowledge_image(api):
    """PRD §2.1: "A request whose role is declared but not permitted for the
    targeted endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: the image-study acknowledge row names ReadingRadiologist as the
    only authorized role.

    Design: Corner/rbac/technologist_cannot_acknowledge_image
    """
    bundle, _appt, study = _setup_completed_appointment_with_study(api, size_mb=500)
    tech_headers = make_technologist_headers(bundle["technologist"]["id"])
    delivered = validate_success(api.transmit_image_study(study["id"], tech_headers))
    assert delivered["status"] == "DELIVERED"

    resp = api.acknowledge_image_study(study["id"], {}, tech_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_mutation_response_reflects_new_state_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.5: "The same staffed-technologist rule guards scan completion, which
    moves `SCANNING` → `COMPLETED` and stamps `completed_at` from the logical
    clock."

    Design: Corner/consistency_model/mutation_response_reflects_new_state_immediately
    """
    bundle = setup_in_service_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    tech_headers = make_technologist_headers(bundle["technologist"]["id"])
    appt = book_appointment(day["id"], bundle["facility"]["id"], "P-001")
    get_success_data(api.confirm_appointment(appt["id"], OPS))

    set_clock("2026-08-04T10:00:00Z")
    get_success_data(
        api.check_in_appointment(
            appt["id"], make_facility_coordinator_headers(bundle["facility"]["id"])
        )
    )
    get_success_data(api.begin_scan_appointment(appt["id"], tech_headers))

    resp = api.complete_scan_appointment(appt["id"], tech_headers)
    data = validate_success(resp)
    assert data["status"] == "COMPLETED", (
        f"Mutation response must carry the new state, got {data['status']}"
    )
    assert str(data["completed_at"]).startswith("2026-08-04T10:00"), (
        f"completed_at must be stamped from the logical clock, got {data['completed_at']}"
    )
