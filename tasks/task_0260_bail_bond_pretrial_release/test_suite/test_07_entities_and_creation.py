"""Corner: entity creation, defaults, type constraints, not-found, and append-only
immutability.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, api_client,
    assert_defendant, assert_notification,
    setup_draft_surety_bond,
    pin_clock, NON_EXISTENT_UUID,
    TEST_USERS,
)

AGENT = TEST_USERS["bonds_agent_headers"]
COURT = TEST_USERS["court_headers"]


# Corner/entities/create_defendant_returns_201_with_fields
def test_create_defendant_returns_201_with_computed_fields(api):
    """PRD 3.1: "Two fields on a defendant are computed and never accepted from the
    client: `total_active_exposure_cents`, which begins at 0 and tracks the agency's
    live exposure to this defendant, and `status`, which begins as `ACTIVE` and is
    one of `ACTIVE` or `CLEARED`."

    Design: Corner/entities/create_defendant_returns_201_with_fields
    """
    resp = api.create_defendant(
        {"full_name": "Ann Ze", "date_of_birth": "1990-01-01", "phone_e164": "+15551110000", "risk_tier": "LOW"}, AGENT)
    data = validate_success(resp, expected_status=201)
    assert_defendant(data)
    assert data["total_active_exposure_cents"] == 0, data["total_active_exposure_cents"]
    assert data["status"] == "ACTIVE", data["status"]


# Corner/entities/get_defendant_not_found
def test_get_defendant_unknown_id_not_found(api):
    """PRD 2.5: "The system validates these identifiers left to right and rejects
    the request at the first identifier that does not resolve to an existing
    resource, returning `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_defendant_not_found
    """
    resp = api.get_defendant(NON_EXISTENT_UUID, AGENT)
    validate_error(resp, "ERR_NOT_FOUND")


# Corner/entities/create_bail_order_missing_required_field
def test_create_bail_order_missing_bail_amount_rejected(api):
    """PRD 2.6: "then structural validity of the body (`ERR_INVALID_REQUEST`,
    HTTP 400 — a required field absent, a value of the wrong type, or an enum value
    outside its declared set)."

    Omitting bail_amount_cents (a required field) -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_bail_order_missing_required_field
    """
    defendant = get_success_data(api_client.create_defendant(
        {"full_name": "Bob Yu", "date_of_birth": "1991-02-02", "phone_e164": "+15551110001"}, AGENT))
    resp = api.create_bail_order(defendant["id"], {"case_number": "CR-X1", "bond_type_allowed": "SURETY"}, COURT)
    validate_error(resp, "ERR_INVALID_REQUEST")


# Corner/entities/defendant_default_risk_tier_applied
def test_defendant_default_risk_tier_is_medium(api):
    """PRD 3.1: "A `risk_tier` may be supplied; when it is omitted it defaults to
    `MEDIUM`, and it must be one of `LOW`, `MEDIUM`, or `HIGH`."

    Design: Corner/entities/defendant_default_risk_tier_applied
    """
    data = validate_success(api.create_defendant(
        {"full_name": "Cy Xa", "date_of_birth": "1992-03-03", "phone_e164": "+15551110002"}, AGENT),
        expected_status=201)
    assert data["risk_tier"] == "MEDIUM", data["risk_tier"]


# Corner/entities/bond_invalid_enum_bond_type
def test_bond_invalid_enum_bond_type_rejected(api):
    """PRD 2.6: "an enum value outside its declared set" -> ERR_INVALID_REQUEST.
    PRD 3.2: "the agent chooses the `bond_type` — one of `CASH`, `SURETY`, or `PR`."

    Posting bond_type "BAILEY" (outside the set) -> ERR_INVALID_REQUEST.

    Design: Corner/entities/bond_invalid_enum_bond_type
    """
    defendant = get_success_data(api_client.create_defendant(
        {"full_name": "Dee Wb", "date_of_birth": "1993-04-04", "phone_e164": "+15551110003"}, AGENT))
    order = get_success_data(api_client.create_bail_order(
        defendant["id"], {"case_number": "CR-X2", "bail_amount_cents": 500000, "bond_type_allowed": "ANY"}, COURT))
    resp = api.create_bond(defendant["id"], order["id"], {"bond_type": "BAILEY"}, AGENT)
    validate_error(resp, "ERR_INVALID_REQUEST")


# Corner/entities/notification_immutable_no_version_field
def test_notification_is_append_only_with_destination(api):
    """PRD 2.4: "a `Notification`, a `CheckIn`, and a `LedgerEntry` have no
    `updated_at` and no `version`, because they are never modified after they are
    written."
    PRD 3.5: "copies the defendant's `phone_e164` into its `destination`."

    Design: Corner/entities/notification_immutable_no_version_field
    """
    pin_clock("2026-07-01T00:00:00Z")
    scen = setup_draft_surety_bond(bail_amount_cents=500000, with_indemnity=False,
                                   with_collateral=False)
    cd = get_success_data(api_client.create_court_date(
        scen["def_id"], scen["bond_id"], {"scheduled_utc": "2026-07-10T09:00:00Z", "duration_minutes": 60}, COURT))
    get_success_data(api_client.notify_court_date(scen["def_id"], cd["id"], {"channel": "SMS"}, COURT))
    notifs, _ = validate_paginated(api.list_notifications(cd["id"], COURT))
    assert len(notifs) == 1, notifs
    note = notifs[0]
    assert_notification(note)
    assert note["destination"] == scen["defendant"]["phone_e164"], (note["destination"], scen["defendant"]["phone_e164"])
