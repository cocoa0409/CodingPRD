"""Auth context, role surface, ownership, and the not-found error family
(PRD §2.1, §2.8, §4)."""
from test_helpers import (
    ApiErrorId,
    create_account,
    create_well,
    make_state_regulator_headers,
    validate_error,
    validate_paginated,
)


def test_missing_auth_headers_returns_error(api):
    """PRD §2.1: "Every request carries two mandatory HTTP headers: `X-User-ID` identifies the acting party, and `X-User-Role` names their operational capacity. Five roles are recognized, spelled exactly as follows: `WellOwner`, `WaterMaster`, `EnforcementOfficer`, `AppealsOfficer`, and `StateRegulator`. A request missing either header, or presenting a role string outside this declared set, is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_returns_error
    """
    resp = api.list_accounts(headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT)


def test_not_found_family_returns_404(api, water_master_headers):
    """PRD §2.8: "then path and body identifier existence (left-to-right for path ids, yielding the appropriate `ERR_ACCOUNT_NOT_FOUND`, `ERR_WELL_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, or `ERR_ANNUAL_REPORT_NOT_FOUND`), then the target resource's from-state preconditions (the various `ERR_INVALID_*_STATE` and `ERR_*_NOT_ACTIVE` codes), and only then the business-constraint, business-safety, and business-fiscal rules described in §3."

    Design: Corner/entities/not_found_family_returns_404
    """
    cases = [
        (api.get_account("11111111-1111-4111-8111-111111111111", water_master_headers),
         ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
        (api.get_well("22222222-2222-4222-8222-222222222222", water_master_headers),
         ApiErrorId.ERR_WELL_NOT_FOUND),
        (api.get_extraction_report("33333333-3333-4333-8333-333333333333", water_master_headers),
         ApiErrorId.ERR_REPORT_NOT_FOUND),
        (api.get_transfer_order("44444444-4444-4444-8444-444444444444", water_master_headers),
         ApiErrorId.ERR_TRANSFER_NOT_FOUND),
        (api.get_penalty_assessment("55555555-5555-4555-8555-555555555555", water_master_headers),
         ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
        (api.publish_basin_snapshot("66666666-6666-4666-8666-666666666666", water_master_headers),
         ApiErrorId.ERR_SNAPSHOT_NOT_FOUND),
        (api.submit_annual_state_report("77777777-7777-4777-8777-777777777777", water_master_headers),
         ApiErrorId.ERR_ANNUAL_REPORT_NOT_FOUND),
    ]
    for resp, error_id in cases:
        validate_error(resp, error_id)


def test_state_regulator_reads_all_collections(api, state_regulator_headers):
    """PRD §4: GET /water-user-accounts, GET /wells, and GET /transfer-orders each list WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator as authorized roles.
    PRD §2.1: "A request whose role is well-formed but not listed among the endpoint's permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/state_regulator_reads_all_collections
    """
    account = create_account(holder_name="Pumper RB-3")
    create_well(account["id"], "PRODUCTION", "Parcel RB-3")

    accounts, accounts_meta = validate_paginated(api.list_accounts(state_regulator_headers))
    wells, wells_meta = validate_paginated(api.list_wells(state_regulator_headers))
    transfers, transfers_meta = validate_paginated(api.list_transfer_orders(state_regulator_headers))

    assert accounts_meta["total_count"] == 1 and len(accounts) == 1
    assert wells_meta["total_count"] == 1 and len(wells) == 1
    assert transfers_meta["total_count"] == 0 and transfers == []
