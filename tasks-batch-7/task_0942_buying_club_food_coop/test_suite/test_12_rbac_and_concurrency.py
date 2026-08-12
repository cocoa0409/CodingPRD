"""Authentication, role authorisation, ownership and the four
optimistic-concurrency tokens."""

from test_helpers import (
    ApiErrorId,
    FINANCE_PREPARER_HEADERS,
    TEST_USERS,
    build_catalog,
    build_user_headers,
    canonical_world,
    capture_aggregates,
    create_credit_grant_payload,
    create_drop_reconciliation_payload,
    create_member_order_payload,
    create_order_line_payload,
    create_receipt_line_payload,
    create_volunteer_shift_payload,
    get_success_data,
    make_coordinator_headers,
    make_member_headers,
    member_version,
    open_cycle,
    open_drop_run,
    route_run_version,
    salt_world,
    set_clock,
    tier_change_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


# ---------------------------------------------------------- authentication --
def test_a_request_without_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint, read or write, must carry two
    headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the
    capacity in which they are acting. If either header is missing or empty, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/a_request_without_auth_headers_returns_unauthenticated
    """
    w = build_catalog(api, items=())
    open_cycle(api, w)

    validate_error(
        api.get_cycle(w.cycle_id, {"Content-Type": "application/json"}),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


def test_an_unrecognised_role_header_returns_unauthenticated(api):
    """PRD §2.1: "The same code and status are returned when `X-User-Role` carries
    a string that is not one of the five roles this platform recognises."
    PRD §2.9: "**Rung 2** — `X-User-Role` names one of the five declared roles.
    Applies to every endpoint. Failure: `ERR_UNAUTHENTICATED`, HTTP 401."

    Design: Corner/rbac/an_unrecognised_role_header_returns_unauthenticated
    """
    w = build_catalog(api, items=())
    open_cycle(api, w)

    body = validate_error(
        api.get_cycle(w.cycle_id, build_user_headers("who-1", "Auditor")),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value


def test_a_member_cannot_lock_a_cycle_and_receives_unauthorized(api):
    """PRD §2.1: "When the acting role is not listed among the roles the endpoint
    admits, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.9: "**Rung 3** — the acting role appears in the endpoint's authorised
    role list. Applies to every endpoint. Failure: `ERR_UNAUTHORIZED`, HTTP 403."

    Design: Corner/rbac/a_member_cannot_lock_a_cycle_and_receives_unauthorized
    """
    w = salt_world(api)
    set_clock(api, "2026-05-25T00:00:00Z")

    validate_error(
        api.lock_cycle(w.cycle_id, make_member_headers(w.mara_id)),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    assert validate_success(api.get_cycle(w.cycle_id, ADMIN))["status"] == "OPEN"
    assert (
        validate_success(api.get_order_line(w.lines["mara_salt"], ADMIN))["status"]
        == "REQUESTED"
    )


# ------------------------------------------------------------- ownership ----
def test_a_member_cannot_add_a_line_to_another_members_order(api):
    """PRD §2.1: "A `Member` reaching a member order, order line or substitution
    offer that belongs to someone else is refused with `ERR_NOT_ORDER_OWNER` (HTTP
    403)."
    PRD §2.9: "**Rung 26** — when the acting role is `Member`, `X-User-ID` equals
    the `member_id` of the member order the target resolves to."

    Design: Corner/rbac/a_member_cannot_add_a_line_to_another_members_order
    """
    w = build_catalog(api, items=("oat",))
    open_cycle(api, w)
    open_drop_run(api, w)
    order = get_success_data(
        api.create_member_order(
            create_member_order_payload(w.mara_id, w.drop_run_id),
            make_member_headers(w.mara_id),
        )
    )

    body = validate_error(
        api.create_order_line(
            create_order_line_payload(order["id"], w.items["oat"], 5, order["version"]),
            make_member_headers(w.ben_id),
        ),
        ApiErrorId.ERR_NOT_ORDER_OWNER.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_STALE_VERSION.value

    _, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"member_order_id": order["id"]})
    )
    assert meta["total_count"] == 0


def test_a_coordinator_downgraded_below_tier_rank_two_is_gated_out_of_their_drop(api):
    """PRD §3.1: "When the new `tier_rank` falls below 2 and this member
    coordinates at least one drop point, every coordinator action on that drop point's
    drop runs is thereafter refused by the coordinator gate at rung 11 with
    `ERR_COORDINATOR_INELIGIBLE`."
    PRD §2.9: "**Rung 11 — COORDINATOR GATE.** When the acting role is
    `DropCoordinator`, that member's `tier_rank` is at least 2. It pre-empts every
    coordinator-scoped rung below it, including the coordinator ownership check at rung
    27."

    Design: Corner/rbac/a_coordinator_downgraded_below_tier_rank_two_is_gated_out_of_their_drop
    """
    w = build_catalog(api, items=())
    open_cycle(api, w)
    open_drop_run(api, w)

    get_success_data(
        api.change_tier(
            w.cora_id,
            tier_change_payload("BASIC", 0, member_version(api, w, w.cora_id)),
            ADMIN,
        )
    )

    body = validate_error(
        api.create_volunteer_shift(
            create_volunteer_shift_payload(w.drop_run_id, w.cora_id, 4.0),
            make_coordinator_headers(w.cora_id),
        ),
        ApiErrorId.ERR_COORDINATOR_INELIGIBLE.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_NOT_DROP_COORDINATOR.value

    cora = validate_success(api.get_member(w.cora_id, ADMIN))
    assert cora["tier"] == "BASIC"
    assert cora["tier_rank"] == 1
    assert cora["is_coordinator"] is True

    _, meta = validate_paginated(
        api.list_volunteer_shifts(ADMIN, params={"drop_run_id": w.drop_run_id})
    )
    assert meta["total_count"] == 0


def test_a_coordinator_of_a_different_drop_cannot_act_on_this_one(api):
    """PRD §2.1: "A `DropCoordinator` reaching a drop run whose
    `coordinator_member_id` is not their `X-User-ID` is refused with
    `ERR_NOT_DROP_COORDINATOR` (HTTP 403)."
    PRD §2.9: "**Rung 27** — when the acting role is `DropCoordinator`, `X-User-ID`
    equals the `coordinator_member_id` of the drop run the target resolves to. Applies
    to merging a drop run, rolling one forward, logging a volunteer shift, and
    verifying or rejecting a shift. Failure: `ERR_NOT_DROP_COORDINATOR`, HTTP 403."

    Design: Corner/rbac/a_coordinator_of_a_different_drop_cannot_act_on_this_one
    """
    w = build_catalog(api, items=())
    open_cycle(api, w)
    open_drop_run(api, w)

    body = validate_error(
        api.create_volunteer_shift(
            create_volunteer_shift_payload(w.drop_run_id, w.mara_id, 4.0),
            make_coordinator_headers(w.mara_id),
        ),
        ApiErrorId.ERR_NOT_DROP_COORDINATOR.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_COORDINATOR_INELIGIBLE.value

    assert validate_success(api.get_member(w.mara_id, ADMIN))["tier_rank"] == 2
    _, meta = validate_paginated(
        api.list_volunteer_shifts(ADMIN, params={"drop_run_id": w.drop_run_id})
    )
    assert meta["total_count"] == 0


# ------------------------------------------------- optimistic concurrency ---
def test_a_stale_expected_member_order_version_on_line_create_is_rejected(api):
    """PRD §2.10: "`POST /order-lines` requires `expected_member_order_version`,
    carrying the client's last observed `version` of the parent `MemberOrder`. Because
    that order's `version` advances on every line create, line cancel and quantity
    change, a request whose `expected_member_order_version` no longer equals the order's
    stored `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client
    cannot add a second line on top of a picture it never saw."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_member_order_version_on_line_create_is_rejected
    """
    w = build_catalog(api, items=("salt", "oat"), include_ben=False)
    open_cycle(api, w)
    open_drop_run(api, w)
    headers = make_member_headers(w.mara_id)
    order = get_success_data(
        api.create_member_order(
            create_member_order_payload(w.mara_id, w.drop_run_id), headers
        )
    )
    stale_version = order["version"]
    get_success_data(
        api.create_order_line(
            create_order_line_payload(order["id"], w.items["salt"], 5, stale_version),
            headers,
        )
    )

    validate_error(
        api.create_order_line(
            create_order_line_payload(order["id"], w.items["oat"], 4, stale_version),
            headers,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )

    _, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"member_order_id": order["id"]})
    )
    assert meta["total_count"] == 1
    assert validate_success(api.get_drop_run(w.drop_run_id, ADMIN))["subtotal_cents"] == 5250


def test_a_stale_expected_route_run_version_on_a_receipt_is_rejected(api):
    """PRD §2.10: "`POST /receipt-lines` requires `expected_route_run_version`,
    carrying the client's last observed `version` of the parent `RouteRun`. Every
    receipt line advances the run's `version` through the allocation cascade, so a stale
    `expected_route_run_version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_route_run_version_on_a_receipt_is_rejected
    """
    w = canonical_world(api, "aggregates")
    stale_version = route_run_version(api, w, w.route_run_id)

    get_success_data(
        api.create_receipt_line(
            create_receipt_line_payload(
                w.route_run_id, w.aggregates["oat"], 2, stale_version
            ),
            WAREHOUSE,
        )
    )

    validate_error(
        api.create_receipt_line(
            create_receipt_line_payload(
                w.route_run_id, w.aggregates["berry"], 2, stale_version
            ),
            WAREHOUSE,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )

    assert (
        validate_success(api.get_case_aggregate(w.aggregates["berry"], ADMIN))["units_received"]
        == 0
    )
    assert (
        validate_success(api.get_order_line(w.lines["mara_berry"], ADMIN))["allocated_units"]
        == 0
    )
    _, meta = validate_paginated(
        api.list_receipt_lines(ADMIN, params={"route_run_id": w.route_run_id})
    )
    assert meta["total_count"] == 1


def test_a_stale_expected_drop_run_version_on_a_reconciliation_draft_is_rejected(api):
    """PRD §2.10: "`POST /drop-reconciliations` requires
    `expected_drop_run_version`, carrying the client's last observed `version` of the
    parent `DropRun`. Drafting a reconciliation legitimately supersedes and voids any
    existing non-posted draft, so nothing else would stop a duplicate; the guard is the
    drop run's `version`, which advances whenever a refund, a verified shift or a further
    receipt changes the numbers being reconciled. A mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_drop_run_version_on_a_reconciliation_draft_is_rejected
    """
    w = canonical_world(api, "delivered")

    validate_error(
        api.create_drop_reconciliation(
            create_drop_reconciliation_payload(w.drop_run_id, 1),
            FINANCE_PREPARER_HEADERS,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )

    _, meta = validate_paginated(
        api.list_drop_reconciliations(
            FINANCE_PREPARER_HEADERS, params={"drop_run_id": w.drop_run_id}
        )
    )
    assert meta["total_count"] == 0


def test_a_stale_expected_member_version_on_a_credit_grant_is_rejected(api):
    """PRD §2.10: "`POST /credit-grants` requires `expected_member_version`,
    carrying the client's last observed `version` of the parent `Member`. The member's
    `version` advances on every dues payment, tier change and credit-expiry sweep, so a
    stale `expected_member_version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.1: "Minting a grant runs the sweep first, then creates the grant, then
    raises the member's `credit_balance_cents`, and bumps the member's `version` — which
    is why the mint carries `expected_member_version` and why two clients cannot both
    mint against the same observed member state."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_member_version_on_a_credit_grant_is_rejected
    """
    w = build_catalog(api, items=())
    stale_version = member_version(api, w, w.mara_id)

    get_success_data(
        api.create_credit_grant(
            create_credit_grant_payload(
                w.mara_id, 3000, "2026-12-01T00:00:00Z", stale_version
            ),
            ADMIN,
        )
    )

    validate_error(
        api.create_credit_grant(
            create_credit_grant_payload(
                w.mara_id, 4000, "2026-12-01T00:00:00Z", stale_version
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )

    _, meta = validate_paginated(
        api.list_credit_grants(ADMIN, params={"member_id": w.mara_id})
    )
    assert meta["total_count"] == 1
    assert validate_success(api.get_member(w.mara_id, ADMIN))["credit_balance_cents"] == 3000
