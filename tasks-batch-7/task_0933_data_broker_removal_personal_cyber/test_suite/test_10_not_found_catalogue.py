"""Every resource family's own 404 code, path parameters and body foreign keys
alike."""
from test_helpers import (
    validate_error, validate_paginated, ApiErrorId, fixtures as fx,
)

def test_an_unknown_plan_id_on_account_creation_is_not_found(api):
    """PRD §2.5: "Foreign keys supplied inside a request body are resolved as well, and
    carry their own codes. A `plan_id` or `new_plan_id` that does not resolve yields
    `ERR_PLAN_NOT_FOUND`; a `member_id` yields `ERR_MEMBER_NOT_FOUND`; a `profile_id` yields
    `ERR_PROFILE_NOT_FOUND`; a `broker_id` yields `ERR_BROKER_NOT_FOUND`; an `exposure_id`
    yields `ERR_EXPOSURE_NOT_FOUND`; and an `addon_id` yields `ERR_ADDON_NOT_FOUND`. All are
    HTTP 404."

    Design: Corner/errors/unknown_plan_id_on_account_create_returns_not_found
    """
    response = api.create_account(
        {"plan_id": "00000000-0000-4000-8000-000000000001",
         "primary_member_email": "o@example.com", "primary_member_full_name": "O"},
        fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_PLAN_NOT_FOUND.value, 404)
    _, meta = validate_paginated(api.list_accounts(fx.ADMIN))
    assert meta["total_count"] == 0


def test_an_unknown_member_id_in_the_path_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_member_id_path_returns_not_found
    """
    response = api.get_member("00000000-0000-4000-8000-000000000002", fx.ADMIN)
    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, 404)


def test_an_unknown_profile_id_in_the_path_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_profile_id_path_returns_not_found
    """
    response = api.get_monitored_profile("00000000-0000-4000-8000-000000000003", fx.ADMIN)
    validate_error(response, ApiErrorId.ERR_PROFILE_NOT_FOUND.value, 404)


def test_retiring_an_unknown_broker_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."
    PRD §2.6: "5. Every `{id}` path segment resolves to an existing row, validated left to
    right — otherwise the family-specific 404 code from §2.5. Applies to every endpoint with
    a path parameter."

    Design: Corner/errors/unknown_broker_id_on_retire_returns_not_found
    """
    response = api.retire_broker("00000000-0000-4000-8000-000000000004", fx.ADMIN)
    validate_error(response, ApiErrorId.ERR_BROKER_NOT_FOUND.value, 404)


def test_an_unknown_scan_id_in_the_path_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_scan_id_path_returns_not_found
    """
    response = api.get_scan_run("00000000-0000-4000-8000-000000000005", fx.AGENT)
    validate_error(response, ApiErrorId.ERR_SCAN_NOT_FOUND.value, 404)


def test_an_unknown_exposure_id_in_the_path_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_exposure_id_path_returns_not_found
    """
    response = api.get_exposure("00000000-0000-4000-8000-000000000006", fx.AGENT)
    validate_error(response, ApiErrorId.ERR_EXPOSURE_NOT_FOUND.value, 404)


def test_an_unknown_removal_request_id_in_the_path_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_removal_request_id_path_returns_not_found
    """
    response = api.get_removal_request("00000000-0000-4000-8000-000000000007", fx.AGENT)
    validate_error(response, ApiErrorId.ERR_REMOVAL_REQUEST_NOT_FOUND.value, 404)


def test_verifying_an_unknown_identity_document_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_document_id_on_verify_returns_not_found
    """
    response = api.verify_identity_document("00000000-0000-4000-8000-000000000008",
                                            fx.AGENT)
    validate_error(response, ApiErrorId.ERR_DOCUMENT_NOT_FOUND.value, 404)


def test_ingesting_against_an_unknown_breach_event_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_breach_event_id_on_ingest_returns_not_found
    """
    response = api.ingest_breach_event("00000000-0000-4000-8000-000000000009",
                                       ["x@example.com"], fx.ADMIN)
    validate_error(response, ApiErrorId.ERR_BREACH_EVENT_NOT_FOUND.value, 404)
    _, meta = validate_paginated(api.list_breach_alerts(fx.ADMIN))
    assert meta["total_count"] == 0


def test_an_unknown_alert_id_in_the_path_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_alert_id_path_returns_not_found
    """
    response = api.get_breach_alert("00000000-0000-4000-8000-00000000000a", fx.AGENT)
    validate_error(response, ApiErrorId.ERR_ALERT_NOT_FOUND.value, 404)


def test_an_unknown_credential_finding_id_in_the_path_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_finding_id_path_returns_not_found
    """
    response = api.get_credential_finding("00000000-0000-4000-8000-00000000000b",
                                          fx.AGENT)
    validate_error(response, ApiErrorId.ERR_FINDING_NOT_FOUND.value, 404)


def test_an_unknown_addon_id_in_the_path_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_addon_id_path_returns_not_found
    """
    response = api.get_addon("00000000-0000-4000-8000-00000000000c", fx.ADMIN)
    validate_error(response, ApiErrorId.ERR_ADDON_NOT_FOUND.value, 404)


def test_an_unknown_device_seat_id_in_the_path_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_seat_id_path_returns_not_found
    """
    response = api.get_device_seat("00000000-0000-4000-8000-00000000000d", fx.ADMIN)
    validate_error(response, ApiErrorId.ERR_SEAT_NOT_FOUND.value, 404)


def test_closing_an_unknown_billing_cycle_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_cycle_id_on_close_returns_not_found
    """
    response = api.close_billing_cycle("00000000-0000-4000-8000-00000000000e", fx.ADMIN)
    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_FOUND.value, 404)


def test_an_unknown_ledger_entry_id_in_the_path_is_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/unknown_ledger_entry_id_path_returns_not_found
    """
    response = api.get_ledger_entry("00000000-0000-4000-8000-00000000000f", fx.ADMIN)
    validate_error(response, ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND.value, 404)
