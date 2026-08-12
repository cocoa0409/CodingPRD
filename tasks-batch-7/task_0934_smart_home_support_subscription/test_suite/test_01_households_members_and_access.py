"""Households, members, account standing and the outermost access rules."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_household,
    assert_is_null,
    assert_same_instant,
    assert_success_envelope,
    claim,
    claim_device_payload,
    create_household_payload,
    create_ticket_payload,
    fetch_household,
    list_tickets,
    set_clock,
    setup_account,
    setup_account_with_catalog,
    validate_error,
    validate_success,
)


def test_household_registration_returns_active_status_and_zero_counters(api, admin_headers):
    """PRD 3.1: "the operator supplies a `name` of between 1 and 120 characters, a
    `region_code` and a `billing_email`, and the service creates the row with
    `account_status` `ACTIVE`, `entitled_device_count` 0 and `active_device_count` 0."
    PRD 2.4: "a `version` integer that begins at 1 when the row is created and
    increases by exactly 1 each time the row is mutated."

    Design: Corner/entities/household_creation_returns_declared_defaults_and_zero_counters
    """
    set_clock("2026-05-01T00:00:00Z")

    response = api.create_household(
        create_household_payload(
            name="Fresh House", region_code="NWA", billing_email="fresh@example.com"
        ),
        admin_headers,
    )
    data = validate_success(response, 201)

    assert_household(data)
    assert data["account_status"] == "ACTIVE"
    # Never suspended, so there is no suspension instant to report.
    assert_is_null(data, "suspended_at", "Household")
    assert data["entitled_device_count"] == 0
    assert data["active_device_count"] == 0
    assert data["version"] == 1
    assert_success_envelope(response.json(), "object")


def test_household_read_with_unknown_id_reports_household_not_found(api, admin_headers):
    """PRD 2.9 rung 5: "Every `Household` id named in the path or body exists —
    otherwise `ERR_HOUSEHOLD_NOT_FOUND`. Applies to every endpoint taking a
    `household_id`."

    Design: Corner/entities/household_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")

    response = api.get_household("00000000-0000-4000-8000-000000000000", admin_headers)
    validate_error(response, ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND.value, 404)


def test_household_member_read_with_unknown_id_reports_member_not_found(api, admin_headers):
    """PRD 2.1: "A header identity that resolves to no member row, to a deactivated
    member row, or to a member row whose `member_role` does not match the header
    role is rejected with `ERR_MEMBER_NOT_FOUND` (HTTP 404)."
    PRD 3.1: "Members are listed with an optional `household_id` filter alongside
    `limit` and `offset`, and any single member row may be read by id."

    Design: Corner/entities/household_member_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")

    response = api.get_household_member(
        "00000000-0000-4000-8000-000000000000", admin_headers
    )
    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, 404)


def test_request_with_no_role_header_is_unauthenticated(api, no_auth_headers):
    """PRD 2.1: "A request whose `X-User-Role` header is missing or blank, or whose
    value is not one of those six literal strings, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/request_without_an_x_user_role_header_returns_unauthenticated
    """
    set_clock("2026-05-01T00:00:00Z")

    # The request carries no X-User-Role header at all.
    response = api.create_household(
        create_household_payload(
            name="No Auth House", region_code="NWA", billing_email="noauth@example.com"
        ),
        no_auth_headers,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_member_role_may_not_claim_a_device(api):
    """PRD 2.9 rung 3: "The role is listed among the target endpoint's authorised roles
    — otherwise `ERR_FORBIDDEN_ROLE`. Applies to every endpoint."
    PRD 3.3: "Claiming a unit onto a household is an `Owner` or `PlatformAdmin` act
    and takes `household_id`, `catalog_entry_id`, `serial_number` and `purchase_date`."

    Design: Corner/rbac/member_cannot_claim_a_device
    """
    world = setup_account_with_catalog(
        "HUB",
        plan_kind="PRO",
        allow_overage=False,
        roles=("OWNER", "MEMBER"),
        name="Role House",
        email_prefix="rol",
    )

    response = api.claim_device(
        claim_device_payload(
            world["household"]["id"], world["catalog"]["id"], "HBX000001", "2026-04-01"
        ),
        world["member_headers"],
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    assert fetch_household(world["household"]["id"])["entitled_device_count"] == 0


def test_billing_admin_may_not_open_a_ticket(api):
    """PRD 2.9 rung 3: "The role is listed among the target endpoint's authorised roles
    — otherwise `ERR_FORBIDDEN_ROLE`. Applies to every endpoint."
    PRD 3.5: "A ticket is raised by an `Owner`, a `Member` or a `SupportAgent`."

    Design: Corner/rbac/billing_admin_cannot_open_a_ticket
    """
    world = setup_account(
        plan_kind="PRO",
        allow_overage=False,
        roles=("BILLING_ADMIN",),
        name="Bill House",
        email_prefix="bil",
    )

    response = api.create_ticket(
        create_ticket_payload(
            world["household"]["id"], severity="P2", summary="Billing wants a ticket"
        ),
        world["billing_headers"],
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    assert list_tickets(household_id=world["household"]["id"]) == []


def test_suspended_account_gate_pre_empts_the_device_cap_rule(api):
    """PRD 2.8: "If the `Household` that scopes the target row has `account_status`
    equal to `SUSPENDED`, the request is refused with `ERR_ACCOUNT_SUSPENDED`
    (HTTP 403)."
    PRD 2.9 rung 23: "Gate 1 — the household scoping the target row is `SUSPENDED`,
    giving `ERR_ACCOUNT_SUSPENDED`. Applies to every mutating endpoint except
    household registration, the account-status endpoint and the clock capability."
    PRD 3.1: "A platform operator may drive `account_status` from `ACTIVE` to
    `SUSPENDED`, which stamps `suspended_at` with the logical-clock instant and,
    from that moment, arms gate 1 for every subsequent mutating request scoped to
    the household."

    The claim would ALSO breach the 1-device entitlement cap at rung 50; the gate
    at rung 23 wins because rungs are evaluated in ascending priority order.

    Design: Corner/validations/suspended_household_gate_preempts_every_downstream_rule
    """
    world = setup_account_with_catalog(
        "HUB",
        plan_kind="PRO",
        plan_overrides={"included_device_count": 1},
        allow_overage=False,
        name="Gate House",
        email_prefix="gate",
    )
    claim(
        world["household"]["id"],
        world["catalog"]["id"],
        "HBX000001",
        world["owner_headers"],
    )
    validate_success(
        api.set_account_status(
            world["household"]["id"],
            {"account_status": "SUSPENDED"},
            TEST_USERS["platform_admin_headers"],
        )
    )

    response = api.claim_device(
        claim_device_payload(
            world["household"]["id"], world["catalog"]["id"], "HBX000002", "2026-04-01"
        ),
        world["owner_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_DEVICE_CAP_EXCEEDED.value

    household = fetch_household(world["household"]["id"])
    assert household["entitled_device_count"] == 1
    assert household["account_status"] == "SUSPENDED"
    # suspended_at is stamped with the logical-clock instant, compared as an instant.
    assert_same_instant(
        household["suspended_at"], "2026-05-01T00:00:00Z", "Household.suspended_at"
    )
