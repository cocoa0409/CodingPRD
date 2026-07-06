"""Quote lifecycle, entity-backed ownership (Technician / ClientContact),
optimistic concurrency on seat adjustments, and reverse-reachability listing."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_technician_headers,
    make_client_contact_headers,
    set_clock,
    create_client,
    create_contract,
    activate_contract,
    create_site,
    create_asset,
    assign_asset_to_contract,
    create_technician,
    create_ticket,
    assign_ticket,
    create_dispatch,
    create_quote,
    send_quote,
    create_seat_adjustment,
    setup_active_contract,
    setup_assigned_asset,
)


SM = "service_manager_headers"


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / quote_branch_and_revert_to_draft
# ---------------------------------------------------------------------------

def test_quote_send_then_request_revision_reverts_to_draft(api):
    """PRD §3.7: "An `AccountManager` sends a `DRAFT` quote — this requires the
    quote to be `DRAFT` (otherwise `ERR_INVALID_STATE`) and its `line_items`
    to be non-empty (otherwise `ERR_EMPTY_LINE_ITEMS`) — moving it `DRAFT` →
    `SENT`."
    PRD §3.7: "Requesting a revision requires the quote to be `SENT` (otherwise
    `ERR_INVALID_STATE`) and reverts it `SENT` → `DRAFT` so the account manager
    can revise its `line_items`."

    Design: Difficulty/non_linear_state_machine/quote_branch_and_revert_to_draft
    """
    client = create_client(company_name="Zeta", primary_contact_email="z@zeta.test")
    quote = create_quote(
        client["id"], "PROJECT",
        line_items=[{"description": "labor", "unit_price_cents": 100000, "qty": 1}],
        title="migration",
    )
    sent = send_quote(quote["id"])
    assert sent["status"] == "SENT"
    resp = api.request_quote_revision(
        quote["id"], make_client_contact_headers(client["id"]),
    )
    reverted = validate_success(resp)
    assert reverted["status"] == "DRAFT"


def test_quote_after_revert_can_be_sent_and_accepted(api):
    """PRD §3.7: "Accepting requires the quote to be `SENT` (otherwise
    `ERR_INVALID_STATE`) and the clock now to be strictly before `valid_until`"
    PRD §3.7: "moving it `SENT` → `ACCEPTED` only on success."

    Design: Difficulty/non_linear_state_machine/quote_branch_and_revert_to_draft
    """
    client = create_client(company_name="Zeta2", primary_contact_email="z2@zeta.test")
    quote = create_quote(
        client["id"], "PROJECT",
        line_items=[{"description": "labor", "unit_price_cents": 100000, "qty": 1}],
        title="migration",
    )
    send_quote(quote["id"])
    validate_success(api.request_quote_revision(
        quote["id"], make_client_contact_headers(client["id"]),
    ))
    # Second send is legal because the quote is DRAFT again.
    sent2 = validate_success(api.send_quote(quote["id"], TEST_USERS["account_manager_headers"]))
    assert sent2["status"] == "SENT"
    accepted = validate_success(api.accept_quote(
        quote["id"], make_client_contact_headers(client["id"]),
    ))
    assert accepted["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# Queue B: state_machines / quote_accept_from_draft_returns_invalid_state
# ---------------------------------------------------------------------------

def test_accept_draft_quote_returns_invalid_state(api):
    """PRD §3.7: "Accepting requires the quote to be `SENT` (otherwise
    `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/quote_accept_from_draft_returns_invalid_state
    """
    client = create_client(company_name="Eta", primary_contact_email="h@eta.test")
    quote = create_quote(
        client["id"], "PROJECT",
        line_items=[{"description": "w", "unit_price_cents": 1000, "qty": 1}],
        title="q",
    )
    resp = api.accept_quote(quote["id"], make_client_contact_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Queue B: state_machines / quote_accept_after_expiry_returns_quote_expired
# ---------------------------------------------------------------------------

def test_accept_expired_quote_returns_quote_expired(api):
    """PRD §3.7: "if now has reached or passed `valid_until` the quote is
    treated as expired and the accept is rejected with `ERR_QUOTE_EXPIRED`"

    Design: Corner/state_machines/quote_accept_after_expiry_returns_quote_expired
    """
    set_clock("2026-05-01T00:00:00Z")
    client = create_client(company_name="The", primary_contact_email="t@the.test")
    quote = create_quote(
        client["id"], "PROJECT",
        line_items=[{"description": "w", "unit_price_cents": 1000, "qty": 1}],
        title="q",
        valid_until="2026-05-02T00:00:00Z",
    )
    send_quote(quote["id"])
    set_clock("2026-05-03T00:00:00Z")
    resp = api.accept_quote(quote["id"], make_client_contact_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)


# ---------------------------------------------------------------------------
# Queue B: rbac / client_contact_ticket_for_foreign_client_denied
# ---------------------------------------------------------------------------

def test_client_contact_opening_ticket_for_foreign_client_returns_not_resource_owner(api):
    """PRD §2.1: "When `X-User-Role` is `ClientContact`, `X-User-ID` is the
    `id` of the acting `Client`. Ownership checks on any resource that references
    a client compare the resource's `client_id` to `X-User-ID`; a client contact
    reading or mutating another client's records is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/client_contact_ticket_for_foreign_client_denied
    """
    client_a = create_client(company_name="A", primary_contact_email="a@a.test")
    client_b = create_client(company_name="B", primary_contact_email="b@b.test")
    contract_b = create_contract(client_b["id"])
    activate_contract(contract_b["id"])
    resp = api.create_ticket(
        {"client_id": client_b["id"], "contract_id": contract_b["id"],
         "priority": "P3", "subject": "cross"},
        make_client_contact_headers(client_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


# ---------------------------------------------------------------------------
# Queue B: rbac / technician_complete_foreign_dispatch_denied
# ---------------------------------------------------------------------------

def test_technician_completing_foreign_dispatch_returns_not_resource_owner(api):
    """PRD §2.1: "When `X-User-Role` is `Technician`, `X-User-ID` is the `id`
    of the acting `Technician`. Ownership checks on a `Dispatch` compare the
    dispatch's `technician_id` to `X-User-ID`; a technician acting on patch
    or dispatch work they are not assigned to is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/technician_complete_foreign_dispatch_denied
    """
    client, contract = setup_active_contract(
        client_overrides={"company_name": "Phi",
                          "primary_contact_email": "f@phi.test"},
    )
    tech_x = create_technician(full_name="X", hourly_rate_cents=8000)
    tech_y = create_technician(full_name="Y", hourly_rate_cents=8000)
    ticket = create_ticket(client["id"], contract["id"], priority="P3", subject="z")
    ticket = assign_ticket(ticket["id"], tech_y["id"])
    dispatch = create_dispatch(
        ticket["id"], tech_y["id"], mode="REMOTE",
        scheduled_start="2026-05-01T02:00:00Z",
        scheduled_end="2026-05-01T03:00:00Z",
    )
    # Technician X (not the assigned technician) tries to complete tech_y's dispatch.
    resp = api.complete_dispatch(
        dispatch["id"], {"logged_minutes": 60},
        make_technician_headers(tech_x["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_complexity_layers / seat_adjustment_stale_contract_version_returns_412
# ---------------------------------------------------------------------------

def test_seat_adjustment_with_stale_expected_version_returns_stale_contract_version(api):
    """PRD §2.8: "The seat-adjustment create endpoint therefore requires a
    non-optional `expected_contract_version` field carrying the client's last
    observed `version` of the target `Contract`. If the contract's `version`
    has advanced since the client read it — because another writer has already
    adjusted seats or activated or terminated the contract — the submitted
    `expected_contract_version` will not equal the contract's current
    `version`, and the request is rejected with `ERR_STALE_CONTRACT_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/seat_adjustment_stale_contract_version_returns_412
    """
    client, contract = setup_active_contract()
    stale_version = contract["version"]
    # First adjustment succeeds with the current version and bumps it.
    create_seat_adjustment(
        contract["id"], delta=1,
        effective_at="2026-05-02T00:00:00Z",
        expected_contract_version=stale_version,
    )
    # Second attempt carrying the pre-bump version must fail.
    resp = api.create_seat_adjustment(
        contract["id"],
        {"delta": 1, "effective_at": "2026-05-03T00:00:00Z",
         "expected_contract_version": stale_version},
        TEST_USERS[SM],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION)


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_complexity_layers / seat_adjustment_correct_version_succeeds
# ---------------------------------------------------------------------------

def test_seat_adjustment_with_current_version_succeeds_and_records_seat_count_after(api):
    """PRD §3.2: "On success the contract's `seat_count` is increased by the
    `delta`, the resulting level is recorded on the event's read-only
    `seat_count_after`, `seats_available` is recomputed, and the contract's
    `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/seat_adjustment_correct_version_succeeds
    """
    client, contract = setup_active_contract(
        contract_overrides={"seat_count": 5},
    )
    resp = api.create_seat_adjustment(
        contract["id"],
        {"delta": 2, "effective_at": "2026-05-02T00:00:00Z",
         "expected_contract_version": contract["version"]},
        TEST_USERS[SM],
    )
    data = validate_success(resp, expected_status=201)
    assert data["seat_count_after"] == 7


# ---------------------------------------------------------------------------
# Queue B: endpoints / list_tickets_filtered_by_client_id
# ---------------------------------------------------------------------------

def test_list_tickets_filtered_by_client_id_returns_only_that_clients_tickets(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."
    PRD §4 endpoint row: `GET /tickets` "List tickets (filter by client_id,
    asset_id, contract_id, status)".

    Design: Corner/endpoints/list_tickets_filtered_by_client_id
    """
    from test_helpers import validate_paginated
    client, contract = setup_active_contract(
        client_overrides={"company_name": "Tau",
                          "primary_contact_email": "t@tau.test"},
    )
    create_ticket(client["id"], contract["id"], priority="P3", subject="one")
    create_ticket(client["id"], contract["id"], priority="P4", subject="two")
    resp = api.list_tickets(TEST_USERS["dispatcher_headers"],
                            params={"client_id": client["id"]})
    items, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    for t in items:
        assert t["client_id"] == client["id"]


# ---------------------------------------------------------------------------
# Queue B: endpoints / list_assets_filtered_by_contract_id
# ---------------------------------------------------------------------------

def test_list_assets_filtered_by_contract_id_returns_only_assigned_assets(api):
    """PRD §4 endpoint row: `GET /assets` "List assets (filter by client_id,
    site_id, contract_id, monitoring_status)".
    PRD §3.3: "On success the asset moves `UNMONITORED` → `ACTIVE`, its
    `contract_id` is set to the target"

    Design: Corner/endpoints/list_assets_filtered_by_contract_id
    """
    from test_helpers import validate_paginated
    client, site, contract, asset = setup_assigned_asset()
    resp = api.list_assets(TEST_USERS[SM], params={"contract_id": contract["id"]})
    items, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert items[0]["id"] == asset["id"]
    assert items[0]["monitoring_status"] == "ACTIVE"
