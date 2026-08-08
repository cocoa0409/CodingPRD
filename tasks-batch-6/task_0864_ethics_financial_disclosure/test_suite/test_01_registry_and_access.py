"""Registry CRUD, input validation, RBAC and pagination bounds.

Queue B (Corner): entities, rbac, pagination validations.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    assert_jurisdiction, assert_filer,
    create_jurisdiction_payload, create_filer_payload,
    make_filer_headers, register_jurisdiction,
)


def test_jurisdiction_defaults_applied(api, registrar_headers):
    """PRD 3.1: "`gift_single_limit_cents`, the per-event ceiling on a single gift's net
    reportable value, defaulting to 5000; and `gift_annual_source_limit_cents`, the per-source
    per-calendar-year cumulative ceiling on net reportable gifts, defaulting to 25000. When a
    policy field is omitted at creation, its stated default applies."
    PRD 3.1: "`penalty_cap_cents`, the absolute ceiling on any single late-filing penalty,
    defaulting to 50000".

    Design: Corner/entities/jurisdiction_create_applies_limit_defaults
    """
    res = api.create_jurisdiction(create_jurisdiction_payload(name="Bare Board"), registrar_headers)
    jur = validate_success(res, 201)
    assert_jurisdiction(jur)
    assert jur["gift_single_limit_cents"] == 5000
    assert jur["gift_annual_source_limit_cents"] == 25000
    assert jur["penalty_cap_cents"] == 50000


def test_new_filer_computed_fields_defaulted(api, registrar_headers):
    """PRD 3.1: "a filer exposes several server-derived attributes that reflect the filer's
    compliance posture and are never set directly by clients: `compliance_status`,
    `outstanding_penalty_cents`, `reportable_gift_total_cents`, `open_recusal_count`, and
    `training_status`."
    PRD 3.9: "and `NONE` when no course has been completed."

    Design: Corner/entities/filer_create_computed_fields_defaulted
    """
    jur = register_jurisdiction()
    res = api.create_filer(
        create_filer_payload(jur["id"], filer_category="APPOINTED", full_name="New Filer",
                             official_title="Aide"), registrar_headers)
    filer = validate_success(res, 201)
    assert_filer(filer)
    assert filer["compliance_status"] == "COMPLIANT"
    assert filer["training_status"] == "NONE"
    assert filer["outstanding_penalty_cents"] == 0
    assert filer["open_recusal_count"] == 0


def test_get_nonexistent_filer_not_found(api, registrar_headers):
    """PRD 2.8: "the referenced resource must exist or the request fails with `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/filer_get_nonexistent_returns_not_found
    """
    res = api.get_filer(NON_EXISTENT_UUID, registrar_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_statement_missing_filing_period_validation(api, registrar_headers):
    """PRD 2.11: "request-body well-formedness — required fields present, enum values legal,
    integer fields non-negative — yielding `ERR_VALIDATION`".
    PRD 3.3: "supplying `filer_id`, `filing_period_id`, and optionally the disclosure `content`".

    Design: Corner/entities/statement_create_missing_required_returns_validation
    """
    jur = register_jurisdiction()
    filer = get_success_data(api.create_filer(
        create_filer_payload(jur["id"], filer_category="ELECTED"), registrar_headers))
    res = api.create_statement({"filer_id": filer["id"]}, make_filer_headers(filer["id"]))
    validate_error(res, "ERR_VALIDATION")


def test_filer_invalid_category_validation(api, registrar_headers):
    """PRD 2.11: "request-body well-formedness — required fields present, enum values legal,
    integer fields non-negative — yielding `ERR_VALIDATION`".
    PRD 3.1: "The `filer_category` is one of `ELECTED`, `APPOINTED`, `SENIOR_STAFF`, or
    `CANDIDATE`".

    Design: Corner/entities/filer_invalid_category_enum_returns_validation
    """
    jur = register_jurisdiction()
    res = api.create_filer(
        create_filer_payload(jur["id"], full_name="X", official_title="Y", filer_category="MAYOR"),
        registrar_headers)
    validate_error(res, "ERR_VALIDATION")


def test_list_filers_pagination_envelope(api, registrar_headers):
    """PRD 2.3: "List responses populate the `limit`, `offset`, `total_count`, and `has_more`
    fields in the `meta` object of the envelope."

    Design: Corner/entities/filers_list_returns_pagination_envelope
    """
    jur = register_jurisdiction()
    get_success_data(api.create_filer(
        create_filer_payload(jur["id"], filer_category="ELECTED"), registrar_headers))
    data, meta = validate_paginated(api.list_filers(registrar_headers, params={"jurisdiction_id": jur["id"]}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1


def test_missing_auth_headers_unauthenticated(api, registrar_headers):
    """PRD 2.1: "A request missing either header, or presenting an `X-User-Role` that is not one
    of the recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    jur = register_jurisdiction()
    filer = get_success_data(api.create_filer(
        create_filer_payload(jur["id"], filer_category="ELECTED"), registrar_headers))
    res = api.get_filer(filer["id"], {})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_filer_cannot_create_jurisdiction(api, registrar_headers):
    """PRD 2.1: "A syntactically authenticated request whose role is not permitted to invoke the
    target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/filer_cannot_create_jurisdiction_returns_unauthorized
    """
    jur = register_jurisdiction()
    filer = get_success_data(api.create_filer(
        create_filer_payload(jur["id"], filer_category="ELECTED"), registrar_headers))
    res = api.create_jurisdiction(
        create_jurisdiction_payload(name="Rogue Board"), make_filer_headers(filer["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_pagination_limit_too_large(api, registrar_headers):
    """PRD 2.3: "A request whose `limit` falls outside the range of 1 through 100 inclusive, or
    whose `offset` is negative, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/validations/list_pagination_limit_too_large_returns_error
    """
    res = api.list_filers(registrar_headers, params={"limit": 500})
    validate_error(res, "ERR_PAGINATION_INVALID")
