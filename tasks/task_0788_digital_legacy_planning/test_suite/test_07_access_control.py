"""Authentication, authorization, ownership scope, secure deputy access, request
validation, and list pagination."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    make_owner_headers, make_deputy_headers, ADMIN_HEADERS,
    set_clock, create_plan, create_subscription, create_vault_item, create_deputy,
    create_and_accept_deputy,
)


# --------------------------------------------------------------------------- #
# vaultitem_create_missing_required_title_returns_invalid_request  (Corner/entities)
# --------------------------------------------------------------------------- #
def test_create_vault_item_missing_title_rejected(api):
    """PRD 2.8: "Third, the request body and query are checked for well-formedness —
    required fields present, enum values within range, numeric amounts non-negative, and
    `allocation_pct` within the inclusive range from 0 to 100 — with any failure returning
    `ERR_VALIDATION`."
    PRD 3.2: "An owner adds a `VaultItem` by supplying its `plan_id`, its `kind` (one of
    `ACCOUNT`, `ASSET`, or `DOCUMENT`), a free-text `category`, a human `title`, and a
    `secret_ref` pointing at the encrypted payload."

    Design: Corner/entities/vaultitem_create_missing_required_title_returns_invalid_request
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    resp = api.create_vault_item(
        {"plan_id": plan_id, "kind": "DOCUMENT", "category": "will", "secret_ref": "vault://will"},
        make_owner_headers(plan_id))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


# --------------------------------------------------------------------------- #
# vaultitem_default_sensitivity_medium  (Corner/entities)
# --------------------------------------------------------------------------- #
def test_vault_item_defaults_sensitivity_to_medium(api):
    """PRD 3.2: "The owner may also set a `sensitivity` of `LOW`, `MEDIUM`, or `HIGH`,
    defaulting to `MEDIUM` when omitted."

    Design: Corner/entities/vaultitem_default_sensitivity_medium
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    item = create_vault_item(api, plan_id, kind="DOCUMENT", category="will", title="Will",
                             secret_ref="vault://will")
    data = validate_success(api.get_vault_item(item["id"], make_owner_headers(plan_id)), 200)
    assert data["sensitivity"] == "MEDIUM", f"expected MEDIUM, got {data['sensitivity']}"


# --------------------------------------------------------------------------- #
# plan_get_nonexistent_returns_not_found  (Corner/entities)
# --------------------------------------------------------------------------- #
def test_get_nonexistent_plan_returns_not_found(api):
    """PRD 2.8: "Fourth, existence is checked: every id in the path and every foreign key in
    the body must resolve to an existing resource, evaluated left to right, returning
    `ERR_NOT_FOUND`"

    Design: Corner/entities/plan_get_nonexistent_returns_not_found
    """
    resp = api.get_plan(NON_EXISTENT_UUID, ADMIN_HEADERS)
    # PRD 2.8 admits both the generic ERR_NOT_FOUND and the entity-specific
    # ERR_PLAN_NOT_FOUND ("used where a specific referenced resource is missing").
    validate_error_is_one_of(resp, [ApiErrorId.ERR_NOT_FOUND, ApiErrorId.ERR_PLAN_NOT_FOUND])


# --------------------------------------------------------------------------- #
# owner_cannot_create_item_on_other_plan_forbidden_scope  (Corner/validations)
# --------------------------------------------------------------------------- #
def test_owner_creating_item_on_other_plan_forbidden(api):
    """PRD 2.1: "Ownership checks on any resource that references a plan compare the
    resource's `plan_id` to `X-User-ID`; an owner acting on a resource whose `plan_id` does
    not equal their `X-User-ID` is rejected with `ERR_FORBIDDEN_SCOPE`."

    Design: Corner/validations/owner_cannot_create_item_on_other_plan_forbidden_scope
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan_a = create_plan(api, owner_full_name="Ada A", owner_email="a@x.com")["id"]
    plan_b = create_plan(api, owner_full_name="Bee B", owner_email="b@x.com")["id"]
    resp = api.create_vault_item(
        {"plan_id": plan_b, "kind": "DOCUMENT", "category": "will", "title": "Will",
         "secret_ref": "vault://will"}, make_owner_headers(plan_a))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SCOPE)


# --------------------------------------------------------------------------- #
# deputy_cannot_create_vault_item_unauthorized  (Corner/errors)
# --------------------------------------------------------------------------- #
def test_deputy_creating_vault_item_unauthorized(api):
    """PRD 2.1: "When the headers are well-formed but the acting role is not permitted to
    invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/errors/deputy_cannot_create_vault_item_unauthorized
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    # PRD 2.9: seat_limit is 0 without a subscription, so a seat-consuming deputy
    # would hit ERR_SEAT_LIMIT_REACHED. Give the plan a subscription first.
    create_subscription(api, plan_id, tier="PLUS")
    deputy = create_deputy(api, plan_id, deputy_role="EXECUTOR", access_scope=["ASSET"])
    resp = api.create_vault_item(
        {"plan_id": plan_id, "kind": "DOCUMENT", "category": "will", "title": "Will",
         "secret_ref": "vault://will"}, make_deputy_headers(deputy["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# --------------------------------------------------------------------------- #
# create_plan_missing_headers_returns_unauthenticated  (Corner/errors)
# --------------------------------------------------------------------------- #
def test_create_plan_without_auth_headers_rejected(api):
    """PRD 2.1: "A request that omits either header, or whose `X-User-Role` is not one of
    these three known roles, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/create_plan_missing_headers_returns_unauthenticated
    """
    resp = api.create_plan({"owner_full_name": "Ada Owner", "owner_email": "ada@x.com"}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# --------------------------------------------------------------------------- #
# deputy_read_unreleased_item_returns_access_not_released  (Corner/errors)
# --------------------------------------------------------------------------- #
def test_deputy_reading_unreleased_item_rejected(api):
    """PRD 2.10: "When the acting role is `Deputy`, a read of a vault item — whether
    fetching one item or listing items — is permitted only when all of the following hold
    for that item: its status is `RELEASED`, its `kind` is contained in the deputy's
    `access_scope`, and there exists a `GRANTED` release request filed by this deputy whose
    released scope covers the item's `kind`. A deputy read that fails any of these conditions
    is rejected with `ERR_ACCESS_NOT_RELEASED`."

    Design: Corner/errors/deputy_read_unreleased_item_returns_access_not_released
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    # PRD 2.9: seat_limit is 0 without a subscription, so a seat-consuming deputy
    # would hit ERR_SEAT_LIMIT_REACHED. Give the plan a subscription first.
    create_subscription(api, plan_id, tier="PLUS")
    deputy = create_and_accept_deputy(api, plan_id, deputy_role="VIEWER",
                                      access_scope=["DOCUMENT"])
    item = create_vault_item(api, plan_id, kind="DOCUMENT", category="will", title="Will",
                             secret_ref="vault://will")  # DRAFT, unreleased
    resp = api.get_vault_item(item["id"], make_deputy_headers(deputy["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCESS_NOT_RELEASED)


# --------------------------------------------------------------------------- #
# vault_items_list_pagination_shape  (Corner/endpoints)
# --------------------------------------------------------------------------- #
def test_vault_items_list_pagination_shape(api):
    """PRD 2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/vault_items_list_pagination_shape
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    create_vault_item(api, plan_id, kind="DOCUMENT", category="will", title="Will",
                      secret_ref="vault://will")
    create_vault_item(api, plan_id, kind="DOCUMENT", category="letters", title="Letters",
                      secret_ref="vault://letters")
    resp = api.list_vault_items(make_owner_headers(plan_id), params={"plan_id": plan_id})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"
