"""Authentication, authorization, ownership, and request-shape validation (breadth corner coverage)."""
from test_helpers import (
    validate_error, ApiErrorId, NON_EXISTENT_UUID,
    create_client_payload, create_parcel_payload,
    make_analyst_headers, make_client_headers, TEST_USERS,
)
from test_helpers import fixtures as fx

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the four recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/corner_missing_role_returns_unauthenticated
    """
    resp = api.create_client(create_client_payload(full_name="X"), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_client_creating_parcel_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/corner_client_creates_parcel_returns_unauthorized
    """
    client = fx.new_client(api)
    jur = fx.new_jurisdiction(api)
    resp = api.create_parcel(create_parcel_payload(client["id"], jur["id"], apn="VX1", address="a"),
                             make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_billing_cannot_file_appeal_authz_precedes_existence(api):
    """PRD §2.10: "Role authorization (`ERR_UNAUTHORIZED`) is next, followed by the ownership check
    for entity-backed roles (`ERR_FORBIDDEN_NOT_OWNER`). Existence of all referenced resources
    (`ERR_NOT_FOUND`) is then confirmed".

    Design: Corner/rbac/corner_billing_cannot_file_appeal_returns_unauthorized
    """
    resp = api.file_appeal(NON_EXISTENT_UUID, BILLING)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_accept_fee_agreement_by_non_owner_returns_forbidden(api):
    """PRD §2.1: "When an entity-backed role (a `Client` on the portal, or an `Analyst` acting on a
    resource it must own) targets a resource whose owner foreign key does not match `X-User-ID`, the
    request is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403)."

    Design: Corner/endpoints/corner_feeagreement_accept_wrong_owner_returns_forbidden
    """
    owner = fx.new_client(api, full_name="Owner")
    other = fx.new_client(api, full_name="Other")
    fa = fx.new_fee_agreement(api, owner["id"])
    resp = api.accept_fee_agreement(fa["id"], make_client_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value)


def test_hearing_end_not_after_start_returns_invalid_value(api):
    """PRD §3.5: "`scheduled_end` must be strictly later than `scheduled_start`; a non-positive
    interval is rejected with `ERR_INVALID_VALUE`."

    Design: Corner/validations/corner_hearing_end_before_start_returns_invalid_value
    """
    ctx = fx.setup_filed_appeal(api, two_analysts=True)
    resp = api.schedule_hearing(
        ctx["appeal_id"],
        {"representative_id": ctx["analyst2_id"], "docket_room": "R1",
         "scheduled_start": "2026-08-01T11:00:00Z", "scheduled_end": "2026-08-01T10:00:00Z"},
        make_analyst_headers(ctx["analyst_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_VALUE.value)


def test_second_nonterminal_appeal_on_assessment_returns_duplicate(api):
    """PRD §3.4: "Only one non-terminal appeal may exist per assessment; attempting a second while an
    appeal on that assessment is still live is rejected with `ERR_DUPLICATE`."

    Design: Corner/validations/corner_second_nonterminal_appeal_returns_duplicate
    """
    ctx = fx.setup_base(api)
    fx.new_appeal(api, ctx["analyst_id"], ctx["assessment_id"], ctx["fee_agreement_id"], "SALES_COMPARISON")
    resp = api.create_appeal(
        {"assessment_id": ctx["assessment_id"], "analyst_id": ctx["analyst_id"],
         "fee_agreement_id": ctx["fee_agreement_id"], "valuation_method": "ASSESSMENT_EQUITY"},
        make_analyst_headers(ctx["analyst_id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)
