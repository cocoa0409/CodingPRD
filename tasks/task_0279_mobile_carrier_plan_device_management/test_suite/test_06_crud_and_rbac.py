"""Entity creation/read surface, list reverse-reachability, and role-based
access control.

Translates corner queue (B) entities, endpoints, and rbac instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_subscriber_headers,
    create_account_payload, create_line_payload,
    assert_account, assert_charge,
    setup_account_plan, setup_active_line,
    SAMPLE_MISSING_UUID,
)
import test_helpers as H

CA = TEST_USERS["carrier_agent_headers"]
BS = TEST_USERS["billing_system_headers"]


# ─── Queue B: entities corners ────────────────────────────────────────────

def test_create_account_returns_201_with_computed_defaults(api):
    """PRD §3.1: "On creation the account's `status` is `ACTIVE`, its
    `active_line_count` is 0, its `group_discount_pct` is 0.00, its
    `wallet_credit_cents` is 0, its `total_eip_outstanding_cents` is 0, and its
    `version` is 1."

    Design: Corner/entities/create_account_returns_201_with_computed_defaults
    """
    res = api.create_account(
        create_account_payload(holder_name="Zoe", holder_email="zoe@x.com",
                               billing_day_of_month=15), CA)
    acc = validate_success(res, 201)
    assert_account(acc)
    assert acc["status"] == "ACTIVE"
    assert acc["active_line_count"] == 0
    assert acc["group_discount_pct"] == 0.00
    assert acc["wallet_credit_cents"] == 0
    assert acc["version"] == 1


def test_create_account_missing_email_returns_validation(api):
    """PRD §2.4: "A request body that is missing a required field or supplies a
    field of the wrong type is rejected with `ERR_VALIDATION` (HTTP 422)." PRD
    §3.1: "An account is created by supplying the `holder_name`, the
    `holder_email` (which doubles as the login identity for the `Subscriber` who
    owns the account), and a `billing_day_of_month` that anchors the billing
    cycle and must be an integer from 1 through 28 inclusive."

    Design: Corner/entities/create_account_missing_required_field_returns_validation
    """
    res = api.create_account(
        {"holder_name": "NoEmail", "billing_day_of_month": 1}, CA)
    validate_error(res, "ERR_VALIDATION")


def test_get_account_not_found_returns_404(api):
    """PRD §2.4: "the first identifier that does not resolve to a stored entity
    produces `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    res = api.get_account(SAMPLE_MISSING_UUID, CA)
    validate_error(res, "ERR_NOT_FOUND")


def test_provisioned_line_is_pending_with_null_number(api):
    """PRD §3.2: "A newly provisioned line enters `status` `PENDING_ACTIVATION`
    with its `phone_number` held at null".

    Design: Corner/entities/line_id_is_system_minted_input_ignored
    """
    account, plan = setup_account_plan()
    res = api.create_line(
        create_line_payload(account["id"], plan["id"], account["version"],
                            sim_type="ESIM"), CA)
    line = validate_success(res, 201)
    assert line["status"] == "PENDING_ACTIVATION"
    assert line.get("phone_number") is None


def test_invalid_sim_type_enum_rejected(api):
    """PRD §3.2: "the `sim_type` it will use (either `PHYSICAL` or `ESIM`)". PRD
    §2.4: "A request body that is missing a required field or supplies a field of
    the wrong type is rejected with `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/plan_code_enum_and_sim_type_enum_rejected_on_invalid
    """
    account, plan = setup_account_plan()
    res = api.create_line(
        create_line_payload(account["id"], plan["id"], account["version"],
                            sim_type="TRIPLE"), CA)
    validate_error(res, "ERR_VALIDATION")


def test_charge_is_append_only_no_mutate_endpoint(api):
    """PRD §2.5: "`Charge` and `UsageRecord` carry only an `id` and a
    `created_at`. They have no `updated_at` and no `version`, because once
    written they are never modified."

    Design: Corner/entities/charge_immutable_event_no_version_field
    """
    res = api.list_charges(BS)
    charges = validate_success(res, 200)
    assert isinstance(charges, list)
    for c in charges:
        assert_charge(c)


# ─── Queue B: endpoints corners ───────────────────────────────────────────

def test_list_lines_filtered_by_account_id(api):
    """PRD §2.4: "Lines are discoverable by `account_id` or by `plan_id`". PRD
    §2.3: "Every list response carries the pagination bookkeeping in the
    envelope's `meta` object, specifically the fields `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/list_lines_filtered_by_account_id_returns_array
    """
    account, plan = setup_account_plan()
    l1 = H.provision_line(account["id"], plan["id"], sim_type="ESIM")
    l2 = H.provision_line(account["id"], plan["id"], sim_type="ESIM")

    data, meta = validate_paginated(api.list_lines(CA, params={"account_id": account["id"]}))
    ids = {row["id"] for row in data}
    assert l1["id"] in ids and l2["id"] in ids
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ─── Queue B: rbac corners ────────────────────────────────────────────────

def test_subscriber_cannot_provision_line(api):
    """PRD §4: the `POST /lines` endpoint authorizes only `CarrierAgent`. PRD
    §2.1: "A recognized but unauthorized role is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/subscriber_cannot_provision_line
    """
    account, plan = setup_account_plan()
    res = api.create_line(
        create_line_payload(account["id"], plan["id"], account["version"], sim_type="ESIM"),
        make_subscriber_headers(account["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_carrier_agent_cannot_close_cycle(api):
    """PRD §4: `POST /billing-cycles/{cycleId}/close` authorizes only
    `BillingSystem`. PRD §2.1: "A recognized but unauthorized role is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/carrier_agent_cannot_close_cycle
    """
    account, plan = setup_account_plan()
    H.set_clock("2026-06-01T00:00:00Z")
    cycle = H.create_billing_cycle(account["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    H.set_clock("2026-07-01T00:00:00Z")

    res = api.close_billing_cycle(cycle["id"], CA)
    validate_error(res, "ERR_FORBIDDEN")


def test_subscriber_cannot_cancel_other_accounts_line(api):
    """PRD §2.1: "A subscriber who acts on an account or line they do not own —
    for instance by cancelling a line, cancelling an add-on, or opening a port
    request against another account's line — is rejected with
    `ERR_NOT_ACCOUNT_OWNER` (HTTP 403)."

    Design: Corner/rbac/subscriber_cannot_cancel_other_accounts_line
    """
    account_a, plan, line = setup_active_line(sim_type="PHYSICAL")
    account_b = H.create_account()

    res = api.cancel_line(line["id"], make_subscriber_headers(account_b["id"]))
    validate_error(res, "ERR_NOT_ACCOUNT_OWNER")


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a
    role the system recognizes, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). This authentication check runs before any
    other validation."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    account = H.create_account()
    res = api.get_account(account["id"], headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")
