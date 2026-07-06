"""Breadth coverage: resource creation, required/enum/default validation, not-found,
listing/pagination, and role-based access control."""
from test_helpers import (
    fixtures, validate_success, validate_error, validate_paginated,
    make_petitioner_headers, NON_EXISTENT_UUID, ApiErrorId,
)
from test_helpers.factories import create_petitioner_payload

CLERK = fixtures.CLERK
AGENCY = fixtures.AGENCY


# ---- Entities: creation, system fields, validation, defaults, not-found ----
def test_create_petitioner_initializes_fee_ledger_to_zero(api):
    """PRD §3.1: "On creation the two ledger totals, `fee_paid_cents` and
    `fee_refunded_cents`, are both initialized to 0."

    Design: Corner/entities/create_petitioner_success
    """
    data = validate_success(api.create_petitioner(create_petitioner_payload(), CLERK),
                            expected_status=201)
    assert data["fee_paid_cents"] == 0
    assert data["fee_refunded_cents"] == 0


def test_petitioner_fee_paid_is_server_owned_and_starts_zero(api):
    """PRD §3.1: "On creation the two ledger totals, `fee_paid_cents` and
    `fee_refunded_cents`, are both initialized to 0."

    Design: Corner/entities/petitioner_system_fields_generated
    """
    data = validate_success(api.create_petitioner(create_petitioner_payload(), CLERK),
                            expected_status=201)
    assert data["fee_paid_cents"] == 0


