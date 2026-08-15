"""Reference resolution (404), request-shape (400), and server-minted-id
claims (PRD 2.7, 2.9, 2.5)."""
from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    create_client,
    create_order,
    make_appraiser_headers,
    make_clientuser_headers,
    make_role_only_headers,
    set_clock,
    validate_error,
    validate_success,
    is_valid_uuid,
)
from test_helpers import ADMIN, COMPLIANCE


# ---------------------------------------------------------------------------
# 404 reference resolution (PRD 2.9)
# ---------------------------------------------------------------------------


def test_client_not_found_returns_404(api):
    """PRD 2.9: "The first unresolvable identifier rejects the request with the
    referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`,
    `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`,
    `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/entities/client_not_found_returns_404
    """
    response = api.get_client(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_CLIENT_NOT_FOUND, 404)


def test_appraiser_not_found_returns_404(api):
    """PRD 2.9: "The first unresolvable identifier rejects the request with the
    referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`,
    `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`,
    `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/entities/appraiser_not_found_returns_404
    """
    response = api.get_appraiser(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_APPRAISER_NOT_FOUND, 404)


def test_panel_membership_not_found_returns_404(api):
    """PRD 2.9: "The first unresolvable identifier rejects the request with the
    referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`,
    `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`,
    `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/entities/panel_membership_not_found_returns_404
    """
    response = api.get_panel_membership(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_PANEL_MEMBERSHIP_NOT_FOUND, 404)


def test_fee_schedule_not_found_returns_404(api):
    """PRD 2.9: "The first unresolvable identifier rejects the request with the
    referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`,
    `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`,
    `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/entities/fee_schedule_not_found_returns_404
    """
    response = api.get_fee_schedule(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_FEE_SCHEDULE_NOT_FOUND, 404)


def test_order_not_found_returns_404(api):
    """PRD 2.9: "The first unresolvable identifier rejects the request with the
    referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`,
    `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`,
    `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/entities/order_not_found_returns_404
    """
    response = api.get_order(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND, 404)


def test_appointment_not_found_returns_404(api):
    """PRD 2.9: "The first unresolvable identifier rejects the request with the
    referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`,
    `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`,
    `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/entities/appointment_not_found_returns_404
    """
    response = api.get_appointment(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND, 404)


def test_comparable_not_found_returns_404(api):
    """PRD 2.9: "The first unresolvable identifier rejects the request with the
    referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`,
    `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`,
    `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/entities/comparable_not_found_returns_404
    """
    response = api.get_comparable(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_COMPARABLE_NOT_FOUND, 404)


def test_report_not_found_returns_404(api):
    """PRD 2.9: "The first unresolvable identifier rejects the request with the
    referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`,
    `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`,
    `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/entities/report_not_found_returns_404
    """
    response = api.get_report(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_REPORT_NOT_FOUND, 404)


def test_revision_request_not_found_returns_404(api):
    """PRD 2.9: "The first unresolvable identifier rejects the request with the
    referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`,
    `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`,
    `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/entities/revision_request_not_found_returns_404
    """
    response = api.get_revision_request(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_REVISION_REQUEST_NOT_FOUND, 404)


def test_workfile_not_found_returns_404(api):
    """PRD 2.9: "The first unresolvable identifier rejects the request with the
    referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`,
    `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`,
    `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/entities/workfile_not_found_returns_404
    """
    response = api.get_workfile_record(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_WORKFILE_NOT_FOUND, 404)


def test_complaint_not_found_returns_404(api):
    """PRD 2.9: "The first unresolvable identifier rejects the request with the
    referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`,
    `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`,
    `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/entities/complaint_not_found_returns_404
    """
    response = api.get_complaint(UNKNOWN_UUID, COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_COMPLAINT_NOT_FOUND, 404)


# ---------------------------------------------------------------------------
# 400 request shape: missing required fields (PRD 2.7 step 3)
# ---------------------------------------------------------------------------


