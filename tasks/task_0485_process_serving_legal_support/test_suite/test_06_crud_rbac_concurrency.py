"""CRUD surface, input validation, county defaults, the immutable territory join,
RBAC denials, optimistic concurrency on assignment offers, and derived/scheduled
fields (distinct_attempt_days dedup, rush deadline).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_client_headers,
    make_server_headers,
    setup_reference_data,
    create_submitted_request,
    offer_to_server,
    log_attempt,
    setup_active_assignment,
    get_request,
    MISSING_UUID,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── Queue B: entities CRUD & validation ──────────────────────────────────
def test_create_service_request_returns_201_draft_version_1(api):
    """PRD 3.2: "A `Client` ... or a `Dispatcher` ... creates one in `DRAFT`
    status".
    PRD 2.4: "`version` — an integer that begins at its initial value and
    increments by one on every mutation."

    Design: Corner/entities/create_servicerequest_returns_201_with_all_fields
    """
    county = get_success_data(api.create_county({"name": "Kern", "state_code": "CA"}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Cre Law", "email": "c@law.com"}, ADMIN))
    sr = validate_success(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "1 St", "service_lat": 35.3, "service_lng": -119.0}, DISPATCHER
        ), 201
    )
    assert sr["status"] == "DRAFT"
    assert sr["version"] == 1
    assert sr["final_fee_cents"] == 0


def test_get_service_request_returns_stored_entity(api):
    """PRD 4: "GET /service-requests/{id} — Get a ServiceRequest". The stored
    recipient_name is echoed back.

    Design: Corner/entities/get_servicerequest_returns_stored_entity
    """
    county = get_success_data(api.create_county({"name": "Kings", "state_code": "CA"}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Ret Law", "email": "r@law.com"}, ADMIN))
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "Jane Q",
             "service_address": "2 St", "service_lat": 36.0, "service_lng": -119.8}, DISPATCHER
        )
    )
    got = validate_success(api.get_service_request(sr["id"], DISPATCHER))
    assert got["recipient_name"] == "Jane Q"


def test_list_service_requests_paginated_envelope(api):
    """PRD 2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_servicerequests_paginated_envelope
    """
    county = get_success_data(api.create_county({"name": "Tulare", "state_code": "CA"}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Lst Law", "email": "l@law.com"}, ADMIN))
    get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "3 St", "service_lat": 36.2, "service_lng": -119.3}, DISPATCHER
        )
    )
    data, meta = validate_paginated(
        api.list_service_requests(DISPATCHER, params={"client_id": client["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False


def test_get_nonexistent_service_request_returns_not_found(api):
    """PRD 2.5: "The first identifier in the path that does not resolve to an
    existing, correctly-scoped resource causes the request to be rejected
    immediately with `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/get_servicerequest_nonexistent_returns_not_found
    """
    validate_error(api.get_service_request(MISSING_UUID, DISPATCHER), ApiErrorId.ERR_NOT_FOUND.value)


def test_create_service_request_missing_recipient_name_invalid(api):
    """PRD 2.6: "a missing required field ... yields `ERR_INVALID_REQUEST` (422)."
    recipient_name is a required input (PRD 3.2).

    Design: Corner/entities/create_servicerequest_missing_required_field_returns_invalid_request
    """
    county = get_success_data(api.create_county({"name": "Fresno", "state_code": "CA"}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Mis Law", "email": "m@law.com"}, ADMIN))
    validate_error(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"],
             "service_address": "4 St", "service_lat": 36.7, "service_lng": -119.7}, DISPATCHER
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


def test_county_omitting_optionals_applies_defaults(api):
    """PRD 3.1: "four optional policy fields that take documented defaults when
    omitted: `e_file_enabled` (... default false), `min_diligent_attempts` (...
    default 3), `filing_fee_cents` (... default 4000), and `max_concurrent_filings`
    (... default 2)."

    Design: Corner/entities/create_county_omitting_defaults_applies_defaults
    """
    county = validate_success(api.create_county({"name": "Madera", "state_code": "CA"}, ADMIN), 201)
    assert county["e_file_enabled"] is False
    assert county["min_diligent_attempts"] == 3
    assert county["filing_fee_cents"] == 4000
    assert county["max_concurrent_filings"] == 2


def test_create_document_invalid_enum_doc_type_invalid(api):
    """PRD 2.6: "an invalid enum value ... yields `ERR_INVALID_REQUEST` (422)."
    PRD 3.2: doc_type is "one of `SUMMONS`, `SUBPOENA`, `COMPLAINT`, `NOTICE`, or
    `WRIT`".

    Design: Corner/entities/create_document_invalid_enum_doc_type_returns_invalid_request
    """
    county = get_success_data(api.create_county({"name": "Stanislaus", "state_code": "CA"}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Enm Law", "email": "e@law.com"}, ADMIN))
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "6 St", "service_lat": 37.6, "service_lng": -121.0}, DISPATCHER
        )
    )
    validate_error(
        api.create_document(sr["id"], {"doc_type": "BANANA", "page_count": 2}, DISPATCHER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


def test_create_document_page_count_zero_invalid(api):
    """PRD 2.6: "a `page_count` below 1 ... yields `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/create_document_page_count_zero_returns_invalid_request
    """
    county = get_success_data(api.create_county({"name": "SanJoaquin", "state_code": "CA"}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Pg Law", "email": "g@law.com"}, ADMIN))
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "7 St", "service_lat": 37.9, "service_lng": -121.3}, DISPATCHER
        )
    )
    validate_error(
        api.create_document(sr["id"], {"doc_type": "SUMMONS", "page_count": 0}, DISPATCHER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


def test_service_request_system_fields_forced(api):
    """PRD 3.2: a request is created "in `DRAFT` status"; PRD 2.4: `version`
    "begins at its initial value". status and version are server-controlled, not
    client-supplied.

    Design: Corner/entities/servicerequest_system_fields_input_ignored
    """
    county = get_success_data(api.create_county({"name": "Mariposa", "state_code": "CA"}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Sys Law", "email": "s@law.com"}, ADMIN))
    sr = validate_success(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "8 St", "service_lat": 37.5, "service_lng": -119.9}, DISPATCHER
        ), 201
    )
    assert sr["status"] == "DRAFT"
    assert sr["version"] == 1


def test_create_service_request_unknown_county_returns_not_found(api):
    """PRD 2.5: "Existence validation of path and body references always precedes
    business-rule evaluation." A body county_id that resolves to nothing yields
    `ERR_NOT_FOUND`.

    Design: Corner/entities/create_servicerequest_wrong_parent_county_returns_not_found
    """
    client = get_success_data(api.create_client({"firm_name": "Fk Law", "email": "f@law.com"}, ADMIN))
    validate_error(
        api.create_service_request(
            {"client_id": client["id"], "county_id": "00000000-0000-4000-8000-000000000999",
             "recipient_name": "R", "service_address": "9 St", "service_lat": 37.0, "service_lng": -120.0}, DISPATCHER
        ),
        ApiErrorId.ERR_NOT_FOUND.value,
    )


def test_server_territory_immutable_no_version_field(api):
    """PRD 2.4: "The `ServerTerritory` join resource ... is immutable after
    creation. It carries only `id` and `created_at`; it has no `updated_at` and no
    `version` field."

    Design: Corner/entities/serverterritory_immutable_no_version_field
    """
    county = get_success_data(api.create_county({"name": "Amador", "state_code": "CA"}, ADMIN))
    server = get_success_data(api.create_server({"full_name": "Imm Utable", "license_no": "PS-IMM1"}, ADMIN))
    territory = validate_success(api.create_territory(server["id"], {"county_id": county["id"]}, ADMIN), 201)
    assert "id" in territory and territory["id"]
    assert "created_at" in territory
    assert "version" not in territory, "immutable join carries no version field"
    assert "updated_at" not in territory, "immutable join carries no updated_at field"


# ─── Queue B: rbac ────────────────────────────────────────────────────────
def test_client_cannot_offer_assignment(api):
    """PRD 2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)." Offering is Dispatcher-exclusive (PRD 2.1:
    Dispatcher "exclusively offers assignments to servers").

    Design: Corner/rbac/rbac_client_cannot_offer_assignment_returns_unauthorized
    """
    county = get_success_data(api.create_county({"name": "Rb County", "state_code": "CA", "min_diligent_attempts": 1}, ADMIN))
    server = get_success_data(api.create_server({"full_name": "Rb Server", "license_no": "PS-RBC1"}, ADMIN))
    get_success_data(api.create_territory(server["id"], {"county_id": county["id"]}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Rb Law", "email": "rb@law.com"}, ADMIN))
    ch = make_client_headers(client["id"])
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "1 St", "service_lat": 36.0, "service_lng": -119.0}, ch
        )
    )
    get_success_data(api.create_document(sr["id"], {"doc_type": "SUMMONS", "page_count": 1}, ch))
    submitted = get_success_data(api.submit_request(sr["id"], ch))
    validate_error(
        api.offer_assignment(
            sr["id"], {"server_id": server["id"], "expected_service_request_version": submitted["version"]}, ch
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


def test_other_server_cannot_log_attempt_on_foreign_assignment(api):
    """PRD 2.1: "The same `ERR_UNAUTHORIZED` is returned when a role is permitted in
    general but the acting principal does not own the specific resource it is trying
    to mutate (an ownership mismatch)." A Server "may ... log attempts only on its
    own assignment".

    Design: Corner/rbac/rbac_other_server_cannot_log_attempt_on_foreign_assignment
    """
    county = get_success_data(api.create_county({"name": "Own County", "state_code": "CA", "min_diligent_attempts": 1}, ADMIN))
    s1 = get_success_data(api.create_server({"full_name": "Owner", "license_no": "PS-OWN1"}, ADMIN))
    s2 = get_success_data(api.create_server({"full_name": "Intruder", "license_no": "PS-OWN2"}, ADMIN))
    get_success_data(api.create_territory(s1["id"], {"county_id": county["id"]}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Ow Law", "email": "ow@law.com"}, ADMIN))
    sr = create_submitted_request(client["id"], county["id"])
    asg = offer_to_server(sr["id"], s1["id"], sr["version"])
    get_success_data(api.accept_assignment(asg["id"], make_server_headers(s1["id"])))
    # s2 (a different server) tries to log an attempt on s1's assignment.
    validate_error(
        api.create_attempt(
            asg["id"], {"attempted_at_utc": "2026-01-01T09:00:00Z", "gps_lat": 36.0, "gps_lng": -119.0, "outcome": "NO_ANSWER"},
            make_server_headers(s2["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


def test_unknown_role_returns_unauthenticated(api):
    """PRD 2.1: "If either header is missing, or if `X-User-Role` is not one of
    these five known roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/rbac_missing_headers_returns_unauthenticated
    """
    county = get_success_data(api.create_county({"name": "Auth County", "state_code": "CA"}, ADMIN))
    bad_headers = {"X-User-ID": "nobody", "X-User-Role": "Nobody", "Content-Type": "application/json"}
    validate_error(api.get_county(county["id"], bad_headers), ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── Queue B: optimistic concurrency ──────────────────────────────────────
def test_offer_with_stale_version_returns_stale_version(api):
    """PRD 2.9: "If `expected_service_request_version` does not equal the request's
    current `version`, the offer is rejected with `ERR_STALE_VERSION` (HTTP 412),
    and no assignment is created."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_assignment_offer_returns_412
    """
    county = get_success_data(api.create_county({"name": "Occ County", "state_code": "CA", "min_diligent_attempts": 1}, ADMIN))
    s1 = get_success_data(api.create_server({"full_name": "Occ One", "license_no": "PS-OCC1"}, ADMIN))
    s2 = get_success_data(api.create_server({"full_name": "Occ Two", "license_no": "PS-OCC2"}, ADMIN))
    get_success_data(api.create_territory(s1["id"], {"county_id": county["id"]}, ADMIN))
    get_success_data(api.create_territory(s2["id"], {"county_id": county["id"]}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Oc Law", "email": "oc@law.com"}, ADMIN))
    sr = create_submitted_request(client["id"], county["id"])
    stale_v = sr["version"]
    offer_to_server(sr["id"], s1["id"], stale_v)  # first offer advances version.
    # Second offer reuses the stale pre-first-offer version.
    validate_error(
        api.offer_assignment(
            sr["id"], {"server_id": s2["id"], "expected_service_request_version": stale_v}, DISPATCHER
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )


def test_offer_with_correct_version_succeeds_and_bumps_version(api):
    """PRD 3.3: "A successful offer has two further effects: any prior `OFFERED`
    assignment for the same request is superseded ... and the request's `version`
    is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_offer_succeeds_and_bumps_version
    """
    county, server, client = setup_reference_data(
        deposit_cents=0, county_overrides={"name": "Occ2 County", "state_code": "CA", "min_diligent_attempts": 1}
    )
    sr = create_submitted_request(client["id"], county["id"])
    before_v = sr["version"]
    asg = validate_success(
        api.offer_assignment(
            sr["id"], {"server_id": server["id"], "expected_service_request_version": before_v}, DISPATCHER
        ), 201
    )
    after = get_request(sr["id"])
    assert after["version"] == before_v + 1, f"version should increase by exactly 1, was {before_v}, now {after['version']}"


# ─── Queue B: derived / scheduled fields ──────────────────────────────────
def test_distinct_attempt_days_dedups_same_day(api):
    """PRD 3.4: "The request's `distinct_attempt_days` counts the distinct UTC
    calendar days on which a non-superseded attempt was logged — two attempts on
    the same calendar day count once."

    Design: Corner/cross_cutting_complexity_layers/derived_distinct_attempt_days_dedup_same_day
    """
    county, server, client, sr, asg = setup_active_assignment(
        county_overrides={"name": "Ded County", "state_code": "CA", "min_diligent_attempts": 1}
    )
    log_attempt(asg["id"], server["id"], "2026-01-01T08:00:00Z", "NO_ANSWER")
    log_attempt(asg["id"], server["id"], "2026-01-01T20:00:00Z", "NO_ANSWER")
    out = get_request(sr["id"])
    assert out["distinct_attempt_days"] == 1, f"two same-day attempts must count as 1, got {out['distinct_attempt_days']}"


def test_rush_deadline_is_created_at_plus_48h(api):
    """PRD 3.2: "`deadline_utc` is set to the request's `created_at` plus 48 hours
    when `rush` is true".
    PRD 2.8: "At startup the clock reads exactly `2026-01-01T00:00:00Z`".

    Design: Corner/cross_cutting_complexity_layers/scheduled_deadline_default_clock_rush_window
    """
    county = get_success_data(api.create_county({"name": "Sch County", "state_code": "CA", "min_diligent_attempts": 1}, ADMIN))
    client = get_success_data(api.create_client({"firm_name": "Sc Law", "email": "sc@law.com"}, ADMIN))
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "1 St", "service_lat": 36.0, "service_lng": -119.0, "rush": True}, DISPATCHER
        )
    )
    get_success_data(api.create_document(sr["id"], {"doc_type": "SUMMONS", "page_count": 1}, DISPATCHER))
    submitted = validate_success(api.submit_request(sr["id"], DISPATCHER), 200)
    assert submitted["deadline_utc"].startswith("2026-01-03T00:00:00"), (
        f"rush deadline should be created_at+48h = 2026-01-03T00:00:00Z, got {submitted['deadline_utc']}"
    )