def test_create_petition_missing_record_ids_rejected(api):
    """PRD §2.10: "3. **Body well-formedness** — on every mutating endpoint, required
    fields are present, enum fields hold in-range values, integer fields are
    non-negative, `household_size` is at least 1, and, for a hearing, `scheduled_end`
    is strictly later than `scheduled_start`; otherwise `ERR_VALIDATION` (422)."

    Design: Corner/entities/petition_missing_record_ids_returns_invalid_request
    """
    p = fixtures.create_petitioner(api)
    resp = api.create_petition({"petitioner_id": p["id"], "jurisdiction_code": "CA-01"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_criminal_record_invalid_offense_class_rejected(api):
    """PRD §2.10: "3. **Body well-formedness** — on every mutating endpoint, required
    fields are present, enum fields hold in-range values, integer fields are
    non-negative, `household_size` is at least 1, and, for a hearing, `scheduled_end`
    is strictly later than `scheduled_start`; otherwise `ERR_VALIDATION` (422)."

    Design: Corner/entities/criminal_record_invalid_offense_class_enum
    """
    p = fixtures.create_petitioner(api)
    resp = api.create_criminal_record({
        "petitioner_id": p["id"], "offense_code": "PC-1", "offense_class": "BOGUS",
        "disposition": "CONVICTED", "disposition_date": "2019-06-01T00:00:00Z",
        "sentence_completion_date": "2020-01-01T00:00:00Z",
    }, CLERK)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_criminal_record_sentence_completion_defaults_null_for_non_convicted(api):
    """PRD §3.2: "The payload names the `petitioner_id`, an `offense_code` (free-text
    statutory code), an `offense_class`, a `disposition`, a `disposition_date`, and —
    only when the disposition is `CONVICTED` — a `sentence_completion_date` (otherwise
    null)."

    Design: Corner/entities/criminal_record_defaults_sentence_completion_null
    """
    p = fixtures.create_petitioner(api)
    data = validate_success(api.create_criminal_record({
        "petitioner_id": p["id"], "offense_code": "PC-2", "offense_class": "MISDEMEANOR",
        "disposition": "DISMISSED", "disposition_date": "2020-01-01T00:00:00Z",
    }, CLERK), expected_status=201)
    assert data["sentence_completion_date"] is None


def test_get_missing_petition_returns_petition_not_found(api):
    """PRD §2.7: "The rejection carries the not-found error specific to the missing
    entity: `ERR_PETITIONER_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`,
    `ERR_PETITION_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, or `ERR_COURT_ORDER_NOT_FOUND`
    for those aggregates ... All of these are HTTP 404."

    Design: Corner/entities/get_petition_not_found
    """
    resp = api.get_petition(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_FOUND.value)


def test_get_missing_courtroom_returns_generic_not_found(api):
    """PRD §2.7: "and the generic `ERR_NOT_FOUND` for a missing courtroom, judge,
    background vendor, petition item, agency notification, objection, fee waiver, or
    sealing distribution. All of these are HTTP 404."

    Design: Corner/entities/get_courtroom_not_found_generic
    """
    resp = api.get_courtroom(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---- Validations: cross-entity ownership ----------------------------------
def test_petition_with_record_of_another_petitioner_rejected(api):
    """PRD §3.3: "As a reference-integrity guard, every `record_id` supplied must
    belong to the same `petitioner_id` as the petition; a record owned by a different
    petitioner is rejected with `ERR_RECORD_NOT_OWNED` (409)."

    Design: Corner/validations/petition_record_not_owned_rejected
    """
    a = fixtures.create_petitioner(api, full_name="Own A")
    b = fixtures.create_petitioner(api, full_name="Own B")
    rb = fixtures.create_record(api, b["id"])  # record belongs to B
    resp = api.create_petition(
        {"petitioner_id": a["id"], "jurisdiction_code": "CA-01", "record_ids": [rb["id"]]}, CLERK)
    validate_error(resp, ApiErrorId.ERR_RECORD_NOT_OWNED.value)


# ---- Endpoints: listing / pagination --------------------------------------
def test_list_criminal_records_paginates_and_filters(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    size of the full filtered set and `has_more` indicates whether items remain
    beyond the current page."

    Design: Corner/endpoints/criminal_records_pagination_and_filter
    """
    p = fixtures.create_petitioner(api)
    for code, oc, disp in [("PC-1", "MISDEMEANOR", "CONVICTED"),
                           ("PC-2", "INFRACTION", "ARREST_ONLY"),
                           ("PC-3", "MISDEMEANOR", "DISMISSED")]:
        fixtures.create_record(api, p["id"], offense_code=code, offense_class=oc,
                               disposition=disp, disposition_date="2020-01-01T00:00:00Z")
    data, meta = validate_paginated(
        api.list_criminal_records(CLERK, params={"petitioner_id": p["id"], "limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


# ---- RBAC -----------------------------------------------------------------
def test_agency_cannot_screen_record(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to invoke the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/agency_cannot_screen_record
    """
    p = fixtures.create_petitioner(api)
    r = fixtures.create_record(api, p["id"])
    resp = api.screen_criminal_record(r["id"], AGENCY)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_petitioner_cannot_enter_court_order(api):
    """PRD §2.10: "1. **Authentication** ... 2. **Authorization** — the acting role
    is permitted to call the endpoint, else `ERR_UNAUTHORIZED` (403). ... 4.
    **Existence** — every path id and body foreign key resolves, checked
    left-to-right per Section 2.7, else the appropriate 404."

    Design: Corner/rbac/petitioner_cannot_enter_order
    """
    headers = make_petitioner_headers("00000000-0000-4000-8000-0000000000aa")
    resp = api.create_court_order(NON_EXISTENT_UUID, {"disposition": "GRANTED"}, headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_petitioner_cannot_create_record_for_another_owner(api):
    """PRD §2.1: "A petitioner acting on a resource whose `petitioner_id` does not
    equal their `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/petitioner_creates_record_for_other_owner_rejected
    """
    a = fixtures.create_petitioner(api, full_name="Owner A")
    b = fixtures.create_petitioner(api, full_name="Owner B")
    headers = make_petitioner_headers(a["id"])  # X-User-ID == A
    resp = api.create_criminal_record({
        "petitioner_id": b["id"], "offense_code": "PC-1", "offense_class": "MISDEMEANOR",
        "disposition": "CONVICTED", "disposition_date": "2019-06-01T00:00:00Z",
        "sentence_completion_date": "2020-01-01T00:00:00Z",
    }, headers)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_rejected_unauthenticated(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, declaring the capacity in
    which they act. If either header is missing, or if `X-User-Role` is not one of the
    roles the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.create_petitioner(create_petitioner_payload(), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
