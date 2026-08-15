"""Role authorization, customer ownership scoping, error envelope, and
pipeline ordering (header/role/existence tiers)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_account,
    create_asset,
    create_asset_payload,
    create_proposed_design,
    create_product_payload,
    make_customer_contact_headers,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
CHEMIST = TEST_USERS["chemist_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_waterchemist_cannot_manage_accounts(api):
    """PRD §4: "| POST | `/wt/accounts` | Create a customer account | AccountManager |"
    PRD §2.6 tier 2: "`X-User-Role` must be one of the four declared roles and
    permitted for the target endpoint; failure is `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/waterchemist_cannot_manage_accounts_or_invoices
    """
    resp = api_client.create_account({"account_name": "Nope Co"}, CHEMIST)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp.status_code == 403


def test_accountmanager_cannot_record_field_data(api):
    """PRD §4: "| POST | `/wt/assets` | Register a system asset under an account | WaterChemist |"
    PRD §4: "| POST | `/wt/program-designs` | Open a system survey / program design | WaterChemist |"
    PRD §2.6: "Every request passes through a single validation pipeline of
    fifteen tiers, evaluated strictly in ascending priority order. The first
    tier whose check fails determines the error response; later tiers are never
    consulted for that request." (role authorization, tier 2, precedes
    existence, tier 4.)

    Design: Corner/rbac/accountmanager_cannot_record_field_data
    """
    account = create_account(account_name="RBAC Co")
    resp_assets = api_client.create_asset(
        create_asset_payload(account["id"], asset_tag="X", asset_type="BOILER"),
        MANAGER,
    )
    validate_error(resp_assets, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    # The bogus asset_id is never even resolved: role check fires first.
    resp_designs = api_client.create_program_design({"asset_id": NON_EXISTENT_UUID}, MANAGER)
    validate_error(resp_designs, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_platformadmin_exclusive_product_catalog(api):
    """PRD §4: "| POST | `/wt/products` | Create a catalog product | PlatformAdmin |"
    PRD §4: "| POST | `/wt/_clock/set_current_utc` | Set the server's logical
    clock; runs due/overdue sweeps | PlatformAdmin |"
    PRD §3.3: "Products are born `LISTED`".
    PRD §2.6 tier 2: failure is `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

    Design: Corner/rbac/platformadmin_exclusive_product_catalog
    """
    account = create_account(account_name="Cat Co")
    payload = create_product_payload(product_code="B3-1")

    resp_denied = api_client.create_product(payload, MANAGER)
    validate_error(resp_denied, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    created = validate_success(api_client.create_product(payload, ADMIN), expected_status=201)
    assert created["status"] == "LISTED"

    resp_clock = api_client.set_clock(
        "2026-08-02T00:00:00Z", make_customer_contact_headers(account["id"])
    )
    validate_error(resp_clock, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp_clock.status_code == 403


def test_customer_contact_ownership_scoping(api):
    """PRD §2.1: "When `X-User-Role` is `CustomerContact`, `X-User-ID` is the
    `id` of the acting `CustomerAccount`; ownership checks on any resource
    compare the resource's owning-account reference to `X-User-ID`, and a
    mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.2: "A `CustomerContact` accepting a design must own the account that
    owns the design's asset — otherwise `ERR_FORBIDDEN`".

    Design: Corner/rbac/customer_contact_ownership_scoping
    """
    acct_a = create_account(account_name="Own A")
    acct_b = create_account(account_name="Own B")
    asset_b = create_asset(acct_b["id"], asset_tag="CT-B4", asset_type="BOILER",
                           recirculation_rate_gpm=100, system_volume_gal=500)
    design_b = create_proposed_design(asset_b["id"])

    resp = api_client.accept_design(
        design_b["id"],
        {"expected_program_design_version": design_b["version"]},
        make_customer_contact_headers(acct_a["id"]),  # caller owns A, design belongs to B
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403

    after = validate_success(api_client.get_program_design(design_b["id"], CHEMIST))
    assert after["status"] == "PROPOSED"


def test_anonymous_missing_headers_rejected(api):
    """PRD §2.6 tier 1: "`X-User-ID` and `X-User-Role` must both be present and
    non-empty; failure is `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400). Applies to all endpoints." Tier 1 precedes tier 4 existence per
    "evaluated strictly in ascending priority order".

    Design: Corner/rbac/anonymous_missing_headers_rejected
    """
    resp = api_client.get_asset(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert resp.status_code == 400


def test_error_envelope_shape_on_any_failure(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." "The `error_id` is a unique,
    machine-readable string that identifies the specific error." "The `message`
    provides a human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape_on_any_failure
    """
    resp = api_client.get_product(NON_EXISTENT_UUID, CHEMIST)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str) and body["meta"]["api_request_id"]
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"].strip()


def test_existence_beats_state_for_bogus_path_id(api):
    """PRD §2.6: "Every request passes through a single validation pipeline of
    fifteen tiers, evaluated strictly in ascending priority order. The first
    tier whose check fails determines the error response; later tiers are never
    consulted for that request." Tier 4 (existence, `ERR_NOT_FOUND`) precedes
    tier 6 (transition legality, `ERR_INVALID_STATE`).

    Design: Corner/validations/existence_beats_state_for_bogus_path_id
    """
    resp = api_client.submit_delivery_order(NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404
