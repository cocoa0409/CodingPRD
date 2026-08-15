"""Authentication, authorization, and validation-chain precedence."""
from test_helpers import (
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    PM,
    RM,
    TC,
    ApiErrorId,
    create_property,
    create_property_payload,
    create_unit,
    create_vendor,
    make_vendor_headers,
    open_turn,
    validate_error,
)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "All interactions with the API must be authenticated through
    two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, declaring the caller's operational capacity."
    PRD §2.1: "A request missing either header, or carrying a role outside this
    declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    resp = api.create_turn(
        {"unit_id": NON_EXISTENT_UUID, "notice_date": "2026-07-28",
         "move_out_date": "2026-07-31"},
        NO_AUTH_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_authorization_precedes_existence(api):
    """PRD §2.8: "Every request is evaluated against a fixed, ordered
    validation chain, and the first failing check determines the error returned
    — later checks are never reached once an earlier one fails."
    PRD §2.8: "**Authorization** — the declared role appears in the endpoint's
    permitted role list; failure yields `ERR_UNAUTHORIZED` (HTTP 403)." (Check
    2, running before existence, check 4.)

    Design: Corner/validations/authz_precedes_existence_unauthorized
    """
    # TurnCoordinator is not permitted on close; the turn id does not exist.
    resp = api.close_turn(NON_EXISTENT_UUID, TC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_vendor_cannot_create_scope_items(api):
    """PRD §2.1: "A request whose role is recognized but not permitted on the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST `/make-ready/scope-items` is authorized for `TurnCoordinator`
    only.

    Design: Corner/rbac/vendor_cannot_create_scope_items
    """
    prop = create_property()
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    vendor = create_vendor("FixCo", "REPAIR")

    resp = api.create_scope_item(
        {"turn_id": turn["id"], "category": "REPAIR",
         "description": "vendor attempt", "estimated_cost_cents": 1000},
        make_vendor_headers(vendor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_coordinator_cannot_submit_inspection(api):
    """PRD §3.7: "Quality control is deliberately segregated: only an
    `Inspector` — never the coordinator who ran the work — submits the verdict,
    and only while the turn is `IN_PROGRESS`; a turn in any other status
    rejects the submission with `ERR_INVALID_STATE`."
    PRD §2.1: "A request whose role is recognized but not permitted on the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/coordinator_cannot_inspect
    """
    prop = create_property()
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])

    resp = api.submit_inspection(turn["id"], {"result": "PASS"}, TC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_property_manager_cannot_create_property(api):
    """PRD §3.1: "A `RegionalManager` onboards a property by supplying its
    `name` together with the four policy numbers that will govern every turn on
    that property: `days_to_ready_target`, the calendar-day goal from scope
    finalization to ready;"
    PRD §2.1: "A request whose role is recognized but not permitted on the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/property_manager_cannot_create_property
    """
    resp = api.create_property(
        create_property_payload(name="Nope Villas"), PM)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
