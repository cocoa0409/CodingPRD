"""Client creation, contract lifecycle, and the client-offboard cascade."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    api_client,
    NON_EXISTENT_UUID,
    set_clock,
    create_client,
    create_site,
    create_contract,
    activate_contract,
    terminate_contract,
    offboard_client,
    setup_active_contract,
    setup_full_offboard_precondition,
    create_client_payload,
    create_contract_payload,
    build_user_headers,
)


SM = "service_manager_headers"


# ---------------------------------------------------------------------------
# Queue B: entities / client_create_returns_all_fields_and_defaults
# ---------------------------------------------------------------------------

def test_client_create_returns_active_status_and_full_available_credit(api):
    """PRD §3.1: "A new client opens in `status` `ACTIVE`, and its read-only
    `credit_available_cents` is initialized to equal `credit_limit_cents`."

    Design: Corner/entities/client_create_returns_all_fields_and_defaults
    """
    resp = api.create_client(
        {"company_name": "Acme", "primary_contact_email": "a@acme.test",
         "credit_limit_cents": 250000},
        TEST_USERS[SM],
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["credit_available_cents"] == 250000
    assert data["credit_limit_cents"] == 250000
    assert data["id"], "id must be present"


# ---------------------------------------------------------------------------
# Queue B: entities / client_missing_required_field_returns_invalid_request
# ---------------------------------------------------------------------------

def test_client_create_missing_company_name_returns_validation_error(api):
    """PRD §3.1: "A `ServiceManager` registers an SMB customer by supplying
    a `company_name` and a `primary_contact_email`, and optionally a
    `credit_limit_cents`"
    PRD §2.7: "Malformed bodies or missing required fields surface as
    `ERR_VALIDATION` (HTTP 400)"

    Design: Corner/entities/client_missing_required_field_returns_invalid_request
    """
    resp = api.create_client(
        {"primary_contact_email": "a@acme.test"},
        TEST_USERS[SM],
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


# ---------------------------------------------------------------------------
# Queue B: entities / contract_invalid_service_tier_enum_returns_invalid_enum
# ---------------------------------------------------------------------------

def test_contract_create_invalid_service_tier_enum_returns_invalid_enum(api):
    """PRD §3.2: "a `service_tier` of `BRONZE`, `SILVER`, or `GOLD`"
    PRD §2.7: "an enum field carrying a value outside its declared set surfaces
    as `ERR_INVALID_ENUM` (HTTP 400)"

    Design: Corner/entities/contract_invalid_service_tier_enum_returns_invalid_enum
    """
    client = create_client(company_name="Beta", primary_contact_email="b@beta.test")
    resp = api.create_contract(
        {"client_id": client["id"], "service_tier": "PLATINUM",
         "seat_count": 5, "per_seat_rate_cents": 5000},
        TEST_USERS[SM],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


# ---------------------------------------------------------------------------
# Queue B: entities / asset_not_found_returns_404
# ---------------------------------------------------------------------------

def test_get_asset_not_found_returns_404(api):
    """PRD §2.7: "every resource identifier named in the path or body must exist,
    validated left-to-right, so the first missing identifier yields the not-found
    error for its own type (`ERR_CLIENT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
    `ERR_TECHNICIAN_NOT_FOUND`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_ASSET_NOT_FOUND`,"

    Note: the quoted list continues; the point of interest here is
    ERR_ASSET_NOT_FOUND / 404 for an unknown asset id.

    Design: Corner/entities/asset_not_found_returns_404
    """
    resp = api.get_asset(NON_EXISTENT_UUID, TEST_USERS[SM])
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_FOUND)


# ---------------------------------------------------------------------------
# Queue B: validations / missing_auth_context_returns_401
# ---------------------------------------------------------------------------

def test_missing_x_user_role_header_returns_missing_auth_context(api):
    """PRD §2.1: "If either header is missing or `X-User-Role` does not name
    a role the system recognizes, the request is rejected with
    `ERR_MISSING_AUTH_CONTEXT` (HTTP 401)."

    Design: Corner/validations/missing_auth_context_returns_401
    """
    # Fabricate headers WITHOUT X-User-Role.
    resp = api.create_client(
        {"company_name": "NoAuth", "primary_contact_email": "n@x.test"},
        {"X-User-ID": "someone"},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT)


# ---------------------------------------------------------------------------
# Queue B: validations / forbidden_role_on_activate_returns_403
# ---------------------------------------------------------------------------

def test_dispatcher_activating_contract_returns_forbidden_role(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4 endpoint table lists `POST /contracts/{id}/activate` as authorized
    for `ServiceManager` only.

    Design: Corner/validations/forbidden_role_on_activate_returns_403
    """
    client = create_client(company_name="Lam", primary_contact_email="l@lam.test")
    contract = create_contract(client["id"])
    resp = api.activate_contract(contract["id"], TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ---------------------------------------------------------------------------
# Queue B: state_machines / contract_activate_from_terminated_returns_invalid_state
# ---------------------------------------------------------------------------

def test_activate_terminated_contract_returns_invalid_state(api):
    """PRD §3.2: "A contract can only be activated from `DRAFT`; activating one
    that is not `DRAFT` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/contract_activate_from_terminated_returns_invalid_state
    """
    client, contract = setup_active_contract()
    terminate_contract(contract["id"])
    resp = api.activate_contract(contract["id"], TEST_USERS[SM])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Queue B: consistency_model / seats_available_visible_in_same_create_response
# ---------------------------------------------------------------------------

def test_contract_create_returns_seats_available_equal_to_seat_count(api):
    """PRD §3.2: "A fresh contract opens in `DRAFT`, with its read-only
    `seats_available` initialized to `seat_count` and its
    `period_ticket_minutes` at 0."

    Design: Corner/consistency_model/seats_available_visible_in_same_create_response
    """
    client = create_client(company_name="Ome", primary_contact_email="o@ome.test")
    resp = api.create_contract(
        {"client_id": client["id"], "service_tier": "GOLD",
         "seat_count": 10, "per_seat_rate_cents": 5000},
        TEST_USERS[SM],
    )
    data = validate_success(resp, expected_status=201)
    assert data["seats_available"] == 10
    assert data["status"] == "DRAFT"
    assert data["period_ticket_minutes"] == 0


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / client_offboard_depth3_contract_asset_patch_ticket
# ---------------------------------------------------------------------------

def test_client_offboard_cascades_to_contract_asset_patchjob_and_ticket(api):
    """PRD §2.6: "The deepest cascade begins when a client is offboarded.
    Offboarding moves the client's `status` from `ACTIVE` to `OFFBOARDED` and
    increments the client's `version`. Every one of that client's contracts
    currently in `ACTIVE` is then terminated exactly as if terminated directly
    — moving `ACTIVE` → `TERMINATED`. Terminating a contract in turn retires
    every `Asset` it covers whose `monitoring_status` is `ACTIVE`, moving that
    asset `ACTIVE` → `RETIRED`. Retiring an asset cascades once more: each of
    that asset's patch jobs still in `SCHEDULED` moves `SCHEDULED` →
    `CANCELLED`, and each of the asset's tickets in `NEW` or `IN_PROGRESS`
    moves to `CANCELLED`."

    Design: Difficulty/transitive_cascade/client_offboard_depth3_contract_asset_patch_ticket
    """
    ctx = setup_full_offboard_precondition()

    offboarded_client = offboard_client(ctx["client"]["id"])
    assert offboarded_client["status"] == "OFFBOARDED"

    # link1: contract → TERMINATED
    contract_after = validate_success(
        api.get_contract(ctx["contract"]["id"], TEST_USERS[SM])
    )
    assert contract_after["status"] == "TERMINATED", contract_after

    # link2: asset → RETIRED
    asset_after = validate_success(
        api.get_asset(ctx["asset"]["id"], TEST_USERS[SM])
    )
    assert asset_after["monitoring_status"] == "RETIRED", asset_after

    # link3a: SCHEDULED patch job → CANCELLED (via asset retire)
    patch_jobs = validate_success(
        api.list_patch_jobs(ctx["asset"]["id"], TEST_USERS[SM])
    )
    # The patch job we created should now be CANCELLED.
    pj_ids = {pj["id"]: pj for pj in patch_jobs}
    assert ctx["patch_job"]["id"] in pj_ids
    assert pj_ids[ctx["patch_job"]["id"]]["status"] == "CANCELLED"

    # link3b: NEW ticket referencing the asset → CANCELLED
    ticket_after = validate_success(
        api.get_ticket(ctx["ticket"]["id"], TEST_USERS[SM])
    )
    assert ticket_after["status"] == "CANCELLED"


def test_client_offboard_status_becomes_offboarded_and_version_increments(api):
    """PRD §2.6: "Offboarding moves the client's `status` from `ACTIVE` to
    `OFFBOARDED` and increments the client's `version`."

    Design: Difficulty/transitive_cascade/client_offboard_depth3_contract_asset_patch_ticket
    """
    client = create_client(company_name="Nova", primary_contact_email="n@nova.test")
    v_before = client["version"]
    offboarded = offboard_client(client["id"])
    assert offboarded["status"] == "OFFBOARDED"
    assert offboarded["version"] > v_before, (
        f"expected version > {v_before}, got {offboarded['version']}"
    )
