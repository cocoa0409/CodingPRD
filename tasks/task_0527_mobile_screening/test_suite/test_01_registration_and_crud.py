"""Entity creation, required-field, default, and listing checks (Corner: entities section)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_mobile_unit_payload, create_participant_payload,
    fixtures,
)

PM = TEST_USERS["program_manager_headers"]


def test_create_mobile_unit_returns_201_with_system_fields(api):
    """PRD §3.1: "A newly created unit has `status` `AVAILABLE`; retiring a unit moves
    it from `AVAILABLE` to `RETIRED`."
    PRD §2.4: "a `version` integer that begins at its initial value on creation and
    increments by exactly one on every mutation."
    PRD §4: "Operations that create a new, stand-alone resource return `201 Created`."

    Design: Corner/entities/create_mobile_unit_returns_201_with_system_fields
    """
    resp = api.create_mobile_unit(
        create_mobile_unit_payload(name="Van A", modality="MAMMOGRAPHY", daily_capacity=10), PM
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "AVAILABLE", f"expected AVAILABLE, got {data['status']}"
    assert data["version"] == 1, f"expected version 1 at creation, got {data['version']}"


def test_create_appointment_missing_required_field_returns_invalid_request(api):
    """PRD §3.4: "A `ProgramManager` or `ClinicalStaff` member books an **appointment**
    by supplying the `event_id` of a published event, the `participant_id` of the person
    being screened, a `slot_start_min` (minutes-from-midnight at which the appointment
    starts), and a `slot_duration_min` (the slot length in minutes, at least 1)."
    PRD §3.4: "Any missing or mistyped body field, or an out-of-range value, is rejected
    first as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_appointment_missing_required_field_returns_invalid_request
    """
    _, _, event = fixtures.create_published_event(modality="BLOOD_PANEL")
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    # Omit slot_duration_min (required)
    resp = api.create_appointment(
        {"event_id": event["id"], "participant_id": participant["id"], "slot_start_min": 540}, PM
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_participant_insurance_without_member_id_returns_invalid_request(api):
    """PRD §3.3: "When `pay_type` is `INSURANCE`, an `insurance_member_id` is required;
    when `pay_type` is `GRANT`, a `grant_id` referencing the funding grant is required;
    each is otherwise optional."

    Design: Corner/entities/create_participant_insurance_without_member_id_returns_invalid_request
    """
    resp = api.create_participant(
        {"full_name": "P1", "date_of_birth": "1980-01-01", "pay_type": "INSURANCE"}, PM
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_event_nonexistent_returns_not_found(api):
    """PRD §2.5: "A missing resource yields a 404 error — the resource-specific code where
    one exists (`ERR_UNIT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`,
    `ERR_REMINDER_NOT_FOUND`) and the generic `ERR_NOT_FOUND` otherwise."

    Design: Corner/entities/get_event_nonexistent_returns_not_found
    """
    resp = api.get_event("00000000-0000-4000-8000-000000000000", PM)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND.value)


def test_create_participant_grant_defaults_strikes_zero_status_active(api):
    """PRD §3.3: "A participant begins with `no_show_strikes` at 0 and `status` `ACTIVE`."

    Design: Corner/entities/create_participant_grant_defaults_strikes_zero_status_active
    """
    sponsor = fixtures.create_sponsor(sponsor_type="GRANT", viewer_user_id="sv2", name="GrantBody")
    grant = fixtures.create_grant(sponsor["id"], total_budget_cents=10000)
    resp = api.create_participant(
        create_participant_payload(full_name="Pat G", date_of_birth="1975-01-01",
                                   pay_type="GRANT", grant_id=grant["id"]),
        PM,
    )
    data = validate_success(resp, expected_status=201)
    assert data["no_show_strikes"] == 0, f"expected 0 strikes, got {data['no_show_strikes']}"
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"


def test_list_participants_pagination_envelope(api):
    """PRD §2.3: "List responses include the following fields in the `meta` object of the
    envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10
    when omitted, with a minimum of 1 and a maximum of 100."

    Design: Corner/entities/list_participants_pagination_envelope
    """
    fixtures.register_participant(pay_type="SELF_PAY", full_name="P1")
    fixtures.register_participant(pay_type="SELF_PAY", full_name="P2", date_of_birth="1981-01-01")
    resp = api.list_participants(PM, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more True, got {meta['has_more']}"
