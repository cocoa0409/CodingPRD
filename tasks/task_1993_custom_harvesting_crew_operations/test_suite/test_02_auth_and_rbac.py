"""Authentication rung and role-based denials (PRD 2.1 and 2.6)."""
from test_helpers import (
    ApiErrorId,
    activate_season,
    add_machine,
    create_season,
    get_season,
    open_settlement_window,
    setup_settling_season_with_draft_settlement,
    validate_error,
)


def test_missing_auth_header_rejected(api, no_auth_headers):
    """PRD section 2.1: "Every request must carry two headers: `X-User-ID` and
    `X-User-Role`. If either header is missing or malformed, the request is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_rejected
    """
    resp = api.list_seasons(no_auth_headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_crew_boss_cannot_close_season(api, crew_boss_headers):
    """PRD section 2.1: "Only a `HarvestOperator` may create and activate a
    season, edit diesel prices, open the settlement window, close the season,
    register machines and lodging sites, onboard and activate or release crew
    members, dispatch repairs, return machines to service, skip route stops,
    and advance the logical clock."
    PRD section 2.1: "If the named role is not permitted to perform the
    requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/crew_boss_cannot_close_season
    """
    season = create_season()
    add_machine(season["id"])
    activate_season(season["id"])
    open_settlement_window(season["id"])
    season_now = get_season(season["id"])
    resp = api.close_season(
        season["id"], {"expected_season_version": season_now["version"]}, crew_boss_headers
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_billing_clerk_cannot_create_contract(api, billing_clerk_headers):
    """PRD section 2.1: "Only a `GrowerLiaison` may create contracts under a
    season, commit or cancel them, create route stops, and dispute an issued
    settlement on a grower's behalf."
    PRD section 2.1: "If the named role is not permitted to perform the
    requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/billing_clerk_cannot_create_contract
    """
    season = create_season()
    resp = api.create_contract(
        season["id"],
        {
            "grower_name": "X", "state_code": "KS", "crop": "WHEAT",
            "rate_basis": "PER_ACRE", "rate_cents_per_acre": 3200,
            "rate_cents_per_bushel": 0, "committed_acres": 100,
        },
        billing_clerk_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_grower_liaison_cannot_issue_settlement(api, grower_liaison_headers):
    """PRD section 2.1: "Only a `BillingClerk` may create draft settlements,
    issue them, mark them paid, and resolve disputes."
    PRD section 2.1: "If the named role is not permitted to perform the
    requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/grower_liaison_cannot_issue_settlement
    """
    ctx = setup_settling_season_with_draft_settlement()
    resp = api.issue_settlement(
        ctx["settlement"]["id"], {"expected_contract_version": 1}, grower_liaison_headers
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