def test_client_create_missing_required_name(api):
    """PRD 2.7: "Request shape: required fields present, enum values within
    their declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.1: "creating a client with its legal `name`, a `client_type` of
    `AMC`, `DIRECT_LENDER`, or `PRIVATE`, a `contact_email`, and a
    `default_turn_time_days`".

    Design: Corner/entities/client_create_missing_required_name
    """
    response = api.create_client(
        {
            "client_type": "AMC",
            "contact_email": "c@x.example",
            "default_turn_time_days": 7,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_appraiser_create_missing_required_license_expiry(api):
    """PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.2: "creating appraisers, each with a `full_name`, a `license_level`
    of `TRAINEE`, `LICENSED`, or `CERTIFIED_RESIDENTIAL`, a state
    `license_number`, and a `license_expiry` date."

    Design: Corner/entities/appraiser_create_missing_required_license_expiry
    """
    response = api.create_appraiser(
        {"full_name": "No Expiry", "license_level": "LICENSED", "license_number": "LA-9"},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_panel_membership_create_missing_required_appraiser(api):
    """PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.1: "creating a membership carrying the `client_id` and the
    `appraiser_id`".

    Design: Corner/entities/panel_membership_create_missing_required_appraiser
    """
    response = api.create_panel_membership({"client_id": UNKNOWN_UUID}, ADMIN)
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_fee_schedule_create_missing_required_base_fee(api):
    """PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.1: "A schedule row carries the `client_id`, a `complexity_tier`
    of `STANDARD`, `COMPLEX`, or `HIGH_VALUE`, a strictly positive
    `base_fee_cents`, a `rush_multiplier_bps` between 0 and 10000 inclusive
    expressing the rush premium in basis points of the base fee, a non-negative
    `revision_fee_cents` charged when a revision request is accepted (§3.7), an
    inclusive `effective_from`, and an optional `effective_to` marking the
    exclusive end of the window — null means open-ended."

    Design: Corner/entities/fee_schedule_create_missing_required_base_fee
    """
    response = api.create_fee_schedule(
        {
            "client_id": UNKNOWN_UUID,
            "complexity_tier": "STANDARD",
            "rush_multiplier_bps": 1000,
            "revision_fee_cents": 12000,
            "effective_from": "2026-07-01T00:00:00Z",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_order_create_missing_required_loan_type(api):
    """PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.3: "a `loan_type` of `CONVENTIONAL`, `FHA`, or `VA`".

    Design: Corner/entities/order_create_missing_required_loan_type
    """
    response = api.create_order(
        {
            "client_id": UNKNOWN_UUID,
            "property_address": "1 St",
            "property_type": "SFR",
            "estimated_value_cents": 45000000,
            "requested_turn_days": 7,
        },
        make_clientuser_headers(UNKNOWN_UUID),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_appointment_create_missing_required_window_end(api):
    """PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.4: "proposes an appointment with the `order_id`, the `appraiser_id`,
    and a window from `window_start` to `window_end`."

    Design: Corner/entities/appointment_create_missing_required_window_end
    """
    response = api.create_appointment(
        {
            "order_id": UNKNOWN_UUID,
            "appraiser_id": UNKNOWN_UUID,
            "window_start": "2026-08-02T09:00:00Z",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_comparable_create_missing_required_sale_date(api):
    """PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.5: "Each comparable is created with the `order_id`, the comparable's
    `address`, its `sale_price_cents` (strictly positive), its `sale_date`,
    its `distance_miles` from the subject (zero or greater), and four signed
    adjustment lines".

    Design: Corner/entities/comparable_create_missing_required_sale_date
    """
    response = api.create_comparable(
        {
            "order_id": UNKNOWN_UUID,
            "address": "1 St",
            "sale_price_cents": 40000000,
            "distance_miles": 0.5,
            "site_adjustment_cents": 0,
            "gla_adjustment_cents": 0,
            "condition_adjustment_cents": 0,
        },
        make_appraiser_headers(UNKNOWN_UUID),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_report_create_missing_required_condition_rating(api):
    """PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.6: "The appraiser creates it with the `order_id`, a `report_type` of
    `FORM_1004`, `FORM_1073`, or `FORM_1025`, and a `condition_rating` of
    `C1`, `C2`, `C3`, `C4`, `C5`, or `C6`."

    Design: Corner/entities/report_create_missing_required_condition_rating
    """
    response = api.create_report(
        {"order_id": UNKNOWN_UUID, "report_type": "FORM_1004"},
        make_appraiser_headers(UNKNOWN_UUID),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_revision_create_missing_required_kind(api):
    """PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.7: "The request supplies a `kind` of `CORRECTION` or
    `RECONSIDERATION_OF_VALUE`, a `detail` narrative, and the concurrency
    guard `expected_order_version` described in §2.8".

    Design: Corner/entities/revision_create_missing_required_kind
    """
    response = api.create_revision_request(
        UNKNOWN_UUID, {"detail": "no kind"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_workfile_create_missing_required_snapshot_type(api):
    """PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.8: "Each record carries the `order_id`, a `snapshot_type` of
    `ORDER_FORM`, `INSPECTION_NOTES`, `COMP_DATA`, `REPORT_PDF`,
    `CERTIFICATION`, or `REVISION_CORRESPONDENCE`, a system-stamped
    `recorded_at`, and a status that begins at `ACTIVE`."

    Design: Corner/entities/workfile_create_missing_required_snapshot_type
    """
    response = api.create_workfile_record({"order_id": UNKNOWN_UUID}, ADMIN)
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_complaint_create_missing_required_description(api):
    """PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.8: "filed by a `FirmAdmin` or a `ComplianceOfficer` with the
    `order_id`, the `respondent_appraiser_id` named in the inquiry, and a
    `description`."

    Design: Corner/entities/complaint_create_missing_required_description
    """
    response = api.create_complaint(
        {"order_id": UNKNOWN_UUID, "respondent_appraiser_id": UNKNOWN_UUID},
        COMPLIANCE,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


# ---------------------------------------------------------------------------
# 400 request shape: enum / range violations (PRD 2.7 step 3)
# ---------------------------------------------------------------------------


def test_order_create_invalid_property_type_enum(api):
    """PRD 2.7: "Request shape: required fields present, enum values within
    their declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."
    PRD 3.3: "a `property_type` of `SFR`, `CONDO`, `MULTI_2_4`, or
    `MANUFACTURED`".

    Design: Corner/entities/order_create_invalid_property_type_enum
    """
    response = api.create_order(
        {
            "client_id": UNKNOWN_UUID,
            "property_address": "1 St",
            "property_type": "DUPLEX5",
            "estimated_value_cents": 45000000,
            "loan_type": "CONVENTIONAL",
            "requested_turn_days": 7,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_appointment_create_inverted_window_rejected(api):
    """PRD 3.4: "`window_end` must be strictly later than `window_start`,
    failing with `ERR_VALIDATION`."

    Design: Corner/entities/appointment_create_inverted_window_rejected
    """
    response = api.create_appointment(
        {
            "order_id": UNKNOWN_UUID,
            "appraiser_id": UNKNOWN_UUID,
            "window_start": "2026-08-02T09:00:00Z",
            "window_end": "2026-08-02T09:00:00Z",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_fee_schedule_rush_bps_out_of_range_rejected(api):
    """PRD 3.1: "a `rush_multiplier_bps` between 0 and 10000 inclusive
    expressing the rush premium in basis points of the base fee".
    PRD 2.7: "Request shape: required fields present, enum values within their
    declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."

    Design: Corner/entities/fee_schedule_rush_bps_out_of_range_rejected
    """
    response = api.create_fee_schedule(
        {
            "client_id": UNKNOWN_UUID,
            "complexity_tier": "STANDARD",
            "base_fee_cents": 45000,
            "rush_multiplier_bps": 10001,
            "revision_fee_cents": 12000,
            "effective_from": "2026-07-01T00:00:00Z",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


def test_comparable_negative_sale_price_rejected(api):
    """PRD 3.5: "its `sale_price_cents` (strictly positive)".
    PRD 2.7: "Request shape: required fields present, enum values within
    their declared sets, and numeric ranges honored — monetary amounts strictly
    positive where required, `window_end` strictly after `window_start`,
    `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000
    inclusive, `default_turn_time_days` and `requested_turn_days` at least 1
    (`ERR_VALIDATION`, 400)."

    Design: Corner/entities/comparable_negative_sale_price_rejected
    """
    response = api.create_comparable(
        {
            "order_id": UNKNOWN_UUID,
            "address": "1 St",
            "sale_price_cents": -5,
            "sale_date": "2026-06-01",
            "distance_miles": 0.5,
            "site_adjustment_cents": 0,
            "gla_adjustment_cents": 0,
            "condition_adjustment_cents": 0,
        },
        make_appraiser_headers(UNKNOWN_UUID),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)


# ---------------------------------------------------------------------------
# Server-minted ids and body foreign-key resolution
# ---------------------------------------------------------------------------


def test_client_create_id_input_ignored(api):
    """PRD 2.5: "`id` (string): a unique, server-minted identifier formatted
    as a UUID, with no type prefix."

    Design: Corner/entities/client_create_id_input_ignored
    """
    response = api.create_client(
        {
            "id": UNKNOWN_UUID,
            "name": "C",
            "client_type": "AMC",
            "contact_email": "c@x.example",
            "default_turn_time_days": 7,
        },
        ADMIN,
    )
    client = validate_success(response, 201)
    assert client["id"] != UNKNOWN_UUID, "server mints its own id"
    assert is_valid_uuid(client["id"])


def test_appointment_create_body_order_fk_not_found(api):
    """PRD 2.9: "path identifiers first, resolved left to right, and then body
    foreign keys such as `order_id`, `client_id`, `appraiser_id`,
    `respondent_appraiser_id`, and `supervisor_id` — each identifier must
    resolve to an existing record."

    Design: Corner/entities/appointment_create_body_order_fk_not_found
    """
    response = api.create_appointment(
        {
            "order_id": UNKNOWN_UUID,
            "appraiser_id": UNKNOWN_UUID,
            "window_start": "2026-08-02T09:00:00Z",
            "window_end": "2026-08-02T10:00:00Z",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND, 404)


def test_complaint_create_body_respondent_fk_not_found(api):
    """PRD 2.9: "then body foreign keys such as `order_id`, `client_id`,
    `appraiser_id`, `respondent_appraiser_id`, and `supervisor_id` — each
    identifier must resolve to an existing record. The first unresolvable
    identifier rejects the request with the referenced entity's not-found
    error".

    Design: Corner/entities/complaint_create_body_respondent_fk_not_found
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    order = create_order(client["id"])
    response = api.create_complaint(
        {
            "order_id": order["id"],
            "respondent_appraiser_id": UNKNOWN_UUID,
            "description": "X",
        },
        COMPLIANCE,
    )
    validate_error(response, ApiErrorId.ERR_APPRAISER_NOT_FOUND, 404)


def test_workfile_create_body_order_fk_not_found(api):
    """PRD 2.9: "When a request references resources — path identifiers first,
    resolved left to right, and then body foreign keys such as `order_id`,
    `client_id`, `appraiser_id`, `respondent_appraiser_id`, and
    `supervisor_id` — each identifier must resolve to an existing record."

    Design: Corner/entities/workfile_create_body_order_fk_not_found
    """
    response = api.create_workfile_record(
        {"order_id": UNKNOWN_UUID, "snapshot_type": "COMP_DATA"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND, 404)


def test_missing_x_user_id_header_unauthenticated(api):
    """PRD 2.1: "A request missing either header, presenting a blank value, or
    naming an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/validations/missing_x_user_id_header_unauthenticated
    """
    response = api.create_client(
        {
            "name": "C",
            "client_type": "AMC",
            "contact_email": "c@x.example",
            "default_turn_time_days": 7,
        },
        make_role_only_headers("FirmAdmin"),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
