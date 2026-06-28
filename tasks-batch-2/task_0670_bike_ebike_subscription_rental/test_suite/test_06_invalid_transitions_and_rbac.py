"""Invalid state transitions, terminal lockdown, and role-based access control.

Covers activation/cancel/close from a wrong state, closed-ticket terminal lockdown, and
RBAC: forbidden operations, FieldTech-exclusive inspect, entity-backed ownership, and
unauthenticated access.
"""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    ApiErrorId,
    make_subscriber_headers,
    make_field_tech_headers,
    make_ops_admin_headers,
    make_anonymous_headers,
    make_unknown_role_headers,
    create_bike_model_payload,
    inspect_payload,
)
from test_helpers.fixtures import (
    set_clock, create_model, add_bikes, create_account, read_model_version,
    reserve, schedule_and_complete_initial_delivery, activate,
)

OPS = make_ops_admin_headers()
TECH = make_field_tech_headers()
ANON = make_anonymous_headers()


# ===========================================================================
# Corner/state_machines/activate_from_reserved_returns_invalid_state
# ===========================================================================
def test_activate_reserved_rental_returns_invalid_state(api):
    """PRD §3.4: "Activation requires the rental to be DELIVERED".
    PRD §3.1: "Attempting to retire a bike that is not AVAILABLE is an undefined
    transition and is rejected with ERR_INVALID_STATE (HTTP 409)."

    Activating a still-RESERVED rental (no INITIAL delivery completed) -> ERR_INVALID_STATE.

    Design: Corner/state_machines/activate_from_reserved_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    resp = api_client.activate_rental(rental["id"], make_subscriber_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Corner/state_machines/cancel_active_rental_returns_invalid_state
# ===========================================================================
def test_cancel_active_rental_returns_invalid_state(api):
    """PRD §3.3: "A Subscriber may cancel a reservation while it is still RESERVED".

    Cancel is defined only from RESERVED; cancelling an ACTIVE rental -> ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_active_rental_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    resp = api_client.cancel_rental(rental["id"], make_subscriber_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Corner/state_machines/close_unreviewed_claim_returns_invalid_state
# ===========================================================================
def test_close_filed_claim_returns_invalid_state(api):
    """PRD §3.10: "Both APPROVED and DENIED claims are later closed to CLOSED."

    Closing a FILED (not yet APPROVED/DENIED) claim -> ERR_INVALID_STATE, since close is
    only defined from APPROVED or DENIED.

    Design: Corner/state_machines/close_unreviewed_claim_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    claim = get_success_data(api_client.create_coverage_claim(
        {"rental_id": rental["id"], "claim_type": "DAMAGE",
         "incident_clock": "2026-06-02T00:00:00Z", "claimed_amount_cents": 5000}, sub))
    resp = api_client.close_coverage_claim(claim["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Corner/state_machines/closed_ticket_terminal_lockdown
# ===========================================================================
def test_closed_ticket_terminal_lockdown(api):
    """PRD §3.5: "A ticket's status runs through OPEN, IN_PROGRESS, RESOLVED, REOPENED,
    and CLOSED, beginning at OPEN, with CLOSED terminal."

    Starting a CLOSED ticket again -> ERR_INVALID_STATE (CLOSED is terminal).

    Design: Corner/state_machines/closed_ticket_terminal_lockdown
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    ticket = get_success_data(api_client.create_service_ticket(
        {"rental_id": rental["id"], "issue_type": "FLAT_TIRE", "severity": "MINOR",
         "description": "flat"}, sub))
    get_success_data(api_client.start_service_ticket(ticket["id"], TECH))
    get_success_data(api_client.resolve_service_ticket(
        ticket["id"], {"resolution_note": "patched"}, TECH))
    get_success_data(api_client.close_service_ticket(ticket["id"], TECH))
    resp = api_client.start_service_ticket(ticket["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Corner/rbac/subscriber_cannot_create_bike_model
# ===========================================================================
def test_subscriber_cannot_create_bike_model(api):
    """PRD §2.1: "When the headers are present and valid but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    POST /bike-models is OpsAdmin-exclusive; a Subscriber call -> ERR_FORBIDDEN_ROLE 403.

    Design: Corner/rbac/subscriber_cannot_create_bike_model
    """
    account = create_account(rental_cap=1)
    resp = api_client.create_bike_model(
        create_bike_model_payload(name="Sneaky"), make_subscriber_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ===========================================================================
# Corner/rbac/subscriber_cannot_inspect_return
# ===========================================================================
def test_subscriber_cannot_inspect_return(api):
    """PRD §2.1: "When the headers are present and valid but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    POST /rentals/{id}/inspect is a FieldTech action; a Subscriber call ->
    ERR_FORBIDDEN_ROLE 403.

    Design: Corner/rbac/subscriber_cannot_inspect_return
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(deposit_cents=20000, fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-06-30T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.request_return(rental["id"], {"return_address": "1 A St"}, sub))
    resp = api_client.inspect_rental(rental["id"], inspect_payload(), sub)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ===========================================================================
# Corner/rbac/subscriber_cannot_act_on_other_accounts_rental
# ===========================================================================
def test_subscriber_cannot_act_on_other_accounts_rental(api):
    """PRD §2.1: "a Subscriber may act on a RentalAgreement only when the agreement's
    account_id equals X-User-ID, and acting on another account's rental yields
    ERR_FORBIDDEN_ROLE."

    Account A1 holds an ACTIVE rental; A2 (different id) requesting its return ->
    ERR_FORBIDDEN_ROLE 403.

    Design: Corner/rbac/subscriber_cannot_act_on_other_accounts_rental
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    a1 = create_account(display_name="A1", email="a1@x.com", rental_cap=1)
    a2 = create_account(display_name="A2", email="a2@x.com", rental_cap=1)
    mv = read_model_version(model["id"], a1["id"])
    rental = reserve(a1["id"], model["id"], mv)
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], a1["id"])
    resp = api_client.request_return(
        rental["id"], {"return_address": "1 A St"}, make_subscriber_headers(a2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ===========================================================================
# Corner/rbac/missing_auth_header_returns_unauthenticated
# ===========================================================================
def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing on an authenticated endpoint, or if
    X-User-Role is not one of the recognized roles, the request is rejected with
    ERR_UNAUTHENTICATED (HTTP 401)."

    GET /rentals/{id} with an unrecognized X-User-Role -> ERR_UNAUTHENTICATED 401.

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    resp = api_client.get_rental(rental["id"], make_unknown_role_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
