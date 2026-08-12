"""Authentication tiers, role authorization, and entity-backed ownership."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, build_user_headers,
    create_contract_payload,
    setup_client, setup_active_per_push, setup_storm_event, set_clock,
    setup_billable_visit, setup_issued_event_invoice,
    make_client_headers,
)

DISPATCH = TEST_USERS["ops_dispatcher_headers"]

_OBS = [("NOAA", "2026-12-10T07:30:00Z", 2.0), ("DTN", "2026-12-10T08:00:00Z", 2.1)]


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role name outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/roles/unknown_role_and_missing_user_id_return_unauthenticated
    """
    client = setup_client(name="Auth Co", credit_limit_cents=500_000)
    validate_error(api.get_client(client["id"],
                                  build_user_headers("someone", "Nobody")),
                   ApiErrorId.ERR_UNAUTHENTICATED)


def test_entity_backed_role_missing_user_id_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role name outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/roles/unknown_role_and_missing_user_id_return_unauthenticated
    """
    client = setup_client(name="Auth Co 2", credit_limit_cents=500_000)
    # ClientContact header without X-User-ID at all.
    validate_error(api.get_client(client["id"], {"X-User-Role": "ClientContact"}),
                   ApiErrorId.ERR_UNAUTHENTICATED)


def test_client_contact_cannot_create_contract(api):
    """PRD §2.1: "Beyond authentication, every operation is restricted to a designated list of roles (see §4); a caller whose role is not on that list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /contracts is authorized for OpsDispatcher only.

    Design: Corner/roles/client_contact_cannot_create_contract
    """
    client = setup_client(name="Role Co", credit_limit_cents=500_000)
    payload = create_contract_payload(client["id"], contract_type="PER_PUSH",
                                      per_push_rate_cents=45_000)
    validate_error(api.create_contract(payload, make_client_headers(client["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_client_cannot_read_foreign_invoice(api):
    """PRD §2.1: "When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting Client; ownership checks on any resource that references a Client compare the resource's `client_id`, or the client reachable through the resource's own site, contract, invoice, or claim chain, to `X-User-ID`. An entity-backed caller that touches a resource outside its ownership is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/roles/client_cannot_read_foreign_invoice
    """
    ctx = setup_active_per_push(client_name="Client A", trigger_depth_inches=1.0)
    other_client = setup_client(name="Client B")
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    setup_billable_visit(ctx, event, _OBS)
    invoice = setup_issued_event_invoice(ctx, event)

    validate_error(api.get_invoice(invoice["id"],
                                   make_client_headers(other_client["id"])),
                   ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    own = validate_success(
        api.get_invoice(invoice["id"], make_client_headers(ctx["client"]["id"])), 200)
    assert own["total_cents"] == 45_000
