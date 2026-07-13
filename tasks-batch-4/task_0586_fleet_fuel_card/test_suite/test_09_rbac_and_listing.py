"""Role-based access control, fleet ownership, and filtered list reads."""
from test_helpers import (
    ANALYST,
    MERCHANT,
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiErrorId,
    authorize_transaction_payload,
    create_fleet_account_payload,
    make_fleet_account,
    make_fleet_manager_headers,
    make_vehicle,
    setup_authorized_fills,
    setup_fueling_scenario,
    validate_error,
    validate_paginated,
)

ADMIN_HEADERS = TEST_USERS["program_admin_headers"]


def test_merchant_cannot_create_fleet_account(api):
    """PRD §2.1: "If the role is recognized but not permitted to invoke the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (403)."
    PRD §2.1: "`ProgramAdmin` is the platform operator. It creates fleet accounts,
    generates and files IFTA reports, drives the logical clock, and may read every
    resource in the system."

    Design: Corner/rbac/merchant_cannot_create_fleet_account_unauthorized
    """
    payload = create_fleet_account_payload(
        company_name="Bad Co", base_jurisdiction="CA", credit_limit_cents=500_000
    )

    resp = api.create_fleet_account(payload, MERCHANT)

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_fraud_analyst_cannot_authorize_a_purchase(api):
    """PRD §2.1: "If the role is recognized but not permitted to invoke the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (403)."
    PRD §2.1: "`Merchant` is the fuel-network point-of-sale terminal; it authorizes,
    captures, settles, and voids purchases."

    Design: Corner/rbac/fraud_analyst_cannot_authorize_transaction_unauthorized
    """
    scenario = setup_fueling_scenario(
        api, account_overrides={"company_name": "Role Co"},
        card_overrides={"last4": "0950"},
    )

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=10, unit_price_cents=400, odometer=10,
    )
    resp = api.authorize_transaction(payload, ANALYST)

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_fleet_manager_cannot_act_on_another_fleets_vehicle(api):
    """PRD §2.1: "When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of
    the acting `FleetAccount`; ownership checks on any resource that belongs to a
    fleet — directly through its `fleet_account_id`, or transitively through the
    card, vehicle, or driver it references — compare that owning account to
    `X-User-ID`."
    PRD §2.1: "A `FleetManager` acting on a resource outside its own account is
    rejected with `ERR_FORBIDDEN_FLEET` (403)."
    PRD §3.1: "A `FleetManager` may retire an `ACTIVE` or `OUT_OF_SERVICE` vehicle,
    moving it to the terminal `RETIRED` state; retiring a vehicle ends every `ACTIVE`
    card assignment bound to it (§3.3)."

    Design: Corner/rbac/fleet_manager_cannot_touch_other_fleet_forbidden
    """
    fleet_a = make_fleet_account(api, company_name="Fleet A", credit_limit_cents=500_000)
    fleet_b = make_fleet_account(api, company_name="Fleet B", credit_limit_cents=500_000)
    vehicle_a = make_vehicle(api, fleet_a["id"], plate="VQ")

    resp = api.retire_vehicle(vehicle_a["id"], make_fleet_manager_headers(fleet_b["id"]))

    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FLEET.value)


def test_request_without_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting principal, and `X-User-Role`, naming its operational capacity. If either
    header is missing, or `X-User-Role` is not one of the recognized roles, the
    request is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/unauthenticated_missing_headers
    """
    payload = create_fleet_account_payload(
        company_name="Anon Co", base_jurisdiction="CA", credit_limit_cents=500_000
    )

    resp = api.create_fleet_account(payload, NO_AUTH_HEADERS)

    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_transactions_filtered_by_card(api):
    """PRD §3.4: "A transaction can be fetched by a `Merchant`, `FleetManager`, or
    `ProgramAdmin`, and transactions can be listed and filtered by `card_id`,
    `vehicle_id`, `driver_id`, `jurisdiction`, and `posting_status`."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the envelope's `meta` object."

    Design: Corner/endpoints/transactions_filtered_by_card_reverse_reachability
    """
    scenario = setup_authorized_fills(
        api, [{"gallons": 10, "unit_price_cents": 400, "odometer": 10}],
        account_overrides={"company_name": "List Co"},
        card_overrides={"last4": "0800"},
    )
    card_id = scenario["card"]["id"]
    txn_id = scenario["transactions"][0]["id"]

    resp = api.list_transactions(scenario["fm"], params={"card_id": card_id})

    data, meta = validate_paginated(resp)
    assert [t["id"] for t in data] == [txn_id], "only this card's transaction is returned"
    assert all(t["card_id"] == card_id for t in data)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
