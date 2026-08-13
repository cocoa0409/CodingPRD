"""Authentication, role authorization, and production-scope enforcement."""
from test_helpers import (
    FO,
    LM,
    ApiErrorId,
    create_owner_payload,
    create_production_payload,
    create_scout_package_payload,
    get_success_data,
    make_owner_rep_headers,
    setup_basic_scenario,
    setup_production_with_executed_agreement,
    setup_under_review_permit,
    validate_error,
)


def test_create_production_missing_auth_header_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or does not name
    one of these three roles, or whose `X-User-ID` header is missing, is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.7: "Requests across the API are checked in a fixed precedence order:
    authentication of the headers first (`ERR_UNAUTHENTICATED`)"

    Design: Corner/validations/create_production_missing_auth_header_unauthenticated
    """
    resp = api.create_production(create_production_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_role_denied_precedes_existence_check(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.7: "authentication of the headers first (`ERR_UNAUTHENTICATED`), then
    role authorization (`ERR_FORBIDDEN`), then existence and production-scope of
    every path identifier (`ERR_NOT_FOUND`)"
    PRD §2.1: "A `LocationManager` is the production-side operator: they create
    productions, register owners and locations, book locations, assemble scout
    packages, negotiate owner agreements, file and amend permit applications,
    request street closures, record notifications, present insurance certificates,
    fund deposit accounts, author walkthrough reports, assign monitors, plan and
    run shoot days, and wrap or cancel the production."

    Design: Corner/validations/role_denied_precedes_existence_check
    """
    # FilmOffice is recognized but not permitted on POST /productions; the
    # payload is otherwise valid, so only the role check can fire.
    resp = api.create_production(create_production_payload(), FO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_nested_not_found_for_child_outside_production_scope(api):
    """PRD §2.7: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
    first identifier — parent `{id}` or child `{rid}` — that does not exist or
    does not belong to the enclosing production's scope, before any business rule
    is evaluated."

    Design: Corner/validations/nested_not_found_for_child_outside_production_scope
    """
    scenario = setup_basic_scenario()
    location_id = scenario["location"]["id"]
    prod_a = scenario["production"]
    prod_b = get_success_data(api.create_production(
        create_production_payload(title="Prod B", production_company="Co B", cast_size=30), LM,
    ))
    package = get_success_data(api.create_scout_package(
        prod_a["id"], create_scout_package_payload(location_id), LM,
    ))

    # The package exists, but under production A — production B's scope 404s.
    resp = api.get_scout_package(prod_b["id"], package["id"], LM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_owner_rep_cannot_create_production(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "An `OwnerRep` is the property owner's representative: they counter
    proposals, accept proposed agreements, dispute post-shoot walkthrough reports,
    and file complaints."
    PRD §2.1: "A `LocationManager` is the production-side operator: they create
    productions, register owners and locations, book locations, assemble scout
    packages, negotiate owner agreements, file and amend permit applications,
    request street closures, record notifications, present insurance certificates,
    fund deposit accounts, author walkthrough reports, assign monitors, plan and
    run shoot days, and wrap or cancel the production."

    Design: Corner/rbac/owner_rep_cannot_create_production
    """
    owner = get_success_data(api.create_owner(create_owner_payload(), LM))
    resp = api.create_production(
        create_production_payload(), make_owner_rep_headers(owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_location_manager_cannot_decide_permit(api):
    """PRD §2.1: "A `FilmOffice` operator is the jurisdiction's staff: they
    configure and suspend jurisdictions, review scout packages, start review on
    and decide permit applications, approve street closures, acknowledge
    notifications, verify or reject insurance certificates, settle deposit
    accounts, confirm, release, check in, and mark no-show monitors, shut down
    shoot days, and drive the logical clock and the operations sweep."
    PRD §2.1: "A request whose role is recognized but not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/location_manager_cannot_decide_permit
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    permit = setup_under_review_permit(scenario, clock="2026-08-03T09:00:00Z")
    assert permit["status"] == "UNDER_REVIEW"

    resp = api.decide_permit_application(production_id, permit["id"], "ISSUE", LM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    current = get_success_data(api.get_permit_application(production_id, permit["id"], LM))
    assert current["status"] == "UNDER_REVIEW"
