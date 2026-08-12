"""Capture sites, scanners, roster windows and the onsite event close-out."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_device,
    assert_device_assignment,
    assert_same_instant,
    check_in,
    create_device_assignment_payload,
    create_mobile_event_payload,
    finalize_card,
    new_agency,
    new_appointment,
    new_applicant,
    new_device,
    new_device_assignment,
    new_fixed_site,
    new_mobile_event,
    open_card,
    pass_positions,
    score_position,
    set_clock,
    setup_checked_in_appointment,
    setup_mobile_registry,
    setup_registry,
    transmit_card,
    validate_error,
    validate_paginated,
    validate_success,
)

VA = TEST_USERS["vendor_admin_headers"]
TECH = TEST_USERS["technician_headers"]
SUP = TEST_USERS["supervisor_headers"]


def _device_with_morning_roster():
    """One device carrying a SCHEDULED window of 09:00-12:00 on 2026-06-02."""
    set_clock("2026-06-01T08:00:00Z")
    agency = new_agency()
    depot = new_fixed_site(name="Depot")
    event_site = new_mobile_event(
        agency["id"],
        name="Afternoon Event",
        concurrent_capacity=3,
        event_window_start="2026-06-02T12:00:00Z",
        event_window_end="2026-06-02T18:00:00Z",
        min_billable_prints=5,
    )
    device = new_device(depot["id"], calibrated_at="2026-05-15T00:00:00Z")
    first = new_device_assignment(
        device["id"],
        depot["id"],
        window_start="2026-06-02T09:00:00Z",
        window_end="2026-06-02T12:00:00Z",
    )
    return {"agency": agency, "depot": depot, "event_site": event_site, "device": device, "first": first}


def test_roster_window_twenty_nine_minutes_after_another_conflicts(api):
    """PRD 3.2: "A candidate roster window conflicts with an existing entry for the same device
    whose `status` is `SCHEDULED` or `ACTIVE` when the candidate's `window_start` falls strictly
    before that entry's `window_end` extended by 30 minutes, **and** the candidate's `window_end`
    extended by 30 minutes falls strictly after that entry's `window_start`."
    PRD 3.2: "The buffer boundary is strict in the operator's favour: a gap of exactly 30 minutes
    between two windows is accepted, a gap of 29 minutes is refused with
    `ERR_DEVICE_ASSIGNMENT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/device_roster_windows_need_a_thirty_minute_buffer
    """
    fixture = _device_with_morning_roster()

    response = api.create_device_assignment(
        create_device_assignment_payload(
            fixture["device"]["id"],
            fixture["event_site"]["id"],
            window_start="2026-06-02T12:29:00Z",
            window_end="2026-06-02T14:00:00Z",
        ),
        SUP,
    )

    validate_error(response, ApiErrorId.ERR_DEVICE_ASSIGNMENT_CONFLICT.value)

    _rows, meta = validate_paginated(
        api.list_device_assignments(SUP, {"device_id": fixture["device"]["id"]})
    )
    assert meta["total_count"] == 1, "the refused candidate is not persisted"


def test_roster_window_exactly_thirty_minutes_after_another_is_accepted(api):
    """PRD 3.2: "The buffer boundary is strict in the operator's favour: a gap of exactly 30 minutes
    between two windows is accepted, a gap of 29 minutes is refused with
    `ERR_DEVICE_ASSIGNMENT_CONFLICT`."
    PRD 3.2: "At creation it also copies the device's `calibration_expires_at` into
    `calibration_expires_at_snapshot` — a historical record only."

    Design: Difficulty/resource_temporal_overlap/device_roster_windows_need_a_thirty_minute_buffer
    """
    fixture = _device_with_morning_roster()

    second = validate_success(
        api.create_device_assignment(
            create_device_assignment_payload(
                fixture["device"]["id"],
                fixture["event_site"]["id"],
                window_start="2026-06-02T12:30:00Z",
                window_end="2026-06-02T14:00:00Z",
            ),
            SUP,
        ),
        201,
    )

    assert_device_assignment(second)
    assert second["status"] == "SCHEDULED"
    assert_same_instant(
        second["calibration_expires_at_snapshot"],
        "2026-11-11T00:00:00Z",
        "calibration_expires_at_snapshot",
    )

    first = validate_success(api.get_device_assignment(fixture["first"]["id"], SUP), 200)
    assert first["status"] == "SCHEDULED"

    _rows, meta = validate_paginated(
        api.list_device_assignments(SUP, {"device_id": fixture["device"]["id"]})
    )
    assert meta["total_count"] == 2


def test_mobile_event_site_without_its_window_is_rejected(api):
    """PRD 2.9 rung 5: "A site created with `site_kind` `MOBILE_EVENT` supplies all four of
    `host_agency_id`, `event_window_start`, `event_window_end` and `min_billable_prints`; a site
    created with `site_kind` `FIXED` supplies none of the four. Violations raise
    `ERR_INVALID_REQUEST`, HTTP 400."

    Design: Corner/entities/create_mobile_event_site_without_window_returns_invalid_request
    """
    set_clock("2026-06-01T09:00:00Z")
    agency = new_agency()

    payload = create_mobile_event_payload(agency["id"], name="Half-declared event", concurrent_capacity=3)
    for field in ("event_window_start", "event_window_end", "min_billable_prints"):
        payload.pop(field)
    response = api.create_site(payload, VA)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _rows, meta = validate_paginated(api.list_sites(VA, {"host_agency_id": agency["id"]}))
    assert meta["total_count"] == 0


def test_recalibrating_a_quarantined_device_restores_it_and_pushes_the_expiry(api):
    """PRD 3.8: "1. The device's `last_calibrated_at` is rewritten to
    `corrected_last_calibrated_at`, its `calibration_expires_at` is recomputed as that instant plus
    180 days, and its `calibration_status` moves `CALIBRATED → QUARANTINED`."
    PRD 3.2: "Recording a fresh calibration takes a new `calibrated_at` and is admitted only when
    the device's `calibration_status` is `EXPIRED` or `QUARANTINED`; it moves the device
    `EXPIRED → CALIBRATED` or `QUARANTINED → CALIBRATED`, rewrites `last_calibrated_at` to the
    supplied instant and `calibration_expires_at` to that instant plus 180 days."

    Design: Corner/state_machines/device_recalibration_returns_a_quarantined_device_to_calibrated
    """
    set_clock("2026-06-01T09:00:00Z")
    new_agency()
    site = new_fixed_site()
    device = new_device(site["id"], calibrated_at="2026-05-15T00:00:00Z")

    set_clock("2026-06-10T00:00:00Z")
    audited = validate_success(
        api.run_calibration_audit(device["id"], "2025-11-01T00:00:00Z", VA), 200
    )
    assert audited["calibration_status"] == "QUARANTINED"

    recalibrated = validate_success(
        api.record_calibration(device["id"], "2026-06-10T00:00:00Z", VA), 200
    )

    assert_device(recalibrated)
    assert recalibrated["calibration_status"] == "CALIBRATED"
    assert_same_instant(
        recalibrated["calibration_expires_at"], "2026-12-07T00:00:00Z", "calibration_expires_at"
    )
    assert_same_instant(
        recalibrated["last_calibrated_at"], "2026-06-10T00:00:00Z", "last_calibrated_at"
    )
    assert recalibrated["tainted_card_count"] == 0
    assert recalibrated["capture_count"] == 0


def test_event_that_meets_its_minimum_is_charged_nothing(api):
    """PRD 3.2: "The shortfall is the event's `min_billable_prints` less the recomputed
    `billable_print_count`, floored at zero, multiplied by 2200 cents per missing print, and the
    result is stamped as `shortfall_charge_cents`."
    PRD 3.2: "When the shortfall is above zero, the reconciliation creates exactly one fee
    assessment whose `assessment_kind` is `ONSITE_SHORTFALL` and whose `payer_regime` is
    `AGENCY_BILLED`; when the shortfall is exactly zero, it creates none."

    Design: Corner/calculations/onsite_shortfall_is_zero_when_the_event_minimum_is_met
    """
    world = setup_mobile_registry(
        clock_start="2026-06-02T08:00:00Z",
        agency_overrides={"payer_regime_default": "AGENCY_BILLED"},
        event_overrides={"name": "Met Minimum Day", "min_billable_prints": 1},
    )
    setup_checked_in_appointment(
        world,
        scheduled_start="2026-06-02T10:00:00Z",
        checkin_clock="2026-06-02T09:55:00Z",
        site_key="event_site",
    )
    world["card"] = open_card(world["appointment"]["id"], world["device"]["id"])
    pass_positions(world["card"]["id"], 80)
    world["card"] = finalize_card(world["card"]["id"])
    transmit_card(world["card"]["id"], world["card"]["version"])

    set_clock("2026-06-02T17:30:00Z")
    reconciled = validate_success(api.reconcile_event(world["event_site"]["id"], VA), 200)

    assert reconciled["shortfall_charge_cents"] == 0
    assert reconciled["reconciliation_status"] == "RECONCILED"
    assert reconciled["billable_print_count"] == 1

    _rows, meta = validate_paginated(
        api.list_fee_assessments(
            VA, {"agency_id": world["agency"]["id"], "assessment_kind": "ONSITE_SHORTFALL"}
        )
    )
    assert meta["total_count"] == 0, "a zero shortfall creates no assessment at all"


def test_reconciliation_releases_the_roster_and_the_trip_surcharge_stands(api):
    """PRD 3.2: "Finally, every roster entry at that site whose `status` is `SCHEDULED` or `ACTIVE`
    is moved to `RELEASED`."
    PRD 3.9: "`trip_surcharge_cents` is 500 cents when the capture site's `site_kind` is
    `MOBILE_EVENT` and the row is a `SUBMISSION` or `REPRINT`, and 0 otherwise."

    Design: Corner/calculations/onsite_shortfall_is_zero_when_the_event_minimum_is_met
    """
    world = setup_mobile_registry(
        clock_start="2026-06-02T08:00:00Z",
        agency_overrides={"payer_regime_default": "AGENCY_BILLED"},
        event_overrides={"name": "Met Minimum Day", "min_billable_prints": 1},
    )
    setup_checked_in_appointment(
        world,
        scheduled_start="2026-06-02T10:00:00Z",
        checkin_clock="2026-06-02T09:55:00Z",
        site_key="event_site",
    )
    world["card"] = open_card(world["appointment"]["id"], world["device"]["id"])
    pass_positions(world["card"]["id"], 80)
    world["card"] = finalize_card(world["card"]["id"])
    submission = transmit_card(world["card"]["id"], world["card"]["version"])

    set_clock("2026-06-02T17:30:00Z")
    validate_success(api.reconcile_event(world["event_site"]["id"], VA), 200)

    assignment = validate_success(api.get_device_assignment(world["assignment"]["id"], SUP), 200)
    assert assignment["status"] == "RELEASED"

    rows, meta = validate_paginated(
        api.list_fee_assessments(VA, {"submission_id": submission["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["trip_surcharge_cents"] == 500
    assert rows[0]["total_cents"] == 6368


def test_capture_attempt_on_a_lapsed_device_is_refused(api):
    """PRD 3.2: "The device's `calibration_status` starts at `CALIBRATED` and is re-derived against
    the logical clock on every read and on every capture attempt: once the clock passes
    `calibration_expires_at`, the device reads `EXPIRED` and further capture attempts on it are
    refused with `ERR_DEVICE_CALIBRATION_EXPIRED`."

    Design: Corner/validations/capture_is_refused_on_an_expired_device_and_on_an_unrostered_event_device
    """
    world = setup_checked_in_appointment(clock_start="2026-06-01T09:00:00Z")
    world["card"] = open_card(world["appointment"]["id"], world["device"]["id"])
    score_position(world["card"]["id"], "R_THUMB", 80)

    device_before = validate_success(api.get_device(world["device"]["id"], VA), 200)
    assert_same_instant(
        device_before["calibration_expires_at"], "2026-11-11T00:00:00Z", "calibration_expires_at"
    )

    set_clock("2026-11-12T00:00:00Z")
    response = api.record_attempt(world["card"]["id"], "R_INDEX", 80, TECH)

    validate_error(response, ApiErrorId.ERR_DEVICE_CALIBRATION_EXPIRED.value)


def test_card_at_a_mobile_event_needs_a_roster_entry_for_its_device(api):
    """PRD 2.9 rung 20: "**Mobile-event device binding.** When the card's site has `site_kind`
    `MOBILE_EVENT`, a device assignment whose `status` is `SCHEDULED` or `ACTIVE` binds that device
    to that site and the logical clock lies inside that assignment's window. Otherwise
    `ERR_DEVICE_ASSIGNMENT_CONFLICT`, HTTP 409."

    Design: Corner/validations/capture_is_refused_on_an_expired_device_and_on_an_unrostered_event_device
    """
    world = setup_registry(clock_start="2026-06-01T09:00:00Z")
    event_site = new_mobile_event(
        world["agency"]["id"],
        name="Unrostered Event",
        concurrent_capacity=3,
        event_window_start="2026-11-20T09:00:00Z",
        event_window_end="2026-11-20T17:00:00Z",
        min_billable_prints=5,
    )
    applicant = new_applicant(full_name="Lou Vane", id_document_expires_on="2033-09-09")
    appointment = new_appointment(
        applicant["id"], event_site["id"], world["service_type"]["id"], "2026-11-20T10:00:00Z"
    )

    set_clock("2026-11-12T00:00:00Z")
    validate_success(api.record_calibration(world["device"]["id"], "2026-11-12T00:00:00Z", VA), 200)
    set_clock("2026-11-20T09:55:00Z")
    check_in(appointment["id"])

    response = api.create_card(
        {"appointment_id": appointment["id"], "device_id": world["device"]["id"]}, TECH
    )

    validate_error(response, ApiErrorId.ERR_DEVICE_ASSIGNMENT_CONFLICT.value)

    _rows, meta = validate_paginated(api.list_cards(TECH, {"appointment_id": appointment["id"]}))
    assert meta["total_count"] == 0

    unchanged = validate_success(api.get_appointment(appointment["id"], TECH), 200)
    assert unchanged["status"] == "CHECKED_IN"
