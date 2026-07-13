"""Intake creation, not-found reads, body validation, and the repeat-caller registry."""
from test_helpers import (
    api_client as api,
    validate_success, validate_error, validate_paginated,
    create_contact_payload, TEST_USERS,
    create_contact,
)

COUNSELOR = TEST_USERS["counselor_headers"]
SUP = TEST_USERS["supervisor_headers"]


def test_create_contact_returns_201_intake():
    """PRD §3.1: "A newly created contact enters the lifecycle in `INTAKE` status."
    PRD §3.1: "`has_active_safety_plan` starts false, `emergency_status` starts `NONE`."

    Design: Corner/entities/contact_create_returns_201_with_intake_status
    """
    res = api.create_contact(
        create_contact_payload(channel="PHONE", caller_key="cr-01", caller_name="Jordan"), COUNSELOR
    )
    contact = validate_success(res, 201)
    assert contact["status"] == "INTAKE", f"expected INTAKE, got {contact['status']}"
    assert contact["emergency_status"] == "NONE", (
        f"expected NONE emergency_status at intake, got {contact['emergency_status']}"
    )


def test_get_nonexistent_contact_returns_not_found():
    """PRD §2.8: "existence of every referenced resource — each path id and each foreign key in the body, checked left to right, yielding the matching not-found error"

    Design: Corner/entities/contact_get_nonexistent_returns_not_found
    """
    res = api.get_contact("00000000-0000-0000-0000-000000000000", COUNSELOR)
    validate_error(res, "ERR_CONTACT_NOT_FOUND", expected_status=404)


def test_create_contact_missing_channel_returns_validation():
    """PRD §2.8: "body-field validity — required fields present and well-formed (`ERR_VALIDATION`), enum fields carrying an allowed value (`ERR_INVALID_ENUM`), and dated windows satisfying end-after-start (`ERR_WINDOW_INVALID`)"

    Design: Corner/entities/contact_create_missing_channel_returns_validation
    """
    res = api.create_contact({"caller_key": "mc-01"}, COUNSELOR)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_repeat_caller_registered_and_counted_on_intake():
    """PRD §3.1: "if no entry exists one is created (its `registry_status` is always `ACTIVE`), and its `contact_count` — the number of contacts sharing this `caller_key` — is recomputed to include the new contact."
    PRD §3.1: "it is true when the `contact_count` is at least 3, or when the caller's `last_risk_band` is `IMMINENT`; otherwise it is false."

    Design: Corner/entities/repeat_caller_registered_and_counted_on_intake
    """
    create_contact("rc-9", channel="PHONE")
    create_contact("rc-9", channel="PHONE")

    rows, meta = validate_paginated(api.list_repeat_callers(SUP, params={"caller_key": "rc-9"}))
    assert meta["total_count"] == 1, f"expected exactly 1 registry row, got {meta['total_count']}"
    rc = rows[0]
    assert rc["contact_count"] == 2, f"expected contact_count 2, got {rc['contact_count']}"
    assert rc["high_risk_flag"] is False, (
        f"unscreened caller with count 2 must not be high-risk, got {rc['high_risk_flag']}"
    )
